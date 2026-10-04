"""
Hardware Driver: Raspberry Pi CSI / V4L2 Camera Interface.
==========================================================
Interface: Dedicated Raspberry Pi Camera Ribbon Connector (CSI) or /dev/video0

Captures live video frames for YOLO11 inference and forensic blackbox buffer.
Does not assume a generic USB webcam.
"""
import os
import time
from typing import Any, Dict, Optional
import numpy as np
from src.modules.hardware.base_driver import BaseHardwareDriver, DriverStatus
from src.config.hardware_config import HARDWARE_CONFIG


class RaspberryPiCameraDriver(BaseHardwareDriver):
    def __init__(self):
        super().__init__("PiCamera_CSI", "Computer_Vision_Optical_Sensor")
        self.device_path = HARDWARE_CONFIG.camera_device
        self._cap = None
        self._picam2 = None
        self.fps = 15.0
        self.resolution = (640, 480)
        self.initialize()

    def initialize(self) -> bool:
        # Check native Pi Camera picamera2 / libcamera
        try:
            from picamera2 import Picamera2
            self._picam2 = Picamera2()
            config = self._picam2.create_video_configuration(main={"size": self.resolution, "format": "RGB888"})
            self._picam2.configure(config)
            self._picam2.start()
            self.status = DriverStatus.ONLINE
            self.is_simulated = False
            self.error_message = None
            return True
        except Exception:
            pass

        # Check standard Linux V4L2 interface (/dev/video0)
        if os.path.exists(self.device_path):
            try:
                import cv2
                self._cap = cv2.VideoCapture(self.device_path)
                if self._cap.isOpened():
                    self.status = DriverStatus.ONLINE
                    self.is_simulated = False
                    self.error_message = None
                    return True
            except Exception:
                pass

        self.status = DriverStatus.SIMULATED
        self.is_simulated = True
        self.error_message = f"Camera device {self.device_path} not found. Running in simulation fallback."
        return False

    def capture_frame(self) -> Optional[np.ndarray]:
        if not self.is_simulated:
            if self._picam2:
                try:
                    return self._picam2.capture_array()
                except Exception:
                    pass
            elif self._cap and self._cap.isOpened():
                try:
                    ret, frame = self._cap.read()
                    if ret:
                        return frame
                except Exception:
                    pass

        # Return simulated test pattern
        h, w = self.resolution
        frame = np.zeros((h, w, 3), dtype=np.uint8)
        frame[:, :] = (35, 45, 55)
        return frame

    def read(self) -> Dict[str, Any]:
        self.read_count += 1
        now = time.time()
        now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))

        return {
            "resolution": f"{self.resolution[0]}x{self.resolution[1]}",
            "fps": self.fps,
            "interface": "RaspberryPi_CSI_libcamera",
            "device": self.device_path,
            "timestamp": now_iso,
            "quality": {
                "status": self.status.value,
                "is_simulated": self.is_simulated,
                "source": "physical_csi_camera" if not self.is_simulated else "simulated_camera"
            }
        }

    def cleanup(self):
        if self._picam2:
            try:
                self._picam2.stop()
            except Exception:
                pass
        if self._cap:
            try:
                self._cap.release()
            except Exception:
                pass
