"""Headless UI smoke tests using Streamlit's AppTest (each page script is executed)."""
from __future__ import annotations

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parent.parent / "app.py")
PAGE_MODULES = ["dashboard", "upload_page", "analysis_page", "generation_page", "notes_page",
                "revision_page", "quiz_page", "evaluation_page", "export_page", "settings_page"]


def test_app_starts_without_exceptions():
    at = AppTest.from_file(APP, default_timeout=60)
    at.run()
    assert not at.exception, [e.value for e in at.exception]


@pytest.mark.parametrize("module", PAGE_MODULES)
def test_page_renders(module):
    import importlib.util
    if importlib.util.find_spec(f"ui.{module}") is None:
        pytest.skip(f"ui.{module} not implemented in this build")
    script = f"""
import streamlit as st
st.session_state.setdefault('_pages', {{}})
from ui.common import apply_style
from ui import {module}
apply_style()
{module}.render()
"""
    at = AppTest.from_string(script, default_timeout=60)
    at.run()
    assert not at.exception, [e.value for e in at.exception]
