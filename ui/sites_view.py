"""
sites_view.py - The schools a teacher is posted to.

Most teachers have one school and will glance at this once. The ones who need
it need it badly: the district's elementary specialists carry up to six schools
each, and a couple of secondary directors hold a high school, a middle school
and two elementaries between them.

Each school owns its own instruments, so what is set here decides what a
checkout is allowed to do -- see Database._assert_same_site.
"""

import tkinter as tk
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from ttkbootstrap.dialogs import Messagebox

from ui.theme import fs, muted_fg, fit_window
from ui.onboarding import BSD_SCHOOLS


LEVELS = [("secondary", "Middle or high school"),
          ("elementary", "Elementary (5th grade)")]

# Band or orchestra, never both.  One teacher cannot run both programmes at one
# school: the sections meet in the same slot and nobody is in two rooms at once.
PROGRAMS = [("band", "Band"), ("orchestra", "Orchestra")]

_LEVEL_LABEL = dict(LEVELS)
_PROGRAM_LABEL = dict(PROGRAMS)


class SitesPanel(ttk.Frame):
    """The list of schools, with add / edit / retire."""

    def __init__(self, parent, db):
        super().__init__(parent)
        self.db = db
        self._build()
        self.reload()

    def _build(self):
        outer = ttk.Frame(self)
        outer.pack(fill=BOTH, expand=True, padx=20, pady=14)

        ttk.Label(outer, text="Schools You Teach At",
                  font=("Segoe UI", 10, "bold")).pack(anchor=W)
        ttk.Label(
            outer,
            text="Add a school for each building you are posted to. Each one "
                 "keeps its own instruments, so an instrument can only be "
                 "checked out to a student at the same school. Elementary "
                 "schools charge no rental fee.",
            font=("Segoe UI", 9), foreground=muted_fg(),
            wraplength=470, justify=LEFT,
        ).pack(anchor=W, pady=(2, 12))

        cols = ("name", "level", "program", "fees")
        self.tree = ttk.Treeview(outer, columns=cols, show="headings",
                                 selectmode="browse", height=8,
                                 bootstyle=PRIMARY)
        for col, head, w in (("name", "School", 230), ("level", "Level", 130),
                             ("program", "Programme", 90), ("fees", "Rental fee", 90)):
            self.tree.heading(col, text=head, anchor=W)
            self.tree.column(col, width=w, anchor=W, stretch=(col == "name"))
        self.tree.pack(fill=BOTH, expand=True)
        self.tree.bind("<Double-1>", lambda e: self._edit())

        row = ttk.Frame(outer)
        row.pack(fill=X, pady=(10, 0))
        ttk.Button(row, text="➕ Add School", bootstyle=SUCCESS,
                   command=self._add).pack(side=LEFT)
        ttk.Button(row, text="✎ Edit", bootstyle=(PRIMARY, OUTLINE),
                   command=self._edit).pack(side=LEFT, padx=6)
        ttk.Button(row, text="Retire", bootstyle=(SECONDARY, OUTLINE),
                   command=self._retire).pack(side=LEFT)

        self._note = ttk.Label(outer, text="", font=("Segoe UI", 8),
                               foreground=muted_fg(), wraplength=470,
                               justify=LEFT)
        self._note.pack(anchor=W, pady=(10, 0))

    # ── data ────────────────────────────────────────────────────────────────

    def reload(self):
        self.tree.delete(*self.tree.get_children())
        try:
            sites = [dict(s) for s in self.db.get_sites()]
        except Exception:
            sites = []
        for s in sites:
            self.tree.insert("", "end", iid=str(s["id"]), values=(
                s["name"],
                _LEVEL_LABEL.get(s["level"], s["level"] or ""),
                _PROGRAM_LABEL.get(s["program"], s["program"] or "—"),
                "charged" if s["charges_fees"] else "none",
            ))
        self._note.config(text=self._summary(sites))

    def _summary(self, sites):
        if not sites:
            return ("No schools yet. Your school from the Teacher tab is added "
                    "automatically the first time Roka opens.")
        if len(sites) == 1:
            return ("One school, so nothing else changes — Roka looks exactly "
                    "as it does now. Add a second to get a school selector.")
        elem = [s for s in sites if s["level"] == "elementary"]
        bits = [f"{len(sites)} schools"]
        if elem:
            bits.append(f"{len(elem)} elementary, reached from the "
                        f"5th Grade window")
        return " · ".join(bits) + "."

    def _selected(self):
        sel = self.tree.selection()
        return int(sel[0]) if sel else None

    # ── actions ─────────────────────────────────────────────────────────────

    def _add(self):
        dlg = SiteDialog(self, self.db)
        self.wait_window(dlg)
        self.reload()

    def _edit(self):
        sid = self._selected()
        if sid is None:
            Messagebox.show_info("Select a school to edit.", title="No school",
                                 parent=self.winfo_toplevel())
            return
        dlg = SiteDialog(self, self.db, site_id=sid)
        self.wait_window(dlg)
        self.reload()

    def _retire(self):
        """Retiring keeps the history.  An assignment ending does not make last
        year's checkouts untrue, and the handoff export still has to read them."""
        sid = self._selected()
        if sid is None:
            Messagebox.show_info("Select a school to retire.", title="No school",
                                 parent=self.winfo_toplevel())
            return
        sites = [dict(s) for s in self.db.get_sites()]
        if len(sites) <= 1:
            Messagebox.show_warning(
                "This is your only school, so it cannot be retired. Edit it "
                "instead if the name is wrong.",
                title="Only school", parent=self.winfo_toplevel())
            return
        site = dict(self.db.get_site(sid))
        if Messagebox.yesno(
                f"Retire {site['name']}?\n\nIts instruments, students and "
                f"history are all kept — it just stops appearing as somewhere "
                f"you teach. You can add it again later.",
                title="Retire school", parent=self.winfo_toplevel()) == "Yes":
            self.db.deactivate_site(sid)
            self.reload()


class SiteDialog(ttk.Toplevel):
    """Add or edit one school."""

    def __init__(self, parent, db, site_id=None):
        super().__init__(parent.winfo_toplevel())
        self.db = db
        self.site_id = site_id
        site = dict(db.get_site(site_id)) if site_id else {}

        self.title("Edit School" if site_id else "Add School")
        self.resizable(False, False)
        self.grab_set()

        body = ttk.Frame(self)
        body.pack(fill=BOTH, expand=True, padx=18, pady=14)

        ttk.Label(body, text="School name",
                  font=("Segoe UI", 9, "bold")).pack(anchor=W)
        # NB: not self._name -- tkinter.Misc uses that attribute itself,
        # and shadowing it makes destroy() raise on the way out.
        self._name_var = tk.StringVar(value=site.get("name", ""))
        ttk.Combobox(body, textvariable=self._name_var, values=BSD_SCHOOLS,
                     width=38).pack(anchor=W, pady=(2, 12))

        ttk.Label(body, text="Level", font=("Segoe UI", 9, "bold")).pack(anchor=W)
        self._level = tk.StringVar(value=site.get("level") or "secondary")
        for value, label in LEVELS:
            ttk.Radiobutton(body, text=label, value=value, variable=self._level,
                            bootstyle=PRIMARY,
                            command=self._level_changed).pack(anchor=W, pady=1)

        ttk.Label(body, text="Programme you teach here",
                  font=("Segoe UI", 9, "bold")).pack(anchor=W, pady=(12, 0))
        ttk.Label(body, text="One or the other — the two meet in the same slot, "
                             "so nobody teaches both at one school.",
                  font=("Segoe UI", 8), foreground=muted_fg(),
                  wraplength=340, justify=LEFT).pack(anchor=W)
        self._program = tk.StringVar(value=site.get("program") or "")
        for value, label in PROGRAMS:
            ttk.Radiobutton(body, text=label, value=value,
                            variable=self._program,
                            bootstyle=PRIMARY).pack(anchor=W, pady=1)

        self._fees = tk.BooleanVar(
            value=bool(site.get("charges_fees", 1)) if site else True)
        self._fees_chk = ttk.Checkbutton(
            body, text="Charge the instrument rental fee",
            variable=self._fees, bootstyle=PRIMARY)
        self._fees_chk.pack(anchor=W, pady=(12, 0))
        self._fees_note = ttk.Label(body, text="", font=("Segoe UI", 8),
                                    foreground=muted_fg(), wraplength=340,
                                    justify=LEFT)
        self._fees_note.pack(anchor=W)

        btns = ttk.Frame(self)
        btns.pack(fill=X, padx=18, pady=(4, 14))
        ttk.Button(btns, text="Cancel", bootstyle=(SECONDARY, OUTLINE),
                   command=self.destroy).pack(side=RIGHT, padx=4)
        ttk.Button(btns, text="Save", bootstyle=SUCCESS,
                   command=self._save).pack(side=RIGHT, padx=4)

        self._level_changed(initial=bool(site_id))
        fit_window(self, 420, 470)

    def _level_changed(self, initial=False):
        """Elementary loans are free, so the fee comes off when elementary is
        chosen. Left switchable rather than locked, in case a school does
        charge — but the default should not be the one that bills a 10-year-old
        $75 by accident."""
        elementary = self._level.get() == "elementary"
        if not initial:
            self._fees.set(not elementary)
        self._fees_note.config(
            text="Elementary instrument loans are free in this district, so "
                 "this is normally off." if elementary else
            "Adds the rental fee to the student's account on checkout.")

    def _save(self):
        name = self._name_var.get().strip()
        if not name:
            Messagebox.show_warning("Give the school a name.",
                                    title="Name needed", parent=self)
            return
        program = self._program.get() or None
        if self._level.get() == "elementary" and not program:
            Messagebox.show_warning(
                "Choose Band or Orchestra for this school.\n\nIt decides which "
                "instruments and class sections you are offered here, and it "
                "cannot be guessed — plenty of teachers run band at one school "
                "and orchestra at another.",
                title="Programme needed", parent=self)
            return

        fields = dict(name=name, level=self._level.get(), program=program,
                      charges_fees=1 if self._fees.get() else 0)
        if self.site_id:
            self.db.update_site(self.site_id, **fields)
        else:
            existing = {(dict(s)["name"] or "").strip().lower()
                        for s in self.db.get_sites(include_inactive=True)}
            if name.lower() in existing:
                Messagebox.show_warning(
                    f"{name} is already on your list.",
                    title="Already added", parent=self)
                return
            self.db.add_site(name, fields["level"], program, self._fees.get())
        self.destroy()
