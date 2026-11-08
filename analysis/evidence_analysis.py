"""
analysis/evidence_analysis.py — per-evidence-type analysis + crime
classification, used by run_analysis() while building up a case's
evidence_provided / entities / crime_info dicts.

NOTE: three sibling functions — _lookup_suspect_background,
_lookup_unidentified_offender, _analyze_network_evidence — are NOT here.
They call the module-level `ds_eng` (DatasetSearchEngine instance) that
gradio_app.py creates at import time; moving them would need `ds_eng`
passed in as a parameter (a real signature change, not a pure move), so
they were left in gradio_app.py for now rather than risk that edit.

Extracted from gradio_app.py, verbatim (no behavior change). All regex /
unicodedata imports used here are LOCAL (inside the functions themselves,
as in the original file).
"""

import re


def _kw_in(keyword, text):
    """Word-boundary keyword match — replaces naive `keyword in text`.

    BUG FIX (P0 — root cause of repeated "Physical Threat: HIGH" /
    Critical-severity false positives across multiple case reviews,
    including the NHAI toll-fraud case): plain substring matching means
    "killed" matches inside "skilled" ("a SKILLED software developer"),
    "rape" matches inside "therapeutic"/"grape"/"drape", "assault" matches
    inside "assaulting", etc. In a financial/fraud case narrative that
    happens to describe someone as "skilled", this single substring bug
    was silently classifying the case as Homicide with Critical severity
    — which then cascaded into an unsupported "Physical Threat: HIGH"
    verdict with no actual violence evidence anywhere in the case. Word-
    boundary matching (\\b...\\b) fixes this for single words; multi-word
    phrases ("shot dead") are matched literally, which is already safe.
    """
    return bool(re.search(r'\b' + re.escape(keyword) + r'\b', text))


def _classify_crime_from_evidence(entities, modus, suspect_name, ocr_text, face_res, vox_res, location="",
                                  incident_date="", crime_category=""):
    # p23 (2026-11-07): the suspect NAME is no longer part of the keyword text —
    # a person or company name is never a crime type or crime evidence.
    text = f"{modus or ''} {ocr_text or ''}".lower()
    crimes_detected = []
    severity = "Low"
    statutes = []
    evidence_found = []

    # p23: crime TYPES from the configurable taxonomy (analysis/report_rules.json).
    # Entity names (ORG/BANK/PERSON) are excluded as keywords.
    _tax_hits = []
    try:
        from analysis.report_rules import classify_crimes as _rr_classify
        _names = []
        for _k in ("ORG", "BANK", "PERSON", "AGENCY"):
            _names += list((entities or {}).get(_k, []) or [])
        if suspect_name:
            _names.append(suspect_name)
        _tax_hits = _rr_classify(f"{modus or ''} {ocr_text or ''}", exclude_terms=_names)
    except Exception:
        _tax_hits = []
    for _h in _tax_hits:
        crimes_detected.append(_h["crime"])
        severity = max(severity, _h["severity"], key=lambda x: ["Low","Medium","High","Critical"].index(x))
        evidence_found.append(f"Crime term '{_h['keyword']}' in narrative -> {_h['crime']} (allegation as written, not a finding)")

    # Financial crimes
    fin_keywords = {
        "money laundering": ("Money Laundering", "PMLA 2002 (India) / 18 U.S.C. § 1956", "High"),
        "tax evasion": ("Tax Evasion", "26 U.S.C. § 7201", "High"),
        "embezzlement": ("Embezzlement", "IPC 406 (India) / 18 U.S.C. § 656", "High"),
        "wire fraud": ("Wire Fraud", "18 U.S.C. § 1343", "High"),
        "bank fraud": ("Bank Fraud", "IPC 420 (India) / 18 U.S.C. § 1344", "High"),
        "ponzi": ("Securities Fraud / Ponzi", "18 U.S.C. § 1348", "Critical"),
        "bribe": ("Bribery", "18 U.S.C. § 201", "High"),
        "shell company": ("Shell Company Fraud", "18 U.S.C. § 1341", "High"),
        "offshore account": ("Offshore Tax Evasion", "26 U.S.C. § 7201", "High"),
        "loan default": ("Bank Loan Fraud / Willful Default", "IPC 420 + RBI wilful defaulter norms", "High"),
        "willful defaulter": ("Wilful Default / Bank Fraud", "RBI wilful defaulter circular / IPC 420", "High"),
        "fund diversion": ("Fund Diversion / Criminal Breach of Trust", "IPC 406 + PMLA 2002", "Critical"),
        # p23: removed "kingfisher" and "mallya" — a company or person name is
        # never a crime type. Crime types come from the taxonomy above.
        "extradition": ("Fugitive from Justice", "FEO Act 2018 / Extradition Treaty", "Critical"),
        "red corner": ("Interpol Red Notice Subject", "Interpol RCN + Extradition proceedings", "Critical"),
    }
    for keyword, (crime, statute, sev) in fin_keywords.items():
        if _kw_in(keyword, text):
            statutes.append(statute)
            if crime.lower() in {c.lower() for c in crimes_detected}:
                continue
            crimes_detected.append(crime)
            severity = max(severity, sev, key=lambda x: ["Low","Medium","High","Critical"].index(x))
            evidence_found.append(f"Keyword '{keyword}' found in evidence text")

    # Identity fraud
    id_keywords = {
        "fake id": ("Identity Document Fraud", "18 U.S.C. § 1028", "High"),
        "forged passport": ("Passport Fraud", "18 U.S.C. § 1543", "High"),
        "counterfeit": ("Counterfeiting", "18 U.S.C. § 471", "High"),
        "impersonate": ("Criminal Impersonation", "18 U.S.C. § 912", "Medium"),
        "stolen identity": ("Identity Theft", "18 U.S.C. § 1028A", "High"),
    }
    for keyword, (crime, statute, sev) in id_keywords.items():
        if _kw_in(keyword, text):
            crimes_detected.append(crime)
            statutes.append(statute)
            severity = max(severity, sev, key=lambda x: ["Low","Medium","High","Critical"].index(x))
            evidence_found.append(f"Identity fraud indicator: '{keyword}'")

    # Violent crimes
    # BUG FIX (2026-08-25): these only cited U.S. federal statutes (18
    # U.S.C. §...) with no Indian equivalent — for a case with an Indian
    # location (e.g. Gujarat/Haryana/Uttar Pradesh, as seen in production
    # test cases), suggesting only U.S. law is actively misleading for an
    # Indian-jurisdiction customer. Add the Indian Penal Code citation
    # alongside, matching the dual-citation convention already used
    # elsewhere in this same list (e.g. "IPC 406 (India) / 18 U.S.C. § 656"
    # for embezzlement, a few lines above).
    violent_keywords = {
        "assault": ("Assault", "IPC 351/352 (India) / 18 U.S.C. § 113", "High"),
        "sexual assault": ("Sexual Assault", "IPC 354/376 (India) / 18 U.S.C. § 2241", "Critical"),
        "trafficking": ("Human Trafficking", "IPC 370 (India) / 18 U.S.C. § 1591", "Critical"),
        "rape": ("Rape", "IPC 375/376 (India) / 18 U.S.C. § 2241", "Critical"),
        "murder": ("Murder", "IPC 302 (India) / 18 U.S.C. § 1111", "Critical"),
        "homicide": ("Homicide", "IPC 302/304 (India) / 18 U.S.C. § 1111", "Critical"),
        "killed": ("Homicide", "IPC 302/304 (India) / 18 U.S.C. § 1111", "Critical"),
        "fatally": ("Homicide", "IPC 302/304 (India) / 18 U.S.C. § 1111", "Critical"),
        "shot dead": ("Homicide", "IPC 302 (India) / 18 U.S.C. § 1111", "Critical"),
        "gunned down": ("Homicide", "IPC 302 (India) / 18 U.S.C. § 1111", "Critical"),
        # BUG FIX (P0 — reviewer feedback, repeated NHAI-case regression):
        # "executed" used to map to Homicide/Critical on a bare substring
        # match — but "executed" is everyday business/legal English
        # ("the fraud scheme was executed via...", "the agreement was
        # executed on..."). In a financial/fraud case narrative this
        # false-positives into "Weapons Violation"/"Homicide" crime
        # classification with Critical severity, which then drove Physical
        # Threat to HIGH even with zero actual violence evidence. Removed
        # as a bare-word trigger — genuine homicide-by-execution narratives
        # are still caught by "murder", "killed", "shot dead", etc. above.
        "kidnap": ("Kidnapping", "IPC 363/364 (India) / 18 U.S.C. § 1201", "Critical"),
        "hostage": ("Kidnapping / Hostage-Taking", "IPC 364A (India) / 18 U.S.C. § 1201", "Critical"),
        "extortion": ("Extortion", "IPC 384 (India) / 18 U.S.C. § 1951", "High"),
        "weapon": ("Weapons Violation", "Arms Act 1959 (India) / 18 U.S.C. § 922", "High"),
        "firearm": ("Weapons Violation", "Arms Act 1959 (India) / 18 U.S.C. § 922", "High"),
        "handgun": ("Weapons Violation", "Arms Act 1959 (India) / 18 U.S.C. § 922", "High"),
        "gunshot": ("Weapons Violation", "Arms Act 1959 (India) / 18 U.S.C. § 922", "High"),
        "shooting": ("Weapons Violation", "Arms Act 1959 (India) / 18 U.S.C. § 922", "High"),
        "stabbed": ("Assault with a Deadly Weapon", "IPC 324/326 (India) / 18 U.S.C. § 113", "Critical"),
        "stabbing": ("Assault with a Deadly Weapon", "IPC 324/326 (India) / 18 U.S.C. § 113", "Critical"),
        "threat": ("Criminal Threat", "IPC 503/506 (India) / 18 U.S.C. § 875", "Medium"),
    }
    for keyword, (crime, statute, sev) in violent_keywords.items():
        if _kw_in(keyword, text):
            crimes_detected.append(crime)
            statutes.append(statute)
            severity = max(severity, sev, key=lambda x: ["Low","Medium","High","Critical"].index(x))
            evidence_found.append(f"Violent crime indicator: '{keyword}'")

    # ─── CYBERCRIME DETECTION ──────────────────────────────────────────────
    cyber_keywords = {
        "hacking": ("Computer Hacking", "18 U.S.C. § 1030", "High"),
        "ransomware": ("Ransomware Attack", "18 U.S.C. § 1030 + § 1951", "Critical"),
        "phishing": ("Phishing Fraud", "18 U.S.C. § 1028", "Medium"),
        "identity theft": ("Identity Theft", "18 U.S.C. § 1028A", "High"),
        "data breach": ("Data Breach", "18 U.S.C. § 1030 + GDPR/DPDP", "High"),
        "dark web": ("Dark Web Criminal Activity", "18 U.S.C. § 1030", "High"),
        "ddos": ("DDoS Attack", "18 U.S.C. § 1030", "Medium"),
        "malware": ("Malware Distribution", "18 U.S.C. § 1030", "High"),
        "crypto theft": ("Cryptocurrency Theft", "18 U.S.C. § 1343", "High"),
    }
    for keyword, (crime, statute, sev) in cyber_keywords.items():
        if _kw_in(keyword, text):
            crimes_detected.append(crime)
            statutes.append(statute)
            severity = max(severity, sev, key=lambda x: ["Low","Medium","High","Critical"].index(x))
            evidence_found.append(f"Cybercrime indicator: '{keyword}'")
    # ─── END CYBERCRIME ──────────────────────────────────────────────────

    # Entity-based
    if entities:
        if entities.get("CRIME"):
            # p23: NER crime terms are evidence notes, not a crime type of their own
            evidence_found.append(f"NER crime terms in narrative: {', '.join(entities.get('CRIME', [])[:5])}")
        if entities.get("WEAPON"):
            crimes_detected.append("Weapons References Found")
            evidence_found.append(f"Weapons: {', '.join(entities.get('WEAPON', [])[:5])}")
            severity = max(severity, "High", key=lambda x: ["Low","Medium","High","Critical"].index(x))
        if entities.get("THREAT"):
            crimes_detected.append("Threat Language Detected")
            evidence_found.append(f"Threats: {', '.join(entities.get('THREAT', [])[:5])}")

    # Face evidence: p23 — the old "anomaly" was derived from the ArcFace
    # embedding norm, which says nothing about disguise/masks/deepfakes. It no
    # longer creates a crime type (deepfake model output is reported separately).

    # Voice evidence
    if vox_res and vox_res.get("name_match") is False:
        crimes_detected.append("Voice Identity Fraud")
        evidence_found.append(f"Voice-name mismatch: claimed vs recognized speaker")
        severity = max(severity, "High", key=lambda x: ["Low","Medium","High","Critical"].index(x))

    # Document evidence
    if ocr_text and len(ocr_text) < 10:
        evidence_found.append("Document barely readable — possible forgery/tampering")

    crimes_detected = list(dict.fromkeys(crimes_detected))  # p42: no duplicate crime names
    if not crimes_detected:
        crimes_detected = ["Under Investigation — No Specific Crime Pattern Detected"]
        evidence_found.append("Insufficient evidence for crime classification")
    if not statutes:
        statutes = ["Pending Evidence Review"]

    # BUG FIX (2026-08-25): jurisdiction was a hardcoded constant
    # ("Federal / State / International") and statute citations always
    # showed U.S. federal codes (with an Indian citation appended
    # alongside as of the previous fix) regardless of the case's actual
    # location. For an Indian-location case, defaulting to a dual U.S./India
    # citation still overstates U.S. relevance — detect Indian jurisdiction
    # from the location text and, when confident, show ONLY the Indian
    # citation, dropping the U.S. Code reference entirely (an investigator
    # can still cross-reference U.S. law manually if genuinely needed for
    # an international case).
    INDIAN_JURISDICTION_MARKERS = (
        "india", "delhi", "mumbai", "bengaluru", "bangalore", "chennai", "kolkata",
        "hyderabad", "pune", "ahmedabad", "gujarat", "haryana", "uttar pradesh",
        "maharashtra", "rajasthan", "punjab", "karnataka", "tamil nadu", "kerala",
        "west bengal", "bihar", "madhya pradesh", "telangana", "andhra pradesh",
        "odisha", "assam", "jharkhand", "chandigarh", "noida", "gurugram", "gurgaon",
        "faridabad", "okhla", "jaipur", "lucknow", "surat", "nagpur", "indore",
    )
    location_lower = str(location or "").lower()
    is_indian_jurisdiction = any(marker in location_lower for marker in INDIAN_JURISDICTION_MARKERS)

    # p23: country detection also reads the narrative and entities (ED, CBI,
    # PMLA, INR, Indian banks ...), not only the location field.
    _country = {"code": None, "basis": []}
    _law = None
    try:
        from analysis.report_rules import detect_country as _rr_country, suggest_laws as _rr_laws
        _country = _rr_country(location, f"{modus or ''} {ocr_text or ''}", entities)
        if _country.get("code") == "IN":
            is_indian_jurisdiction = True
            _law = _rr_laws(_country, _tax_hits, incident_date)
    except Exception:
        _law = None

    combined_statutes = ", ".join(set(statutes))
    if _law is not None:
        combined_statutes = _law["statutes"]
        jurisdiction_label = _law["jurisdiction"]
    elif is_indian_jurisdiction:
        # Strip the "/ 18 U.S.C. § ..." portion from each dual-citation
        # entry, keeping only the Indian statute reference.
        import re as _re_jur
        combined_statutes = _re_jur.sub(r"\s*/\s*18 U\.S\.C\.[^,]*", "", combined_statutes)
        jurisdiction_label = f"India (detected from location: {location.strip()})"
    else:
        jurisdiction_label = "Not confidently detected (no country markers in location or narrative)"

    return {
        "primary": crimes_detected[0] if crimes_detected else "Under Investigation",
        "secondary": ", ".join(crimes_detected[1:4]) if len(crimes_detected) > 1 else "None identified",
        "all_crimes": crimes_detected,
        "severity": severity,
        "statutes": combined_statutes,
        "jurisdiction": jurisdiction_label,
        "is_indian_jurisdiction": is_indian_jurisdiction,
        "evidence_found": evidence_found,
        # p23 extras
        "country": _country,
        "law": _law or {},
        "law_label": (_law or {}).get("label") or "AI-suggested from keyword match — NOT verified; confirm against actual jurisdiction/counsel before citing",
        "law_action": (_law or {}).get("action", ""),
        "taxonomy_crimes": _tax_hits,
        "crime_category": crime_category or "",
    }


def _analyze_text_evidence(entities, modus, suspect_name, location):
    evidence_details = []
    if entities:
        significance_map = {
            "PERSON": "May indicate accomplices, victims, or witnesses",
            "CRIME": "Direct crime references — HIGH PRIORITY",
            "WEAPON": "Weapon mentions — potential violence indicator",
            "THREAT": "Threat language — escalation risk",
            "ORG": "Organisation named in the narrative — context only, not evidence of wrongdoing",
            "BANK": "Bank named in the narrative — context (lender/account holder), not evidence of wrongdoing",
            "AGENCY": "Investigating/regulatory agency named — source of the allegation, not a finding",
            "LAW": "Statute named in the narrative — as cited by the source, not verified",
            "GPE": "Geographic locations — travel pattern analysis",
            "MONEY": "Financial references — money laundering indicator",
            "DATE": "Temporal markers — timeline reconstruction",
            # ─── ADD THESE ──────────────────────────────────────────────
            "DRUG": "Narcotics references — drug trafficking indicator",
            "VEHICLE": "Vehicle references — asset tracking",
            "EMAIL": "Digital footprints — cyber investigation",
            "PHONE": "Communication patterns — network analysis",
            "URL": "Web presence — digital evidence",
            # ─── END NEW ENTITIES ──────────────────────────────────────
        }
        for entity_type, values in entities.items():
            if values:
                evidence_details.append({
                    "type": f"{entity_type} Detected",
                    "values": values[:10],
                    "count": len(values),
                    "significance": significance_map.get(entity_type, "Requires analyst review"),
                })
    if modus:
        word_count = len(modus.split())
        evidence_details.append({
            "type": "Statement Analysis",
            "values": [f"{word_count} words"],
            "count": word_count,
            "significance": "Detailed" if word_count > 50 else "Brief" if word_count > 20 else "Minimal",
        })
    return evidence_details


def _analyze_facial_evidence(face_res, photo_meta):
    if not face_res:
        return {"status": "No facial evidence submitted", "findings": [], "risk_indicators": []}
    findings = []
    risk_indicators = []
    # p23 (2026-11-07): the former "facial anomaly %" was (1 - embedding_norm/25)
    # — a property of the ArcFace vector length, not evidence of a disguise,
    # mask or deepfake. It is shown only as a non-evidentiary technical metric
    # and feeds no score. Deepfake/tamper status comes from the deepfake model.
    findings.append("Face embedding computed (ArcFace). No reference face was compared, so no identity finding.")
    if face_res.get("embedding_norm"):
        findings.append(f"Technical metric (non-evidentiary): embedding norm {face_res['embedding_norm']:.3f}")
    technical = []
    if photo_meta:
        if "GPS_Latitude" in photo_meta:
            findings.append(f"GPS coordinates embedded: {photo_meta['GPS_Latitude']}, {photo_meta['GPS_Longitude']}")
            technical.append("Location data available for geospatial analysis")
        if "DateTime_Original" in photo_meta:
            findings.append(f"Photo timestamp: {photo_meta['DateTime_Original']}")
    return {"status": "Evidence analyzed", "findings": findings, "risk_indicators": risk_indicators,
            "technical_notes": technical, "photo_metadata": photo_meta}


def _analyze_voice_evidence(vox_res, audio_meta):
    if not vox_res:
        return {"status": "NOT SUBMITTED - no voice clip uploaded; voice analysis did not run", "findings": [], "risk_indicators": []}
    findings = []
    risk_indicators = []
    top_speaker = vox_res.get("top_speaker", "Unknown")
    conf = vox_res.get("voice_match_conf", 0)
    findings.append(f"Closest training-set speaker index: {top_speaker} (confidence {conf:.1f}%) - not an identity")
    if vox_res.get("name_match_note"):
        findings.append(f"Identity match: {vox_res['name_match_note']}")
    if vox_res.get("name_match") is True:
        findings.append("Voice matches claimed identity")
    elif vox_res.get("name_match") is False:
        findings.append("Voice DOES NOT MATCH claimed identity")
        risk_indicators.append("Identity fraud — claimed name differs from voice biometric")
    stress = vox_res.get("stress_score", 0)
    if stress > 70:
        findings.append(f"High vocal stress: {stress:.1f}%")
        risk_indicators.append("Elevated stress may indicate deception or coercion")
    elif stress > 40:
        findings.append(f"Moderate vocal stress: {stress:.1f}%")
    else:
        findings.append(f"Normal vocal stress: {stress:.1f}%")
    if audio_meta:
        findings.append(f"Audio duration: {audio_meta.get('Duration_sec', 'N/A')}s")
    return {"status": "Evidence analyzed", "findings": findings, "risk_indicators": risk_indicators, "audio_metadata": audio_meta}


def _analyze_document_evidence(ocr_text, ocr_res, doc_meta):
    # BUG FIX (identity/evidence contradiction — reported by reviewer):
    # this used to collapse two different situations into one status
    # string — "no document was ever uploaded" and "a document WAS
    # uploaded but OCR extracted no readable text" — both showed as
    # "No document evidence submitted". That produced a direct
    # contradiction elsewhere in the same report (e.g. a page showing
    # Files_Count: 4 / a document hash / a PDF filename right next to a
    # page stating no document evidence was submitted). Distinguish the
    # two cases using doc_meta (which reflects files actually uploaded,
    # independent of whether OCR could read them).
    files_provided = bool(doc_meta and doc_meta.get("Files_Count", 0))

    if not ocr_text:
        if files_provided:
            return {
                "status": "Document(s) submitted — OCR extracted no readable text",
                "findings": [f"{doc_meta.get('Files_Count', 0)} document file(s) were uploaded, "
                             f"but no readable text could be extracted (OCR failed or module offline)"],
                # BUG FIX (reviewer feedback): "OCR couldn't read the file"
                # used to go into `risk_indicators`, the SAME list used
                # elsewhere to mean "this document shows signs of fraud/
                # tampering". That made an unreadable scan (blur, bad
                # lighting, wrong format, OCR module offline — none of
                # which imply wrongdoing) get reported downstream as
                # "Document tampering indicates possible digital forgery
                # skills" and bump the Cyber Threat rating. An OCR read
                # failure is a DATA-QUALITY issue, not a fraud signal, so
                # it goes in `technical_issues` instead — surfaced in the
                # report, but excluded from fraud/tampering/cyber-threat
                # scoring, which now only fires on genuine fraud signals
                # (name mismatch, or actual forgery indicators established
                # once a document IS readable).
                "risk_indicators": [],
                "technical_issues": ["Document unreadable by OCR — possible poor scan quality, "
                                      "unsupported format, or OCR module unavailable; this is a "
                                      "technical read failure, NOT evidence of tampering or forgery"],
                "extracted_text": "",
                "document_metadata": doc_meta,
            }
        return {"status": "No document evidence submitted", "findings": [], "risk_indicators": [], "extracted_text": "", "document_metadata": {}}
    findings = []
    risk_indicators = []
    findings.append(f"Document text extracted: {len(ocr_text)} characters")
    match = ocr_res.get("match") if ocr_res else None
    if match is True:
        findings.append("Document name matches suspect identity")
    elif match is False:
        findings.append("Document name DOES NOT MATCH suspect identity")
        risk_indicators.append("Document fraud — name mismatch indicates possible forgery")
    if len(ocr_text) < 20:
        risk_indicators.append("Document barely readable — possible deliberate damage or poor-quality forgery")
    if doc_meta:
        n_files = doc_meta.get('Files_Count', 0)
        findings.append(f"Document file(s) processed: {n_files}")
        for f in doc_meta.get('Files', []):
            if f.get('Type') == 'PDF':
                findings.append(f"  • {f.get('File','?')} — PDF, {f.get('Pages','?')} page(s)")
            else:
                findings.append(f"  • {f.get('File','?')} — image, {f.get('Document_Size','?')}")
    return {"status": "Evidence analyzed", "findings": findings, "risk_indicators": risk_indicators, "extracted_text": ocr_text[:200], "document_metadata": doc_meta}


def _compute_fraud_from_evidence(entities, face_evidence, voice_evidence, doc_evidence, ocr_text, photo, id_doc, suspect_name):
    indicators = {}
    evidence_notes = []

    doc_forgery = 10.0
    if doc_evidence.get("status") == "Evidence analyzed":
        if doc_evidence.get("risk_indicators"):
            doc_forgery += 30
            evidence_notes.append("Document risk indicators detected")
        if not ocr_text or len(ocr_text) < 20:
            doc_forgery += 25
            evidence_notes.append("Document unreadable — possible forgery")
    else:
        doc_forgery = 0.0
    indicators["document_forgery"] = round(min(doc_forgery, 95.0), 1)

    id_fraud = 15.0
    mismatch_count = 0
    # p23: face embedding alone (no reference face) cannot indicate identity fraud
    if voice_evidence.get("risk_indicators"):
        mismatch_count += 1
        evidence_notes.append("Voice-name mismatch detected")
    if doc_evidence.get("risk_indicators"):
        mismatch_count += 1
        evidence_notes.append("Document-name mismatch detected")
    id_fraud += mismatch_count * 20
    indicators["identity_fraud"] = round(min(id_fraud, 95.0), 1)

    fin_anomaly = 5.0
    if entities:
        org_count = len(entities.get("ORG", []))
        money_count = len(entities.get("MONEY", []))
        fin_anomaly += org_count * 8 + money_count * 15
        if org_count > 0:
            evidence_notes.append(f"{org_count} organization(s) referenced")
    indicators["financial_anomaly"] = round(min(fin_anomaly, 95.0), 1)

    mo_match = 0.0
    if entities.get("CRIME"): mo_match += 20
    if entities.get("WEAPON"): mo_match += 15
    if entities.get("THREAT"): mo_match += 10
    if voice_evidence.get("risk_indicators"): mo_match += 10
    if doc_evidence.get("risk_indicators"): mo_match += 10
    if mismatch_count >= 2: mo_match += 20
    indicators["mo_match"] = round(min(mo_match, 95.0), 1)

    # ─── DIGITAL FOOTPRINT ANOMALY ────────────────────────────────
    digital_anomaly = 5.0
    if entities:
        emails = len(entities.get("EMAIL", []))
        urls = len(entities.get("URL", []))
        phones = len(entities.get("PHONE", []))

        if emails > 3:
            digital_anomaly += 15
            evidence_notes.append(f"{emails} email addresses found — high digital footprint")
        if urls > 2:
            digital_anomaly += 10
            evidence_notes.append(f"{urls} URLs found — online presence detected")
        if phones > 2:
            digital_anomaly += 8
            evidence_notes.append(f"{phones} phone numbers found — communication network")

        if any("temp" in e.lower() or "throwaway" in e.lower() or "fake" in e.lower()
               for e in (entities.get("EMAIL", []) + entities.get("URL", []))):
            digital_anomaly += 25
            evidence_notes.append("Disposable/temp email or URL detected — evasion indicator")

    indicators["digital_anomaly"] = round(min(digital_anomaly, 95.0), 1)
    # ─── END DIGITAL ANOMALY ──────────────────────────────────────────────

    flags = []
    if entities.get("CRIME"): flags.append(f"Crime references: {', '.join(entities['CRIME'][:3])}")
    if entities.get("WEAPON"): flags.append(f"Weapon references: {', '.join(entities['WEAPON'][:3])}")
    if entities.get("THREAT"): flags.append(f"Threat language: {', '.join(entities['THREAT'][:3])}")
    if voice_evidence.get("risk_indicators"): flags.extend(voice_evidence["risk_indicators"])
    if face_evidence.get("risk_indicators"): flags.extend(face_evidence["risk_indicators"])
    if doc_evidence.get("risk_indicators"): flags.extend(doc_evidence["risk_indicators"])
    indicators["behavioral_flags"] = flags if flags else ["No suspicious behavioral indicators detected"]
    indicators["evidence_notes"] = evidence_notes if evidence_notes else ["Clean evidence profile"]

    return indicators


def _fix_entity_name_type(entity_name, entity_type):
    """
    Some synced datasets (e.g. the Interpol CSV) have their columns
    swapped at the source — entity_name ends up holding a generic label
    like "Person"/"Organization" while entity_type holds the actual name.
    Detect that pattern and swap back so the real name is what gets shown.
    """
    GENERIC_LABELS = {"person", "organization", "vessel", "aircraft",
                       "entity", "company", "corporate", "individual"}
    name_l = (entity_name or "").strip().lower()
    type_l = (entity_type or "").strip().lower()
    if name_l in GENERIC_LABELS and type_l and type_l not in GENERIC_LABELS:
        return entity_type.strip(), entity_name.strip()
    return (entity_name or "").strip(), (entity_type or "").strip()


def _name_match_strength(query_name, candidate_name, data_blob=""):
    """
    Classifies how strong a name match is, since a FULLTEXT/LIKE hit can
    range from "exact same person" to "shares one common surname with a
    totally different person" (e.g. "Hafiz Saeed" vs "Ahmad Omar Saeed
    Sheikh" — both contain "Saeed" but are unrelated). Returns "strong",
    "partial", or "weak".

    For datasets where entity_name is empty (e.g. modus_operandi rows only
    have a free-text "text" field, no structured name column), falls back
    to checking whether the query name appears as a phrase in data_blob —
    an exact phrase hit there is stronger evidence than a bare word-overlap
    against a populated but different entity_name would be.
    """
    q_norm = query_name.strip().lower()
    q_words = set(w for w in re.findall(r"[a-zA-Z]+", q_norm) if len(w) > 2)
    c_norm = (candidate_name or "").strip().lower()
    c_words = set(w for w in re.findall(r"[a-zA-Z]+", c_norm) if len(w) > 2)

    # ─── PHONETIC MATCHING (for name variations) ──────────────
    # e.g., "Muhammad" vs "Mohammad", "Ahmed" vs "Ahmad"
    import unicodedata
    def _phonetic_normalize(name):
        nfkd = unicodedata.normalize('NFKD', name)
        without_diacritics = ''.join([c for c in nfkd if not unicodedata.combining(c)])
        replacements = {
            'muhammad': 'mohammad', 'muhammed': 'mohammad', 'mohammed': 'mohammad',
            'ahmad': 'ahmed', 'ahemd': 'ahmed',
            'yusuf': 'yousef', 'yusef': 'yousef',
            'khaled': 'khalid', 'khaleed': 'khalid',
            'sayed': 'syed', 'saiyid': 'syed',
        }
        low = without_diacritics.lower()
        for k, v in replacements.items():
            if k in low:
                low = low.replace(k, v)
        return low

    if c_norm:
        q_phon = _phonetic_normalize(q_norm)
        c_phon = _phonetic_normalize(c_norm)
        if q_phon == c_phon and q_norm != c_norm:
            return "strong"  # same name, different spelling/transliteration
    # ─── END PHONETIC MATCHING ────────────────────────────────────────────

    if not c_norm and data_blob:
        # No structured name on this row — check the free-text blob instead.
        blob_l = data_blob.lower()
        if q_norm and q_norm in blob_l:
            return "strong"
        if q_words:
            hits = sum(1 for w in q_words if w in blob_l)
            coverage = hits / len(q_words)
            if coverage >= 0.8:
                return "strong"
            if coverage >= 0.5:
                return "partial"
        return "weak"

    if not q_words or not c_words:
        return "weak"
    if q_norm == c_norm:
        return "strong"

    overlap = q_words & c_words
    if not overlap:
        return "weak"
    coverage_q = len(overlap) / len(q_words)

    # All of the query's words are present in the candidate (e.g. searching
    # "Bishnoi" and matching "Lawrence Bishnoi Gang") -> confident match —
    # BUT ONLY if the candidate isn't a substantially longer, different
    # full name that merely happens to contain the same word(s). Two words
    # shared inside a 4-word name (e.g. querying "Subhash Chandra" and
    # matching the freedom fighter "Alluri Subhash Chandra Bose") is a
    # real, previously-seen false positive: the algorithm reported it as a
    # "strong"/"CONFIRMED" match even though these are different people.
    # A short, common suffix like "Gang"/"Group"/"Network" is fine; two or
    # more EXTRA distinct name-words beyond the query is not.
    _COMMON_SUFFIX_WORDS = {"gang", "group", "network", "syndicate", "cartel", "crew", "family"}
    extra_words = c_words - q_words
    substantive_extra = extra_words - _COMMON_SUFFIX_WORDS
    if coverage_q == 1.0:
        if len(substantive_extra) <= 1:
            return "strong"
        # Candidate has 2+ additional distinct name-words the query never
        # mentioned — treat as a possibly-different individual, not a
        # confirmed match, until a human verifies it.
        return "partial"
    # Multiple distinct words overlap -> real signal, not a coincidence.
    if len(overlap) >= 2 and coverage_q >= 0.5:
        return "partial"
    # Exactly one shared word out of a multi-word name is usually just a
    # common surname/first-name coincidence (e.g. "Saeed", "Khan", "Singh")
    # — do not treat that as a confirmed or even partial match.
    return "weak"


def _assess_threat_from_evidence(deception, risk, crime_info, fraud_indicators, watchlist, text_evidence, face_evidence, voice_evidence, doc_evidence, case_priority="Medium"):
    physical = "None"
    # BUG FIX (2026-08-25): any weapon/assault/murder keyword hit — no
    # matter how severe the resulting crime classification — hardcoded
    # this straight to "Medium". A case classified Critical severity
    # (e.g. Homicide + Weapons Violation together) still showed Physical
    # Threat: Medium, directly contradicting the Crime Classification
    # section a page earlier in the same report. Scale with the actual
    # crime severity, same pattern already used for public_safety below.
    if crime_info.get("severity") == "Critical" and crime_info.get("all_crimes") and \
       any("Weapon" in c or "Assault" in c or "Murder" in c or "Homicide" in c for c in crime_info["all_crimes"]):
        physical = f"HIGH — Critical-severity violent crime classified ({crime_info.get('primary', 'N/A')})"
    elif crime_info.get("all_crimes") and any("Weapon" in c or "Assault" in c or "Murder" in c for c in crime_info["all_crimes"]):
        physical = "Medium"
    if watchlist.get("status", "").startswith("DECEASED"):
        physical = "LOW — Subject deceased, no active physical threat"
    elif watchlist.get("prior_arrests") and len(watchlist["prior_arrests"]) > 1:
        physical = "Medium — History of violence-related arrests" if physical in ("None", "Medium") else physical
    # ─── CASE PRIORITY OVERRIDE ──────────────────────────────────────────
    # BUG FIX (P0 — reviewer feedback, repeated across multiple case
    # reviews): this used to turn ANY case marked High/Critical priority
    # (an administrative/workflow field the investigator sets for their
    # own case-management reasons — urgency, media attention, seniority
    # of who's asking — not a measure of physical danger) into a
    # confident "Physical Threat: HIGH" with no weapon/violence evidence
    # behind it at all. That is a category error: administrative urgency
    # is not evidence of physical danger. A financial/toll-fraud/document
    # case correctly flagged Critical priority for entirely non-violent
    # reasons should never get "HIGH — Critical case priority, active
    # investigation required" as its Physical Threat line. Report this
    # honestly as UNKNOWN rather than asserting a threat level the
    # evidence doesn't support.
    if case_priority in ("High", "Critical") and physical == "None":
        physical = (f"UNKNOWN — no weapon/violence evidence on file; case is flagged {case_priority} "
                     f"priority for case-management reasons unrelated to physical-threat evidence")
    # ─── END CASE PRIORITY OVERRIDE ──────────────────────────────────────

    # p23 (2026-11-07): every financial/cyber/escalation level states its basis;
    # with no evidence it reads NOT ASSESSED. Case priority is a workflow field,
    # not evidence, and no longer raises these.
    basis = {}
    try:
        from analysis.report_rules import financial_crimes_in as _fin_in, NOT_ASSESSED as _NA
    except Exception:
        _fin_in, _NA = (lambda xs: []), "NOT ASSESSED"
    _fin_crimes = _fin_in(crime_info.get("all_crimes", []))
    financial = f"{_NA} — no financial evidence or financial offence in the narrative"
    basis["financial"] = "No financial crime terms, financial IDs or SAR records on file"
    if watchlist.get("fintrac_sar") == "YES":
        financial = "HIGH — Prior suspicious activity reports on file"
        basis["financial"] = "SAR record on file (dataset)"
    elif _fin_crimes:
        _lvl = "HIGH" if len(_fin_crimes) >= 2 or crime_info.get("severity") in ("High", "Critical") else "Medium"
        financial = f"{_lvl} — narrative alleges {', '.join(_fin_crimes[:3])}"
        basis["financial"] = ("Financial offence terms in the case narrative (allegations as written, not findings); "
                              "no transaction records analysed")
    elif fraud_indicators["financial_anomaly"] > 30:
        financial = "Medium — financial references in the narrative"
        basis["financial"] = f"NER organisation/money references (financial anomaly {fraud_indicators['financial_anomaly']:.1f}%)"

    cyber = f"{_NA} — no cyber/digital evidence submitted or classified"
    basis["cyber"] = "No cybercrime terms, digital identifiers or document-fraud indicators"
    if doc_evidence.get("risk_indicators"):
        basis["cyber"] = "Document fraud indicators (see Document Evidence)"
        # BUG FIX (reviewer feedback): this used to fire on ANY doc_evidence
        # risk_indicator, including a plain OCR-read failure (bad scan,
        # wrong format, OCR module offline) — which got worded as "possible
        # digital forgery skills", a much stronger and more specific claim
        # than the evidence supports. `risk_indicators` is now reserved for
        # genuine document-fraud signals only (name mismatch, suspiciously
        # sparse extracted text) — a bare OCR failure lives in
        # `technical_issues` instead and never reaches this branch.
        cyber = "Medium — Document evidence shows fraud indicators (see Document Evidence findings) — investigate for possible forgery"
    # ─── Fix: cyber threat must reflect actual cybercrime classification ──
    CYBER_CRIME_TYPES = (
        "Computer Hacking", "Ransomware Attack", "Phishing Fraud", "Identity Theft",
        "Data Breach", "Dark Web Criminal Activity", "DDoS Attack",
        "Malware Distribution", "Cryptocurrency Theft",
    )
    detected_cyber_crimes = [c for c in crime_info.get("all_crimes", []) if c in CYBER_CRIME_TYPES]
    if detected_cyber_crimes:
        cyber = f"HIGH — Cybercrime indicators classified: {', '.join(detected_cyber_crimes[:3])}"
        basis["cyber"] = "Cybercrime terms classified from the narrative"

    public = "None"
    if crime_info.get("_risk_heuristic"):
        pass  # p23: a heuristic risk number is not evidence of a public-safety threat
    elif risk > 75:
        public = "HIGH — Composite risk exceeds threshold"
    elif risk > 50:
        public = "Medium — Elevated risk profile"
    if watchlist.get("status", "").startswith("DECEASED"):
        public = "Medium — Subject deceased but associates/network may remain active"
    # ─── Fix: crime severity must be able to raise public-safety risk ────
    if crime_info.get("severity") == "Critical":
        public = f"HIGH — Critical-severity crime classified ({crime_info.get('primary', 'N/A')})"
    elif crime_info.get("severity") == "High" and public == "None":
        public = f"Medium — High-severity crime classified ({crime_info.get('primary', 'N/A')})"
    # ─── CASE PRIORITY OVERRIDE ──────────────────────────────────────────
    if case_priority in ("High", "Critical") and public == "None":
        public = "HIGH — Critical case priority demands immediate attention"
    # p38: a non-violent financial offence is not a public-safety threat; severity
    # and case priority measure seriousness/urgency, not physical danger.
    try:
        from analysis.report_rules import is_white_collar as _iwc
        if _iwc(crime_info.get("all_crimes", [])) and not str(watchlist.get("status", "")).startswith("TERRORISM"):
            public = ("LOW — non-violent financial offence; absconding/fugitive name-match is a flight risk, "
                      "not a physical-safety threat" if str(watchlist.get("status", "")).startswith("FUGITIVE")
                      else "LOW — non-violent financial offence; no physical-safety evidence on file")
    except Exception:
        pass
    # ─── END CASE PRIORITY OVERRIDE ──────────────────────────────────────

    # Escalation: only assessed when there is behavioural / threat evidence.
    # Priority, a keyword-driven risk number or narrative length is not that.
    _esc_evidence = []
    for ev in (text_evidence or []):
        if isinstance(ev, dict) and ev.get("type") in ("THREAT Detected", "WEAPON Detected"):
            _esc_evidence.append(ev["type"].replace(" Detected", "").lower() + " language")
    if any(k in c for c in crime_info.get("all_crimes", []) for k in ("Weapon", "Assault", "Murder", "Homicide", "Kidnap", "Threat", "Extortion")):
        _esc_evidence.append("violent-crime classification")
    if voice_evidence.get("status") == "Evidence analyzed":
        _esc_evidence.append("voice stress analysis")
    if str(watchlist.get("status", "")).startswith(("FUGITIVE", "TERRORISM")):
        _esc_evidence.append("fugitive/terror dataset status (name match)")
    if _esc_evidence:
        esc_factors = [risk * 0.3, deception * 0.25, fraud_indicators["mo_match"] * 0.2,
                       (100 if watchlist.get("fbi_watchlist", "NO") != "NO" else 0) * 0.15,
                       len(fraud_indicators.get("behavioral_flags", [])) * 5]
        esc = round(min(95.0, sum(esc_factors)), 1)
        basis["escalation"] = "Heuristic over: " + ", ".join(sorted(set(_esc_evidence))) + " (not a validated forecast)"
        esc_display = f"{esc:.1f}% (heuristic)"
    else:
        esc = None
        basis["escalation"] = "No threat, weapon, violence, voice or fugitive evidence: escalation cannot be estimated"
        esc_display = _NA

    return {
        "physical": physical,
        "financial": financial,
        "cyber": cyber,
        "public_safety": public,
        "escalation_prob": esc,
        "escalation_display": esc_display,
        "basis": basis,
        "escalation_factors": [
            f"Base risk score: {risk:.1f}% (heuristic)",
            f"Deception score: {deception:.1f}%",
            f"Pattern match: {fraud_indicators['mo_match']:.1f}%",
            f"Watchlist status: {watchlist.get('fbi_watchlist', 'N/A')}",
            f"Behavioral flags: {len(fraud_indicators.get('behavioral_flags', []))}",
            f"Case priority: {case_priority}",
        ],
    }


def _generate_actions_from_evidence(crime_info, fraud_indicators, watchlist, threat, risk, deception, evidence_list, case_priority="Medium"):
    actions = []
    evidence_based = []

    if watchlist.get("status", "").startswith("DECEASED"):
        actions.append("CRITICAL: Subject is DECEASED. This analysis is for legacy/historical case review ONLY.")
        evidence_based.append("Status confirmed from background database")

    _heur = bool(crime_info.get("_risk_heuristic"))
    if risk > 75 and _heur:
        actions.append("PRIORITY: heuristic risk estimate is High (risk model not used). Expand verification; "
                       "no surveillance/warrant step is supported by the evidence on file.")
        evidence_based.append(f"Heuristic risk band: High")
    elif risk > 75:
        actions.append("IMMEDIATE: Risk score exceeds 75%. Recommend emergency surveillance warrant.")
        evidence_based.append(f"Composite risk: {risk:.1f}%")
    elif risk > 50:
        actions.append("PRIORITY: Elevated risk detected. Expand background investigation immediately.")
        evidence_based.append("Heuristic risk band: Medium/High" if _heur else f"Composite risk: {risk:.1f}%")

    if fraud_indicators["document_forgery"] > 60:
        actions.append("FORENSIC: Document forgery indicators strong. Submit to document examiner for forensic analysis.")
        evidence_based.append(f"Document forgery score: {fraud_indicators['document_forgery']:.1f}%")

    if fraud_indicators["identity_fraud"] > 60:
        actions.append(
            "IDENTITY: Multiple identity inconsistencies. Cross-check with Aadhaar/UIDAI, passport, and voter ID records."
            if crime_info.get("is_indian_jurisdiction")
            else "IDENTITY: Multiple identity inconsistencies. Cross-check with DMV, SSA, and passport records."
        )
        evidence_based.append(f"Identity fraud score: {fraud_indicators['identity_fraud']:.1f}%")

    if fraud_indicators["financial_anomaly"] > 60:
        actions.append(
            "FINANCIAL: Suspicious financial patterns. Report to FIU-IND (STR) and seek freezing/attachment through ED/court where warranted."
            if crime_info.get("is_indian_jurisdiction") else
            "FINANCIAL: Suspicious financial patterns. File FinCEN SAR and freeze suspicious accounts.")
        evidence_based.append(f"Financial anomaly score: {fraud_indicators['financial_anomaly']:.1f}%")
    elif watchlist.get("fintrac_sar") == "YES":
        actions.append("FINANCIAL: Prior SARs on file. Review latest transaction patterns immediately.")
        evidence_based.append("Existing FinCEN SAR records")

    if crime_info["severity"] in ["High", "Critical"]:
        # BUG FIX (2026-08-25): "federal task force" is U.S.-specific
        # terminology, shown even for cases with a clearly Indian location
        # — jurisdiction-aware wording instead.
        _coord_body = crime_info.get("law_action") or (
            "Consider coordination with State Police / Crime Branch and, for cross-state cases, CBI/NIA."
            if crime_info.get("is_indian_jurisdiction")
            else "Coordinate with the competent law-enforcement authority of the jurisdiction."
        )
        actions.append(f"JURISDICTION: {crime_info['severity']} severity crime. {_coord_body}")
        evidence_based.append(f"Crimes detected: {', '.join(crime_info['all_crimes'][:2])}")

    # p23: a POSSIBLE (spelling-variant) dataset hit only ever produces an
    # identity-verification action — never sanctions/prosecution/Interpol steps.
    _possible = str(watchlist.get("match_confidence", "")).upper().startswith("POSSIBLE")
    if _possible:
        _src = sorted({m.get("dataset", "?") for m in (watchlist.get("possible_variant_matches") or [])})
        actions.append("VERIFY IDENTITY: the suspect name is a POSSIBLE spelling-variant match to dataset record(s) "
                       f"({', '.join(_src)}). Resolve identity (photo, date of birth, parentage, PAN/passport) before "
                       "relying on any wanted-list, debarment or PEP entry.")
        evidence_based.append("Spelling-variant name match only (identity confidence 0%)")
        watchlist = {k: v for k, v in watchlist.items()
                     if k not in ("sanctions", "interpol", "charges", "enforcement_actions", "extradition_status",
                                  "outstanding_debt", "fbi_watchlist")}
    if watchlist.get("fbi_watchlist", "NO") != "NO" and not crime_info.get("is_indian_jurisdiction"):
        actions.append(f"WATCHLIST: {watchlist['fbi_watchlist']}. Coordinate with FBI liaison officer.")
        evidence_based.append("Federal watchlist match")

    if watchlist.get("interpol", "NO") != "NO" and "YES" not in str(watchlist.get("interpol", "")):  # p43: no duplicate INTERPOL action
        actions.append("INTERPOL: Active notice detected. Coordinate with INTERPOL National Central Bureau.")
        evidence_based.append("International notice")

    if watchlist.get("sanctions", "NO") != "NO":
        try:
            from analysis.report_rules import sanction_kind as _sk, sanction_list_name as _sln
            _kind = _sk(watchlist.get("sanctions"))
        except Exception:
            _kind, _sln = "unknown", (lambda v: str(v))
        if _kind == "interpol":
            pass  # p41: an INTERPOL notice is handled by the INTERPOL action, not as a sanctions designation
        elif _kind == "regulatory":
            actions.append(f"REGULATORY DEBARMENT: name matches {_sln(watchlist.get('sanctions'))}. Obtain the SEBI/exchange "
                           "order (date, entity, period) and confirm it refers to this person; this is a market/regulatory "
                           "action, not an international sanctions designation.")
            evidence_based.append("Regulatory debarment-list name match")
        else:
            actions.append("SANCTIONS: Subject matches an international sanctions list. Coordinate with compliance/national security units and verify designation reference.")
            evidence_based.append("Sanctions-list match")

    for ev in evidence_list:
        if isinstance(ev, dict) and ev.get("type") == "WEAPON Detected":
            actions.append("WEAPONS: Weapon references in evidence. Consider firearm registry check and ballistic evidence collection.")
            evidence_based.append(f"Weapons: {', '.join(ev.get('values', [])[:3])}")
        if isinstance(ev, dict) and ev.get("type") == "THREAT Detected":
            actions.append("THREAT: Threat language detected. Evaluate for protective order or witness protection needs.")
            evidence_based.append(f"Threats: {', '.join(ev.get('values', [])[:3])}")

    # Fugitive / extradition-specific actions
    if watchlist.get("extradition_status") and "ORDERED" in watchlist.get("extradition_status", ""):
        actions.append("EXTRADITION: Subject is fugitive with ordered extradition. Coordinate with Ministry of External Affairs (MEA) and host country embassy immediately.")
        evidence_based.append(f"Extradition status: {watchlist.get('extradition_status', 'N/A')}")

    if watchlist.get("interpol") and "YES" in watchlist.get("interpol", "NO"):
        actions.append("INTERPOL: Active Red Corner Notice. Coordinate with INTERPOL NCB (New Delhi) and Interpol General Secretariat (Lyon).")
        evidence_based.append("Interpol RCN confirmed")

    if watchlist.get("outstanding_debt") and "N/A" not in watchlist.get("outstanding_debt", ""):
        actions.append(f"DEBT RECOVERY: Outstanding {watchlist.get('outstanding_debt', '')}. Coordinate with DRT and consortium banks for asset tracing and recovery.")
        evidence_based.append(f"Debt: {watchlist.get('outstanding_debt', 'N/A')}")

    if watchlist.get("charges") and len(watchlist.get("charges", [])) > 0 and watchlist.get("charges", ["N/A"])[0] != "N/A":
        actions.append(f"PROSECUTION: a dataset record (name-match, identity unverified) lists {len(watchlist.get('charges', []))} charge(s). Obtain the actual FIR / charge sheet and confirm it refers to this person before relying on it.")
        evidence_based.append(f"Charges: {', '.join(watchlist.get('charges', [])[:2])}")

    if watchlist.get("enforcement_actions") and len(watchlist.get("enforcement_actions", [])) > 0 and watchlist.get("enforcement_actions", ["N/A"])[0] != "N/A":
        actions.append(f"ENFORCEMENT: {len(watchlist.get('enforcement_actions', []))} enforcement actions ongoing. Monitor ED/CBI/SFIO progress and ensure no double jeopardy conflicts.")
        evidence_based.append(f"Actions: {watchlist.get('enforcement_actions', ['N/A'])[0]}")

    # ─── CYBERCRIME ACTIONS ──────────────────────────────────────────────
    if crime_info.get("all_crimes") and any(
        c in str(crime_info.get("all_crimes", []))
        for c in ["Computer Hacking", "Ransomware Attack", "Data Breach", "Cybercrime"]
    ):
        actions.append("CYBER: Cybercrime indicators detected. Immediately engage Cyber Cell / CFSL (Cyber Forensic Science Lab).")
        evidence_based.append(
            f"Cybercrime: {', '.join([c for c in crime_info.get('all_crimes', []) if 'Cyber' in c or 'Hacking' in c or 'Ransom' in c])}"
        )

    if fraud_indicators.get("digital_anomaly", 0) > 60:
        actions.append("DIGITAL FORENSICS: High digital anomaly score. Preserve all digital evidence using write-blockers and capture network logs.")
        evidence_based.append(f"Digital anomaly score: {fraud_indicators.get('digital_anomaly', 0):.1f}%")

    for ev in evidence_list:
        if isinstance(ev, dict) and ev.get("type") == "EMAIL Detected" and ev.get("count", 0) > 5:
            actions.append("EMAIL ANALYSIS: Multiple email addresses found. Request email provider records and analyze communication patterns.")
            evidence_based.append(f"{ev.get('count', 0)} email addresses identified")
    # ─── END CYBERCRIME ACTIONS ────────────────────────────────────────

    if not actions:
        # This fallback previously fired whenever none of the specific
        # watchlist/PEP/sanctions/cybercrime triggers above matched — but
        # it never checked the case's own priority or crime severity, so a
        # case explicitly marked High/Critical priority (or with a
        # High/Critical crime-severity finding) could still get told
        # "ROUTINE: No immediate threat" right next to a "HIGH PRIORITY —
        # CRITICAL CASE" verdict elsewhere in the same report. Both derive
        # from the same underlying signals, so they must agree.
        if case_priority in ("High", "Critical") or crime_info.get("severity") in ("High", "Critical") or risk > 60:
            actions.append(
                f"ELEVATED: Case priority is {case_priority} "
                f"({'Crime Classification Severity: ' + crime_info.get('severity') if crime_info.get('severity') in ('High','Critical') else ('heuristic risk estimate' if _heur else f'Operational Risk Score: {risk:.1f}%')}) "
                f"— no specific watchlist/cyber/financial trigger fired, but the case's own priority/severity "
                f"still warrants active investigation, not routine monitoring."
            )
            evidence_based.append(f"Case priority: {case_priority}; Crime Classification Severity: {crime_info.get('severity', 'N/A')}")
        else:
            actions.append("ROUTINE: No immediate threat indicators. Continue standard monitoring and evidence collection.")
            evidence_based.append("Clean evidence profile")

    actions.append("RE-EVALUATE: Schedule evidence review in 30 days or immediately upon new evidence submission.")
    evidence_based.append("Standard protocol")

    if risk > 60 and not _heur:
        actions.append("ESCALATION THRESHOLD: If risk exceeds 75% or new violent crime evidence emerges, immediately notify supervising agent and consider emergency protocols.")
        evidence_based.append(f"Current risk: {risk:.1f}% (threshold: 75%)")

    return actions, evidence_based


def _looks_like_a_name(fragment: str) -> bool:
    """Filters out generic role/description phrases from being treated as
    a candidate associate NAME to search against the dataset engine.

    BUG FIX (P0 — reviewer feedback, same failure repeated across two
    case reviews): `_analyze_network_evidence` used to split the
    "Network/Associates" free-text field on commas ONLY and search every
    resulting fragment as if it were a person/company name — including
    purely descriptive phrases like "Unauthorised Software / Application
    Infrastructure" that an investigator typed to describe a MECHANISM,
    not a named associate. That phrase happened to word-overlap with a
    real, unrelated company ("Datasoft Application Software (India) Ltd")
    and got surfaced as a "PARTIAL" network match — a false association
    between the case and a real company built entirely on generic
    vocabulary overlap. A real associate name is short and doesn't read
    like a role/mechanism description. Also splits on "/" and ";" now,
    since a single comma-free fragment containing "/" (as in the example
    above) previously reached this function as one long multi-word string.
    """
    f = (fragment or "").strip()
    if not f:
        return False
    words = f.replace("/", " ").replace(";", " ").split()
    if len(words) > 4:
        return False
    _DESCRIPTIVE_TERMS = {
        "unauthorised", "unauthorized", "infrastructure", "application",
        "software", "revenue", "concealment", "manipulation", "receipt",
        "toll", "collection", "system", "systems", "platform", "process",
        "mechanism", "scheme", "arrangement", "account", "accounts",
        "transaction", "transactions", "activity", "activities",
    }
    lower_words = {w.strip("()/,.").lower() for w in words}
    if lower_words & _DESCRIPTIVE_TERMS:
        return False
    return True


def _analyze_financial_evidence(financial_ids, entities):
    """
    Flags suspicious financial patterns from provided IDs.
    Returns: financial_risk_score, financial_flags
    """
    if not financial_ids or not financial_ids.strip():
        return 0.0, []

    flags = []
    risk = 0.0
    ids = [fid.strip() for fid in financial_ids.split(",") if fid.strip()]

    for fid in ids:
        fid_lower = fid.lower()
        # Crypto wallet patterns
        if len(fid) >= 26 and (fid.startswith("1") or fid.startswith("3") or fid.startswith("bc1")):
            flags.append(f"Bitcoin wallet detected: {fid[:12]}...")
            risk += 12
        elif len(fid) >= 40 and fid.startswith("0x"):
            flags.append(f"Ethereum wallet detected: {fid[:12]}...")
            risk += 12
        elif "t1" in fid_lower or "zs" in fid_lower:
            flags.append(f"Privacy coin address detected: {fid[:12]}...")
            risk += 18
        # Offshore / shell indicators
        elif any(k in fid_lower for k in ["offshore", "shell", "bvi", "cayman", "delaware"]):
            flags.append(f"Offshore/shell entity reference: {fid[:30]}")
            risk += 20
        # High-value account patterns
        elif re.search(r'\\d{10,}', fid):
            flags.append(f"Numeric account identifier: {fid[:20]}...")
            risk += 8

    # Entity-based financial boost
    if entities:
        org_count = len(entities.get("ORG", []))
        money_count = len(entities.get("MONEY", []))
        if org_count > 0:
            flags.append(f"{org_count} organization(s) referenced in text evidence")
            risk += org_count * 5
        if money_count > 0:
            flags.append(f"{money_count} financial reference(s) in text evidence")
            risk += money_count * 10

    return round(min(risk, 95.0), 1), flags[:6]


def _analyze_vehicle_evidence(vehicle_info, suspect_name):
    """
    Vehicle and license plate analysis.
    Returns: vehicle_risk_score, vehicle_flags
    """
    if not vehicle_info or not vehicle_info.strip():
        return 0.0, []

    flags = []
    risk = 0.0
    vehicles = [v.strip() for v in vehicle_info.split(",") if v.strip()]

    for v in vehicles:
        v_upper = v.upper()
        # Indian plate pattern
        if re.match(r'^[A-Z]{2}\\d{2}[A-Z]{1,2}\\d{4}$', v_upper):
            flags.append(f"Indian vehicle registration: {v_upper}")
            risk += 5
        # Generic plate
        elif re.search(r'[A-Z0-9]{4,}', v_upper):
            flags.append(f"Vehicle/plate reference: {v_upper}")
            risk += 5
        # Vessel/IMO
        elif v_upper.startswith("IMO"):
            flags.append(f"Vessel IMO number: {v_upper}")
            risk += 10
        # Aircraft
        elif v_upper.startswith("N") and len(v_upper) >= 3:
            flags.append(f"Aircraft registration: {v_upper}")
            risk += 8

    return round(min(risk, 95.0), 1), flags[:5]


# ============================================================================
# ADDED to this module later: the three functions below need `ds_eng` (the
# module-level DatasetSearchEngine instance gradio_app.py creates at
# startup). Since this module doesn't hold that instance, `ds_eng` is
# passed in explicitly as a parameter instead — gradio_app.py's call sites
# (inside run_analysis) already have `ds_eng` in scope and were updated to
# pass it. This is the one real signature change in this whole refactor;
# everything else was a pure move with zero behavior change.
# ============================================================================


def _lookup_suspect_background(ds_eng, suspect_name, entities):
    """
    Looks up a suspect against master_search_index (built by
    sync_datasets_to_mysql.py from ALL synced dataset folders — Interpol,
    NCRB, wanted/fugitives, modus_operandi, hardcore_crime, watchlists,
    sanctions, network_associates, offshore, crypto, cyber_crime, etc.)
    instead of a hardcoded name->record dictionary. Returns the same
    dict shape the rest of the pipeline (crime override, threat
    assessment, PDF report) already expects.

    Every hit is scored for name-match STRENGTH (strong/partial/weak) so a
    coincidental single-word overlap (e.g. "Saeed") isn't reported with the
    same confidence as an exact/near-exact name match — this avoids the
    report claiming e.g. "Interpol: YES" off a weak partial match.
    Only strong (or, failing that, partial) matches drive the watchlist
    flags; weak-only hits are surfaced separately as "for review".
    """
    result = {
        "criminal_history": "NO RECORD FOUND in database",
        "prior_arrests": [],
        "aliases": ["N/A"],
        "known_associates": [],
        "gang_affiliation": "N/A",
        "pep_status": "NO",
        "pep_connections": [],
        "sanctions": "NO",
        "interpol": "NO",
        "fbi_watchlist": "NO",
        "fintrac_sar": "NO",
        "status": "UNKNOWN",
        "known_properties": [],
        "known_vessels": [],
        "extradition_status": "N/A",
        "outstanding_debt": "N/A",
        "charges": ["N/A"],
        "enforcement_actions": [],
        "dataset_matches": {"count": 0, "datasets": {}, "top": []},
        "match_confidence": "NONE",
        "weak_matches_for_review": [],
    }

    name = (suspect_name or "").strip()
    if not name or not ds_eng.ready:
        if entities and entities.get("PERSON"):
            result["entities_found"] = entities["PERSON"]
        return result

    raw_rows = ds_eng.search(name, limit=25)
    # p23 (2026-11-07): supplementary search with Indian transliteration
    # spellings (Maliya -> Mallya, Malya, Mallia ...) so a spelling variant can
    # surface as a POSSIBLE match. Rows are merged and de-duplicated.
    try:
        from analysis.report_rules import name_tokens as _rr_tokens, spelling_variants as _rr_variants
        _toks = _rr_tokens(name)
        if len(_toks) >= 2:
            _vq = " ".join(v for t in _toks for v in _rr_variants(t, limit=8))
            if _vq.strip() and _vq.strip() != " ".join(_toks):
                _seen = {((r.get("entity_name") or ""), (r.get("dataset") or ""), (r.get("data") or "")[:80]) for r in raw_rows}
                for r in ds_eng.search(_vq, limit=25) or []:
                    k = ((r.get("entity_name") or ""), (r.get("dataset") or ""), (r.get("data") or "")[:80])
                    if k not in _seen:
                        _seen.add(k)
                        raw_rows.append(r)
    except Exception:
        pass
    if not raw_rows:
        if entities and entities.get("PERSON"):
            result["entities_found"] = entities["PERSON"]
        return result

    # Fix swapped entity_name/entity_type, then score match strength per row
    strong_rows, partial_rows, weak_rows, variant_rows = [], [], [], []
    try:
        from analysis.report_rules import spelling_variant_match as _rr_svm, RULES as _RR
        _tier_label = (_RR.get("name_matching", {}) or {}).get("tier_label", "POSSIBLE (spelling variant, verify identity)")
    except Exception:
        _rr_svm, _tier_label = None, "POSSIBLE (spelling variant, verify identity)"
    for r in raw_rows:
        fixed_name, fixed_type = _fix_entity_name_type(r.get("entity_name"), r.get("entity_type"))
        r = {**r, "entity_name": fixed_name, "entity_type": fixed_type}
        strength = _name_match_strength(name, fixed_name, data_blob=r.get("data") or "")
        if strength == "weak" and _rr_svm is not None and fixed_name:
            _v = _rr_svm(name, fixed_name)
            if _v:
                strength = "variant"
                r["_variant"] = _v
        r["_match_strength"] = strength
        (strong_rows if strength == "strong" else
         partial_rows if strength == "partial" else
         variant_rows if strength == "variant" else weak_rows).append(r)
    # "watchlist_names" rows carry no record content (a bare name list) — they
    # are kept for display but never drive a flag
    def _content_row(r):
        return (r.get("dataset") or "").lower() != "watchlist_names"

    if variant_rows:
        result["possible_variant_matches"] = [{
            "name": r["entity_name"], "dataset": r.get("dataset") or "?", "type": r.get("entity_type") or "",
            "pairs_text": ", ".join(f"{a}~{b}" for a, b, _ in r["_variant"]["pairs"] if a != b),
            "detail": _target_row_summary(r)[:200],
        } for r in variant_rows[:8]]

    # Only strong matches (or partial, if no strong ones exist) are treated
    # as real hits for the watchlist flags — weak ones are listed separately
    # so they're visible without being reported as confirmed database hits.
    # p23: with neither, spelling-variant rows form a POSSIBLE tier (never CONFIRMED).
    confirmed_rows = strong_rows or partial_rows
    _variant_tier = False
    if not confirmed_rows and variant_rows:
        confirmed_rows = [r for r in variant_rows if _content_row(r)] or variant_rows
        _variant_tier = True
    result["match_confidence"] = ("STRONG" if strong_rows else "PARTIAL" if partial_rows
                                  else _tier_label if variant_rows else "WEAK")
    result["identity_confidence"] = "0% (name/alias string match only; identity not resolved)"

    if weak_rows and (strong_rows or partial_rows):
        # p41: with a strong/partial match, drop weak rows that share only the surname
        try:
            from analysis.report_rules import name_tokens as _nt
            _q = _nt(name)
            _given = set(_q[:-1]) if len(_q) > 1 else set(_q)
            weak_rows = [r for r in weak_rows if _given & set(_nt(r.get("entity_name") or ""))]
        except Exception:
            pass
    if weak_rows:
        result["weak_matches_for_review"] = [
            f"[{r.get('dataset','?')}] {r['entity_name']} (shares a name fragment only — verify manually)"
            for r in weak_rows[:5]
        ]

    summary = ds_eng.summarize(confirmed_rows) if confirmed_rows else {"count": 0, "datasets": {}, "top": []}
    result["dataset_matches"] = summary

    if not confirmed_rows:
        result["criminal_history"] = (
            "NO CONFIRMED RECORD — only weak/coincidental name-fragment matches found"
            if weak_rows else "NO RECORD FOUND in database"
        )
        if entities and entities.get("PERSON"):
            result["entities_found"] = entities["PERSON"]
        return result

    conf_label = ("CONFIRMED NAME MATCH" if strong_rows else
                  f"{_tier_label}: '{name}' ~ '{confirmed_rows[0].get('entity_name')}'" if _variant_tier else
                  "LIKELY (partial name match — verify)")
    result["criminal_history"] = (
        f"{conf_label} — {summary['count']} record(s) across {len(summary['datasets'])} dataset(s). "
        f"This reflects a name/alias string match against the database, NOT a confirmed personal "
        f"identity — independent identity resolution (photo/biometric/document cross-check) is required "
        f"before treating this as a match to this specific individual."
    )

    charges, evidence_datasets, associates, aliases = [], [], [], []

    # BUG FIX (2026-08-20 — Medium): raw dataset "data" text (e.g. dark-web
    # crawl records) occasionally already contains its own [text](url)-
    # style fragment from an earlier ingestion/scrape step. When that gets
    # embedded straight into "[{dataset}] {data}" here, the brackets
    # collide and render as broken markdown, e.g.
    # "http://darkmarket-val5.onion/gems-vendor](http://darkmarket...".
    # Strip/neutralize embedded bracket-paren link syntax before it goes
    # into a report string, rather than trying to fix it after the fact in
    # every place this text later gets displayed.
    def _sanitize_report_text(text):
        text = str(text or "")
        # Collapse "](" sequences (the actual malformed pattern seen) so a
        # stray markdown fragment can't break out of its intended brackets.
        text = text.replace("](", " → ")
        return text

    for r in confirmed_rows:
        ds = (r.get("dataset") or "").lower()
        src = (r.get("source_table") or "").lower()
        data = _sanitize_report_text(r.get("data") or "")
        real_name = r.get("entity_name") or ""
        tag = ("" if r["_match_strength"] == "strong" else
               " [POSSIBLE spelling-variant match — verify identity]" if r["_match_strength"] == "variant"
               else " [partial match — verify]")
        if ds == "watchlist_names":
            continue
        # p23: OpenSanctions-style rows (targets_*) hold PEP lists, Wikidata,
        # debarment lists etc. — only a non-empty "sanctions" field is a
        # sanction/debarment; PEP lists set pep_status. Read the JSON instead of
        # flagging every row of the table as a sanction.
        if ds.startswith("targets_"):
            _j = _json_or_empty(r.get("data"))
            _lists = str(_j.get("dataset") or _j.get("datasets") or "")
            if str(_j.get("sanctions") or "").strip(" ;"):
                result["sanctions"] = f"YES{tag} — listed: {_lists[:120] or ds} (regulatory/sanction list; check the source)"
            if "politically exposed" in _lists.lower() or "wd_peps" in _lists.lower():
                result["pep_status"] = f"YES{tag} — PEP list ({_lists[:80]})"
            if real_name and real_name.lower() != name.lower() and real_name not in aliases:
                aliases.append(real_name)
            continue

        if real_name and real_name.lower() != name.lower() and real_name not in aliases:
            aliases.append(real_name)

        if "interpol" in ds or "interpol" in src:
            result["interpol"] = f"YES{tag} — Interpol-linked record found"
        if "sanction" in ds or "sanction" in src:
            result["sanctions"] = f"YES{tag} — sanctions-list record found"
        if "wanted" in ds or "wanted" in src or "fugitive" in src:
            result["status"] = (f"POSSIBLE WANTED-LIST MATCH (spelling variant){tag}" if r["_match_strength"] == "variant"
                                else f"FUGITIVE/WANTED MATCH{tag} — verify against source record")
            _j = _json_or_empty(r.get("data"))
            charges.append(f"{_j.get('crime')} (dataset {ds}, status {_j.get('status', '?')}, location {_j.get('location', '?')})"
                           if _j.get("crime") else data[:160])
        if "modus_operandi" in ds or "hardcore_crime" in ds or "crime_intelligence" in ds:
            evidence_datasets.append(f"[{ds or src}]{tag} {data[:160]}")
        if "network_associates" in ds or "network_associates" in src:
            associates.append(data[:160])
        if "ncrb" in ds or "ncrb" in src:
            evidence_datasets.append(f"[NCRB context] {data[:160]}")

        # ─── ADD THESE DATA SOURCES ──────────────────────────────────────
        if "cyber" in ds or "cyber" in src or "dark_web" in ds:
            result["cyber_intel"] = f"YES{tag} — Cybercrime intelligence found"
            evidence_datasets.append(f"[Cyber Intelligence]{tag} {data[:160]}")

        if "financial_intel" in ds or "banking" in ds or "fincen" in ds:
            result["financial_intel"] = f"YES{tag} — Financial intelligence found"
            evidence_datasets.append(f"[Financial Intel]{tag} {data[:160]}")

        if "terrorism" in ds or "terror" in ds or "counterterror" in ds:
            result["terrorism_watch"] = f"YES{tag} — Terrorism watchlist hit"
            result["status"] = f"TERRORISM WATCH{tag} — verify against source record"
            charges.append(data[:160])
        # ─── END NEW DATA SOURCES ────────────────────────────────────────

    if _variant_tier:
        result["criminal_history"] += (
            " NAMESAKE CAUTION: this is a spelling-variant match on name only. Several people can share "
            "this name; confirm with photo, date of birth, parentage or ID before treating it as the same person.")
    if charges:
        result["charges"] = charges[:5]
    if evidence_datasets:
        result["enforcement_actions"] = evidence_datasets[:5]
    if associates:
        result["known_associates"] = associates[:5]
    if aliases:
        result["aliases"] = aliases[:5]
        # SAFEGUARD: if the "aliases" collected across these records are
        # not simple spelling/transliteration variants of each other but
        # genuinely distinct full names (e.g. "Subhash Chandra Baheria"
        # vs "Alluri Subhash Chandra Bose"), these records likely belong
        # to MULTIPLE different individuals who happen to share a name
        # fragment — not one person's aliases. Flag it plainly rather
        # than let the report imply a single confirmed criminal history.
        _distinct_people = [name] + aliases
        _pairs_diverge = False
        for i in range(len(_distinct_people)):
            for j in range(i + 1, len(_distinct_people)):
                if _name_match_strength(_distinct_people[i], _distinct_people[j]) != "strong" and not (
                        _rr_svm is not None and _rr_svm(_distinct_people[i], _distinct_people[j])):
                    _pairs_diverge = True
                    break
            if _pairs_diverge:
                break
        if _pairs_diverge:
            result["criminal_history"] += (
                " ⚠ CAUTION: the name variants found across these records differ enough "
                "that they may belong to DIFFERENT individuals sharing a name fragment, "
                "not aliases of the same person — verify each record's identity separately "
                "before relying on this as one person's criminal history."
            )

    if entities and entities.get("PERSON"):
        result["entities_found"] = entities["PERSON"]
        known_lower = [a.lower() for a in result.get("known_associates", [])]
        entity_matches = [e for e in entities["PERSON"] if any(e.lower() in k or k in e.lower() for k in known_lower)]
        if entity_matches:
            result["associate_matches"] = entity_matches
    return result


def _json_or_empty(data):
    try:
        import json as _json
        v = _json.loads(data) if isinstance(data, str) else (data or {})
        return v if isinstance(v, dict) else {}
    except Exception:
        return {}


def _target_row_summary(r):
    j = _json_or_empty(r.get("data"))
    if not j:
        return str(r.get("data") or "")[:200]
    keys = [k for k in ("crime", "status", "location", "dataset", "datasets", "sanctions", "countries") if j.get(k)]
    return "; ".join(f"{k}={str(j[k])[:90]}" for k in keys) or str(r.get("data") or "")[:200]


def _lookup_unidentified_offender(ds_eng, modus, physical_desc, location):
    """
    For cases where the suspect's identity is NOT known ('Agyat Apradhi' /
    unidentified offender) — there is no name to search on, so instead of
    _lookup_suspect_background's name lookup, this matches the case's
    Modus Operandi + physical description + location against
    master_search_index rows tagged wanted/fugitive/modus_operandi/
    hardcore_crime, to surface POSSIBLE investigative leads.

    This NEVER claims identification. It only returns candidate records
    for a human investigator to independently verify — consistent with
    the "AI suggests, human decides" principle. Results are explicitly
    labeled as leads, not matches, and always include the source dataset
    so provenance is traceable.
    """
    result = {
        "query_used": "", "lead_count": 0, "datasets_searched": {},
        "possible_leads": [], "note": "",
    }

    query_parts = [p.strip() for p in [modus, physical_desc, location] if p and p.strip()]
    query_text = " ".join(query_parts).strip()
    result["query_used"] = query_text[:200]

    if not query_text or not ds_eng.ready:
        result["note"] = "No MO / description text provided, or dataset search unavailable."
        return result

    raw_rows = ds_eng.search(query_text, limit=30)
    if not raw_rows:
        result["note"] = "No candidate records found for this MO/description in wanted, fugitive, or crime-pattern datasets."
        return result

    RELEVANT_DATASET_HINTS = ("wanted", "fugitive", "modus_operandi", "hardcore_crime", "crime_intelligence")
    leads = []
    for r in raw_rows:
        ds = (r.get("dataset") or "").lower()
        src = (r.get("source_table") or "").lower()
        if not any(hint in ds or hint in src for hint in RELEVANT_DATASET_HINTS):
            continue
        fixed_name, fixed_type = _fix_entity_name_type(r.get("entity_name"), r.get("entity_type"))
        leads.append({
            "candidate_name_or_alias": fixed_name or "Unnamed / Alias only",
            "entity_type": fixed_type or "N/A",
            "dataset": r.get("dataset") or r.get("source_table") or "unknown",
            "detail": (r.get("data") or "")[:220],
            "relevance": r.get("relevance", 0),
        })

    leads.sort(key=lambda x: x.get("relevance", 0), reverse=True)
    result["possible_leads"] = leads[:8]
    result["lead_count"] = len(leads)
    ds_counts = {}
    for l in leads:
        ds_counts[l["dataset"]] = ds_counts.get(l["dataset"], 0) + 1
    result["datasets_searched"] = ds_counts

    if not leads:
        result["note"] = "Records matched the query but none fell in wanted/fugitive/MO-pattern datasets — no relevant leads."
    else:
        result["note"] = (
            f"{len(leads)} possible lead(s) surfaced by MO/description similarity. "
            "These are NOT confirmed identifications — verify independently before any action."
        )
    return result


def _analyze_network_evidence(ds_eng, network_text, suspect_name):
    """
    Searches known associates in master_search_index.
    Returns: network_risk_score, associate_matches, network_summary
    """
    if not network_text or not network_text.strip() or not ds_eng.ready:
        return 0.0, [], "No network data provided"

    # BUG FIX: split on "/" and ";" in addition to "," — a fragment like
    # "Unauthorised Software / Application Infrastructure" with no comma
    # used to arrive here as ONE long fragment; splitting more thoroughly
    # lets _looks_like_a_name's word-count check work as intended either
    # way, and also stops a legitimate short name from being silently
    # merged with a trailing descriptive clause.
    try:  # p38: newline / 'Name - role' / 'A and B' aware
        from analysis.report_rules import parse_network_names as _pnn
        associates = [a["name"] for a in _pnn(network_text)]
    except Exception:
        associates = [a.strip() for a in re.split(r"[,;/\n]", network_text) if a.strip()]
    if not associates:
        return 0.0, [], "No valid associate names"

    all_matches = []
    high_risk_count = 0
    _skipped_descriptive = []

    for assoc in associates:
        if not _looks_like_a_name(assoc):
            # Not a plausible name — a role/mechanism description typed
            # into this field. Skip the dataset search entirely rather
            # than risk a coincidental word-overlap match against an
            # unrelated real company/person.
            _skipped_descriptive.append(assoc)
            continue
        rows = ds_eng.search(assoc, limit=5)
        for r in rows:
            fixed_name, fixed_type = _fix_entity_name_type(
                r.get("entity_name"), r.get("entity_type")
            )
            strength = _name_match_strength(assoc, fixed_name, data_blob=r.get("data") or "")
            if strength in ("strong", "partial"):
                match = {
                    "query": assoc,
                    "name": fixed_name,
                    "type": fixed_type,
                    "dataset": r.get("dataset", "unknown"),
                    "data": (r.get("data") or "")[:200],
                    "strength": strength,
                }
                all_matches.append(match)
                ds_lower = match["dataset"].lower()
                if any(k in ds_lower for k in ["interpol", "sanction", "wanted", "fugitive", "hardcore"]):
                    high_risk_count += 1

    # Network risk: more high-risk matches = higher score
    base_risk = min(len(associates) * 5, 30)
    match_risk = min(high_risk_count * 15, 50)
    network_risk = min(base_risk + match_risk, 95.0)

    summary = f"{len(all_matches)} match(es) across {len(set(m['dataset'] for m in all_matches))} dataset(s) from {len(associates)} associate(s)"
    if _skipped_descriptive:
        summary += f" — {len(_skipped_descriptive)} entry/entries skipped as descriptive text, not names ({', '.join(_skipped_descriptive[:2])})"
    return round(network_risk, 1), all_matches, summary
