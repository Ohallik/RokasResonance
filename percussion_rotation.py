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

Mallet assignments respect the room's physical inventory (MALLET_CAPACITY):
one marimba that fits 3 players, one vibraphone (2), one xylophone (2), and
three single-player bell sets -- 10 simultaneous spots.  Everyone on a mallet
seat on a given day (full-rotation and mallets-only alike) is placed on a
specific instrument without ever exceeding a capacity; players beyond 10
rotate through a practice-pad spot, which is why a big section's grid runs
longer than its head count suggests.

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

# Physical mallet inventory — the real limiting factor for any rotation.
# The DEFAULT is this teacher's room: one 4 1/3-octave marimba fits 3
# players at a time, one vibraphone 2, one xylophone 2, and each of the
# three bell sets is one player (so Bells = 3 total) — 10 simultaneous
# mallet spots.  Rooms differ (a 5-octave marimba fits 4; a mini practice
# xylophone adds 1), so every function below accepts an ``inventory``
# override: an ordered list of (equipment name, students at a time).
MALLET_CAPACITY = {"Marimba": 3, "Vibraphone": 2, "Xylophone": 2, "Bells": 3}
PAD = "Practice pad"


def _norm_inventory(inventory):
    """Sanitize a custom inventory into [(name, capacity), ...]; accepts
    (name, cap) tuples or {"name":, "capacity":} dicts.  Falls back to the
    default room when empty/invalid."""
    default = [(i, MALLET_CAPACITY[i]) for i in MALLET_INSTRUMENTS]
    if not inventory:
        return default
    out = []
    for item in inventory:
        if isinstance(item, dict):
            name, cap = item.get("name"), item.get("capacity")
        else:
            name, cap = item
        name = (name or "").strip()
        try:
            cap = int(cap)
        except (TypeError, ValueError):
            cap = 0
        if name and cap > 0:
            out.append((name, cap))
    return out or default

# Special one-off day modes.
MODE_NORMAL = "normal"
MODE_ALL_MALLETS = "all_mallets"
MODE_ALL_SNARE = "all_snare"
ALL_SNARE_LABEL = "SD / Pad"

# When only a few players have earned the full rotation, a ring of that size
# would be degenerate (one earner would sit on a single station forever).
# Small groups instead walk a 5-seat 40/40/20 pattern over TIME, so even a
# single earned player still cycles Mallets -> SD -> Timp/aux across days.
MIN_RING = 5


# ── Custom station lists ──────────────────────────────────────────────────────
# The built-in 40/40/20 allocation below is one (good) opinion about what a
# middle-school percussion section should rotate through.  It is not everyone's:
# a teacher with no kit doesn't want a Drum set seat, another wants Congas in
# the ring, a third splits Timpani away from Auxiliary.  A section may therefore
# carry its OWN station list — an ordered list of ``{"name", "share"}`` where
# ``share`` is how many days out of the total each station is worth relative to
# the others.  Seats are then handed out in proportion to those shares.
#
# ``stations=None`` keeps the built-in behavior exactly, so nothing changes for
# a teacher who never opens the editor.


def default_stations(class_type):
    """The built-in rotation expressed as an editable station list — the
    starting point the station editor shows.  Shares reproduce the built-in
    40% mallets / 40% snare-family / 20% timp-aux split."""
    if class_type == INT_ADV:
        return [{"name": MALLETS, "share": 4},
                {"name": SD, "share": 2},
                {"name": DRUM_SET, "share": 1},
                {"name": BD_SD, "share": 1},
                {"name": TIMP_AUX, "share": 2}]
    return [{"name": MALLETS, "share": 4},
            {"name": SD, "share": 3},
            {"name": BD_SD, "share": 1},
            {"name": TIMP_AUX, "share": 2}]


def norm_stations(stations):
    """Sanitize a custom station list into ``[{"name", "share"}, ...]``, or
    None if there's nothing usable (which means "use the built-in rotation")."""
    if not stations:
        return None
    out = []
    for item in stations:
        if isinstance(item, dict):
            name, share = item.get("name"), item.get("share", 1)
        else:
            try:
                name, share = item
            except (TypeError, ValueError):
                continue
        name = str(name or "").strip()
        try:
            share = int(share)
        except (TypeError, ValueError):
            share = 1
        if name and share > 0:
            out.append({"name": name, "share": share})
    return out or None


def station_names(class_type, stations=None):
    """Every station this section can place a player on — used by the
    per-student rotation-limit picker so it offers the teacher's OWN stations
    rather than the built-in ones."""
    st = norm_stations(stations) or default_stations(class_type)
    return [s["name"] for s in st]


def _custom_seats(n, stations):
    """Hand ``n`` seats out across a custom station list in proportion to each
    station's share (largest-remainder, so the totals always add to n).

    Every listed station gets at least one seat while there are players to
    spare — a station nobody ever reaches isn't a rotation.  When the section
    is smaller than the station list, the highest-share stations win the seats.
    """
    total_share = sum(s["share"] for s in stations)
    if n <= 0 or total_share <= 0:
        return []

    if n < len(stations):
        # Too few players for every station: keep the biggest shares, stable on
        # ties by the teacher's own ordering.
        ranked = sorted(range(len(stations)),
                        key=lambda i: (-stations[i]["share"], i))[:n]
        return [stations[i]["name"] for i in sorted(ranked)]

    # Proportional allocation by largest remainder, so the shares are honoured
    # as closely as whole players allow.
    exact = [n * s["share"] / total_share for s in stations]
    counts = [int(e) for e in exact]
    order = sorted(range(len(stations)),
                   key=lambda i: (-(exact[i] - counts[i]), i))
    for i in order[:n - sum(counts)]:
        counts[i] += 1

    # Then make sure nobody listed a station that never comes up: borrow a seat
    # from whichever station currently has the most (it can spare one).
    for i, c in enumerate(counts):
        if c:
            continue
        donor = max(range(len(counts)), key=lambda j: (counts[j], -j))
        if counts[donor] <= 1:
            break                      # nothing left to borrow — n is too small
        counts[donor] -= 1
        counts[i] = 1

    seats = []
    for st, c in zip(stations, counts):
        seats += [st["name"]] * c
    return seats


def allocate_seats(n, class_type, stations=None):
    """Return a flat list of ``n`` station labels (the multiset of seats) for a
    section of ``n`` full-rotation players.

    With a custom ``stations`` list, seats are proportional to each station's
    share.  Otherwise the built-in allocation targets ~40% mallets, ~40%
    snare-family, ~20% timp/aux, with specialty seats phased in as the section
    grows.  Reproduces the teacher's real grids:

        Entry, n=11   -> 5 Mallets, 3 SD, 1 BD/SD, 2 Timp/aux
        Int/Adv, n=7  -> 3 Mallets, 1 SD, 1 Drum set, 1 BD/SD, 1 Timp/aux
    """
    if n <= 0:
        return []

    custom = norm_stations(stations)
    if custom:
        return _custom_seats(n, custom)

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


def mallet_slots(inventory=None):
    """The flat list of simultaneous mallet spots the room actually has,
    interleaved so walking the list day by day moves a player to a
    different instrument instead of parking them (Xylophone, Bells,
    Marimba, ... rather than Marimba, Marimba, Marimba, ...)."""
    seats = []
    for name, cap in _norm_inventory(inventory):
        seats += [name] * cap
    return _interleave(seats)


def _mallet_slot_walk(count, inventory=None):
    """Slot list sized for ``count`` simultaneous mallet players: the real
    instrument spots, padded with practice-pad spots when the section has
    more mallet players than the room has instruments."""
    slots = mallet_slots(inventory)
    if count > len(slots):
        slots = slots + [PAD] * (count - len(slots))
    return slots


# ── Per-student rotation limits (accessibility / individualized rotations) ────
# Some students can't run the whole rotation: one may only ever play Bells
# (with a 1:1 para) yet play every line beautifully; another may grow from
# mallets-only to +snare to +drum set but never handle timpani/aux.  Give such
# a student an ``allowed_stations`` list — the exact stations they may take —
# and the engine restricts them to ONLY those, cycling among them day by day,
# independent of the earn-based mallets-only/full-rotation split.  An empty or
# missing list means "no limit" (the normal earn-based behavior).

def _is_limited(student):
    return bool(student.get("allowed_stations"))


def _reserved_instruments(limited):
    """Named mallet spots permanently consumed by limited students who are
    LOCKED to a single specific instrument (e.g. Bells only).  These are
    subtracted from the room inventory so the learner walk never double-books
    that student's instrument.  A student allowed several stations isn't
    reserved (their mallet days fall on generic self-choice)."""
    reserved = {}
    for s in limited:
        allowed = s.get("allowed_stations") or []
        if len(allowed) == 1:
            reserved[allowed[0]] = reserved.get(allowed[0], 0) + 1
    return reserved


def _reduce_inventory(inventory, reserved):
    """The room inventory with locked-instrument spots removed, so the
    remaining learners walk only the spots actually free.  Never returns
    empty (that would fall back to the default room)."""
    inv = _norm_inventory(inventory)
    if not reserved:
        return inv
    out = []
    for name, cap in inv:
        cap2 = cap - reserved.get(name, 0)
        if cap2 > 0:
            out.append((name, cap2))
    return out or inv


def _limited_station(student, day, index):
    """The station a limited student takes on ``day`` (1-based): cycle their
    own allowed list, staggered by ``index`` so two limited students sharing
    a list don't move in lockstep."""
    allowed = student.get("allowed_stations") or []
    if not allowed:
        return MALLETS
    return allowed[(day - 1 + index) % len(allowed)]


def build_ring(n, class_type, stations=None):
    """Return the evenly-spread ring of seats for ``n`` full-rotation players.

    The ring never shrinks below MIN_RING seats: with 1-4 earned players the
    extra seats are simply unmanned each day, and the players advance through
    the full 40/40/20 pattern over the days instead.  With a custom station
    list the ring is at least long enough to visit every station."""
    if n <= 0:
        return []
    custom = norm_stations(stations)
    floor = max(MIN_RING, len(custom)) if custom else MIN_RING
    return _interleave(allocate_seats(max(n, floor), class_type, stations))


def cycle_length(students, mallet_subrotation=True, inventory=None,
                 stations=None, class_type=None):
    """Days in one full rotation round for this mix of players.

    Two things have to complete within one cycle, and the length is the
    longer of them so NEITHER gets cut short:

      * Full-rotation players cycle the seat ring (length >= MIN_RING).
      * Still-learning (mallets-only) players walk the room's physical mallet
        spots so each one plays every instrument type — 10 spots for the
        default room (marimba 3, vibraphone 2, xylophone 2, three bell sets),
        plus a practice-pad spot per extra player.

    This is why one earned player must NOT shrink an 11-player Entry section
    down to a 5-day ring: the ten still-learning players would then never
    reach some instruments.  The mallets-only walk keeps it long enough for
    everyone to see marimba, vibraphone, xylophone, and bells.

    Station-limited students (``allowed_stations``) sit outside both groups;
    their own list also has to complete within a cycle, so its length counts
    too."""
    limited = [s for s in students if _is_limited(s)]
    rest = [s for s in students if not _is_limited(s)]
    full_count = sum(1 for s in rest if not s.get("mallets_only"))
    mo_count = sum(1 for s in rest if s.get("mallets_only"))
    inv = _reduce_inventory(inventory, _reserved_instruments(limited))
    custom = norm_stations(stations)
    ring_floor = max(MIN_RING, len(custom)) if custom else MIN_RING
    lengths = []
    if full_count:
        lengths.append(max(full_count, ring_floor))
    if mo_count:
        lengths.append(len(_mallet_slot_walk(mo_count, inv))
                       if mallet_subrotation else 1)
    for s in limited:
        lengths.append(len(s.get("allowed_stations") or []) or 1)
    return max(lengths) if lengths else 1


# ── Mallet "family" by the stick students grab (drives color + icon) ─────────
YARN_MALLETS = "yarn"        # marimba, vibraphone — soft yarn/cord heads
RUBBER_MALLETS = "rubber"    # xylophone, bells/glockenspiel — hard rubber/plastic


def mallet_family(station):
    """'yarn', 'rubber', or None for a station/instrument name.  Generic
    "Mallets" (a full-rotation player's free-choice day) and the practice
    pad return None — only a specific learning-instrument has a stick type."""
    low = (station or "").lower()
    if "marimba" in low or "vibra" in low:
        return YARN_MALLETS
    if "xylophone" in low or "bell" in low or "glock" in low:
        return RUBBER_MALLETS
    return None


def _mallets_only_station(j, mo_count, day, inventory, mallet_subrotation):
    """The specific mallet instrument for the ``j``-th still-learning player
    on ``day``.  Distinct offsets keep any instrument within its capacity,
    and walking the whole spot list guarantees the player rotates through
    every instrument type over one cycle."""
    if not mallet_subrotation:
        return MALLETS
    slots = _mallet_slot_walk(mo_count, inventory)
    return slots[(day - 1 + j) % len(slots)]


def station_summary(n, class_type, stations=None):
    """Return an ordered list of ``(station, count)`` for a section of ``n``.

    Handy for showing the teacher "this rotation is 5 Mallets / 3 SD / ..." and
    the resulting percentages.  Custom stations are reported in the teacher's
    own order; the built-in ones keep their board order.
    """
    seats = allocate_seats(n, class_type, stations)
    custom = norm_stations(stations)
    order = ([s["name"] for s in custom] if custom
             else [MALLETS, SD, BD_SD, DRUM_SET, TIMP_AUX])
    out = []
    for label in order:
        c = seats.count(label)
        if c:
            out.append((label, c))
    # Anything the ordering didn't mention still gets reported.
    for label in seats:
        if label not in order and not any(label == o for o, _ in out):
            out.append((label, seats.count(label)))
    return out


def day_assignments(students, day, class_type,
                    mallet_subrotation=True, mode=MODE_NORMAL,
                    inventory=None, stations=None):
    """Compute the station for every player on rotation ``day`` (1-based).

    ``students`` is an ordered list of dicts with at least:
        ``name``          - display name
        ``mallets_only``  - True if the player has NOT yet earned the full
                            rotation (Entry only); such players stay on mallets.

    Returns a list of ``(name, station)`` tuples in the same order as
    ``students``.

    Full-rotation ("earned") players land on generic ``Mallets`` when their
    ring seat is a mallet seat: they are trusted to grab whichever mallet
    instrument is free.  Still-learning (mallets-only) players instead get a
    SPECIFIC instrument each day and cycle through every type (marimba,
    vibraphone, xylophone, bells), because feeling each instrument's bar
    size and spacing is part of learning.

    ``mode`` may force a special one-off day:
        MODE_ALL_MALLETS  - everyone on Mallets (earned generic; learners
                            still get their specific instrument)
        MODE_ALL_SNARE    - everyone on snare / practice pad

    Station-limited students (``allowed_stations``) always take one of their
    own allowed stations — they ignore the ring, the mallets-only walk, AND
    the special-day modes, since the limit is exactly what they can do.
    """
    if day < 1:
        day = 1

    # Limited students are handled first and pulled out of the normal pools.
    limited = [s for s in students if _is_limited(s)]
    limited_index = {id(s): k for k, s in enumerate(limited)}
    rest = [s for s in students if not _is_limited(s)]

    # Locked-to-one-instrument students reserve that mallet spot for the walk.
    inv = _reduce_inventory(inventory, _reserved_instruments(limited))

    mo = [s for s in rest if s.get("mallets_only")]
    mo_index = {id(s): j for j, s in enumerate(mo)}

    def learner_station(s):
        return _mallets_only_station(mo_index[id(s)], len(mo), day,
                                     inv, mallet_subrotation)

    station_by_id = {}
    for s in limited:
        station_by_id[id(s)] = _limited_station(s, day, limited_index[id(s)])

    if mode == MODE_ALL_MALLETS:
        for s in rest:
            station_by_id[id(s)] = (learner_station(s)
                                    if s.get("mallets_only") else MALLETS)
    elif mode == MODE_ALL_SNARE:
        for s in rest:
            station_by_id[id(s)] = ALL_SNARE_LABEL
    else:
        full = [s for s in rest if not s.get("mallets_only")]
        ring = build_ring(len(full), class_type, stations)
        rlen = len(ring)
        # Full-rotation players take ring seats by position; a Mallets seat
        # stays generic "Mallets" (free choice of any open mallet instrument).
        for i, s in enumerate(full):
            station_by_id[id(s)] = ring[(day - 1 + i) % rlen] if rlen else MALLETS
        # Still-learning players get a specific instrument, cycling all types.
        for s in mo:
            station_by_id[id(s)] = learner_station(s)

    return [(s["name"], station_by_id[id(s)]) for s in students]


def full_grid(students, class_type, days=None,
              mallet_subrotation=True, start_day=1, inventory=None,
              stations=None):
    """Return a printable grid: ``(day_numbers, rows)``.

    ``rows`` is a list of ``(name, [station_day1, station_day2, ...])`` for one
    full cycle (or ``days`` columns if given), starting at ``start_day``.
    """
    if days is None:
        days = cycle_length(students, mallet_subrotation, inventory, stations,
                            class_type)
    day_numbers = [start_day + k for k in range(days)]

    per_day = [day_assignments(students, d, class_type, mallet_subrotation,
                               inventory=inventory, stations=stations)
               for d in day_numbers]
    rows = []
    for idx, s in enumerate(students):
        rows.append((s["name"], [per_day[k][idx][1] for k in range(days)]))
    return day_numbers, rows
