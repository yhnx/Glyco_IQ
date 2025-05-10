import dbus
import dbus.mainloop.glib
import dbus.service
import subprocess
import json
import time
import os
from gi.repository import GLib

# UUIDs
SERVICE_UUID = "00000000-8cb1-44ce-9a66-001dca0941a6"
RUN_DEVICE_UUID = "00000001-8cb1-44ce-9a66-001dca0941a6"
DEVICE_DATA_UUID = "00000002-8cb1-44ce-9a66-001dca0941a6"

# D-Bus constants
BLUEZ_SERVICE = "org.bluez"
GATT_MANAGER_IFACE = "org.bluez.GattManager1"
GATT_SERVICE_IFACE = "org.bluez.GattService1"
GATT_CHAR_IFACE = "org.bluez.GattCharacteristic1"
DBUS_OM_IFACE = "org.freedesktop.DBus.ObjectManager"
DBUS_PROP_IFACE = "org.freedesktop.DBus.Properties"

# Advertisement constants
LE_ADVERTISING_MANAGER_IFACE = "org.bluez.LEAdvertisingManager1"
LE_ADVERTISEMENT_IFACE = "org.bluez.LEAdvertisement1"

class Characteristic(dbus.service.Object):
    def __init__(self, bus, index, uuid, flags, service):
        self.path = f"{service.path}/char{index}"
        self.bus = bus
        self.uuid = uuid
        self.flags = flags
        self.service = service
        dbus.service.Object.__init__(self, bus, self.path)

    def get_properties(self):
        return {
            GATT_CHAR_IFACE: {
                "Service": dbus.ObjectPath(self.service.path),
                "UUID": self.uuid,
                "Flags": self.flags,
                "Value": dbus.Array([], signature="y"),
            }
        }

    @dbus.service.method(DBUS_PROP_IFACE, in_signature="s", out_signature="a{sv}")
    def GetAll(self, interface):
        if interface != GATT_CHAR_IFACE:
            raise dbus.exceptions.DBusException(f"Interface not supported: {interface}")
        return self.get_properties()[interface]

    @dbus.service.method(GATT_CHAR_IFACE, in_signature="a{sv}", out_signature="ay")
    def ReadValue(self, options):
        print(f"ReadValue called on {self.uuid}")
        return dbus.Array([], signature="y")

    @dbus.service.method(GATT_CHAR_IFACE, in_signature="aya{sv}")
    def WriteValue(self, value, options):
        print(f"WriteValue called on {self.uuid} with value: {value}")

    @dbus.service.method(GATT_CHAR_IFACE)
    def StartNotify(self):
        print(f"StartNotify called on {self.uuid}")

    @dbus.service.method(GATT_CHAR_IFACE)
    def StopNotify(self):
        print(f"StopNotify called on {self.uuid}")

class RunDeviceCharacteristic(Characteristic):
    def __init__(self, bus, index, service):
        Characteristic.__init__(self, bus, index, RUN_DEVICE_UUID, ["write"], service)

    def WriteValue(self, value, options):
        command = "".join(chr(b) for b in value).strip()
        print(f"Received command: {command}")
        if command == "run_device":
            try:
                # Use tflite_env Python and set working directory
                result = subprocess.run(
                    ['/home/yhnx/tflite_env/bin/python', '/home/yhnx/Documents/bluetooth_server/device_control.py'],
                    capture_output=True,
                    text=True,
                    timeout=30,
                    cwd='/home/yhnx/Documents/bluetooth_server',
                    env={**os.environ, 'PYTHONUNBUFFERED': '1'}
                )
                print(f"device_control.py stdout: {result.stdout}")
                print(f"device_control.py stderr: {result.stderr}")
                print(f"device_control.py return code: {result.returncode}")
                output = result.stdout.strip()
                if not output:
                    output = json.dumps({"status": "error", "message": "No output from device_control.py"})
                device_data_char = self.service.get_characteristic(DEVICE_DATA_UUID)
                device_data_char.notify(output.encode('utf-8'))
            except subprocess.TimeoutExpired as e:
                error = json.dumps({"status": "error", "message": "device_control.py timed out"})
                print(f"Error: {error}")
                device_data_char = self.service.get_characteristic(DEVICE_DATA_UUID)
                device_data_char.notify(error.encode('utf-8'))
            except Exception as e:
                error = json.dumps({"status": "error", "message": str(e)})
                print(f"Error: {error}")
                device_data_char = self.service.get_characteristic(DEVICE_DATA_UUID)
                device_data_char.notify(error.encode('utf-8'))

class DeviceDataCharacteristic(Characteristic):
    def __init__(self, bus, index, service):
        Characteristic.__init__(self, bus, index, DEVICE_DATA_UUID, ["read", "notify"], service)
        self.notifying = False

    def notify(self, value):
        if self.notifying:
            self.PropertiesChanged(GATT_CHAR_IFACE, {"Value": dbus.Array(value, signature="y")}, [])
            print(f"Notified value: {value}")

    @dbus.service.signal(DBUS_PROP_IFACE, signature="sa{sv}as")
    def PropertiesChanged(self, interface, changed, invalidated):
        pass

    def StartNotify(self):
        self.notifying = True
        print("Notifications enabled")

    def StopNotify(self):
        self.notifying = False
        print("Notifications disabled")

class Service(dbus.service.Object):
    PATH_BASE = "/org/bluez/app/service"

    def __init__(self, bus, index, uuid, primary):
        self.path = f"{self.PATH_BASE}{index}"
        self.bus = bus
        self.index = index
        self.uuid = uuid
        self.primary = primary
        self.characteristics = []
        dbus.service.Object.__init__(self, bus, self.path)

    def get_properties(self):
        return {
            GATT_SERVICE_IFACE: {
                "UUID": self.uuid,
                "Primary": self.primary,
                "Characteristics": dbus.Array(self.get_characteristic_paths(), signature="o"),
            }
        }

    def get_characteristic_paths(self):
        return [dbus.ObjectPath(c.path) for c in self.characteristics]

    def get_characteristic(self, uuid):
        for char in self.characteristics:
            if char.uuid == uuid:
                return char
        return None

    @dbus.service.method(DBUS_PROP_IFACE, in_signature="s", out_signature="a{sv}")
    def GetAll(self, interface):
        if interface != GATT_SERVICE_IFACE:
            raise dbus.exceptions.DBusException(f"Interface not supported: {interface}")
        return self.get_properties()[interface]

    def add_characteristic(self, characteristic):
        self.characteristics.append(characteristic)

class Application(dbus.service.Object):
    def __init__(self, bus):
        self.path = "/org/bluez/app"
        self.services = []
        dbus.service.Object.__init__(self, bus, self.path)

    def add_service(self, service):
        self.services.append(service)

    @dbus.service.method(DBUS_OM_IFACE, out_signature="a{oa{sa{sv}}}")
    def GetManagedObjects(self):
        response = {}
        for service in self.services:
            response[dbus.ObjectPath(service.path)] = service.get_properties()
            for char in service.characteristics:
                response[dbus.ObjectPath(char.path)] = char.get_properties()
        return response

class Advertisement(dbus.service.Object):
    PATH_BASE = "/org/bluez/advertisement"

    def __init__(self, bus, index, advertising_type):
        self.path = f"{self.PATH_BASE}{index}"
        self.bus = bus
        self.ad_type = advertising_type
        self.service_uuids = [SERVICE_UUID.upper()]
        self.solicit_uuids = []
        self.manufacturer_data = None
        self.service_data = None
        self.local_name = "GlycoIQ"
        self.include_tx_power = False
        self.timeout = dbus.UInt16(0)
        dbus.service.Object.__init__(self, bus, self.path)

    def get_properties(self):
        props = {
            LE_ADVERTISEMENT_IFACE: {
                "Type": self.ad_type,
                "ServiceUUIDs": dbus.Array(self.service_uuids, signature="s"),
                "SolicitUUIDs": dbus.Array(self.solicit_uuids, signature="s"),
                "LocalName": self.local_name,
                "IncludeTxPower": self.include_tx_power,
                "Timeout": self.timeout,
            }
        }
        return props

    @dbus.service.method(DBUS_PROP_IFACE, in_signature="s", out_signature="a{sv}")
    def GetAll(self, interface):
        if interface != LE_ADVERTISEMENT_IFACE:
            raise dbus.exceptions.DBusException(f"Interface not supported: {interface}")
        return self.get_properties()[interface]

    @dbus.service.method(LE_ADVERTISEMENT_IFACE)
    def Release(self):
        print("Advertisement released")

def register_app_callback():
    print("GATT application registered")

def register_app_error_callback(error):
    print(f"Failed to register application: {error}")

def register_ad_callback():
    print("Advertisement registered")

def register_ad_error_callback(error):
    print(f"Failed to register advertisement: {error}")

def main():
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus()

    # Ensure adapter is powered on and discoverable
    try:
        adapter = bus.get_object(BLUEZ_SERVICE, "/org/bluez/hci0")
        adapter_props = dbus.Interface(adapter, DBUS_PROP_IFACE)
        adapter_props.Set("org.bluez.Adapter1", "Powered", True)
        adapter_props.Set("org.bluez.Adapter1", "Discoverable", True)
        adapter_props.Set("org.bluez.Adapter1", "Alias", "GlycoIQ")
        powered = adapter_props.Get("org.bluez.Adapter1", "Powered")
        discoverable = adapter_props.Get("org.bluez.Adapter1", "Discoverable")
        print(f"Adapter state: Powered={powered}, Discoverable={discoverable}")
    except Exception as e:
        print(f"Error configuring adapter: {e}")
        return

    # Reset adapter
    try:
        subprocess.run(['sudo', 'hciconfig', 'hci0', 'reset'], check=True)
        subprocess.run(['sudo', 'hciconfig', 'hci0', 'piscan'], check=True)
        print("Adapter reset and set to piscan")
    except subprocess.CalledProcessError as e:
        print(f"Error resetting adapter: {e}")
        return

    # Create application
    app = Application(bus)

    # Create service
    service = Service(bus, 0, SERVICE_UUID, True)
    app.add_service(service)

    # Create characteristics
    run_device_char = RunDeviceCharacteristic(bus, 0, service)
    device_data_char = DeviceDataCharacteristic(bus, 1, service)
    service.add_characteristic(run_device_char)
    service.add_characteristic(device_data_char)

    # Debug: Print object paths
    print(f"Application path: {app.path}")
    print(f"Service path: {service.path}")
    for char in service.characteristics:
        print(f"Characteristic path: {char.path}, UUID: {char.uuid}")

    # Register GATT application
    try:
        gatt_manager = dbus.Interface(adapter, GATT_MANAGER_IFACE)
        gatt_manager.RegisterApplication(
            app.path,
            {},
            reply_handler=register_app_callback,
            error_handler=register_app_error_callback
        )
    except Exception as e:
        print(f"Error registering GATT application: {e}")
        return

    # Register advertisement with retry
    for attempt in range(3):
        try:
            ad = Advertisement(bus, 0, "peripheral")
            ad_manager = dbus.Interface(adapter, LE_ADVERTISING_MANAGER_IFACE)
            ad_manager.RegisterAdvertisement(
                ad.path,
                {},
                reply_handler=register_ad_callback,
                error_handler=register_ad_error_callback
            )
            print(f"Advertisement path: {ad.path}")
            break
        except Exception as e:
            print(f"Advertisement attempt {attempt + 1} failed: {e}")
            time.sleep(1)
            if attempt == 2:
                print("Failed to register advertisement after 3 attempts")
                return

    print("GATT server running, advertising as GlycoIQ")
    GLib.MainLoop().run()

if __name__ == "__main__":
    main()