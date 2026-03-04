"""
ui/music_importer.py - AI-powered sheet music import from images/PDFs

Flow:
  1. User selects files (PDF / PNG / JPG / etc.)
  2. Files are converted to images and sent to LLM vision for title extraction
  3. Each found title is enriched via LLM text query (composer, difficulty, etc.)
  4. Returns a list of prefill dicts for MusicDialog
"""

from __future__ import annotations

import base64
import io
import json
import re
import threading
import tkinter as tk
import ttkbootstrap as ttk
from pathlib import Path
from ttkbootstrap.constants import *


# ── Helpers ──────────────────────────────────────────────────────────────────

def _file_to_images(path: str) -> list[dict]:
    """
    Convert a file to a list of image dicts {mime_type, data}.
    PDFs: renders first 3 pages at 150 DPI.
    Images: returned directly (resized if needed).
    """
    ext = Path(path).suffix.lower()
    images = []

    if ext == ".pdf":
        try:
            import fitz  # pymupdf
            doc = fitz.open(path)
            for i, page in enumerate(doc):
                if i >= 3:
                    break
                mat = fitz.Matrix(150 / 72, 150 / 72)
                pix = page.get_pixmap(matrix=mat, colorspace=fitz.csRGB)
                img_bytes = pix.tobytes("png")
                images.append({
                    "mime_type": "image/png",
                    "data": base64.b64encode(img_bytes).decode(),
                })
            doc.close()
        except ImportError:
            pass  # fitz not available, skip PDF
    else:
        try:
            from PIL import Image
            img = Image.open(path).convert("RGB")
            # Resize so longest side ≤ 1500px
            w, h = img.size
            scale = min(1.0, 1500 / max(w, h))
            if scale < 1.0:
                img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            images.append({
                "mime_type": "image/png",
                "data": base64.b64encode(buf.getvalue()).decode(),
            })
        except Exception:
            pass

    return images


def _extract_json(text: str) -> list | dict | None:
    """Pull the first JSON array or object out of an LLM response."""
    # Try ```json...``` block first
    m = re.search(r"```(?:json)?\s*([\s\S]+?)```", text)
    if m:
        text = m.group(1).strip()
    # Try to find a JSON array or object
    for pattern in (r"(\[[\s\S]+\])", r"(\{[\s\S]+\})"):
        m = re.search(pattern, text)
        if m:
            try:
                return json.loads(m.group(1))
            except json.JSONDecodeError:
                pass
    return None


def _filename_hints(path: str) -> tuple[str, str]:
    """Parse 'Title - Composer' from a filename stem, stripping leading numbers."""
    stem = Path(path).stem
    clean = re.sub(r"^\d+\s*[-.]?\s*", "", stem)  # strip "12 " or "12. "
    parts = [p.strip() for p in clean.split(" - ", 1)]
    title = parts[0] if parts else clean
    composer = parts[1] if len(parts) > 1 else ""
    return title, composer


def _identify_piece(path: str, images: list[dict], base_dir: str) -> dict:
    """
    Phase 1: identify the ONE piece this file represents.
    Uses filename as primary hint, images as supplemental.
    Always returns exactly one piece dict.
    """
    from llm_client import query_with_images

    title_hint, composer_hint = _filename_hints(path)
    fname = Path(path).stem

    _EMPTY = {
        "title": title_hint, "composer": composer_hint,
        "arranger": "", "publisher": "",
        "instrument_parts": "", "time_signature": "", "visible_notes": "",
    }

    if not images:
        return _EMPTY

    composer_str = f' by "{composer_hint}"' if composer_hint else ""
    prompt = (
        f'This file ("{fname}") represents ONE piece of sheet music, '
        f'likely titled "{title_hint}"{composer_str}.\n\n'
        "Examine the images to confirm or correct the title and composer, "
        "then capture any additional info you can clearly SEE:\n"
        "- title: confirmed/corrected title of this one piece\n"
        "- composer: full composer name (use filename hint if not visible)\n"
        "- arranger: arranger name if visible, otherwise empty\n"
        "- publisher: publishing house if visible "
        "  (e.g. Hal Leonard, Alfred Music, Carl Fischer, FJH, Boosey & Hawkes)\n"
        "- instrument_parts: all instrument names visible on the pages\n"
        "- time_signature: meter if clearly shown at the start of a staff\n"
        "- visible_notes: grade/difficulty marking, catalog number, year, "
        "  or other useful identifying text\n\n"
        "This file contains ONE piece. Do not list other titles that appear "
        "in margins, catalogs, series listings, or tables of contents.\n\n"
        "Do NOT attempt to read key signatures — transposing parts make this unreliable.\n\n"
        "Respond ONLY with a single JSON object (not an array):\n"
        '{"title": "...", "composer": "...", "arranger": "...", "publisher": "...", '
        '"instrument_parts": "...", "time_signature": "...", "visible_notes": "..."}\n'
        "Use empty string for fields you cannot clearly see."
    )

    raw = query_with_images(base_dir, prompt, images)
    result = _extract_json(raw)
    if isinstance(result, dict):
        return result
    if isinstance(result, list) and result:
        return result[0]  # fallback if LLM returned array anyway
    return _EMPTY


def _enrich_piece(piece: dict, base_dir: str) -> dict:
    """
    Phase 2: text query to fill in composer, difficulty, key sig, time sig, etc.
    """
    from llm_client import query

    title = piece.get("title", "").strip()
    composer = piece.get("composer", "").strip()
    arranger = piece.get("arranger", "").strip()
    publisher = piece.get("publisher", "").strip()
    vis_time = piece.get("time_signature", "").strip()
    instrument_parts = piece.get("instrument_parts", "").strip()
    visible_notes = piece.get("visible_notes", "").strip()
    vis_publisher = piece.get("publisher", "").strip()

    context_lines = [f'Title: "{title}"']
    if composer:
        context_lines.append(f"Composer: {composer}")
    if arranger:
        context_lines.append(f"Arranger: {arranger}")
    if vis_publisher:
        context_lines.append(f"Publisher visible in image: {vis_publisher}")
    if instrument_parts:
        context_lines.append(f"Instrument parts visible: {instrument_parts}")
    if vis_time:
        context_lines.append(f"Time signature visible: {vis_time}")
    if visible_notes:
        context_lines.append(f"Other visible info: {visible_notes}")

    prompt = (
        "You are a band director and music librarian with deep knowledge of "
        "published educational band and ensemble music.\n\n"
        "Piece to catalogue:\n" + "\n".join(f"  {l}" for l in context_lines) + "\n\n"
        "Use your knowledge of this specific published work as the PRIMARY source. "
        "Cross-reference with what these band music databases list for this piece: "
        "windrep.org (Wind Repertoire Project), jwpepper.com (J.W. Pepper), and "
        "sheetmusicplus.com. Their listings take priority over general estimation. "
        "Image hints above are supplemental. "
        "If you cannot confidently determine a value, return an empty string — do not guess.\n\n"
        "Fields:\n"
        "- title: exact corrected full title\n"
        "- composer: full name of original composer\n"
        "- arranger: full name of arranger (empty if none)\n"
        "- difficulty: rate the SPECIFIC PUBLISHED ARRANGEMENT (not the original "
        "  composition) on a 1–5 scale. "
        "  FIRST: check windrep.org, jwpepper.com, or sheetmusicplus.com for a listed grade "
        "  and convert: Grade 1→1, Grade 2→2, Grade 3→3, Grade 4→4, Grade 5→4.5, Grade 6→5. "
        "  SECOND: if the piece is not in those databases (e.g. non-US publisher, jazz band, "
        "  less-known edition), estimate based on style, complexity, and instrumentation using "
        "  these anchors: 1=very easy/beginning band, 2=easy/early middle school, "
        "  3=developing middle school, 4=strong middle/early high school, 4.5–5=advanced. "
        "  Jazz band context: Easy Jazz=1–2, Medium Jazz=2.5–3, Medium-Advanced=3.5–4, "
        "  Advanced=4.5–5. Educational arrangements of complex orchestral works are typically "
        "  Grade 2–3. Only leave blank if you have absolutely no basis for estimation.\n"
        "- key_signature: CONCERT PITCH key as heard by the audience / played by "
        "  C instruments (flute, oboe, trombone, tuba). Use your knowledge of the "
        "  published piece — do NOT attempt to read from a transposing instrument part. "
        "  List comma-separated if the piece modulates (e.g. 'Ab Major, F Minor').\n"
        "- time_signature: primary meter; use visible value if provided, "
        "  otherwise from knowledge (e.g. '4/4', '3/4', '6/8').\n"
        "- publisher: publishing house (e.g. Hal Leonard, Alfred Music, Carl Fischer, "
        "  FJH Music, Boosey & Hawkes, C.L. Barnhouse, Southern Music). "
        "  Use visible value if provided; otherwise use your knowledge of this edition.\n"
        "- genre: one of: March, Concert, Pop/Rock, Classical, Jazz, World, "
        "  Holiday, Warm-Up, Method Book, Chorale, Other\n"
        "- ensemble_type: one of: Concert Band, Jazz Band, Percussion Ensemble, "
        "  Small Ensemble, Solo, Marching Band, Other\n"
        "- comments: Two parts separated by a newline:\n"
        "  Part 1: One sentence describing what the piece is (style, origin, mood, character).\n"
        "  Part 2: A short bulleted list (• bullet per line) of info a middle school band "
        "  director needs when deciding whether to program this for a concert. "
        "  Only include bullets you know with confidence:\n"
        "    • Duration: approximate performance time (e.g. ~3:30)\n"
        "    • Features: notable solos, featured sections, special instruments\n"
        "    • Occasion: ideal context (opener, closer, holiday concert, contest, etc.)\n"
        "    • Challenges: technical demands worth flagging (range, exposed solos, etc.)\n"
        "    • Extras: alternate versions, special equipment, programmatic content, etc.\n"
        "  Omit any bullet whose info is already captured in the structured fields "
        "  (genre, difficulty, key, time sig, publisher, ensemble type).\n\n"
        "Respond ONLY with a JSON object with those exact keys."
    )

    raw = query(base_dir, prompt)
    enriched = _extract_json(raw)
    if isinstance(enriched, dict):
        # Merge: enriched wins over phase-1 data, but keep visible_notes
        result = dict(piece)
        result.update(enriched)
        return result

    # Enrichment failed — return phase-1 data as-is
    return piece


def _extract_titles_from_collection_image(
    path: str, images: list[dict], base_dir: str
) -> list[dict]:
    """
    For images that show multiple titles (e.g. a photo of binder spines on a shelf).
    Returns a list of minimal piece dicts {title, composer, ...}.
    """
    from llm_client import query_with_images

    prompt = (
        "You are a music librarian cataloguing sheet music from a photo.\n\n"
        "This image shows multiple pieces of sheet music (e.g. binder spines on a shelf, "
        "a stack of folders, or a storage cabinet). Extract EVERY title and composer "
        "you can read.\n\n"
        "For each piece you can make out:\n"
        "- title: the piece title as it appears\n"
        "- composer: composer or arranger name if visible\n"
        "- visible_notes: any other text visible (grade, publisher, etc.)\n\n"
        "Respond ONLY with a JSON array of objects. Include only what you can actually read.\n"
        '{"title": "...", "composer": "...", "arranger": "", "publisher": "", '
        '"instrument_parts": "", "time_signature": "", "visible_notes": "..."}\n'
        "Do not add commentary."
    )

    raw = query_with_images(base_dir, prompt, images)
    result = _extract_json(raw)
    if isinstance(result, list):
        return result
    if isinstance(result, dict):
        return [result]
    return []


def analyze_music_files(
    paths: list[str],
    base_dir: str,
    progress_cb,   # callable(message: str)
    cancel_flag,   # list with one bool — checked to cancel
) -> list[dict]:
    """
    Full analysis pipeline. Returns list of enriched piece dicts.

    PDFs → always 1 piece per file (filename-driven, images just confirm).
    Images → LLM decides: if it looks like a single scan, 1 piece;
             if it's a collection photo (shelf/binders), extract all visible titles.
    """
    all_pieces: list[dict] = []
    _IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp"}

    for file_idx, path in enumerate(paths):
        if cancel_flag[0]:
            break
        fname = Path(path).name
        ext = Path(path).suffix.lower()
        is_image = ext in _IMAGE_EXTS

        progress_cb(f"[{file_idx + 1}/{len(paths)}] Reading: {fname}")
        images = _file_to_images(path)

        # ── Images: let LLM decide if it's a single scan or a collection photo ──
        if is_image and images:
            try:
                pieces = _classify_and_extract(path, images, base_dir, progress_cb)
            except Exception as e:
                progress_cb(f"  Vision failed ({e}) — using filename only")
                t, c = _filename_hints(path)
                pieces = [{"title": t, "composer": c, "arranger": "", "publisher": "",
                           "instrument_parts": "", "time_signature": "", "visible_notes": ""}]
        # ── PDFs (or unreadable images): always 1 piece per file ──
        else:
            try:
                piece = _identify_piece(path, images, base_dir)
            except Exception as e:
                progress_cb(f"  Vision failed ({e}) — using filename only")
                t, c = _filename_hints(path)
                piece = {"title": t, "composer": c, "arranger": "", "publisher": "",
                         "instrument_parts": "", "time_signature": "", "visible_notes": ""}
            pieces = [piece]

        if not pieces:
            progress_cb(f"  Nothing found in: {fname}")
            continue

        for p in pieces:
            parts_note = f" [{p.get('instrument_parts')}]" if p.get("instrument_parts") else ""
            progress_cb(f"  Found: {p.get('title', '?')[:55]}{parts_note}")

        for piece in pieces:
            if cancel_flag[0]:
                break
            title = piece.get("title") or "?"
            progress_cb(f"  Enriching: {title[:55]}")
            try:
                enriched = _enrich_piece(piece, base_dir)
            except Exception as e:
                progress_cb(f"  Enrichment failed ({e}) — using basic data")
                enriched = piece
            all_pieces.append(enriched)

    return all_pieces


def _classify_and_extract(
    path: str, images: list[dict], base_dir: str, progress_cb
) -> list[dict]:
    """
    For image files: ask the LLM whether this is a single-piece scan or a
    collection photo, then dispatch accordingly.
    """
    from llm_client import query_with_images

    probe = (
        "Look at this image. Is it:\n"
        "  A) A scan or photo of a SINGLE piece of sheet music (cover, title page, "
        "or notation for one piece)\n"
        "  B) A photo showing MULTIPLE pieces at once (shelf of binders, stack of "
        "folders, cabinet, or any view where you can read several different titles)\n\n"
        "Reply with ONLY the letter A or B."
    )
    kind = query_with_images(base_dir, probe, images).strip().upper()

    if kind.startswith("B"):
        progress_cb("  Collection photo detected — extracting all visible titles")
        return _extract_titles_from_collection_image(path, images, base_dir)
    else:
        progress_cb("  Single piece scan detected")
        result = _identify_piece(path, images, base_dir)
        return [result]


def _clean_title(raw: str) -> str:
    """Strip leading piece-number prefix from a title (e.g. '12 The Clock Strikes' → 'The Clock Strikes')."""
    # Match patterns like "12 ", "12. ", "12 - ", "No. 12 " at the start
    cleaned = re.sub(r"^(?:No\.?\s*)?\d+\s*[-.]?\s*", "", raw).strip()
    return cleaned if cleaned else raw  # fallback to original if stripping empties it


def _dict_to_prefill(d: dict) -> dict:
    """Normalise an enriched piece dict into MusicDialog prefill_data keys."""
    def _s(key, *aliases):
        for k in (key, *aliases):
            v = d.get(k)
            if v:
                return str(v).strip()
        return ""

    return {
        "title":          _clean_title(_s("title")),
        "composer":       _s("composer"),
        "arranger":       _s("arranger"),
        "publisher":      _s("publisher"),
        "genre":          _s("genre"),
        "ensemble_type":  _s("ensemble_type"),
        "difficulty":     _s("difficulty"),
        "key_signature":  _s("key_signature"),
        "time_signature": _s("time_signature"),
        "location":       "Chinook Middle School",
        "notes":          _s("comments", "visible_notes", "notes"),
    }


# ── Progress Dialog ───────────────────────────────────────────────────────────

class ImportProgressDialog(ttk.Toplevel):
    """
    Shows analysis progress and returns results via self.results when done.
    self.results is None if cancelled or failed, else list of prefill dicts.
    """

    def __init__(self, parent, paths: list[str], base_dir: str):
        super().__init__(parent)
        self.paths = paths
        self.base_dir = base_dir
        self.results = None
        self._cancel_flag = [False]

        self.title("Importing Sheet Music…")
        self.geometry("540x360")
        self.resizable(False, True)
        self.grab_set()

        self.update_idletasks()
        x = (self.winfo_screenwidth() - 540) // 2
        y = (self.winfo_screenheight() - 360) // 2
        self.geometry(f"+{x}+{y}")

        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self._build()
        self.after(100, self._start)

    def _build(self):
        hdr = ttk.Frame(self, bootstyle=INFO)
        hdr.pack(fill=X)
        ttk.Label(
            hdr, text="  🎼  Analyzing Sheet Music",
            font=("Segoe UI", 12, "bold"),
            bootstyle=(INVERSE, INFO),
        ).pack(pady=10, padx=12, anchor=W)

        ttk.Label(
            self,
            text=f"Processing {len(self.paths)} file(s) — this may take a minute…",
            font=("Segoe UI", 9), foreground="#555",
        ).pack(anchor=W, padx=14, pady=(10, 4))

        log_frame = ttk.Frame(self)
        log_frame.pack(fill=BOTH, expand=True, padx=12, pady=(0, 8))

        sb = ttk.Scrollbar(log_frame, orient=VERTICAL)
        self._log = tk.Text(
            log_frame, wrap=WORD, state="disabled",
            font=("Consolas", 8), relief="flat",
            yscrollcommand=sb.set,
        )
        sb.config(command=self._log.yview)
        sb.pack(side=RIGHT, fill=Y)
        self._log.pack(fill=BOTH, expand=True)

        self._status_lbl = ttk.Label(
            self, text="Starting…", font=("Segoe UI", 8), foreground="#555"
        )
        self._status_lbl.pack(anchor=W, padx=14, pady=(0, 4))

        btn_frame = ttk.Frame(self)
        btn_frame.pack(fill=X, padx=12, pady=8)
        self._cancel_btn = ttk.Button(
            btn_frame, text="Cancel",
            bootstyle=(SECONDARY, OUTLINE),
            command=self._cancel,
        )
        self._cancel_btn.pack(side=RIGHT)

    def _log_line(self, msg: str):
        self._log.config(state="normal")
        self._log.insert("end", msg + "\n")
        self._log.config(state="disabled")
        self._log.see("end")
        self._status_lbl.config(text=msg[:80])

    def _start(self):
        def _run():
            try:
                raw_pieces = analyze_music_files(
                    self.paths, self.base_dir,
                    lambda msg: self.after(0, self._log_line, msg),
                    self._cancel_flag,
                )
                prefills = [_dict_to_prefill(p) for p in raw_pieces]
                self.after(0, self._done, prefills)
            except Exception as e:
                self.after(0, self._done, None, str(e))

        threading.Thread(target=_run, daemon=True).start()

    def _done(self, prefills, error=None):
        if error:
            self._log_line(f"ERROR: {error}")
            self._status_lbl.config(text="Analysis failed.", foreground="#cc0000")
            self._cancel_btn.config(text="Close")
            return

        if self._cancel_flag[0]:
            self._log_line("Cancelled.")
            self.results = []
            self.destroy()
            return

        self.results = prefills or []
        self.destroy()

    def _cancel(self):
        self._cancel_flag[0] = True
        self._cancel_btn.config(state="disabled")
        self._status_lbl.config(text="Cancelling…")
