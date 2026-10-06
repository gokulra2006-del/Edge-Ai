"""
Test Suite for Phase 6F: Safety-Policy Verification & Architectural Invariant Assurance.
========================================================================================
Validates that core platform safety invariants hold across all execution paths:
1. A Viewer cannot actuate hardware.
2. An Operator cannot resolve incidents.
3. Every Commander action is audit-logged.
4. External emergency dispatch is never automatic.
5. A RESEARCH_ONLY / CANDIDATE model can never authorize actuation or alerts.
6. A closed incident cannot be modified.
7. An unresolved critical incident cannot be deleted (retention safety).
8. A failed sensor can never increase confidence.

Includes:
- Declarative policy specification validation
- Exhaustive Role x Action permutation matrix
- Static route analysis for 100% coverage of state-changing endpoints
- Property-based sensor degradation tests
- Failure injection test proving failing an invariant fails the build.
"""
from __future__ import annotations

import json
from pathlib import Path
import pytest

from src.modules.security.permission_matrix import (
    ALL_ROLES,
    COMMANDER_ONLY,
    ENDPOINT_PERMISSIONS,
    OPS_ROLES,
    check_endpoint_permission,
)
from src.modules.security.safety_policy_checker import (
    InvariantCheckResult,
    PolicyVerificationReport,
    SafetyPolicyChecker,
)
from src.modules.core.safety_registry_gate import SafetyAwareModelRegistry
from src.modules.decision.uncertainty_fusion import UncertaintyAwareFusion


def test_declarative_policy_spec_valid():
    """Verify safety_policies.json exists, is valid JSON, and defines all 8 invariants."""
    policy_path = Path(__file__).resolve().parents[1] / "config" / "safety_policies.json"
    assert policy_path.exists(), f"Policy spec file missing: {policy_path}"

    with open(policy_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert "invariants" in data
    assert len(data["invariants"]) == 8

    inv_ids = {inv["id"] for inv in data["invariants"]}
    expected_ids = {
        "INV-01-VIEWER-NO-ACTUATION",
        "INV-02-OPERATOR-NO-RESOLVE",
        "INV-03-COMMANDER-AUDIT-LOGGED",
        "INV-04-NO-AUTOMATIC-DISPATCH",
        "INV-05-RESEARCH-MODEL-BOUNDARY",
        "INV-06-CLOSED-INCIDENT-IMMUTABLE",
        "INV-07-CRITICAL-INCIDENT-NO-DELETE",
        "INV-08-SENSOR-FAILURE-MONOTONICITY",
    }
    assert inv_ids == expected_ids


def test_exhaustive_role_action_matrix():
    """
    Exhaustive Role x Action permutation matrix check:
    Roles: VIEWER, OPERATOR, COMMANDER, ENGINEER
    Actions: Actuate Hardware, Resolve Incident, Escalate Incident, Confirm, Acknowledge
    """
    actions_to_test = [
        # (endpoint, method, authorized_roles, unauthorized_roles)
        (
            "/api/actuators/servo",
            "POST",
            {"COMMANDER", "OPERATOR"},
            {"VIEWER", "ENGINEER"},
        ),
        (
            "/api/actuators/buzzer",
            "POST",
            {"COMMANDER", "OPERATOR"},
            {"VIEWER", "ENGINEER"},
        ),
        (
            "/api/incidents/INC-1/resolve",
            "POST",
            {"COMMANDER"},
            {"OPERATOR", "VIEWER", "ENGINEER"},
        ),
        (
            "/api/incidents/INC-1/escalate",
            "POST",
            {"COMMANDER"},
            {"OPERATOR", "VIEWER", "ENGINEER"},
        ),
        (
            "/api/incidents/INC-1/acknowledge",
            "POST",
            {"COMMANDER", "OPERATOR"},
            {"VIEWER", "ENGINEER"},
        ),
        (
            "/api/incidents/INC-1/confirm",
            "POST",
            {"COMMANDER", "OPERATOR"},
            {"VIEWER", "ENGINEER"},
        ),
    ]

    for path, method, authorized, unauthorized in actions_to_test:
        for auth_role in authorized:
            ok, status, _ = check_endpoint_permission(path, method, role=auth_role)
            assert ok is True, f"Expected {auth_role} to be permitted for {method} {path}"
            assert status == 200

        for unauth_role in unauthorized:
            ok, status, _ = check_endpoint_permission(path, method, role=unauth_role)
            assert ok is False, f"Expected {unauth_role} to be FORBIDDEN for {method} {path}"
            assert status == 403, f"Expected 403 Forbidden for {unauth_role} on {method} {path}, got {status}"


def test_all_8_safety_invariants_pass():
    """Verify that all 8 core platform safety invariants strictly pass with 0 violations."""
    checker = SafetyPolicyChecker()
    report = checker.run_all_checks()

    assert report.total_invariants == 8
    assert report.passed_invariants == 8
    assert report.failed_invariants == 0
    assert report.all_passed is True

    for c in report.checks:
        assert c.passed is True, f"Invariant {c.invariant_id} failed: {c.violations}"
        assert len(c.violations) == 0


def test_state_changing_endpoint_coverage():
    """Verify static analysis check: 100% of state-changing endpoints are covered by permission rules."""
    checker = SafetyPolicyChecker()
    cov = checker.verify_state_changing_endpoints_covered()

    assert cov["coverage_pct"] == 100.0
    assert cov["all_covered"] is True
    assert len(cov["uncovered_routes"]) == 0, f"Uncovered routes found: {cov['uncovered_routes']}"


def test_failing_invariant_fails_build(monkeypatch):
    """
    Verify that failing ANY invariant causes report.all_passed to be False,
    which triggers non-zero exit in CI / CLI.
    """
    checker = SafetyPolicyChecker()

    # Simulate an invariant failure (e.g. viewer actuation allowed)
    def mock_fail_viewer():
        return InvariantCheckResult(
            invariant_id="INV-01-VIEWER-NO-ACTUATION",
            name="Viewer Actuation Guard",
            passed=False,
            details="Mock safety breach detected",
            violations=["Simulated breach: VIEWER permitted to trigger actuator"],
        )

    monkeypatch.setattr(checker, "verify_viewer_cannot_actuate", mock_fail_viewer)
    report = checker.run_all_checks()

    assert report.all_passed is False
    assert report.failed_invariants >= 1
    failed_ids = [c.invariant_id for c in report.checks if not c.passed]
    assert "INV-01-VIEWER-NO-ACTUATION" in failed_ids


def test_property_sensor_failure_never_increases_confidence():
    """
    Property-based test: sweeping across sensor confidences and health degradations,
    verify Risk(degraded) <= Risk(healthy) + 1e-6 holds unconditionally.
    """
    fusion = UncertaintyAwareFusion()
    confidences = [0.10, 0.40, 0.60, 0.85, 0.99]
    classes = ["FIRE", "ACCIDENT", "AMBULANCE"]

    for c in classes:
        for conf in confidences:
            healthy_dec = fusion.evaluate(
                predicted_class=c,
                raw_confidence=conf,
                window_history=[c] * 5,
                active_sensor_classes={"camera": c, "audio": c, "sensors": c},
                device_health_inputs={"camera": 1.0, "audio": 1.0, "sensors": 1.0},
            )

            # Degrade camera
            deg_cam = fusion.evaluate(
                predicted_class=c,
                raw_confidence=conf,
                window_history=[c] * 5,
                active_sensor_classes={"camera": c, "audio": c, "sensors": c},
                device_health_inputs={"camera": 0.0, "audio": 1.0, "sensors": 1.0},
            )
            assert deg_cam.final_risk <= healthy_dec.final_risk + 1e-6

            # Degrade audio
            deg_aud = fusion.evaluate(
                predicted_class=c,
                raw_confidence=conf,
                window_history=[c] * 5,
                active_sensor_classes={"camera": c, "audio": c, "sensors": c},
                device_health_inputs={"camera": 1.0, "audio": 0.0, "sensors": 1.0},
            )
            assert deg_aud.final_risk <= healthy_dec.final_risk + 1e-6

            # Sensor conflict / disagreement
            deg_dis = fusion.evaluate(
                predicted_class=c,
                raw_confidence=conf,
                window_history=[c] * 5,
                active_sensor_classes={"camera": c, "audio": "NORMAL", "sensors": c},
                device_health_inputs={"camera": 1.0, "audio": 1.0, "sensors": 1.0},
            )
            assert deg_dis.final_risk <= healthy_dec.final_risk + 1e-6


def test_model_registry_status_actuation_boundary():
    """
    Verifies that status field (PRODUCTION / CANDIDATE / RESEARCH_ONLY)
    is strictly enforced at the physical actuation boundary.
    """
    registry = SafetyAwareModelRegistry()

    # 1. Status = PRODUCTION
    registry.register_model(
        model_id="m_prod",
        name="Production Detector",
        version="1.0",
        sha256="hash1",
        status="PRODUCTION",
    )
    r1 = registry.evaluate_execution_safety("m_prod", "FIRE", 0.95)
    assert r1.actuators_permitted is True
    assert r1.incident_dispatch_permitted is True
    assert r1.is_shadow_only is False

    # 2. Status = CANDIDATE
    registry.register_model(
        model_id="m_cand",
        name="Candidate Detector",
        version="1.1",
        sha256="hash2",
        status="CANDIDATE",
    )
    r2 = registry.evaluate_execution_safety("m_cand", "FIRE", 0.99)
    assert r2.actuators_permitted is False
    assert r2.incident_dispatch_permitted is False
    assert r2.is_shadow_only is True
    assert any("POLICY_RESTRICTION" in v for v in r2.safety_violations)

    # 3. Status = RESEARCH_ONLY
    registry.register_model(
        model_id="m_res",
        name="Research Detector",
        version="0.1",
        sha256="hash3",
        status="RESEARCH_ONLY",
    )
    r3 = registry.evaluate_execution_safety("m_res", "FIRE", 1.00)
    assert r3.actuators_permitted is False
    assert r3.incident_dispatch_permitted is False
    assert r3.is_shadow_only is True
    assert any("POLICY_RESTRICTION" in v for v in r3.safety_violations)
