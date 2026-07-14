"""
student_transfer.py - Hand off students from one director to another.

A feeder-school director (e.g. a middle-school teacher) exports their outgoing
students WITH instruments and guardian contacts; the receiving director (e.g. the
high school) imports them over the summer as "incoming / provisional" students,
before the official class list exists.  When the official roster is later
imported, matching students are confirmed and the leftovers (who never enrolled)
are reviewed and removed.

This is a Roka-native CSV (its own columns), distinct from a Synergy roster, so
it round-trips instruments + contacts that Synergy doesn't carry.  Pure csv, no
tkinter.
"""

import csv

# Columns carried in a handoff file (the student fields worth transferring).
FIELDS = [
    "student_id", "first_name", "last_name", "grade", "gender", "birth_date",
    "primary_instrument", "secondary_instrument", "jazz_instrument",
    "parent1_name", "parent1_relation", "parent1_phone", "parent1_email",
    "parent2_name", "parent2_relation", "parent2_phone", "parent2_email",
    "address", "city", "state", "zip_code", "phone", "student_email", "notes",
]


def export_students(students, out_path):
    """Write the given student rows to a handoff CSV."""
    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        for s in students:
            w.writerow({k: (s.get(k) if s.get(k) is not None else "")
                        for k in FIELDS})
    return out_path


# Header aliases so a handoff file is read whether its columns are the friendly
# "Outgoing students for HS directors" headers (Last Name, Primary Instrument, …)
# or this module's raw field names.
_ALIASES = {
    "student id": "student_id", "student_id": "student_id",
    "last name": "last_name", "last_name": "last_name",
    "first name": "first_name", "first_name": "first_name",
    "grade": "grade", "gender": "gender",
    "birth date": "birth_date", "birth_date": "birth_date",
    "primary instrument": "primary_instrument", "primary_instrument": "primary_instrument",
    "secondary instrument": "secondary_instrument", "secondary_instrument": "secondary_instrument",
    "jazz instrument": "jazz_instrument", "jazz_instrument": "jazz_instrument",
    "ensembles": "ensembles",
    "student email": "student_email", "student_email": "student_email",
    "phone": "phone",
    "parent 1 name": "parent1_name", "parent1_name": "parent1_name",
    "parent 1 email": "parent1_email", "parent1_email": "parent1_email",
    "parent 1 phone": "parent1_phone", "parent1_phone": "parent1_phone",
    "parent 2 name": "parent2_name", "parent2_name": "parent2_name",
    "parent 2 email": "parent2_email", "parent2_email": "parent2_email",
    "parent 2 phone": "parent2_phone", "parent2_phone": "parent2_phone",
    "address": "address", "city": "city", "state": "state",
    "zip_code": "zip_code", "zip": "zip_code",
    "notes": "notes",
}


def import_handoff(db, path, school_year):
    """Import a handoff CSV as PROVISIONAL (incoming) students for ``school_year``.
    Reads the "Outgoing students for HS directors" export format (or this module's
    own).  Dedups by district Student ID (and name as a fallback) so re-importing
    or a student already present is not duplicated.  Returns a summary dict."""
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    if len(rows) < 2:
        return {"added": 0, "skipped": 0, "total": 0}

    idx = {}
    for i, h in enumerate(rows[0]):
        key = _ALIASES.get((h or "").strip().lower())
        if key and key not in idx:
            idx[key] = i

    def cell(row, key):
        i = idx.get(key)
        return (row[i].strip() if i is not None and i < len(row) else "")

    existing_ids, existing_names = set(), set()
    for s in db.get_all_students(school_year):
        if s.get("student_id"):
            existing_ids.add(str(s["student_id"]).strip())
        existing_names.add((str(s.get("first_name") or "").strip().lower(),
                            str(s.get("last_name") or "").strip().lower()))

    added = skipped = 0
    for row in rows[1:]:
        if not any((c or "").strip() for c in row):
            continue
        fn, ln = cell(row, "first_name"), cell(row, "last_name")
        if not (fn or ln):
            skipped += 1
            continue
        sid = cell(row, "student_id")
        if (sid and sid in existing_ids) or (fn.lower(), ln.lower()) in existing_names:
            skipped += 1
            continue
        rec = {k: cell(row, k) for k in idx}
        rec["school_year"] = school_year
        rec["provisional"] = 1
        db.add_student(rec)
        if sid:
            existing_ids.add(sid)
        existing_names.add((fn.lower(), ln.lower()))
        added += 1
    return {"added": added, "skipped": skipped, "total": len(rows) - 1}
