"""P06-P10 - examples, important questions, revision notes, flashcards, diagrams, quizzes.

Each resource is generated from (a) the topic's source chunks and (b) a digest
of the topic's lecture notes, so that resources stay consistent with the notes.
"""
from __future__ import annotations

from typing import Any

from generation.labels import clean_labels, sources_payload
from generation.topic_context import TopicContext, notes_digest
from prompt_engine.context_manager import format_source, select_chunks_for_topic, source_budget
from prompt_engine.prompt_router import fewshot_for, template_for
from prompt_engine.stage_runner import StageResult, StageRunner


def _variables(ctx: TopicContext, resource_type: str) -> dict[str, Any]:
    strategy = ctx.strategy or {}
    return {
        "subject": ctx.subject, "level": ctx.level, "topic_title": ctx.topic.title,
        "subtopics": ctx.subtopics_text(),
        "objectives": "; ".join(ctx.topic.learning_objectives) or "(not specified)",
        "notes_digest": notes_digest(ctx.notes),
        "example_types": ", ".join(strategy.get("example_types") or []) or "whatever suits the subject",
        "question_types": ", ".join(strategy.get("question_types") or []) or "short answer, long answer, conceptual, application",
        "diagram_types": ", ".join(strategy.get("diagram_types") or []) or "flowchart, concept map",
        "fewshot": fewshot_for(resource_type, strategy),
        "source": "",
    }


def generate_resource(runner: StageRunner, ctx: TopicContext, resource_type: str) -> tuple[dict[str, Any], StageResult]:
    if resource_type == "notes":
        raise ValueError("Use notes_generator.generate_notes for lecture notes")
    template = template_for(resource_type)
    variables = _variables(ctx, resource_type)
    probe = runner.build(template, variables)
    budget = source_budget(runner.settings.context_length, runner.max_output_for(probe), probe.system + probe.user)
    chunks, dropped = select_chunks_for_topic(ctx.topic_chunk_ids(), ctx.all_chunks, budget, ctx.focus_text())
    if not chunks:
        raise ValueError(f"No source material found for topic '{ctx.topic.title}'.")
    bundle = format_source(chunks, budget)
    variables["source"] = bundle.text
    result = runner.run(template, variables)
    data = result.output.model_dump()
    removed = clean_labels(data, set(bundle.label_map))
    data["_sources"] = sources_payload(bundle)
    data["_meta"] = {"source_chunks_used": len(bundle.label_map), "source_chunks_dropped": dropped + bundle.dropped_chunks,
                     "invented_labels_removed": removed, "attempts": result.attempts}
    return data, result
