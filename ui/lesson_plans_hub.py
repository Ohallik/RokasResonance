"""
ui/lesson_plans_hub.py - Teacher Tools hub.

One window for the tools a director actually uses day to day: seating
charts, percussion rotations, concert planning, and (coming soon) field
trips and daily agendas.  Everything is scoped to a school year — the year
selector switches between per-year files, and the New School Year wizard
closes out one year and opens the next.
"""

import os
import tkinter as tk
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from ui.theme import muted_fg, fs


class LessonPlansHub(ttk.Frame):
    """Tabbed hub for all Teacher Tools functionality."""

    def __init__(self, parent, db):
        super().__init__(parent)
        self.main_db = db  # instruments, students, music
        self._base_dir = os.path.dirname(os.path.abspath(db.db_path))

        # Per-year tools database
        from lesson_plan_db import (
            get_lesson_plan_db, current_school_year,
            migrate_from_main_db,
        )
        migrated = migrate_from_main_db(db.db_path, self._base_dir)
        self._current_year = migrated or self._opening_year()
        self.db = get_lesson_plan_db(self._base_dir, self._current_year)
        self._build()

    def _opening_year(self):
        """Which school year to open on.

        The year last worked in, when there is one.  Failing that, the most
        recent year that actually has students: opening on a year whose roster
        is empty shows blank seating charts, an empty field trip roster and a
        blank Number of Students on a printed form, all of which read as data
        loss rather than as "you are looking at the wrong year".  The calendar
        year is only the fallback for a profile with no roster at all.
        """
        from lesson_plan_db import current_school_year
        try:
            from ui.settings_dialog import load_settings
            remembered = ((load_settings(self._base_dir).get("lesson_plans")
                           or {}).get("last_year") or "").strip()
        except Exception:
            remembered = ""
        if remembered:
            return remembered
        try:
            for year in self.main_db.get_school_years():
                if self.main_db.get_students_for_email(school_year=year,
                                                       level=None):
                    return year
        except Exception:
            pass
        return current_school_year()

    def _remember_year(self, year):
        """So Teacher Tools comes back where it was left."""
        try:
            from ui.settings_dialog import load_settings, save_settings
            cfg = load_settings(self._base_dir) or {}
            cfg.setdefault("lesson_plans", {})["last_year"] = year
            save_settings(self._base_dir, cfg)
        except Exception:
            pass

    def _build(self):
        # ── Header ───────────────────────────────────────────────────────────
        header = ttk.Frame(self, bootstyle=PRIMARY)
        header.pack(fill=X)

        # The ? follows the open tab, so it lands on seating, concerts or
        # agendas rather than on a general "Teacher Tools" page.
        from ui.help_system import add_help_button
        add_help_button(header, self._help_topic)

        # Buttons are packed BEFORE the title so a narrow window truncates the
        # description rather than pushing the buttons off the right edge.
        ttk.Button(
            header, text="🗂 Manage Classes…", bootstyle=LIGHT,
            command=self._open_manage_classes,
        ).pack(side=RIGHT, padx=(0, 16), pady=8)
        ttk.Button(
            header, text="🔢 Numbers Per Part…", bootstyle=LIGHT,
            command=self._open_numbers_per_part,
        ).pack(side=RIGHT, padx=(0, 4), pady=8)
        # A once-a-year job, and a destructive one: it archives last year's
        # roster and rolls everything forward.  It sits here, beside the year
        # selector it moves, rather than as a full-width button on the hub
        # where it was easy to hit on any of the other 364 days.
        ttk.Button(
            header, text="📦 New School Year…", bootstyle=LIGHT,
            command=self._open_year_wizard,
        ).pack(side=RIGHT, padx=(0, 4), pady=8)

        ttk.Label(
            header,
            text="🧰  Teacher Tools",
            font=("Segoe UI", fs(16), "bold"),
            bootstyle=(INVERSE, PRIMARY),
        ).pack(side=LEFT, padx=16, pady=12)

        # School year selector
        year_frame = ttk.Frame(header, bootstyle=PRIMARY)
        year_frame.pack(side=LEFT, padx=8, pady=8)
        ttk.Label(
            year_frame, text="Year:",
            font=("Segoe UI", fs(9)),
            bootstyle=(INVERSE, PRIMARY),
        ).pack(side=LEFT, padx=(0, 4))
        self._year_var = tk.StringVar(value=self._current_year)
        self._year_combo = ttk.Combobox(
            year_frame, textvariable=self._year_var,
            state="readonly", width=12,
        )
        self._year_combo.pack(side=LEFT)
        self._populate_year_selector()
        self._year_combo.bind("<<ComboboxSelected>>",
                              lambda e: self._switch_school_year())
        ttk.Label(
            header,
            text="Seating charts, percussion rotations, concert planning & more",
            font=("Segoe UI", fs(9)),
            bootstyle=(INVERSE, PRIMARY),
        ).pack(side=LEFT, padx=(8, 8), pady=12)

        # ── Notebook ─────────────────────────────────────────────────────────
        # A fixed handful of tabs, no matter how many classes the teacher runs.
        # A tab strip that grows a new entry per class becomes unreadable by the
        # time someone teaches six sections, so every class's agenda lives
        # behind one class picker inside Agendas.  Percussion and Jazz are two
        # tabs (bands appear as toggles INSIDE the Jazz tab).
        self._notebook = ttk.Notebook(self, bootstyle=PRIMARY)
        self._notebook.pack(fill=BOTH, expand=True)
        self._seating = self._percussion = self._jazz = self._concerts = None
        self._field_trips = self._agendas = None
        self._populate_notebook()
        self._notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

    # ── Notebook tabs are built from the teacher's class registry, so choir/
    #    orchestra/club teachers get their own classes and only band teachers
    #    with a percussion/jazz class see those tool tabs. ──

    def _program_type(self):
        try:
            from ui.settings_dialog import load_settings
            return (load_settings(self._base_dir).get("teacher") or {}).get(
                "program_type", "band")
        except Exception:
            return "band"

    _HELP_TOPICS = {"seating": "seating", "percussion": "percussion",
                    "perc": "percussion", "jazz": "percussion",
                    "performances": "concerts",
                    "agendas": "agendas"}

    def _help_topic(self):
        """Which section of the guide the ? should open, for the tab on show."""
        try:
            label = self._notebook.tab(self._notebook.select(), "text").lower()
        except Exception:
            return "tools"
        for word, topic in self._HELP_TOPICS.items():
            if word in label:
                return topic
        return "tools"

    def _classes(self):
        import class_registry
        return class_registry.load_classes(self._base_dir, self._program_type())

    def _populate_notebook(self):
        # Clear any existing tabs (Manage Classes / year switch rebuilds live).
        for tab_id in list(self._notebook.tabs()):
            w = self._notebook.nametowidget(tab_id)
            self._notebook.forget(tab_id)
            w.destroy()
        classes = self._classes()
        program = self._program_type()

        from ui.seating_chart_view import SeatingChartView
        self._seating = SeatingChartView(self._notebook, self.db,
                                         self.main_db, self._base_dir)
        self._notebook.add(self._seating, text="  🪑 Seating Charts  ")

        self._percussion = None
        self._jazz = None
        # Percussion and Jazz are SEPARATE tabs: concert rotations and the jazz
        # band are different rooms, and squeezing both behind one toggle left
        # the jazz side cramped and hard to find.  Choir/orchestra never see
        # either.
        has_perc = program not in ("choir", "orchestra") and any(
            k.get("percussion") for k in classes)
        has_jazz = program not in ("choir", "orchestra") and any(
            k.get("template") == "jazz" for k in classes)
        if has_perc:
            from ui.percussion_rotation_view import PercussionRotationView
            self._percussion = PercussionRotationView(
                self._notebook, self.db, main_db=self.main_db,
                base_dir=self._base_dir)
            self._notebook.add(self._percussion, text="  🥁 Percussion  ")
        if has_jazz:
            from ui.jazz_view import JazzView
            self._jazz = JazzView(self._notebook, self.db,
                                  main_db=self.main_db,
                                  base_dir=self._base_dir)
            self._notebook.add(self._jazz, text="  🎷 Jazz  ")

        # One tab, because a field trip is a performance with more paperwork
        # and the two were always read together: "what is coming up" used to be
        # a question you answered in two windows and merged in your head.
        self._performances = _PerformancesTab(self._notebook, self.db,
                                              self.main_db, self._base_dir)
        self._notebook.add(self._performances, text="  🎪 Performances  ")
        self._concerts = self._performances
        self._field_trips = self._performances

        self._agendas = _AgendasTab(self._notebook, self.db, self.main_db,
                                    self._base_dir, classes)
        self._notebook.add(self._agendas, text="  📋 Agendas  ")

    def _open_numbers_per_part(self):
        from ui.instrumentation_view import open_instrumentation
        open_instrumentation(self, self.main_db, self._base_dir,
                             self._student_year())

    def _student_year(self):
        """The roster year matching the hub's selected school year (falling
        back to the newest year that actually has students)."""
        try:
            years = self.main_db.get_school_years()
        except Exception:
            return self._current_year
        if self._current_year in years:
            return self._current_year
        return years[0] if years else self._current_year

    def _open_year_wizard(self):
        """Roll the whole program into the next school year.

        It archives last year's roster and moves every tool forward, so it is
        deliberately not a hub button any more: it belongs beside the year
        selector it changes, and being one click further away is the point.
        """
        from ui.year_wizard import NewSchoolYearWizard
        from lesson_plan_db import current_school_year
        try:
            years = self.main_db.get_school_years()
        except Exception:
            years = []
        current = years[0] if years else current_school_year()
        wiz = NewSchoolYearWizard(self.winfo_toplevel(), self.main_db,
                                  self._base_dir, current_year=current)
        self.winfo_toplevel().wait_window(wiz)
        new_year = getattr(wiz, "new_year", None)
        if not new_year:
            return
        # Everything on screen is now showing last year, including this hub --
        # so it follows the wizard rather than leaving the teacher to notice.
        try:
            self.switch_to_year(new_year)
        except Exception:
            pass
        try:
            self.event_generate("<<YearRolledOver>>")
        except Exception:
            pass

    def _open_manage_classes(self):
        classes = self._classes()
        dlg = _ManageClassesDialog(self.winfo_toplevel(), classes,
                                   self._program_type(),
                                   main_db=self.main_db)
        self.wait_window(dlg)
        if dlg.result is None:
            return
        import class_registry
        class_registry.save_classes(self._base_dir, dlg.result)
        self._populate_notebook()

    def _placeholder(self, icon, title, body):
        outer = ttk.Frame(self._notebook)
        frame = ttk.Frame(outer)
        frame.place(relx=0.5, rely=0.45, anchor="center")
        ttk.Label(frame, text=icon, font=("Segoe UI", fs(40))).pack(pady=(0, 10))
        ttk.Label(frame, text=title,
                  font=("Segoe UI", fs(16), "bold")).pack()
        ttk.Label(frame, text=body, font=("Segoe UI", fs(10)),
                  foreground=muted_fg(), justify="center").pack(pady=(8, 0))
        return outer

    def _tabs(self):
        core = [self._seating, self._percussion, self._jazz,
                self._performances, self._agendas]
        return [t for t in core if t is not None]

    def _on_tab_changed(self, event):
        """Refresh the active tab's data when switching to it."""
        try:
            widget = self._notebook.nametowidget(self._notebook.select())
        except Exception:
            return
        if hasattr(widget, "refresh"):
            widget.refresh()

    # ── School years ─────────────────────────────────────────────────────────

    def _populate_year_selector(self):
        """Past years and the current one — never a year that hasn't started.

        Previous years are here to look things up; there is no reason to plan
        into a year the roster hasn't been rolled into yet, and doing so files
        the work somewhere the teacher will never find it again.  The New School
        Year wizard (on the main hub) is what opens the next year."""
        from lesson_plan_db import (list_available_school_years,
                                    current_school_year, past_and_current_years)
        years = past_and_current_years(list_available_school_years(self._base_dir))
        cur = current_school_year()
        if cur not in years:
            years.insert(0, cur)
        if self._current_year not in years and self._current_year:
            years.insert(0, self._current_year)
        years = sorted(set(years), reverse=True)
        self._year_combo.config(values=years)
        self._year_combo.set(self._current_year)

    def _switch_school_year(self):
        new_year = self._year_var.get()
        if new_year == self._current_year:
            return
        from lesson_plan_db import get_lesson_plan_db
        self._current_year = new_year
        self._remember_year(new_year)
        self.db = get_lesson_plan_db(self._base_dir, new_year)
        for tab in self._tabs():
            tab.db = self.db
            # Views that cache per-year data (the mallet inventory) must drop
            # it, or the new year renders with the old year's equipment list.
            if hasattr(tab, "_inv_cache"):
                del tab._inv_cache
            tab.refresh()

    def switch_to_year(self, year: str):
        """Programmatic year switch (used by the New School Year wizard)."""
        self._year_var.set(year)
        self._populate_year_selector()
        self._year_combo.set(year)
        self._switch_school_year()


# ══════════════════════════════════════════════════════════ container tabs ═══
# Both of these exist to keep the tab strip at five entries.  Each owns a set of
# child views, shows one at a time behind a toggle, and forwards the hub's two
# contract points (``db`` assignment on a year switch, and ``refresh()``).

class _SwitcherTab(ttk.Frame):
    """Base for a tab that hosts several views behind a toggle bar.

    Children are built LAZILY — a teacher with eight classes shouldn't pay to
    construct eight agenda editors to look at one.
    """

    def __init__(self, parent, db):
        super().__init__(parent)
        self._db = db
        self._views = {}          # key -> child view
        self._active = None

        self._bar = ttk.Frame(self, bootstyle=LIGHT)
        self._bar.pack(fill=X)
        self._host = ttk.Frame(self)
        self._host.pack(fill=BOTH, expand=True)

    # The hub reassigns ``tab.db`` when the school year changes; push it down.
    @property
    def db(self):
        return self._db

    @db.setter
    def db(self, value):
        self._db = value
        for view in self._views.values():
            view.db = value
            # Views that cache per-year data (the mallet inventory) must drop it,
            # or the new year would render with the old year's equipment list.
            if hasattr(view, "_inv_cache"):
                del view._inv_cache

    def _make_view(self, key):
        raise NotImplementedError

    def _show(self, key):
        if key is None:
            return
        view = self._views.get(key)
        if view is None:
            view = self._make_view(key)
            if view is None:
                return
            self._views[key] = view
        if self._active is not None and self._active != key:
            prev = self._views.get(self._active)
            if prev is not None:
                prev.pack_forget()
        self._active = key
        view.pack(fill=BOTH, expand=True)
        if hasattr(view, "refresh"):
            view.refresh()

    def refresh(self):
        view = self._views.get(self._active)
        if view is not None and hasattr(view, "refresh"):
            view.refresh()

    def _toggle_button(self, key, text, var):
        ttk.Radiobutton(self._bar, text=text, value=key, variable=var,
                        bootstyle=(PRIMARY, "toolbutton"),
                        command=lambda k=key: self._show(k)
                        ).pack(side=LEFT, padx=2, pady=4)


class _AgendasTab(_SwitcherTab):
    """One Agendas tab for every class the teacher runs.

    Previously each class claimed its own notebook tab, which is what made the
    strip unreadable.  The class picker here is the same information in one
    row — and it's built from the class registry, so adding a class in Manage
    Classes is the only place a class name is ever typed.
    """

    def __init__(self, parent, db, main_db, base_dir, classes):
        super().__init__(parent, db)
        self.main_db = main_db
        self.base_dir = base_dir
        self._classes = {k["id"]: k for k in classes}
        first = classes[0]["id"] if classes else None
        self._var = tk.StringVar(value=first or "")
        ttk.Label(self._bar, text="Class:", font=("Segoe UI", fs(9)),
                  foreground=muted_fg()).pack(side=LEFT, padx=(8, 4))
        # Short display labels ("Entry", "Jazz") — full names stay in Manage
        # Classes; the toggle is keyed by class id, so the label is pure display.
        import class_registry as cr
        dmap = cr.display_map([k["label"] for k in classes])
        for k in classes:
            self._toggle_button(k["id"], dmap[k["label"]], self._var)
        if not classes:
            ttk.Label(self._bar,
                      text="No classes yet — add them with “Manage Classes…”.",
                      font=("Segoe UI", fs(9)),
                      foreground=muted_fg()).pack(side=LEFT, padx=8, pady=6)
        self._show(first)

    def _make_view(self, key):
        klass = self._classes.get(key)
        if klass is None:
            return None
        from ui.agendas_view import AgendasView
        return AgendasView(self._host, self._db, self.main_db,
                           self.base_dir, klass=klass)


# ── Template display names for the Manage Classes picker ──────────────────────
# Plain names only — teachers pick during first-run setup before they know what
# each includes, so descriptions here would just confuse. (Details live in each
# template's ``desc`` and show up later in Manage Classes.)
_TMPL_DISPLAY = {
    "generic": "General",
    "band_5": "5th Grade Band",
    "orch_5": "5th Grade Orchestra",
    "band_entry": "MS Band (Entry)",
    "band_intermediate": "MS Band (Intermediate)",
    "band_advanced": "MS Band (Advanced)",
    "orch_mshs": "MS/HS Orchestra",
    "choir_mshs": "MS/HS Choir",
    "jazz_choir": "Jazz Choir",
    "guitar": "MS/HS Guitar",
    "steel_drum": "HS Steel Drum",
    "piano": "MS/HS Piano",
    "guitar_steel": "MS/HS Guitar / Steel Drum",   # retired; see class_registry
    "hs_band_winds": "HS Band (Winds)",
    "hs_band_perc": "HS Band (Percussion)",
    "jazz": "Jazz",
}


class _UpcomingView(ttk.Frame):
    """Everything the band is going to, concerts and trips together, by date.

    A field trip IS a performance, with more paperwork attached: the festival
    you drive to is both. Keeping them on two tabs meant the only way to see
    what was coming was to look in two places and merge them in your head.
    """

    def __init__(self, parent, db, on_open):
        super().__init__(parent)
        self._db = db
        self._on_open = on_open

        head = ttk.Frame(self)
        head.pack(fill=X, padx=14, pady=(12, 4))
        ttk.Label(head, text="🗓  Everything coming up",
                  font=("Segoe UI", fs(12), "bold")).pack(side=LEFT)
        ttk.Label(head, text="Concerts and field trips together, soonest first. "
                            "Double-click one to open it.",
                  font=("Segoe UI", fs(8)),
                  foreground=muted_fg()).pack(side=LEFT, padx=(10, 0))

        cols = ("when", "kind", "what", "who", "where")
        self._tree = ttk.Treeview(self, columns=cols, show="headings", height=14)
        for c, txt, w in (("when", "Date", 110), ("kind", "", 90),
                          ("what", "What", 240), ("who", "Who's going", 200),
                          ("where", "Where", 200)):
            self._tree.heading(c, text=txt)
            self._tree.column(c, width=fs(w), anchor=W)
        self._tree.pack(fill=BOTH, expand=True, padx=14, pady=(4, 8))
        self._tree.bind("<Double-1>", self._open)
        self._tree.tag_configure("past", foreground=muted_fg())

        self._empty = ttk.Label(
            self, text="", font=("Segoe UI", fs(9)), foreground=muted_fg(),
            wraplength=fs(46) * 12, justify=LEFT)
        self._empty.pack(anchor=W, padx=14, pady=(0, 10))
        self._rows = []
        self.refresh()

    @property
    def db(self):
        return self._db

    @db.setter
    def db(self, value):
        self._db = value
        self.refresh()

    def _year(self):
        base = os.path.basename(getattr(self._db, "db_path", "") or "")
        if base.startswith("lesson_plans_") and base.endswith(".db"):
            return base[len("lesson_plans_"):-len(".db")]
        return None

    @staticmethod
    def _pretty(date_str):
        from datetime import datetime as _dt
        for f in ("%Y-%m-%d", "%m/%d/%Y"):
            try:
                return _dt.strptime((date_str or "").strip(), f).strftime("%a %b %d")
            except ValueError:
                continue
        return (date_str or "").strip() or "(no date)"

    def refresh(self):
        from datetime import date as _date
        for iid in self._tree.get_children():
            self._tree.delete(iid)
        year = self._year()
        items = []
        try:
            for c in self._db.get_concerts(year):
                c = dict(c)
                items.append({
                    "date": (c.get("concert_date") or "").strip(),
                    "kind": "concert", "label": "🎪 Concert",
                    "id": c.get("id"), "what": c.get("title") or "Concert",
                    "who": c.get("ensembles") or "",
                    "where": c.get("location") or "",
                })
        except Exception:
            pass
        try:
            for t in self._db.get_field_trips(year):
                t = dict(t)
                items.append({
                    "date": (t.get("depart_date") or "").strip(),
                    "kind": "trip", "label": "🚌 Field trip",
                    "id": t.get("id"), "what": t.get("name") or "Field trip",
                    "who": t.get("groups_list") or "",
                    "where": t.get("destination") or "",
                })
        except Exception:
            pass

        # Undated events sort last, not first: a blank date is a plan without a
        # day yet, and it should not sit above tomorrow's concert.
        items.sort(key=lambda x: (not x["date"], x["date"]))
        today = _date.today().isoformat()
        self._rows = items
        for i, x in enumerate(items):
            past = bool(x["date"]) and x["date"] < today
            self._tree.insert(
                "", "end", iid=str(i),
                values=(self._pretty(x["date"]), x["label"], x["what"],
                        x["who"], x["where"]),
                tags=("past",) if past else ())
        if not items:
            self._empty.config(
                text="Nothing on the calendar yet. Add a concert or a field "
                     "trip with the buttons above and it appears here.")
        else:
            ahead = sum(1 for x in items if not x["date"] or x["date"] >= today)
            self._empty.config(
                text="%d coming up, %d already done."
                     % (ahead, len(items) - ahead))

    def _open(self, _event=None):
        sel = self._tree.selection()
        if not sel:
            return
        try:
            row = self._rows[int(sel[0])]
        except (ValueError, IndexError):
            return
        self._on_open(row["kind"], row["id"])


class _PerformancesTab(_SwitcherTab):
    """Concerts and field trips in one place, with a dated list over both.

    They were two tabs. A field trip is a performance with more paperwork, and
    the two were always read together anyway -- "what is coming up" was a
    question you had to answer in two windows.
    """

    def __init__(self, parent, db, main_db, base_dir):
        super().__init__(parent, db)
        self._main_db = main_db
        self._base_dir = base_dir
        var = tk.StringVar(value="upcoming")
        for key, text in (("upcoming", "  🗓 Upcoming  "),
                          ("concerts", "  🎪 Concerts  "),
                          ("trips", "  🚌 Field Trips  ")):
            self._toggle_button(key, text, var)
        self._show("upcoming")

    def _make_view(self, key):
        if key == "upcoming":
            return _UpcomingView(self._host, self._db, self._open_one)
        if key == "concerts":
            from ui.concerts_view import ConcertsView
            return ConcertsView(self._host, self._db, self._main_db,
                                self._base_dir)
        from ui.field_trips_view import FieldTripsView
        return FieldTripsView(self._host, self._db, self._main_db,
                              self._base_dir)

    def _open_one(self, kind, _item_id):
        """Double-clicking a line goes to the window that owns it."""
        self._show("concerts" if kind == "concert" else "trips")

    def refresh(self):
        # The dated list is the one that goes stale when something is added in
        # another view, so refresh it whether or not it is on screen.
        up = self._views.get("upcoming")
        if up is not None:
            try:
                up.refresh()
            except Exception:
                pass
        super().refresh()



class _ManageClassesDialog(ttk.Toplevel):
    """Add / rename / remove / reorder the classes that get an agenda tab.

    Each class picks a TEMPLATE (its kind).  Existing classes keep their stored
    id (so saved agendas stay attached); new ones get an id from their name.
    """

    def __init__(self, parent, classes, program_type, main_db=None):
        super().__init__(master=parent)
        import class_registry as cr
        self._cr = cr
        self.result = None
        self._program_type = program_type
        # The secondary schools a class can belong to.  With fewer than two
        # there is nothing to choose, and the column stays out of the way.
        self._schools = []
        try:
            self._schools = [dict(x) for x in main_db.get_sites()
                             if dict(x).get("level") != "elementary"]
        except Exception:
            pass
        self._multi_school = len(self._schools) >= 2
        self._school_by_name = {x["name"]: x["id"] for x in self._schools}
        self._school_by_id = {x["id"]: x["name"] for x in self._schools}
        self.title("Manage Classes")
        self.resizable(False, True)
        self.grab_set()
        self.lift()

        self._display_to_tmpl = {v: k for k, v in _TMPL_DISPLAY.items()}
        self._tmpl_options = [_TMPL_DISPLAY[t] for t in cr.TEMPLATE_ORDER]

        hdr = ttk.Frame(self, bootstyle=PRIMARY)
        hdr.pack(fill=X)
        ttk.Label(hdr, text="🗂  Your Classes", font=("Segoe UI", 13, "bold"),
                  bootstyle=(INVERSE, PRIMARY)).pack(pady=12, padx=16, anchor=W)

        # Buttons pinned to the bottom.
        btn = ttk.Frame(self)
        btn.pack(side=BOTTOM, fill=X, padx=16, pady=12)
        ttk.Button(btn, text="Cancel", bootstyle=(SECONDARY, OUTLINE),
                   command=self.destroy).pack(side=RIGHT, padx=4)
        ttk.Button(btn, text="Save", bootstyle=SUCCESS,
                   command=self._save).pack(side=RIGHT, padx=4)

        body = ttk.Frame(self)
        body.pack(fill=BOTH, expand=True, padx=16, pady=10)
        ttk.Label(body, text="One row per class or club. Each gets its own agenda "
                             "tab. Pick the kind of class (its template); rename "
                             "or reorder freely. Itinerant teachers can add as "
                             "many — or as few — as they run.",
                  font=("Segoe UI", 9), wraplength=560, justify=LEFT).pack(anchor=W)
        ttk.Label(body, text="Periods: the class periods this class "
                             "meets, separated by commas. \u201c1, 2\u201d "
                             "means two sections, and the agenda gets a "
                             "P1 / P2 toggle. Blank means one section.",
                  font=("Segoe UI", 9), foreground=muted_fg(),
                  wraplength=560, justify=LEFT).pack(anchor=W, pady=(4, 0))

        self._rows_frame = ttk.Frame(body)
        self._rows_frame.pack(fill=BOTH, expand=True, pady=(8, 0))
        self._rows = []
        for k in classes:
            self._add_row(k)

        ttk.Button(body, text="➕ Add class / club", bootstyle=(SUCCESS, OUTLINE),
                   command=lambda: self._add_row(None)).pack(anchor=W, pady=(8, 0))

        from ui.theme import fit_window
        fit_window(self, 620, 520)

    def _add_row(self, klass):
        tmpl = (klass or {}).get("template", "generic")
        if tmpl not in _TMPL_DISPLAY:
            tmpl = "generic"
        rec = {
            "orig": klass,
            "label": tk.StringVar(value=(klass or {}).get("label", "")),
            "template": tk.StringVar(value=_TMPL_DISPLAY[tmpl]),
            "periods": tk.StringVar(
                value=", ".join((klass or {}).get("periods") or [])),
            "school": tk.StringVar(value=self._school_by_id.get(
                (klass or {}).get("site_id"), "")),
        }
        self._rows.append(rec)
        self._render_rows()

    def _render_rows(self):
        """Headers and fields share one grid, so the columns cannot drift the
        way a separate header row packed to its own widths did."""
        f = self._rows_frame
        for w in f.winfo_children():
            w.destroy()
        heads = ["Class name", "Kind of class", "Periods (e.g. 1, 2)"]
        if self._multi_school:
            heads.append("School")
        for c, text in enumerate(heads):
            ttk.Label(f, text=text, font=("Segoe UI", 9, "bold")).grid(
                row=0, column=c, sticky=W, padx=(0 if c == 0 else 6, 0),
                pady=(0, 2))
        for i, rec in enumerate(self._rows):
            r = i + 1
            ttk.Entry(f, textvariable=rec["label"], width=22).grid(
                row=r, column=0, sticky="ew", pady=2)
            ttk.Combobox(f, textvariable=rec["template"], state="readonly",
                         values=self._tmpl_options, width=30).grid(
                row=r, column=1, sticky="ew", padx=(6, 0), pady=2)
            ttk.Entry(f, textvariable=rec["periods"], width=12).grid(
                row=r, column=2, sticky="ew", padx=(6, 0), pady=2)
            col = 3
            if self._multi_school:
                ttk.Combobox(f, textvariable=rec["school"], state="readonly",
                             width=16, values=[""] + [x["name"] for x in
                                                      self._schools]).grid(
                    row=r, column=3, sticky="ew", padx=(6, 0), pady=2)
                col = 4
            ttk.Button(f, text="▲", width=2, bootstyle=(SECONDARY, OUTLINE, LINK),
                       command=lambda ix=i: self._move(ix, -1)).grid(
                row=r, column=col, padx=(8, 0))
            ttk.Button(f, text="▼", width=2, bootstyle=(SECONDARY, OUTLINE, LINK),
                       command=lambda ix=i: self._move(ix, 1)).grid(
                row=r, column=col + 1)
            ttk.Button(f, text="✕", width=2, bootstyle=(DANGER, OUTLINE, LINK),
                       command=lambda rc=rec: self._remove(rc)).grid(
                row=r, column=col + 2)

    def _remove(self, rec):
        self._rows.remove(rec)
        self._render_rows()

    def _move(self, i, delta):
        j = i + delta
        if 0 <= j < len(self._rows):
            self._rows[i], self._rows[j] = self._rows[j], self._rows[i]
            self._render_rows()

    def _save(self):
        from ttkbootstrap.dialogs import Messagebox
        cr = self._cr
        taken = {(r["orig"] or {}).get("id") for r in self._rows if r["orig"]}
        taken.discard(None)
        result = []
        for rec in self._rows:
            label = rec["label"].get().strip()
            if not label:
                continue
            tmpl = self._display_to_tmpl.get(rec["template"].get(), "generic")
            ti = cr.TEMPLATES[tmpl]
            orig = rec["orig"]
            site = self._school_by_name.get(rec["school"].get().strip())
            if orig:
                k = dict(orig)
                k["label"] = label
                k["periods"] = cr._clean_periods(rec["periods"].get())
                k["site_id"] = site
                if k.get("template") != tmpl:      # kind changed → reset derived
                    k["template"] = tmpl
                    k["book"] = ti["book"]
                    k["percussion"] = ti["percussion"]
                result.append(k)
            else:
                cid = cr.new_class_id([{"id": i} for i in taken], label)
                taken.add(cid)
                result.append({"id": cid, "label": label, "template": tmpl,
                               "ensemble": cid, "book": ti["book"],
                               "percussion": ti["percussion"],
                               "periods": cr._clean_periods(
                                   rec["periods"].get()),
                               "site_id": site})
        if not result:
            Messagebox.show_warning("Keep at least one class.",
                                    title="No classes", parent=self)
            return
        # Two classes that read as the SAME class bound to DIFFERENT schools
        # cannot be told apart by name anywhere rosters are matched, so the
        # binding would silently stop working.  Name them apart instead.
        if self._multi_school:
            seen = {}
            for k in result:
                ident = cr.class_identity(k["label"])
                if ident in seen and seen[ident] != k.get("site_id"):
                    Messagebox.show_warning(
                        f"Two classes named like \u201c{k['label']}\u201d are bound "
                        "to different schools. Give them names that tell them "
                        "apart (for example, add the school), or the school "
                        "binding cannot work.",
                        title="Same name, two schools", parent=self)
                    return
                seen[ident] = k.get("site_id")
        self.result = result
        self.destroy()
