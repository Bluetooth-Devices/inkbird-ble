from bluetooth_sensor_state_data import BluetoothServiceInfo, DeviceClass, SensorUpdate
from sensor_state_data import (
    DeviceKey,
    SensorDescription,
    SensorDeviceInfo,
    SensorValue,
    Units,
)

from inkbird_ble.parser import INKBIRDBluetoothDeviceData


def test_can_create():
    INKBIRDBluetoothDeviceData()


def test_sps():
    parser = INKBIRDBluetoothDeviceData()
    service_info = BluetoothServiceInfo(
        name="sps",
        manufacturer_data={2044: b"\xc7\x12\x00\xc8=V\x06"},
        service_uuids=["0000fff0-0000-1000-8000-00805f9b34fb"],
        address="aa:bb:cc:dd:ee:ff",
        rssi=-60,
        service_data={},
        source="local",
    )
    result = parser.update(service_info)
    assert result == SensorUpdate(
        title=None,
        devices={
            None: SensorDeviceInfo(
                name="IBS-TH EEFF",
                model="IBS-TH",
                manufacturer="INKBIRD",
                sw_version=None,
                hw_version=None,
            )
        },
        entity_descriptions={
            DeviceKey(key="battery", device_id=None): SensorDescription(
                device_key=DeviceKey(key="battery", device_id=None),
                device_class=DeviceClass.BATTERY,
                native_unit_of_measurement=Units.PERCENTAGE,
            ),
            DeviceKey(key="signal_strength", device_id=None): SensorDescription(
                device_key=DeviceKey(key="signal_strength", device_id=None),
                device_class=DeviceClass.SIGNAL_STRENGTH,
                native_unit_of_measurement=Units.SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
            ),
            DeviceKey(key="temperature", device_id=None): SensorDescription(
                device_key=DeviceKey(key="temperature", device_id=None),
                device_class=DeviceClass.TEMPERATURE,
                native_unit_of_measurement=Units.TEMP_CELSIUS,
            ),
            DeviceKey(key="humidity", device_id=None): SensorDescription(
                device_key=DeviceKey(key="humidity", device_id=None),
                device_class=DeviceClass.HUMIDITY,
                native_unit_of_measurement=Units.PERCENTAGE,
            ),
        },
        entity_values={
            DeviceKey(key="battery", device_id=None): SensorValue(
                device_key=DeviceKey(key="battery", device_id=None),
                native_value=86,
                name="Battery",
            ),
            DeviceKey(key="signal_strength", device_id=None): SensorValue(
                device_key=DeviceKey(key="signal_strength", device_id=None),
                name="Signal Strength",
                native_value=-60,
            ),
            DeviceKey(key="temperature", device_id=None): SensorValue(
                device_key=DeviceKey(key="temperature", device_id=None),
                name="Temperature",
                native_value=20.44,
            ),
            DeviceKey(key="humidity", device_id=None): SensorValue(
                device_key=DeviceKey(key="humidity", device_id=None),
                native_value=48.07,
                name="Humidity",
            ),
        },
    )


def test_ibbq_4():
    parser = INKBIRDBluetoothDeviceData()
    service_info = BluetoothServiceInfo(
        name="iBBQ",
        manufacturer_data={
            0: b"\x00\x000\xe2\x83}\xb5\x02\x04\x01\xfa\x00\x04\x01\xfa\x00"
        },
        service_uuids=["0000fff0-0000-1000-8000-00805f9b34fb"],
        address="aa:bb:cc:dd:ee:ff",
        rssi=-60,
        service_data={},
        source="local",
    )
    result = parser.update(service_info)
    assert result == SensorUpdate(
        title=None,
        devices={
            None: SensorDeviceInfo(
                name="iBBQ EEFF",
                model="iBBQ-4",
                manufacturer="INKBIRD",
                sw_version=None,
                hw_version=None,
            )
        },
        entity_descriptions={
            DeviceKey(key="signal_strength", device_id=None): SensorDescription(
                device_key=DeviceKey(key="signal_strength", device_id=None),
                device_class=DeviceClass.SIGNAL_STRENGTH,
                native_unit_of_measurement=Units.SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
            ),
            DeviceKey(key="temperature_probe_1", device_id=None): SensorDescription(
                device_key=DeviceKey(key="temperature_probe_1", device_id=None),
                device_class=DeviceClass.TEMPERATURE,
                native_unit_of_measurement=Units.TEMP_CELSIUS,
            ),
            DeviceKey(key="temperature_probe_2", device_id=None): SensorDescription(
                device_key=DeviceKey(key="temperature_probe_2", device_id=None),
                device_class=DeviceClass.TEMPERATURE,
                native_unit_of_measurement=Units.TEMP_CELSIUS,
            ),
            DeviceKey(key="temperature_probe_3", device_id=None): SensorDescription(
                device_key=DeviceKey(key="temperature_probe_3", device_id=None),
                device_class=DeviceClass.TEMPERATURE,
                native_unit_of_measurement=Units.TEMP_CELSIUS,
            ),
            DeviceKey(key="temperature_probe_4", device_id=None): SensorDescription(
                device_key=DeviceKey(key="temperature_probe_4", device_id=None),
                device_class=DeviceClass.TEMPERATURE,
                native_unit_of_measurement=Units.TEMP_CELSIUS,
            ),
        },
        entity_values={
            DeviceKey(key="signal_strength", device_id=None): SensorValue(
                device_key=DeviceKey(key="signal_strength", device_id=None),
                name="Signal Strength",
                native_value=-60,
            ),
            DeviceKey(key="temperature_probe_1", device_id=None): SensorValue(
                device_key=DeviceKey(key="temperature_probe_1", device_id=None),
                name="Temperature " "Probe " "1",
                native_value=26.0,
            ),
            DeviceKey(key="temperature_probe_2", device_id=None): SensorValue(
                device_key=DeviceKey(key="temperature_probe_2", device_id=None),
                name="Temperature " "Probe " "2",
                native_value=25.0,
            ),
            DeviceKey(key="temperature_probe_3", device_id=None): SensorValue(
                device_key=DeviceKey(key="temperature_probe_3", device_id=None),
                name="Temperature " "Probe " "3",
                native_value=26.0,
            ),
            DeviceKey(key="temperature_probe_4", device_id=None): SensorValue(
                device_key=DeviceKey(key="temperature_probe_4", device_id=None),
                name="Temperature " "Probe " "4",
                native_value=25.0,
            ),
        },
    )
