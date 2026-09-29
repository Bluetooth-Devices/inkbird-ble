"""Tests for INT-14-BW (IBT-4XS) authenticated GATT notify support.

Protocol validated on hardware against known temperatures; reference frames
mirror the regression tests of the community integration at
https://github.com/boris327/ha-inkbird-int14bw.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any
from unittest.mock import patch

import pytest
from bleak.backends.device import BLEDevice
from bleak.exc import BleakError
from bluetooth_data_tools import monotonic_time_coarse
from habluetooth import BluetoothServiceInfoBleak

from inkbird_ble import INKBIRDBluetoothDeviceData, Model
from inkbird_ble.parser import (
    INT_14_BW_AUTH_CHALLENGE_REQUEST,
    INT_14_BW_BATTERY_UUID,
    INT_14_BW_COMMAND_UUID,
    INT_14_BW_NOTIFY_UUID,
    INT_14_BW_STATE_REQUEST,
    INT_14_BW_STATE_UUID,
    int_14_bw_auth_response,
    int_14_bw_clock_sync,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from uuid import UUID

    from sensor_state_data import SensorUpdate


CHALLENGE = bytes.fromhex("112233445566")
# ``07 fb <6-byte challenge>`` framed as <LEN><TYPE><payload>.
CHALLENGE_FRAME = bytes((0x07, 0xFB, *CHALLENGE))
AUTH_ACK_FRAME = bytes((0x02, 0xFC, 0x00))
# Live-validated ff01 frame: four [internal, ambient] signed LE16 pairs in
# tenths of a degree Celsius, then a frame counter and a flag byte.
# probe 1 = 26.0/26.0, probe 2 = 28.6/28.0, probes 3-4 invalid/unplugged.
TEMP_FRAME = bytes.fromhex("040104011e011801ff7fff7f008000000102")
# ff03 dock state: probe 2 (status byte at offset 2) has bit 0x02 set.
DOCK_FRAME = bytes((0x01, 0x10, 0x03, 0x10, 0x01, 0x10, 0x01, 0x10, 0x00))


def _service_info(name: str = "INT-14-BW") -> BluetoothServiceInfoBleak:
    return BluetoothServiceInfoBleak(
        name=name,
        manufacturer_data={},
        service_uuids=["0000ff00-0000-1000-8000-00805f9b34fb"],
        address="A4:C1:38:81:F1:4D",
        rssi=-50,
        service_data={},
        source="local",
        device=BLEDevice(name=name, address="A4:C1:38:81:F1:4D", details={}),
        time=monotonic_time_coarse(),
        advertisement=None,
        connectable=True,
        tx_power=0,
        raw=None,
    )


def test_int_14_bw_detected_by_name() -> None:
    """The INT-14-BW carries no manufacturer data, so it is matched by name.

    Its advertisement only contains the local name and the ff00 service
    UUID; detection therefore happens before the manufacturer-data guard in
    ``_start_update``. The match must be case-insensitive.
    """
    parser = INKBIRDBluetoothDeviceData()
    parser.update(_service_info("INT-14-BW"))
    assert parser.device_type is Model.INT_14_BW
    assert parser.uses_notify is True


def test_lookalike_models_are_not_detected() -> None:
    """INT-14S-BW / INT-12I-BW share the name prefix but use different ff01
    layouts, so the exact-name match must reject them rather than decode
    them with wrong offsets."""
    for name in ("INT-14S-BW", "INT-12I-BW", "int-14-bw-2"):
        parser = INKBIRDBluetoothDeviceData()
        parser.update(_service_info(name))
        assert parser.device_type is None, name


def test_auth_response_golden_vector() -> None:
    """Pin the CRC8 challenge/response construction to a fixed timestamp."""
    assert (
        int_14_bw_auth_response(CHALLENGE, now=1700000000.25).hex()
        == "08fcfa0000f1536555"
    )


def test_clock_sync_golden_vector() -> None:
    assert int_14_bw_clock_sync(now=1700000000.25).hex() == "071900f15365fa00"


class _MockInt14BwClient:
    """Minimal INT-14-BW: answers the ff02 handshake and streams ff01/ff03."""

    def __init__(self, temp_frame: bytes = TEMP_FRAME) -> None:
        self._temp_frame = temp_frame
        self.writes: list[tuple[UUID, bytes]] = []
        self._callbacks: dict[str, Callable[[UUID, bytearray], None]] = {}
        self.authed = False

    def set_disconnected_callback(self, callback: Callable[..., None]) -> None:
        self._disconnect_callback = callback

    async def start_notify(
        self, uuid: UUID, callback: Callable[[UUID, bytearray], None]
    ) -> None:
        self._callbacks[str(uuid)] = callback
        if str(uuid) == str(INT_14_BW_NOTIFY_UUID):
            callback(uuid, bytearray(self._temp_frame))

    async def write_gatt_char(
        self, uuid: UUID, data: bytes, response: bool = False
    ) -> None:
        self.writes.append((uuid, bytes(data)))
        assert str(uuid) == str(INT_14_BW_COMMAND_UUID)
        command_cb = self._callbacks[str(INT_14_BW_COMMAND_UUID)]
        if bytes(data) == INT_14_BW_AUTH_CHALLENGE_REQUEST:
            command_cb(uuid, bytearray(CHALLENGE_FRAME))
        elif data[0] == 0x08 and data[1] == 0xFC:
            self.authed = True
            command_cb(uuid, bytearray(AUTH_ACK_FRAME))

    async def read_gatt_char(self, uuid: UUID) -> bytes:
        assert str(uuid) == str(INT_14_BW_BATTERY_UUID)
        return b"\x55"  # 85 %

    async def disconnect(self) -> None:
        pass

    def feed_dock_state(self, frame: bytes) -> None:
        self._callbacks[str(INT_14_BW_STATE_UUID)](
            INT_14_BW_STATE_UUID, bytearray(frame)
        )


async def _run_session(
    client: _MockInt14BwClient,
    updates: list[SensorUpdate],
    during_session: Callable[[], None] | None = None,
    settle: float = 0,
) -> INKBIRDBluetoothDeviceData:
    parser = INKBIRDBluetoothDeviceData(Model.INT_14_BW, {}, updates.append, None)
    service_info = _service_info()
    parser.update(service_info)
    assert parser.uses_notify is True
    with patch("inkbird_ble.parser.establish_connection", return_value=client):
        await parser.async_start(
            service_info,
            BLEDevice(address="A4:C1:38:81:F1:4D", name="INT-14-BW", details={}),
        )
        for _ in range(20):
            await asyncio.sleep(0)
        if settle:
            await asyncio.sleep(settle)
        if during_session is not None:
            during_session()
            for _ in range(5):
                await asyncio.sleep(0)
        await parser.async_stop()
    return parser


@pytest.mark.asyncio
async def test_notify_int_14_bw_handshake_and_temperature_decode() -> None:
    """Full session: auth handshake, then decode the validated ff01 frame."""
    updates: list[SensorUpdate] = []
    client = _MockInt14BwClient()
    await _run_session(client, updates)

    # The handshake ran: challenge request, then a verify response, then the
    # clock sync and the state request, in that order.
    written = [data for _uuid, data in client.writes]
    assert written[0] == INT_14_BW_AUTH_CHALLENGE_REQUEST
    assert written[1][:2] == b"\x08\xfc"
    assert written[2][1] == 0x19  # clock sync
    assert written[3] == INT_14_BW_STATE_REQUEST
    assert client.authed is True

    assert updates, "expected a temperature update"
    values: dict[str, Any] = {
        key.key: value.native_value for key, value in updates[-1].entity_values.items()
    }
    assert values["temperature_probe_1"] == 26.0
    assert values["temperature_probe_1_ambient"] == 26.0
    assert values["temperature_probe_2"] == 28.6
    assert values["temperature_probe_2_ambient"] == 28.0
    assert values["temperature_probe_3"] is None
    assert values["temperature_probe_4"] is None
    assert values["temperature_probe_4_ambient"] == 0.0
    assert values["battery"] == 85


@pytest.mark.asyncio
async def test_notify_int_14_bw_docked_probe_is_masked() -> None:
    """A probe charging in the base station reports no temperature."""
    updates: list[SensorUpdate] = []
    client = _MockInt14BwClient()
    await _run_session(
        client, updates, during_session=lambda: client.feed_dock_state(DOCK_FRAME)
    )

    values: dict[str, Any] = {
        key.key: value.native_value for key, value in updates[-1].entity_values.items()
    }
    assert values["temperature_probe_1"] == 26.0
    assert values["temperature_probe_2"] is None
    assert values["temperature_probe_2_ambient"] is None


@pytest.mark.asyncio
async def test_notify_int_14_bw_short_frame_dropped() -> None:
    """A truncated ff01 notification is dropped whole."""
    updates: list[SensorUpdate] = []
    client = _MockInt14BwClient(temp_frame=TEMP_FRAME[:10])
    await _run_session(client, updates)
    assert not updates


@pytest.mark.asyncio
async def test_notify_int_14_bw_invalid_markers_are_none() -> None:
    """0x7FFE/0x7FFF/0x8000 temperature slots report None, never a bogus
    3276-degree reading."""
    frame = bytes.fromhex("fe7fff7f0080000080000000000000000102")
    updates: list[SensorUpdate] = []
    client = _MockInt14BwClient(temp_frame=frame)
    await _run_session(client, updates)
    assert updates, "expected an update (battery was read)"
    values: dict[str, Any] = {
        key.key: value.native_value for key, value in updates[-1].entity_values.items()
    }
    assert values["temperature_probe_1"] is None
    assert values["temperature_probe_1_ambient"] is None
    assert values["battery"] == 85


class _MockInt14BwNoAckClient(_MockInt14BwClient):
    """Variant that never ACKs the auth response (exercises the best-effort
    ``contextlib.suppress(TimeoutError)`` around the ACK wait)."""

    async def write_gatt_char(
        self, uuid: UUID, data: bytes, response: bool = False
    ) -> None:
        self.writes.append((uuid, bytes(data)))
        command_cb = self._callbacks[str(INT_14_BW_COMMAND_UUID)]
        if bytes(data) == INT_14_BW_AUTH_CHALLENGE_REQUEST:
            command_cb(uuid, bytearray(CHALLENGE_FRAME))


class _MockInt14BwBatteryFailClient(_MockInt14BwClient):
    """Variant whose 2a19 read fails and which receives a malformed auth
    frame before the real challenge (exercises the ff02 frame walker)."""

    async def read_gatt_char(self, uuid: UUID) -> bytes:
        msg = "no battery"
        raise BleakError(msg)

    async def write_gatt_char(
        self, uuid: UUID, data: bytes, response: bool = False
    ) -> None:
        self.writes.append((uuid, bytes(data)))
        command_cb = self._callbacks[str(INT_14_BW_COMMAND_UUID)]
        if bytes(data) == INT_14_BW_AUTH_CHALLENGE_REQUEST:
            # Malformed frame (truncated length) then an unknown frame type,
            # then the real challenge.
            command_cb(uuid, bytearray(bytes((0x09, 0xFB, 0x01))))
            command_cb(uuid, bytearray(bytes((0x02, 0x99, 0x00))))
            command_cb(uuid, bytearray(CHALLENGE_FRAME))
        elif data[0] == 0x08 and data[1] == 0xFC:
            self.authed = True
            command_cb(uuid, bytearray(AUTH_ACK_FRAME))


@pytest.mark.asyncio
async def test_notify_int_14_bw_auth_ack_timeout_still_streams() -> None:
    """A missing auth ACK must not block the temperature stream."""
    updates: list[SensorUpdate] = []
    client = _MockInt14BwNoAckClient()
    real_wait_for = asyncio.wait_for

    async def _fast_wait_for(aw: Any, timeout: float) -> Any:
        return await real_wait_for(aw, min(timeout, 0.05))

    with patch("asyncio.wait_for", side_effect=_fast_wait_for):
        await _run_session(client, updates, settle=0.2)
    assert updates, "expected a temperature update even without the ACK"
    values: dict[str, Any] = {
        key.key: value.native_value for key, value in updates[-1].entity_values.items()
    }
    assert values["temperature_probe_1"] == 26.0


@pytest.mark.asyncio
async def test_notify_int_14_bw_battery_read_failure_still_emits_temps() -> None:
    """A failed battery read and malformed ff02 frames must not abort the
    temperature update."""
    updates: list[SensorUpdate] = []
    client = _MockInt14BwBatteryFailClient()
    await _run_session(client, updates)
    assert updates, "expected a temperature update despite the battery failure"
    values: dict[str, Any] = {
        key.key: value.native_value for key, value in updates[-1].entity_values.items()
    }
    assert values["temperature_probe_1"] == 26.0
    assert "battery" not in values


@pytest.mark.asyncio
async def test_notify_int_14_bw_battery_notification() -> None:
    """A 2a19 notification updates the battery; 0x7F and implausible values
    are ignored."""
    updates: list[SensorUpdate] = []
    client = _MockInt14BwClient()

    def _battery_frames() -> None:
        cb = client._callbacks[str(INT_14_BW_BATTERY_UUID)]  # noqa: SLF001
        cb(INT_14_BW_BATTERY_UUID, bytearray(b"\x7f"))  # no-data marker
        cb(INT_14_BW_BATTERY_UUID, bytearray(b"\x32"))  # 50 %
        cb(INT_14_BW_BATTERY_UUID, bytearray(b""))  # empty

    await _run_session(client, updates, during_session=_battery_frames)
    parser_updates = updates[-1].entity_values
    battery_keys = [key.key for key in parser_updates if "battery" in key.key]
    assert battery_keys, "expected a battery sensor"
    for key, value in updates[-1].entity_values.items():
        if key.key == "battery":
            assert value.native_value == 50


@pytest.mark.asyncio
async def test_notify_int_14_bw_dock_frame_before_temps_is_ignored() -> None:
    """An ff03 dock frame arriving before any temperature frame publishes
    nothing (there is no reading to mask yet)."""
    updates: list[SensorUpdate] = []
    parser = INKBIRDBluetoothDeviceData(Model.INT_14_BW, {}, updates.append, None)
    parser.update(_service_info())
    parser._notify_int_14_bw(INT_14_BW_STATE_UUID, bytearray(DOCK_FRAME))  # noqa: SLF001
    assert updates == []


@pytest.mark.asyncio
async def test_notify_int_14_bw_without_update_callback() -> None:
    """A missing update callback drops the update instead of raising."""
    parser = INKBIRDBluetoothDeviceData(Model.INT_14_BW, {}, None, None)
    parser.update(_service_info())
    parser._notify_int_14_bw(INT_14_BW_NOTIFY_UUID, bytearray(TEMP_FRAME))  # noqa: SLF001
    parser._notify_int_14_bw(INT_14_BW_STATE_UUID, bytearray(DOCK_FRAME))  # noqa: SLF001


@pytest.mark.asyncio
async def test_notify_int_14_bw_clean_disconnect_returns() -> None:
    """When the link drops cleanly, the notify action returns so the outer
    loop can reconnect."""
    updates: list[SensorUpdate] = []
    client = _MockInt14BwClient()

    def _disconnect() -> None:
        client._disconnect_callback(client)  # noqa: SLF001

    await _run_session(client, updates, during_session=_disconnect)
    assert updates, "expected the temperature update before the disconnect"
