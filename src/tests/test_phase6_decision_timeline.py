"""
Test Suite for Phase 6 Research: Explainable Multimodal Decision Timelines.

Hypothesis:
Chronologically aligning asynchronous multimodal sensor observations, rule
triggers, and human operator actions into an attributed timeline reduces
post-incident ambiguity and provides 100% causal completeness for forensic audits.

Metrics Evaluated:
1. Causal Completeness Score: Percentage of decision steps with verified modality attribution (target: 100%).
2. Attribution Fidelity: Dominant modality matches top input weight.
3. Chronological Consistency: Relative seconds strictly monotonically non-decreasing.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
import pytest

from src.modules.decision_engine.decision_timeline import (
    MultimodalTimelineEngine,
    TimelineEntry,
)


def test_multimodal_timeline_synthesis_and_causal_narrative():
    engine = MultimodalTimelineEngine()

    now = datetime.now(timezone.utc)
    t_genesis = now.isoformat()
    t_audio = (now - timedelta(seconds=0.4)).isoformat()
    t_vision = (now - timedelta(seconds=0.2)).isoformat()
    t_ack = (now + timedelta(seconds=12.5)).isoformat()

    incident_record = {
        "incident_id": "INC-RESEARCH-001",
        "event_type": "COLLISION",
        "severity": "CRITICAL",
        "created_at": t_genesis,
        "zone_id": "ZONE_B_INTERSECTION",
        "modality_weights": {"vision": 0.55, "audio": 0.35, "imu": 0.10},
        "incident_events": [
            {
                "timestamp": t_audio,
                "source": "AUDIO",
                "event_type": "siren_detected",
                "confidence": 0.92,
                "details_json": json.dumps({"audio_db": 84.0}),
            },
            {
                "timestamp": t_vision,
                "source": "VISION",
                "event_type": "crash_visual_detected",
                "confidence": 0.96,
                "details_json": json.dumps({"bounding_box": [100, 200, 300, 400]}),
            },
        ],
        "predictions": [
            {
                "timestamp": t_vision,
                "model_id": "model-vision-yolo11n",
                "label": "crash",
                "confidence": 0.95,
                "payload_json": json.dumps({"ood_status": "IN_DISTRIBUTION"}),
            }
        ],
        "operator_actions": [
            {
                "timestamp": t_ack,
                "action": "acknowledge",
                "operator_id": "commander_1",
                "payload_json": json.dumps({"note": "Confirmed two-vehicle impact in lane 2"}),
            }
        ],
    }

    result = engine.synthesize_timeline(incident_record)

    # Metric 1: Causal completeness
    assert result["incident_id"] == "INC-RESEARCH-001"
    assert result["causal_completeness_pct"] == 100.0
    assert result["event_count"] == 5  # 2 sensor + 1 prediction + 1 genesis + 1 operator

    # Metric 2: Attribution fidelity
    assert result["dominant_modality"] == "VISION"

    # Metric 3: Chronological ordering
    timeline = result["timeline"]
    rel_times = [e["relative_seconds"] for e in timeline]
    assert rel_times == sorted(rel_times)
    assert rel_times[0] < 0.0  # Pre-incident sensor observation
    assert rel_times[-1] > 10.0  # Operator response

    # Narrative verification
    narrative = result["narrative"]
    assert "Acoustic sensor detected audio signature" in narrative
    assert "Vision stream identified" in narrative
    assert "Incident declared (CRITICAL)" in narrative
    assert "Operator 'commander_1' executed action 'ACKNOWLEDGE'" in narrative


def test_timeline_resilience_to_empty_and_corrupt_records():
    engine = MultimodalTimelineEngine()

    # Empty record
    empty_result = engine.synthesize_timeline({})
    assert empty_result["event_count"] == 1  # Only genesis trigger
    assert empty_result["causal_completeness_pct"] == 100.0
    assert "timeline" in empty_result

    # Corrupt / non-JSON details
    corrupt_record = {
        "incident_id": "INC-CORRUPT",
        "created_at": "invalid-timestamp",
        "incident_events": [
            {"timestamp": "bad-ts", "source": "UNKNOWN", "details_json": "INVALID_JSON{{{"}
        ],
        "operator_actions": [
            {"timestamp": "bad-ts", "action": "note", "payload_json": None}
        ],
    }
    corrupt_result = engine.synthesize_timeline(corrupt_record)
    assert corrupt_result["incident_id"] == "INC-CORRUPT"
    assert corrupt_result["event_count"] >= 2
