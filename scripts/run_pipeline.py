"""Headless end-to-end runner (useful for validation, batch use and experiments).

Example:
    .venv\\Scripts\\python scripts\\run_pipeline.py --name "Networks" samples\\computer_networks_module1.pdf ^
        --resources notes,examples,questions,revision,flashcards,diagrams,quiz --evaluate --refine --export

Everything is persisted in the same SQLite database the Streamlit app uses,
so the resulting study pack can be opened in the UI afterwards.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.logging_config import setup_logging  # noqa: E402
from config.settings import get_settings  # noqa: E402
from ingestion.pipeline import ingest_files  # noqa: E402
from prompt_engine.orchestrator import Orchestrator  # noqa: E402
from prompt_engine.prompt_router import RESOURCE_TYPES  # noqa: E402
from providers.provider_router import ProviderRouter  # noqa: E402
from storage.models import Project  # noqa: E402
from storage.repository import Repository  # noqa: E402


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="*", type=Path)
    ap.add_argument("--name", default="CLI study pack")
    ap.add_argument("--project-id", help="Resume an existing project instead of creating one")
    ap.add_argument("--subject", default="")
    ap.add_argument("--level", default="")
    ap.add_argument("--provider", choices=["ollama", "gemini"], default=None)
    ap.add_argument("--resources", default="notes", help=f"comma list from {RESOURCE_TYPES} or 'all'")
    ap.add_argument("--max-topics", type=int, default=0, help="limit number of topics (0 = all)")
    ap.add_argument("--evaluate", action="store_true")
    ap.add_argument("--refine", action="store_true", help="refine topics whose evaluation needs it")
    ap.add_argument("--export", action="store_true")
    ap.add_argument("--skip-analysis", action="store_true")
    args = ap.parse_args()

    setup_logging()
    settings = get_settings()
    repo = Repository()
    router = ProviderRouter.from_settings(settings, primary_override=args.provider)
    for s in router.statuses():
        log(f"provider {s.provider}: {'available' if s.available else 'unavailable'} - {s.message}")
    orch = Orchestrator(repo, router, settings)

    if args.project_id:
        project = repo.get_project(args.project_id)
        if project is None:
            log("Unknown project id")
            return 2
        repo.mark_stale_running_tasks(project.project_id)
    else:
        project = repo.create_project(Project(name=args.name, subject=args.subject or None, academic_level=args.level or None))
    log(f"project {project.project_id} ({project.name})")

    if args.files:
        reports = ingest_files(repo, project.project_id, [(f.name, f.read_bytes()) for f in args.files])
        for r in reports:
            log(f"ingest {r.filename}: {r.status} - {r.message} {r.warnings or ''}")

    if not args.skip_analysis:
        t0 = time.time()
        outcome = orch.run_analysis(project.project_id, progress=lambda m, f: log(m))
        log(f"analysis ok={outcome.ok} in {time.time() - t0:.0f}s warnings={outcome.warnings} error={outcome.error}")
        if not outcome.ok:
            return 1
    analysis = repo.get_analysis(project.project_id)
    log("subject: " + json.dumps({k: analysis["analysis"][k] for k in ("subject", "domain_category", "estimated_level")}))
    log("strategy: " + json.dumps({k: (analysis.get("strategy") or {}).get(k) for k in ("example_style", "note_sections")}))
    topics = repo.list_topics(project.project_id)
    parents = [t for t in topics if t.parent_topic_id is None]
    for p in parents:
        subs = [t.title for t in topics if t.parent_topic_id == p.topic_id]
        log(f"topic: {p.title} ({len(p.source_chunk_ids)} chunks) subtopics={subs} objectives={len(p.learning_objectives)}")
    if args.max_topics:
        parents = parents[: args.max_topics]

    resources = RESOURCE_TYPES if args.resources == "all" else [r.strip() for r in args.resources.split(",") if r.strip()]
    plan = orch.plan(project.project_id, resources, [p.topic_id for p in parents])
    if plan:
        t0 = time.time()
        outcomes = orch.run_plan(project.project_id, plan, progress=lambda m, f: log(m))
        for o in outcomes:
            if o.status != "done":
                log(f"FAILED {o.topic_title}/{o.resource_type}: {o.message}")
        log(f"generation: {sum(o.status == 'done' for o in outcomes)}/{len(outcomes)} done in {time.time() - t0:.0f}s")

    if args.evaluate or args.refine:
        for p in parents:
            if repo.get_resource(project.project_id, p.topic_id, "notes") is None:
                continue
            t0 = time.time()
            ev = orch.evaluate(project.project_id, p.topic_id)
            r = ev.report
            log(f"eval {p.title}: status={ev.evaluation_status} coverage={r.get('coverage_pct')} lexical={r.get('lexical_coverage_pct')} "
                f"grounding={r['grounding'].get('grounding_rate')} unsupported={len(r.get('llm', {}).get('unsupported_claims', []))} "
                f"consistency_issues={len(r['consistency']['issues'])} err={r.get('evaluator_error')} ({time.time() - t0:.0f}s)")
            if args.refine and ev.evaluation_status == "needs_refinement":
                try:
                    before, after, applied = orch.refine(project.project_id, p.topic_id)
                    log(f"refine {p.title}: {applied} -> status={after.evaluation_status} coverage={after.report.get('coverage_pct')}")
                except Exception as exc:  # noqa: BLE001
                    log(f"refine {p.title} failed: {exc}")

    if args.export:
        from export.markdown_exporter import export_markdown
        from export.pdf_exporter import export_pdf
        md = export_markdown(repo, project.project_id)
        pdf = export_pdf(repo, project.project_id)
        log(f"exported {md} and {pdf}")
    log(f"done. project_id={project.project_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
