"""Render LaTeX maths ($...$) to images for the PDF using matplotlib's mathtext (no LaTeX install needed).

mathtext supports a large TeX subset (fractions, powers, roots, Greek, sums, integrals...). Anything it cannot
parse returns None and the exporter keeps the expression as monospace text, so content is never dropped.
"""
from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path

from config.settings import get_settings

DPI = 300


def _cache_dir() -> Path:
    path = get_settings().generated_dir / "_math"
    path.mkdir(parents=True, exist_ok=True)
    return path


@lru_cache(maxsize=2048)
def render_math(expr: str, font_size: float = 10.0) -> tuple[str, float, float] | None:
    """Return (png_path, width_pt, height_pt) for a TeX expression, or None if mathtext cannot render it."""
    expr = expr.strip()
    if not expr or len(expr) > 400:
        return None
    try:
        import matplotlib
        matplotlib.use("Agg")
        from matplotlib import mathtext
        from matplotlib.font_manager import FontProperties
        from PIL import Image
    except ImportError:
        return None
    key = hashlib.sha1(f"{expr}|{font_size}".encode("utf-8")).hexdigest()[:16]
    target = _cache_dir() / f"{key}.png"
    if not target.exists():
        try:
            mathtext.math_to_image(f"${expr}$", str(target), prop=FontProperties(size=font_size), dpi=DPI, format="png")
        except Exception:  # noqa: BLE001 - unsupported TeX: caller falls back to text
            target.unlink(missing_ok=True)
            return None
    with Image.open(target) as img:
        width_px, height_px = img.size
    return str(target), width_px * 72 / DPI, height_px * 72 / DPI
