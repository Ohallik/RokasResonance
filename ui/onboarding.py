"""
ui/onboarding.py - First-run setup for a brand-new profile.

Shown once, right after a teacher creates their profile.  Collects who they are
(name + school; district is assumed Bellevue), their focus (Band / Choir /
Orchestra / Elementary), and the classes they run — seeded from the focus default
but fully editable, so an itinerant teacher can add or remove sections.  Ends by
offering the one-time data import (CutTime / Charms inventory + Synergy rosters).

Everything it saves feeds the rest of the app: ``program_type`` in settings.json
drives ensembles + hides percussion for choir/orchestra, and the class list drives
the agenda tabs (class_registry).
"""

import tkinter as tk
from tkinter import filedialog
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from ttkbootstrap.dialogs import Messagebox

from ui.theme import muted_fg, fs, fit_window
from ui.lesson_plans_hub import _TMPL_DISPLAY

# District is assumed BSD; this seeds the school picker but stays editable.
BSD_SCHOOLS = [
    "Chinook Middle School", "Highland Middle School", "Odle Middle School",
    "Tillicum Middle School", "Tyee Middle School",
    "Bellevue High School", "Interlake High School", "International School",
    "Newport High School", "Sammamish High School", "Big Picture School",
]

FOCUS = [("Band", "band"), ("Choir", "choir"), ("Orchestra", "orchestra"),
         ("Elementary (5th grade)", "elementary")]


class OnboardingWizard(ttk.Toplevel):
    def __init__(self, parent, base_dir, main_db, profile_name, on_finish=None):
        super().__init__(parent)
        self.base_dir = base_dir
        self.main_db = main_db
        self._on_finish = on_finish
        self.title("Welcome to Roka")
        self.grab_set()
        self.lift()

        import class_registry
        self._cr = class_registry
        self._display_to_tmpl = {v: k for k, v in _TMPL_DISPLAY.items()}
        self._tmpl_options = [_TMPL_DISPLAY[t] for t in class_registry.TEMPLATE_ORDER]

        hdr = ttk.Frame(self, bootstyle=PRIMARY)
        hdr.pack(fill=X)
        ttk.Label(hdr, text="👋  Welcome to Roka", font=("Segoe UI", 15, "bold"),
                  bootstyle=(INVERSE, PRIMARY)).pack(pady=12, padx=16, anchor=W)
        ttk.Label(hdr, text="A few quick things and you're set. You can change any "
                            "of this later.",
                  font=("Segoe UI", 9), bootstyle=(INVERSE, PRIMARY)).pack(
            padx=16, pady=(0, 10), anchor=W)

        bar = ttk.Frame(self)
        bar.pack(side=BOTTOM, fill=X, padx=16, pady=12)
        ttk.Button(bar, text="Finish", bootstyle=SUCCESS,
                   command=self._finish).pack(side=RIGHT, padx=4)
        ttk.Button(bar, text="Skip for now", bootstyle=(SECONDARY, OUTLINE),
                   command=self._skip).pack(side=RIGHT, padx=4)

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

        self._build_about(body, profile_name)
        self._build_classes(body)
        self._build_import(body)
        fit_window(self, 700, 700)

    # ── 1. About ──
    def _build_about(self, parent, profile_name):
        box = ttk.Labelframe(parent, text=" 1. About you ", padding=10)
        box.pack(fill=X, pady=(0, 10))
        grid = ttk.Frame(box)
        grid.pack(fill=X)
        grid.columnconfigure(1, weight=1)
        ttk.Label(grid, text="Your name", font=("Segoe UI", 9, "bold")).grid(
            row=0, column=0, sticky=W, pady=4, padx=(0, 10))
        self._name_var = tk.StringVar(value=profile_name or "")
        ttk.Entry(grid, textvariable=self._name_var).grid(row=0, column=1, sticky="ew", pady=4)
        ttk.Label(grid, text="School", font=("Segoe UI", 9, "bold")).grid(
            row=1, column=0, sticky=W, pady=4, padx=(0, 10))
        self._school = tk.StringVar()
        ttk.Combobox(grid, textvariable=self._school, values=BSD_SCHOOLS).grid(
            row=1, column=1, sticky="ew", pady=4)
        ttk.Label(grid, text="(Bellevue School District)", font=("Segoe UI", 8),
                  foreground=muted_fg()).grid(row=2, column=1, sticky=W)

        ttk.Label(grid, text="Backup folder", font=("Segoe UI", 9, "bold")).grid(
            row=3, column=0, sticky=W, pady=(8, 4), padx=(0, 10))
        self._backup = tk.StringVar()
        brow = ttk.Frame(grid)
        brow.grid(row=3, column=1, sticky="ew", pady=(8, 0))
        ttk.Button(brow, text="Browse…", bootstyle=(SECONDARY, OUTLINE),
                   command=self._browse_backup).pack(side=RIGHT, padx=(6, 0))
        ttk.Entry(brow, textvariable=self._backup).pack(side=LEFT, fill=X, expand=True)
        ttk.Label(grid, text="Recommended: a OneDrive folder, so a copy of your "
                            "data is saved off this computer automatically.",
                  font=("Segoe UI", 8), foreground=muted_fg(),
                  wraplength=430, justify=LEFT).grid(row=4, column=1, sticky=W)

        ttk.Label(box, text="What do you teach?",
                  font=("Segoe UI", 9, "bold")).pack(anchor=W, pady=(8, 2))
        self._focus = tk.StringVar(value="band")
        frow = ttk.Frame(box)
        frow.pack(anchor=W)
        for label, val in FOCUS:
            ttk.Radiobutton(frow, text=label, value=val,
                            variable=self._focus).pack(side=LEFT, padx=(0, 12))
        ttk.Label(box, text="Choir and orchestra skip the percussion rotation; "
                            "band gets it. You can rename or add classes below.",
                  font=("Segoe UI", 8), foreground=muted_fg(),
                  wraplength=620, justify=LEFT).pack(anchor=W, pady=(4, 0))

    # ── 2. Classes ──
    def _build_classes(self, parent):
        box = ttk.Labelframe(parent, text=" 2. Your classes ", padding=10)
        box.pack(fill=X, pady=(0, 10))
        ttk.Label(box, text="Type the name of each class you teach and pick its "
                            "kind. Each gets its own agenda tab. Add a row per "
                            "class (most teachers have about five); “General” "
                            "just gives a warm-up + sheet music with no percussion "
                            "rotation.",
                  font=("Segoe UI", 9), wraplength=620, justify=LEFT).pack(anchor=W)
        self._rows_frame = ttk.Frame(box)
        self._rows_frame.pack(fill=X, pady=(6, 0))
        self._rows = []
        self._add_class_row(None)          # start with one blank row to fill in
        ttk.Button(box, text="➕ Add another class", bootstyle=(SUCCESS, OUTLINE),
                   command=lambda: self._add_class_row(None)).pack(anchor=W, pady=(6, 0))

    def _add_class_row(self, klass):
        tmpl = (klass or {}).get("template", "generic")
        if tmpl not in _TMPL_DISPLAY:
            tmpl = "generic"
        rec = {"orig": klass,
               "label": tk.StringVar(value=(klass or {}).get("label", "")),
               "template": tk.StringVar(value=_TMPL_DISPLAY[tmpl])}
        row = ttk.Frame(self._rows_frame)
        row.pack(fill=X, pady=2)
        ttk.Entry(row, textvariable=rec["label"], width=22).pack(side=LEFT)
        ttk.Combobox(row, textvariable=rec["template"], state="readonly",
                     values=self._tmpl_options, width=44).pack(side=LEFT, padx=(6, 0))

        def remove():
            row.destroy()
            self._rows.remove(rec)
        ttk.Button(row, text="✕", width=2, bootstyle=(DANGER, OUTLINE, LINK),
                   command=remove).pack(side=RIGHT)
        self._rows.append(rec)

    # ── 3. Import ──
    def _build_import(self, parent):
        box = ttk.Labelframe(parent,
                             text=" 3. Bring in your data (recommended — first time only) ",
                             padding=10)
        box.pack(fill=X)
        ttk.Label(box, text="Import your instruments from CutTime (and repair / "
                            "purchase history from Charms if you have it), plus "
                            "your class rosters from Synergy. You can do this now "
                            "or anytime from “Import Data” on the main screen.",
                  font=("Segoe UI", 9), wraplength=620, justify=LEFT).pack(anchor=W)
        ttk.Button(box, text="📥 Open the import wizard…", bootstyle=(INFO, OUTLINE),
                   command=self._open_import).pack(anchor=W, pady=(6, 0))

    def _open_import(self):
        # Save first so the import wizard sees the chosen program type + classes.
        self._save()
        from ui.import_wizard import ImportWizard
        try:
            from lesson_plan_db import current_school_year
            year = current_school_year()
        except Exception:
            year = None
        ImportWizard(self, self.main_db, self.base_dir, year)

    # ── save / finish ──
    def _collect_classes(self):
        cr = self._cr
        taken = {(r["orig"] or {}).get("id") for r in self._rows if r["orig"]}
        taken.discard(None)
        out = []
        for rec in self._rows:
            label = rec["label"].get().strip()
            if not label:
                continue
            tmpl = self._display_to_tmpl.get(rec["template"].get(), "generic")
            ti = cr.TEMPLATES[tmpl]
            orig = rec["orig"]
            if orig:
                k = dict(orig)
                k["label"] = label
                if k.get("template") != tmpl:
                    k["template"] = tmpl
                    k["book"] = ti["book"]
                    k["percussion"] = ti["percussion"]
                out.append(k)
            else:
                cid = cr.new_class_id([{"id": i} for i in taken], label)
                taken.add(cid)
                out.append({"id": cid, "label": label, "template": tmpl,
                            "ensemble": cid, "book": ti["book"],
                            "percussion": ti["percussion"]})
        return out

    def _browse_backup(self):
        p = filedialog.askdirectory(parent=self, title="Choose a backup folder")
        if p:
            self._backup.set(p)

    def _save(self):
        from ui.settings_dialog import load_settings, save_settings
        s = load_settings(self.base_dir) or {}
        s.setdefault("teacher", {})
        s["teacher"]["name"] = self._name_var.get().strip()
        s["teacher"]["school"] = self._school.get().strip()
        s["teacher"]["program_type"] = self._focus.get()
        backup = self._backup.get().strip()
        if backup:
            s.setdefault("backup", {})["external_path"] = backup
        save_settings(self.base_dir, s)
        classes = self._collect_classes()
        if classes:
            self._cr.save_classes(self.base_dir, classes)

    def _finish(self):
        self._save()
        if self._on_finish:
            try:
                self._on_finish()
            except Exception:
                pass
        self.destroy()

    def _skip(self):
        # Still record the focus so choir/orchestra don't default to band.
        if Messagebox.yesno("Skip setup for now? You can finish it later from "
                            "Settings and the Import Data link.",
                            title="Skip setup", parent=self) == "Yes":
            self._save()
            if self._on_finish:
                try:
                    self._on_finish()
                except Exception:
                    pass
            self.destroy()
