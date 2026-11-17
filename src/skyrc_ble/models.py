from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum

from .const import MC3000_CHANNEL_COUNT


class TemperatureUnit(IntEnum):
    CELSIUS = 0
    FAHRENHEIT = 1


class DisplayMode(IntEnum):
    OFF = 0
    AUTO = 1
    TIME_1MIN = 2
    TIME_2MIN = 3
    TIME_5MIN = 4
    ALWAYS_ON = 5


class CoolingFanMode(IntEnum):
    AUTO = 0
    OFF = 1
    ON = 2
    TEMP_20C = 3
    TEMP_25C = 4
    TEMP_30C = 5
    TEMP_35C = 6
    TEMP_40C = 7
    TEMP_45C = 8
    TEMP_50C = 9


class BatteryType(IntEnum):
    LIION = 0
    LIFE = 1
    LIION_4_35 = 2
    NIMH = 3
    NICD = 4
    NIZN = 5
    ENELOOP = 6
    RAM = 7
    BATLTO = 8


class ChannelMode(IntEnum):
    CHARGE = 0
    REFRESH = 1
    STORAGE = 2  # for LiIon, LiFe, LiIon_4.35
    BREAKIN = 2  # for NiMH, NiCd, NiZn, Eneloop, Ram, Batlto
    DISCHARGE = 3
    CYCLE = 4


class ChannelStatus(IntEnum):
    STANDBY = 0
    CHARGE = 1
    DISCHARGE = 2
    PAUSE = 3
    DONE = 4
    INPUT_VOLTAGE_LOW = 128
    INPUT_VOLTAGE_HIGH = 129
    MCP3424_1_ERROR = 130
    MCP3424_2_ERROR = 131
    CONNECTION_BREAK = 132
    CHECK_VOLTAGE = 133
    CAPACITY_PROTECTION = 134
    TIME_PROTECTION = 135
    TEMP_HIGH = 136
    BATTERY_TEMP_HIGH = 137
    BATTERY_SHORT_CIRCUIT = 138
    REVERSE_POLARITY = 139


class LedColor(IntEnum):
    OFF = 0
    RED = 1
    GREEN = 2


@dataclass(frozen=True)
class Mc3000BasicData:
    temp_unit: TemperatureUnit = TemperatureUnit.CELSIUS
    system_beep: bool = False
    display: DisplayMode = DisplayMode.OFF
    screensaver: bool = False
    cooling_fan: CoolingFanMode = CoolingFanMode.AUTO
    input_voltage: float = 0.0


@dataclass(frozen=True)
class Mc3000ChannelData:
    type: BatteryType = BatteryType.LIION
    mode: ChannelMode = ChannelMode.CHARGE
    count: int = 0
    status: ChannelStatus = ChannelStatus.STANDBY
    time: int = 0
    voltage: float = 0.0
    current: float = 0.0
    capacity: int = 0
    temperature: float = 0.0
    resistance: float = 0.0
    led: LedColor = LedColor.OFF

    def is_working(self) -> bool:
        return self.status in [
            ChannelStatus.CHARGE,
            ChannelStatus.DISCHARGE,
            ChannelStatus.PAUSE,
        ]


@dataclass
class Mc3000State:
    basic_data: Mc3000BasicData | None = None
    channels: list[Mc3000ChannelData | None] = field(
        default_factory=lambda: [None for _ in range(MC3000_CHANNEL_COUNT)]
    )


@dataclass(frozen=True)
class Mc3000Program:
    """Complete MC3000 work program.

    The charger protocol does not support changing only the chemistry. A complete
    program must always be uploaded, including all current, voltage and protection
    settings.
    """

    battery_type: BatteryType
    operation: ChannelMode
    capacity: int
    charge_current: float
    discharge_current: float
    charge_voltage: int
    discharge_voltage: int
    charge_end_current: int
    discharge_end_current: int
    cycle_time: int = 0
    cycle_count: int = 1
    cycle_type: int = 0
    delta_v: int = 0
    trickle_current: int = 0
    maintenance_voltage: int = 0
    protection_temperature: int = 0
    protection_time: int = 0
    discharge_time: int = 0


@dataclass(frozen=True)
class Mc3000VoltageCurveData:
    """MC3000 voltage curve data."""

    channel: int = 0
    unknown_3: int = 0
    interval_seconds: int = 0
    samples_mv: list[int] = field(default_factory=list)
    checksum_ok: bool = False
    raw_frame: bytes = b""


# --- MC5000 -----------------------------------------------------------------


class Mc5000BatteryType(IntEnum):
    """MC5000 chemistry index (differs from the MC3000 numbering)."""

    LIION = 0
    LIION_HV = 1
    LIFEPO4 = 2
    NIMH = 3
    NICD = 4
    ENELOOP = 5
    NIZN = 6
    RAM = 7
    LTO = 8
    NAION = 9


class Mc5000Operation(IntEnum):
    """Logical MC5000 operation.

    The wire value depends on the chemistry group; use
    :func:`mc5000_operation_code` and :func:`mc5000_operation_from_code`.
    """

    CHARGE = 0
    STORAGE = 1
    DISCHARGE = 2
    CYCLE = 3
    REFRESH = 4
    BREAKIN = 5


class Mc5000ChannelStatus(IntEnum):
    STANDBY = 0
    READY = 1
    CHARGE = 2
    DISCHARGE = 3
    REST = 4
    DONE = 5
    DONE_ALT = 6


class Mc5000Error(IntEnum):
    NONE = 0
    INPUT_VOLTAGE_LOW = 1
    INPUT_VOLTAGE_HIGH = 2
    CONNECTION_BREAK = 3
    CAPACITY_LIMIT = 4
    TIME_LIMIT = 5
    INTERNAL_TEMP_HIGH = 6
    CALIBRATION_FAILED = 7
    HIGH_RESISTANCE = 8
    CONNECTION_BREAK_ALT = 9
    BATTERY_TYPE_ERROR = 10
    OVERLOAD = 11
    REVERSE_POLARITY = 12
    FULLY_CHARGED = 13


# Chemistry group -> {operation: wire code}
_MC5000_LITHIUM = {
    Mc5000BatteryType.LIION,
    Mc5000BatteryType.LIION_HV,
    Mc5000BatteryType.LIFEPO4,
    Mc5000BatteryType.LTO,
    Mc5000BatteryType.NAION,
}
_MC5000_NICKEL = {
    Mc5000BatteryType.NIMH,
    Mc5000BatteryType.NICD,
    Mc5000BatteryType.ENELOOP,
}
_MC5000_OPERATION_CODES = {
    "lithium": {
        Mc5000Operation.CHARGE: 0,
        Mc5000Operation.STORAGE: 1,
        Mc5000Operation.DISCHARGE: 2,
        Mc5000Operation.CYCLE: 3,
    },
    "nickel": {
        Mc5000Operation.CHARGE: 0,
        Mc5000Operation.REFRESH: 1,
        Mc5000Operation.BREAKIN: 2,
        Mc5000Operation.DISCHARGE: 3,
        Mc5000Operation.CYCLE: 4,
    },
    "zinc": {
        Mc5000Operation.CHARGE: 0,
        Mc5000Operation.DISCHARGE: 1,
        Mc5000Operation.CYCLE: 2,
    },
}

# Maximum (and app default) charge voltage per chemistry, in mV.
MC5000_MAX_CHARGE_VOLTAGE = {
    Mc5000BatteryType.LIION: 4200,
    Mc5000BatteryType.LIION_HV: 4350,
    Mc5000BatteryType.LIFEPO4: 3650,
    Mc5000BatteryType.NIMH: 1650,
    Mc5000BatteryType.NICD: 1650,
    Mc5000BatteryType.ENELOOP: 1650,
    Mc5000BatteryType.NIZN: 1900,
    Mc5000BatteryType.RAM: 1650,
    Mc5000BatteryType.LTO: 2850,
    Mc5000BatteryType.NAION: 4000,
}


def _mc5000_group(battery_type: Mc5000BatteryType) -> str:
    if battery_type in _MC5000_LITHIUM:
        return "lithium"
    if battery_type in _MC5000_NICKEL:
        return "nickel"
    return "zinc"


def mc5000_operation_code(
    battery_type: Mc5000BatteryType, operation: Mc5000Operation
) -> int:
    """Return the wire value of an operation for a chemistry."""
    codes = _MC5000_OPERATION_CODES[_mc5000_group(battery_type)]
    if operation not in codes:
        raise ValueError(f"{operation.name} is not available for {battery_type.name}")
    return codes[operation]


def mc5000_operation_from_code(
    battery_type: Mc5000BatteryType, code: int
) -> Mc5000Operation | None:
    """Decode a wire operation value for a chemistry."""
    for operation, value in _MC5000_OPERATION_CODES[
        _mc5000_group(battery_type)
    ].items():
        if value == code:
            return operation
    return None


@dataclass(frozen=True)
class Mc5000ChannelData:
    type: Mc5000BatteryType = Mc5000BatteryType.LIION
    operation: Mc5000Operation | None = Mc5000Operation.CHARGE
    status: Mc5000ChannelStatus = Mc5000ChannelStatus.STANDBY
    error: Mc5000Error = Mc5000Error.NONE
    time: int = 0
    voltage: float = 0.0
    current: float = 0.0
    capacity: int = 0
    temperature: int = 0
    resistance: int = 0

    def is_working(self) -> bool:
        return self.status in [
            Mc5000ChannelStatus.READY,
            Mc5000ChannelStatus.CHARGE,
            Mc5000ChannelStatus.DISCHARGE,
            Mc5000ChannelStatus.REST,
        ]


@dataclass
class Mc5000State:
    channels: list[Mc5000ChannelData | None] = field(
        default_factory=lambda: [None for _ in range(MC3000_CHANNEL_COUNT)]
    )


@dataclass(frozen=True)
class Mc5000Program:
    """Complete MC5000 work program.

    Sending a program to the MC5000 starts it immediately; there is no separate
    start command. All fields are always sent.
    """

    battery_type: Mc5000BatteryType
    operation: Mc5000Operation
    capacity: int
    charge_current: float
    discharge_current: float
    charge_voltage: int
    discharge_voltage: int
    charge_end_current: int = 100
    discharge_end_current: int = 100
    charge_rest_time: int = 10
    discharge_rest_time: int = 10
    cycle_count: int = 1
    cycle_type: int = 0
    delta_v: int = 6
    trickle_current: int = 0
    maintenance_voltage: int = 0
    protection_temperature: int = 60
    protection_time: int = 0
    maxboost_capacity: int = 300
    turbo: int = 0
    storage_voltage: int = 0
    eneloop_type: int = 0
