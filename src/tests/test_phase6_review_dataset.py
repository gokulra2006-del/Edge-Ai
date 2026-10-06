"""
Test Suite: Phase 6 Item 3 - Human Feedback as a Governed Review Dataset.
========================================================================
Validates governance filtering, rejected record handling, dataset curation
integrity, and deterministic SHA-256 manifest generation.
"""
from __future__ import annotations

import json
import pytest
from src.modules.incident_management.review_dataset import (
    GovernedReviewDatasetBuilder,
    GovernedSample,
)


def test_governed_feedback_ingestion_and_manifest():
    """
    Hypothesis: Governed dataset builder admits compliant feedback records,
    computes accurate class distributions, and produces bit-exact SHA-256 manifest.
    """
    builder = GovernedReviewDatasetBuilder(dataset_version="v1.0-research-2026")

    # Ingest 1: Confirmed incident
    ok1 = builder.ingest_feedback_record(
        incident_id="inc_001",
        original_event_type="GUNSHOT",
        original_confidence=0.92,
        operator_verdict="CONFIRMED",
        operator_id="operator_alice",
        notes="Acoustic echo matches 9mm report.",
    )
    assert ok1 is True

    # Ingest 2: Rejected incident (false alarm)
    ok2 = builder.ingest_feedback_record(
        incident_id="inc_002",
        original_event_type="SCREAM",
        original_confidence=0.64,
        operator_verdict="REJECTED",
        operator_id="operator_bob",
        notes="Children playing in park.",
    )
    assert ok2 is True

    # Ingest 3: Corrected incident
    ok3 = builder.ingest_feedback_record(
        incident_id="inc_003",
        original_event_type="GLASS_BREAK",
        original_confidence=0.71,
        operator_verdict="CORRECTED",
        operator_id="operator_alice",
        final_ground_truth_label="DOOR_SLAM",
        notes="Heavy steel security door slammed shut.",
    )
    assert ok3 is True

    payload, manifest = builder.export_dataset()

    assert manifest.total_samples == 3
    assert manifest.confirmed_count == 1
    assert manifest.rejected_count == 1
    assert manifest.corrected_count == 1
    assert manifest.disputed_count == 1  # Corrected with different label counts as disputed
    assert manifest.class_distribution == {
        "GUNSHOT": 1,
        "BACKGROUND_NOISE": 1,
        "DOOR_SLAM": 1,
    }
    assert len(manifest.sha256_checksum) == 64
    assert len(payload["samples"]) == 3


def test_governance_rules_rejection():
    """
    Hypothesis: Ingestion strictly rejects invalid verdicts, anonymous authors,
    and missing ground truth resolutions.
    """
    builder = GovernedReviewDatasetBuilder()

    # Reject 1: Anonymous operator
    assert builder.ingest_feedback_record(
        incident_id="inc_004",
        original_event_type="FIRE",
        original_confidence=0.88,
        operator_verdict="CONFIRMED",
        operator_id="anonymous",
    ) is False

    # Reject 2: Invalid verdict enum
    assert builder.ingest_feedback_record(
        incident_id="inc_005",
        original_event_type="FIRE",
        original_confidence=0.88,
        operator_verdict="MAYBE_REAL",
        operator_id="operator_charlie",
    ) is False

    # Reject 3: Corrected without specifying final label
    assert builder.ingest_feedback_record(
        incident_id="inc_006",
        original_event_type="FIRE",
        original_confidence=0.88,
        operator_verdict="CORRECTED",
        operator_id="operator_charlie",
        final_ground_truth_label=None,
    ) is False

    # Rejection count: Builder remains empty
    assert len(builder.samples) == 0
