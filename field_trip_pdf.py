"""
field_trip_pdf.py - The BSD field trip application, filled in from the planner.

Two forms, because BSD runs two procedures:

  * "Day Field Trip Application" (2320P), for a trip that returns the same day.
  * "Out of State, Overnight or International Field Trip Planning" (2320P),
    which goes to the school board.

The layout follows the district's own forms closely enough that an office
manager can read it without hunting, but it is deliberately NOT a facsimile:
it says at the foot which form it corresponds to and that signatures are still
wet-ink.  A printout that pretended to be the official PDF would be a forgery
risk for no gain -- the district wants its own form, and what a teacher is
short of is the ANSWERS, which are all sitting in the planner already.

Blank lines are left blank rather than filled with "(none)": a blank on a form
is a question still to answer, and inventing text for it hides that.
"""

import os
from datetime import datetime

from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Table, TableStyle,
                                Spacer, KeepTogether)

import field_trip_tools as ft
from concert_tools import fmt_date

CW = 7.0 * inch
_GREY = colors.HexColor("#444444")
_RULE = colors.HexColor("#999999")


def _styles():
    return {
        "title": ParagraphStyle("title", fontName="Helvetica-Bold", fontSize=15,
                                alignment=TA_CENTER, leading=18),
        "sub": ParagraphStyle("sub", fontName="Helvetica-Bold", fontSize=9.5,
                              alignment=TA_CENTER, leading=12,
                              textColor=_GREY),
        "lbl": ParagraphStyle("lbl", fontName="Helvetica-Bold", fontSize=8.5,
                              leading=11),
        "val": ParagraphStyle("val", fontName="Helvetica", fontSize=9,
                              leading=12),
        "q": ParagraphStyle("q", fontName="Helvetica-Bold", fontSize=9,
                            leading=12, spaceBefore=6),
        "a": ParagraphStyle("a", fontName="Helvetica", fontSize=9, leading=13,
                            leftIndent=8, spaceAfter=4),
        "foot": ParagraphStyle("foot", fontName="Helvetica-Oblique", fontSize=7.5,
                               leading=10, textColor=_GREY, alignment=TA_LEFT),
    }


def _money(v):
    try:
        return f"${float(v or 0):,.2f}"
    except (TypeError, ValueError):
        return ""


def _pairs(rows, s):
    """A two-column label/value grid, the way the district form is laid out."""
    data = []
    for left, right in rows:
        data.append([
            Paragraph(left[0], s["lbl"]), Paragraph(left[1] or "", s["val"]),
            Paragraph(right[0] if right else "", s["lbl"]),
            Paragraph(right[1] or "" if right else "", s["val"]),
        ])
    t = Table(data, colWidths=[1.45 * inch, 2.05 * inch, 1.45 * inch, 2.05 * inch])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LINEBELOW", (1, 0), (1, -1), 0.4, _RULE),
        ("LINEBELOW", (3, 0), (3, -1), 0.4, _RULE),
    ]))
    return t


def _costs_table(trip, per_student, s):
    rows = [
        ["Entry fee / participation:", _money(trip.get("entry_fee"))],
        ["Transportation:", _money(trip.get("transport_cost"))],
        ["Substitute teacher:", (trip.get("sub_rate") or "")
         + ("   " + _money(trip.get("sub_cost")) if trip.get("sub_cost") else "")],
        ["Food:", _money(trip.get("food_cost"))],
        ["Other:", _money(trip.get("other_cost"))],
    ]
    total = 0.0
    for key in ("entry_fee", "transport_cost", "sub_cost", "food_cost",
                "other_cost"):
        try:
            total += float(trip.get(key) or 0)
        except (TypeError, ValueError):
            pass
    data = [[Paragraph(a, s["lbl"]), Paragraph(b, s["val"])] for a, b in rows]
    data.append([Paragraph("<b>Total Trip Cost:</b>", s["lbl"]),
                 Paragraph(f"<b>{_money(total)}</b>", s["val"])])
    t = Table(data, colWidths=[2.2 * inch, 4.8 * inch])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("GRID", (0, 0), (-1, -1), 0.4, _RULE),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#F0F0F0")),
    ]))
    return t, total


_QUESTIONS = [
    ("activities", "Describe activities planned while on the trip:"),
    ("assignments", "What required assignments will participants have to "
                    "complete related to this activity? What alternate "
                    "assignments will be available to students who miss the "
                    "activity?"),
    ("missed_work", "What arrangements have been made for students to "
                    "complete work missed in other classes?"),
    ("__adults", "How many adults will provide supervision?"),
    ("affordability", "What considerations have been made for students who "
                      "cannot afford the cost of the trip?"),
    ("health_review", "Have you reviewed student health needs and discussed "
                      "with School Nurse?"),
]


def build_application(trip, path, students=0, chaperones=0, teacher_name="",
                      school_name="", overnight=None):
    """Write the filled application to ``path`` and return it.

    ``overnight`` overrides the trip's own type, for the rare case of printing
    the other form deliberately.
    """
    s = _styles()
    is_overnight = (ft.trip_type(trip) == ft.TRIP_OVERNIGHT
                    if overnight is None else bool(overnight))
    doc = SimpleDocTemplate(path, pagesize=letter,
                            leftMargin=0.75 * inch, rightMargin=0.75 * inch,
                            topMargin=0.6 * inch, bottomMargin=0.6 * inch,
                            title=trip.get("name") or "Field Trip Application")
    flow = []

    flow.append(Paragraph("Bellevue School District", s["sub"]))
    flow.append(Paragraph(
        "Out of State or Overnight Field Trip Planning" if is_overnight
        else "Day Field Trip Application", s["title"]))
    flow.append(Paragraph(
        "(Not for field trips scheduled during the school day)"
        if is_overnight else
        "For School Day or Outside of School Hours. "
        "(Not for Out of State, Overnight or International Field Trips)",
        s["sub"]))
    flow.append(Spacer(1, 10))

    when_req = trip.get("date_of_request") or datetime.today().strftime("%Y-%m-%d")
    n_students = students or ""
    per = ""
    if students:
        total = 0.0
        for key in ("entry_fee", "transport_cost", "sub_cost", "food_cost",
                    "other_cost"):
            try:
                total += float(trip.get(key) or 0)
            except (TypeError, ValueError):
                pass
        per = "$0.00 (covered)" if trip.get("covered") else _money(total / students)

    rows = [
        (("Date of Request:", fmt_date(when_req) or when_req),
         ("Teacher / Advisor:", teacher_name)),
        (("Class or Group:", trip.get("groups_list")),
         ("Number of Students:", str(n_students))),
        (("Departure Date:", fmt_date(trip.get("depart_date"))),
         ("Return Date:", fmt_date(trip.get("return_date")))),
        (("Departure Time:", trip.get("depart_time")),
         ("Return Time:", trip.get("return_time"))),
    ]
    if is_overnight:
        rows += [
            (("Arrive at Destination:", trip.get("arrive_dest_time")),
             ("Depart Destination:", trip.get("depart_dest_time"))),
            (("Advisor Cell Phone:", trip.get("advisor_phone")),
             ("Number of Chaperones:", str(chaperones or ""))),
        ]
    rows += [
        (("Method of Travel:", trip.get("travel_method")),
         ("Charge to Budget Code:", trip.get("budget_code"))),
        (("Anticipated Cost / Student:", per),
         ("Dept. Chair's Signature:", "")),
    ]
    flow.append(_pairs(rows, s))
    flow.append(Spacer(1, 8))

    dest_rows = [(("Trip Destination:", trip.get("destination")), None)]
    if is_overnight:
        dest_rows.append((("Destination Address / Contact:",
                           trip.get("dest_address")), None))
    dest_rows.append((("Educational Objective:",
                       trip.get("educational_objective")), None))
    flow.append(_pairs(dest_rows, s))
    flow.append(Spacer(1, 10))

    flow.append(Paragraph("Trip Costs", s["q"]))
    tbl, _total = _costs_table(trip, per, s)
    flow.append(tbl)
    flow.append(Spacer(1, 4))
    flow.append(Paragraph(
        "Substitute rates are set by the district and change yearly; the rate "
        "chosen above is the one recorded in Roka.", s["foot"]))
    flow.append(Spacer(1, 8))

    for key, question in _QUESTIONS:
        if key == "__adults":
            answer = ""
            if chaperones:
                answer = f"{chaperones} chaperone(s)"
                if teacher_name:
                    answer += f", plus {teacher_name}"
                if is_overnight:
                    answer += ". Non-BSD personnel VIBES cleared: ____"
        else:
            answer = (trip.get(key) or "").strip()
        flow.append(KeepTogether([
            Paragraph(question, s["q"]),
            Paragraph(answer.replace("\n", "<br/>") if answer
                      else "&nbsp;<br/>&nbsp;", s["a"]),
        ]))

    if is_overnight and (trip.get("itinerary") or "").strip():
        flow.append(Paragraph("Itinerary:", s["q"]))
        flow.append(Paragraph(trip["itinerary"].replace("\n", "<br/>"), s["a"]))

    flow.append(Spacer(1, 14))
    sig = Table([[Paragraph("☐ Trip Approved<br/>☐ Trip Denied", s["val"]),
                  Paragraph("<br/>_______________________________<br/>"
                            "<font size=7>Administrator's Signature</font>",
                            s["val"]),
                  Paragraph("<br/>_____________________<br/>"
                            "<font size=7>Date</font>", s["val"])]],
                colWidths=[2.0 * inch, 3.2 * inch, 1.8 * inch])
    sig.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    flow.append(sig)

    flow.append(Spacer(1, 12))
    flow.append(Paragraph(
        "Prepared in Roka's Resonance from the trip planner"
        + (f" for {school_name}" if school_name else "")
        + ". This is a working copy of the answers, not the district's form: "
        "submit on the current BSD "
        + ("Out of State or Overnight Field Trip Application (2320P Exhibit B)"
           if is_overnight else "Day Field Trip Application (2320P)")
        + ", which is the version your principal signs. Check the district "
        "site for the current revision before submitting.", s["foot"]))

    doc.build(flow)
    return path


def suggested_filename(trip, overnight=None):
    is_overnight = (ft.trip_type(trip) == ft.TRIP_OVERNIGHT
                    if overnight is None else bool(overnight))
    name = "".join(c for c in (trip.get("name") or "Field Trip")
                   if c.isalnum() or c in " -_").strip() or "Field Trip"
    kind = "Overnight" if is_overnight else "Day"
    when = (trip.get("depart_date") or datetime.today().strftime("%Y-%m-%d"))
    return f"{name} - {kind} Field Trip Application - {when}.pdf"
