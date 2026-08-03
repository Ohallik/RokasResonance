"""
ui/instrumentation_view.py - "How many of each part do I need?"

The copier question.  Standing at the machine you need to know how many flute
copies Advanced Band takes, or how many flutes there are across Intermediate
AND Advanced when both play the same piece.  Tick the classes, read the count.

Everything comes straight from the student records — instrument and ensemble
are already on each student, so nothing here is typed in and nothing can drift
out of sync with the roster.
"""

import tkinter as tk
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from ttkbootstrap.dialogs import Messagebox

from ui.theme import fs, muted_fg, fit_window
from ui.ensembles import (selectable_ensembles, instrument_sort_key,
                          class_display_map)


def open_instrumentation(parent, main_db, base_dir, school_year=None):
    """Open the numbers-per-part window."""
    return InstrumentationDialog(parent, main_db, base_dir, school_year)


def count_parts(students, ensembles=None, count_secondary=False):
    """``([(instrument, count), ...], total_students)`` in score order.

    ``students`` are student dicts/rows; ``ensembles`` limits them to those
    classes (None = every student given).  A student in two selected classes
    is counted ONCE — you don't print them two folders.
    """
    wanted = list(ensembles) if ensembles else None
    counts = {}
    seen = set()
    from class_registry import csv_has_class
    for s in students:
        sid = s["id"] if "id" in _keys(s) else id(s)
        if sid in seen:
            continue
        if wanted is not None:
            # Identity match: "Entry" / "Entry Band" / "MS Band (Entry)" all
            # select the same students.
            csv = str(_get(s, "ensembles") or "")
            if not any(csv_has_class(csv, w) for w in wanted):
                continue
        seen.add(sid)
        parts = [str(_get(s, "primary_instrument") or "").strip()]
        if count_secondary:
            sec = str(_get(s, "secondary_instrument") or "").strip()
            if sec and sec != parts[0]:
                parts.append(sec)
        for p in parts:
            counts[p or "(no instrument listed)"] = \
                counts.get(p or "(no instrument listed)", 0) + 1
    ordered = sorted(counts.items(), key=lambda kv: instrument_sort_key(kv[0]))
    return ordered, len(seen)


def _keys(row):
    try:
        return row.keys()
    except Exception:
        return []


def _get(row, key):
    try:
        return row[key]
    except Exception:
        return ""


class InstrumentationDialog(ttk.Toplevel):
    def __init__(self, parent, main_db, base_dir, school_year=None):
        super().__init__(parent.winfo_toplevel())
        self.main_db = main_db
        self.base_dir = base_dir
        self.title("Numbers Per Part")
        self.grab_set()
        self.lift()

        self._year = school_year or self._default_year()

        hdr = ttk.Frame(self, bootstyle=INFO)
        hdr.pack(fill=X)
        ttk.Label(hdr, text="🔢  Numbers Per Part",
                  font=("Segoe UI", fs(13), "bold"),
                  bootstyle=(INVERSE, INFO)).pack(pady=10, padx=16, anchor=W)

        # Buttons first so they keep their space on a short screen.
        btn = ttk.Frame(self)
        btn.pack(fill=X, side=BOTTOM, padx=16, pady=12)
        ttk.Button(btn, text="Close", bootstyle=(SECONDARY, OUTLINE),
                   command=self.destroy).pack(side=RIGHT, padx=4)
        ttk.Button(btn, text="📋 Copy List", bootstyle=INFO,
                   command=self._copy).pack(side=RIGHT, padx=4)

        body = ttk.Frame(self)
        body.pack(fill=BOTH, expand=True, padx=16, pady=10)
        ttk.Label(body, text="How many copies of each part to print. Tick the "
                             "class(es) you're making copies for — tick several "
                             "to combine (e.g. Intermediate + Advanced playing "
                             "the same piece).",
                  font=("Segoe UI", fs(9)), wraplength=460,
                  justify=LEFT).pack(anchor=W)

        yr = ttk.Frame(body)
        yr.pack(fill=X, pady=(6, 2))
        ttk.Label(yr, text="School year:", font=("Segoe UI", fs(9), "bold")
                  ).pack(side=LEFT)
        self._year_var = tk.StringVar(value=self._year or "")
        years = self._available_years()
        combo = ttk.Combobox(yr, textvariable=self._year_var, state="readonly",
                             values=years, width=14)
        combo.pack(side=LEFT, padx=(6, 0))
        combo.bind("<<ComboboxSelected>>", lambda e: self._on_year_change())

        pick = ttk.Labelframe(body, text=" Classes to include ", padding=8)
        pick.pack(fill=X, pady=(8, 6))
        self._all = tk.BooleanVar(value=True)
        ttk.Checkbutton(pick, text="All classes", variable=self._all,
                        bootstyle="round-toggle",
                        command=self._toggle_all).pack(anchor=W, pady=(0, 4))
        self._pick_grid = ttk.Frame(pick)
        self._pick_grid.pack(fill=X)
        self._vars, self._checks = {}, []
        self._build_class_checks()

        self._secondary = tk.BooleanVar(value=False)
        ttk.Checkbutton(body, text="Also count secondary instruments "
                                   "(a student who doubles gets both parts)",
                        variable=self._secondary, bootstyle=SECONDARY,
                        command=self._recount).pack(anchor=W)

        table = ttk.Labelframe(body, text=" Instrumentation ", padding=4)
        table.pack(fill=BOTH, expand=True, pady=(8, 0))
        cols = ("Part", "Copies")
        sb = ttk.Scrollbar(table, orient=VERTICAL)
        self._tree = ttk.Treeview(table, columns=cols, show="headings",
                                  yscrollcommand=sb.set, selectmode="none",
                                  bootstyle=INFO, height=12)
        sb.config(command=self._tree.yview)
        self._tree.heading("Part", text="Part", anchor=W)
        self._tree.heading("Copies", text="Copies", anchor=W)
        self._tree.column("Part", width=210, anchor=W, stretch=True)
        self._tree.column("Copies", width=80, anchor=CENTER, stretch=False)
        sb.pack(side=RIGHT, fill=Y)
        self._tree.pack(fill=BOTH, expand=True)

        self._total_lbl = ttk.Label(body, text="", font=("Segoe UI", fs(10), "bold"))
        self._total_lbl.pack(anchor=W, pady=(6, 0))

        self._build_class_checks()
        self._recount()
        fit_window(self, 480, 620)

    # ── context ──────────────────────────────────────────────────────────────

    def _program_type(self):
        try:
            from ui.settings_dialog import load_settings
            return (load_settings(self.base_dir).get("teacher") or {}).get(
                "program_type", "band")
        except Exception:
            return "band"

    def _available_years(self):
        try:
            years = list(self.main_db.get_school_years())
        except Exception:
            years = []
        if self._year and self._year not in years:
            years.insert(0, self._year)
        return years

    def _default_year(self):
        try:
            years = self.main_db.get_school_years()
            if years:
                return years[0]
        except Exception:
            pass
        from lesson_plan_db import current_school_year
        return current_school_year()

    # ── counting ─────────────────────────────────────────────────────────────

    def _build_class_checks(self):
        """One checkbox per class, built from the classes the ROSTER uses (plus
        any configured class that's set up but empty).

        Offering only the configured class names is why ticking a single class
        used to return nothing: a roster imported as "Entry Band" never matches
        a configured "MS Band (Entry)", so the filter excluded everyone while
        "All classes" — which doesn't filter at all — looked fine.
        """
        for cb in self._checks:
            cb.destroy()
        self._vars, self._checks = {}, []
        self._ensembles = selectable_ensembles(
            self.main_db, self._year_var.get() or None,
            self._program_type(), self.base_dir)
        dmap = class_display_map(self._ensembles)
        for i, e in enumerate(self._ensembles):
            v = tk.BooleanVar(value=False)
            cb = ttk.Checkbutton(self._pick_grid, text=dmap[e], variable=v,
                                 bootstyle=INFO, command=self._recount)
            cb.grid(row=i // 2, column=i % 2, sticky=W, padx=(16, 12), pady=1)
            if self._all.get():
                cb.configure(state="disabled")   # disabled while "All" is on
            self._vars[e] = v
            self._checks.append(cb)

    def _on_year_change(self):
        # A different year can have a different set of classes.
        self._build_class_checks()
        self._recount()

    def _toggle_all(self):
        state = "disabled" if self._all.get() else "normal"
        for cb in self._checks:
            cb.configure(state=state)
        self._recount()

    def _selected(self):
        if self._all.get():
            return None                      # None = every student this year
        return [e for e, v in self._vars.items() if v.get()]

    def _recount(self):
        year = self._year_var.get() or None
        try:
            students = list(self.main_db.get_all_students(school_year=year))
        except Exception:
            students = []
        chosen = self._selected()
        if chosen is not None and not chosen:
            self._tree.delete(*self._tree.get_children())
            self._total_lbl.config(text="Tick at least one class.")
            self._rows = []
            return
        rows, total = count_parts(students, chosen, self._secondary.get())
        self._rows = rows
        self._tree.delete(*self._tree.get_children())
        for name, n in rows:
            self._tree.insert("", "end", values=(name, n))
        who = "all classes" if chosen is None else ", ".join(chosen)
        self._total_lbl.config(
            text=f"{total} students · {len(rows)} parts  ({who})")

    def _copy(self):
        if not getattr(self, "_rows", None):
            Messagebox.show_info("Nothing to copy yet.", title="Numbers Per Part",
                                 parent=self)
            return
        chosen = self._selected()
        who = "All classes" if chosen is None else ", ".join(chosen)
        lines = [f"Numbers per part — {who} ({self._year_var.get()})", ""]
        lines += [f"{name}\t{n}" for name, n in self._rows]
        lines.append("")
        lines.append(f"Total\t{sum(n for _, n in self._rows)}")
        self.clipboard_clear()
        self.clipboard_append("\n".join(lines))
        Messagebox.show_info("Copied (tab-separated — paste into Word or Excel).",
                             title="Copied", parent=self)
