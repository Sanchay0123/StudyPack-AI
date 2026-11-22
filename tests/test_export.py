"""Export tests: Markdown rendering, PDF building, Mermaid-to-drawing conversion."""
from __future__ import annotations

from export.markdown_exporter import render_notes, render_quiz
from export.mermaid_render import flowchart_drawing, parse_flowchart, to_flowchart
from export.pdf_exporter import inline, markdown_flowables, styles


def test_flowchart_parsing_edges_labels_chains():
    direction, order, labels, edges = parse_flowchart(
        'flowchart LR\n A["Client (browser)"] -->|request| B{Server}\n B --> C[DB] --> D\n D -- reply --> A\n E & F --> B')
    assert direction == "LR" and labels["A"] == "Client (browser)" and labels["B"] == "Server"
    assert ("A", "B", "request") in edges and ("C", "D", "") in edges and ("D", "A", "reply") in edges
    assert ("E", "B", "") in edges and ("F", "B", "") in edges


def test_cycles_and_other_types_render():
    assert flowchart_drawing("graph TD\n A --> B\n B --> A") is not None
    assert flowchart_drawing("mindmap\n  root((Cells))\n    Nucleus\n    Ribosome") is not None
    assert flowchart_drawing("timeline\n  title T\n  1764 : Jenny\n  1769 : Engine") is not None
    assert to_flowchart("sequenceDiagram\n A->>B: hi") is None  # falls back to source in the PDF


def test_inline_markup_escapes_html_and_converts_markdown():
    out = inline("**bold** <script> `code` $x^2$")
    assert "<b>bold</b>" in out and "&lt;script&gt;" in out and "code" in out and "<script>" not in out


def test_markdown_flowables_handle_tables_code_lists():
    flows = markdown_flowables("Intro text\n\n| A | B |\n|---|---|\n| 1 | 2 |\n\n```python\nprint(1)\n```\n- item\n  - nested", styles())
    kinds = [type(f).__name__ for f in flows]
    assert kinds == ["Paragraph", "Table", "Spacer", "Preformatted", "Paragraph", "Paragraph"]


def test_markdown_renderers_include_provenance_and_answer_key():
    notes = {"overview": "o", "summary": "s", "key_terms": [], "_sources": {"S1": {"chunk_id": "c", "ref": "lec.pdf, p. 2"}},
             "sections": [{"heading": "H", "content": "c", "provenance": "source", "source_labels": ["S1"]}]}
    md = render_notes(notes)
    assert "From source" in md and "lec.pdf, p. 2" in md
    quiz = render_quiz({"questions": [{"question": "Q", "question_type": "mcq", "difficulty": "easy", "options": ["a", "b", "c"],
                                       "correct_answers": ["b"], "explanation": "because"}]})
    assert "B) b" in quiz and "Answer key" in quiz and quiz.index("Answer key") > quiz.index("B) b")


def test_equations_render_as_images_with_safe_fallbacks():
    out = inline(r"Use $v^2 = u^2 + 2as$ with $x_1$; it costs $5 and $10; bad $\begin{align}x\end{align}$ and _italic_")
    assert out.count("<img ") == 2, "two renderable equations become images"
    assert "costs $5 and $10" in out, "prices are not treated as maths"
    assert r"\begin{align}" in out and ("SP-Mono" in out or "Courier" in out), "unsupported TeX falls back to monospace text"
    assert "<i>italic</i>" in out and "<i>1</i>" not in out, "underscores inside maths are not italics"


def test_pdf_with_equations_builds(tmp_path):
    from reportlab.platypus import SimpleDocTemplate
    flows = markdown_flowables("The equations are:\n\n1. $v = u + at$\n2. $s = ut + \\frac{1}{2}at^2$\n", styles())
    SimpleDocTemplate(str(tmp_path / "eq.pdf")).build(flows)
    import pymupdf
    assert len(pymupdf.open(str(tmp_path / "eq.pdf"))[0].get_images()) == 2
