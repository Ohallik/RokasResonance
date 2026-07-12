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

CALENDARS = {
    "2026-2027": {
        "first_day": date(2026, 9, 2),
        "last_day": date(2027, 6, 23),
        "no_school": _BSD_2026_2027_NO_SCHOOL,
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
