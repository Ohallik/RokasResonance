"""
field_trip_tools.py - Pure logic for the Field Trips planner (no UI).

Roster resolution (groups minus opt-outs), the cost / cost-per-student
calculator, chaperone math (1 adult per 10 students), parent contact
autofill, and the three reminder emails (families, chaperones, teachers).
"""

import math
from datetime import datetime, timedelta

from concert_tools import fmt_date, parse_date, _member_of, _display_name

TRAVEL_METHODS = ["School Bus", "Charter Bus", "Private Vehicles", "Walking",
                  "Public Transit", "Other"]

FUNDING_CURRICULAR = "curricular"          # building / department
FUNDING_EXTRACURRICULAR = "extracurricular"  # ASB / boosters

STUDENTS_PER_CHAPERONE = 10

TRIP_STAGES = [("2 weeks", 14), ("1 week", 7)]
AUDIENCES = ["families", "chaperones", "teachers"]

# ── Trip checklist ────────────────────────────────────────────────────────────
# Tri-state per item: 0 = to do, 1 = done, 2 = N/A (doesn't apply to this
# trip — e.g. no bus request for a walking trip).  "Staff emailed" isn't a
# stored item: it derives from the teachers reminder tracking.
CHECK_TODO, CHECK_DONE, CHECK_NA = 0, 1, 2

CHECKLIST_ITEMS = [
    ("approved", "Field trip form"),
    ("bus_requested", "Bus request"),
    ("sub_assigned", "Sub request"),
    ("registration_done", "Registration / payment"),
    ("finalforms_done", "FinalForms group created"),
    ("nurse_check", "Nurse check completed"),
]


def checklist_summary(trip, staff_emailed=None):
    """(done, applicable, missing_labels) across the checklist — N/A items
    don't count either way.  Pass staff_emailed (bool) to include the
    derived 'Staff emailed' item."""
    done, applicable, missing = 0, 0, []
    for key, label in CHECKLIST_ITEMS:
        state = int(trip.get(key) or 0)
        if state == CHECK_NA:
            continue
        applicable += 1
        if state == CHECK_DONE:
            done += 1
        else:
            missing.append(label)
    if staff_emailed is not None:
        applicable += 1
        if staff_emailed:
            done += 1
        else:
            missing.append("Staff emailed")
    return done, applicable, missing


# What carries over when copying a previous year's trip into a new one:
# the what/where/how, costs (edit as prices change), notes, and the saved
# email templates — NOT dates, roster choices, approvals, chaperones, or
# reminder history.
TEMPLATE_FIELDS = ["name", "groups_list", "destination", "travel_method",
                   "depart_time", "return_time", "entry_fee",
                   "transport_cost", "food_cost", "sub_cost", "other_cost",
                   "funding", "covered", "notes",
                   "email_families", "email_chaperones", "email_teachers"]


def trip_template(trip):
    return {k: trip.get(k) for k in TEMPLATE_FIELDS}


def groups_list(trip):
    return [g.strip() for g in (trip.get("groups_list") or "").split(",")
            if g.strip()]


def roster(students, trip, excluded_ids):
    """Students attending: members of any listed group, minus opt-outs."""
    groups = groups_list(trip)
    out = []
    for s in students:
        if s.get("id") in excluded_ids:
            continue
        if any(_member_of(s, g) for g in groups):
            out.append(s)
    return out


def eligible(students, trip):
    """Everyone in the listed groups (including opt-outs) — the roster the
    attendance checklist is built from."""
    groups = groups_list(trip)
    return [s for s in students if any(_member_of(s, g) for g in groups)]


def chaperones_needed(n_students):
    """1 adult per 10 students, beyond the teacher (30 students -> 3)."""
    if n_students <= 0:
        return 0
    return math.ceil(n_students / STUDENTS_PER_CHAPERONE)


def _money(value):
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def trip_costs(trip, n_students):
    """Return a dict with the cost breakdown.

    EVERY cost field is a one-time trip TOTAL — including entry_fee, which is
    the per-ensemble festival registration the school pays once (e.g. $350
    for the BHS Jazz Festival), NOT a per-student amount.

    per_student is the flip side: the charge each attending student would
    pay (income) to cover the school's total expenses.  If the trip is
    marked 'covered' (building/ASB/boosters pay), that charge is zero."""
    entry = _money(trip.get("entry_fee"))
    transport = _money(trip.get("transport_cost"))
    food = _money(trip.get("food_cost"))
    sub = _money(trip.get("sub_cost"))
    other = _money(trip.get("other_cost"))
    total = entry + transport + food + sub + other
    if trip.get("covered"):
        per_student = 0.0
    else:
        per_student = (total / n_students) if n_students else 0.0
    return {
        "entry": entry,
        "transport": transport, "food": food, "sub": sub, "other": other,
        "total": round(total, 2),
        "per_student": round(per_student, 2),
        "income": round(per_student * n_students, 2),
    }


import re as _re


_NAME_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}


def _name_tokens(name):
    """Lowercased first-to-last name words.

    Handles the ways names actually appear: district exports store parents
    as 'Last, First' ('Blair, Bryan' == chaperone sign-up 'Bryan Blair'),
    plus parenthesised nicknames, middle initials ('Juan M.'), and
    generational suffixes — all normalized away."""
    raw = (name or "").strip()
    if "," in raw:                       # 'Last, First [Middle]' -> reorder
        last_part, first_part = raw.split(",", 1)
        raw = f"{first_part} {last_part}"
    clean = _re.sub(r"\([^)]*\)", " ", raw.lower())
    toks = [t for t in _re.split(r"[^a-z\-']+", clean) if t]
    return [t for t in toks
            if t not in _NAME_SUFFIXES and len(t) > 1]


def find_parent_contact(students, name, prefer=None):
    """Autofill a chaperone's phone/email from the parents/guardians of
    registered students.

    Token-based matching so district-form names line up with what's in the
    database: last names must agree and every word of the shorter name must
    appear in the longer one — 'Juan Manuel Hernandez' matches the stored
    parent 'Juan Hernandez'.  ``prefer`` (e.g. the students attending this
    trip) is searched first, then the full student list."""
    want = _name_tokens(name)
    if len(want) < 2:
        return None

    def matches(pname):
        have = _name_tokens(pname)
        if len(have) < 2 or have[-1] != want[-1]:
            return False
        shorter, longer = (have, want) if len(have) <= len(want) else (want, have)
        return all(t in longer for t in shorter)

    pools = []
    if prefer:
        pools.append(prefer)
    pools.append(students)
    for pool in pools:
        for s in pool:
            for i in ("1", "2"):
                pname = (s.get(f"parent{i}_name") or "").strip()
                if pname and matches(pname):
                    return {
                        "name": pname,
                        "phone": (s.get(f"parent{i}_phone") or "").strip(),
                        "email": (s.get(f"parent{i}_email") or "").strip(),
                        "student": f"{(s.get('first_name') or '').strip()} "
                                   f"{(s.get('last_name') or '').strip()}".strip(),
                    }
    return None


# ── Reminder schedule ─────────────────────────────────────────────────────────

def stage_key(audience, label):
    return f"{audience}-{label}"


def trip_schedule(depart_date):
    """[(label, due_date or None), ...] for the 2-week / 1-week cadence."""
    d = parse_date(depart_date)
    return [(label, (d - timedelta(days=days)) if d else None)
            for label, days in TRIP_STAGES]


def stages_due(depart_date, sent_keys, today=None):
    """[(audience, label)] for every reminder whose date has arrived."""
    d = parse_date(depart_date)
    if not d:
        return []
    today = today or datetime.today().date()
    if today > d:
        return []
    due = []
    for audience in AUDIENCES:
        for label, days in TRIP_STAGES:
            if stage_key(audience, label) in sent_keys:
                continue
            if today >= d - timedelta(days=days):
                due.append((audience, label))
    return due


# ── Emails ────────────────────────────────────────────────────────────────────

def _when_lines(trip):
    out = []
    when = fmt_date(trip.get("depart_date"))
    dt = (trip.get("depart_time") or "").strip()
    out.append(f"  • Departing: {when}" + (f", {dt}" if dt else ""))
    rw = fmt_date(trip.get("return_date")) if trip.get("return_date") else when
    rt = (trip.get("return_time") or "").strip()
    out.append(f"  • Returning: {rw}" + (f", {rt}" if rt else ""))
    if trip.get("destination"):
        out.append(f"  • Destination: {trip['destination']}")
    if trip.get("travel_method"):
        out.append(f"  • Travel: {trip['travel_method']}")
    return out


def family_email(trip, per_student, stage_label, teacher_name="", school_name=""):
    """(subject, body) reminder to students/parents."""
    name = (trip.get("name") or "Field trip").strip()
    lead = ("is coming up in about two weeks" if stage_label == "2 weeks"
            else "is only a week away")
    subject = f"Reminder: {name} ({fmt_date(trip.get('depart_date'))})"
    lines = ["Good morning,", "",
             f"This is a friendly reminder that the {name} field trip {lead}!",
             ""]
    lines += _when_lines(trip)
    if per_student and not trip.get("covered"):
        lines.append(f"  • Cost per student: ${per_student:,.2f}")
    groups = groups_list(trip)
    if groups:
        lines.append(f"  • Who's going: {', '.join(groups)}")
    lines += [
        "",
        "Please make sure permission slips and any payments are turned in, "
        "and reach out with any questions.",
        "",
        teacher_name or "Your music teacher",
    ]
    if school_name:
        lines.append(school_name)
    return subject, "\n".join(lines)


def chaperone_email(trip, stage_label, teacher_name="", school_name=""):
    """(subject, body) reminder to signed-up parent chaperones."""
    name = (trip.get("name") or "Field trip").strip()
    lead = ("is about two weeks away" if stage_label == "2 weeks"
            else "is only a week away")
    subject = (f"Chaperone reminder: {name} "
               f"({fmt_date(trip.get('depart_date'))})")
    dt = (trip.get("depart_time") or "").strip()
    lines = ["Hello,", "",
             f"Thank you again for volunteering to chaperone! The {name} trip "
             f"{lead}.", ""]
    lines += _when_lines(trip)
    if dt:
        lines.append(f"  • Please arrive 15 minutes before departure ({dt}).")
    lines += [
        "",
        "If you haven't completed the district volunteer clearance yet, "
        "please do so before the trip. Reply to this email with any "
        "questions. We couldn't do this without you!",
        "",
        teacher_name or "Your music teacher",
    ]
    if school_name:
        lines.append(school_name)
    return subject, "\n".join(lines)


def teacher_email(trip, attending, stage_label, teacher_name=""):
    """(subject, body) heads-up to teachers, admin, and the attendance
    office: the student list (Last, First — sorted, with student ID and
    grade), times, and the missed-work note."""
    name = (trip.get("name") or "Field trip").strip()
    when = fmt_date(trip.get("depart_date"))
    lead = ("in about two weeks" if stage_label == "2 weeks"
            else "next week")
    subject = f"Heads up: {name} field trip {lead} ({when})"
    dt = (trip.get("depart_time") or "").strip()
    rt = (trip.get("return_time") or "").strip()
    lines = ["Hi teachers, admin, and attendance,", "",
             f"A quick heads-up that the following students will be on the "
             f"{name} field trip on {when}"
             + (f", leaving at {dt}" if dt else "")
             + (f" and returning around {rt}" if rt else "") + ".",
             "",
             "Students have been told to be in communication with their "
             "teachers about any missed work. Please let me know if anyone "
             "isn't holding up their end.", "",
             f"Students attending ({len(attending)}):"]

    def sort_key(s):
        return ((s.get("last_name") or "").lower(),
                (s.get("first_name") or "").lower())

    for s in sorted(attending, key=sort_key):
        last = (s.get("last_name") or "").strip()
        first = ((s.get("preferred_name") or "").strip()
                 or (s.get("first_name") or "").strip())
        entry = f"  {last}, {first}"
        bits = []
        grade = str(s.get("grade") or "").strip()
        if grade:
            bits.append(f"Grade {grade}")
        sid = str(s.get("student_id") or "").strip()
        if sid:
            bits.append(f"ID {sid}")
        if bits:
            entry += f"  ({', '.join(bits)})"
        lines.append(entry)
    lines += ["", "Thank you!", "", teacher_name or "Your music teacher"]
    return subject, "\n".join(lines)


def family_addresses(attending):
    """De-duplicated parent emails for the attending students."""
    seen, out = set(), []
    for s in attending:
        for key in ("parent1_email", "parent2_email"):
            addr = (s.get(key) or "").strip()
            if addr and "@" in addr and addr.lower() not in seen:
                seen.add(addr.lower())
                out.append(addr)
    return out
