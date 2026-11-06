"""Offline tests for engines/hybrid_rules.py (no model, no network).
Run: cd /home/nexforensics/app && venv/bin/python -m tests_hybrid.test_hybrid_rules  (or python file directly)
"""
import sys, pathlib
APP = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))
from engines.hybrid_rules import HybridRules, verhoeff_ok

R = HybridRules(APP / "models" / "hybrid_rules")
ok = fail = 0

def check(name, cond):
    global ok, fail
    if cond:
        ok += 1
    else:
        fail += 1
        print("FAIL", name)

check("version 4", R.version.startswith("4"))

t1 = ("Ramesh Kumar of Lucknow transferred Rs 4.5 lakh via UPI ramesh@okicici to account 50100234567890 "
      "at HDFC Bank (IFSC HDFC0001234); call him on +91 98765 43210 or mail rk@gmail.com.")
model1 = {"PER": ["of", "to", "Ramesh Kumar"], "EMAIL": ["mail"], "HASH": ["4.5"], "BANK": ["account"], "ORG": ["HDFC Bank"]}
e, p = R.apply(t1, model1)
check("PER->PERSON keeps real name", e.get("PERSON") == ["Ramesh Kumar"])
check("no PER key", "PER" not in e)
check("model junk EMAIL dropped", "mail" not in e.get("EMAIL", []))
check("email found", "rk@gmail.com" in e.get("EMAIL", []))
check("upi found", "ramesh@okicici" in e.get("UPI", []))
check("upi not email", "ramesh@okicici" not in e.get("EMAIL", []))
check("phone found", any("98765" in x for x in e.get("PHONE", [])))
check("account found", "50100234567890" in e.get("ACCOUNT", []))
check("ifsc found", "HDFC0001234" in e.get("IFSC", []))
check("money found", any("4.5 lakh" in x for x in e.get("MONEY", [])))
check("bad HASH 4.5 dropped", "4.5" not in e.get("HASH", []))
check("BANK 'account' dropped", "account" not in e.get("BANK", []))
check("ORG kept from model", e.get("ORG") == ["HDFC Bank"] and p["ORG"]["HDFC Bank"] == "MODEL")
check("LOC Lucknow from gazetteer", "Lucknow" in e.get("LOC", []))

t2 = "Police seized a pistol, 2 kg heroin and a Scorpio car DL3CAB1234 near Karachi after he threatened to kill the trader."
e, p = R.apply(t2, {"PER": ["Police", "a"]})
check("weapon", "pistol" in [x.lower() for x in e.get("WEAPON", [])])
check("drug", "heroin" in [x.lower() for x in e.get("DRUG", [])])
check("vehicle", "DL3CAB1234" in e.get("VEHICLE", []))
check("threat", any("threaten" in x.lower() for x in e.get("THREAT", [])))
check("lowercase 'a' not a person", "a" not in e.get("PERSON", []))
check("score weapon+drug+threat", R.score(e) == 12 + 8 + 8)

t3 = "रमेश ने 5 लाख रुपये की रिश्वत ली और पिस्तौल से धमकी दी। हवाला के ज़रिए पैसा दुबई भेजा गया।"
e, p = R.apply(t3, {})
check("hindi crime rishwat", "रिश्वत" in e.get("CRIME", []))
check("hindi hawala", "हवाला" in e.get("CRIME", []))
check("hindi weapon", "पिस्तौल" in e.get("WEAPON", []))
check("hindi threat", "धमकी" in e.get("THREAT", []))
check("hindi money", any("लाख" in x for x in e.get("MONEY", [])))

t4 = "Meeting notes: the board discussed quarterly results with Anil Shah in Mumbai on 12 March 2025."
e, p = R.apply(t4, {"PER": ["Anil Shah"]})
check("clean text score 0", R.score(e) == 0)
check("date", any("12 March 2025" in x for x in e.get("DATE", [])))

# validity checks
check("verhoeff valid 234123412346", verhoeff_ok("234123412346"))
check("verhoeff invalid", not verhoeff_ok("234123412345"))
e, _ = R.apply("Aadhaar 2341 2341 2346 and wrong 2341 2341 2345", {})
check("aadhaar only valid", e.get("AADHAAR") == ["2341 2341 2346"])
e, _ = R.apply("PAN ABCPK1234F, IP 10.0.0.256 and 192.168.1.20, url https://example.com/x.", {})
check("pan", e.get("PAN") == ["ABCPK1234F"])
check("ip valid only", e.get("IP") == ["192.168.1.20"])
check("url trailing dot", e.get("URL") == ["https://example.com/x"])
e, _ = R.apply("The order no 123456789012 was shipped.", {})
check("12-digit without account context not ACCOUNT", "ACCOUNT" not in e)
e, _ = R.apply("Wallet 0x52908400098527886E0F7030069857D2E4169EE7 got funds", {})
check("eth wallet", "CRYPTO_WALLET" in e)
e, _ = R.apply("Gunjan went to Agra", {})
check("no 'gun' inside Gunjan", "WEAPON" not in e)
e, _ = R.apply("pistol pistol PISTOL", {"WEAPON": ["pistol"]})
check("dedupe", len(e["WEAPON"]) == 1 and R.score(e) == 12)

e, p = R.apply("Vijay Mallya, chairman of United Breweries Ltd, owed Rs 9,000 crore to SBI. Shri Ram Lal s/o Mohan Das met Dr. Anita Rao at HDFC Bank on 2 March 2016.", {"DATE": ["March"]})
check("org suffix", "United Breweries Ltd" in e.get("ORG", []))
check("bank acronym", "SBI" in e.get("BANK", []))
check("bank suffix", "HDFC Bank" in e.get("BANK", []))
check("honorific person", {"Ram Lal", "Mohan Das", "Anita Rao"} <= set(e.get("PERSON", [])))
check("fragment March dropped", e.get("DATE") == ["2 March 2016"] and p["DATE"]["2 March 2016"] == "BOTH")
print(f"hybrid rules: {ok}/{ok+fail} PASS")
sys.exit(1 if fail else 0)
