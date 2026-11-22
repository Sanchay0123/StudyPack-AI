"""Quiz grading logic (UI-independent, unit-tested)."""
from __future__ import annotations

from typing import Any

from prompt_engine.context_manager import keywords


def grade_choice(question: dict[str, Any], answer: Any) -> bool:
    correct = set(question["correct_answers"])
    if question["question_type"] == "multi_select":
        return set(answer or []) == correct
    return answer in correct


def short_answer_overlap(question: dict[str, Any], answer: str) -> float:
    """Keyword overlap between the student's answer and the model answer (0..1). Only a hint for self-assessment."""
    reference = keywords(" ".join(question["correct_answers"]))
    if not reference or not answer.strip():
        return 0.0
    return len(reference & keywords(answer)) / len(reference)


def score(questions: list[dict[str, Any]], answers: dict[int, Any], self_marks: dict[int, bool]) -> tuple[int, int, list[bool | None]]:
    """Returns (correct, gradable, per-question result). Open questions count only once self-assessed."""
    results: list[bool | None] = []
    correct = gradable = 0
    for i, q in enumerate(questions):
        if q["question_type"] in ("short_answer", "application"):
            mark = self_marks.get(i)
            results.append(mark)
            if mark is not None:
                gradable += 1
                correct += int(mark)
        else:
            ok = grade_choice(q, answers.get(i))
            results.append(ok)
            gradable += 1
            correct += int(ok)
    return correct, gradable, results
