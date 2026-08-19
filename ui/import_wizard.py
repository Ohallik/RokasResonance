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
        # An elementary profile has no classes and no periods: it has schools,
        # and two sections at each.  The roster rows below are built from
        # whichever of those two shapes applies.
        self._elem_sites = []
        if program == "elementary":
            try:
                from ui.fifth_grade_view import elementary_sites
                self._elem_sites = elementary_sites(main_db)
            except Exception:
                self._elem_sites = []
        self._elementary = bool(self._elem_sites)

        hdr = ttk.Frame(self, bootstyle=PRIMARY)
        hdr.pack(fill=X)
        from ui.help_system import add_help_button
        add_help_button(hdr, "import")
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
        self._build_incoming(body)
        self._build_results(body)

        fit_window(self, 860, 700)

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
        var = tk.StringVar()

        def browse():
            p = filedialog.askopenfilename(parent=self, filetypes=filetypes +
                                           [("All files", "*.*")])
            if p:
                var.set(p)
        # Label stacked ABOVE the entry so the row stays narrow and the Browse
        # button (pinned right) is always visible without resizing.
        ttk.Label(parent, text=label, font=("Segoe UI", fs(9))).pack(
            anchor=W, pady=(8, 0))
        row = ttk.Frame(parent)
        row.pack(fill=X)
        ttk.Button(row, text="Browse…", bootstyle=(SECONDARY, OUTLINE),
                   command=browse).pack(side=RIGHT, padx=(6, 0))
        ttk.Entry(row, textvariable=var).pack(side=LEFT, fill=X, expand=True)
        return var

    # ── Rosters ──
    def _build_rosters(self, parent):
        box = ttk.Labelframe(parent, text=" 2. Class rosters (Synergy) ", padding=10)
        box.pack(fill=X, pady=(0, 10))
        if self._elementary:
            blurb = ("One CSV per section. Export each from Synergy, attach it "
                     "here, and say which school and section it is. A child who "
                     "turns up on a second list is moved, not duplicated.")
        else:
            blurb = ("Your classes are listed below (from the setup you just "
                     "did). Export each one from Synergy as a CSV, then Browse "
                     "to attach it and pick its period. Skip any you don't have "
                     "yet, or use “Add class list” for anything extra. A "
                     "student in two of your classes is merged, not duplicated.")
        ttk.Label(box, text=blurb,
                  font=("Segoe UI", 9), wraplength=640, justify=LEFT).pack(anchor=W)
        cols = ttk.Frame(box)
        cols.pack(fill=X, pady=(6, 2))
        ttk.Label(cols, text="CSV file", font=("Segoe UI", 9, "bold"),
                  width=40).pack(side=LEFT)
        ttk.Label(cols, text="School" if self._elementary else "Class",
                  font=("Segoe UI", 9, "bold"), width=22).pack(side=LEFT)
        ttk.Label(cols, text="Section" if self._elementary else "Period",
                  font=("Segoe UI", 9, "bold")).pack(side=LEFT)
        self._roster_frame = ttk.Frame(box)
        self._roster_frame.pack(fill=X)
        self._rosters = []
        # One row per thing the teacher will actually attach a file to: a class
        # at secondary, a school at elementary.  Either way they attach files
        # rather than re-typing what they already told the setup wizard.
        if self._elementary:
            for site in self._elem_sites:
                self._add_roster(site=site)
        elif self._classes:
            for c in self._classes:
                self._add_roster(preset=c["label"])
        else:
            self._add_roster()
        ttk.Button(box,
                   text="➕ Add another section" if self._elementary
                        else "➕ Add class list",
                   bootstyle=(SUCCESS, OUTLINE),
                   command=lambda: self._add_roster(
                       site=self._elem_sites[0] if self._elementary else None)
                   ).pack(anchor=W, pady=(6, 0))

    def _add_roster(self, preset=None, site=None):
        row = ttk.Frame(self._roster_frame)
        row.pack(fill=X, pady=2)
        path = tk.StringVar()
        if self._elementary:
            site = site or self._elem_sites[0]
            default_cls = site["name"]
        else:
            default_cls = preset or (self._classes[0]["label"]
                                     if self._classes else "")
        cls = tk.StringVar(value=default_cls)
        per = tk.StringVar(value="1")
        rec = {"path": path, "cls": cls, "per": per, "row": row,
               "sections": [], "section_map": None,
               "site": site if self._elementary else None}
        ent = ttk.Entry(row, textvariable=path, width=26)
        ent.pack(side=LEFT)

        def browse():
            p = filedialog.askopenfilename(parent=self,
                                           filetypes=[("CSV", "*.csv"),
                                                      ("All files", "*.*")])
            if not p:
                return
            path.set(p)
            # A single Synergy export can contain more than one class (co-directors
            # get each other's rosters).  Detect that and, if so, ask which of the
            # teacher's classes each section maps to.
            try:
                import synergy_import
                rec["sections"] = synergy_import.summarize_sections(p)
            except Exception:
                rec["sections"] = []
            if len(rec["sections"]) > 1:
                self._map_sections(rec)
            else:
                rec["section_map"] = None
                rec["status"].config(text="")
                rec["cls_cb"].config(state="readonly")
        ttk.Button(row, text="…", width=3, bootstyle=(SECONDARY, OUTLINE),
                   command=browse).pack(side=LEFT, padx=(2, 6))
        if self._elementary:
            # A school and one of its two sections.  There are no class periods
            # at elementary -- the sections run back to back in the same room --
            # so offering one would be offering a number that means nothing.
            rec["cls_cb"] = ttk.Combobox(
                row, textvariable=cls, state="readonly", width=18,
                values=[x["name"] for x in self._elem_sites])
            rec["cls_cb"].pack(side=LEFT)
            sec_cb = ttk.Combobox(row, textvariable=per, state="readonly",
                                  width=10)
            sec_cb.pack(side=LEFT, padx=(6, 0))
            rec["sec_cb"] = sec_cb
            self._fill_sections(rec)
            rec["cls_cb"].bind(
                "<<ComboboxSelected>>",
                lambda e, r=rec: self._school_changed(r))
        else:
            rec["cls_cb"] = ttk.Combobox(row, textvariable=cls, state="readonly",
                                         width=18,
                                         values=[c["label"] for c in self._classes])
            rec["cls_cb"].pack(side=LEFT)
            ttk.Combobox(row, textvariable=per, state="readonly", width=5,
                         values=["(all)"] + PERIOD_OPTIONS).pack(side=LEFT, padx=(6, 0))
        rec["status"] = ttk.Label(row, text="", font=("Segoe UI", fs(8)),
                                  foreground=muted_fg())
        rec["status"].pack(side=LEFT, padx=(6, 0))

        def remove():
            row.destroy()
            self._rosters.remove(rec)
        ttk.Button(row, text="✕", width=2, bootstyle=(DANGER, OUTLINE, LINK),
                   command=remove).pack(side=RIGHT, padx=(6, 0))
        self._rosters.append(rec)

    def _fill_sections(self, rec):
        """The sections on offer for whichever school this row is set to."""
        from ui.ensembles import site_sections
        site = rec["site"] or {}
        opts = [x.split(": ", 1)[-1] for x in site_sections(site.get("name", ""))]
        rec["sec_cb"]["values"] = opts
        if rec["per"].get() not in opts:
            rec["per"].set(opts[0] if opts else "")

    def _school_changed(self, rec):
        """Point the row at the school just chosen, and re-offer its sections."""
        name = rec["cls"].get()
        for site in self._elem_sites:
            if site["name"] == name:
                rec["site"] = site
                break
        self._fill_sections(rec)

    def _elem_label(self, rec):
        """What a 5th grade class list is tagged with: the school's own section,
        e.g. "Clyde Hill Elementary School: Section 1".  Naming it after the
        school is what lets the roster tell one school's Section 1 from
        another's -- there are up to six of each."""
        site = rec["site"] or {}
        return f"{site.get('name', '')}: {rec['per'].get()}".strip()

    def _own_name(self):
        """The current teacher's name (lowercased) for matching the CSV's Teacher
        column to auto-select their own section."""
        try:
            from ui.settings_dialog import load_settings
            t = (load_settings(self.base_dir).get("teacher") or {})
            name = t.get("name") or os.path.basename(self.base_dir.rstrip("\\/"))
        except Exception:
            name = os.path.basename(self.base_dir.rstrip("\\/"))
        return (name or "").lower()

    def _map_sections(self, rec):
        """Ask which of the teacher's classes each section in a multi-class file
        maps to (or skip).  Stores the map on the roster row."""
        secs = rec["sections"]
        dlg = ttk.Toplevel(self)
        dlg.title("Map class sections")
        dlg.grab_set()
        dlg.lift()
        ttk.Label(dlg, text="This file has more than one class in it. Choose which "
                            "of your classes each section is — or skip one you "
                            "don't want. (You can point two sections at the same "
                            "class to combine them, or different classes to split.)",
                  font=("Segoe UI", fs(9)), wraplength=490, justify=LEFT).pack(
            anchor=W, padx=12, pady=(12, 8))
        # Pinned button bar (bottom) + scrollable section list, so any number of
        # sections stays usable and the buttons never get pushed off-screen.
        bar = ttk.Frame(dlg)
        bar.pack(side=BOTTOM, fill=X, padx=12, pady=12)
        outer = ttk.Frame(dlg)
        outer.pack(fill=BOTH, expand=True)
        cv = tk.Canvas(outer, highlightthickness=0)
        sb = ttk.Scrollbar(outer, orient=VERTICAL, command=cv.yview)
        cv.configure(yscrollcommand=sb.set)
        sb.pack(side=RIGHT, fill=Y)
        cv.pack(side=LEFT, fill=BOTH, expand=True)
        body = ttk.Frame(cv, padding=(12, 0))
        win = cv.create_window((0, 0), window=body, anchor="nw")
        body.bind("<Configure>", lambda e: cv.configure(scrollregion=cv.bbox("all")))
        cv.bind("<Configure>", lambda e: cv.itemconfig(win, width=e.width))
        cv.bind("<Enter>", lambda e: cv.bind_all(
            "<MouseWheel>", lambda ev: cv.yview_scroll(int(-ev.delta / 120), "units")))
        cv.bind("<Leave>", lambda e: cv.unbind_all("<MouseWheel>"))

        if self._elementary:
            from ui.ensembles import site_sections
            opts = ["— skip —"] + site_sections((rec["site"] or {}).get("name", ""))
            preset = self._elem_label(rec)
        else:
            opts = ["— skip —"] + [c["label"] for c in self._classes]
            preset = rec["cls"].get()
        own = self._own_name()
        pickers = {}
        for s in secs:
            r = ttk.Frame(body)
            r.pack(fill=X, pady=3)
            who = s["teacher"] or s["section"]
            # Pre-select the class the teacher was importing for THEIR OWN section
            # (Teacher column matches their name); leave the co-director's on skip.
            surname = ""
            if s.get("teacher"):
                surname = s["teacher"].split(",")[0].strip().split(" ")[0].lower()
            default = preset if (surname and surname in own and preset in opts) \
                else "— skip —"
            ttk.Label(r, text=f"{who}  ({s['count']} students)",
                      width=34).pack(side=LEFT)
            v = tk.StringVar(value=default)
            ttk.Combobox(r, textvariable=v, state="readonly", width=24,
                         values=opts).pack(side=LEFT)
            pickers[s["section"]] = v

        def ok():
            rec["section_map"] = {sec: ("" if v.get() == "— skip —" else v.get())
                                  for sec, v in pickers.items()}
            n = len({x for x in rec["section_map"].values() if x})
            rec["status"].config(text=f"→ {n} class(es)")
            rec["cls_cb"].config(state="disabled")
            dlg.destroy()
        ttk.Button(bar, text="OK", bootstyle=SUCCESS, command=ok).pack(side=RIGHT)
        ttk.Button(bar, text="Cancel", bootstyle=(SECONDARY, OUTLINE),
                   command=dlg.destroy).pack(side=RIGHT, padx=(0, 6))
        fit_window(dlg, 560, min(200 + 34 * len(secs), 560))

    # ── Incoming students (handoff from another director) ──
    def _build_incoming(self, parent):
        box = ttk.Labelframe(
            parent, text=" 3. Incoming students from another director (optional) ",
            padding=10)
        box.pack(fill=X, pady=(0, 10))
        ttk.Label(box, text="Over the summer, pre-load next year's incoming "
                            "students — with their instruments and guardian "
                            "contacts — from a handoff file their previous director "
                            "sent you. They show up grayed as \"Incoming\" and are "
                            "confirmed (or offered for removal) when you later import "
                            "your official class roster above.",
                  font=("Segoe UI", fs(9)), wraplength=640, justify=LEFT).pack(anchor=W)
        self._incoming = self._file_row(
            box, "Handoff file (.csv from another director)", [("CSV", "*.csv")])

    def _reconcile(self, provisional):
        """After an official roster import, review the incoming students who never
        appeared on it and let the teacher deactivate them."""
        _ReconcileDialog(self, self.db, provisional)

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
        incoming = self._incoming.get().strip()
        if not (ct or ci or cr or rosters or incoming):
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
            if incoming:
                if os.path.exists(incoming):
                    import student_transfer as st
                    ri = st.import_handoff(self.db, incoming, self.school_year)
                    lines.append(f"Incoming students: {ri['added']} pre-loaded"
                                 + (f", {ri['skipped']} already present"
                                    if ri['skipped'] else "") + " (shown as Incoming).")
                else:
                    lines.append(f"Incoming file not found: {os.path.basename(incoming)}")
            official_imported = False
            for r in rosters:
                p = r["path"].get().strip()
                if not os.path.exists(p):
                    lines.append(f"Roster skipped (not found): {os.path.basename(p)}")
                    continue
                official_imported = True
                # A multi-class file that was never mapped must not fall back to
                # dumping every student into one class — make the teacher map it.
                if len(r.get("sections") or []) > 1 and not r.get("section_map"):
                    lines.append(f"{os.path.basename(p)}: skipped — this file has "
                                 "more than one class; click Browse again and map "
                                 "the sections first.")
                    continue
                if self._elementary:
                    # No period, and the label carries the school's name so two
                    # schools' Section 1s stay apart.
                    site_id = (r["site"] or {}).get("id")
                    label = self._elem_label(r)
                    if r.get("section_map"):
                        res = isvc.import_students_sectioned(
                            self.db, p, r["section_map"], None,
                            self.school_year, site_id=site_id)
                        by = ", ".join(f"{k}: {v}" for k, v in
                                       (res.get("per_class") or {}).items()) or "none"
                        lines.append(f"{os.path.basename(p)}: {res['added']} added, "
                                     f"{res['updated']} merged, {res['skipped']} "
                                     f"skipped → {by}")
                    else:
                        res = isvc.import_students(self.db, p, label, None,
                                                   self.school_year,
                                                   site_id=site_id)
                        lines.append(f"{label}: {res['added']} added, "
                                     f"{res['updated']} merged (of {res['total']})")
                    continue
                per = r["per"].get()
                per = "" if per == "(all)" else per
                if r.get("section_map"):
                    res = isvc.import_students_sectioned(
                        self.db, p, r["section_map"], per, self.school_year)
                    by = ", ".join(f"{k}: {v}" for k, v in
                                   (res.get("per_class") or {}).items()) or "none"
                    lines.append(f"{os.path.basename(p)}: {res['added']} added, "
                                 f"{res['updated']} merged, {res['skipped']} skipped "
                                 f"→ {by}")
                else:
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

        # After importing an official roster, any still-"Incoming" students never
        # appeared on it — offer to review/remove those phantoms.
        if official_imported:
            leftover = self.db.get_provisional_students(self.school_year)
            if leftover:
                self.after(150, lambda: self._reconcile(leftover))


class _ReconcileDialog(ttk.Toplevel):
    """Review incoming students who weren't on the official roster; deactivate
    the ones who never enrolled (recoverable), keep any late arrivals."""

    def __init__(self, parent, db, provisional):
        super().__init__(parent)
        self.db = db
        self.title("Review Incoming Students")
        self.grab_set()
        self.lift()
        ttk.Label(self, text="These pre-loaded \"Incoming\" students did NOT appear "
                             "on the official roster you just imported. Uncheck "
                             "anyone you want to keep (a late enrollee); the rest "
                             "will be deactivated (archived and recoverable).",
                  font=("Segoe UI", fs(9)), wraplength=460, justify=LEFT).pack(
            anchor=W, padx=14, pady=(14, 8))
        bar = ttk.Frame(self)
        bar.pack(side=BOTTOM, fill=X, padx=14, pady=12)
        outer = ttk.Frame(self)
        outer.pack(fill=BOTH, expand=True)
        cv = tk.Canvas(outer, highlightthickness=0)
        sb = ttk.Scrollbar(outer, orient=VERTICAL, command=cv.yview)
        cv.configure(yscrollcommand=sb.set)
        sb.pack(side=RIGHT, fill=Y)
        cv.pack(side=LEFT, fill=BOTH, expand=True)
        inner = ttk.Frame(cv, padding=(14, 0))
        win = cv.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>", lambda e: cv.configure(scrollregion=cv.bbox("all")))
        cv.bind("<Configure>", lambda e: cv.itemconfig(win, width=e.width))
        cv.bind("<Enter>", lambda e: cv.bind_all(
            "<MouseWheel>", lambda ev: cv.yview_scroll(int(-ev.delta / 120), "units")))
        cv.bind("<Leave>", lambda e: cv.unbind_all("<MouseWheel>"))
        self._vars = {}
        for s in provisional:
            v = tk.BooleanVar(value=True)     # default: deactivate the phantom
            name = f"{s['last_name']}, {s['first_name']}".strip(", ")
            inst = (s.get("primary_instrument") or "").strip()
            ttk.Checkbutton(inner, text=name + (f"  ({inst})" if inst else ""),
                            variable=v).pack(anchor=W, pady=1)
            self._vars[s["id"]] = v
        ttk.Button(bar, text="Deactivate checked", bootstyle=DANGER,
                   command=self._apply).pack(side=RIGHT)
        ttk.Button(bar, text="Keep all", bootstyle=(SECONDARY, OUTLINE),
                   command=self.destroy).pack(side=RIGHT, padx=(0, 6))
        fit_window(self, 460, min(230 + 26 * len(provisional), 560))

    def _apply(self):
        ids = [i for i, v in self._vars.items() if v.get()]
        if ids:
            self.db.set_students_active(ids, active=0)
        Messagebox.show_info(f"Deactivated {len(ids)} student(s). Any you kept stay "
                             "as Incoming until confirmed.", title="Done", parent=self)
        self.destroy()
