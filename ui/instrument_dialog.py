"""
ui/instrument_dialog.py - Add / Edit instrument dialog
"""

import tkinter as tk
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from ttkbootstrap.dialogs import Messagebox
from datetime import datetime


CONDITION_OPTIONS = ["New", "Excellent", "Good", "Fair", "Poor", "Needs Repair",
                     "Unrepairable", "Unknown"]
CATEGORY_OPTIONS = [
    "Flute", "Oboe", "Clarinet", "Bass Clarinet", "Bassoon",
    "Alto Saxophone", "Tenor Saxophone", "Baritone Saxophone",
    "Trumpet", "French Horn", "Trombone", "Baritone", "Euphonium", "Tuba",
    "Percussion", "Mallets", "Snare Drum", "Bass Drum", "Other Percussion",
    "String Bass", "Cello", "Viola", "Violin",
    "Piano", "Guitar", "Other",
]


class InstrumentDialog(ttk.Toplevel):
    def __init__(self, parent, db, instrument_id=None):
        super().__init__(parent)
        self.db = db
        self.instrument_id = instrument_id
        self._result = None

        title = "Edit Instrument" if instrument_id else "Add New Instrument"
        self.title(title)
        self.resizable(True, True)
        self.grab_set()
        self.lift()

        self._vars = {}
        self._build()

        if instrument_id:
            self._load_instrument(instrument_id)

        from ui.theme import fit_window
        fit_window(self, 680, 720)

    # ───────────────────────────────────────────────────── Build UI ──────────

    def _build(self):
        # Header
        hdr = ttk.Frame(self, bootstyle=PRIMARY)
        hdr.pack(fill=X)
        title = "Edit Instrument" if self.instrument_id else "Add New Instrument"
        ttk.Label(hdr, text=title, font=("Segoe UI", 13, "bold"),
                  bootstyle=(INVERSE, PRIMARY)).pack(pady=12, padx=16, anchor=W)

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
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(content_window, width=e.width))

        # Mouse wheel scrolling
        def _on_mousewheel(event):
            try:
                canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
            except tk.TclError:
                pass
        canvas.bind_all("<MouseWheel>", _on_mousewheel)
        self.bind("<Destroy>", lambda e: canvas.unbind_all("<MouseWheel>"))

        self._build_sections(content)

        # ── Quick actions (only when editing an existing instrument) ──────────
        if self.instrument_id:
            self._action_bar = ttk.Frame(self, bootstyle=LIGHT)
            self._action_bar.pack(fill=X)
            self._refresh_action_bar()

        # Buttons
        btn_frame = ttk.Frame(self)
        btn_frame.pack(fill=X, padx=16, pady=10)

        if self.instrument_id:
            ttk.Button(btn_frame, text="Duplicate as New",
                       bootstyle=(SECONDARY, OUTLINE),
                       command=self._duplicate).pack(side=LEFT, padx=4)
            ttk.Button(btn_frame, text="Mark Inactive",
                       bootstyle=(DANGER, OUTLINE),
                       command=self._mark_inactive).pack(side=LEFT, padx=4)

        ttk.Button(btn_frame, text="Cancel", bootstyle=(SECONDARY, OUTLINE),
                   command=self.destroy).pack(side=RIGHT, padx=4)
        ttk.Button(btn_frame, text="Save", bootstyle=SUCCESS,
                   command=self._save).pack(side=RIGHT, padx=4)

    def _build_sections(self, parent):
        # ── Section: Basic Info ────────────────────────────────────────────────
        self._section(parent, "Basic Information")
        basic = ttk.Frame(parent)
        basic.pack(fill=X, padx=16, pady=(0, 8))

        row0 = ttk.Frame(basic)
        row0.pack(fill=X, pady=2)
        self._field(row0, "Category", "category", widget="combobox",
                    options=CATEGORY_OPTIONS, side=LEFT, width=22)
        self._field(row0, "Description *", "description", side=LEFT, width=30)

        row1 = ttk.Frame(basic)
        row1.pack(fill=X, pady=2)
        self._field(row1, "Brand", "brand", side=LEFT, width=22)
        self._field(row1, "Model", "model", side=LEFT, width=30)

        row2 = ttk.Frame(basic)
        row2.pack(fill=X, pady=2)
        self._field(row2, "Condition", "condition", widget="combobox",
                    options=CONDITION_OPTIONS, side=LEFT, width=22)
        self._field(row2, "Quantity", "quantity", side=LEFT, width=10)

        # ── Section: ID Numbers ───────────────────────────────────────────────
        self._section(parent, "Identification")
        ids = ttk.Frame(parent)
        ids.pack(fill=X, padx=16, pady=(0, 8))

        row3 = ttk.Frame(ids)
        row3.pack(fill=X, pady=2)
        self._field(row3, "Barcode (District #)", "barcode", side=LEFT, width=22)
        self._field(row3, "Serial #", "serial_no", side=LEFT, width=22)

        row4 = ttk.Frame(ids)
        row4.pack(fill=X, pady=2)
        self._field(row4, "Case #", "case_no", side=LEFT, width=22)
        self._field(row4, "PO Number", "po_number", side=LEFT, width=22)

        # ── Section: Financial ────────────────────────────────────────────────
        self._section(parent, "Financial")
        fin = ttk.Frame(parent)
        fin.pack(fill=X, padx=16, pady=(0, 8))

        row5 = ttk.Frame(fin)
        row5.pack(fill=X, pady=2)
        self._field(row5, "Amount Paid ($)", "amount_paid", side=LEFT, width=18)
        self._field(row5, "Est. Value ($)", "est_value", side=LEFT, width=18)

        row6 = ttk.Frame(fin)
        row6.pack(fill=X, pady=2)
        self._field(row6, "Date Purchased", "date_purchased", side=LEFT, width=18,
                    placeholder="YYYY-MM-DD")
        self._field(row6, "Year Purchased", "year_purchased", side=LEFT, width=12)
        self._field(row6, "Last Service", "last_service", side=LEFT, width=18,
                    placeholder="YYYY-MM-DD")

        # ── Section: Storage ──────────────────────────────────────────────────
        self._section(parent, "Storage")
        stor = ttk.Frame(parent)
        stor.pack(fill=X, padx=16, pady=(0, 8))

        row7 = ttk.Frame(stor)
        row7.pack(fill=X, pady=2)
        self._field(row7, "Locker", "locker", side=LEFT, width=16)
        self._field(row7, "Lock #", "lock_no", side=LEFT, width=14)
        self._field(row7, "Combination", "combo", side=LEFT, width=16)

        # ── Section: Notes ────────────────────────────────────────────────────
        self._section(parent, "Accessories & Notes")
        notes = ttk.Frame(parent)
        notes.pack(fill=X, padx=16, pady=(0, 8))

        ttk.Label(notes, text="Accessories:", font=("Segoe UI", 9)).pack(anchor=W)
        acc_var = tk.StringVar()
        self._vars["accessories"] = acc_var
        ttk.Entry(notes, textvariable=acc_var, width=70).pack(fill=X, pady=2)

        ttk.Label(notes, text="Comments / Notes:", font=("Segoe UI", 9)).pack(anchor=W, pady=(6, 0))
        self._comments_text = tk.Text(notes, height=4, font=("Segoe UI", 9),
                                       relief="solid", bd=1, wrap=WORD)
        self._comments_text.pack(fill=X, pady=2)

    def _refresh_action_bar(self):
        """(Re)build the quick-action buttons based on the instrument's current
        checkout / loan status."""
        for w in self._action_bar.winfo_children():
            w.destroy()
        ttk.Label(self._action_bar, text="Quick actions:",
                  font=("Segoe UI", 8, "bold")).pack(side=LEFT, padx=(10, 6), pady=6)

        loan = self.db.get_active_loan(self.instrument_id)
        if loan:
            ttk.Label(self._action_bar,
                      text=f"🏫 On loan to {loan['school']}",
                      font=("Segoe UI", 8), foreground="#1f5fbf").pack(side=LEFT, padx=(0, 8))
            ttk.Button(self._action_bar, text="↩ Return from Loan", bootstyle=PRIMARY,
                       command=self._return_loan_action).pack(side=LEFT, padx=2, pady=4)
            ttk.Button(self._action_bar, text="🔧 Add Repair", bootstyle=SECONDARY,
                       command=self._repair_action).pack(side=LEFT, padx=2, pady=4)
            return

        actives = self.db.get_active_checkouts_for_instrument(self.instrument_id)
        if actives:
            names = ", ".join(a["student_name"] or "?" for a in actives)
            ttk.Label(self._action_bar, text=f"Checked out to {names}",
                      font=("Segoe UI", 8), foreground="#8B4000").pack(side=LEFT, padx=(0, 8))
            ttk.Button(self._action_bar, text="📥 Check In", bootstyle=INFO,
                       command=self._checkin_action).pack(side=LEFT, padx=2, pady=4)
        ttk.Button(self._action_bar, text="📤 Check Out", bootstyle=WARNING,
                   command=self._checkout_action).pack(side=LEFT, padx=2, pady=4)
        ttk.Button(self._action_bar, text="🏫 Loan to School", bootstyle=(PRIMARY, OUTLINE),
                   command=self._loan_action).pack(side=LEFT, padx=2, pady=4)
        ttk.Button(self._action_bar, text="🔧 Add Repair", bootstyle=SECONDARY,
                   command=self._repair_action).pack(side=LEFT, padx=2, pady=4)

    def _checkout_action(self):
        from ui.checkout_dialog import CheckoutDialog
        dlg = CheckoutDialog(self, self.db, instrument_id=self.instrument_id, mode="checkout")
        self.wait_window(dlg)
        self._result = "saved"
        self._load_instrument(self.instrument_id)
        self._refresh_action_bar()

    def _checkin_action(self):
        actives = [dict(a) for a in self.db.get_active_checkouts_for_instrument(self.instrument_id)]
        if not actives:
            self._refresh_action_bar()
            return
        checkout = actives[0] if len(actives) == 1 else self._pick_checkout(actives)
        if not checkout:
            return
        from ui.checkout_dialog import CheckoutDialog
        dlg = CheckoutDialog(self, self.db, instrument_id=self.instrument_id,
                             mode="checkin", checkout_data=checkout)
        self.wait_window(dlg)
        self._result = "saved"
        self._load_instrument(self.instrument_id)
        self._refresh_action_bar()

    def _pick_checkout(self, actives):
        win = ttk.Toplevel(self)
        win.title("Which checkout to check in?")
        win.grab_set()
        ttk.Label(win, text="Choose which person is returning it:",
                  font=("Segoe UI", 9)).pack(anchor=W, padx=16, pady=(14, 6))
        lb = tk.Listbox(win, font=("Segoe UI", 9), height=min(len(actives), 8), width=44)
        lb.pack(fill=BOTH, expand=True, padx=16)
        for a in actives:
            lb.insert("end", f"{a.get('student_name') or '?'}   (out {a.get('date_assigned') or '—'})")
        lb.selection_set(0)
        res = {"c": None}
        def _ok():
            sel = lb.curselection()
            if sel:
                res["c"] = actives[sel[0]]
            win.destroy()
        btns = ttk.Frame(win); btns.pack(pady=12)
        ttk.Button(btns, text="OK", bootstyle=PRIMARY, command=_ok).pack(side=LEFT, padx=4)
        ttk.Button(btns, text="Cancel", bootstyle=(SECONDARY, OUTLINE),
                   command=win.destroy).pack(side=LEFT, padx=4)
        from ui.theme import fit_window
        fit_window(win, 400, 260)
        self.wait_window(win)
        return res["c"]

    def _loan_action(self):
        from ui.checkout_dialog import LoanDialog
        dlg = LoanDialog(self, self.db, instrument_id=self.instrument_id)
        self.wait_window(dlg)
        self._result = "saved"
        self._load_instrument(self.instrument_id)
        self._refresh_action_bar()

    def _return_loan_action(self):
        loan = self.db.get_active_loan(self.instrument_id)
        if not loan:
            self._refresh_action_bar()
            return
        if Messagebox.yesno(f"Mark this instrument as returned from {loan['school']}?",
                            title="Return from Loan", parent=self) == "Yes":
            self.db.return_loan(loan["id"], datetime.today().strftime("%Y-%m-%d"))
            self._result = "saved"
            self._refresh_action_bar()

    def _repair_action(self):
        from ui.repair_dialog import RepairDialog
        dlg = RepairDialog(self, self.db, instrument_id=self.instrument_id, repair_id=None)
        self.wait_window(dlg)
        self._result = "saved"
        self._load_instrument(self.instrument_id)

    def _section(self, parent, title):
        f = ttk.Frame(parent)
        f.pack(fill=X, padx=8, pady=(10, 2))
        ttk.Label(f, text=title, font=("Segoe UI", 10, "bold"), bootstyle=PRIMARY).pack(side=LEFT)
        ttk.Separator(f).pack(side=LEFT, fill=X, expand=True, padx=8)

    def _field(self, parent, label, key, widget="entry", options=None,
               side=LEFT, width=20, placeholder=""):
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

    # ───────────────────────────────────────────────────── Data Methods ───────

    def _load_instrument(self, instrument_id: int):
        row = self.db.get_instrument(instrument_id)
        if not row:
            return
        for key, var in self._vars.items():
            val = row[key] if key in row.keys() else None
            var.set("" if val is None else str(val))

        # Barcode and District # are one identifier now — show whichever is set.
        if "barcode" in self._vars and not self._vars["barcode"].get():
            dn = row["district_no"] if "district_no" in row.keys() else None
            if dn:
                self._vars["barcode"].set(str(dn))

        comments = row["comments"] or ""
        self._comments_text.delete("1.0", "end")
        self._comments_text.insert("1.0", comments)

    def _collect_data(self) -> dict:
        data = {k: v.get().strip() for k, v in self._vars.items()}
        data["comments"] = self._comments_text.get("1.0", "end").strip()
        # Keep district_no in sync with the merged Barcode field so existing
        # code that reads either column stays consistent.
        data["district_no"] = data.get("barcode", "")

        # Type coercions
        for f in ("amount_paid", "est_value"):
            try:
                data[f] = float(data[f].replace("$", "").replace(",", "")) if data[f] else 0.0
            except ValueError:
                data[f] = 0.0
        try:
            data["quantity"] = int(data["quantity"]) if data["quantity"] else 1
        except ValueError:
            data["quantity"] = 1

        if self.instrument_id:
            data["is_active"] = 1

        return data

    def _validate(self, data: dict) -> bool:
        if not data.get("description"):
            Messagebox.show_warning("Description is required.", title="Validation")
            return False
        return True

    def _save(self):
        data = self._collect_data()
        if not self._validate(data):
            return
        if self.instrument_id:
            self.db.update_instrument(self.instrument_id, data)
        else:
            self.db.add_instrument(data)
        self._result = "saved"
        self.destroy()

    def _duplicate(self):
        data = self._collect_data()
        # Clear ID fields so it's treated as new
        data.pop("is_active", None)
        for field in ("barcode", "district_no", "serial_no"):
            data[field] = ""
        new_id = self.db.add_instrument(data)
        Messagebox.show_info(f"Instrument duplicated (ID: {new_id}). Editing the new copy.",
                             title="Duplicated")
        self.instrument_id = new_id
        self._load_instrument(new_id)

    def _mark_inactive(self):
        if Messagebox.yesno(
            "Mark this instrument as inactive? It will be hidden from the main list "
            "but all history will be preserved.",
            title="Confirm"
        ) == "Yes":
            self.db.deactivate_instrument(self.instrument_id)
            self._result = "deactivated"
            self.destroy()
