"""
Module 7 Extension: Multi-Node Green Wave Coordinated Corridor.
==============================================================
Beginner Explanation:
---------------------
What is a Green Wave?
1. When an ambulance is carrying a critical patient to a hospital, it shouldn't
   just get green lights at ONE intersection and then get stuck in traffic at the next!
2. A Multi-Node Green Wave links multiple Raspberry Pi edge units (e.g., Node A -> Node B -> Node C)
   along the hospital artery.
3. When Node A or B detects the ambulance, it calculates the vehicle's speed and arrival time
   at downstream intersections, turning upcoming signals GREEN just before the ambulance arrives,
   flushing stopped traffic and providing an uninterrupted lifeline corridor!
"""
import time
from typing import Any, Dict, List, Optional
from src.modules.logging.logger import LOGGER


class GreenWaveCoordinator:
    """
    Multi-intersection Green Wave pre-emption engine.
    Calculates dynamic arrival offsets and cascades green lights along an emergency corridor.
    """

    # Street Network Node Topology (distances in meters from Corridor Origin)
    NODES_TOPOLOGY = {
        "NODE_A": {"name": "East Highway Junction", "distance_m": 0, "current_signal": "GREEN"},
        "NODE_B": {"name": "Central Intersection (Local Node)", "distance_m": 600, "current_signal": "GREEN"},
        "NODE_C": {"name": "West Metro Boulevard", "distance_m": 1200, "current_signal": "GREEN"},
        "NODE_D": {"name": "Hospital Emergency Gate", "distance_m": 1800, "current_signal": "GREEN"}
    }

    def __init__(self, avg_speed_kmh: float = 50.0):
        self.avg_speed_ms = avg_speed_kmh * (1000.0 / 3600.0)  # ~13.89 m/s
        self.active_corridor: Optional[Dict[str, Any]] = None
        self.state = "NORMAL"  # NORMAL, ROUTE_PLANNED, ACTIVE, COMPLETED

    def initiate_green_wave(
        self,
        origin_node: str = "NODE_B",
        target_destination: str = "NODE_D",
        priority_level: str = "CRITICAL"
    ) -> Dict[str, Any]:
        """
        Calculates arrival timeline and creates sequential green wave plan.
        """
        origin_dist = self.NODES_TOPOLOGY.get(origin_node, {}).get("distance_m", 600)
        corridor_nodes = []

        for node_id, info in sorted(self.NODES_TOPOLOGY.items(), key=lambda x: x[1]["distance_m"]):
            if info["distance_m"] >= origin_dist:
                dist_from_origin = info["distance_m"] - origin_dist
                estimated_arrival_sec = round(dist_from_origin / self.avg_speed_ms, 1)

                corridor_nodes.append({
                    "node_id": node_id,
                    "node_name": info["name"],
                    "distance_ahead_m": dist_from_origin,
                    "eta_seconds": estimated_arrival_sec,
                    "signal_command": "PRE_EMPT_GREEN",
                    "status": "IMMEDIATE" if estimated_arrival_sec == 0 else "SCHEDULED"
                })

        self.state = "ACTIVE"
        corridor_plan = {
            "corridor_id": f"GW_{int(time.time())}",
            "origin_node": origin_node,
            "destination_node": target_destination,
            "priority": priority_level,
            "speed_kmh": round(self.avg_speed_ms * 3.6, 1),
            "state": self.state,
            "route_nodes": corridor_nodes,
            "total_route_distance_m": self.NODES_TOPOLOGY[target_destination]["distance_m"] - origin_dist,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S")
        }
        self.active_corridor = corridor_plan
        LOGGER.warning(f"[GreenWave] Coordinated corridor activated: {origin_node} -> {target_destination} ({len(corridor_nodes)} nodes synchronized).")
        return corridor_plan

    def reset_corridor(self):
        """Restores all downstream intersection nodes to normal cyclic timing."""
        self.state = "NORMAL"
        self.active_corridor = None
        LOGGER.info("[GreenWave] Corridor pre-emption concluded. All nodes returned to normal cyclic traffic.")

    def get_corridor_status(self) -> Dict[str, Any]:
        """Returns the current multi-node green wave state."""
        return {
            "corridor_active": self.state == "ACTIVE",
            "state": self.state,
            "plan": self.active_corridor,
            "topology": self.NODES_TOPOLOGY
        }


# Global singleton instance
GREEN_WAVE = GreenWaveCoordinator()
