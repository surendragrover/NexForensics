"""
analysis/reasoning.py — NexForensics reasoning-engine core layer:
builds the structured "reasoning" block (hypotheses, confidence deltas,
narrative) and the intelligence summary shown in the case report, plus a
regex-based timeline extractor.

Extracted from gradio_app.py, verbatim (no behavior change). `re` inside
_extract_timeline is a LOCAL import (`import re as _re`), as in the
original file.
"""

from utils import _safe_truncate


def _build_reasoning_engine(case_id, modus, location, suspect_name, entities, ocr_text,
                             photo, voice_clip, id_doc,
                             net_matches, fin_flags, veh_flags,
                             mo_links, unidentified_leads, watchlist):
    gaps, contradictions, hypotheses = [], [], []

    # ---------------- GAP DETECTION ----------------
    if not (modus or "").strip():
        gaps.append({
            "gap": "No Modus Operandi / narrative provided",
            "why_it_matters": "MO Fingerprinting and crime classification cannot run meaningfully without it",
            "next_step": "Collect a written account of what happened, in a witness's or subject's own words if possible",
        })
    if not (location or "").strip():
        gaps.append({
            "gap": "No location provided",
            "why_it_matters": "Geospatial context and case-linking checks are weaker without it",
            "next_step": "Confirm exact location, or the nearest known landmark",
        })
    if photo is None:
        gaps.append({
            "gap": "No photo evidence submitted",
            "why_it_matters": "Facial evidence and appearance-based leads are unavailable",
            "next_step": "Request any available photo or CCTV still, even low quality",
        })
    if not voice_clip:
        gaps.append({
            "gap": "No voice/audio evidence submitted",
            "why_it_matters": "Voice-print corroboration is unavailable",
            "next_step": "Check for recorded calls, voicemails, or witness voice notes",
        })
    if not id_doc:
        gaps.append({
            "gap": "No document evidence submitted",
            "why_it_matters": "OCR-based document/ID cross-checks are unavailable",
            "next_step": "Collect any related ID, letter, or receipt",
        })
    if not net_matches:
        gaps.append({
            "gap": "No known-associate / network data checked, or nothing matched",
            "why_it_matters": "Wider network connections may exist but weren't surfaced",
            "next_step": "List any names mentioned informally by witnesses in the Known Associates field",
        })
    if not fin_flags:
        gaps.append({
            "gap": "No financial trail checked",
            "why_it_matters": "Money flow can corroborate or rule out a motive",
            "next_step": "Request any bank/wallet references if available",
        })
    if not veh_flags:
        gaps.append({
            "gap": "No vehicle/asset data checked",
            "why_it_matters": "Vehicle movement can place a subject at, or rule them out of, a scene",
            "next_step": "Check for any plate numbers captured on CCTV or by witnesses",
        })
    persons_mentioned = (entities or {}).get("PERSON", [])
    if persons_mentioned and not (watchlist.get("dataset_matches", {}) or {}).get("count", 0):
        gaps.append({
            "gap": f"{len(persons_mentioned)} person name(s) appear in the evidence text but none were found in any database",
            "why_it_matters": "Could be a genuinely unrecorded individual, a name variant, or a misspelling",
            "next_step": "Try alternate spellings/transliterations, or check informal/local records",
        })

    # ---------------- CONTRADICTION DETECTION ----------------
    loc_entities = [l for l in (entities or {}).get("LOC", []) if l]
    stated_location = (location or "").strip().lower()
    if stated_location and loc_entities:
        mismatched = [l for l in loc_entities if stated_location not in l.lower() and l.lower() not in stated_location]
        if mismatched and len(mismatched) == len(loc_entities):
            contradictions.append({
                "contradiction": f"Location field says '{location}', but evidence text mentions a different location: {', '.join(loc_entities[:3])}",
                "sources": "Location field vs. Modus Operandi text (NER extraction)",
                "severity": "medium",
            })
    if suspect_name and persons_mentioned:
        claimed = suspect_name.strip().lower()
        other_names = [p for p in persons_mentioned if p and claimed not in p.lower() and p.lower() not in claimed]
        if other_names and len(other_names) == len(persons_mentioned):
            contradictions.append({
                "contradiction": f"Suspect Name field says '{suspect_name}', but a different name appears in the evidence text: {', '.join(other_names[:3])}",
                "sources": "Suspect Name field vs. Modus Operandi text (NER extraction)",
                "severity": "medium",
            })

    # ---------------- HYPOTHESIS GENERATION ----------------
    if mo_links.get("linked_cases"):
        # p23: linked_cases only holds links that passed the MO score threshold
        # and are in the same crime category; confidence comes from the score.
        top = mo_links["linked_cases"][0]
        try:
            from analysis.report_rules import mo_confidence_from_score
            _mo_conf = top.get("link_confidence") or mo_confidence_from_score(top.get("fingerprint_score", 0))
        except Exception:
            _mo_conf = "low"
        hypotheses.append({
            "hypothesis": f"This case may be connected to prior case {top.get('case_id','?')} ({top.get('crime_type','?')}) based on a matching MO signature",
            "supporting_evidence": [f"MO Fingerprinting match ({top.get('fingerprint_score', 0)}%): {(top.get('mo_description') or '')[:150]}"],
            "contradicting_evidence": ["No case_link has been confirmed by a human yet"] if not mo_links.get("confirmed_links") else [],
            "confidence": _mo_conf,
            "source": "crime_scenes (MO Fingerprinting)",
        })
    _variants = (watchlist or {}).get("possible_variant_matches") or []
    if _variants:
        _v0 = _variants[0]
        hypotheses.append({
            "hypothesis": (f"The suspect name '{suspect_name}' may be a spelling variant of dataset record "
                           f"'{_v0.get('name')}' ({', '.join(sorted({v.get('dataset','?') for v in _variants}))[:80]}) "
                           "- POSSIBLE match, identity not verified"),
            "supporting_evidence": [f"{v.get('name')} [{v.get('dataset')}] - transliteration match {v.get('pairs_text','')}"
                                    for v in _variants[:3]],
            "contradicting_evidence": ["Spelling-variant name match only: no photo/DOB/ID cross-check; namesakes are possible"],
            "confidence": "low-medium",
            "source": "master_search_index (Indian-name spelling-variant matcher)",
        })
    strong_net = [m for m in (net_matches or []) if m.get("strength") == "strong"]
    if strong_net:
        ds_list = ", ".join(sorted(set(m["dataset"] for m in strong_net)))[:80]
        hypotheses.append({
            "hypothesis": f"Subject/associates may be connected to known entities recorded in {ds_list}",
            "supporting_evidence": [f"{m['name']} — strong name match in {m['dataset']}" for m in strong_net[:3]],
            "contradicting_evidence": ["A name match alone does not confirm identity — could be a namesake"],
            "confidence": "medium",
            "source": "master_search_index (Network Intelligence)",
        })
    if unidentified_leads.get("possible_leads"):
        hypotheses.append({
            "hypothesis": "The unidentified suspect may match a known wanted/fugitive profile, based on MO and physical description similarity",
            "supporting_evidence": [f"{l['candidate_name_or_alias']} ({l['dataset']})" for l in unidentified_leads["possible_leads"][:3]],
            "contradicting_evidence": ["Physical descriptions are inherently approximate — meaningful false-positive risk"],
            "confidence": "low-medium",
            "source": "master_search_index (Agyat Apradhi search)",
        })
    if not hypotheses:
        hypotheses.append({
            "hypothesis": "The evidence gathered so far does not link this case to any known pattern, entity, or prior case — it may be an isolated incident, or evidence collection is still too thin to tell",
            "is_placeholder": True,
            "supporting_evidence": ["No dataset, network, or MO Fingerprinting matches were found"],
            "contradicting_evidence": [],
            "confidence": "low",
            "source": "Absence of matches across all sources searched",
        })

    # ---------------- DRAFT INVESTIGATIVE REPORT ----------------
    d_lines = [
        f"DRAFT — Case {case_id or '(unassigned)'}: AI-generated investigative lead. "
        "Requires human verification before any publication or action.",
        "",
    ]
    if (modus or "").strip():
        d_lines.append(f"The reported account of the incident: \"{_safe_truncate(modus.strip(), 300)}\" [Source: case intake].")
    if (location or "").strip():
        d_lines.append(f"The reported location is {location}. [Source: case intake]")
    if not mo_links.get("linked_cases") and mo_links.get("suppressed_links"):
        d_lines.append(f"No MO link found. {mo_links.get('note', '')} [Source: crime_scenes / MO Fingerprinting]")
    if mo_links.get("linked_cases"):
        d_lines.append(
            f"This case's MO signature resembles {len(mo_links['linked_cases'])} other case(s) on record, "
            f"most notably {mo_links['linked_cases'][0].get('case_id','?')}. "
            "[Source: crime_scenes / MO Fingerprinting — unverified, needs investigator review]"
        )
    if strong_net:
        d_lines.append(
            f"The evidence text references {len(strong_net)} name(s) with a strong match in existing records "
            f"({', '.join(sorted(set(m['dataset'] for m in strong_net)))[:80]}). [Source: master_search_index]"
        )
    if contradictions:
        d_lines.append(f"{len(contradictions)} contradiction(s) were flagged between different pieces of evidence — see below.")
    if gaps:
        d_lines.append(f"{len(gaps)} evidence gap(s) were identified that could materially change this assessment if filled.")
    d_lines += [
        "",
        "This narrative is a STARTING POINT ONLY. Every claim above must be independently "
        "verified, sourced, and edited by a human investigator/journalist before use.",
    ]

    return {
        "gaps": gaps,
        "contradictions": contradictions,
        "hypotheses": hypotheses,
        "draft_report": "\n".join(d_lines),
    }


_EVIDENCE_CHECKLIST_META = {
    "photo":    ("Photo",                   "High",   "Enables Face and Deepfake analysis"),
    "voice":    ("Voice sample",            "High",   "Enables voice-print / stress analysis"),
    "document": ("Supporting document/ID",  "Medium", "Enables OCR cross-checks"),
    "network":  ("Known associates",        "Medium", "Surfaces wider network connections"),
    "financial":("Financial IDs / wallets", "Medium", "Enables money-trail tracing"),
    "vehicle":  ("Vehicle / plate info",    "Medium", "Enables ANPR / movement tracing"),
    "digital":  ("Email/phone/URL leads",   "Low",    "Enables digital-footprint analysis"),
    "cctv_video": ("CCTV footage",          "High",   "Enables CCTV crime-scene classification on an extracted frame"),
}


def _build_intelligence_summary(evidence_provided, crime_info, watchlist, mo_links,
                                 unidentified_leads, reasoning, active_models,
                                 confidence_level, deception, risk):
    # ---- Evidence Completeness Meter ----
    total = len(_EVIDENCE_CHECKLIST_META)
    provided_count = sum(1 for k in _EVIDENCE_CHECKLIST_META if evidence_provided.get(k))
    completeness_pct = round((provided_count / total) * 100) if total else 0
    filled_blocks = round(completeness_pct / 10)
    completeness_bar = "█" * filled_blocks + "░" * (10 - filled_blocks)
    missing_evidence = [
        label for k, (label, _, _) in _EVIDENCE_CHECKLIST_META.items()
        if not evidence_provided.get(k)
    ]

    # ---- Next Evidence Recommendations (re-ranks Reasoning Engine gaps) ----
    next_evidence = []
    # p23: crime-type aware list (financial cases ask for loan/bank/MCA/ED-CBI/court
    # records, not voice/CCTV/vehicle). Falls back to the generic checklist.
    _typed = None
    try:
        from analysis.report_rules import next_evidence_for
        _typed = next_evidence_for(crime_info.get("crime_category", ""), crime_info.get("taxonomy_crimes", []),
                                   evidence_provided)
    except Exception:
        _typed = None
    if _typed:
        next_evidence.extend(_typed)
    else:
        for k, (label, priority, why) in _EVIDENCE_CHECKLIST_META.items():
            if not evidence_provided.get(k):
                next_evidence.append({"priority": priority, "recommendation": f"Obtain {label}", "reason": why})
    if mo_links.get("linked_cases") and not mo_links.get("confirmed_links"):
        next_evidence.append({
            "priority": "Medium",
            "recommendation": "Review possible MO-linked cases",
            "reason": f"{len(mo_links['linked_cases'])} case(s) share a similar signature — unconfirmed",
        })
    priority_rank = {"High": 0, "Medium": 1, "Low": 2}
    next_evidence.sort(key=lambda r: priority_rank.get(r["priority"], 3))

    # ---- Investigation Status panel (replaces the ambiguous single verdict) ----
    # BUG FIX (identity/sanctions contradiction — reported by reviewer):
    # this previously said "Yes" for a known-criminal/dataset match with no
    # link back to the fact that Identity Confidence is 0% (no independent
    # identity resolution has confirmed a specific individual for this
    # case). A reader could see "Known Criminal Match: Yes" + "Sanctions:
    # YES" on one page and "Identity Confidence: 0%" on another and
    # reasonably read that as a confirmed hit on a confirmed person — it
    # is neither. It is, at best, a name/alias string match against a
    # dataset. Every branch below now says so explicitly, and uses the
    # dataset engine's own match_confidence (STRONG/PARTIAL/WEAK) instead
    # of a flat "verify strength of match".
    _dm_count = (watchlist.get("dataset_matches", {}) or {}).get("count", 0)
    _match_conf = watchlist.get("match_confidence", "NONE")
    if _dm_count and str(_match_conf).upper().startswith("POSSIBLE"):
        known_match = (
            f"POSSIBLE — {_dm_count} dataset record(s) match a spelling variant of the name. "
            f"UNVERIFIED IDENTITY — name-only match; namesakes possible."
        )
    elif _dm_count:
        known_match = (
            f"Yes — {_dm_count} dataset record(s), name-match confidence {_match_conf}. "
            f"UNVERIFIED IDENTITY — no independent identity resolution confirms this "
            f"database record belongs to this specific individual."
        )
    elif watchlist.get("status") not in (None, "UNKNOWN"):
        known_match = f"Partial — {watchlist.get('status')} (name-match only, identity not independently confirmed)"
    else:
        known_match = "No"
    investigation_status = {
        "known_criminal_match": known_match,
        # This counts loaded/active AI MODULES (NER/Voice/Face/OCR/XGB),
        # not how much or how reliable the case's actual evidence is —
        # calling it "Evidence Confidence" reads as a finding about the
        # case when it's really infrastructure status. Renamed key +
        # explicit qualifier so it can't be confused with the real,
        # evidence-weighted canonical_confidence shown elsewhere.
        "analytical_source_coverage": f"{active_models}/5 AI modules loaded",
        "analytical_source_coverage_note": "server infrastructure, same for every case; not evidence coverage",
        "threat_severity": crime_info.get("severity", "Low"),
        "threat_severity_note": "Crime Classification signal — see Unified Severity Summary for other signals",
        "investigation_required": "Yes",
    }

    # ---- 5-point Investigation Intelligence Summary ----
    found_bits = []
    if crime_info.get("all_crimes"):
        found_bits.append(", ".join(crime_info["all_crimes"][:3]))
    if mo_links.get("linked_cases"):
        found_bits.append(f"{len(mo_links['linked_cases'])} MO-similar case(s)")
    if (watchlist or {}).get("possible_variant_matches"):
        found_bits.append(f"{len(watchlist['possible_variant_matches'])} POSSIBLE spelling-variant dataset record(s) (identity unverified)")
    if unidentified_leads.get("possible_leads"):
        found_bits.append(f"{len(unidentified_leads['possible_leads'])} unidentified-offender lead(s)")
    what_found = "; ".join(found_bits) if found_bits else "No dataset, network, or MO matches — evidence is currently self-contained"

    what_not_found = ", ".join(missing_evidence) if missing_evidence else "All core evidence types were provided"

    _real_h = [h for h in (reasoning.get("hypotheses") or []) if not h.get("is_placeholder")]
    if _real_h:
        top_h = max(_real_h, key=lambda h: {"high": 3, "medium-high": 2.5, "medium": 2, "low-medium": 1.5, "low": 1}.get(str(h.get("confidence", "")).lower(), 0))
        strongest_lead = f"{_safe_truncate(top_h.get('hypothesis', ''), 160)} (confidence: {top_h.get('confidence', 'N/A')})"
    else:
        strongest_lead = "No hypothesis currently has supporting evidence"
    if not mo_links.get("linked_cases") and (mo_links.get("suppressed_links") or not _real_h):
        try:
            from analysis.report_rules import mo_none_text
            _none = mo_none_text()
        except Exception:
            _none = "No MO link found."
        strongest_lead = (strongest_lead + ". " if _real_h else "") + _none

    weakest_link = (
        f"{len(reasoning.get('contradictions', []))} unresolved contradiction(s) in the evidence"
        if reasoning.get("contradictions")
        else (f"{next_evidence[0]['recommendation']} not yet on file" if _typed and next_evidence else
              f"{missing_evidence[0]} not yet collected" if missing_evidence else "No major weakness identified in evidence collected so far")
    )

    next_step = next_evidence[0]["recommendation"] if next_evidence else "Proceed to human review — no further automatic leads to chase"

    summary_points = {
        "what_was_found": what_found,
        "what_was_not_found": what_not_found,
        "strongest_lead": strongest_lead,
        "weakest_link": weakest_link,
        "next_step": next_step,
    }

    return {
        "completeness_pct": completeness_pct,
        "completeness_bar": completeness_bar,
        "missing_evidence": missing_evidence,
        "next_evidence": next_evidence[:8],
        "investigation_status": investigation_status,
        "summary_points": summary_points,
    }


def _extract_timeline(modus, incident_date):
    """Extract timeline events from Modus Operandi text."""
    if not modus:
        return []
    
    timeline = []
    import re as _re
    
    # Look for time patterns in the text
    time_patterns = [
        (_re.compile(r'(\d{1,2}:\d{2})'), 'Time'),
        (_re.compile(r'(\d{1,2})\s*(?:AM|PM)', _re.IGNORECASE), 'Time'),
        (_re.compile(r'(?:at|around|approximately)\s+(\d{1,2}:\d{2})', _re.IGNORECASE), 'Time'),
        (_re.compile(r'entered.*?(\d{1,2}:\d{2})', _re.IGNORECASE), 'Entry'),
        (_re.compile(r'exited.*?(\d{1,2}:\d{2})', _re.IGNORECASE), 'Exit'),
        (_re.compile(r'left.*?(\d{1,2}:\d{2})', _re.IGNORECASE), 'Departure'),
        (_re.compile(r'disabled.*?(\d{1,2}:\d{2})', _re.IGNORECASE), 'Security Disabled'),
        (_re.compile(r'reached.*?(\d{1,2}:\d{2})', _re.IGNORECASE), 'Arrival'),
    ]
    
    events = []
    for pattern, event_type in time_patterns:
        matches = pattern.findall(modus)
        for m in matches:
            time_str = m if isinstance(m, str) else m[0]
            time_str = time_str.strip()
            if time_str:
                events.append({
                    "time": time_str,
                    "event": event_type,
                })
    
    # BUG FIX (2026-08-24): when the narrative has no explicit time markers
    # (HH:MM, "at X:XX", etc.), this used to silently substitute a fixed,
    # identical placeholder timeline (Start/+4min/+8min/+15min/Unknown) —
    # every case without explicit timestamps got the EXACT SAME sequence,
    # which reads as if it were extracted from that case's own narrative
    # when it's pure boilerplate. Return an explicit empty-state marker
    # instead so the PDF can honestly say no timeline could be extracted,
    # rather than fabricating one.
    if not events:
        return []
    
    # Remove duplicates
    seen = set()
    unique_events = []
    for e in events:
        key = e["time"] + "_" + e["event"]
        if key not in seen:
            seen.add(key)
            unique_events.append(e)
    
    return unique_events[:8]
