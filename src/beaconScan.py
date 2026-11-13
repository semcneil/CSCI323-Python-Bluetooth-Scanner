import asyncio
import sys
from bleak import BleakScanner

def parse_ibeacon(manufacturer_data: dict):
    """Checks for Apple's Company ID (0x004C) and parses iBeacon payload."""
    apple_data = manufacturer_data.get(0x004C)
    # Fixed indexing: byte 0 is 0x02 (iBeacon type), byte 1 is 0x15 (21 bytes length)
    if apple_data and len(apple_data) >= 23 and apple_data[0] == 0x02 and apple_data[1] == 0x15:
        uuid_bytes = apple_data[2:18]
        uuid = (
            f"{uuid_bytes[0:4].hex()}-"
            f"{uuid_bytes[4:6].hex()}-"
            f"{uuid_bytes[6:8].hex()}-"
            f"{uuid_bytes[8:10].hex()}-"
            f"{uuid_bytes[10:16].hex()}"
        ).upper()
        major = int.from_bytes(apple_data[18:20], byteorder="big")
        minor = int.from_bytes(apple_data[20:22], byteorder="big")
        tx_power = int.from_bytes(apple_data[22:23], byteorder="big", signed=True)
        return {"uuid": uuid, "major": major, "minor": minor, "tx_power": tx_power}
    return None

def detection_callback(device, adv_data):
    """Triggered immediately every time a Bluetooth advertisement is heard."""
    name = device.name or adv_data.local_name or "Unknown Device"
    rssi = adv_data.rssi
    
    ibeacon = parse_ibeacon(adv_data.manufacturer_data)
    is_eddystone = "0000feaa-0000-1000-8000-00805f9b34fb" in adv_data.service_uuids

    if ibeacon:
        beacon_info = f"iBeacon | UUID: {ibeacon['uuid']} | Major: {ibeacon['major']} | Minor: {ibeacon['minor']}"
    elif is_eddystone:
        beacon_info = "Eddystone Beacon"
    elif adv_data.manufacturer_data:
        m_ids = [hex(k) for k in adv_data.manufacturer_data.keys()]
        beacon_info = f"BLE Device (Manufacturer IDs: {', '.join(m_ids)})"
    else:
        beacon_info = "Standard BLE Device"

    print(f"[{rssi} dBm] {device.address} ({name}) -> {beacon_info}", flush=True)

async def main():
    print("Starting continuous Bluetooth scan... Press Ctrl+C to stop.\n", flush=True)
    
    scanner = BleakScanner(detection_callback=detection_callback)
    await scanner.start()
    
    try:
        while True:
            await asyncio.sleep(1.0)
    except asyncio.CancelledError:
        pass
    finally:
        print("\nStopping scanner...", flush=True)
        await scanner.stop()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Scan stopped by user.")
        sys.exit(0)
