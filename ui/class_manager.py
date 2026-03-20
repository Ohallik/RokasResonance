"""
ui/class_manager.py - Class management by school year
"""

import tkinter as tk
from tkinter import filedialog
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from ttkbootstrap.dialogs import Messagebox
from datetime import datetime
from ui.theme import muted_fg, subtle_fg, fs


def _current_school_year() -> str:
    today = datetime.today()
    if today.month >= 8:
        return f"{today.year}-{today.year + 1}"
    return f"{today.year - 1}-{today.year}"


ENSEMBLE_OPTIONS = ["Band", "Orchestra", "Choir", "Jazz Band", "Guitar", "Mariachi", "General Music", "Other"]
GRADE_OPTIONS = ["6", "7", "8", "6-7", "7-8", "6-8"]
SKILL_LEVEL_OPTIONS = ["Beginning", "Intermediate", "Advanced", "Mixed"]


class ClassManager(ttk.Frame):
    def __init__(self, parent, db):
        super().__init__(parent)
        self.db = db
        self._year_var = tk.StringVar()
        self._search_var = tk.StringVar()
        self._show_inactive_var = tk.BooleanVar(value=False)
        self._selected_id = None

        self._build()
        self._populate_year_options()
        self.refresh()

    def _build(self):
        # ── Toolbar ───────────────────────────────────────────────────────────
        toolbar = ttk.Frame(self, bootstyle=LIGHT)
        toolbar.pack(fill=X)

        ttk.Button(toolbar, text="➕ Add Class", bootstyle=SUCCESS,
                   command=self._add_class).pack(side=LEFT, padx=6, pady=6)
        ttk.Button(toolbar, text="✏️ Edit", bootstyle=PRIMARY,
                   command=self._edit_class).pack(side=LEFT, padx=2, pady=6)
        ttk.Button(toolbar, text="🗑️ Delete", bootstyle=DANGER,
                   command=self._delete_class).pack(side=LEFT, padx=2, pady=6)
        ttk.Button(toolbar, text="🔄 Refresh", bootstyle=(SECONDARY, OUTLINE),
                   command=self.refresh).pack(side=LEFT, padx=6, pady=6)

        ttk.Separator(toolbar, orient=VERTICAL).pack(side=LEFT, fill=Y, padx=8, pady=4)

        ttk.Label(toolbar, text="School Year:").pack(side=LEFT, padx=(0, 4))
        years_combo = ttk.Combobox(toolbar, textvariable=self._year_var,
                                    state="readonly", width=14)
        years_combo.pack(side=LEFT, padx=(0, 10))
        years_combo.bind("<<ComboboxSelected>>", lambda e: self.refresh())
        self._years_combo = years_combo

        # ── Filter bar (below toolbar) ─────────────────────────────────────────
        filter_bar = ttk.Frame(self)
        filter_bar.pack(fill=X, padx=6, pady=(2, 0))

        ttk.Label(filter_bar, text="Search:").pack(side=LEFT, padx=(0, 4))
        ttk.Entry(filter_bar, textvariable=self._search_var, width=26).pack(side=LEFT)
        self._search_var.trace_add("write", lambda *_: self._apply_filter())

        ttk.Checkbutton(
            filter_bar,
            text="Show Inactive",
            variable=self._show_inactive_var,
            bootstyle=SECONDARY,
            command=self.refresh,
        ).pack(side=LEFT, padx=(12, 0))

        self._count_lbl = ttk.Label(filter_bar, text="", foreground=muted_fg())
        self._count_lbl.pack(side=RIGHT, padx=6)

        # ── Content: Tree + Detail ─────────────────────────────────────────────
        paned = ttk.Panedwindow(self, orient=HORIZONTAL)
        paned.pack(fill=BOTH, expand=True, padx=6, pady=6)

        # Left: class list
        list_frame = ttk.Frame(paned)
        paned.add(list_frame, weight=2)

        cols = ("Class Name", "Ensemble Type", "Grade(s)", "Level", "Period", "Days", "Duration", "Students")
        sb = ttk.Scrollbar(list_frame, orient=VERTICAL)
        self.tree = ttk.Treeview(list_frame, columns=cols, show="headings",
                                  yscrollcommand=sb.set, selectmode="browse",
                                  bootstyle=PRIMARY)
        sb.config(command=self.tree.yview)
        sb.pack(side=RIGHT, fill=Y)
        self.tree.pack(fill=BOTH, expand=True)

        widths = [180, 120, 70, 100, 60, 100, 70, 70]
        _stretch = {"Class Name"}
        for col, w in zip(cols, widths):
            self.tree.heading(col, text=col, anchor=W,
                              command=lambda c=col: self._sort_by(c))
            self.tree.column(col, width=w, anchor=W, stretch=col in _stretch)

        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.bind("<Double-1>", lambda e: self._edit_class())

        # Right: detail panel
        detail_frame = ttk.Frame(paned, width=300)
        paned.add(detail_frame, weight=1)
        self._build_detail(detail_frame)

        self._sort_col = "Class Name"
        self._sort_asc = True
        self._all_classes = []

    def _build_detail(self, parent):
        nb = ttk.Notebook(parent, bootstyle=PRIMARY)
        nb.pack(fill=BOTH, expand=True)

        info_tab = ttk.Frame(nb)
        concerts_tab = ttk.Frame(nb)
        curriculum_tab = ttk.Frame(nb)
        nb.add(info_tab, text="Class Info")
        nb.add(concerts_tab, text="Concert Dates")
        nb.add(curriculum_tab, text="Curriculum Summary")

        # ── Class Info tab ────────────────────────────────────────────────────
        outer = ttk.Frame(info_tab)
        outer.pack(fill=BOTH, expand=True, padx=8, pady=8)

        self._detail_labels = {}
        fields = [
            ("Class Name", "class_name"),
            ("Ensemble Type", "ensemble_type"),
            ("Grade Levels", "grade_levels"),
            ("Skill Level", "skill_level"),
            ("Period", "period"),
            ("Days of Week", "days_of_week"),
            ("Duration", "class_duration"),
            ("Student Count", "student_count"),
            ("Method Book", "method_book"),
            ("School Year", "school_year"),
            ("Room", "room"),
            ("Notes", "notes"),
        ]
        for label, key in fields:
            r = ttk.Frame(outer)
            r.pack(fill=X, pady=1)
            ttk.Label(r, text=f"{label}:", font=("Segoe UI", fs(8), "bold"),
                      width=14, anchor=W).pack(side=LEFT)
            lbl = ttk.Label(r, text="", font=("Segoe UI", fs(8)),
                             anchor=W, wraplength=180, justify=LEFT)
            lbl.pack(side=LEFT, fill=X, expand=True)
            self._detail_labels[key] = lbl

        # ── Concert Dates tab ─────────────────────────────────────────────────
        concerts_frame = ttk.Frame(concerts_tab)
        concerts_frame.pack(fill=BOTH, expand=True, padx=8, pady=8)

        # Toolbar for concert dates
        concerts_toolbar = ttk.Frame(concerts_frame)
        concerts_toolbar.pack(fill=X, pady=(0, 6))

        ttk.Button(concerts_toolbar, text="➕ Add Concert", bootstyle=SUCCESS,
                   command=self._add_concert).pack(side=LEFT, padx=2, pady=2)
        ttk.Button(concerts_toolbar, text="✏️ Edit", bootstyle=PRIMARY,
                   command=self._edit_concert).pack(side=LEFT, padx=2, pady=2)
        ttk.Button(concerts_toolbar, text="🗑️ Delete", bootstyle=DANGER,
                   command=self._delete_concert).pack(side=LEFT, padx=2, pady=2)

        # Concert dates tree
        cols_c = ("Concert Date", "Event Name", "Location")
        sb_c = ttk.Scrollbar(concerts_frame, orient=VERTICAL)
        self._concerts_tree = ttk.Treeview(concerts_frame, columns=cols_c, show="headings",
                                           yscrollcommand=sb_c.set, bootstyle=INFO)
        sb_c.config(command=self._concerts_tree.yview)
        sb_c.pack(side=RIGHT, fill=Y)
        self._concerts_tree.pack(fill=BOTH, expand=True)

        _stretch_c = {"Event Name"}
        for col in cols_c:
            self._concerts_tree.heading(col, text=col, anchor=W)
            self._concerts_tree.column(col, width=120, anchor=W,
                                       minwidth=40, stretch=col in _stretch_c)

        # ── Curriculum Summary tab ────────────────────────────────────────────
        curric_outer = ttk.Frame(curriculum_tab)
        curric_outer.pack(fill=BOTH, expand=True, padx=8, pady=8)

        self._curriculum_labels = {}
        curric_fields = [
            ("Curriculum Items", "item_count"),
            ("Lesson Plans", "lesson_count"),
            ("Date Range", "date_range"),
        ]
        for label, key in curric_fields:
            r = ttk.Frame(curric_outer)
            r.pack(fill=X, pady=4)
            ttk.Label(r, text=f"{label}:", font=("Segoe UI", fs(8), "bold"),
                      width=14, anchor=W).pack(side=LEFT)
            lbl = ttk.Label(r, text="", font=("Segoe UI", fs(8)),
                             anchor=W, wraplength=180, justify=LEFT)
            lbl.pack(side=LEFT, fill=X, expand=True)
            self._curriculum_labels[key] = lbl

    # ─────────────────────────────────────────────────────────── Data Loading ─

    def _populate_year_options(self):
        years = self.db.get_class_school_years()
        cur = _current_school_year()
        # Ensure current year is always available
        if cur not in years:
            years.insert(0, cur)
        self._years_combo["values"] = years
        # Default to current school year
        if not self._year_var.get():
            self._year_var.set(cur)

    def refresh(self):
        year = self._year_var.get() or None
        include_inactive = self._show_inactive_var.get()
        self._all_classes = list(self.db.get_all_classes(
            school_year=year, include_inactive=include_inactive))
        self._apply_filter()
        self._populate_year_options()

    def _apply_filter(self):
        search = self._search_var.get().lower()
        visible = []
        for c in self._all_classes:
            if search:
                haystack = " ".join([
                    str(c.get("class_name") or ""),
                    str(c.get("ensemble_type") or ""),
                    str(c.get("grade_levels") or ""),
                    str(c.get("period") or ""),
                ]).lower()
                if search not in haystack:
                    continue
            visible.append(c)

        self._populate_tree(visible)
        self._count_lbl.config(text=f"{len(visible)} class(es)")

    def _populate_tree(self, classes):
        col_key_map = {
            "Class Name": "class_name",
            "Ensemble Type": "ensemble_type",
            "Grade(s)": "grade_levels",
            "Level": "skill_level",
            "Period": "period",
            "Days": "days_of_week",
            "Duration": "class_duration",
            "Students": "student_count",
        }
        key = col_key_map.get(self._sort_col, "class_name")

        def sort_key(c):
            val = c.get(key) or ""
            return str(val).lower() if isinstance(val, str) else (val or 0)

        classes = sorted(classes, key=sort_key, reverse=not self._sort_asc)

        # Configure inactive tag with current theme color
        self.tree.tag_configure("inactive", foreground=subtle_fg())

        self.tree.delete(*self.tree.get_children())
        for c in classes:
            iid = str(c["id"])
            is_inactive = not c.get("is_active", 1)
            tags = ("inactive",) if is_inactive else ()
            class_name = c.get("class_name", "")
            if is_inactive:
                class_name += " (inactive)"

            duration_str = f"{c.get('class_duration', '')} min" if c.get('class_duration') else ""

            self.tree.insert("", "end", iid=iid, tags=tags, values=(
                class_name,
                c.get("ensemble_type") or "",
                c.get("grade_levels") or "",
                c.get("skill_level") or "",
                c.get("period") or "",
                c.get("days_of_week") or "",
                duration_str,
                c.get("student_count") or "",
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

    def _load_detail(self, class_id: int):
        cls = self.db.get_class(class_id)
        if not cls:
            return

        row = dict(cls)

        # Load basic class info
        for key, lbl in self._detail_labels.items():
            val = row.get(key, "")
            if key == "class_duration" and val:
                val = f"{val} minutes"
            lbl.config(text=str(val) if val else "")

        # Load concert dates
        self._concerts_tree.delete(*self._concerts_tree.get_children())
        concerts = self.db.get_concert_dates(class_id)
        for concert in concerts:
            self._concerts_tree.insert("", "end", iid=str(concert["id"]), values=(
                concert.get("concert_date") or "",
                concert.get("event_name") or "",
                concert.get("location") or "",
            ))

        # Load curriculum summary
        curriculum = list(self.db.get_curriculum_items(class_id))
        item_count = len(curriculum)

        # Get lesson plan stats
        lesson_stats = self.db.get_lesson_plan_stats(class_id)
        lesson_count = lesson_stats.get("count", 0) if lesson_stats else 0

        # Calculate date range
        date_range = ""
        if curriculum:
            dates = [c.get("date") for c in curriculum if c.get("date")]
            if dates:
                dates.sort()
                date_range = f"{dates[0]} to {dates[-1]}"

        self._curriculum_labels["item_count"].config(text=str(item_count))
        self._curriculum_labels["lesson_count"].config(text=str(lesson_count))
        self._curriculum_labels["date_range"].config(text=date_range)

    # ─────────────────────────────────────────────────────────── Actions ──────

    def _get_selected(self):
        sel = self.tree.selection()
        if not sel:
            Messagebox.show_warning("Please select a class first.", title="No Selection", parent=self)
            return None
        return int(sel[0])

    def _add_class(self):
        dlg = ClassDialog(self.winfo_toplevel(), self.db,
                          class_id=None,
                          default_year=self._year_var.get())
        self.wait_window(dlg)
        self.refresh()

    def _edit_class(self):
        cid = self._get_selected()
        if cid is None:
            return
        dlg = ClassDialog(self.winfo_toplevel(), self.db,
                          class_id=cid,
                          default_year=self._year_var.get())
        self.wait_window(dlg)
        self.refresh()
        self._load_detail(cid)

    def _delete_class(self):
        cid = self._get_selected()
        if cid is None:
            return
        cls = self.db.get_class(cid)
        if not cls:
            return
        name = cls.get("class_name", "Unknown")

        # Confirm deletion
        answer = Messagebox.yesno(
            f"Are you sure you want to delete {name}?\n\n"
            f"This will remove it from the class list.",
            title="Confirm Delete"
, parent=self)
        if answer != "Yes":
            return

        self.db.deactivate_class(cid)
        self._selected_id = None
        self.refresh()

    def _add_concert(self):
        if self._selected_id is None:
            Messagebox.show_warning("Please select a class first.", title="No Selection", parent=self)
            return
        dlg = ConcertDateDialog(self.winfo_toplevel(), self.db,
                                concert_id=None,
                                class_id=self._selected_id)
        self.wait_window(dlg)
        self._load_detail(self._selected_id)

    def _edit_concert(self):
        sel = self._concerts_tree.selection()
        if not sel:
            Messagebox.show_warning("Please select a concert date first.", title="No Selection", parent=self)
            return
        concert_id = int(sel[0])
        dlg = ConcertDateDialog(self.winfo_toplevel(), self.db,
                                concert_id=concert_id,
                                class_id=self._selected_id)
        self.wait_window(dlg)
        self._load_detail(self._selected_id)

    def _delete_concert(self):
        sel = self._concerts_tree.selection()
        if not sel:
            Messagebox.show_warning("Please select a concert date first.", title="No Selection", parent=self)
            return
        concert_id = int(sel[0])

        answer = Messagebox.yesno(
            "Delete this concert date?",
            title="Confirm Delete"
, parent=self)
        if answer != "Yes":
            return

        self.db.delete_concert_date(concert_id)
        self._load_detail(self._selected_id)


class ClassDialog(ttk.Toplevel):
    def __init__(self, parent, db, class_id=None, default_year=None):
        super().__init__(parent)
        self.db = db
        self.class_id = class_id
        self.default_year = default_year or _current_school_year()

        self.title("Edit Class" if class_id else "Add Class")
        self.resizable(True, True)
        self.grab_set()
        self.lift()

        self._vars = {}
        self._build()
        if class_id:
            self._load(class_id)

        from ui.theme import fit_window
        fit_window(self, 520, 480)

    def _build(self):
        hdr = ttk.Frame(self, bootstyle=PRIMARY)
        hdr.pack(fill=X)
        title = "Edit Class" if self.class_id else "Add Class"
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

        # Mark Inactive / Reactivate — only shown when editing an existing class
        if self.class_id:
            cls = self.db.get_class(self.class_id)
            is_active = cls.get("is_active", 1) if cls else 1
            if is_active:
                ttk.Button(btn, text="Mark Inactive", bootstyle=(WARNING, OUTLINE),
                           command=self._mark_inactive).pack(side=LEFT, padx=4)
            else:
                ttk.Button(btn, text="Reactivate", bootstyle=(SUCCESS, OUTLINE),
                           command=self._reactivate).pack(side=LEFT, padx=4)

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
                          width=width, state="readonly" if options else "normal").pack(anchor=W)
        elif widget == "spinbox":
            ttk.Spinbox(f, textvariable=var, from_=20, to=120, width=width).pack(anchor=W)
        else:
            ttk.Entry(f, textvariable=var, width=width).pack(anchor=W)
        return var

    def _build_form(self, parent):
        self._section(parent, "Basic Information")
        row0 = ttk.Frame(parent)
        row0.pack(fill=X, padx=16)
        self._field(row0, "School Year *", "school_year", widget="combobox",
                    options=self._get_school_years(), side=LEFT, width=14)
        self._field(row0, "Class Name *", "class_name", side=LEFT, width=20)

        row1 = ttk.Frame(parent)
        row1.pack(fill=X, padx=16, pady=(4, 0))
        self._field(row1, "Ensemble Type *", "ensemble_type", widget="combobox",
                    options=ENSEMBLE_OPTIONS, side=LEFT, width=14)
        self._field(row1, "Grade Levels *", "grade_levels", widget="combobox",
                    options=GRADE_OPTIONS, side=LEFT, width=10)

        row2 = ttk.Frame(parent)
        row2.pack(fill=X, padx=16, pady=(4, 0))
        self._field(row2, "Skill Level", "skill_level", widget="combobox",
                    options=SKILL_LEVEL_OPTIONS, side=LEFT, width=14)
        self._field(row2, "Period", "period", side=LEFT, width=10)

        self._section(parent, "Schedule")
        row3 = ttk.Frame(parent)
        row3.pack(fill=X, padx=16)
        self._field(row3, "Days of Week", "days_of_week", side=LEFT, width=18)
        # Default value
        self._vars["days_of_week"].set("M,T,W,Th,F")

        row4 = ttk.Frame(parent)
        row4.pack(fill=X, padx=16, pady=(4, 0))
        self._field(row4, "Duration (min)", "class_duration", widget="spinbox", side=LEFT, width=10)
        # Default value
        self._vars["class_duration"].set("45")

        self._section(parent, "Details")
        row5 = ttk.Frame(parent)
        row5.pack(fill=X, padx=16)
        self._field(row5, "Method Book", "method_book", side=LEFT, width=20)
        self._field(row5, "Room", "room", side=LEFT, width=8)

        notes_label = ttk.Label(parent, text="Notes:", font=("Segoe UI", 8, "bold"))
        notes_label.pack(anchor=W, padx=24, pady=(10, 2))
        notes_frame = ttk.Frame(parent)
        notes_frame.pack(fill=X, padx=20, pady=(0, 4))
        self._notes_text = tk.Text(notes_frame, height=3, font=("Segoe UI", 9),
                                    relief="solid", bd=1, wrap=WORD, width=60)
        self._notes_text.pack(fill=X)

        # Set default year
        if "school_year" in self._vars:
            self._vars["school_year"].set(self.default_year)

    def _get_school_years(self):
        years = list(self.db.get_class_school_years())
        cur = _current_school_year()
        if cur not in years:
            years.insert(0, cur)
        return years

    def _load(self, class_id: int):
        cls = self.db.get_class(class_id)
        if not cls:
            return
        for key, var in self._vars.items():
            val = cls.get(key)
            var.set("" if val is None else str(val))
        notes = cls.get("notes") or ""
        self._notes_text.delete("1.0", "end")
        self._notes_text.insert("1.0", notes)

    def _collect(self) -> dict:
        data = {k: v.get().strip() for k, v in self._vars.items()}
        data["notes"] = self._notes_text.get("1.0", "end").strip()
        if self.class_id:
            data["is_active"] = 1
        return data

    def _validate(self, data: dict) -> bool:
        if not data.get("class_name"):
            Messagebox.show_warning("Class name is required.", title="Validation", parent=self)
            return False
        if not data.get("school_year"):
            Messagebox.show_warning("School year is required.", title="Validation", parent=self)
            return False
        if not data.get("ensemble_type"):
            Messagebox.show_warning("Ensemble type is required.", title="Validation", parent=self)
            return False
        if not data.get("grade_levels"):
            Messagebox.show_warning("Grade levels are required.", title="Validation", parent=self)
            return False
        # Try to convert duration to int
        try:
            if data.get("class_duration"):
                int(data["class_duration"])
        except ValueError:
            Messagebox.show_warning("Duration must be a number.", title="Validation", parent=self)
            return False
        return True

    def _mark_inactive(self):
        cls = self.db.get_class(self.class_id)
        name = cls.get("class_name", "this class") if cls else "this class"
        answer = Messagebox.yesno(
            f"Mark {name} as inactive?\n\nIt will be hidden from the class list "
            f"unless 'Show Inactive' is checked.",
            title="Mark Inactive",
            parent=self,
        )
        if answer == "Yes":
            self.db.deactivate_class(self.class_id)
            self.destroy()

    def _reactivate(self):
        cls = self.db.get_class(self.class_id)
        name = cls.get("class_name", "this class") if cls else "this class"
        answer = Messagebox.yesno(
            f"Reactivate {name}?",
            title="Reactivate",
            parent=self,
        )
        if answer == "Yes":
            # Update to set is_active = 1
            self.db.update_class(self.class_id, {"is_active": 1})
            self.destroy()

    def _save(self):
        data = self._collect()
        if not self._validate(data):
            return
        if self.class_id:
            self.db.update_class(self.class_id, data)
        else:
            self.db.add_class(data)
        self.destroy()


class ConcertDateDialog(ttk.Toplevel):
    def __init__(self, parent, db, concert_id=None, class_id=None):
        super().__init__(parent)
        self.db = db
        self.concert_id = concert_id
        self.class_id = class_id

        self.title("Edit Concert Date" if concert_id else "Add Concert Date")
        self.resizable(False, False)
        self.grab_set()
        self.lift()

        self._vars = {}
        self._build()
        if concert_id:
            self._load(concert_id)

        from ui.theme import fit_window
        fit_window(self, 400, 220)

    def _build(self):
        hdr = ttk.Frame(self, bootstyle=INFO)
        hdr.pack(fill=X)
        title = "Edit Concert Date" if self.concert_id else "Add Concert Date"
        ttk.Label(hdr, text=title, font=("Segoe UI", 12, "bold"),
                  bootstyle=(INVERSE, INFO)).pack(pady=10, padx=16, anchor=W)

        content = ttk.Frame(self)
        content.pack(fill=BOTH, expand=True, padx=16, pady=12)

        # Concert Date field
        row0 = ttk.Frame(content)
        row0.pack(fill=X, pady=6)
        ttk.Label(row0, text="Concert Date:", font=("Segoe UI", 9)).pack(side=LEFT, padx=(0, 6))
        self._date_var = tk.StringVar()
        self._vars["concert_date"] = self._date_var
        ttk.Entry(row0, textvariable=self._date_var, width=20).pack(side=LEFT)
        ttk.Label(row0, text="(YYYY-MM-DD)", font=("Segoe UI", 8), foreground=muted_fg()).pack(side=LEFT, padx=(6, 0))

        # Event Name field
        row1 = ttk.Frame(content)
        row1.pack(fill=X, pady=6)
        ttk.Label(row1, text="Event Name:", font=("Segoe UI", 9)).pack(side=LEFT, padx=(0, 6))
        self._event_var = tk.StringVar()
        self._vars["event_name"] = self._event_var
        ttk.Entry(row1, textvariable=self._event_var, width=30).pack(side=LEFT, fill=X, expand=True)

        # Location field
        row2 = ttk.Frame(content)
        row2.pack(fill=X, pady=6)
        ttk.Label(row2, text="Location:", font=("Segoe UI", 9)).pack(side=LEFT, padx=(0, 6))
        self._location_var = tk.StringVar()
        self._vars["location"] = self._location_var
        ttk.Entry(row2, textvariable=self._location_var, width=30).pack(side=LEFT, fill=X, expand=True)

        # Notes field
        row3 = ttk.Frame(content)
        row3.pack(fill=X, pady=6)
        ttk.Label(row3, text="Notes:", font=("Segoe UI", 9)).pack(side=LEFT, padx=(0, 6))
        self._notes_var = tk.StringVar()
        self._vars["notes"] = self._notes_var
        ttk.Entry(row3, textvariable=self._notes_var, width=30).pack(side=LEFT, fill=X, expand=True)

        # Buttons
        btn_frame = ttk.Frame(self)
        btn_frame.pack(fill=X, padx=16, pady=(0, 12))
        ttk.Button(btn_frame, text="Cancel", bootstyle=(SECONDARY, OUTLINE),
                   command=self.destroy).pack(side=RIGHT, padx=4)
        ttk.Button(btn_frame, text="Save", bootstyle=SUCCESS,
                   command=self._save).pack(side=RIGHT, padx=4)

    def _load(self, concert_id: int):
        # Query the concert record
        concert = None
        with self.db._connect() as conn:
            concert = conn.execute(
                "SELECT * FROM concert_dates WHERE id=?",
                (concert_id,)
            ).fetchone()

        if not concert:
            return

        self._date_var.set(concert.get("concert_date") or "")
        self._event_var.set(concert.get("event_name") or "")
        self._location_var.set(concert.get("location") or "")
        self._notes_var.set(concert.get("notes") or "")

    def _collect(self) -> dict:
        data = {k: v.get().strip() for k, v in self._vars.items()}
        if self.class_id:
            data["class_id"] = self.class_id
        return data

    def _validate(self, data: dict) -> bool:
        if not data.get("concert_date"):
            Messagebox.show_warning("Concert date is required.", title="Validation", parent=self)
            return False
        # Simple date format validation (YYYY-MM-DD)
        import re
        if not re.match(r'^\d{4}-\d{2}-\d{2}$', data["concert_date"]):
            Messagebox.show_warning("Concert date must be in YYYY-MM-DD format.", title="Validation", parent=self)
            return False
        if not data.get("event_name"):
            Messagebox.show_warning("Event name is required.", title="Validation", parent=self)
            return False
        return True

    def _save(self):
        data = self._collect()
        if not self._validate(data):
            return
        if self.concert_id:
            self.db.update_concert_date(self.concert_id, data)
        else:
            self.db.add_concert_date(data)
        self.destroy()
