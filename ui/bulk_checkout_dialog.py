"""
ui/bulk_checkout_dialog.py - Bulk Check Out / Check In dialog (barcode-driven)
"""

import os
import tkinter as tk
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from ttkbootstrap.dialogs import Messagebox
from datetime import date as dt_date, datetime


def _default_return_date() -> dt_date:
    today = dt_date.today()
    end_year = today.year + 1 if today.month >= 8 else today.year
    return dt_date(end_year, 6, 20)


class BulkCheckoutDialog(ttk.Toplevel):
    def __init__(self, parent, db, base_dir: str, refresh_callback=None):
        super().__init__(parent)
        self.db = db
        self.base_dir = base_dir
        self._instrument = None          # currently loaded instrument row
        self._selected_student_id = None
        self._ac_selecting = False
        self._refresh_callback = refresh_callback

        # Pre-load student list for autocomplete (deduplicated).
        # Always key by first-word-of-first-name + last name so that rows with and
        # without a district student_id for the same person collapse into one entry.
        # Prefer whichever record has a student_id (richer contact data).
        all_students = self.db.get_all_students()
        _seen = {}  # name_key -> (record_dict, has_sid)
        for s in all_students:
            d = dict(s)
            has_sid = bool((s["student_id"] or "").strip())
            first_word = (s["first_name"] or "").split()[0].lower()
            last = (s["last_name"] or "").lower()
            name_key = f"{first_word}|{last}"
            if name_key not in _seen:
                _seen[name_key] = (d, has_sid)
            elif has_sid and not _seen[name_key][1]:
                _seen[name_key] = (d, True)  # upgrade to the richer record
        self._student_list = [
            (f"{s['first_name']} {s['last_name']}", s) for s, _ in _seen.values()
        ]

        self.title("Bulk Check Out / Check In")
        self.resizable(True, True)
        self.grab_set()
        self.lift()

        self._build()

        from ui.theme import fit_window
        fit_window(self, 980, 640)

    # ─────────────────────────────────────────────────────────────── Build ──

    def _build(self):
        # Header
        hdr = ttk.Frame(self, bootstyle=WARNING)
        hdr.pack(fill=X)
        ttk.Label(hdr, text="  Bulk Check Out / Check In",
                  font=("Segoe UI", 13, "bold"),
                  bootstyle=(INVERSE, WARNING)).pack(pady=10, padx=16, anchor=W)

        # Notebook
        nb = ttk.Notebook(self, bootstyle=PRIMARY)
        nb.pack(fill=BOTH, expand=True, padx=10, pady=(8, 0))
        self._nb = nb

        self._checkout_tab = ttk.Frame(nb)
        self._checkin_tab  = ttk.Frame(nb)
        nb.add(self._checkout_tab, text="  Check Out  ")
        nb.add(self._checkin_tab,  text="  Check In  ")

        self._build_checkout_tab()
        self._build_checkin_tab()

        # Set focus to CI barcode when switching to Check In tab
        nb.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        # Close button
        btn_bar = ttk.Frame(self)
        btn_bar.pack(fill=X, padx=16, pady=10)
        ttk.Button(btn_bar, text="Close", bootstyle=(SECONDARY, OUTLINE),
                   command=self.destroy).pack(side=RIGHT)

    # ───────────────────────────────────────────────── Check Out tab ─────

    def _build_checkout_tab(self):
        outer = ttk.Frame(self._checkout_tab)
        outer.pack(fill=BOTH, expand=True, padx=0, pady=0)
        outer.columnconfigure(0, weight=0)
        outer.columnconfigure(1, weight=1)
        outer.rowconfigure(0, weight=1)

        # ── Left: scrollable input form + fixed button bar ────────────────
        left_outer = ttk.Frame(outer, width=330)
        left_outer.grid(row=0, column=0, sticky=NSEW, padx=(10, 4), pady=8)
        left_outer.grid_propagate(False)
        left_outer.rowconfigure(0, weight=1)
        left_outer.rowconfigure(1, weight=0)
        left_outer.columnconfigure(0, weight=1)

        left_canvas = tk.Canvas(left_outer, highlightthickness=0)
        left_canvas.grid(row=0, column=0, sticky=NSEW)
        left_sb = ttk.Scrollbar(left_outer, orient=VERTICAL,
                                command=left_canvas.yview)
        left_sb.grid(row=0, column=1, sticky=NS)
        left_canvas.configure(yscrollcommand=left_sb.set)

        left = ttk.Frame(left_canvas)
        _win_id = left_canvas.create_window((0, 0), window=left, anchor=NW)

        def _on_frame_configure(e):
            left_canvas.configure(scrollregion=left_canvas.bbox("all"))
        def _on_canvas_resize(e):
            left_canvas.itemconfig(_win_id, width=e.width)
        left.bind("<Configure>", _on_frame_configure)
        left_canvas.bind("<Configure>", _on_canvas_resize)

        def _on_mousewheel(e):
            left_canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
        left_canvas.bind_all("<MouseWheel>", _on_mousewheel)
        self.bind("<Destroy>", lambda e: left_canvas.unbind_all("<MouseWheel>")
                  if e.widget is self else None)

        self._build_checkout_form(left)

        # ── Fixed button bar (always visible, below scrollable form) ──────
        btn_outer = ttk.Frame(left_outer)
        btn_outer.grid(row=1, column=0, columnspan=2, sticky=EW, padx=4, pady=(4, 6))

        self._status_var = tk.StringVar(value="")
        self._status_lbl = ttk.Label(btn_outer, textvariable=self._status_var,
                                      font=("Segoe UI", 8), wraplength=280, justify=LEFT)
        self._status_lbl.pack(anchor=W, pady=(0, 4))

        btn_frame = ttk.Frame(btn_outer)
        btn_frame.pack(fill=X)
        self._checkout_btn = ttk.Button(btn_frame, text="Check Out",
                                         bootstyle=WARNING,
                                         command=self._do_checkout)
        self._checkout_btn.pack(side=LEFT, padx=(0, 6))
        self._form_btn = ttk.Button(btn_frame, text="Check Out + Form",
                                     bootstyle=SUCCESS,
                                     command=self._do_checkout_with_form)
        self._form_btn.pack(side=LEFT)

        # Vertical separator
        ttk.Separator(outer, orient=VERTICAL).grid(row=0, column=0, sticky=NS,
                                                    padx=(338, 0), pady=4)

        # ── Right: running log ─────────────────────────────────────────────
        right = ttk.Frame(outer)
        right.grid(row=0, column=1, sticky=NSEW, padx=(8, 8), pady=8)

        ttk.Label(right, text="Session Checkouts",
                  font=("Segoe UI", 10, "bold")).pack(anchor=W, pady=(0, 4))

        log_frame = ttk.Frame(right)
        log_frame.pack(fill=BOTH, expand=True)

        cols = ("Instrument", "Student", "Form")
        sb = ttk.Scrollbar(log_frame, orient=VERTICAL)
        self._log_tree = ttk.Treeview(log_frame, columns=cols, show="headings",
                                       yscrollcommand=sb.set, bootstyle=SUCCESS,
                                       selectmode="browse")
        sb.config(command=self._log_tree.yview)
        sb.pack(side=RIGHT, fill=Y)
        self._log_tree.pack(fill=BOTH, expand=True)

        self._log_tree.heading("Instrument", text="Instrument", anchor=W)
        self._log_tree.heading("Student",    text="Student",    anchor=W)
        self._log_tree.heading("Form",       text="Form",       anchor=W)

        self._log_tree.column("Instrument", width=200, stretch=True,  anchor=W)
        self._log_tree.column("Student",    width=140, stretch=True,  anchor=W)
        self._log_tree.column("Form",       width=80,  stretch=False, anchor=CENTER)

        self._log_tree.tag_configure("has_form", foreground="#4A90D9")

        self._log_tree.bind("<Double-1>", self._open_form_from_log)

        # Map: tree iid → form file path
        self._log_form_paths = {}

        ttk.Label(right, text="Double-click a row to open its loan form.",
                  font=("Segoe UI", 8), foreground="#888").pack(anchor=W, pady=(4, 0))

    def _build_checkout_form(self, parent):
        # ── Input section ──────────────────────────────────────────────────
        input_frame = tk.LabelFrame(parent, text=" Scan / Enter Barcode ",
                                    padx=8, pady=6, font=("Segoe UI", 9, "bold"))
        input_frame.pack(fill=X, padx=4, pady=(4, 8))

        # Instrument Barcode
        ttk.Label(input_frame, text="Instrument Barcode:",
                  font=("Segoe UI", 9, "bold")).pack(anchor=W)
        self._barcode_var = tk.StringVar()
        self._barcode_entry = ttk.Entry(input_frame, textvariable=self._barcode_var,
                                         width=28, font=("Segoe UI", 11))
        self._barcode_entry.pack(fill=X, pady=(2, 8))
        self._barcode_entry.focus_set()
        self._barcode_entry.bind("<Return>", lambda e: self._lookup_barcode())
        self._barcode_entry.bind("<FocusOut>", lambda e: self._lookup_barcode())

        # Student ID
        ttk.Label(input_frame, text="Student ID:",
                  font=("Segoe UI", 9, "bold")).pack(anchor=W)
        self._sid_var = tk.StringVar()
        self._sid_entry = ttk.Entry(input_frame, textvariable=self._sid_var, width=28)
        self._sid_entry.pack(fill=X, pady=(2, 8))
        self._sid_entry.bind("<Return>", lambda e: self._lookup_student_id())
        self._sid_entry.bind("<FocusOut>", lambda e: self._lookup_student_id())

        # Student Name (with autocomplete)
        ttk.Label(input_frame, text="Student Name:",
                  font=("Segoe UI", 9, "bold")).pack(anchor=W)
        self._student_var = tk.StringVar()
        self._student_entry = ttk.Entry(input_frame, textvariable=self._student_var, width=28)
        self._student_entry.pack(fill=X, pady=(2, 0))

        self._ac_container = ttk.Frame(input_frame, relief="solid", borderwidth=1)
        self._ac_container.pack(fill=X)
        self._ac_container.pack_propagate(False)
        self._ac_container.config(height=1)
        self._ac_listbox = tk.Listbox(self._ac_container, font=("Segoe UI", 9),
                                       selectmode=SINGLE, activestyle="underline",
                                       relief="flat", bd=0)
        self._ac_listbox.pack(fill=BOTH, expand=True)

        self._student_var.trace_add("write", self._on_name_changed)
        self._ac_listbox.bind("<<ListboxSelect>>", self._on_ac_select)
        self._ac_listbox.bind("<Return>", self._on_ac_select)
        self._ac_listbox.bind("<Escape>",
                              lambda e: (self._collapse_ac(),
                                         self._student_entry.focus_set()))
        self._student_entry.bind("<Down>", self._focus_ac_list)
        self._student_entry.bind("<Escape>", lambda e: self._collapse_ac())

        # ── Instrument info (filled from DB) ───────────────────────────────
        info_frame = tk.LabelFrame(parent, text=" Instrument Details ",
                                   padx=8, pady=6, font=("Segoe UI", 9, "bold"))
        info_frame.pack(fill=X, padx=4, pady=(0, 8))

        self._info_labels = {}
        for label, key in [
            ("Description", "description"),
            ("Brand / Model", "_brand_model"),
            ("Serial #", "serial_no"),
            ("Condition",  "condition"),
            ("Status",     "_status"),
        ]:
            row = ttk.Frame(info_frame)
            row.pack(fill=X, pady=1)
            ttk.Label(row, text=f"{label}:", font=("Segoe UI", 8, "bold"),
                      width=13, anchor=W).pack(side=LEFT)
            lbl = ttk.Label(row, text="—", font=("Segoe UI", 8), anchor=W)
            lbl.pack(side=LEFT, fill=X, expand=True)
            self._info_labels[key] = lbl

        # ── Return date ────────────────────────────────────────────────────
        date_frame = ttk.Frame(parent)
        date_frame.pack(fill=X, padx=4, pady=(0, 10))
        ttk.Label(date_frame, text="Return Date:",
                  font=("Segoe UI", 9, "bold")).pack(anchor=W)
        default_date = _default_return_date()
        self._due_date_entry = ttk.DateEntry(
            date_frame, dateformat="%Y-%m-%d", startdate=default_date,
            bootstyle=WARNING)
        self._due_date_entry.pack(anchor=W, pady=(2, 0))


    # ───────────────────────────────────────────────────── Check In tab ─────

    def _on_tab_changed(self, event=None):
        idx = self._nb.index(self._nb.select())
        if idx == 1:  # Check In tab
            self.after(50, lambda: self._ci_barcode_entry.focus_set()
                       if self._ci_barcode_entry.winfo_exists() else None)

    def _build_checkin_tab(self):
        self._ci_instrument = None
        self._ci_checkout = None

        outer = ttk.Frame(self._checkin_tab)
        outer.pack(fill=BOTH, expand=True)
        outer.columnconfigure(0, weight=0)
        outer.columnconfigure(1, weight=1)
        outer.rowconfigure(0, weight=1)

        # ── Left: scrollable input form + fixed button bar ────────────────
        left_outer = ttk.Frame(outer, width=330)
        left_outer.grid(row=0, column=0, sticky=NSEW, padx=(10, 4), pady=8)
        left_outer.grid_propagate(False)
        left_outer.rowconfigure(0, weight=1)
        left_outer.rowconfigure(1, weight=0)
        left_outer.columnconfigure(0, weight=1)

        ci_canvas = tk.Canvas(left_outer, highlightthickness=0)
        ci_canvas.grid(row=0, column=0, sticky=NSEW)
        ci_sb = ttk.Scrollbar(left_outer, orient=VERTICAL, command=ci_canvas.yview)
        ci_sb.grid(row=0, column=1, sticky=NS)
        ci_canvas.configure(yscrollcommand=ci_sb.set)

        left = ttk.Frame(ci_canvas)
        _win_id = ci_canvas.create_window((0, 0), window=left, anchor=NW)

        def _on_frame_cfg(e):
            ci_canvas.configure(scrollregion=ci_canvas.bbox("all"))
        def _on_canvas_cfg(e):
            ci_canvas.itemconfig(_win_id, width=e.width)
        left.bind("<Configure>", _on_frame_cfg)
        ci_canvas.bind("<Configure>", _on_canvas_cfg)

        self._build_checkin_form(left)

        # ── Fixed button bar (always visible, below scrollable form) ──────
        ci_btn_outer = ttk.Frame(left_outer)
        ci_btn_outer.grid(row=1, column=0, columnspan=2, sticky=EW, padx=4, pady=(4, 6))

        self._ci_status_var = tk.StringVar()
        self._ci_status_lbl = ttk.Label(ci_btn_outer, textvariable=self._ci_status_var,
                                         font=("Segoe UI", 8), wraplength=280, justify=LEFT)
        self._ci_status_lbl.pack(anchor=W, pady=(0, 4))

        ttk.Button(ci_btn_outer, text="Check In", bootstyle=INFO,
                   command=self._do_checkin).pack(anchor=W)

        # Vertical separator
        ttk.Separator(outer, orient=VERTICAL).grid(row=0, column=0, sticky=NS,
                                                    padx=(338, 0), pady=4)

        # ── Right: running log ─────────────────────────────────────────────
        right = ttk.Frame(outer)
        right.grid(row=0, column=1, sticky=NSEW, padx=(8, 8), pady=8)

        ttk.Label(right, text="Session Check-Ins",
                  font=("Segoe UI", 10, "bold")).pack(anchor=W, pady=(0, 4))

        ci_log_frame = ttk.Frame(right)
        ci_log_frame.pack(fill=BOTH, expand=True)

        ci_cols = ("Instrument", "Barcode", "Student", "Date In")
        ci_log_sb = ttk.Scrollbar(ci_log_frame, orient=VERTICAL)
        self._ci_log_tree = ttk.Treeview(ci_log_frame, columns=ci_cols, show="headings",
                                          yscrollcommand=ci_log_sb.set, bootstyle=INFO,
                                          selectmode="browse")
        ci_log_sb.config(command=self._ci_log_tree.yview)
        ci_log_sb.pack(side=RIGHT, fill=Y)
        self._ci_log_tree.pack(fill=BOTH, expand=True)

        self._ci_log_tree.heading("Instrument", text="Instrument", anchor=W)
        self._ci_log_tree.heading("Barcode",    text="Barcode",    anchor=W)
        self._ci_log_tree.heading("Student",    text="Student",    anchor=W)
        self._ci_log_tree.heading("Date In",    text="Date In",    anchor=W)

        self._ci_log_tree.column("Instrument", width=180, stretch=True,  anchor=W)
        self._ci_log_tree.column("Barcode",    width=90,  stretch=False, anchor=W)
        self._ci_log_tree.column("Student",    width=130, stretch=True,  anchor=W)
        self._ci_log_tree.column("Date In",    width=90,  stretch=True,  anchor=W)

    def _build_checkin_form(self, parent):
        # ── Scan row: Barcode + Serial # side by side ──────────────────────
        scan_frame = tk.LabelFrame(parent, text=" Scan / Enter Identifier ",
                                   padx=8, pady=6, font=("Segoe UI", 9, "bold"))
        scan_frame.pack(fill=X, padx=4, pady=(4, 8))
        scan_frame.columnconfigure(0, weight=1)
        scan_frame.columnconfigure(1, weight=1)

        ttk.Label(scan_frame, text="Barcode:", font=("Segoe UI", 9, "bold")).grid(
            row=0, column=0, sticky=W)
        ttk.Label(scan_frame, text="Serial #:", font=("Segoe UI", 9, "bold")).grid(
            row=0, column=1, sticky=W, padx=(8, 0))

        self._ci_barcode_var = tk.StringVar()
        self._ci_barcode_entry = ttk.Entry(scan_frame, textvariable=self._ci_barcode_var,
                                            width=14, font=("Segoe UI", 11))
        self._ci_barcode_entry.grid(row=1, column=0, sticky=EW, pady=(2, 0))
        self._ci_barcode_entry.bind("<Return>", lambda e: self._ci_lookup_barcode())
        self._ci_barcode_entry.bind("<FocusOut>", lambda e: self._ci_lookup_barcode())

        self._ci_serial_var = tk.StringVar()
        self._ci_serial_entry = ttk.Entry(scan_frame, textvariable=self._ci_serial_var, width=14)
        self._ci_serial_entry.grid(row=1, column=1, sticky=EW, padx=(8, 0), pady=(2, 0))
        self._ci_serial_entry.bind("<Return>", lambda e: self._ci_lookup_serial())
        self._ci_serial_entry.bind("<FocusOut>", lambda e: self._ci_lookup_serial())

        # ── Instrument info ────────────────────────────────────────────────
        info_frame = tk.LabelFrame(parent, text=" Instrument Details ",
                                   padx=8, pady=6, font=("Segoe UI", 9, "bold"))
        info_frame.pack(fill=X, padx=4, pady=(0, 8))

        self._ci_info_labels = {}
        for label, key in [
            ("Description",    "description"),
            ("Brand / Model",  "_brand_model"),
            ("Serial #",       "serial_no"),
            ("Condition",      "condition"),
            ("Assigned To",    "_assigned_to"),
            ("Checked Out On", "_date_out"),
        ]:
            row = ttk.Frame(info_frame)
            row.pack(fill=X, pady=1)
            ttk.Label(row, text=f"{label}:", font=("Segoe UI", 8, "bold"),
                      width=13, anchor=W).pack(side=LEFT)
            lbl = ttk.Label(row, text="—", font=("Segoe UI", 8), anchor=W)
            lbl.pack(side=LEFT, fill=X, expand=True)
            self._ci_info_labels[key] = lbl

        # ── Date returned ──────────────────────────────────────────────────
        date_frame = ttk.Frame(parent)
        date_frame.pack(fill=X, padx=4, pady=(0, 6))
        ttk.Label(date_frame, text="Date Returned:",
                  font=("Segoe UI", 9, "bold")).pack(anchor=W)
        self._ci_date_var = tk.StringVar(value=datetime.today().strftime("%Y-%m-%d"))
        ttk.Entry(date_frame, textvariable=self._ci_date_var, width=16).pack(
            anchor=W, pady=(2, 0))

        # ── Condition at return ────────────────────────────────────────────
        cond_frame = ttk.Frame(parent)
        cond_frame.pack(fill=X, padx=4, pady=(0, 6))
        ttk.Label(cond_frame, text="Condition at Return:",
                  font=("Segoe UI", 9, "bold")).pack(anchor=W)
        self._ci_condition_var = tk.StringVar()
        ttk.Combobox(cond_frame, textvariable=self._ci_condition_var,
                     values=["New", "Excellent", "Good", "Fair", "Poor", "Needs Repair"],
                     width=20, state="readonly").pack(anchor=W, pady=(2, 0))

        # ── Notes ──────────────────────────────────────────────────────────
        notes_frame = ttk.Frame(parent)
        notes_frame.pack(fill=X, padx=4, pady=(0, 6))
        ttk.Label(notes_frame, text="Notes (optional):",
                  font=("Segoe UI", 9, "bold")).pack(anchor=W)
        self._ci_notes = tk.Text(notes_frame, height=3, font=("Segoe UI", 9),
                                  relief="solid", bd=1, width=28)
        self._ci_notes.pack(fill=X, pady=(2, 0))


    # ──────────────────────────────────────────────── CI Lookup ──────────

    def _ci_lookup_barcode(self):
        barcode = self._ci_barcode_var.get().strip()
        if not barcode:
            return
        instrument = self.db.get_instrument_by_barcode(barcode)
        if not instrument:
            self._ci_clear_fields()
            self._ci_set_status(f"No instrument found for barcode '{barcode}'.", error=True)
            return
        # Clear serial field to avoid double-lookup conflict
        self._ci_serial_var.set("")
        self._ci_fill_fields(instrument)

    def _ci_lookup_serial(self):
        serial = self._ci_serial_var.get().strip()
        if not serial:
            return
        instrument = self.db.get_instrument_by_serial(serial)
        if not instrument:
            self._ci_clear_fields()
            self._ci_set_status(f"No instrument found for serial # '{serial}'.", error=True)
            return
        # Clear barcode field to avoid double-lookup conflict
        self._ci_barcode_var.set("")
        self._ci_fill_fields(instrument)

    def _ci_fill_fields(self, instrument):
        self._ci_instrument = dict(instrument)
        brand_model = " ".join(filter(None, [
            instrument["brand"] or "", instrument["model"] or ""
        ]))
        active = self.db.get_active_checkout(instrument["id"])
        self._ci_checkout = dict(active) if active else None

        self._ci_info_labels["description"].config(text=instrument["description"] or "—")
        self._ci_info_labels["_brand_model"].config(text=brand_model or "—")
        self._ci_info_labels["serial_no"].config(text=instrument["serial_no"] or "—")
        self._ci_info_labels["condition"].config(text=instrument["condition"] or "—")

        if active:
            self._ci_info_labels["_assigned_to"].config(
                text=active["student_name"] or "—", foreground="#8B4000")
            self._ci_info_labels["_date_out"].config(
                text=active["date_assigned"] or "—", foreground="#8B4000")
            self._ci_set_status(
                f"Ready to check in: {instrument['description']}", error=False)
        else:
            self._ci_info_labels["_assigned_to"].config(
                text="Not checked out", foreground="#888")
            self._ci_info_labels["_date_out"].config(text="—", foreground="")
            self._ci_set_status("This instrument is not currently checked out.", error=True)

    def _ci_clear_fields(self):
        self._ci_instrument = None
        self._ci_checkout = None
        for lbl in self._ci_info_labels.values():
            lbl.config(text="—", foreground="")
        self._ci_set_status("", error=False)

    def _ci_set_status(self, msg: str, error: bool = False):
        self._ci_status_var.set(msg)
        self._ci_status_lbl.config(foreground="#CC0000" if error else "#2a7a2a")

    # ──────────────────────────────────────────────── Check In logic ──────

    def _do_checkin(self):
        if not self._ci_instrument:
            self._ci_set_status("Scan or enter a barcode / serial # first.", error=True)
            self._ci_barcode_entry.focus_set()
            return
        if not self._ci_checkout:
            self._ci_set_status("This instrument is not currently checked out.", error=True)
            return

        date_returned = self._ci_date_var.get().strip() or datetime.today().strftime("%Y-%m-%d")
        notes = self._ci_notes.get("1.0", "end").strip()
        condition = self._ci_condition_var.get()
        if condition:
            notes = f"Condition at return: {condition}. {notes}".strip(". ")

        self.db.checkin_instrument(self._ci_checkout["id"], date_returned, notes)

        # Update instrument condition if provided
        if condition:
            instr_data = dict(self._ci_instrument)
            instr_data["condition"] = condition
            instr_data.setdefault("is_active", 1)
            self.db.update_instrument(self._ci_instrument["id"], instr_data)

        # Add to session log
        desc = self._ci_instrument.get("description", "")
        barcode = (self._ci_instrument.get("barcode") or
                   self._ci_instrument.get("district_no") or "")
        student_name = self._ci_checkout.get("student_name", "")

        self._ci_log_tree.insert("", 0, values=(desc, barcode, student_name, date_returned))

        self._ci_set_status(f"Checked in: {desc} ← {student_name}", error=False)

        # Refresh inventory list in real time
        if self._refresh_callback:
            self._refresh_callback()

        # Reset all CI fields
        self._ci_instrument = None
        self._ci_checkout = None
        self._ci_barcode_var.set("")
        self._ci_serial_var.set("")
        self._ci_condition_var.set("")
        self._ci_notes.delete("1.0", "end")
        for lbl in self._ci_info_labels.values():
            lbl.config(text="—", foreground="")
        self._ci_barcode_entry.focus_set()

    # ─────────────────────────────────────────────────── Barcode lookup ──

    def _lookup_barcode(self):
        barcode = self._barcode_var.get().strip()
        if not barcode:
            self._clear_instrument_fields()
            return

        instrument = self.db.get_instrument_by_barcode(barcode)
        if not instrument:
            self._clear_instrument_fields()
            self._set_status(f"No instrument found for barcode '{barcode}'.", error=True)
            return

        self._instrument = dict(instrument)
        brand_model = " ".join(filter(None, [
            instrument["brand"] or "", instrument["model"] or ""
        ]))
        active = self.db.get_active_checkout(instrument["id"])
        status = "Checked Out" if active else "Available"

        self._info_labels["description"].config(text=instrument["description"] or "—")
        self._info_labels["_brand_model"].config(text=brand_model or "—")
        self._info_labels["serial_no"].config(text=instrument["serial_no"] or "—")
        self._info_labels["condition"].config(text=instrument["condition"] or "—")
        self._info_labels["_status"].config(
            text=status,
            foreground="#CC0000" if active else "#1a7a1a"
        )

        if active:
            self._set_status(
                f"Already checked out to {active['student_name']}. "
                "Check it in first.", error=True)
        else:
            self._set_status(f"Instrument found: {instrument['description']}", error=False)

    def _clear_instrument_fields(self):
        self._instrument = None
        for lbl in self._info_labels.values():
            lbl.config(text="—", foreground="")
        self._set_status("", error=False)

    def _set_status(self, msg: str, error: bool = False):
        self._status_var.set(msg)
        self._status_lbl.config(foreground="#CC0000" if error else "#2a7a2a")

    # ─────────────────────────────────────────────── Student ID lookup ──

    def _lookup_student_id(self):
        sid = self._sid_var.get().strip()
        if not sid:
            return
        student = self.db.find_student_by_student_id(sid)
        if student:
            name = f"{student['first_name']} {student['last_name']}"
            self._ac_selecting = True
            self._student_var.set(name)
            self._ac_selecting = False
            self._selected_student_id = student["id"]
            self._collapse_ac()
        # Don't warn if not found — student might be typed manually

    # ──────────────────────────────────────────────── Autocomplete ─────

    def _on_name_changed(self, *args):
        if self._ac_selecting:
            return
        self._selected_student_id = None
        text = self._student_var.get().strip().lower()
        if not text:
            self._collapse_ac()
            return
        matches = [name for name, _ in self._student_list if text in name.lower()]
        self._ac_listbox.delete(0, END)
        if matches:
            for m in matches[:8]:
                self._ac_listbox.insert(END, m)
            self._ac_container.config(height=min(len(matches), 8) * 18 + 4)
        else:
            self._collapse_ac()

    def _collapse_ac(self):
        self._ac_listbox.delete(0, END)
        self._ac_container.config(height=1)

    def _focus_ac_list(self, event=None):
        if self._ac_listbox.size() > 0:
            self._ac_listbox.focus_set()
            self._ac_listbox.selection_set(0)

    def _on_ac_select(self, event=None):
        sel = self._ac_listbox.curselection()
        if not sel:
            return
        name = self._ac_listbox.get(sel[0])
        for n, s in self._student_list:
            if n == name:
                self._selected_student_id = s["id"]
                break
        self._ac_selecting = True
        self._student_var.set(name)
        self._ac_selecting = False
        self._collapse_ac()
        self._student_entry.focus_set()

    # ─────────────────────────────────────────────────── Checkout logic ──

    def _validate_checkout(self) -> bool:
        """Returns True if the form is ready to check out. Shows inline status on error."""
        if not self._instrument:
            self._set_status("Scan or enter a barcode first.", error=True)
            self._barcode_entry.focus_set()
            return False

        active = self.db.get_active_checkout(self._instrument["id"])
        if active:
            self._set_status(
                f"Already checked out to {active['student_name']}. "
                "Check it in first.", error=True)
            return False

        if not self._student_var.get().strip():
            self._set_status("Enter a student name.", error=True)
            self._student_entry.focus_set()
            return False

        return True

    def _do_checkout(self, generate_form: bool = False):
        if not self._validate_checkout():
            return

        student_name = self._student_var.get().strip()
        student_id   = self._selected_student_id

        # Try name lookup if not resolved via autocomplete/student-id
        if student_id is None:
            parts = student_name.split(None, 1)
            first = parts[0] if parts else student_name
            last  = parts[1] if len(parts) > 1 else ""
            found = self.db.find_student_by_name(first, last)
            if found:
                student_id = found["id"]

        date_assigned = datetime.today().strftime("%Y-%m-%d")
        try:
            due_date = self._due_date_entry.entry.get().strip()
        except Exception:
            due_date = _default_return_date().strftime("%Y-%m-%d")

        checkout_id = self.db.checkout_instrument(
            self._instrument["id"], student_id, student_name,
            date_assigned, due_date=due_date
        )

        # Generate form if requested
        form_path = None
        if generate_form:
            try:
                from pdf_generator import generate_form_for_checkout
                form_path = generate_form_for_checkout(
                    self.db, checkout_id, self.base_dir)
                self.db.mark_form_generated(checkout_id)
            except Exception as e:
                Messagebox.show_error(
                    f"Checkout saved, but form generation failed:\n{e}",
                    title="Form Error", parent=self)

        # Add to session log
        desc = self._instrument.get("description", "")
        barcode = self._instrument.get("barcode") or self._instrument.get("district_no") or ""
        instrument_label = f"{desc} ({barcode})" if barcode else desc

        form_label = "Open" if form_path else ""
        iid = self._log_tree.insert("", 0, values=(instrument_label, student_name, form_label),
                                     tags=("has_form",) if form_path else ())
        if form_path:
            self._log_form_paths[iid] = form_path

        self._set_status(
            f"Checked out: {desc} → {student_name}" +
            (" (form generated)" if form_path else ""),
            error=False
        )

        # Refresh the inventory list in real time
        if self._refresh_callback:
            self._refresh_callback()

        # Reset all fields for the next entry
        self._instrument = None
        self._barcode_var.set("")
        self._sid_var.set("")
        self._student_var.set("")
        self._selected_student_id = None
        self._collapse_ac()
        for lbl in self._info_labels.values():
            lbl.config(text="—", foreground="")
        self._barcode_entry.focus_set()

    def _do_checkout_with_form(self):
        self._do_checkout(generate_form=True)

    def _open_form_from_log(self, event=None):
        sel = self._log_tree.selection()
        if not sel:
            return
        iid = sel[0]
        path = self._log_form_paths.get(iid)
        if path and os.path.isfile(path):
            os.startfile(path)
        elif path:
            Messagebox.show_warning(
                f"Form file not found:\n{path}", title="File Not Found", parent=self)
