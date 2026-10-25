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


def class_concerts(concerts, class_label, skip_ids=()):
    """The concerts this class performs in (its name is in the concert's
    ensembles list), less any the teacher said don't end a cycle (an
    assembly, a festival), as ``[(id, iso date, title)]`` by date."""
    want = " ".join((class_label or "").lower().split())
    skip = {int(x) for x in skip_ids or []}
    out = []
    for c in concerts or []:
        ens = [" ".join(e.lower().split())
               for e in (c["ensembles"] or "").split(",")]
        if want and want in ens and c["id"] not in skip and c["concert_date"]:
            out.append((c["id"], str(c["concert_date"])[:10], c["title"] or ""))
    return sorted(out, key=lambda t: t[1])
