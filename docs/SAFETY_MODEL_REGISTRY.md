# Safety-Aware Model Registry with RESEARCH_ONLY Restrictions

## 1. Research Overview
Rapid iteration in edge machine learning requires testing experimental network architectures, uncalibrated quantizations, and novel multi-task heads in realistic physical environments. However, deploying experimental models directly onto physical safety nodes creates intolerable risks of accidental strobe triggers, audible sirens, or false municipal emergency dispatches.

This research introduces an architectural **safety execution gate** in the model registry that isolates experimental models designated as `RESEARCH_ONLY` to shadow-only evaluation, strictly preventing physical actuator actuation.

---

## 2. Formal Research Specifications

### Hypothesis
Enforcing explicit `usage_restriction` validation (`PRODUCTION` vs `RESEARCH_ONLY`) at the decision engine runtime boundary guarantees $100\%$ prevention of unauthorized physical actuator triggers or live incident dispatches from experimental models, while allowing non-intrusive shadow telemetry collection.

### Primary Metrics
1. **Actuator Breach Prevention Rate**: Zero ($0$) physical actuator signals or emergency incident records initiated by models tagged `RESEARCH_ONLY`.
2. **Shadow Telemetry Permissibility**: Models with `RESEARCH_ONLY` restriction successfully output inference predictions flagged as `is_shadow_only = True`.
3. **Rejection Determinism**: Deterministic emission of `POLICY_RESTRICTION` violation flags when an unauthorized model attempts to trigger physical state changes.

---

## 3. Evaluation Methodology

### Evaluation Scenarios
1. **Production Pipeline Validation**:
   - Asserts that models tagged `PRODUCTION` and `ACTIVE` pass safety screening and are authorized to trigger hardware actuators and dispatches.

2. **Research Model Isolation Benchmark**:
   - Ingests high-confidence ($0.99$) detections from an experimental architecture (`exp_transformer_edge`) marked `RESEARCH_ONLY`.
   - Confirms that both actuator triggering and live incident dispatch are blocked, and `is_shadow_only` is asserted.

3. **Unregistered Model Defense**:
   - Submits predictions from an unknown model ID.
   - Evaluates whether the system blocks execution with `UNREGISTERED_MODEL` violation.

---

## 4. Implementation Reference
- Implementation: [`SafetyAwareModelRegistry`](file:///C:/Users/gokul/Desktop/PROJECTS/Edge-AI/src/modules/core/safety_registry_gate.py)
- Automated Tests: [`test_phase6_safety_registry.py`](file:///C:/Users/gokul/Desktop/PROJECTS/Edge-AI/src/tests/test_phase6_safety_registry.py)
