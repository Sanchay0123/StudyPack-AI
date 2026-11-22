"""Figure (image) capture during extraction.

Meaningful images are saved next to the stored upload (figures/<doc-stem>_F<n>.png) and represented in the text
by a marker such as "[Figure F2 on slide 3: not yet described]". The optional vision stage (P00) later replaces the
marker with a model-generated description that is explicitly labelled as such and flagged for review.
"""
from __future__ import annotations

import io
from dataclasses import dataclass, field
from pathlib import Path

MIN_SIDE_PX = 120          # skip icons, bullets and logos
MIN_AREA_PX = 120 * 160
MAX_FIGURES_PER_DOC = 40


@dataclass
class FigureCollector:
    document_path: str
    figures: list[dict] = field(default_factory=list)
    skipped_small: int = 0

    @property
    def folder(self) -> Path:
        return Path(self.document_path).parent / "figures"

    def add(self, image_bytes: bytes, *, page: int | None = None, slide: int | None = None, caption: str = "") -> str | None:
        """Save the image (as PNG) and return its marker text, or None if it is too small / not decodable / over the cap."""
        if len(self.figures) >= MAX_FIGURES_PER_DOC:
            return None
        try:
            from PIL import Image
            with Image.open(io.BytesIO(image_bytes)) as img:
                img.load()
                width, height = img.size
                if min(width, height) < MIN_SIDE_PX or width * height < MIN_AREA_PX:
                    self.skipped_small += 1
                    return None
                figure_id = f"F{len(self.figures) + 1}"
                self.folder.mkdir(parents=True, exist_ok=True)
                target = self.folder / f"{Path(self.document_path).stem}_{figure_id}.png"
                img.convert("RGB").save(target, format="PNG")
        except Exception:  # noqa: BLE001 - undecodable/unsupported image formats are skipped
            return None
        where = f"page {page}" if page else (f"slide {slide}" if slide else "document")
        marker = f"[Figure {figure_id} on {where}: not yet described]"
        self.figures.append({"id": figure_id, "path": str(target), "page": page, "slide": slide, "caption": caption,
                             "width": width, "height": height, "marker": marker, "description": None})
        return marker
