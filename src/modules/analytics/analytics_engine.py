from __future__ import annotations

import json
import math
import sqlite3
import statistics
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Sequence

from src.modules.database.governed_store import IncidentRepository, utc_now
from src.modules.analytics.filters import AnalyticsFilter, parse_datetime
from src.modules.analytics.rollup_engine import RollupEngine


def parse_iso_or_none(ts_str: str | None) -> datetime | None:
    if not ts_str:
        return None
    try:
        normalized = ts_str.replace("Z", "+00:00")
        return datetime.fromisoformat(normalized)
    except (ValueError, TypeError):
        return None


def resolve_window_bounds(
    window: str = "24h",
    start_time: str | None = None,
    end_time: str | None = None,
    ref_time: datetime | None = None
) -> tuple[str, str]:
    """Resolve human window or explicit timestamps into (start_iso, end_iso)."""
    now = ref_time or datetime.now(timezone.utc)
    if start_time and end_time:
        return start_time, end_time
    elif start_time and not end_time:
        return start_time, now.isoformat()
    elif end_time and not start_time:
        end_dt = parse_iso_or_none(end_time) or now
        return (end_dt - timedelta(days=1)).isoformat(), end_time

    window_clean = (window or "24h").strip().lower()
    if window_clean == "all":
        return "1970-01-01T00:00:00+00:00", "9999-12-31T23:59:59+00:00"
    elif window_clean == "7d":
        return (now - timedelta(days=7)).isoformat(), now.isoformat()
    elif window_clean == "30d":
        return (now - timedelta(days=30)).isoformat(), now.isoformat()
    elif window_clean.endswith("h"):
        try:
            hours = int(window_clean[:-1])
        except ValueError:
            hours = 24
        return (now - timedelta(hours=hours)).isoformat(), now.isoformat()
    elif window_clean.endswith("d"):
        try:
            days = int(window_clean[:-1])
        except ValueError:
            days = 1
        return (now - timedelta(days=days)).isoformat(), now.isoformat()
    else:
        return (now - timedelta(hours=24)).isoformat(), now.isoformat()


def compute_percentile(data: Sequence[float], p: float) -> float | None:
    """Compute percentile value (0.0 to 1.0) using linear interpolation."""
    if not data:
        return None
    sorted_d = sorted(data)
    idx = (len(sorted_d) - 1) * p
    f = math.floor(idx)
    c = math.ceil(idx)
    if f == c:
        return round(sorted_d[int(idx)], 2)
    val = sorted_d[f] * (c - idx) + sorted_d[c] * (idx - f)
    return round(val, 2)


def make_envelope(
    data: Any,
    filter_obj: AnalyticsFilter,
    rollup_freshness: str | None = None,
    empty_state: bool | None = None
) -> dict[str, Any]:
    """Wrap response in consistent shape with data, filters_applied, and timestamps."""
    if empty_state is None:
        if isinstance(data, dict):
            if "total_incidents" in data:
                empty_state = data["total_incidents"] == 0
            elif "total_predictions" in data:
                empty_state = data["total_predictions"] == 0
            elif "total_snapshots" in data:
                empty_state = data["total_snapshots"] == 0
            elif "total_items" in data:
                empty_state = data["total_items"] == 0
            else:
                empty_state = len(data) == 0
        elif isinstance(data, list):
            empty_state = len(data) == 0
        else:
            empty_state = data is None

    env: dict[str, Any] = {
        "data": data,
        "filters_applied": filter_obj.to_dict(),
        "generated_at": utc_now(),
        "rollup_freshness": rollup_freshness or utc_now(),
        "empty_state": empty_state,
    }
    # Unpack dictionary top-level keys for backwards-compatibility with callers/UI
    if isinstance(data, dict):
        for k, v in data.items():
            if k not in env:
                env[k] = v
    return env


class AnalyticsEngine:
    """Read-only, non-blocking historical analytics and metrics engine."""

    def __init__(self, db_path_or_repo: Path | str | IncidentRepository):
        if isinstance(db_path_or_repo, IncidentRepository):
            self.db_path = Path(db_path_or_repo.db_path)
            self._repo: IncidentRepository | None = db_path_or_repo
        else:
            self.db_path = Path(db_path_or_repo)
            self._repo = None
        self.rollup_engine = RollupEngine(self.db_path)

    def _read_connection(self) -> sqlite3.Connection:
        """Open a read-only SQLite connection configured for concurrent WAL reads."""
        p = self.db_path.resolve()
        try:
            uri = f"file:{p.as_posix()}?mode=ro"
            con = sqlite3.connect(uri, uri=True, timeout=2.0)
        except (sqlite3.OperationalError, sqlite3.DatabaseError):
            con = sqlite3.connect(str(p), timeout=2.0)
            try:
                con.execute("PRAGMA query_only = ON")
            except sqlite3.OperationalError:
                pass

        con.row_factory = sqlite3.Row
        con.execute("PRAGMA busy_timeout = 2000")
        return con

    def run_rollup(self, days_back: int = 3, force_full: bool = False) -> dict[str, Any]:
        """Trigger incremental rollup pre-aggregation."""
        return self.rollup_engine.run_rollup(days_back=days_back, force_full=force_full)

    def _normalize_filter(
        self,
        filt: AnalyticsFilter | dict[str, Any] | None = None,
        window: str = "24h",
        start_time: str | None = None,
        end_time: str | None = None,
        zone: str | None = None,
        severity: str | None = None,
        event_type: str | None = None,
        model_id: str | None = None,
        include_demo: bool = False
    ) -> AnalyticsFilter:
        if isinstance(filt, AnalyticsFilter):
            return filt
        elif isinstance(filt, dict):
            return AnalyticsFilter.from_params(filt)
        else:
            params: dict[str, Any] = {
                "window": window,
                "start_time": start_time,
                "end_time": end_time,
                "zone": zone,
                "severity": severity,
                "event_type": event_type,
                "model_id": model_id,
                "include_demo": include_demo
            }
            return AnalyticsFilter.from_params(params)

    def get_incident_summary(
        self,
        filt: AnalyticsFilter | dict[str, Any] | None = None,
        window: str = "24h",
        start_time: str | None = None,
        end_time: str | None = None,
        include_demo: bool = False,
        zone: str | None = None,
        severity: str | None = None,
        event_type: str | None = None,
        model_id: str | None = None
    ) -> dict[str, Any]:
        """
        Aggregate incident metrics: MTTA/MTTR (mean, median, p95),
        false-alarm rate, totals by severity/zone/status.
        """
        filter_obj = self._normalize_filter(
            filt, window=window, start_time=start_time, end_time=end_time,
            zone=zone, severity=severity, event_type=event_type, model_id=model_id,
            include_demo=include_demo
        )

        with self._read_connection() as con:
            conditions = ["created_at >= ?", "created_at <= ?"]
            params: list[Any] = [filter_obj.start_time, filter_obj.end_time]

            if not filter_obj.include_demo:
                conditions.append("is_demo = 0")
            if filter_obj.zone:
                conditions.append("zone_id = ?")
                params.append(filter_obj.zone)
            if filter_obj.severity:
                conditions.append("severity = ?")
                params.append(filter_obj.severity)
            if filter_obj.event_type:
                conditions.append("event_type = ?")
                params.append(filter_obj.event_type)

            where_clause = " AND ".join(conditions)
            query = f"""
                SELECT incident_id, event_type, zone_id, status, severity,
                       acknowledged_seconds, resolution_seconds, assurance_level,
                       is_demo, created_at
                FROM incidents
                WHERE {where_clause}
                ORDER BY created_at ASC
            """
            rows = con.execute(query, tuple(params)).fetchall()

            total_incidents = len(rows)
            by_status: dict[str, int] = {}
            by_severity: dict[str, int] = {}
            by_event_type: dict[str, int] = {}
            by_zone: dict[str, int] = {}
            by_assurance_level: dict[str, int] = {}
            ack_times: list[float] = []
            res_times: list[float] = []
            false_alarms = 0
            demo_count = 0

            for r in rows:
                st = (r["status"] or "UNKNOWN").upper()
                by_status[st] = by_status.get(st, 0) + 1
                if st == "FALSE_ALARM":
                    false_alarms += 1

                sev = (r["severity"] or "NORMAL").upper()
                by_severity[sev] = by_severity.get(sev, 0) + 1

                ev_type = (r["event_type"] or "UNKNOWN").upper()
                by_event_type[ev_type] = by_event_type.get(ev_type, 0) + 1

                zn = r["zone_id"] or "UNKNOWN"
                by_zone[zn] = by_zone.get(zn, 0) + 1

                al = (r["assurance_level"] or "FULL").upper()
                by_assurance_level[al] = by_assurance_level.get(al, 0) + 1

                if r["is_demo"]:
                    demo_count += 1

                if r["acknowledged_seconds"] is not None:
                    ack_times.append(float(r["acknowledged_seconds"]))
                if r["resolution_seconds"] is not None:
                    res_times.append(float(r["resolution_seconds"]))

            if not filter_obj.include_demo:
                demo_row = con.execute(
                    "SELECT COUNT(*) FROM incidents WHERE created_at >= ? AND created_at <= ? AND is_demo = 1",
                    (filter_obj.start_time, filter_obj.end_time)
                ).fetchone()
                demo_count = demo_row[0] if demo_row else 0

            mean_ack = round(statistics.mean(ack_times), 2) if ack_times else None
            median_ack = round(statistics.median(ack_times), 2) if ack_times else None
            p95_ack = compute_percentile(ack_times, 0.95)

            mean_res = round(statistics.mean(res_times), 2) if res_times else None
            median_res = round(statistics.median(res_times), 2) if res_times else None
            p95_res = compute_percentile(res_times, 0.95)

            far_rate = round((false_alarms / total_incidents) * 100.0, 2) if total_incidents > 0 else 0.0

            freshness = self.rollup_engine.get_freshness()

            core_data = {
                "window": {"preset": window, "start": filter_obj.start_time, "end": filter_obj.end_time},
                "total_incidents": total_incidents,
                "by_status": by_status,
                "by_severity": by_severity,
                "by_event_type": by_event_type,
                "by_zone": by_zone,
                "by_assurance_level": by_assurance_level,
                "mean_acknowledgment_seconds": mean_ack,
                "median_acknowledgment_seconds": median_ack,
                "p95_acknowledgment_seconds": p95_ack,
                "mean_resolution_seconds": mean_res,
                "median_resolution_seconds": median_res,
                "p95_resolution_seconds": p95_res,
                "false_alarm_count": false_alarms,
                "false_alarm_rate_pct": far_rate,
                "demo_count": demo_count,
            }

            return make_envelope(core_data, filter_obj, rollup_freshness=freshness)

    def get_incident_timeseries(
        self,
        filt: AnalyticsFilter | dict[str, Any] | None = None,
        window: str = "24h",
        start_time: str | None = None,
        end_time: str | None = None,
        bucket_interval: str = "1h",
        include_demo: bool = False,
        use_rollup: bool = True
    ) -> list[dict[str, Any]]:
        """
        Compute time-bucketed counts for timeline and chart visualizations.
        Reads from analytics_daily rollup when applicable.
        """
        filter_obj = self._normalize_filter(
            filt, window=window, start_time=start_time, end_time=end_time,
            include_demo=include_demo
        )

        with self._read_connection() as con:
            is_daily = bucket_interval.lower() in ("1d", "day", "daily")

            # Check if rollup table has data for daily aggregation
            if use_rollup and is_daily and not filter_obj.include_demo:
                c_roll = con.execute(
                    "SELECT count(*) FROM analytics_daily WHERE day >= ? AND day <= ?",
                    (filter_obj.start_date, filter_obj.end_date)
                ).fetchone()[0]

                if c_roll > 0:
                    roll_conditions = ["day >= ?", "day <= ?"]
                    r_params: list[Any] = [filter_obj.start_date, filter_obj.end_date]
                    if filter_obj.zone:
                        roll_conditions.append("zone_id = ?")
                        r_params.append(filter_obj.zone)
                    if filter_obj.severity:
                        roll_conditions.append("severity = ?")
                        r_params.append(filter_obj.severity)
                    if filter_obj.event_type:
                        roll_conditions.append("event_type = ?")
                        r_params.append(filter_obj.event_type)
                    if filter_obj.model_id:
                        roll_conditions.append("model_id = ?")
                        r_params.append(filter_obj.model_id)

                    roll_where = " AND ".join(roll_conditions)
                    roll_rows = con.execute(f"""
                        SELECT day,
                               sum(total_incidents) as total,
                               sum(case when severity='CRITICAL' then total_incidents else 0 end) as critical,
                               sum(case when severity='HIGH' then total_incidents else 0 end) as high,
                               sum(case when severity='MEDIUM' then total_incidents else 0 end) as medium,
                               sum(case when severity='LOW' then total_incidents else 0 end) as low,
                               sum(case when severity='NORMAL' then total_incidents else 0 end) as normal,
                               sum(false_alarm_count) as false_alarm
                        FROM analytics_daily
                        WHERE {roll_where}
                        GROUP BY day
                        ORDER BY day ASC
                    """, tuple(r_params)).fetchall()

                    return [
                        {
                            "bucket": f"{rr['day']}T00:00:00Z",
                            "total": rr["total"],
                            "critical": rr["critical"],
                            "high": rr["high"],
                            "medium": rr["medium"],
                            "low": rr["low"],
                            "normal": rr["normal"],
                            "false_alarm": rr["false_alarm"]
                        }
                        for rr in roll_rows
                    ]

            # Raw query fallback
            demo_filter = "" if filter_obj.include_demo else "AND is_demo = 0"
            zone_filter = f"AND zone_id = '{filter_obj.zone}'" if filter_obj.zone else ""
            sev_filter = f"AND severity = '{filter_obj.severity}'" if filter_obj.severity else ""

            query = f"""
                SELECT created_at, severity, status
                FROM incidents
                WHERE created_at >= ? AND created_at <= ? {demo_filter} {zone_filter} {sev_filter}
                ORDER BY created_at ASC
            """
            rows = con.execute(query, (filter_obj.start_time, filter_obj.end_time)).fetchall()

            buckets: dict[str, dict[str, Any]] = {}
            for r in rows:
                dt = parse_iso_or_none(r["created_at"])
                if not dt:
                    continue
                bucket_key = dt.strftime("%Y-%m-%dT00:00:00Z") if is_daily else dt.strftime("%Y-%m-%dT%H:00:00Z")

                if bucket_key not in buckets:
                    buckets[bucket_key] = {
                        "bucket": bucket_key,
                        "total": 0,
                        "critical": 0,
                        "high": 0,
                        "medium": 0,
                        "low": 0,
                        "normal": 0,
                        "false_alarm": 0
                    }

                entry = buckets[bucket_key]
                entry["total"] += 1
                sev = (r["severity"] or "NORMAL").lower()
                if sev in entry:
                    entry[sev] += 1
                if (r["status"] or "").upper() == "FALSE_ALARM":
                    entry["false_alarm"] += 1

            return sorted(buckets.values(), key=lambda b: b["bucket"])

    def get_model_performance(
        self,
        filt: AnalyticsFilter | dict[str, Any] | None = None,
        window: str = "24h",
        model_id: str | None = None,
        start_time: str | None = None,
        end_time: str | None = None
    ) -> dict[str, Any]:
        """Aggregate model accuracy, confusion matrix, false-alarm rate, OOD trends, and disagreement rate."""
        filter_obj = self._normalize_filter(
            filt, window=window, start_time=start_time, end_time=end_time, model_id=model_id
        )

        with self._read_connection() as con:
            model_filter = "AND p.model_id = ?" if filter_obj.model_id else ""
            params: list[Any] = [filter_obj.start_time, filter_obj.end_time]
            if filter_obj.model_id:
                params.append(filter_obj.model_id)

            query = f"""
                SELECT p.id, p.incident_id, p.timestamp, p.label, p.confidence,
                       p.model_id, p.payload_json, p.assurance_level,
                       f.label as feedback_label, f.corrected_class, f.operator_role,
                       inc.status as incident_status
                FROM predictions p
                LEFT JOIN prediction_feedback f ON p.id = f.prediction_id
                LEFT JOIN incidents inc ON p.incident_id = inc.incident_id
                WHERE p.timestamp >= ? AND p.timestamp <= ? {model_filter}
                ORDER BY p.timestamp ASC
            """
            rows = con.execute(query, tuple(params)).fetchall()

            total_predictions = len(rows)
            evaluated_count = 0
            correct_count = 0
            incorrect_count = 0
            ood_count = 0
            false_alarms = 0
            confidences: list[float] = []

            confusion_matrix: dict[str, dict[str, int]] = {}
            by_model: dict[str, dict[str, Any]] = {}

            # Time-bucketed confidence and OOD trends
            trends: dict[str, dict[str, Any]] = {}

            for r in rows:
                mid = r["model_id"] or "UNKNOWN"
                conf = float(r["confidence"]) if r["confidence"] is not None else 0.0
                confidences.append(conf)

                # Day bucket for trends
                dt_str = r["timestamp"][:10]
                if dt_str not in trends:
                    trends[dt_str] = {"day": dt_str, "sample_count": 0, "sum_conf": 0.0, "ood_count": 0}
                trends[dt_str]["sample_count"] += 1
                trends[dt_str]["sum_conf"] += conf

                if mid not in by_model:
                    by_model[mid] = {
                        "total": 0,
                        "evaluated": 0,
                        "correct": 0,
                        "incorrect": 0,
                        "ood_count": 0,
                        "false_alarms": 0,
                        "confidences": []
                    }

                m_entry = by_model[mid]
                m_entry["total"] += 1
                m_entry["confidences"].append(conf)

                # OOD detection
                p_json = {}
                try:
                    p_json = json.loads(r["payload_json"] or "{}")
                except Exception:
                    pass

                is_ood = p_json.get("ood_status") == "OOD"
                if is_ood:
                    ood_count += 1
                    m_entry["ood_count"] += 1
                    trends[dt_str]["ood_count"] += 1

                # Feedback evaluation
                f_label = (r["feedback_label"] or "").upper()
                c_class = (r["corrected_class"] or "").upper()
                predicted_class = (r["label"] or "UNKNOWN").upper()
                inc_st = (r["incident_status"] or "").upper()

                if f_label in ("CORRECT", "INCORRECT"):
                    evaluated_count += 1
                    m_entry["evaluated"] += 1

                    if f_label == "CORRECT":
                        correct_count += 1
                        m_entry["correct"] += 1
                        actual_class = predicted_class
                    else:
                        incorrect_count += 1
                        m_entry["incorrect"] += 1
                        actual_class = c_class or "UNKNOWN"

                    if actual_class not in confusion_matrix:
                        confusion_matrix[actual_class] = {}
                    confusion_matrix[actual_class][predicted_class] = (
                        confusion_matrix[actual_class].get(predicted_class, 0) + 1
                    )

                if inc_st == "FALSE_ALARM" or (f_label == "INCORRECT" and c_class == "NORMAL"):
                    false_alarms += 1
                    m_entry["false_alarms"] += 1

            accuracy = round(correct_count / evaluated_count, 4) if evaluated_count > 0 else None
            disagreement_rate = round((incorrect_count / evaluated_count) * 100.0, 2) if evaluated_count > 0 else 0.0
            far = round(false_alarms / total_predictions, 4) if total_predictions > 0 else 0.0
            ood_rate = round(ood_count / total_predictions, 4) if total_predictions > 0 else 0.0
            mean_conf = round(statistics.mean(confidences), 4) if confidences else None

            model_summaries = {}
            for k, v in by_model.items():
                m_acc = round(v["correct"] / v["evaluated"], 4) if v["evaluated"] > 0 else None
                m_far = round(v["false_alarms"] / v["total"], 4) if v["total"] > 0 else 0.0
                m_ood = round(v["ood_count"] / v["total"], 4) if v["total"] > 0 else 0.0
                m_conf = round(statistics.mean(v["confidences"]), 4) if v["confidences"] else None
                m_dis = round((v["incorrect"] / v["evaluated"]) * 100.0, 2) if v["evaluated"] > 0 else 0.0
                model_summaries[k] = {
                    "total": v["total"],
                    "evaluated": v["evaluated"],
                    "accuracy": m_acc,
                    "false_alarm_rate": m_far,
                    "ood_rate": m_ood,
                    "mean_confidence": m_conf,
                    "disagreement_rate_pct": m_dis,
                }

            trends_list = [
                {
                    "day": td["day"],
                    "sample_count": td["sample_count"],
                    "mean_confidence": round(td["sum_conf"] / td["sample_count"], 4) if td["sample_count"] > 0 else 0.0,
                    "ood_rate": round(td["ood_count"] / td["sample_count"], 4) if td["sample_count"] > 0 else 0.0
                }
                for td in sorted(trends.values(), key=lambda t: t["day"])
            ]

            freshness = self.rollup_engine.get_freshness()

            core_data = {
                "window": {"preset": window, "start": filter_obj.start_time, "end": filter_obj.end_time},
                "total_predictions": total_predictions,
                "evaluated_predictions": evaluated_count,
                "correct_predictions": correct_count,
                "incorrect_predictions": incorrect_count,
                "accuracy": accuracy,
                "disagreement_rate_pct": disagreement_rate,
                "false_alarm_rate": far,
                "ood_prediction_count": ood_count,
                "ood_rate": ood_rate,
                "mean_confidence": mean_conf,
                "confusion_matrix": confusion_matrix,
                "by_model": model_summaries,
                "trends": trends_list,
            }

            return make_envelope(core_data, filter_obj, rollup_freshness=freshness)

    def get_drift_analytics(
        self,
        filt: AnalyticsFilter | dict[str, Any] | None = None,
        window: str = "24h",
        model_id: str | None = None,
        start_time: str | None = None,
        end_time: str | None = None
    ) -> dict[str, Any]:
        """Historical model drift progression and PSI metrics."""
        filter_obj = self._normalize_filter(
            filt, window=window, start_time=start_time, end_time=end_time, model_id=model_id
        )

        with self._read_connection() as con:
            model_filter = "AND model_id = ?" if filter_obj.model_id else ""
            params: list[Any] = [filter_obj.start_time, filter_obj.end_time]
            if filter_obj.model_id:
                params.append(filter_obj.model_id)

            query = f"""
                SELECT id, model_id, timestamp, status, reasons_json, metrics_json,
                       sample_count, insufficient_data
                FROM drift_snapshots
                WHERE timestamp >= ? AND timestamp <= ? {model_filter}
                ORDER BY timestamp ASC
            """
            rows = con.execute(query, tuple(params)).fetchall()

            timeline: list[dict[str, Any]] = []
            status_distribution: dict[str, int] = {}
            latest_status: dict[str, dict[str, Any]] = {}
            psi_progression: list[dict[str, Any]] = []

            for r in rows:
                mid = r["model_id"]
                st = (r["status"] or "UNKNOWN").upper()
                status_distribution[st] = status_distribution.get(st, 0) + 1

                reasons = []
                try:
                    reasons = json.loads(r["reasons_json"])
                except Exception:
                    pass

                metrics = {}
                try:
                    metrics = json.loads(r["metrics_json"])
                except Exception:
                    pass

                item = {
                    "id": r["id"],
                    "model_id": mid,
                    "timestamp": r["timestamp"],
                    "status": st,
                    "sample_count": r["sample_count"],
                    "insufficient_data": bool(r["insufficient_data"]),
                    "reasons": reasons,
                    "metrics": metrics,
                }
                timeline.append(item)
                latest_status[mid] = item

                psi_val = metrics.get("psi") or metrics.get("psi_score")
                if psi_val is not None:
                    psi_progression.append({
                        "timestamp": r["timestamp"],
                        "model_id": mid,
                        "psi": float(psi_val)
                    })

            freshness = self.rollup_engine.get_freshness()

            core_data = {
                "window": {"preset": window, "start": filter_obj.start_time, "end": filter_obj.end_time},
                "total_snapshots": len(timeline),
                "status_distribution": status_distribution,
                "latest_status_by_model": latest_status,
                "psi_progression": psi_progression,
                "timeline": timeline,
            }

            return make_envelope(core_data, filter_obj, rollup_freshness=freshness)

    def get_system_availability(
        self,
        filt: AnalyticsFilter | dict[str, Any] | None = None,
        window: str = "24h",
        start_time: str | None = None,
        end_time: str | None = None
    ) -> dict[str, Any]:
        """Compute system, camera, audio, and device uptime percentages."""
        filter_obj = self._normalize_filter(
            filt, window=window, start_time=start_time, end_time=end_time
        )

        with self._read_connection() as con:
            # 1. Device health events
            health_rows = con.execute(
                """
                SELECT id, timestamp, component, previous_status, current_status,
                       reason_code, message
                FROM device_health_events
                WHERE timestamp >= ? AND timestamp <= ?
                ORDER BY timestamp ASC
                """,
                (filter_obj.start_time, filter_obj.end_time)
            ).fetchall()

            components: dict[str, dict[str, Any]] = {}
            total_events = len(health_rows)
            available_events = 0

            for hr in health_rows:
                comp = hr["component"]
                st = (hr["current_status"] or "UNKNOWN").upper()

                if comp not in components:
                    components[comp] = {
                        "total_events": 0,
                        "ok_events": 0,
                        "degraded_events": 0,
                        "down_events": 0,
                        "unknown_events": 0,
                        "last_status": st,
                    }

                c_data = components[comp]
                c_data["total_events"] += 1
                c_data["last_status"] = st

                if st == "OK":
                    c_data["ok_events"] += 1
                    available_events += 1
                elif st == "DEGRADED":
                    c_data["degraded_events"] += 1
                    available_events += 1
                elif st == "DOWN":
                    c_data["down_events"] += 1
                else:
                    c_data["unknown_events"] += 1

            for comp, c_data in components.items():
                tot = c_data["total_events"]
                avail = c_data["ok_events"] + c_data["degraded_events"]
                c_data["availability_pct"] = round((avail / tot) * 100.0, 2) if tot > 0 else 0.0

            overall_pct = (
                round((available_events / total_events) * 100.0, 2)
                if total_events > 0
                else 100.0
            )

            # 2. Assurance level distribution
            al_rows = con.execute(
                """
                SELECT assurance_level, count(*) as count
                FROM incidents
                WHERE created_at >= ? AND created_at <= ?
                GROUP BY assurance_level
                """,
                (filter_obj.start_time, filter_obj.end_time)
            ).fetchall()

            assurance_distribution = {r["assurance_level"]: r["count"] for r in al_rows}

            freshness = self.rollup_engine.get_freshness()

            core_data = {
                "window": {"preset": window, "start": filter_obj.start_time, "end": filter_obj.end_time},
                "total_events": total_events,
                "overall_availability_pct": overall_pct,
                "components": components,
                "assurance_distribution": assurance_distribution,
            }

            return make_envelope(core_data, filter_obj, rollup_freshness=freshness)

    def get_outbox_analytics(
        self,
        filt: AnalyticsFilter | dict[str, Any] | None = None,
        window: str = "24h",
        limit: int = 50
    ) -> dict[str, Any]:
        """Offline-sync outbox backlog history and backlog trends."""
        filter_obj = self._normalize_filter(filt, window=window)

        with self._read_connection() as con:
            counts_raw = con.execute(
                "SELECT status, count(*) as count FROM sync_outbox GROUP BY status"
            ).fetchall()
            counts = {"PENDING": 0, "SYNCED": 0, "DEAD_LETTER": 0}
            for cr in counts_raw:
                counts[cr["status"]] = cr["count"]

            # Hourly backlog history
            history_rows = con.execute("""
                SELECT strftime('%Y-%m-%d %H:00:00', created_at) as hour_bucket,
                       count(*) as enqueued,
                       sum(CASE WHEN status='SYNCED' THEN 1 ELSE 0 END) as synced,
                       sum(CASE WHEN status='PENDING' THEN 1 ELSE 0 END) as pending,
                       sum(CASE WHEN status='DEAD_LETTER' THEN 1 ELSE 0 END) as dead_letter
                FROM sync_outbox
                WHERE created_at >= ? AND created_at <= ?
                GROUP BY hour_bucket
                ORDER BY hour_bucket ASC
            """, (filter_obj.start_time, filter_obj.end_time)).fetchall()

            recent = [dict(r) for r in con.execute("""
                SELECT id, idempotency_key, target, payload_type, attempts, next_attempt_at,
                       status, priority, last_error, created_at, updated_at
                FROM sync_outbox
                ORDER BY id DESC
                LIMIT ?
            """, (min(limit, 200),)).fetchall()]

            freshness = self.rollup_engine.get_freshness()

            core_data = {
                "counts": counts,
                "history": [dict(hr) for hr in history_rows],
                "recent": recent,
            }

            return make_envelope(core_data, filter_obj, rollup_freshness=freshness)

    def get_operator_analytics(
        self,
        filt: AnalyticsFilter | dict[str, Any] | None = None,
        window: str = "24h",
        start_time: str | None = None,
        end_time: str | None = None
    ) -> dict[str, Any]:
        """Operator actions and workload metrics."""
        filter_obj = self._normalize_filter(filt, window=window, start_time=start_time, end_time=end_time)

        with self._read_connection() as con:
            action_rows = con.execute(
                """
                SELECT id, incident_id, timestamp, operator_id, action, approved
                FROM operator_actions
                WHERE timestamp >= ? AND timestamp <= ?
                ORDER BY timestamp ASC
                """,
                (filter_obj.start_time, filter_obj.end_time)
            ).fetchall()

            note_rows = con.execute(
                """
                SELECT id, incident_id, timestamp, operator_id, operator_role, note
                FROM incident_notes
                WHERE timestamp >= ? AND timestamp <= ?
                ORDER BY timestamp ASC
                """,
                (filter_obj.start_time, filter_obj.end_time)
            ).fetchall()

            total_actions = len(action_rows)
            approved_actions = sum(1 for a in action_rows if a["approved"])
            by_operator: dict[str, dict[str, Any]] = {}

            for a in action_rows:
                op = a["operator_id"] or "UNKNOWN"
                if op not in by_operator:
                    by_operator[op] = {"actions": 0, "approved": 0, "notes_count": 0}
                by_operator[op]["actions"] += 1
                if a["approved"]:
                    by_operator[op]["approved"] += 1

            for n in note_rows:
                op = n["operator_id"] or "UNKNOWN"
                if op not in by_operator:
                    by_operator[op] = {"actions": 0, "approved": 0, "notes_count": 0}
                by_operator[op]["notes_count"] += 1

            freshness = self.rollup_engine.get_freshness()

            core_data = {
                "window": {"preset": window, "start": filter_obj.start_time, "end": filter_obj.end_time},
                "total_actions": total_actions,
                "approved_actions": approved_actions,
                "total_notes": len(note_rows),
                "by_operator": by_operator,
            }

            return make_envelope(core_data, filter_obj, rollup_freshness=freshness)

    def get_paginated_incidents(
        self,
        filt: AnalyticsFilter | dict[str, Any] | None = None,
        page: int = 1,
        page_size: int = 50,
        window: str = "24h",
        start_time: str | None = None,
        end_time: str | None = None
    ) -> dict[str, Any]:
        """Drill-down: paginated raw incident records with hard pagination limits."""
        filter_obj = self._normalize_filter(filt, window=window, start_time=start_time, end_time=end_time)

        # Clamping bounds: page >= 1, 1 <= page_size <= 200
        page = max(1, page)
        page_size = max(1, min(page_size, 200))
        offset = (page - 1) * page_size

        with self._read_connection() as con:
            count_row = con.execute(
                "SELECT COUNT(*) FROM incidents WHERE created_at >= ? AND created_at <= ?",
                (filter_obj.start_time, filter_obj.end_time)
            ).fetchone()
            total_items = count_row[0] if count_row else 0
            total_pages = math.ceil(total_items / page_size) if total_items > 0 else 1

            rows = con.execute(
                """
                SELECT incident_id, incident_uuid, event_type, zone_id, status, severity,
                       acknowledged_seconds, resolution_seconds, assurance_level,
                       is_demo, created_at, updated_at
                FROM incidents
                WHERE created_at >= ? AND created_at <= ?
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
                """,
                (filter_obj.start_time, filter_obj.end_time, page_size, offset)
            ).fetchall()

            core_data = {
                "page": page,
                "page_size": page_size,
                "total_items": total_items,
                "total_pages": total_pages,
                "items": [dict(r) for r in rows],
            }

            return make_envelope(core_data, filter_obj)

    def get_paginated_predictions(
        self,
        filt: AnalyticsFilter | dict[str, Any] | None = None,
        page: int = 1,
        page_size: int = 50,
        window: str = "24h",
        start_time: str | None = None,
        end_time: str | None = None
    ) -> dict[str, Any]:
        """Drill-down: paginated raw prediction records with hard limits."""
        filter_obj = self._normalize_filter(filt, window=window, start_time=start_time, end_time=end_time)

        page = max(1, page)
        page_size = max(1, min(page_size, 200))
        offset = (page - 1) * page_size

        with self._read_connection() as con:
            count_row = con.execute(
                "SELECT COUNT(*) FROM predictions WHERE timestamp >= ? AND timestamp <= ?",
                (filter_obj.start_time, filter_obj.end_time)
            ).fetchone()
            total_items = count_row[0] if count_row else 0
            total_pages = math.ceil(total_items / page_size) if total_items > 0 else 1

            rows = con.execute(
                """
                SELECT id, incident_id, timestamp, label, confidence, model_id, assurance_level
                FROM predictions
                WHERE timestamp >= ? AND timestamp <= ?
                ORDER BY timestamp DESC
                LIMIT ? OFFSET ?
                """,
                (filter_obj.start_time, filter_obj.end_time, page_size, offset)
            ).fetchall()

            core_data = {
                "page": page,
                "page_size": page_size,
                "total_items": total_items,
                "total_pages": total_pages,
                "items": [dict(r) for r in rows],
            }

            return make_envelope(core_data, filter_obj)
