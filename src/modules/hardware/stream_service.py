"""Feature 10: Thread-safe, reconnecting Camera and Audio Streaming Services."""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple
import numpy as np

from src.modules.logging.logger import LOGGER

# Safe optional imports
try:
    import cv2
    OPENCV_AVAILABLE = True
except ImportError:
    cv2 = None
    OPENCV_AVAILABLE = False

try:
    import pyaudio
    PYAUDIO_AVAILABLE = True
except ImportError:
    pyaudio = None
    PYAUDIO_AVAILABLE = False


@dataclass
class StreamHealth:
    name: str
    status: str  # OK / DEGRADED / DOWN / UNKNOWN
    reason_code: str
    message: str
    fps: float
    last_frame_age_seconds: float
    reconnect_count: int
    source: str


class StreamService(ABC):
    """Common base for streaming capture services with thread-safety and auto-reconnect."""

    def __init__(self, name: str, reconnect_base: float = 1.0, reconnect_max: float = 16.0):
        self.name = name
        self.reconnect_base = reconnect_base
        self.reconnect_max = reconnect_max
        self.is_running = False
        self.reconnect_count = 0
        self.status = "DOWN"
        self.reason_code = "STOPPED"
        self.message = "Service not started"
        self.last_ts: Optional[float] = None
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()

    def start(self, source: Optional[str] = None) -> bool:
        with self._lock:
            if self.is_running:
                return True
            self.is_running = True
            self._stop_event.clear()
            self.status = "OK"
            self.reason_code = "STARTING"
            self.message = f"Starting {self.name} stream..."
            self._thread = threading.Thread(target=self._run_loop, daemon=True, name=f"Stream-{self.name}")
            self._thread.start()
            LOGGER.info(f"{self.name} stream service started.")
            return True

    def stop(self) -> bool:
        with self._lock:
            if not self.is_running:
                return True
            self.is_running = False
            self._stop_event.set()
            self.status = "DOWN"
            self.reason_code = "STOPPED"
            self.message = "Stream stopped by operator"
            if self._thread:
                self._thread.join(timeout=1.5)
            self._cleanup_source()
            LOGGER.info(f"{self.name} stream service stopped.")
            return True

    @abstractmethod
    def _run_loop(self) -> None:
        pass

    @abstractmethod
    def _cleanup_source(self) -> None:
        pass

    def get_health(self) -> StreamHealth:
        with self._lock:
            now = time.monotonic()
            age = (now - self.last_ts) if self.last_ts else 999.0
            return StreamHealth(
                name=self.name,
                status=self.status,
                reason_code=self.reason_code,
                message=self.message,
                fps=self._get_measured_fps(),
                last_frame_age_seconds=round(age, 2),
                reconnect_count=self.reconnect_count,
                source=getattr(self, "source", "unknown"),
            )

    @abstractmethod
    def _get_measured_fps(self) -> float:
        pass


class CameraService(StreamService):
    """
    Camera streaming with FPS throttling, bounded ring buffer that DROPS old frames,
    measured FPS/latency, and fallback support for file replay, webcam index, and RTSP.
    """

    def __init__(self, target_fps: float = 15.0, buffer_max: int = 2, default_source: str = "mock"):
        super().__init__("Camera")
        self.target_fps = target_fps
        self.buffer_max = buffer_max
        self.source = default_source
        self._frame_buffer = deque(maxlen=self.buffer_max)
        self._fps_history = deque(maxlen=30)
        self.cap = None

    def set_source(self, source: str) -> None:
        with self._lock:
            self.source = source
            if source not in ("mock", "simulation"):
                self.status = "DEGRADED"
                self.reason_code = "RECONNECTING"
            if self.is_running:
                self._cleanup_source()

    def _cleanup_source(self) -> None:
        if self.cap is not None:
            try:
                self.cap.release()
            except Exception:
                pass
            self.cap = None

    def _run_loop(self) -> None:
        frame_interval = 1.0 / max(1.0, self.target_fps)
        backoff = self.reconnect_base

        while not self._stop_event.is_set():
            # If using physical OpenCV camera but cv2 is missing:
            if self.source not in ("mock", "simulation") and not OPENCV_AVAILABLE:
                self.status = "DOWN"
                self.reason_code = "dependency_missing"
                self.message = "OpenCV (cv2) library not installed"
                time.sleep(1.0)
                continue

            # Produce frame according to source
            start_t = time.monotonic()
            frame = None

            if self.source in ("mock", "simulation"):
                # Fast mock generator
                frame = np.ones((360, 640, 3), dtype=np.uint8) * 35
                self.status = "OK"
                self.reason_code = "MOCK_ACTIVE"
                self.message = "File replay / simulation active"
            else:
                try:
                    if self.cap is None:
                        src_arg = int(self.source) if self.source.isdigit() else self.source
                        self.cap = cv2.VideoCapture(src_arg)
                        if not self.cap.isOpened():
                            raise RuntimeError(f"Unable to open video source {self.source}")
                    ret, raw_frame = self.cap.read()
                    if not ret or raw_frame is None:
                        raise RuntimeError("Failed to read frame from camera")
                    frame = raw_frame
                    self.status = "OK"
                    self.reason_code = "CAPTURING"
                    self.message = f"Connected to {self.source}"
                    backoff = self.reconnect_base
                except Exception as e:
                    self.reconnect_count += 1
                    self.status = "DEGRADED"
                    self.reason_code = "RECONNECTING"
                    self.message = f"Capture error: {e}. Backoff: {backoff:.1f}s"
                    self._cleanup_source()
                    time.sleep(backoff)
                    backoff = min(self.reconnect_max, backoff * 2.0)
                    continue

            # Latest-frame-wins: put in bounded buffer
            if frame is not None:
                self.last_ts = time.monotonic()
                self._frame_buffer.append((self.last_ts, frame))
                self._fps_history.append(self.last_ts)

            # FPS throttling
            elapsed = time.monotonic() - start_t
            sleep_time = frame_interval - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)

    def get_latest_frame(self) -> Optional[Tuple[float, np.ndarray]]:
        """Returns the newest frame, dropping older ones."""
        if self._frame_buffer:
            return self._frame_buffer[-1]
        return None

    def _get_measured_fps(self) -> float:
        if len(self._fps_history) < 2:
            return 0.0
        duration = self._fps_history[-1] - self._fps_history[0]
        if duration <= 0:
            return 0.0
        return round((len(self._fps_history) - 1) / duration, 1)


class AudioService(StreamService):
    """
    Audio streaming service generating overlapping fixed windows matching EdgeAcousticNet,
    with clipping and silence detection feeding input quality checks.
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        window_sec: float = 4.0,
        hop_sec: float = 2.0,
        ring_sec: float = 12.0,
        clipping_thresh: float = 0.98,
        silence_thresh: float = 0.005,
        default_source: str = "mock"
    ):
        super().__init__("Audio")
        self.sample_rate = sample_rate
        self.window_samples = int(sample_rate * window_sec)
        self.hop_samples = int(sample_rate * hop_sec)
        self.max_ring_samples = int(sample_rate * ring_sec)
        self.clipping_thresh = clipping_thresh
        self.silence_thresh = silence_thresh
        self.source = default_source
        self._ring_buffer = deque(maxlen=self.max_ring_samples)
        self._window_history = deque(maxlen=20)
        self.stream = None
        self.pa = None

    def set_source(self, source: str) -> None:
        with self._lock:
            self.source = source
            if self.is_running:
                self._cleanup_source()

    def _cleanup_source(self) -> None:
        if self.stream is not None:
            try:
                self.stream.stop_stream()
                self.stream.close()
            except Exception:
                pass
            self.stream = None
        if self.pa is not None:
            try:
                self.pa.terminate()
            except Exception:
                pass
            self.pa = None

    def _run_loop(self) -> None:
        backoff = self.reconnect_base
        chunk_size = 1024

        while not self._stop_event.is_set():
            if self.source not in ("mock", "simulation") and not PYAUDIO_AVAILABLE:
                self.status = "DOWN"
                self.reason_code = "dependency_missing"
                self.message = "PyAudio library not installed"
                time.sleep(1.0)
                continue

            if self.source in ("mock", "simulation"):
                # Mock synthetic audio chunk
                samples = (np.random.randn(chunk_size) * 0.02).astype(np.float32)
                self.status = "OK"
                self.reason_code = "MOCK_ACTIVE"
                self.message = "Mock audio stream running"
                time.sleep(chunk_size / self.sample_rate)
            else:
                try:
                    if self.pa is None:
                        self.pa = pyaudio.PyAudio()
                    if self.stream is None:
                        dev_idx = int(self.source) if self.source.isdigit() else None
                        self.stream = self.pa.open(
                            format=pyaudio.paInt16,
                            channels=1,
                            rate=self.sample_rate,
                            input=True,
                            input_device_index=dev_idx,
                            frames_per_buffer=chunk_size
                        )
                    raw_data = self.stream.read(chunk_size, exception_on_overflow=False)
                    samples = np.frombuffer(raw_data, dtype=np.int16).astype(np.float32) / 32768.0
                    self.status = "OK"
                    self.reason_code = "CAPTURING"
                    self.message = f"Audio capturing from device {self.source}"
                    backoff = self.reconnect_base
                except Exception as e:
                    self.reconnect_count += 1
                    self.status = "DEGRADED"
                    self.reason_code = "RECONNECTING"
                    self.message = f"Audio capture error: {e}. Backoff: {backoff:.1f}s"
                    self._cleanup_source()
                    time.sleep(backoff)
                    backoff = min(self.reconnect_max, backoff * 2.0)
                    continue

            # Append to ring buffer
            self._ring_buffer.extend(samples)
            self.last_ts = time.monotonic()
            self._window_history.append(self.last_ts)

    def get_latest_window(self) -> Optional[Dict[str, Any]]:
        """
        Extracts fixed-length window from ring buffer, detecting clipping & silence.
        """
        if len(self._ring_buffer) < self.window_samples:
            return None

        # Take last window_samples
        samples = np.array(list(self._ring_buffer)[-self.window_samples:], dtype=np.float32)
        rms = float(np.sqrt(np.mean(samples ** 2)))
        peak = float(np.max(np.abs(samples)))

        is_clipping = peak >= self.clipping_thresh
        is_silent = rms < self.silence_thresh

        pcm_bytes = (samples * 32767).astype(np.int16).tobytes()

        return {
            "pcm_bytes": pcm_bytes,
            "samples": samples,
            "rms": round(rms, 4),
            "peak": round(peak, 4),
            "is_clipping": is_clipping,
            "is_silent": is_silent,
            "timestamp": time.monotonic(),
        }

    def _get_measured_fps(self) -> float:
        if len(self._window_history) < 2:
            return 0.0
        duration = self._window_history[-1] - self._window_history[0]
        if duration <= 0:
            return 0.0
        return round((len(self._window_history) - 1) / duration, 1)


# Global instances for streaming pipeline
CAMERA_STREAM = CameraService()
AUDIO_STREAM = AudioService()
