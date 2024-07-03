"""Parser for Inkbird BLE advertisements.

This file is shamelessly copied from the following repository:
https://github.com/Ernst79/bleparser/blob/c42ae922e1abed2720c7fac993777e1bd59c0c93/package/bleparser/inkbird.py

MIT License applies.
"""

from __future__ import annotations

import logging
import struct

from bluetooth_data_tools import short_address
from bluetooth_sensor_state_data import BluetoothData
from home_assistant_bluetooth import BluetoothServiceInfo
from sensor_state_data import SensorLibrary

_LOGGER = logging.getLogger(__name__)

BBQ_LENGTH_TO_TYPE = {
    12: ("iBBQ-1", struct.Struct("<h").unpack),
    14: ("iBBQ-2", struct.Struct("<HH").unpack),
    18: ("iBBQ-4", struct.Struct("<hhhh").unpack),
    22: ("iBBQ-6", struct.Struct("<hhhhhh").unpack),
}

TH_NAMES = {"sps", "n0byd"}

INKBIRD_NAMES = {
    **{name: "IBS-TH" for name in TH_NAMES},
    "tps": "IBS-TH2/P01B",
}
INKBIRD_UNPACK = struct.Struct("<hH").unpack

MANUFACTURER_DATA_ID_EXCLUDES = {2}


def convert_temperature(temp: float) -> float:
    """Temperature converter."""
    return temp / 10.0 if temp > 0 else 0


def is_bbq(lower_name: str) -> bool:
    """Check if the device is a BBQ sensor."""
    return bool("xbbq" in lower_name or "ibbq" in lower_name)


class INKBIRDBluetoothDeviceData(BluetoothData):
    """Date update for INKBIRD Bluetooth devices."""

    def _start_update(self, service_info: BluetoothServiceInfo) -> None:
        """Update from BLE advertisement data."""
        _LOGGER.debug("Parsing inkbird BLE advertisement data: %s", service_info)
        if not (manufacturer_data := service_info.manufacturer_data):
            return
        local_name = service_info.name
        address = service_info.address
        lower_name = local_name.lower()
        last_id = list(manufacturer_data)[-1]
        data = int(last_id).to_bytes(2, byteorder="little") + manufacturer_data[last_id]
        msg_length = len(data)
        if (device_type := INKBIRD_NAMES.get(lower_name)) and (
            msg_length == 9
            or "0000fff0-0000-1000-8000-00805f9b34fb" in service_info.service_uuids
        ):
            self.set_device_name(f"{device_type} {short_address(address)}")
            self.set_device_type(device_type)
        elif is_bbq(lower_name) and (bbq_data := BBQ_LENGTH_TO_TYPE.get(msg_length)):
            dev_type, _ = bbq_data
            self.set_device_name(f"{local_name} {short_address(address)}")
            self.set_device_type(f"{local_name[0]}{dev_type[1:]}")
        else:
            return

        self.set_device_manufacturer("INKBIRD")
        excludes = MANUFACTURER_DATA_ID_EXCLUDES if len(manufacturer_data) > 1 else None
        changed_manufacturer_data = self.changed_manufacturer_data(
            service_info, excludes
        )
        if not changed_manufacturer_data or len(changed_manufacturer_data) > 1:
            # If len(changed_manufacturer_data) > 1 it means we switched
            # ble adapters so we do not know which data is the latest
            # and we need to wait for the next update.
            return
        last_id = list(changed_manufacturer_data)[-1]
        data = (
            int(last_id).to_bytes(2, byteorder="little")
            + changed_manufacturer_data[last_id]
        )

        _LOGGER.debug("Parsing INKBIRD BLE advertisement data: %s", data)
        msg_length = len(data)

        if lower_name in INKBIRD_NAMES and msg_length == 9:
            (temp, hum) = INKBIRD_UNPACK(data[0:4])
            bat = int.from_bytes(data[7:8], "little")
            if lower_name in TH_NAMES:
                self.update_predefined_sensor(
                    SensorLibrary.TEMPERATURE__CELSIUS, temp / 100
                )
                self.update_predefined_sensor(
                    SensorLibrary.HUMIDITY__PERCENTAGE, hum / 100
                )
                self.update_predefined_sensor(SensorLibrary.BATTERY__PERCENTAGE, bat)
            elif lower_name == "tps":
                self.update_predefined_sensor(
                    SensorLibrary.TEMPERATURE__CELSIUS, temp / 100
                )
                self.update_predefined_sensor(SensorLibrary.BATTERY__PERCENTAGE, bat)

        elif is_bbq(lower_name) and (bbq_data := BBQ_LENGTH_TO_TYPE.get(msg_length)):
            _, unpacker = bbq_data
            # Some are iBBQ, some are xBBQ
            xvalue = data[10:]
            for idx, temp in enumerate(unpacker(xvalue)):
                num = idx + 1
                self.update_predefined_sensor(
                    SensorLibrary.TEMPERATURE__CELSIUS,
                    convert_temperature(temp),
                    key=f"temperature_probe_{num}",
                    name=f"Temperature Probe {num}",
                )
