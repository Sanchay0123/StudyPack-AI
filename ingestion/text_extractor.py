"""Plain text and Markdown extraction."""
from __future__ import annotations

import re

from ingestion.types import ExtractionError, ExtractionResult, RawBlock

LIST_RE = re.compile(r"^\s*([-*+•]|\d{1,3}[.)])\s+")
NUMBERED_HEADING_RE = re.compile(r"^(\d+(\.\d+){0,3})\.?\s+[A-Z][^.!?]{2,80}$")


def _decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    raise ExtractionError("Could not decode the text file.")


def extract_text(path: str, markdown: bool) -> ExtractionResult:
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
    except OSError as exc:
        raise ExtractionError(f"Could not read file: {exc}") from exc
    text = _decode(raw).replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    result = ExtractionResult(metadata={"lines": len(lines)})
    para: list[str] = []
    in_code = False
    code: list[str] = []

    def flush_para():
        if para:
            joined = " ".join(s.strip() for s in para).strip()
            if joined:
                result.blocks.append(RawBlock(joined, "text"))
            para.clear()

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            if in_code:
                result.blocks.append(RawBlock("\n".join(code), "code"))
                code, in_code = [], False
            else:
                flush_para()
                in_code = True
            i += 1
            continue
        if in_code:
            code.append(line)
            i += 1
            continue
        if not stripped:
            flush_para()
            i += 1
            continue
        if markdown and stripped.startswith("#"):
            flush_para()
            level = len(stripped) - len(stripped.lstrip("#"))
            result.blocks.append(RawBlock(stripped.lstrip("#").strip(), "heading", heading_level=min(level, 4)))
            i += 1
            continue
        # Setext headings / underlined headings in plain text
        if i + 1 < len(lines) and re.fullmatch(r"\s*(=){3,}\s*|\s*(-){3,}\s*", lines[i + 1]) and len(stripped) < 100:
            flush_para()
            level = 1 if "=" in lines[i + 1] else 2
            result.blocks.append(RawBlock(stripped, "heading", heading_level=level))
            i += 2
            continue
        if stripped.startswith("|") and stripped.endswith("|"):
            flush_para()
            table = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                table.append(lines[i].strip())
                i += 1
            result.blocks.append(RawBlock("\n".join(table), "table"))
            continue
        if not markdown and (NUMBERED_HEADING_RE.match(stripped) or (stripped.isupper() and 3 < len(stripped) < 70)) and not para:
            depth = stripped.split()[0].count(".") + 1 if stripped[0].isdigit() else 1
            result.blocks.append(RawBlock(stripped, "heading", heading_level=min(depth + (0 if stripped.isupper() else 1), 4)))
            i += 1
            continue
        if LIST_RE.match(line):
            flush_para()
            if result.blocks and result.blocks[-1].content_type == "list":
                result.blocks[-1].text += "\n" + line.rstrip()
            else:
                result.blocks.append(RawBlock(line.rstrip(), "list"))
            i += 1
            continue
        if line.startswith(("    ", "\t")) and not para:
            result.blocks.append(RawBlock(line.rstrip(), "code"))
            i += 1
            continue
        if markdown and stripped.startswith("$$"):
            flush_para()
            result.blocks.append(RawBlock(stripped, "equation"))
            i += 1
            continue
        para.append(line)
        i += 1
    flush_para()
    if in_code and code:
        result.blocks.append(RawBlock("\n".join(code), "code"))
        result.warnings.append("Unterminated code block at end of file.")
    if not result.blocks:
        result.warnings.append("The file contains no text.")
    return result
