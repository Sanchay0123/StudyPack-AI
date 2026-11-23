"""Background generation jobs (offline, FakeLLM fixture)."""
from __future__ import annotations

import threading
import time

import pytest

from config.settings import get_settings
from generation import jobs
from ingestion.pipeline import ingest_files
from prompt_engine.orchestrator import Orchestrator
from providers.provider_router import ProviderRouter
from storage.database import Database
from storage.models import Project
from storage.repository import Repository
from tests.fake_llm import FakeLLM


def _wait(job, timeout=20):
    deadline = time.time() + timeout
    while time.time() < deadline and not job.finished:
        time.sleep(0.05)
    return job


@pytest.fixture
def ready(tmp_path):
    db = Database(tmp_path / "jobs.db")
    repo = Repository(db)
    project = repo.create_project(Project(name="Jobs"))
    ingest_files(repo, project.project_id, [("t.md", b"# T\n\n- Bus topology: shared cable.\n- Star topology: switch.\n")],
                 settings=get_settings())
    Orchestrator(repo, ProviderRouter(FakeLLM()), get_settings()).run_analysis(project.project_id)
    return db, repo, project


def test_job_runs_in_background_and_persists(ready):
    db, repo, project = ready
    orch = Orchestrator(repo, ProviderRouter(FakeLLM()), get_settings())
    plan = orch.plan(project.project_id, ["notes", "flashcards", "quiz"])
    job = _wait(jobs.start_job(project.project_id, plan, lambda: Orchestrator(Repository(db), ProviderRouter(FakeLLM()), get_settings())))
    assert job.status == "finished" and job.done == 3 and job.progress == 1.0
    assert orch.plan(project.project_id, ["notes", "flashcards", "quiz"]) == []


def test_only_one_job_at_a_time_and_stop(ready):
    db, repo, project = ready
    gate = threading.Event()

    class SlowLLM(FakeLLM):
        def generate(self, request):
            gate.wait(5)
            return super().generate(request)

    orch = Orchestrator(repo, ProviderRouter(FakeLLM()), get_settings())
    plan = orch.plan(project.project_id, ["notes", "examples", "questions"])
    job = jobs.start_job(project.project_id, plan, lambda: Orchestrator(Repository(db), ProviderRouter(SlowLLM()), get_settings()))
    with pytest.raises(RuntimeError, match="already running"):
        jobs.start_job("other", [], lambda: None)
    deadline = time.time() + 5
    while not job.current and time.time() < deadline:  # wait until the first item is in progress
        time.sleep(0.02)
    jobs.request_stop(project.project_id)
    gate.set()
    _wait(job)
    assert job.status == "stopped" and job.done == 1, "stops after the item in progress, keeping it"
    assert repo.get_resource(project.project_id, plan[0][0], "notes") is not None


def test_analysis_runs_as_background_job_and_blocks_a_second_run(tmp_path):
    db = Database(tmp_path / "a.db")
    repo = Repository(db)
    project = repo.create_project(Project(name="Analysis job"))
    ingest_files(repo, project.project_id, [("t.md", b"# T\n\n- Bus topology: shared cable.\n- Star topology: switch.\n")],
                 settings=get_settings())
    gate = threading.Event()

    class SlowLLM(FakeLLM):
        def generate(self, request):
            gate.wait(5)
            return super().generate(request)

    messages = []
    job = jobs.start_analysis_job(project.project_id, lambda: Orchestrator(Repository(db), ProviderRouter(SlowLLM()), get_settings()))
    assert job.kind == "analysis" and not job.finished
    with pytest.raises(RuntimeError, match="already running"):
        jobs.start_analysis_job(project.project_id, lambda: None)   # double click -> refused
    with pytest.raises(RuntimeError, match="already running"):
        jobs.start_job(project.project_id, [], lambda: None)          # generation meanwhile -> refused
    gate.set()
    _wait(job)
    assert job.status == "finished" and job.done == 100, job.error
    assert [t.title for t in repo.list_topics(project.project_id) if t.parent_topic_id is None] == ["LAN Topologies"]


def test_bulk_refinement_job_evaluates_then_refines_and_detects_stale_evaluations(ready):
    db, repo, project = ready
    factory = lambda: Orchestrator(Repository(db), ProviderRouter(FakeLLM()), get_settings())  # noqa: E731
    orch = factory()
    orch.run_plan(project.project_id, orch.plan(project.project_id, ["notes"]))
    topics = [(t.topic_id, t.title) for t in repo.list_topics(project.project_id) if t.parent_topic_id is None]
    tid = topics[0][0]
    assert orch.current_evaluation(project.project_id, tid) is None, "never evaluated"

    job = _wait(jobs.start_quality_job(project.project_id, topics, "refinement", factory))
    assert job.status == "finished" and job.kind == "refinement" and job.failed == 0 and job.done == len(topics)
    assert any("change(s), coverage" in line for line in job.lines), job.lines
    versions = repo.resource_versions(project.project_id, tid, "notes")
    assert versions[0].origin == "refined"
    current = orch.current_evaluation(project.project_id, tid)
    assert current is not None and current.report["notes_version"] == versions[0].version, "refined version was re-evaluated"

    # editing the notes makes the evaluation stale again
    from storage.models import Resource
    repo.save_resource(Resource(project_id=project.project_id, topic_id=tid, resource_type="notes",
                                content=versions[0].content, origin="edited"))
    assert orch.current_evaluation(project.project_id, tid) is None


def test_bulk_evaluation_job_and_skips_topics_without_notes(ready):
    db, repo, project = ready
    factory = lambda: Orchestrator(Repository(db), ProviderRouter(FakeLLM()), get_settings())  # noqa: E731
    topics = [(t.topic_id, t.title) for t in repo.list_topics(project.project_id) if t.parent_topic_id is None]
    outcome = factory().refine_if_needed(project.project_id, topics[0][0])
    assert outcome.status == "skipped" and "no lecture notes" in outcome.message
    factory().run_plan(project.project_id, factory().plan(project.project_id, ["notes"]))
    job = _wait(jobs.start_quality_job(project.project_id, topics, "evaluation", factory))
    assert job.status == "finished" and job.done == len(topics)
    assert len(repo.list_evaluations(project.project_id)) == len(topics)
    with pytest.raises(ValueError):
        jobs.start_quality_job(project.project_id, topics, "bogus", factory)
