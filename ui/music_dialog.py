"""
ui/music_dialog.py - Add / Edit sheet music dialog
"""

import os
import tkinter as tk
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from ttkbootstrap.dialogs import Messagebox
from tkinter import filedialog
from ui.theme import muted_fg, file_selected_fg


GENRE_OPTIONS = [
    "March", "Concert", "Pop/Rock", "Classical", "Jazz", "World",
    "Holiday", "Warm-Up", "Method Book", "Chorale", "Other",
]

ENSEMBLE_OPTIONS = [
    "Concert Band", "Jazz Band", "Percussion Ensemble",
    "Small Ensemble", "Solo", "Marching Band", "Other",
]

DIFFICULTY_OPTIONS = [
    "0.5", "1", "1.5", "2", "2.5", "3", "3.5", "4", "4.5", "5",
]

KEY_SIGNATURE_OPTIONS = [
    "C Major", "G Major", "D Major", "A Major", "E Major", "B Major",
    "F Major", "Bb Major", "Eb Major", "Ab Major", "Db Major",
    "A Minor", "E Minor", "B Minor", "F# Minor", "C# Minor",
    "D Minor", "G Minor", "C Minor", "F Minor", "Bb Minor", "Eb Minor",
]

TIME_SIGNATURE_OPTIONS = [
    "4/4", "3/4", "2/4", "6/8", "2/2", "3/8", "5/4", "7/8", "12/8",
]

FILE_TYPES = [
    ("PDF files", "*.pdf"),
    ("Images", "*.png *.jpg *.jpeg *.tiff *.tif *.bmp"),
    ("All files", "*.*"),
]


class MusicDialog(ttk.Toplevel):
    def __init__(self, parent, db, base_dir: str, music_id=None, prefill_data=None):
        super().__init__(parent)
        self.db = db
        self.base_dir = base_dir
        self.music_id = music_id
        self._result = None
        self._source_file = None  # Path selected by user before save

        title = "Edit Sheet Music" if music_id else "Add Sheet Music"
        self.title(title)
        self.geometry("760x740")
        self.resizable(True, True)
        self.grab_set()

        # Center
        self.update_idletasks()
        x = (self.winfo_screenwidth() - 760) // 2
        y = (self.winfo_screenheight() - 740) // 2
        self.geometry(f"+{x}+{y}")

        self._vars = {}
        self._build()

        if music_id:
            self._load(music_id)
        else:
            # Defaults for new entries
            self._vars["location"].set("Chinook Middle School")
            if prefill_data:
                self._prefill(prefill_data)

    # ───────────────────────────────────────────────────── Build UI ────────

    def _build(self):
        # Header
        hdr = ttk.Frame(self, bootstyle=INFO)
        hdr.pack(fill=X)
        title = "Edit Sheet Music" if self.music_id else "Add Sheet Music"
        ttk.Label(hdr, text=f"  {title}", font=("Segoe UI", 13, "bold"),
                  bootstyle=(INVERSE, INFO)).pack(pady=12, padx=16, anchor=W)

        # Buttons at bottom
        btn_frame = ttk.Frame(self)
        btn_frame.pack(fill=X, padx=16, pady=10, side=BOTTOM)

        if self.music_id:
            ttk.Button(btn_frame, text="Mark Inactive",
                       bootstyle=(DANGER, OUTLINE),
                       command=self._mark_inactive).pack(side=LEFT, padx=4)

        ttk.Button(btn_frame, text="Cancel", bootstyle=(SECONDARY, OUTLINE),
                   command=self.destroy).pack(side=RIGHT, padx=4)
        ttk.Button(btn_frame, text="Save", bootstyle=SUCCESS,
                   command=self._save).pack(side=RIGHT, padx=4)

        # Scrollable content
        canvas = tk.Canvas(self, highlightthickness=0)
        scrollbar = ttk.Scrollbar(self, orient=VERTICAL, command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side=RIGHT, fill=Y)
        canvas.pack(fill=BOTH, expand=True)

        content = ttk.Frame(canvas)
        content_window = canvas.create_window((0, 0), window=content, anchor=NW)

        def _on_configure(event):
            canvas.configure(scrollregion=canvas.bbox("all"))
            canvas.itemconfig(content_window, width=canvas.winfo_width())

        content.bind("<Configure>", _on_configure)
        canvas.bind("<Configure>",
                     lambda e: canvas.itemconfig(content_window, width=e.width))

        def _on_mousewheel(event):
            try:
                canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
            except tk.TclError:
                pass
        canvas.bind_all("<MouseWheel>", _on_mousewheel)
        self.protocol("WM_DELETE_WINDOW", lambda: (
            canvas.unbind_all("<MouseWheel>"), self.destroy()
        ))

        self._build_sections(content)

    def _build_sections(self, parent):
        # ── Basic Information ─────────────────────────────────────────────
        self._section(parent, "Basic Information")
        basic = ttk.Frame(parent)
        basic.pack(fill=X, padx=16, pady=(0, 8))

        row0 = ttk.Frame(basic)
        row0.pack(fill=X, pady=2)
        self._field(row0, "Title *", "title", side=LEFT, width=50)

        row1 = ttk.Frame(basic)
        row1.pack(fill=X, pady=2)
        self._field(row1, "Composer", "composer", side=LEFT, width=24)
        self._field(row1, "Arranger", "arranger", side=LEFT, width=24)

        row1b = ttk.Frame(basic)
        row1b.pack(fill=X, pady=2)
        self._field(row1b, "Publisher", "publisher", side=LEFT, width=36)

        # ── Classification ────────────────────────────────────────────────
        self._section(parent, "Classification")
        cls = ttk.Frame(parent)
        cls.pack(fill=X, padx=16, pady=(0, 8))

        row2 = ttk.Frame(cls)
        row2.pack(fill=X, pady=2)
        self._field(row2, "Genre", "genre", widget="combobox",
                    options=GENRE_OPTIONS, side=LEFT, width=18)
        self._field(row2, "Ensemble", "ensemble_type", widget="combobox",
                    options=ENSEMBLE_OPTIONS, side=LEFT, width=18)
        self._field(row2, "Difficulty", "difficulty", widget="combobox",
                    options=DIFFICULTY_OPTIONS, side=LEFT, width=14)

        row3 = ttk.Frame(cls)
        row3.pack(fill=X, pady=2)
        self._field(row3, "Key Signature(s)  (e.g. Bb Major, G Minor)", "key_signature",
                    widget="entry", side=LEFT, width=32)
        self._field(row3, "Time Signature", "time_signature", widget="combobox",
                    options=TIME_SIGNATURE_OPTIONS, side=LEFT, width=10)

        # ── Location ────────────────────────────────────────────────────
        self._section(parent, "Location")
        loc_frame = ttk.Frame(parent)
        loc_frame.pack(fill=X, padx=16, pady=(0, 8))

        loc_row = ttk.Frame(loc_frame)
        loc_row.pack(fill=X, pady=2)
        self._field(loc_row, "Location", "location", side=LEFT, width=40)

        # ── File ──────────────────────────────────────────────────────────
        self._section(parent, "Source File (Optional)")
        file_row = ttk.Frame(parent)
        file_row.pack(fill=X, padx=16, pady=(0, 8))

        ttk.Button(file_row, text="Browse...", bootstyle=(PRIMARY, OUTLINE),
                   command=self._browse_file).pack(side=LEFT, padx=(0, 6))
        self._file_label = ttk.Label(
            file_row, text="No file selected",
            font=("Segoe UI", 8), foreground=muted_fg(),
        )
        self._file_label.pack(side=LEFT, fill=X, expand=True)

        # File type + pages inline on same row
        ttk.Label(file_row, text="Type:", font=("Segoe UI", 8)).pack(side=LEFT, padx=(8, 2))
        file_type_var = tk.StringVar()
        self._vars["file_type"] = file_type_var
        ttk.Entry(file_row, textvariable=file_type_var, width=7).pack(side=LEFT)

        ttk.Label(file_row, text="Pages:", font=("Segoe UI", 8)).pack(side=LEFT, padx=(8, 2))
        pages_var = tk.StringVar()
        self._vars["num_pages"] = pages_var
        ttk.Entry(file_row, textvariable=pages_var, width=5).pack(side=LEFT)

        # ── Comments ──────────────────────────────────────────────────────
        self._section(parent, "Comments")
        notes_frame = ttk.Frame(parent)
        notes_frame.pack(fill=X, padx=16, pady=(0, 8))

        self._notes_text = tk.Text(notes_frame, height=8, font=("Segoe UI", 9),
                                   relief="solid", bd=1, wrap=WORD)
        self._notes_text.pack(fill=X, pady=2)

    def _section(self, parent, title):
        f = ttk.Frame(parent)
        f.pack(fill=X, padx=8, pady=(10, 2))
        ttk.Label(f, text=title, font=("Segoe UI", 10, "bold"),
                  bootstyle=PRIMARY).pack(side=LEFT)
        ttk.Separator(f).pack(side=LEFT, fill=X, expand=True, padx=8)

    def _field(self, parent, label, key, widget="entry", options=None,
               side=LEFT, width=20):
        f = ttk.Frame(parent)
        f.pack(side=side, padx=6, pady=1)
        ttk.Label(f, text=label, font=("Segoe UI", 8)).pack(anchor=W)
        var = tk.StringVar()
        self._vars[key] = var
        if widget == "combobox":
            w = ttk.Combobox(f, textvariable=var, values=options or [], width=width)
            w.pack(anchor=W)
        else:
            w = ttk.Entry(f, textvariable=var, width=width)
            w.pack(anchor=W)
        return w

    # ───────────────────────────────────────────────────── File Browse ─────

    def _browse_file(self):
        path = filedialog.askopenfilename(
            title="Select Sheet Music File",
            filetypes=FILE_TYPES,
        )
        if not path:
            return

        self._source_file = path
        self._file_label.config(text=os.path.basename(path), foreground=file_selected_fg())

        # Auto-detect file type
        ext = os.path.splitext(path)[1].lower()
        type_map = {
            ".pdf": "PDF", ".png": "PNG", ".jpg": "JPEG", ".jpeg": "JPEG",
            ".tiff": "TIFF", ".tif": "TIFF", ".bmp": "BMP",
        }
        self._vars["file_type"].set(type_map.get(ext, ext.upper().lstrip(".")))

        # Auto-detect page count for PDFs
        if ext == ".pdf":
            try:
                import pypdf
                reader = pypdf.PdfReader(path)
                self._vars["num_pages"].set(str(len(reader.pages)))
            except Exception:
                pass

    # ───────────────────────────────────────────────────── Data Methods ────

    def _load(self, music_id: int):
        row = self.db.get_sheet_music(music_id)
        if not row:
            return
        for key, var in self._vars.items():
            val = row[key] if key in row.keys() else None
            var.set("" if val is None else str(val))

        notes = row["notes"] or ""
        self._notes_text.delete("1.0", "end")
        self._notes_text.insert("1.0", notes)

        file_path = row["file_path"] or ""
        if file_path:
            self._file_label.config(text=os.path.basename(file_path),
                                    foreground=file_selected_fg())

    def _prefill(self, data: dict):
        """Populate form fields from an AI-analysed prefill dict."""
        for key, var in self._vars.items():
            val = data.get(key, "")
            if val:
                var.set(str(val).strip())
        notes = data.get("notes", "")
        if notes:
            self._notes_text.delete("1.0", "end")
            self._notes_text.insert("1.0", notes)

    def _collect_data(self) -> dict:
        data = {k: v.get().strip() for k, v in self._vars.items()}
        data["notes"] = self._notes_text.get("1.0", "end").strip()

        # Type coercions
        try:
            data["num_pages"] = int(data["num_pages"]) if data["num_pages"] else None
        except ValueError:
            data["num_pages"] = None

        if self.music_id:
            data["is_active"] = 1

        return data

    def _validate(self, data: dict) -> bool:
        if not data.get("title"):
            Messagebox.show_warning("Title is required.", title="Validation")
            return False
        return True

    def _save(self):
        data = self._collect_data()
        if not self._validate(data):
            return

        if self.music_id:
            # Update existing
            if self._source_file:
                from omr_engine import import_file
                dest = import_file(self.base_dir, self.music_id, self._source_file)
                data["file_path"] = dest
            else:
                # Keep existing file_path
                existing = self.db.get_sheet_music(self.music_id)
                if existing:
                    data["file_path"] = existing["file_path"]
            self.db.update_sheet_music(self.music_id, data)
        else:
            # Create new - save first to get ID, then copy file
            data["file_path"] = ""
            new_id = self.db.add_sheet_music(data)
            if self._source_file:
                from omr_engine import import_file
                dest = import_file(self.base_dir, new_id, self._source_file)
                data["file_path"] = dest
                data["is_active"] = 1
                self.db.update_sheet_music(new_id, data)

        self._result = "saved"
        self.destroy()

    def _mark_inactive(self):
        if Messagebox.yesno(
            "Mark this sheet music as inactive? It will be hidden from the "
            "main list but all data will be preserved.",
            title="Confirm"
        ) == "Yes":
            self.db.deactivate_sheet_music(self.music_id)
            self._result = "deactivated"
            self.destroy()
