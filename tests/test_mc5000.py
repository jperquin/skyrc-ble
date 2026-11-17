from unittest import mock

import pytest
from bleak import BLEDevice

from skyrc_ble import Mc5000
from skyrc_ble.mc5000 import build_frame, build_program_payload
from skyrc_ble.models import (
    Mc5000BatteryType,
    Mc5000ChannelData,
    Mc5000ChannelStatus,
    Mc5000Error,
    Mc5000Operation,
    Mc5000Program,
)

NIMH_CHARGE_300MA = Mc5000Program(
    battery_type=Mc5000BatteryType.NIMH,
    operation=Mc5000Operation.CHARGE,
    capacity=2000,
    charge_current=0.3,
    discharge_current=0.5,
    charge_voltage=1650,
    discharge_voltage=900,
)


@pytest.fixture(autouse=True)
def _fast_delays():
    with mock.patch("skyrc_ble.mc5000.CONNECT_SETTLE_DELAY", 0), mock.patch(
        "skyrc_ble.mc5000.INTER_COMMAND_DELAY", 0
    ):
        yield


async def _connected(name="#Charger-4036"):
    mc5000 = Mc5000(BLEDevice("00:01:02:03:04:05", name, None))
    await mc5000.connect()
    return mc5000


def test_build_frame():
    assert build_frame(0x91, [0x01]) == bytes.fromhex("0f 03 91 01 92")
    assert build_frame(0xFE, [0x00]) == bytes.fromhex("0f 03 fe 00 fe")


@pytest.mark.asyncio
async def test_mc5000_state(mock_mc5000_bleak):
    mc5000 = await _connected()
    await mc5000.update()

    assert mc5000.model == "MC5000"
    assert mc5000.state.channels[0] == Mc5000ChannelData(
        type=Mc5000BatteryType.NIMH,
        operation=Mc5000Operation.CHARGE,
        status=Mc5000ChannelStatus.STANDBY,
        error=Mc5000Error.NONE,
        time=0,
        voltage=1.295,
        current=0.0,
        capacity=0,
        temperature=0,
        resistance=0,
    )
    assert mc5000.state.channels[2].type == Mc5000BatteryType.LIION
    assert all(channel is not None for channel in mc5000.state.channels)


@pytest.mark.asyncio
async def test_mc5000_reassembles_split_notifications(mock_mc5000_bleak):
    mock_mc5000_bleak.split_responses = True
    mc5000 = await _connected()
    await mc5000.update()
    assert mc5000.state.channels[0].voltage == 1.295


@pytest.mark.asyncio
async def test_mc5000_start_nimh_charge_matches_hardware_capture(mock_mc5000_bleak):
    mc5000 = await _connected()
    await mc5000.start_program(0, NIMH_CHARGE_300MA)

    # Frame sent to a real MC5000, which acknowledged it and charged at 300 mA.
    assert mc5000._client.sent_data[-1] == bytes.fromhex(
        "0f 2a 94 01 00 01 2c 01 f4 07 d0 06 72 03 84 00 64 00 64 00 0a 00 0a 01 00 06 "
        "00 00 00 3c 00 00 01 2c 00 03 0c e4 00 00 00 00 00 cc"
    )


@pytest.mark.asyncio
async def test_mc5000_start_nimh_discharge_matches_hardware_capture(mock_mc5000_bleak):
    mc5000 = await _connected()
    program = Mc5000Program(
        battery_type=Mc5000BatteryType.NIMH,
        operation=Mc5000Operation.DISCHARGE,
        capacity=3000,
        charge_current=0.3,
        discharge_current=0.5,
        charge_voltage=1650,
        discharge_voltage=1000,
    )
    await mc5000.start_program(1, program)

    assert mc5000._client.sent_data[-1] == bytes.fromhex(
        "0f 2a 94 02 03 01 2c 01 f4 0b b8 06 72 03 e8 00 64 00 64 00 0a 00 0a 01 00 06 "
        "00 00 00 3c 00 00 01 2c 00 03 0c e4 00 00 00 00 00 20"
    )


@pytest.mark.asyncio
async def test_mc5000_stop(mock_mc5000_bleak):
    mc5000 = await _connected()
    await mc5000.stop_charge(0)
    assert mc5000._client.sent_data[-1] == bytes.fromhex("0f 03 fe 01 ff")
    await mc5000.stop_charge_multi(0)
    assert mc5000._client.sent_data[-1] == bytes.fromhex("0f 03 fe 00 fe")


@pytest.mark.parametrize(
    "changes, message",
    [
        ({"charge_voltage": 4300, "battery_type": Mc5000BatteryType.LIION}, "1..4200"),
        ({"operation": Mc5000Operation.STORAGE}, "not available for NIMH"),
        ({"charge_current": 3.5}, "between 0 and 3.0 A"),
        ({"discharge_current": 2.5}, "between 0 and 2.0 A"),
        ({"charge_current": 0.3005}, "0.001 A increments"),
        ({"trickle_current": 15}, "10 mA increments"),
    ],
)
def test_mc5000_program_validation(changes, message):
    fields = {**NIMH_CHARGE_300MA.__dict__, **changes}
    with pytest.raises(ValueError, match=message):
        build_program_payload(0x01, Mc5000Program(**fields))


@pytest.mark.asyncio
async def test_mc5000_rejects_invalid_channels(mock_mc5000_bleak):
    mc5000 = await _connected()
    with pytest.raises(ValueError):
        await mc5000.start_program(4, NIMH_CHARGE_300MA)
    with pytest.raises(ValueError):
        await mc5000.stop_charge_multi(0x10)


@pytest.mark.asyncio
async def test_mc5000_request_after_disconnect_raises_bleak_error(mock_mc5000_bleak):
    from bleak.exc import BleakError

    mc5000 = await _connected()
    mc5000._client = None  # what the disconnected callback does
    with pytest.raises(BleakError):
        await mc5000.stop_charge(0)
