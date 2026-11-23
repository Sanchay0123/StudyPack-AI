"""Context management: token budgeting, source formatting and chunk selection.

Retrieval is deliberately simple and structural (ADR-003): each topic carries
the chunk ids of the source sections the topic map assigned to it, so the
"retrieval" step is a lookup plus budget-aware trimming. Keyword overlap is
only used to decide which chunks to drop when a topic exceeds the budget.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from prompt_engine.prompt_builder import SOURCE_CLOSE, SOURCE_OPEN, neutralize_source_text
from storage.models import ContentChunk

# Characters per token. Prose tokenises at ~3.5-4, but slides with code, symbols and short lines measured 2.69
# with Qwen3.5, so the default is conservative and is lowered further (never raised) from the real prompt token
# counts the provider reports after each call - see calibrate().
DEFAULT_CHARS_PER_TOKEN = 2.6
CHARS_PER_TOKEN = DEFAULT_CHARS_PER_TOKEN
MIN_CHARS_PER_TOKEN = 1.8


def chars_per_token() -> float:
    return CHARS_PER_TOKEN


def calibrate(prompt_chars: int, prompt_tokens: int | None) -> float:
    """Learn from an actual call: if the material tokenised denser than assumed, tighten the estimate (5% margin)."""
    global CHARS_PER_TOKEN
    if prompt_tokens and prompt_tokens > 200 and prompt_chars > 0:
        observed = prompt_chars / prompt_tokens
        if observed * 0.95 < CHARS_PER_TOKEN:
            CHARS_PER_TOKEN = max(MIN_CHARS_PER_TOKEN, round(observed * 0.95, 3))
    return CHARS_PER_TOKEN


STOPWORDS = set("""a an the and or of to in on for with by from as is are was were be been being this that these those it its
into at which who whom whose what when where why how not no can may might will would should could than then there their
they them he she his her we our you your i also such each other more most some any all both between about over under""".split())


def estimate_tokens(text: str) -> int:
    return int(len(text) / CHARS_PER_TOKEN) + 1


def keywords(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-zA-Z][a-zA-Z0-9\-]{2,}", text.lower()) if w not in STOPWORDS}


@dataclass
class SourceBundle:
    """Formatted source material plus the label -> chunk mapping used in it."""
    text: str
    label_map: dict[str, str] = field(default_factory=dict)  # "S1" -> chunk_id
    references: dict[str, str] = field(default_factory=dict)  # "S1" -> human-readable reference
    dropped_chunks: int = 0
    truncated: bool = False

    @property
    def labels(self) -> list[str]:
        return list(self.label_map)


def format_source(chunks: list[ContentChunk], token_budget: int, max_chunk_chars: int | None = None,
                  label_start: int = 1) -> SourceBundle:
    """Render chunks as labelled source blocks inside the untrusted-data delimiter, within budget."""
    bundle = SourceBundle(text="")
    parts = []
    used = estimate_tokens(SOURCE_OPEN + SOURCE_CLOSE) + 5
    for index, chunk in enumerate(chunks, start=label_start):
        label = f"S{index}"
        content = neutralize_source_text(chunk.content)
        if max_chunk_chars and len(content) > max_chunk_chars:
            content = content[:max_chunk_chars].rsplit(" ", 1)[0] + " [...]"
            bundle.truncated = True
        flag = " [low extraction confidence - verify]" if chunk.needs_review else ""
        block = f"[{label}] ({chunk.source_reference}){flag}\n{content}\n"
        cost = estimate_tokens(block)
        if used + cost > token_budget:
            remaining = token_budget - used
            if remaining > 120 and not parts:
                # Always include at least a truncated first chunk.
                block = block[: int(remaining * CHARS_PER_TOKEN)].rsplit(" ", 1)[0] + " [...]\n"
                parts.append(block)
                bundle.label_map[label] = chunk.chunk_id
                bundle.references[label] = chunk.source_reference
                bundle.truncated = True
            bundle.dropped_chunks = len(chunks) - len(bundle.label_map)
            bundle.truncated = True
            break
        parts.append(block)
        used += cost
        bundle.label_map[label] = chunk.chunk_id
        bundle.references[label] = chunk.source_reference
    bundle.text = f"{SOURCE_OPEN}\n" + "\n".join(parts) + f"{SOURCE_CLOSE}"
    return bundle


def select_chunks_for_topic(topic_chunk_ids: list[str], all_chunks: list[ContentChunk], token_budget: int,
                            focus_text: str = "") -> tuple[list[ContentChunk], int]:
    """Return the topic's chunks in document order, trimmed to the budget.

    When trimming is needed, chunks with the lowest keyword overlap with
    `focus_text` (topic title + subtopics) are dropped first.
    """
    by_id = {c.chunk_id: c for c in all_chunks}
    order = {c.chunk_id: i for i, c in enumerate(all_chunks)}
    chunks = [by_id[cid] for cid in dict.fromkeys(topic_chunk_ids) if cid in by_id]
    chunks.sort(key=lambda c: order[c.chunk_id])
    total = sum(estimate_tokens(c.content) + 25 for c in chunks)
    if total <= token_budget:
        return chunks, 0
    focus = keywords(focus_text)
    scored = sorted(chunks, key=lambda c: (len(keywords(c.content) & focus) / (1 + len(keywords(c.content))) ** 0.5), reverse=True)
    keep, used = [], 0
    for c in scored:
        cost = estimate_tokens(c.content) + 25
        if used + cost <= token_budget:
            keep.append(c)
            used += cost
    keep.sort(key=lambda c: order[c.chunk_id])
    return keep, len(chunks) - len(keep)


def retrieve_by_keywords(query: str, all_chunks: list[ContentChunk], limit: int = 8) -> list[ContentChunk]:
    """Fallback retrieval for topics without attached sections (e.g. topics a student added by hand)."""
    q = keywords(query)
    if not q:
        return []
    scored = []
    for i, c in enumerate(all_chunks):
        text_kw = keywords(c.content + " " + (c.heading or ""))
        overlap = len(q & text_kw)
        heading_bonus = 2 * len(q & keywords(c.heading or ""))
        if overlap:
            scored.append((overlap + heading_bonus, -i, c))
    scored.sort(key=lambda t: (t[0], t[1]), reverse=True)
    picked = [c for _, _, c in scored[:limit]]
    order = {c.chunk_id: i for i, c in enumerate(all_chunks)}
    return sorted(picked, key=lambda c: order[c.chunk_id])


def source_budget(context_length: int, max_output_tokens: int, fixed_prompt_text: str, safety: int = 300) -> int:
    """Tokens left for source material once the fixed prompt and the output reservation are accounted for."""
    return max(0, context_length - max_output_tokens - estimate_tokens(fixed_prompt_text) - safety)


def batch_chunks(chunks: list[ContentChunk], token_budget: int) -> list[list[ContentChunk]]:
    """Split chunks (document order) into consecutive batches that each fit the budget."""
    batches, current, used = [], [], 0
    for c in chunks:
        cost = estimate_tokens(c.content) + 25
        if current and used + cost > token_budget:
            batches.append(current)
            current, used = [], 0
        current.append(c)
        used += cost
    if current:
        batches.append(current)
    return batches
