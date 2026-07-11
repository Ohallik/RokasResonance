"""
ui/program_importer.py - Import a concert-program PDF/image to bulk-add
performance history.

Concert programs are visually laid out (columns, decorative fonts), so we send
rendered page images to the vision LLM, which extracts every performed piece and
the ensemble that played it.  The teacher then reviews/adjusts the matches before
the performances are written — far faster than entering them one piece at a time.
"""

import base64
import io
import os
import re
import threading
import tkinter as tk
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from ttkbootstrap.dialogs import Messagebox
from datetime import datetime
from difflib import SequenceMatcher


def _norm(t: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (t or "").lower())


def _date_from_filename(path: str) -> str:
    """Teachers often name programs like '2025-06-04 June concert.pdf'."""
    name = os.path.basename(path or "")
    m = re.search(r"(\d{4})[-_./](\d{1,2})[-_./](\d{1,2})", name)
    if m:
        y, mo, dy = m.groups()
        return f"{y}-{int(mo):02d}-{int(dy):02d}"
    m = re.search(r"(\d{1,2})[-_./](\d{1,2})[-_./](\d{4})", name)
    if m:
        mo, dy, y = m.groups()
        return f"{y}-{int(mo):02d}-{int(dy):02d}"
    return ""


def _last_word(s: str) -> str:
    parts = re.sub(r"[^a-z0-9 ]", "", (s or "").lower()).split()
    return parts[-1] if parts else ""


MATCH_THRESHOLD = 0.82

# Signals that an ensemble name belongs to a school ("Bellevue High School
# Wind Ensemble", "BHS Jazz Band") — used to spot OTHER schools' groups on
# joint-concert programs.
_SCHOOL_WORD_RE = re.compile(
    r"\b(high school|middle school|junior high|intermediate school|elementary)\b",
    re.IGNORECASE)
_SCHOOL_ABBREV_RE = re.compile(r"\b[A-Z]{0,4}(?:HS|MS|JH)\b")

PROGRAM_SYSTEM = (
    "You extract structured performance data from school concert programs. "
    "Return only valid JSON."
)


def _build_prompt(text: str) -> str:
    text_block = ""
    if text and text.strip():
        text_block = ("\n\nHere is the extracted text of the program (may be "
                      "incomplete or out of order):\n" + text.strip()[:6000])
    return (
        "This is a school music concert program. Find the REPERTOIRE / 'Program' "
        "section (often a boxed list titled 'Tonight's Program' or similar) and "
        "identify EVERY musical piece performed, with the ensemble that performed each.\n"
        "Pieces are grouped under ensemble headings (e.g. 'Jazz 2', 'Entry Band', "
        "'Intermediate Band', 'Advanced Band', 'Percussion Ensemble', 'Concert Choir', "
        "'Symphony Orchestra'). Titles are usually followed by dots/a line and then the "
        "composer or 'arr. Name'. Associate each piece with the ensemble heading above it.\n"
        "IGNORE everything that is NOT repertoire: personnel/roster name lists, "
        "acknowledgements, 'Why Band?' essays, program notes, upcoming-concert lists, "
        "and artwork credits. Do NOT treat student or staff names as pieces.\n"
        "Return ONLY a JSON array — one object per piece — with these exact keys:\n"
        '[{"title":"", "composer":"", "arranger":"", "ensemble":"", '
        '"event_name":"", "performance_date":"", "notes":""}]\n'
        "- title: the piece title as printed.\n"
        "- composer: the name after the piece; if it starts with 'arr.' put it in arranger instead.\n"
        "- ensemble: the performing ensemble's heading. If the program includes "
        "ensembles from more than one school (a joint concert), keep the school "
        "name in the ensemble exactly as printed (e.g. 'Bellevue High School "
        "Wind Ensemble').\n"
        "- event_name: the concert's name/title (same for every piece).\n"
        "- performance_date: the concert date as YYYY-MM-DD if shown, else empty.\n"
        "- notes: soloists or notable details, else empty.\n"
        "Use empty strings for anything absent. Do not invent pieces."
        + text_block
    )


def extract_program_media(path: str, max_pages: int = 10):
    """Return (images, text) for a program file. images = list of vision dicts."""
    ext = os.path.splitext(path)[1].lower()
    images, text = [], ""
    if ext == ".pdf":
        import fitz  # pymupdf
        doc = fitz.open(path)
        texts = []
        for i, page in enumerate(doc):
            if i >= max_pages:
                break
            texts.append(page.get_text())
            mat = fitz.Matrix(150 / 72, 150 / 72)
            pix = page.get_pixmap(matrix=mat, colorspace=fitz.csRGB)
            images.append({"mime_type": "image/png",
                           "data": base64.b64encode(pix.tobytes("png")).decode()})
        doc.close()
        text = "\n".join(texts)
    elif ext in (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".gif"):
        from PIL import Image
        img = Image.open(path)
        img.thumbnail((1800, 1800))
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="PNG")
        images.append({"mime_type": "image/png",
                       "data": base64.b64encode(buf.getvalue()).decode()})
    return images, text


def parse_program(base_dir: str, path: str, on_retry=None, max_pages=1):
    """Extract + LLM-parse a program into a list of piece dicts.

    max_pages limits how many pages are scanned — the repertoire is almost
    always on page 1, and scanning fewer pages is much faster."""
    images, text = extract_program_media(path, max_pages=max_pages)
    if not images and not (text or "").strip():
        raise ValueError(
            "Couldn't read that file. Microsoft Publisher (.pub) files can't be read "
            "directly — in Publisher choose File ▸ Export ▸ Create PDF/XPS, then import "
            "the PDF here."
        )
    from llm_client import query_with_images, query
    from ui.music_importer import _extract_json

    prompt = _build_prompt(text)
    items = []
    if images:
        try:
            raw = query_with_images(base_dir, prompt, images, system_prompt=PROGRAM_SYSTEM,
                                    on_retry=on_retry, max_tokens=4000)
            items = _normalize_items(_extract_json(raw))
        except Exception:
            items = []
    # Fall back to the PDF's text layer if the vision pass found nothing
    # (covers text-only models and pages the vision model reads poorly).
    # Use a large token budget — a busy program can list 25+ pieces.
    if not items and (text or "").strip():
        raw = query(base_dir, prompt, system_prompt=PROGRAM_SYSTEM, on_retry=on_retry,
                    max_tokens=4000)
        items = _normalize_items(_extract_json(raw))
    return items


def _coerce_piece(d, default_ensemble=""):
    """Turn one loosely-shaped dict into a normalized piece, tolerating the
    various key names the model sometimes uses."""
    if not isinstance(d, dict):
        return None
    def g(*keys):
        for k in keys:
            if d.get(k):
                return str(d[k]).strip()
        return ""
    title = g("title", "piece", "name", "selection", "work")
    if not title:
        return None
    return {
        "title": title,
        "composer": g("composer", "composers"),
        "arranger": g("arranger", "arr", "arrangedby", "arranged_by"),
        "ensemble": g("ensemble", "group", "performers", "performed_by") or default_ensemble,
        "event_name": g("event_name", "event", "concert", "concert_name"),
        "performance_date": g("performance_date", "date", "concert_date"),
        "notes": g("notes", "note", "soloist", "soloists"),
    }


def _normalize_items(data):
    if data is None:
        return []
    out = []
    if isinstance(data, dict):
        # {"pieces":[...]} / {"items":[...]} / {"performances":[...]}
        for k in ("pieces", "items", "performances", "results", "program"):
            if isinstance(data.get(k), list):
                data = data[k]
                break
        else:
            # Maybe {"Advanced Band":[...], "Jazz 1":[...]} — ensemble-keyed.
            list_vals = {k: v for k, v in data.items() if isinstance(v, list)}
            if list_vals:
                for ens, lst in list_vals.items():
                    for d in lst:
                        if isinstance(d, str):
                            d = {"title": d}
                        p = _coerce_piece(d, default_ensemble=str(ens))
                        if p:
                            out.append(p)
                return out
            data = [data]
    for d in data:
        if isinstance(d, str):
            d = {"title": d}
        p = _coerce_piece(d)
        if p:
            out.append(p)
    return out


def convert_publisher_to_pdf(path: str) -> str:
    """Best-effort: drive Microsoft Publisher (via COM) to export a .pub to PDF,
    so teachers can import Publisher programs directly.  Requires Windows with
    Publisher installed + pywin32.  Raises RuntimeError with guidance otherwise."""
    import tempfile
    try:
        import win32com.client  # from pywin32
    except Exception:
        raise RuntimeError(
            "the pywin32 package isn't installed, so Publisher files can't be read "
            "directly. Run 'pip install pywin32', or export the file to PDF in Publisher "
            "(File ▸ Export ▸ Create PDF) and import that.")
    out = os.path.join(tempfile.gettempdir(),
                       os.path.splitext(os.path.basename(path))[0] + "_rr.pdf")
    app = doc = None
    try:
        app = win32com.client.DispatchEx("Publisher.Application")
        doc = app.Open(os.path.abspath(path))
        # 2 = pbFixedFormatTypePDF
        doc.ExportAsFixedFormat(2, out)
    except Exception as e:
        raise RuntimeError(
            f"couldn't convert the Publisher file automatically ({e}). "
            "Export it to PDF from Publisher and import that instead.")
    finally:
        try:
            if doc:
                doc.Close()
        except Exception:
            pass
        try:
            if app:
                app.Quit()
        except Exception:
            pass
    if not os.path.exists(out):
        raise RuntimeError("Publisher export produced no PDF — export to PDF manually instead.")
    return out


class ProgramImportDialog(ttk.Toplevel):
    def __init__(self, parent, db, base_dir, paths, mode="band", on_done=None, max_pages=1):
        super().__init__(parent)
        self.db = db
        self.base_dir = base_dir
        self.paths = [paths] if isinstance(paths, str) else list(paths)
        self.mode = mode
        self.on_done = on_done
        self.max_pages = max_pages
        self._items = []          # parsed rows (dicts, augmented with match info)
        self._failed = []         # (filename, reason)
        self._library = db.get_music_for_matching()
        from ui.settings_dialog import load_settings
        self._school = ((load_settings(base_dir).get("teacher") or {})
                        .get("school_name") or "").strip()
        self._known = None        # lazy: lowercased own-ensemble vocabulary

        self.title("Import Concert Program(s)")
        self.resizable(True, True)
        self.grab_set()
        self.lift()

        self._build_progress()
        from ui.theme import fit_window
        fit_window(self, 940, 640)

        # Kick off parsing in a worker thread
        threading.Thread(target=self._worker, daemon=True).start()

    # ── Phase 1: progress ──────────────────────────────────────────────────

    def _build_progress(self):
        self._progress_frame = ttk.Frame(self)
        self._progress_frame.pack(fill=BOTH, expand=True)
        n = len(self.paths)
        title = "📄  Reading concert program…" if n == 1 else f"📄  Reading {n} programs…"
        ttk.Label(self._progress_frame, text=title,
                  font=("Segoe UI", 13, "bold"), bootstyle=PRIMARY).pack(pady=(40, 8))
        self._pbar = ttk.Progressbar(self._progress_frame, mode="indeterminate",
                                     bootstyle=PRIMARY, length=360)
        self._pbar.pack(pady=18)
        self._pbar.start(12)
        scope = ("Scanning the first page of each (fastest)…" if self.max_pages == 1
                 else f"Scanning up to {self.max_pages} pages each — slower…")
        self._status = ttk.Label(self._progress_frame, text=scope,
                                 font=("Segoe UI", 9), foreground="#666")
        self._status.pack()

    def _set_status(self, text):
        try:
            self.after(0, lambda: self._status.config(text=text))
        except Exception:
            pass

    def _worker(self):
        # COM (for Publisher conversion) must be initialised on this thread.
        try:
            import pythoncom
            pythoncom.CoInitialize()
        except Exception:
            pythoncom = None
        all_items = []
        try:
            for i, path in enumerate(self.paths, 1):
                base = os.path.basename(path)
                self._set_status(f"Reading {i} of {len(self.paths)}: {base}")
                try:
                    use_path = path
                    if path.lower().endswith(".pub"):
                        use_path = convert_publisher_to_pdf(path)
                    items = parse_program(self.base_dir, use_path,
                                          on_retry=lambda *a, **k: None,
                                          max_pages=self.max_pages)
                    # If a first-page-only scan finds nothing (e.g. page 1 is a
                    # cover), automatically widen the scan before giving up.
                    if not items and self.max_pages == 1:
                        self._set_status(f"First page had no pieces — scanning more of {base}…")
                        items = parse_program(self.base_dir, use_path,
                                              on_retry=lambda *a, **k: None,
                                              max_pages=8)
                    if not items:
                        self._failed.append((base, "no pieces found (the AI couldn't read "
                                             "a repertoire list — check it's the concert program)"))
                    for it in items:
                        it["source"] = base
                        if not it["performance_date"]:
                            it["performance_date"] = _date_from_filename(path)
                    all_items.extend(items)
                except Exception as e:
                    self._failed.append((base, str(e)))
        finally:
            if pythoncom:
                try:
                    pythoncom.CoUninitialize()
                except Exception:
                    pass
        self.after(0, lambda: self._on_parsed(all_items))

    def _on_parsed(self, items):
        self._pbar.stop()
        if not items:
            msg = "No performed pieces were found."
            if self._failed:
                msg += "\n\nProblems:\n" + "\n".join(f"• {n}: {r}" for n, r in self._failed)
            Messagebox.show_info(msg, title="Nothing Found", parent=self)
            self.destroy()
            return
        # Fold our own school's name out of ensemble headings and flag other
        # schools' groups (joint concerts), then match each item to the library
        for it in items:
            self._classify_school(it)
            m = self._match(it["title"], it["composer"])
            it["match_id"] = m["id"] if m else None
            it["match_title"] = m["title"] if m else ""
            it["include"] = not it["other_school"]
        self._items = items
        for w in self._progress_frame.winfo_children():
            w.destroy()
        self._progress_frame.destroy()
        self._build_review()

    def _match(self, title, composer):
        nt = _norm(title)
        if not nt:
            return None
        best, best_score = None, 0.0
        clast = _last_word(composer)
        for m in self._library:
            mt = _norm(m["title"])
            if not mt:
                continue
            score = 1.0 if mt == nt else SequenceMatcher(None, nt, mt).ratio()
            if clast and _last_word(m.get("composer")) == clast:
                score += 0.06
            if score > best_score:
                best_score, best = score, m
        return best if best_score >= MATCH_THRESHOLD else None

    # ── School filtering ────────────────────────────────────────────────────

    def _known_ensembles(self):
        """Lowercased names of the teacher's own ensembles: the program type's
        standard classes plus everything already in performance history."""
        if self._known is None:
            from ui.ensembles import ensembles_for
            from database import strip_school_prefix
            names = {e.lower() for e in ensembles_for(self.mode)}
            try:
                for e in self.db.get_distinct_performance_ensembles():
                    names.add(strip_school_prefix(e, self._school).lower())
            except Exception:
                pass
            self._known = names
        return self._known

    def _classify_school(self, it):
        """Normalize one parsed item's ensemble in place: strip our own
        school's name, and set it['other_school'] for other schools' groups."""
        from database import strip_school_prefix
        raw = (it.get("ensemble") or "").strip()
        stripped = strip_school_prefix(raw, self._school)
        it["ensemble"] = stripped
        # Our school's name was on the heading — definitely ours.
        it["other_school"] = False if stripped != raw else self._is_other_school(stripped)

    def _is_other_school(self, ensemble: str) -> bool:
        from database import school_name_variants
        e = (ensemble or "").strip()
        if not e:
            return False
        low = e.lower()
        known = self._known_ensembles()
        if low in known:
            return False
        own = [v.lower() for v in school_name_variants(self._school)]
        # Mentions a school ("… High School …", "BHS …") that isn't ours
        if ((_SCHOOL_WORD_RE.search(e) or _SCHOOL_ABBREV_RE.search(e))
                and not any(v in low for v in own)):
            return True
        # "Bellevue Jazz 1" — one of OUR ensemble names with a foreign prefix
        for k in known:
            if low.endswith(" " + k):
                prefix = low[: -len(k)].strip(" -–—:")
                if prefix and prefix not in own:
                    return True
        return False

    def _own_only(self) -> bool:
        var = getattr(self, "_own_only_var", None)
        return bool(var.get()) if var else True

    def _is_hidden(self, it) -> bool:
        return self._own_only() and bool(it.get("other_school"))

    # ── Phase 2: review ─────────────────────────────────────────────────────

    def _build_review(self):
        hdr = ttk.Frame(self, bootstyle=PRIMARY)
        hdr.pack(fill=X)
        n_files = len({it.get("source", "") for it in self._items})
        ttk.Label(hdr, text="🎵  Review Program Performances", font=("Segoe UI", 13, "bold"),
                  bootstyle=(INVERSE, PRIMARY)).pack(pady=10, padx=16, anchor=W)

        note = f"Each row keeps its own concert date/event (from its program)."
        if n_files > 1:
            note = f"{len(self._items)} pieces from {n_files} programs.  " + note
        ttk.Label(self, text=note + "  Tick the ones to record; double-click a row to fix "
                                    "its details or library match. ✓ = matched to your library.",
                  font=("Segoe UI", 8), foreground="#666", wraplength=880,
                  justify=LEFT).pack(anchor=W, padx=16, pady=(8, 4))

        # Joint concerts list other schools' groups too — hide those by default.
        filt = ttk.Frame(self)
        filt.pack(fill=X, padx=16, pady=(0, 4))
        self._own_only_var = tk.BooleanVar(value=True)
        school_label = self._school or "my school's"
        ttk.Checkbutton(filt, variable=self._own_only_var, bootstyle=PRIMARY,
                        text=f"Look ONLY for {school_label} ensembles and ignore "
                             "other schools' ensembles",
                        command=self._on_own_only_toggle).pack(side=LEFT)
        self._hidden_lbl = ttk.Label(filt, text="", font=("Segoe UI", 8),
                                     foreground="#8B4000")
        self._hidden_lbl.pack(side=LEFT, padx=(10, 0))

        # Bulk-correct date/event for the ticked rows (handy if AI missed a date)
        top = ttk.Frame(self)
        top.pack(fill=X, padx=16, pady=(0, 4))
        ttk.Label(top, text="Set for ticked →", font=("Segoe UI", 8, "bold")).pack(side=LEFT)
        ttk.Label(top, text="Date:", font=("Segoe UI", 8)).pack(side=LEFT, padx=(6, 2))
        self._bulk_date = tk.StringVar()
        ttk.Entry(top, textvariable=self._bulk_date, width=12).pack(side=LEFT)
        ttk.Label(top, text="Event:", font=("Segoe UI", 8)).pack(side=LEFT, padx=(8, 2))
        self._bulk_event = tk.StringVar()
        ttk.Entry(top, textvariable=self._bulk_event, width=22).pack(side=LEFT)
        ttk.Button(top, text="Apply to ticked", bootstyle=(SECONDARY, OUTLINE),
                   command=self._apply_bulk_dateevent).pack(side=LEFT, padx=(6, 0))

        # Selection controls
        selbar = ttk.Frame(self)
        selbar.pack(fill=X, padx=16)
        ttk.Button(selbar, text="Select All", bootstyle=(SECONDARY, OUTLINE),
                   command=lambda: self._set_all(True)).pack(side=LEFT, padx=2)
        ttk.Button(selbar, text="Clear All", bootstyle=(SECONDARY, OUTLINE),
                   command=lambda: self._set_all(False)).pack(side=LEFT, padx=2)
        ttk.Button(selbar, text="✏ Edit Row", bootstyle=(PRIMARY, OUTLINE),
                   command=self._edit_row).pack(side=LEFT, padx=2)
        # Default OFF — unknown pieces are tagged, not silently added to the library.
        self._create_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(selbar, text="Also add unknown pieces to my library as new entries",
                        variable=self._create_var, bootstyle=PRIMARY,
                        command=self._update_summary).pack(side=LEFT, padx=(14, 0))

        # Review tree
        frame = ttk.Frame(self)
        frame.pack(fill=BOTH, expand=True, padx=16, pady=8)
        cols = ("inc", "date", "ensemble", "title", "composer", "event", "match")
        sb = ttk.Scrollbar(frame, orient=VERTICAL)
        self.tree = ttk.Treeview(frame, columns=cols, show="headings",
                                 yscrollcommand=sb.set, selectmode="browse", bootstyle=PRIMARY)
        sb.config(command=self.tree.yview)
        sb.pack(side=RIGHT, fill=Y)
        self.tree.pack(fill=BOTH, expand=True)
        headers = {"inc": "✓", "date": "Date", "ensemble": "Ensemble", "title": "Title",
                   "composer": "Composer", "event": "Event", "match": "Library Match"}
        widths = {"inc": 34, "date": 92, "ensemble": 130, "title": 210,
                  "composer": 130, "event": 140, "match": 190}
        for c in cols:
            self.tree.heading(c, text=headers[c], anchor=W)
            self.tree.column(c, width=widths[c], anchor=(CENTER if c == "inc" else W),
                             stretch=c in ("title", "match"))
        self.tree.bind("<Button-1>", self._on_click, add="+")
        self.tree.bind("<Double-1>", lambda e: self._edit_row())
        self._refill()

        # Buttons
        btn = ttk.Frame(self)
        btn.pack(fill=X, padx=16, pady=12)
        ttk.Button(btn, text="Cancel", bootstyle=(SECONDARY, OUTLINE),
                   command=self.destroy).pack(side=RIGHT, padx=4)
        ttk.Button(btn, text="Import Performances", bootstyle=SUCCESS,
                   command=self._do_import).pack(side=RIGHT, padx=4)
        self._summary = ttk.Label(btn, text="", font=("Segoe UI", 9), foreground="#666")
        self._summary.pack(side=LEFT)
        self._update_summary()

    def _apply_bulk_dateevent(self):
        dt = self._bulk_date.get().strip()
        ev = self._bulk_event.get().strip()
        if not dt and not ev:
            return
        for it in self._items:
            if it["include"]:
                if dt:
                    it["performance_date"] = dt
                if ev:
                    it["event_name"] = ev
        self._refill()
        self._update_summary()

    def _refill(self):
        self.tree.delete(*self.tree.get_children())
        hidden = 0
        for i, it in enumerate(self._items):
            if self._is_hidden(it):
                hidden += 1
                continue
            match = it["match_title"] if it["match_id"] else "＋ new piece"
            if it.get("other_school"):
                match = "⚠ other school?"
            self.tree.insert("", "end", iid=str(i), values=(
                "☑" if it["include"] else "☐",
                it["performance_date"] or "—",
                it["ensemble"] or "—",
                it["title"],
                it["composer"] or "—",
                it["event_name"] or "—",
                match,
            ))
        if getattr(self, "_hidden_lbl", None):
            self._hidden_lbl.config(
                text=(f"{hidden} piece(s) by other schools' ensembles hidden "
                      "— untick to review them" if hidden else ""))

    def _on_own_only_toggle(self):
        # Re-hiding also un-ticks other-school rows so they can't sneak in.
        if self._own_only():
            for it in self._items:
                if it.get("other_school"):
                    it["include"] = False
        self._refill()
        self._update_summary()

    def _on_click(self, event):
        if self.tree.identify("region", event.x, event.y) != "cell":
            return
        if self.tree.identify_column(event.x) != "#1":
            return
        iid = self.tree.identify_row(event.y)
        if not iid:
            return
        i = int(iid)
        self._items[i]["include"] = not self._items[i]["include"]
        self.tree.set(iid, "inc", "☑" if self._items[i]["include"] else "☐")
        self._update_summary()

    def _set_all(self, val):
        for it in self._items:
            if not self._is_hidden(it):
                it["include"] = val
        self._refill()
        self._update_summary()

    def _update_summary(self):
        inc = [it for it in self._items
               if it["include"] and not self._is_hidden(it)]
        matched = sum(1 for it in inc if it["match_id"])
        unknown = len(inc) - matched
        create = getattr(self, "_create_var", None)
        fate = "will be added" if (create and create.get()) else "will be skipped"
        self._summary.config(
            text=f"{len(inc)} selected  •  {matched} matched, "
                 f"{unknown} unknown ({fate})")

    def _ensemble_suggestions(self):
        from ui.ensembles import ensembles_for
        seen, out = set(), []
        # The program's own classes first, then anything parsed, then history.
        pools = [ensembles_for(self.mode),
                 [it.get("ensemble", "") for it in self._items
                  if not it.get("other_school")]]
        try:
            pools.append(self.db.get_distinct_performance_ensembles())
        except Exception:
            pass
        for pool in pools:
            for e in pool:
                e = (e or "").strip()
                if e and e not in seen:
                    seen.add(e); out.append(e)
        return out

    def _edit_row(self):
        sel = self.tree.selection()
        if not sel:
            Messagebox.show_warning("Select a row to edit.", title="No Selection", parent=self)
            return
        i = int(sel[0])
        it = self._items[i]
        # Local, correctable copy of the match decision
        match_state = {"id": it["match_id"], "title": it["match_title"]}

        win = ttk.Toplevel(self)
        win.title("Verify / Correct Piece")
        win.grab_set()
        ttk.Label(win, text="Verify / Correct Piece", font=("Segoe UI", 12, "bold"),
                  bootstyle=PRIMARY).pack(anchor=W, padx=16, pady=(14, 6))

        vars_ = {}
        for label, key in [("Title", "title"), ("Composer", "composer"),
                           ("Arranger", "arranger"),
                           ("Concert / Event", "event_name"),
                           ("Date (YYYY-MM-DD)", "performance_date")]:
            ttk.Label(win, text=label, font=("Segoe UI", 9, "bold")).pack(anchor=W, padx=16, pady=(6, 0))
            v = tk.StringVar(value=it.get(key, ""))
            vars_[key] = v
            ttk.Entry(win, textvariable=v, width=46).pack(anchor=W, padx=16)

        ttk.Label(win, text="Ensemble", font=("Segoe UI", 9, "bold")).pack(anchor=W, padx=16, pady=(6, 0))
        ens_var = tk.StringVar(value=it.get("ensemble", ""))
        vars_["ensemble"] = ens_var
        ttk.Combobox(win, textvariable=ens_var, values=self._ensemble_suggestions(),
                     width=44).pack(anchor=W, padx=16)

        # ── Library match (correctable) ─────────────────────────────────────
        mf = tk.LabelFrame(win, text=" Library match ", font=("Segoe UI", 9, "bold"),
                           padx=10, pady=6)
        mf.pack(fill=X, padx=16, pady=(10, 4))
        match_lbl = ttk.Label(mf, text="", font=("Segoe UI", 9), wraplength=420, justify=LEFT)
        match_lbl.pack(anchor=W)

        def _refresh_match_lbl():
            if match_state["id"]:
                match_lbl.config(text=f"→ linked to library piece: {match_state['title']}",
                                 foreground="#1a7a1a")
            else:
                match_lbl.config(text="→ will be added as a NEW library piece",
                                 foreground="#8B4000")
        _refresh_match_lbl()

        row = ttk.Frame(mf); row.pack(fill=X, pady=(6, 0))

        def _auto():
            m = self._match(vars_["title"].get().strip(), vars_["composer"].get().strip())
            match_state["id"] = m["id"] if m else None
            match_state["title"] = m["title"] if m else ""
            _refresh_match_lbl()

        def _choose():
            chosen = self._pick_library_piece()
            if chosen == "cancel":
                return
            if chosen is None:
                match_state["id"] = None
                match_state["title"] = ""
            else:
                match_state["id"] = chosen["id"]
                match_state["title"] = chosen["title"]
            _refresh_match_lbl()

        ttk.Button(row, text="🔎 Choose from library…", bootstyle=(PRIMARY, OUTLINE),
                   command=_choose).pack(side=LEFT, padx=(0, 4))
        ttk.Button(row, text="＋ Make new piece", bootstyle=(SECONDARY, OUTLINE),
                   command=lambda: (match_state.update(id=None, title=""), _refresh_match_lbl())).pack(side=LEFT, padx=4)
        ttk.Button(row, text="Auto-match", bootstyle=(SECONDARY, OUTLINE),
                   command=_auto).pack(side=LEFT, padx=4)

        def _save():
            for key, v in vars_.items():
                it[key] = v.get().strip()
            it["match_id"] = match_state["id"]
            it["match_title"] = match_state["title"]
            # Re-normalize the (possibly corrected) ensemble and refresh the
            # other-school flag — renaming to one of our groups un-hides it.
            self._classify_school(it)
            win.destroy()
            self._refill()
            self.tree.selection_set(str(i))
            self._update_summary()

        btns = ttk.Frame(win); btns.pack(fill=X, padx=16, pady=12)
        ttk.Button(btns, text="Cancel", bootstyle=(SECONDARY, OUTLINE),
                   command=win.destroy).pack(side=RIGHT, padx=4)
        ttk.Button(btns, text="Save", bootstyle=SUCCESS, command=_save).pack(side=RIGHT, padx=4)
        from ui.theme import fit_window
        fit_window(win, 470, 560)

    def _pick_library_piece(self):
        """Searchable picker over the library. Returns a piece dict, None (=make
        new), or the string 'cancel'."""
        win = ttk.Toplevel(self)
        win.title("Choose Library Piece")
        win.grab_set()
        ttk.Label(win, text="Type to filter, then pick the matching piece:",
                  font=("Segoe UI", 9)).pack(anchor=W, padx=14, pady=(12, 4))
        search_var = tk.StringVar()
        ent = ttk.Entry(win, textvariable=search_var, width=48)
        ent.pack(padx=14)
        ent.focus_set()
        lb = tk.Listbox(win, font=("Segoe UI", 9), height=12, width=56)
        lb.pack(fill=BOTH, expand=True, padx=14, pady=6)

        lib = sorted(self._library, key=lambda m: (m["title"] or "").lower())
        shown = []

        def _fill(*_):
            q = _norm(search_var.get())
            lb.delete(0, END)
            shown.clear()
            for m in lib:
                label = f"{m['title']}  —  {m.get('composer') or ''}".strip(" —")
                if not q or q in _norm(label):
                    shown.append(m)
                    lb.insert(END, label)
                if len(shown) >= 300:
                    break
            if shown:
                lb.selection_set(0)
        _fill()
        search_var.trace_add("write", _fill)

        result = {"v": "cancel"}

        def _ok():
            sel = lb.curselection()
            if sel:
                result["v"] = shown[sel[0]]
            win.destroy()

        lb.bind("<Double-1>", lambda e: _ok())
        btns = ttk.Frame(win); btns.pack(fill=X, padx=14, pady=12)
        ttk.Button(btns, text="Cancel", bootstyle=(SECONDARY, OUTLINE),
                   command=win.destroy).pack(side=RIGHT, padx=4)
        ttk.Button(btns, text="＋ Make new instead", bootstyle=(SECONDARY, OUTLINE),
                   command=lambda: (result.update(v=None), win.destroy())).pack(side=RIGHT, padx=4)
        ttk.Button(btns, text="Use Selected", bootstyle=SUCCESS, command=_ok).pack(side=RIGHT, padx=4)
        from ui.theme import fit_window
        fit_window(win, 480, 420)
        self.wait_window(win)
        return result["v"]

    def _do_import(self):
        create_new = self._create_var.get()
        added = created = skipped_dup = skipped_unmatched = 0
        seen_batch = set()   # (mid, date, ensemble) recorded in THIS run

        for it in self._items:
            if not it["include"] or self._is_hidden(it):
                continue
            date = (it.get("performance_date") or "").strip()
            event = (it.get("event_name") or "").strip()
            mid = it["match_id"]
            if not mid:
                if not create_new:
                    skipped_unmatched += 1
                    continue
                mid = self.db.add_sheet_music({
                    "title": it["title"],
                    "composer": it["composer"],
                    "arranger": it["arranger"],
                    "notes": "Added from concert-program import.",
                })
                created += 1
                self._library.append({"id": mid, "title": it["title"],
                                      "composer": it["composer"]})
            ensemble = it["ensemble"]
            key = (mid, date, ensemble)
            # Duplicate guard: skip if already in the DB or already added this run
            if date and (key in seen_batch or self.db.performance_exists(mid, date, ensemble)):
                skipped_dup += 1
                continue
            self.db.add_performance({
                "music_id": mid,
                "performance_date": date,
                "ensemble": ensemble,
                "event_name": event,
                "notes": it["notes"],
            })
            seen_batch.add(key)
            added += 1

        parts = [f"Added {added} performance(s)"]
        if created:
            parts.append(f"created {created} new library piece(s)")
        if skipped_dup:
            parts.append(f"skipped {skipped_dup} duplicate(s) already recorded")
        if skipped_unmatched:
            parts.append(f"left {skipped_unmatched} unmatched piece(s) out "
                         "(tick 'add unknown pieces' to include them)")
        msg = ".\n".join(parts) + "."
        if self._failed:
            msg += "\n\nCouldn't read:\n" + "\n".join(f"• {n}: {r}" for n, r in self._failed)
        Messagebox.show_info(msg, title="Programs Imported", parent=self)
        if self.on_done:
            self.on_done()
        self.destroy()
