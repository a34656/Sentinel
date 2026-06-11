"""
report_generator.py — The Report Generator worker.

Receives the completed investigation state from the Master and produces
a structured PDF post-mortem using ReportLab. The PDF is saved to the
/reports directory and the path is stored in state for the Scribe to reference.
"""

import os
from datetime import datetime

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
)
from loguru import logger

from core.state import AgentState


REPORTS_DIR = os.path.join(os.path.dirname(__file__), "..", "reports")
os.makedirs(REPORTS_DIR, exist_ok=True)


def generate(state: AgentState) -> AgentState:
    incident_id = state.get("incident_id", "unknown")
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = f"postmortem_{incident_id[:8]}_{timestamp}.pdf"
    filepath = os.path.join(REPORTS_DIR, filename)

    logger.info(f"[ReportGenerator] Generating PDF → {filepath}")

    try:
        _build_pdf(state, filepath)
        log_entry = f"[ReportGenerator] ✅ PDF saved: {filepath}"
        logger.info(log_entry)
        return {
            **state,
            "current_worker": "report_generator",
            "final_report_path": filepath,
            "step_log": [log_entry],
        }
    except Exception as exc:
        logger.error(f"[ReportGenerator] PDF generation failed: {exc}")
        return {
            **state,
            "current_worker": "report_generator",
            "step_log": [f"[ReportGenerator] ⚠️  PDF failed — {exc}"],
        }


# ── PDF construction ──────────────────────────────────────────────────────────

def _build_pdf(state: AgentState, filepath: str) -> None:
    doc = SimpleDocTemplate(
        filepath,
        pagesize=A4,
        rightMargin=2 * cm,
        leftMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
    )

    styles = getSampleStyleSheet()
    story = []

    # ── Title ─────────────────────────────────────────────────────────────
    title_style = ParagraphStyle(
        "Title",
        parent=styles["Title"],
        fontSize=20,
        spaceAfter=6,
        textColor=colors.HexColor("#0f172a"),
    )
    subtitle_style = ParagraphStyle(
        "Subtitle",
        parent=styles["Normal"],
        fontSize=10,
        textColor=colors.HexColor("#64748b"),
        spaceAfter=20,
    )

    story.append(Paragraph("Incident Post-Mortem", title_style))
    story.append(Paragraph(
        f"Generated {datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC  •  Incident ID: {state.get('incident_id', 'N/A')}",
        subtitle_style,
    ))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#e2e8f0")))
    story.append(Spacer(1, 0.4 * cm))

    # ── Summary table ─────────────────────────────────────────────────────
    confidence_pct = f"{state.get('confidence_score', 0.0) * 100:.0f}%"
    fix_status = "✅ Applied" if state.get("fix_applied") else "⛔ Blocked — requires human action"

    summary_data = [
        ["Field", "Value"],
        ["Root Cause", state.get("root_cause") or "Undetermined"],
        ["Confidence", confidence_pct],
        ["Fix Status", fix_status],
        ["Scripts Run", str(len(state.get("scripts_executed", [])))],
        ["Notion Post-Mortem", state.get("notion_page_url") or "Not published"],
    ]

    table = Table(summary_data, colWidths=[4 * cm, 13 * cm])
    table.setStyle(TableStyle([
        ("BACKGROUND",  (0, 0), (-1, 0),  colors.HexColor("#0f172a")),
        ("TEXTCOLOR",   (0, 0), (-1, 0),  colors.white),
        ("FONTNAME",    (0, 0), (-1, 0),  "Helvetica-Bold"),
        ("FONTSIZE",    (0, 0), (-1, 0),  10),
        ("BACKGROUND",  (0, 1), (-1, -1), colors.HexColor("#f8fafc")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.HexColor("#f8fafc"), colors.white]),
        ("GRID",        (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
        ("VALIGN",      (0, 0), (-1, -1), "TOP"),
        ("FONTSIZE",    (0, 1), (-1, -1), 9),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING",(0, 0), (-1, -1), 8),
        ("TOPPADDING",  (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 6),
    ]))
    story.append(table)
    story.append(Spacer(1, 0.6 * cm))

    # ── Incident description ──────────────────────────────────────────────
    story.append(_section_heading("Incident Description", styles))
    story.append(Paragraph(state.get("incident_prompt", "No description"), styles["Normal"]))
    story.append(Spacer(1, 0.4 * cm))

    # ── Corroborating signals ─────────────────────────────────────────────
    signals = state.get("corroborating_signals", [])
    if signals:
        story.append(_section_heading("Corroborating Signals", styles))
        for signal in signals:
            story.append(Paragraph(f"• {signal}", styles["Normal"]))
        story.append(Spacer(1, 0.4 * cm))

    # ── Scripts executed ──────────────────────────────────────────────────
    scripts = state.get("scripts_executed", [])
    if scripts:
        story.append(_section_heading("Scripts Executed", styles))
        code_style = ParagraphStyle(
            "Code",
            parent=styles["Code"],
            fontSize=7,
            fontName="Courier",
            backColor=colors.HexColor("#f1f5f9"),
            leftIndent=10,
            spaceAfter=8,
        )
        for i, script in enumerate(scripts, 1):
            status = "✅ Success" if script.get("success") else "❌ Failed"
            story.append(Paragraph(f"<b>Script {i} — {status}</b>", styles["Normal"]))
            story.append(Paragraph(
                (script.get("script") or "")[:600].replace("\n", "<br/>"),
                code_style,
            ))
            if script.get("output"):
                story.append(Paragraph(
                    f"<b>Output:</b> {script['output'][:300]}",
                    styles["Normal"],
                ))
            story.append(Spacer(1, 0.2 * cm))

    # ── Proposed fix ──────────────────────────────────────────────────────
    if state.get("proposed_fix"):
        story.append(_section_heading("Proposed Fix", styles))
        story.append(Paragraph(state["proposed_fix"], styles["Normal"]))
        if state.get("fix_blocked_reason"):
            story.append(Spacer(1, 0.2 * cm))
            story.append(Paragraph(
                f"<b>Block reason:</b> {state['fix_blocked_reason']}",
                ParagraphStyle("Warning", parent=styles["Normal"], textColor=colors.HexColor("#dc2626")),
            ))
        story.append(Spacer(1, 0.4 * cm))

    # ── Step log ──────────────────────────────────────────────────────────
    step_log = state.get("step_log", [])
    if step_log:
        story.append(_section_heading("Investigation Timeline", styles))
        small = ParagraphStyle("Small", parent=styles["Normal"], fontSize=8, spaceAfter=2)
        for entry in step_log:
            story.append(Paragraph(entry[:300], small))

    doc.build(story)


def _section_heading(text: str, styles) -> Paragraph:
    return Paragraph(
        text,
        ParagraphStyle(
            "SectionHead",
            parent=styles["Heading2"],
            fontSize=12,
            textColor=colors.HexColor("#0f172a"),
            spaceBefore=12,
            spaceAfter=6,
            borderPad=0,
        ),
    )
