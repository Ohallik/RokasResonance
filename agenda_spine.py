"""
agenda_spine.py - The deterministic curriculum spine for daily agendas.

Given a date and a little context (the year's concert dates + repertoire), this
builds a sensible DEFAULT agenda for that day: the standing reminders, the
Fundamentals warm-up at the right level for the concert cycle, a band-book /
assessment line, the concert repertoire as sheet music, and (Entry only) a
Practice Journal turn-in on Fridays.  Everything it returns is a plain dict the
teacher then edits freely; edits are saved per day.  No UI, no I/O — pure logic
so it can be unit-tested and reused by an LLM "draft this week" helper later.

The one rule that ties it together (the teacher's own): the Fundamentals LEVEL
follows the three home concerts — Level 1 through the December concert, Level 2
through March, Level 3 through June.  Within a week the exercises alternate
odd/even by day, and Friday is "choose three."

This is Entry Band's spine.  Intermediate/Advanced use different warm-up sources
(Broccoli / band book) and no Practice Journal; those hook in later.  The
teacher's specifics live here as DATA so a future version can let other BSD
directors configure their own.
"""

import json as _json
import os as _os
import sys as _sys
from datetime import date, timedelta

import school_calendar as _scal   # pure date logic (no I/O), safe to import


def _data_path(filename):
    """Locate a bundled data file next to this module — or, in a PyInstaller
    build, under the extracted bundle (sys._MEIPASS).  Keeps the SoE / Technique
    line JSON loading in both a source run and the installed .exe."""
    base = getattr(_sys, "_MEIPASS", None)
    if base:
        p = _os.path.join(base, filename)
        if _os.path.exists(p):
            return p
    return _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), filename)

ENTRY = "entry"
INTERMEDIATE = "intermediate"
ADVANCED = "advanced"
JAZZ = "jazz"

# ── Fundamentals for Entry Band, by concert-cycle level ───────────────────────
# Exercise names as the teacher writes them.  Level 1 runs to the December
# concert, Level 2 to March, Level 3 to June.  Level 2 has six exercises (no
# #7); Levels 1 and 3 have seven.
FUNDAMENTALS = {
    1: ["#1 Concert F", "#2 Long Tones", "#3 Back and Forth",
        "#4 Five Note Scale", "#5 Flexibility", "#6 Slurs", "#7 Thirds"],
    2: ["#1 Concert F", "#2 Eighth Notes, Long Tones", "#3 Five Note Scale",
        "#4 Flexibility", "#5 Slurs/Intervals", "#6 Counting Etude"],
    3: ["#1 Concert F", "#2 Long Tones", "#3 Five Note Scale", "#4 Flexibility",
        "#5 Attacks", "#6 High Range Workout", "#7 Etude"],
}


def fundamentals_title(level):
    return "Fundamentals" if level == 1 else f"Fundamentals Level {level}"


# ── The standing "reminders" banner (unchanging bell-work) ────────────────────
DEFAULT_REMINDERS = ["Don't play yet", "Instrument out", "Music out",
                     "Case CLOSED"]

# ── Entry Band's yearly assessments (specific band-book lines, in order) ──────
# The graded "Go for Excellence" / "For ___ Only" / scale lines she tests, in
# order, calibrated against a full normal year (2024-25 Entry): six in the fall,
# then the winter/spring set, plus TWO scale tests pulled from p.42 (Concert Ab,
# then Chromatic).  #138 + the Concert Ab scale land ~together in late May;
# #155 + the Chromatic scale close out in June.  Kept as DATA so it's editable
# per teacher — which line is an assessment, how many, and the cadence, is one
# director's system, not universal.
ASSESSMENTS = [
    "#14", "#29", "#43", "#49", "#55", "#61",                        # sem 1
    "#78", "#84", "#88", "#96", "#122", "#126", "#134",             # sem 2
    "#138", "p.42 Concert Ab scale", "#155", "p.42 Chromatic scale",  # late May → June
]

# Her assessment cadence, as a rule rather than fixed dates (so it transposes
# to any school year and resets each fall):
#   * assessments are due on FRIDAYS,
#   * the first one lands about the 4th school-Friday (after the ~8-day
#     instrument-exploration period at the start of the year),
#   * a new one every 2 weeks after that,
#   * and each is INTRODUCED on the agenda ~2 weeks before it's due.
# Anchored to SCHOOL Fridays (holiday weeks skipped), matching last year's real
# due dates (#14 "first test" was due the 4th school-Friday, Sept 27 2024)
# transposed onto the current calendar.  All are meant to become user-configurable.
# NOTE: real spacing wobbles (one week between #49/#55, wider over concerts and
# breaks, and the final two coincide) — this even cadence is only the SEED the
# teacher then re-dates per year in the Assessments editor.
ASSESS_FIRST_FRIDAY = 4       # 1-based index of the first assessment's Friday
ASSESS_SPACING = 2            # weeks between assessments
ASSESS_LEAD_WEEKS = 2         # show it this many weeks before its due date

# ── Instrument-exploration period ─────────────────────────────────────────────
# She spends roughly the first 8 school days letting Entry members try each
# instrument before committing; page-6 band-book work starts "for real" the
# THIRD week of school.  DATA (a per-teacher default) so it factors out later.
# In 2024-25 (first day Tue Sept 3) the 9th school day was Fri Sept 13 — the
# "FIRST DAY to play for real, pages 6-7" in her agenda.
INTRO_SCHOOL_DAYS = 8


def fundamentals_level(d, concert_dates):
    """Which Fundamentals level (1/2/3) a date falls in.

    Driven by the home-concert boundaries: level = 1 + how many concerts have
    already happened, capped at 3.  With no concerts entered, fall back to a
    simple month split (Aug–Dec = 1, Jan–Mar = 2, Apr–Jul = 3)."""
    bounds = sorted(dd for dd in concert_dates if dd)
    if bounds:
        passed = sum(1 for b in bounds if d > b)
        return min(3, 1 + passed)
    # No concerts entered yet — month-based fallback.
    if d.month >= 8 or d.month == 12:
        return 1 if d.month != 12 or d.day < 20 else 2
    if d.month <= 3:
        return 2
    return 3


def fundamentals_for_day(level, weekday):
    """The Fundamentals exercises to run on ``weekday`` (Mon=0 … Fri=4).

    Odd days (Mon/Wed) do the odd-numbered exercises, even days (Tue/Thu) the
    even ones, and Friday is "choose three" (all of them offered).  Returns
    ``(items, mode)`` where mode is "normal" or "choose3"."""
    items = FUNDAMENTALS.get(level, FUNDAMENTALS[2])
    if weekday >= 4:                       # Friday (or later) — choose 3
        return list(items), "choose3"
    if weekday % 2 == 0:                   # Mon / Wed — odd exercises
        picked = items[0::2]               # #1, #3, #5, (#7)
    else:                                  # Tue / Thu — even exercises
        picked = items[1::2]               # #2, #4, #6
    return picked, "normal"


def _school_days_between(start, end):
    """Count weekdays (Mon–Fri) from ``start`` up to and including ``end``.
    A rough school-day index until the real district calendar is wired in
    (holidays aren't excluded yet)."""
    if end < start:
        return 0
    n = 0
    d = start
    while d <= end:
        if d.weekday() < 5:
            n += 1
        d += timedelta(days=1)
    return n


def week_index(d, year_start):
    """1-based Monday-week number since the year began (for Practice Journal
    numbering and rough pacing)."""
    # Align both to their Monday, count weeks.
    ws = year_start - timedelta(days=year_start.weekday())
    wd = d - timedelta(days=d.weekday())
    return max(1, (wd - ws).days // 7 + 1)


def practice_journal_number(d, year_start):
    """Roughly one Practice Journal per school week (turned in Fridays)."""
    return week_index(d, year_start)


def _school_fridays(cal, year_start, year_end):
    """Every Friday that's a school day, in order.  With no calendar, all
    Fridays in the window (rough fallback)."""
    out = []
    d = year_start
    one = timedelta(days=1)
    while d <= year_end:
        if d.weekday() == 4 and (cal is None or _scal.is_school_day(cal, d)):
            out.append(d)
        d += one
    return out


def _school_day_index(d, cal, year_start):
    """1-based school-day index for ``d`` (0 before the year)."""
    if cal is not None:
        return _scal.school_day_index(cal, d)
    return _school_days_between(year_start, d) if d >= year_start else 0


def in_intro_period(d, cal, year_start, intro_days=INTRO_SCHOOL_DAYS):
    """True during the instrument-exploration window at the start of the year
    (school days 1..intro_days), before page-6 band-book work begins."""
    idx = _school_day_index(d, cal, year_start)
    return 0 < idx <= intro_days


def band_book_page(d, cal, year_start, intro_days=INTRO_SCHOOL_DAYS):
    """The student-book page the class is on the week of ``d``.

    Her pacing: after ~``intro_days`` of instrument tryouts, the first teaching
    week covers pages 6 AND 7, then ~one page per week, capped at 35 (line-work
    ends around there in May; 36-42 are scales/skipped).  Driven by the
    school-day index, so it RESETS to page 6 each fall automatically.  Returns
    an int page (6-35), a "6-7" for the first teaching week via
    :func:`band_book_page_label`, or None before page work begins."""
    idx = _school_day_index(d, cal, year_start) - intro_days
    if idx <= 0:
        return None
    week = (idx - 1) // 5 + 1            # ~5 school days per teaching week
    return min(35, 6 if week == 1 else 6 + week)


def band_book_page_label(d, cal, year_start, intro_days=INTRO_SCHOOL_DAYS):
    """"6-7" the first teaching week (two pages), else "N"; None before page
    work begins (i.e. during the intro period or before the year)."""
    idx = _school_day_index(d, cal, year_start) - intro_days
    if idx <= 0:
        return None
    week = (idx - 1) // 5 + 1
    return "6-7" if week == 1 else str(min(35, 6 + week))


def assessment_schedule(cal, year_start, year_end):
    """Due-dates for the yearly assessments, following her cadence (see the
    ASSESS_* constants): one every ~2 weeks on a Friday, starting ~the 3rd
    school-Friday.  Anchored to SCHOOL Fridays so break weeks are skipped and
    the whole schedule transposes to any year / resets each fall.

    Returns ``[(ref, due_date, introduce_date), ...]`` — introduce_date is when
    the line should first appear on the agenda (~2 weeks ahead of due)."""
    fridays = _school_fridays(cal, year_start, year_end)
    out = []
    if not fridays:
        return out
    for i, ref in enumerate(ASSESSMENTS):
        slot = ASSESS_FIRST_FRIDAY + ASSESS_SPACING * i      # 1-based ordinal
        due = fridays[min(slot, len(fridays)) - 1]
        lead = slot - ASSESS_LEAD_WEEKS
        intro = fridays[lead - 1] if 1 <= lead <= len(fridays) else year_start
        out.append((ref, due, intro))
    return out


def assessments_for_day(d, schedule):
    """Assessments visible on ``d``: introduced (~2 weeks ahead) and not yet
    past due.  Returns ``[(ref, due_date), ...]`` (usually one, sometimes two
    on a hand-off day)."""
    return [(ref, due) for ref, due, intro in schedule if intro <= d <= due]


def default_assessments(cal, year_start, year_end):
    """The suggested starting assessment list — [{'ref', 'due'(date)}] — from the
    built-in cadence.  Used ONLY to seed a teacher who hasn't set their own; the
    real list is teacher-defined (which lines, how many, and each due date)."""
    return [{"ref": ref, "due": due}
            for ref, due, _intro in assessment_schedule(cal, year_start, year_end)]


# ── Intermediate Band's yearly assessments ────────────────────────────────────
# Her Intermediate assessment sheet (both snare AND mallets, always; infinite
# retakes, no late deductions, no speed requirement).  A mix of Book-2 lines and
# "Broccoli" (her own warm-up) scales, bucketed by semester rather than pinned to
# dates — so these seed the editor DATELESS; she assigns due dates per year only
# if she wants a line to auto-surface on the agenda.  DATA (one director's set).
INT_ASSESSMENTS = [
    # Semester 1
    "Broccoli scale 3", "Line 21", "Broccoli scale 4", "Line 29", "Line 37",
    "Broccoli scale 2", "Broccoli scale 5", "Broccoli scale 1", "Broccoli scale 12",
    # Semester 2
    "Line 72", "Line 78", "Broccoli scale 6", "Line 96", "Broccoli scale 11",
    "Broccoli scale 10", "Broccoli scale 9", "Broccoli scale 8", "Broccoli scale 7",
    "Line 118",
]


def default_int_assessments():
    """The seed Intermediate assessment list — [{'ref', 'due'(None)}] — dateless.
    Preserves her real assessment set as editable data; she assigns due dates per
    year if she wants a line to auto-surface (~2 weeks ahead) on the agenda."""
    return [{"ref": ref, "due": None} for ref in INT_ASSESSMENTS]


def assessments_visible(d, items, lead_days=14):
    """From a teacher-defined list ``[{'ref', 'due'(date)}, ...]``, the ones to
    show on ``d``: introduced ``lead_days`` before their due date and not yet
    past due.  Returns ``[(ref, due_date), ...]`` sorted by due date."""
    out = []
    for it in items or []:
        due = it.get("due")
        if due and (due - timedelta(days=lead_days)) <= d <= due:
            out.append((it.get("ref", ""), due))
    out.sort(key=lambda x: x[1])
    return out


def next_assessment(d, schedule):
    """The next assessment due on or after ``d`` — ``(ref, due_date)`` or None.
    Accepts either the 3-tuple schedule or a list of ``(ref, due)`` pairs."""
    for row in schedule:
        ref, due = row[0], row[1]
        if due >= d:
            return ref, due
    return None


def _item(text, done=False, note="", kind=""):
    """One agenda line.  ``kind`` marks special rendering:
        ""          normal (checkbox + text)
        "assessment"  a test line — highlighted blue + bold (checkbox kept)
        "missing"     the "Missing:" names line — no checkbox
    """
    return {"text": text, "done": done, "note": note, "kind": kind}


# ── Standard of Excellence line data (for the band-book dropdowns) ────────────
# Book 1 (Entry) and Book 2 (Intermediate) loaded from JSON next to this module.
# Each numbered line is tagged with its STUDENT page so the teacher can pick a
# page, then pick the lines on that page, instead of typing titles.
_SOE_FILES = {1: "soe_book1_lines.json", 2: "soe_book2_lines.json"}
_SOE_CACHE = {}


def _load_soe(book=1):
    cached = _SOE_CACHE.get(book)
    if cached is not None:
        return cached
    path = _data_path(_SOE_FILES.get(book, _SOE_FILES[1]))
    try:
        with open(path, encoding="utf-8") as fh:
            d = _json.load(fh)
    except Exception:
        _SOE_CACHE[book] = {"pages": [], "by_page": {}, "by_n": {}}
        return _SOE_CACHE[book]
    anchors = sorted((int(k), v) for k, v in
                     d.get("student_page_anchors", {}).items() if str(k).isdigit())

    def page_for(n):
        pg = anchors[0][1] if anchors else 0
        for a, p in anchors:
            if n >= a:
                pg = p
            else:
                break
        return pg

    by_page, by_n = {}, {}
    for line in d.get("lines", []):
        n = line.get("n")
        if n is None:
            continue
        rec = {"n": n, "title": line.get("title", ""), "page": page_for(n),
               "assessment": bool(line.get("assessment"))}
        by_n[n] = rec
        by_page.setdefault(rec["page"], []).append(rec)
    _SOE_CACHE[book] = {"pages": sorted(by_page), "by_page": by_page, "by_n": by_n}
    return _SOE_CACHE[book]


def soe_pages(book=1):
    """Student-book page numbers that have numbered lines."""
    return _load_soe(book)["pages"]


def soe_lines_on_page(page, book=1):
    """The numbered lines on a given student page: [{n, title, assessment}]."""
    return _load_soe(book)["by_page"].get(page, [])


def soe_line(n, book=1):
    return _load_soe(book)["by_n"].get(n)


def soe_label(n, book=1):
    rec = soe_line(n, book)
    return f"#{n} {rec['title']}" if rec and rec.get("title") else f"#{n}"


# ── Technique & Musicianship line data (Advanced Band's key-signature picker) ──
# A different book shape from SoE: every MAJOR key is a 2-page spread with the
# SAME 10 lines — #1-8 and #10 identical for every key, only #9 (a repertoire
# etude) and the page pair vary.  Stored as a template + per-key table and
# expanded here, so adding a key later is one row.  Partial for now (B♭/E♭/F);
# fill in the rest when the TOC is scanned.
_TM_CACHE = None


def _load_tm():
    global _TM_CACHE
    if _TM_CACHE is not None:
        return _TM_CACHE
    path = _data_path("technique_musicianship_lines.json")
    try:
        with open(path, encoding="utf-8") as fh:
            d = _json.load(fh)
    except Exception:
        _TM_CACHE = {"keys": [], "by_key": {}}
        return _TM_CACHE
    common = d.get("common_lines", {})
    order, by_key = [], {}
    for k in d.get("keys", []):
        key = k.get("key")
        if not key:
            continue
        pages = k.get("pages") or []
        even = pages[0] if pages else None
        odd = pages[1] if len(pages) > 1 else even
        disp = f"Concert {key}"
        lines = []
        for n in range(1, 11):
            if n == 9:
                title = k.get("line9", "")
            else:
                title = common.get(str(n), "")
                if n == 1:
                    title = title.replace("{key}", key)
            lines.append({"n": n, "title": title,
                          "page": even if n <= 6 else odd})
        by_key[disp] = lines
        order.append(disp)
    _TM_CACHE = {"keys": order, "by_key": by_key}
    return _TM_CACHE


def tm_keys():
    """Concert-key labels that have a spread entered (e.g. 'Concert B♭')."""
    return _load_tm()["keys"]


def tm_lines_for_key(key):
    """The 10 lines for a key: [{n, title, page}]."""
    return _load_tm()["by_key"].get(key, [])


def tm_label(key, n):
    for r in tm_lines_for_key(key):
        if r["n"] == n:
            return f"#{n} {r['title']}" if r.get("title") else f"#{n}"
    return f"#{n}"


def _concert_for_level(level, concerts):
    """The concert dict for a given cycle level (1→first concert, etc.)."""
    ordered = sorted((c for c in concerts if c.get("date")),
                     key=lambda c: c["date"])
    idx = level - 1
    if 0 <= idx < len(ordered):
        return ordered[idx]
    return ordered[-1] if ordered else None


def build_default_day(d, ctx):
    """Build the DEFAULT agenda dict for date ``d``.

    ``ctx`` carries:
        group                : "entry" (default) or "intermediate"
        year_start, year_end : date bounds of the school year
        concerts             : [{"date": date, "pieces": [title, ...]}, ...]

    Returns a dict: {date, reminders, announcements, sections, practice_journal}
    where each section is {title, items:[{text, done, note}]}.

    The three ensembles share the SAME day skeleton (reminders/announcements
    banner, warm-up, an assessment/band-book area, sheet music); they differ in:
      * Entry        — Rhythms pane + Fundamentals warm-up + SoE Bk 1 band book +
                       the Friday Practice Journal.
      * Intermediate — blank "Broccoli" warm-up + SoE Bk 2 band book, no PJ.
      * Advanced     — blank "Warm Up" + blank "Sheet Music", NO band book (their
                       "Technique & Musicianship" book is warm-up material, not a
                       line-by-line homework spine); the day is intentionally
                       mostly-blank because their day-to-day is the most variable.
                       Assessments are set up per year and only surface (as a small
                       "Assessments" section) once she dates them.  No PJ.
    """
    # A class points at a TEMPLATE (band_entry / band_intermediate /
    # band_advanced / jazz / generic).  Older callers pass ``group`` instead —
    # map the four legacy group names onto their templates so nothing breaks.
    template = ctx.get("template")
    if not template:
        template = {ENTRY: "band_entry", INTERMEDIATE: "band_intermediate",
                    ADVANCED: "band_advanced", JAZZ: "jazz"}.get(
                        ctx.get("group") or ENTRY, "generic")
    is_jazz = template == "jazz"
    is_entry = template == "band_entry"
    is_int = template == "band_intermediate"
    # Everything that isn't one of the four legacy band/jazz templates (choir,
    # orchestra, guitar/steel, HS bands, 5th-grade, one-off clubs) gets the blank
    # "generic" day.  Keeping this as a catch-all means new templates don't have
    # to be enumerated here — they just render blank warm-up + sheet music.
    is_generic = template not in ("band_entry", "band_intermediate",
                                  "band_advanced", "jazz")
    # Advanced and generic share the same skeleton (blank warm-up + sheet music,
    # no method book); only Advanced adds the Technique & Musicianship picker and
    # its assessment seed, both handled in the view.
    is_adv = template == "band_advanced" or is_generic
    book = 2 if is_int else 1

    # ── Jazz — intentionally the simplest day: a blank Warm Up and a blank Sheet
    #    Music, no method book / assessments / practice journal.  The rhythm-
    #    section lineups (rotation + per-song locked personnel) are attached in
    #    the view, not baked into the spine.
    if is_jazz:
        return {
            "date": d.isoformat(),
            "reminders": list(ctx.get("reminders") or []),
            "announcements": [],
            "sections": [
                {"title": "Warm Up", "kind": "warmup", "items": [_item("")]},
                {"title": "Sheet Music", "kind": "sheet", "items": [_item("")]},
            ],
            "practice_journal": None,
        }
    concerts = ctx.get("concerts") or []
    concert_dates = [c.get("date") for c in concerts if c.get("date")]
    year_start = ctx.get("year_start") or date(d.year if d.month >= 8
                                               else d.year - 1, 9, 1)
    year_end = ctx.get("year_end") or date(year_start.year + 1, 6, 30)
    cal = ctx.get("calendar")
    wd = d.weekday()

    level = fundamentals_level(d, concert_dates)   # concert-cycle index

    sections = []

    # ── Warm-up — left BLANK for every class.  The specific warm-up sets
    #    (Fundamentals, "Broccoli", Technique & Musicianship) were one teacher's
    #    and don't generalize, so new users fill in their own.  Entry still gets
    #    the empty Rhythms image pane above it.
    if is_entry:
        sections.append({"title": "Rhythms", "kind": "rhythms", "items": []})
    sections.append({"title": "Warm Up", "kind": "warmup",
                     "items": [_item("") for _ in range(4)]})

    # ── Assessments (teacher-defined only).  We no longer seed any suggested
    #    schedule — the only thing tracked is due dates the teacher enters
    #    themselves.  The view passes its saved list; absent that, none.
    assessments = ctx.get("assessments") or []
    assess_items = []
    for ref, due in assessments_visible(d, assessments):
        label = ref
        if ref.startswith("#"):
            try:
                label = soe_label(int(ref[1:]), book)
            except (ValueError, TypeError):
                pass
        assess_items.append(_item(f"{label} (due {due.strftime('%b %d')})",
                                  kind="assessment"))
        assess_items.append(_item("Missing: ", kind="missing"))

    if is_adv:
        # No band book for Advanced — assessments (when dated) get their own small
        # section, otherwise nothing (keep the day minimal).
        if assess_items:
            sections.append({"title": "Assessments", "kind": "",
                             "items": assess_items})
    else:
        # Band book — a sticky carry-forward page the teacher typed (we never
        # auto-assume a page), plus any dated assessment + its Missing list.
        bb = []
        intro_days = ctx.get("intro_days")
        if intro_days is None:
            intro_days = INTRO_SCHOOL_DAYS
        page = ctx.get("band_page")
        if page:
            bb.append(_item(f"p. {page}"))
        elif is_entry and in_intro_period(d, cal, year_start, intro_days):
            # First ~2 weeks: trying each instrument before committing.
            bb.append(_item("Instrument exploration (trying each instrument)"))
        bb.extend(assess_items)
        if not bb:
            bb.append(_item(""))
        sections.append({"title": "Band book", "kind": "bandbook", "items": bb})

    # ── Sheet Music ──
    if is_adv:
        # Blank — she fills in the current unit's repertoire (short concert cycle,
        # many events, so it changes constantly).
        sections.append({"title": "Sheet Music", "kind": "sheet",
                         "items": [_item("")]})
    else:
        concert = _concert_for_level(level, concerts)
        pieces = (concert or {}).get("pieces") or []
        sections.append({"title": "Sheet Music", "kind": "sheet",
                         "items": [_item(p) for p in pieces] or [_item("")]})

    # Practice journals are not auto-tracked — that was one teacher's weekly
    # routine and doesn't belong in the shared default.  Kept as None so any
    # consumer reading day["practice_journal"] still works.
    pj = None

    # Banner: reminders (standing) + announcements (auto bits).
    # Announcements start blank for everyone (the old "Don't forget Jazz 2" was
    # one teacher's personal note); only the generic concert countdown auto-fills.
    announcements = []
    upcoming = [c["date"] for c in concerts
                if c.get("date") and 0 <= (c["date"] - d).days <= 14]
    if upcoming:
        days = (min(upcoming) - d).days
        announcements.append("Concert is today!" if days == 0
                             else f"Concert in {days} day{'s' if days != 1 else ''}")

    return {
        "date": d.isoformat(),
        "reminders": list(ctx.get("reminders") or []),
        "announcements": announcements,
        "sections": sections,
        "practice_journal": pj,
    }
