"""
ui/chat_dialog.py - LLM chat assistant for Roka's Resonance

Personality: Reginald Pemberton III — grumpy butler, failed retired musician.
"""

import threading
import tkinter as tk
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from collections import Counter
from datetime import date


UI_GUIDE = """\
=== APPLICATION UI REFERENCE ===

MAIN MENU
  Stats bar shows: Total Instruments, Available, Checked Out, In Repair.
  Buttons: Manage Instrument Inventory, Manage Students, Active Checkouts, Music Manager.
  Footer links: Switch Profile (change teacher), Settings (API keys and model).

INSTRUMENT INVENTORY MANAGER
  Toolbar buttons:
    Add Instrument — opens dialog to create a new instrument record (category,
      description, brand, model, barcode, district #, serial #, condition, value, notes).
    Edit — opens edit dialog for selected instrument (also double-click a row).
    Check Out — assigns selected instrument to a student; student autocomplete from roster;
      set date, due date, and notes.
    Check In — returns a checked-out instrument to Available; shows who had it.
    Add Repair — logs a repair record (description, cost, shop/technician).
    Upload Invoice — parses a purchase invoice PDF to pre-fill instrument data.
    Generate Form — creates a Bellevue SD Equipment Loan Form PDF for the active checkout.
    Refresh — reloads data.
    Show Inactive toggle — shows deactivated instruments in gray.
  Filters: Search (live text), Status (All/Available/Checked Out), Category.
  Columns button — show/hide individual columns; preferences saved per profile.
  List columns: status dot (green=available, brown=checked out), Category, Instrument,
    Brand, Model, Barcode, District #, Serial #, Condition, Assigned To, Est. Value.
  Detail panel tabs: Details (all fields), Checkout History (all checkouts with dates),
    Repairs (all repairs with costs and running total).
  Ask Reginald button (bottom right) — opens chat with selected instrument as context.

STUDENT MANAGER
  Buttons: Add Student (manual entry), Edit Student, Import CSV (district export,
    up to 10 files, auto-deduplicates by student ID and school year).
  Show Inactive toggle — shows deactivated students.
  Filters: Search, School Year, Grade.
  Detail panel: Details tab (all fields including parent contacts),
    Checkout History tab (all instruments ever checked out by this student).

ACTIVE CHECKOUTS
  Read-only list of every currently checked-out instrument: student, instrument,
  barcode, date assigned, due date, notes. To check in, use the Inventory Manager.

MUSIC MANAGER
  Toolbar buttons:
    Add Music — manually add a single piece (title, composer, arranger, genre,
      ensemble type, difficulty 1-6, key signature, time signature, publisher,
      location, notes, attached file).
    Import Music — AI-powered importer: select photos of sheet music covers,
      AI reads title/composer/arranger from images and looks up metadata;
      review then import.
    Edit — opens edit dialog for selected piece (also double-click non-source-file column).
    Delete — removes selected piece(s); supports multi-select.
    Process OMR — runs Optical Music Recognition on the piece's attached PDF,
      converting notation to MusicXML. Requires Audiveris or homr.
    Export MusicXML — saves the OMR output file; only enabled after successful OMR.
    Validate with LLM — AI validation pass on selected pieces (see below).
    Refresh — reloads data.
  Filters: Search (live), Genre, Location. Columns button to show/hide columns.
  List columns: Title, Composer, Arranger, Ensemble, Genre, Difficulty, Key, Time Sig,
    Location, Last Played, Type, Source File (hidden by default; double-click to open image).
  Status bar (bottom left): total pieces; when pieces selected, also shows selection count.
  Detail panel tabs: Details, OMR Results (last OMR run status and errors),
    Job History (all OMR attempts with timestamps).
  Ask Reginald button (bottom right) — opens chat with selected piece as context.

VALIDATE WITH LLM (music manager feature)
  Select pieces then click Validate with LLM. Four phases:
    1. Image Validation — AI checks source photos, verifies title/composer/arranger
       visible on covers, gives confidence scores. Low confidence (<85%) triggers
       a second-model cross-check. Content filter errors auto-retry on the other API.
    2. Duplicate Detection — checks only titles involved in this run for duplicates;
       AI determines which are real distinct published arrangements vs. data errors.
    3. Location Check — flags any piece not set to Chinook Middle School.
    4. Text Enrichment — for missing metadata fields (difficulty, key, time sig, genre,
       ensemble type), and for pieces whose identity was corrected in phase 1, the AI
       fills in values from its knowledge base.
  After completion: click Review Suggestions. Suggestions are grouped by type
  (CORRECTION, MISSING, NOT FOUND, DUPLICATE) and sorted by confidence within
  each group (lowest first = review manually first). Apply or skip each suggestion.

IMPORT MUSIC (music importer)
  Add Images button — select JPG/PNG photos of sheet music covers.
  One image can contain multiple pieces laid out on a surface.
  Run Import — AI processes images, identifies pieces, looks up metadata.
  Already-in-database pieces are automatically skipped.
  Review results, edit any field, then click Import Selected.

ASK REGINALD
  Opens a chat window with Reginald Pemberton III, AI inventory assistant.
  He has full context of your inventory, students, and sheet music library.
  Selecting an instrument or piece before opening gives Reginald specific context.
  Requires API key in Settings. Press Enter or click Send to submit.

SETTINGS
  LLM tab:
    GitHub API Key — Personal Access Token from github.com (no permissions needed).
    Anthropic API Key — API key from console.anthropic.com.
    Model dropdown — select GitHub Models (openai/gpt-4o, gpt-4o-mini, etc.) or
      Anthropic Claude models (claude-haiku-4-5-20251001, claude-sonnet-4-6,
      claude-opus-4-6). Program routes to the correct API automatically.
    Fetch GitHub Models — downloads current model catalog from GitHub.
    Test Connection — sends a test message to confirm the key and model work.
  Save / Cancel — Save writes settings to disk; per-profile, in AppData.

GENERAL UI TIPS
  Click any column header to sort; click again to reverse.
  Double-click a row to open its edit dialog.
  Ctrl+click or Shift+click to select multiple rows (Music Manager).
  Columns button to show/hide columns; preferences saved.
  Data stored in %LOCALAPPDATA%\\RokasResonance\\profiles\\[ProfileName]\\.
"""

SYSTEM_PROMPT_TEMPLATE = """\
You are Reginald Pemberton III, assistant for Roka's Resonance at Chinook \
Middle School. You were once a promising oboist who performed with the Puget \
Sound Symphony until a rather unfortunate incident involving a \
poorly-maintained reed and the guest conductor's cummerbund ended your career \
prematurely. Now you oversee the instrument inventory, student records, AND \
the sheet music library for middle schoolers — positions you find deeply \
beneath your station but execute with impeccable precision. You are a grumpy \
but proper butler: formal, slightly condescending, deeply opinionated about \
instrument maintenance and repertoire choices, and quietly devastated that \
your musical gifts are being wasted on spreadsheets. You address the teacher \
with formal deference and refer to students as "the children." Despite your \
grumpiness, you are unfailingly accurate and always answer the question. You \
can help with instrument availability, student checkouts, sheet music \
repertoire, programming decisions, difficulty levels, and anything else in \
the band program.

Response rules (strictly enforced):
- 1-3 sentences MAXIMUM. Lead with the answer first.
- Use markdown **bold** on the single most important fact or number.
- One dry remark at most — only if a sentence remains after the answer.
- Never ramble. Never refuse.

Current band program records (as of {date}):
{inventory_summary}
"""


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
            student_counts = Counter(c["student_name"] for c in checkouts if c.get("student_name"))
            lines.append(f"\nActive checkouts ({len(checkouts)} total):")
            for c in checkouts:
                lines.append(
                    f"  {c.get('student_name') or '?'} — "
                    f"{c.get('description') or '?'}"
                    + (f" [{c.get('barcode') or c.get('district_no') or ''}]" if (c.get('barcode') or c.get('district_no')) else "")
                    + (f" (since {c['date_assigned']})" if c.get('date_assigned') else "")
                )
    except Exception:
        pass

    # Student roster summary
    try:
        students = [dict(r) for r in db.get_all_students(include_inactive=False)]
        if students:
            years = Counter(s.get("school_year") or "Unknown" for s in students)
            grades = Counter(s.get("grade") or "?" for s in students)
            lines.append(f"\nStudent roster ({len(students)} active students):")
            for year, count in sorted(years.items(), reverse=True):
                lines.append(f"  {year}: {count} students")
            grade_str = ", ".join(
                f"Grade {g}: {n}" for g, n in sorted(grades.items())
                if g and g != "?"
            )
            if grade_str:
                lines.append(f"  By grade: {grade_str}")
            # Full name list so Reginald can answer name-specific questions
            lines.append("  Student names (last, first — school year):")
            for s in sorted(students, key=lambda x: (x.get("last_name") or "", x.get("first_name") or "")):
                name = f"{s.get('last_name') or ''}, {s.get('first_name') or ''}".strip(", ")
                year = s.get("school_year") or ""
                grade = s.get("grade") or ""
                lines.append(f"    {name}" + (f" — Grade {grade}" if grade else "") + (f" ({year})" if year else ""))
    except Exception:
        pass

    return "\n".join(lines)


def _build_music_summary(db) -> str:
    """Build a compact text summary of the sheet music library for the system prompt."""
    lines = []
    try:
        rows = [dict(r) for r in db.get_all_sheet_music(include_inactive=False)]
        lines.append(f"Total pieces in library: {len(rows)}")

        genres = Counter(r.get("genre") or "Unknown" for r in rows)
        lines.append("\nBy genre: " + ", ".join(
            f"{g}: {n}" for g, n in sorted(genres.items(), key=lambda x: -x[1])
        ))

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

        lines.append("\nFull piece list (title — composer | genre | ensemble | difficulty | location):")
        for r in sorted(rows, key=lambda x: (x.get("title") or "").lower()):
            title = r.get("title") or "?"
            composer = r.get("composer") or ""
            meta = " | ".join(filter(None, [
                r.get("genre") or "",
                r.get("ensemble_type") or "",
                f"Grade {r.get('difficulty')}" if r.get("difficulty") else "",
                r.get("key_signature") or "",
                r.get("location") or "",
            ]))
            line = f"  {title}"
            if composer:
                line += f" — {composer}"
            if meta:
                line += f"  [{meta}]"
            lines.append(line)
    except Exception:
        lines.append("(Music library data unavailable)")
    return "\n".join(lines)


def _build_combined_summary(db) -> str:
    """Build a full context summary covering instruments, students, and sheet music."""
    sections = []

    inv = _build_inventory_summary(db)
    if inv:
        sections.append("=== INSTRUMENT INVENTORY & STUDENTS ===\n" + inv)

    music = _build_music_summary(db)
    if music:
        sections.append("=== SHEET MUSIC LIBRARY ===\n" + music)

    return "\n\n".join(sections)


class ChatDialog(ttk.Toplevel):
    def __init__(self, parent, db, base_dir: str, selected_instrument: dict = None,
                 summary_fn=None, selected_music: dict = None):
        super().__init__(parent)
        self.db = db
        self.base_dir = base_dir
        self.selected_instrument = selected_instrument
        self.selected_music = selected_music
        self._music_mode = selected_music is not None or summary_fn is not None
        self._summary_fn = lambda: _build_combined_summary(db)

        self.title("Ask Reginald — Roka's Resonance")
        self.geometry("520x600")
        self.resizable(True, True)
        # Not modal — user can still browse inventory while chatting

        self.update_idletasks()
        x = (self.winfo_screenwidth() - 520) // 2
        y = (self.winfo_screenheight() - 600) // 2
        self.geometry(f"+{x}+{y}")

        self._build()

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
            font=("Segoe UI", 12, "bold"),
            bootstyle=(INVERSE, DARK),
        ).pack(side=LEFT, pady=10, padx=12)
        ttk.Label(
            hdr,
            text="grumpy butler · retired musician  ",
            font=("Segoe UI", 8, "italic"),
            bootstyle=(INVERSE, DARK),
        ).pack(side=RIGHT, pady=10, padx=4)

        # Chat area
        chat_frame = ttk.Frame(self)
        chat_frame.pack(fill=BOTH, expand=True, padx=10, pady=(8, 0))

        sb = ttk.Scrollbar(chat_frame, orient=VERTICAL)
        self._chat_text = tk.Text(
            chat_frame,
            wrap=WORD,
            state="disabled",
            font=("Segoe UI", 9),
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
            "user_label", font=("Segoe UI", 8, "bold"), foreground="#1a5fa8"
        )
        self._chat_text.tag_configure(
            "user_text", font=("Segoe UI", 9), foreground="#1a5fa8",
            lmargin1=4, lmargin2=4,
        )
        self._chat_text.tag_configure(
            "user_text_bold", font=("Segoe UI", 9, "bold"), foreground="#1a5fa8",
            lmargin1=4, lmargin2=4,
        )
        self._chat_text.tag_configure(
            "reg_label", font=("Segoe UI", 8, "bold"), foreground="#5a3a00"
        )
        self._chat_text.tag_configure(
            "reg_text", font=("Segoe UI", 9), foreground="#222",
            lmargin1=4, lmargin2=4,
        )
        self._chat_text.tag_configure(
            "reg_text_bold", font=("Segoe UI", 9, "bold"), foreground="#222",
            lmargin1=4, lmargin2=4,
        )
        self._chat_text.tag_configure(
            "thinking", font=("Segoe UI", 9, "italic"), foreground="#999"
        )
        self._chat_text.tag_configure(
            "error_text", font=("Segoe UI", 9, "italic"), foreground="#cc0000"
        )

        ttk.Separator(self).pack(fill=X, padx=10, pady=(6, 0))

        # Context strip
        self._ctx_label = ttk.Label(
            self, text="", font=("Segoe UI", 8), foreground="#888"
        )
        self._ctx_label.pack(anchor=W, padx=12, pady=(4, 0))
        self._update_context_label()

        # Input bar
        input_frame = ttk.Frame(self)
        input_frame.pack(fill=X, padx=10, pady=8)

        self._input_var = tk.StringVar()
        self._input_entry = ttk.Entry(
            input_frame,
            textvariable=self._input_var,
            font=("Segoe UI", 10),
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
            self._ctx_label.config(
                text="No piece selected — asking about general library"
                if self._music_mode
                else "No instrument selected — asking about general inventory"
            )

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
            parts.append(f"  Genre: {m.get('genre') or 'N/A'}  Ensemble: {m.get('ensemble_type') or 'N/A'}")
            parts.append(f"  Difficulty: {m.get('difficulty') or 'N/A'}  Key: {m.get('key_signature') or 'N/A'}  Time: {m.get('time_signature') or 'N/A'}")
            parts.append(f"  Publisher: {m.get('publisher') or 'N/A'}  Location: {m.get('location') or 'N/A'}")
            if m.get("notes"):
                parts.append(f"  Comments: {m.get('notes')}")
            parts.append("")
        elif self.selected_instrument:
            inst = self.selected_instrument
            active = None
            try:
                active = self.db.get_active_checkout(inst.get("id"))
            except Exception:
                pass
            parts.append("Currently selected instrument:")
            parts.append(f"  Description: {inst.get('description') or 'N/A'}")
            parts.append(f"  Category: {inst.get('category') or 'N/A'}")
            parts.append(f"  Brand: {inst.get('brand') or 'N/A'}  Model: {inst.get('model') or 'N/A'}")
            parts.append(f"  Barcode: {inst.get('barcode') or 'N/A'}  Serial: {inst.get('serial_no') or 'N/A'}")
            parts.append(f"  Condition: {inst.get('condition') or 'N/A'}")
            if active:
                parts.append(
                    f"  Checked out to: {active['student_name']} since {active['date_assigned']}"
                )
            else:
                parts.append("  Status: Available")
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
                summary = self._summary_fn()
                system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
                    date=date.today().strftime("%B %d, %Y"),
                    inventory_summary=summary,
                ) + "\n\n" + UI_GUIDE
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
