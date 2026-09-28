"""Tests for INT-31-BW / INT-33-BW settings access."""

from __future__ import annotations

import asyncio
import struct
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from bleak.backends.device import BLEDevice

from inkbird_ble import INTBWClient, Model, Units
from inkbird_ble.intbw import (
    AlarmRepeat,
    Calibration,
    CookTarget,
    INTBWAuthError,
    INTBWCommandError,
    INTBWError,
    auth_response,
    decode_cook_target,
    decode_timer,
    split_frames,
)

# Replies captured from a real INT-31-BW base (firmware V1.0.8).
CAPTURED_REPLIES = {
    "0104": "020443",
    "0106": "020650",
    "0108": "03081e00",
    "020aff": "0c0a0100000000000000000000",
    "010c": "030c5a03",
    "0111": "0411110301",
    "0115": "4c15d0eff038c1a4699c1a6956312e302e38d9f2082510252056312e332e30e7"
    "0000000000000000000000007f0000000000000000000000007f000000000000000000"
    "0000007f3c0b59334ba1",
    "020201": "0d02010000000000000000000000",
    "020210": "0d02100000000000000000000000",
    "0124": "0a24010000000000000000",
    "022601": "0a26010000000000000000",
    "023701": "0b3701494e542d33312d4257",
    "023702": "073702424c41434b",
    "0141": "0441018403",
    "015b": "025b01",
}
# INT-33-BW replies, shaped from the INKBIRD app's reply parsing.
INT_33_REPLIES = {
    "020aff": "1c0a07" + "00" * 26,
    "0124": "0a24070000000000000000",
    "020202": "0d02020000000000000000000000",
    "020220": "0d02200000000000000000000000",
    "020204": "0d02040000000000000000000000",
    "022602": "0a26020000000000000000",
    "022604": "0a26040000000000000000",
    "023701": "0b3701494e542d33332d4257",
    "023703": "073703424c41434b",
    "023704": "073704" + b"WHITE".hex(),
}
CHALLENGE = bytes.fromhex("895040689bb6")


class FakeClient:
    """Stand-in for the bleak client that answers like the base."""

    def __init__(self, auth_result: str = "00", model: Model = Model.INT_31_BW) -> None:
        self.writes: list[bytes] = []
        self.replies = dict(CAPTURED_REPLIES)
        if model is Model.INT_33_BW:
            self.replies.update(INT_33_REPLIES)
        self.auth_result = auth_result
        self.callback: Any = None
        self.disconnect = AsyncMock()

    async def start_notify(self, _uuid: Any, callback: Any) -> None:
        self.callback = callback

    async def write_gatt_char(self, _uuid: Any, data: bytes, response: bool) -> None:
        assert response is False
        self.writes.append(data)
        hex_data = data.hex()
        if hex_data == "01fb":
            reply = "07fb" + CHALLENGE.hex()
        elif data[1] == 0xFC:
            reply = "02fc" + self.auth_result
        elif hex_data in self.replies:
            reply = self.replies[hex_data]
        elif data[1] == 0x19:
            reply = "0520" + data[2:6].hex()
        else:
            reply = "".join(
                bytes((len(p) + 1, cmd + 1)).hex() + p.hex()
                for cmd, p in split_frames(data)
            )
        if reply:
            asyncio.get_running_loop().call_soon(
                self.callback, None, bytearray.fromhex(reply)
            )


BLE_DEVICE = BLEDevice(address="A4:C1:38:F0:EF:D0", name="INT-31-BW", details={})
BLE_DEVICE_33 = BLEDevice(address="A4:C1:38:F0:EF:D1", name="INT-33-BW", details={})


async def _client(fake: FakeClient, device: BLEDevice = BLE_DEVICE) -> INTBWClient:
    with patch("inkbird_ble.intbw.establish_connection", return_value=fake):
        client = INTBWClient(device, timeout=0.2)
        await client.async_connect()
    return client


def test_auth_response_matches_app() -> None:
    """The handshake reply is the CRC construction the app uses."""
    packet = auth_response(CHALLENGE, 1_790_000_000_123)
    assert packet[:2] == b"\x08\xfc"
    assert packet[2:8] == struct.pack("<HI", 123, 1_790_000_000)
    assert len(packet) == 9


def test_split_frames() -> None:
    """Concatenated replies are split by their length byte."""
    assert split_frames(bytes.fromhex("020443025b0100ff")) == [
        (0x04, b"C"),
        (0x5B, b"\x01"),
    ]


def test_model_from_name() -> None:
    """The model comes from the device name unless given."""
    assert INTBWClient(BLE_DEVICE).model is Model.INT_31_BW
    assert INTBWClient(BLE_DEVICE_33).model is Model.INT_33_BW
    assert INTBWClient(BLE_DEVICE, Model.INT_33_BW).model is Model.INT_33_BW
    assert len(INTBWClient(BLE_DEVICE_33).probes) == 3


def test_unsupported_model() -> None:
    """Non-BW devices are rejected."""
    with pytest.raises(ValueError, match="Unsupported model"):
        INTBWClient(BLEDevice(address="AA", name="sps", details={}))
    with pytest.raises(ValueError, match="Unsupported model"):
        INTBWClient(BLE_DEVICE, Model.IBS_TH)


@pytest.mark.asyncio
async def test_read_settings() -> None:
    """Settings decode from real replies."""
    fake = FakeClient()
    client = await _client(fake)
    settings = await client.async_read_settings()
    assert settings.temperature_unit is Units.TEMP_CELSIUS
    assert settings.brightness == 80
    assert settings.backlight_timeout == 30
    assert settings.volume == 3
    assert settings.alarm_repeat is None
    assert settings.auto_sleep == 900
    assert settings.wifi is True
    assert settings.name == "INT-31-BW"
    (probe,) = settings.probes
    assert probe.name == "BLACK"
    assert probe.calibration == Calibration(sensors=(0.0,) * 4, ambient=0.0)
    assert probe.food_target is None
    assert probe.ambient_target is None
    assert probe.pre_alarm is None
    assert probe.timer is None
    await client.async_disconnect()
    fake.disconnect.assert_awaited_once()


@pytest.mark.asyncio
async def test_read_settings_non_default() -> None:
    """Fahrenheit, mute, repeat, sleep off and active targets decode."""
    fake = FakeClient()
    fake.replies.update(
        {
            "0104": "020446",
            "010c": "030c1100",
            "0111": "0411010305",
            "0141": "0441000000",
            "015b": "025b00",
            "020aff": "0c0a01" + struct.pack("<5h", 180, 0, 0, 0, -360).hex(),
            "020201": "0d020110b0360000000000f2bab9",
            "020210": "0d021011b004e803000000f2bab96a",
            "0124": "0a2401090000000000000000",
            "022601": "0a268100e1f5050000000000",
        }
    )
    client = await _client(fake)
    settings = await client.async_read_settings()
    assert settings.temperature_unit is Units.TEMP_FAHRENHEIT
    assert settings.volume == 0
    assert settings.alarm_repeat == AlarmRepeat(times=3, interval=5)
    assert settings.auto_sleep is None
    assert settings.wifi is False
    (probe,) = settings.probes
    assert probe.calibration == Calibration(sensors=(1.0, 0.0, 0.0, 0.0), ambient=-2.0)
    assert probe.food_target == CookTarget(high=60.0)
    assert probe.ambient_target == CookTarget(high=48.9, low=37.8)
    assert probe.pre_alarm == 5.0
    assert probe.timer is not None
    assert probe.timer.count_up
    assert probe.timer.end is None
    assert probe.timer.start == datetime.fromtimestamp(100_000_000, UTC)


@pytest.mark.asyncio
async def test_read_settings_int_33_bw() -> None:
    """INT-33-BW settings cover three probes; probe 3 has no ambient."""
    fake = FakeClient(model=Model.INT_33_BW)
    fake.replies["020aff"] = "1c0a07" + struct.pack("<13h", *range(0, 1300, 100)).hex()
    fake.replies["0124"] = "0a24070012000000000000"
    client = await _client(fake, BLE_DEVICE_33)
    settings = await client.async_read_settings()
    assert settings.name == "INT-33-BW"
    assert [p.name for p in settings.probes] == ["BLACK", "BLACK", "WHITE"]
    assert settings.probes[0].calibration.ambient == 2.22
    assert settings.probes[1].calibration.sensors[0] == 2.78
    assert settings.probes[2].calibration == Calibration(sensors=(5.56, 6.11, 6.67))
    assert settings.probes[2].ambient_target is None
    assert settings.probes[1].pre_alarm == 10.0
    assert "020240" not in [w.hex() for w in fake.writes]


def test_decode_short_replies() -> None:
    """Truncated target / timer replies decode to ``None``."""
    assert decode_cook_target(b"\x01\x10") is None
    assert decode_timer(b"\x01") is None


@pytest.mark.asyncio
async def test_read_volume_level_fallback() -> None:
    """Unknown volume level bytes read as level 1."""
    fake = FakeClient()
    fake.replies["010c"] = "030c5a07"
    client = await _client(fake)
    assert (await client.async_read_settings()).volume == 1


@pytest.mark.asyncio
async def test_read_device_info() -> None:
    """Device info decodes firmware and addresses."""
    client = await _client(FakeClient())
    info = await client.async_read_device_info()
    assert info.base_address == "A4:C1:38:F0:EF:D0"
    assert info.base_firmware == "V1.0.8"
    (probe,) = info.probes
    assert probe is not None
    assert probe.address == "20:25:10:25:08:F2"
    assert probe.firmware == "V1.3.0"
    assert probe.rssi == -25
    assert info.wifi_address == "3C:0B:59:33:4B:A1"


@pytest.mark.asyncio
async def test_read_device_info_int_33_bw() -> None:
    """INT-33-BW device info has a slot per probe; unpaired slots are None."""
    client = await _client(FakeClient(model=Model.INT_33_BW), BLE_DEVICE_33)
    info = await client.async_read_device_info()
    assert info.probes[0] is not None
    assert info.probes[1:] == (None, None)


@pytest.mark.asyncio
async def test_read_device_info_too_short() -> None:
    """A truncated device info reply raises."""
    fake = FakeClient()
    fake.replies["0115"] = "031500ff"
    client = await _client(fake)
    with pytest.raises(INTBWError, match="too short"):
        await client.async_read_device_info()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "args", "expected"),
    [
        ("async_set_temperature_unit", (Units.TEMP_FAHRENHEIT,), "020346"),
        ("async_set_temperature_unit", (Units.TEMP_CELSIUS,), "020343"),
        ("async_set_brightness", (80,), "020550"),
        ("async_set_backlight_timeout", (30,), "03071e00"),
        ("async_set_volume", (0,), "030b1100"),
        ("async_set_volume", (2,), "030b5a02"),
        ("async_set_alarm_repeat", (None,), "0410110000"),
        ("async_set_alarm_repeat", (AlarmRepeat(3, 5),), "0410010305"),
        ("async_set_auto_sleep", (900,), "0440018403"),
        ("async_set_auto_sleep", (None,), "0440000000"),
        ("async_set_wifi", (True,), "025a01"),
        ("async_set_wifi", (False,), "025a00"),
        ("async_set_name", ("INT-31-BW",), "0b3601494e542d33312d4257"),
        ("async_set_probe_name", (1, "BLACK"), "073602424c41434b"),
        (
            "async_set_calibration",
            (1, Calibration(sensors=(1.0, 0.0, 0.0, 0.0), ambient=-2.0)),
            "0c0901b400000000000000" + struct.pack("<h", -360).hex(),
        ),
        ("async_reset_timer", (1,), "0a25010000000000000000"),
        ("async_silence_alarms", (), "0638ffffffffff"),
        ("async_start_signal_optimization", (), "023a01"),
    ],
)
async def test_setters(method: str, args: tuple[Any, ...], expected: str) -> None:
    """Each setter writes the frame the app writes."""
    fake = FakeClient()
    client = await _client(fake)
    await getattr(client, method)(*args)
    assert fake.writes[-1].hex() == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "args", "expected"),
    [
        ("async_set_probe_name", (3, "WHITE"), "073604" + b"WHITE".hex()),
        ("async_reset_timer", (3,), "0a25040000000000000000"),
        (
            "async_set_calibration",
            (3, Calibration(sensors=(1.0, 0.0, -1.0))),
            "1c0904" + "00" * 20 + struct.pack("<3h", 180, 0, -180).hex(),
        ),
    ],
)
async def test_setters_int_33_bw(
    method: str, args: tuple[Any, ...], expected: str
) -> None:
    """INT-33-BW probe commands select the probe by mask."""
    fake = FakeClient(model=Model.INT_33_BW)
    client = await _client(fake, BLE_DEVICE_33)
    await getattr(client, method)(*args)
    assert fake.writes[-1].hex() == expected


@pytest.mark.asyncio
async def test_set_cook() -> None:
    """Food, ambient and pre-alarm go out in one write."""
    fake = FakeClient()
    client = await _client(fake)
    with patch("inkbird_ble.intbw.time.time", return_value=100_000_000):
        await client.async_set_cook(
            1, CookTarget(high=60.0), CookTarget(high=120.0, low=100.0), pre_alarm=5.0
        )
    start = struct.pack("<I", 100_000_000).hex()
    assert fake.writes[-1].hex() == (
        "0d010110b036000000" + "00" + start
        + "0d011011b0094808" + "0000" + start
        + "0a23010900000000000000"
    )  # fmt: skip


@pytest.mark.asyncio
async def test_set_cook_int_33_bw() -> None:
    """Probe 2 uses masks 0x02 / 0x20; probe 3 has no ambient frame."""
    fake = FakeClient(model=Model.INT_33_BW)
    client = await _client(fake, BLE_DEVICE_33)
    with patch("inkbird_ble.intbw.time.time", return_value=100_000_000):
        await client.async_set_cook(2, CookTarget(high=60.0), pre_alarm=5.0)
        start = struct.pack("<I", 100_000_000).hex()
        assert fake.writes[-1].hex() == (
            "0d010210b036000000" + "00" + start
            + "0d0120" + "00" * 11
            + "0a2302" + "0009" + "00" * 6
        )  # fmt: skip
        await client.async_set_cook(3, CookTarget(high=60.0))
    assert fake.writes[-1].hex() == (
        "0d010410b036000000" + "00" + start + "0a2304" + "00" * 8
    )


@pytest.mark.asyncio
async def test_clear_cook() -> None:
    """Clearing zeroes both targets and the pre-alarm."""
    fake = FakeClient()
    client = await _client(fake)
    await client.async_set_cook(1, None)
    assert fake.writes[-1].hex() == (
        "0d0101" + "00" * 11 + "0d0110" + "00" * 11 + "0a2301" + "00" * 8
    )


@pytest.mark.asyncio
async def test_set_timer() -> None:
    """Countdown and count-up timers encode start/end times and the probe."""
    fake = FakeClient()
    client = await _client(fake)
    with patch("inkbird_ble.intbw.time.time", return_value=100):
        await client.async_set_timer(1, 600)
        assert fake.writes[-1].hex() == "0a250164000000bc020000"
        await client.async_set_timer(1, None)
        assert fake.writes[-1].hex() == "0a25816400000000000000"


@pytest.mark.asyncio
async def test_sync_time() -> None:
    """Time sync sends seconds and milliseconds."""
    fake = FakeClient()
    client = await _client(fake)
    with patch("inkbird_ble.intbw.time.time_ns", return_value=100_250_000_000):
        await client.async_sync_time()
    assert fake.writes[-1].hex() == "071964000000fa00"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "args"),
    [
        ("async_set_temperature_unit", (Units.PERCENTAGE,)),
        ("async_set_brightness", (101,)),
        ("async_set_volume", (4,)),
        ("async_set_alarm_repeat", (AlarmRepeat(6, 5),)),
        ("async_set_alarm_repeat", (AlarmRepeat(3, 7),)),
        ("async_set_name", ("",)),
        ("async_set_name", ("x" * 33,)),
        ("async_set_probe_name", (2, "BLACK")),
        ("async_set_calibration", (1, Calibration(sensors=(11.0, 0, 0, 0), ambient=0))),
        ("async_set_calibration", (1, Calibration(sensors=(0, 0, 0, 0), ambient=21))),
        ("async_set_calibration", (1, Calibration(sensors=(0.0,), ambient=0))),
        ("async_set_calibration", (1, Calibration(sensors=(0, 0, 0, 0)))),
        ("async_set_cook", (2, None)),
        ("async_set_timer", (0, 60)),
        ("async_reset_timer", (2,)),
    ],
)
async def test_setter_validation(method: str, args: tuple[Any, ...]) -> None:
    """Out-of-range values raise before anything is written."""
    fake = FakeClient()
    client = await _client(fake)
    writes = len(fake.writes)
    with pytest.raises(ValueError, match=r"."):
        await getattr(client, method)(*args)
    assert len(fake.writes) == writes


@pytest.mark.asyncio
async def test_int_33_bw_restrictions() -> None:
    """Probe 3 has no ambient sensor; signal optimization is INT-31-BW only."""
    client = await _client(FakeClient(model=Model.INT_33_BW), BLE_DEVICE_33)
    with pytest.raises(ValueError, match="no ambient"):
        await client.async_set_cook(3, None, CookTarget(high=100.0))
    with pytest.raises(INTBWError, match="signal optimization"):
        await client.async_start_signal_optimization()


@pytest.mark.asyncio
async def test_context_manager() -> None:
    """The context manager connects, authenticates and disconnects."""
    fake = FakeClient()
    with patch("inkbird_ble.intbw.establish_connection", return_value=fake):
        async with INTBWClient(BLE_DEVICE) as client:
            assert (await client.async_read_settings()).brightness == 80
    assert fake.writes[0].hex() == "01fb"
    assert fake.writes[1][:2] == b"\x08\xfc"
    fake.disconnect.assert_awaited_once()


@pytest.mark.asyncio
async def test_auth_rejected() -> None:
    """A rejected handshake disconnects and raises."""
    fake = FakeClient(auth_result="02")
    with pytest.raises(INTBWAuthError):
        await _client(fake)
    fake.disconnect.assert_awaited_once()


@pytest.mark.asyncio
async def test_auth_timeout_disconnects() -> None:
    """A base that never answers the challenge is disconnected."""
    fake = FakeClient()
    fake.start_notify = AsyncMock()  # type: ignore[method-assign]
    with pytest.raises(TimeoutError):
        await _client(fake)
    fake.disconnect.assert_awaited_once()


@pytest.mark.asyncio
async def test_command_error() -> None:
    """An error frame naming the command fails the request."""
    fake = FakeClient()
    fake.replies["0106"] = "03fe0406"
    client = await _client(fake)
    with pytest.raises(INTBWCommandError):
        await client.async_read_settings()


@pytest.mark.asyncio
async def test_unrelated_error_frame_ignored() -> None:
    """An error frame for another command does not fail the request."""
    fake = FakeClient()
    fake.replies["0106"] = "03fe0453020650"
    client = await _client(fake)
    assert (await client.async_read_settings()).brightness == 80


@pytest.mark.asyncio
async def test_not_connected() -> None:
    """Requests before connecting raise."""
    client = INTBWClient(BLE_DEVICE)
    with pytest.raises(INTBWError, match="Not connected"):
        await client.async_set_brightness(10)
    with pytest.raises(INTBWError, match="Not connected"):
        await client.async_silence_alarms()
    with pytest.raises(INTBWError, match="Not connected"):
        await client.async_read_state()
    with pytest.raises(INTBWError, match="Not connected"):
        await client.async_read_battery()
    await client.async_disconnect()


@pytest.mark.asyncio
async def test_read_state() -> None:
    """The ff03 bitfield decodes; idle and ambient-low alarm states."""
    fake = FakeClient()
    fake.read_gatt_char = AsyncMock(  # type: ignore[attr-defined]
        side_effect=[bytes.fromhex("011000530500"), bytes.fromhex("011001530500")]
    )
    client = await _client(fake)
    idle = await client.async_read_state()
    (probe,) = idle.probes
    assert probe.connected
    assert probe.paired
    assert not probe.charging
    assert idle.base_charging
    assert not idle.alarm
    alarm = await client.async_read_state()
    assert alarm.probes[0].ambient_low_alarm
    assert alarm.alarm


@pytest.mark.asyncio
async def test_read_state_int_33_bw() -> None:
    """INT-33-BW probes use 24-bit slots and device bits start at bit 64."""
    bits = (1 << 24) | (1 << 28) | (1 << 48) | (1 << 64) | (1 << 76) | (1 << 86)
    fake = FakeClient(model=Model.INT_33_BW)
    fake.read_gatt_char = AsyncMock(  # type: ignore[attr-defined]
        return_value=bits.to_bytes(12, "little")
    )
    client = await _client(fake, BLE_DEVICE_33)
    state = await client.async_read_state()
    assert not state.probes[0].connected
    assert state.probes[1].connected
    assert state.probes[1].food_high_alarm
    assert state.probes[1].timer_alarm
    assert state.probes[2].connected
    # Bits 64/65 belong to the base, not probe 3's (absent) ambient alarms.
    assert not state.probes[2].ambient_low_alarm
    assert state.base_charging
    assert state.base_low_battery
    assert state.alarm


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("model", "data", "base", "probes"),
    [
        (Model.INT_31_BW, "6364", 99, (100,)),
        (Model.INT_31_BW, "7f64", None, (100,)),
        (Model.INT_31_BW, "ff", None, (None,)),
        (Model.INT_31_BW, "", None, (None,)),
        (Model.INT_33_BW, "6364507f", 99, (100, 80, None)),
    ],
)
async def test_read_battery(
    model: Model, data: str, base: int | None, probes: tuple[int | None, ...]
) -> None:
    """2a19 carries the base then one percentage per probe."""
    fake = FakeClient(model=model)
    fake.read_gatt_char = AsyncMock(return_value=bytes.fromhex(data))  # type: ignore[attr-defined]
    client = await _client(
        fake, BLE_DEVICE if model is Model.INT_31_BW else BLE_DEVICE_33
    )
    battery = await client.async_read_battery()
    assert (battery.base, battery.probes) == (base, probes)
