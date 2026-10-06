# Sentinel-AI Release Verification Checklist

This checklist must be strictly completed and signed off prior to deploying a new release of Sentinel-AI to production edge nodes (Raspberry Pi 4) or field appliances.

---

## 1. Automated Test & Code Quality Baseline
- [ ] Run the complete automated test suite:
  ```bash
  .venv/bin/pytest src/tests -v --basetemp=data/test_tmp
  # Windows:
  .venv\Scripts\python.exe -m pytest src/tests -v --basetemp=data/test_tmp
  ```
  *Requirement: 100% of tests must pass (126+ tests, zero regressions).*
- [ ] Verify git working directory status:
  ```bash
  git status
  ```
  *Requirement: Clean working tree; no uncommitted secrets, temp databases, or scratch files.*
- [ ] Verify endpoint permission introspection guard passes:
  ```bash
  python -m pytest src/tests/test_phase5e_security_hardening.py -k "test_endpoint_permission_matrix_introspection_guard"
  ```
  *Requirement: No unregistered routes exist.*

---

## 2. Configuration Schema & Secrets Validation
- [ ] Validate production configuration against schema:
  ```python
  from src.modules.core.config_validator import load_and_validate_config
  load_and_validate_config("src/config/production.json")
  ```
- [ ] Ensure `.env` is configured from `.env.example`:
  - `SENTINEL_NODE_ID`: Unique node identifier (e.g., `NODE_B_INTERSECTION_4`).
  - `SENTINEL_SECRET_KEY`: High-entropy random key.
  - `SENTINEL_ALLOWED_HOSTS`: Restricted hostnames or IP addresses.
  - `FIREBASE_DB_URL`: Valid HTTPS endpoint or left blank for offline-only.
- [ ] Ensure NO credentials or plain-text passwords exist in git repo.

---

## 3. Database State & Recovery Checks
- [ ] Run online backup test and verify SHA-256 integrity:
  ```bash
  python -m src.modules.maintenance backup --source data/emergency_events.db --target data/backups/pre_release.db
  python -m src.modules.maintenance verify --db data/backups/pre_release.db
  ```
- [ ] Run startup and crash recovery checks:
  ```bash
  python -m src.modules.maintenance recovery --db data/emergency_events.db
  ```
  *Verify that stuck in-progress outbox rows are cleared and DB passes `quick_check`.*
- [ ] Confirm schema migration version matches current migration sequence (Version 7).

---

## 4. Security & Role Hardening Verification
- [ ] Verify all accounts in user store use salted bcrypt hashes:
  ```bash
  python -m src.modules.security list-users
  ```
- [ ] If initial deployment, initialize the Commander account:
  ```bash
  python -m src.modules.security setup-admin --username commander --role COMMANDER
  ```
- [ ] Confirm session timeouts (idle: 30 minutes, absolute: 8 hours).
- [ ] Confirm CSRF tokens are enforced on state-changing operations.

---

## 5. Hardware Benchmarks & Performance Baselines
Run on the physical Raspberry Pi 4 edge device:
- [ ] Sustained CPU & RAM test:
  ```bash
  python scripts/pi/benchmark_cpu_memory.py --duration 10 --out data/bench_cpu.json
  ```
  *Threshold: Sustained CPU < 80%, RAM RSS < 350 MB.*
- [ ] Camera FPS & Jitter test:
  ```bash
  python scripts/pi/benchmark_camera_fps.py --frames 100 --out data/bench_cam.json
  ```
  *Threshold: Achieved FPS >= 13 FPS (for 15 FPS target), jitter < 20 ms.*
- [ ] Audio Latency & Ring Buffer test:
  ```bash
  python scripts/pi/benchmark_audio_latency.py --duration 10 --out data/bench_audio.json
  ```
  *Threshold: Zero dropped windows, processing latency < 40 ms.*
- [ ] Sensor Bus Contention test:
  ```bash
  python scripts/pi/benchmark_sensor_contention.py --workers 4 --ops 50 --out data/bench_i2c.json
  ```
  *Threshold: Max lock wait < 50 ms, zero bus collisions.*
- [ ] Thermal & Throttling test:
  ```bash
  python scripts/pi/benchmark_thermal.py --out data/bench_thermal.json
  ```
  *Threshold: CPU temperature < 70°C, zero active or historic throttling flags.*
- [ ] MicroSD Write Latency test:
  ```bash
  python scripts/pi/benchmark_storage_latency.py --out data/bench_io.json
  ```
  *Threshold: Average fsync latency < 50 ms.*

---

## 6. Supervisor Readiness & Health Probes
- [ ] Verify `/healthz` liveness probe returns HTTP 200:
  ```bash
  curl -i http://localhost:8080/healthz
  ```
- [ ] Verify `/readyz` readiness probe returns HTTP 200 with all checks `ok`:
  ```bash
  curl -i http://localhost:8080/readyz
  ```
- [ ] Verify version info endpoint:
  ```bash
  curl -i http://localhost:8080/api/system/version
  ```
- [ ] Check dashboard UI displays version badge in header (e.g., `v0.5.0 (git_hash)`).

---

## 7. Service Supervision
- [ ] For Linux / Raspberry Pi: Verify systemd service status:
  ```bash
  sudo systemctl status sentinel.service
  sudo systemctl status sentinel-backup.timer
  ```
- [ ] For Windows: Verify service status in NSSM or Task Scheduler:
  ```bash
  nssm status SentinelAI
  # or
  Get-ScheduledTask -TaskName Sentinel-AI-Edge-Node
  ```
