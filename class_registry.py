"""
class_registry.py - The teacher-configurable list of classes that get an agenda tab.

Historically the four agenda classes (Entry / Intermediate / Advanced Band + Jazz)
were hard-coded in three places at once.  This module makes them DATA: a per-
teacher list of "class" dicts, stored in the profile's ``settings.json`` under
``"classes"``.  Each class points at a TEMPLATE that supplies its default
behavior (which warm-up source, method book, whether it has a percussion section,
etc.), so the existing band pedagogy is preserved unchanged — the default band
teacher simply gets the same four classes they always had — while choir, orchestra
and one-off clubs (Vocal Jazz, Mariachi, Steel Drum, a Bass Ensemble, HS Chamber /
Chorale / Sinfonia / Guitar / Piano …) can add their own.

A class dict:
    {
      "id":        stable key — the agenda storage group_key (never reuse/rename)
      "label":     tab label ("Entry Band", "Chamber Choir", …)
      "template":  one of TEMPLATES below (drives the default day + UI)
      "ensemble":  concert-repertoire match keyword (which pieces to pull)
      "book":      method book 1 / 2 / None (band templates only)
      "percussion": show a percussion rotation for this class (band only)
    }

Only the fields a class overrides need to be stored; everything else falls back
to the template.  ``class_config`` merges the two into the flat dict the agenda
view consumes.
"""

# ── Templates ─────────────────────────────────────────────────────────────────
# Each template is the reusable "kind" of class.  ``class_type`` is the percussion
# grouping token ("entry" / "int_adv" / None) mapped to percussion_rotation
# constants by the view; ``book`` is the default Standard of Excellence book.
TEMPLATES = {
    "generic": {
        "label": "General", "book": None, "class_type": None, "percussion": False,
        "desc": "Blank warm-up + sheet music. For any class or club you run your "
                "own way (no percussion rotation).",
    },
    "band_5": {
        "label": "5th Grade Band", "book": None, "class_type": "entry",
        "percussion": True,
        "desc": "Blank agendas with a fully customizable percussion rotation.",
    },
    "orch_5": {
        "label": "5th Grade Orchestra", "book": None, "class_type": None,
        "percussion": False,
        "desc": "Blank agendas, no percussion rotation.",
    },
    "band_entry": {
        "label": "MS Band (Entry)", "book": 1, "class_type": "entry",
        "percussion": True,
        "desc": "Rhythms + Standard of Excellence Bk 1 with a customizable "
                "percussion rotation (beginning band).",
    },
    "band_intermediate": {
        "label": "MS Band (Intermediate)", "book": 2, "class_type": "int_adv",
        "percussion": True,
        "desc": "Standard of Excellence Bk 2 with a percussion rotation "
                "(2nd-year band).",
    },
    "band_advanced": {
        "label": "MS Band (Advanced)", "book": None, "class_type": "int_adv",
        "percussion": True,
        "desc": "Blank warm-up + sheet music with a percussion rotation "
                "(top band).",
    },
    "orch_mshs": {
        "label": "MS/HS Orchestra", "book": None, "class_type": None,
        "percussion": False,
        "desc": "Blank agendas, no percussion rotation.",
    },
    "choir_mshs": {
        "label": "MS/HS Choir", "book": None, "class_type": None,
        "percussion": False,
        "desc": "Blank agendas, no percussion rotation.",
    },
    "guitar": {
        "label": "MS/HS Guitar", "book": None, "class_type": None,
        "percussion": False,
        "desc": "Blank agendas, no rotation.",
    },
    "steel_drum": {
        "label": "HS Steel Drum", "book": None, "class_type": None,
        "percussion": False,
        "desc": "Blank agendas, no rotation.",
    },
    "piano": {
        "label": "MS/HS Piano", "book": None, "class_type": None,
        "percussion": False,
        "desc": "Blank agendas, no rotation.",
    },
    # A before-school choir that swings.  Its own kind rather than "Jazz",
    # because the band template's description promises a rhythm-section
    # rotation a choir does not have.
    "jazz_choir": {
        "label": "Jazz Choir", "book": None, "class_type": None,
        "percussion": False,
        "desc": "Blank agendas for a jazz/show choir (usually zero period).",
    },
    # Guitar and steel drum shared one template until teachers pointed out they
    # are plainly different courses.  The old key stays so a class already
    # using it keeps its kind -- _sanitize falls back to "generic" for an
    # unknown template, which would quietly demote somebody's class -- but it
    # is out of TEMPLATE_ORDER, so it is never offered again.
    "guitar_steel": {
        "label": "MS/HS Guitar / Steel Drum", "book": None, "class_type": None,
        "percussion": False,
        "desc": "Blank agendas, no rotation.",
    },
    "hs_band_winds": {
        "label": "HS Band (Winds)", "book": None, "class_type": None,
        "percussion": False,
        "desc": "Blank agendas, no percussion rotation.",
    },
    "hs_band_perc": {
        "label": "HS Band (Percussion)", "book": None, "class_type": "entry",
        "percussion": True,
        "desc": "Blank agendas with a fully customizable percussion rotation.",
    },
    "jazz": {
        "label": "Jazz", "book": None, "class_type": None, "percussion": False,
        "desc": "Simple warm-up + sheet music with the jazz rhythm-section "
                "rotation (choose the band with the top toggle).",
    },
}

# The order templates are offered in the Manage Classes / onboarding picker.
TEMPLATE_ORDER = ["generic", "band_5", "orch_5",
                  "band_entry", "band_intermediate", "band_advanced",
                  "orch_mshs", "choir_mshs", "jazz_choir",
                  "guitar", "steel_drum", "piano",
                  "hs_band_winds", "hs_band_perc", "jazz"]


def template_desc(template):
    return TEMPLATES.get(template, TEMPLATES["generic"]).get("desc", "")


# ── Default registries per program type ───────────────────────────────────────
# The band default reproduces the original four hard-coded classes EXACTLY (same
# ids, so existing saved agendas/settings keep working).  Choir/orchestra get a
# leveled trio with no percussion; teachers add/rename from there.

def _band_default():
    return [
        {"id": "entry", "label": "MS Band (Entry)", "template": "band_entry",
         "ensemble": "entry", "book": 1, "percussion": True},
        {"id": "intermediate", "label": "MS Band (Intermediate)",
         "template": "band_intermediate", "ensemble": "interm", "book": 2,
         "percussion": True},
        {"id": "advanced", "label": "MS Band (Advanced)", "template": "band_advanced",
         "ensemble": "adv", "book": None, "percussion": True},
        {"id": "jazz", "label": "Jazz", "template": "jazz", "ensemble": "jazz",
         "book": None, "percussion": False},
    ]


def _leveled_default(word):
    return [
        {"id": "entry", "label": f"Entry {word}", "template": "generic",
         "ensemble": "entry", "book": None, "percussion": False},
        {"id": "intermediate", "label": f"Intermediate {word}",
         "template": "generic", "ensemble": "interm", "book": None,
         "percussion": False},
        {"id": "advanced", "label": f"Advanced {word}", "template": "generic",
         "ensemble": "adv", "book": None, "percussion": False},
    ]


def default_registry(program_type="band"):
    if program_type == "choir":
        return _leveled_default("Choir")
    if program_type == "orchestra":
        return _leveled_default("Orchestra")
    if program_type == "elementary":
        # 5th-grade beginning band/orchestra — one generic class to start; the
        # teacher adds the sections they actually run in the onboarding wizard.
        return [{"id": "beginning", "label": "Beginning Band", "template": "generic",
                 "ensemble": "beginning", "book": None, "percussion": False}]
    return _band_default()


# ── Load / save (profile settings.json) ───────────────────────────────────────

def load_classes(base_dir, program_type="band"):
    """The teacher's class list from settings.json, or the program default if
    none has been saved yet.  Always returns a non-empty, id-unique list."""
    from ui.settings_dialog import load_settings
    classes = (load_settings(base_dir) or {}).get("classes")
    if not isinstance(classes, list) or not classes:
        return default_registry(program_type)
    return _sanitize(classes)


def save_classes(base_dir, classes):
    from ui.settings_dialog import load_settings, save_settings
    settings = load_settings(base_dir) or {}
    settings["classes"] = _sanitize(classes)
    save_settings(base_dir, settings)


def _sanitize(classes):
    out, seen = [], set()
    for k in classes:
        if not isinstance(k, dict):
            continue
        cid = str(k.get("id") or "").strip()
        label = str(k.get("label") or "").strip()
        if not cid or not label or cid in seen:
            continue
        seen.add(cid)
        tmpl = k.get("template") if k.get("template") in TEMPLATES else "generic"
        out.append({
            "id": cid, "label": label, "template": tmpl,
            "ensemble": str(k.get("ensemble") or cid).strip().lower(),
            "book": k.get("book") if k.get("book") in (1, 2) else None,
            "percussion": bool(k.get("percussion", TEMPLATES[tmpl]["percussion"])),
            "periods": _clean_periods(k.get("periods")),
            "site_id": (int(k["site_id"])
                        if str(k.get("site_id") or "").strip().isdigit()
                        else None),
        })
    return out


def _clean_periods(raw):
    """The class periods a class meets, as a list of short strings.

    One entry per SECTION of the class: ["1", "2"] is two sections, P1 and
    P2.  Empty means one section with no period label, which is most classes.
    Accepts a list or a comma-separated string (what the Manage Classes entry
    holds), keeps order, drops blanks and repeats, and caps at six because a
    class meeting seven times a day is a typo.
    """
    if isinstance(raw, str):
        raw = raw.replace(";", ",").split(",")
    if not isinstance(raw, (list, tuple)):
        return []
    out, seen = [], set()
    for x in raw:
        v = str(x).strip().lstrip("pP").strip()
        if v and v.lower() not in seen:
            seen.add(v.lower())
            out.append(v)
    return out[:6]


def site_of_class(label, classes):
    """The school a class label is bound to, or None.

    Matched by class IDENTITY, the same rule every filter uses, so a roster's
    "Entry Band" finds the registry's "MS Band (Entry)".  Two classes sharing
    an identity but bound to different schools is ambiguous -- the label alone
    cannot say which room is meant -- so it resolves to None (unscoped) rather
    than guessing a school and silently halving a roster.
    """
    want = class_identity(label)
    if not want:
        return None
    hits = {k.get("site_id") for k in classes
            if class_identity(k.get("label") or "") == want}
    hits.discard(None)
    return hits.pop() if len(hits) == 1 else None


def new_class_id(existing, label):
    """A stable, unique id derived from the label (slug), falling back to a
    counter.  Used when adding a class in Manage Classes."""
    import re
    base = re.sub(r"[^a-z0-9]+", "_", (label or "class").strip().lower()).strip("_")
    base = base or "class"
    have = {k.get("id") for k in existing}
    if base not in have:
        return base
    n = 2
    while f"{base}_{n}" in have:
        n += 1
    return f"{base}_{n}"


# ── Class-name identity ───────────────────────────────────────────────────────
# THE fix for the app's most persistent bug family: the same class spelled
# differently in different places.  A Synergy import says "Entry Band", the
# default registry says "MS Band (Entry)", a filter shows "Entry" — and any
# code that compares those strings for equality silently matches nothing.
#
# These functions reduce a class name to what it MEANS — its level (entry /
# intermediate / advanced / jazz N), its program word (band / choir / …) — and
# every membership test in the app compares identities, never raw strings.
# Names that don't parse to a known level ("Heavy Metal Ensemble") fall back to
# whole-string identity, so unrelated groups can never falsely merge.
#
# This module is UI-free on purpose: database.py, concert_tools.py and
# roster_export.py all import it.

import re as _re

# Words that say WHICH LEVEL a class is.  Keys are what people type.
_LEVEL_ALIASES = {
    "entry": "entry", "beginning": "entry", "beginner": "entry",
    "intermediate": "intermediate", "interm": "intermediate",
    "int": "intermediate",
    "advanced": "advanced", "adv": "advanced",
}
# Words that say WHICH PROGRAM.  Kept in the identity so an itinerant teacher's
# "Entry Band" and "Entry Choir" stay distinct.
_PROGRAM_WORDS = {"band", "orchestra", "choir", "chorus", "strings", "guitar"}
# Words that carry no identity at all and are ignored.
_NOISE_WORDS = {"ms", "hs", "middle", "high", "school", "the", "ensemble"}


def _name_words(name):
    return [w for w in _re.split(r"[^a-z0-9]+", (name or "").lower()) if w]


def parse_class_name(name):
    """``(kind, program, residue)`` for a class name.

    ``kind`` is the level identity ("entry", "advanced", "jazz 1", …) or None
    when the name doesn't reduce cleanly; ``program`` is the program word or
    None; ``residue`` is the normalized full string, used as the identity when
    ``kind`` is None.  Any unexpected extra word disables reduction — better to
    treat "Advanced Band Percussion" as its own thing than to quietly merge it
    into Advanced Band."""
    words = _name_words(name)
    level = program = None
    jazz = False
    nums, residue = [], []
    for w in words:
        if w in _NOISE_WORDS:
            continue
        if w.isdigit():
            nums.append(w)
        elif w == "jazz":
            jazz = True
        elif w in _LEVEL_ALIASES and level is None:
            level = _LEVEL_ALIASES[w]
        elif w in _PROGRAM_WORDS and program is None:
            program = w
        else:
            residue.append(w)
    if residue or (not jazz and not level):
        # No clean reduction: identity is the name itself.  Only purely
        # cosmetic words drop out here ("The", "Ensemble") — "MS"/"HS" stay
        # significant, because a 6-12 teacher's "MS Percussion" and
        # "HS Percussion" are different classes.
        raw = [w for w in words if w not in ("the", "ensemble")]
        return (None, None, " ".join(raw))
    kind = ("jazz" if jazz else level) + (f" {nums[0]}" if nums else "")
    return (kind, program, "")


def same_class(a, b) -> bool:
    """Do these two names refer to the same class?

    "Entry Band" == "MS Band (Entry)" == "Entry"; a missing program word is a
    wildcard (so the short display label still matches), but two DIFFERENT
    program words never match.  Unparseable names match only themselves."""
    if not a or not b:
        return False
    ka, pa, ra = parse_class_name(a)
    kb, pb, rb = parse_class_name(b)
    if ka and kb:
        return ka == kb and (not pa or not pb or pa == pb)
    if ka or kb:
        return False
    return ra == rb


def class_identity(name) -> str:
    """A stable key for de-duplicating lists of class names.  Two names that
    ``same_class`` (with their program words present) get the same key."""
    kind, program, residue = parse_class_name(name)
    if kind:
        return f"{kind}|{program or ''}"
    return f"raw|{residue}"


def csv_has_class(csv_val, target) -> bool:
    """Is ``target`` one of the classes in a comma-separated field (a student's
    ``ensembles``), compared by identity rather than spelling?"""
    return any(same_class(part.strip(), target)
               for part in (csv_val or "").split(",") if part.strip())


def canonical_class_name(name, offered):
    """The name from ``offered`` (the configured class list) that means the
    same as ``name`` — or ``name`` unchanged if none does.  Write paths use
    this so stored data converges on the configured spelling."""
    for o in offered or []:
        if same_class(o, name):
            return o
    return name


def short_class_label(name) -> str:
    """The compact display form: "MS Band (Entry)" → "Entry"; "Jazz Band 2" →
    "Jazz 2"; anything that doesn't reduce keeps its own name."""
    kind, _program, _residue = parse_class_name(name)
    if not kind:
        return (name or "").strip()
    parts = kind.split()
    label = "Jazz" if parts[0] == "jazz" else parts[0].capitalize()
    return label + (f" {parts[1]}" if len(parts) > 1 else "")


def display_map(names):
    """{full name: display label} for a picker.  Uses the short label unless
    two offered classes would collapse to the same one (an itinerant teacher's
    "Entry Band" + "Entry Choir") — those keep their full names so the picker
    stays unambiguous."""
    by_short = {}
    for n in names:
        by_short.setdefault(short_class_label(n), []).append(n)
    out = {}
    for short, ns in by_short.items():
        if len(ns) == 1:
            out[ns[0]] = short
        else:
            for n in ns:
                out[n] = n
    return out


def display_csv(csv_val) -> str:
    """A student's ensembles CSV shortened for display: "Entry Band,Jazz 2" →
    "Entry, Jazz 2"."""
    parts = [p.strip() for p in (csv_val or "").split(",") if p.strip()]
    return ", ".join(short_class_label(p) for p in parts)


# ── Flattened config for the agenda view ──────────────────────────────────────

def class_config(klass):
    """Merge a class dict with its template into the flat config the AgendasView
    uses (label, ensemble, book, class_type token, percussion, is_jazz)."""
    t = klass.get("template") if klass.get("template") in TEMPLATES else "generic"
    ti = TEMPLATES[t]
    book = klass.get("book")
    if book not in (1, 2):
        book = ti.get("book")
    return {
        "id": klass.get("id"),
        "label": klass.get("label") or ti["label"],
        "template": t,
        "ensemble": (klass.get("ensemble") or klass.get("id") or "").lower(),
        "book": book,
        "class_type": ti.get("class_type"),        # "entry" | "int_adv" | None
        "percussion": bool(klass.get("percussion", ti.get("percussion", False))),
        "is_jazz": t == "jazz",
        "periods": _clean_periods(klass.get("periods")),
        "site_id": klass.get("site_id"),
    }
