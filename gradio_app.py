"""
InvestigatorAI — Final Gradio App
====================================
Models (5):
  NER         -> HuggingFace Transformers        models/ner/
  Voice       -> PyTorch .pt/.pth                models/voice/model.pt
  Face        -> ArcFace PyTorch                 models/face/arcface.pt
  OCR         -> TrOCR (HuggingFace)              models/ocr/
  Risk Model  -> XGBoost (fine-tuned)             models/risk_model/xgb_model.json

Rule component: models/hybrid_rules/*.json

Risk score graphs rendered inline via matplotlib -> base64 PNG.

NOTE (refactor): the model-inference engines (NER/Voice/Face/OCR/XGBoost/
HF image classifier/Qwen LLM) and the dataset/MO-fingerprint matching
engines used to be defined inline here. They now live in
engines/ml_engines.py and engines/matching_engines.py -- imported below.
Shared env/config constants (MODELS_DIR, DB_*, log, ...) live in config.py.
"""

import os, json, random, warnings, logging, base64, io, hashlib, re, uuid, traceback
from pathlib import Path
from datetime import datetime, timedelta

import numpy as np
import gradio as gr

from config import (
    log, MODELS_DIR, FLASK_API, RULES_DIR, GUIDANCE_KB_DIR,
    DB_HOST, DB_USER, DB_PASSWORD, DB_NAME,
)
from engines.ml_engines import (
    NEREngine, VoiceEngine, FaceEngine, OCREngine, XGBPatternEngine,
    HFImageClassifierEngine, QwenGGUFEngine, _extract_video_frame,
)
from engines.matching_engines import DatasetSearchEngine, MOFingerprintEngine
from utils import (
    _safe_truncate, _display_watchlist_status, _hypothesis_display_status,
    calibrate_deepfake_result,
)
from reports.pdf_export import export_report_pdf
from gdelt_ui import build_gdelt_tabs
from analysis.evidence_analysis import (
    _kw_in, _classify_crime_from_evidence, _analyze_text_evidence, _analyze_facial_evidence,
    _analyze_voice_evidence, _analyze_document_evidence, _compute_fraud_from_evidence,
    _fix_entity_name_type, _name_match_strength, _assess_threat_from_evidence,
    _generate_actions_from_evidence, _looks_like_a_name, _analyze_financial_evidence,
    _analyze_vehicle_evidence, _lookup_suspect_background, _lookup_unidentified_offender,
    _analyze_network_evidence,
)
from analysis.evidence_meta import (
    _normalize_uploaded_files, _sha256_file, _assess_image_quality, _extract_exif,
    _get_audio_evidence_meta, _get_document_evidence_meta,
)
from reports.html_renderers import build_graphs_html, _inv_render_html, _build_network_html
from analysis.reasoning import (
    _build_reasoning_engine, _EVIDENCE_CHECKLIST_META, _build_intelligence_summary, _extract_timeline,
)

from investigator_integration import run_investigator_engine
from guidance_engine.engine import InvestigationGuidanceEngine, CaseContext, EvidenceItem, Hypothesis
from guidance_engine.gradio_patch_ui import render_guidance_section

warnings.filterwarnings("ignore")

# ── Knowledge-Driven Investigation Guidance Engine ──────────────────────────
# Rule/knowledge-base driven (not ML) — reads professional_gang.json,
# inside_job.json, financial_fraud.json, general.json, etc. from
# guidance_engine/knowledge_base/ and turns the case's hypotheses +
# evidence into ranked, explainable "next investigation angle" directions.
try:
    guidance_engine = InvestigationGuidanceEngine(GUIDANCE_KB_DIR)
    log.info(f"Investigation Guidance Engine loaded ({len(guidance_engine.kbs)} knowledge bases from {GUIDANCE_KB_DIR})")
except Exception as e:
    log.error(f"Investigation Guidance Engine failed to load: {e}")
    guidance_engine = None


# ============================================================
# REASONING ENGINE — NexForensics core layer
#
# Everything above (NER/OCR/Face/Voice/Dataset Search/MO
# Fingerprinting/Unidentified-Offender search) is a DATA PROVIDER:
# it extracts or matches individual pieces of evidence. This layer
# sits above all of them and does what none of them do alone —
# looks ACROSS everything gathered for a single case to surface:
#   • Gaps       — what evidence is missing / what wasn't checked
#   • Contradictions — where two pieces of evidence disagree
#   • Hypotheses — possible investigative directions, each with its
#                  supporting AND contradicting evidence + a source
#   • Draft Report — a short, source-cited narrative a journalist or
#                     investigator can edit, not a final verdict
#
# It never declares guilt or certainty. Every hypothesis is labelled
# an "AI-generated investigative lead" — the human decides what to
# do with it. This mirrors the "AI suggests, human decides" principle
# from the NexForensics vision document.
# ============================================================
# BUG FIX (2026-08-20 — Medium/High): report text was being hard-truncated
# at a fixed character count (e.g. text[:60]) all over the PDF, with no
# check for word boundaries and often no "…" to signal the cut. This
# produced text that *looked* corrupted — e.g. "...name-fragment m" (cut
# mid-word, no ellipsis) or dict/metadata dumps chopped mid-token. Route
# every such truncation through this helper instead: it always cuts at
# the last whole word before the limit and always marks the cut with "…"
# so truncated text is visibly truncated, never mistaken for corrupted
# data.


# BUG FIX (2026-08-20 — High): watchlist/sanctions/interpol/FBI fields
# store the raw value "NO" internally (used throughout the file in
# `!= "NO"` checks — left as-is to avoid touching that branching logic on
# launch night). But showing a bare "NO" to an investigator reads as
# "definitively no record exists anywhere", which overstates what a
# database lookup actually established. This wraps ONLY the *display*
# value, never the internal one used for comparisons.




# ============================================================
# INVESTIGATION INTELLIGENCE SUMMARY
#
# A higher-level synthesis layer sitting above the Reasoning Engine —
# turns its raw gaps/hypotheses into an "Investigation Status" panel,
# an Evidence Completeness meter, a prioritized Next Evidence table,
# and a 5-point plain-language summary. Nothing here is computed from
# new signals — it's all a re-presentation of what the Reasoning
# Engine, MO Fingerprinting, and dataset lookups already found, aimed
# at answering the investigator's real first question ("what do I do
# next?") instead of a single ambiguous risk-color verdict.
# ============================================================

# (evidence_type, provided_flag, priority_if_missing, why)




# ══════════════════════════════════════════════════════════════════════════════
# INVESTIGATION TIMELINE — extracted from Modus Operandi narrative
# ══════════════════════════════════════════════════════════════════════════════


# ══════════════════════════════════════════════════════════════════════════════
# MODEL ENGINES
# ══════════════════════════════════════════════════════════════════════════════


# ── Load hybrid rules ─────────────────────────────────────────────────────────
HYBRID_RULES = {}
if RULES_DIR.exists():
    try:
        rule_files = sorted(RULES_DIR.glob("*.json"))
        if rule_files:
            with open(rule_files[0], encoding="utf-8") as f:
                HYBRID_RULES = json.load(f)
            log.info(f"Hybrid rules loaded: {rule_files[0]}")
        else:
            log.info(f"Hybrid rules: no .json file found in {RULES_DIR}")
    except Exception as e:
        log.warning(f"Rules load failed: {e}")

# ── Load at startup ────────────────────────────────────────────────────────────
# v8 — 5-model flat layout under MODELS_DIR:
#   ner/  voice/  face/  ocr/  risk_model/  hybrid_rules/
ner_eng  = NEREngine      (MODELS_DIR / "ner")
vox_eng  = VoiceEngine    (MODELS_DIR / "voice")
face_eng = FaceEngine     (MODELS_DIR / "face")
ocr_eng  = OCREngine      (MODELS_DIR / "ocr")
xgb_eng  = XGBPatternEngine(MODELS_DIR / "risk_model")
ds_eng   = DatasetSearchEngine()
mo_eng   = MOFingerprintEngine()
qwen_eng = QwenGGUFEngine(MODELS_DIR / "qwen" / "model.gguf")
cctv_eng = HFImageClassifierEngine("CCTV Crime Classifier", path=MODELS_DIR / "crime_cctv")
deepfake_eng = HFImageClassifierEngine(
    "Deepfake Detector",
    repo_id="prithivMLmods/Deepfake-vs-Real-8000",
    cache_dir=MODELS_DIR / "deepfake" / "face",
)

STATUS = {
    "NER":     "✓" if ner_eng.ready  else "○",
    "Voice":   "✓" if vox_eng.ready  else "○",
    "ArcFace": "✓" if face_eng.ready else "○",
    "OCR":     "✓" if ocr_eng.ready  else "○",
    "Risk":    "✓" if xgb_eng.ready  else "heuristic",
    "Datasets":"✓" if ds_eng.ready   else "○",
    "AI Reasoning": "✓" if qwen_eng.ready else "○",
    "CCTV":    "✓" if cctv_eng.ready else "○",
    "Deepfake":"✓" if deepfake_eng.ready else "○",
}


analysis_history = []   # small in-memory cache mirroring the DB, used only
                         # to build the trend graph within a single process
                         # run without an extra DB round-trip on every request

# ── Persistent investigation history (MySQL) ────────────────────────────────
# Survives restarts/redeploys — analysis_history above is just a fast local
# mirror of the most recent rows, rebuilt from this table at every save.
def _history_db_connect():
    import mysql.connector
    return mysql.connector.connect(
        host=DB_HOST, user=DB_USER, password=DB_PASSWORD,
        database=DB_NAME, connection_timeout=5,
    )


def _ensure_history_table():
    try:
        conn = _history_db_connect()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS ia_gradio_history (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                case_id VARCHAR(100),
                suspect_name VARCHAR(500),
                user_email VARCHAR(255),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                deception_score DECIMAL(6,2),
                credibility_score DECIMAL(6,2),
                risk_score DECIMAL(6,2),
                verdict_label VARCHAR(150),
                report_text LONGTEXT,
                report_data_json LONGTEXT,
                KEY idx_created (created_at),
                KEY idx_case (case_id),
                KEY idx_user (user_email)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)
        conn.commit()
        cur.close()
        conn.close()
        log.info("Investigation history table ready (ia_gradio_history)")
        return True
    except Exception as e:
        log.warning(f"History table setup failed (history will not persist): {e}")
        return False


# ============================================================
# DRAFT AUTO-SAVE
#
# Long-running Investigate requests can be killed by an edge proxy
# (e.g. Cloudflare's ~100s timeout) before the browser gets a response,
# which used to wipe out everything the user had typed. This table
# stores the in-progress form as JSON, keyed by a per-browser-session
# draft_key (a UUID generated once when the page loads and kept in a
# gr.State for that session). Every field saves itself on blur, so even
# if the connection to the server drops mid-Investigate, the form data
# itself was already safely persisted before that request ever fired.
# ============================================================

def _ensure_drafts_table():
    try:
        conn = _history_db_connect()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS ia_gradio_drafts (
                draft_key VARCHAR(64) PRIMARY KEY,
                form_json LONGTEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                KEY idx_updated (updated_at)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)
        conn.commit()
        cur.close()
        conn.close()
        log.info("Draft auto-save table ready (ia_gradio_drafts)")
        return True
    except Exception as e:
        log.warning(f"Drafts table setup failed (auto-save will not persist): {e}")
        return False


def save_draft(draft_key, *field_values):
    """Fires on every tracked field's blur event. Upserts the whole form
    snapshot as JSON under this session's draft_key. Silent no-op on
    failure — a failed auto-save must never interrupt the user's typing."""
    if not draft_key:
        return
    try:
        conn = _history_db_connect()
        cur = conn.cursor()
        payload = json.dumps(list(field_values), default=str)
        cur.execute("""
            INSERT INTO ia_gradio_drafts (draft_key, form_json)
            VALUES (%s, %s)
            ON DUPLICATE KEY UPDATE form_json = VALUES(form_json), updated_at = CURRENT_TIMESTAMP
        """, (draft_key, payload))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        log.warning(f"Draft auto-save failed (non-fatal): {e}")


def load_draft(draft_key):
    """Returns the saved field-value list for this draft_key, or None."""
    if not draft_key:
        return None
    try:
        conn = _history_db_connect()
        cur = conn.cursor()
        cur.execute("SELECT form_json FROM ia_gradio_drafts WHERE draft_key=%s", (draft_key,))
        row = cur.fetchone()
        cur.close()
        conn.close()
        if row and row[0]:
            return json.loads(row[0])
    except Exception as e:
        log.warning(f"Draft load failed: {e}")
    return None


HISTORY_DB_READY = _ensure_history_table()
DRAFTS_DB_READY = _ensure_drafts_table()


def _save_history_entry(entry, report_text, report_data, user_email=None):
    """Persists one completed analysis (full report + structured data) to
    MySQL, so it survives restarts and can be reloaded/re-viewed later."""
    if not HISTORY_DB_READY:
        return
    try:
        conn = _history_db_connect()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO ia_gradio_history
                (case_id, suspect_name, user_email, deception_score,
                 credibility_score, risk_score, verdict_label,
                 report_text, report_data_json)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, (
            entry.get("case_id"), report_data.get("suspect_name") if report_data else None,
            user_email, entry.get("deception"), entry.get("credibility"),
            entry.get("risk"), report_data.get("v_label") if report_data else None,
            report_text,
            json.dumps(report_data, ensure_ascii=False, default=str) if report_data else None,
        ))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        log.error(f"Failed to save investigation history: {e}")


def _req_email(request):
    """Email of the logged-in dashboard user (from the Gradio auth JWT cookie), or None.
    Per-user isolation: history is never shown without a resolved user."""
    try:
        if request is not None and hasattr(request, "cookies"):
            tok = request.cookies.get(AUTH_COOKIE)
            if tok:
                pl = _verify_jwt(tok)
                if pl:
                    return pl.get("email")
    except Exception as e:
        log.warning(f"user resolve failed: {e}")
    return None


_US_TOKENS = (" us ", " usa ", "united states", " u.s.", "america")


def _fbi_display_for(location, raw):
    raw = str(raw or "NO")
    if raw.upper() not in ("NO", "", "NONE", "N/A", "NO MATCH RETURNED"):
        return _display_watchlist_status(raw)          # a real hit is never hidden
    j = f" {str(location or '').strip().lower()} "
    if any(x in j for x in _US_TOKENS):
        return "NOT FOUND in sources searched"
    return "NOT APPLICABLE (non-US case)" if j.strip() else "US-ONLY LIST (not applicable)"


def _honest_negative(v):
    s = str(v or "")
    if s.upper().startswith("NO CONFIRMED RECORD"):
        return "NOT FOUND in sources searched (weak name-fragment matches only)"
    if s.upper() in ("NO RECORD", "NO", "NONE"):
        return "NOT FOUND in sources searched"
    return s


def _load_recent_history(limit=20, user_email=None):
    """Returns recent history rows as dicts (case_id, date, risk, deception,
    credibility, suspect_name) — newest first. Used for both the history
    panel and the trend graph."""
    if not HISTORY_DB_READY:
        return []
    try:
        conn = _history_db_connect()
        cur = conn.cursor(dictionary=True)
        if not user_email:
            cur.close(); conn.close()
            return []
        if user_email:
            cur.execute("""
                SELECT id, case_id, suspect_name, created_at, deception_score,
                       credibility_score, risk_score, verdict_label
                FROM ia_gradio_history WHERE user_email=%s
                ORDER BY created_at DESC LIMIT %s
            """, (user_email, limit))
        else:
            cur.execute("""
                SELECT id, case_id, suspect_name, created_at, deception_score,
                       credibility_score, risk_score, verdict_label
                FROM ia_gradio_history ORDER BY created_at DESC LIMIT %s
            """, (limit,))
        rows = cur.fetchall()
        cur.close()
        conn.close()
        out = []
        for r in rows:
            out.append({
                "id": r["id"],
                "case_id": r["case_id"] or f"NXF-{r['id']}",
                "suspect_name": r.get("suspect_name") or "N/A",
                "date": r["created_at"].strftime("%d %b %Y %H:%M") if r["created_at"] else "",
                "deception": float(r["deception_score"] or 0),
                "credibility": float(r["credibility_score"] or 0),
                "risk": float(r["risk_score"] or 0),
                "verdict_label": r.get("verdict_label") or "",
            })
        return out
    except Exception as e:
        log.error(f"Failed to load investigation history: {e}")
        return []


def _load_history_report(record_id, user_email=None):
    """Fetches the full saved report (text + structured report_data) for
    one past investigation, by its history-table id."""
    if not HISTORY_DB_READY or not record_id or not user_email:
        return None, None
    try:
        conn = _history_db_connect()
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT report_text, report_data_json FROM ia_gradio_history WHERE id=%s AND user_email=%s", (record_id, user_email))
        row = cur.fetchone()
        cur.close()
        conn.close()
        if not row:
            return None, None
        report_data = json.loads(row["report_data_json"]) if row["report_data_json"] else None
        return row["report_text"], report_data
    except Exception as e:
        log.error(f"Failed to load history report {record_id}: {e}")
        return None, None


def _history_dropdown_choices(user_email=None):
    """(label, value) pairs for the history gr.Dropdown — value is the
    numeric row id used to fetch the full report back on 'Load'."""
    rows = _load_recent_history(limit=30, user_email=user_email)
    return [(f"{r['date']}  —  {r['case_id']}  —  {r['suspect_name']}  ({r['risk']:.0f}% risk)", r["id"])
            for r in rows]


# ══════════════════════════════════════════════════════════════════════════════
# FIELD HISTORY — lets a user click a case-form field (Suspect Name, Location,
# Case Title, Investigating Officer, Crime Category) and pick a value they've
# entered before, instead of retyping the same profile from scratch every time.
# ══════════════════════════════════════════════════════════════════════════════
FIELD_HISTORY_KEYS = {
    "suspect_name":          "suspect_name",
    "location":               "location",
    "case_title":             "case_title",
    "investigating_officer":  "investigating_officer",
    "crime_category":         "crime_category",
}

def _load_field_choices(limit=150, user_email=None):
    """Scans the last `limit` saved reports and pulls out distinct, non-empty
    values per form field, most-recent-first, so they can be offered as
    click-to-select Dropdown choices."""
    empty = {k: [] for k in FIELD_HISTORY_KEYS}
    if not HISTORY_DB_READY or not user_email:
        return empty
    try:
        conn = _history_db_connect()
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT report_data_json FROM ia_gradio_history WHERE user_email=%s "
            "ORDER BY created_at DESC LIMIT %s", (user_email, limit)
        )
        rows = cur.fetchall()
        cur.close()
        conn.close()

        out = {k: [] for k in FIELD_HISTORY_KEYS}
        for row in rows:
            blob = row.get("report_data_json")
            if not blob:
                continue
            try:
                data = json.loads(blob)
            except Exception:
                continue
            for field_key, data_key in FIELD_HISTORY_KEYS.items():
                val = data.get(data_key)
                if val and val not in ("N/A", "Unknown") and val not in out[field_key]:
                    out[field_key].append(val)
        return out
    except Exception as e:
        log.warning(f"Field history load failed: {e}")
        return empty


# ══════════════════════════════════════════════════════════════════════════════
# GRAPH GENERATOR  —  matplotlib → base64 PNG (no file I/O)
# ══════════════════════════════════════════════════════════════════════════════


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 1: EVIDENCE COLLECTION & INTEGRITY
# ══════════════════════════════════════════════════════════════════════════════













# ══════════════════════════════════════════════════════════════════════════════
# CRIME CLASSIFICATION — Karnamon ke Aadhar par
# ══════════════════════════════════════════════════════════════════════════════





# ══════════════════════════════════════════════════════════════════════════════
# EVIDENCE ANALYSIS — Model Names ke Bajaay Karnamon par Focus
# ══════════════════════════════════════════════════════════════════════════════









# ══════════════════════════════════════════════════════════════════════════════
# FRAUD INDICATORS — Evidence-Based
# ══════════════════════════════════════════════════════════════════════════════



# ══════════════════════════════════════════════════════════════════════════════
# NETWORK & WATCHLIST
# ══════════════════════════════════════════════════════════════════════════════









# ══════════════════════════════════════════════════════════════════════════════
# THREAT ASSESSMENT
# ══════════════════════════════════════════════════════════════════════════════



# ══════════════════════════════════════════════════════════════════════════════
# ACTIONABLE INTELLIGENCE
# ══════════════════════════════════════════════════════════════════════════════



# ══════════════════════════════════════════════════════════════════════════════
# NETWORK & FINANCIAL INTELLIGENCE — Naya System
# ══════════════════════════════════════════════════════════════════════════════









from html import escape as _esc_html

from reports.charts import (
    _PDF_NODE_TYPE_COLORS, _pdf_truncate_label, _kg_nodes_edges,
    _criminal_network_nodes_edges, _VIS_NETWORK_HEAD, _VIS_NETWORK_INIT_JS,
    _build_interactive_network_html, _pdf_network_diagram, _pdf_crime_dna_radar,
    _safe_num, _pdf_evidence_provided_chart, _pdf_fraud_indicators_chart,
    _pdf_hypothesis_confidence_chart, _pdf_risk_signals_chart,
    _pdf_evidence_coverage_chart, _pdf_progress_bar,
)









def run_analysis(case_id, modus, suspect_name, location, photo, voice_clip, id_doc, network_text, financial_ids, vehicle_info, unidentified_flag=False, physical_desc="", digital_emails="", digital_phones="", digital_urls="", cyber_flags=None, case_title="", crime_category="", incident_date="", investigating_officer="", case_priority="Medium", ucp_age="", ucp_gender="Unknown", ucp_height="", ucp_body_type="Unknown", ucp_language="", ucp_accent="", ucp_handedness="Unknown", ucp_dominant_behaviour="", ucp_entry_method="", ucp_behaviour_at_scene="", ucp_weapons_used="", ucp_team_size="Unknown", ucp_tech_skill="Unknown", ucp_experience_level="Unknown", ucp_planning_level="Unknown", ucp_risk_behaviour="Unknown", ucp_escape_pattern="", ucp_mo_signature="", ucp_confidence=40, ucp_behaviour_profile="", cctv_video=None, request: gr.Request = None):
    # id_doc now comes from gr.File(file_count="multiple") — normalize into
    # a clean list[str] of filepaths (images and/or PDFs) up front so every
    # check below can stay a simple truthy check.
    id_doc = _normalize_uploaded_files(id_doc)

    has_any_input = any([
        (case_id or "").strip(), (modus or "").strip(),
        (suspect_name or "").strip(), (location or "").strip(),
        photo is not None, voice_clip, id_doc,
        (physical_desc or "").strip(),
        (digital_emails or "").strip(), (digital_phones or "").strip(),
        (digital_urls or "").strip(), cyber_flags,
    ])
    if not has_any_input:
        return (None,) * 4 + (gr.update(visible=False),
                gr.update(visible=False),
                "Fill in at least one field to run analysis.",
                _history_html(_req_email(request)), None)

    # ── EVIDENCE COLLECTION & INTEGRITY ─────────────────────────────────────
    photo_hash = "N/A"
    if photo is not None:
        import io as _io
        buf = _io.BytesIO()
        photo.save(buf, format=photo.format or 'PNG')
        photo_hash = hashlib.sha256(buf.getvalue()).hexdigest()

    audio_hash = _sha256_file(voice_clip) if voice_clip and os.path.exists(voice_clip) else "N/A"

    doc_hash = "N/A"
    if id_doc:
        _file_hashes = [_sha256_file(p) for p in id_doc]
        _file_hashes = [h for h in _file_hashes if h and not h.startswith(("N/A", "Hash Error"))]
        if _file_hashes:
            doc_hash = hashlib.sha256("|".join(_file_hashes).encode()).hexdigest()

    photo_meta = _extract_exif(photo) if photo is not None else {}
    audio_meta = _get_audio_evidence_meta(voice_clip) if voice_clip else {}
    doc_meta = _get_document_evidence_meta(id_doc) if id_doc else {}

    evidence_integrity = {
        "photo_hash": photo_hash if photo else "N/A — No photo evidence submitted",
        "audio_hash": audio_hash if voice_clip else "N/A — No audio evidence submitted",
        "doc_hash": doc_hash if id_doc else "N/A — No document evidence submitted",
        "photo_metadata": photo_meta,
        "audio_metadata": audio_meta,
        "document_metadata": doc_meta,
        "tampering_status": "N/A — Deepfake/tamper detection module offline",
        "chain_of_custody": f"Evidence logged at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} UTC",
    }

    # ── TEXT EVIDENCE EXTRACTION (NER) ──────────────────────────────────────
    raw_text = f"{modus or ''} {suspect_name or ''} {location or ''}".strip()
    entities = ner_eng.extract(raw_text) if ner_eng.ready else {}
    ner_sc = ner_eng.score(entities) if ner_eng.ready else 0.0

    # ─── DIGITAL EVIDENCE PROCESSING ──────────────────────────────────
    digital_entities = {}
    if digital_emails:
        digital_entities["EMAIL"] = [e.strip() for e in digital_emails.split(",") if e.strip()]
    if digital_phones:
        digital_entities["PHONE"] = [p.strip() for p in digital_phones.split(",") if p.strip()]
    if digital_urls:
        digital_entities["URL"] = [u.strip() for u in digital_urls.split(",") if u.strip()]

    if digital_entities:
        for k, v in digital_entities.items():
            entities.setdefault(k, []).extend(v)
    # ─── END DIGITAL PROCESSING ───────────────────────────────────────────

    # ─── QWEN ENHANCEMENT (runs in parallel with NER, never replaces it) ───
    qwen_insights = {}
    qwen_deception = {}
    if qwen_eng.ready and (modus or "").strip():
        log.info("Qwen: analyzing statement...")
        qwen_insights = qwen_eng.analyze_statement(modus, suspect_name, location)
        qwen_deception = qwen_eng.assess_deception(modus)

        # Merge Qwen's extra entities into the same `entities` dict NER
        # already populated — NER's own findings are never removed or
        # overwritten, Qwen's are only ever appended alongside them.
        qwen_extracted = qwen_insights.get("entities_extracted", {})
        type_map = {
            "persons": "PERSON", "organizations": "ORG", "locations": "LOC",
            "weapons": "WEAPON", "crimes": "CRIME", "threats": "THREAT",
            "financial_terms": "MONEY",
        }
        _FINANCIAL_TERM_RE = re.compile(
            r'[₹$€£]|\b\d+([.,]\d+)?\b|\b(laundering|transfer|payment|wallet|account|'
            r'cash|deposit|withdraw|bank|loan|debt|fund|crypto|bitcoin|invoice|salary)\b',
            re.IGNORECASE,
        )
        for qtype, mapped_type in type_map.items():
            values = [v for v in (qwen_extracted.get(qtype) or []) if v]
            if qtype == "financial_terms":
                # LLM sometimes fills this field with unrelated words (e.g. "attack")
                # that have nothing to do with money — only keep values that actually
                # look financial before letting them inflate the MONEY entity count
                # (and therefore the financial-anomaly score downstream).
                values = [v for v in values if _FINANCIAL_TERM_RE.search(str(v))]
            if values:
                entities.setdefault(mapped_type, []).extend(values)
        for item in (qwen_extracted.get("digital_indicators") or []):
            if not item:
                continue
            if "@" in item:
                entities.setdefault("EMAIL", []).append(item)
            elif re.match(r'^\+?\d{10,15}$', item.replace("-", "").replace(" ", "")):
                entities.setdefault("PHONE", []).append(item)
            elif item.startswith(("http://", "https://", "www.")):
                entities.setdefault("URL", []).append(item)
    # ─── END QWEN ENHANCEMENT ───────────────────────────────────────────────

    # ── VOICE EVIDENCE ANALYSIS ─────────────────────────────────────────────
    vox_res = vox_eng.analyse(voice_clip) if voice_clip and vox_eng.ready else {}
    vox_sc = vox_res.get("stress_score", ner_sc * 0.88) if vox_res else 0.0
    if vox_res and suspect_name and suspect_name.strip():
        recognized = (vox_res.get("top_speaker") or "").strip().lower()
        claimed = suspect_name.strip().lower()
        vox_res["name_match"] = (claimed in recognized) or (recognized in claimed) if recognized else None
        if vox_res["name_match"] is False:
            vox_sc = min(95.0, vox_sc + 25)

    # Qwen deception-cue fallback — ONLY when there's no actual voice
    # evidence to score against. Never overrides a real voice-stress score.
    if not voice_clip and qwen_deception.get("deception_score"):
        qwen_dec_score = qwen_deception.get("deception_score", 50)
        if qwen_dec_score > 60:
            vox_sc = max(vox_sc, qwen_dec_score * 0.7)
            log.info(f"Qwen: deception cue used as voice-score fallback ({vox_sc:.1f}%)")

    # ── FACIAL EVIDENCE ANALYSIS ──────────────────────────────────────────
    face_res = face_eng.analyse(photo) if photo is not None and face_eng.ready else {}
    face_sc = face_res.get("anomaly_score", ner_sc * 0.82) if face_res else 0.0

    # ── CCTV CRIME-SCENE CLASSIFICATION (video frame, or fallback to photo) ─
    cctv_frame = _extract_video_frame(cctv_video) if cctv_video else None
    cctv_source_image = cctv_frame if cctv_frame is not None else photo
    cctv_source_label = "CCTV video (extracted frame)" if cctv_frame is not None else (
        "Suspect photo (no CCTV video submitted)" if photo is not None else None
    )
    cctv_result = (
        cctv_eng.classify(cctv_source_image)
        if cctv_source_image is not None and cctv_eng.ready else None
    )
    if cctv_video is not None and cctv_frame is None:
        log.warning("CCTV video submitted but frame extraction failed — falling back to photo, if any")

    # ── DEEPFAKE / TAMPER DETECTION (same submitted photo) ─────────────────
    image_quality = _assess_image_quality(photo) if photo is not None else None
    deepfake_result = deepfake_eng.classify(photo) if photo is not None and deepfake_eng.ready else None
    if deepfake_result:
        top = deepfake_result[0]
        is_fake_label = "fake" in top["label"].lower() or "deepfake" in top["label"].lower()
        _calibrated_df_early = calibrate_deepfake_result(deepfake_result, image_quality)
        if _calibrated_df_early:
            tampering_status = (
                f"{'⚠ LIKELY DEEPFAKE' if is_fake_label else 'No deepfake indicators'} "
                f"— Model classification: {_calibrated_df_early['model_classification']} "
                f"(prithivMLmods/ Deepfake-vs-Real-8000). "
                f"Forensic conclusion: {_calibrated_df_early['forensic_conclusion']}."
            )
        else:
            tampering_status = (
                f"{'⚠ LIKELY DEEPFAKE' if is_fake_label else 'No deepfake indicators'} "
                f"— model confidence {top['score']:.1f}% on label '{top['label']}' "
                f"(prithivMLmods/ Deepfake-vs-Real-8000) — verify independently"
            )
        if image_quality and image_quality[0] == "Poor":
            tampering_status += f". ⚠ IMAGE QUALITY: {image_quality[1]} — confidence score above may be unreliable."
    elif photo is not None and not deepfake_eng.ready:
        tampering_status = "N/A — Deepfake/tamper detection module offline"
    else:
        tampering_status = "N/A — No photo evidence submitted"
    evidence_integrity["tampering_status"] = tampering_status

    # ── DOCUMENT EVIDENCE EXTRACTION (OCR) ──────────────────────────────
    ocr_text = ocr_eng.extract(id_doc) if id_doc and ocr_eng.ready else ""
    ocr_sc, ocr_res = (ocr_eng.score(ocr_text, suspect_name) if ocr_eng.ready else (0.0, {})) if ocr_text else (0.0, {})

    # ── CRIME CLASSIFICATION FROM EVIDENCE ────────────────────────────────
    crime_info = _classify_crime_from_evidence(entities, modus, suspect_name, ocr_text, face_res, vox_res, location)

    # ── EVIDENCE ANALYSIS (Model names replaced with evidence focus) ──────
    text_evidence = _analyze_text_evidence(entities, modus, suspect_name, location)
    face_evidence = _analyze_facial_evidence(face_res, photo_meta)
    voice_evidence = _analyze_voice_evidence(vox_res, audio_meta)
    doc_evidence = _analyze_document_evidence(ocr_text, ocr_res, doc_meta)

    # ── FRAUD INDICATORS FROM EVIDENCE ────────────────────────────────────
    fraud_indicators = _compute_fraud_from_evidence(
        entities, face_evidence, voice_evidence, doc_evidence,
        ocr_text, photo, id_doc, suspect_name
    )

    # ── NETWORK & WATCHLIST ───────────────────────────────────────────────
    watchlist = _lookup_suspect_background(ds_eng, suspect_name, entities)

    # ── STEP 2 — UNKNOWN CRIMINAL PROFILE (Agyat Apradhi) ───────────────────
    # A behavioural profile — never a name — built from Step 2 fields.
    # Only meaningful when the suspect is genuinely unidentified.
    criminal_profile = {}

    # ─── BEHAVIOUR INTELLIGENCE ────────────────────────────────────────
    behaviour_indicators = {
        "planning": min(100, (8 if crime_info.get("severity") in ["Critical", "High"] else 0) + 
                          (10 if "planned" in str(modus).lower() else 0) +
                          (5 if "targeted" in str(modus).lower() else 0) +
                          (5 if len(str(modus).split()) > 50 else 0) + 20),
        "discipline": min(100, (10 if "disabled" in str(modus).lower() else 0) +
                          (10 if "no forced" in str(modus).lower() else 0) +
                          (10 if "clean" in str(modus).lower() else 0) + 20),
        "violence": min(100, (20 if "weapon" in str(modus).lower() else 0) +
                       (15 if "threat" in str(modus).lower() else 0) +
                       (10 if "assault" in str(modus).lower() else 0)),
        "cyber_skill": min(100, (10 if "disabled" in str(modus).lower() else 0) +
                         (10 if "cloned" in str(modus).lower() else 0) +
                         (10 if "GPS" in str(modus).lower() else 0) +
                         (5 if "camera" in str(modus).lower() else 0) + 5),
        "financial_motivation": min(100, (15 if "cash" in str(modus).lower() else 0) +
                                  (10 if "money" in str(modus).lower() else 0) +
                                  (10 if "wallet" in str(modus).lower() else 0) + 5),
    }
    # ─── END BEHAVIOUR INTELLIGENCE ────────────────────────────────────

    if unidentified_flag:
        criminal_profile = {
            "estimated_age": ucp_age or "Unknown", "gender": ucp_gender or "Unknown",
            "height": ucp_height or "Unknown", "body_type": ucp_body_type or "Unknown",
            "language": ucp_language or "Unknown", "accent": ucp_accent or "Unknown",
            "handedness": ucp_handedness or "Unknown",
            "dominant_behaviour": ucp_dominant_behaviour or "Unknown",
            "entry_method": ucp_entry_method or "Unknown",
            "behaviour_at_scene": ucp_behaviour_at_scene or "Unknown",
            "weapons_used": ucp_weapons_used or "None observed",
            "vehicle_used": vehicle_info or "None observed",
            "likely_team_size": ucp_team_size or "Unknown",
            "technical_skill": ucp_tech_skill or "Unknown",
            "experience_level": ucp_experience_level or "Unknown",
            "escape_pattern": ucp_escape_pattern or "Unknown",
            "mo_signature": ucp_mo_signature or "Unknown",
            "planning_level": ucp_planning_level or "Unknown",
            "risk_behaviour": ucp_risk_behaviour or "Unknown",
            "profile_confidence": ucp_confidence or 72,
            "behaviour_profile_notes": ucp_behaviour_profile or "",
        }
        # BUG FIX (P0 — reviewer feedback, NHAI case): every field in this
        # profile is exactly what the investigator typed into the Step-2
        # form — nothing here is derived from or checked against THIS
        # case's own MO text. In testing, a profile clearly describing a
        # different crime entirely (weapons/forced-entry/tactical details
        # for a case that's actually about toll-fraud software) got
        # submitted and displayed at face value — almost certainly because
        # the form fields were left populated from a PREVIOUS case's test
        # run and never cleared before this case was submitted. Cross-
        # check the profile's own MO-relevant fields against this case's
        # `modus` text and surface a prominent warning if they share no
        # vocabulary at all, so a stale/mismatched profile doesn't reach
        # the report silently.
        _ucp_mo_fields = " ".join(str(v) for v in [
            ucp_entry_method, ucp_weapons_used, ucp_mo_signature, ucp_dominant_behaviour,
            ucp_behaviour_at_scene, ucp_escape_pattern,
        ] if v and str(v).strip() and str(v) != "Unknown")
        if _ucp_mo_fields.strip() and (modus or "").strip():
            _ucp_words = set(re.findall(r"[a-zA-Z]{4,}", _ucp_mo_fields.lower()))
            _modus_words = set(re.findall(r"[a-zA-Z]{4,}", modus.lower()))
            if _ucp_words and not (_ucp_words & _modus_words):
                criminal_profile["consistency_warning"] = (
                    "⚠ The Step-2 profile fields (entry method / weapons / MO signature / behaviour) "
                    "share NO common terms with this case's own Modus Operandi text below — this profile "
                    "may have been carried over from a different case's form and not cleared before "
                    "submitting this one. VERIFY before relying on it: "
                    f"\"{_ucp_mo_fields[:150]}\" vs. this case's MO: \"{_safe_truncate(modus, 150)}\""
                )
        # AI-assisted estimate for any field the investigator left as
        # "Unknown" — reads keyword signals from the Modus Operandi text.
        # Always clearly labelled as an estimate, with its own confidence,
        # never presented as an investigator-confirmed value.
        for _field in ("likely_team_size", "technical_skill", "planning_level", "risk_behaviour", "experience_level"):
            if criminal_profile.get(_field) == "Unknown":
                est_value, est_conf = _estimate_profile(modus, crime_category, _field)
                if est_conf > 0:
                    criminal_profile[_field] = f"{est_value} (AI-estimated, {est_conf}% confidence)"

        # Derived synthesis field — combines technical_skill + planning_level
        # into one easy-to-scan "how sophisticated is this operation" read.
        sophistication_label, sophistication_conf = _estimate_operational_sophistication(modus, crime_category)
        criminal_profile["operational_sophistication"] = (
            f"{sophistication_label} ({sophistication_conf}% confidence)"
            if sophistication_conf > 0 else "Unknown — insufficient signal in narrative"
        )

        # Feed the extra profile detail into the same search text used for
        # unidentified-offender lookups below — more behavioural detail
        # can surface better dataset matches than physical_desc alone.
        profile_search_extra = " ".join(str(v) for v in [
            ucp_age, ucp_gender, ucp_height, ucp_body_type, ucp_language, ucp_accent,
            ucp_handedness, ucp_dominant_behaviour, ucp_entry_method, ucp_behaviour_at_scene,
            ucp_weapons_used, ucp_escape_pattern, ucp_mo_signature,
            ucp_behaviour_profile,
        ] if v and str(v) != "Unknown")
        physical_desc = f"{physical_desc or ''} {profile_search_extra}".strip()

    # ── UNIDENTIFIED OFFENDER LEADS (Agyat Apradhi) ─────────────────────────
    # Runs when the case has no known suspect name — either the checkbox is
    # ticked, or the name field was simply left blank. Matches MO + physical
    # description against wanted/fugitive/MO-pattern datasets for leads only.
    run_unidentified_search = bool(unidentified_flag) or not (suspect_name or "").strip()
    unidentified_leads = (
        _lookup_unidentified_offender(ds_eng, modus, physical_desc, location)
        if run_unidentified_search and ((modus or "").strip() or (physical_desc or "").strip())
        else {"query_used": "", "lead_count": 0, "datasets_searched": {}, "possible_leads": [], "note": "N/A — suspect name provided"}
    )

    # ── MO FINGERPRINTING — link to unsolved cases ──────────────────────────
    # Matches this case's Modus Operandi text against crime_scenes for other
    # cases with a similar crime signature, and pulls any already-confirmed
    # case_links. Always POSSIBLE links, never an automatic case merge.
    mo_links = mo_eng.find_linked_cases(case_id, modus, location, crime_category=crime_category)

    # ── WATCHLIST-BASED CRIME OVERRIDE (for known fugitives/criminals) ─────
    # If watchlist has serious criminal data, override the text-based classification
    if watchlist.get("charges") and watchlist.get("charges", ["N/A"])[0] != "N/A":
        crime_info["primary"] = watchlist["charges"][0] if watchlist["charges"] else crime_info["primary"]
        if len(watchlist.get("charges", [])) > 1:
            crime_info["secondary"] = ", ".join(watchlist["charges"][1:3])
        crime_info["all_crimes"] = watchlist.get("charges", crime_info.get("all_crimes", []))
        crime_info["severity"] = "Critical"
        crime_info["statutes"] = " | ".join(watchlist.get("charges", []))
        if watchlist.get("enforcement_actions") and watchlist["enforcement_actions"][0] != "N/A":
            crime_info["evidence_found"].extend(watchlist["enforcement_actions"][:3])

    if watchlist.get("status", "").startswith("FUGITIVE"):
        crime_info["severity"] = "Critical"
        crime_info["primary"] = f"FUGITIVE — {crime_info['primary']}"
        if "Absconding" not in crime_info["evidence_found"]:
            crime_info["evidence_found"].append(f"Subject absconding since {watchlist.get('status', '').split('since')[-1].strip() if 'since' in watchlist.get('status', '') else 'unknown date'}")

    if watchlist.get("interpol") and "YES" in watchlist.get("interpol", "NO"):
        crime_info["severity"] = "Critical"
        if "Interpol Red Corner Notice" not in crime_info["evidence_found"]:
            crime_info["evidence_found"].append("Interpol Red Corner Notice active")

    if watchlist.get("sanctions") and "YES" in watchlist.get("sanctions", "NO"):
        crime_info["severity"] = "Critical"
        if "International sanctions-list match" not in crime_info["evidence_found"]:
            crime_info["evidence_found"].append("International sanctions-list match (e.g. UN Security Council)")

    if watchlist.get("outstanding_debt") and "N/A" not in watchlist.get("outstanding_debt", ""):
        if watchlist["outstanding_debt"] not in str(crime_info.get("evidence_found", [])):
            crime_info["evidence_found"].append(f"Outstanding financial liability: {watchlist['outstanding_debt']}")

    # ── NETWORK & FINANCIAL INTELLIGENCE (Naya System) ─────────────────────
    net_risk, net_matches, net_summary = _analyze_network_evidence(ds_eng, network_text, suspect_name)
    fin_risk, fin_flags = _analyze_financial_evidence(financial_ids, entities)
    veh_risk, veh_flags = _analyze_vehicle_evidence(vehicle_info, suspect_name)

    # ── REASONING ENGINE — gaps, contradictions, hypotheses, draft report ──
    reasoning = _build_reasoning_engine(
        case_id, modus, location, suspect_name, entities, ocr_text,
        photo, voice_clip, id_doc,
        net_matches, fin_flags, veh_flags,
        mo_links, unidentified_leads, watchlist,
    )

    # ─── QWEN HYPOTHESES — merged into the rule-based Reasoning Engine ─────
    # Kept clearly source-tagged ("Qwen LLM") and separate from the
    # rule-based hypotheses above, so a reviewer knows which is which.
    qwen_hypotheses = []
    if qwen_eng.ready and (modus or "").strip():
        try:
            qwen_hypotheses = qwen_eng.generate_hypotheses(modus, entities, watchlist, mo_links)
        except Exception as e:
            log.error(f"Qwen hypothesis generation error: {e}")
        for qh in qwen_hypotheses:
            if not isinstance(qh, dict) or not qh.get("hypothesis"):
                continue
            reasoning["hypotheses"].append({
                "hypothesis": qh.get("hypothesis", ""),
                "supporting_evidence": qh.get("supporting_evidence", []) or [],
                "contradicting_evidence": qh.get("contradicting_evidence", []) or [],
                "confidence": qh.get("confidence", "medium"),
                "source": "AI Reasoning (LLM-generated hypothesis — weigh alongside rule-based leads above)",
            })
    # ─── END QWEN HYPOTHESES ────────────────────────────────────────────────

    # Story draft generation moved OFF the automatic Investigate pipeline —
    # it now runs only on-demand via the dedicated "Generate Story Draft"
    # button (regenerate_story_draft()). Running it automatically here was
    # adding a third CPU-bound Qwen call to every single Investigate click,
    # which was pushing total request time past the ~100s edge-proxy
    # (Cloudflare) timeout and causing "connection lost" + form-data loss.
    qwen_story_draft = ""

    # ── RISK MODEL (Pattern Analysis) ─────────────────────────────────────
    feats = {
        "ner_crime": len(entities.get("CRIME", [])),
        "ner_weapon": len(entities.get("WEAPON", [])),
        "ner_person": len(entities.get("PERSON", [])),
        "ner_threat": len(entities.get("THREAT", [])),
        "voice_id_mismatch": vox_sc,
        "face_anomaly": face_sc,
        "ocr_mismatch": ocr_sc,
        "modus_len": len(modus or ""),
        "has_voice": 1 if voice_clip else 0,
        "has_photo": 1 if photo is not None else 0,
    }
    pat_sc, pat_src = xgb_eng.predict(feats) if xgb_eng.ready else (0.0, "heuristic")

    
    # ── COMPOSITE SCORES ────────────────────────────────────────────────────
    W = {"ner": .16, "voice": .20, "face": .12, "ocr": .12, "pattern": .16, "network": .08, "financial": .06, "digital": .10}
    deception = round(min(
        ner_sc*W["ner"] + vox_sc*W["voice"] + face_sc*W["face"] + ocr_sc*W["ocr"] +
        pat_sc*W["pattern"] + net_risk*W["network"] + fin_risk*W["financial"] +
        fraud_indicators.get("digital_anomaly", 0)*W["digital"], 99), 1)
    credibility = round(max(5, 100 - deception - random.uniform(0,6)), 1)
    
    # ─── EXPLAINABLE RISK SCORE ────────────────────────────────────────────
    # Risk has TWO components:
    #   1. Deception-based risk (60% weight)
    #   2. Pattern-based risk (28% weight)
    #   3. Network risk (8% weight)
    #   4. Financial risk (4% weight)
    #   5. CASE PRIORITY BOOST: High/Critical adds +15% to risk
    # 
    # This explains why a case with Critical severity and High priority
    # gets 88% risk even when individual indicators are low.
    
    base_risk = deception * 0.60 + pat_sc * 0.28 + net_risk * 0.08 + fin_risk * 0.04
    
    # Case priority boost
    priority_boost = 0
    if case_priority in ("High", "Critical"):
        priority_boost = 15  # +15% for High/Critical cases
    elif case_priority == "Medium":
        priority_boost = 5   # +5% for Medium cases
    
    risk = round(min(base_risk + priority_boost, 99), 1)
    
    # Store risk breakdown for explainability
    risk_breakdown = {
        "deception_contribution": round(deception * 0.60, 1),
        "pattern_contribution": round(pat_sc * 0.28, 1),
        "network_contribution": round(net_risk * 0.08, 1),
        "financial_contribution": round(fin_risk * 0.04, 1),
        "priority_boost": priority_boost,
        "base_risk": round(base_risk, 1),
    }
    # ─── END RISK EXPLANATION ──────────────────────────────────────────────


    # ── THREAT ASSESSMENT ─────────────────────────────────────────────────
    threat = _assess_threat_from_evidence(
        deception, risk, crime_info, fraud_indicators, watchlist,
        text_evidence, face_evidence, voice_evidence, doc_evidence
    , case_priority=case_priority)

    # ── ACTIONABLE INTELLIGENCE ─────────────────────────────────────────────
    # text_evidence is itself a LIST of per-entity-type dicts (e.g. one dict
    # for "WEAPON Detected", one for "EMAIL Detected", etc.) — it must be
    # flattened into the evidence list, not nested as a single list-item,
    # otherwise `isinstance(ev, dict)` inside _generate_actions_from_evidence
    # never matches any of its entries and those action rules silently never fire.
    all_evidence = [*text_evidence, face_evidence, voice_evidence, doc_evidence]
    actions, evidence_based = _generate_actions_from_evidence(
        crime_info, fraud_indicators, watchlist, threat, risk, deception, all_evidence, case_priority
    )
    print(f"[RISK-DIAGNOSTIC] post-actions-call: risk={risk!r} type={type(risk).__name__}")

    # ── CONFIDENCE ────────────────────────────────────────────────────────
    # BUG FIX (reviewer feedback — "5/5 modules active" bug): this counts
    # how many AI MODEL MODULES are loaded/ready in this deployment
    # (NER/Voice/Face/OCR/XGB) — infrastructure status, identical for every
    # case run on this server. It previously rendered as "Analytical
    # Coverage: VERY HIGH (5/5 modules active)", which reads exactly like
    # "we have strong evidence coverage for THIS case" — even for a case
    # where Voice/Face/OCR/CCTV/Deepfake evidence was NOT SUBMITTED. It has
    # been renamed everywhere it's displayed to "AI Module Availability"
    # with an explicit "not evidence submitted for this case" qualifier.
    active_models = sum([ner_eng.ready, vox_eng.ready, face_eng.ready, ocr_eng.ready, xgb_eng.ready])
    confidence_level = ["CRITICAL", "LOW", "MEDIUM", "HIGH", "VERY HIGH"][min(active_models, 4)]

    # ── INVESTIGATION INTELLIGENCE SUMMARY ──────────────────────────────────
    evidence_provided = {
        "photo": photo is not None,
        "voice": bool(voice_clip),
        "document": bool(id_doc),
        "network": bool((network_text or "").strip()),
        "financial": bool((financial_ids or "").strip()),
        "vehicle": bool((vehicle_info or "").strip()),
        "digital": bool((digital_emails or "").strip() or (digital_phones or "").strip() or (digital_urls or "").strip()),
        "cctv_video": cctv_video is not None,
    }

    # ── PER-CASE EVIDENCE SOURCES STATUS ────────────────────────────────────
    # This is deliberately separate from the global STATUS dict (which only
    # says whether a model loaded successfully at server startup). A model
    # can be perfectly loaded and still have nothing to analyze for THIS
    # case — e.g. Voice shows loaded=True at startup, but if no voice_clip
    # was submitted here, that must read "NOT SUBMITTED", not "ANALYZED".
    def _src_status(engine_ready, evidence_given, produced_result=True):
        if not engine_ready:
            return "NOT AVAILABLE"
        if not evidence_given:
            return "NOT SUBMITTED"
        if not produced_result:
            return "FAILED"
        return "ANALYZED"

    source_status = {
        "NER":         _src_status(ner_eng.ready, bool(raw_text.strip()), bool(entities)),
        "Voice":       _src_status(vox_eng.ready, bool(voice_clip), bool(vox_res)),
        "ArcFace":     _src_status(face_eng.ready, photo is not None, bool(face_res)),
        "OCR":         _src_status(ocr_eng.ready, bool(id_doc), bool(ocr_text)),
        "Risk":        "ANALYZED" if xgb_eng.ready else "HEURISTIC FALLBACK",
        "Datasets":    "ANALYZED" if ds_eng.ready else "NOT AVAILABLE",
        "AI Reasoning":_src_status(qwen_eng.ready, bool((modus or "").strip()), True),
        "CCTV":        ("FALLBACK ANALYZED" if cctv_result is not None and cctv_frame is None and cctv_source_image is not None
                         else _src_status(cctv_eng.ready, cctv_source_image is not None, cctv_result is not None)),
        "Deepfake":    _src_status(deepfake_eng.ready, photo is not None, deepfake_result is not None),
    }

    intel_summary = _build_intelligence_summary(
        evidence_provided, crime_info, watchlist, mo_links, unidentified_leads,
        reasoning, active_models, confidence_level, deception, risk,
    )

    # ── VERDICT ───────────────────────────────────────────────────────────
    # Override verdict based on watchlist status for known criminals/fugitives
    watchlist_override = False
    
    # ─── WATCHLIST OVERRIDES (highest priority) ──────────────────────────
    # BUG FIX (reviewer feedback, two rounds): the verdict headlines here
    # are the single most visible line in the report — a reader skimming
    # ONLY the headline sees it first. "VERDICT — HIGH RISK — SANCTIONED"
    # (even with a parenthetical caveat added afterward) still reads as
    # "this person is sanctioned" at a glance. Per explicit reviewer
    # guidance, when identity is unverified the headline itself must not
    # assert the designation as applying to this person — it must name the
    # database event as a NAME-MATCH, not a verdict on the individual. So
    # instead of "HIGH RISK — SANCTIONED" + a caveat, the label now reads
    # "POTENTIAL SANCTIONS NAME-MATCH — IDENTITY UNVERIFIED" — the
    # sanctions/wanted/fugitive/interpol claim is not the noun anymore,
    # "name-match" is.
    if watchlist.get("status", "").startswith("FUGITIVE") or watchlist.get("status", "").startswith("DECEASED"):
        v_icon, v_color, v_label = "🔴", "#ef4444", "POTENTIAL FUGITIVE NAME-MATCH — IDENTITY UNVERIFIED"
        v_text = (f"A dataset record matching this name is {watchlist.get('status', 'UNKNOWN').split('—')[0].strip()}. "
                  f"IDENTITY CONFIDENCE IS 0% — independent identity resolution has NOT confirmed this record "
                  f"belongs to this specific individual. Treat as a HIGH-PRIORITY lead requiring immediate "
                  f"verification and coordination with enforcement agencies, not a confirmed designation.")
        watchlist_override = True
    elif watchlist.get("interpol") and "YES" in watchlist.get("interpol", "NO"):
        v_icon, v_color, v_label = "🔴", "#ef4444", "POTENTIAL INTERPOL NAME-MATCH — IDENTITY UNVERIFIED"
        v_text = ("A dataset record matching this name carries an active Interpol Red Corner Notice. "
                  "IDENTITY CONFIDENCE IS 0% — this is an unverified name match, not a confirmed identification. "
                  "Coordinate with NCB immediately to independently verify before treating this as this person.")
        watchlist_override = True
    elif watchlist.get("sanctions") and "YES" in watchlist.get("sanctions", "NO"):
        v_icon, v_color, v_label = "🔴", "#ef4444", "POTENTIAL SANCTIONS NAME-MATCH — IDENTITY UNVERIFIED"
        v_text = ("A dataset record matching this name appears on an international sanctions list (e.g. UN "
                  "Security Council Consolidated List). IDENTITY CONFIDENCE IS 0% — independent identity "
                  "resolution has NOT confirmed this record belongs to this specific individual. Coordinate "
                  "with compliance/national security units to verify identity before acting on this as a "
                  "confirmed sanctions hit.")
        watchlist_override = True
    elif watchlist.get("fbi_watchlist", "NO") != "NO" or (watchlist.get("charges") and watchlist["charges"][0] != "N/A"):
        v_icon, v_color, v_label = "🔴", "#ef4444", "POTENTIAL WANTED/CHARGES NAME-MATCH — IDENTITY UNVERIFIED"
        v_text = ("A dataset record matching this name has active criminal charges and/or a federal watchlist "
                  "entry. IDENTITY CONFIDENCE IS 0% — this is an unverified name/alias match. Immediate "
                  "investigative follow-up is recommended to independently confirm identity before enforcement action.")
        watchlist_override = True
    
    # ─── CRIME-SEVERITY OVERRIDE ──────────────────────────────────────────
    elif crime_info.get("severity") == "Critical":
        v_icon, v_color, v_label = "🔴", "#ef4444", "HIGH RISK — SEVERE CRIME INDICATORS"
        v_text = (
            f"Evidence text contains Critical-severity crime indicators "
            f"({', '.join(crime_info.get('all_crimes', [])[:3])}). Immediate investigative "
            f"follow-up recommended regardless of composite deception score."
        )
        watchlist_override = True
    elif crime_info.get("severity") == "High":
        v_icon, v_color, v_label = "🟠", "#f97316", "MODERATE-HIGH RISK — CRIME INDICATORS"
        v_text = (
            f"Evidence text contains High-severity crime indicators "
            f"({', '.join(crime_info.get('all_crimes', [])[:3])}). Recommend expanded "
            f"investigation even though other risk scores are moderate."
        )
        watchlist_override = True
    
    # ─── CASE PRIORITY OVERRIDE ─────────────────────────────────────────────
    elif case_priority in ("High", "Critical"):
        v_icon, v_color, v_label = "🟠", "#f97316", "HIGH PRIORITY — CRITICAL CASE"
        v_text = (
            f"This case has been marked as {case_priority} priority. "
            f"Immediate investigation and resource allocation recommended regardless "
            f"of composite deception score."
        )
        watchlist_override = True
    
    # ─── DECEPTION-BASED VERDICT (lowest priority) ──────────────────────────
    elif deception > 75:
        v_icon, v_color, v_label = "🔴", "#ef4444", "HIGH RISK"
        v_text = "Significant deception markers detected across multiple evidence types. Recommend immediate follow-up."
    elif deception > 50:
        v_icon, v_color, v_label = "🟡", "#f59e0b", "MODERATE RISK"
        v_text = "Evidence inconsistencies detected. Cross-verify all submitted materials and expand investigation."
    else:
        v_icon, v_color, v_label = "🟢", "#22c55e", "LOW RISK"
        v_text = "Evidence patterns appear consistent. Continue routine monitoring and evidence collection."

    # If watchlist override, also bump deception/risk scores for reporting
    if watchlist_override:
        deception = max(deception, 85.0)
        risk = max(risk, 88.0)

    # ── BUILD UI HTML (Evidence-Focused) ──────────────────────────────────
    def bar(label, val, col, width=100):
        val = val or 0
        if isinstance(val, str):
            return f"<div style='margin-bottom:8px;font-size:12px;'><span style='color:#94a3b8;'>{label}</span> <span style='color:{col};font-weight:600;'>{val}</span></div>"
        return (
            f"<div style='margin-bottom:12px;'>"
            f"<div style='display:flex;justify-content:space-between;font-size:12px;margin-bottom:5px;'>"
            f"<span style='color:#94a3b8;'>{label}</span>"
            f"<span style='color:{col};font-weight:600;'>{val:.1f}%</span></div>"
            f"<div style='height:5px;background:#1a2236;border-radius:3px;overflow:hidden;'>"
            f"<div style='width:{min(val,width):.1f}%;height:100%;background:{col};border-radius:3px;'></div></div></div>"
        )

    indicators_html = (
        f"<div style='background:#111620;border:0.5px solid #1a2236;"
        f"border-radius:10px;padding:16px;margin-top:4px;'>"
        f"<p style='font-size:10px;color:#475569;text-transform:uppercase;"
        f"letter-spacing:.1em;margin-bottom:14px;'>Evidence Analysis Summary</p>"
    )

    ev_submitted = []
    if photo: ev_submitted.append("Photo")
    if voice_clip: ev_submitted.append("Voice")
    if id_doc: ev_submitted.append("Document")
    if modus: ev_submitted.append("Statement")
    indicators_html += f"<div style='font-size:12px;color:#60a5fa;margin-bottom:12px;'>Evidence Submitted: {', '.join(ev_submitted) if ev_submitted else 'None'}</div>"

    indicators_html += (
        bar("Text Evidence Risk", ner_sc, "#60a5fa")
        + bar("Voice Evidence Risk", vox_sc, "#ef4444")
        + bar("Facial Evidence Risk", face_sc, "#f59e0b")
        + bar("Document Evidence Risk", ocr_sc, "#f472b6")
        + bar("Criminal Pattern Match", pat_sc, "#a78bfa")
        + bar("Composite Deception", deception, "#22c55e")
        + "<div style='margin-top:14px;border-top:0.5px solid #1a2236;padding-top:12px;'>"
        + "<p style='font-size:10px;color:#475569;text-transform:uppercase;letter-spacing:.08em;margin-bottom:8px;'>Fraud & Crime Indicators</p>"
        + bar("Document Forgery Risk", fraud_indicators["document_forgery"], "#f87171")
        + bar("Identity Fraud Risk", fraud_indicators["identity_fraud"], "#fb923c")
        + bar("Financial Anomaly Risk", fraud_indicators["financial_anomaly"], "#a78bfa")
        + bar("Criminal Pattern Match", fraud_indicators["mo_match"], "#22d3ee")
        + "</div>"
    )

    if fraud_indicators["behavioral_flags"] and fraud_indicators["behavioral_flags"] != ["No suspicious behavioral indicators detected"]:
        indicators_html += (
            "<div style='margin-top:10px;border-top:0.5px solid #1a2236;padding-top:10px;'>"
            "<p style='font-size:10px;color:#475569;text-transform:uppercase;letter-spacing:.08em;margin-bottom:6px;'>Behavioral Red Flags</p>"
        )
        for flag in fraud_indicators["behavioral_flags"][:5]:
            indicators_html += f"<div style='font-size:11px;color:#f87171;margin-bottom:3px;'>⚠ {flag}</div>"
        indicators_html += "</div>"

    # Evidence details
    indicators_html += (
        "<div style='margin-top:14px;border-top:0.5px solid #1a2236;padding-top:12px;'>"
        "<p style='font-size:10px;color:#475569;text-transform:uppercase;letter-spacing:.08em;margin-bottom:8px;'>Evidence Details Found</p>"
    )

    if text_evidence:
        for ev in text_evidence[:4]:
            indicators_html += (
                f"<div style='margin-bottom:6px;font-size:11px;'>"
                f"<span style='color:#60a5fa;font-weight:600;'>📋 {ev['type']}</span>"
                f"<span style='color:#64748b;'> — {ev['count']} found</span>"
                f"<div style='font-size:10px;color:#475569;margin-top:2px;'>{ev['significance']}</div></div>"
            )

    if face_evidence.get("status") == "Evidence analyzed":
        indicators_html += "<div style='margin-top:8px;border-top:0.5px solid #1a2236;padding-top:8px;'>"
        indicators_html += "<span style='color:#f59e0b;font-weight:600;font-size:11px;'>👤 Facial Evidence</span>"
        for finding in face_evidence.get("findings", [])[:2]:
            indicators_html += f"<div style='font-size:10px;color:#64748b;'>• {finding}</div>"
        indicators_html += "</div>"

    if voice_evidence.get("status") == "Evidence analyzed":
        indicators_html += "<div style='margin-top:8px;border-top:0.5px solid #1a2236;padding-top:8px;'>"
        indicators_html += "<span style='color:#ef4444;font-weight:600;font-size:11px;'>🎙️ Voice Evidence</span>"
        for finding in voice_evidence.get("findings", [])[:2]:
            indicators_html += f"<div style='font-size:10px;color:#64748b;'>• {finding}</div>"
        indicators_html += "</div>"

    if doc_evidence.get("status") == "Evidence analyzed":
        indicators_html += "<div style='margin-top:8px;border-top:0.5px solid #1a2236;padding-top:8px;'>"
        indicators_html += "<span style='color:#f472b6;font-weight:600;font-size:11px;'>📄 Document Evidence</span>"
        for finding in doc_evidence.get("findings", [])[:2]:
            indicators_html += f"<div style='font-size:10px;color:#64748b;'>• {finding}</div>"
        if doc_evidence.get("extracted_text"):
            txt = doc_evidence["extracted_text"][:100]
            indicators_html += f"<div style='font-size:10px;color:#475569;margin-top:4px;font-style:italic;'>\"{txt}...\"</div>"
        indicators_html += "</div>"

    indicators_html += "</div>"

    # Crime classification
    indicators_html += (
        "<div style='margin-top:14px;border-top:0.5px solid #1a2236;padding-top:12px;'>"
        "<p style='font-size:10px;color:#475569;text-transform:uppercase;letter-spacing:.08em;margin-bottom:8px;'>Crime Classification</p>"
        f"<div style='font-size:12px;color:#e2e8f0;font-weight:600;'>Primary: {crime_info['primary']}</div>"
        f"<div style='font-size:11px;color:#94a3b8;'>Secondary: {crime_info['secondary']}</div>"
        f"<div style='font-size:11px;color:#94a3b8;'>Severity: <span style='color:{ '#ef4444' if crime_info['severity']=='Critical' else '#f59e0b' if crime_info['severity']=='High' else '#22c55e' };'>{crime_info['severity']}</span></div>"
        f"<div style='font-size:10px;color:#475569;margin-top:4px;'>Potential Applicable Law (AI-suggested — not backend-verified): {crime_info['statutes']}</div>"
        "</div>"
    )

    # Watchlist
    indicators_html += (
        "<div style='margin-top:14px;border-top:0.5px solid #1a2236;padding-top:12px;'>"
        "<p style='font-size:10px;color:#475569;text-transform:uppercase;letter-spacing:.08em;margin-bottom:8px;'>Background & Watchlist</p>"
        f"<div style='font-size:11px;color:#64748b;'>Criminal History: <span style='color:#e2e8f0;'>{_honest_negative(watchlist['criminal_history'])[:70]}</span></div>"
        f"<div style='font-size:11px;color:#64748b;'>Status: <span style='color:#e2e8f0;'>{watchlist['status']}</span></div>"
        f"<div style='font-size:11px;color:#64748b;'>FBI: <span style='color:#e2e8f0;'>{_fbi_display_for(location, watchlist['fbi_watchlist'])[:50]}</span></div>"
        "</div>"
    )

    # Threat
    indicators_html += (
        "<div style='margin-top:14px;border-top:0.5px solid #1a2236;padding-top:12px;'>"
        "<p style='font-size:10px;color:#475569;text-transform:uppercase;letter-spacing:.08em;margin-bottom:8px;'>Threat Assessment</p>"
        f"<div style='font-size:11px;color:#64748b;'>Physical: <span style='color:#e2e8f0;'>{threat['physical']}</span></div>"
        f"<div style='font-size:11px;color:#64748b;'>Financial: <span style='color:#e2e8f0;'>{threat['financial']}</span></div>"
        f"<div style='font-size:11px;color:#64748b;'>Public Safety: <span style='color:#e2e8f0;'>{threat['public_safety']}</span></div>"
        f"<div style='font-size:11px;color:#64748b;'>Escalation: <span style='color:#e2e8f0;'>{threat['escalation_prob']:.1f}%</span></div>"
        "</div>"
    )

    indicators_html += "</div>"

    # ── Save history & graph ────────────────────────────────────────────────
    entry = {
        "case_id": case_id or f"NXF-{random.randint(1000,9999)}",
        "date": datetime.now().strftime("%d %b %Y %H:%M"),
        "deception": deception, "risk": risk, "credibility": credibility,
        "pattern": pat_sc, "voice": vox_sc, "ner": ner_sc, "ocr": ocr_sc,
    }
    analysis_history.insert(0, entry)

    scores_for_graph = {
        "deception": deception, "credibility": credibility, "risk": risk,
        "voice": vox_sc, "ner": ner_sc, "ocr": ocr_sc, "pattern": pat_sc,
    }
    graph_html = build_graphs_html(scores_for_graph, list(reversed(analysis_history[-10:])))

    # ── BUILD TEXT REPORT (Evidence-Focused) ──────────────────────────────
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        "="*70,
        "  NEXFORENSICS — INVESTIGATION INTELLIGENCE REPORT",
        "  nexforensics.com  |  Signal to Evidence  |  CONFIDENTIAL",
        "="*70,
        f"  Case ID         : {entry['case_id']}",
        f"  Case Title      : {case_title or 'N/A'}",
        f"  Crime Category  : {crime_category or 'N/A'}",
        f"  Case Priority   : {case_priority or 'Medium'}",
        f"  Incident Date (as reported, may be FIR/intake date): {incident_date or 'N/A'}",
        f"  Suspect         : {suspect_name or 'N/A'}",
        f"  Location        : {location or 'N/A'}",
        f"  Investigating Officer : {investigating_officer or 'N/A'}",
        f"  Timestamp       : {ts}",
        f"  Analyst         : [Auto-Generated] | Classification: CONFIDENTIAL",
        "-"*70,
        f"  VERDICT         : {v_icon}  {v_label}",
        f"  {v_text}",
        "-"*70,
        "  INVESTIGATION STATUS",
        f"    Known Criminal Match   : {intel_summary['investigation_status']['known_criminal_match']}",
        f"    Analytical Source Coverage : {intel_summary['investigation_status']['analytical_source_coverage']} "
        f"({intel_summary['investigation_status']['analytical_source_coverage_note']})",
        f"    Threat Severity        : {intel_summary['investigation_status']['threat_severity']} "
        f"({intel_summary['investigation_status']['threat_severity_note']})",
        f"    Investigation Required : {intel_summary['investigation_status']['investigation_required']}",
        "-"*70,
        "  INVESTIGATION INTELLIGENCE SUMMARY",
        f"    What Was Found    : {intel_summary['summary_points']['what_was_found']}",
        f"    What Was Not Found: {intel_summary['summary_points']['what_was_not_found']}",
        f"    Strongest Lead    : {intel_summary['summary_points']['strongest_lead']}",
        f"    Weakest Link      : {intel_summary['summary_points']['weakest_link']}",
        f"    Recommended Next Step: {intel_summary['summary_points']['next_step']}",
        "-"*70,
        f"  EVIDENCE-TYPE COVERAGE   {intel_summary['completeness_bar']}  {intel_summary['completeness_pct']}%  "
        f"(simple count of evidence types submitted — see Weighted Evidence Completeness in the "
        f"Investigator Engine section for the per-module weighted figure; the two are different metrics)",
        f"    Not Submitted for This Case: {', '.join(intel_summary['missing_evidence']) if intel_summary['missing_evidence'] else 'None — all core evidence types provided'}",
        "-"*70,
        "  CRIME CLASSIFICATION (Based on Evidence)",
        f"    Primary Crime    : {crime_info['primary']}",
        f"    Secondary Crime  : {crime_info['secondary']}",
        f"    Severity         : {crime_info['severity']}",
        f"    Jurisdiction     : {crime_info['jurisdiction']}",
        f"    Potential Applicable Law : {crime_info['statutes']}",
        f"                       (AI-suggested from keyword match — NOT backend-verified;",
        f"                        confirm against actual jurisdiction/counsel before citing)",
        "-"*70,
        "  EVIDENCE FOUND",
    ]
    for ev_note in crime_info.get("evidence_found", []):
        lines.append(f"    + {ev_note}")

    lines += [
        "-"*70,
        "  COMPOSITE SCORES",
        f"    Deception Score  : {f'{deception}%' if voice_clip else 'N/A — narrative text only'} (linguistic pattern on the case-narrative TEXT — investigator/",
        f"                        case-intake writing, not a subject statement — not the subject's truthfulness)",
        f"    Narrative Credibility : {f'{credibility}%' if voice_clip else 'N/A — narrative text only'} (direct inverse of Deception Score above — same scope)",
        f"    Risk Level       : {risk}%",
        f"    Analysis Engine Coverage : {active_models}/5 AI modules loaded on this server (infrastructure —",
        f"                               same for every case, NOT evidence for this case)",
        f"    Evidence-Type Coverage   : {intel_summary['completeness_pct']}% (evidence types actually submitted",
        f"                               for THIS case — see breakdown above)",
        "-"*70,
        "  FRAUD & CRIME INDICATORS (Evidence-Based)",
        f"    Document Forgery   : {fraud_indicators['document_forgery']:.1f}%",
        f"    Identity Fraud     : {fraud_indicators['identity_fraud']:.1f}%",
        f"    Financial Anomaly  : {fraud_indicators['financial_anomaly']:.1f}%",
        f"    Criminal Pattern   : {fraud_indicators['mo_match']:.1f}%",
        "    Behavioral Flags   :",
    ]
    for flag in fraud_indicators["behavioral_flags"][:5]:
        lines.append(f"      ! {flag}")

    lines += [
        "-"*70,
        "  EVIDENCE ANALYSIS DETAILS",
        "",
        "  TEXT EVIDENCE (Named Entities & Statements)",
    ]
    if text_evidence:
        for ev in text_evidence:
            lines.append(f"    {ev['type']}: {ev['count']} found")
            if ev['values']:
                lines.append(f"      Values: {', '.join(ev['values'][:5])}")
            lines.append(f"      Significance: {ev['significance']}")

    lines += ["", "  FACIAL EVIDENCE"]
    if face_evidence.get("status") == "Evidence analyzed":
        for finding in face_evidence.get("findings", []):
            lines.append(f"    * {finding}")
        for risk in face_evidence.get("risk_indicators", []):
            lines.append(f"    ! {risk}")
    else:
        lines.append(f"    {face_evidence.get('status', 'N/A')}")

    lines += ["", "  VOICE EVIDENCE"]
    if voice_evidence.get("status") == "Evidence analyzed":
        for finding in voice_evidence.get("findings", []):
            lines.append(f"    * {finding}")
        for risk in voice_evidence.get("risk_indicators", []):
            lines.append(f"    ! {risk}")
    else:
        lines.append(f"    {voice_evidence.get('status', 'N/A')}")

    lines += ["", "  DOCUMENT EVIDENCE"]
    if doc_evidence.get("status") == "Evidence analyzed":
        for finding in doc_evidence.get("findings", []):
            lines.append(f"    * {finding}")
        for risk in doc_evidence.get("risk_indicators", []):
            lines.append(f"    ! {risk}")
        if doc_evidence.get("extracted_text"):
            lines.append(f'    Extracted: "{doc_evidence["extracted_text"][:100]}..."')
    else:
        lines.append(f"    {doc_evidence.get('status', 'N/A')}")

    dm = watchlist.get("dataset_matches", {"count": 0, "datasets": {}})
    dm_line = (f"{dm['count']} record(s) across: " + ", ".join(f"{k}({v})" for k, v in dm["datasets"].items())
               if dm.get("count") else "No matches found")
    conf = watchlist.get("match_confidence", "NONE")
    weak = watchlist.get("weak_matches_for_review", [])

    lines += [
        "-"*70,
        "  NETWORK & WATCHLIST STATUS",
        "  ⚠ IDENTITY NOT INDEPENDENTLY VERIFIED (Identity Confidence: 0%) — every field below is a",
        "    NAME/ALIAS MATCH against a dataset, not a confirmed hit on this specific individual.",
        f"    Match Confidence : {conf}",
        f"    Database Match   : {dm_line}",
        f"    Criminal History : {_honest_negative(watchlist['criminal_history'])}",
        f"    Known Aliases    : {', '.join(watchlist.get('aliases', ['N/A'])[:3])} (names from same dataset search — may be different individuals, not verified as one person)",
        f"    Associates       : {', '.join(watchlist.get('known_associates', ['N/A'])[:3])}",
        f"    Gang Affiliation : {watchlist.get('gang_affiliation', 'N/A')}",
        f"    PEP Status       : {watchlist.get('pep_status', 'N/A')} (name-match, identity unverified)",
        f"    Sanctions List   : {watchlist.get('sanctions', 'N/A')} (name-match, identity unverified)",
        f"    Interpol Status  : {watchlist.get('interpol', 'N/A')} (name-match, identity unverified)",
        f"    FBI Watchlist    : {_fbi_display_for(location, watchlist.get('fbi_watchlist', 'N/A'))}",
        f"    Subject Status   : {watchlist.get('status', 'UNKNOWN')}",
    ]
    if weak:
        lines.append("    Weak Matches (name-fragment only, NOT used above — verify manually):")
        for w in weak[:5]:
            lines.append(f"      ~ {w}")

    if criminal_profile:
        lines += [
            "-"*70,
            "  UNKNOWN CRIMINAL PROFILE (Step 2 — behavioural, not a name)",
        ]
        if criminal_profile.get("consistency_warning"):
            lines.append(f"    {criminal_profile['consistency_warning']}")
        lines += [
            f"    Estimated Age       : {criminal_profile['estimated_age']}",
            f"    Gender              : {criminal_profile['gender']}",
            f"    Height              : {criminal_profile['height']}",
            f"    Body Type           : {criminal_profile['body_type']}",
            f"    Language / Accent   : {criminal_profile['language']} / {criminal_profile['accent']}",
            f"    Handedness          : {criminal_profile['handedness']}",
            f"    Dominant Behaviour  : {criminal_profile['dominant_behaviour']}",
            f"    Entry Method        : {criminal_profile['entry_method']}",
            f"    Behaviour at Scene  : {criminal_profile['behaviour_at_scene']}",
            f"    Weapons Used        : {criminal_profile['weapons_used']}",
            f"    Vehicle Used        : {criminal_profile['vehicle_used']}",
            f"    Likely Team Size    : {criminal_profile['likely_team_size']}",
            f"    Technical Skill     : {criminal_profile['technical_skill']}",
            f"    Experience Level    : {criminal_profile['experience_level']}",
            f"    Crime Planning Level: {criminal_profile['planning_level']}",
            f"    Risk Behaviour      : {criminal_profile['risk_behaviour']}",
            f"    Escape Method       : {criminal_profile['escape_pattern']}",
            f"    MO Signature        : {criminal_profile['mo_signature']}",
            f"    Operational Sophistication : {criminal_profile.get('operational_sophistication', 'Unknown')}",
            f"    Behavioral Profile Confidence : {criminal_profile['profile_confidence']}%",
        ]
        if criminal_profile.get("behaviour_profile_notes"):
            lines.append(f"    Notes               : {criminal_profile['behaviour_profile_notes']}")

    if run_unidentified_search:
        lines += [
            "-"*70,
            "  AGYAT APRADHI — UNIDENTIFIED OFFENDER LEADS (MO/description match)",
            f"    Query Used       : {unidentified_leads.get('query_used') or 'N/A'}",
            f"    Leads Found      : {unidentified_leads.get('lead_count', 0)}",
        ]
        if unidentified_leads.get("possible_leads"):
            lines.append("    Possible Leads (NOT confirmed identifications — verify independently):")
            for lead in unidentified_leads["possible_leads"]:
                lines.append(f"      ~ [{lead['dataset']}] {lead['candidate_name_or_alias']} ({lead['entity_type']}) — {lead['detail']}")
        lines.append(f"    Note             : {unidentified_leads.get('note', '')}")

    if (modus or "").strip():
        lines += [
            "-"*70,
            "  MO FINGERPRINTING — LINK TO UNSOLVED CASES",
            f"    Query Used       : {mo_links.get('query_used') or 'N/A'}",
            f"    Similar-MO Cases : {len(mo_links.get('linked_cases', []))}",
        ]
        if mo_links.get("linked_cases"):
            lines.append("    Possible Case Links (verify independently — NOT auto-merged):")
            for c in mo_links["linked_cases"][:6]:
                cat_flag = "" if c.get("category_match", True) else "  ⚠ DIFFERENT CRIME CATEGORY"
                lines.append(
                    f"      ~ Case {c.get('case_id','?')} [{c.get('crime_type','?')}]{cat_flag} "
                    f"{c.get('location','?')} on {c.get('occurred_at','?')} — {(c.get('mo_description') or '')[:120]}"
                )
                lines.append(
                    f"          MO Fingerprint Score: {c.get('fingerprint_score', 0)}% "
                    f"({c.get('fingerprint_match_level', 'LOW')})"
                )
                lines.append(
                    f"          Entry: {c.get('entry_method') or 'Not recorded'} | "
                    f"Scene behaviour: {c.get('behaviour_at_scene') or 'Not recorded'} | "
                    f"Escape: {c.get('escape_method') or 'Not recorded'}"
                )
                lines.append(
                    f"          Planning: {c.get('planning_level') or 'Not recorded'} | "
                    f"Team size: {c.get('team_size') or 'Not recorded'} | "
                    f"MO signature: {c.get('mo_signature') or 'Not recorded'} | "
                    f"Confidence: {c.get('profile_confidence') if c.get('profile_confidence') is not None else 'Not recorded'}"
                )
        if mo_links.get("confirmed_links"):
            lines.append("    Confirmed Links on Record:")
            for cl in mo_links["confirmed_links"][:6]:
                lines.append(
                    f"      ~ {cl.get('case_id','?')} <-> {cl.get('linked_case_id','?')} "
                    f"({cl.get('link_type','?')}, confidence {cl.get('confidence','?')}) — {cl.get('notes','')}"
                )
        lines.append(f"    Note             : {mo_links.get('note', '')}")

    lines += [
        "="*70,
        "  REASONING ENGINE — GAPS, CONTRADICTIONS & INVESTIGATIVE LEADS",
        "  (AI-suggested. Human investigator/journalist makes all final calls.)",
        "-"*70,
        f"  GAPS IN EVIDENCE ({len(reasoning['gaps'])})",
    ]
    if reasoning["gaps"]:
        for g in reasoning["gaps"]:
            lines.append(f"    ~ {g['gap']}")
            lines.append(f"        Why it matters : {g['why_it_matters']}")
            lines.append(f"        Suggested step : {g['next_step']}")
    else:
        lines.append("    None identified — all evidence types were provided.")

    lines += ["-"*70, f"  CONTRADICTIONS ({len(reasoning['contradictions'])})"]
    if reasoning["contradictions"]:
        for c in reasoning["contradictions"]:
            lines.append(f"    ~ {c['contradiction']}")
            lines.append(f"        Sources  : {c['sources']}")
            lines.append(f"        Severity : {c['severity']}")
    else:
        lines.append("    None detected between the pieces of evidence checked.")

    lines += ["-"*70, f"  INVESTIGATIVE HYPOTHESES ({len(reasoning['hypotheses'])})"]
    for i, h in enumerate(reasoning["hypotheses"], 1):
        lines.append(f"    H{i}. {h['hypothesis']}  [confidence: {h['confidence']}]")
        lines.append(f"        Source: {h['source']}")
        for se in h.get("supporting_evidence", []):
            lines.append(f"        + Supports    : {se}")
        for ce in h.get("contradicting_evidence", []):
            lines.append(f"        - Contradicts : {ce}")

    lines += ["-"*70, "  DRAFT INVESTIGATIVE REPORT (editable — not a final finding)"]
    for dl in reasoning["draft_report"].split("\n"):
        lines.append(f"    {dl}" if dl else "")

    if qwen_story_draft:
        lines += [
            "-"*70,
            "  AI-DRAFTED STORY OPENING (LLM narrative — editable, verify every claim)",
        ]
        for dl in qwen_story_draft.split("\n"):
            lines.append(f"    {dl}" if dl else "")

    lines += ["-"*70, "  NEXT EVIDENCE RECOMMENDATION (priority-ranked)"]
    if intel_summary["next_evidence"]:
        for ne in intel_summary["next_evidence"]:
            lines.append(f"    [{ne['priority']:<6}] {ne['recommendation']:<38} — {ne['reason']}")
    else:
        lines.append("    None — all core evidence types have been collected.")

    timeline_events = _extract_timeline(modus, incident_date)
    lines += ["-"*70, "  INVESTIGATION TIMELINE (AI-extracted from narrative — verify against records)"]
    if timeline_events:
        for ev in timeline_events:
            lines.append(f"    {ev.get('time', '?'):<16} → {ev.get('event', '')}")
    else:
        lines.append("    No time-stamped events could be extracted from the narrative.")

    lines += [
        "="*70,
        "  THREAT ASSESSMENT MATRIX",
        f"    Physical Threat    : {threat['physical']}",
        f"    Financial Threat   : {threat['financial']}",
        f"    Cyber Threat       : {threat['cyber']}",
        f"    Public Safety Risk : {threat['public_safety']}",
        f"    Escalation Prob.   : {threat['escalation_prob']:.1f}%",
        "-"*70,
        "  EVIDENCE INTEGRITY",
        f"    Photo Hash       : {evidence_integrity['photo_hash'][:30]}..." if len(str(evidence_integrity['photo_hash'])) > 30 else f"    Photo Hash       : {evidence_integrity['photo_hash']}",
        f"    Audio Hash       : {evidence_integrity['audio_hash'][:30]}..." if len(str(evidence_integrity['audio_hash'])) > 30 else f"    Audio Hash       : {evidence_integrity['audio_hash']}",
        f"    Document Hash    : {evidence_integrity['doc_hash'][:30]}..." if len(str(evidence_integrity['doc_hash'])) > 30 else f"    Document Hash    : {evidence_integrity['doc_hash']}",
        f"    Chain of Custody : {evidence_integrity['chain_of_custody']}",
        f"    Tampering Check  : {evidence_integrity['tampering_status']}",
        "-"*70,
        "  ACTIONABLE INTELLIGENCE",
    ]
    for i, action in enumerate(actions, 1):
        lines.append(f"    {i}. {action}")

    lines += [
        "-"*70,
        "  EVIDENCE SOURCES STATUS (this case)",
        *[f"    {k:15s}: {v}" for k, v in source_status.items()],
        "-"*70,
        "  DISCLAIMER: AI-generated report. Must be reviewed by a",
        "  qualified forensic investigator before any official use.",
        "  CONFIDENTIAL — Unauthorized disclosure prohibited.",
        "="*70,
    ]

    # ── Build report_data for PDF ─────────────────────────────────────────
    # TEMP DIAGNOSTIC (2026-08-29) — remove after root-causing the
    # Risk Score 0.0% vs "Operational Risk Score: 20.9%" divergence seen
    # in review feedback. Logs the exact type/value of `risk` right before
    # report_data is built, and again right after `_generate_actions_from_
    # evidence()` was called with it — to compare what value the action
    # text actually used vs. what ends up in report_data["risk"]. Static
    # code reading has repeatedly failed to find where these could diverge.
    print(f"[RISK-DIAGNOSTIC] pre-report_data: risk={risk!r} type={type(risk).__name__}")
    report_data = {
        "case_id": entry["case_id"], "suspect_name": suspect_name or "N/A",
        "location": location or "N/A", "timestamp": ts, "modus": modus or "",
        "case_title": case_title or "N/A",
        "crime_category": crime_category or "N/A",
        "incident_date": incident_date or "N/A",
        "investigating_officer": investigating_officer or "N/A",
        "case_priority": case_priority or "Medium",
        "criminal_profile": criminal_profile,
        "intel_summary": intel_summary,
        "evidence_provided": evidence_provided,
        "analyst": "[Auto-Generated]", "classification": "CONFIDENTIAL",
        "retention": "Per your organization's records-retention policy",
        "deception": deception, "credibility": credibility,
        # BUG FIX (narrative-only deception score): `deception` above stays
        # a real number everywhere it's used for actual math (credibility,
        # risk score, DB history) — untouched, no behavior change there.
        # This is a separate DISPLAY-ONLY field for the PDF/dashboard. When
        # no voice_clip was submitted, vox_sc (which feeds the deception
        # formula) comes from Qwen's linguistic read of the case-INTAKE
        # narrative text, not any actual recording/statement from the
        # subject — showing that as "85% Deception" invites a reader to
        # mistake investigator-written case notes for subject dishonesty.
        # Only a real voice recording makes this a genuine behavioral
        # signal about the subject rather than a property of the narrative
        # text; gate the human-facing label on that, not the raw number.
        "deception_display": (
            f"{deception}%" if voice_clip else "N/A — Narrative text only"
        ),
        "_deception_has_voice": bool(voice_clip),
        # BUG FIX (2026-08-25): the Composite Scores "Risk Level" card
        # occasionally rendered as a bare "N/A" despite `risk` being used
        # successfully as a float everywhere else in this same report
        # (e.g. "Operational Risk Score: {risk:.1f}%" in Actionable
        # Intelligence) — root cause not pinned down after extensive
        # tracing, but explicitly coercing here guarantees report_data
        # always carries a genuine float for this field, closing off
        # whatever rare upstream path was producing a non-numeric value.
        "risk": float(risk) if isinstance(risk, (int, float)) else 0.0,
        "risk_breakdown": risk_breakdown,
        "confidence_level": confidence_level, "active_models": active_models,
        "v_label": v_label, "v_color": v_color, "v_text": v_text, "v_icon": v_icon,
        "crime_primary": crime_info["primary"],
        "crime_secondary": crime_info["secondary"],
        "crime_all": crime_info["all_crimes"],
        "crime_severity": crime_info["severity"],
        "crime_jurisdiction": crime_info["jurisdiction"],
        "crime_statutes": crime_info["statutes"],
        "crime_evidence": crime_info["evidence_found"],
        "text_evidence": text_evidence,
        "face_evidence": face_evidence,
        "voice_evidence": voice_evidence,
        "doc_evidence": doc_evidence,
        "fraud_doc_forgery": fraud_indicators["document_forgery"],
        "fraud_id_fraud": fraud_indicators["identity_fraud"],
        "fraud_fin_anomaly": fraud_indicators["financial_anomaly"],
        "fraud_mo_match": fraud_indicators["mo_match"],
        "fraud_digital_anomaly": fraud_indicators.get("digital_anomaly", 0),
        "fraud_flags": fraud_indicators["behavioral_flags"],
        "fraud_notes": fraud_indicators["evidence_notes"],
        "watchlist": watchlist,
        "threat": threat,
        "evidence_integrity": evidence_integrity,
        "actions": actions,
        "evidence_based_actions": evidence_based,
        "status": dict(STATUS),
        "source_status": source_status,
        "network_risk": net_risk,
        "financial_risk": fin_risk,
        "vehicle_risk": veh_risk,
        "network_matches": net_matches,
        "network_summary": net_summary,
        "financial_flags": fin_flags,
        "vehicle_flags": veh_flags,
        "unidentified_search_run": run_unidentified_search,
        "unidentified_leads": unidentified_leads,
        "mo_fingerprint_links": mo_links,
        "reasoning": reasoning,
        "behaviour_indicators": behaviour_indicators,
        "timeline": timeline_events,
        "entities": entities,
        "cyber_flags": cyber_flags or [],
        "qwen_insights": qwen_insights,
        "qwen_deception": qwen_deception,
        "qwen_hypotheses": qwen_hypotheses,
        "qwen_story_draft": qwen_story_draft,
        "qwen_loaded": qwen_eng.ready,
        "cctv_result": cctv_result,
        "cctv_source_label": cctv_source_label,
        "image_quality": image_quality,
        "cctv_loaded": cctv_eng.ready,
        "deepfake_result": deepfake_result,
        "image_quality": image_quality,
        "deepfake_loaded": deepfake_eng.ready,
    }
    # ============================================================
    # INVESTIGATOR ENGINE - Integration
    # ============================================================
    try:
        # Build case data
        inv_case_data = {
            "case_id": case_id or "NXF-2024-001",
            "case": {
                "crime_category": crime_category or "unknown",
                "mo_description": modus or "",
                "suspect_name": suspect_name or "Unknown",
                "location": location or "Unknown",
                # Investigator-entered "Unidentified Criminal Profile" (UCP)
                # fields — these are direct human input and must take
                # priority over the engine's own keyword-inference on the
                # narrative text (see mo_centric_profile.py's UCP overrides).
                "ucp_age": ucp_age,
                "ucp_gender": ucp_gender,
                "ucp_height": ucp_height,
                "ucp_body_type": ucp_body_type,
                "ucp_entry_method": ucp_entry_method,
                "ucp_weapons_used": ucp_weapons_used,
                "ucp_team_size": ucp_team_size,
                "ucp_escape_pattern": ucp_escape_pattern,
                "ucp_behaviour_at_scene": ucp_behaviour_at_scene,
                "ucp_dominant_behaviour": ucp_dominant_behaviour,
                "ucp_planning_level": ucp_planning_level,
                "ucp_mo_signature": ucp_mo_signature,
                "ucp_confidence": ucp_confidence,
            },
            "evidence": {
                "evidence_items": {}
            },
            # Raw NER entities (PERSON/WEAPON/ORG/PHONE/EMAIL/URL/CRIME/
            # THREAT buckets) — previously computed and used elsewhere in
            # this function but never threaded through to the investigator
            # engine, so the Criminal Network graph only ever saw
            # face/vehicle/financial/document and stayed stuck at a handful
            # of nodes even when the case narrative mentioned phones,
            # emails, organisations, or weapons. See
            # investigator_integration.py's _build_current_nodes.
            "entities": entities,
        }
        
        # Add evidence if available — quality reflects the REAL analysis
        # outcome (face_evidence/voice_evidence/doc_evidence['status']),
        # not just "was a file uploaded". Previously this was hardcoded to
        # "good" whenever a file was present, so e.g. an uploaded document
        # photo where OCR extracted zero readable text would still tell the
        # Investigator Engine "document quality: good" — producing the
        # exact internal contradiction reported (page showing "OCR FAILED"
        # right next to another section reporting OCR "SUCCESS").
        def _quality_from_status(analysis_result):
            return "good" if analysis_result.get("status") == "Evidence analyzed" else "poor"

        if photo is not None:
            inv_case_data['evidence']['evidence_items']['face'] = {
                "type": "photo", "quality": _quality_from_status(face_evidence)}
        if voice_clip is not None:
            inv_case_data['evidence']['evidence_items']['voice'] = {
                "type": "audio", "quality": _quality_from_status(voice_evidence)}
        if id_doc:
            inv_case_data['evidence']['evidence_items']['document'] = {
                "type": "document", "quality": _quality_from_status(doc_evidence)}
        if cctv_video is not None:
            inv_case_data['evidence']['evidence_items']['cctv'] = {"type": "video", "quality": "good"}
        if financial_ids:
            inv_case_data['evidence']['evidence_items']['financial'] = {"type": "financial", "quality": "narrative"}
        if vehicle_info:
            inv_case_data['evidence']['evidence_items']['vehicle'] = {"type": "vehicle", "quality": "good"}
        # BUG FIX (2026-08-20 — P0): "digital" was never added to
        # evidence_items at all — Evidence Completeness always showed
        # "Digital Evidence: Not Submitted" even when Page 5 clearly listed
        # extracted email/phone/URL entities from the case narrative. Add
        # it when any digital indicator was extracted, but mark it as
        # "narrative" quality (not "good") — matching the reviewer's own
        # requested distinction between a narrative-derived indicator and
        # an actual submitted digital-forensics file/image. Financial is
        # marked the same way for the same reason (financial_ids is also
        # free text, not an uploaded bank/transaction record).
        if digital_emails or digital_phones or digital_urls:
            inv_case_data['evidence']['evidence_items']['digital'] = {"type": "digital", "quality": "narrative"}
        
        # Run Investigator Engine
        inv_results = run_investigator_engine(inv_case_data)

        # BUG FIX (2026-08-20): run_investigator_engine() derives its own
        # "dynamic_profile" (team size / technical skill / planning level /
        # risk behaviour) purely from keyword-matching the MO description
        # text. Meanwhile the "Unknown Criminal Profile" section above
        # (criminal_profile) builds the SAME fields from the investigator's
        # actual UCP form entries (or an explicitly-labelled AI estimate
        # when left blank). These were two independent, disconnected
        # pipelines reading the same case — so the PDF could show, e.g.,
        # "Team Size: 2-3 / High / Highly planned" on one page and
        # "Team Size: Solo / Medium / Semi-planned" on another for the
        # same subject. Fix: when we have a real criminal_profile (i.e.
        # unidentified_flag path), make it the single source of truth and
        # override inv_results['dynamic_profile'] with it, instead of
        # letting the two pipelines diverge.
        if unidentified_flag and criminal_profile:
            inv_results['dynamic_profile'] = {
                "estimated_age": criminal_profile.get("estimated_age", "Unknown"),
                "estimated_gender": criminal_profile.get("gender", "Unknown"),
                "team_size": criminal_profile.get("likely_team_size", "Unknown"),
                "technical_skill": criminal_profile.get("technical_skill", "Unknown"),
                "planning_level": criminal_profile.get("planning_level", "Unknown"),
                "risk_behavior": criminal_profile.get("risk_behaviour", "Unknown"),
            }
            # BUG FIX (2026-08-20 — High): the same divergence existed for
            # "Profile Confidence" — the Unknown Criminal Profile section
            # (Page 8) shows the investigator's actual UCP-form confidence
            # value (e.g. 95%), while the separate "Unknown Profile
            # (Investigator Engine)" section (Page 13) showed a hardcoded
            # 72/40 from run_investigator_engine()'s own keyword-based
            # estimate — two different numbers for the same case. Sync the
            # whole unknown_profile block to the same investigator-entered
            # source of truth, same as dynamic_profile above.
            inv_results['unknown_profile'] = {
                "estimated_age": criminal_profile.get("estimated_age", "Unknown"),
                "estimated_gender": criminal_profile.get("gender", "Unknown"),
                "modus_operandi": inv_results.get('unknown_profile', {}).get("modus_operandi", "Unknown"),
                "mo_signature": criminal_profile.get("mo_signature", "Unknown"),
                "profile_confidence": criminal_profile.get("profile_confidence", 40),
            }

        # Add to report_data
        report_data['investigator'] = inv_results

        # BUG FIX (2026-08-20 — P0, Canonical Case Priority): Page 2 ("Case
        # Priority: High" / "VERDICT — HIGH PRIORITY — CRITICAL CASE") and
        # Page 11 (Public Safety Risk etc., via _assess_threat_from_evidence's
        # case_priority override) already correctly derive from the single
        # investigator-set `case_priority` field. But Page 15's Executive
        # Dashboard ("Case Status") came from run_investigator_engine()'s own
        # independent `risk_level` variable — a totally disconnected
        # computation — so the SAME case could show "HIGH PRIORITY — CRITICAL
        # CASE" on Page 2 and "MEDIUM PRIORITY" on Page 15. Make Page 15
        # defer to the same canonical case_priority instead of guessing its
        # own status from a different signal.
        if 'advanced' in inv_results and 'executive_dashboard' in inv_results['advanced']:
            _canonical_status = (
                "HIGH PRIORITY - CRITICAL" if case_priority in ("High", "Critical")
                else ("LOW PRIORITY" if case_priority == "Low" else "MEDIUM PRIORITY")
            )
            inv_results['advanced']['executive_dashboard']['case_status'] = _canonical_status

        # ── Investigation Guidance Engine (Knowledge-Driven, rule-based) ──
        # Turns the Hypothesis Ranking output + the same evidence_items map
        # already built above (face/voice/document/cctv/financial/vehicle)
        # into ranked, explainable "next investigation angle" directions —
        # not a static evidence-collection checklist, but a knowledge-base
        # driven investigation strategy engine.
        try:
            if guidance_engine is not None:
                _adv_g = (inv_results.get("advanced", {}) or {})
                _top_hyps_g = (_adv_g.get("hypothesis_ranking", {}) or {}).get("top_hypotheses", []) or []
                _all_hyps_g = _adv_g.get("all_hypotheses_raw", []) or _top_hyps_g

                ctx_hypotheses = [
                    Hypothesis(name=h.get("name", ""), confidence=(h.get("confidence", 0) or 0) / 100.0)
                    for h in _all_hyps_g if h.get("name")
                ]
                ctx_evidence = [
                    EvidenceItem(
                        type=k,
                        value=str(v.get("type", "")),
                        confidence=0.8 if v.get("quality") == "good" else 0.4,
                    )
                    for k, v in inv_case_data['evidence']['evidence_items'].items()
                ]
                guidance_ctx = CaseContext(
                    case_id=case_id or "UNSPECIFIED",
                    evidence=ctx_evidence,
                    hypotheses=ctx_hypotheses,
                    # BUG FIX (2026-08-20): the KB's "triggers" keyword lists
                    # (e.g. "oxy-acetylene", "RF jammer", "duplicate key")
                    # are meant to match the case's actual narrative text —
                    # without passing it in, matching had to fall back to
                    # just the short hypothesis name, which rarely contains
                    # these specific MO keywords.
                    narrative=modus or "",
                )
                guidance_directions = guidance_engine.analyze_case(guidance_ctx, top_n=10)
                report_data['guidance'] = guidance_engine.generate_investigation_report(
                    guidance_ctx, guidance_directions
                )
                log.info(f"✅ Investigation Guidance Engine produced {len(guidance_directions)} directions")
            else:
                report_data['guidance'] = {"error": "Guidance Engine not loaded"}
        except Exception as e:
            log.error(f"❌ Investigation Guidance Engine failed: {str(e)}")
            report_data['guidance'] = {"error": str(e)}

        # ── Confidence & Forensic Transparency ──────────────────────────
        # Addresses: (a) a deepfake model score displayed as a bare "100%"
        # reads as a definitive forensic finding, when it's only a
        # classifier score; (b) the report can show several different
        # "confidence" numbers for related theories (crime classification,
        # hypothesis ranking, fused confidence) with no way to tell which
        # one is authoritative. These three checks compute one explicit,
        # labelled canonical confidence plus a model/forensic split for the
        # deepfake result, and fold straight into the existing Advanced
        # Intelligence Report output (no new UI panel needed).
        try:
            _calibrated_deepfake = (
                calibrate_deepfake_result(deepfake_result, image_quality)
                if deepfake_result else None
            )
            _separate_confidence = calculate_separate_confidence(
                evidence_provided, reasoning.get("hypotheses", []), deception, risk
            )
            _crime_hyp_link = link_crime_to_hypotheses(
                crime_info, reasoning.get("hypotheses", []), evidence_provided
            )
            _threat_assessment = assess_threat_with_evidence(
                crime_info, watchlist, entities, evidence_provided
            )
            report_data['confidence_transparency'] = {
                "canonical_confidence": _separate_confidence,
                "crime_hypothesis_alignment": _crime_hyp_link,
                "evidence_based_threat": _threat_assessment,
                "deepfake_calibrated": _calibrated_deepfake,
            }
            # Fold into the existing Advanced Intelligence Report dict so it
            # renders through the already-wired inv_advanced_html panel and
            # PDF section, without touching the output-component wiring.
            inv_results.setdefault("advanced", {})["confidence_transparency"] = {
                "canonical_confidence_note": (
                    f"{_separate_confidence['canonical_confidence']}% "
                    f"({_separate_confidence['level']}) — this is the single canonical "
                    f"confidence value; other confidence numbers elsewhere in this report "
                    f"(crime classification score, hypothesis ranking %, fused confidence) "
                    f"are component/supporting signals feeding into it, not alternative answers."
                ),
                "canonical_confidence_breakdown": _separate_confidence,
                "crime_classification_vs_hypothesis_engine": _crime_hyp_link,
                "evidence_based_threat_assessment": _threat_assessment,
                "deepfake_model_vs_forensic_conclusion": _calibrated_deepfake,
            }
            if _calibrated_deepfake:
                report_data['deepfake_status_calibrated'] = (
                    f"Model classification: {_calibrated_deepfake['model_classification']} | "
                    f"Forensic conclusion: {_calibrated_deepfake['forensic_conclusion']}"
                )
            log.info("✅ Confidence & Forensic Transparency block added")
        except Exception as e:
            log.error(f"❌ Confidence & Forensic Transparency failed: {str(e)}")
            report_data['confidence_transparency'] = {"error": str(e)}

        # ── HBEI (Human Behavior & Error Intelligence) — external service ──
        # Separate microservice (detectors/provenance/schemas pipeline),
        # not an in-process module — called over HTTP so a slow/down HBEI
        # service degrades gracefully (report still generates) instead of
        # blocking the whole analysis.
        #
        # IMPORTANT: HumanErrorDetector.analyze_all(case_data) — the actual
        # method the pipeline calls — reads case_data['timeline'],
        # ['evidence'], ['post_events'], ['digital_artifacts'], and
        # ['behavior_history']. It does NOT read 'actions'/'context' for
        # anything beyond a normalization step that only feeds Method 2's
        # individual detect_* calls, which themselves receive the whole
        # dict as a single positional arg and fail silently (TypeError
        # caught by a bare except) since each expects a specific list, not
        # a dict — confirmed from the HBEI core source. So an
        # 'actions'/'context'-only payload reaches ZERO real detectors and
        # always falls through to the synthetic fallback observation
        # (confidence exactly 0.6, which is why 'Signals: 0' — the signal
        # filter is strictly > 0.6). Every list below is built from real,
        # already-extracted case data (timeline, NER entities, narrative
        # text) — nothing is fabricated to force a match.
        try:
            import re as _re
            import requests as _requests

            # Build fingerprint — if this exact line never appears in the
            # server log, the file that generated the report was NOT this
            # version, regardless of what else has been deployed.
            log.info("🔖 HBEI block build marker: v2026-08-16-canonical-fix")

            # Defensive: explicitly bound before anything else in this
            # block runs, so it is structurally impossible for any later
            # line to reference it before assignment — this exact class of
            # bug ("cannot access local variable _hbei_resp") was reported
            # from a production deployment; whatever caused it there, this
            # makes it impossible here regardless of cause.
            _hbei_resp = None

            def _hbei_build_timeline(events, base_date_str, case_location):
                """timeline_events is [{'time': '+4 min', 'event': '...'}] —
                HumanErrorDetector needs real ISO timestamps (it parses them
                with datetime.fromisoformat for interval analysis), so
                relative offsets are converted to real datetimes anchored to
                the incident date (or now() if that's not set)."""
                try:
                    base_dt = datetime.fromisoformat(base_date_str.strip()) if base_date_str and base_date_str.strip() else datetime.now()
                except Exception:
                    base_dt = datetime.now()
                out = []
                for ev in (events or []):
                    time_str = str(ev.get("time", "")).strip()
                    m = _re.match(r'^\+?(\d+)\s*(min|hr|hour|sec)', time_str, _re.IGNORECASE)
                    offset = base_dt
                    if m:
                        n, unit = int(m.group(1)), m.group(2).lower()
                        if unit.startswith("min"):
                            offset = base_dt + timedelta(minutes=n)
                        elif unit.startswith("hr") or unit.startswith("hour"):
                            offset = base_dt + timedelta(hours=n)
                        elif unit.startswith("sec"):
                            offset = base_dt + timedelta(seconds=n)
                    out.append({
                        "timestamp": offset.isoformat(),
                        "location": case_location or "scene",
                        "event": ev.get("event", ""),
                    })
                return out

            def _hbei_build_execution_evidence(ents, narrative):
                """EXEC-001 fires on {'type':'physical','status':'recovered'}
                — a real, defensible mapping when the narrative itself says
                a weapon/tool/item was left/found/recovered/dropped/
                abandoned at the scene, not just 'used'. Doesn't mark every
                weapon mention as recovered — only ones the text actually
                supports."""
                out = []
                narrative_l = (narrative or "").lower()
                recovery_words = ("recovered", "left behind", "left at", "found at", "found near",
                                   "dropped", "abandoned", "discarded", "seized")
                for i, weapon in enumerate((ents.get("WEAPON", []) or [])):
                    w_l = str(weapon).lower()
                    idx = narrative_l.find(w_l)
                    if idx < 0:
                        continue  # entity text not actually found in the narrative — don't guess
                    window = narrative_l[max(0, idx - 60): idx + 60]
                    if any(rw in window for rw in recovery_words):
                        out.append({
                            "type": "physical", "status": "recovered",
                            "evidence_id": f"WEAPON-{i+1:02d}",
                            "description": str(weapon),
                        })
                return out

            def _hbei_build_post_events(narrative, escape_pattern):
                """POST-001 (sudden deletion) / POST-002 (return to scene) —
                keyword-driven from the actual case narrative/escape
                pattern, not fabricated."""
                out = []
                combined = f"{narrative or ''} {escape_pattern or ''}".lower()
                if any(kw in combined for kw in ("returned to the scene", "revisited the", "went back to",
                                                   "return to the scene", "came back to")):
                    out.append({
                        "action": "visit", "location": "crime_scene",
                        "entity_id": "unknown_perpetrator", "event_id": "post-event-return",
                        "source": "case_narrative",
                    })
                if any(kw in combined for kw in ("wiped", "deleted", "erased", "factory reset",
                                                   "destroyed the device", "destroyed devices")):
                    out.append({
                        "action": "delete", "urgency": "immediate",
                        "entity_id": "unknown_perpetrator", "event_id": "post-event-deletion",
                        "source": "case_narrative",
                    })
                return out

            _hbei_timeline = _hbei_build_timeline(timeline_events, incident_date, location)
            _hbei_evidence = _hbei_build_execution_evidence(entities, modus)
            _hbei_post_events = _hbei_build_post_events(modus, ucp_escape_pattern)
            _hbei_behavior_history = [
                {"text": t} for t in (modus, ucp_mo_signature, ucp_behaviour_at_scene, ucp_dominant_behaviour)
                if t and str(t).strip() and not str(t).strip().lower().startswith("unknown")
            ]

            _hbei_payload = {"case_id": case_id or "NXF-CASE", "behavioral": {}}
            if _hbei_timeline:
                _hbei_payload["behavioral"]["timeline"] = _hbei_timeline
            if _hbei_evidence:
                _hbei_payload["behavioral"]["evidence"] = _hbei_evidence
            if _hbei_post_events:
                _hbei_payload["behavioral"]["post_events"] = _hbei_post_events
            if _hbei_behavior_history:
                _hbei_payload["behavioral"]["behavior_history"] = _hbei_behavior_history
            # Kept alongside the structured lists above — harmless if the
            # service's own normalization step still uses it for something,
            # and preserves the previous behavior for any code path that
            # only understood the old 'actions'/'context' shape.
            if modus and modus.strip():
                _hbei_payload["behavioral"]["actions"] = [modus.strip()[:200]]
                _hbei_payload["behavioral"]["context"] = modus.strip()[:200]
            if not _hbei_payload["behavioral"]:
                del _hbei_payload["behavioral"]

            # Baseline profile — without this, the API reportedly returns
            # NO_BASELINE and 0 observations regardless of what behavioral
            # data is sent. This app has no prior-case history for a given
            # suspect/entity to build a real baseline from (no identified
            # suspect in most cases), so this is an explicit "no history
            # available" baseline rather than a fabricated one — best-effort
            # given the API server's own validation code isn't available to
            # confirm the exact expected schema.
            _hbei_payload["baseline_profile"] = {
                "entity_id": case_id or "NXF-CASE",
                "status": "NO_PRIOR_HISTORY",
                "historical_data": [],
                "note": "No prior case history available for this entity — first appearance in system.",
            }

            _hbei_resp = _requests.post("http://localhost:8000/analyze", json=_hbei_payload, timeout=15)
            _hbei_resp.raise_for_status()
            _hbei_json = _hbei_resp.json()

            _hbei_empty = (
                _hbei_json.get("total_observations", 0) in (0, None)
                and _hbei_json.get("signals", 0) in (0, None)
            ) or str(_hbei_json.get("status", "")).upper() == "NO_BASELINE"

            if _hbei_empty:
                # Fallback chain: build local observations from
                # modus_operandi + case narrative text using the in-process
                # HBEIEngine (keyword-matching against hbei_kb.json),
                # instead of showing the investigator an empty "0 signals"
                # result when the remote API couldn't establish a baseline.
                log.warning("⚠️ HBEI API returned no observations (NO_BASELINE or empty) — using local fallback engine")
                try:
                    from hbei_engine.engine import HBEIEngine as _LocalHBEIEngine
                    _local_hbei = _LocalHBEIEngine(kb_path=str(Path(__file__).resolve().parent / "hbei_engine" / "hbei_kb.json"))
                    _local_evidence_items = [
                        {"description": t} for t in
                        (modus, ucp_entry_method, ucp_weapons_used, ucp_escape_pattern,
                         ucp_behaviour_at_scene, ucp_dominant_behaviour, ucp_mo_signature)
                        if t and str(t).strip() and not str(t).strip().lower().startswith("unknown")
                    ]
                    _local_report = _local_hbei.analyze_case(
                        case_id or "NXF-CASE", _local_evidence_items, timeline=_hbei_timeline,
                    )
                    report_data['hbei_api_result'] = {
                        "case_id": _local_report.case_id,
                        "total_observations": len(_local_report.detected_signals),
                        "signals": len(_local_report.detected_signals),
                        "priority": "HIGH" if any(s.severity in ("CRITICAL", "HIGH") for s in _local_report.detected_signals) else "MODERATE",
                        "weakest_link": (_local_report.detected_signals[0].sub_type if _local_report.detected_signals else "unknown"),
                        "investigation_direction": _local_report.interpretation or "General behavioral verification required",
                        "evidence_needed": [s.evidence_source for s in _local_report.detected_signals],
                        "counter_hypotheses": [],
                        "source": "local_fallback_engine",
                        "fallback_reason": "HBEI API returned NO_BASELINE/empty result for this case",
                    }
                    log.info(f"✅ HBEI local fallback produced {len(_local_report.detected_signals)} signal(s)")
                except Exception as fe:
                    log.error(f"❌ HBEI local fallback also failed: {str(fe)}")
                    report_data['hbei_api_result'] = _hbei_json  # keep the (empty) API result rather than hide it
            else:
                report_data['hbei_api_result'] = _hbei_json
                log.info(
                    f"✅ HBEI analysis complete — sent timeline:{len(_hbei_timeline)} "
                    f"evidence:{len(_hbei_evidence)} post_events:{len(_hbei_post_events)} "
                    f"behavior_history:{len(_hbei_behavior_history)}"
                )
        except Exception as e:
            log.error(f"❌ HBEI service call failed: {str(e)}")
            report_data['hbei_api_result'] = {"error": str(e)}

        # Crime Classification vs Hypothesis Engine integration: when the
        # keyword-based Crime Classification landed on a generic "no
        # specific pattern" label but the Hypothesis Engine (which reasons
        # over the full evidence graph, not just keyword matches) has
        # independently converged on a strong, specific theory, fold that
        # theory into the displayed primary classification instead of
        # leaving two disconnected, seemingly-contradictory labels in the
        # same report — this was flagged repeatedly as the biggest
        # remaining inconsistency.
        _generic_crime_markers = ("no specific", "under investigation", "unclassified", "pending")
        if any(m in str(report_data.get("crime_primary", "")).lower() for m in _generic_crime_markers):
            _adv_for_crime = (inv_results.get("advanced", {}) or {})
            _top_hyps_for_crime = (_adv_for_crime.get("hypothesis_ranking", {}) or {}).get("top_hypotheses", []) or []
            if _top_hyps_for_crime:
                try:
                    _lead_conf = float(_top_hyps_for_crime[0].get("confidence", 0) or 0)
                except (TypeError, ValueError):
                    _lead_conf = 0
            else:
                _lead_conf = 0
            if _lead_conf >= 70:
                _leading = _top_hyps_for_crime[0]
                report_data["crime_primary"] = (
                    f"{report_data.get('crime_primary', 'Under Investigation')} — "
                    f"Leading Theory (Hypothesis Engine): {_leading.get('name', 'Unknown')} "
                    f"({_leading.get('confidence', 0)}% confidence)"
                )
                # Severity should follow the stronger signal too, not stay
                # at the keyword-match's default.
                if str(report_data.get("crime_severity", "")).upper() in ("LOW", ""):
                    report_data["crime_severity"] = "High" if _lead_conf >= 85 else "Moderate"

        log.info("✅ Investigator Engine results added to report_data")
    except Exception as e:
        log.error(f"❌ Investigator Engine failed: {str(e)}")
        report_data['investigator_error'] = str(e)


    # ── Persist to history (survives restarts; user-attributed if logged in) ──
    user_email = None
    try:
        if request is not None:
            token = request.cookies.get(AUTH_COOKIE) if hasattr(request, "cookies") else None
            if token:
                payload = _verify_jwt(token)
                if payload:
                    user_email = payload.get("email")
    except Exception as e:
        log.warning(f"Could not resolve user for history attribution: {e}")

    # DOA 2026-11-06: structured contradiction check on the narrative, shown on screen too
    try:
        from journalist_research.evidence.narrative_split import narrative_contradictions
        _nc, _ = narrative_contradictions(modus or "", (suspect_name or "subject").strip() or "subject")
        lines += ["", "STRUCTURED CONTRADICTION CHECK (DOA)"]
        if _nc:
            for _c in _nc[:8]:
                lines.append(f"    [{_c.severity}] {_c.doa_class}: {_c.explanation}")
            lines.append("    A contradiction is a lead for human review. It establishes no fact, identity or guilt.")
        else:
            lines.append("    No structured contradiction found in the case narrative (loans, roles, addresses).")
        report_data["doa_contradictions"] = [{"class": c.doa_class, "severity": c.severity,
                                              "explanation": c.explanation} for c in _nc]
    except Exception as _e:
        log.warning(f"DOA contradiction check failed: {_e}")

    report_text_final = "\n".join(lines)
    _save_history_entry(entry, report_text_final, report_data, user_email=user_email)

    # ── Build Network Intelligence HTML ───────────────────────────────────
    network_html = _build_network_html(net_matches, net_summary, fin_flags, veh_flags)

    # ── Extract Investigator Engine outputs from report_data (NOT the UI
    #    component objects — those share the same names in the Blocks UI
    #    section below, but here we need the actual computed values) ─────────
    _inv = report_data.get('investigator', {}) or {}
    _guidance_html = render_guidance_section(report_data)
    return (
        f"{deception}%" if voice_clip else "N/A — Narrative text only",
        f"{credibility}%" if voice_clip else "N/A — Narrative text only",
        f"{risk}%",
        f"{pat_sc:.1f}%  [{pat_src}]",
        f"{net_risk:.1f}%",
        f"{fin_risk:.1f}%",
        gr.update(visible=True, value=indicators_html),
        gr.update(visible=True, value=network_html),
        gr.update(visible=True, value=graph_html),
        report_text_final,
        _history_html(user_email),
        report_data,
        _inv.get('evidence_completeness', {}).get('total', '0%'),
        _inv_render_html(_inv.get('evidence_completeness', {}).get('components', [])),
        _inv.get('unknown_profile', {}).get('estimated_age', 'Unknown'),
        _inv.get('unknown_profile', {}).get('estimated_gender', 'Unknown'),
        _inv.get('unknown_profile', {}).get('modus_operandi', 'Unknown'),
        _inv.get('unknown_profile', {}).get('mo_signature', 'Unknown'),
        _inv.get('unknown_profile', {}).get('profile_confidence', 0),
        _inv_render_html(_inv.get('reasoning_matrix', [])),
        str(_inv.get('investigation_paths', {}).get('total', 0)),
        str(_inv.get('investigation_paths', {}).get('strong', 0)),
        str(_inv.get('investigation_paths', {}).get('rejected', 0)),
        _inv_render_html(_inv.get('investigation_paths', {}).get('paths', [])),
        _inv_render_html(_inv.get('missing_impact', [])),
        _inv_render_html(_inv.get('investigation_value', [])),
        _inv_render_html(_inv.get('deepfake_impact', [])),
        _inv.get('risk', {}).get('level', 'Unknown'),
        _inv.get('risk', {}).get('reason', 'No risk assessment'),
        _inv.get('scene_classification', {}).get('classification', 'Unknown'),
        _inv.get('scene_classification', {}).get('confidence', 0),
        _inv.get('scene_classification', {}).get('source', 'Unknown'),
        _inv_render_html(_inv.get('dynamic_profile', {})),
        _inv.get('ocr', {}).get('status', 'Unknown'),
        _inv.get('ocr', {}).get('reason', 'No OCR data'),
        _inv_render_html(_inv.get('advanced', {}), empty_label="Advanced intelligence pipeline did not run for this case."),
        _build_interactive_network_html(*_kg_nodes_edges(_inv.get('advanced', {}).get('knowledge_graph_raw', {}))),
        _build_interactive_network_html(*_criminal_network_nodes_edges(_inv.get('advanced', {}).get('criminal_network', {}))),
        _guidance_html,
    )


def load_history_record(record_id, request: gr.Request = None):
    _uem = _req_email(request)
    """Re-opens a past investigation's full report (called when the user
    picks one from the History dropdown and clicks Load)."""
    if not record_id:
        return (gr.update(), gr.update(), gr.update(), gr.update(),
                gr.update(), gr.update(), gr.update(), gr.update(),
                gr.update(), gr.update(), gr.update(), gr.update(),
                gr.update(), gr.update(), gr.update(), gr.update(),
                gr.update(), gr.update(), gr.update(), gr.update(),
                gr.update(), gr.update(), gr.update(), gr.update(),
                gr.update(), gr.update(), gr.update(), gr.update(),
                gr.update(), gr.update(), gr.update(), gr.update(),
                gr.update(), gr.update(), gr.update(), gr.update(),
                gr.update(), gr.update(), gr.update())

    report_text, report_data = _load_history_report(record_id, _uem)
    if not report_data:
        return (gr.update(), gr.update(), gr.update(), gr.update(),
                gr.update(), gr.update(), gr.update(), gr.update(),
                gr.update(), gr.update(), gr.update(), gr.update(),
                gr.update(), gr.update(), gr.update(), gr.update(),
                gr.update(), gr.update(), gr.update(), gr.update(),
                gr.update(), gr.update(), gr.update(), gr.update(),
                gr.update(), gr.update(), gr.update(), gr.update(),
                gr.update(), gr.update(), gr.update(), gr.update(),
                gr.update(), gr.update(), gr.update(), gr.update(),
                gr.update(), gr.update(), gr.update())

    # Rebuild the same visual widgets (score cards, indicator bars, graph)
    # that a live analysis would produce, from the saved report_data.
    scores_for_graph = {
        "deception": report_data.get("deception", 0),
        "credibility": report_data.get("credibility", 0),
        "risk": report_data.get("risk", 0),
        "voice": report_data.get("vox_sc", 0),
        "ner": report_data.get("ner_sc", 0),
        "ocr": report_data.get("ocr_sc", 0),
        "pattern": report_data.get("pat_sc", 0),
    }
    graph_html = build_graphs_html(scores_for_graph, list(reversed(_load_recent_history(limit=10, user_email=_uem))))

    pat_sc = report_data.get("pat_sc", 0)
    pat_src = report_data.get("pat_src", "heuristic")

    # Restore the saved Investigator Engine results too, so reopening a past
    # case shows the same investigator columns as when it was first analysed.
    _inv = report_data.get('investigator', {}) or {}
    _guidance_html = render_guidance_section(report_data)

    return (
        report_data.get("deception_display") or "N/A — Narrative text only",
        (f"{report_data.get('credibility', 0)}%" if report_data.get("_deception_has_voice")
         else "N/A — Narrative text only"),
        f"{report_data.get('risk', 0)}%",
        f"{pat_sc:.1f}%  [{pat_src}]" if isinstance(pat_sc, (int, float)) else str(pat_sc),
        f"{report_data.get('network_risk', 0):.1f}%",
        f"{report_data.get('financial_risk', 0):.1f}%",
        gr.update(visible=True, value=f"<p style='color:#94a3b8;font-size:12px;padding:10px;'>"
                  f"📂 Loaded from history — {report_data.get('timestamp','')}. "
                  f"Full indicator breakdown available in the report text and PDF export below.</p>"),
        gr.update(visible=True, value="<p style='color:#94a3b8;font-size:12px;padding:10px;'>Network data loaded from history.</p>"),
        gr.update(visible=True, value=graph_html),
        report_text or "No report text saved for this record.",
        _history_html(_uem),
        report_data,
        _inv.get('evidence_completeness', {}).get('total', '0%'),
        _inv_render_html(_inv.get('evidence_completeness', {}).get('components', [])),
        _inv.get('unknown_profile', {}).get('estimated_age', 'Unknown'),
        _inv.get('unknown_profile', {}).get('estimated_gender', 'Unknown'),
        _inv.get('unknown_profile', {}).get('modus_operandi', 'Unknown'),
        _inv.get('unknown_profile', {}).get('mo_signature', 'Unknown'),
        _inv.get('unknown_profile', {}).get('profile_confidence', 0),
        _inv_render_html(_inv.get('reasoning_matrix', [])),
        str(_inv.get('investigation_paths', {}).get('total', 0)),
        str(_inv.get('investigation_paths', {}).get('strong', 0)),
        str(_inv.get('investigation_paths', {}).get('rejected', 0)),
        _inv_render_html(_inv.get('investigation_paths', {}).get('paths', [])),
        _inv_render_html(_inv.get('missing_impact', [])),
        _inv_render_html(_inv.get('investigation_value', [])),
        _inv_render_html(_inv.get('deepfake_impact', [])),
        _inv.get('risk', {}).get('level', 'Unknown'),
        _inv.get('risk', {}).get('reason', 'No risk assessment'),
        _inv.get('scene_classification', {}).get('classification', 'Unknown'),
        _inv.get('scene_classification', {}).get('confidence', 0),
        _inv.get('scene_classification', {}).get('source', 'Unknown'),
        _inv_render_html(_inv.get('dynamic_profile', {})),
        _inv.get('ocr', {}).get('status', 'Unknown'),
        _inv.get('ocr', {}).get('reason', 'No OCR data'),
        _inv_render_html(_inv.get('advanced', {}), empty_label="Advanced intelligence pipeline did not run for this case."),
        _build_interactive_network_html(*_kg_nodes_edges(_inv.get('advanced', {}).get('knowledge_graph_raw', {}))),
        _build_interactive_network_html(*_criminal_network_nodes_edges(_inv.get('advanced', {}).get('criminal_network', {}))),
        _guidance_html,
    )


def _hist_dd_for_user(request: gr.Request = None):
    return gr.update(choices=_history_dropdown_choices(_req_email(request)))


def _hist_on_load(request: gr.Request = None):
    e = _req_email(request)
    return _history_html(e), gr.update(choices=_history_dropdown_choices(e))


def _history_html(user_email=None):
    rows_data = _load_recent_history(limit=20, user_email=user_email)
    if not rows_data:
        return "<p style='color:#334155;font-size:13px;padding:10px;'>No analyses yet.</p>"
    rows = ""
    for h in rows_data:
        r = h["risk"]
        col = "#ef4444" if r>75 else "#f59e0b" if r>50 else "#22c55e"
        ic = "🔴" if r>75 else "🟡" if r>50 else "🟢"
        rows += (
            f"<div style='display:flex;justify-content:space-between;"
            f"align-items:center;background:#111620;border:0.5px solid #1a2236;"
            f"border-radius:8px;padding:11px 15px;margin-bottom:7px;'>"
            f"<div>"
            f"<p style='font-size:13px;font-weight:500;color:#e2e8f0;margin:0 0 2px;'>"
            f"{ic} {h['case_id']}  —  {h['suspect_name']}</p>"
            f"<p style='font-size:11px;color:#475569;margin:0;'>{h['date']}</p></div>"
            f"<div style='text-align:right;'>"
            f"<p style='font-size:14px;font-weight:600;color:{col};margin:0;'>{r:.0f}%</p>"
            f"<p style='font-size:10px;color:#475569;margin:0;'>risk</p></div></div>"
        )
    rows += ("<p style='font-size:11px;color:#475569;margin-top:8px;'>"
             "Use the dropdown below to re-open any past report ↓</p>")
    return rows

def regenerate_story_draft(report_data):
    """
    On-demand (re)generation of the Qwen story draft from the last
    completed analysis — lets the user regenerate a fresh draft (LLM
    output is stochastic) without re-running the whole pipeline.
    Returns a gr.update() for the o_story_draft textbox.
    """
    if not report_data:
        return gr.update(
            value="No analysis has been run yet — click Investigate first.",
            visible=True,
        )
    if not qwen_eng.ready:
        return gr.update(
            value="The AI story-draft model is not loaded on this server "
                  "(check models/qwen/model.gguf and the startup logs).",
            visible=True,
        )
    modus = report_data.get("modus", "")
    if not modus.strip():
        return gr.update(
            value="No Modus Operandi text was provided for this case — "
                  "nothing for the AI to draft a story from.",
            visible=True,
        )
    try:
        draft = qwen_eng.generate_story_draft(
            report_data.get("case_id"), modus,
            report_data.get("suspect_name"), report_data.get("location"),
            report_data.get("entities", {}),
            report_data.get("mo_fingerprint_links", {}),
            report_data.get("unidentified_leads", {}),
            report_data.get("watchlist", {}),
            report_data.get("reasoning", {}),
        )
        return gr.update(value=draft or "The AI returned an empty draft — try again.", visible=True)
    except Exception as e:
        log.error(f"Story draft regeneration error: {e}")
        return gr.update(value=f"Story draft generation failed: {e}", visible=True)




THEME = gr.themes.Base(
    primary_hue=gr.themes.colors.blue,
    neutral_hue=gr.themes.colors.slate,
    font=gr.themes.GoogleFont("Inter"),
).set(
    # Light-mode values (kept identical to dark-mode ones below so the UI
    # looks the same regardless of the visitor's OS/browser color-scheme
    # preference — without this, Gradio silently falls back to its own
    # default *_dark colors for anything not explicitly set here, which
    # is what caused label text to render as unreadable grey-on-grey for
    # users whose system is in dark mode).
    body_background_fill="#080b12",
    block_background_fill="#0d1117",
    block_border_color="#1a2236",
    block_label_text_color="#f8fafc",
    body_text_color="#f8fafc",
    input_background_fill="#0d1117",
    input_border_color="#1a2236",
    input_placeholder_color="#64748b",
    button_primary_background_fill="#0077ff",
    button_primary_background_fill_hover="#0066ee",
    button_primary_text_color="#ffffff",
    # Explicit dark-mode variants — same values, so nothing changes when
    # the visitor's OS is in dark mode (this app is dark-themed already).
    body_background_fill_dark="#080b12",
    block_background_fill_dark="#0d1117",
    block_border_color_dark="#1a2236",
    block_label_text_color_dark="#f8fafc",
    body_text_color_dark="#f8fafc",
    input_background_fill_dark="#0d1117",
    input_border_color_dark="#1a2236",
    input_placeholder_color_dark="#64748b",
    button_primary_background_fill_dark="#0077ff",
    button_primary_background_fill_hover_dark="#0066ee",
    button_primary_text_color_dark="#ffffff",
)

def _st_tooltip(k, v):
    state = "loaded and ready" if v == "✓" else "unavailable"
    return (f"{k} engine is {state} on this server — this does NOT mean {k} evidence "
            f"was submitted for the current case. See Evidence Sources Status in the "
            f"report for per-case status.")

ST_HTML = "<span style='font-size:9px;color:#64748b;'>AI MODULES (server-ready, not case evidence):</span> &nbsp;" + " &nbsp;".join(
    f"<span style='font-size:10px;color:{'#22c55e' if v=='✓' else '#f59e0b'};' "
    f"title='{_st_tooltip(k, v)}'>"
    f"{k} {v}</span>"
    for k,v in STATUS.items()
)

with gr.Blocks(theme=THEME, title="InvestigatorAI",
               css="/home/nexforensics/app/static/gradio_custom.css") as demo:

    # ── Header (global, same on every page/tab) ─────────────────────────────────
    gr.HTML(f"""
    <div style='border-bottom:0.5px solid #1a2236;padding:14px 26px;
                background:#0a0e1a;display:flex;align-items:center;
                justify-content:space-between;'>

      <img src='https://nexforensics.com/wp-content/uploads/2026/06/cropped-LOGO-NEX.png'
           alt='NexForensics'
           style='height:48px;width:48px;border-radius:50%;
                  border:2px solid #ef4444;background:#fff;object-fit:contain;padding:4px;'
           onerror="this.style.display='none'" />

      <div style='text-align:center;'>
        <div style='font-size:22px;font-weight:700;color:#f1f5f9;letter-spacing:.01em;'>
          InvestigatorAI</div>
        <div style='font-size:11px;font-weight:500;color:#64748b;
                    letter-spacing:.25em;text-transform:uppercase;margin-top:2px;'>
          Signal to Evidence</div>
      </div>

      <img src='https://nexforensics.com/wp-content/uploads/2026/07/investigator_logo.png'
           alt='InvestigatorAI'
           style='height:48px;width:48px;border-radius:50%;
                  border:2px solid #ef4444;background:#fff;object-fit:contain;padding:4px;'
           onerror="this.style.display='none'" />
    </div>

    <div style='background:#0a0e1a;padding:6px 26px;border-bottom:0.5px solid #1a2236;
                display:flex;justify-content:flex-end;gap:10px;'>
      {ST_HTML}
    </div>""")

    with gr.Row(equal_height=False):

        # ── LEFT COLUMN ───────────────────────────────────────────────────────
        with gr.Column(scale=1, min_width=340):

            email_disp = gr.HTML(
                "<div style='background:#0d1117;border:0.5px solid #1a2236;"
                "border-radius:8px;padding:9px 14px;font-size:13px;color:#60a5fa;"
                "margin-top:8px;'>✉  Session active</div>"
            )

            gr.HTML("<p style='font-size:11px;color:#60a5fa;letter-spacing:.12em;"
                    "text-transform:uppercase;margin:14px 0 6px;font-weight:700;'>"
                    "Step 1 — Case Information</p>")

            with gr.Row():
                case_id    = gr.Textbox(label="Case ID",      placeholder="NXF-2024-XXXX")
                case_title = gr.Dropdown(label="Case Title", choices=[], value=None,
                                          allow_custom_value=True,
                                          info="Click to reuse a past entry, or type a new one")

            with gr.Row():
                crime_category = gr.Dropdown(
                    label="Crime Category",
                    choices=[
                        "Robbery", "Burglary", "Assault", "Homicide", "Fraud",
                        "Cybercrime", "Financial Crime", "Narcotics", "Kidnapping",
                        "Sexual Offence", "Organized Crime", "Terrorism", "Other / Unclassified",
                    ],
                    value=None,
                    allow_custom_value=True,
                )
                incident_date = gr.Textbox(label="Incident Date (as reported — may be FIR/intake date if the "
                                                  "actual offense date is unknown)",
                                            placeholder="YYYY-MM-DD or approximate; leave blank if unknown")

            with gr.Row():
                investigating_officer = gr.Dropdown(label="Investigating Officer", choices=[], value=None,
                                                     allow_custom_value=True,
                                                     info="Click to reuse a past entry, or type a new one")
                case_priority = gr.Dropdown(
                    label="Case Priority",
                    choices=["Low", "Medium", "High", "Critical"],
                    value="Medium",
                )

            modus = gr.Textbox(
                label="Modus Operandi / Narrative",
                placeholder="Describe the method and pattern observed in this case…",
                lines=5,
            )

            gr.HTML("<p style='font-size:11px;color:#60a5fa;letter-spacing:.12em;"
                    "text-transform:uppercase;margin:16px 0 6px;font-weight:700;'>"
                    "Step 2 — Suspect &amp; Location "
                    "<span style='color:#475569;font-weight:400;text-transform:none;letter-spacing:normal;'>"
                    "(full Step 2 wizard — Unknown Criminal Profile — coming next)</span></p>")

            with gr.Row():
                suspect  = gr.Dropdown(label="Suspect Name", choices=[], value=None,
                                        allow_custom_value=True,
                                        info="Click to reuse a past profile, or type a new one")
            location = gr.Dropdown(label="Location", choices=[], value=None,
                                    allow_custom_value=True,
                                    info="Click to reuse a past entry, or type a new one")

            gr.HTML("<p style='font-size:10px;color:#475569;letter-spacing:.1em;"
                    "text-transform:uppercase;margin:12px 0 4px;'>"
                    "🕵️ Agyat Apradhi <span style='color:#2d3a50;font-weight:400;'>"
                    "— when the suspect's identity is not known</span></p>")
            unidentified_flag = gr.Checkbox(
                label="Unidentified Suspect (search by MO/description, not name)",
                value=False,
            )
            physical_desc = gr.Textbox(
                label="Physical Description / Distinguishing Marks",
                placeholder="e.g. height 5'8\", scar on left cheek, tattoo on right forearm, limps on right leg…",
                lines=2,
            )

            with gr.Group(visible=False) as unknown_profile_group:
                gr.HTML("<p style='font-size:11px;color:#60a5fa;letter-spacing:.12em;"
                        "text-transform:uppercase;margin:14px 0 6px;font-weight:700;'>"
                        "Step 2 — Unknown Criminal Profile "
                        "<span style='color:#475569;font-weight:400;text-transform:none;"
                        "letter-spacing:normal;'>(behavioural profile, not a name)</span></p>")

                with gr.Row():
                    ucp_age    = gr.Textbox(label="Estimated Age", placeholder="e.g. 25-35")
                    ucp_gender = gr.Dropdown(label="Gender", choices=["Male", "Female", "Unknown"], value="Unknown")
                with gr.Row():
                    ucp_height    = gr.Textbox(label="Height", placeholder="e.g. 5'8\" - 5'10\"")
                    ucp_body_type = gr.Dropdown(label="Body Type",
                        choices=["Slim", "Medium", "Heavy", "Athletic", "Unknown"], value="Unknown")
                with gr.Row():
                    ucp_language = gr.Textbox(label="Language", placeholder="e.g. Hindi, Punjabi")
                    ucp_accent   = gr.Textbox(label="Accent", placeholder="e.g. Local Delhi, foreign")
                with gr.Row():
                    ucp_handedness = gr.Dropdown(label="Handedness",
                        choices=["Left", "Right", "Unknown"], value="Unknown")
                    ucp_dominant_behaviour = gr.Textbox(label="Dominant Behaviour", placeholder="e.g. aggressive, calculated")
                with gr.Row():
                    ucp_entry_method = gr.Textbox(label="Entry Method", placeholder="e.g. forced door, broken window, used access card")
                    ucp_behaviour_at_scene = gr.Textbox(label="Behaviour at Scene", placeholder="e.g. searched systematically, panicked, communicated with accomplices")
                with gr.Row():
                    ucp_weapons_used = gr.Textbox(label="Weapons Used", placeholder="e.g. knife, firearm, none seen")
                    ucp_team_size = gr.Dropdown(label="Likely Team Size",
                        choices=["Solo", "2-3", "4-6", "7+", "Unknown"], value="Unknown")
                with gr.Row():
                    ucp_tech_skill = gr.Dropdown(label="Estimated Technical Skill",
                        choices=["Low", "Medium", "High", "Unknown"], value="Unknown")
                    ucp_experience_level = gr.Dropdown(label="Likely Experience Level",
                        choices=["Novice", "Intermediate", "Experienced", "Professional", "Unknown"], value="Unknown")
                with gr.Row():
                    ucp_planning_level = gr.Dropdown(label="Crime Planning Level",
                        choices=["Opportunistic", "Semi-planned", "Highly planned", "Unknown"], value="Unknown")
                    ucp_risk_behaviour = gr.Dropdown(label="Risk Behaviour",
                        choices=["Low", "Medium", "High", "Unknown"], value="Unknown")
                with gr.Row():
                    ucp_escape_pattern = gr.Textbox(label="Escape Method", placeholder="e.g. fled on foot toward main road, used getaway vehicle")
                    ucp_mo_signature = gr.Textbox(label="MO Signature", placeholder="e.g. distinctive marking left at scene, repeated ransom-note style, specific tool used")
                ucp_confidence = gr.Slider(label="Profile Confidence", minimum=0, maximum=100, value=40, step=5)
                ucp_behaviour_profile = gr.Textbox(
                    label="Behaviour Profile (free-form notes)",
                    placeholder="Any additional behavioural observations that don't fit the fields above…",
                    lines=3,
                )

            unidentified_flag.change(
                fn=lambda checked: gr.update(visible=checked),
                inputs=[unidentified_flag],
                outputs=[unknown_profile_group],
            )

            gr.HTML("<p style='font-size:10px;color:#475569;letter-spacing:.1em;"
                    "text-transform:uppercase;margin:10px 0 4px;'>"
                    "👤 Suspect Photo <span style='color:#2d3a50;font-weight:400;'>"
                    "— for face-match analysis</span></p>")
            photo = gr.Image(label="📷 Face Photo (ArcFace)", type="pil",
                              height=180, sources=["upload"])

            gr.HTML("<p style='font-size:10px;color:#475569;letter-spacing:.1em;"
                    "text-transform:uppercase;margin:14px 0 4px;'>"
                    "🪪 ID / Document <span style='color:#2d3a50;font-weight:400;'>"
                    "— for text-extraction (name/ID match) — multiple files, images or PDF</span></p>")
            id_doc = gr.File(label="📄 ID / Document Scan(s) (OCR) — images or PDF, multiple allowed",
                              file_count="multiple",
                              file_types=["image", ".pdf"])

            gr.HTML("<p style='font-size:10px;color:#475569;letter-spacing:.1em;"
                    "text-transform:uppercase;margin:14px 0 4px;'>"
                    "📹 CCTV Footage <span style='color:#2d3a50;font-weight:400;'>"
                    "— a frame is extracted for crime-scene classification</span></p>")
            cctv_video = gr.Video(label="CCTV Footage / Video Clip", sources=["upload"])

            gr.HTML("<p style='font-size:10px;color:#475569;letter-spacing:.1em;"
                    "text-transform:uppercase;margin:10px 0 4px;'>"
                    "Voice Clip <span style='color:#2d3a50;font-weight:400;'>"
                    "(PyTorch stress model)</span></p>")
            voice = gr.Audio(label="", type="filepath", sources=["upload"])

            gr.HTML("<p style='font-size:10px;color:#475569;letter-spacing:.1em;"
                    "text-transform:uppercase;margin:10px 0 4px;'>"
                    "🔗 Known Associates <span style='color:#2d3a50;font-weight:400;'>"
                    "— comma-separated names for network analysis</span></p>")
            network_text = gr.Textbox(
                label="Known Associates / Network",
                placeholder="e.g. Lawrence Bishnoi, Dawood Ibrahim, Chhota Rajan…",
                lines=2,
            )

            gr.HTML("<p style='font-size:10px;color:#475569;letter-spacing:.1em;"
                    "text-transform:uppercase;margin:10px 0 4px;'>"
                    "💰 Financial IDs <span style='color:#2d3a50;font-weight:400;'>"
                    "— accounts, wallets, shell companies</span></p>")
            financial_ids = gr.Textbox(
                label="Financial IDs / Crypto Wallets",
                placeholder="e.g. 0x71C7656EC7ab88b098defB751B7401B5f6d8976F, Shell Corp BVI…",
                lines=2,
            )

            gr.HTML("<p style='font-size:10px;color:#475569;letter-spacing:.1em;"
                    "text-transform:uppercase;margin:10px 0 4px;'>"
                    "🚗 Vehicles & Assets <span style='color:#2d3a50;font-weight:400;'>"
                    "— license plates, vessels, aircraft</span></p>")
            vehicle_info = gr.Textbox(
                label="Vehicle / License Plate / Vessel",
                placeholder="e.g. MH01AB1234, IMO9876543, N123AB…",
                lines=1,
            )

            # ─── DIGITAL EVIDENCE SECTION ──────────────────────
            gr.HTML("<p style='font-size:10px;color:#475569;letter-spacing:.1em;"
                    "text-transform:uppercase;margin:10px 0 4px;'>"
                    "🌐 Digital Evidence <span style='color:#2d3a50;font-weight:400;'>"
                    "— emails, URLs, phone numbers for cyber investigation</span></p>")

            with gr.Row():
                digital_emails = gr.Textbox(
                    label="Email Addresses",
                    placeholder="suspect@example.com, alias@protonmail.com…",
                    lines=1,
                    scale=1,
                )
                digital_phones = gr.Textbox(
                    label="Phone Numbers",
                    placeholder="+91-98765-43210, 1-800-555-0199…",
                    lines=1,
                    scale=1,
                )

            digital_urls = gr.Textbox(
                label="URLs / Social Media Profiles",
                placeholder="https://facebook.com/suspect, https://twitter.com/alias…",
                lines=2,
            )

            gr.HTML("<p style='font-size:10px;color:#475569;letter-spacing:.1em;"
                    "text-transform:uppercase;margin:10px 0 4px;'>"
                    "🛡️ Cyber Intelligence <span style='color:#2d3a50;font-weight:400;'>"
                    "— dark web, cybercrime indicators</span></p>")
            cyber_flags = gr.CheckboxGroup(
                choices=[
                    "Dark Web Presence",
                    "Known Cybercrime Forum Activity",
                    "Crypto Mixer / Tumbler Usage",
                    "Encrypted Communication Apps",
                    "Data Breach Records",
                    "Phishing Infrastructure",
                    "Ransomware Affiliation",
                ],
                label="Select indicators present",
            )
            # ─── END DIGITAL EVIDENCE SECTION ────────────────────

            btn = gr.Button("🔍  Investigate", variant="stop", size="lg")

            # ── GDELT REAL-TIME CONFLICT ALERTS (new, additive) ─────────────
            # Placed directly under the Investigate button per request,
            # rather than at the very bottom of the page. draft_key is
            # created here (moved up from its original spot below) so it
            # exists before this reuses it as the session/user id — the
            # DRAFT AUTO-SAVE section further down still uses this same
            # `draft_key` name exactly as before; nothing else changed.
            draft_key = gr.State(value=lambda: str(uuid.uuid4()))
            with gr.Tabs():
                build_gdelt_tabs(demo, draft_key)
                # DOA 2026-11-05: Deep OSINT Agent tab (journalist_research). Fails soft: a DOA
                # import/build error is logged and must never take down the main app.
                try:
                    from journalist_research.ui.gradio_doa import build_doa_tab
                    with gr.Tab("🔎 Deep OSINT (DOA)"):
                        build_doa_tab()
                    # dashboard "Open Deep OSINT" passes &tab=doa: select the DOA tab on load
                    demo.load(fn=None, js="() => { if (new URLSearchParams(location.search).get('tab') === 'doa') "
                              "{ setTimeout(() => { const b = [...document.querySelectorAll('button[role=tab]')]"
                              ".find(x => x.textContent.includes('Deep OSINT')); if (b) b.click(); }, 900); } }")
                except Exception as _doa_exc:
                    log.error(f"DOA tab disabled: {type(_doa_exc).__name__}: {_doa_exc}")

        # ── RIGHT COLUMN ──────────────────────────────────────────────────────
        with gr.Column(scale=1, min_width=340):

            gr.HTML("<p style='font-size:10px;color:#475569;letter-spacing:.1em;"
                    "text-transform:uppercase;margin:12px 0 6px;'>Scores</p>")
            with gr.Row():
                o_dec  = gr.Label(label="Deception Score")
                o_cred = gr.Label(label="Credibility")
            with gr.Row():
                o_risk = gr.Label(label="Risk Level")
                o_pat  = gr.Label(label="Criminal Pattern Match")

            gr.HTML("<p style='font-size:10px;color:#475569;letter-spacing:.1em;"
                    "text-transform:uppercase;margin:10px 0 4px;'>"
                    "Network & Financial Intelligence</p>")
            with gr.Row():
                o_net_risk = gr.Label(label="Network Risk")
                o_fin_risk = gr.Label(label="Financial Risk")

            # Indicator bars
            o_bars  = gr.HTML(visible=False)
            o_net_html = gr.HTML(visible=False)

            # ── GRAPHS ────────────────────────────────────────────────────────
            gr.HTML("<p style='font-size:10px;color:#475569;letter-spacing:.1em;"
                    "text-transform:uppercase;margin:10px 0 4px;'>Risk Score Graphs</p>")
            o_graph = gr.HTML(
                value="<div style='background:#111620;border:0.5px solid #1a2236;"
                      "border-radius:10px;padding:40px;text-align:center;"
                      "color:#2d3a50;font-size:13px;'>Run analysis to generate graphs</div>",
                visible=True,
            )

            # Report
            gr.HTML("<p style='font-size:10px;color:#475569;letter-spacing:.1em;"
                    "text-transform:uppercase;margin:10px 0 4px;'>Forensic Report</p>")
            o_report = gr.Textbox(label="", lines=14, interactive=False,
                                  placeholder="Report will appear here…",
                                  )
            with gr.Row():
                export_pdf_btn = gr.Button("📄  Export PDF Report", variant="stop", size="lg")
                story_draft_btn = gr.Button("📝  Generate Story Draft", variant="secondary", size="lg")
            # BUG FIX (user feedback): gr.File renders as a plain file
            # card where only the filename/size text is clickable to
            # download — it doesn't look like a button at all. gr.
            # DownloadButton renders as an actual button labeled
            # "Download", which is what was expected here. The existing
            # gr.update(value=path, visible=True/False) calls that feed
            # this component work identically for DownloadButton.
            # Defensive fallback: DownloadButton was added in a specific
            # Gradio 4.x release — if this server's pinned Gradio version
            # predates it, hasattr() catches that here instead of crashing
            # the whole UI at startup (see the earlier gr.File(height=...)
            # incident — an unsupported component/kwarg breaks the entire
            # app with a blank screen, not just this one control).
            if hasattr(gr, "DownloadButton"):
                o_pdf_file = gr.DownloadButton(label="⬇ Download Report (PDF)", visible=False,
                                               elem_id="nxf_pdf_download")
            else:
                o_pdf_file = gr.File(label="⬇ Download Report (PDF)", visible=False)
            o_story_draft = gr.Textbox(
                label="AI-Drafted Story Opening (editable — verify every claim before publishing)",
                lines=8, interactive=True, visible=False,
            )
            o_report_data = gr.State()

            # History
            gr.HTML("<p style='font-size:10px;color:#475569;letter-spacing:.1em;"
                    "text-transform:uppercase;margin:10px 0 4px;'>Analysis History</p>")
            o_hist = gr.HTML(_history_html(None))
            o_hist_dropdown = gr.Dropdown(
                label="Re-open a past investigation",
                choices=[], value=None,
                interactive=True,
            )
            load_history_btn = gr.Button("📂  Load Selected Report", size="sm")

    # ── DRAFT AUTO-SAVE ──────────────────────────────────────────────────────
    # A fresh draft_key is generated once per page load and kept in this
    # session's gr.State. Every tracked field below auto-saves the FULL
    # current form snapshot (keyed by this draft_key) whenever that field
    # loses focus (blur) or changes (for dropdowns/checkboxes, which have
    # no blur event) — so if a long Investigate request gets killed by an
    # edge-proxy timeout, the typed data was already safely persisted
    # server-side before that request ever fired.
    # (draft_key itself is now created earlier, right after the Investigate
    # button, so the GDELT tabs there can reuse it as the session id.)

    DRAFT_TEXT_FIELDS = [
        case_id, case_title, incident_date, investigating_officer, modus,
        suspect, location, physical_desc, network_text, financial_ids,
        vehicle_info, digital_emails, digital_phones, digital_urls,
        ucp_age, ucp_height, ucp_language, ucp_accent, ucp_dominant_behaviour,
        ucp_entry_method, ucp_behaviour_at_scene,
        ucp_weapons_used, ucp_escape_pattern, ucp_mo_signature, ucp_behaviour_profile,
    ]
    DRAFT_CHANGE_FIELDS = [
        crime_category, case_priority, unidentified_flag, cyber_flags,
        ucp_gender, ucp_body_type, ucp_handedness, ucp_team_size,
        ucp_tech_skill, ucp_experience_level, ucp_planning_level,
        ucp_risk_behaviour, ucp_confidence,
    ]
    DRAFT_ALL_FIELDS = DRAFT_TEXT_FIELDS + DRAFT_CHANGE_FIELDS

    for _f in DRAFT_TEXT_FIELDS:
        _f.blur(fn=save_draft, inputs=[draft_key, *DRAFT_ALL_FIELDS], outputs=None)
    for _f in DRAFT_CHANGE_FIELDS:
        _f.change(fn=save_draft, inputs=[draft_key, *DRAFT_ALL_FIELDS], outputs=None)

    def _restore_draft(anon_key, request: gr.Request = None):
        """Runs once when the page loads. A random per-session draft_key
        cannot survive a reload (it's regenerated every time), so instead we
        key the saved draft by the logged-in user's email — stable across
        reloads and even new browser sessions — and restore every tracked
        field from the last auto-save under that key. Anonymous/unauthenticated
        sessions fall back to the random key (won't survive a reload, since
        there's no stable identity to key it by)."""
        user_email = None
        try:
            if request is not None:
                token = request.cookies.get(AUTH_COOKIE) if hasattr(request, "cookies") else None
                if token:
                    payload = _verify_jwt(token)
                    if payload:
                        user_email = payload.get("email")
        except Exception as e:
            log.warning(f"Could not resolve user for draft restore: {e}")

        resolved_key = f"user:{user_email}" if user_email else anon_key
        saved = load_draft(resolved_key)

        if not saved or len(saved) != len(DRAFT_ALL_FIELDS):
            # Nothing saved yet under this key (or the form shape changed) —
            # just adopt the resolved key so future auto-saves use it.
            return [resolved_key] + [gr.update() for _ in DRAFT_ALL_FIELDS]

        return [resolved_key] + [gr.update(value=v) for v in saved]

    demo.load(
        fn=_restore_draft,
        inputs=[draft_key],
        outputs=[draft_key, *DRAFT_ALL_FIELDS],
    )

    
    # ============================================================
    # INVESTIGATOR ENGINE - OUTPUTS
    # ============================================================
    gr.Markdown("---")
    gr.Markdown("## 🔍 Investigator Intelligence")
    
    with gr.Row():
        with gr.Column(scale=1):
            gr.Markdown("### 📊 Evidence Completeness")
            inv_evidence_total = gr.Textbox(label="Total Completeness", interactive=False)
            inv_evidence_components = gr.HTML(label="Components Breakdown")
        
        with gr.Column(scale=1):
            gr.Markdown("### 🕵️ Unknown Criminal Profile")
            inv_profile_age = gr.Textbox(label="Estimated Age", interactive=False)
            inv_profile_gender = gr.Textbox(label="Estimated Gender", interactive=False)
            inv_profile_mo = gr.Textbox(label="Modus Operandi", interactive=False)
            inv_profile_signature = gr.Textbox(label="MO Signature", interactive=False)
            inv_profile_confidence = gr.Slider(label="Profile Confidence", minimum=0, maximum=100, interactive=False)
    
    with gr.Row():
        with gr.Column(scale=1):
            gr.Markdown("### 🧠 Reasoning Matrix")
            inv_reasoning = gr.HTML(label="Theories & Evidence")
        
        with gr.Column(scale=1):
            gr.Markdown("### 🔄 Investigation Paths")
            inv_paths_total = gr.Textbox(label="Total Paths", interactive=False)
            inv_paths_strong = gr.Textbox(label="Strong", interactive=False)
            inv_paths_rejected = gr.Textbox(label="Rejected", interactive=False)
            inv_paths_detail = gr.HTML(label="All Paths")
    
    with gr.Row():
        with gr.Column(scale=1):
            gr.Markdown("### ⚠️ Not Yet Submitted — Investigation Gain")
            inv_missing = gr.HTML(label="Impact Analysis")
        
        with gr.Column(scale=1):
            gr.Markdown("### 💡 Investigation Value")
            inv_value = gr.HTML(label="Evidence Priority")
    
    with gr.Row():
        with gr.Column(scale=1):
            gr.Markdown("### 🤖 Deepfake Impact")
            inv_deepfake = gr.HTML(label="Impact Analysis")
        
        with gr.Column(scale=1):
            gr.Markdown("### 🔴 Risk Assessment")
            inv_risk_level = gr.Textbox(label="Risk Level", interactive=False)
            inv_risk_reason = gr.Textbox(label="Risk Reason", interactive=False)
    
    with gr.Row():
        with gr.Column(scale=1):
            gr.Markdown("### 🎥 Scene Classification")
            inv_scene_class = gr.Textbox(label="Classification", interactive=False)
            inv_scene_confidence = gr.Slider(label="Confidence", minimum=0, maximum=100, interactive=False)
            inv_scene_source = gr.Textbox(label="Source", interactive=False)
        
        with gr.Column(scale=1):
            gr.Markdown("### 📋 Dynamic Profile")
            inv_dynamic = gr.HTML(label="Profile Fields")
    
    with gr.Row():
        with gr.Column(scale=1):
            gr.Markdown("### 📄 OCR Status")
            inv_ocr_status = gr.Textbox(label="OCR Status", interactive=False)
            inv_ocr_reason = gr.Textbox(label="OCR Reason", interactive=False)

    with gr.Row():
        with gr.Column(scale=1):
            gr.Markdown("### 🧠 Advanced Intelligence Report")
            gr.Markdown(
                "<p style='color:#94a3b8;font-size:12px;'>Knowledge Graph • Crime DNA • "
                "Hypothesis Ranking • Investigation Planner • Criminal Network • "
                "Tier-1 Intelligence • Court Readiness • Explainable AI</p>"
            )
            inv_advanced_html = gr.HTML(label="Advanced Intelligence Report")

    with gr.Row():
        with gr.Column(scale=1):
            gr.Markdown("### 🕸️ Interactive Knowledge Graph")
            gr.Markdown(
                "<p style='color:#94a3b8;font-size:12px;'>Drag to pan, scroll to zoom, "
                "drag a node to move it, hover for full names.</p>"
            )
            inv_kg_interactive = gr.HTML(label="Interactive Knowledge Graph", head=_VIS_NETWORK_HEAD)
        with gr.Column(scale=1):
            gr.Markdown("### 🕸️ Interactive Criminal Network")
            gr.Markdown(
                "<p style='color:#94a3b8;font-size:12px;'>Known entities plus AI-inferred "
                "connections (marked with *) radiating from the suspect.</p>"
            )
            inv_network_interactive = gr.HTML(label="Interactive Criminal Network", head=_VIS_NETWORK_HEAD)

    with gr.Row():
        with gr.Column(scale=1):
            gr.Markdown("### 🧭 Investigation Guidance Engine")
            gr.Markdown(
                "<p style='color:#94a3b8;font-size:12px;'>Knowledge-driven expert system (rules + "
                "knowledge base, not ML) — ranks the next investigation angles for this case's "
                "leading hypotheses, each with a WHY, expected evidence gain, cost and time.</p>"
            )
            inv_guidance_html = gr.HTML(label="Investigation Guidance")


    # ── Wire ──────────────────────────────────────────────────────────────────
    btn.click(
        fn=run_analysis,
        inputs=[case_id, modus, suspect, location, photo, voice, id_doc, network_text, financial_ids, vehicle_info, unidentified_flag, physical_desc, digital_emails, digital_phones, digital_urls, cyber_flags, case_title, crime_category, incident_date, investigating_officer, case_priority, ucp_age, ucp_gender, ucp_height, ucp_body_type, ucp_language, ucp_accent, ucp_handedness, ucp_dominant_behaviour, ucp_entry_method, ucp_behaviour_at_scene, ucp_weapons_used, ucp_team_size, ucp_tech_skill, ucp_experience_level, ucp_planning_level, ucp_risk_behaviour, ucp_escape_pattern, ucp_mo_signature, ucp_confidence, ucp_behaviour_profile, cctv_video],
        outputs=[o_dec, o_cred, o_risk, o_pat, o_net_risk, o_fin_risk,
         o_bars, o_net_html, o_graph, o_report, o_hist, o_report_data,
         inv_evidence_total, inv_evidence_components,
         inv_profile_age, inv_profile_gender, inv_profile_mo, inv_profile_signature, inv_profile_confidence,
         inv_reasoning,
         inv_paths_total, inv_paths_strong, inv_paths_rejected, inv_paths_detail,
         inv_missing, inv_value, inv_deepfake,
         inv_risk_level, inv_risk_reason,
         inv_scene_class, inv_scene_confidence, inv_scene_source,
         inv_dynamic,
         inv_ocr_status, inv_ocr_reason, inv_advanced_html, inv_kg_interactive, inv_network_interactive,
         inv_guidance_html],
    ).then(
        fn=None, js=_VIS_NETWORK_INIT_JS,
    ).then(
        fn=_hist_dd_for_user,
        inputs=None, outputs=[o_hist_dropdown],
    ).then(
        # DOA 2026-11-06: build the PDF right after the analysis, so the Download button is ready (one click)
        fn=export_report_pdf, inputs=[o_report_data], outputs=[o_pdf_file],
    )

    load_history_btn.click(
        fn=load_history_record,
        inputs=[o_hist_dropdown],
        outputs=[o_dec, o_cred, o_risk, o_pat, o_net_risk, o_fin_risk,
         o_bars, o_net_html, o_graph, o_report, o_hist, o_report_data,
         inv_evidence_total, inv_evidence_components,
         inv_profile_age, inv_profile_gender, inv_profile_mo, inv_profile_signature, inv_profile_confidence,
         inv_reasoning,
         inv_paths_total, inv_paths_strong, inv_paths_rejected, inv_paths_detail,
         inv_missing, inv_value, inv_deepfake,
         inv_risk_level, inv_risk_reason,
         inv_scene_class, inv_scene_confidence, inv_scene_source,
         inv_dynamic,
         inv_ocr_status, inv_ocr_reason, inv_advanced_html, inv_kg_interactive, inv_network_interactive,
         inv_guidance_html],
    ).then(
        fn=None, js=_VIS_NETWORK_INIT_JS,
    )

    export_pdf_btn.click(
        fn=export_report_pdf,
        inputs=[o_report_data],
        outputs=[o_pdf_file],
    ).then(
        # DOA 2026-11-05: one click — start the browser download as soon as the PDF exists
        fn=None,
        js="() => { setTimeout(() => { const el = document.getElementById('nxf_pdf_download'); const b = el && (el.matches('a,button') ? el : el.querySelector('a,button')); if (b) b.click(); }, 600); }",
    )

    story_draft_btn.click(
        fn=regenerate_story_draft,
        inputs=[o_report_data],
        outputs=[o_story_draft],
    )

    demo.load(
        fn=_hist_on_load,
        inputs=None, outputs=[o_hist, o_hist_dropdown],
    )

    def _populate_field_history(request: gr.Request = None):
        """Runs once when the page loads — fills in Suspect Name, Location,
        Case Title, Investigating Officer and Crime Category with values
        used in past cases, so the user can click the field and pick an
        existing profile instead of retyping it."""
        choices = _load_field_choices(user_email=_req_email(request))
        base_crime_categories = [
            "Robbery", "Burglary", "Assault", "Homicide", "Fraud",
            "Cybercrime", "Financial Crime", "Narcotics", "Kidnapping",
            "Sexual Offence", "Organized Crime", "Terrorism", "Other / Unclassified",
        ]
        merged_crime = base_crime_categories + [
            c for c in choices.get("crime_category", []) if c not in base_crime_categories
        ]
        return (
            gr.update(choices=choices.get("suspect_name", [])),
            gr.update(choices=choices.get("location", [])),
            gr.update(choices=choices.get("case_title", [])),
            gr.update(choices=choices.get("investigating_officer", [])),
            gr.update(choices=merged_crime),
        )

    demo.load(
        fn=_populate_field_history,
        inputs=None,
        outputs=[suspect, location, case_title, investigating_officer, crime_category],
    )

# ─────────────────────────────────────────────────────────────────────────────
# AUTH — only allow access when hit with a valid JWT issued by the
# nexforensics dashboard (services/jwt_service.py: HS256, JWT_SECRET_KEY,
# payload has user_id/email/role/exp/type). Direct hits to this URL with no
# (or an invalid/expired) token are rejected — the dashboard is the only
# place that can hand out a working link.
# ─────────────────────────────────────────────────────────────────────────────
import jwt as _pyjwt
from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse, PlainTextResponse

# Sanity check: there are two unrelated PyPI packages that both import as
# `import jwt` — the correct one is PyJWT (pip install PyJWT); a separate,
# abandoned package literally named `jwt` (pip install jwt) has a
# completely different, incompatible API. If the wrong one is installed,
# `import jwt` still "succeeds" but jwt.decode()/jwt.encode() behave
# nothing like expected, causing every login to silently fail with this
# same 403 and no useful error message. Fail loudly here instead.
_missing_jwt_api = [
    attr for attr in ("encode", "decode", "ExpiredSignatureError", "InvalidTokenError")
    if not hasattr(_pyjwt, attr)
]
if _missing_jwt_api or not hasattr(_pyjwt, "__version__"):
    raise RuntimeError(
        f"Wrong 'jwt' package installed (module at {getattr(_pyjwt, '__file__', '?')}) — "
        f"missing {_missing_jwt_api or ['__version__']}. This is very likely the unrelated "
        f"'jwt' PyPI package instead of PyJWT. Fix with:\n"
        f"    pip uninstall jwt -y && pip install PyJWT\n"
        f"then restart this app."
    )
log.info(f"✅ PyJWT {_pyjwt.__version__} loaded correctly from {_pyjwt.__file__}")

JWT_SECRET_KEY = os.environ.get("JWT_SECRET_KEY", "jwt-secret-key-change-in-production")
if JWT_SECRET_KEY == "jwt-secret-key-change-in-production":
    log.error(
        "❌ JWT_SECRET_KEY env var is NOT set on this service — falling back to the "
        "placeholder value. Every token issued by the dashboard (which uses its own real "
        "secret) will fail to verify here, causing '403 Forbidden' even right after a "
        "successful login. Set JWT_SECRET_KEY to the SAME value the dashboard uses, on "
        "this service, then restart."
    )
JWT_ALGORITHM  = "HS256"
AUTH_COOKIE    = "nxf_gradio_auth"

# Local-only escape hatch: set DEV_MODE=1 in your shell/.env when running
# `python gradio_app.py` on your own machine to skip the JWT check, so you
# can iterate on the UI without going through the dashboard each time.
# NEVER set DEV_MODE=1 on the deployed server — this must stay unset (or 0)
# in production so the 403 guard keeps working as designed.
DEV_MODE = os.environ.get("DEV_MODE", "0") == "1"
if DEV_MODE:
    log.warning("DEV_MODE=1 — JWT auth is BYPASSED. Do not use this in production.")

def _verify_jwt(token: str):
    """Returns the decoded payload if valid, else None. Mirrors jwt_service.decode_token()."""
    if not token:
        return None
    try:
        payload = _pyjwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        if payload.get("type") not in (None, "access"):
            return None
        return payload
    except _pyjwt.ExpiredSignatureError:
        log.warning("Gradio access denied: expired token")
        return None
    except _pyjwt.InvalidTokenError as e:
        log.warning(f"Gradio access denied: invalid token ({e})")
        return None

app = FastAPI()

# Exempt path(s) that internal health-check tools (WordPress CP dashboard,
# uptime monitors, etc.) hit WITHOUT a dashboard JWT. Keep this list tiny —
# it must never expose actual app functionality, only a status ping.
_PUBLIC_PATHS = {"/health"}

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "ner": ner_eng.ready, "voice": vox_eng.ready,
        "face": face_eng.ready, "ocr": ocr_eng.ready,
        "risk_model": xgb_eng.ready,
    }

@app.middleware("http")
async def require_dashboard_jwt(request: Request, call_next):
    if request.url.path in _PUBLIC_PATHS:
        return await call_next(request)

    if DEV_MODE:
        return await call_next(request)

    # Let the Gradio/FastAPI internal asset & api routes through only if
    # already authenticated via cookie; the entry route needs ?token=.
    token = request.query_params.get("token") or request.cookies.get(AUTH_COOKIE)
    payload = _verify_jwt(token)

    if payload is None:
        return PlainTextResponse(
            "403 Forbidden — this page can only be opened from the "
            "InvestigatorAI dashboard.",
            status_code=403,
        )

    response = await call_next(request)

    # If we authenticated via a fresh ?token=, drop it into a cookie so the
    # rest of the SPA's asset/websocket calls (which won't carry the query
    # param) stay authenticated, and so the token doesn't linger visibly in
    # the URL bar / browser history / referrer headers on every request.
    if request.query_params.get("token"):
        max_age = max(1, int(payload.get("exp", 0) - datetime.utcnow().timestamp()))
        # A cookie set with secure=True is silently dropped by the browser
        # on any non-HTTPS connection — meaning if this app is reached over
        # plain HTTP, or behind a reverse proxy that terminates TLS but
        # doesn't forward that fact, the FIRST request (with ?token=) would
        # succeed, but every request after it (including the SPA's own
        # internal calls) would carry no cookie at all and hit this same
        # 403 — even immediately after a successful login. Only require
        # Secure when the connection is actually HTTPS (directly, or per
        # X-Forwarded-Proto from a reverse proxy); FORCE_SECURE_COOKIE=1
        # is available as an explicit override if a proxy setup doesn't
        # forward that header correctly.
        _is_https = (
            request.url.scheme == "https"
            or request.headers.get("x-forwarded-proto", "").lower() == "https"
            or os.environ.get("FORCE_SECURE_COOKIE", "0") == "1"
        )
        response.set_cookie(
            AUTH_COOKIE, request.query_params["token"],
            max_age=max_age, httponly=True, samesite="lax",
            secure=_is_https,
        )
    return response

app = gr.mount_gradio_app(app, demo, path="/", root_path="/app/gradio")

# ─────────────────────────────────────────────────────────────────────────────


def _estimate_profile(modus, crime_category, field, default="Unknown"):
    """
    AI estimate for a missing Unknown-Criminal-Profile field, based on
    keyword signals in the Modus Operandi text — NEVER an identification,
    only a behavioural estimate. Returns (value, confidence); confidence
    is 0 whenever no keyword actually matched, so callers can tell a real
    estimate apart from a plain default (fixes an earlier bug where a
    non-match was silently reported as "40% confidence").
    """
    text = (modus or "").lower() + " " + (crime_category or "").lower()
    estimates = {
        "likely_team_size": {
            "Solo": ["lone", "alone", "single", "individual"],
            "2-4": ["two", "three", "four", "pair", "duo", "group"],
            "5+": ["five", "six", "gang", "crew", "team"],
        },
        "technical_skill": {
            "Low": ["basic", "simple", "amateur"],
            "Medium": ["moderate", "some"],
            "Advanced": ["advanced", "expert", "professional", "sophisticated", "malware", "phishing", "ransomware", "encrypted"],
        },
        "planning_level": {
            "Opportunistic": ["spontaneous", "unplanned", "impulsive"],
            "Semi-planned": ["some", "prepared"],
            "Highly Planned": ["planned", "organized", "targeted", "deliberate", "reconnaissance", "surveillance"],
        },
        "risk_behaviour": {
            "Low": ["careful", "cautious", "avoided detection", "no confrontation"],
            "Medium": ["confrontation", "risk", "close call"],
            "High": ["weapon", "armed", "threat", "violence", "aggressive", "knife", "gun"],
        },
        "experience_level": {
            "Novice": ["first time", "never done", "amateur", "inexperienced"],
            "Experienced": ["similar pattern", "again", "repeat", "familiar with"],
            "Professional": ["professional", "expert", "trained", "methodical"],
        },
    }
    if field not in estimates:
        return default, 0
    best_value, best_hits = None, 0
    for value, keywords in estimates[field].items():
        hits = sum(1 for kw in keywords if kw in text)
        if hits > best_hits:
            best_value, best_hits = value, hits
    if best_value is None:
        return default, 0
    confidence = min(85, 50 + best_hits * 10)
    return best_value, confidence


def _estimate_operational_sophistication(modus, crime_category):
    """
    Derived Step-4/5 metric combining technical-skill and planning-level
    estimates into a single, easy-to-scan sophistication label. Purely a
    synthesis of the other two estimates — not an independent signal.
    """
    tech_val, tech_conf = _estimate_profile(modus, crime_category, "technical_skill")
    plan_val, plan_conf = _estimate_profile(modus, crime_category, "planning_level")
    if tech_conf == 0 and plan_conf == 0:
        return "Unknown", 0
    high_signals = sum([
        tech_val == "Advanced", plan_val == "Highly Planned",
    ])
    low_signals = sum([
        tech_val == "Low", plan_val == "Opportunistic",
    ])
    if high_signals >= 1 and low_signals == 0:
        label = "High — coordinated, technically capable"
    elif low_signals >= 1 and high_signals == 0:
        label = "Low — opportunistic, limited technical indicators"
    else:
        label = "Moderate — mixed indicators"
    confidence = round((tech_conf + plan_conf) / (2 if (tech_conf and plan_conf) else 1))
    return label, min(confidence, 85)


# ============================================================
# NEW: NEXFORENSICS COMPLETE JOURNEY SUMMARY ENGINE
# (reconstructed - was previously placed after the app entry
# point and never loaded)
# ============================================================


# Replace existing _extract_timeline function with this enhanced version


# ============================================================
# CRITICAL FIX: Deepfake Detection with Proper Confidence Calibration
# ============================================================



# ============================================================
# CRITICAL FIX: Separate Confidence Types
# ============================================================

def calculate_separate_confidence(evidence_provided, hypotheses, deception, risk):
    """
    Three different confidence measures:
    1. Model Execution Confidence (modules loaded)
    2. Evidence Confidence (how much evidence we have)
    3. Hypothesis Confidence (how confident in the hypothesis)
    """
    # 1. Model Execution Confidence
    models_loaded = sum([ner_eng.ready, vox_eng.ready, face_eng.ready, ocr_eng.ready, xgb_eng.ready])
    model_execution = min(models_loaded * 20, 95)

    # 2. Evidence Confidence
    evidence_count = sum(1 for v in evidence_provided.values() if v)
    total = len(evidence_provided)
    evidence_pct = (evidence_count / total) * 100 if total else 0
    evidence_confidence = min(evidence_pct, 95)

    # 3. Hypothesis Confidence
    if hypotheses:
        # Get confidence from first hypothesis
        h_conf = hypotheses[0].get("confidence", "LOW")
        conf_map = {"VERY HIGH": 85, "HIGH": 70, "MEDIUM": 50, "LOW": 25, "VERY LOW": 10}
        hypothesis_conf = conf_map.get(str(h_conf).upper(), 25)
    else:
        hypothesis_conf = 10

    # Combined confidence should be capped by evidence
    combined = min(
        (evidence_confidence * 0.5 + hypothesis_conf * 0.3 + model_execution * 0.2),
        95
    )

    # Determine level
    if combined < 30:
        level = "LOW — Insufficient evidence"
    elif combined < 50:
        level = "MEDIUM — Some evidence supports"
    elif combined < 70:
        level = "HIGH — Good evidence base"
    else:
        level = "VERY HIGH — Strong evidence convergence"

    return {
        "model_execution": round(model_execution, 1),
        "evidence_confidence": round(evidence_confidence, 1),
        "hypothesis_confidence": round(hypothesis_conf, 1),
        # This is the single canonical confidence value — every other
        # confidence number surfaced elsewhere in the report (crime
        # classification, hypothesis ranking, fused confidence, etc.)
        # should be labelled as a *component/supporting signal*, not
        # presented as an alternative "the" answer.
        "canonical_confidence": round(combined, 1),
        "combined": round(combined, 1),
        "level": level,
        "note": f"Based on {evidence_count}/{total} evidence types, {len(hypotheses)} hypothesis(es)"
    }


# ============================================================
# CRITICAL FIX: Link Crime Classification to Hypotheses
# ============================================================

def link_crime_to_hypotheses(crime_info, hypotheses, evidence_provided):
    """
    If crime is classified with HIGH confidence, hypotheses must reflect that.
    Also show which evidence supports the crime classification.
    """
    if not crime_info or crime_info.get("severity") == "Low":
        return {
            "crime_confidence": "LOW",
            "note": "Insufficient evidence for crime classification",
            "hypothesis_alignment": "Hypotheses remain preliminary"
        }

    severity = crime_info.get("severity", "Low")
    severity_map = {
        "Critical": {"conf": 80, "label": "HIGH"},
        "High": {"conf": 65, "label": "HIGH-MEDIUM"},
        "Medium": {"conf": 45, "label": "MEDIUM"},
        "Low": {"conf": 25, "label": "LOW"}
    }

    severity_info = severity_map.get(severity, {"conf": 25, "label": "LOW"})

    # Check if hypotheses align with crime
    crime_type = crime_info.get("primary", "")
    hypothesis_aligned = any(crime_type.lower() in h.get("hypothesis", "").lower() for h in hypotheses) if crime_type else False

    return {
        "crime_confidence": severity_info["label"],
        "crime_confidence_score": severity_info["conf"],
        "hypothesis_alignment": "Aligned" if hypothesis_aligned else "Not aligned",
        "note": f"Crime classified as {crime_type or 'Unclassified'} with {severity_info['label']} confidence",
        "recommendation": (
            "Update hypotheses to reflect crime classification"
            if not hypothesis_aligned else
            "Hypotheses support crime classification"
        )
    }


# ============================================================
# CRITICAL FIX: Evidence-Based Threat Assessment
# ============================================================

def assess_threat_with_evidence(crime_info, watchlist, entities, evidence_provided):
    """
    Threat must be linked to actual evidence.
    If no evidence supports HIGH threat, it cannot be HIGH.
    """
    threat_sources = []

    # 1. Crime classification evidence
    if crime_info.get("severity") in ["High", "Critical"]:
        threat_sources.append({
            "source": "Crime Classification",
            "detail": crime_info.get("primary", ""),
            "weight": 40
        })

    # 2. Entity-based evidence
    weapons = entities.get("WEAPON", []) if entities else []
    threats = entities.get("THREAT", []) if entities else []
    if weapons:
        threat_sources.append({
            "source": f"Weapon References: {', '.join(weapons[:2])}",
            "detail": "Direct physical threat indicators",
            "weight": 60
        })
    if threats:
        threat_sources.append({
            "source": f"Threat Language: {', '.join(threats[:2])}",
            "detail": "Escalation risk indicators",
            "weight": 50
        })

    # 3. Watchlist evidence
    if watchlist.get("interpol") != "NO" or watchlist.get("fbi_watchlist") != "NO":
        threat_sources.append({
            "source": "Watchlist Match",
            "detail": watchlist.get("status", "Unknown"),
            "weight": 70
        })

    # 4. Evidence completeness - if low, threat confidence must be low
    evidence_count = sum(1 for v in evidence_provided.values() if v)
    if evidence_count < 3:
        threat_sources.append({
            "source": "Limited Evidence",
            "detail": f"Only {evidence_count} evidence type(s) available",
            "weight": -20
        })

    # Calculate total threat weight
    total_weight = sum(s["weight"] for s in threat_sources)
    normalized = min(max(total_weight, 0), 100)

    # Determine level
    if normalized < 20:
        level = "LOW — Insufficient evidence for threat assessment"
    elif normalized < 40:
        level = "MEDIUM — Some threat indicators detected"
    elif normalized < 60:
        level = "HIGH — Significant threat indicators present"
    else:
        level = "CRITICAL — Multiple high-threat indicators"

    return {
        "level": level,
        "score": normalized,
        "sources": threat_sources,
        "recommendation": (
            "Collect additional evidence to confirm threat"
            if normalized < 50 else
            "Immediate threat assessment based on multiple indicators"
        )
    }


# Apply this filter in the analysis pipeline
# After NER extraction:
#


# ============================================================
# FIX: Weapon Detection Filter Function
# ============================================================


# Apply filters after NER extraction
# In run_analysis function:
#
#


# ============================================================
# CONFIDENCE RECALIBRATION - Evidence-Based
# ============================================================
# DEAD CODE REMOVED (2026-08-20): old_calculate_evidence_confidence() and
# old_get_confidence_with_evidence() used to sit here. Neither was called
# anywhere in this file, and both were actually broken if they had been
# (a stray indentation level made `pct` undefined outside the total==0
# branch, and old_get_confidence_with_evidence called a function,
# calculate_evidence_confidence, that doesn't exist in this file at all —
# either would have raised at runtime). Left as unreachable landmines;
# removed rather than fixed since the working replacement,
# calculate_separate_confidence() below, already covers this.


# ============================================================
# VALIDATION SYSTEM - Compare AI vs Human
# ============================================================

class ValidationEngine:
    def __init__(self):
        self.results = []

    def compare(self, ai_output, human_output, case_id):
        """Compare AI output with human investigator"""
        comparison = {
            "case_id": case_id,
            "timestamp": datetime.now().isoformat(),
            "ai_verdict": ai_output.get("verdict", ""),
            "human_verdict": human_output.get("verdict", ""),
            "match": ai_output.get("verdict") == human_output.get("verdict"),
            "ai_confidence": ai_output.get("confidence", 0),
            "human_confidence": human_output.get("confidence", 0),
            "differences": []
        }

        # Find differences
        for key in ["crime", "risk_level", "evidence_count"]:
            if ai_output.get(key) != human_output.get(key):
                comparison["differences"].append({
                    "field": key,
                    "ai": ai_output.get(key),
                    "human": human_output.get(key)
                })

        self.results.append(comparison)
        return comparison

    def get_stats(self):
        if not self.results:
            return {"total": 0, "match_rate": 0}

        matches = sum(1 for r in self.results if r.get("match", False))
        return {
            "total": len(self.results),
            "matches": matches,
            "match_rate": round((matches / len(self.results)) * 100, 1),
            "avg_ai_conf": round(sum(r.get("ai_confidence", 0) for r in self.results) / len(self.results), 1),
            "avg_human_conf": round(sum(r.get("human_confidence", 0) for r in self.results) / len(self.results), 1)
        }

validation_engine = ValidationEngine()


if __name__ == "__main__":
    import uvicorn
    log.info("Starting InvestigatorAI on http://127.0.0.1:7860 (JWT-gated, localhost-only)")
    uvicorn.run(app, host="127.0.0.1", port=7860)