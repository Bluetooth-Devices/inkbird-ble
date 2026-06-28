# CLAUDE.md — inkbird-ble

Guidance for Claude Code when working in this repository.

## Project overview

`inkbird-ble` is a Python library that parses BLE advertisements and GATT
notifications from INKBIRD Bluetooth devices (thermometers, hygrometers, BBQ
probes, air-quality monitors). It is used by the Home Assistant integration.

- **Public API**: `INKBIRDBluetoothDeviceData`, `Model` (both re-exported in
  `__init__.py`)
- **Single source file**: `src/inkbird_ble/parser.py`
- **Tests**: `tests/test_parser.py`

## Git and PR workflow

This repo lives at `Bluetooth-Devices/inkbird-ble` (upstream). The bot account
operates through a fork at `bluetoothbot/inkbird-ble` (origin).

```bash
# Detect upstream
gh repo view --json parent --jq '.parent.owner.login + "/" + .parent.name'
# → Bluetooth-Devices/inkbird-ble

# Create draft PR targeting upstream
git push -u origin koan/<branch>
gh pr create --draft \
  --repo Bluetooth-Devices/inkbird-ble \
  --head bluetoothbot:<branch> \
  --title "..." --body "..."
```

Always branch off local `main` (tracks upstream), **not** `origin/main` (fork,
may be stale).

```bash
git checkout -b koan/<name> main
```

## Commit style

Conventional Commits. The commitlint config enforces `config-conventional`
rules. Subject-case matters: the description after the scope must be
**lowercase**.

```
feat(ibs-th): add humidity plausibility guard
fix(iam-t1): drop corrupt temperature notification
test(iht-2pb): add frame-walker boundary cases
docs: add supported-devices matrix
```

Run `poetry run ruff check .` to validate before committing. The local
`pre-commit` binary is older than the config stage names — use `poetry run
ruff check` directly; CI runs the real checks.

## Architecture: device categories

Every `Model` enum member belongs to exactly **one** of four sets:

| Set                | Description                                                                                                                |
| ------------------ | -------------------------------------------------------------------------------------------------------------------------- |
| `BBQ_MODELS`       | iBBQ-1/2/4/6 — multi-probe BBQ thermometers, adv only                                                                      |
| `SENSOR_MODELS`    | Advertisement-based sensors (9-byte: IBS-TH/TH2; 18-byte: IBS-P02B/ITH-11-B/ITH-13-B/ITH-21-B/GENERIC_18; 17-byte: IAM-T2) |
| `NOTIFY_MODELS`    | GATT notification devices (IAM-T1, IHT-2PB)                                                                                |
| `GATT_POLL_MODELS` | Poll-only via GATT read (INT-11P-B)                                                                                        |

A meta-test enforces this:

```python
assert set(Model) == (BBQ_MODELS | SENSOR_MODELS | NOTIFY_MODELS | GATT_POLL_MODELS)
```

## Architecture: dispatch

Advertisement parsing dispatches through two class-level dicts built **after**
class definition (post-class pattern):

```python
INKBIRDBluetoothDeviceData._device_type_dispatch = {
    **dict.fromkeys(BBQ_MODELS, _update_bbq_model),
    **dict.fromkeys(NINE_BYTE_SENSOR_MODELS, _update_nine_byte_model),
    **dict.fromkeys(EIGHTEEN_BYTE_SENSOR_MODELS, _update_eighteen_byte_model),
    **dict.fromkeys(SEVENTEEN_BYTE_SENSOR_MODELS, _update_seventeen_byte_model),
}

INKBIRDBluetoothDeviceData._notify_dispatch = {
    Model.IAM_T1: _notify_iam_t1,
    Model.IHT_2PB: _notify_iht_2pb,
}
```

GATT poll models share `async_poll` → `_update_int_11p_b_from_raw` (currently
only INT-11P-B; add a dispatch branch if a second poll model arrives).

## Adding a new device model — mandatory checklist

Missing any step results in CI failure or a runtime KeyError on user hardware.

### 1. Add to `Model` enum (StrEnum)

```python
class Model(StrEnum):
    MY_DEVICE = "My-Device"
```

### 2. Add to `MODEL_INFO` dict

```python
Model.MY_DEVICE: ModelInfo(
    name="My-Device",
    model_type=ModelType.SENSOR,        # or BBQ
    local_name="my-device",             # matches BLE local name (lowercase)
    message_length=18,                  # adv payload length; 0 for notify-only
    unpacker=INKBIRD_UNPACK,            # struct.Struct unpack function
    service_uuid=INKBIRD_SERVICE_UUID,
    characteristic_uuid=EIGHTEEN_BYTE_SENSOR_DATA_CHARACTERISTIC_UUID,
    notify_uuid=None,                   # set for NOTIFY_MODELS
    use_local_name_for_device=False,
    parse_adv=True,                     # False for notify/poll-only models
    supports_polling=True,              # False if connecting wedges firmware
    notify_init_writes=(),              # for models needing activation writes
),
```

### 3. Categorise in the right set

The four sets (`BBQ_MODELS`, `SENSOR_MODELS`, `NOTIFY_MODELS`,
`GATT_POLL_MODELS`) are derived automatically from `MODEL_INFO`, **except**
`GATT_POLL_MODELS` which is a hardcoded set. Add poll-only models there.

### 4. Register in the dispatch dicts

For `NOTIFY_MODELS`, add a `_notify_<device>` method and an entry in
`_notify_dispatch`. For `GATT_POLL_MODELS`, add a decode branch in
`async_poll`.

### 5. Detection logic in `_detect_device_type`

Add a name-check or manufacturer-id check in the if/elif chain.
**Important**: models with no `manufacturer_data` (name-only detection) must be
matched **before** the `if not manufacturer_data: return` guard in
`_start_update`. Currently this means adding them before the GATT path —
see the `IHT_2PB` prefix check for the pattern.

### 6. Boundary-net coverage (meta-tests will fail otherwise)

Every `SENSOR_MODELS` member must add a case in:

- `_ADV_HUMIDITY_BOUNDARY_CASES` (if it reports humidity)
- `_ADV_TEMPERATURE_BOUNDARY_CASES`
- `_ADV_BATTERY_BOUNDARY_CASES` (if it reports battery; excludes IAM-T2)

Every `NOTIFY_MODELS` member must add a test name in `_NOTIFY_CORRUPT_INPUT_TESTS`.
The registry key is the test function **name** (resolved via `sys.modules[__name__]`),
so the test must live in `test_parser.py`.

### 7. `supported_devices.md` row

Add a row to `docs/source/supported_devices.md`. The meta-test
`test_all_models_in_supported_devices_doc` checks `m.value in doc_text` for
every `Model` member.

## Boundary-net (plausibility guards)

All raw-byte fields that can overflow on corrupt packets are guarded by
`_is_<field>_plausible()` helpers. On failure, the **whole packet** is dropped
(no partial updates).

| Guard                       | Ceiling    | Scope                                      |
| --------------------------- | ---------- | ------------------------------------------ |
| `_is_humidity_plausible`    | 100%       | All humidity paths                         |
| `_is_temperature_plausible` | ±200 °C    | IAM-T1 notify only (ADV uses signed parse) |
| `_is_battery_plausible`     | 100%       | All battery paths                          |
| `_is_co2_plausible`         | 40 000 ppm | IAM-T1 notify                              |
| `_is_pressure_plausible`    | 1 200 hPa  | IAM-T1 notify                              |

**Do not** apply `_is_temperature_plausible` to BBQ probe or IHT-2PB decoders:

- iBBQ probes spec up to ~300 °C — they'd need a higher ceiling.
- IHT-2PB is a meat/oven probe (legit ≥306 °C); the frame-walker checksum
  already filters garbage.

The 200 °C ceiling is calibrated for indoor ambient sensors only.

## IHT-2PB protocol details

Protocol verified against hardware (firmware VER1.2.0, issue #222).

- Service: `ffe0`, notify char: `ffe4`, write char: `ffe9`
- Two activation writes required to start the temperature stream (second write
  is best-effort — device rejects it but still notifies)
- Frame format: `55 aa <cmd> <len> <payload...> <checksum>`
  where checksum = `sum(preceding bytes) & 0xFF`
- A single notification can coalesce multiple frames (startup burst)
- Commands: 0x02/0x04/0x06 = Celsius probe 1/2/3; F mirrors (0x03/05/07) ignored
- Payload: signed 16-bit big-endian in tenths of a degree
- Unplugged socket → no frame emitted (do NOT use value-range heuristics)
- Walk with `_iter_iht_2pb_frames`; resync 1 byte on bad header/checksum

## Testing patterns

```python
# Async GATT test
@pytest.mark.asyncio
async def test_notify_foo():
    data = INKBIRDBluetoothDeviceData(Model.FOO, update_callback=cb)
    # fire service_info to set name/type
    data.update(make_bluetooth_service_info(...))
    # mock client: read_gatt_char returns battery, start_notify fires payload
    client = AsyncMock()
    client.read_gatt_char.return_value = b"\x64"
    async def start_notify(uuid, cb):
        cb(sender_mock, bytearray(payload))
    client.start_notify.side_effect = start_notify
    with patch("inkbird_ble.parser.establish_connection") as mock_conn:
        mock_conn.return_value.__aenter__.return_value = client
        await asyncio.wait_for(data.async_start(service_info, ble_device), 1.0)
    # assert update_callback called with expected SensorUpdate
```

Use `async_fire_time_changed(hass, delta)` from `tests/__init__.py` to advance
time in asyncio tests.

Avoid Unicode in comments and docstrings inside `parser.py` — ruff RUF002/RUF003
flags the MULTIPLICATION SIGN (×) and EN DASH (–). Use ASCII `x` and `-`.

## Mypy notes

CI runs mypy with `bleak` and `habluetooth` stubs as `Any` — the ~8 "external
library" errors seen in `poetry run mypy` locally **do not appear in CI**. Only
fix errors that reference your own code. Use `if TYPE_CHECKING: assert
self._device_type is not None` (no runtime S101 violation) to narrow
`Model | None` for dict lookups.

## No-adv notify devices (name-only detection)

Some devices (IBT-4WB — open PR #227) advertise with no manufacturer_data, only
a local name. These must be handled before `_start_update`'s
`if not manufacturer_data: return` guard. Pattern:

```python
# In _start_update, BEFORE the manufacturer_data check:
if not manufacturer_data:
    if service_info.name == "iBBQ-4WB":     # exact match, don't use INKBIRD_NAMES
        self._device_type = Model.IBT_4WB
    self._set_name_and_manufacturer(service_info)
    return
```

Scope the match to the exact `local_name` — do not add these to `INKBIRD_NAMES`
(which is used in the SENSOR path where `manufacturer_data` is always present).
