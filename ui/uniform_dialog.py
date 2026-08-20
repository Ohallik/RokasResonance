"""
ui/uniform_dialog.py — Add/Edit a uniform garment, and check a single garment
out to / in from a student.

Mirrors ui/instrument_dialog.py + ui/checkout_dialog.py, but for garments:
  • no rental fee is charged on checkout,
  • a piece can be assigned to only one student at a time (enforced in the DB),
  • the checkout form surfaces a "last year / suggested size up" hint.
"""

import tkinter as tk
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from ttkbootstrap.dialogs import Messagebox
from datetime import datetime, date as dt_date

from ui.theme import fit_window, fs, muted_fg
from ui.names import display_full

CONDITION_OPTIONS = ["New", "Excellent", "Good", "Fair", "Poor", "Needs Repair",
                     "Unrepairable", "Unknown"]
GENDER_OPTIONS = ["", "Unisex", "Male", "Female"]


# ───────────────────────────────────────────── reusable student autocomplete ──
class StudentPicker(ttk.Frame):
    """An entry + drop-down autocomplete over the current roster.  Read
    ``picker.student_id`` and ``picker.student_name`` after the user has chosen.
    ``on_pick`` (optional) is called with the selected student dict when a name
    is chosen from the list."""

    def __init__(self, parent, db, on_pick=None, width=42):
        super().__init__(parent)
        self.db = db
        self._on_pick = on_pick
        self.student_id = None

        self._selecting = False
        roster = db.get_current_roster()
        seen = {}
        for s in roster:
            d = dict(s)
            has_sid = bool((s["student_id"] or "").strip())
            fw = (s["first_name"] or "").split()[0].lower() if s["first_name"] else ""
            key = f"{fw}|{(s['last_name'] or '').lower()}"
            if key not in seen or (has_sid and not seen[key][1]):
                seen[key] = (d, has_sid)
        self._students = [(display_full(s), s) for s, _ in seen.values()]

        self._var = tk.StringVar()
        self._entry = ttk.Entry(self, textvariable=self._var, width=width)
        self._entry.pack(fill=X)

        self._ac = ttk.Frame(self, relief="solid", borderwidth=1)
        self._ac.pack(fill=X)
        self._ac.pack_propagate(False)
        self._ac.config(height=1)
        self._list = tk.Listbox(self._ac, font=("Segoe UI", fs(9)),
                                selectmode=SINGLE, activestyle="underline",
                                relief="flat", bd=0)
        self._list.pack(fill=BOTH, expand=True)

        self._var.trace_add("write", self._on_change)
        self._list.bind("<<ListboxSelect>>", self._on_select)
        self._list.bind("<Return>", self._on_select)
        self._list.bind("<Escape>", lambda e: (self._collapse(), self._entry.focus_set()))
        self._entry.bind("<Down>", self._focus_list)
        self._entry.bind("<Escape>", lambda e: self._collapse())

    @property
    def student_name(self):
        return self._var.get().strip()

    def focus_set(self):
        self._entry.focus_set()

    def _on_change(self, *args):
        if self._selecting:
            return
        self.student_id = None
        text = self._var.get().strip().lower()
        if not text:
            self._collapse()
            return
        matches = [n for n, _ in self._students if text in n.lower()]
        self._list.delete(0, END)
        if matches:
            for m in matches[:8]:
                self._list.insert(END, m)
            self._ac.config(height=min(len(matches), 8) * 18 + 4)
        else:
            self._collapse()

    def _collapse(self):
        self._list.delete(0, END)
        self._ac.config(height=1)

    def _focus_list(self, event=None):
        if self._list.size() > 0:
            self._list.focus_set()
            self._list.selection_set(0)

    def _on_select(self, event=None):
        sel = self._list.curselection()
        if not sel:
            return
        name = self._list.get(sel[0])
        picked = None
        for n, s in self._students:
            if n == name:
                self.student_id = s["id"]
                picked = s
                break
        self._selecting = True
        self._var.set(name)
        self._selecting = False
        self._collapse()
        self._entry.focus_set()
        if picked and self._on_pick:
            self._on_pick(picked)

    def resolve(self):
        """Return (student_id, student_name), looking the name up by text if the
        user typed rather than picked from the list."""
        name = self._var.get().strip()
        sid = self.student_id
        if sid is None and name:
            parts = name.split(None, 1)
            first = parts[0] if parts else name
            last = parts[1] if len(parts) > 1 else ""
            found = self.db.find_student_by_name(first, last)
            if found:
                sid = found["id"]
        return sid, name


# ─────────────────────────────────────────────────────── Add / Edit dialog ────
class UniformDialog(ttk.Toplevel):
    def __init__(self, parent, db, uniform_id=None, garment_types=None,
                 default_type=None, site_id=None):
        super().__init__(parent)
        self.db = db
        self.site_id = site_id   # the school whose closet this garment joins
        self.uniform_id = uniform_id
        self._result = None
        self._garment_types = garment_types or db.get_garment_types()
        self._default_type = default_type

        self.title("Edit Garment" if uniform_id else "Add Garment")
        self.resizable(True, True)
        self.grab_set()
        self.lift()

        self._vars = {}
        self._build()
        if uniform_id:
            self._load(uniform_id)
        elif default_type:
            self._vars["garment_type"].set(default_type)
        fit_window(self, 560, 560)

    def _build(self):
        hdr = ttk.Frame(self, bootstyle=PRIMARY)
        hdr.pack(fill=X)
        title = "Edit Garment" if self.uniform_id else "Add Garment"
        ttk.Label(hdr, text=f"👕  {title}", font=("Segoe UI", fs(13), "bold"),
                  bootstyle=(INVERSE, PRIMARY)).pack(pady=12, padx=16, anchor=W)

        body = ttk.Frame(self)
        body.pack(fill=BOTH, expand=True, padx=16, pady=8)

        self._section(body, "Garment")
        r0 = ttk.Frame(body); r0.pack(fill=X, pady=2)
        self._field(r0, "Garment Type *", "garment_type", widget="combobox",
                    options=self._garment_types, side=LEFT, width=24)
        self._field(r0, "Item Number *", "item_number", side=LEFT, width=14)

        r1 = ttk.Frame(body); r1.pack(fill=X, pady=2)
        self._field(r1, "Size", "size", side=LEFT, width=16)
        self._field(r1, "Style", "style", side=LEFT, width=16)
        self._field(r1, "Gender", "gender", widget="combobox",
                    options=GENDER_OPTIONS, side=LEFT, width=12)

        r2 = ttk.Frame(body); r2.pack(fill=X, pady=2)
        self._field(r2, "Color", "color", side=LEFT, width=18)
        self._field(r2, "Condition", "condition", widget="combobox",
                    options=CONDITION_OPTIONS, side=LEFT, width=16)

        self._section(body, "Identification & Storage")
        r3 = ttk.Frame(body); r3.pack(fill=X, pady=2)
        self._field(r3, "Barcode", "barcode", side=LEFT, width=20)
        self._field(r3, "Manufacturer", "manufacturer", side=LEFT, width=20)

        r4 = ttk.Frame(body); r4.pack(fill=X, pady=2)
        self._field(r4, "Location", "location", side=LEFT, width=20)

        self._section(body, "Financial & Care")
        r5 = ttk.Frame(body); r5.pack(fill=X, pady=2)
        self._field(r5, "Purchase Price ($)", "purchase_price", side=LEFT, width=14)
        self._field(r5, "Date Purchased", "date_purchased", side=LEFT, width=16,
                    placeholder="YYYY-MM-DD")
        self._field(r5, "Date Last Cleaned", "date_last_cleaned", side=LEFT, width=16,
                    placeholder="YYYY-MM-DD")

        ttk.Label(body, text="Comments / Notes:", font=("Segoe UI", fs(9))).pack(
            anchor=W, pady=(8, 0))
        self._comments = tk.Text(body, height=3, font=("Segoe UI", fs(9)),
                                 relief="solid", bd=1, wrap=WORD)
        self._comments.pack(fill=X, pady=2)

        btns = ttk.Frame(self)
        btns.pack(fill=X, padx=16, pady=10)
        if self.uniform_id:
            ttk.Button(btns, text="Duplicate as New", bootstyle=(SECONDARY, OUTLINE),
                       command=self._duplicate).pack(side=LEFT, padx=4)
            ttk.Button(btns, text="Mark Inactive", bootstyle=(DANGER, OUTLINE),
                       command=self._mark_inactive).pack(side=LEFT, padx=4)
        ttk.Button(btns, text="Cancel", bootstyle=(SECONDARY, OUTLINE),
                   command=self.destroy).pack(side=RIGHT, padx=4)
        ttk.Button(btns, text="Save", bootstyle=SUCCESS,
                   command=self._save).pack(side=RIGHT, padx=4)

    def _section(self, parent, title):
        f = ttk.Frame(parent)
        f.pack(fill=X, pady=(10, 2))
        ttk.Label(f, text=title, font=("Segoe UI", fs(10), "bold"),
                  bootstyle=PRIMARY).pack(side=LEFT)
        ttk.Separator(f).pack(side=LEFT, fill=X, expand=True, padx=8)

    def _field(self, parent, label, key, widget="entry", options=None,
               side=LEFT, width=20, placeholder=""):
        f = ttk.Frame(parent)
        f.pack(side=side, padx=6, pady=1)
        ttk.Label(f, text=label, font=("Segoe UI", fs(8))).pack(anchor=W)
        var = tk.StringVar()
        self._vars[key] = var
        if widget == "combobox":
            w = ttk.Combobox(f, textvariable=var, values=options or [], width=width)
        else:
            w = ttk.Entry(f, textvariable=var, width=width)
        w.pack(anchor=W)
        if placeholder:
            ttk.Label(f, text=placeholder, font=("Segoe UI", fs(7)),
                      foreground=muted_fg()).pack(anchor=W)
        return w

    def _load(self, uniform_id):
        row = self.db.get_uniform(uniform_id)
        if not row:
            return
        for key, var in self._vars.items():
            val = row[key] if key in row.keys() else None
            var.set("" if val is None else str(val))
        self._comments.delete("1.0", "end")
        self._comments.insert("1.0", row["comments"] or "")

    def _collect(self):
        data = {k: v.get().strip() for k, v in self._vars.items()}
        data["comments"] = self._comments.get("1.0", "end").strip()
        try:
            data["purchase_price"] = float(
                data["purchase_price"].replace("$", "").replace(",", "")) \
                if data["purchase_price"] else 0.0
        except ValueError:
            data["purchase_price"] = 0.0
        if self.uniform_id:
            data["is_active"] = 1
        return data

    def _validate(self, data):
        if not data.get("garment_type"):
            Messagebox.show_warning("Garment Type is required.", title="Validation",
                                    parent=self)
            return False
        if not data.get("item_number"):
            Messagebox.show_warning("Item Number is required.", title="Validation",
                                    parent=self)
            return False
        return True

    def _save(self):
        data = self._collect()
        if not self._validate(data):
            return
        # Register a brand-new garment type on the fly.
        if data["garment_type"] not in self._garment_types:
            self.db.add_garment_type(data["garment_type"])
        if self.uniform_id:
            self.db.update_uniform(self.uniform_id, data)
        else:
            data["site_id"] = getattr(self, "site_id", None)
            self.db.add_uniform(data)
        self._result = "saved"
        self.destroy()

    def _duplicate(self):
        data = self._collect()
        data.pop("is_active", None)
        data["barcode"] = ""
        data["site_id"] = getattr(self, "site_id", None)
        new_id = self.db.add_uniform(data)
        Messagebox.show_info(f"Garment duplicated (now editing the copy).",
                             title="Duplicated", parent=self)
        self.uniform_id = new_id
        self._load(new_id)

    def _mark_inactive(self):
        if Messagebox.yesno("Mark this garment inactive? It will be hidden from the "
                            "list but history is preserved.", title="Confirm",
                            parent=self) == "Yes":
            self.db.deactivate_uniform(self.uniform_id)
            self._result = "deactivated"
            self.destroy()


# ──────────────────────────────────────────────── Single check out / in ───────
class UniformCheckoutDialog(ttk.Toplevel):
    def __init__(self, parent, db, uniform_id, mode="checkout", checkout_data=None):
        super().__init__(parent)
        self.db = db
        self.uniform_id = uniform_id
        self.mode = mode
        self.checkout_data = checkout_data or {}
        self._result = None

        self.title("Check Out Garment" if mode == "checkout" else "Check In Garment")
        self.resizable(False, False)
        self.grab_set()
        self.lift()
        self._build()
        fit_window(self, 460, 480)

    def _build(self):
        u = self.db.get_uniform(self.uniform_id)
        if not u:
            self.destroy()
            return
        style = WARNING if self.mode == "checkout" else INFO
        hdr = ttk.Frame(self, bootstyle=style)
        hdr.pack(fill=X)
        icon = "📤" if self.mode == "checkout" else "📥"
        ttk.Label(hdr, text=f"{icon}  {'Check Out' if self.mode=='checkout' else 'Check In'} Garment",
                  font=("Segoe UI", fs(13), "bold"),
                  bootstyle=(INVERSE, style)).pack(pady=12, padx=16, anchor=W)

        btns = ttk.Frame(self)
        btns.pack(fill=X, padx=20, pady=12, side=BOTTOM)
        ttk.Button(btns, text="Cancel", bootstyle=(SECONDARY, OUTLINE),
                   command=self.destroy).pack(side=RIGHT, padx=4)
        ttk.Button(btns, text="Check Out" if self.mode == "checkout" else "Check In",
                   bootstyle=style, command=self._save).pack(side=RIGHT, padx=4)

        main = ttk.Frame(self)
        main.pack(fill=BOTH, expand=True, padx=20, pady=12)

        info = tk.LabelFrame(main, text=" Garment ", padx=8, pady=6,
                             font=("Segoe UI", fs(9), "bold"))
        info.pack(fill=X, pady=(0, 12))
        for label, value in [
            ("Type", u["garment_type"] or ""),
            ("Item #", u["item_number"] or ""),
            ("Size", u["size"] or ""),
            ("Color", u["color"] or ""),
            ("Condition", u["condition"] or ""),
        ]:
            r = ttk.Frame(info); r.pack(fill=X, pady=1)
            ttk.Label(r, text=f"{label}:", font=("Segoe UI", fs(8), "bold"),
                      width=12, anchor=W).pack(side=LEFT)
            ttk.Label(r, text=value, font=("Segoe UI", fs(8))).pack(side=LEFT)

        if self.mode == "checkout":
            self._build_checkout(main, u)
        else:
            self._build_checkin(main)

    def _build_checkout(self, parent, u):
        form = tk.LabelFrame(parent, text=" Check Out To ", padx=8, pady=6,
                             font=("Segoe UI", fs(9), "bold"))
        form.pack(fill=BOTH, expand=True, pady=(0, 8))

        ttk.Label(form, text="Student:", font=("Segoe UI", fs(9), "bold")).pack(anchor=W)
        self._picker = StudentPicker(form, self.db, on_pick=self._on_student_pick)
        self._picker.pack(fill=X, pady=(2, 0))
        self._picker.focus_set()

        # Last-year / size-up hint, filled once a student is chosen.
        self._hint = ttk.Label(form, text="", font=("Segoe UI", fs(8)),
                               foreground=muted_fg(), wraplength=340, justify=LEFT)
        self._hint.pack(anchor=W, pady=(6, 0))
        self._garment_type = u["garment_type"]

        ttk.Label(form, text="Return Date:", font=("Segoe UI", fs(9), "bold")).pack(
            anchor=W, pady=(12, 0))
        today = dt_date.today()
        end_year = today.year + 1 if today.month >= 8 else today.year
        self._due = ttk.DateEntry(form, dateformat="%Y-%m-%d",
                                  startdate=dt_date(end_year, 6, 20), bootstyle=WARNING)
        self._due.pack(anchor=W, pady=(2, 0))

    def _on_student_pick(self, student):
        """Show what this student had last year in this garment type, and, if
        that piece isn't the one being checked out, suggest available sizes up."""
        try:
            last = self.db.get_last_uniform_for_student(
                student["id"], display_full(student), self._garment_type)
        except Exception:
            last = None
        if not last:
            self._hint.config(text="")
            return
        msg = f"Last had {self._garment_type} #{last['item_number']}"
        if last["size"]:
            msg += f" (size {last['size']})"
        # size-up suggestion from currently available pieces
        try:
            from uniform_sizes import suggest_larger
            avail = [dict(r) for r in
                     self.db.get_available_uniforms_of_type(self._garment_type)]
            sugg = suggest_larger(avail, last["size"] or "", limit=2)
            if sugg:
                picks = ", ".join(f"#{s['item_number']} ({s['size']})" for s in sugg)
                msg += f".  Available sizes up: {picks}"
        except Exception:
            pass
        self._hint.config(text=msg)

    def _build_checkin(self, parent):
        form = tk.LabelFrame(parent, text=" Check In ", padx=8, pady=6,
                             font=("Segoe UI", fs(9), "bold"))
        form.pack(fill=BOTH, expand=True, pady=(0, 8))
        form.columnconfigure(1, weight=1)
        student = self.checkout_data.get("student_name", "")
        ttk.Label(form, text="Assigned To:", font=("Segoe UI", fs(9), "bold")).grid(
            row=0, column=0, sticky=W, pady=4)
        ttk.Label(form, text=student, font=("Segoe UI", fs(9))).grid(
            row=0, column=1, sticky=W, pady=4, padx=6)
        ttk.Label(form, text="Date Returned:", font=("Segoe UI", fs(9), "bold")).grid(
            row=1, column=0, sticky=W, pady=4)
        self._ret_var = tk.StringVar(value=datetime.today().strftime("%Y-%m-%d"))
        ttk.Entry(form, textvariable=self._ret_var, width=16).grid(
            row=1, column=1, sticky=W, pady=4, padx=6)
        ttk.Label(form, text="Condition:", font=("Segoe UI", fs(9), "bold")).grid(
            row=2, column=0, sticky=W, pady=4)
        self._cond_var = tk.StringVar()
        ttk.Combobox(form, textvariable=self._cond_var, values=CONDITION_OPTIONS,
                     width=16, state="readonly").grid(row=2, column=1, sticky=W, pady=4, padx=6)
        ttk.Label(form, text="Notes:", font=("Segoe UI", fs(9), "bold")).grid(
            row=3, column=0, sticky=NW, pady=4)
        self._notes = tk.Text(form, height=3, font=("Segoe UI", fs(9)),
                              relief="solid", bd=1, width=30)
        self._notes.grid(row=3, column=1, sticky=EW, pady=4, padx=6)

    def _save(self):
        if self.mode == "checkout":
            self._do_checkout()
        else:
            self._do_checkin()

    def _do_checkout(self):
        sid, name = self._picker.resolve()
        if not name:
            Messagebox.show_warning("Please enter or select a student.",
                                    title="Required", parent=self)
            return
        try:
            due = self._due.entry.get().strip()
        except Exception:
            due = ""
        try:
            self.db.checkout_uniform(self.uniform_id, sid, name,
                                     datetime.today().strftime("%Y-%m-%d"),
                                     due_date=due)
        except ValueError as e:
            Messagebox.show_warning(str(e), title="Already Checked Out", parent=self)
            return
        self._result = "saved"
        self.destroy()

    def _do_checkin(self):
        checkout_id = self.checkout_data.get("id")
        if not checkout_id:
            ac = self.db.get_active_uniform_checkout(self.uniform_id)
            checkout_id = ac["id"] if ac else None
        if not checkout_id:
            self.destroy()
            return
        notes = self._notes.get("1.0", "end").strip()
        cond = self._cond_var.get().strip()
        if cond:
            notes = (f"Returned {cond}. " + notes).strip()
            # keep the garment's condition current
            u = dict(self.db.get_uniform(self.uniform_id))
            u["condition"] = cond
            self.db.update_uniform(self.uniform_id, u)
        self.db.checkin_uniform(checkout_id, self._ret_var.get().strip(), notes)
        self._result = "saved"
        self.destroy()
