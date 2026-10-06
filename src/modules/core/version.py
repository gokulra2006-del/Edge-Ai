"""
Version and Build Metadata for Sentinel-AI Edge Appliance.
Provides commit hash, build date, schema version, and runtime diagnostics.
"""

from __future__ import annotations
import os
from pathlib import Path
import platform
import subprocess
from typing import Any, Dict

APP_VERSION = "0.5.0"
BUILD_DATE = "2026-10-06"
SCHEMA_VERSION = 7
TARGET_PLATFORM = "Raspberry Pi 4 Model B (4 GB)"


def get_git_hash() -> str:
    """Retrieves short git commit hash from environment, git CLI, or fallback."""
    env_hash = os.environ.get("SENTINEL_GIT_HASH")
    if env_hash:
        return env_hash[:8]
    try:
        repo_dir = Path(__file__).resolve().parents[3]
        res = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(repo_dir),
            capture_output=True,
            text=True,
            timeout=2,
        )
        if res.returncode == 0 and res.stdout.strip():
            return res.stdout.strip()
    except Exception:
        pass
    return "e3e988f"


def get_version_info() -> Dict[str, Any]:
    """Returns complete version metadata dictionary for API and dashboard."""
    return {
        "version": APP_VERSION,
        "git_hash": get_git_hash(),
        "build_date": BUILD_DATE,
        "schema_version": SCHEMA_VERSION,
        "target_platform": TARGET_PLATFORM,
        "runtime_os": f"{platform.system()} {platform.release()}",
        "python_version": platform.python_version(),
    }
