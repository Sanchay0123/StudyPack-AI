"""Collects a study pack's content for exporters (single source of truth)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from prompt_engine.prompt_router import RESOURCE_TYPES
from storage.models import Document, Project, Topic
from storage.repository import Repository


@dataclass
class TopicBundle:
    topic: Topic
    subtopics: list[Topic]
    resources: dict[str, dict[str, Any]] = field(default_factory=dict)
    meta: dict[str, dict[str, Any]] = field(default_factory=dict)  # provider/model/version per resource
    evaluation: dict[str, Any] | None = None


@dataclass
class PackBundle:
    project: Project
    documents: list[Document]
    analysis: dict[str, Any]
    strategy: dict[str, Any]
    topics: list[TopicBundle]
    resource_types: list[str]


def collect_pack(repo: Repository, project_id: str, resource_types: list[str] | None = None,
                 topic_ids: list[str] | None = None) -> PackBundle:
    project = repo.get_project(project_id)
    if project is None:
        raise ValueError("Unknown project")
    resource_types = [r for r in RESOURCE_TYPES if r in (resource_types or RESOURCE_TYPES)]
    all_topics = repo.list_topics(project_id)
    parents = [t for t in all_topics if t.parent_topic_id is None and (not topic_ids or t.topic_id in topic_ids)]
    evals = {e.topic_id: e.report for e in repo.list_evaluations(project_id)}
    bundles = []
    for p in parents:
        b = TopicBundle(p, [t for t in all_topics if t.parent_topic_id == p.topic_id], evaluation=evals.get(p.topic_id))
        for rtype in resource_types:
            res = repo.get_resource(project_id, p.topic_id, rtype)
            if res:
                b.resources[rtype] = res.content
                b.meta[rtype] = {"provider": res.provider, "model": res.model, "version": res.version,
                                 "prompt": f"{res.prompt_id}@{res.prompt_version}", "origin": res.origin, "created": res.created_at}
        bundles.append(b)
    stored = repo.get_analysis(project_id)
    return PackBundle(project, repo.list_documents(project_id), stored.get("analysis") or {}, stored.get("strategy") or {},
                      bundles, resource_types)


def models_used(pack: PackBundle) -> list[str]:
    return sorted({f"{m['model']} ({m['provider']})" for t in pack.topics for m in t.meta.values() if m.get("model")})
