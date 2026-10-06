"""
Counterfactual Explanation Engine (Phase 6E).
=============================================
Computes post-hoc counterfactual explanations and decision sensitivity analysis
using the sandboxed 6D incident replay engine:
- Why classified as it was (top contributing evidence)
- Which sensor changed the decision (pivot sensor)
- Modality ablation outcomes ("With camera: ALERT / Without camera: REVIEW_REQUIRED")
- Which missing sensor would reduce confidence most
- Why no emergency response was triggered (when suppressed)
- Explanation fidelity verification against real replay execution.
"""
from __future__ import annotations

import copy
import dataclasses
from dataclasses import asdict, dataclass, field
import datetime
import json
import time
from typing import Any, Dict, List, Optional, Tuple

from src.modules.incident_management.replay_engine import (
    ReplayStepInput,
    SandboxedReplayEngine,
)


@dataclass
class ModalityAblationSummary:
    modality: str
    decision: str
    final_risk: float
    action: str
    plan: str
    risk_drop: float


@dataclass
class CounterfactualExplanation:
    incident_id: str
    generated_at: str
    baseline_decision: str
    baseline_risk: float
    baseline_action: str
    top_contributing_evidence: str
    pivot_sensor: Optional[str]
    highest_impact_sensor: str
    max_risk_drop: float
    why_not_triggered: Optional[str]
    ablation_outcomes: Dict[str, ModalityAblationSummary]
    fidelity_verified: bool
    explanation_text: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "incident_id": self.incident_id,
            "generated_at": self.generated_at,
            "baseline_decision": self.baseline_decision,
            "baseline_risk": self.baseline_risk,
            "baseline_action": self.baseline_action,
            "top_contributing_evidence": self.top_contributing_evidence,
            "pivot_sensor": self.pivot_sensor,
            "highest_impact_sensor": self.highest_impact_sensor,
            "max_risk_drop": self.max_risk_drop,
            "why_not_triggered": self.why_not_triggered,
            "fidelity_verified": self.fidelity_verified,
            "explanation_text": self.explanation_text,
            "ablation_outcomes": {k: asdict(v) for k, v in self.ablation_outcomes.items()},
        }


class CounterfactualExplanationEngine:
    """
    Computes rigorous counterfactual explanations via systematic replay ablations.
    Guaranteed: Explanations are read-only and NEVER mutate live state.
    """

    def __init__(self, replay_engine: Optional[SandboxedReplayEngine] = None):
        self.replay_engine = replay_engine or SandboxedReplayEngine()

    def explain_incident(
        self,
        incident_id: str,
        steps: List[ReplayStepInput],
    ) -> CounterfactualExplanation:
        """
        Executes counterfactual ablations over camera, audio, and sensors to derive explanations.
        """
        t0 = time.perf_counter()

        # 1. Baseline replay (all modalities present)
        base_run = self.replay_engine.execute_replay(incident_id=incident_id, steps=steps)
        base_decision = base_run.final_decision
        base_risk = base_run.final_risk
        base_action = base_run.timeline[-1].action if base_run.timeline else "SUPPRESS_NOISE"

        # 2. Modality ablations
        modalities = ["camera", "audio", "sensors"]
        ablation_runs: Dict[str, ModalityAblationSummary] = {}
        pivot_sensor: Optional[str] = None
        max_drop = -1.0
        highest_impact = "none"

        for mod in modalities:
            # Replay with specific sensor dropped
            mod_run = self.replay_engine.execute_replay(
                incident_id=incident_id,
                steps=steps,
                dropout_sensor=mod,
            )

            mod_decision = mod_run.final_decision
            mod_risk = mod_run.final_risk
            mod_action = mod_run.timeline[-1].action if mod_run.timeline else "SUPPRESS_NOISE"
            mod_plan = mod_run.timeline[-1].recommended_plan if mod_run.timeline else "STANDBY"
            risk_drop = max(0.0, round(base_risk - mod_risk, 4))

            ablation_runs[f"without_{mod}"] = ModalityAblationSummary(
                modality=mod,
                decision=mod_decision,
                final_risk=mod_risk,
                action=mod_action,
                plan=mod_plan,
                risk_drop=risk_drop,
            )

            # Check if this sensor's removal changed the operational decision
            if mod_action != base_action and pivot_sensor is None:
                pivot_sensor = mod

            if risk_drop > max_drop:
                max_drop = risk_drop
                highest_impact = mod

        # Top contributing evidence modality
        top_contrib = highest_impact if highest_impact != "none" else "camera"

        # 3. Why no emergency triggered (if suppressed or normal)
        why_not = None
        if base_decision == "NORMAL" or base_action == "SUPPRESS_NOISE":
            if base_risk < 0.50:
                why_not = (
                    f"Overall risk ({base_risk:.2f}) remained below alert threshold (0.50) due to "
                    f"absence of corroborating multi-sensor telemetry or temporal consensus."
                )
            else:
                why_not = "Raw evidence was suppressed as ambient baseline noise."

        # 4. Generate readable explanation summary string
        summary_lines = [
            f"Classification: {base_decision} (Risk: {base_risk:.2f}, Action: {base_action}).",
            f"Top Evidence: Driven primarily by {top_contrib.upper()} telemetry.",
        ]
        if pivot_sensor:
            summary_lines.append(f"Pivot Sensor: Removal of {pivot_sensor.upper()} changes decision to {ablation_runs[f'without_{pivot_sensor}'].action}.")
        else:
            summary_lines.append(f"Decision Stability: Redundant coverage; no single sensor removal alters the decision.")

        summary_lines.append(f"Ablation Matrix: With all: {base_decision} ({base_risk:.2f}) | " + " | ".join(
            f"Without {mod}: {ablation_runs[f'without_{mod}'].decision} ({ablation_runs[f'without_{mod}'].final_risk:.2f})"
            for mod in modalities
        ))

        explanation_text = " ".join(summary_lines)

        # 5. Explanation fidelity verification: bit-exact match against replay
        fidelity_verified = True
        for mod in modalities:
            # Re-verify against direct replay
            verify_run = self.replay_engine.execute_replay(incident_id=incident_id, steps=steps, dropout_sensor=mod)
            stored = ablation_runs[f"without_{mod}"]
            if verify_run.final_decision != stored.decision or verify_run.final_risk != stored.final_risk:
                fidelity_verified = False

        return CounterfactualExplanation(
            incident_id=incident_id,
            generated_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            baseline_decision=base_decision,
            baseline_risk=base_risk,
            baseline_action=base_action,
            top_contributing_evidence=top_contrib,
            pivot_sensor=pivot_sensor,
            highest_impact_sensor=highest_impact,
            max_risk_drop=max_drop,
            why_not_triggered=why_not,
            ablation_outcomes=ablation_runs,
            fidelity_verified=fidelity_verified,
            explanation_text=explanation_text,
        )
