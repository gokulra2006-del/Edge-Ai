# Operator workflow

The dashboard keeps emergency decisions under human control. `ESCALATED` means ready for operator attention; external dispatch is simulated and requires an authenticated Commander action.

```mermaid
stateDiagram-v2
  OPEN --> ACKNOWLEDGED: acknowledge
  REVIEW_REQUIRED --> ACKNOWLEDGED: acknowledge
  ACKNOWLEDGED --> CONFIRMED: confirm
  ACKNOWLEDGED --> ESCALATED: commander escalate
  CONFIRMED --> ESCALATED: commander escalate
  OPEN --> FALSE_ALARM: reason required
  ACKNOWLEDGED --> FALSE_ALARM: reason required
  ACKNOWLEDGED --> CLOSED: commander resolve
  CONFIRMED --> CLOSED: commander resolve
  ESCALATED --> CLOSED: commander resolve
  FALSE_ALARM --> CLOSED: commander resolve
```

Every transition includes the operator, role, timestamp, previous and new state, and reason. Version checks reject duplicate or stale requests. Closed incidents accept appended notes but no further state changes.

| Capability | Commander | Operator | Engineer | Viewer |
|---|---:|---:|---:|---:|
| View incidents and plans | Yes | Yes | Yes | Yes |
| Acknowledge / confirm | Yes | Yes | No | No |
| Mark false alarm / add note | Yes | Yes | No | No |
| Escalate / resolve | Yes | No | No | No |
| Review queue and model registry | Yes | Yes | Yes | No |
| Stream Controls (Camera / Audio Start / Stop) | Yes | Yes | No (View only) | No |
| View System Health & Drift Dashboard | Yes | Yes | Yes | Yes |

The Review Queue prioritizes unknown, OOD-flagged, low-confidence, and disputed predictions. Reviewers claim an item before adding `CORRECT`, `INCORRECT`, or `UNSURE` feedback. Changed feedback creates another row, preserving history. JSON and CSV manifests include only reviewed feedback and exclude demo incidents by default. Export never starts training.

The Emergency Plan is available at `#emergency-plan`. Browser back, forward, and reload preserve the current page. The Incident Logs page lists governed incidents and opens a detail panel containing temporal events, stored risk, OOD state, evidence, and the append-only audit trail.

The System Health & Resilience page is available at `#system-health`. It provides real-time visibility into subsystem availability, live camera/audio stream parameters and controls, model drift stability indices (PSI), and the offline-first sync outbox queue.
