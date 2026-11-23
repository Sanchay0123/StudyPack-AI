"""Create Study Pack: project details, multi-file upload, extraction, and analysis kick-off."""
from __future__ import annotations

import streamlit as st

from config.settings import get_settings
from ingestion.ocr_processor import ocr_available
from ingestion.pipeline import ingest_files
from ui.job_panels import analysis_panel, start_analysis
from prompt_engine.prompt_router import RESOURCE_LABELS, RESOURCE_TYPES
from storage.models import Project
from ui.common import current_project, get_repo, hero, pill

LEVELS = ["(detect automatically)", "High school", "First-year undergraduate", "Undergraduate", "Advanced undergraduate",
          "Postgraduate", "Professional"]
STATUS_KIND = {"extracted": "ok", "needs_ocr": "warn", "duplicate": "muted", "failed": "bad", "rejected": "bad"}


def show_reports(reports) -> None:
    for r in reports:
        st.markdown(f"{pill(r.status.replace('_', ' '), STATUS_KIND.get(r.status, 'muted'))} **{r.filename}** — {r.message}",
                    unsafe_allow_html=True)
        for w in r.warnings:
            st.caption(f"⚠ {w}")


def render() -> None:
    hero("Create Study Pack", "Upload lecture PDFs, slides, Word documents or notes. Subject detection is automatic.", "New")
    settings = get_settings()
    repo = get_repo()
    ocr_ok = ocr_available()

    with st.form("create_pack", clear_on_submit=False):
        name = st.text_input("Study pack name", placeholder="e.g. Computer Networks — Module 1")
        c1, c2 = st.columns(2)
        with c1:
            subject = st.text_input("Subject (optional)", placeholder="Leave empty to detect automatically")
        with c2:
            level = st.selectbox("Academic level (optional)", LEVELS)
        files = st.file_uploader("Documents", type=["pdf", "docx", "pptx", "txt", "md"], accept_multiple_files=True,
                                 help=f"Up to {settings.max_upload_mb} MB per file. Legacy .doc/.ppt must be saved as .docx/.pptx.")
        resources = st.multiselect("Resources to generate by default", RESOURCE_TYPES, default=RESOURCE_TYPES,
                                   format_func=lambda r: RESOURCE_LABELS[r])
        use_ocr = st.checkbox("Use OCR for scanned pages", value=False, disabled=not ocr_ok,
                              help=None if ocr_ok else "Tesseract is not installed; scanned pages will be detected and reported but not read.")
        analyse_now = st.checkbox("Run the analysis immediately after upload", value=True)
        submitted = st.form_submit_button("Create study pack", type="primary")

    if submitted:
        if not name.strip():
            st.error("Please give the study pack a name.")
            st.stop()
        if not files:
            st.error("Please upload at least one document.")
            st.stop()
        project = repo.create_project(Project(name=name.strip(), subject=subject.strip() or None,
                                              academic_level=None if level == LEVELS[0] else level,
                                              options={"resources": resources}))
        st.session_state["project_id"] = project.project_id
        with st.spinner("Extracting content..."):
            reports = ingest_files(repo, project.project_id, [(f.name, f.getvalue()) for f in files], use_ocr=use_ocr)
        show_reports(reports)
        if not any(r.status in ("extracted",) for r in reports):
            st.error("No document could be extracted. Fix the problems above and add documents on the Document Analysis page.")
            st.stop()
        if analyse_now:
            if start_analysis(project.project_id):
                st.success("Analysis started in the background (P01 → P04). Follow its progress on the Document Analysis page.")
                analysis_panel(project.project_id)
            st.page_link(st.session_state["_pages"]["analysis"], label="Open Document Analysis →", icon=":material/account_tree:")
        else:
            st.page_link(st.session_state["_pages"]["analysis"], label="Continue to Document Analysis →", icon=":material/account_tree:")

    project = current_project()
    if project and not submitted:
        st.divider()
        st.subheader(f"Add documents to “{project.name}”")
        more = st.file_uploader("More documents", type=["pdf", "docx", "pptx", "txt", "md"], accept_multiple_files=True, key="more_docs")
        if st.button("Add to current study pack", disabled=not more):
            with st.spinner("Extracting content..."):
                reports = ingest_files(repo, project.project_id, [(f.name, f.getvalue()) for f in more], use_ocr=False)
            show_reports(reports)
            st.info("Re-run the analysis on the Document Analysis page to include the new material in the topic map.")
