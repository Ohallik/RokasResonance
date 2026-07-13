"""
barcode_labels.py - Printable Code128 barcode sheets for the handheld scanner.

Two sheets, both a 3-column grid on letter paper, that she prints once and keeps
by the Bulk Check Out / Check In window:

  * Instrument barcodes - BRASS & WOODWIND only (percussion excluded), sorted by
    instrument type (category) A-Z.  Each label = a Code128 of the instrument's
    barcode value (the value the "Instrument Barcode" field / get_instrument_by_
    barcode expects), captioned with the instrument TYPE above and the written
    barcode number under the bars, so she can also eyeball which is which.

  * Student barcodes - every student who has a district Student ID, sorted by
    last name then first.  Each label = a Code128 of the STUDENT ID (the value the
    "Student ID" field / find_student_by_student_id expects), captioned with the
    student's name and grade.

Pure PDF generation (reportlab): the caller picks the output path and opens it.
"""

import os

from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_CENTER
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Table, TableStyle,
                                Spacer)
from reportlab.graphics.barcode import code128

# ── Instrument-family classification (from the inventory `category` field) ────
# Only brass + woodwinds get a barcode; percussion, strings, etc. are excluded.
WOODWINDS = {"Flute", "Oboe", "Clarinet", "Bass Clarinet", "Bassoon",
             "Alto Saxophone", "Tenor Saxophone", "Baritone Saxophone"}
BRASS = {"Trumpet", "French Horn", "Trombone", "Baritone", "Euphonium", "Tuba"}

COLUMNS = 3
_MARGIN = 0.5 * inch
_CONTENT_W = letter[0] - 2 * _MARGIN


def instrument_family(category):
    """'Woodwind' / 'Brass' for the categories we print, else None (excluded).

    Accepts BOTH a family-level category ("Brass"/"Woodwind", as the live
    inventory stores it) and a specific instrument type ("Trumpet"/"Flute", as
    the add-instrument picker offers) — so percussion, electronics, guitars,
    keyboards, etc. are excluded either way."""
    c = (category or "").strip()
    cl = c.lower()
    if cl == "brass":
        return "Brass"
    if cl in ("woodwind", "woodwinds"):
        return "Woodwind"
    if c in WOODWINDS:
        return "Woodwind"
    if c in BRASS:
        return "Brass"
    return None


def _val(row, key):
    """Safe read from a sqlite Row or dict."""
    try:
        v = row[key]
    except (KeyError, IndexError, TypeError):
        return ""
    return "" if v is None else str(v)


# ── styles ────────────────────────────────────────────────────────────────────

def _title_style():
    return ParagraphStyle("bc_title", fontName="Helvetica-Bold", fontSize=14,
                          alignment=TA_CENTER, spaceAfter=2)


def _sub_title_style():
    return ParagraphStyle("bc_subtitle", fontName="Helvetica", fontSize=9,
                          alignment=TA_CENTER, textColor=colors.grey)


def _head_style():
    return ParagraphStyle("bc_head", fontName="Helvetica-Bold", fontSize=10,
                          alignment=TA_CENTER, leading=12)


def _sub_style():
    return ParagraphStyle("bc_sub", fontName="Helvetica", fontSize=8,
                          alignment=TA_CENTER, textColor=colors.HexColor("#444444"),
                          leading=10, spaceAfter=1)


def _barcode(value):
    bc = code128.Code128(str(value), barHeight=0.42 * inch, barWidth=0.0092 * inch,
                         humanReadable=True, quiet=False)
    bc.hAlign = "CENTER"
    return bc


def _cell(caption_flowables, value):
    """One label = caption line(s) + a centered Code128 (value printed beneath)."""
    return list(caption_flowables) + [Spacer(1, 2), _barcode(value)]


def _grid_pdf(path, title, subtitle, cells):
    doc = SimpleDocTemplate(path, pagesize=letter, title=title,
                            topMargin=_MARGIN, bottomMargin=_MARGIN,
                            leftMargin=_MARGIN, rightMargin=_MARGIN)
    story = [Paragraph(title, _title_style())]
    if subtitle:
        story.append(Paragraph(subtitle, _sub_title_style()))
    story.append(Spacer(1, 10))
    if not cells:
        story.append(Paragraph("Nothing to print.", _sub_style()))
        doc.build(story)
        return
    rows = []
    for i in range(0, len(cells), COLUMNS):
        row = cells[i:i + COLUMNS]
        row += [""] * (COLUMNS - len(row))       # pad the last row
        rows.append(row)
    col_w = _CONTENT_W / COLUMNS
    tbl = Table(rows, colWidths=[col_w] * COLUMNS)
    tbl.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("TOPPADDING", (0, 0), (-1, -1), 9),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 11),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.grey),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
    ]))
    story.append(tbl)
    doc.build(story)


# ── public exports ────────────────────────────────────────────────────────────

def export_instrument_barcodes(instruments, path):
    """Brass + woodwind instruments (percussion excluded), sorted by type A-Z.
    Returns the number of labels printed."""
    items = []
    for r in instruments:
        cat = _val(r, "category").strip()
        if instrument_family(cat) is None:
            continue
        code = _val(r, "barcode").strip() or _val(r, "district_no").strip()
        if not code:
            continue                              # nothing scannable
        items.append((cat, code))
    items.sort(key=lambda t: (t[0].lower(), t[1]))
    cells = [_cell([Paragraph(cat, _head_style())], code) for cat, code in items]
    _grid_pdf(path, "Instrument Barcodes",
              "Brass & Woodwind, sorted by type", cells)
    return len(items)


def export_student_barcodes(students, path):
    """Students with a district Student ID, sorted by last then first name.
    Returns (printed, skipped) — skipped = students with no Student ID to scan."""
    items, skipped = [], 0
    for s in students:
        sid = _val(s, "student_id").strip()
        last = _val(s, "last_name").strip()
        first = _val(s, "first_name").strip()
        grade = _val(s, "grade").strip()
        if not sid:
            skipped += 1
            continue
        items.append((last, first, grade, sid))
    items.sort(key=lambda t: (t[0].lower(), t[1].lower()))
    cells = []
    for last, first, grade, sid in items:
        name = ", ".join(p for p in (last, first) if p) or "(no name)"
        caption = [Paragraph(name, _head_style())]
        if grade:
            caption.append(Paragraph(f"Grade {grade}", _sub_style()))
        cells.append(_cell(caption, sid))
    _grid_pdf(path, "Student Barcodes",
              "Sorted by last name, then first name", cells)
    return len(items), skipped
