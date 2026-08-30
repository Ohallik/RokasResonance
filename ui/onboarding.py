"""
ui/onboarding.py - First-run setup for a brand-new profile.

Shown once, right after a teacher creates their profile.  It asks three
things and nothing else: who they are, what they teach, and which school(s)
they are at (one of them marked as the primary site).  Then one question --
upload class lists and inventory now, or later?  "Now" opens the import
window the moment setup is saved; "later" says where to find it.

It used to also ask for the class list, the data imports, a backup folder
and co-director sharing, all on the same screen.  Watching new users get
started showed that was too much to answer on the first day: the classes
already have sensible defaults per program, and everything else lives in
Settings, Equipment and Students where it is needed.

Everything it saves feeds the rest of the app: ``program_type`` in
settings.json drives ensembles and hides percussion for choir/orchestra, the
schools become sites (with the primary one as the home school), and the class
list comes from the program's default registry until the teacher edits it.
"""

import tkinter as tk
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from ttkbootstrap.dialogs import Messagebox

from ui.theme import muted_fg, fs, fit_window


# District is assumed BSD; this seeds the school picker but stays editable.
#
# Full names on purpose.  Everyone shortens Sherwood Forest to "Sherwood" in
# conversation, and a handoff file written by a teacher who typed the short
# form will not match one written by a teacher who typed the long form.  The
# picker offers one spelling so the two never diverge.
def school_level(name: str) -> str:
    """"elementary" or "secondary", from the school's own name.

    Every BSD elementary has "Elementary" in its name and no secondary does,
    so this is a reading rather than a guess.  International School and Big
    Picture are 6-12 and come back secondary, which is right.

    Used wherever a school is created, because the level decides a great
    deal downstream: whether the rental fee is charged, whether the loan form
    quotes it, whether the roster has class periods, whether Carry Over is
    offered, and whether the school appears on the 5th grade screen.
    """
    return "elementary" if "elementary" in (name or "").lower() else "secondary"


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


def split_name(full: str):
    """"Meagan R. Mangum" -> ("Meagan", "Mangum").  A profile folder name is
    the best guess there is for the teacher's name on the first run; middle
    initials are dropped because they are not part of either half."""
    try:
        from ui.names import display_person
        full = display_person(full or "")
    except Exception:
        full = (full or "").strip()
    words = full.split()
    if not words:
        return "", ""
    if len(words) == 1:
        return words[0], ""
    return " ".join(words[:-1]), words[-1]


class OnboardingWizard(ttk.Toplevel):
    def __init__(self, parent, base_dir, main_db, profile_name, on_finish=None):
        super().__init__(master=parent)
        self.base_dir = base_dir
        self.main_db = main_db
        self._on_finish = on_finish
        self._app = parent
        self.title("Welcome to Roka")
        self.grab_set()
        self.lift()

        hdr = ttk.Frame(self, bootstyle=PRIMARY)
        hdr.pack(fill=X)
        from ui.help_system import add_help_button
        add_help_button(hdr, "start")
        ttk.Label(hdr, text="👋  Welcome to Roka", font=("Segoe UI", 15, "bold"),
                  bootstyle=(INVERSE, PRIMARY)).pack(pady=12, padx=16, anchor=W)
        ttk.Label(hdr, text="Three quick things and you're set. You can change "
                            "any of this later in Settings.",
                  font=("Segoe UI", 9), bootstyle=(INVERSE, PRIMARY)).pack(
            padx=16, pady=(0, 10), anchor=W)

        bar = ttk.Frame(self)
        bar.pack(side=BOTTOM, fill=X, padx=16, pady=12)
        ttk.Button(bar, text="Finish", bootstyle=SUCCESS,
                   command=self._finish).pack(side=RIGHT, padx=4)
        ttk.Button(bar, text="Skip for now", bootstyle=(SECONDARY, OUTLINE),
                   command=self._skip).pack(side=RIGHT, padx=4)

        from ui.theme import scroll_body
        body = scroll_body(self, fill=BOTH, expand=True)
        inner = ttk.Frame(body, padding=16)
        inner.pack(fill=BOTH, expand=True)

        self._build_about(inner, profile_name)
        self._build_schools(inner)
        self._build_data(inner)
        self._focus_changed()          # start in the state the focus implies
        fit_window(self, 760, 620)

    # ── 1. About you ──
    def _build_about(self, parent, profile_name):
        box = ttk.Labelframe(parent, text=" 1. About you ", padding=10)
        box.pack(fill=X, pady=(0, 10))
        grid = ttk.Frame(box)
        grid.pack(fill=X)
        grid.columnconfigure(1, weight=1)
        grid.columnconfigure(3, weight=1)

        first, last = split_name(profile_name)
        ttk.Label(grid, text="First name", font=("Segoe UI", 9, "bold")).grid(
            row=0, column=0, sticky=W, pady=4, padx=(0, 10))
        self._first = tk.StringVar(value=first)
        ttk.Entry(grid, textvariable=self._first).grid(
            row=0, column=1, sticky="ew", pady=4)
        ttk.Label(grid, text="Last name", font=("Segoe UI", 9, "bold")).grid(
            row=0, column=2, sticky=W, pady=4, padx=(16, 10))
        self._last = tk.StringVar(value=last)
        ttk.Entry(grid, textvariable=self._last).grid(
            row=0, column=3, sticky="ew", pady=4)

        ttk.Label(grid, text="What do you teach?",
                  font=("Segoe UI", 9, "bold")).grid(
            row=1, column=0, sticky=W, pady=(10, 2), padx=(0, 10))
        self._focus = tk.StringVar(value="band")
        frow = ttk.Frame(grid)
        frow.grid(row=1, column=1, columnspan=3, sticky=W, pady=(10, 2))
        for label, val in FOCUS:
            ttk.Radiobutton(frow, text=label, value=val,
                            variable=self._focus,
                            command=self._focus_changed).pack(side=LEFT,
                                                              padx=(0, 12))
        ttk.Label(grid, text="This sets up a starting class list for you "
                             "(rename or add classes any time in Teacher "
                             "Tools). Choir and orchestra skip the percussion "
                             "rotation; band gets it.",
                  font=("Segoe UI", 8), foreground=muted_fg(),
                  wraplength=560, justify=LEFT).grid(
            row=2, column=1, columnspan=3, sticky=W)

    # ── 2. Your school(s) ──
    def _build_schools(self, parent):
        """Every building the teacher is at, with one marked as primary.

        A middle school director has one school; an itinerant 5th grade
        specialist has six, and a high school director may cover a middle
        school as well.  The same list serves all of them: add a row per
        school, and the Primary button says which one is home.
        """
        box = ttk.Labelframe(parent, text=" 2. Your school(s) ", padding=10)
        box.pack(fill=X, pady=(0, 10))
        self._school_note = ttk.Label(
            box, text="", font=("Segoe UI", 8), foreground=muted_fg(),
            wraplength=640, justify=LEFT)
        self._school_note.pack(anchor=W, pady=(0, 6))

        head = ttk.Frame(box)
        head.pack(fill=X)
        ttk.Label(head, text="Primary", width=9,
                  font=("Segoe UI", 9, "bold")).pack(side=LEFT)
        ttk.Label(head, text="School (Bellevue School District)",
                  font=("Segoe UI", 9, "bold")).pack(side=LEFT)
        self._prog_head = ttk.Label(head, text="Band or orchestra there?",
                                    font=("Segoe UI", 9, "bold"))
        self._prog_head.pack(side=RIGHT, padx=(0, 34))

        self._rows_frame = ttk.Frame(box)
        self._rows_frame.pack(fill=X)
        self._primary = tk.IntVar(value=0)
        self._next_row_id = 0
        self._school_rows = []
        self._add_school_row()
        ttk.Button(box, text="➕ Add another school",
                   bootstyle=(SUCCESS, OUTLINE),
                   command=self._add_school_row).pack(anchor=W, pady=(6, 0))

    def _school_choices(self):
        if self._focus.get() == "elementary":
            return [x for x in BSD_SCHOOLS if "Elementary" in x]
        return list(BSD_SCHOOLS)

    def _add_school_row(self):
        rid = self._next_row_id
        self._next_row_id += 1
        row = ttk.Frame(self._rows_frame)
        row.pack(fill=X, pady=2)
        rec = {"id": rid, "row": row, "name": tk.StringVar(),
               "program": tk.StringVar(value="band")}
        ttk.Radiobutton(row, text="", value=rid, variable=self._primary,
                        width=6).pack(side=LEFT, padx=(8, 0))

        # Remove and the program buttons are packed from the RIGHT, and the
        # school box takes whatever is left.  Packed left to right, a long
        # school name pushed the buttons off the edge of the window.
        def remove():
            row.destroy()
            self._school_rows.remove(rec)
            if self._primary.get() == rid and self._school_rows:
                self._primary.set(self._school_rows[0]["id"])
        ttk.Button(row, text="✕", width=2, bootstyle=(DANGER, OUTLINE, LINK),
                   command=remove).pack(side=RIGHT, padx=(6, 0))
        prog = ttk.Frame(row)
        rec["prog"] = prog
        for lbl, val in (("Orchestra", "orchestra"), ("Band", "band")):
            ttk.Radiobutton(prog, text=lbl, value=val,
                            variable=rec["program"]).pack(side=RIGHT,
                                                          padx=(8, 0))
        if self._focus.get() == "elementary":
            prog.pack(side=RIGHT)
        rec["combo"] = ttk.Combobox(row, textvariable=rec["name"],
                                    values=self._school_choices())
        rec["combo"].pack(side=LEFT, fill=X, expand=True, padx=(0, 6))
        self._school_rows.append(rec)
        if len(self._school_rows) == 1:
            self._primary.set(rid)

    def _focus_changed(self):
        """Elementary teachers say band or orchestra per school; nobody else
        has to, because their program is the one they picked above."""
        elementary = self._focus.get() == "elementary"
        for rec in self._school_rows:
            rec["combo"].configure(values=self._school_choices())
            if elementary:
                rec["prog"].pack(side=RIGHT)
            else:
                rec["prog"].pack_forget()
        if elementary:
            self._prog_head.pack(side=RIGHT, padx=(0, 34))
            self._school_note.config(
                text="Add each school you teach at. Each keeps its own "
                     "instruments and class lists. Mark the one you are "
                     "based at as primary; if none of them is, leave the "
                     "first one marked.")
        else:
            self._prog_head.pack_forget()
            self._school_note.config(
                text="Most teachers have one school. If you teach at more "
                     "than one, add a row for each; the primary one is the "
                     "school Roka opens on and prints on forms.")

    # ── 3. Data ──
    def _build_data(self, parent):
        box = ttk.Labelframe(parent, text=" 3. Your class lists and inventory ",
                             padding=10)
        box.pack(fill=X)
        self._upload_now = tk.BooleanVar(value=True)
        ttk.Checkbutton(box, text="Upload class lists and inventory now?",
                        variable=self._upload_now,
                        bootstyle="round-toggle").pack(anchor=W)
        ttk.Label(box, text="Checked: the import window opens as soon as you "
                            "click Finish, ready for your CutTime or Charms "
                            "inventory and your Synergy class lists (or "
                            "Roka's blank inventory form if you are starting "
                            "from scratch). Unchecked: do it later from "
                            "Equipment (inventory) and Students (class lists).",
                  font=("Segoe UI", 8), foreground=muted_fg(),
                  wraplength=640, justify=LEFT).pack(anchor=W, pady=(4, 0))

    # ── save / finish ──
    def _validate(self):
        if not self._first.get().strip() or not self._last.get().strip():
            Messagebox.show_warning("Enter your first and last name.",
                                    title="Name", parent=self)
            return False
        names = [r["name"].get().strip() for r in self._school_rows]
        if not any(names):
            Messagebox.show_warning("Add at least one school.",
                                    title="School", parent=self)
            return False
        primary = self._primary_row()
        if primary is None or not primary["name"].get().strip():
            Messagebox.show_warning("Mark one of your schools as primary.",
                                    title="Primary school", parent=self)
            return False
        seen = set()
        for n in names:
            if n and n.lower() in seen:
                Messagebox.show_warning(f"{n} is listed twice.",
                                        title="School", parent=self)
                return False
            seen.add(n.lower())
        return True

    def _primary_row(self):
        want = self._primary.get()
        for rec in self._school_rows:
            if rec["id"] == want:
                return rec
        return self._school_rows[0] if self._school_rows else None

    def _save(self):
        """Write settings + schools.  Returns the primary site's id (or None)."""
        from ui.settings_dialog import load_settings, save_settings
        s = load_settings(self.base_dir) or {}
        t = s.setdefault("teacher", {})
        first, last = self._first.get().strip(), self._last.get().strip()
        full = f"{first} {last}".strip()
        t["first_name"] = first
        t["last_name"] = last
        if full:
            t["name"] = full
            # The name printed on programs and signed in emails, unless the
            # teacher has already chosen one.
            if not (t.get("display_name") or "").strip():
                t["display_name"] = full
        elementary = self._focus.get() == "elementary"
        t["program_type"] = self._focus.get()

        primary = self._primary_row()
        primary_name = (primary["name"].get().strip() if primary else "")
        # "school_name" is the key every other screen reads (Settings, the
        # loan forms, the concert programs, Reginald).  An itinerant has no
        # default school, so none is written: everything that used to read
        # this takes the school from the instrument being lent instead.
        t["school_name"] = "" if elementary else primary_name

        primary_id = None
        ordered = ([primary] if primary else []) + \
                  [r for r in self._school_rows if r is not primary]
        for rec in ordered:
            name = rec["name"].get().strip()
            if not name:
                continue
            try:
                if elementary:
                    sid = self.main_db.add_site(name, "elementary",
                                                rec["program"].get())
                else:
                    # The name decides the level.  A band teacher whose home
                    # school is an elementary one is ordinary here, and
                    # creating it as secondary charged their 5th graders a
                    # rental fee.
                    sid = self.main_db.add_site(
                        name, school_level(name),
                        (self._focus.get() or "").strip() or None)
            except Exception:
                sid = None
            if rec is primary:
                primary_id = sid
        if primary_id:
            # The school the hub opens on when there is more than one.
            t["active_site_id"] = primary_id
        save_settings(self.base_dir, s)
        return primary_id

    def _finish(self):
        if not self._validate():
            return
        primary_id = self._save()
        upload_now = bool(self._upload_now.get())
        if not upload_now:
            Messagebox.show_info(
                "When you are ready:\n\n"
                "•  Open Equipment to upload or enter your inventory.\n"
                "•  Open Students to upload or enter your class lists.\n\n"
                "Both are on the main screen.",
                title="Later, then", parent=self)
        self._done()
        if upload_now:
            self._open_import(primary_id)

    def _done(self):
        if self._on_finish:
            try:
                self._on_finish()
            except Exception:
                pass
        self.destroy()

    def _open_import(self, site_id):
        """The import window, over the main screen, once setup is saved."""
        from ui.import_wizard import ImportWizard
        try:
            from lesson_plan_db import current_school_year
            year = current_school_year()
        except Exception:
            year = None
        try:
            ImportWizard(self._app, self.main_db, self.base_dir, year,
                         site_id=site_id)
        except Exception as e:
            Messagebox.show_error(f"Could not open the import window:\n{e}\n\n"
                                  "Use Import Data on the main screen instead.",
                                  title="Import")

    def _skip(self):
        # Still record the focus so choir/orchestra don't default to band.
        if Messagebox.yesno("Skip setup for now? You can finish it later in "
                            "Settings, and bring data in from Equipment and "
                            "Students.",
                            title="Skip setup", parent=self) == "Yes":
            self._save()
            self._done()
