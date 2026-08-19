"""
fifth_grade_view.py - The 5th grade window: one tab per elementary school.

Everything inside a tab belongs to that school and nothing else does. There is
deliberately no "all schools" view: an itinerant carries up to six of these,
every school owns its own instruments, and the single most likely mistake is
acting on the wrong one. If the combined view does not exist, it cannot be
left switched on by accident.

The instruments and roster inside each tab are the ordinary managers, scoped to
the school. Reusing them is the point -- a teacher who already knows how to
check an instrument out at the middle school knows how to do it here, and the
loan forms, repair log and checkout history all come along unchanged.
"""

import os
import tkinter as tk
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from ttkbootstrap.dialogs import Messagebox

from ui.theme import fs, muted_fg, fit_window


def elementary_sites(db):
    """The teacher's elementary schools, or [] if they teach none."""
    try:
        return [dict(s) for s in db.get_sites(level="elementary")]
    except Exception:
        return []


def has_fifth_grade(db) -> bool:
    """Whether to offer the 5th grade button at all.  Most teachers have no
    elementary posting and should never see it."""
    return bool(elementary_sites(db))


class FifthGradeView(ttk.Frame):
    """A tab per elementary school; inside each, that school's instruments and
    roster."""

    def __init__(self, parent, db, base_dir: str):
        super().__init__(parent)
        self.db = db
        self.base_dir = base_dir
        self._tabs = {}          # site_id -> {"inventory": …, "students": …}
        self._build()

    def _build(self):
        hdr = ttk.Frame(self, bootstyle=SECONDARY)
        hdr.pack(fill=X)
        try:
            from ui.help_system import add_help_button
            add_help_button(hdr, "fifth_grade")
        except Exception:
            pass
        ttk.Label(hdr, text="  🎺  5th Grade", font=("Segoe UI", 13, "bold"),
                  bootstyle=(INVERSE, SECONDARY)).pack(pady=12, padx=16, anchor=W)

        sites = elementary_sites(self.db)
        if not sites:
            self._empty()
            return

        ttk.Label(
            self,
            text="Each school keeps its own instruments and its own children. "
                 "An instrument can only be checked out to a student at the "
                 "same school, and these loans carry no rental fee.",
            font=("Segoe UI", 9), foreground=muted_fg(),
            wraplength=760, justify=LEFT,
        ).pack(anchor=W, padx=16, pady=(10, 6))

        self.nb = ttk.Notebook(self, bootstyle=PRIMARY)
        self.nb.pack(fill=BOTH, expand=True, padx=12, pady=(0, 10))
        for site in sites:
            self.nb.add(self._school_tab(site), text=f"  {_short(site['name'])}  ")

    def _empty(self):
        box = ttk.Frame(self)
        box.pack(fill=BOTH, expand=True, padx=24, pady=30)
        ttk.Label(box, text="No elementary schools yet",
                  font=("Segoe UI", 12, "bold")).pack(anchor=W)
        ttk.Label(
            box,
            text="Add the elementary schools you teach at in Settings ▸ Schools, "
                 "choosing Band or Orchestra for each one. They will appear here "
                 "as tabs, each with its own instruments and children.",
            font=("Segoe UI", 9), foreground=muted_fg(),
            wraplength=520, justify=LEFT,
        ).pack(anchor=W, pady=(4, 0))

    def _school_tab(self, site):
        """One school: its instruments and its roster, both already scoped."""
        outer = ttk.Frame(self.nb)

        bar = ttk.Frame(outer)
        bar.pack(fill=X, padx=10, pady=(8, 4))
        programme = (site.get("program") or "").capitalize() or "Not set"
        ttk.Label(bar, text=site["name"], font=("Segoe UI", 11, "bold")).pack(side=LEFT)
        ttk.Label(bar, text=f"   {programme}  ·  no rental fee"
                           if not site.get("charges_fees") else f"   {programme}",
                  font=("Segoe UI", 9), foreground=muted_fg()).pack(side=LEFT)

        # Exports for THIS school.  Assignments move around every year, so the
        # question "what am I handing to whoever gets Sherwood Forest next?"
        # has to be answerable without unpicking six schools' worth of records.
        ttk.Button(bar, text="📦 Hand Over This School",
                   bootstyle=(SUCCESS, OUTLINE),
                   command=lambda s=site: self._export(s, "handoff")
                   ).pack(side=RIGHT, padx=(6, 0))
        ttk.Button(bar, text="🔧 Needs Repair", bootstyle=(WARNING, OUTLINE),
                   command=lambda s=site: self._export(s, "needs_repair")
                   ).pack(side=RIGHT, padx=6)
        ttk.Button(bar, text="Repair History", bootstyle=(SECONDARY, OUTLINE),
                   command=lambda s=site: self._export(s, "repair_history")
                   ).pack(side=RIGHT)

        inner = ttk.Notebook(outer, bootstyle=SECONDARY)
        inner.pack(fill=BOTH, expand=True, padx=6, pady=(0, 6))

        from ui.inventory_manager import InventoryManager
        from ui.student_manager import StudentManager

        inv = InventoryManager(inner, self.db, self.base_dir, site_id=site["id"])
        inner.add(inv, text="  Instruments  ")

        stu = StudentManager(inner, self.db,
                             program_type=site.get("program") or "band",
                             site_id=site["id"])
        inner.add(stu, text="  Students  ")

        self._tabs[site["id"]] = {"inventory": inv, "students": stu}
        return outer

    _EXPORTS = {
        "handoff": ("Hand over this school",
                    "Instruments, checkout history and repair history, in one "
                    "file for whoever teaches here next."),
        "needs_repair": ("Instruments awaiting repair",
                         "What is broken now — the list for the technician."),
        "repair_history": ("Repair history",
                           "Everything ever done to this school's instruments."),
    }

    def _export(self, site, kind):
        from tkinter import filedialog
        import site_export as SE

        title, _desc = self._EXPORTS[kind]
        path = filedialog.asksaveasfilename(
            parent=self.winfo_toplevel(),
            title=f"{title} — {site['name']}",
            defaultextension=".xlsx",
            initialfile=SE.suggested_filename(site, kind),
            filetypes=[("Excel workbook", "*.xlsx")],
        )
        if not path:
            return
        try:
            fn = {"handoff": SE.export_handoff,
                  "needs_repair": SE.export_needs_repair,
                  "repair_history": SE.export_repair_history}[kind]
            res = fn(self.db, site, path)
        except ImportError:
            Messagebox.show_error(
                "Writing a spreadsheet needs openpyxl:  pip install openpyxl",
                title="Missing Dependency", parent=self.winfo_toplevel())
            return
        except Exception as e:
            Messagebox.show_error(f"Could not write the file:\n{e}",
                                  title="Export failed",
                                  parent=self.winfo_toplevel())
            return

        counts = ", ".join(
            f"{v} {_plural(k, v)}" for k, v in res.items()
            if k not in ("path", "total") and isinstance(v, int))
        Messagebox.show_info(
            f"{site['name']} — {counts or 'nothing to export'}."
            f"\n\n{os.path.basename(path)}",
            title=title, parent=self.winfo_toplevel())
        try:
            os.startfile(path)
        except Exception:
            pass

    def refresh(self):
        for panes in self._tabs.values():
            for pane in panes.values():
                try:
                    pane.refresh()
                except Exception:
                    pass


def _plural(word: str, n: int) -> str:
    """"1 checkouts" reads like a bug even when the number is right."""
    return word if n == 1 else word + "s"


def _short(name: str) -> str:
    """Tab labels are the school, without the words every one of them shares.

    Six tabs reading "… Elementary School" tell the teacher nothing and push
    the part that differs off the end of the strip."""
    out = (name or "").strip()
    for tail in (" Elementary School", " Elementary", " School"):
        if out.endswith(tail):
            out = out[: -len(tail)]
            break
    return out or (name or "")


def open_fifth_grade_window(parent, db, base_dir):
    """Open (or raise) the 5th grade window."""
    win = ttk.Toplevel(parent)
    win.title("5th Grade — Roka's Resonance")
    view = FifthGradeView(win, db, base_dir)
    view.pack(fill=BOTH, expand=True)
    fit_window(win, 1180, 760)
    return win
