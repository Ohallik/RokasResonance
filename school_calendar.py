"""
school_calendar.py - District no-school days, so the agenda skips holidays.

For SECONDARY (grades 1-12) students only — board meetings, teacher-training
days that are still school days, and elementary-only conference days are NOT
counted here.  Verified against the red per-month school-day counts on the
Bellevue School District 2026-2027 academic calendar (every month matches).

Kept as plain data, keyed by school year, so other years/districts can be added
later without touching the agenda code.
"""

from datetime import date, timedelta


def _dates(*specs):
    """Expand single dates and (start, end) ranges into a set of WEEKDAY dates
    (weekends aren't school days anyway, so they're dropped)."""
    out = set()
    for s in specs:
        if isinstance(s, tuple):
            a, b = s
            d = a
            while d <= b:
                if d.weekday() < 5:
                    out.add(d)
                d += timedelta(days=1)
        elif s.weekday() < 5:
            out.add(s)
    return out


# Bellevue SD 2026-2027, secondary — every weekday with no class.
_BSD_2026_2027_NO_SCHOOL = _dates(
    date(2026, 9, 7),                        # Labor Day
    date(2026, 10, 9),                       # Non-school day (make-up reserve)
    date(2026, 11, 11),                      # Veterans Day
    date(2026, 11, 26), date(2026, 11, 27),  # Thanksgiving
    (date(2026, 12, 21), date(2027, 1, 1)),  # Winter break
    date(2027, 1, 18),                       # MLK Jr. Day
    date(2027, 1, 29),                       # Staff workday, no students
    (date(2027, 2, 15), date(2027, 2, 19)),  # Mid-winter break
    date(2027, 3, 19),                       # Non-school day (make-up reserve)
    (date(2027, 4, 12), date(2027, 4, 16)),  # Spring break
    date(2027, 5, 31),                       # Memorial Day
    date(2027, 6, 1),                        # Non-school day (make-up reserve)
    date(2027, 6, 18),                       # Juneteenth observed
)

# Windows a field trip must not be scheduled in (2320P, both the day-trip and
# the overnight procedure list the same five).  Kept as data per year so the
# rule stays one place and the dates stay correctable.
#
#   semester_starts   first five SCHOOL days of each are blacked out
#   exam_ends         five school days BEFORE each are blacked out (finals /
#                     midterms -- the procedure says "prior to", so the exam
#                     days themselves are not the blackout)
#   testing           (start, end) windows: state testing, AP testing
#
# What is firm and what is not, so nobody trusts the wrong one:
#   * The days before a break come straight from no_school and need no data.
#   * First semester starts on the first day of school.  Second semester is
#     taken as the school day after the 29 Jan 2027 staff workday, which is
#     where BSD normally puts the semester break -- worth confirming.
#   * Exam ends are taken as the last school day of each semester.
#   * AP testing is the College Board's national window, first two full weeks
#     of May.  State testing is district-set and NOT known here: leave it
#     empty rather than invent it, and blackout_reasons will say so.
_BSD_2026_2027_WINDOWS = {
    "semester_starts": [date(2026, 9, 2), date(2027, 2, 1)],
    "exam_ends": [date(2027, 1, 28), date(2027, 6, 23)],
    "testing": [((date(2027, 5, 3), date(2027, 5, 14)), "AP testing")],
    "unknown_windows": ["state testing"],
}

# School board meeting dates.  An overnight or out-of-state trip is approved by
# the BOARD, and every approval deadline counts back from the meeting rather
# than from the trip -- so which meeting a trip is aiming at is the first thing
# that has to be known and the easiest thing to get wrong.
#
# Kept as plain data, and deliberately only the dates that are actually
# published.  BSD lists the next couple of meetings at
#   https://www.bsd405.org/about-us/school-board/meetings
# and keeps the full year's schedule on a Diligent portal that needs a browser
# to read.  Roka does not guess the rest from "roughly monthly": a made-up
# meeting date produces a confident, wrong deadline months out, which is worse
# than admitting the list is short.
#
# To extend: add (date, label) pairs.  Nothing else needs changing.
_BSD_2026_2027_BOARD = [
    (date(2026, 8, 24), "Special meeting (planning)"),
    (date(2026, 8, 27), "Regular board meeting"),
]

CALENDARS = {
    "2026-2027": {
        "first_day": date(2026, 9, 2),
        "last_day": date(2027, 6, 23),
        "no_school": _BSD_2026_2027_NO_SCHOOL,
        "windows": _BSD_2026_2027_WINDOWS,
        "board_meetings": _BSD_2026_2027_BOARD,
    },
}


def get_calendar(school_year):
    """The calendar dict for a year label ('2026-2027'), or None if unknown."""
    return CALENDARS.get(school_year)


def is_school_day(cal, d):
    if not cal:
        return d.weekday() < 5
    return (d.weekday() < 5 and cal["first_day"] <= d <= cal["last_day"]
            and d not in cal["no_school"])


def next_school_day(cal, d):
    for _ in range(400):
        if is_school_day(cal, d):
            return d
        d += timedelta(days=1)
    return None


def prev_school_day(cal, d):
    for _ in range(400):
        if is_school_day(cal, d):
            return d
        d -= timedelta(days=1)
    return None


def school_day_index(cal, d):
    """1-based count of school days from the first day through ``d`` (0 before
    the year starts).  Holidays and breaks are excluded."""
    if not cal:
        start = date(d.year if d.month >= 8 else d.year - 1, 9, 1)
        n, cur = 0, start
        while cur <= d:
            if cur.weekday() < 5:
                n += 1
            cur += timedelta(days=1)
        return n
    if d < cal["first_day"]:
        return 0
    n, cur = 0, cal["first_day"]
    end = min(d, cal["last_day"])
    while cur <= end:
        if is_school_day(cal, cur):
            n += 1
        cur += timedelta(days=1)
    return n


# ── School weeks ─────────────────────────────────────────────────────────────
# Every district field-trip deadline is expressed in SCHOOL weeks, and that is
# not five calendar days: eight school weeks across winter break is most of a
# term.  Counting them by hand is exactly the arithmetic a teacher gets wrong
# and then finds out about too late to fix.

SCHOOL_DAYS_PER_WEEK = 5


def add_school_days(cal, d, days):
    """``days`` school days after (or before, if negative) ``d``.

    Walks day by day rather than estimating: a stretch containing a break is
    not the same length as one that does not, which is the whole point.
    """
    if not cal or not d or not days:
        return d
    step = 1 if days > 0 else -1
    left = abs(int(days))
    cur = d
    lo, hi = cal["first_day"], cal["last_day"]
    # A hard stop well past any real school year, so a bad calendar cannot
    # spin here forever.
    for _ in range(2000):
        if left <= 0:
            return cur
        cur = cur + timedelta(days=step)
        if lo <= cur <= hi:
            if is_school_day(cal, cur):
                left -= 1
        elif cur.weekday() < 5:
            # Outside the school year there are no school days to count, and
            # walking on looking for one runs to the iteration cap and returns
            # a date years adrift.  Counting weekdays keeps the answer sane and
            # says the true thing: the deadline falls outside term.
            left -= 1
    return cur


def school_weeks_before(cal, d, weeks):
    """The date ``weeks`` school weeks before ``d``."""
    return add_school_days(cal, d, -int(round(weeks * SCHOOL_DAYS_PER_WEEK)))


def school_weeks_between(cal, start, end):
    """How many school weeks from ``start`` to ``end`` (negative if end is
    earlier).  Used to say "you have 3 school weeks left", which is the number
    a teacher actually needs."""
    if not cal or not start or not end:
        return None
    lo, hi = (start, end) if start <= end else (end, start)
    days = 0
    cur = lo
    for _ in range(2000):
        if cur >= hi:
            break
        cur += timedelta(days=1)
        if is_school_day(cal, cur):
            days += 1
    weeks = days / SCHOOL_DAYS_PER_WEEK
    return weeks if start <= end else -weeks


# ── Blackout dates ───────────────────────────────────────────────────────────

def blackout_reasons(cal, d):
    """Why this date is a bad one for a field trip -- a list of plain reasons,
    empty when it is fine.  2320P asks teachers to avoid five windows; this
    checks the ones the calendar knows."""
    if not cal or not d:
        return []
    out = []
    win = cal.get("windows") or {}

    # A non-school day is deliberately NOT a warning.  2320P blacks out the
    # school day BEFORE a break, not the break itself, and a trip that runs
    # over spring break is a good idea rather than a mistake: nobody needs a
    # substitute for a day there was no class on.
    # The school day before a break.  Two or more weekdays off in a row, so a
    # long weekend does not count: 2320P names Thanksgiving, winter, mid-winter
    # and spring, and flagging the Friday before Labor Day would train people
    # to ignore the warning.
    if is_school_day(cal, d):
        off, nxt = 0, d + timedelta(days=1)
        for _ in range(30):
            if nxt.weekday() >= 5:
                nxt += timedelta(days=1)
                continue
            if is_school_day(cal, nxt) or nxt > cal["last_day"]:
                break
            off += 1
            nxt += timedelta(days=1)
        if off >= 2:
            out.append("it is the school day before a break")

    for start in win.get("semester_starts", []):
        if start <= d <= add_school_days(cal, start, 4):
            out.append("it is in the first five school days of a semester")
            break

    for end in win.get("exam_ends", []):
        if school_weeks_before(cal, end, 1) <= d <= end:
            out.append("it is in the five school days before midterms or finals")
            break

    for (a, b), label in win.get("testing", []):
        if a <= d <= b:
            out.append(f"it is inside the {label} window")

    return out


def unchecked_windows(cal):
    """Blackout windows this calendar has no dates for, so the warning can say
    what it did NOT check instead of implying the date is clear."""
    return list(((cal or {}).get("windows") or {}).get("unknown_windows", []))


# ── School board meetings ────────────────────────────────────────────────────

BOARD_MEETINGS_URL = "https://www.bsd405.org/about-us/school-board/meetings"


def board_meetings(cal):
    """[(date, label)] for the year, soonest first.  Empty when none are
    recorded, which callers must handle by saying so rather than by guessing."""
    return sorted((cal or {}).get("board_meetings") or [], key=lambda x: x[0])
