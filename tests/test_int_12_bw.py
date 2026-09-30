"""Tests for the INT-12-BW advertisement decoder.

The payloads are real captures from an INT-12-BW base (firmware as shipped in
2026), taken with probes docked, in warm water indoors and outdoors, and checked
against the readings on the base's display.
"""

from __future__ import annotations

import pytest
from bleak.backends.device import BLEDevice
from bluetooth_data_tools import monotonic_time_coarse
from habluetooth import BluetoothServiceInfoBleak
from sensor_state_data import DeviceKey

from inkbird_ble.parser import (
    INT_12_BW_MESSAGE_LENGTH,
    INKBIRDBluetoothDeviceData,
    Model,
)

INT_12_BW_MANUFACTURER_ID = 29845
INT_12_BW_ADDRESS = "A4:C1:38:06:16:64"

# Both probes docked in the base: every temperature is the 0x7FFE marker and
# both probe battery bytes carry the docked/charging flag (0xE4 = 0x80 | 100).
DOCKED = "3a6964160638c1a4fe7ffe7f18e4fe7f19e4d964"
# Probe 1 in warm water (display 118 F), probe 2 in room air (display 72 F).
KITCHEN = "3a6964160638c1a4e001e6003564dc0019648864"
# Outdoors: probe 1 cooling in water (display 111 F), probe 1 ambient on the
# display's right-hand field (81 F), probe 2 in outdoor air (display 64 F).
BBQ = "3a6964160638c1a4c2010e013264be0016648864"


def _service_info(
    payload_hex: str, name: str = "INT-12-BW"
) -> BluetoothServiceInfoBleak:
    return BluetoothServiceInfoBleak(
        name=name,
        manufacturer_data={INT_12_BW_MANUFACTURER_ID: bytes.fromhex(payload_hex)},
        service_uuids=["0000ff00-0000-1000-8000-00805f9b34fb"],
        address=INT_12_BW_ADDRESS,
        rssi=-39,
        service_data={},
        source="local",
        device=BLEDevice(name=name, address=INT_12_BW_ADDRESS, details={}),
        time=monotonic_time_coarse(),
        advertisement=None,
        connectable=True,
        tx_power=0,
        raw=None,
    )


def _values(
    parser: INKBIRDBluetoothDeviceData, payload_hex: str
) -> dict[str, float | None]:
    result = parser.update(_service_info(payload_hex))
    return {k.key: v.native_value for k, v in result.entity_values.items()}


def test_int_12_bw_detected_by_name() -> None:
    parser = INKBIRDBluetoothDeviceData()
    result = parser.update(_service_info(KITCHEN))
    assert parser.device_type is Model.INT_12_BW
    assert result.devices[None].name == "INT-12-BW 1664"
    assert result.devices[None].manufacturer == "INKBIRD"


def test_int_12_bw_kitchen_capture() -> None:
    values = _values(INKBIRDBluetoothDeviceData(), KITCHEN)
    assert values == {
        "temperature_probe_1": 48.0,
        "temperature_probe_1_ambient": 23.0,
        "temperature_probe_2": 22.0,
        "probe_1_battery": 100,
        "probe_2_battery": 100,
        "battery": 100,
        "signal_strength": -39,
    }


def test_int_12_bw_bbq_capture() -> None:
    values = _values(INKBIRDBluetoothDeviceData(), BBQ)
    assert values["temperature_probe_1"] == 45.0
    assert values["temperature_probe_1_ambient"] == 27.0
    assert values["temperature_probe_2"] == 19.0


def test_int_12_bw_probe_2_has_no_ambient() -> None:
    values = _values(INKBIRDBluetoothDeviceData(), KITCHEN)
    assert "temperature_probe_2_ambient" not in values


def test_int_12_bw_docked_probes_clear_temperatures() -> None:
    """Docked probes report the invalid marker; batteries mask off the flag."""
    values = _values(INKBIRDBluetoothDeviceData(), DOCKED)
    assert values["temperature_probe_1"] is None
    assert values["temperature_probe_1_ambient"] is None
    assert values["temperature_probe_2"] is None
    assert values["probe_1_battery"] == 100
    assert values["probe_2_battery"] == 100
    assert values["battery"] == 100


def test_int_12_bw_docking_clears_previous_reading() -> None:
    parser = INKBIRDBluetoothDeviceData()
    assert _values(parser, KITCHEN)["temperature_probe_1"] == 48.0
    assert _values(parser, DOCKED)["temperature_probe_1"] is None


@pytest.mark.parametrize(
    "marker",
    ["fe7f", "ff7f", "0080"],
    ids=["error", "over_range", "under_range"],
)
def test_int_12_bw_invalid_markers_are_none(marker: str) -> None:
    payload = bytearray.fromhex(KITCHEN)
    payload[14:16] = bytes.fromhex(marker)  # probe 2 tip
    values = _values(INKBIRDBluetoothDeviceData(), payload.hex())
    assert values["temperature_probe_2"] is None
    assert values["temperature_probe_1"] == 48.0


def test_int_12_bw_negative_temperature() -> None:
    payload = bytearray.fromhex(KITCHEN)
    payload[8:10] = (-55).to_bytes(2, "little", signed=True)  # probe 1 tip
    values = _values(INKBIRDBluetoothDeviceData(), payload.hex())
    assert values["temperature_probe_1"] == -5.5


def test_int_12_bw_never_polls() -> None:
    parser = INKBIRDBluetoothDeviceData()
    service_info = _service_info(KITCHEN)
    parser.update(service_info)
    assert not parser.poll_needed(service_info, None)


@pytest.mark.parametrize(
    "payload_hex",
    [
        KITCHEN[:-2],  # one byte short
        KITCHEN + "00",  # one byte long
        KITCHEN[:-2] + "ff",  # base battery 255 %
        KITCHEN[:26] + "7f" + KITCHEN[28:],  # probe 1 battery 127 %
        KITCHEN[:34] + "ff" + KITCHEN[36:],  # probe 2 battery 127 % (flag set)
    ],
    ids=[
        "short",
        "long",
        "implausible_base_battery",
        "implausible_probe_1_battery",
        "implausible_probe_2_battery",
    ],
)
def test_int_12_bw_corrupt_advertisement_dropped(payload_hex: str) -> None:
    """A corrupt INT-12-BW advertisement emits no readings."""
    parser = INKBIRDBluetoothDeviceData(Model.INT_12_BW)
    result = parser.update(_service_info(payload_hex))
    assert set(result.entity_values) == {
        DeviceKey(key="signal_strength", device_id=None)
    }


def test_int_12_bw_length_guard_uses_decoded_entry() -> None:
    """A short changed entry is dropped even when the full data length matches."""
    parser = INKBIRDBluetoothDeviceData(Model.INT_12_BW)
    full = INT_12_BW_MANUFACTURER_ID.to_bytes(2, "little") + bytes.fromhex(KITCHEN)
    assert len(full) == INT_12_BW_MESSAGE_LENGTH
    parser._update_int_12_bw(full[:-1], INT_12_BW_MESSAGE_LENGTH)  # noqa: SLF001
    assert not parser._sensor_values  # noqa: SLF001


def test_int_12_bw_lookalike_name_not_matched() -> None:
    parser = INKBIRDBluetoothDeviceData()
    parser.update(_service_info(KITCHEN, name="INT-12I-BW"))
    assert parser.device_type is not Model.INT_12_BW
