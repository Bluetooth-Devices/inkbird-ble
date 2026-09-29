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
