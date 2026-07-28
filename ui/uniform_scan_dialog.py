"""
ui/uniform_scan_dialog.py — Barcode-driven bulk check out / check in for
uniforms.  A handheld scanner emits the barcode text followed by Enter, so both
<Return> and <FocusOut> on the barcode fields trigger a lookup.

Fast garment-day workflow:
  Check Out tab → scan a garment barcode, scan/type the student, hit Check Out.
  Check In  tab → scan a garment barcode → it shows who has it → Check In.
"""

import tkinter as tk
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from ttkbootstrap.dialogs import Messagebox
from datetime import datetime

from ui.theme import fs, muted_fg, fit_window
from ui.uniform_dialog import StudentPicker


class UniformScanDialog(ttk.Toplevel):
    def __init__(self, parent, db, refresh_callback=None, initial_tab=None):
        super().__init__(parent)
        self.db = db
        self.refresh_callback = refresh_callback
        self._out_uniform = None
        self._in_uniform = None
        self._in_checkout = None

        self.title("Scan Uniforms")
        self.grab_set()
        self._build()
        if initial_tab == "checkin":
            self._nb.select(1)
        fit_window(self, 560, 560)

    def _build(self):
        hdr = ttk.Frame(self, bootstyle=WARNING)
        hdr.pack(fill=X)
        ttk.Label(hdr, text="🔦  Scan Uniforms", font=("Segoe UI", fs(13), "bold"),
                  bootstyle=(INVERSE, WARNING)).pack(pady=10, padx=16, anchor=W)

        self._nb = ttk.Notebook(self)
        self._nb.pack(fill=BOTH, expand=True, padx=10, pady=8)
        self._build_out_tab()
        self._build_in_tab()

        log_frame = ttk.Labelframe(self, text=" Recent ", padding=6)
        log_frame.pack(fill=X, padx=10, pady=(0, 8))
        self._log = tk.Listbox(log_frame, height=5, font=("Segoe UI", fs(8)))
        self._log.pack(fill=X)

        ttk.Button(self, text="Done", bootstyle=PRIMARY,
                   command=self._close).pack(pady=(0, 10))

    def _log_msg(self, msg):
        self._log.insert(0, f"{datetime.now().strftime('%H:%M')}  {msg}")

    # ── Check Out tab ──
    def _build_out_tab(self):
        tab = ttk.Frame(self._nb, padding=12)
        self._nb.add(tab, text="  📤  Check Out  ")

        ttk.Label(tab, text="Scan garment barcode:",
                  font=("Segoe UI", fs(9), "bold")).pack(anchor=W)
        self._out_bc = tk.StringVar()
        e = ttk.Entry(tab, textvariable=self._out_bc, width=30)
        e.pack(anchor=W, pady=(2, 0))
        e.bind("<Return>", lambda ev: self._lookup_out())
        e.bind("<FocusOut>", lambda ev: self._lookup_out())
        e.focus_set()

        self._out_info = ttk.Label(tab, text="No garment scanned yet.",
                                   font=("Segoe UI", fs(9)), foreground=muted_fg(),
                                   justify=LEFT)
        self._out_info.pack(anchor=W, pady=(8, 8))

        ttk.Label(tab, text="Student:", font=("Segoe UI", fs(9), "bold")).pack(anchor=W)
        self._out_picker = StudentPicker(tab, self.db)
        self._out_picker.pack(fill=X, pady=(2, 8))

        ttk.Button(tab, text="📤  Check Out", bootstyle=WARNING,
                   command=self._do_out).pack(anchor=W, pady=6)

    def _lookup_out(self):
        code = self._out_bc.get().strip()
        if not code:
            return
        u = self.db.get_uniform_by_barcode(code)
        if not u:
            self._out_uniform = None
            self._out_info.config(text=f"⚠ No garment found for barcode '{code}'.")
            return
        u = dict(u)
        self._out_uniform = u
        ac = self.db.get_active_uniform_checkout(u["id"])
        extra = f"\n⚠ Currently out to {ac['student_name']}" if ac else ""
        self._out_info.config(
            text=f"{u['garment_type']}  #{u['item_number']}  "
                 f"(size {u['size'] or '—'}){extra}")

    def _do_out(self):
        if not self._out_uniform:
            Messagebox.show_warning("Scan a garment first.", title="No Garment",
                                    parent=self)
            return
        sid, name = self._out_picker.resolve()
        if not name:
            Messagebox.show_warning("Enter or select a student.", title="No Student",
                                    parent=self)
            return
        try:
            self.db.checkout_uniform(self._out_uniform["id"], sid, name,
                                     datetime.today().strftime("%Y-%m-%d"))
        except ValueError as e:
            Messagebox.show_warning(str(e), title="Already Out", parent=self)
            return
        self._log_msg(f"OUT  {self._out_uniform['garment_type']} "
                      f"#{self._out_uniform['item_number']} → {name}")
        # reset for the next scan
        self._out_bc.set("")
        self._out_uniform = None
        self._out_info.config(text="No garment scanned yet.")
        self._out_picker._var.set("")
        self._out_picker.student_id = None
        if self.refresh_callback:
            self.refresh_callback()
        self.focus_out_barcode()

    def focus_out_barcode(self):
        try:
            self._nb.nametowidget(self._nb.select())
        except Exception:
            pass

    # ── Check In tab ──
    def _build_in_tab(self):
        tab = ttk.Frame(self._nb, padding=12)
        self._nb.add(tab, text="  📥  Check In  ")

        ttk.Label(tab, text="Scan garment barcode:",
                  font=("Segoe UI", fs(9), "bold")).pack(anchor=W)
        self._in_bc = tk.StringVar()
        e = ttk.Entry(tab, textvariable=self._in_bc, width=30)
        e.pack(anchor=W, pady=(2, 0))
        e.bind("<Return>", lambda ev: self._lookup_in())
        e.bind("<FocusOut>", lambda ev: self._lookup_in())

        self._in_info = ttk.Label(tab, text="No garment scanned yet.",
                                  font=("Segoe UI", fs(9)), foreground=muted_fg(),
                                  justify=LEFT)
        self._in_info.pack(anchor=W, pady=(8, 8))

        self._in_btn = ttk.Button(tab, text="📥  Check In", bootstyle=INFO,
                                  command=self._do_in, state="disabled")
        self._in_btn.pack(anchor=W, pady=6)

    def _lookup_in(self):
        code = self._in_bc.get().strip()
        if not code:
            return
        u = self.db.get_uniform_by_barcode(code)
        if not u:
            self._in_uniform = None
            self._in_checkout = None
            self._in_btn.config(state="disabled")
            self._in_info.config(text=f"⚠ No garment found for barcode '{code}'.")
            return
        u = dict(u)
        self._in_uniform = u
        ac = self.db.get_active_uniform_checkout(u["id"])
        if not ac:
            self._in_checkout = None
            self._in_btn.config(state="disabled")
            self._in_info.config(
                text=f"{u['garment_type']} #{u['item_number']} is not checked out.")
            return
        self._in_checkout = dict(ac)
        self._in_btn.config(state="normal")
        self._in_info.config(
            text=f"{u['garment_type']} #{u['item_number']} is out to "
                 f"{self._in_checkout['student_name']}.")

    def _do_in(self):
        if not self._in_checkout:
            return
        self.db.checkin_uniform(self._in_checkout["id"],
                                datetime.today().strftime("%Y-%m-%d"))
        self._log_msg(f"IN   {self._in_uniform['garment_type']} "
                      f"#{self._in_uniform['item_number']} ← "
                      f"{self._in_checkout['student_name']}")
        self._in_bc.set("")
        self._in_uniform = None
        self._in_checkout = None
        self._in_btn.config(state="disabled")
        self._in_info.config(text="No garment scanned yet.")
        if self.refresh_callback:
            self.refresh_callback()

    def _close(self):
        if self.refresh_callback:
            self.refresh_callback()
        self.destroy()
