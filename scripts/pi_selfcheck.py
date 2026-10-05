#!/usr/bin/env python3
"""
pi_selfcheck.py - Hardware, Resource and Latency Self-Check for SENTINEL-AI.
Target: Raspberry Pi 4 (4GB RAM) deployment validation.
Can also execute on host development machines with unmeasured hardware disclaimers.
"""

import os
import sys
import time
import json
import sqlite3
import platform
import psutil

# Ensure project root is in path
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from src.modules.database.governed_store import IncidentRepository
from src.modules.assurance.device_health import safe_probe_pi_metrics, OfflineSyncOutbox
from src.modules.hardware.stream_service import CameraService, AudioService

def run_pi_selfcheck(duration_seconds: int = 60):
    print("=" * 70)
    print("  SENTINEL-AI EDGE NODE_B: HARDWARE & RESOURCE BENCHMARK SELF-CHECK")
    print("  Deployment Target: Raspberry Pi 4 Model B (4 GB RAM)")
    print(f"  Execution Host:    {platform.system()} {platform.release()} ({platform.machine()})")
    print(f"  Benchmark Run:     {duration_seconds} Seconds Mock Workload")
    print("=" * 70)

    is_linux = platform.system() == "Linux"
    is_arm = "arm" in platform.machine().lower() or "aarch64" in platform.machine().lower()

    if not (is_linux and is_arm):
        print("\n[NOTE / DISCLAIMER]")
        print("  Running on non-ARM / non-Linux host environment (Windows/x86_64).")
        print("  Pi-specific VCGENCMD thermal and throttling sensors report UNAVAILABLE.")
        print("  Pi 4 hardware numbers are stated as UNMEASURED until run on physical Pi hardware.")
        print("=" * 70)

    # Initial hardware probe
    pi_metrics = safe_probe_pi_metrics()
    print(f"\nInitial CPU Temperature: {pi_metrics.get('cpu_temp_c') or 'UNAVAILABLE'}")
    print(f"Initial Throttling Stat: {pi_metrics.get('throttled') or 'UNAVAILABLE'}")

    # Initialize store and services
    db_path = os.path.join(REPO_ROOT, "data", "test_selfcheck.db")
    if os.path.exists(db_path):
        try: os.remove(db_path)
        except Exception: pass

    store = IncidentRepository(db_path=db_path)
    outbox = OfflineSyncOutbox(repository=store)

    camera = CameraService(target_fps=15, default_source="mock")
    audio = AudioService(sample_rate=16000, default_source="mock")

    camera.start()
    audio.start()

    proc = psutil.Process(os.getpid())
    start_time = time.monotonic()
    
    frame_count = 0
    inference_latencies = []
    db_write_latencies = []
    peak_rss_mb = 0.0

    print(f"\nCommencing {duration_seconds}-second benchmark loop...")
    iteration = 0

    while time.monotonic() - start_time < duration_seconds:
        loop_start = time.monotonic()
        iteration += 1

        # 1. Pull stream data
        frame = camera.get_latest_frame()
        if frame is not None:
            frame_count += 1
        
        window = audio.get_latest_window()

        # 2. Simulate inference pass
        t0 = time.monotonic()
        # Mock lightweight tensor math / inference
        _ = sum(i * 0.001 for i in range(10000))
        t1 = time.monotonic()
        inference_latencies.append((t1 - t0) * 1000.0)

        # 3. Simulate DB write & outbox queue
        t_w0 = time.monotonic()
        if iteration % 5 == 0:
            outbox.enqueue(
                idempotency_key=f"check-telemetry-{iteration}",
                target="firebase",
                payload_type="TELEMETRY",
                payload={"sample": iteration, "temp": 42.1},
                priority="LOW"
            )
            store.create_incident(
                event_type="PERIODIC_CHECK",
                zone_id="Zone B",
                assurance_level="FULL"
            )
        t_w1 = time.monotonic()
        db_write_latencies.append((t_w1 - t_w0) * 1000.0)

        # Track memory RSS
        rss_mb = proc.memory_info().rss / (1024 * 1024)
        if rss_mb > peak_rss_mb:
            peak_rss_mb = rss_mb

        # Loop throttle (~30 ms target tick)
        elapsed = time.monotonic() - loop_start
        if elapsed < 0.033:
            time.sleep(0.033 - elapsed)

    total_duration = time.monotonic() - start_time

    # Cleanup services
    camera.stop()
    audio.stop()

    avg_inf_ms = sum(inference_latencies) / len(inference_latencies) if inference_latencies else 0.0
    p95_inf_ms = sorted(inference_latencies)[int(len(inference_latencies) * 0.95)] if inference_latencies else 0.0
    avg_db_ms = sum(db_write_latencies) / len(db_write_latencies) if db_write_latencies else 0.0
    p95_db_ms = sorted(db_write_latencies)[int(len(db_write_latencies) * 0.95)] if db_write_latencies else 0.0
    measured_fps = frame_count / total_duration if total_duration > 0 else 0.0

    outbox_stats = outbox.status_summary()

    print("\n" + "=" * 70)
    print("                    BENCHMARK RESULTS & METRICS")
    print("=" * 70)
    print(f"Elapsed Time:               {total_duration:.2f} s")
    print(f"Total Iterations:           {iteration}")
    print(f"Frames Ingested:            {frame_count} ({measured_fps:.2f} FPS)")
    print(f"Peak Process RSS Memory:    {peak_rss_mb:.2f} MB  (Pi Budget: < 1500 MB)")
    print(f"CPU Utilization (Process):  {proc.cpu_percent():.1f} %")
    print(f"Inference Latency (Avg):    {avg_inf_ms:.2f} ms")
    print(f"Inference Latency (P95):    {p95_inf_ms:.2f} ms")
    print(f"DB Write Latency (Avg):     {avg_db_ms:.2f} ms")
    print(f"DB Write Latency (P95):     {p95_db_ms:.2f} ms")
    print(f"Sync Outbox State:          {outbox_stats}")
    print("=" * 70)

    # Verification checks
    within_memory_budget = peak_rss_mb < 1500.0
    fps_acceptable = measured_fps > 5.0
    db_latency_acceptable = p95_db_ms < 50.0

    print("\nRESOURCE CRITERIA VERIFICATION:")
    print(f"  [x] Memory within budget (<1.5GB): {'PASSED' if within_memory_budget else 'FAILED'} ({peak_rss_mb:.1f} MB)")
    print(f"  [x] Stream ingestion operational:  {'PASSED' if fps_acceptable else 'FAILED'} ({measured_fps:.1f} FPS)")
    print(f"  [x] DB write queue responsive:     {'PASSED' if db_latency_acceptable else 'FAILED'} ({p95_db_ms:.2f} ms P95)")

    if not (is_linux and is_arm):
        print("\nUNVALIDATED UNTIL RUN ON PI 4 HARDWARE:")
        print("  - Broadcom BCM2711 VideoCore VI H.264 camera hardware decoding latency")
        print("  - Physical I2C/SPI sensor polling latency and bus jitter")
        print("  - Thermal throttling under sustained multi-class inference")
        print("  - MicroSD card random 4K write IOPS and WAL checkpoint latency")

    print("=" * 70)

if __name__ == "__main__":
    dur = 5 if len(sys.argv) > 1 and sys.argv[1] == "--quick" else 60
    run_pi_selfcheck(duration_seconds=dur)
