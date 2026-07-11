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
        ).pack(side=RIGHT, padx=16, pady=8)

        # ── Notebook ─────────────────────────────────────────────────────────
        self._notebook = ttk.Notebook(self, bootstyle=PRIMARY)
        self._notebook.pack(fill=BOTH, expand=True)

        from ui.seating_chart_view import SeatingChartView
        self._seating = SeatingChartView(self._notebook, self.db,
                                         self.main_db, self._base_dir)
        self._notebook.add(self._seating, text="  🪑 Seating Charts  ")

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

        self._agendas = self._placeholder(
            "📋", "Daily Agendas",
            "Build a simple daily agenda you can project on the screen:\n"
            "what to grab, warm-up, rehearsal order, percussion assignments,\n"
            "and announcements.\n\nComing soon.")
        self._notebook.add(self._agendas, text="  📋 Agendas  ")

        self._notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

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
        return [self._seating, self._percussion, self._concerts,
                self._field_trips]

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
