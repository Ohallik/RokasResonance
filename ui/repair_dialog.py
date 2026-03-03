"""
ui/repair_dialog.py - Add / Edit repair record dialog
"""

import tkinter as tk
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from ttkbootstrap.dialogs import Messagebox
from datetime import datetime


PRIORITY_OPTIONS = ["0 - Low", "1 - Normal", "2 - High", "3 - Urgent"]


class RepairDialog(ttk.Toplevel):
    def __init__(self, parent, db, instrument_id: int, repair_id=None,
                 prefill_data: dict = None, title_suffix: str = ""):
        super().__init__(parent)
        self.db = db
        self.instrument_id = instrument_id
        self.repair_id = repair_id
        self.saved = False

        if repair_id:
            title = "Edit Repair Record"
        elif prefill_data:
            title = "Review Repair Record"
        else:
            title = "Add Repair Record"
        if title_suffix:
            title += f"  —  {title_suffix}"
        self.title(title)
        self.geometry("500x640")
        self.resizable(False, True)
        self.grab_set()

        self.update_idletasks()
        x = (self.winfo_screenwidth() - 500) // 2
        y = (self.winfo_screenheight() - 640) // 2
        self.geometry(f"+{x}+{y}")

        self._vars = {}
        self._build()

        if repair_id:
            self._load_repair(repair_id)
        elif prefill_data:
            self._prefill(prefill_data)

    def _build(self):
        instrument = self.db.get_instrument(self.instrument_id)

        # Header
        hdr = ttk.Frame(self, bootstyle=WARNING)
        hdr.pack(fill=X)
        ttk.Label(hdr, text="🔧  Repair Record",
                  font=("Segoe UI", 13, "bold"),
                  bootstyle=(INVERSE, WARNING)).pack(pady=12, padx=16, anchor=W)

        # ── Buttons (packed before main so they always stay visible) ─────────
        btn_frame = ttk.Frame(self)
        btn_frame.pack(fill=X, padx=20, pady=10, side=BOTTOM)
        ttk.Button(btn_frame, text="Cancel", bootstyle=(SECONDARY, OUTLINE),
                   command=self.destroy).pack(side=RIGHT, padx=4)
        ttk.Button(btn_frame, text="Save", bootstyle=WARNING,
                   command=self._save).pack(side=RIGHT, padx=4)

        main = ttk.Frame(self)
        main.pack(fill=BOTH, expand=True, padx=20, pady=12)

        # ── Instrument Summary ────────────────────────────────────────────────
        if instrument:
            info = tk.LabelFrame(main, text=" Instrument ", padx=8, pady=6,
                                 font=("Segoe UI", 9, "bold"))
            info.pack(fill=X, pady=(0, 10))
            desc = instrument["description"] or ""
            brand_model = " ".join(filter(None, [instrument["brand"] or "", instrument["model"] or ""]))
            ttk.Label(info, text=f"{desc}  —  {brand_model}",
                      font=("Segoe UI", 9, "bold")).pack(anchor=W)
            ttk.Label(info, text=f"District #: {instrument['district_no'] or ''}   "
                                  f"Serial: {instrument['serial_no'] or ''}",
                      font=("Segoe UI", 8), foreground="#666").pack(anchor=W)

        # ── Form Fields ───────────────────────────────────────────────────────
        form = tk.LabelFrame(main, text=" Repair Details ", padx=8, pady=6,
                             font=("Segoe UI", 9, "bold"))
        form.pack(fill=BOTH, expand=True)
        form.columnconfigure(1, weight=1)

        row_num = 0

        def lbl(text, r):
            ttk.Label(form, text=text, font=("Segoe UI", 9, "bold")).grid(
                row=r, column=0, sticky=W, pady=4, padx=(0, 10))

        def entry(key, r, width=24, widget="entry", options=None):
            var = tk.StringVar()
            self._vars[key] = var
            if widget == "combobox":
                w = ttk.Combobox(form, textvariable=var, values=options or [],
                                  width=width, state="readonly")
            else:
                w = ttk.Entry(form, textvariable=var, width=width)
            w.grid(row=r, column=1, sticky=W, pady=4)
            return var

        lbl("Description:", row_num)
        entry("description", row_num, width=36)
        row_num += 1

        lbl("Priority:", row_num)
        entry("priority", row_num, widget="combobox",
              options=PRIORITY_OPTIONS, width=18)
        row_num += 1

        lbl("Date Added:", row_num)
        var = entry("date_added", row_num, width=16)
        var.set(datetime.today().strftime("%Y-%m-%d"))
        row_num += 1

        lbl("Sent To (shop):", row_num)
        entry("assigned_to", row_num, width=28)
        row_num += 1

        lbl("Date Repaired:", row_num)
        entry("date_repaired", row_num, width=16)
        row_num += 1

        lbl("Location:", row_num)
        entry("location", row_num, width=28)
        row_num += 1

        lbl("Est. Cost ($):", row_num)
        entry("est_cost", row_num, width=14)
        row_num += 1

        lbl("Actual Cost ($):", row_num)
        entry("act_cost", row_num, width=14)
        row_num += 1

        lbl("Invoice #:", row_num)
        entry("invoice_number", row_num, width=20)
        row_num += 1

        lbl("Notes:", row_num)
        self._notes_text = tk.Text(form, height=3, width=36, font=("Segoe UI", 9),
                                    relief="solid", bd=1, wrap=WORD)
        self._notes_text.grid(row=row_num, column=1, pady=4, sticky=W)


    def _prefill(self, data: dict):
        """Pre-populate form fields from a dict (e.g. parsed invoice data)."""
        for key, var in self._vars.items():
            val = data.get(key, "")
            if not val:
                continue
            if key == "priority":
                matching = [o for o in PRIORITY_OPTIONS if o.startswith(str(val))]
                var.set(matching[0] if matching else "1 - Normal")
            else:
                var.set(str(val))
        notes = data.get("notes", "")
        if notes:
            self._notes_text.delete("1.0", "end")
            self._notes_text.insert("1.0", notes)

    def _load_repair(self, repair_id: int):
        repairs = self.db.get_repairs(self.instrument_id)
        repair = next((r for r in repairs if r["id"] == repair_id), None)
        if not repair:
            return

        for key, var in self._vars.items():
            val = repair[key] if key in repair.keys() else None
            if key == "priority" and val is not None:
                # Match to option string
                matching = [o for o in PRIORITY_OPTIONS if o.startswith(str(val))]
                var.set(matching[0] if matching else str(val))
            else:
                var.set("" if val is None else str(val))

        notes = repair["notes"] or ""
        self._notes_text.delete("1.0", "end")
        self._notes_text.insert("1.0", notes)

    def _collect_data(self) -> dict:
        data = {k: v.get().strip() for k, v in self._vars.items()}
        data["notes"] = self._notes_text.get("1.0", "end").strip()
        data["instrument_id"] = self.instrument_id

        # Parse priority number from option string
        pri_raw = data.get("priority", "")
        try:
            data["priority"] = int(str(pri_raw).split("-")[0].strip())
        except (ValueError, IndexError):
            data["priority"] = 0

        for f in ("est_cost", "act_cost"):
            try:
                data[f] = float(str(data.get(f, "0")).replace("$", "").replace(",", "")) if data.get(f) else 0.0
            except ValueError:
                data[f] = 0.0

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
        if self.repair_id:
            self.db.update_repair(self.repair_id, data)
        else:
            self.db.add_repair(data)
        self.saved = True
        self.destroy()
