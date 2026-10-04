"""
Audio AI Dedicated Web Dashboard.
Standalone interactive web interface for inspecting the acoustic emergency model,
viewing precision/recall/F1 metrics and confusion matrix, and testing audio classification live.
"""
from http.server import HTTPServer, BaseHTTPRequestHandler
import json
import os
import sys
import urllib.parse
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(BASE_DIR))
REPORT_PATH = BASE_DIR / "models" / "audio" / "evaluation_report.json"
MODEL_PATH = BASE_DIR / "models" / "audio" / "best_model.pt"

from src.modules.audio_ai.inference import AudioInferenceEngine

# Lazy-loaded inference engine
_INFERENCE_ENGINE = None

def get_engine():
    global _INFERENCE_ENGINE
    if _INFERENCE_ENGINE is None and MODEL_PATH.exists():
        _INFERENCE_ENGINE = AudioInferenceEngine(MODEL_PATH)
    return _INFERENCE_ENGINE


class AudioDashboardHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        if path == "/api/metrics":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            if REPORT_PATH.exists():
                with open(REPORT_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.wfile.write(json.dumps(data).encode("utf-8"))
            else:
                self.wfile.write(json.dumps({"error": "Report not found. Run evaluate.py"}).encode("utf-8"))

        elif path == "/api/test-sample":
            sample_type = query.get("type", ["ambulance"])[0]
            engine = get_engine()
            if not engine:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(b'{"error": "Model not loaded"}')
                return

            # Find matching sample file
            sample_map = {
                "ambulance": list((BASE_DIR / "sireNNet").glob("**/sound_1.wav")),
                "firetruck": list((BASE_DIR / "sireNNet").glob("**/sound_201.wav")),
                "police": list((BASE_DIR / "sireNNet").glob("**/sound_601.wav")),
                "traffic": list((BASE_DIR / "sireNNet").glob("**/sound_401.wav")),
                "glass": list((BASE_DIR / "ESC-50-master").glob("**/1-100038-A-14.wav"))
            }
            files = sample_map.get(sample_type, [])
            if files:
                res = engine.predict_file(str(files[0]))
                res["sample_filename"] = files[0].name
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(res).encode("utf-8"))
            else:
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b'{"error": "Sample file not found"}')

        elif path == "/" or path == "/index.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            html = self._render_html()
            self.wfile.write(html.encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def _render_html(self) -> str:
        report = {}
        if REPORT_PATH.exists():
            with open(REPORT_PATH, "r", encoding="utf-8") as f:
                report = json.load(f)

        acc = report.get("overall_accuracy", 0.0) * 100
        f1 = report.get("macro_f1", 0.0) * 100
        lat = report.get("latency_ms", {}).get("average", 0.0)
        classes = report.get("classes", ["normal_traffic", "ambulance_siren", "firetruck_siren", "police_siren", "breaking_glass", "car_horn"])
        per_class = report.get("per_class_metrics", {})
        conf_mat = report.get("confusion_matrix", [])

        # Rows for per-class table
        table_rows = ""
        for c in classes:
            m = per_class.get(c, {})
            p = m.get("precision", 0) * 100
            r = m.get("recall", 0) * 100
            f = m.get("f1_score", 0) * 100
            fpr = m.get("false_positive_rate", 0) * 100
            sup = m.get("support", 0)
            badge_color = "#10b981" if f >= 80 else ("#f59e0b" if f >= 60 else "#ef4444")
            table_rows += f"""
            <tr style="border-bottom: 1px solid #334155;">
                <td style="padding: 10px; font-weight: 600;">{c.replace('_', ' ').title()}</td>
                <td style="padding: 10px;">{p:.1f}%</td>
                <td style="padding: 10px;">{r:.1f}%</td>
                <td style="padding: 10px; color: {badge_color}; font-weight: bold;">{f:.1f}%</td>
                <td style="padding: 10px; color: #94a3b8;">{fpr:.1f}%</td>
                <td style="padding: 10px; color: #94a3b8;">{sup}</td>
            </tr>
            """

        # Confusion matrix HTML
        cm_headers = "".join([f"<th style='padding: 6px; font-size: 11px;'>{c[:6]}</th>" for c in classes])
        cm_rows = ""
        for i, c in enumerate(classes):
            cells = ""
            for j in range(len(classes)):
                val = conf_mat[i][j] if i < len(conf_mat) and j < len(conf_mat[i]) else 0
                bg = "#1e293b"
                if i == j and val > 0:
                    bg = "#065f46"
                elif i != j and val > 0:
                    bg = "#7f1d1d"
                cells += f"<td style='padding: 6px; text-align: center; background: {bg}; border: 1px solid #334155;'>{val}</td>"
            cm_rows += f"<tr><td style='padding: 6px; font-weight: bold; font-size: 11px;'>{c[:8]}</td>{cells}</tr>"

        return f"""
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <title>Audio AI Emergency Classification Dashboard</title>
            <style>
                body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0b0f19; color: #f1f5f9; margin: 0; padding: 25px; }}
                .container {{ max-width: 1200px; margin: 0 auto; }}
                .header {{ display: flex; justify-content: space-between; align-items: center; border-bottom: 2px solid #1e293b; padding-bottom: 15px; margin-bottom: 25px; }}
                .grid-4 {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 15px; margin-bottom: 25px; }}
                .stat-box {{ background: #161f30; padding: 18px; border-radius: 8px; border: 1px solid #273549; }}
                .stat-title {{ font-size: 12px; color: #94a3b8; text-transform: uppercase; font-weight: bold; }}
                .stat-value {{ font-size: 26px; font-weight: bold; color: #38bdf8; margin-top: 5px; }}
                .card {{ background: #161f30; border-radius: 8px; padding: 20px; border: 1px solid #273549; margin-bottom: 20px; }}
                table {{ width: 100%; border-collapse: collapse; text-align: left; }}
                th {{ padding: 10px; background: #0f172a; color: #94a3b8; font-size: 12px; text-transform: uppercase; }}
                .btn {{ background: #2563eb; color: white; border: none; padding: 9px 16px; border-radius: 6px; cursor: pointer; font-weight: bold; margin-right: 8px; }}
                .btn:hover {{ background: #1d4ed8; }}
                .badge {{ background: #059669; color: white; padding: 4px 10px; border-radius: 20px; font-size: 12px; }}
                .prob-bar {{ height: 8px; background: #334155; border-radius: 4px; overflow: hidden; margin-top: 4px; }}
                .prob-fill {{ height: 100%; background: #38bdf8; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <div>
                        <h1 style="margin: 0; font-size: 24px; color: #38bdf8;">Acoustic AI Intelligence Dashboard</h1>
                        <div style="font-size: 13px; color: #94a3b8; margin-top: 4px;">Model: EdgeAudioCNN (PyTorch) | Target Device: Raspberry Pi 4 CPU</div>
                    </div>
                    <div><span class="badge">PIPELINE ACTIVE</span></div>
                </div>

                <div class="grid-4">
                    <div class="stat-box">
                        <div class="stat-title">Test Accuracy</div>
                        <div class="stat-value" style="color: #10b981;">{acc:.2f}%</div>
                    </div>
                    <div class="stat-box">
                        <div class="stat-title">Macro F1-Score</div>
                        <div class="stat-value">{f1:.2f}%</div>
                    </div>
                    <div class="stat-box">
                        <div class="stat-title">Inference Latency</div>
                        <div class="stat-value" style="color: #f59e0b;">{lat:.2f} ms</div>
                    </div>
                    <div class="stat-box">
                        <div class="stat-title">Edge Model Size</div>
                        <div class="stat-value">190 KB</div>
                    </div>
                </div>

                <!-- Live Test Section -->
                <div class="card">
                    <h3 style="margin-top: 0; color: #f8fafc;">Live Real-Time Inference Tester</h3>
                    <p style="font-size: 13px; color: #94a3b8;">Click any sample audio file below to trigger the Librosa Mel-spectrogram feature extractor and PyTorch neural network:</p>
                    <div style="margin-bottom: 20px;">
                        <button class="btn" onclick="testSound('ambulance')">🚑 Test Ambulance Siren</button>
                        <button class="btn" onclick="testSound('firetruck')">🚒 Test Firetruck Siren</button>
                        <button class="btn" onclick="testSound('police')">🚓 Test Police Siren</button>
                        <button class="btn" onclick="testSound('traffic')">🚗 Test Normal Traffic</button>
                        <button class="btn" onclick="testSound('glass')">💥 Test Shattering Glass</button>
                    </div>

                    <div id="resultBox" style="display: none; background: #0f172a; padding: 18px; border-radius: 8px; border: 1px solid #334155;">
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
                            <div>
                                <span style="font-size: 13px; color: #94a3b8;">Predicted Class:</span>
                                <span id="predClass" style="font-size: 18px; font-weight: bold; color: #38bdf8; margin-left: 8px;"></span>
                            </div>
                            <div>
                                <span style="font-size: 13px; color: #94a3b8;">Confidence:</span>
                                <span id="predConf" style="font-size: 18px; font-weight: bold; color: #10b981; margin-left: 8px;"></span>
                            </div>
                            <div>
                                <span style="font-size: 13px; color: #94a3b8;">Execution Time:</span>
                                <span id="predLatency" style="font-size: 18px; font-weight: bold; color: #f59e0b; margin-left: 8px;"></span>
                            </div>
                        </div>
                        <div id="probBars"></div>
                    </div>
                </div>

                <div style="display: grid; grid-template-columns: 2fr 1fr; gap: 20px;">
                    <div class="card">
                        <h3 style="margin-top: 0;">Per-Class Evaluation Metrics (Unseen Test Set)</h3>
                        <table>
                            <thead>
                                <tr>
                                    <th>Emergency Class</th>
                                    <th>Precision</th>
                                    <th>Recall</th>
                                    <th>F1-Score</th>
                                    <th>FPR (False Alarm)</th>
                                    <th>Support</th>
                                </tr>
                            </thead>
                            <tbody>
                                {table_rows}
                            </tbody>
                        </table>
                    </div>

                    <div class="card">
                        <h3 style="margin-top: 0;">Confusion Matrix</h3>
                        <table>
                            <thead>
                                <tr>
                                    <th>True \\ Pred</th>
                                    {cm_headers}
                                </tr>
                            </thead>
                            <tbody>
                                {cm_rows}
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>

            <script>
                async function testSound(type) {{
                    const box = document.getElementById('resultBox');
                    box.style.display = 'block';
                    document.getElementById('predClass').innerText = 'Processing...';

                    const res = await fetch('/api/test-sample?type=' + type);
                    const data = await res.json();

                    document.getElementById('predClass').innerText = data.predicted_class.toUpperCase();
                    document.getElementById('predConf').innerText = (data.confidence * 100).toFixed(1) + '%';
                    document.getElementById('predLatency').innerText = data.latency_ms.toFixed(1) + ' ms';

                    let bars = '<div style="margin-top: 15px; font-size: 12px; color: #94a3b8; font-weight: bold; margin-bottom: 8px;">PROBABILITY DISTRIBUTION:</div>';
                    for (const [cls, p] of Object.entries(data.probabilities)) {{
                        const pct = (p * 100).toFixed(1);
                        bars += `
                        <div style="margin-bottom: 8px;">
                            <div style="display: flex; justify-content: space-between; font-size: 12px;">
                                <span>${{cls.replace('_', ' ').toUpperCase()}}</span>
                                <span>${{pct}}%</span>
                            </div>
                            <div class="prob-bar">
                                <div class="prob-fill" style="width: ${{pct}}%;"></div>
                            </div>
                        </div>
                        `;
                    }}
                    document.getElementById('probBars').innerHTML = bars;
                }}
            </script>
        </body>
        </html>
        """

    def log_message(self, format, *args):
        pass


def run_dashboard(port: int = 8085):
    server = HTTPServer(("0.0.0.0", port), AudioDashboardHandler)
    print(f"\n=================================================================")
    print(f"  AUDIO AI DASHBOARD ACTIVE AT: http://localhost:{port}")
    print(f"=================================================================\n")
    server.serve_forever()


if __name__ == "__main__":
    run_dashboard()
