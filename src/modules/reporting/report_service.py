"""Orchestrates compliant report generation, manifest registration, and audit logging."""

from __future__ import annotations
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.config.settings import CONFIG
from src.modules.database.governed_store import IncidentRepository, utc_now
from src.modules.analytics.analytics_engine import AnalyticsEngine
from src.modules.reporting.templates import (
    render_monthly_operations_template,
    render_model_assurance_template,
    render_drift_report_template,
    render_device_health_template,
    render_evidence_index_template,
)
from src.modules.reporting.pdf_exporter import generate_pdf_from_report_data
from src.modules.reporting.csv_exporter import export_incidents_csv
from src.modules.reporting.evidence_verifier import compute_sha256


ROLE_ALLOWED_REPORTS = {
    "COMMANDER": {"monthly", "assurance", "drift", "health", "evidence", "csv"},
    "OPERATOR": {"monthly", "csv"},
    "ENGINEER": {"assurance", "drift", "health"},
    "VIEWER": set(),
}


class PermissionDenied(Exception):
    pass


class ReportService:
    """Enterprise report generator with audit trail logging and manifest registration."""

    def __init__(self, repository: IncidentRepository, reports_dir: Path | str | None = None):
        self.repository = repository
        self.reports_dir = Path(reports_dir) if reports_dir else Path("reports")
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        self.manifest_path = self.reports_dir / "manifest.json"
        self.analytics = AnalyticsEngine(repository)

    def _ensure_role_permitted(self, role: str, report_type: str) -> None:
        role_clean = (role or "").upper()
        allowed = ROLE_ALLOWED_REPORTS.get(role_clean, set())
        if report_type.lower() not in allowed:
            raise PermissionDenied(
                f"Role '{role_clean}' is not authorized to generate or download '{report_type}' reports."
            )

    def _update_manifest(self, record: dict[str, Any]) -> None:
        manifest = []
        if self.manifest_path.exists():
            try:
                manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
            except Exception:
                manifest = []
        manifest.append(record)
        self.manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")

    def _audit_log(self, operator_id: str, report_type: str, details: dict[str, Any]) -> None:
        payload = json.dumps(details, sort_keys=True)
        self.repository.writer.submit(
            lambda db: db.execute(
                "INSERT INTO operator_actions(incident_id, timestamp, operator_id, action, approved, payload_json) VALUES(?, ?, ?, ?, 1, ?)",
                ("SYSTEM", utc_now(), operator_id, f"generate_report_{report_type}", payload),
            )
        )

    def generate(
        self,
        report_type: str,
        operator_id: str = "commander",
        role: str = "COMMANDER",
        month: str | None = None,
        as_pdf: bool = False,
        extra_params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Generate requested report, persist to disk, record in manifest, and log audit action."""
        rep_type = report_type.lower().strip()
        self._ensure_role_permitted(role, rep_type)
        now_dt = datetime.now(timezone.utc)
        ts_slug = now_dt.strftime("%Y%m%d_%H%M%S")
        report_id = f"REP-{rep_type.upper()}-{ts_slug}-{uuid.uuid4().hex[:6]}"

        extra = extra_params or {}
        html_content = ""
        report_data: dict[str, Any] = {}
        filename_base = f"{rep_type}_report_{ts_slug}"

        if rep_type == "monthly":
            m_target = month or now_dt.strftime("%Y-%m")
            filename_base = f"operations_report_{m_target}"
            start_iso = f"{m_target}-01T00:00:00+00:00"
            # Approx month end
            end_iso = f"{m_target}-31T23:59:59+00:00"
            summary = self.analytics.get_incident_summary(start_time=start_iso, end_time=end_iso, include_demo=False)
            avail = self.analytics.get_system_availability(start_time=start_iso, end_time=end_iso)

            with self.analytics._read_connection() as con:
                zone_rows = con.execute("""
                    SELECT zone_id,
                           count(*) as total,
                           sum(case when severity in ('CRITICAL', 'HIGH') then 1 else 0 end) as severe_count,
                           sum(case when status not in ('RESOLVED', 'CLOSED', 'FALSE_ALARM') then 1 else 0 end) as active_count
                    FROM incidents
                    WHERE created_at >= ? AND created_at <= ? AND is_demo = 0
                    GROUP BY zone_id
                """, (start_iso, end_iso)).fetchall()

            zones = []
            for zr in zone_rows:
                tot = zr["total"]
                sev_c = zr["severe_count"] or 0
                act_c = zr["active_count"] or 0
                r_lvl = "CRITICAL" if sev_c >= 3 or act_c >= 2 else ("HIGH" if sev_c >= 1 else ("MEDIUM" if tot >= 3 else "LOW"))
                zones.append({
                    "zone_id": zr["zone_id"],
                    "total_incidents": tot,
                    "severe_incidents": sev_c,
                    "active_incidents": act_c,
                    "risk_level": r_lvl,
                })

            total_inc = summary["total_incidents"]
            act_inc = sum(v for k, v in summary["by_status"].items() if k not in ("RESOLVED", "CLOSED", "FALSE_ALARM"))
            res_inc = summary["by_status"].get("RESOLVED", 0) + summary["by_status"].get("CLOSED", 0)
            far_count = summary["false_alarm_count"]
            far_rate = round((far_count / total_inc) * 100.0, 1) if total_inc > 0 else 0.0

            report_data = {
                "month": m_target,
                "kpis": {
                    "total_incidents": total_inc,
                    "active_incidents": act_inc,
                    "resolved_incidents": res_inc,
                    "false_alarms": far_count,
                    "false_alarm_rate_pct": far_rate,
                    "mtta_seconds": summary["mean_acknowledgment_seconds"],
                    "mttr_seconds": summary["mean_resolution_seconds"],
                    "system_availability_pct": avail["overall_availability_pct"],
                },
                "summary": summary,
                "zones": zones,
                "availability": avail,
            }
            html_content = render_monthly_operations_template(report_data)

        elif rep_type == "assurance":
            perf = self.analytics.get_model_performance(window="30d")
            with self.analytics._read_connection() as con:
                models = [dict(r) for r in con.execute("SELECT * FROM models ORDER BY model_id").fetchall()]
            report_data = {
                "performance": perf,
                "models": models,
            }
            html_content = render_model_assurance_template(report_data)

        elif rep_type == "drift":
            drift_data = self.analytics.get_drift_analytics(window="30d")
            report_data = {"drift": drift_data}
            html_content = render_drift_report_template(report_data)

        elif rep_type == "health":
            avail = self.analytics.get_system_availability(window="30d")
            report_data = {"availability": avail}
            html_content = render_device_health_template(report_data)

        elif rep_type == "evidence":
            with self.analytics._read_connection() as con:
                ev_rows = [dict(r) for r in con.execute("SELECT * FROM evidence ORDER BY id DESC").fetchall()]
            report_data = {"evidence": ev_rows}
            html_content = render_evidence_index_template(report_data)

        elif rep_type == "csv":
            target_csv = self.reports_dir / f"incidents_{ts_slug}.csv"
            export_incidents_csv(
                repository=self.repository,
                target_path=target_csv,
                start_time=extra.get("start_time"),
                end_time=extra.get("end_time"),
                zone_id=extra.get("zone_id"),
                severity=extra.get("severity"),
                include_demo=extra.get("include_demo", False),
            )
            file_sha = compute_sha256(target_csv)
            manifest_rec = {
                "report_id": report_id,
                "report_type": "csv",
                "filename": target_csv.name,
                "format": "csv",
                "sha256": file_sha,
                "file_size": target_csv.stat().st_size,
                "generated_at": utc_now(),
                "generated_by": operator_id,
                "role": role,
            }
            self._update_manifest(manifest_rec)
            self._audit_log(operator_id, "csv", manifest_rec)
            return {"status": "SUCCESS", "report": manifest_rec, "path": str(target_csv)}

        else:
            raise ValueError(f"Unknown report type: {report_type}")

        # Write primary print-friendly HTML
        html_file = self.reports_dir / f"{filename_base}.html"
        html_file.write_text(html_content, encoding="utf-8")
        primary_file = html_file
        doc_format = "html"

        # Attempt PDF generation if requested
        if as_pdf:
            pdf_file = self.reports_dir / f"{filename_base}.pdf"
            generated_pdf = generate_pdf_from_report_data(
                title=f"Sentinel-AI {rep_type.title()} Report",
                data=report_data,
                target_path=pdf_file,
                report_type=rep_type,
            )
            if generated_pdf and generated_pdf.exists():
                primary_file = generated_pdf
                doc_format = "pdf"

        file_sha = compute_sha256(primary_file)
        manifest_rec = {
            "report_id": report_id,
            "report_type": rep_type,
            "filename": primary_file.name,
            "format": doc_format,
            "sha256": file_sha,
            "file_size": primary_file.stat().st_size,
            "generated_at": utc_now(),
            "generated_by": operator_id,
            "role": role,
            "parameters": extra,
        }

        self._update_manifest(manifest_rec)
        self._audit_log(operator_id, rep_type, manifest_rec)

        return {
            "status": "SUCCESS",
            "report": manifest_rec,
            "path": str(primary_file),
            "html_path": str(html_file),
        }

    def list_reports(self) -> list[dict[str, Any]]:
        """List all generated reports recorded in manifest."""
        if not self.manifest_path.exists():
            return []
        try:
            return json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except Exception:
            return []


_REPORT_SERVICE_SINGLETON: ReportService | None = None


def get_report_service(repo: IncidentRepository | None = None) -> ReportService:
    global _REPORT_SERVICE_SINGLETON
    if _REPORT_SERVICE_SINGLETON is None:
        if repo is None:
            repo = IncidentRepository(Path(CONFIG.db_path))
        _REPORT_SERVICE_SINGLETON = ReportService(repo)
    return _REPORT_SERVICE_SINGLETON
