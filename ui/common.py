"""Shared UI helpers: styling, cached services, current-project state."""
from __future__ import annotations

import html

import streamlit as st

from config.settings import get_settings
from providers.provider_router import ProviderRouter
from storage.models import Project
from storage.repository import Repository

CSS = """
<style>
.block-container {padding-top: 2.2rem; max-width: 1180px;}
h1, h2, h3 {letter-spacing: -0.01em;}
.sp-hero {padding: 0.2rem 0 0.8rem 0; border-bottom: 1px solid #E2DED5; margin-bottom: 1.2rem;}
.sp-hero .eyebrow {font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.12em; color: #6B7280; margin-bottom: 0.2rem;}
.sp-hero .title {font-family: Georgia, 'Times New Roman', serif; font-size: 2.0rem; font-weight: 600; color: #1F2933; line-height: 1.15;}
.sp-hero .subtitle {color: #52606D; margin-top: 0.35rem; font-size: 0.98rem;}
.sp-card {border: 1px solid #E2DED5; border-radius: 10px; padding: 0.9rem 1rem; background: #FFFFFF; margin-bottom: 0.7rem;}
.sp-card .k {font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.08em; color: #6B7280;}
.sp-card .v {font-size: 1.35rem; font-weight: 600; color: #1F2933; margin-top: 0.1rem;}
.sp-card .s {font-size: 0.82rem; color: #6B7280; margin-top: 0.15rem;}
.sp-pill {display: inline-block; padding: 0.08rem 0.55rem; border-radius: 999px; font-size: 0.74rem; font-weight: 600; margin-right: 0.3rem;}
.sp-ok {background: #E3F1E6; color: #1E6B34;}
.sp-warn {background: #FBF0D9; color: #8A5A00;}
.sp-bad {background: #F9E1E0; color: #9B2C2C;}
.sp-muted {background: #ECEAE4; color: #52606D;}
.sp-prov-source {border-left: 3px solid #2F5D8A; padding-left: 0.8rem;}
.sp-prov-supplementary {border-left: 3px solid #C98A1B; padding-left: 0.8rem;}
.sp-prov-inferred {border-left: 3px solid #9B2C2C; padding-left: 0.8rem;}
.sp-ref {font-size: 0.78rem; color: #6B7280;}
.sp-flash {border: 1px solid #E2DED5; border-radius: 14px; background: #FFFFFF; padding: 2.2rem 1.6rem; min-height: 190px;
           display: flex; align-items: center; justify-content: center; text-align: center; font-size: 1.15rem;}
</style>
"""


def apply_style() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def hero(title: str, subtitle: str = "", eyebrow: str = "") -> None:
    st.markdown(
        f"<div class='sp-hero'><div class='eyebrow'>{html.escape(eyebrow)}</div>"
        f"<div class='title'>{html.escape(title)}</div>"
        f"<div class='subtitle'>{html.escape(subtitle)}</div></div>",
        unsafe_allow_html=True,
    )


def stat_card(label: str, value: str, sub: str = "") -> None:
    st.markdown(f"<div class='sp-card'><div class='k'>{html.escape(label)}</div><div class='v'>{html.escape(str(value))}</div>"
                f"<div class='s'>{html.escape(sub)}</div></div>", unsafe_allow_html=True)


def local_time(iso: str) -> str:
    """Stored timestamps are UTC ISO strings; show them in the user's local time."""
    from datetime import datetime
    try:
        return datetime.fromisoformat(iso).astimezone().strftime("%Y-%m-%d %H:%M")
    except (ValueError, TypeError):
        return iso[:16].replace("T", " ")


def pill(text: str, kind: str = "muted") -> str:
    return f"<span class='sp-pill sp-{kind}'>{html.escape(text)}</span>"


@st.cache_resource
def get_repo() -> Repository:
    return Repository()


def get_router(primary_override: str | None = None) -> ProviderRouter:
    primary = primary_override or st.session_state.get("provider_choice") or get_settings().default_provider
    key = f"_router_{primary}"
    if key not in st.session_state:
        st.session_state[key] = ProviderRouter.from_settings(get_settings(), primary_override=primary)
    return st.session_state[key]


@st.cache_data(ttl=15, show_spinner=False)
def provider_statuses(primary: str) -> list[dict]:
    router = ProviderRouter.from_settings(get_settings(), primary_override=primary)
    return [s.__dict__ for s in router.statuses()]


def current_project() -> Project | None:
    project_id = st.session_state.get("project_id")
    if not project_id:
        return None
    return get_repo().get_project(project_id)


def require_project() -> Project:
    project = current_project()
    if project is None:
        st.info("Select a study pack in the sidebar, or create one on the **Create Study Pack** page.")
        st.stop()
    return project


def render_sidebar() -> None:
    repo = get_repo()
    projects = repo.list_projects()
    with st.sidebar:
        st.markdown("### StudyPack AI")
        if projects:
            ids = [p.project_id for p in projects]
            linked = st.query_params.get("project")  # deep link: ?project=<id>
            if linked in ids and st.session_state.get("_linked") != linked:
                st.session_state["project_id"] = linked
                st.session_state["_linked"] = linked
            current = st.session_state.get("project_id")
            index = ids.index(current) if current in ids else 0
            choice = st.selectbox("Study pack", ids, index=index, format_func=lambda i: next(p.name for p in projects if p.project_id == i))
            st.session_state["project_id"] = choice
        else:
            st.caption("No study packs yet.")
        settings = get_settings()
        options = ["ollama", "gemini"]
        default = st.session_state.get("provider_choice", settings.default_provider)
        st.session_state["provider_choice"] = st.selectbox(
            "Primary provider", options, index=options.index(default) if default in options else 0,
            help=f"Fallback provider: {settings.fallback_provider}. Change defaults in .env.")
        statuses = provider_statuses(st.session_state["provider_choice"])
        for s in statuses:
            kind = "ok" if s["available"] else "bad"
            st.markdown(f"{pill(s['provider'], kind)} <span class='sp-ref'>{html.escape(s['model'])}</span>", unsafe_allow_html=True)
