"""
Module 13: Blackbox Video DVR & Pre-Event Incident Recorder.
============================================================
Beginner Explanation:
---------------------
Why a Blackbox DVR?
1. In aviation and modern high-end vehicles, a blackbox keeps a continuous record
   of the moments leading up to a disaster.
2. Standard video recording requires massive hard drive space.
3. This module maintains a rolling memory buffer (using a circular FIFO queue)
   storing the last 15 seconds of camera frames in RAM.
4. When an emergency (collision crash or fire) is triggered:
   - It captures the buffered pre-event frames (the moments BEFORE the crash).
   - It records an additional 5-10 seconds of post-event frames.
   - It compiles them into a standard MP4 video file and saves it in data/recordings/.
   - The video is immediately playable on the Web Dashboard and accessible via cloud!
"""
from collections import deque
import os
from pathlib import Path
import threading
import time
from typing import Deque, List, Optional
import cv2
import numpy as np

from src.modules.logging.logger import LOGGER

BASE_DIR = Path(__file__).resolve().parents[3]
RECORDINGS_DIR = BASE_DIR / "data" / "recordings"
RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)


class BlackboxDVR:
    """
    Rolling circular video buffer that automatically extracts and encodes
    pre-event and post-event incident clips upon emergency trigger.
    """

    def __init__(self, buffer_seconds: int = 15, fps: int = 15, frame_size=(640, 360)):
        self.buffer_seconds = buffer_seconds
        self.fps = fps
        self.frame_size = frame_size
        self.max_buffer_frames = buffer_seconds * fps

        # Thread-safe circular deque buffer in RAM
        self._buffer: Deque[np.ndarray] = deque(maxlen=self.max_buffer_frames)
        self._lock = threading.Lock()
        self._is_recording_incident = False
        self.recordings_history: List[dict] = []

        LOGGER.info(f"BlackboxDVR initialized (Buffer: {buffer_seconds}s @ {fps} FPS, Resolution: {frame_size[0]}x{frame_size[1]})")

    def add_frame(self, frame: np.ndarray):
        """Adds an incoming camera frame to the rolling circular buffer."""
        if frame is None:
            return

        # Resize to standardized low-compute resolution if needed
        if (frame.shape[1], frame.shape[0]) != self.frame_size:
            resized = cv2.resize(frame, self.frame_size, interpolation=cv2.INTER_AREA)
        else:
            resized = frame.copy()

        with self._lock:
            self._buffer.append(resized)

    def trigger_incident_capture(self, incident_id: str, event_type: str, post_event_seconds: int = 5) -> str:
        """
        Extracts pre-event buffer and captures post-event frames asynchronously.
        Returns:
            str: Expected filename of the saved incident video.
        """
        timestamp_str = time.strftime("%Y%m%d_%H%M%S")
        video_filename = f"incident_{incident_id}_{event_type.lower()}_{timestamp_str}.mp4"
        output_filepath = RECORDINGS_DIR / video_filename

        # Snapshot current pre-event buffer
        with self._lock:
            pre_event_frames = list(self._buffer)

        # Launch background worker to collect post-event frames and encode video
        worker = threading.Thread(
            target=self._encode_incident_video,
            args=(pre_event_frames, str(output_filepath), post_event_seconds, incident_id, event_type),
            daemon=True,
            name=f"DVR-Worker-{incident_id}"
        )
        worker.start()
        return video_filename

    def _encode_incident_video(
        self,
        pre_frames: List[np.ndarray],
        output_path: str,
        post_seconds: int,
        incident_id: str,
        event_type: str
    ):
        """Asynchronous worker that gathers post-event frames and writes MP4."""
        LOGGER.info(f"[BlackboxDVR] Recording incident clip: {incident_id} ({event_type}). Pre-frames: {len(pre_frames)}")

        # Wait to capture post-event frames
        post_frames = []
        frames_to_capture = post_seconds * self.fps
        sleep_step = 1.0 / self.fps

        for _ in range(frames_to_capture):
            with self._lock:
                if len(self._buffer) > 0:
                    post_frames.append(self._buffer[-1].copy())
            time.sleep(sleep_step)

        all_frames = pre_frames + post_frames

        # If buffer was empty (e.g. at startup or simulation), generate synthetic watermark clip
        if not all_frames:
            all_frames = self._generate_synthetic_clip(incident_id, event_type, count=self.fps * 4)

        try:
            # MP4V codec provides universal compatibility across browsers
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            out = cv2.VideoWriter(output_path, fourcc, self.fps, self.frame_size)

            for idx, frame in enumerate(all_frames):
                # Annotate emergency timestamp & incident ID overlay
                annotated = frame.copy()
                cv2.rectangle(annotated, (10, 10), (320, 50), (0, 0, 0), -1)
                cv2.putText(
                    annotated,
                    f"BLACKBOX: {incident_id} | {event_type}",
                    (15, 35),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.5,
                    (0, 0, 255) if event_type in ("ACCIDENT", "FIRE") else (0, 255, 0),
                    1
                )
                out.write(annotated)

            out.release()
            file_size_kb = round(os.path.getsize(output_path) / 1024, 1)
            LOGGER.info(f"[BlackboxDVR] Successfully saved video: {output_path} ({file_size_kb} KB, {len(all_frames)} frames)")

            record_meta = {
                "incident_id": incident_id,
                "event_type": event_type,
                "filename": os.path.basename(output_path),
                "filepath": output_path,
                "size_kb": file_size_kb,
                "frame_count": len(all_frames),
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S")
            }
            self.recordings_history.append(record_meta)

        except Exception as e:
            LOGGER.error(f"[BlackboxDVR] Encoding error: {e}")

    def _generate_synthetic_clip(self, incident_id: str, event_type: str, count: int = 60) -> List[np.ndarray]:
        """Generates clean simulation frames when no live camera feed is present."""
        frames = []
        w, h = self.frame_size

        for i in range(count):
            frame = np.ones((h, w, 3), dtype=np.uint8) * 35  # Dark slate background
            # Draw road lane markings
            cv2.line(frame, (0, h // 2), (w, h // 2), (255, 255, 255), 2)
            cv2.putText(frame, "INCIDENT DVR SIMULATION STREAM", (w // 4, h // 3), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
            cv2.putText(frame, f"EVENT: {event_type} | ID: {incident_id}", (w // 4, h // 2 + 40), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 140, 255), 2)
            cv2.putText(frame, f"FRAME: {i+1}/{count}", (w // 4, h // 2 + 80), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (180, 180, 180), 1)
            frames.append(frame)
        return frames

    def list_recordings(self) -> List[dict]:
        """Returns list of all available blackbox recordings on disk."""
        files = []
        for f in RECORDINGS_DIR.glob("*.mp4"):
            files.append({
                "filename": f.name,
                "size_kb": round(f.stat().st_size / 1024, 1),
                "modified": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(f.stat().st_mtime))
            })
        return sorted(files, key=lambda x: x["modified"], reverse=True)


# Global singleton DVR instance
DVR = BlackboxDVR()
