"""SkyRC MC5000 support.

The MC5000 uses a different BLE protocol from the MC3000: variable-length frames
``0F | LEN | CMD | payload | SUM`` where ``LEN = len(payload) + 2`` and
``SUM = (CMD + sum(payload)) & 0xFF``. Channels are addressed with a bitmask
(channel 0 = 0x01 ... channel 3 = 0x08). Full protocol notes:
https://github.com/fisherbln/skyrc-mc5000/blob/main/PROTOCOL.md
"""

from __future__ import annotations

import asyncio
import logging

from bleak.backends.device import BLEDevice
from bleak.backends.service import BleakGATTCharacteristic
from bleak.exc import BleakError

from .const import MC3000_CHANNEL_COUNT, MC3000_CHARACTERISTIC_UUID
from .device import SkyRcDevice
from .models import (
    MC5000_MAX_CHARGE_VOLTAGE,
    Mc5000BatteryType,
    Mc5000ChannelData,
    Mc5000ChannelStatus,
    Mc5000Error,
    Mc5000Operation,
    Mc5000Program,
    Mc5000State,
    mc5000_operation_code,
    mc5000_operation_from_code,
)

_LOGGER = logging.getLogger(__name__)

PACKET_MAGIC = 0x0F

CMD_HELLO = 0x06
CMD_GET_CHANNEL_DATA = 0x91
CMD_START_PROGRAM = 0x94
CMD_STOP = 0xFE

PROGRAM_PAYLOAD_SIZE = 40
RESPONSE_TIMEOUT = 3.0
CONNECT_SETTLE_DELAY = 0.5
INTER_COMMAND_DELAY = 0.15

# Conservative limits; the charger enforces its own as well.
MC5000_MAX_CHARGE_CURRENT = 3.0
MC5000_MAX_DISCHARGE_CURRENT = 2.0

MC5000_DEFAULT_STORAGE_VOLTAGE = {
    Mc5000BatteryType.LIION: 3800,
    Mc5000BatteryType.LIION_HV: 3900,
    Mc5000BatteryType.LIFEPO4: 3300,
    Mc5000BatteryType.NIMH: 3300,
    Mc5000BatteryType.NICD: 3300,
    Mc5000BatteryType.ENELOOP: 3300,
    Mc5000BatteryType.NIZN: 3300,
    Mc5000BatteryType.RAM: 3300,
    Mc5000BatteryType.LTO: 2400,
    Mc5000BatteryType.NAION: 3500,
}


def build_frame(command: int, payload: bytes | list[int] = b"") -> bytes:
    """Build an MC5000 frame."""
    body = bytes([command]) + bytes(payload)
    return bytes([PACKET_MAGIC, len(body) + 1]) + body + bytes([sum(body) & 0xFF])


def frame_checksum_ok(frame: bytes) -> bool:
    """Validate an MC5000 frame checksum."""
    return (
        len(frame) >= 4
        and frame[0] == PACKET_MAGIC
        and (sum(frame[2:-1]) & 0xFF) == frame[-1]
    )


def build_program_payload(channels: int, program: Mc5000Program) -> bytes:
    """Serialize a work program (40 bytes) as the official SkyRC app does."""

    def u8(name: str, value: int) -> list[int]:
        if not 0 <= value <= 0xFF:
            raise ValueError(f"{name} must fit in one byte")
        return [value]

    def u16(name: str, value: int) -> list[int]:
        if not 0 <= value <= 0xFFFF:
            raise ValueError(f"{name} must fit in two bytes")
        return [value >> 8, value & 0xFF]

    def current(name: str, value: float, maximum: float) -> list[int]:
        if not 0 <= value <= maximum:
            raise ValueError(f"{name} must be between 0 and {maximum} A")
        scaled = round(value * 1000)
        if abs(value * 1000 - scaled) > 1e-6:
            raise ValueError(f"{name} must use 0.001 A increments")
        return u16(name, scaled)

    if not isinstance(program.battery_type, Mc5000BatteryType):
        raise ValueError("battery_type must be an Mc5000BatteryType")
    if not isinstance(program.operation, Mc5000Operation):
        raise ValueError("operation must be an Mc5000Operation")
    max_voltage = MC5000_MAX_CHARGE_VOLTAGE[program.battery_type]
    if not 0 < program.charge_voltage <= max_voltage:
        raise ValueError(
            f"charge_voltage must be 1..{max_voltage} mV for "
            f"{program.battery_type.name}"
        )
    if program.trickle_current % 10:
        raise ValueError("trickle_current must use 10 mA increments")

    storage_voltage = (
        program.storage_voltage or MC5000_DEFAULT_STORAGE_VOLTAGE[program.battery_type]
    )
    discharge_end_current = program.discharge_end_current or round(
        program.discharge_current * 1000
    )

    payload = [
        *u8("channels", channels),
        mc5000_operation_code(program.battery_type, program.operation),
        *current("charge_current", program.charge_current, MC5000_MAX_CHARGE_CURRENT),
        *current(
            "discharge_current",
            program.discharge_current,
            MC5000_MAX_DISCHARGE_CURRENT,
        ),
        *u16("capacity", program.capacity),
        *u16("charge_voltage", program.charge_voltage),
        *u16("discharge_voltage", program.discharge_voltage),
        *u16("charge_end_current", program.charge_end_current),
        *u16("discharge_end_current", discharge_end_current),
        *u16("charge_rest_time", program.charge_rest_time),
        *u16("discharge_rest_time", program.discharge_rest_time),
        *u8("cycle_count", program.cycle_count),
        *u8("cycle_type", program.cycle_type),
        *u8("delta_v", program.delta_v),
        *u8("trickle_current", program.trickle_current // 10),
        *u16("maintenance_voltage", program.maintenance_voltage),
        *u8("protection_temperature", program.protection_temperature or 71),
        *u16("protection_time", program.protection_time),
        *u16("maxboost_capacity", program.maxboost_capacity or 300),
        *u8("turbo", program.turbo),
        int(program.battery_type),
        *u16("storage_voltage", storage_voltage),
        *u8("eneloop_type", program.eneloop_type),
    ]
    payload += [0] * (PROGRAM_PAYLOAD_SIZE - len(payload))
    if len(payload) != PROGRAM_PAYLOAD_SIZE:
        raise AssertionError("Invalid MC5000 program payload size")
    return bytes(payload)


def parse_channel_data(frame: bytes) -> tuple[int, Mc5000ChannelData]:
    """Parse a 0x91 channel-data frame into (channel index, data)."""
    mask = frame[3]
    if mask not in (1, 2, 4, 8):
        raise ValueError(f"Invalid channel mask 0x{mask:02x}")
    channel = mask.bit_length() - 1

    def u16(offset: int) -> int:
        return (frame[offset] << 8) | frame[offset + 1]

    battery_type = Mc5000BatteryType(frame[21])
    data = Mc5000ChannelData(
        type=battery_type,
        operation=mc5000_operation_from_code(battery_type, frame[19]),
        status=Mc5000ChannelStatus(frame[18]),
        error=Mc5000Error(frame[20]),
        time=int.from_bytes(frame[12:16], "big"),
        voltage=u16(6) / 1000.0,
        current=u16(4) / 1000.0,
        capacity=u16(10),
        temperature=u16(8),
        resistance=u16(16),
    )
    return channel, data


class Mc5000(SkyRcDevice[Mc5000State]):
    _model = "MC5000"

    def __init__(self, ble_device: BLEDevice) -> None:
        super().__init__(ble_device)
        self._state = Mc5000State()
        self._buffer = b""
        self._expected_response_command: int | None = None
        self._last_response: bytes | None = None

    async def connect(self) -> bool:
        """Connect to the device."""
        if result := await super().connect():
            self._buffer = b""
            async with self._client_lock:
                await self._client.start_notify(
                    MC3000_CHARACTERISTIC_UUID, self._notification_callback
                )
            # The charger answers the first frame after connecting with a
            # 0x06 "hello" instead of a reply, so send a throwaway query.
            await asyncio.sleep(CONNECT_SETTLE_DELAY)
            await self._request(CMD_GET_CHANNEL_DATA, [0x01], timeout=1.5)
        return result

    async def update(self) -> None:
        """Update the state of all channels."""
        await super().update()
        try:
            for channel in range(0, MC3000_CHANNEL_COUNT):
                await self._request(CMD_GET_CHANNEL_DATA, [1 << channel])
        except BleakError as error:
            if self.is_connected:
                raise error

    async def start_program(self, channel: int, program: Mc5000Program) -> None:
        """Send a complete program to one channel (0-3) and start it."""
        if channel not in range(0, MC3000_CHANNEL_COUNT):
            raise ValueError("Invalid channel")
        await self.start_program_multi(1 << channel, program)

    async def start_program_multi(self, channels: int, program: Mc5000Program) -> None:
        """Send a complete program to channels selected by a bitfield and start it.

        A bitfield of 0 applies the program to all channels.
        """
        if channels not in range(0, 1 << MC3000_CHANNEL_COUNT):
            raise ValueError("Invalid channels")
        payload = build_program_payload(channels, program)
        response = await self._request(CMD_START_PROGRAM, payload)
        if response is None or len(response) < 5 or response[4] != 1:
            raise BleakError("MC5000 rejected or did not acknowledge the program")

    async def stop_charge(self, channel: int) -> None:
        """Stop the specified channel (0-3)."""
        if channel not in range(0, MC3000_CHANNEL_COUNT):
            raise ValueError("Invalid channel")
        await self.stop_charge_multi(1 << channel)

    async def stop_charge_multi(self, channels: int) -> None:
        """Stop channels selected by a bitfield (0 = all channels)."""
        if channels not in range(0, 1 << MC3000_CHANNEL_COUNT):
            raise ValueError("Invalid channels")
        response = await self._request(CMD_STOP, [channels])
        if response is None or len(response) < 5 or response[4] != 1:
            raise BleakError("MC5000 rejected or did not acknowledge the stop")

    async def _request(
        self,
        command: int,
        payload: bytes | list[int],
        timeout: float = RESPONSE_TIMEOUT,
    ) -> bytes | None:
        """Send one frame and wait for the response with the same command byte."""
        frame = build_frame(command, payload)
        _LOGGER.debug("%s: Sending packet: %s", self.name, frame.hex())
        async with self._client_lock:
            self._expected_response_command = command
            self._last_response = None
            self._packet_received.clear()
            try:
                await self._client.write_gatt_char(
                    MC3000_CHARACTERISTIC_UUID, frame, response=False
                )
                try:
                    await asyncio.wait_for(self._packet_received.wait(), timeout)
                except asyncio.TimeoutError:
                    _LOGGER.debug(
                        "%s: Timeout waiting for response to 0x%02x",
                        self.name,
                        command,
                    )
            finally:
                self._expected_response_command = None
            # The official app keeps writes at least 150 ms apart.
            await asyncio.sleep(INTER_COMMAND_DELAY)
            return self._last_response

    async def _notification_callback(
        self, sender: BleakGATTCharacteristic, data: bytearray
    ) -> None:
        """Reassemble frames that may arrive split across notifications."""
        self._buffer += bytes(data)
        while len(self._buffer) >= 2:
            if self._buffer[0] != PACKET_MAGIC:
                self._buffer = self._buffer[1:]
                continue
            length = self._buffer[1] + 2
            if len(self._buffer) < length:
                return
            frame, self._buffer = self._buffer[:length], self._buffer[length:]
            self._handle_frame(frame)

    def _handle_frame(self, frame: bytes) -> None:
        _LOGGER.debug("%s: Received packet: %s", self.name, frame.hex())
        if not frame_checksum_ok(frame):
            _LOGGER.warning("%s: Invalid checksum in packet %s", self.name, frame.hex())
            return
        command = frame[2]
        if command == CMD_GET_CHANNEL_DATA and len(frame) >= 23:
            try:
                channel, data = parse_channel_data(frame)
            except ValueError as error:
                _LOGGER.warning("%s: %s", self.name, error)
            else:
                self._state.channels[channel] = data
        elif command not in (CMD_HELLO, CMD_START_PROGRAM, CMD_STOP):
            _LOGGER.debug("%s: Unhandled packet type 0x%02x", self.name, command)
        if command == self._expected_response_command:
            self._last_response = frame
            self._packet_received.set()
        elif command == CMD_HELLO and self._expected_response_command is not None:
            # The hello replaces the reply to the first frame after connecting.
            self._packet_received.set()
