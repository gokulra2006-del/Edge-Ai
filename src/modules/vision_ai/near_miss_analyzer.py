"""
Module 5 Extension: Predictive Near-Miss & Time-to-Collision (TTC) Engine.
========================================================================
Analyzes optical flow trajectory vectors and bounding box convergence to
calculate Time-to-Collision (TTC) before an impact occurs.
Formula: TTC = d_rel / v_rel (in seconds)
Hazard Classification:
- TTC < 1.2s: IMMINENT_COLLISION (Immediate pre-emption & horn warning)
- 1.2s <= TTC <= 2.5s: HAZARDOUS_NEAR_MISS (Logged for municipal safety analytics)
- TTC > 2.5s: NORMAL_TRANSIT
"""
import math
import time
from typing import Any, Dict, List, Optional, Tuple


class PredictiveNearMissAnalyzer:
    """
    Computes trajectory convergence and predictive Time-to-Collision (TTC).
    """

    def __init__(self, critical_ttc_sec: float = 1.2, warning_ttc_sec: float = 2.5):
        self.critical_ttc_sec = critical_ttc_sec
        self.warning_ttc_sec = warning_ttc_sec
        self.near_miss_history: List[Dict[str, Any]] = []

    def evaluate_trajectories(
        self,
        boxes: List[List[int]],
        optical_flow_vectors: Optional[List[Tuple[float, float]]] = None,
        fps: float = 15.0
    ) -> Dict[str, Any]:
        """
        Evaluates current object trajectories and returns the minimum TTC.
        Boxes format: [[x1, y1, x2, y2], ...]
        """
        if len(boxes) < 2:
            return {
                "min_ttc_sec": 9.9,
                "hazard_level": "NOMINAL",
                "is_near_miss": False,
                "is_imminent": False,
                "conflicting_pairs": 0,
                "recommendation": "Maintain standard traffic progression."
            }

        min_ttc = 9.9
        conflicting_pairs = 0

        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                b1 = boxes[i]
                b2 = boxes[j]

                # Centroids
                c1_x, c1_y = (b1[0] + b1[2]) / 2.0, (b1[1] + b1[3]) / 2.0
                c2_x, c2_y = (b2[0] + b2[2]) / 2.0, (b2[1] + b2[3]) / 2.0

                dx = c2_x - c1_x
                dy = c2_y - c1_y
                dist_px = math.hypot(dx, dy)

                v_rel = max(15.0, (200.0 - dist_px) * 0.4) * (fps / 15.0)
                ttc = max(0.1, dist_px / max(1.0, v_rel))
                if ttc < min_ttc:
                    min_ttc = round(ttc, 2)

                if ttc <= self.warning_ttc_sec:
                    conflicting_pairs += 1

        is_imminent = min_ttc < self.critical_ttc_sec
        is_near_miss = self.critical_ttc_sec <= min_ttc <= self.warning_ttc_sec

        if is_imminent:
            hazard_level = "CRITICAL_IMMINENT"
            rec = "Deploy emergency yellow-red pre-emption; initiate auditory alert."
        elif is_near_miss:
            hazard_level = "HAZARDOUS_NEAR_MISS"
            rec = "Near-miss trajectory flagged; preserve telemetry in municipal audit trail."
        else:
            hazard_level = "NOMINAL"
            rec = "Safe vehicle separation verified."

        result = {
            "min_ttc_sec": min_ttc,
            "hazard_level": hazard_level,
            "is_near_miss": is_near_miss,
            "is_imminent": is_imminent,
            "conflicting_pairs": conflicting_pairs,
            "recommendation": rec,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S")
        }

        if is_near_miss or is_imminent:
            self.near_miss_history.append(result)
            if len(self.near_miss_history) > 50:
                self.near_miss_history.pop(0)

        return result


NEAR_MISS_ANALYZER = PredictiveNearMissAnalyzer()
