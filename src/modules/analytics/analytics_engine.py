from __future__ import annotations

import json
import math
import sqlite3
import statistics
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Sequence

from src.modules.database.governed_store import IncidentRepository, utc_now


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


class AnalyticsEngine:
    """Read-only, non-blocking historical analytics and metrics engine."""

    def __init__(self, db_path_or_repo: Path | str | IncidentRepository):
        if isinstance(db_path_or_repo, IncidentRepository):
            self.db_path = Path(db_path_or_repo.db_path)
        else:
            self.db_path = Path(db_path_or_repo)

    def _read_connection(self) -> sqlite3.Connection:
        """Open a read-only SQLite connection configured for concurrent WAL reads."""
        p = self.db_path.resolve()
        # Try URI read-only connection first
        try:
            uri = f"file:{p.as_posix()}?mode=ro"
            con = sqlite3.connect(uri, uri=True, timeout=1.0)
        except (sqlite3.OperationalError, sqlite3.DatabaseError):
            con = sqlite3.connect(str(p), timeout=1.0)
            try:
                con.execute("PRAGMA query_only = ON")
            except sqlite3.OperationalError:
                pass

        con.row_factory = sqlite3.Row
        con.execute("PRAGMA busy_timeout = 1000")
        return con

    def get_incident_summary(
        self,
        window: str = "24h",
        start_time: str | None = None,
        end_time: str | None = None,
        include_demo: bool = False
    ) -> dict[str, Any]:
        """Aggregate incident metrics over a specified time window."""
        start_iso, end_iso = resolve_window_bounds(window, start_time, end_time)
        with self._read_connection() as con:
            demo_filter = "" if include_demo else "AND is_demo = 0"
            query = f"""
                SELECT incident_id, event_type, zone_id, status, severity,
                       acknowledged_seconds, resolution_seconds, assurance_level,
                       is_demo, created_at
                FROM incidents
                WHERE created_at >= ? AND created_at <= ? {demo_filter}
                ORDER BY created_at ASC
            """
            rows = con.execute(query, (start_iso, end_iso)).fetchall()

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

            # Also count total demo incidents in window regardless of include_demo
            if not include_demo:
                demo_row = con.execute(
                    "SELECT COUNT(*) FROM incidents WHERE created_at >= ? AND created_at <= ? AND is_demo = 1",
                    (start_iso, end_iso)
                ).fetchone()
                demo_count = demo_row[0] if demo_row else 0

            mean_ack = round(statistics.mean(ack_times), 2) if ack_times else None
            median_ack = round(statistics.median(ack_times), 2) if ack_times else None
            mean_res = round(statistics.mean(res_times), 2) if res_times else None
            median_res = round(statistics.median(res_times), 2) if res_times else None

            return {
                "window": {"preset": window, "start": start_iso, "end": end_iso},
                "total_incidents": total_incidents,
                "by_status": by_status,
                "by_severity": by_severity,
                "by_event_type": by_event_type,
                "by_zone": by_zone,
                "by_assurance_level": by_assurance_level,
                "mean_acknowledgment_seconds": mean_ack,
                "median_acknowledgment_seconds": median_ack,
                "mean_resolution_seconds": mean_res,
                "median_resolution_seconds": median_res,
                "false_alarm_count": false_alarms,
                "demo_count": demo_count,
            }

    def get_incident_timeseries(
        self,
        window: str = "24h",
        start_time: str | None = None,
        end_time: str | None = None,
        bucket_interval: str = "1h",
        include_demo: bool = False
    ) -> list[dict[str, Any]]:
        """Compute time-bucketed counts for timeline and chart visualizations."""
        start_iso, end_iso = resolve_window_bounds(window, start_time, end_time)
        with self._read_connection() as con:
            demo_filter = "" if include_demo else "AND is_demo = 0"
            query = f"""
                SELECT created_at, severity, status
                FROM incidents
                WHERE created_at >= ? AND created_at <= ? {demo_filter}
                ORDER BY created_at ASC
            """
            rows = con.execute(query, (start_iso, end_iso)).fetchall()

            buckets: dict[str, dict[str, Any]] = {}
            is_daily = bucket_interval.lower() in ("1d", "day", "daily")

            for r in rows:
                dt = parse_iso_or_none(r["created_at"])
                if not dt:
                    continue
                if is_daily:
                    bucket_key = dt.strftime("%Y-%m-%dT00:00:00Z")
                else:
                    bucket_key = dt.strftime("%Y-%m-%dT%H:00:00Z")

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
        window: str = "24h",
        model_id: str | None = None,
        start_time: str | None = None,
        end_time: str | None = None
    ) -> dict[str, Any]:
        """Aggregate model accuracy, confusion matrix, false-alarm rate, and OOD metrics."""
        start_iso, end_iso = resolve_window_bounds(window, start_time, end_time)
        with self._read_connection() as con:
            model_filter = "AND p.model_id = ?" if model_id else ""
            params: list[Any] = [start_iso, end_iso]
            if model_id:
                params.append(model_id)

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
            confidences: list[float] = []
            false_alarms = 0
            confusion_matrix: dict[str, dict[str, int]] = {}
            by_model: dict[str, dict[str, Any]] = {}

            for r in rows:
                mid = r["model_id"] or "unknown_model"
                conf = float(r["confidence"])
                confidences.append(conf)

                if mid not in by_model:
                    by_model[mid] = {
                        "total": 0,
                        "evaluated": 0,
                        "correct": 0,
                        "incorrect": 0,
                        "confidences": [],
                        "ood_count": 0,
                        "false_alarms": 0,
                    }
                m_entry = by_model[mid]
                m_entry["total"] += 1
                m_entry["confidences"].append(conf)

                # Out of Distribution detection
                is_ood = False
                payload_raw = r["payload_json"] or "{}"
                try:
                    payload = json.loads(payload_raw)
                    if isinstance(payload, dict):
                        if payload.get("ood_status") == "OOD" or payload.get("is_ood"):
                            is_ood = True
                except Exception:
                    pass

                if is_ood:
                    ood_count += 1
                    m_entry["ood_count"] += 1

                # Feedback and Ground Truth evaluation
                predicted_class = (r["label"] or "UNKNOWN").upper()
                f_label = (r["feedback_label"] or "").upper()
                c_class = (r["corrected_class"] or "").upper() if r["corrected_class"] else None
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

                # False alarm tracking
                if inc_st == "FALSE_ALARM" or (f_label == "INCORRECT" and c_class == "NORMAL"):
                    false_alarms += 1
                    m_entry["false_alarms"] += 1

            accuracy = (
                round(correct_count / evaluated_count, 4)
                if evaluated_count > 0
                else None
            )
            far = (
                round(false_alarms / total_predictions, 4)
                if total_predictions > 0
                else 0.0
            )
            ood_rate = (
                round(ood_count / total_predictions, 4)
                if total_predictions > 0
                else 0.0
            )
            mean_conf = (
                round(statistics.mean(confidences), 4) if confidences else None
            )

            # Summarize by_model metrics
            model_summaries = {}
            for k, v in by_model.items():
                m_acc = round(v["correct"] / v["evaluated"], 4) if v["evaluated"] > 0 else None
                m_far = round(v["false_alarms"] / v["total"], 4) if v["total"] > 0 else 0.0
                m_ood = round(v["ood_count"] / v["total"], 4) if v["total"] > 0 else 0.0
                m_conf = round(statistics.mean(v["confidences"]), 4) if v["confidences"] else None
                model_summaries[k] = {
                    "total": v["total"],
                    "evaluated": v["evaluated"],
                    "accuracy": m_acc,
                    "false_alarm_rate": m_far,
                    "ood_rate": m_ood,
                    "mean_confidence": m_conf,
                }

            return {
                "window": {"preset": window, "start": start_iso, "end": end_iso},
                "total_predictions": total_predictions,
                "evaluated_predictions": evaluated_count,
                "correct_predictions": correct_count,
                "incorrect_predictions": incorrect_count,
                "accuracy": accuracy,
                "false_alarm_rate": far,
                "ood_prediction_count": ood_count,
                "ood_rate": ood_rate,
                "mean_confidence": mean_conf,
                "confusion_matrix": confusion_matrix,
                "by_model": model_summaries,
            }

    def get_drift_analytics(
        self,
        window: str = "24h",
        model_id: str | None = None,
        start_time: str | None = None,
        end_time: str | None = None
    ) -> dict[str, Any]:
        """Historical model drift progression and PSI metrics."""
        start_iso, end_iso = resolve_window_bounds(window, start_time, end_time)
        with self._read_connection() as con:
            model_filter = "AND model_id = ?" if model_id else ""
            params: list[Any] = [start_iso, end_iso]
            if model_id:
                params.append(model_id)

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

                psi_val = metrics.get("psi")
                if psi_val is not None:
                    psi_progression.append({
                        "model_id": mid,
                        "timestamp": r["timestamp"],
                        "psi": psi_val,
                        "status": st
                    })

            return {
                "window": {"preset": window, "start": start_iso, "end": end_iso},
                "total_snapshots": len(timeline),
                "status_distribution": status_distribution,
                "latest_status_by_model": latest_status,
                "psi_progression": psi_progression,
                "timeline": timeline,
            }

    def get_system_availability(
        self,
        window: str = "24h",
        start_time: str | None = None,
        end_time: str | None = None
    ) -> dict[str, Any]:
        """Compute system & component uptime and assurance-level distribution."""
        start_iso, end_iso = resolve_window_bounds(window, start_time, end_time)
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
                (start_iso, end_iso)
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

            # Compute uptime per component
            for comp, c_data in components.items():
                tot = c_data["total_events"]
                avail = c_data["ok_events"] + c_data["degraded_events"]
                c_data["availability_pct"] = round((avail / tot) * 100.0, 2) if tot > 0 else 100.0

            overall_pct = (
                round((available_events / total_events) * 100.0, 2)
                if total_events > 0
                else 100.0
            )

            # 2. Assurance-level distributions
            inc_assurance_rows = con.execute(
                """
                SELECT coalesce(assurance_level, 'FULL') as lvl, count(*) as cnt
                FROM incidents
                WHERE created_at >= ? AND created_at <= ?
                GROUP BY lvl
                """,
                (start_iso, end_iso)
            ).fetchall()
            incident_assurance = {r["lvl"]: r["cnt"] for r in inc_assurance_rows}

            pred_assurance_rows = con.execute(
                """
                SELECT coalesce(assurance_level, 'FULL') as lvl, count(*) as cnt
                FROM predictions
                WHERE timestamp >= ? AND timestamp <= ?
                GROUP BY lvl
                """,
                (start_iso, end_iso)
            ).fetchall()
            prediction_assurance = {r["lvl"]: r["cnt"] for r in pred_assurance_rows}

            return {
                "window": {"preset": window, "start": start_iso, "end": end_iso},
                "overall_availability_pct": overall_pct,
                "components": components,
                "incident_assurance_distribution": incident_assurance,
                "prediction_assurance_distribution": prediction_assurance,
            }

    def get_operator_analytics(
        self,
        window: str = "24h",
        start_time: str | None = None,
        end_time: str | None = None
    ) -> dict[str, Any]:
        """Operator actions, response audit trails, and feedback metrics."""
        start_iso, end_iso = resolve_window_bounds(window, start_time, end_time)
        with self._read_connection() as con:
            actions_rows = con.execute(
                """
                SELECT id, incident_id, timestamp, operator_id, action, approved, payload_json
                FROM operator_actions
                WHERE timestamp >= ? AND timestamp <= ?
                ORDER BY timestamp ASC
                """,
                (start_iso, end_iso)
            ).fetchall()

            total_actions = len(actions_rows)
            approved_actions = 0
            by_operator: dict[str, dict[str, Any]] = {}
            by_action_type: dict[str, int] = {}

            for ar in actions_rows:
                op = ar["operator_id"] or "system"
                act = ar["action"] or "unknown"
                appr = bool(ar["approved"])

                if appr:
                    approved_actions += 1

                by_action_type[act] = by_action_type.get(act, 0) + 1

                if op not in by_operator:
                    by_operator[op] = {
                        "actions": 0,
                        "approved": 0,
                        "notes_count": 0,
                        "feedback_count": 0,
                    }
                by_operator[op]["actions"] += 1
                if appr:
                    by_operator[op]["approved"] += 1

            # Count notes per operator
            notes_rows = con.execute(
                """
                SELECT operator_id, count(*) as cnt
                FROM incident_notes
                WHERE timestamp >= ? AND timestamp <= ?
                GROUP BY operator_id
                """,
                (start_iso, end_iso)
            ).fetchall()
            for nr in notes_rows:
                op = nr["operator_id"]
                if op not in by_operator:
                    by_operator[op] = {"actions": 0, "approved": 0, "notes_count": 0, "feedback_count": 0}
                by_operator[op]["notes_count"] += nr["cnt"]

            # Count feedback per operator
            feedback_rows = con.execute(
                """
                SELECT operator_id, count(*) as cnt
                FROM prediction_feedback
                WHERE timestamp >= ? AND timestamp <= ?
                GROUP BY operator_id
                """,
                (start_iso, end_iso)
            ).fetchall()
            for fr in feedback_rows:
                op = fr["operator_id"]
                if op not in by_operator:
                    by_operator[op] = {"actions": 0, "approved": 0, "notes_count": 0, "feedback_count": 0}
                by_operator[op]["feedback_count"] += fr["cnt"]

            approval_rate = (
                round(approved_actions / total_actions, 4)
                if total_actions > 0
                else 1.0
            )

            return {
                "window": {"preset": window, "start": start_iso, "end": end_iso},
                "total_actions": total_actions,
                "approved_actions": approved_actions,
                "approval_rate": approval_rate,
                "by_action_type": by_action_type,
                "by_operator": by_operator,
            }

    def get_paginated_incidents(
        self,
        page: int = 1,
        page_size: int = 20,
        status: str | None = None,
        severity: str | None = None,
        zone_id: str | None = None,
        event_type: str | None = None,
        window: str = "24h",
        start_time: str | None = None,
        end_time: str | None = None,
        include_demo: bool = False
    ) -> dict[str, Any]:
        """Paginated incidents with non-blocking read and bound checks."""
        page = max(1, int(page))
        page_size = min(max(1, int(page_size)), 200)
        offset = (page - 1) * page_size

        start_iso, end_iso = resolve_window_bounds(window, start_time, end_time)
        with self._read_connection() as con:
            conditions = ["created_at >= ?", "created_at <= ?"]
            params: list[Any] = [start_iso, end_iso]

            if not include_demo:
                conditions.append("is_demo = 0")
            if status:
                conditions.append("status = ?")
                params.append(status.upper())
            if severity:
                conditions.append("severity = ?")
                params.append(severity.upper())
            if zone_id:
                conditions.append("zone_id = ?")
                params.append(zone_id)
            if event_type:
                conditions.append("event_type = ?")
                params.append(event_type.upper())

            where_clause = " WHERE " + " AND ".join(conditions)

            # Count total
            total_row = con.execute(f"SELECT COUNT(*) FROM incidents {where_clause}", tuple(params)).fetchone()
            total_items = total_row[0] if total_row else 0
            total_pages = math.ceil(total_items / page_size) if total_items > 0 else 1

            # Fetch page items
            query = f"""
                SELECT incident_id, incident_uuid, event_type, zone_id, status,
                       created_at, updated_at, outcome, risk_level, severity,
                       acknowledged_seconds, resolution_seconds, temporal_state,
                       ood_status, is_demo, assurance_level, version
                FROM incidents
                {where_clause}
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
            """
            fetch_params = tuple(params + [page_size, offset])
            rows = con.execute(query, fetch_params).fetchall()
            items = [dict(r) for r in rows]

            return {
                "page": page,
                "page_size": page_size,
                "total_items": total_items,
                "total_pages": total_pages,
                "items": items,
            }

    def get_paginated_predictions(
        self,
        page: int = 1,
        page_size: int = 20,
        model_id: str | None = None,
        incident_id: str | None = None,
        window: str = "24h",
        start_time: str | None = None,
        end_time: str | None = None
    ) -> dict[str, Any]:
        """Paginated prediction records joined with feedback."""
        page = max(1, int(page))
        page_size = min(max(1, int(page_size)), 200)
        offset = (page - 1) * page_size

        start_iso, end_iso = resolve_window_bounds(window, start_time, end_time)
        with self._read_connection() as con:
            conditions = ["p.timestamp >= ?", "p.timestamp <= ?"]
            params: list[Any] = [start_iso, end_iso]

            if model_id:
                conditions.append("p.model_id = ?")
                params.append(model_id)
            if incident_id:
                conditions.append("p.incident_id = ?")
                params.append(incident_id)

            where_clause = " WHERE " + " AND ".join(conditions)

            total_row = con.execute(f"SELECT COUNT(*) FROM predictions p {where_clause}", tuple(params)).fetchone()
            total_items = total_row[0] if total_row else 0
            total_pages = math.ceil(total_items / page_size) if total_items > 0 else 1

            query = f"""
                SELECT p.id, p.incident_id, p.timestamp, p.label, p.confidence,
                       p.model_id, p.assurance_level,
                       f.label as feedback_label, f.corrected_class, f.operator_id,
                       f.comment as feedback_comment
                FROM predictions p
                LEFT JOIN prediction_feedback f ON p.id = f.prediction_id
                {where_clause}
                ORDER BY p.timestamp DESC
                LIMIT ? OFFSET ?
            """
            fetch_params = tuple(params + [page_size, offset])
            rows = con.execute(query, fetch_params).fetchall()
            items = [dict(r) for r in rows]

            return {
                "page": page,
                "page_size": page_size,
                "total_items": total_items,
                "total_pages": total_pages,
                "items": items,
            }
