"""Offline end-to-end tests of analysis, generation, evaluation and refinement
through the real Orchestrator, using the FakeLLM test fixture."""
from __future__ import annotations

import pytest

from config.settings import get_settings
from ingestion.pipeline import ingest_files
from prompt_engine.orchestrator import Orchestrator
from prompt_engine.prompt_router import RESOURCE_TYPES
from providers.provider_router import ProviderRouter
from storage.database import Database
from storage.models import Project
from storage.repository import Repository
from tests.fake_llm import FakeLLM

DOC = ("# LAN Topologies\n\nA topology describes how devices connect.\n\n"
       "- Bus topology: all devices share a single backbone cable.\n- Star topology: every device connects to a central switch.\n")


@pytest.fixture
def setup(tmp_path):
    repo = Repository(Database(tmp_path / "p.db"))
    project = repo.create_project(Project(name="Offline"))
    ingest_files(repo, project.project_id, [("topologies.md", DOC.encode())], settings=get_settings())
    fake = FakeLLM()
    orch = Orchestrator(repo, ProviderRouter(fake), get_settings())
    return repo, project, orch, fake


def test_analysis_builds_traceable_topic_tree(setup):
    repo, project, orch, _ = setup
    outcome = orch.run_analysis(project.project_id)
    assert outcome.ok, outcome.error
    assert outcome.stages_completed == ["P01", "P02", "P03", "P04"]
    topics = repo.list_topics(project.project_id)
    parent = next(t for t in topics if t.parent_topic_id is None)
    assert parent.title == "LAN Topologies" and parent.learning_objectives == ["Compare bus and star topologies"]
    assert parent.source_chunk_ids, "topic must keep source references"
    assert {t.title for t in topics if t.parent_topic_id} == {"Bus topology", "Star topology"}
    stored = repo.get_analysis(project.project_id)
    assert stored["analysis"]["subject"] == "Computer Networks" and stored["strategy"]["example_style"] == "programming"
    assert repo.get_project(project.project_id).subject == "Computer Networks"
    assert len(repo.list_stage_runs(project.project_id)) == 4


def test_unknown_section_ids_trigger_repair(setup):
    repo, project, orch, fake = setup
    bad = {"topics": [{"title": "T", "description": "d", "section_ids": ["S42"], "subtopics": []}]}
    calls = {"n": 0}
    original = fake.generate

    def generate(request):
        if "topic_mapping" in request.metadata.get("template", "") and calls["n"] == 0:
            calls["n"] += 1
            import json
            from providers.base import GenerationResult
            return GenerationResult(json.dumps(bad), "fake", "m", 0.0)
        return original(request)

    fake.generate = generate
    assert orch.run_analysis(project.project_id).ok
    runs = [r for r in repo.list_stage_runs(project.project_id) if r.stage_id.startswith("P02")]
    assert runs[0].attempts == 2


def test_generate_all_resources_saves_and_versions(setup):
    repo, project, orch, _ = setup
    orch.run_analysis(project.project_id)
    plan = orch.plan(project.project_id, RESOURCE_TYPES)
    assert [r for _, r in plan] == RESOURCE_TYPES  # notes first
    outcomes = orch.run_plan(project.project_id, plan)
    assert all(o.status == "done" for o in outcomes), outcomes
    topic_id = plan[0][0]
    notes = repo.get_resource(project.project_id, topic_id, "notes")
    assert notes.content["_sources"]["S1"]["ref"].startswith("topologies.md")
    assert notes.content["key_terms"][0]["source_labels"] == ["S1"], "invented label S99 must be removed"
    assert notes.prompt_version.startswith("1.") and "+" in notes.prompt_version
    # second generation creates version 2, keeps version 1
    orch.generate_one(project.project_id, topic_id, "notes")
    versions = repo.resource_versions(project.project_id, topic_id, "notes")
    assert [v.version for v in versions] == [2, 1] and versions[0].is_current and not versions[1].is_current
    assert orch.plan(project.project_id, RESOURCE_TYPES) == []  # nothing missing


def test_failed_task_is_recorded_and_retry_resumes(setup):
    repo, project, orch, fake = setup
    orch.run_analysis(project.project_id)
    fake.overrides["flashcards"] = {"cards": []}  # always invalid
    outcomes = orch.run_plan(project.project_id, orch.plan(project.project_id, ["notes", "flashcards", "quiz"]))
    status = {o.resource_type: o.status for o in outcomes}
    assert status == {"notes": "done", "flashcards": "failed", "quiz": "done"}
    task = repo.get_task(project.project_id, outcomes[0].topic_id, "flashcards")
    assert task.status == "failed" and "validation" in task.error
    # retry only what is missing
    del fake.overrides["flashcards"]
    retry_plan = orch.plan(project.project_id, ["notes", "flashcards", "quiz"])
    assert [r for _, r in retry_plan] == ["flashcards"]
    assert orch.run_plan(project.project_id, retry_plan)[0].status == "done"


def test_interrupted_tasks_become_retryable(setup):
    repo, project, orch, _ = setup
    from storage.models import GenerationTask
    orch.run_analysis(project.project_id)
    topic = repo.list_topics(project.project_id)[0]
    repo.upsert_task(GenerationTask(project_id=project.project_id, topic_id=topic.topic_id, resource_type="notes", status="running"))
    assert repo.mark_stale_running_tasks(project.project_id) == 0, "a fresh running task may be live in another session"
    assert repo.get_task(project.project_id, topic.topic_id, "notes").status == "running"
    assert repo.mark_stale_running_tasks(project.project_id, older_than_s=-5) == 1
    assert repo.get_task(project.project_id, topic.topic_id, "notes").status == "interrupted"


def test_evaluation_verifies_evidence_and_refinement_creates_new_version(setup):
    repo, project, orch, _ = setup
    orch.run_analysis(project.project_id)
    orch.run_plan(project.project_id, orch.plan(project.project_id, ["notes", "quiz", "flashcards"]))
    topic_id = repo.list_topics(project.project_id)[0].topic_id
    record = orch.evaluate(project.project_id, topic_id)
    cov = {c["unit"]: c for c in record.report["coverage"]}
    assert cov["Bus topology"]["status"] == "covered" and cov["Bus topology"]["evidence_verified"]
    # evaluator claimed "covered" for Star but its quote is not in the notes -> downgraded
    assert cov["Star topology"]["status"] == "partial" and not cov["Star topology"]["evidence_verified"]
    assert record.coverage_score == 50.0
    assert record.evaluation_status == "needs_refinement"
    assert record.report["grounding"]["source_sections"] == 5

    before, after, applied = orch.refine(project.project_id, topic_id)
    assert applied == ["added: Star Topology Explained"]
    versions = repo.resource_versions(project.project_id, topic_id, "notes")
    assert versions[0].origin == "refined" and versions[0].version == 2
    assert after.report["refined_from_version"] == 1
    assert len(repo.list_evaluations(project.project_id, topic_id, latest_only=False)) == 2


def test_evaluator_failure_is_reported_not_faked(setup):
    repo, project, orch, fake = setup
    orch.run_analysis(project.project_id)
    orch.run_plan(project.project_id, orch.plan(project.project_id, ["notes"]))
    fake.overrides["quality_evaluation"] = {"broken": True}
    topic_id = repo.list_topics(project.project_id)[0].topic_id
    record = orch.evaluate(project.project_id, topic_id)
    assert record.evaluation_status == "incomplete"
    assert record.coverage_score is None and "evaluator_error" in record.report
    assert all(c["status"] != "covered" for c in record.report["coverage"])
