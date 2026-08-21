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


_class_site_cache = {}          # (base_dir, mtime) -> {identity: site_id}


def class_school(label, base_dir=None, program_type=None):
    """The school the current profile binds this class to, or None.

    Called per student per group when building rosters, so it caches the
    registry keyed by settings.json's mtime -- saving Manage Classes changes
    the mtime and the next call reloads.
    """
    import os as _os
    bd = base_dir or _current_base_dir
    if not bd:
        return None
    try:
        mtime = _os.path.getmtime(_os.path.join(bd, "settings.json"))
    except OSError:
        return None
    import class_registry as cr
    key = (bd, mtime)
    cached = _class_site_cache.get(key)
    if cached is None:
        try:
            from ui.settings_dialog import load_settings
            pt = program_type or (load_settings(bd).get("teacher")
                                  or {}).get("program_type", "band")
            classes = cr.load_classes(bd, pt)
        except Exception:
            classes = []
        cached = {}
        for k in classes:
            ident = cr.class_identity(k.get("label") or "")
            if not ident:
                continue
            # Ambiguity (same identity, two schools) resolves to None.
            if ident in cached and cached[ident] != k.get("site_id"):
                cached[ident] = None
            else:
                cached[ident] = k.get("site_id")
        _class_site_cache.clear()          # one profile at a time
        _class_site_cache[key] = cached
    return cached.get(cr.class_identity(label))


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

# Period 0 is before school.  Every jazz band in the district meets then,
# whatever the program, so it is not a band-only option.  Elementary has no
# periods at all and never sees this list.
PERIOD_OPTIONS = ["0", "1", "2", "3", "4", "5", "6", "7"]

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


SECTION_NUMBERS = (1, 2)


def site_sections(site_name: str):
    """The two sections every elementary school runs, named after the school."""
    name = (site_name or "").strip()
    return [f"{name}: Section {n}" for n in SECTION_NUMBERS]


def site_groups(db, site, school_year=None):
    """Every group a 5th grade school can offer.

    Section 1 and Section 2 always, whether or not anybody is in them yet --
    at the start of the year nobody is, and a picker that is empty until the
    roster arrives is a picker that looks broken on the day it is first opened.

    Choir only when at least one child is actually in it. Most schools do not
    run one, and offering an empty choir everywhere would be the same mistake
    in the other direction.
    """
    site = dict(site)
    name = site.get("name") or ""
    groups = site_sections(name)
    choir = choir_ensemble(name)
    try:
        rows = db.get_students_for_email(school_year=school_year,
                                         site_id=site.get("id"))
    except Exception:
        rows = []
    lower = choir.lower()
    for r in rows:
        held = (r["ensembles"] if "ensembles" in r.keys() else "") or ""
        if any(p.strip().lower() == lower for p in held.split(",")):
            groups.append(choir)
            break
    return groups


def all_class_options(db, base_dir=None, program_type="band", school_year=None):
    """Every group a whole-class action can be pointed at -- a fee, a field
    trip -- named the way the roster names it.

    Three sources, because no one of them is complete on its own:

      * Each elementary school's own sections, always, and always carrying the
        school's name.  Six schools each have a Section 1, and "Section 1" on
        its own is not an answer to which children get the bill.
      * What this year's students are ACTUALLY in.  The configured class list
        is what the teacher told the setup wizard; this is what the data holds,
        and a fee lands on the second one.  A teacher whose roster says "Entry
        Band" was being offered "MS Band (Entry)" and nothing else.
      * The configured classes, so a class nobody has been imported into yet
        can still be picked.  At the start of a year that is all of them.

    De-duplicated by class identity, so "Entry Band" and "MS Band (Entry)" do
    not both appear -- but two schools' Section 1 do, because they are two
    different sets of children.
    """
    from class_registry import class_identity
    elementary, rest, seen = [], [], set()

    def add(bucket, label):
        label = (label or "").strip()
        if not label:
            return
        key = class_identity(label)
        if key in seen:
            return
        seen.add(key)
        bucket.append(label)

    if school_year is None:
        try:
            school_year = db.current_school_year()
        except Exception:
            school_year = None

    try:
        for site in db.get_sites(level="elementary"):
            for g in site_groups(db, site, school_year):
                add(elementary, g)
    except Exception:
        pass
    try:
        rows = list(db.get_all_students(school_year=school_year))
        if not rows and school_year:
            # Nothing on this year's roster yet -- see selectable_ensembles.
            rows = list(db.get_all_students())
        for stu in rows:
            held = stu["ensembles"] if "ensembles" in stu.keys() else ""
            for part in (held or "").split(","):
                add(rest, part)
    except Exception:
        pass
    # The configured class list belongs to a SECONDARY program.  At elementary
    # the schools' own sections ARE the class list, and the registry's one
    # placeholder ("Beginning Band") is worse than useless: same_class treats
    # "beginning" and "entry" as one level, so it wins the canonical spelling
    # and a roster full of "Entry Band" is displayed as a class that does not
    # exist.  Secondary classes come from the roster in their own spelling.
    if program_type != "elementary":
        try:
            import class_registry
            for c in class_registry.load_classes(base_dir, program_type):
                add(rest, c["label"])
        except Exception:
            pass
    return elementary + sorted(rest) or list(ensembles_for(program_type, base_dir))


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
    reaches the school inventory -- but the child still plays it.
    """
    if program_type == "orchestra":
        return list(FIFTH_GRADE_STRINGS_COMMON) + ["Other"]
    rest = [i for i in BAND_INSTRUMENTS if i not in FIFTH_GRADE_BAND_COMMON]
    return list(FIFTH_GRADE_BAND_COMMON) + rest + ["Other"]


# Which program a class TEMPLATE belongs to.  "generic", "guitar" and
# "steel_drum" are deliberately absent: they say nothing about band vs strings,
# so a class using one falls through to the next clue instead of being guessed.
_TEMPLATE_PROGRAM = {
    "orch_5": "orchestra", "orch_mshs": "orchestra",
    "choir_mshs": "choir",
    "band_5": "band", "band_entry": "band", "band_intermediate": "band",
    "band_advanced": "band", "hs_band_winds": "band", "hs_band_perc": "band",
    "jazz": "band",
}
# Templates that only exist at 5th grade.
_TEMPLATE_ELEMENTARY = {"band_5", "orch_5"}

# Program words that can appear in a class's own NAME.
_NAME_PROGRAM = {"band": "band", "orchestra": "orchestra", "strings": "orchestra",
                 "choir": "choir", "chorus": "choir"}


def site_of_class(main_db, label, base_dir=None):
    """The school a class belongs to, as a site row, or None.

    Two ways a class names its school, and a teacher may have both: bound to
    one in Manage Classes (secondary), or carrying the school in its own name
    the way every elementary section does ("Medina Elementary School:
    Section 1").
    """
    if main_db is None or not (label or "").strip():
        return None
    try:
        sites = [dict(s) for s in main_db.get_sites()]
    except Exception:
        return None
    try:
        bound = class_school(label, base_dir=base_dir)
    except Exception:
        bound = None
    if bound:
        for s in sites:
            if s.get("id") == bound:
                return s
    low = label.strip().lower()
    for s in sites:
        name = (s.get("name") or "").strip().lower()
        if name and low.startswith(name + ":"):
            return s
    return None


def class_program(main_db, label, base_dir=None, program_type=None):
    """``(program, level)`` for ONE class — the two facts a screen needs before
    it can stop assuming concert band.

    ``program`` is "band", "orchestra" or "choir"; ``level`` is "elementary" or
    "secondary".  Roka was written band-first, so every screen that offers
    instruments, sections or placement options used to read the PROFILE's
    program type — one value for a teacher who may run a 5th grade strings
    class at one building and a concert band at another.  The class is the
    thing that has a program; the profile only has a default.

    In order of how much each clue actually knows:

      1. The class's template in Manage Classes.  "MS/HS Orchestra" is a
         teacher saying so directly, and it is the only clue that distinguishes
         two classes in the SAME building -- a middle school runs band and
         orchestra down the hall from each other, so the school's own program
         cannot separate them.
      2. A program word in the class's own name ("Entry Strings", "5th Grade
         Orchestra"), which is what an imported roster usually carries.
      3. The school the class belongs to.  Elementary sections are named after
         their school and each school records whether it is band or strings.
      4. The profile's program type, when it names a program at all
         ("elementary" does not).

    Band last, because it is the assumption this function exists to stop.
    """
    program = level = None
    label = (label or "").strip()

    if label:
        try:
            import class_registry as cr
            for k in cr.load_classes(base_dir or _current_base_dir,
                                     program_type or "band"):
                if cr.same_class(k.get("label"), label):
                    tmpl = k.get("template")
                    program = _TEMPLATE_PROGRAM.get(tmpl)
                    if tmpl in _TEMPLATE_ELEMENTARY:
                        level = "elementary"
                    break
        except Exception:
            pass

    if not program and label:
        try:
            import class_registry as cr
            for word in cr._name_words(label):
                if word in _NAME_PROGRAM:
                    program = _NAME_PROGRAM[word]
                    break
        except Exception:
            pass

    if not program or not level:
        site = site_of_class(main_db, label, base_dir)
        if site:
            if not level:
                level = site.get("level") or None
            if not program:
                program = (site.get("program") or "").strip().lower() or None

    if not program and program_type in ("band", "orchestra", "choir"):
        program = program_type
    if not level and program_type == "elementary":
        level = "elementary"

    return (program or "band", level or "secondary")


def seating_instruments(program, level="secondary", numbered_parts=False,
                        piano=False):
    """The instruments a seating chart should offer for ONE class.

    A strings class lists strings.  Nothing else -- no flute, no "Percussion",
    and none of the band-shaped options that go with them.

    Only the VIOLINS divide.  Firsts and seconds are a violin idea; violas,
    cellos and basses are one section that happens to divisi on the page, and
    offering "Cello 1 / Cello 2" invites a seating split that orchestras do not
    make.  It is a middle and high school choice even for the violins, and off
    by default: a 10-year-old plays the violin, not second violin -- the rule
    ``fifth_grade_instruments`` already follows on the roster.

    Harp is not offered at all (school orchestras do not have one).  Piano does
    turn up, rarely, so it is its own toggle rather than something bundled in
    with the part split.
    """
    if program == "choir":
        return list(CHOIR_PARTS) + ["Other"]
    if program == "orchestra":
        out = list(FIFTH_GRADE_STRINGS_COMMON)      # Violin, Viola, Cello, Bass
        if numbered_parts and level != "elementary":
            i = out.index("Violin") + 1
            out[i:i] = ["Violin 1", "Violin 2"]
        if piano:
            out.append("Piano")
        return out + ["Other"]
    if level == "elementary":
        return fifth_grade_instruments("band")
    return list(BAND_INSTRUMENTS) + ["Other"]


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


def site_groups_for(main_db, site_id, school_year=None):
    """One school's own sections, looked up by id.  Used when that school has
    no students yet -- the sections exist before anybody is in them, and a
    picker that is empty until the roster arrives looks broken on the day it
    is first opened."""
    try:
        site = main_db.get_site(site_id)
        return site_groups(main_db, site, school_year) if site else []
    except Exception:
        return []


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
    if not found and school_year:
        # The year being asked about has no students on it yet -- which is
        # exactly the situation when somebody is IMPORTING into it, and the
        # moment they most need the class list.  Falling back to every year
        # they have taught offers the names their own data uses instead of the
        # bare program default.
        found = roster_ensembles(main_db, None, site_id=site_id)
    if site_id:
        level = None
        try:
            site = main_db.get_site(site_id)
            level = dict(site).get("level") if site else None
        except Exception:
            pass
        if level == "elementary":
            # One school's own sections and choir, nothing configured for the
            # secondary program.  A Clyde Hill picker offering "Advanced Band"
            # is offering a class that cannot contain any of its children.
            return found or site_groups_for(main_db, site_id, school_year)
        # A SECONDARY school scoped by site: its roster's own classes, plus
        # the configured classes that belong to it (bound to it in Manage
        # Classes, or unbound).  Treating every site_id as elementary was
        # offering Tillicum's roster import "Section 1 / Section 2", which
        # no middle school has.
        import class_registry as cr
        configured = [c for c in ensembles_for(program_type, base_dir)
                      if class_school(c, base_dir) in (None, site_id)]
        out2, seen2 = [], set()

        def add2(name):
            key = cr.class_identity(name)
            if key not in seen2:
                seen2.add(key)
                out2.append(name)
        for e in configured:
            if any(cr.same_class(e, f) for f in found):
                add2(e)
        for f in found:
            add2(f)
        if include_empty or not out2:
            for e in configured:
                add2(e)
        return out2

    # Each elementary school's own sections, whether or not anybody is in them
    # yet.  A teacher with both kinds of school needs both halves; before this,
    # whichever one their program type named was the only one they saw.
    elementary = []
    try:
        for site in main_db.get_sites(level="elementary"):
            for g in site_groups(main_db, site, school_year):
                if g not in elementary:
                    elementary.append(g)
    except Exception:
        pass

    configured = [] if program_type == "elementary" \
        else ensembles_for(program_type, base_dir)

    out, seen = [], set()

    def add(name):
        key = cr.class_identity(name)
        if key not in seen:
            seen.add(key)
            out.append(name)

    for g in elementary:                     # a school's own sections, always
        add(g)
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
