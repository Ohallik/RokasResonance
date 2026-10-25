"""
class_names_sync.py - One spelling for each class, everywhere it is stored.

A class is called whatever the teacher calls it in Manage Classes.  The data,
though, keeps whatever spelling it was saved with: a field trip set up while
the class was still the default "MS Band (Intermediate)" stays that way after
it is renamed "Intermediate Band", and so do the students, concerts and
percussion sections created back then.  Everything still MATCHED (the class
identity check treats them as one class), but the two names showed side by
side in lists and pickers.

``sync_class_names`` rewrites each stored class name to the teacher's own
spelling, by identity -- "MS Band (Intermediate)", "Int Band" and
"Intermediate Band" are one class; "Adv Orchestra", "Bellevue Jazz 1" and
"Heavy Metal" are not touched.  It runs when a profile opens and after the
class list is saved, and only writes rows that actually change, so it is
cheap to repeat.  No tkinter here.
"""

import glob
import json
import os
import re
import sqlite3

_PERIOD_NAME = re.compile(r"^(Period\s+\S+)\s*[-–—]\s*(.+)$")


def _labels(base_dir, program_type=None):
    import class_registry as cr
    if program_type is None:
        try:
            from ui.settings_dialog import load_settings
            program_type = (load_settings(base_dir).get("teacher") or {}).get(
                "program_type", "band")
        except Exception:
            program_type = "band"
    return cr.load_classes(base_dir, program_type)


def _canon_one(name, labels):
    import class_registry as cr
    n = (name or "").strip()
    return cr.canonical_class_name(n, labels) if n else name


def _canon_csv(value, labels, dedupe=True):
    """A comma-separated list with each class respelled and, with
    ``dedupe``, repeats collapsed (a student listed in "Intermediate Band,
    MS Band (Intermediate)" is in it once).  A performance ORDER keeps its
    repeats: a group can go on twice."""
    if not value:
        return value
    out = []
    for part in str(value).split(","):
        p = part.strip()
        if not p:
            continue
        c = _canon_one(p, labels)
        if not dedupe or c not in out:
            out.append(c)
    sep = ", " if ", " in str(value) else ","
    return sep.join(out)


def _update(conn, table, key_col, col, fn):
    """Rewrite ``col`` with ``fn`` wherever it changes; returns rows changed."""
    try:
        rows = conn.execute(
            f'SELECT "{key_col}", "{col}" FROM "{table}" '
            f'WHERE "{col}" IS NOT NULL AND "{col}" != ""').fetchall()
    except sqlite3.Error:
        return 0                        # older file without this table/column
    n = 0
    for key, val in rows:
        new = fn(val)
        if new != val:
            conn.execute(f'UPDATE "{table}" SET "{col}"=? WHERE "{key_col}"=?',
                         (new, key))
            n += 1
    return n


def _sync_lesson_plans(path, labels, classes):
    by_key = {k.get("id"): k.get("label") for k in classes}
    n = 0
    conn = sqlite3.connect(path, timeout=10)
    try:
        csv = lambda v: _canon_csv(v, labels)
        one = lambda v: _canon_one(v, labels)
        n += _update(conn, "concerts", "id", "ensembles", csv)
        n += _update(conn, "concerts", "id", "perf_order",
                     lambda v: _canon_csv(v, labels, dedupe=False))
        n += _update(conn, "field_trips", "id", "groups_list", csv)
        n += _update(conn, "concert_pieces", "id", "ensemble", one)

        def chart(raw):
            try:
                cfg = json.loads(raw)
            except (TypeError, ValueError):
                return raw
            changed = False
            for g in cfg.get("groups") or []:
                if isinstance(g, dict) and g.get("ensemble"):
                    c = one(g["ensemble"])
                    if c != g["ensemble"]:
                        g["ensemble"], changed = c, True
            if isinstance(cfg.get("ensembles"), list):
                new = [one(e) for e in cfg["ensembles"]]
                if new != cfg["ensembles"]:
                    cfg["ensembles"], changed = new, True
            return json.dumps(cfg) if changed else raw
        n += _update(conn, "seating_charts", "id", "config_json", chart)

        # A percussion section's name is DERIVED from its class and period
        # ("Period 6 — Intermediate Band"), so it follows the class's name.
        try:
            groups = conn.execute(
                "SELECT id, name, period, class_key FROM percussion_groups"
            ).fetchall()
        except sqlite3.Error:
            groups = []
        for gid, name, period, key in groups:
            label = by_key.get(key)
            m = _PERIOD_NAME.match(name or "")
            if label and str(period or "").strip():
                new = f"Period {str(period).strip()} — {label}"
            elif m:
                c = one(m.group(2))
                new = f"{m.group(1)} — {c}" if c != m.group(2) else name
            else:
                new = name
            if new != name:
                conn.execute("UPDATE percussion_groups SET name=? WHERE id=?",
                             (new, gid))
                n += 1
        conn.commit()
    finally:
        conn.close()
    return n


def sync_class_names(base_dir, main_db=None, include_performances=True):
    """Respell every stored class name to the teacher's configured name.
    Returns the number of records changed (0 on any trouble -- this is
    tidying, never worth stopping a launch for)."""
    try:
        classes = _labels(base_dir)
    except Exception:
        return 0
    labels = [k["label"] for k in classes if k.get("label")]
    if not labels:
        return 0
    n = 0
    db_path = getattr(main_db, "db_path", None) or os.path.join(
        base_dir, "rokas_resonance.db")
    if os.path.exists(db_path):
        conn = sqlite3.connect(db_path, timeout=10)
        try:
            n += _update(conn, "students", "id", "ensembles",
                         lambda v: _canon_csv(v, labels))
            if include_performances:
                n += _update(conn, "performances", "id", "ensemble",
                             lambda v: _canon_one(v, labels))
            conn.commit()
        except sqlite3.Error:
            pass
        finally:
            conn.close()
    for path in glob.glob(os.path.join(base_dir, "lesson_plans_*.db")):
        try:
            n += _sync_lesson_plans(path, labels, classes)
        except sqlite3.Error:
            continue
    return n
