"""
concert_tools.py - Pure logic for the Concerts planner (no UI).

Covers: score-order personnel sorting for programs, the reminder schedule
(2 weeks / 1 week / 2 days), and the plain-text builders used for the
details page and reminder emails.  Kept UI-free so it can be tested headless.
"""

import re
from datetime import datetime, timedelta


# ── Score order ───────────────────────────────────────────────────────────────
# Concert groups: strings first, then high→low woodwinds, high→low brass,
# then percussion.  Jazz groups: same wind order, but the rhythm section
# (drums, vibes, piano, bass, guitar) closes the list — including string bass.

_WIND_ORDER = [
    "Piccolo", "Flute", "Oboe", "English Horn", "Bassoon",
    "Clarinet", "Alto Clarinet", "Bass Clarinet",
    "Alto Sax", "Tenor Sax", "Bari Sax",
    "Trumpet", "Horn", "Trombone", "Baritone", "Euphonium", "Tuba",
]
_STRING_ORDER = [
    "Violin", "Violin 1", "Violin 2", "Viola", "Viola 1", "Viola 2",
    "Cello", "Cello 1", "Cello 2", "String Bass", "Harp",
]
_VOICE_ORDER = ["Soprano", "Alto", "Tenor", "Baritone Voice", "Bass Voice"]

CONCERT_ORDER = (_STRING_ORDER + _WIND_ORDER + ["Piano", "Guitar", "Percussion"]
                 + _VOICE_ORDER)
JAZZ_ORDER = (_WIND_ORDER
              + ["Percussion", "Drums", "Vibraphone", "Piano",
                 "Bass", "String Bass", "Guitar", "Voice"])

# Normalize stored instrument names to program section labels.  Mrs. Mangum's
# preference: plain "Horn", and clef variants fold into one section.
SECTION_NAMES = {
    "French Horn": "Horn",
    "Baritone BC": "Baritone", "Baritone TC": "Baritone",
    "Euphonium BC": "Euphonium", "Euphonium TC": "Euphonium",
    "Baritone/Euphonium": "Baritone",
    "Alto Saxophone": "Alto Sax", "Tenor Saxophone": "Tenor Sax",
    "Baritone Saxophone": "Bari Sax",
    "Electric Bass": "Bass", "Drum Set": "Drums",
}


def section_for(instrument: str) -> str:
    inst = (instrument or "").strip()
    return SECTION_NAMES.get(inst, inst) if inst else "Other"


def is_jazz(ensemble: str) -> bool:
    return "jazz" in (ensemble or "").lower()


def _order_index(section: str, jazz: bool) -> int:
    order = JAZZ_ORDER if jazz else CONCERT_ORDER
    try:
        return order.index(section)
    except ValueError:
        return len(order)          # unknown instruments sink to the end


def _member_of(student, ensemble: str) -> bool:
    groups = [e.strip().lower() for e in (student.get("ensembles") or "").split(",")]
    return (ensemble or "").strip().lower() in groups


def _display_name(student) -> str:
    """Preferred name wins; otherwise the first word of the first name so
    middle names/initials never print ('Khoi Nguyen' → 'Khoi')."""
    pref = (student.get("preferred_name") or "").strip()
    if pref:
        first = pref
    else:
        raw = (student.get("first_name") or "").strip()
        first = raw.split()[0] if raw else ""
    last = (student.get("last_name") or "").strip()
    return f"{first} {last}".strip()


def personnel_sections(students, ensemble: str):
    """Group an ensemble's members into program sections in score order.

    students: main-DB student rows (dicts).  Returns a list of
    (section_label, [ {name, honors, all_state} ]) tuples; members are
    alphabetical by last name within each section.
    """
    jazz = is_jazz(ensemble)
    members = [s for s in students if _member_of(s, ensemble)]
    by_section = {}
    for s in members:
        inst = s.get("primary_instrument")
        if jazz and (s.get("jazz_instrument") or "").strip():
            # Some students play something entirely different in jazz band
            # (a Horn player on Guitar) — the jazz instrument wins there.
            inst = s["jazz_instrument"]
        sec = section_for(inst)
        by_section.setdefault(sec, []).append({
            "name": _display_name(s),
            "last": (s.get("last_name") or "").lower(),
            "honors": bool(s.get("honors")),
            "all_state": bool(s.get("all_state")),
        })
    out = []
    for sec in sorted(by_section, key=lambda x: (_order_index(x, jazz), x)):
        names = sorted(by_section[sec], key=lambda m: (m["last"], m["name"]))
        for m in names:
            m.pop("last", None)
        out.append((sec, names))
    return out


def mark_name(member) -> str:
    """'♪ Name' for Honors, '★ Name' for Jr. All-State (★♪ if both)."""
    prefix = ""
    if member.get("all_state"):
        prefix += "★"
    if member.get("honors"):
        prefix += "♪"
    return f"{prefix} {member['name']}".strip()


def marks_legend(sections_by_ensemble) -> str:
    """Legend line for whichever marks actually appear in the program."""
    any_honors = any_state = False
    for sections in sections_by_ensemble.values():
        for _, members in sections:
            for m in members:
                any_honors = any_honors or m.get("honors")
                any_state = any_state or m.get("all_state")
    bits = []
    if any_honors:
        bits.append("♪ = Honors in Band")
    if any_state:
        bits.append("★ = Jr. All-State")
    return "     ".join(bits)


# ── Personnel print layout ────────────────────────────────────────────────────
# Splits rosters into print columns for the program: single-spaced within a
# section, a blank line between sections, sections kept whole so no one ends
# up alone at the top of a column, and each ensemble starts a fresh column.

def personnel_columns(personnel, cap=48):
    """personnel: {ensemble: [(section, members), ...]} (insertion-ordered).

    Returns (columns, owners): columns = list of [(text, style)] with style in
    'ens' | 'sec' | 'name' | 'gap'; owners[i] = the ensemble in column i.
    An 'ens' title counts double toward the cap (bigger font).  A section
    that can't fit whole moves to the next column; only sections taller than
    a full column are split, always carrying at least two names and getting
    a '(… cont'd)' header."""
    columns, owners, cur = [], [], []
    cur_owner = None

    def h(lines):
        return sum(2 if st == "ens" else 1 for _, st in lines)

    def close():
        nonlocal cur
        if cur:
            columns.append(cur)
            owners.append(cur_owner)
            cur = []

    for ens, sections in personnel.items():
        close()
        cur_owner = ens
        cur.append((ens, "ens"))
        for sec, members in sections:
            names = [(mark_name(m), "name") for m in members]
            block = [(sec, "sec")] + names
            gap = [] if (not cur or cur[-1][1] == "ens") else [("", "gap")]
            if h(cur) + len(gap) + len(block) <= cap:
                cur.extend(gap + block)
                continue
            room = cap - h(cur) - len(gap)
            if len(block) <= cap and (room < 4 or len(block) - room < 3):
                # keep the section whole in a fresh column
                close()
                cur.extend(block)
                continue
            # taller than a column (or splits cleanly): split, min 3 lines
            # placed and min 3 carried so nobody sits alone
            take = max(3, min(room, len(block) - 3))
            cur.extend(gap + block[:take])
            rest = block[take:]
            while rest:
                close()
                cur.append((f"({sec} cont’d)", "sec"))
                fit = min(len(rest), cap - 1)
                cur.extend(rest[:fit])
                rest = rest[fit:]
    close()
    return columns, owners


def paginate_columns(columns, owners, per_page=3):
    """Group columns into pages of per_page, keeping each ensemble's whole
    run of columns on one page whenever it can fit on one (so an ensemble
    never needlessly bleeds onto a second page)."""
    pages, page = [], []
    i = 0
    while i < len(columns):
        span = 1
        while i + span < len(columns) and owners[i + span] == owners[i]:
            span += 1
        if page and len(page) + span > per_page and span <= per_page:
            pages.append(page)
            page = []
        for k in range(span):
            page.append(columns[i + k])
            if len(page) == per_page:
                pages.append(page)
                page = []
        i += span
    if page:
        pages.append(page)
    return pages


# ── Dates & reminder schedule ─────────────────────────────────────────────────

REMINDER_STAGES = [("2 weeks", 14), ("1 week", 7), ("2 days", 2)]

# ── Tri-state prep checklist (same convention as field trips) ─────────────────
# 0 = ☐ to do, 1 = ☑ done, 2 = N/A (doesn't apply to this concert).

CHECK_TODO, CHECK_DONE, CHECK_NA = 0, 1, 2

CONCERT_CHECKLIST_ITEMS = [
    ("venue_reserved", "Venue / gym reserved"),
    ("tutorials_scheduled", "Tutorials scheduled"),
    ("repertoire_final", "Repertoire finalized"),
    ("details_sent", "Details page sent home"),
    ("program_printed", "Program printed"),
    ("setup_ready", "Set-up plan / volunteers"),
]

# What carries over when a past concert is reused as a template: the whole
# recurring shape of the event, but not its date, tutorial dates, private
# notes, or checklist progress.
CONCERT_TEMPLATE_FIELDS = [
    "title", "location", "offsite", "ensembles", "perf_order",
    "start_time", "end_time", "attire", "bring", "arrival", "setup",
    "seated_by", "itinerary", "directors", "special_guests",
    "acknowledgements", "extra_info",
]


def concert_template(concert):
    """A seed dict for a new concert copied from an earlier one."""
    return {k: concert.get(k) for k in CONCERT_TEMPLATE_FIELDS
            if concert.get(k) not in (None, "")}


def parse_date(date_str: str):
    try:
        return datetime.strptime((date_str or "").strip()[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def fmt_date(date_str: str) -> str:
    """'2026-06-03' → 'Wednesday, June 3, 2026'."""
    d = parse_date(date_str)
    if not d:
        return date_str or ""
    return f"{d.strftime('%A')}, {d.strftime('%B')} {d.day}, {d.year}"


def days_until(date_str: str, today=None):
    d = parse_date(date_str)
    if not d:
        return None
    today = today or datetime.today().date()
    return (d - today).days


def reminder_schedule(date_str: str):
    """[(stage_label, due_date or None), ...] for the standard cadence."""
    d = parse_date(date_str)
    return [(label, (d - timedelta(days=days)) if d else None)
            for label, days in REMINDER_STAGES]


def stages_due(date_str: str, sent_stages, today=None):
    """Reminder stages whose send date has arrived but aren't marked sent
    (and the concert hasn't happened yet)."""
    d = parse_date(date_str)
    if not d:
        return []
    today = today or datetime.today().date()
    if today > d:
        return []
    due = []
    for label, days in REMINDER_STAGES:
        if label in sent_stages:
            continue
        if today >= d - timedelta(days=days):
            due.append(label)
    return due


# ── Staff / facilities email (office, custodians, PE, admin) ─────────────────
# One email, 2 weeks before each home concert week, covering custodial needs,
# set-up, doors, and the 5th grade performance. Skipping it in June 2026
# showed: everyone had to ask for those details individually.

STAFF_STAGE_KEY = "staff-2 weeks"


def staff_due(date_str, sent_stages, today=None):
    """True when the staff/facilities email should have gone out but hasn't
    (2 weeks before, and the concert hasn't happened yet)."""
    d = parse_date(date_str)
    if not d:
        return False
    today = today or datetime.today().date()
    if today > d:
        return False
    if STAFF_STAGE_KEY in sent_stages:
        return False
    return today >= d - timedelta(days=14)


def staff_email(concert, school_name=""):
    """(subject, body) skeleton for the staff/facilities email, modeled on
    the teacher's real December and March versions: one block per event in
    the concert week. The band block is pre-filled from the planner; the
    orchestra, choir, and 5th grade blocks get added by hand."""
    d = parse_date(concert.get("concert_date"))
    month = d.strftime("%B") if d else "concert"
    title = (concert.get("title") or "Concert").strip()
    when = fmt_date(concert.get("concert_date")) or "(date)"
    location = (concert.get("location") or "(location)").strip()
    start = (concert.get("start_time") or "7:00pm").strip()
    arrival = (concert.get("arrival") or "(arrival window)").strip()
    setup = (concert.get("setup") or "(set-up time and plan)").strip()
    subject = (f"{month} concert week: custodial, set-up, and schedule "
               f"details ({when})")
    body = "\n".join([
        "Hi all,",
        "",
        f"Here are the details for our {month} concert week. As always, we "
        "will do our best to not disrupt anyone else more than absolutely "
        "necessary. Please ask if you see any issues or have any questions.",
        "",
        f"{when} = {title}",
        f"Location: {location}",
        "Custodial needs = ALL bleachers (large and small) pulled out by "
        "(time)",
        f"Set up plan = {setup}",
        f"Doors open at (time), kids arrive {arrival}",
        f"Start time {start}",
        "Tear down = immediately after performance",
        "",
        "(Add a block like the one above for each of the other concerts the "
        "same week: orchestra, choir, and the 5th grade performance if "
        "there is one. Note any attendance impacts for the office, for "
        "example which periods the Advanced students will be out. Delete "
        "this note before sending.)",
        "",
        "PE staff, thank you as always for letting us borrow your space. "
        "Please let us know if there are any issues or questions.",
        "",
        "Thanks everyone!",
    ])
    return subject, body


# ── Text builders ─────────────────────────────────────────────────────────────

# Why the tutorials are non-negotiable — printed wherever rehearsals appear.
TUTORIAL_BLURB = ("These tutorials are our only opportunity to work together "
                  "as a full ensemble before public performance, which is why "
                  "they are graded and required.")

# Home-concert months (Dec/Mar/Jun) require two tutorials for Entry Band and
# two for Intermediate Band; this skeleton is auto-filled so it can't be
# forgotten — the teacher just replaces the TBDs with real dates.
TUTORIAL_TEMPLATE = ("Entry Band tutorial #1 (date TBD)\n"
                     "Entry Band tutorial #2 (date TBD)\n"
                     "Intermediate Band tutorial #1 (date TBD)\n"
                     "Intermediate Band tutorial #2 (date TBD)")
TUTORIAL_MONTHS = {12, 3, 6}


def needs_tutorial_template(concert_date, ensembles_text) -> bool:
    """Dec/Mar/Jun home concerts involving Entry or Intermediate Band."""
    d = parse_date(concert_date)
    if not d or d.month not in TUTORIAL_MONTHS:
        return False
    ens = (ensembles_text or "").lower()
    return "entry" in ens or "intermediate" in ens


def _lines(text):
    return [ln.strip() for ln in (text or "").splitlines() if ln.strip()]


def _time_range(concert) -> str:
    start = (concert.get("start_time") or "").strip()
    end = (concert.get("end_time") or "").strip()
    if start and end:
        return f"{start}-{end}"     # plain hyphen, matching the teacher's style
    return start or end


def ensembles_list(concert):
    return [e.strip() for e in (concert.get("ensembles") or "").split(",") if e.strip()]


def upcoming_lines(all_concerts, for_concert):
    """Auto-build 'Upcoming Performances' from every planned concert AFTER
    this one — so a June program can never list December's concert.  Format
    matches the printed programs: 'June 3, 6:30pm — June Band Concert'."""
    this_date = parse_date(for_concert.get("concert_date"))
    this_id = for_concert.get("id")
    out = []
    for c in all_concerts:
        if this_id is not None and c.get("id") == this_id:
            continue
        d = parse_date(c.get("concert_date"))
        if not d or (this_date and d <= this_date):
            continue
        # "June 3, 6:30pm June Band Concert" like the printed programs
        line = f"{d.strftime('%B')} {d.day}"
        start = (c.get("start_time") or "").strip()
        if start:
            line += f", {start}"
        line += f" {(c.get('title') or '').strip()}"
        if c.get("offsite") and (c.get("location") or "").strip():
            line += f" @ {c['location'].strip()}"
        out.append((d, line))
    return [line for _, line in sorted(out, key=lambda x: x[0])]


def merged_upcoming(all_concerts, for_concert):
    """Auto lines from the planner + any manual extras typed on the concert
    (de-duplicated).  Past events can never appear in the auto part."""
    auto = upcoming_lines(all_concerts, for_concert)
    manual = [ln for ln in _lines(for_concert.get("upcoming"))
              if ln not in auto]
    return auto + manual


def merged_acknowledgements(year_text, concert_text):
    """The standing year-wide list plus this concert's extras (paras, student
    teachers, section coaches…), de-duplicated, order preserved."""
    out, seen = [], set()
    for ln in _lines(year_text) + _lines(concert_text):
        key = ln.lower()
        if key not in seen:
            seen.add(key)
            out.append(ln)
    return out


# Starting point for the year-wide acknowledgements — every program should
# credit the school leadership, the other music teachers, the parent org,
# the district booster, and the families.
YEAR_ACK_TEMPLATE = """\
(Principal name), principal
(Vice principal name), vice principal
(Choir director name), choir director
(Orchestra director name), orchestra director
(School) Custodial Staff
(School) PTSA
Bellevue Schools Foundation
And especially…
All Band Parents and Families!"""


def details_text(concert, pieces=None) -> str:
    """The details page as clean plain text — pasteable into an email or doc.

    Itinerary/rehearsal lines are stored one per line; an itinerary line may
    use 'time | activity' to line up nicely."""
    out = []
    title = (concert.get("title") or "Concert").strip()
    out.append(title.upper())
    when = fmt_date(concert.get("concert_date"))
    tr = _time_range(concert)
    out.append(f"{when}, {tr}" if tr else when)
    if concert.get("location"):
        out.append(f"Location: {concert['location']}")
    if (concert.get("setup") or "").strip():
        out.append(f"Set-up: {concert['setup'].strip()}")
    if (concert.get("arrival") or "").strip():
        out.append(f"Student arrival: {concert['arrival'].strip()}")
    if (concert.get("seated_by") or "").strip():
        out.append(f"Everyone seated in the venue by: {concert['seated_by'].strip()}")
    out.append("")

    if concert.get("attire"):
        out.append("WHAT TO WEAR:")
        out += [f"  • {ln}" for ln in _lines(concert["attire"])]
        out.append("")
    if concert.get("bring"):
        out.append("WHAT TO BRING:")
        out += [f"  • {ln}" for ln in _lines(concert["bring"])]
        out.append("")
    if concert.get("rehearsals"):
        out.append("REQUIRED TUTORIALS / REHEARSALS:")
        out.append("  " + TUTORIAL_BLURB)
        out += [f"  • {ln}" for ln in _lines(concert["rehearsals"])]
        out.append("")
    if concert.get("itinerary"):
        out.append("THE PLAN:")
        for ln in _lines(concert["itinerary"]):
            if "|" in ln:
                t, act = ln.split("|", 1)
                out.append(f"  {t.strip():<16} {act.strip()}")
            else:
                out.append(f"  {ln}")
        out.append("")
    if concert.get("perf_order"):
        out.append(f"Performance order: {concert['perf_order'].strip()}")
        out.append("")
    if concert.get("notes"):
        out += _lines(concert["notes"])
    return "\n".join(out).rstrip() + "\n"


def reminder_email(concert, stage_label: str, teacher_name: str = "",
                   school_name: str = ""):
    """(subject, body) for one reminder stage.  Body is a simple bulleted
    list that survives every email client."""
    title = (concert.get("title") or "Concert").strip()
    when = fmt_date(concert.get("concert_date"))
    tr = _time_range(concert)

    if stage_label == "2 days":
        lead = "is almost here, just a couple of days away"
    elif stage_label == "1 week":
        lead = "is one week away"
    else:
        lead = "is two weeks away"

    subject = f"Reminder: {title} ({when})"
    lines = [
        "Good morning,", "",
        f"This is a friendly reminder that the {title} {lead}!", "",
        f"  • When: {when}" + (f", {tr}" if tr else ""),
    ]
    if concert.get("location"):
        lines.append(f"  • Where: {concert['location']}")
    arrival = (concert.get("arrival") or "").strip()
    if arrival:
        lines.append(f"  • Student arrival: {arrival}")
    seated = (concert.get("seated_by") or "").strip()
    if seated:
        lines.append(f"  • Everyone seated in the venue by: {seated}")
    if concert.get("attire"):
        lines.append("  • What to wear: " + "; ".join(_lines(concert["attire"])))
    if concert.get("bring"):
        lines.append("  • What to bring: " + "; ".join(_lines(concert["bring"])))
    if concert.get("rehearsals"):
        lines.append("  • Required rehearsals: " + "; ".join(_lines(concert["rehearsals"])))
    ens = ensembles_list(concert)
    if ens:
        lines.append(f"  • Performing groups: {', '.join(ens)}")
    lines += [
        "",
        "All family and friends are welcome and encouraged to attend. Every "
        "student has worked hard and deserves an audience!",
        "",
        "Please reach out with any questions.",
        "",
    ]
    sig = teacher_name or "Your music teacher"
    if school_name:
        sig += f"\n{school_name}"
    lines.append(sig)
    return subject, "\n".join(lines)


def parent_addresses(students, ensembles):
    """De-duplicated parent email addresses for members of these ensembles."""
    seen, out = set(), []
    for s in students:
        if not any(_member_of(s, e) for e in ensembles):
            continue
        for key in ("parent1_email", "parent2_email"):
            addr = (s.get(key) or "").strip()
            if addr and "@" in addr and addr.lower() not in seen:
                seen.add(addr.lower())
                out.append(addr)
    return out
