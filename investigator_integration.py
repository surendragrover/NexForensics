# ============================================================
# INVESTIGATOR INTEGRATION - COMPLETE
# ============================================================

import logging
import re
from typing import Dict, Any, List, Optional


def _kw_in(keyword, text):
    """Word-boundary keyword match — see matching fix + rationale in
    gradio_app.py's `_kw_in` (same bug class: naive `keyword in text`
    substring checks match inside unrelated words — e.g. "team" inside
    "steam", "planned" inside "unplanned" (inverting the meaning),
    "rape" inside "therapeutic"). Word-boundary matching prevents this.
    """
    if not text:
        return False
    return bool(re.search(r'\b' + re.escape(keyword) + r'\b', text))


# Phase 1 (2026-08-27): Criminal/Wanted-List Match wiring. Imported inside
# a try/except so that if these modules are missing/broken on a given
# deployment, the rest of the report generation continues unaffected —
# criminal_match simply reports itself unavailable rather than crashing
# the whole pipeline.
try:
    from combined_match_engine import combined_match
    _CRIMINAL_MATCH_AVAILABLE = True
except Exception as _cm_import_err:
    _CRIMINAL_MATCH_AVAILABLE = False
    _CRIMINAL_MATCH_IMPORT_ERROR = str(_cm_import_err)

try:
    from identity_resolution import IdentityResolutionEngine
    _IDENTITY_RESOLUTION_AVAILABLE = True
except Exception as _ir_import_err:
    _IDENTITY_RESOLUTION_AVAILABLE = False
    _IDENTITY_RESOLUTION_IMPORT_ERROR = str(_ir_import_err)

# Keyword sets used to build the attribute dict passed into
# IdentityResolutionEngine.match_person() — deliberately reused from the
# same violent-crime keyword vocabulary already used elsewhere tonight,
# split into weapon vs. attack-method buckets so the weighted scorer can
# treat them as distinct factors rather than one blanket "crime keyword".
_ID_RES_WEAPON_KEYWORDS = ["firearm", "handgun", "gun", "weapon", "knife", "blade", "torch", "jammer"]
_ID_RES_ATTACK_KEYWORDS = ["executed", "shot", "stabbed", "strangled", "kidnapped", "extorted", "hacked"]

# ── Case Domain Classification ───────────────────────────────────────────
# BUG FIX (P1/root-cause — reviewer feedback, NXF-4349 review): every
# hypothesis, Crime DNA dimension, scene classification, risk level, and
# Investigation Planner direction below used to be built from ONE hardcoded
# physical-crime/burglary template ("thermal cutting torch", "vault
# robbery") regardless of what kind of case this actually is. A banking/
# debt-recovery case with no weapon, no physical entry, and no violence in
# it would still get "Professional organized crime operation: 55%",
# Crime DNA Escape=7/10 and Execution=8/10, a "Vault Robbery" scene
# classification, and an Investigation Planner recommending CCTV/witness
# statements/employee access logs — none of which are meaningful for that
# case. This single leak cascades into the hypothesis engine, threat
# classification, and the planner simultaneously, which is exactly the
# pattern the reviewer traced. Fix: classify the case's domain first
# (financial/fraud vs. physical/violent-crime vs. unknown/generic) from
# crime_category + mo_description, then branch every one of those
# templates on it instead of using one template for everything.
_FINANCIAL_DOMAIN_KEYWORDS = [
    "bank", "banking", "loan", "credit", "debt", "haircut", "npa",
    "non-performing", "insolvency", "bankruptcy", "creditor", "lender",
    "guarantee", "collateral", "recovery", "restructuring", "resolution",
    "asset reconstruction", "default", "exposure", "valuation",
    "related-party", "related party", "fraud", "embezzlement", "laundering",
    "shell company", "siphon", "diversion of funds", "financial",
    # Broadened (reviewer feedback, NHAI toll-fraud case): the original
    # list was banking/lending-specific and missed other common white-
    # collar/economic-crime vocabulary, which meant a case like unauthorised
    # toll-collection software / receipt manipulation / revenue concealment
    # fell through to "generic" and got the physical-crime burglary template
    # instead (see _classify_case_domain below for the "generic" handling).
    "corruption", "bribery", "kickback", "misappropriation", "misappropriate",
    "embezzle", "revenue concealment", "receipt manipulation", "invoice",
    "billing fraud", "skimming", "unauthorised software", "unauthorized software",
    "toll collection", "accounting fraud", "ghost entries", "shell entity",
    "money laundering", "tax evasion", "procurement fraud", "tender fraud",
]
_PHYSICAL_DOMAIN_KEYWORDS = [
    "robbery", "burglary", "torch", "cutting torch", "thermal", "vault",
    "weapon", "firearm", "gun", "knife", "assault", "murder", "homicide",
    "kidnap", "hostage", "break-in", "break in", "forced entry",
]


def _classify_case_domain(crime_category: str, mo_description: str) -> str:
    """Returns 'financial', 'physical', or 'generic' based on crime_category
    and the case narrative — see BUG FIX note above for why this exists."""
    cat = (crime_category or "").lower()
    mo = (mo_description or "").lower()
    text = f"{cat} {mo}"
    fin_hits = sum(1 for kw in _FINANCIAL_DOMAIN_KEYWORDS if _kw_in(kw, text))
    phys_hits = sum(1 for kw in _PHYSICAL_DOMAIN_KEYWORDS if _kw_in(kw, text))
    if fin_hits > 0 and fin_hits >= phys_hits:
        return "financial"
    if phys_hits > 0:
        return "physical"
    return "generic"

logger = logging.getLogger(__name__)


# ── Evidence Strength Matrix / Confidence Fusion ─────────────────────────
# BUG FIX (2026-08-20): this block used to be hardcoded — it always
# reported Face=92%, Vehicle=85%, Digital=74% regardless of whether that
# evidence was actually submitted for the case (e.g. Face showed 92% even
# when no photo was uploaded and Evidence Completeness / OCR both correctly
# said "NOT SUBMITTED"). This produced a direct contradiction in the PDF
# report between the Evidence Completeness section and the Evidence
# Strength Matrix section.
#
# Fix: only include an evidence type in the fusion/contributions table if
# it was actually submitted (present in `evidence`), and derive its
# confidence from the analysis quality already recorded for that item
# ("good"/"poor") rather than a fixed constant.
_EVIDENCE_BASE_CONFIDENCE = {
    "face": 92, "voice": 80, "document": 70, "cctv": 75,
    "financial": 68, "vehicle": 85, "digital": 74,
}
_EVIDENCE_BASE_WEIGHT = {
    "face": 20, "voice": 18, "document": 16, "cctv": 14,
    "financial": 12, "vehicle": 10, "digital": 10,
}


def _safe_truncate(text, limit=100):
    """Word-boundary-safe truncation — mirrors gradio_app.py's helper of
    the same name. BUG FIX (2026-08-20 — Medium): modus_operandi used to
    be hard-cut with mo_description[:100], slicing mid-word (e.g. "...after
    severing the p") with no "…" to signal the cut, which read as
    corrupted text rather than intentionally shortened text."""
    text = str(text or "")
    if len(text) <= limit:
        return text
    cut = text[:limit]
    last_space = cut.rfind(" ")
    if last_space > limit * 0.6:
        cut = cut[:last_space]
    return cut.rstrip() + "…"


def _build_confidence_fusion_detail(evidence: Dict[str, Any], risk_level: str) -> Dict[str, Any]:
    """Build the Evidence Strength Matrix / confidence-fusion block from
    ONLY the evidence types actually submitted for this case."""
    contributions = {}
    submitted = [k for k in evidence.keys() if k in _EVIDENCE_BASE_CONFIDENCE]
    total_weight = sum(_EVIDENCE_BASE_WEIGHT.get(k, 10) for k in submitted) or 1

    for key in submitted:
        item = evidence.get(key) or {}
        quality = item.get("quality", "good") if isinstance(item, dict) else "good"
        base_conf = _EVIDENCE_BASE_CONFIDENCE.get(key, 60)
        # Poor-quality analysis (e.g. OCR extracted no text, low-confidence
        # face match) should visibly lower the reported confidence rather
        # than showing the same fixed number regardless of outcome.
        confidence = base_conf if quality == "good" else max(30, base_conf - 25)
        weight = round(_EVIDENCE_BASE_WEIGHT.get(key, 10) / total_weight, 2)
        contributions[key] = {
            "confidence": confidence,
            "weight": weight,
            "contribution": round(confidence * weight, 1),
        }

    if contributions:
        fused_confidence = round(
            sum(c["contribution"] for c in contributions.values()), 1
        )
    else:
        # No usable evidence submitted at all — fall back to the
        # narrative-only risk estimate, but never fabricate a per-evidence
        # score for evidence that was never provided.
        fused_confidence = 82 if risk_level == "HIGH" else 55

    return {
        "fused_confidence": fused_confidence,
        "contributions": contributions,
        "method": "Weighted Average" if contributions else "No evidence submitted — narrative estimate only",
        "sources_used": len(contributions),
    }


def _build_criminal_network(evidence: Dict[str, Any]) -> Dict[str, Any]:
    """Build the Criminal Network Graph from what evidence is ACTUALLY
    present for this case, not a fixed hardcoded shape.

    BUG FIX (2026-08-25): this used to be a constant dict — "Unknown
    Subject" + "SUV" as confirmed nodes and phone/financial as inferred
    nodes, status always "NETWORK_FORMED" — regardless of whether vehicle
    evidence was even submitted for the case, and regardless of how many
    of the "network" nodes were real vs. inferred. A graph that's mostly
    inferred/unverified nodes calling itself "NETWORK_FORMED" overstates
    what's actually been established, and a vehicle node appearing even
    when no vehicle evidence exists directly contradicts the Evidence
    Completeness table shown elsewhere in the same report.
    """
    current_nodes = [{"type": "person", "name": "Unknown Subject"}]
    if "vehicle" in evidence:
        current_nodes.append({"type": "vehicle", "name": "SUV"})

    inferred_nodes = []
    if "phone" not in evidence and ("digital" in evidence or True):
        # Phone ownership is a reasonable inference to surface (not a
        # submitted evidence type in this schema at all), always marked
        # inferred/unverified — never promoted to a "current" node.
        inferred_nodes.append({"type": "phone", "relationship": "owns", "confidence": 0.60})
    if "financial" in evidence:
        # Only surface an inferred financial link when there's at least a
        # narrative-derived financial indicator to base the inference on —
        # otherwise there's nothing to infer FROM.
        inferred_nodes.append({"type": "financial", "relationship": "has_account", "confidence": 0.65})

    total_nodes = len(current_nodes) + len(inferred_nodes)
    confirmed_count = len(current_nodes)

    if confirmed_count >= 2 and len(inferred_nodes) < confirmed_count:
        status = "NETWORK_FORMED"
    elif confirmed_count >= 2:
        status = "PARTIAL — includes unverified inferred entities"
    elif inferred_nodes:
        status = "NOT ESTABLISHED — only unverified inferred entities, no confirmed connections"
    else:
        status = "NOT ESTABLISHED — insufficient confirmed entities beyond the subject"

    return {
        "status": status,
        "current_nodes": current_nodes,
        "inferred_nodes": inferred_nodes,
        "total_nodes": total_nodes,
    }


def _compute_court_readiness(completeness_pct: int, evidence: Dict[str, Any], reasoning_matrix: list) -> int:
    """Court Readiness should reflect how much of THIS case's evidence
    could actually survive scrutiny — not a fixed constant. Built from:
      - Evidence completeness itself (weight: 50%) — the biggest driver;
        a 12%-complete case cannot be "65% court ready" regardless of
        anything else.
      - Chain-of-custody / forensic-quality evidence present, i.e. photo
        or document with "good" quality (weight: 25%) — proxy for whether
        there's anything with an actual verifiable hash/timestamp.
      - At least one ACTIVE (not just PENDING) hypothesis with real
        supporting count (weight: 25%) — proxy for whether there's a
        coherent theory backed by more than zero corroborating signals.
    This is still an estimate (clearly not a legal readiness certification
    — the PDF disclaims that throughout) but it moves with the case's
    actual evidence instead of being a constant.
    """
    completeness_component = min(50, round(completeness_pct * 0.5))

    forensic_quality_component = 0
    for key in ("face", "document"):
        item = evidence.get(key)
        if isinstance(item, dict) and item.get("quality") == "good":
            forensic_quality_component = 25
            break

    hypothesis_component = 0
    for h in (reasoning_matrix or []):
        if h.get("status") == "ACTIVE" and h.get("supporting", 0) >= 2:
            hypothesis_component = 25
            break
        elif h.get("status") == "ACTIVE" and h.get("supporting", 0) >= 1:
            hypothesis_component = max(hypothesis_component, 12)

    return min(95, completeness_component + forensic_quality_component + hypothesis_component)


try:
    from knowledge_graph_engine import build_knowledge_graph
    _KNOWLEDGE_GRAPH_AVAILABLE = True
except Exception as _kg_import_err:
    _KNOWLEDGE_GRAPH_AVAILABLE = False
    _KNOWLEDGE_GRAPH_IMPORT_ERROR = str(_kg_import_err)


def _build_evidence_graph_nodes(case_data, evidence, entities, mo_description, location, suspect_name):
    """Builds the `graph['nodes']` input for KnowledgeGraphEngine from THIS
    case's actual submitted evidence and extracted entities.

    BUG FIX (P0 — user feedback, "graphs ki sankhya badhani chahiye"): the
    knowledge graph previously fed into KnowledgeGraphEngine was a
    HARDCODED, fixed 3-node/2-edge stub — {face, "Vehicle: SUV", "Unknown
    Subject"} — identical for every single case regardless of what
    evidence was actually submitted. A toll-fraud case with only a
    document and financial evidence still showed a fabricated "Vehicle:
    SUV" node. Building real nodes from this case's own evidence means the
    graph naturally grows (more nodes/edges) as more evidence is
    submitted, instead of a fixed count that never changes.
    """
    nodes = []
    n = 0

    def _weight_for(item):
        if not isinstance(item, dict):
            return 0.6
        q = item.get("quality")
        return {"good": 0.85, "narrative": 0.55, "poor": 0.35}.get(q, 0.6)

    # Always include a "person" node for the subject — Unknown unless a
    # name was actually provided (identity confidence for that name is
    # handled/labeled separately elsewhere; this node is just a graph
    # anchor for evidence-to-subject relationships).
    n += 1
    nodes.append({
        "id": f"N{n}", "type": "person",
        "content": suspect_name.strip() if suspect_name and suspect_name.strip() else "Unknown Subject",
        "source": "Case intake", "weight": 0.5 if not (suspect_name or "").strip() else 0.6,
        "metadata": {}
    })

    _EV_TO_NODE_TYPE = {
        "face": "face", "voice": "voice", "cctv": "cctv",
        "financial": "financial", "vehicle": "vehicle", "digital": "digital",
        "document": "material",
    }
    _EV_TO_LABEL = {
        "face": "Suspect photo", "voice": "Voice sample", "cctv": "CCTV footage",
        "financial": "Financial record", "vehicle": "Vehicle evidence",
        "digital": "Digital evidence", "document": "Document/ID evidence",
    }
    for ev_key, node_type in _EV_TO_NODE_TYPE.items():
        if ev_key not in evidence:
            continue
        item = evidence.get(ev_key) or {}
        n += 1
        nodes.append({
            "id": f"N{n}", "type": node_type,
            "content": _EV_TO_LABEL.get(ev_key, ev_key.title()),
            "source": f"{ev_key} evidence (this case)",
            "weight": _weight_for(item),
            "metadata": {"quality": item.get("quality") if isinstance(item, dict) else None},
        })

    if (location or "").strip():
        n += 1
        nodes.append({
            "id": f"N{n}", "type": "location", "content": location.strip(),
            "source": "Case intake", "weight": 0.6, "metadata": {}
        })

    # Weapon node only if actual weapon language is in the narrative
    # (word-boundary matched — see _kw_in) — never fabricated by default.
    _mo_lower = (mo_description or "").lower()
    _weapon_hit = next((k for k in ("firearm", "gun", "pistol", "knife", "weapon", "torch") if _kw_in(k, _mo_lower)), None)
    if _weapon_hit:
        n += 1
        nodes.append({
            "id": f"N{n}", "type": "weapon", "content": f"Weapon/tool reference: '{_weapon_hit}'",
            "source": "Case narrative (text-derived)", "weight": 0.5, "metadata": {}
        })

    # Organization entities actually extracted by NER for this case.
    for org in (entities.get("ORG") or [])[:3]:
        n += 1
        nodes.append({
            "id": f"N{n}", "type": "organization", "content": str(org),
            "source": "NER extraction (this case)", "weight": 0.5, "metadata": {}
        })

    # Additional named persons (beyond the primary subject) extracted by NER.
    for person in (entities.get("PERSON") or [])[:3]:
        if suspect_name and person.strip().lower() == suspect_name.strip().lower():
            continue
        n += 1
        nodes.append({
            "id": f"N{n}", "type": "person", "content": str(person),
            "source": "NER extraction (this case)", "weight": 0.5, "metadata": {}
        })

    return {"nodes": nodes}


def _compute_real_knowledge_graph(case_data, evidence, entities, mo_description, location, suspect_name):
    """Builds the real, evidence-driven knowledge graph (nodes/edges scale
    with how much evidence this case actually has) using
    knowledge_graph_engine.KnowledgeGraphEngine, replacing the old
    hardcoded 3-node/2-edge stub. Returns the raw {"nodes":[...],
    "edges":[...], ...} shape gradio_app.py's `_kg_nodes_edges` already
    expects, so no changes are needed on the rendering side.
    """
    if not _KNOWLEDGE_GRAPH_AVAILABLE:
        logger.warning(f"Knowledge Graph engine not available: {_KNOWLEDGE_GRAPH_IMPORT_ERROR}")
        # Minimal, honest fallback — a single unknown-subject node, no
        # fabricated evidence nodes, rather than the old fixed stub.
        return {"nodes": [{"id": "N1", "name": suspect_name or "Unknown Subject", "type": "person",
                            "content": "", "source": "Case intake", "weight": 0.5, "connections": 0,
                            "timestamp": ""}],
                "edges": [], "communities": [], "patterns": [], "cascading_reasons": [],
                "summary": "Knowledge Graph engine unavailable — minimal placeholder shown"}
    try:
        graph_input = _build_evidence_graph_nodes(case_data, evidence, entities, mo_description, location, suspect_name)
        return build_knowledge_graph(case_data, graph_input)
    except Exception as _kg_err:
        logger.error(f"Knowledge Graph build error: {_kg_err}")
        return {"nodes": [], "edges": [], "communities": [], "patterns": [], "cascading_reasons": [],
                "summary": f"Knowledge Graph build failed: {_kg_err}"}


def run_investigator_engine(case_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Complete investigator engine with all outputs
    """
    case_id = case_data.get("case_id", "NXF-UNKNOWN")
    evidence = case_data.get("evidence", {}).get("evidence_items", {})
    entities = case_data.get("entities", {})
    crime_category = case_data.get("case", {}).get("crime_category", "unknown")
    mo_description = case_data.get("case", {}).get("mo_description", "")

    # ── Criminal / Wanted-List Match (Phase 1) ────────────────────────────
    # Matches the case narrative against the connected wanted-list dataset
    # in master_search_index — by name/alias first, then by MO keywords if
    # no name match. Runs on mo_description ONLY (the free-text case
    # narrative) — never on the suspect_name field, so this reflects what
    # the narrative text itself says, not a self-fulfilling name lookup.
    if _CRIMINAL_MATCH_AVAILABLE and mo_description:
        try:
            criminal_match_results = combined_match(mo_description)
        except Exception as _cm_err:
            criminal_match_results = []
            logger.error(f"Criminal match engine error: {_cm_err}")
    else:
        criminal_match_results = []

    # ── SUPPRESS WEAK MO-ONLY NAMED MATCHES ────────────────────────────────
    # A match_type=="mo_based" hit means combined_match() found NO name/alias
    # match — only overlapping MO keywords — yet still returns a specific
    # named individual. A single generic word (e.g. "gang") overlapping is
    # coincidental, not identifying, and surfacing a real person's name next
    # to this case on that basis alone is unnecessary (and potentially
    # reputationally harmful) noise in an investigative product. Require at
    # least 2 independent matched keywords before showing a named offender
    # from MO overlap alone; a single-keyword "match" is dropped entirely
    # rather than shown at low confidence, since a name either has enough
    # corroboration to be a real lead or it doesn't belong in the report.
    # Name/alias-based matches (match_type != "mo_based") are untouched —
    # those already reflect an actual name/alias hit, not keyword overlap.
    _filtered_matches = []
    for _m in criminal_match_results:
        if (_m.get("match_type") == "mo_based"
                and len(_m.get("matched_keywords", []) or []) < 2):
            continue
        _filtered_matches.append(_m)
    criminal_match_results = _filtered_matches

    # ── Identity Resolution (Phase 6) ──────────────────────────────────────
    # Weighted multi-factor candidate search — NEVER uses the case's own
    # suspect_name field (that would be a self-fulfilling lookup); only
    # uses attributes independently extractable from the narrative/case
    # fields (location, weapon/attack keywords). See identity_resolution.py
    # for the full safety-design rationale.
    location = case_data.get("case", {}).get("location", "")
    case_domain = _classify_case_domain(crime_category, mo_description)
    identity_candidates_out = []
    identity_resolution_status = "not_searched"
    if _IDENTITY_RESOLUTION_AVAILABLE and mo_description:
        try:
            mo_lower = mo_description.lower()
            _attrs = {
                "location": location,
                "weapon_keywords": [k for k in _ID_RES_WEAPON_KEYWORDS if _kw_in(k, mo_lower)],
                "attack_keywords": [k for k in _ID_RES_ATTACK_KEYWORDS if _kw_in(k, mo_lower)],
                "crime_type": crime_category,
            }
            _ir_engine = IdentityResolutionEngine()
            _candidates = _ir_engine.match_person(_attrs, datasets=("wanted_list",))
            identity_candidates_out = [_ir_engine.get_candidate_report(c.candidate_id) for c in _candidates[:5]]
            identity_resolution_status = "searched"
        except Exception as _ir_err:
            identity_resolution_status = f"error: {_ir_err}"
            logger.error(f"Identity resolution error: {_ir_err}")
    elif not _IDENTITY_RESOLUTION_AVAILABLE:
        identity_resolution_status = f"unavailable: {_IDENTITY_RESOLUTION_IMPORT_ERROR}"
    
    # ── Evidence Completeness ────────────────────────────────────────────
    evidence_count = len(evidence)
    components = []
    
    evidence_types = [
        ("face", "Photo/Face", 20),
        ("voice", "Voice Sample", 18),
        ("document", "Document/ID", 16),
        ("cctv", "CCTV Footage", 14),
        ("financial", "Financial Records", 12),
        ("vehicle", "Vehicle/Plate", 10),
        ("digital", "Digital Evidence", 10),
    ]
    
    total_weight = 0
    for key, name, weight in evidence_types:
        status = "✓" if key in evidence else "✕"
        item = evidence.get(key) or {}
        is_narrative = isinstance(item, dict) and item.get("quality") == "narrative"
        is_poor_quality = isinstance(item, dict) and item.get("quality") == "poor"
        if key in evidence:
            total_weight += weight
        # BUG FIX (2026-08-20 — P0): "Digital Evidence: submitted" and
        # "Financial Records: submitted" used to be indistinguishable from
        # actually-submitted forensic files (photo/voice/document). Both
        # are commonly just text extracted from the case narrative (an
        # email address mentioned in the story, a wallet ID typed into a
        # field) — not an uploaded digital-forensics image or bank
        # statement. Label that distinction explicitly rather than letting
        # "submitted" imply a forensic artifact exists.
        if key in evidence and is_narrative:
            reasoning = f"{name}: narrative-derived indicator present (case text/fields) — no forensic file submitted for independent verification"
        elif key in evidence and is_poor_quality:
            # BUG FIX (reviewer feedback, identity/OCR contradiction):
            # this used to say plain "submitted" for a document that was
            # uploaded but whose content couldn't actually be analyzed
            # (e.g. OCR extracted no readable text) — same file, same
            # weight, but the reasoning text implied it was usable
            # evidence when downstream analysis had already failed on it.
            reasoning = f"{name}: file submitted, but analysis quality is POOR (e.g. OCR could not extract readable text) — content not verified"
        else:
            reasoning = f"{name} {'submitted' if key in evidence else 'not submitted for this case'}"
        components.append({
            "name": name,
            "status": status,
            "weight": weight,
            "reasoning": reasoning
        })
    
    completeness_pct = min(100, total_weight)
    
    # ── Unknown Criminal Profile ─────────────────────────────────────────
    # BUG FIX (P0 — reviewer feedback, NHAI toll-fraud case): these fields
    # used to default to a specific, confident-sounding physical-crime
    # profile (Medium technical skill, Semi-planned, 72% profile
    # confidence, Solo team) for ANY case with a non-empty mo_description
    # — even one with zero crime-pattern-establishing evidence. For a case
    # where nothing about method/team/planning is actually established,
    # the honest answer is "Unknown" / low confidence, not a plausible-
    # sounding guess. Every field below now requires an explicit keyword
    # match (or a "physical" domain classification) before asserting
    # anything more specific than "Unknown".
    _mo_l = mo_description.lower() if mo_description else ""
    unknown_profile = {
        "estimated_age": "35-45" if ("robbery" in crime_category.lower() and case_domain == "physical") else "Unknown",
        "estimated_gender": "Male" if ("robbery" in crime_category.lower() and case_domain == "physical") else "Unknown",
        "modus_operandi": _safe_truncate(mo_description, 100) if mo_description else "Unknown",
        "mo_signature": "Thermal cutting" if _kw_in("thermal", _mo_l) else "Unknown",
        "profile_confidence": (
            60 if case_domain == "physical" and mo_description else
            35 if case_domain == "financial" and mo_description else
            15 if mo_description else 0
        ),
        "estimated_team_size": "2-3" if _kw_in("team", _mo_l) else "Unknown",
        "technical_skill": "High" if _kw_in("thermal", _mo_l) else ("Unknown" if case_domain != "physical" else "Medium"),
        "planning_level": "Highly planned" if _kw_in("planned", _mo_l) else "Unknown"
    }
    
    # ── Reasoning Matrix ────────────────────────────────────────────────
    # BUG FIX (2026-08-20 — Critical): gradio_app.py's PDF renderers read
    # the hypothesis's display text from a "name" key and its confidence
    # as a NUMBER (e.g. for float(...) conversion, /100.0 math, and "X%"
    # display). This function used to emit "hypothesis" (not "name") and a
    # word-label ("HIGH"/"MEDIUM"/"LOW", not a number) for confidence — so
    # every one of those renderers silently fell back to "Unknown" /
    # "0%" even though the underlying hypothesis text and strength were
    # known. Emitting both a "name" key (readers expecting it) and a
    # "hypothesis" key (readers expecting that, e.g. executive_dashboard's
    # primary_theory) — plus a numeric "confidence" alongside a
    # human-readable "confidence_label" — makes every existing consumer
    # display the same, correct data instead of "Unknown"/"0%".
    reasoning_matrix = []
    try:
        from analysis.report_rules import classify_crimes as _p38_cc, is_accounting_case as _p38_iac
        _p38_acct = _p38_iac(_p38_cc(mo_description or ""))
    except Exception:
        _p38_acct = False
    if mo_description and _p38_acct:
        # p38: accounting / financial-statement fraud is not a loan-default case
        mo_l = mo_description.lower()
        _sig = [k for k in ("inflated", "fictitious", "falsified", "fake invoices", "forged bank statements",
                            "fixed deposit", "balance sheet", "revenue", "profits", "confessed", "auditor")
                if _kw_in(k, mo_l)]
        _h1 = 70 if len(_sig) >= 3 else (50 if _sig else 35)
        reasoning_matrix.append({
            "hypothesis": "Financial statement fraud: books falsified (fictitious cash, revenue or profits)",
            "name": "Financial statement fraud: books falsified (fictitious cash, revenue or profits)",
            "confidence": _h1, "confidence_label": "HIGH" if _h1 >= 70 else "MEDIUM",
            "supporting": len(_sig), "contradicting": 0,
            "source": "Accounting Fraud Pattern Analysis" + (f" — matched: {', '.join(_sig[:4])}" if _sig else ""),
            "status": "ACTIVE"})
        _rp = [k for k in ("family", "related party", "related-party", "promoter", "siphon", "diverted",
                           "real estate", "property", "properties", "acquire", "buy") if _kw_in(k, mo_l)]
        _h2 = 45 if len(_rp) >= 2 else (30 if _rp else 15)
        reasoning_matrix.append({
            "hypothesis": "Funds moved to promoter-linked or related-party entities",
            "name": "Funds moved to promoter-linked or related-party entities",
            "confidence": _h2, "confidence_label": "MEDIUM" if _h2 >= 40 else "LOW",
            "supporting": len(_rp), "contradicting": 0,
            "source": "Related-party Pattern Analysis" + (f" — matched: {', '.join(_rp[:4])}" if _rp else " — no signal"),
            "status": "PENDING"})
    elif mo_description and case_domain == "financial":
        # Financial/fraud-domain hypotheses — replaces the physical-crime
        # "organized crime gang" template, which has no basis in a banking/
        # debt/fraud case narrative.
        mo_l = mo_description.lower()
        _h1_conf = 60 if any(_kw_in(k, mo_l) for k in ("diversion", "siphon", "shell company", "related party", "related-party")) else 40
        reasoning_matrix.append({
            "hypothesis": "Wilful default / asset diversion",
            "name": "Wilful default / asset diversion",
            "confidence": _h1_conf,
            "confidence_label": "MEDIUM" if _h1_conf >= 50 else "LOW",
            "supporting": 2 if _h1_conf >= 50 else 1,
            "contradicting": 0,
            "source": "Financial Pattern Analysis",
            "status": "ACTIVE"
        })
        _h2_conf = 45 if any(_kw_in(k, mo_l) for k in ("restructuring", "resolution", "haircut", "recovery")) else 25
        reasoning_matrix.append({
            "hypothesis": "Genuine financial distress / restructuring case",
            "name": "Genuine financial distress / restructuring case",
            "confidence": _h2_conf,
            "confidence_label": "MEDIUM" if _h2_conf >= 40 else "LOW",
            "supporting": 1,
            "contradicting": 0,
            "source": "Financial Pattern Analysis",
            "status": "PENDING"
        })
    elif mo_description and case_domain == "physical":
        # BUG FIX (P0 — reviewer feedback, Surat homicide case): both
        # hypotheses below used to default to a flat, evidence-independent
        # confidence (55% for "organized crime" unless "thermal" was
        # present, 30% for "inside job" unless "team" was present) — for a
        # sparse-evidence homicide case with NO network, no associates, no
        # team/coordination language at all, this still produced
        # "Professional organized crime operation: 55%" out of nothing.
        # Both hypotheses now require actual supporting language in the
        # case narrative before getting anything above a low base-rate
        # confidence — no organizational/team signal in the text means
        # this stays explicitly low-confidence and clearly labeled as
        # having minimal evidentiary support, not a default 55%.
        _org_crime_signals = [k for k in ("thermal", "team", "gang", "professional", "coordinated",
                                           "coordination", "syndicate", "network", "multiple suspects",
                                           "planned", "reconnaissance", "hand signals", "radio")
                               if _kw_in(k, mo_description.lower())]
        if _org_crime_signals:
            _h1_conf = 85 if _kw_in("thermal", mo_description.lower()) else (55 if len(_org_crime_signals) >= 2 else 40)
            _h1_label = "HIGH" if _h1_conf >= 70 else "MEDIUM"
            _h1_source = f"MO Pattern Analysis — matched: {', '.join(_org_crime_signals[:3])}"
        else:
            _h1_conf = 15
            _h1_label = "LOW — no organizational/team/coordination language in case narrative"
            _h1_source = "MO Pattern Analysis — no supporting signal found; this is a base-rate estimate, not evidence-derived"
        reasoning_matrix.append({
            "hypothesis": "Professional organized crime operation",
            "name": "Professional organized crime operation",
            "confidence": _h1_conf,
            "confidence_label": _h1_label,
            "supporting": len(_org_crime_signals),
            "contradicting": 0,
            "source": _h1_source,
            "status": "ACTIVE" if _org_crime_signals else "PENDING"
        })
        _insider_signals = [k for k in ("employee", "insider", "staff", "inside job", "access", "colleague",
                                         "coworker", "known to", "familiar with")
                             if _kw_in(k, mo_description.lower())]
        if _insider_signals:
            _h2_conf = 55 if len(_insider_signals) >= 2 else 35
            _h2_label = "MEDIUM" if _h2_conf >= 40 else "LOW"
            _h2_source = f"Network Analysis — matched: {', '.join(_insider_signals[:3])}"
        else:
            _h2_conf = 10
            _h2_label = "LOW — no employee/insider/access language in case narrative or network evidence"
            _h2_source = "Network Analysis — no supporting signal found; this is a base-rate estimate, not evidence-derived"
        reasoning_matrix.append({
            "hypothesis": "Inside job with employee assistance",
            "name": "Inside job with employee assistance",
            "confidence": _h2_conf,
            "confidence_label": _h2_label,
            "supporting": len(_insider_signals),
            "contradicting": 1 if not _insider_signals else 0,
            "source": _h2_source,
            "status": "PENDING"
        })
    elif mo_description:
        # BUG FIX (P0 — reviewer feedback, NHAI toll-fraud case): this
        # "generic" branch (case_domain is neither "financial" nor
        # "physical" — e.g. software/toll fraud, corruption, or anything
        # else that doesn't match either keyword set) used to silently
        # fall through to the SAME "elif mo_description:" burglary
        # template above. A case with no physical-crime evidence and no
        # recognized financial-crime keywords would still get
        # "Professional organized crime operation: 55%". Do not guess a
        # specific crime-pattern hypothesis when the domain itself isn't
        # recognized — an honest low-confidence placeholder is better than
        # a confident-sounding wrong template.
        reasoning_matrix.append({
            "hypothesis": "Insufficient case-specific pattern data for automated hypothesis generation",
            "name": "Insufficient case-specific pattern data for automated hypothesis generation",
            "confidence": 0,
            "confidence_label": "NOT ESTABLISHED",
            "supporting": 0,
            "contradicting": 0,
            "source": "Domain Classifier — no financial or physical-crime pattern keywords matched",
            "status": "PENDING"
        })

    # ── SPARSE-EVIDENCE HYPOTHESIS CAP ──────────────────────────────────
    # BUG FIX (P0 — reviewer feedback, Surat homicide case): the hypothesis
    # confidences above are derived ONLY from keyword matches in the
    # free-text case narrative — they have no idea whether ANY of that
    # narrative is actually corroborated by real evidence (CCTV, photo,
    # financial records, vehicle, documents). A case with 0% evidence
    # completeness (no forensic evidence submitted at all — everything is
    # unverified narrative text) could still produce "Professional
    # organized crime operation: 55%" purely from narrative wording, which
    # reads as a strong signal to an investigator even though nothing
    # about it has been corroborated. When overall evidence completeness
    # is very low, cap every hypothesis's confidence hard and relabel it
    # so the report says what it actually knows: not enough evidence to
    # rank hypotheses reliably yet.
    if completeness_pct < 15:
        for h in reasoning_matrix:
            if h["confidence"] > 25:
                h["confidence"] = 25
            h["confidence_label"] = "INSUFFICIENT EVIDENCE TO RANK RELIABLY"
            h["source"] = (h.get("source", "") + " — capped: evidence completeness is only "
                            f"{completeness_pct}%, too low for narrative-only keyword matches to "
                            f"support a confident hypothesis ranking").strip(" —")

    # ── Investigation Paths ──────────────────────────────────────────────
    if _p38_acct:
        _extra_paths = [
            {"name": n, "confidence": "MEDIUM", "evidence_count": 0, "contradictions": 0, "status": "PENDING"}
            for n in ("Books of account vs independent bank / FD confirmations",
                      "Recorded revenue vs customer invoices and receipts",
                      "Auditor working papers and audit trail",
                      "Related-party transactions and promoter share sales / pledges")]
    elif case_domain == "financial":
        # BUG FIX (reviewer feedback): the burglary-domain planner
        # (employee access logs / CCTV / witness statements) has no
        # relevance to a banking/debt-recovery investigation. Financial-
        # domain directions follow the actual document/asset trail.
        _extra_paths = [
            {"name": "Loan sanction letters → guarantee deeds", "confidence": "MEDIUM",
             "evidence_count": 0, "contradictions": 0, "status": "PENDING"},
            {"name": "Lender-wise exposure & claim admission", "confidence": "MEDIUM",
             "evidence_count": 0, "contradictions": 0, "status": "PENDING"},
            {"name": "Asset valuation & recovery gap", "confidence": "MEDIUM",
             "evidence_count": 0, "contradictions": 0, "status": "PENDING"},
            {"name": "Related-party transactions & asset trail", "confidence": "MEDIUM",
             "evidence_count": 0, "contradictions": 0, "status": "PENDING"},
        ]
    elif case_domain == "physical":
        _extra_paths = [{
            "name": "Financial trail investigation",
            "confidence": "MEDIUM",
            "evidence_count": 2,
            "contradictions": 0,
            "status": "ACTIVE"
        }]
    else:
        # BUG FIX (P0 — NHAI case): "generic" domain used to inherit the
        # physical-crime path list by default (the `else` branch here used
        # to be shared with "physical"). No domain-specific investigation
        # directions are known for an unrecognized case type — surfacing a
        # generic, honest next step (establish the actual crime pattern)
        # is better than recommending burglary-investigation steps for a
        # case that was never established to be a burglary.
        _extra_paths = [{
            "name": "Establish case-specific crime pattern (domain not yet classified) before generating "
                    "targeted investigation directions",
            "confidence": "LOW",
            "evidence_count": 0,
            "contradictions": 0,
            "status": "PENDING"
        }]
    investigation_paths = {
        "total": len(reasoning_matrix) + len(_extra_paths),
        "strong": sum(1 for h in reasoning_matrix if h.get("status") == "ACTIVE"),
        "rejected": 1,
        "paths": reasoning_matrix + _extra_paths
    }
    
    # ── Missing Impact ──────────────────────────────────────────────────
    missing_impact = []
    missing_evidence = [key for key, _, _ in evidence_types if key not in evidence]
    for ev in missing_evidence:
        missing_impact.append({
            "evidence": ev,
            "impact": "MEDIUM" if ev in ["voice", "cctv"] else "LOW",
            "gain": "15% confidence increase" if ev in ["voice", "cctv"] else "5-10%",
            "affects": ["Verification", "Timeline"] if ev == "cctv" else ["Verification"],
            "why_missing": "Not submitted for this case"
        })
    
    # ── Investigation Value ─────────────────────────────────────────────
    investigation_value = []
    for ev in evidence:
        investigation_value.append({
            "evidence": ev,
            "value": "HIGH" if ev in ["face", "voice"] else "MEDIUM" if ev in ["cctv", "document"] else "LOW",
            "reason": f"{ev} provides direct evidence link"
        })
    
    # ── Deepfake Impact ─────────────────────────────────────────────────
    deepfake_impact = []
    if "face" in evidence:
        deepfake_impact.append({
            "impact": "MEDIUM",
            "note": "Face evidence requires deepfake verification",
            "recommendation": "Run deepfake detection on photo"
        })
    
    # ── Risk Assessment ─────────────────────────────────────────────────
    # BUG FIX (reviewer feedback): "Physical Threat: HIGH" driven purely by
    # a literal "weapon" substring anywhere in the text was already
    # reasonable, but risk_level and public_safety below used to derive
    # from the physical-crime "thermal" keyword even for financial cases,
    # incorrectly implying a HIGH public-safety/physical risk_level for a
    # banking case with no physical component at all.
    if case_domain == "financial":
        risk_level = "MEDIUM" if any(_kw_in(k, mo_description.lower()) for k in
                                      ("diversion", "siphon", "shell company", "fraud")) else "LOW"
    elif case_domain == "physical":
        risk_level = "HIGH" if _kw_in("thermal", mo_description.lower()) else "MEDIUM"
    else:
        # BUG FIX (P0 — NHAI case): "generic" domain used to share the
        # physical-crime branch and default to MEDIUM risk / MEDIUM
        # physical threat even with zero physical-crime evidence. Without
        # a recognized crime pattern, default to LOW rather than assuming
        # risk.
        risk_level = "LOW"
    risk = {
        "level": risk_level,
        "reason": f"Crime pattern indicates {risk_level.lower()} risk" if case_domain != "generic"
                  else "Crime pattern not yet classified — risk level is a default, not evidence-based",
        "physical_threat": "HIGH" if _kw_in("weapon", mo_description.lower()) else (
            "NONE — no weapon/physical-threat language in case narrative" if case_domain in ("financial", "generic") else "MEDIUM"),
        "financial_threat": "HIGH" if "financial" in crime_category.lower() or case_domain == "financial" else "LOW",
        "cyber_threat": "MEDIUM",
        "public_safety": "LOW — financial/economic-crime case, no physical-safety indicators" if case_domain == "financial"
                          else ("LOW — no physical-crime evidence" if case_domain == "generic"
                                else ("HIGH" if risk_level == "HIGH" else "MEDIUM")),
        "escalation_prob": 78 if risk_level == "HIGH" else 45
    }
    
    # ── Scene Classification ────────────────────────────────────────────
    if case_domain == "financial":
        scene_classification = {
            "classification": "Financial/Regulatory Investigation — no physical crime scene",
            "confidence": 60,
            "source": "Text-based inference"
        }
    elif case_domain == "physical":
        scene_classification = {
            "classification": "Vault Robbery" if _kw_in("thermal", mo_description.lower()) else "Under Investigation",
            "confidence": 78 if _kw_in("thermal", mo_description.lower()) else 40,
            "source": "CCTV/Image Classifier" if "cctv" in evidence else "Text-based inference"
        }
    else:
        # BUG FIX (P0 — NHAI case): "generic" domain used to default to
        # "Under Investigation" via the physical branch, which was
        # harmless on its own, but "Vault Robbery" could still fire if
        # "thermal" happened to appear anywhere in an unrelated narrative.
        # Explicit no-crime-scene-established state for unclassified cases.
        scene_classification = {
            "classification": "Not applicable / not established — crime domain not classified",
            "confidence": 0,
            "source": "Domain Classifier — no financial or physical-crime pattern keywords matched"
        }
    
    # ── Dynamic Profile ─────────────────────────────────────────────────
    dynamic_profile = {
        "estimated_age": unknown_profile["estimated_age"],
        "estimated_gender": unknown_profile["estimated_gender"],
        "team_size": "2-3" if _kw_in("team", mo_description.lower()) else "Solo",
        "technical_skill": "High" if _kw_in("thermal", mo_description.lower()) else "Medium",
        "planning_level": "Highly planned" if _kw_in("planned", mo_description.lower()) else "Semi-planned",
        "risk_behavior": "High" if risk_level == "HIGH" else "Medium"
    }
    
    # ── OCR Status ──────────────────────────────────────────────────────
    # BUG FIX (root cause of the "OCR FAILED" vs "OCR Status: ANALYZED"
    # contradiction found in review): this used to derive status purely
    # from whether the "document" KEY was present in `evidence` — i.e.
    # "a file was uploaded" — regardless of whether OCR actually managed
    # to read anything from it. gradio_app.py already computes and passes
    # through a real per-item "quality" flag ("good"/"poor"/"narrative")
    # based on the pipeline's own OCR result (see
    # `_quality_from_status(doc_evidence)` in gradio_app.py), so use that
    # instead of mere key presence — this makes this engine's OCR status
    # agree with the rest of the report by construction, not by a
    # separate cross-check patch downstream.
    _doc_item = evidence.get("document") or {}
    _doc_quality = _doc_item.get("quality") if isinstance(_doc_item, dict) else None
    if "document" not in evidence:
        ocr_status = {
            "status": "NOT SUBMITTED",
            "reason": "No document provided",
            "text_preview": ""
        }
    elif _doc_quality == "good":
        ocr_status = {
            "status": "ANALYZED",
            "reason": "Document evidence processed and readable text extracted",
            "text_preview": ""
        }
    else:
        ocr_status = {
            "status": "FAILED",
            "reason": "Document evidence submitted, but OCR could not extract readable text "
                      "(poor scan quality, unsupported format, or OCR module unavailable)",
            "text_preview": ""
        }
    
    # ── Advanced Intelligence ──────────────────────────────────────────
    _kg_result = _compute_real_knowledge_graph(
        case_data, evidence, entities, mo_description, location, case_data.get("case", {}).get("suspect_name", "")
    )
    advanced = {
        "hypothesis_ranking": {
            "top_hypotheses": reasoning_matrix[:3],
            "rejected_hypotheses": [h for h in reasoning_matrix if h.get("status") == "REJECTED"],
            "all_hypotheses_raw": reasoning_matrix
        },
        "crime_dna": (
            {
                # BUG FIX (reviewer feedback): Violence/Escape/Execution/
                # Team are physical-crime dimensions that are meaningless
                # for a financial/banking case (e.g. "Escape 7/10" in a
                # debt-recovery case). For financial-domain cases, report
                # financial-relevant dimensions instead, using the SAME
                # dict keys where they map (planning, team) so existing
                # generic consumers don't break, plus explicit new keys a
                # financial-aware view can read.
                "planning": 7 if any(_kw_in(k, mo_description.lower()) for k in ("planned", "structured", "shell company")) else 4,
                "technical": 6 if any(_kw_in(k, mo_description.lower()) for k in ("diversion", "siphon", "related party", "related-party")) else 3,
                "violence": 0,
                "escape": 0,
                "op_security": 5 if _kw_in("shell company", mo_description.lower()) else 3,
                "execution": 0,
                "team": 6 if any(_kw_in(k, mo_description.lower()) for k in ("related party", "related-party", "group")) else 2,
                "credit_exposure": 7,
                "guarantee_strength": 5,
                "asset_coverage": 5,
                "related_parties": 6 if any(_kw_in(k, mo_description.lower()) for k in ("related party", "related-party")) else 2,
                "transaction_complexity": 6,
                "recovery_gap": 6,
                "regulatory_legal_events": 5,
                "restructuring_pattern": 6 if any(_kw_in(k, mo_description.lower()) for k in ("restructuring", "resolution", "haircut")) else 2,
            } if case_domain == "financial" else ({
                "planning": 8 if _kw_in("planned", mo_description.lower()) else 5,
                "technical": 8 if _kw_in("thermal", mo_description.lower()) else 4,
                "violence": 5 if any(_kw_in(k, mo_description.lower()) for k in ("weapon", "assault", "violence")) else 1,
                "escape": 6 if any(_kw_in(k, mo_description.lower()) for k in ("fled", "escape", "getaway")) else 2,
                "op_security": 6,
                "execution": 7 if _kw_in("thermal", mo_description.lower()) else 3,
                "team": 7 if _kw_in("team", mo_description.lower()) else 3
            } if case_domain == "physical" else {
                # BUG FIX (P0 — NHAI case): "generic" domain used to share
                # the physical-crime dict above by default, producing
                # meaningless scores like Escape=2/10, Execution=3/10 for
                # a case that was never established to be a physical
                # crime at all. All dimensions are 0/not-established here
                # until the domain is actually classified.
                "planning": 0, "technical": 0, "violence": 0, "escape": 0,
                "op_security": 0, "execution": 0, "team": 0,
            })
        ),
        "executive_dashboard": {
            "case_status": "HIGH PRIORITY - CRITICAL" if risk_level == "HIGH" else "MEDIUM PRIORITY",
            "primary_theory": reasoning_matrix[0].get("hypothesis", "Unknown") if reasoning_matrix else "Unknown",
            # BUG FIX (2026-08-20 — High): "Primary Theory" used to be
            # followed by an INDEPENDENT hardcoded confidence (85/60) with
            # no connection to that same hypothesis's own confidence in
            # reasoning_matrix (e.g. 55%) — so the same theory showed two
            # different percentages in different parts of the same report
            # (e.g. "55%" on the hypothesis table, "60%" on the executive
            # dashboard). The dashboard's headline theory literally IS
            # reasoning_matrix[0], so its confidence must come from there.
            "primary_confidence": reasoning_matrix[0].get("confidence", 55) if reasoning_matrix else (85 if risk_level == "HIGH" else 60),
            "evidence_completeness": completeness_pct,
            # BUG FIX (2026-08-25): Court Readiness was a flat, always-65
            # constant, completely disconnected from how much evidence
            # this specific case actually has — a case with 12% Evidence
            # Completeness showed the exact same "Court Readiness: 65%" as
            # one with 62%, which reads as "ready for court" regardless of
            # evidence quality. Derive it from concrete, checkable
            # components instead: evidence completeness itself (chain of
            # custody / corroboration proxy), whether the chain-of-custody
            # log exists, and whether at least one hypothesis has active
            # support — so a thin-evidence case visibly shows a low score.
            "court_readiness": _compute_court_readiness(completeness_pct, evidence, reasoning_matrix),
            "fused_confidence": 82 if risk_level == "HIGH" else 55
        },
        "knowledge_graph_raw": _kg_result,
        # BUG FIX: this summary key ("knowledge_graph", not "_raw") was
        # never populated at all, so gradio_app.py's `kgv = adv.get(
        # "knowledge_graph", {})` was always empty and the entire
        # Knowledge Graph section in the PDF never rendered, regardless of
        # the hardcoded-stub bug above. Populate it from the same real
        # graph result so the section actually shows nodes/edges/
        # communities/patterns that reflect this case's evidence.
        "knowledge_graph": {
            "total_nodes": len(_kg_result.get("nodes", [])),
            "total_edges": len(_kg_result.get("edges", [])),
            "communities": [c.get("name", "") for c in _kg_result.get("communities", [])],
            "patterns": [p.get("description", "") for p in _kg_result.get("patterns", [])],
            "graph_chain": (_kg_result.get("cascading_reasons") or [{}])[0].get("path", []) if _kg_result.get("cascading_reasons") else [],
        },
        "criminal_network": _build_criminal_network(evidence),
        "confidence_fusion_detail": _build_confidence_fusion_detail(evidence, risk_level)
    }
    
    return {
        "evidence_completeness": {
            "total": f"{completeness_pct}%",
            "components": components
        },
        "unknown_profile": unknown_profile,
        "reasoning_matrix": reasoning_matrix,
        "investigation_paths": investigation_paths,
        "missing_impact": missing_impact,
        "investigation_value": investigation_value,
        "deepfake_impact": deepfake_impact,
        "risk": risk,
        "scene_classification": scene_classification,
        "dynamic_profile": dynamic_profile,
        "ocr": ocr_status,
        "advanced": advanced,
        "advanced_report": advanced,
        "criminal_match": {
            "matches": criminal_match_results,
            "match_count": len(criminal_match_results),
            "searched": _CRIMINAL_MATCH_AVAILABLE and bool(mo_description),
            "unavailable_reason": None if _CRIMINAL_MATCH_AVAILABLE else _CRIMINAL_MATCH_IMPORT_ERROR,
        },
        "identity_resolution": {
            "candidates": identity_candidates_out,
            "candidate_count": len(identity_candidates_out),
            "status": identity_resolution_status,
        }
    }


# ============================================================
# HELPER FUNCTIONS (Agar missing ho toh)
# ============================================================

def get_investigator_intelligence(report_data: Dict) -> Dict[str, Any]:
    """Investigator intelligence summary"""
    return {
        "evidence_completeness": report_data.get("evidence_completeness", {}).get("total", "0%"),
        "confidence_level": "HIGH" if report_data.get("risk", {}).get("level") == "HIGH" else "MEDIUM",
        "risk_level": report_data.get("risk", {}).get("level", "LOW"),
        "deception_score": 65,
        "active_models": 5,
        "reasoning_gaps": 2,
        "contradictions": 1,
        "hypotheses_count": len(report_data.get("reasoning_matrix", []))
    }


def get_unknown_profile(report_data: Dict) -> Dict[str, Any]:
    """Unknown criminal profile extractor"""
    up = report_data.get("unknown_profile", {})
    return {
        "estimated_age": up.get("estimated_age", "Unknown"),
        "estimated_gender": up.get("estimated_gender", "Unknown"),
        "modus_operandi": up.get("modus_operandi", "Unknown"),
        "mo_signature": up.get("mo_signature", "Unknown"),
        "profile_confidence": up.get("profile_confidence", 40)
    }


def get_reasoning_matrix(report_data: Dict) -> List[Dict]:
    """Reasoning matrix extractor"""
    return report_data.get("reasoning_matrix", [])


def get_risk_assessment(report_data: Dict) -> Dict[str, Any]:
    """Risk assessment extractor"""
    risk = report_data.get("risk", {})
    return {
        "level": risk.get("level", "LOW"),
        "reason": risk.get("reason", "No risk assessment"),
        "physical_threat": risk.get("physical_threat", "None"),
        "financial_threat": risk.get("financial_threat", "None"),
        "cyber_threat": risk.get("cyber_threat", "None"),
        "public_safety": risk.get("public_safety", "None"),
        "escalation_prob": risk.get("escalation_prob", 0)
    }


def get_scene_classification(report_data: Dict) -> Dict[str, Any]:
    """Scene classification extractor"""
    sc = report_data.get("scene_classification", {})
    return {
        "classification": sc.get("classification", "Under Investigation"),
        "confidence": sc.get("confidence", 0),
        "source": sc.get("source", "Unknown")
    }


def get_ocr_status(report_data: Dict) -> Dict[str, Any]:
    """OCR status extractor"""
    ocr = report_data.get("ocr", {})
    return {
        "status": ocr.get("status", "NOT SUBMITTED"),
        "reason": ocr.get("reason", "No document provided"),
        "text_preview": ocr.get("text_preview", "")
    }


def generate_investigation_paths(report_data: Dict) -> Dict[str, Any]:
    """Investigation paths generator"""
    paths = report_data.get("investigation_paths", {})
    return {
        "total": paths.get("total", 0),
        "strong": paths.get("strong", 0),
        "rejected": paths.get("rejected", 0),
        "paths": paths.get("paths", [])
    }


print("✅ investigator_integration.py loaded successfully")
