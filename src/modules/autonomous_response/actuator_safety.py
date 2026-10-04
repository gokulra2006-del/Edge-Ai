"""
Module 7 Hardware Safety: Actuator Safety State Machine & Watchdog Controller.
=============================================================================
Enforces deterministic safety states:
- NORMAL: Standard traffic green cycling, open barriers.
- WARNING: Approaching near-miss or early sensor hazard, amber warning.
- ALL_RED: Collision or fire verified; all incoming approaches halted.
- BARRIER_LOCKDOWN: Access barriers closed to isolate incident zone.
- EMERGENCY: Multi-node green corridor engaged for emergency vehicle.
- MANUAL_OVERRIDE: Commander/Operator manual control with expiration lease.
- SAFE_SHUTDOWN: Fail-safe state (flashing amber or safe defaults on loss of heartbeat).
"""
from enum import Enum
import time
from typing import Any, Dict, Optional
from src.modules.logging.logger import LOGGER


class SafetyState(str, Enum):
    NORMAL = "NORMAL"
    WARNING = "WARNING"
    ALL_RED = "ALL_RED"
    BARRIER_LOCKDOWN = "BARRIER_LOCKDOWN"
    EMERGENCY = "EMERGENCY"
    MANUAL_OVERRIDE = "MANUAL_OVERRIDE"
    SAFE_SHUTDOWN = "SAFE_SHUTDOWN"


class ActuatorSafetyManager:
    """
    Finite State Machine for actuator control with timeout lease watchdogs.
    """

    def __init__(self, override_timeout_sec: int = 30):
        self.current_state = SafetyState.NORMAL
        self.override_timeout_sec = override_timeout_sec
        self.override_expiry_time = 0.0
        self.operator_actor = "SYSTEM_AUTOMATION"
        self.actuator_outputs = {
            "traffic_signal": "GREEN",
            "barrier": "OPEN",
            "buzzer": "OFF"
        }

    def request_transition(
        self,
        target_state: SafetyState,
        actor_role: str = "COMMANDER",
        actor_name: str = "System",
        corroborated: bool = True
    ) -> Dict[str, Any]:
        """Validates and executes state transitions according to safety policy."""
        now = time.time()

        # Reject uncorroborated emergency jumps unless authorized commander override
        if target_state in (SafetyState.ALL_RED, SafetyState.BARRIER_LOCKDOWN):
            if not corroborated and actor_role not in ("COMMANDER", "OPERATOR"):
                return {
                    "success": False,
                    "reason": "Transition rejected: Sensor evidence not corroborated and operator unauthorized."
                }

        self.current_state = target_state
        self.operator_actor = f"{actor_name} ({actor_role})"

        # Apply state to physical actuator outputs
        if target_state == SafetyState.NORMAL:
            self.actuator_outputs = {"traffic_signal": "GREEN", "barrier": "OPEN", "buzzer": "OFF"}
        elif target_state == SafetyState.WARNING:
            self.actuator_outputs = {"traffic_signal": "YELLOW", "barrier": "OPEN", "buzzer": "OFF"}
        elif target_state == SafetyState.ALL_RED:
            self.actuator_outputs = {"traffic_signal": "RED", "barrier": "OPEN", "buzzer": "ON"}
        elif target_state == SafetyState.BARRIER_LOCKDOWN:
            self.actuator_outputs = {"traffic_signal": "RED", "barrier": "CLOSED", "buzzer": "ON"}
        elif target_state == SafetyState.EMERGENCY:
            self.actuator_outputs = {"traffic_signal": "GREEN", "barrier": "OPEN", "buzzer": "OFF"}
        elif target_state == SafetyState.MANUAL_OVERRIDE:
            self.override_expiry_time = now + self.override_timeout_sec
        elif target_state == SafetyState.SAFE_SHUTDOWN:
            self.actuator_outputs = {"traffic_signal": "YELLOW", "barrier": "OPEN", "buzzer": "OFF"}

        LOGGER.info(f"[SafetyStateMachine] Transitioned to {self.current_state.value} by {self.operator_actor}")
        return {
            "success": True,
            "state": self.current_state.value,
            "actuator_outputs": self.actuator_outputs,
            "actor": self.operator_actor
        }

    def check_watchdog(self):
        """Reverts expired manual overrides back to NORMAL baseline."""
        now = time.time()
        if self.current_state == SafetyState.MANUAL_OVERRIDE and now > self.override_expiry_time:
            LOGGER.warning("[SafetyStateMachine] Manual override lease expired. Returning to NORMAL.")
            self.request_transition(SafetyState.NORMAL, actor_name="WatchdogDaemon")


ACTUATOR_SAFETY = ActuatorSafetyManager()
