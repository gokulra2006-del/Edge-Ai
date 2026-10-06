from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

from src.modules.database.governed_store import IncidentRepository, utc_now


def _to_date_str(val: str | datetime) -> str:
    if isinstance(val, datetime):
        return val.strftime("%Y-%m-%d")
    return val[:10]


class RollupEngine:
    """Incremental, idempotent pre-aggregation engine for analytics daily rollups."""

    def __init__(self, db_path_or_repo: Path | str | IncidentRepository):
        if isinstance(db_path_or_repo, IncidentRepository):
            self.db_path = Path(db_path_or_repo.db_path)
            self._repo: IncidentRepository | None = db_path_or_repo
        else:
            self.db_path = Path(db_path_or_repo)
            self._repo = None

    def _connection(self) -> sqlite3.Connection:
        con = sqlite3.connect(str(self.db_path), timeout=2.0)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA busy_timeout=2000")
        return con

    def get_high_water_mark(self, rollup_name: str = "daily_rollup") -> str | None:
        """Retrieve the recorded high-water mark for the rollup."""
        with self._connection() as con:
            row = con.execute(
                "SELECT high_water_mark FROM analytics_rollup_state WHERE rollup_name = ?",
                (rollup_name,)
            ).fetchone()
            return row["high_water_mark"] if row else None

    def get_freshness(self, rollup_name: str = "daily_rollup") -> str | None:
        """Retrieve the last time rollup was executed."""
        with self._connection() as con:
            row = con.execute(
                "SELECT updated_at FROM analytics_rollup_state WHERE rollup_name = ?",
                (rollup_name,)
            ).fetchone()
            return row["updated_at"] if row else None

    def run_rollup(self, days_back: int = 3, force_full: bool = False) -> dict[str, Any]:
        """
        Execute incremental rollup.
        - Reads recent or full range.
        - Re-rolls the last N days to capture late-arriving data.
        - Deletes and re-inserts daily records idempotently.
        - Advances high-water mark.
        """
        now_dt = datetime.now(timezone.utc)
        today_str = now_dt.strftime("%Y-%m-%d")

        with self._connection() as con:
            # 1. Determine date range
            hw_mark = self.get_high_water_mark("daily_rollup")
            if hw_mark and not force_full:
                try:
                    hw_dt = datetime.fromisoformat(hw_mark.replace("Z", "+00:00"))
                    start_dt = hw_dt - timedelta(days=days_back)
                except Exception:
                    start_dt = now_dt - timedelta(days=30)
            else:
                # Find earliest incident or prediction timestamp
                r_earliest = con.execute("""
                    SELECT min(ts) as earliest FROM (
                        SELECT min(created_at) as ts FROM incidents
                        UNION ALL
                        SELECT min(timestamp) as ts FROM predictions
                    ) WHERE ts IS NOT NULL
                """).fetchone()
                if r_earliest and r_earliest["earliest"]:
                    try:
                        start_dt = datetime.fromisoformat(r_earliest["earliest"].replace("Z", "+00:00"))
                    except Exception:
                        start_dt = now_dt - timedelta(days=30)
                else:
                    start_dt = now_dt - timedelta(days=30)

            start_day = start_dt.strftime("%Y-%m-%d")
            end_day = today_str

            # 2. Query raw incident aggregations
            inc_rows = con.execute("""
                SELECT
                    strftime('%Y-%m-%d', i.created_at) as day,
                    COALESCE(i.zone_id, 'UNKNOWN') as zone_id,
                    COALESCE(i.severity, 'UNKNOWN') as severity,
                    COALESCE(i.event_type, 'UNKNOWN') as event_type,
                    COALESCE(p.model_id, 'UNKNOWN') as model_id,
                    count(DISTINCT i.incident_id) as total_incidents,
                    sum(CASE WHEN i.status IN ('RESOLVED', 'CLOSED') THEN 1 ELSE 0 END) as resolved_count,
                    sum(CASE WHEN i.status = 'FALSE_ALARM' THEN 1 ELSE 0 END) as false_alarm_count,
                    sum(COALESCE(i.acknowledged_seconds, 0.0)) as total_ack_seconds,
                    sum(CASE WHEN i.acknowledged_seconds IS NOT NULL THEN 1 ELSE 0 END) as ack_count,
                    sum(COALESCE(i.resolution_seconds, 0.0)) as total_resolve_seconds,
                    sum(CASE WHEN i.resolution_seconds IS NOT NULL THEN 1 ELSE 0 END) as resolve_count
                FROM incidents i
                LEFT JOIN (
                    SELECT incident_id, min(model_id) as model_id
                    FROM predictions
                    GROUP BY incident_id
                ) p ON i.incident_id = p.incident_id
                WHERE i.is_demo = 0
                  AND strftime('%Y-%m-%d', i.created_at) >= ?
                  AND strftime('%Y-%m-%d', i.created_at) <= ?
                GROUP BY day, zone_id, severity, event_type, model_id
            """, (start_day, end_day)).fetchall()

            # 3. Query prediction and feedback aggregations
            pred_rows = con.execute("""
                SELECT
                    strftime('%Y-%m-%d', p.timestamp) as day,
                    COALESCE(p.model_id, 'UNKNOWN') as model_id,
                    count(*) as sample_count,
                    sum(p.confidence) as sum_confidence,
                    sum(CASE WHEN p.payload_json LIKE '%"ood_status": "OOD"%' OR p.payload_json LIKE '%"ood_status":"OOD"%' THEN 1 ELSE 0 END) as ood_count,
                    sum(CASE WHEN f.label = 'INCORRECT' THEN 1 ELSE 0 END) as incorrect_count,
                    sum(CASE WHEN f.label = 'CORRECT' THEN 1 ELSE 0 END) as correct_count
                FROM predictions p
                LEFT JOIN prediction_feedback f ON p.id = f.prediction_id
                WHERE strftime('%Y-%m-%d', p.timestamp) >= ?
                  AND strftime('%Y-%m-%d', p.timestamp) <= ?
                GROUP BY day, model_id
            """, (start_day, end_day)).fetchall()

            pred_lookup: dict[tuple[str, str], dict[str, Any]] = {}
            for pr in pred_rows:
                pred_lookup[(pr["day"], pr["model_id"])] = dict(pr)

            # Build combined rollups map: (day, zone_id, severity, event_type, model_id) -> row
            combined: dict[tuple[str, str, str, str, str], dict[str, Any]] = {}
            for ir in inc_rows:
                key = (ir["day"], ir["zone_id"], ir["severity"], ir["event_type"], ir["model_id"])
                p_metrics = pred_lookup.get((ir["day"], ir["model_id"]), {})
                combined[key] = {
                    "day": ir["day"],
                    "zone_id": ir["zone_id"],
                    "severity": ir["severity"],
                    "event_type": ir["event_type"],
                    "model_id": ir["model_id"],
                    "total_incidents": ir["total_incidents"],
                    "resolved_count": ir["resolved_count"],
                    "false_alarm_count": ir["false_alarm_count"],
                    "total_ack_seconds": ir["total_ack_seconds"],
                    "ack_count": ir["ack_count"],
                    "total_resolve_seconds": ir["total_resolve_seconds"],
                    "resolve_count": ir["resolve_count"],
                    "sample_count": p_metrics.get("sample_count", 0),
                    "sum_confidence": p_metrics.get("sum_confidence", 0.0),
                    "ood_count": p_metrics.get("ood_count", 0),
                    "incorrect_count": p_metrics.get("incorrect_count", 0),
                    "correct_count": p_metrics.get("correct_count", 0),
                }

            # Also incorporate any predictions that don't have matching incidents
            for pr in pred_rows:
                day_m = (pr["day"], "ALL", "ALL", "PREDICTION", pr["model_id"])
                # Check if this day & model already mapped
                already_mapped = any(k[0] == pr["day"] and k[4] == pr["model_id"] for k in combined)
                if not already_mapped:
                    combined[day_m] = {
                        "day": pr["day"],
                        "zone_id": "ALL",
                        "severity": "ALL",
                        "event_type": "PREDICTION",
                        "model_id": pr["model_id"],
                        "total_incidents": 0,
                        "resolved_count": 0,
                        "false_alarm_count": 0,
                        "total_ack_seconds": 0.0,
                        "ack_count": 0,
                        "total_resolve_seconds": 0.0,
                        "resolve_count": 0,
                        "sample_count": pr["sample_count"],
                        "sum_confidence": pr["sum_confidence"],
                        "ood_count": pr["ood_count"],
                        "incorrect_count": pr["incorrect_count"],
                        "correct_count": pr["correct_count"],
                    }

            # 4. Device uptime rollup
            # Calculate daily device uptime per component from device_health_events
            dev_events = con.execute("""
                SELECT timestamp, component, current_status
                FROM device_health_events
                ORDER BY timestamp ASC
            """).fetchall()

            # Group events by component
            dev_by_comp: dict[str, list[dict[str, Any]]] = {}
            for ev in dev_events:
                dev_by_comp.setdefault(ev["component"], []).append(dict(ev))

            # Components to compute: found components or default set
            components = list(dev_by_comp.keys()) or ["camera", "microphone", "system"]
            dev_rollups: list[dict[str, Any]] = []

            # Iterate over each day in [start_day, end_day]
            curr_d = datetime.strptime(start_day, "%Y-%m-%d").date()
            end_d = datetime.strptime(end_day, "%Y-%m-%d").date()
            delta_1d = timedelta(days=1)

            while curr_d <= end_d:
                day_iso_prefix = curr_d.strftime("%Y-%m-%d")
                day_start_ts = f"{day_iso_prefix}T00:00:00+00:00"
                day_end_ts = f"{day_iso_prefix}T23:59:59+00:00"

                for comp in components:
                    events = dev_by_comp.get(comp, [])
                    # Events up to end of this day
                    day_events = [e for e in events if e["timestamp"][:10] == day_iso_prefix]
                    prior_events = [e for e in events if e["timestamp"][:10] < day_iso_prefix]

                    # Initial status at start of day
                    initial_status = prior_events[-1]["current_status"] if prior_events else "UNKNOWN"

                    # Calculate uptime seconds across the 86400s day
                    # Status OK and DEGRADED count as operational uptime; UNKNOWN/OFFLINE/UNHEALTHY do not
                    total_sec = 86400.0
                    uptime_sec = 0.0

                    if not day_events:
                        if initial_status in ("OK", "DEGRADED"):
                            uptime_sec = total_sec
                        else:
                            uptime_sec = 0.0
                    else:
                        # Slice day into segments
                        cur_status = initial_status
                        cur_time_sec = 0.0
                        day_start_dt = datetime.fromisoformat(day_start_ts)

                        for ev in day_events:
                            ev_dt = datetime.fromisoformat(ev["timestamp"].replace("Z", "+00:00"))
                            seg_sec = max(0.0, min(total_sec, (ev_dt - day_start_dt).total_seconds()))
                            dur = seg_sec - cur_time_sec
                            if dur > 0 and cur_status in ("OK", "DEGRADED"):
                                uptime_sec += dur
                            cur_time_sec = seg_sec
                            cur_status = ev["current_status"]

                        # Tail segment to end of day
                        remaining_sec = total_sec - cur_time_sec
                        if remaining_sec > 0 and cur_status in ("OK", "DEGRADED"):
                            uptime_sec += remaining_sec

                    dev_rollups.append({
                        "day": day_iso_prefix,
                        "component": comp,
                        "uptime_seconds": round(uptime_sec, 2),
                        "total_seconds": total_sec,
                        "event_count": len(day_events)
                    })

                curr_d += delta_1d

            # 5. Write rollups atomically in transaction
            with con:
                # Delete existing records in recalculated window
                con.execute(
                    "DELETE FROM analytics_daily WHERE day >= ? AND day <= ?",
                    (start_day, end_day)
                )
                con.execute(
                    "DELETE FROM analytics_device_daily WHERE day >= ? AND day <= ?",
                    (start_day, end_day)
                )

                # Insert analytics_daily
                for row in combined.values():
                    con.execute("""
                        INSERT OR REPLACE INTO analytics_daily(
                            day, zone_id, severity, event_type, model_id,
                            total_incidents, resolved_count, false_alarm_count,
                            total_ack_seconds, ack_count, total_resolve_seconds, resolve_count,
                            sample_count, sum_confidence, ood_count, incorrect_count, correct_count
                        ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        row["day"], row["zone_id"], row["severity"], row["event_type"], row["model_id"],
                        row["total_incidents"], row["resolved_count"], row["false_alarm_count"],
                        row["total_ack_seconds"], row["ack_count"], row["total_resolve_seconds"], row["resolve_count"],
                        row["sample_count"], row["sum_confidence"], row["ood_count"],
                        row["incorrect_count"], row["correct_count"]
                    ))

                # Insert analytics_device_daily
                for drow in dev_rollups:
                    con.execute("""
                        INSERT OR REPLACE INTO analytics_device_daily(
                            day, component, uptime_seconds, total_seconds, event_count
                        ) VALUES(?, ?, ?, ?, ?)
                    """, (
                        drow["day"], drow["component"], drow["uptime_seconds"],
                        drow["total_seconds"], drow["event_count"]
                    ))

                # Advance high-water mark
                max_ts_row = con.execute("""
                    SELECT max(ts) as latest FROM (
                        SELECT max(created_at) as ts FROM incidents
                        UNION ALL
                        SELECT max(timestamp) as ts FROM predictions
                        UNION ALL
                        SELECT max(timestamp) as ts FROM device_health_events
                    )
                """).fetchone()
                latest_ts = (max_ts_row["latest"] if max_ts_row and max_ts_row["latest"] else utc_now())

                con.execute("""
                    INSERT OR REPLACE INTO analytics_rollup_state(rollup_name, high_water_mark, updated_at)
                    VALUES('daily_rollup', ?, ?)
                """, (latest_ts, utc_now()))

        return {
            "start_day": start_day,
            "end_day": end_day,
            "high_water_mark": latest_ts,
            "daily_rows_inserted": len(combined),
            "device_rows_inserted": len(dev_rollups),
        }
