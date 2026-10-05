"""Create a governed simulated incident and an evidence package."""
from __future__ import annotations
import base64
import json
from pathlib import Path
import sys
import wave

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))
from src.modules.database.governed_store import EvidenceExporter, IncidentRepository, ModelRegistry

DB = ROOT / "data" / "phase1_smoke.db"
EVIDENCE = ROOT / "data" / "evidence"
JPEG_1PX = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xdb\x00C\x00" + bytes([8] * 64) + b"\xff\xd9"

def main() -> None:
    repository = IncidentRepository(DB)
    try:
        incident_id, _ = repository.create_incident("collision", "ZONE_B_INTERSECTION")
        repository.writer.drain()
        keyframe = ROOT / "data" / "phase1_keyframe.jpg"; keyframe.write_bytes(JPEG_1PX)
        clip = ROOT / "data" / "phase1_trigger.wav"
        with wave.open(str(clip), "wb") as output:
            output.setnchannels(1); output.setsampwidth(2); output.setframerate(8000); output.writeframes(b"\x00\x00" * 800)
        registry = ModelRegistry(repository)
        registry.register("phase1-simulation", "simulation", "1", keyframe, "UNVERIFIED", "UNVERIFIED")
        repository.writer.drain(); registry.verify_on_startup("phase1-simulation", keyframe)
        repository.add_event(incident_id, "multimodal_trigger", {"source": "existing live-stream simulation"}, dedupe_key="simulation-trigger")
        repository.add_prediction(incident_id, "collision", .91, "phase1-simulation", {"simulated": True})
        repository.add_assurance_state(incident_id, "phase1-simulation", "RESEARCH_ONLY", {"usage_restriction": "operator confirmation required"})
        repository.add_operator_action(incident_id, "commander", "review_required_before_contact", False, {"emergency_service_contact": "operator-approved only"})
        repository.attach_evidence(incident_id, "keyframe", keyframe); repository.attach_evidence(incident_id, "audio_clip", clip)
        repository.close_incident(incident_id, "simulation completed; no real emergency contact")
        manifest = EvidenceExporter(repository, EVIDENCE).export(incident_id)
        repository.writer.drain()
        counts = {table: len(repository.rows(table, incident_id)) for table in ("incidents", "incident_events", "predictions", "operator_actions", "evidence", "assurance_states")}
        deployments = len(repository._read("SELECT * FROM deployments WHERE model_id=?", ("phase1-simulation",)))
        print(json.dumps({"manifest": str(manifest), "counts": counts, "deployments": deployments, "verified": EvidenceExporter.verify(manifest)}, indent=2))
        print(manifest.read_text(encoding="utf-8"))
    finally: repository.close()

if __name__ == "__main__": main()

