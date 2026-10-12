"""Verify INMP441 capture and the deployed audio preprocessing on Raspberry Pi.

Run from the repository root:
    python3 scripts/pi/verify_audio_pipeline.py --seconds 4
"""
from __future__ import annotations

import argparse
import math
import wave
from pathlib import Path

import numpy as np

from src.modules.audio_ai.classifier import AudioClassifier


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=float, default=4.0)
    parser.add_argument("--output", default="reports/inmp441_test.wav")
    args = parser.parse_args()

    try:
        import pyaudio
    except ImportError:
        print("FAIL: install PyAudio first: sudo apt install -y python3-pyaudio")
        return 2

    rate = 16000
    chunk = 1024
    frames = []
    pa = pyaudio.PyAudio()
    stream = None
    try:
        inputs = []
        for i in range(pa.get_device_count()):
            info = pa.get_device_info_by_index(i)
            if info.get("maxInputChannels", 0) > 0:
                inputs.append((i, info.get("name", "unknown")))
        print("Input devices:", inputs)
        if not inputs:
            print("FAIL: no capture device found; check I2S overlay and wiring")
            return 2

        stream = pa.open(format=pyaudio.paInt16, channels=1, rate=rate,
                         input=True, input_device_index=inputs[0][0],
                         frames_per_buffer=chunk)
        for _ in range(max(1, math.ceil(rate * args.seconds / chunk))):
            frames.append(stream.read(chunk, exception_on_overflow=False))
    finally:
        if stream is not None:
            stream.stop_stream()
            stream.close()
        pa.terminate()

    pcm = b"".join(frames)
    samples = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
    rms = float(np.sqrt(np.mean(samples * samples))) if len(samples) else 0.0
    peak = float(np.max(np.abs(samples))) if len(samples) else 0.0
    clipped = float(np.mean(np.abs(samples) >= 0.98)) if len(samples) else 1.0
    print(f"Capture: {len(samples)} samples at {rate} Hz")
    print(f"Signal: RMS={rms:.5f}, peak={peak:.5f}, clipped={clipped:.2%}")

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(output), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(pcm)
    print(f"Saved recording: {output}")

    if rms < 0.005:
        print("FAIL: microphone is effectively silent; check SD, WS, SCK, power, and I2S overlay")
        return 1
    if clipped > 0.01:
        print("FAIL: input is clipping; reduce microphone/input gain")
        return 1

    prediction = AudioClassifier().predict_pcm(pcm, sample_rate=rate)
    print(f"Prediction: {prediction.class_name} ({prediction.confidence:.1%})")
    print("PASS: capture and software preprocessing are operational")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
