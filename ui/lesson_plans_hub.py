"""
ui/lesson_plans_hub.py - Lesson Plans hub with tabbed navigation.

Central entry point for the Lesson Plans feature, providing a Notebook
with tabs for Class Manager, Curriculum Planner, and (future) Resource Library.
"""

import os
import tkinter as tk
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from ui.theme import muted_fg, fs


class LessonPlansHub(ttk.Frame):
    """Tabbed hub for all Lesson Plans functionality."""

    def __init__(self, parent, db):
        super().__init__(parent)
        self.main_db = db  # instruments, students, music
        self._base_dir = os.path.dirname(os.path.abspath(db.db_path))

        # Initialize lesson plan database for current school year
        from lesson_plan_db import (
            get_lesson_plan_db, current_school_year,
            list_available_school_years, migrate_from_main_db,
        )

        # One-time migration from main DB if needed
        migrated = migrate_from_main_db(db.db_path, self._base_dir)
        if migrated:
            self._current_year = migrated
        else:
            self._current_year = current_school_year()

        self.db = get_lesson_plan_db(self._base_dir, self._current_year)
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
        self._year_combo.bind("<<ComboboxSelected>>", lambda e: self._switch_school_year())

        # OneNote buttons (right side of header)
        btn_frame = ttk.Frame(header, bootstyle=PRIMARY)
        btn_frame.pack(side=RIGHT, padx=16, pady=8)

        self._onenote_sync_btn = ttk.Button(
            btn_frame,
            text="OneNote Sync",
            bootstyle=INFO,
            command=self._onenote_sync,
            width=14,
        )
        self._onenote_sync_btn.pack(side=RIGHT, padx=(4, 0))

        self._onenote_btn = ttk.Button(
            btn_frame,
            text="OneNote",
            bootstyle=LIGHT,
            command=self._open_onenote_dialog,
            width=10,
        )
        self._onenote_btn.pack(side=RIGHT, padx=(0, 4))

        # ── Notebook ─────────────────────────────────────────────────────────
        self._notebook = ttk.Notebook(self, bootstyle=PRIMARY)
        self._notebook.pack(fill=BOTH, expand=True)

        # Tab 1: Curriculum Planner (main view — calendar + toolbar)
        from ui.curriculum_planner import CurriculumPlanner
        curriculum_tab = CurriculumPlanner(
            self._notebook, self.db,
            on_open_lesson_plan=self._open_lesson_plan,
            on_class_changed=self._on_class_selection_changed,
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

        # Restore last selected class and update button states
        last_class = self._load_last_class()
        if last_class:
            self._curriculum_planner.select_class_by_id(last_class)
        self._on_class_selection_changed(self._curriculum_planner._selected_class_id)

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

    def _on_class_selection_changed(self, class_id):
        """Called when the class dropdown changes in the curriculum planner."""
        # Enable/disable OneNote buttons based on whether a specific class is selected
        if class_id:
            self._onenote_btn.config(state=NORMAL)
            self._onenote_sync_btn.config(state=NORMAL)
        else:
            self._onenote_btn.config(state=DISABLED)
            self._onenote_sync_btn.config(state=DISABLED)

        # Save last selected class to settings
        self._save_last_class(class_id)

    def _save_last_class(self, class_id):
        """Persist the last selected class ID to settings."""
        try:
            import json
            settings_path = os.path.join(self._get_base_dir(), "settings.json")
            settings = {}
            if os.path.exists(settings_path):
                with open(settings_path, "r") as f:
                    settings = json.load(f)
            if "lesson_plans" not in settings:
                settings["lesson_plans"] = {}
            settings["lesson_plans"]["last_class_id"] = class_id
            with open(settings_path, "w") as f:
                json.dump(settings, f, indent=2)
        except Exception:
            pass  # non-critical

    def _load_last_class(self) -> int:
        """Load the last selected class ID from settings."""
        try:
            import json
            settings_path = os.path.join(self._get_base_dir(), "settings.json")
            if os.path.exists(settings_path):
                with open(settings_path, "r") as f:
                    settings = json.load(f)
                return (settings.get("lesson_plans") or {}).get("last_class_id")
        except Exception:
            pass
        return None

    def _get_base_dir(self):
        """Get base_dir for settings access."""
        return self._base_dir

    def _populate_year_selector(self):
        """Populate the school year dropdown."""
        from lesson_plan_db import list_available_school_years, current_school_year
        years = list_available_school_years(self._base_dir)
        cur = current_school_year()
        if cur not in years:
            years.insert(0, cur)
        years.sort(reverse=True)
        self._year_combo.config(values=years)
        self._year_combo.set(self._current_year)

    def _switch_school_year(self):
        """Switch to a different school year's database."""
        new_year = self._year_var.get()
        if new_year == self._current_year:
            return

        from lesson_plan_db import get_lesson_plan_db
        self._current_year = new_year
        self.db = get_lesson_plan_db(self._base_dir, new_year)

        # Update all tabs to use the new DB
        self._curriculum_planner.db = self.db
        self._curriculum_planner.refresh()
        self._class_manager.db = self.db
        self._class_manager.refresh()
        self._resource_library.db = self.db
        self._resource_library.refresh()
        self._concert_dashboard.db = self.db
        self._concert_dashboard.refresh()
        self._analytics.db = self.db
        self._analytics.refresh()

    def _open_onenote_dialog(self):
        """Open the OneNote integration dialog (Import/Export/Sync settings)."""
        from ui.onenote_dialog import OneNoteDialog

        # Pass the currently selected class if any
        selected_class = None
        if hasattr(self, '_curriculum_planner'):
            selected_class = self._curriculum_planner._selected_class_id

        dialog = OneNoteDialog(
            self.winfo_toplevel(), self.db,
            base_dir=self._get_base_dir(),
            selected_class_id=selected_class,
        )

    def _onenote_sync(self):
        """Trigger a OneNote sync for all enabled sync configurations."""
        from ttkbootstrap.dialogs import Messagebox

        # Get all active syncs
        syncs = self.db.get_all_onenote_syncs()
        if not syncs:
            Messagebox.show_info(
                "No sync configurations found.\n\n"
                "Click 'OneNote' to set up sync in the 'Stay Sync'd' tab.",
                title="No Sync Configured", parent=self.winfo_toplevel(),
            )
            return

        # Ask user which direction to sync
        try:
            from onenote_client import create_client_from_settings
            client = create_client_from_settings(self._get_base_dir())
            client.authenticate(on_status=lambda msg: None)
        except Exception as e:
            Messagebox.show_error(
                f"Could not connect to OneNote:\n{e}",
                title="Connection Error", parent=self.winfo_toplevel(),
            )
            return

        # Build sync summary
        sync_names = [s.get("class_name", "Unknown") for s in syncs]
        summary = "\n".join(f"  - {name}" for name in sync_names)

        result = Messagebox.yesno(
            f"Sync with OneNote?\n\n"
            f"Classes configured for sync:\n{summary}\n\n"
            f"Choose sync direction on next screen.",
            title="OneNote Sync", parent=self.winfo_toplevel(),
        )
        if result != "Yes":
            return

        # Ask direction
        dir_dlg = tk.Toplevel(self.winfo_toplevel())
        dir_dlg.title("Sync Direction")
        dir_dlg.transient(self.winfo_toplevel())
        dir_dlg.grab_set()

        ttk.Label(
            dir_dlg,
            text="Which direction should data flow?",
            font=("Segoe UI", fs(11), "bold"),
        ).pack(padx=20, pady=(16, 8))

        direction = [None]

        def _pick(d):
            direction[0] = d
            dir_dlg.destroy()

        btn_frame = ttk.Frame(dir_dlg)
        btn_frame.pack(padx=20, pady=(0, 16))

        ttk.Button(
            btn_frame,
            text="App → OneNote\n(Push app data to OneNote)",
            bootstyle=PRIMARY, width=30,
            command=lambda: _pick("app_to_onenote"),
        ).pack(pady=4)

        ttk.Button(
            btn_frame,
            text="OneNote → App\n(Pull OneNote data into app)",
            bootstyle=INFO, width=30,
            command=lambda: _pick("onenote_to_app"),
        ).pack(pady=4)

        ttk.Button(
            btn_frame, text="Cancel", bootstyle=SECONDARY,
            command=dir_dlg.destroy, width=15,
        ).pack(pady=(8, 0))

        # Center the dialog
        dir_dlg.update_idletasks()
        pw = self.winfo_toplevel()
        x = pw.winfo_x() + (pw.winfo_width() - 350) // 2
        y = pw.winfo_y() + (pw.winfo_height() - 250) // 2
        dir_dlg.geometry(f"350x250+{max(0,x)}+{max(0,y)}")

        dir_dlg.wait_window()

        if not direction[0]:
            return

        # Perform sync for each configured class
        total_synced = 0
        total_errors = []

        for sync_config in syncs:
            class_name = sync_config.get("class_name", "Unknown")
            try:
                result = client.sync_with_onenote(
                    self.db, dict(sync_config), direction[0],
                )
                total_synced += result.get("synced", 0)
                total_errors.extend(result.get("errors", []))
                # Update timestamp
                self.db.update_sync_timestamp(sync_config["id"])
            except Exception as e:
                total_errors.append(f"{class_name}: {e}")

        # Show result
        msg = f"Sync complete!\n\nItems synced: {total_synced}"
        if total_errors:
            msg += f"\n\nErrors ({len(total_errors)}):\n"
            msg += "\n".join(f"  - {e}" for e in total_errors[:5])
        Messagebox.show_info(msg, title="Sync Complete", parent=self.winfo_toplevel())
        self._curriculum_planner.refresh()
