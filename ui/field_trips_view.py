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

from ui.theme import fs, muted_fg, subtle_fg, fit_window, scroll_body, px
import concert_tools as ct
import field_trip_tools as ft

# Amber is "coming up, mind it"; red is "you have missed it".  A missed
# district deadline can cost the trip, so it does not share a colour with a
# reminder that is merely due soon.
_OVERDUE = "#D00000"
_SOON = "#B45309"


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

    def _export_roster(self):
        from ui.roster_export_view import open_roster_export
        open_roster_export(self, self.main_db, self.base_dir, self._student_year(),
                           context="For a field trip: choose the class(es) going.")

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
        inner._canvas = canvas          # so refresh can put the view back
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
        from ui.settings_dialog import school_name
        school = school_name(self.base_dir)
        # First + last only ("Meagan Mangum") — programs and emails never get
        # the profile folder's middle initial.  Settings can override.
        from ui.names import director_name
        return school, director_name(self.base_dir)

    def _program_type(self):
        from ui.settings_dialog import load_settings
        return (load_settings(self.base_dir).get("teacher") or {}).get(
            "program_type", "band")

    def _students(self):
        """Everyone, both levels.

        get_students_for_email defaults to SECONDARY, which is right for a
        general contact list -- a 5th grader must never turn up on a marching
        band email.  Here the guard is the wrong one: what puts a child on this
        list is being in one of the GROUPS chosen for the event, and an
        elementary group carries its school's name ("Jing Mei Elementary
        School: Section 1"), so it can never match "Advanced Band". Filtering
        by level as well simply hid every 5th grader from a teacher who has
        both -- an elementary event showed nobody attending at all.
        """
        return [dict(r) for r in self.main_db.get_students_for_email(
            school_year=self._student_year(), level=None)]

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
        # Every dialog on this tab calls back here as it closes, and by then
        # the tab itself may be gone: closing Teacher Tools, or switching the
        # year, destroys and rebuilds the whole notebook while a dialog is
        # still open.  Redrawing a tab that no longer exists is a crash, so
        # check before touching anything.
        if not (self.winfo_exists() and self._cards.winfo_exists()):
            return
        # Where the list was scrolled to, so editing the fourth trip does not
        # bounce the window back to the first.  Everything on this tab calls
        # refresh() when it closes, so without this every single edit throws
        # the reader back to the top.
        try:
            was_at = self._cards._canvas.yview()[0]
        except Exception:
            was_at = None

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

        if was_at is not None:
            # After the new cards have been laid out, not before: the scroll
            # region does not exist yet at this point.
            def _restore(pos=was_at):
                try:
                    self._cards._canvas.yview_moveto(pos)
                except Exception:
                    pass
            self.after_idle(_restore)

        # Completed: this year's finished trips, then previous years
        def done_row(label, opener):
            row = ttk.Frame(self._done_rows)
            row.pack(fill=X, padx=4, pady=1)
            ttk.Button(row, text=label, bootstyle=(SECONDARY, OUTLINE, LINK),
                       command=opener).pack(side=LEFT)

        year = self._year()
        for t in completed:
            dest = f", {t['destination']}" if t.get("destination") else ""
            # This year's, so still editable: a trip lands here by mistake
            # whenever the year in the date is a keystroke wrong, and a
            # read-only dead end means retyping the whole thing.
            done_row(f"✔ {t.get('depart_date')}  ·  {t.get('name')}{dest}",
                     lambda tr=t: _PastTripDialog(self, year, dict(tr), self.db,
                                                  editable=True))
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

    def _collapsed(self, trip_id):
        return trip_id in getattr(self, "_folded", set())

    def _toggle_collapsed(self, trip_id):
        """Fold a trip away while working on another one.

        Deliberately not saved: it is a way of clearing the desk for ten
        minutes, not a property of the trip.  Four trips on screen is enough
        to have to scroll past the three that are not today's problem.
        """
        folded = getattr(self, "_folded", None)
        if folded is None:
            folded = self._folded = set()
        folded.symmetric_difference_update({trip_id})
        self.refresh()

    def _trip_card(self, t, students):
        days = ct.days_until(t.get("depart_date"))
        when = ct.fmt_date(t.get("depart_date")) if t.get("depart_date") else "no date yet"
        title = f" {when}: {t['name']} "

        card = tk.LabelFrame(self._cards, text=title,
                             font=("Segoe UI", fs(11), "bold"),
                             padx=10, pady=6, bd=2, relief="groove")
        card.pack(fill=X, padx=6, pady=6)

        # ── Info line + countdown ──
        collapsed = self._collapsed(t["id"])
        top = ttk.Frame(card)
        top.pack(fill=X)
        fold = ttk.Label(top, text="\u25b8  " if collapsed else "\u25be  ",
                         font=("Segoe UI", fs(10), "bold"),
                         foreground=subtle_fg(), cursor="hand2")
        fold.pack(side=LEFT)
        fold.bind("<Button-1>", lambda e, i=t["id"]: self._toggle_collapsed(i))
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

        if collapsed:
            # Folded: the heading, the one-line summary and the countdown, and
            # nothing else.  Click the arrow to bring it back.
            return

        # ── Checklist: click any item to cycle its state ──
        sent = {r["stage"] for r in self.db.get_trip_reminders(t["id"])
                if r["sent_date"]}
        staff_emailed = any(s.startswith("teachers-") for s in sent)
        # Columns size to their text rather than sharing the card's width.
        # Stretched to a third each, "Sub request" sat marooned by itself at
        # the far right of a wide window with nothing between.
        grid = ttk.Frame(card)
        grid.pack(anchor=W, pady=(6, 2))

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

        elementary = self._trip_elementary(t)
        for i, (key, label) in enumerate(ft.checklist_for(t, elementary)):
            state = int(t.get(key) or 0)
            text, color = _item_label(state, label)
            lbl = ttk.Label(grid, text=text, font=("Segoe UI", fs(9)),
                            foreground=color, cursor="hand2")
            lbl.grid(row=i // 3, column=i % 3, sticky=W, padx=(0, 22), pady=1)
            lbl.bind("<Button-1>", lambda e, k=key: _cycle(k))
            lbl.bind("<Button-3>", lambda e, k=key: _set_na(k))
        # Derived item: staff emailed (auto from the teachers reminders)
        # Not clickable, because it is not a note you keep: it ticks itself the
        # moment the staff email is marked sent in Reminders.  "(auto)" said
        # that to nobody.
        text, color = _item_label(
            ft.CHECK_DONE if staff_emailed else ft.CHECK_TODO,
            "Staff emailed (from Reminders)")
        n_items = len(ft.checklist_for(t, elementary))
        ttk.Label(grid, text=text, font=("Segoe UI", fs(9)),
                  foreground=color).grid(row=n_items // 3, column=n_items % 3,
                                         sticky=W, padx=(0, 22), pady=1)

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

        # ── District deadlines ──
        # The reminders above are about telling people; these are the dates
        # the district works to, and for an overnight trip they land months
        # earlier and count back from the board meeting rather than the trip.
        import school_calendar as sc
        cal = sc.get_calendar(self._year())
        dl = ft.deadlines(t, cal)
        if dl:
            overdue = [x for x in dl if x["overdue"]]
            nxt = next((x for x in dl if not x["overdue"] and x["due"]), None)
            missing_anchor = [x for x in dl if not x["due"]]
            bold = False
            if overdue:
                text = ("District deadlines:  ⚠ PAST DUE — "
                        + ", ".join(x["label"] for x in overdue[:3]))
                color, bold = _OVERDUE, True
            elif nxt:
                left = nxt["school_weeks_left"]
                when = ct.fmt_date(nxt["due"].isoformat())
                text = f"Next district deadline:  {nxt['label']} by {when}"
                if left is not None and left >= 0:
                    text += f"  ({left:.0f} school week(s) away)"
                color = muted_fg()
            else:
                text = ""
                color = muted_fg()
            if missing_anchor:
                # Reported whatever else is on the line.  For an overnight trip
                # the approval deadlines are the ones that matter, and a nurse
                # deadline that HAPPENS to be computable was hiding the fact
                # that they could not be worked out at all.
                needs_board = any(x["anchor"] == "board" for x in missing_anchor)
                needs_trip = any(x["anchor"] == "trip" for x in missing_anchor)
                if needs_trip and needs_board:
                    what = "a date for the trip and the board meeting date"
                elif needs_board:
                    what = "the board meeting date"
                else:
                    what = "a date for the trip"
                note = f"set {what} to work the rest out"
                text = (f"{text}   ·   {note}" if text
                        else f"District deadlines: {note}.")
                if not overdue:
                    color = _SOON
            if text:
                lbl = ttk.Label(card, text=text,
                                font=("Segoe UI", fs(9),
                                      "bold") if bold else ("Segoe UI", fs(9)),
                                foreground=color, cursor="hand2")
                lbl.pack(anchor=W, pady=(0, 2))
                lbl.bind("<Button-1>", lambda e, tr=t: self._deadlines(tr))

        # ── Paper forms outstanding ──
        forms = ft.required_forms(t, elementary)
        if forms and not n:
            ttk.Label(card,
                      text="Paper forms:  "
                           + ", ".join(ft.FORM_SHORT[f] for f in forms)
                           + ", once there is a roster to chase.",
                      font=("Segoe UI", fs(9)),
                      foreground=muted_fg()).pack(anchor=W, pady=(0, 2))
        if forms and n:
            have = self.db.get_trip_forms(t["id"])
            missing = sum(1 for stu in attending for f in forms
                          if not have.get((stu["id"], f)))
            gate = [f for f in forms if f in ft.FORM_GATES_ATTENDANCE]
            cannot = sum(1 for stu in attending for f in gate
                         if not have.get((stu["id"], f)))
            if missing:
                msg = f"Paper forms:  {missing} still to come back"
                if cannot:
                    msg += (f"  ·  {cannot} student(s) cannot travel without "
                            f"{ft.FORM_SHORT[gate[0]]}")
                ttk.Label(card, text=msg, font=("Segoe UI", fs(9)),
                          foreground="#B45309").pack(anchor=W, pady=(0, 2))
            else:
                ttk.Label(card, text="Paper forms:  all in ✓",
                          font=("Segoe UI", fs(9)),
                          foreground="#1a7a1a").pack(anchor=W, pady=(0, 2))

        # ── Actions ──
        btns = ttk.Frame(card)
        btns.pack(fill=X, pady=(2, 0))
        ttk.Button(btns, text="✏ Edit", bootstyle=(PRIMARY, OUTLINE),
                   command=lambda tr=t: self._edit_trip(tr)).pack(side=LEFT, padx=(0, 4))
        ttk.Button(btns, text="👥 Roster & Forms", bootstyle=(PRIMARY, OUTLINE),
                   command=lambda tr=t: self._roster_forms(tr)).pack(side=LEFT, padx=4)
        ttk.Button(btns, text="🧑‍🤝‍🧑 Chaperones", bootstyle=(INFO, OUTLINE),
                   command=lambda tr=t: self._chaperones(tr)).pack(side=LEFT, padx=4)
        ttk.Button(btns, text="✉ Reminders", bootstyle=(WARNING, OUTLINE),
                   command=lambda tr=t: self._reminders(tr)).pack(side=LEFT, padx=4)
        ttk.Button(btns, text="📄 Application", bootstyle=(SECONDARY, OUTLINE),
                   command=lambda tr=t: self._application(tr)
                   ).pack(side=LEFT, padx=4)
        ttk.Button(btns, text="🗑", bootstyle=(DANGER, OUTLINE), width=3,
                   command=lambda tr=t: self._delete_trip(tr)).pack(side=RIGHT)

    def _profile_is_elementary(self):
        """Only used when a trip has no groups yet and nothing can be read off
        it.  On its own this is the wrong question -- see _trip_elementary."""
        try:
            from ui.settings_dialog import load_settings
            return ((load_settings(self.base_dir).get("teacher") or {})
                    .get("program_type") == "elementary")
        except Exception:
            return False

    def _trip_elementary(self, trip):
        """Whether THIS trip is a 5th grade trip, from the groups going on it.
        Decides whether permission is FinalForms or paper."""
        return ft.trip_is_elementary(self.main_db, trip,
                                     fallback=self._profile_is_elementary())

    def _deadlines(self, trip):
        _DeadlinesDialog(self, self.db, dict(trip), self._year())

    def _application(self, trip):
        """The district application as one fillable form.

        Everything that lands on the district's page lives here -- the answers
        AND the costs -- because they are one form and were two windows.  Fill
        it in, save it, print it from the same place.
        """
        try:
            fresh = self.db.get_field_trip(trip["id"])
            if fresh:
                trip = dict(fresh)
        except Exception:
            pass
        dlg = _ApplicationDialog(self, self.db, self.main_db, dict(trip),
                                 self.base_dir, self._students(),
                                 self._trip_elementary(dict(trip)))
        self.wait_window(dlg)
        self.refresh()

    def _print_application(self, trip):
        """The district application, with the planner's answers on it."""
        import field_trip_pdf as fp
        from tkinter import filedialog

        t = dict(self.db.get_field_trip(trip["id"]))
        attending = ft.roster(self._students(), t,
                              self.db.get_trip_exclusions(t["id"]))
        try:
            from ui.settings_dialog import load_settings, school_name
            teacher = (load_settings(self.base_dir).get("teacher") or {})
            who = (teacher.get("display_name") or "").strip()
            where = school_name(self.base_dir) or ""
        except Exception:
            who = where = ""

        path = filedialog.asksaveasfilename(
            parent=self.winfo_toplevel(), defaultextension=".pdf",
            initialfile=fp.suggested_filename(t),
            title="Save the field trip application",
            filetypes=[("PDF", "*.pdf")])
        if not path:
            return
        try:
            fp.build_application(
                t, path, students=len(attending),
                chaperones=len(self.db.get_trip_chaperones(t["id"])),
                teacher_name=who, school_name=where)
        except Exception as e:
            Messagebox.show_error(f"Could not write the application.\n\n{e}",
                                  title="Not saved",
                                  parent=self.winfo_toplevel())
            return
        try:
            os.startfile(path)
        except Exception:
            Messagebox.show_info(f"Saved to:\n{path}", title="Saved",
                                 parent=self.winfo_toplevel())

    # ── CRUD ─────────────────────────────────────────────────────────────────

    def _new_trip(self, template=None):
        seed = dict(template) if template else None
        dlg = _TripDialog(self, seed=seed, program_type=self._program_type(),
                          main_db=self.main_db, student_year=self._student_year(),
                          elementary=self._profile_is_elementary())
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
        # Re-read from the database rather than trusting the dict the card was
        # built from.  A card captures its trip when it is drawn, and a dialog
        # holds its own snapshot; either can be a version or two behind by the
        # time Edit is clicked, and a stale seed shows blank fields that were
        # saved perfectly well -- indistinguishable from having lost them.
        try:
            fresh = self.db.get_field_trip(t["id"])
            if fresh:
                t = dict(fresh)
        except Exception:
            pass
        dlg = _TripDialog(self, seed=dict(t),
                          program_type=self._program_type(), editing=True,
                          main_db=self.main_db, student_year=self._student_year(),
                          elementary=self._trip_elementary(dict(t)))
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

    def _roster_forms(self, t):
        try:
            fresh = self.db.get_field_trip(t["id"])
            if fresh:
                t = dict(fresh)
        except Exception:
            pass
        dlg = _RosterFormsDialog(self, self.db, dict(t), self._students(),
                                 self._trip_elementary(dict(t)))
        self.wait_window(dlg)
        self.refresh()

    def _chaperones(self, t):
        attending = self._attending(t)
        dlg = _ChaperonesDialog(self, self.db, dict(t), self._students(),
                                len(attending), attending=attending,
                                base_dir=self.base_dir)
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

    def __init__(self, parent_view, year, trip, pdb, editable=False):
        super().__init__(parent_view.winfo_toplevel())
        self.view = parent_view
        self.trip = trip
        self._pdb = pdb
        self._editable = editable
        self.title(f"{trip.get('name')} — {year}"
                   + ("" if editable else " (read-only)"))
        self.resizable(True, True)
        self.grab_set()

        ttk.Label(self, text=f"🕰  {trip.get('name')} — {year}",
                  font=("Segoe UI", 12, "bold"),
                  bootstyle=PRIMARY).pack(anchor=W, padx=16, pady=(12, 0))
        ttk.Label(
            self,
            text=("This trip's date has already gone by, so it sits with the "
                  "completed trips. Edit it if the date was wrong — a school "
                  "year runs across two calendar years, so it is an easy one "
                  "to mistype."
                  if editable else
                  "Read-only — from a previous school year."),
            font=("Segoe UI", 8), foreground=muted_fg(), wraplength=560,
            justify=LEFT).pack(anchor=W, padx=16)

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
        if editable:
            ttk.Button(btns, text="✏ Edit This Trip", bootstyle=PRIMARY,
                       command=self._edit).pack(side=LEFT, padx=4)
        fit_window(self, 620, 600)

    def _edit(self):
        """Open the ordinary edit dialog on a trip that has slipped into the
        completed list.  Without this, a trip whose year was mistyped is a dead
        end: everything the teacher wrote is there and unreachable."""
        self.destroy()
        try:
            self.view._edit_trip(self.trip)
        except Exception:
            pass

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
    def __init__(self, parent, seed=None, program_type="band", editing=False,
                 main_db=None, student_year=None, elementary=False):
        super().__init__(parent.winfo_toplevel())
        self.result = None
        self._main_db = main_db
        self._profile_elementary = elementary
        self._elementary = elementary
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

        body = scroll_body(self, padx=16, pady=4)
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

        # ── Which procedure ──
        # BSD runs two, and they are not variations of one thing: different
        # forms, a different approval path, and lead times that differ by a
        # factor of four.  Asked first because everything below depends on it.
        ttk.Label(body, text="What kind of trip", font=("Segoe UI", 9, "bold")
                  ).pack(anchor=W, pady=(10, 0))
        self._trip_type = tk.StringVar(
            value=ft.trip_type(seed) if seed else ft.TRIP_DAY)
        for value, label, hint in ft.TRIP_TYPES:
            ttk.Radiobutton(body, text=label, value=value,
                            variable=self._trip_type, bootstyle=PRIMARY,
                            command=self._type_changed).pack(anchor=W)
            ttk.Label(body, text="      " + hint, font=("Segoe UI", 8),
                      foreground=muted_fg()).pack(anchor=W)
        ttk.Label(body, text="      International trips are not covered here; "
                             "work from the district packet for those.",
                  font=("Segoe UI", 8), foreground=muted_fg()).pack(anchor=W)

        # Roka guesses this from the groups attending, and the guess is right
        # nearly always -- but it has nothing to go on before the roster is
        # imported, and it is what decides whether permission is FinalForms or
        # paper.  So it is a box, pre-ticked from the guess, and the teacher's
        # answer is the one that counts.
        self._elem_var = tk.BooleanVar(value=bool(elementary))
        self._elem_touched = bool(seed.get("elementary") is not None
                                  and str(seed.get("elementary")).strip() != "")
        ttk.Checkbutton(
            body, text="This is an elementary school trip",
            variable=self._elem_var, bootstyle=PRIMARY,
            command=self._elem_ticked).pack(anchor=W, pady=(8, 0))
        ttk.Label(body, text="      Elementary trips collect paper permission "
                             "forms; middle and high school day trips are on "
                             "FinalForms.",
                  font=("Segoe UI", 8), foreground=muted_fg(),
                  wraplength=560, justify=LEFT).pack(anchor=W)

        # Groups
        ttk.Label(body, text="Class or group(s) attending",
                  font=("Segoe UI", 9, "bold")).pack(anchor=W, pady=(8, 2))
        # Offer the classes the roster really uses: this list is matched back
        # against student records to build the attending roster.
        from ui.ensembles import selectable_ensembles
        # A class with no students can't attend anything, so only real
        # ones are offered; anything unusual goes in "Other groups".
        std = selectable_ensembles(main_db, student_year, program_type)
        chosen = set(g.strip() for g in
                     (seed.get("groups_list") or "").split(",") if g.strip())
        self._grp_vars = {}
        grid = ttk.Frame(body)
        grid.pack(anchor=W)
        from ui.ensembles import class_display_map
        import class_registry as cr
        dmap = class_display_map(std)
        for i, g in enumerate(std):
            # Tick by identity so an old trip saved as "Entry Band" still
            # shows checked when the picker offers "MS Band (Entry)".
            bv = tk.BooleanVar(value=any(cr.same_class(g, c) for c in chosen))
            self._grp_vars[g] = bv
            ttk.Checkbutton(grid, text=dmap[g], variable=bv, bootstyle=PRIMARY,
                            command=self._type_changed
                            ).grid(row=i // 3, column=i % 3, sticky=W,
                                   padx=(0, 14), pady=2)
        extras = [g for g in chosen
                  if not any(cr.same_class(g, e) for e in std)]
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

        # A blackout date is cheap to fix now and expensive to fix after the
        # packet is written, so it is checked as the date is typed.
        self._blackout = ttk.Label(body, text="", font=("Segoe UI", 8),
                                   foreground="#B45309", wraplength=560,
                                   justify=LEFT)
        self._blackout.pack(anchor=W, pady=(4, 0))
        self._vars["depart_date"].trace_add("write",
                                            lambda *a: self._date_changed())

        # Overnight approval counts back from the school BOARD MEETING, not
        # from the trip, so without this date no deadline can be worked out.
        self._board_box = ttk.Frame(body)
        ttk.Label(self._board_box, text="School board meeting date",
                  font=("Segoe UI", 9, "bold")).pack(anchor=W, pady=(8, 0))
        ttk.Label(self._board_box,
                  text="The meeting your trip needs to be approved at. Every "
                       "approval deadline counts back from this, not from the "
                       "trip.",
                  font=("Segoe UI", 8), foreground=muted_fg(),
                  wraplength=540, justify=LEFT).pack(anchor=W)
        bv = tk.StringVar(value=str(seed.get("board_date") or ""))
        self._vars["board_date"] = bv
        self._board_combo = ttk.Combobox(self._board_box, textvariable=bv,
                                         width=30)
        self._board_combo.pack(anchor=W)
        self._board_combo.bind("<<ComboboxSelected>>",
                               lambda e: self._board_picked())
        bv.trace_add("write", lambda *a: self._board_note_update())
        self._board_note = ttk.Label(self._board_box, text="",
                                     font=("Segoe UI", 8), wraplength=540,
                                     justify=LEFT)
        self._board_note.pack(anchor=W, pady=(2, 0))

        row2 = ttk.Frame(body)
        row2.pack(fill=X, anchor=W)
        c5 = ttk.Frame(row2); c5.pack(side=LEFT, padx=(0, 16))
        c6 = ttk.Frame(row2); c6.pack(side=LEFT)
        ttk.Label(c5, text="Method of travel", font=("Segoe UI", 9, "bold")
                  ).pack(anchor=W, pady=(8, 0))
        tv = tk.StringVar(value=str(seed.get("travel_method") or ""))
        self._vars["travel_method"] = tv
        tv.trace_add("write", lambda *a: self._type_changed())
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
                             "school = no sub, free event = no payment).",
                  font=("Segoe UI", 8), foreground=muted_fg(),
                  wraplength=560, justify=LEFT).pack(anchor=W)
        self._forms_note = ttk.Label(body, text="", font=("Segoe UI", 8),
                                     foreground=muted_fg(), wraplength=560,
                                     justify=LEFT)
        self._forms_note.pack(anchor=W)
        self._extras_note = ttk.Label(body, text="", font=("Segoe UI", 8),
                                      foreground=muted_fg(), wraplength=560,
                                      justify=LEFT)
        self._extras_note.pack(anchor=W)
        self._check_states = {}
        cgrid = ttk.Frame(body)
        cgrid.pack(anchor=W, pady=(4, 0), fill=X)
        cgrid.columnconfigure(0, weight=1)
        cgrid.columnconfigure(1, weight=1)

        def _make_item(idx, key, label):
            # setdefault, not assignment: the checklist is rebuilt whenever the
            # trip type changes, and re-reading the seed each time threw away
            # everything ticked since the window opened.
            self._check_states.setdefault(key, int(seed.get(key) or 0))
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

        self._cgrid = cgrid
        self._make_item = _make_item
        for key, _label in ft.CHECKLIST_ITEMS:      # every state, so a hidden
            self._check_states.setdefault(key, int(seed.get(key) or 0))

        # The district application's own questions are NOT here.  They and the
        # trip costs go on the same sheet of paper, and having them in two
        # windows was a filing decision rather than a real one -- they live
        # together behind the Application button now.  This window is the trip:
        # what it is, when, who is going, and what still has to be arranged.
        self._overnight_box = ttk.Frame(body)   # nothing in it; kept so
        self._long_vars = {}                    # _type_changed stays simple

        ttk.Label(body, text="Notes", font=("Segoe UI", 9, "bold")
                  ).pack(anchor=W, pady=(8, 0))
        self._notes = tk.Text(body, height=3, width=60, font=("Segoe UI", 9),
                              relief="solid", bd=1, wrap=WORD)
        self._notes.insert("1.0", str(seed.get("notes") or ""))
        self._notes.pack(anchor=W, fill=X)

        self._type_changed()
        self._check_blackout()
        fit_window(self, 660, 700)

    def _type_changed(self):
        """Show only what this procedure asks for.  An overnight trip needs a
        board meeting date, four times and an itinerary; a day trip does not,
        and showing them anyway is five more fields to skip past."""
        # Groups drive the guess, and the guess drives the box -- until the
        # teacher touches the box, after which it is theirs.
        try:
            if not self._elem_touched:
                picked = [g for g, bv in self._grp_vars.items() if bv.get()]
                picked += [x.strip() for x in self._extra_grp.get().split(",")
                           if x.strip()]
                self._elem_var.set(ft.trip_is_elementary(
                    self._main_db, {"groups_list": ", ".join(picked)},
                    fallback=self._profile_elementary))
            self._elementary = bool(self._elem_var.get())
        except Exception:
            pass
        overnight = self._trip_type.get() == ft.TRIP_OVERNIGHT
        for box in (self._board_box, self._overnight_box):
            if overnight:
                box.pack(fill=X, anchor=W, pady=(4, 0))
            else:
                box.pack_forget()
        if overnight:
            self._board_combo["values"] = self._board_options()
            self._board_note_update()
        # Rebuild the checklist for this procedure.
        for w in self._cgrid.winfo_children():
            w.destroy()
        trip = {"trip_type": self._trip_type.get()}
        # The checklist depends on how the trip travels and who is paying, so
        # it is built from what is on screen right now.
        snapshot = dict(trip)
        try:
            snapshot["travel_method"] = self._vars["travel_method"].get()
            snapshot["budget_code"] = self._vars["budget_code"].get()
        except Exception:
            pass
        trip = snapshot
        for i, (key, label) in enumerate(ft.checklist_for(trip)):
            self._make_item(i, key, label)
        # The overnight extras are things most teachers have never been asked
        # for, so the window says what they are rather than leaving a tickbox
        # to be guessed at.
        extras = []
        if overnight and ft.uses_charter(snapshot):
            extras.append(
                "Bus company's safety record: the state keeps one for every "
                "charter company. Search for the company by name on the "
                "Washington Utilities and Transportation Commission website "
                "(utc.wa.gov), print its profile, and staple it to the "
                "packet. The district calls this a “carrier "
                "profile”.")
        if overnight and ft.uses_asb_money(snapshot):
            extras.append("A trip on an ASB org key needs the ASB minutes "
                          "attached, and the amount approved there has to "
                          "match the amount on the application.")
        self._extras_note.config(text="  ".join(extras))

        forms = ft.required_forms(trip, elementary=self._elementary)
        if forms:
            self._forms_note.config(
                text="Paper forms for this trip: "
                     + ", ".join(ft.FORM_LABELS[f] for f in forms)
                     + ". Track who has handed them in with the Forms button "
                       "on the trip card.")
        elif ft.uses_finalforms(trip, self._elementary):
            self._forms_note.config(
                text="FinalForms is the permission record for a middle or high "
                     "school day trip: the office builds the participant group "
                     "and there are no paper slips to collect.")
        else:
            self._forms_note.config(text="")

    _BOARD_SEP = "   —   "

    def _board_options(self):
        """The meetings Roka knows about, labelled with what each one means for
        this trip: the packet deadline, and whether it is still in reach."""
        import school_calendar as sc
        year = self._school_year_of(self._vars["depart_date"].get().strip())
        # Only meetings this trip could actually be approved at.  The board
        # holds twenty-odd a year, and a list including the ones whose packet
        # deadline has already gone is a haystack, not a choice.
        trip = {"depart_date": self._vars["depart_date"].get()}
        opts, labels = [], []
        for o in ft.usable_board_meetings(year, trip):
            tail = o["label"]
            if o["packet_due"]:
                tail += f", packet due {o['packet_due'].isoformat()}"
            labels.append(o["date"].isoformat() + self._BOARD_SEP + tail)
            opts.append(o)
        self._board_opts = opts
        return labels

    @staticmethod
    def _school_year_of(date_str):
        d = ct.parse_date(date_str)
        if not d:
            from lesson_plan_db import current_school_year
            return current_school_year()
        start = d.year if d.month >= 7 else d.year - 1
        return f"{start}-{start + 1}"

    def _board_picked(self):
        """Keep only the date; the rest of the label was there to choose by."""
        raw = self._vars["board_date"].get()
        if self._BOARD_SEP in raw:
            self._vars["board_date"].set(raw.split(self._BOARD_SEP, 1)[0])

    def _board_note_update(self):
        """Say whether this is a meeting Roka has heard of, and which one is
        still in reach.  A typed date is accepted either way -- the district
        publishes only the next couple, so most real dates will be unknown
        here, and refusing them would make the field useless."""
        import school_calendar as sc
        year = self._school_year_of(self._vars["depart_date"].get().strip())
        typed = ct.parse_date(self._vars["board_date"].get().split(
            self._BOARD_SEP)[0].strip())
        known = {o["date"] for o in ft.board_meeting_options(year)}
        if typed and known and typed not in known:
            self._board_note.config(
                text="That is not one of the board's regular meetings. Trips "
                     "are approved at regular meetings, so check it against "
                     + sc.BOARD_MEETINGS_URL,
                foreground=muted_fg())
            return
        advice = ft.board_meeting_advice(
            year, {"depart_date": self._vars["depart_date"].get()})
        self._board_note.config(text=advice,
                                foreground="#B45309" if "None of" in advice
                                or "no school board" in advice else muted_fg())

    def _elem_ticked(self):
        """Once she has answered, stop overruling her with the guess."""
        self._elem_touched = True
        self._type_changed()

    def _date_changed(self):
        self._check_blackout()
        if self._trip_type.get() == ft.TRIP_OVERNIGHT:
            try:
                self._board_combo["values"] = self._board_options()
                self._board_note_update()
            except Exception:
                pass

    def _check_blackout(self):
        """Warn while the date is being typed, not after the packet is done.

        A date already gone by is checked here too, and it is the more common
        mistake by far: a school year spans two calendar years, so in August
        "March 9th" is 2027, and typing 2026 files the whole trip under
        completed the moment it is saved.
        """
        raw = self._vars["depart_date"].get().strip()
        d = ct.parse_date(raw)
        bits = []
        if d and d < datetime.today().date():
            bits.append("That date has already gone by, so this trip will be "
                        "filed under completed trips as soon as you save. Check "
                        "the year: a school year runs across two of them.")
        reasons, unchecked = ft.blackout_warning(raw)
        if reasons:
            msg = ("The district asks you to avoid this date: "
                   + "; ".join(reasons) + ".")
            if unchecked:
                msg += (" Roka does not have this year's "
                        + " or ".join(unchecked) + " dates, so it could not "
                        "check those.")
            bits.append(msg)
        self._blackout.config(text="  ".join(bits))

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
        data["trip_type"] = self._trip_type.get()
        data["elementary"] = 1 if self._elem_var.get() else 0
        # A day trip returns the day it left.  Leaving it blank printed a blank
        # Return Date on the district form, which is a question the form asks.
        if (data["trip_type"] == ft.TRIP_DAY and data.get("depart_date")
                and not (data.get("return_date") or "").strip()):
            data["return_date"] = data["depart_date"]
        if data.get("board_date"):
            data["board_date"] = data["board_date"].split(
                self._BOARD_SEP)[0].strip()
        for key, box in self._long_vars.items():
            data[key] = box.get("1.0", "end").strip()
        for key, _label in ft.CHECKLIST_ITEMS:
            data[key] = self._check_states.get(key, 0)

        # Said once, on the way out, so it cannot be missed -- but not
        # blocking. A teacher may have a real reason, and the district asks
        # people to avoid these dates rather than forbidding them.
        gone = ct.parse_date(data.get("depart_date"))
        if gone and gone < datetime.today().date():
            if Messagebox.yesno(
                    f"{ct.fmt_date(data.get('depart_date'))} has already gone "
                    f"by.\n\nThis trip will go straight into completed trips. "
                    f"If you meant a date still to come, check the year — a "
                    f"school year runs across two calendar years.\n\nSave it "
                    f"anyway?",
                    title="That date has passed", parent=self) != "Yes":
                return
        reasons, _unchecked = ft.blackout_warning(data.get("depart_date"))
        if reasons:
            if Messagebox.yesno(
                    "The district asks you to avoid this date:\n\n  · "
                    + "\n  · ".join(reasons)
                    + "\n\nSave it anyway?",
                    title="Blackout date", parent=self) != "Yes":
                return
        self.result = data
        self.destroy()


# ═══════════════════════════════════════ District deadlines ══════════════════

class _DeadlinesDialog(ttk.Toplevel):
    """What 2320P requires, when, counted in school weeks.

    Every district deadline is expressed in SCHOOL weeks, and eight school
    weeks across winter break is most of a term.  That arithmetic is exactly
    what a teacher does in their head, gets wrong, and finds out about too
    late to fix -- so the tool does it.
    """

    def __init__(self, parent, db, trip, year):
        super().__init__(parent.winfo_toplevel())
        import school_calendar as sc

        self.title(f"District deadlines — {trip['name']}")
        self.resizable(True, True)
        self.grab_set()

        kind = ft.trip_type(trip)
        ttk.Label(self, text=f"🗓  {ft.TRIP_TYPE_LABEL[kind]} — what the "
                             f"district needs, and when",
                  font=("Segoe UI", 12, "bold"),
                  bootstyle=PRIMARY).pack(anchor=W, padx=16, pady=(12, 2))
        anchor_note = ("Counted back from the school board meeting where "
                       "marked, otherwise from the trip."
                       if kind == ft.TRIP_OVERNIGHT else
                       "Counted back from the trip, in school weeks — breaks "
                       "do not count.")
        ttk.Label(self, text=anchor_note, font=("Segoe UI", 8),
                  foreground=muted_fg(), wraplength=560,
                  justify=LEFT).pack(anchor=W, padx=16)

        cal = sc.get_calendar(year)
        if not cal:
            ttk.Label(self, text=f"Roka has no school calendar for {year}, so "
                                 f"these are counted in calendar weeks and "
                                 f"will be optimistic.",
                      font=("Segoe UI", 9), foreground="#B45309",
                      wraplength=560, justify=LEFT).pack(anchor=W, padx=16,
                                                         pady=(6, 0))

        body = scroll_body(self, padx=16, pady=8)
        for d in ft.deadlines(trip, cal):
            box = tk.LabelFrame(body, text=f" {d['label']} ",
                                font=("Segoe UI", 9, "bold"), padx=10, pady=6)
            box.pack(fill=X, pady=4)
            if d["due"]:
                when = ct.fmt_date(d["due"].isoformat())
                left = d["school_weeks_left"]
                if d["overdue"]:
                    line, color = f"⚠ PAST DUE — was due {when}", _OVERDUE
                else:
                    line = f"by {when}"
                    if left is not None:
                        line += f"  ·  {left:.0f} school week(s) from today"
                    color = "#1a7a1a" if (left or 0) > 2 else _SOON
            else:
                line = ("Set the school board meeting date on the trip to "
                        "work this one out.")
                color = "#B45309"
            ttk.Label(box, text=line, font=("Segoe UI", 10, "bold"),
                      foreground=color).pack(anchor=W)
            ttk.Label(box, text=f"{d['weeks']} school weeks before "
                                + ("the board meeting" if d["anchor"] == "board"
                                   else "the trip"),
                      font=("Segoe UI", 8), foreground=muted_fg()).pack(anchor=W)
            ttk.Label(box, text=d["detail"], font=("Segoe UI", 9),
                      wraplength=520, justify=LEFT).pack(anchor=W, pady=(2, 0))

        ttk.Button(self, text="Close", bootstyle=(SECONDARY, OUTLINE),
                   command=self.destroy).pack(pady=(4, 12))
        fit_window(self, 600, 560)


def _ask_text(parent, title, prompt, hint=""):
    """One line of text.  Returns the text, or None if cancelled."""
    win = ttk.Toplevel(master=parent)
    win.title(title)
    win.grab_set()
    ttk.Label(win, text=prompt, font=("Segoe UI", 10, "bold")).pack(
        anchor=W, padx=16, pady=(14, 2))
    if hint:
        ttk.Label(win, text=hint, font=("Segoe UI", 8), foreground=muted_fg(),
                  wraplength=380, justify=LEFT).pack(anchor=W, padx=16)
    var = tk.StringVar()
    entry = ttk.Entry(win, textvariable=var, width=44)
    entry.pack(anchor=W, padx=16, pady=(8, 4))
    entry.focus_set()
    out = {"v": None}

    def ok(_e=None):
        out["v"] = var.get().strip() or None
        win.destroy()

    entry.bind("<Return>", ok)
    bar = ttk.Frame(win)
    bar.pack(fill=X, padx=16, pady=12)
    ttk.Button(bar, text="Cancel", bootstyle=(SECONDARY, OUTLINE),
               command=win.destroy).pack(side=RIGHT, padx=4)
    ttk.Button(bar, text="Add", bootstyle=SUCCESS, command=ok).pack(side=RIGHT,
                                                                    padx=4)
    fit_window(win, 440, 220)
    parent.wait_window(win)
    return out["v"]


def _pick_one(parent, title, prompt, options):
    """A small single-choice list.  Returns the chosen string or None."""
    win = ttk.Toplevel(master=parent)
    win.title(title)
    win.grab_set()
    ttk.Label(win, text=prompt, font=("Segoe UI", 10, "bold")).pack(
        anchor=W, padx=16, pady=(14, 6))
    box = tk.Listbox(win, height=min(8, len(options)), width=44)
    for o in options:
        box.insert(END, o)
    box.selection_set(0)
    box.pack(fill=BOTH, expand=True, padx=16)
    chosen = {"v": None}

    def ok():
        sel = box.curselection()
        if sel:
            chosen["v"] = options[sel[0]]
        win.destroy()

    bar = ttk.Frame(win)
    bar.pack(fill=X, padx=16, pady=12)
    ttk.Button(bar, text="Cancel", bootstyle=(SECONDARY, OUTLINE),
               command=win.destroy).pack(side=RIGHT, padx=4)
    ttk.Button(bar, text="OK", bootstyle=SUCCESS, command=ok).pack(side=RIGHT,
                                                                   padx=4)
    fit_window(win, 380, 260)
    parent.wait_window(win)
    return chosen["v"]


# ═══════════════════════════════════════ District application ════════════════

class _ApplicationDialog(ttk.Toplevel):
    """The district field trip application, as one fillable, savable form.

    The answers and the costs used to live in two different windows, which was
    a filing decision rather than a real one: they go on the same sheet of
    paper.  This is that sheet.  Fill it in, Save, and print it from here.

    What is NOT here is what the trip already knows -- its name, dates, groups,
    destination, travel.  Those are shown at the top, read-only, so you can see
    what will print without having two places that both claim to own them.
    """

    def __init__(self, parent, db, main_db, trip, base_dir, students,
                 elementary=False):
        super().__init__(parent.winfo_toplevel())
        self.view = parent
        self.db = db
        self.main_db = main_db
        self.trip = trip
        self.base_dir = base_dir
        self.students = students
        self._elementary = elementary
        self.title(f"District application — {trip.get('name')}")
        self.resizable(True, True)
        self.grab_set()

        overnight = ft.trip_type(trip) == ft.TRIP_OVERNIGHT
        self._overnight = overnight

        ttk.Label(self, text=f"\U0001F4C4  District application — "
                             f"{trip.get('name')}",
                  font=("Segoe UI", 12, "bold"),
                  bootstyle=PRIMARY).pack(anchor=W, padx=16, pady=(12, 0))
        ttk.Label(self,
                  text=("Out of State or Overnight Field Trip Planning"
                        if overnight else "Day Field Trip Application")
                       + " (2320P). Everything on the district's form is here. "
                         "Anything left blank prints blank.",
                  font=("Segoe UI", 8), foreground=muted_fg(),
                  wraplength=620, justify=LEFT).pack(anchor=W, padx=16)

        # Buttons first, so they survive a short window.
        bar = ttk.Frame(self)
        bar.pack(side=BOTTOM, fill=X, padx=16, pady=12)
        ttk.Button(bar, text="Close", bootstyle=(SECONDARY, OUTLINE),
                   command=self.destroy).pack(side=RIGHT, padx=4)
        ttk.Button(bar, text="\U0001F4BE Save", bootstyle=SUCCESS,
                   command=self._save).pack(side=RIGHT, padx=4)
        ttk.Button(bar, text="\U0001F5A8 Generate PDF of completed form",
                   bootstyle=PRIMARY,
                   command=self._generate).pack(side=LEFT)
        if ft.required_forms(trip, elementary):
            ttk.Button(bar, text="\U0001F5A8 Permission forms for every student",
                       bootstyle=(INFO, OUTLINE),
                       command=self._generate_permission).pack(side=LEFT, padx=6)

        body = scroll_body(self, padx=16, pady=6)
        self._vars = {}
        self._texts = {}

        # ── What the trip already knows ──
        known = tk.LabelFrame(body, text=" From the trip ",
                              font=("Segoe UI", 9, "bold"), padx=10, pady=6)
        known.pack(fill=X, pady=(0, 8))
        attending = ft.roster(students, trip, db.get_trip_exclusions(trip["id"]))
        self._n_students = len(attending)
        chaps = len(db.get_trip_chaperones(trip["id"]))
        self._n_chaps = chaps
        rows = [("Class or group", trip.get("groups_list")),
                ("Destination", trip.get("destination")),
                ("Departure", ft.when_line(trip.get("depart_date"),
                                           trip.get("depart_time")) or "—"),
                ("Return", ft.when_line(ft.effective_return_date(trip),
                                        trip.get("return_time")) or "—"),
                ("Method of travel", trip.get("travel_method")),
                ("Number of students", f"{self._n_students} "
                                       f"(from the roster)"),
                ("Chaperones", str(chaps))]
        for label, value in rows:
            r = ttk.Frame(known)
            r.pack(fill=X, pady=1)
            ttk.Label(r, text=label + ":", font=("Segoe UI", 8, "bold"),
                      width=20).pack(side=LEFT)
            ttk.Label(r, text=str(value or "—"),
                      font=("Segoe UI", 9)).pack(side=LEFT)
        ttk.Label(known, text="Change any of these with Edit on the trip.",
                  font=("Segoe UI", 8), foreground=muted_fg()).pack(anchor=W,
                                                                    pady=(4, 0))

        def field(parent, label, key, hint="", width=40):
            ttk.Label(parent, text=label, font=("Segoe UI", 9, "bold")
                      ).pack(anchor=W, pady=(8, 0))
            if hint:
                ttk.Label(parent, text=hint, font=("Segoe UI", 8),
                          foreground=muted_fg(), wraplength=560,
                          justify=LEFT).pack(anchor=W)
            v = tk.StringVar(value=str(trip.get(key) or ""))
            self._vars[key] = v
            ttk.Entry(parent, textvariable=v, width=width).pack(anchor=W)
            return v

        def long_field(parent, label, key, hint="", height=3):
            ttk.Label(parent, text=label, font=("Segoe UI", 9, "bold")
                      ).pack(anchor=W, pady=(8, 0))
            if hint:
                ttk.Label(parent, text=hint, font=("Segoe UI", 8),
                          foreground=muted_fg(), wraplength=560,
                          justify=LEFT).pack(anchor=W)
            box = tk.Text(parent, height=height, width=64,
                          font=("Segoe UI", 9), relief="solid", bd=1, wrap=WORD)
            box.insert("1.0", str(trip.get(key) or ""))
            box.pack(anchor=W, fill=X)
            self._texts[key] = box

        # ── The header answers ──
        head = tk.LabelFrame(body, text=" Header ",
                             font=("Segoe UI", 9, "bold"), padx=10, pady=6)
        head.pack(fill=X, pady=(0, 8))
        field(head, "Charge to budget code", "budget_code",
              hint="The Org Key.", width=26)
        field(head, "Educational objective", "educational_objective",
              hint="Called out twice in the district's own instructions as the "
                   "one people leave off.", width=60)
        if overnight:
            field(head, "Your cell phone", "advisor_phone", width=22)
            field(head, "Destination address / contact", "dest_address",
                  hint="Parents get this on Exhibit C, with the itinerary.",
                  width=60)
            field(head, "Arrive at destination", "arrive_dest_time", width=18)
            field(head, "Depart destination", "depart_dest_time", width=18)

        # ── Trip costs, on the same form as they are on the page ──
        costs = tk.LabelFrame(body, text=" Trip costs ",
                              font=("Segoe UI", 9, "bold"), padx=10, pady=6)
        costs.pack(fill=X, pady=(0, 8))
        ttk.Label(costs, text="One-time totals the school pays; the cost per "
                              "student is worked out from these and the "
                              "roster. Leave a box empty to leave it empty on "
                              "the form, type 0 to print $0.00, or write TBD "
                              "or N/A for something you do not know yet.",
                  font=("Segoe UI", 8), foreground=muted_fg(),
                  wraplength=560, justify=LEFT).pack(anchor=W)
        self._cost_vars = {}
        grid = ttk.Frame(costs)
        grid.pack(anchor=W, pady=(4, 0))
        for i, (label, key) in enumerate([
                ("Entry fee / participation", "entry_fee"),
                ("Transportation", "transport_cost"),
                ("Food", "food_cost"),
                ("Other", "other_cost")]):
            ttk.Label(grid, text=label, font=("Segoe UI", 9)).grid(
                row=i, column=0, sticky=W, padx=(0, 8), pady=2)
            ttk.Label(grid, text="$", font=("Segoe UI", 9)).grid(
                row=i, column=1, sticky=E)
            v = tk.StringVar(value=str(trip.get(key) or ""))
            v.trace_add("write", lambda *a: self._recalc())
            self._cost_vars[key] = v
            ttk.Entry(grid, textvariable=v, width=12).grid(row=i, column=2,
                                                           sticky=W, pady=2)

        srow = ttk.Frame(costs)
        srow.pack(anchor=W, pady=(6, 0))
        ttk.Label(srow, text="Substitute teacher \u2013 check one",
                  font=("Segoe UI", 9)).pack(side=LEFT, padx=(0, 8))
        self._rate_labels = {"": "No substitute needed"}
        for key, label, _amt in ft.SUB_RATES:
            self._rate_labels[key] = label
        self._rate_keys = {v: k for k, v in self._rate_labels.items()}
        self._sub_rate = tk.StringVar(value=self._rate_labels.get(
            (trip.get("sub_rate") or "").strip(), "No substitute needed"))
        rate_cb = ttk.Combobox(srow, textvariable=self._sub_rate,
                               state="readonly", width=20,
                               values=list(self._rate_labels.values()))
        rate_cb.pack(side=LEFT)
        rate_cb.bind("<<ComboboxSelected>>", lambda e: self._rate_picked())
        ttk.Label(srow, text="$", font=("Segoe UI", 9)).pack(side=LEFT,
                                                             padx=(10, 0))
        sv = tk.StringVar(value=str(trip.get("sub_cost") or ""))
        sv.trace_add("write", lambda *a: self._recalc())
        self._cost_vars["sub_cost"] = sv
        ttk.Entry(srow, textvariable=sv, width=10).pack(side=LEFT)
        ttk.Label(costs, text=ft.SUB_RATE_NOTE, font=("Segoe UI", 8),
                  foreground=muted_fg()).pack(anchor=W)

        frow = ttk.Frame(costs)
        frow.pack(anchor=W, pady=(8, 0))
        ttk.Label(frow, text="Funding", font=("Segoe UI", 9, "bold")).pack(
            side=LEFT, padx=(0, 8))
        self._funding = tk.StringVar(value=trip.get("funding")
                                     or ft.FUNDING_CURRICULAR)
        ttk.Radiobutton(frow, text="Building / department (curricular)",
                        value=ft.FUNDING_CURRICULAR, variable=self._funding,
                        bootstyle=PRIMARY).pack(side=LEFT)
        ttk.Radiobutton(frow, text="ASB / boosters (extracurricular)",
                        value=ft.FUNDING_EXTRACURRICULAR,
                        variable=self._funding,
                        bootstyle=PRIMARY).pack(side=LEFT, padx=(12, 0))
        self._covered = tk.BooleanVar(value=bool(trip.get("covered")))
        self._covered.trace_add("write", lambda *a: self._recalc())
        ttk.Checkbutton(costs, text="Costs fully covered \u2014 no student charge",
                        variable=self._covered, bootstyle=SUCCESS).pack(
            anchor=W, pady=(6, 0))
        self._totals = ttk.Label(costs, text="", font=("Segoe UI", 10, "bold"))
        self._totals.pack(anchor=W, pady=(6, 0))

        # ── The narrative answers, in the district's order ──
        ans = tk.LabelFrame(body, text=" The questions on the form ",
                            font=("Segoe UI", 9, "bold"), padx=10, pady=6)
        ans.pack(fill=X, pady=(0, 8))
        long_field(ans, "Describe activities planned while on the trip",
                   "activities")
        long_field(ans, "Required and alternate assignments", "assignments",
                   hint="And what students who miss the trip do instead.")
        long_field(ans, "Work missed in other classes", "missed_work", height=2)
        field(ans, "How many adults will provide supervision", "supervision",
              hint="Leave blank and the form prints your chaperone count plus "
                   "your own name.", width=60)
        long_field(ans, "Students who cannot afford the trip", "affordability",
                   hint="How they get help, and how they ask for it.")
        long_field(ans, "Health needs reviewed with the nurse", "health_review",
                   height=2)
        if overnight:
            long_field(ans, "Itinerary", "itinerary",
                       hint="As detailed as you can. Parents get this too, "
                            "attached to Exhibit C.", height=5)

        self._recalc()
        fit_window(self, 700, 720)

    # ── behaviour ────────────────────────────────────────────────────────

    def _rate_key(self):
        return self._rate_keys.get(self._sub_rate.get(), "")

    def _rate_picked(self):
        key = self._rate_key()
        # Choosing "no substitute needed" is an ANSWER, so it writes 0 rather
        # than clearing the box: a blank means the question is still open, and
        # the two should not look the same on a form somebody signs.
        self._cost_vars["sub_cost"].set(
            f"{ft.SUB_RATE_AMOUNT[key]:.2f}" if key in ft.SUB_RATE_AMOUNT
            else "0")

    def _snapshot(self):
        """What is on screen right now, as a trip dict."""
        out = dict(self.trip)
        for k, v in self._vars.items():
            out[k] = v.get().strip()
        for k, box in self._texts.items():
            out[k] = box.get("1.0", "end").strip()
        # Kept as typed.  Blank means the question is open, "0" means the
        # answer is nothing, and "TBD" means it is not a number yet -- three
        # different answers that all became 0.0 before, and all printed blank.
        for k, v in self._cost_vars.items():
            out[k] = str(v.get()).strip()
        out["sub_rate"] = self._rate_key()
        out["funding"] = self._funding.get()
        out["covered"] = 1 if self._covered.get() else 0
        return out

    def _recalc(self):
        costs = ft.trip_costs(self._snapshot(), self._n_students)
        per = ("$0.00 (covered)" if self._covered.get()
               else f"${costs['per_student']:,.2f}")
        self._totals.config(
            text=f"Total: ${costs['total']:,.2f}      "
                 f"Anticipated cost / student: {per}")

    def _save(self, quiet=False):
        data = self._snapshot()
        try:
            self.db.update_field_trip(self.trip["id"],
                                      {k: data[k] for k in data
                                       if k not in ("id", "created_at",
                                                    "updated_at")})
        except Exception as e:
            Messagebox.show_error(f"Could not save.\n\n{e}", title="Not saved",
                                  parent=self)
            return False
        self.trip = dict(self.db.get_field_trip(self.trip["id"]))
        if not quiet:
            Messagebox.show_info("Saved.", title="Saved", parent=self)
        return True

    def _generate(self):
        """Save first, then print: printing something other than what is on
        screen is the kind of surprise that costs a rewrite."""
        import field_trip_pdf as fp
        from tkinter import filedialog

        if not self._save(quiet=True):
            return
        t = dict(self.trip)
        who, where = self._teacher()
        path = filedialog.asksaveasfilename(
            parent=self, defaultextension=".pdf",
            initialfile=fp.suggested_filename(t),
            title="Save the completed application",
            filetypes=[("PDF", "*.pdf")])
        if not path:
            return
        try:
            fp.build_application(t, path, students=self._n_students,
                                 chaperones=self._n_chaps, teacher_name=who,
                                 school_name=where)
        except Exception as e:
            Messagebox.show_error(f"Could not write the application.\n\n{e}",
                                  title="Not saved", parent=self)
            return
        _open_file(path, self)

    def _generate_permission(self):
        """One PDF, one page per student, school portion already filled."""
        import field_trip_pdf as fp
        from tkinter import filedialog

        if not self._save(quiet=True):
            return
        t = dict(self.trip)
        attending = ft.roster(self.students, t,
                              self.db.get_trip_exclusions(t["id"]))
        if not attending:
            Messagebox.show_info(
                "Nobody is on this trip yet, so there is nobody to print a "
                "form for. Choose the class groups on the trip first.",
                title="No students", parent=self)
            return
        who, where = self._teacher()
        path = filedialog.asksaveasfilename(
            parent=self, defaultextension=".pdf",
            initialfile=fp.suggested_permission_filename(t),
            title="Save the permission forms",
            filetypes=[("PDF", "*.pdf")])
        if not path:
            return
        try:
            fp.build_permission_forms(t, attending, path, teacher_name=who,
                                      school_name=where,
                                      elementary=self._elementary)
        except Exception as e:
            Messagebox.show_error(f"Could not write the forms.\n\n{e}",
                                  title="Not saved", parent=self)
            return
        Messagebox.show_info(
            f"{len(attending)} form(s), one per student, with the school "
            f"portion already filled in.",
            title="Ready to photocopy", parent=self)
        _open_file(path, self)

    def _teacher(self):
        try:
            from ui.settings_dialog import load_settings, school_name
            t = (load_settings(self.base_dir).get("teacher") or {})
            return (t.get("display_name") or "").strip(), \
                   (school_name(self.base_dir) or "")
        except Exception:
            return "", ""


def _open_file(path, parent):
    try:
        os.startfile(path)
    except Exception:
        Messagebox.show_info(f"Saved to:\n{path}", title="Saved", parent=parent)


# ═══════════════════════════════════════════ Roster & costs ══════════════════

class _RosterFormsDialog(ttk.Toplevel):
    """Who is going, and who has handed their permission form back.

    These were two windows and one job.  A teacher looking at the roster is
    almost always asking one of two questions -- is this the right list, and
    who still owes me a form -- and answering them meant opening two things.
    Costs moved the other way, onto the district application, because that is
    the sheet of paper they get written on.
    """

    def __init__(self, parent, db, trip, students, elementary=False):
        super().__init__(parent.winfo_toplevel())
        self.db = db
        self.base_dir = getattr(parent, "base_dir", "")
        self.trip = trip
        self._elementary = elementary
        self._recount_columns()
        self.title(f"Roster & Forms — {trip['name']}")
        self.resizable(True, True)
        self.grab_set()

        ttk.Label(self, text=f"\U0001F465  Roster & Forms — {trip['name']}",
                  font=("Segoe UI", 12, "bold"),
                  bootstyle=PRIMARY).pack(anchor=W, padx=16, pady=(12, 2))
        self._why = ttk.Label(self, text="", font=("Segoe UI", 8),
                              foreground=muted_fg(), wraplength=620,
                              justify=LEFT)
        self._why.pack(anchor=W, padx=16)

        btns = ttk.Frame(self)
        btns.pack(fill=X, side=BOTTOM, padx=16, pady=10)
        ttk.Button(btns, text="Close", bootstyle=(SECONDARY, OUTLINE),
                   command=self.destroy).pack(side=RIGHT, padx=4)
        ttk.Button(btns, text="Save", bootstyle=SUCCESS,
                   command=self._save).pack(side=RIGHT, padx=4)
        self._email_btn = ttk.Button(btns, text="\u2709 Email who is missing one",
                                     bootstyle=(WARNING, OUTLINE),
                                     command=self._email_missing)
        self._all_in_btn = ttk.Button(btns, text="Everyone handed one in",
                                      bootstyle=(SUCCESS, OUTLINE),
                                      command=self._all_in)

        # No "everyone / nobody is going": the roster already arrives as
        # everyone in the chosen groups, which is the answer nine times in ten,
        # and the tenth is one or two children -- untick them.
        bar = ttk.Frame(self)
        bar.pack(fill=X, padx=16, pady=(6, 2))
        ttk.Button(bar, text="\u2795 Add checklist item",
                   bootstyle=(PRIMARY, OUTLINE),
                   command=self._add_column).pack(side=LEFT)
        self._del_btn = ttk.Button(bar, text="Remove checklist item",
                                   bootstyle=(SECONDARY, OUTLINE),
                                   command=self._remove_column)
        ttk.Label(bar, text="  Track anything you chase per student: an "
                            "interest survey, a deposit, a signed code of "
                            "conduct.",
                  font=("Segoe UI", 8), foreground=muted_fg()).pack(side=LEFT,
                                                                    padx=(8, 0))

        self._students = sorted(
            ft.eligible(students, trip),
            key=lambda x: ((x.get("last_name") or "").lower(),
                           (x.get("first_name") or "").lower()))
        excluded = db.get_trip_exclusions(trip["id"])
        self._going = {s["id"]: s["id"] not in excluded for s in self._students}
        self._have = db.get_trip_forms(trip["id"])

        self._tree_holder = ttk.Frame(self)
        self._tree_holder.pack(fill=BOTH, expand=True, padx=16, pady=(6, 4))
        self.tree = None
        self._build_tree()

        self._summary = ttk.Label(self, text="", font=("Segoe UI", 10, "bold"),
                                  justify=LEFT)
        self._summary.pack(anchor=W, padx=16)
        self._outstanding = ttk.Label(self, text="", font=("Segoe UI", 9),
                                      justify=LEFT)
        self._outstanding.pack(anchor=W, padx=16)
        self._costs = ttk.Label(self, text="", font=("Segoe UI", 9),
                                foreground=muted_fg())
        self._costs.pack(anchor=W, padx=16, pady=(0, 4))

        self._reload()
        fit_window(self, 640, 560)

    # ── columns ─────────────────────────────────────────────────────────

    def _recount_columns(self):
        """District columns plus whatever the teacher has added."""
        self.columns = ft.form_columns(self.trip, self._elementary)
        self.forms = [k for k, _l in self.columns]

    def _build_tree(self):
        """(Re)build the grid.  Treeview columns cannot be added after the
        fact, so adding a checklist item rebuilds it -- cheap, and it keeps
        one code path for however many columns there are."""
        for w in self._tree_holder.winfo_children():
            w.destroy()
        cols = ["going", "name", "grade"] + self.forms + ["filler"]
        self.tree = ttk.Treeview(self._tree_holder, columns=cols,
                                 show="headings", selectmode="browse",
                                 bootstyle=PRIMARY)
        self.tree.heading("going", text="Going", anchor=CENTER)
        self.tree.column("going", width=px(56), anchor=CENTER, stretch=False)
        self.tree.heading("name", text="Student", anchor=W)
        # Fixed, not stretchy.  A stretching name column swallows every pixel
        # the window is wider than its contents, which put a hand's width of
        # nothing between a student and their tick box.
        self.tree.column("name", width=px(200), anchor=W, stretch=False)
        self.tree.heading("grade", text="Gr", anchor=CENTER)
        self.tree.column("grade", width=px(40), anchor=CENTER, stretch=False)
        for key, label in self.columns:
            self.tree.heading(key, text=label, anchor=CENTER)
            self.tree.column(key, width=px(max(96, int(7.6 * len(label)))),
                             anchor=CENTER, stretch=False)
        # The slack goes here instead, at the far right where it reads as
        # margin rather than as a gap in the row.
        self.tree.heading("filler", text="")
        self.tree.column("filler", width=px(10), stretch=True)
        self.tree.pack(fill=BOTH, expand=True)
        self.tree.bind("<Button-1>", self._click, add="+")

        has = bool(self.columns)
        for btn, show in ((self._email_btn, has), (self._all_in_btn, has),
                          (self._del_btn, bool(ft.custom_forms(self.trip)))):
            if show:
                btn.pack(side=LEFT, padx=(0, 6))
            else:
                btn.pack_forget()

        why = ("Everyone in the groups on this trip. Untick anyone who is not "
               "going.")
        if self.columns:
            why += "  Tick each column as it comes back."
        elif ft.uses_finalforms(self.trip, self._elementary):
            why += ("  No paper forms for this trip — FinalForms is the "
                    "permission record. Add a checklist item for anything else "
                    "you chase.")
        self._why.config(text=why)

    def _add_column(self):
        label = _ask_text(self, "Add checklist item",
                          "What are you tracking for each student?",
                          "For example: Interest form, Deposit paid, Code of "
                          "conduct signed, Rooming preference.")
        if not label:
            return
        raw, key = ft.add_custom_form(self.trip, label)
        if not key:
            Messagebox.show_info(f"There is already a column called "
                                 f"“{label.strip()}”.",
                                 title="Already there", parent=self)
            return
        self.trip["custom_forms"] = raw
        self.db.update_field_trip(self.trip["id"], {"custom_forms": raw})
        self._recount_columns()
        self._build_tree()
        self._reload()

    def _remove_column(self):
        customs = ft.custom_forms(self.trip)
        if not customs:
            return
        labels = [l for _k, l in customs]
        chosen = _pick_one(self, "Remove checklist item",
                           "Which column should go?", labels)
        if not chosen:
            return
        key = customs[labels.index(chosen)][0]
        if Messagebox.yesno(
                f"Remove “{chosen}” and everything ticked in it?\n\nThe "
                f"students and their other columns are not affected.",
                title="Remove column", parent=self) != "Yes":
            return
        raw = ft.remove_custom_form(self.trip, key)
        self.trip["custom_forms"] = raw
        self.db.update_field_trip(self.trip["id"], {"custom_forms": raw})
        for stu in self._students:
            self._have.pop((stu["id"], key), None)
        try:
            self.db.clear_trip_form(self.trip["id"], key)
        except Exception:
            pass
        self._recount_columns()
        self._build_tree()
        self._reload()

    # ── data ────────────────────────────────────────────────────────────

    def _reload(self):
        from concert_tools import _display_name
        self.tree.delete(*self.tree.get_children())
        for stu in self._students:
            vals = ["\u2611" if self._going.get(stu["id"]) else "\u2610",
                    _display_name(stu), stu.get("grade") or ""]
            for f in self.forms:
                vals.append("\u2611" if self._have.get((stu["id"], f))
                            else "\u2610")
            vals.append("")                       # the filler column
            self.tree.insert("", "end", iid=str(stu["id"]), values=vals)
        self._recalc()

    def _recalc(self):
        n = sum(1 for v in self._going.values() if v)
        need = ft.chaperones_needed(n)
        self._summary.config(
            text=f"{n} student(s) attending      "
                 f"\u2248 {need} adult chaperone(s) suggested "
                 f"(1 per {ft.STUDENTS_PER_CHAPERONE}, plus you)")
        line, colour = "", muted_fg()
        if self.forms:
            going = [s for s in self._students if self._going.get(s["id"])]
            missing = sum(1 for s in going for f in self.forms
                          if not self._have.get((s["id"], f)))
            gate = [f for f in self.forms if f in ft.FORM_GATES_ATTENDANCE]
            cannot = [s for s in going
                      if any(not self._have.get((s["id"], f)) for f in gate)]
            if missing:
                line = f"{missing} still to come back"
                if cannot:
                    line += (f"  \u00b7  {len(cannot)} cannot travel without "
                             f"the {ft.FORM_SHORT[gate[0]]} form")
                colour = "#B45309"
            else:
                line, colour = "Everything is in \u2713", "#1a7a1a"
        self._outstanding.config(text=line, foreground=colour)
        costs = ft.trip_costs(self.trip, n)
        per = ("$0.00 (covered)" if self.trip.get("covered")
               else f"${costs['per_student']:,.2f}")
        self._costs.config(
            text=f"Costs: ${costs['total']:,.2f} total, {per} per student. "
                 f"Edit them on the Application form.")

    # ── interaction ─────────────────────────────────────────────────────

    def _click(self, event):
        if self.tree.identify("region", event.x, event.y) != "cell":
            return
        iid = self.tree.identify_row(event.y)
        if not iid:
            return
        try:
            col = int(self.tree.identify_column(event.x).replace("#", "")) - 1
        except ValueError:
            return
        sid = int(iid)
        if col == 0:
            self._going[sid] = not self._going.get(sid)
        elif col >= 3 and col - 3 < len(self.forms):
            form = self.forms[col - 3]
            now = not self._have.get((sid, form))
            self.db.set_trip_form(self.trip["id"], sid, form, now)
            self._have[(sid, form)] = 1 if now else 0
        else:
            return
        self._reload()
        self.tree.selection_set(iid)
        self.tree.see(iid)

    def _all_in(self):
        """One tick for a form the whole class handed in together, which is
        what happens when they are collected in the room."""
        form = self.forms[0]
        if len(self.forms) > 1:
            sel = _pick_one(self, "Which column?",
                            "Mark every student as done for:",
                            [ft.form_label(self.trip, f) for f in self.forms])
            if not sel:
                return
            form = self.forms[[ft.form_label(self.trip, f)
                               for f in self.forms].index(sel)]
        for stu in self._students:
            self.db.set_trip_form(self.trip["id"], stu["id"], form, True)
            self._have[(stu["id"], form)] = 1
        self._reload()

    def _email_missing(self):
        rows = [s for s in self._students if self._going.get(s["id"])
                and any(not self._have.get((s["id"], f)) for f in self.forms)]
        if not rows:
            Messagebox.show_info("Everything is in.", title="Nothing missing",
                                 parent=self)
            return
        import email_launcher
        addrs = []
        for stu in rows:
            for key in ("parent1_email", "parent2_email"):
                a = (stu.get(key) or "").strip()
                if a and a not in addrs:
                    addrs.append(a)
        if not addrs:
            Messagebox.show_info(
                f"{len(rows)} student(s) still owe a form, but none of them "
                f"have a guardian email on file.",
                title="No addresses", parent=self)
            return
        outstanding = ", ".join(
            label for f, label in self.columns
            if any(not self._have.get((s["id"], f)) for s in rows))
        body = (f"We are still waiting on the {outstanding} form for "
                f"{self.trip['name']}. Please send it in with your child as "
                f"soon as you can, thank you!")
        try:
            email_launcher.compose(
                to=email_launcher.teacher_address(self.base_dir),
                bcc=addrs, subject=f"{self.trip['name']} — form still needed",
                body=body, parent=self)
        except Exception:
            Messagebox.show_info("Addresses:\n\n" + "; ".join(addrs),
                                 title="Copy these", parent=self)

    def _save(self):
        excluded = [sid for sid, going in self._going.items() if not going]
        self.db.set_trip_exclusions(self.trip["id"], excluded)
        self.destroy()


# ═══════════════════════════════════════════ Chaperones ══════════════════════

class _ChaperonesDialog(ttk.Toplevel):
    def __init__(self, parent, db, trip, students, going, attending=None,
                 base_dir=None):
        super().__init__(parent.winfo_toplevel())
        self.db = db
        self.base_dir = base_dir
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
        ttk.Button(brow, text="✉ Email Chaperones",
                   bootstyle=(INFO, OUTLINE),
                   command=self._email).pack(side=LEFT, padx=4)

        self._reload()
        fit_window(self, 680, 480)

    def _email(self):
        """Open a blank message to this trip's chaperones.

        Addresses go in BCC and the teacher's own goes in To, the same as
        every other list Roka sends: a dozen parents in the To line shows
        each of them all the others' addresses.  Subject and body are left
        empty on purpose -- this is for whatever she needs to say today, not
        a template.
        """
        chaps = [dict(c) for c in self.db.get_trip_chaperones(self.trip["id"])]
        if not chaps:
            Messagebox.show_info(
                "No chaperones have signed up for this trip yet.",
                title="Nobody to email", parent=self)
            return

        # Dedupe case-insensitively; two parents of the same child are often
        # entered with the same address.
        seen, addresses, missing = set(), [], []
        for c in chaps:
            addr = (c.get("email") or "").strip()
            if not addr:
                missing.append(c.get("name") or "(unnamed)")
                continue
            if addr.lower() not in seen:
                seen.add(addr.lower())
                addresses.append(addr)

        if not addresses:
            Messagebox.show_warning(
                f"None of the {len(chaps)} chaperone(s) has an email address "
                "on file.\n\nTry Fill Missing Contacts, or add the "
                "addresses in the list above.",
                title="No addresses", parent=self)
            return

        from ui.email_compose import open_message
        note = open_message(self, self.base_dir, subject="", body="",
                            bcc=addresses)
        if note and missing:
            note += (f"  ({len(missing)} without an address: "
                     f"{', '.join(missing[:4])}"
                     f"{'...' if len(missing) > 4 else ''})")
        if note:
            Messagebox.show_info(note, title="Email Chaperones", parent=self)

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
        self.base_dir = getattr(parent, "base_dir", "")
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
                    status, color = f"{label}: ⚠ due (was {due})", _OVERDUE
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

    def _export_student_list(self):
        """The attending students as a spreadsheet, to attach to the staff
        email.  Forty-eight names in the body of a message is a wall nobody
        scrolls; in a grid the office can sort it, and a teacher can filter to
        their own period instead of reading forty-seven other names."""
        import field_trip_pdf as fp
        from tkinter import filedialog

        if not self.attending:
            Messagebox.show_info(
                "Nobody is on this trip yet, so there is nothing to list.",
                title="No students", parent=self)
            return
        try:
            from ui.settings_dialog import load_settings
            who = ((load_settings(self.base_dir).get("teacher") or {})
                   .get("display_name") or "").strip()
        except Exception:
            who = ""
        path = filedialog.asksaveasfilename(
            parent=self, defaultextension=".xlsx",
            initialfile=fp.suggested_student_list_filename(self.trip),
            title="Save the student list", filetypes=[("Excel", "*.xlsx")])
        if not path:
            return
        try:
            fp.build_student_list(self.trip, self.attending, path,
                                  teacher_name=who or self.director,
                                  school_name=self.school)
        except ImportError:
            Messagebox.show_error(
                "Writing a spreadsheet needs openpyxl:  pip install openpyxl",
                title="Missing Dependency", parent=self)
            return
        except Exception as e:
            Messagebox.show_error(f"Could not write the list.\n\n{e}",
                                  title="Not saved", parent=self)
            return
        _open_file(path, self)

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
        from ui.email_compose import add_send_button, add_send_hint
        add_send_hint(win, "so reword it here, not there").pack(anchor=W, padx=16)
        ttk.Label(win, text="Saved as this trip's email, reused for both "
                            "reminder stages and carried into next year via "
                            "“Copy From Previous”.",
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
        ttk.Button(b, text="📋 Copy Subject + Body", bootstyle=(PRIMARY, OUTLINE),
                   command=copy_all).pack(side=RIGHT, padx=4)
        ttk.Button(b, text="📋 Copy Body Only", bootstyle=(PRIMARY, OUTLINE),
                   command=copy_body).pack(side=RIGHT, padx=4)
        if audience == "teachers":
            # The list the email refers to.  Written on demand rather than
            # every time the window opens: most visits are to reword a
            # sentence, not to send.
            ttk.Button(b, text="📊 Student list (Excel)…",
                       bootstyle=(INFO, OUTLINE),
                       command=self._export_student_list).pack(side=LEFT)
        # The addresses this audience gets.  Teachers and admin are chased up
        # individually rather than from a stored list, so that one goes out
        # with no BCC and the teacher adds who it needs to reach.
        bcc = {"families": self._family_addrs,
               "chaperones": self._chap_addrs}.get(audience, [])
        add_send_button(b, win, self.base_dir,
                        subj_var.get, lambda: box.get("1.0", "end"),
                        lambda: bcc,
                        on_before_send=lambda s, t: self._persist_email(audience, t),
                        flash=flash,
                        saved_note="Saved with this trip.")
        ttk.Button(b, text="↺ Reset to Auto", bootstyle=(SECONDARY, OUTLINE),
                   command=reset_auto).pack(side=LEFT, padx=4)
        fit_window(win, 700, 580)

    def _mark(self, key):
        self.db.mark_trip_reminder(self.trip["id"], key,
                                   datetime.today().strftime("%Y-%m-%d"))
        self.destroy()

    def _unmark(self, key):
        self.db.clear_trip_reminder(self.trip["id"], key)
        self.destroy()
