"""Regression tests from a real 14-deck / 560-slide course that overflowed P01 (context full, cut-off JSON)."""
from __future__ import annotations

import json

import prompt_engine.context_manager as cm
from analyzer.document_analyzer import representative_chunks
from analyzer.sections import build_sections, outline_text
from analyzer.topic_mapper import _batches
from config.settings import Settings
from prompt_engine.stage_runner import StageRunner, shrink_variables
from providers.base import BaseLLMProvider, GenerationResult, ProviderStatus
from providers.provider_router import ProviderRouter
from storage.models import ContentChunk
from tests.fake_llm import CANNED


def course(n_docs=14, slides=40):
    chunks = []
    for d in range(n_docs):
        for s in range(slides):
            chunks.append(ContentChunk(chunk_id=f"d{d}-c{s}", document_id=f"doc{d}", project_id="p", seq=s,
                                       document_name=f"L{d + 1}.pptx", content=f"Lecture {d + 1} slide {s} algorithm text " * 6,
                                       heading=f"Lecture {d + 1} topic {s}", section_id=f"d{d}-S{s}", slide_number=s + 1,
                                       source_reference=f"L{d + 1}.pptx, slide {s + 1}"))
    return chunks


def test_calibration_only_tightens_and_has_a_floor():
    saved = cm.CHARS_PER_TOKEN
    try:
        cm.CHARS_PER_TOKEN = 2.6
        assert cm.calibrate(19769, 7356) == round(19769 / 7356 * 0.95, 3)   # the real measurement: 2.69 -> 2.555
        assert cm.calibrate(40000, 4000) == round(19769 / 7356 * 0.95, 3)  # looser material never loosens it
        assert cm.calibrate(1000, 900) == cm.MIN_CHARS_PER_TOKEN
        assert cm.calibrate(500, 50) == cm.MIN_CHARS_PER_TOKEN             # tiny prompts are ignored
    finally:
        cm.CHARS_PER_TOKEN = saved


def test_outline_and_excerpts_cover_every_document():
    sections = build_sections(course())
    outline = outline_text(sections, max_lines=80)
    assert all(f"[L{d}.pptx]" in outline for d in range(1, 15)), "every lecture appears in the outline"
    assert len(outline.splitlines()) <= 80 + 14
    reps = representative_chunks(sections, course(), limit=28)
    assert {c.document_id for c in reps} == {f"doc{d}" for d in range(14)}
    assert len(reps) <= 28 + 14


def test_topic_map_batches_break_at_document_boundaries():
    sections = build_sections(course(n_docs=6, slides=10))
    lines = [f"{s.label} | {s.location} | x" for s in sections]
    batches = _batches(lines, 160, [s.document_name for s in sections])
    assert len(batches) > 1
    # No lecture is split across batches when it fits in one batch on its own.
    doc_of = {s.label: s.document_name for s in sections}
    owners = {}
    for i, batch in enumerate(batches):
        for line in batch:
            owners.setdefault(doc_of[line.split(" | ")[0]], set()).add(i)
    assert all(len(v) == 1 for v in owners.values())


def test_shrink_variables_drops_trailing_source_blocks():
    source = "<source_material>\n" + "\n".join(f"[S{i}] (doc, p. {i})\n" + "text " * 100 for i in range(1, 11)) + "\n</source_material>"
    shrunk, note = shrink_variables({"source": source, "subject": "x"}, excess_tokens=400)
    assert shrunk["source"].startswith("<source_material>\n[S1]") and shrunk["source"].endswith("</source_material>")
    assert "[S10]" not in shrunk["source"] and "[S1]" in shrunk["source"] and "dropped" in note
    assert shrink_variables({"subject": "x"}, 100) == (None, "nothing left to shrink")


class ContextFullThenOk(BaseLLMProvider):
    """TEST FIXTURE: first call reports a full context window and cut-off JSON; then answers properly."""
    name = "fake"

    def __init__(self):
        self.prompts = []

    def generate(self, request):
        self.prompts.append(request.prompt)
        if len(self.prompts) == 1:
            return GenerationResult('{"subject": "Algorithms", "major_conc', "fake", "m", 0.1,
                                    prompt_tokens=7480, output_tokens=712, truncated=True)
        return GenerationResult(json.dumps(CANNED["document_analysis"]), "fake", "m", 0.1, prompt_tokens=3000, output_tokens=500)

    def is_available(self):
        return ProviderStatus("fake", True, "m", "")

    def get_model_info(self):
        return {}


def test_context_full_is_detected_and_recovered_by_shrinking_source():
    fake = ContextFullThenOk()
    source = "<source_material>\n" + "\n".join(f"[S{i}] (L{i}.pptx, slide 1)\n" + "x " * 300 for i in range(1, 9)) + "\n</source_material>"
    variables = {"subject_hint": "-", "level_hint": "-", "domain_hint": "-", "outline": "o", "source": source}
    result = StageRunner(ProviderRouter(fake), Settings(context_length=8192)).run("document_analysis", variables)
    assert result.attempts == 2 and result.output.subject == "Computer Networks"
    assert "Context window full" in result.repairs[0][0]
    assert "previous_response" not in fake.prompts[1], "the cut-off output is not resent"
    assert fake.prompts[1].count("[S") < fake.prompts[0].count("[S")


def test_continuation_topics_are_merged():
    from analyzer.topic_mapper import _merge_duplicate_topics, base_title
    from storage.models import Topic
    for t in ["Dijkstra's Algorithm Execution Examples (Continued)", "Dijkstra's Algorithm Execution Examples (Final)",
              "Dijkstra's Algorithm Execution Examples (Advanced)", "Dijkstra's Algorithm Execution Examples - Part 2"]:
        assert base_title(t) == base_title("Dijkstra's Algorithm Execution Examples")
    assert base_title("Layer 7: Application") != base_title("Layer 6: Presentation")
    assert base_title("Huffman Encoding Fundamentals") != base_title("Huffman Code Construction Algorithm")
    a = Topic(project_id="p", title="DFS Examples", source_chunk_ids=["c1"])
    b = Topic(project_id="p", title="DFS Examples (Continued)", source_chunk_ids=["c2"])
    sa = Topic(project_id="p", parent_topic_id=a.topic_id, title="Tree edges")
    sb = Topic(project_id="p", parent_topic_id=b.topic_id, title="Tree edges")
    sb2 = Topic(project_id="p", parent_topic_id=b.topic_id, title="Back edges")
    merged = _merge_duplicate_topics([a, sa, b, sb, sb2])
    parents = [t for t in merged if t.parent_topic_id is None]
    assert [p.title for p in parents] == ["DFS Examples"] and parents[0].source_chunk_ids == ["c1", "c2"]
    assert sorted(t.title for t in merged if t.parent_topic_id) == ["Back edges", "Tree edges"]


def test_objectives_match_retyped_titles_and_failed_batches_do_not_abort():
    from analyzer.learning_objectives import match_entries, run_learning_objectives
    from prompt_engine.schemas.analysis import TopicObjectives
    from storage.models import Topic
    from tests.fake_llm import FakeLLM
    parents = [Topic(project_id="p", title="Dijkstra's Algorithm Time Complexity"), Topic(project_id="p", title="Huffman Tree Traversal")]
    entries = [TopicObjectives(topic_title="Dijkstras Algorithm - Time Complexity", objectives=["Analyse"], prerequisites=[]),
               TopicObjectives(topic_title="Traversing the Huffman tree", objectives=["Trace"], prerequisites=[])]
    matched = match_entries(parents, entries)
    assert matched[parents[0].topic_id].objectives == ["Analyse"] and matched[parents[1].topic_id].objectives == ["Trace"]
    fake = FakeLLM(overrides={"learning_objectives": {"topics": [{"topic_title": "Something else entirely", "objectives": ["x"], "prerequisites": []}]}})
    topics = [Topic(project_id="p", title=f"Topic {i}") for i in range(8)]
    result, unmatched = run_learning_objectives(StageRunner(ProviderRouter(fake), Settings()), topics, "s", "l", [])
    assert len(unmatched) == 8, "both batches failed, reported instead of raising"


def _refine_setup(tmp_path):
    from config.settings import get_settings
    from generation.topic_context import load_topic_context
    from ingestion.pipeline import ingest_files
    from prompt_engine.orchestrator import Orchestrator
    from storage.database import Database
    from storage.models import Project
    from storage.repository import Repository
    from tests.fake_llm import FakeLLM
    repo = Repository(Database(tmp_path / "r.db"))
    project = repo.create_project(Project(name="Refine"))
    ingest_files(repo, project.project_id, [("t.md", b"# T\n\n- Bus topology: shared cable.\n- Star topology: switch.\n")],
                 settings=get_settings())
    Orchestrator(repo, ProviderRouter(FakeLLM()), get_settings()).run_analysis(project.project_id)
    topic = [t for t in repo.list_topics(project.project_id) if t.parent_topic_id is None][0]
    return load_topic_context(repo, project.project_id, topic.topic_id)


def test_refinement_with_many_findings_and_long_notes_fits_the_context(tmp_path):
    """Real failure: 15 findings (~4k chars) naming most of ~12 long sections overflowed P12 on almost every topic."""
    from evaluation.refiner import FINDINGS_PER_PASS, refine_notes
    from tests.fake_llm import FakeLLM
    ctx = _refine_setup(tmp_path)
    sections = [{"heading": f"Section {i} on Dijkstra relaxation", "content": "Long explanation of the algorithm step. " * 60,
                 "provenance": "source", "source_labels": ["S1"], "kind": "concept"} for i in range(12)]
    notes = {"topic_title": ctx.topic.title, "overview": "Overview. " * 40, "sections": sections, "summary": "Summary.",
             "key_terms": [], "_sources": {}}
    findings = [f"UNSUPPORTED (medium) in section 'Section {i} on Dijkstra relaxation': \"{'claim text ' * 20}\" - "
                f"{'not in the source ' * 6}" for i in range(12)] + [f"THIN coverage: 'Unit {i}' is only mentioned." for i in range(3)]
    cm.CHARS_PER_TOKEN = 1.9  # calibrated down on dense slide material, as in the real run
    fake = FakeLLM()
    runner = StageRunner(ProviderRouter(fake), Settings(context_length=8192))
    updated, result, applied = refine_notes(runner, ctx, notes, findings)
    p12_calls = [c for c in fake.calls if "refinement" in c.metadata.get("template", "")]
    assert len(p12_calls) == -(-len(findings) // FINDINGS_PER_PASS), "findings are applied in groups"
    for call in p12_calls:
        assert cm.estimate_tokens(call.system + call.prompt) + call.max_tokens <= 8192
    assert any(a.startswith("added") for a in applied) and not any("skipped" in a and "finding" in a for a in applied)
    assert len(updated["sections"]) > len(sections)


def test_preflight_shrinks_instead_of_failing():
    from tests.fake_llm import FakeLLM
    fake = FakeLLM()
    runner = StageRunner(ProviderRouter(fake), Settings(context_length=4096, max_output_tokens=1024))
    variables = {"subject": "s", "topic_title": "t", "findings": "1. x", "section_headings": "a", "affected_sections": "a",
                 "notes_text": "Some notes line.\n" * 900, "source": ""}
    result = runner.run("refinement", variables)
    assert result.output is not None and len(fake.calls) == 1
    assert "shortened to fit the context window" in fake.calls[0].prompt
