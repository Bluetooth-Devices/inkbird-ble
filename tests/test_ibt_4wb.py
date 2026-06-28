"""Tests for the INKBIRD IBT-4WB 4-probe BBQ thermometer parser."""

from __future__ import annotations

import asyncio
import struct
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from bleak.backends.device import BLEDevice
from bleak.exc import BleakError
from bluetooth_data_tools import monotonic_time_coarse
from habluetooth import BluetoothServiceInfoBleak
from sensor_state_data import DeviceKey

from inkbird_ble.parser import (
    IBT_4WB_CMD_STATE_SYNC,
    IBT_4WB_DATA_LENGTH,
    IBT_4WB_NO_PROBE,
    IBT_4WB_WRITE_UUID,
    INKBIRDBluetoothDeviceData,
    Model,
)

if TYPE_CHECKING:
    from uuid import UUID

    from bluetooth_sensor_state_data import SensorUpdate


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

IBT_4WB_ADDRESS = "40:79:12:1A:B4:56"
IBT_4WB_SHORT_ADDRESS = "B456"
IBT_4WB_NAME = "Inkbird@IBT-24SPH"


def make_ibt_4wb_service_info(
    rssi: int = -60,
    manufacturer_data: dict[int, bytes] | None = None,
) -> BluetoothServiceInfoBleak:
    """Return a BluetoothServiceInfoBleak for the IBT-4WB."""
    return BluetoothServiceInfoBleak(
        name=IBT_4WB_NAME,
        manufacturer_data=manufacturer_data or {},
        service_uuids=["0000ff00-0000-1000-8000-00805f9b34fb"],
        address=IBT_4WB_ADDRESS,
        rssi=rssi,
        service_data={},
        source="local",
        device=BLEDevice(
            name=IBT_4WB_NAME,
            address=IBT_4WB_ADDRESS,
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
    """Build a 10-byte IBT-4WB notification payload.

    Each argument is the temperature in Fahrenheit * 10 (signed int16), or
    None to encode the no-probe sentinel (0x7FFE).
    """
    no_probe = IBT_4WB_NO_PROBE  # 0x7FFE

    def encode(val: int | None) -> bytes:
        if val is None:
            return struct.pack("<H", no_probe)
        return struct.pack("<h", val)

    return (
        encode(probe1_f10)
        + encode(probe2_f10)
        + encode(probe3_f10)
        + encode(probe4_f10)
        + b"\x00\x00"
    )


def f_to_c(fahrenheit_x10: int) -> float:
    """Convert Fahrenheit*10 raw int to rounded Celsius (1 decimal)."""
    return round((fahrenheit_x10 / 10.0 - 32) * 5 / 9, 1)


# ---------------------------------------------------------------------------
# Detection tests
# ---------------------------------------------------------------------------


def test_ibt_4wb_supported_from_local_name() -> None:
    """IBT-4WB is detected from the 'Inkbird@IBT-*' local name prefix."""
    parser = INKBIRDBluetoothDeviceData()
    service_info = make_ibt_4wb_service_info()
    assert parser.supported(service_info) is True
    assert parser.device_type == Model.IBT_4WB


def test_ibt_4wb_uses_notify() -> None:
    """IBT-4WB should be flagged as a notify-based device."""
    parser = INKBIRDBluetoothDeviceData(Model.IBT_4WB)
    assert parser.uses_notify is True


def test_ibt_4wb_does_not_need_poll() -> None:
    """Notify-based IBT-4WB never requests polling."""
    parser = INKBIRDBluetoothDeviceData()
    service_info = make_ibt_4wb_service_info()
    parser.update(service_info)
    assert parser.poll_needed(service_info, None) is False


# ---------------------------------------------------------------------------
# Temperature conversion tests
# ---------------------------------------------------------------------------


def test_temperature_conversion_typical() -> None:
    """68 °F -> 20.0 °C; 75 °F -> 23.9 °C."""
    assert f_to_c(680) == 20.0
    assert f_to_c(750) == 23.9


def test_temperature_conversion_boiling() -> None:
    """212 °F -> 100.0 °C."""
    assert f_to_c(2120) == 100.0


def test_temperature_conversion_freezing() -> None:
    """32 °F -> 0.0 °C."""
    assert f_to_c(320) == 0.0


# ---------------------------------------------------------------------------
# Notification callback tests (synchronous, no BLE connection required)
# ---------------------------------------------------------------------------


def test_ibt_4wb_notify_two_probes_active() -> None:
    """Notification with 2 active probes and 2 absent probes fires correct update."""
    last_update: SensorUpdate | None = None

    def _update_cb(update: SensorUpdate) -> None:
        nonlocal last_update
        last_update = update

    def _data_cb(data: dict[str, Any]) -> None:
        pass

    parser = INKBIRDBluetoothDeviceData(Model.IBT_4WB, {}, _update_cb, _data_cb)
    service_info = make_ibt_4wb_service_info()
    parser.update(service_info)

    # Build and inject a 10-byte notification (probes 1+2 active, 3+4 absent)
    payload = make_notify_payload(
        probe1_f10=680,  # 68.0 °F = 20.0 °C
        probe2_f10=750,  # 75.0 °F = 23.9 °C
        probe3_f10=None,
        probe4_f10=None,
    )
    assert len(payload) == IBT_4WB_DATA_LENGTH

    parser._notify_callback(MagicMock(), bytearray(payload))  # noqa: SLF001

    assert last_update is not None
    values = last_update.entity_values
    assert values[DeviceKey("temperature_probe_1", None)].native_value == 20.0
    assert values[DeviceKey("temperature_probe_2", None)].native_value == 23.9
    # Absent probes are included in the update with native_value=None so that
    # HA marks them as unavailable rather than showing a stale reading.
    assert values[DeviceKey("temperature_probe_3", None)].native_value is None
    assert values[DeviceKey("temperature_probe_4", None)].native_value is None


def test_ibt_4wb_notify_all_probes_active() -> None:
    """All 4 probes active -> 4 temperature entities."""
    last_update: SensorUpdate | None = None

    def _update_cb(update: SensorUpdate) -> None:
        nonlocal last_update
        last_update = update

    parser = INKBIRDBluetoothDeviceData(Model.IBT_4WB, {}, _update_cb, MagicMock())
    service_info = make_ibt_4wb_service_info()
    parser.update(service_info)

    payload = make_notify_payload(
        probe1_f10=680,  # 20.0 °C
        probe2_f10=750,  # 23.9 °C
        probe3_f10=2120,  # 100.0 °C
        probe4_f10=320,  # 0.0 °C
    )
    parser._notify_callback(MagicMock(), bytearray(payload))  # noqa: SLF001

    assert last_update is not None
    values = last_update.entity_values
    assert values[DeviceKey("temperature_probe_1", None)].native_value == 20.0
    assert values[DeviceKey("temperature_probe_2", None)].native_value == 23.9
    assert values[DeviceKey("temperature_probe_3", None)].native_value == 100.0
    assert values[DeviceKey("temperature_probe_4", None)].native_value == 0.0


def test_ibt_4wb_notify_all_no_probe() -> None:
    """All probes absent -> every probe sensor reports native_value=None."""
    updates: list[SensorUpdate] = []

    def _update_cb(update: SensorUpdate) -> None:
        updates.append(update)

    parser = INKBIRDBluetoothDeviceData(Model.IBT_4WB, {}, _update_cb, MagicMock())
    service_info = make_ibt_4wb_service_info()
    parser.update(service_info)

    payload = make_notify_payload()  # all None -> all 0x7FFE
    parser._notify_callback(MagicMock(), bytearray(payload))  # noqa: SLF001

    assert len(updates) == 1
    values = updates[0].entity_values
    # Each absent probe is included in the update with native_value=None so
    # HA can mark it unavailable instead of holding a stale reading.
    for probe in range(1, 5):
        key = DeviceKey(f"temperature_probe_{probe}", None)
        assert values[key].native_value is None


def test_ibt_4wb_notify_wrong_length_ignored() -> None:
    """Notification payloads that are not exactly 10 bytes are silently dropped."""
    updates: list[SensorUpdate] = []

    def _update_cb(update: SensorUpdate) -> None:
        updates.append(update)

    parser = INKBIRDBluetoothDeviceData(Model.IBT_4WB, {}, _update_cb, MagicMock())
    parser._notify_callback(MagicMock(), bytearray(5))  # noqa: SLF001

    assert len(updates) == 0


def test_ibt_4wb_notify_without_update_callback_is_noop() -> None:
    """A valid notification with no ``update_callback`` set must not raise.

    The decoder guards the publish step so a parser constructed without an
    update callback (e.g. data-only usage) drops the finished update instead
    of calling ``None``.
    """
    parser = INKBIRDBluetoothDeviceData(Model.IBT_4WB, {}, None, None)
    payload = make_notify_payload(probe1_f10=680)
    # Must complete without raising despite update_callback being None.
    parser._notify_callback(MagicMock(), bytearray(payload))  # noqa: SLF001


def test_ibt_4wb_entity_names() -> None:
    """Temperature probe entities carry human-readable names."""
    last_update: SensorUpdate | None = None

    def _update_cb(update: SensorUpdate) -> None:
        nonlocal last_update
        last_update = update

    parser = INKBIRDBluetoothDeviceData(Model.IBT_4WB, {}, _update_cb, MagicMock())
    service_info = make_ibt_4wb_service_info()
    parser.update(service_info)

    payload = make_notify_payload(probe1_f10=680, probe2_f10=750)
    parser._notify_callback(MagicMock(), bytearray(payload))  # noqa: SLF001

    assert last_update is not None
    values = last_update.entity_values
    assert values[DeviceKey("temperature_probe_1", None)].name == "Temperature Probe 1"
    assert values[DeviceKey("temperature_probe_2", None)].name == "Temperature Probe 2"


# ---------------------------------------------------------------------------
# Async notify integration tests (mocked BLE connection)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ibt_4wb_async_start_notify_temperatures_and_battery() -> None:
    """async_start with mocked BLE: temperatures and battery appear in update."""
    last_update: SensorUpdate | None = None

    def _update_cb(update: SensorUpdate) -> None:
        nonlocal last_update
        last_update = update

    parser = INKBIRDBluetoothDeviceData(Model.IBT_4WB, {}, _update_cb, MagicMock())
    service_info = make_ibt_4wb_service_info(rssi=-44)
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
            BLEDevice(address=IBT_4WB_ADDRESS, name=IBT_4WB_NAME, details={}),
        )
        await asyncio.sleep(0)
        await parser.async_stop()

    assert last_update is not None
    values = last_update.entity_values
    assert values[DeviceKey("temperature_probe_1", None)].native_value == 20.0
    assert values[DeviceKey("temperature_probe_2", None)].native_value == 23.9
    assert values[DeviceKey("battery", None)].native_value == 57


@pytest.mark.asyncio
async def test_ibt_4wb_battery_read_failure_is_silent() -> None:
    """BleakError on battery read does not crash and temperatures still arrive."""
    last_update: SensorUpdate | None = None

    def _update_cb(update: SensorUpdate) -> None:
        nonlocal last_update
        last_update = update

    parser = INKBIRDBluetoothDeviceData(Model.IBT_4WB, {}, _update_cb, MagicMock())
    service_info = make_ibt_4wb_service_info()
    parser.update(service_info)

    payload = make_notify_payload(probe1_f10=680)
    disconnect_mock = AsyncMock()
    read_gatt_char_mock = AsyncMock(side_effect=BleakError("characteristic not found"))
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
            BLEDevice(address=IBT_4WB_ADDRESS, name=IBT_4WB_NAME, details={}),
        )
        await asyncio.sleep(0)
        await parser.async_stop()

    assert last_update is not None
    values = last_update.entity_values
    assert values[DeviceKey("temperature_probe_1", None)].native_value == 20.0
    assert DeviceKey("battery", None) not in values


@pytest.mark.asyncio
async def test_ibt_4wb_keepalive_writes_ff02() -> None:
    """Keepalive writes go to FF02 with the correct payload."""
    parser = INKBIRDBluetoothDeviceData(Model.IBT_4WB, {}, MagicMock(), MagicMock())
    service_info = make_ibt_4wb_service_info()
    parser.update(service_info)

    payload = make_notify_payload(probe1_f10=680)
    disconnect_mock = AsyncMock()
    read_gatt_char_mock = AsyncMock(return_value=b"\x39")
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
            BLEDevice(address=IBT_4WB_ADDRESS, name=IBT_4WB_NAME, details={}),
        )
        # Two yields: first lets the notify task run and create the keepalive task;
        # second lets the keepalive task execute its initial write before sleeping.
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        await parser.async_stop()

    # At least one keepalive write should have been issued to FF02
    assert write_gatt_char_mock.call_count >= 1
    call_args = write_gatt_char_mock.call_args_list[0]
    assert call_args.args[0] == IBT_4WB_WRITE_UUID
    assert call_args.args[1] == IBT_4WB_CMD_STATE_SYNC


@pytest.mark.asyncio
async def test_ibt_4wb_keepalive_failure_is_silent() -> None:
    """BleakError on keepalive write is logged and the loop exits cleanly."""
    parser = INKBIRDBluetoothDeviceData(Model.IBT_4WB, {}, MagicMock(), MagicMock())
    service_info = make_ibt_4wb_service_info()
    parser.update(service_info)

    payload = make_notify_payload(probe1_f10=680)
    disconnect_mock = AsyncMock()
    read_gatt_char_mock = AsyncMock(return_value=b"\x39")
    write_gatt_char_mock = AsyncMock(side_effect=BleakError("disconnected"))

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
            BLEDevice(address=IBT_4WB_ADDRESS, name=IBT_4WB_NAME, details={}),
        )
        # First yield lets the notify task run and schedule the keepalive task;
        # second yield lets the keepalive task execute and hit the BleakError.
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        await parser.async_stop()

    # Keepalive failure should not raise -- just exit the loop.


@pytest.mark.asyncio
async def test_ibt_4wb_retries_on_start_notify_error() -> None:
    """When start_notify raises BleakError, async_connect_action retries once.

    The retry happens within the same task iteration (no 5-second sleep) because
    async_connect_action loops up to two times internally.
    """
    last_update: SensorUpdate | None = None

    def _update_cb(update: SensorUpdate) -> None:
        nonlocal last_update
        last_update = update

    parser = INKBIRDBluetoothDeviceData(Model.IBT_4WB, {}, _update_cb, MagicMock())
    service_info = make_ibt_4wb_service_info()
    parser.update(service_info)

    payload = make_notify_payload(probe1_f10=680)
    start_notify_calls = 0

    async def start_notify_mock(uuid: UUID, callback: Any) -> None:
        nonlocal start_notify_calls
        start_notify_calls += 1
        if start_notify_calls == 1:
            msg = "service discovery failed"
            raise BleakError(msg)
        callback(uuid, bytearray(payload))

    mock_client = MagicMock(
        start_notify=start_notify_mock,
        disconnect=AsyncMock(),
        read_gatt_char=AsyncMock(return_value=b"\x39"),
        write_gatt_char=AsyncMock(),
    )

    with patch("inkbird_ble.parser.establish_connection", return_value=mock_client):
        await parser.async_start(
            service_info,
            BLEDevice(address=IBT_4WB_ADDRESS, name=IBT_4WB_NAME, details={}),
        )
        await asyncio.sleep(0)
        await parser.async_stop()

    # Both attempts happened; the second one delivered temperature data.
    assert start_notify_calls >= 2
    assert last_update is not None
    values = last_update.entity_values
    assert values[DeviceKey("temperature_probe_1", None)].native_value == 20.0


@pytest.mark.asyncio
async def test_ibt_4wb_client_set_and_cleared() -> None:
    """_ibt_4wb_client is stored while connected and cleared in the finally block."""
    parser = INKBIRDBluetoothDeviceData(Model.IBT_4WB, {}, MagicMock(), MagicMock())
    service_info = make_ibt_4wb_service_info()
    parser.update(service_info)

    payload = make_notify_payload(probe1_f10=680)

    async def start_notify_mock(uuid: UUID, callback: Any) -> None:
        callback(uuid, bytearray(payload))

    mock_client = MagicMock(
        start_notify=start_notify_mock,
        disconnect=AsyncMock(),
        read_gatt_char=AsyncMock(return_value=b"\x39"),
        write_gatt_char=AsyncMock(),
    )

    with patch("inkbird_ble.parser.establish_connection", return_value=mock_client):
        await parser.async_start(
            service_info,
            BLEDevice(address=IBT_4WB_ADDRESS, name=IBT_4WB_NAME, details={}),
        )
        await asyncio.sleep(0)
        # Client is stored while the keepalive loop is running.
        client_ref = parser._ibt_4wb_client  # noqa: SLF001
        assert client_ref is not None
        await parser.async_stop()
        # Client reference is cleared in the finally block after disconnect.
        assert parser._ibt_4wb_client is None  # noqa: SLF001


# ---------------------------------------------------------------------------
# Write method tests
# ---------------------------------------------------------------------------


def _make_write_client() -> MagicMock:
    """Return a mock BLE client suitable for write-command tests."""
    return MagicMock(
        write_gatt_char=AsyncMock(),
        disconnect=AsyncMock(),
        clear_cache=AsyncMock(),
    )


def _ble_device() -> BLEDevice:
    return BLEDevice(address=IBT_4WB_ADDRESS, name=IBT_4WB_NAME, details={})


@pytest.mark.asyncio
async def test_write_reuses_active_keepalive_client() -> None:
    """_async_ibt_4wb_write uses _ibt_4wb_client directly when it is connected.

    This avoids the ``org.bluez.Error.InProgress`` error that occurs when a
    second connection is opened while the keepalive loop already holds the link.
    """
    parser = INKBIRDBluetoothDeviceData(Model.IBT_4WB)
    mock_client = MagicMock(
        is_connected=True,
        write_gatt_char=AsyncMock(),
    )
    parser._ibt_4wb_client = mock_client  # noqa: SLF001

    with patch("inkbird_ble.parser.establish_connection") as mock_establish:
        await parser.async_ibt_4wb_set_sound_enabled(_ble_device(), enabled=True)
        # establish_connection must NOT have been called -- reused existing client.
        mock_establish.assert_not_called()

    # The command and the state-sync were written on the existing client.
    assert mock_client.write_gatt_char.call_count == 2
    cmd_write, sync_write = mock_client.write_gatt_char.call_args_list
    assert cmd_write.args[1] == b"\x0b\x5a\x00\x00\x00\x00\x00"  # SOUND_ON
    assert sync_write.args[1] == IBT_4WB_CMD_STATE_SYNC


@pytest.mark.asyncio
async def test_set_temperature_unit_celsius() -> None:
    """async_ibt_4wb_set_temperature_unit(True) writes the degrees-C command."""
    parser = INKBIRDBluetoothDeviceData(Model.IBT_4WB)
    mock_client = _make_write_client()
    with patch("inkbird_ble.parser.establish_connection", return_value=mock_client):
        await parser.async_ibt_4wb_set_temperature_unit(_ble_device(), celsius=True)

    first_write = mock_client.write_gatt_char.call_args_list[0]
    assert first_write.args[1] == b"\x03\x43\x00\x00\x00\x00\x00"


@pytest.mark.asyncio
async def test_set_temperature_unit_fahrenheit() -> None:
    """async_ibt_4wb_set_temperature_unit(False) writes the degrees-F command."""
    parser = INKBIRDBluetoothDeviceData(Model.IBT_4WB)
    mock_client = _make_write_client()
    with patch("inkbird_ble.parser.establish_connection", return_value=mock_client):
        await parser.async_ibt_4wb_set_temperature_unit(_ble_device(), celsius=False)

    first_write = mock_client.write_gatt_char.call_args_list[0]
    assert first_write.args[1] == b"\x03\x46\x00\x00\x00\x00\x00"


@pytest.mark.asyncio
async def test_set_sound_enabled() -> None:
    """Sound-on command byte sequence matches captured traffic."""
    parser = INKBIRDBluetoothDeviceData(Model.IBT_4WB)
    mock_client = _make_write_client()
    with patch("inkbird_ble.parser.establish_connection", return_value=mock_client):
        await parser.async_ibt_4wb_set_sound_enabled(_ble_device(), enabled=True)

    first_write = mock_client.write_gatt_char.call_args_list[0]
    assert first_write.args[1] == b"\x0b\x5a\x00\x00\x00\x00\x00"


@pytest.mark.asyncio
async def test_set_sound_disabled() -> None:
    """Mute command byte sequence matches captured traffic."""
    parser = INKBIRDBluetoothDeviceData(Model.IBT_4WB)
    mock_client = _make_write_client()
    with patch("inkbird_ble.parser.establish_connection", return_value=mock_client):
        await parser.async_ibt_4wb_set_sound_enabled(_ble_device(), enabled=False)

    first_write = mock_client.write_gatt_char.call_args_list[0]
    assert first_write.args[1] == b"\x0b\x11\x00\x00\x00\x00\x00"


@pytest.mark.asyncio
async def test_set_brightness_100() -> None:
    """100 percent brightness gives byte 1 = 0x64."""
    parser = INKBIRDBluetoothDeviceData(Model.IBT_4WB)
    mock_client = _make_write_client()
    with patch("inkbird_ble.parser.establish_connection", return_value=mock_client):
        await parser.async_ibt_4wb_set_brightness(_ble_device(), 100)

    first_write = mock_client.write_gatt_char.call_args_list[0]
    assert first_write.args[1] == b"\x05\x64\x00\x00\x00\x00\x00"


@pytest.mark.asyncio
async def test_set_brightness_clamps_low() -> None:
    """Values below 0 are clamped to 0."""
    parser = INKBIRDBluetoothDeviceData(Model.IBT_4WB)
    mock_client = _make_write_client()
    with patch("inkbird_ble.parser.establish_connection", return_value=mock_client):
        await parser.async_ibt_4wb_set_brightness(_ble_device(), -10)
    first_write = mock_client.write_gatt_char.call_args_list[0]
    assert first_write.args[1][1] == 0


@pytest.mark.asyncio
async def test_set_brightness_clamps_high() -> None:
    """Values above 100 are clamped to 100."""
    parser = INKBIRDBluetoothDeviceData(Model.IBT_4WB)
    mock_client = _make_write_client()
    with patch("inkbird_ble.parser.establish_connection", return_value=mock_client):
        await parser.async_ibt_4wb_set_brightness(_ble_device(), 200)
    first_write = mock_client.write_gatt_char.call_args_list[0]
    assert first_write.args[1][1] == 100


@pytest.mark.asyncio
async def test_write_always_sends_state_sync() -> None:
    """Every write command is followed by the state-sync packet."""
    parser = INKBIRDBluetoothDeviceData(Model.IBT_4WB)
    mock_client = _make_write_client()
    with patch("inkbird_ble.parser.establish_connection", return_value=mock_client):
        await parser.async_ibt_4wb_set_sound_enabled(_ble_device(), enabled=True)

    assert mock_client.write_gatt_char.call_count == 2
    second_write = mock_client.write_gatt_char.call_args_list[1]
    assert second_write.args[1] == IBT_4WB_CMD_STATE_SYNC


@pytest.mark.asyncio
async def test_calibration_probe1_minus_0_1c() -> None:
    """Minus 0.1 C calibration on probe 1: int(-0.1*9/5*10) = -1 = 0xFF."""
    parser = INKBIRDBluetoothDeviceData(Model.IBT_4WB)
    mock_client = _make_write_client()
    with patch("inkbird_ble.parser.establish_connection", return_value=mock_client):
        await parser.async_ibt_4wb_set_calibration(_ble_device(), {1: -0.1})

    cmd = mock_client.write_gatt_char.call_args_list[0].args[1]
    assert cmd[0] == 0x09  # calibration command
    assert cmd[1] == 0x01  # probe 1 bitmask
    assert cmd[2] == 0xFF  # -1 as unsigned byte
    assert cmd[3] == cmd[4] == cmd[5] == 0x00


@pytest.mark.asyncio
async def test_calibration_probe2_plus_0_1c() -> None:
    """Plus 0.1 C calibration on probe 2: int(+0.1*9/5*10) = +1 = 0x01."""
    parser = INKBIRDBluetoothDeviceData(Model.IBT_4WB)
    mock_client = _make_write_client()
    with patch("inkbird_ble.parser.establish_connection", return_value=mock_client):
        await parser.async_ibt_4wb_set_calibration(_ble_device(), {2: 0.1})

    cmd = mock_client.write_gatt_char.call_args_list[0].args[1]
    assert cmd[1] == 0x02  # probe 2 bitmask
    assert cmd[3] == 0x01  # +1


@pytest.mark.asyncio
async def test_calibration_probe4_plus_1c() -> None:
    """Plus 1 C calibration on probe 4: int(+1*9/5*10) = +18 = 0x12."""
    parser = INKBIRDBluetoothDeviceData(Model.IBT_4WB)
    mock_client = _make_write_client()
    with patch("inkbird_ble.parser.establish_connection", return_value=mock_client):
        await parser.async_ibt_4wb_set_calibration(_ble_device(), {4: 1.0})

    cmd = mock_client.write_gatt_char.call_args_list[0].args[1]
    assert cmd[1] == 0x08  # probe 4 bitmask
    assert cmd[5] == 0x12  # +18


@pytest.mark.asyncio
async def test_calibration_probe4_minus_1c() -> None:
    """Minus 1 C: int(-18) = -18 = 0xEE."""
    parser = INKBIRDBluetoothDeviceData(Model.IBT_4WB)
    mock_client = _make_write_client()
    with patch("inkbird_ble.parser.establish_connection", return_value=mock_client):
        await parser.async_ibt_4wb_set_calibration(_ble_device(), {4: -1.0})

    cmd = mock_client.write_gatt_char.call_args_list[0].args[1]
    assert cmd[5] == 0xEE  # -18 as unsigned byte


@pytest.mark.asyncio
async def test_calibration_probe3_minus_0_2c() -> None:
    """Minus 0.2 C: int(-3.6) = -3 = 0xFD (matches captured traffic)."""
    parser = INKBIRDBluetoothDeviceData(Model.IBT_4WB)
    mock_client = _make_write_client()
    with patch("inkbird_ble.parser.establish_connection", return_value=mock_client):
        await parser.async_ibt_4wb_set_calibration(_ble_device(), {3: -0.2})

    cmd = mock_client.write_gatt_char.call_args_list[0].args[1]
    assert cmd[1] == 0x04  # probe 3 bitmask
    assert cmd[4] == 0xFD  # -3 as unsigned byte


@pytest.mark.asyncio
async def test_calibration_multi_probe() -> None:
    """Setting probes 1 and 3 together produces the combined bitmask."""
    parser = INKBIRDBluetoothDeviceData(Model.IBT_4WB)
    mock_client = _make_write_client()
    with patch("inkbird_ble.parser.establish_connection", return_value=mock_client):
        await parser.async_ibt_4wb_set_calibration(_ble_device(), {1: 0.0, 3: 0.0})

    cmd = mock_client.write_gatt_char.call_args_list[0].args[1]
    assert cmd[1] == 0x05  # 0x01 | 0x04


def test_calibration_invalid_probe_raises() -> None:
    """Probe numbers outside 1-4 raise ValueError immediately."""
    parser = INKBIRDBluetoothDeviceData(Model.IBT_4WB)
    with pytest.raises(ValueError, match="probe_num"):
        asyncio.run(parser.async_ibt_4wb_set_calibration(_ble_device(), {5: 0.0}))


def test_calibration_out_of_range_raises() -> None:
    """Offsets outside ±5.0 °C raise ValueError."""
    parser = INKBIRDBluetoothDeviceData(Model.IBT_4WB)
    with pytest.raises(ValueError, match="offset_c must be in"):
        asyncio.run(parser.async_ibt_4wb_set_calibration(_ble_device(), {1: 5.1}))
    with pytest.raises(ValueError, match="offset_c must be in"):
        asyncio.run(parser.async_ibt_4wb_set_calibration(_ble_device(), {1: -5.1}))


@pytest.mark.asyncio
async def test_calibration_empty_dict_is_noop() -> None:
    """An empty offsets dict returns without writing anything."""
    parser = INKBIRDBluetoothDeviceData(Model.IBT_4WB)
    with patch("inkbird_ble.parser.establish_connection") as mock_establish:
        await parser.async_ibt_4wb_set_calibration(_ble_device(), {})
        mock_establish.assert_not_called()


# ---------------------------------------------------------------------------
# Edge-case / branch-coverage tests
# ---------------------------------------------------------------------------


def test_notify_callback_ignored_when_not_running() -> None:
    """_notify_callback returns immediately when _running is False (line 544-545)."""
    parser = INKBIRDBluetoothDeviceData(Model.IBT_4WB, {}, MagicMock(), MagicMock())
    # _running starts True in __init__; simulate async_stop() having been called.
    parser._running = False  # noqa: SLF001
    sender = MagicMock()
    payload = bytearray(make_notify_payload(probe1_f10=680))
    # Should silently return without calling _update_ibt_4wb_notify.
    parser._notify_callback(sender, payload)  # noqa: SLF001


def test_notify_callback_ignored_for_unknown_device_type() -> None:
    """_notify_callback returns early for non-IBT_4WB, non-IAM_T1 device types.

    Constructs a parser with a model that is neither IBT_4WB nor IAM_T1 and
    injects a direct call to the callback so the ``device_type != IAM_T1``
    guard branch is exercised.
    """
    # IBS_TH uses passive advertisement data, not notifications; calling
    # _notify_callback directly exercises the ``device_type != IAM_T1`` return.
    parser = INKBIRDBluetoothDeviceData(Model.IBS_TH, {}, MagicMock(), MagicMock())
    sender = MagicMock()
    # Any data is fine — should return before any processing.
    parser._notify_callback(sender, bytearray(10))  # noqa: SLF001


@pytest.mark.asyncio
async def test_ibt_4wb_battery_read_empty_skips_sensor() -> None:
    """Battery sensor is skipped when read_gatt_char returns empty bytes.

    Covers the ``if bat_data:`` FALSE path so the notification subscription
    still proceeds even when the battery characteristic returns no data.
    """
    last_update: SensorUpdate | None = None

    def _cb(update: SensorUpdate) -> None:
        nonlocal last_update
        last_update = update

    parser = INKBIRDBluetoothDeviceData(Model.IBT_4WB, {}, _cb, MagicMock())
    service_info = make_ibt_4wb_service_info()
    parser.update(service_info)

    payload = make_notify_payload(probe1_f10=680)

    async def start_notify_mock(uuid: UUID, callback: Any) -> None:
        callback(uuid, bytearray(payload))

    mock_client = MagicMock(
        start_notify=start_notify_mock,
        disconnect=AsyncMock(),
        # Return empty bytes -> battery sensor must not be updated.
        read_gatt_char=AsyncMock(return_value=b""),
        write_gatt_char=AsyncMock(),
    )

    with patch("inkbird_ble.parser.establish_connection", return_value=mock_client):
        await parser.async_start(
            service_info,
            BLEDevice(address=IBT_4WB_ADDRESS, name=IBT_4WB_NAME, details={}),
        )
        await asyncio.sleep(0)
        await parser.async_stop()

    assert last_update is not None
    # Temperature probe 1 should be present; battery must NOT be present.
    assert DeviceKey("temperature_probe_1", None) in last_update.entity_values
    assert DeviceKey("battery", None) not in last_update.entity_values
