from __future__ import annotations

__version__ = "3.0.0"

from .const import (
    MC3000_BLUETOOTH_NAMES,
    MC3000_CHANNEL_COUNT,
    MC3000_CHARACTERISTIC_UUID,
    MC3000_SERVICE_UUID,
    MC5000_BLUETOOTH_NAME_PREFIX,
)
from .device import SkyRcDevice
from .mc3000 import Mc3000, Mc3000BasicData, Mc3000ChannelData, Mc3000State
from .mc5000 import Mc5000
from .models import (
    Mc3000Program,
    Mc3000VoltageCurveData,
    Mc5000BatteryType,
    Mc5000ChannelData,
    Mc5000Operation,
    Mc5000Program,
    Mc5000State,
)

__all__ = [
    "SkyRcDevice",
    "MC3000_BLUETOOTH_NAMES",
    "MC3000_SERVICE_UUID",
    "MC3000_CHARACTERISTIC_UUID",
    "MC3000_CHANNEL_COUNT",
    "Mc3000",
    "Mc3000BasicData",
    "Mc3000ChannelData",
    "Mc3000State",
    "Mc3000Program",
    "Mc3000VoltageCurveData",
    "MC5000_BLUETOOTH_NAME_PREFIX",
    "Mc5000",
    "Mc5000BatteryType",
    "Mc5000ChannelData",
    "Mc5000Operation",
    "Mc5000Program",
    "Mc5000State",
]
