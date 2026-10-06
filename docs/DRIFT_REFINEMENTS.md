# Edge OOD and Model Drift Monitoring Refinements

## 1. Research Overview
Edge AI nodes deployed in physical environments frequently encounter non-stationary sensor distributions caused by weather shifts, lighting transitions, microphone occlusion, or lens degradation. Standard batch drift monitoring requires hundreds of samples, introducing severe detection delays or false alarms due to transient noise on small windows.

This research introduces a **multi-scale dual-window drift monitor with exponential moving average (EMA) smoothing** specifically engineered for resource-constrained edge deployments.

---

## 2. Formal Research Specifications

### Hypothesis
A dual-scale drift estimation architecture—coupling an agile 20-sample fast window for acute distribution shocks with an EMA-smoothed 100-sample slow window for gradual covariate shift—suppresses spurious drift false alarms on noisy edge telemetry while detecting authentic camera/audio distribution collapse within $\le 20$ predictions.

### Primary Metrics
1. **False Alarm Suppression Rate**: Zero false `DRIFT_DETECTED` triggers under stationary, in-distribution test workloads ($0\%$ spurious trigger rate).
2. **Shock Detection Latency**: Fast-window detection of severe distribution collapse (e.g. lens obstruction) within $\le 20$ samples.
3. **Assurance Degradation Determinism**: Immediate, deterministic transition of recommended system assurance from `FULL` to `DEGRADED` upon sustained distribution divergence ($\text{PSI} \ge 0.25$ or $\text{OOD rate} \ge 20\%$).

---

## 3. Evaluation Methodology

### Evaluation Scenarios
1. **Stationary Baseline Benchmark**:
   - Ingests $100$ predictions drawn from the reference baseline histogram.
   - Evaluates whether $\text{PSI}_{\text{EMA}} < 0.10$, status remains `STABLE`, and recommended assurance is `FULL`.

2. **Acute Sensor Failure (Shock) Injection**:
   - Simulates camera lens occlusion by shifting incoming confidence scores to $\le 0.08$ with high Out-Of-Distribution (OOD) flags.
   - Asserts that within $20$ samples, the fast-window catches the distribution shift, transitioning system status to `DRIFT_DETECTED` and assurance recommendation to `DEGRADED`.

3. **Gradual Covariate Shift & Watch State**:
   - Ingests intermediate drift signals ($0.35$ confidence), observing the smoothing behavior of $\text{PSI}_{\text{EMA}}$.
   - Asserts progressive elevation into `WATCH` state and recommendation of `REVIEW_REQUIRED` before hard system failure occurs.

---

## 4. Implementation Reference
- Implementation: [`RefinedEdgeDriftMonitor`](file:///C:/Users/gokul/Desktop/PROJECTS/Edge-AI/src/modules/assurance/refined_drift_monitor.py)
- Automated Tests: [`test_phase6_refined_drift.py`](file:///C:/Users/gokul/Desktop/PROJECTS/Edge-AI/src/tests/test_phase6_refined_drift.py)
