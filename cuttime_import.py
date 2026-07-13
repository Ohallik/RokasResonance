"""
cuttime_import.py - Parse a CutTime instrument inventory export (.xlsx).

CutTime is where most BSD programs currently keep inventory, so this is the
common "new user" upload.  The export is an Excel sheet with one row per
instrument; the exporter lets the user pick which fields to include, so columns
may be missing or reordered — everything here is matched BY HEADER NAME with
blank fallbacks, never by position.

Each row maps to the app's ``instruments`` schema; a "Checked out" row also
carries the current assignment (student first/last/id + check-out date) as a
``_checkout`` sub-dict so the importer can recreate the loan.  Pure parsing.
"""

import os


# CutTime "Type" → the app's family-level category.  Keyword match, longest
# instrument names first so "Bass Clarinet" beats "Bass".
_FAMILY = [
    ("Percussion", ["drum", "timpani", "cymbal", "mallet", "bell", "xylophone",
                    "marimba", "vibraphone", "glockenspiel", "percussion",
                    "chime", "tambourine", "triangle", "conga", "bongo"]),
    ("Woodwind", ["piccolo", "flute", "oboe", "clarinet", "bassoon", "saxophone",
                  "sax", "recorder"]),
    ("Brass", ["trumpet", "cornet", "flugel", "horn", "trombone", "baritone",
               "euphonium", "tuba", "sousaphone", "mellophone"]),
    ("Strings", ["violin", "viola", "cello", "guitar", "harp"]),
    ("Keyboard", ["piano", "keyboard", "synth"]),
    ("Electronics", ["amp", "mixer", "microphone", "speaker", "recorder",
                     "tuner", "metronome"]),
]


def instrument_family(type_name):
    t = (type_name or "").strip().lower()
    if not t:
        return "Other"
    if "string bass" in t or "double bass" in t or "upright bass" in t:
        return "Strings"
    for family, keys in _FAMILY:
        if any(k in t for k in keys):
            return family
    return "Other"


def _money(val):
    if val is None:
        return None
    s = str(val).replace("$", "").replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def _index_of(headers, *names):
    """First column whose header equals or starts with one of ``names``
    (case-insensitive) — CutTime truncates some headers, so allow a prefix."""
    low = [(h or "").strip().lower() for h in headers]
    for n in names:
        n = n.strip().lower()
        for i, h in enumerate(low):
            if h == n:
                return i
        for i, h in enumerate(low):
            if h.startswith(n) or n.startswith(h) and h:
                return i
    return None


def parse_cuttime_inventory(path):
    """Return a list of instrument dicts (keys matching ``add_instrument``) from
    a CutTime .xlsx export.  Rows that are checked out include a ``_checkout``
    dict with the current assignee."""
    import openpyxl
    import warnings
    warnings.filterwarnings("ignore")
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb.active
    rows = [[c.value for c in row] for row in ws.iter_rows()]
    wb.close()
    if not rows:
        return []
    headers = rows[0]
    col = {
        "type": _index_of(headers, "Type"),
        "make": _index_of(headers, "Make", "Brand"),
        "model": _index_of(headers, "Model"),
        "serial": _index_of(headers, "Serial #", "Serial"),
        "case": _index_of(headers, "Case ID", "Case"),
        "barcode": _index_of(headers, "Barcode"),
        "district": _index_of(headers, "Owner ID", "District", "Asset"),
        "location": _index_of(headers, "Location"),
        "condition": _index_of(headers, "Condition"),
        "cond_comment": _index_of(headers, "Condition comment"),
        "value": _index_of(headers, "Current value"),
        "price": _index_of(headers, "Purchase price"),
        "year": _index_of(headers, "Year purchased"),
        "status": _index_of(headers, "Status"),
        "a_first": _index_of(headers, "Assigned member first"),
        "a_last": _index_of(headers, "Assigned member last"),
        "a_sid": _index_of(headers, "Assigned member student"),
        "a_grade": _index_of(headers, "Assigned member grade"),
        "co_date": _index_of(headers, "Latest check-out date"),
    }

    def cell(row, key):
        i = col.get(key)
        if i is None or i >= len(row) or row[i] is None:
            return ""
        return str(row[i]).strip()

    out = []
    for row in rows[1:]:
        if not any(c not in (None, "") for c in row):
            continue
        itype = cell(row, "type")
        if not (itype or cell(row, "serial") or cell(row, "barcode")):
            continue
        cond = cell(row, "condition")
        comment = cell(row, "cond_comment")
        # CutTime's boilerplate "Imported inspection" comment isn't useful.
        if comment.lower() == "imported inspection":
            comment = ""
        rec = {
            "category": instrument_family(itype),
            "description": itype,
            "brand": cell(row, "make") or None,
            "model": (cell(row, "model") if cell(row, "model").lower() != "unknown"
                      else None),
            "serial_no": cell(row, "serial") or None,
            "barcode": cell(row, "barcode") or None,
            "district_no": cell(row, "district") or None,
            "case_no": cell(row, "case") or None,
            "locker": cell(row, "location") or None,
            "condition": cond or None,
            "comments": comment or None,
            "est_value": _money(cell(row, "value")),
            "amount_paid": _money(cell(row, "price")),
            "year_purchased": cell(row, "year") or None,
            "quantity": 1,
        }
        if cell(row, "status").lower().startswith("checked out"):
            first, last = cell(row, "a_first"), cell(row, "a_last")
            if first or last or cell(row, "a_sid"):
                rec["_checkout"] = {
                    "first_name": first, "last_name": last,
                    "student_id": cell(row, "a_sid"),
                    "grade": cell(row, "a_grade"),
                    "date_assigned": cell(row, "co_date"),
                }
        out.append(rec)
    return out
