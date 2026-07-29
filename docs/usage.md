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

## Example code

```{eval-rst}
.. literalinclude:: ../examples/run.py
   :language: python
   :linenos:
```
