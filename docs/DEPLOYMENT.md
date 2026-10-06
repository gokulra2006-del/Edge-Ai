# Sentinel-AI Production Deployment Guide

This guide documents the procedures for deploying Sentinel-AI to production edge appliances:
1. **Primary Target**: Raspberry Pi 4 Model B (4 GB RAM, Quad-Core Cortex-A72 @ 1.5 GHz) running Raspberry Pi OS (64-bit).
2. **Host / Control Station**: Windows 10/11 (x86_64) workstation running as a background service or scheduled task.

---

## 1. System Architecture & Prerequisites

### Raspberry Pi 4 Model B Specifications
- **CPU**: Broadcom BCM2711, Quad-core Cortex-A72 (ARM v8) 64-bit SoC @ 1.5 GHz.
- **Memory**: 4 GB LPDDR4-3200 SDRAM.
- **Storage**: Minimum 32 GB Class 10 / Application Performance Class A2 MicroSD card.
- **Power**: Official Raspberry Pi 15W USB-C Power Supply (5.1V / 3.0A).
- **Peripherals**:
  - Camera: USB UVC webcam or CSI camera via libcamera / V4L2 (`/dev/video0`).
  - Audio: INMP441 I2S microphone or USB audio input (`/dev/snd`).
  - Sensors: GY-87 (MPU6050 + HMC5883L + BMP180) on I2C bus 1 (`/dev/i2c-1`), DHT22 (GPIO4), ADS1115 (I2C 0x48), NEO-6M GPS (UART `/dev/ttyAMA0` or `/dev/serial0`).

### Software Prerequisites (Raspberry Pi OS 64-bit Bookworm)
```bash
sudo apt update && sudo apt install -y \
    python3 python3-pip python3-venv git \
    libcap-dev v4l-utils i2c-tools libasound2-dev
```

Enable hardware buses via `raspi-config`:
```bash
sudo raspi-config nonint do_i2c 0
sudo raspi-config nonint do_spi 0
sudo raspi-config nonint do_serial_hw 0
```

---

## 2. Raspberry Pi 4 Deployment (systemd)

### Step 1: Clone Repository & Create Virtual Environment
```bash
cd /home/pi
git clone https://github.com/gokulra2006-del/Edge-Ai.git Edge-AI
cd Edge-AI
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
pip install -r requirements-optional.txt
```

### Step 2: Configure Environment Secrets
```bash
cp .env.example .env
nano .env
```
Ensure `SENTINEL_NODE_ID`, `SENTINEL_SECRET_KEY`, and optional cloud endpoints are set.

### Step 3: Install systemd Service & Backup Timer
```bash
sudo cp deploy/systemd/sentinel.service /etc/systemd/system/
sudo cp deploy/systemd/sentinel-backup.service /etc/systemd/system/
sudo cp deploy/systemd/sentinel-backup.timer /etc/systemd/system/

sudo systemctl daemon-reload
sudo systemctl enable --now sentinel.service
sudo systemctl enable --now sentinel-backup.timer
```

### Step 4: Verify Service Health & Supervision
```bash
# Check service status
sudo systemctl status sentinel.service

# View live stream logs
journalctl -u sentinel.service -f

# Check supervisor probes
curl -i http://localhost:8080/healthz
curl -i http://localhost:8080/readyz
curl -i http://localhost:8080/api/system/version
```

### Systemd Sandboxing & Resource Limits
The `sentinel.service` file enforces strict systemd limits to protect the Pi 4 hardware:
- **Watchdog**: `WatchdogSec=30s` with auto-restart on hangs.
- **Auto-Restart**: `Restart=always`, `RestartSec=5s`.
- **Memory Limit**: `MemoryMax=2.8G` and `MemoryHigh=2.5G` (prevents OOM killer from killing OS subsystems).
- **CPU Quota**: `CPUQuota=350%` (leaves 50% of one core free for OS/kernel interrupts).
- **Security**: `ProtectSystem=full`, `PrivateTmp=true`, `NoNewPrivileges=true`.

---

## 3. Windows Service Deployment

For Windows workstations or control node servers:

### Option A: Windows Task Scheduler (Recommended for standard installations)
Run PowerShell as Administrator:
```powershell
powershell -ExecutionPolicy Bypass -File scripts\windows\register_task_scheduler.ps1
```
Or manually via Windows `schtasks`:
```cmd
schtasks /create /tn "Sentinel-AI-Edge-Node" /tr "C:\Users\gokul\Desktop\PROJECTS\Edge-AI\.venv\Scripts\python.exe -m src.modules.dashboard.app --port 8080" /sc onstart /ru "SYSTEM"
```

To manage the task:
```powershell
Start-ScheduledTask -TaskName "Sentinel-AI-Edge-Node"
Get-ScheduledTask -TaskName "Sentinel-AI-Edge-Node"
Stop-ScheduledTask -TaskName "Sentinel-AI-Edge-Node"
```

### Option B: NSSM (Non-Sucking Service Manager)
1. Download `nssm.exe` from [nssm.cc](https://nssm.cc/download) and place in `C:\Windows\System32` or your PATH.
2. Run the automated script as Administrator:
```cmd
scripts\windows\install_service_nssm.bat
```
3. Or configure manually:
```cmd
nssm install SentinelAI "C:\path\to\Edge-AI\.venv\Scripts\python.exe"
nssm set SentinelAI AppParameters "-m src.modules.dashboard.app --port 8080"
nssm set SentinelAI AppDirectory "C:\path\to\Edge-AI"
nssm set SentinelAI Start SERVICE_AUTO_START
nssm start SentinelAI
```

---

## 4. Database Disaster Recovery & Maintenance

### Creating an Online Non-Blocking Backup
Uses SQLite's online backup API, snapshotting without pausing background ingestion:
```bash
python -m src.modules.maintenance backup \
    --source data/emergency_events.db \
    --target data/backups/manual_backup_$(date +%Y%m%d_%H%M%S).db
```
This produces a companion `.meta.json` with the SHA-256 digest.

### Restoring and Verifying Database from Snapshot
```bash
python -m src.modules.maintenance restore \
    --source data/backups/sentinel_daily.db \
    --target data/emergency_events.db
```
The command automatically verifies the SHA-256 checksum and executes `PRAGMA integrity_check` and `PRAGMA quick_check` on the restored database.

### Running Startup & Crash Recovery Audit
```bash
python -m src.modules.maintenance recovery --db data/emergency_events.db
```

---

## 5. Supervisor Health & Readiness Probes

External process supervisors (systemd, Kubernetes, Docker, consul, monit) can query:

### `/healthz` (Liveness Probe)
- **Method**: `GET`
- **Auth**: None required (public)
- **Response**: `200 OK`
```json
{
  "status": "alive",
  "uptime_seconds": 12450.2,
  "timestamp": "2026-10-06T14:30:00Z"
}
```

### `/readyz` (Readiness Probe)
- **Method**: `GET`
- **Auth**: None required (public)
- **Response**: `200 OK` (when ready) or `503 Service Unavailable` (when unready)
```json
{
  "status": "ready",
  "checks": {
    "database": "ok",
    "writer_queue": "ok",
    "storage": "ok",
    "camera": "OK",
    "microphone": "OK"
  },
  "errors": [],
  "timestamp": "2026-10-06T14:30:00Z"
}
```

### `/api/system/version` (Version Metadata)
- **Method**: `GET`
- **Auth**: None required (public)
- **Response**: `200 OK`
```json
{
  "version": "0.5.0",
  "git_hash": "e3e988f",
  "build_date": "2026-10-06",
  "schema_version": 7,
  "target_platform": "Raspberry Pi 4 Model B (4 GB)",
  "runtime_os": "Linux 6.6.20+rpt-rpi-v8",
  "python_version": "3.11.2"
}
```

---

## 6. Hardware Benchmarking Suite (scripts/pi/)

> [!IMPORTANT]
> **Real Hardware Execution Requirement**:
> These benchmark scripts **MUST be run directly on the physical Raspberry Pi 4 Model B hardware**.
> Execution in development environments (Windows/macOS/x86) validates software mechanics, JSON report schema generation, and error fallbacks only; genuine thermal, hardware bus contention, V4L2/libcamera frame rates, and microSD flash write latency metrics require actual ARM hardware and physical peripherals.

Run these scripts directly on the Raspberry Pi 4 to validate production hardware specs. Each script outputs a structured JSON report:

1. **Sustained CPU & Memory**:
   ```bash
   python scripts/pi/benchmark_cpu_memory.py --duration 30 --out reports/bench_cpu.json
   ```
2. **Camera Ingestion FPS**:
   ```bash
   python scripts/pi/benchmark_camera_fps.py --frames 300 --device 0 --fps 15.0 --out reports/bench_camera.json
   ```
3. **Audio Capture Latency & Dropped Windows**:
   ```bash
   python scripts/pi/benchmark_audio_latency.py --duration 30 --sample-rate 16000 --out reports/bench_audio.json
   ```
4. **Sensor Bus (I2C/SPI) Lock Contention**:
   ```bash
   python scripts/pi/benchmark_sensor_contention.py --workers 4 --ops 100 --out reports/bench_i2c.json
   ```
5. **Thermal & Throttling Status (`vcgencmd`)**:
   ```bash
   python scripts/pi/benchmark_thermal.py --out reports/bench_thermal.json
   ```
6. **MicroSD Storage Write Latency & fsync**:
   ```bash
   python scripts/pi/benchmark_storage_latency.py --ops4k 100 --ops64k 50 --out reports/bench_io.json
   ```
