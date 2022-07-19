"""Parser for Inkbird BLE advertisements."""
from __future__ import annotations

from bluetooth_sensor_state_data import SIGNAL_STRENGTH_KEY
from sensor_state_data import DeviceClass, DeviceKey, SensorUpdate
from sensor_state_data.data import (
    ATTR_HW_VERSION,
    ATTR_MANUFACTURER,
    ATTR_MODEL,
    ATTR_NAME,
    ATTR_SW_VERSION,
    SensorDeviceInfo,
)

from .parser import INKBIRDBluetoothDeviceData

__version__ = "0.1.0"

__all__ = [
    "INKBIRDBluetoothDeviceData",
    "SIGNAL_STRENGTH_KEY",
    "ATTR_HW_VERSION",
    "ATTR_MANUFACTURER",
    "ATTR_MODEL",
    "ATTR_NAME",
    "ATTR_SW_VERSION",
    "SIGNAL_STRENGTH_KEY",
    "SensorDeviceInfo",
    "DeviceClass",
    "DeviceKey",
    "SensorUpdate",
    "SensorDeviceInfo",
]
