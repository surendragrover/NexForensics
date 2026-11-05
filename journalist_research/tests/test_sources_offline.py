"""Offline tests for DOA source connectors (no network, no DB)."""
import os, tempfile, subprocess, json
from journalist_research.sources import sebi_orders as S, uk_sanctions as U
from journalist_research.sources.http_polite import looks_like_challenge
from journalist_research.extraction.pdf_text import extract_pdf_bytes

R = []
def t(name, cond): R.append((name, bool(cond))); print(("PASS" if cond else "FAIL"), name)

LIST = '''<tr><td>Nov 04, 2026</td>
  <td><a href="https://www.sebi.gov.in/enforcement/orders/nov-2026/adjudication-order-in-the-matter-of-x-ltd_105598.html"  target="_blank" title="
Adjudication Order in the matter of X Ltd   " class="points">
Adjudication Order in the matter of X &amp; Y Ltd    </a></tr>'''
o = S.parse_listing(LIST)
t("sebi listing parsed 1 row", len(o) == 1)
t("sebi order id", o and o[0].order_id == "105598")
t("sebi ISO date", o and o[0].order_date == "2026-11-04")
t("sebi title unescaped", o and o[0].title == "Adjudication Order in the matter of X & Y Ltd")
t("sebi pdf url from iframe", S.parse_pdf_url("<iframe src='https://www.sebi.gov.in/web/?file=https://www.sebi.gov.in/sebi_data/attachdocs/nov-2026/ORDER_1.pdf' width") ==
  "https://www.sebi.gov.in/sebi_data/attachdocs/nov-2026/ORDER_1.pdf")
t("sebi relative pdf url", S.parse_pdf_url("<iframe src='../../../web/?file=/sebi_data/attachdocs/1435900874990.pdf' w") ==
  "https://www.sebi.gov.in/sebi_data/attachdocs/1435900874990.pdf")
t("sebi no pdf -> None", S.parse_pdf_url("<html></html>") is None)

t("cloudflare 403 blocked", looks_like_challenge(403, b"<title>Just a moment...</title> cf-chl"))
t("plain 200 not blocked", not looks_like_challenge(200, b"<html>ok</html>"))
t("429 blocked", looks_like_challenge(429, b""))

t("non-pdf rejected", extract_pdf_bytes(b"<html>").error.startswith("not a PDF"))
# build a real PDF with pdftotext's sibling if available (ghostscript/ps2pdf) else minimal hand PDF
pdf = (b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj 2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj "
       b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>endobj "
       b"4 0 obj<</Length 120>>stream\nBT /F1 12 Tf 50 700 Td (ORDER in the matter of Ravi Kalpnik Test Limited, penalty Rs 5,00,000 imposed.) Tj ET\nendstream endobj "
       b"5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF")
ex = extract_pdf_bytes(pdf)
t("pdf text extracted", "Ravi Kalpnik" in ex.text)
t("pdf raw+text sha256", len(ex.raw_sha256) == 64 and len(ex.text_sha256) == 64)
t("pdf version stamped", ex.extractor_version == "doa-pdf-1.1")
blank = pdf.replace(b"(ORDER in the matter of Ravi Kalpnik Test Limited, penalty Rs 5,00,000 imposed.)", b"()")
eb = extract_pdf_bytes(blank)
t("blank page flagged needs_ocr", eb.ocr_status in ("NOT_AVAILABLE", "PENDING", "OCR_PARTIAL", "OCR_FAILED") and 1 in eb.scanned_pages)

# OCR: rasterise the text PDF to an image-only PDF, then expect tesseract to recover the text
import shutil
if shutil.which("tesseract") and shutil.which("pdftoppm"):
    try:
        from PIL import Image
        dd = tempfile.mkdtemp(); src = os.path.join(dd, "a.pdf"); open(src, "wb").write(pdf)
        subprocess.run(["pdftoppm", "-r", "200", "-png", "-singlefile", src, os.path.join(dd, "img")], check=True)
        out = os.path.join(dd, "scan.pdf"); Image.open(os.path.join(dd, "img.png")).convert("RGB").save(out, "PDF", resolution=200)
        eo = extract_pdf_bytes(open(out, "rb").read())
        t("OCR recovers text from image-only PDF", eo.ocr_status == "OCR_DONE" and "Kalpnik" in eo.text)
    except ImportError:
        print("SKIP OCR test (no PIL)")

# local corpus search with fixture store
d = tempfile.mkdtemp()
so = S.SebiOrders(store=d)
os.makedirs(os.path.join(d, "1"))
open(os.path.join(d, "1", "text.txt"), "w").write("page one\n\fIn the matter of RAVI  KALPNIK and others")
open(so.index_path, "w").write(json.dumps({"order_id": "1", "title": "T", "order_date": "2026-01-01",
                                            "pdf_url": "u", "raw_sha256": "x"}) + "\n")
h = so.search("Ravi Kalpnik")
t("search finds name across whitespace", len(h) == 1 and h[0]["page"] == 2)
t("search hit is lead only", h and h[0]["match_kind"] == "NAME_ONLY_LEAD")
t("search no partial word", so.search("Ravi Kalp") == [])

# text-only ingest + ajax pagination (fake fetcher, no network)
import gzip
from journalist_research.sources.http_polite import FetchResult
class FakeF:
    def __init__(self):
        import requests; self.s = requests.Session(); self.calls = []
    def _r(self, url, body):
        return FetchResult(url=url, final_url=url, status=200, content=body, content_type="", sha256="h",
                           fetched_at_utc="2026-11-05T00:00:00+00:00", headers={})
    def get(self, url, **kw):
        self.calls.append(("GET", url, None))
        if url.endswith(".pdf"): return self._r(url, pdf)
        if "_105598.html" in url:
            return self._r(url, b"<iframe src='https://www.sebi.gov.in/web/?file=https://www.sebi.gov.in/sebi_data/attachdocs/nov-2026/O.pdf' w>")
        self.s.cookies.set("JSESSIONID", "x")
        return self._r(url, (LIST + " 1 to 25 of 12,022 records").encode())
    def request(self, method, url, data=None, headers=None, **kw):
        self.calls.append((method, url, data, headers)); return self._r(url, (LIST.replace("105598", "104277")).encode())
ff = FakeF(); d2 = tempfile.mkdtemp(); so2 = S.SebiOrders(fetcher=ff, store=d2)
p0 = so2.list_page(6, 0)
t("listing page 0 parses total", p0["total"] == 12022 and len(p0["orders"]) == 1)
p1 = so2.list_page(6, 3)
t("ajax page uses POST + Referer + XHR", ff.calls[-1][0] == "POST" and ff.calls[-1][2]["nextValue"] == "3"
  and ff.calls[-1][3]["X-Requested-With"] == "XMLHttpRequest" and "smid=6" in ff.calls[-1][3]["Referer"])
t("ajax page parsed", p1["orders"] and p1["orders"][0].order_id == "104277")
oo = so2.ingest(p0["orders"][0])
t("text-only: no PDF stored", not os.path.exists(os.path.join(d2, "105598", "order.pdf")))
t("text-only: gz text stored", os.path.exists(os.path.join(d2, "105598", "text.txt.gz")) and oo.stored == "TEXT_ONLY")
t("text-only: PDF sha256 + url kept for proof", len(oo.raw_sha256) == 64 and oo.pdf_url.endswith("O.pdf") and oo.pdf_bytes == len(pdf))
t("search reads gz text", len(so2.search("Ravi Kalpnik")) == 1)
n_calls = len(ff.calls); so2.ingest(p0["orders"][0])
t("re-ingest is a no-op (append-only)", len(ff.calls) == n_calls and len(open(so2.index_path).read().strip().splitlines()) == 1)

CSV = ("Report Date: 03-Nov-2026\nLast Updated,Unique ID,OFSI Group ID,UN Reference Number,Name 6,Name 1,Name 2,Name 3,Name 4,Name 5,Name type,"
       "Regime Name,Designation Type,Sanctions Imposed,Date Designated,D.O.B,Nationality(/ies),Address Line 1,Address Country,Name non-latin script\n"
       "01/01/2026,AA0001,1,,DOE,John,,,,,Primary Name,R1,Individual,Asset freeze,02/02/2020,01/01/1970,X,Street 1,Y,\n"
       "01/01/2026,AA0001,1,,DOE,Johnny,,,,,Alias,R1,Individual,Asset freeze,02/02/2020,01/01/1970,X,Street 2,Y,\n"
       "01/01/2026,BB0002,2,,ACME,,,,,,Primary Name,R2,Entity,Asset freeze,03/03/2021,,,,Z,\n").encode()
recs = U.parse_csv(CSV)
t("uk grouped by Unique ID", set(recs) == {"AA0001", "BB0002"})
t("uk primary + alias split", recs["AA0001"]["names"] == ["John DOE"] and recs["AA0001"]["aliases"] == ["Johnny DOE"])
t("uk addresses merged", len(recs["AA0001"]["addresses"]) == 2)
t("uk report date", recs["AA0001"]["report_date"] == "03-Nov-2026")
new = dict(recs); new.pop("BB0002"); new["CC3"] = dict(recs["BB0002"], unique_id="CC3")
ch = dict(recs["AA0001"], record_sha256="changed"); new["AA0001"] = ch
df = U.diff(recs, new)
t("uk diff added/removed/changed", df == {"added": ["CC3"], "removed": ["BB0002"], "changed": ["AA0001"]})

p = sum(1 for _, ok in R if ok)
print(f"\n{p}/{len(R)} PASS")
raise SystemExit(0 if p == len(R) else 1)
