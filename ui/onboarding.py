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
#
# Full names on purpose.  Everyone shortens Sherwood Forest to "Sherwood" in
# conversation, and a handoff file written by a teacher who typed the short
# form will not match one written by a teacher who typed the long form.  The
# picker offers one spelling so the two never diverge.
BSD_SCHOOLS = [
    # Secondary
    "Chinook Middle School", "Highland Middle School", "Odle Middle School",
    "Tillicum Middle School", "Tyee Middle School",
    "Bellevue High School", "Interlake High School", "International School",
    "Newport High School", "Sammamish High School", "Big Picture School",
    # Elementary — the sixteen with a 5th grade band and/or orchestra.
    "Ardmore Elementary School", "Bennett Elementary School",
    "Cherry Crest Elementary School", "Clyde Hill Elementary School",
    "Enatai Elementary School", "Jing Mei Elementary School",
    "Lake Hills Elementary School", "Medina Elementary School",
    "Newport Heights Elementary School", "Phantom Lake Elementary School",
    "Puesta del Sol Elementary School", "Sherwood Forest Elementary School",
    "Somerset Elementary School", "Spiritridge Elementary School",
    "Stevenson Elementary School", "Woodridge Elementary School",
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
        from ui.help_system import add_help_button
        add_help_button(hdr, "start")
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
        self._focus_changed()          # start in the state the focus implies
        self._build_classes(body)
        self._build_import(body)
        self._build_sharing(body)
        fit_window(self, 700, 700)

    # ── 1. About ──
    def _build_about(self, parent, profile_name):
        """Name, then what they teach, then their school(s), then backup.

        What they teach comes SECOND on purpose.  It decides whether the next
        question is "which school?" or "which schools?", and asking for a home
        school first means an itinerant answers a question that has no true
        answer for them -- six schools and none of them the main one -- before
        being told they did not have to.
        """
        box = ttk.Labelframe(parent, text=" 1. About you ", padding=10)
        box.pack(fill=X, pady=(0, 10))
        grid = ttk.Frame(box)
        grid.pack(fill=X)
        grid.columnconfigure(1, weight=1)

        r = 0
        ttk.Label(grid, text="Your name", font=("Segoe UI", 9, "bold")).grid(
            row=r, column=0, sticky=W, pady=4, padx=(0, 10))
        self._name_var = tk.StringVar(value=profile_name or "")
        ttk.Entry(grid, textvariable=self._name_var).grid(
            row=r, column=1, sticky="ew", pady=4)

        r += 1
        ttk.Label(grid, text="What do you teach?",
                  font=("Segoe UI", 9, "bold")).grid(
            row=r, column=0, sticky=W, pady=(8, 2), padx=(0, 10))
        self._focus = tk.StringVar(value="band")
        frow = ttk.Frame(grid)
        frow.grid(row=r, column=1, sticky=W, pady=(8, 2))
        for label, val in FOCUS:
            ttk.Radiobutton(frow, text=label, value=val,
                            variable=self._focus,
                            command=self._focus_changed).pack(side=LEFT,
                                                              padx=(0, 12))
        r += 1
        self._focus_note = ttk.Label(
            grid, text="Choir and orchestra skip the percussion rotation; band "
                       "gets it. You can rename or add classes below.",
            font=("Segoe UI", 8), foreground=muted_fg(),
            wraplength=430, justify=LEFT)
        self._focus_note.grid(row=r, column=1, sticky=W)

        r += 1
        self._school_lbl = ttk.Label(grid, text="School",
                                     font=("Segoe UI", 9, "bold"))
        self._school_lbl.grid(row=r, column=0, sticky=W, pady=4, padx=(0, 10))
        self._school = tk.StringVar()
        self._school_combo = ttk.Combobox(grid, textvariable=self._school,
                                          values=BSD_SCHOOLS)
        self._school_combo.grid(row=r, column=1, sticky="ew", pady=4)
        r += 1
        self._school_note = ttk.Label(grid, text="(Bellevue School District)",
                                      font=("Segoe UI", 8),
                                      foreground=muted_fg())
        self._school_note.grid(row=r, column=1, sticky=W)

        r += 1
        self._elem_row = r
        self._build_elementary_schools(grid)

        r += 1
        ttk.Label(grid, text="Backup folder",
                  font=("Segoe UI", 9, "bold")).grid(
            row=r, column=0, sticky=W, pady=(8, 4), padx=(0, 10))
        self._backup = tk.StringVar()
        brow = ttk.Frame(grid)
        brow.grid(row=r, column=1, sticky="ew", pady=(8, 0))
        ttk.Button(brow, text="Browse…", bootstyle=(SECONDARY, OUTLINE),
                   command=self._browse_backup).pack(side=RIGHT, padx=(6, 0))
        ttk.Entry(brow, textvariable=self._backup).pack(side=LEFT, fill=X,
                                                        expand=True)
        r += 1
        ttk.Label(grid, text="Recommended: a OneDrive folder, so a copy of your "
                            "data is saved off this computer automatically.",
                  font=("Segoe UI", 8), foreground=muted_fg(),
                  wraplength=430, justify=LEFT).grid(row=r, column=1, sticky=W)

    def _build_elementary_schools(self, parent):
        """The schools an itinerant teaches at -- however many that is.

        A 5th grade specialist does not have "a school"; Ramps Rampersad has
        six and none of them is the main one. Asking for a single default is
        asking a question with no true answer, so for this focus the one-school
        box is replaced by a list.
        """
        self._elem_box = ttk.Frame(parent)
        self._elem_box.grid(row=self._elem_row, column=0, columnspan=2,
                            sticky="ew", pady=(4, 0))
        self._elem_box.grid_remove()          # shown by _focus_changed
        self._elem_rows = []          # (name, program)

        ttk.Label(self._elem_box,
                  text="Add each school you teach at, and whether you run band "
                       "or orchestra there. You can change these later in "
                       "Settings ▸ Schools.",
                  font=("Segoe UI", 8), foreground=muted_fg(),
                  wraplength=600, justify=LEFT).pack(anchor=W, pady=(6, 4))

        add = ttk.Frame(self._elem_box)
        add.pack(fill=X)
        self._elem_name = tk.StringVar()
        ttk.Combobox(add, textvariable=self._elem_name,
                     values=[x for x in BSD_SCHOOLS if "Elementary" in x],
                     width=32).pack(side=LEFT)
        self._elem_program = tk.StringVar(value="band")
        for lbl, val in (("Band", "band"), ("Orchestra", "orchestra")):
            ttk.Radiobutton(add, text=lbl, value=val,
                            variable=self._elem_program).pack(side=LEFT, padx=(8, 0))
        ttk.Button(add, text="Add", bootstyle=SUCCESS,
                   command=self._add_elem_school).pack(side=LEFT, padx=(10, 0))

        self._elem_list = tk.Listbox(self._elem_box, height=5,
                                     font=("Segoe UI", 9))
        self._elem_list.pack(fill=X, pady=(6, 2))
        ttk.Button(self._elem_box, text="Remove selected",
                   bootstyle=(SECONDARY, OUTLINE),
                   command=self._remove_elem_school).pack(anchor=W)

    def _add_elem_school(self):
        name = self._elem_name.get().strip()
        if not name:
            return
        if any(n.lower() == name.lower() for n, _ in self._elem_rows):
            return                     # already on the list
        self._elem_rows.append((name, self._elem_program.get()))
        self._elem_list.insert("end", f"{name}   —   "
                                      f"{self._elem_program.get().capitalize()}")
        self._elem_name.set("")

    def _remove_elem_school(self):
        sel = list(self._elem_list.curselection())
        for i in reversed(sel):
            self._elem_list.delete(i)
            del self._elem_rows[i]

    def _focus_changed(self):
        """Elementary teachers get the school LIST; everybody else gets the box."""
        elementary = self._focus.get() == "elementary"
        for w in (self._school_lbl, self._school_combo, self._school_note):
            if elementary:
                w.grid_remove()
            else:
                w.grid()
        if elementary:
            self._elem_box.grid()
        else:
            self._elem_box.grid_remove()

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

    # ── 4. Sharing (optional, rare) ──
    def _build_sharing(self, parent):
        box = ttk.Labelframe(parent, text=" 4. Share an inventory with a co-director "
                                          "(optional) ", padding=10)
        box.pack(fill=X, pady=(10, 0))
        ttk.Label(box, text="Only for two directors at one school who share the same "
                            "instruments, check-outs, repairs, and music library "
                            "while keeping separate class lists. Most teachers skip "
                            "this. You can also set it up later in Settings ▸ Sharing.",
                  font=("Segoe UI", 9), wraplength=620, justify=LEFT).pack(anchor=W)
        ttk.Button(box, text="🔗 Set up co-director sharing…",
                   bootstyle=(INFO, OUTLINE),
                   command=self._open_sharing).pack(anchor=W, pady=(6, 0))

    def _open_sharing(self):
        # Save first so the panel writes into a settings.json that already has the
        # teacher/classes chosen above.
        self._save()
        top = ttk.Toplevel(self)
        top.title("Co-director sharing")
        top.grab_set()
        from ui.sharing_view import SharingPanel
        SharingPanel(top, self.base_dir).pack(fill=BOTH, expand=True)
        from ui.theme import fit_window
        fit_window(top, 560, 620)

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
        # "school_name" is the key every other screen reads (Settings, the
        # loan forms, the concert programs, Reginald).  This wrote "school",
        # so a teacher who finished setup and never opened Settings had no
        # school name anywhere in the program.
        elementary = self._focus.get() == "elementary"
        # An itinerant has no default school, so none is written.  Everything
        # that used to read this -- the loan form above all -- now takes the
        # school from the instrument being lent, which is the only answer that
        # is true at six schools.
        s["teacher"]["school_name"] = ("" if elementary
                                       else self._school.get().strip())
        s["teacher"]["program_type"] = self._focus.get()
        backup = self._backup.get().strip()
        if backup:
            s.setdefault("backup", {})["external_path"] = backup
        save_settings(self.base_dir, s)
        if elementary:
            self._save_elementary_schools()
        classes = self._collect_classes()
        if classes:
            self._cr.save_classes(self.base_dir, classes)

    def _save_elementary_schools(self):
        """Create a site per school the teacher listed."""
        try:
            db = self.main_db
        except Exception:
            return
        for name, program in getattr(self, "_elem_rows", []):
            try:
                db.add_site(name, "elementary", program)
            except Exception:
                pass

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
