"""Offline tests: lifestyle & interests extractor, social parsing (no network)."""
from journalist_research.evidence.lifestyle_interests import extract_interests, build_profile, section_text
from journalist_research.sources.public_profile import classify_account, analyse_posts

OK = FAIL = 0
def check(name, cond):
    global OK, FAIL
    print(("PASS " if cond else "FAIL ") + name)
    if cond: OK += 1
    else: FAIL += 1

N = ["Arjun Testwal"]
d1 = {"document_id": "a", "url": "https://news.example/a", "publisher": "news.example", "lineage_id": "la", "status": "OK",
      "text": "Arjun Testwal is an avid golfer and owns two racehorses at the Pune stud farm. He also bought a superyacht in 2023. "
              "The minister visited a temple. Arjun Testwal was admitted to hospital for diabetes. "
              "Testwal's son studies abroad. Arjun Testwal plays a key role in the company."}
d2 = {"document_id": "b", "url": "https://other.example/b", "publisher": "other.example", "lineage_id": "lb", "status": "OK",
      "text": "In an interview, Arjun Testwal said his passion is photography and golf."}
d3 = {"document_id": "c", "url": "https://x.example/c", "lineage_id": "lc", "status": "OK",
      "text": "Arjun Testwal, a namesake, loves casinos."}
d4 = {"document_id": "s", "url": "https://bsky.app/profile/a", "lineage_id": "ls", "status": "OK", "source_kind": "SELF",
      "mention": {"self_authored": True}, "text": "[2026-10-01] Weekend at the polo club with friends #polo\n[2026-10-02] Pray for health"}
hits = extract_interests(d1, N)
terms = {h["interest"] for h in hits}
check("golf, racehorse, yacht found", {"golf", "racehorse", "yacht"} <= terms)
check("high-cost flagged", any(h["high_cost"] for h in hits))
check("health/religion/family sentences skipped", not any(k in " ".join(h["quote"] for h in hits).lower()
                                                     for k in ("hospital", "temple", "son ")))
check("'plays a key role' is not a hobby", not any("key role" in h["quote"] for h in hits))
h2 = extract_interests(d2, N)
check("interview quote is SELF_REPORTED", h2 and all(h["basis"] == "SELF_REPORTED" for h in h2))
h4 = extract_interests(d4, N)
check("own posts read without name in text", any("polo" in h["interest"] for h in h4))
check("health post in own feed skipped", not any("health" in h["quote"].lower() for h in h4))
prof = build_profile([d1, d2, d3, d4], {"a": "SAME_SUBJECT_PROBABLE", "b": "SAME_SUBJECT_PROBABLE",
                                        "c": "NAMESAKE_REJECTED", "s": "SAME_SUBJECT_PROBABLE"}, N)
items = {i["interest"]: i for i in prof["items"]}
check("golf corroborated by 2 independent sources", any(i["status"] == "CORROBORATED" for k, i in items.items() if k.startswith("golf")))
check("namesake casino excluded", not any("casino" in k for k in items))
check("income comparison path suggested", prof["next_paths"] and "declared income" in prof["next_paths"][0])
check("fact never established", prof["fact_established"] is False)
prof2 = build_profile([d3], {"c": "UNRESOLVED"}, N)
check("name-only doc gives a LEAD", prof2["items"] and prof2["items"][0]["status"] == "NAME_ONLY_LEAD")
check("section text lists exclusions", "Excluded by design" in section_text(prof))
check("bluesky url", classify_account("https://bsky.app/profile/a.bsky.social")["platform"] == "Bluesky")
check("bare bluesky handle", classify_account("a.bsky.social")["platform"] == "Bluesky")
check("mastodon url", classify_account("https://mastodon.social/@x")["platform"] == "Mastodon")
check("telegram url", classify_account("https://t.me/somechannel")["url"] == "https://t.me/s/somechannel")
check("x is walled", classify_account("https://x.com/someone").get("walled") == "1")
check("instagram is walled", classify_account("https://www.instagram.com/someone/").get("walled") == "1")
check("plain link", classify_account("https://example.org/profile")["platform"] == "link")
a = analyse_posts([{"date": "2026-10-01", "text": "#polo with @friend.bsky https://www.example.com/x"},
                   {"date": "2026-10-05", "text": "#polo again"}])
check("post analysis", a["posts_analysed"] == 2 and a["top_hashtags"][0] == ("polo", 2) and a["first_post"] == "2026-10-01"
      and a["top_link_domains"][0][0] == "example.com")
print(f"\n{OK}/{OK + FAIL} PASS")
raise SystemExit(1 if FAIL else 0)
