#!/usr/bin/env python3
"""
scripts/pi/benchmark_thermal.py
Thermal and Hardware Throttling Diagnostics for Sentinel-AI on Raspberry Pi 4.
Parses vcgencmd get_throttled bitmask, core temperature, and CPU scaling frequency.
Safely reports UNAVAILABLE on non-Pi / host systems without raising.
"""

from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import subprocess
import sys

# Raspberry Pi 4 vcgencmd throttling bit definitions
THROTTLE_FLAGS = {
    0x1: "Under-voltage detected (currently)",
    0x2: "Arm frequency capped (currently)",
    0x4: "Currently throttled",
    0x8: "Soft temperature limit active (currently)",
    0x10000: "Under-voltage has occurred since boot",
    0x20000: "Arm frequency capping has occurred since boot",
    0x40000: "Throttling has occurred since boot",
    0x80000: "Soft temperature limit has occurred since boot",
}


def parse_throttled_hex(hex_str: str) -> dict:
    try:
        val = int(hex_str, 16)
    except ValueError:
        return {"raw_value": hex_str, "active_flags": [], "is_throttled": False}

    active = []
    for bit, desc in THROTTLE_FLAGS.items():
        if val & bit:
            active.append({"bit": hex(bit), "description": desc})

    currently_throttled = bool(val & 0x7)
    historical_throttle = bool(val & 0x70000)

    return {
        "raw_hex": hex_str,
        "integer_value": val,
        "is_currently_throttled": currently_throttled,
        "has_throttled_since_boot": historical_throttle,
        "active_flags": active,
    }


def run_benchmark() -> dict:
    hostname = platform.node()
    is_linux = platform.system() == "Linux"

    temp_c = None
    temp_source = "UNAVAILABLE"
    throttled_data = None
    cpu_freq_mhz = None

    # 1. Read sysfs thermal zone
    sysfs_temp = Path("/sys/class/thermal/thermal_zone0/temp")
    if sysfs_temp.exists():
        try:
            temp_c = round(float(sysfs_temp.read_text().strip()) / 1000.0, 1)
            temp_source = "/sys/class/thermal/thermal_zone0/temp"
        except Exception:
            pass

    # 2. Try vcgencmd measure_temp
    try:
        res = subprocess.run(["vcgencmd", "measure_temp"], capture_output=True, text=True, timeout=1)
        if res.returncode == 0 and "temp=" in res.stdout:
            raw_t = res.stdout.strip().replace("temp=", "").replace("'C", "")
            temp_c = float(raw_t)
            temp_source = "vcgencmd"
    except Exception:
        pass

    # 3. Try vcgencmd get_throttled
    try:
        res = subprocess.run(["vcgencmd", "get_throttled"], capture_output=True, text=True, timeout=1)
        if res.returncode == 0 and "throttled=" in res.stdout:
            raw_hex = res.stdout.strip().replace("throttled=", "")
            throttled_data = parse_throttled_hex(raw_hex)
    except Exception:
        pass

    # 4. Read CPU frequency
    sysfs_freq = Path("/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq")
    if sysfs_freq.exists():
        try:
            cpu_freq_mhz = round(float(sysfs_freq.read_text().strip()) / 1000.0, 1)
        except Exception:
            pass

    status = "OK"
    if temp_c is not None:
        if temp_c >= 80.0:
            status = "CRITICAL_OVERHEAT"
        elif temp_c >= 70.0:
            status = "WARNING_HIGH_TEMP"

    if throttled_data and throttled_data.get("is_currently_throttled"):
        status = "THROTTLED"

    result = {
        "benchmark": "thermal_throttling",
        "target": "Raspberry Pi 4 Model B (4 GB)",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "host": hostname,
        "platform": platform.system(),
        "temperature_celsius": temp_c,
        "temperature_source": temp_source,
        "cpu_frequency_mhz": cpu_freq_mhz,
        "throttling": throttled_data or {
            "status": "UNAVAILABLE",
            "reason": "vcgencmd not found or not running on Raspberry Pi hardware",
            "is_currently_throttled": False,
            "has_throttled_since_boot": False,
        },
        "status": status if temp_c is not None else "UNAVAILABLE",
    }
    return result


def main():
    parser = argparse.ArgumentParser(description="Sentinel-AI Thermal Diagnostics Benchmark")
    parser.add_argument("--out", type=str, default="", help="Path to write JSON output")
    args = parser.parse_args()

    res = run_benchmark()
    out_json = json.dumps(res, indent=2)

    if args.out:
        Path(args.out).write_text(out_json, encoding="utf-8")
        print(f"Results saved to {args.out}")
    else:
        print(out_json)


if __name__ == "__main__":
    main()
