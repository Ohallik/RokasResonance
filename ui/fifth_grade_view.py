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

        top = ttk.Frame(self)
        top.pack(fill=X, padx=16, pady=(10, 6))
        ttk.Label(
            top,
            text="Each school keeps its own instruments and its own children. "
                 "An instrument can only be checked out to a student at the "
                 "same school, and these loans carry no rental fee.",
            font=("Segoe UI", 9), foreground=muted_fg(),
            wraplength=620, justify=LEFT,
        ).pack(side=LEFT, anchor=W)
        # ACROSS the schools, which is why it sits above the tabs and not on
        # one of them: at year end the repair shop gets one sheet listing
        # every broken instrument at every school, not six files stapled.
        ttk.Button(top, text="🔧 All Schools' Repairs…",
                   bootstyle=(WARNING, OUTLINE),
                   command=lambda ss=list(sites): self._export_all_repairs(ss)
                   ).pack(side=RIGHT, anchor=N)

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
        program = (site.get("program") or "").capitalize() or "Not set"
        ttk.Label(bar, text=site["name"], font=("Segoe UI", 11, "bold")).pack(side=LEFT)
        ttk.Label(bar, text=f"   {program}  ·  no rental fee"
                           if not site.get("charges_fees") else f"   {program}",
                  font=("Segoe UI", 9), foreground=muted_fg()).pack(side=LEFT)

        # Exports for THIS school.  Assignments move around every year, so the
        # question "what am I handing to whoever gets Sherwood Forest next?"
        # has to be answerable without unpicking six schools' worth of records.
        ttk.Button(bar, text="📦 Hand Over This School",
                   bootstyle=(SUCCESS, OUTLINE),
                   command=lambda s=site: self._export(s, "handoff")
                   ).pack(side=RIGHT, padx=(6, 0))
        # Needs Repair and Repair History used to sit here as well, and both
        # opened a Save As box.  A button called "Needs Repair" should show
        # the instruments that need repair -- the Repair button below does
        # that -- and both exports are already on the Exports menu beside it.
        # Two buttons that promise a list and hand over a file dialog are
        # worse than no buttons.

        # Start-of-year jobs, in the order a teacher actually meets them:
        # bring the inventory across (once), then load this year's children
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
        # Named for what it does, not for two products.  Roka works the
        # format out itself now, and a teacher whose list came from neither
        # (or from a colleague's spreadsheet) had no reason to press a button
        # naming software they have never used.
        ttk.Button(setup, text="🗄 Import Instrument List",
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
        """First year only: bring an inventory across from CutTime or
        Charms."""
        from tkinter import filedialog
        import import_service

        path = filedialog.askopenfilename(
            parent=self.winfo_toplevel(),
            title=f"Instrument list for {site['name']} "
                  f"(CutTime spreadsheet, Charms CSV, or either exported "
                  f"from a colleague)",
            filetypes=[("Spreadsheet or CSV", "*.xlsx *.xls *.csv"),
                       ("All files", "*.*")])
        if not path:
            return
        # The file says which program it came out of, so it is not worth
        # asking.  A wrong answer reads the wrong columns and imports rows
        # with no description at all, which is worse than no import.
        kind = import_service.detect_inventory_format(path)
        if kind == "charms_xlsx":
            Messagebox.show_error(
                "That looks like a Charms inventory saved as a spreadsheet."
                "\n\nExport it from Charms as a CSV and try again.",
                title="Could not import", parent=self.winfo_toplevel())
            return
        if kind is None:
            Messagebox.show_error(
                "That file is not a CutTime or Charms inventory export."
                "\n\nCutTime exports a spreadsheet (.xlsx); Charms "
                "exports a CSV.",
                title="Could not import", parent=self.winfo_toplevel())
            return
        try:
            res = import_service.import_inventory(
                self.db,
                cuttime_path=path if kind == "cuttime" else None,
                charms_inv_path=path if kind == "charms" else None,
                charms_repair_path=path if kind == "charms_repairs"
                else None,
                site_id=site["id"])
        except Exception as e:
            Messagebox.show_error(
                f"That file could not be read.\n\n{e}",
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

        Named after the school rather than the program: inside a Clyde Hill
        tab, "Clyde Hill: Section 1" says everything, and repeating "Band"
        would only repeat what the school record already knows.
        """
        options = [f"{site['name']}: Section {n}" for n in (1, 2)]
        dlg = ttk.Toplevel(master=self.winfo_toplevel())
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

    def _export_all_repairs(self, sites):
        """One compiled needs-repair list, every school, one file."""
        from tkinter import filedialog
        import site_export as SE
        path = filedialog.asksaveasfilename(
            parent=self, defaultextension=".xlsx",
            filetypes=[("Excel workbook", "*.xlsx")],
            initialfile="Needs Repair - All Schools.xlsx",
            title="Save the compiled repair list")
        if not path:
            return
        try:
            out = SE.export_needs_repair_all(self.db, sites, path)
        except Exception as e:
            Messagebox.show_error(f"Could not write the file:\n{e}",
                                  title="Export failed", parent=self)
            return
        Messagebox.show_info(
            "%d instrument%s awaiting repair across %d school%s.\n\nSaved to %s"
            % (out["repair"], "" if out["repair"] == 1 else "s",
               len(sites), "" if len(sites) == 1 else "s", out["path"]),
            title="Repair List Saved", parent=self)

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

    def show_site(self, site_id):
        """Bring one school's tab to the front.

        An elementary-only teacher reaches a school straight from the hub, so
        the window should already be on the school they asked for rather than
        on whichever happens to be first alphabetically.
        """
        if not site_id or not hasattr(self, "nb"):
            return
        try:
            order = [dict(s)["id"] for s in elementary_sites(self.db)]
            idx = order.index(site_id)
            self.nb.select(self.nb.tabs()[idx])
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


def open_fifth_grade_window(parent, db, base_dir, site_id=None):
    """Open (or raise) the 5th grade window, optionally on one school's tab."""
    win = ttk.Toplevel(master=parent)
    win.title("5th Grade — Roka's Resonance")
    view = FifthGradeView(win, db, base_dir)
    view.pack(fill=BOTH, expand=True)
    view.show_site(site_id)
    fit_window(win, 1180, 760)
    return win
