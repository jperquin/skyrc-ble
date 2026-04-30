from __future__ import annotations

import asyncio
import logging
from struct import Struct

from bleak.backends.device import BLEDevice
from bleak.backends.service import BleakGATTCharacteristic
from bleak.exc import BleakError

from .const import MC3000_CHANNEL_COUNT, MC3000_CHARACTERISTIC_UUID
from .device import SkyRcDevice
from .models import (
    BatteryType,
    ChannelMode,
    ChannelStatus,
    CoolingFanMode,
    DisplayMode,
    LedColor,
    Mc3000BasicData,
    Mc3000ChannelData,
    Mc3000State,
    Mc3000VoltageCurveData,
    TemperatureUnit,
)

_LOGGER = logging.getLogger(__name__)

PACKET_MAGIC = 0x0F

CMD_GET_CHANNEL_DATA = 0x55
CMD_GET_VOLTAGE_CURVE = 0x56
CMD_GET_VERSION_INFO = 0x57
CMD_GET_BASIC_DATA = 0x61
CMD_START_CHARGE = 0x05
CMD_STOP_CHARGE = 0xFE

STRUCT_GET_CHANNEL_DATA = Struct(">BBBBBHHHHBHB")
STRUCT_GET_VERSION_INFO = Struct(">xxxxxxxxxxxxBBB")
STRUCT_GET_BASIC_DATA = Struct(">B?B?BH")


class Mc3000(SkyRcDevice[Mc3000State]):
    _model = "MC3000"

    def __init__(self, ble_device: BLEDevice) -> None:
        super().__init__(ble_device)

        self._state = Mc3000State()
        self._voltage_curve_chunks: list[bytes] | None = None

    async def connect(self) -> bool:
        """Connect to the device."""
        if result := await super().connect():
            async with self._client_lock:
                await self._client.start_notify(
                    MC3000_CHARACTERISTIC_UUID, self._notification_callback
                )
            await self._send_packet(CMD_GET_VERSION_INFO)

        return result

    async def update(self) -> None:
        """Update the state of the device."""
        await super().update()

        try:
            await self._send_packet(CMD_GET_BASIC_DATA)
            for channel in range(0, MC3000_CHANNEL_COUNT):
                await self._send_packet(CMD_GET_CHANNEL_DATA, [channel])

        except BleakError as error:
            if self.is_connected:
                raise error

    async def get_voltage_curve_data(self, channel: int) -> Mc3000VoltageCurveData:
        """Return voltage curve data for the specified channel.

        The MC3000 returns command 0x56 as a 246-byte frame split across
        multiple BLE notifications, usually 12 x 20 bytes + 1 x 6 bytes.
        """
        if channel not in range(0, MC3000_CHANNEL_COUNT):
            raise ValueError("Invalid channel")

        self._voltage_curve_chunks = []

        try:
            await self._send_packet(CMD_GET_VOLTAGE_CURVE, [channel])
            raw = b"".join(self._voltage_curve_chunks or [])
        finally:
            self._voltage_curve_chunks = None

        if len(raw) < 246:
            raise BleakError(
                f"Incomplete voltage curve response: got {len(raw)} bytes, expected 246"
            )

        frame = raw[:246]

        if frame[0] != PACKET_MAGIC:
            raise BleakError("Voltage curve frame does not start with magic number")

        if frame[1] != CMD_GET_VOLTAGE_CURVE:
            raise BleakError(f"Unexpected voltage curve command byte: 0x{frame[1]:02x}")

        if frame[2] != channel:
            raise BleakError(
                f"Voltage curve channel mismatch: got {frame[2]}, expected {channel}"
            )

        checksum = sum(frame[:-1]) & 0xFF
        checksum_ok = frame[-1] == checksum
        if not checksum_ok:
            raise BleakError(
                f"Voltage curve checksum mismatch: got 0x{frame[-1]:02x}, expected 0x{checksum:02x}"
            )

        sample_bytes = frame[5:-1]
        if len(sample_bytes) != 240:
            raise BleakError(
                f"Unexpected voltage curve sample byte length: {len(sample_bytes)}"
            )

        samples_mv = [
            int.from_bytes(sample_bytes[i : i + 2], "big")
            for i in range(0, len(sample_bytes), 2)
        ]

        return Mc3000VoltageCurveData(
            channel=frame[2],
            unknown_3=frame[3],
            interval_seconds=frame[4],
            samples_mv=samples_mv,
            checksum_ok=checksum_ok,
            raw_frame=frame,
        )

    async def get_voltage_curve(self, channel: int) -> list[int]:
        """Return voltage curve samples for the specified channel in millivolts."""
        curve = await self.get_voltage_curve_data(channel)
        return curve.samples_mv

    async def start_charge(self, channel: int) -> None:
        """Start charging the battery in the specified channel."""
        if channel not in range(0, MC3000_CHANNEL_COUNT):
            raise ValueError("Invalid channel")
        await self._send_packet(CMD_START_CHARGE, [1 << channel])

    async def start_charge_multi(self, channels: int) -> None:
        """Start charging the batteries in the specified channels.
        The channels are specified in a bitfield where bits 0-3 represent channels 1-4
        and multiple bits can be set at once.
        """
        if channels not in range(0, 1 << MC3000_CHANNEL_COUNT):
            raise ValueError("Invalid channels")
        await self._send_packet(CMD_START_CHARGE, [channels])

    async def stop_charge(self, channel: int) -> None:
        """Stop charging the battery in the specified channel."""
        if channel not in range(0, MC3000_CHANNEL_COUNT):
            raise ValueError("Invalid channel")
        await self._send_packet(CMD_STOP_CHARGE, [1 << channel])

    async def stop_charge_multi(self, channels: int) -> None:
        """Stop charging the batteries in the specified channels.
        The channels are specified in a bitfield where bits 0-3 represent channels 1-4
        and multiple bits can be set at once.
        """
        if channels not in range(0, 1 << MC3000_CHANNEL_COUNT):
            raise ValueError("Invalid channels")
        await self._send_packet(CMD_STOP_CHARGE, [channels])

    async def _send_packet(self, command: int, payload: list[int] = []) -> None:
        """Send a packet to the device."""

        # Pad payload with zeros
        payload = payload + [0] * (17 - len(payload))

        # Format packet and calculate checksum
        packet = [PACKET_MAGIC, command, *payload, 0]
        packet[-1] = sum(packet) & 255
        packet_bytes = bytes(packet)

        # Send packet and wait for response
        _LOGGER.debug("%s: Sending packet: %s", self.name, packet_bytes.hex())
        async with self._client_lock:
            self._packet_received.clear()
            await self._client.write_gatt_char(MC3000_CHARACTERISTIC_UUID, packet_bytes)
            try:
                await asyncio.wait_for(self._packet_received.wait(), 2)
            except TimeoutError:
                _LOGGER.warn("%s: Timeout waiting for response notification")

    async def _notification_callback(
        self, sender: BleakGATTCharacteristic, packet: bytearray
    ) -> None:
        """Handle a GATT notification."""
        if self._voltage_curve_chunks is not None:
            packet_bytes = bytes(packet)

            if not self._voltage_curve_chunks:
                if (
                    len(packet_bytes) >= 2
                    and packet_bytes[0] == PACKET_MAGIC
                    and packet_bytes[1] == CMD_GET_VOLTAGE_CURVE
                ):
                    self._voltage_curve_chunks.append(packet_bytes)
                    if len(packet_bytes) >= 246:
                        self._packet_received.set()
                    return

                await self._parse_packet(packet)
                self._packet_received.set()
                return

            self._voltage_curve_chunks.append(packet_bytes)
            raw = b"".join(self._voltage_curve_chunks)

            if len(raw) >= 246:
                self._packet_received.set()

            return

        await self._parse_packet(packet)
        self._packet_received.set()

    async def _parse_packet(self, packet: bytearray) -> None:
        """Parse single-packet messages and update the data model.

        Multi-packet messages like voltage-curves are currently not supported.
        """

        _LOGGER.debug("%s: Received packet: %s", self.name, packet.hex())

        if len(packet) < 3:
            _LOGGER.warn("%s: Packet is too short", self.name)
            return
        if packet[0] != PACKET_MAGIC:
            _LOGGER.warn("%s: Packet does not start with magic number", self.name)
            return

        checksum = sum(packet[0:-1]) & 255
        if packet[-1] != checksum:
            if (
                packet[1] != CMD_GET_VERSION_INFO
            ):  # Version info packets have invalid checksums, looks like a bug in the firmware
                _LOGGER.warn(
                    "%s: Packet checksum (%x) does not match expected checksum (%x)",
                    self.name,
                    packet[-1],
                    checksum,
                )
                return

        if packet[1] == CMD_GET_CHANNEL_DATA:
            (
                channel,
                type,
                mode,
                count,
                status,
                time,
                voltage,
                current,
                capacity,
                temperature,
                resistance,
                leds,
            ) = STRUCT_GET_CHANNEL_DATA.unpack_from(packet, 2)
            if channel >= MC3000_CHANNEL_COUNT:
                _LOGGER.warn(
                    "%s: Received channel data for invalid channel %d",
                    self.name,
                    channel,
                )
                return
            self._state.channels[channel] = Mc3000ChannelData(
                BatteryType(type),
                ChannelMode(mode),
                count,
                ChannelStatus(status),
                time,
                voltage / 1000.0,
                current / 1000.0,
                capacity,
                temperature,
                resistance,
                self._resolve_channel_led(leds, channel),
            )
            return

        elif packet[1] == CMD_GET_BASIC_DATA:
            (
                temp_unit,
                system_beep,
                display,
                screensaver,
                cooling_fan,
                input_voltage,
            ) = STRUCT_GET_BASIC_DATA.unpack_from(packet, 2)
            self._state.basic_data = Mc3000BasicData(
                TemperatureUnit(temp_unit),
                system_beep,
                DisplayMode(display),
                screensaver,
                CoolingFanMode(cooling_fan),
                input_voltage / 1000.0,
            )

        elif packet[1] == CMD_GET_VERSION_INFO:
            (
                fw_version_major,
                fw_version_minor,
                hw_version,
            ) = STRUCT_GET_VERSION_INFO.unpack_from(packet, 2)
            self._sw_version = f"{fw_version_major}.{fw_version_minor}"
            self._hw_version = f"{hw_version // 10}.{hw_version % 10}"

        elif packet[1] not in [CMD_START_CHARGE, CMD_STOP_CHARGE]:
            _LOGGER.info("%s: Unknown packet type %d", self.name, packet[1])

    def _resolve_channel_led(self, value: int, channel: int) -> LedColor:
        if (value >> channel) & 1:
            return LedColor.RED
        elif (value >> (channel + MC3000_CHANNEL_COUNT)) & 1:
            return LedColor.GREEN
        return LedColor.OFF
