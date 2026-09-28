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

from .intbw import INTBWClient
from .parser import INKBIRDBluetoothDeviceData, Model

__version__ = "1.7.1"

__all__ = [
    "DeviceClass",
    "DeviceKey",
    "INKBIRDBluetoothDeviceData",
    "INTBWClient",
    "Model",
    "SensorDescription",
    "SensorDeviceInfo",
    "SensorUpdate",
    "SensorValue",
    "Units",
]
