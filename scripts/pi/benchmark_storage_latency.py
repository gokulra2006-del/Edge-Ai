#!/usr/bin/env python3
"""
scripts/pi/benchmark_storage_latency.py
MicroSD Storage Write and fsync Latency Benchmark for Sentinel-AI on Raspberry Pi 4.
Measures 4KB random sync page writes, 64KB sequential streaming, fsync delays, and IOPS.
"""

from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import random
import sys
import time

# Ensure repo root is on path
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    from scripts.pi.common import create_benchmark_header
except ImportError:
    from common import create_benchmark_header


def run_benchmark(
    target_dir: str = "data/test_tmp",
    random_4k_ops: int = 50,
    seq_64k_ops: int = 20,
) -> dict:
    hostname = platform.node()
    test_path = Path(target_dir)
    test_path.mkdir(parents=True, exist_ok=True)
    test_file = test_path / f"bench_io_{int(time.time())}.tmp"

    random_latencies_ms = []
    fsync_latencies_ms = []

    # 1. 4KB synchronous page writes (simulating SQLite commit)
    data_4k = os.urandom(4096)
    fd = os.open(str(test_file), os.O_CREAT | os.O_RDWR)
    try:
        for _ in range(random_4k_ops):
            pos = random.randint(0, 100) * 4096
            os.lseek(fd, pos, os.SEEK_SET)

            t0 = time.monotonic()
            os.write(fd, data_4k)
            t_write = (time.monotonic() - t0) * 1000.0

            t_fsync_start = time.monotonic()
            os.fsync(fd)
            t_fsync = (time.monotonic() - t_fsync_start) * 1000.0

            random_latencies_ms.append(t_write)
            fsync_latencies_ms.append(t_fsync)
    finally:
        os.close(fd)

    # 2. 64KB sequential writes (simulating media / evidence output)
    data_64k = os.urandom(65536)
    seq_file = test_path / f"bench_seq_{int(time.time())}.tmp"
    seq_start = time.monotonic()
    with open(seq_file, "wb") as f:
        for _ in range(seq_64k_ops):
            f.write(data_64k)
            f.flush()
            os.fsync(f.fileno())
    seq_duration = time.monotonic() - seq_start
    total_seq_bytes = seq_64k_ops * 65536
    seq_mb_per_sec = round((total_seq_bytes / (1024 * 1024)) / max(0.001, seq_duration), 2)

    # Cleanup temporary test files
    try:
        test_file.unlink(missing_ok=True)
        seq_file.unlink(missing_ok=True)
    except Exception:
        pass

    avg_fsync_ms = round(sum(fsync_latencies_ms) / len(fsync_latencies_ms), 2) if fsync_latencies_ms else 0.0
    max_fsync_ms = round(max(fsync_latencies_ms), 2) if fsync_latencies_ms else 0.0
    p95_fsync_ms = round(sorted(fsync_latencies_ms)[int(len(fsync_latencies_ms) * 0.95)], 2) if fsync_latencies_ms else 0.0

    iops_estimate = round(1000.0 / avg_fsync_ms, 1) if avg_fsync_ms > 0 else 0.0

    # Assessment: Pi microSD cards typically have fsync latency ~5-25ms.
    # Bad cards or wear out > 100ms.
    status = "EXCELLENT" if avg_fsync_ms < 15.0 else ("ACCEPTABLE" if avg_fsync_ms < 60.0 else "POOR_FLASH_PERFORMANCE")

    header = create_benchmark_header("microsd_write_latency", 0.0, repeatable=True)
    result = {
        "header": header,
        "benchmark": "microsd_write_latency",
        "target": "Raspberry Pi 4 Model B (4 GB)",
        "timestamp_utc": header["timestamp_utc"],
        "host": hostname,
        "parameters": {
            "random_4k_ops": random_4k_ops,
            "sequential_64k_ops": seq_64k_ops,
            "target_directory": str(test_path),
        },
        "summary": {
            "avg_fsync_latency_ms": avg_fsync_ms,
            "p95_fsync_latency_ms": p95_fsync_ms,
            "max_fsync_latency_ms": max_fsync_ms,
            "estimated_sync_iops": iops_estimate,
            "seq_write_mb_per_sec": seq_mb_per_sec,
            "performance_rating": status,
        },
    }
    return result


def main():
    parser = argparse.ArgumentParser(description="Sentinel-AI MicroSD Write Latency Benchmark")
    parser.add_argument("--dir", type=str, default="data/test_tmp", help="Target directory for benchmark files")
    parser.add_argument("--ops4k", type=int, default=50, help="Number of 4KB random sync ops (default: 50)")
    parser.add_argument("--ops64k", type=int, default=20, help="Number of 64KB sequential ops (default: 20)")
    parser.add_argument("--out", type=str, default="", help="Path to write JSON output")
    args = parser.parse_args()

    res = run_benchmark(target_dir=args.dir, random_4k_ops=args.ops4k, seq_64k_ops=args.ops64k)
    out_json = json.dumps(res, indent=2)

    if args.out:
        Path(args.out).write_text(out_json, encoding="utf-8")
        print(f"Results saved to {args.out}")
    else:
        print(out_json)


if __name__ == "__main__":
    main()
