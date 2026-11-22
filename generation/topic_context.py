"""Assembles everything a generation stage needs for one topic."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from prompt_engine.context_manager import retrieve_by_keywords
from storage.models import ContentChunk, Project, Topic
from storage.repository import Repository


@dataclass
class TopicContext:
    project: Project
    topic: Topic
    subtopics: list[Topic]
    analysis: dict[str, Any]
    strategy: dict[str, Any]
    all_chunks: list[ContentChunk]
    notes: dict[str, Any] | None = None

    @property
    def subject(self) -> str:
        return self.project.subject or self.analysis.get("subject") or "the subject"

    @property
    def level(self) -> str:
        return self.project.academic_level or self.analysis.get("estimated_level") or "undergraduate"

    @property
    def subtopic_titles(self) -> list[str]:
        return [s.title for s in self.subtopics]

    def subtopics_text(self) -> str:
        if not self.subtopics:
            return f"(no separate subtopics; cover '{self.topic.title}' fully)"
        return "; ".join(f"{s.title}" + (f" ({s.description})" if s.description else "") for s in self.subtopics)

    def topic_chunk_ids(self) -> list[str]:
        ids = list(self.topic.source_chunk_ids)
        for s in self.subtopics:
            ids.extend(s.source_chunk_ids)
        ids = list(dict.fromkeys(ids))
        if not ids:
            query = " ".join([self.topic.title, self.topic.description] + self.subtopic_titles)
            ids = [c.chunk_id for c in retrieve_by_keywords(query, self.all_chunks)]
        return ids

    def focus_text(self) -> str:
        return " ".join([self.topic.title, self.topic.description] + self.subtopic_titles)


def strategy_text(strategy: dict[str, Any] | None) -> str:
    if not strategy:
        return "(no strategy available: use a clear, general academic teaching approach)"
    lines = [f"Approach: {strategy.get('approach_summary', '')}"]
    if strategy.get("priorities"):
        lines.append("Priorities: " + "; ".join(strategy["priorities"]))
    if strategy.get("notation_guidance"):
        lines.append(f"Notation: {strategy['notation_guidance']}")
    if strategy.get("common_pitfalls_focus"):
        lines.append(f"Highlight mistakes about: {strategy['common_pitfalls_focus']}")
    if strategy.get("sections_to_omit"):
        lines.append("Do not include: " + ", ".join(strategy["sections_to_omit"]))
    return "\n".join(lines)


def notes_digest(notes: dict[str, Any] | None, max_chars: int = 2600) -> str:
    """Compact digest of generated notes, passed to later stages for cross-resource consistency."""
    if not notes:
        return "(lecture notes not generated yet - rely on the source material)"
    parts = [f"Overview: {notes.get('overview', '')}"]
    terms = notes.get("key_terms") or []
    if terms:
        parts.append("Key terms: " + "; ".join(f"{t['term']}: {t['definition'][:140]}" for t in terms[:15]))
    for s in notes.get("sections", []):
        first = " ".join(s.get("content", "").split())[:220]
        parts.append(f"- {s.get('heading')}: {first}")
    text = "\n".join(parts)
    return text if len(text) <= max_chars else text[:max_chars].rsplit(" ", 1)[0] + " ..."


def load_topic_context(repo: Repository, project_id: str, topic_id: str) -> TopicContext:
    project = repo.get_project(project_id)
    topic = repo.get_topic(topic_id)
    if project is None or topic is None:
        raise ValueError("Unknown project or topic")
    topics = repo.list_topics(project_id)
    subtopics = [t for t in topics if t.parent_topic_id == topic_id]
    stored = repo.get_analysis(project_id)
    notes_res = repo.get_resource(project_id, topic_id, "notes")
    return TopicContext(project=project, topic=topic, subtopics=subtopics, analysis=stored.get("analysis") or {},
                        strategy=stored.get("strategy") or {}, all_chunks=repo.list_chunks(project_id),
                        notes=notes_res.content if notes_res else None)
