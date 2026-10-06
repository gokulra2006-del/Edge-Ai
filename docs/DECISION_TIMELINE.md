# Phase 6 Research: Explainable Multimodal Decision Timelines

## 1. Research Overview

In safety-critical municipal emergency infrastructure, machine learning predictions must be auditable and interpretable. When an edge node flags an emergency (such as a collision or structural fire), human operators require rapid, unambiguous situational awareness explaining *what* happened, *which modalities* triggered the decision, and in *what order*.

---

## 2. Hypothesis, Metric, and Evaluation Methodology

### Hypothesis
Aligning asynchronous multimodal sensory telemetry (acoustic signatures, vision bounding boxes, IMU impact spikes, environmental telemetry), deep learning inferences, and human operator actions into a chronologically indexed, attribution-weighted decision graph significantly eliminates post-incident forensic ambiguity and establishes 100% causal completeness.

### Metrics
1. **Causal Completeness Score**:
   $$\text{Causal Completeness (\%)} = \left( \frac{\text{Decision Steps with Verified Modality Attribution}}{\text{Total Timeline Steps}} \right) \times 100$$
   *Target: $100.0\%$.*
2. **Attribution Fidelity**:
   $$\text{Dominant Modality} = \arg\max_{m} w_m$$
   Verifies that the synthesized causal explanation highlights the dominant contributing sensor channel according to the fusion weight matrix.
3. **Temporal Monotonicity**:
   Relative event timestamps must strictly satisfy $T_0 \le T_1 \le \dots \le T_N$.
4. **Edge Synthesis Latency**:
   Timeline generation time on Raspberry Pi 4 CPU ($< 15\text{ ms}$).

### Evaluation Methodology
- Unit and integration tests in [`src/tests/test_phase6_decision_timeline.py`](file:///C:/Users/gokul/Desktop/PROJECTS/Edge-AI/src/tests/test_phase6_decision_timeline.py).
- Evaluates multi-channel event collation (audio + vision + rule trigger + operator acknowledgement), relative timestamp normalization, and resilience against corrupt or missing JSON payloads.

---

## 3. Architecture & Implementation

Implemented in [`src/modules/decision_engine/decision_timeline.py`](file:///C:/Users/gokul/Desktop/PROJECTS/Edge-AI/src/modules/decision_engine/decision_timeline.py):

* **`TimelineEntry`**: Encapsulates relative timestamp ($T \pm \Delta t$), modality identifier, event classification, confidence, modality contribution weights, and plain-language explanation.
* **`MultimodalTimelineEngine`**:
  - Ingests governed incident records, associated predictions from SQLite, and operator audit trail entries.
  - Normalizes asynchronous timestamps relative to incident genesis ($T = 0.0\text{s}$).
  - Computes weighted attribution and identifies dominant modalities.
  - Synthesizes a chronological plain-language causal narrative (e.g. `[T-0.40s] Acoustic sensor detected audio signature 'siren_detected' -> [T-0.20s] Vision stream identified 'crash_visual_detected' -> [T+0.00s] Incident declared (CRITICAL) -> [T+12.50s] Operator 'commander_1' executed action 'ACKNOWLEDGE'`).
