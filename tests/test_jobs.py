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
