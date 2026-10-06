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


---

## Experiment 6B-1: Uncertainty-Aware Fusion and Multi-Factor Explicit Risk Accounting

### 1. Pre-Registration Timestamp
- **Date**: 2026-10-06
- **Status**: PRE-REGISTERED (Criteria locked prior to evaluation runs)

### 2. Hypothesis
- **Hypothesis**: "Uncertainty-aware risk reduces false alarms without increasing missed emergencies."
- **Mathematical Multi-Factor Formulation**:
  $$\text{final\_risk} = \text{event\_confidence} \times \text{temporal\_consistency} \times \text{sensor\_agreement} \times \text{device\_health} \times \text{calibration\_quality} \times \prod_{i} \text{penalty}_i$$
  where each factor is strictly bounded in $[0.0, 1.0]$.
- **Invariance Rule**: Degrading any sensor or health input can NEVER increase $\text{final\_risk}$ (monotonic non-increasing property).
- **Safety Fallback Guard**: When $\text{final\_risk}$ falls below the alert threshold ($0.50$) due to high uncertainty/health penalties, but raw evidence remains strong ($\text{event\_confidence} \ge 0.65$), the incident is routed to `REVIEW_REQUIRED` (human operator queue) rather than silently dropped.

### 3. Factor Definitions & Bounds
1. **$\text{event\_confidence} \in [0.0, 1.0]$**: Highest posterior class probability from raw modality detectors.
2. **$\text{temporal\_consistency} \in [0.0, 1.0]$**: Ratio of window frames confirming the candidate class multiplied by window stability factor:
   $$\text{temporal\_consistency} = \left(\frac{N_{\text{class}}}{W}\right) \times \min\left(1.0, \frac{W}{W_{\text{target}}}\right)$$
3. **$\text{sensor\_agreement} \in [0.0, 1.0]$**: Cosine/Jaccard agreement among active modalities. If multiple sensors confirm identical event class, agreement $= 1.0$; if sensor readings contradict (e.g. vision fire but acoustic silence), agreement drops to $0.20 - 0.40$.
4. **$\text{device\_health} \in [0.0, 1.0]$**: Normalized health score computed from camera FPS, audio clipping/silence flags, and sensor staleness:
   $$\text{device\_health} = 0.40 \cdot H_{\text{camera}} + 0.40 \cdot H_{\text{audio}} + 0.20 \cdot H_{\text{sensors}}$$
5. **$\text{calibration\_quality} \in [0.0, 1.0]$**: Expected calibration reliability score (defaults to $1.0$ until temperature scaling is active in 6C).
6. **Penalties**:
   - $\text{penalty}_{\text{ood}} = 0.60$ if out-of-distribution anomaly detected.
   - $\text{penalty}_{\text{short\_evidence}} = 0.75$ if evidence duration $< 1.0$s.
   - $\text{penalty}_{\text{unreliable\_zone}} = 0.85$ if GPS/zone covariance is high.

### 4. Ablation Suite Under Test
1. `full_uncertainty_aware`: Complete 5-factor risk model.
2. `ablation_no_temporal`: $\text{temporal\_consistency} = 1.0$.
3. `ablation_no_agreement`: $\text{sensor\_agreement} = 1.0$.
4. `ablation_no_health`: $\text{device\_health} = 1.0$.
5. `plain_fusion`: Unweighted raw confidence thresholding.

### 5. Success & Failure Criteria (Locked Pre-Experiment)
- **Success Criteria**:
  1. False-alarm rate of `full_uncertainty_aware` is lower than or equal to `plain_fusion` across all scenarios.
  2. Miss rate increase on genuine emergencies is $\le 2.0\%$ (mitigated by `REVIEW_REQUIRED` routing).
  3. Monotonic non-increasing property holds for 100% of tested health degradations.
  4. Decision logs persist all factor components with every incident record.
- **Failure Criteria**:
  - If uncertainty-aware risk increases false-alarm rate compared to plain fusion, hypothesis fails.
  - If miss rate increases by $> 5.0\%$ without routing to human review, safety invariant fails.


---

## Experiment 6C-1: Post-Hoc Confidence Calibration (Temperature Scaling & Isotonic Regression)

### 1. Pre-Registration Timestamp
- **Date**: 2026-10-06
- **Status**: PRE-REGISTERED (Criteria locked prior to evaluation runs)

### 2. Hypothesis
- **Hypothesis**: "Post-hoc confidence calibration lowers Expected Calibration Error (ECE) and Brier Score, and prevents overconfident false alarms during distribution shifts and post-drift operational periods."
- **Held-Out Split Invariant**: Calibrators are fitted strictly on a held-out calibration split (50% calibration, 50% test); NEVER fitted on test data (zero leakage).
- **OOD Confidence Cap Rule**: On synthetic anomaly or Out-of-Distribution (OOD) inputs, calibrated confidence must be strictly capped ($\le 0.40$) and flagged; 100% confidence on OOD data is strictly prohibited.

### 3. Mathematical Metrics
1. **Expected Calibration Error (ECE)**:
   $$\text{ECE} = \sum_{m=1}^{M} \frac{|B_m|}{N} |\text{acc}(B_m) - \text{conf}(B_m)|$$
   over $M=10$ equal-width probability bins.
2. **Maximum Calibration Error (MCE)**:
   $$\text{MCE} = \max_{m \in \{1,\dots,M\}} |\text{acc}(B_m) - \text{conf}(B_m)|$$
3. **Brier Score**:
   $$\text{Brier} = \frac{1}{N} \sum_{i=1}^{N} \sum_{k=1}^{K} (p_{ik} - y_{ik})^2$$

### 4. Calibration Methods Evaluated
1. `uncalibrated`: Raw softmax output from edge neural networks.
2. `temperature_scaling`: Single learned temperature parameter $T > 0$ optimizing Negative Log Likelihood: $\hat{p} = \sigma(z / T)$.
3. `isotonic_regression`: Non-parametric piecewise constant isotonic fitting on class probabilities.

### 5. Multi-Slice Stratification
- Per-class calibration (`NORMAL`, `ACCIDENT`, `FIRE`, `AMBULANCE`).
- Calibration by device (`camera-node-b`, `audio-node-b`, `sensors-node-b`).
- Calibration by corridor zone (`ZONE_A_INTERSECTION`, `ZONE_B_INTERSECTION`, `ZONE_C_CORRIDOR`).
- Calibration before drift vs after drift (using `drift_snapshots` historical timestamps).

### 6. Success & Failure Criteria (Locked Pre-Experiment)
- **Success Criteria**:
  1. Temperature scaling and isotonic regression reduce ECE by at least $\ge 25\%$ relative to uncalibrated predictions.
  2. Zero test-set leakage: calibrator weights fit only on calibration split.
  3. 100% compliance with OOD cap: max confidence on OOD inputs $\le 0.40$.
  4. Integration with Phase 6B: $\text{calibration\_quality} = 1.0 - \text{ECE}$ successfully modulates the risk formula.
- **Failure Criteria**:
  - If calibration increases Brier score or ECE on the held-out test split, hypothesis fails.
  - If any OOD input yields confidence $> 0.50$, safety guard fails.


---

## Experiment 6D-1: Sandboxed Incident Replay and Counterfactual Digital Twin

### 1. Pre-Registration Timestamp
- **Date**: 2026-10-06
- **Status**: PRE-REGISTERED (Criteria locked prior to evaluation runs)

### 2. Hypothesis
- **Hypothesis**: "Any past incident can be re-run bit-for-bit through the production fusion and decision pipeline with 100% determinism, and counterfactual runs (sensor dropout, delayed streams, network outage, conflicting sensor values, alternative operator actions) expose decision robustness without mutating live state."
- **Sandbox Invariant**: Replay execution runs in memory / isolated workspace and NEVER writes to live incident tables (`incidents`, `evidence_items`), never invokes real hardware actuators, never sounds buzzers, and never sends emergency dispatch notifications.
- **Unified Code Path Invariant**: Replay exercises the exact production pipeline modules:
  `raw evidence -> model predictions -> fusion -> OOD check -> risk score -> response plan -> operator action`.

### 3. Fault & Counterfactual Controls
1. `playback_speed`: Multiplier for virtual time steps ($0.5\times, 1.0\times, 2.0\times, 5.0\times$).
2. `dropout`: Sensor failure injection (`camera`, `audio`, `environmental`).
3. `delayed_audio`: Artificially introduce $N$ ms latency lag on acoustic stream.
4. `camera_failure`: Drop camera feed completely (black frame/0 FPS).
5. `network_outage`: Simulate offline node condition (isolated WAL outbox queue).
6. `conflicting_sensors`: Artificially invert or perturb one modality to contradict others.
7. `operator_action`: Inject alternative operator feedback (`ACKNOWLEDGE`, `FALSE_ALARM`, `OVERRIDE_PLAN`).

### 4. Mathematical Metrics & Mismatch Detection
1. **Replay Mismatch**: Binary divergence flag:
   $$\text{mismatch} = (\hat{y}_{\text{replay}} \neq y_{\text{original}}) \lor (|\text{risk}_{\text{replay}} - \text{risk}_{\text{original}}| > 10^{-4})$$
2. **Robustness Score**: Ratio of counterfactual runs maintaining safe and correct response plan despite single sensor faults.
3. **Timeline Completeness**: 100% coverage of timestamped step entries containing raw inputs, predictions, uncertainty factors, final risk, and recommended response plan.

### 5. Success & Failure Criteria (Locked Pre-Experiment)
- **Success Criteria**:
  1. $100\%$ determinism on unmodified replay: bit-exact match with original decision.
  2. Zero live-table writes verified via pre/post database row count assertions.
  3. Divergence cleanly detected and reported whenever an incident trace is tampered with or counterfactually altered.
  4. Full CLI (`python -m replay run --incident <id> ...`) and REST API `/api/replay/*` available.
- **Failure Criteria**:
  - Any mutation to live database tables or trigger of physical actuators during replay constitutes an immediate safety failure.
  - Non-deterministic outputs across identical seeds/replays fails the determinism invariant.


---

## Experiment 6E-1: Counterfactual Explanations and Decision Stability Verification

### 1. Pre-Registration Timestamp
- **Date**: 2026-10-06
- **Status**: PRE-REGISTERED (Criteria locked prior to evaluation runs)

### 2. Hypothesis
- **Hypothesis**: "Systematic counterfactual ablation of individual sensor modalities provides exact, high-fidelity explanations of edge decisions, exposing critical sensors and sensitivity bounds without mutating live state."
- **Explanation Fidelity Invariant**: Counterfactual explanations computed by the explanation engine must match bit-for-bit the exact outcomes produced by a true physical replay execution with that sensor removed:
  $$\text{Fidelity}(\text{Counterfactual}) = 100\% \quad \text{iff} \quad \text{outcome}_{\text{counterfactual}} \equiv \text{outcome}_{\text{replay\_ablation}}$$
- **Sensor Removal Monotonicity**: Removing any positive evidence stream can NEVER increase final risk:
  $$\text{risk}(\text{without\_sensor } s) \le \text{risk}(\text{with\_sensor } s) \quad \forall s \in \{\text{camera}, \text{audio}, \text{sensors}\}$$

### 3. Generated Explanations Structure
For each evaluated incident, generate:
1. `top_contributing_evidence`: Modality contributing greatest risk weight.
2. `pivot_sensor`: Which sensor's removal causes a state transition (e.g. `DISPATCH_ALERT` $\to$ `REVIEW_REQUIRED` or `NORMAL`).
3. `ablation_outcomes`: Explicit outcome map:
   - `with_all`: baseline status & risk.
   - `without_camera`: status & risk when camera dropped.
   - `without_audio`: status & risk when audio dropped.
   - `without_sensors`: status & risk when environmental sensors dropped.
4. `highest_impact_missing_sensor`: Sensor whose absence reduces confidence the most.
5. `suppression_reason`: Detailed forensic explanation if no emergency alert was triggered.

### 4. Success & Failure Criteria (Locked Pre-Experiment)
- **Success Criteria**:
  1. $100\%$ explanation fidelity: every counterfactual ablation outcome matches live `SandboxedReplayEngine` run.
  2. $100\%$ sensor-removal monotonicity: removing any evidence stream never increases risk.
  3. Execution latency on a standard 3-step incident trace is $\le 25$ ms (safe for Raspberry Pi 4 CPU budget).
  4. Explanations stored alongside incident metadata and surfaced in the dashboard.
- **Failure Criteria**:
  - Any instance where removing a sensor increases computed risk constitutes a safety invariant failure.
  - Explanation fidelity $< 100\%$ constitutes an unfaithful explanation failure.
