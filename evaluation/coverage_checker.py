"""Evidence-based topic coverage.

A subtopic counts as covered only if BOTH:
  * the independent evaluator (P11) judged it "covered", and
  * the evaluator's evidence quote is actually found in the notes text.
If the quote cannot be found, the claim is downgraded to "partial
(unverified evidence)". Coverage % = covered / total x 100, never inflated by
a topic name merely appearing in a heading.

A purely lexical "term coverage" is also computed (no LLM), and reported
separately and labelled as such.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from evaluation.text_utils import normalize, quote_found, stem
from prompt_engine.context_manager import keywords


@dataclass
class CoverageResult:
    unit: str
    status: str  # covered | partial | missing
    llm_status: str | None
    evidence: str
    evidence_verified: bool
    lexical_hit: bool
    note: str = ""


def _key(text: str) -> str:
    return re.sub(r"\W+", " ", text.lower()).strip()


def _root(word: str) -> str:
    root = stem(word)
    if root.endswith("ies"):
        root = root[:-3]
    elif root.endswith("y") and len(root) > 5:
        root = root[:-1]
    return root[:7] if len(root) > 7 else root


def lexical_coverage(unit: str, notes_text: str, min_words: int = 40) -> bool:
    """Heuristic: most of the unit's keywords appear in the notes, inside a reasonably long passage."""
    kw = keywords(unit)
    if not kw:
        return True
    body = normalize(notes_text)
    # Compare word stems (prefix-truncated) so "Networks" matches "network" and "Topologies" matches "topology".
    present = [_root(k) for k in kw if _root(k) in body]
    if len(present) / len(kw) < 0.5:
        return False
    # Require at least one paragraph that mentions a keyword and is not just a heading.
    for para in re.split(r"\n\s*\n|\n#+ ", notes_text):
        p = normalize(para)
        if any(k in p for k in present) and len(p.split()) >= min_words:
            return True
    return False


def compute_coverage(units: list[str], notes_text: str, llm_items: list[dict] | None) -> tuple[list[CoverageResult], float, float]:
    by_key = {_key(i["subtopic"]): i for i in (llm_items or [])}
    results = []
    for unit in units:
        item = by_key.get(_key(unit))
        if item is None:  # tolerate small title differences
            item = next((v for k, v in by_key.items() if _key(unit) in k or k in _key(unit)), None)
        lexical = lexical_coverage(unit, notes_text)
        if item is None:
            # Without evaluator evidence a unit can never count as covered.
            status = "partial" if lexical else "missing"
            results.append(CoverageResult(unit, status, None, "", False, lexical, "Evaluator did not assess this unit; lexical check only."))
            continue
        quote = item.get("evidence_quote", "") or ""
        verified = quote_found(quote, notes_text) if quote else False
        llm_status = item.get("status")
        if llm_status == "covered" and verified:
            status, note = "covered", ""
        elif llm_status == "covered":
            status, note = "partial", "Evaluator said covered, but its evidence quote was not found in the notes."
        else:
            status, note = llm_status or "missing", ""
        results.append(CoverageResult(unit, status, llm_status, quote, verified, lexical, note))
    total = len(units) or 1
    coverage = 100.0 * sum(r.status == "covered" for r in results) / total
    lexical_pct = 100.0 * sum(r.lexical_hit for r in results) / total
    return results, round(coverage, 1), round(lexical_pct, 1)


def coverage_to_dicts(results: list[CoverageResult]) -> list[dict]:
    return [asdict(r) for r in results]
