"""Cross-resource consistency checks (deterministic).

Checks that supplementary resources agree with the notes and the source:
  * numbers stated in flashcards / quiz / revision / questions appear in the notes or source
  * revision formulas appear in the notes or source
  * revision key terms are explained in the notes
  * quiz answers are among the options (already schema-validated; re-checked after edits)
"""
from __future__ import annotations

from typing import Any

from evaluation.text_utils import normalize, numbers_in


def _texts(resource_type: str, content: dict[str, Any]) -> list[tuple[str, str]]:
    """(location, text) pairs to check, per resource type."""
    out = []
    if resource_type == "flashcards":
        out = [(f"card {i + 1}", c["answer"]) for i, c in enumerate(content.get("cards", []))]
    elif resource_type == "quiz":
        for i, q in enumerate(content.get("questions", [])):
            out.append((f"quiz Q{i + 1}", " ".join(q.get("correct_answers", [])) + " " + q.get("explanation", "")))
    elif resource_type == "questions":
        out = [(f"question {i + 1}", q.get("model_answer", "")) for i, q in enumerate(content.get("questions", []))]
    elif resource_type == "revision":
        out = [("revision concepts", " ".join(content.get("key_concepts", [])))]
        out += [(f"definition '{d['term']}'", d["definition"]) for d in content.get("key_definitions", [])]
    return out


def check_consistency(notes: dict[str, Any] | None, resources: dict[str, dict[str, Any]], source_text: str) -> dict[str, Any]:
    issues: list[dict[str, str]] = []
    notes_text = ""
    if notes:
        notes_text = " ".join([notes.get("overview", ""), notes.get("summary", "")]
                              + [s.get("content", "") for s in notes.get("sections", [])]
                              + [t["term"] + " " + t["definition"] for t in notes.get("key_terms", [])])
    reference = notes_text + "\n" + source_text
    ref_numbers = numbers_in(reference)
    ref_norm = normalize(reference)

    for rtype, content in resources.items():
        for location, text in _texts(rtype, content):
            missing = sorted(numbers_in(text) - ref_numbers)
            if missing:
                issues.append({"resource": rtype, "location": location,
                               "issue": f"numbers not found in notes or source: {', '.join(missing[:5])}"})
        if rtype == "revision":
            for f in content.get("formulas", []):
                expr = normalize(f.get("expression", "")).replace(" ", "")
                if expr and expr not in ref_norm.replace(" ", "") and len(expr) > 3:
                    issues.append({"resource": rtype, "location": f"formula '{f.get('name')}'",
                                   "issue": "formula not found verbatim in notes or source (verify notation)"})
            if notes_text:
                nn = normalize(notes_text)
                for d in content.get("key_definitions", []):
                    if normalize(d["term"]) not in nn:
                        issues.append({"resource": rtype, "location": f"definition '{d['term']}'",
                                       "issue": "term is not mentioned in the lecture notes"})
        if rtype == "quiz":
            for i, q in enumerate(content.get("questions", [])):
                if q.get("options") and any(a not in q["options"] for a in q.get("correct_answers", [])):
                    issues.append({"resource": rtype, "location": f"quiz Q{i + 1}", "issue": "correct answer is not one of the options"})
    return {"issues": issues, "checked_resources": sorted(resources)}
