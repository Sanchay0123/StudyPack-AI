"""Optional OCR via Tesseract (pytesseract). Degrades gracefully if missing."""
from __future__ import annotations

import shutil
from functools import lru_cache
from pathlib import Path

from config.settings import PROJECT_ROOT, get_settings


@lru_cache(maxsize=1)
def tesseract_path() -> str | None:
    settings = get_settings()
    candidates = [settings.tesseract_cmd] if settings.tesseract_cmd else []
    candidates += [str(PROJECT_ROOT / "tools" / "tesseract" / "tesseract.exe"), shutil.which("tesseract") or ""]
    for c in candidates:
        if c and Path(c).exists():
            return c
    return None


def ocr_available() -> bool:
    if not get_settings().ocr_enabled:
        return False
    try:
        import pytesseract  # noqa: F401
    except ImportError:
        return False
    return tesseract_path() is not None


def ocr_image(image) -> tuple[str, float]:
    """Return (text, confidence 0..1) for a PIL image."""
    import os

    import pytesseract

    exe = tesseract_path()
    pytesseract.pytesseract.tesseract_cmd = exe
    # A portable (unpacked) Tesseract keeps its language data next to the executable.
    tessdata = Path(exe).parent / "tessdata"
    if tessdata.is_dir() and not os.environ.get("TESSDATA_PREFIX"):
        os.environ["TESSDATA_PREFIX"] = str(tessdata)
    data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)
    confs = [float(c) for c, w in zip(data["conf"], data["text"]) if w.strip() and float(c) >= 0]
    text = pytesseract.image_to_string(image)
    confidence = (sum(confs) / len(confs) / 100.0) if confs else 0.0
    return text, confidence
