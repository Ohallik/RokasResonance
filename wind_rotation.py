"""
wind_rotation.py - Which instrument a doubling wind player is on today.

Some wind players play two or three instruments (flute and oboe, trumpet,
horn and baritone) and take turns with them.  Left to themselves, they lose
track of whose turn it is, so the agenda says it for them: "Julia - Oboe".

Each doubler is a plain dict::

    {"name": "Julia", "instruments": ["Flute", "Oboe", "Violin"],
     "every": "day" | "week" | "concert", "offset": 0, "section": ""}

``every`` is how often they switch:

  * ``day``     - every class meeting (Flute, Oboe, Flute, Oboe...)
  * ``week``    - every school week
  * ``concert`` - stay on one instrument for a whole concert cycle (winter,
                  March, June), switching the day after each concert

The caller counts the steps (the agenda knows the meetings, the weeks and
the concerts); this module only turns a step number into an instrument, and
works out the ``offset`` that makes "today" land on the instrument the
teacher picked.  ``section`` ties the doubler to one class period ("" = the
whole class).  No tkinter here, so it is testable headless.
"""

EVERY = ("day", "week", "concert")
EVERY_LABELS = {"day": "Every other class day",
                "week": "Every other week",
                "concert": "Each concert cycle"}
MAX_INSTRUMENTS = 3


def clean(entry):
    """A doubler with blank instruments dropped and the fields defaulted, or
    None when there is nothing to rotate (no name, or under two instruments)."""
    if not isinstance(entry, dict):
        return None
    name = (entry.get("name") or "").strip()
    seen, insts = set(), []
    for i in entry.get("instruments") or []:
        i = (i or "").strip()
        if i and i.lower() not in seen:
            seen.add(i.lower())
            insts.append(i)
    insts = insts[:MAX_INSTRUMENTS]
    if not name or len(insts) < 2:
        return None
    every = entry.get("every") if entry.get("every") in EVERY else "day"
    try:
        offset = int(entry.get("offset") or 0)
    except (TypeError, ValueError):
        offset = 0
    return {"name": name, "instruments": insts, "every": every,
            "offset": offset % len(insts),
            "section": str(entry.get("section") or "")}


def instrument_on(entry, step):
    """The instrument for counting step ``step`` (1-based: the first class
    day, week or concert cycle of the year is step 1)."""
    e = clean(entry)
    if e is None:
        return ""
    insts = e["instruments"]
    return insts[(max(1, int(step)) - 1 + e["offset"]) % len(insts)]


def offset_for(n_instruments, step, now_index):
    """The offset that puts instrument ``now_index`` on step ``step``."""
    if n_instruments <= 0:
        return 0
    return (int(now_index) - (max(1, int(step)) - 1)) % n_instruments


def concert_step(concert_dates, iso_today):
    """Which concert cycle a date is in, 1-based.  The concert day itself
    still belongs to the cycle it ends; the next day starts the new one."""
    return 1 + sum(1 for d in concert_dates if d and str(d)[:10] < iso_today)


def _skip_key(x):
    """A stored skip: "c:3" / "t:1", or a bare number from before field trips
    counted (always a concert)."""
    x = str(x)
    return x if ":" in x else f"c:{x}"


def class_performances(concerts, trips, class_label, skip_ids=()):
    """Every performance this class is in -- concerts on the Performances
    tab AND field-trip performances -- less any the teacher said don't end a
    cycle, as ``[(key, iso date, title, kind)]`` by date.  ``key`` is
    "c:<id>" or "t:<id>"; ``kind`` is "concert" or "field trip".

    Classes are matched by identity, not spelling: a trip listing
    "MS Band (Intermediate)" is Intermediate Band's (it was missed when the
    names had to match exactly)."""
    try:
        from class_registry import csv_has_class
    except Exception:                                   # pragma: no cover
        def csv_has_class(csv, t):
            return t.lower() in [p.strip().lower() for p in (csv or "").split(",")]
    skip = {_skip_key(x) for x in skip_ids or []}
    out = []
    for c in concerts or []:
        key = f"c:{c['id']}"
        if (c["concert_date"] and key not in skip
                and csv_has_class(c["ensembles"] or "", class_label)):
            out.append((key, str(c["concert_date"])[:10], c["title"] or "",
                        "concert"))
    for t in trips or []:
        key = f"t:{t['id']}"
        if (t["depart_date"] and key not in skip
                and csv_has_class(t["groups_list"] or "", class_label)):
            out.append((key, str(t["depart_date"])[:10], t["name"] or "",
                        "field trip"))
    return sorted(out, key=lambda e: e[1])


def class_concerts(concerts, class_label, skip_ids=()):
    """Concerts only, as ``[(key, iso date, title, kind)]`` (see
    class_performances)."""
    return class_performances(concerts, (), class_label, skip_ids)
