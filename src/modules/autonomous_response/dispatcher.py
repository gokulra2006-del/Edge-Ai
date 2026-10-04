"""
Module 7: Autonomous Response Dispatcher.
Executes autonomous actions:
- Emergency Green Corridor (Traffic signal priority for Ambulance/Fire)
- Lane restriction & warning alerts for accidents
- Fire hazard dispatch & safety perimeter control
(Software interface: prints/logs actions; ready to bind GPIO pins later).
"""
from src.core.data_models import FusedEvent, SeverityAssessment, LocationEstimate, ResponseAction
from src.modules.logging.logger import LOGGER


class AutonomousResponseDispatcher:
    def __init__(self):
        LOGGER.info("AutonomousResponseDispatcher initialized (Hardware GPIO abstracted in software mock)")

    def dispatch(
        self,
        event: FusedEvent,
        severity: SeverityAssessment,
        location: LocationEstimate
    ) -> ResponseAction:
        """
        Determines and triggers autonomous responses based on event, severity, and zone.
        """
        etype = event.event_type
        level = severity.level
        zone = location.probable_zone

        # Default normal state
        traffic_signal = "NORMAL_CYCLIC_PLAN"
        green_corridor = False
        lane_restricted = None
        alert_type = "NONE"
        warning_leds = False
        buzzer = False

        # --- RESPONSE 1: EMERGENCY GREEN CORRIDOR ---
        if etype == "EMERGENCY_VEHICLE":
            traffic_signal = f"GREEN_CORRIDOR_{zone}"
            green_corridor = True
            alert_type = f"PRIORITY_ROUTE_{event.raw_packet.audio_prediction.class_name.upper()}"
            warning_leds = True
            LOGGER.warning(f"[AUTONOMOUS ACTION] >>> EMERGENCY GREEN CORRIDOR ACTIVATED <<< Route: {zone} -> GREEN")

        # --- RESPONSE 2: ACCIDENT RESPONSE ---
        elif etype == "ACCIDENT":
            lane_restricted = f"{zone}_LANE_2"
            traffic_signal = "RESTRICT_AFFECTED_LANE_AND_SLOW"
            alert_type = "DISPATCH_EMERGENCY_AMBULANCE_POLICE"
            warning_leds = True
            buzzer = True
            LOGGER.error(f"[AUTONOMOUS ACTION] >>> ACCIDENT INTERVENTION <<< Restrict: {lane_restricted} | Alert: {alert_type}")

        # --- RESPONSE 3: FIRE HAZARD ---
        elif etype == "FIRE_HAZARD":
            traffic_signal = "HALT_APPROACHING_TRAFFIC_ALL_RED"
            alert_type = "DISPATCH_FIRE_SERVICES"
            warning_leds = True
            buzzer = True
            LOGGER.error(f"[AUTONOMOUS ACTION] >>> FIRE PERIMETER RESPONSE <<< Zone: {zone} -> ALL RED STOP")

        # --- RESPONSE 4: ROAD HAZARD ---
        elif etype == "ROAD_HAZARD":
            traffic_signal = "CAUTION_SPEED_ADVISORY"
            alert_type = "ROAD_MAINTENANCE_ADVISORY"
            warning_leds = True
            LOGGER.info(f"[AUTONOMOUS ACTION] Road hazard advisory posted for {zone}")

        else:
            LOGGER.info("[AUTONOMOUS ACTION] Standard operating state maintained.")

        action = ResponseAction(
            traffic_signal_state=traffic_signal,
            green_corridor_active=green_corridor,
            lane_restricted=lane_restricted,
            alert_type=alert_type,
            warning_leds_active=warning_leds,
            buzzer_active=buzzer
        )
        return action
