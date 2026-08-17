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
    def __init__(self, parent, db, school_year=None):
        super().__init__(parent)
        self.db = db
        self.school_year = school_year or db.current_school_year()
        self.prior_year = db.previous_school_year(self.school_year)
        self.assigned = 0

        self.title("Carry Over Instrument Assignments")
        self.resizable(True, True)
        self.grab_set()
        self.lift()

        self._rows = []
        self._rolled = True
        self._build()
        self._load()

        from ui.theme import fit_window
        fit_window(self, 940, 660)

    # ── layout ───────────────────────────────────────────────────────────────

    def _build(self):
        hdr = ttk.Frame(self, bootstyle=PRIMARY)
        hdr.pack(fill=X)
        ttk.Label(hdr, text="🎺  Carry Over Instrument Assignments",
                  font=("Segoe UI", 13, "bold"),
                  bootstyle=(INVERSE, PRIMARY)).pack(pady=12, padx=16, anchor=W)

        top = ttk.Frame(self)
        top.pack(fill=X, padx=16, pady=(10, 4))
        self._intro = ttk.Label(
            top, text="", font=("Segoe UI", 9), wraplength=880, justify=LEFT)
        self._intro.pack(anchor=W)

        tools = ttk.Frame(self)
        tools.pack(fill=X, padx=16, pady=(6, 4))
        ttk.Button(tools, text="Tick All", bootstyle=(SECONDARY, OUTLINE),
                   command=lambda: self._set_all(True)).pack(side=LEFT, padx=(0, 4))
        ttk.Button(tools, text="Untick All", bootstyle=(SECONDARY, OUTLINE),
                   command=lambda: self._set_all(False)).pack(side=LEFT, padx=4)
        self._sizeup_btn = ttk.Button(
            tools, text="⬆ Move strings up a size", bootstyle=(INFO, OUTLINE),
            command=self._size_up_strings)
        self._sizeup_btn.pack(side=LEFT, padx=(12, 4))
        self._count_lbl = ttk.Label(tools, text="", font=("Segoe UI", 9, "bold"))
        self._count_lbl.pack(side=RIGHT)

        # Checking an instrument out normally adds that student's rental fee.
        # Doing that for a whole program at once is a real bill, so it is a
        # deliberate choice here rather than a silent side effect.
        fees = ttk.Frame(self)
        fees.pack(fill=X, padx=16, pady=(0, 2))
        self._fee_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            fees, variable=self._fee_var, bootstyle=PRIMARY,
            text="Also add each student's instrument rental fee"
        ).pack(side=LEFT)
        ttk.Label(fees, text="(off by default: carrying last year forward "
                             "shouldn't re-bill the program. One fee per "
                             "student per year either way.)",
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
            self._sizeup_btn.config(state="disabled")
            self._update_count()
            return

        self._intro.config(
            text=f"These students had a school instrument in {self.prior_year}. "
                 f"Ticked rows will be checked out for {self.school_year}. "
                 f"Untick anyone who no longer needs one. Each row is one "
                 f"instrument, so a student who had two still shows twice. "
                 f"Students who have already left are unticked to start with.")

        rows = [dict(r) for r in prior]
        # Whether the roster has been rolled into the new year yet decides what
        # "still here" can even mean.  Run before the New Year wizard, nobody is
        # on the new year, and ticking nothing would look broken — so fall back
        # to every active student.
        self._rolled = any((r.get("student_year") or "") == self.school_year
                           for r in rows)
        for row in rows:
            self._add_row(row, self._options_for(row, available, in_use))

        if not self._rolled:
            self._intro.config(
                text=self._intro.cget("text")
                + "  (Your roster is still on "
                + f"{self.prior_year}, so everyone active is ticked. Run the New "
                  "Year wizard first if you want leavers dropped automatically.)")
        self._update_count()

    def _options_for(self, row, available, in_use):
        """Free instruments of the same kind, closest match first, followed by
        same-kind instruments someone else already holds.  Sharing one
        instrument between two students is unusual but sometimes the only
        option, so it is offered last and clearly marked rather than hidden."""
        wanted = row.get("description") or ""
        prior_id = row.get("instrument_id")

        def collect(source, shared):
            out = []
            for inst in source:
                rank = isz.type_rank(wanted, inst.get("description") or "")
                if rank > 1:        # same instrument, not merely the same family
                    continue
                label = _label_for(inst)
                if shared:
                    holder = (inst.get("checked_out_to") or "someone else").strip()
                    label = f"⚠ {label}  — already with {holder}"
                out.append({
                    "label": label, "id": inst["id"], "shared": shared,
                    "size": (inst.get("size") or ""),
                    "desc": (inst.get("description") or ""),
                    "sort": (rank, isz.size_sort_key(inst.get("size") or ""), label),
                })
            return out

        free = collect(available, False)
        shared = collect(in_use, True)
        free.sort(key=lambda o: o["sort"])
        shared.sort(key=lambda o: o["sort"])

        return free + shared

    def _add_row(self, row, options):
        f = ttk.Frame(self._list)
        f.pack(fill=X, pady=1)

        still_here = bool(row.get("student_active")) and (
            not self._rolled
            or (row.get("student_year") or "") == self.school_year)
        keep = tk.BooleanVar(value=still_here)
        cb = ttk.Checkbutton(f, variable=keep, bootstyle=PRIMARY,
                             command=self._update_count)
        cb.pack(side=LEFT, padx=(2, 4))

        name = (row.get("student_name") or "(unknown)").strip()
        grade = (row.get("grade") or "").strip()
        who = f"{name}" + (f"  (Gr {grade})" if grade else "")
        if not still_here:
            who += "  — not enrolled"
        ttk.Label(f, text=who, width=26, anchor=W,
                  font=("Segoe UI", 9)).pack(side=LEFT, padx=2)

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
        prior_id = row.get("instrument_id")
        default = next((o["label"] for o in options
                        if o["id"] == prior_id and not o["shared"]), None)
        free_labels = [o["label"] for o in options if not o["shared"]]
        if default:
            choice.set(default)
        elif free_labels:
            choice.set(free_labels[0])
        elif labels:
            choice.set(labels[0])          # only a shared one is left
        else:
            combo.config(state="disabled")
            keep.set(False)
            cb.config(state="disabled")

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
        if note:
            ttk.Label(f, text=note, font=("Segoe UI", 8, "italic"),
                      foreground=muted_fg()).pack(side=LEFT, padx=6)

        self._rows.append({
            "data": row, "keep": keep, "choice": choice,
            "options": options, "combo": combo,
        })

    # ── actions ──────────────────────────────────────────────────────────────

    def _set_all(self, value):
        for r in self._rows:
            if str(r["combo"].cget("state")) != "disabled":
                r["keep"].set(value)
        self._update_count()

    def _update_count(self):
        n = sum(1 for r in self._rows if r["keep"].get())
        self._count_lbl.config(text=f"{n} of {len(self._rows)} to assign")

    def _size_up_strings(self):
        """For every ticked string row, switch to a free instrument one size
        larger when there is one.  Anything not a string, or already at the
        largest size, is left alone."""
        moved, no_stock = 0, 0
        for r in self._rows:
            if not r["keep"].get():
                continue
            row = r["data"]
            desc = row.get("description") or ""
            if (row.get("category") or "").strip().lower() != "strings" and \
                    isz.family_for(desc) != "Strings":
                continue
            # Offer the smallest free one that is genuinely bigger, rather than
            # insisting on the next size in the catalogue — a school that owns
            # no 7/8 violins should still move a 3/4 player up to a 4/4.
            same_kind = [o for o in r["options"]
                         if not o["shared"] and o["size"]
                         and isz.base_type(o["desc"]) == isz.base_type(desc)]
            target = isz.smallest_larger_than(row.get("size") or "",
                                              [o["size"] for o in same_kind])
            if target is None:
                if isz.sizes_for(desc, row.get("category") or ""):
                    no_stock += 1
                continue
            match = next(o["label"] for o in same_kind if o["size"] == target)
            r["choice"].set(match)
            moved += 1
        msg = f"Moved {moved} student(s) up a size."
        if no_stock:
            msg += (f"\n\n{no_stock} could use a bigger instrument but none is "
                    "free in that size right now.")
        if not moved and not no_stock:
            msg = ("No ticked string players need a bigger size, or they are "
                   "already on the largest one.")
        Messagebox.show_info(msg, title="Size Up", parent=self)

    def _apply(self):
        picks = []
        for r in self._rows:
            if not r["keep"].get():
                continue
            label = r["choice"].get()
            opt = next((o for o in r["options"] if o["label"] == label), None)
            if opt is None:
                continue
            picks.append((r["data"], opt))

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
        done, failed = 0, []
        for row, opt in picks:
            try:
                self.db.checkout_instrument(
                    opt["id"], row.get("student_id"),
                    row.get("student_name") or "", today,
                    notes=f"Carried over from {self.prior_year}",
                    due_date=due, charge_fee=charge)
                done += 1
            except Exception as e:
                failed.append(f"  • {row.get('student_name')}: {e}")

        self.assigned = done
        msg = f"Checked out {done} instrument(s) for {self.school_year}."
        if failed:
            msg += "\n\nCouldn't assign:\n" + "\n".join(failed[:8])
        Messagebox.show_info(msg, title="Assignments Made", parent=self)
        self.destroy()
