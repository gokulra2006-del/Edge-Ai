"""
Module 3: Vision Preprocessor.
Handles edge camera frame scaling and format adaptation for Raspberry Pi 4.
"""
from typing import Tuple, Dict, Any


class VisionPreprocessor:
    def __init__(self, target_size: Tuple[int, int] = (320, 320)):
        self.target_size = target_size

    def preprocess_frame(self, frame_dims: Tuple[int, int, int] = (640, 480, 3)) -> Dict[str, Any]:
        """
        Simulates frame preprocessing: calculates scaling factor and letterboxing.
        Optimized for 320x320 on Raspberry Pi 4.
        """
        orig_w, orig_h, c = frame_dims
        scale_x = self.target_size[0] / orig_w
        scale_y = self.target_size[1] / orig_h
        return {
            "original_dims": frame_dims,
            "target_dims": self.target_size,
            "scale_factors": (scale_x, scale_y),
            "normalized": True
        }
