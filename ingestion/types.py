"""Intermediate extraction types (format-specific -> normalizer)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class ExtractionError(Exception):
    """A document could not be read (corrupted, encrypted, wrong format...)."""


@dataclass
class RawBlock:
    text: str
    content_type: str = "text"  # text | heading | list | table | code | equation | caption | image_ref | slide_notes
    page: int | None = None
    slide: int | None = None
    heading_level: int | None = None  # only for content_type == "heading"
    confidence: float = 1.0
    needs_review: bool = False


@dataclass
class ExtractionResult:
    blocks: list[RawBlock] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    needs_ocr: bool = False
    ocr_applied: bool = False

    @property
    def text_chars(self) -> int:
        return sum(len(b.text) for b in self.blocks if b.content_type != "image_ref")
