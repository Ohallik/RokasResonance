"""
reset_and_import_xlsx.py
One-time script: clears instruments/checkouts/repairs and re-imports
from Inventory.xlsx (CutTime export) as the source of truth.

Run from the RokasResonance folder:
    python reset_and_import_xlsx.py
"""

import os
import sys
import sqlite3
import openpyxl
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH  = os.path.join(BASE_DIR, "rokas_resonance.db")
XLSX_PATH = os.path.join(BASE_DIR, "..", "Inventory.xlsx")

SHEET_NAME = "CutTime Instrument Inventory"

# Map instrument type prefixes to category names
CATEGORY_MAP = {
    "Flute":              "Woodwind",
    "Piccolo":            "Woodwind",
    "Oboe":               "Woodwind",
    "Bassoon":            "Woodwind",
    "Clarinet":           "Woodwind",
    "Saxophone":          "Woodwind",
    "Trumpet":            "Brass",
    "Trombone":           "Brass",
    "Baritone":           "Brass",
    "French Horn":        "Brass",
    "Tuba":               "Brass",
    "Snare Drum":         "Percussion",
    "Bass Drum":          "Percussion",
    "Timpani":            "Percussion",
    "Cymbals":            "Percussion",
    "Tom-Tom":            "Percussion",
    "Xylophone":          "Percussion",
    "Marimba":            "Percussion",
    "Glockenspiel":       "Percussion",
    "Vibraphone":         "Percussion",
    "Chimes":             "Percussion",
    "Auxiliary Percussion": "Percussion",
    "Miscellaneous Drum": "Percussion",
    "Guitar":             "Guitar/Bass",
    "Bass Guitar":        "Guitar/Bass",
    "Piano":              "Keyboard",
    "Miscellaneous Electronic": "Electronics",
}


def get_category(instrument_type: str) -> str:
    if not instrument_type:
        return "Other"
    for prefix, category in CATEGORY_MAP.items():
        if instrument_type.startswith(prefix):
            return category
    return "Other"


def normalize_date(val) -> str:
    if not val:
        return ""
    if isinstance(val, datetime):
        return val.strftime("%Y-%m-%d")
    s = str(val).strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return s


def parse_money(val) -> float:
    if not val:
        return 0.0
    s = str(val).replace("$", "").replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return 0.0


def main():
    if not os.path.exists(XLSX_PATH):
        print(f"ERROR: Could not find {XLSX_PATH}")
        sys.exit(1)

    print(f"Database : {DB_PATH}")
    print(f"Excel    : {XLSX_PATH}")
    print()

    # ── 1. Clear existing instrument / checkout / repair data ────────────────
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = OFF")

    print("Clearing existing instruments, checkouts, and repairs...")
    conn.execute("DELETE FROM repairs")
    conn.execute("DELETE FROM checkouts")
    conn.execute("DELETE FROM instruments")
    conn.execute("DELETE FROM sqlite_sequence WHERE name IN ('instruments','checkouts','repairs')")
    conn.commit()
    print("  Done.\n")

    # ── 2. Load Excel ─────────────────────────────────────────────────────────
    print(f"Loading {XLSX_PATH}...")
    wb = openpyxl.load_workbook(XLSX_PATH, data_only=True)
    ws = wb[SHEET_NAME]
    rows = list(ws.iter_rows(min_row=2, values_only=True))
    print(f"  {len(rows)} rows found.\n")

    # ── 3. Import instruments ─────────────────────────────────────────────────
    # Column indices (0-based):
    # 0=Type, 1=Make, 2=Model, 3=Serial#, 4=Barcode, 5=Condition,
    # 6=Condition comment, 7=Latest inspection date, 8=Repair cost total,
    # 9=Assigned first name, 10=Assigned last name, 11=All current assignees,
    # 12=Year purchased, 13=Purchase price, 14=Assignment History, 15=Notes

    instruments_added = 0
    checkouts_added   = 0

    today = datetime.today().strftime("%Y-%m-%d")

    for r in rows:
        instr_type   = str(r[0]).strip() if r[0] else ""
        brand        = str(r[1]).strip() if r[1] else ""
        model        = str(r[2]).strip() if r[2] else ""
        serial_no    = str(r[3]).strip() if r[3] else ""
        barcode      = str(r[4]).strip() if r[4] else ""
        condition    = str(r[5]).strip() if r[5] else ""
        cond_comment = str(r[6]).strip() if r[6] else ""
        last_service = normalize_date(r[7])
        year_purch   = str(r[12]).strip() if r[12] else ""
        amount_paid  = parse_money(r[13])
        notes        = str(r[15]).strip() if r[15] else ""
        first_name   = str(r[9]).strip() if r[9] else ""
        last_name    = str(r[10]).strip() if r[10] else ""

        if not instr_type:
            continue

        category    = get_category(instr_type)
        description = instr_type

        # Build comments: combine condition comment and notes
        comments_parts = [p for p in [cond_comment, notes] if p]
        comments = " | ".join(comments_parts) if comments_parts else ""

        cur = conn.execute(
            """INSERT INTO instruments
               (category, description, brand, model, barcode, quantity,
                condition, serial_no, last_service, year_purchased,
                amount_paid, comments, is_active)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,1)""",
            (category, description, brand, model, barcode, 1,
             condition, serial_no, last_service, year_purch,
             amount_paid, comments)
        )
        instrument_id = cur.lastrowid
        instruments_added += 1

        # Create checkout if instrument is assigned
        if first_name or last_name:
            student_name = f"{first_name} {last_name}".strip()
            conn.execute(
                """INSERT INTO checkouts
                   (instrument_id, student_name, date_assigned, notes)
                   VALUES (?,?,?,?)""",
                (instrument_id, student_name, today, "")
            )
            checkouts_added += 1

    conn.commit()
    conn.close()

    print(f"Import complete!")
    print(f"  Instruments added : {instruments_added}")
    print(f"  Active checkouts  : {checkouts_added}")
    print(f"  Available         : {instruments_added - checkouts_added}")
    print()
    print("You can now restart Roka's Resonance.")


if __name__ == "__main__":
    main()
