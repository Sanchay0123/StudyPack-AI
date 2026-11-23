"""P01 - document understanding."""
from __future__ import annotations

from analyzer.domain_detector import detect_domain
from analyzer.sections import Section, outline_text, spread
from prompt_engine.context_manager import chars_per_token, estimate_tokens, format_source, source_budget
from prompt_engine.schemas.analysis import DocumentAnalysis
from prompt_engine.stage_runner import StageResult, StageRunner
from storage.models import ContentChunk


EXCERPT_CHARS = 450


def representative_chunks(sections: list[Section], chunks: list[ContentChunk], limit: int | None = None) -> list[ContentChunk]:
    """First chunk of each section; if more than `limit`, a fair, evenly spaced sample from EVERY document."""
    by_id = {c.chunk_id: c for c in chunks}
    reps = [by_id[s.chunk_ids[0]] for s in sections if s.chunk_ids and s.chunk_ids[0] in by_id
            and not by_id[s.chunk_ids[0]].content.startswith("[Figure")]
    if limit is None or len(reps) <= limit:
        return reps
    per_doc: dict[str, list[ContentChunk]] = {}
    for c in reps:
        per_doc.setdefault(c.document_id, []).append(c)
    picked: list[ContentChunk] = []
    for group in per_doc.values():
        quota = max(1, limit * len(group) // len(reps))
        picked += spread(group, quota)
    order = {c.chunk_id: i for i, c in enumerate(reps)}
    return sorted(picked, key=lambda c: order[c.chunk_id])


def run_document_analysis(runner: StageRunner, sections: list[Section], chunks: list[ContentChunk],
                          subject_hint: str = "", level_hint: str = "") -> StageResult:
    domain_hint, _ = detect_domain(" ".join(c.content for c in spread(chunks, 400)))
    variables = {"subject_hint": subject_hint or "(not stated)", "level_hint": level_hint or "(not stated)",
                 "domain_hint": domain_hint, "outline": "", "source": ""}
    # Shrink the outline until at least ~600 tokens remain for excerpts (large documents / small contexts).
    for max_lines in (80, 40, 20, 10):
        variables["outline"] = outline_text(sections, max_lines=max_lines)
        probe = runner.build("document_analysis", variables)
        budget = source_budget(runner.settings.context_length, runner.max_output_for(probe), probe.system + probe.user)
        if budget >= 600:
            break
    # Short excerpts sampled fairly across all documents (not "first sections until the budget runs out").
    per_excerpt_tokens = estimate_tokens("x" * EXCERPT_CHARS) + 30
    reps = representative_chunks(sections, chunks, limit=max(1, budget // per_excerpt_tokens))
    per_chunk = max(EXCERPT_CHARS, int(budget * chars_per_token() / max(len(reps), 1)) - 120)
    bundle = format_source(reps, budget, max_chunk_chars=min(per_chunk, 1200))
    variables["source"] = bundle.text
    return runner.run("document_analysis", variables)


def fallback_analysis(chunks: list[ContentChunk], subject_hint: str = "") -> DocumentAnalysis:
    """Used only to keep the UI usable if P01 fails; clearly marked as heuristic."""
    domain, _ = detect_domain(" ".join(c.content for c in spread(chunks, 400)))
    return DocumentAnalysis(subject=subject_hint or "Unknown subject", domain_category=domain if domain else "other",
                            subject_context="Heuristic placeholder: automatic analysis failed; please edit.",
                            purpose="unknown", estimated_level="unknown", major_concepts=[], key_terms=[],
                            prerequisites=[], gaps=["Automatic document analysis failed"], overlaps=[])
