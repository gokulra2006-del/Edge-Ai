"""
Module 9: Web API, Firebase Telemetry Gateway & Operator Dashboard Server.
=========================================================================
Built using Python's standard library http.server for zero-dependency edge deployment.
Serves the modern responsive HTML5 incident command website and provides REST
endpoints for live telemetry, scenario triggering, and Firebase synchronization.
"""
import json
import os
import sys
import hmac
import secrets
from pathlib import Path
import urllib.parse
import time
from typing import Optional, Any
from http.server import HTTPServer, BaseHTTPRequestHandler

ROOT_DIR = Path(__file__).resolve().parents[3]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.config.settings import CONFIG
from src.modules.dashboard.firebase_sync import FIREBASE_SYNC
from src.modules.dashboard.live_streamer import STREAMER
from src.modules.database.db_manager import DatabaseManager
from src.modules.database.governed_store import IncidentRepository
from src.modules.incident_management.workflow import OperatorWorkflow, ReviewQueue, PermissionDenied, VersionConflict, WorkflowError
from src.modules.logging.logger import LOGGER

WEB_DIR = Path(__file__).resolve().parent / "web"
GOVERNED_REPOSITORY = IncidentRepository(Path(CONFIG.db_path))
OPERATOR_WORKFLOW = OperatorWorkflow(GOVERNED_REPOSITORY, ROOT_DIR / "logs" / "simulated_dispatch.jsonl")
REVIEW_QUEUE = ReviewQueue(GOVERNED_REPOSITORY)
AUTH_SESSIONS: dict[str, dict[str, str]] = {}

from src.modules.assurance.drift_monitor import ModelDriftMonitor
from src.modules.assurance.device_health import HealthMonitor, OfflineSyncOutbox
from src.modules.hardware.stream_service import CAMERA_STREAM, AUDIO_STREAM
from src.modules.analytics.analytics_engine import AnalyticsEngine

DRIFT_MONITOR = ModelDriftMonitor(GOVERNED_REPOSITORY)
HEALTH_MONITOR = HealthMonitor(GOVERNED_REPOSITORY)
OUTBOX = OfflineSyncOutbox(GOVERNED_REPOSITORY)
DRIFT_MONITOR.ensure_default_baselines()
ANALYTICS_ENGINE = AnalyticsEngine(GOVERNED_REPOSITORY)

_ANALYTICS_CACHE: dict[str, tuple[float, Any]] = {}
ANALYTICS_CACHE_TTL = 5.0


class DashboardHandler(BaseHTTPRequestHandler):
    db = DatabaseManager()

    def _json(self, value, status=200):
        self.send_response(status); self.send_header("Content-Type", "application/json"); self.send_header("Access-Control-Allow-Origin", "*"); self.end_headers()
        self.wfile.write(json.dumps(value, default=str).encode("utf-8"))

    def _payload(self):
        length = int(self.headers.get("Content-Length", 0)); return json.loads(self.rfile.read(length) or b"{}")

    def _actor(self):
        token = self.headers.get("Authorization", "").removeprefix("Bearer ")
        return AUTH_SESSIONS.get(token)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        # 1. Real-Time Consolidated Telemetry Stream
        if path == "/api/live":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            state = FIREBASE_SYNC.get_full_live_state()
            from src.modules.assurance.model_assurance import MODEL_ASSURANCE
            state["assurance"] = MODEL_ASSURANCE.summarize(state)
            self.wfile.write(json.dumps(state).encode("utf-8"))

        # Model-card evidence and review state for the active profile.
        elif path == "/api/assurance":
            from src.modules.assurance.model_assurance import MODEL_ASSURANCE
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            state = FIREBASE_SYNC.get_full_live_state()
            self.wfile.write(json.dumps(MODEL_ASSURANCE.summarize(state)).encode("utf-8"))

        elif path == "/api/assessment":
            from src.modules.assurance.assessment_service import assess_live_state
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(assess_live_state(FIREBASE_SYNC.get_full_live_state())).encode("utf-8"))

        elif path == "/api/system/health":
            from src.modules.assurance.system_health import system_health
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(system_health()).encode("utf-8"))

        elif path == "/api/monitoring/health":
            self._json(HEALTH_MONITOR.poll())

        elif path == "/api/monitoring/drift":
            self._json(DRIFT_MONITOR.summary())

        elif path == "/api/monitoring/streams":
            self._json({
                "camera": {
                    "health": HEALTH_MONITOR.last_status.get("camera", "OK"),
                    "stream": CAMERA_STREAM.get_health().__dict__,
                },
                "audio": {
                    "health": HEALTH_MONITOR.last_status.get("microphone", "OK"),
                    "stream": AUDIO_STREAM.get_health().__dict__,
                }
            })

        elif path == "/api/monitoring/outbox":
            self._json({
                "counts": OUTBOX.status_summary(),
                "recent": [dict(r) for r in GOVERNED_REPOSITORY._read("SELECT id, idempotency_key, target, payload_type, attempts, next_attempt_at, status, priority, last_error FROM sync_outbox ORDER BY id DESC LIMIT 20")]
            })

        elif path == "/api/incidents":
            self._json(OPERATOR_WORKFLOW.list_incidents({k:v[0] for k,v in urllib.parse.parse_qs(parsed.query).items()}))

        elif path.startswith("/api/incidents/") and path.endswith("/evidence.zip"):
            incident_id = path.split("/")[3]; archive = ROOT_DIR / "data" / "evidence" / f"{incident_id}.zip"
            if not archive.exists(): self._json({"error":"Evidence package not found"},404); return
            self.send_response(200); self.send_header("Content-Type","application/zip"); self.send_header("Content-Disposition",f'attachment; filename="{incident_id}.zip"'); self.end_headers(); self.wfile.write(archive.read_bytes())

        elif path.startswith("/api/incidents/"):
            try: self._json(OPERATOR_WORKFLOW.get_incident(path.split("/")[3]))
            except WorkflowError as exc: self._json({"error":str(exc)},404)

        elif path == "/api/review-queue":
            self._json(REVIEW_QUEUE.list({k:v[0] for k,v in urllib.parse.parse_qs(parsed.query).items()}))

        elif path == "/api/retraining-manifest":
            query=urllib.parse.parse_qs(parsed.query); fmt=query.get("format",["json"])[0]; body=REVIEW_QUEUE.export(fmt,query.get("include_demo",["false"])[0].lower()=="true")
            self.send_response(200); self.send_header("Content-Type","text/csv" if fmt=="csv" else "application/json"); self.end_headers(); self.wfile.write(body.encode("utf-8"))

        # 2. Historical Incidents from SQLite Database
        elif path == "/api/events":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            events = self.db.get_recent_events(limit=20)
            self.wfile.write(json.dumps(events).encode("utf-8"))

        # 3. Node Information & Health
        elif path == "/api/status":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            status_data = {
                "node_id": CONFIG.node_id,
                "zone": CONFIG.zone_name,
                "status": "ONLINE",
                "cloud_sync_enabled": FIREBASE_SYNC.is_configured(),
                "database_url": FIREBASE_SYNC.database_url,
                "hardware": "Raspberry Pi 4 Model B (Quad-Core Cortex-A72)"
            }
            self.wfile.write(json.dumps(status_data).encode("utf-8"))

        # 4. Blackbox Video DVR Recordings List
        elif path == "/api/recordings":
            from src.modules.recording.blackbox_dvr import DVR
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(DVR.list_recordings()).encode("utf-8"))

        # 5. Blackbox Video Stream / Download (.mp4)
        elif path.startswith("/api/recordings/"):
            filename = os.path.basename(path)
            from src.modules.recording.blackbox_dvr import RECORDINGS_DIR
            video_file = RECORDINGS_DIR / filename
            if video_file.exists():
                self.send_response(200)
                self.send_header("Content-Type", "video/mp4")
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Content-Length", str(video_file.stat().st_size))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                with open(video_file, "rb") as vf:
                    self.wfile.write(vf.read())
            else:
                self.send_response(404)
                self.end_headers()

        # 6. Active Emergency Alerts
        elif path == "/api/alerts":
            from src.modules.autonomous_response.alert_manager import ALERT_MANAGER
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(ALERT_MANAGER.get_latest_alerts()).encode("utf-8"))

        elif path == "/api/response-plan":
            from src.modules.autonomous_response.alert_manager import ALERT_MANAGER
            state = FIREBASE_SYNC.get_full_live_state()
            event = state.get("active_event", {})
            plan = ALERT_MANAGER.response_plan(event.get("event", "NORMAL"), event.get("severity", "NORMAL"), event.get("zone", CONFIG.zone_name), event.get("id", ""))
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(plan).encode("utf-8"))

        # 7. Municipal Multi-Intersection Status
        elif path == "/api/intersections":
            from src.modules.autonomous_response.multi_intersection import MUNICIPAL_GRID
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(MUNICIPAL_GRID.get_grid_state()).encode("utf-8"))

        # 8. Predictive Near-Miss & TTC Statistics
        elif path == "/api/near_miss":
            from src.modules.vision_ai.near_miss_analyzer import NEAR_MISS_ANALYZER
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps({
                "history": NEAR_MISS_ANALYZER.near_miss_history,
                "count": len(NEAR_MISS_ANALYZER.near_miss_history)
            }).encode("utf-8"))

        # 9. Automated Forensic Incident Dossier Report
        elif path == "/api/report" or path.startswith("/api/report/"):
            query = urllib.parse.parse_qs(parsed.query)
            inc_id = query.get("id", ["INC-ACTIVE"])[0]
            from src.modules.recording.report_generator import REPORT_GENERATOR
            state = FIREBASE_SYNC.get_full_live_state()
            active_ev = state.get("active_event", {})
            if inc_id != "INC-ACTIVE":
                active_ev["id"] = inc_id

            report_html = REPORT_GENERATOR.generate_html_report(active_ev, state.get("telemetry", {}))
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(report_html.encode("utf-8"))

        # 10. Hardware Capability & Driver Health Report
        elif path == "/api/hardware":
            from src.modules.sensors.readers import COMPOSITE_SENSOR_HUB
            from src.modules.sensors.gpio_registry import GPIO_REGISTRY
            hardware_state = {
                "probe": COMPOSITE_SENSOR_HUB.probe_info,
                "active_mode": COMPOSITE_SENSOR_HUB.mode,
                "readings": COMPOSITE_SENSOR_HUB.read_all(),
                "gpio_registry": GPIO_REGISTRY.PIN_MAP,
                "gpio_validation_errors": GPIO_REGISTRY.validate_registry()
            }
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(hardware_state).encode("utf-8"))
        # 11. Deep Learning Rule Catalog & Active Rules
        elif path == "/api/deep_rules/catalog":
            from src.modules.decision_engine.deep_rule_engine import DEEP_RULE_ENGINE
            catalog = DEEP_RULE_ENGINE.get_rule_catalog()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps({
                "status": "ONLINE",
                "rules_count": len(catalog),
                "rules": catalog
            }).encode("utf-8"))

        # 12. Master Emergency Dataset Catalog & Modality Explorer
        elif path == "/api/datasets/catalog":
            from src.modules.sensors.dataset_feeder import DATASET_INFERENCE_FEEDER
            catalog = DATASET_INFERENCE_FEEDER.get_master_catalog()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(catalog).encode("utf-8"))

        # 13. Specific Sensor & Actuator APIs
        elif path == "/api/sensors/temperature":
            from src.modules.hardware.hardware_hub import HARDWARE_HUB
            d = HARDWARE_HUB.dht22.read()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(d).encode("utf-8"))

        elif path == "/api/sensors/humidity":
            from src.modules.hardware.hardware_hub import HARDWARE_HUB
            d = HARDWARE_HUB.dht22.read()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps({
                "humidity_pct": d.get("humidity_pct"),
                "timestamp": d.get("timestamp"),
                "quality": d.get("quality")
            }).encode("utf-8"))

        elif path == "/api/sensors/imu":
            from src.modules.hardware.hardware_hub import HARDWARE_HUB
            d = HARDWARE_HUB.gy87.read()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(d).encode("utf-8"))

        elif path == "/api/sensors/gps":
            from src.modules.hardware.hardware_hub import HARDWARE_HUB
            d = HARDWARE_HUB.gps.read()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(d).encode("utf-8"))

        elif path == "/api/sensors/gas":
            from src.modules.hardware.hardware_hub import HARDWARE_HUB
            d = HARDWARE_HUB.ads1115.read()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(d).encode("utf-8"))

        elif path == "/api/device/health":
            from src.modules.hardware.hardware_hub import HARDWARE_HUB
            health = HARDWARE_HUB.get_system_health()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(health).encode("utf-8"))

        elif path == "/api/actuators/leds":
            from src.modules.hardware.hardware_hub import HARDWARE_HUB
            d = HARDWARE_HUB.actuators.read()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps({
                "traffic_light": d.get("traffic_light"),
                "led_pins": d.get("led_pins"),
                "timestamp": d.get("timestamp"),
                "quality": d.get("quality")
            }).encode("utf-8"))

        elif path == "/api/audio/status":
            from src.modules.hardware.hardware_hub import HARDWARE_HUB
            d = HARDWARE_HUB.inmp441.read()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(d).encode("utf-8"))

        elif path == "/api/camera/status":
            from src.modules.hardware.hardware_hub import HARDWARE_HUB
            d = HARDWARE_HUB.camera.read()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(d).encode("utf-8"))

        # 14. Serve Static Web Assets
        elif path in ("/", "/index.html"):
            self._serve_file(WEB_DIR / "index.html", "text/html; charset=utf-8")
        elif path == "/app.js":
            self._serve_file(WEB_DIR / "app.js", "application/javascript")
        elif path == "/chart.min.js":
            self._serve_file(WEB_DIR / "chart.min.js", "application/javascript")
        elif path == "/style.css":
            self._serve_file(WEB_DIR / "style.css", "text/css")

        elif path.startswith("/api/analytics/"):
            now = time.monotonic()
            cache_key = self.path
            if cache_key in _ANALYTICS_CACHE:
                cached_time, cached_val = _ANALYTICS_CACHE[cache_key]
                if now - cached_time < ANALYTICS_CACHE_TTL:
                    self._json(cached_val)
                    return

            rng = query.get("range", query.get("window", ["24h"]))[0]
            st = query.get("start_time", [None])[0]
            et = query.get("end_time", [None])[0]
            inc_demo = query.get("include_demo", ["false"])[0].lower() in ("true", "1")
            zone_filter = query.get("zone", [None])[0]
            sev_filter = query.get("severity", [None])[0]
            model_filter = query.get("model", [None])[0]
            if zone_filter in ("", "all", "ALL"): zone_filter = None
            if sev_filter in ("", "all", "ALL"): sev_filter = None
            if model_filter in ("", "all", "ALL"): model_filter = None

            if path == "/api/analytics/overview":
                summary = ANALYTICS_ENGINE.get_incident_summary(window=rng, start_time=st, end_time=et, include_demo=inc_demo)
                avail = ANALYTICS_ENGINE.get_system_availability(window=rng, start_time=st, end_time=et)
                start_b, end_b = summary["window"]["start"], summary["window"]["end"]
                with ANALYTICS_ENGINE._read_connection() as con:
                    zone_rows = con.execute("""
                        SELECT zone_id,
                               count(*) as total,
                               sum(case when severity in ('CRITICAL', 'HIGH') then 1 else 0 end) as severe_count,
                               sum(case when status not in ('RESOLVED', 'CLOSED', 'FALSE_ALARM') then 1 else 0 end) as active_count
                        FROM incidents
                        WHERE created_at >= ? AND created_at <= ?
                        GROUP BY zone_id
                    """, (start_b, end_b)).fetchall()

                zones = []
                for zr in zone_rows:
                    tot = zr["total"]
                    sev_c = zr["severe_count"] or 0
                    act_c = zr["active_count"] or 0
                    if sev_c >= 3 or act_c >= 2:
                        risk_level = "CRITICAL"
                    elif sev_c >= 1:
                        risk_level = "HIGH"
                    elif tot >= 3:
                        risk_level = "MEDIUM"
                    else:
                        risk_level = "LOW"
                    zones.append({
                        "zone_id": zr["zone_id"],
                        "total_incidents": tot,
                        "severe_incidents": sev_c,
                        "active_incidents": act_c,
                        "risk_level": risk_level
                    })
                zones.sort(key=lambda z: (z["severe_incidents"], z["total_incidents"]), reverse=True)

                total_inc = summary["total_incidents"]
                act_inc = sum(v for k, v in summary["by_status"].items() if k not in ("RESOLVED", "CLOSED", "FALSE_ALARM"))
                res_inc = summary["by_status"].get("RESOLVED", 0) + summary["by_status"].get("CLOSED", 0)
                far_count = summary["false_alarm_count"]
                far_rate = round((far_count / total_inc) * 100.0, 1) if total_inc > 0 else 0.0

                result = {
                    "kpis": {
                        "total_incidents": total_inc,
                        "active_incidents": act_inc,
                        "resolved_incidents": res_inc,
                        "false_alarms": far_count,
                        "false_alarm_rate_pct": far_rate,
                        "mtta_seconds": summary["mean_acknowledgment_seconds"],
                        "mttr_seconds": summary["mean_resolution_seconds"],
                        "system_availability_pct": avail["overall_availability_pct"],
                    },
                    "summary": summary,
                    "zones": zones,
                    "availability": avail
                }
                _ANALYTICS_CACHE[cache_key] = (now, result)
                self._json(result)
                return

            elif path == "/api/analytics/trends":
                bucket = query.get("bucket", ["1h"])[0]
                ts = ANALYTICS_ENGINE.get_incident_timeseries(window=rng, start_time=st, end_time=et, bucket_interval=bucket, include_demo=inc_demo)
                result = {"timeseries": ts, "bucket": bucket, "window": rng}
                _ANALYTICS_CACHE[cache_key] = (now, result)
                self._json(result)
                return

            elif path == "/api/analytics/models":
                perf = ANALYTICS_ENGINE.get_model_performance(window=rng, model_id=model_filter, start_time=st, end_time=et)
                drift = ANALYTICS_ENGINE.get_drift_analytics(window=rng, model_id=model_filter, start_time=st, end_time=et)
                disagree_rate = 0.0
                if perf["evaluated_predictions"] > 0:
                    disagree_rate = round((perf["incorrect_predictions"] / perf["evaluated_predictions"]) * 100.0, 1)

                result = {
                    "performance": perf,
                    "drift": drift,
                    "disagreement_rate_pct": disagree_rate,
                    "mean_confidence": perf["mean_confidence"],
                    "ood_rate_pct": round(perf["ood_rate"] * 100.0, 1)
                }
                _ANALYTICS_CACHE[cache_key] = (now, result)
                self._json(result)
                return

            elif path == "/api/analytics/availability":
                avail = ANALYTICS_ENGINE.get_system_availability(window=rng, start_time=st, end_time=et)
                _ANALYTICS_CACHE[cache_key] = (now, result := avail)
                self._json(result)
                return

            elif path == "/api/analytics/outbox":
                with ANALYTICS_ENGINE._read_connection() as con:
                    recent = [dict(r) for r in con.execute("""
                        SELECT id, idempotency_key, target, payload_type, attempts, next_attempt_at,
                               status, priority, last_error, created_at, updated_at
                        FROM sync_outbox
                        ORDER BY id DESC
                        LIMIT 30
                    """).fetchall()]
                result = {
                    "counts": OUTBOX.status_summary(),
                    "recent": recent
                }
                _ANALYTICS_CACHE[cache_key] = (now, result)
                self._json(result)
                return

            else:
                self._json({"error": "Unknown analytics endpoint"}, 404)
                return
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        if path == "/api/auth/login":
            length = int(self.headers.get("Content-Length", 0))
            try:
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                users_path = ROOT_DIR / "src" / "config" / "dashboard_users.local.json"
                users = json.loads(users_path.read_text(encoding="utf-8"))
                username = str(payload.get("username", "")).lower()
                record = users.get(username, {})
                allowed = {"COMMANDER", "OPERATOR", "ENGINEER", "VIEWER"}
                valid = record.get("role") in allowed and hmac.compare_digest(str(record.get("password", "")), str(payload.get("password", "")))
            except (OSError, ValueError, json.JSONDecodeError):
                valid, record = False, {}
            self.send_response(200 if valid else 401)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            if valid:
                token=secrets.token_urlsafe(24); AUTH_SESSIONS[token]={"operator_id":username,"role":record.get("role")}
                response={"role":record.get("role"),"token":token,"operator_id":username}
            else: response={"error":"invalid credentials"}
            self.wfile.write(json.dumps(response).encode("utf-8"))
            return

        if path.startswith("/api/incidents/"):
            actor=self._actor()
            if not actor: self._json({"error":"Authentication required"},401); return
            parts=path.strip("/").split("/")
            if len(parts)==4:
                incident_id,action=parts[2],parts[3].replace("-","_")
                if action == "notes": action = "note"
                try:
                    payload=self._payload(); result=OPERATOR_WORKFLOW.act(incident_id,action,actor["operator_id"],actor["role"],int(payload.get("version",0)),str(payload.get("note",payload.get("reason",payload.get("resolution_summary","")))))
                    self._json(result)
                except PermissionDenied as exc: self._json({"error":str(exc)},403)
                except VersionConflict as exc: self._json({"error":str(exc)},409)
                except (WorkflowError,ValueError) as exc: self._json({"error":str(exc)},400)
                return

        if path.startswith("/api/predictions/"):
            actor=self._actor()
            if not actor: self._json({"error":"Authentication required"},401); return
            parts=path.strip("/").split("/"); prediction_id=int(parts[2])
            try:
                payload=self._payload()
                if parts[3]=="feedback": REVIEW_QUEUE.feedback(prediction_id,payload.get("label",""),actor["operator_id"],actor["role"],payload.get("corrected_class"),payload.get("comment")); self._json({"status":"recorded"})
                elif parts[3]=="claim": self._json({"claimed":REVIEW_QUEUE.claim(prediction_id,actor["operator_id"],actor["role"])})
                else: self._json({"error":"Unknown review action"},404)
            except PermissionDenied as exc: self._json({"error":str(exc)},403)
        if path == "/api/monitoring/stream/control":
            actor = self._actor()
            if not actor:
                self._json({"error": "Authentication required"}, 401)
                return
            role = actor["role"].upper()
            if role not in ("COMMANDER", "OPERATOR"):
                self._json({"error": f"{role} is not permitted to control streams"}, 403)
                return
            payload = self._payload()
            target_stream = payload.get("stream", "camera").lower()
            action = payload.get("action", "start").lower()
            source = payload.get("source")

            service = CAMERA_STREAM if target_stream == "camera" else AUDIO_STREAM
            if action == "start":
                if source:
                    service.set_source(source)
                service.start()
            elif action == "stop":
                service.stop()
            else:
                self._json({"error": "Unknown stream action"}, 400)
                return

            # Record audit trail
            GOVERNED_REPOSITORY.writer.submit(
                lambda db, op=actor["operator_id"], act=f"stream_{action}_{target_stream}", dj=json.dumps(payload): (
                    db.execute(
                        "INSERT INTO operator_actions(incident_id,timestamp,operator_id,action,approved,payload_json) VALUES(?,?,?,?,?,?)",
                        ("SYSTEM", utc_now(), op, act, 1, dj)
                    )
                )
            )
            self._json({"status": "SUCCESS", "stream": target_stream, "action": action, "health": service.get_health().__dict__})
            return

        if path == "/api/monitoring/stream/source":
            actor = self._actor()
            if not actor:
                self._json({"error": "Authentication required"}, 401)
                return
            role = actor["role"].upper()
            if role not in ("COMMANDER", "OPERATOR"):
                self._json({"error": f"{role} is not permitted to configure stream source"}, 403)
                return
            payload = self._payload()
            target_stream = payload.get("stream", "camera").lower()
            source = payload.get("source", "mock")
            service = CAMERA_STREAM if target_stream == "camera" else AUDIO_STREAM
            service.set_source(source)
            self._json({"status": "SUCCESS", "stream": target_stream, "source": source})
            return

        # 1. Interactive Scenario Trigger
        if path == "/api/trigger_scenario":
            scenario = query.get("scenario", ["NORMAL"])[0]
            result = STREAMER.trigger_scenario(scenario)

            # Also log emergency to SQLite for permanent record
            active_ev = result.get("active_event", {})
            if active_ev.get("event") != "NORMAL":
                try:
                    governed_id, _ = GOVERNED_REPOSITORY.create_incident(active_ev.get("event", "UNKNOWN"), active_ev.get("zone", "ZONE_B_INTERSECTION"))
                    GOVERNED_REPOSITORY.writer.drain()
                    active_ev["id"] = governed_id
                    GOVERNED_REPOSITORY.add_event(governed_id, "scenario_trigger", active_ev, dedupe_key=f"scenario:{active_ev.get('event')}:{active_ev.get('timestamp','')}")
                    GOVERNED_REPOSITORY.add_prediction(governed_id, active_ev.get("event", "UNKNOWN"), float(active_ev.get("confidence", 0)), "live-fusion", {"reason_codes": active_ev.get("ood_reasons", []), "ood_status": active_ev.get("ood_status")})
                    self.db.log_event(
                        event_type=active_ev.get("event"),
                        confidence=active_ev.get("confidence", 0.9),
                        severity=active_ev.get("severity", "HIGH"),
                        probable_zone=active_ev.get("zone", "ZONE_B_INTERSECTION"),
                        raw_features=result.get("telemetry", {}),
                        actions={"traffic_signal": result.get("actuators", {}).get("traffic_signal")}
                    )
                except Exception as e:
                    LOGGER.debug(f"DB log note: {e}")

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(result).encode("utf-8"))

        # 2. Operator Alert Acknowledgment
        elif path == "/api/acknowledge_alert":
            incident_id = query.get("id", [""])[0]
            op_name = query.get("operator", ["Operator"])[0]
            op_role = query.get("role", ["COMMANDER"])[0]
            from src.modules.autonomous_response.alert_manager import ALERT_MANAGER
            full_actor = f"{op_name} ({op_role})"
            success = ALERT_MANAGER.acknowledge_incident(incident_id, operator_name=full_actor)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps({
                "status": "SUCCESS" if success else "NOT_FOUND",
                "incident_id": incident_id,
                "acknowledged_by": full_actor
            }).encode("utf-8"))

        # 3. Hardware Operational Mode Switcher
        elif path == "/api/hardware/mode":
            mode = query.get("mode", ["SIMULATION"])[0]
            fault = query.get("fault", ["DISCONNECT"])[0]
            from src.modules.sensors.readers import COMPOSITE_SENSOR_HUB
            COMPOSITE_SENSOR_HUB.set_mode(mode, fault)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps({
                "status": "SUCCESS",
                "mode": COMPOSITE_SENSOR_HUB.mode
            }).encode("utf-8"))

        # 3. Update Firebase Configuration from Web UI
        elif path == "/api/firebase_config":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8") if content_length > 0 else "{}"
            try:
                data = json.loads(body)
                db_url = data.get("database_url", "")
                auth_secret = data.get("auth_secret", "")
                FIREBASE_SYNC.set_config(db_url, auth_secret)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "SUCCESS", "cloud_enabled": FIREBASE_SYNC.is_configured()}).encode("utf-8"))
            except Exception as e:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))

        # 4. Direct Evaluation of Raw Inputs Against Deep Rule Engine
        elif path == "/api/deep_rules/evaluate":
            try:
                content_length = int(self.headers.get("Content-Length", 0))
                if not 0 < content_length <= 65536:
                    raise ValueError('Expected a JSON request body, at most 64 KiB')
                payload = json.loads(self.rfile.read(content_length))
                if not isinstance(payload, dict):
                    raise ValueError('Expected a JSON object')
                from src.modules.decision_engine.deep_rule_engine import DEEP_RULE_ENGINE
                decision = DEEP_RULE_ENGINE.evaluate(
                    raw_audio=payload.get("raw_audio"),
                    raw_image=payload.get("raw_image"),
                    accel_g=float(payload.get("accel_g", 0.03)),
                    impact_detected=bool(payload.get("impact_detected", False)),
                    smoke_ppm=float(payload.get("smoke_ppm", 12.0)),
                    temperature_c=float(payload.get("temperature_c", 28.5)),
                    motion_analysis=payload.get("motion_analysis"),
                    near_miss=payload.get("near_miss"),
                    scenario_hint=payload.get("scenario_hint")
                )
            except (ValueError, TypeError, OSError, RuntimeError) as exc:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(exc)}).encode("utf-8"))
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(decision.to_dict()).encode("utf-8"))

        # 5. Direct Actuator Controls (Servo & Buzzer)
        elif path == "/api/actuators/servo":
            pos = query.get("position", ["OPEN"])[0]
            from src.modules.hardware.hardware_hub import HARDWARE_HUB
            HARDWARE_HUB.actuators.set_barrier(pos)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "SUCCESS", "barrier_position": pos.upper()}).encode("utf-8"))

        elif path == "/api/actuators/buzzer":
            st = query.get("state", ["OFF"])[0].upper()
            from src.modules.hardware.hardware_hub import HARDWARE_HUB
            HARDWARE_HUB.actuators.set_buzzer(st in ("ON", "1", "TRUE"))
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "SUCCESS", "buzzer_active": st in ("ON", "1", "TRUE")}).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def do_OPTIONS(self):
        # Support CORS preflight
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def _serve_file(self, file_path: Path, content_type: str):
        if file_path.exists():
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            with open(file_path, "rb") as f:
                self.wfile.write(f.read())
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        # Suppress noisy HTTP request logging in console
        pass


def run_dashboard_server(host: str = "0.0.0.0", port: int = 8080) -> HTTPServer:
    # Ensure live telemetry streamer is actively broadcasting
    STREAMER.start()

    server = HTTPServer((host, port), DashboardHandler)
    LOGGER.info(f"Sentinel-AI Web Dashboard running at: http://localhost:{port}")
    return server


if __name__ == "__main__":
    import sys
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    print("=" * 65)
    print(f"SENTINEL-AI URBAN EMERGENCY WEB DASHBOARD (PORT {port})")
    print(f"URL: http://localhost:{port}")
    print("=" * 65)
    srv = run_dashboard_server(port=port)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping dashboard server...")
        STREAMER.stop()
        srv.server_close()

