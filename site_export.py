"""
site_export.py - Hand one school's instruments on to whoever teaches it next.

Elementary assignments change often. A teacher who carried six schools last
year may carry three different ones this year, and the person taking over
Sherwood Forest starts with a cupboard full of instruments and no idea which
ones are out, which are broken, or what has already been repaired twice.

Three exports, all for one school:

  * the handoff       - inventory, checkout history and repair history in one
                        workbook, so a successor gets the whole picture in a
                        single file
  * needs repair now  - what to hand the technician
  * repair history    - everything ever done at that school

No tkinter here; this is data and openpyxl only, so it can be tested and
called from anywhere.
"""

from datetime import date


# The handoff carries the instrument columns worth passing on.  Deliberately
# not every column: locker combinations and internal notes are the outgoing
# teacher's business, and a purchase price from 1994 helps nobody.
INSTRUMENT_FIELDS = [
    ("category", "Category"),
    ("description", "Instrument"),
    ("size", "Size"),
    ("brand", "Brand"),
    ("model", "Model"),
    ("serial_no", "Serial #"),
    ("barcode", "Barcode"),
    ("district_no", "District #"),
    ("condition", "Condition"),
    ("year_manufactured", "Year Made"),
    ("est_value", "Est. Value"),
    ("accessories", "Accessories"),
    ("comments", "Notes"),
]

CHECKOUT_FIELDS = [
    ("instrument_desc", "Instrument"),
    ("size", "Size"),
    ("serial_no", "Serial #"),
    ("barcode", "Barcode"),
    ("student", "Student"),
    ("grade", "Grade"),
    ("date_assigned", "Out"),
    ("date_returned", "Returned"),
    ("due_date", "Due"),
    ("notes", "Notes"),
]

REPAIR_FIELDS = [
    ("instrument_desc", "Instrument"),
    ("serial_no", "Serial #"),
    ("barcode", "Barcode"),
    ("description", "Repair"),
    ("date_added", "Reported"),
    ("date_repaired", "Repaired"),
    ("assigned_to", "Sent To"),
    ("location", "Location"),
    ("est_cost", "Est. Cost"),
    ("act_cost", "Actual Cost"),
    ("invoice_number", "Invoice #"),
    ("priority", "Priority"),
    ("notes", "Notes"),
]


def _val(row, key):
    """One cell's value, with the joined-name convenience the rows don't carry."""
    if key == "student":
        name = f"{row.get('first_name') or ''} {row.get('last_name') or ''}".strip()
        return name or (row.get("student_name") or "")
    v = row.get(key)
    return "" if v is None else v


def _sheet(wb, title, fields, rows, first=False):
    from openpyxl.styles import Font, Alignment

    ws = wb.active if first else wb.create_sheet()
    ws.title = title[:31]

    for c, (_key, head) in enumerate(fields, start=1):
        cell = ws.cell(row=1, column=c, value=head)
        cell.font = Font(bold=True)
        cell.alignment = Alignment(horizontal="left")
    for r, row in enumerate(rows, start=2):
        for c, (key, _head) in enumerate(fields, start=1):
            ws.cell(row=r, column=c, value=_val(row, key))

    # Size each column to what is actually in it.  A fixed width is right at
    # exactly one font size and wrong at the rest, and a serial number cut off
    # halfway is worse than no serial number at all.
    for c, (key, head) in enumerate(fields, start=1):
        longest = max([len(str(head))]
                      + [len(str(_val(row, key))) for row in rows] or [0])
        ws.column_dimensions[ws.cell(row=1, column=c).column_letter].width = \
            min(max(longest + 2, 9), 46)
    ws.freeze_panes = "A2"
    return ws


def _stamp(ws, site_name, subtitle):
    """A line at the top saying which school and when, because these files get
    emailed around and renamed."""
    from openpyxl.styles import Font
    ws.insert_rows(1, 2)
    ws.cell(row=1, column=1,
            value=f"{site_name} — {subtitle}").font = Font(bold=True, size=12)
    ws.cell(row=2, column=1,
            value=f"Exported {date.today():%d %B %Y}").font = Font(italic=True)
    ws.freeze_panes = "A4"


def _site_name(site):
    return (dict(site).get("name") if site else "") or "School"


def export_handoff(db, site, out_path):
    """Everything the next teacher needs for this school, in one workbook."""
    from openpyxl import Workbook

    site = dict(site)
    sid = site["id"]
    instruments = [dict(r) for r in db.get_instruments_with_status(
        include_inactive=True, site_id=sid)]
    checkouts = [dict(r) for r in db.get_checkouts_for_site(sid)]
    repairs = [dict(r) for r in db.get_all_repairs(site_id=sid)]

    wb = Workbook()
    ws = _sheet(wb, "Instruments", INSTRUMENT_FIELDS, instruments, first=True)
    _stamp(ws, site["name"], "instrument inventory")
    _sheet(wb, "Checkout History", CHECKOUT_FIELDS, checkouts)
    _sheet(wb, "Repair History", REPAIR_FIELDS, repairs)
    wb.save(out_path)
    return {"path": out_path, "instrument": len(instruments),
            "checkout": len(checkouts), "repair": len(repairs)}


def export_needs_repair(db, site, out_path):
    """What is broken right now — the list that goes to the technician."""
    from openpyxl import Workbook

    site = dict(site)
    rows = [dict(r) for r in db.get_pending_repairs(site_id=site["id"])]
    wb = Workbook()
    ws = _sheet(wb, "Needs Repair", REPAIR_FIELDS, rows, first=True)
    _stamp(ws, site["name"], "instruments awaiting repair")
    wb.save(out_path)
    return {"path": out_path, "repair": len(rows)}


def export_repair_history(db, site, out_path):
    """Everything ever done to this school's instruments."""
    from openpyxl import Workbook

    site = dict(site)
    rows = [dict(r) for r in db.get_all_repairs(site_id=site["id"])]
    # What was actually spent, not what was quoted -- an estimate that never
    # became an invoice is not money out of anybody's budget.
    total = 0.0
    for r in rows:
        try:
            total += float(r.get("act_cost") or 0)
        except (TypeError, ValueError):
            pass
    wb = Workbook()
    ws = _sheet(wb, "Repair History", REPAIR_FIELDS, rows, first=True)
    _stamp(ws, site["name"], "full repair history")
    ws.cell(row=len(rows) + 5, column=1, value="Total spent")
    ws.cell(row=len(rows) + 5, column=2, value=round(total, 2))
    wb.save(out_path)
    return {"path": out_path, "repair": len(rows), "total": round(total, 2)}


def suggested_filename(site, kind: str) -> str:
    """A filename that still means something in somebody else's downloads."""
    name = "".join(ch for ch in _site_name(site) if ch.isalnum() or ch in " -_").strip()
    name = name.replace(" ", "_") or "School"
    return f"{name}_{kind}_{date.today():%Y%m%d}.xlsx"
