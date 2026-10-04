"""
Execution Entrypoint: End-to-End Edge-AI Pipeline Simulation.
Demonstrates the full 6-stage emergency response lifecycle on Raspberry Pi 4 architecture.
"""
import sys
import json
from pathlib import Path

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from src.core.orchestrator import EmergencyPipelineOrchestrator
from src.modules.sensors.simulator import SimulatedSensorHub


def print_banner(title: str):
    print("\n" + "=" * 70)
    print(f" {title.center(68)} ")
    print("=" * 70)


def run():
    orchestrator = EmergencyPipelineOrchestrator()
    hub = SimulatedSensorHub(node_id="NODE_B")

    # =========================================================================
    # SCENARIO 1: USER'S EXACT CAR ACCIDENT SPECIFICATION
    # =========================================================================
    print_banner("SCENARIO 1: ROAD ACCIDENT DETECTION (USER PROMPT SPECIFICATION)")
    print("Input Telemetry:")
    print("  audio_prediction  = {'class': 'crash', 'confidence': 0.87}")
    print("  vision_prediction = {'class': 'vehicle', 'confidence': 0.91}")
    print("  imu_prediction    = {'impact': True, 'confidence': 1.0}")
    print("  temperature       = 32.5 C")
    print("  smoke_level       = 120 ppm\n")

    packet_accident = hub.generate_packet(
        audio_class="crash",
        audio_conf=0.87,
        vision_class="vehicle",
        vision_conf=0.91,
        imu_impact=True,
        imu_g=4.2,
        temp_c=32.5,
        smoke_ppm=120.0
    )

    result_1 = orchestrator.process_packet(
        packet=packet_accident,
        node_confidence_matrix={"NODE_A": 0.62, "NODE_B": 0.94, "NODE_C": 0.76, "NODE_D": 0.31}
    )

    print("\n[PIPELINE OUTPUT]:")
    print(f"  --> event       = \"{result_1['event']}\"")
    print(f"  --> confidence  = {result_1['confidence']}")
    print(f"  --> is_verified = {result_1['is_verified']}")
    print(f"  --> severity    = \"{result_1['severity']}\" (Score: {result_1['severity_score']})")
    print(f"  --> location    = \"{result_1['location']}\" (via {result_1['primary_node']})")
    print(f"  --> response    = \"{result_1['action']}\" (Alert: {result_1['alert']})")

    # =========================================================================
    # SCENARIO 2: EMERGENCY VEHICLE (GREEN CORRIDOR PRIORITY)
    # =========================================================================
    print_banner("SCENARIO 2: AMBULANCE SIREN -> DYNAMIC GREEN CORRIDOR")
    packet_ambulance = hub.scenario_emergency_siren()
    result_2 = orchestrator.process_packet(packet_ambulance)

    print("\n[PIPELINE OUTPUT]:")
    print(f"  --> event          = \"{result_2['event']}\"")
    print(f"  --> confidence     = {result_2['confidence']}")
    print(f"  --> severity       = \"{result_2['severity']}\"")
    print(f"  --> green_corridor = {result_2['green_corridor']}")
    print(f"  --> response       = \"{result_2['action']}\"")

    # =========================================================================
    # SCENARIO 3: FIRE AND SMOKE EMERGENCY
    # =========================================================================
    print_banner("SCENARIO 3: FIRE & SMOKE HAZARD")
    packet_fire = hub.scenario_fire_hazard()
    result_3 = orchestrator.process_packet(packet_fire)

    print("\n[PIPELINE OUTPUT]:")
    print(f"  --> event       = \"{result_3['event']}\"")
    print(f"  --> confidence  = {result_3['confidence']}")
    print(f"  --> severity    = \"{result_3['severity']}\"")
    print(f"  --> response    = \"{result_3['action']}\"")

    # =========================================================================
    # SCENARIO 4: NORMAL URBAN TRAFFIC (BASELINE)
    # =========================================================================
    print_banner("SCENARIO 4: NORMAL URBAN TRAFFIC (FALSE POSITIVE SUPPRESSION)")
    packet_normal = hub.scenario_normal_traffic()
    result_4 = orchestrator.process_packet(packet_normal)

    print("\n[PIPELINE OUTPUT]:")
    print(f"  --> event       = \"{result_4['event']}\"")
    print(f"  --> severity    = \"{result_4['severity']}\"")
    print(f"  --> response    = \"{result_4['action']}\" (No intervention)")

    # =========================================================================
    # DATABASE QUERY VERIFICATION
    # =========================================================================
    print_banner("SQLITE DATABASE AUDIT TRAIL")
    recent = orchestrator.db.get_recent_events(limit=4)
    for r in recent:
        print(f"  Row #{r['id']} | {r['timestamp'].split('T')[-1][:8]} | {r['event_type']:<18} | Conf: {r['confidence']:.2f} | Sev: {r['severity_level']:<8} | Action: {r['traffic_signal_state']}")

    print("\nSimulation completed successfully!")


if __name__ == "__main__":
    run()
