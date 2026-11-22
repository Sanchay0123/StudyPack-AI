"""Unit tests for the deterministic QA checks (coverage, grounding, consistency, refinement application)."""
from __future__ import annotations

from evaluation.consistency_checker import check_consistency
from evaluation.coverage_checker import compute_coverage, lexical_coverage
from evaluation.grounding_checker import check_grounding
from evaluation.quality_evaluator import decide_status, findings_for_refinement
from evaluation.refiner import apply_revisions
from evaluation.text_utils import numbers_in, quote_found, sentence_support
from prompt_engine.schemas.evaluation import NotesRefinement
from storage.models import ContentChunk

NOTES_TEXT = ("## Star topology\nIn a star topology every device connects to a central switch. If one cable fails, only that "
              "device is affected, but if the switch fails the whole network stops. This makes the switch a single point of failure "
              "that designers must protect with redundancy. Star networks are easy to extend because adding a device only needs one "
              "new cable to the switch.\n\n## Bus\nBus is mentioned.")


def test_quote_found_tolerates_formatting_but_rejects_fabrication():
    assert quote_found("every device connects to a **central switch**", NOTES_TEXT)
    assert not quote_found("ring topology passes a token around the loop", NOTES_TEXT)
    assert not quote_found("a b", NOTES_TEXT)  # too short to count as evidence


def test_heading_alone_does_not_count_as_lexical_coverage():
    assert lexical_coverage("Star topology", NOTES_TEXT)
    assert not lexical_coverage("Bus topology", "## Bus topology\nBus.")


def test_coverage_requires_verified_evidence():
    llm = [{"subtopic": "Star topology", "status": "covered", "evidence_quote": "every device connects to a central switch"},
           {"subtopic": "Ring topology", "status": "covered", "evidence_quote": "the token circulates around the ring"},
           {"subtopic": "Mesh", "status": "missing", "evidence_quote": ""}]
    results, pct, lexical = compute_coverage(["Star topology", "Ring topology", "Mesh"], NOTES_TEXT, llm)
    status = {r.unit: r.status for r in results}
    assert status == {"Star topology": "covered", "Ring topology": "partial", "Mesh": "missing"}
    assert pct == round(100 / 3, 1)


def test_coverage_without_evaluator_never_reports_covered():
    results, pct, _ = compute_coverage(["Star topology"], NOTES_TEXT, None)
    assert results[0].status == "partial" and pct == 0.0


def _chunk(cid, text):
    return ContentChunk(chunk_id=cid, document_id="d", project_id="p", seq=1, content=text, source_reference=f"doc {cid}")


def test_grounding_flags_uncited_and_unsupported_source_sections():
    chunks = {"c1": _chunk("c1", "In a star topology every device connects to a central switch. A switch failure stops the network.")}
    notes = {"_sources": {"S1": {"chunk_id": "c1", "ref": "doc c1"}}, "sections": [
        {"heading": "Good", "provenance": "source", "source_labels": ["S1"],
         "content": "Every device in a star topology connects to a central switch. A switch failure stops the whole network."},
        {"heading": "Uncited", "provenance": "source", "source_labels": [], "content": "Star topology uses a central switch device."},
        {"heading": "Invented", "provenance": "source", "source_labels": ["S1"],
         "content": "Quantum entanglement enables faster-than-light packet routing between galaxies. It was standardised in 1987 by NASA."},
        {"heading": "Background", "provenance": "supplementary", "source_labels": [], "content": "Unrelated helpful analogy about postal systems."},
    ]}
    report = check_grounding(notes, chunks)
    flags = {s["heading"]: s["flags"] for s in report["sections"]}
    assert flags["Good"] == []
    assert any("cites no source" in f for f in flags["Uncited"])
    assert any("weakly grounded" in f for f in flags["Invented"]) and any("1987" in f for f in flags["Invented"])
    assert flags["Background"] == []  # supplementary content is labelled, not penalised
    assert report["source_sections"] == 3 and report["well_grounded_source_sections"] == 1


def test_sentence_support_and_numbers():
    assert sentence_support("Switch failure stops the network entirely today.", "a switch failure stops the network") == 1.0
    assert numbers_in("In 1765, 3 machines, 9.81 m/s2 and 1,200 workers") == {"1765", "9.81", "1200"}


def test_consistency_detects_numbers_and_terms_not_in_notes_or_source():
    notes = {"overview": "", "summary": "", "key_terms": [], "sections": [{"content": "The spinning jenny was invented in 1764."}]}
    resources = {"flashcards": {"cards": [{"question": "When?", "answer": "In 1770."}]},
                 "revision": {"key_concepts": [], "key_definitions": [{"term": "Flying shuttle", "definition": "a loom part"}],
                              "formulas": [{"name": "Speed", "expression": "v = d/t", "meaning": ""}]},
                 "quiz": {"questions": [{"options": ["1764", "1770"], "correct_answers": ["1764"], "explanation": "1764"}]}}
    issues = check_consistency(notes, resources, source_text="Hargreaves 1764")["issues"]
    text = " ".join(i["issue"] + i["location"] for i in issues)
    assert "1770" in text and "Flying shuttle" in text and "formula" in text
    assert not any(i["resource"] == "quiz" for i in issues)


def test_status_and_findings():
    report = {"missing_units": ["Mesh"], "partial_units": [], "coverage": [{"unit": "Mesh", "status": "missing"}],
              "llm": {"verdict": "pass", "unsupported_claims": [{"severity": "high", "section": "X", "claim": "c", "reason": "r"}],
                      "factual_concerns": [], "mislabelled_provenance": [], "corrections": []},
              "grounding": {"flagged_sections": []}}
    assert decide_status(report) == "needs_refinement"
    clean = {"missing_units": [], "partial_units": [], "coverage": [], "grounding": {"flagged_sections": []},
             "llm": {"verdict": "needs_refinement", "unsupported_claims": [], "factual_concerns": []}}
    assert decide_status(clean) == "passed", "a bare verdict without findings must not fail a topic"
    findings = findings_for_refinement(report)
    assert findings[0].startswith("MISSING subtopic: 'Mesh'") and any("UNSUPPORTED (high)" in f for f in findings)
    assert decide_status({**report, "evaluator_error": "down"}) == "incomplete"


def test_apply_revisions_is_targeted():
    sec = lambda h, k="concept": {"heading": h, "kind": k, "content": h, "provenance": "source", "source_labels": []}  # noqa: E731
    notes = {"sections": [sec("Intro", "introduction"), sec("Star"), sec("Bus"), sec("Ring"), sec("Summary", "summary")]}
    refinement = NotesRefinement.model_validate({"revisions": [
        {"action": "replace", "target_heading": "star", "section": sec("Star (fixed)")},
        {"action": "add", "target_heading": "END", "section": sec("Mesh")},
        {"action": "remove", "target_heading": "Ring", "section": None}], "change_log": ["x"]})
    updated, applied = apply_revisions(notes, refinement)
    assert [s["heading"] for s in updated["sections"]] == ["Intro", "Star (fixed)", "Bus", "Mesh", "Summary"]
    assert len(applied) == 3 and [s["heading"] for s in notes["sections"]][1] == "Star", "original must be untouched"


def test_quote_matching_tolerates_word_forms_but_not_scrambles():
    notes = ("This layer manages the communication sessions between devices, establishing, maintaining, and terminating "
             "these connections. Star topology uses a switch.")
    assert quote_found("It establishes, maintains, and terminates these connections.", notes)
    assert not quote_found("switch establishes terminating ring connections devices", notes)
    assert not quote_found("TCP guarantees ordered and reliable delivery using sequence numbers", notes)


def test_refinement_fits_context_for_long_notes():
    """Regression: P12 overflowed the 8K window on a long topic; it must fall back to a targeted view."""
    from config.settings import Settings
    from evaluation.refiner import refine_notes, targeted_notes_view
    from generation.topic_context import TopicContext
    from prompt_engine.stage_runner import StageRunner
    from providers.provider_router import ProviderRouter
    from storage.models import Project, Topic
    from tests.fake_llm import FakeLLM

    long_section = lambda h: {"heading": h, "kind": "concept", "provenance": "source", "source_labels": [],  # noqa: E731
                              "content": "Detailed explanation of the layer. " * 120}
    notes = {"topic_title": "TCP/IP", "overview": "o", "summary": "s", "key_terms": [], "_sources": {},
             "sections": [long_section(f"Layer {i}") for i in range(8)]}
    findings = ["THIN coverage: 'Layer 3' is too brief", "CORRECTION for 'Layer 3': expand"]
    view = targeted_notes_view(notes, findings)
    assert "Layer 3 [provenance" in view and "Layer 5 (content omitted" in view
    chunk = ContentChunk(chunk_id="c1", document_id="d", project_id="p", seq=1, content="IP routes packets.", source_reference="doc")
    topic = Topic(project_id="p", title="TCP/IP", source_chunk_ids=["c1"])
    ctx = TopicContext(Project(name="x"), topic, [], {}, {}, [chunk])
    fake = FakeLLM()
    updated, _, applied = refine_notes(StageRunner(ProviderRouter(fake), Settings()), ctx, notes, findings)
    assert applied and "content omitted" in fake.calls[0].prompt
