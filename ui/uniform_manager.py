"""
ui/uniform_manager.py — Uniform / attire inventory + check-out manager.

The garment counterpart to ui/inventory_manager.py.  Supports a restricted
"Helper Mode": when helper_mode=True (a parent volunteer is logged in), the
inventory-editing, import, and garment-type tools are hidden and only checking
garments out/in and viewing the who-has-what chart are available — and no
student contact data is ever shown here.
"""

import os
import tkinter as tk
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from ttkbootstrap.dialogs import Messagebox
from datetime import datetime

from ui.theme import fs, muted_fg, fit_window
from ui.uniform_dialog import UniformDialog, UniformCheckoutDialog

COLS = ("item_number", "garment_type", "size", "color", "condition",
        "status", "checked_out_to", "barcode")
HEADERS = {
    "item_number": "Item #", "garment_type": "Garment", "size": "Size",
    "color": "Color", "condition": "Condition", "status": "Status",
    "checked_out_to": "Assigned To", "barcode": "Barcode",
}
WIDTHS = {
    "item_number": 70, "garment_type": 150, "size": 90, "color": 110,
    "condition": 90, "status": 100, "checked_out_to": 170, "barcode": 110,
}


class UniformManager(ttk.Frame):
    def __init__(self, parent, db, base_dir: str, on_checkouts=None,
                 helper_mode: bool = False):
        super().__init__(parent)
        self.db = db
        self.base_dir = base_dir
        self.on_checkouts = on_checkouts
        self.helper_mode = helper_mode

        self._search = tk.StringVar()
        self._status_filter = tk.StringVar(value="All")
        self._type_filter = tk.StringVar(value="All")
        self._rows = []

        self._build()
        self.refresh()

    # ─────────────────────────────────────────────────────────── build ────────
    def _build(self):
        hdr = ttk.Frame(self, bootstyle=PRIMARY)
        hdr.pack(fill=X)
        title = "👕  Uniforms & Attire"
        if self.helper_mode:
            title += "   —   Helper Mode"
        ttk.Label(hdr, text=title, font=("Segoe UI", fs(14), "bold"),
                  bootstyle=(INVERSE, PRIMARY)).pack(side=LEFT, pady=10, padx=16)
        if self.helper_mode:
            ttk.Label(hdr, text="Check-out only • student contact info hidden",
                      font=("Segoe UI", fs(8)),
                      bootstyle=(INVERSE, PRIMARY)).pack(side=LEFT, pady=10)

        # ── Toolbar ──
        bar = ttk.Frame(self)
        bar.pack(fill=X, padx=10, pady=(8, 4))

        def tb(text, style, cmd):
            return ttk.Button(bar, text=text, bootstyle=style, command=cmd)

        if not self.helper_mode:
            tb("➕ Add", PRIMARY, self._add).pack(side=LEFT, padx=2)
            tb("✏️ Edit", (SECONDARY, OUTLINE), self._edit).pack(side=LEFT, padx=2)
        tb("📤 Check Out", WARNING, self._checkout).pack(side=LEFT, padx=2)
        tb("📥 Check In", INFO, self._checkin).pack(side=LEFT, padx=2)
        tb("🔦 Scan", (WARNING, OUTLINE), self._bulk_scan).pack(side=LEFT, padx=2)
        tb("📊 Who Has What", SUCCESS, self._chart).pack(side=LEFT, padx=2)
        if not self.helper_mode:
            tb("🏷️ Garment Types", (SECONDARY, OUTLINE),
               self._manage_types).pack(side=LEFT, padx=2)
            tb("📥 Import", (INFO, OUTLINE), self._import).pack(side=LEFT, padx=2)

        # ── Filter row ──
        filt = ttk.Frame(self)
        filt.pack(fill=X, padx=10, pady=(0, 6))
        ttk.Label(filt, text="Search:", font=("Segoe UI", fs(9))).pack(side=LEFT)
        se = ttk.Entry(filt, textvariable=self._search, width=24)
        se.pack(side=LEFT, padx=(4, 12))
        self._search.trace_add("write", lambda *a: self._apply_filters())
        ttk.Label(filt, text="Status:", font=("Segoe UI", fs(9))).pack(side=LEFT)
        ttk.Combobox(filt, textvariable=self._status_filter, width=13, state="readonly",
                     values=["All", "Available", "Checked Out"]).pack(side=LEFT, padx=(4, 12))
        self._status_filter.trace_add("write", lambda *a: self._apply_filters())
        ttk.Label(filt, text="Garment:", font=("Segoe UI", fs(9))).pack(side=LEFT)
        self._type_combo = ttk.Combobox(filt, textvariable=self._type_filter,
                                        width=18, state="readonly")
        self._type_combo.pack(side=LEFT, padx=4)
        self._type_filter.trace_add("write", lambda *a: self._apply_filters())
        self._count_lbl = ttk.Label(filt, text="", font=("Segoe UI", fs(8)),
                                    foreground=muted_fg())
        self._count_lbl.pack(side=RIGHT)

        # ── Tree ──
        pane = ttk.Panedwindow(self, orient=HORIZONTAL)
        pane.pack(fill=BOTH, expand=True, padx=10, pady=(0, 8))

        left = ttk.Frame(pane)
        pane.add(left, weight=4)
        sb = ttk.Scrollbar(left, orient=VERTICAL)
        self.tree = ttk.Treeview(left, columns=COLS, show="headings",
                                 yscrollcommand=sb.set, bootstyle=PRIMARY,
                                 selectmode="browse")
        sb.config(command=self.tree.yview)
        for c in COLS:
            self.tree.heading(c, text=HEADERS[c],
                              command=lambda col=c: self._sort_by(col))
            self.tree.column(c, width=WIDTHS[c], anchor=W,
                             stretch=c in ("garment_type", "checked_out_to"))
        self.tree.tag_configure("available", foreground="#1a7f37")
        self.tree.tag_configure("checkedout", foreground="#8B4000")
        sb.pack(side=RIGHT, fill=Y)
        self.tree.pack(fill=BOTH, expand=True)
        self.tree.bind("<<TreeviewSelect>>", lambda e: self._load_detail())
        self.tree.bind("<Double-1>", lambda e: self._checkout()
                       if self.helper_mode else self._edit())

        # ── Detail pane ──
        right = ttk.Frame(pane)
        pane.add(right, weight=2)
        ttk.Label(right, text="Details", font=("Segoe UI", fs(10), "bold"),
                  bootstyle=PRIMARY).pack(anchor=W, padx=8, pady=(4, 2))
        self._detail = tk.Text(right, height=10, font=("Segoe UI", fs(9)),
                               relief="flat", wrap=WORD, state="disabled")
        self._detail.pack(fill=X, padx=8)
        ttk.Label(right, text="History", font=("Segoe UI", fs(10), "bold"),
                  bootstyle=PRIMARY).pack(anchor=W, padx=8, pady=(8, 2))
        self._history = tk.Text(right, font=("Segoe UI", fs(8)),
                                relief="flat", wrap=WORD, state="disabled")
        self._history.pack(fill=BOTH, expand=True, padx=8, pady=(0, 8))

        self._sort_col = None
        self._sort_rev = False

    # ─────────────────────────────────────────────────────────── data ─────────
    def refresh(self):
        self._rows = [dict(r) for r in self.db.get_uniforms_with_status()]
        types = ["All"] + self.db.get_garment_types()
        self._type_combo.config(values=types)
        if self._type_filter.get() not in types:
            self._type_filter.set("All")
        self._apply_filters()

    def _apply_filters(self):
        q = self._search.get().strip().lower()
        sf = self._status_filter.get()
        tf = self._type_filter.get()
        rows = []
        for r in self._rows:
            if sf != "All" and r.get("status") != sf:
                continue
            if tf != "All" and (r.get("garment_type") or "") != tf:
                continue
            if q:
                hay = " ".join(str(r.get(c) or "") for c in
                               ("item_number", "garment_type", "size", "color",
                                "barcode", "checked_out_to")).lower()
                if q not in hay:
                    continue
            rows.append(r)
        if self._sort_col:
            rows.sort(key=lambda r: self._sort_key(r, self._sort_col),
                      reverse=self._sort_rev)
        self._populate(rows)

    def _sort_key(self, r, col):
        v = r.get(col)
        if col == "item_number":
            try:
                return (0, int(str(v)))
            except (ValueError, TypeError):
                return (1, str(v or ""))
        return str(v or "").lower()

    def _sort_by(self, col):
        if self._sort_col == col:
            self._sort_rev = not self._sort_rev
        else:
            self._sort_col, self._sort_rev = col, False
        self._apply_filters()

    def _populate(self, rows):
        self.tree.delete(*self.tree.get_children())
        avail = 0
        for r in rows:
            tag = "checkedout" if r.get("status") == "Checked Out" else "available"
            if r.get("status") != "Checked Out":
                avail += 1
            self.tree.insert("", "end", iid=str(r["id"]),
                             values=tuple(r.get(c) or "" for c in COLS),
                             tags=(tag,))
        self._count_lbl.config(
            text=f"{len(rows)} shown • {avail} available • "
                 f"{len(rows) - avail} out")

    def _selected_id(self):
        sel = self.tree.selection()
        return int(sel[0]) if sel else None

    def _load_detail(self):
        uid = self._selected_id()
        self._detail.config(state="normal"); self._detail.delete("1.0", "end")
        self._history.config(state="normal"); self._history.delete("1.0", "end")
        if uid:
            u = dict(self.db.get_uniform(uid))
            lines = [
                f"{u['garment_type']}  #{u['item_number']}",
                f"Size: {u['size'] or '—'}    Color: {u['color'] or '—'}",
                f"Condition: {u['condition'] or '—'}",
                f"Barcode: {u['barcode'] or '—'}",
                f"Manufacturer: {u['manufacturer'] or '—'}",
                f"Location: {u['location'] or '—'}",
            ]
            if not self.helper_mode:
                price = u["purchase_price"]
                lines.append(f"Purchase Price: ${price:.2f}" if price else "Purchase Price: —")
                lines.append(f"Last Cleaned: {u['date_last_cleaned'] or '—'}")
                if u["comments"]:
                    lines.append(f"Notes: {u['comments']}")
            self._detail.insert("1.0", "\n".join(lines))
            for h in self.db.get_uniform_checkout_history(uid):
                h = dict(h)
                who = h["student_name"] or "?"
                out = h["date_assigned"] or "?"
                back = h["date_returned"] or "still out"
                self._history.insert("end", f"• {who}\n   {out} → {back}\n")
        self._detail.config(state="disabled")
        self._history.config(state="disabled")

    # ─────────────────────────────────────────────────────── actions ──────────
    def _add(self):
        dlg = UniformDialog(self.winfo_toplevel(), self.db,
                            garment_types=self.db.get_garment_types(),
                            default_type=None if self._type_filter.get() == "All"
                            else self._type_filter.get())
        self.wait_window(dlg)
        if getattr(dlg, "_result", None):
            self.refresh()

    def _edit(self):
        uid = self._selected_id()
        if not uid:
            Messagebox.show_info("Select a garment to edit.", title="No Selection",
                                 parent=self)
            return
        dlg = UniformDialog(self.winfo_toplevel(), self.db, uniform_id=uid,
                            garment_types=self.db.get_garment_types())
        self.wait_window(dlg)
        if getattr(dlg, "_result", None):
            self.refresh()

    def _checkout(self):
        uid = self._selected_id()
        if not uid:
            Messagebox.show_info("Select a garment to check out.",
                                 title="No Selection", parent=self)
            return
        row = next((r for r in self._rows if r["id"] == uid), None)
        if row and row.get("status") == "Checked Out":
            Messagebox.show_warning(
                f"That garment is already out to {row.get('checked_out_to') or 'someone'}. "
                f"Check it in first.", title="Already Out", parent=self)
            return
        dlg = UniformCheckoutDialog(self.winfo_toplevel(), self.db, uid, mode="checkout")
        self.wait_window(dlg)
        if getattr(dlg, "_result", None):
            self.refresh()

    def _checkin(self):
        uid = self._selected_id()
        if not uid:
            Messagebox.show_info("Select a garment to check in.",
                                 title="No Selection", parent=self)
            return
        ac = self.db.get_active_uniform_checkout(uid)
        if not ac:
            Messagebox.show_info("That garment isn't checked out.",
                                 title="Nothing to Check In", parent=self)
            return
        dlg = UniformCheckoutDialog(self.winfo_toplevel(), self.db, uid,
                                    mode="checkin", checkout_data=dict(ac))
        self.wait_window(dlg)
        if getattr(dlg, "_result", None):
            self.refresh()

    def _bulk_scan(self):
        from ui.uniform_scan_dialog import UniformScanDialog
        dlg = UniformScanDialog(self.winfo_toplevel(), self.db,
                                refresh_callback=self.refresh)
        self.wait_window(dlg)
        self.refresh()

    def _chart(self):
        from ui.uniform_chart_view import UniformChartView
        UniformChartView(self.winfo_toplevel(), self.db, self.base_dir)

    def _manage_types(self):
        _GarmentTypesDialog(self.winfo_toplevel(), self.db, on_change=self.refresh)

    def _import(self):
        from tkinter import filedialog
        path = filedialog.askopenfilename(
            title="Choose an attire export (.xlsx)",
            filetypes=[("Excel files", "*.xlsx"), ("All files", "*.*")])
        if not path:
            return
        try:
            from uniform_import import preview_attire_xlsx
            colmap, header, data = preview_attire_xlsx(path)
        except Exception as e:
            Messagebox.show_error(f"Could not read that file:\n{e}",
                                  title="Import Failed", parent=self)
            return
        found = sorted({str(r[colmap["garment_type"]]) for r in data
                        if "garment_type" in colmap and r[colmap["garment_type"]]})
        msg = (f"Found {len(data)} garment rows.\n"
               f"Garment types: {', '.join(found) or '—'}\n\n"
               f"Import them now?  (Rows already assigned to a student on the "
               f"sheet will be linked and marked checked out.)")
        if Messagebox.yesno(msg, title="Confirm Import", parent=self) != "Yes":
            return
        try:
            from uniform_import import import_attire_xlsx
            from lesson_plan_db import current_school_year
            try:
                yr = current_school_year()
            except Exception:
                yr = None
            summary = import_attire_xlsx(self.db, path, school_year=yr)
        except Exception as e:
            Messagebox.show_error(f"Import error:\n{e}", title="Import Failed",
                                  parent=self)
            return
        Messagebox.show_info(
            f"Imported {summary['items']} garments across "
            f"{summary['garment_types']} types.\n"
            f"Linked to students: {summary['assigned_linked']}\n"
            f"Assigned on sheet but no student match: {summary['assigned_unmatched']}",
            title="Import Complete", parent=self)
        self.refresh()


class _GarmentTypesDialog(ttk.Toplevel):
    """Add / rename / remove the user-definable garment types (so choir robes,
    orchestra dresses, etc. can be defined without code changes)."""

    def __init__(self, parent, db, on_change=None):
        super().__init__(parent)
        self.db = db
        self.on_change = on_change
        self.title("Garment Types")
        self.grab_set()
        self._build()
        fit_window(self, 380, 420)

    def _build(self):
        ttk.Label(self, text="Garment Types", font=("Segoe UI", fs(12), "bold"),
                  bootstyle=PRIMARY).pack(anchor=W, padx=14, pady=(12, 2))
        ttk.Label(self, text="These are the clothing items you can assign "
                  "(jackets, shakos, robes, dresses…).",
                  font=("Segoe UI", fs(8)), foreground=muted_fg(),
                  wraplength=340, justify=LEFT).pack(anchor=W, padx=14)

        self._list = tk.Listbox(self, font=("Segoe UI", fs(10)), height=10)
        self._list.pack(fill=BOTH, expand=True, padx=14, pady=8)
        self._reload()

        row = ttk.Frame(self)
        row.pack(fill=X, padx=14, pady=(0, 4))
        self._new = tk.StringVar()
        ttk.Entry(row, textvariable=self._new, width=22).pack(side=LEFT, fill=X, expand=True)
        ttk.Button(row, text="Add", bootstyle=SUCCESS, command=self._add).pack(side=LEFT, padx=4)

        btns = ttk.Frame(self)
        btns.pack(fill=X, padx=14, pady=(0, 12))
        ttk.Button(btns, text="Rename", bootstyle=(SECONDARY, OUTLINE),
                   command=self._rename).pack(side=LEFT, padx=2)
        ttk.Button(btns, text="Remove", bootstyle=(DANGER, OUTLINE),
                   command=self._remove).pack(side=LEFT, padx=2)
        ttk.Button(btns, text="Close", bootstyle=PRIMARY,
                   command=self._close).pack(side=RIGHT, padx=2)

    def _reload(self):
        self._list.delete(0, END)
        for t in self.db.get_garment_types():
            self._list.insert(END, t)

    def _sel(self):
        s = self._list.curselection()
        return self._list.get(s[0]) if s else None

    def _add(self):
        name = self._new.get().strip()
        if name:
            self.db.add_garment_type(name)
            self._new.set("")
            self._reload()

    def _rename(self):
        old = self._sel()
        if not old:
            return
        from ttkbootstrap.dialogs import Querybox
        new = Querybox.get_string(f"New name for '{old}':", title="Rename",
                                  parent=self)
        if new and new.strip():
            self.db.rename_garment_type(old, new.strip())
            self._reload()

    def _remove(self):
        name = self._sel()
        if not name:
            return
        if Messagebox.yesno(f"Remove '{name}' from the list? Existing garments keep "
                            f"their type; this only hides it from the picker.",
                            title="Remove Type", parent=self) == "Yes":
            self.db.delete_garment_type(name)
            self._reload()

    def _close(self):
        if self.on_change:
            self.on_change()
        self.destroy()
