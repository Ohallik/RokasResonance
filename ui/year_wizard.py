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

from ui.theme import fs, muted_fg, fit_window, scroll_body


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

    def _is_id_header(h):
        """Headers that hold ID NUMBERS, never names.  'Student ID' contains
        the word 'student', which is exactly how a district export once got a
        whole class imported with ID numbers as their names."""
        words = h.replace("#", " id ").split()
        return any(w in ("id", "perm", "sis", "number", "no") for w in words)

    def find(*keys, allow_id=False):
        for i, h in enumerate(headers):
            if not allow_id and _is_id_header(h):
                continue
            if any(k in h for k in keys):
                return i
        return None

    cols = {
        "first": find("first"),
        "last": find("last"),
        "name": find("student name", "name", "student"),
        "sid": find("student id", "perm id", "id", allow_id=True),
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
                "sid": None, "instrument": None}
        data = rows
    else:
        data = rows[1:]

    out = []
    numeric_names = 0
    for row in data:
        if not any((c or "").strip() for c in row):
            continue
        row = list(row) + [""] * 6      # pad short rows
        first, last = _split_name(row, cols)
        if not (first or last):
            continue
        if f"{first}{last}".strip().replace("-", "").isdigit():
            numeric_names += 1
            continue                    # an ID number is not a student
        sid = ""
        if cols.get("sid") is not None:
            sid = (row[cols["sid"]] or "").strip()
        inst = ""
        if cols.get("instrument") is not None:
            inst = (row[cols["instrument"]] or "").strip()
        out.append({"first": first, "last": last, "instrument": inst,
                    "student_id": sid})

    # If the "names" were mostly numbers, the file's name column was never
    # found.  Importing that would fill the roster with ID-number students —
    # refuse loudly instead of quietly wrecking the year.
    if numeric_names and numeric_names >= max(1, len(out)):
        raise ValueError(
            "This file's student-name column couldn't be identified — the "
            "names parsed as ID numbers. Open the file and make sure it has "
            "a name column (e.g. 'Student Name' or 'First Name'/'Last "
            "Name'), then try again. Nothing was imported.")
    return out


def students_by_section(path):
    """For a multi-class Synergy export, group students by their Section into the
    ``{first, last, instrument}`` shape ``import_class_list`` expects.  Instruments
    come from each returning student's existing record (Synergy has none), so
    they're left blank here and carried forward by the name match."""
    import synergy_import
    out = {}
    for s in synergy_import.parse_synergy_students(path):
        rec = {"first": s.get("first_name", ""), "last": s.get("last_name", ""),
               "instrument": ""}
        for sec in (s.get("sections") or []):
            out.setdefault(sec, []).append(rec)
    return out


def import_class_list(db, students, school_year, ensemble, periods):
    """Assign every parsed student to ensemble/periods for school_year.
    Returning students (matched by name, any year) are rolled forward and
    reactivated; unknown names become new records.  Returns (added, updated)."""
    all_students = [dict(r) for r in db.get_all_students(include_inactive=True)]
    by_sid = {}
    for s in all_students:
        sid = (s.get("student_id") or "").strip()
        if sid and sid not in by_sid:
            by_sid[sid] = s

    def match(first, last, sid=""):
        # District student ID is the strongest key — names get respelled
        # between exports, IDs don't.
        if sid and sid in by_sid:
            return by_sid[sid]
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
        # Never create a "student" whose name is an ID number — the parser
        # refuses whole files of these, and this catches any stragglers.
        if f"{stu['first']}{stu['last']}".strip().replace("-", "").isdigit():
            continue
        existing = match(stu["first"], stu["last"],
                         (stu.get("student_id") or "").strip())
        if existing:
            rolled_forward = (existing.get("school_year") or "") != school_year
            data = dict(existing)
            data["school_year"] = school_year
            data["is_active"] = 1
            if rolled_forward:
                # A new year means fresh class assignments: without this, a
                # student promoted from Entry to Intermediate kept last year's
                # "Entry" tag AND gained "Intermediate" — showing up in both
                # classes' rosters, seating charts and counts.  The class-list
                # imports (this one and any later ones the same night) re-add
                # every class the student actually belongs to this year.
                data["ensembles"] = ""
                data["class_periods"] = ""
                # A new year is also a new grade level.  Only numeric grades
                # advance; "Other" and blank are left as the teacher set them.
                grade = str(data.get("grade") or "").strip()
                if grade.isdigit():
                    data["grade"] = str(int(grade) + 1)
            if stu["instrument"] and not (data.get("primary_instrument") or "").strip():
                data["primary_instrument"] = stu["instrument"]
            if (stu.get("student_id") or "").strip() and not (
                    data.get("student_id") or "").strip():
                data["student_id"] = stu["student_id"].strip()
            db.update_student(existing["id"], data)
            if rolled_forward:
                # Honors / Jr. All-State are earned fresh each year
                db.set_student_honors(existing["id"], honors=False,
                                      all_state=False)
            touched_ids.append(existing["id"])
            updated += 1
        else:
            rec = {
                "first_name": stu["first"], "last_name": stu["last"],
                "school_year": school_year,
                "primary_instrument": stu["instrument"],
                "student_id": (stu.get("student_id") or "").strip(),
            }
            new_id = db.add_student(rec)
            # Register the new student against the SAME lists match() reads, so
            # a later row for the same person updates this record instead of
            # creating another.  Class lists name a student once per section or
            # meeting day, so beginners routinely appear two or three times in
            # one file — without this, each repeat became its own record.
            rec["id"] = new_id
            rec.setdefault("preferred_name", "")
            all_students.append(rec)
            if rec["student_id"]:
                by_sid.setdefault(rec["student_id"], rec)
            touched_ids.append(new_id)
            added += 1
    # The same student can be touched more than once per file; assign each of
    # them to the ensemble/periods only once.
    touched_ids = list(dict.fromkeys(touched_ids))
    if touched_ids:
        if ensemble:
            db.bulk_set_student_multi(touched_ids, "ensembles", [ensemble])
        if periods:
            db.bulk_set_student_multi(touched_ids, "class_periods",
                                      [str(p) for p in periods])
    return added, updated


class NewSchoolYearWizard(ttk.Toplevel):
    def __init__(self, parent, main_db, base_dir, current_year):
        super().__init__(master=parent)
        self.main_db = main_db
        self.base_dir = base_dir
        self.current_year = current_year
        self.new_year = None            # set on Finish
        self._imports = []              # (filename, ensemble, added, updated)
        # Which halves of this wizard apply.  Paul Gillespie holds a high
        # school, a middle school and two elementaries, so he gets both -- and
        # an itinerant with no secondary program should not be walked through
        # class lists and uniforms that do not exist for him.
        try:
            _sites = [dict(x) for x in main_db.get_sites()]
        except Exception:
            _sites = []
        self._elem_sites = [x for x in _sites if x["level"] == "elementary"]
        self._has_secondary = (any(x["level"] != "elementary" for x in _sites)
                               or not _sites)

        self.title("New School Year")
        self.resizable(True, True)
        self.grab_set()

        hdr = ttk.Frame(self, bootstyle=PRIMARY)
        hdr.pack(fill=X)
        from ui.help_system import add_help_button
        add_help_button(hdr, "newyear")
        ttk.Label(hdr, text="📦  Close Out the Year & Start a New One",
                  font=("Segoe UI", fs(13), "bold"),
                  bootstyle=(INVERSE, PRIMARY)).pack(pady=10, padx=16, anchor=W)

        btns = ttk.Frame(self)
        btns.pack(fill=X, side=BOTTOM, padx=16, pady=10)
        ttk.Button(btns, text="Cancel", bootstyle=(SECONDARY, OUTLINE),
                   command=self.destroy).pack(side=RIGHT, padx=4)
        ttk.Button(btns, text="✓ Finish — Start the New Year",
                   bootstyle=SUCCESS, command=self._finish).pack(side=RIGHT, padx=4)

        # Scrolling, because this window grew.  A teacher with both programs
        # now gets seven steps, and on a laptop the last of them ran off the
        # bottom with no scrollbar and no sign there was anything below --
        # including, on the elementary path, the schools panel itself.
        body = scroll_body(self, padx=18, pady=8)

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

        self._n = 1

        def nstep(title, hint=""):
            self._n += 1
            step(self._n, title, hint)

        # ── Step 2: the permanent copy ──
        # The rolling backups are a two weeks's safety net and are meant to be
        # thrown away.  This is the other kind: taken once, when a year is
        # finished, and put somewhere that outlives the laptop.  Closing out
        # the year is the one moment a teacher is certain to be thinking about
        # the year as a whole, so it is asked for here.
        nstep("Save a permanent copy of " + str(current_year),
              "Students, the whole sheet music library with its performance "
              "history, agendas, seating charts, concerts and field trips — "
              "written as a folder you can open again years from now. Put it "
              "on an external drive if you have one; cloud folders are known "
              "to clear out files nobody has touched in a while.")
        arow = ttk.Frame(body); arow.pack(anchor=W, pady=(4, 0))
        ttk.Button(arow, text="💾  Save Archive Copy…", bootstyle=(INFO, OUTLINE),
                   command=self._save_archive).pack(side=LEFT)
        self._archive_music_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(arow, text="include the scanned music files (much bigger)",
                        variable=self._archive_music_var,
                        bootstyle=INFO).pack(side=LEFT, padx=(10, 0))
        self._archive_log = ttk.Label(
            body, text="Not saved yet. The library's titles, composers and "
                       "performance history are in the copy either way — the "
                       "check box is only about the scans themselves.",
            font=("Segoe UI", fs(8)), foreground=muted_fg(),
            wraplength=560, justify=LEFT)
        self._archive_log.pack(anchor=W, pady=(2, 0))
        self._archived_to = None

        if self._has_secondary:
            nstep("Import this year's class lists (CSV)",
                  "One CSV per class. Returning students are rolled in "
                  "automatically, new students become new records.")
            ttk.Button(body, text="➕ Import a Class List…",
                       bootstyle=(PRIMARY, OUTLINE),
                       command=self._import_list).pack(anchor=W, pady=(4, 2))
            self._import_log = ttk.Label(
                body, text="No class lists imported yet (you can also do this "
                           "later from Manage Students).",
                font=("Segoe UI", fs(8)), foreground=muted_fg(), justify=LEFT)
            self._import_log.pack(anchor=W)

        # 5th grade class lists are imported per school, inside that school's
        # own tab, so they are not repeated here: there is one right place to
        # do it and this is not it.
        if self._elem_sites:
            names = ", ".join(x["name"].replace(" Elementary School", "")
                              for x in self._elem_sites)
            nstep("Before you finish: send off your elementary inventories",
                  "One inventory file per school to hand on, plus one "
                  "combined repair list for the district coordinator."
                  + "\n\nSchools: " + names)
            ttk.Button(body, text="📤 Export Every School's Inventory & Repairs…",
                       bootstyle=(SUCCESS, OUTLINE),
                       command=self._export_year_end).pack(anchor=W, pady=(4, 2))
            self._export_log = ttk.Label(body, text="Nothing exported yet.",
                                         font=("Segoe UI", fs(8)),
                                         foreground=muted_fg(), justify=LEFT)
            self._export_log.pack(anchor=W)

            nstep("Later, in the autumn: your schools for the incoming year",
                  "This can wait until postings are settled; the same panel "
                  "is on Settings ▸ Schools. Archived schools can be "
                  "restored later as needed.")
            from ui.sites_view import SitesPanel
            self._sites_panel = SitesPanel(body, self.main_db)
            self._sites_panel.pack(fill=X, pady=(4, 2))

        if self._has_secondary:
            nstep("Archive the students who didn't move forward",
                  "Runs on Finish, after the imports above, so it only "
                  "archives students who aren't on a new class list. Nothing is "
                  "deleted.")
            self._archive_var = tk.BooleanVar(value=True)
            ttk.Checkbutton(body, variable=self._archive_var, bootstyle=PRIMARY,
                            text="Archive " + current_year + " students who "
                                 "aren't on a new class list"
                            ).pack(anchor=W, pady=(2, 0))

            nstep("Roll uniforms forward",
                  "Returning students keep their pieces. This only releases "
                  "gear held by students who didn't return.")
            self._release_uniforms_var = tk.BooleanVar(value=True)
            ttk.Checkbutton(body, variable=self._release_uniforms_var,
                            bootstyle=PRIMARY,
                            text="Release uniforms held by students who didn't "
                                 "return").pack(anchor=W, pady=(2, 0))
        else:
            # No checkbox, and no uniforms.  Every 5th grader leaves for middle
            # school at the end of every year, without exception, so archiving
            # them is not a decision to put to anybody -- and an itinerant has
            # no uniform closet to roll forward.
            self._archive_var = tk.BooleanVar(value=True)
            self._release_uniforms_var = tk.BooleanVar(value=False)
            nstep("Last year's children",
                  "Your 5th graders have all moved on, so they are archived "
                  "when you finish. Nothing is deleted.")

        # Both really do move now, so this says so instead of sending the
        # teacher off to change a dropdown in another window.
        after = ["Teacher Tools and Budget are now in the new school year."]
        after.append("Continue to add schools or class sections as needed."
                     if self._elem_sites else
                     "Continue to add class lists as needed.")
        if self._has_secondary:
            after.append("Seating charts and rotations are fresh for the new year.")
        nstep("After you finish", "  ".join(after))

        fit_window(self, 640, 620)

    def _export_year_end(self):
        """Every school's inventory and open repairs, in one folder."""
        from tkinter import filedialog
        import site_export as SE

        folder = filedialog.askdirectory(
            parent=self, title="Where should the coordinator's files go?")
        if not folder:
            return
        try:
            res = SE.export_year_end_pack(self.main_db, self._elem_sites, folder)
        except ImportError:
            Messagebox.show_error(
                "Writing a spreadsheet needs openpyxl:  pip install openpyxl",
                title="Missing Dependency", parent=self)
            return
        except Exception as e:
            Messagebox.show_error(f"Could not write the files:\n{e}",
                                  title="Export failed", parent=self)
            return

        n = len(res["written"])
        msg = (f"{n} file(s) for {res['schools']} school(s) written to:\n"
               f"{folder}")
        if res["failed"]:
            msg += ("\n\nThese could not be written: "
                    + ", ".join(f"{name} ({kind})"
                                for name, kind, _e in res["failed"]))
        Messagebox.show_info(msg, title="Exported", parent=self)
        self._export_log.config(
            text=f"{n} file(s) written to {folder}"
                 + (f"  ({len(res['failed'])} failed)" if res["failed"] else ""))
        try:
            import os
            os.startfile(folder)
        except Exception:
            pass

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
        # A combined Synergy export (co-directors' shared rosters) has more than
        # one class in it — map each section to an ensemble instead of dumping
        # everyone into one, same as the first-time import wizard.
        try:
            import synergy_import
            secs = synergy_import.summarize_sections(path)
        except Exception:
            secs = []
        if len(secs) > 1:
            self._import_sectioned(path, year, secs)
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

    def _import_sectioned(self, path, year, secs):
        """Roll forward a multi-class file: map each section to an ensemble, then
        route each section's students through the returning-student carry-forward."""
        dlg = _SectionAssignDialog(self, self.base_dir, os.path.basename(path), secs)
        self.wait_window(dlg)
        if not dlg.result:
            return
        section_map, periods = dlg.result
        by_sec = students_by_section(path)
        bits, total_new, total_ret = [], 0, 0
        for sec, ens in section_map.items():
            if not ens:
                continue
            studs = by_sec.get(sec, [])
            if not studs:
                continue
            a, u = import_class_list(self.main_db, studs, year, ens, periods)
            total_new += a
            total_ret += u
            bits.append(f"{ens}: {a} new, {u} returning")
        if not bits:
            return
        self._imports.append(f"• {os.path.basename(path)} → " + "; ".join(bits))
        self._import_log.config(text="\n".join(self._imports),
                                foreground="#1a7a1a")

    def _save_archive(self):
        """Write the year's permanent copy wherever they say."""
        dest = filedialog.askdirectory(
            parent=self,
            title="Where should the %s archive go?" % self.current_year,
            mustexist=True)
        if not dest:
            return
        profile = os.path.basename(os.path.normpath(self.base_dir))
        self._archive_log.config(text="Saving…", foreground=muted_fg())
        self.update_idletasks()

        def say(msg):
            self._archive_log.config(text=msg)
            self.update_idletasks()

        try:
            out = self.main_db.archive_year(
                dest, self.current_year, profile,
                include_sheet_music=bool(self._archive_music_var.get()),
                progress=say)
        except Exception as e:
            self._archive_log.config(
                text="Could not save the archive: %s" % e, foreground="#c0392b")
            return
        self._archived_to = out
        size = 0
        for root, _dirs, files in os.walk(out):
            for f in files:
                try:
                    size += os.path.getsize(os.path.join(root, f))
                except OSError:
                    pass
        self._archive_log.config(
            text="Saved %.0f MB to %s  —  there is a READ ME FIRST inside "
                 "explaining how to open it again." % (size / 1048576.0, out),
            foreground="#1e7e34")

    def _finish(self):
        year = self._year_var.get().strip()
        if not year:
            Messagebox.show_warning("Pick the new school year first.",
                                    title="No Year", parent=self)
            return
        archived = 0
        if self._has_secondary and self._archive_var.get():
            archived += self.main_db.archive_school_year(
                self.current_year, level="secondary")
        if self._elem_sites or not self._has_secondary:
            # Always, and without asking.  See the step text above.
            archived += self.main_db.archive_school_year(
                self.current_year, level="elementary")
        # Release uniforms held by students who didn't return (now inactive after
        # archiving).  Returning students keep theirs untouched.
        released = 0
        if self._has_secondary and self._release_uniforms_var.get():
            from datetime import datetime as _dt
            try:
                released = self.main_db.checkin_uniforms_for_inactive_students(
                    _dt.today().strftime("%Y-%m-%d"))
            except Exception:
                released = 0
        # Create the new year's Teacher Tools file
        from lesson_plan_db import get_lesson_plan_db
        get_lesson_plan_db(self.base_dir, year)

        # Record which year the teacher is now working in, so the Budget window
        # opens on it too.  It used to open on the most recent year with any
        # activity, which right after a rollover is LAST year -- and the wizard
        # papered over that by telling them to go and change a dropdown.
        try:
            from ui.settings_dialog import load_settings, save_settings
            cfg = load_settings(self.base_dir) or {}
            cfg.setdefault("teacher", {})["active_school_year"] = year
            save_settings(self.base_dir, cfg)
        except Exception:
            pass

        self.new_year = year
        parts = [f"Welcome to {year}!"]
        if archived:
            parts.append(f"Archived {archived} student(s) from "
                         f"{self.current_year}.")
        if released:
            parts.append(f"Released {released} uniform piece(s) from students "
                         f"who didn't return.")
        if self._imports:
            parts.append(f"Imported {len(self._imports)} class list(s).")
        if self._archived_to:
            parts.append(f"A permanent copy of {self.current_year} is at "
                         f"{self._archived_to}.")
        else:
            parts.append(f"You did not save a permanent copy of "
                         f"{self.current_year}. The rolling backups only go "
                         f"back a two weeks — you can still make one from "
                         f"New School Year, or Settings \u2192 Backup.")
        parts.append("Teacher Tools is now on the new year — add your "
                     "concert dates in the Concerts tab, and switch the "
                     "Budget window's year selector when you're ready.")
        Messagebox.show_info("\n\n".join(parts), title="New Year Started",
                             parent=self.master)
        self.destroy()


class _AssignDialog(ttk.Toplevel):
    """Which ensemble + class period(s) a class list belongs to."""

    def __init__(self, parent, base_dir, filename, count):
        super().__init__(master=parent)
        self.result = None
        self.title("Assign Class List")
        self.grab_set()

        from ui.settings_dialog import load_settings
        program_type = (load_settings(base_dir).get("teacher") or {}).get(
            "program_type", "band")
        from ui.ensembles import all_class_options, PERIOD_OPTIONS
        classes = all_class_options(getattr(parent, "main_db", None), base_dir,
                                    program_type,
                                    getattr(parent, "current_year", None))

        ttk.Label(self, text=f"📄  {filename}",
                  font=("Segoe UI", fs(11), "bold"),
                  bootstyle=PRIMARY).pack(anchor=W, padx=16, pady=(14, 0))
        ttk.Label(self, text=f"{count} student(s) found. Assign everyone on "
                             "this list to:",
                  font=("Segoe UI", fs(9))).pack(anchor=W, padx=16, pady=(2, 8))

        ttk.Label(self, text="Ensemble / class",
                  font=("Segoe UI", fs(9), "bold")).pack(anchor=W, padx=16)
        self._ens_var = tk.StringVar()
        # Typeable: the list is everything Roka knows about, not a claim to
        # know every class that exists.
        ttk.Combobox(self, textvariable=self._ens_var, values=classes,
                     width=30).pack(anchor=W, padx=16)

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


class _SectionAssignDialog(ttk.Toplevel):
    """Map each class SECTION in a combined roster to an ensemble (or skip),
    then optionally tag a shared class period.  Returns
    ``({section: ensemble}, [periods])``."""

    def __init__(self, parent, base_dir, filename, secs):
        super().__init__(master=parent)
        self.result = None
        self.title("Map Class Sections")
        self.grab_set()

        from ui.settings_dialog import load_settings
        program_type = (load_settings(base_dir).get("teacher") or {}).get(
            "program_type", "band")
        from ui.ensembles import all_class_options, PERIOD_OPTIONS
        opts = ["— skip —"] + all_class_options(
            getattr(parent, "main_db", None), base_dir, program_type,
            getattr(parent, "current_year", None))

        ttk.Label(self, text=f"📄  {filename}", font=("Segoe UI", fs(11), "bold"),
                  bootstyle=PRIMARY).pack(anchor=W, padx=16, pady=(14, 0))
        ttk.Label(self, text="This file has more than one class in it. Choose "
                             "which ensemble each section rolls into — or skip one "
                             "you don't want.",
                  font=("Segoe UI", fs(9)), wraplength=460, justify=LEFT).pack(
            anchor=W, padx=16, pady=(2, 8))

        self._pickers = {}
        # Pinned buttons + period picker at the bottom, scrollable section list
        # above — robust for a file with many sections (Edd has one with six).
        btns = ttk.Frame(self)
        btns.pack(side=BOTTOM, fill=X, padx=16, pady=14)
        ttk.Button(btns, text="Cancel", bootstyle=(SECONDARY, OUTLINE),
                   command=self.destroy).pack(side=RIGHT, padx=4)
        ttk.Button(btns, text="Import", bootstyle=SUCCESS,
                   command=self._ok).pack(side=RIGHT, padx=4)
        pf = ttk.Frame(self)
        pf.pack(side=BOTTOM, fill=X, padx=16, pady=(0, 4))
        ttk.Label(pf, text="Class period(s) — optional",
                  font=("Segoe UI", fs(9), "bold")).pack(anchor=W)
        grid = ttk.Frame(pf)
        grid.pack(anchor=W)
        self._period_vars = {}
        for i, p in enumerate(PERIOD_OPTIONS):
            vv = tk.BooleanVar(value=False)
            self._period_vars[p] = vv
            ttk.Checkbutton(grid, text=p, variable=vv, bootstyle=PRIMARY
                            ).grid(row=0, column=i, padx=(0, 8))

        outer = ttk.Frame(self)
        outer.pack(fill=BOTH, expand=True)
        cv = tk.Canvas(outer, highlightthickness=0)
        sb = ttk.Scrollbar(outer, orient=VERTICAL, command=cv.yview)
        cv.configure(yscrollcommand=sb.set)
        sb.pack(side=RIGHT, fill=Y)
        cv.pack(side=LEFT, fill=BOTH, expand=True)
        body = ttk.Frame(cv, padding=(16, 0))
        win = cv.create_window((0, 0), window=body, anchor="nw")
        body.bind("<Configure>", lambda e: cv.configure(scrollregion=cv.bbox("all")))
        cv.bind("<Configure>", lambda e: cv.itemconfig(win, width=e.width))
        cv.bind("<Enter>", lambda e: cv.bind_all(
            "<MouseWheel>", lambda ev: cv.yview_scroll(int(-ev.delta / 120), "units")))
        cv.bind("<Leave>", lambda e: cv.unbind_all("<MouseWheel>"))
        for s in secs:
            r = ttk.Frame(body)
            r.pack(fill=X, pady=3)
            who = s["teacher"] or s["section"]
            ttk.Label(r, text=f"{who}  ({s['count']} students)",
                      width=32).pack(side=LEFT)
            v = tk.StringVar(value="— skip —")
            ttk.Combobox(r, textvariable=v, state="readonly", width=24,
                         values=opts).pack(side=LEFT)
            self._pickers[s["section"]] = v

        fit_window(self, 500, min(280 + 30 * len(secs), 560))

    def _ok(self):
        section_map = {sec: ("" if v.get() == "— skip —" else v.get())
                       for sec, v in self._pickers.items()}
        if not any(section_map.values()):
            Messagebox.show_warning("Map at least one section to an ensemble.",
                                    title="Nothing mapped", parent=self)
            return
        periods = [p for p, v in self._period_vars.items() if v.get()]
        self.result = (section_map, periods)
        self.destroy()
