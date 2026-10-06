"""Print-friendly, responsive HTML report templates for Sentinel-AI Edge."""

from __future__ import annotations
import html
from typing import Any


BASE_PRINT_CSS = """
    @page {
        size: A4;
        margin: 15mm 15mm 15mm 15mm;
    }
    @media print {
        body { background: #fff !important; color: #000 !important; font-size: 10pt; }
        .no-print { display: none !important; }
        .page-break { page-break-after: always; }
        .card, table { page-break-inside: avoid; }
        a { text-decoration: none; color: #000; }
    }
    body {
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
        line-height: 1.4;
        color: #1e293b;
        background: #f8fafc;
        margin: 0;
        padding: 24px;
    }
    .report-container {
        max-width: 900px;
        margin: 0 auto;
        background: #ffffff;
        border: 1px solid #e2e8f0;
        border-radius: 12px;
        padding: 32px;
        box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05);
    }
    .header {
        border-bottom: 2px solid #0f172a;
        padding-bottom: 16px;
        margin-bottom: 24px;
        display: flex;
        justify-content: space-between;
        align-items: flex-start;
    }
    .title-block h1 { margin: 0; font-size: 20pt; font-weight: 800; color: #0f172a; letter-spacing: -0.5px; }
    .title-block p { margin: 4px 0 0 0; color: #64748b; font-size: 9pt; font-family: monospace; }
    .badge {
        display: inline-block;
        padding: 4px 8px;
        border-radius: 6px;
        font-size: 8pt;
        font-family: monospace;
        font-weight: 700;
        text-transform: uppercase;
        border: 1px solid #cbd5e1;
        background: #f1f5f9;
        color: #334155;
    }
    .badge-critical { background: #fee2e2; border-color: #fca5a5; color: #991b1b; }
    .badge-stable { background: #dcfce7; border-color: #86efac; color: #166534; }
    .badge-warning { background: #fef3c7; border-color: #fcd34d; color: #92400e; }
    .kpi-grid {
        display: grid;
        grid-template-columns: repeat(4, 1fr);
        gap: 12px;
        margin-bottom: 24px;
    }
    .kpi-card {
        background: #f8fafc;
        border: 1px solid #e2e8f0;
        border-radius: 8px;
        padding: 12px;
    }
    .kpi-label { font-size: 7.5pt; font-weight: 700; text-transform: uppercase; color: #64748b; font-family: monospace; }
    .kpi-value { font-size: 16pt; font-weight: 900; color: #0f172a; margin-top: 4px; font-family: monospace; }
    .kpi-sub { font-size: 7.5pt; color: #94a3b8; margin-top: 2px; }
    table {
        width: 100%;
        border-collapse: collapse;
        margin: 16px 0 24px 0;
        font-size: 9pt;
    }
    th {
        background: #f1f5f9;
        color: #334155;
        font-weight: 700;
        text-align: left;
        padding: 8px 10px;
        border-bottom: 2px solid #cbd5e1;
        font-family: monospace;
        font-size: 8pt;
    }
    td {
        padding: 8px 10px;
        border-bottom: 1px solid #e2e8f0;
    }
    tr:nth-child(even) { background: #f8fafc; }
    .section-title {
        font-size: 11pt;
        font-weight: 800;
        color: #0f172a;
        margin: 24px 0 8px 0;
        text-transform: uppercase;
        font-family: monospace;
        border-left: 4px solid #2563eb;
        padding-left: 8px;
    }
    .footer {
        margin-top: 32px;
        padding-top: 16px;
        border-top: 1px solid #e2e8f0;
        font-size: 7.5pt;
        color: #94a3b8;
        font-family: monospace;
        display: flex;
        justify-content: space-between;
    }
"""


def render_html_document(title: str, body_content: str, meta_tag: str = "OFFICIAL RECORD") -> str:
    """Wraps body content in print-friendly document structure."""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title} - Sentinel-AI</title>
    <style>{BASE_PRINT_CSS}</style>
</head>
<body>
    <div class="report-container">
        <div class="header">
            <div class="title-block">
                <h1>{title}</h1>
                <p>SENTINEL-AI EDGE INTELLIGENCE PLATFORM &middot; NODE_B</p>
            </div>
            <div style="text-align: right;">
                <span class="badge">{html.escape(meta_tag)}</span>
            </div>
        </div>

        {body_content}

        <div class="footer">
            <span>Generated cryptographically from SQLite WAL audit ledger</span>
            <span>Sentinel-AI Governance Engine v2.4</span>
        </div>
    </div>
</body>
</html>"""


def render_monthly_operations_template(data: dict[str, Any]) -> str:
    month = data.get("month", "UNKNOWN")
    kpis = data.get("kpis", {})
    summary = data.get("summary", {})
    zones = data.get("zones", [])

    body = f"""
        <div class="kpi-grid">
            <div class="kpi-card">
                <div class="kpi-label">Total Incidents</div>
                <div class="kpi-value">{kpis.get("total_incidents", 0)}</div>
                <div class="kpi-sub">{kpis.get("active_incidents", 0)} active, {kpis.get("resolved_incidents", 0)} resolved</div>
            </div>
            <div class="kpi-card">
                <div class="kpi-label">Mean Ack Lag (MTTA)</div>
                <div class="kpi-value">{kpis.get("mtta_seconds", "--")}s</div>
                <div class="kpi-sub">Dispatch acknowledgment</div>
            </div>
            <div class="kpi-card">
                <div class="kpi-label">Mean Resolve (MTTR)</div>
                <div class="kpi-value">{kpis.get("mttr_seconds", "--")}s</div>
                <div class="kpi-sub">Total resolution span</div>
            </div>
            <div class="kpi-card">
                <div class="kpi-label">False Alarm Rate</div>
                <div class="kpi-value">{kpis.get("false_alarm_rate_pct", 0)}%</div>
                <div class="kpi-sub">{kpis.get("false_alarms", 0)} false alarms</div>
            </div>
        </div>

        <div class="section-title">1. Operational Status & Severity Breakdown</div>
        <table>
            <thead>
                <tr>
                    <th>Category</th>
                    <th>Distribution</th>
                </tr>
            </thead>
            <tbody>
                <tr>
                    <td><strong>By Severity</strong></td>
                    <td>{", ".join(f"{k}: {v}" for k, v in summary.get("by_severity", {}).items()) or "None recorded"}</td>
                </tr>
                <tr>
                    <td><strong>By Status</strong></td>
                    <td>{", ".join(f"{k}: {v}" for k, v in summary.get("by_status", {}).items()) or "None recorded"}</td>
                </tr>
                <tr>
                    <td><strong>By Event Type</strong></td>
                    <td>{", ".join(f"{k}: {v}" for k, v in summary.get("by_event_type", {}).items()) or "None recorded"}</td>
                </tr>
                <tr>
                    <td><strong>System Availability</strong></td>
                    <td><strong>{kpis.get("system_availability_pct", 100)}%</strong></td>
                </tr>
            </tbody>
        </table>

        <div class="section-title">2. Urban Corridor Zone Risk Comparison</div>
        <table>
            <thead>
                <tr>
                    <th>Zone Identifier</th>
                    <th>Total Incidents</th>
                    <th>Severe Incidents</th>
                    <th>Active Incidents</th>
                    <th>Risk Level</th>
                </tr>
            </thead>
            <tbody>
    """
    for z in zones:
        r_lvl = z.get("risk_level", "LOW")
        b_class = "badge-critical" if r_lvl in ("CRITICAL", "HIGH") else "badge-stable"
        body += f"""
                <tr>
                    <td><strong>{html.escape(z.get("zone_id", ""))}</strong></td>
                    <td>{z.get("total_incidents", 0)}</td>
                    <td>{z.get("severe_incidents", 0)}</td>
                    <td>{z.get("active_incidents", 0)}</td>
                    <td><span class="badge {b_class}">{html.escape(r_lvl)}</span></td>
                </tr>
        """
    body += """
            </tbody>
        </table>
    """
    return render_html_document(f"Monthly Operations Report - {month}", body, meta_tag="MONTHLY REVIEW")


def render_model_assurance_template(data: dict[str, Any]) -> str:
    perf = data.get("performance", {})
    models = data.get("models", [])
    acc = f"{round(perf.get('accuracy', 0) * 100, 1)}%" if perf.get("accuracy") is not None else "N/A"
    conf = f"{round(perf.get('mean_confidence', 0) * 100, 1)}%" if perf.get("mean_confidence") is not None else "N/A"

    body = f"""
        <div class="kpi-grid">
            <div class="kpi-card">
                <div class="kpi-label">Evaluated Samples</div>
                <div class="kpi-value">{perf.get("evaluated_predictions", 0)}</div>
                <div class="kpi-sub">Total: {perf.get("total_predictions", 0)}</div>
            </div>
            <div class="kpi-card">
                <div class="kpi-label">Human Accuracy</div>
                <div class="kpi-value">{acc}</div>
                <div class="kpi-sub">Confirmed feedback</div>
            </div>
            <div class="kpi-card">
                <div class="kpi-label">Mean Confidence</div>
                <div class="kpi-value">{conf}</div>
                <div class="kpi-sub">Prediction confidence</div>
            </div>
            <div class="kpi-card">
                <div class="kpi-label">OOD Rate</div>
                <div class="kpi-value">{round(perf.get("ood_rate", 0) * 100, 1)}%</div>
                <div class="kpi-sub">{perf.get("ood_prediction_count", 0)} out-of-distribution</div>
            </div>
        </div>

        <div class="section-title">Model Registry & Cryptographic Checksums</div>
        <table>
            <thead>
                <tr>
                    <th>Model ID</th>
                    <th>Modality</th>
                    <th>Version</th>
                    <th>Status</th>
                    <th>Usage Restriction</th>
                    <th>SHA-256 Checksum</th>
                </tr>
            </thead>
            <tbody>
    """
    for m in models:
        restr = m.get("usage_restriction", "OPERATIONAL")
        r_badge = "badge-warning" if "RESEARCH" in restr else "badge-stable"
        sh = m.get("sha256", "UNVERIFIED")
        body += f"""
                <tr>
                    <td><strong>{html.escape(m.get("model_id", ""))}</strong></td>
                    <td>{html.escape(m.get("name", ""))}</td>
                    <td>{html.escape(m.get("version", ""))}</td>
                    <td><span class="badge badge-stable">{html.escape(m.get("status", "READY"))}</span></td>
                    <td><span class="badge {r_badge}">{html.escape(restr)}</span></td>
                    <td><code style="font-size: 7pt;">{html.escape(sh[:16] + "..." if len(sh) > 16 else sh)}</code></td>
                </tr>
        """
    body += """
            </tbody>
        </table>
    """
    return render_html_document("Model Assurance & Verification Report", body, meta_tag="ASSURANCE AUDIT")


def render_drift_report_template(data: dict[str, Any]) -> str:
    drift = data.get("drift", {})
    timeline = drift.get("timeline", [])

    body = f"""
        <div class="kpi-grid">
            <div class="kpi-card">
                <div class="kpi-label">Snapshots Logged</div>
                <div class="kpi-value">{drift.get("total_snapshots", 0)}</div>
                <div class="kpi-sub">Total evaluation points</div>
            </div>
            <div class="kpi-card">
                <div class="kpi-label">Stable Models</div>
                <div class="kpi-value">{drift.get("status_distribution", {}).get("STABLE", 0)}</div>
                <div class="kpi-sub">Within baseline bounds</div>
            </div>
            <div class="kpi-card">
                <div class="kpi-label">Watch / Warning</div>
                <div class="kpi-value">{drift.get("status_distribution", {}).get("WATCH", 0) + drift.get("status_distribution", {}).get("DRIFT_WARNING", 0)}</div>
                <div class="kpi-sub">Alert thresholds triggered</div>
            </div>
            <div class="kpi-card">
                <div class="kpi-label">Review Required</div>
                <div class="kpi-value">{drift.get("status_distribution", {}).get("REVIEW_REQUIRED", 0)}</div>
                <div class="kpi-sub">Operator inspection needed</div>
            </div>
        </div>

        <div class="section-title">Drift Snapshots & Population Stability Index (PSI)</div>
        <table>
            <thead>
                <tr>
                    <th>Timestamp</th>
                    <th>Model ID</th>
                    <th>Status</th>
                    <th>PSI Metric</th>
                    <th>Sample Size</th>
                    <th>Reason Codes</th>
                </tr>
            </thead>
            <tbody>
    """
    for item in timeline:
        st = item.get("status", "UNKNOWN")
        st_badge = "badge-stable" if st == "STABLE" else ("badge-warning" if st == "WATCH" else "badge-critical")
        psi_val = item.get("metrics", {}).get("psi", "N/A")
        reasons = ", ".join(item.get("reasons", [])) or "Nominal"
        body += f"""
                <tr>
                    <td>{html.escape(item.get("timestamp", "")[:19])}</td>
                    <td><strong>{html.escape(item.get("model_id", ""))}</strong></td>
                    <td><span class="badge {st_badge}">{html.escape(st)}</span></td>
                    <td><strong>{psi_val}</strong></td>
                    <td>{item.get("sample_count", 0)}</td>
                    <td>{html.escape(reasons)}</td>
                </tr>
        """
    body += """
            </tbody>
        </table>
    """
    return render_html_document("Model Drift Monitoring Report", body, meta_tag="DRIFT ANALYSIS")


def render_device_health_template(data: dict[str, Any]) -> str:
    avail = data.get("availability", {})
    components = avail.get("components", {})
    pct = avail.get("overall_availability_pct", 100.0)

    body = f"""
        <div class="kpi-grid">
            <div class="kpi-card">
                <div class="kpi-label">Overall Availability</div>
                <div class="kpi-value">{pct}%</div>
                <div class="kpi-sub">System uptime ratio</div>
            </div>
            <div class="kpi-card">
                <div class="kpi-label">Active Components</div>
                <div class="kpi-value">{len(components)}</div>
                <div class="kpi-sub">Subsystems monitored</div>
            </div>
        </div>

        <div class="section-title">Component Health Status & Uptime History</div>
        <table>
            <thead>
                <tr>
                    <th>Component</th>
                    <th>Last Status</th>
                    <th>Uptime %</th>
                    <th>Total Events</th>
                    <th>Degraded / Down</th>
                </tr>
            </thead>
            <tbody>
    """
    for comp, c in components.items():
        st = c.get("last_status", "OK")
        st_badge = "badge-stable" if st == "OK" else ("badge-warning" if st == "DEGRADED" else "badge-critical")
        body += f"""
                <tr>
                    <td><strong>{html.escape(comp)}</strong></td>
                    <td><span class="badge {st_badge}">{html.escape(st)}</span></td>
                    <td><strong>{c.get("availability_pct", 100)}%</strong></td>
                    <td>{c.get("total_events", 0)}</td>
                    <td>{c.get("degraded_events", 0)} / {c.get("down_events", 0)}</td>
                </tr>
        """
    body += """
            </tbody>
        </table>
    """
    return render_html_document("Device Health & Availability Report", body, meta_tag="HARDWARE TELEMETRY")


def render_evidence_index_template(data: dict[str, Any]) -> str:
    evidence_rows = data.get("evidence", [])
    total = len(evidence_rows)

    body = f"""
        <div class="kpi-grid">
            <div class="kpi-card">
                <div class="kpi-label">Total Evidence Items</div>
                <div class="kpi-value">{total}</div>
                <div class="kpi-sub">Attached digital artifacts</div>
            </div>
        </div>

        <div class="section-title">Evidence Artifact Inventory & Cryptographic Hashes</div>
        <table>
            <thead>
                <tr>
                    <th>ID</th>
                    <th>Incident ID</th>
                    <th>Timestamp</th>
                    <th>Kind</th>
                    <th>File Name</th>
                    <th>SHA-256 Digest</th>
                </tr>
            </thead>
            <tbody>
    """
    for e in evidence_rows:
        source_name = html.escape(e.get("source_path", "").split("/")[-1].split("\\")[-1])
        sha = e.get("sha256", "")
        body += f"""
                <tr>
                    <td>#{e.get("id", "")}</td>
                    <td><strong>{html.escape(e.get("incident_id", ""))}</strong></td>
                    <td>{html.escape(e.get("timestamp", "")[:19])}</td>
                    <td><span class="badge">{html.escape(e.get("kind", ""))}</span></td>
                    <td>{source_name}</td>
                    <td><code style="font-size: 7pt;">{html.escape(sha[:16] + "..." if len(sha) > 16 else sha)}</code></td>
                </tr>
        """
    body += """
            </tbody>
        </table>
    """
    return render_html_document("Forensic Evidence Package Index", body, meta_tag="FORENSIC MANIFEST")
