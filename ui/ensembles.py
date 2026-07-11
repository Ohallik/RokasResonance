"""
ui/ensembles.py - Shared "class / ensemble" vocabulary for a program.

These are the ensembles a teacher actually runs (not instrumentation), keyed to
their program type.  Used by the student manager, the performance dialog, and the
concert-program importer so they all offer the same choices.

Middle-school level for now; high-school users will get a different set later.
"""

BAND_ENSEMBLES      = ["Entry Band", "Intermediate Band", "Advanced Band", "Jazz 1", "Jazz 2"]
ORCHESTRA_ENSEMBLES = ["Entry Orchestra", "Intermediate Orchestra", "Advanced Orchestra"]
CHOIR_ENSEMBLES     = ["Entry Choir", "Intermediate Choir", "Advanced Choir"]

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


def ensembles_for(program_type: str):
    """The performing ensembles / classes for this program type."""
    if program_type == "choir":
        return CHOIR_ENSEMBLES
    if program_type == "orchestra":
        return ORCHESTRA_ENSEMBLES
    return BAND_ENSEMBLES


def progression_levels(program_type: str):
    """The ordered leveled classes a student moves UP through (Entry →
    Intermediate → Advanced).  Jazz / non-leveled ensembles are excluded — they
    aren't a single-grade progression."""
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
