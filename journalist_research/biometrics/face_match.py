"""
Face comparison for DOA (2026-11-06): the subject's photo vs faces in investigator-uploaded files.

Scope: only files the investigator uploads for this case (images, PDF pages, images inside .docx).
No web or social-media face search. A similarity score is a LEAD for human review: it does not
establish identity, and the pipeline never uses it as an identity anchor.

Models (free, Apache-2.0, opencv_zoo, in models/face_detect/):
  detector   YuNet  face_detection_yunet_2023mar.onnx
  recogniser SFace  face_recognition_sface_2021dec.onnx (aligned 112x112, 128-d, cosine)
OpenCV documents cosine >= 0.363 as "same identity" for SFace. The app's own ArcFace model
(models/face, arcface_v3) was tested on 2026-11-06 and could not separate different people
(cosine 0.84-0.94 for different people vs 0.92 for the same person), so it is not used here.
"""
from __future__ import annotations

import io
import os
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Dict, Iterator, List, Tuple

import numpy as np

APP = Path(__file__).resolve().parents[2]
MD = APP / "models" / "face_detect"
YUNET = MD / "face_detection_yunet_2023mar.onnx"
SFACE = MD / "face_recognition_sface_2021dec.onnx"
SAME_ID = 0.363            # OpenCV's documented SFace cosine threshold
STRONG = 0.50              # provisional higher band
IMG_EXT = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp", ".bmp"}
MAX_PDF_PAGES = 15
MAX_FACES = 80
MAX_SIDE = 1280
_REC = None


def _rec():
    global _REC
    import cv2
    if _REC is None and SFACE.exists() and hasattr(cv2, "FaceRecognizerSF"):
        _REC = cv2.FaceRecognizerSF.create(str(SFACE), "")
    return _REC


def _detect(bgr):
    import cv2
    h, w = bgr.shape[:2]
    sc = min(1.0, MAX_SIDE / float(max(h, w)))
    img = cv2.resize(bgr, (int(w * sc), int(h * sc))) if sc < 1.0 else bgr
    det = cv2.FaceDetectorYN.create(str(YUNET), "", (img.shape[1], img.shape[0]), 0.8, 0.3, 5000)
    det.setInputSize((img.shape[1], img.shape[0]))
    _, faces = det.detect(img)
    faces = [] if faces is None else sorted(faces, key=lambda f: -f[2] * f[3])[:12]
    return img, [f for f in faces if f[2] >= 32 and f[3] >= 32]


def _features(pil) -> List[Tuple[Tuple[int, int, int, int], np.ndarray]]:
    import cv2
    bgr = cv2.cvtColor(np.array(pil.convert("RGB")), cv2.COLOR_RGB2BGR)
    img, faces = _detect(bgr)
    rec, out = _rec(), []
    for f in faces:
        feat = rec.feature(rec.alignCrop(img, f))
        out.append((tuple(int(v) for v in f[:4]), feat))
    return out


def _images_from_file(path: str) -> Iterator[Tuple[str, Any]]:
    from PIL import Image
    ext = os.path.splitext(path)[1].lower()
    if ext in IMG_EXT:
        yield "image", Image.open(path)
    elif ext == ".pdf":
        d = tempfile.mkdtemp(prefix="doa_face_")
        subprocess.run(["pdftoppm", "-r", "110", "-l", str(MAX_PDF_PAGES), "-png", path, os.path.join(d, "p")],
                       capture_output=True, timeout=180)
        for f in sorted(os.listdir(d)):
            yield f"page {int(f.rsplit('-', 1)[-1].split('.')[0])}", Image.open(os.path.join(d, f))
    elif ext == ".docx":
        with zipfile.ZipFile(path) as z:
            for n in z.namelist():
                if n.startswith("word/media/") and os.path.splitext(n)[1].lower() in IMG_EXT:
                    yield os.path.basename(n), Image.open(io.BytesIO(z.read(n)))


def band(sim: float) -> str:
    if sim >= STRONG:
        return "STRONG SIMILARITY (lead)"
    if sim >= SAME_ID:
        return "POSSIBLE MATCH (lead)"
    return "NOT SIMILAR"


def compare(subject_photo, files) -> Dict[str, Any]:
    import cv2
    res: Dict[str, Any] = {"status": "NOT_ASSESSED", "reason": "", "matches": [], "faces_checked": 0,
                           "model": "YuNet + SFace (OpenCV, Apache-2.0)", "calibrated": False,
                           "thresholds": {"possible": SAME_ID, "strong": STRONG}, "notes": []}
    if not subject_photo:
        res["reason"] = "No subject photo uploaded."
        return res
    if not (YUNET.exists() and _rec() is not None):
        res["reason"] = "Face models not installed."
        return res
    from PIL import Image
    try:
        sub = _features(Image.open(subject_photo))
    except Exception as e:  # noqa: BLE001
        res["reason"] = f"Subject photo could not be read ({type(e).__name__})."
        return res
    if not sub:
        res["reason"] = "No face found in the subject photo."
        return res
    if len(sub) > 1:
        res["notes"].append(f"{len(sub)} faces in the subject photo; the largest was used.")
    ref = sub[0][1]
    rec = _rec()
    images = [p for p in (files or []) if os.path.splitext(str(p))[1].lower() in IMG_EXT | {".pdf", ".docx"}]
    if not images:
        res["reason"] = "No uploaded image, PDF or Word file to compare against."
        return res
    for p in images:
        name = os.path.basename(str(p))
        try:
            for where, img in _images_from_file(str(p)):
                for i, (box, feat) in enumerate(_features(img), 1):
                    if res["faces_checked"] >= MAX_FACES:
                        break
                    sim = float(rec.match(ref, feat, cv2.FaceRecognizerSF_FR_COSINE))
                    res["faces_checked"] += 1
                    res["matches"].append({"file": name, "where": where, "face": i, "box": box,
                                           "similarity": round(sim, 3), "band": band(sim)})
        except Exception as e:  # noqa: BLE001
            res["notes"].append(f"{name}: could not be scanned for faces ({type(e).__name__}).")
    res["matches"].sort(key=lambda m: -m["similarity"])
    res["status"] = "ASSESSED"
    if not res["faces_checked"]:
        res["reason"] = "No face found in the uploaded files."
    return res
