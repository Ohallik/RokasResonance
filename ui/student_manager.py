"""
ui/student_manager.py - Student management by school year
"""

import csv
import os
import re
import tkinter as tk
from tkinter import filedialog
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from ttkbootstrap.dialogs import Messagebox
from datetime import datetime


def _current_school_year() -> str:
    today = datetime.today()
    if today.month >= 8:
        return f"{today.year}-{today.year + 1}"
    return f"{today.year - 1}-{today.year}"


def _next_school_year() -> str:
    today = datetime.today()
    if today.month >= 8:
        return f"{today.year + 1}-{today.year + 2}"
    return f"{today.year}-{today.year + 1}"


GRADE_OPTIONS = ["5", "6", "7", "8", "9", "10", "11", "12", "Other"]
GENDER_OPTIONS = ["", "Male", "Female", "Non-binary", "Prefer not to say"]
RELATION_OPTIONS = ["", "Parent", "Guardian", "Grandparent", "Step-parent", "Other"]


class StudentManager(ttk.Frame):
    def __init__(self, parent, db):
        super().__init__(parent)
        self.db = db
        self._year_var = tk.StringVar()
        self._search_var = tk.StringVar()
        self._selected_id = None

        self._build()
        self._populate_year_options()
        self.refresh()

    def _build(self):
        # ── Toolbar ───────────────────────────────────────────────────────────
        toolbar = ttk.Frame(self, bootstyle=LIGHT)
        toolbar.pack(fill=X)

        ttk.Button(toolbar, text="➕ Add Student", bootstyle=SUCCESS,
                   command=self._add_student).pack(side=LEFT, padx=6, pady=6)
        ttk.Button(toolbar, text="✏️ Edit", bootstyle=PRIMARY,
                   command=self._edit_student).pack(side=LEFT, padx=2, pady=6)
        ttk.Button(toolbar, text="🗑️ Delete", bootstyle=DANGER,
                   command=self._delete_student).pack(side=LEFT, padx=2, pady=6)
        ttk.Button(toolbar, text="📂 Import CSV", bootstyle=INFO,
                   command=self._import_csv).pack(side=LEFT, padx=6, pady=6)
        ttk.Button(toolbar, text="🔄 Refresh", bootstyle=(SECONDARY, OUTLINE),
                   command=self.refresh).pack(side=LEFT, padx=6, pady=6)

        ttk.Separator(toolbar, orient=VERTICAL).pack(side=LEFT, fill=Y, padx=8, pady=4)

        ttk.Label(toolbar, text="School Year:").pack(side=LEFT, padx=(0, 4))
        years_combo = ttk.Combobox(toolbar, textvariable=self._year_var,
                                    state="readonly", width=14)
        years_combo.pack(side=LEFT, padx=(0, 10))
        years_combo.bind("<<ComboboxSelected>>", lambda e: self.refresh())
        self._years_combo = years_combo

        ttk.Label(toolbar, text="Search:").pack(side=LEFT, padx=(0, 4))
        ttk.Entry(toolbar, textvariable=self._search_var, width=22).pack(side=LEFT)
        self._search_var.trace_add("write", lambda *_: self._apply_filter())

        self._count_lbl = ttk.Label(toolbar, text="", foreground="#666")
        self._count_lbl.pack(side=RIGHT, padx=10)

        # ── Content: Tree + Detail ─────────────────────────────────────────────
        paned = ttk.Panedwindow(self, orient=HORIZONTAL)
        paned.pack(fill=BOTH, expand=True, padx=6, pady=6)

        # Left: student list
        list_frame = ttk.Frame(paned)
        paned.add(list_frame, weight=2)

        cols = ("Name", "Grade", "Phone", "Parent", "Active Instruments")
        sb = ttk.Scrollbar(list_frame, orient=VERTICAL)
        self.tree = ttk.Treeview(list_frame, columns=cols, show="headings",
                                  yscrollcommand=sb.set, selectmode="browse",
                                  bootstyle=PRIMARY)
        sb.config(command=self.tree.yview)
        sb.pack(side=RIGHT, fill=Y)
        self.tree.pack(fill=BOTH, expand=True)

        widths = [180, 60, 110, 160, 120]
        _stretch = {"Name", "Parent"}
        for col, w in zip(cols, widths):
            self.tree.heading(col, text=col, anchor=W,
                              command=lambda c=col: self._sort_by(c))
            self.tree.column(col, width=w, anchor=W, stretch=col in _stretch)

        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.bind("<Double-1>", lambda e: self._edit_student())

        # Right: detail panel
        detail_frame = ttk.Frame(paned, width=300)
        paned.add(detail_frame, weight=1)
        self._build_detail(detail_frame)

        self._sort_col = "Name"
        self._sort_asc = True
        self._all_students = []

    def _build_detail(self, parent):
        nb = ttk.Notebook(parent, bootstyle=PRIMARY)
        nb.pack(fill=BOTH, expand=True)

        info_tab = ttk.Frame(nb)
        checkout_tab = ttk.Frame(nb)
        nb.add(info_tab, text="Student Info")
        nb.add(checkout_tab, text="Instrument History")

        # ── Info tab ──────────────────────────────────────────────────────────
        outer = ttk.Frame(info_tab)
        outer.pack(fill=BOTH, expand=True, padx=8, pady=8)

        self._detail_labels = {}
        fields = [
            ("Name", "_full_name"),
            ("Grade", "grade"),
            ("School Year", "school_year"),
            ("Gender", "gender"),
            ("Student ID", "student_id"),
            ("Phone", "phone"),
            ("Email", "student_email"),
            ("Address", "_address"),
            ("Parent 1", "parent1_name"),
            ("P1 Phone", "parent1_phone"),
            ("P1 Email", "parent1_email"),
            ("Parent 2", "parent2_name"),
            ("P2 Phone", "parent2_phone"),
            ("P2 Email", "parent2_email"),
            ("Notes", "notes"),
        ]
        for label, key in fields:
            r = ttk.Frame(outer)
            r.pack(fill=X, pady=1)
            ttk.Label(r, text=f"{label}:", font=("Segoe UI", 8, "bold"),
                      width=12, anchor=W).pack(side=LEFT)
            lbl = ttk.Label(r, text="", font=("Segoe UI", 8),
                             anchor=W, wraplength=180, justify=LEFT)
            lbl.pack(side=LEFT, fill=X, expand=True)
            self._detail_labels[key] = lbl

        # ── Checkout history tab ───────────────────────────────────────────────
        hist_frame = ttk.Frame(checkout_tab)
        hist_frame.pack(fill=BOTH, expand=True)

        cols_h = ("Instrument", "Date Out", "Date In")
        sb_h = ttk.Scrollbar(hist_frame, orient=VERTICAL)
        self._hist_tree = ttk.Treeview(hist_frame, columns=cols_h, show="headings",
                                        yscrollcommand=sb_h.set, bootstyle=INFO)
        sb_h.config(command=self._hist_tree.yview)
        sb_h.pack(side=RIGHT, fill=Y)
        self._hist_tree.pack(fill=BOTH, expand=True)

        for col in cols_h:
            self._hist_tree.heading(col, text=col)
            self._hist_tree.column(col, width=100, anchor=W)

    # ─────────────────────────────────────────────────────────── Data Loading ─

    def _populate_year_options(self):
        years = self.db.get_school_years()
        cur = _current_school_year()
        nxt = _next_school_year()
        # Ensure both current and next year are always available
        for y in (nxt, cur):
            if y not in years:
                years.insert(0, y)
        self._years_combo["values"] = years
        # Default to current school year (not necessarily years[0])
        if not self._year_var.get():
            self._year_var.set(cur)

    def refresh(self):
        year = self._year_var.get() or None
        self._all_students = list(self.db.get_all_students(school_year=year))
        self._apply_filter()
        self._populate_year_options()

    def _apply_filter(self):
        search = self._search_var.get().lower()
        visible = []
        for s in self._all_students:
            if search:
                haystack = " ".join([
                    str(s["first_name"] or ""),
                    str(s["last_name"] or ""),
                    str(s["phone"] or ""),
                    str(s["parent1_name"] or ""),
                    str(s["student_id"] or ""),
                ]).lower()
                if search not in haystack:
                    continue
            visible.append(s)

        self._populate_tree(visible)
        self._count_lbl.config(text=f"{len(visible)} student(s)")

    def _populate_tree(self, students):
        col_key_map = {
            "Name": "_sort_name",
            "Grade": "grade",
            "Phone": "phone",
            "Parent": "parent1_name",
            "Active Instruments": "_active_count",
        }
        key = col_key_map.get(self._sort_col, "_sort_name")

        # Get active checkout counts
        active_checkouts = {}
        for s in students:
            with self.db._connect() as conn:
                count = conn.execute(
                    "SELECT COUNT(*) FROM checkouts WHERE student_id=? AND date_returned IS NULL",
                    (s["id"],)
                ).fetchone()[0]
            active_checkouts[s["id"]] = count

        def sort_key(s):
            if key == "_sort_name":
                return (s["last_name"] or "").lower()
            if key == "_active_count":
                return active_checkouts.get(s["id"], 0)
            return (s[key] or "").lower() if isinstance(s[key], str) else (s[key] or 0)

        students = sorted(students, key=sort_key, reverse=not self._sort_asc)

        self.tree.delete(*self.tree.get_children())
        for s in students:
            full_name = f"{s['last_name']}, {s['first_name']}".strip(", ")
            active = active_checkouts.get(s["id"], 0)
            active_str = f"✓ {active}" if active > 0 else ""
            iid = str(s["id"])
            self.tree.insert("", "end", iid=iid, values=(
                full_name,
                s["grade"] or "",
                s["phone"] or "",
                s["parent1_name"] or "",
                active_str,
            ))

    def _sort_by(self, col):
        if self._sort_col == col:
            self._sort_asc = not self._sort_asc
        else:
            self._sort_col = col
            self._sort_asc = True
        self._apply_filter()

    def _on_select(self, event=None):
        sel = self.tree.selection()
        if not sel:
            return
        self._selected_id = int(sel[0])
        self._load_detail(self._selected_id)

    def _load_detail(self, student_id: int):
        student = self.db.get_student(student_id)
        if not student:
            return

        row = dict(student)
        row["_full_name"] = f"{row.get('first_name', '')} {row.get('last_name', '')}".strip()
        addr_parts = [row.get("address", ""), row.get("city", ""),
                      row.get("state", ""), row.get("zip_code", "")]
        row["_address"] = ", ".join(p for p in addr_parts if p)

        for key, lbl in self._detail_labels.items():
            val = row.get(key, "")
            lbl.config(text=str(val) if val else "")

        # Load checkout history
        self._hist_tree.delete(*self._hist_tree.get_children())
        with self.db._connect() as conn:
            history = conn.execute(
                """SELECT c.date_assigned, c.date_returned, i.description
                   FROM checkouts c
                   JOIN instruments i ON i.id=c.instrument_id
                   WHERE c.student_id=?
                   ORDER BY c.date_assigned DESC""",
                (student_id,)
            ).fetchall()
        for h in history:
            self._hist_tree.insert("", "end", values=(
                h["description"] or "",
                h["date_assigned"] or "",
                h["date_returned"] or "Active",
            ))

    # ─────────────────────────────────────────────────────────── Actions ──────

    def _get_selected(self):
        sel = self.tree.selection()
        if not sel:
            Messagebox.show_warning("Please select a student first.", title="No Selection")
            return None
        return int(sel[0])

    def _import_csv(self):
        paths = filedialog.askopenfilenames(
            title="Select Student Roster CSV Files (up to 10)",
            filetypes=[("CSV files", "*.csv *.CSV"), ("All files", "*.*")],
            parent=self.winfo_toplevel(),
        )
        if not paths:
            return
        if len(paths) > 10:
            Messagebox.show_warning(
                "Please select at most 10 files at a time.",
                title="Too Many Files"
            )
            return
        school_year = self._year_var.get() or _current_school_year()
        dlg = _StudentImportDialog(
            self.winfo_toplevel(), self.db, list(paths), school_year
        )
        self.wait_window(dlg)
        self.refresh()

    def _add_student(self):
        dlg = StudentDialog(self.winfo_toplevel(), self.db,
                             student_id=None,
                             default_year=self._year_var.get())
        self.wait_window(dlg)
        self.refresh()

    def _edit_student(self):
        sid = self._get_selected()
        if sid is None:
            return
        dlg = StudentDialog(self.winfo_toplevel(), self.db,
                             student_id=sid,
                             default_year=self._year_var.get())
        self.wait_window(dlg)
        self.refresh()
        self._load_detail(sid)

    def _delete_student(self):
        sid = self._get_selected()
        if sid is None:
            return
        student = self.db.get_student(sid)
        if not student:
            return
        name = f"{student['first_name']} {student['last_name']}".strip()

        # Block deletion if student has active checkouts
        active = self.db.get_student_active_checkout_count(sid)
        if active > 0:
            Messagebox.show_warning(
                f"{name} currently has {active} instrument(s) checked out.\n\n"
                f"Please check in all instruments before deleting this student.",
                title="Cannot Delete"
            )
            return

        # Confirm deletion
        answer = Messagebox.yesno(
            f"Are you sure you want to delete {name}?\n\n"
            f"This will remove them from the student list.",
            title="Confirm Delete"
        )
        if answer != "Yes":
            return

        self.db.deactivate_student(sid)
        self._selected_id = None
        self.refresh()


# ── CSV roster parser ─────────────────────────────────────────────────────────

# Column indices (positional — avoids issues with duplicate header names in
# the district CSV export, which has two "Phone" and two "ParentEmail" cols).
_COL_SID      = 0   # Student ID
_COL_NAME     = 1   # Student Name  (Last, First)
_COL_GRADE    = 2   # Grd
_COL_GENDER   = 3   # Gen
_COL_BDATE    = 4   # Birth Date
_COL_PNAME    = 5   # Parent Name
_COL_PEMAIL   = 8   # ParentEmail   (first occurrence)
_COL_PHONE    = 9   # Phone         (first occurrence — main contact phone)
_COL_RELATION = 11  # Relation
_COL_ORDERBY  = 17  # Orderby (1 = primary contact, 2 = secondary, …)
_COL_SEMAIL   = 21  # Student Email
_COL_ADDRESS  = 22  # Street Address
_COL_CSZ      = 23  # CityStateZip  e.g. "BELLEVUE, WA 98004"

_CSZ_RE = re.compile(r'^(.*?),\s*([A-Z]{2})\s+(\d{5}(?:-\d{4})?)$')


def _parse_csz(csz: str):
    """'BELLEVUE, WA 98004' → ('Bellevue', 'WA', '98004')"""
    m = _CSZ_RE.match((csz or "").strip())
    if m:
        return m.group(1).strip().title(), m.group(2), m.group(3)
    return (csz or "").strip(), "", ""


def _split_name(name: str):
    """'Last, First Middle' → (first, last)"""
    name = (name or "").strip()
    if "," in name:
        last, first = name.split(",", 1)
        return first.strip(), last.strip()
    parts = name.split()
    return (parts[0] if parts else ""), (" ".join(parts[1:]) if len(parts) > 1 else "")


def _normalize_date(d: str) -> str:
    if not d:
        return ""
    try:
        return datetime.strptime(d.strip(), "%m/%d/%Y").strftime("%Y-%m-%d")
    except ValueError:
        return d.strip()


def _parse_student_csvs(paths: list) -> dict:
    """
    Parse one or more school district roster CSV files.

    Each file may have multiple rows per student (one per parent/guardian).
    Students are deduplicated by Student ID across all files.

    Returns a dict  {student_id_or_name: student_data_dict}  ready for
    db.add_student().
    """
    students = {}   # keyed by student_id (or raw name as fallback)

    for path in paths:
        with open(path, encoding="utf-8-sig", errors="replace", newline="") as f:
            reader = csv.reader(f)
            next(reader, None)   # skip header row
            for row in reader:
                if len(row) <= _COL_CSZ:
                    continue

                sid     = row[_COL_SID].strip()
                name    = row[_COL_NAME].strip()
                grade   = row[_COL_GRADE].strip().lstrip("0") or "0"
                gender  = {"M": "Male", "F": "Female"}.get(
                              row[_COL_GENDER].strip(), "")
                bdate   = _normalize_date(row[_COL_BDATE])
                p_name  = row[_COL_PNAME].strip()
                p_email = row[_COL_PEMAIL].strip()
                p_phone = row[_COL_PHONE].strip()
                p_rel   = row[_COL_RELATION].strip()
                orderby = row[_COL_ORDERBY].strip() or "1"
                s_email = row[_COL_SEMAIL].strip()
                address = row[_COL_ADDRESS].strip()
                csz     = row[_COL_CSZ].strip()

                key = sid if sid else name
                if not key:
                    continue

                # First time we see this student — create the base record
                if key not in students:
                    first, last = _split_name(name)
                    city, state, zip_code = _parse_csz(csz)
                    students[key] = {
                        "student_id":    sid,
                        "first_name":    first,
                        "last_name":     last,
                        "grade":         grade,
                        "gender":        gender,
                        "birth_date":    bdate,
                        "student_email": s_email,
                        "address":       address,
                        "city":          city,
                        "state":         state,
                        "zip_code":      zip_code,
                        "_parents":      {},
                    }

                # Accumulate parent contacts keyed by Orderby value.
                # Only keep the first occurrence of each Orderby number.
                if p_name and orderby not in students[key]["_parents"]:
                    students[key]["_parents"][orderby] = {
                        "name":     p_name,
                        "phone":    p_phone,
                        "email":    p_email,
                        "relation": p_rel,
                    }

    # Flatten parent dicts into parent1 / parent2 fields
    result = {}
    for key, s in students.items():
        parents = s.pop("_parents")
        sorted_keys = sorted(parents.keys())
        p1 = parents.get(sorted_keys[0], {}) if sorted_keys else {}
        p2 = parents.get(sorted_keys[1], {}) if len(sorted_keys) > 1 else {}

        s["parent1_name"]     = p1.get("name", "")
        s["parent1_phone"]    = p1.get("phone", "")
        s["parent1_email"]    = p1.get("email", "")
        s["parent1_relation"] = p1.get("relation", "")
        s["parent2_name"]     = p2.get("name", "")
        s["parent2_phone"]    = p2.get("phone", "")
        s["parent2_email"]    = p2.get("email", "")
        s["parent2_relation"] = p2.get("relation", "")
        # Use primary parent phone as the student's main contact phone
        s["phone"] = p1.get("phone", "") or p2.get("phone", "")

        result[key] = s

    return result


# ── Import progress dialog ────────────────────────────────────────────────────

class _StudentImportDialog(ttk.Toplevel):
    """Shows import progress and results for a CSV roster import."""

    def __init__(self, parent, db, paths: list, school_year: str):
        super().__init__(parent)
        self.db          = db
        self.paths       = paths
        self.school_year = school_year

        self.title("Import Student Roster")
        self.geometry("520x400")
        self.resizable(False, False)
        self.grab_set()

        self.update_idletasks()
        x = (self.winfo_screenwidth()  - 520) // 2
        y = (self.winfo_screenheight() - 400) // 2
        self.geometry(f"+{x}+{y}")

        self._build()
        self.after(100, self._run_import)

    def _build(self):
        ttk.Label(
            self,
            text=f"Importing students for {self.school_year}",
            font=("Segoe UI", 11, "bold"),
            bootstyle=PRIMARY,
        ).pack(pady=(16, 6), padx=16, anchor=W)

        self._progress = ttk.Progressbar(self, mode="indeterminate", bootstyle=PRIMARY)
        self._progress.pack(fill=X, padx=20, pady=4)
        self._progress.start(10)

        log_frame = ttk.Frame(self)
        log_frame.pack(fill=BOTH, expand=True, padx=16, pady=8)

        self._log = tk.Text(
            log_frame, height=14, font=("Consolas", 9),
            state="disabled", relief="flat", bd=1, bg="#F8F8F8",
        )
        sb = ttk.Scrollbar(log_frame, orient=VERTICAL, command=self._log.yview)
        self._log.configure(yscrollcommand=sb.set)
        sb.pack(side=RIGHT, fill=Y)
        self._log.pack(fill=BOTH, expand=True)

        self._close_btn = ttk.Button(
            self, text="Close", bootstyle=PRIMARY,
            state="disabled", command=self.destroy,
        )
        self._close_btn.pack(pady=(0, 12))

    def _log_msg(self, msg: str):
        self._log.config(state="normal")
        self._log.insert("end", msg + "\n")
        self._log.see("end")
        self._log.config(state="disabled")
        self.update()

    def _run_import(self):
        try:
            # ── Parse files ───────────────────────────────────────────────
            for i, path in enumerate(self.paths, 1):
                self._log_msg(
                    f"Reading file {i}/{len(self.paths)}: {os.path.basename(path)}"
                )

            students = _parse_student_csvs(self.paths)
            self._log_msg(
                f"\nFound {len(students)} unique student(s) across "
                f"{len(self.paths)} file(s)."
            )
            self._log_msg(f"Importing into school year: {self.school_year}\n")

            # ── Import with deduplication ─────────────────────────────────
            imported = 0
            skipped  = 0

            for data in students.values():
                data["school_year"] = self.school_year

                # Primary dedup key: student_id + school_year
                existing = None
                if data.get("student_id"):
                    with self.db._connect() as conn:
                        existing = conn.execute(
                            "SELECT id FROM students "
                            "WHERE student_id=? AND school_year=?",
                            (data["student_id"], self.school_year),
                        ).fetchone()

                # Fallback dedup: exact first+last name match
                if not existing:
                    existing = self.db.find_student_by_name(
                        data.get("first_name", ""),
                        data.get("last_name", ""),
                        self.school_year,
                    )

                if existing:
                    skipped += 1
                else:
                    self.db.add_student(data)
                    imported += 1

            # ── Summary ───────────────────────────────────────────────────
            self._log_msg("─" * 42)
            self._log_msg(f"Import complete!")
            self._log_msg(f"  Imported : {imported} student(s)")
            self._log_msg(
                f"  Skipped  : {skipped} "
                f"(already in system for {self.school_year})"
            )

        except Exception as e:
            self._log_msg(f"\nError: {e}")
        finally:
            self._progress.stop()
            self._close_btn.config(state="normal")


class StudentDialog(ttk.Toplevel):
    def __init__(self, parent, db, student_id=None, default_year=None):
        super().__init__(parent)
        self.db = db
        self.student_id = student_id
        self.default_year = default_year or _current_school_year()

        self.title("Edit Student" if student_id else "Add Student")
        self.geometry("620x680")
        self.resizable(True, True)
        self.grab_set()

        self.update_idletasks()
        x = (self.winfo_screenwidth() - 620) // 2
        y = (self.winfo_screenheight() - 680) // 2
        self.geometry(f"+{x}+{y}")

        self._vars = {}
        self._build()
        if student_id:
            self._load(student_id)

    def _build(self):
        hdr = ttk.Frame(self, bootstyle=PRIMARY)
        hdr.pack(fill=X)
        title = "Edit Student" if self.student_id else "Add Student"
        ttk.Label(hdr, text=title, font=("Segoe UI", 13, "bold"),
                  bootstyle=(INVERSE, PRIMARY)).pack(pady=12, padx=16, anchor=W)

        # Scrollable body
        canvas = tk.Canvas(self, highlightthickness=0)
        sb = ttk.Scrollbar(self, orient=VERTICAL, command=canvas.yview)
        canvas.configure(yscrollcommand=sb.set)
        sb.pack(side=RIGHT, fill=Y)
        canvas.pack(fill=BOTH, expand=True)

        content = ttk.Frame(canvas)
        cw = canvas.create_window((0, 0), window=content, anchor=NW)

        def _resize(event):
            canvas.configure(scrollregion=canvas.bbox("all"))
            canvas.itemconfig(cw, width=canvas.winfo_width())

        content.bind("<Configure>", _resize)
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(cw, width=e.width))

        def _wheel(event):
            try:
                canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
            except tk.TclError:
                canvas.unbind_all("<MouseWheel>")
        canvas.bind_all("<MouseWheel>", _wheel)
        self.bind("<Destroy>", lambda e: canvas.unbind_all("<MouseWheel>"))

        self._build_form(content)

        btn = ttk.Frame(self)
        btn.pack(fill=X, padx=16, pady=10)
        ttk.Button(btn, text="Cancel", bootstyle=(SECONDARY, OUTLINE),
                   command=self.destroy).pack(side=RIGHT, padx=4)
        ttk.Button(btn, text="Save", bootstyle=SUCCESS,
                   command=self._save).pack(side=RIGHT, padx=4)

    def _section(self, parent, text):
        f = ttk.Frame(parent)
        f.pack(fill=X, padx=8, pady=(10, 2))
        ttk.Label(f, text=text, font=("Segoe UI", 10, "bold"), bootstyle=PRIMARY).pack(side=LEFT)
        ttk.Separator(f).pack(side=LEFT, fill=X, expand=True, padx=8)

    def _field(self, parent, label, key, widget="entry", options=None, side=LEFT, width=20):
        f = ttk.Frame(parent)
        f.pack(side=side, padx=6, pady=2)
        ttk.Label(f, text=label, font=("Segoe UI", 8)).pack(anchor=W)
        var = tk.StringVar()
        self._vars[key] = var
        if widget == "combobox":
            ttk.Combobox(f, textvariable=var, values=options or [],
                          width=width).pack(anchor=W)
        else:
            ttk.Entry(f, textvariable=var, width=width).pack(anchor=W)
        return var

    def _build_form(self, parent):
        self._section(parent, "Basic Information")
        row0 = ttk.Frame(parent)
        row0.pack(fill=X, padx=16)
        self._field(row0, "School Year *", "school_year", side=LEFT, width=14)
        self._field(row0, "First Name *", "first_name", side=LEFT, width=18)
        self._field(row0, "Last Name *", "last_name", side=LEFT, width=18)

        row1 = ttk.Frame(parent)
        row1.pack(fill=X, padx=16, pady=(4, 0))
        self._field(row1, "Grade", "grade", widget="combobox",
                    options=GRADE_OPTIONS, side=LEFT, width=8)
        self._field(row1, "Gender", "gender", widget="combobox",
                    options=GENDER_OPTIONS, side=LEFT, width=16)
        self._field(row1, "Student ID", "student_id", side=LEFT, width=16)

        self._section(parent, "Contact Information")
        row2 = ttk.Frame(parent)
        row2.pack(fill=X, padx=16)
        self._field(row2, "Phone", "phone", side=LEFT, width=18)
        self._field(row2, "Student Email", "student_email", side=LEFT, width=28)

        row3 = ttk.Frame(parent)
        row3.pack(fill=X, padx=16, pady=(4, 0))
        self._field(row3, "Address", "address", side=LEFT, width=30)

        row4 = ttk.Frame(parent)
        row4.pack(fill=X, padx=16, pady=(4, 0))
        self._field(row4, "City", "city", side=LEFT, width=20)
        self._field(row4, "State", "state", side=LEFT, width=6)
        self._field(row4, "ZIP", "zip_code", side=LEFT, width=10)

        self._section(parent, "Parent / Guardian 1")
        row5 = ttk.Frame(parent)
        row5.pack(fill=X, padx=16)
        self._field(row5, "Name", "parent1_name", side=LEFT, width=24)
        self._field(row5, "Relation", "parent1_relation", widget="combobox",
                    options=RELATION_OPTIONS, side=LEFT, width=14)

        row6 = ttk.Frame(parent)
        row6.pack(fill=X, padx=16, pady=(4, 0))
        self._field(row6, "Phone", "parent1_phone", side=LEFT, width=18)
        self._field(row6, "Email", "parent1_email", side=LEFT, width=28)

        self._section(parent, "Parent / Guardian 2")
        row7 = ttk.Frame(parent)
        row7.pack(fill=X, padx=16)
        self._field(row7, "Name", "parent2_name", side=LEFT, width=24)
        self._field(row7, "Relation", "parent2_relation", widget="combobox",
                    options=RELATION_OPTIONS, side=LEFT, width=14)

        row8 = ttk.Frame(parent)
        row8.pack(fill=X, padx=16, pady=(4, 0))
        self._field(row8, "Phone", "parent2_phone", side=LEFT, width=18)
        self._field(row8, "Email", "parent2_email", side=LEFT, width=28)

        self._section(parent, "Notes")
        notes_frame = ttk.Frame(parent)
        notes_frame.pack(fill=X, padx=20, pady=(4, 0))
        self._notes_text = tk.Text(notes_frame, height=3, font=("Segoe UI", 9),
                                    relief="solid", bd=1, wrap=WORD, width=60)
        self._notes_text.pack(fill=X)

        # Set default year
        if "school_year" in self._vars:
            self._vars["school_year"].set(self.default_year)

    def _load(self, student_id: int):
        student = self.db.get_student(student_id)
        if not student:
            return
        for key, var in self._vars.items():
            val = student[key] if key in student.keys() else None
            var.set("" if val is None else str(val))
        notes = student["notes"] or ""
        self._notes_text.delete("1.0", "end")
        self._notes_text.insert("1.0", notes)

    def _collect(self) -> dict:
        data = {k: v.get().strip() for k, v in self._vars.items()}
        data["notes"] = self._notes_text.get("1.0", "end").strip()
        if self.student_id:
            data["is_active"] = 1
        return data

    def _validate(self, data: dict) -> bool:
        if not data.get("first_name") and not data.get("last_name"):
            Messagebox.show_warning("Student name is required.", title="Validation")
            return False
        if not data.get("school_year"):
            Messagebox.show_warning("School year is required.", title="Validation")
            return False
        return True

    def _save(self):
        data = self._collect()
        if not self._validate(data):
            return
        if self.student_id:
            self.db.update_student(self.student_id, data)
        else:
            self.db.add_student(data)
        self.destroy()
