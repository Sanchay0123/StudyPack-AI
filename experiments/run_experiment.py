"""Prompt-engineering experiment: A (baseline) vs B (structured single prompt) vs C (multi-stage pipeline).

Usage (the project must already have been analysed and have pipeline notes, e.g. via scripts/run_pipeline.py):
    .venv\\Scripts\\python experiments\\run_experiment.py --project-id prj_xxx

What is measured (all from actual outputs; nothing is estimated):
  * Topic coverage (lexical, deterministic): share of topic-map units whose key terms are
    explained in a reasonably long passage of the output (same function for all approaches).
  * Blind LLM judge (X03): rubric scores 1-5 for completeness, source fidelity, readability,
    relevance; per-topic adequacy; list of unsupported claims. The judge is not told which
    approach produced the notes; provenance tags are stripped so formatting does not reveal it.
  * Unsupported numbers (deterministic): numbers in the output that do not occur in the source.
  * Cross-resource consistency (C only, from the pipeline's QA reports; A and B produce notes only).
  * Size: words and sections.
A CSV for optional human ratings (1-5) is written next to the results.

Approach C notes are the pipeline's *current* notes (after any P11/P12 refinement).
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config.logging_config import setup_logging  # noqa: E402
from config.settings import get_settings  # noqa: E402
from evaluation.coverage_checker import lexical_coverage  # noqa: E402
from evaluation.text_utils import numbers_in  # noqa: E402
from generation.notes_generator import notes_to_text  # noqa: E402
from prompt_engine.context_manager import estimate_tokens, format_source, source_budget  # noqa: E402
from prompt_engine.stage_runner import StageError, StageRunner  # noqa: E402
from providers.provider_router import ProviderRouter  # noqa: E402
from storage.repository import Repository  # noqa: E402

RESULTS_DIR = ROOT / "experiments" / "results"
RUNS_DIR = ROOT / "experiments" / "runs"


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def strip_provenance(md: str) -> str:
    return re.sub(r"\s*\[provenance:[^\]]*\]", "", md)


def structured_to_text(notes: dict) -> str:
    return strip_provenance(notes_to_text(notes, include_provenance=False))


def coverage_units(topics) -> list[str]:
    parents = [t for t in topics if t.parent_topic_id is None]
    units = []
    for p in parents:
        subs = [t.title for t in topics if t.parent_topic_id == p.topic_id]
        units += subs or [p.title]
    return units


def run(project_id: str, judge_ctx: int) -> Path:
    settings = get_settings()
    repo = Repository()
    project = repo.get_project(project_id)
    chunks = repo.list_chunks(project_id)
    topics = repo.list_topics(project_id)
    parents = [t for t in topics if t.parent_topic_id is None]
    router = ProviderRouter.from_settings(settings)
    runner = StageRunner(router, settings, recorder=repo.save_stage_run, project_id=project_id)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = RUNS_DIR / f"{stamp}_{project_id}"
    run_dir.mkdir(parents=True, exist_ok=True)
    source_text = "\n".join(f"{c.heading or ''}\n{c.content}" for c in chunks)  # headings are part of the source
    outputs: dict[str, str] = {}
    meta: dict[str, dict] = {}

    # ---- Approach A: baseline ------------------------------------------------
    probe = runner.build("baseline_notes", {"source": ""})
    budget = source_budget(settings.context_length, runner.max_output_for(probe), probe.system + probe.user)
    bundle_a = format_source(chunks, budget)
    t0 = time.time()
    text_a, _ = runner.run_text("baseline_notes", {"source": bundle_a.text})
    outputs["A"] = text_a
    meta["A"] = {"seconds": round(time.time() - t0, 1), "source_chunks_used": len(bundle_a.label_map),
                 "source_chunks_total": len(chunks), "calls": 1}
    log(f"A done ({meta['A']['seconds']}s)")

    # ---- Approach B: structured single prompt -------------------------------
    probe = runner.build("structured_notes", {"source": "", "subject": project.subject or ""})
    budget = source_budget(settings.context_length, runner.max_output_for(probe), probe.system + probe.user)
    bundle_b = format_source(chunks, budget)
    t0 = time.time()
    try:
        res_b = runner.run("structured_notes", {"source": bundle_b.text, "subject": project.subject or ""})
        outputs["B"] = structured_to_text(res_b.output.model_dump())
        meta["B"] = {"seconds": round(time.time() - t0, 1), "attempts": res_b.attempts, "calls": res_b.attempts,
                     "source_chunks_used": len(bundle_b.label_map), "source_chunks_total": len(chunks)}
    except StageError as exc:
        outputs["B"] = exc.last_output
        meta["B"] = {"seconds": round(time.time() - t0, 1), "failed_validation": str(exc)[:300]}
    log(f"B done ({meta['B']['seconds']}s)")

    # ---- Approach C: multi-stage pipeline (existing notes) --------------------
    parts, consistency_issues, evaluated = [], 0, 0
    source_labelled_text = []
    for p in parents:
        res = repo.get_resource(project_id, p.topic_id, "notes")
        if res:
            parts.append(structured_to_text(res.content))
            source_labelled_text += [s["content"] for s in res.content.get("sections", []) if s.get("provenance") == "source"]
    for ev in repo.list_evaluations(project_id):
        evaluated += 1
        consistency_issues += len(ev.report.get("consistency", {}).get("issues", []))
    runs = [r for r in repo.list_stage_runs(project_id, limit=2000) if r.stage_id[:3] in ("P01", "P02", "P03", "P04", "P05", "P11", "P12")]
    outputs["C"] = "\n\n".join(parts)
    meta["C"] = {"topics_with_notes": len(parts), "topics": len(parents), "calls": len(runs),
                 "seconds": round(sum(r.duration_s or 0 for r in runs), 1), "evaluated_topics": evaluated,
                 "consistency_issues": consistency_issues,
                 # Fidelity of what the pipeline itself labels as coming from the source (supplementary
                 # content is disclosed to the student, so it is reported separately rather than as fabrication).
                 "source_labelled_unsupported_numbers": sorted(numbers_in(" ".join(source_labelled_text)) - numbers_in(source_text))}
    log("C collected")

    for k, v in outputs.items():
        (run_dir / f"approach_{k}.md").write_text(v, encoding="utf-8")

    # ---- Measurements ------------------------------------------------------
    units = coverage_units(topics)
    judge_settings = settings.with_overrides(context_length=judge_ctx, max_output_tokens=1500)
    judge = StageRunner(router, judge_settings, recorder=repo.save_stage_run, project_id=project_id)
    results = {}
    for key, text in outputs.items():
        lexical = [u for u in units if lexical_coverage(u, text)]
        unsupported_numbers = sorted(numbers_in(text) - numbers_in(source_text))
        entry = {"words": len(text.split()), "sections": len(re.findall(r"(?m)^#{2,4} ", text)),
                 "words_per_unit": round(len(text.split()) / max(len(units), 1), 1),
                 "lexical_topic_coverage_pct": round(100 * len(lexical) / max(len(units), 1), 1),
                 "units_not_covered": [u for u in units if u not in lexical],
                 "unsupported_numbers": unsupported_numbers, **meta[key]}
        probe = judge.build("experiment_judge", {"topic_list": "\n".join(f"- {u}" for u in units), "notes_text": text, "source": ""})
        jbudget = source_budget(judge_ctx, judge.max_output_for(probe), probe.system + probe.user)
        if jbudget < 300:
            entry["judge_error"] = f"notes too long to judge within {judge_ctx} tokens (needs ~{estimate_tokens(text)} for notes)"
        else:
            try:
                verdict = judge.run("experiment_judge", {"topic_list": "\n".join(f"- {u}" for u in units), "notes_text": text,
                                                         "source": format_source(chunks, jbudget).text})
                v = verdict.output.model_dump()
                entry["judge"] = v
                entry["judge_prompt"] = f"{verdict.template_id}@{verdict.version}"
                entry["judge_topic_coverage_pct"] = round(100 * sum(t["adequately_covered"] for t in v["topic_coverage"]) /
                                                          max(len(v["topic_coverage"]), 1), 1)
            except Exception as exc:  # noqa: BLE001 - record, never invent
                entry["judge_error"] = f"{exc.__class__.__name__}: {str(exc)[:300]}"
        results[key] = entry
        log(f"measured {key}: words={entry['words']} lexical={entry['lexical_topic_coverage_pct']}% judge={entry.get('judge_topic_coverage_pct')}")

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"project_id": project_id, "project": project.name, "subject": project.subject, "timestamp": stamp,
               "model": settings.ollama_model if settings.default_provider == "ollama" else settings.gemini_model,
               "provider": settings.default_provider, "generation_context": settings.context_length, "judge_context": judge_ctx,
               "coverage_units": units, "results": results, "raw_outputs_dir": str(run_dir.relative_to(ROOT))}
    out = RESULTS_DIR / f"{stamp}_{re.sub(r'[^a-z0-9]+', '-', project.name.lower())}.json"
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    with open(out.with_suffix(".human_ratings.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["approach_blinded", "file", "completeness_1to5", "source_fidelity_1to5", "readability_1to5",
                    "relevance_1to5", "consistency_1to5", "unsupported_claims_count", "rater", "notes"])
        for i, key in enumerate(outputs):
            w.writerow([f"X{i + 1}", f"approach_{key}.md", "", "", "", "", "", "", "", ""])
    log(f"results written to {out}")
    return out


def summarize(paths: list[Path]) -> str:
    rows = ["| Material | Approach | Words | Words/unit | Lexical coverage | Judge coverage | Merely listed | Completeness | Fidelity | Readability | Relevance | Unsupported claims (judge) | Unsupported numbers |",
            "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    names = {"A": "A baseline", "B": "B structured", "C": "C multi-stage"}
    for path in paths:
        data = json.loads(path.read_text(encoding="utf-8"))
        for key, r in data["results"].items():
            j = r.get("judge") or {}
            rows.append(f"| {data['project']} | {names[key]} | {r['words']} | {r.get('words_per_unit', 'n/a')} | {r['lexical_topic_coverage_pct']}% | "
                        f"{str(r.get('judge_topic_coverage_pct', 'n/a')) + '%' if r.get('judge_topic_coverage_pct') is not None else 'n/a'} | "
                        f"{len(j['merely_listed_concepts']) if 'merely_listed_concepts' in j else 'n/a'} | {j.get('completeness', 'n/a')} | {j.get('source_fidelity', 'n/a')} | {j.get('readability', 'n/a')} | "
                        f"{j.get('relevance', 'n/a')} | {len(j.get('unsupported_claims', [])) if j else 'n/a'} | {len(r['unsupported_numbers'])} |")
    return "\n".join(rows)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project-id", action="append", help="repeat for several projects")
    ap.add_argument("--judge-context", type=int, default=16384)
    ap.add_argument("--summarize", nargs="*", type=Path, help="summarize existing result JSON files")
    args = ap.parse_args()
    setup_logging()
    if args.summarize is not None:
        files = args.summarize or sorted(RESULTS_DIR.glob("*.json"))
        print(summarize(files))
        return 0
    paths = [run(pid, args.judge_context) for pid in args.project_id or []]
    if paths:
        summary = summarize(paths)
        print(summary)
        (RESULTS_DIR / f"summary_{datetime.now().strftime('%Y%m%d-%H%M%S')}.md").write_text(summary + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
