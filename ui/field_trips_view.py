"""
ui/field_trips_view.py - Field Trips tab of Teacher Tools.

Plan a trip the way the district application asks for it (who, when, where,
how, what it costs), then keep working it: per-student attendance and the
cost-per-student calculator, parent chaperones (with contact autofill from
the student database and the 1-adult-per-10-students rule), the
approval/sub/bus checklist, and the reminder emails — families, chaperones,
and a heads-up to other teachers with the student list.
"""

import os
import tkinter as tk
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from ttkbootstrap.dialogs import Messagebox
from datetime import datetime

from ui.theme import fs, muted_fg, subtle_fg, fit_window
import concert_tools as ct
import field_trip_tools as ft


def _copy(widget, text):
    widget.clipboard_clear()
    widget.clipboard_append(text)


class FieldTripsView(ttk.Frame):
    def __init__(self, parent, db, main_db, base_dir):
        super().__init__(parent)
        self.db = db
        self.main_db = main_db
        self.base_dir = base_dir

        hdr = ttk.Frame(self)
        hdr.pack(fill=X, padx=12, pady=(10, 4))
        left = ttk.Frame(hdr)
        left.pack(side=LEFT)
        ttk.Label(left, text="Field Trip Planner",
                  font=("Segoe UI", fs(15), "bold")).pack(anchor=W)
        ttk.Label(left, text="Every upcoming trip and its full checklist on "
                             "one page. Click a checklist item to cycle "
                             "☐ to do → ☑ done → N/A, or right-click to mark "
                             "it N/A right away (no bus needed, no sub, no "
                             "fee…).",
                  font=("Segoe UI", fs(8)), foreground=subtle_fg()).pack(anchor=W)
        ttk.Button(hdr, text="➕ New Field Trip", bootstyle=SUCCESS,
                   command=self._new_trip).pack(side=RIGHT, padx=(4, 0))
        ttk.Button(hdr, text="📋 Copy From Previous…",
                   bootstyle=(SECONDARY, OUTLINE),
                   command=self._copy_from_previous).pack(side=RIGHT)
        ttk.Button(hdr, text="📊 Export Roster (Excel)…",
                   bootstyle=(INFO, OUTLINE),
                   command=self._export_roster).pack(side=RIGHT, padx=(0, 4))

    def _export_roster(self):
        from ui.roster_export_view import open_roster_export
        open_roster_export(self, self.main_db, self.base_dir, self._student_year(),
                           context="For a field trip: choose the class(es) going.")

        # ── Upcoming trips: scrollable cards, Word-doc style ──
        up_frame = tk.LabelFrame(self, text=" Upcoming Field Trips ",
                                 font=("Segoe UI", fs(10), "bold"),
                                 padx=4, pady=2)
        up_frame.pack(fill=BOTH, expand=True, padx=12, pady=(4, 4))
        self._cards = self._scroll_area(up_frame)

        # ── Completed trips: compact read-only list, its own scroll ──
        done_frame = tk.LabelFrame(self, text=" Completed Field Trips "
                                              "(read-only) ",
                                   font=("Segoe UI", fs(10), "bold"),
                                   padx=4, pady=2, height=170)
        done_frame.pack(fill=X, padx=12, pady=(4, 8))
        done_frame.pack_propagate(False)
        self._done_rows = self._scroll_area(done_frame)

        self._past_dbs = {}
        self.refresh()

    def _scroll_area(self, parent):
        """A vertical-scrolling inner frame (mouse wheel works on hover)."""
        canvas = tk.Canvas(parent, highlightthickness=0)
        sb = ttk.Scrollbar(parent, orient=VERTICAL, command=canvas.yview)
        inner = ttk.Frame(canvas)
        inner.bind("<Configure>",
                   lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        cw = canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.bind("<Configure>",
                    lambda e: canvas.itemconfigure(cw, width=e.width))
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side=LEFT, fill=BOTH, expand=True)
        sb.pack(side=RIGHT, fill=Y)

        def _wheel(e):
            canvas.yview_scroll(-1 * (e.delta // 120), "units")
        canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", _wheel))
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))
        return inner

    # ── Context ──────────────────────────────────────────────────────────────

    def _year(self):
        base = os.path.basename(self.db.db_path)
        if base.startswith("lesson_plans_") and base.endswith(".db"):
            return base[len("lesson_plans_"):-len(".db")]
        return None

    def _student_year(self):
        years = self.main_db.get_school_years()
        hub_year = self._year()
        if hub_year and hub_year in years:
            return hub_year
        return years[0] if years else None

    def _teacher(self):
        from ui.settings_dialog import load_settings
        teacher = (load_settings(self.base_dir).get("teacher") or {})
        school = (teacher.get("school_name") or "").strip()
        director = os.path.basename(self.base_dir.rstrip("\\/"))
        return school, director

    def _program_type(self):
        from ui.settings_dialog import load_settings
        return (load_settings(self.base_dir).get("teacher") or {}).get(
            "program_type", "band")

    def _students(self):
        return [dict(r) for r in self.main_db.get_students_for_email(
            school_year=self._student_year())]

    def _attending(self, trip):
        return ft.roster(self._students(), dict(trip),
                         self.db.get_trip_exclusions(trip["id"]))

    def _past_trips(self):
        """(year, trip dict, that year's db) for every other school year on
        disk — shown read-only for reference and reuse."""
        from lesson_plan_db import list_available_school_years, get_lesson_plan_db
        cur = self._year()
        out = []
        for y in list_available_school_years(self.base_dir):
            if y == cur:
                continue
            try:
                if y not in self._past_dbs:
                    self._past_dbs[y] = get_lesson_plan_db(self.base_dir, y)
                pdb = self._past_dbs[y]
                for t in pdb.get_field_trips():
                    out.append((y, dict(t), pdb))
            except Exception:
                continue
        out.sort(key=lambda x: (x[0], x[1].get("depart_date") or ""),
                 reverse=True)
        return out

    # ── Card overview ────────────────────────────────────────────────────────

    def refresh(self):
        for w in self._cards.winfo_children():
            w.destroy()
        for w in self._done_rows.winfo_children():
            w.destroy()
        students = self._students()
        trips = [dict(t) for t in self.db.get_field_trips(self._year())]

        def is_done(t):
            days = ct.days_until(t.get("depart_date"))
            return days is not None and days < 0

        upcoming = [t for t in trips if not is_done(t)]
        completed = [t for t in trips if is_done(t)]
        upcoming.sort(key=lambda t: (ct.parse_date(t.get("depart_date")) is None,
                                     ct.parse_date(t.get("depart_date"))
                                     or ct.parse_date("2999-01-01")))
        completed.sort(key=lambda t: t.get("depart_date") or "", reverse=True)

        if not upcoming:
            ttk.Label(self._cards, text="No upcoming field trips. Click "
                                        "“➕ New Field Trip” to plan one, or "
                                        "reuse a completed trip below as a "
                                        "template.",
                      font=("Segoe UI", fs(10)), foreground=muted_fg()
                      ).pack(anchor=W, padx=8, pady=14)
        for t in upcoming:
            self._trip_card(t, students)

        # Completed: this year's finished trips, then previous years
        def done_row(label, opener):
            row = ttk.Frame(self._done_rows)
            row.pack(fill=X, padx=4, pady=1)
            ttk.Button(row, text=label, bootstyle=(SECONDARY, OUTLINE, LINK),
                       command=opener).pack(side=LEFT)

        year = self._year()
        for t in completed:
            dest = f", {t['destination']}" if t.get("destination") else ""
            done_row(f"✔ {t.get('depart_date')}  ·  {t.get('name')}{dest}",
                     lambda tr=t: _PastTripDialog(self, year, dict(tr), self.db))
        for pyear, t, pdb in self._past_trips():
            dest = f", {t['destination']}" if t.get("destination") else ""
            done_row(f"🕰 {pyear}  ·  {t.get('name')}"
                     f"  ({t.get('depart_date') or 'no date'}{dest})",
                     lambda y=pyear, tr=t, p=pdb:
                     _PastTripDialog(self, y, dict(tr), p))
        if not completed and not self._past_trips():
            ttk.Label(self._done_rows, text="Completed trips will collect "
                                            "here for reference and reuse.",
                      font=("Segoe UI", fs(9)), foreground=muted_fg()
                      ).pack(anchor=W, padx=6, pady=6)

    def _trip_card(self, t, students):
        days = ct.days_until(t.get("depart_date"))
        when = ct.fmt_date(t.get("depart_date")) if t.get("depart_date") else "no date yet"
        title = f" {when}: {t['name']} "

        card = tk.LabelFrame(self._cards, text=title,
                             font=("Segoe UI", fs(11), "bold"),
                             padx=10, pady=6, bd=2, relief="groove")
        card.pack(fill=X, padx=6, pady=6)

        # ── Info line + countdown ──
        top = ttk.Frame(card)
        top.pack(fill=X)
        attending = ft.roster(students, t,
                              self.db.get_trip_exclusions(t["id"]))
        n = len(attending)
        need = ft.chaperones_needed(n)
        have = len(self.db.get_trip_chaperones(t["id"]))
        bits = []
        if t.get("destination"):
            bits.append(f"@ {t['destination']}")
        if t.get("groups_list"):
            bits.append(t["groups_list"])
        bits.append(f"{n} students")
        bits.append(f"chaperones {have}/{need}")
        dt = (t.get("depart_time") or "").strip()
        rt = (t.get("return_time") or "").strip()
        if dt or rt:
            bits.append(f"{dt or '?'} to {rt or '?'}")
        ttk.Label(top, text="  ·  ".join(bits),
                  font=("Segoe UI", fs(9)), foreground=muted_fg()
                  ).pack(side=LEFT)
        if days is None:
            badge, style = "set a date", SECONDARY
        elif days < 0:
            badge, style = "done", SECONDARY
        elif days == 0:
            badge, style = "TODAY!", DANGER
        elif days <= 14:
            badge, style = f"in {days} day{'s' if days != 1 else ''}", WARNING
        else:
            badge, style = f"in {days} days", SUCCESS
        ttk.Label(top, text=badge, font=("Segoe UI", fs(10), "bold"),
                  bootstyle=style).pack(side=RIGHT)

        # ── Checklist: click any item to cycle its state ──
        sent = {r["stage"] for r in self.db.get_trip_reminders(t["id"])
                if r["sent_date"]}
        staff_emailed = any(s.startswith("teachers-") for s in sent)
        grid = ttk.Frame(card)
        grid.pack(fill=X, pady=(6, 2))
        for col in range(3):
            grid.columnconfigure(col, weight=1)

        def _item_label(state, label):
            if state == ft.CHECK_DONE:
                return f"☑  {label}", "#1a7a1a"
            if state == ft.CHECK_NA:
                return f"N/A  {label}", "#999999"
            return f"☐  {label}", "#B45309"

        def _cycle(key, trip_id=t["id"]):
            cur = int(self.db.get_field_trip(trip_id)[key] or 0)
            self.db.update_field_trip(trip_id, {key: (cur + 1) % 3})
            self.refresh()

        def _set_na(key, trip_id=t["id"]):
            cur = int(self.db.get_field_trip(trip_id)[key] or 0)
            new = ft.CHECK_TODO if cur == ft.CHECK_NA else ft.CHECK_NA
            self.db.update_field_trip(trip_id, {key: new})
            self.refresh()

        for i, (key, label) in enumerate(ft.CHECKLIST_ITEMS):
            state = int(t.get(key) or 0)
            text, color = _item_label(state, label)
            lbl = ttk.Label(grid, text=text, font=("Segoe UI", fs(9)),
                            foreground=color, cursor="hand2")
            lbl.grid(row=i // 3, column=i % 3, sticky=W, padx=(0, 12), pady=1)
            lbl.bind("<Button-1>", lambda e, k=key: _cycle(k))
            lbl.bind("<Button-3>", lambda e, k=key: _set_na(k))
        # Derived item: staff emailed (auto from the teachers reminders)
        text, color = _item_label(
            ft.CHECK_DONE if staff_emailed else ft.CHECK_TODO, "Staff emailed")
        ttk.Label(grid, text=text + "  (auto)", font=("Segoe UI", fs(9)),
                  foreground=color).grid(row=2, column=0, sticky=W,
                                         padx=(0, 12), pady=1)

        # ── Reminders summary ──
        due = ft.stages_due(t.get("depart_date"), sent)
        due_auds = sorted({a for a, _ in due})
        rbits = []
        for audience in ft.AUDIENCES:
            n_sent = sum(1 for s in sent if s.startswith(audience + "-"))
            mark = ("⚠ due" if audience in due_auds
                    else f"{n_sent}/2 sent")
            rbits.append(f"{audience} {mark}")
        rline = "Reminders:  " + "   ·   ".join(rbits)
        ttk.Label(card, text=rline, font=("Segoe UI", fs(9)),
                  foreground="#B45309" if due_auds else muted_fg()
                  ).pack(anchor=W, pady=(2, 2))

        # ── Actions ──
        btns = ttk.Frame(card)
        btns.pack(fill=X, pady=(2, 0))
        ttk.Button(btns, text="✏ Edit", bootstyle=(PRIMARY, OUTLINE),
                   command=lambda tr=t: self._edit_trip(tr)).pack(side=LEFT, padx=(0, 4))
        ttk.Button(btns, text="👥 Roster & Costs", bootstyle=(PRIMARY, OUTLINE),
                   command=lambda tr=t: self._roster_costs(tr)).pack(side=LEFT, padx=4)
        ttk.Button(btns, text="🧑‍🤝‍🧑 Chaperones", bootstyle=(INFO, OUTLINE),
                   command=lambda tr=t: self._chaperones(tr)).pack(side=LEFT, padx=4)
        ttk.Button(btns, text="✉ Reminders", bootstyle=(WARNING, OUTLINE),
                   command=lambda tr=t: self._reminders(tr)).pack(side=LEFT, padx=4)
        ttk.Button(btns, text="🗑", bootstyle=(DANGER, OUTLINE), width=3,
                   command=lambda tr=t: self._delete_trip(tr)).pack(side=RIGHT)

    # ── CRUD ─────────────────────────────────────────────────────────────────

    def _new_trip(self, template=None):
        seed = dict(template) if template else None
        dlg = _TripDialog(self, seed=seed, program_type=self._program_type())
        self.wait_window(dlg)
        if dlg.result:
            # A template contributes what the dialog doesn't show (extra
            # costs, funding, saved emails); the dialog's fields win.
            data = dict(template) if template else {}
            data.update(dlg.result)
            data["school_year"] = self._year()
            self.db.add_field_trip(data)
            self.refresh()

    def _copy_from_previous(self):
        """Start a new trip from any earlier trip — this year's or a past
        year's — carrying destination, travel, costs, notes, and the saved
        email templates (but not dates, roster, approvals, or chaperones)."""
        options = []
        for t in self.db.get_field_trips(self._year()):
            options.append((f"{self._year()}  ·  {t['name']}  "
                            f"({t['depart_date'] or 'no date'})", dict(t)))
        for year, t, _pdb in self._past_trips():
            options.append((f"{year}  ·  {t.get('name')}  "
                            f"({t.get('depart_date') or 'no date'})", t))
        if not options:
            Messagebox.show_info("No earlier trips to copy from yet.",
                                 title="Nothing to Copy",
                                 parent=self.winfo_toplevel())
            return

        win = ttk.Toplevel(self.winfo_toplevel())
        win.title("Copy From Previous Trip")
        win.grab_set()
        ttk.Label(win, text="Choose the trip to use as a template:",
                  font=("Segoe UI", 10, "bold")).pack(anchor=W, padx=16,
                                                      pady=(14, 4))
        ttk.Label(win, text="Copies the what/where/how, costs, notes, and "
                            "saved emails — you'll set the new dates next.",
                  font=("Segoe UI", 8), foreground=muted_fg()).pack(anchor=W, padx=16)
        lb = tk.Listbox(win, font=("Segoe UI", 10), height=10, width=54)
        lb.pack(fill=BOTH, expand=True, padx=16, pady=8)
        for label, _t in options:
            lb.insert(END, label)
        lb.selection_set(0)
        chosen = {"t": None}

        def _ok():
            sel = lb.curselection()
            if sel:
                chosen["t"] = options[sel[0]][1]
            win.destroy()
        lb.bind("<Double-1>", lambda e: _ok())
        btns = ttk.Frame(win)
        btns.pack(fill=X, padx=16, pady=(0, 12))
        ttk.Button(btns, text="Cancel", bootstyle=(SECONDARY, OUTLINE),
                   command=win.destroy).pack(side=RIGHT, padx=4)
        ttk.Button(btns, text="Use as Template", bootstyle=SUCCESS,
                   command=_ok).pack(side=RIGHT, padx=4)
        fit_window(win, 480, 380)
        self.wait_window(win)
        if chosen["t"]:
            self._new_trip(template=ft.trip_template(chosen["t"]))

    def _edit_trip(self, t):
        dlg = _TripDialog(self, seed=dict(t),
                          program_type=self._program_type(), editing=True)
        self.wait_window(dlg)
        if dlg.result:
            self.db.update_field_trip(t["id"], dlg.result)
            self.refresh()

    def _delete_trip(self, t):
        if Messagebox.yesno(f"Delete “{t['name']}” (roster choices, "
                            "chaperones, and reminder history too)?",
                            title="Delete Field Trip",
                            parent=self.winfo_toplevel()) != "Yes":
            return
        self.db.delete_field_trip(t["id"])
        self.refresh()

    # ── Tools ────────────────────────────────────────────────────────────────

    def _roster_costs(self, t):
        dlg = _RosterCostsDialog(self, self.db, dict(t), self._students())
        self.wait_window(dlg)
        self.refresh()

    def _chaperones(self, t):
        attending = self._attending(t)
        dlg = _ChaperonesDialog(self, self.db, dict(t), self._students(),
                                len(attending), attending=attending)
        self.wait_window(dlg)
        self.refresh()

    def _reminders(self, t):
        dlg = _RemindersDialog(self, self.db, dict(t), self._students(),
                               self._attending(t), self._teacher())
        self.wait_window(dlg)
        self.refresh()


# ═══════════════════════════════════════════ Past-year viewer ════════════════

class _PastTripDialog(ttk.Toplevel):
    """Read-only look at a previous year's trip — costs, itinerary notes,
    chaperones, and the saved emails — with one button to reuse it all as
    the template for this year's version."""

    def __init__(self, parent_view, year, trip, pdb):
        super().__init__(parent_view.winfo_toplevel())
        self.view = parent_view
        self.trip = trip
        self.title(f"{trip.get('name')} — {year} (read-only)")
        self.resizable(True, True)
        self.grab_set()

        ttk.Label(self, text=f"🕰  {trip.get('name')} — {year}",
                  font=("Segoe UI", 12, "bold"),
                  bootstyle=PRIMARY).pack(anchor=W, padx=16, pady=(12, 0))
        ttk.Label(self, text="Read-only — from a previous school year.",
                  font=("Segoe UI", 8), foreground=muted_fg()).pack(anchor=W, padx=16)

        lines = []
        when = ct.fmt_date(trip.get("depart_date"))
        dt, rt = (trip.get("depart_time") or "").strip(), (trip.get("return_time") or "").strip()
        lines.append(f"When: {when}" + (f", {dt}" if dt else "")
                     + (f"  →  back {rt}" if rt else ""))
        if trip.get("destination"):
            lines.append(f"Destination: {trip['destination']}")
        if trip.get("travel_method"):
            lines.append(f"Travel: {trip['travel_method']}")
        if trip.get("groups_list"):
            lines.append(f"Groups: {trip['groups_list']}")
        costs = ft.trip_costs(trip, 0)
        lines.append("")
        lines.append("Costs that year:")
        for label, key in [("Entry / registration", "entry"),
                           ("Bus / transportation", "transport"),
                           ("Food", "food"), ("Substitute", "sub"),
                           ("Other", "other")]:
            if costs[key]:
                lines.append(f"  {label}: ${costs[key]:,.2f}")
        lines.append(f"  Total expenses: ${costs['total']:,.2f}")
        funding = trip.get("funding") or ""
        if funding:
            lines.append(f"  Funding: {funding}"
                         + ("  (fully covered)" if trip.get("covered") else ""))
        chaps = [dict(c) for c in pdb.get_trip_chaperones(trip["id"])] if pdb else []
        if chaps:
            lines.append("")
            lines.append(f"Chaperones ({len(chaps)}):")
            for c in chaps:
                bits = [c["name"]]
                if (c.get("phone") or "").strip():
                    bits.append(c["phone"])
                if (c.get("email") or "").strip():
                    bits.append(c["email"])
                lines.append("  " + "  ·  ".join(bits))
        if (trip.get("notes") or "").strip():
            lines.append("")
            lines.append("Notes / itinerary:")
            lines.append(trip["notes"])

        box = tk.Text(self, font=("Calibri", 11), width=72, height=16,
                      relief="solid", bd=1, wrap=WORD)
        box.insert("1.0", "\n".join(lines))
        box.config(state="disabled")
        box.pack(fill=BOTH, expand=True, padx=16, pady=8)

        # Saved emails from that year
        erow = ttk.Frame(self)
        erow.pack(fill=X, padx=16)
        ttk.Label(erow, text="Saved emails:", font=("Segoe UI", 9, "bold")
                  ).pack(side=LEFT)
        for audience, label in [("families", "Families"),
                                ("chaperones", "Chaperones"),
                                ("teachers", "Teachers")]:
            text = (trip.get(f"email_{audience}") or "").strip()
            btn = ttk.Button(erow, text=f"✉ {label}",
                             bootstyle=(PRIMARY, OUTLINE),
                             command=lambda a=audience, l=label:
                             self._view_email(l, self.trip.get(f"email_{a}")))
            btn.pack(side=LEFT, padx=3)
            if not text:
                btn.config(state=DISABLED)

        btns = ttk.Frame(self)
        btns.pack(fill=X, padx=16, pady=12)
        ttk.Button(btns, text="Close", bootstyle=(SECONDARY, OUTLINE),
                   command=self.destroy).pack(side=RIGHT, padx=4)
        ttk.Button(btns, text="📋 Use as Template for a New Trip…",
                   bootstyle=SUCCESS, command=self._reuse).pack(side=RIGHT, padx=4)
        fit_window(self, 620, 600)

    def _view_email(self, label, text):
        win = ttk.Toplevel(self)
        win.title(f"Saved email — {label}")
        win.grab_set()
        box = tk.Text(win, font=("Calibri", 11), width=74, height=20,
                      relief="solid", bd=1, wrap=WORD)
        box.insert("1.0", text or "")
        box.config(state="disabled")
        box.pack(fill=BOTH, expand=True, padx=14, pady=(14, 6))
        b = ttk.Frame(win)
        b.pack(fill=X, padx=14, pady=(0, 12))
        ttk.Button(b, text="Close", bootstyle=(SECONDARY, OUTLINE),
                   command=win.destroy).pack(side=RIGHT, padx=4)
        ttk.Button(b, text="📋 Copy", bootstyle=PRIMARY,
                   command=lambda: _copy(win, text or "")).pack(side=RIGHT, padx=4)
        fit_window(win, 640, 520)

    def _reuse(self):
        template = ft.trip_template(self.trip)
        self.destroy()
        self.view._new_trip(template=template)


# ═══════════════════════════════════════════ Trip editor ═════════════════════

class _TripDialog(ttk.Toplevel):
    def __init__(self, parent, seed=None, program_type="band", editing=False):
        super().__init__(parent.winfo_toplevel())
        self.result = None
        seed = seed or {}
        self.title("Edit Field Trip" if editing else "New Field Trip")
        self.resizable(True, True)
        self.grab_set()

        ttk.Label(self, text="🚌  Field Trip", font=("Segoe UI", 12, "bold"),
                  bootstyle=PRIMARY).pack(anchor=W, padx=16, pady=(12, 4))

        btns = ttk.Frame(self)
        btns.pack(fill=X, side=BOTTOM, padx=16, pady=10)
        ttk.Button(btns, text="Cancel", bootstyle=(SECONDARY, OUTLINE),
                   command=self.destroy).pack(side=RIGHT, padx=4)
        ttk.Button(btns, text="Save", bootstyle=SUCCESS,
                   command=self._save).pack(side=RIGHT, padx=4)

        body = ttk.Frame(self)
        body.pack(fill=BOTH, expand=True, padx=16, pady=4)
        self._vars = {}

        def entry(parent, label, key, width=24, hint=""):
            ttk.Label(parent, text=label, font=("Segoe UI", 9, "bold")
                      ).pack(anchor=W, pady=(8, 0))
            if hint:
                ttk.Label(parent, text=hint, font=("Segoe UI", 8),
                          foreground=muted_fg()).pack(anchor=W)
            v = tk.StringVar(value=str(seed.get(key) or ""))
            self._vars[key] = v
            ttk.Entry(parent, textvariable=v, width=width).pack(anchor=W)
            return v

        entry(body, "Field trip name", "name", width=44)

        # Groups
        ttk.Label(body, text="Class or group(s) attending",
                  font=("Segoe UI", 9, "bold")).pack(anchor=W, pady=(8, 2))
        from ui.ensembles import ensembles_for
        std = ensembles_for(program_type)
        chosen = set(g.strip() for g in
                     (seed.get("groups_list") or "").split(",") if g.strip())
        self._grp_vars = {}
        grid = ttk.Frame(body)
        grid.pack(anchor=W)
        for i, g in enumerate(std):
            bv = tk.BooleanVar(value=g in chosen)
            self._grp_vars[g] = bv
            ttk.Checkbutton(grid, text=g, variable=bv, bootstyle=PRIMARY
                            ).grid(row=i // 3, column=i % 3, sticky=W,
                                   padx=(0, 14), pady=2)
        extras = [g for g in chosen if g not in std]
        self._extra_grp = tk.StringVar(value=", ".join(extras))
        ttk.Label(body, text="Other groups (comma-separated)",
                  font=("Segoe UI", 8), foreground=muted_fg()).pack(anchor=W)
        ttk.Entry(body, textvariable=self._extra_grp, width=44).pack(anchor=W)

        entry(body, "Trip destination", "destination", width=44)

        row = ttk.Frame(body)
        row.pack(fill=X, anchor=W)
        c1 = ttk.Frame(row); c1.pack(side=LEFT, padx=(0, 16))
        c2 = ttk.Frame(row); c2.pack(side=LEFT, padx=(0, 16))
        c3 = ttk.Frame(row); c3.pack(side=LEFT, padx=(0, 16))
        c4 = ttk.Frame(row); c4.pack(side=LEFT)
        entry(c1, "Departure date", "depart_date", width=12,
              hint="YYYY-MM-DD")
        entry(c2, "Departure time", "depart_time", width=10,
              hint="e.g. 8:45am")
        entry(c3, "Return date", "return_date", width=12,
              hint="blank = same day")
        entry(c4, "Return time", "return_time", width=10, hint=" ")

        row2 = ttk.Frame(body)
        row2.pack(fill=X, anchor=W)
        c5 = ttk.Frame(row2); c5.pack(side=LEFT, padx=(0, 16))
        c6 = ttk.Frame(row2); c6.pack(side=LEFT)
        ttk.Label(c5, text="Method of travel", font=("Segoe UI", 9, "bold")
                  ).pack(anchor=W, pady=(8, 0))
        tv = tk.StringVar(value=str(seed.get("travel_method") or ""))
        self._vars["travel_method"] = tv
        ttk.Combobox(c5, textvariable=tv, values=ft.TRAVEL_METHODS,
                     width=18).pack(anchor=W)
        entry(c6, "Entry / registration fee ($ total)", "entry_fee", width=10,
              hint="One-time fee the school pays per ensemble entered\n"
                   "(e.g. $350 for a festival). More costs in Roster & Costs.")

        # Tracking checklist — tri-state like the teacher's old Word doc:
        # ☐ to do → ☑ done → N/A (item doesn't apply to this trip).
        ttk.Label(body, text="Checklist", font=("Segoe UI", 9, "bold")
                  ).pack(anchor=W, pady=(10, 0))
        ttk.Label(body, text="Click an item to cycle:  ☐ to do → ☑ done → "
                             "N/A; right-click to mark it N/A right away "
                             "(private vehicles = no bus request, after "
                             "school = no sub, free event = no payment). "
                             "FinalForms replaces paper permission "
                             "slips — the office builds the participant "
                             "group so you have realtime medical and "
                             "emergency-contact info during the trip.",
                  font=("Segoe UI", 8), foreground=muted_fg(),
                  wraplength=560, justify=LEFT).pack(anchor=W)
        self._check_states = {}
        cgrid = ttk.Frame(body)
        cgrid.pack(anchor=W, pady=(4, 0), fill=X)
        cgrid.columnconfigure(0, weight=1)
        cgrid.columnconfigure(1, weight=1)

        def _make_item(idx, key, label):
            self._check_states[key] = int(seed.get(key) or 0)
            btn = ttk.Button(cgrid)

            def render():
                s = self._check_states[key]
                if s == ft.CHECK_DONE:
                    btn.config(text=f"☑  {label}", bootstyle=SUCCESS)
                elif s == ft.CHECK_NA:
                    btn.config(text=f"N/A  {label}", bootstyle=SECONDARY)
                else:
                    btn.config(text=f"☐  {label}",
                               bootstyle=(SECONDARY, OUTLINE))

            def cycle():
                self._check_states[key] = (self._check_states[key] + 1) % 3
                render()

            def set_na(_e=None):
                s = self._check_states[key]
                self._check_states[key] = (ft.CHECK_TODO if s == ft.CHECK_NA
                                           else ft.CHECK_NA)
                render()

            btn.config(command=cycle)
            btn.bind("<Button-3>", set_na)
            render()
            btn.grid(row=idx // 2, column=idx % 2, sticky="ew",
                     padx=(0, 8), pady=2)

        for i, (key, label) in enumerate(ft.CHECKLIST_ITEMS):
            _make_item(i, key, label)

        ttk.Label(body, text="Notes", font=("Segoe UI", 9, "bold")
                  ).pack(anchor=W, pady=(8, 0))
        self._notes = tk.Text(body, height=3, width=60, font=("Segoe UI", 9),
                              relief="solid", bd=1, wrap=WORD)
        self._notes.insert("1.0", str(seed.get("notes") or ""))
        self._notes.pack(anchor=W, fill=X)

        fit_window(self, 620, 640)

    def _save(self):
        name = self._vars["name"].get().strip()
        if not name:
            Messagebox.show_warning("Give the trip a name.",
                                    title="Missing Name", parent=self)
            return
        dd = self._vars["depart_date"].get().strip()
        if dd and not ct.parse_date(dd):
            Messagebox.show_warning("Departure date must be YYYY-MM-DD.",
                                    title="Check the Date", parent=self)
            return
        groups = [g for g, bv in self._grp_vars.items() if bv.get()]
        groups += [x.strip() for x in self._extra_grp.get().split(",")
                   if x.strip()]
        data = {k: v.get().strip() for k, v in self._vars.items()}
        data["groups_list"] = ", ".join(groups)
        data["notes"] = self._notes.get("1.0", "end").strip()
        for key, _label in ft.CHECKLIST_ITEMS:
            data[key] = self._check_states[key]
        self.result = data
        self.destroy()


# ═══════════════════════════════════════════ Roster & costs ══════════════════

class _RosterCostsDialog(ttk.Toplevel):
    """Attendance (default: everyone in the groups) + the cost calculator."""

    def __init__(self, parent, db, trip, students):
        super().__init__(parent.winfo_toplevel())
        self.db = db
        self.trip = trip
        self.title(f"Roster & Costs — {trip['name']}")
        self.resizable(True, True)
        self.grab_set()

        ttk.Label(self, text=f"👥  Roster & Costs — {trip['name']}",
                  font=("Segoe UI", 12, "bold"),
                  bootstyle=PRIMARY).pack(anchor=W, padx=16, pady=(12, 2))

        btns = ttk.Frame(self)
        btns.pack(fill=X, side=BOTTOM, padx=16, pady=10)
        ttk.Button(btns, text="Cancel", bootstyle=(SECONDARY, OUTLINE),
                   command=self.destroy).pack(side=RIGHT, padx=4)
        ttk.Button(btns, text="Save", bootstyle=SUCCESS,
                   command=self._save).pack(side=RIGHT, padx=4)

        body = ttk.Frame(self)
        body.pack(fill=BOTH, expand=True, padx=16, pady=4)

        # ── Left: attendance ──
        left = ttk.Frame(body)
        left.pack(side=LEFT, fill=BOTH, expand=True, padx=(0, 14))
        ttk.Label(left, text="Attending (untick anyone who is NOT going)",
                  font=("Segoe UI", 9, "bold")).pack(anchor=W)
        wrap = ttk.Frame(left)
        wrap.pack(fill=BOTH, expand=True)
        canvas = tk.Canvas(wrap, highlightthickness=0, width=260, height=340)
        sb = ttk.Scrollbar(wrap, orient=VERTICAL, command=canvas.yview)
        inner = ttk.Frame(canvas)
        inner.bind("<Configure>",
                   lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side=LEFT, fill=BOTH, expand=True)
        sb.pack(side=RIGHT, fill=Y)

        excluded = db.get_trip_exclusions(trip["id"])
        self._rows = []
        from concert_tools import _display_name
        for s in sorted(ft.eligible(students, trip),
                        key=lambda x: ((x.get("last_name") or "").lower(),
                                       (x.get("first_name") or "").lower())):
            v = tk.BooleanVar(value=s["id"] not in excluded)
            v.trace_add("write", lambda *a: self._recalc())
            ttk.Checkbutton(inner, text=_display_name(s), variable=v,
                            bootstyle=PRIMARY).pack(anchor=W)
            self._rows.append((s["id"], v))

        self._count_lbl = ttk.Label(left, text="", font=("Segoe UI", 10, "bold"))
        self._count_lbl.pack(anchor=W, pady=(6, 0))
        self._chap_lbl = ttk.Label(left, text="", font=("Segoe UI", 9),
                                   foreground=muted_fg())
        self._chap_lbl.pack(anchor=W)

        # ── Right: costs ──
        right = ttk.Frame(body)
        right.pack(side=LEFT, fill=Y)
        ttk.Label(right, text="Trip expenses (one-time totals the school pays)",
                  font=("Segoe UI", 9, "bold")).pack(anchor=W)
        self._cost_vars = {}
        for label, key, hint in [
                ("Entry / festival registration ($)", "entry_fee",
                 "Per ensemble entered — e.g. $350 for BHS Jazz Festival."),
                ("Bus / transportation ($)", "transport_cost", ""),
                ("Food ($)", "food_cost", ""),
                ("Substitute ($)", "sub_cost",
                 "BSD: $212/4 hrs · $266/5 hrs · $354/full day"),
                ("Other ($)", "other_cost", "")]:
            ttk.Label(right, text=label, font=("Segoe UI", 9)
                      ).pack(anchor=W, pady=(6, 0))
            if hint:
                ttk.Label(right, text=hint, font=("Segoe UI", 8),
                          foreground=muted_fg()).pack(anchor=W)
            v = tk.StringVar(value=str(trip.get(key) or "") or "0")
            v.trace_add("write", lambda *a: self._recalc())
            self._cost_vars[key] = v
            ttk.Entry(right, textvariable=v, width=12).pack(anchor=W)

        ttk.Label(right, text="Funding", font=("Segoe UI", 9, "bold")
                  ).pack(anchor=W, pady=(10, 0))
        self._funding = tk.StringVar(value=trip.get("funding")
                                     or ft.FUNDING_CURRICULAR)
        ttk.Radiobutton(right, text="Building / department (curricular)",
                        value=ft.FUNDING_CURRICULAR, variable=self._funding,
                        bootstyle=PRIMARY).pack(anchor=W)
        ttk.Radiobutton(right, text="ASB / boosters (extracurricular)",
                        value=ft.FUNDING_EXTRACURRICULAR,
                        variable=self._funding,
                        bootstyle=PRIMARY).pack(anchor=W)
        self._covered = tk.BooleanVar(value=bool(trip.get("covered")))
        self._covered.trace_add("write", lambda *a: self._recalc())
        ttk.Checkbutton(right, text="Costs fully covered — no student charge",
                        variable=self._covered, bootstyle=SUCCESS
                        ).pack(anchor=W, pady=(6, 0))

        self._total_lbl = ttk.Label(right, text="",
                                    font=("Segoe UI", 11, "bold"))
        self._total_lbl.pack(anchor=W, pady=(12, 0))
        self._per_lbl = ttk.Label(right, text="",
                                  font=("Segoe UI", 11, "bold"),
                                  bootstyle=SUCCESS)
        self._per_lbl.pack(anchor=W)

        self._recalc()
        fit_window(self, 640, 580)

    def _going(self):
        return sum(1 for _, v in self._rows if v.get())

    def _trip_snapshot(self):
        snap = dict(self.trip)
        for key, v in self._cost_vars.items():
            snap[key] = v.get()
        snap["covered"] = 1 if self._covered.get() else 0
        return snap

    def _recalc(self):
        n = self._going()
        self._count_lbl.config(text=f"{n} student(s) attending")
        need = ft.chaperones_needed(n)
        self._chap_lbl.config(
            text=f"≈ {need} adult chaperone(s) needed (1 per "
                 f"{ft.STUDENTS_PER_CHAPERONE}, plus you)")
        costs = ft.trip_costs(self._trip_snapshot(), n)
        self._total_lbl.config(
            text=f"Total expenses:  ${costs['total']:,.2f}")
        if self._covered.get():
            self._per_lbl.config(text="Charge per student:  $0.00 (covered)")
        else:
            self._per_lbl.config(
                text=f"Charge per student:  ${costs['per_student']:,.2f}"
                     f"   (→ ${costs['income']:,.2f} income from {n})")

    def _save(self):
        data = {}
        for key, v in self._cost_vars.items():
            try:
                data[key] = float(v.get().replace("$", "").replace(",", "") or 0)
            except ValueError:
                Messagebox.show_warning("Costs must be numbers.",
                                        title="Check Costs", parent=self)
                return
        data["funding"] = self._funding.get()
        data["covered"] = 1 if self._covered.get() else 0
        self.db.update_field_trip(self.trip["id"], data)
        excluded = [sid for sid, v in self._rows if not v.get()]
        self.db.set_trip_exclusions(self.trip["id"], excluded)
        self.destroy()


# ═══════════════════════════════════════════ Chaperones ══════════════════════

class _ChaperonesDialog(ttk.Toplevel):
    def __init__(self, parent, db, trip, students, going, attending=None):
        super().__init__(parent.winfo_toplevel())
        self.db = db
        self.trip = trip
        self.students = students
        self.attending = attending or []
        self.title(f"Chaperones — {trip['name']}")
        self.resizable(True, True)
        self.grab_set()

        need = ft.chaperones_needed(going)
        ttk.Label(self, text=f"🧑‍🤝‍🧑  Chaperones — {trip['name']}",
                  font=("Segoe UI", 12, "bold"),
                  bootstyle=PRIMARY).pack(anchor=W, padx=16, pady=(12, 2))
        self._need_lbl = ttk.Label(self, font=("Segoe UI", 9),
                                   foreground=muted_fg())
        self._need_lbl.pack(anchor=W, padx=16)
        self._need = need
        self._going = going

        frame = ttk.Frame(self)
        frame.pack(fill=BOTH, expand=True, padx=16, pady=6)
        cols = ("name", "phone", "email", "cleared")
        self.tree = ttk.Treeview(frame, columns=cols, show="headings",
                                 selectmode="browse", height=8,
                                 bootstyle=PRIMARY)
        heads = {"name": "Name", "phone": "Phone", "email": "Email",
                 "cleared": "District-cleared?"}
        widths = {"name": 160, "phone": 110, "email": 200, "cleared": 110}
        for c in cols:
            self.tree.heading(c, text=heads[c], anchor=W)
            self.tree.column(c, width=widths[c], anchor=W,
                             stretch=c == "email")
        self.tree.pack(fill=BOTH, expand=True)
        self.tree.bind("<Button-1>", self._on_click, add="+")

        add = tk.LabelFrame(self, text=" Add a parent chaperone ",
                            font=("Segoe UI", 9, "bold"), padx=10, pady=6)
        add.pack(fill=X, padx=16, pady=(4, 4))
        row = ttk.Frame(add)
        row.pack(fill=X)
        self._add_vars = {}
        for label, key, w in [("Name", "name", 22), ("Phone", "phone", 14),
                              ("Email", "email", 24)]:
            col = ttk.Frame(row)
            col.pack(side=LEFT, padx=(0, 8))
            ttk.Label(col, text=label, font=("Segoe UI", 8, "bold")).pack(anchor=W)
            v = tk.StringVar()
            self._add_vars[key] = v
            e = ttk.Entry(col, textvariable=v, width=w)
            e.pack(anchor=W)
            if key == "name":
                e.bind("<FocusOut>", lambda ev: self._autofill())
        self._add_cleared = tk.BooleanVar(value=False)
        ttk.Checkbutton(row, text="District-cleared\nvolunteer",
                        variable=self._add_cleared, bootstyle=SUCCESS
                        ).pack(side=LEFT, padx=(4, 0))
        arow = ttk.Frame(add)
        arow.pack(fill=X, pady=(6, 0))
        self._match_lbl = ttk.Label(arow, text="Phone/email auto-fill from the "
                                               "student database as you type "
                                               "a parent's name.",
                                    font=("Segoe UI", 8), foreground=muted_fg())
        self._match_lbl.pack(side=LEFT)
        ttk.Button(arow, text="➕ Add Chaperone", bootstyle=SUCCESS,
                   command=self._add).pack(side=RIGHT)

        brow = ttk.Frame(self)
        brow.pack(fill=X, padx=16, pady=(2, 12))
        ttk.Button(brow, text="Close", bootstyle=(SECONDARY, OUTLINE),
                   command=self.destroy).pack(side=RIGHT, padx=4)
        ttk.Button(brow, text="🗑 Remove Selected", bootstyle=(DANGER, OUTLINE),
                   command=self._remove).pack(side=RIGHT, padx=4)
        ttk.Button(brow, text="⟳ Fill Missing Contacts",
                   bootstyle=(PRIMARY, OUTLINE),
                   command=self._fill_missing).pack(side=LEFT, padx=4)

        self._reload()
        fit_window(self, 680, 480)

    def _reload(self):
        self.tree.delete(*self.tree.get_children())
        chaps = self.db.get_trip_chaperones(self.trip["id"])
        for c in chaps:
            self.tree.insert("", "end", iid=str(c["id"]), values=(
                c["name"], c["phone"] or "—", c["email"] or "—",
                "✓ cleared" if c["cleared"] else "☐ not yet"))
        have = len(chaps)
        status = "✓ covered" if have >= self._need else f"need {self._need - have} more"
        self._need_lbl.config(
            text=f"{self._going} students → ≈ {self._need} chaperone(s) "
                 f"needed (1 per {ft.STUDENTS_PER_CHAPERONE}, plus you). "
                 f"Signed up: {have} — {status}.")

    def _autofill(self):
        name = self._add_vars["name"].get()
        hit = ft.find_parent_contact(self.students, name,
                                     prefer=self.attending)
        if not hit:
            return
        if not self._add_vars["phone"].get().strip():
            self._add_vars["phone"].set(hit["phone"])
        if not self._add_vars["email"].get().strip():
            self._add_vars["email"].set(hit["email"])
        self._match_lbl.config(
            text=f"✓ Matched {hit['name']} (parent of {hit['student']}).",
            foreground="#1a7a1a")

    def _fill_missing(self):
        """Re-match every chaperone with a blank phone/email against the
        parents of registered students and fill in what's found."""
        filled = 0
        for c in self.db.get_trip_chaperones(self.trip["id"]):
            if (c["phone"] or "").strip() and (c["email"] or "").strip():
                continue
            hit = ft.find_parent_contact(self.students, c["name"],
                                         prefer=self.attending)
            if not hit:
                continue
            data = {}
            if not (c["phone"] or "").strip() and hit["phone"]:
                data["phone"] = hit["phone"]
            if not (c["email"] or "").strip() and hit["email"]:
                data["email"] = hit["email"]
            if data:
                self.db.update_trip_chaperone(c["id"], data)
                filled += 1
        self._reload()
        self._match_lbl.config(
            text=(f"✓ Filled contact info for {filled} chaperone(s)."
                  if filled else "No matches found — check the parent names "
                                 "in the student records."),
            foreground="#1a7a1a" if filled else "#B45309")

    def _add(self):
        name = self._add_vars["name"].get().strip()
        if not name:
            return
        self._autofill()
        self.db.add_trip_chaperone(
            self.trip["id"], name,
            phone=self._add_vars["phone"].get().strip(),
            email=self._add_vars["email"].get().strip(),
            cleared=self._add_cleared.get())
        for v in self._add_vars.values():
            v.set("")
        self._add_cleared.set(False)
        self._match_lbl.config(text="Added.", foreground="#1a7a1a")
        self._reload()

    def _remove(self):
        sel = self.tree.selection()
        if not sel:
            return
        self.db.delete_trip_chaperone(int(sel[0]))
        self._reload()

    def _on_click(self, event):
        """Click the cleared column to toggle it."""
        if self.tree.identify("region", event.x, event.y) != "cell":
            return
        if self.tree.identify_column(event.x) != "#4":
            return
        iid = self.tree.identify_row(event.y)
        if not iid:
            return
        c = next((x for x in self.db.get_trip_chaperones(self.trip["id"])
                  if str(x["id"]) == iid), None)
        if c:
            self.db.update_trip_chaperone(int(iid),
                                          {"cleared": 0 if c["cleared"] else 1})
            self._reload()


# ═══════════════════════════════════════════ Reminders ═══════════════════════

class _RemindersDialog(ttk.Toplevel):
    """Families / chaperones / other-teachers reminders at 2 weeks & 1 week."""

    def __init__(self, parent, db, trip, students, attending, teacher):
        super().__init__(parent.winfo_toplevel())
        self.db = db
        self.trip = trip
        self.attending = attending
        self.school, self.director = teacher
        self.title(f"Reminders — {trip['name']}")
        self.resizable(True, True)
        self.grab_set()

        ttk.Label(self, text=f"✉  Reminders — {trip['name']}",
                  font=("Segoe UI", 12, "bold"),
                  bootstyle=PRIMARY).pack(anchor=W, padx=16, pady=(12, 2))

        self._family_addrs = ft.family_addresses(attending)
        self._chap_addrs = [c["email"] for c in
                            db.get_trip_chaperones(trip["id"])
                            if (c["email"] or "").strip()]
        costs = ft.trip_costs(trip, len(attending))
        self._per_student = costs["per_student"]

        sent = {r["stage"]: r["sent_date"]
                for r in db.get_trip_reminders(trip["id"]) if r["sent_date"]}
        today = datetime.today().date()
        schedule = ft.trip_schedule(trip.get("depart_date"))

        sections = [
            ("families", "Students & parents",
             f"{len(self._family_addrs)} parent address(es) for "
             f"{len(attending)} attending student(s)"),
            ("chaperones", "Parent chaperones",
             f"{len(self._chap_addrs)} chaperone email(s) on file"),
            ("teachers", "Teachers / admin / attendance",
             "heads-up with the student list (ID + grade) and missed-work note"),
        ]
        for audience, title, sub in sections:
            box = tk.LabelFrame(self, text=f" {title} ",
                                font=("Segoe UI", 9, "bold"), padx=10, pady=4)
            box.pack(fill=X, padx=16, pady=4)
            ttk.Label(box, text=sub, font=("Segoe UI", 8),
                      foreground=muted_fg()).pack(anchor=W)
            for label, due in schedule:
                key = ft.stage_key(audience, label)
                row = ttk.Frame(box)
                row.pack(fill=X, pady=1)
                if key in sent:
                    status, color = f"{label}: ✓ sent {sent[key]}", "#1a7a1a"
                elif due and today >= due:
                    status, color = f"{label}: ⚠ due (was {due})", "#B45309"
                elif due:
                    status, color = f"{label}: send on {due}", "#555555"
                else:
                    status, color = f"{label}: set a departure date", "#888888"
                ttk.Label(row, text=status, font=("Segoe UI", 9),
                          foreground=color, width=34, anchor=W).pack(side=LEFT)
                if audience != "teachers":
                    ttk.Button(row, text="📋 Addresses",
                               bootstyle=(SECONDARY, OUTLINE),
                               command=lambda a=audience: self._copy_addrs(a)
                               ).pack(side=LEFT, padx=2)
                ttk.Button(row, text="✉ Email Template",
                           bootstyle=(PRIMARY, OUTLINE),
                           command=lambda a=audience, l=label:
                           self._show_email(a, l)).pack(side=LEFT, padx=2)
                if key in sent:
                    ttk.Button(row, text="Undo",
                               bootstyle=(SECONDARY, OUTLINE, LINK),
                               command=lambda k=key: self._unmark(k)
                               ).pack(side=LEFT, padx=2)
                else:
                    ttk.Button(row, text="✓ Mark Sent",
                               bootstyle=(SUCCESS, OUTLINE),
                               command=lambda k=key: self._mark(k)
                               ).pack(side=LEFT, padx=2)

        self._status = ttk.Label(self, text="", font=("Segoe UI", 9),
                                 foreground="#1a7a1a")
        self._status.pack(anchor=W, padx=18, pady=(2, 0))
        ttk.Button(self, text="Close", bootstyle=(SECONDARY, OUTLINE),
                   command=self.destroy).pack(pady=(4, 12))
        fit_window(self, 660, 620)

    def _flash(self, msg):
        self._status.config(text=msg)
        self.after(2200, lambda: self._status.config(text=""))

    def _copy_addrs(self, audience):
        addrs = (self._family_addrs if audience == "families"
                 else self._chap_addrs)
        if not addrs:
            Messagebox.show_info("No email addresses found.",
                                 title="No Addresses", parent=self)
            return
        _copy(self, "; ".join(addrs))
        self._flash(f"✓ {len(addrs)} address(es) copied — paste into BCC.")

    def _email_for(self, audience, label):
        """(subject, body) — a saved per-trip template wins over the
        auto-generated body (so a rich hand-written chaperone email is
        reused for both stages and can carry to next year's trip)."""
        if audience == "families":
            subject, body = ft.family_email(self.trip, self._per_student,
                                            label, self.director, self.school)
        elif audience == "chaperones":
            subject, body = ft.chaperone_email(self.trip, label,
                                               self.director, self.school)
        else:
            subject, body = ft.teacher_email(self.trip, self.attending, label,
                                             self.director)
        saved = (self.trip.get(f"email_{audience}") or "").strip()
        if saved:
            body = saved
        return subject, body

    def _persist_email(self, audience, body):
        try:
            self.db.update_field_trip(self.trip["id"],
                                      {f"email_{audience}": body})
            self.trip[f"email_{audience}"] = body
        except Exception:
            pass

    def _show_email(self, audience, label):
        subject, body = self._email_for(audience, label)
        win = ttk.Toplevel(self)
        win.title(f"Email Template — {audience}, {label}")
        win.grab_set()
        ttk.Label(win, text=f"✉  {audience.title()} — {label} reminder",
                  font=("Segoe UI", 12, "bold"),
                  bootstyle=PRIMARY).pack(anchor=W, padx=16, pady=(12, 2))
        ttk.Label(win, text="Copying saves your edits as this trip's email — "
                            "reused for both reminder stages, and carried "
                            "into next year via “Copy From Previous”.",
                  font=("Segoe UI", 8), foreground=muted_fg()).pack(anchor=W, padx=16)
        srow = ttk.Frame(win)
        srow.pack(fill=X, padx=16, pady=(6, 2))
        ttk.Label(srow, text="Subject:", font=("Segoe UI", 9, "bold")
                  ).pack(side=LEFT)
        subj_var = tk.StringVar(value=subject)
        ttk.Entry(srow, textvariable=subj_var).pack(side=LEFT, fill=X,
                                                    expand=True, padx=(8, 0))
        box = tk.Text(win, font=("Calibri", 11), width=74, height=18,
                      relief="solid", bd=1, wrap=WORD)
        box.insert("1.0", body)
        box.pack(fill=BOTH, expand=True, padx=16, pady=6)

        status = ttk.Label(win, text="", font=("Segoe UI", 9),
                           foreground="#1a7a1a")
        status.pack(anchor=W, padx=18)

        def flash(msg):
            status.config(text=msg)
            win.after(2000, lambda: status.config(text=""))

        def copy_all():
            text = box.get("1.0", "end").strip()
            self._persist_email(audience, text)
            _copy(win, f"Subject: {subj_var.get().strip()}\n\n{text}")
            flash("✓ Subject + body copied (and saved with this trip).")

        def copy_body():
            text = box.get("1.0", "end").strip()
            self._persist_email(audience, text)
            _copy(win, text)
            flash("✓ Body copied (and saved with this trip).")

        def reset_auto():
            self._persist_email(audience, "")
            _, fresh = self._email_for(audience, label)
            box.delete("1.0", "end")
            box.insert("1.0", fresh)
            flash("↺ Back to the auto-generated email.")

        b = ttk.Frame(win)
        b.pack(fill=X, padx=16, pady=(4, 12))
        ttk.Button(b, text="Close", bootstyle=(SECONDARY, OUTLINE),
                   command=win.destroy).pack(side=RIGHT, padx=4)
        ttk.Button(b, text="📋 Copy Subject + Body", bootstyle=PRIMARY,
                   command=copy_all).pack(side=RIGHT, padx=4)
        ttk.Button(b, text="📋 Copy Body Only", bootstyle=(PRIMARY, OUTLINE),
                   command=copy_body).pack(side=RIGHT, padx=4)
        ttk.Button(b, text="↺ Reset to Auto", bootstyle=(SECONDARY, OUTLINE),
                   command=reset_auto).pack(side=LEFT, padx=4)
        fit_window(win, 640, 560)

    def _mark(self, key):
        self.db.mark_trip_reminder(self.trip["id"], key,
                                   datetime.today().strftime("%Y-%m-%d"))
        self.destroy()

    def _unmark(self, key):
        self.db.clear_trip_reminder(self.trip["id"], key)
        self.destroy()
