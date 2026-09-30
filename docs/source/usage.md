# Usage

See [Supported devices](supported_devices.md) for the full list of recognised
models and the transport (advertisement / poll / notify) each one uses.

`inkbird-ble` turns the BLE advertisements (and, for some models, GATT
notifications/reads) emitted by INKBIRD devices into structured sensor values.
It is built on top of
[`bluetooth-sensor-state-data`](https://github.com/Bluetooth-Devices/bluetooth-sensor-state-data)
and is the parser used by the Home Assistant INKBIRD integration, but it can be
used on its own.

The entry point is the `INKBIRDBluetoothDeviceData` class:

```python
from inkbird_ble import INKBIRDBluetoothDeviceData
```

## Passive devices (advertisement only)

Most INKBIRD sensors (the `IBS-TH`, `IBS-TH2`, `ITH-*-B`, `iBBQ-*` and `IAM-T2`
families) broadcast their readings in the BLE advertisement, so no connection is
required. Feed each advertisement to `update()` and you get a `SensorUpdate`
back:

```python
from inkbird_ble import INKBIRDBluetoothDeviceData

# `service_info` is a habluetooth `BluetoothServiceInfoBleak`. Inside Home
# Assistant you receive one for every advertisement; standalone you can build
# one from a Bleak scan (see below).
data = INKBIRDBluetoothDeviceData()

if data.supported(service_info):
    update = data.update(service_info)
    print(data.device_type)   # e.g. Model.IBS_TH
    print(update.entity_values)
```

`update()` returns a `SensorUpdate` whose `entity_values` maps each
`DeviceKey` to a `SensorValue` (temperature in °C, humidity in %, battery in %,
signal strength in dBm, …):

```python
for device_key, sensor_value in update.entity_values.items():
    print(device_key.key, sensor_value.native_value)
# temperature 20.44
# humidity 48.07
# battery 86
# signal_strength -60
```

### What is the integer key in `manufacturer_data`?

A `BluetoothServiceInfoBleak` exposes `manufacturer_data` as a
`dict[int, bytes]`. The integer key is the **Bluetooth SIG company identifier**
advertised by the device — it is _not_ a temperature or a value you need to
decode yourself. You never index into `manufacturer_data` manually; pass the
whole `service_info` to `update()` and the parser selects the right model and
payload for you.

If your device firmware also exposes the raw advertisement bytes, populate the
`raw` field of the `BluetoothServiceInfoBleak` — when present, the parser
prefers it over `manufacturer_data`, which avoids a class of misreads.

## Active devices (connect, read or subscribe)

A few models do not put everything in the advertisement and must be polled or
subscribed to over a GATT connection. `inkbird-ble` handles the connection for
you via [Bleak](https://github.com/hbldh/bleak); you only supply a `BLEDevice`.

If you know the model up front, pass it to the constructor (otherwise it is
detected from the first advertisement):

```python
from inkbird_ble import INKBIRDBluetoothDeviceData

data = INKBIRDBluetoothDeviceData("IBS-TH")
data.supported(service_info)  # also sets the device type
```

### Polling models

For models that expose their data through a readable characteristic, check
`poll_needed()` and call `async_poll()` with a `BLEDevice`:

```python
if data.poll_needed(service_info, last_poll=None):
    update = await data.async_poll(ble_device)
    print(update.entity_values)
```

`poll_needed()` rate-limits itself, so it is safe to call on every
advertisement; it only returns `True` when a fresh read is actually due.

The `INT-11P-B` BBQ probe is a polling model that carries no readings in its
advertisement at all — it is detected by name and read over GATT. A poll yields
its probe and ambient temperatures (`temperature_probe`, `temperature_ambient`)
and its probe and case battery levels (`probe_battery`, `case_battery`).

### Notify models

Some models (for example the `IAM-T1` and the `IHT-2PB` probe thermometer) push
readings over GATT notifications. Start a notification session and receive
updates through callbacks:

```python
def on_update(update):
    print(update.entity_values)

def on_device_data_changed(device_data):
    # e.g. the device's temperature unit changed
    print(device_data)

data = INKBIRDBluetoothDeviceData(
    "IAM-T1",
    update_callback=on_update,
    device_data_changed_callback=on_device_data_changed,
)

await data.async_start(service_info, ble_device)
# ... receive callbacks while connected ...
await data.async_stop()
```

Use the `uses_notify` property to tell the two active styles apart:

```python
if data.uses_notify:
    await data.async_start(service_info, ble_device)
elif data.poll_needed(service_info, last_poll=None):
    await data.async_poll(ble_device)
```

## Building a `BluetoothServiceInfoBleak` outside Home Assistant

When you are not running inside Home Assistant you can construct the
`service_info` yourself from a Bleak scan result:

```python
from habluetooth import BluetoothServiceInfoBleak

service_info = BluetoothServiceInfoBleak(
    name=device.name,
    address=device.address,
    rssi=advertisement_data.rssi,
    manufacturer_data=advertisement_data.manufacturer_data,
    service_data=advertisement_data.service_data,
    service_uuids=advertisement_data.service_uuids,
    source="local",
    device=device,
    advertisement=advertisement_data,
    connectable=True,
    time=0,
    tx_power=advertisement_data.tx_power or 0,
    raw=None,
)
```

`device` and `advertisement_data` are the `BLEDevice` and `AdvertisementData`
objects yielded by `bleak.BleakScanner`.
