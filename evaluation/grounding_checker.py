"""Source-grounding checks for lecture notes (deterministic, no LLM).

For each section:
  * provenance label (source / supplementary / inferred)
  * whether "source" sections cite at least one valid source label
  * sentence support: share of the section's sentences whose content words
    mostly occur in the cited chunks (or, if none cited, the topic's source)
Sections labelled "source" with low support are flagged as weakly grounded.
"""
from __future__ import annotations

from typing import Any

from evaluation.text_utils import numbers_in, sentence_support
from storage.models import ContentChunk

WEAK_SUPPORT = 0.34


def check_grounding(notes: dict[str, Any], chunks_by_id: dict[str, ContentChunk]) -> dict[str, Any]:
    sources = notes.get("_sources", {})
    # Headings (slide titles, section titles) are source text too, but live outside chunk content.
    label_text = {lab: f"{chunks_by_id[v['chunk_id']].heading or ''}\n{chunks_by_id[v['chunk_id']].content}"
                  for lab, v in sources.items() if v.get("chunk_id") in chunks_by_id}
    all_source = "\n".join(label_text.values())
    sections_report = []
    chars = {"source": 0, "supplementary": 0, "inferred": 0}
    for s in notes.get("sections", []):
        content = s.get("content", "")
        prov = s.get("provenance", "inferred")
        chars[prov] = chars.get(prov, 0) + len(content)
        cited = [lab for lab in s.get("source_labels", []) if lab in label_text]
        reference = "\n".join(label_text[lab] for lab in cited) if cited else all_source
        support = sentence_support(content, reference)
        unsupported_numbers = sorted(n for n in numbers_in(content) if n not in all_source)
        flags = []
        if prov == "source" and not cited:
            flags.append("labelled 'source' but cites no source block")
        if prov == "source" and support < WEAK_SUPPORT:
            flags.append(f"weakly grounded: only {support:.0%} of its sentences have lexical support in the cited source")
        if unsupported_numbers and prov == "source":
            flags.append(f"numbers not found in source: {', '.join(unsupported_numbers[:6])}")
        sections_report.append({"heading": s.get("heading"), "provenance": prov, "cited": cited,
                                "references": [sources[lab]["ref"] for lab in cited],
                                "support": round(support, 2), "flags": flags})
    total = sum(chars.values()) or 1
    source_sections = [r for r in sections_report if r["provenance"] == "source"]
    grounded = [r for r in source_sections if not r["flags"]]
    return {
        "sections": sections_report,
        "provenance_share": {k: round(100 * v / total, 1) for k, v in chars.items()},
        "source_sections": len(source_sections),
        "well_grounded_source_sections": len(grounded),
        "grounding_rate": round(100 * len(grounded) / len(source_sections), 1) if source_sections else None,
        "flagged_sections": [r for r in sections_report if r["flags"]],
    }
