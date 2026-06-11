"""
agents/cost_reporter.py
-----------------------
Generates a PDF post-mortem for the Cloud Cost Optimization agent.
Uses reportlab (same approach as Genesis report_generator.py).
Emits GENESIS_REPORT_READY SSE event on completion.
"""

import os
import json
from datetime import datetime
from pathlib import Path
from core.cost_state import CostAgentState

REPORTS_DIR = Path("reports")
REPORTS_DIR.mkdir(exist_ok=True)

# ── waste category display config ─────────────────────────────────────────────
CATEGORY_META = {
    "idle_vm": {
        "label":   "Idle Compute Instances",
        "icon":    "🖥️",
        "action":  "Stop or delete instances with avg CPU < 3% for 14+ days",
    },
    "oversized_vm": {
        "label":   "Oversized VM Instances",
        "icon":    "📦",
        "action":  "Downsize to recommended machine type; estimated 60–75% cost reduction per instance",
    },
    "overprovisioned_cloud_run": {
        "label":   "Overprovisioned Cloud Run Services",
        "icon":    "☁️",
        "action":  "Delete or scale-to-zero services with no requests in 7+ days",
    },
    "orphaned_storage": {
        "label":   "Orphaned GCS Buckets",
        "icon":    "🗄️",
        "action":  "Add lifecycle rules or delete buckets not accessed in 90+ days",
    },
    "expensive_bq_jobs": {
        "label":   "Expensive BigQuery Jobs",
        "icon":    "🔍",
        "action":  "Add partition filters and clustering; use LIMIT during development",
    },
}


async def generate_cost_report(state: CostAgentState) -> CostAgentState:
    """Generate PDF report and return updated state with report_path."""
    findings  = state.get("findings", [])
    beliefs   = state.get("waste_beliefs", {})
    iteration = state.get("iteration", 0)
    prompt    = state.get("incident_prompt", "Cloud cost investigation")

    timestamp  = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    report_name = f"cost_report_{timestamp}.pdf"
    report_path = REPORTS_DIR / report_name

    try:
        _generate_pdf(report_path, findings, beliefs, iteration, prompt)
        print(f"[CostReporter] PDF generated: {report_path}")
    except Exception as e:
        print(f"[CostReporter] PDF generation failed: {e}")
        # Fallback to JSON report
        report_path = REPORTS_DIR / f"cost_report_{timestamp}.json"
        with open(report_path, "w") as f:
            json.dump({
                "findings": findings,
                "beliefs":  beliefs,
                "iterations": iteration,
                "generated_at": datetime.utcnow().isoformat(),
            }, f, indent=2)

    return {**state, "report_path": str(report_path), "phase": "complete"}


def _generate_pdf(path, findings, beliefs, iterations, prompt):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
    )

    doc  = SimpleDocTemplate(str(path), pagesize=A4,
                             leftMargin=2*cm, rightMargin=2*cm,
                             topMargin=2*cm,  bottomMargin=2*cm)
    styles = getSampleStyleSheet()

    # Custom styles
    title_style = ParagraphStyle("Title",
        fontName="Helvetica-Bold", fontSize=22, textColor=colors.HexColor("#0F172A"),
        spaceAfter=6)
    sub_style = ParagraphStyle("Sub",
        fontName="Helvetica", fontSize=11, textColor=colors.HexColor("#64748B"),
        spaceAfter=12)
    h2_style = ParagraphStyle("H2",
        fontName="Helvetica-Bold", fontSize=14, textColor=colors.HexColor("#1E293B"),
        spaceBefore=16, spaceAfter=6)
    body_style = ParagraphStyle("Body",
        fontName="Helvetica", fontSize=10, textColor=colors.HexColor("#374151"),
        leading=14)
    red_style = ParagraphStyle("Red",
        fontName="Helvetica-Bold", fontSize=10, textColor=colors.HexColor("#DC2626"))
    green_style = ParagraphStyle("Green",
        fontName="Helvetica-Bold", fontSize=10, textColor=colors.HexColor("#16A34A"))

    story = []

    # ── header ────────────────────────────────────────────────────────────────
    story.append(Paragraph("Genesis Cloud Cost Report", title_style))
    story.append(Paragraph(
        f"Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}  |  "
        f"Iterations: {iterations}  |  Agent: Genesis Cost Optimizer v1.0",
        sub_style))
    story.append(HRFlowable(width="100%", thickness=2,
                             color=colors.HexColor("#3B82F6"), spaceAfter=12))

    # ── prompt ────────────────────────────────────────────────────────────────
    story.append(Paragraph("Investigation Prompt", h2_style))
    story.append(Paragraph(prompt, body_style))
    story.append(Spacer(1, 12))

    # ── executive summary ─────────────────────────────────────────────────────
    story.append(Paragraph("Executive Summary", h2_style))

    total_waste = sum(f.get("total_monthly_waste", 0) for f in findings)
    total_annual = total_waste * 12
    total_resources = sum(f.get("count", 0) for f in findings)

    summary_data = [
        ["Metric", "Value"],
        ["Total waste resources found",   str(total_resources)],
        ["Monthly wasted spend",          f"${total_waste:,.2f}"],
        ["Projected annual waste",        f"${total_annual:,.2f}"],
        ["Waste categories confirmed",    str(len(findings))],
        ["Agent confidence (avg)",        f"{sum(beliefs.values())/len(beliefs)*100:.0f}%" if beliefs else "N/A"],
    ]
    t = Table(summary_data, colWidths=[10*cm, 7*cm])
    t.setStyle(TableStyle([
        ("BACKGROUND",  (0,0), (-1,0), colors.HexColor("#1E293B")),
        ("TEXTCOLOR",   (0,0), (-1,0), colors.white),
        ("FONTNAME",    (0,0), (-1,0), "Helvetica-Bold"),
        ("FONTSIZE",    (0,0), (-1,-1), 10),
        ("GRID",        (0,0), (-1,-1), 0.5, colors.HexColor("#E2E8F0")),
        ("ROWBACKGROUNDS", (0,1), (-1,-1),
            [colors.HexColor("#F8FAFC"), colors.HexColor("#FFFFFF")]),
        ("LEFTPADDING",  (0,0), (-1,-1), 8),
        ("RIGHTPADDING", (0,0), (-1,-1), 8),
        ("TOPPADDING",   (0,0), (-1,-1), 6),
        ("BOTTOMPADDING",(0,0), (-1,-1), 6),
    ]))
    story.append(t)
    story.append(Spacer(1, 16))

    # ── Bayesian belief state ─────────────────────────────────────────────────
    story.append(Paragraph("Bayesian Waste Confidence State", h2_style))
    story.append(Paragraph(
        "Genesis maintains a probabilistic belief over each waste category, "
        "updated after every script execution. This distinguishes Genesis from "
        "rule-based scanners — it reasons about evidence, not just thresholds.",
        body_style))
    story.append(Spacer(1, 8))

    belief_data = [["Waste Category", "Confidence", "Status"]]
    for cat, conf in sorted(beliefs.items(), key=lambda x: -x[1]):
        meta   = CATEGORY_META.get(cat, {})
        label  = meta.get("label", cat)
        status = "✅ Confirmed" if conf >= 0.80 else ("⚠️ Partial" if conf >= 0.50 else "❓ Unconfirmed")
        belief_data.append([label, f"{conf*100:.0f}%", status])

    bt = Table(belief_data, colWidths=[9*cm, 3*cm, 5*cm])
    bt.setStyle(TableStyle([
        ("BACKGROUND",  (0,0), (-1,0), colors.HexColor("#1E3A5F")),
        ("TEXTCOLOR",   (0,0), (-1,0), colors.white),
        ("FONTNAME",    (0,0), (-1,0), "Helvetica-Bold"),
        ("FONTSIZE",    (0,0), (-1,-1), 10),
        ("GRID",        (0,0), (-1,-1), 0.5, colors.HexColor("#E2E8F0")),
        ("ROWBACKGROUNDS", (0,1), (-1,-1),
            [colors.HexColor("#EFF6FF"), colors.HexColor("#FFFFFF")]),
        ("LEFTPADDING",  (0,0), (-1,-1), 8),
        ("RIGHTPADDING", (0,0), (-1,-1), 8),
        ("TOPPADDING",   (0,0), (-1,-1), 6),
        ("BOTTOMPADDING",(0,0), (-1,-1), 6),
    ]))
    story.append(bt)
    story.append(Spacer(1, 16))

    # ── detailed findings ─────────────────────────────────────────────────────
    story.append(Paragraph("Detailed Findings", h2_style))

    if not findings:
        story.append(Paragraph("No confirmed findings in this run.", body_style))
    else:
        for i, finding in enumerate(findings, 1):
            cat   = finding.get("category", "unknown")
            meta  = CATEGORY_META.get(cat, {})
            label = meta.get("label", cat)
            icon  = meta.get("icon", "•")
            count = finding.get("count", 0)
            waste = finding.get("total_monthly_waste", 0)
            ev    = finding.get("evidence", "")
            rec   = finding.get("recommendation", meta.get("action", ""))

            story.append(Paragraph(f"{icon}  Finding {i}: {label}", h2_style))

            fd = [
                ["Field",                 "Value"],
                ["Resources affected",    str(count)],
                ["Monthly waste",         f"${waste:,.2f}"],
                ["Annual projection",     f"${waste*12:,.2f}"],
                ["Evidence",              ev],
                ["Recommendation",        rec],
            ]
            ft = Table(fd, colWidths=[5*cm, 12*cm])
            ft.setStyle(TableStyle([
                ("BACKGROUND",  (0,0), (0,-1), colors.HexColor("#F1F5F9")),
                ("FONTNAME",    (0,0), (0,-1), "Helvetica-Bold"),
                ("FONTSIZE",    (0,0), (-1,-1), 9),
                ("GRID",        (0,0), (-1,-1), 0.5, colors.HexColor("#E2E8F0")),
                ("LEFTPADDING",  (0,0), (-1,-1), 8),
                ("RIGHTPADDING", (0,0), (-1,-1), 8),
                ("TOPPADDING",   (0,0), (-1,-1), 5),
                ("BOTTOMPADDING",(0,0), (-1,-1), 5),
                ("VALIGN",       (0,0), (-1,-1), "TOP"),
                ("WORDWRAP",     (0,0), (-1,-1), True),
            ]))
            story.append(ft)
            story.append(Spacer(1, 10))

    # ── footer ────────────────────────────────────────────────────────────────
    story.append(Spacer(1, 20))
    story.append(HRFlowable(width="100%", thickness=1,
                             color=colors.HexColor("#CBD5E1")))
    story.append(Spacer(1, 6))
    story.append(Paragraph(
        "Generated by Genesis Cloud Cost Optimization Agent  |  "
        "Powered by Gemini 2.0 Flash + LangGraph + E2B  |  "
        "Traced by Arize Phoenix",
        ParagraphStyle("footer", fontName="Helvetica", fontSize=8,
                       textColor=colors.HexColor("#94A3B8"))))

    doc.build(story)