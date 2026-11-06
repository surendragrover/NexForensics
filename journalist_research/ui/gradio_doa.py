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
from typing import List, Tuple, Optional

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


UPLOAD_TYPES = [".pdf", ".txt", ".md", ".csv", ".html", ".htm", ".docx", ".png", ".jpg", ".jpeg", ".tif", ".tiff"]
MAX_UPLOAD_BYTES = 25 * 1024 * 1024


def _file_text(path: str) -> Tuple[str, str]:
    """Plain text of one uploaded file and the method used. Never executes or renders the file."""
    ext = os.path.splitext(path)[1].lower()
    with open(path, "rb") as fh:
        data = fh.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise ValueError("file larger than 25 MB")
    if ext == ".pdf":
        from journalist_research.extraction.pdf_text import extract_pdf_bytes
        r = extract_pdf_bytes(data, ocr=True)
        return "\n".join(r.pages), f"pdf:{r.engine}" + (" +OCR" if r.scanned_pages else "")
    if ext == ".docx":
        import zipfile, io
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            xml = z.read("word/document.xml").decode("utf-8", "replace")
        xml = re.sub(r"</w:p>", "\n", xml)
        return re.sub(r"<[^>]+>", "", xml), "docx"
    if ext in (".html", ".htm"):
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(data, "html.parser")
        for t in soup(["script", "style", "noscript"]):
            t.decompose()
        return soup.get_text("\n"), "html"
    if ext in (".png", ".jpg", ".jpeg", ".tif", ".tiff"):
        import subprocess
        out = subprocess.run(["tesseract", path, "stdout", "-l", "eng+hin"], capture_output=True, timeout=120)
        return out.stdout.decode("utf-8", "replace"), "image:OCR"
    for enc in ("utf-8", "utf-16", "latin-1"):
        try:
            return data.decode(enc), "text"
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", "replace"), "text"


def parse_uploads(files, profile: SubjectProfile) -> Tuple[list, list]:
    """Each uploaded file becomes its own investigator-supplied document (title = file name)."""
    docs, notes = [], []
    for f in files or []:
        path = f if isinstance(f, str) else getattr(f, "name", None) or getattr(f, "path", None)
        if not path:
            continue
        fname = os.path.basename(path)
        if os.path.splitext(fname)[1].lower() not in UPLOAD_TYPES:
            notes.append(f"{fname}: file type not supported, skipped")
            continue
        try:
            text, how = _file_text(path)
        except Exception as e:  # noqa: BLE001
            notes.append(f"{fname}: could not read ({type(e).__name__})")
            continue
        text = re.sub(r"(?m)^\s*-{3,}\s*$", "\u2014", text or "").strip()
        if not text:
            notes.append(f"{fname}: no readable text")
            continue
        safe = re.sub(r"[^\w.\- ]", "_", fname)[:120]
        got = parse_documents(f"TITLE: {safe}\nURL: upload://{safe}\n{text}", profile)
        for d in got:
            d.document_id = f"up{len(docs) + 1}-{d.document_id}"
            docs.append(d)
        notes.append(f"{fname}: read ({how}), {len(text):,} characters")
    return docs, notes


def gather(profile: SubjectProfile, docs_raw: str, use_local: bool, use_sec: bool, use_dark: bool,
           files=None, use_public: bool = False, social_raw: str = "", extra: Optional[dict] = None) -> Tuple[list, list]:
    docs, notes = parse_documents(docs_raw, profile), []
    up = []
    if files:
        up, up_notes = parse_uploads(files, profile)
        docs += up
        notes += up_notes
    lines = [l.strip() for l in (social_raw or "").splitlines() if l.strip()]
    if use_public or lines:
        try:
            from journalist_research.sources.public_profile import collect_public, mark_uploaded_social
            pdocs, pout, pnotes = collect_public(profile, lines) if use_public else (None, None, None)
            if not use_public:     # only the named accounts/links, no news or encyclopaedia search
                from journalist_research.sources.public_profile import social_documents, link_documents
                sdocs, accts, links = social_documents(lines, profile)
                pdocs, pout, pnotes = sdocs + link_documents(links[:10], profile), {"social_accounts": accts}, []
            docs += pdocs
            notes += pnotes
            if extra is not None:
                extra.update(pout)
            k = mark_uploaded_social(up, pout.get("social_accounts", []), lines)
            if k:
                notes.append(f"{k} uploaded file(s) show a named account and were read as the subject's own posts")
        except Exception as e:  # noqa: BLE001
            notes.append(f"Public profile sources unavailable: {type(e).__name__}: {e}")
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


def _face_md(fr) -> str:
    if not fr or fr.get("status") != "ASSESSED":
        return f"**Face comparison:** not assessed. {fr.get('reason', '') if fr else ''}"
    lines = [f"**Face comparison ({fr.get('model')}):** {fr['faces_checked']} face(s) checked in the uploaded files. "
             "Similarity is a lead for human review, not identity. POSSIBLE MATCH from cosine 0.363 (OpenCV's "
             "documented SFace threshold); STRONG from 0.50 (provisional).", "",
             "| File | Where | Face | Similarity | Band |", "|---|---|---|---|---|"]
    for m in fr["matches"][:15]:
        lines.append(f"| {m['file']} | {m['where']} | {m['face']} | {m['similarity']:.3f} | {m['band']} |")
    if fr.get("reason"):
        lines.append(f"\n{fr['reason']}")
    for n in fr.get("notes", []):
        lines.append(f"\n_{n}_")
    return "\n".join(lines)


try:
    import gradio as _gr_mod
    _GrRequest = _gr_mod.Request
except Exception:  # noqa: BLE001
    _GrRequest = object


def _purge_upload(path) -> bool:
    """Delete one uploaded file from Gradio's cache (and its now-empty folder)."""
    try:
        p = getattr(path, "name", path)
        if not p or not os.path.isfile(p):
            return True
        os.remove(p)
        d = os.path.dirname(p)
        if os.path.isdir(d) and not os.listdir(d):
            os.rmdir(d)
        return True
    except OSError:
        return False


def run_doa(name, aliases, dob, city, orgs, question, docs_raw, use_local, use_sec, use_dark, files=None,
            subject_photo=None, use_public=True, social_raw="", use_corp=True, request: _GrRequest = None):
    import gradio as gr
    from journalist_research.report.doa_pdf import render_doa_pdf
    name = (name or "").strip()
    if not name:
        return ("**Subject name is required.**", None, None, None, None, gr.update(value=None, visible=False))
    if dob and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", dob.strip()):
        return ("**Date of birth must be YYYY-MM-DD (or leave it empty).**", None, None, None, None,
                gr.update(value=None, visible=False))
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    sid = "SUBJ-" + hashlib.sha256(name.lower().encode()).hexdigest()[:10]
    profile = SubjectProfile(subject_id=sid, name=name, aliases=_split_list(aliases), dob=(dob or "").strip() or None,
                             city=(city or "").strip() or None, organizations=_split_list(orgs))
    # several questions, one per line (a line may also hold several "?"-ended questions)
    qs = []
    for ln in (question or "").splitlines():
        for q in re.findall(r"[^?]+\?|[^?]+$", ln):
            q = q.strip(" \t-•*0123456789.)")
            if len(q) > 2:
                qs.append(q if q.endswith("?") else q + "?")
    qs = qs or [f"What can be verified about {name}?"]
    question = "\n".join(f"{i}. {q}" for i, q in enumerate(qs, 1)) if len(qs) > 1 else qs[0]
    try:
        extra = {}
        _corp_fut = None
        if use_corp:
            import concurrent.futures as _cf
            from journalist_research.sources.corporate_registry import collect_corporate
            _ex = _cf.ThreadPoolExecutor(1)
            _corp_fut = _ex.submit(collect_corporate, profile)
        docs, notes = gather(profile, docs_raw, use_local, use_sec, use_dark, files, use_public, social_raw, extra)
        corp = None
        if _corp_fut is not None:
            try:
                corp = _corp_fut.result(timeout=45)
                for _k, _v in corp.get("sources", {}).items():
                    if _v.get("status") not in ("OK", "NOT_ASSESSED"):
                        notes.append(f"Company registry {_k}: {_v.get('status')} {'; '.join(_v.get('notes', []))}")
            except Exception as e:  # noqa: BLE001
                notes.append(f"Company registries not searched ({type(e).__name__})")
        inv = f"DOA-{stamp}-{sid[-6:]}"
        r = DOAPipeline(inv, question, profile, docs, artifact_root=ART,
                        social_accounts=extra.get("social_accounts"), corporate=corp).run()
        from journalist_research.storage import drive_store as _ds
        _uid = _ds.user_from_request(request)
        try:
            _ds.stage(files, _uid, inv, "documents")
        except Exception as e:  # noqa: BLE001
            notes.append(f"Uploaded documents not archived to Drive ({type(e).__name__})")
        face = None
        if subject_photo:
            try:
                from journalist_research.biometrics.face_match import compare as _face_compare
                face = _face_compare(subject_photo, files)
            except Exception as e:  # noqa: BLE001
                face = {"status": "NOT_ASSESSED", "reason": f"Face comparison failed ({type(e).__name__})."}
            finally:
                # Storage rule (approved 2026-11-06): the photo is kept on the owner's Google Drive,
                # encrypted, per user, while the account exists. No copy stays on the server.
                try:
                    _ds.stage([subject_photo], _uid, inv, "subject_photo")
                except Exception as e:  # noqa: BLE001
                    notes.append(f"Subject photo not archived to Drive ({type(e).__name__})")
                _purged = _purge_upload(subject_photo)
                if not _purged:
                    notes.append("Subject photo could not be removed from the server cache; check manually")
        pdf = render_doa_pdf(r, {"name": name, "aliases": profile.aliases, "dob": profile.dob, "city": profile.city,
                                 "organizations": profile.organizations, "face": face}, os.path.join(ART, inv, f"{inv}.pdf"))
        try:
            _ds.stage([pdf["pdf"]], _uid, inv, "dossier")
            notes.append("Uploaded files and the dossier are stored encrypted on Google Drive for this account "
                         "(kept while the account exists)")
        except Exception as e:  # noqa: BLE001
            notes.append(f"Dossier not archived to Drive ({type(e).__name__})")
        for _f in (files or []):
            _purge_upload(_f)
        _ds.flush_async()
    except Exception as e:  # noqa: BLE001
        return (f"**DOA run failed:** `{type(e).__name__}: {e}`\n\n```\n{traceback.format_exc()[-1500:]}\n```",
                None, None, None, None, gr.update(value=None, visible=False))

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
    if subject_photo:
        md.append(_face_md(face))
    md.append(_social_md(r.get("social") or []))
    if r.get("corporate") and (r.get("network") or {}).get("stats"):
        from journalist_research.evidence.corporate_network import markdown as _net_md
        md.append(_net_md(r["corporate"], r["network"]))
    life = [[i["interest"], i["category"], i["status"], i["basis"], i["independent_sources"],
             ("HIGH-COST" if i["high_cost"] else ""), i["mentions"][0]["quote"],
             i["mentions"][0]["publisher"] or i["mentions"][0]["url"]] for i in (r.get("lifestyle") or {}).get("items", [])]
    return ("\n\n".join(m for m in md if m), cov or None, fc or None, fnd or None, life or None,
            gr.update(value=pdf["pdf"], visible=True))


def _social_md(accts) -> str:
    if not accts:
        return ""
    out = ["**Social media** (named accounts are analysed, and their posts are the subject's own words, not verified facts; pages found through search are name-only leads):", "",
           "| Platform | Account | Status | Posts | Period | Followers | Top hashtags | Most mentioned |",
           "|---|---|---|---|---|---|---|---|"]
    for a in accts:
        if a.get("status") == "ASSESSED":
            out.append(f"| {a['platform']} | {a.get('handle', '')} | analysed | {a.get('posts_analysed', 0)} | "
                       f"{a.get('first_post') or '?'} to {a.get('last_post') or '?'} | {a.get('followers') or ''} | "
                       f"{', '.join('#' + t for t, _ in a.get('top_hashtags', [])[:4])} | "
                       f"{', '.join('@' + m for m, _ in a.get('top_mentions', [])[:3])} |")
        elif a.get("status") == "CANDIDATE":
            out.append(f"| {a['platform']} | [{a.get('handle', '')}]({a.get('url')}) | name-only lead (open and confirm) | "
                       f"| | | {(a.get('snippet') or '')[:90].replace('|', '/')} | |")
        else:
            out.append(f"| {a['platform']} | {a.get('handle', '')} | not available | | | | {a.get('reason', '')} | |")
    return "\n".join(out)


AUTO_DOWNLOAD_JS = """() => { setTimeout(() => {
  const el = document.getElementById('doa_pdf_download'); const b = el && (el.matches('a,button') ? el : el.querySelector('a,button')); if (b) b.click(); }, 600); }"""


def build_doa_tab():
    import gradio as gr
    gr.Markdown("### Deep OSINT Agent (DOA)")
    with gr.Row():
        name = gr.Textbox(label="Subject name *", placeholder="e.g. Ravi Kalpnik")
        aliases = gr.Textbox(label="Aliases (comma separated)")
    photo = gr.Image(label="Subject photo (optional): compared with faces in the uploaded files",
                     type="filepath", height=220, sources=["upload"])
    with gr.Row():
        dob = gr.Textbox(label="Date of birth (YYYY-MM-DD)", placeholder="optional, strongest identity anchor")
        city = gr.Textbox(label="City")
        orgs = gr.Textbox(label="Organisations (comma separated)")
    question = gr.Textbox(label="Questions (one per line)", lines=6, max_lines=20,
                          placeholder="e.g.\nDid he take a loan before denying it?\nWas he a director of any company?\n"
                                      "Is his name on any sanctions list?")
    files = gr.File(label="Documents (optional): upload one or more files (PDF, Word, text, HTML, images)",
                    file_count="multiple", file_types=UPLOAD_TYPES, type="filepath")
    docs = gr.State("")
    with gr.Row():
        use_local = gr.Checkbox(value=True, label="Local sources (SEBI, UK/OFAC/UN/EU/World Bank)")
        use_sec = gr.Checkbox(value=False, label="SEC EDGAR live search")
        use_dark = gr.Checkbox(value=True, label="Dark-web monitoring (leads only)")
        use_public = gr.Checkbox(value=True, label="News, Wikipedia & lifestyle (public sources)")
        use_corp = gr.Checkbox(value=True, label="Companies & directors (UK registry, Offshore Leaks, GLEIF)")
    social = gr.Textbox(label="Social media accounts & public links (one per line)", lines=3,
                        placeholder="e.g.\nhttps://bsky.app/profile/name.bsky.social\nhttps://mastodon.social/@name\n"
                                    "https://t.me/channelname\nhttps://x.com/name  (X, Instagram, Facebook, LinkedIn: "
                                    "also upload screenshots of the posts)")
    run = gr.Button("🔎  Run DOA + PDF", variant="primary")
    summary = gr.Markdown()
    cov = gr.Dataframe(headers=["Source", "Status", "Reason"], label="Coverage", wrap=True)
    fc = gr.Dataframe(headers=["Type", "Severity", "What conflicts"], label="Contradictions", wrap=True)
    fnd = gr.Dataframe(headers=["Status", "Statement", "Independent sources"], label="Findings", wrap=True)
    life = gr.Dataframe(headers=["Interest", "Category", "Status", "Basis", "Independent sources", "Cost",
                                 "Quote", "Source"], label="Public lifestyle & interests", wrap=True)
    dl = (gr.DownloadButton(label="⬇ DOA dossier (PDF)", visible=False, elem_id="doa_pdf_download")
          if hasattr(gr, "DownloadButton") else gr.File(label="DOA dossier (PDF)", visible=False, elem_id="doa_pdf_download"))
    run.click(run_doa, inputs=[name, aliases, dob, city, orgs, question, docs, use_local, use_sec, use_dark, files, photo,
                      use_public, social, use_corp],
              outputs=[summary, cov, fc, fnd, life, dl]).then(fn=None, js=AUTO_DOWNLOAD_JS)
    return run
