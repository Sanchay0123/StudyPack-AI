"""Revision Center: quick revision notes, interactive flashcards, suggested important questions."""
from __future__ import annotations

import random

import streamlit as st

from export.markdown_exporter import render_revision
from ui.common import get_repo, hero, pill, require_project
from ui.components import empty_state


def _topic_picker(parents, key: str, allow_all: bool = False):
    options = (["__all__"] if allow_all else []) + [p.topic_id for p in parents]
    return st.selectbox("Topic", options, key=key,
                        format_func=lambda i: "All topics" if i == "__all__" else next(p.title for p in parents if p.topic_id == i))


def _revision(project_id, parents) -> None:
    repo = get_repo()
    topic_id = _topic_picker(parents, "rev_topic")
    res = repo.get_resource(project_id, topic_id, "revision")
    if not res:
        empty_state("Revision notes not generated for this topic yet.")
        return
    d = res.content
    st.info(d.get("one_line_summary", ""))
    c1, c2 = st.columns(2)
    with c1:
        if d.get("key_definitions"):
            st.markdown("##### Definitions")
            for x in d["key_definitions"]:
                st.markdown(f"- **{x['term']}** — {x['definition']}")
        if d.get("formulas"):
            st.markdown("##### Formulas")
            for f in d["formulas"]:
                st.markdown(f"- **{f['name']}**: `{f['expression']}`  \n  {f['meaning']}")
        if d.get("processes"):
            st.markdown("##### Processes")
            for proc in d["processes"]:
                st.markdown(f"**{proc['name']}**\n" + "\n".join(f"{i}. {s}" for i, s in enumerate(proc["steps"], 1)))
    with c2:
        if d.get("key_concepts"):
            st.markdown("##### Key concepts")
            st.markdown("\n".join(f"- {c}" for c in d["key_concepts"]))
        if d.get("differences"):
            st.markdown("##### Important differences")
            for x in d["differences"]:
                st.markdown(f"- **{x['items']}** — {x['difference']}")
        if d.get("relationships"):
            st.markdown("##### Relationships")
            st.markdown("\n".join(f"- {c}" for c in d["relationships"]))
        if d.get("common_mistakes"):
            st.markdown("##### Common mistakes")
            st.markdown("\n".join(f"- ⚠ {c}" for c in d["common_mistakes"]))
    st.download_button("Download revision sheet (Markdown)", render_revision(d), file_name="revision.md")


def _flashcards(project_id, parents) -> None:
    repo = get_repo()
    c1, c2, c3 = st.columns([3, 2, 1])
    with c1:
        topic_id = _topic_picker(parents, "fc_topic", allow_all=True)
    with c2:
        difficulty = st.multiselect("Difficulty", ["easy", "medium", "hard"], default=["easy", "medium", "hard"], key="fc_diff")
    cards = []
    for p in parents:
        if topic_id not in ("__all__", p.topic_id):
            continue
        res = repo.get_resource(project_id, p.topic_id, "flashcards")
        if res:
            cards += [dict(c, topic=p.title) for c in res.content.get("cards", []) if c.get("difficulty") in difficulty]
    if not cards:
        empty_state("No flashcards for this selection yet.")
        return
    deck_key = f"deck_{topic_id}_{'-'.join(difficulty)}"
    state = st.session_state.setdefault(deck_key, {"order": list(range(len(cards))), "i": 0, "show": False, "known": 0, "review": 0})
    if len(state["order"]) != len(cards):
        state.update(order=list(range(len(cards))), i=0, show=False)
    with c3:
        if st.button("Shuffle", key="fc_shuffle"):
            random.shuffle(state["order"])
            state.update(i=0, show=False)
    card = cards[state["order"][state["i"] % len(cards)]]
    st.caption(f"Card {state['i'] % len(cards) + 1} of {len(cards)} · {card['topic']}")
    st.markdown(f"<div class='sp-flash'>{card['question'] if not state['show'] else card['answer']}</div>", unsafe_allow_html=True)
    st.markdown(pill(card["difficulty"], "muted") + (pill("answer", "ok") if state["show"] else pill("question", "muted")),
                unsafe_allow_html=True)
    b1, b2, b3, b4 = st.columns(4)
    if b1.button("Flip", use_container_width=True, key="fc_flip"):
        state["show"] = not state["show"]
        st.rerun()
    if b2.button("✓ I knew it", use_container_width=True, key="fc_known", disabled=not state["show"]):
        state["known"] += 1
        state.update(i=state["i"] + 1, show=False)
        st.rerun()
    if b3.button("↻ Review again", use_container_width=True, key="fc_again", disabled=not state["show"]):
        state["review"] += 1
        state.update(i=state["i"] + 1, show=False)
        st.rerun()
    if b4.button("Next →", use_container_width=True, key="fc_next"):
        state.update(i=state["i"] + 1, show=False)
        st.rerun()
    st.caption(f"This session: {state['known']} known · {state['review']} to review")


def _questions(project_id, parents) -> None:
    repo = get_repo()
    topic_id = _topic_picker(parents, "q_topic")
    res = repo.get_resource(project_id, topic_id, "questions")
    if not res:
        empty_state("Important questions not generated for this topic yet.")
        return
    st.caption("Suggested important questions based on the provided material. They are study aids, not predictions of an actual exam.")
    for i, q in enumerate(res.content.get("questions", []), 1):
        with st.container(border=True):
            st.markdown(f"**Q{i}.** {q['question']}")
            st.markdown(pill(q["question_type"].replace("_", " "), "muted") + pill(q["difficulty"], "muted"), unsafe_allow_html=True)
            with st.expander("Show model answer"):
                st.markdown(q["model_answer"])
                if q.get("key_points"):
                    st.markdown("**Key points:** " + "; ".join(q["key_points"]))


def render() -> None:
    project = require_project()
    hero(project.name, "Condensed revision sheets, active-recall flashcards and suggested exam-style questions.", "Revision Center")
    parents = [t for t in get_repo().list_topics(project.project_id) if t.parent_topic_id is None]
    if not parents:
        empty_state("No topics yet.")
        return
    tabs = st.tabs(["Quick revision", "Flashcards", "Important questions"])
    with tabs[0]:
        _revision(project.project_id, parents)
    with tabs[1]:
        _flashcards(project.project_id, parents)
    with tabs[2]:
        _questions(project.project_id, parents)
