"""Independent quality evaluation of a topic's notes (P11 + deterministic checks)."""
from __future__ import annotations

from typing import Any

from evaluation.consistency_checker import check_consistency
from evaluation.coverage_checker import compute_coverage, coverage_to_dicts
from evaluation.grounding_checker import check_grounding
from generation.notes_generator import notes_to_text
from generation.topic_context import TopicContext
from prompt_engine.context_manager import chars_per_token, format_source, select_chunks_for_topic, source_budget
from prompt_engine.stage_runner import StageError, StageRunner
from providers.exceptions import ProviderError

SUPPLEMENTARY_TYPES = ["examples", "questions", "revision", "flashcards", "diagrams", "quiz"]


def coverage_units(ctx: TopicContext) -> list[str]:
    return ctx.subtopic_titles or [ctx.topic.title]


def evaluate_topic(runner: StageRunner, ctx: TopicContext, notes: dict[str, Any],
                   other_resources: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    """Returns a report dict. Deterministic checks always run; the LLM evaluator may fail
    (e.g. provider down), in which case the report says so instead of inventing numbers."""
    chunks_by_id = {c.chunk_id: c for c in ctx.all_chunks}
    units = coverage_units(ctx)
    notes_text = notes_to_text(notes)
    report: dict[str, Any] = {"topic": ctx.topic.title, "units": units}

    llm_eval: dict[str, Any] | None = None
    variables = {"subject": ctx.subject, "topic_title": ctx.topic.title,
                 "subtopics": "\n".join(f"- {u}" for u in units), "notes_text": notes_text, "source": ""}
    try:
        probe = runner.build("quality_evaluation", variables)
        budget = source_budget(runner.settings.context_length, runner.max_output_for(probe), probe.system + probe.user)
        if budget < 600:
            # Long notes: keep provenance tags but cut the notes view so ~600 tokens remain for source evidence.
            # The cut is recorded so the report does not claim the full notes were reviewed.
            excess_chars = int((600 - budget) * chars_per_token()) + 200
            full = variables["notes_text"]
            variables["notes_text"] = full[: max(2000, len(full) - excess_chars)] + "\n[... notes truncated for the evaluator ...]"
            report["evaluated_notes_fraction"] = round(len(variables["notes_text"]) / len(full), 2)
            probe = runner.build("quality_evaluation", variables)
            budget = source_budget(runner.settings.context_length, runner.max_output_for(probe), probe.system + probe.user)
        chunks, _ = select_chunks_for_topic(ctx.topic_chunk_ids(), ctx.all_chunks, max(budget, 300), ctx.focus_text())
        variables["source"] = format_source(chunks, max(budget, 300)).text
        result = runner.run("quality_evaluation", variables)
        llm_eval = result.output.model_dump()
        report["evaluator"] = {"provider": result.provider, "model": result.model, "prompt": f"{result.template_id}@{result.version}",
                               "attempts": result.attempts}
    except (StageError, ProviderError, ValueError) as exc:
        report["evaluator_error"] = f"{exc.__class__.__name__}: {exc}"

    coverage, coverage_pct, lexical_pct = compute_coverage(units, notes_text, (llm_eval or {}).get("coverage"))
    report["coverage"] = coverage_to_dicts(coverage)
    report["coverage_pct"] = coverage_pct if llm_eval else None
    report["lexical_coverage_pct"] = lexical_pct
    report["missing_units"] = [c.unit for c in coverage if c.status == "missing"]
    report["partial_units"] = [c.unit for c in coverage if c.status == "partial"]
    report["grounding"] = check_grounding(notes, chunks_by_id)
    source_text = "\n".join(f"{chunks_by_id[c].heading or ''}\n{chunks_by_id[c].content}"
                            for c in ctx.topic_chunk_ids() if c in chunks_by_id)  # headings are source text too
    report["consistency"] = check_consistency(notes, other_resources or {}, source_text)
    if llm_eval:
        report["llm"] = llm_eval
    report["status"] = decide_status(report)
    return report


def decide_status(report: dict[str, Any]) -> str:
    if report.get("evaluator_error"):
        return "incomplete"
    """Status is driven only by concrete, listed findings.

    The evaluator's bare verdict is recorded in the report but does not by itself fail a topic:
    small models often answer "needs_refinement" without naming any problem, and an
    evidence-based QA step should not act on an unexplained verdict.
    """
    llm = report.get("llm", {})
    high = [c for c in llm.get("unsupported_claims", []) if c.get("severity") in ("high", "medium")]
    if report["missing_units"] or report["partial_units"] or high or llm.get("factual_concerns"):
        return "needs_refinement"
    return "passed"


def findings_for_refinement(report: dict[str, Any]) -> list[str]:
    """Turn a report into a concrete list of findings for P12."""
    findings = []
    for unit in report.get("missing_units", []):
        findings.append(f"MISSING subtopic: '{unit}' is not explained. Add a section that explains it using the source.")
    for c in report.get("coverage", []):
        if c["status"] == "partial":
            findings.append(f"THIN coverage: '{c['unit']}' is only mentioned or too briefly explained. Expand it.")
    llm = report.get("llm", {})
    for claim in llm.get("unsupported_claims", []):
        findings.append(f"UNSUPPORTED ({claim['severity']}) in section '{claim['section']}': \"{claim['claim']}\" - {claim['reason']}")
    for item in llm.get("factual_concerns", []):
        findings.append(f"FACTUAL CONCERN: {item}")
    for item in llm.get("mislabelled_provenance", []):
        findings.append(f"PROVENANCE: {item} - relabel as supplementary/inferred or ground it in the source.")
    for corr in llm.get("corrections", []):
        findings.append(f"CORRECTION for '{corr['section']}': {corr['problem']} -> {corr['instruction']}")
    for flagged in report.get("grounding", {}).get("flagged_sections", []):
        findings.append(f"GROUNDING in section '{flagged['heading']}': {'; '.join(flagged['flags'])}")
    return list(dict.fromkeys(findings))[:15]
