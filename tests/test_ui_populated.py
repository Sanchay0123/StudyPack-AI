"""UI tests against a fully populated study pack (built offline with the FakeLLM test fixture)."""
from __future__ import annotations

import pytest
from streamlit.testing.v1 import AppTest

from config.settings import get_settings
from ingestion.pipeline import ingest_files
from prompt_engine.orchestrator import Orchestrator
from prompt_engine.prompt_router import RESOURCE_TYPES
from providers.provider_router import ProviderRouter
from storage.models import Project
from storage.repository import Repository
from tests.fake_llm import FakeLLM
from ui.quiz_logic import grade_choice, score, short_answer_overlap

DOC = b"# LAN Topologies\n\n- Bus topology: all devices share a single backbone cable.\n- Star topology: every device connects to a central switch.\n"


@pytest.fixture(scope="module")
def project_id():
    repo = Repository()  # the same (temporary) database the app uses in tests
    project = repo.create_project(Project(name="UI test pack"))
    ingest_files(repo, project.project_id, [("t.md", DOC)], settings=get_settings())
    orch = Orchestrator(repo, ProviderRouter(FakeLLM()), get_settings())
    assert orch.run_analysis(project.project_id).ok
    orch.run_plan(project.project_id, orch.plan(project.project_id, RESOURCE_TYPES))
    orch.evaluate(project.project_id, repo.list_topics(project.project_id)[0].topic_id)
    return project.project_id


def page(module: str, pid: str) -> AppTest:
    at = AppTest.from_string(f"""
import streamlit as st
st.session_state.setdefault('_pages', {{}})
from ui.common import apply_style
from ui import {module}
apply_style()
{module}.render()
""", default_timeout=60)
    at.session_state["project_id"] = pid
    return at


@pytest.mark.parametrize("module", ["analysis_page", "generation_page", "notes_page", "revision_page", "quiz_page",
                                    "evaluation_page", "export_page", "dashboard"])
def test_pages_render_with_content(module, project_id):
    at = page(module, project_id)
    at.run()
    assert not at.exception, [e.value for e in at.exception]


def test_notes_page_shows_sections_and_provenance(project_id):
    at = page("notes_page", project_id)
    at.run()
    text = " ".join(m.value for m in at.markdown)
    assert "Section 0" in text and "From source" in text and "t.md" in text


def test_quiz_hides_answers_until_submit_then_scores(project_id):
    at = page("quiz_page", project_id)
    at.run()
    assert not any("Correct answer" in m.value or "✅ **Correct**" in m.value for m in at.markdown)
    assert "Central switch." not in [i.value for i in at.info]  # explanation hidden
    for radio in at.radio:
        radio.set_value("Star")
    at.button[0].click()  # form submit
    at.run()
    at.run()
    text = " ".join(m.value for m in at.markdown)
    assert "✅ **Correct**" in text
    assert any(m.value == "4 / 4" for m in at.metric)


def test_quiz_logic():
    mcq = {"question_type": "mcq", "correct_answers": ["B"]}
    multi = {"question_type": "multi_select", "correct_answers": ["A", "C"]}
    assert grade_choice(mcq, "B") and not grade_choice(mcq, "A")
    assert grade_choice(multi, ["C", "A"]) and not grade_choice(multi, ["A"])
    short = {"question_type": "short_answer", "correct_answers": ["Bus topology shares one backbone cable"]}
    assert short_answer_overlap(short, "a bus shares one backbone cable") > 0.5
    correct, gradable, results = score([mcq, short], {0: "B"}, {})
    assert (correct, gradable, results) == (1, 1, [True, None])
    assert score([mcq, short], {0: "B"}, {1: False})[:2] == (1, 2)


def test_export_files_complete(project_id):
    from export.markdown_exporter import export_markdown
    from export.pdf_exporter import export_pdf
    repo = Repository()
    md = export_markdown(repo, project_id).read_text(encoding="utf-8")
    for heading in ["Lecture notes", "Worked examples", "Important questions", "Revision notes", "Flashcards", "Diagrams", "Practice quiz"]:
        assert f"### {heading}" in md
    assert "```mermaid" in md and "Answer key" in md and "From source" in md
    pdf = export_pdf(repo, project_id)
    import pymupdf
    doc = pymupdf.open(str(pdf))
    text = "".join(p.get_text() for p in doc)
    assert doc.page_count >= 3 and "Contents" in text and "Answer key" in text and "Page 2" in text


def test_export_marks_missing_resources(project_id):
    from export.collect import collect_pack
    from export.markdown_exporter import build_markdown
    repo = Repository()
    new = repo.create_project(Project(name="Empty"))
    from storage.models import Topic
    repo.replace_topics(new.project_id, [Topic(project_id=new.project_id, title="Lonely topic")])
    md = build_markdown(collect_pack(repo, new.project_id))
    assert md.count("_Not generated yet for this topic._") == len(RESOURCE_TYPES)


def test_generation_and_quality_buttons_work_through_ui():
    """Drives the Generation Center form and the Quality Report buttons with a FakeLLM router injected into the session."""
    repo = Repository()
    project = repo.create_project(Project(name="UI-driven pack"))
    ingest_files(repo, project.project_id, [("t.md", DOC)], settings=get_settings())
    assert Orchestrator(repo, ProviderRouter(FakeLLM()), get_settings()).run_analysis(project.project_id).ok

    at = page("generation_page", project.project_id)
    at.session_state["_router_ollama"] = ProviderRouter(FakeLLM())
    at.session_state["provider_choice"] = "ollama"
    at.run()
    start = next(b for b in at.button if b.label == "Start generation")
    start.click()
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    import time
    from generation import jobs
    deadline = time.time() + 30
    while time.time() < deadline and not jobs.get_job(project.project_id).finished:
        time.sleep(0.2)
    assert jobs.get_job(project.project_id).status == "finished"
    topic_id = repo.list_topics(project.project_id)[0].topic_id
    from prompt_engine.prompt_router import RESOURCE_TYPES as TYPES
    assert all(repo.get_resource(project.project_id, topic_id, r) for r in TYPES), "all resources generated via the UI"

    q = page("evaluation_page", project.project_id)
    q.session_state["_router_ollama"] = ProviderRouter(FakeLLM())
    q.session_state["provider_choice"] = "ollama"
    q.run()
    next(b for b in q.button if b.label == "Run evaluation (P11)").click()
    q.run()
    assert not q.exception, [e.value for e in q.exception]
    assert repo.list_evaluations(project.project_id, topic_id)
    next(b for b in q.button if b.label == "Refine notes (P12)").click()
    q.run()
    assert not q.exception, [e.value for e in q.exception]
    assert repo.get_resource(project.project_id, topic_id, "notes").origin == "refined"


def test_topic_editor_rename_edit_delete_add():
    repo = Repository()
    project = repo.create_project(Project(name="Editor pack"))
    ingest_files(repo, project.project_id, [("t.md", DOC)], settings=get_settings())
    from storage.models import Topic
    repo.replace_topics(project.project_id, [Topic(project_id=project.project_id, title="Old A"),
                                             Topic(project_id=project.project_id, title="Doomed B", order_index=1)])
    repo.save_analysis(project.project_id, analysis={"subject": "Networks", "domain_category": "computer_science",
                                                    "subject_context": "c", "estimated_level": "ug", "major_concepts": [],
                                                    "key_terms": [], "prerequisites": [], "gaps": [], "overlaps": []})
    a, b = [t for t in repo.list_topics(project.project_id)]
    at = page("analysis_page", project.project_id)
    at.run()
    at.text_input(key=f"t_{a.topic_id}").set_value("Renamed A")
    at.text_area(key=f"s_{a.topic_id}").set_value("Sub one\nSub two")
    at.text_area(key=f"ob_{a.topic_id}").set_value("Explain X")
    at.multiselect(key=f"sec_{a.topic_id}").set_value(["S1"])
    at.checkbox(key=f"x_{b.topic_id}").check()
    at.text_input(key="new_topic_title").set_value("Brand new")
    next(btn for btn in at.button if btn.label == "Save topic map").click()
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    topics = repo.list_topics(project.project_id)
    parents = [t for t in topics if t.parent_topic_id is None]
    assert [p.title for p in parents] == ["Renamed A", "Brand new"]
    renamed = parents[0]
    assert renamed.learning_objectives == ["Explain X"] and renamed.source_chunk_ids
    assert [t.title for t in topics if t.parent_topic_id == renamed.topic_id] == ["Sub one", "Sub two"]
