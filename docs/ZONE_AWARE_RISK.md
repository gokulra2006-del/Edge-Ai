# Zone-Aware Risk Scoring

## 1. Research Overview
Uniform thresholding across diverse physical environments is a leading cause of alarm fatigue in industrial security. A detection of loud acoustic noise or fast vehicle motion in an industrial storage yard rarely warrants emergency escalation, whereas the exact same signal occurring in an active school crossing or hospital driveway represents an immediate life-safety hazard.

This research formulates an **adaptive zone-aware risk engine** that dynamically weights raw detection confidence with spatial vulnerability tiers and real-time pedestrian/vehicle crowding density.

---

## 2. Formal Research Specifications

### Hypothesis
Modulating raw event confidence with dynamic spatial criticality profiles (e.g. $1.40\times$ for school crossings vs. $0.75\times$ for industrial yards) and positive crowd-density scaling ($+0.01$ to $+0.05$ per person) achieves statistically superior hazard separation, suppressing false alert rates in low-hazard zones by $>35\%$ while amplifying sensitivity in high-risk public corridors.

### Primary Metrics
1. **Hazard Separation Ratio**: Significant risk score separation ($> 0.35$ difference) between identical sensory inputs in sensitive vs. industrial zones.
2. **Crowd-Density Monotonicity**: Risk score strictly monotonically increases as local pedestrian count rises, subject to an upper risk ceiling ($\le 1.0$).
3. **Transparent Factor Attribution**: Clear diagnostic reporting detailing base multiplier and crowding factor boosts.

---

## 3. Evaluation Methodology

### Evaluation Scenarios
1. **Cross-Zone Risk Discrimination**:
   - Assesses identical high-severity events ($0.80$ confidence) occurring in `ZONE_SCHOOL` vs `ZONE_INDUSTRIAL`.
   - Confirms that the school event is escalated to $> 0.90$ calibrated risk while the industrial event is de-escalated to $< 0.55$.

2. **Density Escalation Benchmark**:
   - Ingests events in `ZONE_COMMERCIAL` with 0, 5, and 20 detected persons.
   - Evaluates whether risk score increases monotonically with crowd density and logs appropriate reason codes.

---

## 4. Implementation Reference
- Implementation: [`ZoneAwareRiskEngine`](file:///C:/Users/gokul/Desktop/PROJECTS/Edge-AI/src/modules/decision_engine/zone_risk.py)
- Automated Tests: [`test_phase6_zone_risk.py`](file:///C:/Users/gokul/Desktop/PROJECTS/Edge-AI/src/tests/test_phase6_zone_risk.py)
