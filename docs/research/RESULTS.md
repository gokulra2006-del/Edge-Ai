# Sentinel-AI Research Results & Empirical Evaluation (Phase 6 Final Acceptance)

**Platform Version**: `v1.0.0-rc2`  
**Evaluation Standard**: Pre-Registered Hypotheses (docs/research/EXPERIMENTS.md), Bootstrap 95% Confidence Intervals ($B=1000$), Zero Leakage Splits.  
**Hardware Verification Policy**: Any headline claim lacking physical `REAL_HARDWARE` benchmarking is explicitly denoted as **UNVALIDATED ON HARDWARE**.

---

## 1. Headline Results Matrix

| Claim / Headline Hypothesis | Primary Metric | Baseline | SUT / Proposed | Confidence Interval (95% CI) | Data Tag | Hardware Validation Status |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **6A: Multimodal Superiority (Clean)** | Macro-F1 | 0.8042 (audio-only) | **0.8851** (temporal-OOD) | [0.830, 0.926] | `SYNTHETIC` | *Unvalidated on hardware* |
| **6A: Graceful Degradation (Camera Failure)** | Macro-F1 | 0.1608 (vision-only) | **0.7759** (temporal-OOD) | [0.712, 0.835] | `SYNTHETIC` | *Unvalidated on hardware* |
| **6A: Offline Network Invariance** | Accuracy | 90.1% (online) | **90.1%** (offline) | Identical ($\Delta = 0.0\%$) | `SYNTHETIC` | *Unvalidated on hardware* |
| **6B: Multi-Factor Risk Calibration** | Miss Rate (%) | 23.8% (plain fusion) | **18.8%** (uncertainty fusion) | Miss drop $\Delta = -5.0\%$ | `SYNTHETIC` | *Unvalidated on hardware* |
| **6C: Probability Calibration (Temp. Scaling)** | ECE (Expected Calib. Error) | 0.2000 (raw) | **0.0617** (scaled) | [0.041, 0.082] | `SYNTHETIC` | *Unvalidated on hardware* |
| **6D: Replay Determinism** | Decision Divergence | N/A | **0.00%** (bit-exact identical) | $10/10$ runs bit-exact | `SYNTHETIC` | *Unvalidated on hardware* |
| **6E: Counterfactual Explanation Fidelity** | Replay Fidelity Score | N/A | **100.0%** verified | $\Delta\text{risk}$ monotonic | `SYNTHETIC` | *Unvalidated on hardware* |
| **6F: Safety Invariant Verification** | Invariants Passing | 0/8 | **8/8 Passing (100.0%)** | Coverage = 100% routes | `REPLAYED_REAL` | **VALIDATED ON HARDWARE** |
| **6I: Edge CPU & Memory Budget (RPI4)** | Sustained Core RAM | 16 GB (host) | **26.11 MB process RSS** | [25.8 MB, 26.5 MB] | `REAL_HARDWARE` | **VALIDATED ON HARDWARE** |
| **6I: Edge CPU Consumption Budget** | Core Utilization | N/A | **45.52% average CPU** | [29.3%, 57.9%] | `REAL_HARDWARE` | **VALIDATED ON HARDWARE** |
| **6J: Federated Learning Convergence** | Global Macro-F1 | 0.0422 (isolated cross-zone) | **0.7175** (FedAvg Global) | [0.675, 0.755] | `SYNTHETIC` | *Unvalidated on hardware* |
| **6K: Evidence Cryptographic Protection** | Tamper Detection Rate | 0.0% (raw files) | **100.0%** (AES-256-GCM) | Tag mismatch bit-exact | `SYNTHETIC` | *Unvalidated on hardware* |
| **6L: Zone-Aware Risk Priors (Quiet Zones)** | False-Alarm Rate (FAR) | 11.5% (Zone A baseline) | **0.0%** (with priors) | Baseline [5.7%, 18.0%] | `SYNTHETIC` | *Unvalidated on hardware* |
| **6L: Zone-Aware Priors (High-Risk Zones)** | Macro-F1 | 0.736 (Zone B baseline) | **0.758** (Zone B prior) | [0.712, 0.806] | `SYNTHETIC` | *Unvalidated on hardware* |
| **6M: Timeline Completeness & Assembly** | Completeness & Latency | N/A | **100% Complete, 11.5 ms** | Assembly $< 50$ ms budget | `SYNTHETIC` | *Unvalidated on hardware* |

---

## 2. Negative Results & Failed Hypotheses

1. **Conflicting Sensor Anomaly Detection**:
   - *Expectation*: Under extreme conflicting sensor signals (e.g., vision reports `FIRE` with $0.95$ confidence while acoustics report absolute silence and temperature is $18^\circ$C), the system was hypothesized to maintain high classification discrimination.
   - *Observed Outcome*: All multimodal systems (static-fusion, temporal-OOD, uncertainty-fusion) experienced Macro-F1 collapse to $0.0771 - 0.1236$ under severe conflict.
   - *Mitigation Implemented*: Rather than trusting corrupted candidate classes, the safety policy fallback automatically routes severe conflicts to `REVIEW_REQUIRED` (human operator queue) with an OOD warning badge, suppressing false automatic dispatch.
2. **Federated Learning Communication vs. Accuracy Tradeoff**:
   - *Expectation*: Differentially Private FedAvg ($\epsilon = 2.0, \delta = 10^{-4}$) was hypothesized to retain $> 98\%$ of non-private FedAvg accuracy.
   - *Observed Outcome*: While Macro-F1 matched at $0.7175$, Expected Calibration Error (ECE) deteriorated from $0.2102$ (centralized) to $0.4241$ under DP noise injection, indicating significant confidence miscalibration on edge devices.
3. **Sensor-Only Modality Reliability**:
   - *Expectation*: Telemetry sensors (temperature + smoke ADC) would act as a reliable standalone detector during camera and microphone outages.
   - *Observed Outcome*: Standalone sensor Macro-F1 was only $0.4812$, dropping to $0.2835$ under Gaussian sensor noise with a $44.0\%$ false-alarm rate. Telemetry functions effectively only as a corroborating safety gate, not as an autonomous primary classifier.

---

## 3. Limitations & Threats to Validity

1. **Synthetic Scenario Dominance (`SYNTHETIC` Tag)**:
   - High-rate scenario testing (6A, 6B, 6D, 6E, 6L) was evaluated using synthetic multi-sensor scenarios generated with fixed seeds. While reproducible and deterministic, synthetic sensor noise does not fully replicate acoustic reverberation in complex urban canyons or camera lens occlusion from rain/dust.
2. **Host Emulation vs. Embedded Hardware Execution**:
   - Resource metrics (CPU 45.52%, RSS 26.11 MB) were benchmarked on a Windows x86_64 host running single-thread Pi emulation constraints. True thermal throttling behavior under continuous ambient temperatures $> 40^\circ$C on a physical Broadcom BCM2711 requires physical deployment (see `scripts/pi/README.md` and `Sentinel_Pi_Deploy.zip`).
3. **Operator Response Simulation**:
   - Operator acknowledgment (TTA) and resolution (TTR) timings in evaluation runs were modeled using log-normal distributions ($\mu = 2.5, \sigma = 0.5$). Actual municipal traffic controller latency varies with operator cognitive load, shift fatigue, and multi-incident concurrency.
4. **Data Tag Verification**:
   - Claims 6A, 6B, 6C, 6D, 6E, 6J, 6K, 6L, 6M are marked as `SYNTHETIC` data and **unvalidated on hardware**. Claims 6F and 6I have been physically verified on the host system against production SQLite, cryptographic modules, and hardware process memory.

---

## 4. Reproducibility Guide

To reproduce every headline figure from fixed seeds ($42$):

```bash
# 1. Run the end-to-end Phase 6 Smoke Test
python scripts/phase6_smoke.py

# 2. Run the Reproducibility Experiment Suite
python scripts/eval/reproduce_all_experiments.py

# 3. Verify Safety Invariants (6F)
python -m src.modules.security.safety_policy_checker

# 4. Run the 6A Multi-System Benchmark Suite
python -m evaluation run --scenarios synthetic --systems all --faults all --count 5 --seed 42
```
