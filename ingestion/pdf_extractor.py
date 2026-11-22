"""PDF extraction with PyMuPDF: headings (by font size), lists, tables, code,
equations, captions; scanned-page detection and optional OCR."""
from __future__ import annotations

import re
import statistics
from collections import Counter

from ingestion.ocr_processor import ocr_available, ocr_image
from ingestion.types import ExtractionError, ExtractionResult, RawBlock

BULLET_RE = re.compile(r"^\s*([•▪●◦‣⁃∙\-\*·]|\(?\d{1,2}[.)]|\(?[a-zA-Z][.)])\s+")
CAPTION_RE = re.compile(r"^\s*(fig(ure)?\.?|table|diagram|chart)\s*\d+", re.I)
MATH_CHARS = set("=∑∫√∂∆πθλμσΣΩ≤≥≠≈±×÷^∞→⇒∈∀∃")
MONO_HINTS = ("mono", "courier", "consolas", "menlo", "inconsolata", "code")
MIN_TEXT_CHARS_PER_PAGE = 25


def _is_marker(text: str) -> bool:
    """A line that is only a bullet/number marker or unmappable glyphs (no real words)."""
    stripped = text.replace("�", "").strip()
    if not stripped:
        return True
    return len(stripped) <= 3 and not any(ch.isalpha() for ch in stripped) and not stripped.rstrip(".)").isdigit()


def _classify_line(text: str, size: float, body: float, bold: bool, mono: bool) -> tuple[str, int | None]:
    stripped = text.strip()
    if mono:
        return "code", None
    if sum(ch.isalpha() for ch in stripped) < 3:
        return "text", None
    if stripped.startswith("- "):
        return "list", None
    if size >= body * 1.45 and len(stripped) < 120:
        return "heading", 1
    if size >= body * 1.18 and len(stripped) < 120:
        return "heading", 2
    if bold and len(stripped) < 80 and not stripped.endswith((".", ",", ";")) and len(stripped.split()) <= 12:
        return "heading", 3
    if CAPTION_RE.match(stripped):
        return "caption", None
    if BULLET_RE.match(stripped):
        return "list", None
    math_count = sum(1 for ch in stripped if ch in MATH_CHARS)
    if math_count >= 2 and math_count / max(len(stripped), 1) > 0.04 and len(stripped) < 160:
        return "equation", None
    return "text", None


def _table_to_markdown(rows: list[list]) -> str:
    rows = [["" if c is None else str(c).replace("\n", " ").strip() for c in r] for r in rows if r]
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    lines = ["| " + " | ".join(rows[0]) + " |", "| " + " | ".join(["---"] * width) + " |"]
    lines += ["| " + " | ".join(r) + " |" for r in rows[1:]]
    return "\n".join(lines)


def _in_any(bbox, rects) -> bool:
    x0, y0, x1, y1 = bbox
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    return any(r[0] <= cx <= r[2] and r[1] <= cy <= r[3] for r in rects)


def extract_pdf(path: str, use_ocr: bool = False) -> ExtractionResult:
    import pymupdf as fitz  # PyMuPDF

    try:
        doc = fitz.open(path)
    except Exception as exc:  # noqa: BLE001 - PyMuPDF raises various types
        raise ExtractionError(f"Could not open PDF (corrupted or unsupported): {exc}") from exc
    if doc.needs_pass:
        raise ExtractionError("The PDF is password-protected; remove the password and upload again.")

    result = ExtractionResult(metadata={"pages": doc.page_count, "title": (doc.metadata or {}).get("title") or ""})
    pages_spans: list[list[tuple]] = []
    sizes: Counter = Counter()
    scanned_pages: list[int] = []
    table_rects_per_page: list[list] = []
    tables_per_page: list[list[tuple]] = []

    for page_index in range(doc.page_count):
        page = doc[page_index]
        try:
            data = page.get_text("dict")
        except Exception as exc:  # noqa: BLE001
            result.warnings.append(f"Page {page_index + 1}: text extraction failed ({exc}); marked for review.")
            pages_spans.append([])
            table_rects_per_page.append([])
            tables_per_page.append([])
            continue
        # Tables first, so their text is not duplicated as paragraphs.
        rects, tables = [], []
        try:
            # find_tables() costs ~2 s/page; only run it where ruling lines/boxes exist (ruled tables).
            ruled = sum(1 for d in page.get_drawings() for item in d.get("items", []) if item[0] in ("l", "re"))
            candidates = page.find_tables().tables if ruled >= 4 else []
            for t in candidates:
                md = _table_to_markdown(t.extract())
                if md and len(t.extract()) >= 2:
                    rects.append(tuple(t.bbox))
                    tables.append((t.bbox[1], md))
        except Exception:  # noqa: BLE001 - table detection is best-effort
            pass
        table_rects_per_page.append(rects)
        tables_per_page.append(tables)

        lines = []
        page_chars = 0
        for block in data.get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                spans = [s for s in line.get("spans", []) if s.get("text", "").strip()]
                if not spans:
                    continue
                text = "".join(s["text"] for s in line["spans"]).strip()
                size = max(s["size"] for s in spans)
                bold = all(("bold" in s["font"].lower()) or (s["flags"] & 16) for s in spans)
                mono = all(any(h in s["font"].lower() for h in MONO_HINTS) for s in spans)
                lines.append((line["bbox"], text, size, bold, mono))
                if not _is_marker(text):
                    sizes[round(size, 1)] += len(text)
                    page_chars += len(text)
        pages_spans.append(lines)
        if page_chars < MIN_TEXT_CHARS_PER_PAGE and page.get_images():
            scanned_pages.append(page_index)

    body = sizes.most_common(1)[0][0] if sizes else 11.0

    for page_index, lines in enumerate(pages_spans):
        page_no = page_index + 1
        items: list[tuple[float, RawBlock]] = []
        pending_marker = False
        # Reading order: top-to-bottom, then left-to-right within a line.
        for bbox, text, size, bold, mono in sorted(lines, key=lambda ln: (round(ln[0][1] / 3), ln[0][0])):
            if _in_any(bbox, table_rects_per_page[page_index]):
                continue
            if _is_marker(text):
                # Bullet glyph drawn separately (often an unmappable symbol-font glyph).
                pending_marker = True
                continue
            if pending_marker:
                text = "- " + text.replace("�", "").strip()
                pending_marker = False
            ctype, level = _classify_line(text, size, body, bold, mono)
            needs_review = "�" in text
            conf = 0.6 if needs_review else (0.8 if ctype == "equation" else 1.0)
            items.append((bbox[1], RawBlock(text, ctype, page=page_no, heading_level=level, confidence=conf,
                                            needs_review=needs_review or ctype == "equation")))
        for y, md in tables_per_page[page_index]:
            items.append((y, RawBlock(md, "table", page=page_no, confidence=0.85)))
        items.sort(key=lambda it: it[0])
        result.blocks.extend(_merge_lines([b for _, b in items]))

        page = doc[page_index]
        try:
            area = page.rect.width * page.rect.height
            big_images = [img for img in page.get_image_info() if
                          (img["bbox"][2] - img["bbox"][0]) * (img["bbox"][3] - img["bbox"][1]) > 0.08 * area]
        except Exception:  # noqa: BLE001
            big_images = []
        if big_images and page_index not in scanned_pages:
            result.blocks.append(RawBlock(
                f"[Figure on page {page_no}: {len(big_images)} image(s) not extracted - see original document]",
                "image_ref", page=page_no, confidence=0.0, needs_review=True))

    if scanned_pages:
        result.metadata["scanned_pages"] = [p + 1 for p in scanned_pages]
        ratio = len(scanned_pages) / max(doc.page_count, 1)
        if use_ocr and ocr_available():
            _apply_ocr(doc, scanned_pages, result)
        else:
            result.needs_ocr = ratio >= 0.3 or result.text_chars < 200
            msg = f"{len(scanned_pages)} page(s) look scanned (no text layer): {result.metadata['scanned_pages'][:10]}"
            if not ocr_available():
                msg += ". OCR is not available (Tesseract not installed); these pages were not extracted."
            else:
                msg += ". Re-run extraction with OCR enabled to read them."
            result.warnings.append(msg)
    doc.close()
    return result


def _merge_lines(blocks: list[RawBlock]) -> list[RawBlock]:
    """Merge consecutive lines of the same type into paragraphs / list items."""
    merged: list[RawBlock] = []
    for b in blocks:
        prev = merged[-1] if merged else None
        if prev and prev.page == b.page and prev.content_type == b.content_type:
            if b.content_type == "text":
                joiner = "" if prev.text.endswith("-") else " "
                prev.text = (prev.text[:-1] if joiner == "" else prev.text) + joiner + b.text
                continue
            if b.content_type == "code":
                prev.text += "\n" + b.text
                continue
            if b.content_type == "list":
                if BULLET_RE.match(b.text):
                    prev.text += "\n" + b.text
                else:
                    prev.text += " " + b.text  # wrapped continuation of a bullet
                continue
            if b.content_type == "heading" and prev.heading_level == b.heading_level and len(prev.text) < 80:
                prev.text += " " + b.text
                continue
        if prev and prev.content_type == "list" and b.content_type == "text" and prev.page == b.page \
                and not BULLET_RE.match(b.text) and len(b.text) < 120 and b.text[:1].islower():
            prev.text += " " + b.text
            continue
        merged.append(b)
    return merged


def _apply_ocr(doc, pages: list[int], result: ExtractionResult) -> None:
    from PIL import Image

    confidences = []
    for page_index in pages:
        pix = doc[page_index].get_pixmap(dpi=200)
        image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        text, conf = ocr_image(image)
        confidences.append(conf)
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
        for para in paragraphs:
            result.blocks.append(RawBlock(" ".join(para.split()), "text", page=page_index + 1, confidence=round(conf, 2),
                                          needs_review=conf < 0.7))
    result.ocr_applied = True
    result.metadata["ocr_mean_confidence"] = round(statistics.mean(confidences), 2) if confidences else None
    result.warnings.append(f"OCR applied to {len(pages)} page(s); mean confidence {result.metadata['ocr_mean_confidence']}.")
    # Re-sort so OCR text sits at the right page position.
    result.blocks.sort(key=lambda b: (b.page or 0))
