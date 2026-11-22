"""P03 - learning objectives and P04 - teaching strategy."""
from __future__ import annotations

import re

from prompt_engine.prompt_router import fewshot_for
from prompt_engine.schemas.analysis import LearningObjectives
from prompt_engine.stage_runner import StageResult, StageRunner
from storage.models import Topic


def topic_list_text(topics: list[Topic], with_subtopics: bool = True) -> str:
    parents = [t for t in topics if t.parent_topic_id is None]
    lines = []
    for p in parents:
        line = f"- {p.title}: {p.description}"
        if with_subtopics:
            subs = [t.title for t in topics if t.parent_topic_id == p.topic_id]
            if subs:
                line += f" Subtopics: {', '.join(subs)}."
        lines.append(line)
    return "\n".join(lines)


def _key(title: str) -> str:
    return re.sub(r"\W+", " ", title.lower()).strip()


def run_learning_objectives(runner: StageRunner, topics: list[Topic], subject: str, level: str,
                            major_concepts: list[str]) -> tuple[StageResult, list[str]]:
    parents = [t for t in topics if t.parent_topic_id is None]

    def check(obj: LearningObjectives) -> list[str]:
        got = {_key(t.topic_title) for t in obj.topics}
        missing = [p.title for p in parents if _key(p.title) not in got]
        if len(missing) > max(1, len(parents) // 4):
            return [f"Objectives are missing for topics: {missing}. Return one entry per topic, titles exactly as given."]
        return []

    result = runner.run("learning_objectives", {
        "subject": subject, "level": level or "(not stated)", "major_concepts": ", ".join(major_concepts[:20]) or "(none)",
        "topic_list": topic_list_text(topics)}, semantic_check=check)
    by_key = {_key(t.topic_title): t for t in result.output.topics}  # type: ignore[attr-defined]
    unmatched = []
    for p in parents:
        entry = by_key.get(_key(p.title))
        if entry is None:
            unmatched.append(p.title)
            continue
        p.learning_objectives = entry.objectives
        p.prerequisites = entry.prerequisites
    return result, unmatched


def run_teaching_strategy(runner: StageRunner, topics: list[Topic], subject: str, domain_category: str,
                          level: str, subject_context: str) -> StageResult:
    return runner.run("teaching_strategy", {
        "subject": subject, "domain_category": domain_category, "level": level or "(not stated)",
        "subject_context": subject_context, "topic_list": topic_list_text(topics, with_subtopics=False),
        "fewshot": fewshot_for("strategy")})
