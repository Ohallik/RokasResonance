"""
ui/lesson_plans_hub.py - Lesson Plans hub with tabbed navigation.

Central entry point for the Lesson Plans feature, providing a Notebook
with tabs for Class Manager, Curriculum Planner, and (future) Resource Library.
"""

import tkinter as tk
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from ui.theme import muted_fg, fs


class LessonPlansHub(ttk.Frame):
    """Tabbed hub for all Lesson Plans functionality."""

    def __init__(self, parent, db):
        super().__init__(parent)
        self.db = db
        self._build()

    def _build(self):
        # ── Header ───────────────────────────────────────────────────────────
        header = ttk.Frame(self, bootstyle=PRIMARY)
        header.pack(fill=X)

        ttk.Label(
            header,
            text="📝  Lesson Plans",
            font=("Segoe UI", fs(16), "bold"),
            bootstyle=(INVERSE, PRIMARY),
        ).pack(side=LEFT, padx=16, pady=12)

        ttk.Label(
            header,
            text="Plan curriculum, manage classes & create daily lesson plans",
            font=("Segoe UI", fs(9)),
            bootstyle=(INVERSE, PRIMARY),
        ).pack(side=LEFT, padx=(0, 16), pady=12)

        # ── Notebook ─────────────────────────────────────────────────────────
        self._notebook = ttk.Notebook(self, bootstyle=PRIMARY)
        self._notebook.pack(fill=BOTH, expand=True)

        # Tab 1: Curriculum Planner (main view — calendar + toolbar)
        from ui.curriculum_planner import CurriculumPlanner
        curriculum_tab = CurriculumPlanner(
            self._notebook, self.db,
            on_open_lesson_plan=self._open_lesson_plan,
        )
        self._notebook.add(curriculum_tab, text="  📅 Curriculum Planner  ")
        self._curriculum_planner = curriculum_tab

        # Tab 2: Class Manager (setup classes, concert dates)
        from ui.class_manager import ClassManager
        class_tab = ClassManager(self._notebook, self.db)
        self._notebook.add(class_tab, text="  🎓 Manage Classes  ")
        self._class_manager = class_tab

        # Tab 3: Resource Library
        from ui.resource_library import ResourceLibrary
        resource_tab = ResourceLibrary(self._notebook, self.db)
        self._notebook.add(resource_tab, text="  📚 Resource Library  ")
        self._resource_library = resource_tab

        # Tab 4: Concert Countdown Dashboard
        from ui.lesson_plan_extras import ConcertCountdownDashboard
        concert_tab = ConcertCountdownDashboard(self._notebook, self.db)
        self._notebook.add(concert_tab, text="  🎪 Concerts  ")
        self._concert_dashboard = concert_tab

        # Tab 5: Reflection Analytics
        from ui.lesson_plan_extras import ReflectionAnalytics
        analytics_tab = ReflectionAnalytics(self._notebook, self.db)
        self._notebook.add(analytics_tab, text="  📊 Analytics  ")
        self._analytics = analytics_tab

        # Refresh active tab when switching
        self._notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

    def _build_resource_placeholder(self, parent):
        """Placeholder for the Resource Library tab (Phase 5)."""
        frame = ttk.Frame(parent)
        frame.place(relx=0.5, rely=0.5, anchor="center")

        ttk.Label(
            frame,
            text="📚",
            font=("Segoe UI", fs(40)),
        ).pack(pady=(0, 10))

        ttk.Label(
            frame,
            text="Resource Library",
            font=("Segoe UI", fs(16), "bold"),
        ).pack()

        ttk.Label(
            frame,
            text="Link OneNote pages, OneDrive folders, websites, method book\n"
                 "references, and other teaching resources here.\n\n"
                 "Coming in a future update.",
            font=("Segoe UI", fs(10)),
            foreground=muted_fg(),
            justify="center",
        ).pack(pady=(8, 0))

    def _on_tab_changed(self, event):
        """Refresh the active tab's data when switching to it."""
        tab_index = self._notebook.index(self._notebook.select())
        if tab_index == 0:
            self._curriculum_planner.refresh()
        elif tab_index == 1:
            self._class_manager.refresh()
        elif tab_index == 2:
            self._resource_library.refresh()
        elif tab_index == 3:
            self._concert_dashboard.refresh()
        elif tab_index == 4:
            self._analytics.refresh()

    def _open_lesson_plan(self, class_id: int, date_str: str):
        """Called when user double-clicks a date in the Curriculum Planner.
        Opens the Lesson Plan Editor for that day.
        """
        from ttkbootstrap.dialogs import Messagebox

        # If no curriculum item exists, offer to create one first
        item = self.db.get_curriculum_item_by_date(class_id, date_str)
        if not item:
            result = Messagebox.yesno(
                f"No curriculum item exists for {date_str}.\n\n"
                "Would you like to create one?",
                title="Create Curriculum Item",
                parent=self.winfo_toplevel(),
            )
            if result == "Yes":
                self.db.add_curriculum_item({
                    "class_id": class_id,
                    "item_date": date_str,
                    "summary": "New topic",
                    "activity_type": "skill_building",
                    "unit_name": "",
                    "is_locked": 0,
                    "sort_order": 0,
                    "notes": "",
                })
                self._curriculum_planner.refresh()
            else:
                return

        # Open the Lesson Plan Editor
        from ui.lesson_plan_editor import LessonPlanEditor
        editor = LessonPlanEditor(
            self.winfo_toplevel(), self.db, class_id, date_str,
            on_save=lambda: self._curriculum_planner.refresh(),
        )
