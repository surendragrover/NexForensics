"""
Public profile sources for DOA (2026-11-06): news, encyclopaedia, investigator links, social media.

Free, login-free, robots-respecting only (PoliteFetcher):
  * Wikipedia article page /wiki/<Name> (en, hi). The API paths are robots-disallowed, so they are not used.
  * GDELT DOC 2.0 article list, then up to N article pages.
  * Links the investigator pastes (public pages).
  * Social accounts the investigator names (we never guess an account from a name, to avoid namesakes):
      Bluesky   public AppView API (profile + author feed)
      Mastodon  public RSS of the account
      Telegram  public channel preview t.me/s/<channel>
    X/Twitter (paid API), Instagram, Facebook, LinkedIn, Threads: login-walled or ToS-barred, so they are
    recorded NOT_AVAILABLE with the reason; screenshots or saved pages uploaded by the user are analysed instead.
Every name hit is a NAME LEAD; identity is decided by DOAPipeline.resolve_identity. Social accounts named
by the investigator are investigator_supplied and their posts are the subject's own words (source_kind SELF).
"""
from __future__ import annotations
import hashlib, json, re, time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote, urlparse
from xml.etree import ElementTree as ET

from ..runtime.doa_pipeline import InputDocument, SubjectProfile
from .http_polite import PoliteFetcher, SourceBlocked

CHECK_WIKI = "Wikipedia (public encyclopaedia)"
CHECK_NEWS = "News coverage (GDELT)"
CHECK_LINKS = "Investigator-supplied public links"
CHECK_SOCIAL = "Social media"
WALLED = {"x.com": "X/Twitter", "twitter.com": "X/Twitter", "instagram.com": "Instagram", "facebook.com": "Facebook",
          "fb.com": "Facebook", "linkedin.com": "LinkedIn", "threads.net": "Threads", "threads.com": "Threads"}
TIME_BUDGET = 35          # seconds for the whole network part of one run
MAX_ARTICLES = 6
MAX_POSTS = 60


def _fetcher() -> PoliteFetcher:
    return PoliteFetcher(delay=1.0, timeout=15)


def _mention(text: str, profile: SubjectProfile, **extra) -> dict:
    from journalist_research.ui.gradio_doa import detect_mention
    return {**detect_mention(text, profile), **extra}


def _html_text(content: bytes, url: str) -> Tuple[str, str, str]:
    from journalist_research.web_research.page_extractor import PageExtractor
    p = PageExtractor().extract(content, url)
    return p.text or "", p.title or "", p.published_at or ""


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8", "ignore")).hexdigest()


# ------------------------------------------------------------------ encyclopaedia
def wikipedia_documents(profile: SubjectProfile, f: Optional[PoliteFetcher] = None) -> List[InputDocument]:
    f = f or _fetcher()
    docs = []
    for lang in ("en", "hi"):
        title = profile.name.strip().replace(" ", "_")
        url = f"https://{lang}.wikipedia.org/wiki/{quote(title)}"
        try:
            r = f.get(url)
        except (SourceBlocked, Exception) as e:  # noqa: BLE001
            docs.append(InputDocument(document_id=f"wiki-{lang}-blocked", source_id=f"wiki-{lang}", url=url,
                                      title="Wikipedia", text="", status="UNAVAILABLE", checklist_item=CHECK_WIKI,
                                      publisher=f"{lang}.wikipedia.org", mention={"error": type(e).__name__}))
            continue
        html = r.text
        if r.status == 404 or "noarticletext" in html:
            continue
        if 'id="disambigbox"' in html or "may refer to" in html[:60000]:
            docs.append(InputDocument(document_id=f"wiki-{lang}-disambig", source_id=f"wiki-{lang}", url=r.final_url,
                                      title="Wikipedia disambiguation", text="", status="NO_RESULT",
                                      checklist_item=CHECK_WIKI, publisher=f"{lang}.wikipedia.org",
                                      mention={"note": "several people share this name; open the page manually"}))
            continue
        text, ttl, _ = _html_text(r.content, r.final_url)
        bday = re.search(r'class="bday">(\d{4}-\d{2}-\d{2})<', html)
        m = _mention(text, profile)
        if bday:
            m["dob"] = bday.group(1)           # infobox DOB: a hard anchor (match or namesake conflict)
        docs.append(InputDocument(document_id=f"wiki-{lang}-{_sha(r.final_url)[:10]}", source_id=f"wiki-{lang}",
                                  url=r.final_url, title=ttl or profile.name, text=text[:60000], tier="MEDIUM",
                                  publisher=f"{lang}.wikipedia.org", source_kind="REPORT",
                                  lineage_id=f"wikipedia:{lang}:{title}", checklist_item=CHECK_WIKI, mention=m))
    if not docs:
        docs.append(InputDocument(document_id="wiki-none", source_id="wiki", url="https://en.wikipedia.org/",
                                  title="Wikipedia", text="", status="NO_RESULT", checklist_item=CHECK_WIKI))
    return docs


# ------------------------------------------------------------------ news
GDELT_GAP = 5.5           # GDELT asks for at most one request every 5 s, from this whole server
GDELT_CACHE_FRESH = 6 * 3600
GDELT_CACHE_STALE_OK = 7 * 86400
NEWS_SKIP_HOSTS = ("wikipedia.org", "wikimedia.org", "facebook.com", "instagram.com", "x.com", "twitter.com",
                   "linkedin.com", "youtube.com", "threads.net", "threads.com", "duckduckgo.com")


def _gdelt_cache_path(q: str):
    import os
    d = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runtime", "artifacts", "cache", "gdelt")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, _sha(q)[:24] + ".json")


def _gdelt_get(api: str, f: PoliteFetcher, deadline: float) -> Tuple[List[dict], str]:
    """Article list for one query. Spacing is shared by every process on the server through a lock file,
    a 429 is retried once after the gap, and a cached list (6 h fresh, 7 days stale) answers when GDELT throttles.
    Returns (articles, how): how is LIVE, CACHED, CACHED_STALE or an error name."""
    import fcntl, os
    cp = _gdelt_cache_path(api)
    try:
        age = time.time() - os.path.getmtime(cp)
        if age < GDELT_CACHE_FRESH:
            return json.load(open(cp)).get("articles", []), "CACHED"
    except OSError:
        age = None
    err = "UNAVAILABLE"
    for attempt in range(2):
        if deadline and time.monotonic() + GDELT_GAP > deadline:
            break
        with open("/tmp/doa_gdelt.lock", "a+") as lk:
            fcntl.flock(lk, fcntl.LOCK_EX)
            try:
                lk.seek(0); last = float(lk.read().strip() or 0)
            except ValueError:
                last = 0
            wait = GDELT_GAP - (time.time() - last)
            if wait > 0:
                time.sleep(wait)
            try:
                body = f.get(api).text or "{}"
                err = ""
            except SourceBlocked as e:
                err = "RATE_LIMITED" if "429" in str(e) else "BLOCKED"
            except Exception as e:  # noqa: BLE001
                err = type(e).__name__
            lk.seek(0); lk.truncate(); lk.write(str(time.time())); lk.flush()
        if not err:
            try:
                data = json.loads(body)
            except ValueError:                       # GDELT answers throttling with plain text
                err = "RATE_LIMITED" if "limit requests" in body else "BAD_RESPONSE"
                continue
            try:
                json.dump({"articles": data.get("articles", [])}, open(cp, "w"))
            except OSError:
                pass
            return data.get("articles", []), "LIVE"
        if err != "RATE_LIMITED":
            break
    if age is not None and age < GDELT_CACHE_STALE_OK:
        return json.load(open(cp)).get("articles", []), "CACHED_STALE"
    raise SourceBlocked(err)


def _search_news_list(profile: SubjectProfile, deadline: float) -> List[dict]:
    """Fallback when GDELT is unavailable: a public search engine's result page for the name.
    Only the result list is read here; each article page is then fetched politely (robots respected)."""
    from journalist_research.web_research.duckduckgo_provider import DuckDuckGoPublicWebProvider
    if deadline and time.monotonic() > deadline - 8:
        return []
    org = (profile.organizations or [""])[0]
    q = f'"{profile.name}" {org} news'.strip()
    out = []
    for h in DuckDuckGoPublicWebProvider(timeout=12).search(q, max_results=20):
        host = urlparse(h.url).netloc.lower()
        if not host or any(host == d or host.endswith("." + d) for d in NEWS_SKIP_HOSTS):
            continue
        out.append({"url": h.url, "title": h.title, "seendate": "", "via": "search"})
    return out


def gdelt_documents(profile: SubjectProfile, f: Optional[PoliteFetcher] = None, deadline: float = 0) -> List[InputDocument]:
    f = f or _fetcher()
    q = quote(f'"{profile.name}"')
    api = f"https://api.gdeltproject.org/api/v2/doc/doc?query={q}&mode=artlist&maxrecords=25&format=json&sort=hybridrel"
    via, gerr = "GDELT", ""
    try:
        arts, how = _gdelt_get(api, f, deadline)
        via = "GDELT" if how == "LIVE" else f"GDELT ({how.lower().replace('_', ' ')})"
    except Exception as e:  # noqa: BLE001
        arts, gerr = [], (str(e) or type(e).__name__)
    if not arts:
        try:
            arts = _search_news_list(profile, deadline)
            via = f"search engine (GDELT {gerr.lower() or 'no result'})"
        except Exception as e:  # noqa: BLE001
            arts = []
            gerr = gerr or type(e).__name__
    if not arts:
        if gerr:
            return [InputDocument(document_id="gdelt-unavailable", source_id="gdelt", url=api, title="GDELT", text="",
                                  status="UNAVAILABLE", checklist_item=CHECK_NEWS, mention={"error": gerr})]
        return [InputDocument(document_id="gdelt-none", source_id="gdelt", url=api, title="GDELT", text="",
                              status="NO_RESULT", checklist_item=CHECK_NEWS)]
    seen_hosts, picks = set(), []
    for a in arts:                                   # one article per outlet, so lineages differ
        h = urlparse(a.get("url", "")).netloc
        if h and h not in seen_hosts:
            seen_hosts.add(h); picks.append(a)
        if len(picks) >= MAX_ARTICLES:
            break
    docs = []

    def one(a):
        if deadline and time.monotonic() > deadline:
            return None
        r = PoliteFetcher(delay=0, timeout=12).get(a["url"])
        text, ttl, pub = _html_text(r.content, r.final_url)
        return a, r, text, ttl, pub

    with ThreadPoolExecutor(max_workers=4) as ex:
        futs = [ex.submit(one, a) for a in picks]
        for fu in as_completed(futs):
            try:
                res = fu.result()
            except Exception:  # noqa: BLE001  (blocked or failed outlet: skipped, counted below)
                continue
            if not res:
                continue
            a, r, text, ttl, pub = res
            if len(text.strip()) < 200:              # paywall or script-only page: nothing to read
                continue
            host = urlparse(r.final_url).netloc
            sd = a.get("seendate", "")
            docs.append(InputDocument(
                document_id=f"news-{_sha(r.final_url)[:12]}", source_id=f"news-{host}", url=r.final_url,
                title=ttl or a.get("title", ""), text=text[:40000], tier="MEDIUM", publisher=host,
                source_kind="REPORT", lineage_id=f"news:{_sha(r.final_url)[:16]}",
                published_at=pub or (f"{sd[:4]}-{sd[4:6]}-{sd[6:8]}" if len(sd) >= 8 else None),
                checklist_item=CHECK_NEWS, mention=_mention(text, profile, found_via=via)))
    if not docs:
        docs.append(InputDocument(document_id="gdelt-fetch-failed", source_id="gdelt", url=api, title="GDELT", text="",
                                  status="UNAVAILABLE", checklist_item=CHECK_NEWS,
                                  mention={"note": f"{len(picks)} articles listed via {via}, none fetchable"}))
    return docs


# ------------------------------------------------------------------ investigator links
def link_documents(urls: List[str], profile: SubjectProfile, f: Optional[PoliteFetcher] = None) -> List[InputDocument]:
    f = f or _fetcher()
    docs = []
    for u in urls:
        try:
            r = f.get(u)
            text, ttl, pub = _html_text(r.content, r.final_url)
            st = "OK" if text.strip() else "UNAVAILABLE"
        except Exception as e:  # noqa: BLE001
            text, ttl, pub, st, r = "", "", "", "UNAVAILABLE", None
        docs.append(InputDocument(
            document_id=f"link-{_sha(u)[:12]}", source_id=f"link-{urlparse(u).netloc}", url=u, title=ttl or u,
            text=text[:60000], tier="MEDIUM", publisher=urlparse(u).netloc, lineage_id=f"link:{_sha(u)[:16]}",
            published_at=pub or None, status=st, checklist_item=CHECK_LINKS,
            mention=_mention(text, profile, investigator_supplied=True)))
    return docs


# ------------------------------------------------------------------ social
def classify_account(line: str) -> Optional[Dict[str, str]]:
    s = line.strip()
    if not s:
        return None
    u = s if re.match(r"https?://", s) else None
    host = urlparse(u).netloc.lower().removeprefix("www.").removeprefix("m.") if u else ""
    for dom, name in WALLED.items():
        if host == dom or host.endswith("." + dom):
            return {"platform": name, "handle": urlparse(u).path.strip("/").split("/")[0], "url": u, "walled": "1"}
    if host == "bsky.app":
        m = re.search(r"/profile/([^/?#]+)", u)
        return {"platform": "Bluesky", "handle": m.group(1), "url": u} if m else None
    if host == "t.me":
        ch = urlparse(u).path.strip("/").removeprefix("s/").split("/")[0]
        return {"platform": "Telegram", "handle": ch, "url": f"https://t.me/s/{ch}"}
    if u and re.search(r"/@[\w.]+/?$", urlparse(u).path):
        return {"platform": "Mastodon", "handle": urlparse(u).path.strip("/@"), "url": u.rstrip("/")}
    if not u and re.fullmatch(r"@?[\w-]+(\.[\w-]+)+", s):           # bare Bluesky handle e.g. name.bsky.social
        return {"platform": "Bluesky", "handle": s.lstrip("@"), "url": f"https://bsky.app/profile/{s.lstrip('@')}"}
    if u:
        return {"platform": "link", "url": u}
    return None


def _bluesky(acc, f) -> Tuple[Dict[str, Any], List[Dict[str, str]]]:
    base = "https://public.api.bsky.app/xrpc/"
    prof = json.loads(f.get(base + "app.bsky.actor.getProfile?actor=" + quote(acc["handle"])).text)
    feed = json.loads(f.get(base + f"app.bsky.feed.getAuthorFeed?actor={quote(acc['handle'])}&limit=100"
                            "&filter=posts_no_replies").text).get("feed", [])
    posts = []
    for it in feed:
        p = it.get("post", {})
        if p.get("author", {}).get("did") != prof.get("did"):      # reposts of others are not the subject's words
            continue
        rec = p.get("record", {})
        posts.append({"date": (rec.get("createdAt") or "")[:10], "text": rec.get("text", "")})
    meta = {"display_name": prof.get("displayName", ""), "bio": prof.get("description", ""),
            "followers": prof.get("followersCount"), "following": prof.get("followsCount"),
            "posts_total": prof.get("postsCount"), "joined": (prof.get("createdAt") or "")[:10]}
    return meta, posts


def _mastodon(acc, f):
    r = f.get(acc["url"] + ".rss")
    root = ET.fromstring(r.content)
    ch = root.find("channel")
    posts = []
    for it in ch.findall("item"):
        from email.utils import parsedate_to_datetime
        try:
            d = parsedate_to_datetime(it.findtext("pubDate")).date().isoformat()
        except Exception:  # noqa: BLE001
            d = ""
        txt = re.sub(r"<[^>]+>", " ", it.findtext("description") or "")
        posts.append({"date": d, "text": re.sub(r"\s+", " ", txt).strip()})
    return {"display_name": ch.findtext("title") or "", "bio": ch.findtext("description") or ""}, posts


def _telegram(acc, f):
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(f.get(acc["url"]).text, "html.parser")
    posts = []
    for w in soup.select(".tgme_widget_message_wrap"):
        t = w.select_one(".tgme_widget_message_text")
        tm = w.select_one("time")
        if t:
            posts.append({"date": (tm.get("datetime", "") if tm else "")[:10], "text": t.get_text(" ", strip=True)})
    title = soup.select_one(".tgme_channel_info_header_title")
    desc = soup.select_one(".tgme_channel_info_description")
    cnt = soup.select_one(".tgme_channel_info_counter .counter_value")
    return {"display_name": title.get_text(strip=True) if title else "", "bio": desc.get_text(" ", strip=True) if desc else "",
            "followers": cnt.get_text(strip=True) if cnt else None}, posts


def analyse_posts(posts: List[Dict[str, str]]) -> Dict[str, Any]:
    texts = [p["text"] for p in posts if p.get("text")]
    dates = sorted(p["date"] for p in posts if p.get("date"))
    tags = Counter(t.lower() for x in texts for t in re.findall(r"#(\w{2,40})", x))
    ments = Counter(m.lower() for x in texts for m in re.findall(r"(?<![\w.])@([\w.]{2,40}\w)", x))
    doms = Counter(urlparse(u).netloc.removeprefix("www.") for x in texts for u in re.findall(r"https?://\S+", x))
    months = Counter(d[:7] for d in dates)
    return {"posts_analysed": len(texts), "first_post": dates[0] if dates else None, "last_post": dates[-1] if dates else None,
            "top_hashtags": tags.most_common(8), "top_mentions": ments.most_common(6), "top_link_domains": doms.most_common(6),
            "busiest_months": months.most_common(3)}


def social_documents(lines: List[str], profile: SubjectProfile, f: Optional[PoliteFetcher] = None
                     ) -> Tuple[List[InputDocument], List[Dict[str, Any]], List[str]]:
    """Returns (documents, per-account analysis, plain public links to fetch as pages)."""
    f = f or _fetcher()
    docs, accounts, links = [], [], []
    for ln in lines:
        acc = classify_account(ln)
        if not acc:
            continue
        if acc["platform"] == "link":
            links.append(acc["url"]); continue
        row = {"platform": acc["platform"], "handle": acc.get("handle", ""), "url": acc["url"]}
        if acc.get("walled"):
            row.update(status="NOT_AVAILABLE", reason=f"{acc['platform']} needs a login or a paid API; "
                       "upload screenshots or a saved page of the posts instead")
            accounts.append(row)
            docs.append(InputDocument(document_id=f"social-{_sha(acc['url'])[:10]}", source_id=f"social-{acc['platform']}",
                                      url=acc["url"], title=f"{acc['platform']} {row['handle']}", text="",
                                      status="UNAVAILABLE", checklist_item=f"{CHECK_SOCIAL}: {acc['platform']}"))
            continue
        try:
            meta, posts = {"Bluesky": _bluesky, "Mastodon": _mastodon, "Telegram": _telegram}[acc["platform"]](acc, f)
        except Exception as e:  # noqa: BLE001
            row.update(status="NOT_AVAILABLE", reason=f"fetch failed ({type(e).__name__})")
            accounts.append(row)
            docs.append(InputDocument(document_id=f"social-{_sha(acc['url'])[:10]}", source_id=f"social-{acc['platform']}",
                                      url=acc["url"], title=row["handle"], text="", status="UNAVAILABLE",
                                      checklist_item=f"{CHECK_SOCIAL}: {acc['platform']}"))
            continue
        posts = posts[:MAX_POSTS]
        row.update(status="ASSESSED", **{k: v for k, v in meta.items() if k != "bio"}, bio=(meta.get("bio") or "")[:300],
                   **analyse_posts(posts))
        accounts.append(row)
        body = (f"Profile bio: {meta.get('bio', '')}\n" if meta.get("bio") else "") + "\n".join(
            f"[{p['date']}] {p['text']}" for p in posts if p.get("text"))
        docs.append(InputDocument(
            document_id=f"social-{_sha(acc['url'])[:10]}", source_id=f"social-{acc['platform']}-{row['handle']}",
            url=acc["url"], title=f"{acc['platform']} @{row['handle']}", text=body[:80000], tier="LOW", publisher=acc["platform"], source_kind="SELF",
            lineage_id=f"social:{acc['platform']}:{row['handle'].lower()}",
            published_at=row.get("last_post"), checklist_item=f"{CHECK_SOCIAL}: {acc['platform']}",
            mention={"name": profile.name, "investigator_supplied": True, "self_authored": True,
                     "account": row["handle"]}))
    return docs, accounts, links


def mark_uploaded_social(docs: List[InputDocument], accounts: List[Dict[str, Any]], lines: List[str]) -> int:
    """Uploaded screenshots/saved pages that show one of the named handles are the subject's own posts."""
    handles = {a.get("handle", "").lower().lstrip("@") for a in accounts if a.get("handle")}
    handles |= {h.lower() for ln in lines for h in re.findall(r"@([\w.]{3,40})", ln)}
    n = 0
    for d in docs:
        low = (d.text or "").lower()
        if any(h and ("@" + h) in low for h in handles):
            d.source_kind = "SELF"
            d.mention = {**(d.mention or {}), "self_authored": True}
            n += 1
    return n


# ------------------------------------------------------------------ search-engine snippets of social profiles
SNIPPET_SITES = [("Facebook", "facebook.com"), ("Instagram", "instagram.com"), ("X/Twitter", "x.com"),
                 ("LinkedIn", "linkedin.com"), ("YouTube", "youtube.com"), ("Threads", "threads.net")]
CHECK_SNIPPETS = "Social media (search-engine snippets)"


def social_snippets(profile: SubjectProfile, deadline: float = 0, per_site: int = 4
                    ) -> Tuple[List[InputDocument], List[Dict[str, Any]]]:
    """What a public search engine already shows about public social pages (title + snippet).
    We read the search engine's result page only; the social sites themselves are not fetched.
    Every hit is a NAME_ONLY lead (namesakes are common) with a link for the journalist to open."""
    from journalist_research.web_research.duckduckgo_provider import DuckDuckGoPublicWebProvider
    prov = DuckDuckGoPublicWebProvider(timeout=12)
    docs, cands, failed = [], [], 0
    for plat, dom in SNIPPET_SITES:
        if deadline and time.monotonic() > deadline:
            break
        try:
            hits = prov.search(f'"{profile.name}" site:{dom}', max_results=per_site)
        except Exception:  # noqa: BLE001
            failed += 1
            continue
        time.sleep(1.0)
        for h in hits:
            if dom not in urlparse(h.url).netloc:
                continue
            text = f"{h.title}. {h.snippet}"
            m = _mention(text, profile)
            if not m.get("name"):
                continue
            cands.append({"platform": plat, "handle": h.title[:60], "url": h.url, "status": "CANDIDATE",
                          "snippet": h.snippet[:240]})
            docs.append(InputDocument(
                document_id=f"snip-{_sha(h.url)[:12]}", source_id=f"snippet-{dom}", url=h.url, title=h.title,
                text=text, tier="LOW", publisher=f"{plat} (search snippet)", source_kind="REPORT",
                lineage_id=f"snippet:{_sha(h.url)[:16]}", checklist_item=CHECK_SNIPPETS, mention=m))
    if not docs:
        docs.append(InputDocument(document_id="snip-none", source_id="snippet", url="https://html.duckduckgo.com/html/",
                                  title="search snippets", text="",
                                  status="UNAVAILABLE" if failed == len(SNIPPET_SITES) else "NO_RESULT",
                                  checklist_item=CHECK_SNIPPETS))
    return docs, cands


def collect_public(profile: SubjectProfile, social_lines: List[str]) -> Tuple[List[InputDocument], Dict[str, Any], List[str]]:
    """News + Wikipedia + named social accounts + pasted links, inside one time budget."""
    deadline = time.monotonic() + TIME_BUDGET
    notes, out = [], {}
    with ThreadPoolExecutor(max_workers=3) as ex:
        fw = ex.submit(wikipedia_documents, profile)
        fn = ex.submit(gdelt_documents, profile, None, deadline)
        fs = ex.submit(social_documents, social_lines, profile)
        fp = ex.submit(social_snippets, profile, deadline)
        docs = []
        for name, fu in (("Wikipedia", fw), ("News", fn)):
            try:
                docs += fu.result(timeout=max(1, deadline - time.monotonic()) + 5)
            except Exception as e:  # noqa: BLE001
                notes.append(f"{name} not searched ({type(e).__name__})")
        try:
            sdocs, accounts, links = fs.result(timeout=max(1, deadline - time.monotonic()) + 10)
            docs += sdocs
        except Exception as e:  # noqa: BLE001
            accounts, links = [], []
            notes.append(f"Social media not searched ({type(e).__name__})")
    try:
        pdocs, cands = fp.result(timeout=max(1, deadline - time.monotonic()) + 15)
        docs += pdocs
    except Exception as e:  # noqa: BLE001
        cands = []
        notes.append(f"Social search snippets not searched ({type(e).__name__})")
    if links:
        docs += link_documents(links[:10], profile)
    out["social_accounts"] = accounts + cands
    return docs, out, notes
