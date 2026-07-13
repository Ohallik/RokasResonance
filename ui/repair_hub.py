"""
ui/repair_hub.py - Consolidated repair center.

One window for everything repair-related: upload an invoice, mark an instrument
as needing repair, see what needs repair / what is out at the shop, review full
repair history, and analyse which instruments have cost the most (for
replacement decisions you can forward to district staff / PTSA).
"""

import tkinter as tk
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from ttkbootstrap.dialogs import Messagebox
from datetime import datetime


PRIORITY_LABELS = {3: "Urgent", 2: "High", 1: "Normal", 0: "Low"}

VIEWS = [
    ("needs", "Needs Repair"),
    ("out",   "Out for Repair"),
    ("history", "Repair History"),
    ("cost",  "Cost Analysis"),
]

# Column layouts per view kind
_REPAIR_COLS = ("priority", "instrument", "brand", "barcode",
                "needed", "reported", "shop", "status")
_REPAIR_HDRS = {
    "priority": "Priority", "instrument": "Instrument", "brand": "Brand",
    "barcode": "Barcode", "needed": "Repair Needed",
    "reported": "Reported", "shop": "Shop / Location", "status": "Status",
}
_REPAIR_WIDTHS = {
    "priority": 70, "instrument": 190, "brand": 90, "barcode": 90,
    "needed": 260, "reported": 90, "shop": 150, "status": 100,
}

_COST_COLS = ("rank", "instrument", "brand", "barcode", "count",
              "total", "value", "age", "last")
_COST_HDRS = {
    "rank": "#", "instrument": "Instrument", "brand": "Brand", "barcode": "Barcode",
    "count": "# Repairs", "total": "Total Repair $", "value": "Est. Value",
    "age": "Age", "last": "Last Repaired",
}
_COST_WIDTHS = {
    "rank": 40, "instrument": 190, "brand": 100, "barcode": 90, "count": 80,
    "total": 110, "value": 90, "age": 50, "last": 100,
}


class RepairHub(ttk.Toplevel):
    def __init__(self, parent, inventory_manager):
        super().__init__(parent)
        self.inv = inventory_manager
        self.db = inventory_manager.db
        self._view = tk.StringVar(value="needs")
        self._sort_state = {}

        self.title("Repair Center — Roka's Resonance")
        self.resizable(True, True)
        self.grab_set()
        self.lift()

        self._build()
        self._reload()

        from ui.theme import fit_window
        fit_window(self, 1040, 620)

    # ─────────────────────────────────────────────────────────── Build UI ──────

    def _build(self):
        hdr = ttk.Frame(self, bootstyle=SECONDARY)
        hdr.pack(fill=X)
        ttk.Label(hdr, text="🔧  Repair Center", font=("Segoe UI", 13, "bold"),
                  bootstyle=(INVERSE, SECONDARY)).pack(pady=10, padx=16, anchor=W)

        # ── View selector ─────────────────────────────────────────────────
        views = ttk.Frame(self)
        views.pack(fill=X, padx=12, pady=(10, 4))
        ttk.Label(views, text="View:", font=("Segoe UI", 9, "bold")).pack(side=LEFT, padx=(0, 8))
        for value, label in VIEWS:
            ttk.Radiobutton(views, text=label, value=value, variable=self._view,
                            bootstyle=(SECONDARY, OUTLINE, TOOLBUTTON),
                            command=self._reload, width=15).pack(side=LEFT, padx=2)
        self._summary_lbl = ttk.Label(views, text="", foreground="#666")
        self._summary_lbl.pack(side=RIGHT, padx=8)

        # ── Action buttons ────────────────────────────────────────────────
        bar = ttk.Frame(self)
        bar.pack(fill=X, padx=12, pady=(2, 6))
        ttk.Button(bar, text="📋 Upload Invoice", bootstyle=(SECONDARY, OUTLINE),
                   command=self._upload_invoice).pack(side=LEFT, padx=2)
        ttk.Button(bar, text="➕ Add Repair", bootstyle=(SECONDARY, OUTLINE),
                   command=self._add_repair_scan).pack(side=LEFT, padx=2)
        self._out_btn = ttk.Button(bar, text="🚚 Mark Out for Repair", bootstyle=(WARNING, OUTLINE),
                                   command=self._mark_out_for_repair)
        self._out_btn.pack(side=LEFT, padx=2)
        self._edit_btn = ttk.Button(bar, text="✏️ Edit", bootstyle=(PRIMARY, OUTLINE),
                                    command=self._edit_selected)
        self._edit_btn.pack(side=LEFT, padx=2)
        self._done_btn = ttk.Button(bar, text="✅ Mark Repaired", bootstyle=(SUCCESS, OUTLINE),
                                    command=self._mark_repaired)
        self._done_btn.pack(side=LEFT, padx=2)
        ttk.Button(bar, text="📊 Export This View", bootstyle=(INFO, OUTLINE),
                   command=self._export_view).pack(side=LEFT, padx=2)
        ttk.Button(bar, text="Close", bootstyle=(SECONDARY, OUTLINE),
                   command=self.destroy).pack(side=RIGHT, padx=2)

        # ── Tree ──────────────────────────────────────────────────────────
        tree_frame = ttk.Frame(self)
        tree_frame.pack(fill=BOTH, expand=True, padx=12, pady=(0, 12))
        sb = ttk.Scrollbar(tree_frame, orient=VERTICAL)
        self.tree = ttk.Treeview(tree_frame, show="headings",
                                 yscrollcommand=sb.set, selectmode="browse",
                                 bootstyle=PRIMARY)
        sb.config(command=self.tree.yview)
        sb.pack(side=RIGHT, fill=Y)
        self.tree.pack(fill=BOTH, expand=True)
        self.tree.bind("<Double-1>", lambda e: self._edit_selected())

    def _configure_columns(self, cost: bool):
        cols = _COST_COLS if cost else _REPAIR_COLS
        hdrs = _COST_HDRS if cost else _REPAIR_HDRS
        widths = _COST_WIDTHS if cost else _REPAIR_WIDTHS
        self.tree.config(columns=cols)
        stretch = {"instrument", "needed"}
        for c in cols:
            self.tree.heading(c, text=hdrs[c], anchor=W,
                              command=lambda col=c: self._sort_by(col))
            anchor = E if c in ("est", "total", "value", "count") else W
            self.tree.column(c, width=widths[c], anchor=anchor,
                             minwidth=40, stretch=c in stretch)

    # Ranks for the text-labelled priority column so sorting is meaningful
    # (Urgent > High > Normal > Low) rather than alphabetical.
    _PRIORITY_RANK = {"Urgent": 3, "High": 2, "Normal": 1, "Low": 0, "": -1}

    def _sort_by(self, col):
        """Sort the visible rows by a clicked column header; click again to
        reverse.  Numbers/money sort numerically, priority by severity."""
        reverse = self._sort_state.get(col, False)

        def key(iid):
            raw = (self.tree.set(iid, col) or "").strip()
            if col == "priority":
                return (0, self._PRIORITY_RANK.get(raw, -1))
            cleaned = raw.lstrip("(").rstrip(")").replace("$", "").replace(",", "")
            try:
                return (0, float(cleaned))
            except ValueError:
                return (1, raw.lower())

        items = sorted(self.tree.get_children(""), key=key, reverse=reverse)
        for idx, iid in enumerate(items):
            self.tree.move(iid, "", idx)
        self._sort_state = {col: not reverse}   # reset others; toggle this one

    # ─────────────────────────────────────────────────────────── Data ──────────

    def _reload(self):
        view = self._view.get()
        cost = view == "cost"
        self._configure_columns(cost)
        self.tree.delete(*self.tree.get_children())

        is_repair_view = view in ("needs", "out")
        self._edit_btn.config(state=NORMAL if view in ("needs", "out", "history") else DISABLED)
        self._done_btn.config(state=NORMAL if is_repair_view else DISABLED)
        self._out_btn.config(state=NORMAL if view == "needs" else DISABLED)

        if cost:
            self._load_cost()
        elif view == "history":
            self._load_history(self.db.get_all_repairs())
        elif view == "out":
            rows = [r for r in self.db.get_instruments_needing_repair()
                    if (r["shop"] or "").strip()]
            self._load_needs(rows)
        else:  # needs — instruments with an open repair OR flagged on the
               # instrument itself (condition = 'Needs Repair') but not yet logged
            rows = list(self.db.get_instruments_needing_repair())
            rows += list(self.db.get_instruments_marked_needs_repair())
            self._load_needs(rows)

    def _load_needs(self, rows):
        """One row per instrument (tag = 'inst:<id>')."""
        for r in rows:
            n_open = r["open_count"] or 0
            needed = r["needs"] or ""
            if n_open > 1:
                needed = f"({n_open}) {needed}"
            self.tree.insert("", "end", tags=(f"inst:{r['id']}",), values=(
                PRIORITY_LABELS.get(int(r["max_priority"] or 0), ""),
                r["instrument_desc"] or "",
                r["brand"] or "",
                r["barcode"] or r["district_no"] or "",
                needed,
                r["last_reported"] or "",
                (r["shop"] or "").strip(),
                "Needs Repair",
            ))
        self._summary_lbl.config(text=f"{len(rows)} instrument(s)")

    def _load_history(self, rows):
        """One row per repair record (tag = 'rep:<id>')."""
        for r in rows:
            done = bool((r["date_repaired"] or "").strip())
            shop = (r["assigned_to"] or "").strip() or (r["location"] or "").strip()
            self.tree.insert("", "end", tags=(f"rep:{r['id']}",), values=(
                PRIORITY_LABELS.get(int(r["priority"] or 0), ""),
                r["instrument_desc"] or "",
                r["brand"] or "",
                r["barcode"] or r["district_no"] or "",
                r["description"] or "",
                r["date_added"] or "",
                shop,
                "Repaired" if done else "Needs Repair",
            ))
        self._summary_lbl.config(text=f"{len(rows)} record(s)")

    def _load_cost(self):
        summary = self.db.get_repair_cost_summary()
        this_year = datetime.today().year
        grand = 0.0
        for rank, s in enumerate(summary, 1):
            total = float(s["total_spent"] or 0)
            grand += total
            yr = str(s["year_purchased"] or "").strip()[:4]
            age = (this_year - int(yr)) if yr.isdigit() else ""
            self.tree.insert("", "end", tags=(f"inst:{s['id']}",), values=(
                rank,
                s["instrument_desc"] or "",
                s["brand"] or "",
                s["barcode"] or s["district_no"] or "",
                s["repair_count"] or 0,
                f"${total:,.2f}",
                f"${float(s['est_value'] or 0):,.2f}",
                age,
                s["last_repair"] or "",
            ))
        self._summary_lbl.config(
            text=f"{len(summary)} instrument(s) repaired • ${grand:,.2f} total spent")

    # ─────────────────────────────────────────────────────────── Actions ───────

    def _selected_tag(self):
        """Return (kind, id) where kind is 'inst' or 'rep', or None."""
        sel = self.tree.selection()
        if not sel:
            return None
        tags = self.tree.item(sel[0], "tags")
        if not tags:
            return None
        tag = tags[0]
        if ":" in tag:
            kind, _id = tag.split(":", 1)
            return (kind, int(_id))
        return ("inst", int(tag))  # cost view fallback

    def _pick_open_repair(self, instrument_id, verb):
        """Resolve an instrument to one of its open repairs.  Returns a repair_id,
        or None if cancelled / none open.  Shows a chooser when there are several."""
        rows = [dict(r) for r in self.db.get_open_repairs_for_instrument(instrument_id)]
        if not rows:
            Messagebox.show_info("This instrument has no open repairs.",
                                 title="Nothing to Edit", parent=self)
            return None
        if len(rows) == 1:
            return rows[0]["id"]

        win = ttk.Toplevel(self)
        win.title(f"Choose a repair to {verb}")
        win.grab_set()
        ttk.Label(win, text=f"This instrument has {len(rows)} open repairs.\n"
                            f"Choose one to {verb}:", font=("Segoe UI", 9),
                  justify=LEFT).pack(anchor=W, padx=16, pady=(14, 6))
        lb = tk.Listbox(win, font=("Segoe UI", 9), height=min(len(rows), 10), width=54)
        lb.pack(fill=BOTH, expand=True, padx=16)
        for r in rows:
            lb.insert(END, f"{r.get('date_added') or '—'}  |  {r.get('description') or '(no description)'}")
        lb.selection_set(0)
        chosen = {"id": None}

        def _ok():
            sel = lb.curselection()
            if sel:
                chosen["id"] = rows[sel[0]]["id"]
            win.destroy()
        btns = ttk.Frame(win); btns.pack(pady=12)
        ttk.Button(btns, text="OK", bootstyle=PRIMARY, command=_ok).pack(side=LEFT, padx=4)
        ttk.Button(btns, text="Cancel", bootstyle=(SECONDARY, OUTLINE),
                   command=win.destroy).pack(side=LEFT, padx=4)
        from ui.theme import fit_window
        fit_window(win, 460, 320)
        self.wait_window(win)
        return chosen["id"]

    def _after_change(self):
        self._reload()
        try:
            self.inv.refresh()
        except Exception:
            pass

    def _upload_invoice(self):
        self.inv._upload_invoice()
        self._after_change()

    def _add_repair_scan(self):
        """Scan/type a barcode or serial, then open a repair record for it."""
        win = ttk.Toplevel(self)
        win.title("Mark Instrument for Repair")
        win.resizable(False, False)
        win.grab_set()
        ttk.Label(win, text="Scan or type a barcode / serial number:",
                  font=("Segoe UI", 9, "bold")).pack(anchor=W, padx=16, pady=(16, 4))
        var = tk.StringVar()
        entry = ttk.Entry(win, textvariable=var, width=32)
        entry.pack(padx=16, pady=2)
        entry.focus_set()
        status = ttk.Label(win, text="", font=("Segoe UI", 8), foreground="#CC0000")
        status.pack(anchor=W, padx=16)

        def _go(_e=None):
            text = var.get().strip()
            inst = (self.db.get_instrument_by_barcode(text)
                    or self.db.get_instrument_by_serial(text)) if text else None
            if not inst:
                status.config(text="No instrument found for that barcode / serial #.")
                entry.select_range(0, END)
                return
            win.destroy()
            from ui.repair_dialog import RepairDialog
            dlg = RepairDialog(self, self.db, instrument_id=inst["id"], repair_id=None)
            self.wait_window(dlg)
            self._after_change()

        entry.bind("<Return>", _go)
        btns = ttk.Frame(win)
        btns.pack(pady=12)
        ttk.Button(btns, text="Continue", bootstyle=WARNING, command=_go).pack(side=LEFT, padx=4)
        ttk.Button(btns, text="Cancel", bootstyle=(SECONDARY, OUTLINE),
                   command=win.destroy).pack(side=LEFT, padx=4)
        from ui.theme import fit_window
        fit_window(win, 340, 190)

    def _edit_selected(self):
        if self._view.get() == "cost":
            return
        tag = self._selected_tag()
        if tag is None:
            Messagebox.show_warning("Select an instrument first.", title="No Selection",
                                    parent=self)
            return
        kind, tid = tag
        if kind == "rep":
            repair_id = tid
        else:
            repair_id = self._pick_open_repair(tid, "edit")
            if repair_id is None:
                return
        with self.db._connect() as conn:
            row = conn.execute("SELECT instrument_id FROM repairs WHERE id=?",
                               (repair_id,)).fetchone()
        if not row:
            return
        from ui.repair_dialog import RepairDialog
        dlg = RepairDialog(self, self.db, instrument_id=row["instrument_id"],
                           repair_id=repair_id)
        self.wait_window(dlg)
        self._after_change()

    def _mark_repaired(self):
        tag = self._selected_tag()
        if tag is None:
            Messagebox.show_warning("Select an instrument first.", title="No Selection",
                                    parent=self)
            return
        kind, tid = tag
        if kind == "rep":
            with self.db._connect() as conn:
                row = conn.execute("SELECT instrument_id FROM repairs WHERE id=?",
                                   (tid,)).fetchone()
            instrument_id = row["instrument_id"] if row else None
            repair_ids = [tid]
        else:
            instrument_id = tid
            repair_ids = [r["id"] for r in self.db.get_open_repairs_for_instrument(tid)]
        if not repair_ids:
            # Flagged on the instrument only (condition = 'Needs Repair', nothing
            # logged) — confirm resetting the condition rather than dead-ending.
            from ui.repair_dialog import confirm_and_clear_needs_repair
            inst = self.db.get_instrument(instrument_id) if instrument_id else None
            if inst and (inst["condition"] or "").strip().lower() == "needs repair":
                confirm_and_clear_needs_repair(self, self.db, instrument_id)
                self._after_change()
                return
            Messagebox.show_info("This instrument has no open repairs.",
                                 title="Nothing to Mark", parent=self)
            return
        # Prefill from the single record; blank when marking several at once.
        if len(repair_ids) == 1:
            with self.db._connect() as conn:
                repair = dict(conn.execute("SELECT * FROM repairs WHERE id=?",
                                           (repair_ids[0],)).fetchone())
        else:
            repair = {}
        self._open_mark_dialog(instrument_id, repair_ids, repair)

    def _mark_out_for_repair(self):
        """Record that a needs-repair instrument has gone to the shop.  Sets the
        shop on its open repair(s); if it was only flagged on the instrument
        (condition = 'Needs Repair', no repair logged yet) a repair record is
        created so it can be tracked.  Moves the row into the Out-for-Repair view."""
        tag = self._selected_tag()
        if tag is None:
            Messagebox.show_warning("Select an instrument first.", title="No Selection",
                                    parent=self)
            return
        kind, tid = tag
        if kind == "rep":
            with self.db._connect() as conn:
                row = conn.execute("SELECT instrument_id FROM repairs WHERE id=?",
                                   (tid,)).fetchone()
            instrument_id = row["instrument_id"] if row else None
            repair_ids = [tid]
        else:
            instrument_id = tid
            repair_ids = [r["id"] for r in self.db.get_open_repairs_for_instrument(tid)]
        self._open_out_dialog(instrument_id, repair_ids)

    def _open_out_dialog(self, instrument_id, repair_ids):
        win = ttk.Toplevel(self)
        win.title("Mark Out for Repair")
        win.resizable(False, False)
        win.grab_set()

        hdr = ttk.Frame(win, bootstyle=WARNING)
        hdr.pack(fill=X)
        ttk.Label(hdr, text="🚚  Mark Out for Repair", font=("Segoe UI", 12, "bold"),
                  bootstyle=(INVERSE, WARNING)).pack(pady=10, padx=16, anchor=W)

        body = ttk.Frame(win)
        body.pack(fill=BOTH, expand=True, padx=18, pady=12)
        note = ("Record where this instrument went and when. It stays on the "
                "Needs / Out list until you mark it repaired.")
        ttk.Label(body, text=note, font=("Segoe UI", 8), foreground="#666",
                  wraplength=380, justify=LEFT).pack(anchor=W, pady=(0, 8))

        grid = ttk.Frame(body)
        grid.pack(fill=X)
        grid.columnconfigure(1, weight=1)
        shop_var = tk.StringVar()
        sent_var = tk.StringVar(value=datetime.today().strftime("%Y-%m-%d"))
        for i, (label, var) in enumerate([("Shop / Location:", shop_var),
                                          ("Date Sent (YYYY-MM-DD):", sent_var)]):
            ttk.Label(grid, text=label, font=("Segoe UI", 9)).grid(
                row=i, column=0, sticky=W, pady=4, padx=(0, 8))
            ttk.Entry(grid, textvariable=var, width=26).grid(row=i, column=1, sticky=EW, pady=4)

        def _save():
            shop_val = shop_var.get().strip()
            if not shop_val:
                Messagebox.show_warning("Enter the shop or location it went to.",
                                        title="Shop Required", parent=win)
                return
            sent_val = sent_var.get().strip()
            ids = list(repair_ids)
            if not ids:               # flagged on the instrument only — log one now
                if instrument_id is None:
                    win.destroy()
                    return
                ids = [self.db.add_repair({
                    "instrument_id": instrument_id, "priority": 1,
                    "date_added": sent_val or datetime.today().strftime("%Y-%m-%d"),
                    "assigned_to": shop_val, "date_repaired": "",
                    "description": "Sent for repair", "location": shop_val,
                    "est_cost": 0, "act_cost": 0, "invoice_number": "", "notes": "",
                })]
            for rid in ids:
                with self.db._connect() as conn:
                    existing = conn.execute("SELECT * FROM repairs WHERE id=?",
                                            (rid,)).fetchone()
                if not existing:
                    continue
                data = dict(existing)
                data["assigned_to"] = shop_val
                if sent_val:
                    data["date_added"] = sent_val
                self.db.update_repair(rid, data)
            win.destroy()
            self._after_change()

        btn = ttk.Frame(win)
        btn.pack(fill=X, padx=16, pady=12)
        ttk.Button(btn, text="Cancel", bootstyle=(SECONDARY, OUTLINE),
                   command=win.destroy).pack(side=RIGHT, padx=4)
        ttk.Button(btn, text="Save", bootstyle=WARNING, command=_save).pack(side=RIGHT, padx=4)

        from ui.theme import fit_window
        fit_window(win, 430, 250)

    def _open_mark_dialog(self, instrument_id, repair_ids, repair):
        multi = len(repair_ids) > 1

        win = ttk.Toplevel(self)
        win.title("Mark Repaired")
        win.resizable(False, False)
        win.grab_set()

        hdr = ttk.Frame(win, bootstyle=SUCCESS)
        hdr.pack(fill=X)
        ttk.Label(hdr, text="✅  Mark Repaired", font=("Segoe UI", 12, "bold"),
                  bootstyle=(INVERSE, SUCCESS)).pack(pady=10, padx=16, anchor=W)

        body = ttk.Frame(win)
        body.pack(fill=BOTH, expand=True, padx=18, pady=12)
        intro = (f"Applies to all {len(repair_ids)} open repairs for this instrument."
                 if multi else (repair.get("description") or "Repair"))
        ttk.Label(body, text=f"{intro}\nFill in what you know — any field can be left blank.",
                  font=("Segoe UI", 8), foreground="#666", justify=LEFT).pack(anchor=W, pady=(0, 8))

        grid = ttk.Frame(body)
        grid.pack(fill=X)
        grid.columnconfigure(1, weight=1)
        date_var = tk.StringVar(value=repair.get("date_repaired") or "")
        shop_var = tk.StringVar(value=repair.get("assigned_to") or "")
        cost_var = tk.StringVar(value=(f"{repair.get('act_cost'):.2f}"
                                       if repair.get("act_cost") else ""))

        fields = [("Date Repaired (YYYY-MM-DD):", date_var), ("Shop:", shop_var)]
        if not multi:
            fields.append(("Actual Cost ($):", cost_var))
        for i, (label, var) in enumerate(fields):
            ttk.Label(grid, text=label, font=("Segoe UI", 9)).grid(
                row=i, column=0, sticky=W, pady=4, padx=(0, 8))
            ttk.Entry(grid, textvariable=var, width=26).grid(row=i, column=1, sticky=EW, pady=4)

        def _use_today():
            date_var.set(datetime.today().strftime("%Y-%m-%d"))
        ttk.Button(grid, text="Use today's date", bootstyle=(SECONDARY, OUTLINE, LINK),
                   command=_use_today).grid(row=0, column=2, padx=(6, 0))

        tip = ("Cost isn't set when marking several at once — use Edit to record a cost "
               "per repair." if multi else
               "Tip: leave the date blank to keep it in the Needs-Repair list "
               "while still recording the shop/cost.")
        ttk.Label(body, text=tip, font=("Segoe UI", 8), foreground="#888",
                  wraplength=360, justify=LEFT).pack(anchor=W, pady=(8, 0))

        def _save():
            date_val = date_var.get().strip()
            shop_val = shop_var.get().strip()
            act_cost = None
            if not multi:
                cost_raw = cost_var.get().strip().replace("$", "").replace(",", "")
                if cost_raw:
                    try:
                        act_cost = float(cost_raw)
                    except ValueError:
                        Messagebox.show_warning("Actual cost must be a number (or blank).",
                                                title="Invalid Cost", parent=win)
                        return
            for rid in repair_ids:
                with self.db._connect() as conn:
                    existing = conn.execute("SELECT * FROM repairs WHERE id=?",
                                            (rid,)).fetchone()
                if not existing:
                    continue
                data = dict(existing)
                data["date_repaired"] = date_val
                data["assigned_to"] = shop_val
                if act_cost is not None:
                    data["act_cost"] = act_cost
                self.db.update_repair(rid, data)
            # If that closed the instrument's last open repair, ASK whether to
            # reset its 'Needs Repair' condition to 'Good' (never automatic — the
            # repair may have been deferred or judged too costly).
            if date_val and instrument_id is not None:
                from ui.repair_dialog import confirm_and_clear_needs_repair
                confirm_and_clear_needs_repair(win, self.db, instrument_id)
            win.destroy()
            self._after_change()

        btn = ttk.Frame(win)
        btn.pack(fill=X, padx=16, pady=12)
        ttk.Button(btn, text="Cancel", bootstyle=(SECONDARY, OUTLINE),
                   command=win.destroy).pack(side=RIGHT, padx=4)
        ttk.Button(btn, text="Save", bootstyle=SUCCESS, command=_save).pack(side=RIGHT, padx=4)

        from ui.theme import fit_window
        fit_window(win, 430, 300)

    def _export_view(self):
        view = self._view.get()
        if view == "cost":
            self.inv._export_cost_report()
        elif view == "history":
            self.inv._export_repairs()
        else:  # needs / out
            self.inv._export_repairs_needed()
