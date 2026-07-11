"""
ui/year_wizard.py - New School Year wizard.

Closes out one school year and opens the next, the way teachers expect:
  1. pick the new year
  2. archive last year's students (kept in the database, just inactive)
  3. import this year's class lists from CSV — every student on a list is
     assigned to the ensemble and class period(s) you choose; returning
     students are rolled forward automatically, new ones are created
  4. pointers for the new budget and concert/field-trip dates

Built for an unskilled user: one window, top to bottom, nothing destructive.
"""

import csv
import os
import tkinter as tk
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from ttkbootstrap.dialogs import Messagebox
from tkinter import filedialog

from ui.theme import fs, muted_fg, fit_window


def _next_school_year(current: str) -> str:
    try:
        start = int(current.split("-")[0])
        return f"{start + 1}-{start + 2}"
    except (ValueError, IndexError):
        from lesson_plan_db import current_school_year
        return current_school_year()


def _split_name(row, cols):
    """(first, last) from a CSV row using detected columns."""
    if cols.get("first") is not None and cols.get("last") is not None:
        return row[cols["first"]].strip(), row[cols["last"]].strip()
    raw = (row[cols["name"]] or "").strip()
    if "," in raw:                       # "Last, First"
        last, first = raw.split(",", 1)
        return first.strip(), last.strip()
    parts = raw.split()                  # "First [Middle] Last"
    if len(parts) >= 2:
        return " ".join(parts[:-1]), parts[-1]
    return raw, ""


def read_class_csv(path):
    """Parse a class-list CSV.  Returns a list of {first, last, instrument}
    dicts.  Column detection is forgiving: any header containing first/last
    (or a single name/student column, 'Last, First' or 'First Last') works."""
    with open(path, newline="", encoding="utf-8-sig", errors="replace") as f:
        sample = f.read(4096)
        f.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        rows = list(csv.reader(f, dialect))
    if not rows:
        return []
    headers = [h.strip().lower() for h in rows[0]]

    def find(*keys):
        for i, h in enumerate(headers):
            if any(k in h for k in keys):
                return i
        return None

    cols = {
        "first": find("first"),
        "last": find("last"),
        "name": find("student name", "name", "student"),
        "instrument": find("instrument"),
    }
    has_header = (cols["first"] is not None or cols["last"] is not None
                  or cols["name"] is not None)
    if not has_header:
        # No recognizable header — treat every row as data, first two columns
        # as first/last (or one column as full name).
        cols = {"first": 0 if len(rows[0]) > 1 else None,
                "last": 1 if len(rows[0]) > 1 else None,
                "name": 0 if len(rows[0]) == 1 else None,
                "instrument": None}
        data = rows
    else:
        data = rows[1:]

    out = []
    for row in data:
        if not any((c or "").strip() for c in row):
            continue
        row = list(row) + [""] * 6      # pad short rows
        first, last = _split_name(row, cols)
        if not (first or last):
            continue
        inst = ""
        if cols.get("instrument") is not None:
            inst = (row[cols["instrument"]] or "").strip()
        out.append({"first": first, "last": last, "instrument": inst})
    return out


def import_class_list(db, students, school_year, ensemble, periods):
    """Assign every parsed student to ensemble/periods for school_year.
    Returning students (matched by name, any year) are rolled forward and
    reactivated; unknown names become new records.  Returns (added, updated)."""
    all_students = [dict(r) for r in db.get_all_students(include_inactive=True)]

    def match(first, last):
        fl, ll = first.strip().lower(), last.strip().lower()
        if not fl or not ll:
            return None
        for s in all_students:
            if (s.get("last_name") or "").strip().lower() != ll:
                continue
            sf = (s.get("first_name") or "").strip().lower()
            pf = (s.get("preferred_name") or "").strip().lower()
            # exact first/preferred name, or same first word (middle names
            # come and go between district exports)
            if sf == fl or pf == fl or sf.split()[:1] == fl.split()[:1]:
                return s
        return None

    added = updated = 0
    touched_ids = []
    for stu in students:
        existing = match(stu["first"], stu["last"])
        if existing:
            rolled_forward = (existing.get("school_year") or "") != school_year
            data = dict(existing)
            data["school_year"] = school_year
            data["is_active"] = 1
            if stu["instrument"] and not (data.get("primary_instrument") or "").strip():
                data["primary_instrument"] = stu["instrument"]
            db.update_student(existing["id"], data)
            if rolled_forward:
                # Honors / Jr. All-State are earned fresh each year
                db.set_student_honors(existing["id"], honors=False,
                                      all_state=False)
            touched_ids.append(existing["id"])
            updated += 1
        else:
            sid = db.add_student({
                "first_name": stu["first"], "last_name": stu["last"],
                "school_year": school_year,
                "primary_instrument": stu["instrument"],
            })
            touched_ids.append(sid)
            added += 1
    if touched_ids:
        if ensemble:
            db.bulk_set_student_multi(touched_ids, "ensembles", [ensemble])
        if periods:
            db.bulk_set_student_multi(touched_ids, "class_periods",
                                      [str(p) for p in periods])
    return added, updated


class NewSchoolYearWizard(ttk.Toplevel):
    def __init__(self, parent, main_db, base_dir, current_year):
        super().__init__(parent)
        self.main_db = main_db
        self.base_dir = base_dir
        self.current_year = current_year
        self.new_year = None            # set on Finish
        self._imports = []              # (filename, ensemble, added, updated)

        self.title("New School Year")
        self.resizable(True, True)
        self.grab_set()

        hdr = ttk.Frame(self, bootstyle=PRIMARY)
        hdr.pack(fill=X)
        ttk.Label(hdr, text="📦  Close Out the Year & Start a New One",
                  font=("Segoe UI", fs(13), "bold"),
                  bootstyle=(INVERSE, PRIMARY)).pack(pady=10, padx=16, anchor=W)

        btns = ttk.Frame(self)
        btns.pack(fill=X, side=BOTTOM, padx=16, pady=10)
        ttk.Button(btns, text="Cancel", bootstyle=(SECONDARY, OUTLINE),
                   command=self.destroy).pack(side=RIGHT, padx=4)
        ttk.Button(btns, text="✓ Finish — Start the New Year",
                   bootstyle=SUCCESS, command=self._finish).pack(side=RIGHT, padx=4)

        body = ttk.Frame(self)
        body.pack(fill=BOTH, expand=True, padx=18, pady=8)

        def step(num, title, hint=""):
            ttk.Label(body, text=f"Step {num} — {title}",
                      font=("Segoe UI", fs(10), "bold")).pack(anchor=W, pady=(10, 0))
            if hint:
                ttk.Label(body, text=hint, font=("Segoe UI", fs(8)),
                          foreground=muted_fg(), wraplength=560,
                          justify=LEFT).pack(anchor=W)

        # ── Step 1: new year ──
        step(1, "Choose the new school year")
        row = ttk.Frame(body); row.pack(anchor=W, pady=(2, 0))
        self._year_var = tk.StringVar(value=_next_school_year(current_year))
        ttk.Combobox(row, textvariable=self._year_var, width=12,
                     values=[_next_school_year(current_year), current_year]
                     ).pack(side=LEFT)
        ttk.Label(row, text=f"(you are closing out {current_year})",
                  font=("Segoe UI", fs(8)), foreground=muted_fg()
                  ).pack(side=LEFT, padx=8)

        # ── Step 2: class lists ──
        step(2, "Import this year's class lists (CSV)",
             "One CSV per class: everyone on the list is assigned to the "
             "ensemble and class period(s) you choose. Returning students "
             "are rolled into the new year automatically (keeping their "
             "instrument, contacts, and history); new names become new "
             "records. Columns just need a first/last name (or one 'Name' "
             "column); an Instrument column is used for new students. "
             "Honors / Jr. All-State marks reset — they're earned fresh "
             "each year.")
        ttk.Button(body, text="➕ Import a Class List…",
                   bootstyle=(PRIMARY, OUTLINE),
                   command=self._import_list).pack(anchor=W, pady=(4, 2))
        self._import_log = ttk.Label(body, text="No class lists imported yet "
                                                "(you can also do this later "
                                                "from Manage Students).",
                                     font=("Segoe UI", fs(8)),
                                     foreground=muted_fg(), justify=LEFT)
        self._import_log.pack(anchor=W)

        # ── Step 3: archive whoever's left ──
        step(3, "Archive the students who didn't move forward",
             "Runs when you click Finish — AFTER the imports above — so it "
             "only archives students who aren't on any new class list "
             "(graduating 8th graders, kids who dropped). Returning students "
             "are already in the new year and are not touched. Nothing is "
             "deleted; anyone can be reactivated later from Manage Students "
             "or by a later class-list import.")
        self._archive_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(body, variable=self._archive_var, bootstyle=PRIMARY,
                        text=f"Archive {current_year} students who aren't on "
                             "a new class list"
                        ).pack(anchor=W, pady=(2, 0))

        # ── Step 4: what happens next ──
        step(4, "After you finish",
             "• Teacher Tools switches to the new year — add concert and "
             "field-trip dates in the Concerts tab.\n"
             "• The Budget window has its own year selector — switch it to "
             "the new year to start the new budget.\n"
             "• Seating charts and percussion rotations start fresh for the "
             "new year; last year's stay saved under its year.")

        fit_window(self, 640, 620)

    def _import_list(self):
        year = self._year_var.get().strip()
        if not year:
            Messagebox.show_warning("Pick the new school year first.",
                                    title="No Year", parent=self)
            return
        path = filedialog.askopenfilename(
            parent=self, title="Choose a class-list CSV",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")])
        if not path:
            return
        try:
            students = read_class_csv(path)
        except Exception as e:
            Messagebox.show_error(f"Couldn't read that CSV:\n{e}",
                                  title="Import Error", parent=self)
            return
        if not students:
            Messagebox.show_warning("No student names found in that file.",
                                    title="Nothing to Import", parent=self)
            return

        dlg = _AssignDialog(self, self.base_dir, os.path.basename(path),
                            len(students))
        self.wait_window(dlg)
        if not dlg.result:
            return
        ensemble, periods = dlg.result
        added, updated = import_class_list(self.main_db, students, year,
                                           ensemble, periods)
        self._imports.append(
            f"• {os.path.basename(path)} → {ensemble or '(no ensemble)'}"
            f"{' · periods ' + ','.join(periods) if periods else ''}"
            f"  ({added} new, {updated} returning)")
        self._import_log.config(text="\n".join(self._imports),
                                foreground="#1a7a1a")

    def _finish(self):
        year = self._year_var.get().strip()
        if not year:
            Messagebox.show_warning("Pick the new school year first.",
                                    title="No Year", parent=self)
            return
        archived = 0
        if self._archive_var.get():
            archived = self.main_db.archive_school_year(self.current_year)
        # Create the new year's Teacher Tools file
        from lesson_plan_db import get_lesson_plan_db
        get_lesson_plan_db(self.base_dir, year)

        self.new_year = year
        parts = [f"Welcome to {year}!"]
        if archived:
            parts.append(f"Archived {archived} student(s) from "
                         f"{self.current_year}.")
        if self._imports:
            parts.append(f"Imported {len(self._imports)} class list(s).")
        parts.append("Teacher Tools is now on the new year — add your "
                     "concert dates in the Concerts tab, and switch the "
                     "Budget window's year selector when you're ready.")
        Messagebox.show_info("\n\n".join(parts), title="New Year Started",
                             parent=self.master)
        self.destroy()


class _AssignDialog(ttk.Toplevel):
    """Which ensemble + class period(s) a class list belongs to."""

    def __init__(self, parent, base_dir, filename, count):
        super().__init__(parent)
        self.result = None
        self.title("Assign Class List")
        self.grab_set()

        from ui.settings_dialog import load_settings
        program_type = (load_settings(base_dir).get("teacher") or {}).get(
            "program_type", "band")
        from ui.ensembles import ensembles_for, PERIOD_OPTIONS

        ttk.Label(self, text=f"📄  {filename}",
                  font=("Segoe UI", fs(11), "bold"),
                  bootstyle=PRIMARY).pack(anchor=W, padx=16, pady=(14, 0))
        ttk.Label(self, text=f"{count} student(s) found. Assign everyone on "
                             "this list to:",
                  font=("Segoe UI", fs(9))).pack(anchor=W, padx=16, pady=(2, 8))

        ttk.Label(self, text="Ensemble / class",
                  font=("Segoe UI", fs(9), "bold")).pack(anchor=W, padx=16)
        self._ens_var = tk.StringVar()
        ttk.Combobox(self, textvariable=self._ens_var,
                     values=ensembles_for(program_type),
                     width=26).pack(anchor=W, padx=16)

        ttk.Label(self, text="Class period(s)",
                  font=("Segoe UI", fs(9), "bold")).pack(anchor=W, padx=16,
                                                         pady=(10, 0))
        grid = ttk.Frame(self); grid.pack(anchor=W, padx=16)
        self._period_vars = {}
        for i, p in enumerate(PERIOD_OPTIONS):
            v = tk.BooleanVar(value=False)
            self._period_vars[p] = v
            ttk.Checkbutton(grid, text=p, variable=v, bootstyle=PRIMARY
                            ).grid(row=0, column=i, padx=(0, 10))

        btns = ttk.Frame(self)
        btns.pack(fill=X, padx=16, pady=14)
        ttk.Button(btns, text="Cancel", bootstyle=(SECONDARY, OUTLINE),
                   command=self.destroy).pack(side=RIGHT, padx=4)
        ttk.Button(btns, text="Import", bootstyle=SUCCESS,
                   command=self._ok).pack(side=RIGHT, padx=4)
        fit_window(self, 440, 260)

    def _ok(self):
        ens = self._ens_var.get().strip()
        if not ens:
            Messagebox.show_warning("Choose the ensemble/class this list "
                                    "belongs to.", title="No Ensemble",
                                    parent=self)
            return
        periods = [p for p, v in self._period_vars.items() if v.get()]
        self.result = (ens, periods)
        self.destroy()
