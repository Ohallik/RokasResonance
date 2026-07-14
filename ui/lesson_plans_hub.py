"""
ui/lesson_plans_hub.py - Teacher Tools hub.

One window for the tools a director actually uses day to day: seating
charts, percussion rotations, concert planning, and (coming soon) field
trips and daily agendas.  Everything is scoped to a school year — the year
selector switches between per-year files, and the New School Year wizard
closes out one year and opens the next.
"""

import os
import tkinter as tk
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from ui.theme import muted_fg, fs


class LessonPlansHub(ttk.Frame):
    """Tabbed hub for all Teacher Tools functionality."""

    def __init__(self, parent, db):
        super().__init__(parent)
        self.main_db = db  # instruments, students, music
        self._base_dir = os.path.dirname(os.path.abspath(db.db_path))

        # Per-year tools database
        from lesson_plan_db import (
            get_lesson_plan_db, current_school_year,
            migrate_from_main_db,
        )
        migrated = migrate_from_main_db(db.db_path, self._base_dir)
        self._current_year = migrated or current_school_year()
        self.db = get_lesson_plan_db(self._base_dir, self._current_year)
        self._build()

    def _build(self):
        # ── Header ───────────────────────────────────────────────────────────
        header = ttk.Frame(self, bootstyle=PRIMARY)
        header.pack(fill=X)

        ttk.Label(
            header,
            text="🧰  Teacher Tools",
            font=("Segoe UI", fs(16), "bold"),
            bootstyle=(INVERSE, PRIMARY),
        ).pack(side=LEFT, padx=16, pady=12)

        ttk.Label(
            header,
            text="Seating charts, percussion rotations, concert planning & more",
            font=("Segoe UI", fs(9)),
            bootstyle=(INVERSE, PRIMARY),
        ).pack(side=LEFT, padx=(0, 8), pady=12)

        # School year selector
        year_frame = ttk.Frame(header, bootstyle=PRIMARY)
        year_frame.pack(side=LEFT, padx=8, pady=8)
        ttk.Label(
            year_frame, text="Year:",
            font=("Segoe UI", fs(9)),
            bootstyle=(INVERSE, PRIMARY),
        ).pack(side=LEFT, padx=(0, 4))
        self._year_var = tk.StringVar(value=self._current_year)
        self._year_combo = ttk.Combobox(
            year_frame, textvariable=self._year_var,
            state="readonly", width=12,
        )
        self._year_combo.pack(side=LEFT)
        self._populate_year_selector()
        self._year_combo.bind("<<ComboboxSelected>>",
                              lambda e: self._switch_school_year())

        ttk.Button(
            header, text="📦 New School Year…", bootstyle=LIGHT,
            command=self._open_year_wizard,
        ).pack(side=RIGHT, padx=(0, 16), pady=8)
        ttk.Button(
            header, text="🗂 Manage Classes…", bootstyle=LIGHT,
            command=self._open_manage_classes,
        ).pack(side=RIGHT, padx=(0, 4), pady=8)

        # ── Notebook (tools + one agenda tab per class in the registry) ────────
        self._notebook = ttk.Notebook(self, bootstyle=PRIMARY)
        self._notebook.pack(fill=BOTH, expand=True)
        self._seating = self._percussion = self._concerts = None
        self._field_trips = self._jazz = None
        self._agenda_views = []
        self._populate_notebook()
        self._notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

    # ── Notebook tabs are built from the teacher's class registry, so choir/
    #    orchestra/club teachers get their own classes and only band teachers
    #    with a percussion/jazz class see those tool tabs. ──

    def _program_type(self):
        try:
            from ui.settings_dialog import load_settings
            return (load_settings(self._base_dir).get("teacher") or {}).get(
                "program_type", "band")
        except Exception:
            return "band"

    def _classes(self):
        import class_registry
        return class_registry.load_classes(self._base_dir, self._program_type())

    def _populate_notebook(self):
        # Clear any existing tabs (Manage Classes / year switch rebuilds live).
        for tab_id in list(self._notebook.tabs()):
            w = self._notebook.nametowidget(tab_id)
            self._notebook.forget(tab_id)
            w.destroy()
        self._agenda_views = []
        classes = self._classes()
        program = self._program_type()

        from ui.seating_chart_view import SeatingChartView
        self._seating = SeatingChartView(self._notebook, self.db,
                                         self.main_db, self._base_dir)
        self._notebook.add(self._seating, text="  🪑 Seating Charts  ")

        self._percussion = None
        # Choir/orchestra never have percussion; otherwise show the tab if any
        # class uses a percussion rotation.
        if program not in ("choir", "orchestra") and any(
                k.get("percussion") for k in classes):
            from ui.percussion_rotation_view import PercussionRotationView
            self._percussion = PercussionRotationView(self._notebook, self.db)
            self._notebook.add(self._percussion, text="  🥁 Percussion  ")

        from ui.concerts_view import ConcertsView
        self._concerts = ConcertsView(self._notebook, self.db, self.main_db,
                                      self._base_dir)
        self._notebook.add(self._concerts, text="  🎪 Concerts  ")

        from ui.field_trips_view import FieldTripsView
        self._field_trips = FieldTripsView(self._notebook, self.db,
                                           self.main_db, self._base_dir)
        self._notebook.add(self._field_trips, text="  🚌 Field Trips  ")

        self._jazz = None
        if any(k.get("template") == "jazz" for k in classes):
            from ui.jazz_view import JazzView
            self._jazz = JazzView(self._notebook, self.db)
            self._notebook.add(self._jazz, text="  🎷 Jazz  ")

        from ui.agendas_view import AgendasView
        for k in classes:
            av = AgendasView(self._notebook, self.db, self.main_db,
                             self._base_dir, klass=k)
            self._notebook.add(av, text=f"  📋 {k['label']}  ")
            self._agenda_views.append(av)

    def _open_manage_classes(self):
        classes = self._classes()
        dlg = _ManageClassesDialog(self.winfo_toplevel(), classes,
                                   self._program_type())
        self.wait_window(dlg)
        if dlg.result is None:
            return
        import class_registry
        class_registry.save_classes(self._base_dir, dlg.result)
        self._populate_notebook()

    def _placeholder(self, icon, title, body):
        outer = ttk.Frame(self._notebook)
        frame = ttk.Frame(outer)
        frame.place(relx=0.5, rely=0.45, anchor="center")
        ttk.Label(frame, text=icon, font=("Segoe UI", fs(40))).pack(pady=(0, 10))
        ttk.Label(frame, text=title,
                  font=("Segoe UI", fs(16), "bold")).pack()
        ttk.Label(frame, text=body, font=("Segoe UI", fs(10)),
                  foreground=muted_fg(), justify="center").pack(pady=(8, 0))
        return outer

    def _tabs(self):
        core = [self._seating, self._percussion, self._concerts,
                self._field_trips, self._jazz]
        return [t for t in core if t is not None] + list(self._agenda_views)

    def _on_tab_changed(self, event):
        """Refresh the active tab's data when switching to it."""
        try:
            widget = self._notebook.nametowidget(self._notebook.select())
        except Exception:
            return
        if hasattr(widget, "refresh"):
            widget.refresh()

    # ── School years ─────────────────────────────────────────────────────────

    def _populate_year_selector(self):
        from lesson_plan_db import list_available_school_years, current_school_year
        years = list_available_school_years(self._base_dir)
        cur = current_school_year()
        if cur not in years:
            years.insert(0, cur)
        if self._current_year not in years:
            years.insert(0, self._current_year)
        years.sort(reverse=True)
        self._year_combo.config(values=years)
        self._year_combo.set(self._current_year)

    def _switch_school_year(self):
        new_year = self._year_var.get()
        if new_year == self._current_year:
            return
        from lesson_plan_db import get_lesson_plan_db
        self._current_year = new_year
        self.db = get_lesson_plan_db(self._base_dir, new_year)
        for tab in self._tabs():
            tab.db = self.db
            tab.refresh()

    def switch_to_year(self, year: str):
        """Programmatic year switch (used by the New School Year wizard)."""
        self._year_var.set(year)
        self._populate_year_selector()
        self._year_combo.set(year)
        self._switch_school_year()

    def _open_year_wizard(self):
        from ui.year_wizard import NewSchoolYearWizard
        wiz = NewSchoolYearWizard(self.winfo_toplevel(), self.main_db,
                                  self._base_dir,
                                  current_year=self._current_year)
        self.wait_window(wiz)
        if wiz.new_year:
            self.switch_to_year(wiz.new_year)


# ── Template display names for the Manage Classes picker ──────────────────────
# Plain names only — teachers pick during first-run setup before they know what
# each includes, so descriptions here would just confuse. (Details live in each
# template's ``desc`` and show up later in Manage Classes.)
_TMPL_DISPLAY = {
    "generic": "General",
    "band_5": "5th Grade Band",
    "orch_5": "5th Grade Orchestra",
    "band_entry": "MS Band (Entry)",
    "band_intermediate": "MS Band (Intermediate)",
    "band_advanced": "MS Band (Advanced)",
    "orch_mshs": "MS/HS Orchestra",
    "choir_mshs": "MS/HS Choir",
    "guitar_steel": "MS/HS Guitar / Steel Drum",
    "hs_band_winds": "HS Band (Winds)",
    "hs_band_perc": "HS Band (Percussion)",
    "jazz": "Jazz",
}


class _ManageClassesDialog(ttk.Toplevel):
    """Add / rename / remove / reorder the classes that get an agenda tab.

    Each class picks a TEMPLATE (its kind).  Existing classes keep their stored
    id (so saved agendas stay attached); new ones get an id from their name.
    """

    def __init__(self, parent, classes, program_type):
        super().__init__(parent)
        import class_registry as cr
        self._cr = cr
        self.result = None
        self._program_type = program_type
        self.title("Manage Classes")
        self.resizable(False, True)
        self.grab_set()
        self.lift()

        self._display_to_tmpl = {v: k for k, v in _TMPL_DISPLAY.items()}
        self._tmpl_options = [_TMPL_DISPLAY[t] for t in cr.TEMPLATE_ORDER]

        hdr = ttk.Frame(self, bootstyle=PRIMARY)
        hdr.pack(fill=X)
        ttk.Label(hdr, text="🗂  Your Classes", font=("Segoe UI", 13, "bold"),
                  bootstyle=(INVERSE, PRIMARY)).pack(pady=12, padx=16, anchor=W)

        # Buttons pinned to the bottom.
        btn = ttk.Frame(self)
        btn.pack(side=BOTTOM, fill=X, padx=16, pady=12)
        ttk.Button(btn, text="Cancel", bootstyle=(SECONDARY, OUTLINE),
                   command=self.destroy).pack(side=RIGHT, padx=4)
        ttk.Button(btn, text="Save", bootstyle=SUCCESS,
                   command=self._save).pack(side=RIGHT, padx=4)

        body = ttk.Frame(self)
        body.pack(fill=BOTH, expand=True, padx=16, pady=10)
        ttk.Label(body, text="One row per class or club. Each gets its own agenda "
                             "tab. Pick the kind of class (its template); rename "
                             "or reorder freely. Itinerant teachers can add as "
                             "many — or as few — as they run.",
                  font=("Segoe UI", 9), wraplength=560, justify=LEFT).pack(anchor=W)

        cols = ttk.Frame(body)
        cols.pack(fill=X, pady=(8, 2))
        ttk.Label(cols, text="Class name", font=("Segoe UI", 9, "bold"),
                  width=22).pack(side=LEFT)
        ttk.Label(cols, text="Kind of class", font=("Segoe UI", 9, "bold")).pack(side=LEFT)

        self._rows_frame = ttk.Frame(body)
        self._rows_frame.pack(fill=BOTH, expand=True)
        self._rows = []
        for k in classes:
            self._add_row(k)

        ttk.Button(body, text="➕ Add class / club", bootstyle=(SUCCESS, OUTLINE),
                   command=lambda: self._add_row(None)).pack(anchor=W, pady=(8, 0))

        from ui.theme import fit_window
        fit_window(self, 620, 520)

    def _add_row(self, klass):
        tmpl = (klass or {}).get("template", "generic")
        if tmpl not in _TMPL_DISPLAY:
            tmpl = "generic"
        rec = {
            "orig": klass,
            "label": tk.StringVar(value=(klass or {}).get("label", "")),
            "template": tk.StringVar(value=_TMPL_DISPLAY[tmpl]),
        }
        self._rows.append(rec)
        self._render_rows()

    def _render_rows(self):
        for w in self._rows_frame.winfo_children():
            w.destroy()
        for i, rec in enumerate(self._rows):
            row = ttk.Frame(self._rows_frame)
            row.pack(fill=X, pady=2)
            ttk.Entry(row, textvariable=rec["label"], width=22).pack(side=LEFT)
            ttk.Combobox(row, textvariable=rec["template"], state="readonly",
                         values=self._tmpl_options, width=44).pack(side=LEFT, padx=(6, 0))
            ttk.Button(row, text="✕", width=2, bootstyle=(DANGER, OUTLINE, LINK),
                       command=lambda r=rec: self._remove(r)).pack(side=RIGHT)
            ttk.Button(row, text="▼", width=2, bootstyle=(SECONDARY, OUTLINE, LINK),
                       command=lambda ix=i: self._move(ix, 1)).pack(side=RIGHT)
            ttk.Button(row, text="▲", width=2, bootstyle=(SECONDARY, OUTLINE, LINK),
                       command=lambda ix=i: self._move(ix, -1)).pack(side=RIGHT)

    def _remove(self, rec):
        self._rows.remove(rec)
        self._render_rows()

    def _move(self, i, delta):
        j = i + delta
        if 0 <= j < len(self._rows):
            self._rows[i], self._rows[j] = self._rows[j], self._rows[i]
            self._render_rows()

    def _save(self):
        from ttkbootstrap.dialogs import Messagebox
        cr = self._cr
        taken = {(r["orig"] or {}).get("id") for r in self._rows if r["orig"]}
        taken.discard(None)
        result = []
        for rec in self._rows:
            label = rec["label"].get().strip()
            if not label:
                continue
            tmpl = self._display_to_tmpl.get(rec["template"].get(), "generic")
            ti = cr.TEMPLATES[tmpl]
            orig = rec["orig"]
            if orig:
                k = dict(orig)
                k["label"] = label
                if k.get("template") != tmpl:      # kind changed → reset derived
                    k["template"] = tmpl
                    k["book"] = ti["book"]
                    k["percussion"] = ti["percussion"]
                result.append(k)
            else:
                cid = cr.new_class_id([{"id": i} for i in taken], label)
                taken.add(cid)
                result.append({"id": cid, "label": label, "template": tmpl,
                               "ensemble": cid, "book": ti["book"],
                               "percussion": ti["percussion"]})
        if not result:
            Messagebox.show_warning("Keep at least one class.",
                                    title="No classes", parent=self)
            return
        self.result = result
        self.destroy()
