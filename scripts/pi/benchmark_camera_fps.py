#!/usr/bin/env python3
"""
scripts/pi/benchmark_camera_fps.py
Camera FPS and Ingestion Throughput Benchmark for Sentinel-AI on Raspberry Pi 4.
Outputs JSON results with measured FPS, inter-frame arrival jitter, and dropped frames.
"""

from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import sys
import time

# Ensure repo root is on path
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def run_benchmark(
    target_frames: int = 150,
    device_index: int = 0,
    target_fps: float = 15.0,
    use_mock: bool = False,
) -> dict:
    start_time = time.time()
    hostname = platform.node()

    has_cv2 = False
    cap = None
    source_type = "mock"

    if not use_mock:
        try:
            import cv2
            has_cv2 = True
            cap = cv2.VideoCapture(device_index)
            if cap.isOpened():
                source_type = f"/dev/video{device_index}"
            else:
                cap.release()
                cap = None
        except Exception:
            pass

    frame_intervals = []
    latencies = []
    last_frame_ts = time.monotonic()
    frames_captured = 0
    frames_dropped = 0
    expected_interval = 1.0 / target_fps

    start_bench = time.monotonic()

    for i in range(target_frames):
        iter_start = time.monotonic()
        frame_ok = False

        if cap and cap.isOpened():
            ret, _ = cap.read()
            if ret:
                frame_ok = True
            else:
                frames_dropped += 1
        else:
            # Mock frame ingestion matching target FPS
            time.sleep(expected_interval)
            frame_ok = True

        now = time.monotonic()
        interval = now - last_frame_ts
        last_frame_ts = now

        if frame_ok:
            frames_captured += 1
            if i > 0:
                frame_intervals.append(interval)
            latencies.append(now - iter_start)

    total_duration = round(time.monotonic() - start_bench, 3)

    if cap:
        try:
            cap.release()
        except Exception:
            pass

    actual_fps = round(frames_captured / total_duration, 2) if total_duration > 0 else 0.0
    avg_interval = round(sum(frame_intervals) / len(frame_intervals), 4) if frame_intervals else 0.0
    
    # Calculate jitter (variance from expected interval)
    jitter_ms = round(
        (sum(abs(iv - expected_interval) for iv in frame_intervals) / len(frame_intervals)) * 1000.0,
        2
    ) if frame_intervals else 0.0

    result = {
        "benchmark": "camera_fps",
        "target": "Raspberry Pi 4 Model B (4 GB)",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "host": hostname,
        "source": source_type,
        "parameters": {
            "target_frames": target_frames,
            "target_fps": target_fps,
            "expected_interval_ms": round(expected_interval * 1000, 2),
        },
        "summary": {
            "measured_fps": actual_fps,
            "total_frames_captured": frames_captured,
            "total_frames_dropped": frames_dropped,
            "duration_seconds": total_duration,
            "avg_interval_ms": round(avg_interval * 1000, 2),
            "frame_jitter_ms": jitter_ms,
            "status": "NOMINAL" if actual_fps >= (target_fps * 0.85) else "DEGRADED",
        },
    }
    return result


def main():
    parser = argparse.ArgumentParser(description="Sentinel-AI Camera FPS Benchmark")
    parser.add_argument("--frames", type=int, default=100, help="Number of frames to benchmark (default: 100)")
    parser.add_argument("--device", type=int, default=0, help="V4L2 Video device index (default: 0)")
    parser.add_argument("--fps", type=float, default=15.0, help="Target FPS (default: 15.0)")
    parser.add_argument("--mock", action="store_true", help="Force mock camera source")
    parser.add_argument("--out", type=str, default="", help="Path to write JSON output")
    args = parser.parse_args()

    res = run_benchmark(target_frames=args.frames, device_index=args.device, target_fps=args.fps, use_mock=args.mock)
    out_json = json.dumps(res, indent=2)

    if args.out:
        Path(args.out).write_text(out_json, encoding="utf-8")
        print(f"Results saved to {args.out}")
    else:
        print(out_json)


if __name__ == "__main__":
    main()
