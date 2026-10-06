# Raspberry Pi Real Deployment Validation Run Guide

This guide details the procedure for executing real hardware benchmarking on physical Raspberry Pi devices (CM4, Pi 4B, Pi 5) for the project thesis:
> *"An Auditable, Drift-Aware, Human-Governed Multimodal Edge AI Platform for Offline Urban Emergency Detection and Response"*

Under our research rules, **zero fabrication** is strictly enforced. Synthetic or simulated results are never presented as real hardware data. All validation scripts cryptographically sign hardware telemetry (`/proc/device-tree/model`, `/proc/cpuinfo`, OS release, git hash) with `data_tag: REAL_HARDWARE`. Any unmeasured metrics will honestly display as `NOT_MEASURED` in generated publication tables.

---

## 1. Prerequisites on Raspberry Pi

### System Requirements
- Raspberry Pi OS (Debian Bookworm 64-bit or Bullseye 64-bit)
- Python 3.9+ with virtual environment
- Git repository clone matching the host commit hash

```bash
# Update system and install hardware utilities
sudo apt-get update
sudo apt-get install -y git python3-venv python3-pip libraspberrypi-bin i2c-tools libportaudio2

# Clone or pull the repository
git clone <REPO_URL> Edge-AI
cd Edge-AI
git checkout <CURRENT_GIT_COMMIT>

# Create virtual environment and install dependencies
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

---

## 2. Automated Master Suite Execution

To run all automated benchmarks in a single batch (CPU/Memory, Thermal, Camera, Audio, Sensor contention, MicroSD storage, and Network recovery simulation):

```bash
python3 -m scripts.pi.run_all_validation --output results/pi_validation_bundle.json --duration 30
```

This generates `results/pi_validation_bundle.json` containing signed hardware metrics for all automated stages.

---

## 3. Individual Benchmark Procedures

### Benchmark 1: Sustained CPU & Memory (`benchmark_cpu_memory.py`)
Measures baseline and multi-threaded edge workload CPU utilization, RAM usage, and RSS delta.

```bash
python3 -m scripts.pi.benchmark_cpu_memory --duration 30 --workers 4 --output results/cpu_memory_results.json
```

---

### Benchmark 2: Thermal Throttling (`benchmark_thermal.py`)
Queries SoC core temperature and parses the `vcgencmd get_throttled` bitmask (under-voltage, arm frequency capped, throttled, soft temperature limit).

```bash
python3 -m scripts.pi.benchmark_thermal --duration 30 --stress --output results/thermal_results.json
```

---

### Benchmark 3: Camera Sensor FPS (`benchmark_camera_fps.py`)
Evaluates native capture frame rate, frame delivery variance, and frame drop counts across V4L2 / Picamera2 / OpenCV capture pipelines.

```bash
# Test CSI ribbon / USB video device 0 at 1080p
python3 -m scripts.pi.benchmark_camera_fps --device 0 --width 1920 --height 1080 --frames 300 --output results/camera_fps_results.json
```

---

### Benchmark 4: Audio Latency & Ring-Buffer Overruns (`benchmark_audio_latency.py`)
Measures round-trip input latency, dropped audio chunks, and DSP feature extraction time for edge acoustic detectors.

```bash
python3 -m scripts.pi.benchmark_audio_latency --duration 30 --samplerate 16000 --blocksize 1024 --output results/audio_latency_results.json
```

---

### Benchmark 5: I2C & SPI Sensor Bus Contention (`benchmark_sensor_contention.py`)
Measures bus transaction latency and bus lock collision rates when multiple sensor threads poll environmental and IMU sensors concurrently.

```bash
python3 -m scripts.pi.benchmark_sensor_contention --i2c-bus 1 --i2c-addr 0x68 --threads 4 --samples 500 --output results/sensor_contention_results.json
```

---

### Benchmark 6: MicroSD Storage Latency (`benchmark_storage_latency.py`)
Measures sync write latency, WAL checkpoint overhead, and fsync jitter under sustained incident logging.

```bash
python3 -m scripts.pi.benchmark_storage_latency --target-dir /var/log/edge-ai --block-size 4096 --count 1000 --fsync --output results/storage_latency_results.json
```

---

## 4. Physical Fault-Injection & Recovery Procedures

### Test 7: Network Outage & Recovery (`test_network_recovery.py`)
Evaluates edge outbox queue spooling when cellular / Wi-Fi drops, and measures time to flush pending batches once reconnected.

#### Physical Step-by-Step:
1. Run the test with live network interface monitor:
   ```bash
   python3 -m scripts.pi.test_network_recovery --outbox-db data/sync_outbox.db --output results/network_recovery_results.json
   ```
2. **Physical Action:**
   - Unplug the Ethernet cable or disable Wi-Fi (`sudo nmcli radio wifi off` or `sudo rfkill block wifi`).
   - The script creates synthetic incident records into the offline outbox database.
   - Reconnect Ethernet or re-enable Wi-Fi (`sudo nmcli radio wifi on` or `sudo rfkill unblock wifi`).
3. The script monitors interface reconnection time, computes flush throughput (records/sec), and writes the cryptographically signed summary.

---

### Test 8: Sudden Power-Interruption Recovery (`test_power_recovery.py`)
Verifies zero data loss in audit logs (`operator_actions`), SQLite database structural integrity (`PRAGMA integrity_check`), and WAL transaction rollforward after unexpected power loss.

#### Physical Step-by-Step:
1. **Pre-Interruption Phase (Execute on Pi):**
   ```bash
   python3 -m scripts.pi.test_power_recovery --prepare --db-path data/edge_production.db
   ```
   *The script populates test audit records, prepares outbox payloads, and prints a ready marker.*

2. **Physical Action (Power Sever):**
   - **DO NOT** type `sudo reboot` or `sudo shutdown`.
   - **Directly unplug the USB-C power supply / barrel jack cable from the Raspberry Pi.**
   - Wait 5 seconds.
   - Re-insert the power cable and allow the device to boot into Raspberry Pi OS.

3. **Post-Boot Verification Phase (Execute on Pi):**
   ```bash
   python3 -m scripts.pi.test_power_recovery --verify --db-path data/edge_production.db --output results/power_recovery_results.json
   ```
   *The script executes `PRAGMA integrity_check`, asserts that 100% of pre-power-cut audit entries exist with intact checksums, measures recovery time, and signs the verification record.*

---

## 5. Merging Results into Repository

Once benchmarks are completed on the Pi:

1. Copy the generated JSON files (or `results/pi_validation_bundle.json`) from the Pi to your workstation host:
   ```bash
   scp pi@raspberrypi.local:~/Edge-AI/results/pi_validation_bundle.json results/
   ```

2. Run the secure result importer on the host:
   ```bash
   python -m scripts.pi.import_results results/pi_validation_bundle.json
   ```
   *The importer verifies the HMAC/SHA-256 hardware telemetry signature, confirms `data_tag: REAL_HARDWARE`, and merges valid entries into `results/hardware_validation.json`.*

3. Generate publication tables:
   ```bash
   python -m scripts.pi.generate_paper_report --input results/hardware_validation.json
   ```
   *This outputs Markdown tables (`docs/research/HARDWARE_VALIDATION_TABLE.md`) and LaTeX source (`results/hardware_validation_table.tex`). Any test not run will be explicitly labeled `NOT_MEASURED`.*
