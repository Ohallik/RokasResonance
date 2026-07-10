"""
percussion_rotation.py - Pure rotation logic for percussion section assignments.

The teacher enters the percussionists in a class period.  Each day the whole
section rotates through a fixed ring of "seats" so that, over a full cycle,
everyone spends roughly:

    * 40% of days on Mallets
    * 40% of days on Snare (SD) / snare-family stations
    * 20% of days on Timpani / Auxiliary

For larger sections extra specialty seats are added:

    * an extra Timp/aux seat (two players at once) as the section grows
    * a BD/SD seat  (bass drum, defaulting to a practice pad when there is no
      bass-drum part) once the section is big enough to spare a player
    * for Intermediate / Advanced sections, a Drum set seat as well, where the
      player works snare AND bass drum together on the kit

Entry-band players must earn their way into the full rotation: until they pass
their first five playing assessments they stay on Mallets only (optionally
cycling through the mallet instruments -- xylophone, bells, marimba,
vibraphone).  Those players are simply excluded from the ring and always show
"Mallets" until the teacher unlocks them.

Everything here is deterministic and free of UI so it can be unit-tested and
later reused by a daily-agenda generator.
"""

ENTRY = "entry"
INT_ADV = "intermediate_advanced"

# Station labels (kept identical to what the teacher writes on the board).
MALLETS = "Mallets"
SD = "SD"
TIMP_AUX = "Timp/aux"
BD_SD = "BD/SD"
DRUM_SET = "Drum set"

# Sub-rotation of mallet instruments for players who are on Mallets only.
MALLET_INSTRUMENTS = ["Xylophone", "Bells", "Marimba", "Vibraphone"]

# Special one-off day modes.
MODE_NORMAL = "normal"
MODE_ALL_MALLETS = "all_mallets"
MODE_ALL_SNARE = "all_snare"
ALL_SNARE_LABEL = "SD / Pad"


def allocate_seats(n, class_type):
    """Return a flat list of ``n`` station labels (the multiset of seats) for a
    section of ``n`` full-rotation players.

    Targets ~40% mallets, ~40% snare-family, ~20% timp/aux, with specialty
    seats phased in as the section grows.  Reproduces the teacher's real grids:

        Entry, n=11   -> 5 Mallets, 3 SD, 1 BD/SD, 2 Timp/aux
        Int/Adv, n=7  -> 3 Mallets, 1 SD, 1 Drum set, 1 BD/SD, 1 Timp/aux
    """
    if n <= 0:
        return []

    # Timp/aux: ~20%, but don't pull a player from a tiny section.
    timp = 0 if n < 3 else max(1, round(0.20 * n))

    remaining = n - timp
    mallets = (remaining + 1) // 2          # ceil -> mallets gets the slack
    snare_family = remaining - mallets       # floor

    if class_type == INT_ADV:
        if n > 5:
            # More than 5 players: keep BOTH a Drum set seat AND a BD/SD seat.
            # Borrow from mallets if needed so a dedicated SD survives too.
            while snare_family < 3 and mallets > 1:
                mallets -= 1
                snare_family += 1
            drumset = 1
            bd = 1 if snare_family >= 2 else 0
            sd = snare_family - drumset - bd
        else:
            # 5 or fewer: Drum set replaces BD/SD -- no BD/SD seat.
            drumset = 1 if snare_family >= 2 else 0
            bd = 0
            sd = snare_family - drumset
        seats = [MALLETS] * mallets
        seats += [SD] * sd + [DRUM_SET] * drumset + [BD_SD] * bd
    else:  # ENTRY
        bd = 1 if snare_family >= 4 else 0
        sd = snare_family - bd
        seats = [MALLETS] * mallets
        seats += [SD] * sd + [BD_SD] * bd

    seats += [TIMP_AUX] * timp
    return seats


def _interleave(seats):
    """Evenly spread a multiset of labels around a ring so no station clumps.

    Uses the classic "most-owed wins" distribution (a la Bresenham): at each
    slot pick the label whose placed-so-far fraction of its own count is
    smallest.  Ties are broken by the label's first appearance in ``seats`` so
    the result is deterministic.
    """
    # Preserve first-seen order of labels and their counts.
    counts = {}
    order = []
    for label in seats:
        if label not in counts:
            counts[label] = 0
            order.append(label)
        counts[label] += 1

    placed = {label: 0 for label in order}
    ring = []
    total = len(seats)
    for _ in range(total):
        best = None
        best_val = None
        for rank, label in enumerate(order):
            if placed[label] >= counts[label]:
                continue
            # Lower value == more "owed" a slot right now.
            val = (placed[label] + 0.5) / counts[label]
            key = (val, rank)
            if best_val is None or key < best_val:
                best_val = key
                best = label
        ring.append(best)
        placed[best] += 1
    return ring


def build_ring(n, class_type):
    """Return the evenly-spread ring of ``n`` seats for the section."""
    return _interleave(allocate_seats(n, class_type))


def station_summary(n, class_type):
    """Return an ordered list of ``(station, count)`` for a section of ``n``.

    Handy for showing the teacher "this rotation is 5 Mallets / 3 SD / ..." and
    the resulting percentages.
    """
    seats = allocate_seats(n, class_type)
    out = []
    for label in [MALLETS, SD, BD_SD, DRUM_SET, TIMP_AUX]:
        c = seats.count(label)
        if c:
            out.append((label, c))
    return out


def day_assignments(students, day, class_type,
                    mallet_subrotation=True, mode=MODE_NORMAL):
    """Compute the station for every player on rotation ``day`` (1-based).

    ``students`` is an ordered list of dicts with at least:
        ``name``          - display name
        ``mallets_only``  - True if the player has NOT yet earned the full
                            rotation (Entry only); such players stay on mallets.

    Returns a list of ``(name, station)`` tuples in the same order as
    ``students``.  ``mode`` may force a special one-off day:
        MODE_ALL_MALLETS  - everyone on Mallets
        MODE_ALL_SNARE    - everyone on snare / practice pad
    """
    if day < 1:
        day = 1

    if mode == MODE_ALL_MALLETS:
        return [(s["name"], MALLETS) for s in students]
    if mode == MODE_ALL_SNARE:
        return [(s["name"], ALL_SNARE_LABEL) for s in students]

    full = [s for s in students if not s.get("mallets_only")]
    ring = build_ring(len(full), class_type)
    n = len(full)

    # Assign full-rotation players by their position in the section.
    station_by_name = {}
    for i, s in enumerate(full):
        station_by_name[id(s)] = ring[(day - 1 + i) % n] if n else MALLETS

    # Assign mallets-only players, optionally cycling mallet instruments.
    mo = [s for s in students if s.get("mallets_only")]
    for j, s in enumerate(mo):
        if mallet_subrotation:
            inst = MALLET_INSTRUMENTS[(day - 1 + j) % len(MALLET_INSTRUMENTS)]
            station_by_name[id(s)] = inst
        else:
            station_by_name[id(s)] = MALLETS

    return [(s["name"], station_by_name[id(s)]) for s in students]


def full_grid(students, class_type, days=None,
              mallet_subrotation=True, start_day=1):
    """Return a printable grid: ``(day_numbers, rows)``.

    ``rows`` is a list of ``(name, [station_day1, station_day2, ...])`` for one
    full cycle (or ``days`` columns if given), starting at ``start_day``.
    """
    full_count = sum(1 for s in students if not s.get("mallets_only"))
    cycle = max(full_count, 1)
    if days is None:
        days = cycle
    day_numbers = [start_day + k for k in range(days)]

    per_day = [day_assignments(students, d, class_type, mallet_subrotation)
               for d in day_numbers]
    rows = []
    for idx, s in enumerate(students):
        rows.append((s["name"], [per_day[k][idx][1] for k in range(days)]))
    return day_numbers, rows
