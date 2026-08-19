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

# Band or orchestra, never both.  One teacher cannot run both programs at one
# school: the sections meet in the same slot and nobody is in two rooms at once.
PROGRAMS = [("band", "Band"), ("orchestra", "Orchestra")]

_LEVEL_LABEL = dict(LEVELS)
_PROGRAM_LABEL = dict(PROGRAMS)


class SitesPanel(ttk.Frame):
    """The list of schools, with add / edit / archive."""

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

        cols = ("name", "level", "program", "fees", "choir")
        self.tree = ttk.Treeview(outer, columns=cols, show="headings",
                                 selectmode="browse", height=8,
                                 bootstyle=PRIMARY)
        for col, head, w in (("name", "School", 230), ("level", "Level", 130),
                             ("program", "Program", 90), ("fees", "Rental fee", 90),
                             ("choir", "Choir", 80)):
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
        ttk.Button(row, text="Archive", bootstyle=(SECONDARY, OUTLINE),
                   command=self._archive).pack(side=LEFT)
        self._restore_btn = ttk.Button(row, text="↩ Restore",
                                       bootstyle=(SUCCESS, OUTLINE),
                                       command=self._restore)
        # An archived school was invisible here, so the only way back was to
        # add it again and hope the name matched.  Archiving something you
        # cannot see afterwards is a frightening button to press.
        self._show_archived = tk.BooleanVar(value=False)
        ttk.Checkbutton(row, text="Show archived", variable=self._show_archived,
                        bootstyle=SECONDARY,
                        command=self.reload).pack(side=RIGHT)

        self._note = ttk.Label(outer, text="", font=("Segoe UI", 8),
                               foreground=muted_fg(), wraplength=470,
                               justify=LEFT)
        self._note.pack(anchor=W, pady=(10, 0))

    # ── data ────────────────────────────────────────────────────────────────

    def reload(self):
        self.tree.delete(*self.tree.get_children())
        show_archived = bool(getattr(self, "_show_archived", None)
                             and self._show_archived.get())
        try:
            sites = [dict(s) for s in self.db.get_sites(
                include_inactive=show_archived)]
        except Exception:
            sites = []
        for s in sites:
            archived = not s["is_active"]
            self.tree.insert("", "end", iid=str(s["id"]),
                             tags=("archived",) if archived else (),
                             values=(
                s["name"] + ("   (archived)" if archived else ""),
                _LEVEL_LABEL.get(s["level"], s["level"] or ""),
                _PROGRAM_LABEL.get(s["program"], s["program"] or "—"),
                "charged" if s["charges_fees"] else "none",
                "everyone" if s["choir_default"] else "—",
            ))
        self.tree.tag_configure("archived", foreground=muted_fg())
        active = [s for s in sites if s["is_active"]]
        self._note.config(text=self._summary(active))
        # Restore is only offered when there is something to restore.
        try:
            if show_archived and any(not s["is_active"] for s in sites):
                self._restore_btn.pack(side=LEFT, padx=6)
            else:
                self._restore_btn.pack_forget()
        except Exception:
            pass

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

    def _restore(self):
        """Bring an archived school back, with everything it had."""
        sid = self._selected()
        if sid is None:
            Messagebox.show_info("Select an archived school to restore.",
                                 title="No school", parent=self.winfo_toplevel())
            return
        site = dict(self.db.get_site(sid))
        if site["is_active"]:
            Messagebox.show_info(f"{site['name']} is not archived.",
                                 title="Already active",
                                 parent=self.winfo_toplevel())
            return
        self.db.update_site(sid, is_active=1)
        self.reload()
        Messagebox.show_info(
            f"{site['name']} is back, with its instruments, children and "
            f"history exactly as they were.",
            title="School restored", parent=self.winfo_toplevel())

    def _archive(self):
        """Archiving keeps the history.  An assignment ending does not make last
        year's checkouts untrue, and the handoff export still has to read them."""
        sid = self._selected()
        if sid is None:
            Messagebox.show_info("Select a school to archive.", title="No school",
                                 parent=self.winfo_toplevel())
            return
        sites = [dict(s) for s in self.db.get_sites()]
        if len(sites) <= 1:
            Messagebox.show_warning(
                "This is your only school, so it cannot be archived. Edit it "
                "instead if the name is wrong.",
                title="Only school", parent=self.winfo_toplevel())
            return
        site = dict(self.db.get_site(sid))
        if Messagebox.yesno(
                f"Archive {site['name']}?\n\nIts instruments, students and "
                f"history are all kept — it just stops appearing as somewhere "
                f"you teach. You can add it again later.",
                title="Archive school", parent=self.winfo_toplevel()) == "Yes":
            self.db.archive_site(sid)
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

        ttk.Label(body, text="Program you teach here",
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

        # Where a school's choir is simply "the 5th grade", ticking two hundred
        # children one at a time is not a reasonable thing to ask.
        self._choir = tk.BooleanVar(value=bool(site.get("choir_default", 0)))
        self._choir_chk = ttk.Checkbutton(
            body, text="Everyone here is in choir",
            variable=self._choir, bootstyle=PRIMARY)
        self._choir_chk.pack(anchor=W, pady=(10, 0))
        self._choir_note = ttk.Label(
            body, text="Some schools run a choir before or after school and put "
                       "the whole year group in it. Tick this and every child "
                       "imported here joins it automatically; leave it off to "
                       "tick them individually.",
            font=("Segoe UI", 8), foreground=muted_fg(), wraplength=340,
            justify=LEFT)
        self._choir_note.pack(anchor=W)

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
        for w in (self._choir_chk, self._choir_note):
            if elementary:
                w.pack(anchor=W)
            else:
                w.pack_forget()
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
                title="Program needed", parent=self)
            return

        elementary = self._level.get() == "elementary"
        fields = dict(name=name, level=self._level.get(), program=program,
                      charges_fees=1 if self._fees.get() else 0,
                      choir_default=1 if (elementary and self._choir.get()) else 0)
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
            self.db.add_site(name, fields["level"], program, self._fees.get(),
                             choir_default=bool(fields["choir_default"]))
        self.destroy()
