# Sentinel-AI Operational Analytics & Intelligence Engine (Phase 5A)

## 1. Overview & Architectural Principles

The Sentinel-AI Analytics Engine delivers high-speed, non-blocking operational intelligence for mission-critical edge deployments on Raspberry Pi 4/5 and Windows workstations.

### Core Architecture Rules:
1. **Non-Blocking Read Isolation**: Analytics queries run over dedicated read-only SQLite connections with `PRAGMA query_only = ON` and `PRAGMA busy_timeout = 2000`. Analytics readers NEVER block live telemetry or incident writers in WAL mode.
2. **Pre-Aggregated Daily Rollups**: High-frequency charts and aggregations query the pre-aggregated `analytics_daily` and `analytics_device_daily` tables instead of repeatedly scanning raw telemetry tables.
3. **Resumable & Idempotent Incremental Rollup**: The rollup worker maintains high-water marks in `analytics_rollup_state`. Late-arriving data from offline edge nodes is safely captured by re-rolling the last $N$ days (default 3 days).
4. **Bounded Range Enforcement**: All queries require bounded time ranges (default: last 30 days; maximum: 365 days). Unbounded queries and inverted ranges (`start > end`) are strictly rejected.
5. **Strict Pagination on Drill-Downs**: Raw record endpoints (`incidents`, `predictions`) enforce hard pagination limits (clamped to a maximum page size of 200) to protect Raspberry Pi CPU and memory.

---

## 2. Canonical Metric Definitions

### 2.1 False Alarm Rate
* **Definition**: An incident is classified as a false alarm if an operator marks the incident status as `FALSE_ALARM`, or if operator review feedback flags a model prediction as `INCORRECT` with a corrected classification of `NORMAL`.
* **Formula**:
  $$\text{False Alarm Rate (\%)} = \left( \frac{\text{False Alarm Incidents}}{\text{Total Incidents}} \right) \times 100$$
* **Edge Cases**: If $\text{Total Incidents} = 0$, the false alarm rate defaults to `0.0%`.

### 2.2 Operator Disagreement Rate
* **Definition**: Quantifies divergence between edge AI model predictions and human operator ground truth.
* **Formula**:
  $$\text{Disagreement Rate (\%)} = \left( \frac{\text{Evaluated Predictions with } \text{label} = \text{'INCORRECT'}}{\text{Total Evaluated Predictions}} \right) \times 100$$
* **Edge Cases**: Unevaluated predictions without human feedback are excluded from the denominator. If no predictions have been evaluated, the disagreement rate defaults to `0.0%`.

### 2.3 Mean, Median, and p95 Response Times (MTTA & MTTR)
* **Mean Time to Acknowledge (MTTA)**:
  $$\text{MTTA} = \frac{1}{N_{\text{ack}}} \sum_{i=1}^{N_{\text{ack}}} t_{\text{ack}, i}$$
  Calculated strictly over non-null, non-negative acknowledgment durations recorded when an operator confirms or acknowledges an incident.
* **Mean Time to Resolve (MTTR)**:
  $$\text{MTTR} = \frac{1}{N_{\text{res}}} \sum_{i=1}^{N_{\text{res}}} t_{\text{res}, i}$$
  Calculated across all resolved and closed incidents.
* **Median & p95 Percentiles**:
  p95 represents the 95th percentile response duration computed via linear interpolation across sorted duration samples:
  $$P_{95} = \text{Percentile}_{0.95}(\{t_i\})$$

### 2.4 Subsystem Availability & Uptime
* **Operational States**: `OK` and `DEGRADED` states count toward operational availability (system is functioning and ingesting).
* **Downtime States**: `DOWN`, `UNHEALTHY`, and `CRITICAL` states count as downtime.
* **Missing & Unknown Data Policy**:
  > [!IMPORTANT]
  > Gaps in telemetry or health records with status `UNKNOWN` are **NEVER** treated as 100% uptime. Missing data intervals are recorded as unverified downtime until positive heartbeat telemetry is restored.
* **Uptime Percentage**:
  $$\text{Availability (\%)} = \left( \frac{\text{Uptime Seconds}}{\text{Total Monitored Seconds}} \right) \times 100$$

### 2.5 Model Confidence & OOD Trend
* **Mean Confidence**: Arithmetic mean of raw model prediction confidences ($[0.0, 1.0]$).
* **Out-Of-Distribution (OOD) Rate**:
  $$\text{OOD Rate} = \frac{\text{Count of Predictions where } \text{ood\_status} = \text{'OOD'}}{\text{Total Predictions}}$$

### 2.6 Drift Progression (PSI)
* Historical tracking of Population Stability Index (PSI) snapshots:
  * **STABLE**: $\text{PSI} < 0.10$
  * **DRIFT_WARNING**: $0.10 \le \text{PSI} < 0.25$
  * **DRIFT_DETECTED**: $\text{PSI} \ge 0.25$

---

## 3. Database Schema & Migration 8

Migration 8 establishes pre-aggregated rollups and query composite indexes:

```sql
-- Pre-aggregated daily rollup for incidents and models
CREATE TABLE IF NOT EXISTS analytics_daily (
  day TEXT NOT NULL,
  zone_id TEXT NOT NULL,
  severity TEXT NOT NULL,
  event_type TEXT NOT NULL,
  model_id TEXT NOT NULL,
  total_incidents INTEGER NOT NULL DEFAULT 0,
  resolved_count INTEGER NOT NULL DEFAULT 0,
  false_alarm_count INTEGER NOT NULL DEFAULT 0,
  total_ack_seconds REAL NOT NULL DEFAULT 0.0,
  ack_count INTEGER NOT NULL DEFAULT 0,
  total_resolve_seconds REAL NOT NULL DEFAULT 0.0,
  resolve_count INTEGER NOT NULL DEFAULT 0,
  sample_count INTEGER NOT NULL DEFAULT 0,
  sum_confidence REAL NOT NULL DEFAULT 0.0,
  ood_count INTEGER NOT NULL DEFAULT 0,
  incorrect_count INTEGER NOT NULL DEFAULT 0,
  correct_count INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (day, zone_id, severity, event_type, model_id)
);

-- Daily device uptime rollup
CREATE TABLE IF NOT EXISTS analytics_device_daily (
  day TEXT NOT NULL,
  component TEXT NOT NULL,
  uptime_seconds REAL NOT NULL DEFAULT 0.0,
  total_seconds REAL NOT NULL DEFAULT 0.0,
  event_count INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (day, component)
);

-- Incremental rollup state tracking
CREATE TABLE IF NOT EXISTS analytics_rollup_state (
  rollup_name TEXT PRIMARY KEY,
  high_water_mark TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

-- Composite query indexes
CREATE INDEX IF NOT EXISTS idx_incidents_created_zone ON incidents(created_at, zone_id);
CREATE INDEX IF NOT EXISTS idx_incidents_created_sev ON incidents(created_at, severity);
CREATE INDEX IF NOT EXISTS idx_incidents_created_event ON incidents(created_at, event_type);
CREATE INDEX IF NOT EXISTS idx_predictions_ts_model ON predictions(timestamp, model_id);
CREATE INDEX IF NOT EXISTS idx_device_health_ts_comp ON device_health_events(timestamp, component);
CREATE INDEX IF NOT EXISTS idx_outbox_ts_status ON sync_outbox(created_at, status);
CREATE INDEX IF NOT EXISTS idx_analytics_daily_day ON analytics_daily(day);
CREATE INDEX IF NOT EXISTS idx_analytics_device_day ON analytics_device_daily(day);
```

---

## 4. Query Filter & Envelope Specification

### 4.1 Filter Object (`AnalyticsFilter`)
All analytics methods accept an `AnalyticsFilter` instance:
* `start_time`: ISO 8601 start timestamp.
* `end_time`: ISO 8601 end timestamp.
* `zone`: Optional zone identifier (e.g. `ZONE_NORTH`).
* `severity`: Optional severity filter (`CRITICAL`, `HIGH`, `MEDIUM`, `LOW`, `NORMAL`).
* `event_type`: Optional event type filter (`FIRE`, `COLLISION`, `HAZARD`).
* `model_id`: Optional model version identifier.
* `include_demo`: Boolean (default `False`). Excludes simulation test records from production metrics.

### 4.2 Standard Response Envelope
All `/api/analytics/*` JSON endpoints return a standardized envelope:

```json
{
  "data": { ... },
  "filters_applied": {
    "start_time": "2026-09-01T00:00:00+00:00",
    "end_time": "2026-09-30T23:59:59+00:00",
    "start_date": "2026-09-01",
    "end_date": "2026-09-30",
    "zone": null,
    "severity": null,
    "event_type": null,
    "model_id": null,
    "include_demo": false
  },
  "generated_at": "2026-10-06T15:00:00+00:00",
  "rollup_freshness": "2026-10-06T14:55:00+00:00",
  "empty_state": false
}
```

---

## 5. API Reference & Role Access

| Endpoint | Method | Allowed Roles | Description |
| :--- | :--- | :--- | :--- |
| `/api/analytics/overview` | `GET` | All Roles | Operations overview KPI cards, zone comparison |
| `/api/analytics/trends` | `GET` | All Roles | Time-bucketed incident volume and severity trend |
| `/api/analytics/zones` | `GET` | All Roles | Zone risk comparison and active incident rankings |
| `/api/analytics/models` | `GET` | All Roles | Model accuracy, confusion matrix, OOD trends |
| `/api/analytics/availability`| `GET` | All Roles | Component uptime percentages & degradation |
| `/api/analytics/outbox` | `GET` | All Roles | Offline sync outbox backlog and queue status |
