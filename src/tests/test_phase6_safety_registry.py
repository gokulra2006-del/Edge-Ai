"""
Test Suite: Phase 6 Item 9 - Safety-Aware Model Registry with RESEARCH_ONLY Restrictions.
========================================================================================
Validates that RESEARCH_ONLY models are strictly forbidden from triggering live
incident dispatches or physical actuators while operating freely in shadow mode.
"""
from __future__ import annotations

import pytest
from src.modules.core.safety_registry_gate import SafetyAwareModelRegistry


def test_production_model_execution_permitted():
    """
    Hypothesis: Production active models are authorized to dispatch incidents
    and actuate emergency hardware.
    """
    registry = SafetyAwareModelRegistry()
    registry.register_model(
        model_id="prod_yolo_v8n",
        name="Production YOLOv8",
        version="v1.4",
        sha256="abc123456789",
        usage_restriction="PRODUCTION",
        status="ACTIVE",
    )

    res = registry.evaluate_execution_safety(
        model_id="prod_yolo_v8n",
        predicted_label="GUNSHOT",
        confidence=0.96,
    )

    assert res.actuators_permitted is True
    assert res.incident_dispatch_permitted is True
    assert res.is_shadow_only is False
    assert len(res.safety_violations) == 0


def test_research_only_model_strictly_isolated_to_shadow():
    """
    Hypothesis: Models with RESEARCH_ONLY restriction are blocked from actuating
    hardware or triggering live dispatches, even with 0.99 confidence.
    """
    registry = SafetyAwareModelRegistry()
    registry.register_model(
        model_id="exp_transformer_edge",
        name="Experimental Edge Transformer",
        version="v0.1-alpha",
        sha256="def987654321",
        usage_restriction="RESEARCH_ONLY",
        status="ACTIVE",
    )

    res = registry.evaluate_execution_safety(
        model_id="exp_transformer_edge",
        predicted_label="EXPLOSION",
        confidence=0.99,
    )

    # Actuators and dispatches MUST be strictly blocked
    assert res.actuators_permitted is False
    assert res.incident_dispatch_permitted is False
    assert res.is_shadow_only is True
    assert any("POLICY_RESTRICTION" in v for v in res.safety_violations)


def test_unregistered_model_rejection():
    """
    Hypothesis: Execution from unregistered models is blocked with violation code.
    """
    registry = SafetyAwareModelRegistry()

    res = registry.evaluate_execution_safety(
        model_id="rogue_unregistered_model",
        predicted_label="FIRE",
        confidence=0.90,
    )

    assert res.actuators_permitted is False
    assert res.incident_dispatch_permitted is False
    assert any("UNREGISTERED_MODEL" in v for v in res.safety_violations)
