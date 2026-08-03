"""
ui/names.py - Consistent student name display.

Teachers rarely want middle names/initials on screen, and often use a preferred
name.  These helpers give the display first name (preferred if set, else the
first token of the given first name — dropping middle names/initials) and
convenient full-name formats.  The stored first_name/last_name are never
changed, so exports, matching, and the district record stay intact.
"""


def _sget(row, key):
    try:
        return (row[key] if key in row.keys() else "") or ""
    except Exception:
        try:
            return row.get(key) or ""
        except Exception:
            return ""


def display_first(first_name: str, preferred_name: str = "") -> str:
    """Preferred name if provided, otherwise the first word of the given first
    name (hides middle names and initials like 'Jensen W.' → 'Jensen')."""
    pref = (preferred_name or "").strip()
    if pref:
        return pref
    first = (first_name or "").strip()
    if not first:
        return ""
    return first.split()[0]


def display_first_of(row) -> str:
    return display_first(_sget(row, "first_name"), _sget(row, "preferred_name"))


def display_full(row) -> str:
    """'First Last' using the display first name."""
    return f"{display_first_of(row)} {_sget(row, 'last_name')}".strip()


def display_last_first(row) -> str:
    """'Last, First' using the display first name (for sorted lists)."""
    last = _sget(row, "last_name")
    first = display_first_of(row)
    return f"{last}, {first}".strip(", ").strip()


# ── Adult / director names ────────────────────────────────────────────────────

def display_person(name: str) -> str:
    """A person's name with middle INITIALS dropped: "Meagan R. Mangum" →
    "Meagan Mangum".  Only single-letter tokens (with or without a period) are
    removed — "Mary Ann Smith" keeps all three words, and a name that is
    nothing but initials is left alone."""
    words = (name or "").split()
    kept = [w for w in words if len(w.rstrip(".")) > 1]
    return " ".join(kept) if kept else (name or "").strip()


def director_name(base_dir: str) -> str:
    """The teacher's name as printed on programs and signed in emails.

    An explicit "Your Name" in Settings wins (that's the "unless told
    otherwise" hook); the fallback is the profile folder name with middle
    initials stripped — profile folders are file paths, not print copy, and
    "Meagan R. Mangum" on disk should still print as "Meagan Mangum"."""
    import os
    try:
        from ui.settings_dialog import load_settings
        explicit = ((load_settings(base_dir).get("teacher") or {})
                    .get("display_name") or "").strip()
        if explicit:
            return explicit
    except Exception:
        pass
    return display_person(os.path.basename((base_dir or "").rstrip("\\/")))
