#!/usr/bin/env python3
"""
Test 13: Raspberry Pi Camera (CSI / V4L2)
=========================================
Tests camera capture capability via libcamera / rpicam or OpenCV.

Connection:
    - CSI camera ribbon cable plugged into CAMERA port on Raspberry Pi 4.
    - Blue backing tape facing the Ethernet/USB ports.

Run: python3 src/rpi/tests/test_13_camera.py
"""
import os
import subprocess
import sys
import time

def test_camera():
    print("=" * 50)
    print("TEST 13: Camera Interface Check")
    print("=" * 50)

    # 1. Check for /dev/video* devices
    v4l2_devices = [f"/dev/{f}" for f in os.listdir("/dev") if f.startswith("video")] if os.path.exists("/dev") else []
    print(f"  Detected V4L2 video nodes: {v4l2_devices if v4l2_devices else 'None'}")

    # 2. Try libcamera / rpicam command line tools (modern Raspberry Pi OS Bookworm/Bullseye)
    cam_cmd = None
    for cmd in ["rpicam-still", "libcamera-still"]:
        try:
            res = subprocess.run([cmd, "--list-cameras"], capture_output=True, text=True, timeout=5)
            if "available cameras" in res.stdout.lower() or "0 :" in res.stdout:
                cam_cmd = cmd
                print(f"  Camera utility found: {cmd}")
                print("  " + "\n  ".join(res.stdout.strip().split("\n")))
                break
        except FileNotFoundError:
            pass
        except Exception:
            pass

    if cam_cmd:
        print(f"\n  Capturing test image with {cam_cmd}...")
        test_img = "/tmp/sentinel_cam_test.jpg"
        try:
            cmd_args = [cam_cmd, "-o", test_img, "-t", "1000", "--width", "640", "--height", "480", "-n"]
            proc = subprocess.run(cmd_args, capture_output=True, text=True, timeout=10)
            if proc.returncode == 0 and os.path.exists(test_img) and os.path.getsize(test_img) > 1000:
                size_kb = os.path.getsize(test_img) / 1024.0
                print(f"  Frame captured successfully: {test_img} ({size_kb:.1f} KB)")
                print("\n  RESULT: PASS (CSI camera operational)")
                return
        except Exception as e:
            print(f"  Capture error: {e}")

    # 3. Fallback to OpenCV VideoCapture
    print("\n  Attempting capture via OpenCV VideoCapture...")
    try:
        import cv2
        cap = cv2.VideoCapture(0)
        if not cap.isOpened():
            print("  Cannot open /dev/video0 via OpenCV.")
            cap.release()
        else:
            ret, frame = cap.read()
            cap.release()
            if ret and frame is not None:
                h, w, c = frame.shape
                print(f"  Frame captured: {w}x{h} ({c} channels)")
                print("\n  RESULT: PASS (V4L2 camera operational)")
                return
    except ImportError:
        print("  OpenCV (cv2) not installed.")
    except Exception as e:
        print(f"  OpenCV error: {e}")

    print("\n  Camera not detected or failed to capture frame.")
    print("  Check ribbon cable orientation: contacts face HDMI port.")
    print("  Run 'rpicam-hello' to diagnose libcamera stack.")
    print("\n  RESULT: NOT DETECTED")

if __name__ == "__main__":
    test_camera()
