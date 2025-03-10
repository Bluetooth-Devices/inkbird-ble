"""
Parser for Inkbird BLE advertisements.

This file is shamelessly copied from the following repository:
https://github.com/Ernst79/bleparser/blob/c42ae922e1abed2720c7fac993777e1bd59c0c93/package/bleparser/inkbird.py

MIT License applies.
"""

from __future__ import annotations

import contextlib
import logging
import struct
from enum import StrEnum
from functools import lru_cache
from typing import TYPE_CHECKING, ClassVar

from bluetooth_data_tools import short_address
from bluetooth_sensor_state_data import BluetoothData
from sensor_state_data import SensorLibrary

if TYPE_CHECKING:
    from collections.abc import Callable

    from home_assistant_bluetooth import BluetoothServiceInfo


_LOGGER = logging.getLogger(__name__)


class Model(StrEnum):
    IBBQ_1 = "iBBQ-1"
    IBBQ_2 = "iBBQ-2"
    IBBQ_4 = "iBBQ-4"
    IBBQ_6 = "iBBQ-6"
    IBS_TH = "IBS-TH"
    IBS_TH2 = "IBS-TH2"
    ITH_13_B = "ITH-13-B"
    ITH_21_B = "ITH-21-B"


MODEL_NAMES = {
    Model.IBBQ_1: "iBBQ-1",
    Model.IBBQ_2: "iBBQ-2",
    Model.IBBQ_4: "iBBQ-4",
    Model.IBBQ_6: "iBBQ-6",
    Model.IBS_TH: "IBS-TH",
    Model.IBS_TH2: "IBS-TH2/P01B",
    Model.ITH_13_B: "ITH-13-B",
    Model.ITH_21_B: "ITH-21-B",
}

BBQ_LENGTH_TO_TYPE = {
    12: (Model.IBBQ_1, struct.Struct("<h").unpack),
    14: (Model.IBBQ_2, struct.Struct("<HH").unpack),
    18: (Model.IBBQ_4, struct.Struct("<hhhh").unpack),
    22: (Model.IBBQ_6, struct.Struct("<hhhhhh").unpack),
}

BBQ_MODELS = {Model.IBBQ_1, Model.IBBQ_2, Model.IBBQ_4, Model.IBBQ_6}

NINE_BYTE_SENSOR_MODELS = {Model.IBS_TH, Model.IBS_TH2}
SIXTEEN_BYTE_SENSOR_MODELS = {Model.ITH_21_B, Model.ITH_13_B}

SENSOR_MODELS = {*NINE_BYTE_SENSOR_MODELS, *SIXTEEN_BYTE_SENSOR_MODELS}

INKBIRD_NAMES = {
    "sps": Model.IBS_TH,  # 9 byte manufacturer data
    "tps": Model.IBS_TH2,  # 9 byte manufacturer data
    "ith-13-b": Model.ITH_13_B,  # 16 byte manufacturer data
    "ith-21-b": Model.ITH_21_B,  # 16 byte manufacturer data
}
INKBIRD_UNPACK = struct.Struct("<hH").unpack

MANUFACTURER_DATA_ID_EXCLUDES = {2}


@lru_cache
def try_parse_model(value: str | Model | None) -> Model | None:
    """
    Try to parse the value into a model.

    Return None if parsing fails.
    """
    with contextlib.suppress(ValueError):
        return Model(value)  # type: ignore[arg-type]
    return None


def convert_temperature(temp: float) -> float:
    """Temperature converter."""
    return temp / 10.0 if temp > 0 else 0


def is_bbq(lower_name: str) -> bool:
    """Check if the device is a BBQ sensor."""
    return bool("xbbq" in lower_name or "ibbq" in lower_name)


class INKBIRDBluetoothDeviceData(BluetoothData):
    """Date update for INKBIRD Bluetooth devices."""

    def __init__(self, device_type: Model | str | None = None) -> None:
        """Initialize the class."""
        super().__init__()
        self._device_type = try_parse_model(device_type)

    @property
    def device_type(self) -> Model | None:
        """Return the device type."""
        return self._device_type

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
        if self._device_type is None:
            # If we do not know the device type yet, try to determine it
            # from the advertisement data.
            if (lower_name in INKBIRD_NAMES) and (
                msg_length in (9, 16)
                or "0000fff0-0000-1000-8000-00805f9b34fb" in service_info.service_uuids
            ):
                self._device_type = INKBIRD_NAMES[lower_name]
            elif is_bbq(lower_name) and msg_length in BBQ_LENGTH_TO_TYPE:
                self._device_type = BBQ_LENGTH_TO_TYPE[msg_length][0]
            else:
                return

        dev_type_name = MODEL_NAMES[self._device_type]
        if self._device_type in BBQ_MODELS:
            self.set_device_name(f"{local_name} {short_address(address)}")
            self.set_device_type(f"{local_name[0]}{dev_type_name[1:]}")
        elif self._device_type in SENSOR_MODELS:
            self.set_device_name(f"{dev_type_name} {short_address(address)}")
            self.set_device_type(dev_type_name)

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
        self._device_type_dispatch[self._device_type](self, data, msg_length)

    def _update_bbq_model(self, data: bytes, msg_length: int) -> None:
        """Update a BBQ sensor model."""
        _, unpacker = BBQ_LENGTH_TO_TYPE[msg_length]
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

    def _update_nine_byte_model(self, data: bytes, msg_length: int) -> None:
        """Update the sensor values for a 9 byte model."""
        (temp, hum) = INKBIRD_UNPACK(data[0:4])
        bat = int.from_bytes(data[7:8], "little")
        self.update_predefined_sensor(SensorLibrary.TEMPERATURE__CELSIUS, temp / 100)
        self.update_predefined_sensor(SensorLibrary.BATTERY__PERCENTAGE, bat)
        # Only some TH2 models have humidity
        if self._device_type == Model.IBS_TH or (
            self._device_type == Model.IBS_TH2 and hum != 0
        ):
            self.update_predefined_sensor(SensorLibrary.HUMIDITY__PERCENTAGE, hum / 100)

    def _update_sixteen_byte_model(self, data: bytes, msg_length: int) -> None:
        """Update the sensor values for a 16 byte model."""
        (temp, hum) = INKBIRD_UNPACK(data[6:10])
        bat = int.from_bytes(data[10:11], "little")
        self.update_predefined_sensor(SensorLibrary.TEMPERATURE__CELSIUS, temp / 10)
        self.update_predefined_sensor(SensorLibrary.BATTERY__PERCENTAGE, bat)
        self.update_predefined_sensor(SensorLibrary.HUMIDITY__PERCENTAGE, hum / 10)

    _device_type_dispatch: ClassVar[
        dict[Model, Callable[[INKBIRDBluetoothDeviceData, bytes, int], None]]
    ]


INKBIRDBluetoothDeviceData._device_type_dispatch = {  # noqa: SLF001
    **{
        model: INKBIRDBluetoothDeviceData._update_bbq_model  # noqa: SLF001
        for model in BBQ_MODELS
    },
    **{
        model: INKBIRDBluetoothDeviceData._update_nine_byte_model  # noqa: SLF001
        for model in NINE_BYTE_SENSOR_MODELS
    },
    **{
        model: INKBIRDBluetoothDeviceData._update_sixteen_byte_model  # noqa: SLF001
        for model in SIXTEEN_BYTE_SENSOR_MODELS
    },
}
