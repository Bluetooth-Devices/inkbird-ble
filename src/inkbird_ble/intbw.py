"""Read and change INT-31-BW / INT-33-BW base station settings over GATT.

Commands go to the ``ff02`` characteristic as ``[len][cmd][payload]`` frames,
where ``len`` counts the bytes after itself. The base answers every query and
every write on ``ff02`` with the matching read command (write command + 1)
holding the value it now has. A connection must first pass a CRC-based
challenge handshake; no cloud secrets are involved.

Probe-specific commands select a probe with a bit mask: ``1 << (probe - 1)``
for the food sensors and ``1 << (probe + 3)`` for the ambient sensor. The
INT-31-BW behaviour is verified on hardware; the INT-33-BW differences come
from the INKBIRD app.
"""

from __future__ import annotations

import asyncio
import struct
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Self
from uuid import UUID

from bleak_retry_connector import BleakClientWithServiceCache, establish_connection
from sensor_state_data import Units

from .parser import BW_PROBES, BWProbe, Model, try_parse_model

if TYPE_CHECKING:
    from collections.abc import Callable
    from types import TracebackType

    from bleak import BleakGATTCharacteristic, BLEDevice

COMMAND_UUID = UUID("0000ff02-0000-1000-8000-00805f9b34fb")
STATE_UUID = UUID("0000ff03-0000-1000-8000-00805f9b34fb")
BATTERY_UUID = UUID("00002a19-0000-1000-8000-00805f9b34fb")

CMD_AUTH_CHALLENGE = 0xFB
CMD_AUTH_RESPONSE = 0xFC
CMD_ERROR = 0xFE
CMD_COOK = 0x01
CMD_UNIT = 0x03
CMD_BRIGHTNESS = 0x05
CMD_BACKLIGHT = 0x07
CMD_CALIBRATION = 0x09
CMD_VOLUME = 0x0B
CMD_ALARM_REPEAT = 0x10
CMD_DEVICE_INFO = 0x14
CMD_TIME_SYNC = 0x19
CMD_TIME_SYNC_REPLY = 0x20
CMD_PRE_ALARM = 0x23
CMD_TIMER = 0x25
CMD_NAME = 0x36
CMD_SILENCE = 0x38
CMD_SIGNAL_OPTIMIZATION = 0x3A
CMD_AUTO_SLEEP = 0x40
CMD_WIFI = 0x5A

MODE_HIGH = 0x10
MODE_LOW = 0x01
NAME_BASE = 0x01
UNIT_FAHRENHEIT = ord("F")
UNIT_CELSIUS = ord("C")
VOLUME_MUTED = 0x11
VOLUME_ON = 0x5A
ALARM_ONCE = 0x11
ALARM_REPEAT = 0x01
TIMER_COUNT_UP = 0x80
SILENCE_ALL = b"\xff" * 5
BATTERY_INVALID = 0x7F
PRE_ALARM_SLOTS = 8

MAX_BATTERY = 100
MAX_VOLUME = 3
MAX_BRIGHTNESS = 100
MAX_NAME_BYTES = 32
MAX_ALARM_REPEAT_TIMES = 5
ALARM_REPEAT_INTERVALS = (1, 3, 5, 10, 15, 20, 25, 30)
MAX_FOOD_CALIBRATION_C = 10.0
MAX_AMBIENT_CALIBRATION_C = 20.0
DEVICE_INFO_PROBE_OFFSET = 17
DEVICE_INFO_PROBE_LEN = 13
DEVICE_INFO_WIFI_LEN = 6
COOK_MIN_LEN = 8
TIMER_LEN = 9
STATE_PROBE_BITS = 24

DEFAULT_TIMEOUT = 10.0


@dataclass(frozen=True)
class BWModel:
    """Protocol differences between the INT-BW bases."""

    probes: tuple[BWProbe, ...]
    state_device_bit: int
    signal_optimization: bool


BW_MODELS = {
    Model.INT_31_BW: BWModel(
        BW_PROBES[Model.INT_31_BW], state_device_bit=24, signal_optimization=True
    ),
    Model.INT_33_BW: BWModel(
        BW_PROBES[Model.INT_33_BW], state_device_bit=64, signal_optimization=False
    ),
}


class INTBWError(Exception):
    """Base error for INT-BW settings access."""


class INTBWAuthError(INTBWError):
    """The base rejected the authentication handshake."""


class INTBWCommandError(INTBWError):
    """The base rejected a command."""


@dataclass(frozen=True)
class AlarmRepeat:
    """Repeat an alarm ``times`` times, ``interval`` minutes apart."""

    times: int
    interval: int


@dataclass(frozen=True)
class CookTarget:
    """A cook alarm target in Celsius; ``None`` bounds are not set."""

    high: float | None = None
    low: float | None = None
    doneness: int = 0
    food: int = 0


@dataclass(frozen=True)
class Timer:
    """A countdown (``end`` set) or count-up timer."""

    start: datetime
    end: datetime | None
    count_up: bool


@dataclass(frozen=True)
class Calibration:
    """Calibration offsets in Celsius; ``ambient`` is ``None`` without a sensor."""

    sensors: tuple[float, ...]
    ambient: float | None = None


@dataclass(frozen=True)
class ProbeSettings:
    """Settings for one probe."""

    name: str
    calibration: Calibration
    food_target: CookTarget | None
    ambient_target: CookTarget | None
    pre_alarm: float | None
    timer: Timer | None


@dataclass(frozen=True)
class Settings:
    """All user settings of an INT-BW base."""

    temperature_unit: Units
    brightness: int
    backlight_timeout: int
    volume: int
    alarm_repeat: AlarmRepeat | None
    auto_sleep: int | None
    wifi: bool
    name: str
    probes: tuple[ProbeSettings, ...]


@dataclass(frozen=True)
class Battery:
    """Battery percentages; ``None`` when the base reports no value."""

    base: int | None
    probes: tuple[int | None, ...]


@dataclass(frozen=True)
class ProbeInfo:
    """Address, firmware and signal of a paired probe."""

    address: str
    firmware: str
    rssi: int


@dataclass(frozen=True)
class DeviceInfo:
    """Firmware and addresses reported by the base."""

    base_address: str
    base_firmware: str
    probes: tuple[ProbeInfo | None, ...]
    wifi_address: str


@dataclass(frozen=True)
class ProbeState:
    """State and alarms of one probe (a slot of the ``ff03`` bitfield)."""

    connected: bool
    charging: bool
    paired: bool
    low_battery: bool
    food_low_alarm: bool
    food_high_alarm: bool
    food_over_temperature: bool
    food_under_temperature: bool
    pre_alarm: bool
    ambient_low_alarm: bool
    ambient_high_alarm: bool
    ambient_over_temperature: bool
    ambient_under_temperature: bool
    signal_interference: bool
    timer_running: bool
    timer_alarm: bool

    @property
    def alarm(self) -> bool:
        """Return True while any of this probe's alarms is sounding."""
        return any(
            (
                self.low_battery,
                self.food_low_alarm,
                self.food_high_alarm,
                self.food_over_temperature,
                self.food_under_temperature,
                self.pre_alarm,
                self.ambient_low_alarm,
                self.ambient_high_alarm,
                self.ambient_over_temperature,
                self.ambient_under_temperature,
                self.timer_alarm,
            )
        )


@dataclass(frozen=True)
class State:
    """Probe, base and alarm state (the ``ff03`` bitfield)."""

    probes: tuple[ProbeState, ...]
    base_charging: bool
    base_low_battery: bool
    base_over_temperature: bool
    base_under_temperature: bool

    @property
    def alarm(self) -> bool:
        """Return True while any alarm is sounding."""
        return any(p.alarm for p in self.probes) or any(
            (
                self.base_low_battery,
                self.base_over_temperature,
                self.base_under_temperature,
            )
        )


def _crc8(data: bytes, poly: int, init: int) -> int:
    crc = init
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = ((crc << 1) ^ poly) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
    return crc


def auth_response(challenge: bytes, now_ms: int) -> bytes:
    """Build the ``fc`` frame answering an ``fb`` challenge."""
    stamp = struct.pack("<HI", now_ms % 1000, now_ms // 1000)
    check = stamp + bytes((_crc8(stamp, 0xD5, 0x00), _crc8(challenge, 0x9B, 0xFF)))
    return frame(CMD_AUTH_RESPONSE, stamp + bytes((_crc8(check, 0xD5, 0x00),)))


def frame(cmd: int, payload: bytes = b"") -> bytes:
    """Wrap ``payload`` in a ``[len][cmd]`` frame."""
    return bytes((len(payload) + 1, cmd)) + payload


def split_frames(data: bytes) -> list[tuple[int, bytes]]:
    """Split a notification into ``(cmd, payload)`` frames."""
    frames = []
    index = 0
    while index + 1 < len(data):
        length = data[index]
        if length == 0:
            break
        body = data[index + 1 : index + 1 + length]
        frames.append((body[0], bytes(body[1:])))
        index += 1 + length
    return frames


def food_mask(probe: int) -> int:
    """Return the command mask selecting a probe's food sensors."""
    return 1 << (probe - 1)


def ambient_mask(probe: int) -> int:
    """Return the command mask selecting a probe's ambient sensor."""
    return 1 << (probe + 3)


def _f_delta(celsius: float, scale: int) -> int:
    return round(celsius * 9 / 5 * scale)


def _c_delta(raw: int, scale: int) -> float:
    return round(raw / scale * 5 / 9, 2)


def _to_f(celsius: float, scale: int) -> int:
    return round((celsius * 9 / 5 + 32) * scale)


def _to_c(raw: int, scale: int) -> float:
    return round((raw / scale - 32) * 5 / 9, 1)


def _address(raw: bytes) -> str:
    return ":".join(f"{b:02X}" for b in reversed(raw))


def _timestamp(value: int) -> datetime:
    return datetime.fromtimestamp(value, UTC)


def encode_cook_target(mask: int, target: CookTarget | None, start: int) -> bytes:
    """Encode a food or ambient target (ambient masks are ``>= 0x10``)."""
    scale = 10 if mask >= ambient_mask(1) else 100
    if target is None:
        return frame(CMD_COOK, bytes((mask,)) + bytes(11))
    mode = (MODE_HIGH if target.high is not None else 0) | (
        MODE_LOW if target.low is not None else 0
    )
    high = 0 if target.high is None else _to_f(target.high, scale)
    low = 0 if target.low is None else _to_f(target.low, scale)
    return frame(
        CMD_COOK,
        struct.pack(
            "<BBhhBBI", mask, mode, high, low, target.doneness, target.food, start
        ),
    )


def decode_cook_target(payload: bytes) -> CookTarget | None:
    """Decode a cook target reply (``mask`` first)."""
    if len(payload) < COOK_MIN_LEN or not payload[1]:
        return None
    mask, mode, high, low, doneness, food = struct.unpack_from("<BBhhBB", payload)
    scale = 10 if mask >= ambient_mask(1) else 100
    return CookTarget(
        high=_to_c(high, scale) if mode & MODE_HIGH else None,
        low=_to_c(low, scale) if mode & MODE_LOW else None,
        doneness=doneness,
        food=food,
    )


def _calibration_size(probe: BWProbe) -> int:
    return probe.sensors + probe.ambient


def decode_calibration(
    payload: bytes, probes: tuple[BWProbe, ...]
) -> tuple[Calibration, ...]:
    """Decode a calibration reply (``mask`` then int16 offsets per probe)."""
    count = sum(_calibration_size(p) for p in probes)
    values = [_c_delta(v, 100) for v in struct.unpack_from(f"<{count}h", payload, 1)]
    result = []
    for probe in probes:
        chunk, values = (
            values[: _calibration_size(probe)],
            values[_calibration_size(probe) :],
        )
        result.append(
            Calibration(
                sensors=tuple(chunk[: probe.sensors]),
                ambient=chunk[probe.sensors] if probe.ambient else None,
            )
        )
    return tuple(result)


def decode_timer(payload: bytes) -> Timer | None:
    """Decode a timer reply."""
    if len(payload) < TIMER_LEN:
        return None
    index, start, end = struct.unpack_from("<BII", payload)
    if not start:
        return None
    return Timer(
        start=_timestamp(start),
        end=_timestamp(end) if end else None,
        count_up=bool(index & TIMER_COUNT_UP),
    )


def decode_battery(data: bytes, probe_count: int) -> Battery:
    """Decode the ``2a19`` read (base percentage, then one per probe)."""

    def level(index: int) -> int | None:
        if len(data) <= index or data[index] == BATTERY_INVALID:
            return None
        value = data[index]
        return value if value <= MAX_BATTERY else None

    return Battery(
        base=level(0), probes=tuple(level(i + 1) for i in range(probe_count))
    )


def decode_device_info(payload: bytes, probe_count: int) -> DeviceInfo:
    """Decode a device info reply."""
    probes: list[ProbeInfo | None] = []
    for idx in range(probe_count):
        offset = DEVICE_INFO_PROBE_OFFSET + idx * DEVICE_INFO_PROBE_LEN
        entry = payload[offset : offset + DEVICE_INFO_PROBE_LEN]
        if len(entry) < DEVICE_INFO_PROBE_LEN or not any(entry[:6]):
            probes.append(None)
            continue
        probes.append(
            ProbeInfo(
                address=_address(entry[0:6]),
                firmware=entry[6:12].decode(errors="replace"),
                rssi=struct.unpack_from("b", entry, 12)[0],
            )
        )
    return DeviceInfo(
        base_address=_address(payload[0:6]),
        base_firmware=payload[10:16].decode(errors="replace"),
        probes=tuple(probes),
        wifi_address=":".join(f"{b:02X}" for b in payload[-DEVICE_INFO_WIFI_LEN:]),
    )


def decode_state(data: bytes, model: BWModel) -> State:
    """Decode the ``ff03`` state bitfield (LSB-first bits)."""
    bits = int.from_bytes(data, "little")

    def bit(n: int) -> bool:
        return bool(bits >> n & 1)

    device = model.state_device_bit
    probes = []
    for idx, probe in enumerate(model.probes):
        base = idx * STATE_PROBE_BITS
        ambient = probe.ambient
        probes.append(
            ProbeState(
                connected=bit(base),
                charging=bit(base + 1),
                food_low_alarm=bit(base + 3),
                food_high_alarm=bit(base + 4),
                food_over_temperature=bit(base + 7) or bit(base + 15),
                food_under_temperature=bit(base + 8),
                pre_alarm=bit(base + 9),
                ambient_over_temperature=ambient and bit(base + 10),
                ambient_under_temperature=ambient and bit(base + 11),
                paired=bit(base + 12),
                low_battery=bit(base + 14),
                ambient_low_alarm=ambient and bit(base + 16),
                ambient_high_alarm=ambient and bit(base + 17),
                signal_interference=model.signal_optimization and bit(base + 22),
                timer_alarm=bit(device + 11 + idx),
                timer_running=bit(device + 15 + idx),
            )
        )
    return State(
        probes=tuple(probes),
        base_charging=bit(device),
        base_over_temperature=bit(device + 19),
        base_under_temperature=bit(device + 20),
        base_low_battery=bit(device + 22),
    )


class INTBWClient:
    """Authenticated settings connection to an INT-31-BW or INT-33-BW base.

    Use as an async context manager; the connection is closed on exit::

        async with INTBWClient(ble_device) as client:
            settings = await client.async_read_settings()
            await client.async_set_volume(2)

    Probes are numbered from 1. The model is taken from the device name unless
    ``model`` is given.
    """

    def __init__(
        self,
        ble_device: BLEDevice,
        model: Model | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        ble_device_callback: Callable[[], BLEDevice] | None = None,
    ) -> None:
        """Initialize the client.

        ``ble_device_callback`` returns the freshest ``BLEDevice`` between
        connection attempts (as with ``establish_connection``).
        """
        model = model or try_parse_model(ble_device.name)
        if model not in BW_MODELS:
            msg = f"Unsupported model: {model or ble_device.name}"
            raise ValueError(msg)
        self.model = model
        self._layout = BW_MODELS[model]
        self._ble_device = ble_device
        self._ble_device_callback = ble_device_callback
        self._timeout = timeout
        self._client: BleakClientWithServiceCache | None = None
        self._pending: dict[tuple[int, bytes], asyncio.Future[bytes]] = {}
        self._lock = asyncio.Lock()

    @property
    def probes(self) -> tuple[BWProbe, ...]:
        """Return the probe layout of this model."""
        return self._layout.probes

    async def __aenter__(self) -> Self:
        """Connect and authenticate."""
        await self.async_connect()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Disconnect."""
        await self.async_disconnect()

    async def async_connect(self) -> None:
        """Connect to the base and pass the authentication handshake."""
        self._client = await establish_connection(
            BleakClientWithServiceCache,
            self._ble_device,
            self._ble_device.name or self._ble_device.address,
            ble_device_callback=self._ble_device_callback,
        )
        try:
            await self._client.start_notify(COMMAND_UUID, self._on_notify)
            challenge = await self._request(
                frame(CMD_AUTH_CHALLENGE), CMD_AUTH_CHALLENGE
            )
            result = await self._request(
                auth_response(challenge, time.time_ns() // 1_000_000),
                CMD_AUTH_RESPONSE,
            )
        except BaseException:
            await self.async_disconnect()
            raise
        if result != b"\x00":
            await self.async_disconnect()
            msg = f"Authentication rejected: {result.hex()}"
            raise INTBWAuthError(msg)

    async def async_disconnect(self) -> None:
        """Disconnect from the base."""
        if (client := self._client) is not None:
            self._client = None
            await client.disconnect()

    def _on_notify(self, _sender: BleakGATTCharacteristic, data: bytearray) -> None:
        for cmd, payload in split_frames(bytes(data)):
            if cmd == CMD_ERROR:
                error = INTBWCommandError(f"Command rejected: {payload.hex()}")
                for (reply_cmd, _), future in self._pending.items():
                    if payload[-1:] in (
                        bytes((reply_cmd,)),
                        bytes((reply_cmd - 1,)),
                    ) and (not future.done()):
                        future.set_exception(error)
                continue
            for (reply_cmd, prefix), future in self._pending.items():
                if (
                    reply_cmd == cmd
                    and payload.startswith(prefix)
                    and not future.done()
                ):
                    future.set_result(payload)
                    break

    def _connected(self) -> BleakClientWithServiceCache:
        if self._client is None:
            msg = "Not connected"
            raise INTBWError(msg)
        return self._client

    def _probe(self, probe: int) -> BWProbe:
        if not 1 <= probe <= len(self.probes):
            msg = f"{self.model} has probes 1-{len(self.probes)}"
            raise ValueError(msg)
        return self.probes[probe - 1]

    async def _request(self, data: bytes, reply_cmd: int, prefix: bytes = b"") -> bytes:
        """Write ``data`` and return the payload of the matching reply."""
        client = self._connected()
        key = (reply_cmd, prefix)
        future: asyncio.Future[bytes] = asyncio.get_running_loop().create_future()
        async with self._lock:
            self._pending[key] = future
            try:
                await client.write_gatt_char(COMMAND_UUID, data, response=False)
                async with asyncio.timeout(self._timeout):
                    return await future
            finally:
                del self._pending[key]

    async def _query(
        self, cmd: int, arg: bytes = b"", prefix: bytes | None = None
    ) -> bytes:
        prefix = arg[:1] if prefix is None else prefix
        return await self._request(frame(cmd + 1, arg), cmd + 1, prefix)

    async def _write(self, cmd: int, payload: bytes, prefix: bytes = b"") -> bytes:
        return await self._request(frame(cmd, payload), cmd + 1, prefix)

    async def _send(self, data: bytes) -> None:
        client = self._connected()
        async with self._lock:
            await client.write_gatt_char(COMMAND_UUID, data, response=False)

    async def async_read_settings(self) -> Settings:
        """Read every setting from the base."""
        unit = await self._query(CMD_UNIT)
        volume = await self._query(CMD_VOLUME)
        repeat = await self._query(CMD_ALARM_REPEAT)
        sleep = await self._query(CMD_AUTO_SLEEP)
        pre_alarm = await self._query(CMD_PRE_ALARM)
        calibration = await self._read_calibration()
        probes = []
        for num, probe in enumerate(self.probes, 1):
            name = await self._query(CMD_NAME, bytes((num + 1,)))
            pre = pre_alarm[num] if len(pre_alarm) > num else 0
            probes.append(
                ProbeSettings(
                    name=name[1:].decode(),
                    calibration=calibration[num - 1],
                    food_target=decode_cook_target(
                        await self._query(CMD_COOK, bytes((food_mask(num),)))
                    ),
                    ambient_target=decode_cook_target(
                        await self._query(CMD_COOK, bytes((ambient_mask(num),)))
                    )
                    if probe.ambient
                    else None,
                    pre_alarm=_c_delta(pre, 1) if pre else None,
                    timer=decode_timer(
                        await self._query(CMD_TIMER, bytes((food_mask(num),)), b"")
                    ),
                )
            )
        return Settings(
            temperature_unit=Units.TEMP_FAHRENHEIT
            if unit[:1] == bytes((UNIT_FAHRENHEIT,))
            else Units.TEMP_CELSIUS,
            brightness=(await self._query(CMD_BRIGHTNESS))[0],
            backlight_timeout=struct.unpack_from(
                "<H", await self._query(CMD_BACKLIGHT)
            )[0],
            volume=0
            if volume[0] == VOLUME_MUTED
            else (volume[1] if volume[1] in (2, 3) else 1),
            alarm_repeat=None
            if repeat[0] == ALARM_ONCE
            else AlarmRepeat(times=repeat[1], interval=repeat[2]),
            auto_sleep=struct.unpack_from("<H", sleep, 1)[0] if sleep[0] else None,
            wifi=(await self._query(CMD_WIFI))[0] in (0x01, 0x03),
            name=(await self._query(CMD_NAME, bytes((NAME_BASE,))))[1:].decode(),
            probes=tuple(probes),
        )

    async def _read_calibration(self) -> tuple[Calibration, ...]:
        payload = await self._query(CMD_CALIBRATION, b"\xff", b"")
        return decode_calibration(payload, self.probes)

    async def async_read_battery(self) -> Battery:
        """Read the base and probe battery levels."""
        data = await self._connected().read_gatt_char(BATTERY_UUID)
        return decode_battery(bytes(data), len(self.probes))

    async def async_read_state(self) -> State:
        """Read the probe, base and alarm state."""
        data = await self._connected().read_gatt_char(STATE_UUID)
        return decode_state(bytes(data), self._layout)

    async def async_read_device_info(self) -> DeviceInfo:
        """Read firmware versions and addresses."""
        payload = await self._query(CMD_DEVICE_INFO)
        if len(payload) < DEVICE_INFO_PROBE_OFFSET + DEVICE_INFO_WIFI_LEN:
            msg = f"Device info reply too short: {payload.hex()}"
            raise INTBWError(msg)
        return decode_device_info(payload, len(self.probes))

    async def async_set_temperature_unit(self, unit: Units) -> None:
        """Set the display unit (``Units.TEMP_CELSIUS`` or ``TEMP_FAHRENHEIT``)."""
        if unit not in (Units.TEMP_CELSIUS, Units.TEMP_FAHRENHEIT):
            msg = f"Unsupported unit: {unit}"
            raise ValueError(msg)
        value = UNIT_FAHRENHEIT if unit is Units.TEMP_FAHRENHEIT else UNIT_CELSIUS
        await self._write(CMD_UNIT, bytes((value,)))

    async def async_set_brightness(self, brightness: int) -> None:
        """Set the display brightness (0-100)."""
        if not 0 <= brightness <= MAX_BRIGHTNESS:
            msg = f"Brightness must be 0-{MAX_BRIGHTNESS}"
            raise ValueError(msg)
        await self._write(CMD_BRIGHTNESS, bytes((brightness,)))

    async def async_set_backlight_timeout(self, seconds: int) -> None:
        """Set how long the display stays lit, in seconds."""
        await self._write(CMD_BACKLIGHT, struct.pack("<H", seconds))

    async def async_set_volume(self, level: int) -> None:
        """Set the buzzer volume (1-3), or 0 to mute."""
        if not 0 <= level <= MAX_VOLUME:
            msg = f"Volume must be 0-{MAX_VOLUME}"
            raise ValueError(msg)
        payload = bytes((VOLUME_MUTED, 0)) if level == 0 else bytes((VOLUME_ON, level))
        await self._write(CMD_VOLUME, payload)

    async def async_set_alarm_repeat(self, repeat: AlarmRepeat | None) -> None:
        """Repeat alarms, or sound them once when ``repeat`` is ``None``."""
        if repeat is None:
            payload = bytes((ALARM_ONCE, 0, 0))
        else:
            if not 1 <= repeat.times <= MAX_ALARM_REPEAT_TIMES:
                msg = f"Repeat times must be 1-{MAX_ALARM_REPEAT_TIMES}"
                raise ValueError(msg)
            if repeat.interval not in ALARM_REPEAT_INTERVALS:
                msg = f"Repeat interval must be one of {ALARM_REPEAT_INTERVALS}"
                raise ValueError(msg)
            payload = bytes((ALARM_REPEAT, repeat.times, repeat.interval))
        await self._write(CMD_ALARM_REPEAT, payload)

    async def async_set_auto_sleep(self, seconds: int | None) -> None:
        """Set the auto-sleep delay in seconds, or ``None`` to disable it."""
        payload = struct.pack("<BH", seconds is not None, seconds or 0)
        await self._write(CMD_AUTO_SLEEP, payload)

    async def async_set_wifi(self, enabled: bool) -> None:
        """Turn the base's Wi-Fi on or off."""
        await self._write(CMD_WIFI, bytes((enabled,)))

    async def async_set_name(self, name: str) -> None:
        """Rename the base."""
        await self._set_name(NAME_BASE, name)

    async def async_set_probe_name(self, probe: int, name: str) -> None:
        """Rename a probe."""
        self._probe(probe)
        await self._set_name(probe + 1, name)

    async def _set_name(self, which: int, name: str) -> None:
        encoded = name.encode()
        if not 0 < len(encoded) <= MAX_NAME_BYTES:
            msg = f"Name must be 1-{MAX_NAME_BYTES} bytes"
            raise ValueError(msg)
        await self._write(CMD_NAME, bytes((which,)) + encoded, bytes((which,)))

    async def async_set_calibration(self, probe: int, calibration: Calibration) -> None:
        """Set a probe's calibration offsets (Celsius)."""
        layout = self._probe(probe)
        if len(calibration.sensors) != layout.sensors or (
            (calibration.ambient is not None) != layout.ambient
        ):
            msg = (
                f"Probe {probe} takes {layout.sensors} sensor offsets"
                f"{' and an ambient offset' if layout.ambient else ''}"
            )
            raise ValueError(msg)
        if any(abs(v) > MAX_FOOD_CALIBRATION_C for v in calibration.sensors) or (
            abs(calibration.ambient or 0) > MAX_AMBIENT_CALIBRATION_C
        ):
            msg = (
                f"Offsets must be within ±{MAX_FOOD_CALIBRATION_C}°C (sensors) "
                f"and ±{MAX_AMBIENT_CALIBRATION_C}°C (ambient)"
            )
            raise ValueError(msg)
        current = list(await self._read_calibration())
        current[probe - 1] = calibration
        values = [
            _f_delta(v, 100)
            for cal in current
            for v in (*cal.sensors, *(() if cal.ambient is None else (cal.ambient,)))
        ]
        await self._write(
            CMD_CALIBRATION,
            struct.pack(f"<B{len(values)}h", food_mask(probe), *values),
        )

    async def async_set_cook(
        self,
        probe: int,
        food: CookTarget | None,
        ambient: CookTarget | None = None,
        pre_alarm: float | None = None,
    ) -> None:
        """Set a probe's cook targets; pass ``None`` for everything to end it.

        ``pre_alarm`` sounds an early warning this many °C before the food
        high target.
        """
        layout = self._probe(probe)
        if ambient is not None and not layout.ambient:
            msg = f"Probe {probe} has no ambient sensor"
            raise ValueError(msg)
        start = int(time.time()) if food or ambient else 0
        pre = bytearray(PRE_ALARM_SLOTS)
        pre[probe - 1] = 0 if pre_alarm is None else _f_delta(pre_alarm, 1)
        data = encode_cook_target(food_mask(probe), food, start)
        if layout.ambient:
            data += encode_cook_target(ambient_mask(probe), ambient, start)
        data += frame(CMD_PRE_ALARM, bytes((food_mask(probe),)) + pre)
        await self._request(data, CMD_PRE_ALARM + 1)

    async def async_set_timer(self, probe: int, seconds: int | None) -> None:
        """Start a countdown of ``seconds``, or a count-up timer when ``None``."""
        self._probe(probe)
        start = int(time.time())
        mask = food_mask(probe)
        if seconds is None:
            payload = struct.pack("<BII", mask | TIMER_COUNT_UP, start, 0)
        else:
            payload = struct.pack("<BII", mask, start, start + seconds)
        await self._write(CMD_TIMER, payload)

    async def async_reset_timer(self, probe: int) -> None:
        """Stop and clear a probe's timer."""
        self._probe(probe)
        await self._write(CMD_TIMER, struct.pack("<BII", food_mask(probe), 0, 0))

    async def async_silence_alarms(self) -> None:
        """Silence every sounding alarm."""
        await self._send(frame(CMD_SILENCE, SILENCE_ALL))

    async def async_sync_time(self) -> None:
        """Set the base clock to the current time."""
        now_ms = time.time_ns() // 1_000_000
        await self._request(
            frame(CMD_TIME_SYNC, struct.pack("<IH", now_ms // 1000, now_ms % 1000)),
            CMD_TIME_SYNC_REPLY,
        )

    async def async_start_signal_optimization(self) -> None:
        """Ask the base to pick a less congested radio channel (INT-31-BW)."""
        if not self._layout.signal_optimization:
            msg = f"{self.model} does not support signal optimization"
            raise INTBWError(msg)
        await self._send(frame(CMD_SIGNAL_OPTIMIZATION, b"\x01"))
