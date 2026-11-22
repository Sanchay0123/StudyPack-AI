"""StudyPack AI - Streamlit entry point.

Run with:  .venv\\Scripts\\streamlit run app.py
"""
from __future__ import annotations

import importlib

import streamlit as st

from config.logging_config import setup_logging

st.set_page_config(page_title="StudyPack AI", page_icon="📘", layout="wide")
setup_logging()

from ui.common import apply_style, render_sidebar  # noqa: E402

# (key, module, title, icon, section)
PAGE_SPECS = [
    ("dashboard", "ui.dashboard", "Dashboard", ":material/space_dashboard:", "Overview"),
    ("create", "ui.upload_page", "Create Study Pack", ":material/upload_file:", "Overview"),
    ("analysis", "ui.analysis_page", "Document Analysis", ":material/account_tree:", "Build"),
    ("generation", "ui.generation_page", "Generation Center", ":material/auto_awesome:", "Build"),
    ("notes", "ui.notes_page", "Lecture Notes", ":material/menu_book:", "Study"),
    ("revision", "ui.revision_page", "Revision Center", ":material/style:", "Study"),
    ("quiz", "ui.quiz_page", "Quiz Center", ":material/quiz:", "Study"),
    ("quality", "ui.evaluation_page", "Quality Report", ":material/fact_check:", "Review"),
    ("export", "ui.export_page", "Export", ":material/download:", "Review"),
    ("settings", "ui.settings_page", "Models & Settings", ":material/tune:", "System"),
]


def _build_pages():
    sections: dict[str, list] = {}
    registry = {}
    for key, module_name, title, icon, section in PAGE_SPECS:
        try:
            module = importlib.import_module(module_name)
        except ModuleNotFoundError as exc:
            if exc.name == module_name:
                continue  # page not implemented yet in this build
            raise
        page = st.Page(module.render, title=title, icon=icon, url_path=key, default=(key == "dashboard"))
        sections.setdefault(section, []).append(page)
        registry[key] = page
    return sections, registry


apply_style()
sections, registry = _build_pages()
st.session_state["_pages"] = registry
navigation = st.navigation(sections)
render_sidebar()
navigation.run()
