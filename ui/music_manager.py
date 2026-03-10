"""
ui/music_manager.py - Sheet music management screen with OMR processing
"""

import os
import json
import shutil
import threading
import tkinter as tk
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from ttkbootstrap.dialogs import Messagebox
from tkinter import filedialog, messagebox
from datetime import datetime
from ui.theme import muted_fg, fs, bind_copy_menu

# MusicPics folder names to search when resolving source_file paths
_MUSIC_PICS_FOLDERS = ["MusicPics", "music_pics", "musicpics"]
# Program directory (RokasResonance/) — used to locate shared MusicPics folder
_APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ── Band column configuration ────────────────────────────────────────────────
BAND_TREEVIEW_COLS = (
    "title", "composer", "arranger",
    "ensemble_type", "genre", "difficulty",
    "key_signature", "time_signature", "location", "last_played", "file_type",
    "source_file",
)
BAND_COL_HEADERS = {
    "title":          "Title",
    "composer":       "Composer",
    "arranger":       "Arranger",
    "ensemble_type":  "Ensemble",
    "genre":          "Genre",
    "difficulty":     "Difficulty",
    "key_signature":  "Key",
    "time_signature": "Time Sig",
    "location":       "Location",
    "last_played":    "Last Played",
    "file_type":      "Type",
    "source_file":    "Source File",
}
BAND_COL_WIDTHS = {
    "title":          220,
    "composer":       140,
    "arranger":       120,
    "ensemble_type":  110,
    "genre":          90,
    "difficulty":     70,
    "key_signature":  90,
    "time_signature": 70,
    "location":       120,
    "last_played":    100,
    "file_type":      50,
    "source_file":    160,
}
BAND_COL_HIDDEN_DEFAULT = {"source_file"}

# ── Choir column configuration ────────────────────────────────────────────────
CHOIR_TREEVIEW_COLS = (
    "title", "composer", "arranger",
    "voicing", "language", "genre", "difficulty",
    "key_signature", "location", "last_played", "file_type",
    "source_file",
)
CHOIR_COL_HEADERS = {
    "title":         "Title",
    "composer":      "Composer",
    "arranger":      "Arranger",
    "voicing":       "Voicing",
    "language":      "Language",
    "genre":         "Genre",
    "difficulty":    "Difficulty",
    "key_signature": "Key",
    "location":      "Location",
    "last_played":   "Last Played",
    "file_type":     "Type",
    "source_file":   "Source File",
}
CHOIR_COL_WIDTHS = {
    "title":         220,
    "composer":      140,
    "arranger":      120,
    "voicing":       90,
    "language":      100,
    "genre":         90,
    "difficulty":    70,
    "key_signature": 70,
    "location":      120,
    "last_played":   100,
    "file_type":     50,
    "source_file":   160,
}
CHOIR_COL_HIDDEN_DEFAULT = {"source_file"}

# Keep module-level aliases pointing to band defaults (backward compat)
TREEVIEW_COLS        = BAND_TREEVIEW_COLS
COL_HEADERS          = BAND_COL_HEADERS
COL_WIDTHS           = BAND_COL_WIDTHS
COL_HIDDEN_DEFAULT   = BAND_COL_HIDDEN_DEFAULT


class _WorksCatalogAdapter:
    """Adapts an external 'works' catalog DB to the sheet_music interface used by MusicManager.

    The works table uses 'grade' for difficulty and lacks location/file fields.
    This adapter translates queries and row dicts so MusicManager works unchanged.
    """

    def __init__(self, db_path: str):
        self.db_path = db_path

    def _connect(self):
        import sqlite3
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _row_to_dict(self, row) -> dict:
        d = dict(row)
        d["difficulty"] = d.get("grade") or ""
        d.setdefault("file_path", "")
        d.setdefault("file_type", "")
        d.setdefault("source_file", "")
        d.setdefault("location", "")
        d.setdefault("last_played", "")
        d.setdefault("is_active", 1)
        d.setdefault("notes", d.get("description") or "")
        return d

    def search_sheet_music(self, search="", genre="", location="", voicing="",
                           order_col="title", order_asc=True, limit=200, offset=0):
        params = []
        where_parts = []

        if search:
            tok = f"%{search}%"
            where_parts.append(
                "(title LIKE ? OR composer LIKE ? OR arranger LIKE ? "
                "OR genre LIKE ? OR ensemble_type LIKE ? "
                "OR key_signature LIKE ? OR COALESCE(voicing,'') LIKE ?)"
            )
            params.extend([tok] * 7)

        if genre:
            where_parts.append("genre=?")
            params.append(genre)

        if voicing:
            where_parts.append("voicing=?")
            params.append(voicing)

        # works has no location column — ignore that filter
        where_sql = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""

        _col_map = {"difficulty": "grade_numeric", "last_played": "title",
                    "time_signature": "time_signature", "ensemble_type": "ensemble_type"}
        actual_col = _col_map.get(order_col, order_col)
        valid = {"title", "composer", "arranger", "ensemble_type", "genre",
                 "grade", "grade_numeric", "key_signature", "time_signature", "voicing"}
        if actual_col not in valid:
            actual_col = "title"
        direction = "ASC" if order_asc else "DESC"

        data_sql = (f"SELECT * FROM works {where_sql} "
                    f"ORDER BY {actual_col} {direction} LIMIT ? OFFSET ?")
        count_sql = f"SELECT COUNT(*) FROM works {where_sql}"

        with self._connect() as conn:
            total = conn.execute(count_sql, params).fetchone()[0]
            rows = conn.execute(data_sql, params + [limit, offset]).fetchall()
        return [self._row_to_dict(r) for r in rows], total

    def get_distinct_genres(self) -> list:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT DISTINCT genre FROM works "
                "WHERE genre IS NOT NULL AND genre != '' ORDER BY genre"
            ).fetchall()
        return [r[0] for r in rows]

    def get_distinct_voicings(self) -> list:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT DISTINCT voicing FROM works "
                "WHERE voicing IS NOT NULL AND voicing != '' ORDER BY voicing"
            ).fetchall()
        return [r[0] for r in rows]

    def get_distinct_locations(self) -> list:
        return []

    def get_sheet_music(self, music_id: int):
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM works WHERE id=?", (music_id,)).fetchone()
        return self._row_to_dict(row) if row else None

    def get_all_sheet_music(self, include_inactive=True):
        return []

    def get_latest_omr_job(self, music_id):
        return None

    def get_omr_jobs(self, music_id):
        return []

    def get_performances(self, music_id):
        return []


class MusicManager(ttk.Frame):
    def __init__(self, parent, db, base_dir: str, mode: str = "band"):
        super().__init__(parent)
        self.db = db
        self._main_db = db   # always the profile's own DB
        self.base_dir = base_dir
        self.mode = mode  # "band" or "choir"
        if mode == "band":
            self._show_external_var = tk.BooleanVar(value=False)

        # Pick column config for this mode
        if mode == "choir":
            self._treeview_cols    = CHOIR_TREEVIEW_COLS
            self._col_headers      = CHOIR_COL_HEADERS
            self._col_widths       = CHOIR_COL_WIDTHS
            self._col_hidden_def   = CHOIR_COL_HIDDEN_DEFAULT
            self._col_prefs_file   = "choir_column_prefs.json"
        else:
            self._treeview_cols    = BAND_TREEVIEW_COLS
            self._col_headers      = BAND_COL_HEADERS
            self._col_widths       = BAND_COL_WIDTHS
            self._col_hidden_def   = BAND_COL_HIDDEN_DEFAULT
            self._col_prefs_file   = "music_column_prefs.json"

        self._all_rows = []        # current page's rows
        self._selected_id = None
        self._sort_col = "title"
        self._sort_asc = True
        self._page = 0
        self._page_size = 200
        self._total_count = 0
        self._search_var = tk.StringVar()
        self._filter_genre = tk.StringVar(value="All")
        self._filter_voicing = tk.StringVar(value="All")
        self._filter_location = tk.StringVar(value="All")
        self._col_vars = {
            c: tk.BooleanVar(value=(c not in self._col_hidden_def))
            for c in self._treeview_cols
        }
        self._col_popup = None
        self._chat_window = None
        self._search_debounce_id = None
        self._detail_debounce_id = None

        self._build()
        self._load_col_prefs()
        self._apply_col_visibility()
        self.refresh()

    # ──────────────────────────────────────────────────────── Build UI ─────

    def _build(self):
        # ── Toolbar ───────────────────────────────────────────────────────
        toolbar = ttk.Frame(self, bootstyle=LIGHT)
        toolbar.pack(fill=X, padx=0, pady=0)

        self._add_btn = ttk.Button(toolbar, text="Add Music", bootstyle=SUCCESS,
                                   command=self._add_music)
        self._add_btn.pack(side=LEFT, padx=6, pady=6)
        self._import_btn = ttk.Button(toolbar, text="Import Music", bootstyle=(SUCCESS, OUTLINE),
                                      command=self._import_music)
        self._import_btn.pack(side=LEFT, padx=2, pady=6)
        self._edit_btn = ttk.Button(toolbar, text="Edit", bootstyle=PRIMARY,
                                    command=self._edit_music)
        self._edit_btn.pack(side=LEFT, padx=2, pady=6)
        self._delete_btn = ttk.Button(toolbar, text="Delete", bootstyle=DANGER,
                                      command=self._delete_selected, state=DISABLED)
        self._delete_btn.pack(side=LEFT, padx=2, pady=6)

        # OMR buttons hidden — OMR not currently in use
        self._omr_btn = ttk.Button(toolbar, text="Process OMR", bootstyle=WARNING,
                                   command=self._process_omr, state=DISABLED)
        self._export_btn = ttk.Button(toolbar, text="Export MusicXML", bootstyle=INFO,
                                      command=self._export_musicxml, state=DISABLED)

        self._validate_btn = ttk.Button(toolbar, text="Validate with LLM",
                                        bootstyle=(INFO, OUTLINE),
                                        command=self._validate_with_llm, state=DISABLED)
        self._validate_btn.pack(side=LEFT, padx=2, pady=6)

        ttk.Separator(toolbar, orient=VERTICAL).pack(
            side=LEFT, fill=Y, padx=8, pady=4)

        ttk.Button(toolbar, text="Refresh", bootstyle=(SECONDARY, OUTLINE),
                   command=self.refresh).pack(side=LEFT, padx=2, pady=6)

        if self.mode == "band":
            ttk.Separator(toolbar, orient=VERTICAL).pack(
                side=LEFT, fill=Y, padx=8, pady=4)
            ttk.Checkbutton(
                toolbar, text="Show External Source",
                variable=self._show_external_var,
                bootstyle=PRIMARY,
                command=self._toggle_external_source,
            ).pack(side=LEFT, padx=2, pady=6)
            self._ext_source_label = ttk.Label(
                toolbar, text="", foreground="#888", font=("Segoe UI", 8))
            self._ext_source_label.pack(side=LEFT, padx=(0, 6), pady=6)

        # ── Search / Filter Bar ───────────────────────────────────────────
        filter_bar = ttk.Frame(self)
        filter_bar.pack(fill=X, padx=8, pady=(4, 2))

        ttk.Label(filter_bar, text="Search:").pack(side=LEFT, padx=(0, 4))
        search_entry = ttk.Entry(filter_bar, textvariable=self._search_var,
                                 width=28)
        search_entry.pack(side=LEFT, padx=(0, 10))
        self._search_var.trace_add("write", lambda *_: self._debounce_search())

        if self.mode == "choir":
            ttk.Label(filter_bar, text="Voicing:").pack(side=LEFT, padx=(0, 4))
            self._voicing_combo = ttk.Combobox(
                filter_bar, textvariable=self._filter_voicing,
                state="readonly", width=10
            )
            self._voicing_combo.pack(side=LEFT, padx=(0, 10))
            self._filter_voicing.trace_add("write", lambda *_: self._apply_filters())
        else:
            ttk.Label(filter_bar, text="Genre:").pack(side=LEFT, padx=(0, 4))
            self._genre_combo = ttk.Combobox(
                filter_bar, textvariable=self._filter_genre,
                state="readonly", width=14
            )
            self._genre_combo.pack(side=LEFT, padx=(0, 10))
            self._filter_genre.trace_add("write", lambda *_: self._apply_filters())

        ttk.Label(filter_bar, text="Location:").pack(side=LEFT, padx=(0, 4))
        self._location_combo = ttk.Combobox(
            filter_bar, textvariable=self._filter_location,
            state="readonly", width=18
        )
        self._location_combo.pack(side=LEFT, padx=(0, 10))
        self._filter_location.trace_add("write", lambda *_: self._apply_filters())

        self._col_btn = ttk.Button(
            filter_bar, text="Columns \u25bc",
            bootstyle=(SECONDARY, OUTLINE), width=10,
            command=lambda: self._show_col_chooser(self._col_btn)
        )
        self._col_btn.pack(side=RIGHT, padx=(0, 4))

        self._count_label = ttk.Label(filter_bar, text="", foreground=muted_fg())
        self._count_label.pack(side=RIGHT, padx=6)

        # ── Main Content: Tree + Detail Panel ─────────────────────────────
        paned = ttk.Panedwindow(self, orient=HORIZONTAL)
        paned.pack(fill=BOTH, expand=True, padx=6, pady=4)

        # Left: Treeview
        tree_frame = ttk.Frame(paned)
        paned.add(tree_frame, weight=3)

        scrollbar_y = ttk.Scrollbar(tree_frame, orient=VERTICAL)
        scrollbar_x = ttk.Scrollbar(tree_frame, orient=HORIZONTAL)

        self.tree = ttk.Treeview(
            tree_frame,
            columns=self._treeview_cols,
            show="headings",
            yscrollcommand=scrollbar_y.set,
            xscrollcommand=scrollbar_x.set,
            selectmode="extended",
            bootstyle=INFO,
        )
        scrollbar_y.config(command=self.tree.yview)
        scrollbar_x.config(command=self.tree.xview)

        # Pagination bar — packed before tree so it gets fixed height at bottom
        page_bar = ttk.Frame(tree_frame)
        self._prev_btn = ttk.Button(
            page_bar, text="◀ Prev", bootstyle=(PRIMARY, OUTLINE), width=7,
            command=self._on_prev_page
        )
        self._prev_btn.pack(side=LEFT, padx=(4, 2), pady=3)
        self._next_btn = ttk.Button(
            page_bar, text="Next ▶", bootstyle=(PRIMARY, OUTLINE), width=7,
            command=self._on_next_page
        )
        self._next_btn.pack(side=LEFT, padx=2, pady=3)
        self._page_label = ttk.Label(page_bar, text="", foreground=muted_fg(),
                                     font=("Segoe UI", 8))
        self._page_label.pack(side=LEFT, padx=8)

        scrollbar_y.pack(side=RIGHT, fill=Y)
        scrollbar_x.pack(side=BOTTOM, fill=X)
        page_bar.pack(side=BOTTOM, fill=X)
        self.tree.pack(fill=BOTH, expand=True)

        _STRETCH = {"title", "composer", "arranger", "location"}
        for col in self._treeview_cols:
            self.tree.heading(
                col, text=self._col_headers[col], anchor=W,
                command=lambda c=col: self._sort_by(c)
            )
            self.tree.column(col, width=self._col_widths[col], anchor=W,
                             minwidth=40, stretch=col in _STRETCH)

        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.bind("<Double-1>", self._on_dbl_click)

        # Right: Detail Panel
        detail_frame = ttk.Frame(paned, width=320)
        paned.add(detail_frame, weight=1)

        self._detail_nb = ttk.Notebook(detail_frame, bootstyle=INFO)
        self._detail_nb.pack(fill=BOTH, expand=True)

        self._detail_tab = ttk.Frame(self._detail_nb)
        self._perf_tab = ttk.Frame(self._detail_nb)
        self._omr_tab = ttk.Frame(self._detail_nb)
        self._history_tab = ttk.Frame(self._detail_nb)

        self._detail_nb.add(self._detail_tab, text="Details")
        self._detail_nb.add(self._perf_tab, text="Performances")
        # OMR Results and Job History tabs hidden — OMR not currently in use

        self._build_detail_tab()
        self._build_perf_tab()
        self._build_omr_tab()
        self._build_history_tab()

        # ── AI Chat Footer ─────────────────────────────────────────────────
        footer = ttk.Frame(self)
        footer.pack(fill=X, side=BOTTOM)
        ttk.Separator(footer).pack(fill=X)
        ttk.Button(
            footer,
            text="🎩 Ask Reginald",
            bootstyle=(DARK, OUTLINE),
            command=self._open_chat,
        ).pack(side=RIGHT, padx=10, pady=5)
        self._status_label = ttk.Label(footer, text="", foreground=muted_fg(),
                                       font=("Segoe UI", 9))
        self._status_label.pack(side=LEFT, padx=12, pady=5)

        # ── Resize performance: suppress right-panel cascade during window resize ──
        # When the window is resized, tkinter cascades Configure events through every
        # nested widget. The right panel (Notebook → Canvas → ~20 labels) is the slow
        # path. Hiding it during active resize stops the cascade; it's restored 150ms
        # after the last resize event.
        self._resize_restore_id = None

        def _on_resize(e):
            if e.widget is not self:
                return
            if self._resize_restore_id is None:
                self._detail_nb.pack_forget()
            else:
                try:
                    self.after_cancel(self._resize_restore_id)
                except Exception:
                    pass
            self._resize_restore_id = self.after(150, _restore_detail)

        def _restore_detail():
            self._resize_restore_id = None
            self._detail_nb.pack(fill=BOTH, expand=True)

        self.bind("<Configure>", _on_resize)

    def _build_detail_tab(self):
        canvas = tk.Canvas(self._detail_tab, highlightthickness=0)
        sb = ttk.Scrollbar(self._detail_tab, orient=VERTICAL, command=canvas.yview)
        canvas.configure(yscrollcommand=sb.set)
        sb.pack(side=RIGHT, fill=Y)
        canvas.pack(fill=BOTH, expand=True)

        outer = ttk.Frame(canvas)
        _cw = canvas.create_window((0, 0), window=outer, anchor=NW)

        # Track labels that need dynamic wraplength: (widget, num_columns)
        self._detail_wrap_info = []
        self._detail_resize_id = None

        def _do_resize():
            self._detail_resize_id = None
            w = canvas.winfo_width()
            canvas.itemconfig(_cw, width=w)
            canvas.configure(scrollregion=canvas.bbox("all"))
            pad = 24
            for lbl, n in getattr(self, "_detail_wrap_info", []):
                col_w = max(60, (w - pad) // n - 8)
                try:
                    lbl.configure(wraplength=col_w)
                except tk.TclError:
                    pass

        def _resize(e=None):
            if self._detail_resize_id is not None:
                try:
                    self.after_cancel(self._detail_resize_id)
                except Exception:
                    pass
            self._detail_resize_id = self.after(16, _do_resize)

        outer.bind("<Configure>", _resize)
        canvas.bind("<Configure>", _resize)

        def _wheel(e):
            try:
                canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
            except tk.TclError:
                pass
        canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", _wheel))
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))

        self._detail_labels = {}
        _muted = muted_fg()

        def _section(title):
            f = ttk.Frame(outer)
            f.pack(fill=X, padx=8, pady=(14, 4))
            ttk.Label(f, text=title, font=("Segoe UI", fs(9), "bold"),
                      bootstyle=PRIMARY).pack(side=LEFT)
            ttk.Separator(f).pack(side=LEFT, fill=X, expand=True, padx=(6, 2))

        def _row(*pairs):
            r = ttk.Frame(outer)
            r.pack(fill=X, padx=10, pady=(0, 10))
            n = len(pairs)
            for i in range(n):
                r.columnconfigure(i, weight=1, uniform="cols")
            for i, (label, key) in enumerate(pairs):
                col = ttk.Frame(r)
                col.grid(row=0, column=i, sticky="new", padx=(0, 8))
                ttk.Label(col, text=label, font=("Segoe UI", fs(8), "bold"),
                          foreground=_muted).pack(anchor=W)
                fnt = ("Segoe UI", fs(13)) if key == "title" else ("Segoe UI", fs(10))
                lbl = ttk.Label(col, text="", font=fnt,
                                anchor=W, wraplength=280, justify=LEFT)
                lbl.pack(anchor=W)
                bind_copy_menu(lbl)
                self._detail_labels[key] = lbl
                self._detail_wrap_info.append((lbl, n))

        _section("Basic")
        _row(("Title", "title"))
        _row(("Composer", "composer"), ("Arranger", "arranger"))
        _row(("Publisher", "publisher"))

        _section("Classification")
        if self.mode == "choir":
            _row(("Genre", "genre"), ("Voicing", "voicing"))
            _row(("Language", "language"), ("Accompaniment", "accompaniment"))
            _row(("Difficulty", "difficulty"), ("Key", "key_signature"))
        else:
            _row(("Genre", "genre"), ("Ensemble", "ensemble_type"))
            _row(("Difficulty", "difficulty"), ("Time Sig", "time_signature"))
            _row(("Key", "key_signature"))

        _section("Details")
        _row(("Location", "location"))
        _row(("Source File", "source_file"))

        _section("Comments")
        cf = ttk.Frame(outer)
        cf.pack(fill=X, padx=10, pady=(0, 16))
        notes_lbl = ttk.Label(cf, text="", font=("Segoe UI", fs(10)),
                              anchor=NW, wraplength=280, justify=LEFT)
        notes_lbl.pack(anchor=W)
        self._detail_labels["notes"] = notes_lbl
        self._detail_wrap_info.append((notes_lbl, 1))

    def _build_perf_tab(self):
        frame = ttk.Frame(self._perf_tab)
        frame.pack(fill=BOTH, expand=True)

        btn_row = ttk.Frame(frame)
        btn_row.pack(fill=X, padx=8, pady=(8, 4))
        ttk.Button(btn_row, text="Add Performance", bootstyle=SUCCESS,
                   command=self._add_performance).pack(side=LEFT, padx=2)
        ttk.Button(btn_row, text="Edit", bootstyle=(PRIMARY, OUTLINE),
                   command=self._edit_performance).pack(side=LEFT, padx=2)
        ttk.Button(btn_row, text="Delete", bootstyle=(DANGER, OUTLINE),
                   command=self._delete_performance).pack(side=LEFT, padx=2)

        cols = ("Date", "Ensemble", "Event", "Notes")
        sb = ttk.Scrollbar(frame, orient=VERTICAL)
        self._perf_tree = ttk.Treeview(
            frame, columns=cols, show="headings",
            yscrollcommand=sb.set, bootstyle=SUCCESS, height=10
        )
        sb.config(command=self._perf_tree.yview)
        sb.pack(side=RIGHT, fill=Y)
        self._perf_tree.pack(fill=BOTH, expand=True, padx=8, pady=(0, 8))

        widths = [100, 120, 150, 150]
        for col, w in zip(cols, widths):
            self._perf_tree.heading(col, text=col, anchor=W)
            self._perf_tree.column(col, width=w, anchor=W,
                                   minwidth=40, stretch=col in ("Event", "Notes"))

    def _build_omr_tab(self):
        frame = ttk.Frame(self._omr_tab)
        frame.pack(fill=BOTH, expand=True)

        self._omr_summary = ttk.Label(
            frame, text="Select a piece to see OMR results",
            font=("Segoe UI", 9), foreground=muted_fg()
        )
        self._omr_summary.pack(anchor=W, padx=8, pady=(8, 4))

        cols = ("Type", "Measure", "Part", "Message")
        sb = ttk.Scrollbar(frame, orient=VERTICAL)
        self._omr_tree = ttk.Treeview(
            frame, columns=cols, show="headings",
            yscrollcommand=sb.set, bootstyle=WARNING, height=14
        )
        sb.config(command=self._omr_tree.yview)
        sb.pack(side=RIGHT, fill=Y)
        self._omr_tree.pack(fill=BOTH, expand=True, padx=8, pady=(0, 8))

        widths = [60, 60, 100, 280]
        for col, w in zip(cols, widths):
            self._omr_tree.heading(col, text=col, anchor=W)
            self._omr_tree.column(col, width=w, anchor=W,
                                  minwidth=40, stretch=col == "Message")

        self._omr_tree.tag_configure("error", foreground="#CC0000")
        self._omr_tree.tag_configure("warning", foreground="#B8860B")
        self._omr_tree.tag_configure("info", foreground="#1a7a1a")
        self._omr_tree.tag_configure("correction", foreground="#0066CC")

    def _build_history_tab(self):
        frame = ttk.Frame(self._history_tab)
        frame.pack(fill=BOTH, expand=True)

        cols = ("Date", "Engine", "Status", "Output")
        sb = ttk.Scrollbar(frame, orient=VERTICAL)
        self._history_tree = ttk.Treeview(
            frame, columns=cols, show="headings",
            yscrollcommand=sb.set, bootstyle=SECONDARY, height=10
        )
        sb.config(command=self._history_tree.yview)
        sb.pack(side=RIGHT, fill=Y)
        self._history_tree.pack(fill=BOTH, expand=True, padx=8, pady=8)

        widths = [130, 80, 80, 200]
        for col, w in zip(cols, widths):
            self._history_tree.heading(col, text=col, anchor=W)
            self._history_tree.column(col, width=w, anchor=W,
                                      minwidth=40, stretch=col == "Output")

        self._history_tree.tag_configure("completed", foreground="#1a7a1a")
        self._history_tree.tag_configure("failed", foreground="#CC0000")

    # ──────────────────────────────────────────── Column Preferences ──────

    def _load_col_prefs(self):
        path = os.path.join(self.base_dir, self._col_prefs_file)
        try:
            with open(path) as f:
                prefs = json.load(f)
            for col, var in self._col_vars.items():
                if col in prefs:
                    var.set(bool(prefs[col]))
        except (FileNotFoundError, json.JSONDecodeError):
            pass

    def _save_col_prefs(self):
        path = os.path.join(self.base_dir, self._col_prefs_file)
        try:
            with open(path, "w") as f:
                json.dump({c: v.get() for c, v in self._col_vars.items()}, f, indent=2)
        except Exception:
            pass

    def _apply_col_visibility(self):
        visible = [c for c in self._treeview_cols if self._col_vars[c].get()]
        self.tree["displaycolumns"] = visible

    def _show_col_chooser(self, btn):
        if self._col_popup and self._col_popup.winfo_exists():
            self._col_popup.destroy()
            self._col_popup = None
            return

        popup = tk.Toplevel(self)
        popup.wm_overrideredirect(True)
        popup.wm_attributes("-topmost", True)
        self._col_popup = popup

        bx = btn.winfo_rootx()
        by = btn.winfo_rooty() + btn.winfo_height()
        popup.geometry(f"+{bx}+{by}")

        outer = ttk.Frame(popup, relief="solid", borderwidth=1)
        outer.pack(fill=BOTH, expand=True)

        ttk.Label(outer, text="Show Columns",
                  font=("Segoe UI", 9, "bold")).pack(anchor=W, padx=10, pady=(8, 2))
        ttk.Separator(outer, orient=HORIZONTAL).pack(fill=X, padx=6, pady=2)

        for col in self._treeview_cols:
            ttk.Checkbutton(
                outer,
                text=self._col_headers[col],
                variable=self._col_vars[col],
                command=lambda: (self._apply_col_visibility(), self._save_col_prefs())
            ).pack(anchor=W, padx=10, pady=1)

        ttk.Separator(outer, orient=HORIZONTAL).pack(fill=X, padx=6, pady=(4, 2))

        btn_row = ttk.Frame(outer)
        btn_row.pack(fill=X, padx=10, pady=(2, 8))

        def _show_all():
            for var in self._col_vars.values():
                var.set(True)
            self._apply_col_visibility()
            self._save_col_prefs()

        ttk.Button(btn_row, text="Show All", bootstyle=(SECONDARY, OUTLINE),
                   command=_show_all).pack(side=LEFT)
        ttk.Button(btn_row, text="Done", bootstyle=PRIMARY,
                   command=popup.destroy).pack(side=RIGHT)

        root = self.winfo_toplevel()
        _bid = [None]

        def _check_outside(event):
            try:
                if not popup.winfo_exists():
                    if _bid[0]:
                        root.unbind("<Button-1>", _bid[0])
                    return
                px, py = popup.winfo_rootx(), popup.winfo_rooty()
                pw, ph = popup.winfo_width(), popup.winfo_height()
                if not (px <= event.x_root <= px + pw and
                        py <= event.y_root <= py + ph):
                    popup.destroy()
                    self._col_popup = None
                    if _bid[0]:
                        root.unbind("<Button-1>", _bid[0])
            except Exception:
                pass

        def _setup_binding():
            _bid[0] = root.bind("<Button-1>", _check_outside, add="+")

        popup.after(150, _setup_binding)

    # ───────────────────────────────────────────────────── Data Loading ────

    def refresh(self):
        """Reload filter dropdowns and current page from DB (preserves page/filters)."""
        if self.mode == "choir":
            self._update_voicing_filter()
        else:
            self._update_genre_filter()
        self._update_location_filter()
        self._load_page()
        if self._selected_id:
            self._restore_selection()

    def _update_genre_filter(self):
        genres = self.db.get_distinct_genres()
        self._genre_combo["values"] = ["All"] + genres
        if self._filter_genre.get() not in ["All"] + genres:
            self._filter_genre.set("All")

    def _update_voicing_filter(self):
        voicings = self.db.get_distinct_voicings()
        self._voicing_combo["values"] = ["All"] + voicings
        if self._filter_voicing.get() not in ["All"] + voicings:
            self._filter_voicing.set("All")

    def _update_location_filter(self):
        locations = self.db.get_distinct_locations()
        self._location_combo["values"] = ["All"] + locations
        if self._filter_location.get() not in ["All"] + locations:
            self._filter_location.set("All")

    def _debounce_search(self):
        if self._search_debounce_id is not None:
            self.after_cancel(self._search_debounce_id)
        self._search_debounce_id = self.after(300, self._apply_filters)

    def _apply_filters(self):
        """Called when search text or filter dropdowns change — resets to page 0."""
        self._search_debounce_id = None
        self._load_page(reset_page=True)

    def _load_page(self, reset_page: bool = False):
        """Query the DB for the current page and populate the treeview."""
        if reset_page:
            self._page = 0

        search = self._search_var.get().strip().lower()
        location_f = self._filter_location.get()

        if self.mode == "choir":
            voicing_f = self._filter_voicing.get()
            query_kwargs = dict(
                search=search,
                voicing="" if voicing_f == "All" else voicing_f,
                location="" if location_f == "All" else location_f,
                order_col=self._sort_col,
                order_asc=self._sort_asc,
                limit=self._page_size,
                offset=self._page * self._page_size,
            )
        else:
            genre_f = self._filter_genre.get()
            query_kwargs = dict(
                search=search,
                genre="" if genre_f == "All" else genre_f,
                location="" if location_f == "All" else location_f,
                order_col=self._sort_col,
                order_asc=self._sort_asc,
                limit=self._page_size,
                offset=self._page * self._page_size,
            )

        rows, total = self.db.search_sheet_music(**query_kwargs)

        self._total_count = total
        # Clamp page if deletions reduced total below current page
        max_page = max(0, (total - 1) // self._page_size)
        if self._page > max_page:
            self._page = max_page
            query_kwargs["offset"] = self._page * self._page_size
            rows, total = self.db.search_sheet_music(**query_kwargs)

        self._all_rows = rows
        self._populate_tree(rows)

        self._count_label.config(text=f"{total} pieces")

        self._update_pagination()
        self._update_status_label()

    def _populate_tree(self, rows):
        self.tree.delete(*self.tree.get_children())
        for row in rows:
            if self.mode == "choir":
                values = (
                    row.get("title") or "",
                    row.get("composer") or "",
                    row.get("arranger") or "",
                    row.get("voicing") or "",
                    row.get("language") or "",
                    row.get("genre") or "",
                    row.get("difficulty") or "",
                    row.get("key_signature") or "",
                    row.get("location") or "",
                    row.get("last_played") or "",
                    row.get("file_type") or "",
                    os.path.basename(row.get("source_file") or ""),
                )
            else:
                values = (
                    row["title"] or "",
                    row["composer"] or "",
                    row["arranger"] or "",
                    row["ensemble_type"] or "",
                    row["genre"] or "",
                    row["difficulty"] or "",
                    row.get("key_signature") or "",
                    row.get("time_signature") or "",
                    row.get("location") or "",
                    row.get("last_played") or "",
                    row["file_type"] or "",
                    os.path.basename(row.get("source_file") or ""),
                )
            iid = str(row["id"])
            self.tree.insert("", "end", iid=iid, values=values)

    def _sort_by(self, col: str):
        if self._sort_col == col:
            self._sort_asc = not self._sort_asc
        else:
            self._sort_col = col
            self._sort_asc = True
        self._apply_filters()

    def _restore_selection(self):
        iid = str(self._selected_id)
        if self.tree.exists(iid):
            self.tree.selection_set(iid)
            self.tree.see(iid)

    # ──────────────────────────────────────────────────── Detail Panel ─────

    def _on_select(self, event=None):
        sel = self.tree.selection()
        n = len(sel)

        # Immediate cheap updates — no DB calls
        multi_state = NORMAL if n >= 1 else DISABLED
        self._delete_btn.config(state=multi_state)
        self._validate_btn.config(state=multi_state)
        self._update_status_label()

        if not sel:
            self._omr_btn.config(state=DISABLED)
            self._export_btn.config(state=DISABLED)
            return

        self._selected_id = int(sel[-1])

        # Debounce the detail panel — defer DB work until scrolling pauses
        if self._detail_debounce_id is not None:
            self.after_cancel(self._detail_debounce_id)
        self._detail_debounce_id = self.after(150, self._load_detail_deferred)

    def _load_detail_deferred(self):
        self._detail_debounce_id = None
        if self._selected_id is None:
            return
        piece = next((r for r in self._all_rows if r["id"] == self._selected_id), None)
        has_file = bool(piece and piece.get("file_path"))
        state = NORMAL if has_file else DISABLED
        self._omr_btn.config(state=state)
        self._export_btn.config(state=state)
        if self._chat_window and self._chat_window.winfo_exists():
            self._chat_window.update_selected_music(piece)
        self._load_detail(self._selected_id)

    def _on_dbl_click(self, event):
        """Double-click: open source file if that column was clicked, else open edit dialog."""
        col_id = self.tree.identify_column(event.x)  # "#1", "#2", etc.
        display_cols = self.tree["displaycolumns"]
        if not display_cols or display_cols == ("all",):
            display_cols = TREEVIEW_COLS
        try:
            col_name = display_cols[int(col_id.lstrip("#")) - 1]
        except (ValueError, IndexError):
            col_name = ""
        if col_name == "source_file":
            self._open_selected_source_file()
        else:
            self._edit_music()

    def _open_selected_source_file(self):
        sel = self.tree.selection()
        if not sel:
            return
        pid = int(sel[0])
        piece = next((p for p in self._all_rows if p["id"] == pid), None)
        if not piece:
            return
        path = (piece.get("source_file") or "").strip()
        if not path:
            messagebox.showinfo("No Source File", "This piece has no source file set.", parent=self)
            return
        resolved = _resolve_source_file(path, self.base_dir)
        if not resolved:
            messagebox.showwarning("File Not Found", f"Cannot find:\n{path}", parent=self)
            return
        try:
            os.startfile(resolved)
        except Exception as e:
            messagebox.showerror("Cannot Open File", str(e), parent=self)

    def _get_selected_ids(self) -> list[int]:
        """Return list of all selected music IDs."""
        return [int(iid) for iid in self.tree.selection()]

    def _update_status_label(self):
        sel = len(self.tree.selection())
        if sel:
            text = f"{self._total_count} pieces in inventory  •  {sel} selected"
        else:
            text = f"{self._total_count} pieces in inventory"
        self._status_label.config(text=text)

    def _load_detail(self, music_id: int):
        piece = next((r for r in self._all_rows if r["id"] == music_id), None)
        if not piece:
            return

        row = dict(piece)

        # Show just filename for source_file (full path is too long to display)
        sf = row.get("source_file") or ""
        if sf:
            row["source_file"] = os.path.basename(sf)

        for key, lbl in self._detail_labels.items():
            val = row.get(key, "")
            if val is None:
                val = ""
            lbl.config(text=str(val))

        job = self.db.get_latest_omr_job(music_id)
        job = dict(job) if job else None
        self._load_performances(music_id)
        self._load_omr_results(music_id, job)
        self._load_job_history(music_id)

    def _load_omr_results(self, music_id: int, job=None):
        self._omr_tree.delete(*self._omr_tree.get_children())

        if not job:
            self._omr_summary.config(
                text="No OMR results yet. Click 'Process OMR' to start."
            )
            return

        # Load corrections
        corrections = []
        if job.get("corrections_applied"):
            try:
                corrections = json.loads(job["corrections_applied"])
            except (json.JSONDecodeError, TypeError):
                pass

        # Load validation issues
        issues = []
        if job.get("validation_errors"):
            try:
                issues = json.loads(job["validation_errors"])
            except (json.JSONDecodeError, TypeError):
                pass

        if not corrections and not issues:
            self._omr_summary.config(
                text="No OMR results yet. Click 'Process OMR' to start."
            )
            return

        # Build summary
        n_corr = len(corrections)
        n_err = sum(1 for i in issues if i.get("type") == "error")
        n_warn = sum(1 for i in issues if i.get("type") == "warning")

        parts = []
        if n_corr:
            parts.append(f"{n_corr} correction(s) applied")
        if n_err:
            parts.append(f"{n_err} error(s)")
        if n_warn:
            parts.append(f"{n_warn} warning(s)")
        if not n_err and not n_warn and not n_corr:
            parts.append("No issues found")
        self._omr_summary.config(text="Results: " + ", ".join(parts))

        # Display corrections first, then validation issues
        for item in corrections + issues:
            itype = item.get("type", "")
            measure = item.get("measure", 0)
            part = item.get("part", "")
            msg = item.get("message", "")
            measure_str = str(measure) if measure else ""
            self._omr_tree.insert("", "end",
                                  values=(itype.title(), measure_str, part, msg),
                                  tags=(itype,))

    def _load_job_history(self, music_id: int):
        self._history_tree.delete(*self._history_tree.get_children())
        jobs = self.db.get_omr_jobs(music_id)
        for j in jobs:
            output = os.path.basename(j["musicxml_path"]) if j["musicxml_path"] else ""
            tag = j["status"] if j["status"] in ("completed", "failed") else ""
            self._history_tree.insert("", "end", values=(
                j["started_at"] or "",
                j["engine"] or "",
                j["status"] or "",
                output,
            ), tags=(tag,) if tag else ())

    # ───────────────────────────────────────────── Performances ──────────

    def _load_performances(self, music_id: int):
        self._perf_tree.delete(*self._perf_tree.get_children())
        perfs = self.db.get_performances(music_id)
        for p in perfs:
            self._perf_tree.insert("", "end", iid=str(p["id"]), values=(
                p["performance_date"] or "",
                p["ensemble"] or "",
                p["event_name"] or "",
                p["notes"] or "",
            ))

    def _add_performance(self):
        if not self._selected_id:
            Messagebox.show_warning("Select a piece first.", title="No Selection",
                                    parent=self.winfo_toplevel())
            return
        from ui.performance_dialog import PerformanceDialog
        dlg = PerformanceDialog(self.winfo_toplevel(), self.db, self._selected_id, mode=self.mode)
        self.wait_window(dlg)
        if dlg.saved:
            self._load_performances(self._selected_id)

    def _edit_performance(self):
        sel = self._perf_tree.selection()
        if not sel:
            Messagebox.show_warning("Select a performance first.", title="No Selection",
                                    parent=self.winfo_toplevel())
            return
        perf_id = int(sel[0])
        from ui.performance_dialog import PerformanceDialog
        dlg = PerformanceDialog(self.winfo_toplevel(), self.db, self._selected_id,
                                performance_id=perf_id, mode=self.mode)
        self.wait_window(dlg)
        if dlg.saved:
            self._load_performances(self._selected_id)

    def _delete_performance(self):
        sel = self._perf_tree.selection()
        if not sel:
            Messagebox.show_warning("Select a performance first.", title="No Selection",
                                    parent=self.winfo_toplevel())
            return
        perf_id = int(sel[0])
        answer = Messagebox.yesno(
            "Delete this performance record?", title="Confirm Delete",
            parent=self.winfo_toplevel()
        )
        if answer != "Yes":
            return
        self.db.delete_performance(perf_id)
        self._load_performances(self._selected_id)

    # ──────────────────────────────────────────────── Pagination ──────────

    def _on_prev_page(self):
        if self._page > 0:
            self._page -= 1
            self._load_page()
            self.tree.yview_moveto(0)

    def _on_next_page(self):
        total_pages = max(1, (self._total_count + self._page_size - 1) // self._page_size)
        if self._page < total_pages - 1:
            self._page += 1
            self._load_page()
            self.tree.yview_moveto(0)

    def _update_pagination(self):
        total_pages = max(1, (self._total_count + self._page_size - 1) // self._page_size)
        current = self._page + 1
        shown = len(self._all_rows)
        start = self._page * self._page_size + 1
        end = start + shown - 1

        if self._total_count == 0:
            label = "No results"
        elif total_pages == 1:
            label = ""   # count label at top already shows it
        else:
            label = f"{start}–{end} of {self._total_count}  •  Page {current} of {total_pages}"

        self._page_label.config(text=label)
        self._prev_btn.config(state=NORMAL if self._page > 0 else DISABLED)
        self._next_btn.config(state=NORMAL if current < total_pages else DISABLED)

    # ──────────────────────────────────────────────── Action Handlers ──────

    def _get_selected_music(self):
        sel = self.tree.selection()
        if not sel:
            Messagebox.show_warning(
                "Please select a piece first.", title="No Selection",
                parent=self.winfo_toplevel()
            )
            return None
        return int(sel[0])

    def _add_music(self):
        from ui.music_dialog import MusicDialog
        dlg = MusicDialog(self.winfo_toplevel(), self.db,
                          base_dir=self.base_dir, music_id=None, mode=self.mode)
        self.wait_window(dlg)
        self.refresh()

    def _import_music(self):
        from llm_client import is_configured
        if not is_configured(self.base_dir):
            Messagebox.show_warning(
                "No API key configured. Open Settings and enter your GitHub token "
                "to use AI-powered import.",
                title="API Key Required",
                parent=self.winfo_toplevel()
            )
            return

        paths = filedialog.askopenfilenames(
            title="Select Sheet Music Files to Import",
            parent=self.winfo_toplevel(),
            filetypes=[
                ("Image & PDF files", "*.pdf *.png *.jpg *.jpeg *.tiff *.tif *.bmp"),
                ("PDF files", "*.pdf"),
                ("Images", "*.png *.jpg *.jpeg *.tiff *.tif *.bmp"),
                ("All files", "*.*"),
            ],
        )
        if not paths:
            return

        from ui.music_importer import BatchImportDialog, _norm_title

        # Build set of existing titles for duplicate detection
        existing = self.db.get_all_sheet_music()
        existing_titles = {_norm_title(r["title"]) for r in existing if r["title"]}

        dlg = BatchImportDialog(
            self.winfo_toplevel(), list(paths), self.base_dir,
            existing_titles=existing_titles, mode=self.mode,
        )
        self.wait_window(dlg)

        results = dlg.results
        if not results:
            return

        for prefill in results:
            # Strip internal-only keys before saving
            prefill.pop("_duplicate", None)
            self.db.add_sheet_music(prefill)

        self.refresh()
        Messagebox.show_info(
            f"Added {len(results)} piece(s) to your library.",
            title="Import Complete",
            parent=self.winfo_toplevel()
        )

    def _edit_music(self):
        iid = self._get_selected_music()
        if iid is None:
            return
        from ui.music_dialog import MusicDialog
        dlg = MusicDialog(self.winfo_toplevel(), self.db,
                          base_dir=self.base_dir, music_id=iid, mode=self.mode)
        self.wait_window(dlg)
        self.refresh()
        self._load_detail(iid)

    def _delete_selected(self):
        ids = self._get_selected_ids()
        if not ids:
            return
        n = len(ids)

        # Build title list preview (up to 5)
        titles = []
        for mid in ids[:5]:
            row = self.db.get_sheet_music(mid)
            if row:
                titles.append(f"  \u2022 {row['title'] or '(untitled)'}")
        preview = "\n".join(titles)
        if n > 5:
            preview += f"\n  \u2026 and {n - 5} more"

        msg = (
            f"Permanently delete {n} piece(s) from the database?\n\n"
            f"{preview}\n\n"
            "This cannot be undone."
        )
        if n > 1:
            msg += "\n\nA backup of the database will be created first."

        answer = Messagebox.yesno(msg, title="Confirm Delete",
                                  parent=self.winfo_toplevel())
        if answer != "Yes":
            return

        # Backup DB before bulk delete
        if n > 1:
            try:
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                backup_path = self.db.db_path + f".backup_{ts}.db"
                shutil.copy2(self.db.db_path, backup_path)
            except Exception as e:
                Messagebox.show_warning(
                    f"Could not create backup: {e}\nDelete cancelled.",
                    title="Backup Failed",
                    parent=self.winfo_toplevel()
                )
                return

        for mid in ids:
            self.db.delete_sheet_music(mid)

        self._selected_id = None
        self.refresh()

        info = f"Deleted {n} piece(s)."
        if n > 1:
            info += f"\nBackup saved to:\n{backup_path}"
        Messagebox.show_info(info, title="Deleted", parent=self.winfo_toplevel())

    def _validate_with_llm(self):
        ids = self._get_selected_ids()
        if not ids:
            return
        from llm_client import is_configured
        if not is_configured(self.base_dir):
            Messagebox.show_warning(
                "No LLM API key configured. Open Settings and enter a key first.",
                title="API Key Required",
                parent=self.winfo_toplevel()
            )
            return
        pieces = [dict(self.db.get_sheet_music(mid)) for mid in ids
                  if self.db.get_sheet_music(mid)]
        dlg = _LLMValidateDialog(
            self.winfo_toplevel(), self.db, self.base_dir, pieces, mode=self.mode
        )
        self.wait_window(dlg)
        if getattr(dlg, "changes_made", False):
            self.refresh()

    def _process_omr(self):
        iid = self._get_selected_music()
        if iid is None:
            return
        piece = self.db.get_sheet_music(iid)
        if not piece or not piece["file_path"]:
            Messagebox.show_warning(
                "This piece has no source file. Edit it to add one first.",
                title="No File",
                parent=self.winfo_toplevel()
            )
            return
        if not os.path.exists(piece["file_path"]):
            Messagebox.show_warning(
                f"Source file not found:\n{piece['file_path']}",
                title="File Missing",
                parent=self.winfo_toplevel()
            )
            return

        dlg = _OMRProcessDialog(
            self.winfo_toplevel(), self.db, iid, self.base_dir
        )
        self.wait_window(dlg)
        self.refresh()
        self._load_detail(iid)
        # Switch to OMR Results tab after processing
        self._detail_nb.select(self._omr_tab)

    def _export_musicxml(self):
        iid = self._get_selected_music()
        if iid is None:
            return
        _job = self.db.get_latest_omr_job(iid)
        job = dict(_job) if _job else None
        if not job or job["status"] != "completed" or not job.get("musicxml_path"):
            Messagebox.show_warning(
                "No completed OMR output to export.\n"
                "Process the piece first with 'Process OMR'.",
                title="No Output",
                parent=self.winfo_toplevel()
            )
            return
        src = job["musicxml_path"]
        if not os.path.exists(src):
            Messagebox.show_warning(
                f"MusicXML file not found:\n{src}",
                title="File Missing",
                parent=self.winfo_toplevel()
            )
            return

        ext = os.path.splitext(src)[1]
        piece = self.db.get_sheet_music(iid)
        default_name = (piece["title"] if piece else "output") + ext

        dest = filedialog.asksaveasfilename(
            title="Export MusicXML",
            parent=self.winfo_toplevel(),
            defaultextension=ext,
            initialfile=default_name,
            filetypes=[
                ("MusicXML", "*.musicxml *.mxl *.xml"),
                ("All files", "*.*"),
            ],
        )
        if not dest:
            return

        try:
            shutil.copy2(src, dest)
            Messagebox.show_info(
                f"MusicXML exported to:\n{dest}",
                title="Export Complete",
                parent=self.winfo_toplevel()
            )
        except Exception as e:
            Messagebox.show_error(
                f"Failed to export:\n{e}",
                title="Export Error",
                parent=self.winfo_toplevel()
            )


    def _set_action_buttons_state(self, state):
        """Enable or disable the write-action toolbar buttons."""
        for btn in (self._add_btn, self._import_btn, self._edit_btn,
                    self._validate_btn):
            btn.config(state=state)
        # Delete and OMR buttons also depend on selection; just disable fully in external mode
        if state == DISABLED:
            self._delete_btn.config(state=DISABLED)

    def _toggle_external_source(self):
        """Switch between the profile's own DB and an external DB."""
        if not self._show_external_var.get():
            # Unchecked — revert to main DB
            self.db = self._main_db
            self._ext_source_label.config(text="")
            self._set_action_buttons_state(NORMAL)
            self.refresh()
            return

        # Checked — load external DB path from settings
        from ui.settings_dialog import load_settings
        settings = load_settings(self.base_dir)
        ext_path = (settings.get("teacher") or {}).get("external_db_path", "").strip()

        if not ext_path:
            self._show_external_var.set(False)
            Messagebox.show_warning(
                "No external database configured.\n"
                "Go to Settings → Teacher and select a .db file.",
                title="No External Database",
                parent=self.winfo_toplevel(),
            )
            return

        if not os.path.isfile(ext_path):
            self._show_external_var.set(False)
            Messagebox.show_warning(
                f"External database not found:\n{ext_path}",
                title="File Not Found",
                parent=self.winfo_toplevel(),
            )
            return

        try:
            import sqlite3
            _conn = sqlite3.connect(ext_path)
            _tables = {r[0] for r in _conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
            _sheet_count = _conn.execute("SELECT COUNT(*) FROM sheet_music").fetchone()[0] \
                if "sheet_music" in _tables else 0
            _works_count = _conn.execute("SELECT COUNT(*) FROM works").fetchone()[0] \
                if "works" in _tables else 0
            _conn.close()

            if _works_count > 0 and _sheet_count == 0:
                self.db = _WorksCatalogAdapter(ext_path)
            else:
                from database import Database
                self.db = Database(ext_path)
        except Exception as e:
            self._show_external_var.set(False)
            Messagebox.show_error(
                f"Could not open external database:\n{e}",
                title="Error",
                parent=self.winfo_toplevel(),
            )
            return

        self._ext_source_label.config(text=f"({os.path.basename(ext_path)})")
        self._set_action_buttons_state(DISABLED)
        self.refresh()

    def _open_chat(self):
        from ui.chat_dialog import ChatDialog
        if self._chat_window and self._chat_window.winfo_exists():
            self._chat_window.lift()
            self._chat_window.focus_force()
            return
        piece = None
        if self._selected_id:
            row = self.db.get_sheet_music(self._selected_id)
            if row:
                piece = dict(row)
        self._chat_window = ChatDialog(
            self.winfo_toplevel(), self.db, self.base_dir,
            selected_music=piece, mode=self.mode,
        )


# ══════════════════════════════════════════════════════════════════════════════
# OMR Processing Dialog
# ══════════════════════════════════════════════════════════════════════════════

class _OMRProcessDialog(ttk.Toplevel):
    """Modal dialog that runs OMR processing with progress feedback."""

    def __init__(self, parent, db, music_id: int, base_dir: str):
        super().__init__(parent)
        self.db = db
        self.music_id = music_id
        self.base_dir = base_dir
        self._job_id = None

        piece = db.get_sheet_music(music_id)
        self._piece_title = piece["title"] if piece else "Unknown"
        self._file_path = piece["file_path"] if piece else ""

        self.title("OMR Processing")
        self.resizable(True, True)
        self.grab_set()
        self.lift()

        self._build()

        from ui.theme import fit_window
        fit_window(self, 650, 520)

        # Start detection after dialog is visible
        self.after(200, self._detect_engines)

    def _build(self):
        # Header
        hdr = ttk.Frame(self, bootstyle=WARNING)
        hdr.pack(fill=X)
        ttk.Label(
            hdr,
            text=f"  Processing: {self._piece_title}",
            font=("Segoe UI", 12, "bold"),
            bootstyle=(INVERSE, WARNING),
        ).pack(pady=10, padx=16, anchor=W)

        # Engine selection
        eng_frame = ttk.Frame(self)
        eng_frame.pack(fill=X, padx=16, pady=(10, 4))

        ttk.Label(eng_frame, text="Engine:",
                  font=("Segoe UI", 9)).pack(side=LEFT, padx=(0, 6))
        self._engine_var = tk.StringVar()
        self._engine_combo = ttk.Combobox(
            eng_frame, textvariable=self._engine_var,
            state="readonly", width=16
        )
        self._engine_combo.pack(side=LEFT, padx=(0, 10))

        self._start_btn = ttk.Button(
            eng_frame, text="Start Processing", bootstyle=SUCCESS,
            command=self._start_processing, state=DISABLED
        )
        self._start_btn.pack(side=LEFT, padx=4)

        # Progress bar with percentage label
        prog_frame = ttk.Frame(self)
        prog_frame.pack(fill=X, padx=16, pady=(8, 4))

        self._progress_var = tk.IntVar(value=0)
        self._progress = ttk.Progressbar(
            prog_frame, mode="determinate", bootstyle=WARNING,
            variable=self._progress_var, maximum=100
        )
        self._progress.pack(side=LEFT, fill=X, expand=True)

        self._progress_label = ttk.Label(
            prog_frame, text="", font=("Segoe UI", 9),
            width=18, anchor=CENTER
        )
        self._progress_label.pack(side=LEFT, padx=(8, 0))

        # Log area
        log_frame = ttk.Frame(self)
        log_frame.pack(fill=BOTH, expand=True, padx=16, pady=(4, 8))

        log_sb = ttk.Scrollbar(log_frame, orient=VERTICAL)
        self._log = tk.Text(
            log_frame, height=16, font=("Consolas", 9),
            relief="solid", bd=1, wrap=WORD,
            yscrollcommand=log_sb.set, state=DISABLED
        )
        log_sb.config(command=self._log.yview)
        log_sb.pack(side=RIGHT, fill=Y)
        self._log.pack(fill=BOTH, expand=True)

        # Bottom buttons
        btn_frame = ttk.Frame(self)
        btn_frame.pack(fill=X, padx=16, pady=(0, 10))
        self._close_btn = ttk.Button(
            btn_frame, text="Close", bootstyle=(SECONDARY, OUTLINE),
            command=self.destroy
        )
        self._close_btn.pack(side=RIGHT, padx=4)

    def _log_msg(self, msg: str):
        """Append a message to the log (must be called from main thread)."""
        self._log.config(state=NORMAL)
        self._log.insert("end", msg + "\n")
        self._log.see("end")
        self._log.config(state=DISABLED)

    def _detect_engines(self):
        from omr_engine import get_available_engines
        self._log_msg("Detecting available OMR engines...")

        engines = get_available_engines()
        if not engines:
            self._log_msg("")
            self._log_msg("No OMR engines found!")
            self._log_msg("")
            self._log_msg("To use OMR, install one of the following:")
            self._log_msg("  Audiveris (recommended):")
            self._log_msg("    Download from https://github.com/Audiveris/audiveris/releases")
            self._log_msg("    Or set AUDIVERIS_PATH environment variable")
            self._log_msg("")
            self._log_msg("  homr (Python package):")
            self._log_msg("    pip install homr")
            return

        self._engine_combo["values"] = engines
        self._engine_var.set(engines[0])  # Prefer first (audiveris if available)
        self._start_btn.config(state=NORMAL)

        for eng in engines:
            self._log_msg(f"  Found: {eng}")
        self._log_msg("")
        self._log_msg("Select an engine and click 'Start Processing'.")

    def _start_processing(self):
        engine = self._engine_var.get()
        if not engine:
            return

        self._start_btn.config(state=DISABLED)
        self._engine_combo.config(state=DISABLED)
        self._progress_var.set(0)
        self._progress_label.config(text="Starting...")

        self._log_msg(f"Starting {engine} on: {os.path.basename(self._file_path)}")
        self._log_msg("-" * 50)

        # Create job record
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._job_id = self.db.add_omr_job({
            "music_id": self.music_id,
            "engine": engine,
            "status": "processing",
            "started_at": now,
            "notes": "",
        })

        # Run in background thread
        thread = threading.Thread(
            target=self._do_process,
            args=(engine,),
            daemon=True
        )
        thread.start()

    def _update_progress(self, current, total):
        """Update the determinate progress bar (called from main thread)."""
        pct = int(current / total * 100) if total else 0
        self._progress_var.set(pct)
        self._progress_label.config(text=f"Page {current}/{total}  ({pct}%)")

    def _do_process(self, engine: str):
        """Worker thread — runs OMR engine and validation."""
        from omr_engine import process_sheet_music, get_piece_dir

        output_dir = get_piece_dir(self.base_dir, self.music_id)

        def progress_cb(msg):
            # Schedule UI update on main thread
            self.after(0, self._log_msg, msg)

        def progress_pct_cb(current, total):
            # Schedule progress bar update on main thread
            self.after(0, self._update_progress, current, total)

        # Build metadata dict for post-processing corrections
        piece = self.db.get_sheet_music(self.music_id)
        omr_metadata = {
            "title": self._piece_title,
            "num_pages": piece["num_pages"] if piece else None,
        }

        result = process_sheet_music(
            self._file_path, output_dir,
            engine=engine,
            progress_callback=progress_cb,
            progress_percent_callback=progress_pct_cb,
            metadata=omr_metadata
        )

        # Update job record
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.db.update_omr_job(self._job_id, {
            "status": result["status"],
            "musicxml_path": result.get("musicxml_path"),
            "validation_errors": json.dumps(result.get("validation_issues", [])),
            "corrections_applied": json.dumps(result.get("corrections", [])),
            "completed_at": now,
            "notes": result.get("error") or "",
        })

        # Schedule completion on main thread
        self.after(0, self._on_complete, result)

    def _on_complete(self, result: dict):
        """Called on main thread when processing finishes."""
        self._progress_var.set(100)
        if result["status"] == "completed":
            self._progress_label.config(text="Complete!")
        else:
            self._progress_label.config(text="Failed")

        self._log_msg("")
        self._log_msg("=" * 50)

        if result["status"] == "completed":
            self._log_msg("OMR PROCESSING COMPLETE")
            path = result.get("musicxml_path", "")
            if path:
                self._log_msg(f"Output: {os.path.basename(path)}")

            corrections = result.get("corrections", [])
            if corrections:
                self._log_msg(
                    f"Corrections applied: {len(corrections)}"
                )
                for corr in corrections[:10]:
                    m = corr.get("measure", "")
                    p = corr.get("part", "")
                    loc = f"m.{m}" if m else ""
                    if p:
                        loc = f"{p} {loc}" if loc else p
                    self._log_msg(
                        f"  [FIX] {loc}: {corr.get('message', '')}"
                    )
                if len(corrections) > 10:
                    self._log_msg(
                        f"  ... and {len(corrections) - 10} more"
                    )
                self._log_msg("")

            issues = result.get("validation_issues", [])
            n_err = sum(1 for i in issues if i.get("type") == "error")
            n_warn = sum(1 for i in issues if i.get("type") == "warning")
            self._log_msg(f"Validation: {n_err} error(s), {n_warn} warning(s)")

            if issues:
                self._log_msg("")
                for iss in issues[:10]:
                    prefix = iss.get("type", "").upper()
                    m = iss.get("measure", "")
                    p = iss.get("part", "")
                    loc = f"m.{m}" if m else ""
                    if p:
                        loc = f"{p} {loc}" if loc else p
                    self._log_msg(f"  [{prefix}] {loc}: {iss.get('message', '')}")
                if len(issues) > 10:
                    self._log_msg(f"  ... and {len(issues) - 10} more")
        else:
            self._log_msg("OMR PROCESSING FAILED")
            self._log_msg(f"Error: {result.get('error', 'Unknown')}")

        self._log_msg("=" * 50)
        self._log_msg("You may close this dialog.")


# ══════════════════════════════════════════════════════════════════════════════
# LLM Validation Dialog
# ══════════════════════════════════════════════════════════════════════════════

def _resolve_source_file(path: str, base_dir: str) -> str | None:
    """Return the resolved path to a source image, or None if not found."""
    if not path:
        return None
    if os.path.isfile(path):
        return path
    # Try just the filename in known MusicPics folders under the program dir,
    # then the profile data dir as a fallback
    fname = os.path.basename(path)
    for root in [_APP_DIR, base_dir]:
        for folder in _MUSIC_PICS_FOLDERS:
            candidate = os.path.join(root, folder, fname)
            if os.path.isfile(candidate):
                return candidate
    return None


def _load_image_b64(path: str) -> dict | None:
    """Load an image file as a base64 dict for LLM vision calls.

    Saves as JPEG (not PNG) so photos stay well under the 5 MB API limit.
    Steps down quality until the encoded size fits if needed.
    """
    try:
        import base64, io
        from PIL import Image
        img = Image.open(path).convert("RGB")
        w, h = img.size
        scale = min(1.0, 3000 / max(w, h))
        if scale < 1.0:
            img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
        _MAX_BYTES = 4_500_000
        buf = io.BytesIO()
        for quality in (92, 80, 65, 50):
            buf.seek(0)
            buf.truncate()
            img.save(buf, format="JPEG", quality=quality, optimize=True)
            if buf.tell() <= _MAX_BYTES:
                break
        return {
            "mime_type": "image/jpeg",
            "data": base64.b64encode(buf.getvalue()).decode(),
        }
    except Exception:
        return None


class _LLMValidateDialog(ttk.Toplevel):
    """
    Validates selected pieces against their source images using the LLM.

    For each unique source image among the selected pieces:
      - Checks whether each piece is actually visible in the image
      - Checks if title/composer look correct
      - Identifies any pieces visible but NOT in the database
    Low-confidence results are cross-checked with backup models.
    """

    _BACKUP_MODELS = ["claude-opus-4-6", "openai/gpt-4o"]

    def __init__(self, parent, db, base_dir: str, pieces: list[dict], mode: str = "band"):
        super().__init__(parent)
        self.db = db
        self.base_dir = base_dir
        self._mode = mode
        self.pieces = pieces  # selected piece dicts
        self.changes_made = False

        self.title("Validate with LLM")
        self.resizable(True, True)
        self.grab_set()
        self.lift()

        self._build()

        from ui.theme import fit_window
        fit_window(self, 700, 540)

        self.after(200, self._start_validation)

    def _build(self):
        hdr = ttk.Frame(self, bootstyle=SECONDARY)
        hdr.pack(fill=X)
        ttk.Label(
            hdr,
            text=f"  Validating {len(self.pieces)} piece(s) with LLM...",
            font=("Segoe UI", 11, "bold"),
            bootstyle=(INVERSE, SECONDARY),
        ).pack(pady=10, padx=16, anchor=W)

        prog_frame = ttk.Frame(self)
        prog_frame.pack(fill=X, padx=16, pady=(10, 4))
        self._progress_var = tk.IntVar(value=0)
        self._progress = ttk.Progressbar(
            prog_frame, mode="determinate", bootstyle=INFO,
            variable=self._progress_var, maximum=100,
        )
        self._progress.pack(side=LEFT, fill=X, expand=True)
        self._pct_label = ttk.Label(prog_frame, text="", width=12, anchor=CENTER)
        self._pct_label.pack(side=LEFT, padx=(8, 0))

        log_frame = ttk.Frame(self)
        log_frame.pack(fill=BOTH, expand=True, padx=16, pady=(4, 8))
        log_sb = ttk.Scrollbar(log_frame, orient=VERTICAL)
        self._log = tk.Text(
            log_frame, height=18, font=("Consolas", 9),
            relief="solid", bd=1, wrap=WORD,
            yscrollcommand=log_sb.set, state=DISABLED,
        )
        log_sb.config(command=self._log.yview)
        log_sb.pack(side=RIGHT, fill=Y)
        self._log.pack(fill=BOTH, expand=True)

        btn_frame = ttk.Frame(self)
        btn_frame.pack(fill=X, padx=16, pady=(0, 10))
        self._close_btn = ttk.Button(
            btn_frame, text="Close", bootstyle=(SECONDARY, OUTLINE),
            command=self.destroy
        )
        self._close_btn.pack(side=RIGHT, padx=4)
        self._review_btn = ttk.Button(
            btn_frame, text="Review Suggestions", bootstyle=SUCCESS,
            command=self._open_review, state=DISABLED,
        )
        self._review_btn.pack(side=RIGHT, padx=4)

        self._suggestions = []  # populated by worker thread

    def _log_msg(self, msg: str):
        self._log.config(state=NORMAL)
        self._log.insert("end", msg + "\n")
        self._log.see("end")
        self._log.config(state=DISABLED)

    def _set_progress(self, pct: int, label: str = ""):
        self._progress_var.set(pct)
        self._pct_label.config(text=label)

    def _start_validation(self):
        threading.Thread(target=self._do_validate, daemon=True).start()

    @staticmethod
    def _norm(t: str) -> str:
        import re
        return re.sub(r"[^a-z0-9]", "", (t or "").lower())

    def _do_validate(self):
        import llm_client
        from ui.settings_dialog import load_settings

        settings = load_settings(self.base_dir)
        current_model = (settings.get("llm") or {}).get("model", llm_client.DEFAULT_MODEL)
        github_key = llm_client._get_api_key(self.base_dir)
        anthropic_key = llm_client._get_anthropic_key(self.base_dir)

        # Build full-DB title set for "missing" filtering
        all_db_rows = [dict(r) for r in self.db.get_all_sheet_music()]
        db_titles_norm = {self._norm(r["title"]) for r in all_db_rows if r["title"]}

        # Tracks pieces whose identity (title/composer/arranger) was corrected by
        # image validation — those pieces will be re-enriched using the corrected values.
        # Maps piece_id → piece dict with corrections applied.
        identity_corrected: dict[int, dict] = {}

        # Group pieces by source_file
        by_image: dict[str, list[dict]] = {}
        no_source = []
        for p in self.pieces:
            sf = p.get("source_file") or ""
            resolved = _resolve_source_file(sf, self.base_dir)
            if resolved:
                by_image.setdefault(resolved, []).append(p)
            else:
                no_source.append(p)

        total_images = len(by_image)
        all_suggestions: list[dict] = []

        self.after(0, self._log_msg, f"Selected: {len(self.pieces)} pieces across {total_images} image(s).")
        if no_source:
            names = ", ".join(p.get("title","?") for p in no_source[:5])
            if len(no_source) > 5:
                names += f" + {len(no_source)-5} more"
            self.after(0, self._log_msg,
                       f"Skipping {len(no_source)} piece(s) with no/missing source image: {names}")
        self.after(0, self._log_msg, "")

        for img_idx, (img_path, img_pieces) in enumerate(by_image.items()):
            pct = int(img_idx / total_images * 90)
            self.after(0, self._set_progress, pct, f"{img_idx+1}/{total_images}")
            self.after(0, self._log_msg,
                       f"[{img_idx+1}/{total_images}] {os.path.basename(img_path)}")

            img_dict = _load_image_b64(img_path)
            if not img_dict:
                self.after(0, self._log_msg,
                           "  Could not load image (PIL not available or bad file). Skipping.")
                continue

            # Build prompt — focused on what's visible in the image
            piece_list = "\n".join(
                f"  ID {p['id']}: title=\"{p.get('title','')}\", "
                f"composer=\"{p.get('composer','')}\", arranger=\"{p.get('arranger','')}\""
                for p in img_pieces
            )
            _inventory_type = "choir/choral music" if self._mode == "choir" else "band sheet music"
            system_prompt = (
                f"You are a meticulous music librarian verifying a school {_inventory_type} inventory "
                "using photographs. Your primary job is accurate visual text recognition.\n\n"
                "KEY RULES:\n"
                "- Music covers use many fonts: script, italic, decorative, hand-lettered, embossed, "
                "  outlined, shadowed. Read ALL text regardless of style.\n"
                "- A piece is found=true if the SAME MUSICAL WORK is visible, even if the exact "
                "  spelling or subtitle differs slightly from the database record.\n"
                "- Only mark found=false when you have examined the entire image carefully and the "
                "  work is genuinely absent — not merely hard to read.\n"
                "- When uncertain between found=true and found=false, choose found=true and lower "
                "  your confidence score instead.\n"
                "- Your note field must explain your reasoning, especially for found=false.\n\n"
                "PUBLISHER SERIES vs. PIECE TITLE:\n"
                "- 'Easy Jazz Ensemble', 'Jazz Ensemble', 'Discovery Jazz', 'Jazz Band', "
                "'Concert Band', 'Flex-Band', 'Young Band' etc. are PUBLISHER SERIES NAMES — "
                "they are NOT the piece title.\n"
                "- The actual piece title is typically the SMALLER text printed above, below, "
                "or alongside the series branding.\n"
                "- 'Words and Music by ...', 'Arranged by ...', 'arr. ...' identify the "
                "composer/arranger — they are not part of the title.\n"
                "- Publisher names (Hal Leonard, Carl Fischer, Alfred, Kendor, etc.) are also "
                "not titles."
            )
            prompt = (
                "Examine this photograph of sheet music materials carefully.\n\n"
                f"These pieces are recorded in our database as coming from this image:\n{piece_list}\n\n"
                "Step 1 — Read all visible text in the image: covers, spines, stickers, stamps, "
                "labels, and any handwriting. Note every title and name you can make out.\n\n"
                "Step 2 — For EACH listed piece, determine:\n"
                "1. Is this work visible anywhere in the image? (found: true/false)\n"
                "   Tip: compare against every title you read in Step 1. "
                "   Match even if font is decorative, cursive, or stylized.\n"
                "2. Does the title look correct? If you can read a different title, provide it.\n"
                "3. Does the composer look correct? If you can read a different name, provide it.\n"
                "4. Does the arranger look correct? If visible and different, provide it.\n"
                "5. Confidence (0.0–1.0): 0.95+ means you directly read the title clearly; "
                "   0.8 = fairly sure; 0.6 = partly obscured but recognisable; "
                "   below 0.6 = very uncertain.\n\n"
                "Step 3 — List any musical works visible in the image that are NOT in the list above.\n\n"
                "Return ONLY valid JSON (no markdown fences):\n"
                "{\n"
                '  "pieces": [\n'
                '    {"id": <id>, "found": true/false, "confidence": 0.0-1.0,\n'
                '     "suggested_title": "<corrected title or null>",\n'
                '     "suggested_composer": "<corrected composer or null>",\n'
                '     "suggested_arranger": "<corrected arranger or null>",\n'
                '     "note": "<explain what you saw and why found=true/false>"}\n'
                "  ],\n"
                '  "missing_from_db": [\n'
                '    {"title": "<title>", "composer": "<composer or empty>", "arranger": "<arranger or empty>", "note": "<where you saw it>"}\n'
                "  ]\n"
                "}"
            )

            primary_result = self._call_llm_vision(
                prompt, img_dict, current_model, github_key, anthropic_key,
                system_prompt=system_prompt,
            )

            if primary_result is None:
                self.after(0, self._log_msg, "  LLM call failed. Skipping this image.")
                continue

            # Cross-check low-confidence pieces with backup models
            low_conf_ids = {
                p["id"] for p in primary_result.get("pieces", [])
                if p.get("confidence", 1.0) < 0.85 or p.get("found") is False
            }
            if low_conf_ids:
                self.after(0, self._log_msg,
                           f"  Low confidence on {len(low_conf_ids)} piece(s) — cross-checking...")
                backup_results = self._cross_check(
                    prompt, img_dict, current_model, github_key, anthropic_key,
                    system_prompt=system_prompt,
                )
                primary_result = self._merge_results(primary_result, backup_results)

            _EXTRA_FIELDS = [
                "suggested_title", "suggested_composer", "suggested_arranger",
                "suggested_genre", "suggested_key_signature", "suggested_time_signature",
                "suggested_difficulty", "suggested_ensemble_type",
            ]

            # Log summary
            for p in primary_result.get("pieces", []):
                conf = p.get("confidence", 1.0)
                found = p.get("found", True)
                pid = p.get("id")
                orig = next((x for x in img_pieces if x["id"] == pid), {})
                title = orig.get("title", f"ID {pid}")
                has_suggestions = any(p.get(f) for f in _EXTRA_FIELDS)
                if not found:
                    self.after(0, self._log_msg,
                               f"  NOT FOUND: \"{title}\" (conf={conf:.0%})")
                elif has_suggestions:
                    self.after(0, self._log_msg,
                               f"  CORRECTION: \"{title}\" → see suggestions (conf={conf:.0%})")
                else:
                    self.after(0, self._log_msg,
                               f"  OK: \"{title}\" (conf={conf:.0%})")

            # Filter "missing" pieces against the FULL database
            raw_missing = primary_result.get("missing_from_db", [])
            truly_missing = []
            already_in_db = []
            for m in raw_missing:
                if self._norm(m.get("title", "")) in db_titles_norm:
                    already_in_db.append(m)
                else:
                    truly_missing.append(m)

            if already_in_db:
                self.after(0, self._log_msg,
                           f"  Already in DB (skipped): {len(already_in_db)} piece(s)")
                for m in already_in_db:
                    self.after(0, self._log_msg,
                               f"    \"{m.get('title','')}\" — already tracked in database")

            if truly_missing:
                self.after(0, self._log_msg,
                           f"  FOUND IN IMAGE BUT NOT IN DB: {len(truly_missing)} piece(s)")
                for m in truly_missing:
                    self.after(0, self._log_msg,
                               f"    \"{m.get('title','')}\" by {m.get('composer','')}")

            # Collect suggestions
            for p in primary_result.get("pieces", []):
                pid = p.get("id")
                orig = next((x for x in img_pieces if x["id"] == pid), {})
                if not p.get("found", True):
                    all_suggestions.append({
                        "type": "not_found",
                        "id": pid,
                        "title": orig.get("title", ""),
                        "composer": orig.get("composer", ""),
                        "note": p.get("note", ""),
                        "confidence": p.get("confidence", 0.5),
                        "image": os.path.basename(img_path),
                    })
                elif any(p.get(f) for f in _EXTRA_FIELDS):
                    all_suggestions.append({
                        "type": "correction",
                        "id": pid,
                        "current_title": orig.get("title", ""),
                        "current_composer": orig.get("composer", ""),
                        "current_arranger": orig.get("arranger", ""),
                        "current_genre": orig.get("genre", ""),
                        "current_key_signature": orig.get("key_signature", ""),
                        "current_time_signature": orig.get("time_signature", ""),
                        "current_difficulty": orig.get("difficulty", ""),
                        "current_ensemble_type": orig.get("ensemble_type", ""),
                        "suggested_title": p.get("suggested_title"),
                        "suggested_composer": p.get("suggested_composer"),
                        "suggested_arranger": p.get("suggested_arranger"),
                        "suggested_genre": p.get("suggested_genre"),
                        "suggested_key_signature": p.get("suggested_key_signature"),
                        "suggested_time_signature": p.get("suggested_time_signature"),
                        "suggested_difficulty": p.get("suggested_difficulty"),
                        "suggested_ensemble_type": p.get("suggested_ensemble_type"),
                        "note": p.get("note", ""),
                        "confidence": p.get("confidence", 0.8),
                        "image": os.path.basename(img_path),
                    })
                    # If identity fields were corrected, build an updated piece dict
                    # so text enrichment re-checks all other fields under the new identity.
                    if pid and any(p.get(f) for f in (
                        "suggested_title", "suggested_composer", "suggested_arranger"
                    )):
                        corrected = dict(orig)
                        for skey, dbkey in [
                            ("suggested_title",    "title"),
                            ("suggested_composer", "composer"),
                            ("suggested_arranger", "arranger"),
                        ]:
                            if p.get(skey):
                                corrected[dbkey] = p[skey]
                        identity_corrected[pid] = corrected

            for m in truly_missing:
                all_suggestions.append({
                    "type": "missing",
                    "title": m.get("title", ""),
                    "composer": m.get("composer", ""),
                    "arranger": m.get("arranger", ""),
                    "note": m.get("note", ""),
                    "image": os.path.basename(img_path),
                    "image_path": img_path,
                })

            self.after(0, self._log_msg, "")

        # Duplicate detection: only check titles touched by this validation run —
        # the selected pieces' original titles, plus any corrected titles suggested above.
        self.after(0, self._log_msg, "Checking for duplicate entries in database...")
        if self._mode == "choir":
            _SCORE_FIELDS = [
                "composer", "arranger", "genre", "difficulty",
                "key_signature", "voicing", "language", "location",
            ]
        else:
            _SCORE_FIELDS = [
                "composer", "arranger", "genre", "difficulty",
                "key_signature", "time_signature", "ensemble_type", "location",
            ]

        def _detail_score(p):
            return sum(1 for f in _SCORE_FIELDS if (p.get(f) or "").strip())

        # Collect normalized titles from selected pieces (original + any suggested corrections)
        touched_titles: set[str] = set()
        for p in self.pieces:
            t = self._norm(p.get("title", ""))
            if t:
                touched_titles.add(t)
        for s in all_suggestions:
            for key in ("suggested_title", "title"):
                t = self._norm(s.get(key, ""))
                if t:
                    touched_titles.add(t)

        title_groups: dict[str, list] = {}
        for row in all_db_rows:
            key = self._norm(row.get("title", ""))
            if key and key in touched_titles:
                title_groups.setdefault(key, []).append(row)

        dup_groups = {k: v for k, v in title_groups.items() if len(v) >= 2}
        dup_count = 0

        if not dup_groups:
            self.after(0, self._log_msg, "No duplicate titles found.")
        else:
            self.after(0, self._log_msg,
                       f"  {len(dup_groups)} title(s) with multiple entries — validating with LLM...")

        import llm_client as _lc, re as _re, json as _json

        for gi, (norm_title, group) in enumerate(dup_groups.items()):
            ref = group[0]
            ref_title = ref.get("title", "")
            composer_str = (ref.get("composer") or "").strip() or "unknown composer"
            self.after(0, self._log_msg,
                       f"  [{gi+1}/{len(dup_groups)}] \"{ref_title}\" — {len(group)} entries")

            # Build entry summary for the LLM
            entry_lines = []
            for e in group:
                parts = [f"ID {e['id']}:"]
                if self._mode == "choir":
                    dup_fields = ("arranger", "voicing", "language", "genre", "difficulty", "key_signature")
                else:
                    dup_fields = ("arranger", "ensemble_type", "genre", "difficulty",
                                  "key_signature", "time_signature")
                for f in dup_fields:
                    v = (e.get(f) or "").strip()
                    parts.append(f'{f}="{v}"' if v else f'{f}=(blank)')
                entry_lines.append("  " + "  ".join(parts))

            if self._mode == "choir":
                _inv_label = "school choir/choral music inventory"
                _knowledge_label = "published choral music"
            else:
                _inv_label = "school band sheet music inventory"
                _knowledge_label = "published band and jazz ensemble music"

            dup_prompt = (
                f"You are a music librarian validating a {_inv_label}.\n\n"
                f"The following {len(group)} database entries all share the title "
                f'"{ref_title}" by {composer_str}. Some may be legitimate distinct published '
                "arrangements; others may be duplicate or erroneous entries.\n\n"
                "Entries:\n" + "\n".join(entry_lines) + "\n\n"
                f"Using your knowledge of {_knowledge_label}:\n"
                "1. Identify each entry as VALID (a real published arrangement) or "
                "DUPLICATE/INVALID (erroneously entered, blank arranger that duplicates "
                "another, or an arranger who never published this piece).\n"
                "2. If two entries are the same arrangement entered twice, mark the one "
                "with fewer details as duplicate_of the better one.\n"
                "3. If an arranger name looks misspelled or incomplete, provide the correction.\n\n"
                "Return ONLY valid JSON (no markdown fences):\n"
                '{"entries":[\n'
                '  {"id":<id>,"valid":true/false,'
                '"suggested_arranger":"<corrected name or null>",'
                '"duplicate_of":<id or null>,'
                '"note":"<brief reasoning>"}\n'
                "]}"
            )

            result = None
            try:
                raw = _lc.query(self.base_dir, dup_prompt)
                raw = _re.sub(r"```(?:json)?\s*", "", raw).strip().rstrip("`").strip()
                m = _re.search(r"\{[\s\S]+\}", raw)
                if m:
                    result = _json.loads(m.group(0))
            except Exception as e:
                self.after(0, self._log_msg, f"    LLM error: {e} — using field-count fallback")

            if result:
                for er in result.get("entries", []):
                    eid = er.get("id")
                    orig = next((x for x in group if x["id"] == eid), None)
                    if not orig:
                        continue
                    is_valid = er.get("valid", True)
                    dup_of = er.get("duplicate_of")
                    sugg_arr = (er.get("suggested_arranger") or "").strip() or None
                    note = er.get("note", "")

                    if not is_valid or dup_of:
                        keeper = next((x for x in group if x["id"] == dup_of), None)
                        all_suggestions.append({
                            "type": "duplicate",
                            "id": eid,
                            "keeper_id": dup_of,
                            "title": orig.get("title", ""),
                            "composer": orig.get("composer", ""),
                            "keeper_title": keeper.get("title", "") if keeper else "",
                            "keeper_composer": keeper.get("composer", "") if keeper else "",
                            "dup_score": _detail_score(orig),
                            "keeper_score": _detail_score(keeper) if keeper else 0,
                            "missing_fields": [],
                            "confidence": 0.85,
                            "note": note,
                        })
                        dup_count += 1
                        self.after(0, self._log_msg, f"    DUPLICATE ID {eid}: {note}")
                    else:
                        # Valid — check if arranger needs correcting
                        if sugg_arr and sugg_arr != (orig.get("arranger") or "").strip():
                            all_suggestions.append({
                                "type": "correction",
                                "id": eid,
                                "current_title": orig.get("title", ""),
                                "current_composer": orig.get("composer", ""),
                                "current_arranger": orig.get("arranger", ""),
                                "current_genre": orig.get("genre", ""),
                                "current_key_signature": orig.get("key_signature", ""),
                                "current_time_signature": orig.get("time_signature", ""),
                                "current_difficulty": orig.get("difficulty", ""),
                                "current_ensemble_type": orig.get("ensemble_type", ""),
                                "suggested_arranger": sugg_arr,
                                "note": f"From duplicate analysis: {note}",
                                "confidence": 0.8,
                                "image": "",
                            })
                            self.after(0, self._log_msg,
                                       f"    VALID ID {eid} — arranger correction: → {sugg_arr}")
                        else:
                            self.after(0, self._log_msg, f"    VALID ID {eid}: {note}")
            else:
                # LLM unavailable — fall back to field-count scoring
                scored = sorted(group, key=_detail_score, reverse=True)
                keeper = scored[0]
                for dup in scored[1:]:
                    missing = [
                        f for f in _SCORE_FIELDS
                        if (keeper.get(f) or "").strip() and not (dup.get(f) or "").strip()
                    ]
                    all_suggestions.append({
                        "type": "duplicate",
                        "id": dup["id"],
                        "keeper_id": keeper["id"],
                        "title": dup.get("title", ""),
                        "composer": dup.get("composer", ""),
                        "keeper_title": keeper.get("title", ""),
                        "keeper_composer": keeper.get("composer", ""),
                        "dup_score": _detail_score(dup),
                        "keeper_score": _detail_score(keeper),
                        "missing_fields": missing,
                        "confidence": 0.5,
                        "note": "LLM unavailable — based on field count only, verify manually",
                    })
                    dup_count += 1

        if dup_count:
            self.after(0, self._log_msg,
                       f"Found {dup_count} duplicate/invalid entry(s) — see suggestions")
        self.after(0, self._log_msg, "")

        # Location: always "Chinook Middle School" — only ever changed manually.
        # Suggest correction for any piece not already set to this value.
        _DEFAULT_LOCATION = "Chinook Middle School"
        loc_count = 0
        for p in self.pieces:
            if (p.get("location") or "").strip() != _DEFAULT_LOCATION:
                all_suggestions.append({
                    "type": "correction",
                    "id": p["id"],
                    "current_title": p.get("title", ""),
                    "current_composer": p.get("composer", ""),
                    "current_arranger": p.get("arranger", ""),
                    "current_genre": p.get("genre", ""),
                    "current_key_signature": p.get("key_signature", ""),
                    "current_time_signature": p.get("time_signature", ""),
                    "current_difficulty": p.get("difficulty", ""),
                    "current_ensemble_type": p.get("ensemble_type", ""),
                    "suggested_location": _DEFAULT_LOCATION,
                    "note": "Location auto-filled (all music is at Chinook Middle School)",
                    "confidence": 1.0,
                    "image": "",
                })
                loc_count += 1
        if loc_count:
            self.after(0, self._log_msg,
                       f"Location: {loc_count} piece(s) not set to 'Chinook Middle School' — will suggest correction")

        # Text-based enrichment: for pieces missing metadata fields OR whose identity
        # (title/composer/arranger) was corrected by image validation — re-verify all
        # other fields using the (possibly corrected) title/composer as the lookup key.
        if self._mode == "choir":
            _ENRICH_TRIGGER = ["difficulty", "key_signature", "voicing", "language", "genre"]
        else:
            _ENRICH_TRIGGER = ["difficulty", "key_signature", "time_signature", "genre", "ensemble_type"]
        pieces_to_enrich = [
            p for p in self.pieces
            if any(not (p.get(f) or "").strip() for f in _ENRICH_TRIGGER)
            or p["id"] in identity_corrected
        ]
        if pieces_to_enrich:
            self.after(0, self._log_msg, "")
            self.after(0, self._log_msg,
                       f"Text enrichment: looking up metadata for {len(pieces_to_enrich)} piece(s)...")
            try:
                if self._mode == "choir":
                    from ui.music_importer import _enrich_piece_choir as _enrich_fn
                else:
                    from ui.music_importer import _enrich_piece as _enrich_fn
            except ImportError:
                _enrich_fn = None

            if _enrich_fn:
                _CONF_MAP = {"high": 0.9, "medium": 0.7, "low": 0.4}
                if self._mode == "choir":
                    _ENRICH_FIELDS = [
                        ("suggested_title",          "title"),
                        ("suggested_composer",        "composer"),
                        ("suggested_arranger",        "arranger"),
                        ("suggested_genre",           "genre"),
                        ("suggested_key_signature",   "key_signature"),
                        ("suggested_voicing",         "voicing"),
                        ("suggested_language",        "language"),
                        ("suggested_accompaniment",   "accompaniment"),
                        ("suggested_difficulty",      "difficulty"),
                    ]
                else:
                    _ENRICH_FIELDS = [
                        ("suggested_title",          "title"),
                        ("suggested_composer",        "composer"),
                        ("suggested_arranger",        "arranger"),
                        ("suggested_genre",           "genre"),
                        ("suggested_key_signature",   "key_signature"),
                        ("suggested_time_signature",  "time_signature"),
                        ("suggested_difficulty",      "difficulty"),
                        ("suggested_ensemble_type",   "ensemble_type"),
                    ]
                for i, p in enumerate(pieces_to_enrich):
                    pct = int(90 + i / len(pieces_to_enrich) * 9)
                    self.after(0, self._set_progress, pct,
                               f"Enriching {i+1}/{len(pieces_to_enrich)}")
                    # Use corrected identity if available
                    piece_for_enrich = identity_corrected.get(p["id"], p)
                    label = piece_for_enrich.get("title") or p.get("title", "")
                    reason = " (identity corrected)" if p["id"] in identity_corrected else ""
                    self.after(0, self._log_msg,
                               f"  [{i+1}/{len(pieces_to_enrich)}] \"{label}\"{reason}")
                    try:
                        enriched = _enrich_fn(piece_for_enrich, self.base_dir)
                        conf_str = str(enriched.get("confidence", "")).lower()
                        conf_val = _CONF_MAP.get(conf_str, 0.7)
                        sug = {
                            "type": "correction",
                            "id": p["id"],
                            "current_title": p.get("title", ""),
                            "current_composer": p.get("composer", ""),
                            "current_arranger": p.get("arranger", ""),
                            "current_genre": p.get("genre", ""),
                            "current_key_signature": p.get("key_signature", ""),
                            "current_time_signature": p.get("time_signature", ""),
                            "current_difficulty": p.get("difficulty", ""),
                            "current_ensemble_type": p.get("ensemble_type", ""),
                            "note": f"Text enrichment (LLM knowledge base, confidence: {conf_str or 'unknown'})",
                            "confidence": conf_val,
                            "image": "",
                        }
                        has_changes = False
                        for skey, dbkey in _ENRICH_FIELDS:
                            enriched_val = str(enriched.get(dbkey) or "").strip()
                            current_val = str(p.get(dbkey) or "").strip()
                            # Only suggest if enriched has a value AND it differs from current
                            if enriched_val and enriched_val != current_val:
                                sug[skey] = enriched_val
                                has_changes = True
                        if has_changes:
                            all_suggestions.append(sug)
                            filled = [lbl for skey, dbkey in _ENRICH_FIELDS
                                      if sug.get(skey)
                                      for lbl in [dbkey]]
                            self.after(0, self._log_msg,
                                       f"    → suggestions: {', '.join(filled)}")
                        else:
                            self.after(0, self._log_msg, "    → no new data found")
                    except Exception as e:
                        self.after(0, self._log_msg, f"    → enrichment error: {e}")

        self._suggestions = all_suggestions
        self.after(0, self._on_done)

    def _call_llm_vision(self, prompt, img_dict, model, github_key, anthropic_key,
                         system_prompt=None):
        """Call the LLM with vision and parse JSON. Returns dict or None."""
        import llm_client, re, json as _json

        def _parse(text):
            # Strip markdown fences if present
            text = re.sub(r"```(?:json)?\s*", "", text).strip().rstrip("`").strip()
            m = re.search(r"\{[\s\S]+\}", text)
            if m:
                try:
                    return _json.loads(m.group(0))
                except Exception:
                    pass
            return None

        def _is_content_filter_error(e) -> bool:
            msg = str(e).lower()
            return "content filter" in msg or "content_filter" in msg or "content filtering" in msg

        try:
            try:
                if llm_client._is_anthropic_model(model):
                    if not anthropic_key:
                        self.after(0, self._log_msg,
                                   "  No Anthropic API key configured — skipping.")
                        return None
                    text = llm_client._query_with_images_anthropic(
                        self.base_dir, model, prompt, [img_dict],
                        system_prompt=system_prompt, max_tokens=4096,
                    )
                else:
                    if not github_key:
                        self.after(0, self._log_msg,
                                   "  No GitHub API key configured — skipping.")
                        return None
                    text = llm_client.query_with_images(
                        self.base_dir, prompt, [img_dict],
                        system_prompt=system_prompt, max_tokens=4096,
                    )
            except Exception as e:
                if not _is_content_filter_error(e):
                    raise
                # Content filter blocked — try the other backend
                if llm_client._is_anthropic_model(model) and github_key:
                    fallback = "openai/gpt-4o"
                    self.after(0, self._log_msg,
                               f"  Content filter blocked — retrying with {fallback}...")
                    from openai import OpenAI
                    msgs = []
                    if system_prompt:
                        msgs.append({"role": "system", "content": system_prompt})
                    msgs.append({"role": "user", "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {
                            "url": f"data:{img_dict['mime_type']};base64,{img_dict['data']}"
                        }},
                    ]})
                    text = OpenAI(base_url=llm_client.ENDPOINT, api_key=github_key)\
                        .chat.completions.create(
                            model=fallback, messages=msgs,
                            max_tokens=4096, temperature=0.2,
                        ).choices[0].message.content
                elif not llm_client._is_anthropic_model(model) and anthropic_key:
                    fallback = llm_client.ANTHROPIC_MODELS[1]  # claude-sonnet
                    self.after(0, self._log_msg,
                               f"  Content filter blocked — retrying with {fallback}...")
                    text = llm_client._query_with_images_anthropic(
                        self.base_dir, fallback, prompt, [img_dict],
                        system_prompt=system_prompt, max_tokens=4096,
                    )
                else:
                    raise  # no fallback available
            result = _parse(text)
            if result is None:
                preview = text[:200].replace("\n", " ") if text else "(empty)"
                self.after(0, self._log_msg,
                           f"  Could not parse JSON from response: {preview}")
            return result
        except Exception as e:
            self.after(0, self._log_msg, f"  LLM error: {e}")
            return None

    def _cross_check(self, prompt, img_dict, current_model, github_key, anthropic_key,
                     system_prompt=None):
        """Run 1–2 backup model checks, return list of result dicts."""
        import llm_client
        results = []
        for backup in self._BACKUP_MODELS:
            if backup == current_model:
                continue
            if llm_client._is_anthropic_model(backup) and not anthropic_key:
                continue
            if not llm_client._is_anthropic_model(backup) and not github_key:
                continue
            # Temporarily call with explicit model
            try:
                if llm_client._is_anthropic_model(backup):
                    import llm_client as _lc
                    text = _lc._query_with_images_anthropic(
                        self.base_dir, backup, prompt, [img_dict],
                        system_prompt=system_prompt,
                    )
                else:
                    from openai import OpenAI
                    client = OpenAI(base_url=llm_client.ENDPOINT, api_key=github_key)
                    messages = []
                    if system_prompt:
                        messages.append({"role": "system", "content": system_prompt})
                    content = [{"type": "text", "text": prompt}]
                    content.append({
                        "type": "image_url",
                        "image_url": {"url": f"data:{img_dict['mime_type']};base64,{img_dict['data']}"},
                    })
                    messages.append({"role": "user", "content": content})
                    resp = client.chat.completions.create(
                        model=backup,
                        messages=messages,
                        max_tokens=2048,
                        temperature=0.2,
                    )
                    text = resp.choices[0].message.content
                import re, json as _json
                text = re.sub(r"```(?:json)?\s*", "", text).strip().rstrip("`").strip()
                m = re.search(r"\{[\s\S]+\}", text)
                if m:
                    r = _json.loads(m.group(0))
                    results.append(r)
            except Exception:
                pass
        return results

    def _merge_results(self, primary: dict, backups: list[dict]) -> dict:
        """Merge backup checks into primary result, boosting/dampening confidence."""
        if not backups:
            return primary
        all_results = [primary] + backups
        merged_pieces = {}
        for result in all_results:
            for p in result.get("pieces", []):
                pid = p.get("id")
                if pid not in merged_pieces:
                    merged_pieces[pid] = []
                merged_pieces[pid].append(p)

        merged = dict(primary)
        new_pieces = []
        for pid, versions in merged_pieces.items():
            if len(versions) == 1:
                new_pieces.append(versions[0])
                continue
            # Average confidence; if majority say "found=False", keep that
            avg_conf = sum(v.get("confidence", 0.8) for v in versions) / len(versions)
            found_votes = sum(1 for v in versions if v.get("found", True))
            found = found_votes > len(versions) / 2
            # Use the primary's suggested fields unless all backups agree on different
            base = versions[0].copy()
            base["confidence"] = round(avg_conf, 2)
            base["found"] = found
            new_pieces.append(base)

        merged["pieces"] = new_pieces
        # Union of missing_from_db across all results (dedupe by title)
        seen_titles = set()
        all_missing = []
        for result in all_results:
            for m in result.get("missing_from_db", []):
                t = (m.get("title") or "").lower().strip()
                if t and t not in seen_titles:
                    seen_titles.add(t)
                    all_missing.append(m)
        merged["missing_from_db"] = all_missing
        return merged

    def _on_done(self):
        self._set_progress(100, "Done")
        n = len(self._suggestions)
        if n == 0:
            self._log_msg("No suggestions — everything looks correct!")
        else:
            self._log_msg(f"Found {n} suggestion(s). Click 'Review Suggestions' to apply fixes.")
            self._review_btn.config(state=NORMAL)

    def _open_review(self):
        if not self._suggestions:
            return
        dlg = _FixSuggestionsDialog(
            self.winfo_toplevel(), self.db, self.base_dir, self._suggestions
        )
        self.wait_window(dlg)
        if getattr(dlg, "changes_made", False):
            self.changes_made = True


# ══════════════════════════════════════════════════════════════════════════════
# Fix Suggestions Dialog
# ══════════════════════════════════════════════════════════════════════════════

class _FixSuggestionsDialog(ttk.Toplevel):
    """Shows LLM validation suggestions grouped by type with apply options."""

    def __init__(self, parent, db, base_dir: str, suggestions: list[dict]):
        super().__init__(parent)
        self.db = db
        self.base_dir = base_dir
        self.suggestions = suggestions
        self.changes_made = False
        self._check_vars: list[tk.BooleanVar] = []

        self.title("LLM Validation Suggestions")
        self.resizable(True, True)
        self.grab_set()
        self.lift()

        self._build()

        from ui.theme import fit_window
        fit_window(self, 820, 640)

    def _build(self):
        hdr = ttk.Frame(self, bootstyle=SUCCESS)
        hdr.pack(fill=X)
        ttk.Label(
            hdr,
            text=f"  {len(self.suggestions)} Suggestion(s) — Review and Apply",
            font=("Segoe UI", 11, "bold"),
            bootstyle=(INVERSE, SUCCESS),
        ).pack(pady=10, padx=16, anchor=W)

        # Scrollable suggestion list
        canvas_frame = ttk.Frame(self)
        canvas_frame.pack(fill=BOTH, expand=True, padx=12, pady=(8, 4))

        canvas = tk.Canvas(canvas_frame, borderwidth=0, highlightthickness=0)
        vsb = ttk.Scrollbar(canvas_frame, orient=VERTICAL, command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side=RIGHT, fill=Y)
        canvas.pack(side=LEFT, fill=BOTH, expand=True)

        inner = ttk.Frame(canvas)
        inner_id = canvas.create_window((0, 0), window=inner, anchor="nw")

        def _on_configure(event):
            canvas.configure(scrollregion=canvas.bbox("all"))
            canvas.itemconfig(inner_id, width=canvas.winfo_width())

        inner.bind("<Configure>", _on_configure)
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(inner_id, width=e.width))

        def _on_wheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        canvas.bind_all("<MouseWheel>", _on_wheel)
        self.bind("<Destroy>", lambda e: canvas.unbind_all("<MouseWheel>"))

        # Group suggestions
        groups = [
            ("not_found",  "Pieces NOT found in image", DANGER),
            ("duplicate",  "Possible duplicate entries", WARNING),
            ("correction", "Suggested corrections", WARNING),
            ("missing",    "Pieces found in image but missing from database", INFO),
        ]

        self._check_vars.clear()
        self._suggestion_meta: list[dict] = []  # parallel to _check_vars

        for gtype, glabel, gstyle in groups:
            items = sorted(
                (s for s in self.suggestions if s["type"] == gtype),
                key=lambda s: s.get("confidence", 1.0),
            )
            if not items:
                continue

            ttk.Label(inner, text=glabel,
                      font=("Segoe UI", 10, "bold"),
                      bootstyle=gstyle).pack(anchor=W, padx=8, pady=(12, 2))
            ttk.Separator(inner, orient=HORIZONTAL).pack(fill=X, padx=8, pady=(0, 4))

            for s in items:
                row = ttk.Frame(inner)
                row.pack(fill=X, padx=8, pady=2)

                var = tk.BooleanVar(value=True)
                self._check_vars.append(var)
                self._suggestion_meta.append(s)

                cb = ttk.Checkbutton(row, variable=var, bootstyle=gstyle)
                cb.pack(side=LEFT, padx=(0, 6))

                if gtype == "not_found":
                    desc = (
                        f"NOT FOUND  \"{s.get('title','')}\" by {s.get('composer','')}\n"
                        f"  Image: {s.get('image','')}  Confidence: {s.get('confidence',0):.0%}"
                    )
                    if s.get("note"):
                        desc += f"\n  Note: {s['note']}"
                    action_lbl = "Deactivate in DB"
                elif gtype == "duplicate":
                    missing = s.get("missing_fields", [])
                    lines = [
                        f"DUPLICATE  \"{s.get('title','')}\"  (ID {s.get('id','')})",
                        f"  Keep: ID {s.get('keeper_id','')} \"{s.get('keeper_title','')}\" "
                        f"({s.get('keeper_score',0)} fields filled)",
                        f"  This entry: {s.get('dup_score',0)} fields filled  "
                        f"Confidence: {s.get('confidence',0):.0%}",
                    ]
                    if missing:
                        lines.append(f"  Missing vs keeper: {', '.join(missing)}")
                    if s.get("note"):
                        lines.append(f"  ⚠ {s['note']}")
                    desc = "\n".join(lines)
                    action_lbl = "Deactivate duplicate"
                elif gtype == "correction":
                    _FIELD_LABELS = [
                        ("suggested_title",          "current_title",          "Title"),
                        ("suggested_composer",        "current_composer",       "Composer"),
                        ("suggested_arranger",        "current_arranger",       "Arranger"),
                        ("suggested_genre",           "current_genre",          "Genre"),
                        ("suggested_key_signature",   "current_key_signature",  "Key"),
                        ("suggested_time_signature",  "current_time_signature", "Time Sig"),
                        ("suggested_difficulty",      "current_difficulty",     "Difficulty"),
                        ("suggested_ensemble_type",   "current_ensemble_type",  "Ensemble"),
                        ("suggested_voicing",         "current_voicing",        "Voicing"),
                        ("suggested_language",        "current_language",       "Language"),
                        ("suggested_accompaniment",   "current_accompaniment",  "Accompaniment"),
                        ("suggested_location",        None,                     "Location"),
                    ]
                    lines = [f"CORRECTION  \"{s.get('current_title','')}\""]
                    for skey, ckey, label in _FIELD_LABELS:
                        sval = s.get(skey)
                        cval = s.get(ckey, "") if ckey else ""
                        if sval and sval != cval:
                            lines.append(f"  {label}: \"{cval}\" → \"{sval}\"")
                    if s.get("image"):
                        lines.append(f"  Image: {s['image']}  Confidence: {s.get('confidence',0):.0%}")
                    if s.get("note"):
                        lines.append(f"  Note: {s['note']}")
                    desc = "\n".join(lines)
                    action_lbl = "Apply correction"
                else:  # missing
                    by_parts = [s.get("composer", "")]
                    if s.get("arranger"):
                        by_parts.append(f"arr. {s['arranger']}")
                    by_str = ", ".join(p for p in by_parts if p)
                    desc = (
                        f"MISSING  \"{s.get('title','')}\" by {by_str}\n"
                        f"  Image: {s.get('image','')}"
                    )
                    if s.get("note"):
                        desc += f"\n  Note: {s['note']}"
                    action_lbl = "Add to database"

                text_frame = ttk.Frame(row)
                text_frame.pack(side=LEFT, fill=X, expand=True)
                ttk.Label(text_frame, text=desc, font=("Segoe UI", 8),
                          justify=LEFT, anchor=W, wraplength=600).pack(anchor=W)
                ttk.Label(text_frame, text=f"Action: {action_lbl}",
                          font=("Segoe UI", 8, "italic"),
                          foreground=muted_fg()).pack(anchor=W)

                ttk.Separator(inner, orient=HORIZONTAL).pack(fill=X, padx=8, pady=2)

        # Bottom controls
        ctrl = ttk.Frame(inner)
        ctrl.pack(fill=X, padx=8, pady=8)
        ttk.Button(ctrl, text="Select All", bootstyle=(SECONDARY, OUTLINE),
                   command=lambda: [v.set(True) for v in self._check_vars]).pack(side=LEFT, padx=2)
        ttk.Button(ctrl, text="Deselect All", bootstyle=(SECONDARY, OUTLINE),
                   command=lambda: [v.set(False) for v in self._check_vars]).pack(side=LEFT, padx=2)

        # Footer buttons
        btn_frame = ttk.Frame(self)
        btn_frame.pack(fill=X, padx=16, pady=(0, 12))
        ttk.Button(btn_frame, text="Cancel", bootstyle=(SECONDARY, OUTLINE),
                   command=self.destroy).pack(side=RIGHT, padx=4)
        ttk.Button(btn_frame, text="Apply Selected", bootstyle=SUCCESS,
                   command=self._apply_selected).pack(side=RIGHT, padx=4)

    def _apply_selected(self):
        applied = 0
        errors = []
        for var, s in zip(self._check_vars, self._suggestion_meta):
            if not var.get():
                continue
            try:
                if s["type"] == "not_found":
                    self.db.deactivate_sheet_music(s["id"])
                    applied += 1
                elif s["type"] == "duplicate":
                    self.db.deactivate_sheet_music(s["id"])
                    applied += 1
                elif s["type"] == "correction":
                    piece = self.db.get_sheet_music(s["id"])
                    if piece:
                        data = dict(piece)
                        for skey, dbkey in [
                            ("suggested_title",          "title"),
                            ("suggested_composer",       "composer"),
                            ("suggested_arranger",       "arranger"),
                            ("suggested_genre",          "genre"),
                            ("suggested_key_signature",  "key_signature"),
                            ("suggested_time_signature", "time_signature"),
                            ("suggested_difficulty",     "difficulty"),
                            ("suggested_ensemble_type",  "ensemble_type"),
                            ("suggested_voicing",        "voicing"),
                            ("suggested_language",       "language"),
                            ("suggested_accompaniment",  "accompaniment"),
                            ("suggested_location",       "location"),
                        ]:
                            val = s.get(skey)
                            if val:
                                data[dbkey] = val
                        self.db.update_sheet_music(s["id"], data)
                        applied += 1
                elif s["type"] == "missing":
                    self.db.add_sheet_music({
                        "title": s.get("title", ""),
                        "composer": s.get("composer", ""),
                        "arranger": s.get("arranger", ""),
                        "genre": "Jazz",
                        "ensemble_type": "Jazz Ensemble",
                        "source_file": s.get("image_path", ""),
                    })
                    applied += 1
            except Exception as e:
                errors.append(str(e))

        self.changes_made = applied > 0
        msg = f"Applied {applied} fix(es)."
        if errors:
            msg += f"\n{len(errors)} error(s):\n" + "\n".join(errors[:3])
        Messagebox.show_info(msg, title="Done", parent=self.winfo_toplevel())
        self.destroy()
