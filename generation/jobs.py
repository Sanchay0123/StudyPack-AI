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
    kind: str = "generation"  # generation | analysis

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


def start_analysis_job(project_id: str, orchestrator_factory: Callable[[], object]) -> Job:
    """Run the analysis chain (P01-P04) in the background. Shares the one-job-at-a-time lock with generation, so
    clicking "Run analysis" twice (or during a generation) cannot start a second competing run."""
    global _active
    with _lock:
        if _active and not _jobs[_active].finished:
            raise RuntimeError("Another job is already running; it must finish (or be stopped) first.")
        job = Job(project_id=project_id, total=100, kind="analysis")
        _jobs[project_id] = job
        _active = project_id

    def run():
        try:
            orch = orchestrator_factory()

            def progress(message: str, fraction: float):
                job.current = message
                job.done = int(min(max(fraction, 0.0), 1.0) * 100)

            outcome = orch.run_analysis(project_id, progress=progress)
            job.lines = list(outcome.warnings)
            if outcome.ok:
                job.status, job.done = "finished", 100
            else:
                job.status, job.error = "error", outcome.error or "Analysis failed"
                if outcome.stages_completed:
                    job.lines.append(f"Completed stages were saved: {', '.join(outcome.stages_completed)}.")
        except Exception as exc:  # noqa: BLE001 - surfaced in the UI
            log.exception("Analysis job crashed")
            job.status, job.error = "error", f"{exc.__class__.__name__}: {exc}"
        finally:
            job.current = ""

    threading.Thread(target=run, name=f"analysis-{project_id}", daemon=True).start()
    return job


def start_quality_job(project_id: str, topics: list[tuple[str, str]], mode: str,
                      orchestrator_factory: Callable[[], object]) -> Job:
    """Evaluate (mode="evaluation") or evaluate-then-refine (mode="refinement") many topics in the background.
    `topics` is a list of (topic_id, title). Shares the one-job-at-a-time lock."""
    global _active
    if mode not in ("evaluation", "refinement"):
        raise ValueError(f"Unknown quality job mode: {mode}")
    with _lock:
        if _active and not _jobs[_active].finished:
            raise RuntimeError("Another job is already running; it must finish (or be stopped) first.")
        job = Job(project_id=project_id, total=len(topics), kind=mode)
        _jobs[project_id] = job
        _active = project_id

    def run():
        try:
            orch = orchestrator_factory()
            for topic_id, title in topics:
                if job.stop_requested:
                    job.status = "stopped"
                    return
                if mode == "evaluation":
                    job.current = f"Evaluating — {title}"
                    try:
                        rec = orch.evaluate(project_id, topic_id)
                        cov = f"{rec.coverage_score:.0f}%" if rec.coverage_score is not None else "n/a"
                        job.done += 1
                        job.lines.append(f"✅ {title} — {rec.evaluation_status.replace('_', ' ')}, verified coverage {cov}")
                    except Exception as exc:  # noqa: BLE001 - one topic failing must not stop the batch
                        job.failed += 1
                        job.lines.append(f"❌ {title} — {exc.__class__.__name__}: {str(exc)[:200]}")
                else:
                    job.current = f"Evaluating / refining — {title}"
                    outcome = orch.refine_if_needed(project_id, topic_id)
                    if outcome.status == "failed":
                        job.failed += 1
                        job.lines.append(f"❌ {title} — {outcome.message}")
                    else:
                        job.done += 1
                        job.lines.append(f"{'✅' if outcome.status == 'done' else '➖'} {title} — {outcome.message}")
            job.status = "finished"
            verb = "Evaluated" if mode == "evaluation" else "Bulk refinement processed"
            orch.repo.log_activity(project_id, f"{verb} {job.done}/{job.total} topics")
        except Exception as exc:  # noqa: BLE001 - surfaced in the UI
            log.exception("Quality job crashed")
            job.status, job.error = "error", f"{exc.__class__.__name__}: {exc}"
        finally:
            job.current = ""

    threading.Thread(target=run, name=f"{mode}-{project_id}", daemon=True).start()
    return job


def request_stop(project_id: str) -> None:
    job = get_job(project_id)
    if job and not job.finished:
        job.stop_requested = True
