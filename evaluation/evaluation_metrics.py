"""Project-level aggregation of persisted evaluation results (no estimation)."""
from __future__ import annotations

from typing import Any

from storage.repository import Repository


def project_summary(repo: Repository, project_id: str) -> dict[str, Any]:
    parents = [t for t in repo.list_topics(project_id) if t.parent_topic_id is None]
    with_notes = [p for p in parents if repo.get_resource(project_id, p.topic_id, "notes")]
    evals = {e.topic_id: e for e in repo.list_evaluations(project_id)}
    scored = [evals[p.topic_id].coverage_score for p in with_notes if p.topic_id in evals and evals[p.topic_id].coverage_score is not None]
    reports = [evals[p.topic_id].report for p in with_notes if p.topic_id in evals]
    claims = [c for r in reports for c in (r.get("llm") or {}).get("unsupported_claims", [])]
    return {
        "topics": len(parents),
        "with_notes": len(with_notes),
        "evaluated": len(reports),
        "mean_coverage": round(sum(scored) / len(scored), 1) if scored else None,
        "missing_units": sum(len(r.get("missing_units", [])) for r in reports),
        "partial_units": sum(len(r.get("partial_units", [])) for r in reports),
        "unsupported_claims": len(claims),
        "high_severity": sum(c.get("severity") == "high" for c in claims),
        "passed": sum(r.get("status") == "passed" for r in reports),
        "missing_topics": [p.title for p in parents if p not in with_notes],
    }
