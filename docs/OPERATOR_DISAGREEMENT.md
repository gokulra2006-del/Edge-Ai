# Operator Disagreement Analytics

## 1. Research Overview
Supervisory operations in edge AI command centers generate critical telemetry whenever human security officers override, dismiss, or correct model-inferred event classifications. Without systematic statistical profiling, these operator interventions remain isolated transactions rather than actionable diagnostic signals.

This research establishes an **operator disagreement analyzer** that breaks down human overrides across confidence tiers, isolates high-confidence blind spots, and profiles sensory modalities.

---

## 2. Formal Research Specifications

### Hypothesis
Systematic profiling of human operator disagreements across model confidence deciles and sensory modalities exposes latent model blind spots (e.g. repeated false positives with $\ge 0.80$ model confidence) and provides early warnings of sensor degradation or environmental lighting shifts.

### Primary Metrics
1. **Disagreement Rate Accuracy**: Exact computation of operator rejection and correction proportions relative to total reviewed events.
2. **High-Confidence Blind Spot Discovery**: Automated clustering and identification of classes with $\ge 2$ overrides at $\ge 0.80$ confidence.
3. **Modality Error Profiling**: Exact separation of error rates between visual (`CAMERA`), acoustic (`AUDIO`), and multimodal (`FUSION`) pipelines.

---

## 3. Evaluation Methodology

### Evaluation Scenarios
1. **Multi-Class Review Dataset Evaluation**:
   - Ingests a mixture of confirmed events (`PERSON_DOWN`, `GUNSHOT`) and rejected events (`FIRE`, `SCREAM`).
   - Asserts overall disagreement rate ($60\%$).

2. **Blind Spot Isolation Benchmark**:
   - Injects multiple high-confidence false alarms for `FIRE` due to sunlight glare.
   - Evaluates whether the analyzer flags `BLIND_SPOT: FIRE` in its summary clusters and attributes errors to the `CAMERA` modality.

---

## 4. Implementation Reference
- Implementation: [`OperatorDisagreementAnalyzer`](file:///C:/Users/gokul/Desktop/PROJECTS/Edge-AI/src/modules/analytics/disagreement_analytics.py)
- Automated Tests: [`test_phase6_disagreement_analytics.py`](file:///C:/Users/gokul/Desktop/PROJECTS/Edge-AI/src/tests/test_phase6_disagreement_analytics.py)
