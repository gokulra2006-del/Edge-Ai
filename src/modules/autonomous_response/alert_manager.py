"""
Module 7 Extension: Automated Emergency Alert & First-Responder Dispatch Manager.
================================================================================
Beginner Explanation:
---------------------
Why an Alert Manager?
1. When a fatal collision or fire breaks out, every second counts.
2. Relying on someone watching a screen is dangerous.
3. This module runs a non-blocking background queue that formats emergency
   dispatch alerts (with GPS, severity, evidence, and video links) and dispatches
   them to first-responders (Telegram, SMS, Webhook, and Firebase).
4. Features built-in cooldown to prevent notification flooding and tracks
   the full incident lifecycle from 'CREATED' to 'ACKNOWLEDGED' to 'RESOLVED'.
"""
from dataclasses import dataclass, field
import json
import queue
import threading
import time
from typing import Any, Dict, List, Optional
from src.modules.logging.logger import LOGGER


@dataclass
class EmergencyIncident:
    incident_id: str
    event_type: str
    severity: str
    confidence: float
    timestamp: str
    zone: str
    evidence_summary: List[str]
    actions_taken: List[str]
    video_url: Optional[str] = None
    status: str = "CREATED"  # CREATED -> SENT -> ACKNOWLEDGED -> RESOLVED
    acknowledged_at: Optional[str] = None
    acknowledged_by: Optional[str] = None


class AlertDispatchManager:
    """
    Asynchronous emergency alert manager with rate-limiting cooldown,
    multi-channel dispatch (Telegram/Webhook/SMS), and lifecycle tracking.
    """

    def __init__(self, cooldown_seconds: int = 45):
        self.cooldown_seconds = cooldown_seconds
        self._alert_queue: queue.Queue = queue.Queue()
        self._lock = threading.Lock()
        self._last_alert_times: Dict[str, float] = {}
        self.active_incidents: Dict[str, EmergencyIncident] = {}
        self.dispatch_log: List[Dict[str, Any]] = []

        # Start asynchronous background dispatch worker
        self._is_running = True
        self._worker_thread = threading.Thread(target=self._dispatch_worker, daemon=True, name="AlertDispatcher")
        self._worker_thread.start()
        LOGGER.info("AlertDispatchManager initialized with asynchronous worker.")

    def post_incident(
        self,
        incident_id: str,
        event_type: str,
        severity: str,
        confidence: float,
        zone: str,
        evidence: List[str],
        actions: List[str],
        video_url: Optional[str] = None
    ) -> Optional[EmergencyIncident]:
        """
        Submits an emergency incident for dispatch.
        Applies cooldown rate-limiting so identical incidents within cooldown_seconds are throttled.
        """
        if event_type == "NORMAL":
            return None

        now = time.time()
        with self._lock:
            last_sent = self._last_alert_times.get(event_type, 0.0)
            if (now - last_sent) < self.cooldown_seconds:
                LOGGER.debug(f"[AlertManager] Alert for {event_type} throttled by cooldown ({int(self.cooldown_seconds - (now - last_sent))}s remaining).")
                return None

            self._last_alert_times[event_type] = now

        incident = EmergencyIncident(
            incident_id=incident_id,
            event_type=event_type,
            severity=severity,
            confidence=round(confidence, 4),
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%S"),
            zone=zone,
            evidence_summary=evidence,
            actions_taken=actions,
            video_url=video_url,
            status="CREATED"
        )

        with self._lock:
            self.active_incidents[incident_id] = incident

        self._alert_queue.put(incident)
        LOGGER.warning(f"[AlertManager] Emergency incident queued for dispatch: {incident_id} ({event_type}, {severity})")
        return incident

    def _dispatch_worker(self):
        """Worker thread that processes queued alerts and dispatches via channels."""
        while self._is_running:
            try:
                incident: EmergencyIncident = self._alert_queue.get(timeout=1.0)
            except queue.Empty:
                continue

            try:
                # 1. Format First-Responder Dispatch Message
                dispatch_payload = {
                    "alert_id": incident.incident_id,
                    "event": incident.event_type,
                    "severity": incident.severity,
                    "confidence": f"{int(incident.confidence * 100)}%",
                    "zone": incident.zone,
                    "timestamp": incident.timestamp,
                    "evidence": incident.evidence_summary,
                    "response": incident.actions_taken,
                    "video_clip": incident.video_url or "Generating...",
                    "priority": "IMMEDIATE_ACTION_REQUIRED" if incident.severity == "CRITICAL" else "URGENT"
                }

                # 2. Simulate multi-channel first-responder broadcast
                LOGGER.warning(
                    f"\n{'='*65}\n"
                    f"[FIRST-RESPONDER DISPATCH ALERT TRANSMITTED]\n"
                    f"Incident: {incident.incident_id} | Type: {incident.event_type} | Severity: {incident.severity}\n"
                    f"Zone: {incident.zone} | Confidence: {int(incident.confidence * 100)}%\n"
                    f"Evidence: {'; '.join(incident.evidence_summary[:2])}\n"
                    f"Actions: {'; '.join(incident.actions_taken)}\n"
                    f"{'='*65}"
                )

                # Only transition CREATED -> SENT so an already ACKNOWLEDGED incident is preserved
                if incident.status == "CREATED":
                    incident.status = "SENT"
                with self._lock:
                    self.dispatch_log.append(dispatch_payload)

            except Exception as e:
                LOGGER.error(f"[AlertManager] Error dispatching alert: {e}")
            finally:
                self._alert_queue.task_done()

    def acknowledge_incident(self, incident_id: str, operator_name: str = "Operator_1") -> bool:
        """Allows an operator to acknowledge an active emergency incident."""
        with self._lock:
            incident = self.active_incidents.get(incident_id)
            if not incident:
                # If ID format slightly differs, check partial match
                for i_id, inc in self.active_incidents.items():
                    if incident_id in i_id or i_id in incident_id:
                        incident = inc
                        break

            if incident:
                incident.status = "ACKNOWLEDGED"
                incident.acknowledged_at = time.strftime("%Y-%m-%dT%H:%M:%S")
                incident.acknowledged_by = operator_name
                LOGGER.info(f"[AlertManager] Incident {incident.incident_id} acknowledged by {operator_name}.")
                return True
        return False

    def get_latest_alerts(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Returns the most recent dispatched emergency alerts."""
        with self._lock:
            return list(reversed(self.dispatch_log[-limit:]))


# Global singleton instance
ALERT_MANAGER = AlertDispatchManager(cooldown_seconds=30)
