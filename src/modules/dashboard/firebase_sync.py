"""
Module 9: Firebase Realtime Database Synchronization Bridge for Raspberry Pi.
=============================================================================
Beginner Explanation:
---------------------
What does this bridge do?
1. An edge device (like a Raspberry Pi 4 placed at an intersection) collects
   sensor data, runs AI inference, and determines emergency situations.
2. To make this data accessible anywhere in the world, this module sends
   (syncs) the live telemetry and emergency alerts to Google Firebase.
3. Firebase Realtime Database is a cloud-hosted NoSQL database where data
   is stored as JSON and synchronized in real time to any connected website or app.
4. This script uses Python's standard 'urllib' library, meaning it has
   ZERO heavy external dependencies (no complex GCP SDKs required), making it
   ultra-lightweight and reliable on edge hardware.
"""
import json
import logging
import os
import time
import urllib.error
import urllib.request
from typing import Any, Dict, Optional

LOGGER = logging.getLogger("EdgeAI.FirebaseSync")


class FirebaseEdgeSync:
    """
    Handles bidirectional synchronization between Raspberry Pi edge node
    and Google Firebase Realtime Database via REST API.
    """

    def __init__(
        self,
        database_url: Optional[str] = None,
        auth_secret: Optional[str] = None,
        node_id: str = "NODE_B"
    ):
        # User's Firebase Realtime Database URL (No API key needed in Test Mode)
        DEFAULT_URL = "https://edge-ai-524d4-default-rtdb.asia-southeast1.firebasedatabase.app"
        if database_url is None:
            database_url = os.environ.get("FIREBASE_DATABASE_URL", DEFAULT_URL)
        self.database_url = (database_url or "").rstrip("/")
        self.auth_secret = auth_secret or os.environ.get("FIREBASE_AUTH_SECRET", "")
        self.node_id = node_id

        # In-memory local state cache (serves as zero-latency local fallback)
        self.local_cache = {
            "node_id": self.node_id,
            "connected": False,
            "cloud_sync_enabled": bool(self.database_url),
            "last_synced_timestamp": None,
            "telemetry": {},
            "actuators": {
                "traffic_signal": "GREEN",
                "barrier": "OPEN",
                "buzzer": "OFF",
                "green_corridor_active": False,
                "dispatch_alert": "SYSTEM_STANDBY_NORMAL"
            },
            "active_event": {
                "event": "NORMAL",
                "confidence": 0.90,
                "severity": "LOW",
                "zone": "ZONE_B_INTERSECTION",
                "verified": True
            }
        }

        if self.database_url:
            LOGGER.info(f"FirebaseEdgeSync initialized with cloud URL: {self.database_url}")
        else:
            LOGGER.info("FirebaseEdgeSync running in Local Bridge Mode (Cloud URL not set; will serve locally and accept web config)")

    def is_configured(self) -> bool:
        """Returns True if a valid Firebase database URL is configured."""
        return bool(self.database_url and self.database_url.startswith("https://"))

    def set_config(self, database_url: str, auth_secret: Optional[str] = None):
        """Update Firebase configuration dynamically at runtime."""
        self.database_url = database_url.rstrip("/") if database_url else ""
        if auth_secret is not None:
            self.auth_secret = auth_secret
        self.local_cache["cloud_sync_enabled"] = self.is_configured()
        LOGGER.info(f"Firebase configuration updated. Cloud enabled: {self.local_cache['cloud_sync_enabled']}")

    def _build_url(self, path: str) -> str:
        """Builds standard REST endpoint URL with optional auth token."""
        clean_path = path.strip("/")
        url = f"{self.database_url}/{clean_path}.json"
        if self.auth_secret:
            url += f"?auth={self.auth_secret}"
        return url

    def _send_request(self, method: str, path: str, data: Optional[Dict[str, Any]] = None) -> bool:
        """
        Sends HTTP REST request to Firebase Realtime Database.
        Method: PUT (write/replace) or PATCH (update).
        """
        if not self.is_configured():
            return False

        url = self._build_url(path)
        payload = json.dumps(data).encode("utf-8") if data is not None else None
        headers = {"Content-Type": "application/json"}

        req = urllib.request.Request(url, data=payload, headers=headers, method=method)

        try:
            with urllib.request.urlopen(req, timeout=3.0) as response:
                if response.status in (200, 204):
                    self.local_cache["connected"] = True
                    self.local_cache["last_synced_timestamp"] = time.time()
                    return True
                return False
        except urllib.error.HTTPError as e:
            LOGGER.warning(f"Firebase HTTP Error ({e.code}) on {path}: {e.reason}")
            self.local_cache["connected"] = False
            return False
        except Exception as e:
            LOGGER.debug(f"Firebase connection attempt notice: {e}")
            self.local_cache["connected"] = False
            return False

    def sync_live_telemetry(self, telemetry: Dict[str, Any]) -> bool:
        """
        Pushes live sensor telemetry from Raspberry Pi to Firebase:
        /nodes/{node_id}/telemetry
        """
        # Always update local cache for local web dashboard fallback
        self.local_cache["telemetry"] = telemetry

        if not self.is_configured():
            return False

        path = f"nodes/{self.node_id}/telemetry"
        return self._send_request("PUT", path, telemetry)

    def sync_actuators(self, actuators: Dict[str, Any]) -> bool:
        """
        Pushes autonomous actuator state (traffic lights, barrier, buzzer) to Firebase:
        /nodes/{node_id}/actuators
        """
        self.local_cache["actuators"].update(actuators)

        if not self.is_configured():
            return False

        path = f"nodes/{self.node_id}/actuators"
        return self._send_request("PATCH", path, actuators)

    def sync_emergency_event(self, event_data: Dict[str, Any]) -> bool:
        """
        Pushes current emergency event state and appends to event log:
        /nodes/{node_id}/current_event
        /events/{event_id}
        """
        self.local_cache["active_event"] = event_data

        if not self.is_configured():
            return False

        # 1. Update current node event
        path_current = f"nodes/{self.node_id}/current_event"
        self._send_request("PUT", path_current, event_data)

        # 2. Append to persistent global incident feed
        event_id = event_data.get("id") or f"ev_{int(time.time() * 1000)}"
        path_log = f"events/{event_id}"
        return self._send_request("PUT", path_log, event_data)

    def get_full_live_state(self) -> Dict[str, Any]:
        """Returns consolidated snapshot of all telemetry, actuators, and events."""
        return {
            "node_id": self.node_id,
            "connected_to_firebase": self.local_cache["connected"],
            "cloud_sync_enabled": self.local_cache["cloud_sync_enabled"],
            "database_url": self.database_url,
            "timestamp": time.time(),
            "telemetry": self.local_cache["telemetry"],
            "actuators": self.local_cache["actuators"],
            "active_event": self.local_cache["active_event"]
        }


# Global singleton instance for easy cross-module sharing
FIREBASE_SYNC = FirebaseEdgeSync()
