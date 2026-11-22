"""Export: Markdown and PDF study packs with selectable resources and topics."""
from __future__ import annotations

import streamlit as st

from export.collect import collect_pack
from export.markdown_exporter import export_markdown
from export.pdf_exporter import export_pdf
from prompt_engine.prompt_router import RESOURCE_LABELS, RESOURCE_TYPES
from ui.common import get_repo, hero, require_project


def render() -> None:
    project = require_project()
    repo = get_repo()
    hero(project.name, "Download the study pack as Markdown or as a formatted PDF.", "Export")
    parents = [t for t in repo.list_topics(project.project_id) if t.parent_topic_id is None]
    if not parents:
        st.info("Nothing to export yet.")
        return
    types = st.multiselect("Include resources", RESOURCE_TYPES, default=RESOURCE_TYPES, format_func=lambda r: RESOURCE_LABELS[r])
    topic_ids = st.multiselect("Include topics", [p.topic_id for p in parents], default=[p.topic_id for p in parents],
                               format_func=lambda i: next(p.title for p in parents if p.topic_id == i))
    pack = collect_pack(repo, project.project_id, types, topic_ids)
    missing = [(tb.topic.title, RESOURCE_LABELS[r]) for tb in pack.topics for r in pack.resource_types if r not in tb.resources]
    if missing:
        st.warning(f"{len(missing)} selected item(s) have not been generated; the export will say “Not generated yet” for them, "
                   "rather than leaving them out silently.")
        with st.expander("Show missing items"):
            st.markdown("\n".join(f"- {t} · {r}" for t, r in missing))
    c1, c2 = st.columns(2)
    with c1:
        if st.button("Build Markdown", type="primary", disabled=not types or not topic_ids):
            path = export_markdown(repo, project.project_id, types, topic_ids)
            st.session_state["md_export"] = (path.name, path.read_bytes())
        if st.session_state.get("md_export"):
            name, data = st.session_state["md_export"]
            st.download_button("Download Markdown", data, file_name=name, mime="text/markdown")
    with c2:
        if st.button("Build PDF", type="primary", disabled=not types or not topic_ids):
            with st.spinner("Typesetting PDF..."):
                try:
                    path = export_pdf(repo, project.project_id, types, topic_ids)
                    st.session_state["pdf_export"] = (path.name, path.read_bytes())
                except Exception as exc:  # noqa: BLE001
                    st.error(f"PDF export failed: {exc.__class__.__name__}: {exc}")
        if st.session_state.get("pdf_export"):
            name, data = st.session_state["pdf_export"]
            st.download_button("Download PDF", data, file_name=name, mime="application/pdf")
    st.caption("Exports are also saved under generated/<project id>/.")
