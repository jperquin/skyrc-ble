import pytest
from bleak import BLEDevice

from skyrc_ble import Mc3000
from skyrc_ble.models import (
    BatteryType,
    ChannelMode,
    ChannelStatus,
    CoolingFanMode,
    DisplayMode,
    LedColor,
    Mc3000BasicData,
    Mc3000ChannelData,
    Mc3000Program,
    TemperatureUnit,
)


@pytest.mark.asyncio
async def test_mc3000_state(mock_mc3000_bleak):
    ble_device = BLEDevice("00:01:02:03:04:05", "Charger", None)
    mc3000 = Mc3000(ble_device)

    await mc3000.connect()
    assert mc3000.name == "Charger"
    assert mc3000.address == "00:01:02:03:04:05"
    assert mc3000.hw_version == "2.2"
    assert mc3000.sw_version == "1.15"

    await mc3000.update()
    assert mc3000.state.basic_data == Mc3000BasicData(
        temp_unit=TemperatureUnit.CELSIUS,
        system_beep=False,
        display=DisplayMode.TIME_1MIN,
        screensaver=False,
        cooling_fan=CoolingFanMode.AUTO,
        input_voltage=11.0,
    )
    assert mc3000.state.channels[0] == Mc3000ChannelData(
        type=BatteryType.LIION,
        mode=ChannelMode.CHARGE,
        count=0,
        status=ChannelStatus.STANDBY,
        time=5107,
        voltage=3.642,
        current=0.0,
        capacity=1207,
        temperature=24,
        resistance=27,
        led=LedColor.RED,
    )
    assert mc3000.state.channels[1] == Mc3000ChannelData(
        type=BatteryType.LIION,
        mode=ChannelMode.CHARGE,
        count=0,
        status=ChannelStatus.CHARGE,
        time=54,
        voltage=3.694,
        current=1.001,
        capacity=13,
        temperature=24,
        resistance=25,
        led=LedColor.RED,
    )
    assert mc3000.state.channels[2] == Mc3000ChannelData(
        type=BatteryType.LIION,
        mode=ChannelMode.CHARGE,
        count=0,
        status=ChannelStatus.DONE,
        time=5142,
        voltage=4.154,
        current=0.0,
        capacity=1220,
        temperature=24,
        resistance=30,
        led=LedColor.GREEN,
    )
    assert mc3000.state.channels[3] == Mc3000ChannelData(
        type=BatteryType.LIION,
        mode=ChannelMode.CHARGE,
        count=0,
        status=ChannelStatus.STANDBY,
        time=5452,
        voltage=0.0,
        current=0.0,
        capacity=1211,
        temperature=24,
        resistance=136,
        led=LedColor.OFF,
    )


@pytest.mark.asyncio
async def test_mc3000_start_stop(mock_mc3000_bleak):
    ble_device = BLEDevice("00:01:02:03:04:05", "Charger", None)
    mc3000 = Mc3000(ble_device)

    await mc3000.connect()

    sent = mc3000._client.packets_sent
    await mc3000.start_charge(0)
    await mc3000.stop_charge(0)
    assert mc3000._client.packets_sent == sent + 2


@pytest.mark.asyncio
async def test_mc3000_write_nimh_program(mock_mc3000_bleak):
    ble_device = BLEDevice("00:01:02:03:04:05", "Charger", None)
    mc3000 = Mc3000(ble_device)
    await mc3000.connect()

    program = Mc3000Program(
        battery_type=BatteryType.NIMH,
        operation=ChannelMode.CHARGE,
        capacity=3500,
        charge_current=1.0,
        discharge_current=0.2,
        charge_voltage=1650,
        discharge_voltage=1000,
        charge_end_current=990,
        discharge_end_current=200,
        cycle_time=0,
        cycle_count=1,
        cycle_type=0,
        delta_v=10,
        trickle_current=10,
        maintenance_voltage=4150,
        protection_temperature=19,
        protection_time=0,
        discharge_time=0,
    )

    await mc3000.write_program(0, program)

    assert mc3000._client.sent_data[-2] == bytes.fromhex(
        "0f110103000dac03e800c8067203e803de00c800"
    )
    assert mc3000._client.sent_data[-1] == bytes.fromhex(
        "01000a0110361300000000000000000000000001"
    )


def test_mc3000_work_program_validation():
    program = Mc3000Program(
        battery_type=BatteryType.NIMH,
        operation=ChannelMode.CHARGE,
        capacity=3500,
        charge_current=1.0005,
        discharge_current=0.2,
        charge_voltage=1650,
        discharge_voltage=1000,
        charge_end_current=990,
        discharge_end_current=200,
    )

    with pytest.raises(ValueError, match="0.001 A increments"):
        Mc3000._build_work_program_frames(1, program)


@pytest.mark.asyncio
async def test_mc3000_write_program_rejects_empty_channel_mask(mock_mc3000_bleak):
    ble_device = BLEDevice("00:01:02:03:04:05", "Charger", None)
    mc3000 = Mc3000(ble_device)
    program = Mc3000Program(
        battery_type=BatteryType.NIMH,
        operation=ChannelMode.CHARGE,
        capacity=3500,
        charge_current=1.0,
        discharge_current=0.2,
        charge_voltage=1650,
        discharge_voltage=1000,
        charge_end_current=990,
        discharge_end_current=200,
    )

    with pytest.raises(ValueError, match="Invalid channels"):
        await mc3000.write_program_multi(0, program)
