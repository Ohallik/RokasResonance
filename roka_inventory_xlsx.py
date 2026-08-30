"""
roka_inventory_xlsx.py - Roka's own blank inventory form (.xlsx), and its reader.

Not every program has an inventory to export.  Some teachers never put their
instruments into CutTime, their last records are a decade-old Charms list, and
some have no list at all and want to build one.  CutTime hands those teachers a
blank import sheet; this is Roka's version of that, with columns that match
Roka's own instrument record rather than CutTime's.

The form is generated from inside the app (so the Instrument Type dropdown is
the vocabulary the check-out forms know, the Size dropdown follows the
instrument, and the School column lists the teacher's own schools), filled in
by the teacher in Excel, and read back by ``parse_roka_inventory``.  Everything
is matched BY HEADER NAME, never by column position, so a teacher who deletes
or reorders a column has not broken anything.
"""

import os

SHEET = "Inventory"
TYPES_SHEET = "Instrument Types"
SIZES_SHEET = "Sizes"
README_SHEET = "Read Me"
MARKER = "RokaInventoryForm"          # a defined name that says "this is ours"
DATA_ROWS = 500                       # rows carrying dropdowns and validation

# Size groups: which list the Size dropdown offers for an instrument type.
SIZE_GROUPS = {
    "fraction": ["1/16", "1/10", "1/8", "1/4", "1/2", "3/4", "7/8", "4/4 (full)"],
    "viola": ['12"', '13"', '14"', '15"', '15.5"', '16"', '16.5"'],
    "bass": ["1/8", "1/4", "1/2", "3/4", "7/8", "4/4 (full)"],
    # Middle schools mostly own 3/4 tubas, high schools full size.
    "tuba": ["3/4", "4/4 (full)"],
}

# (family, instrument type, size group or "").  The type names are the ones
# the check-out form's accessory table knows (pdf_generator), so picking from
# this list is what gets the right accessories printed.
INSTRUMENT_TYPES = [
    # Woodwind
    ("Woodwind", "Piccolo", ""),
    ("Woodwind", "Flute", ""),
    ("Woodwind", "Flute - Alto", ""),
    ("Woodwind", "Flute - Bass", ""),
    ("Woodwind", "Oboe", ""),
    ("Woodwind", "English Horn", ""),
    ("Woodwind", "Bassoon", ""),
    ("Woodwind", "Contrabassoon", ""),
    ("Woodwind", "Clarinet - Eb", ""),
    ("Woodwind", "Clarinet - Bb", ""),
    ("Woodwind", "Clarinet - Eb Alto", ""),
    ("Woodwind", "Clarinet - Bb Bass", ""),
    ("Woodwind", "Clarinet - Contrabass", ""),
    ("Woodwind", "Saxophone - Soprano", ""),
    ("Woodwind", "Saxophone - Eb Alto", ""),
    ("Woodwind", "Saxophone - Bb Tenor", ""),
    ("Woodwind", "Saxophone - Eb Baritone", ""),
    ("Woodwind", "Recorder", ""),
    # Brass
    ("Brass", "Trumpet - Bb", ""),
    ("Brass", "Cornet", ""),
    ("Brass", "Flugelhorn", ""),
    ("Brass", "French Horn - Single in F", ""),
    ("Brass", "French Horn - Single in Bb", ""),
    ("Brass", "French Horn - Double", ""),
    ("Brass", "Mellophone", ""),
    ("Brass", "Trombone", ""),
    ("Brass", "Trombone - Tenor (w/ F trigger)", ""),
    ("Brass", "Trombone - Bass", ""),
    ("Brass", "Baritone - 3-valve", ""),
    ("Brass", "Baritone - 4-valve", ""),
    ("Brass", "Euphonium", ""),
    ("Brass", "Tuba", "tuba"),
    ("Brass", "Sousaphone", ""),
    # Strings
    ("Strings", "Violin", "fraction"),
    ("Strings", "Viola", "viola"),
    ("Strings", "Cello", "fraction"),
    ("Strings", "String Bass", "bass"),
    ("Strings", "Harp", ""),
    # Percussion
    ("Percussion", "Snare Drum - Concert", ""),
    ("Percussion", "Snare Drum - Drum Set", ""),
    ("Percussion", "Drum Set", ""),
    ("Percussion", "Bass Drum - Concert", ""),
    ("Percussion", "Bass Drum - Kick Drum", ""),
    ("Percussion", "Tom-Tom - Concert Tom (Single)", ""),
    ("Percussion", "Tom-Tom - Concert Toms (Set)", ""),
    ("Percussion", "Tom-Tom - Floor Tom", ""),
    ("Percussion", "Tom-Tom - Rack Tom", ""),
    ("Percussion", 'Timpani - 23"', ""),
    ("Percussion", 'Timpani - 26"', ""),
    ("Percussion", 'Timpani - 29"', ""),
    ("Percussion", 'Timpani - 32"', ""),
    ("Percussion", "Cymbals - Crash (pair)", ""),
    ("Percussion", "Cymbals - Suspended", ""),
    ("Percussion", "Cymbals - Hi-Hat", ""),
    ("Percussion", "Cymbals - Ride", ""),
    ("Percussion", "Miscellaneous Drum - Bongos", ""),
    ("Percussion", "Miscellaneous Drum - Conga (Single)", ""),
    ("Percussion", "Miscellaneous Drum - Djembe", ""),
    ("Percussion", "Miscellaneous Drum - Cajon", ""),
    ("Percussion", "Auxiliary Percussion - Other", ""),
    ("Percussion", "Stick bag + sticks/mallets", ""),
    # Mallets
    ("Mallets", "Glockenspiel/Bells - Bell Kit", ""),
    ("Mallets", "Glockenspiel/Bells - Concert", ""),
    ("Mallets", "Xylophone", ""),
    ("Mallets", "Marimba - 4.3 Octave", ""),
    ("Mallets", "Marimba - 5 Octave", ""),
    ("Mallets", "Vibraphone", ""),
    ("Mallets", "Chimes - Concert", ""),
    # Guitar / Bass
    ("Guitar/Bass", "Guitar - Acoustic", ""),
    ("Guitar/Bass", "Guitar - Electric", ""),
    ("Guitar/Bass", "Bass Guitar - Electric", ""),
    ("Guitar/Bass", "Ukulele", ""),
    # Keyboard
    ("Keyboard", "Piano", ""),
    ("Keyboard", "Keyboard - Electric", ""),
    # Electronics
    ("Electronics", "Guitar Amp", ""),
    ("Electronics", "Bass Amp", ""),
    ("Electronics", "Keyboard Amp", ""),
    ("Electronics", "Microphone", ""),
    ("Electronics", "Mixer", ""),
    ("Electronics", "Speaker / PA", ""),
    ("Electronics", "Audio Recorder", ""),
    ("Electronics", "Electric Drum Set", ""),
    ("Electronics", "Tuner", ""),
    ("Electronics", "Metronome", ""),
    ("Electronics", "Miscellaneous Electronic - Other", ""),
    # Other
    ("Other", "Music Stand", ""),
    ("Other", "Other", ""),
]

# Which family list comes first depends on who is filling the form in.  An
# orchestra teacher should not scroll past forty band instruments to find
# "Violin".
_FAMILY_ORDER = {
    "band": ["Woodwind", "Brass", "Percussion", "Mallets", "Strings",
             "Guitar/Bass", "Keyboard", "Electronics", "Other"],
    "orchestra": ["Strings", "Woodwind", "Brass", "Percussion", "Mallets",
                  "Guitar/Bass", "Keyboard", "Electronics", "Other"],
    "choir": ["Keyboard", "Electronics", "Guitar/Bass", "Percussion",
              "Mallets", "Woodwind", "Brass", "Strings", "Other"],
    "elementary": ["Woodwind", "Brass", "Strings", "Percussion", "Mallets",
                   "Guitar/Bass", "Keyboard", "Electronics", "Other"],
}

CONDITIONS = ["New", "Excellent", "Good", "Fair", "Poor", "Needs Repair",
              "Unrepairable", "Unknown"]

# Header text on the form -> instruments column.  The header is what the
# teacher sees; the parser matches on the part before any "(" or "*".
COLUMNS = [
    ("Instrument Type *", "description"),
    ("Size", "size"),
    ("Make / Brand", "brand"),
    ("Model", "model"),
    ("Serial Number", "serial_no"),
    ("Barcode", "barcode"),
    ("Condition", "condition"),
    ("Location (room / locker)", "locker"),
    ("Lock #", "lock_no"),
    ("Combination", "combo"),
    ("Year Purchased", "year_purchased"),
    ("Purchase Price", "amount_paid"),
    ("Estimated Value", "est_value"),
    ("Year Made", "year_manufactured"),
    ("PO Number", "po_number"),
    ("Accessories (only if not the usual set)", "accessories"),
    ("Notes", "comments"),
]
SCHOOL_HEADER = "School"

_MONEY_COLS = {"amount_paid", "est_value"}
_YEAR_COLS = {"year_purchased", "year_manufactured"}


def _key(header):
    """"Instrument Type *" / "Location (room / locker)" -> "instrument type"."""
    h = str(header or "").split("(")[0].replace("*", "").strip().lower()
    return " ".join(h.split())


def types_for(program_type="band"):
    """The instrument list in the order this program wants it."""
    order = _FAMILY_ORDER.get((program_type or "band").lower(),
                              _FAMILY_ORDER["band"])
    rank = {f: i for i, f in enumerate(order)}
    return sorted(INSTRUMENT_TYPES,
                  key=lambda t: (rank.get(t[0], len(rank)),
                                 INSTRUMENT_TYPES.index(t)))


_FAMILY_BY_TYPE = {t.lower(): fam for fam, t, _ in INSTRUMENT_TYPES}


def family_for_type(type_name):
    """The family the form's own list gives an instrument type; falls back
    to the app-wide keyword match for anything typed in by hand."""
    fam = _FAMILY_BY_TYPE.get(" ".join((type_name or "").lower().split()))
    if fam:
        return fam
    try:
        import instrument_sizes
        return instrument_sizes.family_for(type_name) or "Other"
    except Exception:
        return "Other"


# ── Writing the blank form ───────────────────────────────────────────────────

def write_template(path, program_type="band", schools=None):
    """Write the blank form to ``path``.  ``schools`` (a list of names) adds a
    School column with a dropdown; give it only when there is more than one,
    because a column every row answers the same way is a column to skip."""
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter
    from openpyxl.worksheet.datavalidation import DataValidation
    from openpyxl.workbook.defined_name import DefinedName

    schools = [s for s in (schools or []) if str(s).strip()]
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = SHEET

    headers = list(COLUMNS)
    if len(schools) >= 2:
        headers = [(SCHOOL_HEADER, "_site")] + headers
    type_col = next(i for i, (h, k) in enumerate(headers, 1)
                    if k == "description")
    type_letter = get_column_letter(type_col)

    head_font = Font(bold=True, color="FFFFFF")
    head_fill = PatternFill("solid", fgColor="1F4E79")
    req_fill = PatternFill("solid", fgColor="C55A11")
    thin = Side(style="thin", color="BFBFBF")
    for i, (h, key) in enumerate(headers, 1):
        c = ws.cell(row=1, column=i, value=h)
        c.font = head_font
        c.fill = req_fill if h.endswith("*") else head_fill
        c.alignment = Alignment(wrap_text=True, vertical="center")
        c.border = Border(bottom=thin)
    ws.row_dimensions[1].height = 32
    ws.freeze_panes = "A2"
    widths = {"description": 30, "size": 10, "brand": 16, "model": 16,
              "serial_no": 16, "barcode": 14,
              "condition": 14, "locker": 18, "lock_no": 9,
              "combo": 12, "year_purchased": 10, "amount_paid": 12,
              "est_value": 12, "year_manufactured": 10, "po_number": 12,
              "accessories": 30, "comments": 34, "_site": 28}
    for i, (h, key) in enumerate(headers, 1):
        ws.column_dimensions[get_column_letter(i)].width = widths.get(key, 14)
        if key in _MONEY_COLS:
            for r in range(2, DATA_ROWS + 2):
                ws.cell(row=r, column=i).number_format = '"$"#,##0.00'
    last = get_column_letter(len(headers))
    ws.auto_filter.ref = f"A1:{last}{DATA_ROWS + 1}"

    # Instrument Types sheet: family, type, size group.
    ts = wb.create_sheet(TYPES_SHEET)
    ts["A1"], ts["B1"], ts["C1"] = "Family", "Instrument Type", "Size list"
    ts["E1"] = ("Roka reads this sheet for the Instrument Type dropdown. "
                "Leave it as it is.")
    for c in ("A1", "B1", "C1"):
        ts[c].font = Font(bold=True)
    ts["E1"].font = Font(italic=True, color="808080")
    types = types_for(program_type)
    for r, (fam, name, grp) in enumerate(types, 2):
        ts.cell(row=r, column=1, value=fam)
        ts.cell(row=r, column=2, value=name)
        ts.cell(row=r, column=3,
                value=f"Sizes_{grp.capitalize()}" if grp else "Sizes_None")
    ts.column_dimensions["A"].width = 14
    ts.column_dimensions["B"].width = 34
    ts.column_dimensions["C"].width = 16
    ts.freeze_panes = "A2"
    n_types = len(types) + 1

    # Sizes sheet: one column per size group, each a named range.
    ss = wb.create_sheet(SIZES_SHEET)
    groups = list(SIZE_GROUPS.items()) + [("none", [""])]
    for ci, (grp, vals) in enumerate(groups, 1):
        ss.cell(row=1, column=ci, value=grp.capitalize()).font = Font(bold=True)
        for ri, v in enumerate(vals, 2):
            ss.cell(row=ri, column=ci, value=v)
        letter = get_column_letter(ci)
        ref = f"'{SIZES_SHEET}'!${letter}$2:${letter}${max(len(vals), 1) + 1}"
        wb.defined_names[f"Sizes_{grp.capitalize()}"] = DefinedName(
            f"Sizes_{grp.capitalize()}", attr_text=ref)
    if len(schools) >= 2:
        col = len(groups) + 2
        ss.cell(row=1, column=col, value="Schools").font = Font(bold=True)
        for ri, name in enumerate(schools, 2):
            ss.cell(row=ri, column=col, value=name)
        letter = get_column_letter(col)
        wb.defined_names["Roka_Schools"] = DefinedName(
            "Roka_Schools",
            attr_text=f"'{SIZES_SHEET}'!${letter}$2:${letter}${len(schools) + 1}")

    # Validations on the Inventory sheet.
    span = f"2:{DATA_ROWS + 1}"

    def col_range(key):
        i = next(i for i, (h, k) in enumerate(headers, 1) if k == key)
        L = get_column_letter(i)
        return f"{L}2:{L}{DATA_ROWS + 1}", L

    rng, _ = col_range("description")
    dv = DataValidation(
        type="list", formula1=f"'{TYPES_SHEET}'!$B$2:$B${n_types}",
        allow_blank=True, errorStyle="warning", showErrorMessage=True,
        errorTitle="Not on Roka's list",
        error="Roka does not know this instrument. It will still be imported; "
              "you may need to set its family in Roka afterwards. Keep it?",
        promptTitle="Instrument type",
        prompt="Pick from the list. This decides which accessories print on "
               "the check-out form.")
    dv.showInputMessage = True
    ws.add_data_validation(dv)
    dv.add(rng)

    rng, _ = col_range("size")
    dv = DataValidation(
        type="list",
        formula1=(f"INDIRECT(IFERROR(VLOOKUP(${type_letter}2,"
                  f"'{TYPES_SHEET}'!$B:$C,2,FALSE),\"Sizes_None\"))"),
        allow_blank=True, showErrorMessage=False,
        promptTitle="Size",
        prompt="Strings (1/2, 3/4, a viola in inches) and tubas (3/4 or full). "
               "Leave blank for everything else.")
    dv.showInputMessage = True
    ws.add_data_validation(dv)
    dv.add(rng)

    rng, _ = col_range("condition")
    dv = DataValidation(type="list", formula1='"' + ",".join(CONDITIONS) + '"',
                        allow_blank=True, errorStyle="warning",
                        showErrorMessage=True, errorTitle="Condition",
                        error="Pick one of the listed conditions.")
    ws.add_data_validation(dv)
    dv.add(rng)

    for key in _YEAR_COLS:
        rng, _ = col_range(key)
        dv = DataValidation(type="whole", operator="between", formula1="1850",
                            formula2="2100", allow_blank=True,
                            errorStyle="warning", showErrorMessage=True,
                            errorTitle="Year", error="A four-digit year, e.g. 2014.")
        ws.add_data_validation(dv)
        dv.add(rng)

    for key in _MONEY_COLS:
        rng, _ = col_range(key)
        dv = DataValidation(type="decimal", operator="greaterThanOrEqual",
                            formula1="0", allow_blank=True,
                            errorStyle="warning", showErrorMessage=True,
                            errorTitle="Amount", error="A dollar amount, e.g. 1250.")
        ws.add_data_validation(dv)
        dv.add(rng)

    if len(schools) >= 2:
        rng, _ = col_range("_site")
        dv = DataValidation(type="list", formula1="Roka_Schools",
                            allow_blank=True, errorStyle="warning",
                            showErrorMessage=True, errorTitle="School",
                            error="Pick one of your schools.")
        ws.add_data_validation(dv)
        dv.add(rng)

    # Read Me sheet, plus the marker that says this is a Roka form.
    rm = wb.create_sheet(README_SHEET)
    rm.column_dimensions["A"].width = 100
    lines = [
        ("Roka inventory form", Font(bold=True, size=14)),
        ("", None),
        ("One instrument per row on the Inventory sheet. Fill in what you "
         "know and leave the rest blank; you can add details in Roka later.",
         None),
        ("", None),
        ("Instrument Type is the only required column. Pick from the "
         "dropdown: it decides which accessories print on the check-out "
         "form (a trumpet gets mouthpiece and valve oil, a violin gets bow "
         "and shoulder rest). If your instrument is not on the list, type "
         "it in anyway.", None),
        ("Size is for strings (1/2, 3/4, a viola measured in inches) and "
         "for tubas (3/4 for most middle schools, full size for high "
         "schools). The dropdown follows the instrument you chose.", None),
        ("Serial Number and Barcode (the district asset tag) are how Roka "
         "tells two identical flutes apart. Fill in at least one when you "
         "can; if an instrument has none, Roka still imports it.", None),
        ("Condition: " + ", ".join(CONDITIONS) + ".", None),
        ("Accessories: leave blank to get the usual set for that instrument. "
         "Only fill it in (comma separated) when this one is different.",
         None),
    ]
    if len(schools) >= 2:
        lines.append(("School: which of your schools the instrument lives at. "
                      "Blank rows go to the school you import from.", None))
    lines += [
        ("", None),
        ("When you are done: save this file, then in Roka open Import Data "
         "(or Equipment ▸ Import) and choose it under \"Roka inventory "
         "form\".", None),
        ("", None),
        ("Example row:", Font(bold=True)),
    ]
    for r, (text, font) in enumerate(lines, 1):
        c = rm.cell(row=r, column=1, value=text)
        c.alignment = Alignment(wrap_text=True, vertical="top")
        if font:
            c.font = font
    ex_row = len(lines) + 1
    example = {"description": "Trumpet - Bb", "brand": "Yamaha",
               "model": "YTR-2330", "serial_no": "D12345", "barcode": "000123",
               "condition": "Good", "locker": "Room 12, locker 4",
               "year_purchased": 2019, "amount_paid": 650}
    for i, (h, key) in enumerate(headers, 1):
        rm.cell(row=ex_row, column=i, value=h).font = Font(bold=True)
        rm.cell(row=ex_row + 1, column=i, value=example.get(key))
    for i in range(2, len(headers) + 1):
        rm.column_dimensions[get_column_letter(i)].width = 16
    wb.defined_names[MARKER] = DefinedName(
        MARKER, attr_text=f"'{README_SHEET}'!$A$1")

    ws.sheet_view.tabSelected = True
    wb.active = 0
    wb.save(path)
    return path


# ── Reading a filled-in form ─────────────────────────────────────────────────

def sniff(path):
    """True when an .xlsx is a Roka inventory form (blank or filled in)."""
    try:
        import openpyxl
        import warnings
        warnings.filterwarnings("ignore")
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    except Exception:
        return False
    try:
        if MARKER in wb.defined_names:
            return True
        if SHEET in wb.sheetnames:
            ws = wb[SHEET]
            for row in ws.iter_rows(max_row=1, values_only=True):
                keys = {_key(h) for h in row if h}
                return "instrument type" in keys
        return False
    except Exception:
        return False
    finally:
        try:
            wb.close()
        except Exception:
            pass


def _money(val):
    if val is None or val == "":
        return None
    s = str(val).replace("$", "").replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def _year(val):
    if val is None or val == "":
        return None
    if isinstance(val, float) and val.is_integer():
        val = int(val)
    if hasattr(val, "year"):                      # a date typed into a year box
        return str(val.year)
    return str(val).strip() or None


def _text(val):
    if val is None:
        return ""
    if isinstance(val, float) and val.is_integer():
        return str(int(val))                      # a barcode typed as a number
    return str(val).strip()


def parse_roka_inventory(path):
    """Return instrument dicts (keys matching ``add_instrument``) from a
    filled-in form.  Each carries ``_site`` with the School column's text
    ("" when the form had none) for the importer to resolve."""
    import openpyxl
    import warnings
    import instrument_sizes
    warnings.filterwarnings("ignore")
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb[SHEET] if SHEET in wb.sheetnames else wb.active
    rows = [list(r) for r in ws.iter_rows(values_only=True)]
    wb.close()
    if not rows:
        return []
    by_key = {_key(h): k for h, k in COLUMNS}
    by_key[_key(SCHOOL_HEADER)] = "_site"
    col = {}
    for i, h in enumerate(rows[0]):
        k = by_key.get(_key(h))
        if k and k not in col:
            col[k] = i

    def cell(row, key):
        i = col.get(key)
        if i is None or i >= len(row):
            return None
        return row[i]

    out = []
    for row in rows[1:]:
        if not any(v not in (None, "") for v in row):
            continue
        desc = _text(cell(row, "description"))
        if not (desc or _text(cell(row, "serial_no"))
                or _text(cell(row, "barcode"))):
            continue
        rec = {
            "category": family_for_type(desc) if desc else "Other",
            "description": desc or "Unknown instrument",
            "size": instrument_sizes.normalize_size(_text(cell(row, "size"))) or None,
            "quantity": 1,
            "_site": _text(cell(row, "_site")),
        }
        for key in ("brand", "model", "serial_no", "barcode", "condition",
                    "locker", "lock_no", "combo", "po_number", "accessories",
                    "comments"):
            rec[key] = _text(cell(row, key)) or None
        for key in _YEAR_COLS:
            rec[key] = _year(cell(row, key))
        for key in _MONEY_COLS:
            rec[key] = _money(cell(row, key))
        out.append(rec)
    return out
