# Reproducible Incident Replay for Evaluation

## 1. Research Overview
Evaluating edge artificial intelligence systems against live camera and microphone streams introduces non-deterministic latency jitter, varying network conditions, and unrepeatable physical environments. Without deterministic replay mechanisms, evaluating algorithmic improvements or diagnosing false positive cascades becomes virtually impossible.

This research formulates an **isolated virtual-time incident replay engine** capable of reproducing complex multi-modal sensor telemetry with $100\%$ determinism.

---

## 2. Formal Research Specifications

### Hypothesis
Executing serialized multi-sensor telemetry traces through the decision engine in an isolated virtual-time event loop produces $100\%$ deterministic risk accumulation trajectories and declaration state transitions across repeated runs, enabling rigorous counterfactual evaluation and sensitivity analysis.

### Primary Metrics
1. **Replay Determinism**: $100\%$ identical risk score decimals, state flags, and trigger steps across repeated evaluation runs on the same serialized trace.
2. **Chronological Integrity**: Strict monotonicity of event timestamp offsets with zero temporal inversion during execution.
3. **Counterfactual Sensitivity**: Immediate, measurable shifts in incident declaration timing when altering engine threshold parameters.

---

## 3. Evaluation Methodology

### Evaluation Scenarios
1. **Cross-Run Repeatability Benchmark**:
   - Replays a 3-step multimodal event trace (`RAPID_APPROACH` $\to$ `TIRE_SCREECH` $\to$ `VEHICLE_COLLISION`) twice in independent instances.
   - Asserts bit-exact match across all accumulated risk values, state transitions, and declaration indices.

2. **Counterfactual Threshold Sensitivity**:
   - Compares incident declaration behavior at baseline threshold ($0.75$) vs strict threshold ($0.99$).
   - Demonstrates clear, measurable counterfactual divergence (declared at step 2 vs never declared).

---

## 4. Implementation Reference
- Implementation: [`IncidentReplayEngine`](file:///C:/Users/gokul/Desktop/PROJECTS/Edge-AI/src/modules/incident_management/incident_replay.py)
- Automated Tests: [`test_phase6_incident_replay.py`](file:///C:/Users/gokul/Desktop/PROJECTS/Edge-AI/src/tests/test_phase6_incident_replay.py)
