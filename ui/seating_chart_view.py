"""
ui/seating_chart_view.py - Classroom & concert seating chart generator.

Pick a class period (or combine ensembles for a concert), choose how many seats
are in each row and how to sort, and the tool lays students out in color-coded
rows (matching velcro carpet markers) or concert arcs.  Supports "keep apart"
conflicts, IEP/504 row placement, manual click-to-swap, and copy-to-clipboard
as an image.
"""

import json
import os
import random
import tkinter as tk
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from ttkbootstrap.dialogs import Messagebox

import seating_chart as sc
import seating_render as sr
from ui.ensembles import ensembles_for, PERIOD_OPTIONS
from ui.names import display_first_of, display_full
from ui.theme import muted_fg, fs

SORT_LABELS = [
    ("alphabetical", "Alphabetical (by last name)"),
    ("sections", "Like instruments together (whole sections)"),
    ("small_groups", "Like-instrument small groups (2–3)"),
    ("full_shuffle", "Full shuffle (mix instruments)"),
]
SORT_LABEL_TO_KEY = {v: k for k, v in SORT_LABELS}
SORT_KEY_TO_LABEL = {k: v for k, v in SORT_LABELS}


def _default_config(chart_type="concert"):
    return {
        "chart_type": chart_type,
        "groups": [],                   # [{"ensemble":..., "period": "all"|"N"}]
        "ensembles": [],                # legacy (kept for old saved charts)
        "scope": "all",                 # legacy
        "extra_students": [],           # [{"name":..., "instrument":...}] cross-ensemble adds
        # Four rows of ten and no color: a plain room, not a copy of Meagan's.
        # Her own 8/10/12/13 and row colors are a click away in Configuration,
        # and whatever a teacher sets last becomes their default (see
        # _remembered_layout).
        "row_caps": "10,10,10,10",
        "sort_mode": "sections",
        "color_mode": "none",            # "row" | "section" | "none"
        "name_display": "first",        # "first" | "last_initial" | "last_full"
        "show_instrument": True,
        "separate_percussion": True,
        "view": "rows",
        "flip": False,                  # True == front at bottom
        "center_tuba": True,
        "instrument_overrides": {},         # {str(student_id): "Flute"}
        "section_order": [],                # custom instrument ordering (blank = family default)
        "shuffle_members": False,           # randomize who sits by whom within a section
        "shuffle_sections": False,          # randomize which section is placed where
        "together": [],                     # [[nameA, nameB], ...] seat these side by side
        "zones": {},                        # {instrument: [1-based row numbers]} lock section to rows
        "side_zones": {},                   # {instrument: "left"|"right"} stage side (audience view)
        "section_zones": {},                # {instrument: 1..9} — see sc.ZONE_LABELS
        "zone_scheme": 9,                   # migrates charts saved with six
        "close_gaps": True,                 # no empty chairs inside the ensemble
        "bass_corner": True,                # orchestra: string basses in the back corner
        "bass_corner_side": "right",        # which corner (audience view)
        "numbered_parts": False,            # orchestra: offer Violin 1 / Violin 2 (MS/HS)
        "jazz_mode": False,                 # seat by jazz PART, rebuilt every draw
        "piano": False,                     # orchestra: rare, so it is its own toggle
        "seed": 1,
    }


def _program_type(base_dir):
    try:
        from ui.settings_dialog import load_settings
        return (load_settings(base_dir).get("teacher") or {}).get("program_type", "band")
    except Exception:
        return "band"


class SeatingChartView(ttk.Frame):
    def __init__(self, parent, db, main_db, base_dir):
        super().__init__(parent)
        self.db = db
        self.main_db = main_db
        self.base_dir = base_dir
        self.program_type = _program_type(base_dir)
        self._chart_id = None
        self._cfg = _default_config()
        self._apply_remembered_layout()
        self._apply_program_defaults()
        self._rows = []
        self._perc = []
        self._unseated = []
        self._unresolved = []
        self._image = None
        self._photo = None
        self._seat_boxes = {}
        self._swap_first = None
        self._dirty = False
        self._build()
        self._sync_program_ui()
        self._refresh_chart_list()
        self._update_roster_label()
        self._regenerate()

    # ─────────────────────────────────────────────────────────────── build ────

    def _build(self):
        self._chart_var = tk.StringVar()
        bar = ttk.Frame(self, bootstyle=LIGHT)
        bar.pack(fill=X)
        ttk.Label(bar, text="🪑  Seating Chart", font=("Segoe UI", fs(12), "bold")).pack(
            side=LEFT, padx=12, pady=8)
        ttk.Button(bar, text="📋 Copy Image", bootstyle=INFO,
                   command=self._copy_image).pack(side=RIGHT, padx=10, pady=6)
        ttk.Button(bar, text="💾 Save Image…", bootstyle=(INFO, OUTLINE),
                   command=self._save_image).pack(side=RIGHT, padx=2, pady=6)

        body = ttk.Panedwindow(self, orient=HORIZONTAL)
        body.pack(fill=BOTH, expand=True)

        # Scrollable left config panel (the options list is long).
        cfg_outer = ttk.Frame(body, width=310)
        cfg_outer.pack_propagate(False)
        body.add(cfg_outer, weight=0)
        cfg_canvas = tk.Canvas(cfg_outer, highlightthickness=0, width=290)
        cfg_sb = ttk.Scrollbar(cfg_outer, orient=VERTICAL, command=cfg_canvas.yview)
        cfg_canvas.configure(yscrollcommand=cfg_sb.set)
        cfg_sb.pack(side=RIGHT, fill=Y)
        cfg_canvas.pack(side=LEFT, fill=BOTH, expand=True)
        cfg = ttk.Frame(cfg_canvas)
        cfg_win = cfg_canvas.create_window((0, 0), window=cfg, anchor=NW)
        cfg.bind("<Configure>", lambda e: cfg_canvas.configure(scrollregion=cfg_canvas.bbox("all")))
        cfg_canvas.bind("<Configure>", lambda e: cfg_canvas.itemconfig(cfg_win, width=e.width))

        def _wheel(event):
            try:
                cfg_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
            except tk.TclError:
                pass
        cfg_canvas.bind("<Enter>", lambda e: cfg_canvas.bind_all("<MouseWheel>", _wheel))
        cfg_canvas.bind("<Leave>", lambda e: cfg_canvas.unbind_all("<MouseWheel>"))
        self._build_config(cfg)

        right = ttk.Frame(body)
        body.add(right, weight=1)
        self._build_canvas(right)

    def _build_config(self, parent):
        head = lambda t: ttk.Label(parent, text=t, font=("Segoe UI", fs(10), "bold"),
                                   bootstyle=PRIMARY)
        bpad = dict(padx=10)

        # ── Chart name + New / Save / Load / Shuffle ──
        head("Chart name").pack(anchor=W, padx=10, pady=(8, 0))
        self._name_var = tk.StringVar(value="Untitled Chart")
        ttk.Entry(parent, textvariable=self._name_var).pack(fill=X, **bpad)
        brow = ttk.Frame(parent)
        brow.pack(fill=X, **bpad, pady=(4, 0))
        ttk.Button(brow, text="New", bootstyle=SUCCESS,
                   command=self._new_chart).pack(side=LEFT, fill=X, expand=True, padx=(0, 2))
        ttk.Button(brow, text="Save", bootstyle=PRIMARY,
                   command=self._save_chart).pack(side=LEFT, fill=X, expand=True, padx=2)
        ttk.Button(brow, text="Load", bootstyle=(PRIMARY, OUTLINE),
                   command=self._load_dialog).pack(side=LEFT, fill=X, expand=True, padx=(2, 0))
        ttk.Button(parent, text="🔀  Shuffle…", bootstyle=SUCCESS,
                   command=self._shuffle_prompt).pack(fill=X, **bpad, pady=(4, 0))
        # On the main panel on purpose: combining two bands for one concert is
        # the moment you need it, and hunting for it inside a settings window
        # is the moment you give up.
        ttk.Button(parent, text="✨  Optimize Seats", bootstyle=(SUCCESS, OUTLINE),
                   command=self._optimize).pack(fill=X, **bpad, pady=(4, 0))
        # Jazz is a concert-band idea.  A strings or choir chart had a Jazz
        # Setup button sitting on it that could only ever produce a big-band
        # layout of instruments they do not have.
        # Its own frame, which STAYS packed whether the button is showing or
        # not.  pack_forget on the button itself would send it to the bottom of
        # the panel when it came back.
        self._jazz_slot = ttk.Frame(parent)
        self._jazz_slot.pack(fill=X, **bpad, pady=(4, 0))
        self._jazz_btn = ttk.Button(self._jazz_slot, text="🎷  Jazz Band Setup…",
                                    bootstyle=(INFO, OUTLINE),
                                    command=self._jazz_setup)
        self._jazz_btn.pack(fill=X)

        # ── Group ──
        head("Group").pack(anchor=W, padx=10, pady=(10, 0))
        self._roster_lbl = ttk.Label(parent, text="(none selected)", font=("Segoe UI", fs(9)),
                                     wraplength=270, justify=LEFT)
        self._roster_lbl.pack(anchor=W, **bpad)
        ttk.Button(parent, text="Choose group…", bootstyle=SECONDARY,
                   command=self._edit_group).pack(fill=X, **bpad, pady=(3, 0))

        # ── Configuration: everything about the CHART ──
        # There used to be three buttons within an inch of each other called
        # "Set Up", "Concert Setup" and "Student Set Up", and no way to guess
        # which held what.  Two now, split by what they are about: the chart
        # (Configuration) and the students in it (Set Up).
        ttk.Button(parent, text="⚙  Configuration…", bootstyle=SECONDARY,
                   command=self._open_configuration).pack(fill=X, **bpad, pady=(8, 0))

        # ── Group students (sort) ──
        head("Group students").pack(anchor=W, padx=10, pady=(10, 0))
        self._sort_var = tk.StringVar(value=self._cfg["sort_mode"])
        for key, label in [("alphabetical_first", "Alpha by first name"),
                           ("alphabetical", "Alpha by last name"),
                           ("small_groups", "In groups of 2–3 (like instruments)"),
                           ("sections", "By section")]:
            ttk.Radiobutton(parent, text=label, value=key, variable=self._sort_var,
                            command=self._apply_and_regen).pack(anchor=W, padx=16)

        # ── Set Up: everything about the STUDENTS in it ──
        ttk.Button(parent, text="👤  Set Up…", bootstyle=SECONDARY,
                   command=self._open_student_setup).pack(fill=X, **bpad, pady=(12, 0))
        ttk.Button(parent, text="🤖  AI Assist…", bootstyle=INFO,
                   command=self._ai_assistant).pack(fill=X, **bpad, pady=(4, 0))

        self._status = ttk.Label(parent, text="", font=("Segoe UI", fs(9)),
                                 wraplength=270, justify=LEFT)
        self._status.pack(anchor=W, **bpad, pady=(12, 0))
        ttk.Label(parent, text="Tip: click one seat then another to swap them.",
                  font=("Segoe UI", fs(8)), foreground=muted_fg()).pack(anchor=W, **bpad, pady=(6, 8))

    def _build_canvas(self, parent):
        # Red warning banner directly under the chart image.
        self._warn_lbl = ttk.Label(parent, text="", foreground="#d32f2f",
                                   font=("Segoe UI", fs(10), "bold"),
                                   wraplength=1000, justify=LEFT)
        self._warn_lbl.pack(side=BOTTOM, fill=X, padx=12, pady=(2, 8))

        wrap = ttk.Frame(parent)
        wrap.pack(fill=BOTH, expand=True)
        self._canvas = tk.Canvas(wrap, background="#ffffff", highlightthickness=0)
        vsb = ttk.Scrollbar(wrap, orient=VERTICAL, command=self._canvas.yview)
        hsb = ttk.Scrollbar(wrap, orient=HORIZONTAL, command=self._canvas.xview)
        self._canvas.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        vsb.pack(side=RIGHT, fill=Y)
        hsb.pack(side=BOTTOM, fill=X)
        self._canvas.pack(fill=BOTH, expand=True)
        self._canvas.bind("<Button-1>", self._on_canvas_click)

    # ─────────────────────────────────────────────────── config plumbing ────

    def _collect_cfg(self):
        # A blank radio value means a full scramble is active — keep it.
        if self._sort_var.get():
            self._cfg["sort_mode"] = self._sort_var.get()
        # Everything else (row_caps, view, flip, colors, display, section
        # placement) is edited in the Set Up dialog and lives in self._cfg.

    def _apply_and_regen(self):
        self._collect_cfg()
        self._regenerate()

    def _ensure_sections_mode(self):
        """Shuffling and section-order only mean something when grouped by
        section, so switch the sort there (updating the radios too)."""
        if self._cfg.get("sort_mode") != "sections":
            self._cfg["sort_mode"] = "sections"
            self._sort_var.set("sections")

    def _shuffle_members(self):
        """Shuffle who sits where WITHIN each section — in place.  Sections
        (and every empty/reserved seat) stay exactly where they are; only the
        people inside each section trade seats.  Students with accommodations
        (front/back/edge or a reserved buffer beside them) stay put."""
        rng = random.Random()

        def movable(x):
            return bool(x and not x.get("reserved") and not x.get("pref")
                        and not int(x.get("buffer") or 0))

        for _ in range(8):    # retry if a keep-apart pair lands adjacent
            by_inst = {}
            for ri, row in enumerate(self._rows):
                for ci, x in enumerate(row):
                    if movable(x):
                        by_inst.setdefault(x.get("instrument") or "", []).append((ri, ci))
            for seats in by_inst.values():
                occ = [self._rows[r][c] for r, c in seats]
                rng.shuffle(occ)
                for (r, c), o in zip(seats, occ):
                    self._rows[r][c] = o
            pidx = [i for i, p in enumerate(self._perc or []) if movable(p)]
            pocc = [self._perc[i] for i in pidx]
            rng.shuffle(pocc)
            for i, o in zip(pidx, pocc):
                self._perc[i] = o
            if not self._adjacent_conflicts():
                break
        self._dirty = True
        self._render()

    def _adjacent_conflicts(self):
        """True if any keep-apart pair sits with fewer than 2 students between
        them in the same row (same rule the layout engine enforces)."""
        conf = self._conflict_set()
        if not conf:
            return False
        for row in self._rows:
            named = [(ci, x) for ci, x in enumerate(row)
                     if x and not x.get("reserved")]
            for i in range(len(named)):
                for j in range(i + 1, len(named)):
                    if named[j][0] - named[i][0] >= 3:
                        break
                    pair = frozenset({(named[i][1].get("name") or "").lower(),
                                      (named[j][1].get("name") or "").lower()})
                    if pair in conf:
                        return True
        return False

    def _shuffle_sections(self):
        """Move whole sections to different parts of the room, at random.

        This used to shuffle the section ORDER, which is not the same thing:
        once sections had zones, reordering the list changed only who was
        seated first and everybody stayed exactly where they were, so the
        button appeared to do nothing.  It now deals the sections out into
        random zones, which is what "move sections somewhere else" means.

        Nothing to do with concert order -- the point is a room the students
        have not seen before.
        """
        caps = sc.parse_row_caps(self._cfg["row_caps"])
        roster = self._resolve_roster()
        sections = self._section_list()
        if not sections:
            Messagebox.show_info("Choose a group first.", title="No Sections",
                                 parent=self)
            return
        counts = {}
        for st in roster:
            inst = (st.get("instrument") or "").strip()
            if inst:
                counts[inst] = counts.get(inst, 0) + 1
        self._cfg["section_zones"] = sc.random_zone_assignment(
            sections, counts, caps, random.Random())
        self._cfg["shuffle_sections"] = False
        self._ensure_sections_mode()
        self._cfg["seed"] = random.randint(1, 10_000_000)
        self._apply_and_regen()

    def _optimize(self):
        """Fit the room to the ensemble, in one click.

        Adds chairs and rows when people do not fit -- combining an
        intermediate and an advanced band for one concert doubles the room
        overnight -- and takes away chairs nobody is sitting in, so the
        formation is not full of holes.  The shape of the room is kept, so a
        concert arc stays an arc.
        """
        roster = self._resolve_roster()
        if not roster:
            Messagebox.show_info("Choose a group first.", title="No Students",
                                 parent=self)
            return
        if self._cfg.get("jazz_mode"):
            # A jazz chart already works its own room out from the parts, and
            # the concert sizing pulled the band apart into rows of its own.
            self._regenerate()
            self._status.config(
                text="%d seated by jazz part.  The rows fit the band already; "
                     "change parts in Jazz Band Setup." % len(roster))
            return
        seated = roster
        if self._cfg.get("separate_percussion", True):
            # Percussion has its own row (and wraps on its own), so it must not
            # count toward the width of the rows in front of it.
            seated = [s for s in roster
                      if sc.family(s.get("instrument")) != "Percussion"]
        # Reserved seats beside a student are seats too.
        need = len(seated) + sum(int(s.get("buffer") or 0) for s in seated)

        before = sc.parse_row_caps(self._cfg.get("row_caps") or "8")
        after = sc.optimize_row_caps(need, before)
        self._cfg["row_caps"] = ",".join(str(c) for c in after)
        self._cfg["close_gaps"] = True
        self._regenerate()

        # An exact fit is not always seatable: in 2s and 3s a group will
        # not split across a row, so a room with precisely enough chairs
        # can still leave somebody standing.  Rather than reason about it,
        # add the seats that turned out to be missing and look again.
        for _ in range(4):
            if not self._unseated:
                break
            after = sc.optimize_row_caps(
                sum(after) + len(self._unseated) + 1, after)
            self._cfg["row_caps"] = ",".join(str(c) for c in after)
            self._regenerate()
        self._remember_layout()

        was, now = sum(before), sum(after)
        bits = [f"{len(seated)} to seat."]
        if len(after) != len(before):
            bits.append(f"{len(before)} rows → {len(after)}.")
        bits.append(f"{was} chairs → {now}.")
        if self._unseated:
            bits.append(f"⚠ {len(self._unseated)} still do not fit — "
                        f"the room is capped at {sc.MAX_ROWS} rows.")
        self._status.config(text="  ".join(bits))

    def _jazz_parts_map(self, roster):
        """{student id: part}, from the student records, guessed where blank."""
        parts = {s["id"]: (s.get("jazz_part") or "") for s in roster}
        missing = [s for s in roster if not parts.get(s["id"])]
        if missing:
            # The guess must not hand out a chair somebody already has.
            guessed = sc.jazz_auto_parts(missing, taken=parts.values())
            for sid, guess in guessed.items():
                parts[sid] = guess
        return parts

    def _render_jazz(self):
        """Lay the band out by part and draw it."""
        roster = self._resolve_roster()
        self._roster = {s["id"]: s for s in roster}
        if not roster:
            self._rows, self._perc, self._unseated, self._unresolved = [], [], [], []
            self._render()
            return
        rows, caps, rhythm = sc.jazz_seating(
            roster, self._jazz_parts_map(roster),
            self._cfg.get("jazz_side", "left"),
            int(self._cfg.get("jazz_high_rows", 1)))
        self._cfg["row_caps"] = ",".join(str(c) for c in caps)
        self._caps = caps
        self._rows = rows
        self._jazz_rhythm = rhythm
        self._perc = []
        self._unseated = []
        self._unresolved = []
        self._render()

    def _shuffle_small_groups(self):
        """Break the room into 2s (and a 3 where a section is odd), mixed up.

        Part independence with training wheels: everybody has a buddy on the
        same part nearby, but the section as a block is gone.
        """
        self._cfg["sort_mode"] = "small_groups"
        self._sort_var.set("small_groups")
        self._cfg["seed"] = random.randint(1, 10_000_000)
        self._cfg["shuffle_members"] = False
        self._cfg["shuffle_sections"] = False
        self._regenerate()

    def _shuffle_all(self):
        """True scramble: everyone gets a new seat and new neighbors, every
        click (fresh random seed each time; ignores section grouping)."""
        self._cfg["seed"] = random.randint(1, 10_000_000)
        self._cfg["shuffle_members"] = False
        self._cfg["shuffle_sections"] = False
        self._cfg["sort_mode"] = "full_shuffle"
        self._sort_var.set("")   # no radio lit while fully scrambled
        self._regenerate()

    def _shuffle_prompt(self):
        _ShufflePrompt(self.winfo_toplevel(), self._shuffle_all,
                       self._shuffle_members, self._shuffle_sections,
                       self._shuffle_small_groups,
                       self._clear_concert_setup,
                       has_setup=bool(self._cfg.get("section_order")
                                      or self._cfg.get("section_zones")
                                      or self._cfg.get("zones")
                                      or self._cfg.get("side_zones")))

    def _clear_concert_setup(self):
        self._cfg["section_order"] = []
        self._cfg["section_zones"] = {}
        self._cfg["zones"] = {}
        self._cfg["side_zones"] = {}

    def _reset_shuffle(self):
        self._cfg["shuffle_members"] = False
        self._cfg["shuffle_sections"] = False
        self._apply_and_regen()

    # ─────────────────────────────────────────────────────── data + render ────

    def _year(self):
        base = os.path.basename(self.db.db_path)
        if base.startswith("lesson_plans_") and base.endswith(".db"):
            return base[len("lesson_plans_"):-len(".db")]
        return None

    def _student_year(self):
        """Rosters follow the hub's selected school year (matching how the
        concert program picks students); fall back to the newest year."""
        years = self.main_db.get_school_years()
        hub_year = self._year()
        if hub_year and hub_year in years:
            return hub_year
        return years[0] if years else None

    @staticmethod
    def _row_value(row, key):
        """One column off a student row, or "" if this database predates it."""
        try:
            return (row[key] or "").strip()
        except (KeyError, IndexError, TypeError):
            return ""

    def _effective_instrument(self, student_id, primary, secondary,
                              jazz_instrument=""):
        """Which instrument to seat a student by.

        A per-student override for THIS chart wins.  Then, on a jazz chart,
        what they play in jazz band -- the Student Manager has had a "Jazz Band
        Instrument" box for exactly this since long before the jazz chart did,
        and a horn player who covers guitar was still being seated as a horn.
        Otherwise their primary instrument.
        """
        override = (self._cfg.get("instrument_overrides") or {}).get(str(student_id))
        if override:
            return override
        if jazz_instrument and self._is_jazz_chart():
            return jazz_instrument
        return (primary or "").strip()

    def _is_jazz_chart(self):
        """Is this chart for a jazz band?

        True once Jazz Band Setup has been applied, and also when the class
        being seated is a jazz class -- so the jazz instrument is used from the
        first draw rather than only after a trip through the setup window.
        """
        if self._cfg.get("jazz_mode"):
            return True
        try:
            import class_registry as cr
            labels = [g.get("ensemble") for g in self._groups() if g.get("ensemble")]
            if not labels:
                return False
            classes = cr.load_classes(self.base_dir, self.program_type)
            for label in labels:
                for k in classes:
                    if cr.same_class(k.get("label"), label):
                        if k.get("template") == "jazz":
                            return True
                if "jazz" in (label or "").lower():
                    return True
        except Exception:
            pass
        return False

    def _groups(self):
        """Normalized selection list [{'ensemble':.., 'period': 'all'|'N'}].
        Migrates the legacy ensembles+scope config on the fly."""
        groups = self._cfg.get("groups")
        if groups:
            return groups
        ens = self._cfg.get("ensembles") or []
        if ens:
            scope = self._cfg.get("scope", "all")
            return [{"ensemble": e, "period": scope} for e in ens]
        return []

    def _resolve_roster(self):
        year = self._student_year()
        groups = self._groups()
        seen = {}
        # No group chosen -> start blank (you'd never seat every student at once).
        for g in groups:
            e = g.get("ensemble")
            p = g.get("period", "all")
            period = None if p in ("all", "", None) else str(p)
            for r in self.main_db.get_students_for_email(
                    school_year=year, ensemble=e, period=period):
                seen[r["id"]] = r
        studs = []
        for r in seen.values():
            base = display_first_of(r)
            studs.append({
                "id": r["id"], "base": base, "name": base,
                "first": r["first_name"] or "", "last": r["last_name"] or "",
                "primary": (r["primary_instrument"] or "").strip(),
                "secondary": (r["secondary_instrument"] or "").strip(),
                "jazz_instrument": self._row_value(r, "jazz_instrument"),
                "jazz_part": self._row_value(r, "jazz_part"),
                "instrument": self._effective_instrument(
                    r["id"], r["primary_instrument"], r["secondary_instrument"],
                    self._row_value(r, "jazz_instrument")),
            })
        # Extra students typed in from another ensemble (rare concert combos).
        for i, ex in enumerate(self._cfg.get("extra_students") or []):
            nm = (ex.get("name") or "").strip()
            if not nm:
                continue
            xid = f"x{i}"
            inst = (self._cfg.get("instrument_overrides") or {}).get(xid) or (ex.get("instrument") or "").strip()
            studs.append({"id": xid, "base": nm, "name": nm, "first": nm, "last": nm,
                          "primary": inst, "secondary": "", "instrument": inst})

        self._apply_name_display(studs, self._cfg.get("name_display", "first"))

        # Apply accommodations (pins) by final (disambiguated) display name.
        pins = {p["student_name"]: p for p in self.db.get_seating_pins(self._year())}
        for s in studs:
            pin = pins.get(s["name"])
            s["pref"] = (pin["pref"] if pin else None)
            s["note"] = (pin["note"] if pin else "")
            s["buffer"] = (self._pin_buffer(pin) if pin else 0)
        return studs

    @staticmethod
    def _pin_buffer(pin):
        try:
            return int(pin["buffer"] or 0)
        except (KeyError, TypeError, IndexError):
            return 0

    @staticmethod
    def _apply_name_display(studs, mode):
        """Set each student's display ``name``.

        mode 'last_initial'  -> "First L." for everyone
        mode 'last_full'     -> "First Last" for everyone
        mode 'first' (default) -> just the first name, adding a last initial (or
        full last name) ONLY where several students share a first name.
        """
        if mode == "last_full":
            for s in studs:
                s["name"] = f"{s['base']} {s['last']}".strip()
            return
        if mode == "last_initial":
            for s in studs:
                li = (s["last"][:1] or "").upper()
                s["name"] = f"{s['base']} {li}." if li else s["base"]
            return
        # 'first' — disambiguate only on collision, per student: two Andrews
        # become "Andrew K." and "Andrew S.", and only students whose last
        # INITIALS also collide (Andrew Kim / Andrew Kam) escalate to the full
        # last name.  A third Andrew with a unique initial keeps "Andrew S." —
        # the escalation never spreads past the students who actually need it.
        from collections import defaultdict
        groups = defaultdict(list)
        for s in studs:
            groups[s["base"]].append(s)
        for base, members in groups.items():
            if len(members) < 2:
                members[0]["name"] = base
                continue
            inits = [(m["last"][:1] or "").upper() for m in members]
            for m, ini in zip(members, inits):
                if ini and inits.count(ini) == 1:
                    m["name"] = f"{base} {ini}."
                else:
                    m["name"] = f"{base} {m['last']}".strip()

    # What a new chart inherits from the last one they set up.  Room shape and
    # appearance only -- never a placement, which belongs to the group being
    # seated, and never the group itself.
    _REMEMBERED_KEYS = ("row_caps", "view", "flip", "color_mode",
                        "show_instrument", "name_display",
                        "separate_percussion", "center_tuba",
                        "bass_corner", "bass_corner_side",
                        "numbered_parts", "piano", "close_gaps")

    def _remember_layout(self):
        """Keep the room they just described, so the next new chart opens as
        their room rather than as the built-in default."""
        try:
            from ui.settings_dialog import load_settings, save_settings
            cfg = load_settings(self.base_dir) or {}
            cfg.setdefault("seating", {})["layout"] = {
                k: self._cfg.get(k) for k in self._REMEMBERED_KEYS
                if k in self._cfg}
            save_settings(self.base_dir, cfg)
        except Exception:
            pass

    def _apply_remembered_layout(self):
        """The saved room shape, over the built-in default, on a NEW chart."""
        try:
            from ui.settings_dialog import load_settings
            saved = ((load_settings(self.base_dir).get("seating") or {})
                     .get("layout") or {})
        except Exception:
            saved = {}
        for k in self._REMEMBERED_KEYS:
            if k in saved and saved[k] is not None:
                self._cfg[k] = saved[k]

    def _sync_program_ui(self):
        """Show only what this chart's program can use.

        Called whenever the chosen class changes, because the answer changes
        with it: the same window is a band chart one minute and a 5th grade
        strings chart the next.
        """
        program, _level = self._chart_program()
        try:
            if program == "band":
                self._jazz_btn.pack(fill=X)
            else:
                self._jazz_btn.pack_forget()
        except Exception:
            pass

    def _chart_program(self):
        """``(program, level)`` for the class this chart is seating.

        Not the profile's program type: a teacher can run a 5th grade strings
        class at one building and a concert band at another, and the chart in
        front of them belongs to exactly one of those.  Everything that used to
        read ``self.program_type`` -- the instrument list, which placement
        options appear, whether Jazz Setup is offered -- reads this instead.

        A chart seating two classes at once (a combined concert) only gets one
        answer, so when the groups disagree the profile's own program is used
        rather than picking one class's program for all of them.
        """
        from ui.ensembles import class_program
        groups = [g.get("ensemble") for g in self._groups() if g.get("ensemble")]
        answers = []
        for label in groups:
            try:
                answers.append(class_program(self.main_db, label, self.base_dir,
                                             self.program_type))
            except Exception:
                pass
        if answers and all(a == answers[0] for a in answers):
            return answers[0]
        if self.program_type in ("band", "orchestra", "choir"):
            return (self.program_type, "secondary")
        if self.program_type == "elementary":
            # Every school they have is elementary; the program still has to
            # come from a school, so use one only when they all agree.
            try:
                progs = {(dict(s).get("program") or "").lower()
                         for s in self.main_db.get_sites()
                         if (dict(s).get("program") or "").strip()}
            except Exception:
                progs = set()
            if len(progs) == 1:
                return (progs.pop(), "elementary")
            return ("band", "elementary")
        return ("band", "secondary")

    def _zones_0based(self, caps):
        """Convert cfg zones {instrument: [1-based rows]} to {instrument:
        [0-based indices]} within the current row count."""
        n = len(caps)
        out = {}
        for inst, rows in (self._cfg.get("zones") or {}).items():
            idxs = sorted({int(r) - 1 for r in rows if 1 <= int(r) <= n})
            if idxs:
                out[inst] = idxs
        return out or None

    # How a roster might spell the basses.  Only consulted for an ORCHESTRA
    # chart, so plain "Bass" is safe here — in a choir it is a voice part.
    _BASS_NAMES = ("String Bass", "Double Bass", "Upright Bass", "Bass")

    # The standard string layout, in zone numbers, off a normal orchestra
    # chart: firsts front on stage right, seconds just behind them, the violas
    # as the middle wedge (where she says they go, and where the chart puts
    # them), cellos stage left.  The basses are not here -- they have their own
    # check box, because they are the one section a director nearly always wants
    # pinned whatever else they have done.
    _ORCHESTRA_DEFAULT_ZONES = {
        "Violin": 1, "Violin 1": 1,
        "Violin 2": 4,
        "Viola": 2, "Viola 1": 2, "Viola 2": 2,
        "Cello": 3, "Cello 1": 3, "Cello 2": 3,
    }

    # A SYMPHONY orchestra -- strings with winds, brass and percussion behind
    # them -- off the standard chart.  The strings keep the front: firsts stage
    # right, seconds beside them, violas the middle wedge, cellos stage left,
    # basses behind the cellos.  Woodwinds sit in the middle across the centre,
    # horns / trumpets / low brass line the back, and the percussion has its own
    # row further back still.  Harp and piano stand at the stage-right edge.
    _SYMPHONY_DEFAULT_ZONES = {
        # front: the string body
        "Violin": 1, "Violin 1": 1, "Violin 2": 1,
        "Viola": 2, "Viola 1": 2, "Viola 2": 2,
        "Cello": 3, "Cello 1": 3, "Cello 2": 3,
        # middle: keyboards and harp at the edge, winds across the centre,
        # basses standing behind the cellos
        "Harp": 4, "Piano": 4,
        "Flute": 5, "Piccolo": 5, "Oboe": 5, "English Horn": 5,
        "Clarinet": 5, "Bass Clarinet": 5, "Bassoon": 5, "Contrabassoon": 5,
        "Alto Sax": 5, "Tenor Sax": 5, "Bari Sax": 5,
        "String Bass": 6, "Double Bass": 6, "Upright Bass": 6,
        # back: brass
        "French Horn": 7,
        "Trumpet": 8,
        "Trombone": 9, "Tuba": 9,
        "Baritone BC": 9, "Baritone TC": 9,
        "Euphonium BC": 9, "Euphonium TC": 9, "Baritone/Euphonium": 9,
    }

    _BOWED = ("Violin", "Viola", "Cello")

    def _is_symphony(self, roster=None):
        """Bowed strings AND winds on the same chart, whichever program owns it.

        A string orchestra fills the stage with strings; a symphony pushes them
        forward and stacks the winds, brass and percussion behind.  The roster
        says which one this is, so there is nothing to ask -- and it works both
        ways around: an orchestra that gains winds AND a band that gains a
        string section both read as a symphony.  A lone string bass does not
        count as a string section; jazz bands carry one, and so do some
        concert bands.
        """
        if self._cfg.get("jazz_mode") or self._is_jazz_chart():
            return False
        try:
            roster = self._resolve_roster() if roster is None else roster
        except Exception:
            return False
        bowed = wind = False
        for x in roster:
            inst = (x.get("instrument") or "")
            if any(inst.startswith(b) for b in self._BOWED):
                bowed = True
            elif sc.family(inst) in ("Woodwind", "Brass", "Percussion"):
                wind = True
        return bowed and wind

    def _orchestra_defaults(self, roster=None):
        return (self._SYMPHONY_DEFAULT_ZONES if self._is_symphony(roster)
                else self._ORCHESTRA_DEFAULT_ZONES)

    def _effective_placement(self, caps):
        """(zones, side_zones) to seat by, in the layout engine's terms.

        Three sources, narrowest last:

          * the program's default layout, while the teacher has placed nothing
          * the six zones they assigned in Configuration
          * the string-bass corner checkbox, which holds whatever else they do

        Zones are stored as the NUMBER (1-6), not as rows and a side, so they
        keep meaning the same thing when the room grows a row or gets turned
        around.  They are turned into rows and sides here, against the row
        count actually in force.
        """
        n = len(caps)
        zones = self._zones_0based(caps) or {}
        sides = dict(self._cfg.get("side_zones") or {})
        assigned = dict(self._cfg.get("section_zones") or {})
        program, _level = self._chart_program()
        customized = bool(zones or sides or assigned
                          or self._cfg.get("section_order"))

        if not customized and (program == "orchestra" or self._is_symphony()):
            # An orchestra gets its string layout; ANY chart that has become a
            # symphony -- an orchestra that gained winds, or a band that gained
            # a string section for one concert -- gets the symphony layout.
            for inst, z in self._orchestra_defaults().items():
                assigned.setdefault(inst, z)

        cols = {}
        for inst, z in assigned.items():
            rows, side = sc.zone_rows_side(z, n)
            if rows:
                zones[inst] = rows
                sides[inst] = side
                # A zone is a box a third of the room wide, not a whole row.
                cols[inst] = (lambda zz: (lambda cap: sc.zone_columns(zz, cap)))(z)

        anchors = {}
        if program == "orchestra" and self._cfg.get("bass_corner", True):
            corner = self._cfg.get("bass_corner_side", "right")
            for b in self._BASS_NAMES:
                if n > 1:
                    zones.setdefault(b, [n - 1])
                sides.setdefault(b, corner)
                # The one placement that hugs the wall even in a half-empty
                # room, because the teacher asked for a CORNER.
                anchors[b] = corner
        return (zones or None), (sides or None), (cols or None), (anchors or None)

    def _conflict_set(self):
        out = set()
        for c in self.db.get_seating_conflicts(self._year()):
            out.add(frozenset({(c["name_a"] or "").lower(), (c["name_b"] or "").lower()}))
        return out

    def _pad(self, rows, caps):
        out = []
        for r, row in enumerate(rows):
            cap = sc.row_capacity(caps, r)
            rr = list(row) + [None] * (cap - len(row))
            out.append(rr[:cap] if cap < len(rr) else rr)
        return out

    def _regenerate(self, from_layout=None):
        caps = sc.parse_row_caps(self._cfg["row_caps"])
        self._caps = caps
        roster = self._resolve_roster()
        self._roster = {s["id"]: s for s in roster}
        zones, side_zones, zone_cols, anchors = self._effective_placement(caps)
        self._unseated = []

        self._jazz_rhythm = []
        if self._cfg.get("jazz_mode") and from_layout is None:
            # Rebuilt from the parts every time, not stamped once and hoped
            # for.  Applying it as a fixed layout meant anything that redrew
            # the chart -- Optimize, a sort radio, reopening it -- threw the
            # band back into concert rows.
            self._render_jazz()
            return

        if from_layout is not None:
            rows_data = from_layout.get("rows", []) if isinstance(from_layout, dict) else from_layout
            perc_data = from_layout.get("perc", []) if isinstance(from_layout, dict) else []

            def seat(sid):
                if sid is None:
                    return None
                if sid == "R":     # reserved (empty-beside) seat
                    return {"reserved": True, "name": "", "instrument": "", "pref": None}
                return self._roster.get(sid)

            rows = [[seat(sid) for sid in row] for row in rows_data]
            self._rows = self._pad(rows, caps)
            self._perc = [self._roster.get(sid) for sid in perc_data if self._roster.get(sid)]
            self._unresolved = []
        else:
            built, unresolved, perc, unseated = sc.build_chart(
                roster, self._cfg["sort_mode"], caps, concert=True,
                conflicts=self._conflict_set(),
                center_tuba=self._cfg["center_tuba"], seed=self._cfg["seed"],
                separate_percussion=self._cfg.get("separate_percussion", True),
                section_order=self._cfg.get("section_order") or None,
                shuffle_members=self._cfg.get("shuffle_members", False),
                shuffle_sections=self._cfg.get("shuffle_sections", False),
                together=self._cfg.get("together") or None,
                zones=zones, side_zones=side_zones, zone_cols=zone_cols,
                close_gaps=self._cfg.get("close_gaps", True), anchors=anchors)
            self._rows = self._pad(built, caps)
            self._perc = list(perc)
            self._unresolved = unresolved
            self._unseated = unseated
        self._swap_first = None
        self._render()

    def _render(self):
        perc = [p for p in (self._perc or []) if p] or None
        color_mode = self._cfg.get("color_mode", "row")
        show_inst = self._cfg.get("show_instrument", True)
        flip = self._cfg.get("flip", False)
        front = "FRONT OF THE ROOM"
        rhythm = list(getattr(self, "_jazz_rhythm", None) or [])
        side = self._cfg.get("jazz_side", "left")
        try:
            if self._cfg.get("view") == "arcs":
                img, boxes = sr.render_arcs(
                    self._rows, self._caps, flip=flip, percussion=perc,
                    show_instrument=show_inst, color_mode=color_mode,
                    front_label=front, jazz_rhythm=rhythm, rhythm_side=side)
            else:
                img, boxes = sr.render_rows(
                    self._rows, self._caps, flip=flip, percussion=perc,
                    front_label=front, show_instrument=show_inst,
                    color_mode=color_mode, jazz_rhythm=rhythm,
                    rhythm_side=side)
        except Exception as e:
            self._status.config(text=f"Render error: {e}")
            return
        self._image = img
        self._seat_boxes = boxes
        from PIL import ImageTk
        self._photo = ImageTk.PhotoImage(img)
        self._canvas.delete("all")
        self._canvas.create_image(0, 0, anchor="nw", image=self._photo)
        self._canvas.config(scrollregion=(0, 0, img.width, img.height))
        self._update_status()

    def _update_status(self):
        n = (sum(1 for row in self._rows for x in row if x and not x.get("reserved"))
             + len([p for p in (self._perc or []) if p and not p.get("reserved")])
             + len([p for p in (getattr(self, "_jazz_rhythm", None) or []) if p]))
        if n == 0 and not self._groups() and not (self._cfg.get("extra_students")):
            self._status.config(text="Choose a group to begin.")
        else:
            self._status.config(text=f"{n} seated.")
        # Problems go in the red banner under the chart.
        warns = []
        if self._unseated:
            who = ", ".join(s["name"] for s in self._unseated[:8])
            more = "…" if len(self._unseated) > 8 else ""
            warns.append(f"⚠ {len(self._unseated)} students don't fit the "
                         f"current rows — click Optimize Seats, or add a "
                         f"row in Configuration ({who}{more}).")
        if self._unresolved:
            pairs = "; ".join(f"{a} & {b}" for a, b in self._unresolved[:4])
            warns.append(f"⚠ Couldn't keep these apart: {pairs}.")
        self._warn_lbl.config(text="   ".join(warns))

    # ─────────────────────────────────────────────────────── canvas clicks ────

    def _seat_get(self, key):
        r, c = key
        if r == "P":
            return self._perc[c] if c < len(self._perc) else None
        if r == "J":
            rh = getattr(self, "_jazz_rhythm", None) or []
            return rh[c] if c < len(rh) else None
        return self._rows[r][c] if c < len(self._rows[r]) else None

    def _seat_set(self, key, val):
        r, c = key
        if r == "P":
            while len(self._perc) <= c:
                self._perc.append(None)
            self._perc[c] = val
        elif r == "J":
            rh = getattr(self, "_jazz_rhythm", None) or []
            if c < len(rh):
                rh[c] = val
        else:
            self._rows[r][c] = val

    def _seat_at(self, x, y):
        for key, (x0, y0, x1, y1) in self._seat_boxes.items():
            if x0 <= x <= x1 and y0 <= y <= y1:
                return key
        return None

    def _on_canvas_click(self, event):
        x = self._canvas.canvasx(event.x)
        y = self._canvas.canvasy(event.y)
        seat = self._seat_at(x, y)
        if seat is None:
            return
        occupant = self._seat_get(seat)
        if self._swap_first is None:
            if occupant is None:
                return
            self._swap_first = seat
            self._highlight(seat)
        else:
            a = self._swap_first
            va, vb = self._seat_get(a), self._seat_get(seat)
            self._seat_set(a, vb)
            self._seat_set(seat, va)
            self._swap_first = None
            self._dirty = True
            self._render()

    def _highlight(self, seat):
        box = self._seat_boxes.get(seat)
        if not box:
            return
        x0, y0, x1, y1 = box
        self._canvas.create_rectangle(x0, y0, x1, y1, outline="#1a73e8", width=3, tags="hl")

    # ─────────────────────────────────────────────────────── group / setup ───

    def _roster_ensembles(self, year):
        """The classes this chart can be built from — the ones the ROSTER uses.

        Offering only the class-registry labels means a roster imported with
        different names ("Entry Band" vs "MS Band (Entry)") produces an empty
        picker and a chart that can never be built.  Shared with every other
        class picker in the app — see ui.ensembles.selectable_ensembles."""
        from ui.ensembles import selectable_ensembles
        return selectable_ensembles(self.main_db, year, self.program_type)

    def _ensemble_periods(self):
        """{ensemble: [real class periods]} for ensembles that have students.

        Only the ensemble's genuine section periods are returned (a period is
        kept only if it holds at least half as many of the ensemble's students
        as its biggest section — this drops stray periods that come from a
        student's OTHER classes).  Jazz ensembles meet before school as a club,
        so they get an empty period list (whole-ensemble only)."""
        from collections import Counter
        year = self._student_year()
        out = {}
        for e in self._roster_ensembles(year):
            studs = self.main_db.get_students_for_email(school_year=year, ensemble=e)
            if not studs:
                continue
            if "jazz" in e.lower():
                out[e] = []
                continue
            cnt = Counter()
            for r in studs:
                for p in (r["class_periods"] or "").split(","):
                    p = p.strip()
                    if p:
                        cnt[p] += 1
            if not cnt:
                out[e] = []
                continue
            mx = max(cnt.values())
            out[e] = sorted([p for p, c in cnt.items() if c >= mx * 0.5],
                            key=lambda x: (len(x), x))
        return out

    def _roster_diagnostic(self):
        """Why the class picker might be empty, in the teacher's terms."""
        year = self._student_year()
        try:
            all_years = self.main_db.get_school_years()
        except Exception:
            all_years = []
        try:
            # level=None: this is a COUNT of the teacher's own roster, not a
            # contact list.  Left at the secondary default it told an
            # elementary teacher their year had 0 students while four of
            # their 5th graders sat in it -- the one message on the screen
            # whose whole job is to say where the students went.
            n = len(self.main_db.get_students_for_email(school_year=year,
                                                        level=None))
        except Exception:
            n = 0
        bits = [f"Looking at the {year or 'current'} school year, "
                f"which has {n} student{'' if n == 1 else 's'}."]
        if not n:
            other = [y for y in all_years if y != year]
            if other:
                bits.append("Your students are recorded under: "
                            + ", ".join(other) + ".  Switch the Year at the top "
                            "of Teacher Tools, or run New School Year on the "
                            "main menu to bring them forward.")
            else:
                bits.append("Add or import students in Manage Students first.")
        else:
            bits.append("Those students have no class/ensemble set. Open "
                        "Manage Students, check the students, and use "
                        "“🏷️ Assign” to put them in a class.")
        return "  ".join(bits)

    def _edit_group(self):
        dlg = _GroupDialog(self.winfo_toplevel(), self._ensemble_periods(),
                           self._groups(), self._cfg.get("extra_students") or [],
                           diagnostic=self._roster_diagnostic())
        self.wait_window(dlg)
        if dlg.result is None:
            return
        self._cfg["groups"] = dlg.result["groups"]
        self._cfg["ensembles"] = []       # supersede legacy
        self._cfg["extra_students"] = dlg.result["extra"]
        # The class decides the program, so choosing one can change which
        # options apply -- a band chart pointed at a strings class keeps
        # "percussion in a back row" on until this runs.
        self._apply_program_defaults()
        self._sync_program_ui()
        self._update_roster_label()
        self._regenerate()

    def _update_roster_label(self):
        groups = self._groups()
        extra = self._cfg.get("extra_students") or []
        if not groups and not extra:
            self._roster_lbl.config(text="No group chosen yet.\nClick “Choose group…” to begin.")
            return
        import class_registry as cr
        parts = [f"{cr.short_class_label(g['ensemble'])}"
                 + ("" if g.get('period', 'all') in ('all', '', None) else f" · P{g['period']}")
                 for g in groups]
        txt = "; ".join(parts) if parts else "Added students"
        if extra:
            txt += f"  (+{len(extra)} added)"
        n = len(self._resolve_roster())
        self._roster_lbl.config(text=f"{txt}\n{n} students")

    def _section_list(self):
        """The instrument sections on this chart, in their placement order."""
        roster = self._resolve_roster()
        seen, uniq = set(), []
        for s in roster:
            inst = (s.get("instrument") or "").strip()
            if inst and inst not in seen:
                seen.add(inst)
                uniq.append(inst)
        cur = self._cfg.get("section_order") or []
        uniq.sort(key=lambda i: (cur.index(i) if i in cur else 999,
                                 sc.concert_rank(i), i))
        return uniq

    def _open_configuration(self):
        program, level = self._chart_program()
        dlg = _ConfigurationDialog(
            self.winfo_toplevel(), self._cfg, program, level,
            sections=self._section_list())
        self.wait_window(dlg)
        if dlg.result is None:
            return
        had_order = bool(self._cfg.get("section_order"))
        self._cfg.update(dlg.result)
        self._remember_layout()
        # Zones and section order only mean anything grouped by section.
        # Switch the sort only when they actually placed something, so
        # opening Configuration to change a color does not silently
        # re-sort the chart.
        if (self._cfg.get("section_order")
                or self._cfg.get("section_zones") or had_order):
            self._ensure_sections_mode()
        self._regenerate()

    def _open_student_setup(self):
        roster = self._resolve_roster()
        _StudentSetupDialog(self.winfo_toplevel(), self, roster)
        self._regenerate()

    # ─────────────────────────────────────────────────────── chart CRUD ───────

    def _refresh_chart_list(self):
        # Each school year already has its own lesson-plans database file, so
        # list every chart in this year's file — filtering again by the stored
        # year label could hide charts if the label was ever stamped oddly.
        self._charts = list(self.db.get_seating_charts(None))

    def _load_dialog(self):
        self._refresh_chart_list()
        if not self._charts:
            Messagebox.show_info("No saved charts yet.", title="Load Chart", parent=self)
            return
        dlg = _LoadDialog(self.winfo_toplevel(), self._charts)
        self.wait_window(dlg)
        if dlg.action == "load" and dlg.chart_id is not None:
            self._load_chart(dlg.chart_id)
        elif dlg.action == "delete" and dlg.chart_id is not None:
            self.db.delete_seating_chart(dlg.chart_id)
            if self._chart_id == dlg.chart_id:
                self._chart_id = None
            self._refresh_chart_list()

    def _load_chart(self, chart_id):
        chart = self.db.get_seating_chart(chart_id)
        if not chart:
            return
        self._chart_id = chart["id"]
        try:
            self._cfg = json.loads(chart["config_json"]) if chart["config_json"] else _default_config()
        except Exception:
            self._cfg = _default_config()
        migrate = ("zone_scheme" not in self._cfg
                   and bool(self._cfg.get("section_zones")))
        for k, v in _default_config().items():
            self._cfg.setdefault(k, v)
        if migrate:
            # Six zones were front HALF (1-3) and back half (4-6).  With nine
            # the back three are 7-9, so a saved chart keeps the placement it
            # was saved with instead of silently sliding into the middle.
            self._cfg["section_zones"] = {
                inst: sc.ZONE_MIGRATION_6_TO_9.get(int(z), int(z))
                for inst, z in (self._cfg.get("section_zones") or {}).items()}
        self._name_var.set(chart["name"])
        self._sort_var.set(self._cfg.get("sort_mode", "alphabetical"))
        self._chart_var.set(chart["name"])
        # A saved chart carries its own class, so the program can differ from
        # the one on screen a moment ago.
        self._apply_program_defaults()
        self._sync_program_ui()
        self._update_roster_label()
        layout = None
        try:
            layout = json.loads(chart["layout_json"]) if chart["layout_json"] else None
        except Exception:
            layout = None
        self._regenerate(from_layout=layout)
        self._dirty = False

    def _apply_program_defaults(self):
        """Turn off the options that belong to another program.

        'Keep percussion in a back row' and 'center the tuba' are concert band
        and nothing else — a strings class has no percussion section and no
        tuba, and a choir has neither.  They are not offered to those programs
        at all now, so leaving them ON would apply a band rule invisibly.
        """
        program, _level = self._chart_program()
        if self._is_symphony():
            # Timpani and the rest stand behind the brass on every symphony
            # chart, which is exactly what the separate percussion row draws --
            # and the tuba belongs with the back brass, not centered by the
            # concert-band rule.  True for a band that gained strings too.
            self._cfg["separate_percussion"] = True
            self._cfg["center_tuba"] = False
        elif program != "band":
            self._cfg["separate_percussion"] = False
            self._cfg["center_tuba"] = False

    def _new_chart(self):
        self._chart_id = None
        self._cfg = _default_config()
        self._apply_remembered_layout()
        self._apply_program_defaults()
        self._sync_program_ui()
        self._name_var.set("Untitled Chart")
        self._sort_var.set(self._cfg["sort_mode"])
        self._chart_var.set("")
        self._update_roster_label()
        self._regenerate()

    def _layout_ids(self):
        def sid(x):
            if not x:
                return None
            if x.get("reserved"):
                return "R"                 # reserved (empty-beside) seat marker
            return x.get("id")
        return {
            "rows": [[sid(x) for x in row] for row in self._rows],
            "perc": [p.get("id") for p in (self._perc or [])
                     if p and not p.get("reserved")],
        }

    def _save_chart(self):
        try:
            self._collect_cfg()
            name = self._name_var.get().strip() or "Untitled Chart"
            data = {
                "school_year": self._year(),
                "name": name,
                # Kept for the column's sake, but derived rather than fixed:
                # a chart drawn in arcs is a concert chart, one in rows is a
                # classroom chart.  It used to be the constant "concert".
                "chart_type": ("concert"
                               if self._cfg.get("view") == "arcs" else "class"),
                "config_json": json.dumps(self._cfg),
                "layout_json": json.dumps(self._layout_ids()),
            }
            # The chart NAME is its identity: saving under a name that already
            # exists overwrites that chart; saving under a new name creates a
            # new chart (so "rename then Save" works like Save As and never
            # clobbers the original).
            self._refresh_chart_list()
            existing = next((c for c in self._charts
                             if (c["name"] or "").strip().lower() == name.lower()), None)
            if existing and existing["id"] != self._chart_id:
                # About to clobber a DIFFERENT saved chart — confirm first.
                if Messagebox.yesno(
                        f"A chart named “{name}” is already saved.\n"
                        f"Overwrite it with this one?",
                        title="Overwrite Chart?", parent=self) != "Yes":
                    return
            if existing:
                self._chart_id = existing["id"]
                self.db.update_seating_chart(self._chart_id, data)
            else:
                self._chart_id = self.db.add_seating_chart(data)
        except Exception as e:
            Messagebox.show_error(f"Could not save the chart:\n{e}",
                                  title="Save Failed", parent=self)
            return
        self._dirty = False
        self._refresh_chart_list()
        self._chart_var.set(name)
        Messagebox.show_info("Seating chart saved.", title="Saved", parent=self)

    def _copy_image(self):
        if self._image is None:
            Messagebox.show_warning(
                "There's no chart to copy yet — generate a seating chart first.",
                title="Nothing to Copy", parent=self)
            return
        ok = sr.copy_image_to_clipboard(self._image)
        if ok:
            Messagebox.show_info("Seating chart copied — paste into PowerPoint, Word, or OneNote.",
                                 title="Copied", parent=self)
        else:
            Messagebox.show_warning(
                "Could not copy the image — another program is holding the "
                "clipboard.\n\nClose any clipboard manager and try again, or "
                "use “Save Image…” to write the chart to a file instead.",
                title="Copy Failed", parent=self)

    def _save_image(self):
        if self._image is None:
            Messagebox.show_warning(
                "There's no chart to save yet — generate a seating chart first.",
                title="Nothing to Save", parent=self)
            return
        from tkinter import filedialog
        name = (self._chart_var.get() or "seating_chart").strip()
        safe = "".join(c for c in name if c.isalnum() or c in " _-").strip()
        path = filedialog.asksaveasfilename(
            parent=self, defaultextension=".png",
            initialfile=f"{safe or 'seating_chart'}.png",
            filetypes=[("PNG image", "*.png"), ("All files", "*.*")],
            title="Save Seating Chart")
        if not path:
            return
        try:
            self._image.save(path)
        except Exception as e:
            Messagebox.show_error(f"Could not save the image:\n{e}",
                                  title="Save Failed", parent=self)
            return
        Messagebox.show_info(f"Saved to:\n{path}", title="Saved", parent=self)

    # ─────────────────────────────────────────────── conflicts & pins dlgs ────

    def _roster_names(self):
        return sorted({s["name"] for s in self._resolve_roster()})

    def _edit_conflicts(self):
        _ConflictsDialog(self.winfo_toplevel(), self.db, self._year(), self._roster_names())
        self._regenerate()

    def _edit_pins(self):
        _PinsDialog(self.winfo_toplevel(), self.db, self._year(), self._roster_names())
        self._regenerate()

    def _edit_instruments(self):
        roster = self._resolve_roster()
        if not roster:
            Messagebox.show_info("Choose students first.", title="No Students", parent=self)
            return
        from ui.ensembles import seating_instruments
        program, level = self._chart_program()
        options = seating_instruments(program, level,
                                      self._cfg.get("numbered_parts", False),
                                      self._cfg.get("piano", False))
        if self._is_symphony() and program == "band":
            # A band that has become a symphony seats strings too, so the
            # override dialog has to be able to name them.
            options = (options[:-1]
                       + seating_instruments("orchestra", level,
                                             self._cfg.get("numbered_parts", False))
                       )
        dlg = _InstrumentDialog(self.winfo_toplevel(), roster,
                                self._cfg.get("instrument_overrides") or {}, options)
        self.wait_window(dlg)
        if dlg.result is not None:
            self._cfg["instrument_overrides"] = dlg.result
            self._regenerate()

    def _jazz_setup(self):
        """Seat a jazz band by PART, as close to the standard chart as the
        players allow.

        Instrument grouping cannot produce a jazz chart: the front row reads
        T1 A2 A1 T2 B, three instruments interleaved by part.  So the parts are
        assigned (guessed, then corrected by the teacher) and the seats come
        from those -- saxes across the front, bass-clef players on the trombone
        parts behind them, trumpets and high winds at the back, with part 1 of
        each row lined up behind the lead alto.
        """
        roster = self._resolve_roster()
        if not roster:
            Messagebox.show_info("Choose a group first.", title="No Students",
                                 parent=self)
            return
        # Read from the students, so what was set last time is still there.
        by_id = self._jazz_parts_map(roster)
        parts = {str(k): v for k, v in by_id.items()}

        dlg = _JazzSetupDialog(self.winfo_toplevel(), roster=roster, parts=parts,
                               side=self._cfg.get("jazz_side", "left"),
                               high_rows=int(self._cfg.get("jazz_high_rows", 1)),
                               view=self._cfg.get("view", "rows"))
        self.wait_window(dlg)
        if dlg.result is None:
            return

        self._cfg["jazz_side"] = dlg.result["side"]
        self._cfg["jazz_high_rows"] = dlg.result["high_rows"]
        self._cfg["view"] = dlg.result["view"]
        # A jazz chart is placed by hand, so none of the concert machinery
        # applies: no zones, no percussion back row (the drummer is IN the
        # band), no tuba centring, and the gaps on the far side are the point.
        self._cfg["section_zones"] = {}
        self._cfg["section_order"] = []
        self._cfg["separate_percussion"] = False
        self._cfg["center_tuba"] = False
        self._cfg["close_gaps"] = False
        self._cfg["jazz_mode"] = True
        self._regenerate()
        self._dirty = True


    # ─────────────────────────────────────────────────────── AI assistant ────

    def _ai_assistant(self):
        roster = self._resolve_roster()
        if not roster:
            Messagebox.show_info("Choose students first.", title="No Students", parent=self)
            return
        roster_lines = "\n".join(
            f"- {s['name']} — {s.get('instrument') or 'unknown'}" for s in roster)
        sections = sorted({(s.get("instrument") or "") for s in roster if s.get("instrument")})
        _AIDialog(self.winfo_toplevel(), self.base_dir, roster_lines, sections, self._apply_ai)

    def _apply_ai(self, data):
        """Apply LLM-parsed constraints/swaps to the chart.  Returns a summary."""
        if not isinstance(data, dict):
            return "The assistant didn't return anything usable."
        names = {n.lower(): n for n in self._roster_names()}
        applied = []
        year = self._year()

        for pair in data.get("keep_apart") or []:
            if isinstance(pair, (list, tuple)) and len(pair) >= 2:
                a = names.get(str(pair[0]).lower())
                b = names.get(str(pair[1]).lower())
                if a and b and a != b:
                    self.db.add_seating_conflict(year, a, b)
                    applied.append(f"keep {a} & {b} apart")

        for p in data.get("placements") or []:
            if not isinstance(p, dict):
                continue
            nm = names.get(str(p.get("name", "")).lower())
            if not nm:
                continue
            row = (p.get("row") or "none").lower()
            row = row if row in ("front", "back", "edge") else "none"
            try:
                eb = int(p.get("empty_beside") or 0)
            except (TypeError, ValueError):
                eb = 0
            note = str(p.get("note") or "")
            if row == "none" and eb == 0 and not note:
                self.db.clear_seating_pin(year, nm)
            else:
                self.db.set_seating_pin(year, nm, row, note, buffer=eb)
            applied.append(f"{nm}: {row}" + (f" +{eb} empty" if eb else ""))

        # Seat pairs side by side.
        together = []
        for pair in data.get("seat_together") or []:
            if isinstance(pair, (list, tuple)) and len(pair) >= 2:
                a = names.get(str(pair[0]).lower())
                b = names.get(str(pair[1]).lower())
                if a and b and a != b:
                    together.append([a, b])
                    applied.append(f"seat {a} by {b}")
        if together:
            self._cfg["together"] = together

        known = {(s.get("instrument") or "") for s in self._resolve_roster()}
        so = data.get("section_order") or []
        if so:
            so = [i for i in so if i in known]
            if so:
                self._cfg["section_order"] = so
                self._ensure_sections_mode()   # section order only applies when grouped
                applied.append("section order updated")

        zdata = data.get("zones") or {}
        if isinstance(zdata, dict) and zdata:
            n_rows = len(sc.parse_row_caps(self._cfg.get("row_caps") or "8"))
            zones = {}
            for inst, rws in zdata.items():
                if inst not in known:
                    continue
                if isinstance(rws, (int, str)):
                    rws = [rws]
                vals = []
                for x in rws or []:
                    try:
                        v = int(x)
                    except (TypeError, ValueError):
                        continue
                    if 1 <= v <= n_rows:
                        vals.append(v)
                if vals:
                    zones[inst] = sorted(set(vals))
            if zones:
                self._cfg["zones"] = {**(self._cfg.get("zones") or {}), **zones}
                self._ensure_sections_mode()
                applied.append("row zones updated")

        # "shuffle the winds" etc.
        if data.get("shuffle_neighbors") or data.get("shuffle"):
            self._ensure_sections_mode()
            self._cfg["seed"] = random.randint(1, 10_000_000)
            self._cfg["shuffle_members"] = True
            applied.append("shuffled neighbors")

        self._regenerate()

        swaps = data.get("swaps") or []
        did_swap = False
        for pair in swaps:
            if isinstance(pair, (list, tuple)) and len(pair) >= 2:
                if self._swap_by_name(names.get(str(pair[0]).lower()),
                                      names.get(str(pair[1]).lower())):
                    applied.append(f"swap {pair[0]} ↔ {pair[1]}")
                    did_swap = True
        if did_swap:
            self._dirty = True
            self._render()

        return "; ".join(applied) if applied else "No matching changes were found."

    def _find_seat_by_name(self, name):
        for r, row in enumerate(self._rows):
            for c, x in enumerate(row):
                if x and x.get("name") == name:
                    return (r, c)
        for c, x in enumerate(self._perc or []):
            if x and x.get("name") == name:
                return ("P", c)
        for c, x in enumerate(getattr(self, "_jazz_rhythm", None) or []):
            if x and x.get("name") == name:
                return ("J", c)
        return None

    def _swap_by_name(self, a, b):
        if not a or not b:
            return False
        pa = self._find_seat_by_name(a)
        pb = self._find_seat_by_name(b)
        if pa and pb:
            va, vb = self._seat_get(pa), self._seat_get(pb)
            self._seat_set(pa, vb)
            self._seat_set(pb, va)
            return True
        return False

    def refresh(self):
        self._refresh_chart_list()
        self._regenerate()


# ══════════════════════════════════════════════════════════════ dialogs ══════

class _JazzSetupDialog(ttk.Toplevel):
    """The jazz STAGE: which side the rhythm section is on, how many rows the
    trumpets use, straight rows or arcs.

    Who covers which part is deliberately NOT here.  Assigning lead trumpet in
    a seating chart window read as confusing, so the parts live where the rest
    of the jazz machinery does -- the Perc/Jazz tab's Band Parts button -- and
    this chart simply reads what is set there (guessing from instruments for
    anyone not yet assigned).
    """

    def __init__(self, parent, roster=None, parts=None, side="left",
                 high_rows=1, view="rows"):
        super().__init__(master=parent)
        self.result = None
        self._roster = list(roster or [])
        self._parts = dict(parts or {})
        self.title("Jazz Band Setup")
        self.grab_set()
        self.lift()

        hdr = ttk.Frame(self, bootstyle=INFO)
        hdr.pack(fill=X)
        ttk.Label(hdr, text="🎷  Jazz Band Setup", font=("Segoe UI", 12, "bold"),
                  bootstyle=(INVERSE, INFO)).pack(pady=10, padx=16, anchor=W)

        btn = ttk.Frame(self)
        btn.pack(side=BOTTOM, fill=X, padx=16, pady=12)
        ttk.Button(btn, text="Cancel", bootstyle=(SECONDARY, OUTLINE),
                   command=self.destroy).pack(side=RIGHT, padx=4)
        ttk.Button(btn, text="Apply", bootstyle=SUCCESS,
                   command=self._ok).pack(side=RIGHT, padx=4)

        body = ttk.Frame(self)
        body.pack(fill=BOTH, expand=True, padx=16, pady=10)
        ttk.Label(body,
                  text="Saxes across the front in part order, bass-clef players "
                       "behind them on the trombone parts, trumpets (plus any "
                       "flutes, clarinets or strings) at the back. Part 1 of "
                       "each row lines up behind the lead alto.",
                  font=("Segoe UI", 9), wraplength=420,
                  justify=LEFT).pack(anchor=W)

        assigned = sum(1 for s in self._roster
                       if (self._parts.get(str(s.get("id"))) or "").strip())
        ttk.Label(body,
                  text="%d of %d players have a part. Who covers which part "
                       "is set on the Perc/Jazz tab — 🎺 Band Parts — and "
                       "anyone without one is seated by a guess from their "
                       "instrument." % (assigned, len(self._roster)),
                  font=("Segoe UI", 8), foreground=muted_fg(),
                  wraplength=420, justify=LEFT).pack(anchor=W, pady=(4, 0))

        ttk.Label(body, text="Rhythm section on:",
                  font=("Segoe UI", 9, "bold")).pack(anchor=W, pady=(10, 0))
        self._side = tk.StringVar(value=side if side in ("left", "right") else "left")
        srow = ttk.Frame(body)
        srow.pack(fill=X)
        ttk.Radiobutton(srow, text="Left side", value="left",
                        variable=self._side).pack(side=LEFT, padx=(0, 12))
        ttk.Radiobutton(srow, text="Right side", value="right",
                        variable=self._side).pack(side=LEFT)
        ttk.Label(body, text="(Flip this if the chart comes out mirrored from "
                             "your room.)",
                  font=("Segoe UI", 8), foreground=muted_fg(),
                  wraplength=420, justify=LEFT).pack(anchor=W)

        ttk.Label(body, text="Trumpet parts use:",
                  font=("Segoe UI", 9, "bold")).pack(anchor=W, pady=(10, 0))
        self._high = tk.IntVar(value=2 if int(high_rows or 1) >= 2 else 1)
        hrow = ttk.Frame(body)
        hrow.pack(fill=X)
        ttk.Radiobutton(hrow, text="One row", value=1,
                        variable=self._high).pack(side=LEFT, padx=(0, 12))
        ttk.Radiobutton(hrow, text="Two rows", value=2,
                        variable=self._high).pack(side=LEFT)

        ttk.Label(body, text="Shape:", font=("Segoe UI", 9, "bold")).pack(
            anchor=W, pady=(10, 0))
        self._view = tk.StringVar(value=view if view in ("rows", "arcs") else "rows")
        vrow = ttk.Frame(body)
        vrow.pack(fill=X)
        ttk.Radiobutton(vrow, text="Straight rows (jazz)", value="rows",
                        variable=self._view).pack(side=LEFT, padx=(0, 12))
        ttk.Radiobutton(vrow, text="Concert arcs", value="arcs",
                        variable=self._view).pack(side=LEFT)

        from ui.theme import fit_window
        fit_window(self, 480, 440)

    def _ok(self):
        self.result = {
            "side": self._side.get(),
            "high_rows": int(self._high.get()),
            "view": self._view.get(),
        }
        self.destroy()



class _StudentPicker(ttk.Toplevel):
    def __init__(self, parent, program_type, selected, scope, extra):
        super().__init__(master=parent)
        self.result = None
        self.title("Choose Students")
        self.grab_set()
        self.lift()

        hdr = ttk.Frame(self, bootstyle=PRIMARY)
        hdr.pack(fill=X)
        ttk.Label(hdr, text="Choose Students", font=("Segoe UI", 12, "bold"),
                  bootstyle=(INVERSE, PRIMARY)).pack(pady=10, padx=16, anchor=W)

        # Pin the action buttons to the bottom FIRST so they can never be pushed
        # off-screen when the "add students" box appears.
        btn = ttk.Frame(self)
        btn.pack(side=BOTTOM, fill=X, padx=16, pady=12)
        ttk.Button(btn, text="Cancel", bootstyle=(SECONDARY, OUTLINE),
                   command=self.destroy).pack(side=RIGHT, padx=4)
        ttk.Button(btn, text="OK", bootstyle=SUCCESS, command=self._ok).pack(side=RIGHT, padx=4)

        body = ttk.Frame(self)
        body.pack(fill=BOTH, expand=True, padx=16, pady=10)

        # Ensemble(s) — the program's own ensembles.
        ttk.Label(body, text="Ensemble(s)", font=("Segoe UI", 9, "bold")).pack(anchor=W)
        self._vars = {}
        for e in ensembles_for(program_type):
            v = tk.BooleanVar(value=e in selected)
            self._vars[e] = v
            ttk.Checkbutton(body, text=e, variable=v, bootstyle=INFO).pack(anchor=W, padx=(10, 0))
        ttk.Label(body, text="Leave unchecked to use the whole current roster.",
                  font=("Segoe UI", 8), foreground=muted_fg()).pack(anchor=W, pady=(2, 0))

        # Scope — all sections (whole ensemble / concert) or one class period.
        ttk.Label(body, text="Which students", font=("Segoe UI", 9, "bold")).pack(anchor=W, pady=(10, 0))
        self._scope = tk.StringVar(value="all" if scope in ("all", "", None) else "period")
        srow = ttk.Frame(body)
        srow.pack(fill=X)
        ttk.Radiobutton(srow, text="All sections (full ensemble)", value="all",
                        variable=self._scope).pack(anchor=W)
        prow = ttk.Frame(body)
        prow.pack(fill=X)
        ttk.Radiobutton(prow, text="Only class period:", value="period",
                        variable=self._scope).pack(side=LEFT)
        self._period = tk.StringVar(value=(str(scope) if scope not in ("all", "", None) else "1"))
        ttk.Combobox(prow, textvariable=self._period, values=PERIOD_OPTIONS,
                     width=4, state="readonly").pack(side=LEFT, padx=(6, 0))

        # Rare: add students from another ensemble (choir/orchestra combos).
        self._extra_on = tk.BooleanVar(value=bool(extra))
        ttk.Checkbutton(body, text="Add students from another ensemble",
                        variable=self._extra_on, bootstyle=INFO,
                        command=self._toggle_extra).pack(anchor=W, pady=(10, 0))
        self._extra_frame = ttk.Frame(body)
        ttk.Label(self._extra_frame, text="One per line — “Name” or “Name, Instrument”:",
                  font=("Segoe UI", 8), foreground=muted_fg()).pack(anchor=W)
        self._extra_text = tk.Text(self._extra_frame, height=5, width=34, relief="solid", bd=1)
        self._extra_text.pack(fill=X)
        if extra:
            self._extra_text.insert("1.0", "\n".join(
                (f"{e.get('name')}, {e.get('instrument')}" if e.get("instrument") else e.get("name", ""))
                for e in extra))
        self._toggle_extra()

        self.resizable(True, True)
        from ui.theme import fit_window
        fit_window(self, 380, 640)

    def _toggle_extra(self):
        if self._extra_on.get():
            self._extra_frame.pack(fill=X, pady=(4, 0))
        else:
            self._extra_frame.pack_forget()

    def _ok(self):
        ens = [e for e, v in self._vars.items() if v.get()]
        scope = "all" if self._scope.get() == "all" else self._period.get().strip()
        extra = []
        if self._extra_on.get():
            for line in self._extra_text.get("1.0", "end").splitlines():
                line = line.strip()
                if not line:
                    continue
                if "," in line:
                    nm, inst = line.split(",", 1)
                    extra.append({"name": nm.strip(), "instrument": inst.strip()})
                else:
                    extra.append({"name": line, "instrument": ""})
        self.result = {"ensembles": ens, "scope": scope, "extra": extra}
        self.destroy()


class _ConflictsDialog(ttk.Toplevel):
    def __init__(self, parent, db, year, names):
        super().__init__(master=parent)
        self.db = db
        self.year = year
        self.names = names
        self.title("Keep-Apart Pairs")
        self.grab_set()
        self.lift()

        hdr = ttk.Frame(self, bootstyle=WARNING)
        hdr.pack(fill=X)
        ttk.Label(hdr, text="🚫 Students Who Can't Sit Together",
                  font=("Segoe UI", 12, "bold"), bootstyle=(INVERSE, WARNING)).pack(pady=10, padx=16, anchor=W)

        body = ttk.Frame(self)
        body.pack(fill=BOTH, expand=True, padx=16, pady=10)
        add = ttk.Frame(body)
        add.pack(fill=X)
        self._a = tk.StringVar()
        self._b = tk.StringVar()
        ttk.Combobox(add, textvariable=self._a, values=names, width=16, state="readonly").pack(side=LEFT)
        ttk.Label(add, text=" ✕ ").pack(side=LEFT)
        ttk.Combobox(add, textvariable=self._b, values=names, width=16, state="readonly").pack(side=LEFT)
        ttk.Button(add, text="Add", bootstyle=SUCCESS, command=self._add).pack(side=LEFT, padx=6)

        # exportselection=False everywhere a list shares a window with a box
        # you type in: otherwise the list loses its highlight to the box and
        # "Remove Selected" quietly removes nothing.
        self._list = tk.Listbox(body, height=8, exportselection=False)
        self._list.pack(fill=BOTH, expand=True, pady=(8, 4))
        ttk.Button(body, text="Remove Selected", bootstyle=(DANGER, OUTLINE),
                   command=self._remove).pack(anchor=W)

        ttk.Button(self, text="Close", bootstyle=(SECONDARY, OUTLINE),
                   command=self.destroy).pack(side=RIGHT, padx=16, pady=(0, 12))
        self._fill()
        from ui.theme import fit_window
        fit_window(self, 460, 380)

    def _fill(self):
        self._list.delete(0, END)
        self._rows = list(self.db.get_seating_conflicts(self.year))
        for c in self._rows:
            self._list.insert(END, f"{c['name_a']}  ✕  {c['name_b']}")

    def _add(self):
        a, b = self._a.get().strip(), self._b.get().strip()
        if a and b and a != b:
            self.db.add_seating_conflict(self.year, a, b)
            self._a.set(""); self._b.set(""); self._fill()

    def _remove(self):
        sel = self._list.curselection()
        if sel:
            self.db.delete_seating_conflict(self._rows[sel[0]]["id"])
            self._fill()


class _PinsDialog(ttk.Toplevel):
    def __init__(self, parent, db, year, names):
        super().__init__(master=parent)
        self.db = db
        self.year = year
        self.names = names
        self.title("Special Accommodations")
        self.grab_set()
        self.lift()

        hdr = ttk.Frame(self, bootstyle=WARNING)
        hdr.pack(fill=X)
        ttk.Label(hdr, text="♿ Special Accommodations",
                  font=("Segoe UI", 12, "bold"), bootstyle=(INVERSE, WARNING)).pack(pady=10, padx=16, anchor=W)

        body = ttk.Frame(self)
        body.pack(fill=BOTH, expand=True, padx=16, pady=10)
        add = ttk.Frame(body)
        add.pack(fill=X)
        self._student = tk.StringVar()
        ttk.Combobox(add, textvariable=self._student, values=names, width=15, state="readonly").pack(side=LEFT)
        ttk.Label(add, text="row:").pack(side=LEFT, padx=(6, 1))
        self._pref = tk.StringVar(value="none")
        ttk.Combobox(add, textvariable=self._pref, values=["none", "front", "back", "edge"],
                     width=6, state="readonly").pack(side=LEFT)
        ttk.Label(add, text="empty beside:").pack(side=LEFT, padx=(6, 1))
        self._buffer = tk.StringVar(value="0")
        ttk.Combobox(add, textvariable=self._buffer, values=["0", "1", "2"],
                     width=3, state="readonly").pack(side=LEFT)
        ttk.Button(add, text="Set", bootstyle=SUCCESS, command=self._set).pack(side=LEFT, padx=(6, 0))

        note_row = ttk.Frame(body)
        note_row.pack(fill=X, pady=(4, 0))
        ttk.Label(note_row, text="Note:").pack(side=LEFT)
        self._note = tk.StringVar()
        ttk.Entry(note_row, textvariable=self._note, width=34).pack(side=LEFT, padx=(4, 0))

        ttk.Label(body, text="Row: front = first row, back = last row, edge = outside end of a row.  "
                             "Empty beside = reserved seats for a 1:1 para or a buffer around a "
                             "distractible student.",
                  font=("Segoe UI", 8), foreground=muted_fg(), wraplength=460,
                  justify=LEFT).pack(anchor=W, pady=(4, 0))

        self._list = tk.Listbox(body, height=8, exportselection=False)
        self._list.pack(fill=BOTH, expand=True, pady=(8, 4))
        ttk.Button(body, text="Remove Selected", bootstyle=(DANGER, OUTLINE),
                   command=self._remove).pack(anchor=W)

        ttk.Button(self, text="Close", bootstyle=(SECONDARY, OUTLINE),
                   command=self.destroy).pack(side=RIGHT, padx=16, pady=(0, 12))
        self._fill()
        from ui.theme import fit_window
        fit_window(self, 560, 400)

    def _buffer_of(self, p):
        try:
            return int(p["buffer"] or 0)
        except (KeyError, TypeError, IndexError):
            return 0

    def _fill(self):
        self._list.delete(0, END)
        self._rows = list(self.db.get_seating_pins(self.year))
        for p in self._rows:
            bits = []
            if p["pref"] and p["pref"] != "none":
                bits.append(p["pref"])
            b = self._buffer_of(p)
            if b:
                bits.append(f"{b} empty seat{'s' if b > 1 else ''} beside")
            if p["note"]:
                bits.append(p["note"])
            self._list.insert(END, f"{p['student_name']}: {', '.join(bits) or '—'}")

    def _set(self):
        name = self._student.get().strip()
        if not name:
            return
        pref = self._pref.get()
        try:
            buf = int(self._buffer.get())
        except ValueError:
            buf = 0
        if pref == "none" and buf == 0 and not self._note.get().strip():
            self.db.clear_seating_pin(self.year, name)
        else:
            self.db.set_seating_pin(self.year, name, pref, self._note.get().strip(), buffer=buf)
        self._note.set("")
        self._buffer.set("0")
        self._fill()

    def _remove(self):
        sel = self._list.curselection()
        if sel:
            self.db.clear_seating_pin(self.year, self._rows[sel[0]]["student_name"])
            self._fill()


class _InstrumentDialog(ttk.Toplevel):
    """Per-student instrument override for this chart (for kids who play more
    than one and need a specific instrument for a particular concert)."""

    def __init__(self, parent, roster, overrides, options):
        super().__init__(master=parent)
        self.result = None
        self._roster = roster
        self._overrides = dict(overrides or {})
        self._options = options
        self.title("Adjust Instruments")
        self.grab_set()
        self.lift()

        hdr = ttk.Frame(self, bootstyle=PRIMARY)
        hdr.pack(fill=X)
        ttk.Label(hdr, text="🎺 Instrument per student (this chart)",
                  font=("Segoe UI", 12, "bold"), bootstyle=(INVERSE, PRIMARY)).pack(
            pady=10, padx=16, anchor=W)
        ttk.Label(self, text="Blank = use the student's primary/secondary as set by the toggle.",
                  font=("Segoe UI", 8), foreground=muted_fg()).pack(anchor=W, padx=16, pady=(6, 0))

        # Scrollable list of students with an editable instrument combobox.
        canvas = tk.Canvas(self, highlightthickness=0, height=360)
        sb = ttk.Scrollbar(self, orient=VERTICAL, command=canvas.yview)
        canvas.configure(yscrollcommand=sb.set)
        sb.pack(side=RIGHT, fill=Y)
        canvas.pack(fill=BOTH, expand=True, padx=(16, 0), pady=8)
        inner = ttk.Frame(canvas)
        cw = canvas.create_window((0, 0), window=inner, anchor=NW)
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(cw, width=e.width))

        self._vars = {}
        for s in sorted(roster, key=lambda x: (x["last"].lower(), x["name"].lower())):
            row = ttk.Frame(inner)
            row.pack(fill=X, pady=1)
            base = s.get("primary") or ""
            sec = s.get("secondary") or ""
            hint = base + (f" / {sec}" if sec else "")
            ttk.Label(row, text=s["name"], width=16, anchor=W).pack(side=LEFT)
            ttk.Label(row, text=hint or "—", width=18, anchor=W,
                      foreground=muted_fg(), font=("Segoe UI", 8)).pack(side=LEFT)
            var = tk.StringVar(value=self._overrides.get(str(s["id"]), ""))
            self._vars[str(s["id"])] = var
            ttk.Combobox(row, textvariable=var, values=[""] + list(options),
                         width=16).pack(side=LEFT, padx=(4, 8))

        btn = ttk.Frame(self)
        btn.pack(fill=X, padx=16, pady=12)
        ttk.Button(btn, text="Cancel", bootstyle=(SECONDARY, OUTLINE),
                   command=self.destroy).pack(side=RIGHT, padx=4)
        ttk.Button(btn, text="Apply", bootstyle=SUCCESS, command=self._ok).pack(side=RIGHT, padx=4)

        from ui.theme import fit_window
        fit_window(self, 520, 520)

    def _ok(self):
        out = {}
        for sid, var in self._vars.items():
            val = var.get().strip()
            if val:
                out[sid] = val
        self.result = out
        self.destroy()


_SORT_WORDS = {
    "alphabetical_first": "alpha by first name",
    "alphabetical": "alpha by last name",
    "small_groups": "small groups",
    "sections": "by section",
}


def _chart_label(c):
    """One line describing a saved chart: what it is for, how it was sorted,
    and when it was saved."""
    name = (c["name"] or "Untitled Chart").strip()
    bits = []
    try:
        cfg = json.loads(c["config_json"] or "{}")
    except Exception:
        cfg = {}
    try:
        import class_registry as cr
        groups = cfg.get("groups") or []
        classes = []
        for g in groups:
            lab = cr.short_class_label(g.get("ensemble") or "")
            per = g.get("period", "all")
            if per not in ("all", "", None):
                lab += f" P{per}"
            if lab and lab not in classes:
                classes.append(lab)
        if classes:
            bits.append(", ".join(classes))
    except Exception:
        pass
    word = _SORT_WORDS.get(cfg.get("sort_mode") or "")
    if word:
        bits.append(word)
    when = (c["updated_at"] or c["created_at"] or "")[:10] if (
        "updated_at" in c.keys() or "created_at" in c.keys()) else ""
    if when:
        bits.append(when)
    return f"{name}   ({' · '.join(bits)})" if bits else name


class _LoadDialog(ttk.Toplevel):
    def __init__(self, parent, charts):
        super().__init__(master=parent)
        self.action = None
        self.chart_id = None
        self._charts = charts
        self.title("Load Chart")
        self.grab_set()
        self.lift()
        ttk.Label(self, text="Saved seating charts", font=("Segoe UI", 12, "bold"),
                  bootstyle=PRIMARY).pack(anchor=W, padx=16, pady=(12, 6))
        self._list = tk.Listbox(self, height=10, width=40, font=("Segoe UI", 10))
        self._list.pack(fill=BOTH, expand=True, padx=16)
        for c in charts:
            self._list.insert(END, _chart_label(c))
        self._list.bind("<Double-1>", lambda e: self._do("load"))
        btn = ttk.Frame(self)
        btn.pack(fill=X, padx=16, pady=12)
        ttk.Button(btn, text="Close", bootstyle=(SECONDARY, OUTLINE),
                   command=self.destroy).pack(side=RIGHT, padx=4)
        ttk.Button(btn, text="Load", bootstyle=SUCCESS,
                   command=lambda: self._do("load")).pack(side=RIGHT, padx=4)
        ttk.Button(btn, text="Delete", bootstyle=(DANGER, OUTLINE),
                   command=lambda: self._do("delete")).pack(side=LEFT, padx=4)
        from ui.theme import fit_window
        fit_window(self, 380, 380)

    def _do(self, action):
        sel = self._list.curselection()
        if not sel:
            return
        self.action = action
        self.chart_id = self._charts[sel[0]]["id"]
        self.destroy()


class _ShufflePrompt(ttk.Toplevel):
    """The four kinds of shuffle, which are four different questions.

    Each stands alone.  "Shuffle within sections" shuffles inside every section
    wherever that section currently sits -- the default concert layout, a zone
    set by hand, or one a section shuffle landed on; it never needs another
    shuffle run first.  That is also what lets the two chain: shuffle the
    sections into new parts of the room, then shuffle within them, and you get
    an arrangement nobody has sat in before.
    """

    def __init__(self, parent, on_all, on_members, on_sections, on_groups=None,
                 on_clear_setup=None, has_setup=False):
        super().__init__(master=parent)
        self.title("Shuffle")
        self.grab_set()
        self.lift()
        ttk.Label(self, text="\U0001f500  Shuffle", font=("Segoe UI", 13, "bold"),
                  bootstyle=PRIMARY).pack(anchor=W, padx=16, pady=(14, 4))
        ttk.Label(self, text="What would you like to shuffle?",
                  font=("Segoe UI", 10)).pack(anchor=W, padx=16)
        body = ttk.Frame(self)
        body.pack(fill=BOTH, expand=True, padx=16, pady=10)

        self._clear = tk.BooleanVar(value=False)

        def run(cb):
            if self._clear.get() and on_clear_setup:
                on_clear_setup()
            cb()
            self.destroy()

        def make(text, desc, cb):
            f = ttk.Frame(body)
            f.pack(fill=X, pady=4)
            ttk.Button(f, text=text, bootstyle=SUCCESS, width=26,
                       command=lambda: run(cb)).pack(side=LEFT, anchor=N)
            ttk.Label(f, text=desc, font=("Segoe UI", 9), wraplength=300,
                      justify=LEFT).pack(side=LEFT, padx=8)

        make("Shuffle everyone",
             "A brand new seat and new neighbours for every student, every "
             "click. Keep-apart pairs and accommodations are still obeyed.",
             on_all)
        make("Shuffle section placement",
             "Move whole sections to different parts of the room, at random. "
             "The people inside each section stay in their order.",
             on_sections)
        make("Shuffle within sections",
             "Change who sits by whom INSIDE each section, leaving every "
             "section exactly where it is — wherever that is. Use it on "
             "its own, or after the one above to re-mix the people without "
             "disturbing the room you just made.",
             on_members)
        if on_groups is not None:
            make("Shuffle into 2s and 3s",
                 "Break the band into pairs of the same part (a three only "
                 "where a section is odd), spread around the room so no "
                 "section re-forms. A section of one buddies up with the "
                 "nearest sound \u2014 a lone bassoon with a lone tuba.",
                 on_groups)

        if has_setup:
            ttk.Separator(body).pack(fill=X, pady=(8, 4))
            ttk.Checkbutton(body, text="Start from standard concert seating "
                                       "(drop the zones first)",
                            variable=self._clear, bootstyle=WARNING).pack(anchor=W)
            ttk.Label(body, text="Otherwise a section with a zone stays in it "
                                 "and everything else moves around it.  There "
                                 "is a \u201cStandard concert seating\u201d "
                                 "button in Configuration too, if that is all "
                                 "you want.",
                      font=("Segoe UI", 8), foreground=muted_fg(),
                      wraplength=430, justify=LEFT).pack(anchor=W, pady=(2, 0))

        ttk.Button(self, text="Cancel", bootstyle=(SECONDARY, OUTLINE),
                   command=self.destroy).pack(side=RIGHT, padx=16, pady=(0, 12))
        from ui.theme import fit_window
        fit_window(self, 620, 480 if has_setup else 420)



class _GroupDialog(ttk.Toplevel):
    """Pick ensemble × class-period combinations (multi-select for concerts),
    plus optional add-ins from another ensemble."""

    def __init__(self, parent, ensemble_periods, current, extra,
                 diagnostic=""):
        super().__init__(master=parent)
        self.result = None
        self._ep = ensemble_periods
        cur = {(g.get("ensemble"), str(g.get("period", "all"))) for g in (current or [])}
        self.title("Choose Group")
        self.grab_set()
        self.lift()

        hdr = ttk.Frame(self, bootstyle=PRIMARY)
        hdr.pack(fill=X)
        ttk.Label(hdr, text="Choose Group", font=("Segoe UI", 12, "bold"),
                  bootstyle=(INVERSE, PRIMARY)).pack(pady=10, padx=16, anchor=W)

        btn = ttk.Frame(self)
        btn.pack(side=BOTTOM, fill=X, padx=16, pady=12)
        ttk.Button(btn, text="Cancel", bootstyle=(SECONDARY, OUTLINE),
                   command=self.destroy).pack(side=RIGHT, padx=4)
        ttk.Button(btn, text="OK", bootstyle=SUCCESS, command=self._ok).pack(side=RIGHT, padx=4)

        body = ttk.Frame(self)
        body.pack(fill=BOTH, expand=True, padx=16, pady=10)
        ttk.Label(body, text="Check a whole ensemble, or specific class periods. "
                             "Check several to combine for a concert.",
                  font=("Segoe UI", 9), wraplength=340, justify=LEFT).pack(anchor=W)

        self._all_vars = {}
        self._period_vars = {}
        if not ensemble_periods:
            # An empty picker used to say only "none found", which gives the
            # teacher nothing to act on.  Say which year was searched and how
            # many students are in it — that's what tells them whether the
            # problem is the year, the import, or the class names.
            ttk.Label(body, text="No classes with students found.",
                      font=("Segoe UI", 9, "bold"), bootstyle=WARNING,
                      wraplength=340, justify=LEFT).pack(anchor=W, pady=(8, 2))
            if diagnostic:
                ttk.Label(body, text=diagnostic, font=("Segoe UI", 8),
                          foreground=muted_fg(), wraplength=340,
                          justify=LEFT).pack(anchor=W)
        import class_registry as cr
        display = cr.display_map(list(ensemble_periods))
        for e, periods in ensemble_periods.items():
            disp = display.get(e, e)
            self._period_vars[e] = {}
            if len(periods) <= 1:
                # Meets all together, all the time — one box is enough.
                checked = (e, "all") in cur or any((e, p) in cur for p in periods)
                av = tk.BooleanVar(value=checked)
                self._all_vars[e] = av
                ttk.Checkbutton(body, text=disp, variable=av,
                                bootstyle=INFO).pack(anchor=W, pady=(8, 0))
            else:
                ef = ttk.Labelframe(body, text=disp, padding=6)
                ef.pack(fill=X, pady=(8, 0))
                av = tk.BooleanVar(value=(e, "all") in cur)
                self._all_vars[e] = av
                ttk.Checkbutton(ef, text="All periods", variable=av,
                                bootstyle=INFO).pack(anchor=W)
                prow = ttk.Frame(ef)
                prow.pack(fill=X)
                for p in periods:
                    pv = tk.BooleanVar(value=(e, p) in cur)
                    self._period_vars[e][p] = pv
                    ttk.Checkbutton(prow, text=f"Period {p}", variable=pv).pack(side=LEFT, padx=(0, 10))

        self._extra_on = tk.BooleanVar(value=bool(extra))
        ttk.Checkbutton(body, text="Add students from another ensemble",
                        variable=self._extra_on, bootstyle=INFO,
                        command=self._toggle_extra).pack(anchor=W, pady=(12, 0))
        self._extra_frame = ttk.Frame(body)
        ttk.Label(self._extra_frame, text="One per line — “Name” or “Name, Instrument”:",
                  font=("Segoe UI", 8), foreground=muted_fg()).pack(anchor=W)
        self._extra_text = tk.Text(self._extra_frame, height=4, width=36, relief="solid", bd=1)
        self._extra_text.pack(fill=X)
        if extra:
            self._extra_text.insert("1.0", "\n".join(
                (f"{e.get('name')}, {e.get('instrument')}" if e.get("instrument") else e.get("name", ""))
                for e in extra))
        self._toggle_extra()

        self.resizable(True, True)
        from ui.theme import fit_window
        fit_window(self, 400, 620)

    def _toggle_extra(self):
        if self._extra_on.get():
            self._extra_frame.pack(fill=X, pady=(4, 0))
        else:
            self._extra_frame.pack_forget()

    def _ok(self):
        groups = []
        for e in self._ep:
            if self._all_vars[e].get():
                groups.append({"ensemble": e, "period": "all"})
            else:
                for p, v in self._period_vars[e].items():
                    if v.get():
                        groups.append({"ensemble": e, "period": p})
        extra = []
        if self._extra_on.get():
            for line in self._extra_text.get("1.0", "end").splitlines():
                line = line.strip()
                if not line:
                    continue
                if "," in line:
                    nm, inst = line.split(",", 1)
                    extra.append({"name": nm.strip(), "instrument": inst.strip()})
                else:
                    extra.append({"name": line, "instrument": ""})
        self.result = {"groups": groups, "extra": extra}
        self.destroy()


class _ConfigurationDialog(ttk.Toplevel):
    """Everything about the CHART, in one window, in two columns.

    This was three windows: "Set Up" (view, rows, colors), "Concert Setup"
    (section order and row zones) and half of "Student Set Up" (names).  Three
    buttons with near-identical names sat within an inch of each other and
    nothing said which was which.

    Two columns rather than one long scroll, because the concert seating was
    below the fold in a single column and a teacher who did not think to scroll
    concluded it had been taken away.  Nothing here is worth hiding.

    What is offered depends on the class being seated.  A strings class is not
    shown 'keep percussion in a back row' -- it has no percussion section, and
    an option that cannot apply is worse than a missing one.
    """

    def __init__(self, parent, cfg, program, level, sections=None):
        super().__init__(master=parent)
        self.result = None
        self._program = program
        self._level = level
        self.title("Configuration")
        self.grab_set()
        self.lift()

        hdr = ttk.Frame(self, bootstyle=PRIMARY)
        hdr.pack(fill=X)
        ttk.Label(hdr, text="⚙  Configuration", font=("Segoe UI", 12, "bold"),
                  bootstyle=(INVERSE, PRIMARY)).pack(pady=10, padx=16, anchor=W)

        btn = ttk.Frame(self)
        btn.pack(side=BOTTOM, fill=X, padx=16, pady=12)
        ttk.Button(btn, text="Cancel", bootstyle=(SECONDARY, OUTLINE),
                   command=self.destroy).pack(side=RIGHT, padx=4)
        ttk.Button(btn, text="Apply", bootstyle=SUCCESS,
                   command=self._ok).pack(side=RIGHT, padx=4)

        cols = ttk.Frame(self)
        cols.pack(fill=BOTH, expand=True, padx=16, pady=(10, 0))
        left = ttk.Frame(cols)
        left.pack(side=LEFT, fill=BOTH, expand=True, anchor=N)
        ttk.Separator(cols, orient=VERTICAL).pack(side=LEFT, fill=Y, padx=14)
        right = ttk.Frame(cols)
        right.pack(side=LEFT, fill=BOTH, expand=True, anchor=N)

        def head(parent, t, top=12):
            ttk.Label(parent, text=t, font=("Segoe UI", 10, "bold")).pack(
                anchor=W, pady=(top, 2))

        # -- LEFT: how the chart looks -----------------------------------
        head(left, "Layout", top=0)
        self._view = tk.StringVar(value=cfg.get("view", "rows"))
        vf = ttk.Frame(left); vf.pack(fill=X)
        ttk.Radiobutton(vf, text="Rows", value="rows",
                        variable=self._view).pack(side=LEFT)
        ttk.Radiobutton(vf, text="Arcs", value="arcs",
                        variable=self._view).pack(side=LEFT, padx=(12, 0))

        ttk.Label(left, text="Front of the room is",
                  font=("Segoe UI", 9)).pack(anchor=W, pady=(8, 0))
        self._front = tk.StringVar(value="bottom" if cfg.get("flip") else "top")
        ff = ttk.Frame(left); ff.pack(fill=X)
        ttk.Radiobutton(ff, text="Top", value="top",
                        variable=self._front).pack(side=LEFT)
        ttk.Radiobutton(ff, text="Bottom", value="bottom",
                        variable=self._front).pack(side=LEFT, padx=(12, 0))

        ttk.Label(left, text="Seats in each row (front → back)",
                  font=("Segoe UI", 9)).pack(anchor=W, pady=(8, 0))
        ttk.Label(left, text="Leave a box blank to remove that row.",
                  font=("Segoe UI", 8), foreground=muted_fg()).pack(anchor=W)
        caps = sc.parse_row_caps(cfg.get("row_caps") or "8")
        self._rows = []
        rowsf = ttk.Frame(left); rowsf.pack(fill=X, pady=(2, 0))
        # Two per line: six stacked boxes were most of the window's height.
        line = None
        for i in range(6):
            if i % 2 == 0:
                line = ttk.Frame(rowsf); line.pack(fill=X, pady=1)
            ttk.Label(line, text="Row %d:" % (i + 1), width=7).pack(side=LEFT)
            v = tk.StringVar(value=str(caps[i]) if i < len(caps) else "")
            self._rows.append(v)
            ttk.Entry(line, textvariable=v, width=5).pack(side=LEFT, padx=(0, 12))

        head(left, "Colors and names")
        self._color = tk.StringVar(value=cfg.get("color_mode", "none"))
        cf = ttk.Frame(left); cf.pack(fill=X)
        ttk.Radiobutton(cf, text="By row", value="row",
                        variable=self._color).pack(side=LEFT)
        ttk.Radiobutton(cf, text="By section", value="section",
                        variable=self._color).pack(side=LEFT, padx=(12, 0))
        ttk.Radiobutton(cf, text="None", value="none",
                        variable=self._color).pack(side=LEFT, padx=(12, 0))

        self._showinst = tk.BooleanVar(value=cfg.get("show_instrument", True))
        ttk.Checkbutton(left, text="Show instrument under each name",
                        variable=self._showinst,
                        bootstyle=INFO).pack(anchor=W, pady=(6, 0))
        self._name_display = tk.StringVar(value=cfg.get("name_display", "first"))
        for val, txt in [
                ("first", "First name only (last initial only if two share it)"),
                ("last_initial", "Show all last-name initials"),
                ("last_full", "Show full last names")]:
            ttk.Radiobutton(left, text=txt, value=val,
                            variable=self._name_display).pack(anchor=W)

        head(left, "Section placement")
        self._close = tk.BooleanVar(value=cfg.get("close_gaps", True))
        ttk.Checkbutton(left, text="No empty chairs inside the ensemble",
                        variable=self._close, bootstyle=INFO).pack(anchor=W)
        ttk.Label(left, text="Closes up gaps between sections and leaves the "
                             "spare chairs at the outside ends and the back.",
                  font=("Segoe UI", 8),
                  foreground=muted_fg()).pack(anchor=W, pady=(0, 4))
        self._perc = tk.BooleanVar(value=cfg.get("separate_percussion", True))
        self._tuba = tk.BooleanVar(value=cfg.get("center_tuba", True))
        self._bass = tk.BooleanVar(value=cfg.get("bass_corner", True))
        self._bass_side = tk.StringVar(value=cfg.get("bass_corner_side", "right"))
        self._parts = tk.BooleanVar(value=cfg.get("numbered_parts", False))
        self._piano = tk.BooleanVar(value=cfg.get("piano", False))

        if program == "band":
            ttk.Checkbutton(left, text="Keep percussion in a back row",
                            variable=self._perc, bootstyle=INFO).pack(anchor=W)
            ttk.Checkbutton(left, text="Keep tuba in the middle of the back row",
                            variable=self._tuba, bootstyle=INFO).pack(anchor=W)
        elif program == "orchestra":
            bf = ttk.Frame(left); bf.pack(fill=X)
            ttk.Checkbutton(bf, text="Keep string basses in the back corner",
                            variable=self._bass, bootstyle=INFO).pack(side=LEFT)
            ttk.Combobox(bf, textvariable=self._bass_side, width=6,
                         state="readonly",
                         values=["right", "left"]).pack(side=LEFT, padx=(8, 0))
            ttk.Label(left, text="Which corner, as the audience sees it. "
                                 "Right is the usual one.",
                      font=("Segoe UI", 8),
                      foreground=muted_fg()).pack(anchor=W)
            if level != "elementary":
                ttk.Checkbutton(left, text="Expand to Violin 1 / Violin 2",
                                variable=self._parts,
                                bootstyle=INFO).pack(anchor=W, pady=(6, 0))
            ttk.Checkbutton(left, text="This group has a piano",
                            variable=self._piano, bootstyle=INFO).pack(anchor=W)
        else:
            ttk.Label(left, text="A choir seats by voice part; there are no "
                                 "extra placement rules.",
                      font=("Segoe UI", 8),
                      foreground=muted_fg()).pack(anchor=W)

        # -- RIGHT: concert seating --------------------------------------
        head(right, "Concert seating", top=0)
        self._sections = list(sections or [])
        self._zones = {i: (cfg.get("section_zones") or {}).get(i, "")
                       for i in self._sections}
        self._last_sel = None
        self._had_placement = bool(cfg.get("section_order")
                                   or cfg.get("section_zones"))
        self._touched = False
        self._cleared = False

        self._zone_legend(right)

        if not self._sections:
            ttk.Label(right, text="Choose a group first, and the sections in it "
                                  "appear here to place.",
                      font=("Segoe UI", 9), foreground=muted_fg(),
                      wraplength=300, justify=LEFT).pack(anchor=W, pady=(8, 0))
            self._list = None
        else:
            ttk.Label(right, text="Give a section a zone, or leave it blank to "
                                  "let it flow.  Top of the list is seated "
                                  "first, nearest the front.",
                      font=("Segoe UI", 8), foreground=muted_fg(),
                      wraplength=300, justify=LEFT).pack(anchor=W, pady=(6, 2))
            sec = ttk.Frame(right); sec.pack(fill=BOTH, expand=True)
            # exportselection=False: with Tk's default the list DROPS its
            # selection the moment a box beside it takes focus, which is why
            # setting a zone used to do nothing at all.
            self._list = tk.Listbox(sec, height=9, activestyle="dotbox",
                                    exportselection=False, width=30)
            self._list.pack(side=LEFT, fill=BOTH, expand=True)
            self._list.bind("<<ListboxSelect>>", lambda e: self._on_select())
            side = ttk.Frame(sec); side.pack(side=LEFT, fill=Y, padx=(8, 0))
            ttk.Button(side, text="▲ Up", bootstyle=(SECONDARY, OUTLINE),
                       command=lambda: self._move(-1)).pack(fill=X, pady=2)
            ttk.Button(side, text="▼ Down", bootstyle=(SECONDARY, OUTLINE),
                       command=lambda: self._move(1)).pack(fill=X, pady=2)
            ttk.Label(side, text="Zone:",
                      font=("Segoe UI", 8, "bold")).pack(anchor=W, pady=(10, 0))
            self._zone_var = tk.StringVar(value="")
            ttk.Combobox(side, textvariable=self._zone_var, width=20,
                         state="readonly",
                         values=[""] + [sc.ZONE_LABELS[z] for z in sorted(sc.ZONE_LABELS)]
                         ).pack(anchor=W)
            ttk.Button(side, text="Set zone", bootstyle=(INFO, OUTLINE),
                       command=self._set_zone).pack(fill=X, pady=(4, 0))
            ttk.Button(side, text="Clear zone", bootstyle=(SECONDARY, OUTLINE),
                       command=self._clear_zone).pack(fill=X, pady=(2, 0))
            ttk.Button(right, text="\u21ba  Standard concert seating",
                       bootstyle=(INFO, OUTLINE),
                       command=self._clear_placement).pack(anchor=W, pady=(8, 2))
            ttk.Label(right, text="Puts every section back in normal concert "
                                  "order, front to back, and removes the zones "
                                  "above.",
                      font=("Segoe UI", 8), foreground=muted_fg(),
                      wraplength=300, justify=LEFT).pack(anchor=W)
            self._refresh_list(0)

        from ui.theme import fit_window
        fit_window(self, 880, 560)

    def _zone_legend(self, parent):
        """The nine zones drawn as the room, so the numbers need no explaining."""
        box = ttk.Labelframe(parent, text=" The nine zones ", padding=8)
        box.pack(fill=X)
        ttk.Label(box, text="Front of the room at the top, as the audience sees it.",
                  font=("Segoe UI", 8),
                  foreground=muted_fg()).grid(row=0, column=0, columnspan=4,
                                              sticky=W, pady=(0, 4))
        for c, t in enumerate(sc.ZONE_SIDES):
            ttk.Label(box, text=t, font=("Segoe UI", 8),
                      foreground=muted_fg()).grid(row=1, column=c + 1, padx=6)
        for r, depth in enumerate(sc.ZONE_DEPTHS):
            ttk.Label(box, text=depth, font=("Segoe UI", 8, "bold")).grid(
                row=r + 2, column=0, sticky=W, padx=(0, 6), pady=2)
            for c in range(3):
                ttk.Label(box, text=str(r * 3 + c + 1),
                          font=("Segoe UI", 11, "bold"),
                          bootstyle=INFO, anchor=CENTER, width=4,
                          relief="solid", borderwidth=1).grid(
                              row=r + 2, column=c + 1, padx=6, pady=2)

    # -- section list helpers --------------------------------------------
    def _n_rows(self):
        """How many rows there are RIGHT NOW - read from the boxes, not from
        the config, so a zone means the layout being edited."""
        n = len([v for v in self._rows
                 if v.get().strip().isdigit() and int(v.get()) > 0])
        return n or 1

    def _selected(self):
        """The section being edited, falling back to the last one clicked: a
        listbox can lose its highlight to whatever takes focus next, and losing
        the highlight must not mean losing the click."""
        sel = self._list.curselection() if self._list else ()
        if sel:
            self._last_sel = sel[0]
            return sel[0]
        if self._last_sel is not None and self._last_sel < len(self._sections):
            return self._last_sel
        return None

    def _need_selection(self):
        Messagebox.show_info("Click a section in the list first.",
                             title="No Section Chosen", parent=self)

    def _refresh_list(self, select_idx=None):
        self._list.delete(0, END)
        for inst in self._sections:
            z = self._zones.get(inst)
            self._list.insert(END, inst + ("   →  zone %s" % z if z else ""))
        self._list.selection_clear(0, END)
        if select_idx is not None and 0 <= select_idx < len(self._sections):
            self._list.selection_set(select_idx)
            self._list.activate(select_idx)
            self._list.see(select_idx)
            self._last_sel = select_idx
            self._on_select()

    def _on_select(self):
        sel = self._list.curselection()
        if not sel:
            return
        self._last_sel = sel[0]
        z = self._zones.get(self._sections[sel[0]])
        self._zone_var.set(sc.ZONE_LABELS.get(z, "") if z else "")

    def _mark(self):
        self._touched = True
        self._cleared = False

    def _move(self, delta):
        i = self._selected()
        if i is None:
            return self._need_selection()
        j = i + delta
        if j < 0 or j >= len(self._sections):
            return
        self._sections[i], self._sections[j] = self._sections[j], self._sections[i]
        self._mark()
        self._refresh_list(j)

    def _set_zone(self):
        i = self._selected()
        if i is None:
            return self._need_selection()
        label = self._zone_var.get()
        zone = next((z for z, t in sc.ZONE_LABELS.items() if t == label), None)
        self._zones[self._sections[i]] = zone or ""
        self._mark()
        self._refresh_list(i)

    def _clear_zone(self):
        i = self._selected()
        if i is None:
            return self._need_selection()
        self._zones[self._sections[i]] = ""
        self._zone_var.set("")
        self._mark()
        self._refresh_list(i)

    def _clear_placement(self):
        """Back to standard concert seating: sections in their normal
        front-to-back order and no zones on any of them."""
        self._sections.sort(key=lambda i: (sc.concert_rank(i), i))
        self._zones = {i: "" for i in self._sections}
        self._zone_var.set("")
        self._touched = True
        self._cleared = True
        self._refresh_list(0)

    def _ok(self):
        caps = [v.get().strip() for v in self._rows
                if v.get().strip().isdigit() and int(v.get()) > 0]
        out = {
            "view": self._view.get(),
            "flip": self._front.get() == "bottom",
            "row_caps": ",".join(caps) if caps else "8",
            "color_mode": self._color.get(),
            "show_instrument": self._showinst.get(),
            "name_display": self._name_display.get(),
            "separate_percussion": self._perc.get() if self._program == "band" else False,
            "center_tuba": self._tuba.get() if self._program == "band" else False,
            "bass_corner": self._bass.get(),
            "bass_corner_side": self._bass_side.get(),
            "numbered_parts": self._parts.get(),
            "piano": self._piano.get(),
            "close_gaps": self._close.get(),
        }
        # Only write a placement if they made one.  Opening Configuration to
        # change a color must not stamp an order on the chart: "the teacher has
        # placed sections themselves" is what switches off a program's default
        # layout, so an order nobody asked for would quietly take an orchestra's
        # violins off stage right.
        if self._list is not None and (self._touched or self._had_placement):
            if self._cleared:
                out["section_order"] = []
                out["section_zones"] = {}
            else:
                out["section_order"] = list(self._sections)
                out["section_zones"] = {i: int(z)
                                        for i, z in self._zones.items() if z}
        self.result = out
        self.destroy()



class _StudentSetupDialog(ttk.Toplevel):
    """The rules that belong to individual STUDENTS: who cannot sit together,
    who needs a particular row or an empty seat beside them, and who plays
    something other than what the roster says.

    How the chart itself looks -- rows, colors, names, section placement --
    moved to Configuration.  This window used to hold half of each, which is
    why neither its name nor "Set Up" told anyone which one to open.
    """

    def __init__(self, parent, view, roster):
        super().__init__(master=parent)
        self._view = view
        self.title("Set Up")
        self.grab_set()
        self.lift()

        hdr = ttk.Frame(self, bootstyle=PRIMARY)
        hdr.pack(fill=X)
        ttk.Label(hdr, text="👤  Set Up", font=("Segoe UI", 12, "bold"),
                  bootstyle=(INVERSE, PRIMARY)).pack(pady=10, padx=16, anchor=W)

        body = ttk.Frame(self)
        body.pack(fill=BOTH, expand=True, padx=16, pady=10)
        ttk.Label(body, text="Rules for particular students on this chart.",
                  font=("Segoe UI", 9),
                  foreground=muted_fg()).pack(anchor=W, pady=(0, 8))

        ttk.Button(body, text="🚫  Keep-Apart Pairs…", bootstyle=(WARNING, OUTLINE),
                   command=view._edit_conflicts).pack(fill=X, pady=3)
        ttk.Button(body, text="♿  Special Accommodations…", bootstyle=(WARNING, OUTLINE),
                   command=view._edit_pins).pack(fill=X, pady=3)
        ttk.Button(body, text="🎺  Change a student's instrument…", bootstyle=(SECONDARY, OUTLINE),
                   command=view._edit_instruments).pack(fill=X, pady=3)

        ttk.Label(body, text="Rows, colors, names and where each section sits "
                             "are in Configuration.",
                  font=("Segoe UI", 8), foreground=muted_fg(),
                  wraplength=360, justify=LEFT).pack(anchor=W, pady=(12, 0))

        ttk.Button(self, text="Close", bootstyle=SUCCESS,
                   command=self.destroy).pack(side=RIGHT, padx=16, pady=(0, 12))
        self.resizable(True, True)
        from ui.theme import fit_window
        fit_window(self, 420, 300)


def _extract_json_object(text):
    """Parse a JSON OBJECT from an LLM reply (tolerant of code fences / prose).
    Unlike the generic extractor, this always returns the object, not an inner
    array."""
    import json
    import re
    if not text:
        return None
    t = text.strip()
    m = re.search(r"```(?:json)?\s*([\s\S]+?)```", t)
    if m:
        t = m.group(1).strip()
    try:
        v = json.loads(t)
        if isinstance(v, dict):
            return v
    except Exception:
        pass
    i, j = t.find("{"), t.rfind("}")
    if i != -1 and j != -1 and j > i:
        try:
            v = json.loads(t[i:j + 1])
            if isinstance(v, dict):
                return v
        except Exception:
            pass
    return None


_AI_SYSTEM = (
    "You help a band/orchestra teacher build a classroom or concert seating "
    "chart. Convert the teacher's plain-English instructions into a JSON object "
    "of seating constraints. Use ONLY student names exactly as they appear in "
    "the roster. Output ONLY valid JSON — no explanation, no markdown."
)


def _ai_user_prompt(roster_lines, sections, instructions):
    return (
        f"Roster (name — instrument):\n{roster_lines}\n\n"
        f"Instrument sections present: {', '.join(sections)}\n\n"
        f"Teacher's instructions:\n{instructions}\n\n"
        "Return a JSON object with any of these optional keys:\n"
        '- "keep_apart": [[nameA, nameB], ...] students who must not sit next to each other.\n'
        '- "seat_together": [[nameA, nameB], ...] students who SHOULD sit right next to each other.\n'
        '- "placements": [{"name": ..., "row": "front"|"back"|"edge"|"none", '
        '"empty_beside": 0|1|2, "note": ""}]. row places them in that row; '
        '"edge" = outside end of a row; "empty_beside" reserves empty seats next '
        "to them (a 1:1 para or a buffer around a distractible student).\n"
        '- "section_order": [instrument, ...] front-to-back order — for general '
        "front/back preferences, list every instrument section from front to back.\n"
        '- "zones": {"Instrument": [row numbers]} — lock a section to SPECIFIC rows '
        "(rows are numbered 1 = front). Use this when the teacher names exact rows, "
        'e.g. “flutes in the back row” or “trumpets in the first two rows”.\n'
        '- "shuffle_neighbors": true — set this if the teacher wants students shuffled/randomized '
        "within their sections.\n"
        '- "swaps": [[nameA, nameB], ...] to swap two students already on the chart.\n'
        "Use the section names exactly as listed above. Include only the keys relevant to "
        "the instructions."
    )


class _AIDialog(ttk.Toplevel):
    def __init__(self, parent, base_dir, roster_lines, sections, on_apply):
        super().__init__(master=parent)
        self.base_dir = base_dir
        self.roster_lines = roster_lines
        self.sections = sections
        self.on_apply = on_apply
        self._busy = False
        self.title("AI Seating Assistant")
        self.grab_set()
        self.lift()

        hdr = ttk.Frame(self, bootstyle=INFO)
        hdr.pack(fill=X)
        ttk.Label(hdr, text="🤖 AI Seating Assistant", font=("Segoe UI", 12, "bold"),
                  bootstyle=(INVERSE, INFO)).pack(pady=10, padx=16, anchor=W)

        body = ttk.Frame(self)
        body.pack(fill=BOTH, expand=True, padx=16, pady=10)
        ttk.Label(body, text="Describe any seating concerns or changes in plain English. "
                             "It works for a new chart or to adjust the current one.",
                  font=("Segoe UI", 9), wraplength=440, justify=LEFT).pack(anchor=W)
        ttk.Label(body, text="e.g. “Keep Jaden and Marcus apart, put low brass up front, "
                             "give Ava an empty seat beside her, Leo needs the front row, "
                             "swap Ozan and Rani.”",
                  font=("Segoe UI", 8), foreground=muted_fg(), wraplength=440,
                  justify=LEFT).pack(anchor=W, pady=(2, 6))
        self._text = tk.Text(body, height=6, width=54, relief="solid", bd=1, wrap=WORD,
                             font=("Segoe UI", 10))
        self._text.pack(fill=BOTH, expand=True)
        self._text.focus_set()

        self._status = ttk.Label(body, text="", font=("Segoe UI", 8),
                                 foreground=muted_fg(), wraplength=440, justify=LEFT)
        self._status.pack(anchor=W, pady=(6, 0))

        btn = ttk.Frame(self)
        btn.pack(fill=X, padx=16, pady=12)
        ttk.Button(btn, text="Close", bootstyle=(SECONDARY, OUTLINE),
                   command=self.destroy).pack(side=RIGHT, padx=4)
        self._apply_btn = ttk.Button(btn, text="Apply directions", bootstyle=INFO,
                                     command=self._run)
        self._apply_btn.pack(side=RIGHT, padx=4)

        from ui.theme import fit_window
        fit_window(self, 520, 400)

    def _run(self):
        if self._busy:
            return
        instructions = self._text.get("1.0", "end").strip()
        if not instructions:
            self._status.config(text="Type some directions first.")
            return
        self._busy = True
        self._apply_btn.config(state="disabled")
        self._status.config(text="Thinking…")

        import threading
        import llm_client

        def worker():
            result = {}
            try:
                raw = llm_client.query(
                    self.base_dir,
                    _ai_user_prompt(self.roster_lines, self.sections, instructions),
                    system_prompt=_AI_SYSTEM,
                    on_retry=lambda *a, **k: self.after(0, lambda: self._status.config(
                        text="Rate-limited, retrying…")),
                    max_tokens=1500)
                self._raw = raw
                result = _extract_json_object(raw)
                if result is None:
                    result = {"__error__": "Could not read the response as JSON. "
                              f"Model said: {(raw or '')[:200]}"}
            except Exception as e:
                result = {"__error__": str(e)}
            self.after(0, lambda: self._finish(result))

        threading.Thread(target=worker, daemon=True).start()

    def _finish(self, result):
        self._busy = False
        self._apply_btn.config(state="normal")
        if isinstance(result, dict) and result.get("__error__"):
            self._status.config(text=f"Error: {result['__error__']}")
            return
        try:
            summary = self.on_apply(result)
        except Exception as e:
            self._status.config(text=f"Could not apply: {e}")
            return
        self._status.config(text=f"Applied: {summary}")
