"""Deterministic section index built from normalized chunks.

A section = consecutive chunks sharing a section_id (i.e. under the same
heading). Sections are what the topic mapper (P02) assigns to topics, which
keeps every topic traceable to concrete pages/slides.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from storage.models import ContentChunk


@dataclass
class Section:
    label: str  # short id shown to the model, e.g. "S4"
    section_id: str
    heading: str
    document_name: str
    chunk_ids: list[str] = field(default_factory=list)
    pages: list[int] = field(default_factory=list)
    slides: list[int] = field(default_factory=list)
    chars: int = 0
    opening: str = ""
    items: list[str] = field(default_factory=list)  # lead phrases of listed items (e.g. "Bus topology")

    @property
    def location(self) -> str:
        if self.slides:
            lo, hi = min(self.slides), max(self.slides)
            loc = f"slide {lo}" if lo == hi else f"slides {lo}-{hi}"
        elif self.pages:
            lo, hi = min(self.pages), max(self.pages)
            loc = f"p. {lo}" if lo == hi else f"pp. {lo}-{hi}"
        else:
            loc = ""
        return f"{self.document_name} {loc}".strip()


def build_sections(chunks: list[ContentChunk]) -> list[Section]:
    sections: list[Section] = []
    by_key: dict[tuple[str, str], Section] = {}
    for c in chunks:
        key = (c.document_id, c.section_id or "none")
        sec = by_key.get(key)
        if sec is None or sections[-1] is not sec:
            # A section id can only continue if it is contiguous.
            sec = Section(label=f"S{len(sections) + 1}", section_id=c.section_id or "", heading=(c.heading or "(untitled)"),
                          document_name=c.document_name)
            sections.append(sec)
            by_key[key] = sec
        sec.chunk_ids.append(c.chunk_id)
        if c.page_number and c.page_number not in sec.pages:
            sec.pages.append(c.page_number)
        if c.slide_number and c.slide_number not in sec.slides:
            sec.slides.append(c.slide_number)
        sec.chars += len(c.content)
        if not sec.opening:
            sec.opening = " ".join(c.content.split())
        for line in c.content.splitlines():
            m = re.match(r"^\s*(?:[-*•]|\d{1,2}[.)])\s+(.+)", line)
            if m and len(sec.items) < 12:
                lead = re.split(r"[:–—]| - ", m.group(1), maxsplit=1)[0].strip()
                sec.items.append(" ".join(lead.split()[:8]))
    return sections


def section_index_lines(sections: list[Section], opening_chars: int = 160) -> list[str]:
    lines = []
    for s in sections:
        heading = s.heading.split(" > ")[-1] if s.heading else "(untitled)"
        parent = " > ".join(s.heading.split(" > ")[:-1])
        crumbs = f"{parent} > {heading}" if parent else heading
        opening = s.opening[:opening_chars].replace("\n", " ")
        listed = f" | lists: {'; '.join(s.items)}" if s.items else ""
        lines.append(f"{s.label} | {s.location} | {crumbs} | {s.chars} chars | {opening}{listed}")
    return lines


def outline_text(sections: list[Section], max_lines: int = 120) -> str:
    seen, lines = set(), []
    for s in sections:
        if s.heading in seen:
            continue
        seen.add(s.heading)
        depth = s.heading.count(" > ")
        lines.append("  " * depth + "- " + s.heading.split(" > ")[-1] + f"  ({s.location})")
    if len(lines) > max_lines:
        lines = lines[:max_lines] + [f"... ({len(lines) - max_lines} more headings)"]
    return "\n".join(lines) if lines else "(no headings detected)"
