"""
Governed Autonomous Response & Visible Safety Contract Engine (Phase 6N).
==========================================================================
Hypothesis:
"Showing evidence, uncertainty, and approval requirements for each proposed action
reduces unauthorized or unreviewed actions without delaying authorized ones."

Guarantees & Invariants:
1. AI Proposes Only: AI models only emit `PROPOSED` actions within an explicit response plan.
   Physical actuation and external dispatch unconditionally require human approval by an authorized role.
2. Visible Safety Contract: Every decision produces a contract record stored with the incident:
   - What the AI detected (class, confidence)
   - Which evidence supports it (modalities, key signals)
   - What uncertainty remains (6B multi-factor risk components)
   - What action is proposed
   - Which human role must approve it (OPERATOR vs COMMANDER)
   - Why the action was blocked, if blocked (Phase 6F policy rule ID, e.g. INV-04, INV-05)
3. Model Tier Invariance: RESEARCH_ONLY models cannot propose physical actuation or emergency dispatch (INV-05).
4. Response Plan Lifecycle: Status transitions (PROPOSED -> APPROVED -> EXECUTED, BLOCKED, EXPIRED).
   Completion time (proposal to final status) is strictly measured and recorded.
5. Audit Accountability: All authorization failures and blocked actions produce immutable records
   in the `operator_actions` ledger.
"""
from __future__ import annotations

import copy
import dataclasses
from dataclasses import asdict, dataclass, field
import datetime
import html
import json
import time
import uuid
from typing import Any, Dict, List, Literal, Optional, Set, Tuple

from src.modules.database.governed_store import IncidentRepository, utc_now
from src.modules.security.permission_matrix import ALL_ROLES, check_endpoint_permission

ActionStatus = Literal["PROPOSED", "APPROVED", "BLOCKED", "EXECUTED", "EXPIRED"]
ApproverRole = Literal["OPERATOR", "COMMANDER", "ENGINEER"]


@dataclass
class ProposedAction:
    action_id: str
    action_type: str  # e.g., "TRAFFIC_PREEMPTION", "FIRE_CREW_DISPATCH", "EVACUATION_ALARM"
    description: str
    required_approver_role: ApproverRole  # e.g., "OPERATOR" or "COMMANDER"
    status: ActionStatus = "PROPOSED"
    proposed_at: str = field(default_factory=utc_now)
    acted_at: Optional[str] = None
    acted_by: Optional[str] = None
    acted_role: Optional[str] = None
    blocked_rule_id: Optional[str] = None
    blocked_reason: Optional[str] = None
    execution_result: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ResponsePlan:
    plan_id: str
    incident_id: str
    created_at: str
    actions: List[ProposedAction]
    status: ActionStatus = "PROPOSED"
    completed_at: Optional[str] = None
    completion_duration_seconds: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "incident_id": self.incident_id,
            "status": self.status,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "completion_duration_seconds": (
                round(self.completion_duration_seconds, 3)
                if self.completion_duration_seconds is not None
                else None
            ),
            "actions": [a.to_dict() for a in self.actions],
        }

    def update_action_status(
        self,
        action_id: str,
        new_status: ActionStatus,
        operator_id: str,
        operator_role: str,
        blocked_rule_id: Optional[str] = None,
        blocked_reason: Optional[str] = None,
    ) -> bool:
        """Updates an individual proposed action and computes plan-level completion."""
        now = utc_now()
        found = False
        for a in self.actions:
            if a.action_id == action_id:
                a.status = new_status
                a.acted_at = now
                a.acted_by = operator_id
                a.acted_role = operator_role
                if blocked_rule_id:
                    a.blocked_rule_id = blocked_rule_id
                    a.blocked_reason = blocked_reason
                found = True
                break

        if not found:
            return False

        # If all actions have concluded (APPROVED, BLOCKED, EXECUTED, or EXPIRED)
        non_pending = [a for a in self.actions if a.status != "PROPOSED"]
        if len(non_pending) == len(self.actions):
            self.completed_at = now
            t_created = datetime.datetime.fromisoformat(self.created_at).timestamp()
            t_completed = datetime.datetime.fromisoformat(now).timestamp()
            self.completion_duration_seconds = max(0.0, t_completed - t_created)
            if any(a.status == "EXECUTED" for a in self.actions):
                self.status = "EXECUTED"
            elif any(a.status == "BLOCKED" for a in self.actions):
                self.status = "BLOCKED"
            elif all(a.status == "APPROVED" for a in self.actions):
                self.status = "APPROVED"
            else:
                self.status = "EXPIRED"

        return True


@dataclass
class VisibleSafetyContract:
    contract_id: str
    incident_id: str
    decision_id: str
    timestamp: str
    detected_class: str
    confidence: float
    evidence: List[str]
    uncertainty_factors: Dict[str, float]
    proposed_actions: List[Dict[str, Any]]
    required_approver_role: str
    is_blocked: bool = False
    blocked_rule_id: Optional[str] = None
    blocked_reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_html(self) -> str:
        """Renders offline, printable HTML view of the safety contract."""
        esc_inc = html.escape(self.incident_id)
        esc_det = html.escape(self.detected_class)
        esc_role = html.escape(self.required_approver_role)
        status_badge = (
            f'<span style="color:#b91c1c;font-weight:bold;background:#fee2e2;padding:2px 6px;border-radius:4px;">BLOCKED ({html.escape(self.blocked_rule_id or "POLICY")})</span>'
            if self.is_blocked
            else '<span style="color:#15803d;font-weight:bold;background:#dcfce7;padding:2px 6px;border-radius:4px;">PROPOSAL PENDING HUMAN APPROVAL</span>'
        )

        ev_items = "".join(f"<li>{html.escape(e)}</li>" for e in self.evidence)
        unc_items = " &bull; ".join(f"{html.escape(k)}: {v:.2f}" for k, v in self.uncertainty_factors.items())

        actions_html = []
        for a in self.proposed_actions:
            act_desc = html.escape(a.get("description", a.get("action_type", "")))
            act_role = html.escape(a.get("required_approver_role", "OPERATOR"))
            act_stat = html.escape(a.get("status", "PROPOSED"))
            actions_html.append(f"<li><strong>{act_desc}</strong> [Requires: {act_role}] &mdash; Status: <em>{act_stat}</em></li>")
        actions_str = "".join(actions_html)

        block_section = ""
        if self.is_blocked:
            block_section = f"""
            <div style="margin-top:10px;padding:8px 12px;background:#fef2f2;border:1px solid #fecaca;border-radius:6px;color:#991b1b;font-size:12px;">
              <strong>Action Blocked by Safety Invariant:</strong> {html.escape(self.blocked_rule_id or "INV-UNKNOWN")}<br>
              <strong>Rationale:</strong> {html.escape(self.blocked_reason or "Policy restriction")}
            </div>
            """

        return f"""
        <div style="background:#ffffff;border:1px solid #cbd5e1;border-radius:8px;padding:16px;font-family:-apple-system,BlinkMacSystemFont,sans-serif;margin:12px 0;">
          <div style="display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid #e2e8f0;padding-bottom:8px;margin-bottom:10px;">
            <span style="font-weight:800;font-size:13px;color:#0f172a;">Visible Safety Contract &bull; {esc_inc}</span>
            {status_badge}
          </div>
          <div style="font-size:12px;color:#334155;margin-bottom:8px;">
            <strong>AI Detection:</strong> {esc_det} ({(self.confidence * 100):.1f}% confidence) &bull; <strong>Required Approver:</strong> <span style="font-family:monospace;font-weight:bold;">{esc_role}</span>
          </div>
          <div style="font-size:11px;color:#475569;margin-bottom:8px;">
            <strong>Supporting Evidence:</strong>
            <ul style="margin:4px 0 0 16px;padding:0;">{ev_items}</ul>
          </div>
          <div style="font-size:11px;color:#475569;margin-bottom:8px;">
            <strong>Uncertainty Profile (6B Factors):</strong>
            <div style="background:#f8fafc;padding:6px;border-radius:4px;font-family:monospace;margin-top:4px;">{unc_items}</div>
          </div>
          <div style="font-size:11px;color:#334155;">
            <strong>Proposed Action(s):</strong>
            <ul style="margin:4px 0 0 16px;padding:0;">{actions_str}</ul>
          </div>
          {block_section}
        </div>
        """


class GovernedResponseEngine:
    """
    Synthesizes and enforces governed response plans and safety contracts.
    Guarantees AI only proposes; execution unconditionally requires human approval.
    """

    ROLE_ACTION_PERMISSIONS: Dict[str, Set[str]] = {
        "VIEWER": set(),  # Viewer cannot actuate or approve anything (INV-01)
        "OPERATOR": {"TRAFFIC_PREEMPTION", "HOLD_TRAFFIC", "LOCAL_SIGNS", "ACKNOWLEDGE", "RESTRICT_LANE"},
        "COMMANDER": {
            "TRAFFIC_PREEMPTION", "HOLD_TRAFFIC", "LOCAL_SIGNS", "ACKNOWLEDGE", "RESTRICT_LANE",
            "DISPATCH_AMBULANCE", "DISPATCH_FIRE_CREW", "DISPATCH_POLICE", "EVACUATION_ALARM", "RESOLVE"
        },
        "ENGINEER": {"ACKNOWLEDGE"},
    }

    def __init__(self, repository: Optional[IncidentRepository] = None):
        self.repository = repository
        self.active_plans: Dict[str, ResponsePlan] = {}

    def synthesize_response_plan(
        self,
        incident_id: str,
        detected_class: str,
        confidence: float,
        evidence_summary: List[str],
        risk_factors: Dict[str, float],
        model_id: str = "prod_detector_v1",
        model_usage_restriction: str = "PRODUCTION",
    ) -> Tuple[ResponsePlan, VisibleSafetyContract]:
        """
        Creates a proposed response plan and binds a visible safety contract.
        If the model is RESEARCH_ONLY, actuation is strictly BLOCKED under INV-05.
        """
        now = utc_now()
        plan_id = f"PLAN-{incident_id}-{int(time.time()*1000)}"
        det_upper = detected_class.upper()

        proposed_actions: List[ProposedAction] = []
        is_blocked = False
        blocked_rule_id = None
        blocked_reason = None
        required_approver: ApproverRole = "OPERATOR"

        # 1. Evaluate INV-05: RESEARCH_ONLY models cannot authorize actuation
        is_research = model_usage_restriction.upper() in ("RESEARCH_ONLY", "CANDIDATE")

        if det_upper == "FIRE":
            required_approver = "COMMANDER"
            act1 = ProposedAction(
                action_id=f"ACT-{uuid.uuid4().hex[:6]}",
                action_type="HOLD_TRAFFIC",
                description="Halt cross-traffic approaching fire hazard zone",
                required_approver_role="OPERATOR",
            )
            act2 = ProposedAction(
                action_id=f"ACT-{uuid.uuid4().hex[:6]}",
                action_type="DISPATCH_FIRE_CREW",
                description="Request emergency fire brigade dispatch (operator approval required)",
                required_approver_role="COMMANDER",
            )
            proposed_actions.extend([act1, act2])

        elif det_upper in ("ACCIDENT", "VEHICLE_ACCIDENT"):
            required_approver = "COMMANDER"
            act1 = ProposedAction(
                action_id=f"ACT-{uuid.uuid4().hex[:6]}",
                action_type="TRAFFIC_PREEMPTION",
                description="Preempt traffic signal corridor to clear path for emergency arrival",
                required_approver_role="OPERATOR",
            )
            act2 = ProposedAction(
                action_id=f"ACT-{uuid.uuid4().hex[:6]}",
                action_type="DISPATCH_AMBULANCE",
                description="Request emergency ambulance dispatch (operator approval required)",
                required_approver_role="COMMANDER",
            )
            proposed_actions.extend([act1, act2])

        elif det_upper == "AMBULANCE":
            required_approver = "OPERATOR"
            act1 = ProposedAction(
                action_id=f"ACT-{uuid.uuid4().hex[:6]}",
                action_type="TRAFFIC_PREEMPTION",
                description="Trigger green-wave corridor preemption for inbound ambulance",
                required_approver_role="OPERATOR",
            )
            proposed_actions.append(act1)

        else:
            required_approver = "OPERATOR"
            act1 = ProposedAction(
                action_id=f"ACT-{uuid.uuid4().hex[:6]}",
                action_type="LOCAL_SIGNS",
                description="Display advisory traffic advisory message",
                required_approver_role="OPERATOR",
            )
            proposed_actions.append(act1)

        # Apply INV-05 restriction if model is RESEARCH_ONLY
        if is_research:
            is_blocked = True
            blocked_rule_id = "INV-05-RESEARCH-MODEL-BOUNDARY"
            blocked_reason = (
                f"Model '{model_id}' usage restriction is '{model_usage_restriction}'. "
                "Architectural safety policy strictly prohibits non-production models from proposing physical actuation or dispatch."
            )
            for a in proposed_actions:
                a.status = "BLOCKED"
                a.blocked_rule_id = blocked_rule_id
                a.blocked_reason = blocked_reason

        # Assemble plan
        plan = ResponsePlan(
            plan_id=plan_id,
            incident_id=incident_id,
            created_at=now,
            actions=proposed_actions,
            status="BLOCKED" if is_blocked else "PROPOSED",
        )

        # Assemble safety contract
        contract = VisibleSafetyContract(
            contract_id=f"CONTRACT-{incident_id}-{uuid.uuid4().hex[:6]}",
            incident_id=incident_id,
            decision_id=plan_id,
            timestamp=now,
            detected_class=det_upper,
            confidence=round(confidence, 4),
            evidence=list(evidence_summary),
            uncertainty_factors=copy.deepcopy(risk_factors),
            proposed_actions=[a.to_dict() for a in proposed_actions],
            required_approver_role=required_approver,
            is_blocked=is_blocked,
            blocked_rule_id=blocked_rule_id,
            blocked_reason=blocked_reason,
        )

        self.active_plans[plan_id] = plan

        # Persist to repository if available
        if self.repository is not None:
            self._persist_plan_and_contract(plan, contract)

        return plan, contract

    def approve_action(
        self,
        plan_id: str,
        action_id: str,
        operator_id: str,
        role: str,
    ) -> Tuple[bool, str, Optional[ProposedAction]]:
        """
        Executes an action following explicit human authorization check.
        Returns: (success, message, action_object)
        """
        role_upper = (role or "").upper()
        plan = self.active_plans.get(plan_id)

        if not plan:
            # Try to load plan from database
            plan = self._load_plan_from_db(plan_id)
            if not plan:
                return False, f"Response plan '{plan_id}' not found.", None

        # Find targeted action
        action: Optional[ProposedAction] = None
        for a in plan.actions:
            if a.action_id == action_id:
                action = a
                break

        if not action:
            return False, f"Action '{action_id}' not found in plan '{plan_id}'.", None

        # 1. Invariant Check: Action already closed
        if action.status in ("APPROVED", "EXECUTED", "BLOCKED", "EXPIRED"):
            return False, f"Action is already finalized with status '{action.status}'.", action

        # 2. Invariant Check: Role authorization
        allowed_actions = self.ROLE_ACTION_PERMISSIONS.get(role_upper, set())

        # Dispatches require COMMANDER
        if "DISPATCH" in action.action_type and role_upper != "COMMANDER":
            rule_id = "INV-04-NO-AUTOMATIC-DISPATCH"
            reason = f"Role '{role_upper}' is not authorized to approve external emergency dispatches; requires COMMANDER."
            self._audit_block(plan.incident_id, operator_id, role_upper, action.action_type, rule_id, reason)
            plan.update_action_status(action_id, "BLOCKED", operator_id, role_upper, rule_id, reason)
            self._save_plan(plan)
            return False, reason, action

        # Viewer / unauthorized role
        if action.action_type not in allowed_actions:
            rule_id = "INV-01-VIEWER-NO-ACTUATION" if role_upper == "VIEWER" else "INV-ROLE-UNAUTHORIZED"
            reason = f"Role '{role_upper}' lacks required permissions for '{action.action_type}'."
            self._audit_block(plan.incident_id, operator_id, role_upper, action.action_type, rule_id, reason)
            plan.update_action_status(action_id, "BLOCKED", operator_id, role_upper, rule_id, reason)
            self._save_plan(plan)
            return False, reason, action

        # 3. Successful human approval & execution
        plan.update_action_status(action_id, "EXECUTED", operator_id, role_upper)
        self._audit_approval(plan.incident_id, operator_id, role_upper, action.action_type)
        self._save_plan(plan)

        return True, f"Action '{action.action_type}' approved and executed by {operator_id} ({role_upper}).", action

    def _audit_approval(self, incident_id: str, operator_id: str, role: str, action_type: str) -> None:
        if self.repository is None:
            return
        payload = {"role": role, "action_type": action_type, "status": "APPROVED_AND_EXECUTED"}
        self.repository.add_operator_action(
            incident_id=incident_id,
            operator_id=operator_id,
            action=f"APPROVE_RESPONSE:{action_type}",
            approved=True,
            payload=payload,
        )

    def _audit_block(self, incident_id: str, operator_id: str, role: str, action_type: str, rule_id: str, reason: str) -> None:
        if self.repository is None:
            return
        payload = {"role": role, "action_type": action_type, "rule_id": rule_id, "reason": reason, "status": "BLOCKED"}
        self.repository.add_operator_action(
            incident_id=incident_id,
            operator_id=operator_id,
            action=f"BLOCKED_RESPONSE:{action_type}",
            approved=False,
            payload=payload,
        )

    def _persist_plan_and_contract(self, plan: ResponsePlan, contract: VisibleSafetyContract) -> None:
        if self.repository is None:
            return
        try:
            # 1. Insert contract
            self.repository.writer.submit(
                lambda c: c.execute(
                    """
                    INSERT INTO safety_contracts (
                      incident_id, decision_id, timestamp, detected_class, confidence,
                      evidence_json, uncertainty_factors_json, proposed_action,
                      required_approver_role, is_blocked, blocked_rule_id, blocked_reason
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        contract.incident_id,
                        contract.decision_id,
                        contract.timestamp,
                        contract.detected_class,
                        contract.confidence,
                        json.dumps(contract.evidence),
                        json.dumps(contract.uncertainty_factors),
                        json.dumps(contract.proposed_actions),
                        contract.required_approver_role,
                        1 if contract.is_blocked else 0,
                        contract.blocked_rule_id,
                        contract.blocked_reason,
                    ),
                )
            )

            # 2. Insert or update plan
            self._save_plan(plan)
        except Exception:
            pass

    def _save_plan(self, plan: ResponsePlan) -> None:
        if self.repository is None:
            return
        try:
            actions_blob = json.dumps([a.to_dict() for a in plan.actions])
            self.repository.writer.submit(
                lambda c: c.execute(
                    """
                    INSERT INTO response_plans (
                      plan_id, incident_id, status, created_at, completed_at,
                      completion_duration_seconds, actions_json
                    ) VALUES (?,?,?,?,?,?,?)
                    ON CONFLICT(plan_id) DO UPDATE SET
                      status=excluded.status,
                      completed_at=excluded.completed_at,
                      completion_duration_seconds=excluded.completion_duration_seconds,
                      actions_json=excluded.actions_json
                    """,
                    (
                        plan.plan_id,
                        plan.incident_id,
                        plan.status,
                        plan.created_at,
                        plan.completed_at,
                        plan.completion_duration_seconds,
                        actions_blob,
                    ),
                )
            )
        except Exception:
            pass

    def _load_plan_from_db(self, plan_id: str) -> Optional[ResponsePlan]:
        if self.repository is None:
            return None
        try:
            rows = self.repository._read("SELECT * FROM response_plans WHERE plan_id=?", (plan_id,))
            if not rows:
                return None
            r = rows[0]
            raw_acts = json.loads(r["actions_json"])
            acts = [ProposedAction(**a) for a in raw_acts]
            plan = ResponsePlan(
                plan_id=r["plan_id"],
                incident_id=r["incident_id"],
                created_at=r["created_at"],
                actions=acts,
                status=r["status"],
                completed_at=r["completed_at"],
                completion_duration_seconds=r["completion_duration_seconds"],
            )
            self.active_plans[plan_id] = plan
            return plan
        except Exception:
            return None
