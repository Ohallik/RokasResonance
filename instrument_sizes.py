"""
instrument_sizes.py - Instrument sizes, and the family an instrument belongs to.

School string instruments come in fractional sizes (a 1/2 violin for a small
sixth grader, a 3/4 cello) and violas are measured across the back in inches.
That is real inventory data a director sorts and pulls by, so it lives in its
own ``instruments.size`` column rather than being written into the instrument's
name.  This module supplies the choices offered per instrument and the order
they sort in, which is NOT alphabetical: "1/2" belongs between "1/4" and "3/4",
and "10 inch" belongs before "9 inch" nowhere at all.
"""

import re

# ── Families ─────────────────────────────────────────────────────────────────
# The canonical vocabulary for instruments.category.  Instrument NAMES belong in
# instruments.description; a family here keeps every inventory sortable the same
# way regardless of which program set it up.
FAMILIES = [
    "Woodwind", "Brass", "Percussion", "Mallets", "Strings",
    "Guitar/Bass", "Keyboard", "Electronics", "Other",
]

# Instrument name -> family.  Longest, most specific keys first when matching so
# "Bass Clarinet" beats "Clarinet" and "String Bass" is never read as a drum.
_FAMILY_BY_KEYWORD = [
    ("Strings", ["violin", "viola", "cello", "string bass", "double bass",
                 "upright bass", "contrabass", "harp", "fiddle"]),
    ("Woodwind", ["piccolo", "flute", "oboe", "clarinet", "bassoon",
                  "saxophone", "sax", "recorder", "english horn"]),
    ("Brass", ["trumpet", "cornet", "flugel", "french horn", "mellophone",
               "trombone", "baritone", "euphonium", "tuba", "sousaphone"]),
    ("Mallets", ["marimba", "xylophone", "vibraphone", "glockenspiel", "bells",
                 "chimes", "orchestra bells"]),
    ("Percussion", ["drum", "timpani", "cymbal", "percussion", "tambourine",
                    "triangle", "conga", "bongo", "djembe", "gong"]),
    ("Guitar/Bass", ["guitar", "bass guitar", "ukulele", "banjo", "mandolin"]),
    ("Keyboard", ["piano", "keyboard", "synth", "organ", "celesta"]),
    ("Electronics", ["amp", "mixer", "microphone", "speaker", "tuner",
                     "metronome", "interface", "cable"]),
]

# "French horn" contains "horn"; "English horn" is a woodwind.  Checked first.
_FAMILY_OVERRIDES = [
    ("Woodwind", ["english horn", "basset horn"]),
    ("Brass", ["french horn", "alto horn", "tenor horn"]),
    ("Guitar/Bass", ["bass guitar", "electric bass"]),
    ("Strings", ["string bass", "double bass", "upright bass"]),
    ("Percussion", ["bass drum"]),
    ("Woodwind", ["bass clarinet"]),
]


def family_for(name: str) -> str:
    """Best-guess family for an instrument name.  "" when nothing matches."""
    low = " ".join((name or "").strip().lower().split())
    if not low:
        return ""
    for fam, words in _FAMILY_OVERRIDES:
        if any(w in low for w in words):
            return fam
    for fam, words in _FAMILY_BY_KEYWORD:
        if any(w in low for w in words):
            return fam
    return ""


# ── Sizes ────────────────────────────────────────────────────────────────────
# Smallest to largest, which is the order they are offered and sorted in.
FRACTIONAL_SIZES = ["1/16", "1/10", "1/8", "1/4", "1/2", "3/4", "7/8", "4/4 (full)"]
VIOLA_SIZES = ['12"', '13"', '14"', '15"', '15.5"', '16"', '16.5"']
BASS_SIZES = ["1/8", "1/4", "1/2", "3/4", "7/8", "4/4 (full)"]

# Which list a given instrument should offer.
_SIZE_CHOICES = [
    (("viola",), VIOLA_SIZES),
    (("string bass", "double bass", "upright bass", "contrabass"), BASS_SIZES),
    (("violin", "cello", "fiddle"), FRACTIONAL_SIZES),
]


def sizes_for(instrument: str, family: str = "") -> list:
    """The common sizes to offer for this instrument.  Empty when size is not a
    thing that instrument comes in, so the field can stay out of the way."""
    low = " ".join((instrument or "").strip().lower().split())
    for words, choices in _SIZE_CHOICES:
        if any(w in low for w in words):
            return list(choices)
    if (family or "").strip().lower() == "strings":
        return list(FRACTIONAL_SIZES)
    return []


_FRACTION_RE = re.compile(r"^\s*(\d+)\s*/\s*(\d+)")
_INCH_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(?:\"|''|in\b|inch)", re.IGNORECASE)


def size_sort_key(size: str):
    """Order sizes smallest to largest.  Fractions sort by value, inches by
    number, and anything unrecognized sorts last, alphabetically, so a typed-in
    oddity never disappears or jumps to the front."""
    s = (size or "").strip()
    if not s:
        return (3, 0.0, "")          # blanks last
    m = _FRACTION_RE.match(s)
    if m:
        den = int(m.group(2)) or 1
        return (0, int(m.group(1)) / den, "")
    m = _INCH_RE.match(s)
    if m:
        return (1, float(m.group(1)), "")
    if s.lower().startswith("full"):
        return (0, 1.0, "")
    return (2, 0.0, s.lower())


def normalize_size(size: str) -> str:
    """Tidy a hand-typed size ("3 / 4", "14 in") into the offered spelling."""
    s = " ".join((size or "").strip().split())
    if not s:
        return ""
    if s.lower() in ("full", "full size", "full-size"):
        return "4/4 (full)"
    m = _FRACTION_RE.match(s)
    if m:
        frac = f"{int(m.group(1))}/{int(m.group(2))}"
        return "4/4 (full)" if frac == "4/4" else frac
    m = _INCH_RE.match(s)
    if m:
        num = m.group(1).rstrip("0").rstrip(".") if "." in m.group(1) else m.group(1)
        return f'{num}"'
    return s


# Everything a size can be made of: the measurement itself plus the words that
# decorate one.  A value built only from these is a size and nothing more.
_SIZE_TOKEN_RE = re.compile(
    r"\d+\s*/\s*\d+"                                  # 3/4
    r"|\d+(?:\.\d+)?\s*(?:\"|''|in\b|inch(?:es)?\b)"   # 14", 15.5 inch
    r"|\bfull\b|\bsize\b|\(|\)|-|,",
    re.IGNORECASE)


def base_type(description: str) -> str:
    """The instrument without its variant: "Saxophone - Eb Alto" -> "saxophone".
    This is what makes a trumpet swappable for another trumpet but not for a
    trombone."""
    d = " ".join((description or "").strip().lower().split())
    return d.split(" - ")[0].strip()


def type_rank(wanted: str, candidate: str) -> int:
    """How good a substitute `candidate` is for `wanted`: 0 identical,
    1 the same instrument in another variant, 2 merely the same family,
    3 unrelated.  Used to order the swap list so the closest match is first."""
    w = " ".join((wanted or "").strip().lower().split())
    c = " ".join((candidate or "").strip().lower().split())
    if not w or not c:
        return 3
    if w == c:
        return 0
    if base_type(w) and base_type(w) == base_type(c):
        return 1
    fw, fc = family_for(w), family_for(c)
    if fw and fw == fc:
        return 2
    return 3


def smallest_larger_than(size: str, candidates):
    """The smallest of `candidates` that is bigger than `size`, or None.

    Deliberately not "the next size in the catalog": hardly any school owns a
    7/8 violin, so a student outgrowing a 3/4 should be offered the 4/4 that is
    actually on the shelf rather than told nothing is available."""
    key = size_sort_key(normalize_size(size))
    bigger = [c for c in candidates if size_sort_key(normalize_size(c)) > key]
    if not bigger:
        return None
    return min(bigger, key=lambda c: size_sort_key(normalize_size(c)))


def looks_like_size(text: str) -> bool:
    """True when a value is ONLY a size, which is the signature of an inventory
    that put the size where the instrument's name belongs."""
    s = " ".join((text or "").strip().split())
    if not s:
        return False
    return not _SIZE_TOKEN_RE.sub("", s).strip()
