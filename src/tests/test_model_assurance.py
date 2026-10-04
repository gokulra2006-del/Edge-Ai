"""Model-card evidence is available to the decision-support layer."""
from src.modules.assurance.model_assurance import ModelAssuranceService


def test_synthetic_profile_marks_generated_data_for_operator_review(monkeypatch):
    monkeypatch.setenv("EDGE_AI_MODEL_PROFILE", "synthetic")
    result = ModelAssuranceService().summarize({
        "telemetry": {
            "audio_prediction": {"class": "siren", "confidence": 0.98, "dataset": "Synthetic supplied dataset"},
            "vision_prediction": {"class": "bus", "confidence": 0.61, "dataset": "Synthetic supplied dataset"},
        },
        "active_event": {"event": "EMERGENCY_VEHICLE"},
    })
    assert result["status"] == "RESEARCH_ONLY"
    assert result["operator_confirmation_required"] is True
    assert result["actuation_modified"] is False
    assert result["modalities"][0]["held_out_f1"] == 1.0
    assert result["modalities"][1]["readiness"] == "REVIEW_REQUIRED"


def test_low_support_class_is_explicitly_flagged(monkeypatch):
    monkeypatch.setenv("EDGE_AI_MODEL_PROFILE", "synthetic")
    result = ModelAssuranceService().summarize({
        "telemetry": {
            "audio_prediction": {"class": "ambient", "confidence": 0.99},
            "vision_prediction": {"class": "motorcycle", "confidence": 0.80},
        },
        "active_event": {"event": "NORMAL"},
    })
    vision = result["modalities"][1]
    assert vision["held_out_f1"] < 0.60
    assert vision["readiness"] == "REVIEW_REQUIRED"


def test_legacy_profile_does_not_claim_unmeasured_reliability(monkeypatch):
    monkeypatch.setenv("EDGE_AI_MODEL_PROFILE", "legacy")
    result = ModelAssuranceService().summarize({"telemetry": {}, "active_event": {"event": "NORMAL"}})
    assert result["status"] == "MONITORING"
    assert all(item["readiness"] == "UNMEASURED" for item in result["modalities"])
