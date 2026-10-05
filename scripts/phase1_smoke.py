"""Create a governed simulated incident and an evidence package."""
from __future__ import annotations
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))

from src.modules.database.governed_store import EvidenceExporter, IncidentRepository, ModelRegistry

DB = ROOT / "data" / "phase1_smoke.db"
EVIDENCE = ROOT / "data" / "evidence"


def main() -> None:
    repository = IncidentRepository(DB)
    try:
        registry = ModelRegistry(repository)
        registry.populate_from_assurance()
        incident_id, _ = repository.create_incident("collision", "ZONE_B_INTERSECTION")
        repository.writer.drain()
        repository.add_event(incident_id, "multimodal_trigger", {"source": "existing live-stream simulation"}, dedupe_key="simulation-trigger")
        repository.add_prediction(incident_id, "collision", .91, "assurance-vision", {"simulated": True})
        repository.add_operator_action(incident_id, "commander", "review_required_before_contact", False, {"emergency_service_contact": "operator-approved only"})
        clip = ROOT / "data" / "phase1_trigger.txt"; clip.write_text("simulated trigger evidence", encoding="utf-8")
        repository.attach_evidence(incident_id, "simulation_trigger", clip)
        repository.close_incident(incident_id, "simulation completed; no real emergency contact")
        manifest = EvidenceExporter(repository, EVIDENCE).export(incident_id)
        repository.writer.drain()
        counts = {table: len(repository.rows(table, incident_id)) for table in ("incidents", "incident_events", "predictions", "operator_actions", "evidence")}
        print(json.dumps({"manifest": str(manifest), "counts": counts, "verified": EvidenceExporter.verify(manifest)}, indent=2))
        print(manifest.read_text(encoding="utf-8"))
    finally:
        repository.close()

if __name__ == "__main__": main()


