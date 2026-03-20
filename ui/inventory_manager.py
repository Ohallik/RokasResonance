"""
ui/inventory_manager.py - Main inventory management screen
"""

import os
import json
import tkinter as tk
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from ttkbootstrap.dialogs import Messagebox
from ui.theme import muted_fg, fs, bind_copy_menu


TREEVIEW_COLS = (
    "status", "category", "description", "brand", "model",
    "barcode", "district_no", "serial_no", "condition",
    "checked_out_to", "est_value"
)
COL_HEADERS = {
    "status":        "●",
    "category":      "Category",
    "description":   "Instrument",
    "brand":         "Brand",
    "model":         "Model",
    "barcode":       "Barcode",
    "district_no":   "District #",
    "serial_no":     "Serial #",
    "condition":     "Condition",
    "checked_out_to": "Assigned To",
    "est_value":     "Est. Value",
}
COL_WIDTHS = {
    "status":        42,
    "category":      100,
    "description":   180,
    "brand":         90,
    "model":         90,
    "barcode":       80,
    "district_no":   80,
    "serial_no":     110,
    "condition":     70,
    "checked_out_to": 150,
    "est_value":     80,
}


class InventoryManager(ttk.Frame):
    def __init__(self, parent, db, base_dir: str):
        super().__init__(parent)
        self.db = db
        self.base_dir = base_dir
        self._all_rows = []
        self._selected_id = None
        self._sort_col = "category"
        self._sort_asc = True
        self._search_var = tk.StringVar()
        self._filter_status = tk.StringVar(value="All")
        self._filter_category = tk.StringVar(value="All")
        self._show_inactive = tk.BooleanVar(value=False)
        self._col_vars = {c: tk.BooleanVar(value=True)
                          for c in TREEVIEW_COLS if c != "status"}
        self._col_popup = None
        self._chat_window = None

        self._build()
        self._load_col_prefs()
        self._apply_col_visibility()
        self.refresh()

    # ─────────────────────────────────────────────────────────────── Build UI ──

    def _build(self):
        # ── Toolbar ───────────────────────────────────────────────────────────
        toolbar = ttk.Frame(self, bootstyle=LIGHT)
        toolbar.pack(fill=X, padx=0, pady=0)

        # ── Group 1: single-instrument actions ────────────────────────────
        ttk.Button(toolbar, text="➕ Add Instrument", bootstyle=SUCCESS,
                   command=self._add_instrument).pack(side=LEFT, padx=6, pady=6)
        ttk.Button(toolbar, text="✏️ Edit", bootstyle=PRIMARY,
                   command=self._edit_instrument).pack(side=LEFT, padx=2, pady=6)
        ttk.Button(toolbar, text="📤 Check Out", bootstyle=WARNING,
                   command=self._checkout).pack(side=LEFT, padx=2, pady=6)
        ttk.Button(toolbar, text="📥 Check In", bootstyle=INFO,
                   command=self._checkin).pack(side=LEFT, padx=2, pady=6)
        ttk.Button(toolbar, text="📄 Generate Form", bootstyle=PRIMARY,
                   command=self._generate_form).pack(side=LEFT, padx=2, pady=6)

        ttk.Separator(toolbar, orient=VERTICAL).pack(side=LEFT, fill=Y, padx=8, pady=4)

        # ── Group 2: bulk / special actions ───────────────────────────────
        ttk.Button(toolbar, text="📦 Bulk Check Out/In", bootstyle=(WARNING, OUTLINE),
                   command=self._bulk_checkout).pack(side=LEFT, padx=2, pady=6)
        ttk.Button(toolbar, text="🔧 Add Repair", bootstyle=SECONDARY,
                   command=self._add_repair).pack(side=LEFT, padx=2, pady=6)
        ttk.Button(toolbar, text="📋 Upload Invoice", bootstyle=SECONDARY,
                   command=self._upload_invoice).pack(side=LEFT, padx=2, pady=6)
        ttk.Button(toolbar, text="📊 Export Repairs", bootstyle=SECONDARY,
                   command=self._export_repairs).pack(side=LEFT, padx=2, pady=6)

        ttk.Separator(toolbar, orient=VERTICAL).pack(side=LEFT, fill=Y, padx=8, pady=4)

        ttk.Checkbutton(toolbar, text="Show Inactive",
                        variable=self._show_inactive,
                        command=self.refresh,
                        bootstyle=(SECONDARY, ROUND, TOGGLE)
                        ).pack(side=LEFT, padx=8, pady=6)

        # ── Search / Filter Bar ───────────────────────────────────────────────
        filter_bar = ttk.Frame(self)
        filter_bar.pack(fill=X, padx=8, pady=(4, 2))

        ttk.Label(filter_bar, text="Search:").pack(side=LEFT, padx=(0, 4))
        search_entry = ttk.Entry(filter_bar, textvariable=self._search_var, width=28)
        search_entry.pack(side=LEFT, padx=(0, 10))
        self._search_var.trace_add("write", lambda *_: self._apply_filters())

        ttk.Label(filter_bar, text="Status:").pack(side=LEFT, padx=(0, 4))
        ttk.Combobox(filter_bar, textvariable=self._filter_status,
                     values=["All", "Available", "Checked Out"],
                     state="readonly", width=14
                     ).pack(side=LEFT, padx=(0, 10))
        self._filter_status.trace_add("write", lambda *_: self._apply_filters())

        ttk.Label(filter_bar, text="Category:").pack(side=LEFT, padx=(0, 4))
        self._cat_combo = ttk.Combobox(filter_bar, textvariable=self._filter_category,
                                        state="readonly", width=18)
        self._cat_combo.pack(side=LEFT, padx=(0, 10))
        self._filter_category.trace_add("write", lambda *_: self._apply_filters())

        self._count_label = ttk.Label(filter_bar, text="", foreground=muted_fg())
        self._count_label.pack(side=RIGHT, padx=6)

        self._col_btn = ttk.Button(
            filter_bar, text="Columns ▼",
            bootstyle=(SECONDARY, OUTLINE), width=10,
            command=lambda: self._show_col_chooser(self._col_btn)
        )
        self._col_btn.pack(side=RIGHT, padx=(0, 4))

        # ── Main Content: Tree + Detail Panel ─────────────────────────────────
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
            selectmode="browse",
            bootstyle=PRIMARY,
        )
        scrollbar_y.config(command=self.tree.yview)
        scrollbar_x.config(command=self.tree.xview)

        scrollbar_y.pack(side=RIGHT, fill=Y)
        scrollbar_x.pack(side=BOTTOM, fill=X)
        self.tree.pack(fill=BOTH, expand=True)

        _STRETCH = {"description", "checked_out_to"}
        for col in TREEVIEW_COLS:
            self.tree.heading(
                col,
                text=COL_HEADERS[col],
                anchor=W,
                command=lambda c=col: self._sort_by(c)
            )
            self.tree.column(col, width=COL_WIDTHS[col], anchor=W,
                             minwidth=40, stretch=col in _STRETCH)

        self.tree.column("status", anchor=CENTER, stretch=False)
        self.tree.heading("status", anchor=CENTER)
        self.tree.column("est_value", anchor=E, stretch=False)
        self.tree.heading("est_value", anchor=E)

        self.tree.tag_configure("available", foreground="#1a7a1a")
        self.tree.tag_configure("checkedout", foreground="#8B4000")
        self.tree.tag_configure("inactive", foreground="#AAAAAA")

        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.bind("<Double-1>", lambda e: self._edit_instrument())

        # Right: Detail Panel
        detail_frame = ttk.Frame(paned, width=320)
        paned.add(detail_frame, weight=1)

        self._detail_nb = ttk.Notebook(detail_frame, bootstyle=PRIMARY)
        self._detail_nb.pack(fill=BOTH, expand=True)

        self._detail_tab = ttk.Frame(self._detail_nb)
        self._history_tab = ttk.Frame(self._detail_nb)
        self._repair_tab = ttk.Frame(self._detail_nb)

        self._detail_nb.add(self._detail_tab, text="Details")
        self._detail_nb.add(self._history_tab, text="Checkout History")
        self._detail_nb.add(self._repair_tab, text="Repairs")

        self._build_detail_tab()
        self._build_history_tab()
        self._build_repair_tab()

        # ── AI Chat Footer ─────────────────────────────────────────────────────
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
            ("Description", "description"),
            ("Category", "category"),
            ("Brand", "brand"),
            ("Model", "model"),
            ("Barcode", "barcode"),
            ("District #", "district_no"),
            ("Serial #", "serial_no"),
            ("Condition", "condition"),
            ("Status", "_status"),
            ("Assigned To", "checked_out_to"),
            ("Checkout Date", "checkout_date"),
            ("Est. Value", "est_value"),
            ("Amount Paid", "amount_paid"),
            ("Date Purchased", "date_purchased"),
            ("PO Number", "po_number"),
            ("Last Service", "last_service"),
            ("Case #", "case_no"),
            ("Locker", "locker"),
            ("Lock #", "lock_no"),
            ("Combo", "combo"),
            ("Accessories", "accessories"),
            ("Comments", "comments"),
        ]

        for label, key in fields:
            row = ttk.Frame(outer)
            row.pack(fill=X, pady=1)
            ttk.Label(row, text=f"{label}:", font=("Segoe UI", fs(8), "bold"),
                      width=14, anchor=W).pack(side=LEFT)
            val_lbl = ttk.Label(row, text="", font=("Segoe UI", fs(8)),
                                 anchor=W, wraplength=180, justify=LEFT)
            val_lbl.pack(side=LEFT, fill=X, expand=True)
            bind_copy_menu(val_lbl)
            self._detail_labels[key] = val_lbl

    def _build_history_tab(self):
        frame = ttk.Frame(self._history_tab)
        frame.pack(fill=BOTH, expand=True)

        cols = ("Student", "Date Out", "Date In")
        sb = ttk.Scrollbar(frame, orient=VERTICAL)
        self._history_tree = ttk.Treeview(frame, columns=cols, show="headings",
                                           yscrollcommand=sb.set, bootstyle=INFO,
                                           height=12)
        sb.config(command=self._history_tree.yview)
        sb.pack(side=RIGHT, fill=Y)
        self._history_tree.pack(fill=BOTH, expand=True)

        _stretch_h = {"Student"}
        for col in cols:
            self._history_tree.heading(col, text=col, anchor=W)
            self._history_tree.column(col, width=100, anchor=W,
                                      minwidth=40, stretch=col in _stretch_h)

    def _build_repair_tab(self):
        frame = ttk.Frame(self._repair_tab)
        frame.pack(fill=BOTH, expand=True)

        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill=X, padx=6, pady=4)
        ttk.Button(btn_frame, text="Add Repair", bootstyle=(SECONDARY, OUTLINE),
                   command=self._add_repair).pack(side=LEFT, padx=2)
        ttk.Button(btn_frame, text="Edit", bootstyle=(PRIMARY, OUTLINE),
                   command=self._edit_repair).pack(side=LEFT, padx=2)
        ttk.Button(btn_frame, text="Delete", bootstyle=(DANGER, OUTLINE),
                   command=self._delete_repair).pack(side=LEFT, padx=2)

        cols = ("Date", "Description", "Est $", "Act $", "Repaired")
        sb = ttk.Scrollbar(frame, orient=VERTICAL)
        self._repair_tree = ttk.Treeview(frame, columns=cols, show="headings",
                                          yscrollcommand=sb.set, bootstyle=WARNING,
                                          height=10, selectmode="extended")
        sb.config(command=self._repair_tree.yview)
        sb.pack(side=RIGHT, fill=Y)
        self._repair_tree.pack(fill=BOTH, expand=True)

        widths = [80, 160, 55, 55, 80]
        _stretch_r = {"Description"}
        for col, w in zip(cols, widths):
            self._repair_tree.heading(col, text=col, anchor=W)
            self._repair_tree.column(col, width=w, anchor=W,
                                     minwidth=40, stretch=col in _stretch_r)

        self._repair_total_var = tk.StringVar(value="")
        self._repair_costs = {}  # iid -> act_cost or est_cost
        self._repair_total_label = ttk.Label(
            frame, textvariable=self._repair_total_var,
            font=("Segoe UI", fs(9)), foreground=muted_fg(), anchor=E,
        )
        self._repair_total_label.pack(fill=X, padx=8, pady=(2, 4))
        self._repair_tree.bind("<<TreeviewSelect>>", self._on_repair_select)

    # ──────────────────────────────────────────────────── Column Visibility ────

    def _load_col_prefs(self):
        path = os.path.join(self.base_dir, "column_prefs.json")
        try:
            with open(path) as f:
                prefs = json.load(f)
            for col, var in self._col_vars.items():
                if col in prefs:
                    var.set(bool(prefs[col]))
        except (FileNotFoundError, json.JSONDecodeError):
            pass  # Use defaults (all visible)

    def _save_col_prefs(self):
        path = os.path.join(self.base_dir, "column_prefs.json")
        try:
            with open(path, "w") as f:
                json.dump({c: v.get() for c, v in self._col_vars.items()}, f, indent=2)
        except Exception:
            pass

    def _apply_col_visibility(self):
        visible = ["status"] + [
            c for c in TREEVIEW_COLS if c != "status" and self._col_vars[c].get()
        ]
        self.tree["displaycolumns"] = visible

    def _show_col_chooser(self, btn):
        # Toggle: close if already open
        if self._col_popup and self._col_popup.winfo_exists():
            self._col_popup.destroy()
            self._col_popup = None
            return

        popup = tk.Toplevel(self)
        popup.wm_overrideredirect(True)
        popup.wm_attributes("-topmost", True)
        self._col_popup = popup

        # Position below the button
        bx = btn.winfo_rootx()
        by = btn.winfo_rooty() + btn.winfo_height()
        popup.geometry(f"+{bx}+{by}")

        outer = ttk.Frame(popup, relief="solid", borderwidth=1)
        outer.pack(fill=BOTH, expand=True)

        ttk.Label(outer, text="Show Columns",
                  font=("Segoe UI", 9, "bold")).pack(anchor=W, padx=10, pady=(8, 2))
        ttk.Separator(outer, orient=HORIZONTAL).pack(fill=X, padx=6, pady=2)

        for col in TREEVIEW_COLS:
            if col == "status":
                continue
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

        # Close when clicking outside the popup
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

    # ─────────────────────────────────────────────────────────── Data Loading ──

    def refresh(self):
        """Reload all data from DB."""
        self._all_rows = list(self.db.get_instruments_with_status(
            include_inactive=self._show_inactive.get()
        ))
        self._update_category_filter()
        self._apply_filters()
        if self._selected_id:
            self._restore_selection()

    def _update_category_filter(self):
        cats = sorted(set(r["category"] or "Unknown" for r in self._all_rows))
        self._cat_combo["values"] = ["All"] + cats
        if self._filter_category.get() not in ["All"] + cats:
            self._filter_category.set("All")

    def _apply_filters(self):
        search = self._search_var.get().lower()
        status_filter = self._filter_status.get()
        cat_filter = self._filter_category.get()

        visible = []
        for row in self._all_rows:
            status = row["status"]
            cat = row["category"] or ""

            if status_filter != "All" and status != status_filter:
                continue
            if cat_filter != "All" and cat != cat_filter:
                continue
            if search:
                haystack = " ".join([
                    str(row["description"] or ""),
                    str(row["brand"] or ""),
                    str(row["model"] or ""),
                    str(row["barcode"] or ""),
                    str(row["district_no"] or ""),
                    str(row["serial_no"] or ""),
                    str(row["checked_out_to"] or ""),
                    str(row["category"] or ""),
                ]).lower()
                if search not in haystack:
                    continue
            visible.append(row)

        self._populate_tree(visible)
        n = len(visible)
        total = len(self._all_rows)
        self._count_label.config(text=f"{n} of {total} instruments")

    def _populate_tree(self, rows):
        # Sort
        reverse = not self._sort_asc
        try:
            rows = sorted(rows, key=lambda r: (r[self._sort_col] or "").lower(), reverse=reverse)
        except Exception:
            pass

        self.tree.delete(*self.tree.get_children())
        for row in rows:
            status = row["status"]
            is_active = row["is_active"] if "is_active" in row.keys() else 1
            tag = "available" if status == "Available" else "checkedout"
            if not is_active:
                tag = "inactive"

            est = row["est_value"]
            try:
                est_str = f"${float(est):,.2f}" if est else ""
            except (TypeError, ValueError):
                est_str = str(est or "")

            values = (
                "●" if status == "Available" else "◉",
                row["category"] or "",
                row["description"] or "",
                row["brand"] or "",
                row["model"] or "",
                row["barcode"] or "",
                row["district_no"] or "",
                row["serial_no"] or "",
                row["condition"] or "",
                row["checked_out_to"] or "",
                est_str,
            )
            iid = str(row["id"])
            self.tree.insert("", "end", iid=iid, values=values, tags=(tag,))

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

    # ─────────────────────────────────────────────────────── Detail Panel ──────

    def _on_select(self, event=None):
        sel = self.tree.selection()
        if not sel:
            return
        iid = sel[0]
        self._selected_id = int(iid)
        self._load_detail(self._selected_id)
        # Keep open chat window in sync with selected instrument
        if self._chat_window and self._chat_window.winfo_exists():
            instrument = self.db.get_instrument(self._selected_id)
            if instrument:
                self._chat_window.update_selected_instrument(dict(instrument))

    def _open_chat(self):
        from ui.chat_dialog import ChatDialog
        # Raise existing window if already open
        if self._chat_window and self._chat_window.winfo_exists():
            self._chat_window.lift()
            self._chat_window.focus_force()
            return
        instrument = None
        if self._selected_id:
            row = self.db.get_instrument(self._selected_id)
            if row:
                instrument = dict(row)
        self._chat_window = ChatDialog(
            self.winfo_toplevel(), self.db, self.base_dir, instrument
        )

    def _load_detail(self, instrument_id: int):
        instrument = self.db.get_instrument(instrument_id)
        if not instrument:
            return

        # Get current checkout
        active = self.db.get_active_checkout(instrument_id)
        status = "Checked Out" if active else "Available"
        checked_out_to = active["student_name"] if active else ""
        checkout_date = active["date_assigned"] if active else ""

        row = dict(instrument)
        row["_status"] = status
        row["checked_out_to"] = checked_out_to
        row["checkout_date"] = checkout_date

        for key, lbl in self._detail_labels.items():
            val = row.get(key, "")
            if val is None:
                val = ""
            # Format currency fields
            if key in ("est_value", "amount_paid") and val:
                try:
                    val = f"${float(val):,.2f}"
                except (ValueError, TypeError):
                    val = str(val)
            lbl.config(text=str(val))

        # Color status label
        status_lbl = self._detail_labels.get("_status")
        if status_lbl:
            status_lbl.config(
                foreground="#1a7a1a" if status == "Available" else "#8B4000",
                font=("Segoe UI", 8, "bold")
            )

        self._load_history(instrument_id)
        self._load_repairs(instrument_id)

    def _load_history(self, instrument_id: int):
        self._history_tree.delete(*self._history_tree.get_children())
        history = self.db.get_checkout_history(instrument_id)
        for h in history:
            self._history_tree.insert("", "end", values=(
                h["student_name"] or "",
                h["date_assigned"] or "",
                h["date_returned"] or "Active",
            ))

    def _load_repairs(self, instrument_id: int):
        self._repair_tree.delete(*self._repair_tree.get_children())
        self._repair_costs = {}
        repairs = self.db.get_repairs(instrument_id)
        for r in repairs:
            est = f"${r['est_cost']:,.2f}" if r["est_cost"] else ""
            act = f"${r['act_cost']:,.2f}" if r["act_cost"] else ""
            iid = self._repair_tree.insert("", "end", values=(
                r["date_added"] or "",
                r["description"] or "",
                est,
                act,
                r["date_repaired"] or "Pending",
            ))
            # Store repair id in item
            self._repair_tree.item(iid, tags=(str(r["id"]),))
            self._repair_costs[iid] = float(r["act_cost"] or r["est_cost"] or 0)
        total = sum(self._repair_costs.values())
        n = len(self._repair_costs)
        if n:
            self._repair_total_var.set(f"Total spent: ${total:,.2f}  ({n} repair{'s' if n != 1 else ''})")
        else:
            self._repair_total_var.set("")

    def _on_repair_select(self, _event=None):
        sel = self._repair_tree.selection()
        total = sum(self._repair_costs.values())
        if not sel:
            n = len(self._repair_costs)
            if n:
                self._repair_total_var.set(f"Total spent: ${total:,.2f}  ({n} repair{'s' if n != 1 else ''})")
            else:
                self._repair_total_var.set("")
            return
        sel_total = sum(self._repair_costs.get(iid, 0) for iid in sel)
        self._repair_total_var.set(
            f"Selected: ${sel_total:,.2f}  •  Total: ${total:,.2f}"
        )

    # ─────────────────────────────────────────────────────── Action Handlers ──

    def _get_selected_instrument(self):
        sel = self.tree.selection()
        if not sel:
            Messagebox.show_warning("Please select an instrument first.", title="No Selection",
                                    parent=self.winfo_toplevel())
            return None
        return int(sel[0])

    def _add_instrument(self):
        from ui.instrument_dialog import InstrumentDialog
        dlg = InstrumentDialog(self.winfo_toplevel(), self.db, instrument_id=None)
        self.wait_window(dlg)
        self.refresh()

    def _edit_instrument(self):
        iid = self._get_selected_instrument()
        if iid is None:
            return
        from ui.instrument_dialog import InstrumentDialog
        dlg = InstrumentDialog(self.winfo_toplevel(), self.db, instrument_id=iid)
        self.wait_window(dlg)
        self.refresh()
        self._load_detail(iid)

    def _checkout(self):
        iid = self._get_selected_instrument()
        if iid is None:
            return
        active = self.db.get_active_checkout(iid)
        if active:
            Messagebox.show_warning(
                f"This instrument is already checked out to {active['student_name']}.\n"
                "Check it in first before checking it out again.",
                title="Already Checked Out", parent=self.winfo_toplevel()
            )
            return
        from ui.checkout_dialog import CheckoutDialog
        dlg = CheckoutDialog(self.winfo_toplevel(), self.db, instrument_id=iid, mode="checkout")
        self.wait_window(dlg)
        self.refresh()
        self._load_detail(iid)

    def _checkin(self):
        iid = self._get_selected_instrument()
        if iid is None:
            return
        active = self.db.get_active_checkout(iid)
        if not active:
            Messagebox.show_warning(
                "This instrument is not currently checked out.",
                title="Not Checked Out", parent=self.winfo_toplevel()
            )
            return
        from ui.checkout_dialog import CheckoutDialog
        dlg = CheckoutDialog(self.winfo_toplevel(), self.db, instrument_id=iid,
                             mode="checkin", checkout_data=dict(active))
        self.wait_window(dlg)
        self.refresh()
        self._load_detail(iid)

    def _bulk_checkout(self):
        from ui.bulk_checkout_dialog import BulkCheckoutDialog
        dlg = BulkCheckoutDialog(self.winfo_toplevel(), self.db, self.base_dir,
                                 refresh_callback=self.refresh)
        self.wait_window(dlg)
        self.refresh()

    def _add_repair(self):
        iid = self._get_selected_instrument()
        if iid is None:
            return
        from ui.repair_dialog import RepairDialog
        dlg = RepairDialog(self.winfo_toplevel(), self.db, instrument_id=iid, repair_id=None)
        self.wait_window(dlg)
        if self._selected_id:
            self._load_repairs(self._selected_id)

    def _edit_repair(self):
        sel = self._repair_tree.selection()
        if not sel:
            return
        tags = self._repair_tree.item(sel[0], "tags")
        if not tags:
            return
        repair_id = int(tags[0])
        iid = self._get_selected_instrument()
        from ui.repair_dialog import RepairDialog
        dlg = RepairDialog(self.winfo_toplevel(), self.db, instrument_id=iid, repair_id=repair_id)
        self.wait_window(dlg)
        if self._selected_id:
            self._load_repairs(self._selected_id)

    def _delete_repair(self):
        sel = self._repair_tree.selection()
        if not sel:
            return
        tags = self._repair_tree.item(sel[0], "tags")
        if not tags:
            return
        repair_id = int(tags[0])
        if Messagebox.yesno("Delete this repair record?", title="Confirm Delete",
                            parent=self.winfo_toplevel()) == "Yes":
            self.db.delete_repair(repair_id)
            if self._selected_id:
                self._load_repairs(self._selected_id)

    def _generate_form(self):
        iid = self._get_selected_instrument()
        if iid is None:
            return
        active = self.db.get_active_checkout(iid)
        if not active:
            Messagebox.show_warning(
                "This instrument must be checked out to generate a loan form.",
                title="Not Checked Out", parent=self.winfo_toplevel()
            )
            return
        try:
            from pdf_generator import generate_form_for_checkout
            path = generate_form_for_checkout(self.db, active["id"], self.base_dir)
            self.db.mark_form_generated(active["id"])
            Messagebox.show_info(
                f"Loan form generated!\n\n{path}\n\nOpening now...",
                title="Form Generated", parent=self.winfo_toplevel()
            )
            os.startfile(path)
        except Exception as e:
            Messagebox.show_error(f"Failed to generate form:\n{e}", title="Error",
                                  parent=self.winfo_toplevel())

    def _upload_invoice(self):
        from tkinter import filedialog
        try:
            from invoice_parser import parse_invoices
        except ImportError as e:
            Messagebox.show_error(str(e), title="Missing Dependency",
                                  parent=self.winfo_toplevel())
            return

        paths = filedialog.askopenfilenames(
            title="Select Invoice PDF(s)",
            parent=self.winfo_toplevel(),
            filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")],
        )
        if not paths:
            return

        instruments = [dict(r) for r in self.db.get_all_instruments(include_inactive=False)]

        try:
            results = parse_invoices(list(paths), instruments)
        except ImportError as e:
            Messagebox.show_error(str(e), title="Missing Dependency",
                                  parent=self.winfo_toplevel())
            return
        except Exception as e:
            Messagebox.show_error(f"Error parsing invoice(s):\n{e}", title="Parse Error",
                                  parent=self.winfo_toplevel())
            return

        errors  = [r for r in results if "error" in r]
        matches = [r for r in results if "error" not in r]

        if not matches:
            msg = "No instrument matches found in the selected invoice(s)."
            if errors:
                msg += "\n\nErrors:\n" + "\n".join(e["error"] for e in errors)
            Messagebox.show_info(msg, title="No Matches Found",
                                 parent=self.winfo_toplevel())
            return

        # Confirm before opening dialogs
        error_note = f"\n\n({len(errors)} file(s) could not be parsed)" if errors else ""
        answer = Messagebox.yesno(
            f"Found {len(matches)} repair record(s) across "
            f"{len(set(m['source_file'] for m in matches))} invoice file(s).{error_note}\n\n"
            "Review each repair record now?",
            title="Invoice Parsed", parent=self.winfo_toplevel()
        )
        if answer != "Yes":
            return

        saved_count = 0
        from ui.repair_dialog import RepairDialog
        for i, match in enumerate(matches, 1):
            suffix = f"{i} of {len(matches)}  —  {match['instrument_label']}"
            dlg = RepairDialog(
                self.winfo_toplevel(), self.db,
                instrument_id=match["instrument_id"],
                repair_id=None,
                prefill_data=match["prefill"],
                title_suffix=suffix,
            )
            self.wait_window(dlg)
            if dlg.saved:
                saved_count += 1

        self.refresh()
        if self._selected_id:
            self._load_repairs(self._selected_id)

        Messagebox.show_info(
            f"Saved {saved_count} of {len(matches)} repair record(s).",
            title="Invoice Review Complete", parent=self.winfo_toplevel()
        )

    def _export_repairs(self):
        # ── Scope selection dialog ─────────────────────────────────────────
        selected_ids = {int(iid) for iid in self.tree.selection()}
        n_sel = len(selected_ids)

        dlg = ttk.Toplevel(self.winfo_toplevel())
        dlg.title("Export Repairs")
        dlg.resizable(False, False)
        dlg.grab_set()

        ttk.Label(dlg, text="Export repair records for:",
                  font=("Segoe UI", fs(10), "bold")).pack(anchor=W, padx=20, pady=(18, 8))

        scope_var = tk.StringVar(value="all" if n_sel == 0 else "selected")

        sel_text = (f"Selected instruments only  ({n_sel} selected)"
                    if n_sel else "Selected instruments only  (none selected)")
        ttk.Radiobutton(dlg, text=sel_text, variable=scope_var,
                        value="selected",
                        state="normal" if n_sel else "disabled").pack(anchor=W, padx=32, pady=2)
        ttk.Radiobutton(dlg, text="All instruments", variable=scope_var,
                        value="all").pack(anchor=W, padx=32, pady=2)

        result = {"ok": False}

        def _ok():
            result["ok"] = True
            dlg.destroy()

        btn_row = ttk.Frame(dlg)
        btn_row.pack(pady=(14, 18))
        ttk.Button(btn_row, text="Export", bootstyle=PRIMARY,
                   command=_ok).pack(side=LEFT, padx=6)
        ttk.Button(btn_row, text="Cancel", bootstyle=SECONDARY,
                   command=dlg.destroy).pack(side=LEFT, padx=6)

        from ui.theme import fit_window
        fit_window(dlg, 340, 185)
        dlg.wait_window()
        if not result["ok"]:
            return

        # ── Gather instrument + repair data ───────────────────────────────
        all_instruments = [dict(r) for r in self.db.get_all_instruments(include_inactive=True)]
        if scope_var.get() == "selected" and selected_ids:
            all_instruments = [i for i in all_instruments if i["id"] in selected_ids]

        data = []
        for inst in all_instruments:
            repairs = [dict(r) for r in self.db.get_repairs(inst["id"])]
            if repairs:
                data.append((inst, repairs))

        if not data:
            Messagebox.show_info("No repair records found for the selected instruments.",
                                 title="Nothing to Export", parent=self.winfo_toplevel())
            return

        # ── Build Excel workbook ───────────────────────────────────────────
        try:
            import openpyxl
            from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
            from openpyxl.utils import get_column_letter
        except ImportError:
            Messagebox.show_error("openpyxl is required. Run: pip install openpyxl",
                                  title="Missing Dependency", parent=self.winfo_toplevel())
            return

        wb = openpyxl.Workbook()

        def _fill(hex_color):
            return PatternFill("solid", fgColor=hex_color)

        def _border():
            s = Side(style="thin", color="CCCCCC")
            return Border(left=s, right=s, top=s, bottom=s)

        hdr_font   = Font(bold=True, color="FFFFFF", size=10)
        hdr_fill   = _fill("2E5E8E")   # dark blue
        inst_font  = Font(bold=True, size=9)
        inst_fill  = _fill("D9E1F2")   # light blue
        total_font = Font(bold=True, size=9)
        total_fill = _fill("E2EFDA")   # light green
        alt_fill   = _fill("F5F5F5")   # light gray
        money_fmt  = '"$"#,##0.00'

        def _row(ws, r, values, font=None, fill=None, fmts=None):
            for c, val in enumerate(values, 1):
                cell = ws.cell(row=r, column=c, value=val)
                cell.border = _border()
                cell.alignment = Alignment(vertical="center")
                if font:  cell.font = font
                if fill:  cell.fill = fill
                if fmts and fmts.get(c):
                    cell.number_format = fmts[c]

        # ── Sheet 1: Summary ──────────────────────────────────────────────
        ws1 = wb.active
        ws1.title = "Summary"
        ws1.freeze_panes = "A2"

        s1_hdrs = ["Category", "Instrument", "Brand", "Model",
                   "Barcode", "District #", "Serial #", "Condition",
                   "# Repairs", "Total Spent", "Last Repaired"]
        _row(ws1, 1, s1_hdrs, font=hdr_font, fill=hdr_fill)
        ws1.row_dimensions[1].height = 18

        summary = []
        for inst, repairs in data:
            total = sum(float(r.get("act_cost") or r.get("est_cost") or 0) for r in repairs)
            last  = max((r.get("date_repaired") or r.get("date_added") or "") for r in repairs)
            summary.append((inst, repairs, total, last))
        summary.sort(key=lambda x: -x[2])

        grand_total = 0.0
        for ri, (inst, repairs, total, last) in enumerate(summary, 2):
            grand_total += total
            fill = alt_fill if ri % 2 == 0 else None
            _row(ws1, ri, [
                inst.get("category") or "",
                inst.get("description") or "",
                inst.get("brand") or "",
                inst.get("model") or "",
                inst.get("barcode") or "",
                inst.get("district_no") or "",
                inst.get("serial_no") or "",
                inst.get("condition") or "",
                len(repairs),
                total,
                last or "",
            ], fill=fill, fmts={10: money_fmt})

        gt_row = len(summary) + 2
        _row(ws1, gt_row,
             ["", "", "", "", "", "", "", "GRAND TOTAL", "", grand_total, ""],
             font=total_font, fill=total_fill, fmts={10: money_fmt})

        for col, w in zip(range(1, 12), [14, 26, 16, 16, 10, 10, 14, 12, 9, 13, 13]):
            ws1.column_dimensions[get_column_letter(col)].width = w

        # ── Sheet 2: Repair Details ───────────────────────────────────────
        ws2 = wb.create_sheet("Repair Details")
        ws2.freeze_panes = "A2"

        s2_hdrs = ["Category", "Instrument", "Brand", "Barcode",
                   "Date Added", "Description", "Shop / Location",
                   "Est. Cost", "Actual Cost", "Date Repaired", "Status"]
        _row(ws2, 1, s2_hdrs, font=hdr_font, fill=hdr_fill)
        ws2.row_dimensions[1].height = 18

        dr = 2
        for inst, repairs, total, _ in summary:
            # Instrument header spanning all columns
            label = "  ".join(filter(None, [
                inst.get("category") or "",
                inst.get("description") or "",
                inst.get("brand") or "",
                f"Barcode: {inst.get('barcode')}" if inst.get("barcode") else "",
                f"District #: {inst.get('district_no')}" if inst.get("district_no") else "",
            ]))
            _row(ws2, dr, [label] + [""] * (len(s2_hdrs) - 1),
                 font=inst_font, fill=inst_fill)
            ws2.merge_cells(start_row=dr, start_column=1,
                            end_row=dr, end_column=len(s2_hdrs))
            dr += 1

            for ridx, r in enumerate(
                sorted(repairs, key=lambda x: x.get("date_added") or "")
            ):
                fill = alt_fill if ridx % 2 == 1 else None
                status = "Completed" if r.get("date_repaired") else "Pending"
                _row(ws2, dr, [
                    inst.get("category") or "",
                    inst.get("description") or "",
                    inst.get("brand") or "",
                    inst.get("barcode") or "",
                    r.get("date_added") or "",
                    r.get("description") or "",
                    r.get("assigned_to") or r.get("location") or "",
                    float(r.get("est_cost") or 0),
                    float(r.get("act_cost") or 0),
                    r.get("date_repaired") or "",
                    status,
                ], fill=fill, fmts={8: money_fmt, 9: money_fmt})
                dr += 1

            # Subtotal row
            _row(ws2, dr,
                 ["", "", "", "", "", "", "Subtotal", "", total, "", ""],
                 font=total_font, fill=total_fill, fmts={8: money_fmt, 9: money_fmt})
            dr += 2  # blank row between instruments

        for col, w in zip(range(1, 12), [12, 22, 14, 10, 12, 34, 22, 10, 12, 14, 10]):
            ws2.column_dimensions[get_column_letter(col)].width = w

        # ── Save ──────────────────────────────────────────────────────────
        from tkinter import filedialog
        import datetime
        path = filedialog.asksaveasfilename(
            title="Save Repair Export",
            parent=self.winfo_toplevel(),
            defaultextension=".xlsx",
            initialfile=f"Repairs_{datetime.date.today().isoformat()}.xlsx",
            filetypes=[("Excel files", "*.xlsx"), ("All files", "*.*")],
        )
        if not path:
            return

        try:
            wb.save(path)
        except Exception as e:
            Messagebox.show_error(f"Could not save file:\n{e}", title="Save Error",
                                  parent=self.winfo_toplevel())
            return

        answer = Messagebox.yesno(
            "Repair data exported successfully.\n\nOpen the file now?",
            title="Export Complete", parent=self.winfo_toplevel()
        )
        if answer == "Yes":
            import subprocess
            subprocess.Popen(["start", "", path], shell=True)
