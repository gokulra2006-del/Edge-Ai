"""
scripts/pi/common.py
Common hardware detection, metadata collection, and authentication utilities
for Sentinel-AI physical Raspberry Pi validation suite.
"""

from __future__ import annotations
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
from typing import Any, Dict, Optional, Tuple

SALT = "sentinel_pi_hardware_auth_v1"


def get_git_hash() -> str:
    """Retrieves current git commit hash, falling back to environment or UNKNOWN."""
    if os.environ.get("GIT_HASH"):
        return os.environ["GIT_HASH"]
    try:
        res = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=2,
            check=True,
        )
        return res.stdout.strip()
    except Exception:
        return "UNKNOWN_GIT_HASH"


def get_hardware_model() -> str:
    """
    Detects true hardware model.
    On Raspberry Pi, reads /proc/device-tree/model or /proc/cpuinfo.
    """
    dt_model = Path("/proc/device-tree/model")
    if dt_model.exists():
        try:
            val = dt_model.read_text(encoding="utf-8", errors="replace").strip("\x00\n ")
            if val:
                return val
        except Exception:
            pass

    cpuinfo = Path("/proc/cpuinfo")
    if cpuinfo.exists():
        try:
            for line in cpuinfo.read_text(encoding="utf-8", errors="replace").splitlines():
                if line.startswith("Model"):
                    parts = line.split(":", 1)
                    if len(parts) == 2 and parts[1].strip():
                        return parts[1].strip()
        except Exception:
            pass

    # Non-Pi or host fallback
    return f"{platform.system()} {platform.machine()} ({platform.processor() or 'generic'})"


def get_os_info() -> str:
    """Retrieves OS release string or Linux distribution details."""
    os_release = Path("/etc/os-release")
    if os_release.exists():
        try:
            lines = os_release.read_text(encoding="utf-8", errors="replace").splitlines()
            for line in lines:
                if line.startswith("PRETTY_NAME="):
                    return line.split("=", 1)[1].strip("\"'")
        except Exception:
            pass

    return f"{platform.system()} {platform.release()} ({platform.machine()})"


def get_soc_temperature() -> Optional[float]:
    """Reads SoC core temperature in degrees Celsius."""
    # 1. Sysfs thermal zone
    sysfs_temp = Path("/sys/class/thermal/thermal_zone0/temp")
    if sysfs_temp.exists():
        try:
            raw = float(sysfs_temp.read_text().strip())
            return round(raw / 1000.0, 1)
        except Exception:
            pass

    # 2. vcgencmd measure_temp
    try:
        res = subprocess.run(["vcgencmd", "measure_temp"], capture_output=True, text=True, timeout=1)
        if res.returncode == 0 and "temp=" in res.stdout:
            raw = res.stdout.strip().replace("temp=", "").replace("'C", "")
            return float(raw)
    except Exception:
        pass

    return None


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


def get_throttled_state() -> Optional[Dict[str, Any]]:
    """Executes and parses vcgencmd get_throttled on Raspberry Pi."""
    try:
        res = subprocess.run(["vcgencmd", "get_throttled"], capture_output=True, text=True, timeout=1)
        if res.returncode == 0 and "throttled=" in res.stdout:
            raw_hex = res.stdout.strip().replace("throttled=", "")
            val = int(raw_hex, 16)
            active = [
                {"bit": hex(bit), "description": desc}
                for bit, desc in THROTTLE_FLAGS.items()
                if val & bit
            ]
            return {
                "raw_hex": raw_hex,
                "integer_value": val,
                "is_currently_throttled": bool(val & 0x7),
                "has_throttled_since_boot": bool(val & 0x70000),
                "active_flags": active,
            }
    except Exception:
        pass
    return None


def compute_benchmark_signature(
    benchmark_name: str,
    hardware_model: str,
    timestamp_utc: str,
    git_hash: str,
) -> str:
    """Computes tamper-evident cryptographic signature for the benchmark record."""
    canonical = f"{SALT}:{benchmark_name}:{hardware_model}:{timestamp_utc}:{git_hash}".encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def create_benchmark_header(
    benchmark_name: str,
    duration_seconds: float,
    repeatable: bool = True,
) -> Dict[str, Any]:
    """Generates standard benchmark header with authentic hardware provenance."""
    now = datetime.now(timezone.utc).isoformat()
    hw_model = get_hardware_model()
    os_info = get_os_info()
    git_hash = get_git_hash()
    sig = compute_benchmark_signature(benchmark_name, hw_model, now, git_hash)

    return {
        "tool_version": "1.0.0",
        "data_tag": "REAL_HARDWARE",
        "benchmark": benchmark_name,
        "hardware_model": hw_model,
        "os": os_info,
        "git_hash": git_hash,
        "timestamp_utc": now,
        "duration_seconds": duration_seconds,
        "repeatable": repeatable,
        "signature": sig,
    }


def verify_benchmark_header(data: Dict[str, Any]) -> Tuple[bool, str]:
    """Validates benchmark structure, data tag, and cryptographic signature."""
    if not isinstance(data, dict):
        return False, "Data is not a valid JSON dictionary"

    header = data.get("header") or data
    required = ["data_tag", "benchmark", "hardware_model", "timestamp_utc", "git_hash", "signature"]
    for field in required:
        if field not in header:
            return False, f"Missing required authentication field: '{field}'"

    if header.get("data_tag") != "REAL_HARDWARE":
        return False, f"Invalid data_tag '{header.get('data_tag')}'; must be 'REAL_HARDWARE'"

    expected_sig = compute_benchmark_signature(
        header["benchmark"],
        header["hardware_model"],
        header["timestamp_utc"],
        header["git_hash"],
    )

    if header.get("signature") != expected_sig:
        return False, "Cryptographic signature mismatch; file was altered or generated outside tooling"

    return True, "Valid authentic hardware benchmark"
