"""
ui/ensembles.py - Shared "class / ensemble" vocabulary for a program.

These are the ensembles a teacher actually runs (not instrumentation), keyed to
their program type.  Used by the student manager, the performance dialog, and the
concert-program importer so they all offer the same choices.

Middle-school level for now; high-school users will get a different set later.
"""

# Fallback defaults, used only before a profile is loaded (or if a profile has
# no configured classes).  The REAL class list a teacher works with comes from
# their setup wizard via class_registry — see ensembles_for() below.
BAND_ENSEMBLES      = ["Entry Band", "Intermediate Band", "Advanced Band", "Jazz 1", "Jazz 2"]
ORCHESTRA_ENSEMBLES = ["Entry Orchestra", "Intermediate Orchestra", "Advanced Orchestra"]
CHOIR_ENSEMBLES     = ["Entry Choir", "Intermediate Choir", "Advanced Choir"]

# The active profile's base_dir, set once when a profile loads (main.py).  Lets
# ensembles_for() return the teacher's own configured classes everywhere without
# threading base_dir through every dialog.  Single active profile, so a module
# global is safe.
_current_base_dir = None


def set_current_profile(base_dir):
    """Point the shared class vocabulary at the loaded profile's classes."""
    global _current_base_dir
    _current_base_dir = base_dir


def _configured_labels(program_type, base_dir):
    """The teacher's own class labels from their setup, or None if unavailable."""
    if not base_dir:
        return None
    try:
        import class_registry
        labels = [c["label"] for c in class_registry.load_classes(base_dir, program_type)
                  if c.get("label")]
        return labels or None
    except Exception:
        return None

PERIOD_OPTIONS = ["1", "2", "3", "4", "5", "6", "7"]

BAND_INSTRUMENTS = [
    "Flute", "Oboe", "Bassoon", "Clarinet", "Bass Clarinet",
    "Alto Sax", "Tenor Sax", "Bari Sax",
    "Trumpet", "French Horn", "Trombone",
    "Baritone BC", "Baritone TC", "Euphonium BC", "Euphonium TC", "Tuba",
    "Percussion",
]
ORCHESTRA_INSTRUMENTS = [
    "Violin", "Violin 1", "Violin 2",
    "Viola", "Viola 1", "Viola 2",
    "Cello", "Cello 1", "Cello 2",
    "String Bass", "Harp", "Piano",
]
CHOIR_PARTS = ["Soprano", "Alto", "Tenor", "Baritone", "Bass"]

# Jazz-band instrument choices: everything from concert band plus the rhythm
# section.  Used for the per-student "Jazz Band Instrument" override (a Horn
# player who plays Guitar in Jazz 1, etc.).
JAZZ_INSTRUMENTS = BAND_INSTRUMENTS + [
    "Drums", "Vibraphone", "Piano", "Guitar", "Bass",
    "Violin", "Viola", "Cello", "String Bass", "Voice", "Other",
]


# What a 5th grader actually starts on, in the order a beginning teacher hands
# them out.  The rest of the list stays available underneath: a gifted child
# does occasionally turn up on oboe or french horn, and while those families
# almost always buy or rent privately, the option should not be missing.
FIFTH_GRADE_BAND_COMMON = [
    "Flute", "Clarinet", "Trumpet", "Trombone", "Percussion",
    "Baritone BC", "Baritone TC",
]
# Strings are sized rather than swapped, so the instrument list is short and the
# size field on the instrument carries 1/2, 3/4 and the rest.
FIFTH_GRADE_STRINGS_COMMON = ["Violin", "Viola", "Cello", "String Bass"]

# The choir some schools run before or after school.  Not a class anywhere in
# the district, so it is an ensemble a child is in as well as their instrument,
# never instead of it.
CHOIR_SUFFIX = "Choir"


def fifth_grade_instruments(program_type: str):
    """What a 5th grader can be recorded as playing.

    Strings are the four instruments and nothing else. The numbered entries in
    ORCHESTRA_INSTRUMENTS -- Violin 1, Violin 2, Viola 1 -- are PART
    assignments, which start at middle school; a 10-year-old plays the violin,
    not second violin, and offering the split here only invites a choice that
    means nothing yet.

    Band is ordered rather than filtered: the usual starters come first, and
    the rest of the concert band follows, because the rare gifted child really
    does turn up on oboe or french horn and has to be recordable. Those
    families almost always buy or rent privately, so the instrument seldom
    reaches the school cupboard -- but the child still plays it.
    """
    if program_type == "orchestra":
        return list(FIFTH_GRADE_STRINGS_COMMON) + ["Other"]
    rest = [i for i in BAND_INSTRUMENTS if i not in FIFTH_GRADE_BAND_COMMON]
    return list(FIFTH_GRADE_BAND_COMMON) + rest + ["Other"]


def choir_ensemble(site_name: str) -> str:
    """The choir group for one school, named the way its sections are."""
    return f"{(site_name or '').strip()}: {CHOIR_SUFFIX}"


def ensembles_for(program_type: str, base_dir=None):
    """The performing ensembles / classes for this program type.  Returns the
    teacher's OWN configured classes (from the setup wizard) whenever a profile
    is loaded; falls back to the built-in defaults only before that."""
    labels = _configured_labels(program_type, base_dir or _current_base_dir)
    if labels:
        return labels
    if program_type == "choir":
        return CHOIR_ENSEMBLES
    if program_type == "orchestra":
        return ORCHESTRA_ENSEMBLES
    return BAND_ENSEMBLES


def progression_levels(program_type: str, base_dir=None):
    """The ordered leveled classes a student moves UP through.  Uses the
    teacher's configured classes (excluding jazz, which isn't a single-grade
    progression) when available, else the built-in leveled defaults."""
    bd = base_dir or _current_base_dir
    if bd:
        try:
            import class_registry
            levels = [c["label"] for c in class_registry.load_classes(bd, program_type)
                      if c.get("label") and c.get("template") != "jazz"]
            if levels:
                return levels
        except Exception:
            pass
    if program_type == "choir":
        return list(CHOIR_ENSEMBLES)
    if program_type == "orchestra":
        return list(ORCHESTRA_ENSEMBLES)
    return ["Entry Band", "Intermediate Band", "Advanced Band"]


def instruments_for(program_type: str):
    """Primary/secondary instrument choices for the picker."""
    if program_type == "choir":
        return CHOIR_PARTS + ["Other"]
    if program_type == "orchestra":
        # String orchestra: strings only.  Numbered parts (Violin 1/2, …)
        # let directors zone and shuffle within a part.
        return ORCHESTRA_INSTRUMENTS + ["Other"]
    return BAND_INSTRUMENTS + ["Other"]


def roster_ensembles(main_db, school_year=None, site_id=None):
    """Every class name that actually appears on student records, in roster
    order.  This is what the data says, as opposed to what the setup wizard
    configured.  ``site_id`` limits it to one school's classes."""
    seen = []
    if main_db is None:
        return seen
    try:
        rows = main_db.get_students_for_email(school_year=school_year,
                                              site_id=site_id)
    except Exception:
        return seen
    for r in rows:
        try:
            raw = r["ensembles"]
        except Exception:
            raw = ""
        for e in (raw or "").split(","):
            e = e.strip()
            if e and e not in seen:
                seen.append(e)
    return seen


def selectable_ensembles(main_db, school_year=None, program_type="band",
                         base_dir=None, include_empty=False, site_id=None):
    """What a class picker should offer.

    The configured class list and the names actually on student records drift
    apart constantly and silently.  A roster imported from Synergy says "Entry
    Band"; the default registry says "MS Band (Entry)".  Offering only the
    registry names means every filter, export and count matches nothing — the
    picker looks fine and quietly returns zero students, which reads as "I have
    no flutes" rather than "these two lists don't line up".

    ``include_empty=False`` (the default, for FILTERING and COUNTING) offers
    only classes that actually have students — a class with nobody in it can
    only ever return zero, so listing it is noise.
    ``include_empty=True`` (for ASSIGNING and EDITING) also offers configured
    classes that are still empty, since putting the first student into one is
    exactly the point.

    Configured order first (that's the teacher's own ordering), then whatever
    else the roster mentions.  De-duplicated by class IDENTITY — a roster's
    "Entry Band" and the registry's "MS Band (Entry)" are one class, offered
    once, under the configured (canonical) spelling.
    """
    import class_registry as cr
    found = roster_ensembles(main_db, school_year, site_id=site_id)
    if site_id:
        # One school's own sections and choir, nothing configured for the
        # secondary program.  A Clyde Hill picker offering "Advanced Band"
        # is offering a class that cannot contain any of its children.
        return found
    configured = ensembles_for(program_type, base_dir)
    out, seen = [], set()

    def add(name):
        key = cr.class_identity(name)
        if key not in seen:
            seen.add(key)
            out.append(name)

    for e in configured:                     # set up AND populated → canonical
        if any(cr.same_class(e, f) for f in found):
            add(e)
    for f in found:                          # populated only (roster spelling)
        add(f)
    if include_empty or not out:
        # Configured-but-empty classes; also the fallback when the roster
        # names nothing at all, so a brand-new profile still has choices.
        for e in configured:
            add(e)
    return out


def display_class(name):
    """Short display form of one class name ("MS Band (Entry)" → "Entry")."""
    import class_registry as cr
    return cr.short_class_label(name)


def class_display_map(names):
    """{full name: display label} for a picker — short labels, unless two
    offered classes would collide (then those keep their full names)."""
    import class_registry as cr
    return cr.display_map(names)


def class_periods_for(main_db, school_year, ensemble):
    """The class periods ``ensemble`` actually meets, read from the roster.

    A period counts as a real section of this class only if it holds at least
    half as many of the class's students as its biggest section — otherwise a
    single student's OTHER class shows up as a phantom period.  Returns [] when
    nothing is known, which callers treat as "whole ensemble, no sections".

    Same rule the seating chart uses; kept here so the percussion sections, the
    agendas, and the charts all agree on what "Period 1" means.
    """
    from collections import Counter
    if not main_db or not ensemble:
        return []
    try:
        studs = main_db.get_students_for_email(school_year=school_year,
                                               ensemble=ensemble)
    except Exception:
        return []
    counts = Counter()
    for r in studs:
        for p in (r["class_periods"] or "").split(","):
            p = p.strip()
            if p:
                counts[p] += 1
    if not counts:
        return []
    top = max(counts.values())
    return sorted([p for p, c in counts.items() if c >= top * 0.5],
                  key=lambda x: (len(x), x))


# ── Score order ───────────────────────────────────────────────────────────────
# Directors read a roster top-of-score down (piccolo → tuba → percussion), never
# alphabetically.  Anything sorted or counted by instrument (the Student Manager
# "Instrument" column, the numbers-per-part count) uses this order so the list
# matches the score on the stand.

SCORE_ORDER = (
    ["Piccolo"] + BAND_INSTRUMENTS[:BAND_INSTRUMENTS.index("Percussion")]
    + ORCHESTRA_INSTRUMENTS
    + CHOIR_PARTS
    + ["Drums", "Vibraphone", "Guitar", "Bass", "Voice", "Percussion"]
)
_SCORE_RANK = {name.lower(): i for i, name in enumerate(SCORE_ORDER)}


def instrument_sort_key(name: str):
    """``(rank, name)`` for one instrument, in score order.

    Known instruments rank by position in the score; unrecognized ones (a
    teacher typed "Contra Clarinet") fall in after them but before blanks, so
    the sort stays total and nothing silently disappears."""
    clean = (name or "").strip()
    if not clean:
        return (9999, "")                     # blank instruments sort last
    rank = _SCORE_RANK.get(clean.lower())
    if rank is None:
        return (5000, clean.lower())          # unknown but named
    return (rank, clean.lower())
