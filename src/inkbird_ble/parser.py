"""
Parser for Inkbird BLE advertisements.

This file is shamelessly copied from the following repository:
https://github.com/Ernst79/bleparser/blob/c42ae922e1abed2720c7fac993777e1bd59c0c93/package/bleparser/inkbird.py

MIT License applies.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import struct
from dataclasses import dataclass
from enum import Enum, StrEnum, auto
from functools import lru_cache
from typing import TYPE_CHECKING, Any, ClassVar
from uuid import UUID

from bleak.exc import BleakCharacteristicNotFoundError, BleakError
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection
from bluetooth_data_tools import monotonic_time_coarse, short_address
from bluetooth_sensor_state_data import BluetoothData, SensorUpdate
from sensor_state_data import SensorLibrary, Units

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

    from bleak import BleakGATTCharacteristic, BLEDevice
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
    IAM_T1 = "IAM-T1"


class ModelType(Enum):
    BBQ = auto()
    SENSOR = auto()


@dataclass(frozen=True)
class ModelInfo:
    """Model information."""

    name: str
    model_type: ModelType
    local_name: str | None
    message_length: int
    unpacker: Callable[[bytes], tuple[int, ...]]
    service_uuid: UUID | None
    characteristic_uuid: UUID | None
    notify_uuid: UUID | None
    use_local_name_for_device: bool
    parse_adv: bool


INKBIRD_SERVICE_UUID = UUID("0000fff0-0000-1000-8000-00805f9b34fb")
SIXTEEN_BYTE_SENSOR_DATA_CHARACTERISTIC_UUID = UUID(
    "0000fff7-0000-1000-8000-00805f9b34fb"
)
NINE_BYTE_SENSOR_DATA_CHARACTERISTIC_UUID = UUID("0000fff2-0000-1000-8000-00805f9b34fb")
IAM_T1_CHARACTERISTIC_UUID = UUID("0000fff4-0000-1000-8000-00805f9b34fb")

INKBIRD_UNPACK = struct.Struct("<hH").unpack

MODEL_INFO = {
    Model.IBBQ_1: ModelInfo(
        name="iBBQ-1",
        model_type=ModelType.BBQ,
        local_name=None,
        message_length=12,
        unpacker=struct.Struct("<h").unpack,
        service_uuid=None,
        characteristic_uuid=None,
        notify_uuid=None,
        use_local_name_for_device=True,
        parse_adv=True,
    ),
    Model.IBBQ_2: ModelInfo(
        name="iBBQ-2",
        model_type=ModelType.BBQ,
        local_name=None,
        message_length=14,
        unpacker=struct.Struct("<HH").unpack,
        service_uuid=None,
        characteristic_uuid=None,
        notify_uuid=None,
        use_local_name_for_device=True,
        parse_adv=True,
    ),
    Model.IBBQ_4: ModelInfo(
        name="iBBQ-4",
        model_type=ModelType.BBQ,
        local_name=None,
        message_length=18,
        unpacker=struct.Struct("<hhhh").unpack,
        service_uuid=None,
        characteristic_uuid=None,
        notify_uuid=None,
        use_local_name_for_device=True,
        parse_adv=True,
    ),
    Model.IBBQ_6: ModelInfo(
        name="iBBQ-6",
        model_type=ModelType.BBQ,
        local_name=None,
        message_length=22,
        unpacker=struct.Struct("<hhhhhh").unpack,
        service_uuid=None,
        characteristic_uuid=None,
        notify_uuid=None,
        use_local_name_for_device=True,
        parse_adv=True,
    ),
    Model.IBS_TH: ModelInfo(
        name="IBS-TH",
        model_type=ModelType.SENSOR,
        local_name="sps",
        message_length=9,
        unpacker=INKBIRD_UNPACK,
        service_uuid=INKBIRD_SERVICE_UUID,
        characteristic_uuid=NINE_BYTE_SENSOR_DATA_CHARACTERISTIC_UUID,
        notify_uuid=None,
        use_local_name_for_device=False,
        parse_adv=True,
    ),
    Model.IBS_TH2: ModelInfo(
        name="IBS-TH2/P01B",
        model_type=ModelType.SENSOR,
        local_name="tps",
        message_length=9,
        unpacker=INKBIRD_UNPACK,
        service_uuid=INKBIRD_SERVICE_UUID,
        characteristic_uuid=NINE_BYTE_SENSOR_DATA_CHARACTERISTIC_UUID,
        notify_uuid=None,
        use_local_name_for_device=False,
        parse_adv=True,
    ),
    Model.ITH_11_B: ModelInfo(
        name="ITH-11-B",
        model_type=ModelType.SENSOR,
        local_name="ith-11-b",
        message_length=16,
        unpacker=INKBIRD_UNPACK,
        service_uuid=INKBIRD_SERVICE_UUID,
        characteristic_uuid=SIXTEEN_BYTE_SENSOR_DATA_CHARACTERISTIC_UUID,
        notify_uuid=None,
        use_local_name_for_device=False,
        parse_adv=True,
    ),
    Model.ITH_13_B: ModelInfo(
        name="ITH-13-B",
        model_type=ModelType.SENSOR,
        local_name="ith-13-b",
        message_length=16,
        unpacker=INKBIRD_UNPACK,
        service_uuid=INKBIRD_SERVICE_UUID,
        characteristic_uuid=SIXTEEN_BYTE_SENSOR_DATA_CHARACTERISTIC_UUID,
        notify_uuid=None,
        use_local_name_for_device=False,
        parse_adv=True,
    ),
    Model.ITH_21_B: ModelInfo(
        name="ITH-21-B",
        model_type=ModelType.SENSOR,
        local_name="ith-21-b",
        message_length=16,
        unpacker=INKBIRD_UNPACK,
        service_uuid=INKBIRD_SERVICE_UUID,
        characteristic_uuid=SIXTEEN_BYTE_SENSOR_DATA_CHARACTERISTIC_UUID,
        notify_uuid=None,
        use_local_name_for_device=False,
        parse_adv=True,
    ),
    Model.IAM_T1: ModelInfo(
        name="IAM-T1",
        model_type=ModelType.SENSOR,
        local_name="ink@iam-t1",
        message_length=17,
        unpacker=INKBIRD_UNPACK,
        service_uuid=UUID("0000ffe0-0000-1000-8000-00805f9b34fb"),
        characteristic_uuid=None,
        notify_uuid=UUID("0000ffe4-0000-1000-8000-00805f9b34fb"),
        use_local_name_for_device=False,
        parse_adv=False,
    ),
}

INKBIRD_NAMES = {
    dev_info.local_name: dev_type
    for dev_type, dev_info in MODEL_INFO.items()
    if dev_info.local_name is not None
}

BBQ_MODELS = {
    model_type
    for model_type, model_info in MODEL_INFO.items()
    if model_info.model_type is ModelType.BBQ
}
SENSOR_MSG_LENGTHS = {
    model_info.message_length
    for model_info in MODEL_INFO.values()
    if model_info.model_type is ModelType.SENSOR
}
NINE_BYTE_SENSOR_MODELS = {
    model_type
    for model_type, model_info in MODEL_INFO.items()
    if model_info.model_type is ModelType.SENSOR and model_info.message_length == 9  # noqa: PLR2004
}
SIXTEEN_BYTE_SENSOR_MODELS = {
    model_type
    for model_type, model_info in MODEL_INFO.items()
    if model_info.model_type is ModelType.SENSOR and model_info.message_length == 16  # noqa: PLR2004
}
SENSOR_MODELS = {
    *NINE_BYTE_SENSOR_MODELS,
    *SIXTEEN_BYTE_SENSOR_MODELS,
}
BBQ_LENGTH_TO_TYPE = {
    model_info.message_length: model_type
    for model_type, model_info in MODEL_INFO.items()
    if model_info.model_type is ModelType.BBQ
}
NOTIFY_MODELS = {
    model_type
    for model_type, model_info in MODEL_INFO.items()
    if model_info.notify_uuid is not None
}

MANUFACTURER_DATA_ID_EXCLUDES = {2}

MIN_POLL_INTERVAL = 180.0


async def async_connect_action(
    ble_device: BLEDevice,
    action: Callable[
        [BleakClientWithServiceCache], Coroutine[None, None, bytes | None]
    ],
) -> bytes | None:
    """Connect to the device and read the data characteristic."""
    for attempt in range(2):
        client = await establish_connection(
            BleakClientWithServiceCache,
            ble_device,
            ble_device.name or ble_device.address,
        )
        try:
            return await action(client)
        except BleakCharacteristicNotFoundError:
            if attempt == 0:
                await client.clear_cache()
                continue
            raise
        except BleakError:
            if attempt == 0:
                continue
            raise
        finally:
            await client.disconnect()
    raise AssertionError("unreachable")  # pragma: no cover


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

    def __init__(
        self,
        device_type: Model | str | None = None,
        device_data: dict[str, Any] | None = None,
        update_callback: Callable[[SensorUpdate], None] | None = None,
        device_data_changed_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        """Initialize the class."""
        super().__init__()
        self._device_type = try_parse_model(device_type)
        # Last time we got a full update from ADV data
        self._last_full_update = 0.0
        self._notify_task: asyncio.Task[None] | None = None
        self._running = True
        self._device_data = device_data.copy() if device_data else {}
        self._update_callback = update_callback
        self._device_data_changed_callback = device_data_changed_callback

    @property
    def uses_notify(self) -> bool:
        """Return True if the device uses notifications."""
        return self._device_type in NOTIFY_MODELS

    async def async_start(
        self, service_info: BluetoothServiceInfo, ble_device: BLEDevice
    ) -> None:
        """Start the device."""
        self._set_name_and_manufacturer(service_info)
        assert self._device_type is not None
        self._running = True
        if self._device_type not in NOTIFY_MODELS:
            return
        self._notify_task = asyncio.create_task(self._async_start_notify(ble_device))

    async def async_stop(self) -> None:
        """Stop the device."""
        self._running = False
        if self._notify_task:
            self._notify_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._notify_task
            self._notify_task = None

    async def _async_start_notify(self, ble_device: BLEDevice) -> None:
        """Start the notification loop."""
        while self._running:
            _LOGGER.debug("Starting notification for %s", self.name)
            try:
                await async_connect_action(ble_device, self._async_notify_action)
            except (BleakError, TimeoutError) as err:
                _LOGGER.debug("Error starting notification: %s", str(err) or type(err))
            _LOGGER.debug("Notification loop for %s finished", self.name)
            # Wait for 5 seconds before trying again
            # This is needed to avoid a busy loop if the device is not
            # available
            await asyncio.sleep(5)

    async def _async_notify_action(self, client: BleakClientWithServiceCache) -> None:
        assert self._device_type is not None
        dev_info = MODEL_INFO[self._device_type]
        notify_uuid = dev_info.notify_uuid
        loop = asyncio.get_running_loop()
        disconnect_future = loop.create_future()

        def _resolve_disconnect_callback(_: BleakClientWithServiceCache) -> None:
            if not disconnect_future.done():
                disconnect_future.set_result(None)

        client.set_disconnected_callback(_resolve_disconnect_callback)
        await client.start_notify(notify_uuid, self._notify_callback)
        await disconnect_future  # wait for disconnect

    def _notify_callback(
        self, sender: BleakGATTCharacteristic, data: bytearray
    ) -> None:
        """Callback for notifications."""
        _LOGGER.debug("Received notification from %s: %s", sender, data)
        if not self._running or self._device_type != Model.IAM_T1:
            return
        # IAM_T1
        if len(data) == 12:  # noqa: PLR2004
            in_f = data[10] & 0xF
            unit = Units.TEMP_FAHRENHEIT if in_f else Units.TEMP_CELSIUS
            _LOGGER.debug("IAM-T1 unit: %s (%s)", unit, self._device_data)
            if unit != self._device_data.get("temp_unit"):
                self._device_data["temp_unit"] = unit
                assert self._device_data_changed_callback is not None
                _LOGGER.debug("IAM-T1 unit changed: %s (%s)", unit, self._device_data)
                self._device_data_changed_callback(self._device_data)
        elif len(data) == 16:  # noqa: PLR2004
            sign = data[4] & 0xF
            temp = data[5] << 8 | data[6]
            signed_temp = (temp if sign == 0 else -temp) / 10
            _LOGGER.debug("IAM-T1 temperature: %s (%s)", signed_temp, self._device_data)
            if self._device_data.get("temp_unit") == Units.TEMP_FAHRENHEIT:
                # Convert to Celsius
                signed_temp = round((signed_temp - 32) * 5 / 9, 2)
            self.update_predefined_sensor(
                SensorLibrary.TEMPERATURE__CELSIUS, signed_temp
            )
            self.update_predefined_sensor(
                SensorLibrary.HUMIDITY__PERCENTAGE, (data[7] << 8 | data[8]) / 10
            )
            self.update_predefined_sensor(
                SensorLibrary.CO2__CONCENTRATION_PARTS_PER_MILLION,
                data[9] << 8 | data[10],
            )
            self.update_predefined_sensor(
                SensorLibrary.PRESSURE__HPA, data[11] << 8 | data[12]
            )
            assert self._update_callback is not None
            self._update_callback(self._finish_update())
        else:
            _LOGGER.debug(
                "Unexpected notification length %d from %s", len(data), sender
            )

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
        self.set_device_manufacturer("INKBIRD")
        local_name = service_info.name
        address = service_info.address
        dev_info = MODEL_INFO[self._device_type]
        dev_type_name = dev_info.name
        if dev_info.use_local_name_for_device:
            self.set_device_name(f"{local_name} {short_address(address)}")
            self.set_device_type(f"{local_name[0]}{dev_type_name[1:]}")
        else:
            self.set_device_name(f"{dev_type_name} {short_address(address)}")
            self.set_device_type(dev_type_name)

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
                msg_length in SENSOR_MSG_LENGTHS
                or "0000fff0-0000-1000-8000-00805f9b34fb" in service_info.service_uuids
            ):
                self._device_type = INKBIRD_NAMES[lower_name]
            elif is_bbq(lower_name) and msg_length in BBQ_LENGTH_TO_TYPE:
                self._device_type = BBQ_LENGTH_TO_TYPE[msg_length]
            elif 12628 in manufacturer_data and manufacturer_data[12628].startswith(  # noqa: PLR2004
                b"AC-6200"
            ):
                # AC-6200
                self._device_type = Model.IAM_T1
            else:
                return
        self._set_name_and_manufacturer(service_info)
        if not MODEL_INFO[self._device_type].parse_adv:
            # Device does not support parsing advertisement data
            return
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
        # Try to connect to the device and read the data characteristic
        # up to 2 times.
        # If the first attempt fails, clear the cache and try again.
        # This is needed because the cache may contain old data.
        # If the second attempt fails, raise an error.
        data = await async_connect_action(ble_device, self._async_poll_action)
        assert data is not None
        return data

    async def _async_poll_action(
        self, client: BleakClientWithServiceCache
    ) -> bytes | None:
        """Poll the device for updates."""
        if TYPE_CHECKING:
            assert self._device_type is not None
        dev_info = MODEL_INFO[self._device_type]
        service = client.services.get_service(dev_info.service_uuid)
        char = service.get_characteristic(dev_info.characteristic_uuid)
        return await client.read_gatt_char(char)

    async def async_poll(self, ble_device: BLEDevice) -> SensorUpdate:
        """Poll the device for updates."""
        payload = await self._async_connect_and_read(ble_device)
        if self._device_type in SIXTEEN_BYTE_SENSOR_MODELS:
            self._update_sixteen_byte_model_from_raw(payload[5:9], payload[9])
        elif self._device_type in NINE_BYTE_SENSOR_MODELS:
            # Battery doesn't seem to be available for these models
            # but it is in the advertisement data
            self._update_nine_byte_model_from_raw(payload[0:4], None)
        return self._finish_update()

    def _update_bbq_model(self, data: bytes, msg_length: int) -> None:
        """Update a BBQ sensor model."""
        # Some are iBBQ, some are xBBQ
        if TYPE_CHECKING:
            assert self._device_type is not None
        xvalue = data[10:]
        for idx, temp in enumerate(MODEL_INFO[self._device_type].unpacker(xvalue)):
            num = idx + 1
            self.update_predefined_sensor(
                SensorLibrary.TEMPERATURE__CELSIUS,
                convert_temperature(temp),
                key=f"temperature_probe_{num}",
                name=f"Temperature Probe {num}",
            )

    def _update_nine_byte_model(self, data: bytes, msg_length: int) -> None:
        """Update the sensor values for a 9 byte model."""
        self._update_nine_byte_model_from_raw(data[0:4], data[7])

    def _update_nine_byte_model_from_raw(
        self, temp_hum_bytes: bytes, bat: int | None
    ) -> None:
        if TYPE_CHECKING:
            assert self._device_type is not None
        temp, hum = MODEL_INFO[self._device_type].unpacker(temp_hum_bytes)
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
        self._update_sixteen_byte_model_from_raw(data[6:10], data[10])

    def _update_sixteen_byte_model_from_raw(
        self, temp_hum_bytes: bytes, bat: int
    ) -> None:
        """Update the sensor values for a 16 byte model."""
        if TYPE_CHECKING:
            assert self._device_type is not None
        temp, hum = MODEL_INFO[self._device_type].unpacker(temp_hum_bytes)
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
