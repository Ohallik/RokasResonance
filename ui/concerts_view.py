"""
ui/concerts_view.py - Concerts tab of Lesson Plans.

One place to plan a concert cycle:
  • the concert itself (date, time, location, ensembles involved)
  • repertoire per ensemble — freely revisable, fine to leave empty early on
  • a family "details page" (attire, arrival, required rehearsals, itinerary)
    exportable as editable Publisher (.pub) or copyable text for email
  • an editable Publisher concert program (cover + personnel in score order)
  • reminder emails on the standard cadence: 2 weeks / 1 week / 2 days out
"""

import os
import threading
import tkinter as tk
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from ttkbootstrap.dialogs import Messagebox
from tkinter import filedialog
from datetime import datetime

from ui.theme import fs, muted_fg, subtle_fg, fit_window
import concert_tools as ct


def _copy(widget, text):
    widget.clipboard_clear()
    widget.clipboard_append(text)


def _default_filename(concert, suffix=""):
    """'2026-06-03 June Concert.pub' — date first so files sort by concert."""
    date = (concert.get("concert_date") or "").strip()
    title = (concert.get("title") or "Concert").strip()
    base = f"{date} {title}".strip() + (f" {suffix}" if suffix else "")
    for ch in '\\/:*?"<>|':
        base = base.replace(ch, "-")
    return base + ".pub"


class ConcertsView(ttk.Frame):
    def __init__(self, parent, db, main_db, base_dir):
        super().__init__(parent)
        self.db = db                # per-year lesson-plan DB (concerts live here)
        self.main_db = main_db      # student records for rosters / parent emails
        self.base_dir = base_dir

        # ── Header ──
        hdr = ttk.Frame(self)
        hdr.pack(fill=X, padx=12, pady=(10, 4))
        left = ttk.Frame(hdr)
        left.pack(side=LEFT)
        ttk.Label(left, text="Concert Planner",
                  font=("Segoe UI", fs(15), "bold")).pack(anchor=W)
        ttk.Label(left, text="Every upcoming concert and its prep checklist "
                             "on one page. Click a checklist item to cycle "
                             "☐ to do → ☑ done → N/A, or right-click to mark "
                             "it N/A right away.",
                  font=("Segoe UI", fs(8)), foreground=subtle_fg()).pack(anchor=W)
        ttk.Button(hdr, text="➕ New Concert", bootstyle=SUCCESS,
                   command=self._new_concert).pack(side=RIGHT)
        ttk.Button(hdr, text="📊 Export Roster (Excel)…",
                   bootstyle=(INFO, OUTLINE),
                   command=self._export_roster).pack(side=RIGHT, padx=(0, 4))

    def _export_roster(self):
        from ui.roster_export_view import open_roster_export
        open_roster_export(self, self.main_db, self.base_dir, self._student_year(),
                           context="For an in-school performance: choose the "
                                   "class(es) performing.")

        # ── Upcoming concerts: scrollable cards, checklist on each ──
        up_frame = tk.LabelFrame(self, text=" Upcoming Concerts ",
                                 font=("Segoe UI", fs(10), "bold"),
                                 padx=4, pady=2)
        up_frame.pack(fill=BOTH, expand=True, padx=12, pady=(4, 4))
        self._cards = self._scroll_area(up_frame)

        # ── Past concerts: compact read-only list, its own scroll ──
        done_frame = tk.LabelFrame(self, text=" Past Concerts (read-only) ",
                                   font=("Segoe UI", fs(10), "bold"),
                                   padx=4, pady=2, height=170)
        done_frame.pack(fill=X, padx=12, pady=(4, 8))
        done_frame.pack_propagate(False)
        self._done_rows = self._scroll_area(done_frame)

        self._past_dbs = {}
        self.refresh()
        # Pop a notification shortly after the tab is built if any reminder
        # stage has come due (2 weeks / 1 week / 2 days before a concert).
        self.after(800, self._notify_due)

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

    def _notify_due(self):
        try:
            due_list = []
            for c in self.db.get_concerts(self._year()):
                sent = {r["stage"] for r in
                        self.db.get_concert_reminders(c["id"]) if r["sent_date"]}
                due = ct.stages_due(c["concert_date"], sent)
                if ct.staff_due(c["concert_date"], sent):
                    due = ["staff/custodial"] + due
                if due:
                    due_list.append((dict(c), due))
        except Exception:
            return
        if not due_list:
            return

        win = ttk.Toplevel(self.winfo_toplevel())
        win.title("Concert Reminders Due")
        win.lift()
        win.attributes("-topmost", True)
        win.after(300, lambda: win.attributes("-topmost", False))
        ttk.Label(win, text="🔔  Concert reminders are due!",
                  font=("Segoe UI", 12, "bold"),
                  bootstyle=WARNING).pack(anchor=W, padx=18, pady=(14, 6))
        for c, due in due_list:
            when = ct.fmt_date(c.get("concert_date"))
            ttk.Label(win, text=f"•  {c['title']} ({when}) — "
                                f"{' + '.join(due)} reminder"
                                f"{'s' if len(due) > 1 else ''} ready to send",
                      font=("Segoe UI", 9), wraplength=420,
                      justify=LEFT).pack(anchor=W, padx=24, pady=1)
        ttk.Label(win, text="Each takes under a minute: copy the addresses, "
                            "copy the email template, send, mark sent.",
                  font=("Segoe UI", 8), foreground=muted_fg(),
                  wraplength=420, justify=LEFT).pack(anchor=W, padx=24, pady=(6, 0))

        first = due_list[0][0]

        def _open():
            win.destroy()
            self._reminders(first)

        btns = ttk.Frame(win)
        btns.pack(fill=X, padx=16, pady=12)
        ttk.Button(btns, text="Later", bootstyle=(SECONDARY, OUTLINE),
                   command=win.destroy).pack(side=RIGHT, padx=4)
        ttk.Button(btns, text="✉ Open Reminders…", bootstyle=WARNING,
                   command=_open).pack(side=RIGHT, padx=4)
        fit_window(win, 480, 240)

    # ── Context helpers ──────────────────────────────────────────────────────

    def _year(self):
        base = os.path.basename(self.db.db_path)
        if base.startswith("lesson_plans_") and base.endswith(".db"):
            return base[len("lesson_plans_"):-len(".db")]
        return None

    def _student_year(self):
        """Rosters follow the hub's selected school year, so a concert's
        program always uses that year's class assignments; fall back to the
        newest year that actually has students."""
        years = self.main_db.get_school_years()
        hub_year = self._year()
        if hub_year and hub_year in years:
            return hub_year
        return years[0] if years else None

    def _teacher(self):
        """(school_name, director_name) from Settings / the profile."""
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

    def _past_concerts(self):
        """(year, concert dict, that year's db) for every other school year
        on disk — shown read-only for reference and reuse."""
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
                for c in pdb.get_concerts():
                    out.append((y, dict(c), pdb))
            except Exception:
                continue
        out.sort(key=lambda x: (x[0], x[1].get("concert_date") or ""),
                 reverse=True)
        return out

    # ── Card overview ────────────────────────────────────────────────────────

    def refresh(self):
        for w in self._cards.winfo_children():
            w.destroy()
        for w in self._done_rows.winfo_children():
            w.destroy()
        concerts = [dict(c) for c in self.db.get_concerts(self._year())]

        def is_done(c):
            days = ct.days_until(c.get("concert_date"))
            return days is not None and days < 0

        upcoming = [c for c in concerts if not is_done(c)]
        completed = [c for c in concerts if is_done(c)]
        upcoming.sort(key=lambda c: (ct.parse_date(c.get("concert_date")) is None,
                                     ct.parse_date(c.get("concert_date"))
                                     or ct.parse_date("2999-01-01")))
        completed.sort(key=lambda c: c.get("concert_date") or "", reverse=True)

        if not upcoming:
            ttk.Label(self._cards, text="No upcoming concerts. Click "
                                        "“➕ New Concert” to plan one, or "
                                        "reuse a past concert below as a "
                                        "template.",
                      font=("Segoe UI", fs(10)), foreground=muted_fg()
                      ).pack(anchor=W, padx=8, pady=14)
        for c in upcoming:
            self._concert_card(c)

        # Past: this year's finished concerts, then previous years
        def done_row(label, opener):
            row = ttk.Frame(self._done_rows)
            row.pack(fill=X, padx=4, pady=1)
            ttk.Button(row, text=label, bootstyle=(SECONDARY, OUTLINE, LINK),
                       command=opener).pack(side=LEFT)

        year = self._year()
        for c in completed:
            loc = f", {c['location']}" if c.get("location") else ""
            done_row(f"✔ {c.get('concert_date')}  ·  {c.get('title')}{loc}",
                     lambda cc=c: _PastConcertDialog(self, year, dict(cc),
                                                     self.db))
        for pyear, c, pdb in self._past_concerts():
            loc = f", {c['location']}" if c.get("location") else ""
            done_row(f"🕰 {pyear}  ·  {c.get('title')}"
                     f"  ({c.get('concert_date') or 'no date'}{loc})",
                     lambda y=pyear, cc=c, p=pdb:
                     _PastConcertDialog(self, y, dict(cc), p))
        if not completed and not self._past_concerts():
            ttk.Label(self._done_rows, text="Past concerts will collect here "
                                            "for reference and reuse.",
                      font=("Segoe UI", fs(9)), foreground=muted_fg()
                      ).pack(anchor=W, padx=6, pady=6)

    def _concert_card(self, c):
        days = ct.days_until(c.get("concert_date"))
        when = (ct.fmt_date(c.get("concert_date"))
                if c.get("concert_date") else "no date yet")
        card = tk.LabelFrame(self._cards, text=f" {when}: {c['title']} ",
                             font=("Segoe UI", fs(11), "bold"),
                             padx=10, pady=6, bd=2, relief="groove")
        card.pack(fill=X, padx=6, pady=6)

        # ── Info line + countdown ──
        top = ttk.Frame(card)
        top.pack(fill=X)
        bits = []
        if c.get("location"):
            bits.append(f"@ {c['location']}" +
                        (" (off-site)" if c.get("offsite") else ""))
        if c.get("ensembles"):
            bits.append(c["ensembles"])
        st = (c.get("start_time") or "").strip()
        et = (c.get("end_time") or "").strip()
        if st or et:
            bits.append(f"{st or '?'} to {et or '?'}")
        n_pieces = len(self.db.get_concert_pieces(c["id"]))
        bits.append(f"{n_pieces} piece{'s' if n_pieces != 1 else ''} entered")
        ttk.Label(top, text="  ·  ".join(bits),
                  font=("Segoe UI", fs(9)), foreground=muted_fg()
                  ).pack(side=LEFT)
        if days is None:
            badge, style = "set a date", SECONDARY
        elif days == 0:
            badge, style = "TODAY!", DANGER
        elif days <= 14:
            badge, style = f"in {days} day{'s' if days != 1 else ''}", WARNING
        else:
            badge, style = f"in {days} days", SUCCESS
        ttk.Label(top, text=badge, font=("Segoe UI", fs(10), "bold"),
                  bootstyle=style).pack(side=RIGHT)

        # ── Checklist: left-click cycles, right-click marks N/A ──
        grid = ttk.Frame(card)
        grid.pack(fill=X, pady=(6, 2))
        for col in range(3):
            grid.columnconfigure(col, weight=1)

        def _item_label(state, label):
            if state == ct.CHECK_DONE:
                return f"☑  {label}", "#1a7a1a"
            if state == ct.CHECK_NA:
                return f"N/A  {label}", "#999999"
            return f"☐  {label}", "#B45309"

        def _cycle(key, concert_id=c["id"]):
            cur = int(self.db.get_concert(concert_id)[key] or 0)
            self.db.update_concert(concert_id, {key: (cur + 1) % 3})
            self.refresh()

        def _set_na(key, concert_id=c["id"]):
            cur = int(self.db.get_concert(concert_id)[key] or 0)
            new = ct.CHECK_TODO if cur == ct.CHECK_NA else ct.CHECK_NA
            self.db.update_concert(concert_id, {key: new})
            self.refresh()

        for i, (key, label) in enumerate(ct.CONCERT_CHECKLIST_ITEMS):
            state = int(c.get(key) or 0)
            text, color = _item_label(state, label)
            lbl = ttk.Label(grid, text=text, font=("Segoe UI", fs(9)),
                            foreground=color, cursor="hand2")
            lbl.grid(row=i // 3, column=i % 3, sticky=W, padx=(0, 12), pady=1)
            lbl.bind("<Button-1>", lambda e, k=key: _cycle(k))
            lbl.bind("<Button-3>", lambda e, k=key: _set_na(k))
        # Derived item: repertoire entered (auto from the pieces list)
        text, color = _item_label(
            ct.CHECK_DONE if n_pieces else ct.CHECK_TODO, "Repertoire entered")
        ttk.Label(grid, text=text + "  (auto)", font=("Segoe UI", fs(9)),
                  foreground=color).grid(row=2, column=0, sticky=W,
                                         padx=(0, 12), pady=1)

        # ── Reminders summary ──
        sent = {r["stage"] for r in self.db.get_concert_reminders(c["id"])
                if r["sent_date"]}
        due = ct.stages_due(c.get("concert_date"), sent)
        staff_due = ct.staff_due(c.get("concert_date"), sent)
        rbits = []
        d14 = dict(ct.reminder_schedule(c.get("concert_date"))).get("2 weeks")
        if ct.STAFF_STAGE_KEY in sent:
            rbits.append("✓ staff/custodial")
        elif staff_due:
            rbits.append("⚠ staff/custodial due")
        elif d14:
            rbits.append(f"staff/custodial on {d14.month}/{d14.day}")
        else:
            rbits.append("staff/custodial (set a date)")
        for label, due_date in ct.reminder_schedule(c.get("concert_date")):
            if label in sent:
                rbits.append(f"✓ {label}")
            elif label in due:
                rbits.append(f"⚠ {label} due")
            elif due_date:
                rbits.append(f"{label} on {due_date.month}/{due_date.day}")
            else:
                rbits.append(f"{label} (set a date)")
        ttk.Label(card, text="Reminders:  " + "   ·   ".join(rbits),
                  font=("Segoe UI", fs(9)),
                  foreground="#B45309" if (due or staff_due) else muted_fg()
                  ).pack(anchor=W, pady=(2, 2))

        # ── Actions ──
        btns = ttk.Frame(card)
        btns.pack(fill=X, pady=(2, 0))
        ttk.Button(btns, text="✏ Edit", bootstyle=(PRIMARY, OUTLINE),
                   command=lambda cc=c: self._edit_concert(cc)
                   ).pack(side=LEFT, padx=(0, 4))
        ttk.Button(btns, text="🎼 Repertoire", bootstyle=(PRIMARY, OUTLINE),
                   command=lambda cc=c: self._repertoire(cc)).pack(side=LEFT, padx=4)
        ttk.Button(btns, text="🎖 Honors", bootstyle=(SECONDARY, OUTLINE),
                   command=lambda cc=c: self._honors(cc)).pack(side=LEFT, padx=4)
        ttk.Button(btns, text="📄 Details Page", bootstyle=(INFO, OUTLINE),
                   command=lambda cc=c: self._details(cc)).pack(side=LEFT, padx=4)
        ttk.Button(btns, text="📖 Program (.pub)", bootstyle=(SUCCESS, OUTLINE),
                   command=lambda cc=c: self._program(cc)).pack(side=LEFT, padx=4)
        ttk.Button(btns, text="✉ Reminders", bootstyle=(WARNING, OUTLINE),
                   command=lambda cc=c: self._reminders(cc)).pack(side=LEFT, padx=4)
        ttk.Button(btns, text="🗑", bootstyle=(DANGER, OUTLINE), width=3,
                   command=lambda cc=c: self._delete_concert(cc)).pack(side=RIGHT)

    # ── Create / edit / delete ───────────────────────────────────────────────

    def _new_concert(self, template=None):
        # New concerts start from the previous one — attire, acknowledgements,
        # and arrival barely change between cycles.
        prev = None
        existing = self.db.get_concerts(self._year()) or self.db.get_concerts()
        if existing:
            prev = existing[-1]
        school, _ = self._teacher()
        polo = f"{school or 'School'} music polo"
        default_plan = (
            "1:20-2:30pm | Set up the gym — volunteers appreciated!\n"
            "2:00pm-6:15pm | Go home. DO HOMEWORK. Eat a healthy dinner. Change clothes.\n"
            "6:15pm-6:25pm | Arrive, get your instrument out. Leave your case & "
            "belongings in your locker — take your music with you!\n"
            "6:25pm | ALL musicians in the gym. Do not play yet.\n"
            "6:30pm-8:00pm | Concert! Please stay to listen for each other.\n"
            "8:00pm | Return all chairs/stands/percussion — everyone carries one thing back!")
        seed = {
            "attire": (prev["attire"] if prev and prev["attire"] else
                       f"{polo}\nBlack pants/long black skirt\nBlack socks\nBlack shoes"),
            "acknowledgements": prev["acknowledgements"] if prev else "",
            "upcoming": prev["upcoming"] if prev else "",
            "arrival": prev["arrival"] if prev else "",
            "setup": (prev["setup"] if prev and "setup" in prev.keys() else ""),
            "seated_by": (prev["seated_by"]
                          if prev and "seated_by" in prev.keys() else ""),
            "itinerary": (prev["itinerary"] if prev and prev["itinerary"]
                          else default_plan),
            "directors": self._teacher()[1],
        }
        if template:
            seed.update(template)
        dlg = _ConcertDialog(self, seed=seed, program_type=self._program_type())
        self.wait_window(dlg)
        if dlg.result:
            # A template contributes what the dialog doesn't show (e.g.
            # special guests); the dialog's fields win.
            data = dict(template) if template else {}
            data.update(dlg.result)
            data["school_year"] = self._year()
            self.db.add_concert(data)
            self.refresh()

    def _edit_concert(self, c):
        dlg = _ConcertDialog(self, seed=dict(c),
                             program_type=self._program_type(), editing=True)
        self.wait_window(dlg)
        if dlg.result:
            self.db.update_concert(c["id"], dlg.result)
            self.refresh()

    def _delete_concert(self, c):
        if Messagebox.yesno(f"Delete “{c['title']}” and its repertoire list?\n"
                            "This can't be undone.",
                            title="Delete Concert",
                            parent=self.winfo_toplevel()) != "Yes":
            return
        self.db.delete_concert(c["id"])
        self.refresh()

    # ── Tools ────────────────────────────────────────────────────────────────

    def _repertoire(self, c):
        dlg = _RepertoireDialog(self, self.db, dict(c))
        self.wait_window(dlg)
        self.refresh()

    def _honors(self, c):
        dlg = _HonorsDialog(self, self.main_db, self._students(),
                            ct.ensembles_list(c))
        self.wait_window(dlg)

    def _details(self, c):
        dlg = _DetailsDialog(self, dict(c), self._teacher()[0])
        self.wait_window(dlg)

    def _reminders(self, c):
        dlg = _RemindersDialog(self, self.db, dict(c), self._students(),
                               self._teacher())
        self.wait_window(dlg)
        self.refresh()

    def _program(self, c):
        concert = dict(c)
        ensembles = ct.ensembles_list(concert)
        if not ensembles:
            Messagebox.show_warning("Add the ensembles involved first (Edit).",
                                    title="No Ensembles",
                                    parent=self.winfo_toplevel())
            return

        # Performance order decides program order when given
        order = [e.strip() for e in (concert.get("perf_order") or "").split(",")
                 if e.strip()]
        ordered = [e for e in order if e in ensembles] + \
                  [e for e in ensembles if e not in order]

        # Pre-fill the builder.  Acknowledgements: this concert's saved list,
        # else the LAST list used anywhere (they barely change between
        # concerts).  Upcoming: auto-built from the planner (past events and
        # this concert itself can never appear) plus saved extras.
        school, director = self._teacher()
        prefill = {
            "directors": (concert.get("directors") or "").strip() or director,
            "special_guests": concert.get("special_guests") or "",
            "acknowledgements": (concert.get("acknowledgements") or "").strip()
                                or self.db.get_program_setting("acknowledgements"),
            "upcoming": "\n".join(ct.merged_upcoming(
                [dict(x) for x in self.db.get_concerts(self._year())], concert)),
            "extra_info": concert.get("extra_info") or "",
        }
        opts = self._program_options(prefill)
        if not opts:
            return

        # EVERYTHING in the builder is saved back to the concert, so
        # regenerating the program starts from what you had last time; the
        # acknowledgements also become the default for the next concert.
        self.db.update_concert(concert["id"], {
            "directors": opts["directors"],
            "special_guests": opts["special_guests"],
            "acknowledgements": opts["acknowledgements"],
            "upcoming": opts["upcoming"],
            "extra_info": opts["extra_info"],
        })
        if opts["acknowledgements"].strip():
            self.db.set_program_setting("acknowledgements",
                                        opts["acknowledgements"])
        concert.update(opts)

        pieces = {}
        for e in ordered:
            pieces[e] = [dict(p) for p in
                         self.db.get_concert_pieces(concert["id"], e)]
        students = self._students()
        personnel = {}
        for e in ordered:
            sections = ct.personnel_sections(students, e)
            if sections:
                personnel[e] = sections

        path = filedialog.asksaveasfilename(
            parent=self.winfo_toplevel(), defaultextension=".pub",
            initialfile=_default_filename(concert),
            filetypes=[("Publisher files", "*.pub")])
        if not path:
            return

        folded = opts["layout"] == "folded"
        fmt = "folded booklet, 5.5×8.5\" pages" if folded else "full page 8.5×11\""
        note = f"Format: {fmt}"
        if folded:
            note += ("\nOpening from here pre-selects “Booklet, side-fold” "
                     "printing. If you open the file later on its own, pick "
                     "“Booklet, side-fold” in the Print settings.")
        from concert_program_pub import PRINT_BOOKLET_SIDE_FOLD
        self._run_publisher(
            f"Building the {fmt} program in Microsoft Publisher…",
            lambda: __import__("concert_program_pub").build_program_pub(
                path, concert, pieces, personnel,
                school_name=school, director=director,
                layout=opts["layout"]),
            path, done_note=note,
            open_style=PRINT_BOOKLET_SIDE_FOLD if folded else None)

    def _program_options(self, prefill):
        """The Program Builder: format choice plus every fillable text block
        that prints on the program, pre-filled and editable in one place."""
        win = ttk.Toplevel(self.winfo_toplevel())
        win.title("Build Program")
        win.resizable(True, True)
        win.grab_set()

        btns = ttk.Frame(win)
        btns.pack(fill=X, side=BOTTOM, padx=16, pady=10)

        ttk.Label(win, text="📖  Build Program", font=("Segoe UI", 12, "bold"),
                  bootstyle=PRIMARY).pack(anchor=W, padx=16, pady=(12, 4))

        # Scrollable body — this window carries several text blocks
        wrap = ttk.Frame(win)
        wrap.pack(fill=BOTH, expand=True, padx=12)
        canvas = tk.Canvas(wrap, highlightthickness=0)
        sb = ttk.Scrollbar(wrap, orient=VERTICAL, command=canvas.yview)
        body = ttk.Frame(canvas)
        body.bind("<Configure>",
                  lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        cw = canvas.create_window((0, 0), window=body, anchor="nw")
        canvas.bind("<Configure>",
                    lambda e: canvas.itemconfigure(cw, width=e.width))
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side=LEFT, fill=BOTH, expand=True)
        sb.pack(side=RIGHT, fill=Y)
        canvas.bind_all("<MouseWheel>",
                        lambda e: canvas.yview_scroll(-1 * (e.delta // 120),
                                                      "units"))

        # ── Format ──
        ttk.Label(body, text="Format", font=("Segoe UI", 9, "bold")
                  ).pack(anchor=W, pady=(4, 0))
        layout_var = tk.StringVar(value=self.db.get_program_setting(
            "program_layout", "full"))
        ttk.Radiobutton(body, text="Full page — 8.5×11\"  (print "
                                   "front-to-back and staple)",
                        value="full", variable=layout_var,
                        bootstyle=PRIMARY).pack(anchor=W, padx=8)
        ttk.Radiobutton(body, text="Folded booklet — 5.5×8.5\" pages  (print "
                                   "with Publisher's “Booklet, side-fold”)",
                        value="folded", variable=layout_var,
                        bootstyle=PRIMARY).pack(anchor=W, padx=8)

        def entry(label, key, hint=""):
            ttk.Label(body, text=label, font=("Segoe UI", 9, "bold")
                      ).pack(anchor=W, pady=(10, 0))
            if hint:
                ttk.Label(body, text=hint, font=("Segoe UI", 8),
                          foreground=muted_fg(), wraplength=520,
                          justify=LEFT).pack(anchor=W)
            v = tk.StringVar(value=prefill.get(key, ""))
            ttk.Entry(body, textvariable=v).pack(anchor=W, fill=X, padx=(0, 8))
            return v

        def text(label, key, height, hint=""):
            ttk.Label(body, text=label, font=("Segoe UI", 9, "bold")
                      ).pack(anchor=W, pady=(10, 0))
            if hint:
                ttk.Label(body, text=hint, font=("Segoe UI", 8),
                          foreground=muted_fg(), wraplength=520,
                          justify=LEFT).pack(anchor=W)
            t = tk.Text(body, height=height, font=("Segoe UI", 9),
                        relief="solid", bd=1, wrap=WORD)
            t.insert("1.0", prefill.get(key, ""))
            t.pack(anchor=W, fill=X, padx=(0, 8))
            return t

        dir_var = entry("Director(s)", "directors",
                        hint="Printed on the cover — add guest directors "
                             "(e.g. the 5th grade band directors in March).")
        guest_var = entry("Special guests (optional)", "special_guests",
                          hint="Also printed on the cover — e.g. "
                               "Cherry Crest • Clyde Hill • Enatai")
        ack_t = text("Acknowledgements", "acknowledgements", 7,
                     hint="One per line: principal, vice principal(s), the "
                          "other music teachers (choir/orchestra directors), "
                          "custodial staff, PTSA, Bellevue Schools Foundation, "
                          "music boosters, paras/student teachers/section "
                          "coaches, and families. Pre-filled from the last "
                          "list you used; edits here are saved automatically.")
        upc_t = text("Upcoming Performances", "upcoming", 5,
                     hint="Auto-filled from the other concerts in this "
                          "planner — anything already past is dropped. Add "
                          "or trim freely; edits are saved for next time.")
        extra_t = text("Additional info (optional)", "extra_info", 6,
                       hint="Registration / recruiting blurbs, class "
                            "descriptions, testimonials — printed on its own "
                            "page at the back. First line becomes the heading.")

        out = {"v": None}

        def _ok():
            out["v"] = {
                "layout": layout_var.get(),
                "directors": dir_var.get().strip(),
                "special_guests": guest_var.get().strip(),
                "acknowledgements": ack_t.get("1.0", "end").strip(),
                "upcoming": upc_t.get("1.0", "end").strip(),
                "extra_info": extra_t.get("1.0", "end").strip(),
            }
            self.db.set_program_setting("program_layout", out["v"]["layout"])
            win.destroy()

        ttk.Button(btns, text="Cancel", bootstyle=(SECONDARY, OUTLINE),
                   command=win.destroy).pack(side=RIGHT, padx=4)
        ttk.Button(btns, text="Continue → Save As…", bootstyle=SUCCESS,
                   command=_ok).pack(side=RIGHT, padx=4)
        fit_window(win, 600, 720)
        self.wait_window(win)
        return out["v"]

    def _run_publisher(self, message, job, path, done_note="", open_style=None):
        """Run a Publisher COM job in a worker thread with a small progress
        window (Publisher takes a few seconds to start).  open_style: print
        style to pre-select when the user opens the result (booklet fold)."""
        win = ttk.Toplevel(self.winfo_toplevel())
        win.title("Working…")
        win.grab_set()
        ttk.Label(win, text=message, font=("Segoe UI", 10)).pack(padx=24, pady=(18, 8))
        pbar = ttk.Progressbar(win, mode="indeterminate", length=280,
                               bootstyle=SUCCESS)
        pbar.pack(padx=24, pady=(0, 18))
        pbar.start(12)
        fit_window(win, 340, 120)

        def work():
            try:
                job()
                err = None
            except Exception as e:
                err = str(e)

            def done():
                try:
                    win.destroy()
                except Exception:
                    pass
                if err:
                    Messagebox.show_error(
                        f"Couldn't create the Publisher file:\n{err}",
                        title="Publisher Error", parent=self.winfo_toplevel())
                else:
                    note = f"\n{done_note}" if done_note else ""
                    if Messagebox.yesno(
                            f"Saved:\n{path}{note}\n\nOpen it in Publisher now?",
                            title="Done", parent=self.winfo_toplevel()) == "Yes":
                        def _open():
                            try:
                                from concert_program_pub import open_pub
                                open_pub(path, open_style)
                            except Exception:
                                try:
                                    os.startfile(path)
                                except Exception:
                                    pass
                        threading.Thread(target=_open, daemon=True).start()
            self.after(0, done)
        threading.Thread(target=work, daemon=True).start()


# ═══════════════════════════════════════════ Past-concert viewer ═════════════

class _PastConcertDialog(ttk.Toplevel):
    """Read-only look at a finished concert — when, where, who played what —
    with one button to reuse it all as the template for the next one."""

    def __init__(self, parent_view, year, concert, pdb):
        super().__init__(parent_view.winfo_toplevel())
        self.view = parent_view
        self.concert = concert
        self.title(f"{concert.get('title')} — {year} (read-only)")
        self.resizable(True, True)
        self.grab_set()

        ttk.Label(self, text=f"🕰  {concert.get('title')} — {year}",
                  font=("Segoe UI", 12, "bold"),
                  bootstyle=PRIMARY).pack(anchor=W, padx=16, pady=(12, 0))
        ttk.Label(self, text="Read-only — this concert has already happened.",
                  font=("Segoe UI", 8), foreground=muted_fg()).pack(anchor=W, padx=16)

        lines = []
        when = ct.fmt_date(concert.get("concert_date"))
        st = (concert.get("start_time") or "").strip()
        et = (concert.get("end_time") or "").strip()
        time_bit = f", {st}" + (f"-{et}" if et else "") if st else ""
        lines.append(f"When: {when}{time_bit}")
        if concert.get("location"):
            lines.append(f"Location: {concert['location']}"
                         + ("  (off-site)" if concert.get("offsite") else ""))
        if concert.get("ensembles"):
            lines.append(f"Ensembles: {concert['ensembles']}")
        if (concert.get("directors") or "").strip():
            lines.append(f"Directors: {concert['directors']}")
        if (concert.get("special_guests") or "").strip():
            lines.append(f"Special guests: {concert['special_guests']}")

        pieces = [dict(p) for p in pdb.get_concert_pieces(concert["id"])] if pdb else []
        if pieces:
            lines.append("")
            lines.append("Program:")
            by_ens = {}
            for p in pieces:
                by_ens.setdefault(p.get("ensemble") or "", []).append(p)
            order = [e.strip() for e in
                     (concert.get("perf_order") or "").split(",") if e.strip()]
            ens_names = [e for e in order if e in by_ens] + \
                        [e for e in by_ens if e not in order]
            for e in ens_names:
                lines.append(f"  {e}:")
                for p in by_ens[e]:
                    credit = (p.get("composer") or "").strip()
                    if (p.get("arranger") or "").strip():
                        credit = (credit + ", " if credit else "") + \
                                 f"arr. {p['arranger'].strip()}"
                    lines.append(f"    {p['title']}"
                                 + (f"  ({credit})" if credit else ""))
        if (concert.get("attire") or "").strip():
            lines.append("")
            lines.append("Attire:")
            for a in concert["attire"].splitlines():
                lines.append(f"  {a}")
        if (concert.get("notes") or "").strip():
            lines.append("")
            lines.append("Notes:")
            lines.append(concert["notes"])

        box = tk.Text(self, font=("Calibri", 11), width=72, height=18,
                      relief="solid", bd=1, wrap=WORD)
        box.insert("1.0", "\n".join(lines))
        box.config(state="disabled")
        box.pack(fill=BOTH, expand=True, padx=16, pady=8)

        btns = ttk.Frame(self)
        btns.pack(fill=X, padx=16, pady=12)
        ttk.Button(btns, text="Close", bootstyle=(SECONDARY, OUTLINE),
                   command=self.destroy).pack(side=RIGHT, padx=4)
        ttk.Button(btns, text="📋 Use as Template for a New Concert…",
                   bootstyle=SUCCESS, command=self._reuse).pack(side=RIGHT, padx=4)
        fit_window(self, 620, 600)

    def _reuse(self):
        template = ct.concert_template(self.concert)
        self.destroy()
        self.view._new_concert(template=template)


# ═══════════════════════════════════════════ Concert editor ══════════════════

class _ConcertDialog(ttk.Toplevel):
    """Everything about one concert, in three small tabs."""

    def __init__(self, parent, seed=None, program_type="band", editing=False):
        super().__init__(parent.winfo_toplevel())
        self.result = None
        seed = seed or {}
        self.title("Edit Concert" if editing else "New Concert")
        self.resizable(True, True)
        self.grab_set()

        ttk.Label(self, text="✏  Concert" if editing else "➕  New Concert",
                  font=("Segoe UI", 12, "bold"),
                  bootstyle=PRIMARY).pack(anchor=W, padx=16, pady=(12, 4))

        btns = ttk.Frame(self)
        btns.pack(fill=X, side=BOTTOM, padx=16, pady=10)
        ttk.Button(btns, text="Cancel", bootstyle=(SECONDARY, OUTLINE),
                   command=self.destroy).pack(side=RIGHT, padx=4)
        ttk.Button(btns, text="Save", bootstyle=SUCCESS,
                   command=self._save).pack(side=RIGHT, padx=4)

        nb = ttk.Notebook(self, bootstyle=PRIMARY)
        nb.pack(fill=BOTH, expand=True, padx=12, pady=6)
        basics = ttk.Frame(nb, padding=10)
        family = ttk.Frame(nb, padding=10)
        program = ttk.Frame(nb, padding=10)
        checklist = ttk.Frame(nb, padding=10)
        nb.add(basics, text="  Basics  ")
        nb.add(family, text="  Family Details  ")
        nb.add(program, text="  Program Extras  ")
        nb.add(checklist, text="  Checklist  ")

        self._vars = {}

        def entry(parent, label, key, width=30, hint=""):
            ttk.Label(parent, text=label, font=("Segoe UI", 9, "bold")
                      ).pack(anchor=W, pady=(6, 0))
            if hint:
                ttk.Label(parent, text=hint, font=("Segoe UI", 8),
                          foreground=muted_fg()).pack(anchor=W)
            v = tk.StringVar(value=str(seed.get(key) or ""))
            self._vars[key] = v
            ttk.Entry(parent, textvariable=v, width=width).pack(anchor=W)
            return v

        def text(parent, label, key, height=4, hint=""):
            ttk.Label(parent, text=label, font=("Segoe UI", 9, "bold")
                      ).pack(anchor=W, pady=(6, 0))
            if hint:
                ttk.Label(parent, text=hint, font=("Segoe UI", 8),
                          foreground=muted_fg(), wraplength=520,
                          justify=LEFT).pack(anchor=W)
            t = tk.Text(parent, height=height, width=64, font=("Segoe UI", 9),
                        relief="solid", bd=1, wrap=WORD)
            t.insert("1.0", str(seed.get(key) or ""))
            t.pack(anchor=W, fill=X)
            self._texts[key] = t

        self._texts = {}

        # ── Basics ──
        entry(basics, "Concert title", "title", width=44)
        row = ttk.Frame(basics); row.pack(fill=X)
        left = ttk.Frame(row); left.pack(side=LEFT, padx=(0, 18))
        right = ttk.Frame(row); right.pack(side=LEFT)
        ttk.Label(left, text="Date (YYYY-MM-DD)", font=("Segoe UI", 9, "bold")
                  ).pack(anchor=W, pady=(6, 0))
        v = tk.StringVar(value=str(seed.get("concert_date") or ""))
        self._vars["concert_date"] = v
        ttk.Entry(left, textvariable=v, width=14).pack(anchor=W)
        ttk.Label(right, text="Start / end time", font=("Segoe UI", 9, "bold")
                  ).pack(anchor=W, pady=(6, 0))
        tr = ttk.Frame(right); tr.pack(anchor=W)
        v1 = tk.StringVar(value=str(seed.get("start_time") or ""))
        v2 = tk.StringVar(value=str(seed.get("end_time") or ""))
        self._vars["start_time"], self._vars["end_time"] = v1, v2
        ttk.Entry(tr, textvariable=v1, width=10).pack(side=LEFT)
        ttk.Label(tr, text=" to ").pack(side=LEFT)
        ttk.Entry(tr, textvariable=v2, width=10).pack(side=LEFT)

        entry(basics, "Location", "location", width=44)
        self._offsite = tk.BooleanVar(value=bool(seed.get("offsite")))
        ttk.Checkbutton(basics, text="Off-site event (bus trip, festival, "
                                     "another school…)",
                        variable=self._offsite, bootstyle=PRIMARY
                        ).pack(anchor=W, pady=(6, 0))

        # Ensembles: standard ones as checkboxes + free-text extras
        ttk.Label(basics, text="Ensembles performing",
                  font=("Segoe UI", 9, "bold")).pack(anchor=W, pady=(10, 2))
        from ui.ensembles import ensembles_for
        std = ensembles_for(program_type)
        chosen = set(ct.ensembles_list(seed))
        self._ens_vars = {}
        grid = ttk.Frame(basics); grid.pack(anchor=W)
        for i, e in enumerate(std):
            bv = tk.BooleanVar(value=e in chosen)
            self._ens_vars[e] = bv
            ttk.Checkbutton(grid, text=e, variable=bv, bootstyle=PRIMARY
                            ).grid(row=i // 3, column=i % 3, sticky=W,
                                   padx=(0, 14), pady=2)
        extras = [e for e in chosen if e not in std]
        ttk.Label(basics, text="Other groups (comma-separated — e.g. "
                               "Heavy Metal, 5th Grade Bands, Adv Orchestra)",
                  font=("Segoe UI", 8), foreground=muted_fg()).pack(anchor=W, pady=(4, 0))
        self._extra_ens = tk.StringVar(value=", ".join(extras))
        ttk.Entry(basics, textvariable=self._extra_ens, width=54).pack(anchor=W)

        entry(basics, "Performance order", "perf_order", width=54,
              hint="Comma-separated, first to last — also sets program order.")

        entry(basics, "Director(s)", "directors", width=54,
              hint="Printed on the program cover — add guest directors when "
                   "needed (e.g. the 5th grade band directors in March).")

        # ── Family details ──
        entry(family, "Set-up (when / how)", "setup", width=54,
              hint="e.g. 1:20-2:30pm — volunteers set up the main gym ASAP.")
        entry(family, "Student arrival", "arrival", width=44,
              hint="e.g. 6:15pm-6:25pm — this is “early”.  Copied into "
                   "reminder emails automatically.")
        entry(family, "Everyone seated in the venue by", "seated_by", width=24,
              hint="e.g. 6:25pm — in the gym, do not play yet.")
        text(family, "What to wear", "attire", height=4,
             hint="One item per line.")
        text(family, "What to bring (off-site)", "bring", height=3,
             hint="One item per line — instrument extras, sheet music, lunch money…")
        text(family, "Required rehearsals (Tutorial / Activity)", "rehearsals",
             height=3, hint="One per line, e.g.  Thurs, May 28: Entry Band")
        text(family, "The Plan — itinerary for the day", "itinerary", height=8,
             hint="One step per line as  time | what happens.  Include set-up, "
                  "when students arrive, what to leave in the band room, bus "
                  "departure/return for off-site events, and teardown — e.g.\n"
                  "6:15pm | Arrive at school, get your instrument out")

        # ── Program extras ──
        text(program, "Acknowledgements", "acknowledgements", height=7,
             hint="One per line: principal, vice principal(s), the other music "
                  "teachers, custodial staff, PTSA, Bellevue Schools "
                  "Foundation, boosters, paras/student teachers/section "
                  "coaches, and families. The Program Builder pre-fills this "
                  "from your last concert automatically, so you'll rarely "
                  "start from scratch.")
        text(program, "Additional program info (optional)", "extra_info",
             height=6,
             hint="Recruiting blurbs, class descriptions, registration info, "
                  "testimonials… Printed on its own page at the back of the "
                  "program. The first line becomes the heading; leave a blank "
                  "line between paragraphs. Bold specific words in Publisher "
                  "afterward if you like.")
        text(program, "Extra upcoming events (optional)", "upcoming", height=4,
             hint="Concerts you've entered in this planner are added to "
                  "“Upcoming Performances” automatically, and anything already "
                  "past is dropped. Use this box only for events that aren't "
                  "in the planner (festivals, S&E, field trips).")
        text(program, "Notes (private — not printed)", "notes", height=3)

        # ── Checklist ──
        ttk.Label(checklist, text="Concert prep checklist",
                  font=("Segoe UI", 9, "bold")).pack(anchor=W)
        ttk.Label(checklist, text="Click an item to cycle:  ☐ to do → ☑ done "
                                  "→ N/A; right-click to mark it N/A right "
                                  "away (e.g. no tutorials needed for a "
                                  "festival). The checklist also shows on the "
                                  "concert's card in the planner, where each "
                                  "item is one click away.",
                  font=("Segoe UI", 8), foreground=muted_fg(),
                  wraplength=560, justify=LEFT).pack(anchor=W, pady=(0, 6))
        self._check_states = {}
        cgrid = ttk.Frame(checklist)
        cgrid.pack(anchor=W, fill=X)
        cgrid.columnconfigure(0, weight=1)
        cgrid.columnconfigure(1, weight=1)

        def _make_item(idx, key, label):
            self._check_states[key] = int(seed.get(key) or 0)
            btn = ttk.Button(cgrid)

            def render():
                s = self._check_states[key]
                if s == ct.CHECK_DONE:
                    btn.config(text=f"☑  {label}", bootstyle=SUCCESS)
                elif s == ct.CHECK_NA:
                    btn.config(text=f"N/A  {label}", bootstyle=SECONDARY)
                else:
                    btn.config(text=f"☐  {label}",
                               bootstyle=(SECONDARY, OUTLINE))

            def cycle():
                self._check_states[key] = (self._check_states[key] + 1) % 3
                render()

            def set_na(_e=None):
                s = self._check_states[key]
                self._check_states[key] = (ct.CHECK_TODO if s == ct.CHECK_NA
                                           else ct.CHECK_NA)
                render()

            btn.config(command=cycle)
            btn.bind("<Button-3>", set_na)
            render()
            btn.grid(row=idx // 2, column=idx % 2, sticky="ew",
                     padx=(0, 8), pady=2)

        for i, (key, label) in enumerate(ct.CONCERT_CHECKLIST_ITEMS):
            _make_item(i, key, label)

        fit_window(self, 640, 660)

    def _save(self):
        title = self._vars["title"].get().strip()
        if not title:
            Messagebox.show_warning("Give the concert a title.",
                                    title="Missing Title", parent=self)
            return
        date = self._vars["concert_date"].get().strip()
        if date and not ct.parse_date(date):
            Messagebox.show_warning("The date must be YYYY-MM-DD "
                                    "(e.g. 2026-06-03).",
                                    title="Check the Date", parent=self)
            return
        ens = [e for e, bv in self._ens_vars.items() if bv.get()]
        ens += [x.strip() for x in self._extra_ens.get().split(",") if x.strip()]
        data = {k: v.get().strip() for k, v in self._vars.items()}
        data.update({k: t.get("1.0", "end").strip()
                     for k, t in self._texts.items()})
        data["ensembles"] = ", ".join(ens)
        data["offsite"] = 1 if self._offsite.get() else 0
        for key, _label in ct.CONCERT_CHECKLIST_ITEMS:
            data[key] = self._check_states[key]
        # Dec/Mar/Jun home concerts: two required tutorials each for Entry and
        # Intermediate Band.  Auto-fill the skeleton so it can't be forgotten.
        if not data.get("rehearsals") and ct.needs_tutorial_template(
                data.get("concert_date"), data["ensembles"]):
            data["rehearsals"] = ct.TUTORIAL_TEMPLATE
        self.result = data
        self.destroy()


# ═══════════════════════════════════════════ Repertoire ══════════════════════

class _RepertoireDialog(ttk.Toplevel):
    """Pieces per ensemble — add, revise, remove, reorder as the cycle
    progresses.  Empty is fine early in the cycle."""

    def __init__(self, parent, db, concert):
        super().__init__(parent.winfo_toplevel())
        self.db = db
        self.concert = concert
        self.title(f"Repertoire — {concert['title']}")
        self.resizable(True, True)
        self.grab_set()

        ttk.Label(self, text=f"🎼  Repertoire — {concert['title']}",
                  font=("Segoe UI", 12, "bold"),
                  bootstyle=PRIMARY).pack(anchor=W, padx=16, pady=(12, 2))
        ttk.Label(self, text="Pieces can be added, revised, or removed any "
                             "time — the printed program always uses the "
                             "current list.",
                  font=("Segoe UI", 8), foreground=muted_fg()).pack(anchor=W, padx=16)

        bar = ttk.Frame(self)
        bar.pack(fill=X, padx=16, pady=(8, 4))
        ttk.Label(bar, text="Ensemble:", font=("Segoe UI", 9, "bold")).pack(side=LEFT)
        self._ens_var = tk.StringVar()
        ens = ct.ensembles_list(concert) or ["(none set)"]
        self._combo = ttk.Combobox(bar, textvariable=self._ens_var, values=ens,
                                   state="readonly", width=26)
        self._combo.pack(side=LEFT, padx=8)
        self._combo.current(0)
        self._combo.bind("<<ComboboxSelected>>", lambda e: self._reload())

        body = ttk.Frame(self)
        body.pack(fill=BOTH, expand=True, padx=16, pady=4)
        self._list = tk.Listbox(body, font=("Segoe UI", 10), height=10)
        self._list.pack(side=LEFT, fill=BOTH, expand=True)
        side = ttk.Frame(body)
        side.pack(side=LEFT, fill=Y, padx=(8, 0))
        for label, cmd in [("▲", self._up), ("▼", self._down),
                           ("✏ Edit", self._edit), ("🗑 Remove", self._remove)]:
            ttk.Button(side, text=label, bootstyle=(SECONDARY, OUTLINE),
                       command=cmd, width=9).pack(pady=2)

        add = tk.LabelFrame(self, text=" Add / edit piece ",
                            font=("Segoe UI", 9, "bold"), padx=10, pady=6)
        add.pack(fill=X, padx=16, pady=(6, 4))
        self._piece_vars = {}
        row = ttk.Frame(add); row.pack(fill=X)
        for label, key, w in [("Title", "title", 30), ("Composer", "composer", 18),
                              ("Arranger", "arranger", 16)]:
            col = ttk.Frame(row); col.pack(side=LEFT, padx=(0, 8))
            ttk.Label(col, text=label, font=("Segoe UI", 8, "bold")).pack(anchor=W)
            v = tk.StringVar()
            self._piece_vars[key] = v
            ttk.Entry(col, textvariable=v, width=w).pack(anchor=W)
        self._editing_id = None
        self._add_btn = ttk.Button(add, text="➕ Add Piece", bootstyle=SUCCESS,
                                   command=self._add_or_save)
        self._add_btn.pack(anchor=E, pady=(6, 0))

        ttk.Button(self, text="Close", bootstyle=(SECONDARY, OUTLINE),
                   command=self.destroy).pack(pady=(4, 12))
        self._reload()
        fit_window(self, 640, 520)

    def _pieces(self):
        return [dict(p) for p in self.db.get_concert_pieces(
            self.concert["id"], self._ens_var.get())]

    def _reload(self):
        self._list.delete(0, END)
        for p in self._pieces():
            credit = (p.get("composer") or "").strip()
            if (p.get("arranger") or "").strip():
                credit = (credit + ", " if credit else "") + f"arr. {p['arranger'].strip()}"
            self._list.insert(END, f"{p['title']}" + (f"  —  {credit}" if credit else ""))
        self._editing_id = None
        self._add_btn.config(text="➕ Add Piece")
        for v in self._piece_vars.values():
            v.set("")

    def _sel_piece(self):
        sel = self._list.curselection()
        if not sel:
            return None
        return self._pieces()[sel[0]]

    def _add_or_save(self):
        title = self._piece_vars["title"].get().strip()
        if not title:
            return
        data = {"title": title,
                "composer": self._piece_vars["composer"].get().strip(),
                "arranger": self._piece_vars["arranger"].get().strip()}
        if self._editing_id:
            self.db.update_concert_piece(self._editing_id, data)
        else:
            data.update({"concert_id": self.concert["id"],
                         "ensemble": self._ens_var.get(),
                         "position": len(self._pieces())})
            self.db.add_concert_piece(data)
        self._reload()

    def _edit(self):
        p = self._sel_piece()
        if not p:
            return
        self._editing_id = p["id"]
        for key in ("title", "composer", "arranger"):
            self._piece_vars[key].set(p.get(key) or "")
        self._add_btn.config(text="💾 Save Changes")

    def _remove(self):
        p = self._sel_piece()
        if not p:
            return
        self.db.delete_concert_piece(p["id"])
        self._renumber()
        self._reload()

    def _move(self, delta):
        sel = self._list.curselection()
        if not sel:
            return
        i = sel[0]
        pieces = self._pieces()
        j = i + delta
        if j < 0 or j >= len(pieces):
            return
        pieces[i], pieces[j] = pieces[j], pieces[i]
        for pos, p in enumerate(pieces):
            self.db.update_concert_piece(p["id"], {"position": pos})
        self._reload()
        self._list.selection_set(j)

    def _up(self):
        self._move(-1)

    def _down(self):
        self._move(1)

    def _renumber(self):
        for pos, p in enumerate(self._pieces()):
            self.db.update_concert_piece(p["id"], {"position": pos})


# ═══════════════════════════════════════════ Honors marks ════════════════════

class _HonorsDialog(ttk.Toplevel):
    """Tick Honors (♪) and Jr. All-State (★) for students in this concert's
    ensembles — the marks print next to their names on the program."""

    def __init__(self, parent, main_db, students, ensembles):
        super().__init__(parent.winfo_toplevel())
        self.main_db = main_db
        self.title("Program Recognition Marks")
        self.resizable(True, True)
        self.grab_set()

        ttk.Label(self, text="🎖  Honors & Jr. All-State",
                  font=("Segoe UI", 12, "bold"),
                  bootstyle=PRIMARY).pack(anchor=W, padx=16, pady=(12, 2))
        ttk.Label(self, text="♪ = Honors in Band   ★ = Jr. All-State — marks "
                             "appear next to names on every program until unticked.",
                  font=("Segoe UI", 8), foreground=muted_fg()).pack(anchor=W, padx=16)

        wrap = ttk.Frame(self)
        wrap.pack(fill=BOTH, expand=True, padx=16, pady=8)
        canvas = tk.Canvas(wrap, highlightthickness=0, width=460, height=380)
        sb = ttk.Scrollbar(wrap, orient=VERTICAL, command=canvas.yview)
        inner = ttk.Frame(canvas)
        inner.bind("<Configure>",
                   lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side=LEFT, fill=BOTH, expand=True)
        sb.pack(side=RIGHT, fill=Y)
        canvas.bind_all("<MouseWheel>",
                        lambda e: canvas.yview_scroll(-1 * (e.delta // 120), "units"))

        members = [s for s in students
                   if any(e.strip() and e.strip().lower() in
                          (s.get("ensembles") or "").lower() for e in ensembles)]
        members.sort(key=lambda s: ((s.get("last_name") or "").lower(),
                                    (s.get("first_name") or "").lower()))
        hdr = ttk.Frame(inner); hdr.pack(fill=X)
        ttk.Label(hdr, text="Student", width=30,
                  font=("Segoe UI", 9, "bold")).pack(side=LEFT)
        ttk.Label(hdr, text="♪ Honors", font=("Segoe UI", 9, "bold")).pack(side=LEFT, padx=6)
        ttk.Label(hdr, text="★ All-State", font=("Segoe UI", 9, "bold")).pack(side=LEFT, padx=6)
        self._rows = []
        for s in members:
            row = ttk.Frame(inner); row.pack(fill=X, pady=1)
            name = f"{s.get('first_name') or ''} {s.get('last_name') or ''}".strip()
            inst = (s.get("primary_instrument") or "").strip()
            ttk.Label(row, text=f"{name}" + (f"  ({inst})" if inst else ""),
                      width=34, anchor=W).pack(side=LEFT)
            hv = tk.BooleanVar(value=bool(s.get("honors")))
            av = tk.BooleanVar(value=bool(s.get("all_state")))
            ttk.Checkbutton(row, variable=hv, bootstyle=PRIMARY).pack(side=LEFT, padx=22)
            ttk.Checkbutton(row, variable=av, bootstyle=PRIMARY).pack(side=LEFT, padx=22)
            self._rows.append((s["id"], hv, av, bool(s.get("honors")),
                               bool(s.get("all_state"))))

        btns = ttk.Frame(self)
        btns.pack(fill=X, padx=16, pady=(0, 12))
        ttk.Button(btns, text="Cancel", bootstyle=(SECONDARY, OUTLINE),
                   command=self.destroy).pack(side=RIGHT, padx=4)
        ttk.Button(btns, text="Save", bootstyle=SUCCESS,
                   command=self._save).pack(side=RIGHT, padx=4)
        fit_window(self, 540, 540)

    def _save(self):
        for sid, hv, av, oh, oa in self._rows:
            if hv.get() != oh or av.get() != oa:
                self.main_db.set_student_honors(sid, honors=hv.get(),
                                                all_state=av.get())
        self.destroy()


# ═══════════════════════════════════════════ Details page ════════════════════

class _DetailsDialog(ttk.Toplevel):
    """Preview + export of the family details page."""

    def __init__(self, parent, concert, school_name):
        super().__init__(parent.winfo_toplevel())
        self._parent_view = parent
        self.concert = concert
        self.school_name = school_name
        self.title(f"Details Page — {concert['title']}")
        self.resizable(True, True)
        self.grab_set()

        ttk.Label(self, text=f"📄  Details Page — {concert['title']}",
                  font=("Segoe UI", 12, "bold"),
                  bootstyle=PRIMARY).pack(anchor=W, padx=16, pady=(12, 2))
        ttk.Label(self, text="Copy the text straight into an email/newsletter, "
                             "or export an editable Publisher page to print.",
                  font=("Segoe UI", 8), foreground=muted_fg()).pack(anchor=W, padx=16)

        text = ct.details_text(concert)
        box = tk.Text(self, font=("Calibri", 11), width=86, height=24,
                      relief="solid", bd=1, wrap=WORD)
        box.insert("1.0", text)
        box.config(state="disabled")
        box.pack(fill=BOTH, expand=True, padx=16, pady=8)

        btns = ttk.Frame(self)
        btns.pack(fill=X, padx=16, pady=(0, 12))
        ttk.Button(btns, text="Close", bootstyle=(SECONDARY, OUTLINE),
                   command=self.destroy).pack(side=RIGHT, padx=4)
        ttk.Button(btns, text="🖨 Export Publisher Page (.pub)",
                   bootstyle=(SUCCESS, OUTLINE),
                   command=self._export_pub).pack(side=RIGHT, padx=4)
        self._copy_btn = ttk.Button(btns, text="📋 Copy Text",
                                    bootstyle=PRIMARY,
                                    command=lambda: self._copy(text))
        self._copy_btn.pack(side=RIGHT, padx=4)
        fit_window(self, 720, 620)

    def _copy(self, text):
        _copy(self, text)
        self._copy_btn.config(text="✓ Copied!")
        self.after(1600, lambda: self._copy_btn.config(text="📋 Copy Text"))

    def _export_pub(self):
        path = filedialog.asksaveasfilename(
            parent=self, defaultextension=".pub",
            initialfile=_default_filename(self.concert, "Details"),
            filetypes=[("Publisher files", "*.pub")])
        if not path:
            return
        self._parent_view._run_publisher(
            "Building the details page in Microsoft Publisher…",
            lambda: __import__("concert_program_pub").build_details_pub(
                path, self.concert, school_name=self.school_name),
            path)
        self.destroy()


# ═══════════════════════════════════════════ Reminders ═══════════════════════

class _RemindersDialog(ttk.Toplevel):
    """The standard reminder cadence: 2 weeks / 1 week / 2 days before.
    Each stage gets a ready-made email + the parent address list; the view
    tracks which have gone out."""

    def __init__(self, parent, db, concert, students, teacher):
        super().__init__(parent.winfo_toplevel())
        self.db = db
        self.concert = concert
        self.school, self.director = teacher
        self.title(f"Reminders — {concert['title']}")
        self.resizable(True, True)
        self.grab_set()

        ttk.Label(self, text=f"✉  Reminders — {concert['title']}",
                  font=("Segoe UI", 12, "bold"),
                  bootstyle=PRIMARY).pack(anchor=W, padx=16, pady=(12, 2))

        ens = ct.ensembles_list(concert)
        self._addresses = ct.parent_addresses(students, ens)
        ttk.Label(self, text=f"{len(self._addresses)} parent email address(es) "
                             f"found for: {', '.join(ens) or '—'}",
                  font=("Segoe UI", 8), foreground=muted_fg()).pack(anchor=W, padx=16)

        sent = {r["stage"]: r["sent_date"]
                for r in db.get_concert_reminders(concert["id"]) if r["sent_date"]}
        today = datetime.today().date()

        # ── Staff / facilities email — the one that can't be skipped ──
        sbox = tk.LabelFrame(self, text=" Office / custodians / PE / admin "
                                        "(2 weeks before) ",
                             font=("Segoe UI", 9, "bold"), padx=10, pady=6)
        sbox.pack(fill=X, padx=16, pady=(8, 4))
        ttk.Label(sbox, text="One email for the whole concert week: custodial "
                             "needs, set-up, doors, tear down, and the 5th "
                             "grade performance. Send to the office manager, "
                             "assistant office manager, PE teachers, "
                             "custodians, and admin.",
                  font=("Segoe UI", 8), foreground=muted_fg(),
                  wraplength=540, justify=LEFT).pack(anchor=W)
        d14 = dict(ct.reminder_schedule(concert.get("concert_date"))
                   ).get("2 weeks")
        skey = ct.STAFF_STAGE_KEY
        if skey in sent:
            status, color = f"✓ sent {sent[skey]}", "#1a7a1a"
        elif ct.staff_due(concert.get("concert_date"), sent):
            status, color = f"⚠ due — send now (was due {d14})", "#B45309"
        elif d14:
            status, color = f"send on {d14}", "#555555"
        else:
            status, color = "set a concert date to schedule", "#888888"
        srow = ttk.Frame(sbox)
        srow.pack(fill=X, pady=(4, 0))
        ttk.Label(srow, text=status, font=("Segoe UI", 9),
                  foreground=color).pack(side=LEFT)
        sbtns = ttk.Frame(srow)
        sbtns.pack(side=RIGHT)
        ttk.Button(sbtns, text="✉ Email Template", bootstyle=(PRIMARY, OUTLINE),
                   command=self._show_staff_email).pack(side=LEFT, padx=2)
        if skey in sent:
            ttk.Button(sbtns, text="Undo", bootstyle=(SECONDARY, OUTLINE, LINK),
                       command=lambda: self._unmark(skey)).pack(side=LEFT, padx=2)
        else:
            ttk.Button(sbtns, text="✓ Mark Sent", bootstyle=(SUCCESS, OUTLINE),
                       command=lambda: self._mark(skey)).pack(side=LEFT, padx=2)

        self._stage_widgets = {}
        for label, due in ct.reminder_schedule(concert.get("concert_date")):
            box = tk.LabelFrame(self, text=f" {label} before ",
                                font=("Segoe UI", 9, "bold"), padx=10, pady=6)
            box.pack(fill=X, padx=16, pady=4)
            if label in sent:
                status, color = f"✓ sent {sent[label]}", "#1a7a1a"
            elif due and today >= due:
                status, color = f"⚠ due — send now (was due {due})", "#B45309"
            elif due:
                status, color = f"send on {due}", "#555555"
            else:
                status, color = "set a concert date to schedule", "#888888"
            lbl = ttk.Label(box, text=status, font=("Segoe UI", 9), foreground=color)
            lbl.pack(side=LEFT)
            row = ttk.Frame(box)
            row.pack(side=RIGHT)
            ttk.Button(row, text="📋 Addresses", bootstyle=(SECONDARY, OUTLINE),
                       command=self._copy_addresses).pack(side=LEFT, padx=2)
            ttk.Button(row, text="✉ Email Template", bootstyle=(PRIMARY, OUTLINE),
                       command=lambda l=label: self._show_email(l)).pack(side=LEFT, padx=2)
            if label in sent:
                ttk.Button(row, text="Undo", bootstyle=(SECONDARY, OUTLINE, LINK),
                           command=lambda l=label: self._unmark(l)).pack(side=LEFT, padx=2)
            else:
                ttk.Button(row, text="✓ Mark Sent", bootstyle=(SUCCESS, OUTLINE),
                           command=lambda l=label: self._mark(l)).pack(side=LEFT, padx=2)

        ttk.Label(self, text="Workflow: copy the addresses into BCC, copy the "
                             "email text, adjust anything personal, send — then "
                             "mark the stage sent so the Concerts list stops "
                             "flagging it.",
                  font=("Segoe UI", 8), foreground=muted_fg(), wraplength=560,
                  justify=LEFT).pack(anchor=W, padx=18, pady=(4, 0))

        self._status = ttk.Label(self, text="", font=("Segoe UI", 9),
                                 foreground="#1a7a1a")
        self._status.pack(anchor=W, padx=18, pady=(4, 0))
        ttk.Button(self, text="Close", bootstyle=(SECONDARY, OUTLINE),
                   command=self.destroy).pack(pady=(6, 14))
        fit_window(self, 620, 620)

    def _flash(self, msg):
        self._status.config(text=msg)
        self.after(2200, lambda: self._status.config(text=""))

    def _copy_addresses(self):
        if not self._addresses:
            Messagebox.show_info("No parent email addresses found for these "
                                 "ensembles — check student records.",
                                 title="No Addresses", parent=self)
            return
        _copy(self, "; ".join(self._addresses))
        self._flash(f"✓ {len(self._addresses)} addresses copied — paste into BCC.")

    def _show_email(self, stage):
        """Preview + edit the reminder email before copying anything."""
        subject, body = ct.reminder_email(self.concert, stage,
                                          teacher_name=self.director,
                                          school_name=self.school)
        win = ttk.Toplevel(self)
        win.title(f"Email Template — {stage} reminder")
        win.grab_set()
        ttk.Label(win, text=f"✉  Email Template — {stage} reminder",
                  font=("Segoe UI", 12, "bold"),
                  bootstyle=PRIMARY).pack(anchor=W, padx=16, pady=(12, 2))
        ttk.Label(win, text="Adjust anything below, then copy — the copy "
                            "buttons always take the edited version.",
                  font=("Segoe UI", 8), foreground=muted_fg()).pack(anchor=W, padx=16)

        srow = ttk.Frame(win)
        srow.pack(fill=X, padx=16, pady=(8, 2))
        ttk.Label(srow, text="Subject:", font=("Segoe UI", 9, "bold")).pack(side=LEFT)
        subj_var = tk.StringVar(value=subject)
        ttk.Entry(srow, textvariable=subj_var).pack(side=LEFT, fill=X,
                                                    expand=True, padx=(8, 0))

        box = tk.Text(win, font=("Calibri", 11), width=76, height=18,
                      relief="solid", bd=1, wrap=WORD)
        box.insert("1.0", body)
        box.pack(fill=BOTH, expand=True, padx=16, pady=6)

        status = ttk.Label(win, text="", font=("Segoe UI", 9),
                           foreground="#1a7a1a")
        status.pack(anchor=W, padx=18)

        def flash(msg):
            status.config(text=msg)
            win.after(2000, lambda: status.config(text=""))

        def copy_body():
            _copy(win, box.get("1.0", "end").strip())
            flash("✓ Email body copied.")

        def copy_all():
            _copy(win, f"Subject: {subj_var.get().strip()}\n\n"
                       f"{box.get('1.0', 'end').strip()}")
            flash("✓ Subject + body copied.")

        btns = ttk.Frame(win)
        btns.pack(fill=X, padx=16, pady=(4, 12))
        ttk.Button(btns, text="Close", bootstyle=(SECONDARY, OUTLINE),
                   command=win.destroy).pack(side=RIGHT, padx=4)
        ttk.Button(btns, text="📋 Copy Subject + Body", bootstyle=PRIMARY,
                   command=copy_all).pack(side=RIGHT, padx=4)
        ttk.Button(btns, text="📋 Copy Body Only", bootstyle=(PRIMARY, OUTLINE),
                   command=copy_body).pack(side=RIGHT, padx=4)
        fit_window(win, 660, 540)

    # ── Staff / facilities email ──

    def _staff_body(self):
        """Saved with this concert if she's edited it; otherwise start from
        the most recent concert that has one (December's email becomes
        March's first draft); otherwise the auto skeleton."""
        saved = (self.concert.get("email_staff") or "").strip()
        if saved:
            return saved
        others = [dict(x) for x in self.db.get_concerts()
                  if x["id"] != self.concert["id"]
                  and (dict(x).get("email_staff") or "").strip()]
        if others:
            others.sort(key=lambda x: x.get("concert_date") or "")
            return others[-1]["email_staff"].strip()
        _, body = ct.staff_email(self.concert, self.school)
        return body

    def _persist_staff(self, body):
        try:
            self.db.update_concert(self.concert["id"], {"email_staff": body})
            self.concert["email_staff"] = body
        except Exception:
            pass

    def _show_staff_email(self):
        subject, _auto = ct.staff_email(self.concert, self.school)
        win = ttk.Toplevel(self)
        win.title("Email Template — office / custodians / PE / admin")
        win.grab_set()
        ttk.Label(win, text="✉  Staff & facilities email",
                  font=("Segoe UI", 12, "bold"),
                  bootstyle=PRIMARY).pack(anchor=W, padx=16, pady=(12, 2))
        ttk.Label(win, text="Copying saves your edits as this concert's "
                            "staff email, and the next concert starts from "
                            "it — update the dates and details instead of "
                            "rewriting. The To list is saved for every "
                            "concert this year.",
                  font=("Segoe UI", 8), foreground=muted_fg(),
                  wraplength=560, justify=LEFT).pack(anchor=W, padx=16)

        trow = ttk.Frame(win)
        trow.pack(fill=X, padx=16, pady=(8, 2))
        ttk.Label(trow, text="To:", font=("Segoe UI", 9, "bold"),
                  width=8).pack(side=LEFT)
        to_var = tk.StringVar(value=self.db.get_program_setting(
            "staff_addresses"))
        ttk.Entry(trow, textvariable=to_var).pack(side=LEFT, fill=X,
                                                  expand=True, padx=(8, 0))
        srow = ttk.Frame(win)
        srow.pack(fill=X, padx=16, pady=(2, 2))
        ttk.Label(srow, text="Subject:", font=("Segoe UI", 9, "bold"),
                  width=8).pack(side=LEFT)
        subj_var = tk.StringVar(value=subject)
        ttk.Entry(srow, textvariable=subj_var).pack(side=LEFT, fill=X,
                                                    expand=True, padx=(8, 0))
        box = tk.Text(win, font=("Calibri", 11), width=76, height=20,
                      relief="solid", bd=1, wrap=WORD)
        box.insert("1.0", self._staff_body())
        box.pack(fill=BOTH, expand=True, padx=16, pady=6)

        status = ttk.Label(win, text="", font=("Segoe UI", 9),
                           foreground="#1a7a1a")
        status.pack(anchor=W, padx=18)

        def flash(msg):
            status.config(text=msg)
            win.after(2000, lambda: status.config(text=""))

        def save_all():
            self._persist_staff(box.get("1.0", "end").strip())
            try:
                self.db.set_program_setting("staff_addresses",
                                            to_var.get().strip())
            except Exception:
                pass

        def copy_addrs():
            save_all()
            if not to_var.get().strip():
                flash("Type the staff addresses into “To” first — they're "
                      "saved for next time.")
                return
            _copy(win, to_var.get().strip())
            flash("✓ Addresses copied (and saved for every concert).")

        def copy_body():
            save_all()
            _copy(win, box.get("1.0", "end").strip())
            flash("✓ Body copied (and saved with this concert).")

        def copy_all():
            save_all()
            _copy(win, f"Subject: {subj_var.get().strip()}\n\n"
                       f"{box.get('1.0', 'end').strip()}")
            flash("✓ Subject + body copied (and saved with this concert).")

        def reset_auto():
            self._persist_staff("")
            _, fresh = ct.staff_email(self.concert, self.school)
            box.delete("1.0", "end")
            box.insert("1.0", fresh)
            flash("↺ Back to the auto-generated skeleton.")

        b = ttk.Frame(win)
        b.pack(fill=X, padx=16, pady=(4, 12))
        ttk.Button(b, text="Close", bootstyle=(SECONDARY, OUTLINE),
                   command=win.destroy).pack(side=RIGHT, padx=4)
        ttk.Button(b, text="📋 Copy Subject + Body", bootstyle=PRIMARY,
                   command=copy_all).pack(side=RIGHT, padx=4)
        ttk.Button(b, text="📋 Copy Body Only", bootstyle=(PRIMARY, OUTLINE),
                   command=copy_body).pack(side=RIGHT, padx=4)
        ttk.Button(b, text="📋 Addresses", bootstyle=(SECONDARY, OUTLINE),
                   command=copy_addrs).pack(side=RIGHT, padx=4)
        ttk.Button(b, text="↺ Reset to Auto", bootstyle=(SECONDARY, OUTLINE),
                   command=reset_auto).pack(side=LEFT, padx=4)
        fit_window(win, 680, 620)

    def _mark(self, stage):
        self.db.mark_concert_reminder(self.concert["id"], stage,
                                      datetime.today().strftime("%Y-%m-%d"))
        self.destroy()

    def _unmark(self, stage):
        self.db.clear_concert_reminder(self.concert["id"], stage)
        self.destroy()
