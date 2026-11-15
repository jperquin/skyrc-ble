"""Session fixtures."""

import asyncio
from typing import Any, Awaitable, Callable
from unittest import mock

import pytest
from bleak import BleakGATTCharacteristic

from skyrc_ble.mc3000 import (
    CMD_GET_BASIC_DATA,
    CMD_GET_CHANNEL_DATA,
    CMD_GET_VERSION_INFO,
    CMD_SET_WORK_PROGRAM,
    CMD_START_CHARGE,
    CMD_STOP_CHARGE,
)


class MockMc3000BleakClient:
    """Mock BleakClient."""

    def __init__(self, *args, **kwargs):
        """Mock BleakClient."""
        self.packets_sent: int = 0
        self.sent_data: list[bytes] = []
        self._work_program_pending = False

    async def connect(self, *args, **kwargs):
        """Mock BleakClient.connect."""

    async def disconnect(self, *args, **kwargs):
        """Mock BleakClient.disconnect."""

    async def start_notify(
        self,
        char_specifier: str,
        callback: Callable[[BleakGATTCharacteristic, bytearray], Awaitable[None]],
        **kwargs: Any,
    ) -> None:
        """Mock BleakClient.start_notify."""

        def wrapped_callback(data):
            asyncio.ensure_future(callback(None, data))

        self._callback = wrapped_callback

    async def write_gatt_char(
        self, char_specifier: str, data: bytes, response: bool = False
    ) -> None:
        """Mock BleakClient.write_gatt_char."""

        self.sent_data.append(bytes(data))

        if data[1] == CMD_SET_WORK_PROGRAM:
            self._work_program_pending = True
            self.packets_sent += 1
            return
        elif self._work_program_pending:
            self._work_program_pending = False
            value = bytearray.fromhex("0f1101f0ffff000000000000000000000000000f")
        elif data[1] == CMD_GET_VERSION_INFO:
            value = bytearray.fromhex("0f57003130303038330100000000010f1600adfc")
        elif data[1] == CMD_GET_BASIC_DATA:
            value = bytearray.fromhex("0f6100000200002af80000000000000000000094")
        elif data[1] == CMD_GET_CHANNEL_DATA and data[2] == 0:
            value = bytearray.fromhex("0f55000000000013f30e3a000004b718001b07a7")
        elif data[1] == CMD_GET_CHANNEL_DATA and data[2] == 1:
            value = bytearray.fromhex("0f55010000000100360e6e03e9000d1800190749")
        elif data[1] == CMD_GET_CHANNEL_DATA and data[2] == 2:
            value = bytearray.fromhex("0f5502000000041416103a000004c418001e704c")
        elif data[1] == CMD_GET_CHANNEL_DATA and data[2] == 3:
            value = bytearray.fromhex("0f550300000000154c0000000004bb1800887097")
        elif data[1] == CMD_START_CHARGE and data[2] == 1:
            value = bytearray.fromhex("0f05010000000000000000000000000000000015")
        elif data[1] == CMD_STOP_CHARGE and data[2] == 1:
            value = bytearray.fromhex("0ffe01f0ffff00000000000000000000000000fc")
        else:
            value = bytearray([0])

        self.packets_sent += 1

        asyncio.get_running_loop().call_soon(self._callback, value)
        await asyncio.sleep(0)


@pytest.fixture()
def mock_mc3000_bleak():
    """Mock BleakClient."""

    with mock.patch("skyrc_ble.device.BleakClient", MockMc3000BleakClient):
        yield


# Frames captured from a real MC5000 (2026-11-15).
MC5000_HELLO = "0f 04 06 01 01 08"
MC5000_CHANNEL_DATA = {
    0x01: "0f 16 91 01 00 00 05 0f 00 00 00 00 00 00 00 00 00 00 00 00 00 03 00 a9",
    0x02: "0f 16 91 02 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 03 00 96",
    0x04: "0f 16 91 04 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 95",
    0x08: "0f 16 91 08 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 99",
}


class MockMc5000BleakClient(MockMc3000BleakClient):
    """Mock BleakClient that answers like an MC5000.

    Like the real charger, the first frame after connecting is answered with a
    0x06 hello instead of its own reply. Responses can be split into chunks to
    exercise frame reassembly.
    """

    split_responses = False

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._hello_sent = False

    async def write_gatt_char(
        self, char_specifier: str, data: bytes, response: bool = False
    ) -> None:
        self.sent_data.append(bytes(data))
        self.packets_sent += 1
        command = data[2]
        if not self._hello_sent:
            self._hello_sent = True
            value = bytes.fromhex(MC5000_HELLO)
        elif command == 0x91:
            value = bytes.fromhex(MC5000_CHANNEL_DATA[data[3]])
        elif command in (0x94, 0xFE):
            body = bytes([command, data[3], 0x01])
            value = bytes([0x0F, 0x04]) + body + bytes([sum(body) & 0xFF])
        else:
            return

        chunks = [value[:10], value[10:]] if self.split_responses else [value]
        for chunk in chunks:
            asyncio.get_running_loop().call_soon(self._callback, bytearray(chunk))
        await asyncio.sleep(0)


@pytest.fixture()
def mock_mc5000_bleak():
    """Mock BleakClient for the MC5000."""

    MockMc5000BleakClient.split_responses = False
    with mock.patch("skyrc_ble.device.BleakClient", MockMc5000BleakClient):
        yield MockMc5000BleakClient
