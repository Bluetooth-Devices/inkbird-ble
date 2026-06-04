"""Parser for Inkbird BLE advertisements."""

from __future__ import annotations

from sensor_state_data import (
    DeviceClass,
    DeviceKey,
    SensorDescription,
    SensorDeviceInfo,
    SensorUpdate,
    SensorValue,
    Units,
)

from .parser import INKBIRDBluetoothDeviceData, Model

__version__ = "1.5.2"

__all__ = [
    "DeviceClass",
    "DeviceKey",
    "INKBIRDBluetoothDeviceData",
    "Model",
    "SensorDescription",
    "SensorDeviceInfo",
    "SensorUpdate",
    "SensorValue",
    "Units",
]
