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

    # 8. Operational Analytics & Intelligence (Phase 5A/5B)
    ("GET", r"^/api/analytics/overview$", ALL_ROLES, "Operations overview KPI metrics"),
    ("GET", r"^/api/analytics/trends$", ALL_ROLES, "Incident volume timeseries trends"),
    ("GET", r"^/api/analytics/zones$", ALL_ROLES, "Zone risk assessment"),
    ("GET", r"^/api/analytics/models$", ALL_ROLES, "Model assurance metrics & confusion matrix"),
    ("GET", r"^/api/analytics/availability$", ALL_ROLES, "Subsystem availability breakdown"),
    ("GET", r"^/api/analytics/outbox-history$", ALL_ROLES, "Outbox replay sync history"),

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
]


def check_endpoint_permission(
    path: str,
    method: str,
    role: Optional[str] = None,
) -> Tuple[bool, int, str]:
    """
    Checks if a request path and method are permitted for the given role.
    Returns: (is_permitted, status_code, message)
    """
    method_upper = method.upper()
    role_upper = role.upper() if role else None

    # Search for matching rule
    matched_rule = None
    for rule_method, rule_pattern, allowed_roles, desc in ENDPOINT_PERMISSIONS:
        if rule_method == method_upper and re.match(rule_pattern, path):
            matched_rule = (allowed_roles, desc)
            break

    if not matched_rule:
        # Route not registered in security matrix!
        return False, 404, f"Endpoint {method_upper} {path} is not recognized or permitted"

    allowed_roles, desc = matched_rule

    # 1. Public route
    if PUBLIC == allowed_roles or "*" in allowed_roles:
        return True, 200, "OK"

    # 2. Authentication required
    if not role_upper:
        return False, 401, "Authentication required"

    # 3. Role verification
    if role_upper in allowed_roles:
        return True, 200, "OK"

    return False, 403, f"Role {role_upper} is not authorized for {desc}"
