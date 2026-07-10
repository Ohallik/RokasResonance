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
