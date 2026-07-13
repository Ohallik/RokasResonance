"""
ui/import_wizard.py - One-time "new profile" data import.

Run once when a teacher first sets up Roka from scratch: pull inventory from
CutTime and/or Charms, and student rosters from Synergy class-list CSVs (one per
class, tagged with the class + period).  After this, everything lives locally and
only class lists are re-uploaded each year via the New School Year wizard.

The heavy lifting (parsing + merge policy — CutTime authoritative, Charms fills
purchase blanks + adds the repair log) lives in ``import_service``; this is the
form around it.
"""

import os
import tkinter as tk
from tkinter import filedialog
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from ttkbootstrap.dialogs import Messagebox

from ui.theme import muted_fg, fs, fit_window
from ui.ensembles import PERIOD_OPTIONS


class ImportWizard(ttk.Toplevel):
    def __init__(self, parent, main_db, base_dir, school_year):
        super().__init__(parent)
        self.db = main_db
        self.base_dir = base_dir
        self.school_year = school_year
        self.title("Import Data")
        self.grab_set()
        self.lift()

        import class_registry
        program = self._program_type()
        self._classes = class_registry.load_classes(base_dir, program)

        hdr = ttk.Frame(self, bootstyle=PRIMARY)
        hdr.pack(fill=X)
        ttk.Label(hdr, text="📥  Import Your Data", font=("Segoe UI", 14, "bold"),
                  bootstyle=(INVERSE, PRIMARY)).pack(pady=12, padx=16, anchor=W)
        ttk.Label(hdr, text=f"Setting up {self.school_year}. Do this once — after "
                            "that your data stays on this computer.",
                  font=("Segoe UI", 9), bootstyle=(INVERSE, PRIMARY)).pack(
            padx=16, pady=(0, 10), anchor=W)

        # Bottom bar first (so it's always visible).
        bar = ttk.Frame(self)
        bar.pack(side=BOTTOM, fill=X, padx=16, pady=12)
        ttk.Button(bar, text="Close", bootstyle=(SECONDARY, OUTLINE),
                   command=self.destroy).pack(side=RIGHT, padx=4)
        self._import_btn = ttk.Button(bar, text="Import", bootstyle=SUCCESS,
                                      command=self._run)
        self._import_btn.pack(side=RIGHT, padx=4)
        self._status = ttk.Label(bar, text="", font=("Segoe UI", fs(9)),
                                 foreground=muted_fg())
        self._status.pack(side=LEFT)

        # Scrollable body.
        outer = ttk.Frame(self)
        outer.pack(fill=BOTH, expand=True)
        cv = tk.Canvas(outer, highlightthickness=0)
        sb = ttk.Scrollbar(outer, orient=VERTICAL, command=cv.yview)
        cv.configure(yscrollcommand=sb.set)
        sb.pack(side=RIGHT, fill=Y)
        cv.pack(side=LEFT, fill=BOTH, expand=True)
        body = ttk.Frame(cv, padding=16)
        win = cv.create_window((0, 0), window=body, anchor="nw")
        body.bind("<Configure>", lambda e: cv.configure(scrollregion=cv.bbox("all")))
        cv.bind("<Configure>", lambda e: cv.itemconfig(win, width=e.width))
        cv.bind("<Enter>", lambda e: cv.bind_all(
            "<MouseWheel>", lambda ev: cv.yview_scroll(int(-ev.delta / 120), "units")))
        cv.bind("<Leave>", lambda e: cv.unbind_all("<MouseWheel>"))

        self._build_inventory(body)
        self._build_rosters(body)
        self._build_results(body)

        fit_window(self, 720, 680)

    def _program_type(self):
        try:
            from ui.settings_dialog import load_settings
            return (load_settings(self.base_dir).get("teacher") or {}).get(
                "program_type", "band")
        except Exception:
            return "band"

    # ── Inventory ──
    def _build_inventory(self, parent):
        box = ttk.Labelframe(parent, text=" 1. Instrument inventory ", padding=10)
        box.pack(fill=X, pady=(0, 10))
        ttk.Label(box, text="Provide whichever you have. CutTime is used as your "
                            "current inventory; Charms fills in purchase details "
                            "and adds your repair history (CutTime has no repair "
                            "export). If you only have Charms, that's used on its own.",
                  font=("Segoe UI", 9), wraplength=640, justify=LEFT).pack(anchor=W)
        self._cuttime = self._file_row(box, "CutTime inventory export (.xlsx)",
                                       [("Excel", "*.xlsx")])
        self._charms_inv = self._file_row(box, "Charms inventory (.csv) — optional",
                                          [("CSV", "*.csv")])
        self._charms_rep = self._file_row(box, "Charms repair log (.csv) — optional",
                                          [("CSV", "*.csv")])

    def _file_row(self, parent, label, filetypes):
        row = ttk.Frame(parent)
        row.pack(fill=X, pady=(6, 0))
        ttk.Label(row, text=label, width=42,
                  font=("Segoe UI", fs(9))).pack(side=LEFT)
        var = tk.StringVar()
        ent = ttk.Entry(row, textvariable=var)
        ent.pack(side=LEFT, fill=X, expand=True, padx=(4, 4))

        def browse():
            p = filedialog.askopenfilename(parent=self, filetypes=filetypes +
                                           [("All files", "*.*")])
            if p:
                var.set(p)
        ttk.Button(row, text="Browse…", bootstyle=(SECONDARY, OUTLINE),
                   command=browse).pack(side=LEFT)
        return var

    # ── Rosters ──
    def _build_rosters(self, parent):
        box = ttk.Labelframe(parent, text=" 2. Class rosters (Synergy) ", padding=10)
        box.pack(fill=X, pady=(0, 10))
        ttk.Label(box, text="Export each class list from Synergy as a CSV and add "
                            "a row per class, choosing which class and period it "
                            "is. A student in two of your classes is merged, not "
                            "duplicated.",
                  font=("Segoe UI", 9), wraplength=640, justify=LEFT).pack(anchor=W)
        cols = ttk.Frame(box)
        cols.pack(fill=X, pady=(6, 2))
        ttk.Label(cols, text="CSV file", font=("Segoe UI", 9, "bold"),
                  width=40).pack(side=LEFT)
        ttk.Label(cols, text="Class", font=("Segoe UI", 9, "bold"),
                  width=22).pack(side=LEFT)
        ttk.Label(cols, text="Period", font=("Segoe UI", 9, "bold")).pack(side=LEFT)
        self._roster_frame = ttk.Frame(box)
        self._roster_frame.pack(fill=X)
        self._rosters = []
        self._add_roster()
        ttk.Button(box, text="➕ Add class list", bootstyle=(SUCCESS, OUTLINE),
                   command=self._add_roster).pack(anchor=W, pady=(6, 0))

    def _add_roster(self):
        row = ttk.Frame(self._roster_frame)
        row.pack(fill=X, pady=2)
        path = tk.StringVar()
        cls = tk.StringVar(value=self._classes[0]["label"] if self._classes else "")
        per = tk.StringVar(value="1")
        ent = ttk.Entry(row, textvariable=path, width=30)
        ent.pack(side=LEFT)

        def browse():
            p = filedialog.askopenfilename(parent=self,
                                           filetypes=[("CSV", "*.csv"),
                                                      ("All files", "*.*")])
            if p:
                path.set(p)
        ttk.Button(row, text="…", width=3, bootstyle=(SECONDARY, OUTLINE),
                   command=browse).pack(side=LEFT, padx=(2, 6))
        ttk.Combobox(row, textvariable=cls, state="readonly", width=20,
                     values=[c["label"] for c in self._classes]).pack(side=LEFT)
        ttk.Combobox(row, textvariable=per, state="readonly", width=5,
                     values=["(all)"] + PERIOD_OPTIONS).pack(side=LEFT, padx=(6, 0))
        rec = {"path": path, "cls": cls, "per": per, "row": row}

        def remove():
            row.destroy()
            self._rosters.remove(rec)
        ttk.Button(row, text="✕", width=2, bootstyle=(DANGER, OUTLINE, LINK),
                   command=remove).pack(side=LEFT, padx=(6, 0))
        self._rosters.append(rec)

    # ── Results ──
    def _build_results(self, parent):
        box = ttk.Labelframe(parent, text=" Results ", padding=10)
        box.pack(fill=BOTH, expand=True)
        self._results = tk.Text(box, height=8, wrap="word", relief="solid", bd=1,
                                font=("Segoe UI", fs(9)))
        self._results.pack(fill=BOTH, expand=True)
        self._results.insert("1.0", "Choose your files above, then click Import.")
        self._results.config(state="disabled")

    def _log(self, text):
        self._results.config(state="normal")
        self._results.delete("1.0", "end")
        self._results.insert("1.0", text)
        self._results.config(state="disabled")

    # ── Run ──
    def _run(self):
        import import_service as isvc
        ct = self._cuttime.get().strip()
        ci = self._charms_inv.get().strip()
        cr = self._charms_rep.get().strip()
        rosters = [r for r in self._rosters if r["path"].get().strip()]
        if not (ct or ci or cr or rosters):
            Messagebox.show_warning("Add at least one file to import.",
                                    title="Nothing chosen", parent=self)
            return
        for label, p in (("CutTime", ct), ("Charms inventory", ci),
                         ("Charms repair log", cr)):
            if p and not os.path.exists(p):
                Messagebox.show_warning(f"{label} file not found:\n{p}",
                                        title="File not found", parent=self)
                return

        self._import_btn.config(state="disabled")
        self._status.config(text="Importing…")
        self.update_idletasks()
        lines = []
        try:
            if ct or ci or cr:
                s = isvc.import_inventory(self.db, cuttime_path=ct or None,
                                          charms_inv_path=ci or None,
                                          charms_repair_path=cr or None)
                lines.append("Inventory:")
                lines.append(f"  • {s['added']} instruments added"
                             + (f", {s['charms_only_added']} from Charms"
                                if s['charms_only_added'] else ""))
                if s["enriched"]:
                    lines.append(f"  • {s['enriched']} updated with Charms "
                                 "purchase details")
                if s["repairs"]:
                    lines.append(f"  • {s['repairs']} repair records added")
                if s["loans"]:
                    unm = s["loans_unmatched"]
                    lines.append(f"  • {s['loans']} current loans recreated"
                                 + (f" ({unm} not yet linked to a student — "
                                    "import rosters first)" if unm else ""))
            for r in rosters:
                p = r["path"].get().strip()
                if not os.path.exists(p):
                    lines.append(f"Roster skipped (not found): {os.path.basename(p)}")
                    continue
                per = r["per"].get()
                per = "" if per == "(all)" else per
                res = isvc.import_students(self.db, p, r["cls"].get(), per,
                                           self.school_year)
                lines.append(f"{r['cls'].get()} (P{per or 'all'}): "
                             f"{res['added']} added, {res['updated']} merged "
                             f"(of {res['total']})")
        except Exception as e:
            self._log("Import error:\n" + str(e))
            self._status.config(text="Error")
            self._import_btn.config(state="normal")
            return
        lines.append("")
        lines.append("Done. You can close this window; run it again to add more.")
        self._log("\n".join(lines))
        self._status.config(text="Done ✓")
        self._import_btn.config(state="normal")
