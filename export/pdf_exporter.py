"""PDF export (ReportLab): title page, table of contents, numbered pages, styled
notes with provenance markers, tables, code, rendered flowcharts, answer keys."""
from __future__ import annotations

import html
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (BaseDocTemplate, Frame, KeepTogether, PageBreak, PageTemplate, Paragraph, Preformatted,
                                Spacer, Table, TableStyle)
from reportlab.platypus.tableofcontents import TableOfContents

from config.settings import get_settings
from export.collect import PackBundle, collect_pack, models_used
from export.markdown_exporter import slug
from export.mermaid_render import flowchart_drawing
from prompt_engine.prompt_router import RESOURCE_LABELS
from storage.repository import Repository

PROV_LABEL = {"source": ("From source", "#2F5D8A"), "supplementary": ("Supplementary explanation", "#B07A12"),
              "inferred": ("Inferred / uncertain", "#9B2C2C")}

_FONTS: dict[str, str] | None = None


def fonts() -> dict[str, str]:
    """Register a Unicode TTF family if available (Greek letters, ², √, ≈...), else use built-in Helvetica."""
    global _FONTS
    if _FONTS is not None:
        return _FONTS
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    candidates = [
        (Path("C:/Windows/Fonts"), "arial.ttf", "arialbd.ttf", "ariali.ttf", "consola.ttf"),
        (Path("/usr/share/fonts/truetype/dejavu"), "DejaVuSans.ttf", "DejaVuSans-Bold.ttf", "DejaVuSans-Oblique.ttf", "DejaVuSansMono.ttf"),
        (Path("/Library/Fonts"), "Arial.ttf", "Arial Bold.ttf", "Arial Italic.ttf", "Courier New.ttf"),
    ]
    for folder, reg, bold, italic, mono in candidates:
        if all((folder / f).exists() for f in (reg, bold, italic, mono)):
            pdfmetrics.registerFont(TTFont("SP", str(folder / reg)))
            pdfmetrics.registerFont(TTFont("SP-Bold", str(folder / bold)))
            pdfmetrics.registerFont(TTFont("SP-Italic", str(folder / italic)))
            pdfmetrics.registerFont(TTFont("SP-Mono", str(folder / mono)))
            pdfmetrics.registerFontFamily("SP", normal="SP", bold="SP-Bold", italic="SP-Italic", boldItalic="SP-Bold")
            _FONTS = {"body": "SP", "bold": "SP-Bold", "italic": "SP-Italic", "mono": "SP-Mono"}
            return _FONTS
    _FONTS = {"body": "Helvetica", "bold": "Helvetica-Bold", "italic": "Helvetica-Oblique", "mono": "Courier"}
    return _FONTS


def styles() -> dict[str, ParagraphStyle]:
    f = fonts()
    base = getSampleStyleSheet()
    s = {
        "title": ParagraphStyle("SPTitle", parent=base["Title"], fontName=f["bold"], fontSize=26, leading=32, spaceAfter=14,
                                textColor=colors.HexColor("#1F2933")),
        "subtitle": ParagraphStyle("SPSub", fontName=f["body"], fontSize=12, leading=17, alignment=TA_CENTER,
                                   textColor=colors.HexColor("#52606D")),
        "h1": ParagraphStyle("SPH1", fontName=f["bold"], fontSize=18, leading=23, spaceBefore=6, spaceAfter=10,
                             textColor=colors.HexColor("#2F5D8A")),
        "h2": ParagraphStyle("SPH2", fontName=f["bold"], fontSize=14, leading=18, spaceBefore=12, spaceAfter=6,
                             textColor=colors.HexColor("#1F2933")),
        "h3": ParagraphStyle("SPH3", fontName=f["bold"], fontSize=11.5, leading=15, spaceBefore=9, spaceAfter=3,
                             textColor=colors.HexColor("#1F2933")),
        "body": ParagraphStyle("SPBody", fontName=f["body"], fontSize=10, leading=14.2, spaceAfter=5),
        "small": ParagraphStyle("SPSmall", fontName=f["italic"], fontSize=8.3, leading=11, textColor=colors.HexColor("#6B7280"),
                                spaceAfter=3),
        "bullet": ParagraphStyle("SPBullet", fontName=f["body"], fontSize=10, leading=14, leftIndent=14, bulletIndent=4, spaceAfter=2),
        "code": ParagraphStyle("SPCode", fontName=f["mono"], fontSize=8.3, leading=10.5, backColor=colors.HexColor("#F3F1EC"),
                               borderPadding=5, leftIndent=4, spaceBefore=3, spaceAfter=6),
        "cell": ParagraphStyle("SPCell", fontName=f["body"], fontSize=8.8, leading=11.5),
        "toc1": ParagraphStyle("TOC1", fontName=f["body"], fontSize=11, leading=16, leftIndent=10),
    }
    return s


# $...$ / $$...$$ with pandoc's rule: no whitespace just inside the delimiters, and the closing $ not followed by a
# digit, so prices such as "$5 and $10" are not treated as maths.
MATH_RE = re.compile(r"\$\$(.+?)\$\$|\$(?!\s)([^$\n]+?)(?<!\s)\$(?!\d)")


def math_markup(expr_escaped: str, font_size: float = 10.0) -> str:
    """Rendered equation image if mathtext can draw it, else monospace text."""
    from export.math_render import render_math

    f = fonts()
    rendered = render_math(html.unescape(expr_escaped), font_size)
    if rendered is None:
        return f'<font face="{f["mono"]}" color="#2F5D8A">{expr_escaped}</font>'
    path, width, height = rendered
    return f'<img src="{html.escape(path)}" width="{width:.1f}" height="{height:.1f}" valign="middle"/>'


def inline(text: str, font_size: float = 10.0) -> str:
    """Escape text and convert simple Markdown inline syntax (and $maths$) to ReportLab markup."""
    f = fonts()
    text = html.escape(text, quote=False)
    protected: list[str] = []

    def protect(markup: str) -> str:
        protected.append(markup)
        return f"\x00{len(protected) - 1}\x00"

    # Code and maths first, as placeholders, so _ and * inside them are not read as italics/bold.
    text = re.sub(r"`([^`]+)`", lambda m: protect(f'<font face="{f["mono"]}">{m.group(1)}</font>'), text)
    text = MATH_RE.sub(lambda m: protect(math_markup(m.group(1) or m.group(2), font_size)), text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"(?<![\w*])\*([^*\n]+)\*(?![\w*])", r"<i>\1</i>", text)
    text = re.sub(r"(?<![\w_])_([^_\n]+)_(?![\w_])", r"<i>\1</i>", text)
    return re.sub(r"\x00(\d+)\x00", lambda m: protected[int(m.group(1))], text)


def _table(rows: list[list[str]], st, widths=None) -> Table:
    data = [[Paragraph(inline(c), st["cell"]) for c in r] for r in rows]
    t = Table(data, colWidths=widths, repeatRows=1, hAlign="LEFT")
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E6EDF4")),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#C9CED6")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]))
    return t


def markdown_flowables(md: str, st) -> list:
    """Convert the Markdown subset produced by the generators into flowables."""
    out: list = []
    lines = md.replace("\r\n", "\n").split("\n")
    i = 0
    para: list[str] = []

    def flush():
        if para:
            out.append(Paragraph(inline(" ".join(p.strip() for p in para)), st["body"]))
            para.clear()

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if stripped.startswith("```"):
            flush()
            code = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code.append(lines[i])
                i += 1
            out.append(Preformatted("\n".join(code) or " ", st["code"], maxLineLength=95))
            i += 1
            continue
        if stripped.startswith("|") and stripped.endswith("|") and stripped.count("|") >= 3:
            flush()
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
                    rows.append(cells)
                i += 1
            if rows:
                width = max(len(r) for r in rows)
                rows = [r + [""] * (width - len(r)) for r in rows]
                out.append(_table(rows, st, [16.5 * cm / width] * width))
                out.append(Spacer(1, 4))
            continue
        m = re.match(r"^(#{1,6})\s+(.*)", stripped)
        if m:
            flush()
            out.append(Paragraph(inline(m.group(2)), st["h3"]))
            i += 1
            continue
        m = re.match(r"^(\s*)([-*+]|\d+[.)])\s+(.*)", line)
        if m:
            flush()
            indent = len(m.group(1).replace("\t", "    ")) // 2
            bullet = "•" if not m.group(2)[0].isdigit() else m.group(2)
            style = ParagraphStyle(f"b{indent}", parent=st["bullet"], leftIndent=14 + 12 * indent, bulletIndent=4 + 12 * indent)
            out.append(Paragraph(inline(m.group(3)), style, bulletText=bullet))
            i += 1
            continue
        if not stripped:
            flush()
            i += 1
            continue
        para.append(line)
        i += 1
    flush()
    return out


class StudyPackDoc(BaseDocTemplate):
    def __init__(self, filename, title, **kw):
        super().__init__(filename, pagesize=A4, leftMargin=2.2 * cm, rightMargin=2.2 * cm, topMargin=2 * cm,
                         bottomMargin=2 * cm, title=title, author="StudyPack AI", **kw)
        frame = Frame(self.leftMargin, self.bottomMargin, self.width, self.height, id="main")
        self.pack_title = title
        self.addPageTemplates([PageTemplate("first", [frame], onPage=self._first),
                               PageTemplate("normal", [frame], onPage=self._decorate)])

    def _first(self, canvas, doc):
        pass

    def _decorate(self, canvas, doc):
        f = fonts()
        canvas.saveState()
        canvas.setFont(f["body"], 8)
        canvas.setFillColor(colors.HexColor("#6B7280"))
        canvas.drawString(self.leftMargin, 1.2 * cm, self.pack_title[:90])
        canvas.drawRightString(A4[0] - self.rightMargin, 1.2 * cm, f"Page {doc.page}")
        canvas.setStrokeColor(colors.HexColor("#E2DED5"))
        canvas.line(self.leftMargin, 1.5 * cm, A4[0] - self.rightMargin, 1.5 * cm)
        canvas.restoreState()

    def afterFlowable(self, flowable):
        if isinstance(flowable, Paragraph) and flowable.style.name == "SPH1":
            text = flowable.getPlainText()
            key = f"h1-{self.seq.nextf('h1')}"
            self.canv.bookmarkPage(key)
            self.canv.addOutlineEntry(text, key, level=0)
            self.notify("TOCEntry", (0, text, self.page, key))


def _provenance_line(section: dict[str, Any], sources: dict[str, Any], st) -> Paragraph:
    label, color = PROV_LABEL.get(section.get("provenance"), ("Unlabelled", "#6B7280"))
    refs = "; ".join(dict.fromkeys(sources[l]["ref"] for l in section.get("source_labels", []) if l in sources))
    edited = " <i>(edited by student)</i>" if section.get("edited_by_user") else ""
    text = f'<font color="{color}"><b>■ {label}</b></font>{edited}' + (f" — {html.escape(refs)}" if refs else "")
    return Paragraph(text, st["small"])


def topic_flowables(tb, rtypes, st, index: int) -> list:
    out: list = [Paragraph(f"{index}. {inline(tb.topic.title)}", st["h1"])]
    if tb.topic.description:
        out.append(Paragraph(f"<i>{inline(tb.topic.description)}</i>", st["body"]))
    if tb.topic.learning_objectives:
        out.append(Paragraph("<b>Learning objectives</b>", st["body"]))
        out += [Paragraph(inline(o), st["bullet"], bulletText="•") for o in tb.topic.learning_objectives]
    for rtype in rtypes:
        out.append(Paragraph(RESOURCE_LABELS[rtype], st["h2"]))
        data = tb.resources.get(rtype)
        if data is None:
            out.append(Paragraph("<i>Not generated yet for this topic.</i>", st["small"]))
            continue
        out += RENDER[rtype](data, st)
    return out


def r_notes(n, st):
    out = markdown_flowables(n.get("overview", ""), st)
    sources = n.get("_sources", {})
    for s in n.get("sections", []):
        out.append(KeepTogether([Paragraph(inline(s["heading"]), st["h3"]), _provenance_line(s, sources, st)]))
        out += markdown_flowables(s.get("content", ""), st)
    if n.get("key_terms"):
        out.append(Paragraph("Key terms", st["h3"]))
        out.append(_table([["Term", "Definition"]] + [[t["term"], t["definition"]] for t in n["key_terms"]], st, [4.5 * cm, 12 * cm]))
    out.append(Paragraph("Summary", st["h3"]))
    out += markdown_flowables(n.get("summary", ""), st)
    return out


def r_examples(d, st):
    out = []
    for i, ex in enumerate(d.get("examples", []), 1):
        out.append(Paragraph(f"Example {i}: {inline(ex['title'])} <font size=8 color='#6B7280'>({inline(ex['example_type'])})</font>", st["h3"]))
        out.append(Paragraph(f"<b>Problem.</b> {inline(ex['problem'])}", st["body"]))
        for n, step in enumerate(ex.get("steps", []), 1):
            out += markdown_flowables(f"{n}. {step}", st) if "```" not in step else markdown_flowables(step, st)
        out.append(Paragraph(f"<b>Answer.</b> {inline(ex['answer'])}", st["body"]))
        out.append(Paragraph(f"<i>{inline(ex['explanation'])}</i>", st["body"]))
    return out


def r_questions(d, st):
    out = [Paragraph("Suggested important questions based on the provided material (not a prediction of actual exam questions).", st["small"])]
    for i, q in enumerate(d.get("questions", []), 1):
        out.append(Paragraph(f"<b>Q{i}.</b> {inline(q['question'])} <font size=8 color='#6B7280'>"
                             f"({q['question_type'].replace('_', ' ')}, {q['difficulty']})</font>", st["body"]))
        out.append(Paragraph(f"<b>Model answer:</b> {inline(q['model_answer'])}", st["bullet"]))
        if q.get("key_points"):
            out.append(Paragraph(f"<b>Key points:</b> {inline('; '.join(q['key_points']))}", st["bullet"]))
    return out


def r_revision(d, st):
    out = [Paragraph(f"<b>In one line:</b> {inline(d.get('one_line_summary', ''))}", st["body"])]
    if d.get("key_definitions"):
        out.append(_table([["Term", "Definition"]] + [[x["term"], x["definition"]] for x in d["key_definitions"]], st, [4.5 * cm, 12 * cm]))
    for title, key in (("Key concepts", "key_concepts"), ("Relationships", "relationships"), ("Common mistakes", "common_mistakes")):
        if d.get(key):
            out.append(Paragraph(f"<b>{title}</b>", st["body"]))
            out += [Paragraph(inline(x), st["bullet"], bulletText="•") for x in d[key]]
    if d.get("formulas"):
        out.append(Paragraph("<b>Formulas</b>", st["body"]))
        out.append(_table([["Name", "Formula", "Meaning"]] + [[f["name"], f"`{f['expression']}`", f["meaning"]] for f in d["formulas"]],
                          st, [3.5 * cm, 5 * cm, 8 * cm]))
    if d.get("differences"):
        out.append(Paragraph("<b>Important differences</b>", st["body"]))
        out.append(_table([["Compared", "Difference"]] + [[x["items"], x["difference"]] for x in d["differences"]], st, [4.5 * cm, 12 * cm]))
    for proc in d.get("processes", []):
        out.append(Paragraph(f"<b>Process: {inline(proc['name'])}</b>", st["body"]))
        out += [Paragraph(inline(s), st["bullet"], bulletText=f"{i}.") for i, s in enumerate(proc["steps"], 1)]
    return out


def r_flashcards(d, st):
    rows = [["#", "Question", "Answer"]] + [[str(i), c["question"], c["answer"]] for i, c in enumerate(d.get("cards", []), 1)]
    return [_table(rows, st, [0.8 * cm, 7.3 * cm, 8.4 * cm])]


def r_diagrams(d, st):
    out = []
    for dg in d.get("diagrams", []):
        out.append(Paragraph(f"{inline(dg['title'])} <font size=8 color='#6B7280'>({inline(dg['diagram_type'])})</font>", st["h3"]))
        drawing = None
        try:
            drawing = flowchart_drawing(dg["mermaid"])
        except Exception:  # noqa: BLE001 - fall back to source on any layout problem
            drawing = None
        if drawing is not None:
            out.append(drawing)
        else:
            out.append(Paragraph("Diagram type not rendered in PDF; Mermaid source below (renders in the app):", st["small"]))
            out.append(Preformatted(dg["mermaid"], st["code"], maxLineLength=95))
        out.append(Paragraph(f"<i>{inline(dg['caption'])}</i>", st["body"]))
    if not d.get("diagrams"):
        out.append(Paragraph(f"<i>No diagram: {inline(d.get('no_diagram_reason') or 'not applicable')}</i>", st["small"]))
    return out


def r_quiz(d, st):
    out, key = [], []
    letters = "ABCDEFGH"
    for i, q in enumerate(d.get("questions", []), 1):
        out.append(Paragraph(f"<b>{i}.</b> {inline(q['question'])} <font size=8 color='#6B7280'>({q['question_type'].replace('_', ' ')})</font>", st["body"]))
        out += [Paragraph(inline(o), st["bullet"], bulletText=f"{letters[j]})") for j, o in enumerate(q.get("options", []))]
        key.append(Paragraph(f"<b>{i}.</b> {inline('; '.join(q['correct_answers']))} — {inline(q['explanation'])}", st["small"]))
    return out + [Paragraph("<b>Answer key</b>", st["body"])] + key


RENDER = {"notes": r_notes, "examples": r_examples, "questions": r_questions, "revision": r_revision,
          "flashcards": r_flashcards, "diagrams": r_diagrams, "quiz": r_quiz}


def build_pdf(pack: PackBundle, path: Path) -> Path:
    st = styles()
    p = pack.project
    doc = StudyPackDoc(str(path), p.name)
    story: list = [Spacer(1, 5 * cm), Paragraph(inline(p.name), st["title"]),
                   Paragraph(inline(p.subject or pack.analysis.get("subject", "")), st["subtitle"]), Spacer(1, 0.6 * cm),
                   Paragraph(f"Level: {inline(p.academic_level or pack.analysis.get('estimated_level', 'n/a'))}", st["subtitle"]),
                   Paragraph(f"Generated {datetime.now().strftime('%d %B %Y')} with StudyPack AI", st["subtitle"]),
                   Paragraph(f"Models: {inline(', '.join(models_used(pack)) or 'n/a')}", st["subtitle"]), Spacer(1, 1.5 * cm),
                   Paragraph("Source documents: " + inline(", ".join(d.filename for d in pack.documents)), st["subtitle"]),
                   Spacer(1, 2.5 * cm),
                   Paragraph("Provenance markers: <font color='#2F5D8A'><b>■ From source</b></font> — stated in your documents; "
                             "<font color='#B07A12'><b>■ Supplementary</b></font> — added background explanation; "
                             "<font color='#9B2C2C'><b>■ Inferred</b></font> — interpretation, verify before relying on it.", st["small"])]
    from reportlab.platypus.doctemplate import NextPageTemplate
    story += [NextPageTemplate("normal"), PageBreak(), Paragraph("Contents", st["h2"])]
    toc = TableOfContents()
    toc.levelStyles = [st["toc1"]]
    story += [toc, PageBreak()]
    for i, tb in enumerate(pack.topics, 1):
        story += topic_flowables(tb, pack.resource_types, st, i)
        story.append(PageBreak())
    doc.multiBuild(story)
    return path


def export_pdf(repo: Repository, project_id: str, resource_types: list[str] | None = None, topic_ids: list[str] | None = None) -> Path:
    pack = collect_pack(repo, project_id, resource_types, topic_ids)
    out_dir = get_settings().generated_dir / project_id
    out_dir.mkdir(parents=True, exist_ok=True)
    return build_pdf(pack, out_dir / f"{slug(pack.project.name)}.pdf")
