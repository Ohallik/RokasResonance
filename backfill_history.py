"""
backfill_history.py - One-time script to import historical checkout and repair
data from Old Charms CSV exports into the current database.

Only imports history for instruments that exist in the current inventory.
Does NOT modify active checkouts (date_returned IS NULL).
Both import methods have built-in deduplication.
"""

import csv
import os
import sys
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from database import Database

# ── Paths ────────────────────────────────────────────────────────────────────
CHARMS_DIR = os.path.dirname(BASE_DIR)
HISTORY_CSV = os.path.join(CHARMS_DIR, "Old Charms - inventory_history_report.csv")
REPAIR_CSV = os.path.join(CHARMS_DIR, "Old Charms - invrepairlog.csv")

DB_PATH = os.path.join(BASE_DIR, "profiles", "Meagan R. Mangum", "rokas_resonance.db")


def _normalize_date(raw: str) -> str:
    """Convert M/D/YYYY or M/D/YY to YYYY-MM-DD for consistent DB storage."""
    if not raw or not raw.strip():
        return ""
    raw = raw.strip()
    for fmt in ("%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    # Try month name format like "Aug-22"
    try:
        return datetime.strptime(raw, "%b-%y").strftime("%Y-%m-%d")
    except ValueError:
        pass
    return raw  # Return as-is if unparseable


def _build_barcode_map(db: Database) -> dict[str, int]:
    """Build barcode -> instrument_id mapping for all instruments in DB."""
    mapping = {}
    with db._connect() as conn:
        rows = conn.execute("SELECT id, barcode FROM instruments WHERE barcode IS NOT NULL AND barcode != ''").fetchall()
        for r in rows:
            mapping[r["barcode"].strip()] = r["id"]
    return mapping


def import_checkouts(db: Database, barcode_map: dict[str, int]):
    """Import historical checkouts from the Charms history CSV.

    CSV layout (line 1 = title, line 2 = header):
      Category, Description, Brand, Model, Dist No, Serial,
      Assigned To, Date Assigned, Date Returned
    """
    if not os.path.exists(HISTORY_CSV):
        print(f"  Checkout history CSV not found: {HISTORY_CSV}")
        return

    imported = 0
    skipped_no_instrument = 0
    skipped_current = 0

    with open(HISTORY_CSV, "r", encoding="utf-8-sig") as f:
        # Line 1 is the title "Chinook Middle School..."
        f.readline()
        # Line 2 is the header row
        reader = csv.DictReader(f)
        for row in reader:
            dist_no = (row.get("Dist No") or "").strip()
            student_name = (row.get("Assigned To") or "").strip()
            date_assigned = _normalize_date(row.get("Date Assigned", ""))
            date_returned = _normalize_date(row.get("Date Returned", ""))

            # Skip placeholder current assignments
            if "___" in student_name or not student_name:
                skipped_current += 1
                continue

            # Find instrument
            instrument_id = barcode_map.get(dist_no)
            if not instrument_id:
                skipped_no_instrument += 1
                continue

            # Only import completed checkouts (has a return date)
            if not date_returned:
                skipped_current += 1
                continue

            db.import_checkout(
                instrument_id=instrument_id,
                student_id=None,
                student_name=student_name,
                date_assigned=date_assigned,
                date_returned=date_returned,
            )
            imported += 1

    print(f"  Checkouts: {imported} imported, "
          f"{skipped_no_instrument} skipped (not in inventory), "
          f"{skipped_current} skipped (current/placeholder)")


def import_repairs(db: Database, barcode_map: dict[str, int]):
    """Import repair history from the Charms repair log CSV.

    CSV layout (line 1 = title, line 2 = "Prepared...", line 3 = header):
      0: Category, 1: Description (instrument), 2: Brand, 3: Model,
      4: District/ID No., 5: Serial No., 6: Priority, 7: Date Added,
      8: Assigned To, 9: Date Repaired, 10: Description (repair),
      11: Location, 12: Est Cost, 13: Act Cost, 14: Invoice Number

    Uses positional indexing because there are two "Description" columns.
    """
    if not os.path.exists(REPAIR_CSV):
        print(f"  Repair log CSV not found: {REPAIR_CSV}")
        return

    imported = 0
    skipped_no_instrument = 0

    with open(REPAIR_CSV, "r", encoding="utf-8-sig") as f:
        # Line 1: "Chinook Middle School Band Inventory Repair Log"
        f.readline()
        # Line 2: "Prepared 8/23/2024  10:44 AM"
        f.readline()
        # Line 3: Header row (skip it, we use positional indexing)
        f.readline()

        reader = csv.reader(f)
        for cols in reader:
            if len(cols) < 13:
                continue

            dist_no = cols[4].strip()
            instrument_id = barcode_map.get(dist_no)
            if not instrument_id:
                skipped_no_instrument += 1
                continue

            # Parse assigned_to — Charms uses "Last  First" format
            assigned_raw = cols[8].strip()
            if assigned_raw:
                parts = assigned_raw.split()
                # Flip "Kim  Sean" to "Sean Kim"
                if len(parts) >= 2:
                    assigned_to = f"{parts[-1]} {parts[0]}"
                else:
                    assigned_to = assigned_raw
            else:
                assigned_to = ""

            def _safe_float(val):
                try:
                    return float(val.strip().replace(",", ""))
                except (ValueError, AttributeError):
                    return 0.0

            data = {
                "instrument_id": instrument_id,
                "priority": int(cols[6]) if cols[6].strip().isdigit() else 0,
                "date_added": _normalize_date(cols[7]),
                "assigned_to": assigned_to,
                "date_repaired": _normalize_date(cols[9]),
                "description": cols[10].strip(),   # Repair description (col 10)
                "location": cols[11].strip() if len(cols) > 11 else "",
                "est_cost": _safe_float(cols[12]) if len(cols) > 12 else 0,
                "act_cost": _safe_float(cols[13]) if len(cols) > 13 else 0,
                "invoice_number": cols[14].strip() if len(cols) > 14 else "",
            }

            db.import_repair(data)
            imported += 1

    print(f"  Repairs: {imported} imported, "
          f"{skipped_no_instrument} skipped (not in inventory)")


def main():
    print("Backfilling history data from Old Charms CSV exports...")
    print(f"  Database: {DB_PATH}")

    db = Database(DB_PATH)
    barcode_map = _build_barcode_map(db)
    print(f"  {len(barcode_map)} instruments with barcodes in DB")

    # Count existing data
    with db._connect() as conn:
        existing_checkouts = conn.execute("SELECT COUNT(*) FROM checkouts").fetchone()[0]
        existing_repairs = conn.execute("SELECT COUNT(*) FROM repairs").fetchone()[0]
    print(f"  Existing: {existing_checkouts} checkouts, {existing_repairs} repairs")
    print()

    print("Importing checkout history...")
    import_checkouts(db, barcode_map)
    print()

    print("Importing repair history...")
    import_repairs(db, barcode_map)
    print()

    # Final counts
    with db._connect() as conn:
        total_checkouts = conn.execute("SELECT COUNT(*) FROM checkouts").fetchone()[0]
        active_checkouts = conn.execute("SELECT COUNT(*) FROM checkouts WHERE date_returned IS NULL").fetchone()[0]
        total_repairs = conn.execute("SELECT COUNT(*) FROM repairs").fetchone()[0]
    print(f"Final totals:")
    print(f"  Checkouts: {total_checkouts} total ({active_checkouts} active)")
    print(f"  Repairs: {total_repairs}")
    print()
    print("Done!")


if __name__ == "__main__":
    main()
