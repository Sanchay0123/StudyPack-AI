"""PPTX extraction with python-pptx: slide titles, bullet levels, tables, notes, picture alt text."""
from __future__ import annotations

import zipfile

from ingestion.figures import FigureCollector
from ingestion.types import ExtractionError, ExtractionResult, RawBlock


def _table_markdown(table) -> str:
    rows = [[" ".join(cell.text.split()).replace("|", "\\|") for cell in row.cells] for row in table.rows]
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    out = ["| " + " | ".join(rows[0]) + " |", "| " + " | ".join(["---"] * width) + " |"]
    out += ["| " + " | ".join(r) + " |" for r in rows[1:]]
    return "\n".join(out)


def _iter_shapes(shapes):
    from pptx.enum.shapes import MSO_SHAPE_TYPE

    for shape in shapes:
        if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
            yield from _iter_shapes(shape.shapes)
        else:
            yield shape


def extract_pptx(path: str) -> ExtractionResult:
    try:
        from pptx import Presentation
        from pptx.enum.shapes import MSO_SHAPE_TYPE, PP_PLACEHOLDER

        prs = Presentation(path)
    except (zipfile.BadZipFile, KeyError, ValueError) as exc:
        raise ExtractionError(f"Could not open PPTX (corrupted or not a PowerPoint file): {exc}") from exc
    except Exception as exc:  # noqa: BLE001
        raise ExtractionError(f"Could not open PPTX: {exc}") from exc

    result = ExtractionResult()
    figures = FigureCollector(path)
    title_types = {PP_PLACEHOLDER.TITLE, PP_PLACEHOLDER.CENTER_TITLE}
    for index, slide in enumerate(prs.slides, start=1):
        title_shape = slide.shapes.title
        title = " ".join(title_shape.text.split()) if title_shape is not None and title_shape.has_text_frame else ""
        result.blocks.append(RawBlock(title or f"Slide {index}", "heading", slide=index, heading_level=2,
                                      confidence=1.0 if title else 0.5))
        for shape in _iter_shapes(slide.shapes):
            if title_shape is not None and shape.shape_id == title_shape.shape_id:
                continue
            if shape.is_placeholder and shape.placeholder_format.type in title_types:
                continue
            if shape.has_text_frame:
                lines = []
                for para in shape.text_frame.paragraphs:
                    text = " ".join("".join(r.text for r in para.runs).split())
                    if text:
                        lines.append(("  " * para.level) + "- " + text)
                if lines:
                    ctype = "list" if len(lines) > 1 or shape.is_placeholder else "text"
                    body = "\n".join(lines) if ctype == "list" else lines[0][2:].strip()
                    result.blocks.append(RawBlock(body, ctype, slide=index))
            elif getattr(shape, "has_table", False) and shape.has_table:
                md = _table_markdown(shape.table)
                if md:
                    result.blocks.append(RawBlock(md, "table", slide=index, confidence=0.95))
            elif shape.shape_type == MSO_SHAPE_TYPE.PICTURE:
                alt = ""
                try:
                    alt = shape._element.xpath("./p:nvPicPr/p:cNvPr")[0].get("descr", "") or ""
                except (IndexError, AttributeError):
                    pass
                marker = None
                try:
                    marker = figures.add(shape.image.blob, slide=index, caption=alt)
                except Exception:  # noqa: BLE001 - linked/unsupported pictures
                    marker = None
                if marker:
                    label = marker + (f" (alt text: {alt})" if alt else "")
                else:
                    label = f"[Image on slide {index}" + (f": {alt}]" if alt else " - content not extracted]")
                result.blocks.append(RawBlock(label, "image_ref", slide=index, confidence=0.3 if alt else 0.0, needs_review=not alt))
        if slide.has_notes_slide:
            notes = " ".join(slide.notes_slide.notes_text_frame.text.split()) if slide.notes_slide.notes_text_frame else ""
            if notes:
                result.blocks.append(RawBlock(f"Speaker notes: {notes}", "slide_notes", slide=index))
    result.metadata = {"slides": len(prs.slides), "figures": figures.figures}
    if not any(b.content_type != "heading" for b in result.blocks):
        result.warnings.append("Slides contain titles only (no body text was found).")
    return result
