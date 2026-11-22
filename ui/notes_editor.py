"""Manual editing of lecture notes. Every save creates a new version (origin "edited"); older versions are kept."""
from __future__ import annotations

import copy
from typing import Any

import streamlit as st

from storage.models import Resource

PROVENANCES = ["source", "supplementary", "inferred"]


def apply_edits(notes: dict[str, Any], overview: str, summary: str, sections: list[dict[str, Any]]) -> tuple[dict[str, Any], list[str]]:
    """Return (new notes, change log). `sections` items: {index, heading, content, provenance, delete}.

    Sections whose text the student changed are flagged `edited_by_user` so the quality report and
    exports can tell model-generated text from the student's own edits.
    """
    updated = copy.deepcopy(notes)
    changes: list[str] = []
    if overview.strip() != notes.get("overview", "").strip():
        updated["overview"] = overview.strip()
        changes.append("edited overview")
    if summary.strip() != notes.get("summary", "").strip():
        updated["summary"] = summary.strip()
        changes.append("edited summary")
    new_sections = []
    for edit in sections:
        original = notes["sections"][edit["index"]]
        if edit.get("delete"):
            changes.append(f"deleted section: {original['heading']}")
            continue
        section = copy.deepcopy(original)
        changed = False
        for key in ("heading", "content", "provenance"):
            value = edit[key].strip() if isinstance(edit[key], str) else edit[key]
            if value != (original.get(key) or "").strip():
                section[key] = value
                changed = True
        if changed:
            section["edited_by_user"] = True
            changes.append(f"edited section: {section['heading']}")
        new_sections.append(section)
    if not new_sections:
        raise ValueError("Notes must keep at least one section.")
    updated["sections"] = new_sections
    if changes:
        updated["_meta"] = {**notes.get("_meta", {}), "edited": True, "edit_log": changes}
    return updated, changes


def render_editor(repo, current: Resource) -> None:
    notes = current.content
    st.info("Editing creates a new version; the current one stays available in the version list. "
            "Re-run the evaluation afterwards if you changed content.")
    with st.form(f"edit_{current.resource_id}"):
        overview = st.text_area("Overview", notes.get("overview", ""), height=100)
        edits = []
        for i, s in enumerate(notes.get("sections", [])):
            with st.expander(f"{i + 1}. {s['heading']}", expanded=False):
                heading = st.text_input("Heading", s["heading"], key=f"h_{current.resource_id}_{i}")
                prov = s.get("provenance", "inferred")
                provenance = st.selectbox("Provenance", PROVENANCES, index=PROVENANCES.index(prov) if prov in PROVENANCES else 2,
                                          key=f"p_{current.resource_id}_{i}",
                                          help="Keep 'source' only if the text is stated in your documents.")
                content = st.text_area("Content (Markdown)", s.get("content", ""), height=220, key=f"c_{current.resource_id}_{i}")
                delete = st.checkbox("Delete this section", key=f"d_{current.resource_id}_{i}")
                edits.append({"index": i, "heading": heading, "content": content, "provenance": provenance, "delete": delete})
        summary = st.text_area("Summary", notes.get("summary", ""), height=100)
        saved = st.form_submit_button("Save as new version", type="primary")
    if saved:
        try:
            updated, changes = apply_edits(notes, overview, summary, edits)
        except ValueError as exc:
            st.error(str(exc))
            return
        if not changes:
            st.info("No changes to save.")
            return
        repo.save_resource(Resource(project_id=current.project_id, topic_id=current.topic_id, resource_type="notes",
                                    content=updated, prompt_id=current.prompt_id, prompt_version=current.prompt_version,
                                    provider=current.provider, model=current.model, origin="edited"))
        repo.log_activity(current.project_id, f"Edited notes ({len(changes)} change(s))")
        st.session_state["_close_notes_editor"] = True  # applied before the toggle is drawn on the next run
        st.success(f"Saved: {'; '.join(changes)}")
        st.rerun()
