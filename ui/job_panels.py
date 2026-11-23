"""Background analysis job: start + live progress panel (shared by the Create and Document Analysis pages)."""
from __future__ import annotations

import time

import streamlit as st

from config.settings import get_settings
from generation import jobs
from prompt_engine.orchestrator import Orchestrator
from storage.repository import Repository
from ui.common import get_router


def start_analysis(project_id: str) -> bool:
    router, settings = get_router(), get_settings()
    try:
        jobs.start_analysis_job(project_id, lambda: Orchestrator(Repository(), router, settings))
    except RuntimeError as exc:
        st.error(str(exc))
        return False
    return True


def analysis_running(project_id: str) -> bool:
    job = jobs.get_job(project_id)
    return job is not None and job.kind == "analysis" and not job.finished


def busy_elsewhere(project_id: str) -> str | None:
    """Message if another job (any project) holds the single local-inference slot."""
    active = jobs.active_job()
    if active is not None and not active.finished and not (active.project_id == project_id and active.kind == "analysis"):
        return (f"A {active.kind} job is running ({active.current or 'starting'}). Local inference runs one job at a time; "
                "this button is enabled again when it finishes.")
    return None


def start_quality(project_id: str, topics: list[tuple[str, str]], mode: str) -> bool:
    router, settings = get_router(), get_settings()
    try:
        jobs.start_quality_job(project_id, topics, mode, lambda: Orchestrator(Repository(), router, settings))
    except RuntimeError as exc:
        st.error(str(exc))
        return False
    return True


def any_job_running() -> str | None:
    active = jobs.active_job()
    if active is not None and not active.finished:
        return f"A {active.kind} job is running ({active.current or 'starting'}). Local inference runs one job at a time."
    return None


@st.fragment(run_every=3)
def quality_panel(project_id: str) -> None:
    job = jobs.get_job(project_id)
    if job is None or job.kind not in ("evaluation", "refinement"):
        return
    elapsed = (time.time() - job.started) / 60
    label = "Bulk evaluation" if job.kind == "evaluation" else "Bulk refinement"
    if not job.finished:
        st.progress(job.progress, text=f"{label}: {job.done + job.failed}/{job.total} topics · {job.current or 'starting...'} "
                                       f"· {elapsed:.1f} min elapsed")
        c1, c2 = st.columns([1, 4])
        if c1.button("Stop after this topic", key=f"stop_{job.kind}_{job.started}", disabled=job.stop_requested):
            jobs.request_stop(project_id)
        c2.caption("Runs on the server: you can leave this page. Each topic takes a few minutes on local hardware "
                   "(evaluation, and for refinement a P12 pass plus a re-evaluation).")
    else:
        msg = f"{label} {job.status}: {job.done} done, {job.failed} failed of {job.total} ({elapsed:.1f} min)."
        (st.error if job.status == "error" else st.success if not job.failed else st.warning)(
            msg + (f" {job.error}" if job.error else ""))
    if job.lines:
        with st.expander(f"Per-topic results ({len(job.lines)})", expanded=job.finished):
            st.markdown("\n".join(f"- {line}" for line in job.lines))
    if job.finished and not st.session_state.get(f"_quality_refreshed_{job.started}"):
        st.session_state[f"_quality_refreshed_{job.started}"] = True
        st.rerun(scope="app")


@st.fragment(run_every=3)
def analysis_panel(project_id: str) -> None:
    job = jobs.get_job(project_id)
    if job is None or job.kind != "analysis":
        return
    elapsed = (time.time() - job.started) / 60
    if not job.finished:
        st.progress(job.done / 100, text=f"{job.current or 'Starting analysis...'} · {elapsed:.1f} min elapsed")
        st.caption("Analysis runs on the server: you can leave this page and come back. Large courses take 10-20 minutes.")
        return
    if job.status == "finished":
        st.success(f"Analysis complete ({elapsed:.1f} min). Review the topic map below before generating.")
    else:
        st.error(f"Analysis failed: {job.error}")
    for line in job.lines:
        st.warning(line)
    if not st.session_state.get(f"_analysis_refreshed_{job.started}"):
        st.session_state[f"_analysis_refreshed_{job.started}"] = True
        st.rerun(scope="app")  # show the new topic map / subject on the full page
