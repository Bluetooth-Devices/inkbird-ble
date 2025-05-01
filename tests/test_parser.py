from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
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

from inkbird_ble.parser import INKBIRDBluetoothDeviceData, Model

from . import async_fire_time_changed

if TYPE_CHECKING:
    from collections.abc import Callable
    from uuid import UUID


def test_can_create():
    parser = INKBIRDBluetoothDeviceData()
    assert parser.name == "Unknown"


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
            rssi=rssi,
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
    """Test xBBQ2 accepts 1 updates."""
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
            DeviceKey(key="temperature_probe_2", device_id=None): SensorDescription(
                device_key=DeviceKey(key="temperature_probe_2", device_id=None),
                device_class=SensorDeviceClass.TEMPERATURE,
                native_unit_of_measurement=Units.TEMP_CELSIUS,
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
            DeviceKey(key="temperature_probe_2", device_id=None): SensorValue(
                device_key=DeviceKey(key="temperature_probe_2", device_id=None),
                name="Temperature Probe 2",
                native_value=6553.5,
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
                rssi=-60,
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
                rssi=-60,
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
                rssi=-60,
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
                rssi=-60,
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
            rssi=-60,
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
                rssi=-60,
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
        callback(uuid, b"U\xaa\x01\x10\x00\x00\xfe\x01\xd6\x02\xd9\x03\xf1\x01\x00\xb5")

    mock_client = MagicMock(start_notify=start_notify_mock, disconnect=disconnect_mock)
    with patch("inkbird_ble.parser.establish_connection", return_value=mock_client):
        await parser.async_start(
            service_info,
            BLEDevice(
                address="62:00:A1:3C:AE:7B",
                name="Ink@IAM-T1",
                details={},
                rssi=-60,
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
                rssi=-60,
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
                rssi=-60,
            ),
        )
        await asyncio.sleep(0)
        assert set_disconnected_callback_mock.called
        set_disconnected_callback_mock.call_args[0][0](mock_client)
        await asyncio.sleep(0)
        assert start_notify_calls == 1
        async_fire_time_changed(datetime.utcnow() + timedelta(seconds=5))
        await asyncio.sleep(0)
        assert start_notify_calls == 2  # noqa: PLR2004
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


def test_passive_detection():
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
