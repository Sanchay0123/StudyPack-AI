"""Dashboard: overview of study packs, recent activity, provider status."""
from __future__ import annotations

import streamlit as st

from config.settings import get_settings
from ui.common import get_repo, hero, local_time, pill, provider_statuses, stat_card


def render() -> None:
    hero("StudyPack AI", "Turn lecture PDFs, slides and notes into complete, source-grounded study packs.", "Dashboard")
    repo = get_repo()
    projects = repo.list_projects()
    settings = get_settings()
    statuses = provider_statuses(st.session_state.get("provider_choice", settings.default_provider))
    active = next((s for s in statuses if s["available"]), None)

    cols = st.columns(3)
    with cols[0]:
        stat_card("Study packs", str(len(projects)), "saved locally in SQLite")
    with cols[1]:
        total_resources = sum(len(repo.list_resources(p.project_id)) for p in projects)
        stat_card("Generated resources", str(total_resources), "current versions")
    with cols[2]:
        if active:
            stat_card("Active model", active["model"], f"via {active['provider']}")
        else:
            stat_card("Active model", "Unavailable", "see Models & Settings")

    if not active:
        st.error("No LLM provider is available. Start Ollama with `scripts\\start_ollama.ps1` "
                 "(or configure GEMINI_API_KEY), then press *Refresh status* on the Models & Settings page.")

    left, right = st.columns([3, 2], gap="large")
    with left:
        st.subheader("Your study packs")
        if not projects:
            st.info("No study packs yet. Create one to get started.")
        for p in projects:
            docs = repo.list_documents(p.project_id)
            topics = repo.list_topics(p.project_id)
            notes = repo.list_resources(p.project_id, "notes")
            with st.container(border=True):
                c1, c2 = st.columns([4, 1])
                with c1:
                    st.markdown(f"**{p.name}**")
                    subject = p.subject or "subject not detected yet"
                    st.markdown(
                        f"{pill(subject, 'muted')}{pill(f'{len(docs)} docs', 'muted')}"
                        f"{pill(f'{len([t for t in topics if t.parent_topic_id is None])} topics', 'muted')}"
                        f"{pill(f'{len(notes)} notes', 'ok' if notes else 'muted')}",
                        unsafe_allow_html=True)
                    st.caption(f"Updated {local_time(p.updated_at)}")
                with c2:
                    if st.button("Open", key=f"open_{p.project_id}"):
                        st.session_state["project_id"] = p.project_id
                        st.switch_page(st.session_state["_pages"]["analysis"])
        if st.button("Create a new study pack", type="primary"):
            st.switch_page(st.session_state["_pages"]["create"])
    with right:
        st.subheader("Recent activity")
        activity = repo.recent_activity()
        if not activity:
            st.caption("Nothing yet.")
        for a in activity:
            st.markdown(f"<div class='sp-ref'>{local_time(a['created_at'])} · {a.get('project_name') or ''}</div>"
                        f"{a['message']}", unsafe_allow_html=True)
