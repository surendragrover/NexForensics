"""
Gradio tab: Deep OSINT Agent (DOA).

  with gr.Tab("🔎 Deep OSINT (DOA)"):
      build_doa_tab()

One click runs the pipeline AND writes the dossier PDF; the browser download starts by itself.
Pasted documents: blocks separated by a line '---'. Optional header lines at the top of a block:
  URL: ...   TITLE: ...   TIER: PRIMARY_OFFICIAL|HIGH|MEDIUM|LOW|SELF_REPORTED
  KIND: RECORD|REPORT|SELF   PUBLISHED: YYYY-MM-DD
Identity anchors for pasted text are detected only from the text itself (DOB, city, organisation
present in the document), never assumed.
"""
from __future__ import annotations
import hashlib, os, re, traceback
from datetime import datetime, timezone
from typing import List, Tuple

from journalist_research.runtime.doa_pipeline import DOAPipeline, InputDocument, SubjectProfile

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ART = os.path.join(APP, "runtime", "artifacts", "doa_ui")
MANUAL_CHECK = "Documents supplied by investigator"
TIERS = {"PRIMARY_OFFICIAL", "HIGH", "MEDIUM", "LOW", "SELF_REPORTED"}
OFFICIAL = re.compile(r"^https?://([a-z0-9-]+\.)*(gov\.in|nic\.in|gov\.uk|gov|europa\.eu|un\.org|worldbank\.org|"
                      r"sebi\.gov\.in|mca\.gov\.in|ecourts\.gov\.in|sci\.gov\.in|rbi\.org\.in)(/|$)", re.I)
HEADER = re.compile(r"^(URL|TITLE|TIER|KIND|PUBLISHED)\s*:\s*(.+)$", re.I)
MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september",
          "october", "november", "december"]


def _split_list(s: str) -> List[str]:
    return [x.strip() for x in re.split(r"[,;\n]", s or "") if x.strip()]


def _dob_forms(dob: str) -> List[str]:
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", (dob or "").strip())
    if not m:
        return []
    y, mo, d = m.groups()
    mon = MONTHS[int(mo) - 1]
    return [f"{y}-{mo}-{d}", f"{d}/{mo}/{y}", f"{d}-{mo}-{y}", f"{d}.{mo}.{y}",
            f"{int(d)} {mon} {y}", f"{int(d)} {mon[:3]} {y}", f"{mon} {int(d)}, {y}", f"{mon[:3]} {int(d)}, {y}"]


def detect_mention(text: str, p: SubjectProfile) -> dict:
    low = (text or "").lower()
    names = [p.name] + list(p.aliases)
    name = next((n for n in names if n and re.search(r"(?<!\w)" + r"\s+".join(map(re.escape, n.lower().split())) + r"(?!\w)", low)), None)
    m = {"name": name or ""}
    if p.dob and any(f.lower() in low for f in _dob_forms(p.dob)):
        m["dob"] = p.dob
    elif p.dob:
        # a different stated date of birth is a conflicting anchor (namesake guard), even in pasted text
        mm = re.search(r"(?:\bborn(?:\s+on)?|\bd\.?o\.?b\.?|date\s+of\s+birth)[:\s]+(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})", low)
        mi = re.search(r"(?:\bborn(?:\s+on)?|\bd\.?o\.?b\.?|date\s+of\s+birth)[:\s]+(\d{4})-(\d{2})-(\d{2})", low)
        if mm:
            m["dob"] = f"{mm.group(3)}-{int(mm.group(2)):02d}-{int(mm.group(1)):02d}"
        elif mi:
            m["dob"] = f"{mi.group(1)}-{mi.group(2)}-{mi.group(3)}"
    if p.city and re.search(r"(?<!\w)" + re.escape(p.city.lower()) + r"(?!\w)", low):
        m["city"] = p.city
    orgs = [o for o in p.organizations if o and o.lower() in low]
    if orgs:
        m["organizations"] = orgs
    m["anchors_from_text"] = True
    return m


def parse_documents(raw: str, profile: SubjectProfile) -> List[InputDocument]:
    docs = []
    blocks = [b.strip() for b in re.split(r"(?m)^\s*-{3,}\s*$", raw or "") if b.strip()]
    for i, b in enumerate(blocks, 1):
        meta, lines = {}, b.splitlines()
        while lines and HEADER.match(lines[0].strip()):
            k, v = HEADER.match(lines[0].strip()).groups(); meta[k.upper()] = v.strip(); lines = lines[1:]
        text = "\n".join(lines).strip()
        if not text:
            continue
        tier = meta.get("TIER", "MEDIUM").upper()
        tier = tier if tier in TIERS else "MEDIUM"
        claimed = tier
        url0 = meta.get("URL", "")
        # A pasted text cannot prove it is an official record: PRIMARY_OFFICIAL is accepted only for a URL
        # on an official domain; otherwise it is capped at HIGH (the claim is kept for the reviewer).
        if tier == "PRIMARY_OFFICIAL" and not OFFICIAL.search(url0):
            tier = "HIGH"
        kind = meta.get("KIND", "REPORT").upper()
        kind = kind if kind in ("RECORD", "REPORT", "SELF") else "REPORT"
        h = hashlib.sha256(text.encode()).hexdigest()
        url = meta.get("URL", f"manual://doc-{i}")
        mention = {**detect_mention(text, profile), "tier_claimed": claimed, "investigator_supplied": True}
        if "KIND" not in meta:
            from journalist_research.evidence.narrative_split import split_narrative, mixed
            cl = split_narrative(text)
            if mixed(cl):
                # one pasted narrative mixing what the subject says with what a record shows:
                # split it so the two sides can be compared (each clause is a separate, non-independent source)
                groups = {"SELF": [c["text"] for c in cl if c["kind"] == "SELF"],
                          "REPORT": [c["text"] for c in cl if c["kind"] == "REPORT"]}
                subs = [("SELF", " ".join(groups["SELF"]), tier)] if groups["SELF"] else []
                subs += [("RECORD", c["text"], "MEDIUM" if tier in ("PRIMARY_OFFICIAL", "HIGH") else tier)
                         for c in cl if c["kind"] == "RECORD"]
                subs += [("REPORT", " ".join(groups["REPORT"]), tier)] if groups["REPORT"] else []
                for j, (k, t, tr) in enumerate(subs, 1):
                    hh = hashlib.sha256(t.encode()).hexdigest()
                    ttl = {"SELF": "Subject's statement (from investigator narrative)",
                           "RECORD": "Record as summarised by investigator - verify the original",
                           "REPORT": "Investigator narrative (other)"}[k]
                    docs.append(InputDocument(document_id=f"manual-{i}.{j}-{hh[:8]}", source_id=f"manual-{hh[:12]}",
                                              url=f"manual://doc-{i}.{j}", title=ttl, text=t, tier=tr,
                                              publisher="manual", source_kind=k, lineage_id=f"manual:{hh[:16]}",
                                              published_at=meta.get("PUBLISHED"), checklist_item=MANUAL_CHECK,
                                              mention=dict(mention)))
                continue
        docs.append(InputDocument(document_id=f"manual-{i}-{h[:8]}", source_id=f"manual-{h[:12]}", url=url,
                                  title=meta.get("TITLE", f"Investigator document {i}"), text=text, tier=tier,
                                  publisher=re.sub(r"^https?://([^/]+).*", r"\1", url), source_kind=kind,
                                  lineage_id=f"manual:{url if not url.startswith('manual://') else h[:16]}",
                                  published_at=meta.get("PUBLISHED"), checklist_item=MANUAL_CHECK,
                                  mention=mention))
    return docs


def gather(profile: SubjectProfile, docs_raw: str, use_local: bool, use_sec: bool, use_dark: bool) -> Tuple[list, list]:
    docs, notes = parse_documents(docs_raw, profile), []
    if use_local:
        try:
            from journalist_research.sources.collect import collect
            docs += collect(profile, live=use_sec)
        except Exception as e:  # noqa: BLE001
            notes.append(f"Local sources unavailable: {type(e).__name__}: {e}")
    if use_dark:
        try:
            from journalist_research.darkweb_research.collect import ransomware_documents, onion_documents
            docs += ransomware_documents(profile) + onion_documents(profile)
        except Exception as e:  # noqa: BLE001
            notes.append(f"Dark-web sources unavailable: {type(e).__name__}: {e}")
    return docs, notes


def run_doa(name, aliases, dob, city, orgs, question, docs_raw, use_local, use_sec, use_dark):
    import gradio as gr
    from journalist_research.report.doa_pdf import render_doa_pdf
    name = (name or "").strip()
    if not name:
        return ("**Subject name is required.**", None, None, None, gr.update(value=None, visible=False))
    if dob and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", dob.strip()):
        return ("**Date of birth must be YYYY-MM-DD (or leave it empty).**", None, None, None,
                gr.update(value=None, visible=False))
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    sid = "SUBJ-" + hashlib.sha256(name.lower().encode()).hexdigest()[:10]
    profile = SubjectProfile(subject_id=sid, name=name, aliases=_split_list(aliases), dob=(dob or "").strip() or None,
                             city=(city or "").strip() or None, organizations=_split_list(orgs))
    question = (question or "").strip() or f"What can be verified about {name}?"
    try:
        docs, notes = gather(profile, docs_raw, use_local, use_sec, use_dark)
        inv = f"DOA-{stamp}-{sid[-6:]}"
        r = DOAPipeline(inv, question, profile, docs, artifact_root=ART).run()
        pdf = render_doa_pdf(r, {"name": name, "aliases": profile.aliases, "dob": profile.dob, "city": profile.city,
                                 "organizations": profile.organizations}, os.path.join(ART, inv, f"{inv}.pdf"))
    except Exception as e:  # noqa: BLE001
        return (f"**DOA run failed:** `{type(e).__name__}: {e}`\n\n```\n{traceback.format_exc()[-1500:]}\n```",
                None, None, None, gr.update(value=None, visible=False))

    try:
        from journalist_research.jobs.audit_chain import append as _audit
        if os.environ.get("DOA_AUDIT") == "off":      # offline tests only
            raise RuntimeError("audit disabled by DOA_AUDIT=off")
        _audit("DOA_DOSSIER", r["investigation_id"], r["sha256"],
               {"pdf_sha256": pdf["pdf_sha256"], "documents": len(docs), "pipeline": r.get("pipeline_version")})
    except Exception as e:  # noqa: BLE001
        notes.append(f"Audit chain entry not written: {type(e).__name__}")
    cov = [[c["checklist_item"], c["status"], c["reason"]] for c in r.get("coverage", [])]
    fc = [[c["doa_class"], c["severity"], c["explanation"]] for c in (r.get("contradictions") or {}).get("structured", [])]
    fnd = [[f["status"], f["statement"], f["independent_lineages"]] for f in r.get("findings", [])]
    ids = r.get("identity", [])
    same = sum(1 for i in ids if i["decision"] == "SAME_SUBJECT_PROBABLE")
    rej = sum(1 for i in ids if i["decision"] == "NAMESAKE_REJECTED")
    unres = sum(1 for i in ids if i["decision"] == "UNRESOLVED")
    high = [c for c in (r.get("contradictions") or {}).get("structured", []) if c["severity"] in ("HIGH", "CRITICAL")]
    gaps = [c for c in r.get("coverage", []) if c["status"] in ("NOT_ASSESSED", "NOT_AVAILABLE")]
    md = [f"### DOA: {name}",
          f"**{len(docs)}** documents checked. **{same}** attributed to the subject on a non-name anchor, "
          f"**{rej}** rejected as namesakes, **{unres}** unresolved (name only, kept out of findings).",
          f"**{len(fc)}** structured contradiction(s), **{len(high)}** HIGH. **{len(gaps)}** source(s) not assessed or unavailable.",
          "> Evidence graph, not a verdict: no fact, identity, guilt or non-existence is established automatically. "
          "\"Not found\" means not found in the sources searched.",
          f"<sub>Run {r['investigation_id']} · result SHA-256 `{r['sha256'][:16]}…` · PDF SHA-256 `{pdf['pdf_sha256'][:16]}…` · {pdf['generated']}</sub>"]
    if notes:
        md.append("\n".join(f"- ⚠ {n}" for n in notes))
    return ("\n\n".join(md), cov or None, fc or None, fnd or None, gr.update(value=pdf["pdf"], visible=True))


AUTO_DOWNLOAD_JS = """() => { setTimeout(() => {
  const el = document.getElementById('doa_pdf_download'); const b = el && (el.matches('a,button') ? el : el.querySelector('a,button')); if (b) b.click(); }, 600); }"""


def build_doa_tab():
    import gradio as gr
    gr.Markdown("**Deep OSINT Agent (DOA).** Builds an evidence graph from official lists, SEBI orders, ICIJ, "
                "sanctions, dark-web monitoring and documents you paste. Leads, not verdicts.")
    with gr.Row():
        name = gr.Textbox(label="Subject name *", placeholder="e.g. Ravi Kalpnik")
        aliases = gr.Textbox(label="Aliases (comma separated)")
    with gr.Row():
        dob = gr.Textbox(label="Date of birth (YYYY-MM-DD)", placeholder="optional, strongest identity anchor")
        city = gr.Textbox(label="City")
        orgs = gr.Textbox(label="Organisations (comma separated)")
    question = gr.Textbox(label="Question", placeholder="e.g. Did he take a loan before denying it?")
    docs = gr.Textbox(label="Documents (optional): separate with a line ---; headers URL:/TITLE:/TIER:/KIND:/PUBLISHED:",
                      lines=8)
    with gr.Row():
        use_local = gr.Checkbox(value=True, label="Local sources (SEBI, UK/OFAC/UN/EU/World Bank)")
        use_sec = gr.Checkbox(value=False, label="SEC EDGAR live search")
        use_dark = gr.Checkbox(value=True, label="Dark-web monitoring (leads only)")
    run = gr.Button("🔎  Run DOA + PDF", variant="primary")
    summary = gr.Markdown()
    cov = gr.Dataframe(headers=["Source", "Status", "Reason"], label="Coverage", wrap=True)
    fc = gr.Dataframe(headers=["Type", "Severity", "What conflicts"], label="Contradictions", wrap=True)
    fnd = gr.Dataframe(headers=["Status", "Statement", "Independent sources"], label="Findings", wrap=True)
    dl = (gr.DownloadButton(label="⬇ DOA dossier (PDF)", visible=False, elem_id="doa_pdf_download")
          if hasattr(gr, "DownloadButton") else gr.File(label="DOA dossier (PDF)", visible=False, elem_id="doa_pdf_download"))
    run.click(run_doa, inputs=[name, aliases, dob, city, orgs, question, docs, use_local, use_sec, use_dark],
              outputs=[summary, cov, fc, fnd, dl]).then(fn=None, js=AUTO_DOWNLOAD_JS)
    return run
