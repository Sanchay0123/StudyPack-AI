"""Background generation jobs.

Generation runs in a server-side thread, so the user can navigate the app (or close the tab) while a
study pack is being generated. Only one job runs at a time (sequential local inference). Every
completed item is persisted by the orchestrator as it finishes, so a stopped or crashed job loses
at most the item in progress.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Callable

from config.logging_config import get_logger
from prompt_engine.prompt_router import RESOURCE_LABELS

log = get_logger("jobs")


@dataclass
class Job:
    project_id: str
    total: int
    done: int = 0
    failed: int = 0
    current: str = ""
    lines: list[str] = field(default_factory=list)
    status: str = "running"  # running | finished | stopped | error
    error: str = ""
    started: float = field(default_factory=time.time)
    stop_requested: bool = False

    @property
    def finished(self) -> bool:
        return self.status != "running"

    @property
    def progress(self) -> float:
        return (self.done + self.failed) / self.total if self.total else 1.0


_lock = threading.Lock()
_jobs: dict[str, Job] = {}
_active: str | None = None


def active_job() -> Job | None:
    with _lock:
        return _jobs.get(_active) if _active else None


def get_job(project_id: str) -> Job | None:
    with _lock:
        return _jobs.get(project_id)


def start_job(project_id: str, plan: list[tuple[str, str]], orchestrator_factory: Callable[[], object]) -> Job:
    """Start a job; raises RuntimeError if another job is still running."""
    global _active
    with _lock:
        if _active and not _jobs[_active].finished:
            raise RuntimeError("Another generation job is already running; it must finish (or be stopped) first.")
        job = Job(project_id=project_id, total=len(plan))
        _jobs[project_id] = job
        _active = project_id

    def run():
        try:
            orch = orchestrator_factory()
            titles = {t.topic_id: t.title for t in orch.repo.list_topics(project_id)}
            for topic_id, rtype in plan:
                if job.stop_requested:
                    job.status = "stopped"
                    return
                job.current = f"{RESOURCE_LABELS[rtype]} — {titles.get(topic_id, '')}"
                outcome = orch.generate_one(project_id, topic_id, rtype)
                if outcome.status == "done":
                    job.done += 1
                    job.lines.append(f"✅ {outcome.topic_title} · {RESOURCE_LABELS[rtype]}")
                else:
                    job.failed += 1
                    job.lines.append(f"❌ {outcome.topic_title} · {RESOURCE_LABELS[rtype]} — {outcome.message[:200]}")
            job.status = "finished"
            orch.repo.log_activity(project_id, f"Generated {job.done}/{job.total} resources")
        except Exception as exc:  # noqa: BLE001 - surfaced in the UI
            log.exception("Generation job crashed")
            job.status, job.error = "error", f"{exc.__class__.__name__}: {exc}"
        finally:
            job.current = ""

    threading.Thread(target=run, name=f"gen-{project_id}", daemon=True).start()
    return job


def request_stop(project_id: str) -> None:
    job = get_job(project_id)
    if job and not job.finished:
        job.stop_requested = True
