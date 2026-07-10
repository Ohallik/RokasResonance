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
    "Violin": "#48cae4", "Violin 1": "#48cae4", "Violin 2": "#8fdcf0",
    "Viola": "#00b4d8", "Viola 1": "#00b4d8", "Viola 2": "#4cc9e6",
    "Cello": "#0096c7", "Cello 1": "#0096c7", "Cello 2": "#3fb0d6",
    "String Bass": "#0077b6", "Harp": "#48bfe3", "Piano": "#56cfe1",
    "Soprano": "#ff6b6b", "Alto": "#ffd166", "Tenor": "#8ac926",
    "Baritone": "#4d96ff", "Bass": "#9b5de5",
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
        sizes = []
        n = len(m)
        while n >= 5:
            sizes.append(3)
            n -= 3
        if n == 4:
            sizes += [2, 2]
        elif n:
            sizes.append(n)
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

    # Round-robin clusters across instruments so like groups spread around.
    out = []
    queues = [list(cl) for _, cl in per_inst]
    while any(queues):
        for q in queues:
            if q:
                out.append(q.pop(0))
    return out


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
    """Nudge players of ``instrument`` toward the centre of their row's
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


def layout_section_blocks(groups, row_caps, target_width=4, zones=None,
                          side_zones=None):
    """Lay out sections as contiguous runs (never scattering).  ``zones`` locks a
    section to specific rows; ``side_zones`` ({instrument: 'left'|'right'}) packs
    a section against the audience-left or audience-right side of the room.

    ``zones`` optionally locks a section to specific rows: ``{instrument: [row
    indices]}`` (0-based).  Zoned sections are placed in their rows first; the
    rest fill the remaining space.

    ``groups`` is an ordered list of (instrument, [students]).  Returns
    (rows, unseated) where rows are fixed-width grids (with None for empty seats)
    and ``unseated`` is anyone who didn't fit the room as configured."""
    zones = zones or {}
    side_zones = side_zones or {}
    R = len(row_caps)
    caps = [row_caps[r] for r in range(R)]
    grid = [[None] * caps[r] for r in range(R)]
    unseated = []

    def fill(members, allowed_rows, from_right=False):
        """Fill members into empty seats of ``allowed_rows`` in reading order
        (row by row).  ``from_right`` fills each row right-to-left (for a section
        assigned to stage right).  Sections land in a CONTIGUOUS run, never
        scattering.  Returns leftover members."""
        leftover = list(members)
        for r in allowed_rows:
            if r < 0 or r >= R:
                continue
            cols = range(caps[r] - 1, -1, -1) if from_right else range(caps[r])
            for c in cols:
                if not leftover:
                    return leftover
                if grid[r][c] is None:
                    grid[r][c] = leftover.pop(0)
        return leftover

    all_rows = list(range(R))
    # 1) Row-zoned sections claim their rows (respecting a stage side too,
    #    e.g. string basses in the back row toward stage right).
    for inst, members in groups:
        if inst in zones:
            left = fill(list(members), sorted(zones[inst]),
                        from_right=(side_zones.get(inst) == "right"))
            unseated.extend(fill(left, all_rows))
    # 2) Stage-left sections pack from the left, stage-right from the right.
    for inst, members in groups:
        if inst not in zones and side_zones.get(inst) == "left":
            unseated.extend(fill(list(members), all_rows))
    for inst, members in groups:
        if inst not in zones and side_zones.get(inst) == "right":
            unseated.extend(fill(list(members), all_rows, from_right=True))
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
                together=None, zones=None, side_zones=None):
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
                                               side_zones=side_zones)
    elif mode == "small_groups":
        # Whole 2–3 person like-instrument clusters — never split across rows.
        clusters = small_group_clusters(students, order_key=concert_rank, seed=seed)
        rows, unseated = layout_clusters(clusters, row_caps)
    else:
        ordered = order_students(students, mode, concert=concert, seed=seed)
        rows, unseated = layout_rows(ordered, row_caps)
    rows = _pad_to_grid(rows, row_caps)
    rows = apply_row_pins(rows, row_caps)
    rows, unresolved = separate_conflicts(rows, conflicts or set())
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
