"""
pdf_generator.py - Generate Bellevue School District Equipment Loan Form PDFs
Matches the Charms single-page layout.
"""

import math
import os
from datetime import datetime

from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Table, TableStyle,
    Spacer, HRFlowable
)
from reportlab.lib.enums import TA_CENTER, TA_LEFT


SCHOOL_NAME   = "Chinook Middle School Band"
DISTRICT_NAME = "Bellevue School District"
MAINT_YEAR    = "$75"
MAINT_SUMMER  = "$20"

CW = 7.0 * inch   # usable content width (letter − 0.75" margins each side)


# ── Instrument-specific accessories ──────────────────────────────────────────

INSTRUMENT_ACCESSORIES = {
    "Piccolo":                              ["Case", "Cleaning Rod", "Cleaning Cloth"],
    "Flute":                                ["Case", "Cleaning Rod", "Cleaning Cloth"],
    "Flute - Other":                        ["Case", "Cleaning Rod", "Cleaning Cloth"],
    "Oboe":                                 ["Case", "Cleaning Swab"],
    "Bassoon":                              ["Case", "Bocal", "Seat Strap", "Reed Case", "Swab"],
    "Clarinet - Bb":                        ["Case", "Mouthpiece", "Ligature", "Cleaning Swab"],
    "Clarinet - Bb Bass":                   ["Case", "Mouthpiece", "Ligature", "Gooseneck", "Neck Strap", "Cleaning Swab"],
    "Clarinet - Eb Alto":                   ["Case", "Mouthpiece", "Ligature", "Reed(s)", "Barrel", "Cleaning Swab"],
    "Saxophone - Eb Alto":                  ["Case", "Mouthpiece", "Ligature", "Neck Strap", "Gooseneck", "Swab"],
    "Saxophone - Bb Tenor":                 ["Case", "Mouthpiece", "Ligature", "Neck Strap", "Gooseneck", "Swab"],
    "Saxophone - Eb Baritone":              ["Case", "Mouthpiece", "Ligature", "Neck Strap", "Gooseneck", "Swab"],
    "Trumpet - Bb":                         ["Case", "Mouthpiece", "Valve Oil", "Slide Grease"],
    "Trombone":                             ["Case", "Mouthpiece", "Slide Oil"],
    "Trombone - Bass":                      ["Case", "Mouthpiece", "Slide Oil", "Valve Oil"],
    "Trombone - Tenor (w/ F trigger)":      ["Case", "Mouthpiece", "Slide Oil", "Valve Oil"],
    "Baritone":                             ["Case", "Mouthpiece", "Valve Oil", "Slide Grease"],
    "Baritone - 3-valve":                   ["Case", "Mouthpiece", "Valve Oil", "Slide Grease"],
    "Baritone - 4-valve":                   ["Case", "Mouthpiece", "Valve Oil", "Slide Grease"],
    "French Horn - Single in F":            ["Case", "Mouthpiece", "Valve Oil", "Slide Grease"],
    "French Horn - Single in Bb":           ["Case", "Mouthpiece", "Valve Oil", "Slide Grease"],
    "French Horn - Double":                 ["Case", "Mouthpiece", "Valve Oil", "Slide Grease"],
    "Tuba":                                 ["Case", "Mouthpiece", "Valve Oil", "Slide Grease"],
    "Snare Drum - Concert":                 ["Case/Bag", "Sticks/Mallets", "Stand"],
    "Snare Drum - Drum Set":                ["Case/Bag", "Sticks/Mallets", "Stand", "Practice Pad"],
    "Bass Drum - Concert":                  ["Cover", "Mallets", "Stand"],
    "Bass Drum - Kick Drum":                ["Cover", "Pedal", "Mallets"],
    "Tom-Tom - Concert Tom (Single)":       ["Cover", "Mallets"],
    "Tom-Tom - Concert Toms (Set)":         ["Cover", "Mallets"],
    "Tom-Tom - Floor Tom":                  ["Cover", "Mallets"],
    "Tom-Tom - Rack Tom":                   ["Cover", "Mallets"],
    "Miscellaneous Drum - Bongos":          ["Cover/Case", "Sticks/Mallets"],
    "Miscellaneous Drum - Conga (Single)":  ["Cover/Case", "Sticks/Mallets"],
    "Miscellaneous Drum - Djembe":          ["Cover/Case", "Strap"],
    'Timpani - 23"':                        ["Cover", "Mallets", "Foot Pedal"],
    'Timpani - 26"':                        ["Cover", "Mallets", "Foot Pedal"],
    'Timpani - 29"':                        ["Cover", "Mallets", "Foot Pedal"],
    'Timpani - 32"':                        ["Cover", "Mallets", "Foot Pedal"],
    "Glockenspiel/Bells - Bell Kit":        ["Case", "Mallets", "Stand"],
    "Glockenspiel/Bells - Concert":         ["Cover", "Mallets", "Stand"],
    "Marimba - 4.3 Octave":               ["Cover", "Mallets", "Stand"],
    "Xylophone":                            ["Cover", "Mallets", "Stand"],
    "Xylophone - Other":                    ["Cover", "Mallets", "Stand"],
    "Vibraphone":                           ["Cover", "Mallets", "Stand"],
    "Chimes - Concert":                     ["Cover", "Mallets", "Stand"],
    "Auxiliary Percussion - Other":         ["Stick bag", "Yarn mallets", "Rubber/Plastic Mallets", "Timpani Mallets", "Snare Sticks"],
    "Cymbals - Hi-Hat":                     ["Case/Bag", "Stand"],
    "Guitar - Acoustic":                    ["Case", "Strap"],
    "Guitar - Electric":                    ["Case", "Strap", "Cable"],
    "Bass Guitar - Electric":               ["Case", "Strap", "Cable"],
    "Piano":                                ["Bench", "Cover"],
    "Miscellaneous Electronic - Other":     ["Case/Bag", "Power Adapter", "Cable"],
    "Violin":                               ["Case", "Bow", "Shoulder Rest"],
    "Viola":                                ["Case", "Bow", "Shoulder Rest"],
    "Cello":                                ["Case", "Bow"],
    "Bass":                                 ["Case", "Bow"],
    "String Bass":                          ["Case", "Bow"],
}


def _get_accessories(description: str) -> list:
    """Return the accessory list for the given instrument description."""
    if description in INSTRUMENT_ACCESSORIES:
        return INSTRUMENT_ACCESSORIES[description]
    # Prefix fallback: "Trombone" → matches "Trombone - Bass" etc.
    base = description.split(" - ")[0]
    for key, val in INSTRUMENT_ACCESSORIES.items():
        if key.startswith(base + " ") or key == base:
            return val
    return ["Case", "Mouthpiece"]


# ── Style helpers ─────────────────────────────────────────────────────────────

def _ps(name, size=10, bold=False, align=TA_LEFT, leading=None):
    font = "Helvetica-Bold" if bold else "Helvetica"
    return ParagraphStyle(
        name, fontName=font, fontSize=size,
        alignment=align, leading=leading or (size + 2),
        spaceAfter=0, spaceBefore=0,
    )


def _styles():
    return {
        "title":  _ps("title",  size=14, bold=True,  align=TA_CENTER, leading=18),
        "b10":    _ps("b10",    size=10, bold=True),
        "b9":     _ps("b9",     size=9,  bold=True,  leading=11),
        "n10":    _ps("n10",    size=10),
        "n9":     _ps("n9",     size=9,  leading=11),
        "n8":     _ps("n8",     size=8,  leading=10),
        "footer": _ps("footer", size=11, bold=True,  align=TA_CENTER, leading=15),
    }


def _p(text, style):
    return Paragraph(str(text or ""), style)


def _tbl(data, col_widths, underline_cols=(), top_pad=3, bot_pad=2):
    """Single-row Table; LINEBELOW applied to columns listed in underline_cols."""
    tbl = Table([data], colWidths=col_widths)
    cmds = [
        ("VALIGN",        (0, 0), (-1, -1), "BOTTOM"),
        ("TOPPADDING",    (0, 0), (-1, -1), top_pad),
        ("BOTTOMPADDING", (0, 0), (-1, -1), bot_pad),
        ("LEFTPADDING",   (0, 0), (-1, -1), 1),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 1),
    ]
    for c in underline_cols:
        cmds.append(("LINEBELOW", (c, 0), (c, 0), 0.75, colors.black))
    tbl.setStyle(TableStyle(cmds))
    return tbl


# ── Info rows (matching Charms form line by line) ─────────────────────────────

def _row_student(student_name, grade, s):
    # STUDENT'S NAME ___  School Chinook Middle School Band  Grade ___
    cw = [1.3*inch, 1.85*inch, 0.55*inch, 1.95*inch, 0.5*inch, 0.85*inch]
    return _tbl([
        _p("<b>STUDENT'S NAME</b>",   s["b10"]),
        _p(student_name,               s["n10"]),
        _p("<b>School</b>",           s["b10"]),
        _p(SCHOOL_NAME,                s["n10"]),
        _p("<b>Grade</b>",            s["b10"]),
        _p(grade,                      s["n10"]),
    ], cw, underline_cols=(1, 5), top_pad=6)


def _row_address(address, phone, parent, s, parent_style="n10"):
    # Address ___  Phone ___  Parent's Name ___
    cw = [0.65*inch, 1.9*inch, 0.55*inch, 1.25*inch, 1.1*inch, 1.55*inch]
    return _tbl([
        _p("<b>Address</b>",         s["b10"]),
        _p(address,                   s["n8"]),
        _p("<b>Phone</b>",           s["b10"]),
        _p(phone,                     s["n10"]),
        _p("<b>Parent's Name</b>",   s["b10"]),
        _p(parent,                    s[parent_style]),
    ], cw, underline_cols=(1, 3, 5), top_pad=5)


def _row_instrument(description, serial_no, barcode, s):
    # Instrument: ___  Serial # ___  Barcode # ___
    cw = [0.85*inch, 1.9*inch, 0.65*inch, 1.15*inch, 0.75*inch, 1.7*inch]
    return _tbl([
        _p("<b>Instrument:</b>",     s["b10"]),
        _p(description,               s["n10"]),
        _p("<b>Serial #</b>",        s["b10"]),
        _p(serial_no,                 s["n10"]),
        _p("<b>Barcode #</b>",       s["b10"]),
        _p(barcode,                   s["n10"]),
    ], cw, top_pad=5)


def _row_make(brand, condition, est_value, s):
    # Make ___  Condition ___  Replacement Value ___
    cw = [0.5*inch, 1.0*inch, 0.85*inch, 1.25*inch, 1.35*inch, 2.05*inch]
    return _tbl([
        _p("<b>Make</b>",                s["b10"]),
        _p(brand,                         s["n10"]),
        _p("<b>Condition</b>",           s["b10"]),
        _p(condition,                     s["n10"]),
        _p("<b>Replacement Value</b>",   s["b10"]),
        _p(est_value,                     s["n10"]),
    ], cw, top_pad=5)


def _row_describe(s):
    # Describe if not excellent ___
    cw = [1.85*inch, 5.15*inch]
    return _tbl([
        _p("<b>Describe if not excellent</b>", s["b10"]),
        _p("",                                  s["n10"]),
    ], cw, underline_cols=(1,), top_pad=5)


# ── Accessories & Condition table ─────────────────────────────────────────────

def _accessories_table(accessories, s):
    """
    Two-column table: each item name is bold+underlined, followed by
    Excellent / Good / Fair / Poor (plain text for the student to circle).
    """
    mid   = math.ceil(len(accessories) / 2)
    left  = accessories[:mid]
    right = accessories[mid:]
    while len(right) < len(left):
        right.append(None)

    # 11 columns: item | Exc | Good | Fair | Poor | gap | item | Exc | Good | Fair | Poor
    cw = [
        1.45*inch, 0.65*inch, 0.5*inch, 0.4*inch, 0.4*inch,   # left side (5)
        0.15*inch,                                              # gap
        1.45*inch, 0.65*inch, 0.5*inch, 0.4*inch, 0.45*inch,  # right side (5)
    ]  # total = 7.0"

    def item_p(name):
        return _p(f"<u><b>{name}</b></u>", s["b9"]) if name else _p("", s["n9"])

    def cond_p(word, show):
        return _p(word, s["n9"]) if show else _p("", s["n9"])

    rows = []
    for l_item, r_item in zip(left, right):
        show_r = r_item is not None
        rows.append([
            item_p(l_item),
            _p("Excellent", s["n9"]), _p("Good", s["n9"]),
            _p("Fair", s["n9"]),      _p("Poor", s["n9"]),
            _p("", s["n9"]),
            item_p(r_item),
            cond_p("Excellent", show_r), cond_p("Good", show_r),
            cond_p("Fair", show_r),      cond_p("Poor", show_r),
        ])

    tbl = Table(rows, colWidths=cw)
    tbl.setStyle(TableStyle([
        ("TOPPADDING",    (0, 0), (-1, -1), 1),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
        ("LEFTPADDING",   (0, 0), (-1, -1), 1),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 1),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
    ]))
    return tbl


# ── Date / Return / Repair rows ───────────────────────────────────────────────

def _row_date_issued(date_str, s):
    # Date Issued [date]   Instructor's Signature ___
    cw = [0.85*inch, 1.4*inch, 0.45*inch, 1.5*inch, 2.8*inch]
    return _tbl([
        _p("<b>Date Issued</b>",            s["b10"]),
        _p(date_str,                         s["n10"]),
        _p("",                               s["n10"]),
        _p("<b>Instructor's Signature</b>", s["b10"]),
        _p("",                               s["n10"]),
    ], cw, underline_cols=(4,), top_pad=6)


def _row_date_returned(s):
    # Date Returned ___   Instructor's Signature ___
    cw = [1.05*inch, 1.2*inch, 0.45*inch, 1.5*inch, 2.8*inch]
    return _tbl([
        _p("<b>Date Returned</b>",          s["b10"]),
        _p("",                               s["n10"]),
        _p("",                               s["n10"]),
        _p("<b>Instructor's Signature</b>", s["b10"]),
        _p("",                               s["n10"]),
    ], cw, underline_cols=(1, 4), top_pad=6)


def _row_condition_returned(s):
    # Condition Returned ___   Describe if not excellent ___
    cw = [1.3*inch, 1.85*inch, 0.2*inch, 1.85*inch, 1.8*inch]
    return _tbl([
        _p("<b>Condition Returned</b>",        s["b10"]),
        _p("",                                  s["n10"]),
        _p("",                                  s["n10"]),
        _p("<b>Describe if not excellent</b>", s["b10"]),
        _p("",                                  s["n10"]),
    ], cw, underline_cols=(1, 4), top_pad=6)


def _row_repairs(s):
    # Repairs Necessary ___   Yes ___   No ___   Cost ___
    cw = [1.3*inch, 1.3*inch, 0.3*inch,
          0.3*inch, 0.5*inch,
          0.3*inch, 0.5*inch,
          0.5*inch, 2.0*inch]
    return _tbl([
        _p("<b>Repairs Necessary</b>", s["b10"]),
        _p("",                          s["n10"]),
        _p("",                          s["n10"]),
        _p("<b>Yes</b>",               s["b10"]),
        _p("",                          s["n10"]),
        _p("<b>No</b>",                s["b10"]),
        _p("",                          s["n10"]),
        _p("<b>Cost</b>",              s["b10"]),
        _p("",                          s["n10"]),
    ], cw, underline_cols=(1, 4, 6, 8), top_pad=6)


# ── Signature lines ───────────────────────────────────────────────────────────

def _sig_line(label, s):
    cw = [1.4*inch, 5.6*inch]
    return _tbl([
        _p(f"<b>{label}</b>", s["b10"]),
        _p("",                 s["n10"]),
    ], cw, underline_cols=(1,), top_pad=16, bot_pad=2)


# ── Main entry points ─────────────────────────────────────────────────────────

def generate_loan_form(checkout_data: dict, instrument_data: dict, output_path: str) -> str:
    """
    Generate a Bellevue School District Equipment Loan Form PDF matching
    the Charms single-page layout.

    checkout_data keys: student_name, grade, address, city, state, zip_code,
                        phone, parent1_name, date_assigned
    instrument_data keys: description, serial_no, barcode, brand, condition,
                          est_value
    """
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    doc = SimpleDocTemplate(
        output_path,
        pagesize=letter,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
        topMargin=0.55 * inch,
        bottomMargin=0.5 * inch,
    )

    s = _styles()
    story = []

    # ── Unpack data ───────────────────────────────────────────────────────
    student_name = str(checkout_data.get("student_name") or "")
    grade        = str(checkout_data.get("grade")        or "")
    address      = str(checkout_data.get("address")      or "")
    city         = str(checkout_data.get("city")         or "")
    state_       = str(checkout_data.get("state")        or "")
    zip_code     = str(checkout_data.get("zip_code")     or "")
    phone        = str(checkout_data.get("phone")        or "")
    parent1      = str(checkout_data.get("parent1_name") or "")
    parent2      = str(checkout_data.get("parent2_name") or "")
    if parent1 and parent2:
        parent        = f"{parent1}<br/>{parent2}"
        parent_style  = "n8"
    else:
        parent        = parent1 or parent2
        parent_style  = "n10"
    date_raw     = checkout_data.get("date_assigned") or datetime.today().strftime("%Y-%m-%d")

    description  = str(instrument_data.get("description") or "")
    serial_no    = str(instrument_data.get("serial_no")   or "")
    barcode      = str(instrument_data.get("barcode")     or "")
    brand        = str(instrument_data.get("brand")       or "")
    condition    = str(instrument_data.get("condition")   or "")
    est_val_raw  = instrument_data.get("est_value")

    # Two-line address: street on first line, city/state/zip on second
    city_state_zip = ", ".join(filter(None, [city, state_, zip_code]))
    if address and city_state_zip:
        full_address = f"{address}<br/>{city_state_zip}"
    else:
        full_address = address or city_state_zip

    # Date: M/D/YYYY with no leading zeros (matches Charms style)
    try:
        dt = datetime.strptime(str(date_raw), "%Y-%m-%d")
        date_display = f"{dt.month}/{dt.day}/{dt.year}"
    except (ValueError, TypeError):
        date_display = str(date_raw)

    # Replacement value
    try:
        fval = float(est_val_raw or 0)
        est_value = f"${fval:,.2f}" if fval > 0 else ""
    except (ValueError, TypeError):
        est_value = str(est_val_raw or "")

    accessories = _get_accessories(description)

    # ── Title ─────────────────────────────────────────────────────────────
    story.append(_p(f"{DISTRICT_NAME} Equipment Loan Form", s["title"]))
    story.append(Spacer(1, 4))
    story.append(HRFlowable(width="100%", thickness=1.5, color=colors.black))
    story.append(Spacer(1, 4))

    # ── Student / Instrument Info ──────────────────────────────────────────
    story.append(_row_student(student_name, grade, s))
    story.append(_row_address(full_address, phone, parent, s, parent_style))
    story.append(_row_instrument(description, serial_no, barcode, s))
    story.append(_row_make(brand, condition, est_value, s))
    story.append(_row_describe(s))
    story.append(Spacer(1, 8))

    # ── Accessories & Condition ────────────────────────────────────────────
    story.append(_p("<u><b>Accessories &amp; Condition</b></u> (circle)", s["n10"]))
    story.append(Spacer(1, 3))
    story.append(_accessories_table(accessories, s))
    story.append(Spacer(1, 7))

    # ── Date / Return / Repair Fields ─────────────────────────────────────
    story.append(_row_date_issued(date_display, s))
    story.append(_row_date_returned(s))
    story.append(_row_condition_returned(s))
    story.append(_row_repairs(s))
    story.append(Spacer(1, 8))

    # ── To Students and Parents ────────────────────────────────────────────
    story.append(_p("<u><b>To Students and Parents:</b></u>", s["b10"]))
    story.append(Spacer(1, 2))
    story.append(_p(
        f"Besides the maintenance fee, of <u><b>{MAINT_YEAR} for the school year and "
        f"{MAINT_SUMMER} for Summer</b></u> use, no charge will be made for the loan of "
        f"school district instruments provided the following conditions are met:",
        s["n9"]
    ))
    story.append(Spacer(1, 1))

    terms = [
        "We expect normal wear, but we also expect that the instrument will be returned "
        "in as good a condition as it was when you checked it out.",
        "<u>Any repairs necessary due to accident or misuse are you and your parents' "
        "responsibility.</u>",
        "Should you leave Bellevue, you must return the instrument to your music instructor.",
        "You may keep the instrument out over the summer provided you make arrangements "
        "with your instructor.",
    ]
    for i, t in enumerate(terms, 1):
        story.append(_p(f"{i}. {t}", s["n9"]))

    story.append(Spacer(1, 4))

    # ── Insurance Information ──────────────────────────────────────────────
    story.append(_p("<u><b>Insurance Information</b></u>", s["b10"]))
    story.append(Spacer(1, 2))
    story.append(_p(
        "When the instrument is stored in a school building and it is damaged by fire, "
        "the school district insurance will cover its loss or damage. There is no school "
        "district insurance in effect to cover losses due to damage by accidents, "
        "mistreatment, and loss by theft. It is you and your parents' responsibility.",
        s["n9"]
    ))
    story.append(Spacer(1, 8))

    # ── Signatures ────────────────────────────────────────────────────────
    story.append(_sig_line("Student's Signature", s))
    story.append(Spacer(1, 6))
    story.append(_sig_line("Parent's Signature", s))
    story.append(Spacer(1, 10))

    # ── Footer ────────────────────────────────────────────────────────────
    footer_tbl = Table(
        [[_p(
            f"<b>Make Checks Payable to Your School</b><br/>"
            f"{MAINT_YEAR} School Year - {MAINT_SUMMER} Summer",
            s["footer"]
        )]],
        colWidths=[CW]
    )
    footer_tbl.setStyle(TableStyle([
        ("BOX",           (0, 0), (-1, -1), 1.5, colors.black),
        ("TOPPADDING",    (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(footer_tbl)

    doc.build(story)
    return output_path


def generate_form_for_checkout(db, checkout_id: int, base_dir: str) -> str:
    """
    Look up checkout + instrument data and generate the PDF.
    Returns the path to the generated PDF.
    """
    with db._connect() as conn:
        checkout = conn.execute(
            """SELECT c.*, s.grade, s.address, s.city, s.state, s.zip_code,
                      s.phone, s.parent1_name, s.parent2_name
               FROM checkouts c
               LEFT JOIN students s ON s.id = c.student_id
               WHERE c.id=?""",
            (checkout_id,)
        ).fetchone()
        if not checkout:
            raise ValueError(f"Checkout {checkout_id} not found")

        instrument = conn.execute(
            "SELECT * FROM instruments WHERE id=?",
            (checkout["instrument_id"],)
        ).fetchone()

    safe_name = "".join(
        c for c in (checkout["student_name"] or "unknown")
        if c.isalnum() or c in (" ", "_", "-")
    ).strip().replace(" ", "_")
    date_str  = datetime.today().strftime("%Y%m%d")
    filename  = f"{safe_name}_{date_str}.pdf"
    out_dir   = os.path.join(base_dir, "checkout_forms")
    out_path  = os.path.join(out_dir, filename)

    return generate_loan_form(dict(checkout), dict(instrument), out_path)
