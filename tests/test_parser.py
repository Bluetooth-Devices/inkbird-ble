from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from bleak.backends.device import BLEDevice
from bleak.exc import BleakCharacteristicNotFoundError, BleakError
from bluetooth_data_tools import monotonic_time_coarse
from bluetooth_sensor_state_data import DeviceClass, SensorUpdate
from habluetooth import BluetoothServiceInfoBleak
from sensor_state_data import (
    DeviceKey,
    SensorDescription,
    SensorDeviceClass,
    SensorDeviceInfo,
    SensorValue,
    Units,
)

import inkbird_ble
from inkbird_ble import INKBIRDBluetoothDeviceData as PublicData
from inkbird_ble import Model as PublicModel
from inkbird_ble.parser import (
    IHT_2PB_NOTIFY_UUID,
    IHT_2PB_WRITE_UUID,
    MAX_PLAUSIBLE_HUMIDITY,
    MIN_POLL_INTERVAL,
    SENSOR_MODELS,
    INKBIRDBluetoothDeviceData,
    Model,
)

from . import async_fire_time_changed

if TYPE_CHECKING:
    from collections.abc import Callable
    from uuid import UUID


def test_can_create():
    parser = INKBIRDBluetoothDeviceData()
    assert parser.name == "Unknown"


def test_model_is_public_export():
    """``Model`` is part of the documented public API.

    The usage docs reference ``Model.IBS_TH`` and the constructor accepts a
    ``Model | str | None`` device_type, so ``Model`` must be importable from
    the package root — not only from the private ``inkbird_ble.parser`` path.
    """
    assert PublicModel is Model
    assert "Model" in inkbird_ble.__all__
    assert PublicModel.IBS_TH.value == "IBS-TH"


def test_constructor_accepts_publicly_exported_model():
    parser = PublicData(PublicModel.IBS_TH)
    assert parser.device_type is PublicModel.IBS_TH


def make_bluetooth_service_info(  # noqa: PLR0913
    name: str,
    manufacturer_data: dict[int, bytes],
    service_uuids: list[str],
    address: str,
    rssi: int,
    service_data: dict[UUID, bytes],
    source: str,
    tx_power: int = 0,
    raw: bytes | None = None,
) -> BluetoothServiceInfoBleak:
    return BluetoothServiceInfoBleak(
        name=name,
        manufacturer_data=manufacturer_data,
        service_uuids=service_uuids,
        address=address,
        rssi=rssi,
        service_data=service_data,
        source=source,
        device=BLEDevice(
            name=name,
            address=address,
            details={},
        ),
        time=monotonic_time_coarse(),
        advertisement=None,
        connectable=True,
        tx_power=tx_power,
        raw=raw,
    )


def test_unsupported():
    parser = INKBIRDBluetoothDeviceData()
    service_info = make_bluetooth_service_info(
        name="x",
        manufacturer_data={},
        service_uuids=["0000fff0-0000-1000-8000-00805f9b34fb"],
        address="aa:bb:cc:dd:ee:ff",
        rssi=-60,
        service_data={},
        source="local",
    )
    assert parser.supported(service_info) is False
    assert parser.device_type is None


def test_unsupported_with_manufacturer_data():
    parser = INKBIRDBluetoothDeviceData()
    service_info = make_bluetooth_service_info(
        name="x",
        manufacturer_data={2044: b"\xc7\x12\x00\xc8=V\x06"},
        service_uuids=["0000fff0-0000-1000-8000-00805f9b34fb"],
        address="aa:bb:cc:dd:ee:ff",
        rssi=-60,
        service_data={},
        source="local",
    )
    assert parser.supported(service_info) is False
    assert parser.device_type is None


def test_raw_manufacturer_data():
    parser = INKBIRDBluetoothDeviceData()
    service_info = make_bluetooth_service_info(
        name="sps",
        manufacturer_data={1: b"\x00"},
        service_uuids=["0000fff0-0000-1000-8000-00805f9b34fb"],
        address="aa:bb:cc:dd:ee:ff",
        rssi=-60,
        service_data={},
        source="local",
        raw=b"\x0a\xff\xfc\x07\xc7\x12\x00\xc8=V\x06",
    )
    assert parser.supported(service_info) is True
    assert parser.device_type == Model.IBS_TH
    assert parser.update(service_info) == SensorUpdate(
        title=None,
        devices={
            None: SensorDeviceInfo(
                name="IBS-TH EEFF",
                model="IBS-TH",
                manufacturer="INKBIRD",
                sw_version=None,
                hw_version=None,
            )
        },
        entity_descriptions={
            DeviceKey(key="signal_strength", device_id=None): SensorDescription(
                device_key=DeviceKey(key="signal_strength", device_id=None),
                device_class=SensorDeviceClass.SIGNAL_STRENGTH,
                native_unit_of_measurement=Units.SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
            ),
            DeviceKey(key="temperature", device_id=None): SensorDescription(
                device_key=DeviceKey(key="temperature", device_id=None),
                device_class=SensorDeviceClass.TEMPERATURE,
                native_unit_of_measurement=Units.TEMP_CELSIUS,
            ),
            DeviceKey(key="humidity", device_id=None): SensorDescription(
                device_key=DeviceKey(key="humidity", device_id=None),
                device_class=SensorDeviceClass.HUMIDITY,
                native_unit_of_measurement=Units.PERCENTAGE,
            ),
            DeviceKey(key="battery", device_id=None): SensorDescription(
                device_key=DeviceKey(key="battery", device_id=None),
                device_class=SensorDeviceClass.BATTERY,
                native_unit_of_measurement=Units.PERCENTAGE,
            ),
        },
        entity_values={
            DeviceKey(key="signal_strength", device_id=None): SensorValue(
                device_key=DeviceKey(key="signal_strength", device_id=None),
                name="Signal Strength",
                native_value=-60,
            ),
            DeviceKey(key="temperature", device_id=None): SensorValue(
                device_key=DeviceKey(key="temperature", device_id=None),
                name="Temperature",
                native_value=20.44,
            ),
            DeviceKey(key="humidity", device_id=None): SensorValue(
                device_key=DeviceKey(key="humidity", device_id=None),
                name="Humidity",
                native_value=48.07,
            ),
            DeviceKey(key="battery", device_id=None): SensorValue(
                device_key=DeviceKey(key="battery", device_id=None),
                name="Battery",
                native_value=86,
            ),
        },
        binary_entity_descriptions={},
        binary_entity_values={},
        events={},
    )


def test_sps_with_invalid_model_passed():
    parser = INKBIRDBluetoothDeviceData("invalid")
    service_info = make_bluetooth_service_info(
        name="sps",
        manufacturer_data={2044: b"\xc7\x12\x00\xc8=V\x06"},
        service_uuids=["0000fff0-0000-1000-8000-00805f9b34fb"],
        address="aa:bb:cc:dd:ee:ff",
        rssi=-60,
        service_data={},
        source="local",
    )
    parser.update(service_info)
    assert parser.device_type == Model.IBS_TH


def test_sps():
    parser = INKBIRDBluetoothDeviceData()
    service_info = make_bluetooth_service_info(
        name="sps",
        manufacturer_data={2044: b"\xc7\x12\x00\xc8=V\x06"},
        service_uuids=["0000fff0-0000-1000-8000-00805f9b34fb"],
        address="aa:bb:cc:dd:ee:ff",
        rssi=-60,
        service_data={},
        source="local",
    )
    result = parser.update(service_info)
    assert parser.device_type == Model.IBS_TH
    assert result == SensorUpdate(
        title=None,
        devices={
            None: SensorDeviceInfo(
                name="IBS-TH EEFF",
                model="IBS-TH",
                manufacturer="INKBIRD",
                sw_version=None,
                hw_version=None,
            )
        },
        entity_descriptions={
            DeviceKey(key="battery", device_id=None): SensorDescription(
                device_key=DeviceKey(key="battery", device_id=None),
                device_class=DeviceClass.BATTERY,
                native_unit_of_measurement=Units.PERCENTAGE,
            ),
            DeviceKey(key="signal_strength", device_id=None): SensorDescription(
                device_key=DeviceKey(key="signal_strength", device_id=None),
                device_class=DeviceClass.SIGNAL_STRENGTH,
                native_unit_of_measurement=Units.SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
            ),
            DeviceKey(key="temperature", device_id=None): SensorDescription(
                device_key=DeviceKey(key="temperature", device_id=None),
                device_class=DeviceClass.TEMPERATURE,
                native_unit_of_measurement=Units.TEMP_CELSIUS,
            ),
            DeviceKey(key="humidity", device_id=None): SensorDescription(
                device_key=DeviceKey(key="humidity", device_id=None),
                device_class=DeviceClass.HUMIDITY,
                native_unit_of_measurement=Units.PERCENTAGE,
            ),
        },
        entity_values={
            DeviceKey(key="battery", device_id=None): SensorValue(
                device_key=DeviceKey(key="battery", device_id=None),
                native_value=86,
                name="Battery",
            ),
            DeviceKey(key="signal_strength", device_id=None): SensorValue(
                device_key=DeviceKey(key="signal_strength", device_id=None),
                name="Signal Strength",
                native_value=-60,
            ),
            DeviceKey(key="temperature", device_id=None): SensorValue(
                device_key=DeviceKey(key="temperature", device_id=None),
                name="Temperature",
                native_value=20.44,
            ),
            DeviceKey(key="humidity", device_id=None): SensorValue(
                device_key=DeviceKey(key="humidity", device_id=None),
                native_value=48.07,
                name="Humidity",
            ),
        },
    )


def test_unknown_sps():
    parser = INKBIRDBluetoothDeviceData()
    service_info = make_bluetooth_service_info(
        name="sps",
        manufacturer_data={
            2063: b"\xc0\x12\x01p\x08d\x06",
            2083: b"\x12\x01w\x08d\x06",
        },
        service_uuids=["0000fff0-0000-1000-8000-00805f9b34fb"],
        address="49:21:09:09:65:49",
        rssi=-54,
        service_data={},
        source="local",
    )
    assert parser.supported(service_info) is True
    assert parser.device_type == Model.IBS_TH


def test_sps_variant():
    parser = INKBIRDBluetoothDeviceData()
    service_info = make_bluetooth_service_info(
        name="sps",
        manufacturer_data={
            2083: b"\x12\x01q\x08d\x06",
        },
        service_uuids=["0000fff0-0000-1000-8000-00805f9b34fb"],
        address="49:21:09:09:65:49",
        rssi=-96,
        service_data={},
        source="local",
    )
    assert parser.supported(service_info) is True
    assert parser.device_type == Model.IBS_TH


def test_sps_variant2():
    parser = INKBIRDBluetoothDeviceData()
    service_info = make_bluetooth_service_info(
        name="sps",
        manufacturer_data={
            2363: b"\xd0\x13\x00\xce\x90d\x06",
        },
        service_uuids=["0000fff0-0000-1000-8000-00805f9b34fb"],
        address="49:22:03:25:01:46",
        rssi=-96,
        service_data={},
        source="local",
    )
    assert parser.supported(service_info) is True
    assert parser.device_type == Model.IBS_TH
    parser = INKBIRDBluetoothDeviceData()
    result = parser.update(service_info)
    assert result == SensorUpdate(
        title=None,
        devices={
            None: SensorDeviceInfo(
                name="IBS-TH 0146",
                model="IBS-TH",
                manufacturer="INKBIRD",
                sw_version=None,
                hw_version=None,
            )
        },
        entity_descriptions={
            DeviceKey(key="battery", device_id=None): SensorDescription(
                device_key=DeviceKey(key="battery", device_id=None),
                device_class=SensorDeviceClass.BATTERY,
                native_unit_of_measurement=Units.PERCENTAGE,
            ),
            DeviceKey(key="humidity", device_id=None): SensorDescription(
                device_key=DeviceKey(key="humidity", device_id=None),
                device_class=SensorDeviceClass.HUMIDITY,
                native_unit_of_measurement=Units.PERCENTAGE,
            ),
            DeviceKey(key="signal_strength", device_id=None): SensorDescription(
                device_key=DeviceKey(key="signal_strength", device_id=None),
                device_class=SensorDeviceClass.SIGNAL_STRENGTH,
                native_unit_of_measurement=Units.SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
            ),
            DeviceKey(key="temperature", device_id=None): SensorDescription(
                device_key=DeviceKey(key="temperature", device_id=None),
                device_class=SensorDeviceClass.TEMPERATURE,
                native_unit_of_measurement=Units.TEMP_CELSIUS,
            ),
        },
        entity_values={
            DeviceKey(key="battery", device_id=None): SensorValue(
                device_key=DeviceKey(key="battery", device_id=None),
                name="Battery",
                native_value=100,
            ),
            DeviceKey(key="humidity", device_id=None): SensorValue(
                device_key=DeviceKey(key="humidity", device_id=None),
                name="Humidity",
                native_value=50.72,
            ),
            DeviceKey(key="signal_strength", device_id=None): SensorValue(
                device_key=DeviceKey(key="signal_strength", device_id=None),
                name="Signal Strength",
                native_value=-96,
            ),
            DeviceKey(key="temperature", device_id=None): SensorValue(
                device_key=DeviceKey(key="temperature", device_id=None),
                name="Temperature",
                native_value=23.63,
            ),
        },
        binary_entity_descriptions={},
        binary_entity_values={},
        events={},
    )


def test_sps_th2_dupe_updates():
    parser = INKBIRDBluetoothDeviceData()
    service_info = make_bluetooth_service_info(
        name="sps",
        manufacturer_data={2248: b"\x84\x14\x00\x88\x99d\x06"},
        service_uuids=["0000fff0-0000-1000-8000-00805f9b34fb"],
        address="aa:bb:cc:dd:ee:ff",
        rssi=-60,
        service_data={},
        source="local",
    )
    result = parser.update(service_info)
    assert parser.device_type == Model.IBS_TH
    assert result == SensorUpdate(
        title=None,
        devices={
            None: SensorDeviceInfo(
                name="IBS-TH EEFF",
                model="IBS-TH",
                manufacturer="INKBIRD",
                sw_version=None,
                hw_version=None,
            )
        },
        entity_descriptions={
            DeviceKey(key="battery", device_id=None): SensorDescription(
                device_key=DeviceKey(key="battery", device_id=None),
                device_class=DeviceClass.BATTERY,
                native_unit_of_measurement=Units.PERCENTAGE,
            ),
            DeviceKey(key="signal_strength", device_id=None): SensorDescription(
                device_key=DeviceKey(key="signal_strength", device_id=None),
                device_class=DeviceClass.SIGNAL_STRENGTH,
                native_unit_of_measurement=Units.SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
            ),
            DeviceKey(key="temperature", device_id=None): SensorDescription(
                device_key=DeviceKey(key="temperature", device_id=None),
                device_class=DeviceClass.TEMPERATURE,
                native_unit_of_measurement=Units.TEMP_CELSIUS,
            ),
            DeviceKey(key="humidity", device_id=None): SensorDescription(
                device_key=DeviceKey(key="humidity", device_id=None),
                device_class=DeviceClass.HUMIDITY,
                native_unit_of_measurement=Units.PERCENTAGE,
            ),
        },
        entity_values={
            DeviceKey(key="battery", device_id=None): SensorValue(
                device_key=DeviceKey(key="battery", device_id=None),
                native_value=100,
                name="Battery",
            ),
            DeviceKey(key="signal_strength", device_id=None): SensorValue(
                device_key=DeviceKey(key="signal_strength", device_id=None),
                name="Signal Strength",
                native_value=-60,
            ),
            DeviceKey(key="temperature", device_id=None): SensorValue(
                device_key=DeviceKey(key="temperature", device_id=None),
                name="Temperature",
                native_value=22.48,
            ),
            DeviceKey(key="humidity", device_id=None): SensorValue(
                device_key=DeviceKey(key="humidity", device_id=None),
                native_value=52.52,
                name="Humidity",
            ),
        },
    )


def test_sps_th2():
    parser = INKBIRDBluetoothDeviceData()
    service_info = make_bluetooth_service_info(
        name="sps",
        manufacturer_data={2248: b"\x84\x14\x00\x88\x99d\x06"},
        service_uuids=["0000fff0-0000-1000-8000-00805f9b34fb"],
        address="aa:bb:cc:dd:ee:ff",
        rssi=-60,
        service_data={},
        source="local",
    )
    result = parser.update(service_info)
    assert parser.device_type == Model.IBS_TH
    assert result == SensorUpdate(
        title=None,
        devices={
            None: SensorDeviceInfo(
                name="IBS-TH EEFF",
                model="IBS-TH",
                manufacturer="INKBIRD",
                sw_version=None,
                hw_version=None,
            )
        },
        entity_descriptions={
            DeviceKey(key="battery", device_id=None): SensorDescription(
                device_key=DeviceKey(key="battery", device_id=None),
                device_class=DeviceClass.BATTERY,
                native_unit_of_measurement=Units.PERCENTAGE,
            ),
            DeviceKey(key="signal_strength", device_id=None): SensorDescription(
                device_key=DeviceKey(key="signal_strength", device_id=None),
                device_class=DeviceClass.SIGNAL_STRENGTH,
                native_unit_of_measurement=Units.SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
            ),
            DeviceKey(key="temperature", device_id=None): SensorDescription(
                device_key=DeviceKey(key="temperature", device_id=None),
                device_class=DeviceClass.TEMPERATURE,
                native_unit_of_measurement=Units.TEMP_CELSIUS,
            ),
            DeviceKey(key="humidity", device_id=None): SensorDescription(
                device_key=DeviceKey(key="humidity", device_id=None),
                device_class=DeviceClass.HUMIDITY,
                native_unit_of_measurement=Units.PERCENTAGE,
            ),
        },
        entity_values={
            DeviceKey(key="battery", device_id=None): SensorValue(
                device_key=DeviceKey(key="battery", device_id=None),
                native_value=100,
                name="Battery",
            ),
            DeviceKey(key="signal_strength", device_id=None): SensorValue(
                device_key=DeviceKey(key="signal_strength", device_id=None),
                name="Signal Strength",
                native_value=-60,
            ),
            DeviceKey(key="temperature", device_id=None): SensorValue(
                device_key=DeviceKey(key="temperature", device_id=None),
                name="Temperature",
                native_value=22.48,
            ),
            DeviceKey(key="humidity", device_id=None): SensorValue(
                device_key=DeviceKey(key="humidity", device_id=None),
                native_value=52.52,
                name="Humidity",
            ),
        },
    )


def test_unknown_tps():
    parser = INKBIRDBluetoothDeviceData()
    service_info = make_bluetooth_service_info(
        name="tps",
        manufacturer_data={
            2120: b"\x00\x00\x00\xc6n\r\x06",
        },
        service_uuids=["0000fff0-0000-1000-8000-00805f9b34fb"],
        address="49:21:09:09:65:49",
        rssi=-54,
        service_data={},
        source="local",
    )
    assert parser.supported(service_info) is True
    parser = INKBIRDBluetoothDeviceData()
    result = parser.update(service_info)
    assert parser.device_type == Model.IBS_TH2
    assert result == SensorUpdate(
        title=None,
        devices={
            None: SensorDeviceInfo(
                name="IBS-TH2/P01B 6549",
                model="IBS-TH2/P01B",
                manufacturer="INKBIRD",
                sw_version=None,
                hw_version=None,
            )
        },
        entity_descriptions={
            DeviceKey(key="temperature", device_id=None): SensorDescription(
                device_key=DeviceKey(key="temperature", device_id=None),
                device_class=SensorDeviceClass.TEMPERATURE,
                native_unit_of_measurement=Units.TEMP_CELSIUS,
            ),
            DeviceKey(key="signal_strength", device_id=None): SensorDescription(
                device_key=DeviceKey(key="signal_strength", device_id=None),
                device_class=SensorDeviceClass.SIGNAL_STRENGTH,
                native_unit_of_measurement=Units.SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
            ),
            DeviceKey(key="battery", device_id=None): SensorDescription(
                device_key=DeviceKey(key="battery", device_id=None),
                device_class=SensorDeviceClass.BATTERY,
                native_unit_of_measurement=Units.PERCENTAGE,
            ),
        },
        entity_values={
            DeviceKey(key="temperature", device_id=None): SensorValue(
                device_key=DeviceKey(key="temperature", device_id=None),
                name="Temperature",
                native_value=21.2,
            ),
            DeviceKey(key="signal_strength", device_id=None): SensorValue(
                device_key=DeviceKey(key="signal_strength", device_id=None),
                name="Signal Strength",
                native_value=-54,
            ),
            DeviceKey(key="battery", device_id=None): SensorValue(
                device_key=DeviceKey(key="battery", device_id=None),
                name="Battery",
                native_value=13,
            ),
        },
        binary_entity_descriptions={},
        binary_entity_values={},
        events={},
    )


def test_tps_multi_entry_dict_with_raw() -> None:
    # Two FF AD segments in a single raw advertisement are legal per the
    # BLE spec. The last one is the most recent reading; previously the
    # parser bailed on len>1, leaving battery and temperature unset.
    parser = INKBIRDBluetoothDeviceData()
    service_info = make_bluetooth_service_info(
        name="tps",
        manufacturer_data={
            2200: b"\x00\x00\x00\x07\xbc\x00\x08",
            2240: b"\x00\x00\x00&q\x00\x08",
        },
        service_uuids=["0000fff0-0000-1000-8000-00805f9b34fb"],
        address="49:22:08:15:00:BB",
        rssi=-59,
        service_data={},
        source="98:3D:AE:4F:E9:FA",
        raw=b"\x02\x01\x06\x03\x02\xf0\xff"
        b"\x0a\xff\x98\x08\x00\x00\x00\x07\xbc\x00\x08"
        b"\x0a\xff\xc0\x08\x00\x00\x00&q\x00\x08",
    )
    result = parser.update(service_info)
    assert parser.device_type == Model.IBS_TH2
    assert (
        result.entity_values[DeviceKey(key="temperature", device_id=None)].native_value
        == 22.4
    )
    assert (
        result.entity_values[DeviceKey(key="battery", device_id=None)].native_value == 0
    )


def test_tps_multi_entry_dict_without_raw_bails() -> None:
    # Without raw, multiple newly changed entries are ambiguous (could be
    # missed packets, a fresh source, etc.) so the parser waits for the
    # next update rather than guessing.
    parser = INKBIRDBluetoothDeviceData()
    first = make_bluetooth_service_info(
        name="tps",
        manufacturer_data={2200: b"\x00\x00\x00\x07\xbc\x00\x08"},
        service_uuids=["0000fff0-0000-1000-8000-00805f9b34fb"],
        address="49:22:08:15:00:BB",
        rssi=-59,
        service_data={},
        source="98:3D:AE:4F:E9:FA",
    )
    parser.update(first)
    second = make_bluetooth_service_info(
        name="tps",
        manufacturer_data={
            2200: b"\x00\x00\x00\x07\xbc\x00\x08",
            2210: b"\x00\x00\x00\xdf\xb9\x00\x08",
            2240: b"\x00\x00\x00&q\x00\x08",
        },
        service_uuids=["0000fff0-0000-1000-8000-00805f9b34fb"],
        address="49:22:08:15:00:BB",
        rssi=-59,
        service_data={},
        source="98:3D:AE:4F:E9:FA",
    )
    result = parser.update(second)
    # Temperature stays at the value from the first parse; no new reading
    # was committed because the diff was ambiguous.
    assert (
        result.entity_values[DeviceKey(key="temperature", device_id=None)].native_value
        == 22.0
    )


def test_ibbq_4():
    parser = INKBIRDBluetoothDeviceData()
    service_info = make_bluetooth_service_info(
        name="iBBQ",
        manufacturer_data={
            0: b"\x00\x000\xe2\x83}\xb5\x02\x04\x01\xfa\x00\x04\x01\xfa\x00"
        },
        service_uuids=["0000fff0-0000-1000-8000-00805f9b34fb"],
        address="aa:bb:cc:dd:ee:ff",
        rssi=-60,
        service_data={},
        source="local",
    )
    result = parser.update(service_info)
    assert parser.device_type == Model.IBBQ_4
    assert result == SensorUpdate(
        title=None,
        devices={
            None: SensorDeviceInfo(
                name="iBBQ EEFF",
                model="iBBQ-4",
                manufacturer="INKBIRD",
                sw_version=None,
                hw_version=None,
            )
        },
        entity_descriptions={
            DeviceKey(key="signal_strength", device_id=None): SensorDescription(
                device_key=DeviceKey(key="signal_strength", device_id=None),
                device_class=DeviceClass.SIGNAL_STRENGTH,
                native_unit_of_measurement=Units.SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
            ),
            DeviceKey(key="temperature_probe_1", device_id=None): SensorDescription(
                device_key=DeviceKey(key="temperature_probe_1", device_id=None),
                device_class=DeviceClass.TEMPERATURE,
                native_unit_of_measurement=Units.TEMP_CELSIUS,
            ),
            DeviceKey(key="temperature_probe_2", device_id=None): SensorDescription(
                device_key=DeviceKey(key="temperature_probe_2", device_id=None),
                device_class=DeviceClass.TEMPERATURE,
                native_unit_of_measurement=Units.TEMP_CELSIUS,
            ),
            DeviceKey(key="temperature_probe_3", device_id=None): SensorDescription(
                device_key=DeviceKey(key="temperature_probe_3", device_id=None),
                device_class=DeviceClass.TEMPERATURE,
                native_unit_of_measurement=Units.TEMP_CELSIUS,
            ),
            DeviceKey(key="temperature_probe_4", device_id=None): SensorDescription(
                device_key=DeviceKey(key="temperature_probe_4", device_id=None),
                device_class=DeviceClass.TEMPERATURE,
                native_unit_of_measurement=Units.TEMP_CELSIUS,
            ),
        },
        entity_values={
            DeviceKey(key="signal_strength", device_id=None): SensorValue(
                device_key=DeviceKey(key="signal_strength", device_id=None),
                name="Signal Strength",
                native_value=-60,
            ),
            DeviceKey(key="temperature_probe_1", device_id=None): SensorValue(
                device_key=DeviceKey(key="temperature_probe_1", device_id=None),
                name="Temperature Probe 1",
                native_value=26.0,
            ),
            DeviceKey(key="temperature_probe_2", device_id=None): SensorValue(
                device_key=DeviceKey(key="temperature_probe_2", device_id=None),
                name="Temperature Probe 2",
                native_value=25.0,
            ),
            DeviceKey(key="temperature_probe_3", device_id=None): SensorValue(
                device_key=DeviceKey(key="temperature_probe_3", device_id=None),
                name="Temperature Probe 3",
                native_value=26.0,
            ),
            DeviceKey(key="temperature_probe_4", device_id=None): SensorValue(
                device_key=DeviceKey(key="temperature_probe_4", device_id=None),
                name="Temperature Probe 4",
                native_value=25.0,
            ),
        },
    )


def test_ibbq_4_sub_zero_probe():
    """A signed probe reading below 0°C is preserved, not clamped to 0 (#186).

    Probe 1 raw value is -50 (0xFFCE), i.e. -5.0°C — a legitimate cold reading,
    not the -1/0xFFFF disconnect sentinel, so it must survive as -5.0.
    """
    parser = INKBIRDBluetoothDeviceData()
    service_info = make_bluetooth_service_info(
        name="iBBQ",
        manufacturer_data={
            0: b"\x00\x000\xe2\x83}\xb5\x02\xce\xff\xfa\x00\x04\x01\xfa\x00"
        },
        service_uuids=["0000fff0-0000-1000-8000-00805f9b34fb"],
        address="aa:bb:cc:dd:ee:ff",
        rssi=-60,
        service_data={},
        source="local",
    )
    result = parser.update(service_info)
    assert parser.device_type == Model.IBBQ_4
    assert (
        result.entity_values[
            DeviceKey(key="temperature_probe_1", device_id=None)
        ].native_value
        == -5.0
    )
    # Remaining probes are unaffected.
    assert (
        result.entity_values[
            DeviceKey(key="temperature_probe_2", device_id=None)
        ].native_value
        == 25.0
    )


def test_ibbq_2_sub_zero_probe():
    """An iBBQ-2 probe reading below 0°C survives, not wrapped to ~6548°C.

    Probe 1 raw value is -50 (0xFFCE, little-endian ``\\xce\\xff``), i.e. -5.0°C.
    An unsigned ``<HH`` unpacker would read 0xFFCE as 65486 -> 6548.6°C. It is
    not the 0xFFFF disconnect sentinel, so it must survive as -5.0. Probe 2 is
    a normal 25.0°C reading.
    """
    parser = INKBIRDBluetoothDeviceData()
    service_info = make_bluetooth_service_info(
        name="xBBQ",
        manufacturer_data={1: b"\x00\x00,\x11\x00\x00m\xd3\xce\xff\xfa\x00"},
        service_uuids=["0000fff0-0000-1000-8000-00805f9b34fb"],
        address="aa:bb:cc:dd:ee:ff",
        rssi=-60,
        service_data={},
        source="local",
    )
    result = parser.update(service_info)
    assert parser.device_type == Model.IBBQ_2
    assert (
        result.entity_values[
            DeviceKey(key="temperature_probe_1", device_id=None)
        ].native_value
        == -5.0
    )
    assert (
        result.entity_values[
            DeviceKey(key="temperature_probe_2", device_id=None)
        ].native_value
        == 25.0
    )


def test_ibt_2x():
    parser = INKBIRDBluetoothDeviceData()
    service_info = make_bluetooth_service_info(
        name="xBBQ",
        manufacturer_data={1: b"\x00\x00,\x11\x00\x00m\xd3\x14\x01\x11\x01"},
        service_uuids=["0000fff0-0000-1000-8000-00805f9b34fb"],
        address="aa:bb:cc:dd:ee:ff",
        rssi=-60,
        service_data={},
        source="local",
    )
    result = parser.update(service_info)
    assert parser.device_type == Model.IBBQ_2
    assert result == SensorUpdate(
        title=None,
        devices={
            None: SensorDeviceInfo(
                name="xBBQ EEFF",
                model="xBBQ-2",
                manufacturer="INKBIRD",
                sw_version=None,
                hw_version=None,
            )
        },
        entity_descriptions={
            DeviceKey(key="temperature_probe_1", device_id=None): SensorDescription(
                device_key=DeviceKey(key="temperature_probe_1", device_id=None),
                device_class=DeviceClass.TEMPERATURE,
                native_unit_of_measurement=Units.TEMP_CELSIUS,
            ),
            DeviceKey(key="signal_strength", device_id=None): SensorDescription(
                device_key=DeviceKey(key="signal_strength", device_id=None),
                device_class=DeviceClass.SIGNAL_STRENGTH,
                native_unit_of_measurement=Units.SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
            ),
            DeviceKey(key="temperature_probe_2", device_id=None): SensorDescription(
                device_key=DeviceKey(key="temperature_probe_2", device_id=None),
                device_class=DeviceClass.TEMPERATURE,
                native_unit_of_measurement=Units.TEMP_CELSIUS,
            ),
        },
        entity_values={
            DeviceKey(key="temperature_probe_1", device_id=None): SensorValue(
                device_key=DeviceKey(key="temperature_probe_1", device_id=None),
                name="Temperature Probe 1",
                native_value=27.6,
            ),
            DeviceKey(key="signal_strength", device_id=None): SensorValue(
                device_key=DeviceKey(key="signal_strength", device_id=None),
                name="Signal Strength",
                native_value=-60,
            ),
            DeviceKey(key="temperature_probe_2", device_id=None): SensorValue(
                device_key=DeviceKey(key="temperature_probe_2", device_id=None),
                name="Temperature Probe 2",
                native_value=27.3,
            ),
        },
    )


def test_xbbq_2a_adv1():
    """Test xBBQ2 with a disconnected probe (0xFFFF) skips that probe."""
    parser = INKBIRDBluetoothDeviceData()
    service_info = make_bluetooth_service_info(
        name="xBBQ",
        manufacturer_data={1: b"\x00\x00V\x11\x00\x00\x7fs\xf8\x00\xff\xff"},
        service_uuids=["0000fff0-0000-1000-8000-00805f9b34fb"],
        address="aa:bb:cc:dd:ee:ff",
        rssi=-60,
        service_data={},
        source="local",
    )
    result = parser.update(service_info)
    assert parser.device_type == Model.IBBQ_2
    assert result == SensorUpdate(
        title=None,
        devices={
            None: SensorDeviceInfo(
                name="xBBQ EEFF",
                model="xBBQ-2",
                manufacturer="INKBIRD",
                sw_version=None,
                hw_version=None,
            )
        },
        entity_descriptions={
            DeviceKey(key="temperature_probe_1", device_id=None): SensorDescription(
                device_key=DeviceKey(key="temperature_probe_1", device_id=None),
                device_class=SensorDeviceClass.TEMPERATURE,
                native_unit_of_measurement=Units.TEMP_CELSIUS,
            ),
            DeviceKey(key="signal_strength", device_id=None): SensorDescription(
                device_key=DeviceKey(key="signal_strength", device_id=None),
                device_class=SensorDeviceClass.SIGNAL_STRENGTH,
                native_unit_of_measurement=Units.SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
            ),
        },
        entity_values={
            DeviceKey(key="temperature_probe_1", device_id=None): SensorValue(
                device_key=DeviceKey(key="temperature_probe_1", device_id=None),
                name="Temperature Probe 1",
                native_value=24.8,
            ),
            DeviceKey(key="signal_strength", device_id=None): SensorValue(
                device_key=DeviceKey(key="signal_strength", device_id=None),
                name="Signal Strength",
                native_value=-60,
            ),
        },
        binary_entity_descriptions={},
        binary_entity_values={},
    )


def test_ibt_2x_no_probes_connected():
    """Both probes unplugged (0xFFFF) emit no temperature (issue #155)."""
    parser = INKBIRDBluetoothDeviceData()
    service_info = make_bluetooth_service_info(
        name="xBBQ",
        manufacturer_data={1: b"\x00\x00,\x11\x00\x00m\xd3\xff\xff\xff\xff"},
        service_uuids=["0000fff0-0000-1000-8000-00805f9b34fb"],
        address="aa:bb:cc:dd:ee:ff",
        rssi=-60,
        service_data={},
        source="local",
    )
    result = parser.update(service_info)
    assert parser.device_type == Model.IBBQ_2
    assert result == SensorUpdate(
        title=None,
        devices={
            None: SensorDeviceInfo(
                name="xBBQ EEFF",
                model="xBBQ-2",
                manufacturer="INKBIRD",
                sw_version=None,
                hw_version=None,
            )
        },
        entity_descriptions={
            DeviceKey(key="signal_strength", device_id=None): SensorDescription(
                device_key=DeviceKey(key="signal_strength", device_id=None),
                device_class=SensorDeviceClass.SIGNAL_STRENGTH,
                native_unit_of_measurement=Units.SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
            ),
        },
        entity_values={
            DeviceKey(key="signal_strength", device_id=None): SensorValue(
                device_key=DeviceKey(key="signal_strength", device_id=None),
                name="Signal Strength",
                native_value=-60,
            ),
        },
        binary_entity_descriptions={},
        binary_entity_values={},
    )


def test_xbbq_2a_adv2():
    """Test xBBQ2 ignores 2 updates."""
    parser = INKBIRDBluetoothDeviceData()
    service_info = make_bluetooth_service_info(
        name="xBBQ",
        manufacturer_data={2: b"\x00\x00V\x11\x00\x00\x7fs\x9a\x00\x13\x00"},
        service_uuids=["0000fff0-0000-1000-8000-00805f9b34fb"],
        address="aa:bb:cc:dd:ee:ff",
        rssi=-60,
        service_data={},
        source="local",
    )
    assert parser.supported(service_info) is True
    assert parser.device_type == Model.IBBQ_2
    parser = INKBIRDBluetoothDeviceData()
    result = parser.update(service_info)
    assert result == SensorUpdate(
        title=None,
        devices={
            None: SensorDeviceInfo(
                name="xBBQ EEFF",
                model="xBBQ-2",
                manufacturer="INKBIRD",
                sw_version=None,
                hw_version=None,
            )
        },
        entity_descriptions={
            DeviceKey(key="temperature_probe_1", device_id=None): SensorDescription(
                device_key=DeviceKey(key="temperature_probe_1", device_id=None),
                device_class=SensorDeviceClass.TEMPERATURE,
                native_unit_of_measurement=Units.TEMP_CELSIUS,
            ),
            DeviceKey(key="temperature_probe_2", device_id=None): SensorDescription(
                device_key=DeviceKey(key="temperature_probe_2", device_id=None),
                device_class=SensorDeviceClass.TEMPERATURE,
                native_unit_of_measurement=Units.TEMP_CELSIUS,
            ),
            DeviceKey(key="signal_strength", device_id=None): SensorDescription(
                device_key=DeviceKey(key="signal_strength", device_id=None),
                device_class=SensorDeviceClass.SIGNAL_STRENGTH,
                native_unit_of_measurement=Units.SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
            ),
        },
        entity_values={
            DeviceKey(key="temperature_probe_1", device_id=None): SensorValue(
                device_key=DeviceKey(key="temperature_probe_1", device_id=None),
                name="Temperature Probe 1",
                native_value=15.4,
            ),
            DeviceKey(key="temperature_probe_2", device_id=None): SensorValue(
                device_key=DeviceKey(key="temperature_probe_2", device_id=None),
                name="Temperature Probe 2",
                native_value=1.9,
            ),
            DeviceKey(key="signal_strength", device_id=None): SensorValue(
                device_key=DeviceKey(key="signal_strength", device_id=None),
                name="Signal Strength",
                native_value=-60,
            ),
        },
        binary_entity_descriptions={},
        binary_entity_values={},
        events={},
    )


def test_xbbq_multiple_mfr_data():
    """Test xBBQ2 ignores 2 updates when there re multiple."""
    parser = INKBIRDBluetoothDeviceData()
    service_info = make_bluetooth_service_info(
        name="xBBQ",
        manufacturer_data={
            1: b"\x00\x00,\x11\x00\x00m\xd3\x11\x01\x12\x01",
            2: b"\x00\x00,\x11\x00\x00m\xd3\xda\x03\xda\x03",
        },
        service_uuids=["0000fff0-0000-1000-8000-00805f9b34fb"],
        address="aa:bb:cc:dd:ee:ff",
        rssi=-60,
        service_data={},
        source="local",
    )
    result = parser.update(service_info)
    assert parser.device_type == Model.IBBQ_2
    assert result == SensorUpdate(
        title=None,
        devices={
            None: SensorDeviceInfo(
                name="xBBQ EEFF",
                model="xBBQ-2",
                manufacturer="INKBIRD",
                sw_version=None,
                hw_version=None,
            )
        },
        entity_descriptions={
            DeviceKey(key="temperature_probe_2", device_id=None): SensorDescription(
                device_key=DeviceKey(key="temperature_probe_2", device_id=None),
                device_class=SensorDeviceClass.TEMPERATURE,
                native_unit_of_measurement=Units.TEMP_CELSIUS,
            ),
            DeviceKey(key="temperature_probe_1", device_id=None): SensorDescription(
                device_key=DeviceKey(key="temperature_probe_1", device_id=None),
                device_class=SensorDeviceClass.TEMPERATURE,
                native_unit_of_measurement=Units.TEMP_CELSIUS,
            ),
            DeviceKey(key="signal_strength", device_id=None): SensorDescription(
                device_key=DeviceKey(key="signal_strength", device_id=None),
                device_class=SensorDeviceClass.SIGNAL_STRENGTH,
                native_unit_of_measurement=Units.SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
            ),
        },
        entity_values={
            DeviceKey(key="temperature_probe_2", device_id=None): SensorValue(
                device_key=DeviceKey(key="temperature_probe_2", device_id=None),
                name="Temperature Probe 2",
                native_value=27.4,
            ),
            DeviceKey(key="temperature_probe_1", device_id=None): SensorValue(
                device_key=DeviceKey(key="temperature_probe_1", device_id=None),
                name="Temperature Probe 1",
                native_value=27.3,
            ),
            DeviceKey(key="signal_strength", device_id=None): SensorValue(
                device_key=DeviceKey(key="signal_strength", device_id=None),
                name="Signal Strength",
                native_value=-60,
            ),
        },
        binary_entity_descriptions={},
        binary_entity_values={},
    )


@pytest.mark.parametrize(("model"), [Model.IBS_TH, "IBS-TH"])
def test_corrupt_name(model: Model | str) -> None:
    """Test corrupt name."""
    parser = INKBIRDBluetoothDeviceData(model)
    assert parser.device_type == Model.IBS_TH
    service_info = make_bluetooth_service_info(
        name="N0BYD",
        manufacturer_data={63915: b"\x1b\x1e\x00H\xe37\x08"},
        service_uuids=["0000fff0-0000-1000-8000-00805f9b34fb"],
        address="aa:bb:cc:dd:ee:ff",
        rssi=-60,
        service_data={},
        source="local",
    )
    result = parser.update(service_info)
    assert result == SensorUpdate(
        title=None,
        devices={
            None: SensorDeviceInfo(
                name="IBS-TH EEFF",
                model="IBS-TH",
                manufacturer="INKBIRD",
                sw_version=None,
                hw_version=None,
            )
        },
        entity_descriptions={
            DeviceKey(key="temperature", device_id=None): SensorDescription(
                device_key=DeviceKey(key="temperature", device_id=None),
                device_class=SensorDeviceClass.TEMPERATURE,
                native_unit_of_measurement=Units.TEMP_CELSIUS,
            ),
            DeviceKey(key="battery", device_id=None): SensorDescription(
                device_key=DeviceKey(key="battery", device_id=None),
                device_class=SensorDeviceClass.BATTERY,
                native_unit_of_measurement=Units.PERCENTAGE,
            ),
            DeviceKey(key="signal_strength", device_id=None): SensorDescription(
                device_key=DeviceKey(key="signal_strength", device_id=None),
                device_class=SensorDeviceClass.SIGNAL_STRENGTH,
                native_unit_of_measurement=Units.SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
            ),
            DeviceKey(key="humidity", device_id=None): SensorDescription(
                device_key=DeviceKey(key="humidity", device_id=None),
                device_class=SensorDeviceClass.HUMIDITY,
                native_unit_of_measurement=Units.PERCENTAGE,
            ),
        },
        entity_values={
            DeviceKey(key="temperature", device_id=None): SensorValue(
                device_key=DeviceKey(key="temperature", device_id=None),
                name="Temperature",
                native_value=-16.21,
            ),
            DeviceKey(key="battery", device_id=None): SensorValue(
                device_key=DeviceKey(key="battery", device_id=None),
                name="Battery",
                native_value=55,
            ),
            DeviceKey(key="signal_strength", device_id=None): SensorValue(
                device_key=DeviceKey(key="signal_strength", device_id=None),
                name="Signal Strength",
                native_value=-60,
            ),
            DeviceKey(key="humidity", device_id=None): SensorValue(
                device_key=DeviceKey(key="humidity", device_id=None),
                name="Humidity",
                native_value=77.07,
            ),
        },
        binary_entity_descriptions={},
        binary_entity_values={},
        events={},
    )


def test_ith_21_b():
    parser = INKBIRDBluetoothDeviceData()
    service_info = make_bluetooth_service_info(
        name="ITH-21-B",
        manufacturer_data={
            9289: b"\x07\x11\x00\x98\xd8\x00\x13\x02d\x01\x90\x04\x00\x00\x00\x00",
        },
        service_uuids=["0000fff0-0000-1000-8000-00805f9b34fb"],
        address="aa:bb:cc:dd:ee:ff",
        rssi=-34,
        service_data={},
        source="local",
    )
    result = parser.update(service_info)
    assert parser.device_type is Model.ITH_21_B
    assert result == SensorUpdate(
        title=None,
        devices={
            None: SensorDeviceInfo(
                name="ITH-21-B EEFF",
                model="ITH-21-B",
                manufacturer="INKBIRD",
                sw_version=None,
                hw_version=None,
            )
        },
        entity_descriptions={
            DeviceKey(key="battery", device_id=None): SensorDescription(
                device_key=DeviceKey(key="battery", device_id=None),
                device_class=SensorDeviceClass.BATTERY,
                native_unit_of_measurement=Units.PERCENTAGE,
            ),
            DeviceKey(key="humidity", device_id=None): SensorDescription(
                device_key=DeviceKey(key="humidity", device_id=None),
                device_class=SensorDeviceClass.HUMIDITY,
                native_unit_of_measurement=Units.PERCENTAGE,
            ),
            DeviceKey(key="signal_strength", device_id=None): SensorDescription(
                device_key=DeviceKey(key="signal_strength", device_id=None),
                device_class=SensorDeviceClass.SIGNAL_STRENGTH,
                native_unit_of_measurement=Units.SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
            ),
            DeviceKey(key="temperature", device_id=None): SensorDescription(
                device_key=DeviceKey(key="temperature", device_id=None),
                device_class=SensorDeviceClass.TEMPERATURE,
                native_unit_of_measurement=Units.TEMP_CELSIUS,
            ),
        },
        entity_values={
            DeviceKey(key="battery", device_id=None): SensorValue(
                device_key=DeviceKey(key="battery", device_id=None),
                name="Battery",
                native_value=100,
            ),
            DeviceKey(key="humidity", device_id=None): SensorValue(
                device_key=DeviceKey(key="humidity", device_id=None),
                name="Humidity",
                native_value=53.1,
            ),
            DeviceKey(key="signal_strength", device_id=None): SensorValue(
                device_key=DeviceKey(key="signal_strength", device_id=None),
                name="Signal Strength",
                native_value=-34,
            ),
            DeviceKey(key="temperature", device_id=None): SensorValue(
                device_key=DeviceKey(key="temperature", device_id=None),
                name="Temperature",
                native_value=21.6,
            ),
        },
        binary_entity_descriptions={},
        binary_entity_values={},
        events={},
    )


def test_ith_31_b():
    parser = INKBIRDBluetoothDeviceData()
    # 26.8C 53% b'\x12#\x05/\x0e\x01\x10\x02d\x00\x00\x00\x00\x00\x00\x00'
    # 24.0C 50% b'\x12#\x05/\xf0\x00\xf9\x01d\x00\x00\x04\x00\x00\x00\x00'
    service_info = make_bluetooth_service_info(
        name="ITH-13-B",
        manufacturer_data={
            9289: b"\x12#\x05/\x0e\x01\x10\x02d\x00\x00\x00\x00\x00\x00\x00"
        },
        service_uuids=["0000fff0-0000-1000-8000-00805f9b34fb"],
        address="aa:bb:cc:dd:ee:ff",
        rssi=-34,
        service_data={},
        source="local",
    )
    result = parser.update(service_info)
    assert parser.device_type is Model.ITH_13_B
    assert result == SensorUpdate(
        title=None,
        devices={
            None: SensorDeviceInfo(
                name="ITH-13-B EEFF",
                model="ITH-13-B",
                manufacturer="INKBIRD",
                sw_version=None,
                hw_version=None,
            )
        },
        entity_descriptions={
            DeviceKey(key="battery", device_id=None): SensorDescription(
                device_key=DeviceKey(key="battery", device_id=None),
                device_class=SensorDeviceClass.BATTERY,
                native_unit_of_measurement=Units.PERCENTAGE,
            ),
            DeviceKey(key="humidity", device_id=None): SensorDescription(
                device_key=DeviceKey(key="humidity", device_id=None),
                device_class=SensorDeviceClass.HUMIDITY,
                native_unit_of_measurement=Units.PERCENTAGE,
            ),
            DeviceKey(key="signal_strength", device_id=None): SensorDescription(
                device_key=DeviceKey(key="signal_strength", device_id=None),
                device_class=SensorDeviceClass.SIGNAL_STRENGTH,
                native_unit_of_measurement=Units.SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
            ),
            DeviceKey(key="temperature", device_id=None): SensorDescription(
                device_key=DeviceKey(key="temperature", device_id=None),
                device_class=SensorDeviceClass.TEMPERATURE,
                native_unit_of_measurement=Units.TEMP_CELSIUS,
            ),
        },
        entity_values={
            DeviceKey(key="battery", device_id=None): SensorValue(
                device_key=DeviceKey(key="battery", device_id=None),
                name="Battery",
                native_value=100,
            ),
            DeviceKey(key="humidity", device_id=None): SensorValue(
                device_key=DeviceKey(key="humidity", device_id=None),
                name="Humidity",
                native_value=52.8,
            ),
            DeviceKey(key="signal_strength", device_id=None): SensorValue(
                device_key=DeviceKey(key="signal_strength", device_id=None),
                name="Signal Strength",
                native_value=-34,
            ),
            DeviceKey(key="temperature", device_id=None): SensorValue(
                device_key=DeviceKey(key="temperature", device_id=None),
                name="Temperature",
                native_value=27.0,
            ),
        },
        binary_entity_descriptions={},
        binary_entity_values={},
        events={},
    )

    service_info = make_bluetooth_service_info(
        name="ITH-13-B",
        manufacturer_data={
            9289: b"\x12#\x05/\xf0\x00\xf9\x01d\x00\x00\x04\x00\x00\x00\x00"
        },
        service_uuids=["0000fff0-0000-1000-8000-00805f9b34fb"],
        address="aa:bb:cc:dd:ee:ff",
        rssi=-34,
        service_data={},
        source="local",
    )
    result = parser.update(service_info)
    assert parser.device_type is Model.ITH_13_B
    assert result == SensorUpdate(
        title=None,
        devices={
            None: SensorDeviceInfo(
                name="ITH-13-B EEFF",
                model="ITH-13-B",
                manufacturer="INKBIRD",
                sw_version=None,
                hw_version=None,
            )
        },
        entity_descriptions={
            DeviceKey(key="battery", device_id=None): SensorDescription(
                device_key=DeviceKey(key="battery", device_id=None),
                device_class=SensorDeviceClass.BATTERY,
                native_unit_of_measurement=Units.PERCENTAGE,
            ),
            DeviceKey(key="humidity", device_id=None): SensorDescription(
                device_key=DeviceKey(key="humidity", device_id=None),
                device_class=SensorDeviceClass.HUMIDITY,
                native_unit_of_measurement=Units.PERCENTAGE,
            ),
            DeviceKey(key="signal_strength", device_id=None): SensorDescription(
                device_key=DeviceKey(key="signal_strength", device_id=None),
                device_class=SensorDeviceClass.SIGNAL_STRENGTH,
                native_unit_of_measurement=Units.SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
            ),
            DeviceKey(key="temperature", device_id=None): SensorDescription(
                device_key=DeviceKey(key="temperature", device_id=None),
                device_class=SensorDeviceClass.TEMPERATURE,
                native_unit_of_measurement=Units.TEMP_CELSIUS,
            ),
        },
        entity_values={
            DeviceKey(key="battery", device_id=None): SensorValue(
                device_key=DeviceKey(key="battery", device_id=None),
                name="Battery",
                native_value=100,
            ),
            DeviceKey(key="humidity", device_id=None): SensorValue(
                device_key=DeviceKey(key="humidity", device_id=None),
                name="Humidity",
                native_value=50.5,
            ),
            DeviceKey(key="signal_strength", device_id=None): SensorValue(
                device_key=DeviceKey(key="signal_strength", device_id=None),
                name="Signal Strength",
                native_value=-34,
            ),
            DeviceKey(key="temperature", device_id=None): SensorValue(
                device_key=DeviceKey(key="temperature", device_id=None),
                name="Temperature",
                native_value=24.0,
            ),
        },
        binary_entity_descriptions={},
        binary_entity_values={},
        events={},
    )


def test_ith_11_b():
    parser = INKBIRDBluetoothDeviceData()
    service_info = make_bluetooth_service_info(
        name="ITH-11-B",
        manufacturer_data={
            9289: b"\x08\x12\x00^\x00\x00]\x03d\x00d\x08\x00\x00\x00\x00"
        },
        service_uuids=["0000fff0-0000-1000-8000-00805f9b34fb"],
        address="aa:bb:cc:dd:ee:ff",
        rssi=-34,
        service_data={},
        source="local",
    )
    result = parser.update(service_info)
    assert parser.name == "ITH-11-B EEFF"
    assert parser.poll_needed(service_info, None) is False
    assert parser.device_type is Model.ITH_11_B
    assert result == SensorUpdate(
        title=None,
        devices={
            None: SensorDeviceInfo(
                name="ITH-11-B EEFF",
                model="ITH-11-B",
                manufacturer="INKBIRD",
                sw_version=None,
                hw_version=None,
            )
        },
        entity_descriptions={
            DeviceKey(key="battery", device_id=None): SensorDescription(
                device_key=DeviceKey(key="battery", device_id=None),
                device_class=SensorDeviceClass.BATTERY,
                native_unit_of_measurement=Units.PERCENTAGE,
            ),
            DeviceKey(key="humidity", device_id=None): SensorDescription(
                device_key=DeviceKey(key="humidity", device_id=None),
                device_class=SensorDeviceClass.HUMIDITY,
                native_unit_of_measurement=Units.PERCENTAGE,
            ),
            DeviceKey(key="signal_strength", device_id=None): SensorDescription(
                device_key=DeviceKey(key="signal_strength", device_id=None),
                device_class=SensorDeviceClass.SIGNAL_STRENGTH,
                native_unit_of_measurement=Units.SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
            ),
            DeviceKey(key="temperature", device_id=None): SensorDescription(
                device_key=DeviceKey(key="temperature", device_id=None),
                device_class=SensorDeviceClass.TEMPERATURE,
                native_unit_of_measurement=Units.TEMP_CELSIUS,
            ),
        },
        entity_values={
            DeviceKey(key="battery", device_id=None): SensorValue(
                device_key=DeviceKey(key="battery", device_id=None),
                name="Battery",
                native_value=100,
            ),
            DeviceKey(key="humidity", device_id=None): SensorValue(
                device_key=DeviceKey(key="humidity", device_id=None),
                name="Humidity",
                native_value=86.1,
            ),
            DeviceKey(key="signal_strength", device_id=None): SensorValue(
                device_key=DeviceKey(key="signal_strength", device_id=None),
                name="Signal Strength",
                native_value=-34,
            ),
            DeviceKey(key="temperature", device_id=None): SensorValue(
                device_key=DeviceKey(key="temperature", device_id=None),
                name="Temperature",
                native_value=0.0,
            ),
        },
        binary_entity_descriptions={},
        binary_entity_values={},
        events={},
    )

    service_info = make_bluetooth_service_info(
        name="ITH-11-B",
        manufacturer_data={
            9289: b"\x08\x12\x00^\xfe\xffH\x03d\x00d\x08\x00\x00\x00\x00"
        },
        service_uuids=["0000fff0-0000-1000-8000-00805f9b34fb"],
        address="aa:bb:cc:dd:ee:ff",
        rssi=-34,
        service_data={},
        source="local",
    )
    result = parser.update(service_info)
    assert parser.device_type is Model.ITH_11_B
    assert result == SensorUpdate(
        title=None,
        devices={
            None: SensorDeviceInfo(
                name="ITH-11-B EEFF",
                model="ITH-11-B",
                manufacturer="INKBIRD",
                sw_version=None,
                hw_version=None,
            )
        },
        entity_descriptions={
            DeviceKey(key="battery", device_id=None): SensorDescription(
                device_key=DeviceKey(key="battery", device_id=None),
                device_class=SensorDeviceClass.BATTERY,
                native_unit_of_measurement=Units.PERCENTAGE,
            ),
            DeviceKey(key="humidity", device_id=None): SensorDescription(
                device_key=DeviceKey(key="humidity", device_id=None),
                device_class=SensorDeviceClass.HUMIDITY,
                native_unit_of_measurement=Units.PERCENTAGE,
            ),
            DeviceKey(key="signal_strength", device_id=None): SensorDescription(
                device_key=DeviceKey(key="signal_strength", device_id=None),
                device_class=SensorDeviceClass.SIGNAL_STRENGTH,
                native_unit_of_measurement=Units.SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
            ),
            DeviceKey(key="temperature", device_id=None): SensorDescription(
                device_key=DeviceKey(key="temperature", device_id=None),
                device_class=SensorDeviceClass.TEMPERATURE,
                native_unit_of_measurement=Units.TEMP_CELSIUS,
            ),
        },
        entity_values={
            DeviceKey(key="battery", device_id=None): SensorValue(
                device_key=DeviceKey(key="battery", device_id=None),
                name="Battery",
                native_value=100,
            ),
            DeviceKey(key="humidity", device_id=None): SensorValue(
                device_key=DeviceKey(key="humidity", device_id=None),
                name="Humidity",
                native_value=84.0,
            ),
            DeviceKey(key="signal_strength", device_id=None): SensorValue(
                device_key=DeviceKey(key="signal_strength", device_id=None),
                name="Signal Strength",
                native_value=-34,
            ),
            DeviceKey(key="temperature", device_id=None): SensorValue(
                device_key=DeviceKey(key="temperature", device_id=None),
                name="Temperature",
                native_value=-0.2,
            ),
        },
        binary_entity_descriptions={},
        binary_entity_values={},
        events={},
    )


def test_ith_11_b_corrupt_humidity_dropped():
    """A corrupt reading (humidity > 100%, temperature 0) is dropped (#141)."""
    parser = INKBIRDBluetoothDeviceData()
    service_info = make_bluetooth_service_info(
        # data[6:10] = 00 00 ff ff -> temp 0.0C, humidity 6553.5% (0xFFFF/10)
        name="ITH-11-B",
        manufacturer_data={
            9289: b"\x08\x12\x00^\x00\x00\xff\xffd\x00d\x08\x00\x00\x00\x00"
        },
        service_uuids=["0000fff0-0000-1000-8000-00805f9b34fb"],
        address="aa:bb:cc:dd:ee:ff",
        rssi=-34,
        service_data={},
        source="local",
    )
    result = parser.update(service_info)
    assert parser.device_type is Model.ITH_11_B
    # The corrupt packet emits no temperature/humidity/battery values; only the
    # always-present signal strength remains.
    assert result == SensorUpdate(
        title=None,
        devices={
            None: SensorDeviceInfo(
                name="ITH-11-B EEFF",
                model="ITH-11-B",
                manufacturer="INKBIRD",
                sw_version=None,
                hw_version=None,
            )
        },
        entity_descriptions={
            DeviceKey(key="signal_strength", device_id=None): SensorDescription(
                device_key=DeviceKey(key="signal_strength", device_id=None),
                device_class=SensorDeviceClass.SIGNAL_STRENGTH,
                native_unit_of_measurement=Units.SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
            ),
        },
        entity_values={
            DeviceKey(key="signal_strength", device_id=None): SensorValue(
                device_key=DeviceKey(key="signal_strength", device_id=None),
                name="Signal Strength",
                native_value=-34,
            ),
        },
        binary_entity_descriptions={},
        binary_entity_values={},
        events={},
    )


def test_passive_data_needs_polling() -> None:
    """Test passive data need polling."""
    parser = INKBIRDBluetoothDeviceData(Model.IBS_TH)
    assert parser.device_type == Model.IBS_TH
    service_info = make_bluetooth_service_info(
        name="N0BYD",
        manufacturer_data={},
        service_uuids=["0000fff0-0000-1000-8000-00805f9b34fb"],
        address="aa:bb:cc:dd:ee:ff",
        rssi=-60,
        service_data={},
        source="local",
    )
    result = parser.update(service_info)
    assert parser.poll_needed(service_info, None) is True
    assert parser.name == "IBS-TH EEFF"
    assert result == SensorUpdate(
        title=None,
        devices={
            None: SensorDeviceInfo(
                name="IBS-TH EEFF",
                model="IBS-TH",
                manufacturer="INKBIRD",
                sw_version=None,
                hw_version=None,
            )
        },
        entity_descriptions={
            DeviceKey(key="signal_strength", device_id=None): SensorDescription(
                device_key=DeviceKey(key="signal_strength", device_id=None),
                device_class=SensorDeviceClass.SIGNAL_STRENGTH,
                native_unit_of_measurement=Units.SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
            ),
        },
        entity_values={
            DeviceKey(key="signal_strength", device_id=None): SensorValue(
                device_key=DeviceKey(key="signal_strength", device_id=None),
                name="Signal Strength",
                native_value=-60,
            ),
        },
        binary_entity_descriptions={},
        binary_entity_values={},
        events={},
    )


@pytest.mark.asyncio
async def test_passive_polling_ibs_th() -> None:
    """Test polling with passing data."""
    parser = INKBIRDBluetoothDeviceData(Model.IBS_TH)
    assert parser.device_type == Model.IBS_TH
    service_info = make_bluetooth_service_info(
        name="N0BYD",
        manufacturer_data={},
        service_uuids=["0000fff0-0000-1000-8000-00805f9b34fb"],
        address="aa:bb:cc:dd:ee:ff",
        rssi=-60,
        service_data={},
        source="local",
    )
    parser.update(service_info)
    assert parser.poll_needed(service_info, None) is True
    read_gatt_char_mock = AsyncMock(return_value=b"\x09\x09\x00\x04\xe37\x08")
    disconnect_mock = AsyncMock()
    mock_client = MagicMock(
        read_gatt_char=read_gatt_char_mock, disconnect=disconnect_mock
    )
    with patch("inkbird_ble.parser.establish_connection", return_value=mock_client):
        update = await parser.async_poll(
            BLEDevice(
                address="aa:bb:cc:dd:ee:ff",
                name="N0BYD",
                details={},
            )
        )
    assert update == SensorUpdate(
        title=None,
        devices={
            None: SensorDeviceInfo(
                name="IBS-TH EEFF",
                model="IBS-TH",
                manufacturer="INKBIRD",
                sw_version=None,
                hw_version=None,
            )
        },
        entity_descriptions={
            DeviceKey(key="signal_strength", device_id=None): SensorDescription(
                device_key=DeviceKey(key="signal_strength", device_id=None),
                device_class=SensorDeviceClass.SIGNAL_STRENGTH,
                native_unit_of_measurement=Units.SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
            ),
            DeviceKey(key="temperature", device_id=None): SensorDescription(
                device_key=DeviceKey(key="temperature", device_id=None),
                device_class=SensorDeviceClass.TEMPERATURE,
                native_unit_of_measurement=Units.TEMP_CELSIUS,
            ),
            DeviceKey(key="humidity", device_id=None): SensorDescription(
                device_key=DeviceKey(key="humidity", device_id=None),
                device_class=SensorDeviceClass.HUMIDITY,
                native_unit_of_measurement=Units.PERCENTAGE,
            ),
        },
        entity_values={
            DeviceKey(key="signal_strength", device_id=None): SensorValue(
                device_key=DeviceKey(key="signal_strength", device_id=None),
                name="Signal Strength",
                native_value=-60,
            ),
            DeviceKey(key="temperature", device_id=None): SensorValue(
                device_key=DeviceKey(key="temperature", device_id=None),
                name="Temperature",
                native_value=23.13,
            ),
            DeviceKey(key="humidity", device_id=None): SensorValue(
                device_key=DeviceKey(key="humidity", device_id=None),
                name="Humidity",
                native_value=10.24,
            ),
        },
        binary_entity_descriptions={},
        binary_entity_values={},
        events={},
    )


@pytest.mark.asyncio
async def test_passive_polling_ith_11_b() -> None:
    """Test polling with passing data."""
    parser = INKBIRDBluetoothDeviceData(Model.ITH_11_B)
    assert parser.device_type == Model.ITH_11_B
    service_info = make_bluetooth_service_info(
        name="N0BYD",
        manufacturer_data={},
        service_uuids=["0000fff0-0000-1000-8000-00805f9b34fb"],
        address="aa:bb:cc:dd:ee:ff",
        rssi=-60,
        service_data={},
        source="local",
    )
    parser.update(service_info)
    assert parser.poll_needed(service_info, None) is True
    read_gatt_char_mock = AsyncMock(return_value=b"rtdth\xd8\x00\xef\x01a\x00\x90\x04")
    disconnect_mock = AsyncMock()
    mock_client = MagicMock(
        read_gatt_char=read_gatt_char_mock, disconnect=disconnect_mock
    )
    with patch("inkbird_ble.parser.establish_connection", return_value=mock_client):
        update = await parser.async_poll(
            BLEDevice(
                address="aa:bb:cc:dd:ee:ff",
                name="N0BYD",
                details={},
            )
        )
    assert update == SensorUpdate(
        title=None,
        devices={
            None: SensorDeviceInfo(
                name="ITH-11-B EEFF",
                model="ITH-11-B",
                manufacturer="INKBIRD",
                sw_version=None,
                hw_version=None,
            )
        },
        entity_descriptions={
            DeviceKey(key="signal_strength", device_id=None): SensorDescription(
                device_key=DeviceKey(key="signal_strength", device_id=None),
                device_class=SensorDeviceClass.SIGNAL_STRENGTH,
                native_unit_of_measurement=Units.SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
            ),
            DeviceKey(key="temperature", device_id=None): SensorDescription(
                device_key=DeviceKey(key="temperature", device_id=None),
                device_class=SensorDeviceClass.TEMPERATURE,
                native_unit_of_measurement=Units.TEMP_CELSIUS,
            ),
            DeviceKey(key="humidity", device_id=None): SensorDescription(
                device_key=DeviceKey(key="humidity", device_id=None),
                device_class=SensorDeviceClass.HUMIDITY,
                native_unit_of_measurement=Units.PERCENTAGE,
            ),
            DeviceKey(key="battery", device_id=None): SensorDescription(
                device_key=DeviceKey(key="battery", device_id=None),
                device_class=SensorDeviceClass.BATTERY,
                native_unit_of_measurement=Units.PERCENTAGE,
            ),
        },
        entity_values={
            DeviceKey(key="signal_strength", device_id=None): SensorValue(
                device_key=DeviceKey(key="signal_strength", device_id=None),
                name="Signal Strength",
                native_value=-60,
            ),
            DeviceKey(key="temperature", device_id=None): SensorValue(
                device_key=DeviceKey(key="temperature", device_id=None),
                name="Temperature",
                native_value=21.6,
            ),
            DeviceKey(key="humidity", device_id=None): SensorValue(
                device_key=DeviceKey(key="humidity", device_id=None),
                name="Humidity",
                native_value=49.5,
            ),
            DeviceKey(key="battery", device_id=None): SensorValue(
                device_key=DeviceKey(key="battery", device_id=None),
                name="Battery",
                native_value=97,
            ),
        },
        binary_entity_descriptions={},
        binary_entity_values={},
        events={},
    )


@pytest.mark.asyncio
async def test_passive_polling_fails_missing_char() -> None:
    """Test polling with passing data."""
    parser = INKBIRDBluetoothDeviceData(Model.ITH_11_B)
    assert parser.device_type == Model.ITH_11_B
    service_info = make_bluetooth_service_info(
        name="N0BYD",
        manufacturer_data={},
        service_uuids=["0000fff0-0000-1000-8000-00805f9b34fb"],
        address="aa:bb:cc:dd:ee:ff",
        rssi=-60,
        service_data={},
        source="local",
    )
    parser.update(service_info)
    assert parser.poll_needed(service_info, None) is True
    read_gatt_char_mock = AsyncMock(side_effect=BleakCharacteristicNotFoundError(1))
    disconnect_mock = AsyncMock()
    clear_cache_mock = AsyncMock()
    mock_client = MagicMock(
        read_gatt_char=read_gatt_char_mock,
        disconnect=disconnect_mock,
        clear_cache=clear_cache_mock,
    )

    with (
        pytest.raises(BleakCharacteristicNotFoundError),
        patch("inkbird_ble.parser.establish_connection", return_value=mock_client),
    ):
        await parser.async_poll(
            BLEDevice(
                address="aa:bb:cc:dd:ee:ff",
                name="N0BYD",
                details={},
            )
        )

    clear_cache_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_passive_polling_fails_generic_bleak_error() -> None:
    """Test polling with passing data."""
    parser = INKBIRDBluetoothDeviceData(Model.ITH_11_B)
    assert parser.device_type == Model.ITH_11_B
    service_info = make_bluetooth_service_info(
        name="N0BYD",
        manufacturer_data={},
        service_uuids=["0000fff0-0000-1000-8000-00805f9b34fb"],
        address="aa:bb:cc:dd:ee:ff",
        rssi=-60,
        service_data={},
        source="local",
    )
    parser.update(service_info)
    assert parser.poll_needed(service_info, None) is True
    read_gatt_char_mock = AsyncMock(side_effect=BleakError)
    disconnect_mock = AsyncMock()
    clear_cache_mock = AsyncMock()
    mock_client = MagicMock(
        read_gatt_char=read_gatt_char_mock,
        disconnect=disconnect_mock,
        clear_cache=clear_cache_mock,
    )

    with (
        pytest.raises(BleakError),
        patch("inkbird_ble.parser.establish_connection", return_value=mock_client),
    ):
        await parser.async_poll(
            BLEDevice(
                address="aa:bb:cc:dd:ee:ff",
                name="N0BYD",
                details={},
            )
        )

    clear_cache_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_passive_detect_iam_t1() -> None:
    """Test polling with passing data."""
    parser = INKBIRDBluetoothDeviceData()
    service_info = make_bluetooth_service_info(
        name="",
        manufacturer_data={12628: bytes.fromhex("41432d363230306131336361650000")},
        service_uuids=[],
        address="aa:bb:cc:dd:ee:ff",
        rssi=-60,
        service_data={},
        source="local",
    )
    parser.update(service_info)
    assert parser.device_type == Model.IAM_T1
    assert parser.poll_needed(service_info, None) is False
    assert parser.name == "IAM-T1 EEFF"
    assert parser.supported(service_info) is True


@pytest.mark.asyncio
async def test_notify_does_nothing_not_supported() -> None:
    """Test polling with passing data."""
    parser = INKBIRDBluetoothDeviceData(Model.ITH_11_B)
    assert parser.device_type == Model.ITH_11_B
    assert parser.uses_notify is False
    await parser.async_start(
        make_bluetooth_service_info(
            name="N0BYD",
            manufacturer_data={},
            service_uuids=["0000fff0-0000-1000-8000-00805f9b34fb"],
            address="aa:bb:cc:dd:ee:ff",
            rssi=-60,
            service_data={},
            source="local",
        ),
        BLEDevice(
            address="aa:bb:cc:dd:ee:ff",
            name="N0BYD",
            details={},
        ),
    )
    await parser.async_stop()


@pytest.mark.asyncio
async def test_notify_callbacks_iam_t1_f() -> None:
    """Test notify with passing data in F."""

    last_update: SensorUpdate | None = None

    def _update_callback(update: SensorUpdate) -> None:
        nonlocal last_update
        last_update = update

    def _data_callback(data: dict[str, Any]) -> None:
        """
        Callback for data updates.
        """

    parser = INKBIRDBluetoothDeviceData(
        Model.IAM_T1, {}, _update_callback, _data_callback
    )
    assert parser.device_type == Model.IAM_T1
    service_info = make_bluetooth_service_info(
        name="Ink@IAM-T1",
        manufacturer_data={12628: b"AC-6200a13cae\x00\x00"},
        service_uuids=["0000fff0-0000-1000-8000-00805f9b34fb"],
        address="62:00:A1:3C:AE:7B",
        rssi=-44,
        service_data={},
        source="local",
    )
    parser.update(service_info)
    assert parser.supported(service_info) is True
    assert parser.poll_needed(service_info, None) is False
    assert parser.uses_notify
    disconnect_mock = AsyncMock()

    async def start_notify_mock(
        uuid: UUID, callback: Callable[[UUID, bytes], None]
    ) -> None:
        callback(uuid, b"U")
        callback(uuid, b"U\xaa\x05\x0c\x00\x00\x00\x00\x00\x00\x01\x11")
        callback(uuid, b"U\xaa\x01\x10\x10\x03\x0b\x01\xd6\x02\xe3\x03\xf1\x01\x00\xcf")

    mock_client = MagicMock(start_notify=start_notify_mock, disconnect=disconnect_mock)
    with patch("inkbird_ble.parser.establish_connection", return_value=mock_client):
        await parser.async_start(
            service_info,
            BLEDevice(
                address="62:00:A1:3C:AE:7B",
                name="Ink@IAM-T1",
                details={},
            ),
        )
        await asyncio.sleep(0)
        await parser.async_stop()

    assert last_update == SensorUpdate(
        title=None,
        devices={
            None: SensorDeviceInfo(
                name="IAM-T1 AE7B",
                model="IAM-T1",
                manufacturer="INKBIRD",
                sw_version=None,
                hw_version=None,
            )
        },
        entity_descriptions={
            DeviceKey(key="temperature", device_id=None): SensorDescription(
                device_key=DeviceKey(key="temperature", device_id=None),
                device_class=SensorDeviceClass.TEMPERATURE,
                native_unit_of_measurement=Units.TEMP_CELSIUS,
            ),
            DeviceKey(key="humidity", device_id=None): SensorDescription(
                device_key=DeviceKey(key="humidity", device_id=None),
                device_class=SensorDeviceClass.HUMIDITY,
                native_unit_of_measurement=Units.PERCENTAGE,
            ),
            DeviceKey(key="carbon_dioxide", device_id=None): SensorDescription(
                device_key=DeviceKey(key="carbon_dioxide", device_id=None),
                device_class=SensorDeviceClass.CO2,
                native_unit_of_measurement=Units.CONCENTRATION_PARTS_PER_MILLION,
            ),
            DeviceKey(key="pressure", device_id=None): SensorDescription(
                device_key=DeviceKey(key="pressure", device_id=None),
                device_class=SensorDeviceClass.PRESSURE,
                native_unit_of_measurement=Units.PRESSURE_HPA,
            ),
            DeviceKey(key="signal_strength", device_id=None): SensorDescription(
                device_key=DeviceKey(key="signal_strength", device_id=None),
                device_class=SensorDeviceClass.SIGNAL_STRENGTH,
                native_unit_of_measurement=Units.SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
            ),
        },
        entity_values={
            DeviceKey(key="temperature", device_id=None): SensorValue(
                device_key=DeviceKey(key="temperature", device_id=None),
                name="Temperature",
                native_value=25.5,
            ),
            DeviceKey(key="humidity", device_id=None): SensorValue(
                device_key=DeviceKey(key="humidity", device_id=None),
                name="Humidity",
                native_value=47.0,
            ),
            DeviceKey(key="carbon_dioxide", device_id=None): SensorValue(
                device_key=DeviceKey(key="carbon_dioxide", device_id=None),
                name="Carbon Dioxide",
                native_value=739,
            ),
            DeviceKey(key="pressure", device_id=None): SensorValue(
                device_key=DeviceKey(key="pressure", device_id=None),
                name="Pressure",
                native_value=1009,
            ),
            DeviceKey(key="signal_strength", device_id=None): SensorValue(
                device_key=DeviceKey(key="signal_strength", device_id=None),
                name="Signal Strength",
                native_value=-44,
            ),
        },
        binary_entity_descriptions={},
        binary_entity_values={},
        events={},
    )


@pytest.mark.asyncio
async def test_notify_iam_t1_c() -> None:
    """Test notify with passing data in C."""
    last_update: SensorUpdate | None = None

    def _update_callback(update: SensorUpdate) -> None:
        nonlocal last_update
        last_update = update

    def _data_callback(data: dict[str, Any]) -> None:
        """
        Callback for data updates.
        """

    parser = INKBIRDBluetoothDeviceData(
        Model.IAM_T1, {}, _update_callback, _data_callback
    )
    assert parser.device_type == Model.IAM_T1
    service_info = make_bluetooth_service_info(
        name="Ink@IAM-T1",
        manufacturer_data={12628: b"AC-6200a13cae\x00\x00"},
        service_uuids=["0000fff0-0000-1000-8000-00805f9b34fb"],
        address="62:00:A1:3C:AE:7B",
        rssi=-44,
        service_data={},
        source="local",
    )
    parser.update(service_info)
    assert parser.supported(service_info) is True
    assert parser.poll_needed(service_info, None) is False
    assert parser.uses_notify
    disconnect_mock = AsyncMock()

    async def start_notify_mock(
        uuid: UUID, callback: Callable[[UUID, bytes], None]
    ) -> None:
        callback(uuid, b"U\xaa\x05\x0c\x00\x00\x00\x00\x00\x00\x00\x10")
        callback(uuid, b"U\xaa\x01\x10\x00\x00\xe8\x01\xf4\x04K\x03")
        callback(uuid, b"U\xaa\x01\x10\x00\x00\xfe\x01\xd6\x02\xd9\x03\xf1\x01\x00\xb5")

    mock_client = MagicMock(start_notify=start_notify_mock, disconnect=disconnect_mock)
    with patch("inkbird_ble.parser.establish_connection", return_value=mock_client):
        await parser.async_start(
            service_info,
            BLEDevice(
                address="62:00:A1:3C:AE:7B",
                name="Ink@IAM-T1",
                details={},
            ),
        )
        await asyncio.sleep(0)
        await parser.async_stop()
    assert last_update == SensorUpdate(
        title=None,
        devices={
            None: SensorDeviceInfo(
                name="IAM-T1 AE7B",
                model="IAM-T1",
                manufacturer="INKBIRD",
                sw_version=None,
                hw_version=None,
            )
        },
        entity_descriptions={
            DeviceKey(key="temperature", device_id=None): SensorDescription(
                device_key=DeviceKey(key="temperature", device_id=None),
                device_class=SensorDeviceClass.TEMPERATURE,
                native_unit_of_measurement=Units.TEMP_CELSIUS,
            ),
            DeviceKey(key="humidity", device_id=None): SensorDescription(
                device_key=DeviceKey(key="humidity", device_id=None),
                device_class=SensorDeviceClass.HUMIDITY,
                native_unit_of_measurement=Units.PERCENTAGE,
            ),
            DeviceKey(key="carbon_dioxide", device_id=None): SensorDescription(
                device_key=DeviceKey(key="carbon_dioxide", device_id=None),
                device_class=SensorDeviceClass.CO2,
                native_unit_of_measurement=Units.CONCENTRATION_PARTS_PER_MILLION,
            ),
            DeviceKey(key="pressure", device_id=None): SensorDescription(
                device_key=DeviceKey(key="pressure", device_id=None),
                device_class=SensorDeviceClass.PRESSURE,
                native_unit_of_measurement=Units.PRESSURE_HPA,
            ),
            DeviceKey(key="signal_strength", device_id=None): SensorDescription(
                device_key=DeviceKey(key="signal_strength", device_id=None),
                device_class=SensorDeviceClass.SIGNAL_STRENGTH,
                native_unit_of_measurement=Units.SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
            ),
        },
        entity_values={
            DeviceKey(key="temperature", device_id=None): SensorValue(
                device_key=DeviceKey(key="temperature", device_id=None),
                name="Temperature",
                native_value=25.4,
            ),
            DeviceKey(key="humidity", device_id=None): SensorValue(
                device_key=DeviceKey(key="humidity", device_id=None),
                name="Humidity",
                native_value=47.0,
            ),
            DeviceKey(key="carbon_dioxide", device_id=None): SensorValue(
                device_key=DeviceKey(key="carbon_dioxide", device_id=None),
                name="Carbon Dioxide",
                native_value=729,
            ),
            DeviceKey(key="pressure", device_id=None): SensorValue(
                device_key=DeviceKey(key="pressure", device_id=None),
                name="Pressure",
                native_value=1009,
            ),
            DeviceKey(key="signal_strength", device_id=None): SensorValue(
                device_key=DeviceKey(key="signal_strength", device_id=None),
                name="Signal Strength",
                native_value=-44,
            ),
        },
        binary_entity_descriptions={},
        binary_entity_values={},
        events={},
    )


@pytest.mark.asyncio
async def test_notify_iam_t1_corrupt_temperature_dropped() -> None:
    """A corrupt IAM-T1 notification (|temperature| > 200 °C) is dropped.

    The IAM-T1 notify payload encodes temperature as an unsigned 16-bit value
    plus a separate sign nibble, so a garbage ``0xFFFF`` temperature field
    with ``sign == 0`` decodes to 6553.5 °C — the same wraparound shape the
    signed advertisement parsers block at the source (#155 / #188 / #193).
    Notify cannot switch to signed parsing without breaking the protocol, so
    the implausible-temperature guard catches it on the notify side and
    drops the whole packet rather than publishing any of its fields.
    """
    updates: list[SensorUpdate] = []

    def _update_callback(update: SensorUpdate) -> None:
        updates.append(update)

    def _data_callback(data: dict[str, Any]) -> None:
        """Callback for data updates."""

    parser = INKBIRDBluetoothDeviceData(
        Model.IAM_T1, {}, _update_callback, _data_callback
    )
    service_info = make_bluetooth_service_info(
        name="Ink@IAM-T1",
        manufacturer_data={12628: b"AC-6200a13cae\x00\x00"},
        service_uuids=["0000fff0-0000-1000-8000-00805f9b34fb"],
        address="62:00:A1:3C:AE:7B",
        rssi=-44,
        service_data={},
        source="local",
    )
    parser.update(service_info)
    disconnect_mock = AsyncMock()

    async def start_notify_mock(
        uuid: UUID, callback: Callable[[UUID, bytes], None]
    ) -> None:
        # Unit-setting packet (Celsius): low nibble of data[10] = 0 -> Celsius.
        callback(uuid, b"U\xaa\x05\x0c\x00\x00\x00\x00\x00\x00\x00\x10")
        # Data packet: sign nibble 0, temp bytes ff ff (-> 6553.5 °C), but
        # humidity 01 f4 (-> 50.0%) is perfectly plausible. The temperature
        # guard must drop the whole packet rather than publish a bogus
        # 6553.5 °C reading alongside the valid humidity.
        callback(uuid, b"U\xaa\x01\x10\x00\xff\xff\x01\xf4\x04M\x03\xfe\x01\x00A")

    mock_client = MagicMock(start_notify=start_notify_mock, disconnect=disconnect_mock)
    with patch("inkbird_ble.parser.establish_connection", return_value=mock_client):
        await parser.async_start(
            service_info,
            BLEDevice(
                address="62:00:A1:3C:AE:7B",
                name="Ink@IAM-T1",
                details={},
            ),
        )
        await asyncio.sleep(0)
        await parser.async_stop()

    # The corrupt-temperature packet produced no update callback at all.
    assert updates == []


@pytest.mark.asyncio
async def test_notify_iam_t1_corrupt_humidity_dropped() -> None:
    """A corrupt IAM-T1 notification (humidity > 100%) is dropped (#141 family)."""
    updates: list[SensorUpdate] = []

    def _update_callback(update: SensorUpdate) -> None:
        updates.append(update)

    def _data_callback(data: dict[str, Any]) -> None:
        """Callback for data updates."""

    parser = INKBIRDBluetoothDeviceData(
        Model.IAM_T1, {}, _update_callback, _data_callback
    )
    service_info = make_bluetooth_service_info(
        name="Ink@IAM-T1",
        manufacturer_data={12628: b"AC-6200a13cae\x00\x00"},
        service_uuids=["0000fff0-0000-1000-8000-00805f9b34fb"],
        address="62:00:A1:3C:AE:7B",
        rssi=-44,
        service_data={},
        source="local",
    )
    parser.update(service_info)
    disconnect_mock = AsyncMock()

    async def start_notify_mock(
        uuid: UUID, callback: Callable[[UUID, bytes], None]
    ) -> None:
        # Unit-setting packet (no update callback)
        callback(uuid, b"U\xaa\x05\x0c\x00\x00\x00\x00\x00\x00\x00\x10")
        # Data packet with humidity bytes ff ff -> 6553.5%; must be dropped
        # whole rather than publishing a temperature from a corrupt packet.
        callback(uuid, b"U\xaa\x01\x10\x00\x00\xe8\xff\xff\x04M\x03\xfe\x01\x00A")

    mock_client = MagicMock(start_notify=start_notify_mock, disconnect=disconnect_mock)
    with patch("inkbird_ble.parser.establish_connection", return_value=mock_client):
        await parser.async_start(
            service_info,
            BLEDevice(
                address="62:00:A1:3C:AE:7B",
                name="Ink@IAM-T1",
                details={},
            ),
        )
        await asyncio.sleep(0)
        await parser.async_stop()

    # The corrupt packet produced no update callback at all.
    assert updates == []


@pytest.mark.asyncio
async def test_iam_t1_multiple_updates_with_broken_packet() -> None:
    """Test IAM-T1 handling multiple updates from issue #119.

    This test validates that the parser correctly processes a sequence of packets
    including a broken packet (12 bytes with data prefix) that should be ignored.
    The test uses real packet data from issue #119 where a truncated packet
    caused the unit to incorrectly switch.
    """
    updates: list[SensorUpdate] = []

    def _update_callback(update: SensorUpdate) -> None:
        updates.append(update)

    def _data_callback(data: dict[str, Any]) -> None:
        """Callback for data updates."""

    parser = INKBIRDBluetoothDeviceData(
        Model.IAM_T1, {}, _update_callback, _data_callback
    )
    service_info = make_bluetooth_service_info(
        name="Ink@IAM-T1",
        manufacturer_data={12628: b"AC-6200a13cae\x00\x00"},
        service_uuids=["0000fff0-0000-1000-8000-00805f9b34fb"],
        address="62:00:A1:3C:AE:7B",
        rssi=-44,
        service_data={},
        source="local",
    )
    parser.update(service_info)
    disconnect_mock = AsyncMock()

    async def start_notify_mock(
        uuid: UUID, callback: Callable[[UUID, bytes], None]
    ) -> None:
        # Initial unit setting (Celsius) - doesn't trigger update callback
        callback(uuid, b"U\xaa\x05\x0c\x00\x00\x00\x00\x00\x00\x00\x10")
        # Valid data packet 1: temp=23.3°C, humidity=50.0%, co2=1103ppm
        callback(uuid, b"U\xaa\x01\x10\x00\x00\xe9\x01\xf4\x04O\x03\xfe\x01\x00C")
        # Valid data packet 2: temp=23.2°C, humidity=50.0%, co2=1101ppm
        callback(uuid, b"U\xaa\x01\x10\x00\x00\xe8\x01\xf4\x04M\x03\xfe\x01\x00A")
        # The broken packet (12 bytes with data prefix, should be 16)
        # This packet will be ignored
        callback(uuid, b"U\xaa\x01\x10\x00\x00\xe8\x01\xf4\x04K\x03")
        # Valid data packet 3 (after broken packet)
        callback(uuid, b"U\xaa\x01\x10\x00\x00\xe8\x01\xf4\x04F\x03\xfe\x01\x009")
        # Valid data packet 4
        callback(uuid, b"U\xaa\x01\x10\x00\x00\xe8\x01\xf4\x04D\x03\xfe\x01\x007")

    mock_client = MagicMock(start_notify=start_notify_mock, disconnect=disconnect_mock)
    with patch("inkbird_ble.parser.establish_connection", return_value=mock_client):
        await parser.async_start(
            service_info,
            BLEDevice(
                address="62:00:A1:3C:AE:7B",
                name="Ink@IAM-T1",
                details={},
            ),
        )
        await asyncio.sleep(0)
        await parser.async_stop()

    # Should have received updates for the 4 valid data packets
    # (not the broken one)
    # This is the key assertion: we got exactly 4 updates,
    # proving the broken packet was ignored
    assert len(updates) == 4

    # Verify the final update has values from the last valid packet
    # Note: Due to how the parser works, all updates reference the
    # same mutable state, so we can only reliably verify the final
    # state matches the last packet sent
    temp_key = DeviceKey(key="temperature", device_id=None)
    humidity_key = DeviceKey(key="humidity", device_id=None)
    co2_key = DeviceKey(key="carbon_dioxide", device_id=None)

    # The last update should have values from packet 4
    assert updates[-1].entity_values[temp_key].native_value == 23.2
    assert updates[-1].entity_values[humidity_key].native_value == 50.0
    assert updates[-1].entity_values[co2_key].native_value == 1092


@pytest.mark.asyncio
async def test_retry_iam_t1_f() -> None:
    """Test retry with notify with passing data in F."""

    last_update: SensorUpdate | None = None
    data_callbacks: list[dict[str, Any]] = []

    def _update_callback(update: SensorUpdate) -> None:
        nonlocal last_update
        last_update = update

    def _data_callback(data: dict[str, Any]) -> None:
        """
        Callback for data updates.
        """
        data_callbacks.append(data.copy())

    parser = INKBIRDBluetoothDeviceData(
        Model.IAM_T1, {}, _update_callback, _data_callback
    )
    assert parser.device_type == Model.IAM_T1
    service_info = make_bluetooth_service_info(
        name="Ink@IAM-T1",
        manufacturer_data={12628: b"AC-6200a13cae\x00\x00"},
        service_uuids=["0000fff0-0000-1000-8000-00805f9b34fb"],
        address="62:00:A1:3C:AE:7B",
        rssi=-44,
        service_data={},
        source="local",
    )
    parser.update(service_info)
    assert parser.supported(service_info) is True
    assert parser.poll_needed(service_info, None) is False
    assert parser.uses_notify
    disconnect_mock = AsyncMock()

    attempt = 0

    async def start_notify_mock(
        uuid: UUID, callback: Callable[[UUID, bytes], None]
    ) -> None:
        nonlocal attempt
        attempt += 1
        if attempt == 1:
            msg = "test error"
            raise BleakError(msg)
        callback(uuid, b"U")
        callback(uuid, b"U\xaa\x05\x0c\x00\x00\x00\x00\x00\x00\x00\x11")
        callback(uuid, b"U\xaa\x05\x0c\x00\x00\x00\x00\x00\x00\x01\x11")
        callback(uuid, b"U\xaa\x01\x10\x10\x03\x0b\x01\xd6\x02\xe3\x03\xf1\x01\x00\xcf")

    mock_client = MagicMock(start_notify=start_notify_mock, disconnect=disconnect_mock)
    with patch("inkbird_ble.parser.establish_connection", return_value=mock_client):
        await parser.async_start(
            service_info,
            BLEDevice(
                address="62:00:A1:3C:AE:7B",
                name="Ink@IAM-T1",
                details={},
            ),
        )
        await asyncio.sleep(0)
        await parser.async_stop()

    assert last_update is not None
    assert data_callbacks == [
        {"temp_unit": Units.TEMP_CELSIUS},
        {"temp_unit": Units.TEMP_FAHRENHEIT},
    ]


@pytest.mark.asyncio
async def test_reconnect_iam_t1_f() -> None:
    """Test reconnect with notify with passing data in F."""

    last_update: SensorUpdate | None = None

    def _update_callback(update: SensorUpdate) -> None:
        nonlocal last_update
        last_update = update

    def _data_callback(data: dict[str, Any]) -> None:
        """
        Callback for data updates.
        """

    parser = INKBIRDBluetoothDeviceData(
        Model.IAM_T1, {}, _update_callback, _data_callback
    )
    assert parser.device_type == Model.IAM_T1
    service_info = make_bluetooth_service_info(
        name="Ink@IAM-T1",
        manufacturer_data={12628: b"AC-6200a13cae\x00\x00"},
        service_uuids=["0000fff0-0000-1000-8000-00805f9b34fb"],
        address="62:00:A1:3C:AE:7B",
        rssi=-44,
        service_data={},
        source="local",
    )
    parser.update(service_info)
    assert parser.supported(service_info) is True
    assert parser.poll_needed(service_info, None) is False
    assert parser.uses_notify
    disconnect_mock = AsyncMock()
    start_notify_calls = 0

    async def start_notify_mock(
        uuid: UUID, callback: Callable[[UUID, bytes], None]
    ) -> None:
        nonlocal start_notify_calls
        start_notify_calls += 1
        callback(uuid, b"U")
        callback(uuid, b"U\xaa\x05\x0c\x00\x00\x00\x00\x00\x00\x01\x11")
        callback(uuid, b"U\xaa\x01\x10\x10\x03\x0b\x01\xd6\x02\xe3\x03\xf1\x01\x00\xcf")

    set_disconnected_callback_mock = MagicMock()
    mock_client = MagicMock(
        start_notify=start_notify_mock,
        disconnect=disconnect_mock,
        set_disconnected_callback=set_disconnected_callback_mock,
    )
    with patch("inkbird_ble.parser.establish_connection", return_value=mock_client):
        await parser.async_start(
            service_info,
            BLEDevice(
                address="62:00:A1:3C:AE:7B",
                name="Ink@IAM-T1",
                details={},
            ),
        )
        await asyncio.sleep(0)
        assert set_disconnected_callback_mock.called
        set_disconnected_callback_mock.call_args[0][0](mock_client)
        await asyncio.sleep(0)
        assert start_notify_calls == 1
        async_fire_time_changed(datetime.now(UTC) + timedelta(seconds=5))
        await asyncio.sleep(0)
        assert start_notify_calls == 2
        await parser.async_stop()

    assert last_update is not None


@pytest.mark.asyncio
async def test_notify_iam_t1_connection_failure_retries() -> None:
    """A failed notify connection is logged and retried after the backoff.

    When every connection attempt raises (``async_connect_action`` propagates a
    ``BleakError``), ``_async_start_notify`` must swallow the error, wait, and
    reconnect on the next loop iteration rather than letting the notify task
    die. The first connection here fails; after the 5s backoff the retry
    succeeds and the device starts streaming.
    """
    last_update: SensorUpdate | None = None

    def _update_callback(update: SensorUpdate) -> None:
        nonlocal last_update
        last_update = update

    def _data_callback(data: dict[str, Any]) -> None:
        """Callback for data updates."""

    parser = INKBIRDBluetoothDeviceData(
        Model.IAM_T1, {}, _update_callback, _data_callback
    )
    service_info = make_bluetooth_service_info(
        name="Ink@IAM-T1",
        manufacturer_data={12628: b"AC-6200a13cae\x00\x00"},
        service_uuids=["0000fff0-0000-1000-8000-00805f9b34fb"],
        address="62:00:A1:3C:AE:7B",
        rssi=-44,
        service_data={},
        source="local",
    )
    parser.update(service_info)
    assert parser.uses_notify

    disconnect_mock = AsyncMock()

    async def start_notify_mock(
        uuid: UUID, callback: Callable[[UUID, bytes], None]
    ) -> None:
        callback(uuid, b"U\xaa\x05\x0c\x00\x00\x00\x00\x00\x00\x01\x11")
        callback(uuid, b"U\xaa\x01\x10\x10\x03\x0b\x01\xd6\x02\xe3\x03\xf1\x01\x00\xcf")

    mock_client = MagicMock(
        start_notify=start_notify_mock,
        disconnect=disconnect_mock,
        set_disconnected_callback=MagicMock(),
    )

    connect_calls = 0

    async def establish_mock(*_args: Any, **_kwargs: Any) -> MagicMock:
        nonlocal connect_calls
        connect_calls += 1
        if connect_calls == 1:
            msg = "connection failed"
            raise BleakError(msg)
        return mock_client

    with patch("inkbird_ble.parser.establish_connection", establish_mock):
        await parser.async_start(
            service_info,
            BLEDevice(address="62:00:A1:3C:AE:7B", name="Ink@IAM-T1", details={}),
        )
        await asyncio.sleep(0)
        # First attempt failed: the error was logged, nothing delivered yet.
        assert connect_calls == 1
        assert last_update is None
        # Advance past the 5s backoff so the loop reconnects and succeeds.
        async_fire_time_changed(datetime.now(UTC) + timedelta(seconds=5))
        await asyncio.sleep(0)
        assert connect_calls == 2
        await parser.async_stop()

    assert last_update is not None


def test_IBS_P02B():
    parser = INKBIRDBluetoothDeviceData()
    service_info = make_bluetooth_service_info(
        name="IBS-P02B",
        manufacturer_data={9289: bytes.fromhex("11180065d00000005a00800000000000")},
        service_uuids=["0000fff0-0000-1000-8000-00805f9b34fb"],
        address="aa:bb:cc:dd:ee:ff",
        rssi=-60,
        service_data={},
        source="local",
    )
    result = parser.update(service_info)
    assert parser.device_type == Model.IBS_P02B
    assert result == SensorUpdate(
        title=None,
        devices={
            None: SensorDeviceInfo(
                name="IBS-P02B EEFF",
                model="IBS-P02B",
                manufacturer="INKBIRD",
                sw_version=None,
                hw_version=None,
            )
        },
        entity_descriptions={
            DeviceKey(key="temperature", device_id=None): SensorDescription(
                device_key=DeviceKey(key="temperature", device_id=None),
                device_class=SensorDeviceClass.TEMPERATURE,
                native_unit_of_measurement=Units.TEMP_CELSIUS,
            ),
            DeviceKey(key="battery", device_id=None): SensorDescription(
                device_key=DeviceKey(key="battery", device_id=None),
                device_class=SensorDeviceClass.BATTERY,
                native_unit_of_measurement=Units.PERCENTAGE,
            ),
            DeviceKey(key="signal_strength", device_id=None): SensorDescription(
                device_key=DeviceKey(key="signal_strength", device_id=None),
                device_class=SensorDeviceClass.SIGNAL_STRENGTH,
                native_unit_of_measurement=Units.SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
            ),
        },
        entity_values={
            DeviceKey(key="temperature", device_id=None): SensorValue(
                device_key=DeviceKey(key="temperature", device_id=None),
                name="Temperature",
                native_value=20.8,
            ),
            DeviceKey(key="battery", device_id=None): SensorValue(
                device_key=DeviceKey(key="battery", device_id=None),
                name="Battery",
                native_value=90,
            ),
            DeviceKey(key="signal_strength", device_id=None): SensorValue(
                device_key=DeviceKey(key="signal_strength", device_id=None),
                name="Signal Strength",
                native_value=-60,
            ),
        },
        binary_entity_descriptions={},
        binary_entity_values={},
        events={},
    )


def test_IBS_P02B_real_data():
    parser = INKBIRDBluetoothDeviceData()
    service_info = make_bluetooth_service_info(
        name="IBS-P02B",
        manufacturer_data={9289: bytes.fromhex("111800656e0100005f00000100000000")},
        service_uuids=["0000fff0-0000-1000-8000-00805f9b34fb"],
        address="49:24:11:18:00:65",
        rssi=-60,
        service_data={},
        source="local",
    )
    result = parser.update(service_info)
    assert parser.device_type == Model.IBS_P02B
    assert result == SensorUpdate(
        title=None,
        devices={
            None: SensorDeviceInfo(
                name="IBS-P02B 0065",
                model="IBS-P02B",
                manufacturer="INKBIRD",
                sw_version=None,
                hw_version=None,
            )
        },
        entity_descriptions={
            DeviceKey(key="battery", device_id=None): SensorDescription(
                device_key=DeviceKey(key="battery", device_id=None),
                device_class=SensorDeviceClass.BATTERY,
                native_unit_of_measurement=Units.PERCENTAGE,
            ),
            DeviceKey(key="signal_strength", device_id=None): SensorDescription(
                device_key=DeviceKey(key="signal_strength", device_id=None),
                device_class=SensorDeviceClass.SIGNAL_STRENGTH,
                native_unit_of_measurement=Units.SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
            ),
            DeviceKey(key="temperature", device_id=None): SensorDescription(
                device_key=DeviceKey(key="temperature", device_id=None),
                device_class=SensorDeviceClass.TEMPERATURE,
                native_unit_of_measurement=Units.TEMP_CELSIUS,
            ),
        },
        entity_values={
            DeviceKey(key="battery", device_id=None): SensorValue(
                device_key=DeviceKey(key="battery", device_id=None),
                name="Battery",
                native_value=95,
            ),
            DeviceKey(key="signal_strength", device_id=None): SensorValue(
                device_key=DeviceKey(key="signal_strength", device_id=None),
                name="Signal Strength",
                native_value=-60,
            ),
            DeviceKey(key="temperature", device_id=None): SensorValue(
                device_key=DeviceKey(key="temperature", device_id=None),
                name="Temperature",
                native_value=36.6,
            ),
        },
        binary_entity_descriptions={},
        binary_entity_values={},
        events={},
    )


def test_IBS_P02B_passive_detection():
    parser = INKBIRDBluetoothDeviceData()
    service_info = make_bluetooth_service_info(
        name="",
        manufacturer_data={9289: bytes.fromhex("11180065d00000005a00800000000000")},
        service_uuids=["0000fff0-0000-1000-8000-00805f9b34fb"],
        address="aa:bb:cc:dd:ee:ff",
        rssi=-60,
        service_data={},
        source="local",
    )
    result = parser.update(service_info)
    assert parser.device_type == Model.GENERIC_18
    assert result == SensorUpdate(
        title=None,
        devices={
            None: SensorDeviceInfo(
                name="Unknown 18-byte model EEFF",
                model="Unknown 18-byte model",
                manufacturer="INKBIRD",
                sw_version=None,
                hw_version=None,
            )
        },
        entity_descriptions={
            DeviceKey(key="temperature", device_id=None): SensorDescription(
                device_key=DeviceKey(key="temperature", device_id=None),
                device_class=SensorDeviceClass.TEMPERATURE,
                native_unit_of_measurement=Units.TEMP_CELSIUS,
            ),
            DeviceKey(key="battery", device_id=None): SensorDescription(
                device_key=DeviceKey(key="battery", device_id=None),
                device_class=SensorDeviceClass.BATTERY,
                native_unit_of_measurement=Units.PERCENTAGE,
            ),
            DeviceKey(key="signal_strength", device_id=None): SensorDescription(
                device_key=DeviceKey(key="signal_strength", device_id=None),
                device_class=SensorDeviceClass.SIGNAL_STRENGTH,
                native_unit_of_measurement=Units.SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
            ),
        },
        entity_values={
            DeviceKey(key="temperature", device_id=None): SensorValue(
                device_key=DeviceKey(key="temperature", device_id=None),
                name="Temperature",
                native_value=20.8,
            ),
            DeviceKey(key="battery", device_id=None): SensorValue(
                device_key=DeviceKey(key="battery", device_id=None),
                name="Battery",
                native_value=90,
            ),
            DeviceKey(key="signal_strength", device_id=None): SensorValue(
                device_key=DeviceKey(key="signal_strength", device_id=None),
                name="Signal Strength",
                native_value=-60,
            ),
        },
        binary_entity_descriptions={},
        binary_entity_values={},
        events={},
    )


def test_IBS_P02B_multiple_updates():
    """Test multiple sequential updates from an IBS-P02B device with real-world data.

    This test uses real data captured from an IBS-P02B device to verify that the
    parser correctly handles multiple updates with varying signal strengths
    but consistent temperature readings.
    """
    parser = INKBIRDBluetoothDeviceData()

    # 1st update - 2025-05-08 23:36:23.808
    service_info = make_bluetooth_service_info(
        name="IBS-P02B",
        manufacturer_data={
            9289: b"\x11\x18\x00ev\x01\x00\x00_\x00\x00\x01\x00\x00\x00\x00"
        },
        service_uuids=["0000fff0-0000-1000-8000-00805f9b34fb"],
        address="49:24:11:18:00:65",
        rssi=-83,
        service_data={},
        source="B8:D6:1A:8B:C7:C6",
        raw=b"\x02\x01\x06\x03\x02\xf0\xff\t\tIBS-P02B\x13\xffI$\x11\x18\x00ev\x01\x00\x00_\x00\x00\x01\x00\x00\x00\x00",
    )
    result = parser.update(service_info)
    assert parser.device_type == Model.IBS_P02B
    assert (
        result.entity_values[
            DeviceKey(key="signal_strength", device_id=None)
        ].native_value
        == -83
    )
    assert (
        result.entity_values[DeviceKey(key="battery", device_id=None)].native_value
        == 95
    )
    assert (
        result.entity_values[DeviceKey(key="temperature", device_id=None)].native_value
        == 37.4
    )

    # 2nd update - 2025-05-08 23:36:44.518
    service_info = make_bluetooth_service_info(
        name="IBS-P02B",
        manufacturer_data={
            9289: b"\x11\x18\x00ev\x01\x00\x00`\x00\x00\x01\x00\x00\x00\x00"
        },
        service_uuids=["0000fff0-0000-1000-8000-00805f9b34fb"],
        address="49:24:11:18:00:65",
        rssi=-77,
        service_data={},
        source="B8:D6:1A:8B:C7:C6",
        raw=b"\x02\x01\x06\x03\x02\xf0\xff\t\tIBS-P02B\x13\xffI$\x11\x18\x00ev\x01\x00\x00`\x00\x00\x01\x00\x00\x00\x00",
    )
    result = parser.update(service_info)
    assert parser.device_type == Model.IBS_P02B
    assert (
        result.entity_values[
            DeviceKey(key="signal_strength", device_id=None)
        ].native_value
        == -77
    )
    assert (
        result.entity_values[DeviceKey(key="battery", device_id=None)].native_value
        == 96
    )
    assert (
        result.entity_values[DeviceKey(key="temperature", device_id=None)].native_value
        == 37.4
    )

    # 3rd update - 2025-05-08 23:37:52.300
    service_info = make_bluetooth_service_info(
        name="IBS-P02B",
        manufacturer_data={
            9289: b"\x11\x18\x00ev\x01\x00\x00_\x00\x00\x01\x00\x00\x00\x00"
        },
        service_uuids=["0000fff0-0000-1000-8000-00805f9b34fb"],
        address="49:24:11:18:00:65",
        rssi=-73,
        service_data={},
        source="B8:D6:1A:8B:C7:C6",
        raw=b"\x02\x01\x06\x03\x02\xf0\xff\t\tIBS-P02B\x13\xffI$\x11\x18\x00ev\x01\x00\x00_\x00\x00\x01\x00\x00\x00\x00",
    )
    result = parser.update(service_info)
    assert parser.device_type == Model.IBS_P02B
    assert (
        result.entity_values[
            DeviceKey(key="signal_strength", device_id=None)
        ].native_value
        == -73
    )
    assert (
        result.entity_values[DeviceKey(key="battery", device_id=None)].native_value
        == 95
    )
    assert (
        result.entity_values[DeviceKey(key="temperature", device_id=None)].native_value
        == 37.4
    )

    # 4th update - 2025-05-08 23:38:25.011
    service_info = make_bluetooth_service_info(
        name="IBS-P02B",
        manufacturer_data={
            9289: b"\x11\x18\x00ev\x01\x00\x00`\x00\x00\x01\x00\x00\x00\x00"
        },
        service_uuids=["0000fff0-0000-1000-8000-00805f9b34fb"],
        address="49:24:11:18:00:65",
        rssi=-74,
        service_data={},
        source="B8:D6:1A:8B:C7:C6",
        raw=b"\x02\x01\x06\x03\x02\xf0\xff\t\tIBS-P02B\x13\xffI$\x11\x18\x00ev\x01\x00\x00`\x00\x00\x01\x00\x00\x00\x00",
    )
    result = parser.update(service_info)
    assert parser.device_type == Model.IBS_P02B
    assert (
        result.entity_values[
            DeviceKey(key="signal_strength", device_id=None)
        ].native_value
        == -74
    )
    assert (
        result.entity_values[DeviceKey(key="battery", device_id=None)].native_value
        == 96
    )
    assert (
        result.entity_values[DeviceKey(key="temperature", device_id=None)].native_value
        == 37.4
    )

    # 5th update - 2025-05-08 23:39:52.325
    service_info = make_bluetooth_service_info(
        name="IBS-P02B",
        manufacturer_data={
            9289: b"\x11\x18\x00ev\x01\x00\x00_\x00\x00\x01\x00\x00\x00\x00"
        },
        service_uuids=["0000fff0-0000-1000-8000-00805f9b34fb"],
        address="49:24:11:18:00:65",
        rssi=-79,
        service_data={},
        source="B8:D6:1A:8B:C7:C6",
        raw=b"\x02\x01\x06\x03\x02\xf0\xff\t\tIBS-P02B\x13\xffI$\x11\x18\x00ev\x01\x00\x00_\x00\x00\x01\x00\x00\x00\x00",
    )
    result = parser.update(service_info)
    assert parser.device_type == Model.IBS_P02B
    assert (
        result.entity_values[
            DeviceKey(key="signal_strength", device_id=None)
        ].native_value
        == -79
    )
    assert (
        result.entity_values[DeviceKey(key="battery", device_id=None)].native_value
        == 95
    )
    assert (
        result.entity_values[DeviceKey(key="temperature", device_id=None)].native_value
        == 37.4
    )

    # 6th update - 2025-05-08 23:40:53.261
    service_info = make_bluetooth_service_info(
        name="IBS-P02B",
        manufacturer_data={
            9289: b"\x11\x18\x00ev\x01\x00\x00`\x00\x00\x01\x00\x00\x00\x00"
        },
        service_uuids=["0000fff0-0000-1000-8000-00805f9b34fb"],
        address="49:24:11:18:00:65",
        rssi=-78,
        service_data={},
        source="B8:D6:1A:8B:C7:C6",
        raw=b"\x02\x01\x06\x03\x02\xf0\xff\t\tIBS-P02B\x13\xffI$\x11\x18\x00ev\x01\x00\x00`\x00\x00\x01\x00\x00\x00\x00",
    )
    result = parser.update(service_info)
    assert parser.device_type == Model.IBS_P02B
    assert (
        result.entity_values[
            DeviceKey(key="signal_strength", device_id=None)
        ].native_value
        == -78
    )
    assert (
        result.entity_values[DeviceKey(key="battery", device_id=None)].native_value
        == 96
    )
    assert (
        result.entity_values[DeviceKey(key="temperature", device_id=None)].native_value
        == 37.4
    )

    # 7th update - 2025-05-08 23:42:47.511
    service_info = make_bluetooth_service_info(
        name="IBS-P02B",
        manufacturer_data={
            9289: b"\x11\x18\x00ev\x01\x00\x00_\x00\x00\x01\x00\x00\x00\x00"
        },
        service_uuids=["0000fff0-0000-1000-8000-00805f9b34fb"],
        address="49:24:11:18:00:65",
        rssi=-72,
        service_data={},
        source="B8:D6:1A:8B:C7:C6",
        raw=b"\x02\x01\x06\x03\x02\xf0\xff\t\tIBS-P02B\x13\xffI$\x11\x18\x00ev\x01\x00\x00_\x00\x00\x01\x00\x00\x00\x00",
    )
    result = parser.update(service_info)
    assert parser.device_type == Model.IBS_P02B
    assert (
        result.entity_values[
            DeviceKey(key="signal_strength", device_id=None)
        ].native_value
        == -72
    )
    assert (
        result.entity_values[DeviceKey(key="battery", device_id=None)].native_value
        == 95
    )
    assert (
        result.entity_values[DeviceKey(key="temperature", device_id=None)].native_value
        == 37.4
    )

    # 8th update - 2025-05-08 23:43:48.405
    service_info = make_bluetooth_service_info(
        name="IBS-P02B",
        manufacturer_data={
            9289: b"\x11\x18\x00ev\x01\x00\x00`\x00\x00\x01\x00\x00\x00\x00"
        },
        service_uuids=["0000fff0-0000-1000-8000-00805f9b34fb"],
        address="49:24:11:18:00:65",
        rssi=-78,
        service_data={},
        source="B8:D6:1A:8B:C7:C6",
        raw=b"\x02\x01\x06\x03\x02\xf0\xff\t\tIBS-P02B\x13\xffI$\x11\x18\x00ev\x01\x00\x00`\x00\x00\x01\x00\x00\x00\x00",
    )
    result = parser.update(service_info)
    assert parser.device_type == Model.IBS_P02B
    assert (
        result.entity_values[
            DeviceKey(key="signal_strength", device_id=None)
        ].native_value
        == -78
    )
    assert (
        result.entity_values[DeviceKey(key="battery", device_id=None)].native_value
        == 96
    )
    assert (
        result.entity_values[DeviceKey(key="temperature", device_id=None)].native_value
        == 37.4
    )

    # 9th update - 2025-05-08 23:44:37.322
    service_info = make_bluetooth_service_info(
        name="IBS-P02B",
        manufacturer_data={
            9289: b"\x11\x18\x00ev\x01\x00\x00_\x00\x00\x01\x00\x00\x00\x00"
        },
        service_uuids=["0000fff0-0000-1000-8000-00805f9b34fb"],
        address="49:24:11:18:00:65",
        rssi=-75,
        service_data={},
        source="B8:D6:1A:8B:C7:C6",
        raw=b"\x02\x01\x06\x03\x02\xf0\xff\t\tIBS-P02B\x13\xffI$\x11\x18\x00ev\x01\x00\x00_\x00\x00\x01\x00\x00\x00\x00",
    )
    result = parser.update(service_info)
    assert parser.device_type == Model.IBS_P02B
    assert (
        result.entity_values[
            DeviceKey(key="signal_strength", device_id=None)
        ].native_value
        == -75
    )
    assert (
        result.entity_values[DeviceKey(key="battery", device_id=None)].native_value
        == 95
    )
    assert (
        result.entity_values[DeviceKey(key="temperature", device_id=None)].native_value
        == 37.4
    )

    # 10th update - 2025-05-08 23:46:30.410
    service_info = make_bluetooth_service_info(
        name="IBS-P02B",
        manufacturer_data={
            9289: b"\x11\x18\x00ev\x01\x00\x00`\x00\x00\x01\x00\x00\x00\x00"
        },
        service_uuids=["0000fff0-0000-1000-8000-00805f9b34fb"],
        address="49:24:11:18:00:65",
        rssi=-76,
        service_data={},
        source="B8:D6:1A:8B:C7:C6",
        raw=b"\x02\x01\x06\x03\x02\xf0\xff\t\tIBS-P02B\x13\xffI$\x11\x18\x00ev\x01\x00\x00`\x00\x00\x01\x00\x00\x00\x00",
    )
    result = parser.update(service_info)
    assert parser.device_type == Model.IBS_P02B
    assert (
        result.entity_values[
            DeviceKey(key="signal_strength", device_id=None)
        ].native_value
        == -76
    )
    assert (
        result.entity_values[DeviceKey(key="battery", device_id=None)].native_value
        == 96
    )
    assert (
        result.entity_values[DeviceKey(key="temperature", device_id=None)].native_value
        == 37.4
    )

    # 11th update - 2025-05-08 23:46:37.319
    service_info = make_bluetooth_service_info(
        name="IBS-P02B",
        manufacturer_data={
            9289: b"\x11\x18\x00ev\x01\x00\x00_\x00\x00\x01\x00\x00\x00\x00"
        },
        service_uuids=["0000fff0-0000-1000-8000-00805f9b34fb"],
        address="49:24:11:18:00:65",
        rssi=-81,
        service_data={},
        source="B8:D6:1A:8B:C7:C6",
        raw=b"\x02\x01\x06\x03\x02\xf0\xff\t\tIBS-P02B\x13\xffI$\x11\x18\x00ev\x01\x00\x00_\x00\x00\x01\x00\x00\x00\x00",
    )
    result = parser.update(service_info)
    assert parser.device_type == Model.IBS_P02B
    assert (
        result.entity_values[
            DeviceKey(key="signal_strength", device_id=None)
        ].native_value
        == -81
    )
    assert (
        result.entity_values[DeviceKey(key="battery", device_id=None)].native_value
        == 95
    )
    assert (
        result.entity_values[DeviceKey(key="temperature", device_id=None)].native_value
        == 37.4
    )

    # 12th update - 2025-05-08 23:47:57.110
    service_info = make_bluetooth_service_info(
        name="IBS-P02B",
        manufacturer_data={
            9289: b"\x11\x18\x00ev\x01\x00\x00`\x00\x00\x01\x00\x00\x00\x00"
        },
        service_uuids=["0000fff0-0000-1000-8000-00805f9b34fb"],
        address="49:24:11:18:00:65",
        rssi=-78,
        service_data={},
        source="B8:D6:1A:8B:C7:C6",
        raw=b"\x02\x01\x06\x03\x02\xf0\xff\t\tIBS-P02B\x13\xffI$\x11\x18\x00ev\x01\x00\x00`\x00\x00\x01\x00\x00\x00\x00",
    )
    result = parser.update(service_info)
    assert parser.device_type == Model.IBS_P02B
    assert (
        result.entity_values[
            DeviceKey(key="signal_strength", device_id=None)
        ].native_value
        == -78
    )
    assert (
        result.entity_values[DeviceKey(key="battery", device_id=None)].native_value
        == 96
    )
    assert (
        result.entity_values[DeviceKey(key="temperature", device_id=None)].native_value
        == 37.4
    )

    # Verify device information is consistent throughout all updates
    assert result.devices[None].name == "IBS-P02B 0065"
    assert result.devices[None].model == "IBS-P02B"
    assert result.devices[None].manufacturer == "INKBIRD"

    # Verify that temperature was consistent throughout all updates
    assert (
        result.entity_values[DeviceKey(key="temperature", device_id=None)].native_value
        == 37.4
    )


def test_IBS_P02B_never_polls_on_first_sighting() -> None:
    """IBS-P02B must never request a connectable poll.

    The IBS-P02B broadcasts its full reading (temperature + battery) in the
    advertisement, so a connectable poll adds nothing. Worse, the firmware
    becomes unstable under active connections and stops responding until the
    batteries are pulled (see #116). ``poll_needed`` returns True on first
    sighting for any polling sensor, so guard that path explicitly.
    """
    parser = INKBIRDBluetoothDeviceData(Model.IBS_P02B)
    service_info = make_bluetooth_service_info(
        name="IBS-P02B",
        manufacturer_data={9289: bytes.fromhex("11180065d00000005a00800000000000")},
        service_uuids=["0000fff0-0000-1000-8000-00805f9b34fb"],
        address="aa:bb:cc:dd:ee:ff",
        rssi=-60,
        service_data={},
        source="local",
    )
    # No advertisement parsed yet (``_last_full_update == 0``): a polling
    # sensor would ask to connect here. The IBS-P02B must not.
    assert parser.poll_needed(service_info, None) is False


def test_IBS_P02B_never_polls_after_updates() -> None:
    """IBS-P02B never polls, even after advertisements have been parsed."""
    parser = INKBIRDBluetoothDeviceData()
    service_info = make_bluetooth_service_info(
        name="IBS-P02B",
        manufacturer_data={9289: bytes.fromhex("11180065d00000005a00800000000000")},
        service_uuids=["0000fff0-0000-1000-8000-00805f9b34fb"],
        address="aa:bb:cc:dd:ee:ff",
        rssi=-60,
        service_data={},
        source="local",
    )
    parser.update(service_info)
    assert parser.device_type == Model.IBS_P02B
    assert parser.poll_needed(service_info, None) is False


def test_iam_t2_detection() -> None:
    """Test IAM-T2 device detection from advertisement data."""
    # Using real data from issue #96
    service_info = make_bluetooth_service_info(
        name="Ink@IAM-T2",
        manufacturer_data={12884: bytes.fromhex("006200a13e2c6a4202d001be025f72")},
        service_uuids=[],
        address="62:00:A1:3E:2C:6A",
        rssi=-78,
        service_data={},
        source="Core Bluetooth",
    )
    parser = INKBIRDBluetoothDeviceData()
    parser.update(service_info)
    assert parser.device_type == Model.IAM_T2
    assert parser.supported(service_info) is True
    assert parser.uses_notify is False


def test_iam_t2_sensor_data() -> None:
    """Test IAM-T2 sensor data parsing from advertisement data."""
    parser = INKBIRDBluetoothDeviceData()
    # Real data from user: 28.2°C, 55% humidity, 615 CO2
    service_info = make_bluetooth_service_info(
        name="Ink@IAM-T2",
        manufacturer_data={12884: bytes.fromhex("006200a13e29bed4011a0227026791")},
        service_uuids=[],
        address="62:00:A1:3E:29:BE",
        rssi=-67,
        service_data={},
        source="Core Bluetooth",
    )
    assert parser.supported(service_info) is True
    assert parser.device_type == Model.IAM_T2
    result = parser.update(service_info)
    assert result == SensorUpdate(
        title=None,
        devices={
            None: SensorDeviceInfo(
                name="IAM-T2 29BE",
                model="IAM-T2",
                manufacturer="INKBIRD",
                sw_version=None,
                hw_version=None,
            )
        },
        entity_descriptions={
            DeviceKey(key="signal_strength", device_id=None): SensorDescription(
                device_key=DeviceKey(key="signal_strength", device_id=None),
                device_class=SensorDeviceClass.SIGNAL_STRENGTH,
                native_unit_of_measurement=Units.SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
            ),
            DeviceKey(key="temperature", device_id=None): SensorDescription(
                device_key=DeviceKey(key="temperature", device_id=None),
                device_class=SensorDeviceClass.TEMPERATURE,
                native_unit_of_measurement=Units.TEMP_CELSIUS,
            ),
            DeviceKey(key="humidity", device_id=None): SensorDescription(
                device_key=DeviceKey(key="humidity", device_id=None),
                device_class=SensorDeviceClass.HUMIDITY,
                native_unit_of_measurement=Units.PERCENTAGE,
            ),
            DeviceKey(key="carbon_dioxide", device_id=None): SensorDescription(
                device_key=DeviceKey(key="carbon_dioxide", device_id=None),
                device_class=SensorDeviceClass.CO2,
                native_unit_of_measurement=Units.CONCENTRATION_PARTS_PER_MILLION,
            ),
        },
        entity_values={
            DeviceKey(key="signal_strength", device_id=None): SensorValue(
                device_key=DeviceKey(key="signal_strength", device_id=None),
                name="Signal Strength",
                native_value=-67,
            ),
            DeviceKey(key="temperature", device_id=None): SensorValue(
                device_key=DeviceKey(key="temperature", device_id=None),
                name="Temperature",
                native_value=28.2,
            ),
            DeviceKey(key="humidity", device_id=None): SensorValue(
                device_key=DeviceKey(key="humidity", device_id=None),
                name="Humidity",
                native_value=55.1,
            ),
            DeviceKey(key="carbon_dioxide", device_id=None): SensorValue(
                device_key=DeviceKey(key="carbon_dioxide", device_id=None),
                name="Carbon Dioxide",
                native_value=615,
            ),
        },
        binary_entity_descriptions={},
        binary_entity_values={},
        events={},
    )


def test_iam_t2_fahrenheit_mode() -> None:
    """Test IAM-T2 in Fahrenheit mode with real data."""
    parser = INKBIRDBluetoothDeviceData()
    # Real data from user: 82.8°F, 45.7% humidity, 576 CO2
    service_info = make_bluetooth_service_info(
        name="Ink@IAM-T2",
        manufacturer_data={12884: bytes.fromhex("006200a13e29bed6033c01c9024091")},
        service_uuids=[],
        address="62:00:A1:3E:29:BE",
        rssi=-66,
        service_data={},
        source="Core Bluetooth",
    )
    result = parser.update(service_info)
    assert parser.device_type == Model.IAM_T2
    # 82.8°F = 28.22°C
    assert (
        round(
            result.entity_values[
                DeviceKey(key="temperature", device_id=None)
            ].native_value,
            1,
        )
        == 28.2
    )
    assert (
        result.entity_values[DeviceKey(key="humidity", device_id=None)].native_value
        == 45.7
    )
    assert (
        result.entity_values[
            DeviceKey(key="carbon_dioxide", device_id=None)
        ].native_value
        == 576
    )


def test_iam_t2_celsius_mode() -> None:
    """Test IAM-T2 in Celsius mode with real data."""
    parser = INKBIRDBluetoothDeviceData()
    # Real data from user: 27.9°C, 49.4% humidity, 595 CO2
    service_info = make_bluetooth_service_info(
        name="Ink@IAM-T2",
        manufacturer_data={12884: bytes.fromhex("006200a13e29bed4011701ee025391")},
        service_uuids=[],
        address="62:00:A1:3E:29:BE",
        rssi=-65,
        service_data={},
        source="Core Bluetooth",
    )
    result = parser.update(service_info)
    assert parser.device_type == Model.IAM_T2
    # Temperature in Celsius mode
    assert (
        result.entity_values[DeviceKey(key="temperature", device_id=None)].native_value
        == 27.9
    )
    assert (
        result.entity_values[DeviceKey(key="humidity", device_id=None)].native_value
        == 49.4
    )
    assert (
        result.entity_values[
            DeviceKey(key="carbon_dioxide", device_id=None)
        ].native_value
        == 595
    )


def test_iam_t2_sub_zero_celsius() -> None:
    """Sub-zero IAM-T2 reading must stay negative, not wrap to ~6553°C (#188)."""
    parser = INKBIRDBluetoothDeviceData()
    # status d4 = Celsius mode; temp bytes ffce = -50 tenths = -5.0°C.
    service_info = make_bluetooth_service_info(
        name="Ink@IAM-T2",
        manufacturer_data={12884: bytes.fromhex("006200a13e29bed4ffce01ee025391")},
        service_uuids=[],
        address="62:00:A1:3E:29:BE",
        rssi=-65,
        service_data={},
        source="Core Bluetooth",
    )
    result = parser.update(service_info)
    assert parser.device_type == Model.IAM_T2
    assert (
        result.entity_values[DeviceKey(key="temperature", device_id=None)].native_value
        == -5.0
    )


def test_iam_t2_sub_zero_fahrenheit() -> None:
    """Sub-zero Fahrenheit IAM-T2 reading must convert to negative Celsius (#188)."""
    parser = INKBIRDBluetoothDeviceData()
    # status d6 = Fahrenheit mode; temp bytes ffd8 = -40 tenths = -4.0°F = -20.0°C.
    service_info = make_bluetooth_service_info(
        name="Ink@IAM-T2",
        manufacturer_data={12884: bytes.fromhex("006200a13e29bed6ffd801ee025391")},
        service_uuids=[],
        address="62:00:A1:3E:29:BE",
        rssi=-65,
        service_data={},
        source="Core Bluetooth",
    )
    result = parser.update(service_info)
    assert parser.device_type == Model.IAM_T2
    assert (
        round(
            result.entity_values[
                DeviceKey(key="temperature", device_id=None)
            ].native_value,
            1,
        )
        == -20.0
    )


def test_iam_t2_corrupt_humidity_dropped() -> None:
    """A corrupt IAM-T2 reading (humidity > 100%) is dropped (#141 family)."""
    parser = INKBIRDBluetoothDeviceData()
    # status d4 = Celsius, temp ffce = -5.0°C (valid), humidity ffff = 6553.5%
    # (garbage). The impossible humidity must drop the whole advertisement.
    service_info = make_bluetooth_service_info(
        name="Ink@IAM-T2",
        manufacturer_data={12884: bytes.fromhex("006200a13e29bed4ffceffff025391")},
        service_uuids=[],
        address="62:00:A1:3E:29:BE",
        rssi=-65,
        service_data={},
        source="Core Bluetooth",
    )
    result = parser.update(service_info)
    assert parser.device_type == Model.IAM_T2
    # Only the always-present signal strength survives; no sensor values leak.
    assert set(result.entity_values) == {
        DeviceKey(key="signal_strength", device_id=None)
    }


def test_iam_t2_fahrenheit_mode_82f() -> None:
    """Test IAM-T2 in Fahrenheit mode with 82°F data."""
    parser = INKBIRDBluetoothDeviceData()
    # Real data from user: 82.0°F, 52.3% humidity, 667 CO2
    service_info = make_bluetooth_service_info(
        name="Ink@IAM-T2",
        manufacturer_data={12884: bytes.fromhex("006200a13e29bed60334020b029b91")},
        service_uuids=[],
        address="62:00:A1:3E:29:BE",
        rssi=-73,
        service_data={},
        source="Core Bluetooth",
    )
    result = parser.update(service_info)
    assert parser.device_type == Model.IAM_T2
    # 82.0°F = 27.78°C
    assert (
        round(
            result.entity_values[
                DeviceKey(key="temperature", device_id=None)
            ].native_value,
            1,
        )
        == 27.8
    )
    assert (
        result.entity_values[DeviceKey(key="humidity", device_id=None)].native_value
        == 52.3
    )
    assert (
        result.entity_values[
            DeviceKey(key="carbon_dioxide", device_id=None)
        ].native_value
        == 667
    )


def test_iam_t2_detection_without_name() -> None:
    """Test IAM-T2 device detection from manufacturer data alone without device name."""
    parser = INKBIRDBluetoothDeviceData()
    # Real data but with empty/generic name to test manufacturer data detection
    service_info = make_bluetooth_service_info(
        name="",  # Empty name to force detection via manufacturer data
        manufacturer_data={12884: bytes.fromhex("006200a13e29bed4011701ee025391")},
        service_uuids=[],
        address="62:00:A1:3E:29:BE",
        rssi=-65,
        service_data={},
        source="Core Bluetooth",
    )
    assert parser.supported(service_info) is True
    assert parser.device_type == Model.IAM_T2

    result = parser.update(service_info)
    assert result is not None

    # Verify it still parses data correctly
    assert (
        result.entity_values[DeviceKey(key="temperature", device_id=None)].native_value
        == 27.9
    )
    assert (
        result.entity_values[DeviceKey(key="humidity", device_id=None)].native_value
        == 49.4
    )
    assert (
        result.entity_values[
            DeviceKey(key="carbon_dioxide", device_id=None)
        ].native_value
        == 595
    )


def test_poll_needed_recency_uses_service_info_time() -> None:
    """A stale service_info forces a poll even if the parser updated recently."""
    parser = INKBIRDBluetoothDeviceData(Model.IBS_TH)
    service_info = make_bluetooth_service_info(
        name="sps",
        manufacturer_data={2096: b"\x0f\x12\x00Z\xc7W\x06"},
        service_uuids=["0000fff0-0000-1000-8000-00805f9b34fb"],
        address="aa:bb:cc:dd:ee:ff",
        rssi=-60,
        service_data={},
        source="local",
    )
    parser.update(service_info)
    assert parser.poll_needed(service_info, None) is False

    fresh = make_bluetooth_service_info(
        name="sps",
        manufacturer_data={2096: b"\x0f\x12\x00Z\xc7W\x06"},
        service_uuids=["0000fff0-0000-1000-8000-00805f9b34fb"],
        address="aa:bb:cc:dd:ee:ff",
        rssi=-60,
        service_data={},
        source="local",
    )
    stale = BluetoothServiceInfoBleak(
        name=fresh.name,
        manufacturer_data=fresh.manufacturer_data,
        service_uuids=fresh.service_uuids,
        address=fresh.address,
        rssi=fresh.rssi,
        service_data=fresh.service_data,
        source=fresh.source,
        device=fresh.device,
        time=monotonic_time_coarse() - 400.0,
        advertisement=None,
        connectable=True,
        tx_power=0,
    )
    assert parser.poll_needed(stale, None) is True


def test_iht_2pb_detected_from_advertisement() -> None:
    """The IHT-2PB is identified by name prefix and uses the notify flow."""
    parser = INKBIRDBluetoothDeviceData()
    service_info = make_bluetooth_service_info(
        name="Ink@IHT-2PB#c4b",
        manufacturer_data={18505: b"2PB6200a1359c4b"},
        service_uuids=[],
        address="62:00:A1:35:9C:4B",
        rssi=-33,
        service_data={},
        source="local",
    )
    parser.update(service_info)
    assert parser.device_type == Model.IHT_2PB
    assert parser.supported(service_info) is True
    assert parser.uses_notify is True
    # Notify-only model: it must not be marked as needing a readable poll.
    assert parser.poll_needed(service_info, None) is False


@pytest.mark.asyncio
async def test_notify_iht_2pb_probes() -> None:
    """Each notify packet reports one probe; sub-zero readings are signed."""
    updates: list[SensorUpdate] = []

    def _update_callback(update: SensorUpdate) -> None:
        updates.append(update)

    parser = INKBIRDBluetoothDeviceData(Model.IHT_2PB, {}, _update_callback, None)
    service_info = make_bluetooth_service_info(
        name="Ink@IHT-2PB#c4b",
        manufacturer_data={18505: b"2PB6200a1359c4b"},
        service_uuids=[],
        address="62:00:A1:35:9C:4B",
        rssi=-33,
        service_data={},
        source="local",
    )
    parser.update(service_info)
    assert parser.uses_notify is True

    async def start_notify_mock(
        uuid: UUID, callback: Callable[[UUID, bytes], None]
    ) -> None:
        # probe 1 -> 24.5C, probe 2 -> 100.0C, probe 3 -> -1.0C (sub-zero)
        callback(uuid, b"\x55\xaa\x02\x00\x00\xf5")
        callback(uuid, b"\x55\xaa\x04\x00\x03\xeb")
        callback(uuid, b"\x55\xaa\x06\x00\xff\xf5")

    write_mock = AsyncMock()
    mock_client = MagicMock(
        start_notify=start_notify_mock,
        write_gatt_char=write_mock,
        disconnect=AsyncMock(),
    )
    with patch("inkbird_ble.parser.establish_connection", return_value=mock_client):
        await parser.async_start(
            service_info,
            BLEDevice(
                address="62:00:A1:35:9C:4B",
                name="Ink@IHT-2PB#c4b",
                details={},
            ),
        )
        await asyncio.sleep(0)
        await parser.async_stop()

    # The accumulated final update carries all three probes.
    values = {
        key.key: value.native_value for key, value in updates[-1].entity_values.items()
    }
    assert values["temperature_probe_1"] == 24.5
    assert values["temperature_probe_2"] == 100.0
    assert values["temperature_probe_3"] == -1.0

    # Both activation commands were written after subscribing.
    written = {
        (call.args[0], bytes(call.args[1])) for call in write_mock.await_args_list
    }
    assert (IHT_2PB_WRITE_UUID, b"\x55\xaa\x19\x01\x00\x19") in written
    assert (IHT_2PB_NOTIFY_UUID, b"\x55\xaa\x1a\x01\x00\x1a") in written


@pytest.mark.asyncio
async def test_notify_iht_2pb_skips_invalid_packets() -> None:
    """Disconnected probes, unknown selectors and short packets are ignored."""
    updates: list[SensorUpdate] = []

    def _update_callback(update: SensorUpdate) -> None:
        updates.append(update)

    parser = INKBIRDBluetoothDeviceData(Model.IHT_2PB, {}, _update_callback, None)
    service_info = make_bluetooth_service_info(
        name="Ink@IHT-2PB#c4b",
        manufacturer_data={18505: b"2PB6200a1359c4b"},
        service_uuids=[],
        address="62:00:A1:35:9C:4B",
        rssi=-33,
        service_data={},
        source="local",
    )
    parser.update(service_info)

    async def start_notify_mock(
        uuid: UUID, callback: Callable[[UUID, bytes], None]
    ) -> None:
        callback(uuid, b"\x55\xaa\x02\x00\x64\x00")  # hi=100 -> unplugged dead zone
        callback(uuid, b"\x55\xaa\x03\x00\x00\xf5")  # selector 3 -> unknown
        callback(uuid, b"\x55\xaa")  # too short

    mock_client = MagicMock(
        start_notify=start_notify_mock,
        write_gatt_char=AsyncMock(),
        disconnect=AsyncMock(),
    )
    with patch("inkbird_ble.parser.establish_connection", return_value=mock_client):
        await parser.async_start(
            service_info,
            BLEDevice(
                address="62:00:A1:35:9C:4B",
                name="Ink@IHT-2PB#c4b",
                details={},
            ),
        )
        await asyncio.sleep(0)
        await parser.async_stop()

    # No valid probe packet -> the callback never emitted an update.
    assert updates == []


@pytest.mark.asyncio
async def test_notify_iht_2pb_write_error_is_swallowed() -> None:
    """A rejected activation write must not abort the notify session."""
    updates: list[SensorUpdate] = []

    def _update_callback(update: SensorUpdate) -> None:
        updates.append(update)

    parser = INKBIRDBluetoothDeviceData(Model.IHT_2PB, {}, _update_callback, None)
    service_info = make_bluetooth_service_info(
        name="Ink@IHT-2PB#c4b",
        manufacturer_data={18505: b"2PB6200a1359c4b"},
        service_uuids=[],
        address="62:00:A1:35:9C:4B",
        rssi=-33,
        service_data={},
        source="local",
    )
    parser.update(service_info)

    async def start_notify_mock(
        uuid: UUID, callback: Callable[[UUID, bytes], None]
    ) -> None:
        callback(uuid, b"\x55\xaa\x02\x00\x00\xf5")  # probe 1 -> 24.5C

    mock_client = MagicMock(
        start_notify=start_notify_mock,
        write_gatt_char=AsyncMock(side_effect=BleakError("does not allow writing")),
        disconnect=AsyncMock(),
    )
    with patch("inkbird_ble.parser.establish_connection", return_value=mock_client):
        await parser.async_start(
            service_info,
            BLEDevice(
                address="62:00:A1:35:9C:4B",
                name="Ink@IHT-2PB#c4b",
                details={},
            ),
        )
        await asyncio.sleep(0)
        await parser.async_stop()

    values = {
        key.key: value.native_value for key, value in updates[-1].entity_values.items()
    }
    assert values["temperature_probe_1"] == 24.5


@pytest.mark.asyncio
async def test_notify_iht_2pb_ignored_after_stop() -> None:
    """A notification delivered after the session is stopped is ignored."""
    updates: list[SensorUpdate] = []

    def _update_callback(update: SensorUpdate) -> None:
        updates.append(update)

    parser = INKBIRDBluetoothDeviceData(Model.IHT_2PB, {}, _update_callback, None)
    service_info = make_bluetooth_service_info(
        name="Ink@IHT-2PB#c4b",
        manufacturer_data={18505: b"2PB6200a1359c4b"},
        service_uuids=[],
        address="62:00:A1:35:9C:4B",
        rssi=-33,
        service_data={},
        source="local",
    )
    parser.update(service_info)

    captured: list[Callable[[UUID, bytes], None]] = []

    async def start_notify_mock(
        uuid: UUID, callback: Callable[[UUID, bytes], None]
    ) -> None:
        captured.append(callback)

    mock_client = MagicMock(
        start_notify=start_notify_mock,
        write_gatt_char=AsyncMock(),
        disconnect=AsyncMock(),
    )
    with patch("inkbird_ble.parser.establish_connection", return_value=mock_client):
        await parser.async_start(
            service_info,
            BLEDevice(
                address="62:00:A1:35:9C:4B",
                name="Ink@IHT-2PB#c4b",
                details={},
            ),
        )
        await asyncio.sleep(0)
        await parser.async_stop()

    # Once the session has stopped, a late notification must be a no-op.
    captured[0](IHT_2PB_NOTIFY_UUID, b"\x55\xaa\x02\x00\x00\xf5")
    assert updates == []


def test_notify_callback_drops_model_without_handler() -> None:
    """A notification for a model with no notify handler is dropped, not raised."""
    updates: list[SensorUpdate] = []

    def _update_callback(update: SensorUpdate) -> None:
        updates.append(update)

    # IAM-T2 is a sensor-only model with no entry in the notify dispatch table,
    # so a stray notification must be ignored rather than raising.
    parser = INKBIRDBluetoothDeviceData(Model.IAM_T2, {}, _update_callback, None)
    parser._notify_callback(MagicMock(), bytearray(b"\x55\xaa\x02\x00\x00\xf5"))  # noqa: SLF001
    assert updates == []


def _int_11p_b_service_info() -> BluetoothServiceInfoBleak:
    """A representative INT-11P-B advertisement (carries no readings)."""
    return make_bluetooth_service_info(
        name="INT-11P-B",
        manufacturer_data={1576: b"\x0a\xc6\x7b\x90"},
        service_uuids=["0000fff0-0000-1000-8000-00805f9b34fb"],
        address="90:7B:C6:0A:06:28",
        rssi=-55,
        service_data={},
        source="local",
    )


def test_int_11p_b_detected_from_advertisement() -> None:
    """The INT-11P-B is identified by name and is a poll-only GATT model."""
    parser = INKBIRDBluetoothDeviceData()
    service_info = _int_11p_b_service_info()
    parser.update(service_info)
    assert parser.device_type == Model.INT_11P_B
    assert parser.supported(service_info) is True
    assert parser.name == "INT-11P-B 0628"
    # It reads from a characteristic rather than streaming notifications.
    assert parser.uses_notify is False
    # No readings in the advertisement, so a poll is due on first sighting.
    assert parser.poll_needed(service_info, None) is True


def test_int_11p_b_poll_needed_rate_limited() -> None:
    """poll_needed gates on time since last poll, not advertisement recency."""
    parser = INKBIRDBluetoothDeviceData(Model.INT_11P_B)
    service_info = _int_11p_b_service_info()
    parser.update(service_info)
    # Never polled -> due now.
    assert parser.poll_needed(service_info, None) is True
    # Polled recently -> not due yet (advertisement is always "fresh").
    assert parser.poll_needed(service_info, 10.0) is False
    # Last poll older than the interval -> due again.
    assert parser.poll_needed(service_info, MIN_POLL_INTERVAL + 1.0) is True


@pytest.mark.asyncio
async def test_int_11p_b_poll() -> None:
    """Polling reads fff1 and decodes both temperatures and both batteries."""
    parser = INKBIRDBluetoothDeviceData(Model.INT_11P_B)
    service_info = _int_11p_b_service_info()
    parser.update(service_info)
    assert parser.poll_needed(service_info, None) is True
    # 0xAA 0x20 0x80 0x1D 0xC8 0x38 0x54
    # probe=32C ambient=29C probe_batt=0xC8&0x7F=72% case_batt=0x38>>1=28%
    read_gatt_char_mock = AsyncMock(return_value=b"\xaa\x20\x80\x1d\xc8\x38\x54")
    mock_client = MagicMock(read_gatt_char=read_gatt_char_mock, disconnect=AsyncMock())
    with patch("inkbird_ble.parser.establish_connection", return_value=mock_client):
        update = await parser.async_poll(
            BLEDevice(address="90:7B:C6:0A:06:28", name="INT-11P-B", details={})
        )
    values = {
        key.key: value.native_value for key, value in update.entity_values.items()
    }
    assert values["temperature_probe"] == 32
    assert values["temperature_ambient"] == 29
    assert values["probe_battery"] == 72
    assert values["case_battery"] == 28


@pytest.mark.asyncio
async def test_int_11p_b_poll_skips_zero_ambient() -> None:
    """An ambient reading of 0 means "no value" and is not reported."""
    parser = INKBIRDBluetoothDeviceData(Model.INT_11P_B)
    parser.update(_int_11p_b_service_info())
    read_gatt_char_mock = AsyncMock(return_value=b"\xaa\x20\x80\x00\xc8\x38\x54")
    mock_client = MagicMock(read_gatt_char=read_gatt_char_mock, disconnect=AsyncMock())
    with patch("inkbird_ble.parser.establish_connection", return_value=mock_client):
        update = await parser.async_poll(
            BLEDevice(address="90:7B:C6:0A:06:28", name="INT-11P-B", details={})
        )
    keys = {key.key for key in update.entity_values}
    assert "temperature_probe" in keys
    assert "temperature_ambient" not in keys


@pytest.mark.asyncio
async def test_int_11p_b_poll_short_read_ignored() -> None:
    """A truncated read does not emit any temperature or battery values."""
    parser = INKBIRDBluetoothDeviceData(Model.INT_11P_B)
    parser.update(_int_11p_b_service_info())
    read_gatt_char_mock = AsyncMock(return_value=b"\xaa\x20\x80")
    mock_client = MagicMock(read_gatt_char=read_gatt_char_mock, disconnect=AsyncMock())
    with patch("inkbird_ble.parser.establish_connection", return_value=mock_client):
        update = await parser.async_poll(
            BLEDevice(address="90:7B:C6:0A:06:28", name="INT-11P-B", details={})
        )
    keys = {key.key for key in update.entity_values}
    assert "temperature_probe" not in keys
    assert "probe_battery" not in keys


@pytest.mark.asyncio
async def test_nine_byte_poll_short_read_ignored() -> None:
    """A truncated 9-byte poll read is skipped instead of raising.

    The decode unpacks ``payload[0:4]`` with a 4-byte struct; a shorter read
    would raise ``struct.error``. The guard drops it so the poll emits no
    temperature/humidity values.
    """
    parser = INKBIRDBluetoothDeviceData(Model.IBS_TH)
    service_info = make_bluetooth_service_info(
        name="N0BYD",
        manufacturer_data={},
        service_uuids=["0000fff0-0000-1000-8000-00805f9b34fb"],
        address="aa:bb:cc:dd:ee:ff",
        rssi=-60,
        service_data={},
        source="local",
    )
    parser.update(service_info)
    read_gatt_char_mock = AsyncMock(return_value=b"\x09\x09")
    mock_client = MagicMock(read_gatt_char=read_gatt_char_mock, disconnect=AsyncMock())
    with patch("inkbird_ble.parser.establish_connection", return_value=mock_client):
        update = await parser.async_poll(
            BLEDevice(address="aa:bb:cc:dd:ee:ff", name="N0BYD", details={})
        )
    keys = {key.key for key in update.entity_values}
    assert "temperature" not in keys
    assert "humidity" not in keys


@pytest.mark.asyncio
async def test_eighteen_byte_poll_short_read_ignored() -> None:
    """A truncated 18-byte poll read is skipped instead of raising.

    The decode slices ``payload[5:9]`` and indexes ``payload[9]``; a shorter
    read would raise ``IndexError``. The guard drops it so the poll emits no
    temperature/humidity/battery values.
    """
    parser = INKBIRDBluetoothDeviceData(Model.ITH_11_B)
    service_info = make_bluetooth_service_info(
        name="N0BYD",
        manufacturer_data={},
        service_uuids=["0000fff0-0000-1000-8000-00805f9b34fb"],
        address="aa:bb:cc:dd:ee:ff",
        rssi=-60,
        service_data={},
        source="local",
    )
    parser.update(service_info)
    read_gatt_char_mock = AsyncMock(return_value=b"\x00\x01\x02")
    mock_client = MagicMock(read_gatt_char=read_gatt_char_mock, disconnect=AsyncMock())
    with patch("inkbird_ble.parser.establish_connection", return_value=mock_client):
        update = await parser.async_poll(
            BLEDevice(address="aa:bb:cc:dd:ee:ff", name="N0BYD", details={})
        )
    keys = {key.key for key in update.entity_values}
    assert "temperature" not in keys
    assert "humidity" not in keys
    assert "battery" not in keys


@pytest.mark.asyncio
async def test_async_poll_without_gatt_decoder_emits_no_readings() -> None:
    """Polling a model with no GATT decode path produces no probe readings.

    Only the 18-byte, 9-byte and INT-11P-B models decode a connectable GATT
    read; any other pollable model (here the 17-byte IAM-T2) falls through
    ``async_poll`` without the INT-11P-B decoder running, so no probe values
    are emitted.
    """
    parser = INKBIRDBluetoothDeviceData(Model.IAM_T2)
    parser.update(
        make_bluetooth_service_info(
            name="IAM-T2",
            manufacturer_data={},
            service_uuids=[],
            address="00:62:00:00:00:01",
            rssi=-55,
            service_data={},
            source="local",
        )
    )
    read_gatt_char_mock = AsyncMock(return_value=b"\x00" * 17)
    mock_client = MagicMock(read_gatt_char=read_gatt_char_mock, disconnect=AsyncMock())
    with patch("inkbird_ble.parser.establish_connection", return_value=mock_client):
        update = await parser.async_poll(
            BLEDevice(address="00:62:00:00:00:01", name="IAM-T2", details={})
        )
    keys = {key.key for key in update.entity_values}
    assert "temperature_probe" not in keys
    assert "temperature_ambient" not in keys
    assert "probe_battery" not in keys
    assert "case_battery" not in keys


# ---------------------------------------------------------------------------
# Systematic corrupt-input boundary net (#141 family).
#
# Every advertisement temperature/humidity field was historically parsed
# unsigned, so a garbage ``0xFFFF`` field wrapped into a physically impossible
# reading (~6553% RH / ~6553 C). Each occurrence was fixed reactively in a
# different release (#141, #155, #188, #193, #209) and the next path bit again.
#
# This table feeds the disconnect/garbage sentinel into the humidity field of
# *every* advertisement sensor model and asserts the invariant the fixes were
# really enforcing: an impossible humidity is never published. The companion
# meta-test below ties the table to ``SENSOR_MODELS`` so a new advertisement
# parser cannot be added without declaring its corrupt-input expectation here.
# ---------------------------------------------------------------------------

# A valid 18-byte payload shared by the name-detected 18-byte models and the
# manufacturer-id-detected GENERIC_18 (humidity at mfr bytes [6:8] = 0x0190 ->
# 40.0%; trailing zeros keep GENERIC_18 detection happy).
_VALID_18_BYTE = b"\x08\x12\x00^\x00\x00\x90\x01d\x00d\x08\x00\x00\x00\x00"

# model -> (advertised name, manufacturer id, valid payload, humidity byte slice)
_ADV_HUMIDITY_BOUNDARY_CASES: dict[Model, tuple[str, int, bytes, slice]] = {
    Model.IBS_TH: ("sps", 2044, b"\xc7\x12\x00\xc8=V\x06", slice(0, 2)),
    Model.IBS_TH2: ("tps", 2248, b"\x84\x14\x00\x88\x99d\x06", slice(0, 2)),
    Model.ITH_11_B: ("ith-11-b", 9289, _VALID_18_BYTE, slice(6, 8)),
    Model.ITH_13_B: ("ith-13-b", 9289, _VALID_18_BYTE, slice(6, 8)),
    Model.ITH_21_B: ("ith-21-b", 9289, _VALID_18_BYTE, slice(6, 8)),
    Model.IBS_P02B: ("ibs-p02b", 9289, _VALID_18_BYTE, slice(6, 8)),
    Model.GENERIC_18: ("unknown", 9289, _VALID_18_BYTE, slice(6, 8)),
    Model.IAM_T2: (
        "ink@iam-t2",
        12884,
        bytes.fromhex("006200a13e29bed4ffce01ee025391"),
        slice(10, 12),
    ),
}

_HUMIDITY_KEY = DeviceKey(key="humidity", device_id=None)


def _boundary_service_info(
    name: str, mfr_id: int, payload: bytes
) -> BluetoothServiceInfoBleak:
    return make_bluetooth_service_info(
        name=name,
        manufacturer_data={mfr_id: payload},
        service_uuids=["0000fff0-0000-1000-8000-00805f9b34fb"],
        address="aa:bb:cc:dd:ee:ff",
        rssi=-60,
        service_data={},
        source="local",
    )


@pytest.mark.parametrize("model", list(_ADV_HUMIDITY_BOUNDARY_CASES))
def test_adv_humidity_boundary_invariant(model: Model) -> None:
    """No advertisement sensor model ever publishes an impossible humidity.

    The valid payload decodes to a plausible humidity; the same payload with a
    garbage ``0xFFFF`` humidity field publishes none (the corrupt packet is
    dropped). Guards the whole #141/#155/#188/#193/#209 family at once.
    """
    name, mfr_id, payload, humidity_slice = _ADV_HUMIDITY_BOUNDARY_CASES[model]

    # Baseline: the model is detected and reports a physically plausible value.
    valid = INKBIRDBluetoothDeviceData()
    valid_result = valid.update(_boundary_service_info(name, mfr_id, payload))
    assert valid.device_type is model
    valid_humidity = valid_result.entity_values.get(_HUMIDITY_KEY)
    assert valid_humidity is not None
    assert 0 <= valid_humidity.native_value <= MAX_PLAUSIBLE_HUMIDITY

    # Corrupt only the humidity field; detection bytes are untouched.
    corrupt_payload = bytearray(payload)
    corrupt_payload[humidity_slice] = b"\xff\xff"
    corrupt = INKBIRDBluetoothDeviceData()
    corrupt_result = corrupt.update(
        _boundary_service_info(name, mfr_id, bytes(corrupt_payload))
    )
    assert corrupt.device_type is model
    assert corrupt_result.entity_values.get(_HUMIDITY_KEY) is None


def test_adv_humidity_boundary_covers_every_sensor_model() -> None:
    """Every advertisement sensor model must declare a corrupt-input case.

    Forces a future device parser added to ``SENSOR_MODELS`` to also add a
    boundary entry, so the unsigned-humidity bug family cannot silently regrow.
    """
    assert set(_ADV_HUMIDITY_BOUNDARY_CASES) == SENSOR_MODELS


# ---------------------------------------------------------------------------
# Temperature side of the same boundary net (#155/#188/#193 family).
#
# Three separate fixes converted advertisement temperature parsers from
# unsigned to signed (BBQ <HH -> <hh in #193, IAM-T2 big-endian in #189, iBBQ-2
# in #185). The companion humidity net above proves a 0xFFFF *humidity* never
# escapes; this table proves a 0xFFFF *temperature* still decodes inside a
# plausible Celsius range — i.e. the parser is signed. A regression to the
# unsigned form would surface as ~6553 C and fail this invariant.
#
# Layout differs by model family:
#   * Nine-byte name-detected models (IBS-TH / IBS-TH2) read the temperature
#     from the manufacturer-id key itself, not the payload, so the corruption
#     swaps the mfr_id for ``0xFFFF`` rather than mutating payload bytes.
#   * Eighteen-byte / seventeen-byte models read the temperature from a fixed
#     payload slice; detection bytes (mfr_id, IAM-T2 MAC prefix) stay intact.
# ---------------------------------------------------------------------------

_TEMPERATURE_KEY = DeviceKey(key="temperature", device_id=None)

# Outer bound for a physically plausible decoded temperature in Celsius. An
# unsigned-temperature regression wraps 0xFFFF to ~6553.5; any value inside
# this range proves the parser is still signed.
_PLAUSIBLE_TEMP_CELSIUS_MAX = 200.0

# model -> (advertised name, manufacturer id, valid payload, temperature byte
# slice in the payload; ``None`` means "the temperature lives in the mfr_id
# itself — corrupt by swapping the key to 0xFFFF").
_ADV_TEMPERATURE_BOUNDARY_CASES: dict[Model, tuple[str, int, bytes, slice | None]] = {
    Model.IBS_TH: ("sps", 2044, b"\xc7\x12\x00\xc8=V\x06", None),
    Model.IBS_TH2: ("tps", 2248, b"\x84\x14\x00\x88\x99d\x06", None),
    Model.ITH_11_B: ("ith-11-b", 9289, _VALID_18_BYTE, slice(4, 6)),
    Model.ITH_13_B: ("ith-13-b", 9289, _VALID_18_BYTE, slice(4, 6)),
    Model.ITH_21_B: ("ith-21-b", 9289, _VALID_18_BYTE, slice(4, 6)),
    Model.IBS_P02B: ("ibs-p02b", 9289, _VALID_18_BYTE, slice(4, 6)),
    Model.GENERIC_18: ("unknown", 9289, _VALID_18_BYTE, slice(4, 6)),
    Model.IAM_T2: (
        "ink@iam-t2",
        12884,
        bytes.fromhex("006200a13e29bed4ffce01ee025391"),
        slice(8, 10),
    ),
}


@pytest.mark.parametrize("model", list(_ADV_TEMPERATURE_BOUNDARY_CASES))
def test_adv_temperature_boundary_invariant(model: Model) -> None:
    """A 0xFFFF advertisement temperature decodes inside a plausible range.

    Every advertisement temperature parser is now signed; a 0xFFFF field
    therefore decodes to a small negative number (e.g. -0.01 C / -0.1 C), not
    the ~6553 C wraparound the unsigned form produced (#155/#188/#193). If a
    future change regrew the unsigned parse, the decoded value would jump
    outside the plausible range and this test would fail.
    """
    name, mfr_id, payload, temp_slice = _ADV_TEMPERATURE_BOUNDARY_CASES[model]

    # Baseline: detection works and the valid payload decodes plausibly.
    valid = INKBIRDBluetoothDeviceData()
    valid_result = valid.update(_boundary_service_info(name, mfr_id, payload))
    assert valid.device_type is model
    valid_temp = valid_result.entity_values.get(_TEMPERATURE_KEY)
    assert valid_temp is not None
    assert abs(valid_temp.native_value) <= _PLAUSIBLE_TEMP_CELSIUS_MAX

    # Corrupt only the temperature field; detection bytes (name, mfr_id key
    # for 18/17-byte models, IAM-T2 MAC prefix) stay intact.
    if temp_slice is None:
        corrupt_info = _boundary_service_info(name, 0xFFFF, payload)
    else:
        corrupt_payload = bytearray(payload)
        corrupt_payload[temp_slice] = b"\xff\xff"
        corrupt_info = _boundary_service_info(name, mfr_id, bytes(corrupt_payload))

    corrupt = INKBIRDBluetoothDeviceData()
    corrupt_result = corrupt.update(corrupt_info)
    assert corrupt.device_type is model
    corrupt_temp = corrupt_result.entity_values.get(_TEMPERATURE_KEY)
    # A model is free to drop the whole packet on a corrupt temperature; but
    # if it publishes one, it must be in a sane range. The unsigned-parse
    # regression we are guarding against would land at ~6553 C.
    if corrupt_temp is not None:
        assert abs(corrupt_temp.native_value) <= _PLAUSIBLE_TEMP_CELSIUS_MAX, (
            f"{model.name}: corrupt 0xFFFF temperature decoded as "
            f"{corrupt_temp.native_value} C — unsigned-parse regression"
        )


def test_adv_temperature_boundary_covers_every_sensor_model() -> None:
    """Every advertisement sensor model must declare a corrupt-temperature case.

    Mirrors the humidity meta-test: forces a future device parser added to
    ``SENSOR_MODELS`` to also declare its temperature boundary, so the
    unsigned-temperature bug family (#155/#188/#193) cannot silently regrow.
    """
    assert set(_ADV_TEMPERATURE_BOUNDARY_CASES) == SENSOR_MODELS
