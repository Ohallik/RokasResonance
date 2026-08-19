"""
ui/instrument_carryover_dialog.py - Assign this year's school instruments from
last year's assignments.

Most students keep what they had, so the new year starts from last year's list
rather than from an empty check-out screen.  Every row is one ASSIGNMENT, not
one student: a tuba player keeps one at school and one at home, a sax player may
have three, and a high school student can be in marching, jazz and concert band
at once.  Nothing here caps how many instruments a student may hold.

Each row offers the instrument they had plus every other AVAILABLE instrument of
the same kind, so a flute player sees flutes and a trumpet player sees trumpets.
String players can be moved up a size in one click, since a student who grew
over the summer needs the next size, not the one they had.

Only students who are on THIS year's roster are listed.  Last year's top class
has moved on to the high school and their instruments come back to the shelf,
so they must not appear here — and neither must anyone who chose not to
continue.  That test is deliberately strict: a row that reaches this screen
gets an instrument checked out and a rental fee billed, and billing the wrong
child is far worse than leaving a returning one to be checked out by hand.
"""

import tkinter as tk
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from ttkbootstrap.dialogs import Messagebox
from datetime import datetime

import instrument_sizes as isz
from ui.theme import fs, muted_fg

# Words the inventory already treats as "still district property, but not
# usable" — those pieces must never be offered to a student.
_UNUSABLE = ("unrepairable", "lost", "missing", "stolen", "retired", "disposed",
             "out of service", "unavailable", "scrap", "beyond repair")


def _is_usable(inst) -> bool:
    blob = ((inst.get("condition") or "") + " " +
            (inst.get("comments") or "")).lower()
    return not any(w in blob for w in _UNUSABLE)


def _norm(text) -> str:
    """A name flattened for comparison: case, punctuation and stray spaces are
    all things a district export changes between years."""
    return " ".join(str(text or "").replace(".", " ").replace(",", " ")
                    .strip().lower().split())


def _given_name(first) -> str:
    """The part of a first name that survives a re-export.  Rosters carry
    middle initials one year and drop them the next — 'Lincoln A.' and
    'Lincoln' are the same child, so the initial is not part of the key."""
    parts = [p for p in _norm(first).split() if len(p) > 1]
    return parts[0] if parts else _norm(first)


def _split_full_name(full):
    """'Bryson D. Park' → ('Bryson D.', 'Park').

    The surname is the LAST word, not the second one: splitting from the left
    made 'D. Park' a surname, and nobody matched."""
    parts = _norm(full).split()
    if not parts:
        return "", ""
    if len(parts) == 1:
        return "", parts[0]
    return " ".join(parts[:-1]), parts[-1]


def _numeric_grade(value):
    text = str(value or "").strip()
    return int(text) if text.isdigit() else None


def _year_end_holdings(rows):
    """One row per instrument a student was actually holding by June, rather
    than one per check-out event.

    A horn that went in for repair and came back, or a loaner swapped for a
    better one, is ONE instrument across the year.  Carrying every event
    forward would hand that student two horns and bill them twice.  Overlapping
    loans are kept apart though — a sax player really does hold an alto, a
    tenor and a bari at the same time — by threading each check-out onto a
    "slot" that was free when it started, and keeping the last of each slot."""
    groups = {}
    for r in rows:
        who = r.get("student_id") or _norm(r.get("student_name"))
        groups.setdefault((who, isz.base_type(r.get("description") or "")),
                          []).append(r)

    keep = []
    for group in groups.values():
        group.sort(key=lambda r: ((r.get("date_assigned") or ""),
                                  (r.get("checkout_id") or 0)))
        slots = []                      # [(date that slot came free, row)]
        for r in group:
            out = r.get("date_assigned") or ""
            back = (r.get("date_returned") or "").strip()
            for i, (free_from, _held) in enumerate(slots):
                if free_from and out >= free_from:
                    slots[i] = (back, r)        # this one replaced that one
                    break
            else:
                slots.append((back, r))         # held alongside the others
        keep.extend(held for _free, held in slots)
    return keep


def _default_return_date() -> str:
    """The June the school year ends in, matching the checkout dialogs."""
    today = datetime.today()
    end_year = today.year + 1 if today.month >= 8 else today.year
    return f"{end_year}-06-20"


def _label_for(inst) -> str:
    """How an instrument reads in the dropdown: what it is, then how to find it."""
    bits = [(inst["description"] or "").strip() or "(no name)"]
    size = (inst["size"] if "size" in inst.keys() else "") or ""
    if size:
        bits.append(size.strip())
    tag = ((inst["barcode"] if "barcode" in inst.keys() else "") or
           (inst["district_no"] if "district_no" in inst.keys() else "") or
           (inst["serial_no"] if "serial_no" in inst.keys() else "") or "")
    label = " ".join(bits)
    if tag:
        label += f"  #{tag}"
    brand = (inst["brand"] if "brand" in inst.keys() else "") or ""
    if brand:
        label += f"  ({brand})"
    return label


class InstrumentCarryOverDialog(ttk.Toplevel):
    def __init__(self, parent, db, school_year=None, base_dir=None):
        super().__init__(parent)
        self.db = db
        self.base_dir = base_dir
        self.school_year = school_year or db.current_school_year()
        self.prior_year = db.previous_school_year(self.school_year)
        self.assigned = 0
        self._year_start = db.school_year_bounds(self.school_year)[0]

        self.title("Carry Over Instrument Assignments")
        self.resizable(True, True)
        self.grab_set()
        self.lift()

        self._rows = []
        self._already = {}
        self._rolled = True
        self._build()
        self._load()

        from ui.theme import fit_window
        fit_window(self, 940, 660)

    # ── the teacher's own setup ──────────────────────────────────────────────

    def _program_type(self):
        """band / orchestra / choir — an orchestra director gets the size-up
        button on rows a band-shaped guess would skip."""
        if getattr(self, "_cached_program", None) is None:
            try:
                from ui.settings_dialog import load_settings
                self._cached_program = str(
                    (load_settings(self.base_dir or ".").get("teacher") or {}
                     ).get("program_type", "band")).strip().lower()
            except Exception:
                self._cached_program = "band"
        return self._cached_program

    def _fee_label(self):
        """The school-year rental as the teacher has it priced — $75 unless
        they changed the fee type."""
        amount = 75.0
        try:
            for t in self.db.get_fee_types():
                name = (t["name"] or "").lower()
                if name.startswith("instrument rental") and "school year" in name:
                    amount = float(t["default_amount"] or amount)
                    break
        except Exception:
            pass
        return f"${amount:,.2f}".replace(".00", "")

    # ── layout ───────────────────────────────────────────────────────────────

    def _build(self):
        hdr = ttk.Frame(self, bootstyle=PRIMARY)
        hdr.pack(fill=X)
        from ui.help_system import add_help_button
        add_help_button(hdr, "carryover")
        ttk.Label(hdr, text="🎺  Carry Over Instrument Assignments",
                  font=("Segoe UI", 13, "bold"),
                  bootstyle=(INVERSE, PRIMARY)).pack(pady=12, padx=16, anchor=W)

        top = ttk.Frame(self)
        top.pack(fill=X, padx=16, pady=(10, 4))
        self._intro = ttk.Label(
            top, text="", font=("Segoe UI", 9), wraplength=880, justify=LEFT)
        self._intro.pack(anchor=W)

        # Helper hint: users should run the New School Year wizard before
        # carrying forward assignments. Offer a quick link to open it.
        hint_frame = ttk.Frame(top)
        hint_frame.pack(fill=X, pady=(6, 0))
        self._new_year_hint = ttk.Label(hint_frame,
            text=("If you haven't run the New School Year wizard yet, "
                  "do that first — it imports class lists and rolls students "
                  "forward."), font=("Segoe UI", 8), foreground=muted_fg(), wraplength=760, justify=LEFT)
        self._new_year_hint.pack(side=LEFT)
        ttk.Button(hint_frame, text="Start New School Year…",
                   bootstyle=(INFO, OUTLINE), command=self._open_year_wizard).pack(side=RIGHT)

        tools = ttk.Frame(self)
        tools.pack(fill=X, padx=16, pady=(6, 4))
        ttk.Button(tools, text="Tick All", bootstyle=(SECONDARY, OUTLINE),
                   command=lambda: self._set_all(True)).pack(side=LEFT, padx=(0, 4))
        ttk.Button(tools, text="Untick All", bootstyle=(SECONDARY, OUTLINE),
                   command=lambda: self._set_all(False)).pack(side=LEFT, padx=4)
        ttk.Label(tools, text="String players who have grown get a ⬆ button on "
                              "their own row.",
                  font=("Segoe UI", 8), foreground=muted_fg()).pack(side=LEFT, padx=(12, 4))
        self._count_lbl = ttk.Label(tools, text="", font=("Segoe UI", 9, "bold"))
        self._count_lbl.pack(side=RIGHT)

        # The rental fee is an annual charge every renting student owes, one per
        # instrument, so it is added by default.  The switch exists for the case
        # where these assignments were billed already.
        fees = ttk.Frame(self)
        fees.pack(fill=X, padx=16, pady=(0, 2))
        self._fee_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            fees, variable=self._fee_var, bootstyle=PRIMARY,
            text=f"Bill the {self._fee_label()} school-year rental for each "
                 "instrument assigned"
        ).pack(side=LEFT)
        ttk.Label(fees, text="(a student taking two instruments is billed twice; "
                             "untick only if these were already billed)",
                  font=("Segoe UI", 8), foreground=muted_fg()).pack(side=LEFT, padx=6)

        # Column headings, aligned with the row grid below.
        head = ttk.Frame(self)
        head.pack(fill=X, padx=16, pady=(6, 0))
        for text, w in (("", 3), ("Student", 26), ("Had last year", 34),
                        ("Assign this year", 44)):
            ttk.Label(head, text=text, font=("Segoe UI", 8, "bold"),
                      foreground=muted_fg(), width=w, anchor=W).pack(side=LEFT, padx=2)

        body = ttk.Frame(self)
        body.pack(fill=BOTH, expand=True, padx=16, pady=(2, 4))
        canvas = tk.Canvas(body, highlightthickness=0)
        sb = ttk.Scrollbar(body, orient=VERTICAL, command=canvas.yview)
        canvas.configure(yscrollcommand=sb.set)
        sb.pack(side=RIGHT, fill=Y)
        canvas.pack(side=LEFT, fill=BOTH, expand=True)
        self._list = ttk.Frame(canvas)
        win = canvas.create_window((0, 0), window=self._list, anchor="nw")
        self._list.bind("<Configure>",
                        lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(win, width=e.width))
        canvas.bind("<Enter>", lambda e: canvas.bind_all(
            "<MouseWheel>", lambda ev: canvas.yview_scroll(int(-ev.delta / 120), "units")))
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))

        btn = ttk.Frame(self)
        btn.pack(fill=X, padx=16, pady=12)
        ttk.Button(btn, text="Cancel", bootstyle=(SECONDARY, OUTLINE),
                   command=self.destroy).pack(side=RIGHT, padx=4)
        self._apply_btn = ttk.Button(btn, text="Assign Ticked", bootstyle=SUCCESS,
                                     command=self._apply)
        self._apply_btn.pack(side=RIGHT, padx=4)

    # ── data ─────────────────────────────────────────────────────────────────

    def _load(self):
        prior = self.db.get_assignments_for_school_year(self.prior_year)
        # Everything with its current status, so the dropdown can fall back to
        # an instrument someone else already has when nothing else is free.
        # "On Loan" instruments are physically at another school, so they are
        # not offered at all.
        all_inst = [dict(r) for r in self.db.get_instruments_with_status()
                    if _is_usable(dict(r))]
        available = [i for i in all_inst if i.get("status") == "Available"]
        in_use = [i for i in all_inst if i.get("status") == "Checked Out"]

        if not prior:
            self._intro.config(
                text=f"No instrument assignments were recorded for "
                     f"{self.prior_year}, so there is nothing to carry forward.")
            self._apply_btn.config(state="disabled")
            self._update_count()
            return

        self._intro.config(
            text=f"These students had a school instrument in {self.prior_year} "
                 f"and are on the {self.school_year} roster. Ticked rows will be "
                 f"checked out for {self.school_year} and billed the "
                 f"{self._fee_label()} rental. Untick anyone who no longer needs "
                 f"one. Each row is one instrument, so a student who really "
                 f"keeps two is billed for both. Students who graduated or did "
                 f"not continue are not listed at all.")

        # One row per instrument they finished the year with, not one per
        # check-out event: repairs and swaps would otherwise each become a
        # separate instrument to hand out and a separate fee to pay.
        rows = _year_end_holdings([dict(r) for r in prior])

        # Who is on THIS year's roster.  Resolved by identity rather than by the
        # student id stored on the checkout: that id is last year's row, and a
        # district CSV import creates a new row per year, which would make every
        # returning student look like they had left.
        #
        # Only three keys count, and each must land on exactly ONE student:
        #   1) district student ID     — respellings don't change it
        #   2) full name               — middle initials normalized away
        #   3) given name + surname    — 'Sandra Menchu Ixcotoyac' → Sandra …
        # Looser keys were tried and are deliberately gone.  Matching on a
        # surname alone handed a graduated Alan Chen's trombone to his brother
        # Leo and billed Leo for it; a surname plus a first initial did the same
        # for Asahel and Aneeka Satpathy.  A student the roster can't confirm is
        # left off and checked out by hand.
        cur_students = [dict(s) for s in self.db.get_all_students(self.school_year)]
        by_sid, by_full, by_given = {}, {}, {}
        for s in cur_students:
            sid = str(s.get("student_id") or "").strip()
            if sid:
                by_sid.setdefault(sid, []).append(s)
            last = _norm(s.get("last_name"))
            if not last:
                continue
            for first in {_norm(s.get("first_name")), _norm(s.get("preferred_name"))}:
                if first:
                    by_full.setdefault((first, last), []).append(s)
            for given in {_given_name(s.get("first_name")),
                          _given_name(s.get("preferred_name"))}:
                if given:
                    by_given.setdefault((given, last), []).append(s)

        def only(bucket, key):
            found = bucket.get(key) or []
            return found[0] if len(found) == 1 else None

        # The highest grade this program teaches, read off last year's roster —
        # 8 for a middle school, 12 for a high school.  Trusted only when that
        # roster spans three grades or more, because a handful of students left
        # behind says nothing about where the program ends, and a wrong ceiling
        # would quietly hide students who really are coming back.  Nobody is
        # dropped on this test either way: a student above the ceiling is shown
        # unticked, with the reason, for the teacher to judge.
        top_grade = None
        try:
            last_roster = [dict(s) for s in self.db.get_all_students(
                self.prior_year, include_inactive=True)]
            grades = [g for g in (_numeric_grade(s.get("grade")) for s in last_roster)
                      if g is not None]
            if len(set(grades)) >= 3:
                top_grade = max(grades)
        except Exception:
            top_grade = None

        for r in rows:
            first, last = r.get("first_name"), r.get("last_name")
            if not (first and last):
                first, last = _split_full_name(r.get("student_name"))
            first, last = _norm(first), _norm(last)
            district_id = str(r.get("district_id") or "").strip()

            match, confidence = None, None
            if district_id:
                match = only(by_sid, district_id)
                confidence = "id" if match else None
            if not match and first and last:
                match = only(by_full, (first, last))
                confidence = "name" if match else None
            if not match and first and last:
                match = only(by_given, (_given_name(first), last))
                confidence = "given" if match else None

            grade = _numeric_grade(match.get("grade")) if match else None
            r["_current"] = dict(match) if match else None
            r["_match_confidence"] = confidence
            r["_past_top"] = (top_grade if match and top_grade and grade
                              and grade > top_grade else None)

        keep_rows = [r for r in rows if r["_current"]]
        # Only assignments that resolve to a current roster entry are listed.
        # If nothing resolves, the user must run the New Year wizard or import
        # the roster before carrying assignments forward.
        self._rolled = bool(keep_rows)
        dropped = len(rows) - len(keep_rows)

        # Anything this student already holds this year — so running the screen
        # twice can't check the same horn out twice or bill the fee twice.
        self._already = {}
        try:
            for c in self.db.get_open_instrument_checkouts():
                c = dict(c)
                self._already.setdefault(c.get("instrument_id"), []).append(c)
        except Exception:
            pass

        for row in keep_rows:
            self._add_row(row, self._options_for(row, available, in_use))

        if not keep_rows:
            self._intro.config(
                text=(f"No students from {self.prior_year} are on the "
                      f"{self.school_year} roster, so there is nothing to carry "
                      "forward. Run the New Year wizard (or import this year's "
                      "class lists) first — carry-over only offers students it "
                      "can confirm are still in your program."))
            self._apply_btn.config(state="disabled")
        elif dropped:
            self._intro.config(
                text=self._intro.cget("text")
                + f"  ({dropped} instrument(s) belonged to students who are not "
                  f"on the {self.school_year} roster — graduated or not "
                  "continuing — and are not listed.)")
        self._update_count()

    def _held_by(self, row, instrument_id):
        """The open check-out on this instrument that belongs to this same
        student, if there is one.

        Instruments kept over the summer are still signed out, so without this
        a student's own horn would come back to them marked "already with
        <themself>" — and assigning it would open a second loan on top of the
        first."""
        cur = row.get("_current") or {}
        ids = {i for i in (cur.get("id"), row.get("student_id")) if i is not None}
        names = {n for n in (_norm(f"{cur.get('first_name') or ''} "
                                   f"{cur.get('last_name') or ''}"),
                             _norm(row.get("student_name"))) if n}
        for c in self._already.get(instrument_id, []):
            if c.get("student_id") in ids or _norm(c.get("student_name")) in names:
                return c
        return None

    def _options_for(self, row, available, in_use):
        """Free instruments of the same kind, closest match first, followed by
        same-kind instruments someone else already holds.  Sharing one
        instrument between two students is unusual but sometimes the only
        option, so it is offered last and clearly marked rather than hidden.

        An instrument this student is already holding counts as free to them."""
        wanted = row.get("description") or ""

        def collect(source, shared):
            out = []
            for inst in source:
                rank = isz.type_rank(wanted, inst.get("description") or "")
                if rank > 1:        # same instrument, not merely the same family
                    continue
                label = _label_for(inst)
                mine = self._held_by(row, inst["id"]) if shared else None
                if mine:
                    label += "  — still has it"
                elif shared:
                    holder = (inst.get("checked_out_to") or "someone else").strip()
                    label = f"⚠ {label}  — already with {holder}"
                out.append({
                    "label": label, "id": inst["id"],
                    "shared": bool(shared and not mine), "mine": mine,
                    "size": (inst.get("size") or ""),
                    "desc": (inst.get("description") or ""),
                    "sort": (rank, isz.size_sort_key(inst.get("size") or ""), label),
                })
            return out

        picked = collect(available, False) + collect(in_use, True)
        free = [o for o in picked if not o["shared"]]
        shared = [o for o in picked if o["shared"]]
        free.sort(key=lambda o: o["sort"])
        shared.sort(key=lambda o: o["sort"])
        options = free + shared

        # Two untagged flutes read as the same line, and the teacher has no way
        # to tell which one they just picked.  Number the repeats.
        counts = {}
        for o in options:
            counts[o["label"]] = counts.get(o["label"], 0) + 1
        seen = {}
        for o in options:
            if counts[o["label"]] > 1:
                base = o["label"]
                seen[base] = seen.get(base, 0) + 1
                o["label"] = f"{base}  ({seen[base]} of {counts[base]})"
        return options

    def _add_row(self, row, options):
        f = ttk.Frame(self._list)
        f.pack(fill=X, pady=1)

        # Only enrolled students reach this point, so every row starts ticked.
        keep = tk.BooleanVar(value=True)
        cb = ttk.Checkbutton(f, variable=keep, bootstyle=PRIMARY,
                             command=self._update_count)
        cb.pack(side=LEFT, padx=(2, 4))

        cur = row.get("_current") or {}
        name = ((cur.get("first_name") and
                 f"{cur['first_name']} {cur.get('last_name') or ''}".strip())
                or (row.get("student_name") or "(unknown)").strip())
        # This year's grade, not the one they were in when they borrowed it.
        grade = str(cur.get("grade") or row.get("grade") or "").strip()
        who = f"{name}" + (f"  (Gr {grade})" if grade else "")
        lbl = ttk.Label(f, text=who, width=26, anchor=W,
                  font=("Segoe UI", 9))
        lbl.pack(side=LEFT, padx=2)

        # How this student was recognized on the new roster.  Shown because the
        # teacher is the only one who can spot a wrong pairing, and the fee
        # follows whoever is on the row.
        conf_text = {"id": "matched on student ID",
                     "name": "matched on name",
                     "given": "matched on first + last name"}.get(
            row.get("_match_confidence") or "", "")
        if conf_text:
            ttk.Label(f, text=conf_text, font=("Segoe UI", 8),
                      foreground=muted_fg()).pack(side=LEFT, padx=(6, 10))

        had = (row.get("description") or "").strip()
        if row.get("size"):
            had += f" {row['size']}"
        tag = row.get("barcode") or row.get("district_no") or row.get("serial_no") or ""
        if tag:
            had += f"  #{tag}"
        ttk.Label(f, text=had or "(unknown)", width=34, anchor=W,
                  font=("Segoe UI", 9), foreground=muted_fg()).pack(side=LEFT, padx=2)

        choice = tk.StringVar()
        labels = [o["label"] for o in options]
        combo = ttk.Combobox(f, textvariable=choice, values=labels,
                             state="readonly", width=44)
        combo.pack(side=LEFT, padx=2)

        # Default to the very instrument they had, when it is still free.
        # Selection is tracked by POSITION, never by the text in the box: two
        # untagged flutes can read identically, and looking the choice back up
        # by its label handed the student whichever one came first.
        prior_id = row.get("instrument_id")
        free_at = [i for i, o in enumerate(options) if not o["shared"]]
        default = next((i for i in free_at if options[i]["id"] == prior_id), None)
        if default is not None:
            combo.current(default)
        elif free_at:
            combo.current(free_at[0])
        elif labels:
            combo.current(0)               # only a shared one is left
        else:
            combo.config(state="disabled")
            keep.set(False)
            cb.config(state="disabled")
        free_labels = [options[i]["label"] for i in free_at]

        # Say plainly when there is nothing else of this kind to switch to, so
        # an unchangeable dropdown reads as a fact rather than a glitch.
        # "Additional" means anything free other than the one they already had.
        alternatives = [o for o in options
                        if not o["shared"] and o["id"] != prior_id]
        note = ""
        if not options:
            note = "no instruments of this type"
        elif not alternatives:
            note = ("no additional instruments available"
                    if free_labels else "none free — sharing only")

        # Already carried over — a second run must not check the same horn out
        # twice or bill the rental fee twice, so the row starts unticked.  A
        # loan begun this year says so by its date; one that simply ran on from
        # the summer says so by the note carry-over left on it.
        held = self._held_by(row, prior_id)
        done = bool(held and ((held.get("date_assigned") or "") >= self._year_start
                              or f"Carried over to {self.school_year}"
                              in (held.get("notes") or "")))
        if done:
            keep.set(False)
            note = "already assigned this year"

        # Still on the roster, but a grade above where the program ends: most
        # likely a leftover row for someone who has moved up to the high
        # school.  Shown rather than hidden — the teacher knows which it is —
        # but never ticked, because ticking it bills them.
        past = row.get("_past_top")
        if past:
            keep.set(False)
            note = f"Gr {grade} — past Gr {past}; has this student moved on?"

        entry = {
            "data": row, "keep": keep, "choice": choice,
            "done": done or bool(past),
            "options": options, "combo": combo, "sizeup_btn": None,
        }

        # A string player who has grown gets their own size-up button, right
        # where their instrument is chosen.
        bigger = self._bigger_option(row, options)
        if bigger is not None:
            btn = ttk.Button(f, text="⬆", width=3, bootstyle=(INFO, OUTLINE),
                             command=lambda e=entry: self._size_up_row(e))
            btn.pack(side=LEFT, padx=(4, 0))
            entry["sizeup_btn"] = btn
            note = f"can go up to {bigger['size']}"

        if note:
            ttk.Label(f, text=note, font=("Segoe UI", 8, "italic"),
                      foreground=muted_fg()).pack(side=LEFT, padx=6)

        self._rows.append(entry)

    # ── actions ──────────────────────────────────────────────────────────────

    def _set_all(self, value):
        for r in self._rows:
            # Rows already assigned this year stay off: Tick All is a
            # convenience, not a reason to bill somebody twice.
            if r.get("done") and value:
                continue
            if str(r["combo"].cget("state")) != "disabled":
                r["keep"].set(value)
        self._update_count()

    def _update_count(self):
        n = sum(1 for r in self._rows if r["keep"].get())
        self._count_lbl.config(text=f"{n} of {len(self._rows)} to assign")

    def _bigger_option(self, row, options):
        """The smallest free instrument of the same kind that is genuinely
        larger than the one this student had, or None.

        Deliberately not "the next size in the catalog": hardly any school
        owns a 7/8 violin, so a student outgrowing a 3/4 should be offered the
        4/4 that is actually on the shelf.

        Sizing up is a string thing, so it is offered on string rows for any
        teacher.  An orchestra director gets it on every sized instrument they
        own, since their whole inventory is sized and a fractional cello may
        sit under a category a band-shaped guess doesn't recognize."""
        desc = row.get("description") or ""
        if self._program_type() != "orchestra" and \
                (row.get("category") or "").strip().lower() != "strings" and \
                isz.family_for(desc) != "Strings":
            return None
        same_kind = [o for o in options
                     if not o["shared"] and o["size"]
                     and isz.base_type(o["desc"]) == isz.base_type(desc)]
        target = isz.smallest_larger_than(row.get("size") or "",
                                          [o["size"] for o in same_kind])
        if target is None:
            return None
        return next(o for o in same_kind if o["size"] == target)

    def _size_up_row(self, entry):
        """Move one student up a size.  Growing into a bigger instrument is a
        judgement about that particular child, so it is never done in bulk."""
        bigger = self._bigger_option(entry["data"], entry["options"])
        if bigger is None:
            return
        entry["combo"].current(entry["options"].index(bigger))
        entry["sizeup_btn"].config(state="disabled")

    def _apply(self):
        picks = []
        for r in self._rows:
            if not r["keep"].get():
                continue
            i = r["combo"].current()
            if i is None or i < 0 or i >= len(r["options"]):
                continue
            picks.append((r["data"], r["options"][i]))

        if not picks:
            Messagebox.show_warning("Nothing is ticked to assign.",
                                    title="Nothing to Do", parent=self)
            return

        # Two students on one instrument is real but rare — usually with their
        # own mouthpieces — so it is confirmed rather than blocked.
        seen = {}
        doubled = []
        for row, opt in picks:
            iid = opt["id"]
            if iid in seen:
                doubled.append(f"  • {opt['label'].lstrip('⚠ ').split('  —')[0]}"
                               f"\n      {seen[iid]} and {row.get('student_name')}")
            else:
                seen[iid] = row.get("student_name") or "someone"
        already_shared = [f"  • {row.get('student_name')} → "
                          f"{opt['label'].split('  —')[0].lstrip('⚠ ')}"
                          for row, opt in picks if opt["shared"]]
        warn = []
        if doubled:
            warn.append("These instruments go to two students at once:\n\n"
                        + "\n".join(doubled[:8]))
        if already_shared:
            warn.append("These are already checked out to someone else:\n\n"
                        + "\n".join(already_shared[:8]))
        if warn:
            if Messagebox.yesno(
                    "\n\n".join(warn)
                    + "\n\nThat is allowed, and sometimes the only option, but "
                      "it is worth a second look.\n\nAssign anyway?",
                    title="Shared Instruments", parent=self) != "Yes":
                return

        today = datetime.today().strftime("%Y-%m-%d")
        due = _default_return_date()
        charge = self._fee_var.get()
        done, kept, failed = 0, 0, []
        for row, opt in picks:
            try:
                cur = row.get("_current") or {}
                # Check out against THIS year's student record, so the loan and
                # its rental fee land on the roster the teacher is looking at.
                sid = cur.get("id") or row.get("student_id")
                sname = ((cur.get("first_name") and
                          f"{cur['first_name']} {cur.get('last_name') or ''}".strip())
                         or row.get("student_name") or "")
                if opt.get("mine"):
                    # They kept it over the summer and it never came back, so
                    # the loan is already open.  Run it on into this year and
                    # bill the new year's fee, rather than opening a second
                    # loan on an instrument that never came back to the shelf.
                    self.db.carry_checkout_into_year(
                        opt["mine"].get("checkout_id"), self.school_year, due)
                    if charge and sid:
                        self.db.add_rental_fee(sid, today, "school_year",
                                               per_instrument=True)
                    kept += 1
                    continue
                self.db.checkout_instrument(
                    opt["id"], sid, sname, today,
                    notes=f"Carried over from {self.prior_year}",
                    due_date=due, charge_fee=charge, fee_per_instrument=True)
                done += 1
            except Exception as e:
                failed.append(f"  • {row.get('student_name')}: {e}")

        self.assigned = done + kept
        msg = f"Checked out {done} instrument(s) for {self.school_year}."
        if kept:
            msg += (f"\n\n{kept} student(s) already had their instrument from "
                    "over the summer — those loans stay as they are"
                    + (", and only the new year's fee was added." if charge
                       else "."))
        if failed:
            msg += "\n\nCouldn't assign:\n" + "\n".join(failed[:8])
        Messagebox.show_info(msg, title="Assignments Made", parent=self)
        self.destroy()

    def _open_year_wizard(self):
        """Open the global New School Year wizard and refresh matches on return."""
        try:
            from ui.year_wizard import NewSchoolYearWizard
            from lesson_plan_db import current_school_year
        except Exception:
            Messagebox.show_error("Couldn't open the New School Year wizard.", parent=self)
            return
        try:
            years = self.db.get_school_years()
        except Exception:
            years = []
        current = years[0] if years else current_school_year()
        wiz = NewSchoolYearWizard(self.winfo_toplevel(), self.db, self.base_dir or ".", current)
        self.winfo_toplevel().wait_window(wiz)
        # If a new year was created or class lists imported, refresh matching.
        if getattr(wiz, "new_year", None) or getattr(wiz, "_imports", None):
            try:
                # Rebuild rows to pick up any newly imported roster
                for child in list(self._list.winfo_children()):
                    child.destroy()
            except Exception:
                pass
            self._rows = []
            self._load()
