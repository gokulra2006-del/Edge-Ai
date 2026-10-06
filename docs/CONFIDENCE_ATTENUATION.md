# Confidence Reduction on Sensor Failure

## 1. Research Overview
Edge intelligence systems operate directly with physical transducers (USB cameras, I2S microphones, GPIO motion detectors). When physical sensors malfunction—due to lens smudges, bus dropouts, cable detachment, or frame starvation—standard neural models often output spurious high confidence on corrupted noise or frozen frames.

This research establishes an **automatic confidence attenuation and risk-ceiling mechanism** that scales down model output weights proportionally to hardware sensor health.

---

## 2. Formal Research Specifications

### Hypothesis
Dynamically attenuating event confidence scores according to real-time sensor health coefficients (e.g. $1.0\times$ for healthy, $0.5\times$ for degraded, $0.0\times$ for disconnected) and enforcing hard risk ceilings ($\le 0.45$ under degraded conditions, $\le 0.20$ under sensor disconnection) guarantees zero critical false alarms caused by corrupted sensor hardware.

### Primary Metrics
1. **Critical False Alarm Suppression**: $0\%$ false emergency escalations occurring when the originating sensor is in `DEGRADED` or `DOWN` status.
2. **Confidence Attenuation Monotonicity**: Fused confidence monotonically decreases as packet drop rates and sensor degradation severity increase.
3. **Ceiling Invariance**: Even an artificial $0.99$ raw model confidence score cannot exceed the $0.45$ safety ceiling when the modality is degraded.

---

## 3. Evaluation Methodology

### Evaluation Scenarios
1. **Healthy Pass-Through**:
   - Asserts that when cameras and microphones report `HEALTHY` with $0\%$ frame drops, raw model confidence and risk scores pass through unimpeded ($1.0\times$ multiplier).

2. **Degraded Camera / Lens Obstruction**:
   - Injects a `DEGRADED` sensor state.
   - Evaluates whether raw confidence ($0.95$) is attenuated to $0.475$ and raw risk ($0.92$) is clipped to the safety ceiling ($\le 0.45$).

3. **Total Sensor Disconnection (`DOWN`)**:
   - Injects a `DOWN` sensor state.
   - Asserts that effective sensor weight collapses to $0.0\times$, resulting in zero confidence and total suppression of actuator alerts.

---

## 4. Implementation Reference
- Implementation: [`SensorConfidenceAttenuator`](file:///C:/Users/gokul/Desktop/PROJECTS/Edge-AI/src/modules/sensor_fusion/confidence_attenuation.py)
- Automated Tests: [`test_phase6_confidence_attenuation.py`](file:///C:/Users/gokul/Desktop/PROJECTS/Edge-AI/src/tests/test_phase6_confidence_attenuation.py)
