"""Ingestion tests: every extractor, normalization, upload validation, failure handling."""
from __future__ import annotations

import pytest

from config.settings import get_settings
from ingestion.docx_extractor import extract_docx
from ingestion.normalizer import normalize
from ingestion.pdf_extractor import extract_pdf
from ingestion.pipeline import ingest_files
from ingestion.pptx_extractor import extract_pptx
from ingestion.text_extractor import extract_text
from ingestion.types import ExtractionError, RawBlock
from ingestion.upload_handler import UploadError, detect_file_type, sanitize_filename
from storage.database import Database
from storage.models import Project
from storage.repository import Repository
from tests import fixture_builders as fb


@pytest.fixture
def repo(tmp_path):
    return Repository(Database(tmp_path / "t.db"))


def test_pdf_extraction_headings_lists_code_pages(tmp_path):
    res = extract_pdf(str(fb.make_pdf(tmp_path / "net.pdf")))
    headings = [b for b in res.blocks if b.content_type == "heading"]
    assert [h.text for h in headings] == ["OSI Reference Model", "Transport Layer"]
    assert headings[1].page == 2
    assert any(b.content_type == "list" and "Data link" in b.text for b in res.blocks)
    assert any(b.content_type == "code" and "print" in b.text for b in res.blocks)
    assert not res.needs_ocr


def test_scanned_pdf_detected(tmp_path):
    res = extract_pdf(str(fb.make_scanned_pdf(tmp_path / "scan.pdf")))
    assert res.metadata["scanned_pages"] == [1]
    assert res.needs_ocr
    assert res.warnings


def test_corrupted_pdf_raises(tmp_path):
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"%PDF-1.4\n garbage garbage")
    with pytest.raises(ExtractionError):
        extract_pdf(str(bad))


def test_docx_extraction(tmp_path):
    res = extract_docx(str(fb.make_docx(tmp_path / "phys.docx")))
    types = [(b.content_type, b.text.split("\n")[0]) for b in res.blocks]
    assert ("heading", "Newton's Laws of Motion") in types
    assert any(t == "list" for t, _ in types)
    assert any(b.content_type == "table" and "| Force | N |" in b.text for b in res.blocks)


def test_corrupted_docx_raises(tmp_path):
    bad = tmp_path / "bad.docx"
    bad.write_bytes(b"PK\x03\x04 not really a zip")
    with pytest.raises(ExtractionError):
        extract_docx(str(bad))


def test_pptx_extraction_slides_notes_tables(tmp_path):
    res = extract_pptx(str(fb.make_pptx(tmp_path / "hist.pptx")))
    assert res.metadata["slides"] == 2
    assert res.blocks[0].content_type == "heading" and res.blocks[0].slide == 1
    assert any(b.content_type == "list" and "  - Availability of coal" in b.text for b in res.blocks)
    assert any(b.content_type == "slide_notes" for b in res.blocks)
    assert any(b.content_type == "table" and b.slide == 2 for b in res.blocks)


def test_markdown_extraction(tmp_path):
    res = extract_text(str(fb.make_markdown(tmp_path / "s.md")), markdown=True)
    kinds = [b.content_type for b in res.blocks]
    assert kinds.count("heading") == 2 and "code" in kinds and "table" in kinds and "list" in kinds


def test_text_extraction_detects_headings(tmp_path):
    res = extract_text(str(fb.make_text(tmp_path / "e.txt")), markdown=False)
    headings = [b.text for b in res.blocks if b.content_type == "heading"]
    assert "SUPPLY AND DEMAND" in headings and "1.1 Market Equilibrium" in headings


def test_normalizer_preserves_references_and_sections():
    blocks = [RawBlock("Intro", "heading", page=1, heading_level=1),
              RawBlock("A " * 400, "text", page=1),
              RawBlock("More text", "text", page=2),
              RawBlock("Details", "heading", page=3, heading_level=2),
              RawBlock("Detail text.", "text", page=3)]
    chunks = normalize(blocks, document_id="doc_abc123", project_id="p", document_name="Lecture.pdf", target_chars=300)
    assert all(c.source_reference.startswith("Lecture.pdf") for c in chunks)
    last = chunks[-1]
    assert last.heading == "Intro > Details" and last.page_number == 3
    assert "section \"Intro > Details\"" in last.source_reference
    assert len({c.section_id for c in chunks}) == 2
    assert len({c.chunk_id for c in chunks}) == len(chunks)


def test_sanitize_filename_blocks_traversal():
    assert sanitize_filename("../../etc/passwd") == "passwd"
    assert sanitize_filename("C:\\Windows\\evil.pdf") == "evil.pdf"
    assert "/" not in sanitize_filename("a/b<>:\"|?*.pdf")


def test_unsupported_and_spoofed_files_rejected():
    with pytest.raises(UploadError, match="unsupported"):
        detect_file_type("virus.exe", b"MZ")
    with pytest.raises(UploadError, match="not a PDF"):
        detect_file_type("fake.pdf", b"hello")
    with pytest.raises(UploadError, match="not a valid Office"):
        detect_file_type("old.docx", b"\xd0\xcf\x11\xe0")


def test_pipeline_end_to_end_with_duplicates_and_failures(repo, tmp_path):
    project = repo.create_project(Project(name="Test"))
    files = [
        ("net.pdf", fb.make_pdf(tmp_path / "net.pdf").read_bytes()),
        ("phys.docx", fb.make_docx(tmp_path / "phys.docx").read_bytes()),
        ("hist.pptx", fb.make_pptx(tmp_path / "hist.pptx").read_bytes()),
        ("notes.md", fb.make_markdown(tmp_path / "s.md").read_bytes()),
        ("econ.txt", fb.make_text(tmp_path / "e.txt").read_bytes()),
        ("net copy.pdf", (tmp_path / "net.pdf").read_bytes()),
        ("broken.pdf", b"%PDF-1.4 broken"),
        ("malware.exe", b"MZ..."),
        ("scan.pdf", fb.make_scanned_pdf(tmp_path / "scan.pdf").read_bytes()),
    ]
    reports = {r.filename: r for r in ingest_files(repo, project.project_id, files, settings=get_settings())}
    for name in ("net.pdf", "phys.docx", "hist.pptx", "notes.md", "econ.txt"):
        assert reports[name].status == "extracted", reports[name]
        assert reports[name].chunks > 0
    assert reports["net copy.pdf"].status == "duplicate"
    assert reports["broken.pdf"].status == "failed"
    assert reports["malware.exe"].status == "rejected"
    assert reports["scan.pdf"].status == "needs_ocr"
    chunks = repo.list_chunks(project.project_id)
    assert any(c.slide_number == 2 for c in chunks)
    assert any(c.page_number == 2 for c in chunks)
    assert len(repo.list_documents(project.project_id)) == 7  # duplicate + rejected not stored


def test_upload_size_limit(repo):
    from ingestion.upload_handler import store_upload
    project = repo.create_project(Project(name="Big"))
    small = get_settings().with_overrides(max_upload_mb=0)
    with pytest.raises(UploadError, match="limit"):
        store_upload(repo, small, project.project_id, "a.txt", b"x" * 10)


def test_reportlab_bullets_with_symbol_glyphs_are_not_headings(tmp_path):
    """Regression: ReportLab bullets are drawn in a symbol font PyMuPDF maps to U+FFFD and a larger size."""
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import ListFlowable, ListItem, Paragraph, SimpleDocTemplate

    styles = getSampleStyleSheet()
    path = tmp_path / "rl.pdf"
    SimpleDocTemplate(str(path)).build([
        Paragraph("Topologies", styles["Heading2"]),
        ListFlowable([ListItem(Paragraph("Bus topology shares one cable", styles["BodyText"])),
                      ListItem(Paragraph("Star topology uses a central switch", styles["BodyText"]))], bulletType="bullet"),
    ])
    res = extract_pdf(str(path))
    headings = [b.text for b in res.blocks if b.content_type == "heading"]
    assert headings == ["Topologies"]
    lists = [b.text for b in res.blocks if b.content_type == "list"]
    assert lists and "- Bus topology" in lists[0] and "- Star topology" in lists[0]


def test_ocr_path_integration_with_fake_engine(tmp_path, monkeypatch):
    """OCR wiring test. The Tesseract binary is replaced by a TEST FIXTURE function."""
    import ingestion.pdf_extractor as pdf_mod
    monkeypatch.setattr(pdf_mod, "ocr_available", lambda: True)
    monkeypatch.setattr(pdf_mod, "ocr_image", lambda image: ("Photosynthesis converts light energy.\n\nChlorophyll absorbs light.", 0.62))
    res = extract_pdf(str(fb.make_scanned_pdf(tmp_path / "scan.pdf")), use_ocr=True)
    assert res.ocr_applied and not res.needs_ocr
    texts = [b.text for b in res.blocks if b.content_type == "text"]
    assert texts == ["Photosynthesis converts light energy.", "Chlorophyll absorbs light."]
    assert all(b.needs_review and b.confidence == 0.62 for b in res.blocks if b.content_type == "text")
    assert res.metadata["ocr_mean_confidence"] == 0.62


def test_pdf_table_with_ruling_lines_is_extracted(tmp_path):
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle

    path = tmp_path / "table.pdf"
    t = Table([["Layer", "Protocol"], ["Transport", "TCP"], ["Network", "IP"]])
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, (0, 0, 0))]))
    SimpleDocTemplate(str(path)).build([t])
    res = extract_pdf(str(path))
    tables = [b.text for b in res.blocks if b.content_type == "table"]
    assert tables and "| Transport | TCP |" in tables[0]
