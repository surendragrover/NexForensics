"""
DOA end-to-end pipeline orchestrator.

question -> hypotheses -> search plan -> (documents from a connector or fixture)
-> source access check -> entity resolution with namesake guard -> claim extraction
-> structured assertions -> contradictions (legacy text + structured fact)
-> timeline -> per-finding status (common ladder) -> synthesis -> 20-section dossier
-> safety validation -> hashed artifact.

This module performs NO network access itself.  Documents are passed in
(already fetched by web_research or produced by a fixture).  It never
writes to the database.
"""
from __future__ import annotations
import hashlib
import json
from dataclasses import dataclass, field, asdict, is_dataclass
from datetime import datetime, timezone, date
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from journalist_research.common.status import (
    EvidenceStatus, SourceTier, TIER_WEIGHT, determine_status, phrase, to_canonical, tier_of)
from journalist_research.common import independence as ind
from journalist_research.common.safety import (
    assert_no_automatic_conclusion, validate_render, redact, negative_statement)
from journalist_research.common.dates import parse_dates
from journalist_research.evidence.fact_contradiction import (
    extract_assertions, detect_fact_contradictions, Assertion, FactContradiction)
from journalist_research.evidence.role_contradiction import (
    extract_role_assertions, detect_role_contradictions)

PIPELINE_VERSION = "doa-pipeline-1.0.0"

DOSSIER_SECTIONS = [
    "Executive Intelligence Summary", "Identity Resolution", "Known Names & Aliases",
    "Biographical Timeline", "Career & Corporate History", "Companies & Ownership",
    "People & Relationship Network", "Legal & Court Intelligence", "Regulatory Intelligence",
    "Financial/Corporate Signals", "Digital Footprint", "Historical Web Evidence",
    "Dark-Web Intelligence", "Claims & Evidence Matrix", "Contradiction Matrix",
    "Source Reliability Matrix", "Unverified Claims", "Evidence Gaps",
    "Unanswered Investigative Questions", "Journalist's Next Investigation Paths",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class SubjectProfile:
    subject_id: str
    name: str
    aliases: List[str] = field(default_factory=list)
    dob: Optional[str] = None
    city: Optional[str] = None
    organizations: List[str] = field(default_factory=list)


@dataclass
class InputDocument:
    document_id: str
    source_id: str
    url: str
    title: str
    text: str
    tier: str = "LOW"
    publisher: str = ""
    source_kind: str = "REPORT"          # REPORT | RECORD | SELF
    lineage_id: Optional[str] = None
    archive_of: Optional[str] = None
    published_at: Optional[str] = None   # publication date, NOT event date
    status: str = "OK"                   # OK | BLOCKED | UNAVAILABLE | NO_RESULT
    checklist_item: Optional[str] = None  # e.g. eCourts, MCA, SEBI
    mention: Dict[str, Any] = field(default_factory=dict)  # name, dob, city, organizations


def _ser(v):
    if isinstance(v, Enum):
        return v.value
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if is_dataclass(v):
        return {k: _ser(x) for k, x in asdict(v).items()}
    if isinstance(v, dict):
        return {str(k): _ser(x) for k, x in v.items()}
    if isinstance(v, (list, tuple, set)):
        return [_ser(x) for x in v]
    if hasattr(v, "__dict__") and not isinstance(v, type):
        return {k: _ser(x) for k, x in vars(v).items() if not k.startswith("_")}
    return v


# ---------------------------------------------------------------- identity
def resolve_identity(profile: SubjectProfile, doc: InputDocument) -> Dict[str, Any]:
    """Anchor-based decision layered over the legacy resolver.

    name match alone -> UNRESOLVED (kept out of findings);
    any conflicting hard anchor (DOB) -> NAMESAKE_REJECTED;
    name + >=1 matching non-name anchor -> SAME_SUBJECT_PROBABLE.
    """
    m = doc.mention or {}
    legacy = None
    try:
        from journalist_research.entity_intelligence.entity_resolution import (
            EntityCandidate, resolve_subject)
        cand = EntityCandidate(candidate_id=f"CAND-{doc.document_id}", name=m.get("name", ""),
                               locations=[m["city"]] if m.get("city") else [],
                               organizations=list(m.get("organizations", [])),
                               dates=[m["dob"]] if m.get("dob") else [],
                               source_ids=[doc.source_id])
        res = resolve_subject(profile.name, [cand])
        if res:
            legacy = {"status": _ser(res[0].status), "score": round(float(res[0].match_score), 3)}
    except Exception as exc:  # legacy module failure must not break the pipeline
        legacy = {"error": f"{type(exc).__name__}: {exc}"}

    names = {profile.name.lower(), *[a.lower() for a in profile.aliases]}
    name_match = (m.get("name") or "").lower().replace("(fictional)", "").strip() in names
    anchors_match, anchors_conflict = [], []
    if profile.dob and m.get("dob"):
        (anchors_match if profile.dob == m["dob"] else anchors_conflict).append("dob")
    if profile.city and m.get("city"):
        (anchors_match if profile.city.lower() == m["city"].lower() else anchors_conflict).append("city")
    orgs = {o.lower() for o in profile.organizations}
    if orgs and m.get("organizations"):
        if orgs & {o.lower() for o in m["organizations"]}:
            anchors_match.append("organization")

    # Text the investigator pasted for THIS case is attributed to the subject on the investigator's word
    # (anchor "investigator_supplied"); identity is still not established, and a DOB conflict still wins.
    if m.get("investigator_supplied") and name_match and not anchors_conflict and not anchors_match:
        anchors_match.append("investigator_supplied")

    if not name_match:
        decision = "NOT_SUBJECT"
    elif "dob" in anchors_conflict:
        decision = "NAMESAKE_REJECTED"
    elif anchors_match and not anchors_conflict:
        decision = "SAME_SUBJECT_PROBABLE"
    elif anchors_match and anchors_conflict:
        decision = "UNRESOLVED"
    else:
        decision = "UNRESOLVED"
    return {"document_id": doc.document_id, "decision": decision, "name_match": name_match,
            "anchors_match": anchors_match, "anchors_conflict": anchors_conflict,
            "legacy_resolver": legacy, "identity_established": False}


# ---------------------------------------------------------------- pipeline
class DOAPipeline:

    def __init__(self, investigation_id: str, question: str, profile: SubjectProfile,
                 documents: List[InputDocument], *, checklist: Optional[List[str]] = None,
                 artifact_root: Optional[str] = None):
        self.investigation_id = investigation_id
        self.question = question
        self.profile = profile
        self.documents = documents
        self.checklist = checklist or []
        self.artifact_root = artifact_root
        self.trace: List[Dict[str, Any]] = []
        self.r: Dict[str, Any] = {"investigation_id": investigation_id, "question": question,
                                  "pipeline_version": PIPELINE_VERSION, "started_at": utc_now()}

    def _mark(self, stage, **info):
        self.trace.append({"stage": stage, "at": utc_now(), **info})

    # 1. question layer (existing modules)
    def question_layer(self):
        out = {}
        try:
            from journalist_research.runtime.investigation_runtime import DOARuntime
            rt = DOARuntime(self.investigation_id, self.question)
            rt.execute_question_layer()
            st = rt.state
            out = {"categories": _ser(getattr(st.parsed_question, "categories", [])),
                   "sub_questions": _ser(getattr(st.parsed_question, "sub_questions", []))[:12],
                   "hypothesis_count": len(getattr(st.hypotheses, "hypotheses", []) or []),
                   "search_task_count": len(getattr(st.search_plan, "tasks", []) or [])}
        except Exception as exc:
            out = {"status": "NOT_ASSESSED", "error": f"{type(exc).__name__}: {exc}"}
        self.r["question_layer"] = out
        self._mark("QUESTION_LAYER", ok="error" not in out)

    # 2. access + coverage
    def coverage(self):
        from journalist_research.evidence.negative_finding import (
            build_search_attempt, build_negative_finding, finalize_negative_finding, SearchOutcome)
        rows, attempts = [], []
        outcome_map = {"BLOCKED": SearchOutcome.ACCESS_BLOCKED, "UNAVAILABLE": SearchOutcome.SOURCE_UNAVAILABLE,
                       "NO_RESULT": SearchOutcome.NO_RESULT, "OK": SearchOutcome.RELEVANT_RESULT}
        by_item: Dict[str, List[InputDocument]] = {}
        for d in self.documents:
            by_item.setdefault(d.checklist_item or "general_web", []).append(d)
        for item in self.checklist or sorted(by_item):
            docs = by_item.get(item, [])
            if not docs:
                status = EvidenceStatus.NOT_ASSESSED
                reason = "not searched"
            elif all(d.status in ("BLOCKED", "UNAVAILABLE") for d in docs):
                status, reason = EvidenceStatus.NOT_AVAILABLE, "source blocked/unavailable"
            elif all(d.status == "NO_RESULT" for d in docs):
                status, reason = EvidenceStatus.NOT_ESTABLISHED, negative_statement(self.profile.name, [item])
            else:
                status, reason = EvidenceStatus.REPORTED, "relevant results returned"
            legacy = None
            try:
                atts = [build_search_attempt(f"{self.profile.name} {item}", item,
                                             outcome=outcome_map.get(d.status, SearchOutcome.SEARCH_NOT_PERFORMED),
                                             source_ids=[d.source_id]) for d in docs]
                attempts += atts
                nf = finalize_negative_finding(build_negative_finding(self.profile.name,
                                                investigation_id=self.investigation_id), atts) if atts else None
                legacy = _ser(nf.status) if nf else "NOT_ASSESSED"
            except Exception as exc:
                legacy = f"error: {type(exc).__name__}: {exc}"
            rows.append({"checklist_item": item, "status": status.value, "reason": reason,
                         "legacy_negative_finding": legacy})
        self.r["coverage"] = rows
        self._mark("COVERAGE", items=len(rows))

    # 3. identity
    def identity(self):
        self.r["identity"] = [resolve_identity(self.profile, d) for d in self.documents if d.status == "OK"]
        self.same_docs = [d for d in self.documents if d.status == "OK" and any(
            i["document_id"] == d.document_id and i["decision"] == "SAME_SUBJECT_PROBABLE" for i in self.r["identity"])]
        self._mark("IDENTITY", same=len(self.same_docs))

    # 4. claims (existing extractor) — marked AI_EXTRACTED
    def claims(self):
        from journalist_research.evidence.claim_extractor import extract_claims
        claims = []
        for d in self.same_docs:
            for c in extract_claims(d.text, d.source_id, d.document_id, min_length=15):
                claims.append({"claim_id": c.claim_id, "text": c.text, "source_ids": [d.source_id],
                               "entity_ids": [self.profile.subject_id], "document_id": d.document_id,
                               "classification": _ser(c.classification), "dates_raw": _ser(c.dates),
                               "extraction": "AI_EXTRACTED", "extractor": "claim_extractor"})
        self.claims_list = claims
        self.r["claims"] = claims
        self._mark("CLAIMS", count=len(claims))

    # 5. assertions + contradictions
    def contradictions(self):
        from journalist_research.evidence.contradiction_engine import detect_claim_contradictions
        assertions: List[Assertion] = []
        for d in self.same_docs:
            assertions += extract_assertions(
                d.text, subject_id=self.profile.subject_id, source_id=d.source_id, document_id=d.document_id,
                lineage=ind.lineage_key(asdict(d)), source_kind={"RECORD": "RECORD", "SELF": "SELF_STATEMENT"}.get(d.source_kind, "REPORT"))
            assertions += extract_role_assertions(
                d.text, subject_id=self.profile.subject_id, source_id=d.source_id, document_id=d.document_id,
                lineage=ind.lineage_key(asdict(d)), source_kind={"RECORD": "RECORD", "SELF": "SELF_STATEMENT"}.get(d.source_kind, "REPORT"))
        legacy = []
        try:
            legacy = [_ser(c) for c in detect_claim_contradictions(self.claims_list)]
        except Exception as exc:
            legacy = [{"error": f"{type(exc).__name__}: {exc}"}]
        fact = detect_fact_contradictions(assertions) + detect_role_contradictions(assertions)
        self.assertions, self.fact_contradictions = assertions, fact
        self.r["assertions"] = [_ser(a) for a in assertions]
        self.r["contradictions"] = {"structured": [_ser(c) for c in fact], "legacy_text": legacy}
        self._mark("CONTRADICTIONS", structured=len(fact), legacy=len(legacy))

    # 6. timeline (precision-aware)
    def timeline(self):
        events = []
        for a in self.assertions:
            when = a.value if a.attribute == "loan.start" else a.as_of
            if not when:
                continue
            events.append({"date_start": when["start"], "date_end": when["end"], "precision": when["precision"],
                           "flags": when.get("flags", []), "attribute": a.attribute,
                           "value": a.value if not isinstance(a.value, dict) else a.value["raw"],
                           "kind": a.kind, "assertion_id": a.assertion_id, "source_id": a.source_id,
                           "date_role": "EVENT_DATE"})
        for d in self.same_docs:
            if d.published_at:
                events.append({"date_start": d.published_at, "date_end": d.published_at, "precision": "DAY",
                               "flags": [], "attribute": "document.published", "value": d.title,
                               "kind": "PUBLICATION", "source_id": d.source_id, "date_role": "PUBLICATION_DATE"})
        events.sort(key=lambda e: (e["date_start"], e["date_end"]))
        self.r["timeline"] = events
        self._mark("TIMELINE", events=len(events))

    # 7. findings with canonical status + legacy confidence for comparison
    def findings(self):
        from journalist_research.evidence.confidence_engine import (
            assess_confidence, ConfidenceEvidence, EvidenceStrength)
        src = {d.source_id: asdict(d) for d in self.same_docs}
        by_id = {a.assertion_id: a for a in self.assertions}

        def weight(a: Assertion) -> float:
            # A subject's own statement weighs as SELF_REPORTED whichever outlet carried it:
            # outlet quality shows the statement was made, not that it is true.
            if a.kind == "SELF_STATEMENT":
                return TIER_WEIGHT[SourceTier.SELF_REPORTED]
            return TIER_WEIGHT[tier_of(src.get(a.source_id, {}).get("tier"))]

        contested = {}   # assertion_id -> [(contradiction, opposing assertion)]
        for c in self.fact_contradictions:
            for aid, other in ((c.assertion_a, c.assertion_b), (c.assertion_b, c.assertion_a)):
                contested.setdefault(aid, []).append((c, by_id.get(other)))
        groups: Dict[tuple, List[Assertion]] = {}
        for a in self.assertions:
            val = a.value["raw"] if isinstance(a.value, dict) else a.value
            groups.setdefault((a.attribute, a.kind, str(val)), []).append(a)
        out = []
        for (attr, kind, val), items in groups.items():
            sources = [src[a.source_id] for a in items if a.source_id in src]
            pairs = [p for a in items for p in contested.get(a.assertion_id, [])]
            cs = [c for c, _ in pairs]
            own = max((weight(a) for a in items), default=0.0)
            # Quality-weighted cap: only a comparable-quality opposing assertion caps this finding at DISPUTED.
            material = any(c.severity in ("MODERATE", "HIGH", "CRITICAL") and opp is not None
                           and weight(opp) >= 0.75 * own for c, opp in pairs)
            lower_quality_contest = bool(cs) and not material
            status = determine_status(assessed=True, independent_lineages=ind.independent_count(sources),
                                      best_tier=ind.best_tier(sources), adequate_lineages=ind.adequate_count(sources),
                                      material_contradiction=material)
            if kind == "SELF_STATEMENT" and status not in (EvidenceStatus.DISPUTED,):
                status = EvidenceStatus.UNVERIFIED   # a subject's own word is a claim, not corroboration
            legacy = None
            try:
                ev = [ConfidenceEvidence(evidence_id=f"E-{a.assertion_id}", source_id=a.source_id,
                                         evidence_strength=EvidenceStrength.MODERATE,
                                         source_quality=TIER_WEIGHT[tier_of(src[a.source_id]["tier"])],
                                         independent=True, supports_claim=True) for a in items if a.source_id in src]
                la = assess_confidence(f"F-{items[0].assertion_id}", ev, contradiction_count=len(cs),
                                       material_contradiction=material,
                                       critical_contradiction=any(c.severity == "CRITICAL" for c in cs))
                legacy = {"level": _ser(la.level), "score": round(la.score, 3),
                          "independent_source_count": la.independent_source_count,
                          "canonical_equivalent": to_canonical(la.level).value}
            except Exception as exc:
                legacy = {"error": f"{type(exc).__name__}: {exc}"}
            label = {"loan.exists": "Loan exists", "loan.start": "Loan start date",
                     "loan.amount": "Loan amount (INR)", "loan.repaid": "Loan repaid",
                     "role.held": "Role", "role.ceased": "Left role", "address.city": "Address (city)"}.get(attr, attr)
            statement = f"{phrase(status)} {label.lower()}: {val} ({kind.replace('_', ' ').lower()})."
            if lower_quality_contest:
                statement += (" Contested by a lower-quality assertion ("
                              + ", ".join(sorted({c.contradiction_id for c in cs})) + "); review before publishing.")
            out.append({"finding_id": "FND-" + hashlib.sha256(f"{attr}|{kind}|{val}".encode()).hexdigest()[:10],
                        "attribute": attr, "kind": kind, "value": val, "status": status.value,
                        "statement": statement, "statement_hi": f"{phrase(status, 'hi')} {label}: {val}",
                        "assertion_ids": [a.assertion_id for a in items],
                        "source_ids": sorted({a.source_id for a in items}),
                        "independent_lineages": ind.independent_count(sources),
                        "contradiction_ids": sorted({c.contradiction_id for c in cs}),
                        "contested_by_lower_quality": lower_quality_contest,
                        "legacy_confidence": legacy})
        self.findings_list = out
        self.r["findings"] = out
        self._mark("FINDINGS", count=len(out))

    # 8. synthesis (existing) + dossier (existing builders)
    def synthesis_and_dossier(self):
        from journalist_research.evidence.evidence_synthesis import (
            synthesize_investigation, SynthesisInput, SynthesisClaim)
        from journalist_research.report import journalist_report as jr
        gaps = [f"{row['checklist_item']}: {row['status']} ({row['reason']})"
                for row in self.r["coverage"] if row["status"] in ("NOT_ASSESSED", "NOT_AVAILABLE")]
        crit = [c for c in self.fact_contradictions if c.severity in ("HIGH", "CRITICAL")]
        try:
            syn = synthesize_investigation(SynthesisInput(
                investigation_id=self.investigation_id,
                claims=[SynthesisClaim(claim_id=f["finding_id"], confidence_level=f["legacy_confidence"].get("level", "NOT_ASSESSED")
                                       if isinstance(f["legacy_confidence"], dict) else "NOT_ASSESSED",
                                       supporting_source_count=len(f["source_ids"]),
                                       independent_source_count=f["independent_lineages"],
                                       contradiction_count=len(f["contradiction_ids"]),
                                       critical_contradiction=any(c.contradiction_id in f["contradiction_ids"] for c in crit))
                        for f in self.findings_list],
                evidence_gaps=gaps, contradiction_count=len(self.fact_contradictions),
                critical_contradiction_count=len(crit),
                access_limitation_count=sum(1 for r in self.r["coverage"] if r["status"] == "NOT_AVAILABLE")))
            self.r["synthesis"] = {"state": _ser(syn.state), "canonical_state": to_canonical(syn.state).value,
                                   "evidence_balance": _ser(syn.evidence_balance),
                                   "review_priority": _ser(syn.review_priority),
                                   "human_review_required": syn.human_review_required}
            assert_no_automatic_conclusion(syn)
        except Exception as exc:
            self.r["synthesis"] = {"status": "NOT_ASSESSED", "error": f"{type(exc).__name__}: {exc}"}

        FT, FS = jr.FindingType, jr.FindingState
        state_map = {"ESTABLISHED": FS.CORROBORATED, "STRONGLY_CORROBORATED": FS.CORROBORATED,
                     "REPORTED": FS.DEVELOPING, "UNVERIFIED": FS.UNVERIFIED, "DISPUTED": FS.CONTESTED,
                     "NOT_ESTABLISHED": FS.NOT_ASSESSED, "NOT_AVAILABLE": FS.NOT_ASSESSED, "NOT_ASSESSED": FS.NOT_ASSESSED}
        dfind = []
        for f in self.findings_list:
            dfind.append(jr.build_finding(finding_type=FT.FINANCIAL, title=f["attribute"], statement=redact(f["statement"]),
                                          state=state_map[f["status"]], source_ids=f["source_ids"],
                                          contradiction_ids=f["contradiction_ids"], notes=[f"canonical:{f['status']}"]))
        for c in self.fact_contradictions:
            dfind.append(jr.build_finding(finding_type=FT.CONTRADICTION, title=f"{c.doa_class} contradiction ({c.severity})",
                                          statement=redact(c.explanation), state=FS.REVIEW_REQUIRED,
                                          source_ids=c.source_ids, contradiction_ids=[c.contradiction_id],
                                          notes=c.alternative_explanations))
        for row in self.r["coverage"]:
            if row["status"] != "REPORTED":
                dfind.append(jr.build_finding(finding_type=FT.NEGATIVE_FINDING if row["status"] == "NOT_ESTABLISHED" else FT.EVIDENCE_GAP,
                                              title=row["checklist_item"], statement=row["reason"],
                                              state=FS.NOT_ASSESSED, negative_finding=row["status"] == "NOT_ESTABLISHED",
                                              notes=[f"canonical:{row['status']}"]))
        steps = []
        for i, c in enumerate(sorted(self.fact_contradictions, key=lambda x: x.severity != "HIGH"), 1):
            steps.append(jr.build_next_step(i, f"Resolve {c.doa_class.lower()} contradiction {c.contradiction_id}",
                                            c.alternative_explanations[0] if c.alternative_explanations else c.explanation,
                                            related_contradiction_ids=[c.contradiction_id], related_source_ids=c.source_ids))
        for row in self.r["coverage"]:
            if row["status"] in ("NOT_ASSESSED", "NOT_AVAILABLE"):
                steps.append(jr.build_next_step(len(steps) + 1, f"Check {row['checklist_item']}",
                                                f"Gap: {row['status']} ({row['reason']})"))
        q = jr.build_question(self.question, category="FINANCIAL")
        dossier = jr.build_dossier(self.investigation_id, f"DOA dossier: {self.profile.name}",
                                   executive_summary="", questions=[q], findings=dfind, next_steps=steps)

        sections = self._sections()
        dossier.executive_summary = sections[0]["body"]
        self.r["dossier"] = {"legacy_status": _ser(dossier.status), "canonical_status": to_canonical(dossier.status).value,
                             "finding_count": len(dfind), "next_steps": [_ser(s) for s in steps],
                             "sections": sections}
        assert_no_automatic_conclusion(dossier)
        self._mark("DOSSIER", sections=len(sections), findings=len(dfind))

    def _sections(self) -> List[Dict[str, Any]]:
        ids = self.r["identity"]
        same = [i for i in ids if i["decision"] == "SAME_SUBJECT_PROBABLE"]
        rej = [i for i in ids if i["decision"] == "NAMESAKE_REJECTED"]
        unres = [i for i in ids if i["decision"] == "UNRESOLVED"]
        fc = self.fact_contradictions
        unv = [f for f in self.findings_list if f["status"] in ("UNVERIFIED", "DISPUTED")]
        gaps = [r for r in self.r["coverage"] if r["status"] in ("NOT_ASSESSED", "NOT_AVAILABLE")]
        body: Dict[str, str] = {}
        body["Executive Intelligence Summary"] = (
            f"{len(self.same_docs)} document(s) attributed to the subject on non-name anchors; "
            f"{len(rej)} namesake document(s) rejected; {len(unres)} unresolved. "
            f"{len(fc)} structured contradiction(s) "
            f"({', '.join(sorted({c.doa_class + ':' + c.severity for c in fc})) or 'none'}). "
            f"{len(gaps)} checklist source(s) not assessed or unavailable. Human review is required; "
            f"no fact, identity or misconduct is established by this report.")
        body["Identity Resolution"] = "; ".join(
            f"{i['document_id']}: {i['decision']} (match={i['anchors_match']}, conflict={i['anchors_conflict']})" for i in ids) or ""
        body["Known Names & Aliases"] = ", ".join([self.profile.name] + self.profile.aliases)
        body["Biographical Timeline"] = "; ".join(
            f"{e['date_start']}..{e['date_end']} [{e['precision']}{'/' + ','.join(e['flags']) if e['flags'] else ''}] "
            f"{e['attribute']}={e['value']} ({e['kind']}, {e['date_role']})" for e in self.r["timeline"])
        body["Financial/Corporate Signals"] = " ".join(f["statement"] for f in self.findings_list)
        body["Claims & Evidence Matrix"] = "; ".join(
            f"{f['finding_id']} {f['attribute']}={f['value']} -> {f['status']} (lineages={f['independent_lineages']})"
            for f in self.findings_list)
        body["Contradiction Matrix"] = "; ".join(f"{c.contradiction_id} {c.doa_class}/{c.severity}: {c.explanation}" for c in fc)
        body["Source Reliability Matrix"] = "; ".join(
            f"{d.source_id} {d.publisher or d.url} tier={d.tier} lineage={ind.lineage_key(asdict(d))} status={d.status}"
            for d in self.documents)
        body["Unverified Claims"] = "; ".join(f["statement"] for f in unv)
        body["Evidence Gaps"] = "; ".join(f"{r['checklist_item']}: {r['status']} ({r['reason']})" for r in gaps)
        body["Unanswered Investigative Questions"] = self.question if fc or gaps else ""
        body["Journalist's Next Investigation Paths"] = "; ".join(
            s for c in fc for s in c.alternative_explanations[:1]) + ("; " if fc and gaps else "") + "; ".join(
            f"check {r['checklist_item']}" for r in gaps)
        for item, key in (("eCourts", "Legal & Court Intelligence"), ("SEBI", "Regulatory Intelligence"),
                          ("MCA", "Companies & Ownership")):
            row = next((r for r in self.r["coverage"] if r["checklist_item"] == item), None)
            if row:
                body[key] = f"{row['status']}: {row['reason']}"
        out = []
        for n, title in enumerate(DOSSIER_SECTIONS, 1):
            text = body.get(title, "")
            if not text:
                reason = "no sources in scope for this section" if title != "Dark-Web Intelligence" else \
                    "dark-web search not performed in this run"
                out.append({"order": n, "title": title, "status": "NOT_ASSESSED", "body": f"NOT_ASSESSED: {reason}"})
            else:
                out.append({"order": n, "title": title, "status": "RENDERED", "body": redact(text)})
        return out

    # 9. safety + artifact
    def finalize(self):
        texts = [s["body"] for s in self.r["dossier"]["sections"]] + [f["statement"] for f in self.findings_list]
        self.r["safety"] = {"banned_phrase_issues": validate_render(texts),
                            "fact_established": False, "identity_established": False,
                            "guilt_established": False, "non_existence_established": False,
                            "automatic_conclusion": False, "human_review_required": True}
        for c in self.fact_contradictions:
            assert_no_automatic_conclusion(c)
        self.r["trace"] = self.trace
        self.r["finished_at"] = utc_now()
        payload = json.dumps(self.r, ensure_ascii=False, sort_keys=True, default=str)
        self.r["sha256"] = hashlib.sha256(payload.encode()).hexdigest()
        if self.artifact_root:
            p = Path(self.artifact_root) / self.investigation_id
            p.mkdir(parents=True, exist_ok=False)   # never overwrite an earlier run
            (p / "result.json").write_text(json.dumps(self.r, ensure_ascii=False, indent=2, default=str))
            (p / "result.sha256").write_text(self.r["sha256"] + "  result-payload\n")
            self.r["artifact_path"] = str(p / "result.json")
        return self.r

    def run(self) -> Dict[str, Any]:
        self.question_layer()
        self.coverage()
        self.identity()
        self.claims()
        self.contradictions()
        self.timeline()
        self.findings()
        self.synthesis_and_dossier()
        return self.finalize()
