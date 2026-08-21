"""
seating_chart.py - Pure logic for generating classroom & concert seating charts.

A student is a dict with at least:
    id, name (display / first name), last, first, instrument,
    pref  ('front' | 'back' | None)      # IEP/504 row preference
    note  (str)                           # IEP/504 note

The module turns a roster into rows of seats using one of several strategies,
honours "keep apart" conflicts and IEP/504 row pins, and knows the standard
band concert front-to-back ordering (woodwinds → brass → percussion, with the
tuba drawn toward the middle of the back).

No UI, no I/O — everything here is deterministic given its inputs (except the
explicitly random shuffle, which takes an optional seed).
"""

import random
import re as _re

# ── Instrument families ───────────────────────────────────────────────────────
# Short names are the current vocabulary; the long forms are kept so students
# entered before the rename still classify correctly.
BARITONE_FAMILY = ["Baritone BC", "Baritone TC", "Euphonium BC", "Euphonium TC",
                   "Baritone/Euphonium"]
WOODWINDS = ["Flute", "Oboe", "Bassoon", "Clarinet", "Bass Clarinet",
             "Alto Sax", "Tenor Sax", "Bari Sax",
             "Alto Saxophone", "Tenor Saxophone", "Baritone Saxophone"]
BRASS = ["Trumpet", "French Horn", "Trombone", "Tuba"] + BARITONE_FAMILY
LOW_BRASS = ["Trombone", "Tuba"] + BARITONE_FAMILY
PERCUSSION = ["Percussion"]
STRINGS = ["Violin", "Violin 1", "Violin 2", "Viola", "Viola 1", "Viola 2",
           "Cello", "Cello 1", "Cello 2", "String Bass", "Harp", "Piano"]
VOICES = ["Soprano", "Alto", "Tenor", "Baritone", "Bass"]

# Standard band concert order, front (index 0) to back.
CONCERT_ORDER = [
    "Flute", "Clarinet",                                    # front row
    "Oboe", "Bassoon", "Bass Clarinet",                     # other woodwinds
    "Alto Sax", "Alto Saxophone",
    "Tenor Sax", "Tenor Saxophone",
    "Bari Sax", "Baritone Saxophone",
    "Trumpet", "French Horn",                               # brass
    "Trombone",
    "Baritone BC", "Baritone TC", "Euphonium BC", "Euphonium TC",
    "Baritone/Euphonium", "Tuba",                           # low brass
    "Violin 1", "Violin 2", "Violin",                       # strings
    "Viola 1", "Viola 2", "Viola",
    "Cello 1", "Cello 2", "Cello",
    "String Bass", "Harp", "Piano",
    "Soprano", "Alto", "Tenor", "Baritone", "Bass",         # choir voices
    "Percussion",                                           # back row
]

SORT_MODES = ["alphabetical_first", "alphabetical", "sections", "small_groups", "full_shuffle"]

# Stable per-section colors for the "color by section" view.
SECTION_COLORS = {
    "Flute": "#ff6b6b", "Oboe": "#f78fb3", "Clarinet": "#ffd166",
    "Bass Clarinet": "#f4a259", "Bassoon": "#e07a5f",
    "Alto Sax": "#8ac926", "Tenor Sax": "#52b788", "Bari Sax": "#2a9d8f",
    "Alto Saxophone": "#8ac926", "Tenor Saxophone": "#52b788",
    "Baritone Saxophone": "#2a9d8f",
    "Trumpet": "#4d96ff", "French Horn": "#6c8dfa",
    "Trombone": "#9b5de5", "Tuba": "#7b2cbf",
    "Baritone BC": "#c77dff", "Baritone TC": "#c77dff",
    "Euphonium BC": "#c77dff", "Euphonium TC": "#c77dff",
    "Baritone/Euphonium": "#c77dff",
    # Strings get five separate hues rather than shades of one.  Every string
    # section used to be a variant of cyan, which read as a single blue block
    # across the whole chart.  Divided parts share their section's hue (a second
    # viola stand is still viola); firsts and seconds of the violins are the one
    # split a conductor scans for, so they are deliberately far apart.
    "Violin": "#ff6b6b", "Violin 1": "#ff6b6b", "Violin 2": "#ffd166",
    "Viola": "#8ac926", "Viola 1": "#8ac926", "Viola 2": "#8ac926",
    "Cello": "#4d96ff", "Cello 1": "#4d96ff", "Cello 2": "#4d96ff",
    # A deeper purple than the obvious #9b5de5: red-blind and green-blind
    # viewers see that lighter violet as very nearly the cello blue, and the
    # two lowest voices sitting next to each other is exactly where that
    # matters.  This one stays plainly purple and reads darker than the blue.
    # Harp and piano sit outside the five string sections, so they get colors
    # that belong to no section at all rather than another pink or orange that
    # competes with the violins.
    "String Bass": "#8e24aa", "Harp": "#8d6e63", "Piano": "#264653",
    "Soprano": "#ff6b6b", "Alto": "#ffd166", "Tenor": "#8ac926",
    "Baritone": "#4d96ff", "Bass": "#8e24aa",
    "Percussion": "#adb5bd",
}
_SECTION_FALLBACK = ["#ff6b6b", "#ffd166", "#8ac926", "#4d96ff", "#9b5de5",
                     "#f78fb3", "#52b788", "#6c8dfa", "#c77dff", "#48cae4"]


def section_color(instrument, index=0):
    return SECTION_COLORS.get((instrument or "").strip(),
                              _SECTION_FALLBACK[index % len(_SECTION_FALLBACK)])


# "Like instrument" affinity groups for small mixed clusters.  Two instruments
# are alike if they share ANY of these groupings — instrument family (brass
# with brass, woodwind with woodwind), the sax family, double reeds, or the
# same voice register.  So a bari sax pairs naturally with a tuba (low voice),
# an alto sax (saxes), or a trombone (low voice).
SAXES = {"Alto Sax", "Alto Saxophone", "Tenor Sax", "Tenor Saxophone",
         "Bari Sax", "Baritone Saxophone"}
DOUBLE_REEDS = {"Oboe", "Bassoon"}
HIGH_VOICES = {"Flute", "Oboe", "Trumpet", "Clarinet",
               "Violin", "Violin 1", "Violin 2", "Soprano"}
MID_VOICES = {"French Horn", "Alto Sax", "Alto Saxophone",
              "Viola", "Viola 1", "Viola 2", "Alto"}
LOW_VOICES = {"Bassoon", "Bass Clarinet", "Tenor Sax", "Tenor Saxophone",
              "Bari Sax", "Baritone Saxophone", "Trombone",
              "Baritone BC", "Baritone TC", "Euphonium BC", "Euphonium TC",
              "Baritone/Euphonium", "Tuba",
              "Cello", "Cello 1", "Cello 2", "String Bass",
              "Tenor", "Baritone", "Bass"}


def affinity_score(a, b):
    """How strongly two instruments belong together (0 = not alike).
    Same instrument > tight families (saxes together, double reeds together)
    > same voice register (high/mid/low) > same instrument family."""
    a = (a or "").strip()
    b = (b or "").strip()
    if not a or not b:
        return 0
    if a == b:
        return 100
    score = 0
    for group, pts in ((SAXES, 80), (DOUBLE_REEDS, 80),
                       (HIGH_VOICES, 60), (MID_VOICES, 60), (LOW_VOICES, 60)):
        if a in group and b in group:
            score = max(score, pts)
    if score < 40:
        for group in (set(BRASS), set(WOODWINDS), set(STRINGS), set(VOICES),
                      set(PERCUSSION)):
            if a in group and b in group:
                score = max(score, 40)
    return score


def instruments_alike(a, b):
    """True if two instruments belong together in a small mixed group."""
    return affinity_score(a, b) > 0


def family(instrument):
    i = (instrument or "").strip()
    if i in WOODWINDS:
        return "Woodwind"
    if i in BRASS:
        return "Brass"
    if i in PERCUSSION:
        return "Percussion"
    if i in STRINGS:
        return "String"
    if i in VOICES:
        return "Voice"
    return "Other"


def concert_rank(instrument):
    """Front-to-back rank; unknown instruments sit just ahead of percussion."""
    i = (instrument or "").strip()
    if i in CONCERT_ORDER:
        return CONCERT_ORDER.index(i)
    return len(CONCERT_ORDER) - 1  # just ahead of Percussion


# ── Jazz big-band layout ──────────────────────────────────────────────────────
# A jazz band seats differently from a concert band: saxes across the FRONT,
# trombones (and any other bass-clef players) behind them, trumpets (and any
# extra high winds/strings) in the BACK — with the rhythm section off to one
# side (usually stage left) and the whole band packed toward it, empty chairs
# left on the far (stage-right) side.  Middle-school reality is highly variable
# (any number per part, missing parts, doublers, even strings), so instruments
# are mapped to a ROW BAND rather than to fixed pro-chart seats.
JAZZ_RHYTHM = ["Piano", "Electric Piano", "Keyboard", "Guitar", "Bass Guitar",
               "Electric Bass", "String Bass", "Bass", "Drums", "Drum Set",
               "Drumset", "Percussion", "Vibraphone", "Vibes", "Aux Percussion"]
# Front row — the saxes, in the usual order (altos toward the middle, then
# tenors, bari on the end).
JAZZ_SAXES = ["Alto Sax", "Alto Saxophone", "Tenor Sax", "Tenor Saxophone",
              "Bari Sax", "Baritone Saxophone", "Soprano Sax"]
# Middle "bass-clef" row: trombones and anything else she puts there — French
# horns, baritones/euphoniums, tubas, bassoons, cellos, bass clarinet.
JAZZ_LOW = ["Trombone", "Bass Trombone", "French Horn", "Baritone BC",
            "Baritone TC", "Euphonium BC", "Euphonium TC", "Baritone/Euphonium",
            "Tuba", "Bassoon", "Bass Clarinet", "Cello", "Cello 1", "Cello 2"]
# Back row(s): trumpets and any extra high winds/strings (clarinet, flute, and
# in some years oboe/violin/viola — enough to spill into an added row).
JAZZ_HIGH = ["Trumpet", "Clarinet", "Flute", "Oboe", "Violin", "Violin 1",
             "Violin 2", "Viola", "Viola 1", "Viola 2"]

_JAZZ_ORDER = {"rhythm": JAZZ_RHYTHM, "sax": JAZZ_SAXES,
               "low": JAZZ_LOW, "high": JAZZ_HIGH}


def jazz_band(instrument):
    """Which jazz block an instrument belongs to: 'rhythm', 'sax', 'low', or
    'high'.  Anything unrecognized is treated as 'high' (it lands in the back
    overflow rows rather than being dropped)."""
    i = (instrument or "").strip()
    for band in ("rhythm", "sax", "low"):
        if i in _JAZZ_ORDER[band]:
            return band
    return "high"


def jazz_layout(instruments, high_rows=1, rhythm_side="left"):
    """Plan a jazz row layout from the instruments PRESENT.

    ``instruments`` is one entry PER PLAYER (repeats expected), so the row widths
    reflect how many students are actually on each part.  Returns
    ``(section_order, zones, side_zones, row_caps)`` to feed ``build_chart``
    (sections mode).  Rows are 0-based, front (audience side) = 0: row 0 = rhythm
    + saxes, row 1 = bass-clef, rows 2.. = trumpets/high winds.  ``high_rows`` is
    how many rows the back block may use (2 = "split the third row into a
    fourth").  Every section is packed toward ``rhythm_side`` so the empty chairs
    fall on the far side, and every row is the same width so the ragged,
    packed-to-one-side look comes through.
    """
    from collections import Counter
    counts = Counter(i for i in instruments if i)
    present = [i for i in dict.fromkeys(instruments) if i]      # de-dup, order
    bands = {"rhythm": [], "sax": [], "low": [], "high": []}
    for i in present:
        bands[jazz_band(i)].append(i)

    def ordered(band):
        pref = _JAZZ_ORDER[band]
        return sorted(bands[band],
                      key=lambda x: (pref.index(x) if x in pref else 999, x))

    def players(band):
        return sum(counts[i] for i in bands[band])

    rhythm, sax = ordered("rhythm"), ordered("sax")
    low, high = ordered("low"), ordered("high")
    high_rows = max(1, int(high_rows or 1))
    high_row_idx = list(range(2, 2 + high_rows))

    zones = {}
    for i in rhythm + sax:
        zones[i] = [0]
    for i in low:
        zones[i] = [1]
    for i in high:
        zones[i] = list(high_row_idx)                # spill across the back rows

    # Fill (and therefore left-to-right) order within a row: rhythm first so it
    # sits at the packed-side end, then saxes; low row and back rows by section.
    section_order = rhythm + sax + low + high
    side = "right" if rhythm_side == "right" else "left"
    side_zones = {i: side for i in section_order}

    # Uniform row width = the widest row's PLAYER count (+1 slack), so shorter
    # rows show empty chairs on the far side rather than re-centering.
    front = players("rhythm") + players("sax")
    mid = players("low")
    per_high = -(-players("high") // high_rows) if players("high") else 0   # ceil
    width = max(front, mid, per_high, 4) + 1
    row_caps = [width, width] + [width] * high_rows
    return section_order, zones, side_zones, row_caps


# ── Jazz band: PARTS, not instruments ─────────────────────────────────────
# A jazz chart is laid out by the part a player is covering, not by what they
# carry.  The front row reads T1 A2 A1 T2 B left to right, which is three
# different instruments interleaved -- no amount of grouping by instrument
# produces it.  Behind that, the parts are numbered outward from the lead:
# 2 1 3 4, so the lead sits second from the end and the section fans away.
#
# Middle school rarely has the book: a second row of "trombones" is whatever
# bass-clef players exist (baritone, bassoon, cello, the odd tuba) and the
# third row of "trumpets" picks up flutes, clarinets, the odd violin.  They
# still cover trombone and trumpet parts, so that is what they are labelled.
JAZZ_SAX_PARTS = ["A1", "A2", "T1", "T2", "B"]
JAZZ_RHYTHM_PARTS = ["Piano", "Guitar", "Bass", "Drums", "Vibes", "Aux"]
JAZZ_MAX_PART = 8

# Front rhythm shares the sax row; the other two stand behind with the brass.
_RHYTHM_FRONT = ("Piano", "Guitar")

# Left-to-right seating order within each row, as the ideal chart draws it.
_SAX_SEATING = ["T1", "A2", "A1", "T2", "B"]


def jazz_low_parts(n=JAZZ_MAX_PART):
    return ["Tbn %d" % i for i in range(1, n + 1)]


def jazz_high_parts(n=JAZZ_MAX_PART):
    return ["Tpt %d" % i for i in range(1, n + 1)]


def jazz_part_options():
    """Every part a player can be put on, in the order the picker shows them."""
    return (JAZZ_SAX_PARTS + jazz_low_parts(5) + jazz_high_parts(5)
            + JAZZ_RHYTHM_PARTS)


def jazz_part_band(part):
    """Which ROW a part belongs to: sax, low, high or rhythm.

    A2 and A6 are both alto parts.  The ideal chart only names five saxes, but
    a middle school front row runs to ten or twelve, and a part the ideal does
    not name is still a sax part -- reading it as "unknown" swept the extra
    altos into the trumpet row.
    """
    p = (part or "").strip()
    if p in JAZZ_RHYTHM_PARTS or p.startswith(("Vibes", "Aux")):
        return "rhythm"
    if p.startswith("Tbn"):
        return "low"
    if p.startswith("Tpt"):
        return "high"
    if _re.match(r"^[ATB]\s*\d*$", p):
        return "sax"
    return ""


def _numbered(part):
    m = _re.search(r"(\d+)\s*$", part or "")
    return int(m.group(1)) if m else 99


def jazz_seating_order(parts, band):
    """The parts of one row, left to right.

    Saxes read T1 A2 A1 T2 B.  A numbered section reads 2 1 3 4 -- the lead
    second from the end with the rest fanning away, which is what puts Trumpet
    1 behind Trombone 1 behind Alto 1.  Anything the ideal does not name (a
    sixth alto, an eighth trombone) goes on the end rather than being dropped.
    """
    parts = list(parts)
    if band == "sax":
        known = [p for p in _SAX_SEATING if p in parts]
        # A sixth alto goes on the end of the row, by part number, rather than
        # anywhere clever -- the front row simply gets longer.
        extra = sorted((p for p in parts if p not in _SAX_SEATING),
                       key=lambda x: (x[:1], _numbered(x)))
        return known + extra
    if band == "rhythm":
        known = [p for p in JAZZ_RHYTHM_PARTS if p in parts]
        return known + sorted(p for p in parts if p not in JAZZ_RHYTHM_PARTS)
    nums = sorted(parts, key=_numbered)
    if len(nums) >= 2:
        nums = [nums[1], nums[0]] + nums[2:]        # 2, 1, 3, 4 ...
    return nums


def jazz_auto_parts(players, taken=None):
    """A first guess at who is covering what, from the instruments present.

    Only a guess -- the teacher fixes it in the Jazz Band Setup window, and
    what they set is what gets used.  Guessing beats an empty table: most of a
    middle school band is already in the right place once the altos are altos.
    """
    from collections import defaultdict
    used = defaultdict(int)
    out = {}
    # Parts the teacher has already given out.  Guessing straight past them put
    # a second player on the lead trumpet part, and two players on one part
    # seat in an order nobody chose.
    spoken_for = {(t or "").strip() for t in (taken or ()) if (t or "").strip()}

    def take(prefix, key, first=None):
        """The next free part on a line, numbering past the end of the ideal
        rather than sitting two players on the same part -- and never one that
        is already spoken for."""
        for _ in range(64):
            i = used[key]
            used[key] += 1
            if first and i < len(first):
                part = first[i]
            elif not prefix:
                part = first[-1] if first else ""
            else:
                part = "%s%d" % (prefix, i + 1)
            if part not in spoken_for:
                spoken_for.add(part)
                return part
        return ""

    for p in players:
        inst = (p.get("instrument") or "").strip()
        band = jazz_band(inst)
        low = inst.lower()
        if band == "rhythm":
            if "piano" in low or "keyboard" in low:
                out[p["id"]] = "Piano"
            elif "guitar" in low:
                out[p["id"]] = "Guitar"
            elif "bass" in low and "clarinet" not in low and "sax" not in low:
                out[p["id"]] = "Bass"
            elif "vib" in low or "mallet" in low:
                out[p["id"]] = take("Vibes ", "vibes", first=["Vibes"])
            else:
                # Only one of them is on the kit.  A band with three
                # percussionists had all three guessed as Drums, which is a
                # guess nobody can use.
                out[p["id"]] = take("", "kit", first=["Drums", "Aux", "Aux"])
        elif band == "sax":
            if "tenor" in low:
                out[p["id"]] = take("T", "tenor")
            elif "bari" in low:
                out[p["id"]] = take("B", "bari", first=["B"])
            else:
                out[p["id"]] = take("A", "alto")
        elif band == "low":
            out[p["id"]] = take("Tbn ", "low")
        else:
            out[p["id"]] = take("Tpt ", "high")
    return out


def _split_evenly(seq, n):
    """``seq`` cut into ``n`` contiguous chunks of near-equal size, order kept.
    The earlier chunks take the extra, so the front row is the fuller one."""
    seq = list(seq)
    n = max(1, int(n))
    base, extra = divmod(len(seq), n)
    out, i = [], 0
    for j in range(n):
        take = base + (1 if j < extra else 0)
        out.append(seq[i:i + take])
        i += take
    return [c for c in out if c] or [[]]


def jazz_seating(players, parts, rhythm_side="left", high_rows=1):
    """Seat a jazz band by PART, as close to the ideal chart as the players allow.

    Returns ``(rows_of_players, row_caps, rhythm_players)``.  Row 0 is the
    saxes, row 1 the trombone parts, rows 2+ the trumpet parts, each numbered
    row offset so part 1 lines up behind the lead alto -- the one alignment
    every jazz chart draws.

    The rhythm section is NOT in the rows.  A piano is an instrument off to
    the side, not a chair in a row, and drawing the drummer amongst the
    trombones read as the drummer being a trombone.  They come back as their
    own list, in part order, for the renderer to stand beside the band on
    whichever side the teacher picked.

    ``rhythm_side`` also mirrors the rows: the winds pack toward the rhythm
    section, so any empty chairs land on the far side, not between the band
    and its rhythm players.
    """
    high_rows = max(1, int(high_rows or 1))
    by_part = {}
    for p in players:
        part = (parts or {}).get(p["id"]) or ""
        by_part.setdefault(part, []).append(p)

    def band_parts(band):
        return [q for q in by_part if jazz_part_band(q) == band]

    def seats(band):
        out = []
        for q in jazz_seating_order(band_parts(band), band):
            out.extend(by_part[q])
        return out

    rhythm = seats("rhythm")
    sax, low, high = seats("sax"), seats("low"), seats("high")
    unplaced = [p for p in players
                if not jazz_part_band((parts or {}).get(p["id"]))]
    high = high + unplaced          # never leave anybody off the chart

    # Where the brass blocks start, so the leads line up behind the lead alto.
    sax_order = jazz_seating_order(band_parts("sax"), "sax")
    lead_at = sax_order.index("A1") if "A1" in sax_order else 0
    lead_col = sum(len(by_part[q]) for q in sax_order[:lead_at])
    brass_start = max(lead_col - 1, 0)

    # Splitting the trumpet row keeps the part order: the first chunk sits in
    # FRONT of the second, so the lead trumpet stays in the nearer row and
    # stays lined up behind trombone 1.  Dealing every other player into each
    # row (which is what a stride does) put trumpet 1 behind trumpet 2.
    high_split = _split_evenly(high, high_rows) if high else []

    rows = [sax, [None] * brass_start + low]
    for chunk in high_split:
        rows.append([None] * brass_start + chunk)
    if not high_split:
        rows.append([])

    width = max((len(r) for r in rows), default=4)
    width = max(width, 4)
    rows = [r + [None] * (width - len(r)) for r in rows]
    if rhythm_side == "right":
        rows = [list(reversed(r)) for r in rows]
    return rows, [width] * len(rows), rhythm


def _by_last(students):
    return sorted(students, key=lambda s: ((s.get("last") or "").lower(),
                                           (s.get("first") or "").lower()))


def _grouped_by_instrument(students, order_key):
    """Return list of (instrument, [students]) groups, groups ordered by
    ``order_key(instrument)`` and members sorted by last name."""
    buckets = {}
    for s in students:
        buckets.setdefault((s.get("instrument") or "").strip(), []).append(s)
    ordered_instruments = sorted(buckets.keys(), key=lambda i: (order_key(i), i))
    return [(inst, _by_last(buckets[inst])) for inst in ordered_instruments]


# ── Sort strategies (classroom) ───────────────────────────────────────────────

def sort_alphabetical(students):
    return _by_last(students)


def sort_alphabetical_first(students):
    return sorted(students, key=lambda s: ((s.get("first") or "").lower(),
                                           (s.get("last") or "").lower()))


def sort_sections(students, order_key=None):
    """Whole sections together; small sections adjacent, large sections span
    consecutive seats (and therefore consecutive rows) but stay contiguous."""
    order_key = order_key or (lambda i: (i or "").lower())
    out = []
    for _inst, members in _grouped_by_instrument(students, order_key):
        out.extend(members)
    return out


def sort_small_groups(students, size=3, order_key=None):
    """Break each section into chunks of up to ``size`` and interleave the
    chunks so you get little 2-3 clusters of a like instrument rather than an
    entire section in one block."""
    order_key = order_key or (lambda i: (i or "").lower())
    groups = _grouped_by_instrument(students, order_key)
    # Build a queue of chunks per instrument.
    chunk_lists = []
    for _inst, members in groups:
        chunks = [members[i:i + size] for i in range(0, len(members), size)]
        chunk_lists.append(chunks)
    # Round-robin the chunks across instruments.
    out = []
    idx = 0
    remaining = sum(len(c) for c in chunk_lists)
    pos = [0] * len(chunk_lists)
    while remaining > 0:
        cl = chunk_lists[idx % len(chunk_lists)]
        p = pos[idx % len(chunk_lists)]
        if p < len(cl):
            out.extend(cl[p])
            pos[idx % len(chunk_lists)] += 1
            remaining -= 1
        idx += 1
    return out


def _cluster_sizes(n):
    """How to break a section of ``n`` into small groups.

    TWOS, with a single three when the number is odd.  The point of the layout
    is "two clarinets, then two trumpets, then two flutes" -- a pair is a buddy,
    while a three is most of a section and re-forms the block the exercise is
    meant to break up.  The old rule took threes first and only fell back to
    pairs at the end, so a section of ten came out 3+3+2+2 instead of 2x5.

    A section of one is left as a single here; the caller pairs it with a
    like-sounding section (the lone bassoon with the lone tuba, both low).
    """
    if n <= 0:
        return []
    if n == 1:
        return [1]
    if n % 2 == 0:
        return [2] * (n // 2)
    return [3] + [2] * ((n - 3) // 2)


def _deal_spread(per_inst, rng=None):
    """Deal clusters out so two groups of the SAME section land as far apart as
    the room allows.

    A plain round-robin only separates the first cluster of each section: with
    ten trumpets and one of everything else, the trumpet pairs came out in a
    run and looked exactly like a trumpet section again, which is the thing the
    layout exists to avoid.  Taking the section with the MOST clusters left
    each time (never the one just placed, if there is any alternative)
    interleaves them all the way to the end.
    """
    rng = rng or random.Random()
    remaining = {}
    order = []
    for inst, clusters in per_inst:
        key = inst or ""
        if key not in remaining:
            remaining[key] = []
            order.append(key)
        remaining[key].extend(clusters)

    out, prev = [], None
    while any(remaining[k] for k in order):
        live = [k for k in order if remaining[k]]
        rng.shuffle(live)                       # break ties differently each time
        pick = max((k for k in live if k != prev),
                   key=lambda k: len(remaining[k]), default=None)
        if pick is None:                        # only the previous section left
            pick = live[0]
        out.append(remaining[pick].pop(0))
        prev = pick
    return out


def small_group_clusters(students, order_key=None, seed=None):
    """Build 2–3 person clusters of like instruments that will sit TOGETHER.

    Each section is chunked into 2s and 3s.  A leftover single never sits
    alone: they join a 2-cluster of the same part family (trombone with
    baritones, tuba with a bari sax, horn with alto saxes…), pair up with
    another related single, or as a last resort join any small cluster.
    Clusters are then dealt round-robin across instruments for variety."""
    order_key = order_key or (lambda i: (i or "").lower())
    groups = _grouped_by_instrument(students, order_key)
    rng = random.Random(seed)

    per_inst = []      # [(inst, [cluster, ...])]
    singles = []
    for inst, members in groups:
        m = list(members)
        if seed is not None:
            rng.shuffle(m)
        sizes = _cluster_sizes(len(m))
        clusters = []
        for sz in sizes:
            chunk, m = m[:sz], m[sz:]
            if sz == 1:
                singles.append(chunk[0])
            else:
                clusters.append(chunk)
        if clusters:
            per_inst.append((inst, clusters))

    all_clusters = [c for _, cl in per_inst for c in cl]

    def alike(s, cluster):
        return any(instruments_alike(s.get("instrument"), m.get("instrument"))
                   for m in cluster)

    def same_inst(s, cluster):
        return any((m.get("instrument") or "") == (s.get("instrument") or "")
                   for m in cluster)

    # 1) Pair singles with EACH OTHER first — same instrument, then any like
    #    instrument.  A lone bari sax pairs with the lone tuba rather than
    #    tagging onto an already-formed clarinet group.
    def pair_pass(pool, same_only):
        pairs, remaining = [], []
        while pool:
            s = pool.pop(0)
            mi, best = None, 0
            for j, o in enumerate(pool):
                pts = affinity_score(s.get("instrument"), o.get("instrument"))
                if same_only and pts < 100:
                    continue
                if pts > best:
                    mi, best = j, pts
            if mi is not None:
                pairs.append([s, pool.pop(mi)])
            else:
                remaining.append(s)
        return pairs, remaining

    pairs, still = pair_pass(list(singles), True)
    more, still = pair_pass(still, False)
    for pair in pairs + more:
        all_clusters.append(pair)
        per_inst.append((pair[0].get("instrument") or "", [pair]))
    # 2) Remaining singles join the BEST-matching small cluster — own section
    #    beats a tight family (saxes, double reeds), which beats a voice-
    #    register match, which beats a generic family match.  A lone tuba
    #    prefers the [bass clarinet, bari sax] pair (low voices) over a
    #    trumpet pair (merely brass).
    def cluster_score(s, c):
        return max((affinity_score(s.get("instrument"), m.get("instrument"))
                    for m in c), default=0)

    rest = []
    for s in still:
        cands = [c for c in all_clusters if len(c) <= 3 and cluster_score(s, c) > 0]
        cands.sort(key=lambda c: (-cluster_score(s, c), len(c)))
        if cands:
            cands[0].append(s)
        else:
            rest.append(s)
    # 3) Last resort: join a like cluster of any size, then any 2-cluster,
    #    then the smallest cluster — never sit alone.
    for s in rest:
        target = (next((c for c in all_clusters if alike(s, c) and len(c) < 4), None)
                  or next((c for c in all_clusters if len(c) == 2), None))
        if target is None and all_clusters:
            target = min(all_clusters, key=len)
        if target is not None:
            target.append(s)
        else:
            solo = [s]
            all_clusters.append(solo)
            per_inst.append((s.get("instrument") or "", [solo]))

    # Spread the clusters so a big section's pairs do not end up in a run.
    return _deal_spread(per_inst, rng)


def layout_clusters(clusters, row_caps):
    """Pack whole clusters into rows — a cluster NEVER splits across a row
    boundary.  If the next cluster doesn't fit the seats left in a row, a
    smaller cluster from later in the queue is used; failing that, the seats
    stay empty.  Clusters containing an edge-accommodation student start a row
    (so that student sits on the outside), and an occupied trailing row is
    never left with fewer than 4 students when an earlier row can spare a
    cluster.  Returns (rows, unseated)."""
    R = len(row_caps)

    def edge_first(c):
        return sorted(c, key=lambda m: 0 if (m and m.get("pref") == "edge") else 1)

    def has_edge(c):
        return any(m and m.get("pref") == "edge" for m in c)

    queue = [edge_first(c) for c in clusters]
    rows_cl = [[] for _ in range(R)]
    used = [0] * R
    for r in range(R):
        while queue:
            rem = row_caps[r] - used[r]
            idx = None
            if used[r] == 0:               # row start — prefer an edge cluster
                idx = next((i for i, c in enumerate(queue)
                            if has_edge(c) and len(c) <= rem), None)
            if idx is None:
                idx = next((i for i, c in enumerate(queue) if len(c) <= rem), None)
            if idx is None:
                break                      # leave the row's edge seats empty
            c = queue.pop(idx)
            rows_cl[r].append(c)
            used[r] += len(c)
    unseated = [s for c in queue for s in c]

    # Never leave the last occupied row with fewer than 4 students if an
    # earlier row can spare its final cluster.
    occupied = [r for r in range(R) if used[r]]
    if occupied:
        last = occupied[-1]
        for _ in range(4):
            if not (0 < used[last] < 4):
                break
            donor = next((r for r in reversed(occupied) if r < last
                          and len(rows_cl[r]) > 1
                          and used[r] - len(rows_cl[r][-1]) >= 4
                          and used[last] + len(rows_cl[r][-1]) <= row_caps[last]),
                         None)
            if donor is None:
                break
            c = rows_cl[donor].pop()
            used[donor] -= len(c)
            rows_cl[last].append(c)
            used[last] += len(c)

    grid = [[None] * row_caps[r] for r in range(R)]
    for r in range(R):
        pos = 0
        for c in rows_cl[r]:
            for s in c:
                grid[r][pos] = s
                pos += 1

    # Last resort: a chair that is free beats a group that is whole.  A cluster
    # of three will not split, so with two seats left over the room showed two
    # empty chairs AND told the teacher two students did not fit -- which is
    # true of the group but plainly untrue of the chairs.  Keeping the cluster
    # together is a preference; every child having somewhere to sit is not.
    if unseated:
        still = []
        for st in unseated:
            spot = next(((r, c) for r in range(R)
                         for c in range(row_caps[r]) if grid[r][c] is None),
                        None)
            if spot is None:
                still.append(st)
            else:
                grid[spot[0]][spot[1]] = st
        unseated = still
    return grid, unseated


def sort_full_shuffle(students, seed=None, order_key=None):
    """Spread instruments out so neighbours differ as much as possible:
    deal one student from each section in rotation (largest sections first so
    they don't clump at the end)."""
    order_key = order_key or (lambda i: (i or "").lower())
    groups = _grouped_by_instrument(students, order_key)
    rng = random.Random(seed)
    queues = []
    for _inst, members in groups:
        m = list(members)
        rng.shuffle(m)
        queues.append(m)
    # Largest sections first each round so they deplete evenly.
    out = []
    while any(queues):
        queues.sort(key=len, reverse=True)
        for q in queues:
            if q:
                out.append(q.pop(0))
    return out


def order_students(students, mode, concert=False, seed=None):
    """Dispatch to a sort strategy.  When ``concert`` is True, sections are
    ordered by the standard concert front-to-back ranking."""
    order_key = concert_rank if concert else None
    if mode == "alphabetical_first":
        return sort_alphabetical_first(students)
    if mode == "alphabetical":
        return sort_alphabetical(students)
    if mode == "sections":
        return sort_sections(students, order_key)
    if mode == "small_groups":
        return sort_small_groups(students, order_key=order_key)
    if mode == "full_shuffle":
        return sort_full_shuffle(students, seed=seed, order_key=order_key)
    return sort_alphabetical(students)


# ── Row capacities & layout ───────────────────────────────────────────────────

def parse_row_caps(spec, default=8):
    """Turn '8' or '8,10,12,13' into a list of ints.  Blank -> [default]."""
    if isinstance(spec, (list, tuple)):
        caps = [int(x) for x in spec if int(x) > 0]
        return caps or [default]
    caps = []
    for part in str(spec or "").replace(";", ",").split(","):
        part = part.strip()
        if part.isdigit() and int(part) > 0:
            caps.append(int(part))
    return caps or [default]


def layout_rows(ordered, row_caps):
    """Fill exactly ``len(row_caps)`` rows (one per specified capacity) — the
    tool never invents extra rows.  Returns (rows, unseated) where ``unseated``
    is any student who did not fit in the room as configured.

    A trailing row is never left with fewer than 4 students: seats are pulled
    back from the row in front (order preserved) until it has at least 4."""
    rows = []
    i = 0
    for cap in row_caps:
        rows.append(ordered[i:i + cap])
        i += cap
    unseated = ordered[i:]
    occupied = [r for r, row in enumerate(rows) if row]
    if occupied:
        last = occupied[-1]
        while 0 < len(rows[last]) < 4 and last > 0 and len(rows[last - 1]) > 4:
            rows[last].insert(0, rows[last - 1].pop())
    return rows, unseated


def row_capacity(row_caps, r):
    return row_caps[r] if r < len(row_caps) else row_caps[-1]


# ── Post-processing: IEP/504 pins, conflicts, tuba centering ──────────────────

def _flatten(rows):
    return [s for row in rows for s in row if s]


def apply_row_pins(rows, row_caps):
    """Move students with pref 'front' into the first row and 'back' into the
    last row, swapping with an unpinned occupant.  Mutates and returns rows.
    Handles both ragged rows and grid rows that contain empty (None) seats."""
    if not rows:
        return rows

    def move_to_row(student, target_r):
        # Find current position.
        for r, row in enumerate(rows):
            if student in row:
                if r == target_r:
                    return
                cur_r, cur_c = r, row.index(student)
                break
        else:
            return
        target = rows[target_r]
        cap = row_capacity(row_caps, target_r)
        # Prefer an empty (None) seat already in the target row.
        for c, occ in enumerate(target):
            if occ is None:
                target[c] = student
                rows[cur_r][cur_c] = None
                return
        # Or append if the ragged row still has room.
        if len(target) < cap:
            target.append(student)
            del rows[cur_r][cur_c]
            return
        # Otherwise swap with an unpinned occupant of the target row.
        for c, occ in enumerate(target):
            if occ and not occ.get("pref") and not occ.get("reserved"):
                target[c], rows[cur_r][cur_c] = student, occ
                return

    last = len(rows) - 1
    for s in _flatten(rows):
        if s.get("pref") == "front":
            move_to_row(s, 0)
    for s in _flatten(rows):
        if s.get("pref") == "back":
            move_to_row(s, last)
    return rows


def apply_edge_pins(rows):
    """Move students with pref 'edge' to an outside end of a row (useful for a
    student with difficult social skills, so fewer neighbours are next to them).
    Prefers left/right ends that aren't already held by another pinned student."""
    edge_students = [s for row in rows for s in row
                     if s and not s.get("reserved") and s.get("pref") == "edge"]
    if not edge_students:
        return rows

    def pos(student):
        for r, row in enumerate(rows):
            if student in row:
                return r, row.index(student)
        return None

    # Candidate edge seats: leftmost and rightmost occupied seat of each row.
    edges = []
    for r, row in enumerate(rows):
        if row:
            edges.append((r, 0))
            if len(row) > 1:
                edges.append((r, len(row) - 1))
    used = set()
    for s in edge_students:
        p = pos(s)
        if not p:
            continue
        pr, pc = p
        if pc == 0 or pc == len(rows[pr]) - 1:
            used.add((pr, pc))
            continue
        for e in edges:
            if e in used:
                continue
            er, ec = e
            if ec >= len(rows[er]):
                continue
            occ = rows[er][ec]
            if occ is not None and (occ.get("pref") or occ.get("reserved")):
                continue
            rows[er][ec], rows[pr][pc] = rows[pr][pc], rows[er][ec]
            used.add(e)
            break
    return rows


def separate_conflicts(rows, conflicts, max_passes=8, min_gap=3):
    """Keep "keep apart" students separated by a buffer of at least two other
    students in the same row (column distance >= ``min_gap``).

    Repair swaps stay INSIDE the student's own section — two alto saxes trade
    places so the pair lands at opposite ends of the sax row — so nobody gets
    flung into another instrument's territory.  Returns (rows, unresolved)."""
    if not conflicts:
        return rows, []

    def key(s):
        return (s.get("name") or "").lower() if s else None

    def find_bad():
        pos = {}
        for r, row in enumerate(rows):
            for c, x in enumerate(row):
                k = key(x)
                if k and not x.get("reserved"):
                    pos[k] = (r, c)
        bad = []
        for pair in conflicts:
            ns = sorted(pair)
            if len(ns) < 2:
                continue
            a, b = pos.get(ns[0]), pos.get(ns[1])
            if a and b and a[0] == b[0] and abs(a[1] - b[1]) < min_gap:
                bad.append((ns[0], ns[1], a, b))
        return bad

    def movable(x):
        return bool(x and not x.get("reserved") and not x.get("pref")
                    and not int(x.get("buffer") or 0))

    for _ in range(max_passes):
        bad = find_bad()
        if not bad:
            return rows, []
        progressed = False
        for _na, _nb, pa, pb in bad:
            moved = False
            # Try moving either of the pair; only same-instrument swaps.
            for (mr, mc), anchor in ((pb, pa), (pa, pb)):
                mover = rows[mr][mc]
                if not movable(mover):
                    continue
                inst = (mover.get("instrument") or "")
                cands = []
                for r2, row2 in enumerate(rows):
                    for c2, occ in enumerate(row2):
                        if (r2, c2) == (mr, mc) or not movable(occ):
                            continue
                        if (occ.get("instrument") or "") != inst:
                            continue
                        if r2 == anchor[0] and abs(c2 - anchor[1]) < min_gap:
                            continue  # still too close to the other student
                        dist = abs(r2 - anchor[0]) * 100 + abs(c2 - anchor[1])
                        cands.append((dist, r2, c2))
                cands.sort(reverse=True)     # farthest from the other student first
                before = len(bad)
                for _d, r2, c2 in cands:
                    rows[mr][mc], rows[r2][c2] = rows[r2][c2], rows[mr][mc]
                    if len(find_bad()) < before:
                        moved = True
                        break
                    rows[mr][mc], rows[r2][c2] = rows[r2][c2], rows[mr][mc]
                if moved:
                    break
            if moved:
                progressed = True
        if not progressed:
            break

    remaining = []
    seen = set()
    for na, nb, _pa, _pb in find_bad():
        if (na, nb) not in seen:
            seen.add((na, nb))
            remaining.append((na, nb))
    return rows, remaining


def center_instrument(rows, instrument):
    """Nudge players of ``instrument`` toward the center of their row's
    occupants (used for tuba in the back row).  Works even when the row has
    empty seats — the occupants are re-dealt into the same occupied positions,
    so gaps and reserved seats stay exactly where they were."""
    for row in rows:
        idxs = [c for c, s in enumerate(row) if s and not s.get("reserved")]
        occ = [row[c] for c in idxs]
        movers = [s for s in occ if (s.get("instrument") or "") == instrument]
        if not movers or len(occ) < 3:
            continue
        others = [s for s in occ if (s.get("instrument") or "") != instrument]
        mid = len(others) // 2
        rearranged = others[:mid] + movers + others[mid:]
        for c, s in zip(idxs, rearranged):
            row[c] = s
    return rows


# ── The nine zones a teacher names ────────────────────────────────────────
# Meagan's vocabulary, from her own diagrams, widened to three depths after she
# sent a college wind-band chart laid out in concentric rings: the room splits
# front / middle / back, and each of those into stage right / center / stage
# left.  Nine is the most that still fits in a head -- a 3x3 grid you can read
# off a legend -- while giving the inner ring / middle ring / outer ring
# distinction a real band chart needs.
#
# STAGE right is the AUDIENCE's left, which is the left of the picture when the
# front of the room is drawn at the top -- so zones 1/4/7 map to side "left"
# here, where left/right have always meant audience view.  Flipping the room to
# front-at-bottom rotates the whole picture, so a zone stays the same physical
# corner and simply appears on the other side of the page.
ZONE_LABELS = {
    1: "1 - front, stage right",
    2: "2 - front, stage center",
    3: "3 - front, stage left",
    4: "4 - middle, stage right",
    5: "5 - middle, stage center",
    6: "6 - middle, stage left",
    7: "7 - back, stage right",
    8: "8 - back, stage center",
    9: "9 - back, stage left",
}
ZONE_DEPTHS = ("front", "middle", "back")
ZONE_SIDES = ("stage right", "stage center", "stage left")
_ZONE_SIDE = {z: ("left", "center", "right")[(z - 1) % 3] for z in range(1, 10)}

# Charts saved when there were only six zones: 1-3 were the front HALF and 4-6
# the back half, so the back three move to the new back three and the front
# three keep their numbers.
ZONE_MIGRATION_6_TO_9 = {1: 1, 2: 2, 3: 3, 4: 7, 5: 8, 6: 9}


def _depth_bands(n_rows):
    """The rows making up the front, middle and back thirds of the room.

    Worked out from the CURRENT row count, so a chart that grows from four rows
    to six keeps meaning the same thing: zone 7 is still "the back", not
    "row 4".  A room too shallow to have three distinct depths lets the bands
    share rows rather than leaving a zone that seats nobody.
    """
    if n_rows <= 0:
        return ([], [], [])
    base, extra = divmod(n_rows, 3)
    sizes = [base + (1 if i < extra else 0) for i in range(3)]
    bands, i = [], 0
    for sz in sizes:
        bands.append(list(range(i, i + sz)))
        i += sz
    for j in range(3):
        if not bands[j]:
            bands[j] = (bands[j - 1] if j and bands[j - 1]
                        else next((b for b in bands if b), []))
    return tuple(bands)


def zone_rows_side(zone, n_rows):
    """``([0-based rows], side)`` for one of the nine zones."""
    try:
        zone = int(zone)
    except (TypeError, ValueError):
        return ([], "left")
    if zone not in _ZONE_SIDE or n_rows <= 0:
        return ([], "left")
    bands = _depth_bands(n_rows)
    rows = bands[(zone - 1) // 3]
    return (list(rows) or list(range(n_rows)), _ZONE_SIDE[zone])


def zone_columns(zone, cap):
    """The seats across a row that a zone covers: its third of the room.

    A zone is a BOX in the diagram, not a whole row -- stage right is the left
    third, stage center the middle third, stage left the right third.  Without
    this a big first section filled the entire front row and the sections meant
    to sit beside it were pushed to whatever was left, so the violas ended up on
    the far side of the room from the middle wedge they were assigned.

    A section too big for its third is not left standing: it takes its third
    first and spills outward from there (see layout_section_blocks).
    """
    try:
        zone = int(zone)
    except (TypeError, ValueError):
        return list(range(cap))
    if zone not in _ZONE_SIDE or cap <= 0:
        return list(range(cap))
    side = _ZONE_SIDE[zone]
    a = cap // 3
    b = cap - a                          # the middle third gets the remainder
    if side == "left":
        return list(range(0, a))
    if side == "right":
        return list(range(b, cap))
    return list(range(a, b))


def zone_capacity(zone, row_caps):
    """How many seats a zone actually holds, for the row shape in force."""
    rows, _side = zone_rows_side(zone, len(row_caps))
    return sum(len(zone_columns(zone, row_capacity(row_caps, r))) for r in rows)


def random_zone_assignment(sections, counts, row_caps, rng=None):
    """Put every section in a zone, at random -- what "shuffle section
    placement" means.

    Truly random, with one concession to the room: the biggest sections choose
    first, from the zones that can still hold them.  Without that a big section
    could draw the middle wedge of the front half, overflow it, and spill
    across everything else, which reads as the shuffle being broken rather than
    as the room being full.
    """
    rng = rng or random.Random()
    cap = {z: zone_capacity(z, row_caps) for z in ZONE_LABELS}
    left = dict(cap)
    out = {}
    for name in sorted(sections, key=lambda s: -counts.get(s, 0)):
        need = max(1, counts.get(name, 1))
        zs = list(ZONE_LABELS)
        rng.shuffle(zs)                       # random order among equals
        fits = [z for z in zs if left[z] >= need] or zs
        # Random, but from the EMPTIEST zones.  Purely random draws piled four
        # sections into the back half and left the front two rows with three
        # players between them -- a room with a hole in it, which reads as the
        # shuffle being broken.  Choosing among the emptiest keeps every click
        # different while still filling the room.
        fits.sort(key=lambda z: -left[z])
        top = [z for z in fits if left[z] == left[fits[0]]]
        pool = top if len(top) > 1 else fits[:2]
        z = rng.choice(pool)
        out[name] = z
        left[z] -= need
    return out


def layout_section_blocks(groups, row_caps, target_width=4, zones=None,
                          side_zones=None, zone_cols=None, anchors=None):
    """Lay out sections as contiguous runs (never scattering).  ``zones`` locks a
    section to specific rows; ``side_zones``
    ({instrument: 'left'|'center'|'right'}) packs a section against one side of
    the room, or out from the middle.  Left and right are AUDIENCE view, which
    is stage right and stage left respectively -- the seating chart's zones 1-6
    are built out of these two controls.

    ``zones`` optionally locks a section to specific rows: ``{instrument: [row
    indices]}`` (0-based).  Zoned sections are placed in their rows first; the
    rest fill the remaining space.

    ``groups`` is an ordered list of (instrument, [students]).  Returns
    (rows, unseated) where rows are fixed-width grids (with None for empty seats)
    and ``unseated`` is anyone who didn't fit the room as configured."""
    zones = zones or {}
    side_zones = side_zones or {}
    zone_cols = zone_cols or {}
    anchors = anchors or {}
    R = len(row_caps)
    caps = [row_caps[r] for r in range(R)]
    grid = [[None] * caps[r] for r in range(R)]
    unseated = []

    def col_order(cap, side):
        """Which seats a section claims first, and in what order.

        'center' works OUT FROM THE MIDDLE, which is what a middle wedge is:
        the violas sit either side of the center line, not packed against it.
        """
        if side == "right":
            return list(range(cap - 1, -1, -1))
        if side == "center":
            middle = (cap - 1) / 2
            return sorted(range(cap), key=lambda c: (abs(c - middle), c))
        return list(range(cap))

    def fill(members, allowed_rows, side="left", only_cols=None, hug=None,
             placed=None):
        """Fill members into empty seats of ``allowed_rows`` in reading order
        (row by row).  ``side`` decides where in each row the section starts:
        the audience-left end, the audience-right end, or the middle.
        ``only_cols`` restricts it to a zone's own third of the room.  ``hug``
        is {row: [columns this section already holds]} -- the overflow then
        takes the seats NEAREST its own block instead of the first free seat in
        the row, which is what stops a section being split by whoever happens
        to be sitting between.  ``placed`` collects the seats used.  Sections
        land in a CONTIGUOUS run, never scattering.  Returns leftovers."""
        leftover = list(members)
        for r in allowed_rows:
            if r < 0 or r >= R:
                continue
            cols = col_order(caps[r], side)
            if only_cols is None and hug and hug.get(r):
                anchor = hug[r]
                cols = sorted(range(caps[r]),
                              key=lambda c: (min(abs(c - a) for a in anchor), c))
            if only_cols is not None:
                # Inside a zone, fill STRICTLY along the row so each section
                # lands as one run.  Working outward from the middle (which is
                # what a centered section wants on its own) made the second
                # section in a zone wrap around the first: clarinets took the
                # two middle seats and the trombones ended up one on each side
                # of them.  compact_rows centers the row afterwards, so
                # sequential order here costs nothing.
                allowed = sorted(only_cols(caps[r]))
                cols = allowed[::-1] if side == "right" else allowed
            for c in cols:
                if not leftover:
                    return leftover
                if grid[r][c] is None:
                    grid[r][c] = leftover.pop(0)
                    if placed is not None:
                        placed.append((r, c))
        return leftover

    all_rows = list(range(R))
    # 1) Row-zoned sections claim their rows (respecting a stage side too,
    #    e.g. string basses in the back row toward stage right).
    # 1a) Every zoned section claims its OWN third of its own rows first, so
    #     one big section cannot swallow the row that its neighbours were
    #     assigned to sit in.
    spill = []
    # A section pinned to a CORNER claims its seats before anything else, or a
    # neighbour assigned to the same end of the room gets there first and the
    # corner section lands in the middle of it -- the cellos came out split in
    # two around the basses.
    zoned = [g for g in groups if g[0] in zones]
    zoned.sort(key=lambda g: 0 if g[0] in anchors else 1)
    for inst, members in zoned:
        cols = zone_cols.get(inst)
        side = side_zones.get(inst, "left")
        rows_for = sorted(zones[inst])
        # Prefer a row of the zone that can take the WHOLE section.  Filling
        # strictly front-to-back spilled the last one or two players into
        # the row behind, and a row holding one person with the rest of it
        # empty is the "giant gap" a teacher sees -- worse than the section
        # simply sitting a row further back, together.
        whole = None
        if len(members) > 1:
            for r in rows_for:
                if r < 0 or r >= R:
                    continue
                room = [c for c in (cols(caps[r]) if cols else range(caps[r]))
                        if grid[r][c] is None]
                if len(room) >= len(members):
                    whole = r
                    break
        target = [whole] if whole is not None else rows_for
        seats_used = []
        left = fill(list(members), target, side=side, only_cols=cols,
                    placed=seats_used)
        spill.append((inst, left, seats_used))
    # 1b) Anything that did not fit its third spills outward: the rest of its
    #     own rows, and only then the room at large.
    for inst, left, seats_used in spill:
        if not left:
            continue
        hug = {}
        for r, c in seats_used:
            hug.setdefault(r, []).append(c)
        left = fill(left, sorted(zones[inst]),
                    side=side_zones.get(inst, "left"), hug=hug)
        unseated.extend(fill(left, all_rows, hug=hug))
    # 2) Side-assigned sections claim their end (or the middle) of every row.
    #    Center goes FIRST: it is the wedge the outer sections pack against, and
    #    filling it after them would find the middle already taken.
    for want in ("center", "left", "right"):
        for inst, members in groups:
            if inst not in zones and side_zones.get(inst) == want:
                unseated.extend(fill(list(members), all_rows, side=want))
    # 3) Everyone else flows contiguously into the middle, front to back, with
    #    widow/orphan control: rather than strand one or two players past a row
    #    edge, leave those edge seats empty and keep the whole section together
    #    in the next row — whenever the room can spare the seats.
    flow = [(inst, list(members)) for inst, members in groups
            if inst not in zones and inst not in side_zones and members]
    blocked = [set() for _ in range(R)]

    def open_cols(r):
        return [c for c in range(caps[r]) if grid[r][c] is None and c not in blocked[r]]

    def free_total():
        return sum(len(open_cols(r)) for r in range(R))

    total_left = sum(len(m) for _, m in flow)
    for _inst, members in flow:
        while members:
            r0 = next((r for r in range(R) if open_cols(r)), None)
            if r0 is None:
                unseated.extend(members)
                total_left -= len(members)
                members = []
                break
            cols = open_cols(r0)
            n = len(members)
            if n <= len(cols):
                for c in cols[:n]:
                    grid[r0][c] = members.pop(0)
                total_left -= n
                break
            head, tail = len(cols), n - len(cols)
            row_started = (len(cols) < caps[r0]
                           and any(grid[r0][c] is not None for c in range(caps[r0])))
            fits_whole_later = any(len(open_cols(rr)) >= n for rr in range(r0 + 1, R))
            if row_started and fits_whole_later and free_total() - head >= total_left:
                # Abandon this row's remainder; seat the whole section together below.
                blocked[r0].update(cols)
                continue
            if 0 < tail <= 2 and head - (3 - tail) >= 3 and free_total() - (3 - tail) >= total_left:
                # Shift the split point so no 1–2 player orphan spills over.
                use = head - (3 - tail)
                for c in cols[:use]:
                    grid[r0][c] = members.pop(0)
                blocked[r0].update(cols[use:])
                total_left -= use
                continue
            for c in cols:                       # ordinary split (big section)
                grid[r0][c] = members.pop(0)
            total_left -= head
    return grid, unseated


def _section_groups(students, section_order, shuffle_members, shuffle_sections, seed):
    """Group students by instrument and order the groups.

    Group order: a custom ``section_order`` wins; otherwise the musical family
    order (concert ranking) so related instruments stay adjacent (low brass
    together, etc.).  ``shuffle_members`` randomizes who sits by whom inside each
    section (keeping the section in the same area).  ``shuffle_sections``
    randomizes which section is placed where (so low brass could land up front).
    """
    if section_order:
        rank = {name: i for i, name in enumerate(section_order)}
        order_key = lambda i: (rank.get(i, len(section_order)), i)
    else:
        order_key = concert_rank
    groups = _grouped_by_instrument(students, order_key)
    rng = random.Random(seed)
    if shuffle_members:
        groups = [(inst, _shuffled(members, rng)) for inst, members in groups]
    if shuffle_sections:
        # An explicit shuffle always wins over a saved section order — the
        # user asked for sections to actually move.
        rng.shuffle(groups)
    return groups


def _shuffled(seq, rng):
    out = list(seq)
    rng.shuffle(out)
    return out


def _reserved():
    return {"reserved": True, "name": "", "instrument": "", "pref": None}


def regroup_rows(rows):
    """Make every section contiguous within its own row.

    The zones are thirds, and a section bigger than its third has to overflow
    somewhere -- with its neighbours already seated, the overflow lands past
    them and the section comes out in two pieces with somebody else in the
    middle.  Four first violins in a three-seat wedge came out as three, two
    violas, and a stray fourth violin.

    Nothing moves rows and no seat is added or removed: the same chairs stay
    occupied, and the people in them are reordered so that each section is one
    run.  Sections keep the left-to-right order they were placed in, so a
    section seated stage right of another still is.
    """
    out = []
    for row in rows:
        order, buckets = [], {}
        for x in row:
            if x is None:
                continue
            key = (x.get("instrument") or "") if isinstance(x, dict) else ""
            if key not in buckets:
                buckets[key] = []
                order.append(key)
            buckets[key].append(x)
        seq = [x for key in order for x in buckets[key]]
        new, i = list(row), 0
        for c, seat in enumerate(row):
            if seat is not None:
                new[c] = seq[i]
                i += 1
        out.append(new)
    return out


def _row_anchor(people, anchors):
    """Which end of the row a compacted block should hold on to.

    Only a DELIBERATE corner holds: the string basses pinned to the back corner
    by their own check box.  Anything else centers.

    This used to look at the zone SIDE, which anchored any row that happened to
    hold only right-hand sections -- so a row with three players in it was
    pushed against the wall with seven empty chairs beside them, which is the
    giant gap this whole exercise is about.  A zone says which third of the
    room a section belongs to, not that it should hug the wall when the room is
    half empty.
    """
    if not anchors:
        return "center"
    sides = set()
    for x in people:
        if isinstance(x, dict):
            side = anchors.get((x.get("instrument") or ""))
            if side is None:
                return "center"
            sides.add(side)
    if len(sides) == 1:
        return sides.pop()
    return "center"


# A row wider than this is hard to read and hard to walk into.  Used as the
# point at which "fit everybody" starts adding rows instead of widening.
COMFORTABLE_ROW = 12
COMFORTABLE_MIN_ROW = 6     # below this a row is not worth having
MAX_ROWS = 6                # what the Configuration window can show and edit


def optimize_row_caps(n_seats, current_caps, max_rows=MAX_ROWS, max_width=None):
    """The smallest room that seats ``n_seats``, shaped like the one they have.

    Two jobs at once, which is why it is one button: add chairs (and rows) when
    the ensemble does not fit -- combining two bands for one concert doubles
    the room overnight -- and take away chairs nobody is sitting in, so the
    formation is not full of holes.

    The PROPORTIONS of the current rows are kept, so a room set up 8/10/12/13
    grows and shrinks as a concert arc rather than being flattened into equal
    rows.  New rows are added at the back, and only once the existing rows have
    reached a comfortable width -- widening forever gives a row nobody at the
    end can hear from.
    """
    shape = [c for c in (current_caps or []) if c > 0] or [8]
    n_seats = max(0, int(n_seats))
    if not n_seats:
        return shape[:1]
    max_width = max_width or max(max(shape), COMFORTABLE_ROW)

    rows = len(shape)
    while rows < max_rows and rows * max_width < n_seats:
        rows += 1
    # ...and the other way: six players do not need four rows of one or two.
    # A row is worth having at about six in it.
    rows = max(1, min(rows, -(-n_seats // COMFORTABLE_MIN_ROW)))
    if rows > len(shape):
        shape = shape + [shape[-1]] * (rows - len(shape))   # new rows at the back
    elif rows < len(shape):
        shape = shape[:rows]

    total = sum(shape) or 1
    caps = [max(1, int(round(n_seats * c / float(total)))) for c in shape]

    # Round-off: top up from the back, trim from the widest.
    i = 0
    while sum(caps) < n_seats:
        caps[len(caps) - 1 - (i % len(caps))] += 1
        i += 1
    while sum(caps) > n_seats:
        j = max(range(len(caps)), key=lambda k: caps[k])
        if caps[j] <= 1:
            break
        caps[j] -= 1

    # A row nobody needs is not a row.
    while len(caps) > 1 and sum(caps[:-1]) >= n_seats:
        caps.pop()
    return caps


def split_percussion(perc, width):
    """Wrap a long percussion line into balanced rows.

    Nineteen percussionists in one straight line is wider than the band in
    front of them and reads as a wall rather than a section.  Split evenly, so
    two rows come out 10 and 9 rather than 12 and 7.
    """
    perc = list(perc or [])
    n = len(perc)
    if n == 0:
        return []
    if width <= 0 or n <= width:
        return [perc]
    k = -(-n // width)                       # ceil
    base, extra = divmod(n, k)
    out, i = [], 0
    for j in range(k):
        take = base + (1 if j < extra else 0)
        out.append(perc[i:i + take])
        i += take
    return out


def compact_rows(rows, row_caps, anchors=None):
    """Close the gaps INSIDE the ensemble, leaving the empty chairs at the ends.

    Zones are thirds of the room, so a section that does not fill its third
    leaves a hole -- three trumpets stage right, three flutes stage left and
    four empty chairs between them, in the middle of the band.  Nobody wants an
    empty chair there; they want it on the outside, or at the back.

    Each row keeps its LEFT-TO-RIGHT ORDER, so the arrangement the zones
    produced survives: whoever was stage right of whom still is.  The block is
    then centered, which splits the spare chairs between the two outside ends --
    unless every player in the row was deliberately pinned to a corner (see
    ``_row_anchor``), which only the string basses are.

    A row that ends up completely empty is pulled out from under the rows
    behind it, so the ensemble never has a blank row in front of it -- but only
    when every row still fits where it lands, since rows can have different
    widths.
    """
    n_rows = len(rows)
    caps = [row_capacity(row_caps, r) for r in range(n_rows)]
    people = [[x for x in row if x is not None] for row in rows]

    # No empty row in front of an occupied one.
    kept = [p for p in people if p]
    if kept and len(kept) < n_rows:
        if all(len(kept[i]) <= caps[i] for i in range(len(kept))):
            people = kept + [[] for _ in range(n_rows - len(kept))]

    out = []
    for r, p in enumerate(people):
        cap = caps[r]
        row = [None] * cap
        anchor = _row_anchor(p, anchors)
        if anchor == "left":
            start = 0
        elif anchor == "right":
            start = max(0, cap - len(p))
        else:
            start = max(0, (cap - len(p)) // 2)
        for i, occupant in enumerate(p[:cap]):
            row[start + i] = occupant
        out.append(row)
    return out


def _pad_to_grid(rows, row_caps):
    """Pad every row out to its capacity with empty (None) seats so all later
    passes work on a fixed-width grid."""
    out = []
    for r, row in enumerate(rows):
        cap = row_capacity(row_caps, r)
        rr = list(row) + [None] * (cap - len(row))
        out.append(rr[:cap] if cap < len(rr) else rr)
    return out


def _open_right(row, tc):
    """Open seat ``tc`` by sliding occupants right into the nearest empty seat at
    or after ``tc``.  Seats left of ``tc`` (incl. the buffered student) don't
    move, so nobody is ejected far from their section.  Returns True on success."""
    if tc < 0 or tc >= len(row):
        return False
    for e in range(tc, len(row)):
        if row[e] is None:
            for i in range(e, tc, -1):
                row[i] = row[i - 1]
            row[tc] = _reserved()
            return True
    return False


def _open_left(row, tc):
    """Open seat ``tc`` by sliding occupants left into the nearest empty seat at
    or before ``tc``.  Returns True on success."""
    if tc < 0 or tc >= len(row):
        return False
    for e in range(tc, -1, -1):
        if row[e] is None:
            for i in range(e, tc):
                row[i] = row[i + 1]
            row[tc] = _reserved()
            return True
    return False


def apply_buffers(rows):
    """Guarantee a reserved (empty) seat IMMEDIATELY next to each student with a
    ``buffer`` — same row, right side first — for a 1:1 para or a buffer around a
    distractible student.  Opens the seat by a LOCAL shift within the row, so no
    section-mate gets stranded across the room.  Runs last."""
    def find(student):
        for r, row in enumerate(rows):
            for c, x in enumerate(row):
                if x is student:
                    return r, c
        return None

    buffered = [s for row in rows for s in row
                if s and not s.get("reserved") and int(s.get("buffer") or 0) > 0]
    for s in buffered:
        pos = find(s)
        if not pos:
            continue
        r, c = pos
        row = rows[r]
        k = int(s.get("buffer") or 0)
        if not any(x is None for x in row):
            # Row is completely full — relocate its far-end movable student to
            # the nearest empty seat elsewhere so a seat can open up here.
            dest = next(((r2, c2) for r2, row2 in enumerate(rows)
                         for c2, x in enumerate(row2) if x is None), None)
            ei = next((i for i in range(len(row) - 1, -1, -1)
                       if i != c and row[i] is not None
                       and not row[i].get("reserved") and not row[i].get("pref")
                       and not int(row[i].get("buffer") or 0)), None)
            if dest is not None and ei is not None:
                rows[dest[0]][dest[1]] = row[ei]
                row[ei] = None
        opened = 0
        # First buffer: prefer the right side, fall back to the left.
        if k >= 1:
            if _open_right(row, c + 1) or _open_left(row, c - 1):
                opened += 1
        # Second buffer: the other side (student column is unchanged by shifts).
        if opened < k:
            if _open_left(row, c - 1) or _open_right(row, c + 1):
                opened += 1
    return rows


def apply_together(rows, pairs):
    """Seat each named pair next to each other in the same row (e.g. a student
    who should sit beside a friend/peer model).  Moves the second student to a
    seat immediately beside the first, swapping the displaced occupant back."""
    if not pairs:
        return rows

    def find(name):
        nm = (name or "").lower()
        for r, row in enumerate(rows):
            for c, x in enumerate(row):
                if x and not x.get("reserved") and (x.get("name") or "").lower() == nm:
                    return r, c
        return None

    for pair in pairs:
        if not isinstance(pair, (list, tuple)) or len(pair) < 2:
            continue
        pa, pb = find(pair[0]), find(pair[1])
        if not pa or not pb:
            continue
        ra, ca = pa
        rb, cb = pb
        if ra == rb and abs(ca - cb) == 1:
            continue  # already adjacent
        row = rows[ra]
        for tc in (ca + 1, ca - 1):
            if 0 <= tc < len(row):
                occ = row[tc]
                if occ and (occ.get("pref") or occ.get("reserved")):
                    continue
                b = rows[rb][cb]
                rows[rb][cb] = row[tc]
                row[tc] = b
                break
    return rows


def build_chart(students, mode, row_caps, concert=False, conflicts=None,
                center_tuba=True, seed=None, separate_percussion=False,
                section_order=None, shuffle_members=False, shuffle_sections=False,
                together=None, zones=None, side_zones=None, zone_cols=None,
                close_gaps=True, anchors=None):
    """End-to-end: order → lay out → pins → conflict repair → (concert) center
    tuba → buffers.  When ``separate_percussion`` is set, percussionists are
    pulled out and returned as a flat list for a straight back row.  ``zones``
    locks a section to specific rows ({instrument: [0-based row indices]}).

    Returns (rows, unresolved_conflicts, percussion_list, unseated)."""
    students = list(students)
    percussion = []
    if separate_percussion:
        percussion = [s for s in students if family(s.get("instrument")) == "Percussion"]
        students = [s for s in students if family(s.get("instrument")) != "Percussion"]
        percussion = _by_last(percussion)

    sections_mode = mode == "sections"
    if sections_mode:
        groups = _section_groups(students, section_order, shuffle_members,
                                 shuffle_sections, seed)
        # Keep an edge-pinned student WITH their section by seating them at the
        # section block's trailing edge, rather than yanking them to the row end.
        groups = [(inst, _edge_last(members)) for inst, members in groups]
        rows, unseated = layout_section_blocks(groups, row_caps, zones=zones,
                                               side_zones=side_zones,
                                               zone_cols=zone_cols,
                                               anchors=anchors)
    elif mode == "small_groups":
        # Whole 2–3 person like-instrument clusters — never split across rows.
        clusters = small_group_clusters(students, order_key=concert_rank, seed=seed)
        rows, unseated = layout_clusters(clusters, row_caps)
    else:
        ordered = order_students(students, mode, concert=concert, seed=seed)
        rows, unseated = layout_rows(ordered, row_caps)
    rows = _pad_to_grid(rows, row_caps)
    if sections_mode:
        # Before the pins and the conflict repair get their say, so a section
        # made whole here can still be pulled apart for a good reason.
        rows = regroup_rows(rows)
    rows = apply_row_pins(rows, row_caps)
    rows, unresolved = separate_conflicts(rows, conflicts or set())
    if close_gaps:
        # Before the tuba is centered and before the reserved buffer seats go
        # in: those ARE wanted empty chairs and must not be closed up.
        rows = compact_rows(rows, row_caps, anchors)
    if center_tuba and mode == "sections":
        # Only meaningful when seated by section — in small-group or
        # alphabetical layouts it would rip the tuba out of their group.
        center_instrument(rows, "Tuba")
    if mode not in ("sections", "small_groups"):
        # Sections seat edge students at their section's edge; small groups
        # start a row with the edge student's cluster.  Only plain layouts
        # need the post-hoc row-edge move.
        rows = apply_edge_pins(rows)
    rows = apply_together(rows, together or [])
    rows = apply_buffers(rows)     # last, so the empty seat stays put next to them
    unseated = [s for s in unseated if s and not s.get("reserved")]
    return rows, unresolved, percussion, unseated


def _edge_last(members):
    """Order a section's members so edge-pinned students sit at the block's
    trailing edge (keeping them with their section)."""
    non_edge = [m for m in members if not (m and m.get("pref") == "edge")]
    edge = [m for m in members if m and m.get("pref") == "edge"]
    return non_edge + edge
