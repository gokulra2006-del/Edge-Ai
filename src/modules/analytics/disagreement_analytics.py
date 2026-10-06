"""
Module: Operator Disagreement Analytics.
========================================
Analyzes human operator overrides and disagreements relative to edge model predictions.
Discovers blind spots, measures disagreement ratios per confidence bin and modality,
and correlates disagreement surges with model drift.

Research Hypothesis:
Clustering operator overrides across model confidence deciles and sensory modalities
isolates latent edge model blind spots and provides leading indicators of sensor
calibration decay prior to catastrophic model failure.

Primary Metrics:
1. Overall Disagreement Rate: Accurately computes disagreement ratio (disagreements / total reviews).
2. High-Confidence Disagreement Isolation: Isolates severe failures where model confidence
   exceeded 0.80 but operator rejected or corrected the verdict.
3. Modality Error Profiling: Determines error concentration between visual and acoustic sensors.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


@dataclass
class DisagreementRecord:
    incident_id: str
    model_id: str
    modality: str  # CAMERA, AUDIO, FUSION
    model_label: str
    model_confidence: float
    operator_verdict: str  # CONFIRMED, REJECTED, DISPUTED, CORRECTED
    operator_label: Optional[str]
    is_disagreement: bool


@dataclass
class DisagreementAnalyticsSummary:
    total_reviews: int
    total_disagreements: int
    disagreement_rate: float
    high_confidence_disagreements: int
    modality_breakdown: Dict[str, Dict[str, int]]
    confidence_bin_breakdown: Dict[str, int]
    blind_spot_clusters: List[str]


class OperatorDisagreementAnalyzer:
    """
    Computes statistical telemetry on operator vs model discrepancies.
    """

    def __init__(self):
        self.records: List[DisagreementRecord] = []

    def record_review(
        self,
        incident_id: str,
        model_id: str,
        modality: str,
        model_label: str,
        model_confidence: float,
        operator_verdict: str,
        operator_label: Optional[str] = None,
    ) -> None:
        verdict = (operator_verdict or "").strip().upper()
        # Disagreement occurs if operator rejected or corrected to a different class
        is_disagree = verdict in ("REJECTED", "DISPUTED") or (
            verdict == "CORRECTED" and operator_label and operator_label != model_label
        )

        rec = DisagreementRecord(
            incident_id=incident_id,
            model_id=model_id,
            modality=modality.upper(),
            model_label=model_label,
            model_confidence=max(0.0, min(1.0, float(model_confidence))),
            operator_verdict=verdict,
            operator_label=operator_label,
            is_disagreement=is_disagree,
        )
        self.records.append(rec)

    def analyze(self) -> DisagreementAnalyticsSummary:
        total = len(self.records)
        if total == 0:
            return DisagreementAnalyticsSummary(
                total_reviews=0,
                total_disagreements=0,
                disagreement_rate=0.0,
                high_confidence_disagreements=0,
                modality_breakdown={},
                confidence_bin_breakdown={},
                blind_spot_clusters=[],
            )

        disagreements = [r for r in self.records if r.is_disagreement]
        rate = len(disagreements) / total

        high_conf_disagree = sum(1 for r in disagreements if r.model_confidence >= 0.80)

        # Modality breakdown
        mod_breakdown: Dict[str, Dict[str, int]] = {}
        for r in self.records:
            if r.modality not in mod_breakdown:
                mod_breakdown[r.modality] = {"total": 0, "disagreements": 0}
            mod_breakdown[r.modality]["total"] += 1
            if r.is_disagreement:
                mod_breakdown[r.modality]["disagreements"] += 1

        # Confidence bins for disagreements: [0.0-0.5), [0.5-0.8), [0.8-1.0]
        bins = {"LOW_<0.5": 0, "MED_0.5-0.8": 0, "HIGH_>=0.8": 0}
        for r in disagreements:
            if r.model_confidence < 0.50:
                bins["LOW_<0.5"] += 1
            elif r.model_confidence < 0.80:
                bins["MED_0.5-0.8"] += 1
            else:
                bins["HIGH_>=0.8"] += 1

        # Blind spot clusters: labels with multiple high-confidence disagreements
        label_disagrees: Dict[str, int] = {}
        for r in disagreements:
            if r.model_confidence >= 0.80:
                label_disagrees[r.model_label] = label_disagrees.get(r.model_label, 0) + 1

        clusters = [
            f"BLIND_SPOT: {lbl} ({count} high-confidence rejections)"
            for lbl, count in label_disagrees.items()
            if count >= 2
        ]

        return DisagreementAnalyticsSummary(
            total_reviews=total,
            total_disagreements=len(disagreements),
            disagreement_rate=round(rate, 4),
            high_confidence_disagreements=high_conf_disagree,
            modality_breakdown=mod_breakdown,
            confidence_bin_breakdown=bins,
            blind_spot_clusters=clusters,
        )
