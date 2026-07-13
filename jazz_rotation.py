"""
jazz_rotation.py - Rhythm-section assignment logic for jazz ensembles.

Unlike the concert-percussion rotation (fixed mallet/snare/timpani seats with an
earn-based mallets-only phase), a jazz rhythm section is *variable*: the teacher
lists the SEATS in play (Drum set, Vibraphone, Piano, Electric piano, Bass,
Guitar, and any custom part like a doubled tenor sax) and, for each PLAYER, the
subset of those seats they can actually cover.  Two things then happen:

  * WARM-UPS / a brand-new tune — nobody is committed yet, so the section
    ROTATES: each day the eligible players cycle through the open seats so the
    kids who can play, say, either drum set or vibraphone take turns on each.

  * An ESTABLISHED tune — once she's auditioned and picked an actual drummer,
    pianist, etc., those seats are LOCKED to specific players for that song and
    stop rotating.  A song may lock some seats and leave others rotating.

This module is pure logic (no UI, no I/O) so it can be unit-tested and reused by
both the Jazz tool tab and the daily-agenda rhythm panel.  A "player" is a dict
``{"name": str, "parts": [seat, ...]}``; a "lock" is a map ``{seat: name}``.
Everything is deterministic — the same (seats, players, locks, day) always gives
the same board, so the agenda and the tool always agree.
"""

# Primary rhythm-section seats offered when a new jazz ensemble is created.  She
# can rename/add/remove (e.g. add "Electric piano" to seat a second pianist, or
# "Tenor Sax" for a multi-instrumentalist).  Order here is the board order.
DEFAULT_SEATS = ["Drum set", "Piano", "Bass", "Guitar", "Vibraphone"]

# A larger menu the seat editor offers as quick-add buttons (still fully
# editable / free-text).  "Aux percussion" covers congas/shaker/etc.
COMMON_SEATS = ["Drum set", "Piano", "Electric piano", "Bass", "Guitar",
                "Vibraphone", "Aux percussion", "Tenor Sax", "Trombone",
                "Trumpet", "Vocals"]


def _clean_seats(seats):
    """Ordered, de-duplicated, non-blank seat list."""
    out, seen = [], set()
    for s in seats or []:
        s = (s or "").strip()
        if s and s.lower() not in seen:
            seen.add(s.lower())
            out.append(s)
    return out


def eligible_players(seat, players, used=None):
    """Players who can cover ``seat`` and aren't already placed (``used`` is a
    set of names).  Order follows the roster order (which the teacher controls)
    so the rotation is stable."""
    used = used or set()
    return [p for p in players
            if seat in (p.get("parts") or []) and p.get("name") not in used]


def day_assignments(seats, players, day=1, locked=None):
    """Assign a player to each seat for rotation ``day`` (1-based).

    ``locked`` (``{seat: name}``) pins seats to specific players — those seats
    don't rotate, and a locked player is unavailable for any other seat that
    day.  Remaining seats rotate: for each open seat the eligible players (who
    can play it and aren't already placed today) are cycled by ``day`` so the
    assignment advances each day and, over a cycle, everyone who can play a seat
    gets a turn on it.

    Returns ``(assignments, bench)`` where ``assignments`` is an ordered list of
    ``(seat, name_or_None)`` (None = nobody eligible/left for that seat) and
    ``bench`` is the list of player names not placed anywhere today.
    """
    seats = _clean_seats(seats)
    locked = {s: n for s, n in (locked or {}).items() if s in seats and n}
    if day < 1:
        day = 1

    names = {p.get("name") for p in players}
    assigned = {}
    used = set()

    # 1) Locked seats first (only if that player is actually on the roster).
    for seat in seats:
        who = locked.get(seat)
        if who and who in names and who not in used:
            assigned[seat] = who
            used.add(who)

    # 2) Rotate the remaining (open) seats.  ``si`` staggers each seat's pick so
    #    two seats sharing an eligible pool don't both grab the same first
    #    player before the day offset advances.
    open_seats = [s for s in seats if s not in assigned]
    for si, seat in enumerate(open_seats):
        elig = eligible_players(seat, players, used)
        if not elig:
            assigned[seat] = None
            continue
        pick = elig[(day - 1 + si) % len(elig)]
        assigned[seat] = pick["name"]
        used.add(pick["name"])

    bench = [p["name"] for p in players if p.get("name") not in used]
    return [(seat, assigned.get(seat)) for seat in seats], bench


def cycle_length(seats, players, locked=None):
    """A sensible number of distinct rotation days before the board repeats, so
    the day-stepper wraps instead of running forever.

    It's the largest eligible-player pool over the OPEN (non-locked) seats: a
    seat two players can share needs 2 days to show both; three needs 3.  Locked
    seats don't rotate, so they don't count.  Never less than 1.
    """
    seats = _clean_seats(seats)
    locked = {s: n for s, n in (locked or {}).items() if s in seats and n}
    open_seats = [s for s in seats if s not in locked]
    best = 1
    # Approximate the interaction between seats by removing locked players from
    # the pools (they can't rotate elsewhere).
    locked_names = set(locked.values())
    avail = [p for p in players if p.get("name") not in locked_names]
    for seat in open_seats:
        best = max(best, len(eligible_players(seat, avail)))
    return best


def describe_seat_coverage(seats, players):
    """For the setup screen: ``[(seat, [eligible names]), ...]`` so the teacher
    can spot a seat with nobody who can play it, or one everyone piles onto."""
    seats = _clean_seats(seats)
    return [(seat, [p["name"] for p in eligible_players(seat, players)])
            for seat in seats]
