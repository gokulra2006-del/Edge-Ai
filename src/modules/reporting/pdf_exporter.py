"""PDF generator using ReportLab with automatic fallback to print-friendly HTML."""

from __future__ import annotations
import logging
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger("EdgeAI.Reporting")


def generate_pdf_from_report_data(
    title: str,
    data: dict[str, Any],
    target_path: Path | str,
    report_type: str = "general",
) -> Path | None:
    """Generate a clean PDF report using ReportLab, or return None if unavailable."""
    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.lib import colors
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    except ImportError:
        LOGGER.warning("ReportLab is not installed; falling back to print-friendly HTML.")
        return None

    try:
        pdf_path = Path(target_path)
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        doc = SimpleDocTemplate(str(pdf_path), pagesize=letter, leftMargin=36, rightMargin=36, topMargin=36, bottomMargin=36)
        styles = getSampleStyleSheet()

        title_style = ParagraphStyle(
            "DocTitle",
            parent=styles["Heading1"],
            fontSize=18,
            leading=22,
            textColor=colors.HexColor("#0f172a"),
            fontName="Helvetica-Bold",
        )
        sub_style = ParagraphStyle(
            "DocSub",
            parent=styles["Normal"],
            fontSize=9,
            leading=12,
            textColor=colors.HexColor("#64748b"),
            fontName="Helvetica",
        )
        heading_style = ParagraphStyle(
            "SectionHeading",
            parent=styles["Heading2"],
            fontSize=11,
            leading=15,
            textColor=colors.HexColor("#1e293b"),
            fontName="Helvetica-Bold",
        )
        cell_style = ParagraphStyle(
            "CellNormal",
            parent=styles["Normal"],
            fontSize=8,
            leading=10,
            fontName="Helvetica",
        )
        cell_bold = ParagraphStyle(
            "CellBold",
            parent=styles["Normal"],
            fontSize=8,
            leading=10,
            fontName="Helvetica-Bold",
        )

        elements: list[Any] = []

        # Header
        elements.append(Paragraph(title, title_style))
        elements.append(Paragraph("SENTINEL-AI EDGE COMMAND PLATFORM &middot; NODE_B", sub_style))
        elements.append(Spacer(1, 14))

        # KPI Summary Table
        kpis = data.get("kpis") or data.get("performance") or data.get("drift") or {}
        if kpis:
            kpi_rows = []
            row = []
            for k, v in list(kpis.items())[:6]:
                if isinstance(v, (int, float, str)):
                    label = k.replace("_", " ").upper()
                    row.append(Paragraph(f"<b>{label}</b><br/>{v}", cell_style))
                    if len(row) == 3:
                        kpi_rows.append(row)
                        row = []
            if row:
                while len(row) < 3:
                    row.append(Paragraph("", cell_style))
                kpi_rows.append(row)

            if kpi_rows:
                kpi_table = Table(kpi_rows, colWidths=[180, 180, 180])
                kpi_table.setStyle(TableStyle([
                    ('BACKGROUND', (0,0), (-1,-1), colors.HexColor("#f8fafc")),
                    ('BOX', (0,0), (-1,-1), 1, colors.HexColor("#e2e8f0")),
                    ('INNERGRID', (0,0), (-1,-1), 0.5, colors.HexColor("#e2e8f0")),
                    ('TOPPADDING', (0,0), (-1,-1), 6),
                    ('BOTTOMPADDING', (0,0), (-1,-1), 6),
                ]))
                elements.append(kpi_table)
                elements.append(Spacer(1, 14))

        # Detail Table
        elements.append(Paragraph("Detailed Records Summary", heading_style))
        elements.append(Spacer(1, 6))

        table_data: list[list[Any]] = []
        if report_type == "monthly":
            zones = data.get("zones", [])
            table_data.append([
                Paragraph("<b>Zone ID</b>", cell_bold),
                Paragraph("<b>Total</b>", cell_bold),
                Paragraph("<b>Severe</b>", cell_bold),
                Paragraph("<b>Active</b>", cell_bold),
                Paragraph("<b>Risk Level</b>", cell_bold),
            ])
            for z in zones:
                table_data.append([
                    Paragraph(str(z.get("zone_id", "")), cell_style),
                    Paragraph(str(z.get("total_incidents", 0)), cell_style),
                    Paragraph(str(z.get("severe_incidents", 0)), cell_style),
                    Paragraph(str(z.get("active_incidents", 0)), cell_style),
                    Paragraph(str(z.get("risk_level", "LOW")), cell_style),
                ])
        elif report_type == "evidence":
            evidence = data.get("evidence", [])
            table_data.append([
                Paragraph("<b>ID</b>", cell_bold),
                Paragraph("<b>Incident</b>", cell_bold),
                Paragraph("<b>Kind</b>", cell_bold),
                Paragraph("<b>SHA-256 (Trunc)</b>", cell_bold),
            ])
            for e in evidence[:25]:
                sha = e.get("sha256", "")[:12] + "..." if len(e.get("sha256", "")) > 12 else e.get("sha256", "")
                table_data.append([
                    Paragraph(f"#{e.get('id', '')}", cell_style),
                    Paragraph(str(e.get("incident_id", "")), cell_style),
                    Paragraph(str(e.get("kind", "")), cell_style),
                    Paragraph(sha, cell_style),
                ])
        else:
            # Generic summary table
            table_data.append([
                Paragraph("<b>Metric / Parameter</b>", cell_bold),
                Paragraph("<b>Value</b>", cell_bold),
            ])
            for k, v in list(data.items())[:15]:
                if isinstance(v, (int, float, str)):
                    table_data.append([
                        Paragraph(k.replace("_", " ").title(), cell_style),
                        Paragraph(str(v), cell_style),
                    ])

        if len(table_data) > 1:
            detail_table = Table(table_data)
            detail_table.setStyle(TableStyle([
                ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#f1f5f9")),
                ('BOTTOMPADDING', (0,0), (-1,-1), 4),
                ('TOPPADDING', (0,0), (-1,-1), 4),
                ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor("#e2e8f0")),
            ]))
            elements.append(detail_table)

        doc.build(elements)
        return pdf_path
    except Exception as exc:
        LOGGER.warning(f"ReportLab PDF generation encountered an error: {exc}; falling back to HTML.")
        return None
