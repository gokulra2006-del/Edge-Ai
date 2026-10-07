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


---

## Experiment 6F-1: Automated Safety-Policy Verification and Invariant Assurance

### 1. Pre-Registration Timestamp
- **Date**: 2026-10-06
- **Status**: PRE-REGISTERED (Criteria locked prior to verification execution)

### 2. Hypothesis
- **Hypothesis**: "The platform's core safety invariants (role boundaries, model restriction gates, audit trails, immutability, critical deletion protection, and sensor monotonicity) hold deterministically across all runtime code paths."
- **Invariants Under Verification**:
  1. **Viewer Actuation Guard**: A Viewer cannot actuate hardware under any circumstances.
  2. **Operator Resolution Guard**: An Operator cannot resolve incidents (resolution is restricted to Commander).
  3. **Commander Audit Trail**: Every Commander action is unconditionally audit-logged with non-repudiation.
  4. **Manual Dispatch Gate**: External municipal emergency dispatch is never automated; it requires explicit human Commander escalation.
  5. **Model Registry Restriction Gate**: Models designated as `RESEARCH_ONLY` or `CANDIDATE` can never authorize physical actuation or live emergency alerts.
  6. **Closed Incident Immutability**: A closed incident cannot be modified (status, transitions, or outcomes are immutable).
  7. **Critical Retention Protection**: An unresolved critical incident cannot be deleted, including during automated storage retention cleanups.
  8. **Sensor Failure Confidence Monotonicity**: A failed, degraded, or dropped sensor can never increase event confidence or computed risk score.

### 3. Primary Metrics & Target Thresholds
- **Invariant Pass Rate**: $100\%$ (8 of 8 invariants strictly passing, 0 violations permitted).
- **State-Changing Route Coverage**: $100\%$ of all state-changing endpoints (`POST`, `PUT`, `DELETE`) in `app.py` protected by active permission matrix rules and CSRF validation.
- **Role $\times$ Action Matrix Rejection Rate**: $100\%$ of unauthorized role-action combinations rejected with HTTP 403 or `PermissionDenied`.

### 4. Success & Failure Criteria (Locked Pre-Experiment)
- **Success Criteria**:
  1. All 8 safety invariants verified via automated checker, role-matrix tests, and property tests.
  2. 100% of state-changing routes have explicit policy coverage.
  3. Declarative policy file (`src/config/safety_policies.json`) drives both runtime enforcement and offline validation.
  4. Model registry enforces `status` (`PRODUCTION`, `CANDIDATE`, `RESEARCH_ONLY`) at the actuation boundary.
  5. Policy checker runnable via module, CLI (`python -m src.modules.security.safety_policy_checker`), and CI test, outputting `docs/SAFETY_POLICY.md` and `results/safety_policy_verification.json`.
  6. Any invariant violation immediately fails the build with non-zero exit code.
- **Failure Criteria**:
  - Any bypassed permission, untracked commander action, automated external dispatch, actuation from a non-production model, modification of a closed incident, deletion of an unresolved incident, or confidence increase on sensor failure constitutes an immediate build-breaking invariant failure.

### 5. Honest Scope Disclaimer
- Automated verification demonstrates invariant satisfaction across covered execution paths, mock scenarios, and property-based sweeps; it does not constitute a formal mathematical proof (e.g. TLA+ or Coq).


---

## Experiment 6G-1: Governed Human-Feedback Loop and Active-Learning Review Selection

### 1. Pre-Registration Timestamp
- **Date**: 2026-10-06
- **Status**: PRE-REGISTERED (Criteria locked prior to evaluation runs)

### 2. Hypothesis
- **Hypothesis**: "Uncertainty-based active-learning review selection (combining least-confidence, classification margin, and OOD signals) improves candidate model macro-F1 faster per labeled sample than uniform random selection, while immutable dataset versioning and gated proposal approvals guarantee 0% test-set leakage and zero unapproved model deployments."

### 3. Primary Metrics & Target Thresholds
- **Sample Efficiency Ratio**:
  $$\text{Gain}_{\text{sample}} = \frac{\Delta \text{Macro-F1}_{\text{Active}}}{\Delta \text{Macro-F1}_{\text{Random}}} > 1.0$$
- **Inter-Operator Agreement ($P_o$)**: Exact agreement percentage between multiple independent operator labels on identical predictions, with automated conflict escalation when $P_o < 1.0$.
- **Test-Set Leakage**: Strictly $0.0\%$ (zero overlap between training/feedback dataset snapshots and the frozen evaluation split).
- **Snapshot Immutability**: $100\%$ tamper-detection rate via SHA-256 digest verification.
- **Autonomous Deployment Prohibition**: $100\%$ rejection of automated model actuation or promotion; only audit-logged `COMMANDER` or `ENGINEER` approvals transition candidate models.

### 4. Success & Failure Criteria (Locked Pre-Experiment)
- **Success Criteria**:
  1. Active learning selection prioritizes uncertain, low-margin, and OOD samples, outperforming uniform random selection in macro-F1 gain per labeled batch.
  2. Label quality tracking computes operator reliability and flags conflicting labels for commander adjudication.
  3. Dataset snapshots are cryptographically hashed and versioned with full provenance.
  4. Retraining proposals document before/after metrics on a frozen test split (per-zone, per-class, and macro-F1).
  5. Retraining approval workflow enforces role boundaries (Engineer/Commander only), logs audit entries, and places approved models in registry strictly as `CANDIDATE`.
- **Failure Criteria**:
  - Any overlap between dataset snapshot and frozen test split constitutes a test-leakage failure.
  - Any automated deployment without human approval violates research invariants.
  - Inability to detect dataset snapshot tampering.


---

## Experiment 6H-1: Environmental Robustness and Subgroup Fairness Evaluation

### 1. Pre-Registration Timestamp
- **Date**: 2026-10-06
- **Status**: PRE-REGISTERED (Criteria locked prior to evaluation runs)

### 2. Hypothesis
- **Hypothesis**: "Edge AI incident detection performance diverges significantly across environmental and operational conditions (time of day, weather, camera angle, traffic density, microphone placement, road surface, acoustic zone, and hardware node). A synthetic-only nominal baseline masks severe operational degradation, whereas stratified condition reporting with honest sample accounting and provenance tagging exposes critical safety vulnerabilities and subgroup fairness gaps."

### 3. Evaluated Condition Dimensions & Subgroups
Evaluation is stratified across 8 operational axes:
1. **Time of Day**: `day`, `night`
2. **Weather**: `clear`, `rain`, `fog`
3. **Camera Angle**: `overhead`, `street_level`, `oblique`
4. **Traffic Density**: `low`, `medium`, `high`
5. **Microphone Placement**: `pole_mounted`, `curbside`, `enclosed`
6. **Road Surface**: `asphalt`, `wet_concrete`, `gravel`
7. **Acoustic Zone**: `quiet_suburb`, `noisy_intersection`, `commercial`
8. **Hardware Node**: `rpi4_node1`, `jetson_node2`, `edge_server`

### 4. Metrics & Evaluation Protocol
For each condition subgroup:
1. **Sample Count ($N$)**: Total evaluated steps/scenarios.
2. **Sample Adequacy Gate**: If $N < N_{\min}$ (default $N_{\min} = 10$), flag status as `INSUFFICIENT_DATA` rather than reporting misleading, high-variance point estimates.
3. **Performance Metrics**:
   - **Macro-F1** with non-parametric Bootstrap 95% Confidence Interval.
   - **False-Alarm Rate (FAR %)**: $\frac{\text{False Alarms}}{\text{True Normals}} \times 100\%$ with Bootstrap 95% CI.
   - **Miss Rate (FNR %)**: $\frac{\text{Missed Emergencies}}{\text{Total Emergencies}} \times 100\%$ with Bootstrap 95% CI.
   - **Expected Calibration Error (ECE)** and **Brier Score**.
4. **Subgroup Disparity & Fairness Gap**:
   $$\Delta_{\text{Macro-F1}} = \max_{c} \text{F1}(c) - \min_{c} \text{F1}(c)$$
   $$\Delta_{\text{FAR}} = \max_{c} \text{FAR}(c) - \min_{c} \text{FAR}(c)$$
   $$\Delta_{\text{Miss}} = \max_{c} \text{Miss}(c) - \min_{c} \text{Miss}(c)$$
5. **Honest Data Provenance & Real-Data Disclosure**:
   - Every result tagged explicitly: `SYNTHETIC`, `REPLAYED_REAL`, or `REAL_HARDWARE`.
   - Clear disclosure of which conditions have real physical data vs synthetic/simulated perturbations.

### 5. Success & Failure Criteria (Locked Pre-Experiment)
- **Success Criteria**:
  1. Condition metadata is integrated directly into scenario formats and database evidence records.
  2. Per-condition evaluation produces Macro-F1, FAR, Miss Rate, ECE, Brier score, sample counts, and bootstrap 95% CIs.
  3. Any condition with $N < N_{\min}$ is strictly flagged as `INSUFFICIENT_DATA` without reporting false point estimates.
  4. Worst-performing conditions and performance gaps ($\Delta$) are automatically identified and highlighted across all 8 dimensions.
  5. 100% of reported results carry honest provenance tags (`SYNTHETIC`, `REPLAYED_REAL`, `REAL_HARDWARE`).
  6. Exportable publication-grade HTML report (`reports/robustness_report.html`) and CSV (`results/robustness_evaluation.csv`) are generated.
  7. CLI command enables single-command reproduction of the full evaluation suite.
- **Failure Criteria**:
  - Failure to flag low-sample subgroups ($N < N_{\min}$) as `INSUFFICIENT_DATA`.
  - Presenting synthetic perturbations as real hardware data.
  - Missing any of the 8 required condition dimensions.
  - Failure to compute bootstrap confidence intervals or calibration metrics.


---

## Experiment 6I-1: Physical Edge Deployment Validation on Raspberry Pi 4

### 1. Pre-Registration Timestamp
- **Date**: 2026-10-06
- **Status**: PRE-REGISTERED (Criteria locked prior to physical hardware execution)

### 2. Hypothesis
- **Hypothesis**: "Physical edge hardware deployment introduces sustained thermal throttling, MicroSD fsync bottlenecks, sensor bus contention, and power/network disruptions that synthetic simulations underestimate. A robust edge architecture maintains sub-second recovery and 0% audit loss under physical disruption, while reporting authentic physical telemetry without fabrication."

### 3. Primary Metrics & Target Thresholds
1. **Sustained Compute & Memory**:
   - Sustained CPU utilization (%) under active vision, audio, and environmental sensor fusion.
   - Process RSS memory consumption $\le 120$ MB.
2. **Thermal & Throttling Diagnostics**:
   - SoC Core Temperature ($^\circ\text{C}$) via `/sys/class/thermal/thermal_zone0/temp`.
   - `vcgencmd get_throttled` bitmask: detects under-voltage ($0\text{x}1$), frequency capping ($0\text{x}2$), and thermal throttling ($0\text{x}4$).
3. **Camera Ingestion Throughput**:
   - Camera FPS $\ge 12.0$ FPS under full inference pipeline.
   - Frame drop rate $\le 2.0\%$.
4. **Audio Latency & Buffer Stability**:
   - Audio window processing latency $\le 80$ ms.
   - Dropped window count $= 0$ under nominal load.
5. **Bus Contention (I2C/SPI)**:
   - Transaction round-trip time $\le 25$ ms.
   - Bus transaction error rate $\le 0.1\%$.
6. **MicroSD Storage Latency**:
   - SQLite WAL append and `fsync` write latency: median $\le 15$ ms, p95 $\le 65$ ms.
7. **Network Outage Recovery**:
   - Seamless offline buffer transition: 100% of generated events persisted to local SQLite outbox during physical network cut.
   - Recovery flush time $\le 5.0$ seconds upon physical reconnection.
8. **Power-Interruption Recovery**:
   - SQLite database integrity check: `PRAGMA integrity_check` returns strictly `"ok"`.
   - 0% lost audit records: all pre-cut committed `operator_actions` and incidents retain bit-exact cryptographic consistency.

### 4. Honest Data & Anti-Fabrication Invariants
- **Zero Fabrication Rule**: The software system and assistant must NEVER synthesize, mock, or fake physical Raspberry Pi measurements.
- **Tagging Invariant**: Every benchmark generated on physical hardware is authenticated and tagged `REAL_HARDWARE`.
- **Missing Measurement Invariant**: Any metric that has not been executed on physical hardware must be explicitly labeled as `NOT_MEASURED` in all paper tables and reports.
- **Tamper-Resistant Importer**: Importer validates hardware provenance, cryptographic script fingerprint, and rejects unauthorized or synthetic files attempting to claim real hardware origin.

### 5. Success & Failure Criteria (Locked Pre-Experiment)
- **Success Criteria**:
  1. Complete standalone validation tooling under `scripts/pi/` recording hardware model, OS, git hash, duration, and parameters.
  2. Physical testing guide (`docs/hardware/PI_VALIDATION_GUIDE.md`) detailing physical test protocol (unplugging network, abrupt power cuts).
  3. Result importer (`scripts/pi/import_results.py`) safely merges authenticated outputs into `results/` tagged `REAL_HARDWARE` and rejects invalid inputs.
  4. Publication report generator produces paper-ready tables where unmeasured fields render strictly as `NOT_MEASURED`.
  5. Power interruption recovery asserts `PRAGMA integrity_check == ok` and 0 audit log deletions.
- **Failure Criteria**:
  - Any fabricated or guessed performance numbers.
  - Importer accepting synthetic data as real hardware.
  - Missing any of the required physical validation vectors.
  - Database corruption or audit loss following power recovery test.

---

## Experiment 6J-1: Privacy-Preserving Multi-Node Federated Learning under Non-IID Zone Drift

### 1. Pre-Registration Timestamp
- **Date**: 2026-10-06
- **Status**: PRE-REGISTERED (Criteria locked prior to code execution)

### 2. Hypothesis
- **Hypothesis**: "Federated updates across zone-specific edge nodes improve non-IID cross-zone detection performance without uploading raw audio, video, or incident payloads. A simulation-first federated architecture with cryptographic update signatures, robust aggregation, and differential privacy clipping delivers generalized detection across heterogeneous zones while strictly preserving the edge privacy boundary."

### 3. Primary Metrics & Target Thresholds
1. **Cross-Zone Generalization (Non-IID Evaluation)**:
   - Evaluated on partitioned, heterogeneous urban emergency distributions (Zone A: traffic accident skewed; Zone B: fire/hazard skewed; Zone C: violence/panic skewed).
   - Federated global model Macro-F1 across all zones exceeds isolated local-only models on out-of-zone test distributions by $\ge 15.0\%$ relative improvement.
   - Federated global model performance remains within $5.0\%$ Macro-F1 of a hypothetical (privacy-violating) centralized pooled baseline.
2. **Confidence Calibration**:
   - Global federated model Expected Calibration Error (ECE) $\le 0.150$ across non-IID test splits.
3. **Privacy Boundary Invariant**:
   - Zero raw audio waveforms, video frames, or incident metadata are included in node upload payloads ($0\text{ bytes}$ raw payload).
   - Enforced by strict boundary assertion tests.
4. **Communication Overhead**:
   - Measured and reported in exact bytes per training round (client-to-server parameter upload + server-to-client global broadcast).
5. **Robustness & Tamper Rejection**:
   - 100% rejection rate for unsigned, forged, or payload-tampered model updates.
   - Robust aggregation (Coordinate Trimmed-Mean / Median) maintains stable convergence in the presence of Byzantine or adversarial gradient updates compared to standard FedAvg.
6. **Differential Privacy (DP) Budget**:
   - Configurable gradient/delta clipping bound $C$ and calibrated noise multiplier $\sigma$, recording effective privacy parameters $(\epsilon, \delta)$.
7. **Governance & Model Registry Gate**:
   - Aggregated federated models enter the model registry strictly as `CANDIDATE`.
   - Cannot actuate hardware or dispatch emergency responders without explicit human Commander/Engineer approval via the Phase 6G proposal workflow.

### 4. Data Tagging & Honest Limitations
- **Tagging**: Tagged strictly as `SYNTHETIC` (simulated multi-node environment on a single testbed).
- **Honest Limitations**: While network bandwidth, serialization sizes, and multi-node gradient exchanges are faithfully measured, this simulation does not capture real-world wide-area network (WAN) packet loss, physical edge node compute throttling, or high-latency cellular connectivity.

### 5. Success & Failure Criteria (Locked Pre-Experiment)
- **Success Criteria**:
  1. Simulation engine successfully trains $N \ge 3$ nodes across non-IID zone partitions.
  2. Federated model beats local-only models on cross-zone evaluation.
  3. Privacy boundary test guarantees zero raw media leaves any node.
  4. Cryptographic signature check rejects tampered node weights.
  5. Aggregated model enters registry strictly as `CANDIDATE`.
- **Failure Criteria**:
  - Raw media found in node upload payloads.
  - Aggregator accepts unsigned or tampered updates.
  - Aggregated model automatically enters registry as `PRODUCTION`.
  - Non-deterministic runs under identical random seeds.

---

## Experiment 6K-1: Authenticated Evidence Encryption at Rest with Key Rotation and Tamper Detection

### 1. Pre-Registration Timestamp
- **Date**: 2026-10-07
- **Status**: PRE-REGISTERED (Criteria locked prior to code execution)

### 2. Hypothesis
- **Hypothesis**: "Authenticated encryption at rest (AES-256-GCM) protects forensic evidence files from unauthorized extraction and storage-level bit-rot or malicious modification without breaking the cryptographic chain of custody (plaintext SHA-256 matching stored incident manifests), while providing seamless key rotation, transparent retention pruning, and comprehensive audit accountability for every access or authorization failure."

### 3. Primary Metrics & Target Thresholds
1. **Tamper Detection Rate**:
   - 100% of single-bit modifications in ciphertext, nonce, or tag fail AES-GCM authentication (`InvalidTag`) and abort plaintext release.
2. **Chain of Custody Invariance**:
   - Plaintext SHA-256 hash computed pre-encryption strictly matches post-decryption digest across all keys, migrations, and rotations.
3. **Key Rotation Continuity**:
   - Multi-key KeyRing decrypts historic evidence encrypted under retired key IDs and transparently re-encrypts to the active key with 0 data loss.
4. **Access Governance & Audit Accountability**:
   - Decryption authorized strictly for permitted operational roles (`COMMANDER`, `OPERATOR`, `ENGINEER`).
   - 100% of decryption events and 100% of denied authorization actions (`role x forbidden-action`) produce tamper-evident audit records in `operator_actions`.
5. **Storage & Retention Compatibility**:
   - Phase 5D storage retention manager prunes and archives encrypted evidence files safely based on file age and policy rules without requiring plaintext decryption.

### 4. Data Tagging & Honest Limitations
- **Tagging**: Tagged `SYNTHETIC` for generated incident test evidence.
- **Honest Limitations**: AES-256-GCM protects evidence confidentiality and integrity at rest on the local file system. It relies on the security of the host environment variable or external key file path (`EVIDENCE_ENCRYPTION_KEY`). Key storage in hardware HSMs / TPMs remains a physical deployment consideration.

### 5. Success & Failure Criteria (Locked Pre-Experiment)
- **Success Criteria**:
  1. Authenticated encryption module (`AES-256-GCM`) with envelope format containing magic header, key ID, nonce, and ciphertext tag.
  2. External key resolution via environment variable or external key file.
  3. Key rotation mechanism supporting multiple active and historic keys.
  4. Migration command encrypting existing unencrypted evidence files while preserving database SHA-256 hashes.
  5. Automated tamper test confirming 100% tamper detection.
  6. Automated wrong-key test confirming authentication failure.
  7. Audit logging of every decryption attempt and every denied role action.
  8. Retention manager (5D) and Merkle evidence packaging (5C) updated for encrypted files.
- **Failure Criteria**:
---

## Experiment 6L-1: Zone-Aware Risk Scoring with Contextual Priors and Critical Safety Floor

### 1. Pre-Registration Timestamp
- **Date**: 2026-10-07
- **Status**: PRE-REGISTERED (Criteria locked prior to code execution)

### 2. Hypothesis
- **Hypothesis**: "Zone-specific priors (accident base rate, time of day, noise level, traffic density) reduce false alarms in quiet zones and improve detection in high-risk zones versus a zone-agnostic baseline."

### 3. Safety Invariants & Guardrails
1. **Critical Safety Floor**:
   - Priors may adjust alert priority/thresholds but **can never suppress a high-confidence critical event**.
   - If an event is evaluated with high confidence (e.g. `raw_confidence >= 0.85` or severe physical signature like `CRITICAL` / `FIRE` / `ACCIDENT`), a low zone prior CANNOT downgrade it to `NORMAL` or dismiss it; it must route to `REVIEW_REQUIRED` or maintain alerting priority.
2. **Leakage-Free Estimation**:
   - Zone-specific and time-bucket priors are estimated strictly from training/historical data partitions with frozen snapshots; zero test-set leakage.
3. **Auditability & Ablation**:
   - The zone factor (prior adjustment delta, base rate, bucket) is explicitly logged in the prediction payload with every decision.
   - The zone prior is fully ablatable (`use_zone_priors=False` reverts identically to the zone-agnostic baseline).

### 4. Primary Metrics & Target Thresholds
1. **False-Alarm Reduction in Quiet Zones**:
   - False-alarm rate (FAR) in low-risk/quiet zones drops by $\ge 15\%$ relative to zone-agnostic baseline without reducing critical recall.
2. **Recall in High-Risk Zones**:
   - Detection sensitivity / macro-F1 in high-risk zones improves or remains $\ge 0.90$.
3. **Safety Invariant Enforcement**:
   - 100% of high-confidence critical events in low-risk zones remain detected or routed to `REVIEW_REQUIRED` (0% suppressed).
4. **Statistical Rigor**:
   - Evaluated across zones using the Phase 6A evaluation framework with 95% bootstrap confidence intervals and explicit data tagging (`SYNTHETIC` / `REPLAYED_REAL`).

### 5. Success & Failure Criteria (Locked Pre-Experiment)
- **Success Criteria**:
  1. Versioned, leakage-free prior tables estimated across zones and time buckets.
  2. Integration into uncertainty/decision pipeline with ablatable configuration flag.
  3. Safety policy floor strictly enforced (verified by property-based and regression tests).
  4. Decision logging includes `zone_prior`, `adjusted_risk`, `baseline_risk`, and rationale.
  5. Per-zone comparative evaluation report generated with confidence intervals and honest limitations.
- **Failure Criteria**:
  - A high-confidence critical event is suppressed or demoted to `NORMAL` due to low prior.
  - Evaluation test data is used to calculate priors (data leakage).
  - Suppression of real anomalies in quiet zones.

---

## Experiment 6N-1: Governed Autonomous Response with Visible Safety Contract

### 1. Pre-Registration Timestamp
- **Date**: 2026-10-07
- **Status**: PRE-REGISTERED (Criteria locked prior to code execution)

### 2. Hypothesis
- **Hypothesis**: "Showing evidence, uncertainty, and approval requirements for each proposed action reduces unauthorized or unreviewed actions without delaying authorized ones."
- **Core Mechanism**:
  1. **AI Proposes Only**: The AI decision system only produces `PROPOSED` actions within an explicit response plan. Physical execution and emergency dispatches unconditionally require human approval by an authorized role.
  2. **Visible Safety Contract**: Every decision record binds an immutable safety contract containing:
     - What the AI detected (event class, confidence, timestamp, zone).
     - Which evidence supports it (multi-sensor modalities, sensor readings, and key evidence items).
     - What uncertainty remains (6B multi-factor risk components: temporal consistency, sensor agreement, health, calibration, penalties).
     - What action is proposed (e.g. traffic signal preemption, dispatch request, evacuation advisory).
     - Which human role must approve it (`OPERATOR` for tactical actions, `COMMANDER` for dispatch/escalation/resolution).
     - Why an action was blocked if blocked (policy rule ID from Phase 6F, e.g. `INV-04-NO-AUTOMATIC-DISPATCH`, `INV-05-RESEARCH-MODEL-BOUNDARY`, `INV-01-VIEWER-NO-ACTUATION`).
  3. **Model Tier Invariance**: `RESEARCH_ONLY` models are architecturally prohibited from proposing physical actuation or emergency dispatch (`INV-05`).

### 3. Primary Metrics & Target Thresholds
1. **Unauthorized / Unreviewed Action Rate**:
   - Zero unauthorized or unreviewed actuations/dispatches executed ($0.0\%$, verified across 100% of execution paths).
2. **Approval Latency / Completion Time Accounting**:
   - Response-plan completion time (duration from plan proposal timestamp to final status: `APPROVED`, `BLOCKED`, `EXECUTED`, or `EXPIRED`) is measured and recorded per plan.
   - P95 response plan resolution time remains $\le 5.0$ seconds in automated triage simulation.
3. **Contract Completeness & Congruence**:
   - 100% of generated decision records contain a congruent, non-null safety contract matching stored telemetry and predictions.
4. **Audit Trail Accountability**:
   - 100% of authorization failures and blocked actions produce immutable records in the `operator_actions` audit ledger.

### 4. Success & Failure Criteria (Locked Pre-Experiment)
- **Success Criteria**:
  1. Response-plan object per incident tracking proposed actions with required approver role, status (`PROPOSED`, `APPROVED`, `BLOCKED`, `EXECUTED`, `EXPIRED`), timestamps, and actor ID.
  2. Stored safety contract with AI detection, evidence list, 6B uncertainty factors, proposed action, required approver role, and block reason ID.
  3. Strict enforcement: AI only proposes; external dispatch and physical actuation cannot execute without human approval.
  4. Blocked actions and authorization rejections logged to audit ledger with corresponding 6F invariant rule IDs.
  5. Response-plan completion duration tracked per plan.
  6. Safety contract included in forensic reports (5C/10) and sandboxed replay output (6D).
  7. Offline compatibility (zero CDN) and role permission matrix enforcement.
- **Failure Criteria**:
  - Any physical actuation or external dispatch executes without explicit human approval.
  - A `RESEARCH_ONLY` model successfully proposes physical actuation.
  - An action is blocked without recording a policy rule ID from 6F.
  - Incongruence between stored evidence/risk factors and the displayed safety contract.

---

## Experiment 6O-1: Sensor-Availability Matrix and Threshold Controls

### 1. Pre-Registration Timestamp
- **Date**: 2026-10-07
- **Status**: PRE-REGISTERED (Criteria locked prior to code execution)

### 2. Hypothesis
- **Hypothesis**: "Showing how each incident's outcome changes when each sensor is removed, or when sensors conflict, lets operators judge decision robustness; evaluated by decision stability and agreement with real replays."
- **Core Mechanisms**:
  1. **Systematic Modality Ablation Matrix**: For every incident, systematic sensor removal (single sensors: camera, audio, IMU, environmental; and sensor-pair combinations: camera+audio, camera+IMU, audio+IMU; plus conflict condition) is evaluated via the unified 6D replay engine and 6B uncertainty fusion.
  2. **Explicit Conflict Resolution**: When active modalities disagree beyond a configured margin ($\Delta_{\text{conf}} \le \text{margin}$ with opposing non-normal classes), the outcome is routed to `HUMAN_REVIEW`, strictly prohibiting silent resolution or arbitrary modal tie-breaking.
  3. **Hypothetical Replay Controls**: Operators can explore alternative confidence thresholds (e.g. 0.30 - 0.90) and alternative decisions (e.g. override, acknowledge, false alarm), with all output explicitly tagged as `is_hypothetical=True`.
  4. **Monotonic Risk Invariant**: Removing a sensor can never raise risk ($Risk_{\text{ablation}} \le Risk_{\text{baseline}}$); the matrix outcome must equal what a real replay with that sensor removed produces bit-for-bit.
  5. **Edge Budget & Lazy Caching**: On Raspberry Pi 4 hardware, matrix computation is evaluated lazily on request or cached in the background, never blocking the critical millisecond alert path.

### 3. Primary Metrics & Target Thresholds
1. **Monotonic Risk Invariant Rate**:
   - $100\%$ of sensor removal evaluations satisfy $Risk_{\text{ablation}} \le Risk_{\text{baseline}} + \epsilon$ ($\epsilon = 0.0001$).
2. **Replay Engine Congruence**:
   - $100\%$ bit-exact agreement between the matrix outcomes and independent direct 6D sandboxed replay execution.
3. **Explicit Conflict Gating**:
   - $100\%$ of conflicting modality injection scenarios result in `HUMAN_REVIEW` (0.0% silent picks).
4. **Decision Stability Score**:
   - Metric measuring the fraction of single-sensor ablations that maintain the baseline event classification or gracefully transition to human review rather than flipping to an erroneous contradictory emergency. Baseline target $\ge 0.85$.
5. **Execution Latency Budget**:
   - Real-time alert path latency overhead: $0.0\text{ms}$ (lazily computed or background cached).
   - Lazy generation latency: $\le 50\text{ms}$ for full 9-condition matrix on edge CPU.

### 4. Success & Failure Criteria (Locked Pre-Experiment)
- **Success Criteria**:
  1. Availability matrix computed per incident covering all individual sensors and sensor pairs.
  2. Outcome levels accurately mapped (`CRITICAL`, `HIGH`, `REVIEW_REQUIRED`, `LOW_CONFIDENCE`, `HUMAN_REVIEW`).
  3. Invariant: removing a sensor never raises risk.
  4. Invariant: matrix outcome equals real replay output bit-for-bit.
  5. Explicit conflict detection routing to `HUMAN_REVIEW` when modalities disagree within margin.
  6. Hypothetical controls for alternative thresholds and operator decisions.
  7. Displayed on incident page and forensic reports with zero external CDN dependencies.
  8. Decision stability metric integrated into Phase 6A evaluation framework.
- **Failure Criteria**:
  - Removing a sensor inflates risk above baseline.
  - A multimodal conflict is silently resolved without `HUMAN_REVIEW`.
  - Matrix calculation blocks or delays live real-time incident detection.
  - Incongruence between availability matrix and direct 6D replay.

---

## Experiment 6P-1: Drift-to-Review Closed Loop and Active-Learning Recovery Evaluation

### 1. Pre-Registration Timestamp
- **Date**: 2026-10-07
- **Status**: PRE-REGISTERED (Criteria locked prior to evaluation runs)

### 2. Hypothesis
- **Hypothesis**: "When drift is detected, selecting the most uncertain recent samples for operator labeling and producing a candidate model recovers performance faster per labeled sample than random selection; the human decides whether to deploy."
- **Core Workflow**:
  $$\text{Drift Detected} \xrightarrow{\text{Active Selection}} \text{Batch Selected} \xrightarrow{\text{Flooding Capped}} \text{Review Tasks} \xrightarrow{\text{Operator Labeling}} \text{Dataset Snapshot} \xrightarrow{\text{Offline Eval}} \text{Candidate Model} \xrightarrow{\text{Human Gate}} \text{Approve / Reject}$$
- **Key Constraints**:
  1. **Automated Batch Ingestion with Flooding Guard**: A drift snapshot indicating drift (`status != NOMINAL` or $\text{PSI} > 0.25$) automatically forms a review batch prioritized by Phase 6G active learning scores (least-confidence, margin, OOD), capped at `max_batch_size` (default 25) so human operators are never flooded.
  2. **Audited State Progression**: Every stage records immutable state, UTC timestamps, actor IDs and roles, dataset SHA-256 version hash, candidate model version, and before/after metrics on a frozen evaluation test set.
  3. **Strict Non-Autonomous Deployment Guarantee**: Candidate evaluation runs offline and is manually triggered or scheduled by an engineer. The system NEVER replaces or deploys the live production model automatically.
  4. **Strict Role-Gated Decision**: Approving or rejecting candidate models is strictly restricted to `ENGINEER` or `COMMANDER` roles, audit-logged with a mandatory rationale.
  5. **Rejected Candidate Retention**: Rejected candidate models and proposals are never purged; they remain permanently in the audit log for safety retrospectives.

### 3. Primary Metrics & Target Thresholds
1. **F1 Recovery Rate per Labeled Sample**:
   $$\text{Recovery Efficiency} = \frac{\Delta \text{Macro-F1}_{\text{Active}}}{\Delta \text{Macro-F1}_{\text{Random}}} > 1.20$$
   Measured across incremental labeled sample budgets with 95% bootstrap confidence intervals.
2. **Audit Trail Completeness**:
   - $100\%$ of lifecycle stages contain valid timestamps, actor identity, role attribution, dataset hash, and evaluation deltas.
3. **Flooding Guard Compliance**:
   - $100\%$ of created review batches satisfy $|\text{Batch}| \le \text{max\_batch\_size}$ regardless of total drifted sample volume.
4. **Autonomous Deployment Prohibition**:
   - $0.0\%$ automated production deployments (strictly $100\%$ gated behind human `ENGINEER` or `COMMANDER` approval).
5. **Test-Set Non-Leakage**:
   - $0.0\%$ sample overlap between review dataset snapshots and frozen evaluation test splits.
6. **Data Provenance Tag**:
   - All evaluation results tagged with explicit provenance (`SYNTHETIC` for synthetic drift simulation).

### 4. Success & Failure Criteria (Locked Pre-Experiment)
- **Success Criteria**:
  1. Complete closed loop connected: drift detection $\rightarrow$ uncertainty selection $\rightarrow$ review tasks $\rightarrow$ operator labeling $\rightarrow$ versioned dataset $\rightarrow$ offline candidate evaluation $\rightarrow$ human approve/reject.
  2. Active learning selection yields higher Macro-F1 recovery per sample than random selection with non-overlapping 95% confidence intervals at sample sizes $N \in [10, 50]$.
  3. Review batches strictly respect configured size limits preventing operator flooding.
  4. All stages audit-logged with cryptographically hashed dataset versions and before/after evaluation deltas.
  5. Role permissions strictly prevent `OPERATOR` or `VIEWER` roles from approving/rejecting candidate models.
  6. Rejected candidates are retained in audit records and dashboard history.
- **Failure Criteria**:
  - Live model replaced automatically without human approval.
  - Review queue flooded beyond configured batch size limits.
  - Test set leakage between candidate training and evaluation splits.
  - Incomplete audit trail missing actor, timestamps, or dataset version hash.







