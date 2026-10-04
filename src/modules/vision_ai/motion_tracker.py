"""
Module 3 Extension: Optical Flow & Vehicle Motion Crash Tracker.
================================================================
Beginner Explanation:
---------------------
Why Motion Tracking & Optical Flow?
1. Object detection (YOLO) alone only tells us "there is a car in this frame".
   It cannot tell if the car just slammed on the brakes or collided!
2. This module tracks vehicle centroids over time to compute:
   - Pixel Velocity: How fast the vehicle is moving across the camera's field of view.
   - Sudden Deceleration: A sudden drop in velocity (e.g., from 40 px/frame to 0).
   - Collision Overlap: When two vehicle bounding boxes rapidly converge and overlap.
   - Dense Optical Flow Anomaly: Chaotic pixel displacement across the crash area.
3. Combining these motion cues with the MPU-6050 accelerometer creates an
   extremely accurate, multi-modal crash confirmation score.
"""
import math
import time
from typing import Any, Dict, List, Optional, Tuple
import cv2
import numpy as np
from src.modules.logging.logger import LOGGER


class VehicleMotionTracker:
    """
    Lightweight optical flow and centroid motion tracker for detecting
    sudden vehicle deceleration, lane standstills, and collision events.
    """

    def __init__(self, max_history: int = 15, fps: float = 15.0):
        self.max_history = max_history
        self.fps = fps
        self.prev_gray: Optional[np.ndarray] = None

        # Tracks vehicle history: {vehicle_id: {"trajectory": [(x, y, t)], "speeds": [px/s]}}
        self.tracked_vehicles: Dict[int, Dict[str, Any]] = {}
        self.next_vehicle_id = 1
        self.last_crash_score = 0.0

    def update(
        self,
        frame: np.ndarray,
        detected_boxes: List[List[float]],
        imu_impact_score: float = 0.0
    ) -> Dict[str, Any]:
        """
        Processes a new camera frame and YOLO detection boxes to update motion metrics.
        Args:
            frame: BGR numpy image frame.
            detected_boxes: List of bounding boxes [[x1, y1, x2, y2], ...]
            imu_impact_score: Normalized MPU-6050 impact score (0.0 to 1.0)
        Returns:
            Dict containing motion analysis, deceleration scores, and crash probability.
        """
        now = time.time()
        w, h = frame.shape[1], frame.shape[0]

        # 1. Compute Dense Optical Flow Magnitude (Downsampled for Pi 4 CPU speed)
        small_frame = cv2.resize(frame, (160, 90), interpolation=cv2.INTER_AREA)
        gray = cv2.cvtColor(small_frame, cv2.COLOR_BGR2GRAY)

        optical_flow_anomaly = 0.0
        if self.prev_gray is not None:
            # OpenCV Farneback algorithm
            flow = cv2.calcOpticalFlowFarneback(
                self.prev_gray, gray, None,
                pyr_scale=0.5, levels=2, winsize=11,
                iterations=2, poly_n=5, poly_sigma=1.1, flags=0
            )
            mag, _ = cv2.cartToPolar(flow[..., 0], flow[..., 1])
            avg_flow_mag = float(np.mean(mag))
            # Normal traffic flow is 1.0 - 3.5; sudden crash/impact shock creates chaotic spikes > 6.0
            optical_flow_anomaly = min(1.0, max(0.0, (avg_flow_mag - 2.5) / 5.0))
        self.prev_gray = gray

        # 2. Centroid Tracking & Velocity Calculation
        current_centroids = []
        for box in detected_boxes:
            cx = (box[0] + box[2]) / 2.0
            cy = (box[1] + box[3]) / 2.0
            current_centroids.append((cx, cy, box))

        # Associate current centroids with tracked vehicle IDs
        active_ids = []
        max_deceleration_score = 0.0

        for cx, cy, box in current_centroids:
            matched_id = None
            min_dist = float("inf")

            for vid, data in self.tracked_vehicles.items():
                if vid in active_ids:
                    continue
                last_x, last_y, _ = data["trajectory"][-1]
                dist = math.hypot(cx - last_x, cy - last_y)
                # If within 80 pixels (reasonable displacement at 15 FPS)
                if dist < 80.0 and dist < min_dist:
                    min_dist = dist
                    matched_id = vid

            if matched_id is None:
                matched_id = self.next_vehicle_id
                self.next_vehicle_id += 1
                self.tracked_vehicles[matched_id] = {
                    "trajectory": [(cx, cy, now)],
                    "speeds": [0.0],
                    "box": box
                }
            else:
                data = self.tracked_vehicles[matched_id]
                prev_x, prev_y, prev_t = data["trajectory"][-1]
                dt = max(1e-4, now - prev_t)
                speed = math.hypot(cx - prev_x, cy - prev_y) / dt  # px/s

                # Check deceleration
                if len(data["speeds"]) > 0:
                    prev_speed = data["speeds"][-1]
                    speed_drop = prev_speed - speed
                    # Rapid deceleration threshold (e.g. > 150 px/s drop)
                    if speed_drop > 80.0:
                        decel_score = min(1.0, speed_drop / 250.0)
                        if decel_score > max_deceleration_score:
                            max_deceleration_score = decel_score

                data["trajectory"].append((cx, cy, now))
                data["speeds"].append(speed)
                data["box"] = box

                # Trim history
                if len(data["trajectory"]) > self.max_history:
                    data["trajectory"].pop(0)
                    data["speeds"].pop(0)

            active_ids.append(matched_id)

        # 3. Collision Proximity & Bounding Box Overlap Score
        collision_overlap_score = 0.0
        n_boxes = len(detected_boxes)
        for i in range(n_boxes):
            for j in range(i + 1, n_boxes):
                b1, b2 = detected_boxes[i], detected_boxes[j]
                iou = self._compute_iou(b1, b2)
                if iou > 0.15:  # High overlap between vehicles suggests crash contact
                    collision_overlap_score = max(collision_overlap_score, min(1.0, iou * 2.0))

        # 4. Composite Crash Probability Score
        # Formula: 0.35 * decel + 0.30 * collision + 0.20 * optical_flow + 0.15 * imu
        crash_score = (
            0.35 * max_deceleration_score +
            0.30 * collision_overlap_score +
            0.20 * optical_flow_anomaly +
            0.15 * imu_impact_score
        )
        self.last_crash_score = round(crash_score, 4)

        return {
            "tracked_vehicle_count": len(active_ids),
            "sudden_deceleration_score": round(max_deceleration_score, 4),
            "collision_overlap_score": round(collision_overlap_score, 4),
            "optical_flow_anomaly_score": round(optical_flow_anomaly, 4),
            "composite_crash_score": self.last_crash_score,
            "crash_visually_confirmed": self.last_crash_score >= 0.65
        }

    @staticmethod
    def _compute_iou(box1: List[float], box2: List[float]) -> float:
        """Calculates Intersection over Union (IoU) between two bounding boxes."""
        x1 = max(box1[0], box2[0])
        y1 = max(box1[1], box2[1])
        x2 = min(box1[2], box2[2])
        y2 = min(box1[3], box2[3])

        intersection = max(0.0, x2 - x1) * max(0.0, y2 - y1)
        area1 = max(0.0, box1[2] - box1[0]) * max(0.0, box1[3] - box1[1])
        area2 = max(0.0, box2[2] - box2[0]) * max(0.0, box2[3] - box2[1])
        union = area1 + area2 - intersection

        return intersection / union if union > 0 else 0.0


# Global singleton instance
MOTION_TRACKER = VehicleMotionTracker()
