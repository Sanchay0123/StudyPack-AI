"""Generation Center: status matrix, background generation with live progress, stop, retry."""
from __future__ import annotations

import time

import pandas as pd
import streamlit as st

from config.settings import get_settings
from generation import jobs
from prompt_engine.orchestrator import Orchestrator
from prompt_engine.prompt_router import RESOURCE_LABELS, RESOURCE_TYPES
from storage.repository import Repository
from ui.common import get_repo, get_router, hero, require_project

ICON = {"done": "✅", "failed": "❌", "interrupted": "⏸", "running": "⏳", "pending": "·"}


def _matrix(project_id: str, parents) -> pd.DataFrame:
    repo = get_repo()
    tasks = {(t.topic_id, t.resource_type): t for t in repo.list_tasks(project_id)}
    rows = []
    for p in parents:
        row = {"Topic": p.title}
        for rtype in RESOURCE_TYPES:
            res = repo.get_resource(project_id, p.topic_id, rtype)
            task = tasks.get((p.topic_id, rtype))
            if task is not None and task.status == "running":
                row[RESOURCE_LABELS[rtype]] = "⏳ running"
            elif res is not None:
                row[RESOURCE_LABELS[rtype]] = f"✅ v{res.version}"
            elif task is not None:
                row[RESOURCE_LABELS[rtype]] = ICON.get(task.status, task.status)
            else:
                row[RESOURCE_LABELS[rtype]] = "—"
        rows.append(row)
    return pd.DataFrame(rows)


def _start(project_id: str, plan) -> None:
    if not plan:
        st.info("Nothing to generate: every selected resource already exists. Untick “Only missing” to regenerate.")
        return
    router, settings = get_router(), get_settings()
    try:
        jobs.start_job(project_id, plan, lambda: Orchestrator(Repository(), router, settings))
    except RuntimeError as exc:
        st.error(str(exc))
        return
    st.rerun()


@st.fragment(run_every=3)
def _job_panel(project_id: str, parents) -> None:
    job = jobs.get_job(project_id)
    if job is None:
        return
    elapsed = time.time() - job.started
    if job.finished:
        label = {"finished": "Finished", "stopped": "Stopped", "error": "Stopped by an error"}[job.status]
        kind = st.success if job.status == "finished" and not job.failed else st.warning
        kind(f"{label}: {job.done} generated, {job.failed} failed, of {job.total} planned ({elapsed / 60:.1f} min).")
        if job.error:
            st.error(job.error)
    else:
        st.progress(job.progress, text=f"[{job.done + job.failed + 1}/{job.total}] {job.current or 'starting...'} "
                                       f"· {elapsed / 60:.1f} min elapsed")
        if st.button("Stop after the current item", key="stop_job"):
            jobs.request_stop(project_id)
        st.caption("Generation runs on the server: you can open other pages (e.g. read finished notes) and come back.")
    if job.lines:
        with st.expander("Log", expanded=not job.finished):
            st.markdown("\n\n".join(job.lines[-15:]))
    st.dataframe(_matrix(project_id, parents), hide_index=True, use_container_width=True)


def render() -> None:
    project = require_project()
    hero(project.name, "Generate lecture notes and learning resources topic by topic. Progress is saved after every item.",
         "Generation Center")
    repo = get_repo()
    stale = repo.mark_stale_running_tasks(project.project_id)
    if stale:
        st.warning(f"{stale} task(s) were interrupted in a previous session and can be retried below.")
    parents = [t for t in repo.list_topics(project.project_id) if t.parent_topic_id is None]
    if not parents:
        st.info("Run the document analysis first to build the topic map.")
        return
    orch = Orchestrator(repo, get_router(), get_settings())
    statuses = get_router().statuses()
    if not any(s.available for s in statuses):
        st.error("No LLM provider is available: " + " | ".join(s.message for s in statuses))

    active = jobs.active_job()
    busy = active is not None and not active.finished
    st.subheader("Status")
    if jobs.get_job(project.project_id):
        _job_panel(project.project_id, parents)
    else:
        st.dataframe(_matrix(project.project_id, parents), hide_index=True, use_container_width=True)
    st.caption("✅ generated (version) · ⏳ running · ❌ failed · ⏸ interrupted · — not generated yet. Lecture notes are "
               "generated first because every other resource is built from them for consistency.")
    if busy and active.project_id != project.project_id:
        name = (repo.get_project(active.project_id) or project).name
        st.info(f"A generation job for “{name}” is running. Local inference is sequential, so new jobs can start when it finishes.")

    st.subheader("Generate")
    default_types = project.options.get("resources") or RESOURCE_TYPES
    with st.form("gen_form"):
        topic_ids = st.multiselect("Topics", [p.topic_id for p in parents], default=[p.topic_id for p in parents],
                                   format_func=lambda i: next(p.title for p in parents if p.topic_id == i))
        types = st.multiselect("Resources", RESOURCE_TYPES, default=[t for t in default_types if t in RESOURCE_TYPES],
                               format_func=lambda r: RESOURCE_LABELS[r])
        only_missing = st.checkbox("Only missing items (resume)", value=True,
                                   help="Untick to regenerate; previous versions are kept and can be viewed in the notes viewer.")
        go = st.form_submit_button("Start generation", type="primary", disabled=busy)
    if go:
        plan = orch.plan(project.project_id, types, topic_ids, only_missing=only_missing)
        st.caption(f"{len(plan)} item(s) planned, roughly {len(plan) * 0.5:.0f} min on local hardware.")
        _start(project.project_id, plan)

    failed = [t for t in repo.list_tasks(project.project_id) if t.status in ("failed", "interrupted")
              and repo.get_resource(project.project_id, t.topic_id, t.resource_type) is None]
    if failed:
        st.subheader("Failed or interrupted")
        titles = {p.topic_id: p.title for p in parents}
        for t in failed:
            c1, c2 = st.columns([5, 1])
            with c1:
                st.markdown(f"**{titles.get(t.topic_id, '?')} · {RESOURCE_LABELS[t.resource_type]}** — attempt {t.attempts}")
                st.caption(t.error or "")
            with c2:
                if st.button("Retry", key=f"retry_{t.topic_id}_{t.resource_type}", disabled=busy):
                    _start(project.project_id, [(t.topic_id, t.resource_type)])
        if st.button("Retry all failed", disabled=busy):
            _start(project.project_id, [(t.topic_id, t.resource_type) for t in failed])

    with st.expander("Prompt-stage log (most recent 50)"):
        runs = repo.list_stage_runs(project.project_id, limit=50)
        if runs:
            st.dataframe(pd.DataFrame([{"time": r.created_at[11:19], "stage": r.stage_id, "provider": r.provider, "model": r.model,
                                        "attempts": r.attempts, "ok": "✅" if r.success else "❌", "seconds": r.duration_s,
                                        "prompt tok": r.prompt_tokens, "output tok": r.output_tokens,
                                        "validation / error": (r.error or "")[:160]} for r in runs]),
                         hide_index=True, use_container_width=True)
