"""TEST FIXTURES: programmatically built documents for ingestion tests.

These are synthetic test inputs, clearly separate from application data.
"""
from __future__ import annotations

from pathlib import Path


def make_pdf(path: Path) -> Path:
    import pymupdf as fitz

    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 80), "OSI Reference Model", fontsize=20, fontname="hebo")
    page.insert_text((72, 120), "The OSI model divides network communication into seven layers.", fontsize=11)
    page.insert_text((72, 140), "Each layer provides services to the layer above it.", fontsize=11)
    page.insert_text((72, 170), "- Physical layer transmits raw bits", fontsize=11)
    page.insert_text((72, 186), "- Data link layer handles framing", fontsize=11)
    page2 = doc.new_page()
    page2.insert_text((72, 80), "Transport Layer", fontsize=20, fontname="hebo")
    page2.insert_text((72, 120), "TCP provides reliable, connection-oriented delivery of segments.", fontsize=11)
    page2.insert_text((72, 140), "print('hello')", fontsize=10, fontname="cour")
    doc.save(str(path))
    return path


def make_scanned_pdf(path: Path) -> Path:
    """A PDF whose only page content is an image (no text layer)."""
    import pymupdf as fitz
    from PIL import Image, ImageDraw

    img_path = path.with_suffix(".png")
    img = Image.new("RGB", (1200, 800), "white")
    ImageDraw.Draw(img).text((50, 50), "Scanned lecture page about photosynthesis", fill="black")
    img.save(img_path)
    doc = fitz.open()
    page = doc.new_page()
    page.insert_image(page.rect, filename=str(img_path))
    doc.save(str(path))
    return path


def make_docx(path: Path) -> Path:
    import docx

    d = docx.Document()
    d.add_heading("Newton's Laws of Motion", level=1)
    d.add_paragraph("Newton's first law states that an object remains at rest or in uniform motion unless acted on by a net force.")
    d.add_heading("Second Law", level=2)
    d.add_paragraph("The net force equals mass times acceleration: F = ma.")
    d.add_paragraph("Force is measured in newtons", style="List Bullet")
    d.add_paragraph("Mass is measured in kilograms", style="List Bullet")
    table = d.add_table(rows=2, cols=2)
    table.cell(0, 0).text, table.cell(0, 1).text = "Quantity", "Unit"
    table.cell(1, 0).text, table.cell(1, 1).text = "Force", "N"
    d.save(str(path))
    return path


def make_pptx(path: Path) -> Path:
    from pptx import Presentation
    from pptx.util import Inches

    prs = Presentation()
    s1 = prs.slides.add_slide(prs.slide_layouts[1])
    s1.shapes.title.text = "Causes of the Industrial Revolution"
    body = s1.placeholders[1].text_frame
    body.text = "Agricultural improvements increased food supply"
    p = body.add_paragraph()
    p.text = "Availability of coal and iron"
    p.level = 1
    s1.notes_slide.notes_text_frame.text = "Emphasise Britain's geographic advantages."
    s2 = prs.slides.add_slide(prs.slide_layouts[5])
    s2.shapes.title.text = "Key Inventions"
    rows = s2.shapes.add_table(2, 2, Inches(1), Inches(2), Inches(6), Inches(1)).table
    rows.cell(0, 0).text, rows.cell(0, 1).text = "Invention", "Year"
    rows.cell(1, 0).text, rows.cell(1, 1).text = "Spinning jenny", "1764"
    prs.save(str(path))
    return path


def make_markdown(path: Path) -> Path:
    path.write_text(
        "# Sorting Algorithms\n\nSorting arranges items in order.\n\n## Bubble Sort\n\n"
        "Bubble sort repeatedly swaps adjacent elements.\n\n- Time complexity: O(n^2)\n- Space: O(1)\n\n"
        "```python\ndef bubble(a):\n    pass\n```\n\n| Algorithm | Best |\n|---|---|\n| Bubble | O(n) |\n",
        encoding="utf-8")
    return path


def make_text(path: Path) -> Path:
    path.write_text(
        "SUPPLY AND DEMAND\n\nThe law of demand states that quantity demanded falls as price rises.\n\n"
        "1.1 Market Equilibrium\nEquilibrium occurs where supply equals demand.\n", encoding="utf-8")
    return path
