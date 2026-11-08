"""
reports/pdf_export.py — the full case PDF report builder.

  export_report_pdf(report_data)   the Gradio button handler; builds the
                                    entire multi-section PDF via reportlab
                                    and returns gr.update(value=path) (or
                                    gr.update(visible=False) on failure).
  _compute_ai_verdict              private helper, only used here.

reportlab imports are LOCAL (inside export_report_pdf itself, exactly as
they were in the original file) rather than at module level here — kept
as-is to avoid changing behavior during the move.

Extracted from gradio_app.py, verbatim (was ~2,770 lines inline, was the
single largest function in the file).
"""

import io
import re
import time
import traceback
from datetime import datetime

import gradio as gr

from config import log
from reports.charts import (
    _pdf_network_diagram, _pdf_crime_dna_radar, _pdf_evidence_provided_chart,
    _pdf_fraud_indicators_chart, _pdf_hypothesis_confidence_chart,
    _pdf_risk_signals_chart, _pdf_evidence_coverage_chart, _pdf_progress_bar,
    _kg_nodes_edges, _criminal_network_nodes_edges,
)
from utils import (
    _safe_truncate, _display_watchlist_status, _hypothesis_display_status,
    calibrate_deepfake_result,
)


# -- Section 2: Live Tracking (appended at PDF end) --
try:
    from tracking.api import (
        get_live_map_data, get_recent_alerts, list_sources, get_entity_trail,
    )
    TRACKING_AVAILABLE = True
except ImportError:
    TRACKING_AVAILABLE = False


def _compute_ai_verdict(adv, external_risk_level=None):
    """Derives the top-of-report 'AI Verdict' summary (star rating,
    Probability of Organized Crime, Inside Assistance, Professional
    Planning, Repeat Crime Chance, Immediate Threat) purely from data
    already computed by the advanced pipeline — no extra engine calls.

    external_risk_level: the ORIGINAL 4-engine pipeline's own, separate
    Risk Assessment level (e.g. from nexforensics_engine_final.py). That
    engine and the advanced pipeline's executive_dashboard/case_status can
    independently disagree about how dangerous the case looks (e.g. one
    says HIGH, the other LOW) — when they do, this report reports the more
    severe of the two rather than silently picking one, which would
    otherwise show a "HIGH" Immediate Threat next to a "LOW" Risk Level
    elsewhere in the same document."""
    hyps = (adv.get('hypothesis_ranking', {}) or {}).get('top_hypotheses', []) or []
    dna = adv.get('crime_dna', {}) or {}
    ed = adv.get('executive_dashboard', {}) or {}

    def _hyp_confidence(*name_fragments):
        for h in hyps:
            name = str(h.get('name', '')).lower()
            if any(frag in name for frag in name_fragments):
                return h.get('confidence', 0), h.get('evidence_for', []) or []
        return None, []

    organized_crime, organized_crime_basis = _hyp_confidence('gang', 'professional criminal', 'organized')
    if organized_crime is None:
        vals = [dna[k] for k in ('planning', 'technical', 'team') if isinstance(dna.get(k), (int, float))]
        organized_crime = round(sum(vals) / len(vals) * 10) if vals else "N/A"
        organized_crime_basis = [k.replace('_', ' ').title() for k in ('planning', 'technical', 'team')
                                  if isinstance(dna.get(k), (int, float))]

    inside_assistance, inside_assistance_basis = _hyp_confidence('insider', 'inside job', 'employee', 'staff collusion')
    if inside_assistance is None:
        inside_assistance = "N/A"

    professional_planning = dna.get('planning')
    professional_planning_basis = ["Planning"] if isinstance(professional_planning, (int, float)) else []
    professional_planning = professional_planning * 10 if isinstance(professional_planning, (int, float)) else "N/A"

    tier1 = adv.get('tier1_intelligence', {}) or {}
    repeat_crime = tier1.get('mo_evolution')
    repeat_crime = repeat_crime if isinstance(repeat_crime, (int, float)) else "N/A"

    case_status = str(ed.get('case_status', ''))
    if 'CRITICAL' in case_status.upper():
        threat_from_status = "CRITICAL"
    elif 'HIGH' in case_status.upper():
        threat_from_status = "HIGH"
    else:
        threat_from_status = "MODERATE"

    _rank = {"LOW": 0, "MODERATE": 1, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}
    _label_by_rank = {0: "LOW", 1: "MODERATE", 2: "HIGH", 3: "CRITICAL"}
    r_status = _rank.get(threat_from_status, 1)
    r_external = _rank.get(str(external_risk_level or "").upper(), 1)
    threat_label = _label_by_rank[max(r_status, r_external)]

    fused = ed.get('fused_confidence', 0) or 0
    try:
        stars = max(1, min(5, round(float(fused) / 20)))
    except (TypeError, ValueError):
        stars = 3

    return {
        'stars': stars,
        'organized_crime': organized_crime,
        'organized_crime_basis': organized_crime_basis,
        'inside_assistance': inside_assistance,
        'inside_assistance_basis': inside_assistance_basis,
        'professional_planning': professional_planning,
        'professional_planning_basis': professional_planning_basis,
        'repeat_crime': repeat_crime,
        'immediate_threat': threat_label,
    }



def export_report_pdf(report_data):
    if not report_data:
        return gr.update(value=None, visible=False)

    def _safe_num(val, default=0):
        """Coerce a value that SHOULD be numeric (but comes from external/
        varied-type data — hypothesis confidence, fraud scores, etc.) into
        a float, instead of assuming its type and crashing on comparison.
        This exact 'str vs int' TypeError has hit multiple separate
        comparisons in this function — this is the fix applied everywhere
        such a comparison happens."""
        try:
            if val is None:
                return default
            return float(val)
        except (TypeError, ValueError):
            return default

    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.lib import colors
        from reportlab.lib.utils import ImageReader
        from reportlab.lib.units import mm
        from reportlab.lib.enums import TA_CENTER, TA_LEFT
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.platypus import (SimpleDocTemplate, Table, TableStyle,
                                         Paragraph, Spacer, HRFlowable, PageBreak, KeepTogether)
        from reportlab.pdfgen import canvas
        import time, io

        d = report_data
        safe_case = (d.get("case_id") or "report").strip().replace(" ", "_").replace("/", "-") or "report"
        out_path = f"/tmp/investigatorai_{safe_case}_{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}.pdf"

        NAVY   = colors.HexColor("#0b1220")
        RED    = colors.HexColor("#dc2626")
        GRAY   = colors.HexColor("#94a3b8")
        LGRAY  = colors.HexColor("#f1f5f9")
        BORDER = colors.HexColor("#e2e8f0")
        DARK   = colors.black
        BAR_H  = 78
        AMBER  = colors.HexColor("#f59e0b")
        GREEN  = colors.HexColor("#16a34a")

        def severity_color(val):
            if val is None: return GRAY
            if isinstance(val, str):
                if val in ["CRITICAL", "HIGH", "DECEASED", "YES"]:
                    return RED
                if val in ["Medium", "MODERATE"]:
                    return AMBER
                if val in ["N/A", "NOT ASSESSED", "UNKNOWN"]:
                    return GRAY
                # DOA 2026-11-05: "not found in the sources searched" is not a clean bill
                if val.upper().startswith(("NOT FOUND", "NOT APPLICABLE", "US-ONLY", "NO MATCH RETURNED")):
                    return GRAY
                return GREEN
            if val > 75: return RED
            if val > 50: return AMBER
            return GREEN

        LOGO_CROPS = {
            "nx": ("/home/nexforensics/app/nexforensics_logo.png", (640, 500, 1439, 1248)),
            "ia": ("/home/nexforensics/app/investigator-Logo.png", (641, 392, 1357, 1332)),
        }
        _logo_cache = {}

        def get_logo_reader(key):
            if key in _logo_cache:
                return _logo_cache[key]
            path, box = LOGO_CROPS[key]
            try:
                from PIL import Image
                img = Image.open(path).convert("RGBA")
                x0, y0, x1, y1 = box
                padx, pady = int((x1 - x0) * 0.05), int((y1 - y0) * 0.05)
                safe_box = (max(0, x0 - padx), max(0, y0 - pady), x1 + padx, y1 + pady)
                cropped = img.crop(safe_box)
                buf = io.BytesIO()
                cropped.save(buf, format="PNG")
                buf.seek(0)
                result = (ImageReader(buf), cropped.width, cropped.height)
            except Exception as e:
                log.warning(f"PDF logo load failed ({key}): {e}")
                result = (None, 0, 0)
            _logo_cache[key] = result
            return result

        def draw_circular_logo(c, key, cx, cy, r):
            reader, pw, ph = get_logo_reader(key)
            c.saveState()
            p = c.beginPath()
            p.circle(cx, cy, r)
            c.clipPath(p, stroke=0, fill=0)
            c.setFillColor(colors.white)
            c.rect(cx - r, cy - r, 2 * r, 2 * r, fill=1, stroke=0)
            if reader is not None:
                diag = (pw ** 2 + ph ** 2) ** 0.5
                scale = (2 * r * 0.88) / diag
                dw, dh = pw * scale, ph * scale
                c.drawImage(reader, cx - dw / 2, cy - dh / 2, width=dw, height=dh, mask='auto')
            else:
                c.setFillColor(NAVY)
                c.setFont("Times-Bold", r)
                c.drawCentredString(cx, cy - r * 0.35, "N" if key == "nx" else "I")
            c.restoreState()
            # Scoped separately so the stroke settings below never leak into
            # whatever canvas drawing happens next (see draw_spaced_centered
            # for why unscoped graphics-state changes are dangerous here).
            c.saveState()
            c.setStrokeColor(RED)
            c.setLineWidth(1.6)
            c.circle(cx, cy, r, stroke=1, fill=0)
            c.restoreState()

        def draw_spaced_centered(c, text, cx, y, font, size, char_space, color):
            # IMPORTANT: setCharSpace() writes a Tc (character-spacing) operator
            # into the PDF content stream, which is part of the graphics state
            # and — unless explicitly saved/restored — leaks into every text
            # drawn afterwards, including all of Platypus's own Paragraph/Table
            # text later on the page. That extra spacing makes Platypus's
            # actual rendered text wider than what it calculated during word
            # wrapping, so lines run past their column/frame width and
            # visually collide with whatever sits next to or below them —
            # this was the cause of the widespread text/column overlap
            # throughout the report. saveState/restoreState scopes the char
            # spacing to just this label.
            c.saveState()
            c.setFont(font, size)
            text_w = c.stringWidth(text, font, size) + char_space * (len(text) - 1)
            tx = c.beginText(cx - text_w / 2, y)
            tx.setFont(font, size)
            tx.setCharSpace(char_space)
            tx.setFillColor(color)
            tx.textOut(text)
            c.drawText(tx)
            c.restoreState()

        def draw_fitted_centered(c, text, cx, y, font, max_size, color, max_width, min_size=9):
            """Draws text centered at (cx, y), shrinking the font size as
            needed so it never overlaps whatever sits on either side (here:
            the two circular header logos) — fixes the title text running
            out past the badges at the default fixed size."""
            size = max_size
            while size > min_size and c.stringWidth(text, font, size) > max_width:
                size -= 0.5
            c.setFillColor(color)
            c.setFont(font, size)
            c.drawCentredString(cx, y, text)
            return size

        # DOA 2026-11-05: integrity footer (timezone-aware time + SHA-256 of the report data)
        try:
            import hashlib as _hl, json as _js
            from zoneinfo import ZoneInfo as _ZI
            _content_sha = _hl.sha256(_js.dumps(report_data, sort_keys=True, default=str).encode()).hexdigest()
            _gen_time = datetime.now(_ZI("Asia/Kolkata")).strftime("%Y-%m-%d %H:%M IST (UTC+05:30)")
        except Exception:
            _content_sha, _gen_time = "n/a", datetime.now().strftime("%Y-%m-%d %H:%M (server time)")

        def on_page(c, doc_):
            c.saveState()
            width, height = letter
            margin_x = doc_.leftMargin
            c.setFillColor(NAVY)
            c.rect(0, height - BAR_H, width, BAR_H, fill=1, stroke=0)
            mid_y = height - BAR_H / 2
            badge_r = 22
            draw_circular_logo(c, "nx", margin_x + badge_r, mid_y, badge_r)
            draw_circular_logo(c, "ia", width - margin_x - badge_r, mid_y, badge_r)
            title_max_width = width - 2 * (margin_x + 2 * badge_r) - 16
            title_size = draw_fitted_centered(
                c, "NexForensics Investigation Intelligence Report",
                width / 2, mid_y + 6, "Times-Bold", 18, colors.white, title_max_width,
            )
            draw_spaced_centered(c, "SIGNAL TO EVIDENCE", width / 2, mid_y - (14 if title_size >= 14 else 12),
                                  "Times-Roman", 8, 2.4, GRAY)
            FOOTER_GRAY = colors.HexColor("#475569")
            c.setFont("Times-Bold", 7.5)
            c.setFillColor(FOOTER_GRAY)
            c.drawCentredString(width / 2, 32,
                "CONFIDENTIAL — AI-generated report. Must be reviewed by a qualified investigator.")
            c.drawString(margin_x, 18, f"Case: {safe_case}  |  Generated {_gen_time}  |  Content SHA-256 {_content_sha[:16]}… (full value in Report Integrity section)")
            c.drawRightString(width - margin_x, 18, f"Page {c.getPageNumber()}")
            # Belt-and-suspenders: guarantees a clean graphics/text state
            # (font, colors, char-spacing, line width, clip path...) for
            # every flowable Platypus draws next, regardless of what any
            # header-drawing helper above did or forgot to reset.
            c.restoreState()

        styles = getSampleStyleSheet()
        h2 = ParagraphStyle("h2", parent=styles["Heading2"], fontSize=11,
                             textColor=DARK, spaceBefore=14, spaceAfter=6, fontName="Times-Bold")
        h3 = ParagraphStyle("h3", parent=styles["Heading3"], fontSize=10,
                             textColor=DARK, spaceBefore=10, spaceAfter=4, fontName="Times-Bold")
        body = ParagraphStyle("body", parent=styles["Normal"], fontSize=9.5,
                               textColor=colors.black, leading=13)
        small = ParagraphStyle("small", parent=styles["Normal"], fontSize=8.5,
                                textColor=colors.black,
                                fontName="Times-Bold", leading=12)
        # White, bold header-row style — used for the label row of every table
        # whose TableStyle sets a DARK background on row 0. TableStyle's
        # TEXTCOLOR command has no effect on Paragraph flowables (only plain
        # strings), so those header cells were previously rendered in
        # `small`'s black text on a near-black background — invisible.
        th = ParagraphStyle("th", parent=styles["Normal"], fontSize=8.5,
                             textColor=colors.white,
                             fontName="Times-Bold", leading=12)
        card_num = ParagraphStyle("cardnum", fontName="Times-Bold", fontSize=22,
                                   leading=26, alignment=TA_CENTER)
        card_lbl = ParagraphStyle("cardlbl", fontName="Times-Roman", fontSize=8,
                                   leading=11, spaceBefore=4, alignment=TA_CENTER, textColor=GRAY)
        verdict_title = ParagraphStyle("vtitle", fontName="Times-Bold", fontSize=13,
                                        textColor=colors.white)
        verdict_body = ParagraphStyle("vbody", fontName="Times-Roman", fontSize=9.5,
                                       textColor=colors.white, leading=13)
        alert_red = ParagraphStyle("alertred", fontName="Times-Bold", fontSize=9,
                                    textColor=RED, leading=13)
        alert_amber = ParagraphStyle("alertamber", fontName="Times-Bold", fontSize=9,
                                      textColor=AMBER, leading=13)
        evidence_style = ParagraphStyle("evidence", fontName="Times-Roman", fontSize=9,
                                           textColor=colors.black, leading=12)

        def P(text, style=body):
            return Paragraph(str(text), style)

        def severity_cell(val):
            col = severity_color(val)
            return Paragraph(f'<font color="{col.hexval()}"><b>{val}</b></font>', body)

        story = []

        def _fbi_display(wl_):
            raw = str(wl_.get("fbi_watchlist", "NO") or "NO")
            if raw.upper() not in ("NO", "", "NONE", "N/A", "NO MATCH RETURNED"):
                return _display_watchlist_status(_safe_truncate(raw, 50))      # a real hit is never hidden
            j = str(d.get("crime_jurisdiction", "") or "").strip().lower()
            if any(x in f" {j} " for x in (" us ", " usa ", "united states", " u.s.", "america")):
                return _display_watchlist_status(_safe_truncate(raw, 50))
            return "NOT APPLICABLE (non-US case)" if j and j not in ("n/a", "unknown") else "US-ONLY LIST (not applicable)"

        def _honest_negative(val):
            v = str(val or "")
            if v.upper().startswith("NO CONFIRMED RECORD"):
                return "NOT FOUND in the local watchlist datasets searched (only weak name-fragment matches)"
            if v.upper().startswith("NO RECORD") or v.upper() in ("NO", "NONE"):
                return "NOT FOUND in the local watchlist datasets searched"
            return v

        # ── AI VERDICT — the first thing a senior officer should see ──────
        _adv_top = (d.get("investigator", {}) or {}).get("advanced", {}) or {}
        if _adv_top and "error" not in _adv_top:
            _external_risk_level = (d.get("investigator", {}) or {}).get("risk", {}).get("level")
            verdict = _compute_ai_verdict(_adv_top, external_risk_level=_external_risk_level)
            # DOA 2026-11-05: hypothesis percentages are withheld when evidence coverage is too low
            # (same 25% threshold the Crime DNA section uses), instead of e.g. "Organized Crime 30%"
            # on a case with ~0% evidence.
            try:
                _ev_cov = float((d.get("intel_summary", {}) or {}).get("completeness_pct", 0) or 0)
            except (TypeError, ValueError):
                _ev_cov = 0.0
            _verdict_gated = _ev_cov < 25
            if _verdict_gated:
                for _k in ("organized_crime", "inside_assistance", "professional_planning", "repeat_crime"):
                    if isinstance(verdict.get(_k), (int, float)):
                        verdict[_k] = "N/A"
                verdict["organized_crime_basis"] = []
                verdict["inside_assistance_basis"] = []
                verdict["immediate_threat"] = "N/A"     # 2026-11-06: no threat level without evidence
            stars_html = (
                f'<font color="white">{"★" * verdict["stars"]}</font>'
                f'<font color="#475569">{"★" * (5 - verdict["stars"])}</font>'
            )
            verdict_style = ParagraphStyle("verdict", fontName="Times-Roman", fontSize=10,
                                            textColor=colors.white, leading=15)
            verdict_label_style = ParagraphStyle("verdictlbl", fontName="Times-Roman", fontSize=8,
                                                  textColor=colors.HexColor("#cbd5e1"), leading=11)
            verdict_num_style = ParagraphStyle("verdictnum", fontName="Times-Bold", fontSize=15,
                                                textColor=colors.white, leading=18)

            def _verdict_metric(label, val):
                disp = f"{val}%" if isinstance(val, (int, float)) else str(val)
                st = verdict_num_style if (isinstance(val, (int, float)) or len(disp) <= 4) else ParagraphStyle(
                    "verdictnum_s", parent=verdict_num_style, fontSize=9.5, leading=12)
                return [Paragraph(disp, st), Paragraph(label, verdict_label_style)]

            verdict_header = Table([[
                Paragraph((f"AI VERDICT: NOT ASSESSED (evidence coverage {_ev_cov:.0f}%)" if _verdict_gated else
                           f"AI VERDICT&nbsp;&nbsp;&nbsp;<font size=13>{stars_html}</font>"),
                          ParagraphStyle("verdicttitle", fontName="Times-Bold", fontSize=13,
                                         textColor=colors.white)),
            ]], colWidths=[480])
            verdict_header.setStyle(TableStyle([
                ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ]))

            verdict_metrics = Table([[
                _verdict_metric("Organized Crime", verdict["organized_crime"]),
                _verdict_metric("Inside Assistance", verdict["inside_assistance"]),
                _verdict_metric("Professional Planning", verdict["professional_planning"]),
                _verdict_metric("Repeat Crime Chance", verdict["repeat_crime"]),
                _verdict_metric("Immediate Threat", verdict["immediate_threat"]),
            ]], colWidths=[96, 96, 96, 96, 96])
            verdict_metrics.setStyle(TableStyle([
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ]))

            verdict_box = Table([[verdict_header], [verdict_metrics]], colWidths=[480])
            verdict_box.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#0f172a")),
                ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#334155")),
                ("TOPPADDING", (0, 0), (-1, -1), 10), ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
                ("LEFTPADDING", (0, 0), (-1, -1), 14), ("RIGHTPADDING", (0, 0), (-1, -1), 14),
            ]))
            story.append(KeepTogether(verdict_box))
            if _verdict_gated:
                story.append(Spacer(1, 4))
                story.append(Paragraph(
                    f"<b>Hypothesis percentages withheld:</b> Evidence-Type Coverage is {_ev_cov:g}%, below the 25% "
                    "needed to support them. They are shown as N/A, not as zero risk.", small))
            # NEW: risk/verdict signals bar chart — added per user request
            # for more visual coverage; makes it visually clear these five
            # numbers are different independent signals on the same 0-100
            # scale, not one score contradicting itself.
            _risk_chart_data = [
                ("Organized Crime", verdict.get("organized_crime")),
                ("Inside Assist.", verdict.get("inside_assistance")),
                ("Prof. Planning", verdict.get("professional_planning")),
                ("Repeat Crime", verdict.get("repeat_crime")),
                ("Immediate Threat", verdict.get("immediate_threat")),
            ]
            _risk_chart = _pdf_risk_signals_chart(_risk_chart_data)
            if _risk_chart:
                story.append(Spacer(1, 6))
                story.append(_risk_chart)
            story.append(P(
                "These five figures are independent AI-suggested signals (hypothesis confidence, "
                "not confirmed findings) — see \"Unified Severity / Confidence Table\" and "
                "\"Confidence Taxonomy Summary\" later in this report for what each number type means "
                "and why they can legitimately differ from each other.",
                small
            ))

            # Evidence basis footnote — so each percentage above is
            # traceable to what actually produced it, not a black box.
            _basis_bits = []
            if verdict.get("organized_crime_basis"):
                _basis_bits.append(f"Organized Crime {verdict['organized_crime']}%: " +
                                    ", ".join(verdict["organized_crime_basis"][:5]))
            if verdict.get("inside_assistance_basis"):
                _basis_bits.append(f"Inside Assistance {verdict['inside_assistance']}%: " +
                                    ", ".join(verdict["inside_assistance_basis"][:5]))
            if _basis_bits:
                story.append(Spacer(1, 3))
                story.append(P("Evidence basis — " + "  |  ".join(_basis_bits), evidence_style))
            story.append(Spacer(1, 14))

        # ── SIGNAL CONSISTENCY CHECK ────────────────────────────────────
        # Several independent scoring paths in this report can each reach
        # a different severity conclusion about the same case (Crime
        # Classification's keyword-based severity, the Investigator
        # Engine's own separate Risk Assessment, and the Advanced
        # pipeline's hypothesis-driven Immediate Threat). Rather than
        # silently letting them disagree — or forcing a fake agreement by
        # overwriting one with another — this section states plainly when
        # they don't line up, so the disagreement is something a human
        # investigator reviews deliberately, not something that undermines
        # trust by only being noticed later.
        #
        # These findings are also merged into the Reasoning Engine's
        # "Contradictions" count further below — a report showing
        # "Contradictions (0)" right next to a Signal Consistency Check
        # warning was itself a glaring, self-undermining inconsistency.
        _signal_contradictions = []
        _rank = {"LOW": 0, "MODERATE": 1, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}
        _sev_signals = []
        _crime_sev = str(d.get("crime_severity", "") or "").upper()
        if _crime_sev:
            _sev_signals.append(("Crime Classification Severity", _crime_sev))
        _risk_lvl = str((d.get("investigator", {}) or {}).get("risk", {}).get("level", "") or "").upper()
        if _risk_lvl:
            _sev_signals.append(("Risk Assessment (Investigator Engine)", _risk_lvl))
        if _adv_top and "error" not in _adv_top:
            _sev_signals.append(("AI Verdict Immediate Threat", verdict["immediate_threat"]))

        _known_signals = [(name, lvl) for name, lvl in _sev_signals if lvl in _rank]
        if len(_known_signals) >= 2:
            _ranks_seen = {_rank[lvl] for _, lvl in _known_signals}
            if len(_ranks_seen) > 1:
                _signal_contradictions.append({
                    "contradiction": "Independent severity signals disagree: " +
                        "; ".join(f"{name}: {lvl.title()}" for name, lvl in _known_signals),
                    "sources": ", ".join(name for name, _ in _known_signals),
                    "severity": "High",
                })
                story.append(P(
                    "⚠ Signal Consistency Check: This report's independent scoring paths do not agree "
                    "on this case's severity — " +
                    "; ".join(f"{name}: {lvl.title()}" for name, lvl in _known_signals) +
                    ". This is not a data error; each reflects a different sub-analysis "
                    "(keyword-matched crime severity vs. the Investigator Engine's own risk model vs. "
                    "hypothesis-driven threat assessment). Review the higher-severity signal(s) directly "
                    "before treating the lower one as a reason to deprioritize this case.",
                    alert_amber))
                story.append(Spacer(1, 10))

        # ── UNIFIED SEVERITY / CONFIDENCE TABLE ─────────────────────────
        # The Signal Consistency Check above *explains* why independent
        # scoring paths can show different severities. Per repeated review
        # feedback, explanation alone isn't enough — investigators need one
        # normalised table where every metric is unambiguously labelled,
        # so a bare "Low" or "Critical" is never seen without its
        # qualifier anywhere else in the report.
        _unified_threat = d.get("threat", {}) or {}
        _unified_rows = [[P("Signal", th), P("Value", th), P("Meaning", th)]]
        _unified_meta = [
            ("Crime Classification Severity", d.get("crime_severity"), "Keyword/pattern-matched crime category severity"),
            ("Operational Risk", (d.get("investigator", {}) or {}).get("risk", {}).get("level"), "Investigator Engine's own risk model"),
            ("Immediate Threat", verdict.get("immediate_threat") if _adv_top and "error" not in _adv_top else None, "Hypothesis-driven AI Verdict threat level"),
            ("Deception Score", d.get("deception_display") or "N/A — Narrative text only",
             "Linguistic-pattern score on the CASE NARRATIVE TEXT — this is investigator/case-intake "
             "writing describing the case, not a verbatim statement or interrogation transcript from the "
             "subject. Read this as a property of the narrative text, NOT as a measure of the subject's "
             "personal truthfulness, unless the submitted text is confirmed to directly quote the subject."),
            ("Escalation Probability", (
                _unified_threat.get('escalation_display') or
                (f"{_unified_threat.get('escalation_prob')}%" if _unified_threat.get('escalation_prob') is not None else None)
            ), "30-day escalation risk from the Threat Forecast model — a different computation than Deception Score"),
            ("Evidence Confidence", (
                f"{(d.get('confidence_transparency', {}) or {}).get('canonical_confidence', {}).get('canonical_confidence')}%"
                if (d.get('confidence_transparency', {}) or {}).get('canonical_confidence', {}).get('canonical_confidence') is not None
                else None
            ), "Canonical evidence-weighted confidence (see Confidence Transparency)"),
        ]
        for label, value, meaning in _unified_meta:
            if value is None or value == "":
                continue
            _unified_rows.append([P(label), P(str(value).upper() if not str(value).endswith('%') else str(value)), P(meaning, small)])

        if len(_unified_rows) > 1:
            story.append(Paragraph("Unified Severity & Confidence Summary", h3))
            _unified_tbl = Table(_unified_rows, colWidths=[150, 80, 250])
            _unified_tbl.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), DARK),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LGRAY]),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("GRID", (0, 0), (-1, -1), 0.4, BORDER),
            ]))
            story.append(_unified_tbl)
            story.append(P(
                "These are five distinct signals, not five attempts at the same number — "
                "treat the highest-severity signal as the one to act on first.",
                small))
            story.append(Spacer(1, 12))

        # ── CONFIDENCE TAXONOMY SUMMARY (Phase 2, 2026-08-27) ─────────────
        # BUG FIX / NEW FEATURE: consolidates the confidence-type numbers
        # that were scattered across many pages (Evidence Confidence,
        # Profile/Identity Confidence, Hypothesis Confidence, Risk Score,
        # Escalation/Threat Forecast, Court/Report Readiness) into ONE
        # explicitly-labelled table, right next to the Unified Severity
        # Summary above, so a reader sees both "which severity signal"
        # AND "which confidence type" tables together instead of hunting
        # across 15+ pages for each individually-labelled number. This
        # does not replace the individual numbers shown elsewhere in the
        # report — it's an additive index, built from the exact same
        # already-computed values.
        _inv_for_taxonomy = d.get("investigator", {}) or {}
        _reasoning_top = (_inv_for_taxonomy.get("reasoning_matrix") or [{}])[0] if _inv_for_taxonomy.get("reasoning_matrix") else {}
        _canon_conf_val = (d.get('confidence_transparency', {}) or {}).get('canonical_confidence', {}).get('canonical_confidence')
        _canon_conf_display = f"{_canon_conf_val}%" if _canon_conf_val is not None else "N/A"
        _simple_completeness_val = (d.get("intel_summary", {}) or {}).get("completeness_pct")
        _simple_completeness_display = f"{_simple_completeness_val}%" if _simple_completeness_val is not None else "N/A"

        # BUG FIX (2026-09 — investor-review feedback: "score factory" /
        # cognitive overload): the 8+ percentages scattered through this
        # report (Evidence Confidence, Hypothesis Confidence, Threat
        # Forecast, Report Readiness, Fused Confidence, Investigation
        # Progress, Evidence Completeness, Weighted Evidence Completeness)
        # each have a real, distinct meaning — but a first-time reader
        # sees a wall of percentages with no sense of which ones build on
        # which. Group the SAME already-computed values (no new/duplicate
        # calculations — two of these, Weighted Evidence Completeness and
        # Fused Confidence/Investigation Progress, are computed later in
        # this function from local state that isn't safely available yet
        # here, so those two rows point forward to their page instead of
        # re-deriving the number a second time and risking it drift out
        # of sync with the original) into an explicit 4-stage pipeline:
        #   EVIDENCE -> ANALYSIS -> INTELLIGENCE -> RECOMMENDATION
        # mirroring how the platform actually processes a case, so a
        # reader sees the STORY the numbers tell, not just the numbers.
        _tier_header_style = ParagraphStyle("tierhdr", fontName="Times-Bold", fontSize=8.5,
                                             textColor=colors.white, leading=11)
        def _tier_row(label):
            return [Paragraph(f"▸ {label}", _tier_header_style), P(""), P("")]

        _taxonomy_rows = [
            [P("Confidence Type", th), P("Value", th), P("Meaning", th)],

            _tier_row("1. EVIDENCE — what was actually submitted for this case"),
            [P("Evidence Completeness"), P(_simple_completeness_display),
             P("Simple count of evidence TYPES submitted (photo/voice/document/etc.) — "
               "the input layer everything below is built on")],
            [P("Weighted Evidence Completeness"), P("see Evidence Completeness section, below"),
             P("Same idea, weighted by how forensically valuable each evidence type is "
               "(e.g. CCTV counts for more than a name alone)")],

            _tier_row("2. ANALYSIS — what the AI engines found in that evidence"),
            [P("Evidence Confidence"), P(_canon_conf_display),
             P("Canonical evidence-weighted confidence (see Confidence Transparency)")],
            [P("Identity Confidence"), P("0% — not established"),
             P("No independent identity resolution has confirmed a specific individual for this case")],
            [P("Risk Score"), P(d.get("risk_display") if d.get("risk_is_heuristic") else (f"{d.get('risk', 'N/A')}" if not isinstance(d.get('risk'), (int, float)) else f"{d.get('risk'):.1f}%")),
             P("Investigator Engine's own risk-model output")],

            _tier_row("3. INTELLIGENCE — reasoning built on top of that analysis"),
            [P("Hypothesis Confidence"), P(f"{_reasoning_top.get('confidence', 'N/A')}%" if _reasoning_top else "N/A"),
             P(f"Leading hypothesis: {_reasoning_top.get('hypothesis', 'N/A')}" if _reasoning_top else "No active hypothesis")],
            [P("Threat Forecast"), P((d.get('threat', {}) or {}).get('escalation_display') or f"{(d.get('threat', {}) or {}).get('escalation_prob', 'N/A')}%"),
             P("30-day escalation probability from the Threat Forecast model")],
            [P("Fused Confidence"), P("see Advanced Intelligence Report, below"),
             P("Combines evidence, hypothesis, and readiness signals into one Executive Dashboard figure")],

            _tier_row("4. RECOMMENDATION — what this means for next steps"),
            [P("Report Readiness"), P(f"{((_inv_for_taxonomy.get('advanced', {}) or {}).get('executive_dashboard', {}) or {}).get('court_readiness', 'N/A')}%"),
             P("Derived from evidence completeness + forensic-quality evidence + hypothesis support — NOT a legal/court certification")],
            [P("Investigation Progress"), P("see Advanced Intelligence Report, below"),
             P("At-a-glance average of completeness/readiness/confidence — how far along this case is overall")],
        ]
        story.append(Paragraph("Score Hierarchy: Evidence → Analysis → Intelligence → Recommendation", h3))
        story.append(P(
            "Every score below builds on the tier above it — evidence in, analysis of that "
            "evidence, intelligence reasoned from that analysis, and finally what to do about it. "
            "Read top to bottom, not as eight unrelated numbers.",
            small))
        _taxonomy_tbl = Table(_taxonomy_rows, colWidths=[150, 100, 200])
        _taxonomy_tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), DARK),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Times-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LGRAY]),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("GRID", (0, 0), (-1, -1), 0.4, BORDER),
        ]))
        # Give every tier-header row ("1. EVIDENCE", "2. ANALYSIS", ...) the
        # same dark banner + full-width span treatment as the real header
        # row above — found by their own "▸ " marker rather than a
        # hardcoded row number, so this can't silently target the wrong
        # row (a real data row) if a row is ever added/removed above.
        _tier_row_indices = [i for i, row in enumerate(_taxonomy_rows) if row[0].text.startswith("▸ ")]
        for _i in _tier_row_indices:
            _taxonomy_tbl.setStyle(TableStyle([
                ("BACKGROUND", (0, _i), (-1, _i), DARK),
                ("SPAN", (0, _i), (-1, _i)),
            ]))
        story.append(_taxonomy_tbl)
        story.append(P(
            "Eight distinct signals across four stages, each measuring a different thing — none of "
            "these is a substitute for the others, and none is a substitute for human "
            "verification of the underlying evidence.",
            small))
        story.append(Spacer(1, 12))

        # Crime Classification vs. Hypothesis Engine: the keyword-based
        # Crime Classification can land on a generic "no specific pattern
        # detected" label while the Advanced pipeline's Hypothesis Engine
        # has already converged on a specific, high-confidence theory (e.g.
        # "Professional Gang" at 92%) — these come from different analysis
        # methods on the same evidence and can genuinely disagree, same as
        # the severity signals above.
        _crime_primary = str(d.get("crime_primary", "") or "")
        _crime_is_generic = any(p in _crime_primary.lower() for p in
                                 ("no specific", "under investigation", "unclassified", "pending"))
        if _crime_is_generic and _adv_top and "error" not in _adv_top:
            _top_hyps = (_adv_top.get("hypothesis_ranking", {}) or {}).get("top_hypotheses", []) or []
            # BUG FIX (reviewer feedback): this note previously only fired
            # for hypotheses at ≥70% confidence — so a mid-range hypothesis
            # (e.g. "Professional organized crime: 55%", "Inside job: 30%")
            # sitting right next to a "no specific crime pattern
            # established" Crime Classification line got NO explanatory
            # note at all, letting the percentage read as an unqualified
            # finding. Any hypothesis confidence >0% next to a generic
            # Crime Classification result now gets this caveat — the
            # wording and severity still scale with how strong the
            # hypothesis is.
            if _top_hyps and _safe_num(_top_hyps[0].get("confidence", 0)) > 0:
                _top_conf = _safe_num(_top_hyps[0].get("confidence", 0))
                _signal_contradictions.append({
                    "contradiction": f"Crime Classification (\"{_crime_primary}\") vs. Hypothesis Engine "
                                      f"(\"{_top_hyps[0].get('name','Unknown')}\" at {_top_hyps[0].get('confidence',0)}%)",
                    "sources": "Crime Classification, Hypothesis Engine",
                    "severity": "Medium" if _top_conf >= 70 else "Low",
                })
                if _top_conf >= 70:
                    story.append(P(
                        f"⚠ Signal Consistency Check: Crime Classification reports \"{_crime_primary}\" "
                        f"(no specific pattern matched by keyword analysis), while the Hypothesis Engine has "
                        f"independently converged on \"{_top_hyps[0].get('name','Unknown')}\" at "
                        f"{_top_hyps[0].get('confidence',0)}% confidence (see Advanced Intelligence Report). "
                        f"The Hypothesis Engine reasons over the full evidence graph and is the more specific "
                        f"signal here — Crime Classification's keyword match not firing does not mean the "
                        f"Hypothesis Engine's theory is unsupported.",
                        alert_amber))
                else:
                    story.append(P(
                        f"Note: Crime Classification reports \"{_crime_primary}\" (no specific pattern matched "
                        f"by keyword analysis). The Hypothesis Engine's leading theory, "
                        f"\"{_top_hyps[0].get('name','Unknown')}\" at {_top_hyps[0].get('confidence',0)}%, is "
                        f"an AI-SUGGESTED HYPOTHESIS at moderate-to-low confidence, NOT an established "
                        f"finding — treat percentages in the hypothesis table as investigative leads to "
                        f"verify, not conclusions.",
                        small))
                story.append(Spacer(1, 10))

        # AI Modules Executed / Not Executed — right below the header
        MODULE_LABELS = {
            "NER": "Named Entity Recognition", "Voice": "Voice Analysis",
            "ArcFace": "Face Analysis", "OCR": "OCR",
            "Risk": "Risk Assessment", "Datasets": "Database / Watchlist Search",
            "AI Reasoning": "AI Reasoning Layer", "CCTV": "CCTV Crime Classification",
            "Deepfake": "Deepfake Detection",
        }

        status = d.get("source_status") or {}
        executed = [MODULE_LABELS.get(k, k) for k, v in status.items() if v in ("ANALYZED", "HEURISTIC FALLBACK", "FALLBACK ANALYZED")]
        not_executed = [f"{MODULE_LABELS.get(k, k)} — {v}" for k, v in status.items()
                         if v not in ("ANALYZED", "HEURISTIC FALLBACK", "FALLBACK ANALYZED")]

        exec_style = ParagraphStyle("modexec", fontName="Times-Bold", fontSize=9,
                                     textColor=colors.HexColor("#16a34a"), leading=14)
        notexec_style = ParagraphStyle("modnotexec", fontName="Times-Roman", fontSize=9,
                                        textColor=colors.HexColor("#94a3b8"), leading=14)
        mod_title_style = ParagraphStyle("modtitle", fontName="Times-Bold", fontSize=9.5,
                                          textColor=colors.black, leading=13)

        exec_para = Paragraph(
            "<br/>".join([f"✓ {m}" for m in executed]) or "—", exec_style)
        not_exec_para = Paragraph(
            "<br/>".join([f"• {m}" for m in not_executed]) or "—", notexec_style)

        modules_tbl = Table([
            [Paragraph("AI Modules Executed", mod_title_style),
             Paragraph("Modules Not Executed", mod_title_style)],
            [exec_para, not_exec_para],
        ], colWidths=[240, 240])
        modules_tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
            ("BOX", (0, 0), (-1, -1), 0.75, colors.HexColor("#e2e8f0")),
            ("LINEAFTER", (0, 0), (0, -1), 0.75, colors.HexColor("#e2e8f0")),
            ("LINEBELOW", (0, 0), (-1, 0), 0.75, colors.HexColor("#e2e8f0")),
            ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ("LEFTPADDING", (0, 0), (-1, -1), 12),
            ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ]))
        story.append(modules_tbl)
        # Clarifies the exact scope of "Executed" — this table shows AI
        # capability availability (is this model loaded and running at
        # all), not evidence-type completeness for this specific case. A
        # module can show ✓ here (the classifier ran, e.g. on the suspect
        # photo as a fallback) while "Evidence Completeness" below still
        # correctly lists that evidence type as Missing (no dedicated
        # footage/file of that type was actually submitted). Both can be
        # true at once — this line exists so that isn't read as a bug.
        story.append(P(
            "\"Executed\" = model ran. The specific section for each module (e.g. CCTV Crime-Scene "
            "Classification) shows whether it ran on REAL CCTV VIDEO or a fallback IMAGE — the source "
            "badge distinguishes genuine investigative feeds from fallback analysis. See \"Evidence "
            "Completeness\" for what was actually submitted.", small))
        story.append(Spacer(1, 6))
        story.append(P(
            f"NexForensics Investigation Intelligence Report  •  Engine v1.0.0  •  "
            f"Report Format: Enterprise Edition  •  Generated: {datetime.now().strftime('%Y-%m-%d')}  •  "
            f"Build: {datetime.now().strftime('%Y.%m.%d')}.01",
            small
        ))
        story.append(Spacer(1, 8))

        # PAGE 1: Case Info, Crime Classification, Evidence Summary, Scores
        story.append(Paragraph("CASE INFORMATION", h2))
        case_tbl = Table([
            [P("Case ID", small), P(d.get("case_id", "N/A") + (f"<br/>(user reference: {d.get('case_user_reference')})" if d.get("case_user_reference") else "")),
             P("Timestamp", small), P(d.get("timestamp", "N/A"))],
            [P("Case Title", small), P(d.get("case_title", "N/A")),
             P("Case Priority", small), P(d.get("case_priority", "Medium"))],
            [P("Crime Category", small), P(d.get("crime_category", "N/A")),
             P("Incident Date (as reported)", small), P(d.get("incident_date", "N/A"))],
            [P("Suspect", small), P(d.get("suspect_name", "N/A")),
             P("Location", small), P(d.get("location", "N/A"))],
            [P("Investigating Officer", small), P(d.get("investigating_officer", "N/A")),
             P("Classification", small), P(d.get("classification", "CONFIDENTIAL"))],
            [P("Analyst", small), P(d.get("analyst", "[Auto-Generated]")),
             P("Retention", small), P(d.get("retention", "Per your organization's records-retention policy"))],
            [P("Analysis Engine Coverage", small),
             P(f"{d.get('active_models',0)}/5 AI modules loaded on server (infrastructure — same for every case)", small),
             P("Evidence-Type Coverage", small),
             P(f"{(d.get('intel_summary', {}) or {}).get('completeness_pct', 0)}% (evidence types actually "
               f"submitted for THIS case)", small)],
        ], colWidths=[62, 170, 72, 168])
        case_tbl.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (0, -1), "Times-Bold"),
            ("FONTNAME", (2, 0), (2, -1), "Times-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("TEXTCOLOR", (0, 0), (0, -1), GRAY),
            ("TEXTCOLOR", (2, 0), (2, -1), GRAY),
            ("TEXTCOLOR", (1, 0), (1, -1), DARK),
            ("TEXTCOLOR", (3, 0), (3, -1), DARK),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (0, -1), 10),
            ("RIGHTPADDING", (2, 0), (2, -1), 10),
            ("LINEBELOW", (0, 0), (-1, -2), 0.5, BORDER),
        ]))
        story.append(case_tbl)

        story.append(Spacer(1, 12))
        v_bg = colors.HexColor(d.get("v_color", "#f59e0b"))
        verdict_tbl = Table([[P(f"VERDICT — {d.get('v_label','')}", verdict_title)],
                              [P(d.get("v_text", ""), verdict_body)]],
                             colWidths=[480])
        verdict_tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), v_bg),
            ("LEFTPADDING", (0, 0), (-1, -1), 14),
            ("RIGHTPADDING", (0, 0), (-1, -1), 14),
            ("TOPPADDING", (0, 0), (0, 0), 10),
            ("BOTTOMPADDING", (0, 0), (0, 0), 2),
            ("TOPPADDING", (0, 1), (0, 1), 2),
            ("BOTTOMPADDING", (0, 1), (0, 1), 10),
            ("ROUNDEDCORNERS", [6, 6, 6, 6]),
        ]))
        story.append(KeepTogether(verdict_tbl))

        # ── Investigation Status panel ───────────────────────────────────────
        intel = d.get("intel_summary", {})
        if intel:
            story.append(Spacer(1, 12))
            story.append(Paragraph("INVESTIGATION STATUS", h2))
            inv_status = intel.get("investigation_status", {})
            status_tbl = Table([
                [P("Known Criminal Match", small), P(inv_status.get("known_criminal_match", "N/A")),
                 P("Analytical Source Coverage", small),
                 P(f"{inv_status.get('analytical_source_coverage', 'N/A')}<br/>({inv_status.get('analytical_source_coverage_note', '')})", small)],
                [P("Threat Severity", small), severity_cell(inv_status.get("threat_severity", "Low")),
                 P("Investigation Required", small), P(inv_status.get("investigation_required", "Yes"))],
                [P("", small), P(f"({inv_status.get('threat_severity_note', '')})", small), P("", small), P("", small)],
            ], colWidths=[62, 170, 72, 168])
            status_tbl.setStyle(TableStyle([
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ROWBACKGROUNDS", (0, 0), (-1, -1), [LGRAY, colors.white]),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("GRID", (0, 0), (-1, -1), 0.4, BORDER),
            ]))
            story.append(status_tbl)

            # Investigation Intelligence Summary — 5-point synthesis
            story.append(Spacer(1, 10))
            story.append(Paragraph("Investigation Intelligence Summary", h3))
            sp = intel.get("summary_points", {})
            for label, key in [
                ("What Was Found", "what_was_found"), ("What Was Not Found", "what_was_not_found"),
                ("Strongest Lead", "strongest_lead"), ("Weakest Link", "weakest_link"),
                ("Recommended Next Step", "next_step"),
            ]:
                story.append(P(f"<b>{label}:</b> {sp.get(key, 'N/A')}", evidence_style))

            # Evidence Completeness Meter
            story.append(Spacer(1, 10))
            story.append(Paragraph("Evidence Completeness", h3))
            story.append(P(
                f"Evidence-Type Coverage: {intel.get('completeness_bar','')}  {intel.get('completeness_pct',0)}%  "
                f"— simple count of evidence TYPES submitted (photo/voice/document/etc.), each type "
                f"counted equally. See \"Weighted Evidence Completeness\" later in this report for the "
                f"per-module, weighted figure — the two are different metrics and are expected to differ.",
                evidence_style))
            # NEW: evidence-submitted/missing bar chart — added per user
            # request to explain more report facts via graphs.
            _ev_chart = _pdf_evidence_provided_chart(d.get("evidence_provided", {}))
            if _ev_chart:
                story.append(Spacer(1, 4))
                story.append(_ev_chart)
            missing = intel.get("missing_evidence", [])
            story.append(P(
                f"Not Submitted for This Case: {', '.join(missing)}" if missing else "All core evidence types provided.",
                small
            ))

        # Crime Classification
        story.append(Spacer(1, 14))
        story.append(Paragraph("CRIME CLASSIFICATION (Based on Evidence)", h2))
        crime_sev = d.get("crime_severity", "Low")
        ev_found = d.get("crime_evidence", [])
        ev_text = "<br/>".join([f"• {e}" for e in ev_found[:5]]) if ev_found else "No specific crime indicators found"

        crime_tbl = Table([
            [P("Primary Crime", small), P(d.get("crime_primary", "Under Investigation")),
             P("Severity", small), severity_cell(crime_sev)],
            [P("Secondary Crime", small), P(d.get("crime_secondary", "N/A")),
             P("Jurisdiction", small), P(d.get("crime_jurisdiction", "N/A"))],
            [P("Potential Applicable Law", small), P(d.get("crime_statutes", "Pending Review")),
             P("", small), P("")],
            [P("", small), P((d.get("crime_law_label") or "AI-suggested from keyword match — NOT backend-verified. "
                              "Confirm against actual jurisdiction/counsel before citing.")
                             + ((" " + (d.get("crime_law") or {}).get("date_note", "") + ".") if (d.get("crime_law") or {}).get("date_note") else ""), small),
             P("", small), P("")],
            [P("Evidence Found", small), P(ev_text, evidence_style),
             P("", small), P("")],
        ], colWidths=[62, 170, 72, 168])
        crime_tbl.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (0, -1), "Times-Bold"),
            ("FONTNAME", (2, 0), (2, -1), "Times-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("TEXTCOLOR", (0, 0), (0, -1), GRAY),
            ("TEXTCOLOR", (2, 0), (2, -1), GRAY),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (0, -1), 10),
            ("RIGHTPADDING", (2, 0), (2, -1), 10),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LINEBELOW", (0, 0), (-1, -2), 0.5, BORDER),
        ]))
        story.append(crime_tbl)

        # Composite scores
        story.append(Spacer(1, 14))
        story.append(Paragraph("COMPOSITE SCORES", h2))
        def score_card(label, val):
            # Defensive: this card renders at 22pt bold, so anything other
            # than a plain number here doesn't just look wrong — it visibly
            # blows up the whole row (this exact failure mode is what
            # caused the "RISK LEVEL" card to render a full sentence and
            # overlap neighbouring cards in earlier reports). Whatever the
            # upstream cause, this card must only ever show a clean number.
            try:
                val = round(float(val), 1) if not isinstance(val, bool) else 0
                if val == int(val):
                    val = int(val)
            except (TypeError, ValueError):
                log.warning(f"score_card('{label}') got non-numeric value {val!r} — showing N/A")
                col = GRAY
                return [P(f'<font color="{col.hexval()}">N/A</font>', card_num),
                        P(label.upper(), card_lbl)]
            col = severity_color(val)
            return [P(f'<font color="{col.hexval()}">{val}%</font>', card_num),
                    P(label.upper(), card_lbl)]
        # BUG FIX (2026-08-25): when d.get("risk") is non-numeric (root
        # cause still not pinned down after extensive tracing — it's a
        # valid float everywhere else in this same report, e.g.
        # "Operational Risk Score: {risk:.1f}%" in Actionable
        # Intelligence), defaulting this card to a flat 0% actively
        # misleads — it reads as a confidently-computed "zero risk"
        # finding, which is worse than "N/A" for a Critical/Homicide case.
        # Fall back to the SAME-report's independent Investigator Engine
        # risk level (already shown as "Operational Risk: MEDIUM" etc. in
        # the Unified Severity Summary) translated to a representative
        # number, so this card is at minimum internally consistent with
        # what the rest of the report already says about risk.
        _risk_val = d.get("risk", 0)
        if not isinstance(_risk_val, (int, float)):
            _inv_risk_level = str((d.get("investigator", {}) or {}).get("risk", {}).get("level", "")).upper()
            _risk_val = {"LOW": 20, "MEDIUM": 50, "HIGH": 75, "CRITICAL": 90}.get(_inv_risk_level, 0)
        # BUG FIX (investor-review feedback): "Credibility" is computed as
        # `100 - deception - jitter` (see gradio_app.py) — it is the direct
        # mathematical inverse of Deception Score, so it inherits that
        # score's EXACT same scope limitation: a linguistic-pattern read of
        # the case-INTAKE narrative text, not a measure of the subject's
        # actual credibility, unless real voice evidence was submitted.
        # Showing a bare "Credibility: 74.7%" right next to a correctly
        # N/A'd Deception Score (same underlying number) is exactly the
        # kind of inconsistency that undermines trust in the whole report.
        # Same _deception_has_voice gate, same renaming pattern.
        cards_tbl = Table([[score_card("Deception Score", d.get("deception") if d.get("_deception_has_voice") else None),
                            score_card("Narrative Credibility", d.get("credibility") if d.get("_deception_has_voice") else None),
                            (score_card("Risk Level", _risk_val) if not d.get("risk_is_heuristic") else
                             [P(f'<font color="{severity_color(str(d.get("risk_band", "")).upper() if str(d.get("risk_band", "")).upper() != "MEDIUM" else "Medium").hexval()}">{d.get("risk_band", "N/A")}</font>', card_num),
                              P("RISK LEVEL (HEURISTIC ESTIMATE)", card_lbl)]),
                            # BUG FIX (2026-08-20 — High): this card used to
                            # be labelled bare "Confidence" while showing
                            # active_models*20 — a count of how many AI
                            # modules were active (e.g. 2/5 -> 40%), NOT
                            # evidence/case confidence. Sitting right next
                            # to Deception/Credibility/Risk, it read as a
                            # 4th case-quality score and directly conflicted
                            # with the canonical "Evidence Confidence 46.8%"
                            # shown on Page 1 for the same case. Same fix
                            # already applied elsewhere in this report
                            # (analytical_source_coverage) — apply the same
                            # explicit relabel here.
                            score_card(f"AI Modules Loaded ({d.get('active_models', 0)}/5)", min(d.get("active_models", 0) * 20, 100))]],
                          colWidths=[120, 120, 120, 120])
        cards_tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), LGRAY),
            ("BOX", (0, 0), (0, 0), 0.75, BORDER),
            ("BOX", (1, 0), (1, 0), 0.75, BORDER),
            ("BOX", (2, 0), (2, 0), 0.75, BORDER),
            ("BOX", (3, 0), (3, 0), 0.75, BORDER),
            ("TOPPADDING", (0, 0), (-1, -1), 14),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 14),
        ]))
        story.append(cards_tbl)

        # Fraud & Crime Indicators
        story.append(Spacer(1, 14))
        story.append(Paragraph("FRAUD & CRIME INDICATORS (Evidence-Based)", h2))
        fraud_rows = [
            [P("Indicator", th), P("Score", th), P("Assessment", th), P("Evidence Basis", th)],
        ]
        _doc_ev = d.get("doc_evidence", {}) or {}
        _face_ev = d.get("face_evidence", {}) or {}
        _voice_ev = d.get("voice_evidence", {}) or {}
        _doc_analyzed = _doc_ev.get("status") == "Evidence analyzed"
        if _doc_analyzed:
            fraud_rows.append([
                P("Document Forgery Risk"), severity_cell(f"{d.get('fraud_doc_forgery',0):.1f}%"),
                P("HIGH" if d.get('fraud_doc_forgery',0) > 60 else "MODERATE" if d.get('fraud_doc_forgery',0) > 30 else "LOW"),
                P("OCR analysis + document metadata")])
        else:
            fraud_rows.append([
                P("Document Forgery Risk"), severity_cell("N/A"),
                P("NOT ASSESSED"),
                P("No document submitted for this case")])
        # Identity Fraud Risk basis: only list the evidence types that were
        # actually submitted and analyzed — the old hardcoded "Face + voice
        # + document consistency" claimed all three regardless of what was
        # actually provided.
        _id_basis_parts = []
        # p23: a face embedding with no reference face is not an identity-fraud basis
        if _voice_ev.get("status") == "Evidence analyzed":
            _id_basis_parts.append("voice")
        if _doc_analyzed:
            _id_basis_parts.append("document")
        _id_basis = (" + ".join(_id_basis_parts) + " consistency") if _id_basis_parts else "No identity evidence submitted"
        fraud_rows.append([
            P("Identity Fraud Risk"), severity_cell(f"{d.get('fraud_id_fraud',0):.1f}%") if _id_basis_parts else severity_cell("N/A"),
            P("HIGH" if d.get('fraud_id_fraud',0) > 60 else "MODERATE" if d.get('fraud_id_fraud',0) > 30 else "LOW") if _id_basis_parts else P("NOT ASSESSED"),
            P(_id_basis)])
        fraud_rows += [
            [P("Financial Anomaly Risk"), severity_cell(f"{d.get('fraud_fin_anomaly',0):.1f}%"),
             P("HIGH" if d.get('fraud_fin_anomaly',0) > 60 else "MODERATE" if d.get('fraud_fin_anomaly',0) > 30 else "LOW"),
             P("Named entities + modus operandi text")],
            [P("Criminal Pattern Match"), severity_cell(f"{d.get('fraud_mo_match',0):.1f}%"),
             P("MATCH" if d.get('fraud_mo_match',0) > 70 else "PARTIAL" if d.get('fraud_mo_match',0) > 40 else "NO MATCH"),
             P("All evidence combined pattern analysis")],
        ]
        fraud_tbl = Table(fraud_rows, colWidths=[130, 70, 80, 200])
        fraud_tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), DARK),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Times-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LGRAY]),
            ("TOPPADDING", (0, 0), (-1, -1), 7),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("LINEBELOW", (0, 0), (-1, 0), 0.75, DARK),
            ("GRID", (0, 0), (-1, -1), 0.4, BORDER),
        ]))
        story.append(fraud_tbl)
        # NEW: fraud-indicators bar chart — added per user request to
        # explain more report facts via graphs.
        _fraud_chart_data = [
            ("Doc. Forgery", d.get('fraud_doc_forgery', 0) if _doc_analyzed else 0),
            ("Identity Fraud", d.get('fraud_id_fraud', 0) if _id_basis_parts else 0),
            ("Financial Anomaly", d.get('fraud_fin_anomaly', 0)),
            ("Pattern Match", d.get('fraud_mo_match', 0)),
        ]
        _fraud_chart = _pdf_fraud_indicators_chart(_fraud_chart_data)
        if _fraud_chart:
            story.append(Spacer(1, 6))
            story.append(_fraud_chart)

        flags = d.get("fraud_flags", [])
        if flags and flags != ["No suspicious behavioral indicators detected"]:
            story.append(Spacer(1, 8))
            story.append(Paragraph("Behavioral Red Flags from Evidence:", small))
            for flag in flags[:6]:
                story.append(P(f"  ⚠ {flag}", alert_amber))

        story.append(PageBreak())

        # PAGE 2: Evidence Analysis Details
        story.append(Paragraph("EVIDENCE ANALYSIS DETAILS", h2))

        # Text Evidence
        story.append(Paragraph("Text Evidence — Named Entities & Statements", h3))
        text_ev = d.get("text_evidence", [])
        if text_ev:
            text_rows = [[P("Evidence Type", th), P("Count", th), P("Values Found", th), P("Forensic Significance", th)]]
            for ev in text_ev[:6]:
                # BUG FIX (2026-08-20 — Medium): a URL entity extracted from
                # case narrative text that already contains markdown-style
                # "[text](url)" formatting gets captured with the "](" intact,
                # producing a duplicated/malformed-looking URL in the report
                # (e.g. ".../gems-vendor](http://darkmarket-...). Same fix as
                # the dataset-match table earlier — neutralize "](" before
                # it reaches the PDF.
                _raw_vals = [str(v).replace("](", " → ") for v in (ev.get("values", []) or [])]
                vals = ", ".join(_raw_vals[:5]) if _raw_vals else "N/A"
                text_rows.append([P(ev.get("type", "N/A")), P(str(ev.get("count", 0))),
                                  P(_safe_truncate(vals, 60)), P(_safe_truncate(ev.get("significance", "N/A"), 80))])
            text_tbl = Table(text_rows, colWidths=[120, 50, 150, 160])
            text_tbl.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), DARK),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Times-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LGRAY]),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("LINEBELOW", (0, 0), (-1, 0), 0.75, DARK),
                ("GRID", (0, 0), (-1, -1), 0.4, BORDER),
            ]))
            story.append(text_tbl)
        else:
            story.append(P("No text evidence analyzed."))

        # Facial Evidence
        story.append(Spacer(1, 10))
        story.append(Paragraph("Facial Evidence Analysis", h3))
        face_ev = d.get("face_evidence", {})
        if face_ev.get("status") == "Evidence analyzed":
            for finding in face_ev.get("findings", []):
                story.append(P(f"  • {finding}"))
            for risk in face_ev.get("risk_indicators", []):
                story.append(P(f"  ⚠ {risk}", alert_amber))
            meta = face_ev.get("photo_metadata", {})
            if meta:
                story.append(P(f"  Metadata: {str(meta)[:200]}", evidence_style))
        else:
            story.append(P(face_ev.get("status", "No facial evidence submitted")))

        img_q = d.get("image_quality")
        if img_q:
            q_label, q_note = img_q
            q_color = {"Good": "#22c55e", "Average": "#f59e0b", "Poor": "#ef4444"}.get(q_label, "#94a3b8")
            story.append(P(
                f'  Evidence Reliability — Input Quality: <font color="{q_color}"><b>{q_label}</b></font> — {q_note}',
                small
            ))

        # ─── CCTV / IMAGE SCENE CLASSIFICATION ──────────────────────
        story.append(Spacer(1, 10))
        cctv_result_pdf = d.get("cctv_result")
        cctv_source_pdf = d.get("cctv_source_label") or ""
        is_real_cctv = "cctv video" in cctv_source_pdf.lower()
        story.append(Paragraph(
            "CCTV Crime-Scene Classification" if is_real_cctv else "Image Scene Classification",
            h3
        ))
        if cctv_result_pdf:
            # Explicit source provenance badge — investor/reviewer ko
            # unambiguous dikhe ki classifier REAL CCTV VIDEO pe chala
            # ya fallback IMAGE pe. Ye do alag cheezein hain.
            if is_real_cctv:
                _source_badge = f'<font color="#16a34a"><b>SOURCE: REAL CCTV VIDEO</b></font> — {cctv_source_pdf or "Unknown"}'
            else:
                _source_badge = f'<font color="#f59e0b"><b>SOURCE: IMAGE FALLBACK</b></font> — {cctv_source_pdf or "Unknown"}'
                _source_badge += " <i>(no CCTV video submitted — classifier ran on fallback photo)</i>"
            story.append(P(f"  {_source_badge}", small))
            for r in cctv_result_pdf[:5]:
                story.append(P(f"  • {r['label']}: {r['score']:.1f}%", evidence_style))
            story.append(P("Model-generated classification — verify independently.", small))
        elif not d.get("cctv_loaded"):
            story.append(P("N/A — classification module offline."))
        else:
            story.append(P("No CCTV footage or photo evidence submitted."))

        # ─── DEEPFAKE DETECTION ─────────────────────────────────────
        story.append(Spacer(1, 10))
        story.append(Paragraph("Deepfake Detection", h3))
        deepfake_result_pdf = d.get("deepfake_result")
        if deepfake_result_pdf:
            _calibrated_pdf = calibrate_deepfake_result(deepfake_result_pdf, d.get("image_quality"))
            if _calibrated_pdf:
                story.append(P(f"  • Model classification: {_calibrated_pdf['model_classification']}", evidence_style))
                story.append(P(f"  • Forensic conclusion: {_calibrated_pdf['forensic_conclusion']}", evidence_style))
                story.append(P(f"  • Model confidence level: {_calibrated_pdf['confidence_level']}", evidence_style))
            else:
                for r in deepfake_result_pdf[:5]:
                    story.append(P(f"  • {r['label']}: {r['score']:.1f}%", evidence_style))
            story.append(P("Model: prithivMLmods/Deepfake-vs-Real-8000 — verify independently.", small))
        elif not d.get("deepfake_loaded"):
            story.append(P("N/A — Deepfake detection module offline."))
        else:
            story.append(P("No photo evidence submitted."))

        # p28: Narrative vs document consistency (NLI v3)
        story.append(Spacer(1, 10))
        story.append(Paragraph("Narrative vs Document Consistency (NLI v3 - experimental)", h3))
        _nli = d.get("nli_claim_check") or {}
        if _nli.get("status") == "ASSESSED":
            _c = _nli.get("counts", {})
            story.append(P(f"Supported {_c.get('SUPPORTED',0)} | Contradicted {_c.get('CONTRADICTED',0)} | No evidence in document {_c.get('NO_EVIDENCE',0)}"))
            for _cl in _nli.get("claims", []):
                story.append(P(f"  [{_cl['verdict']}] {_cl['claim'][:200]}", evidence_style))
                if _cl.get("document_sentence"):
                    story.append(P(f"      document: {_cl['document_sentence'][:200]}", small))
        else:
            story.append(P(f"NOT ASSESSED - {_nli.get('reason', 'not run')}"))
        story.append(P(_nli.get("note", "Experimental; leads only."), small))

        # Voice Evidence
        story.append(Spacer(1, 10))
        story.append(Paragraph("Voice Evidence Analysis", h3))
        voice_ev = d.get("voice_evidence", {})
        if voice_ev.get("status") == "Evidence analyzed":
            for finding in voice_ev.get("findings", []):
                story.append(P(f"  • {finding}"))
            for risk in voice_ev.get("risk_indicators", []):
                story.append(P(f"  ⚠ {risk}", alert_amber))
            meta = voice_ev.get("audio_metadata", {})
            if meta:
                story.append(P(f"  Metadata: {str(meta)[:200]}", evidence_style))
        else:
            story.append(P(voice_ev.get("status", "No voice evidence submitted")))

        # Document Evidence
        story.append(Spacer(1, 10))
        story.append(Paragraph("Document Evidence Extraction", h3))
        doc_ev = d.get("doc_evidence", {})
        if doc_ev.get("status") == "Evidence analyzed":
            for finding in doc_ev.get("findings", []):
                story.append(P(f"  • {finding}"))
            for risk in doc_ev.get("risk_indicators", []):
                story.append(P(f"  ⚠ {risk}", alert_amber))
            if doc_ev.get("extracted_text"):
                story.append(P(f'  Extracted text: "{doc_ev["extracted_text"][:150]}..."', evidence_style))
        else:
            story.append(P(doc_ev.get("status", "No document evidence submitted")))
            # Submitted-but-unreadable case: show the file findings and the
            # technical (non-fraud) reason, so a reader sees the document
            # WAS there and understands why it produced no text — instead
            # of only a one-line status that reads like nothing was
            # uploaded at all.
            for finding in doc_ev.get("findings", []):
                story.append(P(f"  • {finding}", evidence_style))
            for issue in doc_ev.get("technical_issues", []):
                story.append(P(f"  ⓘ {issue}", small))

        # ─── DIGITAL & CYBER EVIDENCE SECTION ──────────────────────
        story.append(Spacer(1, 10))
        story.append(Paragraph("Digital & Cyber Evidence", h3))

        digital_evidence_pdf = []
        if d.get("entities", {}):
            for etype in ["EMAIL", "PHONE", "URL"]:
                if d["entities"].get(etype):
                    # BUG FIX (2026-08-20 — Medium): same "](" markdown-link
                    # collision as the Named Entities table above — a URL
                    # entity already containing markdown-style formatting in
                    # the source narrative renders as duplicated/malformed
                    # text otherwise.
                    _clean_vals = [str(v).replace("](", " → ") for v in d["entities"][etype][:5]]
                    digital_evidence_pdf.append(f"{etype}: {', '.join(_clean_vals)}")

        if digital_evidence_pdf:
            for de in digital_evidence_pdf:
                story.append(P(f"  • {de}", evidence_style))
        else:
            story.append(P("No digital evidence captured.", evidence_style))

        cyber_flags_pdf = d.get("cyber_flags", [])
        if cyber_flags_pdf:
            story.append(Spacer(1, 6))
            story.append(Paragraph("Cyber Intelligence Flags:", small))
            for flag in cyber_flags_pdf:
                story.append(P(f"  ⚠ {flag}", alert_amber))

        if d.get("fraud_digital_anomaly", 0) > 0:
            story.append(Spacer(1, 6))
            story.append(P(
                f"Digital Anomaly Score: {d['fraud_digital_anomaly']:.1f}%",
                small
            ))
        # ─── END DIGITAL EVIDENCE SECTION ─────────────────────────────────────

        story.append(PageBreak())

        # PAGE 3: Network/Watchlist, Threat, Evidence Integrity, Actions
        story.append(Paragraph("NETWORK & WATCHLIST STATUS", h2))
        story.append(P(
            "⚠ IDENTITY NOT INDEPENDENTLY VERIFIED (Identity Confidence: 0%). Every row below is a "
            "NAME/ALIAS MATCH against a dataset — none of it has been confirmed to belong to this "
            "specific individual by photo, biometric, or document cross-check. A \"YES\" in this table "
            "means the dataset has a record with a matching name, not a confirmed hit on this person.",
            alert_red
        ))
        story.append(Spacer(1, 4))
        wl = d.get("watchlist", {})
        dm = wl.get("dataset_matches", {"count": 0, "datasets": {}})
        dm_text = (f"{dm['count']} record(s): " + ", ".join(f"{k}({v})" for k, v in dm["datasets"].items())
                   if dm.get("count") else "No internal database record found (searched master_search_index)")
        watch_rows = [
            [P("Check", th), P("Result", th), P("Details", th)],
            [P("Match Confidence"), severity_cell(wl.get("match_confidence", "NONE")),
             P("STRONG=name string closely matches (NOT person confirmed), PARTIAL=verify, POSSIBLE=spelling variant (verify identity), WEAK=coincidental only")],
            [P("Database Match"), severity_cell(_safe_truncate(dm_text, 60)),
             P(f"Searched across {len(dm.get('datasets', {}))} dataset(s)" if dm.get("count") else "master_search_index")],
            [P("Criminal History"), severity_cell(_safe_truncate(_honest_negative(wl.get("criminal_history", "NO RECORD")), 64)),
             P("Prior convictions / arrests")],
            [P("Known Aliases"), P(", ".join(wl.get("aliases", ["N/A"])[:3])),
             P("Other names found under the SAME dataset search — may be alternate identities OR "
               "different individuals who happen to share a name fragment; not verified as one person")],
            [P("Known Associates"), P(", ".join(wl.get("known_associates", ["N/A"])[:2])),
             P("Connected persons of interest")],
            [P("Gang / Organization"), P(wl.get("gang_affiliation", "N/A")),
             P("Group affiliations")],
            [P("PEP Status"), severity_cell(_display_watchlist_status(wl.get("pep_status", "NO"))),
             P("Politically Exposed Person (name-match, identity unverified)")],
            [P("Sanctions List"), severity_cell(_display_watchlist_status(wl.get("sanctions", "NO"))),
             P("OFAC / UN / EU sanctions (name-match, identity unverified)")],
            [P("Interpol Status"), severity_cell(_display_watchlist_status(wl.get("interpol", "NO"))),
             P("Red Notice / Diffusion (name-match, identity unverified)")],
            [P("FBI Watchlist"), severity_cell(_fbi_display(wl)),
             P("US federal list: applies to US cases only")],
            [P("FinCEN SARs"), severity_cell(_display_watchlist_status(wl.get("fintrac_sar", "NO"))),
             P("Suspicious Activity Reports")],
            [P("Subject Status"), severity_cell(wl.get("status", "UNKNOWN")),
             P("Current disposition")],
        ]
        if wl.get("possible_variant_matches"):
            watch_rows.append([
                P("Possible Matches"),
                P(f"{len(wl['possible_variant_matches'])} spelling-variant record(s) — POSSIBLE, verify identity"),
                P("; ".join(f"[{m.get('dataset')}] {m.get('name')} ({m.get('pairs_text') or 'variant'})"
                            for m in wl["possible_variant_matches"][:3])[:220]),
            ])
        weak_matches = wl.get("weak_matches_for_review", [])
        if weak_matches:
            watch_rows.append([
                P("Weak Matches"),
                P(f"{len(weak_matches)} name-fragment hit(s) — NOT counted above"),
                P("; ".join(weak_matches[:2])[:200]),
            ])
        watch_tbl = Table(watch_rows, colWidths=[120, 180, 192])
        watch_tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), DARK),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Times-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LGRAY]),
            ("TOPPADDING", (0, 0), (-1, -1), 7),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("LINEBELOW", (0, 0), (-1, 0), 0.75, DARK),
            ("GRID", (0, 0), (-1, -1), 0.4, BORDER),
        ]))
        story.append(watch_tbl)

        # ── WANTED-LIST / CRIMINAL DATABASE MATCH (Phase 1, 2026-08-27) ──────
        # BUG FIX / NEW FEATURE: matches the case narrative against the
        # connected wanted-list dataset (master_search_index). Runs on the
        # free-text mo_description ONLY — never on the suspect_name field —
        # so a "match" here reflects what the narrative itself describes,
        # not a self-fulfilling lookup of an already-known name. Always
        # renders this section explicitly (even with zero matches) so a
        # "no match" is a visible, honest finding rather than silence.
        story.append(Spacer(1, 14))
        story.append(Paragraph("WANTED-LIST / CRIMINAL DATABASE MATCH", h2))
        story.append(P(
            "Matches the case narrative text against the connected wanted-list "
            "dataset by name/alias, then by modus-operandi keyword overlap if no "
            "name match. A match here is an investigative lead requiring human "
            "verification, not a confirmed identification.",
            alert_amber
        ))
        _cm = (d.get("investigator", {}) or {}).get("criminal_match", {}) or {}
        _cm_matches = _cm.get("matches", [])
        if not _cm.get("searched"):
            story.append(P(
                f"Not searched — {_cm.get('unavailable_reason') or 'no case narrative available to search on'}.",
                evidence_style
            ))
        elif not _cm_matches:
            story.append(P(
                "No match against the connected wanted-list database for this case's narrative text.",
                evidence_style
            ))
        else:
            cm_rows = [[P("Name", th), P("Match Type", th), P("Details", th)]]
            for m in _cm_matches[:5]:
                if m.get("match_type") == "mo_based":
                    detail = f"MO keyword overlap: {m.get('match_score', 0)}% ({', '.join(m.get('matched_keywords', [])[:4])})"
                else:
                    detail = f"{m.get('crime', 'N/A')} — {m.get('location', 'N/A')} — Status: {m.get('status', 'N/A')}"
                cm_rows.append([
                    P(m.get("name", "N/A")),
                    P((m.get("match_type") or "N/A").replace("_", " ").title()),
                    P(_safe_truncate(detail, 90)),
                ])
            cm_tbl = Table(cm_rows, colWidths=[120, 90, 282])
            cm_tbl.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), DARK),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Times-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LGRAY]),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("LINEBELOW", (0, 0), (-1, 0), 0.75, DARK),
                ("GRID", (0, 0), (-1, -1), 0.4, BORDER),
            ]))
            story.append(cm_tbl)

        # ── IDENTITY RESOLUTION CANDIDATES (Phase 6, 2026-08-29) ──────────────
        # BUG FIX / NEW FEATURE: weighted multi-factor candidate correlation
        # against the connected wanted-list dataset — uses location +
        # weapon/attack keywords extracted from the case narrative, NEVER
        # the case's own supplied suspect name (which would make this a
        # trivially self-fulfilling lookup rather than genuine candidate
        # discovery). Every candidate is explicitly an unverified lead.
        story.append(Spacer(1, 14))
        story.append(Paragraph("IDENTITY RESOLUTION — CANDIDATE LEADS", h2))
        story.append(P(
            "Weighted correlation of case attributes (location, weapon/attack-method "
            "keywords) against the connected wanted-list dataset — independent of any "
            "name supplied for this case. A candidate here is an unverified investigative "
            "lead, never a confirmed identification. Confidence is capped at 25% unless "
            "supported by 2 or more independent corroborating factors (not just one "
            "coincidental keyword overlap).",
            alert_amber
        ))
        _ir = (d.get("investigator", {}) or {}).get("identity_resolution", {}) or {}
        _ir_candidates = _ir.get("candidates", [])
        _ir_status = _ir.get("status", "not_searched")
        if _ir_status.startswith("unavailable") or _ir_status.startswith("error"):
            story.append(P(f"Not searched — {_ir_status}.", evidence_style))
        elif not _ir_candidates:
            story.append(P(
                "No identity-resolution candidates met the minimum corroboration threshold for this case.",
                evidence_style
            ))
        else:
            ir_rows = [[P("Candidate", th), P("Confidence", th), P("Supporting Factors", th)]]
            for c in _ir_candidates[:5]:
                supp = "; ".join(c.get("supporting_evidence", [])[:3]) or "N/A"
                ir_rows.append([
                    P(c.get("candidate", "N/A")),
                    severity_cell(f"{c.get('confidence', 0)}%"),
                    P(_safe_truncate(supp, 100)),
                ])
            ir_tbl = Table(ir_rows, colWidths=[110, 80, 302])
            ir_tbl.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), DARK),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Times-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LGRAY]),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("LINEBELOW", (0, 0), (-1, 0), 0.75, DARK),
                ("GRID", (0, 0), (-1, -1), 0.4, BORDER),
            ]))
            story.append(ir_tbl)

        # ── UNKNOWN CRIMINAL PROFILE (Step 2) ────────────────────────────────
        cp = d.get("criminal_profile", {})
        if cp:
            story.append(Spacer(1, 14))
            story.append(Paragraph("UNKNOWN CRIMINAL PROFILE", h2))
            story.append(P(
                "Behavioural profile only — never a name. Built from investigator "
                "observations; fields marked 'AI-estimated' are keyword-based inferences "
                "from the case narrative, not confirmed facts.",
                alert_amber
            ))
            if cp.get("consistency_warning"):
                story.append(P(cp["consistency_warning"], alert_red))
            story.append(Spacer(1, 6))
            cp_rows = [
                [P("Estimated Age", small), P(cp.get("estimated_age", "Unknown")),
                 P("Gender", small), P(cp.get("gender", "Unknown"))],
                [P("Height", small), P(cp.get("height", "Unknown")),
                 P("Body Type", small), P(cp.get("body_type", "Unknown"))],
                [P("Language", small), P(cp.get("language", "Unknown")),
                 P("Accent", small), P(cp.get("accent", "Unknown"))],
                [P("Handedness", small), P(cp.get("handedness", "Unknown")),
                 P("Dominant Behaviour", small), P(cp.get("dominant_behaviour", "Unknown"))],
                [P("Entry Method", small), P(cp.get("entry_method", "Unknown")),
                 P("Behaviour at Scene", small), P(cp.get("behaviour_at_scene", "Unknown"))],
                [P("Weapons Used", small), P(cp.get("weapons_used", "Unknown")),
                 P("Vehicle Used", small), P(cp.get("vehicle_used", "Unknown"))],
                [P("Likely Team Size", small), P(cp.get("likely_team_size", "Unknown")),
                 P("Technical Skill", small), P(cp.get("technical_skill", "Unknown"))],
                [P("Experience Level", small), P(cp.get("experience_level", "Unknown")),
                 P("Planning Level", small), P(cp.get("planning_level", "Unknown"))],
                [P("Risk Behaviour", small), P(cp.get("risk_behaviour", "Unknown")),
                 P("Escape Method", small), P(cp.get("escape_pattern", "Unknown"))],
                [P("MO Signature", small), P(cp.get("mo_signature", "Unknown")),
                 P("Operational Sophistication", small), P(cp.get("operational_sophistication", "Unknown"))],
                [P("Behavioral Profile Confidence", small), P(f"{cp.get('profile_confidence', 0)}%"),
                 P("", small), P("")],
            ]
            cp_tbl = Table(cp_rows, colWidths=[85, 145, 85, 155])
            cp_tbl.setStyle(TableStyle([
                ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, LGRAY]),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("GRID", (0, 0), (-1, -1), 0.4, BORDER),
            ]))
            story.append(cp_tbl)
            if cp.get("behaviour_profile_notes"):
                story.append(Spacer(1, 6))
                story.append(P(f"Notes: {cp['behaviour_profile_notes']}", evidence_style))

        # ── NETWORK, FINANCIAL & VEHICLE INTELLIGENCE ───────────────────────
        net_matches_pdf = d.get("network_matches", [])
        net_summary_pdf = d.get("network_summary", "")
        fin_flags_pdf   = d.get("financial_flags", [])
        veh_flags_pdf   = d.get("vehicle_flags", [])
        if net_matches_pdf or fin_flags_pdf or veh_flags_pdf:
            story.append(Spacer(1, 14))
            story.append(Paragraph("NETWORK, FINANCIAL & VEHICLE INTELLIGENCE", h2))

            if net_matches_pdf:
                story.append(Paragraph("Known Associates / Network", h3))
                story.append(P(
                    "⚠ Non-STRONG rows below are database/semantic word-overlap leads — NOT an established "
                    "network association with this case. Only STRONG-strength rows reflect a close name match; "
                    "PARTIAL rows require independent verification before being treated as a connection to this case.",
                    small
                ))
                story.append(P(net_summary_pdf or f"{len(net_matches_pdf)} match(es) found", small))
                net_rows = [[P("Queried Name", th), P("Matched Record", th), P("Dataset", th), P("Strength / Type", th)]]
                for m in net_matches_pdf[:8]:
                    # BUG FIX (reviewer feedback — "Datasoft" residual
                    # noise): label non-strong rows explicitly as a
                    # database lead, not a network association, matching
                    # the same fix applied to the live-preview HTML above.
                    _strength_label = "STRONG (network match)" if m.get("strength") == "strong" \
                        else f"{m.get('strength','').upper()} — semantic/database lead, no case link established"
                    net_rows.append([
                        P(m.get("query", "")), P(m.get("name", "")),
                        P(m.get("dataset", "")[:24]), severity_cell(_strength_label),
                    ])
                net_tbl = Table(net_rows, colWidths=[90, 110, 85, 137])
                net_tbl.setStyle(TableStyle([
                    ("BACKGROUND", (0, 0), (-1, 0), DARK),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTNAME", (0, 0), (-1, 0), "Times-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LGRAY]),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                    ("LEFTPADDING", (0, 0), (-1, -1), 8),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                    ("LINEBELOW", (0, 0), (-1, 0), 0.75, DARK),
                    ("GRID", (0, 0), (-1, -1), 0.4, BORDER),
                ]))
                story.append(net_tbl)
                story.append(Spacer(1, 10))

            if fin_flags_pdf:
                story.append(Paragraph("Financial IDs / Crypto Wallets", h3))
                for flag in fin_flags_pdf:
                    story.append(P(f"  💰 {flag}", evidence_style))
                story.append(Spacer(1, 10))

            if veh_flags_pdf:
                story.append(Paragraph("Vehicle / License Plate / Vessel", h3))
                for flag in veh_flags_pdf:
                    story.append(P(f"  🚗 {flag}", evidence_style))

        # ── AGYAT APRADHI — Unidentified Offender Leads ─────────────────────
        ui_leads = d.get("unidentified_leads", {})
        if d.get("unidentified_search_run") and ui_leads.get("lead_count", 0) > 0:
            story.append(Spacer(1, 14))
            story.append(Paragraph("AGYAT APRADHI — UNIDENTIFIED OFFENDER LEADS", h2))
            story.append(P(
                "Suspect identity unknown — matched by Modus Operandi / physical description "
                "against wanted, fugitive, and crime-pattern datasets. These are POSSIBLE LEADS "
                "ONLY, not confirmed identifications. Verify independently before any action.",
                alert_amber
            ))
            story.append(Spacer(1, 6))
            lead_rows = [[P("Dataset", th), P("Candidate / Alias", th), P("Detail", th)]]
            for lead in ui_leads.get("possible_leads", [])[:8]:
                lead_rows.append([
                    P(_safe_truncate(lead.get("dataset", ""), 30)),
                    P(f"{lead.get('candidate_name_or_alias','')} ({lead.get('entity_type','')})"),
                    P((lead.get("detail", "") or "")[:180]),
                ])
            lead_tbl = Table(lead_rows, colWidths=[90, 150, 252])
            lead_tbl.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), DARK),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Times-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LGRAY]),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("LINEBELOW", (0, 0), (-1, 0), 0.75, DARK),
                ("GRID", (0, 0), (-1, -1), 0.4, BORDER),
            ]))
            story.append(lead_tbl)

        # ── MO FINGERPRINTING — Link to Unsolved Cases ──────────────────────
        mo_links = d.get("mo_fingerprint_links", {})
        if not mo_links.get("linked_cases") and mo_links.get("suppressed_links"):
            story.append(Spacer(1, 14))
            story.append(Paragraph("MO FINGERPRINTING — LINK TO UNSOLVED CASES", h2))
            story.append(P(mo_links.get("note") or "No MO link found.", evidence_style))
            for c in mo_links["suppressed_links"][:3]:
                story.append(P(f"  × Not used: case {c.get('case_id','?')} [{c.get('crime_type','?')}] — {c.get('suppressed_reason','')}", small))
        if mo_links.get("linked_cases") or mo_links.get("confirmed_links"):
            story.append(Spacer(1, 14))
            story.append(Paragraph("MO FINGERPRINTING — LINK TO UNSOLVED CASES", h2))
            story.append(P(
                "Cases below share a similar crime signature (Modus Operandi) to this case. "
                "These are POSSIBLE LINKS ONLY — never auto-merged. An investigator must "
                "independently verify before treating cases as connected.",
                alert_amber
            ))
            story.append(Spacer(1, 6))
            any_cross_cat_pdf = any(not c.get("category_match", True) for c in mo_links.get("linked_cases", []))
            if any_cross_cat_pdf:
                story.append(P(
                    "⚠ NO MATCH FOUND WITHIN THE SAME CRIME CATEGORY. The case(s) below are from "
                    "a DIFFERENT crime category — this is a text-similarity match only and should "
                    "be treated as a much weaker lead than a same-category match.",
                    alert_red
                ))
                story.append(Spacer(1, 6))
            mo_rows = [[P("Case ID", th), P("Type / Location", th), P("MO Description", th),
                        P("Entry / Escape", th), P("Planning / Team", th), P("MO Signature", th),
                        P("Fingerprint", th)]]
            for c in mo_links.get("linked_cases", [])[:6]:
                cat_note = "" if c.get("category_match", True) else "  ⚠ DIFFERENT CATEGORY"
                mo_rows.append([
                    P(str(c.get("case_id", ""))),
                    P(f"{c.get('crime_type','')}{cat_note} — {c.get('location','')}"),
                    P((c.get("mo_description", "") or "")[:180]),
                    P(f"{c.get('entry_method') or 'Not recorded'} / {c.get('escape_method') or 'Not recorded'}"),
                    P(f"{c.get('planning_level') or 'Not recorded'} / {c.get('team_size') or 'Not recorded'}"),
                    P(c.get("mo_signature") or "Not recorded"),
                    P(f"{c.get('fingerprint_score', 0)}% ({c.get('fingerprint_match_level', 'LOW')}); link: {c.get('link_confidence', 'n/a')}"),
                ])
            mo_tbl = Table(mo_rows, colWidths=[40, 85, 130, 80, 80, 22, 55])
            mo_tbl.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), DARK),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Times-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LGRAY]),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("LINEBELOW", (0, 0), (-1, 0), 0.75, DARK),
                ("GRID", (0, 0), (-1, -1), 0.4, BORDER),
            ]))
            if mo_links.get("linked_cases"):
                story.append(mo_tbl)
            if mo_links.get("confirmed_links"):
                story.append(Spacer(1, 8))
                story.append(P("Confirmed Links on Record:", small))
                for cl in mo_links["confirmed_links"][:5]:
                    story.append(P(
                        f"  • {cl.get('case_id','?')} ↔ {cl.get('linked_case_id','?')} "
                        f"({cl.get('link_type','?')}, confidence {cl.get('confidence','?')}) — {cl.get('notes','')}",
                        evidence_style
                    ))

        # ── REASONING ENGINE — Gaps, Contradictions, Hypotheses, Draft Report ──
        reasoning_pdf = d.get("reasoning", {})
        if reasoning_pdf:
            story.append(PageBreak())
            story.append(Paragraph("REASONING ENGINE — GAPS, CONTRADICTIONS & LEADS", h2))
            story.append(P(
                "AI-suggested only. The human investigator/journalist makes all final calls "
                "on what to verify, publish, or act on.",
                alert_amber
            ))
            story.append(Spacer(1, 8))

            gaps_pdf = reasoning_pdf.get("gaps", [])
            story.append(Paragraph(f"Gaps in Evidence ({len(gaps_pdf)})", h3))
            if gaps_pdf:
                for g in gaps_pdf:
                    story.append(P(f"• {g['gap']}", evidence_style))
                    story.append(P(f"   Why it matters: {g['why_it_matters']}  |  Suggested step: {g['next_step']}", small))
            else:
                story.append(P("None identified — all evidence types were provided.", small))
            story.append(Spacer(1, 8))

            contras_pdf = reasoning_pdf.get("contradictions", []) + _signal_contradictions
            story.append(Paragraph(f"Contradictions ({len(contras_pdf)})", h3))
            if contras_pdf:
                for c in contras_pdf:
                    story.append(P(f"• {c['contradiction']}", evidence_style))
                    story.append(P(f"   Sources: {c['sources']}  |  Severity: {c['severity']}", small))
            else:
                story.append(P("None detected between the pieces of evidence checked.", small))
            story.append(Spacer(1, 8))

            hyps_pdf = reasoning_pdf.get("hypotheses", [])
            _inv_for_hyps = d.get("investigator", {}) or {}
            _adv_for_hyps = _inv_for_hyps.get("advanced", {}) or {}
            _adv_hyps = (_adv_for_hyps.get("hypothesis_ranking", {}) or {}).get("top_hypotheses", []) or []

            if _adv_hyps:
                # Advanced Hypothesis Engine has real, evidence-ranked
                # theories — show those as THE investigative hypotheses
                # (this is what Page 14/15 already call the Primary Theory
                # and Hypothesis Ranking), instead of the basic reasoning
                # engine's single, often-stale placeholder hypothesis.
                story.append(Paragraph(f"Investigative Hypotheses ({len(_adv_hyps)}) — Advanced Hypothesis Engine", h3))
                story.append(P(
                    "Ranked by the Advanced Hypothesis Engine using this case's evidence "
                    "(see Hypothesis Ranking / Explainable AI sections for full supporting "
                    "detail). This supersedes the basic reasoning pass below where the two "
                    "disagree.",
                    small))
                for i, h in enumerate(_adv_hyps, 1):
                    try:
                        _conf = float(h.get("confidence", 0) or 0)
                    except (TypeError, ValueError):
                        _conf = 0
                    _status = "ACTIVE / HIGHLY SUPPORTED" if _conf >= 80 else "ACTIVE" if _conf >= 50 else "ACTIVE / LOW SUPPORT"
                    story.append(P(f"H{i}. {h.get('name','')}  —  Confidence: {_conf}%  —  Status: {_status}", evidence_style))
                    for se in (h.get("evidence_for") or [])[:4]:
                        story.append(P(f"   + Supports: {se}", small))
                story.append(Spacer(1, 6))
                if hyps_pdf:
                    story.append(Paragraph("Alternative / Counter-Hypothesis (Basic Reasoning Pass)", h3))
                    story.append(P(
                        "A separate, simpler keyword-based reasoning pass — kept visible as a "
                        "counter-consideration, not a competing primary finding.",
                        small))
                    for i, h in enumerate(hyps_pdf, 1):
                        story.append(P(f"• {h['hypothesis']}  [confidence: {h['confidence']}]", evidence_style))
                        story.append(P(f"   Source: {h['source']}", small))
            else:
                story.append(Paragraph(f"Investigative Hypotheses ({len(hyps_pdf)})", h3))
                for i, h in enumerate(hyps_pdf, 1):
                    story.append(P(f"H{i}. {h['hypothesis']}  [confidence: {h['confidence']}]", evidence_style))
                    story.append(P(f"   Source: {h['source']}", small))
                    for se in h.get("supporting_evidence", []):
                        story.append(P(f"   + Supports: {se}", small))
                    for ce in h.get("contradicting_evidence", []):
                        story.append(P(f"   − Contradicts: {ce}", small))
            story.append(Spacer(1, 10))

            story.append(Paragraph("Draft Investigative Report (editable — not a final finding)", h3))
            for dl in reasoning_pdf.get("draft_report", "").split("\n"):
                story.append(P(dl if dl.strip() else " ", evidence_style))

            qwen_story_pdf = d.get("qwen_story_draft", "")
            if qwen_story_pdf:
                story.append(Spacer(1, 10))
                story.append(Paragraph("AI-Drafted Story Opening (LLM narrative)", h3))
                story.append(P(
                    "AI-generated draft prose — verify every claim independently before "
                    "editing into a publishable piece.",
                    alert_amber
                ))
                for dl in qwen_story_pdf.split("\n"):
                    story.append(P(dl if dl.strip() else " ", evidence_style))

        # ── NEXT EVIDENCE RECOMMENDATION ─────────────────────────────────────
        next_ev = intel.get("next_evidence", []) if intel else []
        story.append(Spacer(1, 14))
        story.append(Paragraph("NEXT EVIDENCE RECOMMENDATION", h2))
        if next_ev:
            ne_rows = [[P("Priority", th), P("Recommendation", th), P("Reason", th)]]
            for ne in next_ev:
                ne_rows.append([severity_cell(ne["priority"]), P(ne["recommendation"]), P(ne["reason"], evidence_style)])
            ne_tbl = Table(ne_rows, colWidths=[70, 170, 262])
            ne_tbl.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), DARK),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Times-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LGRAY]),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("GRID", (0, 0), (-1, -1), 0.4, BORDER),
            ]))
            story.append(ne_tbl)
        else:
            story.append(P("None — all core evidence types have been collected.", evidence_style))

        # ── p44: INVESTIGATION ROADMAP (ranked, de-duplicated) ──────────────
        _road = d.get("roadmap") or []
        if _road:
            story.append(Spacer(1, 14))
            story.append(Paragraph(f"INVESTIGATION ROADMAP ({len(_road)} ranked steps)", h2))
            _rr = [[P("#", th), P("Priority", th), P("Step", th), P("Why", th)]]
            for _i, _r in enumerate(_road, 1):
                _rr.append([P(str(_i)), severity_cell(_r.get("priority", "Medium")), P(_r.get("step", "")), P(_r.get("why", ""), evidence_style)])
            _rt = Table(_rr, colWidths=[22, 62, 200, 218])
            _rt.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), DARK), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTSIZE", (0, 0), (-1, -1), 8.5), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LGRAY]),
                ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("GRID", (0, 0), (-1, -1), 0.4, BORDER)]))
            story.append(_rt)
            story.append(P("Leads for the investigator, not findings. Duplicates across sections are merged here.", evidence_style))

        # ── INVESTIGATION TIMELINE ───────────────────────────────────────────
        timeline_pdf = d.get("timeline", [])
        story.append(Spacer(1, 14))
        story.append(Paragraph("INVESTIGATION TIMELINE", h2))
        story.append(P(
            "First row is the intake incident date as reported; the rest are AI-extracted from the case narrative — verify every timestamp against "
            "CCTV, call records, or other independent sources before use.",
            alert_amber
        ))
        story.append(Spacer(1, 6))
        if timeline_pdf:
            tl_rows = [[P("Time", th), P("Event", th)]]
            for ev in timeline_pdf:
                tl_rows.append([P(str(ev.get("time", "?"))), P(ev.get("event", "") + (f"  <i>[{ev.get('source')}]</i>" if ev.get("source") else ""))])
            tl_tbl = Table(tl_rows, colWidths=[100, 402])
            tl_tbl.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), DARK),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Times-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LGRAY]),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("GRID", (0, 0), (-1, -1), 0.4, BORDER),
            ]))
            story.append(tl_tbl)
        else:
            story.append(P("No time-stamped events could be extracted from the narrative.", evidence_style))

        # Threat Assessment
        story.append(Spacer(1, 14))
        story.append(Paragraph("THREAT ASSESSMENT MATRIX", h2))
        threat = d.get("threat", {})
        # BUG FIX (2026-08-20 — P0): these "Evidence Basis" strings used to
        # be static text regardless of what evidence actually existed for
        # THIS case (e.g. "Weapon/threat entities + criminal history" shown
        # even when Page 7 says "NO CONFIRMED RECORD", or "watchlist status
        # + associates" implying a positive watchlist hit when none exists).
        # Build each basis line from what's actually true for this case.
        _wl = d.get("watchlist", {}) or {}
        _has_criminal_history = bool(_wl.get("criminal_history")) and "NO CONFIRMED RECORD" not in str(_wl.get("criminal_history", "")).upper()
        # BUG FIX (P0 — reviewer feedback, "Physical Threat provenance"
        # bug): this checked NER `entities.get("WEAPON")/("THREAT")` —
        # a COMPLETELY SEPARATE signal from what actually drives the
        # Physical Threat LEVEL above (`crime_info["all_crimes"]` /
        # keyword classification, stored here as `d["crime_evidence"]`).
        # NER and keyword classification can disagree — e.g. a keyword
        # match sets Physical Threat to HIGH while NER tagged no WEAPON/
        # THREAT entity at all — which made this basis text say "no
        # weapon/threat language" right next to a HIGH verdict driven by
        # the OTHER system. Use the SAME evidence trail that actually
        # produced the physical-threat level, so the level and its basis
        # can never contradict each other.
        _crime_evidence_trail = d.get("crime_evidence", []) or []
        _weapon_violence_hits = [e for e in _crime_evidence_trail if "violent crime indicator" in str(e).lower()
                                  or "weapons" in str(e).lower()]
        if _weapon_violence_hits and _has_criminal_history:
            _physical_basis = (f"Matched case-narrative indicator(s): {'; '.join(_weapon_violence_hits[:2])} "
                                f"+ name-matched criminal-history record (identity unverified)")
        elif _weapon_violence_hits:
            _physical_basis = f"Matched case-narrative indicator(s): {'; '.join(_weapon_violence_hits[:2])} (no criminal-history match on file)"
        elif _has_criminal_history:
            _physical_basis = "Name-matched criminal-history record only (identity unverified) — no weapon/threat language in this case's narrative"
        else:
            _physical_basis = "No weapon/threat language in case narrative and no criminal-history match on file"
        _fincen_hit = str(_wl.get("fintrac_sar", "")).upper() not in ("NO", "NO MATCH RETURNED", "")
        _financial_basis = "Financial anomaly score" + (" + confirmed FinCEN SAR" if _fincen_hit else " (no FinCEN SAR match on file)")
        _doc_ev_for_basis = d.get("doc_evidence", {}) or {}
        _doc_has_fraud_indicators = bool(_doc_ev_for_basis.get("risk_indicators"))
        _doc_files_submitted = bool((_doc_ev_for_basis.get("document_metadata") or {}).get("Files_Count", 0))
        # BUG FIX (reviewer feedback): this used to read "document-tampering
        # check unavailable — no document evidence submitted" any time
        # there were no risk_indicators — including cases where a document
        # WAS submitted and simply came back clean, which is not the same
        # thing as "no document evidence submitted" at all.
        if _doc_has_fraud_indicators:
            _cyber_basis = "Deception score + document fraud indicators (see Document Evidence findings)"
        elif _doc_files_submitted:
            _cyber_basis = "Deception score (document submitted and reviewed — no fraud indicators found)"
        else:
            _cyber_basis = "Deception score (document-tampering check unavailable — no document evidence submitted)"
        _has_watchlist_hit = any(str(_wl.get(k, "")).upper() not in ("NO", "NO MATCH RETURNED", "") for k in ("interpol", "fbi_watchlist", "sanctions", "pep_status", "fintrac_sar"))
        _has_associates = bool(_wl.get("associates"))
        _public_basis = "Composite risk score" + (" + confirmed watchlist match" if _has_watchlist_hit else " (no confirmed watchlist match)") + (" + known associates on file" if _has_associates else "")
        threat_rows = [
            [P("Threat Dimension", th), P("Level", th), P("Evidence Basis", th)],
            [P("Physical Threat"), severity_cell(threat.get("physical", "None")),
             P(_physical_basis)],
            [P("Financial Threat"), severity_cell(threat.get("financial", "None")),
             P((threat.get("basis") or {}).get("financial") or _financial_basis)],
            [P("Cyber Threat"), severity_cell(threat.get("cyber", "None")),
             P((threat.get("basis") or {}).get("cyber") or _cyber_basis)],
            [P("Public Safety Risk"), severity_cell(threat.get("public_safety", "None")),
             P(_public_basis)],
            [P("Escalation Probability"),
             severity_cell(threat.get("escalation_display") or (f"{threat.get('escalation_prob'):.1f}%" if isinstance(threat.get('escalation_prob'), (int, float)) else "NOT ASSESSED")),
             P((threat.get("basis") or {}).get("escalation") or "Combined risk factors over 30-day horizon")],
        ]
        threat_tbl = Table(threat_rows, colWidths=[140, 100, 252])
        threat_tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), DARK),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Times-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LGRAY]),
            ("TOPPADDING", (0, 0), (-1, -1), 7),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("LINEBELOW", (0, 0), (-1, 0), 0.75, DARK),
            ("GRID", (0, 0), (-1, -1), 0.4, BORDER),
        ]))
        story.append(threat_tbl)

        # Evidence Integrity
        story.append(Spacer(1, 14))
        story.append(Paragraph("EVIDENCE INTEGRITY & CHAIN OF CUSTODY", h2))
        ei = d.get("evidence_integrity", {})
        def _short_hash(h, n=16):
            # BUG FIX (2026-08-20 — High): this used to insert a space
            # every 4 characters unconditionally to make long hex hashes
            # wrap cleanly (e.g. "a1b2 c3d4 e5f6…"). But when evidence
            # wasn't submitted, this field doesn't hold a hash at all — it
            # holds a full status SENTENCE like "N/A — No audio evidence
            # submitted". Running that sentence through the same 4-char
            # grouping logic produced garbled, mid-word-broken text (e.g.
            # "aud io e...", "document f...") that read as corrupted data.
            # Only apply hash-style character grouping to strings that
            # actually look like a hash/token (no spaces); plain status
            # sentences get word-safe truncation instead.
            h = str(h or "N/A")
            if len(h) <= n:
                return h
            if " " in h:
                # Not a hash — it's a status sentence. Truncate at a word
                # boundary instead of chopping it into 4-char fragments.
                return _safe_truncate(h, n * 2)
            # p23: full SHA-256 (no truncation), split in two halves so it wraps
            if re.fullmatch(r"[0-9a-fA-F]{64}", h):
                return h[:32] + "<br/>" + h[32:]
            return h

        ev_rows = [
            [P("Evidence Type", th), P("Hash / Status", th), P("Metadata", th)],
            [P("Photo"), P(_short_hash(ei.get("photo_hash", "N/A"))),
             P(_safe_truncate(str(ei.get("photo_metadata", {})), 100))],
            [P("Audio"), P(_short_hash(ei.get("audio_hash", "N/A"))),
             P(_safe_truncate(str(ei.get("audio_metadata", {})), 100))],
            [P("Document"), P(_short_hash(ei.get("doc_hash", "N/A"))),
             P(_safe_truncate(str(ei.get("document_metadata", {})), 100))],
            [P("Tampering Detection"), severity_cell(ei.get("tampering_status", "N/A")),
             P("Deepfake / splicing / forgery analysis")],
            [P("Chain of Custody"), P(ei.get("chain_of_custody", "N/A")),
             P("Timestamped evidence log")],
        ]
        ev_tbl = Table(ev_rows, colWidths=[100, 200, 192])
        ev_tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), DARK),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Times-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8.5),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LGRAY]),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("LINEBELOW", (0, 0), (-1, 0), 0.75, DARK),
            ("GRID", (0, 0), (-1, -1), 0.4, BORDER),
        ]))
        story.append(ev_tbl)

        # Actionable Intelligence
        story.append(Spacer(1, 14))
        story.append(Paragraph("ACTIONABLE INTELLIGENCE (Evidence-Based)", h2))
        actions = d.get("actions", ["No specific actions recommended."])
        ev_based = d.get("evidence_based_actions", [])
        for i, (action, basis) in enumerate(zip(actions, ev_based + [""] * (len(actions) - len(ev_based))), 1):
            if "CRITICAL" in action or "IMMEDIATE" in action or "ESCALATE" in action:
                story.append(P(f"{i}. {action}", alert_red))
            elif "PRIORITY" in action or "FORENSIC" in action or "FINANCIAL" in action:
                story.append(P(f"{i}. {action}", alert_amber))
            else:
                story.append(P(f"{i}. {action}"))
            if basis:
                story.append(P(f"   Basis: {basis}", evidence_style))
            story.append(Spacer(1, 3))

        # Evidence Sources Status
        story.append(Spacer(1, 14))
        story.append(Paragraph("EVIDENCE SOURCES STATUS (this case)", h2))
        status = d.get("source_status") or {}
        status_rows = [[P("Source", th), P("Status", th), P("Evidence Type", th)]]
        source_map = {
            "NER": "Text Evidence (Named Entities)",
            "Voice": "Voice Evidence (Biometrics)",
            "ArcFace": "Facial Evidence (Visual Analysis)",
            "OCR": "Document Evidence (Text Extraction)",
            "Risk": "Pattern Evidence (Behavioral Analysis)",
            "Datasets": "Watchlist / Database Search",
            "AI Reasoning": "LLM Statement & Hypothesis Analysis",
            "CCTV": "CCTV / Photo Crime-Scene Classification",
            "Deepfake": "Photo Tamper / Deepfake Detection",
        }
        for k, v in status.items():
            status_rows.append([P(k), severity_cell(str(v)), P(source_map.get(k, "N/A"))])
        status_tbl = Table(status_rows, colWidths=[100, 150, 242])
        status_tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), DARK),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Times-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LGRAY]),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("LINEBELOW", (0, 0), (-1, 0), 0.75, DARK),
            ("GRID", (0, 0), (-1, -1), 0.4, BORDER),
        ]))
        story.append(status_tbl)

        # ── INVESTIGATOR ENGINE INTELLIGENCE (added: was UI-only before) ──────
        inv = d.get("investigator", {}) or {}
        if inv:
            story.append(Spacer(1, 14))
            story.append(Paragraph("INVESTIGATOR INTELLIGENCE", h2))

            def _humanize(val):
                """Turns nested dict/list structures into plain, readable text
                instead of a raw Python/JSON dump (e.g. {'key': 'value'})."""
                if isinstance(val, dict):
                    parts = []
                    for k, v in val.items():
                        label = str(k).replace("_", " ").strip().title()
                        parts.append(f"{label}: {_humanize(v)}")
                    return "; ".join(parts)
                if isinstance(val, (list, tuple)):
                    return ", ".join(_humanize(v) for v in val) if val else "None"
                if isinstance(val, bool):
                    return "Yes" if val else "No"
                if val is None or val == "":
                    return "Unknown"
                return str(val)

            def _fmt_item(item):
                return _humanize(item)

            # Evidence Completeness — table instead of a "Name: X; Status: Y;
            # Weight: Z; Reasoning: ..." bullet dump, which reads like raw
            # debug output rather than a report.
            ec = inv.get("evidence_completeness", {}) or {}
            if ec:
                story.append(Paragraph("Evidence Completeness", h3))
                # This engine's own weighted-module total (NER/Risk/Watchlist/
                # Photo/Voice/OCR/CCTV) disagreed with the plain "how many
                # evidence types were actually submitted" percentage shown
                # elsewhere in the report (e.g. text-only modules like NER
                # and Risk Analysis always run and score points even with
                # zero evidence files uploaded, inflating this total vs. the
                # simpler evidence-types-submitted count). Rather than show
                # two different completeness percentages for the same
                # concept, this now displays the single authoritative
                # evidence-types-submitted figure everywhere; the per-module
                # breakdown below still shows which AI modules ran.
                _authoritative_completeness = (d.get("intel_summary", {}) or {}).get("completeness_pct")
                _completeness_display = (f"{_authoritative_completeness}%"
                                          if _authoritative_completeness is not None else ec.get('total', '0%'))
                story.append(P(
                    f"Total: {_completeness_display}  "
                    f"(simple count of evidence types submitted — see weighted "
                    f"figure below for the per-component breakdown)", small))
                _components = ec.get("components", []) or []
                # Watchlist/database searches (PEP, Sanctions, Interpol, FBI,
                # FinCEN — see the Network & Watchlist Status section) are
                # genuinely performed by this pipeline, independently of the
                # evidence-completeness engine's own component list, which
                # only knows about a handful of evidence-file types and
                # always marks "Watchlist" as missing/weight-0 since it was
                # never wired to see the real search result. Reconcile it
                # here with the actual result instead of showing "Analyzed"
                # on Page 6 and "Missing" on Page 11 for the same search.
                # CCTV: the classifier can run on a fallback suspect photo
                # when no video was submitted (see cctv_source_label above)
                # — "CCTV: ANALYZED" in this table reads as "CCTV footage
                # was available" when it may only mean "the model ran on a
                # substitute image". Make the fallback explicit here too.
                _cctv_label = d.get("cctv_source_label") or ""
                if "no CCTV video submitted" in _cctv_label:
                    for comp in _components:
                        if isinstance(comp, dict) and "cctv" in str(comp.get("name", "")).lower():
                            comp["reasoning"] = (
                                "Classifier EXECUTED on fallback source (suspect photo) — "
                                "CCTV footage NOT SUBMITTED for this case."
                            )

                _wl = d.get("watchlist", {}) or {}
                _wl_searched = bool(_wl) and any(
                    _wl.get(k) is not None for k in
                    ("interpol", "fbi_watchlist", "sanctions", "pep", "fincen", "status")
                )
                if _wl_searched:
                    _wl_hit = any(
                        str(_wl.get(k, "NO")) not in ("NO", "N/A", "", "None")
                        for k in ("interpol", "fbi_watchlist", "sanctions", "pep", "fincen")
                    )
                    _wl_status = "Present"
                    _wl_reasoning = (
                        "Database/watchlist search executed (PEP, Sanctions, Interpol, FBI, "
                        "FinCEN) — " + ("confirmed match found" if _wl_hit else "no confirmed match")
                    )
                    _found_wl_row = False
                    for comp in _components:
                        if isinstance(comp, dict) and "watchlist" in str(comp.get("name", "")).lower():
                            comp["status"] = "✓"
                            comp["reasoning"] = _wl_reasoning
                            _found_wl_row = True
                    if not _found_wl_row:
                        _fallback_weight = 15
                        for _c in _components:
                            if isinstance(_c, dict) and _c.get("weight"):
                                _fallback_weight = _c["weight"]
                                break
                        _components = list(_components) + [{
                            "name": "Watchlist", "status": "✓",
                            "weight": _fallback_weight,
                            "reasoning": _wl_reasoning,
                        }]
                if _components and all(isinstance(c, dict) for c in _components):
                    # BUG FIX (2026-08-20 — High): once the Watchlist row
                    # is appended above, the table's own weights no longer
                    # sum to 100 (e.g. 100 + a 20-weight Watchlist row =
                    # 120) — but the headline "Total: X%" above still came
                    # from a completely different, unweighted calculation
                    # (simple evidence-types-submitted count). Reviewers
                    # correctly flagged this as unexplained math. Show the
                    # table's own weighted total explicitly, with its real
                    # denominator, so the two numbers can never disagree.
                    def _comp_weight(c):
                        try:
                            return float(c.get("weight", 0) or 0)
                        except (TypeError, ValueError):
                            return 0.0
                    _total_weight_sum = sum(_comp_weight(c) for c in _components)
                    _available_weight_sum = sum(
                        _comp_weight(c) for c in _components
                        if str(c.get("status", "")).strip() in ("✓", "true", "True", "yes")
                    )
                    if _total_weight_sum > 0:
                        _weighted_pct = round((_available_weight_sum / _total_weight_sum) * 100, 1)
                        story.append(P(
                            f"Weighted Evidence Completeness: {_weighted_pct}%  "
                            f"({_available_weight_sum:g} / {_total_weight_sum:g} points collected)",
                            small))
                        # NEW: side-by-side bar chart comparing the two
                        # completeness metrics — added per user request for
                        # more visual coverage; this pairing has repeatedly
                        # been misread as "two conflicting numbers" when
                        # shown as plain text, so a chart makes the "these
                        # are different metrics" point visually obvious.
                        _simple_coverage_pct = (d.get("intel_summary", {}) or {}).get("completeness_pct", 0)
                        _cov_chart = _pdf_evidence_coverage_chart(_simple_coverage_pct, _weighted_pct)
                        if _cov_chart:
                            story.append(Spacer(1, 4))
                            story.append(_cov_chart)
                    _comp_rows = [[P("Component", th), P("Status", th), P("Weight", th), P("Reasoning", th)]]
                    for comp in _components:
                        status_raw = str(comp.get("status", "")).strip()
                        status_disp = "Present" if status_raw in ("✓", "true", "True", "yes") else \
                                      ("Not Submitted for This Case" if status_raw in ("✕", "✗", "false", "False", "no") else status_raw)
                        _comp_rows.append([
                            P(comp.get("name", "")), P(status_disp),
                            P(str(comp.get("weight", ""))), P(comp.get("reasoning", "")),
                        ])
                    _comp_tbl = Table(_comp_rows, colWidths=[90, 60, 50, 280])
                    _comp_tbl.setStyle(TableStyle([
                        ("BACKGROUND", (0, 0), (-1, 0), DARK),
                        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LGRAY]),
                        ("TOPPADDING", (0, 0), (-1, -1), 4),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                        ("GRID", (0, 0), (-1, -1), 0.4, BORDER),
                    ]))
                    story.append(_comp_tbl)
                else:
                    for comp in _components:
                        story.append(P(f"• {_fmt_item(comp)}", evidence_style))
                story.append(Spacer(1, 6))

            # Unknown Criminal Profile (from Investigator Engine)
            up = inv.get("unknown_profile", {}) or {}
            if up:
                story.append(Paragraph("Unknown Profile (Investigator Engine)", h3))
                up_rows = [
                    [P("Estimated Age", small), P(str(up.get("estimated_age", "Unknown"))),
                     P("Estimated Gender", small), P(str(up.get("estimated_gender", "Unknown")))],
                    [P("Modus Operandi", small), P(str(up.get("modus_operandi", "Unknown"))),
                     P("MO Signature", small), P(str(up.get("mo_signature", "Unknown")))],
                    [P("Behavioral Profile Confidence", small), P(f"{up.get('profile_confidence', 0)}%"),
                     P("", small), P("")],
                ]
                up_tbl = Table(up_rows, colWidths=[100, 148, 100, 144])
                up_tbl.setStyle(TableStyle([
                    ("FONTSIZE", (0, 0), (-1, -1), 9),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, LGRAY]),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                    ("LEFTPADDING", (0, 0), (-1, -1), 8),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                    ("GRID", (0, 0), (-1, -1), 0.4, BORDER),
                ]))
                story.append(up_tbl)
                story.append(Spacer(1, 6))

            # Reasoning Matrix
            reasoning = inv.get("reasoning_matrix", []) or []
            if reasoning:
                story.append(Paragraph("Reasoning Matrix", h3))
                for r in reasoning:
                    story.append(P(f"• {_fmt_item(r)}", evidence_style))
                story.append(Spacer(1, 6))

            # Investigation Paths
            ip = inv.get("investigation_paths", {}) or {}
            if ip:
                story.append(Paragraph("Investigation Paths", h3))
                story.append(P(
                    f"Total: {ip.get('total', 0)}  |  Strong: {ip.get('strong', 0)}  |  "
                    f"Rejected: {ip.get('rejected', 0)}", small))
                for path in ip.get("paths", []) or []:
                    # LABEL FIX: this dict's "confidence" field is really this
                    # investigation PATH's own priority/worth as a lead (e.g.
                    # "Financial trail investigation" gets a template MEDIUM
                    # regardless of whether financial evidence was actually
                    # submitted) — it is NOT a measure of evidence confidence,
                    # and reads confusingly next to sections that genuinely
                    # are evidence-derived confidence numbers. Rename only
                    # for display; the underlying dict/data is untouched.
                    _display_path = dict(path)
                    if "confidence" in _display_path:
                        _display_path["investigation_value"] = _display_path.pop("confidence")
                    story.append(P(f"• {_fmt_item(_display_path)}", evidence_style))
                story.append(Spacer(1, 6))

            # Uncollected Evidence — Potential Investigation Gain
            missing = inv.get("missing_impact", []) or []
            if missing:
                story.append(Paragraph("Not Yet Submitted — Potential Investigation Gain", h3))
                for m in missing:
                    story.append(P(f"• {_fmt_item(m)}", alert_amber))
                story.append(Spacer(1, 6))

            # Investigation Value
            value = inv.get("investigation_value", []) or []
            if value:
                story.append(Paragraph("Investigation Value", h3))
                for v in value:
                    story.append(P(f"• {_fmt_item(v)}", evidence_style))
                story.append(Spacer(1, 6))

            # Deepfake Impact
            deepfake_impact = inv.get("deepfake_impact", []) or []
            if deepfake_impact:
                story.append(Paragraph("Deepfake Impact", h3))
                for df in deepfake_impact:
                    story.append(P(f"• {_fmt_item(df)}", evidence_style))
                story.append(Spacer(1, 6))

            # Risk Assessment (Investigator Engine)
            inv_risk = inv.get("risk", {}) or {}
            if inv_risk:
                story.append(Paragraph("Risk Assessment (Investigator Engine)", h3))
                story.append(P(f"Level: {inv_risk.get('level', 'Unknown')}", small))
                story.append(P(f"Reason: {inv_risk.get('reason', 'No risk assessment')}", evidence_style))
                story.append(Spacer(1, 6))

            # Scene Classification
            scene = inv.get("scene_classification", {}) or {}
            if scene:
                story.append(Paragraph("Scene Classification", h3))
                story.append(P(
                    f"Classification: {scene.get('classification', 'Unknown')}  |  "
                    f"Classification Confidence: {scene.get('confidence', 0)}%  |  "
                    f"Source: {scene.get('source', 'Unknown')}", small))
                story.append(Spacer(1, 6))

            # Dynamic Profile
            # BUG FIX (consistency with Crime DNA gating above): this dict's
            # team_size/technical_skill/planning_level/risk_behavior values
            # come from investigator_integration.py's keyword-based
            # defaults (e.g. "Solo"/"Medium"/"Semi-planned" when no keyword
            # matched) — NOT from actual independent evidence. Crime DNA
            # already refuses to show a confident profile below 25%
            # Evidence-Type Coverage; showing this equally-unsupported
            # profile as if it were established data right next to that
            # same-page disclaimer was an inconsistency an investigator
            # could easily miss. Use the identical threshold/variable so
            # both sections agree on when there's "enough evidence" or not.
            dyn = inv.get("dynamic_profile", {}) or {}
            _dyn_evidence_pct = (d.get("intel_summary", {}) or {}).get("completeness_pct", 0)
            if dyn and _dyn_evidence_pct < 25:
                story.append(Paragraph("Dynamic Profile", h3))
                story.append(P(
                    f"⚠ INSUFFICIENT EVIDENCE FOR BEHAVIORAL PROFILING — this case's Evidence-Type "
                    f"Coverage is only {_dyn_evidence_pct}%, the same threshold below which Crime DNA "
                    f"scoring above is also withheld. Team size, technical skill, planning level, and "
                    f"risk behavior are NOT displayed here as established findings; treat this profile "
                    f"as NOT ASSESSED until more evidence is submitted.",
                    alert_red
                ))
                story.append(Spacer(1, 6))
            elif dyn:
                story.append(Paragraph("Dynamic Profile", h3))
                for k, v in dyn.items():
                    label = str(k).replace("_", " ").strip().title()
                    story.append(P(f"• {label}: {_humanize(v)}", evidence_style))
                story.append(Spacer(1, 6))

            # OCR Status
            inv_ocr = inv.get("ocr", {}) or {}
            if inv_ocr:
                story.append(Paragraph("OCR Status (Investigator Engine)", h3))
                story.append(P(
                    f"Status: {inv_ocr.get('status', 'Unknown')}  |  "
                    f"Reason: {inv_ocr.get('reason', 'No OCR data')}", small))
                # Cross-check against this report's own OCR-based Document
                # Evidence section (above) — these are two independently
                # computed OCR readings (Investigator Engine vs. this
                # pipeline's TrOCR pass) and have previously been observed
                # to disagree (e.g. one saying "FAILED", the other
                # "ANALYZED", for the same upload). Surface that explicitly
                # instead of letting the two silently contradict each other
                # on different pages of the same report.
                _our_doc_ev = d.get("doc_evidence", {}) or {}
                _our_ok = _our_doc_ev.get("status") == "Evidence analyzed"
                _inv_ok = str(inv_ocr.get("status", "")).upper() in ("ANALYZED", "SUCCESS", "OK", "READ")
                _inv_failed = "FAIL" in str(inv_ocr.get("status", "")).upper()
                if (_our_ok and _inv_failed) or (not _our_ok and _inv_ok):
                    story.append(P(
                        "⚠ OCR STATUS CONFLICT: this pipeline's own OCR pass and the "
                        "Investigator Engine's OCR pass disagree on whether the uploaded "
                        "document was readable. Treat any name/identity match derived from "
                        "this document as UNVERIFIED until manually reviewed.",
                        alert_red
                    ))
                story.append(Spacer(1, 6))

        # ── ADVANCED INTELLIGENCE REPORT (Knowledge Graph, Crime DNA,
        #    Tier-1 Intelligence, Investigation Planner, Court Readiness,
        #    Criminal Network, Confidence Fusion, Explainable AI) ──────────
        adv = inv.get("advanced", {}) or {}
        if adv and "error" not in adv:
            story.append(PageBreak())
            story.append(Paragraph("ADVANCED INTELLIGENCE REPORT", h2))
            story.append(P(
                "Generated by the 13-step advanced reasoning pipeline (Knowledge Graph, "
                "Crime DNA, Hypothesis Engine, Confidence Fusion, Investigation Planner, "
                "Criminal Network, Tier-1 Intelligence, Court Readiness). AI-suggested — "
                "requires human verification before any official use.", alert_amber))
            story.append(Spacer(1, 8))

            # Executive Dashboard
            ed = adv.get("executive_dashboard", {}) or {}
            if ed:
                story.append(Paragraph("Executive Dashboard", h3))
                story.append(P(
                    f"Case Status: {ed.get('case_status', 'Unknown')}  |  "
                    f"Primary Theory: {ed.get('primary_theory', 'Unknown')} "
                    f"({ed.get('primary_confidence', 0)}%)", small))
                # Same authoritative evidence-completeness figure used above
                # (see note in the Investigator Intelligence section) — one
                # number for this concept everywhere in the report.
                _authoritative_completeness = (d.get("intel_summary", {}) or {}).get("completeness_pct")
                _ed_completeness = (_authoritative_completeness if _authoritative_completeness is not None
                                     else ed.get('evidence_completeness', 0))
                story.append(P(
                    f"Evidence Completeness: {_ed_completeness}%  |  "
                    f"Court Readiness: {ed.get('court_readiness', 0)}%  |  "
                    + ("Fused Confidence: withheld (evidence coverage below 25%)"
                     if float((d.get("intel_summary", {}) or {}).get("completeness_pct", 0) or 0) < 25
                     else f"Fused Confidence: {ed.get('fused_confidence', 0)}%"), small))
                if ed.get("critical_missing"):
                    story.append(P("Not Yet Submitted (High Priority): " + ", ".join(ed["critical_missing"]), alert_amber))

                # Overall Investigation Progress — one glance at how far
                # along this case is, averaged across the three headline
                # completeness/readiness/confidence figures above.
                _progress_vals = [v for v in (
                    _ed_completeness, ed.get('court_readiness'), ed.get('fused_confidence')
                ) if isinstance(v, (int, float))]
                if _progress_vals:
                    _progress = round(sum(_progress_vals) / len(_progress_vals), 1)
                    story.append(Spacer(1, 6))
                    story.append(P("Investigation Progress", small))
                    _progress_color = "#16a34a" if _progress >= 66 else ("#f59e0b" if _progress >= 33 else "#ef4444")
                    story.append(_pdf_progress_bar(_progress, total_width=300, height=11, fill_color=_progress_color))
                    story.append(P(f"{_progress}%", evidence_style))
                story.append(Spacer(1, 8))

            # Evidence Strength Matrix — per-evidence-type confidence, at a
            # glance, for a judge/senior officer.
            _fusion_detail = adv.get("confidence_fusion_detail", {}) or {}
            _contributions = _fusion_detail.get("contributions", {}) or {}
            if _contributions:
                story.append(Paragraph("Evidence Strength Matrix", h3))
                for ev_type, info in _contributions.items():
                    conf = info.get("confidence", 0) if isinstance(info, dict) else info
                    try:
                        conf = float(conf)
                    except (TypeError, ValueError):
                        conf = 0
                    bar_color = "#16a34a" if conf >= 66 else ("#f59e0b" if conf >= 33 else "#ef4444")
                    row = Table([[
                        P(str(ev_type).replace("_", " ").title(), small),
                        _pdf_progress_bar(conf, total_width=180, height=9, fill_color=bar_color),
                        P(f"{conf:.0f}%", evidence_style),
                    ]], colWidths=[90, 190, 40])
                    row.setStyle(TableStyle([
                        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                        ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                    ]))
                    story.append(row)
                story.append(Spacer(1, 8))

            # Knowledge Graph — actual node-link diagram, not a text chain.
            # A bullet list like "Face -> Person, Vehicle -> Location" is
            # data representation; an investigator reads a real diagram in
            # 2 seconds instead of parsing sentences.
            kgv = adv.get("knowledge_graph", {}) or {}
            kg_raw = adv.get("knowledge_graph_raw", {}) or {}
            if kgv:
                story.append(Paragraph("Knowledge Graph", h3))
                story.append(P(
                    f"Nodes: {kgv.get('total_nodes', 0)}  |  Edges: {kgv.get('total_edges', 0)}", small))
                _kg_nodes, _kg_edges = _kg_nodes_edges(kg_raw)
                _kg_drawing = _pdf_network_diagram(_kg_nodes, _kg_edges) if _kg_nodes else None
                if _kg_drawing:
                    story.append(_kg_drawing)
                elif kgv.get("graph_chain"):
                    story.append(P(" → ".join(str(x) for x in kgv["graph_chain"]), evidence_style))
                if kgv.get("communities"):
                    story.append(P("Communities: " + ", ".join(kgv["communities"]), evidence_style))
                if kgv.get("patterns"):
                    for p in kgv["patterns"]:
                        story.append(P(f"• {p}", evidence_style))
                story.append(Spacer(1, 8))

            # Evidence Relationship Graph — same underlying graph as
            # Knowledge Graph above, so rather than draw a duplicate
            # diagram from identical data, this stays as the enriched
            # relationship summary (counts + strengths).
            rg = adv.get("relationship_graph", {}) or {}
            if rg:
                story.append(Paragraph("Evidence Relationship Graph", h3))
                story.append(P(
                    f"Total Relationships: {rg.get('total_relationships', 0)}  "
                    f"(see network diagram in Knowledge Graph above)", small))
                kc = rg.get("key_connections", {}) or {}
                if kc:
                    story.append(P(_humanize(kc), evidence_style))
                _prov_tag_color = {
                    "OBSERVED": "#22c55e", "EXTRACTED": "#38bdf8",
                    "INFERRED": "#f59e0b", "UNVERIFIED": "#f87171",
                }
                for rel in (rg.get("relationships") or [])[:8]:
                    _prov = rel.get("confidence_type", "INFERRED")
                    _refs = rel.get("evidence_refs") or []
                    # evidence_refs entries look like "E01 (ArcFace, node
                    # weight 0.90)" — pull just the source names for a
                    # compact per-relationship source line.
                    _sources = [r.split("(", 1)[1].split(",")[0].strip() for r in _refs
                                if "(" in r and not r.startswith("Basis:")]
                    _source_str = ", ".join(_sources) if _sources else "Unknown"
                    story.append(P(
                        f"• {rel.get('from','?')} — {rel.get('relationship','connected')} → "
                        f"{rel.get('to','?')}  "
                        f"<font color='{_prov_tag_color.get(_prov, '#94a3b8')}'><b>[{_prov}]</b></font>  "
                        f"(strength: {rel.get('strength',0)}, confidence: {rel.get('confidence', 0)})",
                        evidence_style))
                    story.append(P(f"   Source: {_source_str}", small))
                    if _prov == "UNVERIFIED":
                        story.append(P(f"   ⚠ {rel.get('derivation_method', '')}", small))
                story.append(Spacer(1, 8))

            # Crime DNA — radar/spider chart (7 dimensions at once is the
            # industry-standard way to read a multi-dimensional profile;
            # much faster than seven separate numbers).
            cdna = adv.get("crime_dna", {}) or {}
            # BUG FIX (P0 — reviewer feedback): Crime DNA used to render a
            # confident 7-dimension numeric profile (radar chart included)
            # even when this case's own Evidence-Type Coverage was as low
            # as 12% — a level of behavioral-scoring granularity the
            # actual evidence on file cannot support. A radar chart in
            # particular *looks* authoritative regardless of the numbers
            # behind it. Gate the confident visualization on evidence
            # coverage; below the threshold, say so plainly instead of
            # rendering numbers that outrun the evidence.
            _cdna_evidence_pct = (d.get("intel_summary", {}) or {}).get("completeness_pct", 0)
            _cdna_has_signal = cdna and any(v not in (0, "0") for v in cdna.values() if isinstance(v, (int, float)))
            if cdna and _cdna_evidence_pct < 25:
                story.append(Paragraph("Crime DNA Dashboard", h3))
                story.append(P(
                    f"⚠ INSUFFICIENT EVIDENCE FOR CRIME DNA SCORING — this case's Evidence-Type Coverage is "
                    f"only {_cdna_evidence_pct}%, too low to support a confident 7-dimension behavioral "
                    f"profile. The numeric scores this module would normally show are NOT displayed here; "
                    f"treat Crime DNA as NOT ASSESSED until more evidence is submitted.",
                    alert_red
                ))
                story.append(Spacer(1, 8))
            elif cdna and not _cdna_has_signal:
                story.append(Paragraph("Crime DNA Dashboard", h3))
                story.append(P("NOT ASSESSED — no crime-pattern dimensions established for this case.", small))
                story.append(Spacer(1, 8))
            elif cdna:
                story.append(Paragraph("Crime DNA Dashboard", h3))
                _radar = _pdf_crime_dna_radar(cdna)
                if _radar:
                    story.append(_radar)
                else:
                    story.append(P(
                        f"Planning: {cdna.get('planning',0)}/10  |  Technical: {cdna.get('technical',0)}/10  |  "
                        f"Violence: {cdna.get('violence',0)}/10  |  Escape: {cdna.get('escape',0)}/10", small))
                    story.append(P(
                        f"Op. Security: {cdna.get('op_security',0)}/10  |  Execution: {cdna.get('execution',0)}/10  |  "
                        f"Team: {cdna.get('team',0)}/10", small))
                story.append(P(
                    f"Signature: {cdna.get('signature','Unknown')}  |  DNA String: {cdna.get('dna_string','')}", small))
                if cdna.get("patterns"):
                    story.append(P("Patterns: " + ", ".join(cdna["patterns"]), evidence_style))
                story.append(Spacer(1, 8))

            # Hypothesis Ranking Table
            hr = adv.get("hypothesis_ranking", {}) or {}
            if hr.get("top_hypotheses"):
                story.append(Paragraph("Hypothesis Ranking", h3))
                story.append(P(
                    "Every confidence % below is an AI-SUGGESTED HYPOTHESIS, not an established "
                    "finding or conclusion — including when Crime Classification elsewhere in this "
                    "report shows no specific pattern established. These are investigative leads for "
                    "the investigator/journalist to verify, not confirmed facts.",
                    small))
                hyp_rows = [[P("Rank", th), P("Theory", th), P("Confidence", th), P("Status", th)]]
                for h in hr["top_hypotheses"]:
                    hyp_rows.append([
                        P(str(h.get("rank", ""))), P(h.get("name", "Unknown")),
                        P(f"{h.get('confidence', 0)}%"),
                        P(_hypothesis_display_status(h.get("status", ""), h.get("confidence", 0))),
                    ])
                hyp_tbl = Table(hyp_rows, colWidths=[40, 260, 80, 100])
                hyp_tbl.setStyle(TableStyle([
                    ("BACKGROUND", (0, 0), (-1, 0), DARK),
                    ("FONTSIZE", (0, 0), (-1, -1), 9),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LGRAY]),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                    ("GRID", (0, 0), (-1, -1), 0.4, BORDER),
                ]))
                story.append(hyp_tbl)
                # NEW: hypothesis-confidence bar chart, added per user
                # request for more visual coverage in the report beyond
                # the Crime DNA radar and network diagram — makes relative
                # hypothesis strength immediately visible at a glance.
                _hyp_chart = _pdf_hypothesis_confidence_chart(hr["top_hypotheses"])
                if _hyp_chart:
                    story.append(Spacer(1, 6))
                    story.append(_hyp_chart)
                for h in hr["top_hypotheses"]:
                    if h.get("evidence_for"):
                        story.append(P(
                            f"  {h.get('name','')} — supported by: " + ", ".join(h["evidence_for"]),
                            evidence_style))
                if hr.get("rejected_hypotheses"):
                    story.append(P("Rejected: " + "; ".join(
                        f"{h.get('name','')} ({h.get('confidence',0)}%)" for h in hr["rejected_hypotheses"]
                    ), small))

                # Appendix — the engine generates far more theories than the
                # top-5 headline table can show, and an investigator
                # sometimes needs to work off theory #17, not #1.
                _all_hyps = adv.get("all_hypotheses_raw", []) or []
                if len(_all_hyps) > 5:
                    story.append(Spacer(1, 6))
                    story.append(P(
                        f"Appendix — {len(_all_hyps) - 5} additional theories generated "
                        f"(full list, lowest confidence first is omitted below 30%):", small))
                    appendix_rows = [[P("#", th), P("Theory", th), P("Category", th), P("Confidence", th)]]
                    for i, h in enumerate(_all_hyps[5:], start=6):
                        if _safe_num(h.get("confidence", 0)) < 30:
                            continue
                        appendix_rows.append([
                            P(str(i)), P(h.get("name", "Unknown")),
                            P(h.get("category", "")), P(f"{h.get('confidence', 0)}%"),
                        ])
                    if len(appendix_rows) > 1:
                        appendix_tbl = Table(appendix_rows, colWidths=[30, 220, 130, 100])
                        appendix_tbl.setStyle(TableStyle([
                            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#475569")),
                            ("FONTSIZE", (0, 0), (-1, -1), 8),
                            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LGRAY]),
                            ("TOPPADDING", (0, 0), (-1, -1), 3),
                            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                            ("GRID", (0, 0), (-1, -1), 0.4, BORDER),
                        ]))
                        story.append(appendix_tbl)
                story.append(Spacer(1, 8))

            # HBEI — Human Behavior & Error Intelligence (external service,
            # port 8000). "AI finds errors, humans find truth" — these are
            # investigative leads, never guilt claims.
            hbei_res = d.get("hbei_api_result") or {}
            if hbei_res and not hbei_res.get("error"):
                story.append(Paragraph("Human Behavior & Error Intelligence (HBEI)", h3))
                story.append(P(
                    "Behavioral anomaly detection across available case narrative/evidence "
                    "— investigative leads, not evidence of guilt.",
                    small))
                story.append(P(
                    f"Total Observations: {hbei_res.get('total_observations', 0)}  |  "
                    f"Signals: {hbei_res.get('signals', 0)}  |  "
                    f"Priority: {hbei_res.get('priority', 'N/A')}  |  "
                    f"Weakest Link: {hbei_res.get('weakest_link', 'N/A')}",
                    evidence_style))
                # BUG FIX (2026-08-20 — Medium): "Signals: 0" next to
                # "Priority: HIGH" reads as a contradiction — as if a HIGH
                # priority were derived from zero detected behavioral
                # signals. In practice HBEI's Priority reflects overall
                # case risk context from the upstream service, not a count
                # of THIS module's own detected signals — so make that
                # distinction explicit instead of leaving it to guesswork.
                if hbei_res.get('signals', 0) in (0, None) and str(hbei_res.get('priority', '')).upper() in ("HIGH", "CRITICAL"):
                    story.append(P(
                        f"<i>Note: no behavioral anomaly signals were detected by this module "
                        f"(Signals: 0) — the {hbei_res.get('priority','HIGH')} priority reflects "
                        f"overall case risk context, not a HBEI-specific behavioral finding. "
                        f"Treat as \"HBEI: not elevated / Overall case priority: "
                        f"{hbei_res.get('priority','HIGH')}\".</i>",
                        small))
                if hbei_res.get("investigation_direction"):
                    story.append(P(f"<b>Investigation Direction:</b> {hbei_res['investigation_direction']}", evidence_style))
                if hbei_res.get("evidence_needed"):
                    story.append(P("<b>Evidence Needed:</b>", evidence_style))
                    for ev in hbei_res["evidence_needed"]:
                        story.append(P(f"   • {ev}", small))
                if hbei_res.get("counter_hypotheses"):
                    story.append(P("<b>Counter-Hypotheses:</b>", evidence_style))
                    for ch in hbei_res["counter_hypotheses"]:
                        story.append(P(f"   • {ch}", small))
                if hbei_res.get("provenance_links") or (hbei_res.get("full_result", {}) or {}).get("investigation_direction", {}).get("provenance_links"):
                    _prov_links = hbei_res.get("provenance_links") or (hbei_res.get("full_result", {}) or {}).get("investigation_direction", {}).get("provenance_links", [])
                    story.append(P("<b>Provenance Chain:</b>", evidence_style))
                    for p in _prov_links:
                        story.append(P(
                            f"   • {p.get('source_evidence_id','?')} → {p.get('source_type','?')} "
                            f"| {p.get('verification_status','?')} | by: {p.get('created_by','?')}",
                            small))
                story.append(P(
                    "⚠ HBEI outputs are investigative leads, not guilt determinations. "
                    "Human verification required.",
                    small))
                story.append(Spacer(1, 8))
            elif hbei_res.get("error"):
                story.append(Paragraph("Human Behavior & Error Intelligence (HBEI)", h3))
                story.append(P(f"HBEI service unavailable: {hbei_res['error']}", small))
                story.append(Spacer(1, 8))

            # Investigation Guidance Engine — knowledge-driven (rules +
            # knowledge base, not ML) ranked "next investigation angle"
            # directions derived from the hypotheses above, each with a
            # trigger, WHY, search targets, cross-match plan, expected
            # outcome, P1/P2/P3 priority (rank-relative, not everyone
            # "Critical"), and if-confirmed/if-denied confidence impact.
            guidance = d.get("guidance") or {}
            g_dirs = guidance.get("recommended_directions", []) if isinstance(guidance, dict) else []
            if g_dirs:
                story.append(Paragraph(
                    f"Investigation Guidance — Recommended Directions ({len(g_dirs)})", h3))
                story.append(P(
                    "Knowledge-driven expert system output (rules + knowledge base per hypothesis "
                    "type) — case-specific investigation angles, not a generic evidence checklist. "
                    "AI-suggested priority order, not a substitute for investigator judgment.",
                    small))
                _g_tier_colors = {
                    "P1": colors.HexColor("#dc2626"),
                    "P2": colors.HexColor("#ea580c"),
                    "P3": colors.HexColor("#2563eb"),
                }
                g_rows = [[P("#", th), P("Direction", th), P("Tier", th), P("Hypothesis", th),
                           P("Likelihood", th), P("Cost", th), P("Time", th), P("Gain", th)]]
                for gdir in g_dirs:
                    g_rows.append([
                        P(str(gdir.get("rank", ""))),
                        P(gdir.get("title", "")),
                        P(gdir.get("priority_tier", "")),
                        P(gdir.get("hypothesis", "")),
                        P(f"{gdir.get('likelihood', 0)}%"),
                        P(gdir.get("cost", "")),
                        P(gdir.get("time_estimate", "")),
                        P(f"+{gdir.get('expected_evidence_gain', 0)}%"),
                    ])
                g_tbl = Table(g_rows, colWidths=[16, 130, 30, 65, 45, 45, 55, 40])
                g_tbl.setStyle(TableStyle([
                    ("BACKGROUND", (0, 0), (-1, 0), DARK),
                    ("FONTSIZE", (0, 0), (-1, -1), 8),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LGRAY]),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                    ("GRID", (0, 0), (-1, -1), 0.4, BORDER),
                ]))
                story.append(g_tbl)
                story.append(Spacer(1, 4))
                for gdir in g_dirs:
                    tier = gdir.get("priority_tier", "P3")
                    story.append(P(
                        f"<b>#{gdir.get('rank','')} {gdir.get('title','')}</b> "
                        f"<font color='{_g_tier_colors.get(tier, colors.HexColor('#6b7280')).hexval()}'>"
                        f"[{tier}]</font> — hypothesis: {gdir.get('hypothesis','')}", evidence_style))
                    if gdir.get("trigger"):
                        story.append(P(f"TRIGGER: {gdir['trigger']}", small))
                    story.append(P(f"WHY: {gdir.get('why','')}", small))
                    if gdir.get("description"):
                        story.append(P(gdir["description"], evidence_style))
                    if gdir.get("search_targets"):
                        story.append(P("Search: " + ", ".join(gdir["search_targets"]), small))
                    if gdir.get("cross_match"):
                        story.append(P("Cross-match: " + ", ".join(gdir["cross_match"]), small))
                    if gdir.get("expected_outcome"):
                        story.append(P(f"Expected outcome: {gdir['expected_outcome']}", small))
                    if gdir.get("agencies_to_involve"):
                        story.append(P("Agencies: " + ", ".join(gdir["agencies_to_involve"]), small))
                    if gdir.get("expected_documents"):
                        story.append(P("Documents: " + ", ".join(gdir["expected_documents"]), small))
                    if gdir.get("failure_conditions"):
                        story.append(P("Failure risk: " + ", ".join(gdir["failure_conditions"]), small))
                    ci_c = gdir.get("confidence_impact_confirmed", 0)
                    ci_d = gdir.get("confidence_impact_denied", 0)
                    story.append(P(
                        f"If confirmed: {gdir.get('hypothesis','')} {ci_c:+.0f} pts &nbsp;|&nbsp; "
                        f"If denied: {gdir.get('hypothesis','')} {ci_d:+.0f} pts", small))
                    story.append(Spacer(1, 4))
                story.append(Spacer(1, 6))

                # Counter-Hypothesis (If/Then) Analysis
                cf_rows_data = guidance.get("counterfactual_analysis", []) if isinstance(guidance, dict) else []
                if cf_rows_data:
                    story.append(Paragraph("Counter-Hypothesis Analysis (If / Then)", h3))
                    story.append(P(
                        "How each leading hypothesis's confidence would move depending on what its "
                        "top linked investigation direction finds.", small))
                    cf_rows = [[P("Hypothesis", th), P("Current", th), P("If Confirmed", th),
                                P("If Denied", th), P("Driven By", th)]]
                    for c in cf_rows_data:
                        cf_rows.append([
                            P(c.get("hypothesis", "")),
                            P(f"{c.get('current_confidence', 0)}%"),
                            P(f"{c['if_confirmed']['confidence']}% ({c['if_confirmed']['delta']:+.0f})"),
                            P(f"{c['if_denied']['confidence']}% ({c['if_denied']['delta']:+.0f})"),
                            P(c.get("driving_direction", "")),
                        ])
                    cf_tbl = Table(cf_rows, colWidths=[85, 45, 85, 85, 126])
                    cf_tbl.setStyle(TableStyle([
                        ("BACKGROUND", (0, 0), (-1, 0), DARK),
                        ("FONTSIZE", (0, 0), (-1, -1), 8),
                        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LGRAY]),
                        ("TOPPADDING", (0, 0), (-1, -1), 4),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                        ("GRID", (0, 0), (-1, -1), 0.4, BORDER),
                    ]))
                    story.append(cf_tbl)
                    story.append(Spacer(1, 8))
            elif isinstance(guidance, dict) and guidance.get("error"):
                story.append(Paragraph("Investigation Guidance Engine", h3))
                story.append(P(f"Guidance Engine unavailable: {guidance['error']}", small))
                story.append(Spacer(1, 8))

            # Investigation Planner — actionable TODAY checklist, grouped
            # by urgency, instead of a flat priority table. A checkbox list
            # is what an investigator actually works from.
            ip = adv.get("investigation_planner", {}) or {}
            if ip.get("actions"):
                # Dedupe near-identical actions (e.g. "Collect Voice
                # Evidence" and "Collect Voice sample" are the same task
                # phrased two ways) — keep whichever variant has the
                # higher expected gain.
                _seen_action_keys = {}
                _action_filler = {"collect", "evidence", "sample", "samples", "logs",
                                   "log", "records", "record", "critical", "-", "the"}
                for a in ip["actions"]:
                    _words = str(a.get("action", "")).lower().replace("-", " ").split()
                    _core = tuple(sorted(w for w in _words if w not in _action_filler))
                    if not _core:
                        _core = (str(a.get("action", "")).lower(),)
                    if _core not in _seen_action_keys or \
                       a.get("gain", 0) > _seen_action_keys[_core].get("gain", 0):
                        _seen_action_keys[_core] = a
                _deduped_actions = list(_seen_action_keys.values())

                story.append(Paragraph(
                    f"Investigation Planner ({len(_deduped_actions)} actions, "
                    f"{sum(1 for a in _deduped_actions if str(a.get('priority','')).upper()=='HIGH')} high priority)",
                    h3))
                _by_priority = {"HIGH": [], "MEDIUM": [], "LOW": []}
                for a in _deduped_actions:
                    _by_priority.setdefault(str(a.get("priority", "MEDIUM")).upper(), []).append(a)
                _section_titles = {"HIGH": "TODAY — High Priority", "MEDIUM": "THIS WEEK — Medium Priority",
                                    "LOW": "WHEN AVAILABLE — Low Priority"}
                for _pkey in ("HIGH", "MEDIUM", "LOW"):
                    _actions = _by_priority.get(_pkey, [])
                    if not _actions:
                        continue
                    story.append(P(_section_titles[_pkey], small))
                    for a in _actions:
                        gain = a.get("gain", 0)
                        time_est = a.get("time", "")
                        story.append(P(
                            f"[ ] {a.get('action', '')}  "
                            f"<font color='#64748b' size=8>(+{gain}% gain, {time_est})</font>",
                            evidence_style))
                    story.append(Spacer(1, 4))
                story.append(Spacer(1, 4))

            # Criminal Network Graph — node-link diagram radiating from the
            # suspect, instead of two flat "Known / Inferred" bullet lists.
            cn = adv.get("criminal_network", {}) or {}
            if cn:
                story.append(Paragraph("Criminal Network Graph", h3))
                story.append(P(f"Status: {cn.get('status', 'Unknown')}  |  "
                                f"Total Nodes: {cn.get('total_nodes', 0)}", small))
                story.append(P(cn.get("message", ""), evidence_style))
                if cn.get("inferred_nodes"):
                    story.append(P("(* = inferred, not directly observed)", small))

                _cnn_nodes, _cnn_edges = _criminal_network_nodes_edges(cn)
                _cnn_drawing = _pdf_network_diagram(_cnn_nodes, _cnn_edges) if len(_cnn_nodes) >= 2 else None
                if _cnn_drawing:
                    story.append(_cnn_drawing)
                else:
                    for n in cn.get("current_nodes", []) or []:
                        story.append(P(f"• Known: {_humanize(n)}", evidence_style))
                    for n in cn.get("inferred_nodes", []) or []:
                        story.append(P(f"• Inferred: {_humanize(n)}", evidence_style))
                story.append(Spacer(1, 8))

            # Tier-1 Criminal Intelligence
            t1 = adv.get("tier1_intelligence", {}) or {}
            if t1:
                story.append(Paragraph("Tier-1 Criminal Intelligence", h3))
                story.append(P(
                    f"DNA Signature: {t1.get('dna_signature', 'Unknown')}  |  "
                    f"Intelligence Score: {t1.get('intelligence_score', 0)}  |  "
                    f"MO Evolution: {t1.get('mo_evolution', 0)}", small))
                _raw_similar = t1.get("similar_cases", []) or []
                # Collapse repeated "no real case, same placeholder id"
                # entries into one — three identical "UNKNOWN — 70%" blocks
                # in a row reads as a rendering bug, not three findings.
                _seen_placeholder = False
                _similar_cases = []
                for s in _raw_similar:
                    _cid = str(s.get('case_id', '') or '').strip().upper()
                    if _cid in ("", "?", "UNKNOWN", "NONE", "N/A"):
                        if _seen_placeholder:
                            continue
                        _seen_placeholder = True
                    _similar_cases.append(s)
                for s in _similar_cases:
                    # A perfect 100% match undermines trust in the whole
                    # comparison (real-world similar cases are similar, not
                    # identical) — cap the displayed figure just under 100
                    # as a safety net even though the self-comparison bug
                    # that caused this is now fixed at the source.
                    _sim = s.get('similarity', 0)
                    try:
                        _sim = min(float(_sim), 99.0)
                    except (TypeError, ValueError):
                        _sim = 0
                    _case_id = str(s.get('case_id', '') or '').strip()
                    _no_real_case = _case_id.upper() in ("", "?", "UNKNOWN", "NONE", "N/A")
                    if _no_real_case:
                        # Don't present a placeholder case_id as if a real
                        # matching case exists in the database — this is a
                        # feature-vector similarity score with no verified
                        # case behind it, and should read that way.
                        story.append(P("Verified Similar Case: NONE FOUND", small))
                        story.append(P(
                            f"Abstract Pattern Similarity: {_sim:.0f}% — feature-vector "
                            f"similarity only, not a verified case-to-case match.",
                            alert_amber))
                    else:
                        story.append(P(
                            f"Similar case: {_case_id}  —  Overall Similarity {_sim:.0f}%",
                            small))
                    if s.get("common_factors"):
                        story.append(P("Basis / Matched Features:" if _no_real_case else "Matched Features:", evidence_style))
                        for factor in s["common_factors"]:
                            story.append(P(f"&#10003; {factor}", evidence_style))
                    story.append(Spacer(1, 3))
                for p in t1.get("predictions", []) or []:
                    story.append(P(
                        f"• Predicted: {p.get('crime_type','?')} ({p.get('probability',0)}%)", evidence_style))
                story.append(Spacer(1, 8))

            # Court Readiness Dashboard
            cr = adv.get("court_readiness", {}) or {}
            if cr:
                story.append(Paragraph("Court Readiness Dashboard", h3))
                story.append(P(f"Score: {cr.get('readiness_score', cr.get('score', 0))}%  |  Status: {cr.get('status', 'NOT READY')}", small))
                _custody_status = cr.get("custody_status")
                for key, met in (cr.get("checklist", {}) or {}).items():
                    if key == "Chain of Custody" and _custody_status:
                        # Honest 3-state display instead of a flat ✗ — a
                        # logged intake timestamp exists even though the
                        # full legal transfer history doesn't yet.
                        mark = {"FULL": "✓", "PARTIAL": "◐", "NONE": "✗"}.get(_custody_status, "✗")
                        style = evidence_style if _custody_status == "FULL" else alert_amber
                        story.append(P(f"{mark} Chain of Custody — {_custody_status}", style))
                        story.append(P(cr.get("custody_note", ""), small))
                        continue
                    mark = "✓" if met else "✗"
                    style = evidence_style if met else alert_amber
                    story.append(P(f"{mark} {key}", style))
                if cr.get("missing_collectible_now") or cr.get("not_yet_collectible_by_system"):
                    if cr.get("missing_collectible_now"):
                        story.append(P(
                            "Not Submitted for This Case: " + ", ".join(cr["missing_collectible_now"]),
                            alert_amber))
                    if cr.get("not_yet_collectible_by_system"):
                        story.append(P(
                            "No Collection Pathway in System Yet: " + ", ".join(cr["not_yet_collectible_by_system"]),
                            small))
                elif cr.get("missing"):
                    story.append(P("Not Submitted for This Case: " + ", ".join(cr["missing"]), alert_amber))
                story.append(Spacer(1, 8))

            # Explainable AI
            xai = adv.get("explainable_ai", {}) or {}
            if xai and xai.get("hypothesis"):
                story.append(Paragraph("Explainable AI — Why This Conclusion?", h3))
                story.append(P(
                    f"Hypothesis: {xai.get('hypothesis','')} ({xai.get('confidence',0)}%)", small))
                if xai.get("why_believe"):
                    story.append(P("Why believe: " + "; ".join(xai["why_believe"]), evidence_style))
                if xai.get("why_doubt"):
                    story.append(P("Why doubt: " + "; ".join(xai["why_doubt"]), evidence_style))
                story.append(Spacer(1, 8))


        # ── Source display name mapping ─────────────────────────────────
        # Backend identifiers (test_cctv_manual, etc.) are internal — the
        # investor-facing PDF must show human-readable names, never
        # technical codes. The underlying source_code is unchanged.
        _SOURCE_DISPLAY_MAP = {
            "test_cctv_manual": "CCTV Live Feed",
            "test_gps_manual": "GPS Live Feed",
            "test_anpr_manual": "ANPR Live Feed",
            "test_mobile_manual": "Mobile Location Feed",
            "test_interpol_manual": "Interpol Feed",
            "cctv_live": "CCTV Live Feed",
            "gps_live": "GPS Live Feed",
            "uk_police_crime": "UK Police Crime Archive",
        }

        def _display_source_name(code, fallback=""):
            if not code:
                return fallback or "Unknown Source"
            code = str(code)
            if code in _SOURCE_DISPLAY_MAP:
                return _SOURCE_DISPLAY_MAP[code]
            # Generic pattern: test_xxx_manual → "XXX Live Feed"
            if code.startswith("test_") and code.endswith("_manual"):
                middle = code[5:-7]
                return f"{middle.upper()} Live Feed"
            if code.endswith("_live"):
                return f"{code[:-5].upper()} Live Feed"
            return fallback or code.replace("_", " ").title()

                # ═══════════════════════════════════════════════════════════════════
        # SECTION 2: LIVE TRACKING DATA
        # Runs unconditionally — Silently skipped on any failure.
        # ═══════════════════════════════════════════════════════════════════
        if TRACKING_AVAILABLE and d.get("case_id"):
            try:
                _tracking_case_id = d.get("case_id")
                _live = get_live_map_data(case_id=_tracking_case_id)
                _alerts_data = get_recent_alerts(case_id=_tracking_case_id,
                                                   hours=168, limit=50)
                if not _alerts_data.get("success") or _alerts_data.get("count", 0) < 1:
                    _alerts_data = get_recent_alerts(case_id=_tracking_case_id, hours=87600, limit=50)
                _sources = list_sources()

                _live_entities = _live.get("entities", []) if _live.get("success") else []
                _live_stats = _live.get("stats", {}) if _live.get("success") else {}
                _alerts = _alerts_data.get("alerts", []) if _alerts_data.get("success") else []

                _has_tracking = bool(_live_entities or _alerts or _sources)

                if _has_tracking:
                    story.append(PageBreak())
                    story.append(Paragraph("SECTION 2 — LIVE TRACKING", h2))
                    story.append(P(
                        "Live location tracking, alerts, and data sources for this case. "
                        "AI-suggested investigative leads — verify independently before use.",
                        alert_amber))
                    story.append(Spacer(1, 10))

                    # 2.1 Summary
                    story.append(Paragraph("2.1 Tracking Summary", h3))
                    _summary_rows = [
                        [P("Metric", th), P("Value", th)],
                        [P("Total Tracked Entities"), P(str(_live_stats.get("total", len(_live_entities))))],
                        [P("Critical Risk"), P(str(_live_stats.get("critical", 0)))],
                        [P("High Risk"), P(str(_live_stats.get("high", 0)))],
                        [P("Medium Risk"), P(str(_live_stats.get("medium", 0)))],
                        [P("Low Risk"), P(str(_live_stats.get("low", 0)))],
                        [P("Active Data Sources"), P(str(len(_sources)))],
                        [P("Recent Alerts (7 days)"), P(str(len(_alerts)))],
                    ]
                    _summary_tbl = Table(_summary_rows, colWidths=[200, 200])
                    _summary_tbl.setStyle(TableStyle([
                        ("BACKGROUND", (0, 0), (-1, 0), DARK),
                        ("FONTSIZE", (0, 0), (-1, -1), 9),
                        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LGRAY]),
                        ("TOPPADDING", (0, 0), (-1, -1), 5),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                        ("GRID", (0, 0), (-1, -1), 0.4, BORDER),
                    ]))
                    story.append(_summary_tbl)
                    story.append(Spacer(1, 10))

                    # 2.2 Live Locations
                    if _live_entities:
                        story.append(Paragraph(
                            f"2.2 Live Locations ({len(_live_entities)} entities)", h3))
                        _ent_rows = [[
                            P("Entity", th), P("Type", th), P("Risk", th),
                            P("Coordinates", th), P("Source", th), P("Last Update", th),
                        ]]
                        for e in _live_entities[:30]:
                            _ent_rows.append([
                                P(str(e.get("entity_name", "Unknown"))[:40]),
                                P(str(e.get("entity_type", "?"))[:10]),
                                severity_cell(e.get("risk_level", "LOW")),
                                P(f"{e.get('latitude', 0):.4f}, {e.get('longitude', 0):.4f}"),
                                P(str(e.get("source", "?"))[:20]),
                                P(str(e.get("updated_at", "?"))[:19]),
                            ])
                        _ent_tbl = Table(_ent_rows, colWidths=[110, 45, 45, 90, 60, 90])
                        _ent_tbl.setStyle(TableStyle([
                            ("BACKGROUND", (0, 0), (-1, 0), DARK),
                            ("FONTSIZE", (0, 0), (-1, -1), 8),
                            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LGRAY]),
                            ("TOPPADDING", (0, 0), (-1, -1), 4),
                            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                            ("GRID", (0, 0), (-1, -1), 0.4, BORDER),
                        ]))
                        story.append(_ent_tbl)
                        story.append(Spacer(1, 10))


                    # 2.2b Location Trail (movement history) — for each
                    # entity that has history, render a small trail table
                    # so the report shows WHERE the subject moved, not
                    # just their current position. Consecutive points
                    # with identical coordinates are collapsed (the
                    # scheduler polls the same location every minute and
                    # would otherwise flood the table with duplicate
                    # rows). Silent skip if an entity has <2 distinct
                    # points (no movement to show).
                    for _ent in _live_entities[:5]:
                        _ent_uid = _ent.get("entity_uid")
                        _ent_name = _ent.get("entity_name", "Unknown")
                        if not _ent_uid:
                            continue
                        _trail_data = get_entity_trail(_ent_uid, hours=24, limit=500, min_gap_minutes=15)
                        if not _trail_data.get("success") or _trail_data.get("count", 0) < 2:
                            _trail_data = get_entity_trail(_ent_uid, hours=720, limit=500, min_gap_minutes=15)
                        if not _trail_data.get("success") or _trail_data.get("count", 0) < 2:
                            _trail_data = get_entity_trail(_ent_uid, hours=87600, limit=500, min_gap_minutes=15)
                        _raw = _trail_data.get("trail", []) if _trail_data.get("success") else []

                        # Collapse consecutive duplicate coordinates
                        _distinct = []
                        _prev_coord = None
                        for _t in _raw:
                            _coord = (round(float(_t.get("latitude") or 0), 6),
                                      round(float(_t.get("longitude") or 0), 6))
                            if _coord != _prev_coord:
                                _distinct.append(_t)
                                _prev_coord = _coord

                        if len(_distinct) < 2:
                            continue  # need at least 2 distinct points for movement

                        story.append(Paragraph(
                            f"2.2b Location Trail — {_ent_name} ({len(_distinct)} distinct points)",
                            h3))

                        import math as _math

                        def _hav_km(_a, _b):
                            _R = 6371.0
                            _lat1 = _math.radians(float(_a["latitude"]))
                            _lon1 = _math.radians(float(_a["longitude"]))
                            _lat2 = _math.radians(float(_b["latitude"]))
                            _lon2 = _math.radians(float(_b["longitude"]))
                            _dlat = _lat2 - _lat1
                            _dlon = _lon2 - _lon1
                            _h = (_math.sin(_dlat / 2) ** 2 +
                                  _math.cos(_lat1) * _math.cos(_lat2) *
                                  _math.sin(_dlon / 2) ** 2)
                            return 2 * _R * _math.asin(_math.sqrt(_h))

                        _trail_rows = [[
                            P("Time", th), P("Coordinates", th), P("Source ID", th),
                            P("Speed", th), P("Hdg", th), P("Delta", th),
                        ]]

                        _total_dist_m = 0.0
                        for _i, _t in enumerate(_distinct):
                            _lat_v = float(_t.get("latitude") or 0)
                            _lng_v = float(_t.get("longitude") or 0)
                            if _i == 0:
                                _delta = "-"
                            else:
                                _prev = _distinct[_i - 1]
                                _d_km = _hav_km(_prev, _t)
                                _total_dist_m += _d_km * 1000
                                _delta = f"{_d_km*1000:.0f} m"
                            _trail_rows.append([
                                P(str(_t.get("recorded_at", "?"))[:19]),
                                P(f"{_lat_v:.4f}, {_lng_v:.4f}"),
                                P(str(_t.get("source_id") or _t.get("source") or "?")[:20]),
                                P(str(_t.get("speed_kmh") or "-")),
                                P(str(_t.get("heading_degrees") or "-")),
                                P(_delta),
                            ])

                        _trail_tbl = Table(_trail_rows, colWidths=[80, 95, 95, 45, 35, 60])
                        _trail_tbl.setStyle(TableStyle([
                            ("BACKGROUND", (0, 0), (-1, 0), DARK),
                            ("FONTSIZE", (0, 0), (-1, -1), 8),
                            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LGRAY]),
                            ("TOPPADDING", (0, 0), (-1, -1), 4),
                            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                            ("GRID", (0, 0), (-1, -1), 0.4, BORDER),
                        ]))
                        story.append(_trail_tbl)

                        # Movement summary
                        _first = _distinct[0]
                        _last = _distinct[-1]
                        _net_m = _hav_km(_first, _last) * 1000
                        _dlat_net = float(_last["latitude"]) - float(_first["latitude"])
                        _dlon_net = float(_last["longitude"]) - float(_first["longitude"])
                        if _dlat_net > 0 and _dlon_net > 0:    _dir = "NE"
                        elif _dlat_net > 0 and _dlon_net < 0:  _dir = "NW"
                        elif _dlat_net < 0 and _dlon_net > 0:  _dir = "SE"
                        elif _dlat_net < 0 and _dlon_net < 0:  _dir = "SW"
                        elif _dlat_net > 0:                    _dir = "N"
                        elif _dlat_net < 0:                    _dir = "S"
                        elif _dlon_net > 0:                    _dir = "E"
                        elif _dlon_net < 0:                    _dir = "W"
                        else:                                  _dir = "stationary"
                        story.append(Spacer(1, 4))
                        story.append(P(
                            f"Movement Summary: {len(_distinct)} distinct points, "
                            f"total path {_total_dist_m:.0f} m, "
                            f"net displacement {_net_m:.0f} m ({_dir}).",
                            small))
                        story.append(Spacer(1, 10))
                    # 2.3 Alerts
                    if _alerts:
                        story.append(Paragraph(
                            f"2.3 Recent Alerts ({len(_alerts)})", h3))
                        _alert_rows = [[
                            P("Severity", th), P("Type", th), P("Entity", th),
                            P("Title", th), P("Time", th),
                        ]]
                        for a in _alerts[:20]:
                            _alert_rows.append([
                                severity_cell(a.get("severity", "LOW")),
                                P(str(a.get("alert_type", "?"))[:15]),
                                P(str(a.get("entity_name") or a.get("entity_uid", "?"))[:30]),
                                P(str(a.get("title", ""))[:60]),
                                P(str(a.get("created_at", ""))[:19]),
                            ])
                        _alert_tbl = Table(_alert_rows, colWidths=[55, 60, 100, 160, 85])
                        _alert_tbl.setStyle(TableStyle([
                            ("BACKGROUND", (0, 0), (-1, 0), DARK),
                            ("FONTSIZE", (0, 0), (-1, -1), 8),
                            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LGRAY]),
                            ("TOPPADDING", (0, 0), (-1, -1), 4),
                            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                            ("GRID", (0, 0), (-1, -1), 0.4, BORDER),
                        ]))
                        story.append(_alert_tbl)
                        story.append(Spacer(1, 10))

                    # 2.4 Sources
                    if _sources:
                        story.append(Paragraph(
                            f"2.4 Active Data Sources ({len(_sources)})", h3))
                        story.append(P(
                            "Data Source Status: REALTIME — Live feeds currently connected "
                            "to the investigation platform. All entities in this section are "
                            "derived from real source feeds, not fallback analysis.",
                            small))
                        _src_rows = [[
                            P("Source Name", th), P("Type", th),
                            P("Frequency", th), P("Last Success", th), P("Status", th),
                        ]]
                        for s in _sources:
                            _status = "Active" if s.get("is_active") else "Inactive"
                            if s.get("error_count", 0) > 0:
                                _status += f" ({s['error_count']} err)"
                            _src_rows.append([
                                P(_display_source_name(s.get("source_code"), s.get("source_name", ""))[:30]),
                                P(str(s.get("source_type", ""))[:10]),
                                P(str(s.get("update_frequency", ""))[:10]),
                                P(str(s.get("last_success_at", "Never"))[:19]),
                                P(_status),
                            ])
                        _src_tbl = Table(_src_rows, colWidths=[130, 50, 55, 105, 90])
                        _src_tbl.setStyle(TableStyle([
                            ("BACKGROUND", (0, 0), (-1, 0), DARK),
                            ("FONTSIZE", (0, 0), (-1, -1), 8),
                            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LGRAY]),
                            ("TOPPADDING", (0, 0), (-1, -1), 4),
                            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                            ("GRID", (0, 0), (-1, -1), 0.4, BORDER),
                        ]))
                        story.append(_src_tbl)

            except Exception as _tracking_err:
                log.warning(f"Tracking section skipped: {_tracking_err}")


        story.append(Spacer(1, 14))
        story.append(HRFlowable(width="100%", color=BORDER, thickness=0.75))
        story.append(Spacer(1, 6))
        story.append(Paragraph(
            "<b>Disclaimer:</b> This report was generated by AI and may contain errors. Human review is recommended: "
            "all findings must be independently reviewed and verified by a qualified investigator/legal reviewer before any official, "
            "editorial, or legal use. "
            "<b>CONFIDENTIAL</b> — sensitive investigative material. "
            # BUG FIX (reviewer feedback — P3): this used to hard-code a US
            # federal law-enforcement citation (28 CFR § 16.41) and US
            # law-enforcement role titles ("Case Officer, Supervising
            # Agent") regardless of who is actually using the report or
            # which jurisdiction they're in (e.g. an investigative
            # journalist working a case in India). Citing a specific,
            # inapplicable foreign statute is itself misleading, so this
            # is now generic language instead of a fabricated legal basis
            # — confidentiality handling should follow whatever policy or
            # law actually applies to the report's user and jurisdiction.
            "Handle and distribute according to your organization's confidentiality policy and applicable "
            "law in your jurisdiction — this report does not itself establish a legal basis for restricted "
            "distribution.",
            small))

        # DOA 2026-11-05: structured contradiction check on the case narrative (loans, roles, addresses)
        _doa = []
        try:
            from journalist_research.evidence.fact_contradiction import extract_assertions, detect_fact_contradictions
            from journalist_research.evidence.role_contradiction import (
                extract_role_assertions, detect_role_contradictions)
            _narr = str(d.get("modus", "") or "")
            _sid = str(d.get("suspect_name", "subject") or "subject")
            from journalist_research.evidence.narrative_split import narrative_contradictions
            # each clause (subject's statement vs a record's content) is its own non-independent statement
            _fc, _as = narrative_contradictions(_narr, _sid)
            _doa.append(Spacer(1, 10))
            _doa.append(Paragraph("Structured Contradiction Check (DOA)", h3))
            if _fc:
                _rows = [[P("Type", th), P("Severity", th), P("What conflicts", th)]]
                for _c in _fc[:8]:
                    _rows.append([P(_c.doa_class), severity_cell(_c.severity),
                                  P(_safe_truncate(_c.explanation, 300))])
                _t = Table(_rows, colWidths=[110, 72, 298])
                _t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), DARK), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                                        ("GRID", (0, 0), (-1, -1), 0.4, BORDER), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
                _doa.append(_t)
                _doa.append(P("A contradiction is a lead for human review. It does not establish a fact, an identity "
                               "or guilt. All statements come from one case narrative, so they are not independent.",
                               small))
            else:
                _doa.append(P(f"No structured contradiction found in the case narrative ({len(_as)} assertion(s) "
                               "checked: loans, roles, addresses). This does not mean the account is consistent "
                               "outside these rules.", small))
        except Exception as _e:
            _doa.append(P(f"Structured contradiction check unavailable ({type(_e).__name__}).", small))
        _tl = d.get("narrative_timeline") or []
        if _tl:
            _doa.append(Spacer(1, 8))
            _doa.append(Paragraph("Narrative Timeline (dated statements)", h3))
            _rows = [[P("Date", th), P("Type", th), P("Statement", th)]]
            for _r in _tl[:20]:
                _amb = " (day/month ambiguous)" if "AMBIGUOUS_DAY_MONTH" in (_r.get("flags") or []) else ""
                _rows.append([P(f"{_r.get('date')}{_amb}"), P(_r.get("kind")), P(_safe_truncate(_r.get("text", ""), 220))])
            _t = Table(_rows, colWidths=[110, 60, 310])
            _t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), DARK), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                                    ("GRID", (0, 0), (-1, -1), 0.4, BORDER), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
            _doa.append(_t)
        _ck = d.get("source_checklist") or []
        if _ck:
            _doa.append(Spacer(1, 8))
            _doa.append(Paragraph("Source Checklist", h3))
            _rows = [[P("Source", th), P("Status", th), P("Note", th)]]
            for _c in _ck:
                _rows.append([P(_c.get("source")), P(_c.get("status")), P(_c.get("note"))])
            _t = Table(_rows, colWidths=[190, 90, 200])
            _t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), DARK), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                                    ("GRID", (0, 0), (-1, -1), 0.4, BORDER), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
            _doa.append(_t)
            _doa.append(P("NOT ASSESSED means the source was not checked for this report. It is not a negative finding.", small))
        _doa.append(Spacer(1, 6))
        _doa.append(P(f"<b>Integrity:</b> generated {_gen_time}. Content SHA-256 of the report data: "
                       f"{_content_sha}. The PDF file's own SHA-256 is written to a .sha256 file next to the export.",
                       small))

        # place the DOA block before the closing disclaimer (Spacer, HR, Spacer, Paragraph)
        story[len(story) - 4:len(story) - 4] = _doa

        doc = SimpleDocTemplate(out_path, pagesize=letter,
                                 topMargin=BAR_H + 20, bottomMargin=50,
                                 leftMargin=50, rightMargin=50)
        doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
        try:
            import hashlib as _hl2, os as _os
            _pdf_sha = _hl2.sha256(open(out_path, "rb").read()).hexdigest()
            with open(out_path + ".sha256", "w") as _fh:
                _fh.write(f"{_pdf_sha}  {_os.path.basename(out_path)}\ncontent_sha256 {_content_sha}\ngenerated {_gen_time}\n")
            log.info(f"PDF export {_os.path.basename(out_path)} sha256={_pdf_sha}")
        except Exception:
            pass
        return gr.update(value=out_path, visible=True)
    except Exception as e:
        log.error(f"PDF export error: {e}\n{traceback.format_exc()}")
        return gr.update(value=None, visible=False)
