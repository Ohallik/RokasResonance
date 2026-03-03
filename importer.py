"""
importer.py - Import Charms CSV data into Roka's Resonance database
"""

import csv
import os
import re
from datetime import datetime
from database import Database


SKIP_VALUES = {"category", "chinook", "prepared", "description", ""}

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(BASE_DIR)


def _open_csv(path: str):
    """Open a CSV with UTF-8-sig encoding and fallback."""
    return open(path, encoding="utf-8-sig", errors="replace", newline="")


def _is_header_or_junk(row: list) -> bool:
    """Return True if the row should be skipped."""
    if not row:
        return True
    first = str(row[0]).strip().lower()
    return first in SKIP_VALUES or first.startswith("prepared") or first.startswith("chinook")


def _parse_float(val: str) -> float:
    if not val:
        return 0.0
    cleaned = re.sub(r"[^\d.\-]", "", str(val))
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def _parse_int(val: str) -> int:
    try:
        return int(str(val).strip())
    except (ValueError, TypeError):
        return 0


def _school_year_from_date(date_str: str) -> str:
    """Derive school year string like '2022-2023' from a date string."""
    if not date_str:
        return ""
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y"):
        try:
            dt = datetime.strptime(date_str.strip(), fmt)
            if dt.month >= 8:
                return f"{dt.year}-{dt.year + 1}"
            else:
                return f"{dt.year - 1}-{dt.year}"
        except ValueError:
            continue
    return ""


def _normalize_date(date_str: str) -> str:
    """Normalize dates to YYYY-MM-DD, return original if unparseable."""
    if not date_str:
        return ""
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(date_str.strip(), fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return date_str.strip()


def import_inventory(db: Database, csv_path: str) -> dict:
    """
    Import instruments from Old Charms inventory_report CSV.
    Columns: Category, Description, Barcode, Brand, Model, Quantity,
             District No., Case No., Condition, Serial No., Date Purch,
             Year Purch, PO Number, Last Serv, Assigned/Location/Loan,
             Amt. Paid, Est. Value, Locker, Lock #, Combo, Comments, Accessories
    """
    if not os.path.exists(csv_path):
        return {"imported": 0, "skipped": 0, "error": f"File not found: {csv_path}"}

    imported = 0
    skipped = 0

    with _open_csv(csv_path) as f:
        reader = csv.reader(f)
        for row in reader:
            if _is_header_or_junk(row):
                continue
            if len(row) < 2:
                continue

            data = {
                "category":       str(row[0]).strip() if len(row) > 0 else "",
                "description":    str(row[1]).strip() if len(row) > 1 else "",
                "barcode":        str(row[2]).strip() if len(row) > 2 else "",
                "brand":          str(row[3]).strip() if len(row) > 3 else "",
                "model":          str(row[4]).strip() if len(row) > 4 else "",
                "quantity":       _parse_int(row[5]) if len(row) > 5 else 1,
                "district_no":    str(row[6]).strip() if len(row) > 6 else "",
                "case_no":        str(row[7]).strip() if len(row) > 7 else "",
                "condition":      str(row[8]).strip() if len(row) > 8 else "",
                "serial_no":      str(row[9]).strip() if len(row) > 9 else "",
                "date_purchased": _normalize_date(row[10]) if len(row) > 10 else "",
                "year_purchased": str(row[11]).strip() if len(row) > 11 else "",
                "po_number":      str(row[12]).strip() if len(row) > 12 else "",
                "last_service":   _normalize_date(row[13]) if len(row) > 13 else "",
                # row[14] = Assigned/Location/Loan — not stored as separate field
                "amount_paid":    _parse_float(row[15]) if len(row) > 15 else 0.0,
                "est_value":      _parse_float(row[16]) if len(row) > 16 else 0.0,
                "locker":         str(row[17]).strip() if len(row) > 17 else "",
                "lock_no":        str(row[18]).strip() if len(row) > 18 else "",
                "combo":          str(row[19]).strip() if len(row) > 19 else "",
                "comments":       str(row[20]).strip() if len(row) > 20 else "",
                "accessories":    str(row[21]).strip() if len(row) > 21 else "",
            }

            if not data["description"]:
                skipped += 1
                continue

            iid = db.import_instrument(data)
            if iid:
                imported += 1
            else:
                skipped += 1

    return {"imported": imported, "skipped": skipped}


def import_history(db: Database, csv_path: str) -> dict:
    """
    Import checkout history from Old Charms inventory_history_report CSV.
    Columns: Category, Description, Brand, Model, Dist No, Serial,
             Assigned To, Date Assigned, Date Returned
    """
    if not os.path.exists(csv_path):
        return {"imported": 0, "skipped": 0, "error": f"File not found: {csv_path}"}

    imported = 0
    skipped = 0

    with _open_csv(csv_path) as f:
        reader = csv.reader(f)
        for row in reader:
            if _is_header_or_junk(row):
                continue
            if len(row) < 7:
                continue

            district_no   = str(row[4]).strip()
            assigned_to   = str(row[6]).strip()
            date_assigned = _normalize_date(row[7]) if len(row) > 7 else ""
            date_returned = _normalize_date(row[8]) if len(row) > 8 else ""

            if not assigned_to or not date_assigned:
                skipped += 1
                continue

            # Find instrument by district number
            instrument_id = None
            with db._connect() as conn:
                if district_no:
                    row_inst = conn.execute(
                        "SELECT id FROM instruments WHERE district_no=? LIMIT 1",
                        (district_no,)
                    ).fetchone()
                    if row_inst:
                        instrument_id = row_inst["id"]

                if not instrument_id:
                    # Try serial number
                    serial = str(row[5]).strip()
                    if serial:
                        row_inst = conn.execute(
                            "SELECT id FROM instruments WHERE serial_no=? LIMIT 1",
                            (serial,)
                        ).fetchone()
                        if row_inst:
                            instrument_id = row_inst["id"]

            if not instrument_id:
                skipped += 1
                continue

            # Parse student name: "Last, First" or "First Last"
            name_parts = assigned_to.strip()
            student_id = None
            if "," in name_parts:
                parts = name_parts.split(",", 1)
                last_name  = parts[0].strip()
                first_name = parts[1].strip()
            else:
                parts = name_parts.split()
                first_name = parts[0] if parts else ""
                last_name  = " ".join(parts[1:]) if len(parts) > 1 else ""

            school_year = _school_year_from_date(date_assigned)

            # Find or create student
            student = db.find_student_by_name(first_name, last_name, school_year)
            if not student:
                student_id = db.add_student({
                    "first_name":  first_name,
                    "last_name":   last_name,
                    "school_year": school_year,
                })
            else:
                student_id = student["id"]

            cid = db.import_checkout(
                instrument_id, student_id, assigned_to,
                date_assigned, date_returned or None
            )
            if cid:
                imported += 1
            else:
                skipped += 1

    return {"imported": imported, "skipped": skipped}


def import_repairs(db: Database, csv_path: str) -> dict:
    """
    Import repairs from Old Charms invrepairlog CSV.
    Columns: Category, Description, Brand, Model, District/ID No., Serial No.,
             Priority, Date Added, Assigned To, Date Repaired, Description,
             Location, Est Cost, Act Cost, Invoice Number
    """
    if not os.path.exists(csv_path):
        return {"imported": 0, "skipped": 0, "error": f"File not found: {csv_path}"}

    imported = 0
    skipped = 0

    with _open_csv(csv_path) as f:
        reader = csv.reader(f)
        for row in reader:
            if _is_header_or_junk(row):
                continue
            if len(row) < 5:
                continue

            district_no = str(row[4]).strip()
            serial_no   = str(row[5]).strip()

            instrument_id = None
            with db._connect() as conn:
                if district_no:
                    r = conn.execute(
                        "SELECT id FROM instruments WHERE district_no=? LIMIT 1",
                        (district_no,)
                    ).fetchone()
                    if r:
                        instrument_id = r["id"]
                if not instrument_id and serial_no:
                    r = conn.execute(
                        "SELECT id FROM instruments WHERE serial_no=? LIMIT 1",
                        (serial_no,)
                    ).fetchone()
                    if r:
                        instrument_id = r["id"]

            if not instrument_id:
                skipped += 1
                continue

            data = {
                "instrument_id":  instrument_id,
                "priority":       _parse_int(row[6]) if len(row) > 6 else 0,
                "date_added":     _normalize_date(row[7]) if len(row) > 7 else "",
                "assigned_to":    str(row[8]).strip() if len(row) > 8 else "",
                "date_repaired":  _normalize_date(row[9]) if len(row) > 9 else "",
                "description":    str(row[10]).strip() if len(row) > 10 else "",
                "location":       str(row[11]).strip() if len(row) > 11 else "",
                "est_cost":       _parse_float(row[12]) if len(row) > 12 else 0.0,
                "act_cost":       _parse_float(row[13]) if len(row) > 13 else 0.0,
                "invoice_number": str(row[14]).strip() if len(row) > 14 else "",
            }

            rid = db.import_repair(data)
            if rid:
                imported += 1
            else:
                skipped += 1

    return {"imported": imported, "skipped": skipped}


def import_student_history(db: Database, csv_path: str) -> dict:
    """
    Import from Old Charms inventory_student_history_report CSV if present.
    Format varies — this will try to pull student and checkout data.
    """
    if not os.path.exists(csv_path):
        return {"imported": 0, "skipped": 0, "error": f"File not found: {csv_path}"}
    # Delegate to history importer — same format
    return import_history(db, csv_path)


def run_full_import(db: Database, base_dir: str = None, progress_callback=None) -> dict:
    """
    Run the complete import from all Charms CSVs found in base_dir.
    progress_callback(message: str) is called with status updates.
    """
    if base_dir is None:
        base_dir = PARENT_DIR

    def report(msg):
        if progress_callback:
            progress_callback(msg)

    results = {}

    # 1. Inventory (instruments must come first)
    inv_path = os.path.join(base_dir, "Old Charms - inventory_report edited.csv")
    if not os.path.exists(inv_path):
        # Try alternate name
        inv_path = os.path.join(base_dir, "Old Charms - inventory_report.csv")

    report("Importing instruments from inventory report...")
    res = import_inventory(db, inv_path)
    results["inventory"] = res
    report(f"  Instruments: {res.get('imported', 0)} imported, {res.get('skipped', 0)} skipped")

    # 2. Checkout history
    hist_path = os.path.join(base_dir, "Old Charms - inventory_history_report.csv")
    report("Importing checkout history...")
    res = import_history(db, hist_path)
    results["history"] = res
    report(f"  Checkouts: {res.get('imported', 0)} imported, {res.get('skipped', 0)} skipped")

    # 3. Student history (may be same or different format)
    stud_path = os.path.join(base_dir, "Old Charms - inventory_student_history_report.csv")
    if os.path.exists(stud_path) and stud_path != hist_path:
        report("Importing student history...")
        res = import_student_history(db, stud_path)
        results["student_history"] = res
        report(f"  Student checkouts: {res.get('imported', 0)} imported, {res.get('skipped', 0)} skipped")

    # 4. Repair log
    repair_path = os.path.join(base_dir, "Old Charms - invrepairlog.csv")
    report("Importing repair log...")
    res = import_repairs(db, repair_path)
    results["repairs"] = res
    report(f"  Repairs: {res.get('imported', 0)} imported, {res.get('skipped', 0)} skipped")

    report("Import complete!")
    return results
