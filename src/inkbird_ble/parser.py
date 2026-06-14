"""Parser for Inkbird BLE advertisements.

This file is shamelessly copied from the following repository:
https://github.com/Ernst79/bleparser/blob/c42ae922e1abed2720c7fac993777e1bd59c0c93/package/bleparser/inkbird.py

MIT License applies.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import struct
from dataclasses import dataclass
from enum import Enum, StrEnum, auto
from functools import lru_cache
from typing import TYPE_CHECKING, Any, ClassVar
from uuid import UUID

from bleak.exc import BleakCharacteristicNotFoundError, BleakError
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection
from bluetooth_data_tools import (
    monotonic_time_coarse,
    short_address,
)
from bluetooth_sensor_state_data import BluetoothData
from sensor_state_data import SensorLibrary, Units

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine, Iterable

    from bleak import BleakGATTCharacteristic, BLEDevice
    from bluetooth_sensor_state_data import SensorUpdate
    from habluetooth import BluetoothServiceInfoBleak


_LOGGER = logging.getLogger(__name__)


class Model(StrEnum):
    IBBQ_1 = "iBBQ-1"
    IBBQ_2 = "iBBQ-2"
    IBBQ_4 = "iBBQ-4"
    IBBQ_6 = "iBBQ-6"
    IBS_TH = "IBS-TH"
    IBS_TH2 = "IBS-TH2"
    IBS_P02B = "IBS-P02B"
    ITH_11_B = "ITH-11-B"
    ITH_13_B = "ITH-13-B"
    ITH_21_B = "ITH-21-B"
    GENERIC_18 = "Generic 18 byte model"
    IAM_T1 = "IAM-T1"
    IAM_T2 = "IAM-T2"
    IHT_2PB = "IHT-2PB"
    INT_11P_B = "INT-11P-B"
    IBT_4WB = "IBT-4WB"


class ModelType(Enum):
    BBQ = auto()
    SENSOR = auto()


@dataclass(frozen=True)
class ModelInfo:
    """Model information."""

    name: str
    model_type: ModelType
    local_name: str | None
    message_length: int
    unpacker: Callable[[bytes], tuple[int, ...]] | None
    service_uuid: UUID | None
    characteristic_uuid: UUID | None
    notify_uuid: UUID | None
    use_local_name_for_device: bool
    parse_adv: bool
    # Commands written after subscribing to notifications to make a device
    # start streaming (each entry is ``(characteristic_uuid, payload)``). Most
    # notify models stream unprompted, so this defaults to empty.
    notify_init_writes: tuple[tuple[UUID, bytes], ...] = ()
    # Whether the device may be refreshed via a connectable GATT poll. Probe
    # thermometers like the IBS-P02B broadcast their full reading in the
    # advertisement and become unstable under active connections — the firmware
    # stops responding until the batteries are pulled — so polling is disabled
    # for them. The advertisement already carries every field a poll would read.
    # See https://github.com/Bluetooth-Devices/inkbird-ble/issues/116
    supports_polling: bool = True


INKBIRD_SERVICE_UUID = UUID("0000fff0-0000-1000-8000-00805f9b34fb")
EIGHTEEN_BYTE_SENSOR_DATA_CHARACTERISTIC_UUID = UUID(
    "0000fff7-0000-1000-8000-00805f9b34fb"
)
NINE_BYTE_SENSOR_DATA_CHARACTERISTIC_UUID = UUID("0000fff2-0000-1000-8000-00805f9b34fb")
IAM_T1_CHARACTERISTIC_UUID = UUID("0000fff4-0000-1000-8000-00805f9b34fb")
IBT_4WB_SERVICE_UUID = UUID("0000ff00-0000-1000-8000-00805f9b34fb")
IBT_4WB_NOTIFY_UUID = UUID("0000ff01-0000-1000-8000-00805f9b34fb")
IBT_4WB_WRITE_UUID = UUID("0000ff02-0000-1000-8000-00805f9b34fb")
IBT_4WB_ACK_UUID = UUID("0000ff03-0000-1000-8000-00805f9b34fb")
IBT_4WB_BATTERY_UUID = UUID("00002a19-0000-1000-8000-00805f9b34fb")
IBT_4WB_NO_PROBE = 0x7FFE
IBT_4WB_DATA_LENGTH = 10

# Commands are 7-byte payloads written to FF02; the device ACKs on FF03.
# Byte 0: command type
# Byte 1: parameter (or probe bitmask for calibration)
# Bytes 2-5: additional parameters
# Byte 6: 0x00 terminator
IBT_4WB_CMD_UNIT_C = b"\x03\x43\x00\x00\x00\x00\x00"  # display °C
IBT_4WB_CMD_UNIT_F = b"\x03\x46\x00\x00\x00\x00\x00"  # display °F
IBT_4WB_CMD_SOUND_ON = b"\x0b\x5a\x00\x00\x00\x00\x00"  # un-mute / beeper on
IBT_4WB_CMD_SOUND_OFF = b"\x0b\x11\x00\x00\x00\x00\x00"  # mute / beeper off
# State-sync: asks the device to ACK with current calibration values.
# Also serves as keepalive -- the Inkbird app sends this after every write.
IBT_4WB_CMD_STATE_SYNC = b"\x0a\x0f\x00\x00\x00\x00\x00"
IBT_4WB_KEEPALIVE_INTERVAL = 3  # seconds between keepalive state-sync writes
IBT_4WB_CALIBRATION_MAX_C = 5.0  # maximum calibration offset in °C

INKBIRD_UNPACK = struct.Struct("<hH").unpack

# IAM-T1 notify packet identifiers
IAM_T1_NOTIFY_DATA_PREFIX = b"\xaa\x01"
IAM_T1_NOTIFY_STATE_PREFIX = b"\xaa\x05"

# IAM-T1 notification packet lengths (header + payload).
IAM_T1_STATE_NOTIFY_LENGTH = 12
IAM_T1_DATA_NOTIFY_LENGTH = 16

# Advertisement message lengths (2-byte manufacturer id prefix + payload).
NINE_BYTE_MESSAGE_LENGTH = 9
SEVENTEEN_BYTE_MESSAGE_LENGTH = 17
EIGHTEEN_BYTE_MESSAGE_LENGTH = 18

# Minimum byte counts a connectable GATT poll read must return before it can be
# decoded. A truncated read (BLE flakiness, a short MTU) would otherwise raise
# struct.error / IndexError while slicing the payload. The nine-byte path
# unpacks payload[0:4]; the eighteen-byte path slices payload[5:9] and indexes
# payload[9]. See ``async_poll``.
NINE_BYTE_POLL_MIN_READ_LEN = 4
EIGHTEEN_BYTE_POLL_MIN_READ_LEN = 10

# Manufacturer-data IDs used to disambiguate models that advertise a generic
# or shared local name. These are the integer keys of the manufacturer_data
# dict (Bluetooth SIG company identifiers). Endianness only matters when the
# key is serialized to its 2-byte wire form, which the code does explicitly
# with int(...).to_bytes(2, "little").
GENERIC_18_MANUFACTURER_ID = 9289
IAM_T1_MANUFACTURER_ID = 12628
IAM_T2_MANUFACTURER_ID = 12884

# IAM-T2 advertises a payload whose MAC bytes start with 00:62.
IAM_T2_MAC_PREFIX = b"\x00\x62"

# IHT-2PB GATT support. This probe thermometer does not broadcast its readings;
# it streams them over notifications on ``fff0/ffe4`` once two activation
# commands are written. The protocol was verified against hardware (firmware
# VER1.2.0) with live GATT captures in
# https://github.com/Bluetooth-Devices/inkbird-ble/issues/222 (reference decoder
# at https://github.com/quittung/iht2pb).
IHT_2PB_SERVICE_UUID = UUID("0000ffe0-0000-1000-8000-00805f9b34fb")
IHT_2PB_NOTIFY_UUID = UUID("0000ffe4-0000-1000-8000-00805f9b34fb")
IHT_2PB_WRITE_UUID = UUID("0000ffe9-0000-1000-8000-00805f9b34fb")
IHT_2PB_INIT_WRITES = (
    (IHT_2PB_WRITE_UUID, b"\x55\xaa\x19\x01\x00\x19"),
    # The second write targets the notify characteristic itself; the device
    # rejects it ("does not allow writing") yet it is required to start the
    # temperature stream, so the write is best-effort (errors are swallowed).
    (IHT_2PB_NOTIFY_UUID, b"\x55\xaa\x1a\x01\x00\x1a"),
)
# A notification carries one or more frames back-to-back, each laid out as
# ``55 aa <command> <length> <payload...> <checksum>`` where <length> counts the
# payload bytes and <checksum> is ``sum(preceding bytes) & 0xFF``. Probe
# temperature frames use commands 0x02/0x04/0x06 (Celsius for probe 1/2/3); the
# payload is a signed 16-bit big-endian value in tenths of a degree Celsius.
IHT_2PB_FRAME_HEADER = b"\x55\xaa"
# Frame byte offsets relative to the header start.
IHT_2PB_HEADER_LEN = 2
IHT_2PB_CMD_OFFSET = 2
IHT_2PB_LEN_OFFSET = 3
IHT_2PB_PAYLOAD_OFFSET = 4
IHT_2PB_FRAME_MIN_LEN = 5  # header(2) + command(1) + length(1) + checksum(1)
IHT_2PB_PROBE_SELECTORS = {0x02: 1, 0x04: 2, 0x06: 3}
IHT_2PB_TEMP_PAYLOAD_LEN = 2
# Probe payload is a signed 16-bit big-endian value in tenths of a degree.
IHT_2PB_TEMP_UNPACK = struct.Struct(">h").unpack

# INT-11P-B GATT support. This connectable BBQ probe carries no readings in its
# advertisement; the values are read from the ``fff1`` characteristic on the
# ``fff0`` service. The byte layout was reverse-engineered by the community
# (https://github.com/Bluetooth-Devices/inkbird-ble/issues/41 and the linked
# Home Assistant forum thread) and is not yet verified against hardware here:
#   [0] header (0xAA)
#   [1] probe (internal) temperature, °C
#   [2] flags (bit 7 = probe charging)
#   [3] ambient temperature, °C (0 means "no ambient reading")
#   [4] probe battery: low 7 bits = percentage, bit 7 = flag
#   [5] case battery: bits 1-7 = percentage (>> 1), bit 0 = case charging
#   [6] unknown
INT_11P_B_DATA_CHARACTERISTIC_UUID = UUID("0000fff1-0000-1000-8000-00805f9b34fb")
INT_11P_B_MIN_READ_LEN = 6
INT_11P_B_PROBE_TEMP_INDEX = 1
INT_11P_B_AMBIENT_TEMP_INDEX = 3
INT_11P_B_PROBE_BATTERY_INDEX = 4
INT_11P_B_CASE_BATTERY_INDEX = 5
INT_11P_B_BATTERY_MASK = 0x7F

MODEL_INFO = {
    Model.IBBQ_1: ModelInfo(
        name="iBBQ-1",
        model_type=ModelType.BBQ,
        local_name=None,
        message_length=12,
        unpacker=struct.Struct("<h").unpack,
        service_uuid=None,
        characteristic_uuid=None,
        notify_uuid=None,
        use_local_name_for_device=True,
        parse_adv=True,
    ),
    Model.IBBQ_2: ModelInfo(
        name="iBBQ-2",
        model_type=ModelType.BBQ,
        local_name=None,
        message_length=14,
        # Signed like the other BBQ models: an unsigned ``<HH`` turns a
        # legitimate sub-zero reading (e.g. -5.0C -> 0xFFCE) into ~6548C, the
        # same #155 wraparound family. Signed parsing keeps the 0xFFFF "no
        # probe" sentinel as -1, which BBQ_PROBE_NOT_CONNECTED still drops.
        unpacker=struct.Struct("<hh").unpack,
        service_uuid=None,
        characteristic_uuid=None,
        notify_uuid=None,
        use_local_name_for_device=True,
        parse_adv=True,
    ),
    Model.IBBQ_4: ModelInfo(
        name="iBBQ-4",
        model_type=ModelType.BBQ,
        local_name=None,
        message_length=18,
        unpacker=struct.Struct("<hhhh").unpack,
        service_uuid=None,
        characteristic_uuid=None,
        notify_uuid=None,
        use_local_name_for_device=True,
        parse_adv=True,
    ),
    Model.IBBQ_6: ModelInfo(
        name="iBBQ-6",
        model_type=ModelType.BBQ,
        local_name=None,
        message_length=22,
        unpacker=struct.Struct("<hhhhhh").unpack,
        service_uuid=None,
        characteristic_uuid=None,
        notify_uuid=None,
        use_local_name_for_device=True,
        parse_adv=True,
    ),
    Model.IBS_TH: ModelInfo(
        name="IBS-TH",
        model_type=ModelType.SENSOR,
        local_name="sps",
        message_length=9,
        unpacker=INKBIRD_UNPACK,
        service_uuid=INKBIRD_SERVICE_UUID,
        characteristic_uuid=NINE_BYTE_SENSOR_DATA_CHARACTERISTIC_UUID,
        notify_uuid=None,
        use_local_name_for_device=False,
        parse_adv=True,
    ),
    Model.IBS_TH2: ModelInfo(
        name="IBS-TH2/P01B",
        model_type=ModelType.SENSOR,
        local_name="tps",
        message_length=9,
        unpacker=INKBIRD_UNPACK,
        service_uuid=INKBIRD_SERVICE_UUID,
        characteristic_uuid=NINE_BYTE_SENSOR_DATA_CHARACTERISTIC_UUID,
        notify_uuid=None,
        use_local_name_for_device=False,
        parse_adv=True,
    ),
    Model.GENERIC_18: ModelInfo(
        name="Unknown 18-byte model",
        model_type=ModelType.SENSOR,
        local_name="unknown",
        message_length=18,
        unpacker=INKBIRD_UNPACK,
        service_uuid=INKBIRD_SERVICE_UUID,
        characteristic_uuid=EIGHTEEN_BYTE_SENSOR_DATA_CHARACTERISTIC_UUID,
        notify_uuid=None,
        use_local_name_for_device=False,
        parse_adv=True,
    ),
    Model.IBS_P02B: ModelInfo(
        name="IBS-P02B",
        model_type=ModelType.SENSOR,
        local_name="ibs-p02b",
        message_length=18,
        unpacker=INKBIRD_UNPACK,
        service_uuid=INKBIRD_SERVICE_UUID,
        characteristic_uuid=EIGHTEEN_BYTE_SENSOR_DATA_CHARACTERISTIC_UUID,
        notify_uuid=None,
        use_local_name_for_device=False,
        parse_adv=True,
        # Advertisement-only: connecting to poll this probe wedges its firmware
        # until a battery reset (#116). Every field is already in the broadcast.
        supports_polling=False,
    ),
    Model.ITH_11_B: ModelInfo(
        name="ITH-11-B",
        model_type=ModelType.SENSOR,
        local_name="ith-11-b",
        message_length=18,
        unpacker=INKBIRD_UNPACK,
        service_uuid=INKBIRD_SERVICE_UUID,
        characteristic_uuid=EIGHTEEN_BYTE_SENSOR_DATA_CHARACTERISTIC_UUID,
        notify_uuid=None,
        use_local_name_for_device=False,
        parse_adv=True,
    ),
    Model.ITH_13_B: ModelInfo(
        name="ITH-13-B",
        model_type=ModelType.SENSOR,
        local_name="ith-13-b",
        message_length=18,
        unpacker=INKBIRD_UNPACK,
        service_uuid=INKBIRD_SERVICE_UUID,
        characteristic_uuid=EIGHTEEN_BYTE_SENSOR_DATA_CHARACTERISTIC_UUID,
        notify_uuid=None,
        use_local_name_for_device=False,
        parse_adv=True,
    ),
    Model.ITH_21_B: ModelInfo(
        name="ITH-21-B",
        model_type=ModelType.SENSOR,
        local_name="ith-21-b",
        message_length=18,
        unpacker=INKBIRD_UNPACK,
        service_uuid=INKBIRD_SERVICE_UUID,
        characteristic_uuid=EIGHTEEN_BYTE_SENSOR_DATA_CHARACTERISTIC_UUID,
        notify_uuid=None,
        use_local_name_for_device=False,
        parse_adv=True,
    ),
    Model.IAM_T1: ModelInfo(
        name="IAM-T1",
        model_type=ModelType.SENSOR,
        local_name="ink@iam-t1",
        message_length=17,
        unpacker=INKBIRD_UNPACK,
        service_uuid=UUID("0000ffe0-0000-1000-8000-00805f9b34fb"),
        characteristic_uuid=None,
        notify_uuid=UUID("0000ffe4-0000-1000-8000-00805f9b34fb"),
        use_local_name_for_device=False,
        parse_adv=False,
    ),
    Model.IAM_T2: ModelInfo(
        name="IAM-T2",
        model_type=ModelType.SENSOR,
        local_name="ink@iam-t2",
        message_length=17,
        unpacker=INKBIRD_UNPACK,
        service_uuid=None,
        characteristic_uuid=None,
        notify_uuid=None,
        use_local_name_for_device=False,
        parse_adv=True,
    ),
    Model.IHT_2PB: ModelInfo(
        name="IHT-2PB",
        model_type=ModelType.SENSOR,
        local_name="ink@iht-2pb",
        # No usable advertisement payload — readings arrive over notifications.
        # message_length=0 keeps it out of the adv length / poll dispatch sets.
        message_length=0,
        unpacker=INKBIRD_UNPACK,
        service_uuid=IHT_2PB_SERVICE_UUID,
        characteristic_uuid=None,
        notify_uuid=IHT_2PB_NOTIFY_UUID,
        use_local_name_for_device=False,
        parse_adv=False,
        notify_init_writes=IHT_2PB_INIT_WRITES,
    ),
    Model.INT_11P_B: ModelInfo(
        name="INT-11P-B",
        model_type=ModelType.SENSOR,
        local_name="int-11p-b",
        # No usable advertisement payload — readings are read from the fff1
        # characteristic. message_length=0 keeps it out of the adv length /
        # passive dispatch sets; polling is enabled via GATT_POLL_MODELS.
        message_length=0,
        unpacker=INKBIRD_UNPACK,
        service_uuid=INKBIRD_SERVICE_UUID,
        characteristic_uuid=INT_11P_B_DATA_CHARACTERISTIC_UUID,
        notify_uuid=None,
        use_local_name_for_device=False,
        parse_adv=False,
    ),
    Model.IBT_4WB: ModelInfo(
        name="IBT-4WB",
        model_type=ModelType.SENSOR,
        local_name="inkbird@ibt-24sph",
        message_length=IBT_4WB_DATA_LENGTH,
        unpacker=None,
        service_uuid=IBT_4WB_SERVICE_UUID,
        characteristic_uuid=None,
        notify_uuid=IBT_4WB_NOTIFY_UUID,
        use_local_name_for_device=False,
        parse_adv=False,
    ),
}

INKBIRD_NAMES = {
    dev_info.local_name: dev_type
    for dev_type, dev_info in MODEL_INFO.items()
    if dev_info.local_name is not None
}

BBQ_MODELS = {
    model_type
    for model_type, model_info in MODEL_INFO.items()
    if model_info.model_type is ModelType.BBQ
}
SENSOR_MSG_LENGTHS = {
    model_info.message_length
    for model_info in MODEL_INFO.values()
    if model_info.model_type is ModelType.SENSOR
}
NINE_BYTE_SENSOR_MODELS = {
    model_type
    for model_type, model_info in MODEL_INFO.items()
    if model_info.model_type is ModelType.SENSOR
    and model_info.message_length == NINE_BYTE_MESSAGE_LENGTH
}
EIGHTEEN_BYTE_SENSOR_MODELS = {
    model_type
    for model_type, model_info in MODEL_INFO.items()
    if model_info.model_type is ModelType.SENSOR
    and model_info.message_length == EIGHTEEN_BYTE_MESSAGE_LENGTH
}
SEVENTEEN_BYTE_SENSOR_MODELS = {
    model_type
    for model_type, model_info in MODEL_INFO.items()
    if model_info.model_type is ModelType.SENSOR
    and model_info.message_length == SEVENTEEN_BYTE_MESSAGE_LENGTH
    and model_info.parse_adv
}
SENSOR_MODELS = {
    *NINE_BYTE_SENSOR_MODELS,
    *EIGHTEEN_BYTE_SENSOR_MODELS,
    *SEVENTEEN_BYTE_SENSOR_MODELS,
}
BBQ_LENGTH_TO_TYPE = {
    model_info.message_length: model_type
    for model_type, model_info in MODEL_INFO.items()
    if model_info.model_type is ModelType.BBQ
}
NOTIFY_MODELS = {
    model_type
    for model_type, model_info in MODEL_INFO.items()
    if model_info.notify_uuid is not None
}
# Connectable probes whose readings are only available via a GATT read of a
# data characteristic (no usable advertisement payload). They are not in the
# length-based SENSOR_MODELS sets, but they must still be polled.
GATT_POLL_MODELS = {Model.INT_11P_B}

MANUFACTURER_DATA_ID_EXCLUDES = {2}

MIN_POLL_INTERVAL = 330.0


async def async_connect_action(
    ble_device: BLEDevice,
    action: Callable[
        [BleakClientWithServiceCache], Coroutine[None, None, bytes | None]
    ],
) -> bytes | None:
    """Connect to the device and read the data characteristic."""
    for attempt in range(2):
        client = await establish_connection(
            BleakClientWithServiceCache,
            ble_device,
            ble_device.name or ble_device.address,
        )
        try:
            return await action(client)
        except BleakCharacteristicNotFoundError:
            if attempt == 0:
                await client.clear_cache()
                continue
            raise
        except BleakError:
            if attempt == 0:
                continue
            raise
        finally:
            await client.disconnect()
    msg = "unreachable"  # pragma: no cover
    raise AssertionError(msg)  # pragma: no cover


@lru_cache
def try_parse_model(value: str | Model | None) -> Model | None:
    """Try to parse the value into a model.

    Return None if parsing fails.
    """
    with contextlib.suppress(ValueError):
        return Model(value)  # type: ignore[arg-type]
    return None


# A BBQ probe that is not plugged in reports 0xFFFF. All BBQ models now use
# signed unpackers, so this surfaces as -1; the unsigned 65535 form is kept
# defensively in case a future model is added with an unsigned unpacker. Either
# way it means "no probe attached" and must be dropped rather than reported as
# a bogus 6553.5°C reading.
BBQ_PROBE_NOT_CONNECTED = frozenset((0xFFFF, -1))

# Inkbird hygrometers occasionally emit a corrupt advertisement where the
# unsigned humidity field is garbage (e.g. 0xFFFF -> 6553.5%) and the
# temperature reads 0. Relative humidity cannot exceed 100%, so a reading
# above this is treated as a corrupt packet and dropped rather than polluting
# the sensor history. See https://github.com/Bluetooth-Devices/inkbird-ble/issues/141
MAX_PLAUSIBLE_HUMIDITY = 100.0

# Companion plausibility ceiling for ambient/indoor-air decoders (currently
# the IAM-T1 notify path). That protocol encodes temperature as an unsigned
# 16-bit value plus a separate sign nibble, so a garbage ``0xFFFF`` field with
# ``sign == 0`` decodes to 6553.5 °C — the same wraparound shape as the
# #155 / #188 / #193 advertisement family, which the signed advertisement
# parsers now block at the source. Notify cannot switch to signed parsing
# without breaking the sign-nibble protocol, so the guard runs here instead:
# any decoded reading whose absolute value exceeds this ceiling marks a
# corrupt packet and is dropped. The ceiling matches the invariant the
# temperature boundary-net test enforces against the advertisement parsers
# (see ``test_adv_temperature_boundary_invariant``).
#
# NOT valid for BBQ probe decoders (iBBQ-1/2/4/6), which spec up to ~300 °C
# and would need their own higher ceiling (e.g.
# ``MAX_PLAUSIBLE_PROBE_TEMPERATURE_CELSIUS``) if a real corruption case ever
# appears there. Today the ADV BBQ decoders are already signed, so applying
# this guard to them would be dead defensive code.
MAX_PLAUSIBLE_AMBIENT_TEMPERATURE_CELSIUS = 200.0

# Battery percentages above 100 are physically impossible. The advertisement
# (9/18-byte) and INT-11P-B poll decoders read battery from a single raw byte,
# so a garbage 0xFF surfaces as 255% (or 127% after the INT-11P-B mask/shift).
# Same shape as the humidity #141 / temperature #155 family: a corrupt field
# marks a corrupt packet, so the whole reading is dropped.
MAX_PLAUSIBLE_BATTERY_PERCENTAGE = 100

# CO2 and atmospheric pressure ceilings for the IAM-T1 notify packet. Both
# fields are decoded as unsigned 16-bit values from raw bytes (data[9:11] and
# data[11:13] respectively); a garbage ``0xFFFF`` field surfaces as 65535 ppm
# or 65535 hPa, the same corrupt-byte shape as the #141 humidity and #155
# temperature families. The ceilings are deliberately lenient — far above any
# real-world reading the sensor can produce — so the guard only catches the
# obvious wraparound, not edge readings near the sensor's range. Indoor-air
# CO2 sensors typically max out around 5000-10000 ppm; industrial range tops
# out near 40000 ppm. Atmospheric pressure ranges from ~870 hPa (cyclone) to
# ~1085 hPa (high-pressure system); 1200 hPa is a generous ceiling. On any
# implausible value the whole packet is dropped rather than publishing a
# bogus reading alongside potentially-corrupt temperature/humidity fields.
MAX_PLAUSIBLE_CO2_PPM = 40000
MAX_PLAUSIBLE_PRESSURE_HPA = 1200


def convert_temperature(temp: float) -> float:
    """Temperature converter.

    Signed BBQ probes can legitimately read below 0°C (e.g. an ambient probe
    in a freezer or a cold smoker). Disconnected probes are dropped upstream
    via ``BBQ_PROBE_NOT_CONNECTED``, so no clamping is needed here — clamping
    sub-zero readings to 0 would corrupt valid data.
    """
    return temp / 10.0


def is_bbq(lower_name: str) -> bool:
    """Check if the device is a BBQ sensor."""
    return bool("xbbq" in lower_name or "ibbq" in lower_name)


class INKBIRDBluetoothDeviceData(BluetoothData):
    """Date update for INKBIRD Bluetooth devices."""

    def __init__(
        self,
        device_type: Model | str | None = None,
        device_data: dict[str, Any] | None = None,
        update_callback: Callable[[SensorUpdate], None] | None = None,
        device_data_changed_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        """Initialize the class."""
        super().__init__()
        self._device_type = try_parse_model(device_type)
        # Last time we got a full update from ADV data
        self._last_full_update = 0.0
        self._notify_task: asyncio.Task[None] | None = None
        self._ibt_4wb_client: BleakClientWithServiceCache | None = None
        self._ibt_4wb_write_lock: asyncio.Lock = asyncio.Lock()
        self._running = True
        self._device_data = device_data.copy() if device_data else {}
        self._update_callback = update_callback
        self._device_data_changed_callback = device_data_changed_callback

    @property
    def uses_notify(self) -> bool:
        """Return True if the device uses notifications."""
        return self._device_type in NOTIFY_MODELS

    async def async_start(
        self, service_info: BluetoothServiceInfoBleak, ble_device: BLEDevice
    ) -> None:
        """Start the device."""
        self._set_name_and_manufacturer(service_info)
        if TYPE_CHECKING:
            assert self._device_type is not None
        self._running = True
        if self._device_type not in NOTIFY_MODELS:
            return
        self._notify_task = asyncio.create_task(self._async_start_notify(ble_device))

    async def async_stop(self) -> None:
        """Stop the device."""
        self._running = False
        if self._notify_task:
            self._notify_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._notify_task
            self._notify_task = None

    async def _async_start_notify(self, ble_device: BLEDevice) -> None:
        """Start the notification loop."""
        while self._running:
            _LOGGER.debug("Starting notification for %s", self.name)
            try:
                await async_connect_action(ble_device, self._async_notify_action)
            except (BleakError, TimeoutError) as err:
                _LOGGER.debug("Error starting notification: %s", str(err) or type(err))
            _LOGGER.debug("Notification loop for %s finished", self.name)
            # Wait for 5 seconds before trying again
            # This is needed to avoid a busy loop if the device is not
            # available
            await asyncio.sleep(5)

    async def _async_notify_action(self, client: BleakClientWithServiceCache) -> None:
        if TYPE_CHECKING:
            assert self._device_type is not None
        dev_info = MODEL_INFO[self._device_type]
        notify_uuid = dev_info.notify_uuid
        loop = asyncio.get_running_loop()
        disconnect_future: asyncio.Future[None] = loop.create_future()

        def _resolve_disconnect_callback(_: BleakClientWithServiceCache) -> None:
            if not disconnect_future.done():
                disconnect_future.set_result(None)

        client.set_disconnected_callback(_resolve_disconnect_callback)
        if self._device_type == Model.IBT_4WB:
            # Read battery before subscribing to notifications so the value is
            # stored and included in the very first temperature SensorUpdate.
            try:
                bat_data = await client.read_gatt_char(IBT_4WB_BATTERY_UUID)
                if bat_data:
                    self.update_predefined_sensor(
                        SensorLibrary.BATTERY__PERCENTAGE, int(bat_data[0])
                    )
            except BleakError as err:
                _LOGGER.debug("IBT-4WB battery read failed: %s", err)
        await client.start_notify(notify_uuid, self._notify_callback)
        for char_uuid, payload in dev_info.notify_init_writes:
            # Some devices (e.g. IHT-2PB) only start streaming after an
            # activation command is written. These writes are best-effort:
            # at least one known device rejects the write yet still begins
            # notifying, so a write error must not abort the session.
            with contextlib.suppress(BleakError):
                await client.write_gatt_char(char_uuid, payload, response=False)
        if self._device_type == Model.IBT_4WB:
            self._ibt_4wb_client = client
            keepalive_task = asyncio.create_task(
                self._async_ibt_4wb_keepalive(client, disconnect_future)
            )
            try:
                await disconnect_future
            finally:
                self._ibt_4wb_client = None
                keepalive_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await keepalive_task
        else:
            await disconnect_future  # wait for disconnect

    async def _async_ibt_4wb_keepalive(
        self,
        client: BleakClientWithServiceCache,
        disconnect_future: asyncio.Future[None],
    ) -> None:
        """Send periodic state-sync writes to FF02 to maintain the BLE link.

        The Inkbird app uses the 0x0A state-sync command as its heartbeat.
        The device ACKs on FF03 with the current calibration values.
        """
        while not disconnect_future.done():
            try:
                async with self._ibt_4wb_write_lock:
                    await client.write_gatt_char(
                        IBT_4WB_WRITE_UUID, IBT_4WB_CMD_STATE_SYNC, response=False
                    )
            except BleakError as err:
                _LOGGER.debug("IBT-4WB keepalive write failed: %s", err)
                break
            await asyncio.sleep(IBT_4WB_KEEPALIVE_INTERVAL)

    def _notify_ibt_4wb(
        self, _sender: BleakGATTCharacteristic, data: bytearray
    ) -> None:
        """Dispatch an IBT-4WB notification to the temperature update handler."""
        if len(data) == IBT_4WB_DATA_LENGTH:
            self._update_ibt_4wb_notify(bytes(data))

    def _update_ibt_4wb_notify(self, data: bytes) -> None:
        """Update IBT-4WB temperature sensors from a 10-byte notification payload.

        The device broadcasts temperatures as Fahrenheit * 10 (signed int16 LE).
        0x7FFE means no probe connected.
        """
        for idx in range(4):
            # A single signed read suffices: 0x7FFE (32766) is positive as
            # both signed and unsigned int16, so the sentinel check is identical.
            raw = struct.unpack_from("<h", data, idx * 2)[0]
            num = idx + 1
            if raw == IBT_4WB_NO_PROBE:
                self.update_predefined_sensor(
                    SensorLibrary.TEMPERATURE__CELSIUS,
                    None,
                    key=f"temperature_probe_{num}",
                    name=f"Temperature Probe {num}",
                )
                continue
            temp_f = raw / 10.0
            temp_c = round((temp_f - 32) * 5 / 9, 1)
            self.update_predefined_sensor(
                SensorLibrary.TEMPERATURE__CELSIUS,
                temp_c,
                key=f"temperature_probe_{num}",
                name=f"Temperature Probe {num}",
            )
        if self._update_callback is None:
            _LOGGER.debug("IBT-4WB: update_callback not set, dropping update")
            return
        self._update_callback(self._finish_update())

    def _notify_callback(
        self, sender: BleakGATTCharacteristic, data: bytearray
    ) -> None:
        """Dispatch a notification to the handler for the current model."""
        _LOGGER.debug("Received notification from %s: %s", sender, data)
        if not self._running:
            return
        handler = self._notify_dispatch.get(self._device_type)
        if handler is not None:
            handler(self, sender, data)

    def _notify_iam_t1(self, sender: BleakGATTCharacteristic, data: bytearray) -> None:
        """Parse an IAM-T1 notification."""
        if (
            len(data) == IAM_T1_STATE_NOTIFY_LENGTH
            and bytes(data[1:3]) == IAM_T1_NOTIFY_STATE_PREFIX
        ):
            in_f = data[10] & 0xF
            unit = Units.TEMP_FAHRENHEIT if in_f else Units.TEMP_CELSIUS
            _LOGGER.debug("IAM-T1 unit: %s (%s)", unit, self._device_data)
            if unit != self._device_data.get("temp_unit"):
                self._device_data["temp_unit"] = unit
                if TYPE_CHECKING:
                    assert self._device_data_changed_callback is not None
                _LOGGER.debug("IAM-T1 unit changed: %s (%s)", unit, self._device_data)
                self._device_data_changed_callback(self._device_data)
        elif (
            len(data) == IAM_T1_DATA_NOTIFY_LENGTH
            and bytes(data[1:3]) == IAM_T1_NOTIFY_DATA_PREFIX
        ):
            sign = data[4] & 0xF
            temp = data[5] << 8 | data[6]
            signed_temp = (temp if sign == 0 else -temp) / 10
            humidity = (data[7] << 8 | data[8]) / 10
            co2 = data[9] << 8 | data[10]
            pressure = data[11] << 8 | data[12]
            if not self._is_humidity_plausible(humidity):
                # A garbage humidity field marks a corrupt notification; drop
                # the whole packet rather than publish any of its fields (#141).
                return
            _LOGGER.debug("IAM-T1 temperature: %s (%s)", signed_temp, self._device_data)
            if self._device_data.get("temp_unit") == Units.TEMP_FAHRENHEIT:
                # Convert to Celsius
                signed_temp = round((signed_temp - 32) * 5 / 9, 2)
            if not self._is_temperature_plausible(signed_temp):
                # Temperature here is unsigned 16-bit + a separate sign
                # nibble, so a garbage ``0xFFFF`` field decodes to ~6553 °C
                # (or ~-6553 with the sign bit set) — the same wraparound
                # shape the signed advertisement parsers now block at the
                # source. Treat it as a corrupt notification and drop the
                # whole packet rather than publish any of its fields.
                return
            if not self._is_co2_plausible(co2) or not self._is_pressure_plausible(
                pressure
            ):
                # CO2 and pressure are unsigned 16-bit fields, so a garbage
                # 0xFFFF surfaces as 65535 ppm / 65535 hPa — the same
                # corrupt-byte shape as the temperature/humidity guards
                # above. Drop the whole packet rather than publish a bogus
                # CO2/pressure reading alongside a temperature/humidity that
                # happens to land in a plausible range by chance.
                return
            self.update_predefined_sensor(
                SensorLibrary.TEMPERATURE__CELSIUS, signed_temp
            )
            self.update_predefined_sensor(SensorLibrary.HUMIDITY__PERCENTAGE, humidity)
            self.update_predefined_sensor(
                SensorLibrary.CO2__CONCENTRATION_PARTS_PER_MILLION,
                co2,
            )
            self.update_predefined_sensor(SensorLibrary.PRESSURE__HPA, pressure)
            if TYPE_CHECKING:
                assert self._update_callback is not None
            self._update_callback(self._finish_update())
        else:
            _LOGGER.debug(
                "Unexpected notification from %s length: %d header: %s",
                sender,
                len(data),
                bytes(data[:3]),
            )

    @staticmethod
    def _iter_iht_2pb_frames(
        data: bytearray,
    ) -> Iterable[tuple[int, bytes]]:
        """Yield ``(command, payload)`` for each checksum-valid frame in ``data``.

        A single notification may bundle several frames back-to-back (e.g. the
        startup config burst arriving coalesced), so the buffer is walked by the
        per-frame ``<length>`` byte and each frame's checksum is verified before
        it is yielded. Frames that fail the header or checksum check are skipped
        and the walk resynchronises one byte at a time.
        """
        index = 0
        length = len(data)
        while index + IHT_2PB_FRAME_MIN_LEN <= length:
            if data[index : index + IHT_2PB_HEADER_LEN] != IHT_2PB_FRAME_HEADER:
                index += 1
                continue
            payload_len = data[index + IHT_2PB_LEN_OFFSET]
            checksum_index = index + IHT_2PB_PAYLOAD_OFFSET + payload_len
            if checksum_index >= length:
                # Declared length overshoots the buffer. A spurious ``55 aa``
                # whose length byte runs long should not abort the walk, so
                # resync one byte (like the bad-header/checksum paths); a
                # genuinely truncated tail frame just runs out and stops.
                index += 1
                continue
            if sum(data[index:checksum_index]) & 0xFF != data[checksum_index]:
                index += 1
                continue
            command = data[index + IHT_2PB_CMD_OFFSET]
            payload = bytes(data[index + IHT_2PB_PAYLOAD_OFFSET : checksum_index])
            yield command, payload
            index = checksum_index + 1

    def _notify_iht_2pb(
        self, _sender: BleakGATTCharacteristic, data: bytearray
    ) -> None:
        """Parse an IHT-2PB notification.

        The notification holds one or more ``55 aa <command> <length>
        <payload...> <checksum>`` frames. Commands 0x02/0x04/0x06 carry a
        Celsius reading for probe 1/2/3; the payload is a signed 16-bit
        big-endian value in tenths of a degree. Other frames (the Fahrenheit
        mirrors, alarm setpoints, connection bitmask) are ignored. An unplugged
        socket simply emits no frame, so there is no value-range heuristic to
        guess at occupancy. Verified against hardware in issue #222.
        """
        emitted = False
        for command, payload in self._iter_iht_2pb_frames(data):
            probe_num = IHT_2PB_PROBE_SELECTORS.get(command)
            if probe_num is None or len(payload) < IHT_2PB_TEMP_PAYLOAD_LEN:
                continue
            temp = IHT_2PB_TEMP_UNPACK(payload[:IHT_2PB_TEMP_PAYLOAD_LEN])[0] / 10
            _LOGGER.debug("IHT-2PB probe %d temperature: %s", probe_num, temp)
            self.update_predefined_sensor(
                SensorLibrary.TEMPERATURE__CELSIUS,
                temp,
                key=f"temperature_probe_{probe_num}",
                name=f"Temperature Probe {probe_num}",
            )
            emitted = True
        if not emitted:
            return
        if TYPE_CHECKING:
            assert self._update_callback is not None
        self._update_callback(self._finish_update())

    _notify_dispatch: ClassVar[
        dict[
            Model | None,
            Callable[
                [INKBIRDBluetoothDeviceData, BleakGATTCharacteristic, bytearray],
                None,
            ],
        ]
    ]

    @property
    def device_type(self) -> Model | None:
        """Return the device type."""
        return self._device_type

    @property
    def name(self) -> str:
        """Return the device name."""
        if (info := self._get_device_info(None)) and info.name:
            return info.name
        return self._device_type.name if self._device_type else "Unknown"

    def _set_name_and_manufacturer(
        self, service_info: BluetoothServiceInfoBleak
    ) -> None:
        if self._device_type is None:
            return
        self.set_device_manufacturer("INKBIRD")
        local_name = service_info.name
        address = service_info.address
        dev_info = MODEL_INFO[self._device_type]
        dev_type_name = dev_info.name
        if dev_info.use_local_name_for_device:
            self.set_device_name(f"{local_name} {short_address(address)}")
            self.set_device_type(f"{local_name[0]}{dev_type_name[1:]}")
        else:
            self.set_device_name(f"{dev_type_name} {short_address(address)}")
            self.set_device_type(dev_type_name)

    def _detect_device_type(
        self,
        service_info: BluetoothServiceInfoBleak,
        manufacturer_data: dict[int, bytes],
        data: bytes,
        msg_length: int,
    ) -> bool:
        """Identify the device type from advertisement data.

        Set ``self._device_type`` and return ``True`` when a known model is
        recognised, or return ``False`` when the advertisement does not match
        any supported device. The branchy match chain keeps this above the
        mccabe threshold; it is a single linear dispatch by design.
        """
        lower_name = service_info.name.lower()
        if (lower_name in INKBIRD_NAMES) and (
            msg_length in SENSOR_MSG_LENGTHS
            or "0000fff0-0000-1000-8000-00805f9b34fb" in service_info.service_uuids
        ):
            self._device_type = INKBIRD_NAMES[lower_name]
        elif lower_name.startswith("ink@iht-2pb"):
            # The IHT-2PB advertises as "Ink@IHT-2PB#<suffix>" and carries
            # no usable payload; identify it by name prefix and let the
            # notify flow (async_start) read its probes over GATT.
            self._device_type = Model.IHT_2PB
        elif is_bbq(lower_name) and msg_length in BBQ_LENGTH_TO_TYPE:
            self._device_type = BBQ_LENGTH_TO_TYPE[msg_length]
        elif (
            msg_length == EIGHTEEN_BYTE_MESSAGE_LENGTH
            and GENERIC_18_MANUFACTURER_ID in manufacturer_data
            and "0000fff0-0000-1000-8000-00805f9b34fb" in service_info.service_uuids
            and manufacturer_data[GENERIC_18_MANUFACTURER_ID].endswith(b"\x00\x00\x00")
        ):
            self._device_type = Model.GENERIC_18
        elif IAM_T1_MANUFACTURER_ID in manufacturer_data and manufacturer_data[
            IAM_T1_MANUFACTURER_ID
        ].startswith(b"AC-6200"):
            # AC-6200
            self._device_type = Model.IAM_T1
        elif (
            msg_length == SEVENTEEN_BYTE_MESSAGE_LENGTH
            and IAM_T2_MANUFACTURER_ID in manufacturer_data
            and data[2:4] == IAM_T2_MAC_PREFIX  # MAC starts with 00:62
        ):
            # IAM-T2
            self._device_type = Model.IAM_T2
        else:
            return False
        return True

    def _start_update(self, service_info: BluetoothServiceInfoBleak) -> None:
        """Update from BLE advertisement data."""
        _LOGGER.debug("Parsing inkbird BLE advertisement data: %s", service_info)
        lower_name = service_info.name.lower()
        if self._device_type is None:
            self._device_type = INKBIRD_NAMES.get(lower_name)
        if not (manufacturer_data := service_info.manufacturer_data):
            self._set_name_and_manufacturer(service_info)
            return
        last_id = list(manufacturer_data)[-1]
        data = int(last_id).to_bytes(2, byteorder="little") + manufacturer_data[last_id]
        msg_length = len(data)
        # If we do not know the device type yet, try to determine it from the
        # advertisement data.
        if self._device_type in (
            None,
            Model.GENERIC_18,
        ) and not self._detect_device_type(
            service_info, manufacturer_data, data, msg_length
        ):
            return
        self._set_name_and_manufacturer(service_info)
        if TYPE_CHECKING:
            assert self._device_type is not None
        if not MODEL_INFO[self._device_type].parse_adv:
            # Device does not support parsing advertisement data
            return
        excludes = MANUFACTURER_DATA_ID_EXCLUDES if len(manufacturer_data) > 1 else None
        changed_manufacturer_data = self.changed_manufacturer_data(
            service_info, excludes
        )
        if not changed_manufacturer_data:
            return
        if service_info.raw is None and len(changed_manufacturer_data) > 1:
            # Without raw advertisement bytes, multiple changed entries are
            # ambiguous (missed packets / new source) so we wait for the
            # next update. When raw is available, changed_manufacturer_data
            # reflects only the current packet, so trust the last entry.
            return
        last_id = list(changed_manufacturer_data)[-1]
        data = (
            int(last_id).to_bytes(2, byteorder="little")
            + changed_manufacturer_data[last_id]
        )

        _LOGGER.debug("Parsing INKBIRD BLE advertisement data: %s", data)
        self._device_type_dispatch[self._device_type](self, data, msg_length)
        self._last_full_update = service_info.time

    def poll_needed(
        self, service_info: BluetoothServiceInfoBleak, last_poll: float | None
    ) -> bool:
        """Return whether the device needs a connectable poll for this update.

        Called every time we get a ``service_info`` for a device, or manually.

        For models that broadcast their readings, the recency check uses
        ``service_info.time`` rather than ``self._last_full_update`` so a
        healthy device whose readings have not changed (and whose repeat
        advertisements are therefore deduplicated before the parser runs) does
        not get marked as needing a connectable poll.

        For poll-only models (``GATT_POLL_MODELS``) the advertisement carries no
        readings, so its freshness is irrelevant; the gate is instead the time
        since the last successful poll (``last_poll`` is the number of seconds
        since the last poll, or ``None`` if the device has never been polled).
        """
        if not self._supports_polling:
            poll_needed = False
        elif self._device_type in GATT_POLL_MODELS:
            poll_needed = last_poll is None or last_poll > MIN_POLL_INTERVAL
        else:
            poll_needed = (
                not self._last_full_update
                or (monotonic_time_coarse() - service_info.time) > MIN_POLL_INTERVAL
            )
        _LOGGER.debug("Poll needed for INKBIRD device %s: %s", self.name, poll_needed)
        return poll_needed

    @property
    def _supports_polling(self) -> bool:
        """Return True if the device supports polling."""
        return self._device_type is not None and (
            (
                self._device_type in SENSOR_MODELS
                and MODEL_INFO[self._device_type].supports_polling
            )
            or self._device_type in GATT_POLL_MODELS
        )

    async def _async_connect_and_read(self, ble_device: BLEDevice) -> bytes:
        """Connect to the device and read the data characteristic."""
        _LOGGER.debug("Polling INKBIRD device %s", self.name)
        # Try to connect to the device and read the data characteristic
        # up to 2 times.
        # If the first attempt fails, clear the cache and try again.
        # This is needed because the cache may contain old data.
        # If the second attempt fails, raise an error.
        data = await async_connect_action(ble_device, self._async_poll_action)
        if TYPE_CHECKING:
            assert data is not None
        return data

    async def _async_poll_action(
        self, client: BleakClientWithServiceCache
    ) -> bytes | None:
        """Poll the device for updates."""
        if TYPE_CHECKING:
            assert self._device_type is not None
        dev_info = MODEL_INFO[self._device_type]
        service = client.services.get_service(dev_info.service_uuid)
        char = service.get_characteristic(dev_info.characteristic_uuid)
        return await client.read_gatt_char(char)

    def _poll_read_too_short(self, payload: bytes, minimum: int) -> bool:
        """Return ``True`` (and log) when a GATT poll read is undersized.

        A device that returns fewer bytes than a decode path needs would
        otherwise crash that path while slicing; callers skip the decode so the
        poll yields no values rather than raising. Mirrors the INT-11P-B guard.
        """
        if len(payload) < minimum:
            _LOGGER.debug(
                "%s poll read too short (%d bytes, need %d): %s",
                self.name,
                len(payload),
                minimum,
                payload,
            )
            return True
        return False

    async def async_poll(self, ble_device: BLEDevice) -> SensorUpdate:
        """Poll the device for updates."""
        payload = await self._async_connect_and_read(ble_device)
        if self._device_type in EIGHTEEN_BYTE_SENSOR_MODELS:
            if not self._poll_read_too_short(payload, EIGHTEEN_BYTE_POLL_MIN_READ_LEN):
                self._update_eighteen_byte_model_from_raw(payload[5:9], payload[9])
        elif self._device_type in NINE_BYTE_SENSOR_MODELS:
            # Battery doesn't seem to be available for these models
            # but it is in the advertisement data
            if not self._poll_read_too_short(payload, NINE_BYTE_POLL_MIN_READ_LEN):
                self._update_nine_byte_model_from_raw(payload[0:4], None)
        elif self._device_type == Model.INT_11P_B:
            self._update_int_11p_b_from_raw(payload)
        return self._finish_update()

    def _update_bbq_model(self, data: bytes, _msg_length: int) -> None:
        """Update a BBQ sensor model."""
        # Some are iBBQ, some are xBBQ
        if TYPE_CHECKING:
            assert self._device_type is not None
        xvalue = data[10:]
        for idx, temp in enumerate(MODEL_INFO[self._device_type].unpacker(xvalue)):
            if temp in BBQ_PROBE_NOT_CONNECTED:
                # Probe not plugged in; skip it instead of reporting 6553.5°C.
                continue
            num = idx + 1
            self.update_predefined_sensor(
                SensorLibrary.TEMPERATURE__CELSIUS,
                convert_temperature(temp),
                key=f"temperature_probe_{num}",
                name=f"Temperature Probe {num}",
            )

    def _update_nine_byte_model(self, data: bytes, _msg_length: int) -> None:
        """Update the sensor values for a 9 byte model."""
        self._update_nine_byte_model_from_raw(data[0:4], data[7])

    def _update_nine_byte_model_from_raw(
        self, temp_hum_bytes: bytes, bat: int | None
    ) -> None:
        if TYPE_CHECKING:
            assert self._device_type is not None
        temp, hum = MODEL_INFO[self._device_type].unpacker(temp_hum_bytes)
        # Only some models report humidity: IBS-TH always, IBS-TH2 when non-zero.
        reports_humidity = self._device_type == Model.IBS_TH or (
            self._device_type == Model.IBS_TH2 and hum != 0
        )
        humidity = hum / 100
        if reports_humidity and not self._is_humidity_plausible(humidity):
            # Humidity is parsed unsigned (``<hH``); a garbage 0xFFFF field
            # surfaces as 655.35%. Like the 18-byte and IAM paths, treat an
            # impossible humidity as a corrupt packet and drop the whole
            # reading rather than publish any of its fields (#141).
            return
        if bat is not None and not self._is_battery_plausible(bat):
            # Garbage battery byte (e.g. 0xFF -> 255%) marks a corrupt packet;
            # drop the whole reading to match the humidity/temperature family.
            return
        self.update_predefined_sensor(SensorLibrary.TEMPERATURE__CELSIUS, temp / 100)
        if reports_humidity:
            self.update_predefined_sensor(SensorLibrary.HUMIDITY__PERCENTAGE, humidity)
        if bat is not None:
            # Battery is only available in the advertisement data
            # for some models
            self.update_predefined_sensor(SensorLibrary.BATTERY__PERCENTAGE, bat)

    def _update_eighteen_byte_model(self, data: bytes, _msg_length: int) -> None:
        """Update the sensor values for a 18 byte model."""
        self._update_eighteen_byte_model_from_raw(data[6:10], data[10])

    def _is_humidity_plausible(self, humidity: float) -> bool:
        """Return ``False`` for a physically impossible humidity reading.

        Relative humidity cannot exceed 100%; a higher value (e.g. a garbage
        ``0xFFFF`` field -> 6553.5%) marks a corrupt packet. Callers drop the
        whole reading rather than let it pollute the sensor history. Shared by
        every humidity-bearing decode path. See #141.
        """
        if humidity > MAX_PLAUSIBLE_HUMIDITY:
            _LOGGER.debug(
                "Ignoring corrupt reading from %s: humidity %.1f%% exceeds 100%%",
                self.name,
                humidity,
            )
            return False
        return True

    def _is_temperature_plausible(self, temperature_c: float) -> bool:
        """Return ``False`` for an ambient temperature outside plausible Celsius range.

        Scoped to **ambient/indoor-air** decoders whose protocol cannot be
        made signed at the source (currently only the IAM-T1 sign-nibble
        notify packet). A garbage 16-bit field there decodes to ~6553 °C,
        the same wraparound the signed advertisement parsers now block —
        this guard catches it on the notify side. Callers drop the whole
        packet rather than publish a temperature outside
        ``MAX_PLAUSIBLE_AMBIENT_TEMPERATURE_CELSIUS``.

        **Not valid for BBQ probe decoders** (iBBQ-1/2/4/6), which spec up
        to ~300 °C — those would need their own higher ceiling if a real
        corruption case ever appears there.
        """
        if abs(temperature_c) > MAX_PLAUSIBLE_AMBIENT_TEMPERATURE_CELSIUS:
            _LOGGER.debug(
                "Ignoring corrupt reading from %s: temperature %.1f °C "
                "exceeds plausible range",
                self.name,
                temperature_c,
            )
            return False
        return True

    def _is_co2_plausible(self, co2_ppm: int) -> bool:
        """Return ``False`` for a CO2 reading outside the plausible range.

        Scoped to the IAM-T1 notify path, whose protocol encodes CO2 as an
        unsigned 16-bit field. A garbage ``0xFFFF`` decodes to 65535 ppm —
        the same wraparound shape as the #141 humidity / #155 temperature
        families. Callers drop the whole packet rather than publish a value
        above ``MAX_PLAUSIBLE_CO2_PPM`` (40000 ppm — well above any indoor
        or industrial sensor's real range).
        """
        if co2_ppm > MAX_PLAUSIBLE_CO2_PPM:
            _LOGGER.debug(
                "Ignoring corrupt reading from %s: CO2 %d ppm exceeds plausible range",
                self.name,
                co2_ppm,
            )
            return False
        return True

    def _is_pressure_plausible(self, pressure_hpa: int) -> bool:
        """Return ``False`` for atmospheric pressure outside the plausible range.

        Scoped to the IAM-T1 notify path, whose protocol encodes pressure as
        an unsigned 16-bit field. A garbage ``0xFFFF`` decodes to 65535 hPa —
        the same corrupt-byte shape as the CO2 / humidity / temperature
        guards. Real atmospheric pressure spans roughly 870-1085 hPa;
        ``MAX_PLAUSIBLE_PRESSURE_HPA`` (1200 hPa) is a generous ceiling that
        still catches the wraparound. Callers drop the whole packet on an
        implausible value.
        """
        if pressure_hpa > MAX_PLAUSIBLE_PRESSURE_HPA:
            _LOGGER.debug(
                "Ignoring corrupt reading from %s: pressure %d hPa "
                "exceeds plausible range",
                self.name,
                pressure_hpa,
            )
            return False
        return True

    def _is_battery_plausible(self, battery: int) -> bool:
        """Return ``False`` for a battery percentage that cannot physically exist.

        Advertisement and poll decoders read battery from a raw byte; a garbage
        0xFF surfaces as 255% (or 127% after INT-11P-B's mask/shift), the same
        corrupt-packet shape as the #141 humidity and #155 temperature families.
        Callers drop the whole reading rather than publish an impossible
        battery alongside potentially-corrupt temperature/humidity fields.
        """
        if battery > MAX_PLAUSIBLE_BATTERY_PERCENTAGE:
            _LOGGER.debug(
                "Ignoring corrupt reading from %s: battery %d%% exceeds 100%%",
                self.name,
                battery,
            )
            return False
        return True

    def _update_eighteen_byte_model_from_raw(
        self, temp_hum_bytes: bytes, bat: int
    ) -> None:
        """Update the sensor values for a 18 byte model."""
        if TYPE_CHECKING:
            assert self._device_type is not None
        temp, hum = MODEL_INFO[self._device_type].unpacker(temp_hum_bytes)
        humidity = hum / 10
        if not self._is_humidity_plausible(humidity):
            return
        if not self._is_battery_plausible(bat):
            # Garbage battery byte (e.g. 0xFF -> 255%) marks a corrupt packet;
            # drop the whole reading to match the humidity/temperature family.
            return
        self.update_predefined_sensor(SensorLibrary.TEMPERATURE__CELSIUS, temp / 10)
        self.update_predefined_sensor(SensorLibrary.BATTERY__PERCENTAGE, bat)
        if hum != 0:
            self.update_predefined_sensor(SensorLibrary.HUMIDITY__PERCENTAGE, humidity)

    def _update_seventeen_byte_model(self, data: bytes, _msg_length: int) -> None:
        """Update the sensor values for 17-byte sensor models (IAM-T2)."""
        # Data format is 17 bytes total: a 2-byte manufacturer ID followed by
        # a 15-byte payload laid out as 6 bytes of MAC, 1 unknown byte, 1
        # status byte, then 2 bytes each of temperature, humidity and CO2, and
        # finally 1 battery byte.

        # Parse status byte
        status = data[9]

        # Parse sensor values (all big-endian). Temperature is signed: sub-zero
        # readings arrive as two's-complement (e.g. -5.0C -> 0xFFCE). Parsing it
        # unsigned reports ~6553C for any negative temperature (see #155 family).
        temperature_raw = int.from_bytes(data[10:12], "big", signed=True)
        humidity = ((data[12] << 8) | data[13]) / 10.0
        co2 = (data[14] << 8) | data[15]

        # Temperature is in tenths of degrees
        if status & 0x02:  # Fahrenheit mode
            temperature_f = temperature_raw / 10.0
            temperature_c = (temperature_f - 32) * 5 / 9
        else:  # Celsius mode
            temperature_c = temperature_raw / 10.0

        # Battery is intentionally not reported: its encoding is unconfirmed
        # (one device reported a raw value of 145 for 75%), so it is omitted
        # rather than published incorrectly.

        if not self._is_humidity_plausible(humidity):
            # A garbage humidity field marks a corrupt advertisement; drop the
            # whole reading rather than publish any of its fields (#141).
            return

        self.update_predefined_sensor(SensorLibrary.TEMPERATURE__CELSIUS, temperature_c)
        self.update_predefined_sensor(SensorLibrary.HUMIDITY__PERCENTAGE, humidity)
        self.update_predefined_sensor(
            SensorLibrary.CO2__CONCENTRATION_PARTS_PER_MILLION, co2
        )

    def _update_int_11p_b_from_raw(self, payload: bytes) -> None:
        """Update the sensor values for an INT-11P-B GATT read.

        The probe exposes a small fixed-layout buffer on its ``fff1``
        characteristic instead of broadcasting readings. Decoding follows the
        community reverse-engineering referenced from issue #41.
        """
        if len(payload) < INT_11P_B_MIN_READ_LEN:
            _LOGGER.debug(
                "INT-11P-B read too short (%d bytes): %s", len(payload), payload
            )
            return
        probe_battery = payload[INT_11P_B_PROBE_BATTERY_INDEX] & INT_11P_B_BATTERY_MASK
        case_battery = payload[INT_11P_B_CASE_BATTERY_INDEX] >> 1
        if not self._is_battery_plausible(
            probe_battery
        ) or not self._is_battery_plausible(case_battery):
            # The 7-bit mask / >>1 shift caps these at 127 — still impossible.
            # A garbage byte here marks a corrupt read; drop the whole packet
            # to match the humidity/temperature corrupt-input family.
            return
        self.update_predefined_sensor(
            SensorLibrary.TEMPERATURE__CELSIUS,
            payload[INT_11P_B_PROBE_TEMP_INDEX],
            key="temperature_probe",
            name="Probe Temperature",
        )
        ambient_temp = payload[INT_11P_B_AMBIENT_TEMP_INDEX]
        if ambient_temp:
            # An ambient reading of 0 means the probe is not reporting an
            # ambient value (the community config filters it out), so skip it.
            self.update_predefined_sensor(
                SensorLibrary.TEMPERATURE__CELSIUS,
                ambient_temp,
                key="temperature_ambient",
                name="Ambient Temperature",
            )
        self.update_predefined_sensor(
            SensorLibrary.BATTERY__PERCENTAGE,
            probe_battery,
            key="probe_battery",
            name="Probe Battery",
        )
        self.update_predefined_sensor(
            SensorLibrary.BATTERY__PERCENTAGE,
            case_battery,
            key="case_battery",
            name="Case Battery",
        )

    # ------------------------------------------------------------------
    # IBT-4WB write commands
    # ------------------------------------------------------------------

    async def async_ibt_4wb_set_temperature_unit(
        self, ble_device: BLEDevice, celsius: bool
    ) -> None:
        """Set the temperature display unit on the IBT-4WB.

        Note: the device always transmits temperatures internally as
        Fahrenheit * 10; this command only changes what the device's
        own screen displays.
        """
        cmd = IBT_4WB_CMD_UNIT_C if celsius else IBT_4WB_CMD_UNIT_F
        await self._async_ibt_4wb_write(ble_device, cmd)

    async def async_ibt_4wb_set_sound_enabled(
        self, ble_device: BLEDevice, enabled: bool
    ) -> None:
        """Enable or disable the IBT-4WB beeper / alarm sound."""
        cmd = IBT_4WB_CMD_SOUND_ON if enabled else IBT_4WB_CMD_SOUND_OFF
        await self._async_ibt_4wb_write(ble_device, cmd)

    async def async_ibt_4wb_set_brightness(
        self, ble_device: BLEDevice, level: int
    ) -> None:
        """Set the IBT-4WB screen brightness (0-100 %).

        The device accepts values 0-100 decimal in byte 1.
        In practice the Inkbird app clips the minimum to 4.
        """
        level = max(0, min(100, level))
        cmd = bytes([0x05, level, 0x00, 0x00, 0x00, 0x00, 0x00])
        await self._async_ibt_4wb_write(ble_device, cmd)

    async def async_ibt_4wb_set_calibration(
        self,
        ble_device: BLEDevice,
        offsets_celsius: dict[int, float],
    ) -> None:
        """Set per-probe temperature calibration offsets (in °C).

        ``offsets_celsius`` maps probe number (1-4) to offset in °C.
        Offsets are converted to the device's native 0.1 °F unit using
        ``int(celsius * 9/5 * 10)`` (truncation toward zero, matching
        the Inkbird app's behaviour).

        Example::

            await data.async_ibt_4wb_set_calibration(
                ble_device, {1: -0.1, 2: 0.0, 3: 0.5}
            )
        """
        if not offsets_celsius:
            return
        probe_to_bit = {1: 0x01, 2: 0x02, 3: 0x04, 4: 0x08}
        mask = 0
        cal: list[int] = [0, 0, 0, 0]  # indices 0-3 -> probes 1-4
        for probe_num, offset_c in offsets_celsius.items():
            if probe_num not in probe_to_bit:
                msg = f"probe_num must be 1-4, got {probe_num!r}"
                raise ValueError(msg)
            lo, hi = -IBT_4WB_CALIBRATION_MAX_C, IBT_4WB_CALIBRATION_MAX_C
            if not (lo <= offset_c <= hi):
                msg = (
                    f"offset_c must be in"
                    f" -{IBT_4WB_CALIBRATION_MAX_C}..+{IBT_4WB_CALIBRATION_MAX_C} C,"
                    f" got {offset_c!r}"
                )
                raise ValueError(msg)
            mask |= probe_to_bit[probe_num]
            # Convert °C offset -> 0.1 °F units, truncate toward zero
            raw = int(offset_c * 9 / 5 * 10)
            cal[probe_num - 1] = raw & 0xFF  # to unsigned byte
        cmd = bytes([0x09, mask, cal[0], cal[1], cal[2], cal[3], 0x00])
        await self._async_ibt_4wb_write(ble_device, cmd)

    async def _async_ibt_4wb_write(self, ble_device: BLEDevice, cmd: bytes) -> None:
        """Write a command to FF02 then send the state-sync to get an ACK.

        Reuses the persistent keepalive connection if it is still active to
        avoid triggering an ``InProgress`` error from BlueZ when a second
        connection attempt is made while the keepalive loop is running.
        """
        if self._ibt_4wb_client and self._ibt_4wb_client.is_connected:
            async with self._ibt_4wb_write_lock:
                await self._ibt_4wb_client.write_gatt_char(
                    IBT_4WB_WRITE_UUID, cmd, response=True
                )
                await self._ibt_4wb_client.write_gatt_char(
                    IBT_4WB_WRITE_UUID, IBT_4WB_CMD_STATE_SYNC, response=True
                )
            return

        async def _action(client: BleakClientWithServiceCache) -> bytes | None:
            await client.write_gatt_char(IBT_4WB_WRITE_UUID, cmd, response=True)
            await client.write_gatt_char(
                IBT_4WB_WRITE_UUID, IBT_4WB_CMD_STATE_SYNC, response=True
            )
            return None

        await async_connect_action(ble_device, _action)

    _device_type_dispatch: ClassVar[
        dict[Model, Callable[[INKBIRDBluetoothDeviceData, bytes, int], None]]
    ]


INKBIRDBluetoothDeviceData._device_type_dispatch = {  # noqa: SLF001
    **dict.fromkeys(
        BBQ_MODELS,
        INKBIRDBluetoothDeviceData._update_bbq_model,  # noqa: SLF001
    ),
    **dict.fromkeys(
        NINE_BYTE_SENSOR_MODELS,
        INKBIRDBluetoothDeviceData._update_nine_byte_model,  # noqa: SLF001
    ),
    **dict.fromkeys(
        EIGHTEEN_BYTE_SENSOR_MODELS,
        INKBIRDBluetoothDeviceData._update_eighteen_byte_model,  # noqa: SLF001
    ),
    **dict.fromkeys(
        SEVENTEEN_BYTE_SENSOR_MODELS,
        INKBIRDBluetoothDeviceData._update_seventeen_byte_model,  # noqa: SLF001
    ),
}

INKBIRDBluetoothDeviceData._notify_dispatch = {  # noqa: SLF001
    Model.IAM_T1: INKBIRDBluetoothDeviceData._notify_iam_t1,  # noqa: SLF001
    Model.IHT_2PB: INKBIRDBluetoothDeviceData._notify_iht_2pb,  # noqa: SLF001
    Model.IBT_4WB: INKBIRDBluetoothDeviceData._notify_ibt_4wb,  # noqa: SLF001
}
