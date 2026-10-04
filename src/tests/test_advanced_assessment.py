import json
from pathlib import Path
from src.modules.sensor_fusion.advanced_fusion import AdvancedFusionEngine
from src.modules.sensor_fusion.event_validation import EventValidator
from src.modules.severity_assessment.risk_engine import RiskEngine

CONFIG=json.loads((Path(__file__).parents[1]/"config"/"advanced_platform.json").read_text())
def test_fusion_and_risk_keep_single_signal_under_review():
    assurance={"modalities":[{"readiness":"SUPPORTED"},{"readiness":"REVIEW_REQUIRED"}]}
    telemetry={"audio_prediction":{"class":"crash","confidence":.91},"vision_prediction":{"class":"unknown","confidence":.12},"smoke_level":12,"temperature":28}
    fusion=AdvancedFusionEngine(CONFIG).fuse(telemetry, assurance)
    assert fusion["incident_type"] == "vehicle_accident"
    assert "single-modality evidence" in fusion["contradicting_evidence"]
    temporal=EventValidator(CONFIG)
    result=None
    for _ in range(3): result=temporal.ingest("vehicle_accident", .9)
    assert result["confirmed"]
    risk=RiskEngine(CONFIG).assess(fusion,result)
    assert 0 <= risk["risk_score"] <= 100
