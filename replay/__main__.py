"""CLI entrypoint for incident replay: python -m replay run --incident <id> [options]"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Add root directory to path
ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.modules.incident_management.replay_engine import (
    ReplayStepInput,
    SandboxedReplayEngine,
)


def build_sample_incident_trace(incident_id: str) -> list[ReplayStepInput]:
    """Generates synthetic replay trace for demonstration or testing."""
    return [
        ReplayStepInput(
            timestamp_offset_sec=0.0,
            camera_classes=["car", "pedestrian"],
            camera_confidence=0.75,
            audio_class="ambient",
            audio_confidence=0.5,
        ),
        ReplayStepInput(
            timestamp_offset_sec=1.0,
            camera_classes=["damaged_vehicle", "debris"],
            camera_confidence=0.88,
            audio_class="crash",
            audio_confidence=0.92,
            audio_db=94.0,
        ),
        ReplayStepInput(
            timestamp_offset_sec=2.0,
            camera_classes=["damaged_vehicle", "emergency_vehicle"],
            camera_confidence=0.94,
            audio_class="siren",
            audio_confidence=0.96,
            audio_db=96.0,
        ),
    ]


def main():
    parser = argparse.ArgumentParser(description="Sentinel-AI Digital Twin Incident Replay CLI")
    parser.add_argument("command", choices=["run"], help="Command to execute")
    parser.add_argument("--incident", type=str, default="INC-DEMO-001", help="Incident ID to replay")
    parser.add_argument("--speed", type=float, default=1.0, help="Playback speed multiplier")
    parser.add_argument("--dropout", type=str, choices=["camera", "audio", "sensors"], help="Simulate sensor dropout")
    parser.add_argument("--delayed-audio", type=int, default=0, help="Audio delay in milliseconds")
    parser.add_argument("--camera-failure", action="store_true", help="Simulate camera video failure")
    parser.add_argument("--network-outage", action="store_true", help="Simulate offline network outage")
    parser.add_argument("--conflicting-sensors", action="store_true", help="Simulate conflicting sensor inputs")
    parser.add_argument("--operator-action", type=str, default="NONE", choices=["NONE", "ACKNOWLEDGE", "FALSE_ALARM", "OVERRIDE_PLAN"])
    parser.add_argument("--out", type=str, help="Output JSON path")
    args = parser.parse_args()

    print(f"===============================================================")
    print(f" Sentinel-AI Sandboxed Incident Replay: {args.incident}")
    print(f"===============================================================")

    trace = build_sample_incident_trace(args.incident)
    engine = SandboxedReplayEngine()

    result = engine.execute_replay(
        incident_id=args.incident,
        steps=trace,
        playback_speed=args.speed,
        dropout_sensor=args.dropout,
        delayed_audio_ms=args.delayed_audio,
        camera_failure=args.camera_failure,
        network_outage=args.network_outage,
        conflicting_sensors=args.conflicting_sensors,
        operator_action=args.operator_action,
    )

    print(f"Replay ID:          {result.replay_id}")
    print(f"Final Decision:     {result.final_decision}")
    print(f"Final Risk:         {result.final_risk:.4f}")
    print(f"Counterfactual:     {result.is_counterfactual}")
    print(f"Timeline Steps:     {len(result.timeline)}")
    print(f"Sandbox Isolation:  {'VERIFIED (0 Live Table Writes)' if result.sandbox_verified else 'FAILED'}")
    print("---------------------------------------------------------------")
    for s in result.timeline:
        print(f" Step {s.step_idx} [{s.timestamp_offset_sec:.1f}s] -> Pred: {s.model_predictions.get('camera')}, Risk: {s.final_risk:.2f}, Plan: {s.recommended_plan}")

    if args.out:
        out_p = Path(args.out)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(json.dumps(result.to_dict(), indent=2), encoding="utf-8")
        print(f"\nSaved replay artifact to: {out_p}")


if __name__ == "__main__":
    main()
