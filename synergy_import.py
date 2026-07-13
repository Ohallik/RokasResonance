"""
synergy_import.py - Parse a Synergy student export CSV into student records.

Every BSD teacher pulls class lists from the same grading software (Synergy), so
the export format is shared.  Its defining quirk: it has ONE ROW PER PARENT /
guardian, so a student with two parents appears in two rows and one with three in
three.  This module groups the rows back into one record per student, collecting
each student's parents in ``Orderby`` order (1 → parent1, 2 → parent2, extras →
notes), and maps the columns onto the app's ``students`` schema.

The class (ensemble) and class period a list belongs to are NOT taken from the
file — the teacher assigns them when importing a given class's CSV — so those,
plus the school year, are left for the caller to fill in.  Pure parsing, no I/O
beyond reading the file; returns plain dicts ready for ``db.add_student``.
"""

import csv
import io
import os
import re


def _header_index(headers, *names):
    """Index of the first header matching any of ``names`` (case-insensitive
    exact), or None.  Handles the export's duplicate column names (ParentEmail,
    Phone, Extn appear twice) by taking the first — which is the parent's own."""
    low = [(h or "").strip().lower() for h in headers]
    for n in names:
        n = n.strip().lower()
        for i, h in enumerate(low):
            if h == n:
                return i
    return None


def _split_name(last_first):
    """"Last, First M." → (first, last).  Falls back to "First Last" order."""
    s = (last_first or "").strip()
    if "," in s:
        last, first = s.split(",", 1)
        return first.strip(), last.strip()
    parts = s.split()
    if len(parts) >= 2:
        return parts[0], " ".join(parts[1:])
    return s, ""


def _clean_first(first):
    """Drop a trailing middle initial so "Lincoln A." → "Lincoln" (a single
    trailing capital, optionally with a period, is a middle initial — a real
    multi-word first name like "Mary Jane" is left alone)."""
    m = re.match(r"^(.*\S)\s+[A-Z]\.?$", (first or "").strip())
    return m.group(1).strip() if m else (first or "").strip()


def _natural_parent(last_first):
    """Parent "Last, First" → "First Last" for display."""
    f, l = _split_name(last_first)
    return f"{f} {l}".strip()


def _split_city_state_zip(csz):
    """"BELLEVUE, WA 98004" → ("Bellevue", "WA", "98004")."""
    s = (csz or "").strip()
    city = state = zc = ""
    if "," in s:
        city, rest = s.split(",", 1)
        city = city.strip().title()
        toks = rest.strip().split()
        if toks:
            state = toks[0]
        if len(toks) > 1:
            zc = toks[1]
    elif s:
        city = s.title()
    return city, state, zc


def parse_synergy_students(source):
    """Parse a Synergy export (a file path OR the raw CSV text) into a list of
    student dicts — one per student, in first-seen order — with keys matching the
    ``students`` table (minus school_year / ensembles / class_periods, which the
    importer assigns per class)."""
    if os.path.exists(str(source)):
        with open(source, encoding="utf-8-sig", newline="") as fh:
            rows = list(csv.reader(fh))
    else:
        rows = list(csv.reader(io.StringIO(source)))
    if not rows:
        return []
    headers = rows[0]
    idx = {
        "sid": _header_index(headers, "Student ID"),
        "name": _header_index(headers, "Student Name"),
        "grd": _header_index(headers, "Grd", "Grade"),
        "gen": _header_index(headers, "Gen", "Gender"),
        "dob": _header_index(headers, "Birth Date", "Birthdate", "DOB"),
        "pname": _header_index(headers, "Parent Name"),
        "pemail": _header_index(headers, "ParentEmail"),
        "pphone": _header_index(headers, "Phone"),
        "relation": _header_index(headers, "Relation"),
        "orderby": _header_index(headers, "Orderby"),
        "email": _header_index(headers, "Email"),          # student email
        "addr": _header_index(headers, "Address"),
        "csz": _header_index(headers, "CityStateZip"),
        "lang": _header_index(headers, "Communication Home Language",
                              "Home Language"),
        "section": _header_index(headers, "Section"),
    }

    def cell(row, key):
        i = idx.get(key)
        return row[i].strip() if (i is not None and i < len(row)) else ""

    students, order = {}, []
    for row in rows[1:]:
        if not any((c or "").strip() for c in row):
            continue
        sid = cell(row, "sid")
        key = sid or cell(row, "name")
        if not key:
            continue
        if key not in students:
            first, last = _split_name(cell(row, "name"))
            city, state, zc = _split_city_state_zip(cell(row, "csz"))
            students[key] = {
                "student_id": sid,
                "first_name": _clean_first(first),
                "last_name": last,
                "grade": (cell(row, "grd").lstrip("0") or cell(row, "grd")),
                "gender": cell(row, "gen"),
                "birth_date": cell(row, "dob"),
                "student_email": cell(row, "email"),
                "address": cell(row, "addr"),
                "city": city, "state": state, "zip_code": zc,
                "_lang": cell(row, "lang"),
                "_section": cell(row, "section"),
                "_parents": {},
            }
            order.append(key)
        pname = cell(row, "pname")
        if pname:
            try:
                ob = int(cell(row, "orderby") or 0)
            except ValueError:
                ob = 0
            # Keep the lowest Orderby if a slot repeats; unknown (0) piles at end.
            students[key]["_parents"].setdefault(ob if ob else 99, {
                "name": _natural_parent(pname),
                "relation": cell(row, "relation"),
                "phone": cell(row, "pphone"),
                "email": cell(row, "pemail"),
            })

    out = []
    for key in order:
        s = students[key]
        parents = [s["_parents"][k] for k in sorted(s["_parents"])]
        rec = {k: v for k, v in s.items() if not k.startswith("_")}
        if parents:
            p = parents[0]
            rec.update(parent1_name=p["name"], parent1_relation=p["relation"],
                       parent1_phone=p["phone"], parent1_email=p["email"])
        if len(parents) > 1:
            p = parents[1]
            rec.update(parent2_name=p["name"], parent2_relation=p["relation"],
                       parent2_phone=p["phone"], parent2_email=p["email"])
        notes = []
        for p in parents[2:]:                       # 3rd+ guardian → notes
            bits = " ".join(x for x in (p["relation"], p["phone"], p["email"]) if x)
            notes.append(f"Add'l contact: {p['name']} ({bits})".strip())
        if s["_lang"] and s["_lang"].strip().lower() not in ("", "english"):
            notes.append(f"Home language: {s['_lang'].strip()}")
        if notes:
            rec["notes"] = "; ".join(notes)
        out.append(rec)
    return out
