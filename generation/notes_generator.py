"""P05 - comprehensive lecture notes.

If a topic's source material exceeds the context budget, the notes are
generated in consecutive parts (each part sees a different slice of the
source, with globally unique source labels) and merged, rather than silently
truncating the source.
"""
from __future__ import annotations

from typing import Any

from generation.labels import clean_labels, sources_payload
from generation.topic_context import TopicContext, strategy_text
from prompt_engine.context_manager import batch_chunks, estimate_tokens, format_source, source_budget
from prompt_engine.stage_runner import StageResult, StageRunner

DEFAULT_SECTIONS = ["introduction", "background", "concept", "definitions", "mechanism", "example",
                    "applications", "advantages_disadvantages", "comparison", "mistakes", "key_points", "summary"]
MAX_PARTS = 4


def _base_variables(ctx: TopicContext) -> dict[str, Any]:
    strategy = ctx.strategy or {}
    return {
        "subject": ctx.subject, "level": ctx.level, "topic_title": ctx.topic.title,
        "topic_description": ctx.topic.description or "(see source)", "subtopics": ctx.subtopics_text(),
        "objectives": "; ".join(ctx.topic.learning_objectives) or "(not specified)",
        "prerequisites": "; ".join(ctx.topic.prerequisites) or "(none listed)",
        "strategy": strategy_text(strategy),
        "section_kinds": ", ".join(strategy.get("note_sections") or DEFAULT_SECTIONS),
        "part_note": "", "source": "",
    }


def generate_notes(runner: StageRunner, ctx: TopicContext) -> tuple[dict[str, Any], list[StageResult]]:
    variables = _base_variables(ctx)
    probe = runner.build("lecture_notes", variables)
    budget = source_budget(runner.settings.context_length, runner.max_output_for(probe), probe.system + probe.user)
    by_id = {c.chunk_id: c for c in ctx.all_chunks}
    chunks = [by_id[cid] for cid in ctx.topic_chunk_ids() if cid in by_id]
    if not chunks:
        raise ValueError(f"No source material found for topic '{ctx.topic.title}'. Attach sections to it in Document Analysis.")
    total = sum(estimate_tokens(c.content) + 25 for c in chunks)
    parts = [chunks] if total <= budget else batch_chunks(chunks, budget)
    dropped_parts = 0
    if len(parts) > MAX_PARTS:
        dropped_parts = len(parts) - MAX_PARTS
        parts = parts[:MAX_PARTS]

    results: list[StageResult] = []
    bundles = []
    merged: dict[str, Any] | None = None
    label_start = 1
    removed_labels = 0
    for index, part in enumerate(parts, start=1):
        bundle = format_source(part, budget, label_start=label_start)
        label_start += len(bundle.label_map)
        bundles.append(bundle)
        part_vars = dict(variables, source=bundle.text)
        if len(parts) > 1:
            part_vars["part_note"] = (
                f"\nThis is PART {index} of {len(parts)}: the source below is only one portion of the topic's material. "
                f"Write detailed sections for the content in THIS portion only"
                + (" (start with the introduction)." if index == 1 else "; do not repeat the introduction, and put the summary only in the last part." if index < len(parts) else "; finish with the summary of the whole topic."))
        result = runner.run("lecture_notes", part_vars)
        results.append(result)
        data = result.output.model_dump()
        removed_labels += clean_labels(data, set(bundle.label_map))
        if merged is None:
            merged = data
        else:
            merged["sections"].extend(data["sections"])
            known = {t["term"].lower() for t in merged["key_terms"]}
            merged["key_terms"].extend(t for t in data["key_terms"] if t["term"].lower() not in known)
            merged["summary"] = data["summary"] if index == len(parts) else merged["summary"]

    assert merged is not None
    merged["topic_title"] = ctx.topic.title
    merged["_sources"] = sources_payload(*bundles)
    merged["_meta"] = {
        "parts": len(parts), "source_chunks_used": sum(len(b.label_map) for b in bundles),
        "source_chunks_total": len(chunks), "truncated": any(b.truncated for b in bundles) or dropped_parts > 0,
        "attempts": sum(r.attempts for r in results), "invented_labels_removed": removed_labels,
    }
    return merged, results


def notes_to_text(notes: dict[str, Any], include_provenance: bool = True) -> str:
    """Plain-text rendering used for evaluation prompts."""
    lines = [f"# {notes.get('topic_title', '')}", notes.get("overview", "")]
    for s in notes.get("sections", []):
        tag = f" [provenance: {s.get('provenance')}; cites: {', '.join(s.get('source_labels') or []) or 'none'}]" if include_provenance else ""
        lines.append(f"\n## {s.get('heading')}{tag}\n{s.get('content', '')}")
    if notes.get("key_terms"):
        lines.append("\n## Key terms\n" + "\n".join(f"- {t['term']}: {t['definition']}" for t in notes["key_terms"]))
    lines.append(f"\n## Summary\n{notes.get('summary', '')}")
    return "\n".join(lines)
