"""P02 - topic and subtopic mapping with source traceability."""
from __future__ import annotations

import re

from analyzer.sections import Section, section_index_lines
from config.logging_config import get_logger
from prompt_engine.context_manager import estimate_tokens, source_budget
from prompt_engine.schemas.analysis import TopicMap
from prompt_engine.stage_runner import StageRunner
from storage.models import Topic

log = get_logger("analyzer.topics")


def _norm_label(label: str) -> str:
    m = re.search(r"(\d+)", label)
    return f"S{int(m.group(1))}" if m else label.strip().upper()


def make_section_check(valid: set[str]):
    def check(topic_map: TopicMap) -> list[str]:
        bad = set()
        for t in topic_map.topics:
            for sid in t.section_ids:
                if _norm_label(sid) not in valid:
                    bad.add(sid)
            for st in t.subtopics:
                for sid in st.section_ids:
                    if _norm_label(sid) not in valid:
                        bad.add(sid)
        if bad:
            ordered = sorted(valid, key=lambda s: int(s[1:]))
            return [f"Unknown section IDs {sorted(bad)}; use only IDs from the index ({ordered[0]}..{ordered[-1]})."]
        if not any(t.section_ids or any(st.section_ids for st in t.subtopics) for t in topic_map.topics):
            return ["No section IDs were attached; every topic must list the section IDs it comes from."]
        return []
    return check


def _batches(lines: list[str], budget_tokens: int) -> list[list[str]]:
    batches, current, used = [], [], 0
    for line in lines:
        cost = estimate_tokens(line) + 2
        if current and used + cost > budget_tokens:
            batches.append(current)
            current, used = [], 0
        current.append(line)
        used += cost
    if current:
        batches.append(current)
    return batches


def run_topic_mapping(runner: StageRunner, sections: list[Section], subject: str, subject_context: str,
                      project_id: str) -> tuple[list[Topic], list[str]]:
    warnings: list[str] = []
    variables = {"subject": subject, "subject_context": subject_context, "section_index": ""}
    probe = runner.build("topic_mapping", variables)
    budget = source_budget(runner.settings.context_length, runner.max_output_for(probe), probe.system + probe.user)
    lines = section_index_lines(sections)
    if sum(estimate_tokens(l) for l in lines) > budget:
        lines = section_index_lines(sections, opening_chars=70)
    batches = _batches(lines, budget)
    if len(batches) > 1:
        warnings.append(f"Material is large: topic mapping ran in {len(batches)} batches.")

    by_label = {s.label: s for s in sections}
    topics: list[Topic] = []
    for batch in batches:
        valid = {line.split(" | ", 1)[0] for line in batch}
        result = runner.run("topic_mapping", {**variables, "section_index": "\n".join(batch)},
                            semantic_check=make_section_check(valid))
        topic_map: TopicMap = result.output  # type: ignore[assignment]
        for item in topic_map.topics:
            parent = Topic(project_id=project_id, title=item.title.strip(), description=item.description.strip(),
                           order_index=len(topics))
            own = [by_label[_norm_label(s)] for s in item.section_ids if _norm_label(s) in by_label]
            children = []
            for sub in item.subtopics:
                sub_secs = [by_label[_norm_label(s)] for s in sub.section_ids if _norm_label(s) in by_label]
                child = Topic(project_id=project_id, parent_topic_id=parent.topic_id, title=sub.title.strip(),
                              description=sub.description.strip(),
                              source_chunk_ids=[c for s in sub_secs for c in s.chunk_ids])
                children.append(child)
                own.extend(sub_secs)
            parent.source_chunk_ids = list(dict.fromkeys(c for s in own for c in s.chunk_ids))
            topics.append(parent)
            topics.extend(children)

    topics = _merge_duplicate_topics(topics)
    attached = attach_unassigned_sections(topics, sections)
    if attached:
        warnings.append(f"{attached} source section(s) were not assigned by the model and were attached to the nearest preceding topic.")
    for i, t in enumerate(topics):
        t.order_index = i
    return topics, warnings


def _merge_duplicate_topics(topics: list[Topic]) -> list[Topic]:
    """When batching produces the same top-level topic twice, merge them."""
    seen: dict[str, Topic] = {}
    out: list[Topic] = []
    remap: dict[str, str] = {}
    for t in topics:
        if t.parent_topic_id is None:
            key = re.sub(r"\W+", " ", t.title.lower()).strip()
            if key in seen:
                keep = seen[key]
                keep.source_chunk_ids = list(dict.fromkeys(keep.source_chunk_ids + t.source_chunk_ids))
                remap[t.topic_id] = keep.topic_id
                continue
            seen[key] = t
        elif t.parent_topic_id in remap:
            t.parent_topic_id = remap[t.parent_topic_id]
        out.append(t)
    return out


def attach_unassigned_sections(topics: list[Topic], sections: list[Section]) -> int:
    """Deterministically attach sections the model skipped, so no source content is silently lost."""
    parents = [t for t in topics if t.parent_topic_id is None]
    if not parents:
        return 0
    assigned = {c for t in topics for c in t.source_chunk_ids}
    order = {cid: i for i, s in enumerate(sections) for cid in s.chunk_ids}
    count = 0
    for idx, s in enumerate(sections):
        if s.chars < 80 or all(c in assigned for c in s.chunk_ids):
            continue
        # nearest preceding parent that owns an earlier section; default to the first topic
        target = parents[0]
        best = -1
        for p in parents:
            positions = [order[c] for c in p.source_chunk_ids if c in order and order[c] <= idx]
            if positions and max(positions) > best:
                best, target = max(positions), p
        target.source_chunk_ids = list(dict.fromkeys(target.source_chunk_ids + s.chunk_ids))
        assigned.update(s.chunk_ids)
        count += 1
    return count
