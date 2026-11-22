"""DOCX extraction with python-docx, preserving body order of paragraphs and tables."""
from __future__ import annotations

import re
import zipfile

from ingestion.types import ExtractionError, ExtractionResult, RawBlock

MONO_HINTS = ("mono", "courier", "consolas", "menlo", "code")


def _table_markdown(table) -> str:
    rows = []
    for row in table.rows:
        cells = []
        for cell in row.cells:
            cells.append(" ".join(cell.text.split()).replace("|", "\\|"))
        rows.append(cells)
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    out = ["| " + " | ".join(rows[0]) + " |", "| " + " | ".join(["---"] * width) + " |"]
    out += ["| " + " | ".join(r) + " |" for r in rows[1:]]
    return "\n".join(out)


def extract_docx(path: str) -> ExtractionResult:
    try:
        import docx
        from docx.table import Table
        from docx.text.paragraph import Paragraph

        document = docx.Document(path)
    except (zipfile.BadZipFile, KeyError, ValueError) as exc:
        raise ExtractionError(f"Could not open DOCX (corrupted or not a Word document): {exc}") from exc
    except Exception as exc:  # noqa: BLE001
        raise ExtractionError(f"Could not open DOCX: {exc}") from exc

    result = ExtractionResult()
    image_count = 0
    body = document.element.body
    for child in body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "tbl":
            md = _table_markdown(Table(child, document))
            if md.strip():
                result.blocks.append(RawBlock(md, "table", confidence=0.95))
            continue
        if tag != "p":
            continue
        para = Paragraph(child, document)
        if para._element.xpath(".//*[local-name()='drawing' or local-name()='pict']"):
            image_count += 1
            result.blocks.append(RawBlock("[Embedded image - content not extracted]", "image_ref", confidence=0.0, needs_review=True))
        text = para.text.strip()
        if not text:
            continue
        style = (para.style.name if para.style is not None else "") or ""
        style_l = style.lower()
        has_numbering = bool(para._element.xpath("./*[local-name()='pPr']/*[local-name()='numPr']"))
        fonts = {(r.font.name or "").lower() for r in para.runs if r.text.strip()}
        if style_l == "title":
            result.blocks.append(RawBlock(text, "heading", heading_level=1))
        elif style_l.startswith("heading"):
            m = re.search(r"(\d+)", style)
            result.blocks.append(RawBlock(text, "heading", heading_level=min(int(m.group(1)) if m else 2, 4)))
        elif "list" in style_l or has_numbering:
            result.blocks.append(RawBlock(f"- {text}", "list"))
        elif "code" in style_l or (fonts and all(any(h in f for h in MONO_HINTS) for f in fonts)):
            result.blocks.append(RawBlock(para.text, "code"))
        elif re.match(r"^(figure|fig\.|table)\s*\d+", text, re.I):
            result.blocks.append(RawBlock(text, "caption"))
        else:
            # Bold-only short paragraphs often act as headings in student notes.
            runs = [r for r in para.runs if r.text.strip()]
            if runs and all(r.bold for r in runs) and len(text) < 90 and not text.endswith("."):
                result.blocks.append(RawBlock(text, "heading", heading_level=3))
            else:
                result.blocks.append(RawBlock(text, "text"))

    # Merge consecutive list items / code lines.
    merged: list[RawBlock] = []
    for b in result.blocks:
        if merged and b.content_type in ("list", "code") and merged[-1].content_type == b.content_type:
            merged[-1].text += "\n" + b.text
        else:
            merged.append(b)
    result.blocks = merged
    result.metadata = {"paragraphs": len(document.paragraphs), "tables": len(document.tables), "images": image_count,
                       "title": document.core_properties.title or ""}
    if not result.blocks:
        result.warnings.append("No text found in the document.")
    return result
