"""Quiz Center: attempt quizzes; answers and explanations are only revealed after submission."""
from __future__ import annotations

import streamlit as st

from ui.common import get_repo, hero, pill, require_project
from ui.components import empty_state
from ui.quiz_logic import grade_choice, score, short_answer_overlap

LETTERS = "ABCDEFGH"


def render() -> None:
    project = require_project()
    repo = get_repo()
    hero(project.name, "Practice quizzes with instant feedback. Answers stay hidden until you submit.", "Quiz Center")
    parents = [t for t in repo.list_topics(project.project_id) if t.parent_topic_id is None]
    available = [(p, repo.get_resource(project.project_id, p.topic_id, "quiz")) for p in parents]
    available = [(p, r) for p, r in available if r]
    if not available:
        empty_state("No quizzes generated yet (Generation Center → Practice quiz).")
        return
    topic_id = st.selectbox("Quiz topic", [p.topic_id for p, _ in available],
                            format_func=lambda i: next(p.title for p, _ in available if p.topic_id == i))
    topic, res = next((p, r) for p, r in available if p.topic_id == topic_id)
    questions = res.content.get("questions", [])
    key = f"quiz_{res.resource_id}"
    state = st.session_state.setdefault(key, {"submitted": False, "answers": {}, "self": {}})

    with st.form(f"form_{key}"):
        for i, q in enumerate(questions):
            st.markdown(f"**{i + 1}. {q['question']}**")
            st.markdown(pill(q["question_type"].replace("_", " "), "muted") + pill(q["difficulty"], "muted"), unsafe_allow_html=True)
            disabled = state["submitted"]
            if q["question_type"] == "multi_select":
                st.caption("Select all that apply.")
                chosen = [o for j, o in enumerate(q["options"])
                          if st.checkbox(f"{LETTERS[j]}) {o}", key=f"{key}_{i}_{j}", disabled=disabled)]
                state["answers"][i] = chosen if not disabled else state["answers"].get(i, chosen)
            elif q["question_type"] in ("mcq", "true_false"):
                choice = st.radio("Answer", q["options"], index=None, key=f"{key}_{i}", label_visibility="collapsed",
                                  format_func=lambda o, q=q: o if q["question_type"] == "true_false" else f"{LETTERS[q['options'].index(o)]}) {o}",
                                  disabled=disabled)
                if not disabled:
                    state["answers"][i] = choice
            else:
                text = st.text_area("Your answer", key=f"{key}_{i}", disabled=disabled, height=90)
                if not disabled:
                    state["answers"][i] = text
            st.write("")
        submitted = st.form_submit_button("Submit answers", type="primary", disabled=state["submitted"])
    if submitted:
        state["submitted"] = True
        st.rerun()

    if state["submitted"]:
        st.divider()
        st.subheader("Feedback")
        for i, q in enumerate(questions):
            ans = state["answers"].get(i)
            with st.container(border=True):
                st.markdown(f"**{i + 1}. {q['question']}**")
                if q["question_type"] in ("short_answer", "application"):
                    st.markdown(f"**Your answer:** {ans or '_(blank)_'}")
                    st.markdown(f"**Model answer:** {'; '.join(q['correct_answers'])}")
                    overlap = short_answer_overlap(q, ans or "")
                    st.caption(f"Keyword overlap with the model answer: {overlap:.0%} (a hint only — judge your own answer).")
                    mark = st.radio("How did you do?", ["Not marked", "Correct", "Incorrect"], horizontal=True, key=f"{key}_self_{i}")
                    state["self"][i] = None if mark == "Not marked" else mark == "Correct"
                else:
                    ok = grade_choice(q, ans)
                    shown = ", ".join(ans) if isinstance(ans, list) else (ans or "(no answer)")
                    st.markdown(("✅ **Correct**" if ok else "❌ **Incorrect**") + f" — your answer: {shown}")
                    if not ok:
                        st.markdown(f"**Correct answer:** {'; '.join(q['correct_answers'])}")
                st.info(q["explanation"])
        correct, gradable, _ = score(questions, state["answers"], {k: v for k, v in state["self"].items() if v is not None})
        pending = sum(1 for i, q in enumerate(questions) if q["question_type"] in ("short_answer", "application") and state["self"].get(i) is None)
        st.metric("Score", f"{correct} / {gradable}", help="Open questions count once you mark them yourself.")
        if pending:
            st.caption(f"{pending} open question(s) not marked yet.")
        c1, c2 = st.columns(2)
        if c1.button("Save result"):
            repo.log_activity(project.project_id, f"Quiz '{topic.title}': {correct}/{gradable}")
            st.toast("Result saved to recent activity.")
        if c2.button("Try again"):
            st.session_state.pop(key, None)
            for k in list(st.session_state):
                if k.startswith(f"{key}_"):
                    st.session_state.pop(k)
            st.rerun()
