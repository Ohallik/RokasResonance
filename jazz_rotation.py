"""
jazz_rotation.py - Rhythm-section assignment logic for jazz ensembles.

Unlike the concert-percussion rotation (fixed mallet/snare/timpani seats with an
earn-based mallets-only phase), a jazz rhythm section is *variable*: the teacher
lists the SEATS in play and, for each PLAYER, the subset of those seats they can
cover.  Two things then happen:

  * WARM-UPS / a brand-new tune — nobody is committed yet, so the section
    ROTATES: each day the eligible players cycle through the seats.
  * An ESTABLISHED tune — once she's auditioned an actual drummer, pianist, etc.,
    those seats are LOCKED to specific players for that song and stop rotating.

Two things make a jazz section different from the percussion one, and this module
models both:

  * SEAT CAPACITY.  Most seats hold one player at a time (drum set, piano), but a
    "Vibraphone" (really any mallet spot — vibes, marimba, bells) can hold
    several, and that's where extra players go so nobody sits out.  Each seat
    therefore has a capacity.
  * SHARED LIMITS (pools).  Some seats draw on a shared resource — e.g. there are
    only three amps, split any way across Bass and Guitar (two basses + a guitar,
    or two guitars + a bass).  A pool caps the TOTAL players across a set of seats.

The engine's goals, in order: honor locks, give players turns on the scarce
one-at-a-time seats (drum set first — it's the whole point), and then MINIMIZE
who's benched by parking spare players on the high-capacity mallet seat.

Everything is deterministic — the same inputs always give the same board — so the
agenda and the Jazz tool always agree.  A "player" is ``{"name", "parts": [...]}``,
a "seat" is a name or ``{"name", "capacity"}``, a "lock" is ``{seat: name |
[names]}``, and a "pool" is ``{"name", "limit", "seats": [...]}``.
"""

# Default rhythm-section seats for a new jazz ensemble, with sensible capacities:
# the mallet seat holds several players (vibes/marimba/bells), everything else is
# one at a time.  She can rename/add/remove and change any capacity.
DEFAULT_SEATS = [
    {"name": "Drum set", "capacity": 1},
    {"name": "Piano", "capacity": 1},
    {"name": "Bass", "capacity": 1},
    {"name": "Guitar", "capacity": 1},
    {"name": "Vibraphone", "capacity": 4},
]

# Quick-add menu offered in the seat editor (all still free-text / editable).
COMMON_SEATS = ["Drum set", "Piano", "Electric piano", "Bass", "Guitar",
                "Vibraphone", "Aux percussion", "Tenor Sax", "Trombone",
                "Trumpet", "Vocals"]

# Seat names treated as "the drum set" for turn-priority (case-insensitive).
DRUM_SEATS = {"drum set", "drums", "drumset", "kit", "drum kit"}


def normalize_seats(seats):
    """Ordered, de-duplicated ``[(name, capacity), ...]``.  Accepts a list of
    plain names (capacity 1) or ``{"name", "capacity"}`` dicts."""
    out, seen = [], set()
    for s in seats or []:
        if isinstance(s, dict):
            name, cap = (s.get("name") or "").strip(), s.get("capacity", 1)
        else:
            name, cap = (s or "").strip(), 1
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        try:
            cap = max(1, int(cap))
        except (TypeError, ValueError):
            cap = 1
        out.append((name, cap))
    return out


def seat_names(seats):
    return [n for n, _ in normalize_seats(seats)]


def _clean_seats(seats):
    """Ordered, de-duplicated, non-blank NAME list (for a player's parts)."""
    out, seen = [], set()
    for s in seats or []:
        s = (s or "").strip()
        if s and s.lower() not in seen:
            seen.add(s.lower())
            out.append(s)
    return out


def normalize_pools(pools, valid_seats):
    """Sanitize shared-limit pools into ``[{"name","limit","seats":set}]``,
    dropping seats that aren't in the ensemble and pools with no valid seats."""
    valid = {s for s in valid_seats}
    out = []
    for p in pools or []:
        if not isinstance(p, dict):
            continue
        name = (p.get("name") or "").strip()
        try:
            limit = int(p.get("limit"))
        except (TypeError, ValueError):
            continue
        seats = {s for s in (p.get("seats") or []) if s in valid}
        if name and limit > 0 and seats:
            out.append({"name": name, "limit": limit, "seats": seats})
    return out


def normalize_locked(locked, valid_seats):
    """``{seat: name | [names]}`` → ``{seat: [names]}`` for valid seats only."""
    valid = set(valid_seats)
    out = {}
    for seat, val in (locked or {}).items():
        if seat not in valid:
            continue
        if isinstance(val, list):
            names = [v for v in val if v]
        elif val:
            names = [val]
        else:
            names = []
        if names:
            out[seat] = names
    return out


def eligible_players(seat, players, used=None):
    """Roster-ordered players who can cover ``seat`` and aren't placed yet."""
    used = used or set()
    return [p for p in players
            if seat in (p.get("parts") or []) and p.get("name") not in used]


def day_assignments(seats, players, day=1, locked=None, pools=None):
    """Assign players to seats for rotation ``day`` (1-based).

    Order of operations:
      1. Locked seats (a song's auditioned players) are pinned first, consuming
         capacity — and, if the seat is in a pool, a slot of that pool.
      2. Scarce one-at-a-time seats are filled first (drum set before anything,
         then by capacity) so turns on them rotate day to day across everyone
         eligible — the main goal of a jazz rotation.
      3. Anyone still unplaced is parked on any seat they can play that still has
         room (preferring the emptiest, i.e. the big mallet seat) so as few
         players as possible sit out.

    ``locked`` may map a seat to one name or a list (up to its capacity); pools
    ({"name","limit","seats"}) cap the TOTAL players across their seats (e.g. 3
    amps split across Bass + Guitar).

    Returns ``(assignments, bench)`` — ``assignments`` is an ordered list of
    ``(seat, [names])`` (a list because a seat may hold several) and ``bench`` is
    the players not placed anywhere.
    """
    seatlist = normalize_seats(seats)
    names = [n for n, _ in seatlist]
    caps = {n: c for n, c in seatlist}
    present = {p.get("name") for p in players}
    pool_list = normalize_pools(pools, names)
    seat_pool = {s: p["name"] for p in pool_list for s in p["seats"]}
    pool_limit = {p["name"]: p["limit"] for p in pool_list}
    pool_use = {p["name"]: 0 for p in pool_list}
    locked = normalize_locked(locked, names)
    if day < 1:
        day = 1

    assign = {n: [] for n in names}
    used = set()
    by_name = {p.get("name"): p for p in players}
    locked_names = {nm for lst in locked.values() for nm in lst}

    def has_room(seat):
        if len(assign[seat]) >= caps[seat]:
            return False
        pn = seat_pool.get(seat)
        return not (pn and pool_use[pn] >= pool_limit[pn])

    def place(seat, name):
        assign[seat].append(name)
        used.add(name)
        pn = seat_pool.get(seat)
        if pn:
            pool_use[pn] += 1

    def unplace(seat, name):
        assign[seat].remove(name)
        used.discard(name)
        pn = seat_pool.get(seat)
        if pn:
            pool_use[pn] -= 1

    # 1) Locked players (from a song's saved lineup).
    for seat in names:
        for nm in locked.get(seat, []):
            if nm in present and nm not in used and has_room(seat):
                place(seat, nm)

    # 2) Rotate — drum set first, then the other scarce (small-capacity) seats,
    #    so a turn on the kit cycles through every eligible player over the days.
    def priority(item):
        n, c = item
        return (0 if n.strip().lower() in DRUM_SEATS else 1, c, names.index(n))

    for seat, _cap in sorted(seatlist, key=priority):
        offset = names.index(seat)
        while has_room(seat):
            elig = eligible_players(seat, players, used)
            if not elig:
                break
            place(seat, elig[(day - 1 + offset) % len(elig)]["name"])

    # 3) Minimize the bench: seat any leftover player wherever they fit, filling
    #    the emptiest seat first (the mallet seat soaks up the extras).
    for p in players:
        if p["name"] in used:
            continue
        cands = [s for s in names if s in (p.get("parts") or []) and has_room(s)]
        if not cands:
            continue
        cands.sort(key=lambda s: caps[s] - len(assign[s]), reverse=True)
        place(cands[0], p["name"])

    # 4) Rescue pass — a player may still be benched only because a seat they can
    #    play is full of players who each have somewhere ELSE to go (e.g. a piano-
    #    only student stuck behind a pianist who also plays vibes).  Shuffle one
    #    movable occupant out so the stuck player gets a seat.  Repeats until no
    #    further rescue is possible.
    changed = True
    while changed:
        changed = False
        for p in players:
            if p["name"] in used:
                continue
            for seat in (p.get("parts") or []):
                if seat not in assign:
                    continue
                for occ in list(assign[seat]):
                    if occ in locked_names:
                        continue
                    op = by_name.get(occ)
                    if not op:
                        continue
                    alt = next((a for a in (op.get("parts") or [])
                                if a != seat and a in assign and has_room(a)), None)
                    if alt is not None:
                        unplace(seat, occ)
                        place(alt, occ)
                        place(seat, p["name"])
                        changed = True
                        break
                if p["name"] in used:
                    break

    bench = [p["name"] for p in players if p["name"] not in used]
    return [(n, assign[n]) for n in names], bench


def cycle_length(seats, players, locked=None, pools=None):
    """Distinct rotation days before the board repeats (so the day-stepper
    wraps).  It's the most turns any single scarce seat needs to show everyone
    eligible: a one-seat spot two players share needs 2 days; three, 3.  A seat's
    open capacity (after locks) divides its eligible pool.  Never less than 1."""
    seatlist = normalize_seats(seats)
    names = [n for n, _ in seatlist]
    locked = normalize_locked(locked, names)
    locked_names = {nm for v in locked.values() for nm in v}
    avail = [p for p in players if p.get("name") not in locked_names]
    best = 1
    for name, cap in seatlist:
        open_slots = cap - len(locked.get(name, []))
        if open_slots <= 0:
            continue
        elig = len(eligible_players(name, avail))
        if elig > open_slots:
            best = max(best, -(-elig // open_slots))          # ceil
    return best


def describe_seat_coverage(seats, players):
    """For the setup screen: ``[(seat, capacity, [eligible names]), ...]`` so the
    teacher can spot a seat nobody can cover, or one everyone piles onto."""
    return [(name, cap, [p["name"] for p in eligible_players(name, players)])
            for name, cap in normalize_seats(seats)]
