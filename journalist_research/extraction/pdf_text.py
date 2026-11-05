"""
PDF text extraction for court / regulator orders.

Order of engines: poppler `pdftotext -layout` (per page) -> PyPDF2 fallback.
Scanned pages (too little text) are flagged needs_ocr; OCR is NOT_AVAILABLE
on this server until tesseract is installed (needs owner approval).
Raw-PDF and text SHA-256 are both recorded; nothing is overwritten.
"""
from __future__ import annotations
import hashlib, shutil, subprocess, tempfile, os
from dataclasses import dataclass, field, asdict
from typing import List

EXTRACTOR_VERSION = "doa-pdf-1.1"
MIN_CHARS_PER_PAGE = 40


@dataclass
class PdfExtraction:
    raw_sha256: str
    text_sha256: str
    pages: List[str]
    page_count: int
    engine: str
    scanned_pages: List[int] = field(default_factory=list)
    needs_ocr: bool = False
    ocr_status: str = "NOT_ASSESSED"
    extractor_version: str = EXTRACTOR_VERSION
    error: str = ""

    @property
    def text(self) -> str:
        return "\n\f".join(self.pages)

    def to_dict(self):
        d = asdict(self); d.pop("pages"); return d


def _pdftotext(path: str) -> List[str]:
    out = subprocess.run(["pdftotext", "-layout", "-enc", "UTF-8", path, "-"],
                         capture_output=True, timeout=120)
    if out.returncode != 0:
        raise RuntimeError(out.stderr.decode(errors="replace")[:300])
    pages = out.stdout.decode("utf-8", errors="replace").split("\f")
    if pages and not pages[-1].strip():
        pages = pages[:-1]
    return pages


def _pypdf2(path: str) -> List[str]:
    import PyPDF2
    r = PyPDF2.PdfReader(path)
    return [(p.extract_text() or "") for p in r.pages]


def _ocr_pages(path: str, page_numbers: List[int], lang: str = "eng+hin") -> dict:
    """OCR selected 1-based pages with pdftoppm + tesseract. Returns {page: text}."""
    out = {}
    with tempfile.TemporaryDirectory() as d:
        for p in page_numbers[:200]:
            base = os.path.join(d, f"p{p}")
            subprocess.run(["pdftoppm", "-r", "200", "-f", str(p), "-l", str(p), "-png", "-singlefile", path, base],
                           capture_output=True, timeout=120, check=True)
            # 2-CPU server shared with the live app: one OMP thread, lowest priority
            r = subprocess.run(["nice", "-n", "19", "tesseract", base + ".png", "-", "-l", lang],
                               capture_output=True, timeout=180,
                               env=dict(os.environ, OMP_THREAD_LIMIT="1"))
            out[p] = r.stdout.decode("utf-8", errors="replace")
    return out


def extract_pdf_bytes(data: bytes, ocr: bool = True) -> PdfExtraction:
    raw = hashlib.sha256(data).hexdigest()
    if not data.startswith(b"%PDF"):
        return PdfExtraction(raw, "", [], 0, "none", error="not a PDF (missing %PDF header)")
    fd, path = tempfile.mkstemp(suffix=".pdf")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        pages, engine, err = [], "", ""
        if shutil.which("pdftotext"):
            try:
                pages, engine = _pdftotext(path), "pdftotext"
            except Exception as e:
                err = f"pdftotext: {e}"
        if not pages:
            try:
                pages, engine = _pypdf2(path), "PyPDF2"
            except Exception as e:
                err += f" PyPDF2: {e}"
        scanned = [i + 1 for i, p in enumerate(pages) if len(p.strip()) < MIN_CHARS_PER_PAGE]
        needs_ocr = bool(pages) and len(scanned) >= max(1, len(pages) // 2)
        ocr_status = "NOT_AVAILABLE" if (scanned and not shutil.which("tesseract")) else (
            "PENDING" if scanned else "NOT_NEEDED")
        if scanned and ocr and shutil.which("tesseract") and shutil.which("pdftoppm"):
            try:
                got = _ocr_pages(path, scanned)
                for p, t in got.items():
                    if len(t.strip()) >= MIN_CHARS_PER_PAGE:
                        pages[p - 1] = t
                still = [p for p in scanned if len(pages[p - 1].strip()) < MIN_CHARS_PER_PAGE]
                ocr_status = "OCR_DONE" if not still else "OCR_PARTIAL"
                engine = (engine or "none") + "+tesseract"
                needs_ocr = False if not still else len(still) >= max(1, len(pages) // 2)
            except Exception as e:
                ocr_status, err = "OCR_FAILED", (err + f" ocr: {e}").strip()
        text = "\n\f".join(pages)
        return PdfExtraction(raw, hashlib.sha256(text.encode()).hexdigest(), pages, len(pages),
                             engine or "none", scanned, needs_ocr, ocr_status, error=err.strip())
    finally:
        os.unlink(path)
