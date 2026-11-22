"""Text-matching helpers shared by the deterministic checkers."""
from __future__ import annotations

import re

from prompt_engine.context_manager import keywords


def normalize(text: str) -> str:
    text = re.sub(r"[`*_#>|]", " ", text.lower())
    text = re.sub(r"[^\w\s$^=+\-/().%]", " ", text)
    return " ".join(text.split())


def quote_found(quote: str, haystack: str, threshold: float = 0.8) -> bool:
    """True if `quote` (approximately) occurs in `haystack`.

    Exact normalized substring match, or >= threshold of the quote's word
    trigrams present in the haystack (tolerates small paraphrase/formatting).
    """
    q, h = normalize(quote), normalize(haystack)
    if not q or len(q.split()) < 3:
        return False
    if q in h:
        return True
    words = q.split()
    grams = [" ".join(words[i:i + 3]) for i in range(len(words) - 2)]
    if not grams:
        return False
    hits = sum(1 for g in grams if g in h)
    if hits / len(grams) >= threshold:
        return True
    return _stem_window_match(q, h, max(threshold, 0.85))


_STOP = {"the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "is", "are", "it", "its", "this", "that", "these",
         "by", "with", "as", "be", "at", "from", "which"}


def stem(word: str) -> str:
    """Crude suffix stripping so 'establishes' / 'establishing' / 'established' compare equal."""
    for suffix in ("ations", "ation", "ings", "ing", "edly", "ed", "es", "s", "ly"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 4:
            return word[: -len(suffix)]
    return word


def _stem_window_match(q: str, h: str, threshold: float) -> bool:
    """>= threshold of the quote's content-word stems occur within one local window of the haystack.

    Tolerates the evaluator changing word forms ("establishes" vs "establishing") while still
    requiring the evidence to be in one place in the notes, so quotes about absent content fail.
    """
    q_stems = [stem(w) for w in re.findall(r"[a-z0-9]+", q) if w not in _STOP]
    if len(q_stems) < 3:
        return False
    h_stems = [stem(w) for w in re.findall(r"[a-z0-9]+", h) if w not in _STOP]
    need = set(q_stems)
    window = max(len(q_stems) * 2, 8)
    for i in range(0, max(1, len(h_stems) - window + 1)):
        if len(need & set(h_stems[i:i + window])) / len(need) >= threshold:
            return True
    return False


def keyword_support(text: str, reference: str) -> float:
    """Share of the content keywords of `text` that also occur in `reference` (0..1)."""
    kw = keywords(text)
    if not kw:
        return 1.0
    ref = keywords(reference)
    return len(kw & ref) / len(kw)


NUMBER_RE = re.compile(r"(?<![\w.])(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)(?![\w])")


def numbers_in(text: str) -> set[str]:
    """Significant numbers (ignores 0-10, which are usually list numbering or trivial)."""
    out = set()
    for m in NUMBER_RE.findall(text):
        value = m.replace(",", "")
        try:
            if float(value) <= 10 and "." not in value:
                continue
        except ValueError:
            continue
        out.add(value)
    return out


SENTENCE_RE = re.compile(r"(?<=[.!?])\s+|\n+")


def sentence_support(text: str, reference: str, min_share: float = 0.5) -> float:
    """Share of sentences (with >= 4 content words) whose keywords mostly occur in `reference`.

    Heuristic lexical grounding: elaboration and paraphrase lower it, so it is
    reported as an indicator, not as proof of (un)faithfulness.
    """
    ref = keywords(reference)
    scored = []
    for sent in SENTENCE_RE.split(text):
        kw = keywords(sent)
        if len(kw) < 4:
            continue
        scored.append(len(kw & ref) / len(kw) >= min_share)
    if not scored:
        return 1.0
    return sum(scored) / len(scored)
