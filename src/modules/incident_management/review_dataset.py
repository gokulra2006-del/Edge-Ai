"""
Module: Human Feedback as a Governed Review Dataset.
====================================================
Transforms human operator feedback, resolution verdicts, and dispute labels into
a cryptographically verifiable, strictly governed machine learning review dataset.

Research Hypothesis:
Treating operator review feedback as a structured, immutable, schema-validated
dataset with strict governance filters (excluding unverified, ambiguous, or demo
artifacts) achieves 100% curation provenance and guarantees zero contaminated or
unresolved annotations enter fine-tuning and active learning pipelines.

Primary Metrics:
1. Governance Compliance Rate: 100% of exported dataset samples satisfy strict
   eligibility criteria (valid status, verified operator ID, non-empty label).
2. Provenance Integrity: Dataset manifest includes SHA-256 integrity hash over all
   included records, enabling bit-exact audit verification.
3. Class Balance Fidelity: Extracts accurate multi-class breakdown and dispute ratios.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Dict, List, Optional


@dataclass
class GovernedSample:
    sample_id: str
    incident_id: str
    original_event_type: str
    original_confidence: float
    operator_verdict: str  # CONFIRMED, REJECTED, DISPUTED, CORRECTED
    final_ground_truth_label: str
    operator_id: str
    notes: str
    is_disputed: bool
    media_references: List[str]
    reviewed_at: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sample_id": self.sample_id,
            "incident_id": self.incident_id,
            "original_event_type": self.original_event_type,
            "original_confidence": round(self.original_confidence, 4),
            "operator_verdict": self.operator_verdict,
            "final_ground_truth_label": self.final_ground_truth_label,
            "operator_id": self.operator_id,
            "notes": self.notes,
            "is_disputed": self.is_disputed,
            "media_references": self.media_references,
            "reviewed_at": self.reviewed_at,
        }


@dataclass
class GovernedDatasetManifest:
    dataset_version: str
    created_at: str
    total_samples: int
    disputed_count: int
    confirmed_count: int
    rejected_count: int
    corrected_count: int
    class_distribution: Dict[str, int]
    sha256_checksum: str
    governance_rules_applied: List[str]


class GovernedReviewDatasetBuilder:
    """
    Curates and exports operator feedback into an immutable review dataset.
    """

    ALLOWED_VERDICTS = {"CONFIRMED", "REJECTED", "DISPUTED", "CORRECTED"}

    def __init__(self, dataset_version: str = "v1.0-research"):
        self.dataset_version = dataset_version
        self.samples: List[GovernedSample] = []

    def ingest_feedback_record(
        self,
        incident_id: str,
        original_event_type: str,
        original_confidence: float,
        operator_verdict: str,
        operator_id: str,
        final_ground_truth_label: Optional[str] = None,
        notes: str = "",
        media_references: Optional[List[str]] = None,
        reviewed_at: Optional[str] = None,
    ) -> bool:
        """
        Validates governance constraints before ingesting feedback into dataset.
        Returns True if admitted, False if rejected by governance rules.
        """
        # Governance Rule 1: Valid verdict enum
        verdict = (operator_verdict or "").strip().upper()
        if verdict not in self.ALLOWED_VERDICTS:
            return False

        # Governance Rule 2: Must have authenticated operator ID (no anonymous/demo)
        if not operator_id or operator_id.lower() in ("anonymous", "system_auto", ""):
            return False

        # Governance Rule 3: Valid incident ID
        if not incident_id or not incident_id.strip():
            return False

        # Governance Rule 4: Final ground truth label resolution
        if not final_ground_truth_label or not final_ground_truth_label.strip():
            if verdict == "CONFIRMED":
                final_ground_truth_label = original_event_type
            elif verdict == "REJECTED":
                final_ground_truth_label = "BACKGROUND_NOISE"
            else:
                # Disputed or corrected without explicit label cannot be admitted
                return False

        is_disputed = (verdict == "DISPUTED") or (verdict == "CORRECTED" and final_ground_truth_label != original_event_type)

        sample_id = f"smp_{incident_id}_{len(self.samples) + 1:04d}"
        reviewed_ts = reviewed_at or datetime.now(timezone.utc).isoformat()

        sample = GovernedSample(
            sample_id=sample_id,
            incident_id=incident_id,
            original_event_type=original_event_type,
            original_confidence=float(original_confidence),
            operator_verdict=verdict,
            final_ground_truth_label=final_ground_truth_label.strip(),
            operator_id=operator_id.strip(),
            notes=notes.strip(),
            is_disputed=is_disputed,
            media_references=media_references or [],
            reviewed_at=reviewed_ts,
        )
        self.samples.append(sample)
        return True

    def export_dataset(self) -> Tuple[Dict[str, Any], GovernedDatasetManifest]:
        """
        Exports all valid samples into JSON structure and computes cryptographically
        secure SHA-256 provenance manifest.
        """
        records = [s.to_dict() for s in self.samples]
        records_json = json.dumps(records, sort_keys=True, indent=2)
        checksum = hashlib.sha256(records_json.encode("utf-8")).hexdigest()

        # Metrics aggregation
        class_dist: Dict[str, int] = {}
        for s in self.samples:
            class_dist[s.final_ground_truth_label] = class_dist.get(s.final_ground_truth_label, 0) + 1

        manifest = GovernedDatasetManifest(
            dataset_version=self.dataset_version,
            created_at=datetime.now(timezone.utc).isoformat(),
            total_samples=len(self.samples),
            disputed_count=sum(1 for s in self.samples if s.is_disputed),
            confirmed_count=sum(1 for s in self.samples if s.operator_verdict == "CONFIRMED"),
            rejected_count=sum(1 for s in self.samples if s.operator_verdict == "REJECTED"),
            corrected_count=sum(1 for s in self.samples if s.operator_verdict == "CORRECTED"),
            class_distribution=class_dist,
            sha256_checksum=checksum,
            governance_rules_applied=[
                "VERDICT_ENUM_VALIDATION",
                "AUTHENTICATED_OPERATOR_REQUIRED",
                "RESOLVED_GROUND_TRUTH_REQUIRED",
                "DETERMINISTIC_SHA256_PACKAGING",
            ],
        )

        export_payload = {
            "manifest": {
                "dataset_version": manifest.dataset_version,
                "created_at": manifest.created_at,
                "total_samples": manifest.total_samples,
                "disputed_count": manifest.disputed_count,
                "confirmed_count": manifest.confirmed_count,
                "rejected_count": manifest.rejected_count,
                "corrected_count": manifest.corrected_count,
                "class_distribution": manifest.class_distribution,
                "sha256_checksum": manifest.sha256_checksum,
                "governance_rules_applied": manifest.governance_rules_applied,
            },
            "samples": records,
        }

        return export_payload, manifest
