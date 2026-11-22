"""Orchestrates the multi-stage prompt chain.

Analysis chain:   P01 document understanding -> P02 topic map -> P03 objectives -> P04 strategy
Generation chain: per topic, P05 notes -> P06..P10 resources (each sees a notes digest)
Quality loop:     P11 independent evaluation (+ deterministic checks) -> P12 targeted
                  refinement -> re-evaluation of the refined version

Every stage result is persisted as soon as it is produced; per-(topic, resource)
tasks record status so an interrupted run can be resumed without redoing
completed work.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from analyzer.document_analyzer import run_document_analysis
from analyzer.learning_objectives import run_learning_objectives, run_teaching_strategy
from analyzer.sections import build_sections
from analyzer.topic_mapper import run_topic_mapping
from config.logging_config import get_logger
from config.settings import Settings, get_settings
from evaluation.quality_evaluator import SUPPLEMENTARY_TYPES, evaluate_topic, findings_for_refinement
from evaluation.refiner import refine_notes
from generation.notes_generator import generate_notes
from generation.resource_generators import generate_resource
from generation.topic_context import load_topic_context
from prompt_engine.prompt_router import RESOURCE_LABELS, RESOURCE_TYPES
from prompt_engine.stage_runner import StageError, StageRunner
from providers.exceptions import ProviderError
from providers.provider_router import ProviderRouter
from storage.models import EvaluationRecord, GenerationTask, Resource
from storage.repository import Repository

log = get_logger("orchestrator")

ProgressCallback = Callable[[str, float], None]


def _noop(message: str, fraction: float) -> None:
    pass


@dataclass
class AnalysisOutcome:
    ok: bool
    warnings: list[str] = field(default_factory=list)
    error: str | None = None
    stages_completed: list[str] = field(default_factory=list)


@dataclass
class TaskOutcome:
    topic_id: str
    topic_title: str
    resource_type: str
    status: str  # done | failed | skipped
    message: str = ""


class Orchestrator:
    def __init__(self, repo: Repository, router: ProviderRouter, settings: Settings | None = None):
        self.repo = repo
        self.router = router
        self.settings = settings or get_settings()

    def runner(self, project_id: str) -> StageRunner:
        return StageRunner(self.router, self.settings, recorder=self.repo.save_stage_run, project_id=project_id)

    # ---------------------------------------------------------------- analysis
    def run_analysis(self, project_id: str, progress: ProgressCallback = _noop) -> AnalysisOutcome:
        project = self.repo.get_project(project_id)
        chunks = self.repo.list_chunks(project_id)
        if not chunks:
            return AnalysisOutcome(False, error="No extracted content. Upload documents and make sure extraction succeeded.")
        runner = self.runner(project_id)
        sections = build_sections(chunks)
        outcome = AnalysisOutcome(True)
        try:
            progress("P01 Document understanding: identifying subject, purpose and key concepts...", 0.05)
            p01 = run_document_analysis(runner, sections, chunks, project.subject or "", project.academic_level or "")
            analysis = p01.output.model_dump()
            subject = project.subject or analysis["subject"]
            self.repo.save_analysis(project_id, analysis=analysis)
            outcome.stages_completed.append("P01")

            progress("P02 Topic mapping: building the topic hierarchy...", 0.3)
            topics, warnings = run_topic_mapping(runner, sections, subject, analysis["subject_context"], project_id)
            outcome.warnings.extend(warnings)
            outcome.stages_completed.append("P02")

            progress("P03 Learning objectives...", 0.55)
            _, unmatched = run_learning_objectives(runner, topics, subject, project.academic_level or analysis["estimated_level"],
                                                   analysis["major_concepts"])
            if unmatched:
                outcome.warnings.append(f"No objectives were produced for: {', '.join(unmatched)} (you can add them manually).")
            outcome.stages_completed.append("P03")
            self.repo.replace_topics(project_id, topics)

            progress("P04 Teaching strategy selection...", 0.8)
            p04 = run_teaching_strategy(runner, topics, subject, analysis["domain_category"],
                                        project.academic_level or analysis["estimated_level"], analysis["subject_context"])
            self.repo.save_analysis(project_id, strategy=p04.output.model_dump())
            outcome.stages_completed.append("P04")
        except (StageError, ProviderError, ValueError) as exc:
            log.exception("Analysis failed")
            outcome.ok = False
            outcome.error = f"{exc.__class__.__name__}: {exc}"
            return outcome
        if not project.subject:
            project.subject = analysis["subject"]
        project.options = {**project.options, "domain_category": analysis["domain_category"]}
        self.repo.update_project(project)
        self.repo.log_activity(project_id, f"Analysis complete: {len([t for t in topics if t.parent_topic_id is None])} topics detected")
        progress("Analysis complete.", 1.0)
        return outcome

    def regenerate_strategy(self, project_id: str) -> None:
        project = self.repo.get_project(project_id)
        analysis = self.repo.get_analysis(project_id).get("analysis") or {}
        topics = self.repo.list_topics(project_id)
        p04 = run_teaching_strategy(self.runner(project_id), topics, project.subject or analysis.get("subject", ""),
                                    analysis.get("domain_category", "other"),
                                    project.academic_level or analysis.get("estimated_level", ""), analysis.get("subject_context", ""))
        self.repo.save_analysis(project_id, strategy=p04.output.model_dump())

    # -------------------------------------------------------------- generation
    def generate_one(self, project_id: str, topic_id: str, resource_type: str) -> TaskOutcome:
        topic = self.repo.get_topic(topic_id)
        task = self.repo.get_task(project_id, topic_id, resource_type) or GenerationTask(
            project_id=project_id, topic_id=topic_id, resource_type=resource_type)
        task.status, task.attempts, task.error = "running", task.attempts + 1, None
        self.repo.upsert_task(task)
        runner = self.runner(project_id)
        try:
            ctx = load_topic_context(self.repo, project_id, topic_id)
            if resource_type == "notes":
                content, results = generate_notes(runner, ctx)
                last = results[-1]
            else:
                content, last = generate_resource(runner, ctx, resource_type)
            self.repo.save_resource(Resource(project_id=project_id, topic_id=topic_id, resource_type=resource_type,
                                             content=content, prompt_id=last.template_id, prompt_version=last.version,
                                             provider=last.provider, model=last.model))
        except (StageError, ProviderError, ValueError) as exc:
            task.status, task.error = "failed", f"{exc.__class__.__name__}: {exc}"[:1500]
            self.repo.upsert_task(task)
            log.warning("Generation failed for %s/%s: %s", topic.title if topic else topic_id, resource_type, exc)
            return TaskOutcome(topic_id, topic.title if topic else "?", resource_type, "failed", task.error)
        task.status = "done"
        self.repo.upsert_task(task)
        self.repo.touch_project(project_id)
        return TaskOutcome(topic_id, topic.title, resource_type, "done", f"{RESOURCE_LABELS[resource_type]} generated")

    def plan(self, project_id: str, resource_types: list[str], topic_ids: list[str] | None = None,
             only_missing: bool = True) -> list[tuple[str, str]]:
        topics = [t for t in self.repo.list_topics(project_id) if t.parent_topic_id is None]
        if topic_ids:
            topics = [t for t in topics if t.topic_id in topic_ids]
        ordered_types = [r for r in RESOURCE_TYPES if r in resource_types]  # notes always first
        plan = []
        for t in topics:
            for rtype in ordered_types:
                if only_missing and self.repo.get_resource(project_id, t.topic_id, rtype) is not None:
                    continue
                plan.append((t.topic_id, rtype))
        return plan

    def run_plan(self, project_id: str, plan: list[tuple[str, str]], progress: ProgressCallback = _noop,
                 should_stop: Callable[[], bool] = lambda: False) -> list[TaskOutcome]:
        outcomes = []
        titles = {t.topic_id: t.title for t in self.repo.list_topics(project_id)}
        for i, (topic_id, rtype) in enumerate(plan):
            if should_stop():
                break
            progress(f"[{i + 1}/{len(plan)}] {RESOURCE_LABELS[rtype]} - {titles.get(topic_id, '')}", i / max(len(plan), 1))
            outcomes.append(self.generate_one(project_id, topic_id, rtype))
        done = sum(o.status == "done" for o in outcomes)
        if outcomes:
            self.repo.log_activity(project_id, f"Generated {done}/{len(outcomes)} resources")
        progress("Finished.", 1.0)
        return outcomes

    # ----------------------------------------------------------------- quality
    def evaluate(self, project_id: str, topic_id: str, extra: dict | None = None) -> EvaluationRecord:
        ctx = load_topic_context(self.repo, project_id, topic_id)
        notes_res = self.repo.get_resource(project_id, topic_id, "notes")
        if notes_res is None:
            raise ValueError("Generate lecture notes for this topic before evaluating it.")
        others = {}
        for rtype in SUPPLEMENTARY_TYPES:
            res = self.repo.get_resource(project_id, topic_id, rtype)
            if res:
                others[rtype] = res.content
        report = evaluate_topic(self.runner(project_id), ctx, notes_res.content, others)
        report["notes_version"] = notes_res.version
        report.update(extra or {})
        record = self.repo.save_evaluation(EvaluationRecord(
            project_id=project_id, topic_id=topic_id, resource_id=notes_res.resource_id,
            coverage_score=report.get("coverage_pct"), report=report, evaluation_status=report["status"]))
        return record

    def refine(self, project_id: str, topic_id: str) -> tuple[EvaluationRecord, EvaluationRecord, list[str]]:
        """Refine notes from the latest evaluation, save as a new version, then re-evaluate it."""
        evals = self.repo.list_evaluations(project_id, topic_id)
        before = evals[0] if evals else self.evaluate(project_id, topic_id)
        findings = findings_for_refinement(before.report)
        if not findings:
            raise ValueError("The latest evaluation has no findings to fix.")
        ctx = load_topic_context(self.repo, project_id, topic_id)
        notes_res = self.repo.get_resource(project_id, topic_id, "notes")
        updated, result, applied = refine_notes(self.runner(project_id), ctx, notes_res.content, findings)
        self.repo.save_resource(Resource(project_id=project_id, topic_id=topic_id, resource_type="notes", content=updated,
                                         prompt_id=result.template_id, prompt_version=result.version,
                                         provider=result.provider, model=result.model, origin="refined"))
        after = self.evaluate(project_id, topic_id, extra={"refined_from_version": notes_res.version,
                                                            "refinement_changes": applied,
                                                            "findings_addressed": findings})
        self.repo.log_activity(project_id, f"Refined notes for '{ctx.topic.title}' ({len(applied)} change(s))")
        return before, after, applied
