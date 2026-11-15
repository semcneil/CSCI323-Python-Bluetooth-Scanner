import asyncio
import math
import struct
import time
from bleak import BleakScanner
import matplotlib.pyplot as plt

# --- CONFIGURATION ---
# Set your ESP32-C6 iBeacon UUID here to ignore other beacons (or leave None for all)
TARGET_UUID = None

# Smoothing factor (0.0 to 1.0).
# Lower = smoother/slower response (e.g., 0.15). Higher = faster/jumpier (e.g., 0.5).
EMA_ALPHA = 0.2

# Seconds before a beacon is considered lost and removed from the radar
STALE_TIMEOUT = 10.0

# Max radius (in meters) shown on the radar plot
MAX_RADAR_METERS = 10.0

# Dictionary storing active beacons: key = (uuid, major, minor)
active_beacons = {}


def parse_ibeacon(manufacturer_data):
    """Extracts UUID, Major, Minor, and TX Power from Apple iBeacon payload."""
    apple_data = manufacturer_data.get(0x004C)
    # 0x02 = iBeacon type, 0x15 = 21 bytes remaining length
    if apple_data and len(apple_data) >= 23 and apple_data[0] == 0x02 and apple_data[1] == 0x15:
        uuid_bytes = apple_data[2:18]
        uuid_str = (
            f"{uuid_bytes[0:4].hex()}-{uuid_bytes[4:6].hex()}-"
            f"{uuid_bytes[6:8].hex()}-{uuid_bytes[8:10].hex()}-"
            f"{uuid_bytes[10:16].hex()}"
        ).upper()
        major, minor, tx_power = struct.unpack(">HHb", apple_data[18:23])
        return uuid_str, major, minor, tx_power
    return None


def estimate_distance(rssi, tx_power):
    """Calculates rough distance in meters using path-loss formula."""
    if rssi == 0 or tx_power == 0:
        return -1.0
    ratio = rssi * 1.0 / tx_power
    if ratio < 1.0:
        return round(pow(ratio, 10), 2)
    else:
        return round((0.89976) * pow(ratio, 7.7095) + 0.111, 2)


def detection_callback(device, advertisement_data):
    """Triggered every time a BLE advertisement packet is received."""
    parsed = parse_ibeacon(advertisement_data.manufacturer_data)
    if not parsed:
        return

    uuid_str, major, minor, tx_power = parsed

    if TARGET_UUID and uuid_str != TARGET_UUID.upper():
        return

    beacon_key = (uuid_str, major, minor)
    raw_rssi = advertisement_data.rssi

    # Apply Exponential Moving Average (EMA) smoothing
    if beacon_key in active_beacons:
        prev_rssi = active_beacons[beacon_key]["smoothed_rssi"]
        smoothed_rssi = (EMA_ALPHA * raw_rssi) + ((1 - EMA_ALPHA) * prev_rssi)
    else:
        smoothed_rssi = float(raw_rssi)

    active_beacons[beacon_key] = {
        "raw_rssi": raw_rssi,
        "smoothed_rssi": round(smoothed_rssi, 1),
        "tx_power": tx_power,
        "distance": estimate_distance(smoothed_rssi, tx_power),
        "last_seen": time.time(),
    }


def setup_radar_plot():
    """Initializes the interactive Matplotlib polar radar chart."""
    plt.ion()
    fig = plt.figure(figsize=(8, 8))
    fig.canvas.manager.set_window_title("ESP32-C6 iBeacon Proximity Radar")
    ax = fig.add_subplot(111, polar=True)
    return fig, ax


def update_radar_plot(fig, ax, now):
    """Redraws the radar with current smoothed beacon distances."""
    ax.clear()
    ax.set_ylim(0, MAX_RADAR_METERS)
    ax.set_yticklabels([f"{int(r)}m" for r in ax.get_yticks()], color="gray", fontsize=8)
    ax.set_xticklabels([])  # Hide degree labels since single-node BLE has no compass angle
    ax.grid(True, linestyle="--", alpha=0.5)
    ax.set_title(
        f"ESP32-C6 iBeacon Relative Proximity (EMA Alpha: {EMA_ALPHA})\n"
        "Center = This Computer | Ring = Estimated Distance",
        pad=15,
        fontsize=11,
        fontweight="bold",
    )

    # Plot receiver at center
    ax.scatter([0], [0], color="black", s=120, marker="^", zorder=5, label="Scanner (You)")

    # Remove stale beacons
    stale_keys = [k for k, v in active_beacons.items() if (now - v["last_seen"]) > STALE_TIMEOUT]
    for k in stale_keys:
        del active_beacons[k]

    sorted_keys = sorted(active_beacons.keys(), key=lambda k: (k[1], k[2]))
    total = len(sorted_keys)

    if total == 0:
        ax.text(
            0, 0, "\n\nScanning for ESP32-C6 iBeacons...",
            ha="center", va="top", color="gray", fontsize=10
        )
    else:
        # Spread beacons evenly around the circle so labels don't overlap
        for idx, key in enumerate(sorted_keys):
            uuid_str, major, minor = key
            data = active_beacons[key]
            dist = min(data["distance"], MAX_RADAR_METERS)  # Clamp to outer ring if farther
            angle = (2 * math.pi * idx) / total

            # Color code by proximity
            color = "#2ecc71" if dist < 2.0 else "#f39c12" if dist < 5.0 else "#e74c3c"

            ax.scatter([angle], [dist], color=color, s=160, zorder=4)
            
            # Draw dashed line from center to beacon
            ax.plot([0, angle], [0, dist], color=color, linestyle=":", alpha=0.6)

            label = (
                f"M:{major} m:{minor}\n"
                f"~{data['distance']}m ({data['smoothed_rssi']} dBm)"
            )
            ax.annotate(
                label,
                xy=(angle, dist),
                xytext=(0, 12),
                textcoords="offset points",
                ha="center",
                fontsize=9,
                fontweight="bold",
                bbox=dict(boxstyle="round,pad=0.3", fc="white", ec=color, alpha=0.85),
            )

    fig.canvas.draw_idle()
    fig.canvas.flush_events()


async def monitor_beacons():
    fig, ax = setup_radar_plot()
    scanner = BleakScanner(detection_callback=detection_callback)
    await scanner.start()
    print("Radar window opened. Close the window or press Ctrl+C in terminal to stop.")

    try:
        while plt.fignum_exists(fig.number):
            now = time.time()
            update_radar_plot(fig, ax, now)
            # Yield control to asyncio so BLE packets keep arriving smoothly
            await asyncio.sleep(0.25)
    except asyncio.CancelledError:
        pass
    finally:
        await scanner.stop()
        plt.close("all")
        print("Scanner stopped.")


if __name__ == "__main__":
    try:
        asyncio.run(monitor_beacons())
    except KeyboardInterrupt:
        print("\nExited by user.")
