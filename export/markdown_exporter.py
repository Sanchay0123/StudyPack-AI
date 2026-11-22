"""Markdown export of a complete study pack. Missing resources are stated explicitly, never silently dropped."""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

from config.settings import get_settings
from export.collect import PackBundle, TopicBundle, collect_pack, models_used
from prompt_engine.prompt_router import RESOURCE_LABELS
from storage.repository import Repository

PROV_TAG = {"source": "📘 From source", "supplementary": "📙 Supplementary explanation", "inferred": "📕 Inferred / uncertain"}


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60] or "topic"


def _refs(labels: list[str], sources: dict[str, Any]) -> str:
    refs = [sources[l]["ref"] for l in labels if l in sources]
    return "; ".join(dict.fromkeys(refs))


def render_notes(notes: dict[str, Any]) -> str:
    sources = notes.get("_sources", {})
    out = [notes.get("overview", ""), ""]
    for s in notes.get("sections", []):
        out.append(f"#### {s['heading']}")
        refs = _refs(s.get("source_labels", []), sources)
        out.append(f"*{PROV_TAG.get(s.get('provenance'), s.get('provenance'))}*" + (f" — Source: {refs}" if refs else ""))
        out.append("")
        out.append(s.get("content", ""))
        out.append("")
    if notes.get("key_terms"):
        out.append("#### Key terms\n\n| Term | Definition |\n|---|---|")
        for t in notes["key_terms"]:
            out.append(f"| {t['term']} | {t['definition'].replace('|', '/')} |")
        out.append("")
    out.append(f"#### Summary\n\n{notes.get('summary', '')}\n")
    return "\n".join(out)


def render_examples(data: dict[str, Any]) -> str:
    out = []
    for i, ex in enumerate(data.get("examples", []), 1):
        out.append(f"**Example {i}: {ex['title']}** _({ex['example_type']}; {PROV_TAG.get(ex.get('provenance'), '')})_\n")
        out.append(f"**Problem.** {ex['problem']}\n")
        out.append("**Solution.**\n")
        out += [f"{n}. {step}" for n, step in enumerate(ex.get("steps", []), 1)]
        out.append(f"\n**Answer.** {ex['answer']}\n\n**Why it matters.** {ex['explanation']}\n")
    return "\n".join(out)


def render_questions(data: dict[str, Any]) -> str:
    out = ["_Suggested important questions based on the provided material (not a prediction of actual exam questions)._\n"]
    for i, q in enumerate(data.get("questions", []), 1):
        out.append(f"**Q{i}.** {q['question']} _({q['question_type'].replace('_', ' ')}, {q['difficulty']})_\n")
        out.append(f"<details><summary>Model answer</summary>\n\n{q['model_answer']}\n\nKey points: {'; '.join(q.get('key_points', []))}\n\n</details>\n")
    return "\n".join(out)


def render_revision(data: dict[str, Any]) -> str:
    out = [f"**In one line:** {data.get('one_line_summary', '')}\n"]
    if data.get("key_definitions"):
        out.append("**Definitions**\n")
        out += [f"- **{d['term']}**: {d['definition']}" for d in data["key_definitions"]]
        out.append("")
    if data.get("key_concepts"):
        out.append("**Key concepts**\n")
        out += [f"- {c}" for c in data["key_concepts"]]
        out.append("")
    if data.get("formulas"):
        out.append("**Formulas**\n")
        out += [f"- **{f['name']}**: `{f['expression']}` — {f['meaning']}" for f in data["formulas"]]
        out.append("")
    if data.get("relationships"):
        out.append("**Relationships**\n")
        out += [f"- {r}" for r in data["relationships"]]
        out.append("")
    if data.get("differences"):
        out.append("**Important differences**\n\n| Compared | Difference |\n|---|---|")
        out += [f"| {d['items']} | {d['difference'].replace('|', '/')} |" for d in data["differences"]]
        out.append("")
    for proc in data.get("processes", []):
        out.append(f"**Process: {proc['name']}**\n")
        out += [f"{i}. {s}" for i, s in enumerate(proc["steps"], 1)]
        out.append("")
    if data.get("common_mistakes"):
        out.append("**Common mistakes**\n")
        out += [f"- {m}" for m in data["common_mistakes"]]
        out.append("")
    return "\n".join(out)


def render_flashcards(data: dict[str, Any]) -> str:
    out = ["| # | Question | Answer | Difficulty |", "|---|---|---|---|"]
    for i, c in enumerate(data.get("cards", []), 1):
        out.append(f"| {i} | {c['question'].replace('|', '/')} | {c['answer'].replace('|', '/')} | {c['difficulty']} |")
    return "\n".join(out) + "\n"


def render_diagrams(data: dict[str, Any]) -> str:
    out = []
    for d in data.get("diagrams", []):
        out.append(f"**{d['title']}** _({d['diagram_type']})_\n\n```mermaid\n{d['mermaid']}\n```\n\n{d['caption']}\n")
    if not data.get("diagrams"):
        out.append(f"_No diagram generated: {data.get('no_diagram_reason') or 'not applicable to this topic'}._\n")
    return "\n".join(out)


def render_quiz(data: dict[str, Any]) -> str:
    out, key = [], ["**Answer key**\n"]
    for i, q in enumerate(data.get("questions", []), 1):
        out.append(f"**{i}.** {q['question']} _({q['question_type'].replace('_', ' ')}, {q['difficulty']})_\n")
        letters = "ABCDEFGH"
        out += [f"   - {letters[j]}) {o}" for j, o in enumerate(q.get("options", []))]
        out.append("")
        key.append(f"{i}. **{'; '.join(q['correct_answers'])}** — {q['explanation']}")
    return "\n".join(out + [""] + key) + "\n"


RENDERERS = {"notes": render_notes, "examples": render_examples, "questions": render_questions, "revision": render_revision,
             "flashcards": render_flashcards, "diagrams": render_diagrams, "quiz": render_quiz}


def render_topic(tb: TopicBundle, index: int, resource_types: list[str]) -> str:
    out = [f"## {index}. {tb.topic.title}\n"]
    if tb.topic.description:
        out.append(f"_{tb.topic.description}_\n")
    if tb.topic.learning_objectives:
        out.append("**Learning objectives**\n")
        out += [f"- {o}" for o in tb.topic.learning_objectives]
        out.append("")
    for rtype in resource_types:
        out.append(f"### {RESOURCE_LABELS[rtype]}\n")
        if rtype in tb.resources:
            out.append(RENDERERS[rtype](tb.resources[rtype]))
        else:
            out.append("_Not generated yet for this topic._\n")
    return "\n".join(out)


def build_markdown(pack: PackBundle) -> str:
    p = pack.project
    lines = [f"# {p.name}", "", f"**Subject:** {p.subject or pack.analysis.get('subject', 'n/a')}  ",
             f"**Level:** {p.academic_level or pack.analysis.get('estimated_level', 'n/a')}  ",
             f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M')} with StudyPack AI  ",
             f"**Models:** {', '.join(models_used(pack)) or 'n/a'}  ",
             f"**Source documents:** {', '.join(d.filename for d in pack.documents)}", "",
             "> **Provenance legend.** 📘 From source = stated in your uploaded documents · 📙 Supplementary = added "
             "background explanation · 📕 Inferred = interpretation; verify before relying on it.", "",
             "## Contents", ""]
    for i, tb in enumerate(pack.topics, 1):
        lines.append(f"{i}. [{tb.topic.title}](#{i}-{slug(tb.topic.title)})")
    lines.append("")
    for i, tb in enumerate(pack.topics, 1):
        lines.append(render_topic(tb, i, pack.resource_types))
        lines.append("\n---\n")
    return "\n".join(lines)


def export_markdown(repo: Repository, project_id: str, resource_types: list[str] | None = None,
                    topic_ids: list[str] | None = None) -> Path:
    pack = collect_pack(repo, project_id, resource_types, topic_ids)
    text = build_markdown(pack)
    out_dir = get_settings().generated_dir / project_id
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{slug(pack.project.name)}.md"
    path.write_text(text, encoding="utf-8")
    return path
