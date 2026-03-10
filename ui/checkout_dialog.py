"""
ui/checkout_dialog.py - Check out / Check in instrument dialog
"""

import tkinter as tk
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from ttkbootstrap.dialogs import Messagebox
from datetime import datetime, date as dt_date


class CheckoutDialog(ttk.Toplevel):
    def __init__(self, parent, db, instrument_id: int, mode: str = "checkout",
                 checkout_data: dict = None):
        """
        mode: 'checkout' or 'checkin'
        checkout_data: dict of the active checkout record (for checkin mode)
        """
        super().__init__(parent)
        self.db = db
        self.instrument_id = instrument_id
        self.mode = mode
        self.checkout_data = checkout_data or {}

        self.title("Check Out Instrument" if mode == "checkout" else "Check In Instrument")
        self.resizable(False, False)
        self.grab_set()
        self.lift()

        self._build()

        from ui.theme import fit_window
        fit_window(self, 480, 500)

    def _build(self):
        instrument = self.db.get_instrument(self.instrument_id)
        if not instrument:
            self.destroy()
            return

        # ── Header ────────────────────────────────────────────────────────────
        hdr_style = WARNING if self.mode == "checkout" else INFO
        hdr = ttk.Frame(self, bootstyle=hdr_style)
        hdr.pack(fill=X)
        icon = "📤" if self.mode == "checkout" else "📥"
        title_text = f"{icon}  {'Check Out' if self.mode == 'checkout' else 'Check In'} Instrument"
        ttk.Label(hdr, text=title_text, font=("Segoe UI", 13, "bold"),
                  bootstyle=(INVERSE, hdr_style)).pack(pady=12, padx=16, anchor=W)

        # ── Buttons (packed before main so they always stay visible) ─────────
        btn_frame = ttk.Frame(self)
        btn_frame.pack(fill=X, padx=20, pady=12, side=BOTTOM)
        ttk.Button(btn_frame, text="Cancel", bootstyle=(SECONDARY, OUTLINE),
                   command=self.destroy).pack(side=RIGHT, padx=4)
        action_text = "Check Out" if self.mode == "checkout" else "Check In"
        action_style = WARNING if self.mode == "checkout" else INFO
        ttk.Button(btn_frame, text=action_text, bootstyle=action_style,
                   command=self._save).pack(side=RIGHT, padx=4)

        main = ttk.Frame(self)
        main.pack(fill=BOTH, expand=True, padx=20, pady=12)

        # ── Instrument Info (read-only) ────────────────────────────────────────
        info_frame = tk.LabelFrame(main, text=" Instrument ", padx=8, pady=6,
                                   font=("Segoe UI", 9, "bold"))
        info_frame.pack(fill=X, pady=(0, 12))

        desc = instrument["description"] or ""
        brand_model = " ".join(filter(None, [instrument["brand"] or "", instrument["model"] or ""]))
        barcode = instrument["barcode"] or instrument["district_no"] or ""
        serial = instrument["serial_no"] or ""
        condition = instrument["condition"] or ""

        for label, value in [
            ("Description", desc),
            ("Brand / Model", brand_model),
            ("Barcode", barcode),
            ("Serial #", serial),
            ("Condition", condition),
        ]:
            r = ttk.Frame(info_frame)
            r.pack(fill=X, pady=1)
            ttk.Label(r, text=f"{label}:", font=("Segoe UI", 8, "bold"),
                      width=16, anchor=W).pack(side=LEFT)
            ttk.Label(r, text=value, font=("Segoe UI", 8)).pack(side=LEFT)

        # ── Mode-Specific Section ─────────────────────────────────────────────
        if self.mode == "checkout":
            self._build_checkout_form(main)
        else:
            self._build_checkin_form(main)


    def _build_checkout_form(self, parent):
        form = tk.LabelFrame(parent, text=" Check Out Details ", padx=8, pady=6,
                             font=("Segoe UI", 9, "bold"))
        form.pack(fill=BOTH, expand=True, pady=(0, 8))

        self._ac_selecting = False
        self._selected_student_id = None

        # Load all student names up front for autocomplete (deduplicated).
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

        # ── Student Name ───────────────────────────────────────────────────────
        ttk.Label(form, text="Student Name:", font=("Segoe UI", 9, "bold")).pack(anchor=W)

        self._student_var = tk.StringVar()
        self._student_entry = ttk.Entry(form, textvariable=self._student_var, width=42)
        self._student_entry.pack(fill=X, pady=(2, 0))
        self._student_entry.focus_set()

        # Autocomplete container — always packed here so it stays between entry and date
        # pack_propagate(False) lets us control height without children forcing it
        self._ac_container = ttk.Frame(form, relief="solid", borderwidth=1)
        self._ac_container.pack(fill=X)
        self._ac_container.pack_propagate(False)
        self._ac_container.config(height=1)  # Collapsed initially

        self._ac_listbox = tk.Listbox(
            self._ac_container, font=("Segoe UI", 9),
            selectmode=SINGLE, activestyle="underline",
            relief="flat", bd=0
        )
        self._ac_listbox.pack(fill=BOTH, expand=True)

        # ── Return Date ────────────────────────────────────────────────────────
        ttk.Label(form, text="Return Date:", font=("Segoe UI", 9, "bold")).pack(
            anchor=W, pady=(14, 0))

        default_date = self._default_return_date()
        self._due_date_entry = ttk.DateEntry(
            form, dateformat="%Y-%m-%d", startdate=default_date, bootstyle=WARNING
        )
        self._due_date_entry.pack(anchor=W, pady=(2, 0))

        # ── Bind Events ────────────────────────────────────────────────────────
        self._student_var.trace_add("write", self._on_name_changed)
        self._ac_listbox.bind("<<ListboxSelect>>", self._on_ac_select)
        self._ac_listbox.bind("<Return>", self._on_ac_select)
        self._ac_listbox.bind("<Escape>", lambda e: (self._collapse_ac(), self._student_entry.focus_set()))
        self._student_entry.bind("<Down>", self._focus_ac_list)
        self._student_entry.bind("<Escape>", lambda e: self._collapse_ac())

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
            row_px = 18
            self._ac_container.config(height=min(len(matches), 8) * row_px + 4)
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

    def _default_return_date(self) -> dt_date:
        today = dt_date.today()
        end_year = today.year + 1 if today.month >= 8 else today.year
        return dt_date(end_year, 6, 20)

    def _build_checkin_form(self, parent):
        form = tk.LabelFrame(parent, text=" Check In Details ", padx=8, pady=6,
                             font=("Segoe UI", 9, "bold"))
        form.pack(fill=BOTH, expand=True, pady=(0, 8))
        form.columnconfigure(1, weight=1)

        student = self.checkout_data.get("student_name", "")
        date_out = self.checkout_data.get("date_assigned", "")

        ttk.Label(form, text="Currently Assigned To:", font=("Segoe UI", 9, "bold")).grid(
            row=0, column=0, sticky=W, pady=4)
        ttk.Label(form, text=student, font=("Segoe UI", 9)).grid(
            row=0, column=1, sticky=W, pady=4, padx=6)

        ttk.Label(form, text="Checked Out On:", font=("Segoe UI", 9, "bold")).grid(
            row=1, column=0, sticky=W, pady=4)
        ttk.Label(form, text=date_out, font=("Segoe UI", 9)).grid(
            row=1, column=1, sticky=W, pady=4, padx=6)

        ttk.Label(form, text="Date Returned:", font=("Segoe UI", 9, "bold")).grid(
            row=2, column=0, sticky=W, pady=4)
        self._date_var = tk.StringVar(value=datetime.today().strftime("%Y-%m-%d"))
        ttk.Entry(form, textvariable=self._date_var, width=16).grid(
            row=2, column=1, sticky=W, pady=4, padx=6)

        ttk.Label(form, text="Condition at Return:", font=("Segoe UI", 9, "bold")).grid(
            row=3, column=0, sticky=W, pady=4)
        self._condition_var = tk.StringVar()
        ttk.Combobox(form, textvariable=self._condition_var,
                     values=["New", "Excellent", "Good", "Fair", "Poor", "Needs Repair"],
                     width=18, state="readonly").grid(row=3, column=1, sticky=W, pady=4, padx=6)

        ttk.Label(form, text="Notes:", font=("Segoe UI", 9, "bold")).grid(
            row=4, column=0, sticky=NW, pady=4)
        self._notes_text = tk.Text(form, height=3, font=("Segoe UI", 9),
                                    relief="solid", bd=1, width=32)
        self._notes_text.grid(row=4, column=1, sticky=EW, pady=4, padx=6)

    def _save(self):
        if self.mode == "checkout":
            self._do_checkout()
        else:
            self._do_checkin()

    def _do_checkout(self):
        student_name = self._student_var.get().strip()
        if not student_name:
            Messagebox.show_warning("Please enter or select a student name.", title="Required")
            return

        student_id = self._selected_student_id
        if student_id is None:
            # Try to find in DB by name (First Last format)
            parts = student_name.split(None, 1)
            first = parts[0] if parts else student_name
            last = parts[1] if len(parts) > 1 else ""
            found = self.db.find_student_by_name(first, last)
            if found:
                student_id = found["id"]

        date_assigned = datetime.today().strftime("%Y-%m-%d")

        # Get return date from DateEntry
        try:
            due_date = self._due_date_entry.entry.get().strip()
        except Exception:
            due_date = ""

        self.db.checkout_instrument(
            self.instrument_id, student_id, student_name, date_assigned, due_date=due_date
        )
        self.destroy()

    def _do_checkin(self):
        date = self._date_var.get().strip()
        if not date:
            date = datetime.today().strftime("%Y-%m-%d")

        notes = self._notes_text.get("1.0", "end").strip()
        condition = getattr(self, "_condition_var", None)
        if condition and condition.get():
            notes = f"Condition at return: {condition.get()}. {notes}".strip(". ")

        checkout_id = self.checkout_data.get("id")
        if checkout_id:
            self.db.checkin_instrument(checkout_id, date, notes)

        if hasattr(self, "_condition_var") and self._condition_var.get():
            instr = self.db.get_instrument(self.instrument_id)
            if instr:
                data = dict(instr)
                data["condition"] = self._condition_var.get()
                data["is_active"] = data.get("is_active", 1)
                self.db.update_instrument(self.instrument_id, data)

        self.destroy()
