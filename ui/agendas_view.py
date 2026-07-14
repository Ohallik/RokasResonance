"""
ui/agendas_view.py - Daily Agendas tab (parameterized per ensemble).

One ``AgendasView`` serves both Entry and Intermediate Band (``group=`` picks
which); the two share the whole editor/present machinery and differ only by the
per-group ``GROUP_CONFIG`` (label, percussion class type, concert-ensemble, and
which Standard of Excellence book the band-book picker uses) plus the group-aware
curriculum spine.

Two views of one day:
  * PLAN  - edit a day as named, colored checklists (reminders, announcements,
            warm-up, band book, sheet music, Practice Journal), the day's
            percussion rotation, and pasted rhythm images.  Jump by day / week
            / month; a context line shows the concert cycle / warm-up level.
  * PRESENT - a full-screen classroom projection: a live clock AND a countdown
            timer (both visible), a chosen pastel background, per-line text
            colours / highlights, a Reminders + Announcements banner, and the
            agenda sections with big check-off boxes.  The percussion rotation
            is a SEPARATE floating panel (top-right) that can be collapsed once
            the players are set so it doesn't cover the agenda.  Empty sections
            are hidden.

The curriculum spine (agenda_spine.py) generates each day's sensible default.

NOTE ON COLOURS: ttkbootstrap resets the colours of plain tk widgets set at
construction time, but a post-construction ``.configure()`` sticks.  So every
coloured tk widget here is built through ``_tk(...)``, which applies the colour
options AFTER the widget exists.  Do NOT pass bg/fg straight to tk.Label/etc.
"""

import os
import json
import time
import calendar
import tkinter as tk
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from ttkbootstrap.dialogs import Messagebox
from datetime import date, timedelta

import agenda_spine as spine
import percussion_rotation as pr
import school_calendar as scal
from ui.theme import muted_fg, fs

ENTRY_GROUP = "entry"
INTERMEDIATE_GROUP = "intermediate"
ADVANCED_GROUP = "advanced"
JAZZ_GROUP = "jazz"
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri"]

# One parameterized view serves every ensemble.  Per-group config: display label,
# the percussion class_type to show, the concert-ensemble keyword (to pull that
# ensemble's repertoire), and which Standard of Excellence book the band-book
# picker uses (Entry = Bk 1, Intermediate = Bk 2, Advanced = none — their day is
# mostly blank + teacher-driven).
GROUP_CONFIG = {
    ENTRY_GROUP: {"label": "Entry Band", "class_type": pr.ENTRY,
                  "ensemble": "entry", "book": 1},
    INTERMEDIATE_GROUP: {"label": "Intermediate Band", "class_type": pr.INT_ADV,
                         "ensemble": "interm", "book": 2},
    ADVANCED_GROUP: {"label": "Advanced Band", "class_type": pr.INT_ADV,
                     "ensemble": "adv", "book": None},
    # Jazz — no method book, no earn-based percussion; its "percussion" panel is
    # the jazz rhythm-section rotation, and multiple jazz bands are picked with a
    # toolbar dropdown (each band is its own agenda, keyed "jazz_<ensemble id>").
    JAZZ_GROUP: {"label": "Jazz Band", "class_type": None,
                 "ensemble": "jazz", "book": None},
}

# Section-header chip.
HDR_BG = "#3b7dc4"
HDR_FG = "#ffffff"
# Assessment-line highlight (the light-blue emphasis she uses for test lines).
ASSESS_BG = "#dbeafe"
ASSESS_FG = "#0b3d6b"

# Countdown-timer presets she uses (label, seconds).
TIMER_PRESETS = [("30 sec", 30), ("1 min", 60), ("2 min", 120),
                 ("3 min", 180), ("5 min", 300), ("10 min", 600)]

# Present-mode background choices (name -> hex).  Soft pastels like OneNote's
# page colours, so projected text stays readable (dark on light).
PRESENT_BGS = [("White", "#ffffff"), ("Blue", "#dbe9fb"), ("Green", "#e2f0d9"),
               ("Yellow", "#fdf5cf"), ("Peach", "#fbe5d6"), ("Pink", "#fbe0ea"),
               ("Lavender", "#e9e3f6"), ("Gray", "#eceff1")]
PRESENT_BG_MAP = dict(PRESENT_BGS)

# A few per-line text colours to make a line pop (name, value).  Vivid, so
# "Red" reads as red on a projector — not a muted brick.
ITEM_COLORS = [("Default", ""), ("Black", "black"), ("Blue", "blue"),
               ("Red", "red"), ("White", "white"), ("Yellow highlight", "hl")]
_TEXT_HEX = {"black": "#111111", "blue": "#1565d8", "red": "#e11414",
             "white": "#ffffff"}
_HL = ("#111111", "#fff59d")   # (fg, bg) yellow highlight

# tk colour options that ttkbootstrap clobbers at construction time — we strip
# these out, build the widget, then .configure() them so they take effect.
_COLOR_KEYS = {"bg", "fg", "background", "foreground", "insertbackground",
               "selectbackground", "selectforeground", "activebackground",
               "activeforeground", "highlightbackground", "highlightcolor",
               "selectcolor", "disabledforeground", "readonlybackground"}


def _tk(cls, parent, **kw):
    """Create a plain tk widget whose colour options actually stick under
    ttkbootstrap (see module docstring)."""
    colors = {k: kw.pop(k) for k in list(kw) if k in _COLOR_KEYS}
    w = cls(parent, **kw)
    if colors:
        w.configure(**colors)
    return w


def _lum(hexcolor):
    h = hexcolor.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _auto_fg(bg):
    return "#f4f4f4" if _lum(bg) < 0.5 else "#141414"


def _plan_colors(color, kind):
    """(fg, bg) for a line in the PLAN editor (which is always light)."""
    if color == "hl":
        return _HL
    if color == "white":
        return ("#ffffff", "#333333")          # dark chip so white is visible
    if color in ("black", "blue", "red"):
        return (_TEXT_HEX[color], "#ffffff")
    if kind == "assessment":
        return (ASSESS_FG, ASSESS_BG)
    return ("#1a1a1a", "#ffffff")


def _present_colors(color, kind, bg):
    """(fg, bg) for a line in PRESENT, over background ``bg``."""
    if color == "hl":
        return _HL
    if color in _TEXT_HEX:
        return (_TEXT_HEX[color], bg)
    if kind == "assessment":
        return (ASSESS_FG, ASSESS_BG)
    return (_auto_fg(bg), bg)


def _perc_icon(widget, station):
    from ui.percussion_rotation_view import _icon_for_station
    return _icon_for_station(widget, station)


def _station_color(station):
    from ui.percussion_rotation_view import _color_for_station
    return _color_for_station(station)


class AgendasView(ttk.Frame):
    def __init__(self, parent, db, main_db=None, base_dir=None,
                 group=None, klass=None):
        super().__init__(parent)
        self.db = db
        self.main_db = main_db
        self.base_dir = base_dir
        # A class is described by a registry dict (class_registry.py) pointing at
        # a TEMPLATE.  ``_template`` drives behavior (band_entry / band_intermediate
        # / band_advanced / jazz / generic); ``_group`` is the per-day storage key.
        # For the three concert bands the id equals the legacy group name so old
        # saved agendas keep working.  Jazz differs: one tab serves any number of
        # jazz bands, so its storage key is "jazz_<ensemble id>" and the active
        # band is chosen from a toolbar toggle.  Older callers pass ``group=`` (a
        # legacy name) instead of ``klass=`` — build a class dict from GROUP_CONFIG.
        import class_registry
        if klass is None:
            g = group if group in GROUP_CONFIG else ENTRY_GROUP
            gc = GROUP_CONFIG[g]
            klass = {"id": g,
                     "label": gc["label"],
                     "template": {ENTRY_GROUP: "band_entry",
                                  INTERMEDIATE_GROUP: "band_intermediate",
                                  ADVANCED_GROUP: "band_advanced",
                                  JAZZ_GROUP: "jazz"}.get(g, "generic"),
                     "ensemble": gc["ensemble"], "book": gc["book"],
                     "percussion": gc["class_type"] is not None}
        self._klass = klass
        cfg = class_registry.class_config(klass)
        self._template = cfg["template"]
        self._is_jazz = cfg["is_jazz"]
        self._book = cfg["book"]
        # Choir and orchestra never have a percussion rotation — force it off for
        # those programs regardless of the class flag.
        self._percussion = (cfg["percussion"]
                            and self._program_type() not in ("choir", "orchestra"))
        ct = cfg["class_type"]
        class_type = pr.ENTRY if ct == "entry" else (pr.INT_ADV if ct == "int_adv"
                                                     else None)
        self._cfg = {"label": cfg["label"], "ensemble": cfg["ensemble"],
                     "book": cfg["book"], "class_type": class_type}
        self._store_id = cfg["id"]
        self._jazz_eid = self._first_jazz_eid() if self._is_jazz else None
        self._group = self._jazz_store_key() if self._is_jazz else self._store_id
        self._date = _snap_weekday(date.today())
        self._day = None
        self._saved = False
        self._present = None
        self._img_refs = []
        self._build()
        self.refresh()

    # ──────────────────────────────────────────────────────────── jazz mode ────
    # Jazz is the only ensemble whose one tab serves several bands.  These helpers
    # resolve the active band, its storage key, and its rhythm-section rotation.

    def _program_type(self):
        try:
            from ui.settings_dialog import load_settings
            return (load_settings(self.base_dir).get("teacher") or {}).get(
                "program_type", "band")
        except Exception:
            return "band"

    def _technique_enabled(self):
        """The Advanced 'Technique & Musicianship' key picker is one teacher's
        personal warm-up system and confuses everyone else, so it's off unless a
        profile explicitly opts in (teacher.technique_musicianship = true)."""
        try:
            from ui.settings_dialog import load_settings
            return bool((load_settings(self.base_dir).get("teacher") or {}).get(
                "technique_musicianship"))
        except Exception:
            return False

    def _last_reminders(self):
        """Carry the most recent saved day's Reminders forward — blank for a
        brand-new user until they type their own."""
        for iso in sorted(self.db.get_saved_agenda_dates(self._group), reverse=True):
            sd = _parse_date(iso)
            if not sd or sd > self._date:
                continue
            row = self.db.get_agenda_day(self._group, iso)
            try:
                day = json.loads(row["data"])
            except Exception:
                continue
            return list(day.get("reminders") or [])
        return []

    def _jazz_ensembles(self):
        return self.db.get_jazz_ensembles(self._year()) if self._is_jazz else []

    def _first_jazz_eid(self):
        ens = self._jazz_ensembles()
        return ens[0]["id"] if ens else None

    def _jazz_store_key(self):
        return f"jazz_{self._jazz_eid}" if self._jazz_eid else "jazz_none"

    def _jazz_ensemble(self):
        if not self._is_jazz or self._jazz_eid is None:
            return None
        return self.db.get_jazz_ensemble(self._jazz_eid)

    def _sync_jazz_selection(self):
        """Re-validate the active band against what exists now (bands are created
        on the Jazz tab) and rebuild the toolbar toggle."""
        ens = self._jazz_ensembles()
        self._jazz_ids = [e["id"] for e in ens]
        if self._jazz_eid not in self._jazz_ids:
            self._jazz_eid = self._jazz_ids[0] if self._jazz_ids else None
        self._group = self._jazz_store_key()
        self._render_jazz_selector(ens)

    def _render_jazz_selector(self, ens=None):
        """Side-by-side band toggle — the same look as the P1/P2 Section toggle."""
        if getattr(self, "_jazz_bar", None) is None:
            return
        for w in self._jazz_bar.winfo_children():
            w.destroy()
        if ens is None:
            ens = self._jazz_ensembles()
        if not ens:
            ttk.Label(self._jazz_bar, text="  (create a band on the 🎷 Jazz tab)",
                      font=("Segoe UI", fs(9)),
                      foreground=muted_fg()).pack(side=LEFT, padx=(6, 0))
            return
        ttk.Label(self._jazz_bar, text="Band:",
                  font=("Segoe UI", fs(9))).pack(side=LEFT, padx=(14, 4))
        self._jazz_var = tk.StringVar(
            value=str(self._jazz_eid) if self._jazz_eid else "")
        for e in ens:
            ttk.Radiobutton(self._jazz_bar, text=e["name"], value=str(e["id"]),
                            variable=self._jazz_var, bootstyle=(INFO, "toolbutton"),
                            command=lambda gid=e["id"]: self._set_jazz(gid)
                            ).pack(side=LEFT, padx=1)

    def _set_jazz(self, eid):
        self._jazz_eid = eid
        self._group = self._jazz_store_key()
        self.refresh()

    def _jazz_seats_players(self):
        e = self._jazz_ensemble()
        if not e:
            return [], [], []
        import jazz_rotation as jr
        seats = _safe_json(e["seats"], [])           # [{name, capacity}, ...]
        try:
            pools = _safe_json(e["pools"], []) or []
        except (KeyError, IndexError):
            pools = []
        players = []
        for r in self.db.get_jazz_players(e["id"]):
            players.append({"name": r["name"],
                            "parts": jr._clean_seats(_safe_json(r["parts"], []))})
        return seats, players, pools

    def _jazz_day(self):
        """Warm-up rotation day for this school day — auto-advances day to day and
        wraps by the rotation cycle, like the percussion rotation."""
        import jazz_rotation as jr
        seats, players, pools = self._jazz_seats_players()
        cyc = jr.cycle_length(seats, players, pools=pools)
        if cyc <= 0:
            return 1
        cal = self._calendar()
        if cal:
            idx = scal.school_day_index(cal, self._date)
        else:
            start, _end = self._year_bounds()
            idx = spine._school_days_between(start, self._date)
        return ((idx - 1) % cyc) + 1

    def _jazz_rotation(self):
        import jazz_rotation as jr
        seats, players, pools = self._jazz_seats_players()
        if not seats:
            return [], []
        return jr.day_assignments(seats, players, self._jazz_day(), pools=pools)

    def _display_label(self):
        if self._is_jazz:
            e = self._jazz_ensemble()
            return e["name"] if e else self._cfg["label"]
        return self._cfg["label"]

    # ─────────────────────────────────────────────────────────────── build ────

    def _build(self):
        bar = ttk.Frame(self, bootstyle=LIGHT)
        bar.pack(fill=X)
        ttk.Label(bar, text=f"📋  {self._cfg['label']} — Daily Agenda",
                  font=("Segoe UI", fs(12), "bold")).pack(side=LEFT, padx=10, pady=8)
        # Jazz bands switch with side-by-side toggle buttons, exactly like the
        # P1/P2 percussion Section toggle (populated in _render_jazz_selector).
        self._jazz_bar = ttk.Frame(bar)
        if self._is_jazz:
            self._jazz_bar.pack(side=LEFT)
        self._section_bar = ttk.Frame(bar)      # P1/P2 toggle (populated on render)
        self._section_bar.pack(side=LEFT)
        ttk.Button(bar, text="🖥 Present", bootstyle=SUCCESS,
                   command=self._open_present).pack(side=RIGHT, padx=8, pady=6)
        if not self._is_jazz:
            ttk.Button(bar, text="🎯 Assessments…", bootstyle=(INFO, OUTLINE),
                       command=self._open_assessments).pack(side=RIGHT, padx=2, pady=6)
        ttk.Button(bar, text="↺ Reset Day", bootstyle=(SECONDARY, OUTLINE),
                   command=self._reset_day).pack(side=RIGHT, padx=2, pady=6)
        ttk.Label(bar, text="Screen bg:", font=("Segoe UI", fs(9))).pack(
            side=RIGHT, padx=(10, 2))
        self._bg_var = tk.StringVar(value=self._present_bg_name())
        bg_combo = ttk.Combobox(bar, textvariable=self._bg_var, state="readonly",
                                width=11, values=[n for n, _ in PRESENT_BGS])
        bg_combo.pack(side=RIGHT, pady=6)
        bg_combo.bind("<<ComboboxSelected>>", self._on_bg_change)

        nav = ttk.Frame(self)
        nav.pack(fill=X, padx=10, pady=(6, 0))

        def navbtn(text, cmd, w=4):
            ttk.Button(nav, text=text, width=w, bootstyle=(SECONDARY, OUTLINE),
                       command=cmd).pack(side=LEFT, padx=1)
        navbtn("« Month", lambda: self._shift_month(-1), w=8)
        navbtn("‹ Week", lambda: self._shift_week(-1), w=7)
        navbtn("◀", lambda: self._shift_day(-1), w=3)
        self._date_lbl = ttk.Label(nav, text="", font=("Segoe UI", fs(11), "bold"),
                                   width=26, anchor=CENTER)
        self._date_lbl.pack(side=LEFT, padx=4)
        navbtn("▶", lambda: self._shift_day(1), w=3)
        navbtn("Week ›", lambda: self._shift_week(1), w=7)
        navbtn("Month »", lambda: self._shift_month(1), w=8)
        ttk.Button(nav, text="Today", bootstyle=(INFO, OUTLINE),
                   command=self._go_today).pack(side=LEFT, padx=(8, 0))
        self._saved_lbl = ttk.Label(nav, text="", font=("Segoe UI", fs(8)),
                                    foreground=muted_fg())
        self._saved_lbl.pack(side=LEFT, padx=10)

        self._ctx_lbl = ttk.Label(self, text="", font=("Segoe UI", fs(9), "italic"),
                                  foreground=muted_fg())
        self._ctx_lbl.pack(fill=X, padx=12, pady=(2, 0))

        self._week_bar = ttk.Frame(self)
        self._week_bar.pack(fill=X, padx=10, pady=(4, 0))

        self._canvas = tk.Canvas(self, highlightthickness=0)
        vsb = ttk.Scrollbar(self, orient=VERTICAL, command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side=RIGHT, fill=Y)
        self._canvas.pack(side=LEFT, fill=BOTH, expand=True, padx=(10, 0), pady=8)
        self._inner = ttk.Frame(self._canvas)
        self._win = self._canvas.create_window((0, 0), window=self._inner, anchor="nw")
        self._inner.bind("<Configure>",
                         lambda e: self._canvas.configure(scrollregion=self._canvas.bbox("all")))
        self._canvas.bind("<Configure>",
                          lambda e: self._canvas.itemconfig(self._win, width=e.width))
        self._canvas.bind("<Enter>", lambda e: self._canvas.bind_all(
            "<MouseWheel>", self._on_wheel))
        self._canvas.bind("<Leave>", lambda e: self._canvas.unbind_all("<MouseWheel>"))

    def _on_wheel(self, event):
        self._canvas.yview_scroll(int(-event.delta / 120), "units")

    # ─────────────────────────────────────────────────────────── data / ctx ───

    def refresh(self):
        if self._is_jazz:
            self._sync_jazz_selection()
        cal = self._calendar()
        if cal and not scal.is_school_day(cal, self._date):
            nd = scal.next_school_day(cal, self._date) or \
                scal.prev_school_day(cal, self._date)
            if nd:
                self._date = nd
        self._load_day()
        self._render()

    def _calendar(self):
        return scal.get_calendar(self._year())

    def _snap(self, d):
        cal = self._calendar()
        if cal:
            return (scal.next_school_day(cal, d) or
                    scal.prev_school_day(cal, d) or _snap_weekday(d))
        return _snap_weekday(d)

    def _year(self):
        base = os.path.basename(self.db.db_path)
        if base.startswith("lesson_plans_") and base.endswith(".db"):
            return base[len("lesson_plans_"):-len(".db")]
        return None

    def _year_bounds(self):
        cal = self._calendar()
        if cal:
            return cal["first_day"], cal["last_day"]
        y = self._year() or ""
        try:
            s, e = (int(x) for x in y.split("-"))
        except Exception:
            t = date.today()
            s = t.year if t.month >= 8 else t.year - 1
            e = s + 1
        return date(s, 9, 1), date(e, 6, 30)

    def _context(self):
        start, end = self._year_bounds()
        return {"template": self._template,
                "reminders": self._last_reminders(),
                "year_start": start, "year_end": end,
                "calendar": self._calendar(),
                "assessments": self._load_assessments(),   # None => seed default
                "intro_days": self._intro_days(),
                "band_page": self._page_label_for(self._date),
                "concerts": self._concerts()}

    def _intro_days(self):
        """School days of instrument exploration before page-6 work begins.
        Per-teacher (program_setting), defaulting to her ~8 (page 6 starts the
        third week of school)."""
        raw = self.db.get_program_setting("agenda_intro_days")
        try:
            return max(0, int(raw))
        except (TypeError, ValueError):
            return spine.INTRO_SCHOOL_DAYS

    # ── teacher-defined assessments (per group, per year; None if uncustomised)

    def _assess_key(self):
        return f"agenda_assessments_{self._group}"

    def _load_assessments(self):
        raw = self.db.get_program_setting(self._assess_key())
        if not raw:
            return None
        try:
            data = json.loads(raw)
        except Exception:
            return None
        out = []
        for r in data:
            ref = (r.get("ref") or "").strip()
            if not ref:
                continue
            # due may be blank (dateless assessments — kept in the list but not
            # auto-surfaced on the agenda until the teacher assigns a date).
            out.append({"ref": ref, "due": _parse_date(r.get("due"))})
        return out

    def _save_assessments(self, items):
        payload = [{"ref": i["ref"],
                    "due": i["due"].isoformat() if i.get("due") else ""}
                   for i in items if i.get("ref")]
        self.db.set_program_setting(self._assess_key(), json.dumps(payload))
        self.refresh()

    def _default_assessments(self):
        """No suggested schedule is seeded for any class anymore; assessments are
        entirely teacher-entered (the app only tracks due dates they add)."""
        # No suggested schedule is seeded for any class. Assessments are entirely
        # teacher-entered — the app only tracks due dates the teacher adds.
        return []

    def _open_assessments(self):
        items = self._load_assessments()
        if items is None:                    # seed from the suggested list
            items = self._default_assessments()
        _AssessmentsDialog(self, items)

    # ── sticky band-book page: carry the last page you set forward until you
    #    change it again; before any is set, assume NO page (start empty) ──

    def _page_label_for(self, d):
        import re
        for iso in sorted(self.db.get_saved_agenda_dates(self._group), reverse=True):
            sd = _parse_date(iso)
            if not sd or sd > d:
                continue
            row = self.db.get_agenda_day(self._group, iso)
            try:
                day = json.loads(row["data"])
            except Exception:
                continue
            for sec in day.get("sections", []):
                k = sec.get("kind")
                if k is None:
                    k = _infer_section_kind(sec.get("title", ""))
                if k != "bandbook":
                    continue
                for it in sec.get("items", []):
                    m = re.match(r"\s*p\.\s*([0-9]+(?:-[0-9]+)?)", it.get("text", ""))
                    if m:
                        return m.group(1)
        # No page was ever set on an earlier day — don't assume one.  The Band
        # book section starts empty (just the page/line pickers).
        return None

    def _concerts(self):
        out = []
        for c in self.db.get_concerts(self._year()):
            d = _parse_date(c["concert_date"])
            if d:
                out.append({"date": d, "title": c["title"],
                            "pieces": self._pieces(c)})
        return out

    def _pieces(self, concert):
        rows = self.db.get_concert_pieces(concert["id"])
        kw = self._cfg["ensemble"]
        matched = [r for r in rows if kw in (r["ensemble"] or "").lower()]
        use = matched if matched else rows
        return [r["title"] for r in use if r["title"]]

    def _load_day(self):
        row = self.db.get_agenda_day(self._group, self._date.isoformat())
        if row and row["data"]:
            try:
                self._day = json.loads(row["data"])
                self._saved = True
                self._heal_kinds(self._day)
                self._ensure_ids(self._day)
                return
            except Exception:
                pass
        self._day = spine.build_default_day(self._date, self._context())
        self._saved = False
        self._ensure_ids(self._day)

    def _heal_kinds(self, day):
        """Older saved days stored every section with a null ``kind``, which hid
        the special sections (band-book page/line picker, Rhythms image pane,
        Advanced warm-up picker, etc.).  Infer a missing kind from the section
        title so those days behave like freshly-generated ones.  Only fills a
        genuinely absent kind — a section the teacher made plain on purpose (via
        "Add Section") has kind "" and is left alone."""
        for sec in (day or {}).get("sections", []):
            if sec.get("kind") is not None:
                continue
            sec["kind"] = _infer_section_kind(sec.get("title", ""))

    def _ensure_ids(self, day):
        """Give every item a stable id so per-section checkbox state can key to
        it.  Assigned in memory; persisted whenever the (shared) day is saved."""
        import uuid
        for sec in (day or {}).get("sections", []):
            for it in sec.get("items", []):
                if not it.get("id"):
                    it["id"] = uuid.uuid4().hex[:12]

    def _save_day(self, rebuild_present=True):
        self.db.save_agenda_day(self._group, self._date.isoformat(),
                                json.dumps(self._day))
        self._saved = True
        self._saved_lbl.config(text="Saved ✓")
        if (rebuild_present and self._present is not None
                and self._present.winfo_exists()):
            self._present.rebuild()

    def _present_bg_name(self):
        return self.db.get_program_setting("agenda_present_bg") or "White"

    def _present_bg(self):
        return PRESENT_BG_MAP.get(self._present_bg_name(), "#ffffff")

    def _on_bg_change(self, _e=None):
        self.db.set_program_setting("agenda_present_bg", self._bg_var.get())
        if self._present is not None and self._present.winfo_exists():
            self._present.rebuild()

    def _base(self):
        return self.base_dir or os.path.dirname(os.path.abspath(self.db.db_path))

    def _image_abspath(self, rel):
        return rel if os.path.isabs(rel) else os.path.join(self._base(), rel)

    # ─────────────────────────────────────────────────────────── navigation ───

    def _shift_day(self, delta):
        cal = self._calendar()
        if cal:
            step = timedelta(days=1)
            nd = (scal.next_school_day(cal, self._date + step) if delta > 0
                  else scal.prev_school_day(cal, self._date - step))
            if nd:
                self._date = nd
        else:
            d = self._date
            for _ in range(14):
                d += timedelta(days=delta)
                if d.weekday() < 5:
                    break
            self._date = d
        self.refresh()

    def _shift_week(self, delta):
        self._date = self._snap(self._date + timedelta(weeks=delta))
        self.refresh()

    def _shift_month(self, delta):
        y, m = self._date.year, self._date.month + delta
        while m > 12:
            m -= 12
            y += 1
        while m < 1:
            m += 12
            y -= 1
        day = min(self._date.day, calendar.monthrange(y, m)[1])
        self._date = self._snap(date(y, m, day))
        self.refresh()

    def _go_today(self):
        self._date = self._snap(date.today())
        self.refresh()

    def _jump_to(self, d):
        self._date = d
        self.refresh()

    def _reset_day(self):
        if Messagebox.yesno("Rebuild this day from the curriculum spine? "
                            "Your edits for this day will be discarded.",
                            title="Reset Day", parent=self) != "Yes":
            return
        self.db.delete_agenda_day(self._group, self._date.isoformat())
        self.refresh()

    # ─────────────────────────────────────────────────────────────── render ───

    def _render(self):
        try:
            top = self._canvas.yview()[0]
        except Exception:
            top = 0.0
        self._date_lbl.config(text=self._date.strftime("%A, %b %d, %Y"))
        self._saved_lbl.config(
            text="Saved ✓" if self._saved else "Auto-generated (unsaved)")
        self._ctx_lbl.config(text=self._curriculum_line())
        self._render_section_toggle()
        self._render_week_bar()
        self._img_refs = []
        for w in self._inner.winfo_children():
            w.destroy()
        self._render_banner(self._inner)
        for si, section in enumerate(self._day.get("sections", [])):
            self._render_section(self._inner, si, section)
        addbar = ttk.Frame(self._inner)
        addbar.pack(fill=X, pady=(2, 12))
        ttk.Button(addbar, text="➕ Add Section", bootstyle=(PRIMARY, OUTLINE),
                   command=self._add_section).pack(side=LEFT)
        self.after_idle(lambda: self._restore_scroll(self._canvas, top))

    @staticmethod
    def _restore_scroll(canvas, frac):
        try:
            canvas.yview_moveto(frac)
        except Exception:
            pass

    def _curriculum_line(self):
        concerts = self._concerts()
        cds = [c["date"] for c in concerts]
        level = spine.fundamentals_level(self._date, cds)
        # Warm-ups are blank by default now, so the old "Warm Up: Level" chip is
        # gone; the concert-cycle context below is what stays useful.
        parts = []
        # Concert-cycle chip for Entry/Intermediate only.  Advanced has a short
        # cycle with many events (Chinook Night, Veterans Day, winter, festival,
        # June concert), so the cycle index isn't meaningful — just the school day.
        if self._template in ("band_entry", "band_intermediate"):
            concert = spine._concert_for_level(level, concerts)
            if concert and concert.get("title"):
                cd = concert["date"]
                rel = "after" if self._date > cd else "rehearsing for"
                parts.append(f"{rel} {concert['title']} ({cd.strftime('%b %d')})")
            elif not cds and self._template == "band_entry":
                parts.append("level set by month — add concerts to anchor the cycle")
        cal = self._calendar()
        if cal:
            parts.append(f"school day {scal.school_day_index(cal, self._date)}")
        return "    ·    ".join(parts)

    def _render_week_bar(self):
        for w in self._week_bar.winfo_children():
            w.destroy()
        cal = self._calendar()
        monday = self._date - timedelta(days=self._date.weekday())
        for i, lbl in enumerate(WEEKDAYS):
            d = monday + timedelta(days=i)
            if cal and not scal.is_school_day(cal, d):
                _tk(tk.Label, self._week_bar, text=f"{lbl} {d.day}\nno school",
                    width=8, fg=muted_fg(),
                    font=("Segoe UI", fs(8))).pack(side=LEFT, padx=2)
                continue
            selected = (d == self._date)
            saved = self.db.get_agenda_day(self._group, d.isoformat()) is not None
            style = SUCCESS if selected else ((INFO, OUTLINE) if saved else (SECONDARY, OUTLINE))
            ttk.Button(self._week_bar, text=f"{lbl} {d.day}", bootstyle=style,
                       width=8, command=lambda dd=d: self._jump_to(dd)
                       ).pack(side=LEFT, padx=2)

    def _hdr_label(self, parent, text, size):
        return _tk(tk.Label, parent, text=text, bg=HDR_BG, fg=HDR_FG, anchor="w",
                   font=("Segoe UI", fs(size), "bold"), padx=8, pady=3)

    # ── banner: Reminders · Announcements · Percussion (grid, no clipping) ──

    def _render_banner(self, parent):
        # The third column (percussion / jazz rhythm) only exists for a class
        # that has one; choir/orchestra and other non-percussion classes get a
        # clean two-column banner with no percussion prompt at all.
        show_third = self._is_jazz or self._percussion
        row = ttk.Frame(parent)
        row.pack(fill=X, pady=(0, 8))
        row.columnconfigure(0, weight=1, uniform="ban")
        row.columnconfigure(1, weight=1, uniform="ban")
        if show_third:
            row.columnconfigure(2, weight=0, minsize=fs(24) * 12)
        self._banner_text(row, "Reminders", "reminders", 0)
        self._banner_text(row, "Announcements", "announcements", 1)
        if self._is_jazz:
            self._banner_rhythm(row, 2)
        elif self._percussion:
            self._banner_percussion(row, 2)

    def _banner_text(self, parent, title, key, col):
        wrap = ttk.Frame(parent)
        wrap.grid(row=0, column=col, sticky="nsew", padx=(0, 6))
        self._hdr_label(wrap, title, 11).pack(fill=X)
        txt = tk.Text(wrap, height=5, wrap="word", relief="solid", bd=1,
                      font=("Segoe UI", fs(10)))
        txt.pack(fill=BOTH, expand=True)
        txt.insert("1.0", "\n".join(self._day.get(key, [])))

        def commit(_e=None):
            lines = [ln.strip() for ln in txt.get("1.0", "end").splitlines()
                     if ln.strip()]
            if lines != self._day.get(key, []):
                self._day[key] = lines
                self._save_day()
        txt.bind("<FocusOut>", commit)

    def _banner_percussion(self, parent, col):
        wrap = ttk.Frame(parent)
        wrap.grid(row=0, column=col, sticky="nsew")
        self._hdr_label(wrap, "Percussion", 11).pack(fill=X)
        body = ttk.Frame(wrap, relief="solid", borderwidth=1, padding=4)
        body.pack(fill=BOTH, expand=True)

        groups = self._perc_groups()
        if not groups:
            ttk.Label(body, text=f"Add {self._cfg['label']} percussion on the 🥁 "
                               "Percussion tab; it will show here.",
                      wraplength=fs(24) * 11,
                      font=("Segoe UI", fs(8)), foreground=muted_fg(),
                      justify=LEFT).pack(anchor=W)
            return
        group = self._section_group() or groups[0]
        # Section name (the toolbar P1/P2 toggle switches this when there are 2+).
        ttk.Label(body, text=group["name"],
                  font=("Segoe UI", fs(9), "bold")).pack(anchor=W)
        asg, day, cycle = self._perc_assignments(group)
        ttk.Label(body, text=(f"Day {day} of {cycle}" if cycle else "No players"),
                  font=("Segoe UI", fs(8), "bold"),
                  foreground=muted_fg()).pack(anchor=W, pady=(2, 2))
        for name, station in asg:
            r = ttk.Frame(body)
            r.pack(fill=X)
            icon = _perc_icon(body, station)
            if icon is not None:
                self._img_refs.append(icon)
                _tk(tk.Label, r, image=icon).pack(side=LEFT)
            else:
                _tk(tk.Label, r, text=" ", background=_station_color(station),
                    relief="solid", bd=1, width=2).pack(side=LEFT)
            ttk.Label(r, text=name, font=("Segoe UI", fs(9), "bold"),
                      width=11, anchor=W).pack(side=LEFT, padx=(4, 2))
            ttk.Label(r, text=station,
                      font=("Segoe UI", fs(9))).pack(side=LEFT)

    def _banner_rhythm(self, parent, col):
        """Jazz counterpart to the percussion banner: the rhythm-section warm-up
        rotation for this school day (drum set / piano / bass / … → player)."""
        import jazz_icons
        wrap = ttk.Frame(parent)
        wrap.grid(row=0, column=col, sticky="nsew")
        self._hdr_label(wrap, "Rhythm Section", 11).pack(fill=X)
        body = ttk.Frame(wrap, relief="solid", borderwidth=1, padding=4)
        body.pack(fill=BOTH, expand=True)
        e = self._jazz_ensemble()
        if not e:
            ttk.Label(body, text="Create a jazz band on the 🎷 Jazz tab (set its "
                               "players and the parts each can cover); the warm-up "
                               "rotation shows here.",
                      wraplength=fs(24) * 11, font=("Segoe UI", fs(8)),
                      foreground=muted_fg(), justify=LEFT).pack(anchor=W)
            return
        asg, bench = self._jazz_rotation()
        if not asg:
            ttk.Label(body, text="Add seats & players on the 🎷 Jazz tab.",
                      font=("Segoe UI", fs(8)), foreground=muted_fg()).pack(anchor=W)
            return
        ttk.Label(body, text=f"Warm-up rotation · day {self._jazz_day()}",
                  font=("Segoe UI", fs(8), "bold"),
                  foreground=muted_fg()).pack(anchor=W, pady=(0, 2))
        for seat, names in asg:
            r = ttk.Frame(body)
            r.pack(fill=X, pady=1)
            ic = jazz_icons.icon(body, seat, px=fs(20))
            if ic is not None:                    # icon only — no instrument label
                self._img_refs.append(ic)
                _tk(tk.Label, r, image=ic).pack(side=LEFT)
            else:                                 # no icon for this seat: name it
                ttk.Label(r, text=seat, font=("Segoe UI", fs(9)),
                          width=12, anchor=W).pack(side=LEFT)
            ttk.Label(r, text=", ".join(names) if names else "—",
                      font=("Segoe UI", fs(9), "bold")).pack(side=LEFT, padx=(8, 0))
        if bench:
            ttk.Label(body, text="Out: " + ", ".join(bench),
                      font=("Segoe UI", fs(8)), foreground=muted_fg(),
                      wraplength=fs(24) * 11, justify=LEFT).pack(anchor=W, pady=(2, 0))

    def _jazz_song_picker(self, parent, section):
        """Under the jazz Sheet Music: pick a song set up on the Jazz tab and drop
        its LOCKED personnel in (Drum set: Murys, Piano: Emma, …) so she never
        re-enters an established tune's lineup."""
        e = self._jazz_ensemble()
        if not e:
            return
        songs = self.db.get_jazz_songs(e["id"])
        bar = ttk.Frame(parent)
        bar.pack(fill=X, pady=(4, 0))
        ttk.Label(bar, text="Insert song lineup:",
                  font=("Segoe UI", fs(8))).pack(side=LEFT)
        var = tk.StringVar()
        combo = ttk.Combobox(bar, textvariable=var, width=24, state="readonly",
                             values=[s["title"] for s in songs])
        combo.pack(side=LEFT, padx=(2, 6))

        def add():
            title = var.get().strip()
            song = next((s for s in songs if s["title"] == title), None)
            if not song:
                return
            locked = _safe_json(song["locked"], {})
            # The piece name is a normal (checkable) line; the assigned players
            # come in as FIXED text lines beneath it (no checkbox / no edit box).
            section.setdefault("items", []).append(spine._item(title))
            for seat, who in locked.items():
                names = who if isinstance(who, list) else ([who] if who else [])
                if names:
                    section["items"].append(
                        spine._item(f"{seat}: {', '.join(names)}", kind="static"))
            self._save_day()
            self._render()
        ttk.Button(bar, text="➕ Add", bootstyle=(SUCCESS, OUTLINE),
                   command=add).pack(side=LEFT)
        if not songs:
            ttk.Label(bar, text="(add songs on the 🎷 Jazz tab)",
                      font=("Segoe UI", fs(8)),
                      foreground=muted_fg()).pack(side=LEFT, padx=4)

    # ── a section ──

    def _render_section(self, parent, si, section):
        kind = section.get("kind", "")
        cont = ttk.Frame(parent)
        cont.pack(fill=X, pady=4)

        head = _tk(tk.Frame, cont, bg=HDR_BG)
        head.pack(fill=X)
        title_var = tk.StringVar(value=section.get("title", ""))
        ent = _tk(tk.Entry, head, textvariable=title_var, bg=HDR_BG, fg=HDR_FG,
                  insertbackground=HDR_FG,
                  font=("Segoe UI", fs(12), "bold"), relief="flat", bd=0)
        ent.pack(side=LEFT, fill=X, expand=True, padx=6, pady=2)

        def rename(_e=None):
            section["title"] = title_var.get().strip()
            self._save_day()
        ent.bind("<FocusOut>", rename)
        ent.bind("<Return>", rename)
        _tk(tk.Button, head, text="✕ Section", bg=HDR_BG, fg="#ffe0e0",
            relief="flat", bd=0, cursor="hand2", activebackground=HDR_BG,
            activeforeground="#ffffff", font=("Segoe UI", fs(8)),
            command=lambda: self._remove_section(si)).pack(side=RIGHT, padx=6)

        body = ttk.Frame(cont, padding=(6, 2))
        body.pack(fill=X)
        last_ref = None                         # assessment above a Missing line
        for item in section.get("items", []):
            if kind == "rhythms" and not item.get("image"):
                continue                       # Rhythms is images only
            if item.get("kind") == "assessment":
                last_ref = self._assess_ref(item.get("text", ""))
            self._render_item(body, section, item,
                              missing_ref=last_ref
                              if item.get("kind") == "missing" else None)

        if kind == "bandbook":
            self._bandbook_picker(body, section)
        if (kind == "warmup" and self._template == "band_advanced"
                and self._technique_enabled() and spine.tm_keys()):
            self._tm_picker(body, section)
        if self._is_jazz and kind == "sheet":
            self._jazz_song_picker(body, section)

        tools = ttk.Frame(body)
        tools.pack(fill=X, pady=(3, 0))
        if kind != "rhythms":
            ttk.Button(tools, text="＋ item", bootstyle=(SUCCESS, OUTLINE, LINK),
                       command=lambda: self._add_item(section)).pack(side=LEFT)
        ttk.Button(tools, text="📷 Paste Image", bootstyle=(INFO, OUTLINE, LINK),
                   command=lambda: self._paste_image(section)).pack(side=LEFT, padx=8)

    def _render_item(self, parent, section, item, missing_ref=None):
        if item.get("image"):
            self._render_image_item(parent, section, item)
            return
        kind = item.get("kind", "")
        if kind == "static":
            # Fixed, non-editable text (e.g. a song's locked rhythm-section
            # personnel dropped under the piece) — no checkbox, no entry, just an
            # indented label with a small ✕ to remove it.
            row = ttk.Frame(parent)
            row.pack(fill=X, pady=1)
            ttk.Label(row, text="", width=3).pack(side=LEFT)
            ttk.Label(row, text=item.get("text", ""), font=("Segoe UI", fs(10)),
                      anchor=W, justify=LEFT).pack(side=LEFT, fill=X, expand=True)
            ttk.Button(row, text="✕", width=2, bootstyle=(DANGER, OUTLINE, LINK),
                       command=lambda: self._remove_item(section, item)
                       ).pack(side=RIGHT)
            return
        color = item.get("color", "")
        fg, bg = _plan_colors(color, kind)
        row = ttk.Frame(parent)
        row.pack(fill=X, pady=1)
        iso = self._date.isoformat()
        # Pin this row to the section it is drawn under. A late FocusOut (fired
        # while the toggle is already flipping to the other period) then saves
        # to the section it was typed in, never the newly-selected one.
        msid = self._section_id() if kind == "missing" else None
        if kind == "missing":                   # per-section text (not shared)
            text_var = tk.StringVar(value=self._missing_text(iso, missing_ref, sid=msid))
        else:
            text_var = tk.StringVar(value=item.get("text", ""))

        if kind == "missing":
            ttk.Label(row, text="", width=3).pack(side=LEFT)
        else:
            done = tk.BooleanVar(value=self._is_done(iso, item))

            def toggle():
                self._set_done(iso, item.get("id", ""), done.get())
                self._save_day()          # persist item ids in the shared plan
            ttk.Checkbutton(row, variable=done, command=toggle).pack(side=LEFT)

        bold = "bold" if kind == "assessment" else "normal"
        te = _tk(tk.Entry, row, textvariable=text_var, bg=bg, fg=fg,
                 insertbackground=fg, relief="solid", bd=1,
                 font=("Segoe UI", fs(10), bold))
        te.pack(side=LEFT, fill=X, expand=True, padx=(4, 4))

        def commit(_e=None):
            if kind == "missing":               # save to the section overlay
                if text_var.get() != self._missing_text(iso, missing_ref, sid=msid):
                    self._set_missing_text(iso, missing_ref, text_var.get(), sid=msid)
            elif text_var.get() != item.get("text", ""):
                item["text"] = text_var.get()
                self._save_day()
        te.bind("<FocusOut>", commit)
        te.bind("<Return>", commit)
        self._color_menu(row, item).pack(side=LEFT, padx=(0, 2))
        ttk.Button(row, text="✕", width=2, bootstyle=(DANGER, OUTLINE, LINK),
                   command=lambda: self._remove_item(section, item)).pack(side=LEFT)

    def _render_image_item(self, parent, section, item):
        row = ttk.Frame(parent)
        row.pack(fill=X, pady=2, anchor=W)
        iso = self._date.isoformat()
        done = tk.BooleanVar(value=self._is_done(iso, item))

        def toggle():
            self._set_done(iso, item.get("id", ""), done.get())
            self._save_day()
        ttk.Checkbutton(row, variable=done,
                        command=toggle).pack(side=LEFT, anchor=N, pady=4)

        # Plan pane is narrower than the projector — show the image fit to the
        # pane so a full-width rhythm line isn't clipped while editing.  The
        # stored img_w is the PRESENT width; +/- tune that.
        w = int(item.get("img_w") or 380)
        pane = self._canvas.winfo_width()
        disp = w if pane <= 1 else max(140, min(w, pane - 150))
        img = self._thumb(item["image"], disp)
        if img is not None:
            self._img_refs.append(img)
            _tk(tk.Label, row, image=img, relief="solid", bd=1).pack(
                side=LEFT, padx=(4, 4))
        else:
            ttk.Label(row, text="[image not found]", foreground=muted_fg()
                      ).pack(side=LEFT, padx=4)

        zoom = ttk.Frame(row)
        zoom.pack(side=LEFT, anchor=N, pady=4)
        ttk.Button(zoom, text="－", width=2, bootstyle=(SECONDARY, OUTLINE),
                   command=lambda: self._zoom_image(item, -1)).pack(pady=1)
        ttk.Button(zoom, text="＋", width=2, bootstyle=(SECONDARY, OUTLINE),
                   command=lambda: self._zoom_image(item, 1)).pack(pady=1)
        ttk.Button(zoom, text="✕", width=2, bootstyle=(DANGER, OUTLINE),
                   command=lambda: self._remove_item(section, item)).pack(pady=(6, 1))

    def _zoom_image(self, item, direction):
        w = int(item.get("img_w") or 380)
        w = max(140, min(1800, w + direction * 150))
        item["img_w"] = w
        self._save_day()
        self._render()

    def _color_menu(self, parent, item):
        mb = tk.Menubutton(parent, text="🎨", relief="flat", cursor="hand2",
                           font=("Segoe UI", fs(9)))
        menu = tk.Menu(mb, tearoff=0)
        for label, val in ITEM_COLORS:
            menu.add_command(label=label,
                             command=lambda v=val: self._set_item_color(item, v))
        mb.config(menu=menu)
        return mb

    def _set_item_color(self, item, val):
        item["color"] = val
        self._save_day()
        self._render()

    def _bandbook_picker(self, parent, section):
        bar = ttk.Frame(parent)
        bar.pack(fill=X, pady=(4, 0))
        ttk.Label(bar, text="Add line — Page:",
                  font=("Segoe UI", fs(8))).pack(side=LEFT)
        pages = [str(p) for p in spine.soe_pages(self._book)]
        page_var = tk.StringVar()
        line_var = tk.StringVar()
        page_combo = ttk.Combobox(bar, textvariable=page_var, width=5,
                                  state="readonly", values=pages)
        page_combo.pack(side=LEFT, padx=(2, 6))
        line_combo = ttk.Combobox(bar, textvariable=line_var, width=32,
                                  state="readonly", values=[])
        line_combo.pack(side=LEFT)

        def on_page(_e=None):
            try:
                lines = spine.soe_lines_on_page(int(page_var.get()), self._book)
            except (ValueError, TypeError):
                lines = []
            labels = [f"#{r['n']} {r['title']}" for r in lines]
            line_combo.config(values=labels)
            line_var.set(labels[0] if labels else "")
        page_combo.bind("<<ComboboxSelected>>", on_page)

        def add():
            label = line_var.get().strip()
            if not label:
                return
            try:
                n = int(label.split()[0].lstrip("#"))
            except (ValueError, IndexError):
                return
            rec = spine.soe_line(n, self._book)
            kind = "assessment" if rec and rec.get("assessment") else ""
            section.setdefault("items", []).append(
                spine._item(spine.soe_label(n, self._book), kind=kind))
            self._save_day()
            self._render()
        ttk.Button(bar, text="➕ Add", bootstyle=(SUCCESS, OUTLINE),
                   command=add).pack(side=LEFT, padx=6)

    def _tm_picker(self, parent, section):
        """Advanced Warm Up: pick a concert key from Technique & Musicianship and
        add one of its 10 lines (or the whole key).  The Warm Up section still
        DEFAULTS blank — this is purely an optional add-tool.  (Partial data for
        now; grows as more keys are entered in technique_musicianship_lines.json.)"""
        bar = ttk.Frame(parent)
        bar.pack(fill=X, pady=(4, 0))
        ttk.Label(bar, text="Technique & Musicianship — Key:",
                  font=("Segoe UI", fs(8))).pack(side=LEFT)
        keys = spine.tm_keys()
        key_var = tk.StringVar()
        line_var = tk.StringVar()
        key_combo = ttk.Combobox(bar, textvariable=key_var, width=12,
                                 state="readonly", values=keys)
        key_combo.pack(side=LEFT, padx=(2, 6))
        line_combo = ttk.Combobox(bar, textvariable=line_var, width=34,
                                  state="readonly", values=[])
        line_combo.pack(side=LEFT)

        def on_key(_e=None):
            lines = spine.tm_lines_for_key(key_var.get())
            labels = [f"#{r['n']} {r['title']}" for r in lines]
            line_combo.config(values=labels)
            line_var.set(labels[0] if labels else "")
        key_combo.bind("<<ComboboxSelected>>", on_key)

        def add_one():
            label = line_var.get().strip()
            if not label:
                return
            section.setdefault("items", []).append(spine._item(label))
            self._save_day()
            self._render()
        ttk.Button(bar, text="➕ Add", bootstyle=(SUCCESS, OUTLINE),
                   command=add_one).pack(side=LEFT, padx=6)

        def add_key():
            key = key_var.get()
            lines = spine.tm_lines_for_key(key)
            if not lines:
                return
            for r in lines:
                section.setdefault("items", []).append(
                    spine._item(f"#{r['n']} {r['title']}"))
            self._save_day()
            self._render()
        ttk.Button(bar, text="➕ Add whole key", bootstyle=(INFO, OUTLINE, LINK),
                   command=add_key).pack(side=LEFT, padx=2)

    # ── images (stored in the day as base64 so they ride DB backups) ──

    def _thumb(self, val, target_w):
        import io
        import base64
        try:
            from PIL import Image, ImageTk
            if isinstance(val, str) and val.startswith("b64:"):
                im = Image.open(io.BytesIO(base64.b64decode(val[4:])))
            else:
                im = Image.open(self._image_abspath(val))
            h = max(1, int(im.height * target_w / im.width))
            im = im.resize((target_w, h), Image.LANCZOS)
            return ImageTk.PhotoImage(im, master=self)
        except Exception:
            return None

    def _paste_image(self, section):
        try:
            from PIL import ImageGrab, Image
            obj = ImageGrab.grabclipboard()
        except Exception:
            obj = None
            Image = None
        im = None
        if Image is not None:
            if isinstance(obj, Image.Image):
                im = obj
            elif isinstance(obj, list):
                for f in obj:
                    try:
                        im = Image.open(f)
                        break
                    except Exception:
                        pass
        if im is None:
            Messagebox.show_info(
                "Copy an image first (e.g. a rhythm screenshot), then click "
                "“Paste Image”.", title="No image on the clipboard", parent=self)
            return
        item = spine._item("")
        item["image"] = self._encode_image(im)
        # Rhythm lines are wide/thin — start near full width so it's usable on
        # the projector without clicking + a dozen times.
        item["img_w"] = min(im.width, 1500)
        section.setdefault("items", []).append(item)
        self._save_day()
        self._render()

    def _encode_image(self, im):
        import io
        import base64
        from PIL import Image
        if im.width > 1800:                    # keep enough res for full-width
            h = int(im.height * 1800 / im.width)
            im = im.resize((1800, h), Image.LANCZOS)
        buf = io.BytesIO()
        im.convert("RGB").save(buf, "PNG")
        return "b64:" + base64.b64encode(buf.getvalue()).decode("ascii")

    # ── section / item mutations ──

    def _add_section(self):
        self._day.setdefault("sections", []).append(
            {"title": "New section", "kind": "", "items": [spine._item("")]})
        self._save_day()
        self._render()

    def _remove_section(self, si):
        try:
            self._day["sections"].pop(si)
        except (IndexError, KeyError):
            return
        self._save_day()
        self._render()

    def _add_item(self, section):
        section.setdefault("items", []).append(spine._item(""))
        self._save_day()
        self._render()

    def _remove_item(self, section, item):
        try:
            section["items"].remove(item)
        except ValueError:
            return
        self._save_day()
        self._render()

    # ─────────────────────────────────────────────────────── percussion data ──

    def _perc_groups(self):
        """This ensemble's percussion sections.  Entry filters on the ENTRY
        class type; Intermediate & Advanced share the INT_ADV type, so those are
        split by the group keyword in the section NAME ("int" vs "adv").  For
        Intermediate we also tolerate un-"int"-named sections (any INT_ADV group
        that isn't an Advanced one); Advanced requires an explicit "adv" name so
        it never grabs the Intermediate sections."""
        ct = self._cfg["class_type"]
        # No percussion for this class (jazz, choir/orchestra, a non-perc club).
        if ct is None or not self._percussion:
            return []
        groups = [g for g in self.db.get_percussion_groups(self._year())
                  if g["class_type"] == ct]
        if self._template == "band_entry":
            return groups
        kw = self._cfg["ensemble"]
        named = [g for g in groups if kw in (g["name"] or "").lower()]
        if named:
            return named
        if self._template == "band_intermediate":
            return [g for g in groups if "adv" not in (g["name"] or "").lower()]
        return named            # Advanced: only explicitly "adv"-named sections

    # ── P1/P2 (or P6/P7) section: a section IS its percussion group.  The toolbar
    #    toggle picks which section's rotation + Missing lists to show; the
    #    lesson plan itself is SHARED across sections (planned once). ──

    def _section_setting_key(self):
        return f"agenda_{self._group}_section"

    def _section_group(self):
        """The active section (a percussion group) from the toolbar toggle;
        falls back to the first section (and, for Entry, the legacy setting)."""
        groups = self._perc_groups()
        if not groups:
            return None
        want = self.db.get_program_setting(self._section_setting_key())
        if not want and self._template == "band_entry":
            want = self.db.get_program_setting("agenda_entry_perc")  # legacy
        for g in groups:
            if str(g["id"]) == str(want):
                return g
        return groups[0]

    def _apply_section(self, group_id):
        self.db.set_program_setting(self._section_setting_key(), str(group_id))
        if self._template == "band_entry":
            self.db.set_program_setting("agenda_entry_perc", str(group_id))  # legacy

    def _set_section(self, group_id):
        self._flush_focus()      # commit any in-progress edit to the OLD section
        self._apply_section(group_id)
        self.refresh()

    def _flush_focus(self):
        # Force the focused entry to fire its <FocusOut> commit before we switch
        # sections, so a half-typed Missing line is saved under the right period.
        try:
            w = self.focus_get()
            if isinstance(w, tk.Entry):
                w.event_generate("<FocusOut>")
        except Exception:
            pass

    def _section_id(self):
        g = self._section_group()
        return g["id"] if g else None

    # Banner + present call this; a section == its percussion group.
    def _linked_perc_group(self):
        return self._section_group()

    def _render_section_toggle(self):
        """Populate the toolbar section toggle (only when 2+ sections)."""
        for w in self._section_bar.winfo_children():
            w.destroy()
        groups = self._perc_groups()
        if len(groups) < 2:
            return                       # one section (or none) — nothing to toggle
        ttk.Label(self._section_bar, text="Section:",
                  font=("Segoe UI", fs(9))).pack(side=LEFT, padx=(14, 4))
        active = self._section_group()
        self._section_var = tk.StringVar(
            value=str(active["id"]) if active else "")
        for g in groups:
            ttk.Radiobutton(self._section_bar, text=g["name"],
                            value=str(g["id"]), variable=self._section_var,
                            bootstyle=(INFO, "toolbutton"),
                            command=lambda gid=g["id"]: self._set_section(gid)
                            ).pack(side=LEFT, padx=1)

    # ── per-section "Missing" name lists ─────────────────────────────────────
    # Typed by hand (no per-student pass tracking yet) but stored SEPARATELY per
    # section, keyed by (section, date, assessment) — so P1 and P2 keep their own
    # missing lists and swap with the toggle.  NOT stored in the shared agenda.

    @staticmethod
    def _assess_ref(text):
        """Stable per-day key for a missing line: the assessment label above it
        without its '(due …)' suffix (e.g. '#88 Concert Bb Major Scale')."""
        import re
        return re.split(r"\s*\(due\b", (text or ""), 1)[0].strip()

    def _missing_setting_key(self, sid=None):
        if sid is None:
            sid = self._section_id()
        return f"agenda_missing_{sid}" if sid is not None else "agenda_missing_none"

    def _load_missing_map(self, sid=None):
        raw = self.db.get_program_setting(self._missing_setting_key(sid))
        if not raw:
            return {}
        try:
            m = json.loads(raw)
            return m if isinstance(m, dict) else {}
        except Exception:
            return {}

    # ``sid`` pins the read/write to a specific section so a late FocusOut save
    # (after the toggle already flipped) still lands in the section it was typed
    # under — never bleeding P1's names into P2.
    def _missing_text(self, iso, ref, default="Missing: ", sid=None):
        return (self._load_missing_map(sid).get(iso) or {}).get(ref or "", default)

    def _set_missing_text(self, iso, ref, text, sid=None):
        m = self._load_missing_map(sid)
        m.setdefault(iso, {})[ref or ""] = text
        self.db.set_program_setting(self._missing_setting_key(sid), json.dumps(m))

    # ── per-section checkbox ("done") state ──────────────────────────────────
    # Which lines each section actually got through — saved SEPARATELY per
    # section (keyed by item id + date) so P1 and P2 don't share checkmarks.
    # Lets her review at end of day what each class covered.

    def _done_setting_key(self):
        sid = self._section_id()
        return f"agenda_done_{sid}" if sid is not None else "agenda_done_none"

    def _load_done_map(self):
        raw = self.db.get_program_setting(self._done_setting_key())
        if not raw:
            return {}
        try:
            m = json.loads(raw)
            return m if isinstance(m, dict) else {}
        except Exception:
            return {}

    def _is_done(self, iso, item):
        iid = item.get("id")
        return bool(iid and (self._load_done_map().get(iso) or {}).get(iid))

    def _set_done(self, iso, item_id, val):
        if not item_id:
            return
        m = self._load_done_map()
        day = m.setdefault(iso, {})
        if val:
            day[item_id] = True
        else:
            day.pop(item_id, None)
            if not day:
                m.pop(iso, None)
        self.db.set_program_setting(self._done_setting_key(), json.dumps(m))

    def _perc_payload(self, group):
        out = []
        is_entry = group["class_type"] == pr.ENTRY
        for r in self.db.get_percussion_students(group["id"]):
            allowed = None
            try:
                raw = r["allowed_stations"]
                if raw:
                    v = json.loads(raw)
                    allowed = v if isinstance(v, list) and v else None
            except Exception:
                allowed = None
            out.append({"name": r["name"],
                        "mallets_only": is_entry and not r["full_rotation"],
                        "allowed_stations": allowed})
        return out

    def _perc_inventory(self):
        raw = self.db.get_program_setting("mallet_inventory")
        if raw:
            try:
                return pr._norm_inventory(json.loads(raw))
            except Exception:
                pass
        return None

    def _rotation_day(self, payload):
        cal = self._calendar()
        if cal:
            idx = scal.school_day_index(cal, self._date)
        else:
            start, _end = self._year_bounds()
            idx = spine._school_days_between(start, self._date)
        cycle = pr.cycle_length(payload, inventory=self._perc_inventory())
        if cycle <= 0:
            return 1, 1
        return ((idx - 1) % cycle) + 1, cycle

    def _perc_assignments(self, group):
        payload = self._perc_payload(group)
        if not payload:
            return [], 0, 0
        day, cycle = self._rotation_day(payload)
        asg = pr.day_assignments(payload, day, group["class_type"],
                                 inventory=self._perc_inventory())
        return asg, day, cycle

    # ────────────────────────────────────────────────────────────── present ───

    def _open_present(self):
        if self._present is not None and self._present.winfo_exists():
            self._present.lift()
            return
        self._present = _PresentWindow(self.winfo_toplevel(), self)
        self._present.protocol("WM_DELETE_WINDOW", self._close_present)

    def _close_present(self):
        if self._present is not None:
            self._present.destroy()
        self._present = None
        self._load_day()
        self._render()


# ══════════════════════════════════════════════════════════════ present ══════

class _PresentWindow(ttk.Toplevel):
    """Full-screen projection.

    Layout (matches her sketch):
        ┌ header: clock · date · timer · ✕ ─────────────────────────┐
        ├ banner: Reminders   Announcements ─────────────────────────┤
        │ Warm Up / Band book / Sheet Music …      ╔═ Percussion ═╗  │
        │ (scrolls if needed, fills the screen)    ║ floating,     ║  │
        │                                          ║ collapsible   ║  │
        └──────────────────────────────────────────╚═══════════════╝──┘
    The percussion panel FLOATS over the top-right (place()), so the agenda
    below uses the full width; collapse it once players are set.
    """

    def __init__(self, parent, view):
        super().__init__(parent)
        self.view = view
        self.title("Agenda — Present")
        self._img_refs = []
        self._timer_started = False
        self._timer_running = False
        self._timer_end = 0.0
        self._timer_remaining = 0
        self._perc_collapsed = False
        self._perc_widget = None
        if getattr(view, "_fullscreen", True):
            try:
                self.attributes("-fullscreen", True)
            except Exception:
                self.geometry("1200x780")
        else:
            self.geometry("1200x780")
        self.bind("<Escape>", lambda e: self.view._close_present())

        self._header()
        self._stage = _tk(tk.Frame, self, bg="#ffffff")
        self._stage.pack(fill=BOTH, expand=True)
        # Banner (reminders / announcements) — fixed, short, stays on scroll.
        self._banner_host = _tk(tk.Frame, self._stage, bg="#ffffff")
        self._banner_host.pack(fill=X)
        wrap = ttk.Frame(self._stage)
        wrap.pack(fill=BOTH, expand=True)
        self._canvas = tk.Canvas(wrap, highlightthickness=0)
        vsb = ttk.Scrollbar(wrap, orient=VERTICAL, command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side=RIGHT, fill=Y)
        self._canvas.pack(side=LEFT, fill=BOTH, expand=True)
        self._body = _tk(tk.Frame, self._canvas, bg="#ffffff")
        self._bwin = self._canvas.create_window((0, 0), window=self._body, anchor="nw")
        self._body.bind("<Configure>",
                        lambda e: self._canvas.configure(scrollregion=self._canvas.bbox("all")))
        self._canvas.bind("<Configure>",
                          lambda e: self._canvas.itemconfig(self._bwin, width=e.width))
        self._canvas.bind_all("<MouseWheel>",
                              lambda e: self._canvas.yview_scroll(int(-e.delta / 120), "units"))

        self.rebuild()
        self._tick()

    def _header(self):
        hdr = ttk.Frame(self, bootstyle=DARK)
        hdr.pack(fill=X)
        self._clock = ttk.Label(hdr, text="", font=("Segoe UI", fs(26), "bold"),
                                bootstyle=(INVERSE, DARK))
        self._clock.pack(side=LEFT, padx=(18, 10), pady=6)
        self._title = ttk.Label(hdr, text="", font=("Segoe UI", fs(14), "bold"),
                                 bootstyle=(INVERSE, DARK))
        self._title.pack(side=LEFT, padx=6)
        self._present_section_toggle(hdr)     # P1/P2 switch, right in present
        # Countdown sits right next to the clock/date, not off in the corner.
        self._timer_lbl = ttk.Label(hdr, text="", font=("Segoe UI", fs(26), "bold"),
                                     bootstyle=(INVERSE, DARK))
        self._timer_lbl.pack(side=LEFT, padx=(40, 10), pady=6)

        _tk(tk.Button, hdr, text="✕", bg="#c0392b", fg="#ffffff", bd=0,
            activebackground="#e74c3c", activeforeground="#ffffff",
            cursor="hand2", font=("Segoe UI", fs(14), "bold"),
            command=self.view._close_present).pack(side=RIGHT, padx=(6, 14),
                                                   pady=6, ipadx=6)
        self._pause_btn = ttk.Button(hdr, text="⏸ Pause", bootstyle=WARNING,
                                     command=self._toggle_pause, width=9)
        self._pause_btn.pack(side=RIGHT, padx=2, pady=6)
        ttk.Button(hdr, text="▶ Start", bootstyle=WARNING, width=7,
                   command=self._start_selected).pack(side=RIGHT, padx=2, pady=6)
        self._preset_var = tk.StringVar(value="5 min")
        ttk.Combobox(hdr, textvariable=self._preset_var, state="readonly",
                     width=7, values=[l for l, _ in TIMER_PRESETS]).pack(
            side=RIGHT, padx=2, pady=6)
        ttk.Label(hdr, text="Timer:", font=("Segoe UI", fs(10)),
                  bootstyle=(INVERSE, DARK)).pack(side=RIGHT, padx=(0, 2))

    def _present_section_toggle(self, hdr):
        """P1/P2 toggle in the present header — switch section without leaving
        the projection (the two periods run back-to-back)."""
        groups = self.view._perc_groups()
        if len(groups) < 2:
            return
        active = self.view._section_group()
        self._sect_var = tk.StringVar(value=str(active["id"]) if active else "")
        box = ttk.Frame(hdr)
        box.pack(side=LEFT, padx=(24, 6))
        for g in groups:
            ttk.Radiobutton(box, text=g["name"], value=str(g["id"]),
                            variable=self._sect_var, bootstyle=(INFO, "toolbutton"),
                            command=lambda gid=g["id"]: self._switch_section(gid)
                            ).pack(side=LEFT, padx=1)

    def _switch_section(self, gid):
        self.view._apply_section(gid)
        self.view._render()                 # keep the plan view in sync underneath
        self.rebuild()                      # re-project with this section's data

    # ── clock / timer (both shown at once) ──

    def _tick(self):
        if not self.winfo_exists():
            return
        self._clock.config(text=time.strftime("%I:%M:%S %p").lstrip("0"))
        if self._timer_started:
            if self._timer_running:
                remaining = max(0, int(round(self._timer_end - time.time())))
                if remaining <= 0:
                    self._timer_running = False
            else:
                remaining = self._timer_remaining
            m, s = divmod(remaining, 60)
            danger = remaining <= 10
            self._timer_lbl.config(
                text=f"⏱ {m:d}:{s:02d}",
                bootstyle=(INVERSE, DANGER if danger else DARK))
        self.after(250, self._tick)

    def _start_selected(self):
        secs = dict(TIMER_PRESETS).get(self._preset_var.get(), 300)
        self._timer_started = True
        self._timer_running = True
        self._timer_end = time.time() + secs
        self._pause_btn.config(text="⏸ Pause")

    def _toggle_pause(self):
        if not self._timer_started:
            return
        if self._timer_running:
            self._timer_remaining = max(0, int(round(self._timer_end - time.time())))
            self._timer_running = False
            self._pause_btn.config(text="▶ Resume")
        else:
            self._timer_end = time.time() + self._timer_remaining
            self._timer_running = True
            self._pause_btn.config(text="⏸ Pause")

    # ── content ──

    def _hdr(self, parent, text):
        return _tk(tk.Label, parent, text=text, bg=HDR_BG, fg=HDR_FG, anchor="w",
                   font=("Segoe UI", fs(15), "bold"), padx=10, pady=3)

    def rebuild(self):
        try:
            top = self._canvas.yview()[0]
        except Exception:
            top = 0.0
        day = self.view._day
        bg = self.view._present_bg()
        self._img_refs = []
        self._canvas.config(bg=bg)
        self._stage.configure(bg=bg)
        self._body.configure(bg=bg)
        self._banner_host.configure(bg=bg)
        self._title.config(text=self.view._display_label() + "  ·  " +
                           self.view._date.strftime("%A, %b %d"))
        for w in self._banner_host.winfo_children():
            w.destroy()
        for w in self._body.winfo_children():
            w.destroy()
        if self._perc_widget is not None:
            try:
                self._perc_widget.destroy()
            except Exception:
                pass
            self._perc_widget = None

        banner = _tk(tk.Frame, self._banner_host, bg=bg)
        banner.pack(fill=X, padx=20, pady=(8, 6))
        self._present_banner_text(banner, "Reminders", day.get("reminders", []), bg)
        self._present_banner_text(banner, "Announcements",
                                  day.get("announcements", []), bg)

        for section in day.get("sections", []):
            self._present_section(section, bg)

        self._build_perc_panel(bg)
        self.after_idle(lambda: AgendasView._restore_scroll(self._canvas, top))

    def _present_banner_text(self, parent, title, lines, bg):
        if not lines:
            return                              # hide an empty banner column
        col = _tk(tk.Frame, parent, bg=bg)
        col.pack(side=LEFT, fill=Y, padx=(0, 40), anchor=N)
        self._hdr(col, title).pack(fill=X)
        for ln in lines:
            _tk(tk.Label, col, text="•  " + ln, bg=bg, fg=_auto_fg(bg),
                font=("Segoe UI", fs(14)), wraplength=460,
                justify=LEFT, anchor=W).pack(fill=X)

    # ── floating, collapsible percussion panel ──

    def _toggle_perc(self):
        self._perc_collapsed = not self._perc_collapsed
        self.rebuild()

    def _build_perc_panel(self, bg):
        if self.view._is_jazz:
            self._build_rhythm_panel(bg)
            return
        group = self.view._linked_perc_group()
        asg, dnum, cyc = ([], 0, 0)
        if group:
            asg, dnum, cyc = self.view._perc_assignments(group)
        if not asg:
            return                              # nothing to show

        if self._perc_collapsed:
            btn = _tk(tk.Button, self._stage, text="🥁 Percussion  ▾",
                      bg=HDR_BG, fg=HDR_FG, activebackground=HDR_BG,
                      activeforeground=HDR_FG, bd=0, cursor="hand2",
                      relief="flat", padx=10, pady=4,
                      font=("Segoe UI", fs(12), "bold"), command=self._toggle_perc)
            btn.place(relx=1.0, y=8, anchor="ne", x=-10)
            self._perc_widget = btn
            return

        panel = _tk(tk.Frame, self._stage, bg=bg,
                    highlightbackground="#8aa0b8", highlightthickness=2)
        head = _tk(tk.Frame, panel, bg=HDR_BG)
        head.pack(fill=X)
        _tk(tk.Label, head, text=f"🥁 Percussion — day {dnum} of {cyc}",
            bg=HDR_BG, fg=HDR_FG, anchor="w", padx=8, pady=3,
            font=("Segoe UI", fs(13), "bold")).pack(side=LEFT, fill=X, expand=True)
        _tk(tk.Button, head, text="▸ hide", bg=HDR_BG, fg=HDR_FG,
            activebackground=HDR_BG, activeforeground=HDR_FG, bd=0, cursor="hand2",
            relief="flat", padx=6, font=("Segoe UI", fs(10), "bold"),
            command=self._toggle_perc).pack(side=RIGHT, padx=2)
        table = _tk(tk.Frame, panel, bg=bg)
        table.pack(fill=BOTH, padx=8, pady=(4, 6))
        for name, station in asg:
            r = _tk(tk.Frame, table, bg=bg)
            r.pack(fill=X, pady=1)
            icon = _perc_icon(table, station)
            if icon is not None:
                self._img_refs.append(icon)
                _tk(tk.Label, r, image=icon, bg=bg).pack(side=LEFT)
            else:
                _tk(tk.Label, r, text="  ", background=_station_color(station),
                    relief="solid", bd=1).pack(side=LEFT)
            _tk(tk.Label, r, text=name, bg=bg, fg=_auto_fg(bg), width=10,
                anchor="w", font=("Segoe UI", fs(12), "bold")).pack(side=LEFT, padx=6)
            _tk(tk.Label, r, text=station, bg=bg, fg=_auto_fg(bg),
                font=("Segoe UI", fs(12))).pack(side=LEFT)
        panel.place(relx=1.0, y=8, anchor="ne", x=-10)
        self._perc_widget = panel

    def _build_rhythm_panel(self, bg):
        """Present-mode floating panel for the jazz rhythm-section rotation."""
        import jazz_icons
        asg, bench = self.view._jazz_rotation()
        if not asg:
            return
        dnum = self.view._jazz_day()
        if self._perc_collapsed:
            btn = _tk(tk.Button, self._stage, text="🎷 Rhythm  ▾",
                      bg=HDR_BG, fg=HDR_FG, activebackground=HDR_BG,
                      activeforeground=HDR_FG, bd=0, cursor="hand2",
                      relief="flat", padx=10, pady=4,
                      font=("Segoe UI", fs(12), "bold"), command=self._toggle_perc)
            btn.place(relx=1.0, y=8, anchor="ne", x=-10)
            self._perc_widget = btn
            return
        panel = _tk(tk.Frame, self._stage, bg=bg,
                    highlightbackground="#8aa0b8", highlightthickness=2)
        head = _tk(tk.Frame, panel, bg=HDR_BG)
        head.pack(fill=X)
        _tk(tk.Label, head, text=f"🎷 Rhythm — warm-up day {dnum}",
            bg=HDR_BG, fg=HDR_FG, anchor="w", padx=8, pady=3,
            font=("Segoe UI", fs(13), "bold")).pack(side=LEFT, fill=X, expand=True)
        _tk(tk.Button, head, text="▸ hide", bg=HDR_BG, fg=HDR_FG,
            activebackground=HDR_BG, activeforeground=HDR_FG, bd=0, cursor="hand2",
            relief="flat", padx=6, font=("Segoe UI", fs(10), "bold"),
            command=self._toggle_perc).pack(side=RIGHT, padx=2)
        table = _tk(tk.Frame, panel, bg=bg)
        table.pack(fill=BOTH, padx=8, pady=(4, 6))
        for seat, names in asg:
            r = _tk(tk.Frame, table, bg=bg)
            r.pack(fill=X, pady=1)
            ic = jazz_icons.icon(table, seat, px=fs(24))
            if ic is not None:                    # icon only — no instrument label
                self._img_refs.append(ic)
                _tk(tk.Label, r, image=ic, bg=bg).pack(side=LEFT)
            else:
                _tk(tk.Label, r, text=seat, bg=bg, fg=_auto_fg(bg), width=12,
                    anchor="w", font=("Segoe UI", fs(12), "bold")).pack(side=LEFT)
            _tk(tk.Label, r, text=", ".join(names) if names else "—", bg=bg,
                fg=_auto_fg(bg), font=("Segoe UI", fs(12))).pack(side=LEFT, padx=(8, 0))
        panel.place(relx=1.0, y=8, anchor="ne", x=-10)
        self._perc_widget = panel

    # ── sections ──

    def _big_check(self, parent, item, bg):
        """A large, tap-anywhere check box (☐ / ☑) — legible from the room.
        Per-section (saved to the active section's own 'done' store)."""
        iso = self.view._date.isoformat()
        lbl = _tk(tk.Label, parent,
                  text="☑" if self.view._is_done(iso, item) else "☐",
                  bg=bg, fg=_auto_fg(bg), cursor="hand2",
                  font=("Segoe UI", fs(24)))

        def click(_e=None):
            val = not self.view._is_done(iso, item)
            self.view._set_done(iso, item.get("id", ""), val)
            lbl.config(text="☑" if val else "☐")
            self.view._save_day(rebuild_present=False)   # persist item ids
        lbl.bind("<Button-1>", click)
        return lbl

    def _present_section(self, section, bg):
        iso = self.view._date.isoformat()
        last_ref = None
        rows = []                               # (item, per-section missing text)
        for it in section.get("items", []):
            if it.get("kind") == "assessment":
                last_ref = self.view._assess_ref(it.get("text", ""))
            mtext = None
            if it.get("kind") == "missing":
                mtext = self.view._missing_text(iso, last_ref, default="")
                if mtext.strip().rstrip(":") in ("", "Missing"):
                    continue                    # nobody missing -> hide the line
            elif not (it.get("image") or (it.get("text") or "").strip()):
                continue
            rows.append((it, mtext))
        if not rows:
            return                              # hide empty sections in present
        col = _tk(tk.Frame, self._body, bg=bg)
        col.pack(fill=X, padx=20, pady=(3, 1))
        self._hdr(col, section.get("title", "")).pack(fill=X, anchor=W)
        for item, mtext in rows:
            if item.get("image"):
                self._present_image(col, item, bg)
                continue
            self._present_line(col, item, bg, missing_text=mtext)

    def _present_image(self, parent, item, bg):
        row = _tk(tk.Frame, parent, bg=bg)
        row.pack(fill=X, pady=2, anchor=W)
        self._big_check(row, item, bg).pack(side=LEFT, anchor=N)
        w = int(item.get("img_w") or 380)
        img = self.view._thumb(item["image"], min(1800, max(200, w)))
        if img is not None:
            self._img_refs.append(img)
            _tk(tk.Label, row, image=img, bg=bg).pack(side=LEFT, padx=6)

    def _present_line(self, parent, item, bg, missing_text=None):
        kind = item.get("kind", "")
        color = item.get("color", "")
        fg, lbg = _present_colors(color, kind, bg)
        row = _tk(tk.Frame, parent, bg=bg)
        row.pack(fill=X, pady=1, anchor=W)
        if kind in ("missing", "static"):
            # Fixed text, no check box (missing names, or a song's locked
            # personnel dropped under the piece), indented under the checkboxes.
            _tk(tk.Label, row, text="", bg=bg, width=3).pack(side=LEFT)
            _tk(tk.Label, row, text=missing_text or item.get("text", ""), bg=bg,
                fg=_auto_fg(bg), font=("Segoe UI", fs(14)), wraplength=1100,
                justify=LEFT).pack(side=LEFT)
            return
        self._big_check(row, item, bg).pack(side=LEFT, padx=(0, 2))
        weight = "bold" if kind == "assessment" else "normal"
        _tk(tk.Label, row, text=item["text"], bg=lbg, fg=fg,
            font=("Segoe UI", fs(16), weight), wraplength=1050,
            justify=LEFT, padx=(6 if lbg != bg else 0)).pack(side=LEFT, padx=8)


# ══════════════════════════════════════════════════ assessments editor ══════

class _AssessmentsDialog(ttk.Toplevel):
    """Teacher-defined assessments: which lines are tested and each due date.
    Every teacher's set (and count) differs, so this is fully editable; the due
    dates are for the current school year and are set fresh each year."""

    def __init__(self, view, items):
        super().__init__(view.winfo_toplevel())
        self.view = view
        self.title(f"Assessments — {view._cfg['label']}")
        self.geometry("600x640")
        self._rows = []                       # [(frame, ref_var, due_var), ...]

        ttk.Label(self, text="Your assessments and their due dates. Each line "
                  "appears on the agenda about 2 weeks before it's due. Dates "
                  "are for THIS school year — set them fresh each year. Leave the "
                  "date blank to keep an assessment on your list without putting "
                  "it on the agenda.",
                  wraplength=560, bootstyle=SECONDARY, justify=LEFT
                  ).pack(fill=X, padx=14, pady=(14, 8))

        cols = ttk.Frame(self)
        cols.pack(fill=X, padx=14)
        ttk.Label(cols, text="Book line / ref", width=34,
                  font=("Segoe UI", fs(9), "bold")).pack(side=LEFT)
        ttk.Label(cols, text="Due date (YYYY-MM-DD)",
                  font=("Segoe UI", fs(9), "bold")).pack(side=LEFT)

        box = ttk.Frame(self)
        box.pack(fill=BOTH, expand=True, padx=14, pady=(2, 6))
        canvas = tk.Canvas(box, highlightthickness=0)
        sb = ttk.Scrollbar(box, orient=VERTICAL, command=canvas.yview)
        canvas.configure(yscrollcommand=sb.set)
        sb.pack(side=RIGHT, fill=Y)
        canvas.pack(side=LEFT, fill=BOTH, expand=True)
        self._list = ttk.Frame(canvas)
        win = canvas.create_window((0, 0), window=self._list, anchor="nw")
        self._list.bind("<Configure>",
                        lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(win, width=e.width))

        for it in items:
            due = it.get("due")
            self._add_row(it.get("ref", ""), due.isoformat() if due else "")

        addbar = ttk.Frame(self)
        addbar.pack(fill=X, padx=14, pady=(0, 4))
        ttk.Button(addbar, text="＋ Add row", bootstyle=(SUCCESS, OUTLINE),
                   command=lambda: self._add_row("", "")).pack(side=LEFT)
        # "Add from book page" only for ensembles with a Standard of Excellence
        # book (Entry/Intermediate).  Advanced has no line book — free-text refs.
        self._pg = tk.StringVar()
        self._ln = tk.StringVar()
        if view._book:
            ttk.Label(addbar, text="  or from book page:").pack(side=LEFT)
            pgc = ttk.Combobox(addbar, textvariable=self._pg, width=5,
                               state="readonly",
                               values=[str(p) for p in spine.soe_pages(view._book)])
            pgc.pack(side=LEFT, padx=2)
            self._lnc = ttk.Combobox(addbar, textvariable=self._ln, width=24,
                                     state="readonly", values=[])
            self._lnc.pack(side=LEFT, padx=2)
            pgc.bind("<<ComboboxSelected>>", self._fill_lines)
            ttk.Button(addbar, text="Add line", bootstyle=(SUCCESS, OUTLINE, LINK),
                       command=self._add_from_line).pack(side=LEFT, padx=2)

        btns = ttk.Frame(self)
        btns.pack(fill=X, padx=14, pady=(6, 12))
        ttk.Button(btns, text="Save", bootstyle=SUCCESS,
                   command=self._save).pack(side=RIGHT)
        ttk.Button(btns, text="Cancel", bootstyle=(SECONDARY, OUTLINE),
                   command=self.destroy).pack(side=RIGHT, padx=6)
        ttk.Button(btns, text="Use suggested schedule",
                   bootstyle=(INFO, OUTLINE, LINK),
                   command=self._reset_suggested).pack(side=LEFT)

    def _add_row(self, ref, due):
        row = ttk.Frame(self._list)
        row.pack(fill=X, pady=1)
        rv = tk.StringVar(value=ref)
        dv = tk.StringVar(value=due)
        ttk.Entry(row, textvariable=rv, width=36).pack(side=LEFT, padx=(0, 4))
        ttk.Entry(row, textvariable=dv, width=14).pack(side=LEFT)
        rec = (row, rv, dv)
        ttk.Button(row, text="✕", width=2, bootstyle=(DANGER, OUTLINE, LINK),
                   command=lambda: self._del_row(rec)).pack(side=LEFT, padx=4)
        self._rows.append(rec)

    def _del_row(self, rec):
        rec[0].destroy()
        try:
            self._rows.remove(rec)
        except ValueError:
            pass

    def _fill_lines(self, _e=None):
        try:
            lines = spine.soe_lines_on_page(int(self._pg.get()), self.view._book)
        except (ValueError, TypeError):
            lines = []
        labels = [f"#{r['n']} {r['title']}" for r in lines]
        self._lnc.config(values=labels)
        self._ln.set(labels[0] if labels else "")

    def _add_from_line(self):
        ref = self._ln.get().strip()
        if ref:
            self._add_row(ref, "")

    def _reset_suggested(self):
        for rec in list(self._rows):
            self._del_row(rec)
        for it in self.view._default_assessments():
            due = it.get("due")
            self._add_row(it["ref"], due.isoformat() if due else "")

    def _save(self):
        items, bad = [], []
        for _row, rv, dv in self._rows:
            ref, ds = rv.get().strip(), dv.get().strip()
            if not ref:
                continue                       # a date with no line — skip
            due = None
            if ds:                             # blank date is allowed (dateless)
                due = _parse_date(ds)
                if not due:
                    bad.append(ref)
                    continue
            items.append({"ref": ref, "due": due})
        if bad:
            Messagebox.show_warning(
                "These rows need a valid date (YYYY-MM-DD) or a blank date: "
                + ", ".join(bad),
                title="Check due dates", parent=self)
            return
        self.view._save_assessments(items)
        self.destroy()


# ─────────────────────────────────────────────────────────────── helpers ─────

def _snap_weekday(d):
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def _parse_date(s):
    if not s:
        return None
    try:
        return date.fromisoformat(str(s)[:10])
    except Exception:
        return None


def _safe_json(raw, default):
    if not raw:
        return default
    try:
        return json.loads(raw)
    except Exception:
        return default


def _infer_section_kind(title):
    """Best-guess section kind from its title, for healing legacy days that
    saved a null kind (see AgendasView._heal_kinds)."""
    t = (title or "").lower()
    if "band book" in t or "bandbook" in t:
        return "bandbook"
    if "rhythm" in t:
        return "rhythms"
    if "sheet music" in t or "sheet" in t:
        return "sheet"
    if "practice journal" in t:
        return "pj"
    if any(k in t for k in ("warm up", "warm-up", "warmup",
                            "fundamentals", "broccoli")):
        return "warmup"
    return ""
