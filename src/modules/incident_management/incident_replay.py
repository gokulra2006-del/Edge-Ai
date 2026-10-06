"""
Module: Reproducible Incident Replay for Evaluation.
===================================================
Enables bit-exact deterministic replay of multi-sensor incident telemetry
and timestamps through the decision engine for reproducible counterfactual
evaluation and regression analysis.

Research Hypothesis:
Replaying serialized multi-sensor telemetry traces and keyframes in an isolated
virtual-time replay environment yields 100% deterministic decision engine state
transitions and identical risk scores across repeated runs, eliminating evaluation
stochasticity caused by wall-clock latency jitter.

Primary Metrics:
1. Replay Determinism: 100% identical state transitions, incident severity classifications,
   and final risk scores across 10 repeated replay executions.
2. Temporal Fidelity: Event inter-arrival timings and timestamp offsets match recorded
   incident chronology with zero sequencing inversion.
3. Counterfactual Sensitivity: Replacing or tuning a threshold parameter in the replayed
   engine produces immediately measurable, reproducible changes in incident outcomes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class ReplayTelemetryEvent:
    timestamp_offset_ms: int
    modality: str  # CAMERA, AUDIO, SENSOR
    event_type: str
    confidence: float
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ReplayExecutionLog:
    step_index: int
    timestamp_offset_ms: int
    modality: str
    event_type: str
    raw_confidence: float
    accumulated_risk: float
    engine_state: str  # MONITORING, WARNING, INCIDENT_DECLARED


class IncidentReplayEngine:
    """
    Deterministic replay simulator for historical or synthetic incidents.
    """

    def __init__(self, incident_id: str, declaration_threshold: float = 0.75):
        self.incident_id = incident_id
        self.declaration_threshold = declaration_threshold
        self.events: List[ReplayTelemetryEvent] = []

    def load_telemetry_trace(self, trace_json_str: str) -> None:
        """Loads serialized telemetry trace and sorts strictly by timestamp offset."""
        raw_list = json.loads(trace_json_str)
        self.events = [
            ReplayTelemetryEvent(
                timestamp_offset_ms=int(item["timestamp_offset_ms"]),
                modality=item["modality"].upper(),
                event_type=item["event_type"],
                confidence=float(item["confidence"]),
                metadata=item.get("metadata", {}),
            )
            for item in raw_list
        ]
        self.events.sort(key=lambda x: x.timestamp_offset_ms)

    def run_replay(self) -> Tuple[List[ReplayExecutionLog], Dict[str, Any]]:
        """
        Executes replay in virtual time, returning step-by-step logs and summary.
        """
        logs: List[ReplayExecutionLog] = []
        current_risk: float = 0.0
        engine_state: str = "MONITORING"
        incident_declared_at_step: Optional[int] = None

        for idx, ev in enumerate(self.events):
            # Dynamic state transition logic based on cumulative evidence
            # Fusion factor: 0.6 * previous_risk + 0.5 * event_confidence
            current_risk = min(1.0, (current_risk * 0.5) + (ev.confidence * 0.6))

            if current_risk >= self.declaration_threshold:
                engine_state = "INCIDENT_DECLARED"
                if incident_declared_at_step is None:
                    incident_declared_at_step = idx
            elif current_risk >= (self.declaration_threshold * 0.6):
                engine_state = "WARNING"
            else:
                engine_state = "MONITORING"

            step_log = ReplayExecutionLog(
                step_index=idx,
                timestamp_offset_ms=ev.timestamp_offset_ms,
                modality=ev.modality,
                event_type=ev.event_type,
                raw_confidence=ev.confidence,
                accumulated_risk=round(current_risk, 4),
                engine_state=engine_state,
            )
            logs.append(step_log)

        summary = {
            "incident_id": self.incident_id,
            "total_events_replayed": len(self.events),
            "final_state": engine_state,
            "final_risk": round(current_risk, 4),
            "incident_declared": engine_state == "INCIDENT_DECLARED",
            "declaration_step": incident_declared_at_step,
        }

        return logs, summary
