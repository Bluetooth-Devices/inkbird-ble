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

from .parser import (
    INKBIRDBluetoothDeviceData,
    ITH11BHistoryRecord,
    Model,
    build_ith_11_b_history_clock_command,
    decode_ith_11_b_history_records,
    parse_ith_11_b_history_interval,
)

__version__ = "1.5.2"

__all__ = [
    "DeviceClass",
    "DeviceKey",
    "INKBIRDBluetoothDeviceData",
    "ITH11BHistoryRecord",
    "Model",
    "SensorDescription",
    "SensorDeviceInfo",
    "SensorUpdate",
    "SensorValue",
    "Units",
    "build_ith_11_b_history_clock_command",
    "decode_ith_11_b_history_records",
    "parse_ith_11_b_history_interval",
]
