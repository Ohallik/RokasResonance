"""
uniform_import.py — Import a CutTime (or similar) attire/uniform export into the
uniforms + uniform_checkouts tables.

The reference format is CutTime's "Attire Inventory" export, whose columns are:

    Garment type, Item number, Size, Style, Gender, Color, Manufacturer,
    Barcode, Location, Condition, Date last cleaned, Date purchased,
    Purchase price, Assigned member first name, Assigned member last name,
    Assigned member student ID, Assigned member grade, ID

Header matching is fuzzy (case/space/punctuation-insensitive) so slightly
different exports still line up.  Rows that carry an assigned member are linked
to a matching student and recorded as an OPEN checkout (no rental fee — garments
never carry one).  Re-running is safe: pieces that already have an open
assignment are left alone.
"""

import re


# canonical field -> list of header aliases (all normalized before compare)
_ALIASES = {
    "garment_type":  ["garment type", "garmenttype", "type", "item type", "category"],
    "item_number":   ["item number", "itemnumber", "item #", "number", "uniform number", "item no"],
    "size":          ["size"],
    "style":         ["style"],
    "gender":        ["gender"],
    "color":         ["color", "color"],
    "manufacturer":  ["manufacturer", "maker", "brand"],
    "barcode":       ["barcode", "bar code"],
    "location":      ["location"],
    "condition":     ["condition"],
    "date_last_cleaned": ["date last cleaned", "last cleaned", "date cleaned"],
    "date_purchased":    ["date purchased", "purchase date"],
    "purchase_price":    ["purchase price", "price", "cost"],
    "assigned_first": ["assigned member first name", "member first name", "first name"],
    "assigned_last":  ["assigned member last name", "member last name", "last name"],
    "assigned_sid":   ["assigned member student id", "member student id", "student id"],
    "assigned_grade": ["assigned member grade", "member grade", "grade"],
}


def _norm(s) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(s or "").lower()).strip()


def _parse_price(v):
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    m = re.search(r"-?\d+(?:\.\d+)?", str(v).replace(",", ""))
    return float(m.group()) if m else None


def _build_colmap(header_row):
    """Return {canonical_field: column_index} for the fields we recognize."""
    norm_headers = {i: _norm(h) for i, h in enumerate(header_row)}
    colmap = {}
    for field, aliases in _ALIASES.items():
        alias_norms = {_norm(a) for a in aliases}
        for i, nh in norm_headers.items():
            if nh in alias_norms:
                colmap[field] = i
                break
    return colmap


def preview_attire_xlsx(path):
    """Read the file and return (colmap, header, data_rows) without touching the
    DB — used to show the user a summary before committing the import."""
    import openpyxl
    # NOTE: NOT read_only.  CutTime's export stores a broken sheet dimension, and
    # a read-only sheet trusts it and yields only the first cell.  The normal
    # loader rescans the real used range.  A uniform inventory is at most a few
    # thousand rows, so loading it fully is fine.
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    wb.close()
    if not rows:
        return {}, [], []
    header = list(rows[0])
    colmap = _build_colmap(header)
    data = [r for r in rows[1:] if any(c not in (None, "") for c in r)]
    return colmap, header, data


def import_attire_xlsx(db, path, school_year=None, link_assignments=True):
    """Import the attire export at *path* into *db*.

    Returns a summary dict:
        {items, garment_types, assigned_linked, assigned_unmatched, skipped}
    """
    colmap, header, data = preview_attire_xlsx(path)
    if "garment_type" not in colmap and "item_number" not in colmap:
        raise ValueError(
            "This doesn't look like an attire export — no 'Garment type' or "
            "'Item number' column was found.")

    def cell(row, field):
        i = colmap.get(field)
        if i is None or i >= len(row):
            return None
        v = row[i]
        return v.strip() if isinstance(v, str) else v

    seen_types = set()
    items = assigned_linked = assigned_unmatched = skipped = 0

    from datetime import datetime as _dt
    today = _dt.today().strftime("%Y-%m-%d")

    for row in data:
        gtype = cell(row, "garment_type")
        item_no = cell(row, "item_number")
        if not gtype and not item_no:
            skipped += 1
            continue
        if gtype and gtype not in seen_types:
            db.add_garment_type(gtype)
            seen_types.add(gtype)

        uniform_id = db.add_uniform({
            "garment_type":  gtype,
            "item_number":   None if item_no is None else str(item_no),
            "size":          cell(row, "size"),
            "style":         cell(row, "style"),
            "gender":        cell(row, "gender"),
            "color":         cell(row, "color"),
            "manufacturer":  cell(row, "manufacturer"),
            "barcode":       None if cell(row, "barcode") is None else str(cell(row, "barcode")),
            "location":      cell(row, "location"),
            "condition":     cell(row, "condition"),
            "date_last_cleaned": _as_date(cell(row, "date_last_cleaned")),
            "date_purchased":    _as_date(cell(row, "date_purchased")),
            "purchase_price":    _parse_price(cell(row, "purchase_price")),
            "comments":      None,
        })
        items += 1

        if not link_assignments:
            continue
        first = cell(row, "assigned_first")
        last = cell(row, "assigned_last")
        sid = cell(row, "assigned_sid")
        if not (first or last):
            continue
        # Resolve a student: prefer student_id, then name.
        student = None
        if sid:
            student = db.find_student_by_student_id(str(sid))
        if student is None and first and last:
            student = db.find_student_by_name(str(first), str(last), school_year) \
                or db.find_student_by_name(str(first), str(last))
        display = f"{last}, {first}".strip(", ") if (first or last) else ""
        student_id = student["id"] if student else None
        db.import_open_uniform_checkout(uniform_id, student_id, display, today)
        if student_id:
            assigned_linked += 1
        else:
            assigned_unmatched += 1

    return {
        "items": items,
        "garment_types": len(seen_types),
        "assigned_linked": assigned_linked,
        "assigned_unmatched": assigned_unmatched,
        "skipped": skipped,
    }


def _as_date(v):
    """Normalize an Excel date-ish value to a YYYY-MM-DD string, or pass text
    through unchanged."""
    if v is None or v == "":
        return None
    try:
        # openpyxl hands back datetime objects for real date cells
        return v.strftime("%Y-%m-%d")
    except AttributeError:
        return str(v)
