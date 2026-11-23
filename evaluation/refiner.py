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
from prompt_engine.stage_runner import StageError, StageResult, StageRunner
from providers.exceptions import ContextOverflowError, ProviderError


def _key(text: str) -> str:
    return re.sub(r"\W+", " ", (text or "").lower()).strip()


def affected_sections(notes: dict[str, Any], findings: list[str]) -> list[str]:
    joined = " ".join(findings).lower()
    return [s["heading"] for s in notes.get("sections", []) if s["heading"].lower() in joined]


def apply_revisions(notes: dict[str, Any], refinement: NotesRefinement,
                    allowed: set[str] | None = None) -> tuple[dict[str, Any], list[str]]:
    """Apply section-level edits. If `allowed` is given, replace/remove only touch those headings."""
    updated = copy.deepcopy(notes)
    sections = updated["sections"]
    applied = []
    replaced_targets = {_key(r.target_heading) for r in refinement.revisions if r.action == "replace" and r.section}
    for rev in refinement.revisions:
        target = _key(rev.target_heading)
        new_heading = _key(rev.section.heading) if rev.section else ""
        # "Summary" / "Overview" / "Key terms" are fields of the notes, not sections.
        field_target = next((f for f in ("summary", "overview", "key terms") if f in (target, new_heading)), None)
        if field_target:
            if rev.section and field_target in ("summary", "overview") and rev.action in ("replace", "add"):
                updated[field_target] = rev.section.content
                applied.append(f"updated {field_target}")
            continue  # key terms are not edited through sections
        if rev.action == "remove" and target in replaced_targets:
            continue  # the model both fixed and removed this section: keep the fix
        if allowed is not None and rev.action in ("replace", "remove") and target not in {_key(h) for h in allowed}:
            applied.append(f"skipped (no findings for this section): {rev.target_heading}")
            continue
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


FINDINGS_PER_PASS = 5


def refine_notes(runner: StageRunner, ctx: TopicContext, notes: dict[str, Any], findings: list[str]) -> tuple[dict[str, Any], StageResult, list[str]]:
    """Apply the findings in groups of FINDINGS_PER_PASS, each group as one P12 call on the notes updated by the
    previous group. Small groups keep each prompt inside the context window (only the sections a group names are
    sent in full) and give the small model a short, focused task. A failing group is skipped; if every group
    fails, the last error is raised."""
    groups = [findings[i:i + FINDINGS_PER_PASS] for i in range(0, len(findings), FINDINGS_PER_PASS)] or [[]]
    current, last_result, applied_all, change_log, last_error = notes, None, [], [], None
    for group in groups:
        try:
            current, result, applied = _refine_pass(runner, ctx, current, group)
        except (StageError, ProviderError) as exc:
            if isinstance(exc, ProviderError) and not isinstance(exc, ContextOverflowError):
                raise  # provider down: stop rather than burn through the remaining groups
            last_error = exc
            applied_all.append(f"skipped {len(group)} finding(s): {exc.__class__.__name__}")
            continue
        last_result = result
        applied_all.extend(applied)
        change_log.extend(current.get("_meta", {}).get("change_log", []) or [])
    if last_result is None:
        raise last_error  # type: ignore[misc]
    current["_meta"] = {**current.get("_meta", {}), "change_log": change_log, "applied": applied_all}
    return current, last_result, applied_all


def _refine_pass(runner: StageRunner, ctx: TopicContext, notes: dict[str, Any], findings: list[str]) -> tuple[dict[str, Any], StageResult, list[str]]:
    variables = {"subject": ctx.subject, "topic_title": ctx.topic.title,
                 "findings": "\n".join(f"{i + 1}. {f}" for i, f in enumerate(findings)),
                 "section_headings": "; ".join(s["heading"] for s in notes.get("sections", [])),
                 "affected_sections": "; ".join(affected_sections(notes, findings)) or "(none named - findings concern missing or thin coverage)",
                 "notes_text": notes_to_text(notes), "source": ""}
    probe = runner.build("refinement", variables)
    budget = source_budget(runner.settings.context_length, runner.max_output_for(probe), probe.system + probe.user)
    # Targeted context: if the full notes do not leave room for evidence, send only the sections the
    # findings name (other sections are listed by heading), then shorten those if still necessary.
    for max_chars in (None, 1500, 700, 300, 120):
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
    allowed = None if any(f.startswith(("MISSING", "THIN")) for f in findings) else set(affected_sections(notes, findings))
    updated, applied = apply_revisions(notes, refinement, allowed)
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
