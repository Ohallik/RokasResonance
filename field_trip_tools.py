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

# 2320P does not set a ratio -- both applications only ask "how many adults
# will provide supervision".  One per ten is Roka's own suggestion, not a
# district rule, and is presented that way.
STUDENTS_PER_CHAPERONE = 10

# ── Trip type ────────────────────────────────────────────────────────────────
# BSD runs two entirely separate procedures, with different forms, a different
# approval path, and lead times that differ by a factor of four.  International
# is a third; it is rare enough that it is deliberately not modeled, and a
# teacher planning one is told to work from the district packet.

# The three substitute rates the district form offers as a "check one".  Kept
# as data because they are stamped with a school year on the form itself and
# change: the amount stays editable, this only decides which box is ticked.
SUB_RATES = [
    ("4hr", "$212/4 hrs", 212.0),
    ("5hr", "$266/5 hrs", 266.0),
    ("day", "$354/full day", 354.0),
]
SUB_RATE_NOTE = "24-25 Rates adjusted to consider taxes/benefits"
SUB_RATE_AMOUNT = {k: a for k, _l, a in SUB_RATES}
SUB_RATE_LABEL = {k: l for k, l, _a in SUB_RATES}

TRIP_DAY = "day"
TRIP_OVERNIGHT = "overnight"

TRIP_TYPES = [
    (TRIP_DAY, "Day trip",
     "During the school day or after it, returning the same day."),
    (TRIP_OVERNIGHT, "Overnight or out of state",
     "Needs school BOARD approval, and the clock starts months earlier."),
]

TRIP_TYPE_LABEL = {k: lbl for k, lbl, _ in TRIP_TYPES}


def trip_type(trip):
    """The procedure this trip follows.  An overnight trip is one that returns
    on a later day than it left, so a trip that grew an extra night is not
    quietly left on the day-trip timeline."""
    t = (trip.get("trip_type") or "").strip().lower()
    if t in (TRIP_DAY, TRIP_OVERNIGHT):
        return t
    dep = (trip.get("depart_date") or "").strip()
    ret = (trip.get("return_date") or "").strip()
    if dep and ret and ret > dep:
        return TRIP_OVERNIGHT
    return TRIP_DAY


# ── The forms, per procedure ─────────────────────────────────────────────────
# Per-STUDENT forms are the ones a teacher chases sixty families for; the trip
# cannot leave without them.  Trip-level paperwork stays on the checklist.
#
# FinalForms covers a middle or high school DAY trip -- the office builds the
# participant group and the paper permission slip stopped being collected years
# ago.  It does not cover elementary, which both procedures say plainly ("For
# High School and Middle School trips, use FinalForms"), and it does not cover
# an overnight trip, where Exhibit C must come back signed per student.

FORM_EXHIBIT_A = "exhibit_a"
FORM_EXHIBIT_C = "exhibit_c"
FORM_EXHIBIT_E = "exhibit_e"
FORM_MEDICATION = "medication"

FORM_LABELS = {
    FORM_EXHIBIT_A: "Exhibit A — parent authorization",
    FORM_EXHIBIT_C: "Exhibit C — parent authorization and risk",
    # Retired, and kept only so a tick recorded against one before they were
    # retired still has a name to display.  Neither is chased any more:
    #   Exhibit E   -- the overnight emergency health form, now entirely
    #                  covered by FinalForms.
    #   3416P       -- the medication authorisation, which is no longer even
    #                  published on the district website.
    FORM_EXHIBIT_E: "Exhibit E — emergency health (retired)",
    FORM_MEDICATION: "3416P — medication authorization (retired)",
}

# Named for what they are.  "Exhibit C" is what the district calls its own
# filing cabinet; a column heading has to say what the teacher is chasing.
FORM_SHORT = {
    FORM_EXHIBIT_A: "Parent Authorization",
    FORM_EXHIBIT_C: "Parent Authorization",
    FORM_EXHIBIT_E: "Emergency Health",
    FORM_MEDICATION: "Medication",
}

# The form that decides whether a child may get on the bus at all.
FORM_GATES_ATTENDANCE = {FORM_EXHIBIT_A, FORM_EXHIBIT_C}


def trip_is_elementary(main_db, trip, fallback=False):
    """Whether THIS trip is a 5th grade trip.

    Read off the groups going, not off the teacher's profile.  A teacher can
    hold a middle school and six elementaries at once, and her program type
    says nothing about which of them is on the bus: a day trip for Advanced
    Band was being told to collect Exhibit A from all 48 students, on paper,
    because the PROFILE said elementary.

    An elementary group carries its school's name ("Jing Mei Elementary
    School: Section 1"), so the groups answer it.  ``fallback`` is used only
    when the trip has no groups yet and there is nothing to read.
    """
    # An explicit answer beats a clever one.  Inference off the groups is a
    # good default and a bad certainty: a trip whose roster has not been
    # imported yet has nothing to infer from, and the teacher knows.
    said = trip.get("elementary")
    if said is not None and str(said).strip() != "":
        return bool(int(said))
    groups = groups_list(trip)
    if not groups:
        return fallback
    try:
        sites = [dict(x) for x in main_db.get_sites(level="elementary")]
    except Exception:
        return fallback
    if not sites:
        # No elementary schools on file, so the groups cannot answer it.  A
        # teacher whose whole programme is 5th grade but who has not added
        # their schools yet still gets the elementary rules.
        return fallback
    from ui.ensembles import site_groups
    for site in sites:
        try:
            labels = site_groups(main_db, site, None)
        except Exception:
            labels = []
        for label in labels:
            if any(_member_of({"ensembles": g}, label) or g == label
                   for g in groups):
                return True
    return False


def required_forms(trip, elementary=False):
    """The per-student forms this trip has to collect on paper.

    Empty for a middle or high school day trip: FinalForms replaced those, and
    listing them anyway would have teachers ticking boxes for paperwork nobody
    collects.
    """
    # What is genuinely still collected on paper, checked against the district
    # forms themselves rather than against the procedure's list of them:
    #
    #   Exhibit C   overnight and out-of-state, from every student.  "Without
    #               this form, a student cannot attend the trip."  Its third
    #               page is a notary block, which the form itself says applies
    #               to international trips only -- not to a basic overnight.
    #   Exhibit A   elementary day trips.  Both procedures put elementary
    #               outside FinalForms in as many words.
    #
    # Not collected, and deliberately not listed:
    #   Exhibit E   covered by FinalForms.
    #   3416P       no longer published by the district at all.
    if trip_type(trip) == TRIP_OVERNIGHT:
        return [FORM_EXHIBIT_C]
    if elementary:
        return [FORM_EXHIBIT_A]
    return []


# ── The teacher's own tick columns ───────────────────────────────────────────
# The district's forms are not the only per-student thing a trip chases.  An
# overnight trip usually starts with an interest survey, then a deposit, then a
# code of conduct -- none of which 2320P has ever heard of, and all of which
# are the same job: a list of names and who has done it.  Rather than guess at
# that list, the teacher writes their own columns.

CUSTOM_PREFIX = "custom:"


def custom_forms(trip):
    """[(key, label)] of the teacher's own columns for this trip."""
    import json
    raw = (trip.get("custom_forms") or "").strip()
    if not raw:
        return []
    try:
        items = json.loads(raw)
    except Exception:
        return []
    out = []
    for it in items if isinstance(items, list) else []:
        if not isinstance(it, dict):
            continue
        key = str(it.get("key") or "").strip()
        label = str(it.get("label") or "").strip()
        if key and label:
            out.append((key, label))
    return out


def _custom_json(items):
    import json
    return json.dumps([{"key": k, "label": l} for k, l in items])


def add_custom_form(trip, label):
    """Add a column.  Returns (json, key), or (json, None) if the label is
    already there -- two columns with the same name would be two lists of the
    same thing, which is how a tally stops being trusted."""
    label = (label or "").strip()
    items = custom_forms(trip)
    if not label:
        return _custom_json(items), None
    if any(l.lower() == label.lower() for _k, l in items):
        return _custom_json(items), None
    n = 1
    used = {k for k, _l in items}
    while f"{CUSTOM_PREFIX}{n}" in used:
        n += 1
    key = f"{CUSTOM_PREFIX}{n}"
    items.append((key, label))
    return _custom_json(items), key


def remove_custom_form(trip, key):
    return _custom_json([(k, l) for k, l in custom_forms(trip) if k != key])


def form_columns(trip, elementary=False):
    """Every per-student column this trip tracks: the district's, then the
    teacher's own, in the order they were added."""
    out = [(f, FORM_SHORT[f]) for f in required_forms(trip, elementary)]
    return out + custom_forms(trip)


def form_label(trip, key):
    """The full name of one column, district or custom."""
    if key in FORM_LABELS:
        return FORM_LABELS[key]
    for k, label in custom_forms(trip):
        if k == key:
            return label
    return key


def uses_finalforms(trip, elementary=False):
    """Whether the FinalForms participant group is this trip's permission
    record.  MS/HS day trips only."""
    return trip_type(trip) == TRIP_DAY and not elementary


# ── Deadlines ────────────────────────────────────────────────────────────────
# Everything 2320P asks for is counted in SCHOOL weeks, and for an overnight
# trip most of it counts back from the school BOARD MEETING rather than from
# the trip.  A June overnight trip has its packet moving in February.
#
# Note a conflict in the district's own overnight document: the numbered steps
# say the packet reaches the principal "at minimum 4 school weeks prior to the
# date needed for board approval", while the TIMELINES table on page 5 says 5.
# The stricter one is used.

DEADLINES_DAY = [
    ("nurse_notify", 4, "trip", "Tell the school nurse",
     "Notify the nurse and office manager. If a nurse or para has to come, "
     "that is a conversation with a building administrator and an extra cost."),
    ("application", 2, "trip", "Application to the principal",
     "The application is not complete until you have seen the Office Manager "
     "about a sub."),
    ("nurse_roster", 2, "trip", "Roster and medical info to the nurse",
     "Who is going, and anything they need. Health plans and medications "
     "travel with the student."),
]

DEADLINES_OVERNIGHT = [
    ("nurse_notify", 8, "trip", "Tell the school nurse",
     "Eight school weeks, and before board approval. The Special Education "
     "Supervisor for Health Services is notified too."),
    ("application", 5, "board", "Packet to the principal",
     "Five school weeks before the board meeting. The district's own steps "
     "say four; the timeline table says five, so this uses five."),
    ("athletics", 3, "board", "Packet to Athletics & Activities",
     "The principal's office sends it to Jessica Dowling. Ask for a read "
     "receipt: that is your proof it arrived."),
    ("nurse_roster", 6, "trip", "Roster, medical and bus info to the nurse",
     "Six school weeks before the trip."),
    ("health_forms", 6, "trip", "Exhibit E and medication forms from students",
     "From every student, not only the ones who take medication."),
]


def deadlines(trip, cal=None, today=None):
    """Every district deadline for this trip, soonest first.

    Each is {key, label, detail, weeks, due (date|None), anchor, overdue,
    school_weeks_left}.  ``due`` is None when the date it counts back from has
    not been set -- an overnight trip with no board meeting date cannot have
    its approval deadlines worked out, and saying so is more use than guessing.
    """
    import school_calendar as sc

    kind = trip_type(trip)
    rules = DEADLINES_OVERNIGHT if kind == TRIP_OVERNIGHT else DEADLINES_DAY
    trip_d = parse_date(trip.get("depart_date"))
    board_d = parse_date(trip.get("board_date"))
    today = today or datetime.today().date()

    out = []
    for key, weeks, anchor, label, detail in rules:
        anchor_date = board_d if anchor == "board" else trip_d
        due = None
        if anchor_date and cal:
            due = sc.school_weeks_before(cal, anchor_date, weeks)
        elif anchor_date:
            due = anchor_date - timedelta(days=weeks * 7)
        left = None
        if due and cal:
            left = sc.school_weeks_between(cal, today, due)
        out.append({
            "key": key, "label": label, "detail": detail, "weeks": weeks,
            "anchor": anchor, "due": due,
            "overdue": bool(due and due < today),
            "school_weeks_left": left,
        })
    out.sort(key=lambda x: (x["due"] is None, x["due"] or today))
    return out


def board_meeting_options(school_year, trip=None):
    """The board meetings Roka knows about, each with whether a trip aiming at
    it could still be approved in time.

    Returns [{date, label, packet_due, reachable, before_trip}] soonest first.
    ``reachable`` is False once the five-school-week packet deadline has passed
    -- the meeting is still real, it is just no longer a meeting this trip can
    make, and saying which ones are gone is the point of showing the list.
    """
    import school_calendar as sc

    today = datetime.today().date()
    trip_d = parse_date((trip or {}).get("depart_date"))
    weeks = dict((k, w) for k, w, a, _l, _d in DEADLINES_OVERNIGHT
                 if a == "board").get("application", 5)
    out = []
    for when, label in sc.board_meetings():
        # Count the packet deadline back through the calendar the DEADLINE
        # falls in, not the trip's: five school weeks before an early-September
        # meeting lands in the previous school year.
        cal = (sc.get_calendar(school_year_of(when))
               or sc.get_calendar(school_year))
        due = sc.school_weeks_before(cal, when, weeks) if cal else \
            when - timedelta(days=weeks * 7)
        out.append({
            "date": when, "label": label, "packet_due": due,
            "reachable": bool(due and due >= today),
            "before_trip": bool(trip_d and when < trip_d),
        })
    return out


def school_year_of(d):
    """The school year a date falls in ("2026-2027"), July to June."""
    if not d:
        return None
    start = d.year if d.month >= 7 else d.year - 1
    return f"{start}-{start + 1}"


def usable_board_meetings(school_year, trip):
    """The meetings worth offering for this trip: still in reach, and before
    the trip itself.  A list of every meeting the board will ever hold is not
    a choice, it is a haystack."""
    opts = board_meeting_options(school_year, trip)
    trip_d = parse_date((trip or {}).get("depart_date"))
    out = [o for o in opts if o["reachable"]]
    if trip_d:
        out = [o for o in out if o["date"] < trip_d]
    return out


def board_meeting_advice(school_year, trip):
    """One sentence about the board meeting for this trip, or "" when there is
    nothing worth saying."""
    import school_calendar as sc

    opts = board_meeting_options(school_year, trip)
    if not opts:
        return ("Roka has no school board meeting dates for this year. Add "
                "them and it can work out every approval deadline for you; "
                "until then, type the meeting date yourself. "
                + sc.BOARD_MEETINGS_URL)
    usable = usable_board_meetings(school_year, trip)
    if not usable:
        return ("None of the board meetings Roka knows about are still in "
                "reach for this trip. Check the district's list for a later "
                "one: " + sc.BOARD_MEETINGS_URL)
    first = usable[0]
    return (f"{len(usable)} meeting(s) still in reach. The soonest is "
            f"{fmt_date(first['date'].isoformat())}, with the packet to the "
            f"principal by {fmt_date(first['packet_due'].isoformat())}. A "
            f"later meeting is fine, so long as the trip still has room after "
            f"it for payments and forms.")


def blackout_warning(depart_date, school_year=None):
    """Why this date is one 2320P asks teachers to avoid, plus what could not
    be checked.  Returns (reasons, unchecked) -- both lists, both possibly
    empty.  Checked when the date is typed, because the point is to catch it
    before the packet is written, not after."""
    import school_calendar as sc

    d = parse_date(depart_date)
    if not d:
        return [], []
    year = school_year or f"{d.year if d.month >= 7 else d.year - 1}-" \
                          f"{d.year + 1 if d.month >= 7 else d.year}"
    cal = sc.get_calendar(year)
    if not cal:
        return [], []
    return sc.blackout_reasons(cal, d), sc.unchecked_windows(cal)

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
    # Overnight only -- see checklist_for().
    ("board_approved", "School board approval"),
    # 2320P, overnight, "Transportation".  The district calls it a "carrier
    # profile", which tells a teacher nothing: it is the state's safety record
    # for the bus company, printed off and stapled to the packet.  Named for
    # the job, not for the jargon.  Only asked of a charter company -- a
    # district bus has nothing to attach.
    ("carrier_profile", "Bus company's safety record attached"),
    # 2320P, overnight, "Financial Plan": ASB minutes go with any trip on an
    # ASB org key, and the amount approved has to match the application.
    ("asb_minutes", "ASB minutes attached"),
]

# Which items apply to which procedure.  An item that does not apply is not
# shown at all rather than shown and marked N/A: six schools' worth of "N/A"
# is noise, and a checklist people scroll past is not a checklist.
_DAY_ONLY = {"finalforms_done"}
_OVERNIGHT_ONLY = {"board_approved", "carrier_profile", "asb_minutes"}


def uses_charter(trip):
    """Whether this trip is on a hired coach, as opposed to a district bus,
    private cars or walking."""
    return "charter" in (trip.get("travel_method") or "").lower()


def uses_asb_money(trip):
    """Whether ASB money is paying, which is what pulls the ASB minutes in."""
    if (trip.get("funding") or "") == FUNDING_EXTRACURRICULAR:
        return True
    return "asb" in (trip.get("budget_code") or "").lower()


def checklist_for(trip, elementary=False):
    """The checklist items this trip actually has.

    An item that cannot apply is not shown at all rather than shown and left
    at N/A: a charter carrier profile means nothing on a district bus, and a
    list of things to ignore is a list people stop reading.
    """
    overnight = trip_type(trip) == TRIP_OVERNIGHT
    out = []
    for key, label in CHECKLIST_ITEMS:
        if key in _OVERNIGHT_ONLY and not overnight:
            continue
        if key in _DAY_ONLY and (overnight or elementary):
            continue
        if key == "carrier_profile" and not uses_charter(trip):
            continue
        if key == "asb_minutes" and not uses_asb_money(trip):
            continue
        out.append((key, label))
    return out


def checklist_summary(trip, staff_emailed=None, elementary=False):
    """(done, applicable, missing_labels) across the checklist — N/A items
    don't count either way.  Pass staff_emailed (bool) to include the
    derived 'Staff emailed' item."""
    done, applicable, missing = 0, 0, []
    for key, label in checklist_for(trip, elementary):
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
# What a new trip inherits when an old one is reused as its template.  Not the
# dates, roster, approvals or chaperones -- those are this year's.  Everything
# else, including every answer on the district application: the objective, the
# activities, the alternate assignments and the affordability answer are the
# same words year after year, and retyping them is the tax the paperwork
# charges for running the trip again.
TEMPLATE_FIELDS = ["name", "groups_list", "destination", "travel_method",
                   "depart_time", "return_time", "entry_fee",
                   "transport_cost", "food_cost", "sub_cost", "sub_rate",
                   "other_cost", "funding", "covered", "notes",
                   "email_families", "email_chaperones", "email_teachers",
                   # the district application
                   "trip_type", "budget_code", "educational_objective",
                   "supervision", "activities", "assignments", "missed_work",
                   "affordability", "health_review", "custom_forms",
                   "elementary",
                   # overnight only
                   "advisor_phone", "dest_address", "arrive_dest_time",
                   "depart_dest_time", "itinerary"]


def trip_template(trip):
    return {k: trip.get(k) for k in TEMPLATE_FIELDS}


def effective_return_date(trip):
    """The date the trip gets back.

    A day trip returns the day it left, and saying so beats a dash: on the
    district form a blank Return Date is a question left unanswered, and on
    screen it reads as though somebody forgot.  Trips saved before Roka filled
    this in automatically still have it empty, so it is worked out on the way
    out rather than trusted from the record.
    """
    back = (trip.get("return_date") or "").strip()
    if back:
        return back
    if trip_type(trip) == TRIP_DAY:
        return (trip.get("depart_date") or "").strip()
    return ""


def when_line(date_str, time_str):
    """"Tuesday, March 9, 2027, 8:45am" -- one comma between the date and the
    time, rather than a gap wide enough to read as two separate answers."""
    when = fmt_date(date_str) or ""
    at = (time_str or "").strip()
    if when and at:
        return f"{when}, {at}"
    return when or at


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
    """A cost as a number.  A box holding "TBD" or "N/A" counts as nothing
    towards the total -- the form says what is missing beside it."""
    try:
        return float(str(value).replace("$", "").replace(",", "").strip() or 0)
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
             # The names used to be typed out here, one line each.  At 48
             # students that is a wall of text nobody scrolls through and
             # nobody can sort, and a teacher looking for their own period has
             # to read all of it.  A spreadsheet is the right shape for a list
             # of names, so the email points at one.
             f"The full list of the {len(attending)} student(s) attending is "
             f"attached as a spreadsheet, with grade and student ID.",
             "",
             "Thank you!", "", teacher_name or "Your music teacher"]
    return subject, "\n".join(lines)


def attending_rows(attending):
    """The attending students as spreadsheet rows, sorted the way a register
    is: surname first."""
    def sort_key(s):
        return ((s.get("last_name") or "").lower(),
                (s.get("first_name") or "").lower())

    rows = []
    for s in sorted(attending, key=sort_key):
        first = ((s.get("preferred_name") or "").strip()
                 or (s.get("first_name") or "").strip())
        rows.append({
            "last_name": (s.get("last_name") or "").strip(),
            "first_name": first,
            "grade": str(s.get("grade") or "").strip(),
            "student_id": str(s.get("student_id") or "").strip(),
            "ensembles": (s.get("ensembles") or "").strip(),
        })
    return rows


def family_addresses(attending):
    """De-duplicated family addresses for the attending students.

    Guardians and the student. A trip is the student's day out; they should
    get the departure time as directly as their parents do.
    """
    seen, out = set(), []
    for s in attending:
        for key in ("parent1_email", "parent2_email", "student_email"):
            addr = (s.get(key) or "").strip()
            if addr and "@" in addr and addr.lower() not in seen:
                seen.add(addr.lower())
                out.append(addr)
    return out
