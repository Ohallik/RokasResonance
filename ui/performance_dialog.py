"""
ui/performance_dialog.py - Add / Edit performance record dialog
"""

import tkinter as tk
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from ttkbootstrap.dialogs import Messagebox
from datetime import datetime

ENSEMBLE_OPTIONS = [
    "Concert Band", "Jazz Band", "Percussion Ensemble",
    "Small Ensemble", "Solo", "Marching Band", "Other",
]

CHOIR_ENSEMBLE_OPTIONS = [
    "Concert Choir", "Chamber Choir", "Women's Choir", "Men's Choir",
    "Full Choir", "Small Ensemble", "Solo", "Other",
]


class PerformanceDialog(ttk.Toplevel):
    def __init__(self, parent, db, music_id: int, performance_id=None, mode="band"):
        super().__init__(parent)
        self.db = db
        self.music_id = music_id
        self.performance_id = performance_id
        self._mode = mode
        self.saved = False

        title = "Edit Performance" if performance_id else "Add Performance"
        self.title(title)
        self.resizable(False, False)
        self.grab_set()
        self.lift()

        self._vars = {}
        self._build()

        if performance_id:
            self._load(performance_id)
        else:
            self._vars["performance_date"].set(datetime.now().strftime("%Y-%m-%d"))

        from ui.theme import fit_window
        fit_window(self, 440, 440)

    def _build(self):
        # Header
        hdr = ttk.Frame(self, bootstyle=INFO)
        hdr.pack(fill=X)
        title = "Edit Performance" if self.performance_id else "Add Performance"
        ttk.Label(hdr, text=f"  {title}", font=("Segoe UI", 13, "bold"),
                  bootstyle=(INVERSE, INFO)).pack(pady=12, padx=16, anchor=W)

        content = ttk.Frame(self)
        content.pack(fill=BOTH, expand=True, padx=20, pady=12)

        # Date
        self._make_field(content, "Date (YYYY-MM-DD)", "performance_date")

        # Ensemble
        f = ttk.Frame(content)
        f.pack(fill=X, pady=4)
        ttk.Label(f, text="Ensemble", font=("Segoe UI", 9)).pack(anchor=W)
        var = tk.StringVar()
        self._vars["ensemble"] = var
        opts = CHOIR_ENSEMBLE_OPTIONS if self._mode == "choir" else ENSEMBLE_OPTIONS
        ttk.Combobox(f, textvariable=var, values=opts, width=30).pack(
            anchor=W, pady=(2, 0)
        )

        # Event Name
        self._make_field(content, "Event Name *", "event_name")

        # Notes
        ttk.Label(content, text="Notes", font=("Segoe UI", 9)).pack(anchor=W, pady=(8, 0))
        self._notes_text = tk.Text(content, height=4, font=("Segoe UI", 9),
                                   relief="solid", bd=1, wrap=WORD)
        self._notes_text.pack(fill=X, pady=(2, 0))

        # Buttons
        btn_frame = ttk.Frame(self)
        btn_frame.pack(fill=X, padx=20, pady=12)
        ttk.Button(btn_frame, text="Cancel", bootstyle=(SECONDARY, OUTLINE),
                   command=self.destroy).pack(side=RIGHT, padx=4)
        ttk.Button(btn_frame, text="Save", bootstyle=SUCCESS,
                   command=self._save).pack(side=RIGHT, padx=4)

    def _make_field(self, parent, label, key):
        f = ttk.Frame(parent)
        f.pack(fill=X, pady=4)
        ttk.Label(f, text=label, font=("Segoe UI", 9)).pack(anchor=W)
        var = tk.StringVar()
        self._vars[key] = var
        ttk.Entry(f, textvariable=var, width=34).pack(anchor=W, pady=(2, 0))

    def _load(self, performance_id: int):
        rows = self.db.get_performances(self.music_id)
        row = None
        for r in rows:
            if r["id"] == performance_id:
                row = r
                break
        if not row:
            return
        for key in ("performance_date", "ensemble", "event_name"):
            if key in self._vars:
                self._vars[key].set(row[key] or "")
        self._notes_text.delete("1.0", "end")
        self._notes_text.insert("1.0", row["notes"] or "")

    def _save(self):
        data = {k: v.get().strip() for k, v in self._vars.items()}
        data["notes"] = self._notes_text.get("1.0", "end").strip()
        data["music_id"] = self.music_id

        if not data.get("event_name"):
            Messagebox.show_warning("Event name is required.", title="Validation",
                                    parent=self)
            return

        if self.performance_id:
            self.db.update_performance(self.performance_id, data)
        else:
            self.db.add_performance(data)

        self.saved = True
        self.destroy()
