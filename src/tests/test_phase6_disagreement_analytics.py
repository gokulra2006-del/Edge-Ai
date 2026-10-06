"""
Test Suite: Phase 6 Item 8 - Operator Disagreement Analytics.
============================================================
Tests operator disagreement tracking, high-confidence blind spot isolation,
and modality-specific error profiling.
"""
from __future__ import annotations

import pytest
from src.modules.analytics.disagreement_analytics import OperatorDisagreementAnalyzer


def test_disagreement_analytics_metrics_and_blind_spots():
    """
    Hypothesis: The analyzer accurately computes disagreement ratios,
    identifies high-confidence false alarms, and flags blind spot clusters.
    """
    analyzer = OperatorDisagreementAnalyzer()

    # 1. Agrees: Video detection confirmed
    analyzer.record_review(
        incident_id="inc_1",
        model_id="yolo_v8",
        modality="CAMERA",
        model_label="PERSON_DOWN",
        model_confidence=0.88,
        operator_verdict="CONFIRMED",
    )

    # 2. Agrees: Audio detection confirmed
    analyzer.record_review(
        incident_id="inc_2",
        model_id="yamnet",
        modality="AUDIO",
        model_label="GUNSHOT",
        model_confidence=0.92,
        operator_verdict="CONFIRMED",
    )

    # 3. Disagreement: High-confidence false alarm 1
    analyzer.record_review(
        incident_id="inc_3",
        model_id="yolo_v8",
        modality="CAMERA",
        model_label="FIRE",
        model_confidence=0.85,
        operator_verdict="REJECTED",  # Sunset glare misclassified
    )

    # 4. Disagreement: High-confidence false alarm 2 on same label
    analyzer.record_review(
        incident_id="inc_4",
        model_id="yolo_v8",
        modality="CAMERA",
        model_label="FIRE",
        model_confidence=0.89,
        operator_verdict="REJECTED",  # Halogen spotlight misclassified
    )

    # 5. Disagreement: Low confidence audio rejection
    analyzer.record_review(
        incident_id="inc_5",
        model_id="yamnet",
        modality="AUDIO",
        model_label="SCREAM",
        model_confidence=0.45,
        operator_verdict="REJECTED",
    )

    summary = analyzer.analyze()

    assert summary.total_reviews == 5
    assert summary.total_disagreements == 3
    assert summary.disagreement_rate == 0.60
    assert summary.high_confidence_disagreements == 2  # The two FIRE rejections >= 0.80

    # Modality checks
    assert summary.modality_breakdown["CAMERA"]["disagreements"] == 2
    assert summary.modality_breakdown["AUDIO"]["disagreements"] == 1

    # Confidence bin checks
    assert summary.confidence_bin_breakdown["HIGH_>=0.8"] == 2
    assert summary.confidence_bin_breakdown["LOW_<0.5"] == 1

    # Blind spot detection: 'FIRE' has 2 high-confidence rejections
    assert any("BLIND_SPOT: FIRE" in c for c in summary.blind_spot_clusters)
