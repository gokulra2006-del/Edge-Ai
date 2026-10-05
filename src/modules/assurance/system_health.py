"""Local, evidence-based startup and operator self-test checks."""
from __future__ import annotations
import shutil
import sqlite3
from pathlib import Path
from typing import Any, Dict
from src.config.model_profile import model_profile
from src.modules.database.governed_store import writer_health_snapshot

ROOT = Path(__file__).resolve().parents[3]

def system_health() -> Dict[str, Any]:
    profile = model_profile()
    checks = []
    for label, path in [("audio_model", profile["audio"]), *[("vision_model", p) for p in profile["vision"]]]:
        checks.append({"component": label, "status": "PASS" if Path(path).is_file() else "FAIL", "detail": Path(path).name})
    try:
        db = ROOT / "data" / "emergency_events.db"
        db.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(db) as connection: connection.execute("SELECT 1")
        checks.append({"component": "local_database", "status": "PASS", "detail": "SQLite writable"})
    except sqlite3.Error as error:
        checks.append({"component": "local_database", "status": "FAIL", "detail": str(error)})
    for label, path in [("assessment_config", ROOT / "src/config/advanced_platform.json"), ("dashboard_credentials", ROOT / "src/config/dashboard_users.local.json")]:
        checks.append({"component": label, "status": "PASS" if path.is_file() else "WARNING", "detail": "available" if path.is_file() else "missing"})
    writer = writer_health_snapshot()
    checks.append({"component": "governed_writer", "status": "PASS" if writer["healthy"] else "WARNING", "detail": "queue healthy" if writer["healthy"] else "; ".join(writer["failures"][-3:])})
    usage = shutil.disk_usage(ROOT)
    checks.append({"component": "storage", "status": "PASS" if usage.free > 1_000_000_000 else "WARNING", "detail": f"{usage.free // 1_000_000_000} GB free"})
    overall = "FAIL" if any(c["status"] == "FAIL" for c in checks) else ("WARNING" if any(c["status"] == "WARNING" for c in checks) else "PASS")
    return {"status": overall, "profile": profile["name"], "research_only": bool(profile.get("synthetic")), "checks": checks}
