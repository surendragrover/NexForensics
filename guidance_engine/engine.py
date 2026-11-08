import os, json
from pathlib import Path
from datetime import datetime, timezone


class Hypothesis:
    def __init__(self, name="", confidence=0):
        self.name = name
        self.confidence = confidence


class EvidenceItem:
    def __init__(self, type="", value="", confidence=0):
        self.type = type
        self.value = value
        self.confidence = confidence


class CaseContext:
    def __init__(self, case_id="", evidence=None, hypotheses=None, narrative=""):
        self.case_id = case_id
        self.evidence = evidence or []
        self.hypotheses = hypotheses or []
        self.narrative = narrative or ""


class InvestigationGuidanceEngine:
    def __init__(self, kb_dir):
        self.kb_dir = kb_dir
        self.kbs = []
        if kb_dir and os.path.exists(kb_dir):
            for f in sorted(Path(kb_dir).glob("*.json")):
                try:
                    with open(f, encoding="utf-8") as fp:
                        kb = json.load(fp)
                        if isinstance(kb, dict) and "hypothesis_type" in kb:
                            self.kbs.append(kb)
                except Exception:
                    pass

    def _score_kb(self, kb, narrative_lower, hyp_names_lower):
        triggers = kb.get("triggers", [])
        if not triggers:
            return 0
        hits = 0
        for trig in triggers:
            t = str(trig).lower()
            if t in narrative_lower or any(t in h for h in hyp_names_lower):
                hits += 1
        return hits

    def _match_hypothesis_confidence(self, kb_hyp_name, ctx_hypotheses):
        kb_words = set(str(kb_hyp_name).lower().replace("/", " ").split())
        best_score, best_conf = 0, None
        for h in ctx_hypotheses or []:
            h_words = set(str(h.name).lower().split())
            overlap = len(kb_words & h_words)
            if overlap > best_score:
                best_score, best_conf = overlap, round(h.confidence * 100)
        if best_score >= 2:
            return best_conf, True
        return None, False

    def analyze_case(self, ctx, top_n=10):
        narrative_lower = (ctx.narrative or "").lower()
        hyp_names_lower = [str(h.name).lower() for h in (ctx.hypotheses or [])]
        if not narrative_lower:
            narrative_lower = " ".join(hyp_names_lower + [str(e.value) for e in (ctx.evidence or [])]).lower()

        scored_kbs = []
        general_kb = None
        for kb in self.kbs:
            if kb.get("hypothesis_type") == "general" or not kb.get("triggers"):
                general_kb = kb
                continue
            score = self._score_kb(kb, narrative_lower, hyp_names_lower)
            if score > 0:
                scored_kbs.append((score, kb))

        scored_kbs.sort(key=lambda x: x[0], reverse=True)

        active_kbs = [kb for _, kb in scored_kbs]
        _fin_types = {"financial_fraud", "accounting_fraud"}
        if not active_kbs and general_kb:
            active_kbs = [general_kb]
        elif general_kb and not any(k.get("hypothesis_type") in _fin_types for k in active_kbs):
            active_kbs.append(general_kb)  # p38: CCTV/witness template not added to financial cases

        top_hyp_conf = (ctx.hypotheses[0].confidence if ctx.hypotheses else 0.5)

        directions = []
        for kb in active_kbs:
            base_priority = kb.get("priority", 4)
            matched_conf, was_matched = self._match_hypothesis_confidence(
                kb.get("name", kb.get("hypothesis_type", "")), ctx.hypotheses
            )
            for d in kb.get("investigation_directions", []):
                entry = dict(d)
                entry["hypothesis"] = kb.get("name", kb.get("hypothesis_type", "Unknown"))
                entry["_kb_priority"] = base_priority
                entry["_matched_confidence"] = matched_conf
                entry["_confidence_is_estimated"] = not was_matched
                directions.append(entry)

        directions.sort(key=lambda d: (d.get("_kb_priority", 4), -d.get("expected_evidence_gain", 0)))
        directions = directions[:top_n]

        n = len(directions) or 1
        result = []
        for i, d in enumerate(directions):
            tier = "P1" if i < max(1, n // 3) else ("P2" if i < max(2, (2 * n) // 3) else "P3")
            gain = d.get("expected_evidence_gain", 10)
            if d.get("_matched_confidence") is not None:
                likelihood = d["_matched_confidence"]
            else:
                likelihood = max(20, 60 - d.get("_kb_priority", 4) * 10)

            # BUG FIX (2026-09 — Investigation Planner over-eagerness): tier
            # was assigned purely by rank position within the KB-priority
            # sort above (top third = P1/"Critical"), with NO check on
            # whether the underlying hypothesis actually has the evidence
            # to justify that urgency. A hypothesis sitting at, say, 10%
            # confidence with the case's own Reasoning Engine already
            # labeling it "INSUFFICIENT EVIDENCE TO RANK RELIABLY" should
            # never be presented as a Critical-priority lead just because
            # its knowledge base happened to sort first — that overstates
            # confidence the investigator hasn't earned yet. Cap such
            # weakly-supported directions at P2 ("High"): the lead stays
            # visible and actionable, just not at the top of the urgency
            # scale until something actually corroborates it.
            if tier == "P1" and likelihood < 20:
                tier = "P2"

            # BUG FIX (2026-09 — investigator feedback): capping the TIER
            # (above) stops a weak hypothesis from looking Critical, but the
            # direction still read like a standing directive ("Review
            # employee access logs") rather than what it actually is: a
            # lead that only makes sense to pursue IF independent evidence
            # first suggests this hypothesis is live. At <20% confidence
            # with the Reasoning Engine already saying "INSUFFICIENT
            # EVIDENCE TO RANK RELIABLY", presenting it as an imperative
            # next step overstates how settled the hypothesis is. Reframe
            # it explicitly as conditional instead of dropping it — the
            # lead stays visible and actionable, just correctly scoped to
            # "only if" rather than "do this now".
            is_conditional = likelihood < 20
            _hyp_name = d.get("hypothesis", "this hypothesis")
            _base_title = d.get("title", "Investigate")
            if is_conditional:
                display_title = f"[Conditional] {_base_title}"
                trigger_text = (
                    f"CONDITIONAL — {_hyp_name} currently has insufficient evidence "
                    f"({likelihood}% confidence, no independent corroboration yet). "
                    f"Only pursue if independent evidence emerges supporting this "
                    f"hypothesis; not a standing investigation priority on its own."
                )
            else:
                display_title = _base_title
                trigger_text = f"Matched knowledge base: {_hyp_name}"

            result.append({
                "rank": i + 1,
                "title": display_title,
                "priority_tier": tier,
                "priority": {"P1": "Critical", "P2": "High", "P3": "Medium"}[tier],
                "hypothesis": d.get("hypothesis", "Unknown"),
                "trigger": trigger_text,
                "is_conditional": is_conditional,
                "why": d.get("why", ""),
                "description": d.get("why", ""),
                "search_targets": d.get("search_targets", []),
                "cross_match": d.get("cross_match", []),
                "expected_outcome": d.get("why", ""),
                "likelihood": likelihood,
                "likelihood_is_estimated": d.get("_confidence_is_estimated", True),
                "cost": str(d.get("cost", "medium")).title(),
                "time_estimate": d.get("time_estimate", "Unknown"),
                "expected_evidence_gain": gain,
                "agencies_to_involve": d.get("agencies_to_involve", []),
                "expected_documents": d.get("expected_documents", []),
                "failure_conditions": d.get("failure_conditions", []),
                "confidence_impact_confirmed": d.get("confidence_impact_confirmed", round(gain * 0.7)),
                "confidence_impact_denied": d.get("confidence_impact_denied", -round(gain * 0.4)),
            })
        return result

    def generate_investigation_report(self, ctx, directions):
        critical = sum(1 for d in directions if d.get("priority_tier") == "P1")
        high = sum(1 for d in directions if d.get("priority_tier") == "P2")

        cf = []
        seen_hyps = set()
        for d in directions:
            hname = d.get("hypothesis", "")
            if hname in seen_hyps:
                continue
            seen_hyps.add(hname)
            h_conf, matched = self._match_hypothesis_confidence(hname, ctx.hypotheses)
            if not matched:
                continue
            cf.append({
                "hypothesis": hname,
                "current_confidence": h_conf,
                "if_confirmed": {
                    "confidence": min(95, h_conf + d.get("confidence_impact_confirmed", 0)),
                    "delta": d.get("confidence_impact_confirmed", 0),
                },
                "if_denied": {
                    "confidence": max(0, h_conf + d.get("confidence_impact_denied", 0)),
                    "delta": d.get("confidence_impact_denied", 0),
                },
                "driving_direction": d.get("title", ""),
            })

        return {
            "case_id": ctx.case_id,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total_directions": len(directions),
            "critical_count": critical,
            "high_count": high,
            "recommended_directions": directions,
            "counterfactual_analysis": cf,
        }
