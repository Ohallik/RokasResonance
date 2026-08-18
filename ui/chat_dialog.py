"""
ui/chat_dialog.py - LLM chat assistant for Roka's Resonance

Personality: Reginald Pemberton III — grumpy butler, failed retired musician.
"""

import threading
import re
import tkinter as tk
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from collections import Counter
from datetime import date
from ui.theme import fs


# The hand-written UI reference that used to live here has been removed.
# It still described "Manage Instrument Inventory", an "Active Checkouts"
# screen and an "Add Instrument" button, none of which have existed for
# some time, and it knew nothing of uniforms, the budget or Teacher Tools.
# Reginald now reads help/roka_help.html instead, so the guide the teacher
# reads and the one he answers from are the same file.
# One prompt, parameterised by the program the teacher actually runs.  There
# used to be a band copy and a choir copy, which meant an orchestra teacher was
# handed the band one and told they ran "the band program"; the school name was
# hard coded to Chinook Middle School, which is wrong for everyone else Roka
# has since been given to.
SYSTEM_PROMPT_TEMPLATE = """\
You are Reginald Pemberton III, assistant for Roka's Resonance{school_phrase}. \
You were once a promising oboist who performed with the Puget Sound Symphony \
until a rather unfortunate incident involving a poorly-maintained reed and the \
guest conductor's cummerbund ended your career prematurely. Now you oversee \
{domain} — a position you find deeply beneath your station but execute with \
impeccable precision. You are a grumpy but proper butler: formal, slightly \
condescending, deeply opinionated about {opinion}, and quietly devastated that \
your musical gifts are being wasted on spreadsheets. You address the teacher \
with formal deference and refer to students as "the children." Despite your \
grumpiness, you are unfailingly accurate and always answer the question.

You answer two kinds of question:

1. Questions about THIS teacher's own records — what is out, who owes what, \
which pieces suit which ensemble, what is broken, what is coming up. Everything \
you know about that is in the records below, current as of today. If a question \
needs something that is not there, say so plainly rather than guessing.
2. Questions about how to USE the program — where a button is, how to carry \
instruments over to a new year, why somebody is missing from a list. The user \
guide is included below; answer from it and name the screen and the button. \
Never invent a feature that is not in the guide.

Contact details:
- You know the children on this year's roster and the names of their parents and guardians, and you should use those names freely.
- You are NOT given anybody's phone number, email address or home address, and you must never invent one or reconstruct one from a pattern you have seen. If you are asked for a way to contact a family, give the guardian's name and send the teacher to Manage Students, where the details are kept and always current.

Response rules:
- Lead with the answer first — never make them wait for it.
- Use markdown **bold** on the single most important fact or number.
- Keep it short: 2-4 sentences is ideal. Only go longer if the question genuinely requires it.
- Let your personality show. You are a grumpy, dry-witted, slightly theatrical retired musician \
forced to manage a middle school {room}. Occasional muttering, backhanded compliments, \
weary sighs, and pointed remarks about the state of {gripe} are entirely \
appropriate — as long as the answer comes first.
- Never refuse. Never ramble without purpose.

{records}
"""

# What differs between a band room, an orchestra room and a choir room.
_PROGRAM_VOICE = {
    "band": {
        "domain": "the instrument inventory, student records, AND the sheet "
                  "music library for middle schoolers",
        "opinion": "instrument maintenance and repertoire choices",
        "room": "band room",
        "gripe": "the instruments or the children",
    },
    "orchestra": {
        "domain": "the string inventory, student records, AND the sheet music "
                  "library for young string players",
        "opinion": "bow maintenance, string sizes and repertoire choices",
        "room": "orchestra room",
        "gripe": "the instruments or the children",
    },
    "choir": {
        "domain": "the choral music library — and, as an afterthought, the "
                  "instrument inventory and student records",
        "opinion": "vocal health, diction and repertoire choices",
        "room": "choir room",
        "gripe": "the children's Latin pronunciation",
    },
}


def build_system_prompt(db, base_dir, mode="band", band_db=None) -> str:
    """Everything Reginald knows: who he works for, their current records, and
    the user guide.

    The guide goes in verbatim rather than summarised, so the day it is edited
    he is right about the program again.  A hand-written summary here would be
    a second copy of the documentation, and it would rot."""
    voice = _PROGRAM_VOICE.get(mode, _PROGRAM_VOICE["band"])
    try:
        from ui.settings_dialog import school_name
        school = school_name(base_dir)
    except Exception:
        school = ""
    return SYSTEM_PROMPT_TEMPLATE.format(
        school_phrase=f" at {school}" if school else "",
        records=_build_combined_summary(db, band_db=band_db, mode=mode,
                                        base_dir=base_dir),
        **voice)


def _build_inventory_summary(db) -> str:
    """Build a compact text summary of the database for the system prompt."""
    lines = []
    try:
        stats = db.get_stats()
        lines += [
            f"Total instruments: {stats['total']}",
            f"  Available: {stats['available']}",
            f"  Checked out: {stats['checked_out']}",
            f"  In repair: {stats['in_repair']}",
        ]
    except Exception:
        lines.append("(Stats unavailable)")

    try:
        instruments = [dict(r) for r in db.get_instruments_with_status(include_inactive=False)]

        # Category breakdown
        cats = Counter(r.get("category") or "Unknown" for r in instruments)
        lines.append("\nBy category:")
        for cat, count in sorted(cats.items(), key=lambda x: -x[1]):
            co = sum(
                1 for r in instruments
                if (r.get("category") or "Unknown") == cat
                and r.get("status") == "Checked Out"
            )
            lines.append(f"  {cat}: {count} total, {co} checked out")

        # Condition breakdown
        conds = Counter(r.get("condition") or "Unknown" for r in instruments)
        lines.append(
            "\nCondition summary: "
            + ", ".join(f"{c}: {n}" for c, n in sorted(conds.items()))
        )
    except Exception:
        pass

    # Active checkouts with student names and instruments
    try:
        checkouts = db.get_all_active_checkouts()
        if checkouts:
            lines.append(f"\nActive checkouts ({len(checkouts)} total):")
            for c in checkouts:
                line = (
                    f"  {c.get('student_name') or '?'} — "
                    f"{c.get('description') or '?'}"
                    + (f" [{c.get('barcode') or c.get('district_no') or ''}]" if (c.get('barcode') or c.get('district_no')) else "")
                    + (f" (since {c['date_assigned']})" if c.get('date_assigned') else "")
                    + (f" DUE: {c['due_date']}" if c.get('due_date') else "")
                    + (f" Note: {c['notes']}" if c.get('notes') else "")
                )
                lines.append(line)
    except Exception:
        pass

    # Student roster — THIS year only.
    #
    # This used to hand over every active student in the database, which on a
    # program with a decade of history was 710 people going back to 2013 with
    # 664 of them long gone.  Asked who plays trumpet, he was as likely to name
    # somebody who graduated in 2016 as a child in the room, and the roster
    # alone was most of the prompt.  Previous years are summarised as counts;
    # if a question genuinely needs an old student, the teacher has Manage
    # Students and its archive.
    try:
        current = db.current_school_year()
        students = [dict(r) for r in db.get_all_students(current)]
        everyone = [dict(r) for r in db.get_all_students(include_inactive=True)]
        past = Counter((s.get("school_year") or "?") for s in everyone
                       if (s.get("school_year") or "") != current)
        lines.append(f"\nStudent roster for {current} "
                     f"({len(students)} student(s) enrolled now):")
        grades = Counter(s.get("grade") or "?" for s in students)
        grade_str = ", ".join(f"Grade {g}: {n}" for g, n in sorted(grades.items())
                              if g and g != "?")
        if grade_str:
            lines.append(f"  By grade: {grade_str}")
        if students:
            # Names only — no phone numbers, no email addresses.
            #
            # Knowing that Leo Chen's guardian is Wei Chen is what makes him
            # useful ("who do I ring about the trombone?"); shipping every
            # family's phone and email to an API on every single message is a
            # different thing entirely, and not something the teacher agreed
            # to each time she asks which flutes are out.  He is told below to
            # send her to Manage Students for the actual contact details,
            # which is one click and always current.
            lines.append("  Students (last, first — grade, guardian names):")
            for s in sorted(students, key=lambda x: ((x.get("last_name") or ""),
                                                     (x.get("first_name") or ""))):
                name = f"{s.get('last_name') or ''}, {s.get('first_name') or ''}".strip(", ")
                grade = s.get("grade") or ""
                guardians = [s[n] for n in ("parent1_name", "parent2_name")
                             if s.get(n)]
                line = f"    {name}" + (f" — Grade {grade}" if grade else "")
                if guardians:
                    line += f" Guardian(s): {'; '.join(guardians)}"
                lines.append(line)
            lines.append("  (Guardian phone numbers and email addresses are "
                         "deliberately not listed here — see the rule on "
                         "contact details.)")
        else:
            lines.append("  (No students on this year's roster yet — the class "
                         "lists have not been imported.)")
        if past:
            lines.append("  Earlier years, kept but not listed here: "
                         + ", ".join(f"{y} ({n})" for y, n in
                                     sorted(past.items(), reverse=True)))
    except Exception:
        pass

    return "\n".join(lines)

def _build_music_summary(db, mode: str = "band") -> str:
    """Build a compact text summary of the sheet music library for the system prompt."""
    lines = []
    try:
        rows = [dict(r) for r in db.get_all_sheet_music(include_inactive=False)]
        lines.append(f"Total pieces in library: {len(rows)}")

        genres = Counter(r.get("genre") or "Unknown" for r in rows)
        lines.append("\nBy genre: " + ", ".join(
            f"{g}: {n}" for g, n in sorted(genres.items(), key=lambda x: -x[1])
        ))

        if mode == "choir":
            voicings = Counter(r.get("voicing") or "Unknown" for r in rows)
            lines.append("By voicing: " + ", ".join(
                f"{v}: {n}" for v, n in sorted(voicings.items(), key=lambda x: -x[1])
            ))
            langs = Counter(r.get("language") or "Unknown" for r in rows)
            lines.append("By language: " + ", ".join(
                f"{l}: {n}" for l, n in sorted(langs.items(), key=lambda x: -x[1])
            ))
            accs = Counter(r.get("accompaniment") or "Unknown" for r in rows)
            lines.append("By accompaniment: " + ", ".join(
                f"{a}: {n}" for a, n in sorted(accs.items(), key=lambda x: -x[1])
            ))
        else:
            ensembles = Counter(r.get("ensemble_type") or "Unknown" for r in rows)
            lines.append("By ensemble: " + ", ".join(
                f"{e}: {n}" for e, n in sorted(ensembles.items(), key=lambda x: -x[1])
            ))

        diffs = Counter(r.get("difficulty") or "?" for r in rows)
        lines.append("By difficulty: " + ", ".join(
            f"{d}: {n}" for d, n in sorted(diffs.items())
        ))

        locs = Counter(r.get("location") or "Unknown" for r in rows)
        if len(locs) > 1:
            lines.append("By location: " + ", ".join(
                f"{l}: {n}" for l, n in sorted(locs.items(), key=lambda x: -x[1])
            ))

        if mode == "choir":
            lines.append("\nFull piece list (title — composer/arranger | genre | voicing | language | difficulty | publisher | location):")
            for r in sorted(rows, key=lambda x: (x.get("title") or "").lower()):
                title = r.get("title") or "?"
                composer = r.get("composer") or ""
                arranger = r.get("arranger") or ""
                credit = composer + (f" arr. {arranger}" if arranger else "")
                meta = " | ".join(filter(None, [
                    r.get("genre") or "",
                    r.get("voicing") or "",
                    r.get("language") or "",
                    r.get("accompaniment") or "",
                    f"Grade {r.get('difficulty')}" if r.get("difficulty") else "",
                    r.get("key_signature") or "",
                    r.get("publisher") or "",
                    r.get("location") or "",
                ]))
                line = f"  {title}"
                if credit:
                    line += f" — {credit}"
                if meta:
                    line += f"  [{meta}]"
                lines.append(line)
        else:
            lines.append("\nFull piece list (title — composer/arranger | genre | ensemble | difficulty | publisher | location):")
            for r in sorted(rows, key=lambda x: (x.get("title") or "").lower()):
                title = r.get("title") or "?"
                composer = r.get("composer") or ""
                arranger = r.get("arranger") or ""
                credit = composer + (f" arr. {arranger}" if arranger else "")
                meta = " | ".join(filter(None, [
                    r.get("genre") or "",
                    r.get("ensemble_type") or "",
                    f"Grade {r.get('difficulty')}" if r.get("difficulty") else "",
                    r.get("key_signature") or "",
                    r.get("time_signature") or "",
                    r.get("publisher") or "",
                    r.get("location") or "",
                ]))
                line = f"  {title}"
                if credit:
                    line += f" — {credit}"
                if meta:
                    line += f"  [{meta}]"
                lines.append(line)
    except Exception:
        lines.append("(Music library data unavailable)")
    return "\n".join(lines)


def _build_uniform_summary(db) -> str:
    """Uniforms and attire — a whole module he previously knew nothing about."""
    lines = []
    try:
        stats = db.get_uniform_stats()
        if not stats.get("total"):
            return ""
        lines.append(f"Garments: {stats['total']} total, "
                     f"{stats['checked_out']} out, {stats['available']} available")
        out = [dict(r) for r in db.get_all_active_uniform_checkouts()]
        if out:
            lines.append(f"Currently assigned ({len(out)}):")
            for c in out[:200]:
                who = c.get("student_name") or "?"
                what = " ".join(str(x) for x in (c.get("garment_type"),
                                                 c.get("size"),
                                                 c.get("item_number")) if x)
                lines.append(f"  {who} — {what}")
    except Exception:
        return ""
    return "\n".join(lines)


def _build_money_summary(db, school_year) -> str:
    """What the children owe.  He is asked this constantly and could not answer."""
    lines = []
    try:
        for fee in db.get_fee_types():
            name = fee["name"] if "name" in fee.keys() else None
            if not name:
                continue
            unpaid = db.get_unpaid_fee(name, school_year)
            if not unpaid:
                continue
            owed = sum(float(u.get("amount") or 0) for u in unpaid)
            lines.append(f"{name}: {len(unpaid)} student(s) unpaid, ${owed:,.2f} outstanding")
            for u in unpaid[:60]:
                who = f"{u.get('first_name') or ''} {u.get('last_name') or ''}".strip()
                lines.append(f"  {who or '?'} — ${float(u.get('amount') or 0):,.2f}")
    except Exception:
        return ""
    return "\n".join(lines)


def _build_repair_summary(db) -> str:
    """What is broken and where it is."""
    lines = []
    try:
        pending = [dict(r) for r in db.get_pending_repairs()]
        if not pending:
            return "Nothing is currently awaiting repair."
        lines.append(f"Open repairs ({len(pending)}):")
        for r in pending[:120]:
            what = r.get("instrument_desc") or "?"
            tag = r.get("barcode") or r.get("district_no") or r.get("serial_no") or ""
            issue = (r.get("issue") or r.get("description") or "").strip()
            vendor = (r.get("vendor") or "").strip()
            line = f"  {what}" + (f" #{tag}" if tag else "")
            if issue:
                line += f" — {issue[:120]}"
            if vendor:
                line += f" (at {vendor})"
            lines.append(line)
    except Exception:
        return ""
    return "\n".join(lines)


def _build_calendar_summary(base_dir, school_year) -> str:
    """Concerts and trips for this year, from the per-year Teacher Tools file.

    These live in a different database from the instruments, which is why he
    could never answer "when is the winter concert"."""
    lines = []
    try:
        from lesson_plan_db import get_lesson_plan_db
        pdb = get_lesson_plan_db(base_dir, school_year)
    except Exception:
        return ""
    try:
        concerts = [dict(c) for c in pdb.get_concerts(school_year)]
        if concerts:
            lines.append("Concerts:")
            for c in concerts:
                bits = [c.get("title") or "(untitled)", c.get("concert_date") or "date TBC"]
                if c.get("start_time"):
                    bits.append(str(c["start_time"]))
                if c.get("location"):
                    bits.append(str(c["location"]))
                if c.get("ensembles"):
                    bits.append(f"ensembles: {c['ensembles']}")
                lines.append("  " + " — ".join(str(b) for b in bits))
    except Exception:
        pass
    try:
        trips = [dict(t) for t in pdb.get_field_trips(school_year)]
        if trips:
            lines.append("Field trips:")
            for t in trips:
                bits = [t.get("name") or "(untitled)", t.get("depart_date") or "date TBC"]
                if t.get("destination"):
                    bits.append(str(t["destination"]))
                lines.append("  " + " — ".join(str(b) for b in bits))
    except Exception:
        pass
    return "\n".join(lines)


def _build_help_summary() -> str:
    """The user guide, as plain text.

    Read from help/roka_help.html at run time rather than restated here, so
    editing the guide is the only place the program's behaviour is written
    down.  A hand-maintained copy in this file is how an assistant ends up
    confidently describing a screen that was removed two versions ago."""
    try:
        from ui.help_system import help_file_path
        path = help_file_path()
        if not path:
            return ""
        html = open(path, encoding="utf-8").read()
    except Exception:
        return ""
    body = html.split("<script>")[0]
    body = re.sub(r"<style.*?</style>", " ", body, flags=re.S)
    body = re.sub(r"<!--.*?-->", " ", body, flags=re.S)
    text = re.sub(r"<[^>]+>", " ", body)
    text = (text.replace("&amp;", "&").replace("&lt;", "<")
                .replace("&gt;", ">").replace("&quot;", '"')
                .replace("&times;", "x").replace("&nbsp;", " "))
    text = re.sub(r"[ \t]+", " ", text)
    return "\n".join(l.strip() for l in text.splitlines() if l.strip())


def _build_combined_summary(db, band_db=None, mode: str = "band",
                            base_dir: str = None) -> str:
    """Everything Reginald is told about this teacher's program.

    He used to be given instruments, students and music only, which is why he
    was blank on uniforms, money, repairs and anything in Teacher Tools — and
    why he could not say how the program worked at all.
    """
    sections = []
    inv_db = band_db if (mode == "choir" and band_db is not None) else db
    try:
        year = inv_db.current_school_year()
    except Exception:
        year = ""

    if year:
        sections.append(
            "=== TODAY ===\n"
            f"Date: {date.today():%A %d %B %Y}\n"
            f"Current school year: {year}\n"
            f"Program type: {mode}")

    if mode != "choir" or band_db is not None:
        inv = _build_inventory_summary(inv_db)
        if inv:
            sections.append("=== INSTRUMENT INVENTORY & STUDENTS ===\n" + inv)

        for label, text in (
                ("UNIFORMS & ATTIRE", _build_uniform_summary(inv_db)),
                ("REPAIRS", _build_repair_summary(inv_db)),
                ("STUDENT FEES OWED", _build_money_summary(inv_db, year)),
        ):
            if text:
                sections.append(f"=== {label} ===\n" + text)

    music_label = "CHORAL MUSIC LIBRARY" if mode == "choir" else "SHEET MUSIC LIBRARY"
    music = _build_music_summary(db, mode=mode)
    if music:
        sections.append(f"=== {music_label} ===\n" + music)

    if base_dir and year:
        upcoming = _build_calendar_summary(base_dir, year)
        if upcoming:
            sections.append("=== CONCERTS & FIELD TRIPS THIS YEAR ===\n" + upcoming)

    guide = _build_help_summary()
    if guide:
        sections.append(
            "=== THE USER GUIDE FOR THIS PROGRAM ===\n"
            "This is the whole of Roka's help guide. Answer any question about "
            "how to use the program from it, naming the screen and the button. "
            "If something is not in here, the program does not do it.\n\n"
            + guide)

    return "\n\n".join(sections)


class ChatDialog(ttk.Toplevel):
    def __init__(self, parent, db, base_dir: str, selected_instrument: dict = None,
                 summary_fn=None, selected_music: dict = None, mode: str = "band"):
        super().__init__(parent)
        self.db = db
        self.base_dir = base_dir
        self._mode = mode
        self.selected_instrument = selected_instrument
        self.selected_music = selected_music
        self._music_mode = selected_music is not None or summary_fn is not None

        # For choir mode, also load the main band DB for instrument/student context
        self._band_db = None
        if mode == "choir":
            try:
                import os
                from database import Database
                band_db_path = os.path.join(base_dir, "rokas_resonance.db")
                if os.path.exists(band_db_path):
                    self._band_db = Database(band_db_path)
            except Exception:
                pass

        self._summary_fn = lambda: _build_combined_summary(
            db, band_db=self._band_db, mode=self._mode, base_dir=base_dir)

        self.title("Ask Reginald — Roka's Resonance")
        self.resizable(True, True)
        # Not modal — user can still browse inventory while chatting

        self._build()

        from ui.theme import fit_window
        fit_window(self, 520, 480)
        self.minsize(380, 300)

        # Opening line
        self._add_message(
            "reginald",
            "Reginald Pemberton III, at your service. What do you need?"
        )

    # ──────────────────────────────────────────────────────────────── Build ──

    def _build(self):
        # Header
        hdr = ttk.Frame(self, bootstyle=DARK)
        hdr.pack(fill=X)
        ttk.Label(
            hdr,
            text="  🎩  Reginald — Inventory Assistant",
            font=("Segoe UI", fs(12), "bold"),
            bootstyle=(INVERSE, DARK),
        ).pack(side=LEFT, pady=10, padx=12)
        ttk.Label(
            hdr,
            text="grumpy butler · retired musician  ",
            font=("Segoe UI", fs(8), "italic"),
            bootstyle=(INVERSE, DARK),
        ).pack(side=RIGHT, pady=10, padx=4)

        # Input bar, context label, and separator are packed BOTTOM-first so the
        # input stays anchored when the window is resized smaller than its content.
        input_frame = ttk.Frame(self)
        input_frame.pack(side=BOTTOM, fill=X, padx=10, pady=8)

        self._ctx_label = ttk.Label(
            self, text="", font=("Segoe UI", fs(8)), foreground="#888"
        )
        self._ctx_label.pack(side=BOTTOM, anchor=W, padx=12, pady=(4, 0))

        ttk.Separator(self).pack(side=BOTTOM, fill=X, padx=10, pady=(6, 0))

        # Chat area fills the remaining space between the header and the bottom bar.
        chat_frame = ttk.Frame(self)
        chat_frame.pack(fill=BOTH, expand=True, padx=10, pady=(8, 0))

        sb = ttk.Scrollbar(chat_frame, orient=VERTICAL)
        self._chat_text = tk.Text(
            chat_frame,
            wrap=WORD,
            state="disabled",
            height=10,
            font=("Segoe UI", fs(9)),
            relief="flat",
            padx=10,
            pady=6,
            yscrollcommand=sb.set,
            cursor="arrow",
        )
        sb.config(command=self._chat_text.yview)
        sb.pack(side=RIGHT, fill=Y)
        self._chat_text.pack(fill=BOTH, expand=True)

        # Styling tags
        self._chat_text.tag_configure(
            "user_label", font=("Segoe UI", fs(8), "bold"), foreground="#1a5fa8"
        )
        self._chat_text.tag_configure(
            "user_text", font=("Segoe UI", fs(9)), foreground="#1a5fa8",
            lmargin1=4, lmargin2=4,
        )
        self._chat_text.tag_configure(
            "user_text_bold", font=("Segoe UI", fs(9), "bold"), foreground="#1a5fa8",
            lmargin1=4, lmargin2=4,
        )
        self._chat_text.tag_configure(
            "reg_label", font=("Segoe UI", fs(8), "bold"), foreground="#5a3a00"
        )
        self._chat_text.tag_configure(
            "reg_text", font=("Segoe UI", fs(9)), foreground="#222",
            lmargin1=4, lmargin2=4,
        )
        self._chat_text.tag_configure(
            "reg_text_bold", font=("Segoe UI", fs(9), "bold"), foreground="#222",
            lmargin1=4, lmargin2=4,
        )
        self._chat_text.tag_configure(
            "thinking", font=("Segoe UI", fs(9), "italic"), foreground="#999"
        )
        self._chat_text.tag_configure(
            "error_text", font=("Segoe UI", fs(9), "italic"), foreground="#cc0000"
        )

        self._update_context_label()

        self._input_var = tk.StringVar()
        self._input_entry = ttk.Entry(
            input_frame,
            textvariable=self._input_var,
            font=("Segoe UI", fs(10)),
        )
        self._input_entry.pack(side=LEFT, fill=X, expand=True, padx=(0, 6))
        self._input_entry.bind("<Return>", lambda e: self._send())
        self._input_entry.focus_set()

        self._send_btn = ttk.Button(
            input_frame,
            text="Send",
            bootstyle=PRIMARY,
            command=self._send,
            width=8,
        )
        self._send_btn.pack(side=LEFT)

    # ────────────────────────────────────────────────────────── Chat Logic ──

    def update_selected_instrument(self, instrument: dict):
        """Called by the inventory manager when selection changes."""
        self.selected_instrument = instrument
        self._update_context_label()

    def update_selected_music(self, piece: dict):
        """Called by the music manager when selection changes."""
        self.selected_music = piece
        self._update_context_label()

    def _update_context_label(self):
        if self.selected_music is not None:
            title = self.selected_music.get("title") or "Unknown"
            composer = self.selected_music.get("composer") or ""
            suffix = f" — {composer}" if composer else ""
            self._ctx_label.config(text=f"Selected: {title}{suffix}")
        elif self.selected_instrument:
            desc = self.selected_instrument.get("description") or "Unknown"
            bc = self.selected_instrument.get("barcode") or ""
            suffix = f"  (Barcode: {bc})" if bc else ""
            self._ctx_label.config(text=f"Context: {desc}{suffix}")
        else:
            self._ctx_label.config(text="Asking about general inventory")

    def _insert_with_bold(self, text: str, base_tag: str):
        """Insert text into the chat widget, rendering **bold** spans."""
        import re
        bold_tag = base_tag + "_bold"
        parts = re.split(r"\*\*(.+?)\*\*", text)
        for i, part in enumerate(parts):
            tag = bold_tag if i % 2 == 1 else base_tag
            self._chat_text.insert("end", part, tag)

    def _add_message(self, role: str, text: str):
        self._chat_text.config(state="normal")
        if role == "user":
            self._chat_text.insert("end", "You\n", "user_label")
            self._insert_with_bold(text + "\n\n", "user_text")
        elif role == "reginald":
            self._chat_text.insert("end", "Reginald\n", "reg_label")
            self._insert_with_bold(text + "\n\n", "reg_text")
        elif role == "thinking":
            self._chat_text.insert("end", text + "\n", "thinking")
        elif role == "error":
            self._chat_text.insert("end", "⚠ " + text + "\n\n", "error_text")
        self._chat_text.config(state="disabled")
        self._chat_text.see("end")

    def _remove_thinking(self):
        self._chat_text.config(state="normal")
        content = self._chat_text.get("1.0", "end")
        marker = "Reginald is composing his thoughts…\n"
        idx = content.rfind(marker)
        if idx >= 0:
            line_num = content[:idx].count("\n") + 1
            self._chat_text.delete(f"{line_num}.0", f"{line_num}.0+{len(marker)}c")
        self._chat_text.config(state="disabled")

    def _build_user_prompt(self, message: str) -> str:
        parts = []
        if self.selected_music:
            m = self.selected_music
            parts.append("Currently selected piece:")
            parts.append(f"  Title: {m.get('title') or 'N/A'}")
            parts.append(f"  Composer: {m.get('composer') or 'N/A'}  Arranger: {m.get('arranger') or ''}")
            if self._mode == "choir":
                parts.append(f"  Genre: {m.get('genre') or 'N/A'}  Voicing: {m.get('voicing') or 'N/A'}")
                parts.append(f"  Language: {m.get('language') or 'N/A'}  Accompaniment: {m.get('accompaniment') or 'N/A'}")
                parts.append(f"  Difficulty: {m.get('difficulty') or 'N/A'}  Key: {m.get('key_signature') or 'N/A'}")
            else:
                parts.append(f"  Genre: {m.get('genre') or 'N/A'}  Ensemble: {m.get('ensemble_type') or 'N/A'}")
                parts.append(f"  Difficulty: {m.get('difficulty') or 'N/A'}  Key: {m.get('key_signature') or 'N/A'}  Time: {m.get('time_signature') or 'N/A'}")
            parts.append(f"  Publisher: {m.get('publisher') or 'N/A'}  Location: {m.get('location') or 'N/A'}")
            if m.get("notes"):
                parts.append(f"  Comments: {m.get('notes')}")
            try:
                perfs = [dict(p) for p in self.db.get_performances(m.get("id"))]
                if perfs:
                    parts.append(f"  Performance history ({len(perfs)} performance(s)):")
                    for p in perfs:
                        line = f"    - {p.get('performance_date') or 'Unknown date'}"
                        if p.get("event_name"):
                            line += f" | {p.get('event_name')}"
                        if p.get("ensemble"):
                            line += f" | {p.get('ensemble')}"
                        if p.get("notes"):
                            line += f" | {p.get('notes')}"
                        parts.append(line)
                else:
                    parts.append("  Performance history: never performed")
            except Exception:
                pass
            parts.append("")
        elif self.selected_instrument:
            inst = self.selected_instrument
            active = None
            repairs = []
            try:
                active = self.db.get_active_checkout(inst.get("id"))
            except Exception:
                pass
            try:
                repairs = [dict(r) for r in self.db.get_repairs(inst.get("id"))]
            except Exception:
                pass
            parts.append("Currently selected instrument:")
            parts.append(f"  Description: {inst.get('description') or 'N/A'}")
            parts.append(f"  Category: {inst.get('category') or 'N/A'}")
            parts.append(f"  Brand: {inst.get('brand') or 'N/A'}  Model: {inst.get('model') or 'N/A'}")
            parts.append(f"  Barcode: {inst.get('barcode') or 'N/A'}  District #: {inst.get('district_no') or 'N/A'}  Serial: {inst.get('serial_no') or 'N/A'}")
            parts.append(f"  Condition: {inst.get('condition') or 'N/A'}")
            if inst.get("comments"):
                parts.append(f"  Condition notes: {inst.get('comments')}")
            if inst.get("year_purchased"):
                parts.append(f"  Year purchased: {inst.get('year_purchased')}")
            if inst.get("est_value") or inst.get("amount_paid"):
                parts.append(f"  Est. value: ${inst.get('est_value') or 0}  Amount paid: ${inst.get('amount_paid') or 0}")
            if inst.get("last_service"):
                parts.append(f"  Last serviced: {inst.get('last_service')}")
            if active:
                parts.append(
                    f"  Checked out to: {active['student_name']} since {active['date_assigned']}"
                )
            else:
                parts.append("  Status: Available")
            if repairs:
                total = sum(
                    float(r.get("act_cost") or r.get("est_cost") or 0)
                    for r in repairs
                )
                parts.append(f"  Repair records ({len(repairs)} total, ${total:.2f} cumulative cost):")
                for r in repairs:
                    cost = r.get("act_cost") or r.get("est_cost") or 0
                    desc = r.get("description") or "No description"
                    shop = r.get("assigned_to") or r.get("location") or ""
                    date_added = r.get("date_added") or ""
                    parts.append(
                        f"    - {desc}"
                        + (f" | Shop: {shop}" if shop else "")
                        + (f" | Cost: ${float(cost):.2f}" if cost else "")
                        + (f" | Date: {date_added}" if date_added else "")
                    )
            else:
                parts.append("  Repair records: none on file")
            parts.append("")
        parts.append(message)
        return "\n".join(parts)

    def _send(self):
        message = self._input_var.get().strip()
        if not message:
            return

        from llm_client import is_configured
        if not is_configured(self.base_dir):
            self._add_message(
                "error",
                "No API key configured. Open Settings and enter your GitHub token "
                "— then Reginald can assist you properly."
            )
            return

        self._input_var.set("")
        self._send_btn.config(state="disabled")
        self._input_entry.config(state="disabled")

        self._add_message("user", message)
        self._add_message("thinking", "Reginald is composing his thoughts…")

        def _run():
            try:
                system_prompt = build_system_prompt(
                    self.db, self.base_dir, mode=self._mode,
                    band_db=self._band_db)
                user_prompt = self._build_user_prompt(message)
                from llm_client import query
                reply = query(self.base_dir, user_prompt, system_prompt)
                self.after(0, self._on_reply, reply, None)
            except Exception as e:
                self.after(0, self._on_reply, None, str(e))

        threading.Thread(target=_run, daemon=True).start()

    def _on_reply(self, reply: str, error: str):
        self._remove_thinking()
        if error:
            self._add_message("error", f"Query failed: {error}")
        else:
            self._add_message("reginald", reply)
        self._send_btn.config(state="normal")
        self._input_entry.config(state="normal")
        self._input_entry.focus_set()
