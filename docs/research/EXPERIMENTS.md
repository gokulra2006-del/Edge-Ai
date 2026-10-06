# Sentinel-AI Research Experiments Pre-Registration Log

Project Thesis: *"An Auditable, Drift-Aware, Human-Governed Multimodal Edge AI Platform for Offline Urban Emergency Detection and Response."*

---

## Experiment 6A-1: Multimodal Fusion vs. Unimodal Baselines Under Clean and Degraded Edge Conditions

### 1. Pre-Registration Timestamp
- **Date**: 2026-10-06
- **Status**: PRE-REGISTERED (Criteria locked prior to evaluation runs)

### 2. Hypothesis
- **Hypothesis 1 (Multimodal Superiority)**: Multimodal temporal + OOD fusion achieves higher Macro-F1 and lower false-alarm rate than any single modality (audio-only, vision-only, sensor-only) and static fixed-weight fusion on clean multimodal emergency scenarios.
- **Hypothesis 2 (Graceful Degradation)**: Under simulated sensor faults (camera dropout, audio silence/clipping, sensor noise/stuck values), multimodal temporal + OOD fusion degrades more gracefully (maintaining $\ge 0.15$ higher Macro-F1) compared to static fusion due to confidence attenuation on sensor failure and out-of-distribution detection.
- **Hypothesis 3 (Offline Emergency Invariance)**: In the presence of network outage, edge incident detection and local safety actuations remain identical in accuracy and detection latency to online operation ($0.0\%$ degradation), verifying true offline-first edge autonomy.

### 3. Systems Under Test (SUT)
All systems process identical timestamped scenario streams through a unified evaluation interface:
1. `audio-only`: Classifies emergency state strictly from acoustic Mel-spectrogram stream (`EdgeAcousticNet`).
2. `vision-only`: Classifies emergency state strictly from camera vision stream (`EdgeVision YOLO`).
3. `sensor-only`: Classifies emergency state strictly from environmental telemetry (smoke, temperature, IMU).
4. `static-fusion`: Weighted average fusion with fixed weights ($w_{\text{audio}} = 0.40, w_{\text{vision}} = 0.40, w_{\text{telemetry}} = 0.20$).
5. `temporal-ood-fusion` (Our Proposed SUT): Adaptive multimodal fusion combining temporal consistency filtering, uncertainty/OOD gating, and sensor-health confidence attenuation.

### 4. Fault Injections Evaluated
1. `clean`: Nominal operation across all sensors.
2. `camera-dropout`: Vision stream cuts to black/frozen frames.
3. `audio-silence-clipping`: Acoustic stream contains pure silence or extreme clipping distortion.
4. `sensor-stuck-noise`: Environmental telemetry reports stuck values or high Gaussian noise.
5. `network-outage`: Cloud/MQTT bridge disconnected; offline local store mode.
6. `conflicting-sensors`: Extreme sensor mismatch (e.g. vision reports fire, acoustic reports quiet, temperature normal).

### 5. Benchmark Metrics & Honest Accounting
- **Detection Performance**:
  - Macro-F1 (with 95% bootstrap confidence intervals, $B=1000$).
  - Per-class F1 (`NORMAL`, `ACCIDENT`, `FIRE`, `AMBULANCE`).
  - False-Alarm Rate (FAR, %).
  - Miss Rate (False Negative Rate, %).
- **Temporal & Operational Latency**:
  - Detection Latency: Duration from ground-truth event onset to system alert trigger (seconds).
  - Time to Acknowledge (TTA, s): Simulated operator acknowledgment model parameterized by log-normal distribution ($\mu = 2.5, \sigma = 0.5$).
  - Time to Resolve (TTR, s): Simulated operator resolution model.
- **Edge Resource Footprint**:
  - Peak RAM (MB) and CPU consumption (%) measured via `psutil`.
  - Bandwidth: Byte payload per second.
  - Power / Hardware Metrics: If running on simulated/workstation environment, marked explicitly as `NOT_MEASURED` (never silently guessed).
- **Data Tagging**:
  - All scenarios explicitly labeled `SYNTHETIC` or `REPLAYED_REAL`.

### 6. Success & Failure Criteria (Locked Pre-Experiment)
- **Success Criteria**:
  1. `temporal-ood-fusion` achieves Macro-F1 $\ge 0.85$ on clean scenarios.
  2. `temporal-ood-fusion` exceeds `static-fusion` Macro-F1 by at least $+0.08$ under fault injections.
  3. False-alarm rate under `clean` scenarios is $\le 5.0\%$.
  4. Detection latency under `clean` scenarios is $\le 2.0$ seconds.
  5. 100% scenario determinism: identical random seed produces bit-exact identical metrics.
- **Failure Criteria**:
  - If `static-fusion` or unimodal baselines outperform `temporal-ood-fusion` under corrupted sensor conditions, the hypothesis of adaptive degradation fails.
  - If network outage reduces local alert triggering or detection accuracy, the offline autonomy hypothesis fails.
