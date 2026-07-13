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
from ui.ensembles import ensembles_for, instruments_for, PERIOD_OPTIONS
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
        "row_caps": "8,10,12,13",
        "sort_mode": "sections",
        "color_mode": "row",            # "row" | "section" | "none"
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
        ttk.Button(parent, text="🎼  Concert Setup…", bootstyle=(INFO, OUTLINE),
                   command=self._edit_section_order).pack(fill=X, **bpad, pady=(4, 0))
        ttk.Button(parent, text="🎷  Jazz Setup…", bootstyle=(INFO, OUTLINE),
                   command=self._jazz_setup).pack(fill=X, **bpad, pady=(4, 0))

        # ── Group ──
        head("Group").pack(anchor=W, padx=10, pady=(10, 0))
        self._roster_lbl = ttk.Label(parent, text="(none selected)", font=("Segoe UI", fs(9)),
                                     wraplength=270, justify=LEFT)
        self._roster_lbl.pack(anchor=W, **bpad)
        ttk.Button(parent, text="Choose group…", bootstyle=SECONDARY,
                   command=self._edit_group).pack(fill=X, **bpad, pady=(3, 0))

        # ── Set Up (view / rows / colors / section placement) ──
        ttk.Button(parent, text="⚙  Set Up…", bootstyle=SECONDARY,
                   command=self._open_setup).pack(fill=X, **bpad, pady=(8, 0))

        # ── Group students (sort) ──
        head("Group students").pack(anchor=W, padx=10, pady=(10, 0))
        self._sort_var = tk.StringVar(value=self._cfg["sort_mode"])
        for key, label in [("alphabetical_first", "Alpha by first name"),
                           ("alphabetical", "Alpha by last name"),
                           ("small_groups", "In groups of 2–3 (like instruments)"),
                           ("sections", "By section")]:
            ttk.Radiobutton(parent, text=label, value=key, variable=self._sort_var,
                            command=self._apply_and_regen).pack(anchor=W, padx=16)

        # ── Student Set Up + AI Assist ──
        ttk.Button(parent, text="👤  Student Set Up…", bootstyle=SECONDARY,
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
        self._ensure_sections_mode()
        self._cfg["seed"] = random.randint(1, 10_000_000)
        self._cfg["shuffle_sections"] = True
        self._apply_and_regen()

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
                       self._clear_concert_setup,
                       has_setup=bool(self._cfg.get("section_order")
                                      or self._cfg.get("zones")
                                      or self._cfg.get("side_zones")))

    def _clear_concert_setup(self):
        self._cfg["section_order"] = []
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

    def _effective_instrument(self, student_id, primary, secondary):
        """Which instrument to seat a student by: a per-student override wins,
        otherwise their primary instrument (the sensible default — secondaries
        only matter for a handful of students, handled via the override dialog)."""
        override = (self._cfg.get("instrument_overrides") or {}).get(str(student_id))
        if override:
            return override
        return (primary or "").strip()

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
                "instrument": self._effective_instrument(
                    r["id"], r["primary_instrument"], r["secondary_instrument"]),
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
        # 'first' — disambiguate only on collision.
        from collections import defaultdict
        groups = defaultdict(list)
        for s in studs:
            groups[s["base"]].append(s)
        for base, members in groups.items():
            if len(members) < 2:
                members[0]["name"] = base
                continue
            inits = [(m["last"][:1] or "").upper() for m in members]
            if all(inits) and len(set(inits)) == len(members):
                for m in members:
                    m["name"] = f"{base} {(m['last'][:1] or '').upper()}."
            else:
                for m in members:
                    m["name"] = f"{base} {m['last']}".strip()

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

    def _effective_placement(self, caps):
        """(zones, side_zones) to seat by.  Orchestra programs get the standard
        string-orchestra layout by default — violins stage left, cellos stage
        right, violas in the middle, basses in the back row toward stage right
        (audience view) — unless the teacher has set anything in Concert Setup."""
        zones = self._zones_0based(caps) or {}
        sides = dict(self._cfg.get("side_zones") or {})
        customized = bool(zones or sides or self._cfg.get("section_order"))
        if self.program_type == "orchestra" and not customized:
            for v in ("Violin", "Violin 1", "Violin 2"):
                sides[v] = "left"
            for c in ("Cello", "Cello 1", "Cello 2"):
                sides[c] = "right"
            if len(caps) > 1:
                zones["String Bass"] = [len(caps) - 1]
            sides["String Bass"] = "right"
        return (zones or None), (sides or None)

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
        zones, side_zones = self._effective_placement(caps)
        self._unseated = []

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
                zones=zones, side_zones=side_zones)
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
        try:
            if self._cfg.get("view") == "arcs":
                img, boxes = sr.render_arcs(
                    self._rows, self._caps, flip=flip, percussion=perc,
                    show_instrument=show_inst, color_mode=color_mode,
                    front_label=front)
            else:
                img, boxes = sr.render_rows(
                    self._rows, self._caps, flip=flip, percussion=perc,
                    front_label=front, show_instrument=show_inst, color_mode=color_mode)
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
             + len([p for p in (self._perc or []) if p and not p.get("reserved")]))
        if n == 0 and not self._groups() and not (self._cfg.get("extra_students")):
            self._status.config(text="Choose a group to begin.")
        else:
            self._status.config(text=f"{n} seated.")
        # Problems go in the red banner under the chart.
        warns = []
        if self._unseated:
            who = ", ".join(s["name"] for s in self._unseated[:8])
            more = "…" if len(self._unseated) > 8 else ""
            warns.append(f"⚠ {len(self._unseated)} students don't fit the current rows — "
                         f"add seats or another row in Set Up ({who}{more}).")
        if self._unresolved:
            pairs = "; ".join(f"{a} & {b}" for a, b in self._unresolved[:4])
            warns.append(f"⚠ Couldn't keep these apart: {pairs}.")
        self._warn_lbl.config(text="   ".join(warns))

    # ─────────────────────────────────────────────────────── canvas clicks ────

    def _seat_get(self, key):
        r, c = key
        if r == "P":
            return self._perc[c] if c < len(self._perc) else None
        return self._rows[r][c] if c < len(self._rows[r]) else None

    def _seat_set(self, key, val):
        r, c = key
        if r == "P":
            while len(self._perc) <= c:
                self._perc.append(None)
            self._perc[c] = val
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
        for e in ensembles_for(self.program_type):
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

    def _edit_group(self):
        dlg = _GroupDialog(self.winfo_toplevel(), self._ensemble_periods(),
                           self._groups(), self._cfg.get("extra_students") or [])
        self.wait_window(dlg)
        if dlg.result is None:
            return
        self._cfg["groups"] = dlg.result["groups"]
        self._cfg["ensembles"] = []       # supersede legacy
        self._cfg["extra_students"] = dlg.result["extra"]
        self._update_roster_label()
        self._regenerate()

    def _update_roster_label(self):
        groups = self._groups()
        extra = self._cfg.get("extra_students") or []
        if not groups and not extra:
            self._roster_lbl.config(text="No group chosen yet.\nClick “Choose group…” to begin.")
            return
        parts = [f"{g['ensemble']}"
                 + ("" if g.get('period', 'all') in ('all', '', None) else f" · P{g['period']}")
                 for g in groups]
        txt = "; ".join(parts) if parts else "Added students"
        if extra:
            txt += f"  (+{len(extra)} added)"
        n = len(self._resolve_roster())
        self._roster_lbl.config(text=f"{txt}\n{n} students")

    def _open_setup(self):
        dlg = _SetupDialog(self.winfo_toplevel(), self._cfg,
                           concert=self._cfg.get("chart_type") == "concert")
        self.wait_window(dlg)
        if dlg.result is not None:
            self._cfg.update(dlg.result)
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
        for k, v in _default_config().items():
            self._cfg.setdefault(k, v)
        self._name_var.set(chart["name"])
        self._sort_var.set(self._cfg.get("sort_mode", "alphabetical"))
        self._chart_var.set(chart["name"])
        self._update_roster_label()
        layout = None
        try:
            layout = json.loads(chart["layout_json"]) if chart["layout_json"] else None
        except Exception:
            layout = None
        self._regenerate(from_layout=layout)
        self._dirty = False

    def _apply_program_defaults(self):
        """Choir and orchestra basically never need the band-specific seating
        options, so leave 'separate percussion into a back row' and 'center the
        tuba' OFF for them by default."""
        if self.program_type in ("choir", "orchestra"):
            self._cfg["separate_percussion"] = False
            self._cfg["center_tuba"] = False

    def _new_chart(self):
        self._chart_id = None
        self._cfg = _default_config()
        self._apply_program_defaults()
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
                "chart_type": self._cfg["chart_type"],
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
            return
        ok = sr.copy_image_to_clipboard(self._image)
        if ok:
            Messagebox.show_info("Seating chart copied — paste into PowerPoint, Word, or OneNote.",
                                 title="Copied", parent=self)
        else:
            Messagebox.show_warning("Could not copy the image.", title="Copy Failed", parent=self)

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
        options = instruments_for(self.program_type)
        dlg = _InstrumentDialog(self.winfo_toplevel(), roster,
                                self._cfg.get("instrument_overrides") or {}, options)
        self.wait_window(dlg)
        if dlg.result is not None:
            self._cfg["instrument_overrides"] = dlg.result
            self._regenerate()

    def _edit_section_order(self):
        roster = self._resolve_roster()
        seen, uniq = set(), []
        for s in roster:
            inst = (s.get("instrument") or "").strip()
            if inst and inst not in seen:
                seen.add(inst)
                uniq.append(inst)
        if not uniq:
            Messagebox.show_info("Choose students first.", title="No Sections", parent=self)
            return
        cur = self._cfg.get("section_order") or []
        uniq.sort(key=lambda i: (cur.index(i) if i in cur else 999, sc.concert_rank(i), i))
        n_rows = len(sc.parse_row_caps(self._cfg.get("row_caps") or "8"))
        dlg = _SectionOrderDialog(self.winfo_toplevel(), uniq,
                                  self._cfg.get("zones") or {}, n_rows,
                                  self._cfg.get("side_zones") or {})
        self.wait_window(dlg)
        if dlg.result is not None:
            self._ensure_sections_mode()
            self._cfg["section_order"] = dlg.result.get("order", [])
            self._cfg["zones"] = dlg.result.get("zones", {})
            self._cfg["side_zones"] = dlg.result.get("side_zones", {})
            self._regenerate()

    def _jazz_setup(self):
        """Apply a jazz big-band layout to the current roster: saxes across the
        front, bass-clef (trombones + horn/bari/tuba/bassoon/cello) behind, then
        trumpets and any high winds/strings in the back — rhythm section on the
        chosen side, the whole band packed toward it (empty chairs on the far
        side).  Works as straight rows OR concert arcs."""
        roster = self._resolve_roster()
        if not roster:
            Messagebox.show_info("Choose a group first.", title="No Students", parent=self)
            return
        dlg = _JazzSetupDialog(self.winfo_toplevel(),
                               side=self._cfg.get("jazz_side", "left"),
                               high_rows=int(self._cfg.get("jazz_high_rows", 1)),
                               view=self._cfg.get("view", "rows"))
        self.wait_window(dlg)
        if dlg.result is None:
            return
        insts = [s.get("instrument") for s in roster if s.get("instrument")]
        order, zones0, sides, caps = sc.jazz_layout(
            insts, high_rows=dlg.result["high_rows"], rhythm_side=dlg.result["side"])
        # cfg stores zones 1-based (the view converts back to 0-based per row count).
        self._cfg["section_order"] = order
        self._cfg["zones"] = {i: [r + 1 for r in rows] for i, rows in zones0.items()}
        self._cfg["side_zones"] = sides
        self._cfg["row_caps"] = ",".join(str(c) for c in caps)
        self._cfg["view"] = dlg.result["view"]
        self._cfg["separate_percussion"] = False   # keep drums/vibes in the layout
        self._cfg["center_tuba"] = False           # don't re-center the low row
        self._cfg["jazz_side"] = dlg.result["side"]
        self._cfg["jazz_high_rows"] = dlg.result["high_rows"]
        self._ensure_sections_mode()
        self._regenerate()

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
    """Options for a jazz big-band layout: which side the rhythm section is on
    (and the band packs toward), how many rows the trumpets/high winds may use,
    and straight rows vs. concert arcs."""

    def __init__(self, parent, side="left", high_rows=1, view="rows"):
        super().__init__(parent)
        self.result = None
        self.title("Jazz Setup")
        self.resizable(False, False)
        self.grab_set()
        self.lift()

        hdr = ttk.Frame(self, bootstyle=INFO)
        hdr.pack(fill=X)
        ttk.Label(hdr, text="🎷  Jazz Band Setup", font=("Segoe UI", 12, "bold"),
                  bootstyle=(INVERSE, INFO)).pack(pady=10, padx=16, anchor=W)

        body = ttk.Frame(self)
        body.pack(fill=BOTH, expand=True, padx=16, pady=10)
        ttk.Label(body,
                  text="Saxes go across the front, trombones (and any other "
                       "bass-clef players — horns, baritones, tubas, bassoons, "
                       "cellos) behind them, trumpets (plus any clarinets, "
                       "flutes, or strings) in the back. The rhythm section sits "
                       "on the side you pick and the whole band packs toward it, "
                       "leaving the empty chairs on the far side.",
                  font=("Segoe UI", 9), wraplength=420, justify=LEFT).pack(anchor=W)

        ttk.Label(body, text="Rhythm section on / pack toward:",
                  font=("Segoe UI", 9, "bold")).pack(anchor=W, pady=(10, 0))
        self._side = tk.StringVar(value=side if side in ("left", "right") else "left")
        srow = ttk.Frame(body)
        srow.pack(fill=X)
        ttk.Radiobutton(srow, text="Left side", value="left",
                        variable=self._side).pack(side=LEFT, padx=(0, 12))
        ttk.Radiobutton(srow, text="Right side", value="right",
                        variable=self._side).pack(side=LEFT)
        ttk.Label(body, text="(Flip this if the projected chart ends up mirrored "
                             "from your room.)",
                  font=("Segoe UI", 8), foreground=muted_fg(),
                  wraplength=420, justify=LEFT).pack(anchor=W)

        ttk.Label(body, text="Back rows (trumpets + high winds/strings):",
                  font=("Segoe UI", 9, "bold")).pack(anchor=W, pady=(10, 0))
        self._high = tk.IntVar(value=2 if int(high_rows or 1) >= 2 else 1)
        hrow = ttk.Frame(body)
        hrow.pack(fill=X)
        ttk.Radiobutton(hrow, text="One row", value=1,
                        variable=self._high).pack(side=LEFT, padx=(0, 12))
        ttk.Radiobutton(hrow, text="Two rows (split the trumpet row)", value=2,
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

        btn = ttk.Frame(self)
        btn.pack(fill=X, padx=16, pady=12)
        ttk.Button(btn, text="Cancel", bootstyle=(SECONDARY, OUTLINE),
                   command=self.destroy).pack(side=RIGHT, padx=4)
        ttk.Button(btn, text="Apply", bootstyle=SUCCESS,
                   command=self._ok).pack(side=RIGHT, padx=4)

        from ui.theme import fit_window
        fit_window(self, 470, 470)

    def _ok(self):
        self.result = {"side": self._side.get(),
                       "high_rows": int(self._high.get()),
                       "view": self._view.get()}
        self.destroy()


class _StudentPicker(ttk.Toplevel):
    def __init__(self, parent, program_type, selected, scope, extra):
        super().__init__(parent)
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
        ttk.Label(body, text="Leave unticked to use the whole current roster.",
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
        super().__init__(parent)
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

        self._list = tk.Listbox(body, height=8)
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
        super().__init__(parent)
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

        self._list = tk.Listbox(body, height=8)
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
        super().__init__(parent)
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


class _SectionOrderDialog(ttk.Toplevel):
    """Reorder the instrument sections (front-to-back placement order) and
    optionally lock a section to specific rows (a zone).  Move a section up to
    seat it closer to the front, or type e.g. “4” to keep flutes in the back row.
    """

    def __init__(self, parent, instruments, zones, n_rows, side_zones=None):
        super().__init__(parent)
        self.result = None
        self.n_rows = n_rows
        self._zones = {i: list(zones.get(i, [])) for i in instruments}
        self._sides = {i: (side_zones or {}).get(i, "") for i in instruments}
        self.title("Concert Setup")
        self.grab_set()
        self.lift()

        hdr = ttk.Frame(self, bootstyle=PRIMARY)
        hdr.pack(fill=X)
        ttk.Label(hdr, text="🎼 Concert Setup", font=("Segoe UI", 12, "bold"),
                  bootstyle=(INVERSE, PRIMARY)).pack(pady=10, padx=16, anchor=W)
        ttk.Label(self, text=f"Place sections in performance positions. Top of the list = "
                             f"frontmost. A “row zone” locks a section to specific rows "
                             f"(1–{n_rows}, front to back; e.g. 4 = back row). “Stage side” "
                             f"pins a section left or right as the audience sees it.",
                  font=("Segoe UI", 9), wraplength=400,
                  justify=LEFT).pack(anchor=W, padx=16, pady=(6, 0))

        body = ttk.Frame(self)
        body.pack(fill=BOTH, expand=True, padx=16, pady=8)
        self._instruments = list(instruments)
        self._list = tk.Listbox(body, height=12, activestyle="dotbox")
        self._list.pack(side=LEFT, fill=BOTH, expand=True)
        self._list.bind("<<ListboxSelect>>", lambda e: self._on_select())
        side = ttk.Frame(body)
        side.pack(side=LEFT, fill=Y, padx=(8, 0))
        ttk.Button(side, text="▲ Up", bootstyle=(SECONDARY, OUTLINE),
                   command=lambda: self._move(-1)).pack(fill=X, pady=2)
        ttk.Button(side, text="▼ Down", bootstyle=(SECONDARY, OUTLINE),
                   command=lambda: self._move(1)).pack(fill=X, pady=2)
        ttk.Label(side, text="Row zone:", font=("Segoe UI", 8, "bold")).pack(anchor=W, pady=(10, 0))
        self._zone_var = tk.StringVar()
        ttk.Entry(side, textvariable=self._zone_var, width=8).pack(anchor=W)
        ttk.Button(side, text="Set zone", bootstyle=(INFO, OUTLINE),
                   command=self._set_zone).pack(fill=X, pady=(2, 0))
        ttk.Button(side, text="Clear zone", bootstyle=(SECONDARY, OUTLINE),
                   command=self._clear_zone).pack(fill=X, pady=(2, 0))
        ttk.Label(side, text="Stage side:", font=("Segoe UI", 8, "bold")).pack(anchor=W, pady=(10, 0))
        self._side_var = tk.StringVar(value="")
        ttk.Combobox(side, textvariable=self._side_var, width=7, state="readonly",
                     values=["", "left", "right"]).pack(anchor=W)
        ttk.Button(side, text="Set side", bootstyle=(INFO, OUTLINE),
                   command=self._set_side).pack(fill=X, pady=(2, 0))
        ttk.Label(side, text="(audience view)", font=("Segoe UI", 7),
                  foreground=muted_fg()).pack(anchor=W)

        self._refresh_list()

        btn = ttk.Frame(self)
        btn.pack(fill=X, padx=16, pady=12)
        ttk.Button(btn, text="Cancel", bootstyle=(SECONDARY, OUTLINE),
                   command=self.destroy).pack(side=RIGHT, padx=4)
        ttk.Button(btn, text="Apply", bootstyle=SUCCESS, command=self._ok).pack(side=RIGHT, padx=4)
        ttk.Button(btn, text="Clear concert setup", bootstyle=(WARNING, OUTLINE),
                   command=self._reset).pack(side=LEFT, padx=4)

        from ui.theme import fit_window
        fit_window(self, 470, 480)

    def _refresh_list(self, select_idx=None):
        self._list.delete(0, END)
        for inst in self._instruments:
            z = self._zones.get(inst)
            sd = self._sides.get(inst)
            tag = ""
            if z:
                tag += f"  → rows {','.join(str(x) for x in z)}"
            if sd:
                tag += f"  → {sd}"
            self._list.insert(END, f"{inst}{tag}")
        self._list.selection_clear(0, END)
        if select_idx is not None and 0 <= select_idx < len(self._instruments):
            self._list.selection_set(select_idx)
            self._list.activate(select_idx)
            self._list.see(select_idx)

    def _on_select(self):
        sel = self._list.curselection()
        if sel:
            inst = self._instruments[sel[0]]
            self._zone_var.set(",".join(str(x) for x in self._zones.get(inst, [])))
            self._side_var.set(self._sides.get(inst, ""))

    def _set_side(self):
        sel = self._list.curselection()
        if not sel:
            return
        i = sel[0]
        self._sides[self._instruments[i]] = self._side_var.get()
        self._refresh_list(i)

    def _move(self, delta):
        sel = self._list.curselection()
        if not sel:
            return
        i = sel[0]
        j = i + delta
        if j < 0 or j >= len(self._instruments):
            return
        self._instruments[i], self._instruments[j] = self._instruments[j], self._instruments[i]
        self._refresh_list(j)

    def _set_zone(self):
        sel = self._list.curselection()
        if not sel:
            return
        i = sel[0]
        inst = self._instruments[i]
        rows = []
        for part in self._zone_var.get().replace(";", ",").split(","):
            part = part.strip()
            if part.isdigit() and 1 <= int(part) <= self.n_rows:
                rows.append(int(part))
        self._zones[inst] = sorted(set(rows))
        self._refresh_list(i)

    def _clear_zone(self):
        sel = self._list.curselection()
        if sel:
            i = sel[0]
            self._zones[self._instruments[i]] = []
            self._refresh_list(i)

    def _reset(self):
        self.result = {"order": [], "zones": {}, "side_zones": {}}
        self.destroy()

    def _ok(self):
        zones = {i: z for i, z in self._zones.items() if z}
        sides = {i: s for i, s in self._sides.items() if s in ("left", "right")}
        self.result = {"order": list(self._instruments), "zones": zones, "side_zones": sides}
        self.destroy()


class _LoadDialog(ttk.Toplevel):
    def __init__(self, parent, charts):
        super().__init__(parent)
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
            self._list.insert(END, f"{c['name']}   ({c['chart_type']})")
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
    def __init__(self, parent, on_all, on_members, on_sections,
                 on_clear_setup=None, has_setup=False):
        super().__init__(parent)
        self.title("Shuffle")
        self.grab_set()
        self.lift()
        ttk.Label(self, text="🔀  Shuffle", font=("Segoe UI", 13, "bold"),
                  bootstyle=PRIMARY).pack(anchor=W, padx=16, pady=(14, 8))
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
            ttk.Button(f, text=text, bootstyle=SUCCESS, width=24,
                       command=lambda: run(cb)).pack(side=LEFT)
            ttk.Label(f, text=desc, font=("Segoe UI", 9), wraplength=230,
                      justify=LEFT).pack(side=LEFT, padx=8)

        make("Shuffle all students", "Everyone gets a new seat and new neighbors, every click.",
             on_all)
        make("Shuffle within sections", "Keep sections where they are; change who sits by whom.",
             on_members)
        make("Shuffle section placement", "Move whole sections to different parts of the room.",
             on_sections)

        if has_setup:
            ttk.Separator(body).pack(fill=X, pady=(8, 4))
            ttk.Checkbutton(body, text="Also clear Concert Setup (section order, row zones, "
                                       "stage sides) so nothing stays pinned",
                            variable=self._clear, bootstyle=WARNING).pack(anchor=W)
            ttk.Label(body, text="Otherwise, sections locked to a zone or stage side stay put "
                                 "and everything else moves.",
                      font=("Segoe UI", 8), foreground=muted_fg(),
                      wraplength=430, justify=LEFT).pack(anchor=W, pady=(2, 0))

        ttk.Button(self, text="Cancel", bootstyle=(SECONDARY, OUTLINE),
                   command=self.destroy).pack(side=RIGHT, padx=16, pady=(0, 12))
        from ui.theme import fit_window
        fit_window(self, 500, 380 if has_setup else 300)


class _GroupDialog(ttk.Toplevel):
    """Pick ensemble × class-period combinations (multi-select for concerts),
    plus optional add-ins from another ensemble."""

    def __init__(self, parent, ensemble_periods, current, extra):
        super().__init__(parent)
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
        ttk.Label(body, text="Tick a whole ensemble, or specific class periods. "
                             "Tick several to combine for a concert.",
                  font=("Segoe UI", 9), wraplength=340, justify=LEFT).pack(anchor=W)

        self._all_vars = {}
        self._period_vars = {}
        if not ensemble_periods:
            ttk.Label(body, text="No ensembles with students found. "
                                 "Leave blank to use the whole current roster.",
                      font=("Segoe UI", 8), foreground=muted_fg(),
                      wraplength=340, justify=LEFT).pack(anchor=W, pady=(6, 0))
        display = {"Jazz 1": "Jazz Band 1", "Jazz 2": "Jazz Band 2"}
        for e, periods in ensemble_periods.items():
            disp = display.get(e, e)
            self._period_vars[e] = {}
            if len(periods) <= 1:
                # Meets all together, all the time — one box is enough.
                ticked = (e, "all") in cur or any((e, p) in cur for p in periods)
                av = tk.BooleanVar(value=ticked)
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


class _SetupDialog(ttk.Toplevel):
    """View / rows / color / section-placement setup window."""

    def __init__(self, parent, cfg, concert):
        super().__init__(parent)
        self.result = None
        self.title("Set Up")
        self.grab_set()
        self.lift()

        hdr = ttk.Frame(self, bootstyle=PRIMARY)
        hdr.pack(fill=X)
        ttk.Label(hdr, text="⚙  Set Up", font=("Segoe UI", 12, "bold"),
                  bootstyle=(INVERSE, PRIMARY)).pack(pady=10, padx=16, anchor=W)

        body = ttk.Frame(self)
        body.pack(fill=BOTH, expand=True, padx=16, pady=10)

        ttk.Label(body, text="View", font=("Segoe UI", 10, "bold")).pack(anchor=W)
        self._view = tk.StringVar(value=cfg.get("view", "rows"))
        vf = ttk.Frame(body)
        vf.pack(fill=X)
        ttk.Radiobutton(vf, text="Rows", value="rows", variable=self._view).pack(side=LEFT)
        ttk.Radiobutton(vf, text="Arcs", value="arcs", variable=self._view).pack(side=LEFT, padx=(12, 0))

        ttk.Label(body, text="Front of the room is", font=("Segoe UI", 10, "bold")).pack(anchor=W, pady=(10, 0))
        self._front = tk.StringVar(value="bottom" if cfg.get("flip") else "top")
        ff = ttk.Frame(body)
        ff.pack(fill=X)
        ttk.Radiobutton(ff, text="Top", value="top", variable=self._front).pack(side=LEFT)
        ttk.Radiobutton(ff, text="Bottom", value="bottom", variable=self._front).pack(side=LEFT, padx=(12, 0))

        ttk.Label(body, text="Seats in each row (front → back)",
                  font=("Segoe UI", 10, "bold")).pack(anchor=W, pady=(10, 0))
        ttk.Label(body, text="Leave a box blank to remove that row.",
                  font=("Segoe UI", 8), foreground=muted_fg()).pack(anchor=W)
        caps = sc.parse_row_caps(cfg.get("row_caps") or "8")
        self._rows = []
        rowsf = ttk.Frame(body)
        rowsf.pack(fill=X, pady=(2, 0))
        for i in range(6):
            r = ttk.Frame(rowsf)
            r.pack(fill=X, pady=1)
            ttk.Label(r, text=f"Row {i + 1}:", width=7).pack(side=LEFT)
            v = tk.StringVar(value=str(caps[i]) if i < len(caps) else "")
            self._rows.append(v)
            ttk.Entry(r, textvariable=v, width=6).pack(side=LEFT)

        ttk.Label(body, text="Color coding", font=("Segoe UI", 10, "bold")).pack(anchor=W, pady=(10, 0))
        self._color = tk.StringVar(value=cfg.get("color_mode", "row"))
        cf = ttk.Frame(body)
        cf.pack(fill=X)
        ttk.Radiobutton(cf, text="By row", value="row", variable=self._color).pack(side=LEFT)
        ttk.Radiobutton(cf, text="By section", value="section", variable=self._color).pack(side=LEFT, padx=(12, 0))
        ttk.Radiobutton(cf, text="None", value="none", variable=self._color).pack(side=LEFT, padx=(12, 0))

        ttk.Label(body, text="Section placement", font=("Segoe UI", 10, "bold")).pack(anchor=W, pady=(10, 0))
        self._perc = tk.BooleanVar(value=cfg.get("separate_percussion", True))
        ttk.Checkbutton(body, text="Keep percussion in a back row", variable=self._perc,
                        bootstyle=INFO).pack(anchor=W)
        self._tuba = tk.BooleanVar(value=cfg.get("center_tuba", True))
        ttk.Checkbutton(body, text="Keep tuba in the middle of the back row", variable=self._tuba,
                        bootstyle=INFO).pack(anchor=W)

        btn = ttk.Frame(self)
        btn.pack(fill=X, padx=16, pady=12)
        ttk.Button(btn, text="Cancel", bootstyle=(SECONDARY, OUTLINE),
                   command=self.destroy).pack(side=RIGHT, padx=4)
        ttk.Button(btn, text="Apply", bootstyle=SUCCESS, command=self._ok).pack(side=RIGHT, padx=4)
        from ui.theme import fit_window
        fit_window(self, 420, 620)

    def _ok(self):
        caps = [v.get().strip() for v in self._rows if v.get().strip().isdigit() and int(v.get()) > 0]
        self.result = {
            "view": self._view.get(),
            "flip": self._front.get() == "bottom",
            "row_caps": ",".join(caps) if caps else "8",
            "color_mode": self._color.get(),
            "separate_percussion": self._perc.get(),
            "center_tuba": self._tuba.get(),
        }
        self.destroy()


class _StudentSetupDialog(ttk.Toplevel):
    """One window: keep-apart, accommodations, change-instrument, section order,
    and name-display options."""

    def __init__(self, parent, view, roster):
        super().__init__(parent)
        self._view = view
        self.title("Student Set Up")
        self.grab_set()
        self.lift()

        hdr = ttk.Frame(self, bootstyle=PRIMARY)
        hdr.pack(fill=X)
        ttk.Label(hdr, text="👤  Student Set Up", font=("Segoe UI", 12, "bold"),
                  bootstyle=(INVERSE, PRIMARY)).pack(pady=10, padx=16, anchor=W)

        body = ttk.Frame(self)
        body.pack(fill=BOTH, expand=True, padx=16, pady=10)

        ttk.Button(body, text="🚫  Keep-Apart Pairs…", bootstyle=(WARNING, OUTLINE),
                   command=view._edit_conflicts).pack(fill=X, pady=3)
        ttk.Button(body, text="♿  Special Accommodations…", bootstyle=(WARNING, OUTLINE),
                   command=view._edit_pins).pack(fill=X, pady=3)
        ttk.Button(body, text="🎺  Change a student's instrument…", bootstyle=(SECONDARY, OUTLINE),
                   command=view._edit_instruments).pack(fill=X, pady=3)

        ttk.Separator(body).pack(fill=X, pady=(10, 6))
        ttk.Label(body, text="Show on the chart", font=("Segoe UI", 10, "bold")).pack(anchor=W)
        self._showinst = tk.BooleanVar(value=view._cfg.get("show_instrument", True))
        ttk.Checkbutton(body, text="Show instrument under each name", variable=self._showinst,
                        bootstyle=INFO, command=self._apply).pack(anchor=W)

        ttk.Label(body, text="Names", font=("Segoe UI", 10, "bold")).pack(anchor=W, pady=(8, 0))
        self._name = tk.StringVar(value=view._cfg.get("name_display", "first"))
        for val, txt in [("first", "First name only (add last initial only if two share a name)"),
                         ("last_initial", "Show all last-name initials"),
                         ("last_full", "Show full last names")]:
            ttk.Radiobutton(body, text=txt, value=val, variable=self._name,
                            command=self._apply).pack(anchor=W)

        ttk.Button(self, text="Close", bootstyle=SUCCESS,
                   command=self.destroy).pack(side=RIGHT, padx=16, pady=(0, 12))
        self.resizable(True, True)
        from ui.theme import fit_window
        fit_window(self, 420, 460)

    def _apply(self):
        self._view._cfg["show_instrument"] = self._showinst.get()
        self._view._cfg["name_display"] = self._name.get()
        self._view._regenerate()


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
        super().__init__(parent)
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
