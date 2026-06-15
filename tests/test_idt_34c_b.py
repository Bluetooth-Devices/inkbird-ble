"""Tests for the INKBIRD IDT-34c-B 6-probe BBQ thermometer parser.

The IDT-34c-B is a GATT-notify sibling of the IBT-4WB: it advertises only a
local name (no manufacturer data) and streams signed-int16 little-endian probe
temperatures in Fahrenheit*10 on ``ff01``, with ``0x7FFE`` marking an unplugged
probe. It shares the IBT-4WB decode formula and 0x7FFE sentinel, but it carries
SIX probes in a 13-byte frame (versus the IBT-4WB's four probes in 10 bytes).

The layout is anchored to a live ``ff01`` capture posted by a hardware owner in
https://github.com/Bluetooth-Devices/inkbird-ble/issues/230:

    6A 03 FE 7F FE 7F 87 03 FE 7F FE 7F 7F  (two probes plugged)

which decodes to probe 1 = 87.4 °F (30.8 °C), probe 4 = 90.3 °F (32.4 °C), the
remaining four probes unplugged, plus a trailing status byte.
"""

from __future__ import annotations

import asyncio
import struct
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from bleak.backends.device import BLEDevice
from bluetooth_data_tools import monotonic_time_coarse
from habluetooth import BluetoothServiceInfoBleak
from sensor_state_data import DeviceKey

from inkbird_ble.parser import (
    IBT_4WB_NO_PROBE,
    IDT_34C_B_DATA_LENGTH,
    INKBIRDBluetoothDeviceData,
    Model,
)

if TYPE_CHECKING:
    from uuid import UUID

    from bluetooth_sensor_state_data import SensorUpdate


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

IDT_34C_B_ADDRESS = "A4:C1:38:81:F1:4C"
IDT_34C_B_SHORT_ADDRESS = "F14C"
IDT_34C_B_NAME = "IDT-34c-B"

# Live ff01 capture from issue #230 (two probes plugged).
IDT_34C_B_ISSUE_230_CAPTURE = bytes.fromhex("6A03FE7FFE7F8703FE7FFE7F7F")

IDT_34C_B_PROBE_COUNT = 6


def make_idt_34c_b_service_info(
    rssi: int = -60,
    manufacturer_data: dict[int, bytes] | None = None,
) -> BluetoothServiceInfoBleak:
    """Return a BluetoothServiceInfoBleak for the IDT-34c-B."""
    return BluetoothServiceInfoBleak(
        name=IDT_34C_B_NAME,
        manufacturer_data=manufacturer_data or {},
        service_uuids=["0000ff00-0000-1000-8000-00805f9b34fb"],
        address=IDT_34C_B_ADDRESS,
        rssi=rssi,
        service_data={},
        source="local",
        device=BLEDevice(
            name=IDT_34C_B_NAME,
            address=IDT_34C_B_ADDRESS,
            details={},
        ),
        time=monotonic_time_coarse(),
        advertisement=None,
        connectable=True,
        tx_power=0,
        raw=None,
    )


def make_notify_payload(*probes_f10: int | None) -> bytes:
    """Build a 13-byte IDT-34c-B notification payload.

    Each positional argument is a probe temperature in Fahrenheit * 10 (signed
    int16), or None to encode the no-probe sentinel (0x7FFE). Up to six probes;
    omitted probes default to the sentinel. A trailing status byte completes the
    13-byte frame.
    """

    def encode(val: int | None) -> bytes:
        if val is None:
            return struct.pack("<H", IBT_4WB_NO_PROBE)
        return struct.pack("<h", val)

    values = list(probes_f10) + [None] * (IDT_34C_B_PROBE_COUNT - len(probes_f10))
    return b"".join(encode(v) for v in values[:IDT_34C_B_PROBE_COUNT]) + b"\x7f"


# ---------------------------------------------------------------------------
# Detection tests
# ---------------------------------------------------------------------------


def test_idt_34c_b_supported_from_local_name() -> None:
    """IDT-34c-B is detected from its exact local name (no manufacturer data)."""
    parser = INKBIRDBluetoothDeviceData()
    service_info = make_idt_34c_b_service_info()
    assert parser.supported(service_info) is True
    assert parser.device_type == Model.IDT_34C_B


def test_idt_34c_b_uses_notify() -> None:
    """IDT-34c-B should be flagged as a notify-based device."""
    parser = INKBIRDBluetoothDeviceData(Model.IDT_34C_B)
    assert parser.uses_notify is True


def test_idt_34c_b_does_not_need_poll() -> None:
    """Notify-based IDT-34c-B never requests polling."""
    parser = INKBIRDBluetoothDeviceData()
    service_info = make_idt_34c_b_service_info()
    parser.update(service_info)
    assert parser.poll_needed(service_info, None) is False


# ---------------------------------------------------------------------------
# Decode tests (shared IBT-4WB protocol, six probes)
# ---------------------------------------------------------------------------


def test_idt_34c_b_notify_real_capture_from_issue_230() -> None:
    """The live ff01 capture from issue #230 decodes to its known probe values."""
    updates: list[SensorUpdate] = []

    parser = INKBIRDBluetoothDeviceData(
        Model.IDT_34C_B, {}, updates.append, MagicMock()
    )
    parser.update(make_idt_34c_b_service_info())

    parser._notify_callback(  # noqa: SLF001
        MagicMock(), bytearray(IDT_34C_B_ISSUE_230_CAPTURE)
    )

    assert len(updates) == 1
    values = updates[0].entity_values
    # 87.4 °F -> 30.8 °C on probe 1, 90.3 °F -> 32.4 °C on probe 4.
    assert values[DeviceKey("temperature_probe_1", None)].native_value == 30.8
    assert values[DeviceKey("temperature_probe_2", None)].native_value is None
    assert values[DeviceKey("temperature_probe_3", None)].native_value is None
    assert values[DeviceKey("temperature_probe_4", None)].native_value == 32.4
    assert values[DeviceKey("temperature_probe_5", None)].native_value is None
    assert values[DeviceKey("temperature_probe_6", None)].native_value is None


def test_idt_34c_b_notify_two_probes_active() -> None:
    """Two active probes decode to Celsius; the other four report None."""
    updates: list[SensorUpdate] = []

    parser = INKBIRDBluetoothDeviceData(
        Model.IDT_34C_B, {}, updates.append, MagicMock()
    )
    parser.update(make_idt_34c_b_service_info())

    # 68.0 °F -> 20.0 °C, 212.0 °F -> 100.0 °C
    payload = make_notify_payload(680, 2120)
    parser._notify_callback(MagicMock(), bytearray(payload))  # noqa: SLF001

    assert len(updates) == 1
    values = updates[0].entity_values
    assert values[DeviceKey("temperature_probe_1", None)].native_value == 20.0
    assert values[DeviceKey("temperature_probe_2", None)].native_value == 100.0
    for probe in range(3, IDT_34C_B_PROBE_COUNT + 1):
        key = DeviceKey(f"temperature_probe_{probe}", None)
        assert values[key].native_value is None


def test_idt_34c_b_notify_six_probes_active() -> None:
    """All six probes decode independently."""
    updates: list[SensorUpdate] = []

    parser = INKBIRDBluetoothDeviceData(
        Model.IDT_34C_B, {}, updates.append, MagicMock()
    )
    parser.update(make_idt_34c_b_service_info())

    # 32 -> 0 °C, 50 -> 10 °C, 68 -> 20 °C, 86 -> 30 °C, 104 -> 40 °C, 122 -> 50 °C
    payload = make_notify_payload(320, 500, 680, 860, 1040, 1220)
    parser._notify_callback(MagicMock(), bytearray(payload))  # noqa: SLF001

    values = updates[0].entity_values
    expected = [0.0, 10.0, 20.0, 30.0, 40.0, 50.0]
    for idx, want in enumerate(expected, start=1):
        key = DeviceKey(f"temperature_probe_{idx}", None)
        assert values[key].native_value == want


def test_idt_34c_b_notify_subzero_probe() -> None:
    """A sub-zero probe (signed int16) decodes to a negative Celsius value."""
    updates: list[SensorUpdate] = []

    parser = INKBIRDBluetoothDeviceData(
        Model.IDT_34C_B, {}, updates.append, MagicMock()
    )
    parser.update(make_idt_34c_b_service_info())

    # 14.0 °F -> -10.0 °C
    payload = make_notify_payload(140)
    parser._notify_callback(MagicMock(), bytearray(payload))  # noqa: SLF001

    values = updates[0].entity_values
    assert values[DeviceKey("temperature_probe_1", None)].native_value == -10.0


def test_idt_34c_b_notify_all_no_probe() -> None:
    """All probes absent -> every probe sensor reports native_value=None."""
    updates: list[SensorUpdate] = []

    parser = INKBIRDBluetoothDeviceData(
        Model.IDT_34C_B, {}, updates.append, MagicMock()
    )
    parser.update(make_idt_34c_b_service_info())

    parser._notify_callback(MagicMock(), bytearray(make_notify_payload()))  # noqa: SLF001

    assert len(updates) == 1
    values = updates[0].entity_values
    for probe in range(1, IDT_34C_B_PROBE_COUNT + 1):
        key = DeviceKey(f"temperature_probe_{probe}", None)
        assert values[key].native_value is None


def test_idt_34c_b_entity_names() -> None:
    """Temperature probe entities carry human-readable names."""
    last_update: SensorUpdate | None = None

    def _update_cb(update: SensorUpdate) -> None:
        nonlocal last_update
        last_update = update

    parser = INKBIRDBluetoothDeviceData(Model.IDT_34C_B, {}, _update_cb, MagicMock())
    parser.update(make_idt_34c_b_service_info())

    payload = make_notify_payload(680, 750)
    parser._notify_callback(MagicMock(), bytearray(payload))  # noqa: SLF001

    assert last_update is not None
    values = last_update.entity_values
    assert values[DeviceKey("temperature_probe_1", None)].name == "Temperature Probe 1"
    assert values[DeviceKey("temperature_probe_6", None)].name == "Temperature Probe 6"


# ---------------------------------------------------------------------------
# Async notify integration test (mocked BLE connection)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_idt_34c_b_async_start_notify_temperatures_and_battery() -> None:
    """async_start with mocked BLE: temperatures and battery appear in update."""
    last_update: SensorUpdate | None = None

    def _update_cb(update: SensorUpdate) -> None:
        nonlocal last_update
        last_update = update

    parser = INKBIRDBluetoothDeviceData(Model.IDT_34C_B, {}, _update_cb, MagicMock())
    service_info = make_idt_34c_b_service_info(rssi=-44)
    parser.update(service_info)

    payload = make_notify_payload(680, 750)
    disconnect_mock = AsyncMock()
    read_gatt_char_mock = AsyncMock(return_value=b"\x39")  # 57 %
    write_gatt_char_mock = AsyncMock()

    async def start_notify_mock(uuid: UUID, callback: Any) -> None:
        callback(uuid, bytearray(payload))

    mock_client = MagicMock(
        start_notify=start_notify_mock,
        disconnect=disconnect_mock,
        read_gatt_char=read_gatt_char_mock,
        write_gatt_char=write_gatt_char_mock,
    )

    with patch("inkbird_ble.parser.establish_connection", return_value=mock_client):
        await parser.async_start(
            service_info,
            BLEDevice(address=IDT_34C_B_ADDRESS, name=IDT_34C_B_NAME, details={}),
        )
        await asyncio.sleep(0)
        await parser.async_stop()

    assert last_update is not None
    values = last_update.entity_values
    assert values[DeviceKey("temperature_probe_1", None)].native_value == 20.0
    assert values[DeviceKey("temperature_probe_2", None)].native_value == 23.9
    assert values[DeviceKey("battery", None)].native_value == 57


def test_idt_34c_b_wrong_length_notification_ignored() -> None:
    """Notification payloads that are not exactly 13 bytes are silently dropped."""
    updates: list[SensorUpdate] = []

    parser = INKBIRDBluetoothDeviceData(
        Model.IDT_34C_B, {}, updates.append, MagicMock()
    )
    # A 10-byte IBT-4WB-sized frame must NOT be accepted for the IDT-34c-B.
    parser._notify_callback(  # noqa: SLF001
        MagicMock(), bytearray(IDT_34C_B_DATA_LENGTH - 3)
    )
    assert updates == []
