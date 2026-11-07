"""
analysis/evidence_meta.py — file-level evidence intake helpers: normalizing
uploaded file objects, hashing, image-quality assessment, EXIF extraction,
and audio/document metadata probing.

librosa / fitz (PyMuPDF) / PIL imports are LOCAL (inside the functions
that need them, as in the original file) so this module has no heavy
import cost unless those specific evidence types are actually present.

Extracted from gradio_app.py, verbatim (no behavior change).
"""

import os
import hashlib


def _normalize_uploaded_files(files):
    """Normalizes whatever gr.File(file_count='multiple') hands back — a
    list of filepath strings, tempfile-like objects with a `.name`
    attribute, or (depending on Gradio version) a single value instead of
    a list — into a clean list[str] of filepaths that actually exist on
    disk. Returns [] if nothing was uploaded, so every downstream truthy
    check (`if id_doc:`) keeps working unchanged.
    """
    if not files:
        return []
    if not isinstance(files, list):
        files = [files]
    paths = []
    for f in files:
        if f is None:
            continue
        p = getattr(f, "name", f)
        if isinstance(p, str) and os.path.exists(p):
            paths.append(p)
    return paths


def _sha256_file(path):
    if not path or not os.path.exists(path):
        return "N/A — evidence not provided"
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception as e:
        return f"Hash Error: {e}"


def _assess_image_quality(pil_img):
    """
    Lightweight input-quality read for a photo, based on resolution —
    used to caveat Deepfake/CCTV classification results so a 100%-confidence
    reading on a small/compressed image doesn't get mistaken for a strong
    finding. Returns (quality_label, note) or None if no image.
    """
    if pil_img is None:
        return None
    try:
        w, h = pil_img.width, pil_img.height
        pixels = w * h
        if pixels < 40000:       # smaller than ~200x200
            return "Poor", f"Low resolution ({w}×{h}px) — classifier reliability reduced, treat scores with caution"
        elif pixels < 250000:    # smaller than ~500x500
            return "Average", f"Moderate resolution ({w}×{h}px)"
        else:
            return "Good", f"Adequate resolution ({w}×{h}px)"
    except Exception:
        return None


def _extract_exif(pil_img):
    if pil_img is None:
        return {}
    try:
        info = {}
        if hasattr(pil_img, "_getexif") and pil_img._getexif():
            exif = pil_img._getexif()
            tag_map = {
                271: "Camera_Make", 272: "Camera_Model", 306: "DateTime_Modified",
                36867: "DateTime_Original", 34853: "GPS_Info",
                2: "GPS_Latitude", 4: "GPS_Longitude",
            }
            for tag, name in tag_map.items():
                if tag in exif:
                    info[name] = str(exif[tag])
        info["Image_Size"] = f"{pil_img.width}x{pil_img.height}"
        info["Color_Mode"] = pil_img.mode
        # BUG FIX (2026-08-20 — Medium): PIL's .format is genuinely None
        # (not missing) once an image has been re-saved/re-wrapped (e.g.
        # after cv2/numpy processing), so `hasattr(...) else "Unknown"`
        # never triggered — the attribute existed, its value was just
        # None. Check the value itself, not just attribute presence.
        _fmt = getattr(pil_img, 'format', None)
        info["File_Format"] = _fmt if _fmt else "Unknown (processed image, original format not retained)"
        return info
    except Exception:
        return {"Note": "EXIF extraction failed"}


def _get_audio_evidence_meta(audio_path):
    if not audio_path or not os.path.exists(audio_path):
        return {}
    try:
        import librosa
        y, sr = librosa.load(audio_path, sr=None, mono=True, duration=0.5)
        duration = librosa.get_duration(path=audio_path)
        return {
            "Duration_sec": round(duration, 2),
            "SampleRate_Hz": sr,
            "Channels": "Mono" if len(y.shape) == 1 else "Stereo",
            "FileSize_MB": round(os.path.getsize(audio_path) / (1024*1024), 2),
        }
    except Exception as e:
        return {"Error": str(e)}


def _get_document_evidence_meta(file_paths):
    """Builds metadata for one or more uploaded ID/document files — each
    can be an image (jpg/png/…) or a PDF. `file_paths` should already be
    a clean list[str] (see `_normalize_uploaded_files`)."""
    if not file_paths:
        return {}
    metas = []
    for p in file_paths:
        try:
            if not p or not os.path.exists(p):
                continue
            size_mb = round(os.path.getsize(p) / (1024 * 1024), 3)
            ext = os.path.splitext(p)[1].lower()
            if ext == ".pdf":
                page_count = "Unknown"
                try:
                    import fitz  # PyMuPDF
                    with fitz.open(p) as _doc:
                        page_count = len(_doc)
                except Exception:
                    pass
                metas.append({
                    "File": os.path.basename(p), "Type": "PDF",
                    "Pages": page_count, "FileSize_MB": size_mb,
                })
            else:
                from PIL import Image as _PILImage
                with _PILImage.open(p) as img:
                    metas.append({
                        "File": os.path.basename(p), "Type": "Image",
                        "Document_Size": f"{img.width}x{img.height}",
                        "DPI_Estimate": "300" if img.width > 2000 else "150",
                        "Color_Mode": img.mode,
                        "FileSize_MB": size_mb,
                    })
        except Exception:
            metas.append({"File": os.path.basename(p) if p else "?", "Note": "Metadata extraction failed"})
    return {"Files_Count": len(metas), "Files": metas}
