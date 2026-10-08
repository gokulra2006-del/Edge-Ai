"""Canonical Role-Permission Matrix for Sentinel-AI Edge API.

Every endpoint and method registered in the platform MUST have an explicit rule here.
Regression tests verify that any route added to app.py without a rule causes an immediate test failure.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Set, Tuple

ALL_ROLES: Set[str] = {"COMMANDER", "OPERATOR", "ENGINEER", "VIEWER"}
COMMANDER_ONLY: Set[str] = {"COMMANDER"}
OPS_ROLES: Set[str] = {"COMMANDER", "OPERATOR"}
TECH_ROLES: Set[str] = {"COMMANDER", "ENGINEER"}
TRIAGE_ROLES: Set[str] = {"COMMANDER", "OPERATOR", "ENGINEER"}
PUBLIC: Set[str] = {"*"}  # Unauthenticated public access permitted

# Canonical endpoint permission registry:
# Tuple format: (HTTP_METHOD, URL_REGEX_PATTERN, ALLOWED_ROLES_SET, DESCRIPTION)
ENDPOINT_PERMISSIONS: List[Tuple[str, str, Set[str], str]] = [
    # 1. Static Web Assets & Public Status
    ("GET", r"^/$", PUBLIC, "Dashboard home page"),
    ("GET", r"^/index\.html$", PUBLIC, "Dashboard index page"),
    ("GET", r"^/app\.js$", PUBLIC, "Dashboard client JS"),
    ("GET", r"^/chart\.min\.js$", PUBLIC, "Offline chart engine JS"),
    ("GET", r"^/style\.css$", PUBLIC, "Dashboard stylesheet"),
    ("GET", r"^/api/live$", PUBLIC, "System liveness heartbeat"),
    ("GET", r"^/api/events$", PUBLIC, "Recent events feed"),
    ("GET", r"^/api/telemetry$", PUBLIC, "Raw sensor telemetry feed"),
    ("GET", r"^/api/alerts$", PUBLIC, "Active emergency alerts"),
    ("GET", r"^/api/response-plan$", PUBLIC, "Live response action plan"),
    ("GET", r"^/api/intersections$", PUBLIC, "Multi-intersection state"),
    ("GET", r"^/api/near_miss$", PUBLIC, "Predictive TTC statistics"),
    ("GET", r"^/healthz$", PUBLIC, "Liveness probe for supervisors"),
    ("GET", r"^/readyz$", PUBLIC, "Readiness probe for supervisors"),
    ("GET", r"^/api/system/version$", PUBLIC, "Version and build metadata"),
    ("GET", r"^/api/system/health$", PUBLIC, "System health summary"),
    ("GET", r"^/api/device/health$", PUBLIC, "Hardware device status"),
    ("GET", r"^/api/camera/stream$", PUBLIC, "Live camera MJPEG stream"),
    ("GET", r"^/api/camera/status$", PUBLIC, "Camera driver telemetry"),
    ("GET", r"^/api/audio/status$", PUBLIC, "Microphone driver telemetry"),
    ("GET", r"^/api/sensors/(temperature|humidity|imu|gps|gas)$", PUBLIC, "Hardware sensor streams"),
    ("GET", r"^/api/actuators/leds$", PUBLIC, "Actuator indicators telemetry"),
    ("GET", r"^/api/dvr/video/.*$", PUBLIC, "DVR video clip streaming"),
    ("GET", r"^/api/report.*$", PUBLIC, "Automated forensic incident dossier report"),

    # 2. Authentication & Admin Setup
    ("GET", r"^/api/auth/setup-status$", PUBLIC, "Check first-run admin setup status"),
    ("POST", r"^/api/auth/setup-admin$", PUBLIC, "First-run initial admin creation"),
    ("POST", r"^/api/auth/login$", PUBLIC, "Operator authentication"),
    ("POST", r"^/api/auth/logout$", ALL_ROLES, "Operator logout & session invalidation"),
    ("GET", r"^/api/auth/me$", ALL_ROLES, "Current authenticated operator details"),
    ("GET", r"^/api/auth/users$", COMMANDER_ONLY, "List operator user accounts"),
    ("POST", r"^/api/auth/users$", COMMANDER_ONLY, "Create operator user account"),
    ("DELETE", r"^/api/auth/users/.*$", COMMANDER_ONLY, "Delete operator user account"),

    # 3. Governed Incident Store & Audit Ledger
    ("GET", r"^/api/governed/incidents$", ALL_ROLES, "List governed incidents"),
    ("GET", r"^/api/governed/incident/[^/]+$", ALL_ROLES, "Governed incident details & timeline"),
    ("GET", r"^/api/governed/models$", ALL_ROLES, "Model registry entries"),
    ("GET", r"^/api/governed/evidence/[^/]+$", ALL_ROLES, "Forensic evidence package details"),

    # 4. Review Queue & Feedback
    ("GET", r"^/api/review/queue$", TRIAGE_ROLES, "Pending review predictions queue"),
    ("POST", r"^/api/review/claim$", TRIAGE_ROLES, "Claim prediction for review"),
    ("POST", r"^/api/review/feedback$", TRIAGE_ROLES, "Submit prediction review feedback"),

    # 5. Incident Lifecycle & Workflow Actions
    ("POST", r"^/api/incidents/[^/]+/acknowledge$", OPS_ROLES, "Acknowledge incident"),
    ("POST", r"^/api/incidents/[^/]+/confirm$", OPS_ROLES, "Confirm verified emergency"),
    ("POST", r"^/api/incidents/[^/]+/false_alarm$", OPS_ROLES, "Mark false alarm"),
    ("POST", r"^/api/incidents/[^/]+/notes?$", OPS_ROLES, "Append operator note"),
    ("POST", r"^/api/incidents/[^/]+/escalate$", COMMANDER_ONLY, "Escalate to municipal emergency services"),
    ("POST", r"^/api/incidents/[^/]+/resolve$", COMMANDER_ONLY, "Close and resolve emergency incident"),

    # 6. Stream & Ingestion Control
    ("POST", r"^/api/monitoring/stream/control$", OPS_ROLES, "Start / stop camera or audio ingestion"),
    ("POST", r"^/api/monitoring/stream/source$", OPS_ROLES, "Configure stream hardware source"),
    ("POST", r"^/api/trigger_scenario$", OPS_ROLES, "Trigger interactive simulation scenario"),

    # 7. System Monitoring & Resilience
    ("GET", r"^/api/monitoring/health$", ALL_ROLES, "Device health transitions & availability"),
    ("GET", r"^/api/monitoring/drift$", ALL_ROLES, "Model drift metrics & PSI baselines"),
    ("GET", r"^/api/monitoring/streams$", ALL_ROLES, "Ingestion streams status"),
    ("GET", r"^/api/monitoring/outbox$", ALL_ROLES, "Offline sync outbox status"),

    # 8. Operational Analytics & Intelligence (Phase 5A/5B/6C)
    ("GET", r"^/api/analytics/overview$", ALL_ROLES, "Operations overview KPI metrics"),
    ("GET", r"^/api/analytics/trends$", ALL_ROLES, "Incident volume timeseries trends"),
    ("GET", r"^/api/analytics/zones$", ALL_ROLES, "Zone risk assessment"),
    ("GET", r"^/api/analytics/models$", ALL_ROLES, "Model assurance metrics & confusion matrix"),
    ("GET", r"^/api/analytics/availability$", ALL_ROLES, "Subsystem availability breakdown"),
    ("GET", r"^/api/analytics/outbox(-history)?$", ALL_ROLES, "Outbox replay sync history"),
    ("GET", r"^/api/calibration/metrics$", ALL_ROLES, "Confidence calibration ECE, MCE, and Brier metrics"),
    ("GET", r"^/api/calibration/diagram$", ALL_ROLES, "Reliability diagram data and zone calibration breakdown"),
    ("GET", r"^/api/replay/timeline$", ALL_ROLES, "Digital twin incident replay timeline and risk trajectory"),
    ("POST", r"^/api/replay/execute$", ALL_ROLES, "Execute sandboxed counterfactual incident replay"),
    ("GET", r"^/api/counterfactual/explain$", ALL_ROLES, "Counterfactual decision explanations and ablation sensitivity"),
    ("GET", r"^/api/incident/timeline$", ALL_ROLES, "Explainable multi-modal decision timeline (Phase 6M)"),
    ("GET", r"^/api/incident/timeline/print$", ALL_ROLES, "Offline printable explainable decision timeline report (Phase 6M)"),
    ("GET", r"^/api/incident/safety-contract$", ALL_ROLES, "Visible safety contract details (Phase 6N)"),
    ("POST", r"^/api/response-plan/approve$", OPS_ROLES, "Approve proposed action in response plan (Phase 6N)"),
    ("GET", r"^/api/incident/availability-matrix$", ALL_ROLES, "Sensor availability matrix (Phase 6O)"),
    ("POST", r"^/api/replay/hypothetical$", OPS_ROLES, "Hypothetical replay with custom thresholds (Phase 6O)"),

    # 9. Reporting and Exports (Phase 5C)
    ("GET", r"^/api/reports/csv/incidents$", OPS_ROLES, "Export sanitized incident CSV"),
    ("POST", r"^/api/reports/generate$", TRIAGE_ROLES, "Generate operational, drift, or assurance report"),
    ("GET", r"^/api/reports/download/.*$", TRIAGE_ROLES, "Download generated report file"),
    ("GET", r"^/api/reports/list$", TRIAGE_ROLES, "List available report files"),
    ("POST", r"^/api/evidence/verify$", TECH_ROLES, "Verify forensic evidence SHA-256 digests"),

    # 10. Data Retention & Storage Safety (Phase 5D)
    ("GET", r"^/api/storage/status$", ALL_ROLES, "Storage volume utilization & margins"),
    ("POST", r"^/api/storage/cleanup$", TECH_ROLES, "Execute retention cleanup policies"),
    ("POST", r"^/api/storage/checkpoint$", TECH_ROLES, "Execute SQLite WAL checkpoint"),
    ("GET", r"^/api/storage/cleanup-logs$", TECH_ROLES, "View storage cleanup audit log"),

    # 11. Core Auxiliary & Interactive Endpoints
    ("GET", r"^/api/status$", PUBLIC, "System status summary"),
    ("GET", r"^/api/assurance$", PUBLIC, "Model assurance summary"),
    ("GET", r"^/api/assessment$", PUBLIC, "Live state assessment"),
    ("GET", r"^/api/hardware$", PUBLIC, "Hardware subsystem status"),
    ("GET", r"^/api/hardware/mode$", OPS_ROLES, "Hardware operational mode status"),
    ("POST", r"^/api/hardware/mode$", OPS_ROLES, "Hardware operational mode switcher"),
    ("GET", r"^/api/actuators/(servo|buzzer)$", OPS_ROLES, "Hardware actuator telemetry"),
    ("POST", r"^/api/actuators/(servo|buzzer)$", OPS_ROLES, "Hardware actuator control"),
    ("GET", r"^/api/recordings(/.*)?$", ALL_ROLES, "Blackbox recordings directory"),
    ("GET", r"^/api/acknowledge_alert$", OPS_ROLES, "Interactive alert acknowledgment"),
    ("POST", r"^/api/acknowledge_alert$", OPS_ROLES, "Interactive alert acknowledgment"),
    ("GET", r"^/api/deep_rules/catalog$", ALL_ROLES, "Deep rule engine catalog"),
    ("GET", r"^/api/deep_rules/evaluate$", ALL_ROLES, "Deep rule engine evaluation"),
    ("POST", r"^/api/deep_rules/evaluate$", ALL_ROLES, "Deep rule engine evaluation"),
    ("GET", r"^/api/datasets/catalog$", ALL_ROLES, "Dataset catalog"),
    ("GET", r"^/api/retraining-manifest$", TRIAGE_ROLES, "Retraining dataset manifest"),
    ("GET", r"^/api/review-queue$", TRIAGE_ROLES, "Legacy review queue alias"),
    ("GET", r"^/api/incidents(/.*)?$", ALL_ROLES, "Legacy incident listing and details"),
    ("POST", r"^/api/incidents/.*$", OPS_ROLES, "Incident operations"),
    ("GET", r"^/api/predictions/.*$", TRIAGE_ROLES, "Prediction actions"),
    ("POST", r"^/api/predictions/.*$", TRIAGE_ROLES, "Prediction actions"),
    ("POST", r"^/api/firebase_config$", COMMANDER_ONLY, "Firebase cloud synchronization configuration"),
    ("GET", r"^/api/analytics/.*$", ALL_ROLES, "Analytics endpoints prefix"),

    # 12. Governed Human Feedback Loop & Retraining Proposals (Phase 6G)
    ("GET", r"^/api/governance/disagreements$", ALL_ROLES, "Inter-operator disagreement analytics"),
    ("GET", r"^/api/governance/proposals$", ALL_ROLES, "Model retraining proposals list"),
    ("POST", r"^/api/governance/proposals/generate$", TECH_ROLES, "Generate model retraining proposal"),
    ("POST", r"^/api/governance/proposals/[^/]+/approve$", TECH_ROLES, "Approve candidate model retraining proposal"),
    ("POST", r"^/api/governance/snapshots/create$", TECH_ROLES, "Create immutable dataset snapshot"),

    # 13. Drift-to-Review Closed Loop Governance (Phase 6P)
    ("GET", r"^/api/governance/drift-loops(/[^/]+)?$", ALL_ROLES, "Drift-to-review loop records and history"),
    ("POST", r"^/api/governance/drift-loops/trigger$", TECH_ROLES, "Trigger drift review loop batch"),
    ("POST", r"^/api/governance/drift-loops/evaluate$", TECH_ROLES, "Run offline candidate evaluation"),
    ("POST", r"^/api/governance/drift-loops/decide$", TECH_ROLES, "Approve or reject candidate model"),
    ("GET", r"^/api/governance/drift-loops/experiment$", ALL_ROLES, "Simulated drift recovery experiment metrics"),

    # 14. Tamper-Evident Evidence Bundles & Verification (Phase 6Q)
    ("GET", r"^/api/evidence/bundle/[^/]+$", ALL_ROLES, "Get incident evidence bundle manifest"),
    ("POST", r"^/api/evidence/bundle/[^/]+/build$", TECH_ROLES, "Build incident evidence bundle"),
    ("GET", r"^/api/evidence/verify/[^/]+$", ALL_ROLES, "Verify incident evidence bundle status"),
    ("POST", r"^/api/evidence/verify/[^/]+$", ALL_ROLES, "Verify incident evidence bundle with options"),
]


def audit_denied_action(
    repository: Any,
    operator_id: str,
    role: str,
    action: str,
    reason: str,
    endpoint: Optional[str] = None,
    method: Optional[str] = None,
    incident_id: str = "SYSTEM",
) -> None:
    """
    Audit logs every denied action or authorization failure into operator_actions ledger.
    Who, role, endpoint/action, timestamp, reason.
    """
    if not repository:
        return

    from src.modules.database.governed_store import utc_now
    import json

    ts = utc_now()
    payload = {
        "operator_id": operator_id,
        "role": role,
        "action": action,
        "endpoint": endpoint or action,
        "method": method or "UNKNOWN",
        "reason": reason,
        "timestamp": ts,
    }
    payload_str = json.dumps(payload, sort_keys=True)
    action_name = f"DENIED:{action}" if not action.startswith("DENIED:") else action

    def _write(db):
        db.execute(
            """
            INSERT OR IGNORE INTO incidents(incident_id, incident_uuid, event_type, zone_id, status, created_at, updated_at)
            VALUES(?, ?, 'AUDIT', 'SYSTEM', 'CLOSED', ?, ?)
            """,
            (incident_id, f"audit-{incident_id}", ts, ts),
        )
        db.execute(
            """
            INSERT INTO operator_actions (incident_id, timestamp, operator_id, action, approved, payload_json)
            VALUES (?, ?, ?, ?, 0, ?)
            """,
            (incident_id, ts, operator_id, action_name, payload_str),
        )

    try:
        repository.writer.submit(_write)
    except Exception:
        # Fallback for direct sqlite connections in test harnesses
        try:
            with repository._read_connection() as db:
                _write(db)
        except Exception:
            pass


def check_endpoint_permission(
    path: str,
    method: str,
    role: Optional[str] = None,
    operator_id: Optional[str] = None,
    repository: Optional[Any] = None,
) -> Tuple[bool, int, str]:
    """
    Checks if a request path and method are permitted for the given role.
    If repository is provided, any authorization denial (403 or 401) is automatically
    audit-logged to the operator_actions ledger.
    Returns: (is_permitted, status_code, message)
    """
    method_upper = method.upper()
    role_upper = role.upper() if role else None
    op_id = operator_id or (f"operator_{role_upper.lower()}" if role_upper else "unauthenticated")

    # Search for matching rule
    matched_rule = None
    for rule_method, rule_pattern, allowed_roles, desc in ENDPOINT_PERMISSIONS:
        if rule_method == method_upper and re.match(rule_pattern, path):
            matched_rule = (allowed_roles, desc)
            break

    if not matched_rule:
        # Route not registered in security matrix!
        msg = f"Endpoint {method_upper} {path} is not recognized or permitted"
        if repository and role_upper:
            audit_denied_action(
                repository=repository,
                operator_id=op_id,
                role=role_upper,
                action=f"{method_upper}:{path}",
                reason="Unrecognized or unregistered endpoint",
                endpoint=path,
                method=method_upper,
            )
        return False, 404, msg

    allowed_roles, desc = matched_rule

    # 1. Public route
    if PUBLIC == allowed_roles or "*" in allowed_roles:
        return True, 200, "OK"

    # 2. Authentication required
    if not role_upper:
        msg = "Authentication required"
        if repository:
            audit_denied_action(
                repository=repository,
                operator_id=op_id,
                role="ANONYMOUS",
                action=f"{method_upper}:{path}",
                reason=msg,
                endpoint=path,
                method=method_upper,
            )
        return False, 401, msg

    # 3. Role verification
    if role_upper in allowed_roles:
        return True, 200, "OK"

    reason = f"Role {role_upper} is not authorized for {desc}"
    if repository:
        audit_denied_action(
            repository=repository,
            operator_id=op_id,
            role=role_upper,
            action=f"{method_upper}:{path}",
            reason=reason,
            endpoint=path,
            method=method_upper,
        )

    return False, 403, reason

