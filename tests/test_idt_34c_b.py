"""Tests for IDT-34c-B GATT notify support (issue #230)."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from bleak.backends.device import BLEDevice
from bleak.exc import BleakError
from bluetooth_data_tools import monotonic_time_coarse
from habluetooth import BluetoothServiceInfoBleak

from inkbird_ble import INKBIRDBluetoothDeviceData, Model
from inkbird_ble.parser import IDT_34C_B_BATTERY_UUID

if TYPE_CHECKING:
    from collections.abc import Callable
    from uuid import UUID

    from sensor_state_data import SensorUpdate


def _service_info(name: str = "IDT-34c-B") -> BluetoothServiceInfoBleak:
    return BluetoothServiceInfoBleak(
        name=name,
        manufacturer_data={},
        service_uuids=["0000ff00-0000-1000-8000-00805f9b34fb"],
        address="A4:C1:38:81:F1:4C",
        rssi=-50,
        service_data={},
        source="local",
        device=BLEDevice(name=name, address="A4:C1:38:81:F1:4C", details={}),
        time=monotonic_time_coarse(),
        advertisement=None,
        connectable=True,
        tx_power=0,
        raw=None,
    )


def test_idt_34c_b_detected_by_name() -> None:
    """The IDT-34c-B carries no manufacturer data, so it is matched by name.

    Its advertisement only contains the local name and the ff00 service UUID;
    detection therefore happens before the manufacturer-data guard in
    ``_start_update``. The match must be case-insensitive.
    """
    parser = INKBIRDBluetoothDeviceData()
    parser.update(_service_info("IDT-34c-B"))
    assert parser.device_type is Model.IDT_34C_B
    assert parser.uses_notify is True


@pytest.mark.asyncio
async def test_notify_idt_34c_b_temperature_decode() -> None:
    """Decode the live ff01 capture from issue #230.

    Capture ``6A 03 FE 7F FE 7F 87 03 FE 7F FE 7F 7F`` (two probes plugged):

    * probe 1 = 0x036A = 874 -> 87.4 F -> 30.8 C
    * probe 4 = 0x0387 = 903 -> 90.3 F -> 32.4 C
    * probes 2/3/5/6 = 0x7FFE (unplugged) -> ``None``

    The battery is read from the standard 2a19 characteristic before the
    notification subscription, so it appears in the same update.
    """
    updates: list[SensorUpdate] = []

    def _update_callback(update: SensorUpdate) -> None:
        updates.append(update)

    parser = INKBIRDBluetoothDeviceData(Model.IDT_34C_B, {}, _update_callback, None)
    service_info = _service_info()
    parser.update(service_info)
    assert parser.uses_notify is True

    capture = bytes.fromhex("6a03fe7ffe7f8703fe7ffe7f7f")

    async def start_notify_mock(
        uuid: UUID, callback: Callable[[UUID, bytes], None]
    ) -> None:
        callback(uuid, capture)

    async def read_gatt_char_mock(uuid: UUID) -> bytes:
        assert uuid == IDT_34C_B_BATTERY_UUID
        return b"\x55"  # 85 %

    mock_client = MagicMock(
        start_notify=start_notify_mock,
        read_gatt_char=read_gatt_char_mock,
        disconnect=AsyncMock(),
    )
    with patch("inkbird_ble.parser.establish_connection", return_value=mock_client):
        await parser.async_start(
            service_info,
            BLEDevice(address="A4:C1:38:81:F1:4C", name="IDT-34c-B", details={}),
        )
        await asyncio.sleep(0)
        await parser.async_stop()

    assert updates, "expected a temperature update"
    values: dict[str, Any] = {
        key.key: value.native_value for key, value in updates[-1].entity_values.items()
    }
    assert values["temperature_probe_1"] == 30.8
    assert values["temperature_probe_2"] is None
    assert values["temperature_probe_3"] is None
    assert values["temperature_probe_4"] == 32.4
    assert values["temperature_probe_5"] is None
    assert values["temperature_probe_6"] is None
    assert values["battery"] == 85


@pytest.mark.asyncio
async def test_notify_idt_34c_b_battery_read_failure_still_emits_temps() -> None:
    """A failed battery read must not abort the temperature update."""
    updates: list[SensorUpdate] = []

    def _update_callback(update: SensorUpdate) -> None:
        updates.append(update)

    parser = INKBIRDBluetoothDeviceData(Model.IDT_34C_B, {}, _update_callback, None)
    service_info = _service_info()
    parser.update(service_info)

    capture = bytes.fromhex("6a03fe7ffe7f8703fe7ffe7f7f")

    async def start_notify_mock(
        uuid: UUID, callback: Callable[[UUID, bytes], None]
    ) -> None:
        callback(uuid, capture)

    mock_client = MagicMock(
        start_notify=start_notify_mock,
        read_gatt_char=AsyncMock(side_effect=BleakError("no battery char")),
        disconnect=AsyncMock(),
    )
    with patch("inkbird_ble.parser.establish_connection", return_value=mock_client):
        await parser.async_start(
            service_info,
            BLEDevice(address="A4:C1:38:81:F1:4C", name="IDT-34c-B", details={}),
        )
        await asyncio.sleep(0)
        await parser.async_stop()

    values: dict[str, Any] = {
        key.key: value.native_value for key, value in updates[-1].entity_values.items()
    }
    assert values["temperature_probe_1"] == 30.8
    assert "battery" not in values


@pytest.mark.asyncio
async def test_notify_idt_34c_b_battery_empty_read_omits_battery() -> None:
    """An empty 2a19 read logs and omits battery, but temps still emit."""
    updates: list[SensorUpdate] = []

    def _update_callback(update: SensorUpdate) -> None:
        updates.append(update)

    parser = INKBIRDBluetoothDeviceData(Model.IDT_34C_B, {}, _update_callback, None)
    service_info = _service_info()
    parser.update(service_info)

    capture = bytes.fromhex("6a03fe7ffe7f8703fe7ffe7f7f")

    async def start_notify_mock(
        uuid: UUID, callback: Callable[[UUID, bytes], None]
    ) -> None:
        callback(uuid, capture)

    mock_client = MagicMock(
        start_notify=start_notify_mock,
        read_gatt_char=AsyncMock(return_value=b""),
        disconnect=AsyncMock(),
    )
    with patch("inkbird_ble.parser.establish_connection", return_value=mock_client):
        await parser.async_start(
            service_info,
            BLEDevice(address="A4:C1:38:81:F1:4C", name="IDT-34c-B", details={}),
        )
        await asyncio.sleep(0)
        await parser.async_stop()

    values: dict[str, Any] = {
        key.key: value.native_value for key, value in updates[-1].entity_values.items()
    }
    assert values["temperature_probe_1"] == 30.8
    assert "battery" not in values


@pytest.mark.asyncio
async def test_notify_idt_34c_b_implausible_battery_dropped() -> None:
    """An implausible (>100%) first battery byte is dropped; temps still emit."""
    updates: list[SensorUpdate] = []

    def _update_callback(update: SensorUpdate) -> None:
        updates.append(update)

    parser = INKBIRDBluetoothDeviceData(Model.IDT_34C_B, {}, _update_callback, None)
    service_info = _service_info()
    parser.update(service_info)

    capture = bytes.fromhex("6a03fe7ffe7f8703fe7ffe7f7f")

    async def start_notify_mock(
        uuid: UUID, callback: Callable[[UUID, bytes], None]
    ) -> None:
        callback(uuid, capture)

    mock_client = MagicMock(
        start_notify=start_notify_mock,
        read_gatt_char=AsyncMock(return_value=b"\xff"),  # 255% -> implausible
        disconnect=AsyncMock(),
    )
    with patch("inkbird_ble.parser.establish_connection", return_value=mock_client):
        await parser.async_start(
            service_info,
            BLEDevice(address="A4:C1:38:81:F1:4C", name="IDT-34c-B", details={}),
        )
        await asyncio.sleep(0)
        await parser.async_stop()

    values: dict[str, Any] = {
        key.key: value.native_value for key, value in updates[-1].entity_values.items()
    }
    assert values["temperature_probe_1"] == 30.8
    assert "battery" not in values


@pytest.mark.asyncio
async def test_notify_idt_34c_b_battery_timeout_still_emits_temps() -> None:
    """A TimeoutError on the battery read must not abort the temperature update."""
    updates: list[SensorUpdate] = []

    def _update_callback(update: SensorUpdate) -> None:
        updates.append(update)

    parser = INKBIRDBluetoothDeviceData(Model.IDT_34C_B, {}, _update_callback, None)
    service_info = _service_info()
    parser.update(service_info)

    capture = bytes.fromhex("6a03fe7ffe7f8703fe7ffe7f7f")

    async def start_notify_mock(
        uuid: UUID, callback: Callable[[UUID, bytes], None]
    ) -> None:
        callback(uuid, capture)

    mock_client = MagicMock(
        start_notify=start_notify_mock,
        read_gatt_char=AsyncMock(side_effect=TimeoutError()),
        disconnect=AsyncMock(),
    )
    with patch("inkbird_ble.parser.establish_connection", return_value=mock_client):
        await parser.async_start(
            service_info,
            BLEDevice(address="A4:C1:38:81:F1:4C", name="IDT-34c-B", details={}),
        )
        await asyncio.sleep(0)
        await parser.async_stop()

    values: dict[str, Any] = {
        key.key: value.native_value for key, value in updates[-1].entity_values.items()
    }
    assert values["temperature_probe_1"] == 30.8
    assert "battery" not in values


@pytest.mark.asyncio
async def test_notify_idt_34c_b_without_update_callback() -> None:
    """A notification with no update callback set is dropped without error."""
    parser = INKBIRDBluetoothDeviceData(Model.IDT_34C_B, {})
    service_info = _service_info()
    parser.update(service_info)

    capture = bytes.fromhex("6a03fe7ffe7f8703fe7ffe7f7f")

    async def start_notify_mock(
        uuid: UUID, callback: Callable[[UUID, bytes], None]
    ) -> None:
        callback(uuid, capture)

    mock_client = MagicMock(
        start_notify=start_notify_mock,
        read_gatt_char=AsyncMock(return_value=b"\x55"),
        disconnect=AsyncMock(),
    )
    with patch("inkbird_ble.parser.establish_connection", return_value=mock_client):
        await parser.async_start(
            service_info,
            BLEDevice(address="A4:C1:38:81:F1:4C", name="IDT-34c-B", details={}),
        )
        await asyncio.sleep(0)
        await parser.async_stop()
