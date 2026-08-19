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

        # Start-of-year jobs, in the order a teacher actually meets them:
        # bring the cupboard across (once), then load this year's children
        # (every year).  Same wording and same file types as the secondary
        # Import Data wizard, because plenty of people do both jobs.
        setup = ttk.Frame(outer)
        setup.pack(fill=X, padx=10, pady=(0, 6))
        ttk.Label(setup, text="Start of year:", font=("Segoe UI", 9, "bold"),
                  foreground=muted_fg()).pack(side=LEFT, padx=(0, 8))
        ttk.Button(setup, text="📥 Import Inventory From Another Teacher",
                   bootstyle=(PRIMARY, OUTLINE),
                   command=lambda s=site: self._import_handoff(s)
                   ).pack(side=LEFT, padx=(0, 6))
        ttk.Button(setup, text="🗄 Import From CutTime / Charms",
                   bootstyle=(SECONDARY, OUTLINE),
                   command=lambda s=site: self._import_legacy(s)
                   ).pack(side=LEFT, padx=(0, 6))
        ttk.Button(setup, text="🎓 Import Class List (CSV)",
                   bootstyle=(SUCCESS, OUTLINE),
                   command=lambda s=site: self._import_roster(s)
                   ).pack(side=LEFT)

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

    # ── Start-of-year imports ───────────────────────────────────────────────

    def _import_handoff(self, site):
        """Pick up where the last teacher left off at this school."""
        from tkinter import filedialog
        import site_export as SE

        path = filedialog.askopenfilename(
            parent=self.winfo_toplevel(),
            title=f"Inventory handed over for {site['name']}",
            filetypes=[("Roka handover file", "*.xlsx"), ("All files", "*.*")])
        if not path:
            return
        try:
            res = SE.import_handoff(self.db, site, path)
        except ImportError:
            Messagebox.show_error(
                "Reading a spreadsheet needs openpyxl:  pip install openpyxl",
                title="Missing Dependency", parent=self.winfo_toplevel())
            return
        except Exception as e:
            Messagebox.show_error(
                "That file could not be read as a Roka handover."
                f"\n\n{e}\n\nIt should be the file the previous teacher saved "
                "with Hand Over This School.",
                title="Could not import", parent=self.winfo_toplevel())
            return

        lines = [f"{res['added']} instrument(s) added to {site['name']}."]
        if res["matched"]:
            lines.append(f"{res['matched']} were already here and were left alone, "
                         f"so running this twice is safe.")
        if res["repairs"]:
            lines.append(f"{res['repairs']} repair record(s) came across with them.")
        if res["unidentifiable"]:
            lines.append(f"{res['unidentifiable']} had no serial number, barcode or "
                         f"district number, so importing this file again would add "
                         f"them a second time.")
        lines.append("Last year's check-outs were not brought over — those "
                     "children have moved on.")
        Messagebox.show_info("\n\n".join(lines), title="Inventory imported",
                             parent=self.winfo_toplevel())
        self.refresh()

    def _import_legacy(self, site):
        """First year only: bring a cupboard across from CutTime or Charms."""
        from tkinter import filedialog
        import import_service

        path = filedialog.askopenfilename(
            parent=self.winfo_toplevel(),
            title=f"CutTime or Charms inventory export for {site['name']}",
            filetypes=[("Spreadsheet or CSV", "*.xlsx *.xls *.csv"),
                       ("All files", "*.*")])
        if not path:
            return
        # Which one it is decides how the columns are read, and the two look
        # nothing alike, so ask rather than sniff and get it subtly wrong.
        answer = Messagebox.yesno(
            "Is this a CutTime export?\n\nYes — CutTime.\nNo — Charms.",
            title="Which program?", parent=self.winfo_toplevel())
        is_cuttime = (answer == "Yes")
        try:
            res = import_service.import_inventory(
                self.db,
                cuttime_path=path if is_cuttime else None,
                charms_inv_path=None if is_cuttime else path,
                site_id=site["id"])
        except Exception as e:
            Messagebox.show_error(
                f"That file could not be read as {'CutTime' if is_cuttime else 'Charms'}"
                f" inventory.\n\n{e}",
                title="Could not import", parent=self.winfo_toplevel())
            return

        added = res.get("added", 0) + res.get("charms_only_added", 0)
        Messagebox.show_info(
            f"{added} instrument(s) added to {site['name']}."
            + (f"\n\n{res['enriched']} existing record(s) were filled in with "
               f"purchase details." if res.get("enriched") else "")
            + (f"\n\n{res['repairs']} repair record(s) imported."
               if res.get("repairs") else ""),
            title="Inventory imported", parent=self.winfo_toplevel())
        self.refresh()

    def _import_roster(self, site):
        """This year's children, from the district class list."""
        from tkinter import filedialog
        import import_service

        section = self._ask_section(site)
        if not section:
            return
        path = filedialog.askopenfilename(
            parent=self.winfo_toplevel(),
            title=f"Class list for {section}",
            filetypes=[("CSV file", "*.csv"), ("All files", "*.*")])
        if not path:
            return
        try:
            res = import_service.import_students(
                self.db, path, section, None,
                self.db.current_school_year(), site_id=site["id"])
        except Exception as e:
            Messagebox.show_error(
                f"That class list could not be read.\n\n{e}",
                title="Could not import", parent=self.winfo_toplevel())
            return
        Messagebox.show_info(
            f"{res['added']} child(ren) added to {section}."
            + (f"\n\n{res['updated']} were already on this school's roster and "
               f"were updated." if res["updated"] else ""),
            title="Class list imported", parent=self.winfo_toplevel())
        self.refresh()

    def _ask_section(self, site):
        """Which of this school's sections the class list belongs to.

        Named after the school rather than the programme: inside a Clyde Hill
        tab, "Clyde Hill: Section 1" says everything, and repeating "Band"
        would only repeat what the school record already knows.
        """
        options = [f"{site['name']}: Section {n}" for n in (1, 2)]
        dlg = ttk.Toplevel(self.winfo_toplevel())
        dlg.title("Which section?")
        dlg.resizable(False, False)
        dlg.grab_set()
        chosen = {"value": None}

        body = ttk.Frame(dlg)
        body.pack(fill=BOTH, expand=True, padx=18, pady=14)
        ttk.Label(body, text="Which section is this class list for?",
                  font=("Segoe UI", 10, "bold")).pack(anchor=W)
        ttk.Label(body, text="Most schools run two, back to back in the same "
                             "room. Import each one separately.",
                  font=("Segoe UI", 8), foreground=muted_fg(),
                  wraplength=340, justify=LEFT).pack(anchor=W, pady=(2, 10))
        pick = tk.StringVar(value=options[0])
        for opt in options:
            ttk.Radiobutton(body, text=opt, value=opt, variable=pick,
                            bootstyle=PRIMARY).pack(anchor=W, pady=1)

        btns = ttk.Frame(dlg)
        btns.pack(fill=X, padx=18, pady=(4, 14))

        def ok():
            chosen["value"] = pick.get()
            dlg.destroy()

        ttk.Button(btns, text="Cancel", bootstyle=(SECONDARY, OUTLINE),
                   command=dlg.destroy).pack(side=RIGHT, padx=4)
        ttk.Button(btns, text="Choose File…", bootstyle=SUCCESS,
                   command=ok).pack(side=RIGHT, padx=4)
        fit_window(dlg, 400, 260)
        self.wait_window(dlg)
        return chosen["value"]

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
