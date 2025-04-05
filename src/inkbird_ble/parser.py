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
from uuid import UUID

from bleak.exc import BleakCharacteristicNotFoundError, BleakError
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection
from bluetooth_data_tools import monotonic_time_coarse, short_address
from bluetooth_sensor_state_data import BluetoothData, SensorUpdate
from sensor_state_data import SensorLibrary

if TYPE_CHECKING:
    from collections.abc import Callable

    from bleak import BLEDevice
    from home_assistant_bluetooth import BluetoothServiceInfo


_LOGGER = logging.getLogger(__name__)


class Model(StrEnum):
    IBBQ_1 = "iBBQ-1"
    IBBQ_2 = "iBBQ-2"
    IBBQ_4 = "iBBQ-4"
    IBBQ_6 = "iBBQ-6"
    IBS_TH = "IBS-TH"
    IBS_TH2 = "IBS-TH2"
    ITH_11_B = "ITH-11-B"
    ITH_13_B = "ITH-13-B"
    ITH_21_B = "ITH-21-B"


MODEL_NAMES = {
    Model.IBBQ_1: "iBBQ-1",
    Model.IBBQ_2: "iBBQ-2",
    Model.IBBQ_4: "iBBQ-4",
    Model.IBBQ_6: "iBBQ-6",
    Model.IBS_TH: "IBS-TH",
    Model.IBS_TH2: "IBS-TH2/P01B",
    Model.ITH_11_B: "ITH-11-B",
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
SIXTEEN_BYTE_SENSOR_MODELS = {Model.ITH_11_B, Model.ITH_21_B, Model.ITH_13_B}

SENSOR_MODELS = {*NINE_BYTE_SENSOR_MODELS, *SIXTEEN_BYTE_SENSOR_MODELS}


SIXTEEN_BYTE_SENSOR_DATA_SERVICE_UUID = UUID("0000fff0-0000-1000-8000-00805f9b34fb")
SIXTEEN_BYTE_SENSOR_DATA_CHARACTERISTIC_UUID = UUID(
    "0000fff7-0000-1000-8000-00805f9b34fb"
)
NINE_BYTE_SENSOR_DATA_SERVICE_UUID = UUID("0000fff0-0000-1000-8000-00805f9b34fb")
NINE_BYTE_SENSOR_DATA_CHARACTERISTIC_UUID = UUID("0000fff2-0000-1000-8000-00805f9b34fb")

MODEL_GATT = {
    **dict.fromkeys(
        NINE_BYTE_SENSOR_MODELS,
        (NINE_BYTE_SENSOR_DATA_SERVICE_UUID, NINE_BYTE_SENSOR_DATA_CHARACTERISTIC_UUID),
    ),
    **dict.fromkeys(
        SIXTEEN_BYTE_SENSOR_MODELS,
        (
            SIXTEEN_BYTE_SENSOR_DATA_SERVICE_UUID,
            SIXTEEN_BYTE_SENSOR_DATA_CHARACTERISTIC_UUID,
        ),
    ),
}

INKBIRD_NAMES = {
    "sps": Model.IBS_TH,  # 9 byte manufacturer data
    "tps": Model.IBS_TH2,  # 9 byte manufacturer data
    "ith-11-b": Model.ITH_11_B,  # 16 byte manufacturer data
    "ith-13-b": Model.ITH_13_B,  # 16 byte manufacturer data
    "ith-21-b": Model.ITH_21_B,  # 16 byte manufacturer data
}
INKBIRD_UNPACK = struct.Struct("<hH").unpack

MANUFACTURER_DATA_ID_EXCLUDES = {2}

MIN_POLL_INTERVAL = 180.0


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
        # Last time we got a full update from ADV data
        self._last_full_update = 0.0

    @property
    def device_type(self) -> Model | None:
        """Return the device type."""
        return self._device_type

    @property
    def name(self) -> str:
        """Return the device name."""
        if (info := self._get_device_info(None)) and info.name:
            return info.name
        return self._device_type.name if self._device_type else "Unknown"

    def _set_name_and_manufacturer(self, service_info: BluetoothServiceInfo) -> None:
        if self._device_type is None:
            return
        local_name = service_info.name
        address = service_info.address
        dev_type_name = MODEL_NAMES[self._device_type]
        if self._device_type in BBQ_MODELS:
            self.set_device_name(f"{local_name} {short_address(address)}")
            self.set_device_type(f"{local_name[0]}{dev_type_name[1:]}")
        elif self._device_type in SENSOR_MODELS:
            self.set_device_name(f"{dev_type_name} {short_address(address)}")
            self.set_device_type(dev_type_name)

        self.set_device_manufacturer("INKBIRD")

    def _start_update(self, service_info: BluetoothServiceInfo) -> None:
        """Update from BLE advertisement data."""
        _LOGGER.debug("Parsing inkbird BLE advertisement data: %s", service_info)
        if not (manufacturer_data := service_info.manufacturer_data):
            self._set_name_and_manufacturer(service_info)
            return
        last_id = list(manufacturer_data)[-1]
        data = int(last_id).to_bytes(2, byteorder="little") + manufacturer_data[last_id]
        msg_length = len(data)
        if self._device_type is None:
            lower_name = service_info.name.lower()
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
        self._set_name_and_manufacturer(service_info)
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
        self._last_full_update = monotonic_time_coarse()

    def poll_needed(
        self, service_info: BluetoothServiceInfo, last_poll: float | None
    ) -> bool:
        """
        This is called every time we get a service_info for a device or if
        called manually.
        """
        poll_needed = self._supports_polling and (
            not self._last_full_update
            or (monotonic_time_coarse() - self._last_full_update) > MIN_POLL_INTERVAL
        )
        _LOGGER.debug("Poll needed for INKBIRD device %s: %s", self.name, poll_needed)
        return poll_needed

    @property
    def _supports_polling(self) -> bool:
        """Return True if the device supports polling."""
        return self._device_type is not None and self._device_type in SENSOR_MODELS

    async def _async_connect_and_read(self, ble_device: BLEDevice) -> bytes:
        """Connect to the device and read the data characteristic."""
        _LOGGER.debug("Polling INKBIRD device %s", self.name)
        if TYPE_CHECKING:
            assert self._device_type is not None
        service_uuid, characteristic_uuid = MODEL_GATT[self._device_type]
        # Try to connect to the device and read the data characteristic
        # up to 2 times.
        # If the first attempt fails, clear the cache and try again.
        # This is needed because the cache may contain old data.
        # If the second attempt fails, raise an error.
        for attempt in range(2):
            client = await establish_connection(
                BleakClientWithServiceCache,
                ble_device,
                ble_device.name or ble_device.address,
            )
            try:
                service = client.services.get_service(service_uuid)
                char = service.get_characteristic(characteristic_uuid)
                return await client.read_gatt_char(char)
            except BleakCharacteristicNotFoundError:
                await client.clear_cache()
                if attempt == 0:
                    continue
                raise
            except BleakError:
                if attempt == 0:
                    continue
                raise
            finally:
                await client.disconnect()
        raise AssertionError("unreachable")  # pragma: no cover

    async def async_poll(self, ble_device: BLEDevice) -> SensorUpdate:
        """Poll the device for updates."""
        if not self._supports_polling:
            return self._finish_update()
        payload = await self._async_connect_and_read(ble_device)
        if self._device_type in SIXTEEN_BYTE_SENSOR_MODELS:
            (temp, hum) = INKBIRD_UNPACK(payload[5:9])
            bat = payload[9]
            self._update_sixteen_byte_model_from_raw(temp, hum, bat)
        elif self._device_type in NINE_BYTE_SENSOR_MODELS:
            (temp, hum) = INKBIRD_UNPACK(payload[0:4])
            # Battery doesn't seem to be available for these models
            # but it is in the advertisement data
            self._update_nine_byte_model_from_raw(temp, hum, None)

        return self._finish_update()

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
        bat = data[7]
        self._update_nine_byte_model_from_raw(temp, hum, bat)

    def _update_nine_byte_model_from_raw(
        self, temp: int, hum: int, bat: int | None
    ) -> None:
        self.update_predefined_sensor(SensorLibrary.TEMPERATURE__CELSIUS, temp / 100)
        # Only some TH2 models have humidity
        if self._device_type == Model.IBS_TH or (
            self._device_type == Model.IBS_TH2 and hum != 0
        ):
            self.update_predefined_sensor(SensorLibrary.HUMIDITY__PERCENTAGE, hum / 100)
        if bat is not None:
            # Battery is only available in the advertisement data
            # for some models
            self.update_predefined_sensor(SensorLibrary.BATTERY__PERCENTAGE, bat)

    def _update_sixteen_byte_model(self, data: bytes, msg_length: int) -> None:
        """Update the sensor values for a 16 byte model."""
        (temp, hum) = INKBIRD_UNPACK(data[6:10])
        bat = data[10]
        self._update_sixteen_byte_model_from_raw(temp, hum, bat)

    def _update_sixteen_byte_model_from_raw(
        self, temp: int, hum: int, bat: int
    ) -> None:
        self.update_predefined_sensor(SensorLibrary.TEMPERATURE__CELSIUS, temp / 10)
        self.update_predefined_sensor(SensorLibrary.BATTERY__PERCENTAGE, bat)
        self.update_predefined_sensor(SensorLibrary.HUMIDITY__PERCENTAGE, hum / 10)

    _device_type_dispatch: ClassVar[
        dict[Model, Callable[[INKBIRDBluetoothDeviceData, bytes, int], None]]
    ]


INKBIRDBluetoothDeviceData._device_type_dispatch = {  # noqa: SLF001
    **dict.fromkeys(
        BBQ_MODELS,
        INKBIRDBluetoothDeviceData._update_bbq_model,  # noqa: SLF001
    ),
    **dict.fromkeys(
        NINE_BYTE_SENSOR_MODELS,
        INKBIRDBluetoothDeviceData._update_nine_byte_model,  # noqa: SLF001
    ),
    **dict.fromkeys(
        SIXTEEN_BYTE_SENSOR_MODELS,
        INKBIRDBluetoothDeviceData._update_sixteen_byte_model,  # noqa: SLF001
    ),
}
