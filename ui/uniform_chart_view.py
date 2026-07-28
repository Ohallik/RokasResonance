"""
ui/uniform_chart_view.py — "Who has which garment" chart.

One row per current student, one column per garment type; each cell shows the
item number they hold (blank = not assigned, so missing pieces stand out).  This
is the at-a-glance sheet a director prints and posts so kids who forget their
numbers have one thing to check.
"""

import os
import tkinter as tk
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from ttkbootstrap.dialogs import Messagebox

from ui.theme import fs, muted_fg, fit_window


class UniformChartView(ttk.Toplevel):
    def __init__(self, parent, db, base_dir):
        super().__init__(parent)
        self.db = db
        self.base_dir = base_dir
        self.title("Uniform Assignments — Who Has What")
        self._only_missing = tk.BooleanVar(value=False)
        self._build()
        self._reload()
        fit_window(self, 900, 600)

    def _build(self):
        hdr = ttk.Frame(self, bootstyle=SUCCESS)
        hdr.pack(fill=X)
        ttk.Label(hdr, text="📊  Uniform Assignments", font=("Segoe UI", fs(13), "bold"),
                  bootstyle=(INVERSE, SUCCESS)).pack(side=LEFT, pady=10, padx=16)

        bar = ttk.Frame(self)
        bar.pack(fill=X, padx=10, pady=6)
        ttk.Checkbutton(bar, text="Only students missing a piece",
                        variable=self._only_missing, bootstyle="round-toggle",
                        command=self._reload).pack(side=LEFT)
        ttk.Button(bar, text="🖨 Print / Save PDF", bootstyle=SUCCESS,
                   command=self._print).pack(side=RIGHT, padx=2)
        self._count = ttk.Label(bar, text="", font=("Segoe UI", fs(8)),
                                foreground=muted_fg())
        self._count.pack(side=RIGHT, padx=10)

        wrap = ttk.Frame(self)
        wrap.pack(fill=BOTH, expand=True, padx=10, pady=(0, 10))
        self._xsb = ttk.Scrollbar(wrap, orient=HORIZONTAL)
        self._ysb = ttk.Scrollbar(wrap, orient=VERTICAL)
        self.tree = ttk.Treeview(wrap, show="headings", bootstyle=SUCCESS,
                                 xscrollcommand=self._xsb.set,
                                 yscrollcommand=self._ysb.set)
        self._xsb.config(command=self.tree.xview)
        self._ysb.config(command=self.tree.yview)
        self._ysb.pack(side=RIGHT, fill=Y)
        self._xsb.pack(side=BOTTOM, fill=X)
        self.tree.pack(fill=BOTH, expand=True)
        self.tree.tag_configure("missing", foreground="#b3261e")

    def _reload(self):
        types, rows = self.db.get_uniform_chart()
        self._types = types
        cols = ["student", "grade"] + types
        self.tree.config(columns=cols)
        # Student + Grade get fixed widths (so the name column no longer hogs
        # space); the garment columns are sized to fit their header text and
        # stretch to share any leftover width, so headers stay readable.
        self.tree.heading("student", text="Student")
        self.tree.column("student", width=180, minwidth=150, anchor=W, stretch=False)
        self.tree.heading("grade", text="Gr")
        self.tree.column("grade", width=44, minwidth=40, anchor=CENTER, stretch=False)
        for t in types:
            self.tree.heading(t, text=t)
            w = max(120, len(t) * 9 + 26)  # wide enough for the full header
            self.tree.column(t, width=w, minwidth=w, anchor=CENTER, stretch=True)

        self.tree.delete(*self.tree.get_children())
        shown = missing_total = 0
        for r in rows:
            missing = [t for t in types if not r["assignments"].get(t)]
            if self._only_missing.get() and not missing:
                continue
            if missing:
                missing_total += 1
            vals = [r["student"], r["grade"]] + \
                   [r["assignments"].get(t, "") for t in types]
            self.tree.insert("", "end", values=vals,
                             tags=("missing",) if missing else ())
            shown += 1
        self._count.config(
            text=f"{shown} students • {missing_total} missing at least one piece")

    def _print(self):
        try:
            from pdf_generator import generate_uniform_chart
            path = generate_uniform_chart(self.db, self.base_dir)
        except Exception as e:
            Messagebox.show_error(f"Could not create the PDF:\n{e}",
                                  title="Print Failed", parent=self)
            return
        try:
            os.startfile(path)  # Windows: open in default PDF viewer
        except Exception:
            Messagebox.show_info(f"Saved to:\n{path}", title="Chart Saved",
                                 parent=self)
