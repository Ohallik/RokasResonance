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
    "band_entry": {
        "label": "Entry Band", "book": 1, "class_type": "entry",
        "percussion": True,
        "desc": "Rhythms + Fundamentals warm-up + Standard of Excellence Bk 1 "
                "+ Friday Practice Journal (beginning band).",
    },
    "band_intermediate": {
        "label": "Intermediate Band", "book": 2, "class_type": "int_adv",
        "percussion": True,
        "desc": "Broccoli warm-up + Standard of Excellence Bk 2 (2nd-year band).",
    },
    "band_advanced": {
        "label": "Advanced Band", "book": None, "class_type": "int_adv",
        "percussion": True,
        "desc": "Blank warm-up + Technique & Musicianship picker, teacher-set "
                "assessments (top band).",
    },
    "jazz": {
        "label": "Jazz", "book": None, "class_type": None, "percussion": False,
        "desc": "Simple warm-up + sheet music with the jazz rhythm-section "
                "rotation (choose the band with the top toggle).",
    },
    "generic": {
        "label": "Class", "book": None, "class_type": None, "percussion": False,
        "desc": "Blank warm-up + sheet music. For choir, orchestra, and any "
                "club or class you run your own way.",
    },
}

# The order templates are offered in the Manage Classes picker.
TEMPLATE_ORDER = ["generic", "band_entry", "band_intermediate", "band_advanced",
                  "jazz"]


def template_desc(template):
    return TEMPLATES.get(template, TEMPLATES["generic"]).get("desc", "")


# ── Default registries per program type ───────────────────────────────────────
# The band default reproduces the original four hard-coded classes EXACTLY (same
# ids, so existing saved agendas/settings keep working).  Choir/orchestra get a
# leveled trio with no percussion; teachers add/rename from there.

def _band_default():
    return [
        {"id": "entry", "label": "Entry Band", "template": "band_entry",
         "ensemble": "entry", "book": 1, "percussion": True},
        {"id": "intermediate", "label": "Intermediate Band",
         "template": "band_intermediate", "ensemble": "interm", "book": 2,
         "percussion": True},
        {"id": "advanced", "label": "Advanced Band", "template": "band_advanced",
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
        })
    return out


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
    }
