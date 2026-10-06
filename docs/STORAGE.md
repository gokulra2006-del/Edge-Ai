# Sentinel-AI Production Storage Safety & Data Retention (Phase 5D)

## 1. Overview & Architectural Principles

Edge AI appliances deployed in unattended municipal and industrial field settings (such as Raspberry Pi 4/5 units with microSD cards) face severe storage constraints and flash wear risks. Sentinel-AI implements an automated, fail-safe storage retention engine designed to operate 24/7 without manual maintenance.

### Core Architectural Guarantees:
1. **Zero Data Loss on Protected Safety Records**:
   - **Active/Unresolved Incidents**: Incidents in `OPEN`, `ACKNOWLEDGED`, `CONFIRMED`, or `ESCALATED` states are **NEVER** deleted.
   - **Forensic Evidence Linked to Open/Recent Incidents**: Video clips, audio traces, and keyframes linked to unresolved or recently resolved incidents are strictly protected from deletion.
   - **Immutable Audit Ledger**: Records in `operator_actions`, `incident_notes`, and `storage_cleanup_logs` are permanent and **NEVER** pruned under any condition.
   - **Unsynced Outbox Messages**: Queued messages with status `PENDING` or `DEAD_LETTER` are strictly preserved to guarantee eventually-consistent cloud sync.
2. **Compress-Before-Prune Telemetry Archival**: High-frequency raw sensor telemetry is never deleted outright; rows are batched, exported to compressed `.json.gz` archives in `data/archives/`, cryptographically checksummed with SHA-256, and only then pruned from SQLite tables.
3. **Oldest-First DVR Eviction**: Video recordings in `data/recordings/` are capped by a configurable byte limit (default: 500 MB). When storage exceeds the cap, the oldest video recordings are evicted first until the directory falls within safety margins.
4. **Automated SQLite WAL Checkpointing**: The Write-Ahead Log (WAL) is periodically checkpointed (`PASSIVE` during normal operations, and auto-`TRUNCATE` when exceeding configured size limits) to reclaim microSD flash storage and prevent unbounded file growth.
5. **Dry-Run Simulation & Audit Trail**: Every cleanup job supports a `--dry-run` simulation mode. All cleanup actions (files deleted, bytes reclaimed, policy invoked) are permanently logged to `storage_cleanup_logs`.
6. **Network Outage Resilience**: Bounded outbox queues with exponential backoff and batch catch-up enable nodes to survive days of offline operation and rapidly synchronize upon network recovery without overflowing flash storage.

---

## 2. Retention Policies Configuration

Storage policies are configured centrally in `config.json` / `governance_config.py`:

```json
{
  "storage": {
    "retention": {
      "raw_telemetry_days": 7,
      "archive_telemetry_after_days": 3,
      "dvr_max_bytes": 524288000,
      "evidence_retention_days": 30,
      "reports_retention_days": 90,
      "logs_retention_days": 14,
      "synced_outbox_retention_days": 7
    },
    "wal": {
      "checkpoint_mode": "PASSIVE",
      "auto_truncate_bytes": 10485760,
      "checkpoint_interval_seconds": 300
    },
    "thresholds": {
      "warning_bytes": 1073741824,
      "critical_bytes": 268435456
    }
  }
}
```

### Policy Reference Matrix:

| Subsystem | Policy Limit | Eviction / Retention Mechanism | Safeguard |
|---|---|---|---|
| **Raw Telemetry** | 3 days raw / 7 days max | Compressed to `.json.gz` in `data/archives/` before SQLite pruning. | Archive SHA-256 verified before deleting raw rows. |
| **Blackbox DVR** | 500 MB hard cap | Oldest video files evicted first when folder exceeds cap. | Eviction halts once total size falls below cap. |
| **Forensic Evidence** | 30 days retention | Deleted only if linked incident is `CLOSED` or `RESOLVED`. | **NEVER deletes evidence for open/active incidents.** |
| **Audit Ledger** | Indefinite | Permanent immutable history. | **NEVER deleted under any circumstances.** |
| **Sync Outbox** | 500 rows max cap | Prunes expired `SYNCED` rows older than 7 days. Drops `LOW` priority telemetry if cap exceeded. | **NEVER drops `HIGH`, `AUDIT`, `PENDING`, or `DEAD_LETTER` rows.** |
| **SQLite WAL** | 10 MB threshold | Automatic `TRUNCATE` checkpoint to reclaim flash storage space. | Passive checkpoints flush dirty pages with zero database locks. |

---

## 3. Storage Health Thresholds & System Health Dashboard

Storage capacity is monitored continuously:
* **Nominal (`OK`)**: Available disk space $> 1.0\text{ GB}$.
* **Warning (`DEGRADED`)**: Available disk space $\le 1.0\text{ GB}$ and $> 250\text{ MB}$. Storage status banner on `#system-health` turns amber (`STORAGE_WARNING`).
* **Critical (`DOWN`)**: Available disk space $\le 250\text{ MB}$. Storage status banner turns red (`STORAGE_CRITICAL`), non-essential background tasks pause, and emergency notifications alert operators.

---

## 4. Command-Line Interface (CLI)

The storage subsystem includes a dedicated management CLI:

```bash
# 1. View storage health, volume utilization, and threshold margins
python -m src.modules.storage status

# 2. Simulate cleanup in dry-run mode (no files or rows deleted)
python -m src.modules.storage cleanup --dry-run --policy all --role COMMANDER

# 3. Execute real cleanup across all policies
python -m src.modules.storage cleanup --policy all --role COMMANDER

# 4. Execute specific subsystem cleanup (e.g. telemetry archival)
python -m src.modules.storage cleanup --policy telemetry --role COMMANDER

# 5. Force an immediate SQLite WAL TRUNCATE checkpoint
python -m src.modules.storage checkpoint --mode TRUNCATE --role ENGINEER

# 6. Inspect recent permanent storage cleanup logs
python -m src.modules.storage logs --limit 10
```
