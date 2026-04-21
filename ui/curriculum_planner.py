"""
ui/curriculum_planner.py - Curriculum Planner view for managing lesson schedules.

A professional curriculum planning interface wrapping CalendarView with class filtering,
navigation controls, and calendar manipulation operations (shift, move, swap, copy, etc).
"""

import os
import tkinter as tk
from tkinter import filedialog, simpledialog
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from ttkbootstrap.dialogs import Messagebox
from datetime import datetime, timedelta

from ui.theme import muted_fg, subtle_fg, fg, fs, is_dark
from ui.calendar_widget import CalendarView
from lesson_plan_importer import import_from_file


class CurriculumPlanner(ttk.Frame):
    """Main curriculum planning view with calendar, toolbar, and class filter."""

    def __init__(self, parent, db, on_open_lesson_plan=None, on_class_changed=None):
        """
        Initialize CurriculumPlanner.

        Args:
            parent: Parent tkinter widget
            db: Database instance
            on_open_lesson_plan: Callable(class_id, date_str) fired on double-click
            on_class_changed: Callable(class_id) fired when class selection changes
        """
        super().__init__(parent)
        self.db = db
        self.on_open_lesson_plan = on_open_lesson_plan
        self.on_class_changed = on_class_changed

        # State
        self._class_id_map = {}  # {"All Classes": None, "Band": 1, ...}
        self._selected_class_id = None
        self._selected_date = None
        self._swap_mode = False
        self._swap_date_1 = None

        # UI refs
        self._class_combo = None
        self._calendar = None
        self._nav_title_label = None
        self._status_label = None
        self._status_right_label = None

        self._build()
        self.refresh()

    def _build(self):
        """Build the UI layout — compact single toolbar with dropdown menus."""
        # ──────────────────────────── Single Toolbar Row ──────────────────────
        toolbar = ttk.Frame(self, bootstyle=LIGHT)
        toolbar.pack(fill=X, padx=4, pady=2)

        # Class filter
        ttk.Label(toolbar, text="Class:", font=("Segoe UI", fs(9))).pack(
            side=LEFT, padx=(4, 2))
        self._class_combo = ttk.Combobox(toolbar, state="readonly", width=18)
        self._class_combo.pack(side=LEFT, padx=(0, 8))
        self._class_combo.bind("<<ComboboxSelected>>",
                               lambda e: self._on_class_changed())

        # Navigation: ◀ Title ▶ Today
        ttk.Button(toolbar, text="◀", width=2,
                   command=self._on_prev).pack(side=LEFT, padx=1)
        self._nav_title_label = ttk.Label(
            toolbar, text="", font=("Segoe UI", fs(10), "bold"))
        self._nav_title_label.pack(side=LEFT, padx=6)
        ttk.Button(toolbar, text="▶", width=2,
                   command=self._on_next).pack(side=LEFT, padx=1)
        ttk.Button(toolbar, text="Today", bootstyle=PRIMARY,
                   command=self._on_today).pack(side=LEFT, padx=(4, 8))

        # View mode: Month | Week | Year (no fixed width — auto-size to text)
        self._month_btn = ttk.Button(
            toolbar, text="Month", bootstyle=SECONDARY,
            command=lambda: self._set_view_mode("month"))
        self._month_btn.pack(side=LEFT, padx=1)
        self._week_btn = ttk.Button(
            toolbar, text="Week", bootstyle=(SECONDARY, OUTLINE),
            command=lambda: self._set_view_mode("week"))
        self._week_btn.pack(side=LEFT, padx=1)
        self._year_btn = ttk.Button(
            toolbar, text="Year", bootstyle=(SECONDARY, OUTLINE),
            command=lambda: self._set_view_mode("year"))
        self._year_btn.pack(side=LEFT, padx=(1, 8))

        # ── Edit dropdown (replaces 8 separate buttons) ──
        edit_btn = ttk.Menubutton(toolbar, text="Edit ▾", bootstyle=INFO)
        edit_btn.pack(side=LEFT, padx=2)
        edit_menu = tk.Menu(edit_btn, tearoff=False)
        edit_btn.config(menu=edit_menu)
        edit_menu.add_command(label="Move To...", command=self._move_to)
        edit_menu.add_command(label="Shift Forward...", command=self._shift_forward)
        edit_menu.add_command(label="Shift Back...", command=self._shift_backward)
        edit_menu.add_command(label="Swap Dates", command=self._swap_dates)
        edit_menu.add_separator()
        edit_menu.add_command(label="Insert Blank Day", command=self._insert_day)
        edit_menu.add_command(label="Remove Day", command=self._remove_day)
        edit_menu.add_command(label="Copy Day...", command=self._copy_day)
        edit_menu.add_separator()
        edit_menu.add_command(label="Lock/Unlock", command=self._toggle_lock)

        # Import and AI buttons (kept visible — used frequently)
        ttk.Button(toolbar, text="Import", bootstyle=(INFO, OUTLINE),
                   command=self._import_curriculum).pack(side=LEFT, padx=2)
        ttk.Button(toolbar, text="AI Generate", bootstyle=(SUCCESS, OUTLINE),
                   command=self._ai_generate).pack(side=LEFT, padx=2)

        # Status info (right side of toolbar)
        self._status_label = ttk.Label(
            toolbar, text="", foreground=subtle_fg(),
            font=("Segoe UI", fs(8)))
        self._status_label.pack(side=RIGHT, padx=4)

        # ──────────────────────────── Calendar Area ────────────────────────────
        calendar_frame = ttk.Frame(self)
        calendar_frame.pack(fill=BOTH, expand=True, padx=4, pady=(0, 2))

        self._calendar = CalendarView(calendar_frame)
        self._calendar.pack(fill=BOTH, expand=True)
        self._calendar.set_on_date_click(self._on_date_clicked)
        self._calendar.set_on_date_double_click(self._on_date_double_clicked)

        # Selected date info bar (thin, below calendar)
        self._status_right_label = ttk.Label(
            self, text="", foreground=muted_fg(),
            font=("Segoe UI", fs(8)))
        self._status_right_label.pack(fill=X, padx=8, pady=(0, 2))

    # ═══════════════════════════════════ Public Methods ═════════════════════

    def refresh(self):
        """Reload classes dropdown and curriculum items."""
        self._populate_class_combo()
        self._load_calendar_items()
        self._update_status_bar()

    # ═════════════════════════════════════ Navigation ═════════════════════════

    def _on_prev(self):
        """Navigate to previous period."""
        self._calendar.prev_period()
        self._update_nav_title()

    def _on_next(self):
        """Navigate to next period."""
        self._calendar.next_period()
        self._update_nav_title()

    def _on_today(self):
        """Navigate to today."""
        self._calendar.set_date(datetime.now())
        self._update_nav_title()

    def _set_view_mode(self, mode: str):
        """Switch calendar view mode (month, week, year)."""
        self._calendar.set_mode(mode)
        self._update_nav_title()
        self._update_view_buttons()

    def _update_nav_title(self):
        """Update navigation title label."""
        title = self._calendar.get_title()
        self._nav_title_label.config(text=title)

    def _update_view_buttons(self):
        """Update view mode button states."""
        mode = self._calendar._mode
        for btn, m in [
            (self._month_btn, "month"),
            (self._week_btn, "week"),
            (self._year_btn, "year"),
        ]:
            if m == mode:
                btn.config(bootstyle=SECONDARY)
            else:
                btn.config(bootstyle=(SECONDARY, OUTLINE))

    # ════════════════════════════════════ Class Filter ═══════════════════════

    def _populate_class_combo(self):
        """Load classes into the dropdown, preserving current selection."""
        # Remember current selection
        prev_selection = self._class_combo.get() if self._class_combo else ""

        self._class_id_map = {"All Classes": None}
        classes = self.db.get_all_classes()
        for cls in classes:
            name = cls["class_name"]
            self._class_id_map[name] = cls["id"]

        self._class_combo.config(values=list(self._class_id_map.keys()))

        # Restore previous selection if it still exists, otherwise default
        if prev_selection and prev_selection in self._class_id_map:
            self._class_combo.set(prev_selection)
            self._selected_class_id = self._class_id_map[prev_selection]
        else:
            self._class_combo.set("All Classes")
            self._selected_class_id = None

    def _on_class_changed(self):
        """Handle class filter change."""
        selected = self._class_combo.get()
        self._selected_class_id = self._class_id_map.get(selected)
        self._load_calendar_items()
        self._update_status_bar()
        # Notify parent (hub) about the change
        if self.on_class_changed:
            self.on_class_changed(self._selected_class_id)

    def select_class_by_id(self, class_id: int):
        """Programmatically select a class by its ID (used for restoring last selection)."""
        for name, cid in self._class_id_map.items():
            if cid == class_id:
                self._class_combo.set(name)
                self._selected_class_id = cid
                self._load_calendar_items()
                self._update_status_bar()
                return True
        return False

    # ════════════════════════════════════ Calendar Items ═════════════════════

    def _load_calendar_items(self):
        """Query DB and populate calendar with curriculum items and concerts."""
        items_dict = {}

        # Load curriculum items
        if self._selected_class_id is None:
            # "All Classes" mode: load all curriculum items
            all_classes = self.db.get_all_classes()
            for cls in all_classes:
                curr_items = self.db.get_curriculum_items(cls["id"])
                for item in curr_items:
                    date_str = item["item_date"]
                    if date_str not in items_dict:
                        items_dict[date_str] = []
                    items_dict[date_str].append({
                        "summary": item["summary"] or "Untitled",
                        "activity_type": item["activity_type"] or "skill_building",
                        "is_locked": bool(item.get("is_locked")),
                        "item_id": item["id"],
                    })
        else:
            # Single class mode
            curr_items = self.db.get_curriculum_items(self._selected_class_id)
            for item in curr_items:
                date_str = item["item_date"]
                if date_str not in items_dict:
                    items_dict[date_str] = []
                items_dict[date_str].append({
                    "summary": item["summary"] or "Untitled",
                    "activity_type": item["activity_type"] or "skill_building",
                    "is_locked": bool(item.get("is_locked")),
                    "item_id": item["id"],
                })

        # Add concert dates
        if self._selected_class_id is None:
            all_concerts = self.db.get_concert_dates()
        else:
            all_concerts = self.db.get_concert_dates(self._selected_class_id)

        for concert in all_concerts:
            date_str = concert["concert_date"]
            if date_str not in items_dict:
                items_dict[date_str] = []
            items_dict[date_str].insert(0, {
                "summary": concert.get("event_name") or "Concert",
                "activity_type": "concert",
                "is_locked": True,
                "concert_id": concert["id"],
            })

        self._calendar.set_items(items_dict)

    def _on_date_clicked(self, date_str: str):
        """Handle single click on a date."""
        self._selected_date = date_str

        # If in swap mode, perform the swap with this second date
        if self._swap_mode and self._swap_date_1:
            if date_str == self._swap_date_1:
                Messagebox.show_warning(
                    "Cannot swap a date with itself.",
                    title="Swap", parent=self.winfo_toplevel(),
                )
                self._swap_mode = False
                self._swap_date_1 = None
                self._update_status_bar()
                return

            item_a = self.db.get_curriculum_item_by_date(
                self._selected_class_id, self._swap_date_1
            )
            item_b = self.db.get_curriculum_item_by_date(
                self._selected_class_id, date_str
            )

            if not item_a or not item_b:
                Messagebox.show_warning(
                    "Cannot swap: one or both dates have no curriculum items.",
                    title="Swap Error", parent=self.winfo_toplevel(),
                )
            else:
                # Get class name for the confirmation message
                cls = self.db.get_class(self._selected_class_id)
                class_name = cls.get("class_name", "this class") if cls else "this class"
                date1_display = datetime.strptime(self._swap_date_1, "%Y-%m-%d").strftime("%a %b %d")
                date2_display = datetime.strptime(date_str, "%Y-%m-%d").strftime("%a %b %d")

                confirm = Messagebox.yesno(
                    f"Swap the curriculum for {class_name}?\n\n"
                    f"  {date1_display}: {item_a.get('summary', '')[:60]}\n"
                    f"  {date2_display}: {item_b.get('summary', '')[:60]}\n\n"
                    f"The topics for these two days will be exchanged.",
                    title="Confirm Swap", parent=self.winfo_toplevel(),
                )
                if confirm == "Yes":
                    try:
                        self.db.swap_curriculum_items(item_a["id"], item_b["id"])
                    except Exception as e:
                        Messagebox.show_error(
                            str(e), title="Error", parent=self.winfo_toplevel(),
                        )

            self._swap_mode = False
            self._swap_date_1 = None
            self.refresh()
            return

        self._update_status_bar()

    def _on_date_double_clicked(self, date_str: str):
        """Handle double click on a date (open lesson plan editor)."""
        self._selected_date = date_str
        if not self.on_open_lesson_plan:
            return

        class_id = self._selected_class_id
        if not class_id:
            # "All Classes" mode — find the first class with an item on this date
            all_classes = self.db.get_all_classes()
            for cls in all_classes:
                item = self.db.get_curriculum_item_by_date(cls["id"], date_str)
                if item:
                    class_id = cls["id"]
                    break
            if not class_id:
                from ttkbootstrap.dialogs import Messagebox
                Messagebox.show_warning(
                    "No curriculum item on this date. Select a specific class to create one.",
                    title="No Item", parent=self,
                )
                return

        self.on_open_lesson_plan(class_id, date_str)

    def _update_status_bar(self):
        """Update status bar with stats and selected date info."""
        # Left side: counts
        if self._selected_class_id is None:
            all_classes = self.db.get_all_classes()
            total_items = sum(
                len(self.db.get_curriculum_items(cls["id"])) for cls in all_classes
            )
        else:
            total_items = len(self.db.get_curriculum_items(self._selected_class_id))

        total_concerts = len(
            self.db.get_concert_dates(self._selected_class_id)
            if self._selected_class_id else self.db.get_concert_dates()
        )

        # Count lesson plans (non-null content)
        lesson_plans = 0
        if self._selected_class_id is None:
            all_classes = self.db.get_all_classes()
            for cls in all_classes:
                items = self.db.get_curriculum_items(cls["id"])
                for item in items:
                    plan = self.db.get_lesson_plan_by_curriculum_item(item["id"])
                    if plan and plan.get("content"):
                        lesson_plans += 1
        else:
            items = self.db.get_curriculum_items(self._selected_class_id)
            for item in items:
                plan = self.db.get_lesson_plan_by_curriculum_item(item["id"])
                if plan and plan.get("content"):
                    lesson_plans += 1

        status_text = f"{total_items} curriculum items · {lesson_plans} lesson plans · {total_concerts} concerts"
        self._status_label.config(text=status_text)

        # Right side: selected date info
        if self._swap_mode:
            right_text = f"Swap mode: Click another date to swap with {self._swap_date_1}"
        elif self._selected_date:
            day_name = datetime.strptime(self._selected_date, "%Y-%m-%d").strftime("%a %b %d, %Y")
            item = self.db.get_curriculum_item_by_date(
                self._selected_class_id, self._selected_date
            ) if self._selected_class_id else None
            if item:
                summary = item.get("summary") or "Untitled"
                right_text = f"Selected: {day_name} — {summary}"
            else:
                right_text = f"Selected: {day_name}"
        else:
            right_text = ""

        self._status_right_label.config(text=right_text)

    # ════════════════════════════ Toolbar Actions ════════════════════════════

    def _move_to(self):
        """Move selected date's agenda to a different date."""
        if not self._can_modify():
            return

        target_date = self._ask_date(
            "Move Agenda",
            "Target date (YYYY-MM-DD):"
        )
        if not target_date:
            return

        # Get curriculum item for selected date
        item = self.db.get_curriculum_item_by_date(
            self._selected_class_id, self._selected_date
        )
        if not item:
            Messagebox.show_warning("No curriculum item on this date.", title="No Item", parent=self.winfo_toplevel())
            return

        try:
            self.db.move_curriculum_item(item["id"], target_date)
            self.refresh()
            Messagebox.show_info(f"Moved to {target_date}.", title="Success", parent=self.winfo_toplevel())
        except Exception as e:
            Messagebox.show_error(str(e), title="Error", parent=self.winfo_toplevel())

    def _shift_forward(self):
        """Shift all items from selected date forward by N days."""
        if not self._can_modify():
            return

        days = self._ask_number("Shift Forward", "Number of days:", 1, 30, 1)
        if days is None:
            return

        try:
            self.db.shift_curriculum_items(
                self._selected_class_id, self._selected_date, days
            )
            self.refresh()
            Messagebox.show_info(f"Shifted forward {days} days.", title="Success", parent=self.winfo_toplevel())
        except Exception as e:
            Messagebox.show_error(str(e), title="Error", parent=self.winfo_toplevel())

    def _shift_backward(self):
        """Shift all items from selected date backward by N days."""
        if not self._can_modify():
            return

        days = self._ask_number("Shift Backward", "Number of days:", 1, 30, 1)
        if days is None:
            return

        try:
            self.db.shift_curriculum_items(
                self._selected_class_id, self._selected_date, -days
            )
            self.refresh()
            Messagebox.show_info(f"Shifted backward {days} days.", title="Success", parent=self.winfo_toplevel())
        except Exception as e:
            Messagebox.show_error(str(e), title="Error", parent=self.winfo_toplevel())

    def _swap_dates(self):
        """Toggle swap mode. First click stores the date, second click (on calendar) performs swap."""
        if not self._can_modify():
            return

        if self._swap_mode:
            # Already in swap mode — cancel it
            self._swap_mode = False
            self._swap_date_1 = None
            self._update_status_bar()
        else:
            # Enter swap mode — next calendar click will perform the swap
            self._swap_mode = True
            self._swap_date_1 = self._selected_date
            self._update_status_bar()

    def _insert_day(self):
        """Insert a blank curriculum item, shifting others forward."""
        if not self._can_modify():
            return

        try:
            self.db.add_curriculum_item({
                "class_id": self._selected_class_id,
                "item_date": self._selected_date,
                "summary": "",
                "activity_type": "skill_building",
                "is_locked": False,
            })
            self.refresh()
            Messagebox.show_info("Blank day inserted.", title="Success", parent=self.winfo_toplevel())
        except Exception as e:
            Messagebox.show_error(str(e), title="Error", parent=self.winfo_toplevel())

    def _remove_day(self):
        """Remove selected day's curriculum item."""
        if not self._can_modify():
            return

        item = self.db.get_curriculum_item_by_date(
            self._selected_class_id, self._selected_date
        )
        if not item:
            Messagebox.show_warning("No curriculum item on this date.", title="No Item", parent=self.winfo_toplevel())
            return

        if Messagebox.yesno("Delete this day's curriculum item?", title="Confirm Delete", parent=self.winfo_toplevel()):
            try:
                self.db.delete_curriculum_item(item["id"])
                self.refresh()
            except Exception as e:
                Messagebox.show_error(str(e), title="Error", parent=self.winfo_toplevel())

    def _copy_day(self):
        """Copy selected day's agenda to another date."""
        if not self._can_modify():
            return

        item = self.db.get_curriculum_item_by_date(
            self._selected_class_id, self._selected_date
        )
        if not item:
            Messagebox.show_warning("No curriculum item on this date.", title="No Item", parent=self.winfo_toplevel())
            return

        target_date = self._ask_date(
            "Copy Agenda",
            "Target date (YYYY-MM-DD):"
        )
        if not target_date:
            return

        try:
            self.db.add_curriculum_item({
                "class_id": self._selected_class_id,
                "item_date": target_date,
                "summary": item["summary"],
                "activity_type": item["activity_type"],
                "is_locked": item.get("is_locked", False),
            })
            self.refresh()
            Messagebox.show_info(f"Copied to {target_date}.", title="Success", parent=self.winfo_toplevel())
        except Exception as e:
            Messagebox.show_error(str(e), title="Error", parent=self.winfo_toplevel())

    def _toggle_lock(self):
        """Toggle lock status on selected date's item."""
        if not self._can_modify():
            return

        item = self.db.get_curriculum_item_by_date(
            self._selected_class_id, self._selected_date
        )
        if not item:
            Messagebox.show_warning("No curriculum item on this date.", title="No Item", parent=self.winfo_toplevel())
            return

        new_locked = 1 if not item.get("is_locked", 0) else 0
        try:
            update_data = {
                "class_id": item["class_id"],
                "item_date": item["item_date"],
                "summary": item["summary"],
                "activity_type": item["activity_type"],
                "unit_name": item.get("unit_name", ""),
                "is_locked": new_locked,
                "sort_order": item.get("sort_order", 0),
                "notes": item.get("notes", ""),
            }
            self.db.update_curriculum_item(item["id"], update_data)
            self.refresh()
            status = "locked" if new_locked else "unlocked"
            Messagebox.show_info(f"Item {status}.", title="Success", parent=self.winfo_toplevel())
        except Exception as e:
            Messagebox.show_error(str(e), title="Error", parent=self.winfo_toplevel())

    def _import_curriculum(self):
        """Import curriculum from a file."""
        file_path = filedialog.askopenfilename(
            parent=self.winfo_toplevel(),
            title="Import Curriculum",
            filetypes=[
                ("CSV", "*.csv"),
                ("Excel", "*.xlsx"),
                ("JSON", "*.json"),
                ("Text", "*.txt"),
                ("All Files", "*.*"),
            ],
        )
        if not file_path:
            return

        try:
            from lesson_plan_importer import import_from_file
            result = import_from_file(
                file_path,
                self.db,
                class_id=self._selected_class_id,
            )
            # Result is a dict with: imported, skipped, errors
            message = (
                f"Imported: {result.get('imported', 0)}\n"
                f"Skipped: {result.get('skipped', 0)}\n"
                f"Errors: {result.get('errors', 0)}"
            )
            Messagebox.show_info(message, title="Import Result", parent=self.winfo_toplevel())
            self.refresh()
        except Exception as e:
            Messagebox.show_error(str(e), title="Import Error", parent=self.winfo_toplevel())

    def _ai_generate(self):
        """Open AI curriculum generation dialog with reference materials support."""
        class_id = self._selected_class_id
        if not class_id:
            Messagebox.show_warning(
                "Please select a specific class (not 'All Classes') first.",
                title="No Class Selected", parent=self.winfo_toplevel(),
            )
            return

        cls = self.db.get_class(class_id)
        if not cls:
            return

        parent_win = self.winfo_toplevel()
        dlg = ttk.Toplevel(parent_win)
        dlg.title("AI Curriculum Generator")
        dlg.transient(parent_win)
        dlg.grab_set()

        # ── Header ──
        ttk.Label(dlg, text=f"Generate curriculum for: {cls['class_name']}",
                  font=("Segoe UI", fs(12), "bold")).pack(padx=16, pady=(16, 4))

        # ── Scrollable content ──
        canvas = tk.Canvas(dlg, highlightthickness=0)
        scrollbar = ttk.Scrollbar(dlg, orient=VERTICAL, command=canvas.yview)
        scroll_frame = ttk.Frame(canvas)
        scroll_frame.bind("<Configure>",
                          lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scroll_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=RIGHT, fill=Y)
        canvas.pack(fill=BOTH, expand=True, padx=16, pady=4)

        form = scroll_frame

        # ── Date Range ──
        ttk.Label(form, text="Date Range", font=("Segoe UI", fs(10), "bold")).pack(
            anchor=W, pady=(8, 4))
        date_row = ttk.Frame(form)
        date_row.pack(fill=X, pady=2)

        sy = cls.get("school_year", "2025-2026") or "2025-2026"
        sy_start = sy[:4]

        ttk.Label(date_row, text="Start:").pack(side=LEFT, padx=(0, 4))
        start_var = tk.StringVar(value=f"{sy_start}-09-03")
        ttk.Entry(date_row, textvariable=start_var, width=12).pack(side=LEFT, padx=(0, 16))
        ttk.Label(date_row, text="End:").pack(side=LEFT, padx=(0, 4))
        end_var = tk.StringVar(value=f"{int(sy_start)+1}-06-15")
        ttk.Entry(date_row, textvariable=end_var, width=12).pack(side=LEFT)

        # ── Approach ──
        ttk.Label(form, text="Approach", font=("Segoe UI", fs(10), "bold")).pack(
            anchor=W, pady=(12, 4))
        approach_var = tk.StringVar(value="from_scratch")
        for val, label, desc in [
            ("from_scratch", "From Scratch",
             "AI builds curriculum using class info, method book, and concert dates"),
            ("from_previous", "From Previous Data",
             "AI improves on existing curriculum items and teacher reflections"),
            ("hybrid", "Hybrid",
             "AI fills gaps in your partial plan and improves existing items"),
        ]:
            rb_frame = ttk.Frame(form)
            rb_frame.pack(fill=X, pady=1)
            ttk.Radiobutton(rb_frame, text=label, variable=approach_var,
                            value=val).pack(side=LEFT)
            ttk.Label(rb_frame, text=f"  {desc}", foreground=muted_fg(),
                      font=("Segoe UI", fs(8))).pack(side=LEFT)

        # ── Reference Materials ──
        ttk.Label(form, text="Reference Materials (optional)",
                  font=("Segoe UI", fs(10), "bold")).pack(anchor=W, pady=(12, 4))
        ttk.Label(form,
                  text="Add files or folders for the AI to use as context — last year's plans,\n"
                       "worksheets, sheet music, syllabi, or any teaching materials.",
                  foreground=muted_fg(), font=("Segoe UI", fs(8))).pack(anchor=W, pady=(0, 4))

        ref_paths = []  # mutable list shared with closures

        ref_listbox = tk.Listbox(form, height=4, font=("Segoe UI", fs(9)))
        ref_listbox.pack(fill=X, pady=4)

        ref_btn_row = ttk.Frame(form)
        ref_btn_row.pack(fill=X, pady=2)

        def _add_file():
            path = filedialog.askopenfilename(
                parent=dlg, title="Select Reference File",
                filetypes=[
                    ("All Supported", "*.csv *.txt *.md *.pdf *.json *.xml *.html"),
                    ("CSV", "*.csv"), ("Text", "*.txt *.md"),
                    ("PDF", "*.pdf"), ("All Files", "*.*"),
                ],
            )
            if path and path not in ref_paths:
                ref_paths.append(path)
                ref_listbox.insert("end", os.path.basename(path))

        def _add_folder():
            path = filedialog.askdirectory(parent=dlg, title="Select Reference Folder")
            if path and path not in ref_paths:
                ref_paths.append(path)
                folder_name = os.path.basename(path) or path
                ref_listbox.insert("end", f"[Folder] {folder_name}")

        def _remove_selected():
            sel = ref_listbox.curselection()
            if sel:
                idx = sel[0]
                ref_listbox.delete(idx)
                ref_paths.pop(idx)

        ttk.Button(ref_btn_row, text="Add File...", bootstyle=INFO,
                   command=_add_file).pack(side=LEFT, padx=2)
        ttk.Button(ref_btn_row, text="Add Folder...", bootstyle=INFO,
                   command=_add_folder).pack(side=LEFT, padx=2)
        ttk.Button(ref_btn_row, text="Remove", bootstyle=(DANGER, OUTLINE),
                   command=_remove_selected).pack(side=LEFT, padx=2)

        # ── Special Instructions ──
        ttk.Label(form, text="Special Instructions (optional)",
                  font=("Segoe UI", fs(10), "bold")).pack(anchor=W, pady=(12, 4))
        instructions = tk.Text(form, height=3, width=50, font=("Segoe UI", fs(9)))
        instructions.pack(fill=X, pady=4)

        # ── Status ──
        status_var = tk.StringVar(value="Ready to generate")
        ttk.Label(dlg, textvariable=status_var, foreground=muted_fg()).pack(padx=16, pady=4)

        # ── Generate handler ──
        def _do_generate():
            from lesson_plan_ai import generate_curriculum
            import json as _json
            status_var.set("Generating... (this may take a minute)")
            dlg.update_idletasks()

            base_dir = self._get_base_dir()
            result = generate_curriculum(
                base_dir=base_dir, db=self.db, class_id=class_id,
                start_date=start_var.get(), end_date=end_var.get(),
                days_of_week=cls.get("days_of_week", "M,T,W,Th,F"),
                approach=approach_var.get(),
                additional_instructions=instructions.get("1.0", "end").strip(),
                reference_paths=ref_paths if ref_paths else None,
                on_status=lambda msg: (status_var.set(msg), dlg.update_idletasks()),
            )
            if result.get("error"):
                status_var.set("Error!")
                Messagebox.show_error(result["error"], title="AI Error", parent=dlg)
                return
            items = result.get("items", [])
            if not items:
                status_var.set("AI returned no items")
                return
            confirm = Messagebox.yesno(
                f"AI generated {len(items)} curriculum items.\nImport them?",
                title="Confirm Import", parent=dlg,
            )
            if confirm == "Yes":
                from lesson_plan_importer import import_curriculum_from_llm_response
                json_str = _json.dumps(items, default=str)
                import_curriculum_from_llm_response(
                    self.db, json_str, class_id,
                    start_date=start_var.get(),
                    days_of_week=cls.get("days_of_week", "M,T,W,Th,F"),
                )
                status_var.set(f"Imported {len(items)} items!")
                self.refresh()
                dlg.after(1500, dlg.destroy)

        # ── Buttons ──
        btn_frame = ttk.Frame(dlg)
        btn_frame.pack(pady=(4, 12))
        ttk.Button(btn_frame, text="Generate Curriculum", bootstyle=SUCCESS,
                   command=_do_generate).pack(side=LEFT, padx=8)
        ttk.Button(btn_frame, text="Cancel", bootstyle=SECONDARY,
                   command=dlg.destroy).pack(side=LEFT, padx=8)

        self._center_dialog(dlg, 600, 580)

    def _get_base_dir(self):
        """Get base_dir for LLM client access."""
        import os
        return os.path.dirname(os.path.abspath(self.db.db_path))

    # ════════════════════════════ Dialog Helpers ════════════════════════════

    def _center_dialog(self, dialog, w, h):
        """Center a dialog relative to the parent Toplevel."""
        parent = self.winfo_toplevel()
        px = parent.winfo_x() + (parent.winfo_width() - w) // 2
        py = parent.winfo_y() + (parent.winfo_height() - h) // 2
        dialog.geometry(f"{w}x{h}+{max(0,px)}+{max(0,py)}")

    def _ask_date(self, title: str, prompt: str) -> str:
        """Show dialog for entering a date string.

        Returns:
            Date string (YYYY-MM-DD) or None if cancelled
        """
        parent_win = self.winfo_toplevel()
        dialog = tk.Toplevel(parent_win)
        dialog.title(title)
        dialog.transient(parent_win)
        dialog.resizable(True, True)
        self._center_dialog(dialog, 350, 160)
        dialog.grab_set()

        ttk.Label(dialog, text=prompt, font=("Segoe UI", fs(10))).pack(
            padx=16, pady=(16, 8))
        entry = ttk.Entry(dialog, width=20, font=("Segoe UI", fs(10)))
        entry.pack(padx=16, pady=(0, 8))
        entry.insert(0, "YYYY-MM-DD")
        entry.select_range(0, "end")
        entry.focus_set()

        result = [None]

        def on_ok(event=None):
            text = entry.get().strip()
            if text and text != "YYYY-MM-DD":
                try:
                    datetime.strptime(text, "%Y-%m-%d")
                    result[0] = text
                    dialog.destroy()
                except ValueError:
                    Messagebox.show_warning(
                        "Please use YYYY-MM-DD format.",
                        title="Invalid Date", parent=dialog,
                    )
            else:
                dialog.destroy()

        entry.bind("<Return>", on_ok)

        btn_frame = ttk.Frame(dialog)
        btn_frame.pack(pady=(8, 16))
        ttk.Button(btn_frame, text="OK", bootstyle=PRIMARY,
                   command=on_ok, width=10).pack(side=LEFT, padx=6)
        ttk.Button(btn_frame, text="Cancel", bootstyle=SECONDARY,
                   command=dialog.destroy, width=10).pack(side=LEFT, padx=6)

        dialog.wait_window()
        return result[0]

    def _ask_number(
        self, title: str, prompt: str, min_val: int, max_val: int, default: int
    ) -> int:
        """Show dialog for entering a number.

        Returns:
            Integer value or None if cancelled
        """
        parent_win = self.winfo_toplevel()
        dialog = tk.Toplevel(parent_win)
        dialog.title(title)
        dialog.transient(parent_win)
        dialog.resizable(True, True)
        self._center_dialog(dialog, 350, 170)
        dialog.grab_set()

        ttk.Label(dialog, text=prompt, font=("Segoe UI", fs(10))).pack(
            padx=16, pady=(16, 8))
        spinbox = ttk.Spinbox(
            dialog, from_=min_val, to=max_val, width=10,
            font=("Segoe UI", fs(10)),
        )
        spinbox.set(default)
        spinbox.pack(padx=16, pady=(0, 8))
        spinbox.focus_set()

        result = [None]

        def on_ok(event=None):
            try:
                val = int(spinbox.get())
                if min_val <= val <= max_val:
                    result[0] = val
                    dialog.destroy()
            except ValueError:
                pass

        spinbox.bind("<Return>", on_ok)

        btn_frame = ttk.Frame(dialog)
        btn_frame.pack(pady=(8, 16))
        ttk.Button(btn_frame, text="OK", bootstyle=PRIMARY,
                   command=on_ok, width=10).pack(side=LEFT, padx=6)
        ttk.Button(btn_frame, text="Cancel", bootstyle=SECONDARY,
                   command=dialog.destroy, width=10).pack(side=LEFT, padx=6)

        dialog.wait_window()
        return result[0]

    # ════════════════════════════ Validation Helpers ═════════════════════════

    def _can_modify(self) -> bool:
        """Check if we can modify curriculum (class and date selected)."""
        if self._selected_class_id is None:
            Messagebox.show_warning(
                "Please select a specific class (not 'All Classes') first.",
                title="No Class Selected", parent=self.winfo_toplevel(),
            )
            return False

        if not self._selected_date:
            Messagebox.show_warning(
                "Please click on a date in the calendar first.",
                title="No Date Selected", parent=self.winfo_toplevel(),
            )
            return False

        return True
