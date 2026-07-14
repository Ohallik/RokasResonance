"""
ui/roster_export_view.py - "Export roster to Excel" dialog.

Pick one, several, or all of your classes and export a Student Name / Grade /
Student ID spreadsheet — for field-trip lists or in-school performance pull-outs.
Reused from both the Field Trips and Concerts views.
"""

import os
import tkinter as tk
from tkinter import filedialog
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from ttkbootstrap.dialogs import Messagebox

from ui.theme import muted_fg, fs, fit_window


def open_roster_export(parent, db, base_dir, school_year, context="", handoff=False):
    RosterExportDialog(parent, db, base_dir, school_year, context, handoff)


class RosterExportDialog(ttk.Toplevel):
    def __init__(self, parent, db, base_dir, school_year, context="", handoff=False):
        super().__init__(parent)
        self.db = db
        self.base_dir = base_dir or os.path.dirname(getattr(db, "db_path", "") or "")
        self.school_year = school_year
        self._handoff = handoff
        self.title("Send Students to Another Director" if handoff
                   else "Export Roster to Excel")
        self.grab_set()
        self.lift()

        from ui.ensembles import ensembles_for
        self._ensembles = ensembles_for(self._program_type())

        head = ("Send students to another director — a handoff file with their "
                "instruments and guardian contacts (they'll import it as incoming)."
                if handoff else
                "Export a Student Name / Grade / Student ID list to Excel.")
        ttk.Label(self, text=head, font=("Segoe UI", fs(10), "bold"),
                  wraplength=440, justify=LEFT).pack(anchor=W, padx=16, pady=(14, 2))
        if context:
            ttk.Label(self, text=context, font=("Segoe UI", fs(9)),
                      foreground=muted_fg()).pack(anchor=W, padx=16)
        ttk.Label(self, text="Choose which classes to include:",
                  font=("Segoe UI", fs(9))).pack(anchor=W, padx=16, pady=(10, 2))

        box = ttk.Frame(self)
        box.pack(fill=X, padx=16)
        self._all = tk.BooleanVar(value=True)
        ttk.Checkbutton(box, text="All classes", variable=self._all,
                        bootstyle="round-toggle",
                        command=self._toggle_all).pack(anchor=W, pady=2)
        self._vars = {}
        self._checks = []
        for e in self._ensembles:
            v = tk.BooleanVar(value=False)
            cb = ttk.Checkbutton(box, text=e, variable=v)
            cb.pack(anchor=W, padx=(20, 0))
            cb.configure(state="disabled")   # disabled while "All" is on
            self._vars[e] = v
            self._checks.append(cb)

        bar = ttk.Frame(self)
        bar.pack(fill=X, padx=16, pady=14)
        ttk.Button(bar, text="Export…", bootstyle=SUCCESS,
                   command=self._export).pack(side=RIGHT)
        ttk.Button(bar, text="Cancel", bootstyle=(SECONDARY, OUTLINE),
                   command=self.destroy).pack(side=RIGHT, padx=(0, 6))

        fit_window(self, 380, 200 + 24 * len(self._ensembles))

    def _program_type(self):
        try:
            from ui.settings_dialog import load_settings
            return (load_settings(self.base_dir).get("teacher") or {}).get(
                "program_type", "band")
        except Exception:
            return "band"

    def _toggle_all(self):
        state = "disabled" if self._all.get() else "normal"
        for cb in self._checks:
            cb.configure(state=state)

    def _selected(self):
        if self._all.get():
            return list(self._ensembles)
        return [e for e, v in self._vars.items() if v.get()]

    def _export(self):
        chosen = self._selected()
        if not chosen:
            Messagebox.show_warning("Pick at least one class (or All classes).",
                                    title="Nothing selected", parent=self)
            return
        import roster_export
        try:
            students = [dict(s) for s in self.db.get_all_students(self.school_year)]
        except Exception:
            students = [dict(s) for s in self.db.get_all_students()]

        if self._handoff:
            full = roster_export.filter_full(students, chosen)
            if not full:
                Messagebox.show_info("No students found in the selected class(es).",
                                     title="Nothing to send", parent=self)
                return
            path = filedialog.asksaveasfilename(
                parent=self, defaultextension=".csv", initialfile="students_handoff.csv",
                filetypes=[("CSV", "*.csv")])
            if not path:
                return
            try:
                import student_transfer
                student_transfer.export_students(full, path)
            except Exception as e:
                Messagebox.show_error(f"Could not write the file:\n{e}",
                                      title="Export failed", parent=self)
                return
            Messagebox.show_info(
                f"Sent {len(full)} students to:\n{os.path.basename(path)}\n\n"
                "The receiving director imports this under \"Incoming students "
                "from another director\" in their Import Data window.",
                title="Handoff created", parent=self)
            self.destroy()
            return

        # "All classes" means every selectable class, so pass the chosen list
        # (filter_students treats an explicit list as the include set).
        rows = roster_export.filter_students(students, chosen)
        if not rows:
            Messagebox.show_info("No students found in the selected class(es).",
                                 title="Empty roster", parent=self)
            return
        default = "roster.xlsx"
        if len(chosen) == 1:
            safe = "".join(c for c in chosen[0] if c.isalnum() or c in " -_").strip()
            default = f"{safe or 'roster'}.xlsx"
        path = filedialog.asksaveasfilename(
            parent=self, defaultextension=".xlsx",
            initialfile=default, filetypes=[("Excel", "*.xlsx")])
        if not path:
            return
        subtitle = ("All classes" if self._all.get()
                    else ", ".join(chosen)) + f" — {len(rows)} students"
        try:
            roster_export.write_roster_xlsx(rows, path, title="Roster",
                                            subtitle=subtitle)
        except Exception as e:
            Messagebox.show_error(f"Could not write the file:\n{e}",
                                  title="Export failed", parent=self)
            return
        try:
            os.startfile(path)     # open in Excel
        except Exception:
            pass
        Messagebox.show_info(f"Exported {len(rows)} students to:\n"
                             f"{os.path.basename(path)}",
                             title="Exported", parent=self)
        self.destroy()
