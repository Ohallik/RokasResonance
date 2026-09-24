"""
roka_roster_xlsx.py - Roka's own blank student roster form (.xlsx), and its reader.

Not every teacher can pull the parent/student directory out of the district
system.  An elementary specialist is not the classroom teacher of record, so
Synergy hands them the simple student list -- a name and an ID number -- and
nothing else.  This is the student counterpart of ``roka_inventory_xlsx``:
Roka saves a blank sheet whose columns are the fields of the Student window,
the teacher pastes whatever list they have into it (and fills in what else
they know), and Roka reads it back.

Only the name is required, plus the school when the teacher has several.  The
class column suggests but never restricts: "Beginning Band", "Symphonic
Winds" and "Section 2" are all real classes somewhere, so whatever is typed
is what the student is put in.

Everything is matched BY HEADER NAME, never by position, so a teacher who
deletes or reorders a column has not broken anything, and the headings other
lists use ("Student Name", "Grd", "Parent Name") are understood as well.
"""

import csv
import io
import os
import re

SHEET = "Students"
LISTS_SHEET = "Lists"
README_SHEET = "Read Me"
MARKER = "RokaRosterForm"            # a defined name that says "this is ours"
DATA_ROWS = 500

SCHOOL_KEY = "_site"
CHOIR_KEY = "_choir"
NAME_KEY = "_name"                   # a single "Last, First" column, when read

GRADES = ["K", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12"]
GENDERS = ["Male", "Female", "Non-binary", "Prefer not to say"]
PERIODS = ["0", "1", "2", "3", "4", "5", "6", "7"]
RELATIONS = ["Parent", "Guardian", "Grandparent", "Step-parent", "Other"]
YES_NO = ["Yes", "No"]

# Header text on the form -> students column, in the order the Student window
# shows them.  The School column goes in front when the teacher has schools.
_BASIC = [
    ("First Name *", "first_name"),
    ("Last Name *", "last_name"),
    ("Preferred Name", "preferred_name"),
    ("Grade", "grade"),
    ("Gender", "gender"),
    ("Student ID", "student_id"),
]
_SECONDARY_CLASSES = [
    ("Ensemble(s)", "ensembles"),
    ("Class Period(s)", "class_periods"),
]
_ELEMENTARY_CLASSES = [
    ("Section", "ensembles"),
    ("Also sings in choir", CHOIR_KEY),
]
_SECONDARY_INSTRUMENTS = [
    ("Concert Instrument (Primary)", "primary_instrument"),
    ("Concert Instrument (Secondary)", "secondary_instrument"),
    ("Jazz Band Instrument", "jazz_instrument"),
]
_ELEMENTARY_INSTRUMENTS = [
    ("5th Grade Instrument", "primary_instrument"),
]
_CONTACT = [
    ("Phone", "phone"),
    ("Student Email", "student_email"),
    ("Address", "address"),
    ("City", "city"),
    ("State", "state"),
    ("ZIP", "zip_code"),
    ("Parent 1 Name", "parent1_name"),
    ("Parent 1 Relation", "parent1_relation"),
    ("Parent 1 Phone", "parent1_phone"),
    ("Parent 1 Email", "parent1_email"),
    ("Parent 2 Name", "parent2_name"),
    ("Parent 2 Relation", "parent2_relation"),
    ("Parent 2 Phone", "parent2_phone"),
    ("Parent 2 Email", "parent2_email"),
    ("Notes", "notes"),
]
SCHOOL_HEADER = "School"


def columns_for(level="secondary"):
    """The form's columns for a profile: "elementary" (sections, one
    instrument, a choir box, no periods), "secondary" (ensembles, periods,
    two concert instruments and jazz), or "mixed" (secondary's columns plus
    the choir box, for a teacher who has both kinds of school)."""
    if level == "elementary":
        return _BASIC + _ELEMENTARY_CLASSES + _ELEMENTARY_INSTRUMENTS + _CONTACT
    cols = _BASIC + _SECONDARY_CLASSES
    if level == "mixed":
        cols = cols + [("Also sings in choir", CHOIR_KEY)]
    return cols + _SECONDARY_INSTRUMENTS + _CONTACT


# Other headings the reader understands, so a Synergy student list, the HS
# transfer CSV, or a colleague's own spreadsheet all import without editing.
ALIASES = {
    "school": SCHOOL_KEY, "building": SCHOOL_KEY, "site": SCHOOL_KEY,
    "student name": NAME_KEY, "name": NAME_KEY, "student": NAME_KEY,
    "full name": NAME_KEY,
    "first name": "first_name", "first": "first_name", "given name": "first_name",
    "last name": "last_name", "last": "last_name", "surname": "last_name",
    "family name": "last_name",
    "student id": "student_id", "id": "student_id", "student number": "student_id",
    "perm id": "student_id", "sis id": "student_id", "student #": "student_id",
    "grade": "grade", "grd": "grade", "grade level": "grade", "gr": "grade",
    "class": "ensembles", "ensemble": "ensembles", "ensembles": "ensembles",
    "section": "ensembles", "group": "ensembles", "course": "ensembles",
    "class / ensemble": "ensembles", "class/ensemble": "ensembles",
    "period": "class_periods", "class period": "class_periods",
    "class periods": "class_periods", "per": "class_periods",
    "instrument": "primary_instrument", "primary instrument": "primary_instrument",
    "concert instrument": "primary_instrument",
    "part": "primary_instrument", "voice part": "primary_instrument",
    "second instrument": "secondary_instrument",
    "secondary instrument": "secondary_instrument",
    "jazz instrument": "jazz_instrument",
    "choir": CHOIR_KEY, "in choir": CHOIR_KEY, "sings in choir": CHOIR_KEY,
    "preferred name": "preferred_name", "nickname": "preferred_name",
    "goes by": "preferred_name",
    "gender": "gender", "gen": "gender", "sex": "gender",
    "birth date": "birth_date", "birthdate": "birth_date", "dob": "birth_date",
    "date of birth": "birth_date", "birthday": "birth_date",
    "student email": "student_email", "email": "student_email",
    "student e-mail": "student_email",
    "home phone": "phone", "phone number": "phone",
    "street": "address", "street address": "address",
    "zip": "zip_code", "zip code": "zip_code", "postal code": "zip_code",
    "parent name": "parent1_name", "parent/guardian": "parent1_name",
    "parent": "parent1_name", "guardian": "parent1_name",
    "guardian 1": "parent1_name", "parent 1": "parent1_name",
    "relation": "parent1_relation", "relationship": "parent1_relation",
    "parent phone": "parent1_phone", "guardian phone": "parent1_phone",
    "parent email": "parent1_email", "parentemail": "parent1_email",
    "guardian email": "parent1_email",
    "guardian 2": "parent2_name", "parent 2": "parent2_name",
    "note": "notes", "comments": "notes",
}

_RE_ID = re.compile(r"^\d{4,}$")
_RE_GRADE = re.compile(r"^(k|kg|kinder|kindergarten|\d{1,2})(st|nd|rd|th)?$", re.I)
_RE_DATE = re.compile(r"^\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}$")
_RE_PHONE = re.compile(r"^[\d\-\(\) .+]{7,}$")


def _key(header):
    """Heading text -> lookup key: no "*", one space between words, lower."""
    h = str(header or "").replace("*", "").strip().lower()
    return " ".join(h.split())


def _header_keys():
    keys = {}
    for level in ("secondary", "mixed", "elementary"):
        for h, k in columns_for(level):
            keys.setdefault(_key(h), k)
    keys[_key(SCHOOL_HEADER)] = SCHOOL_KEY
    for a, k in ALIASES.items():
        keys.setdefault(a, k)
    return keys


def header_map(cells):
    """{column index: students key} for a heading row, or {} when the row is
    not a heading (nothing in it names a student column)."""
    keys = _header_keys()
    out = {}
    for i, h in enumerate(cells):
        full = _key(h)
        k = keys.get(full) or keys.get(full.split("(")[0].strip())
        if k and k not in out.values():
            out[i] = k
    if not any(k in (NAME_KEY, "first_name", "last_name") for k in out.values()):
        return {}
    return out


def _text(val):
    if val is None:
        return ""
    if isinstance(val, float) and val.is_integer():
        return str(int(val))                    # an ID typed as a number
    if hasattr(val, "strftime"):                # a real date cell
        return val.strftime("%m/%d/%Y")
    return str(val).strip()


def normalize_grade(val):
    """"05" -> "5", "5th" -> "5", "KG" -> "K".  Anything else is left alone."""
    s = _text(val)
    m = _RE_GRADE.match(s)
    if not m:
        return s
    core = m.group(1).lower()
    if core.startswith("k"):
        return "K"
    return core.lstrip("0") or "0"


def yes(val):
    """A Yes/No cell -> True/False, or None when blank."""
    s = _text(val).lower()
    if not s:
        return None
    return s in ("yes", "y", "true", "x", "1", "choir", "✓", "✔")


def split_name(raw):
    """"Last, First M." / "First Last" / "First M. Last" -> (first, last).

    A comma means "Last, First", which is how every district list is written.
    Without one the LAST word is the surname, so "Mary Jane Smith" is Mary
    Jane Smith rather than Mary "Jane Smith"."""
    import synergy_import
    s = " ".join(_text(raw).split())
    if not s:
        return "", ""
    if "," in s:
        last, first = s.split(",", 1)
        return synergy_import._clean_first(first.strip()), last.strip()
    parts = s.split()
    if len(parts) == 1:
        return parts[0], ""
    return synergy_import._clean_first(" ".join(parts[:-1])), parts[-1]


# ── Writing the blank form ───────────────────────────────────────────────────

def write_template(path, schools=None, classes=None, instruments=None,
                   jazz_instruments=None, relations=None, level="secondary"):
    """Write the blank form to ``path``.

    ``schools`` (names) adds a School column with a dropdown; it is marked
    required when there are two or more, because then a blank row has no
    answer.  ``classes``, ``instruments`` and ``jazz_instruments`` are
    SUGGESTIONS for their dropdowns: whatever the teacher types is accepted,
    since the classes at their school are theirs to name.  ``level`` picks
    the column set (see ``columns_for``)."""
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter
    from openpyxl.worksheet.datavalidation import DataValidation
    from openpyxl.workbook.defined_name import DefinedName

    def clean(vals):
        out = []
        for v in vals or []:
            v = str(v).strip()
            if v and v not in out:
                out.append(v)
        return out

    schools = clean(schools)
    classes = clean(classes)
    instruments = clean(instruments)
    jazz_instruments = clean(jazz_instruments)
    relations = clean(relations) or list(RELATIONS)
    elementary = level == "elementary"

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = SHEET

    headers = list(columns_for(level))
    if schools:
        head = SCHOOL_HEADER + (" *" if len(schools) >= 2 else "")
        headers = [(head, SCHOOL_KEY)] + headers

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
    widths = {SCHOOL_KEY: 28, "first_name": 16, "last_name": 18,
              "preferred_name": 14, "grade": 7, "gender": 10, "student_id": 12,
              "ensembles": 24, "class_periods": 9, CHOIR_KEY: 9,
              "primary_instrument": 20, "secondary_instrument": 20,
              "jazz_instrument": 18, "phone": 14, "student_email": 28,
              "address": 26, "city": 14, "state": 6, "zip_code": 8,
              "parent1_name": 22, "parent1_relation": 11, "parent1_phone": 14,
              "parent1_email": 28, "parent2_name": 22, "parent2_relation": 11,
              "parent2_phone": 14, "parent2_email": 28, "notes": 34}
    for i, (h, key) in enumerate(headers, 1):
        ws.column_dimensions[get_column_letter(i)].width = widths.get(key, 14)
        if key in ("student_id", "zip_code", "phone", "parent1_phone",
                   "parent2_phone", "class_periods"):
            # Text, so Excel keeps a leading zero and never turns an ID into
            # 1.77E+06 or "3, 6" into a date.
            for r in range(2, DATA_ROWS + 2):
                ws.cell(row=r, column=i).number_format = "@"
    last = get_column_letter(len(headers))
    ws.auto_filter.ref = f"A1:{last}{DATA_ROWS + 1}"

    # Lists sheet: one column per dropdown, each a named range.
    ls = wb.create_sheet(LISTS_SHEET)
    ls["A1"] = ("Roka reads this sheet for the dropdowns on the Students "
                "sheet. Leave it as it is.")
    ls["A1"].font = Font(italic=True, color="808080")
    lists = [("Grades", GRADES), ("Genders", GENDERS), ("Periods", PERIODS),
             ("YesNo", YES_NO), ("Relations", relations)]
    if schools:
        lists.append(("Schools", schools))
    if classes:
        lists.append(("Classes", classes))
    if instruments:
        lists.append(("Instruments", instruments))
    if jazz_instruments:
        lists.append(("Jazz", jazz_instruments))
    names = {}
    for ci, (title, vals) in enumerate(lists, 1):
        ls.cell(row=2, column=ci, value=title).font = Font(bold=True)
        for ri, v in enumerate(vals, 3):
            ls.cell(row=ri, column=ci, value=v)
        letter = get_column_letter(ci)
        ls.column_dimensions[letter].width = 26
        ref = f"'{LISTS_SHEET}'!${letter}$3:${letter}${len(vals) + 2}"
        nm = f"Roka_{title}"
        wb.defined_names[nm] = DefinedName(nm, attr_text=ref)
        names[title] = nm

    def col_range(key):
        i = next((i for i, (h, k) in enumerate(headers, 1) if k == key), None)
        if i is None:
            return None
        L = get_column_letter(i)
        return f"{L}2:{L}{DATA_ROWS + 1}"

    def add_list(key, title, strict, prompt_title, prompt, err=None):
        rng = col_range(key)
        if not rng or title not in names:
            return
        dv = DataValidation(
            type="list", formula1=names[title], allow_blank=True,
            # "warning" lets a typed value through after a question; a
            # dropdown that only suggests shows no error at all.
            errorStyle="warning", showErrorMessage=bool(strict),
            errorTitle=prompt_title, error=err or "",
            promptTitle=prompt_title, prompt=prompt)
        dv.showInputMessage = True
        ws.add_data_validation(dv)
        dv.add(rng)

    def add_prompt(key, title, prompt):
        rng = col_range(key)
        if not rng:
            return
        # No type: Excel's "Any value", which exists only to carry the
        # input message.
        dv = DataValidation(allow_blank=True, showErrorMessage=False,
                            promptTitle=title, prompt=prompt)
        dv.showInputMessage = True
        ws.add_data_validation(dv)
        dv.add(rng)

    add_list(SCHOOL_KEY, "Schools", True, "School",
             "Which of your schools this student is at.",
             "Pick one of your schools.")
    add_prompt("last_name", "Last Name",
               "If your list has names as Last, First in one column, paste "
               "it here and leave First Name blank. Roka splits them.")
    add_list("grade", "Grades", True, "Grade", "K through 12.",
             "A grade from K to 12.")
    add_list("gender", "Genders", True, "Gender", "Optional.",
             "Pick one of the listed options, or leave it blank.")
    add_prompt("student_id", "Student ID", "The district ID number.")
    if elementary:
        add_list("ensembles", "Classes", False, "Section",
                 "Section 1 or Section 2. Type another name if your school "
                 "calls its group something else.")
    else:
        add_list("ensembles", "Classes", False, "Ensemble(s)",
                 "Pick one or type your own. Several: separate with commas.")
        add_list("class_periods", "Periods", True, "Class Period(s)",
                 "The period this class meets. Several: separate with commas.",
                 "A period number, 0 to 7.")
    add_list(CHOIR_KEY, "YesNo", True, "Also sings in choir",
             "Yes if the student is in the school's choir as well as their "
             "section.", "Yes or No.")
    add_list("primary_instrument", "Instruments", False,
             "5th Grade Instrument" if elementary else "Concert Instrument",
             "Pick one or type your own.")
    add_list("secondary_instrument", "Instruments", False,
             "Concert Instrument (Secondary)", "Only if they play a second one.")
    add_list("jazz_instrument", "Jazz", False, "Jazz Band Instrument",
             "Only if different in jazz band (a horn player on guitar).")
    add_list("parent1_relation", "Relations", False, "Relation",
             "Mother, Father, Guardian… or type your own.")
    add_list("parent2_relation", "Relations", False, "Relation",
             "Mother, Father, Guardian… or type your own.")

    # Read Me sheet, plus the marker that says this is a Roka form.
    rm = wb.create_sheet(README_SHEET)
    rm.column_dimensions["A"].width = 100
    lines = [
        ("Roka student roster form", Font(bold=True, size=14)),
        ("", None),
        ("One student per row on the Students sheet. The columns are the "
         "fields of Roka's Student window. Fill in what you know and leave "
         "the rest blank; you can add details in Roka later.", None),
        ("", None),
        ("First Name and Last Name are the only columns every row needs. "
         "If your list has names as Last, First in one column (the way the "
         "district writes them), paste that column into Last Name and leave "
         "First Name blank: Roka splits them.", None),
    ]
    if len(schools) >= 2:
        lines.append(("School is required too: pick which of your schools "
                      "each student is at. Rows left blank go to the school "
                      "you import from.", None))
    elif schools:
        lines.append(("School: your one school is already the only choice, "
                      "so you can leave it blank.", None))
    lines.append(("Grade: K through 12.", None))
    if elementary:
        lines += [
            ("Section: Section 1 or Section 2 (or whatever your school "
             "calls its group, typed in). Also sings in choir: Yes for a "
             "student who is in the school's choir as well.", None),
            ("5th Grade Instrument: pick from the list or type your own.",
             None),
        ]
    else:
        lines += [
            ("Ensemble(s): the class this student is in, in your own words. "
             "The dropdown suggests the classes Roka already knows, but type "
             "whatever your school calls it. A student in two classes: "
             "separate them with commas.", None),
            ("Class Period(s): the period the class meets. Leave blank at an "
             "elementary school.", None),
            ("Instruments: pick from the list or type your own. Jazz Band "
             "Instrument only if it differs from the concert instrument.",
             None),
        ]
        if level == "mixed":
            lines.append(("Also sings in choir: Yes for an elementary "
                          "student who is in the school's choir as well as "
                          "their section.", None))
    lines += [
        ("Parent / Guardian 1 and 2: a family contact each. Names, phones "
         "and emails are optional, but they are what the email lists and "
         "the loan forms use.", None),
        ("", None),
        ("A student already on this year's roster (same Student ID, or the "
         "same name) is updated rather than added twice, so you can add "
         "rows to this sheet and import it again.", None),
        ("", None),
        ("When you are done: save this file, then in Roka open Students and "
         "choose Import > Student list (Roka roster form), or on a 5th "
         "grade school's tab click Import Class List.", None),
        ("", None),
        ("Example rows:", Font(bold=True)),
    ]
    for r, (text, font) in enumerate(lines, 1):
        c = rm.cell(row=r, column=1, value=text)
        c.alignment = Alignment(wrap_text=True, vertical="top")
        if font:
            c.font = font
    ex_row = len(lines) + 1
    first_class = classes[0] if classes else ("Section 1" if elementary
                                              else "Concert Band")
    examples = [
        {SCHOOL_KEY: schools[0] if schools else None,
         "first_name": "Ines", "last_name": "Barros", "grade": "5",
         "student_id": "1770401", "ensembles": first_class,
         "class_periods": None if elementary else "2",
         "primary_instrument": "Flute",
         "parent1_name": "Teresa Barros", "parent1_relation": "Mother",
         "parent1_phone": "425-555-0710",
         "parent1_email": "teresa.barros@example.com"},
        {SCHOOL_KEY: schools[0] if schools else None,
         "first_name": None, "last_name": "Nakamura, Kai",
         "student_id": "1770455", "grade": "5"},
    ]
    for i, (h, key) in enumerate(headers, 1):
        rm.cell(row=ex_row, column=i, value=h).font = Font(bold=True)
        for n, ex in enumerate(examples, 1):
            rm.cell(row=ex_row + n, column=i, value=ex.get(key))
    for i in range(2, len(headers) + 1):
        rm.column_dimensions[get_column_letter(i)].width = 16
    wb.defined_names[MARKER] = DefinedName(
        MARKER, attr_text=f"'{README_SHEET}'!$A$1")

    ws.sheet_view.tabSelected = True
    wb.active = 0
    wb.save(path)
    return path


# ── Reading a filled-in form (or any list with headings Roka knows) ──────────

def sniff(path):
    """True when an .xlsx is a Roka roster form (blank or filled in), or any
    workbook whose first row names a student column."""
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
        ws = wb[SHEET] if SHEET in wb.sheetnames else wb.active
        for row in ws.iter_rows(max_row=1, values_only=True):
            return bool(header_map(list(row)))
        return False
    except Exception:
        return False
    finally:
        try:
            wb.close()
        except Exception:
            pass


def read_rows(path):
    """A file's cells as a list of rows (lists of text).  Reads .xlsx and
    .csv/.txt; raises ValueError with a sentence a teacher can act on for
    anything else."""
    ext = os.path.splitext(path or "")[1].lower()
    if ext in (".xlsx", ".xlsm"):
        import openpyxl
        import warnings
        warnings.filterwarnings("ignore")
        wb = openpyxl.load_workbook(path, data_only=True)
        try:
            ws = wb[SHEET] if SHEET in wb.sheetnames else wb.active
            return [[_text(v) for v in r] for r in ws.iter_rows(values_only=True)]
        finally:
            wb.close()
    if ext == ".xls":
        raise ValueError("This is an old-style Excel file (.xls). Open it in "
                         "Excel and use Save As to make an .xlsx or a CSV.")
    import synergy_import
    with open(path, "rb") as fh:
        text = synergy_import._decode_export(fh.read())
    return text_to_rows(text)


def text_to_rows(text):
    """CSV (or tab-separated) text -> rows.

    Tabs win when there are any (Excel's "Unicode Text" save).  Otherwise
    commas, but only when the text really is a CSV: a bare list of "Last,
    First" names has one comma per line and is NOT a CSV, so those lines
    are read whole."""
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    text = text.lstrip("﻿")
    lines = [ln for ln in text.split("\n") if ln.strip()]
    if not lines:
        return []
    if any("\t" in ln for ln in lines):
        return [[c.strip() for c in ln.split("\t")] for ln in lines]
    counts = [ln.count(",") for ln in lines]
    quoted = sum(1 for ln in lines if '"' in ln)
    if max(counts) >= 2 and (quoted or sum(1 for c in counts if c >= 2)
                             >= max(1, len(lines) // 2)):
        return [[c.strip() for c in row]
                for row in csv.reader(io.StringIO("\n".join(lines)))]
    out = []
    for ln in lines:
        parts = [p.strip() for p in re.split(r"\s{2,}", ln.strip()) if p.strip()]
        out.append(parts or [ln.strip()])
    return out


def match_school(cell, schools):
    """The school a cell names, matched loosely: "Clyde Hill" finds "Clyde
    Hill Elementary School" as long as it finds only that one.  Returns the
    name as given in ``schools``, or None."""
    s = " ".join(_text(cell).lower().split())
    if not s or not schools:
        return None
    for name in schools:
        if " ".join(str(name).lower().split()) == s:
            return name
    hits = [name for name in schools
            if s in " ".join(str(name).lower().split())
            or " ".join(str(name).lower().split()) in s]
    return hits[0] if len(hits) == 1 else None


def _guess_row(cells, schools):
    """A row with no heading: decide what each cell is by its shape."""
    rec = {}
    for cell in cells:
        s = _text(cell)
        if not s:
            continue
        low = s.lower()
        if "@" in s:
            rec.setdefault("student_email", s)
        elif _RE_ID.match(s):
            rec.setdefault("student_id", s)
        elif _RE_DATE.match(s):
            rec.setdefault("birth_date", s)
        elif _RE_GRADE.match(s) and (
                low.startswith("k") or int(re.sub(r"\D", "", s) or 99) <= 12):
            rec.setdefault("grade", normalize_grade(s))
        elif _RE_PHONE.match(s) and sum(ch.isdigit() for ch in s) >= 7:
            rec.setdefault("phone", s)
        elif schools and match_school(s, schools):
            rec.setdefault(SCHOOL_KEY, match_school(s, schools))
        elif NAME_KEY not in rec:
            rec[NAME_KEY] = s
        # Any further text (a teacher's name, a section code) is nothing
        # Roka can safely file, so it is left where it is.
    return rec


def rows_to_students(rows, schools=None):
    """Rows (lists of text) -> student dicts with keys matching the students
    table, plus ``_site`` (the School text, "" when none) and ``_choir``
    (True/False/None).

    The first row is a heading when it names a student column; otherwise
    every row is data and the columns are guessed from their shape (a bare
    name-and-ID list with no heading still imports)."""
    rows = [[_text(c) for c in r] for r in (rows or [])]
    rows = [r for r in rows if any(r)]
    if not rows:
        return []
    hmap = header_map(rows[0])
    body = rows[1:] if hmap else rows
    out = []
    for r in body:
        if hmap:
            rec = {}
            for i, key in hmap.items():
                if i < len(r) and r[i]:
                    rec[key] = r[i]
        else:
            rec = _guess_row(r, schools)
        first = rec.pop("first_name", "")
        last = rec.pop("last_name", "")
        raw = rec.pop(NAME_KEY, "")
        if raw and not (first or last):
            first, last = split_name(raw)
        elif last and not first and ("," in last or " " in last.strip()):
            first, last = split_name(last)      # "Last, First" pasted whole
        elif first and not last and "," in first:
            first, last = split_name(first)
        first, last = " ".join(first.split()), " ".join(last.split())
        if not (first or last):
            continue
        rec["first_name"], rec["last_name"] = first, last
        if "grade" in rec:
            rec["grade"] = normalize_grade(rec["grade"])
        for key in ("parent1_name", "parent2_name"):
            if rec.get(key) and "," in rec[key]:
                f, l = split_name(rec[key])
                rec[key] = f"{f} {l}".strip()
        rec[SCHOOL_KEY] = _text(rec.get(SCHOOL_KEY, ""))
        rec[CHOIR_KEY] = yes(rec.get(CHOIR_KEY))
        out.append(rec)
    return out


def parse_roka_roster(path, schools=None):
    """Student dicts from a filled-in form, a CSV, or any spreadsheet with a
    heading row Roka understands."""
    return rows_to_students(read_rows(path), schools=schools)
