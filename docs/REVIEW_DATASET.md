# Human Feedback as a Governed Review Dataset

## 1. Research Overview
Operational edge AI deployments produce high volumes of human supervisory actions—such as incident acknowledgments, false-alarm dismissals, and ground-truth corrections. In uncurated pipelines, this feedback often contains ambiguities, anonymous submissions, or disputed edge cases, which degrade model retraining pipelines if ingested without validation.

This module formalizes human supervisory actions into an **immutable, governance-validated active learning dataset** with end-to-end cryptographic provenance.

---

## 2. Formal Research Specifications

### Hypothesis
Treating operator review feedback as a structured, immutable dataset governed by strict verification constraints (mandating authenticated operator identity, standardized verdict enums, and explicit ground-truth reconciliation) ensures that 100% of admitted samples satisfy curation standards and generates tamper-evident SHA-256 manifests for reproducible model retraining.

### Primary Metrics
1. **Governance Compliance Rate**: $100\%$ of admitted feedback samples adhere to schema validation rules (rejection of anonymous/demo users or unmapped labels).
2. **Provenance Integrity**: Deterministic generation of a 64-character SHA-256 cryptographic digest across serialized dataset records.
3. **Dispute Isolation**: Exact categorization and tracking of disputed vs. agreed annotations across all target event classes.

---

## 3. Evaluation Methodology

### Evaluation Scenarios
1. **Multi-Verdict Dataset Assembly**:
   - Ingests `CONFIRMED`, `REJECTED`, and `CORRECTED` feedback records submitted by authenticated operators (`operator_alice`, `operator_bob`).
   - Verifies class distribution computation and automatic assignment of background noise to rejected alerts.
   - Evaluates whether the generated SHA-256 manifest accurately matches record contents.

2. **Governance Rejection Testing**:
   - Submits records with anonymous operator attribution, illegal verdict strings, and unmapped ground-truth corrections.
   - Verifies that $100\%$ of non-compliant records are rejected, preserving a zero-contamination dataset.

---

## 4. Implementation Reference
- Implementation: [`GovernedReviewDatasetBuilder`](file:///C:/Users/gokul/Desktop/PROJECTS/Edge-AI/src/modules/incident_management/review_dataset.py)
- Automated Tests: [`test_phase6_review_dataset.py`](file:///C:/Users/gokul/Desktop/PROJECTS/Edge-AI/src/tests/test_phase6_review_dataset.py)
