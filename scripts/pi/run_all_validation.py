#!/usr/bin/env python3
"""
scripts/pi/run_all_validation.py
Master runner that executes all physical hardware benchmarks and validators
on Raspberry Pi 4, outputting a consolidated authenticated bundle JSON.
"""

from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.pi.common import create_benchmark_header, get_hardware_model, get_os_info, get_git_hash
import scripts.pi.benchmark_cpu_memory as bench_cpu
import scripts.pi.benchmark_thermal as bench_thermal
import scripts.pi.benchmark_camera_fps as bench_camera
import scripts.pi.benchmark_audio_latency as bench_audio
import scripts.pi.benchmark_sensor_contention as bench_bus
import scripts.pi.benchmark_storage_latency as bench_storage
import scripts.pi.test_network_recovery as test_net
import scripts.pi.test_power_recovery as test_pwr


def run_all_benchmarks(
    duration_scale: float = 1.0,
    output_bundle_path: Path | None = None,
) -> dict:
    start_time = time.monotonic()
    t_start_iso = datetime.now(timezone.utc).isoformat()
    bundle_header = create_benchmark_header("consolidated_pi_validation_bundle", 0.0, repeatable=True)

    print(f"===========================================================")
    print(f"Sentinel-AI Raspberry Pi Physical Hardware Validation Suite")
    print(f"Hardware: {bundle_header['hardware_model']}")
    print(f"OS:       {bundle_header['os']}")
    print(f"Git Hash: {bundle_header['git_hash'][:8]}")
    print(f"Timestamp:{bundle_header['timestamp_utc']}")
    print(f"===========================================================\n")

    benchmarks = {}

    # 1. CPU / Memory
    print("[1/8] Running Sustained CPU & Memory Benchmark...")
    cpu_dur = max(5, int(10 * duration_scale))
    benchmarks["cpu_memory"] = bench_cpu.run_benchmark(duration_seconds=cpu_dur)
    print(f"      Avg CPU: {benchmarks['cpu_memory']['summary']['cpu_percent_avg']}%, RSS: {benchmarks['cpu_memory']['summary']['process_rss_mb_avg']} MB\n")

    # 2. Thermal / Throttling
    print("[2/8] Running Thermal & Throttling Diagnostics...")
    benchmarks["thermal"] = bench_thermal.run_benchmark()
    print(f"      Temp: {benchmarks['thermal']['temperature_celsius']} °C, Status: {benchmarks['thermal']['status']}\n")

    # 3. Camera FPS
    print("[3/8] Running Camera FPS Throughput Benchmark...")
    cam_frames = max(30, int(100 * duration_scale))
    benchmarks["camera_fps"] = bench_camera.run_benchmark(target_frames=cam_frames, use_mock=False)
    print(f"      Measured: {benchmarks['camera_fps']['summary']['measured_fps']} FPS, Status: {benchmarks['camera_fps']['summary']['status']}\n")

    # 4. Audio Latency
    print("[4/8] Running Audio Window Latency Benchmark...")
    aud_dur = max(5, int(10 * duration_scale))
    benchmarks["audio_latency"] = bench_audio.run_benchmark(duration_seconds=aud_dur, use_mock=False)
    print(f"      Avg Latency: {benchmarks['audio_latency']['summary']['avg_processing_latency_ms']} ms, Dropped: {benchmarks['audio_latency']['summary']['windows_dropped']}\n")

    # 5. Bus Contention (I2C/SPI)
    print("[5/8] Running Sensor Bus Contention Benchmark...")
    benchmarks["sensor_bus"] = bench_bus.run_benchmark(concurrency=4, operations_per_thread=25)
    print(f"      Contention Rate: {benchmarks['sensor_bus']['summary']['contention_rate_pct']}%, Avg Wait: {benchmarks['sensor_bus']['summary']['avg_lock_wait_ms']} ms\n")

    # 6. MicroSD Write Latency
    print("[6/8] Running MicroSD Storage Write & fsync Benchmark...")
    benchmarks["storage_latency"] = bench_storage.run_benchmark(random_4k_ops=25, seq_64k_ops=10)
    print(f"      Avg fsync: {benchmarks['storage_latency']['summary']['avg_fsync_latency_ms']} ms, p95: {benchmarks['storage_latency']['summary']['p95_fsync_latency_ms']} ms\n")

    # 7. Network Outage Recovery
    print("[7/8] Running Network Outage Recovery Test...")
    benchmarks["network_recovery"] = test_net.run_network_recovery_benchmark(test_duration_seconds=5.0, generated_events=5)
    print(f"      Zero Dropped: {benchmarks['network_recovery']['metrics']['zero_dropped_events']}, Flush: {benchmarks['network_recovery']['metrics']['reconnection_flush_duration_seconds']}s\n")

    # 8. Power Interruption Verification
    print("[8/8] Checking Power Interruption Recovery & Database Integrity...")
    benchmarks["power_recovery"] = test_pwr.verify_power_recovery()
    pwr_metrics = benchmarks["power_recovery"].get("metrics", {})
    print(f"      SQLite Integrity: {pwr_metrics.get('sqlite_integrity_check')}, Lost Audit: {pwr_metrics.get('lost_audit_records_count')}\n")

    total_time = round(time.monotonic() - start_time, 2)
    bundle_header["duration_seconds"] = total_time

    bundle = {
        "bundle_header": bundle_header,
        "execution_summary": {
            "total_benchmarks_executed": len(benchmarks),
            "total_duration_seconds": total_time,
            "started_at": t_start_iso,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        },
        "benchmarks": benchmarks,
    }

    if output_bundle_path:
        out_p = Path(output_bundle_path)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        with open(out_p, "w", encoding="utf-8") as f:
            json.dump(bundle, f, indent=2)
        print(f"Validation bundle written to: {out_p}")

    return bundle


def main():
    parser = argparse.ArgumentParser(description="Sentinel-AI All-in-One Pi Validation Suite")
    parser.add_argument("--scale", type=float, default=1.0, help="Scale test durations (e.g. 0.5 for fast run)")
    parser.add_argument("--output", type=str, default="results/pi_validation_bundle.json", help="Path to write bundle JSON")
    args = parser.parse_args()

    run_all_benchmarks(duration_scale=args.scale, output_bundle_path=Path(args.output))


if __name__ == "__main__":
    main()
