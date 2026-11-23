"""P03 - learning objectives and P04 - teaching strategy."""
from __future__ import annotations

import re

from prompt_engine.prompt_router import fewshot_for
from prompt_engine.schemas.analysis import LearningObjectives
from prompt_engine.stage_runner import StageError, StageResult, StageRunner
from storage.models import Topic


TOPICS_PER_OBJECTIVES_CALL = 6   # P03 answers grow with the number of topics: batch them
MAX_STRATEGY_TITLES = 40          # P04 only needs the flavour of the course, not every topic


def topic_list_text(topics: list[Topic], with_subtopics: bool = True, parents: list[Topic] | None = None) -> str:
    parents = parents if parents is not None else [t for t in topics if t.parent_topic_id is None]
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


def match_entries(parents: list[Topic], entries: list) -> dict[str, object]:
    """Map topic_id -> objectives entry. Exact normalised title first, then close fuzzy match (the model often
    retypes titles: apostrophes, dropped words), then position when the model returned exactly one entry per topic."""
    import difflib

    keyed = {_key(e.topic_title): e for e in entries}
    matched: dict[str, object] = {}
    used: set[int] = set()
    for p in parents:
        k = _key(p.title)
        entry = keyed.get(k)
        if entry is None:
            close = difflib.get_close_matches(k, list(keyed), n=1, cutoff=0.75)
            entry = keyed[close[0]] if close else None
        if entry is not None and id(entry) not in used:
            matched[p.topic_id] = entry
            used.add(id(entry))
    if len(matched) < len(parents) and len(entries) == len(parents):
        for p, e in zip(parents, entries):
            if p.topic_id not in matched and id(e) not in used:
                matched[p.topic_id] = e
                used.add(id(e))
    return matched


def run_learning_objectives(runner: StageRunner, topics: list[Topic], subject: str, level: str,
                            major_concepts: list[str], on_batch=None) -> tuple[StageResult | None, list[str]]:
    """P03 in batches of topics, so large courses neither overflow the prompt nor the answer.

    A batch that still fails after its repair attempts is reported (its topics get no objectives, which the
    student can add in the editor) instead of aborting the whole analysis.
    """
    all_parents = [t for t in topics if t.parent_topic_id is None]
    unmatched: list[str] = []
    result = None
    n_batches = (len(all_parents) + TOPICS_PER_OBJECTIVES_CALL - 1) // TOPICS_PER_OBJECTIVES_CALL
    for i in range(0, len(all_parents), TOPICS_PER_OBJECTIVES_CALL):
        if on_batch:
            on_batch(i // TOPICS_PER_OBJECTIVES_CALL, n_batches)
        parents = all_parents[i:i + TOPICS_PER_OBJECTIVES_CALL]

        def check(obj: LearningObjectives, parents=parents) -> list[str]:
            matched = match_entries(parents, obj.topics)
            missing = [p.title for p in parents if p.topic_id not in matched]
            if len(missing) > max(1, len(parents) // 4):
                return [f"Objectives are missing for topics: {missing}. Return one entry per topic, titles exactly as given."]
            return []

        try:
            result = runner.run("learning_objectives", {
                "subject": subject, "level": level or "(not stated)", "major_concepts": ", ".join(major_concepts[:20]) or "(none)",
                "topic_list": topic_list_text(topics, parents=parents)}, semantic_check=check)
        except StageError:
            unmatched += [p.title for p in parents]
            continue
        matched = match_entries(parents, result.output.topics)  # type: ignore[attr-defined]
        for p in parents:
            entry = matched.get(p.topic_id)
            if entry is None:
                unmatched.append(p.title)
                continue
            p.learning_objectives = entry.objectives
            p.prerequisites = entry.prerequisites
    return result, unmatched


def run_teaching_strategy(runner: StageRunner, topics: list[Topic], subject: str, domain_category: str,
                          level: str, subject_context: str) -> StageResult:
    from analyzer.sections import spread

    parents = [t for t in topics if t.parent_topic_id is None]
    titles = spread([p.title for p in parents], MAX_STRATEGY_TITLES)
    topic_list = "; ".join(titles) + (f" (and {len(parents) - len(titles)} more topics)" if len(titles) < len(parents) else "")
    return runner.run("teaching_strategy", {
        "subject": subject, "domain_category": domain_category, "level": level or "(not stated)",
        "subject_context": subject_context, "topic_list": topic_list, "fewshot": fewshot_for("strategy")})
