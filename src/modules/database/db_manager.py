"""
Module 8: Local Edge Database Manager (SQLite).
Lightweight persistent storage for edge telemetry, fused emergency events,
and autonomous response audit trails.
"""
import sqlite3
import json
from typing import List, Dict, Any, Optional
from src.core.data_models import FusedEvent, SeverityAssessment, LocationEstimate, ResponseAction
from src.config.settings import CONFIG
from src.modules.logging.logger import LOGGER


class DatabaseManager:
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or CONFIG.db_path
        self._init_db()

    def _init_db(self):
        """Creates the necessary relational tables if they do not exist."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Events table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS emergency_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    is_verified INTEGER NOT NULL,
                    severity_level TEXT NOT NULL,
                    severity_score REAL NOT NULL,
                    primary_node TEXT NOT NULL,
                    probable_zone TEXT NOT NULL,
                    traffic_signal_state TEXT NOT NULL,
                    green_corridor_active INTEGER NOT NULL,
                    lane_restricted TEXT,
                    alert_type TEXT NOT NULL,
                    contributing_modalities TEXT NOT NULL
                )
            """)

            # Raw Telemetry table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS telemetry_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    node_id TEXT NOT NULL,
                    audio_class TEXT,
                    audio_confidence REAL,
                    vision_class TEXT,
                    vision_confidence REAL,
                    imu_impact INTEGER,
                    imu_g_force REAL,
                    temperature_c REAL,
                    smoke_ppm REAL
                )
            """)
            conn.commit()
            LOGGER.info(f"SQLite database initialized at: {self.db_path}")

    def log_event(
        self,
        event: FusedEvent,
        severity: SeverityAssessment,
        location: LocationEstimate,
        action: ResponseAction
    ) -> int:
        """Stores a fused emergency event and its corresponding action."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO emergency_events (
                    timestamp, event_type, confidence, is_verified,
                    severity_level, severity_score, primary_node, probable_zone,
                    traffic_signal_state, green_corridor_active, lane_restricted,
                    alert_type, contributing_modalities
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                event.timestamp,
                event.event_type,
                event.confidence,
                1 if event.is_verified else 0,
                severity.level,
                severity.score,
                location.primary_node,
                location.probable_zone,
                action.traffic_signal_state,
                1 if action.green_corridor_active else 0,
                action.lane_restricted,
                action.alert_type,
                json.dumps(event.contributing_modalities)
            ))
            event_id = cursor.lastrowid
            conn.commit()
            LOGGER.info(f"Database: Logged emergency event #{event_id} ({event.event_type})")
            return event_id

    def get_recent_events(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Fetches the most recent emergency events."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM emergency_events ORDER BY id DESC LIMIT ?", (limit,))
            rows = cursor.fetchall()
            return [dict(r) for r in rows]
