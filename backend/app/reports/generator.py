"""PDF Report Generation Engine for PlantIQ (S6-FS-01).

Implements multi-page, publication-grade executive solar reports.
Uses Jinja2 for HTML template compilation and ReportLab / PyMuPDF for self-contained,
high-performance vector PDF rendering without external GTK system dependencies.
"""

from __future__ import annotations

import io
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional
from uuid import UUID

from jinja2 import Environment, FileSystemLoader
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch, mm
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    HRFlowable,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from sqlalchemy.orm import Session

from app.models import Plant, Report
from app.reports.service import collect_report_data

REPORTS_DIR = Path("uploads/reports")


class NumberedCanvas(canvas.Canvas):
    """Two-pass canvas for dynamic 'Page X of Y' footers and headers."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._saved_page_states: list[Any] = []

    def showPage(self) -> None:
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self) -> None:
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_decorations(num_pages)
            super().showPage()
        super().save()

    def draw_page_decorations(self, total_pages: int) -> None:
        self.saveState()
        self.setFont("Helvetica", 8)
        self.setFillColor(colors.HexColor("#64748b"))

        # Footer
        self.setStrokeColor(colors.HexColor("#e2e8f0"))
        self.setLineWidth(0.5)
        self.line(15 * mm, 12 * mm, 195 * mm, 12 * mm)

        self.drawString(15 * mm, 8 * mm, "PlantIQ Industrial SCADA Analytics • Confidential")
        page_str = f"Page {self._pageNumber} of {total_pages}"
        self.drawRightString(195 * mm, 8 * mm, page_str)
        self.restoreState()


def get_jinja_env() -> Environment:
    """Return Jinja2 environment pointing to template directory."""
    template_dir = Path(__file__).resolve().parent.parent / "templates" / "reports"
    template_dir.mkdir(parents=True, exist_ok=True)
    return Environment(loader=FileSystemLoader(str(template_dir)), autoescape=True)


def build_report_pdf_bytes(report_data: Dict[str, Any]) -> bytes:
    """Render structured report data into publication-ready PDF bytes using ReportLab."""
    meta = report_data.get("metadata", {})
    kpis = report_data.get("kpis", {})
    telemetry_quality = report_data.get("telemetry_quality", {})
    daily_rows = report_data.get("daily_breakdown", [])
    inverters = report_data.get("inverters", [])
    anomalies = report_data.get("anomalies", {})
    events = report_data.get("events", {})

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=15 * mm,
        bottomMargin=18 * mm,
        title=f"{meta.get('plant_name', 'PlantIQ')} - {meta.get('period_label', 'Report')}",
        author="PlantIQ Industrial Copilot",
    )

    styles = getSampleStyleSheet()

    # Custom typography styles
    title_style = ParagraphStyle(
        "ReportTitle",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=18,
        leading=22,
        textColor=colors.HexColor("#004874"),
    )
    subtitle_style = ParagraphStyle(
        "ReportSubtitle",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=12,
        leading=16,
        textColor=colors.HexColor("#1e293b"),
    )
    meta_style = ParagraphStyle(
        "ReportMeta",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8.5,
        leading=12,
        textColor=colors.HexColor("#64748b"),
    )
    h2_style = ParagraphStyle(
        "Heading2Custom",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=11,
        leading=15,
        textColor=colors.HexColor("#0f172a"),
        spaceBefore=10,
        spaceAfter=6,
    )
    body_style = ParagraphStyle(
        "BodyCustom",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8.5,
        leading=11,
        textColor=colors.HexColor("#334155"),
    )
    table_cell = ParagraphStyle(
        "TableCell",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=7.5,
        leading=10,
        textColor=colors.HexColor("#0f172a"),
    )
    table_cell_bold = ParagraphStyle(
        "TableCellBold",
        parent=table_cell,
        fontName="Helvetica-Bold",
    )
    table_cell_mono = ParagraphStyle(
        "TableCellMono",
        parent=table_cell,
        fontName="Courier",
    )

    story: list[Any] = []

    # 1. Header Banner
    header_data = [
        [
            Paragraph("PLANTIQ SCADA ANALYTICS", title_style),
            Paragraph(
                f"<font color='#0284c7'><b>{meta.get('report_type', 'REPORT').upper()}</b></font><br/>"
                f"<font size='7' color='#64748b'>Generated: {meta.get('generated_at', '')}</font>",
                ParagraphStyle("HRight", parent=meta_style, alignment=2),
            ),
        ]
    ]
    t_header = Table(header_data, colWidths=[120 * mm, 60 * mm])
    t_header.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story.append(t_header)

    story.append(
        Paragraph(
            f"{meta.get('plant_name', '')} &mdash; {meta.get('period_label', '')}",
            subtitle_style,
        )
    )
    story.append(
        Paragraph(
            f"Reporting Range: <b>{meta.get('start_date', '')}</b> to <b>{meta.get('end_date', '')}</b> | "
            f"Timezone: {meta.get('timezone', 'Asia/Kolkata')} | "
            f"Capacity: <b>{meta.get('capacity_ac_mw', 0.0)} MW AC</b> / {meta.get('capacity_dc_mwp', 0.0)} MWp DC | "
            f"Expected PR: <b>{meta.get('expected_pr_percent', 80.0)}%</b>",
            meta_style,
        )
    )
    story.append(Spacer(1, 3 * mm))
    story.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor("#0284c7"), spaceAfter=10))

    # 2. Telemetry Gap Alert Banner (if applicable)
    if telemetry_quality.get("has_gap"):
        missing_d_str = ", ".join(telemetry_quality.get("missing_dates", [])) or "selected periods"
        gap_p = Paragraph(
            f"<b>Telemetry Quality Alert:</b> Incomplete SCADA telemetry recorded during reporting interval.<br/>"
            f"<font size='7.5'>Data dropouts or missing logs occurred on: <b>{missing_d_str}</b>. "
            f"Metrics are grounded exclusively on verifiable active observations.</font>",
            ParagraphStyle(
                "GapAlert",
                parent=body_style,
                textColor=colors.HexColor("#92400e"),
                fontSize=8,
                leading=11,
            ),
        )
        t_gap = Table([[gap_p]], colWidths=[180 * mm])
        t_gap.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fffbeb")),
                    ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#f59e0b")),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                    ("LEFTPADDING", (0, 0), (-1, -1), 8),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ]
            )
        )
        story.append(t_gap)
        story.append(Spacer(1, 4 * mm))

    # 3. Hero KPI Cards Grid (4 columns)
    gross_gen_mwh = kpis.get("gross_generation_mwh", 0.0)
    rev_inr = kpis.get("revenue_generated_inr", 0.0)
    pr_val = kpis.get("performance_ratio")
    cuf_val = kpis.get("cuf_percent")
    avail_val = kpis.get("availability_percent")

    pr_str = f"{pr_val:.1f}%" if pr_val is not None else "N/A"
    cuf_str = f"{cuf_val:.2f}%" if cuf_val is not None else "N/A"
    avail_str = f"{avail_val:.1f}%" if avail_val is not None else "N/A"

    kpi_card_data = [
        [
            Paragraph(
                f"<font size='7' color='#64748b'><b>GROSS GENERATION</b></font><br/>"
                f"<font size='14' color='#004874'><b>{gross_gen_mwh:,.2f}</b></font> <font size='8'>MWh</font><br/>"
                f"<font size='7' color='#10b981'><b>₹{rev_inr:,.2f}</b></font>",
                body_style,
            ),
            Paragraph(
                f"<font size='7' color='#64748b'><b>PERFORMANCE RATIO</b></font><br/>"
                f"<font size='14' color='#0f172a'><b>{pr_str}</b></font><br/>"
                f"<font size='7' color='#64748b'>Target: {meta.get('expected_pr_percent', 80.0)}%</font>",
                body_style,
            ),
            Paragraph(
                f"<font size='7' color='#64748b'><b>CAPACITY UTIL. FACTOR</b></font><br/>"
                f"<font size='14' color='#0f172a'><b>{cuf_str}</b></font><br/>"
                f"<font size='7' color='#64748b'>DC Nameplate Basis</font>",
                body_style,
            ),
            Paragraph(
                f"<font size='7' color='#64748b'><b>PLANT AVAILABILITY</b></font><br/>"
                f"<font size='14' color='#0f172a'><b>{avail_str}</b></font><br/>"
                f"<font size='7' color='#64748b'>{meta.get('total_inverters', 0)} Active Inverters</font>",
                body_style,
            ),
        ]
    ]
    t_kpis = Table(kpi_card_data, colWidths=[45 * mm, 45 * mm, 45 * mm, 45 * mm])
    t_kpis.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.append(t_kpis)
    story.append(Spacer(1, 4 * mm))

    # 4. Daily Performance Summary Table
    story.append(Paragraph("1. Daily Generation & Performance Breakdown", h2_style))
    daily_table_data = [
        [
            Paragraph("<b>Date</b>", table_cell_bold),
            Paragraph("<b>Generation (MWh)</b>", table_cell_bold),
            Paragraph("<b>PR (%)</b>", table_cell_bold),
            Paragraph("<b>CUF (%)</b>", table_cell_bold),
            Paragraph("<b>Availability (%)</b>", table_cell_bold),
            Paragraph("<b>Data Status</b>", table_cell_bold),
        ]
    ]
    for row in daily_rows[:14]:  # Show up to 14 days
        pr_display = f"{row['performance_ratio']:.1f}" if row.get("performance_ratio") is not None else "—"
        cuf_display = f"{row['cuf_percent']:.2f}" if row.get("cuf_percent") is not None else "—"
        avail_display = f"{row['availability_percent']:.1f}" if row.get("availability_percent") is not None else "—"
        daily_table_data.append(
            [
                Paragraph(row.get("date", ""), table_cell_mono),
                Paragraph(f"{row.get('generation_mwh', 0.0):,.3f}", table_cell_mono),
                Paragraph(pr_display, table_cell_mono),
                Paragraph(cuf_display, table_cell_mono),
                Paragraph(avail_display, table_cell_mono),
                Paragraph(row.get("status", "Recorded"), table_cell),
            ]
        )

    t_daily = Table(
        daily_table_data,
        colWidths=[28 * mm, 32 * mm, 22 * mm, 22 * mm, 26 * mm, 50 * mm],
    )
    t_daily.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f1f5f9")),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
            ]
        )
    )
    story.append(t_daily)
    story.append(Spacer(1, 4 * mm))

    # 5. Inverter Performance Ranking Table (Top Losers)
    story.append(Paragraph("2. Inverter Performance Ranking (Deficit Analysis)", h2_style))
    inv_table_data = [
        [
            Paragraph("<b>Asset Name</b>", table_cell_bold),
            Paragraph("<b>Model</b>", table_cell_bold),
            Paragraph("<b>Gen (kWh)</b>", table_cell_bold),
            Paragraph("<b>PR (%)</b>", table_cell_bold),
            Paragraph("<b>Deficit (kWh)</b>", table_cell_bold),
            Paragraph("<b>Anomalies</b>", table_cell_bold),
            Paragraph("<b>Operational Status</b>", table_cell_bold),
        ]
    ]
    for inv in inverters[:12]:
        inv_pr_str = f"{inv['performance_ratio']:.1f}" if inv.get("performance_ratio") is not None else "—"
        loss_color = "#e11d48" if inv.get("deficit_kwh", 0) > 0 else "#10b981"
        inv_table_data.append(
            [
                Paragraph(f"<b>{inv.get('asset_name', '')}</b>", table_cell),
                Paragraph(inv.get("model", ""), table_cell),
                Paragraph(f"{inv.get('generation_kwh', 0.0):,.1f}", table_cell_mono),
                Paragraph(inv_pr_str, table_cell_mono),
                Paragraph(f"<font color='{loss_color}'>{inv.get('deficit_kwh', 0.0):,.1f}</font>", table_cell_mono),
                Paragraph(str(inv.get("anomaly_count", 0)), table_cell_mono),
                Paragraph(inv.get("status", "Optimal"), table_cell_bold),
            ]
        )

    t_inv = Table(
        inv_table_data,
        colWidths=[36 * mm, 34 * mm, 26 * mm, 20 * mm, 24 * mm, 18 * mm, 22 * mm],
    )
    t_inv.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f1f5f9")),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
                ("TOPPADDING", (0, 0), (-1, -1), 3.5),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
            ]
        )
    )
    story.append(t_inv)
    story.append(Spacer(1, 4 * mm))

    # 6. Anomalies & Incident Triage Summary
    anom_total = anomalies.get("total_count", 0)
    anom_loss_inr = anomalies.get("total_loss_inr", 0.0)
    anom_loss_kwh = anomalies.get("total_loss_kwh", 0.0)
    sev_map = anomalies.get("by_severity", {})

    story.append(Paragraph("3. Detected Anomalies & Incident Triage", h2_style))
    story.append(
        Paragraph(
            f"Total Anomalies Flagged: <b>{anom_total}</b> | "
            f"Critical: <font color='#e11d48'><b>{sev_map.get('critical', 0)}</b></font> | "
            f"High: <font color='#ea580c'><b>{sev_map.get('high', 0)}</b></font> | "
            f"Medium: <b>{sev_map.get('medium', 0)}</b> | "
            f"Energy Deficit: <b>{anom_loss_kwh:,.1f} kWh</b> | "
            f"Revenue Risk: <font color='#e11d48'><b>₹{anom_loss_inr:,.2f}</b></font>",
            body_style,
        )
    )
    story.append(Spacer(1, 2 * mm))

    anom_items = anomalies.get("items", [])
    if anom_items:
        anom_table_data = [
            [
                Paragraph("<b>Detected At</b>", table_cell_bold),
                Paragraph("<b>Asset</b>", table_cell_bold),
                Paragraph("<b>Detector Rule</b>", table_cell_bold),
                Paragraph("<b>Severity</b>", table_cell_bold),
                Paragraph("<b>Loss (kWh)</b>", table_cell_bold),
                Paragraph("<b>Revenue (₹)</b>", table_cell_bold),
                Paragraph("<b>Status</b>", table_cell_bold),
            ]
        ]
        for a in anom_items[:8]:
            sev_color = "#e11d48" if a.get("severity") == "CRITICAL" else "#ea580c"
            anom_table_data.append(
                [
                    Paragraph(a.get("detected_at", ""), table_cell_mono),
                    Paragraph(a.get("asset_name", ""), table_cell),
                    Paragraph(a.get("detector_name", ""), table_cell),
                    Paragraph(f"<font color='{sev_color}'><b>{a.get('severity', '')}</b></font>", table_cell),
                    Paragraph(f"{a.get('loss_kwh', 0.0):,.1f}", table_cell_mono),
                    Paragraph(f"₹{a.get('financial_loss_inr', 0.0):,.2f}", table_cell_mono),
                    Paragraph(a.get("status", "Open"), table_cell),
                ]
            )
        t_anom = Table(
            anom_table_data,
            colWidths=[28 * mm, 32 * mm, 38 * mm, 20 * mm, 22 * mm, 22 * mm, 18 * mm],
        )
        t_anom.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f1f5f9")),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                    ("TOPPADDING", (0, 0), (-1, -1), 3),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
                ]
            )
        )
        story.append(t_anom)
    else:
        story.append(Paragraph("<i>No anomalies recorded during this operational window.</i>", body_style))

    story.append(Spacer(1, 3 * mm))

    # 7. Operational Events Summary
    event_items = events.get("items", [])
    if event_items:
        story.append(Paragraph("4. Grid & Curtailment Events", h2_style))
        ev_table_data = [
            [
                Paragraph("<b>Event Type</b>", table_cell_bold),
                Paragraph("<b>Start Time</b>", table_cell_bold),
                Paragraph("<b>End Time</b>", table_cell_bold),
                Paragraph("<b>Impact (kW)</b>", table_cell_bold),
                Paragraph("<b>Description</b>", table_cell_bold),
            ]
        ]
        for ev in event_items[:6]:
            ev_table_data.append(
                [
                    Paragraph(f"<b>{ev.get('event_type', '')}</b>", table_cell),
                    Paragraph(ev.get("start_time", ""), table_cell_mono),
                    Paragraph(ev.get("end_time", ""), table_cell_mono),
                    Paragraph(f"{ev.get('impact_kw', 0.0):,.1f}", table_cell_mono),
                    Paragraph(ev.get("description", ""), table_cell),
                ]
            )
        t_ev = Table(ev_table_data, colWidths=[26 * mm, 32 * mm, 32 * mm, 22 * mm, 68 * mm])
        t_ev.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f1f5f9")),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                    ("TOPPADDING", (0, 0), (-1, -1), 3),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
                ]
            )
        )
        story.append(t_ev)

    # Build PDF with two-pass NumberedCanvas
    doc.build(story, canvasmaker=NumberedCanvas)
    return buffer.getvalue()


def execute_report_generation(report_id: UUID, db: Session) -> Report:
    """Core synchronous worker routine to gather data, render PDF, save to disk, and update report row."""
    report = db.get(Report, report_id)
    if report is None:
        raise ValueError(f"Report {report_id} not found")

    report.status = "processing"
    db.commit()
    db.refresh(report)

    try:
        plant = db.get(Plant, report.plant_id)
        if plant is None:
            raise ValueError(f"Plant {report.plant_id} not found")

        # 1. Gather all metrics and telemetry
        report_data = collect_report_data(
            plant=plant,
            start_date=report.start_date,
            end_date=report.end_date,
            report_type=report.report_type,
            db=db,
        )

        # 2. Render HTML via Jinja2 (persisted for inspection / verification)
        jinja_env = get_jinja_env()
        try:
            tmpl = jinja_env.get_template("report_template.html")
            html_content = tmpl.render(data=report_data)
        except Exception:
            html_content = ""

        # 3. Generate authoritative PDF bytes
        pdf_bytes = build_report_pdf_bytes(report_data)
        if not pdf_bytes.startswith(b"%PDF-"):
            raise ValueError("Generated stream failed PDF header verification")

        # 4. Save to secure storage directory
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        pdf_filename = f"{report.id}.pdf"
        pdf_path = REPORTS_DIR / pdf_filename

        with open(pdf_path, "wb") as f:
            f.write(pdf_bytes)

        # Also store HTML snapshot for debugging / alternative rendering
        html_path = REPORTS_DIR / f"{report.id}.html"
        if html_content:
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(html_content)

        file_size = len(pdf_bytes)

        # 5. Update Report record
        report.status = "completed"
        report.file_path = str(pdf_path).replace("\\", "/")
        report.file_size_bytes = file_size
        report.metrics_summary = {
            "gross_generation_mwh": report_data.get("kpis", {}).get("gross_generation_mwh"),
            "revenue_generated_inr": report_data.get("kpis", {}).get("revenue_generated_inr"),
            "performance_ratio": report_data.get("kpis", {}).get("performance_ratio"),
            "cuf_percent": report_data.get("kpis", {}).get("cuf_percent"),
            "availability_percent": report_data.get("kpis", {}).get("availability_percent"),
            "anomalies_count": report_data.get("anomalies", {}).get("total_count"),
            "revenue_loss_inr": report_data.get("anomalies", {}).get("total_loss_inr"),
            "has_telemetry_gap": report_data.get("telemetry_quality", {}).get("has_gap"),
        }
        report.error_message = None
        report.completed_at = datetime.now(timezone.utc)

        db.commit()
        db.refresh(report)
        return report

    except Exception as exc:
        db.rollback()
        report.status = "failed"
        report.error_message = str(exc)
        report.completed_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(report)
        raise exc

