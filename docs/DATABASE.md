# Governed incident database

Phase 1 adds a separate, backward-compatible incident record beside the existing emergency-event and telemetry tables. `MigrationRunner` applies numbered migrations once through `schema_migrations`; it keeps the legacy tables and creates `LEGACY-*` incident records for prior emergency events. SQLite runs in WAL mode with foreign keys and a short busy timeout.

Inference code never waits for persistence: `SQLiteWriter` accepts operations on one bounded queue, retries transient locks, and records failures for health reporting. A queue failure does not change a detection or actuator decision.

```mermaid
erDiagram
  INCIDENTS ||--o{ INCIDENT_EVENTS : groups
  INCIDENTS ||--o{ PREDICTIONS : records
  INCIDENTS ||--o{ OPERATOR_ACTIONS : audits
  INCIDENTS ||--o{ EVIDENCE : preserves
  INCIDENTS ||--o{ ASSURANCE_STATES : captures
  MODELS ||--o{ PREDICTIONS : produces
  MODELS ||--o{ DEPLOYMENTS : logs
  INCIDENTS {
    string incident_id PK
    string incident_uuid
    string status
    string zone_id
  }
  MODELS {
    string model_id PK
    string held_out_f1
    string readiness
    string usage_restriction
    string status
  }
```

`EvidenceExporter` creates `evidence/<incident_id>/manifest.json` and an optional ZIP. The manifest contains the incident timeline, predictions, operator actions, copied source files, and SHA-256 values. `verify()` recomputes every packaged-file hash before accepting it.

Synthetic profiles remain `RESEARCH_ONLY`; model entries carry the same usage restriction. Missing evaluation measures are stored as `UNVERIFIED`, never inferred. Startup checksum mismatches mark the model `REVIEW_REQUIRED` and record a deployment event.

## Phase 2 migration

Migration 3 adds `risk_level` and `risk_breakdown_json` to incidents. Migrations remain append-only; old data and tables are retained.

## Phase 3 migration

Migration 4 adds optimistic-concurrency versioning, acknowledgement/resolution durations, temporal/OOD fields, demo and severity metadata, plus append-only `incident_notes`, `prediction_feedback`, and `review_claims` tables.

```mermaid
erDiagram
  INCIDENTS ||--o{ INCIDENT_NOTES : receives
  PREDICTIONS ||--o{ PREDICTION_FEEDBACK : reviews
  PREDICTIONS ||--o| REVIEW_CLAIMS : assigned
```

## Phase 4 migration

Migration 5 introduces dynamic system resilience, model drift tracking, and offline-first queue persistence:
- **`assurance_level`**: Added to `incidents` and `predictions` (`FULL`, `VISION_ONLY`, `AUDIO_ONLY`, `SENSORS_ONLY`, `DEGRADED`).
- **`model_baselines`**: Captures fixed-bin confidence histograms, class priors, OOD rates, false alarm rates, and `RESEARCH_ONLY` restrictions.
- **`drift_snapshots`**: Records periodic evaluations of Population Stability Index (PSI), max prior shifts, and drift status (`STABLE`, `WATCH`, `DRIFT_WARNING`, `REVIEW_REQUIRED`).
- **`device_health_events`**: Transition-only ledger of hardware, storage, and database availability changes.
- **`sync_outbox`**: Offline-first idempotent queue with exponential backoff, jitter, dead-letter state, and priority-aware compaction policies.

```mermaid
erDiagram
  MODELS ||--o{ MODEL_BASELINES : calibrates
  MODELS ||--o{ DRIFT_SNAPSHOTS : monitors
  INCIDENTS ||--o{ SYNC_OUTBOX : queues
```
