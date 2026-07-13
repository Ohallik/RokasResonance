"""
charms_import.py - Parse legacy Charms exports (inventory + repair log).

CutTime has no repair export and doesn't carry vendor / purchase-order detail, so
a teacher who used Charms before CutTime keeps that history here.  This parses the
two Charms CSVs that matter:

  * the inventory file (MMangum_inventory.csv / inventory_report.csv) — for its
    PURCHASE data (vendor, date/year purchased, amount paid, PO number) and, for a
    Charms-only user, the instruments themselves;
  * the repair log (invrepairlog.csv) — the REPAIR HISTORY.

Both files start with a couple of title / "Prepared" rows before the real
``Category,…`` header, so the header row is found by scanning.  Rows carry match
keys (serial / barcode / district) so the import step can attach purchase data and
repairs to the right instrument — CutTime stays authoritative for current state,
Charms only fills blanks and adds history.  Pure parsing, no DB writes.
"""

import csv
import re

from cuttime_import import instrument_family


def _load_rows(path):
    with open(path, encoding="utf-8-sig", errors="replace", newline="") as fh:
        return list(csv.reader(fh))


def _header_row(rows):
    """Index of the real header row (first cell == 'Category'), or None."""
    for i, r in enumerate(rows):
        if r and str(r[0]).strip().lower() == "category":
            return i
    return None


def _money(val):
    if val in (None, ""):
        return None
    s = re.sub(r"[^\d.\-]", "", str(val))
    try:
        f = float(s)
    except ValueError:
        return None
    return f if f != 0 else None       # Charms writes 0 for "unknown"


def _s(val):
    v = "" if val is None else str(val).strip()
    return v or None


def _by_name(headers):
    """Map header name (lowercased) → first column index."""
    out = {}
    for i, h in enumerate(headers):
        key = (h or "").strip().lower()
        if key and key not in out:
            out[key] = i
    return out


def parse_charms_inventory(path):
    """Instrument dicts from a Charms inventory CSV — full record (add_instrument
    keys) plus purchase fields and, if present, a current ``_checkout``.  Also
    good for a Charms-only user (no CutTime)."""
    rows = _load_rows(path)
    hi = _header_row(rows)
    if hi is None:
        return []
    col = _by_name(rows[hi])

    def g(row, *names):
        for n in names:
            i = col.get(n.lower())
            if i is not None and i < len(row):
                v = _s(row[i])
                if v is not None:
                    return v
        return None

    out = []
    for row in rows[hi + 1:]:
        if not row or not any((c or "").strip() for c in row):
            continue
        desc = g(row, "Description")
        serial = g(row, "Serial #", "Serial No.", "Serial")
        barcode = g(row, "Barcode")
        if not (desc or serial or barcode):
            continue
        vendor = g(row, "Vendor")
        comments = g(row, "Comments") or ""
        if vendor:
            note = f"Purchased from {vendor}"
            comments = f"{comments}  ({note})".strip() if comments else note
        rec = {
            "category": instrument_family(desc),
            "description": desc,
            "brand": g(row, "Brand"),
            "model": g(row, "Model"),
            "serial_no": serial,
            "barcode": barcode,
            "district_no": g(row, "District No.", "District/ID No.") or barcode,
            "case_no": g(row, "Case #", "Case No."),
            "condition": g(row, "Cond", "Condition"),
            "quantity": g(row, "Quantity") or 1,
            "date_purchased": g(row, "Date Purch"),
            "year_purchased": (g(row, "Year Purch")
                               if (g(row, "Year Purch") or "0") not in ("0", "0000")
                               else None),
            "amount_paid": _money(g(row, "Amt Paid", "Amt. Paid")),
            "est_value": _money(g(row, "Cur Value", "Est. Value")),
            "po_number": g(row, "PO Num", "PO Number"),
            "last_service": g(row, "Last Service", "Last Serv"),
            "locker": g(row, "Locker"),
            "lock_no": g(row, "Lock #"),
            "combo": g(row, "Combo"),
            "accessories": g(row, "Accessories"),
            "comments": comments or None,
        }
        first, last = g(row, "Assigned To F"), g(row, "Assigned To L")
        if first or last:
            rec["_checkout"] = {"first_name": first or "", "last_name": last or "",
                                "date_assigned": g(row, "Date Assigned") or ""}
        out.append(rec)
    return out


def charms_purchase_fields(inst):
    """Just the purchase/history fields worth back-filling onto a CutTime
    instrument (CutTime is authoritative for current state)."""
    return {k: inst.get(k) for k in
            ("date_purchased", "year_purchased", "amount_paid", "est_value",
             "po_number", "last_service") if inst.get(k)}


# ── Repair log ────────────────────────────────────────────────────────────────
# Fixed layout (two "Description" columns — instrument then repair — so mapped by
# POSITION): Category, Description, Brand, Model, District/ID No., Serial No.,
# Priority, Date Added, Assigned To, Date Repaired, Description, Location,
# Est Cost, Act Cost, Invoice Number.

def parse_charms_repairs(path):
    """Repair records from a Charms invrepairlog CSV.  Each carries ``match_serial``
    / ``match_district`` so the import step can attach it to an instrument, plus
    the repair fields (matching the ``repairs`` schema)."""
    rows = _load_rows(path)
    hi = _header_row(rows)
    if hi is None:
        return []

    def cell(row, i):
        return _s(row[i]) if i < len(row) else None

    out = []
    for row in rows[hi + 1:]:
        if not row or not any((c or "").strip() for c in row):
            continue
        if len(row) < 6:
            continue
        district = cell(row, 4)
        serial = cell(row, 5)
        if not (district or serial):
            continue
        out.append({
            "match_district": district,
            "match_serial": serial,
            "instrument_desc": cell(row, 1),
            "brand": cell(row, 2),
            "priority": _int(cell(row, 6)),
            "date_added": cell(row, 7),
            "assigned_to": cell(row, 8),
            "date_repaired": cell(row, 9),
            "description": cell(row, 10),
            "location": cell(row, 11),
            "est_cost": _money(cell(row, 12)) or 0.0,
            "act_cost": _money(cell(row, 13)) or 0.0,
            "invoice_number": cell(row, 14),
        })
    return out


def _int(val):
    try:
        return int(str(val).strip())
    except (TypeError, ValueError):
        return 0
