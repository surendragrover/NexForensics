"""
DOA dossier -> PDF (reportlab). One file per run, never overwritten.
Footer on every page: generation time (IST, with offset) + result SHA-256 + page number.
After writing, the PDF's own SHA-256 goes to <pdf>.sha256 (a file cannot contain its own hash).
"""
from __future__ import annotations
import hashlib, os
from datetime import datetime
from typing import Any, Dict
from zoneinfo import ZoneInfo
from xml.sax.saxutils import escape

STATUS_COLOR = {"ESTABLISHED": "#166534", "STRONGLY_CORROBORATED": "#15803d", "REPORTED": "#1d4ed8",
                "UNVERIFIED": "#b45309", "DISPUTED": "#b91c1c", "NOT_ESTABLISHED": "#475569",
                "NOT_AVAILABLE": "#64748b", "NOT_ASSESSED": "#64748b"}
SEV_COLOR = {"CRITICAL": "#7f1d1d", "HIGH": "#b91c1c", "MODERATE": "#b45309", "LOW": "#475569"}


def ist_now() -> str:
    return datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%Y-%m-%d %H:%M IST (UTC+05:30)")


def render_doa_pdf(result: Dict[str, Any], subject: Dict[str, Any], out_path: str) -> Dict[str, str]:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether

    if os.path.exists(out_path):
        raise FileExistsError(out_path)
    gen = ist_now()
    rsha = result.get("sha256", "n/a")
    ss = getSampleStyleSheet()
    body = ParagraphStyle("b", parent=ss["BodyText"], fontName="Helvetica", fontSize=9, leading=12)
    small = ParagraphStyle("s", parent=body, fontSize=7.5, leading=10, textColor=colors.HexColor("#334155"))
    h1 = ParagraphStyle("h1", parent=ss["Title"], fontName="Helvetica-Bold", fontSize=16, leading=20)
    h2 = ParagraphStyle("h2", parent=ss["Heading2"], fontName="Helvetica-Bold", fontSize=11.5, leading=14,
                        spaceBefore=8, spaceAfter=4, textColor=colors.HexColor("#0f172a"))
    th = ParagraphStyle("th", parent=body, fontName="Helvetica-Bold", textColor=colors.white, fontSize=8.5)
    P = lambda t, st=body: Paragraph(escape(str(t)).replace("\n", "<br/>"), st)

    def colored(t, c):
        return Paragraph(f'<font color="{c}"><b>{escape(str(t))}</b></font>', body)

    def table(rows, widths):
        t = Table(rows, colWidths=widths, repeatRows=1)
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f172a")),
                               ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cbd5e1")),
                               ("VALIGN", (0, 0), (-1, -1), "TOP"),
                               ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")])]))
        return t

    story = [P("NexForensics: Deep OSINT Dossier (DOA)", h1),
             P(f"Investigation {result.get('investigation_id', '')}  |  Generated {gen}", small), Spacer(1, 6)]
    subj = [[P("Subject", th), P("Value", th)]] + [[P(k), P(v or "not given")] for k, v in (
        ("Name", subject.get("name")), ("Aliases", ", ".join(subject.get("aliases") or [])),
        ("Date of birth", subject.get("dob")), ("City", subject.get("city")),
        ("Organisations", ", ".join(subject.get("organizations") or [])), ("Questions", (result.get("question") or "").replace("\n", "   ")))]
    story.append(table(subj, [110, 405]))
    story.append(Spacer(1, 6))
    story.append(Paragraph(
        '<font color="#7f1d1d"><b>Read first:</b></font> this dossier is an evidence graph, not a verdict. '
        "It establishes no fact, identity, guilt or non-existence. Name-only matches are leads. "
        "\"Not found\" means not found in the sources searched. Dark-web material is unverified. "
        "A qualified person must review every item before publication or legal use.", small))

    cov = result.get("coverage") or []
    if cov:
        story.append(P("Source coverage", h2))
        rows = [[P("Source / checklist item", th), P("Status", th), P("Reason", th)]]
        for c in cov:
            rows.append([P(c.get("checklist_item")), colored(c.get("status"), STATUS_COLOR.get(c.get("status"), "#334155")),
                         P(c.get("reason"))])
        story.append(table(rows, [150, 105, 260]))

    fc = (result.get("contradictions") or {}).get("structured") or []
    story.append(P("Structured contradictions", h2))
    if fc:
        rows = [[P("Type", th), P("Severity", th), P("What conflicts / other explanations", th)]]
        for c in fc:
            alts = "; ".join(c.get("alternative_explanations") or [])
            rows.append([P(c.get("doa_class")), colored(c.get("severity"), SEV_COLOR.get(c.get("severity"), "#334155")),
                         P(f"{c.get('explanation')}\nOther explanations: {alts}" if alts else c.get("explanation"))])
        story.append(table(rows, [95, 65, 355]))
    else:
        story.append(P("No structured contradiction found by the current rules (loans, roles, addresses).", small))

    fnd = result.get("findings") or []
    if fnd:
        story.append(P("Findings (canonical status)", h2))
        rows = [[P("Status", th), P("Statement", th), P("Indep. sources", th)]]
        for f in fnd:
            rows.append([colored(f.get("status"), STATUS_COLOR.get(f.get("status"), "#334155")), P(f.get("statement")),
                         P(f.get("independent_lineages"))])
        story.append(table(rows, [105, 350, 60]))

    ids = result.get("identity") or []
    if ids:
        story.append(P("Identity resolution (per document)", h2))
        rows = [[P("Document", th), P("Decision", th), P("Anchors matched", th), P("Anchors conflicting", th)]]
        for i in ids[:60]:
            rows.append([P(i.get("document_id")), P(i.get("decision")), P(", ".join(i.get("anchors_match") or []) or "-"),
                         P(", ".join(i.get("anchors_conflict") or []) or "-")])
        story.append(table(rows, [150, 165, 100, 100]))

    fr = subject.get("face")
    if fr:
        story.append(P("Face comparison", h2))
        if fr.get("status") == "ASSESSED":
            story.append(P(f"Model {fr.get('model')}. {fr.get('faces_checked', 0)} face(s) checked in the investigator's "
                           "uploaded files only (no web search). Similarity is a lead for human review; it does not "
                           "establish identity. POSSIBLE MATCH from cosine 0.363 (OpenCV's documented SFace threshold); "
                           "STRONG from 0.50 (provisional).", small))
            rows = [[P("File", th), P("Where", th), P("Face", th), P("Similarity", th), P("Band", th)]]
            for m in (fr.get("matches") or [])[:20]:
                rows.append([P(m["file"]), P(m["where"]), P(m["face"]), P(f"{m['similarity']:.3f}"), P(m["band"])])
            if len(rows) > 1:
                story.append(table(rows, [140, 70, 40, 65, 200]))
        if fr.get("reason"):
            story.append(P(fr["reason"], small))

    for s in (result.get("dossier") or {}).get("sections") or []:
        story.append(KeepTogether([P(f"{s.get('order')}. {s.get('title')}", h2), P(s.get("body"))]))

    story.append(Spacer(1, 8))
    story.append(P(f"Integrity: generated {gen}. Result payload SHA-256 {rsha}. Pipeline "
                   f"{result.get('pipeline_version', '')}. The PDF file's own SHA-256 is in {os.path.basename(out_path)}.sha256.",
                   small))

    def on_page(c, doc):
        c.saveState()
        c.setFont("Helvetica", 7)
        c.setFillColor(colors.HexColor("#475569"))
        c.drawString(36, 20, f"DOA {result.get('investigation_id', '')} | {gen} | result SHA-256 {rsha[:16]}")
        c.drawRightString(A4[0] - 36, 20, f"Page {c.getPageNumber()}")
        c.drawCentredString(A4[0] / 2, 31, "CONFIDENTIAL. Evidence graph for human review; not a finding of fact or guilt.")
        c.restoreState()

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    SimpleDocTemplate(out_path, pagesize=A4, leftMargin=36, rightMargin=36, topMargin=36, bottomMargin=46,
                      title="DOA dossier", author="NexForensics DOA").build(story, onFirstPage=on_page, onLaterPages=on_page)
    pdf_sha = hashlib.sha256(open(out_path, "rb").read()).hexdigest()
    with open(out_path + ".sha256", "w") as fh:
        fh.write(f"{pdf_sha}  {os.path.basename(out_path)}\nresult_sha256 {rsha}\ngenerated {gen}\n")
    return {"pdf": out_path, "pdf_sha256": pdf_sha, "generated": gen}
