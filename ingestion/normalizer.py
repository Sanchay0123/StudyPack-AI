"""Convert format-specific RawBlocks into normalized, traceable ContentChunks.

Chunking rules:
* A heading starts a new section (section_id) and a new chunk.
* A new slide starts a new chunk (slides are natural units).
* Chunks are filled up to ~target_chars at block boundaries; an oversized
  block is split at sentence boundaries, never mid-word.
* Every chunk keeps document name, page/slide range and heading in a
  human-readable `source_reference`.
"""
from __future__ import annotations

import re

from ingestion.types import RawBlock
from storage.models import ContentChunk

SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9(\"'])")


def _split_long(text: str, limit: int) -> list[str]:
    if len(text) <= limit:
        return [text]
    sentences = SENTENCE_SPLIT.split(text)
    parts, current = [], ""
    for s in sentences:
        if len(s) > limit:  # pathological: no sentence breaks
            for i in range(0, len(s), limit):
                piece = s[i:i + limit]
                if current:
                    parts.append(current)
                    current = ""
                parts.append(piece)
            continue
        if current and len(current) + len(s) + 1 > limit:
            parts.append(current)
            current = s
        else:
            current = f"{current} {s}".strip()
    if current:
        parts.append(current)
    return parts


def _location(doc_name: str, pages: list[int], slides: list[int], heading: str | None) -> str:
    parts = [doc_name]
    if slides:
        lo, hi = min(slides), max(slides)
        parts.append(f"slide {lo}" if lo == hi else f"slides {lo}-{hi}")
    elif pages:
        lo, hi = min(pages), max(pages)
        parts.append(f"p. {lo}" if lo == hi else f"pp. {lo}-{hi}")
    if heading:
        parts.append(f"section \"{heading[:80]}\"")
    return ", ".join(parts)


def normalize(blocks: list[RawBlock], *, document_id: str, project_id: str, document_name: str,
              target_chars: int = 1400) -> list[ContentChunk]:
    short = document_id.split("_")[-1][:6]
    chunks: list[ContentChunk] = []
    heading_stack: list[tuple[int, str]] = []
    section_no = 0
    current: dict | None = None

    def heading_path() -> str | None:
        return " > ".join(h for _, h in heading_stack) if heading_stack else None

    def flush():
        nonlocal current
        if current and current["parts"]:
            content = "\n\n".join(current["parts"]).strip()
            types = set(current["types"])
            ctype = types.pop() if len(types) == 1 else "mixed"
            seq = len(chunks) + 1
            chunks.append(ContentChunk(
                chunk_id=f"{short}-C{seq:04d}", document_id=document_id, project_id=project_id,
                document_name=document_name, seq=seq, content=content, content_type=ctype,
                page_number=min(current["pages"]) if current["pages"] else None,
                slide_number=min(current["slides"]) if current["slides"] else None,
                heading=current["heading"], section_id=current["section_id"],
                source_reference=_location(document_name, current["pages"], current["slides"], current["heading"]),
                extraction_confidence=round(min(current["confs"]), 2) if current["confs"] else 1.0,
                needs_review=current["review"],
            ))
        current = None

    def start(section_id: str):
        nonlocal current
        current = {"parts": [], "types": [], "pages": [], "slides": [], "confs": [], "review": False,
                   "heading": heading_path(), "section_id": section_id, "size": 0}

    section_id = f"{short}-S{section_no:03d}"
    for block in blocks:
        text = block.text.strip()
        if not text:
            continue
        if block.content_type == "heading":
            flush()
            level = block.heading_level or 2
            heading_stack[:] = [(lvl, h) for lvl, h in heading_stack if lvl < level]
            heading_stack.append((level, " ".join(text.split())[:150]))
            section_no += 1
            section_id = f"{short}-S{section_no:03d}"
            start(section_id)
            continue
        new_slide = current is not None and block.slide is not None and current["slides"] and block.slide not in current["slides"]
        if current is None or new_slide:
            flush()
            start(section_id)
        pieces = _split_long(text, int(target_chars * 1.2)) if block.content_type in ("text", "slide_notes") else [text]
        for piece in pieces:
            if current["size"] and current["size"] + len(piece) > target_chars * 1.25:
                flush()
                start(section_id)
            current["parts"].append(piece)
            current["types"].append(block.content_type)
            current["size"] += len(piece)
            if block.page is not None and block.page not in current["pages"]:
                current["pages"].append(block.page)
            if block.slide is not None and block.slide not in current["slides"]:
                current["slides"].append(block.slide)
            current["confs"].append(block.confidence)
            current["review"] = current["review"] or block.needs_review
    flush()
    return chunks
