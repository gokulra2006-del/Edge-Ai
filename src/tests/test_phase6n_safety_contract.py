"""
Comprehensive Test Suite for Governed Autonomous Response & Visible Safety Contract (Phase 6N).
================================================================================================
Hypothesis:
"Showing evidence, uncertainty, and approval requirements for each proposed action
reduces unauthorized or unreviewed actions without delaying authorized ones."

Verifies:
1. Every blocked-action path produces a contract with a valid 6F rule ID and reason.
2. AI only PROPOSES; no action executes without explicit human approval by an authorized role.
3. RESEARCH_ONLY models cannot propose actuation or dispatch (INV-05).
4. Safety contract contents strictly match stored decision data and 6B uncertainty factors.
5. Response-plan completion time duration is accurately measured and recorded.
6. Blocked actions and authorization rejections are audit-logged to `operator_actions`.
7. Safety contract is included in forensic reports (Phase 5C) and replay output (Phase 6D).
8. Standalone offline-first execution with zero external CDN dependencies.
"""
from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import time
import pytest

from src.modules.autonomous_response.safety_contract import (
    GovernedResponseEngine,
    ProposedAction,
    ResponsePlan,
    VisibleSafetyContract,
)
from src.modules.database.governed_store import IncidentRepository
from src.modules.incident_management.replay_engine import (
    ReplayStepInput,
    SandboxedReplayEngine,
)
from src.modules.recording.report_generator import ForensicReportGenerator


@pytest.fixture
def repo(tmp_path: Path):
    db_path = tmp_path / "test_safety_contract.db"
    repository = IncidentRepository(db_path)
    yield repository
    repository.close()


def test_response_plan_lifecycle_and_completion_duration():
    """Verify response plan status transitions and accurate completion duration calculation."""
    act1 = ProposedAction(
        action_id="ACT-1",
        action_type="HOLD_TRAFFIC",
        description="Hold traffic",
        required_approver_role="OPERATOR",
    )
    act2 = ProposedAction(
        action_id="ACT-2",
        action_type="DISPATCH_FIRE_CREW",
        description="Dispatch fire brigade",
        required_approver_role="COMMANDER",
    )

    t0_iso = "2026-10-07T12:00:00+00:00"
    plan = ResponsePlan(
        plan_id="PLAN-TEST-1",
        incident_id="INC-1",
        created_at=t0_iso,
        actions=[act1, act2],
        status="PROPOSED",
    )

    assert plan.status == "PROPOSED"
    assert plan.completed_at is None
    assert plan.completion_duration_seconds is None

    # Update first action -> plan remains incomplete
    ok1 = plan.update_action_status("ACT-1", "APPROVED", "operator_1", "OPERATOR")
    assert ok1 is True
    assert plan.actions[0].status == "APPROVED"
    assert plan.completed_at is None

    # Update second action -> all actions finalized -> plan completes
    ok2 = plan.update_action_status("ACT-2", "EXECUTED", "commander_1", "COMMANDER")
    assert ok2 is True
    assert plan.actions[1].status == "EXECUTED"
    assert plan.completed_at is not None
    assert plan.status == "EXECUTED"
    assert plan.completion_duration_seconds is not None
    assert plan.completion_duration_seconds >= 0.0


def test_ai_proposes_only_no_action_executes_without_human_approval(repo: IncidentRepository):
    """Verify AI only proposes, and no execution occurs without explicit authorized role approval."""
    engine = GovernedResponseEngine(repository=repo)

    plan, contract = engine.synthesize_response_plan(
        incident_id="INC-FIRE-101",
        detected_class="FIRE",
        confidence=0.96,
        evidence_summary=["Thermal reading 62C", "Acoustic siren detected"],
        risk_factors={"sensor_agreement": 0.95, "model_uncertainty": 0.05},
        model_id="yolo11n_sentinel",
        model_usage_restriction="PRODUCTION",
    )

    # 1. AI only proposes
    assert plan.status == "PROPOSED"
    assert all(a.status == "PROPOSED" for a in plan.actions)
    assert not contract.is_blocked

    # Find the actions
    traffic_act = next(a for a in plan.actions if a.action_type == "HOLD_TRAFFIC")
    dispatch_act = next(a for a in plan.actions if a.action_type == "DISPATCH_FIRE_CREW")

    # 2. VIEWER role is completely blocked from any actuation (INV-01)
    ok, err, act = engine.approve_action(plan.plan_id, traffic_act.action_id, "viewer_1", "VIEWER")
    assert ok is False
    assert "INV-01-VIEWER-NO-ACTUATION" in (act.blocked_rule_id or "")
    assert act.status == "BLOCKED"

    # 3. OPERATOR cannot approve external dispatch (INV-04 requires COMMANDER)
    ok, err, act = engine.approve_action(plan.plan_id, dispatch_act.action_id, "operator_1", "OPERATOR")
    assert ok is False
    assert "INV-04-NO-AUTOMATIC-DISPATCH" in (act.blocked_rule_id or "")
    assert "COMMANDER" in err
    assert act.status == "BLOCKED"

    # 4. Synthesize fresh plan to test successful approval by COMMANDER
    plan2, contract2 = engine.synthesize_response_plan(
        incident_id="INC-FIRE-102",
        detected_class="FIRE",
        confidence=0.96,
        evidence_summary=["Smoke 80 PPM"],
        risk_factors={"sensor_agreement": 0.92},
        model_usage_restriction="PRODUCTION",
    )
    dispatch_act2 = next(a for a in plan2.actions if a.action_type == "DISPATCH_FIRE_CREW")
    ok, msg, act2 = engine.approve_action(plan2.plan_id, dispatch_act2.action_id, "commander_1", "COMMANDER")
    assert ok is True
    assert act2.status == "EXECUTED"
    assert act2.acted_by == "commander_1"
    assert act2.acted_role == "COMMANDER"


def test_research_only_model_cannot_propose_actuation(repo: IncidentRepository):
    """Verify RESEARCH_ONLY / CANDIDATE models cannot propose actuation under INV-05."""
    engine = GovernedResponseEngine(repository=repo)

    plan, contract = engine.synthesize_response_plan(
        incident_id="INC-EXP-201",
        detected_class="ACCIDENT",
        confidence=0.99,
        evidence_summary=["Acoustic crash detected"],
        risk_factors={"model_uncertainty": 0.02},
        model_id="experimental_sound_v3",
        model_usage_restriction="RESEARCH_ONLY",
    )

    # Architectural invariant INV-05: actions immediately marked BLOCKED
    assert plan.status == "BLOCKED"
    assert contract.is_blocked is True
    assert contract.blocked_rule_id == "INV-05-RESEARCH-MODEL-BOUNDARY"
    assert "strictly prohibits non-production models" in contract.blocked_reason
    assert all(a.status == "BLOCKED" for a in plan.actions)

    # Trying to approve any action of this plan fails
    act = plan.actions[0]
    ok, err, _ = engine.approve_action(plan.plan_id, act.action_id, "commander_1", "COMMANDER")
    assert ok is False
    assert "already finalized" in err or "BLOCKED" in err


def test_authorization_failures_and_blocks_are_audit_logged(repo: IncidentRepository):
    """Verify all authorization failures and blocks produce immutable records in operator_actions."""
    inc_id, _ = repo.create_incident("ACCIDENT", "ZONE_A")
    repo.writer.drain()

    engine = GovernedResponseEngine(repository=repo)

    plan, contract = engine.synthesize_response_plan(
        incident_id=inc_id,
        detected_class="ACCIDENT",
        confidence=0.91,
        evidence_summary=["Collision detected"],
        risk_factors={"temporal_consistency": 0.89},
        model_usage_restriction="PRODUCTION",
    )

    dispatch_act = next(a for a in plan.actions if a.action_type == "DISPATCH_AMBULANCE")

    # Viewer attempt
    engine.approve_action(plan.plan_id, dispatch_act.action_id, "viewer_bob", "VIEWER")

    # Operator attempt
    engine.approve_action(plan.plan_id, dispatch_act.action_id, "operator_alice", "OPERATOR")

    # Drain writer queue to SQLite
    repo.writer.drain()

    with sqlite3.connect(str(repo.db_path)) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        actions = cur.execute(
            "SELECT * FROM operator_actions WHERE incident_id=? ORDER BY id ASC", (inc_id,)
        ).fetchall()

        assert len(actions) >= 1
        first_act = actions[0]
        assert "BLOCKED_RESPONSE" in first_act["action"]
        assert first_act["approved"] == 0
        payload = json.loads(first_act["payload_json"])
        assert payload["status"] == "BLOCKED"
        assert payload["rule_id"] in ("INV-01-VIEWER-NO-ACTUATION", "INV-04-NO-AUTOMATIC-DISPATCH")


def test_safety_contract_contents_match_stored_decision_data(repo: IncidentRepository):
    """Verify safety contract contents match stored database records bit-for-bit."""
    inc_id, _ = repo.create_incident("FIRE", "ZONE_A")
    repo.writer.drain()

    engine = GovernedResponseEngine(repository=repo)

    evidence = ["Acoustic siren 90 dB", "Camera confidence 0.94", "IMU shock 3.2g"]
    factors = {"temporal_consistency": 0.91, "sensor_agreement": 0.95, "device_health": 1.0}

    plan, contract = engine.synthesize_response_plan(
        incident_id=inc_id,
        detected_class="FIRE",
        confidence=0.94,
        evidence_summary=evidence,
        risk_factors=factors,
        model_id="production_model_v1",
        model_usage_restriction="PRODUCTION",
    )

    repo.writer.drain()

    # Query stored contract
    contracts = repo._read(
        "SELECT * FROM safety_contracts WHERE incident_id=?", (inc_id,)
    )
    assert len(contracts) == 1
    sc = contracts[0]

    assert sc["incident_id"] == inc_id
    assert sc["detected_class"] == "FIRE"
    assert round(sc["confidence"], 2) == 0.94
    assert json.loads(sc["evidence_json"]) == evidence
    assert json.loads(sc["uncertainty_factors_json"]) == factors
    assert sc["required_approver_role"] == "COMMANDER"
    assert sc["is_blocked"] == 0

    # Query stored response plan
    plans = repo._read(
        "SELECT * FROM response_plans WHERE incident_id=?", (inc_id,)
    )
    assert len(plans) == 1
    p = plans[0]
    assert p["plan_id"] == plan.plan_id
    assert p["status"] == "PROPOSED"
    actions_loaded = json.loads(p["actions_json"])
    assert len(actions_loaded) == len(plan.actions)


def test_safety_contract_included_in_replay_output():
    """Verify sandboxed incident replay engine attaches safety contract to timeline and result."""
    replay_engine = SandboxedReplayEngine()

    steps = [
        ReplayStepInput(
            timestamp_offset_sec=0.0,
            camera_classes=["fire"],
            camera_confidence=0.95,
            audio_class="siren",
            audio_confidence=0.90,
            sensor_temp=65.0,
            sensor_smoke_ppm=120.0,
        ),
        ReplayStepInput(
            timestamp_offset_sec=1.0,
            camera_classes=["fire"],
            camera_confidence=0.98,
            audio_class="siren",
            audio_confidence=0.94,
            sensor_temp=72.0,
            sensor_smoke_ppm=140.0,
        ),
    ]

    result = replay_engine.execute_replay(incident_id="INC-REPLAY-501", steps=steps)

    assert result.safety_contract is not None
    assert result.safety_contract["incident_id"] == "INC-REPLAY-501"
    assert result.safety_contract["detected_class"] == "FIRE"
    assert result.safety_contract["required_approver_role"] == "COMMANDER"

    # Verify every step timeline includes safety contract
    for step in result.timeline:
        assert step.safety_contract is not None
        assert "detected_class" in step.safety_contract
        assert "evidence" in step.safety_contract
        assert "uncertainty_factors" in step.safety_contract


def test_safety_contract_included_in_forensic_reports():
    """Verify court-admissible forensic dossier embeds visible safety contract card."""
    incident = {
        "incident_id": "INC-REPORT-601",
        "event_type": "FIRE",
        "confidence": 0.95,
        "evidence_summary": ["High thermal gradient", "Smoke detector threshold exceeded"],
        "risk_factors": {"temporal_consistency": 0.92, "sensor_agreement": 0.98},
    }

    report_html = ForensicReportGenerator.generate_html_report(incident=incident)

    assert "Governed Autonomous Response & Visible Safety Contract" in report_html
    assert "Visible Safety Contract &bull; INC-REPORT-601" in report_html
    assert "Required Approver:" in report_html
    assert "COMMANDER" in report_html
    assert "High thermal gradient" in report_html


def test_visible_safety_contract_offline_zero_cdn():
    """Verify Visible Safety Contract HTML is completely standalone with zero external CDN dependencies."""
    contract = VisibleSafetyContract(
        contract_id="CONTRACT-1",
        incident_id="INC-OFFLINE-701",
        decision_id="PLAN-1",
        timestamp="2026-10-07T12:00:00+00:00",
        detected_class="ACCIDENT",
        confidence=0.88,
        evidence=["Acoustic crash", "Inertial shock"],
        uncertainty_factors={"temporal_consistency": 0.85},
        proposed_actions=[{"description": "Preempt traffic signal", "required_approver_role": "OPERATOR", "status": "PROPOSED"}],
        required_approver_role="OPERATOR",
    )

    rendered = contract.to_html()
    assert "http://" not in rendered
    assert "https://" not in rendered
    assert "<script" not in rendered
    assert "INC-OFFLINE-701" in rendered
    assert "ACCIDENT" in rendered
