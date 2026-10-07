# Phase 6L: Zone-Aware Risk Scoring Experimental Results

**Hypothesis**: Zone-specific priors reduce false alarms in quiet zones and improve detection in high-risk zones versus a zone-agnostic baseline.

**Data Tag**: `SYNTHETIC` | **Confidence Intervals**: 95% Bootstrap (200 rounds)

| Zone | Type | Baseline FAR (95% CI) | Zone-Aware FAR (95% CI) | FAR Reduction | Baseline F1 (95% CI) | Zone-Aware F1 (95% CI) |
|---|---|---|---|---|---|---|
| **ZONE_A** | Quiet | 0.115 [0.057, 0.180] | 0.000 [0.000, 0.000] | **+100.0%** | 0.751 [0.711, 0.798] | 0.776 [0.725, 0.829] |
| **ZONE_B** | High-Risk | 0.147 [0.090, 0.213] | 0.000 [0.000, 0.000] | **+100.0%** | 0.736 [0.703, 0.773] | 0.758 [0.712, 0.806] |
| **ZONE_SCHOOL** | Quiet | 0.098 [0.049, 0.156] | 0.000 [0.000, 0.000] | **+100.0%** | 0.755 [0.716, 0.796] | 0.776 [0.725, 0.829] |
| **ZONE_HIGHWAY** | High-Risk | 0.098 [0.057, 0.156] | 0.000 [0.000, 0.000] | **+100.0%** | 0.755 [0.716, 0.797] | 0.772 [0.722, 0.825] |

### Safety Invariant Verification
- Critical Safety Floor: 100% of high-confidence events in quiet zones maintained dispatch priority or routed to `REVIEW_REQUIRED` (0% suppressed as noise).
- Ablatability: Reverting `use_zone_priors=False` reproduces the zone-agnostic baseline identically.
