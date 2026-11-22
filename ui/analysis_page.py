"""Document Analysis: documents & extraction, detected subject, strategy, and an editable topic map."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from analyzer.sections import build_sections
from config.settings import get_settings
from ingestion.ocr_processor import ocr_available
from ingestion.pipeline import process_document
from prompt_engine.orchestrator import Orchestrator
from prompt_engine.schemas.analysis import NoteSectionKind
from storage.models import Topic
from ui.common import get_repo, get_router, hero, pill, require_project, stat_card
from ui.upload_page import run_analysis_ui

SECTION_KINDS = list(NoteSectionKind.__args__)  # type: ignore[attr-defined]
STATUS_KIND = {"extracted": "ok", "needs_ocr": "warn", "failed": "bad", "uploaded": "muted"}


def _documents(project) -> None:
    repo = get_repo()
    docs = repo.list_documents(project.project_id)
    st.subheader("Documents")
    if not docs:
        st.info("No documents yet. Add some on the Create Study Pack page.")
        return
    for d in docs:
        meta = d.metadata
        c1, c2 = st.columns([5, 1])
        with c1:
            detail = f"{meta.get('chunks', 0)} chunks · {meta.get('chars', 0):,} chars"
            if meta.get("pages"):
                detail += f" · {meta['pages']} pages"
            if meta.get("slides"):
                detail += f" · {meta['slides']} slides"
            if meta.get("needs_review_chunks"):
                detail += f" · {meta['needs_review_chunks']} chunk(s) need review"
            st.markdown(f"{pill(d.processing_status.replace('_', ' '), STATUS_KIND.get(d.processing_status, 'muted'))} "
                        f"**{d.filename}** <span class='sp-ref'>{d.file_type.upper()} · {d.size_bytes / 1024:.0f} KB · {detail}</span>",
                        unsafe_allow_html=True)
            for w in meta.get("warnings", []):
                st.caption(f"⚠ {w}")
            if meta.get("error"):
                st.caption(f"✖ {meta['error']}")
        with c2:
            if d.processing_status == "needs_ocr" and ocr_available():
                if st.button("Run OCR", key=f"ocr_{d.document_id}"):
                    with st.spinner("Running OCR..."):
                        report = process_document(repo, d, get_settings(), use_ocr=True)
                    st.toast(f"{d.filename}: {report.status}")
                    st.rerun()
            if st.button("Remove", key=f"del_{d.document_id}", help="Delete this document and its extracted content"):
                repo.delete_document(d.document_id)
                st.rerun()

    chunks = repo.list_chunks(project.project_id)
    with st.expander(f"Extracted content preview ({len(chunks)} chunks)"):
        if chunks:
            df = pd.DataFrame([{"chunk": c.chunk_id, "source": c.source_reference, "type": c.content_type,
                                "confidence": c.extraction_confidence, "review": "⚠" if c.needs_review else "",
                                "text": c.content[:160].replace("\n", " ")} for c in chunks])
            st.dataframe(df, hide_index=True, use_container_width=True)


def _figures(project) -> None:
    from analyzer.figure_describer import describe_figures, pending_figures
    from prompt_engine.stage_runner import StageRunner

    repo = get_repo()
    docs = repo.list_documents(project.project_id)
    figures = [(d, f) for d in docs for f in (d.metadata.get("figures") or [])]
    if not figures:
        return
    pending = pending_figures(repo, project.project_id)
    st.subheader("Figures")
    st.caption(f"{len(figures)} figure(s) found in the documents; {len(figures) - len(pending)} described. Descriptions come from "
               "the vision model, are labelled as such in the source text, and are flagged for review.")
    if pending and st.button(f"Describe {len(pending)} figure(s) with the vision model",
                             help="Run before (re-)running the analysis so the descriptions inform the topic map and notes."):
        bar = st.progress(0.0)
        runner = StageRunner(get_router(), get_settings(), recorder=repo.save_stage_run, project_id=project.project_id)
        stats = describe_figures(repo, runner, project.project_id, project.subject or "",
                                 progress=lambda m, f: bar.progress(min(f, 1.0), text=m))
        st.success(f"Described {stats['described']} of {stats['total']} ({stats['low_relevance']} decorative).")
        for err in stats["errors"]:
            st.warning(err)
    with st.expander("Show figures"):
        for doc, fig in figures:
            c1, c2 = st.columns([1, 2])
            with c1:
                try:
                    st.image(fig["path"], use_container_width=True)
                except Exception:  # noqa: BLE001 - file removed
                    st.caption("(image file missing)")
            with c2:
                where = f"page {fig['page']}" if fig.get("page") else (f"slide {fig['slide']}" if fig.get("slide") else "")
                st.markdown(f"**{fig['id']}** · {doc.filename} {where}")
                d = fig.get("description")
                if d:
                    st.markdown(f"{pill(d['figure_kind'].replace('_', ' '), 'muted')}{pill('relevance ' + d['educational_relevance'], 'muted')}",
                                unsafe_allow_html=True)
                    st.write(d["description"])
                    if d.get("text_in_image"):
                        st.caption(f"Text in image: {d['text_in_image']}")
                else:
                    st.caption("Not described yet.")


def _analysis_summary(project, stored) -> None:
    analysis = stored.get("analysis")
    if not analysis:
        return
    st.subheader("Detected subject")
    c1, c2, c3 = st.columns(3)
    with c1:
        stat_card("Subject", project.subject or analysis["subject"])
    with c2:
        stat_card("Domain", analysis["domain_category"].replace("_", " "))
    with c3:
        stat_card("Level", project.academic_level or analysis["estimated_level"])
    st.write(analysis["subject_context"])
    cols = st.columns(2)
    with cols[0]:
        st.markdown("**Major concepts**")
        st.markdown("\n".join(f"- {c}" for c in analysis.get("major_concepts", [])) or "_none_")
        if analysis.get("prerequisites"):
            st.markdown("**Prerequisites**")
            st.markdown("\n".join(f"- {c}" for c in analysis["prerequisites"]))
    with cols[1]:
        if analysis.get("key_terms"):
            st.markdown("**Key terms**")
            st.dataframe(pd.DataFrame(analysis["key_terms"]), hide_index=True, use_container_width=True, height=240)
    for label, key in (("Possible gaps in the material", "gaps"), ("Overlapping content", "overlaps")):
        if analysis.get(key):
            st.warning(f"**{label}:** " + "; ".join(analysis[key]))


def _strategy_editor(project, stored) -> None:
    strategy = stored.get("strategy")
    if not strategy:
        return
    st.subheader("Teaching strategy")
    st.caption("Selected automatically by P04 for this subject. It steers every generation prompt; adjust it if needed.")
    with st.form("strategy_form"):
        approach = st.text_area("Approach", strategy.get("approach_summary", ""), height=80)
        priorities = st.text_area("Priorities (one per line)", "\n".join(strategy.get("priorities", [])), height=110)
        c1, c2 = st.columns(2)
        with c1:
            sections = st.multiselect("Note sections (in order)", SECTION_KINDS,
                                      default=[s for s in strategy.get("note_sections", []) if s in SECTION_KINDS])
        with c2:
            styles = ["quantitative", "programming", "conceptual", "case_study", "mixed"]
            style = st.selectbox("Example style", styles, index=styles.index(strategy.get("example_style", "conceptual")))
        notation = st.text_input("Notation guidance", strategy.get("notation_guidance", ""))
        pitfalls = st.text_input("Mistakes to highlight", strategy.get("common_pitfalls_focus", ""))
        c3, c4 = st.columns(2)
        save = c3.form_submit_button("Save strategy")
        regen = c4.form_submit_button("Re-select strategy with the model")
    if save:
        strategy.update({"approach_summary": approach, "priorities": [p.strip() for p in priorities.splitlines() if p.strip()],
                         "note_sections": sections, "example_style": style, "notation_guidance": notation,
                         "common_pitfalls_focus": pitfalls, "edited_by_user": True})
        get_repo().save_analysis(project.project_id, strategy=strategy)
        st.success("Strategy saved.")
    if regen:
        with st.spinner("Running P04..."):
            try:
                Orchestrator(get_repo(), get_router(), get_settings()).regenerate_strategy(project.project_id)
                st.rerun()
            except Exception as exc:  # noqa: BLE001
                st.error(f"{exc.__class__.__name__}: {exc}")


def _topic_editor(project) -> None:
    repo = get_repo()
    topics = repo.list_topics(project.project_id)
    parents = [t for t in topics if t.parent_topic_id is None]
    st.subheader("Topic map")
    if not parents:
        st.info("No topics yet. Run the analysis first.")
        return
    sections = build_sections(repo.list_chunks(project.project_id))
    sec_by_label = {s.label: s for s in sections}
    sec_label_of_chunk = {c: s.label for s in sections for c in s.chunk_ids}
    sec_options = [s.label for s in sections]

    def fmt(label: str) -> str:
        s = sec_by_label[label]
        return f"{label} · {s.heading.split(' > ')[-1][:50]} · {s.location}"

    st.caption("Review the hierarchy before generating. You can rename, reorder, delete or add topics, edit subtopics and "
               "objectives, and change which source sections each topic uses. Deleting a topic also deletes its generated resources.")
    with st.form("topic_editor"):
        edited = []
        for i, p in enumerate(parents):
            subs = [t for t in topics if t.parent_topic_id == p.topic_id]
            with st.expander(f"{i + 1}. {p.title}  ·  {len(subs)} subtopics  ·  {len(p.source_chunk_ids)} source chunks", expanded=False):
                c1, c2 = st.columns([4, 1])
                title = c1.text_input("Title", p.title, key=f"t_{p.topic_id}")
                order = c2.number_input("Order", 1, 99, i + 1, key=f"o_{p.topic_id}")
                desc = st.text_area("Description", p.description, key=f"d_{p.topic_id}", height=68)
                sub_text = st.text_area("Subtopics (one per line)", "\n".join(s.title for s in subs), key=f"s_{p.topic_id}", height=110)
                obj_text = st.text_area("Learning objectives (one per line)", "\n".join(p.learning_objectives), key=f"ob_{p.topic_id}", height=110)
                current_secs = list(dict.fromkeys(sec_label_of_chunk[c] for c in p.source_chunk_ids if c in sec_label_of_chunk))
                secs = st.multiselect("Source sections", sec_options, default=current_secs, format_func=fmt, key=f"sec_{p.topic_id}")
                delete = st.checkbox("Delete this topic", key=f"x_{p.topic_id}")
                edited.append((p, subs, title, order, desc, sub_text, obj_text, secs, delete))
        st.markdown("**Add a topic**")
        new_title = st.text_input("New topic title", key="new_topic_title")
        new_secs = st.multiselect("Source sections for the new topic", sec_options, format_func=fmt, key="new_topic_secs")
        saved = st.form_submit_button("Save topic map", type="primary")

    if saved:
        new_topics: list[Topic] = []
        for p, subs, title, order, desc, sub_text, obj_text, secs, delete in sorted(edited, key=lambda e: e[3]):
            if delete or not title.strip():
                continue
            p.title, p.description = title.strip(), desc.strip()
            p.learning_objectives = [o.strip() for o in obj_text.splitlines() if o.strip()]
            p.source_chunk_ids = [c for lab in secs for c in sec_by_label[lab].chunk_ids]
            p.order_index = len(new_topics)
            new_topics.append(p)
            existing = {s.title.strip().lower(): s for s in subs}
            for line in sub_text.splitlines():
                name = line.strip()
                if not name:
                    continue
                child = existing.get(name.lower()) or Topic(project_id=project.project_id, parent_topic_id=p.topic_id, title=name)
                child.parent_topic_id = p.topic_id
                child.order_index = len(new_topics)
                new_topics.append(child)
        if new_title.strip():
            new_topics.append(Topic(project_id=project.project_id, title=new_title.strip(), order_index=len(new_topics),
                                    source_chunk_ids=[c for lab in new_secs for c in sec_by_label[lab].chunk_ids]))
        repo.replace_topics(project.project_id, new_topics)
        repo.log_activity(project.project_id, "Topic map edited")
        st.success("Topic map saved.")
        st.rerun()


def render() -> None:
    project = require_project()
    hero(project.name, "Inspect the extraction, the detected subject and the topic hierarchy before generating.", "Document Analysis")
    repo = get_repo()
    _documents(project)
    _figures(project)
    stored = repo.get_analysis(project.project_id)
    c1, c2 = st.columns([1, 3])
    with c1:
        label = "Re-run analysis" if stored.get("analysis") else "Run analysis"
        run = st.button(label, type="primary" if not stored.get("analysis") else "secondary",
                        help="Runs P01-P04. Re-running replaces the topic map (and the resources of topics that no longer exist).")
    if run:
        if run_analysis_ui(project.project_id):
            st.rerun()
    if not stored.get("analysis"):
        st.info("The material has not been analysed yet.")
        return
    _analysis_summary(project, stored)
    _topic_editor(project)
    _strategy_editor(project, stored)
