# Usage

To use this package:

- import the package
- search for a compatible device using Bleak
- create a new `Mc3000` instance based on the found `BLEDevice`
- call `update()` to fetch the latest device state
- call `start_charge()` or `stop_charge()` to start or stop charging a battery in one of the four channels (indexed 0-3)
- call `write_program()` to upload a complete `Mc3000Program` before starting

The MC3000 protocol cannot change only the battery chemistry. Program uploads
always include the currents, voltage limits, termination values and protection
settings. Validate every field for the installed battery.

```python
from skyrc_ble.models import BatteryType, ChannelMode, Mc3000Program

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
    delta_v=10,
    trickle_current=10,
    maintenance_voltage=4150,
    protection_temperature=19,
)

await mc3000.write_program(0, program)
await mc3000.start_charge(0)
```

## MC5000

The MC5000 uses its own `Mc5000` class. Sending a program starts it right away,
so there is no separate start call. Channels are indexed 0-3.

```python
from skyrc_ble import Mc5000, Mc5000BatteryType, Mc5000Operation, Mc5000Program

mc5000 = Mc5000(ble_device)  # advertised name starts with "#Charger"
await mc5000.update()
print(mc5000.state.channels[0])

program = Mc5000Program(
    battery_type=Mc5000BatteryType.NIMH,
    operation=Mc5000Operation.CHARGE,
    capacity=2000,
    charge_current=0.3,
    discharge_current=0.5,
    charge_voltage=1650,
    discharge_voltage=900,
)
await mc5000.start_program(0, program)
await mc5000.stop_charge(0)
```

## Example code

```{eval-rst}
.. literalinclude:: ../examples/run.py
   :language: python
   :linenos:
```
