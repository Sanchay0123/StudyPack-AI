"""Quality Report: evidence-based coverage, grounding, consistency, evaluator findings, refinement."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from config.settings import get_settings
from evaluation.evaluation_metrics import project_summary
from prompt_engine.orchestrator import Orchestrator
from ui.common import get_repo, get_router, hero, local_time, pill, require_project, stat_card
from ui.components import empty_state

STATUS_KIND = {"passed": "ok", "needs_refinement": "warn", "incomplete": "bad"}


def _report(report: dict) -> None:
    llm = report.get("llm") or {}
    if report.get("evaluator_error"):
        st.error(f"The independent evaluator did not complete, so no coverage score is shown: {report['evaluator_error']}")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        stat_card("Verified coverage", f"{report['coverage_pct']:.0f}%" if report.get("coverage_pct") is not None else "n/a",
                  "evaluator + evidence check")
    with c2:
        stat_card("Term coverage", f"{report['lexical_coverage_pct']:.0f}%", "lexical heuristic")
    with c3:
        g = report["grounding"].get("grounding_rate")
        stat_card("Grounded source sections", f"{g:.0f}%" if g is not None else "n/a",
                  f"{report['grounding']['well_grounded_source_sections']}/{report['grounding']['source_sections']} sections")
    with c4:
        stat_card("Readability", f"{llm.get('readability', '–')}/5" if llm else "n/a", f"relevance {llm.get('subject_relevance', '–')}/5" if llm else "")

    st.markdown("##### Coverage by subtopic")
    st.dataframe(pd.DataFrame([{"Subtopic": c["unit"], "Status": c["status"], "Evaluator said": c["llm_status"] or "—",
                                "Evidence verified": "✅" if c["evidence_verified"] else "✗",
                                "Evidence / note": c["evidence"][:140] or c["note"]} for c in report["coverage"]]),
                 hide_index=True, use_container_width=True)
    share = report["grounding"]["provenance_share"]
    st.markdown("##### Provenance of the notes")
    st.markdown(f"{pill(f'source {share.get('source', 0):.0f}%', 'ok')}{pill(f'supplementary {share.get('supplementary', 0):.0f}%', 'warn')}"
                f"{pill(f'inferred {share.get('inferred', 0):.0f}%', 'bad')}", unsafe_allow_html=True)
    with st.expander("Section-level grounding"):
        st.dataframe(pd.DataFrame([{"Section": s["heading"], "Provenance": s["provenance"], "Cites": ", ".join(s["references"])[:120],
                                    "Sentence support": s["support"], "Flags": "; ".join(s["flags"])} for s in report["grounding"]["sections"]]),
                     hide_index=True, use_container_width=True)
    if llm.get("unsupported_claims"):
        st.markdown("##### Unsupported claims (independent evaluator)")
        for c in llm["unsupported_claims"]:
            st.markdown(f"{pill(c['severity'], 'bad' if c['severity'] == 'high' else 'warn')} **{c['section']}** — “{c['claim']}”  \n"
                        f"<span class='sp-ref'>{c['reason']}</span>", unsafe_allow_html=True)
    for title, key in (("Factual concerns", "factual_concerns"), ("Provenance problems", "mislabelled_provenance"),
                       ("Structural issues", "structural_issues")):
        if llm.get(key):
            st.markdown(f"##### {title}")
            st.markdown("\n".join(f"- {x}" for x in llm[key]))
    issues = report["consistency"]["issues"]
    st.markdown("##### Cross-resource consistency")
    if issues:
        st.dataframe(pd.DataFrame(issues), hide_index=True, use_container_width=True)
    else:
        st.caption(f"No issues found across: {', '.join(report['consistency']['checked_resources']) or 'no other resources yet'}.")
    if llm.get("corrections"):
        with st.expander("Corrections recommended by the evaluator"):
            st.markdown("\n".join(f"- **{c['section']}**: {c['problem']} → {c['instruction']}" for c in llm["corrections"]))
    if report.get("refinement_changes"):
        st.success("This evaluation is of a refined version. Changes made: " + "; ".join(report["refinement_changes"]))
    if report.get("evaluator"):
        st.caption(f"Evaluator: {report['evaluator']['model']} via {report['evaluator']['provider']} · {report['evaluator']['prompt']} · "
                   f"notes version {report.get('notes_version')}")


def render() -> None:
    project = require_project()
    hero(project.name, "Independent evaluation of the generated notes. All numbers come from actual checks; nothing is estimated.",
         "Quality Report")
    repo = get_repo()
    parents = [t for t in repo.list_topics(project.project_id) if t.parent_topic_id is None]
    with_notes = [p for p in parents if repo.get_resource(project.project_id, p.topic_id, "notes")]
    if not with_notes:
        empty_state("Generate lecture notes first; evaluation checks notes against the source and the topic map.")
        return
    orch = Orchestrator(repo, get_router(), get_settings())
    summary = project_summary(repo, project.project_id)
    st.subheader("Study pack overview")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        stat_card("Topics evaluated", f"{summary['evaluated']}/{summary['topics']}", f"{summary['with_notes']} with notes")
    with c2:
        stat_card("Mean verified coverage", f"{summary['mean_coverage']:.0f}%" if summary["mean_coverage"] is not None else "n/a",
                  "over evaluated topics")
    with c3:
        stat_card("Missing subtopics", str(summary["missing_units"]), f"{summary['partial_units']} partially covered")
    with c4:
        stat_card("Unsupported claims", str(summary["unsupported_claims"]), f"{summary['high_severity']} high severity")
    if summary["missing_topics"]:
        st.warning("Topics without notes: " + ", ".join(summary["missing_topics"]))

    if st.button("Evaluate all topics that have notes"):
        bar = st.progress(0.0)
        for i, p in enumerate(with_notes):
            bar.progress(i / len(with_notes), text=f"Evaluating {p.title}...")
            orch.evaluate(project.project_id, p.topic_id)
        bar.progress(1.0, text="Done")
        st.rerun()

    st.subheader("Per topic")
    topic_id = st.selectbox("Topic", [p.topic_id for p in with_notes], format_func=lambda i: next(p.title for p in with_notes if p.topic_id == i))
    evals = repo.list_evaluations(project.project_id, topic_id, latest_only=False)
    c1, c2, _ = st.columns([1, 1, 3])
    if c1.button("Run evaluation (P11)", type="primary"):
        with st.spinner("Independent evaluation running..."):
            orch.evaluate(project.project_id, topic_id)
        st.rerun()
    can_refine = bool(evals) and evals[0].evaluation_status == "needs_refinement"
    if c2.button("Refine notes (P12)", disabled=not can_refine,
                 help="Applies targeted fixes for the latest findings, saves a new version and re-evaluates it."):
        with st.spinner("Refining and re-evaluating..."):
            try:
                before, after, applied = orch.refine(project.project_id, topic_id)
                st.session_state["last_refine"] = (before.coverage_score, after.coverage_score, applied)
            except Exception as exc:  # noqa: BLE001
                st.error(f"{exc.__class__.__name__}: {exc}")
        st.rerun()
    if st.session_state.get("last_refine"):
        b, a, applied = st.session_state.pop("last_refine")
        st.success(f"Refinement applied {len(applied)} change(s). Verified coverage {b if b is not None else 'n/a'}% → {a if a is not None else 'n/a'}%.")
    if not evals:
        st.info("This topic has not been evaluated yet.")
        return
    latest = evals[0]
    st.markdown(f"{pill(latest.evaluation_status.replace('_', ' '), STATUS_KIND.get(latest.evaluation_status, 'muted'))} "
                f"<span class='sp-ref'>evaluated {local_time(latest.created_at)}</span>", unsafe_allow_html=True)
    _report(latest.report)
    if len(evals) > 1:
        with st.expander(f"Evaluation history ({len(evals)})"):
            st.dataframe(pd.DataFrame([{"when": local_time(e.created_at), "status": e.evaluation_status,
                                        "verified coverage": e.coverage_score, "notes version": e.report.get("notes_version")}
                                       for e in evals]), hide_index=True, use_container_width=True)
