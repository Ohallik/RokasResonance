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


class _History:
    """What the rotation has already handed out, day by day, so a turn goes
    to whoever has waited longest rather than to whoever happens to sit at a
    given index in today's eligible list.

    ``turns[seat][name]`` counts days on that seat, ``last[seat][name]`` is the
    most recent day they held it, ``seated[name]`` is days placed anywhere."""

    def __init__(self):
        self.turns = {}
        self.last = {}
        self.seated = {}

    def record(self, day, assignments):
        for seat, names in assignments:
            t = self.turns.setdefault(seat, {})
            l = self.last.setdefault(seat, {})
            for nm in names:
                t[nm] = t.get(nm, 0) + 1
                l[nm] = day
                self.seated[nm] = self.seated.get(nm, 0) + 1

    def key(self, seat, name, roster_index):
        """Sort key: fewest turns on this seat, then the longest wait since the
        last one, then fewest days seated anywhere, then roster order."""
        return (self.turns.get(seat, {}).get(name, 0),
                self.last.get(seat, {}).get(name, 0),
                self.seated.get(name, 0),
                roster_index)


def _assign_one_day(seats, players, day, locked, pools, hist):
    """One day's board given the history so far — see day_assignments."""
    seatlist = normalize_seats(seats)
    names = [n for n, _ in seatlist]
    caps = {n: c for n, c in seatlist}
    present = {p.get("name") for p in players}
    pool_list = normalize_pools(pools, names)
    seat_pool = {s: p["name"] for p in pool_list for s in p["seats"]}
    pool_limit = {p["name"]: p["limit"] for p in pool_list}
    pool_use = {p["name"]: 0 for p in pool_list}
    locked = normalize_locked(locked, names)
    roster_index = {p.get("name"): i for i, p in enumerate(players)}

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

    # 2) Rotate — drum set first, then the other scarce (small-capacity) seats.
    #    Each open slot goes to the eligible player who has had the FEWEST
    #    turns on that seat (then the longest wait), so every pianist gets to
    #    the piano no matter how many drummers double on it.
    def priority(item):
        n, c = item
        return (0 if n.strip().lower() in DRUM_SEATS else 1, c, names.index(n))

    for seat, _cap in sorted(seatlist, key=priority):
        while has_room(seat):
            elig = eligible_players(seat, players, used)
            if not elig:
                break
            elig.sort(key=lambda p: hist.key(seat, p["name"],
                                             roster_index.get(p["name"], 0)))
            place(seat, elig[0]["name"])

    # 3) Rescue pass — a player may still be benched only because a seat they
    #    can play is full of players who each have somewhere ELSE to go (e.g. a
    #    piano-only student stuck behind a pianist who also plays vibes).
    #    Shuffle one movable occupant out so the stuck player gets a seat.
    #    Repeats until no further rescue is possible.
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


def _simulate(seats, players, days, locked=None, pools=None):
    """Boards for days 1..``days`` in order, each built on what came before.
    Yields ``(day, assignments, bench, hist)``."""
    hist = _History()
    for d in range(1, max(1, days) + 1):
        asg, bench = _assign_one_day(seats, players, d, locked, pools, hist)
        hist.record(d, asg)
        yield d, asg, bench, hist


def _memo_key(*parts):
    import json
    try:
        return json.dumps(parts, sort_keys=True, default=str)
    except (TypeError, ValueError):
        return None


_MEMO = {}


def _memoized(key, compute):
    """Same inputs, same answer — remembered, because the agenda banner, the
    Present window and an export all ask for today's board in one go."""
    if key is None:
        return compute()
    hit = _MEMO.get(key)
    if hit is None:
        if len(_MEMO) > 512:
            _MEMO.clear()
        hit = _MEMO[key] = compute()
    return hit


def day_assignments(seats, players, day=1, locked=None, pools=None):
    """Assign players to seats for rotation ``day`` (1-based).

    Order of operations:
      1. Locked seats (a song's auditioned players) are pinned first, consuming
         capacity — and, if the seat is in a pool, a slot of that pool.
      2. Scarce one-at-a-time seats are filled first (drum set before anything,
         then by capacity).  Each slot goes to the eligible player with the
         fewest turns on that seat so far, ties to whoever has waited longest,
         so turns genuinely rotate through everyone eligible — a student who
         doubles on drums and piano no longer knocks a piano-only student out
         of the piano rotation for good.
      3. Anyone still benched behind a movable occupant is rescued.

    The board for a day is built by replaying the days before it, so it is
    deterministic — the same inputs always give the same board — and the
    agenda and the Jazz tool always agree.

    ``locked`` may map a seat to one name or a list (up to its capacity); pools
    ({"name","limit","seats"}) cap the TOTAL players across their seats (e.g. 3
    amps split across Bass + Guitar).

    Returns ``(assignments, bench)`` — ``assignments`` is an ordered list of
    ``(seat, [names])`` (a list because a seat may hold several) and ``bench`` is
    the players not placed anywhere.
    """
    if day < 1:
        day = 1

    def compute():
        asg, bench = [], [p.get("name") for p in players]
        for _d, asg, bench, _h in _simulate(seats, players, day, locked, pools):
            pass
        return asg, bench

    asg, bench = _memoized(_memo_key("day", seats, players, day, locked, pools),
                           compute)
    return [(s, list(n)) for s, n in asg], list(bench)


# The longest cycle worth looking for.  Two drummers and three pianists need
# six days for everyone to come out even; a section would have to be very
# lopsided to need more than this.
_MAX_CYCLE = 120


def cycle_length(seats, players, locked=None, pools=None):
    """Distinct rotation days before the board repeats (so the day-stepper
    wraps): the first day on which every rotating seat has given each of its
    eligible players the same number of turns.  Two drummers alone need 2
    days; two drummers and three pianists need 6, so that the drummers come
    out 3 and 3 and the pianists 2, 2 and 2.  Never less than 1.

    A seat nobody has to wait for (everyone eligible fits at once) never
    lengthens the cycle.  If no day within the search window comes out even —
    the only drummer also wants a piano turn, say — the fairest day found is
    used instead."""
    seatlist = normalize_seats(seats)
    names = [n for n, _ in seatlist]
    locked = normalize_locked(locked, names)
    locked_names = {nm for v in locked.values() for nm in v}
    avail = [p for p in players if p.get("name") not in locked_names]
    rotating = {}
    for name, cap in seatlist:
        open_slots = cap - len(locked.get(name, []))
        if open_slots <= 0:
            continue
        elig = [p["name"] for p in eligible_players(name, avail)]
        if len(elig) > open_slots:
            rotating[name] = elig
    if not rotating:
        return 1

    def compute():
        best_day, best_spread = 1, None
        for d, _asg, _bench, hist in _simulate(seats, players, _MAX_CYCLE,
                                               locked, pools):
            spread = 0
            for seat, elig in rotating.items():
                counts = [hist.turns.get(seat, {}).get(nm, 0) for nm in elig]
                spread += max(counts) - min(counts)
            if spread == 0:
                return d
            if best_spread is None or spread < best_spread:
                best_day, best_spread = d, spread
        return best_day

    return _memoized(_memo_key("cycle", seats, players, locked, pools), compute)


def describe_seat_coverage(seats, players):
    """For the setup screen: ``[(seat, capacity, [eligible names]), ...]`` so the
    teacher can spot a seat nobody can cover, or one everyone piles onto."""
    return [(name, cap, [p["name"] for p in eligible_players(name, players)])
            for name, cap in normalize_seats(seats)]
