"""P01 - document understanding."""
from __future__ import annotations

from analyzer.domain_detector import detect_domain
from analyzer.sections import Section, outline_text
from prompt_engine.context_manager import format_source, source_budget
from prompt_engine.schemas.analysis import DocumentAnalysis
from prompt_engine.stage_runner import StageResult, StageRunner
from storage.models import ContentChunk


def representative_chunks(sections: list[Section], chunks: list[ContentChunk]) -> list[ContentChunk]:
    """First chunk of every section, in document order (spread across the whole material)."""
    by_id = {c.chunk_id: c for c in chunks}
    return [by_id[s.chunk_ids[0]] for s in sections if s.chunk_ids and s.chunk_ids[0] in by_id]


def run_document_analysis(runner: StageRunner, sections: list[Section], chunks: list[ContentChunk],
                          subject_hint: str = "", level_hint: str = "") -> StageResult:
    domain_hint, _ = detect_domain(" ".join(c.content for c in chunks[:400]))
    variables = {"subject_hint": subject_hint or "(not stated)", "level_hint": level_hint or "(not stated)",
                 "domain_hint": domain_hint, "outline": "", "source": ""}
    # Shrink the outline until at least ~600 tokens remain for excerpts (large documents / small contexts).
    for max_lines in (80, 40, 20, 10):
        variables["outline"] = outline_text(sections, max_lines=max_lines)
        probe = runner.build("document_analysis", variables)
        budget = source_budget(runner.settings.context_length, runner.max_output_for(probe), probe.system + probe.user)
        if budget >= 600:
            break
    reps = representative_chunks(sections, chunks)
    # Spread the budget across sections: cap each excerpt so many sections fit.
    per_chunk = max(300, int(budget * 3.3 / max(len(reps), 1)))
    bundle = format_source(reps, budget, max_chunk_chars=min(per_chunk, 1200))
    variables["source"] = bundle.text
    return runner.run("document_analysis", variables)


def fallback_analysis(chunks: list[ContentChunk], subject_hint: str = "") -> DocumentAnalysis:
    """Used only to keep the UI usable if P01 fails; clearly marked as heuristic."""
    domain, _ = detect_domain(" ".join(c.content for c in chunks[:400]))
    return DocumentAnalysis(subject=subject_hint or "Unknown subject", domain_category=domain if domain else "other",
                            subject_context="Heuristic placeholder: automatic analysis failed; please edit.",
                            purpose="unknown", estimated_level="unknown", major_concepts=[], key_terms=[],
                            prerequisites=[], gaps=["Automatic document analysis failed"], overlaps=[])
