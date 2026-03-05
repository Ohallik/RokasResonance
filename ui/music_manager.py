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
from tkinter import filedialog
from datetime import datetime
from ui.theme import muted_fg

# MusicPics folder names to search when resolving source_file paths
_MUSIC_PICS_FOLDERS = ["MusicPics", "music_pics", "musicpics"]


TREEVIEW_COLS = (
    "title", "composer", "arranger",
    "ensemble_type", "genre", "difficulty",
    "key_signature", "time_signature", "location", "last_played", "file_type",
    "source_file",
)
COL_HEADERS = {
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
COL_WIDTHS = {
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
# Columns hidden by default (user can enable via Columns menu)
COL_HIDDEN_DEFAULT = {"source_file"}


class MusicManager(ttk.Frame):
    def __init__(self, parent, db, base_dir: str):
        super().__init__(parent)
        self.db = db
        self.base_dir = base_dir
        self._all_rows = []
        self._omr_status_cache = {}   # music_id -> latest job status
        self._selected_id = None
        self._sort_col = "title"
        self._sort_asc = True
        self._search_var = tk.StringVar()
        self._filter_genre = tk.StringVar(value="All")
        self._filter_location = tk.StringVar(value="All")
        self._filter_omr = tk.StringVar(value="All")
        self._col_vars = {
            c: tk.BooleanVar(value=(c not in COL_HIDDEN_DEFAULT))
            for c in TREEVIEW_COLS
        }
        self._col_popup = None
        self._last_played_cache = {}  # music_id -> date string
        self._chat_window = None

        self._build()
        self._load_col_prefs()
        self._apply_col_visibility()
        self.refresh()

    # ──────────────────────────────────────────────────────── Build UI ─────

    def _build(self):
        # ── Toolbar ───────────────────────────────────────────────────────
        toolbar = ttk.Frame(self, bootstyle=LIGHT)
        toolbar.pack(fill=X, padx=0, pady=0)

        ttk.Button(toolbar, text="Add Music", bootstyle=SUCCESS,
                   command=self._add_music).pack(side=LEFT, padx=6, pady=6)
        ttk.Button(toolbar, text="Import Music", bootstyle=(SUCCESS, OUTLINE),
                   command=self._import_music).pack(side=LEFT, padx=2, pady=6)
        ttk.Button(toolbar, text="Edit", bootstyle=PRIMARY,
                   command=self._edit_music).pack(side=LEFT, padx=2, pady=6)
        self._delete_btn = ttk.Button(toolbar, text="Delete", bootstyle=DANGER,
                                      command=self._delete_selected, state=DISABLED)
        self._delete_btn.pack(side=LEFT, padx=2, pady=6)

        ttk.Separator(toolbar, orient=VERTICAL).pack(
            side=LEFT, fill=Y, padx=8, pady=4)

        self._omr_btn = ttk.Button(toolbar, text="Process OMR", bootstyle=WARNING,
                                   command=self._process_omr, state=DISABLED)
        self._omr_btn.pack(side=LEFT, padx=2, pady=6)
        self._export_btn = ttk.Button(toolbar, text="Export MusicXML", bootstyle=INFO,
                                      command=self._export_musicxml, state=DISABLED)
        self._export_btn.pack(side=LEFT, padx=2, pady=6)
        self._validate_btn = ttk.Button(toolbar, text="Validate with LLM",
                                        bootstyle=(SECONDARY, OUTLINE),
                                        command=self._validate_with_llm, state=DISABLED)
        self._validate_btn.pack(side=LEFT, padx=2, pady=6)

        ttk.Separator(toolbar, orient=VERTICAL).pack(
            side=LEFT, fill=Y, padx=8, pady=4)

        ttk.Button(toolbar, text="Refresh", bootstyle=(SECONDARY, OUTLINE),
                   command=self.refresh).pack(side=LEFT, padx=2, pady=6)

        # ── Search / Filter Bar ───────────────────────────────────────────
        filter_bar = ttk.Frame(self)
        filter_bar.pack(fill=X, padx=8, pady=(4, 2))

        ttk.Label(filter_bar, text="Search:").pack(side=LEFT, padx=(0, 4))
        search_entry = ttk.Entry(filter_bar, textvariable=self._search_var,
                                 width=28)
        search_entry.pack(side=LEFT, padx=(0, 10))
        self._search_var.trace_add("write", lambda *_: self._apply_filters())

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
            columns=TREEVIEW_COLS,
            show="headings",
            yscrollcommand=scrollbar_y.set,
            xscrollcommand=scrollbar_x.set,
            selectmode="extended",
            bootstyle=INFO,
        )
        scrollbar_y.config(command=self.tree.yview)
        scrollbar_x.config(command=self.tree.xview)

        scrollbar_y.pack(side=RIGHT, fill=Y)
        scrollbar_x.pack(side=BOTTOM, fill=X)
        self.tree.pack(fill=BOTH, expand=True)

        _STRETCH = {"title", "composer", "arranger", "location"}
        for col in TREEVIEW_COLS:
            self.tree.heading(
                col, text=COL_HEADERS[col], anchor=W,
                command=lambda c=col: self._sort_by(c)
            )
            self.tree.column(col, width=COL_WIDTHS[col], anchor=W,
                             minwidth=40, stretch=col in _STRETCH)

        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.bind("<Double-1>", lambda e: self._edit_music())

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
        self._detail_nb.add(self._omr_tab, text="OMR Results")
        self._detail_nb.add(self._history_tab, text="Job History")

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

    def _build_detail_tab(self):
        outer = ttk.Frame(self._detail_tab)
        outer.pack(fill=BOTH, expand=True, padx=8, pady=8)

        self._detail_labels = {}
        fields = [
            ("Title", "title"),
            ("Composer", "composer"),
            ("Arranger", "arranger"),
            ("Publisher", "publisher"),
            ("Genre", "genre"),
            ("Ensemble", "ensemble_type"),
            ("Difficulty", "difficulty"),
            ("Key", "key_signature"),
            ("Time Sig", "time_signature"),
            ("Location", "location"),
            ("File Type", "file_type"),
            ("Pages", "num_pages"),
            ("File", "file_path"),
            ("Source File", "source_file"),
            ("Comments", "notes"),
            ("OMR Status", "_omr_status"),
            ("Last Processed", "_last_processed"),
        ]

        for label, key in fields:
            row = ttk.Frame(outer)
            row.pack(fill=X, pady=1)
            ttk.Label(row, text=f"{label}:", font=("Segoe UI", 8, "bold"),
                      width=14, anchor=W).pack(side=LEFT)
            val_lbl = ttk.Label(row, text="", font=("Segoe UI", 8),
                                anchor=W, wraplength=180, justify=LEFT)
            val_lbl.pack(side=LEFT, fill=X, expand=True)
            self._detail_labels[key] = val_lbl

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
        path = os.path.join(self.base_dir, "music_column_prefs.json")
        try:
            with open(path) as f:
                prefs = json.load(f)
            for col, var in self._col_vars.items():
                if col in prefs:
                    var.set(bool(prefs[col]))
        except (FileNotFoundError, json.JSONDecodeError):
            pass

    def _save_col_prefs(self):
        path = os.path.join(self.base_dir, "music_column_prefs.json")
        try:
            with open(path, "w") as f:
                json.dump({c: v.get() for c, v in self._col_vars.items()}, f, indent=2)
        except Exception:
            pass

    def _apply_col_visibility(self):
        visible = [c for c in TREEVIEW_COLS if self._col_vars[c].get()]
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

        for col in TREEVIEW_COLS:
            ttk.Checkbutton(
                outer,
                text=COL_HEADERS[col],
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
        self._all_rows = [dict(r) for r in self.db.get_all_sheet_music()]
        # Cache OMR status and last played date for each piece
        self._omr_status_cache.clear()
        self._last_played_cache.clear()
        for row in self._all_rows:
            job = self.db.get_latest_omr_job(row["id"])
            if job:
                self._omr_status_cache[row["id"]] = dict(job)
            else:
                self._omr_status_cache[row["id"]] = None
            perfs = self.db.get_performances(row["id"])
            if perfs:
                self._last_played_cache[row["id"]] = perfs[0]["performance_date"] or ""
            else:
                self._last_played_cache[row["id"]] = ""
        self._update_genre_filter()
        self._update_location_filter()
        self._apply_filters()
        if self._selected_id:
            self._restore_selection()

    def _update_genre_filter(self):
        genres = sorted(set(
            r["genre"] for r in self._all_rows
            if r["genre"]
        ))
        self._genre_combo["values"] = ["All"] + genres
        if self._filter_genre.get() not in ["All"] + genres:
            self._filter_genre.set("All")

    def _update_location_filter(self):
        locations = sorted(set(
            r["location"] for r in self._all_rows
            if r.get("location")
        ))
        self._location_combo["values"] = ["All"] + locations
        if self._filter_location.get() not in ["All"] + locations:
            self._filter_location.set("All")

    def _apply_filters(self):
        search = self._search_var.get().lower()
        genre_f = self._filter_genre.get()
        location_f = self._filter_location.get()
        omr_f = self._filter_omr.get()

        visible = []
        for row in self._all_rows:
            # Genre filter
            if genre_f != "All" and (row["genre"] or "") != genre_f:
                continue

            # Location filter
            if location_f != "All" and (row.get("location") or "") != location_f:
                continue

            # OMR status filter
            job = self._omr_status_cache.get(row["id"])
            job_status = job["status"] if job else None
            if omr_f == "Processed" and job_status != "completed":
                continue
            if omr_f == "Unprocessed" and job_status is not None:
                continue
            if omr_f == "Failed" and job_status != "failed":
                continue

            # Search
            if search:
                haystack = " ".join([
                    str(row["title"] or ""),
                    str(row["composer"] or ""),
                    str(row["arranger"] or ""),
                    str(row["genre"] or ""),
                    str(row["ensemble_type"] or ""),
                    str(row.get("key_signature") or ""),
                    str(row.get("time_signature") or ""),
                    str(row.get("location") or ""),
                ]).lower()
                if search not in haystack:
                    continue

            visible.append(row)

        self._populate_tree(visible)
        self._count_label.config(
            text=f"{len(visible)} of {len(self._all_rows)} pieces"
        )

    def _populate_tree(self, rows):
        reverse = not self._sort_asc
        try:
            rows = sorted(
                rows,
                key=lambda r: (r.get(self._sort_col) or "").lower()
                if isinstance(r.get(self._sort_col), str)
                else str(r.get(self._sort_col) or ""),
                reverse=reverse
            )
        except Exception:
            pass

        self.tree.delete(*self.tree.get_children())
        for row in rows:
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
                self._last_played_cache.get(row["id"], ""),
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

        # Enable/disable multi-selection buttons
        multi_state = NORMAL if n >= 1 else DISABLED
        self._delete_btn.config(state=multi_state)
        self._validate_btn.config(state=multi_state)

        if not sel:
            self._omr_btn.config(state=DISABLED)
            self._export_btn.config(state=DISABLED)
            return

        # Detail panel shows the last selected item
        iid = sel[-1]
        self._selected_id = int(iid)
        self._load_detail(self._selected_id)

        # Enable/disable OMR buttons based on source file (single-select context)
        piece = self.db.get_sheet_music(self._selected_id)
        has_file = bool(piece and piece["file_path"])
        state = NORMAL if has_file else DISABLED
        self._omr_btn.config(state=state)
        self._export_btn.config(state=state)

        # Keep open chat window in sync with selected piece
        if self._chat_window and self._chat_window.winfo_exists():
            self._chat_window.update_selected_music(
                dict(piece) if piece else None
            )

    def _get_selected_ids(self) -> list[int]:
        """Return list of all selected music IDs."""
        return [int(iid) for iid in self.tree.selection()]

    def _load_detail(self, music_id: int):
        piece = self.db.get_sheet_music(music_id)
        if not piece:
            return

        row = dict(piece)

        # OMR status info
        job = self._omr_status_cache.get(music_id)
        if job and job["status"] == "completed":
            row["_omr_status"] = "Completed"
            row["_last_processed"] = job.get("completed_at") or job.get("started_at") or ""
        elif job and job["status"] == "failed":
            row["_omr_status"] = "Failed"
            row["_last_processed"] = job.get("started_at") or ""
        else:
            row["_omr_status"] = "Not processed"
            row["_last_processed"] = ""

        # Show just filename for file_path
        fp = row.get("file_path") or ""
        if fp:
            row["file_path"] = os.path.basename(fp)

        for key, lbl in self._detail_labels.items():
            val = row.get(key, "")
            if val is None:
                val = ""
            lbl.config(text=str(val))

        # Color OMR status
        status_lbl = self._detail_labels.get("_omr_status")
        if status_lbl:
            s = row.get("_omr_status", "")
            if s == "Completed":
                status_lbl.config(foreground="#1a7a1a",
                                  font=("Segoe UI", 8, "bold"))
            elif s == "Failed":
                status_lbl.config(foreground="#CC0000",
                                  font=("Segoe UI", 8, "bold"))
            else:
                status_lbl.config(foreground=muted_fg(),
                                  font=("Segoe UI", 8))

        self._load_performances(music_id)
        self._load_omr_results(music_id)
        self._load_job_history(music_id)

    def _load_omr_results(self, music_id: int):
        self._omr_tree.delete(*self._omr_tree.get_children())
        job = self._omr_status_cache.get(music_id)

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
        dlg = PerformanceDialog(self.winfo_toplevel(), self.db, self._selected_id)
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
                                performance_id=perf_id)
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
                          base_dir=self.base_dir, music_id=None)
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
            existing_titles=existing_titles,
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
                          base_dir=self.base_dir, music_id=iid)
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
            self.winfo_toplevel(), self.db, self.base_dir, pieces
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
        job = self._omr_status_cache.get(iid)
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
            selected_music=piece,
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
        self.geometry("650x520")
        self.resizable(True, True)
        self.grab_set()

        # Center
        self.update_idletasks()
        x = (self.winfo_screenwidth() - 650) // 2
        y = (self.winfo_screenheight() - 520) // 2
        self.geometry(f"+{x}+{y}")

        self._build()
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
    # Try just the filename in known MusicPics folders
    fname = os.path.basename(path)
    for folder in _MUSIC_PICS_FOLDERS:
        candidate = os.path.join(base_dir, folder, fname)
        if os.path.isfile(candidate):
            return candidate
    return None


def _load_image_b64(path: str) -> dict | None:
    """Load an image file as a base64 dict for LLM vision calls."""
    try:
        import base64, io
        from PIL import Image
        img = Image.open(path).convert("RGB")
        w, h = img.size
        scale = min(1.0, 1800 / max(w, h))
        if scale < 1.0:
            img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return {
            "mime_type": "image/png",
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

    def __init__(self, parent, db, base_dir: str, pieces: list[dict]):
        super().__init__(parent)
        self.db = db
        self.base_dir = base_dir
        self.pieces = pieces  # selected piece dicts
        self.changes_made = False

        self.title("Validate with LLM")
        self.geometry("700x540")
        self.resizable(True, True)
        self.grab_set()

        self.update_idletasks()
        x = (self.winfo_screenwidth() - 700) // 2
        y = (self.winfo_screenheight() - 540) // 2
        self.geometry(f"+{x}+{y}")

        self._build()
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
        all_db_rows = self.db.get_all_sheet_music()
        db_titles_norm = {self._norm(r["title"]) for r in all_db_rows if r["title"]}

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
            prompt = (
                "You are verifying a sheet music database. "
                "This image is a photograph of sheet music materials (folders, covers, spines, or scores).\n\n"
                f"The following pieces are recorded in the database as coming from this image:\n{piece_list}\n\n"
                "For EACH listed piece:\n"
                "1. Is it actually visible/readable in this image? (found: true/false)\n"
                "2. Does the title look correct from what you can see? If wrong, provide the correct title.\n"
                "3. Does the composer look correct from what you can see? If wrong, provide the correct composer.\n"
                "4. Does the arranger look correct from what you can see? If wrong or newly visible, provide the correct arranger.\n"
                "5. Rate your confidence (0.0–1.0).\n\n"
                "ALSO list any pieces you can clearly see in the image that are NOT in the list above.\n\n"
                "Return ONLY valid JSON (no markdown fences):\n"
                "{\n"
                '  "pieces": [\n'
                '    {"id": <id>, "found": true/false, "confidence": 0.0-1.0,\n'
                '     "suggested_title": "<corrected title or null>",\n'
                '     "suggested_composer": "<corrected composer or null>",\n'
                '     "suggested_arranger": "<corrected arranger or null>",\n'
                '     "note": "<optional brief explanation>"}\n'
                "  ],\n"
                '  "missing_from_db": [\n'
                '    {"title": "<title>", "composer": "<composer or empty>", "arranger": "<arranger or empty>", "note": "<context>"}\n'
                "  ]\n"
                "}"
            )

            primary_result = self._call_llm_vision(
                prompt, img_dict, current_model, github_key, anthropic_key
            )

            if primary_result is None:
                self.after(0, self._log_msg, "  LLM call failed. Skipping this image.")
                continue

            # Cross-check low-confidence pieces with backup models
            low_conf_ids = {
                p["id"] for p in primary_result.get("pieces", [])
                if p.get("confidence", 1.0) < 0.7 or p.get("found") is False
            }
            if low_conf_ids:
                self.after(0, self._log_msg,
                           f"  Low confidence on {len(low_conf_ids)} piece(s) — cross-checking...")
                backup_results = self._cross_check(
                    prompt, img_dict, current_model, github_key, anthropic_key
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

        # Text-based enrichment: for pieces missing metadata fields, query the LLM
        # by title/composer to fill in difficulty, key, time sig, genre, ensemble, arranger
        _ENRICH_TRIGGER = ["difficulty", "key_signature", "time_signature", "genre", "ensemble_type"]
        pieces_to_enrich = [
            p for p in self.pieces
            if any(not (p.get(f) or "").strip() for f in _ENRICH_TRIGGER)
        ]
        if pieces_to_enrich:
            self.after(0, self._log_msg, "")
            self.after(0, self._log_msg,
                       f"Text enrichment: looking up metadata for {len(pieces_to_enrich)} piece(s)...")
            try:
                from ui.music_importer import _enrich_piece
            except ImportError:
                _enrich_piece = None

            if _enrich_piece:
                _CONF_MAP = {"high": 0.9, "medium": 0.7, "low": 0.4}
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
                    self.after(0, self._log_msg,
                               f"  [{i+1}/{len(pieces_to_enrich)}] \"{p.get('title','')}\"")
                    try:
                        enriched = _enrich_piece(p, self.base_dir)
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

    def _call_llm_vision(self, prompt, img_dict, model, github_key, anthropic_key):
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

        try:
            if llm_client._is_anthropic_model(model):
                if not anthropic_key:
                    return None
                text = llm_client._query_with_images_anthropic(
                    self.base_dir, model, prompt, [img_dict]
                )
            else:
                if not github_key:
                    return None
                text = llm_client.query_with_images(self.base_dir, prompt, [img_dict])
            return _parse(text)
        except Exception as e:
            self.after(0, self._log_msg, f"  LLM error: {e}")
            return None

    def _cross_check(self, prompt, img_dict, current_model, github_key, anthropic_key):
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
                        self.base_dir, backup, prompt, [img_dict]
                    )
                else:
                    from openai import OpenAI
                    client = OpenAI(base_url=llm_client.ENDPOINT, api_key=github_key)
                    content = [{"type": "text", "text": prompt}]
                    content.append({
                        "type": "image_url",
                        "image_url": {"url": f"data:{img_dict['mime_type']};base64,{img_dict['data']}"},
                    })
                    resp = client.chat.completions.create(
                        model=backup,
                        messages=[{"role": "user", "content": content}],
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
        self.geometry("820x640")
        self.resizable(True, True)
        self.grab_set()

        self.update_idletasks()
        x = (self.winfo_screenwidth() - 820) // 2
        y = (self.winfo_screenheight() - 640) // 2
        self.geometry(f"+{x}+{y}")

        self._build()

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
            ("correction", "Suggested title / composer corrections", WARNING),
            ("missing",    "Pieces found in image but missing from database", INFO),
        ]

        self._check_vars.clear()
        self._suggestion_meta: list[dict] = []  # parallel to _check_vars

        for gtype, glabel, gstyle in groups:
            items = [s for s in self.suggestions if s["type"] == gtype]
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
