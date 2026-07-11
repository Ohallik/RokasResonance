"""
ui/checkout_dialog.py - Check out / Check in instrument dialog
"""

import tkinter as tk
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from ttkbootstrap.dialogs import Messagebox
from datetime import datetime, date as dt_date
from ui.names import display_full


def _record_needed_repair(parent, db, instrument_id, date, notes, student_name=None):
    """Create a pending repair record for an instrument returned in
    'Needs Repair' condition, and offer to open it for more detail."""
    desc = (notes or "").strip() or "Returned needing repair (details TBD)"
    who = (student_name or "").strip()
    full_notes = notes or ""
    if who:
        full_notes = (f"Reported at check-in from {who}. {notes}" if notes
                      else f"Reported at check-in from {who}.")
    try:
        db.add_repair({
            "instrument_id": instrument_id,
            "priority": 1,
            "date_added": date,
            "description": desc[:250],
            "notes": full_notes,
            "date_repaired": None,
        })
    except Exception:
        pass


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


    def _rental_label(self, rental_type: str) -> str:
        """Fee name + amount for the rental type, read from configured fee types."""
        want = "summer" if rental_type == "summer" else "school year"
        default_amt = 20.0 if rental_type == "summer" else 75.0
        try:
            for t in self.db.get_fee_types():
                n = (t["name"] or "").lower()
                if n.startswith("instrument rental") and want in n:
                    return f"${float(t['default_amount'] or default_amt):.0f}"
        except Exception:
            pass
        return f"${default_amt:.0f}"

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
        all_students = self.db.get_current_roster()
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
            (display_full(s), s) for s, _ in _seen.values()
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

        # ── Rental Fee Type ────────────────────────────────────────────────────
        # A rental fee is auto-added to Budget ▸ Student Fees. Default to the
        # $75 school-year fee; June checkouts default to the $20 summer fee.
        ttk.Label(form, text="Rental Fee:", font=("Segoe UI", 9, "bold")).pack(
            anchor=W, pady=(14, 0))
        self._rental_type_var = tk.StringVar(
            value="summer" if datetime.today().month == 6 else "school_year")
        rt = ttk.Frame(form)
        rt.pack(anchor=W, pady=(2, 0))
        ttk.Radiobutton(rt, text=f"School Year ({self._rental_label('school_year')})",
                        variable=self._rental_type_var, value="school_year").pack(anchor=W)
        ttk.Radiobutton(rt, text=f"Summer ({self._rental_label('summer')})",
                        variable=self._rental_type_var, value="summer").pack(anchor=W)

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
                     values=["New", "Excellent", "Good", "Fair", "Poor",
                             "Needs Repair", "Unrepairable"],
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

        rental_type = getattr(self, "_rental_type_var", None)
        rental_type = rental_type.get() if rental_type else "school_year"
        self.db.checkout_instrument(
            self.instrument_id, student_id, student_name, date_assigned,
            due_date=due_date, rental_type=rental_type,
        )
        self.destroy()

    def _do_checkin(self):
        date = self._date_var.get().strip()
        if not date:
            date = datetime.today().strftime("%Y-%m-%d")

        raw_notes = self._notes_text.get("1.0", "end").strip()
        condition = getattr(self, "_condition_var", None)
        cond_val = condition.get() if condition else ""
        notes = raw_notes
        if cond_val:
            notes = f"Condition at return: {cond_val}. {raw_notes}".strip(". ")

        checkout_id = self.checkout_data.get("id")
        if checkout_id:
            self.db.checkin_instrument(checkout_id, date, notes)

        if cond_val:
            instr = self.db.get_instrument(self.instrument_id)
            if instr:
                data = dict(instr)
                data["condition"] = cond_val
                data["is_active"] = data.get("is_active", 1)
                self.db.update_instrument(self.instrument_id, data)

        # If it came back needing repair, open a real (pending) repair record so
        # the info is tracked and can be printed for the technician — not lost
        # inside the returned checkout row.
        if cond_val == "Needs Repair":
            _record_needed_repair(self, self.db, self.instrument_id, date,
                                  raw_notes, self.checkout_data.get("student_name"))

        self.destroy()


class LoanDialog(ttk.Toplevel):
    """Loan an instrument out to another school.  While the loan is open the
    instrument is marked 'On Loan' and is unavailable for local checkout."""

    def __init__(self, parent, db, instrument_id: int):
        super().__init__(parent)
        self.db = db
        self.instrument_id = instrument_id
        self.saved = False

        self.title("Loan to Another School")
        self.resizable(False, False)
        self.grab_set()
        self.lift()

        self._vars = {}
        self._build()

        from ui.theme import fit_window
        fit_window(self, 460, 470)

    def _build(self):
        instrument = self.db.get_instrument(self.instrument_id)

        hdr = ttk.Frame(self, bootstyle=PRIMARY)
        hdr.pack(fill=X)
        ttk.Label(hdr, text="🏫  Loan to Another School", font=("Segoe UI", 13, "bold"),
                  bootstyle=(INVERSE, PRIMARY)).pack(pady=12, padx=16, anchor=W)

        btn_frame = ttk.Frame(self)
        btn_frame.pack(fill=X, padx=20, pady=12, side=BOTTOM)
        ttk.Button(btn_frame, text="Cancel", bootstyle=(SECONDARY, OUTLINE),
                   command=self.destroy).pack(side=RIGHT, padx=4)
        ttk.Button(btn_frame, text="Loan Out", bootstyle=PRIMARY,
                   command=self._save).pack(side=RIGHT, padx=4)

        main = ttk.Frame(self)
        main.pack(fill=BOTH, expand=True, padx=20, pady=12)

        if instrument:
            desc = instrument["description"] or ""
            brand = instrument["brand"] or ""
            barcode = instrument["barcode"] or instrument["district_no"] or ""
            ttk.Label(main, text=f"{desc}  {brand}".strip(),
                      font=("Segoe UI", 10, "bold")).pack(anchor=W)
            ttk.Label(main, text=f"Barcode: {barcode}", font=("Segoe UI", 8),
                      foreground="#888").pack(anchor=W, pady=(0, 8))

        def _field(label, key, required=False):
            ttk.Label(main, text=label + (" *" if required else ""),
                      font=("Segoe UI", 9, "bold")).pack(anchor=W, pady=(6, 0))
            var = tk.StringVar()
            self._vars[key] = var
            ttk.Entry(main, textvariable=var, width=44).pack(fill=X)
            return var

        _field("School", "school", required=True)
        _field("Teacher / Contact Name", "contact_name")
        _field("Contact Email", "contact_email")
        _field("Contact Phone", "contact_phone")

        ttk.Label(main, text="Expected Return Date:", font=("Segoe UI", 9, "bold")).pack(
            anchor=W, pady=(6, 0))
        self._due_entry = ttk.DateEntry(main, dateformat="%Y-%m-%d", bootstyle=PRIMARY)
        self._due_entry.pack(anchor=W, pady=(2, 0))

        ttk.Label(main, text="Notes:", font=("Segoe UI", 9, "bold")).pack(anchor=W, pady=(6, 0))
        self._notes = tk.Text(main, height=2, font=("Segoe UI", 9), relief="solid", bd=1)
        self._notes.pack(fill=X)

    def _save(self):
        school = self._vars["school"].get().strip()
        if not school:
            Messagebox.show_warning("Please enter the school the instrument is loaned to.",
                                    title="Required", parent=self)
            return
        try:
            due = self._due_entry.entry.get().strip()
        except Exception:
            due = ""
        self.db.add_loan({
            "instrument_id": self.instrument_id,
            "school": school,
            "contact_name": self._vars["contact_name"].get().strip(),
            "contact_email": self._vars["contact_email"].get().strip(),
            "contact_phone": self._vars["contact_phone"].get().strip(),
            "date_out": datetime.today().strftime("%Y-%m-%d"),
            "date_due": due,
            "notes": self._notes.get("1.0", "end").strip(),
        })
        self.saved = True
        self.destroy()


class ItemCheckoutDialog(ttk.Toplevel):
    """Check out a free-text item (mute, method book, marching lyre, …) that has
    no inventory record.  Borrower may be a student (autocomplete) or any typed
    name (a para, another teacher)."""

    def __init__(self, parent, db):
        super().__init__(parent)
        self.db = db
        self._selected_student_id = None
        self._ac_selecting = False

        self.title("Check Out Item")
        self.resizable(False, False)
        self.grab_set()
        self.lift()

        self._build()

        from ui.theme import fit_window
        fit_window(self, 460, 430)

    def _build(self):
        hdr = ttk.Frame(self, bootstyle=WARNING)
        hdr.pack(fill=X)
        ttk.Label(hdr, text="🎒  Check Out Item", font=("Segoe UI", 13, "bold"),
                  bootstyle=(INVERSE, WARNING)).pack(pady=12, padx=16, anchor=W)

        btn_frame = ttk.Frame(self)
        btn_frame.pack(fill=X, padx=20, pady=12, side=BOTTOM)
        ttk.Button(btn_frame, text="Cancel", bootstyle=(SECONDARY, OUTLINE),
                   command=self.destroy).pack(side=RIGHT, padx=4)
        ttk.Button(btn_frame, text="Check Out", bootstyle=WARNING,
                   command=self._save).pack(side=RIGHT, padx=4)

        form = ttk.Frame(self)
        form.pack(fill=BOTH, expand=True, padx=20, pady=12)

        # ── Item description ──────────────────────────────────────────────
        ttk.Label(form, text="Item *", font=("Segoe UI", 9, "bold")).pack(anchor=W)
        ttk.Label(form, text="e.g. Trumpet mute, method book, marching lyre",
                  font=("Segoe UI", 8), foreground="#888").pack(anchor=W)
        self._item_var = tk.StringVar()
        item_entry = ttk.Entry(form, textvariable=self._item_var, width=44)
        item_entry.pack(fill=X, pady=(2, 10))
        item_entry.focus_set()

        # ── Borrower name (student autocomplete, or any name) ─────────────
        ttk.Label(form, text="Checked out to *", font=("Segoe UI", 9, "bold")).pack(anchor=W)
        ttk.Label(form, text="Start typing a student, or type any name (para, staff).",
                  font=("Segoe UI", 8), foreground="#888").pack(anchor=W)
        self._name_var = tk.StringVar()
        self._name_entry = ttk.Entry(form, textvariable=self._name_var, width=44)
        self._name_entry.pack(fill=X, pady=(2, 0))

        self._ac_container = ttk.Frame(form, relief="solid", borderwidth=1)
        self._ac_container.pack(fill=X)
        self._ac_container.pack_propagate(False)
        self._ac_container.config(height=1)
        self._ac_listbox = tk.Listbox(self._ac_container, font=("Segoe UI", 9),
                                      selectmode=SINGLE, activestyle="underline",
                                      relief="flat", bd=0)
        self._ac_listbox.pack(fill=BOTH, expand=True)

        # Build student autocomplete list (current active roster only)
        _seen = {}
        for s in self.db.get_current_roster():
            has_sid = bool((s["student_id"] or "").strip())
            first_word = (s["first_name"] or "").split()[0].lower() if s["first_name"] else ""
            key = f"{first_word}|{(s['last_name'] or '').lower()}"
            if key not in _seen or (has_sid and not _seen[key][1]):
                _seen[key] = (dict(s), has_sid)
        self._student_list = [
            (display_full(s), s) for s, _ in _seen.values()
        ]

        # ── Return date ───────────────────────────────────────────────────
        ttk.Label(form, text="Return Date:", font=("Segoe UI", 9, "bold")).pack(
            anchor=W, pady=(12, 0))
        default_date = self._default_return_date()
        self._due_date_entry = ttk.DateEntry(form, dateformat="%Y-%m-%d",
                                             startdate=default_date, bootstyle=WARNING)
        self._due_date_entry.pack(anchor=W, pady=(2, 0))

        self._name_var.trace_add("write", self._on_name_changed)
        self._ac_listbox.bind("<<ListboxSelect>>", self._on_ac_select)
        self._ac_listbox.bind("<Return>", self._on_ac_select)
        self._name_entry.bind("<Down>", self._focus_ac_list)

    def _default_return_date(self) -> dt_date:
        today = dt_date.today()
        end_year = today.year + 1 if today.month >= 8 else today.year
        return dt_date(end_year, 6, 20)

    def _on_name_changed(self, *args):
        if self._ac_selecting:
            return
        self._selected_student_id = None
        text = self._name_var.get().strip().lower()
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
        self._name_var.set(name)
        self._ac_selecting = False
        self._collapse_ac()
        self._name_entry.focus_set()

    def _save(self):
        item = self._item_var.get().strip()
        name = self._name_var.get().strip()
        if not item:
            Messagebox.show_warning("Please describe the item.", title="Required", parent=self)
            return
        if not name:
            Messagebox.show_warning("Please enter who it is checked out to.",
                                    title="Required", parent=self)
            return

        student_id = self._selected_student_id
        if student_id is None:
            parts = name.split(None, 1)
            first = parts[0] if parts else name
            last = parts[1] if len(parts) > 1 else ""
            found = self.db.find_student_by_name(first, last)
            if found:
                student_id = found["id"]

        try:
            due_date = self._due_date_entry.entry.get().strip()
        except Exception:
            due_date = ""

        self.db.checkout_item(
            student_id, name, item, datetime.today().strftime("%Y-%m-%d"),
            due_date=due_date,
        )
        self.destroy()
