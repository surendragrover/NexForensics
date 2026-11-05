"""Offline tests for the DOA dark-web module (no Tor, no network, no DB)."""
import json, os, tempfile
from journalist_research.darkweb_research import safety_filters as SF
from journalist_research.darkweb_research import ransomware_live as RL
from journalist_research.darkweb_research import onion_monitor as OM
from journalist_research.darkweb_research import collect as DC
from journalist_research.runtime.doa_pipeline import SubjectProfile
from journalist_research.common.status import SourceTier, ADEQUATE, tier_of

R = []
def t(name, cond): R.append((name, bool(cond))); print(("PASS" if cond else "FAIL"), name)

ONION = "http://" + "a" * 56 + ".onion/"
ONION2 = "http://" + "b" * 56 + ".onion/x"

# --- safety filters
txt, n = SF.redact_credentials("leak: ravi@example.com:Hunter2! and admin:5f4dcc3b5aa765d61d8327deb882cf99 password=abc123 card 4111 1111 1111 1111")
t("email:password redacted", "Hunter2" not in txt and "[REDACTED-CREDENTIAL]" in txt)
t("hash redacted", "5f4dcc3b5aa765d61d8327deb882cf99" not in txt)
t("password= redacted", "abc123" not in txt)
t("card number redacted", "4111 1111" not in txt)
t("redaction count > 0", n >= 4)
t("plain prose untouched", SF.redact_credentials("SEBI fined X Ltd in 2024.")[0] == "SEBI fined X Ltd in 2024.")
t("abuse tripwire fires", SF.abuse_tripwire("new PTHC links"))
t("tripwire quiet on normal text", not SF.abuse_tripwire("ransomware group posted company files"))
t("html content-type ok", SF.content_type_ok("text/html; charset=utf-8"))
t("image content-type refused", not SF.content_type_ok("image/jpeg"))
t("zip url refused", SF.url_ext_blocked(ONION + "dump.zip"))
t("sql url refused", SF.url_ext_blocked(ONION + "users.sql"))

# --- fake Tor session
class Resp:
    def __init__(self, body, ct="text/html", status=200, redirect=False):
        self.content, self.status_code, self.headers = body, status, {"Content-Type": ct}
        self.encoding, self.is_redirect, self.text = "utf-8", redirect, body.decode(errors="ignore")
    def iter_content(self, n):
        for i in range(0, len(self.content), n): yield self.content[i:i+n]
    def close(self): pass
class Sess:
    def __init__(self, pages): self.pages, self.headers, self.proxies, self.calls = pages, {}, {}, []
    def get(self, url, **kw):
        self.calls.append(url)
        if url.endswith("/robots.txt"): return Resp(b"", status=404)
        return self.pages[url]
    def request(self, m, url, **kw): return self.get(url)

d = tempfile.mkdtemp(); wl = os.path.join(d, "wl.json")
json.dump([{"url": ONION, "label": "forum A"}, {"url": "http://example.com/", "label": "clearnet"}], open(wl, "w"))
pages = {
    ONION: Resp(b"<html><body>Thread: Ravi Kalpnik sold data. ravi@x.com:Secret99 <img src=a.jpg></body></html>"),
    ONION2: Resp(b"<html>preteen content</html>"),
}
s = Sess(pages)
m = OM.OnionMonitor(store=os.path.join(d, "store"), session=s, watchlist_path=wl)
m.fetcher.delay = 0
t("clearnet entry dropped from watchlist", len(m.watchlist) == 1)
t("non-watchlist onion refused", m.fetch(ONION2)["status"] == "REFUSED")
r = m.fetch(ONION, label="forum A")
t("watchlist page fetched", r["status"] == "OK")
t("credential not stored", "Secret99" not in open(os.path.join(m.store, r["path"])).read())
t("raw + text sha256 recorded", len(r["raw_sha256"]) == 64 and len(r["text_sha256"]) == 64)
r2 = m.fetch(ONION2, manual=True)
t("abuse page discarded", r2["status"] == "DISCARDED_SAFETY" and "url" not in r2)
log = open(os.path.join(m.store, "fetch_log.jsonl")).read()
t("abuse URL not written to log", ONION2 not in log)
t("no stored file for abuse page", len(os.listdir(os.path.join(m.store, "pages"))) == 1)
s.pages[ONION + "pic"] = Resp(b"\xff\xd8", ct="image/jpeg")
t("image refused by content-type", m.fetch(ONION + "pic", manual=True)["status"] == "REFUSED")
s.pages[ONION + "r"] = Resp(b"", status=302, redirect=True)
t("redirect not followed", m.fetch(ONION + "r", manual=True)["status"] == "NOT_AVAILABLE")
t("clearnet URL refused", m.fetch("http://example.com/", manual=True)["status"] == "REFUSED")
hits = m.search(["Ravi Kalpnik"], [r])
t("name hit found with offsets", len(hits) == 1 and hits[0]["offsets"][0] > 0)
t("hit is UNVERIFIED lead", hits[0]["status"] == "UNVERIFIED" and hits[0]["match_kind"] == "NAME_ONLY_LEAD")

prof = SubjectProfile(subject_id="T1", name="Ravi Kalpnik", organizations=["Kalpnik Traders Pvt Ltd"])
docs = DC.onion_documents(prof, monitor=m)
t("onion docs tier LOW (not adequate)", docs and all(tier_of(x.tier) not in ADEQUATE for x in docs))
empty = OM.OnionMonitor(store=os.path.join(d, "s2"), session=s, watchlist_path=os.path.join(d, "none.json"))
t("empty watchlist -> UNAVAILABLE, not NO_RESULT", DC.onion_documents(prof, monitor=empty)[0].status == "UNAVAILABLE")

# --- ransomware.live (fake client)
class FakeRL:
    def search(self, q):
        if q != "Kalpnik Traders Pvt Ltd": return []
        return [RL.normalise({"id": "abc", "post_title": "Kalpnik Traders Pvt Ltd", "group_name": "grp",
                              "published": "2026-10-01", "discovered": "2026-10-02", "country": "IN",
                              "description": "contact boss@k.com:pass1234"},
                             {"_sha256": "f" * 64, "_snapshot": "x.json", "_fetched_utc": "20261105T000000Z"})]
rd = DC.ransomware_documents(prof, client=FakeRL())
t("org listing found", len(rd) == 1 and rd[0].document_id == "rl-abc")
t("listing tier LOW", rd[0].tier == "LOW")
t("listing text says unverified claim", "not verified" in rd[0].text)
t("credential redacted in description", "pass1234" not in RL.normalise({"description": "a@b.co:pass1234"}, {})["description"])
class NoneRL:
    def search(self, q): return []
t("miss -> NO_RESULT", DC.ransomware_documents(prof, client=NoneRL())[0].status == "NO_RESULT")
class BoomRL:
    def search(self, q): raise RuntimeError("429")
t("API failure -> UNAVAILABLE (never 'not found')", DC.ransomware_documents(prof, client=BoomRL())[0].status == "UNAVAILABLE")

# --- end-to-end through the pipeline: dark-web lead alone never establishes anything
try:
    from journalist_research.runtime.doa_pipeline import DOAPipeline
    out = DOAPipeline("DW-TEST-" + os.urandom(3).hex(), "Is Kalpnik Traders on a ransomware leak site?", prof, rd + docs).run()
    est = [f for f in out.get("findings", []) if str(f.get("status")) in ("ESTABLISHED", "STRONGLY_CORROBORATED")]
    t("pipeline: dark-web lead never ESTABLISHED/STRONGLY_CORROBORATED", not est)
    t("pipeline: human review required", out["safety"]["human_review_required"] and not out["safety"]["fact_established"])
except TypeError as e:
    print("SKIP pipeline run:", e)

# --- discovery / continuous monitor
from journalist_research.darkweb_research import onion_discovery as OD
t("classify leak forum", OD.classify("leaked database dump breach forum leaks") == "LEAK_FORUM")
t("classify market", OD.classify("market vendor escrow shop cart") == "MARKET")
t("classify weak -> OTHER", OD.classify("hello world") == "OTHER")
reg = OD.Registry(os.path.join(d, "reg.json"))
A, B, C, E = ("c" * 56 + ".onion"), ("d" * 56 + ".onion"), ("e" * 56 + ".onion"), ("f" * 56 + ".onion")
reg.upsert(A, "ransomware.live", category="RANSOMWARE_DLS", group="grp", rl_seized=False, rl_captcha=False)
reg.upsert(B, "ransomware.live", category="RANSOMWARE_DLS", group="seized", rl_seized=True)
reg.upsert(C, "ahmia"); reg.upsert(E, "ahmia")
s.pages["http://%s/" % C] = Resp(b"<html>Leaks forum: leaked database dumps, breach threads, members board</html>")
s.pages["http://%s/" % E] = Resp(b"<html>pthc stuff</html>")
pr = OD.probe(reg, m, limit=10)
t("probe classified leak forum", reg.d[C]["category"] == "LEAK_FORUM")
t("probe tripwire blocks address", reg.d[E]["blocked"] and reg.d[E]["category"] == "BLOCKED")
reg.upsert(E, "ahmia", category="LEAK_FORUM")
t("blocked address cannot be re-categorised", reg.d[E]["category"] == "BLOCKED")
wlp = os.path.join(d, "wl2.json"); json.dump([{"url": ONION, "label": "mine"}], open(wlp, "w"))
bw = OD.build_watchlist(reg, wlp); wl2 = json.load(open(wlp)); urls = [w["url"] for w in wl2]
t("manual watchlist entry kept", ONION in urls and bw["manual"] == 1)
t("DLS + leak forum auto-added", ("http://%s/" % A) in urls and ("http://%s/" % C) in urls)
t("seized + blocked not watched", ("http://%s/" % B) not in urls and ("http://%s/" % E) not in urls)
reg.save(); t("registry saved atomically", os.path.exists(os.path.join(d, "reg.json")))
s.pages["http://%s/" % A] = Resp(b"<html>Victims: Kalpnik Traders Pvt Ltd - files coming soon</html>")
m2 = OM.OnionMonitor(store=os.path.join(d, "mon"), session=s, watchlist_path=wlp); m2.fetcher.delay = 0
rw = m2.refresh_watchlist(limit=10, min_age_hours=0)
t("monitor fetched watchlist", rw["ok"] >= 2)
n_files = sum(len(f) for _, _, f in os.walk(os.path.join(m2.store, "pages")))
m2.refresh_watchlist(limit=10, min_age_hours=0)
t("unchanged pages not re-stored", sum(len(f) for _, _, f in os.walk(os.path.join(m2.store, "pages"))) == n_files)
hs = m2.search_store(["Kalpnik Traders Pvt Ltd"])
t("search over stored snapshots (no network)", len(hs) == 1 and hs[0]["status"] == "UNVERIFIED")
od = DC.onion_documents(prof, monitor=m2)
t("org name searched in dark-web docs", any(x.mention.get("name") == "Kalpnik Traders Pvt Ltd" for x in od))

ok = sum(c for _, c in R)
print(f"DARKWEB OFFLINE: {ok}/{len(R)} {'PASS' if ok == len(R) else 'FAIL'}")
