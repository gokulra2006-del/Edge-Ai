# Sentinel-AI Raspberry Pi 4 Validation Guide (Phase 6I)

This guide provides step-by-step instructions for running the hardware validation suite on a physical Raspberry Pi 4 Model B.

---

## 1. Prerequisites on the Raspberry Pi

Ensure your Raspberry Pi is connected to your local network and running Raspberry Pi OS (Debian Bullseye/Bookworm 64-bit recommended).

### Install System Packages:
```bash
sudo apt update
sudo apt install -y python3 python3-pip python3-venv git v4l-utils libasound2-dev
```

---

## 2. Setting Up the Repository

### Clone or Pull the Code:
```bash
cd ~
git clone <your-repo-url> Edge-AI
cd Edge-AI
```

### Create and Activate Virtual Environment:
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

---

## 3. Running All Benchmarks in One Command

To run all 8 physical benchmarks sequentially and generate `results/pi_validation_bundle.json`:

```bash
python3 scripts/pi/run_all_validation.py --output results/pi_validation_bundle.json
```

Or for a faster benchmark run:
```bash
python3 scripts/pi/run_all_validation.py --scale 0.5 --output results/pi_validation_bundle.json
```

---

## 4. Running Individual Benchmarks

You can also run benchmarks individually:

### 1. CPU & Memory Usage
```bash
python3 scripts/pi/benchmark_cpu_memory.py --duration 30 --output results/pi_cpu_memory.json
```

### 2. Thermal & Throttling Check
```bash
python3 scripts/pi/benchmark_thermal.py --output results/pi_thermal.json
```

### 3. Camera FPS Throughput
```bash
python3 scripts/pi/benchmark_camera_fps.py --frames 100 --output results/pi_camera_fps.json
```

### 4. Audio Latency & Window Dropping
```bash
python3 scripts/pi/benchmark_audio_latency.py --duration 20 --output results/pi_audio_latency.json
```

### 5. I2C / SPI Bus Contention
```bash
python3 scripts/pi/benchmark_sensor_contention.py --threads 4 --ops 25 --output results/pi_sensor_contention.json
```

### 6. MicroSD Write & fsync Latency
```bash
python3 scripts/pi/benchmark_storage_latency.py --ops-4k 25 --ops-64k 10 --output results/pi_storage_latency.json
```

### 7. Network Outage & Recovery
```bash
python3 scripts/pi/test_network_recovery.py --duration 10 --output results/pi_network_recovery.json
```

### 8. Power Interruption Verification
```bash
python3 scripts/pi/test_power_recovery.py --output results/pi_power_recovery.json
```

---

## 5. Generating the Paper-Ready Table Report

Once the JSON outputs are created in `results/`, generate the Markdown table for the paper:

```bash
python3 scripts/pi/generate_paper_report.py --input-dir results --output results/pi_paper_table.md
```

---

## 6. Transferring Results Back to Windows

From your Windows machine, pull the generated JSON files:

```powershell
scp pi@<PI_IP>:~/Edge-AI/results/pi_*.json C:\Users\gokul\Desktop\PROJECTS\Edge-AI\results\
```

Then import and verify them (authenticates git hash and tags with `REAL_HARDWARE`):

```powershell
python scripts/pi/import_results.py --input-dir results --tag REAL_HARDWARE
```
