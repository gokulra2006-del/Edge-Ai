# Offline-First Emergency Operation Validation

## 1. Research Overview
Municipal safety systems cannot rely on continuous broadband or cloud connectivity during natural disasters, infrastructure failures, or deliberate jamming. Critical edge nodes must be capable of autonomous emergency detection, immediate local actuator triggering (strobes, sirens, relays), and persistent SQLite logging entirely decoupled from remote API availability.

This validation establishes rigorous empirical proof that edge decision-making and emergency dispatch continue with sub-$100\text{ ms}$ latency under $100\%$ WAN isolation, while remote consistency is maintained via an offline-first transactional outbox.

---

## 2. Formal Research Specifications

### Hypothesis
Decoupling local emergency decision logic, hardware siren actuators, and SQLite WAL storage from cloud dispatch guarantees sub-$100\text{ ms}$ local emergency handling during complete network blackout, while the transactional outbox preserves $100\%$ of critical audit and incident payloads for subsequent synchronization without blocking local execution.

### Primary Metrics
1. **Local Emergency Dispatch Latency**: $\le 100\text{ ms}$ elapsed time from incident trigger to local SQLite transaction commit and actuator assertion during total network isolation.
2. **Zero Audit Data Loss**: $100\%$ preservation of high-priority emergency outbox rows during extended network outages (never dropped by outbox cap policies).
3. **Decoupled Execution Reliability**: Zero unhandled exceptions or thread starvation caused by unreachable cloud endpoints.

---

## 3. Evaluation Methodology

### Evaluation Scenarios
1. **Total WAN Blackout Simulation**:
   - Ingests a critical incident (`EXPLOSION`, `CRITICAL` risk) while simulating complete network disconnect.
   - Measures end-to-end latency to assert local actuator execution and commit records to SQLite.
   - Verifies that latency satisfies the strict edge bound ($< 100\text{ ms}$).

2. **Outbox Buffering & State Preservation**:
   - Confirms that emergency payloads are enqueued in `sync_outbox` with `PENDING` status.
   - Verifies that local records in `incidents` remain immediately queryable by local operators despite the lack of internet connectivity.

---

## 4. Implementation Reference
- Architecture: [`IncidentRepository`](file:///C:/Users/gokul/Desktop/PROJECTS/Edge-AI/src/modules/database/governed_store.py) and [`OfflineSyncOutbox`](file:///C:/Users/gokul/Desktop/PROJECTS/Edge-AI/src/modules/assurance/device_health.py)
- Automated Tests: [`test_phase6_offline_validation.py`](file:///C:/Users/gokul/Desktop/PROJECTS/Edge-AI/src/tests/test_phase6_offline_validation.py)
