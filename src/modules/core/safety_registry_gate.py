"""
Module: Safety-Aware Model Registry with RESEARCH_ONLY Restrictions.
===================================================================
Enforces architectural runtime safety gates preventing unverified, experimental,
or RESEARCH_ONLY models from actuating physical sirens, triggering emergency dispatches,
or closing real-world security gates.

Research Hypothesis:
Embedding immutable usage restriction policies ('RESEARCH_ONLY' vs 'PRODUCTION')
directly within the model registry and decision engine pipeline guarantees 100%
isolation of experimental models from physical actuators while enabling non-intrusive
live shadow evaluation against real sensor streams.

Primary Metrics:
1. Actuator Breach Prevention Rate: 100% prevention (0 breaches) of physical actuator
   triggers or real incident dispatches originating from RESEARCH_ONLY models.
2. Shadow Ingestion Completeness: RESEARCH_ONLY models generate shadow inference
   records and logs with zero operational impact.
3. Policy Enforcement Determinism: Explicit error and safety violation code emitted
   whenever an unapproved model attempts production execution.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class RegisteredModelRecord:
    model_id: str
    name: str
    version: str
    sha256: str
    usage_restriction: str = "RESEARCH_ONLY"  # PRODUCTION, RESEARCH_ONLY, DEPRECATED
    status: str = "RESEARCH_ONLY"             # PRODUCTION, CANDIDATE, RESEARCH_ONLY (or ACTIVE/INACTIVE)
    registry_status: str = "RESEARCH_ONLY"    # Explicit tier: PRODUCTION, CANDIDATE, RESEARCH_ONLY


@dataclass
class ModelExecutionResult:
    model_id: str
    prediction_label: str
    confidence: float
    actuators_permitted: bool
    incident_dispatch_permitted: bool
    is_shadow_only: bool
    safety_violations: List[str]


class SafetyAwareModelRegistry:
    """
    Registry enforcing strict runtime guardrails around research and production models.
    Enforces that only verified PRODUCTION models can actuate hardware or dispatch alerts.
    """

    def __init__(self):
        self.models: Dict[str, RegisteredModelRecord] = {}

    def register_model(
        self,
        model_id: str,
        name: str,
        version: str,
        sha256: str,
        usage_restriction: str = "RESEARCH_ONLY",
        status: str = "ACTIVE",
        registry_status: Optional[str] = None,
    ) -> None:
        norm_status = status.upper()
        norm_usage = usage_restriction.upper()
        # Derive effective registry status tier (PRODUCTION / CANDIDATE / RESEARCH_ONLY)
        if registry_status:
            effective_tier = registry_status.upper()
        elif norm_status in ("PRODUCTION", "CANDIDATE", "RESEARCH_ONLY"):
            effective_tier = norm_status
        elif norm_usage in ("PRODUCTION", "CANDIDATE", "RESEARCH_ONLY"):
            effective_tier = norm_usage
        else:
            effective_tier = "RESEARCH_ONLY"

        rec = RegisteredModelRecord(
            model_id=model_id,
            name=name,
            version=version,
            sha256=sha256,
            usage_restriction=norm_usage,
            status=norm_status,
            registry_status=effective_tier,
        )
        self.models[model_id] = rec

    def evaluate_execution_safety(
        self,
        model_id: str,
        predicted_label: str,
        confidence: float,
    ) -> ModelExecutionResult:
        """
        Determines whether the model output is authorized to trigger real-world
        incidents or physical actuators.
        Enforces:
        - UNREGISTERED models are rejected.
        - RESEARCH_ONLY models are restricted to shadow evaluation (no actuators, no alerts).
        - CANDIDATE models are restricted to shadow evaluation.
        - Only PRODUCTION models (active status) are authorized for physical actuation.
        """
        violations: List[str] = []
        if model_id not in self.models:
            violations.append(f"UNREGISTERED_MODEL: {model_id}")
            return ModelExecutionResult(
                model_id=model_id,
                prediction_label=predicted_label,
                confidence=confidence,
                actuators_permitted=False,
                incident_dispatch_permitted=False,
                is_shadow_only=False,
                safety_violations=violations,
            )

        model = self.models[model_id]
        tier = (model.registry_status or model.usage_restriction or "RESEARCH_ONLY").upper()
        if model.status in ("PRODUCTION", "CANDIDATE", "RESEARCH_ONLY"):
            tier = model.status.upper()

        if tier == "RESEARCH_ONLY":
            violations.append("POLICY_RESTRICTION: Model is RESEARCH_ONLY and cannot actuate physical hardware or authorize alerts")
            return ModelExecutionResult(
                model_id=model_id,
                prediction_label=predicted_label,
                confidence=confidence,
                actuators_permitted=False,
                incident_dispatch_permitted=False,
                is_shadow_only=True,
                safety_violations=violations,
            )

        if tier == "CANDIDATE":
            violations.append("POLICY_RESTRICTION: Model is CANDIDATE (shadow-evaluation only) and cannot actuate physical hardware or authorize alerts")
            return ModelExecutionResult(
                model_id=model_id,
                prediction_label=predicted_label,
                confidence=confidence,
                actuators_permitted=False,
                incident_dispatch_permitted=False,
                is_shadow_only=True,
                safety_violations=violations,
            )

        if model.status not in ("ACTIVE", "PRODUCTION"):
            violations.append(f"INACTIVE_MODEL: Model status is {model.status}")
            return ModelExecutionResult(
                model_id=model_id,
                prediction_label=predicted_label,
                confidence=confidence,
                actuators_permitted=False,
                incident_dispatch_permitted=False,
                is_shadow_only=False,
                safety_violations=violations,
            )

        # PRODUCTION and ACTIVE model
        return ModelExecutionResult(
            model_id=model_id,
            prediction_label=predicted_label,
            confidence=confidence,
            actuators_permitted=True,
            incident_dispatch_permitted=True,
            is_shadow_only=False,
            safety_violations=[],
        )
