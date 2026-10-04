#!/usr/bin/env python3
"""
Test 11: INMP441 I2S MEMS Microphone
====================================
Tests digital audio input over I2S on Raspberry Pi.

Wiring:
    - SCK / BCLK: GPIO 18 (Pin 12)
    - WS / LRCK:  GPIO 19 (Pin 35)
    - SD / DIN:   GPIO 20 (Pin 38)
    - L/R:        GND (Left channel) or VDD (Right channel)
    - VDD:        Pin 1 or 17 (3.3V)
    - GND:        Pin 20 or 39 (GND)

RPi Configuration:
    Requires I2S overlay in /boot/firmware/config.txt (or /boot/config.txt):
        dtoverlay=googlevoicehat-soundcard
    or
        dtoverlay=i2s-mmap

Run: python3 src/rpi/tests/test_11_inmp441.py
"""
import math
import os
import struct
import subprocess
import sys
import time

def test_inmp441():
    print("=" * 55)
    print("TEST 11: INMP441 I2S MEMS Microphone Capture")
    print("=" * 55)
    print("  Target Pins: SCK=GPIO18(P12), WS=GPIO19(P35), SD=GPIO20(P38)\n")

    # 1. Check ALSA capture devices
    print("  Checking ALSA audio capture devices (arecord -l)...")
    try:
        proc = subprocess.run(["arecord", "-l"], capture_output=True, text=True, timeout=5)
        print("  " + "\n  ".join(proc.stdout.strip().split("\n")[:8]))
        if "card" not in proc.stdout.lower():
            print("\n  No ALSA audio capture card detected.")
            print("  Verify /boot/firmware/config.txt has the I2S microphone overlay enabled.")
            print("  Example: dtoverlay=googlevoicehat-soundcard")
    except FileNotFoundError:
        print("  'arecord' tool not found (alsa-utils package).")
    except Exception as e:
        print(f"  ALSA query error: {e}")

    # 2. Test Audio Capture using PyAudio
    print("\n  Testing audio stream capture with PyAudio...")
    try:
        import pyaudio
        p = pyaudio.PyAudio()
    except ImportError:
        print("  pyaudio not installed. Install with: sudo apt-get install python3-pyaudio")
        print("\n  RESULT: FAIL (pyaudio library not found)")
        return

    device_index = None
    # Look for an input device containing 'i2s', 'voicehat', or default input
    info_count = p.get_device_count()
    for idx in range(info_count):
        dev = p.get_device_info_by_index(idx)
        if dev.get("maxInputChannels", 0) > 0:
            name = dev.get("name", "")
            print(f"    [Device {idx}] {name} (Inputs: {dev.get('maxInputChannels')})")
            if any(term in name.lower() for term in ("i2s", "voicehat", "snd_rpi", "mic")):
                device_index = idx

    if device_index is None and info_count > 0:
        # Fall back to default input device
        try:
            default_dev = p.get_default_input_device_info()
            device_index = default_dev.get("index")
            print(f"  Using default input device: {default_dev.get('name')}")
        except Exception:
            device_index = 0

    if device_index is None:
        p.terminate()
        print("\n  RESULT: NOT DETECTED (No audio input devices found)")
        return

    SAMPLE_RATE = 44100
    CHUNK_SIZE = 1024

    try:
        stream = p.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=SAMPLE_RATE,
            input=True,
            input_device_index=device_index,
            frames_per_buffer=CHUNK_SIZE
        )
        print("  Capturing 2 seconds of audio samples...")

        rms_values = []
        for _ in range(int(SAMPLE_RATE / CHUNK_SIZE * 2)):
            raw_data = stream.read(CHUNK_SIZE, exception_on_overflow=False)
            count = len(raw_data) // 2
            format_str = f"<{count}h"
            shorts = struct.unpack(format_str, raw_data)
            sum_squares = sum(s * s for s in shorts)
            rms = math.sqrt(sum_squares / count) if count > 0 else 0
            rms_values.append(rms)

        stream.stop_stream()
        stream.close()
        p.terminate()

        avg_rms = sum(rms_values) / len(rms_values) if rms_values else 0
        db_estimate = 20 * math.log10(avg_rms + 1e-6)

        print(f"\n  Average RMS Amplitude: {avg_rms:6.1f}")
        print(f"  Estimated Sound Level: {db_estimate:6.1f} dBFS")

        if avg_rms > 5.0:
            print("\n  RESULT: PASS (Microphone audio signal detected)")
        else:
            print("\n  RESULT: WARNING (Audio captured but near silence. Check wiring / mic gain).")

    except Exception as e:
        p.terminate()
        print(f"\n  Capture error: {e}")
        print("\n  RESULT: FAIL")

if __name__ == "__main__":
    test_inmp441()
