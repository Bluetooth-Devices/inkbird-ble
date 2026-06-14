# Supported devices

`inkbird-ble` recognises the following INKBIRD models. Each one is exposed as a
member of the `Model` enum (importable from `inkbird_ble`); pass it to
`INKBIRDBluetoothDeviceData(...)` when you know the model up front, otherwise
the parser detects it from the first advertisement (passive devices) or you
must supply it (notify-only devices).

| Model                   | Family                  | Transport          | Detection                          | Sensors                                                             |
| ----------------------- | ----------------------- | ------------------ | ---------------------------------- | ------------------------------------------------------------------- |
| `IBS-TH`                | Hygrometer              | advertisement      | local name `sps`                   | temperature, humidity, battery                                      |
| `IBS-TH2` / `P01B`      | Hygrometer              | advertisement      | local name `tps`                   | temperature, humidity, battery                                      |
| `IBS-P02B`              | Pool / probe            | advertisement only | local name `ibs-p02b`              | temperature, battery                                                |
| `ITH-11-B`              | Hygrometer              | advertisement      | local name `ith-11-b`              | temperature, humidity, battery                                      |
| `ITH-13-B`              | Hygrometer              | advertisement      | local name `ith-13-b`              | temperature, humidity, battery                                      |
| `ITH-21-B`              | Hygrometer              | advertisement      | local name `ith-21-b`              | temperature, humidity, battery                                      |
| `IAM-T1`                | Indoor air quality      | GATT notify        | manufacturer-data `AC-6200` prefix | temperature, humidity, CO₂, atmospheric pressure                    |
| `IAM-T2`                | Indoor air quality      | advertisement      | 17-byte payload + MAC prefix       | temperature, humidity, CO₂                                          |
| `IHT-2PB`               | 3-probe thermometer     | GATT notify        | local name `Ink@IHT-2PB#…`         | temperature × 3 probes                                              |
| `INT-11P-B`             | Connected BBQ probe     | GATT poll          | local name `int-11p-b`             | probe temperature, ambient temperature, probe battery, case battery |
| `IBT-4WB`               | 4-probe BBQ thermometer | GATT notify        | local name `Inkbird@IBT-24SPH`     | temperature × 4 probes, battery                                     |
| `IDT-34c-B`             | 4-probe BBQ thermometer | GATT notify        | local name `IDT-34c-B`             | temperature × 4 probes, battery                                     |
| `iBBQ-1`                | BBQ probe (1 channel)   | advertisement      | name contains `xbbq` / `ibbq`      | temperature × 1                                                     |
| `iBBQ-2`                | BBQ probe (2 channel)   | advertisement      | name contains `xbbq` / `ibbq`      | temperature × 2                                                     |
| `iBBQ-4`                | BBQ probe (4 channel)   | advertisement      | name contains `xbbq` / `ibbq`      | temperature × 4                                                     |
| `iBBQ-6`                | BBQ probe (6 channel)   | advertisement      | name contains `xbbq` / `ibbq`      | temperature × 6                                                     |
| `Generic 18 byte model` | Unknown hygrometer      | advertisement      | 18-byte payload + service UUID     | temperature, humidity, battery                                      |

## Transport guide

- **advertisement** — passive: feed every `service_info` to
  `INKBIRDBluetoothDeviceData.update()` and it returns a `SensorUpdate`. No
  connection is opened. The `IBS-TH` family, the eighteen-byte hygrometers and
  the iBBQ probes work this way; `IAM-T2` is advertisement-only as well.
- **advertisement only** — the device cannot be polled or notified safely
  (`IBS-P02B` wedges its firmware until a battery reset if you open a GATT
  connection, see issue [#116]). All fields are already in the broadcast.
- **GATT poll** — the device exposes a readable characteristic; call
  `async_poll(ble_device)` when `poll_needed()` returns true. `INT-11P-B`
  carries _no_ readings in its advertisement, so it must be polled.
- **GATT notify** — the device pushes readings over a notify characteristic;
  call `async_start(service_info, ble_device)` to subscribe. `IAM-T1`,
  `IHT-2PB`, `IBT-4WB` and `IDT-34c-B` use this transport. `IHT-2PB`
  additionally requires two activation writes (handled transparently) before it
  starts streaming. `IBT-4WB` keeps the connection alive with a periodic
  state-sync write and exposes optional control commands
  (`async_ibt_4wb_set_temperature_unit`, `async_ibt_4wb_set_sound_enabled`,
  `async_ibt_4wb_set_brightness`, `async_ibt_4wb_set_calibration`); its probe
  temperatures are transmitted in Fahrenheit and converted to Celsius, and an
  unplugged probe is published as `None`. `IDT-34c-B` is a 4-probe sibling that
  shares the same notify protocol (the same decode and keepalive); its support
  was derived from community reverse-engineering pending confirmation against
  hardware (see issue [#230]).

## Not supported

A few INKBIRD product lines that come up in the issue tracker are out of
scope for this library:

- **Sous-vide cookers** (`ISV-100W`, `ISV-100W 2.0`, `ISV-200W`, `ISV-300W`,
  `ISV-101W`). These are **Wi-Fi / Tuya** devices, not BLE, so they cannot be
  parsed here.

If you have a device that looks like it should work but is not detected,
open an issue with a BLE advertisement capture (e.g. from `bluetoothctl` or
`nrfConnect`) so the model can be reverse-engineered.

[#116]: https://github.com/Bluetooth-Devices/inkbird-ble/issues/116
[#230]: https://github.com/Bluetooth-Devices/inkbird-ble/issues/230
