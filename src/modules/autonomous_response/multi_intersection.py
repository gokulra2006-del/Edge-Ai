"""
Module 7 Extension: Municipal Multi-Intersection Coordination Grid.
===================================================================
Coordinates 4 municipal intersections:
- NODE_A: North Boulevard Approach
- NODE_B: Central Junction (Primary Sentinel Edge Node)
- NODE_C: Hospital Parkway Approach
- NODE_D: Emergency Ward Gate
Provides synchronized corridor clearing and cascaded perimeter isolation.
"""
import time
from typing import Any, Dict, List


class MunicipalIntersectionCoordinator:
    """
    Manages multi-node municipal intersection synchronization.
    """

    def __init__(self):
        self.nodes = {
            "NODE_A": {"name": "North Boulevard", "signal": "GREEN", "barrier": "OPEN", "status": "ONLINE", "offset_sec": 0},
            "NODE_B": {"name": "Central Junction (Edge Host)", "signal": "GREEN", "barrier": "OPEN", "status": "ONLINE", "offset_sec": 0},
            "NODE_C": {"name": "Hospital Parkway", "signal": "GREEN", "barrier": "OPEN", "status": "ONLINE", "offset_sec": 4},
            "NODE_D": {"name": "Emergency Gate", "signal": "GREEN", "barrier": "OPEN", "status": "ONLINE", "offset_sec": 8}
        }
        self.active_mode = "NORMAL"

    def get_grid_state(self) -> Dict[str, Any]:
        return {
            "mode": self.active_mode,
            "nodes": self.nodes,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S")
        }

    def set_emergency_preemption(self, affected_node: str = "NODE_B", mode: str = "ALL_RED"):
        self.active_mode = mode
        for nid, n in self.nodes.items():
            if mode == "ALL_RED":
                n["signal"] = "RED"
                n["barrier"] = "CLOSED" if nid == affected_node else "OPEN"
            elif mode == "GREEN_WAVE":
                n["signal"] = "GREEN"
                n["barrier"] = "OPEN"
            else:
                n["signal"] = "GREEN"
                n["barrier"] = "OPEN"

    def reset_grid(self):
        self.active_mode = "NORMAL"
        for n in self.nodes.values():
            n["signal"] = "GREEN"
            n["barrier"] = "OPEN"


MUNICIPAL_GRID = MunicipalIntersectionCoordinator()
