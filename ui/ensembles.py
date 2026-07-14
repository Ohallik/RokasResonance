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
