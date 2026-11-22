"""Large and multi-document handling: chunking, topic-map batching, multi-part notes (offline, FakeLLM fixture)."""
from __future__ import annotations

import re

import pytest

from config.settings import get_settings
from generation.notes_generator import generate_notes
from generation.topic_context import load_topic_context
from ingestion.pipeline import ingest_files
from prompt_engine.orchestrator import Orchestrator
from prompt_engine.stage_runner import StageRunner
from providers.provider_router import ProviderRouter
from storage.database import Database
from storage.models import Project
from storage.repository import Repository
from tests.fake_llm import CANNED, FakeLLM

PARAGRAPH = ("Thermodynamics studies energy transfer between systems. The first law states that energy is conserved, "
             "so the change in internal energy equals heat added minus work done by the system. ") * 6


def make_large_pdf(path, chapters=40, pages_per_chapter=2):
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate

    styles = getSampleStyleSheet()
    story = []
    for c in range(1, chapters + 1):
        story.append(Paragraph(f"Chapter {c}: Topic number {c}", styles["Heading1"]))
        for _ in range(pages_per_chapter):
            story += [Paragraph(PARAGRAPH, styles["BodyText"]) for _ in range(3)]
            story.append(PageBreak())
    SimpleDocTemplate(str(path)).build(story)
    return path


def topic_map_from_prompt(request):
    """Dynamic fixture: one topic per section ID present in this batch's index."""
    ids = re.findall(r"^(S\d+) \|", request.prompt, flags=re.M)
    return {"topics": [{"title": f"Topic for {sid}", "description": "d", "section_ids": [sid], "subtopics": []} for sid in ids[:20]]}


def objectives_from_prompt(request):
    titles = re.findall(r"^- (Topic for S\d+):", request.prompt, flags=re.M)
    return {"topics": [{"topic_title": t, "objectives": ["Explain it"], "prerequisites": []} for t in titles]}


@pytest.fixture
def large_project(tmp_path):
    repo = Repository(Database(tmp_path / "large.db"))
    project = repo.create_project(Project(name="Large"))
    big = make_large_pdf(tmp_path / "big.pdf")
    second = tmp_path / "extra.md"
    second.write_text("# Appendix\n\nEntropy measures disorder.\n", encoding="utf-8")
    reports = ingest_files(repo, project.project_id, [("big.pdf", big.read_bytes()), ("extra.md", second.read_bytes())],
                           settings=get_settings())
    assert [r.status for r in reports] == ["extracted", "extracted"]
    return repo, project


def test_large_pdf_chunking_preserves_pages_and_sections(large_project):
    repo, project = large_project
    chunks = repo.list_chunks(project.project_id)
    pdf_chunks = [c for c in chunks if c.document_name == "big.pdf"]
    assert len(pdf_chunks) > 50
    assert max(c.page_number for c in pdf_chunks) >= 75
    assert all(len(c.content) <= get_settings().chunk_target_chars * 1.6 for c in pdf_chunks)
    assert len({c.section_id for c in pdf_chunks}) == 40
    assert any(c.document_name == "extra.md" for c in chunks), "multi-document project keeps both sources"


def test_topic_mapping_batches_when_index_exceeds_budget(large_project):
    repo, project = large_project
    fake = FakeLLM(overrides={"topic_mapping": topic_map_from_prompt, "learning_objectives": objectives_from_prompt})
    small = get_settings().with_overrides(context_length=4096, max_output_tokens=1200)
    outcome = Orchestrator(repo, ProviderRouter(fake), small).run_analysis(project.project_id)
    assert outcome.ok, outcome.error
    assert any("batches" in w for w in outcome.warnings)
    topics = [t for t in repo.list_topics(project.project_id) if t.parent_topic_id is None]
    assert len(topics) > 20, "topics from several batches are combined (one batch is capped at 20 by the schema)"
    assigned = {c for t in topics for c in t.source_chunk_ids}
    assert assigned == {c.chunk_id for c in repo.list_chunks(project.project_id)}, "no source content lost"


def test_large_topic_notes_generated_in_parts_with_unique_labels(large_project):
    repo, project = large_project
    chunks = repo.list_chunks(project.project_id)
    from storage.models import Topic
    topic = Topic(project_id=project.project_id, title="Everything", source_chunk_ids=[c.chunk_id for c in chunks])
    repo.replace_topics(project.project_id, [topic])
    fake = FakeLLM()
    settings = get_settings().with_overrides(context_length=6000, max_output_tokens=2000)
    notes, results = generate_notes(StageRunner(ProviderRouter(fake), settings), load_topic_context(repo, project.project_id, topic.topic_id))
    meta = notes["_meta"]
    assert meta["parts"] > 1 and len(results) == meta["parts"]
    assert "PART 1 of" in fake.calls[0].prompt and "PART 2 of" in fake.calls[1].prompt
    labels = list(notes["_sources"])
    assert len(labels) == len(set(labels)) and labels[0] == "S1"
    assert len(notes["sections"]) == 5 * meta["parts"]
    assert meta["truncated"] is (meta["source_chunks_used"] < meta["source_chunks_total"])
    assert CANNED["lecture_notes"]["summary"] == notes["summary"]
