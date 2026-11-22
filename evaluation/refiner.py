"""P12 - targeted refinement: apply section-level revisions to the notes."""
from __future__ import annotations

import copy
import re
from typing import Any

from generation.labels import clean_labels
from generation.notes_generator import notes_to_text
from generation.topic_context import TopicContext
from prompt_engine.context_manager import format_source, select_chunks_for_topic, source_budget
from prompt_engine.schemas.evaluation import NotesRefinement
from prompt_engine.stage_runner import StageResult, StageRunner


def _key(text: str) -> str:
    return re.sub(r"\W+", " ", (text or "").lower()).strip()


def apply_revisions(notes: dict[str, Any], refinement: NotesRefinement) -> tuple[dict[str, Any], list[str]]:
    updated = copy.deepcopy(notes)
    sections = updated["sections"]
    applied = []
    for rev in refinement.revisions:
        target = _key(rev.target_heading)
        index = next((i for i, s in enumerate(sections) if _key(s["heading"]) == target), None)
        if index is None:
            index = next((i for i, s in enumerate(sections) if target and (target in _key(s["heading"]) or _key(s["heading"]) in target)), None)
        new_section = rev.section.model_dump() if rev.section else None
        if rev.action == "replace" and new_section:
            if index is None:
                sections.append(new_section)
                applied.append(f"added (replace target not found): {new_section['heading']}")
            else:
                sections[index] = new_section
                applied.append(f"replaced: {new_section['heading']}")
        elif rev.action == "add" and new_section:
            if index is None or target == "end":
                # insert before a trailing summary section if present
                pos = len(sections) - 1 if sections and sections[-1].get("kind") == "summary" else len(sections)
                sections.insert(pos, new_section)
            else:
                sections.insert(index + 1, new_section)
            applied.append(f"added: {new_section['heading']}")
        elif rev.action == "remove" and index is not None and len(sections) > 3:
            removed = sections.pop(index)
            applied.append(f"removed: {removed['heading']}")
    return updated, applied


def targeted_notes_view(notes: dict[str, Any], findings: list[str], max_chars: int | None = None) -> str:
    """Notes text containing only the sections named in the findings (others appear as headings)."""
    joined = " ".join(findings).lower()
    lines = [f"# {notes.get('topic_title', '')}", notes.get("overview", "")]
    for s in notes.get("sections", []):
        if s["heading"].lower() in joined:
            content = s.get("content", "")
            if max_chars and len(content) > max_chars:
                content = content[:max_chars].rsplit(" ", 1)[0] + " [...]"
            lines.append(f"\n## {s['heading']} [provenance: {s.get('provenance')}]\n{content}")
        else:
            lines.append(f"\n## {s['heading']} (content omitted: no findings for this section)")
    return "\n".join(lines)


def refine_notes(runner: StageRunner, ctx: TopicContext, notes: dict[str, Any], findings: list[str]) -> tuple[dict[str, Any], StageResult, list[str]]:
    variables = {"subject": ctx.subject, "topic_title": ctx.topic.title,
                 "findings": "\n".join(f"{i + 1}. {f}" for i, f in enumerate(findings)),
                 "section_headings": "; ".join(s["heading"] for s in notes.get("sections", [])),
                 "notes_text": notes_to_text(notes), "source": ""}
    probe = runner.build("refinement", variables)
    budget = source_budget(runner.settings.context_length, runner.max_output_for(probe), probe.system + probe.user)
    # Targeted context: if the full notes do not leave room for evidence, send only the sections the
    # findings name (other sections are listed by heading), then shorten those if still necessary.
    for max_chars in (None, 1500, 700):
        if budget >= 600:
            break
        variables["notes_text"] = targeted_notes_view(notes, findings, max_chars)
        probe = runner.build("refinement", variables)
        budget = source_budget(runner.settings.context_length, runner.max_output_for(probe), probe.system + probe.user)
    chunks, _ = select_chunks_for_topic(ctx.topic_chunk_ids(), ctx.all_chunks, max(budget, 300), " ".join(findings))
    # Reuse the labels already used by the notes where possible so citations stay comparable.
    bundle = format_source(chunks, max(budget, 300))
    variables["source"] = bundle.text
    result = runner.run("refinement", variables)
    refinement: NotesRefinement = result.output  # type: ignore[assignment]
    updated, applied = apply_revisions(notes, refinement)
    # Map refinement labels into the notes' label space.
    existing = {v["chunk_id"]: lab for lab, v in notes.get("_sources", {}).items()}
    sources = dict(notes.get("_sources", {}))
    relabel = {}
    for lab, chunk_id in bundle.label_map.items():
        if chunk_id in existing:
            relabel[lab] = existing[chunk_id]
        else:
            new_label = f"S{len(sources) + 1}"
            sources[new_label] = {"chunk_id": chunk_id, "ref": bundle.references[lab]}
            relabel[lab] = new_label
    touched = {r.section.heading for r in refinement.revisions if r.section}
    for s in updated["sections"]:
        if s["heading"] in touched:
            s["source_labels"] = [relabel.get(l.upper().strip("[]"), "") for l in s.get("source_labels", [])]
            s["source_labels"] = [l for l in s["source_labels"] if l]
    clean_labels(updated, set(sources))
    updated["_sources"] = sources
    updated["_meta"] = {**notes.get("_meta", {}), "refined": True, "change_log": refinement.change_log, "applied": applied}
    return updated, result, applied
