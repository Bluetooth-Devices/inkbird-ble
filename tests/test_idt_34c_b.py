"""Tests for the INKBIRD IDT-34c-B 4-probe BBQ thermometer parser.

The IDT-34c-B is a GATT-notify sibling of the IBT-4WB: it advertises only a
local name (no manufacturer data) and streams four signed-int16 little-endian
probe temperatures in Fahrenheit*10 on ``ff01``, with ``0x7FFE`` marking an
unplugged probe. It therefore reuses the IBT-4WB notify decode and connection
flow; these tests exercise detection from its distinct local name and the
shared decode path under the ``IDT_34C_B`` model. See
https://github.com/Bluetooth-Devices/inkbird-ble/issues/230
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
    IBT_4WB_DATA_LENGTH,
    IBT_4WB_NO_PROBE,
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


def make_notify_payload(
    probe1_f10: int | None = None,
    probe2_f10: int | None = None,
    probe3_f10: int | None = None,
    probe4_f10: int | None = None,
) -> bytes:
    """Build a 10-byte notification payload.

    Each argument is the temperature in Fahrenheit * 10 (signed int16), or
    None to encode the no-probe sentinel (0x7FFE).
    """

    def encode(val: int | None) -> bytes:
        if val is None:
            return struct.pack("<H", IBT_4WB_NO_PROBE)
        return struct.pack("<h", val)

    return (
        encode(probe1_f10)
        + encode(probe2_f10)
        + encode(probe3_f10)
        + encode(probe4_f10)
        + b"\x00\x00"
    )


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
# Decode tests (shared IBT-4WB protocol)
# ---------------------------------------------------------------------------


def test_idt_34c_b_notify_two_probes_active() -> None:
    """Two active probes decode to Celsius; the others report None."""
    updates: list[SensorUpdate] = []

    def _update_cb(update: SensorUpdate) -> None:
        updates.append(update)

    parser = INKBIRDBluetoothDeviceData(Model.IDT_34C_B, {}, _update_cb, MagicMock())
    parser.update(make_idt_34c_b_service_info())

    # 68.0 °F -> 20.0 °C, 212.0 °F -> 100.0 °C
    payload = make_notify_payload(probe1_f10=680, probe2_f10=2120)
    parser._notify_callback(MagicMock(), bytearray(payload))  # noqa: SLF001

    assert len(updates) == 1
    values = updates[0].entity_values
    assert values[DeviceKey("temperature_probe_1", None)].native_value == 20.0
    assert values[DeviceKey("temperature_probe_2", None)].native_value == 100.0
    assert values[DeviceKey("temperature_probe_3", None)].native_value is None
    assert values[DeviceKey("temperature_probe_4", None)].native_value is None


def test_idt_34c_b_notify_subzero_probe() -> None:
    """A sub-zero probe (signed int16) decodes to a negative Celsius value."""
    updates: list[SensorUpdate] = []

    def _update_cb(update: SensorUpdate) -> None:
        updates.append(update)

    parser = INKBIRDBluetoothDeviceData(Model.IDT_34C_B, {}, _update_cb, MagicMock())
    parser.update(make_idt_34c_b_service_info())

    # 14.0 °F -> -10.0 °C
    payload = make_notify_payload(probe1_f10=140)
    parser._notify_callback(MagicMock(), bytearray(payload))  # noqa: SLF001

    values = updates[0].entity_values
    assert values[DeviceKey("temperature_probe_1", None)].native_value == -10.0


def test_idt_34c_b_notify_all_no_probe() -> None:
    """All probes absent -> every probe sensor reports native_value=None."""
    updates: list[SensorUpdate] = []

    def _update_cb(update: SensorUpdate) -> None:
        updates.append(update)

    parser = INKBIRDBluetoothDeviceData(Model.IDT_34C_B, {}, _update_cb, MagicMock())
    parser.update(make_idt_34c_b_service_info())

    parser._notify_callback(MagicMock(), bytearray(make_notify_payload()))  # noqa: SLF001

    assert len(updates) == 1
    values = updates[0].entity_values
    for probe in range(1, 5):
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

    payload = make_notify_payload(probe1_f10=680, probe2_f10=750)
    parser._notify_callback(MagicMock(), bytearray(payload))  # noqa: SLF001

    assert last_update is not None
    values = last_update.entity_values
    assert values[DeviceKey("temperature_probe_1", None)].name == "Temperature Probe 1"
    assert values[DeviceKey("temperature_probe_2", None)].name == "Temperature Probe 2"


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

    payload = make_notify_payload(probe1_f10=680, probe2_f10=750)
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
    """Notification payloads that are not exactly 10 bytes are silently dropped."""
    updates: list[SensorUpdate] = []

    def _update_cb(update: SensorUpdate) -> None:
        updates.append(update)

    parser = INKBIRDBluetoothDeviceData(Model.IDT_34C_B, {}, _update_cb, MagicMock())
    parser._notify_callback(MagicMock(), bytearray(IBT_4WB_DATA_LENGTH - 1))  # noqa: SLF001
    assert updates == []
