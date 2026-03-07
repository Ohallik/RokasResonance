"""
ui/music_importer.py - AI-powered sheet music import from images/PDFs

Flow:
  1. User selects files (PDF / PNG / JPG / etc.)
  2. Each image is classified into one of four types:
       SINGLE_PIECE       - one score page or one folder cover
       FLAT_COVERS        - multiple folders laid face-up on a table
       SPINE_SHELF        - shelf/cabinet with vertical binder spines
       TABLE_OF_CONTENTS  - a printed list/index of titles
  3. A specialized extraction prompt is used for each type.
  4. Optionally each piece is enriched via a text query (difficulty, key, genre).
  5. BatchImportDialog shows all found pieces for review before importing.
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


# ── Image helpers ──────────────────────────────────────────────────────────────

def _file_to_images(path: str, max_px: int = 1800) -> list[dict]:
    """Convert a file to a list of image dicts {mime_type, data}."""
    ext = Path(path).suffix.lower()
    images = []

    if ext == ".pdf":
        try:
            import fitz
            doc = fitz.open(path)
            for i, page in enumerate(doc):
                if i >= 3:
                    break
                mat = fitz.Matrix(150 / 72, 150 / 72)
                pix = page.get_pixmap(matrix=mat, colorspace=fitz.csRGB)
                images.append({
                    "mime_type": "image/png",
                    "data": base64.b64encode(pix.tobytes("png")).decode(),
                })
            doc.close()
        except ImportError:
            pass
    else:
        try:
            from PIL import Image
            img = Image.open(path).convert("RGB")
            w, h = img.size
            scale = min(1.0, max_px / max(w, h))
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


# ── JSON extraction ────────────────────────────────────────────────────────────

def _extract_json(text: str) -> list | dict | None:
    m = re.search(r"```(?:json)?\s*([\s\S]+?)```", text)
    if m:
        text = m.group(1).strip()
    for pattern in (r"(\[[\s\S]+\])", r"(\{[\s\S]+\})"):
        m = re.search(pattern, text)
        if m:
            try:
                return json.loads(m.group(1))
            except json.JSONDecodeError:
                pass
    return None


# ── Filename hints ─────────────────────────────────────────────────────────────

def _filename_hints(path: str) -> tuple[str, str]:
    stem = Path(path).stem
    # Camera-generated filenames (IMG_1234, DSC_5678, etc.) carry no title info
    if re.match(r'^(?:IMG|DSC|DCIM|PHOTO|PIC|IMAGE|P\d{1,2})[-_]?\d+$', stem, re.IGNORECASE):
        return "", ""
    clean = re.sub(r"^\d+\s*[-.]?\s*", "", stem)
    parts = [p.strip() for p in clean.split(" - ", 1)]
    title = parts[0] if parts else clean
    composer = parts[1] if len(parts) > 1 else ""
    return title, composer


# ── 4-way image classifier ─────────────────────────────────────────────────────

def _classify_image(images: list[dict], base_dir: str, on_retry=None) -> str:
    """
    Returns one of: SINGLE_PIECE, FLAT_COVERS, SPINE_SHELF, TABLE_OF_CONTENTS
    """
    from llm_client import query_with_images

    probe = (
        "Look at this image and classify it into EXACTLY one of these categories:\n\n"
        "  A) SINGLE_PIECE — a scan or photo of ONE piece of sheet music "
        "(one cover, one score page, or one folder shown alone). "
        "There is only a single title visible as the main piece.\n"
        "  B) FLAT_COVERS — multiple music folders or booklets laid face-up "
        "on a table or floor, so you can see their front covers\n"
        "  C) SPINE_SHELF — a shelf, cabinet, or rack where you can see the "
        "vertical spine text of multiple binders or folders stored upright\n"
        "  D) TABLE_OF_CONTENTS — any page or document that lists MULTIPLE piece "
        "titles in rows or columns. This includes: a printed table of contents, "
        "an index page, a set list, a conductor packet contents page, a folder "
        "insert listing songs in a collection, or a concert program listing pieces. "
        "If you can count 3 or more piece titles listed on the page, choose D.\n\n"
        "Reply with ONLY the letter: A, B, C, or D."
    )
    try:
        kind = query_with_images(base_dir, probe, images, on_retry=on_retry).strip().upper()
    except Exception:
        return "SINGLE_PIECE"

    if kind.startswith("B"):
        return "FLAT_COVERS"
    if kind.startswith("C"):
        return "SPINE_SHELF"
    if kind.startswith("D"):
        return "TABLE_OF_CONTENTS"
    return "SINGLE_PIECE"


# ── Extraction: SINGLE_PIECE ───────────────────────────────────────────────────

def _extract_single_piece(path: str, images: list[dict], base_dir: str, on_retry=None) -> list[dict]:
    from llm_client import query_with_images

    title_hint, composer_hint = _filename_hints(path)
    fname = Path(path).stem
    composer_str = f' by "{composer_hint}"' if composer_hint else ""

    _EMPTY = {
        "title": title_hint, "composer": composer_hint, "arranger": "",
        "publisher": "", "ensemble_type": "", "difficulty": "",
        "time_signature": "", "visible_notes": "",
    }

    if not images:
        return [_EMPTY]

    if title_hint:
        intro = f'This image shows ONE piece of sheet music, likely titled "{title_hint}"{composer_str}.'
        title_instruction = "- title: the piece title (confirm or correct the hint above)\n"
    else:
        intro = "This image shows ONE piece of sheet music."
        title_instruction = "- title: the piece title as printed on the cover or score\n"

    prompt = (
        intro + "\n\n"
        "Extract everything you can clearly see:\n"
        + title_instruction +
        "- composer: full composer name\n"
        "- arranger: arranger name if visible, else empty\n"
        "- publisher: publishing house if visible "
        "(e.g. Hal Leonard, Alfred, Carl Fischer, FJH, C.L. Barnhouse)\n"
        "- ensemble_type: Concert Band, Jazz Band, Percussion Ensemble, "
        "Small Ensemble, Solo, Marching Band, or Other\n"
        "- difficulty: grade/level if shown (e.g. 'Grade 2', 'Level 1', 'Easy Jazz')\n"
        "- time_signature: meter if clearly shown (e.g. '4/4', '3/4')\n"
        "- visible_notes: any other useful text (catalog number, year, series name)\n\n"
        "Respond ONLY with a single JSON object. Use empty string for anything not visible.\n"
        '{"title":"","composer":"","arranger":"","publisher":"","ensemble_type":"",'
        '"difficulty":"","time_signature":"","visible_notes":""}'
    )

    try:
        raw = query_with_images(base_dir, prompt, images, on_retry=on_retry)
        result = _extract_json(raw)
        if isinstance(result, dict):
            return [result]
        if isinstance(result, list) and result:
            return [result[0]]
    except Exception:
        pass
    return [_EMPTY]


# ── Extraction: FLAT_COVERS ────────────────────────────────────────────────────

def _extract_flat_covers(images: list[dict], base_dir: str, on_retry=None) -> list[dict]:
    from llm_client import query_with_images

    prompt = (
        "This image shows multiple pieces of sheet music laid face-up on a surface. "
        "Each folder or booklet is a separate piece.\n\n"
        "For EACH cover you can clearly read, extract:\n"
        "- title: piece title exactly as printed on the cover\n"
        "- composer: composer name if visible\n"
        "- arranger: arranger name if visible, else empty\n"
        "- publisher: publishing house (logo, text, or imprint) if visible. "
        "Common publishers: Hal Leonard, Alfred Music, Carl Fischer, FJH Music, "
        "C.L. Barnhouse, Warner Bros, Southern Music.\n"
        "- ensemble_type: Concert Band, Jazz Band, Percussion Ensemble, "
        "Small Ensemble, Solo, Marching Band, or Other — infer from series name if needed\n"
        "- difficulty: grade or level if shown on the cover\n"
        "- visible_notes: any other text visible on that cover (series, catalog number, year)\n\n"
        "Include EVERY cover whose title you can read. "
        "Respond ONLY with a JSON array. Use empty string for anything not visible.\n"
        '[{"title":"","composer":"","arranger":"","publisher":"","ensemble_type":"",'
        '"difficulty":"","visible_notes":""}]'
    )

    try:
        raw = query_with_images(base_dir, prompt, images, on_retry=on_retry)
        result = _extract_json(raw)
        if isinstance(result, list):
            return result
        if isinstance(result, dict):
            return [result]
    except Exception:
        pass
    return []


# ── Extraction: SPINE_SHELF ────────────────────────────────────────────────────

def _extract_spine_shelf(images: list[dict], base_dir: str, on_retry=None) -> list[dict]:
    from llm_client import query_with_images

    prompt = (
        "This image shows sheet music binders or folders stored upright on a shelf "
        "or in a file cabinet. The title text runs vertically along each spine.\n\n"
        "Carefully read each visible spine. The text is rotated — tilt your "
        "perspective. For each piece you can make out:\n"
        "- title: piece title (read the vertical text carefully)\n"
        "- composer: composer or arranger name if printed on the spine\n"
        "- publisher: publisher name if visible on the spine. "
        "Common publishers: Hal Leonard, Alfred, Carl Fischer, FJH, "
        "C.L. Barnhouse, Warner Bros, Manhattan Beach Music.\n"
        "- ensemble_type: infer from spine text if possible "
        "(e.g. 'Beginning Band Series' → Concert Band, 'Easy Jazz Ensemble' → Jazz Band, "
        "'Young Band' → Concert Band, 'FJH Beginning Band' → Concert Band)\n"
        "- visible_notes: any other text on that spine (grade level, catalog number, series)\n\n"
        "Include EVERY spine you can read, even if the title is partial. "
        "Respond ONLY with a JSON array. Use empty string for anything not visible.\n"
        '[{"title":"","composer":"","publisher":"","ensemble_type":"","visible_notes":""}]'
    )

    try:
        raw = query_with_images(base_dir, prompt, images, on_retry=on_retry)
        result = _extract_json(raw)
        if isinstance(result, list):
            return result
        if isinstance(result, dict):
            return [result]
    except Exception:
        pass
    return []


# ── Extraction: TABLE_OF_CONTENTS ─────────────────────────────────────────────

def _extract_toc(images: list[dict], base_dir: str, on_retry=None) -> list[dict]:
    from llm_client import query_with_images

    prompt = (
        "This image shows a printed table of contents, index, or set list for "
        "a music collection.\n\n"
        "Extract EVERY entry in the list. For each row:\n"
        "- title: piece title exactly as printed\n"
        "- composer: composer name if listed in this row\n"
        "- arranger: arranger name if listed (often shown as 'arr.' or 'Arranged by')\n"
        "- visible_notes: page number or any other info from this row\n\n"
        "Read the entire page — some pages may be upside-down or at an angle. "
        "Respond ONLY with a JSON array. Use empty string for missing fields.\n"
        '[{"title":"","composer":"","arranger":"","visible_notes":""}]'
    )

    try:
        raw = query_with_images(base_dir, prompt, images, on_retry=on_retry)
        result = _extract_json(raw)
        if isinstance(result, list):
            return result
        if isinstance(result, dict):
            return [result]
    except Exception:
        pass
    return []


# ── Enrichment (optional) ──────────────────────────────────────────────────────

_ENRICH_SYSTEM = (
    "You are a band director and music librarian with deep knowledge of "
    "published educational band and ensemble music."
)

_ENRICH_FIELDS = (
    "Fields to fill:\n"
    "- title: exact corrected full title\n"
    "- composer: full name of original composer\n"
    "- arranger: full name of arranger (empty if none)\n"
    "- publisher: publishing house\n"
    "- difficulty: 1–5 scale. Grade 1→1, Grade 2→2, Grade 3→3, Grade 4→4, "
    "  Grade 5→4.5, Grade 6→5. "
    "  1=beginning band, 2=easy middle school, 3=developing middle school, "
    "  4=strong middle/early high school, 5=advanced.\n"
    "- key_signature: concert pitch key. Comma-separated if the piece modulates.\n"
    "- time_signature: primary meter (e.g. '4/4', '3/4', '6/8')\n"
    "- genre: March, Concert, Pop/Rock, Classical, Jazz, World, Holiday, "
    "  Warm-Up, Method Book, Chorale, or Other\n"
    "- ensemble_type: Concert Band, Jazz Band, Percussion Ensemble, "
    "  Small Ensemble, Solo, Marching Band, or Other\n"
    "- comments: One sentence describing the piece, then a bullet list of "
    "  duration, notable features, ideal occasion, challenges, and extras. "
    "  Omit bullets that duplicate structured fields.\n"
    "- confidence: high | medium | low — your overall confidence that the "
    "  above facts are correct for THIS specific published work. "
    "  high = you know this piece well from a recognised publisher; "
    "  medium = you are fairly sure but the title is common or details are thin; "
    "  low = you are inferring or the piece is obscure.\n\n"
    "Respond ONLY with a JSON object with those exact keys."
)


def _ddg_search(piece: dict) -> str:
    """Free DuckDuckGo search for a piece. Returns concatenated snippets or ''."""
    try:
        try:
            from ddgs import DDGS
        except ImportError:
            from duckduckgo_search import DDGS
    except ImportError:
        return ""

    title    = (piece.get("title")    or "").strip()
    composer = (piece.get("composer") or "").strip()
    arranger = (piece.get("arranger") or "").strip()
    names = " ".join(filter(None, [composer, arranger]))
    query = f'"{title}" {names} band sheet music'.strip()

    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=5))
        parts = [
            f"[{r.get('href', '')}]\n{r.get('body', '').strip()}"
            for r in results if r.get("body", "").strip()
        ]
        return "\n\n".join(parts)
    except Exception:
        return ""


def _enrich_piece(piece: dict, base_dir: str, on_retry=None) -> dict:
    """
    Three-tier enrichment:
      1. Free DuckDuckGo search → Haiku parses snippets  (~$0)
      2. Haiku + Anthropic web search, 1 use             (~$0.05/piece)
      3. Selected model, training knowledge only          (no search cost)
    """
    title = (piece.get("title") or "").strip()
    if not title:
        return piece

    context_lines = [f'Title: "{title}"']
    for key, label in [
        ("composer", "Composer"), ("arranger", "Arranger"),
        ("publisher", "Publisher"), ("ensemble_type", "Ensemble type"),
        ("time_signature", "Time signature visible"),
        ("visible_notes", "Other visible info"),
    ]:
        val = (piece.get(key) or "").strip()
        if val:
            context_lines.append(f"{label}: {val}")

    piece_context = "\n".join(f"  {l}" for l in context_lines)

    _PLACEHOLDERS = {
        "unknown", "n/a", "none", "not specified", "not listed",
        "not available", "not found", "not applicable", "undetermined",
        "varies", "various", "tbd", "see score", "see parts",
    }

    def _is_placeholder(v: str) -> bool:
        vl = v.lower().strip().rstrip(".")
        return (vl in _PLACEHOLDERS
                or vl.startswith("not specified")
                or vl.startswith("not listed")
                or vl.startswith("not found")
                or vl.startswith("unknown")
                or vl.startswith("not available"))

    def _apply(raw):
        enriched = _extract_json(raw)
        if not isinstance(enriched, dict):
            return None
        result = dict(piece)
        for k, v in enriched.items():
            if v is None:
                continue
            sv = str(v).strip()
            if not sv or _is_placeholder(sv):
                continue
            # Don't overwrite a real existing value with something worse
            existing = str(result.get(k) or "").strip()
            if existing and _is_placeholder(sv):
                continue
            result[k] = v
        return result

    # ── Tier 1: Free DuckDuckGo search → Haiku (text-only) ──────────────────
    tier1_result = None
    snippets = _ddg_search(piece)
    if snippets:
        prompt = (
            f"Piece:\n{piece_context}\n\n"
            "Web search results (use as PRIMARY facts where they match this piece):\n"
            f"{snippets}\n\n"
            "Use the search results combined with your knowledge to fill in all fields. "
            "If the search results don't match this piece, rely on your training knowledge.\n\n"
            + _ENRICH_FIELDS
        )
        try:
            from llm_client import query_haiku
            result = _apply(query_haiku(base_dir, prompt,
                                        system_prompt=_ENRICH_SYSTEM, on_retry=on_retry))
            if result:
                conf = str(result.get("confidence") or "").strip().lower()
                if conf != "low":
                    return result  # confident enough — stop here
                tier1_result = result  # low confidence — save as fallback, escalate
        except Exception:
            pass

    # ── Tier 2: Haiku + Anthropic web search (1 search) ─────────────────────
    # Runs when: DDG found nothing, Tier 1 threw, or Tier 1 confidence was low.
    try:
        from llm_client import query_haiku_with_search
        prompt = (
            f"Piece:\n{piece_context}\n\n"
            "Search for this piece on windrep.org, jwpepper.com, or sheetmusicplus.com. "
            "Use any data found as PRIMARY facts; fall back to training knowledge for missing fields.\n\n"
            + _ENRICH_FIELDS
        )
        result = _apply(query_haiku_with_search(base_dir, prompt,
                                                system_prompt=_ENRICH_SYSTEM, on_retry=on_retry))
        if result:
            return result
    except Exception:
        pass

    # ── Tier 3: Selected model, training knowledge only ──────────────────────
    # Runs when Tier 2 failed (or wasn't reached). Tier 1 low-confidence data
    # is not used here — if Tier 2 failed, Tier 1 data is likely unreliable too.
    try:
        from llm_client import query
        prompt = (
            f"Piece:\n{piece_context}\n\n"
            "Using your training knowledge and best inference, fill in all fields. "
            "Do not leave fields empty unless you have no basis to infer a value.\n\n"
            + _ENRICH_FIELDS
        )
        result = _apply(query(base_dir, prompt,
                              system_prompt=_ENRICH_SYSTEM, on_retry=on_retry))
        if result:
            return result
    except Exception:
        pass

    # Last resort: use low-confidence Tier 1 data rather than nothing
    if tier1_result:
        return tier1_result

    return piece


# ── Main analysis pipeline ─────────────────────────────────────────────────────

def analyze_music_files(
    paths: list[str],
    base_dir: str,
    progress_cb,
    cancel_flag,
    enrich: bool = False,
    results_list: list | None = None,
    mode: str = "band",
) -> list[dict]:
    """
    Full analysis pipeline. Returns list of piece dicts.
    enrich=False (default): vision-only extraction, fast.
    enrich=True: adds a knowledge-enrichment LLM call per piece.
    results_list: if provided, pieces are appended here as they are found (for partial import).
    """
    all_pieces: list[dict] = results_list if results_list is not None else []
    _IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp"}

    for file_idx, path in enumerate(paths):
        if cancel_flag[0]:
            break

        fname = Path(path).name
        ext = Path(path).suffix.lower()
        is_image = ext in _IMAGE_EXTS

        progress_cb(f"[{file_idx + 1}/{len(paths)}] {fname}")
        images = _file_to_images(path, max_px=1800)

        if not images:
            progress_cb("  Could not read file — skipping")
            continue

        def _retry_cb(n, d):
            progress_cb(f"  Rate limited — retry {n} in {d}s...")

        try:
            if is_image:
                progress_cb("  Classifying...")
                img_type = _classify_image(images, base_dir, on_retry=_retry_cb)
                progress_cb(f"  {img_type.replace('_', ' ').title()}")

                if mode == "choir":
                    if img_type == "FLAT_COVERS":
                        progress_cb("  Extracting covers...")
                        pieces = _extract_flat_covers_choir(images, base_dir, on_retry=_retry_cb)
                    elif img_type == "SPINE_SHELF":
                        progress_cb("  Extracting spines (high-res)...")
                        hi_res = _file_to_images(path, max_px=2400)
                        pieces = _extract_spine_shelf_choir(hi_res or images, base_dir, on_retry=_retry_cb)
                    elif img_type == "TABLE_OF_CONTENTS":
                        progress_cb("  Extracting TOC...")
                        pieces = _extract_toc(images, base_dir, on_retry=_retry_cb)
                    else:
                        progress_cb("  Extracting piece...")
                        pieces = _extract_single_piece_choir(path, images, base_dir, on_retry=_retry_cb)
                else:
                    if img_type == "FLAT_COVERS":
                        progress_cb("  Extracting covers...")
                        pieces = _extract_flat_covers(images, base_dir, on_retry=_retry_cb)
                    elif img_type == "SPINE_SHELF":
                        progress_cb("  Extracting spines (high-res)...")
                        hi_res = _file_to_images(path, max_px=2400)
                        pieces = _extract_spine_shelf(hi_res or images, base_dir, on_retry=_retry_cb)
                    elif img_type == "TABLE_OF_CONTENTS":
                        progress_cb("  Extracting TOC...")
                        pieces = _extract_toc(images, base_dir, on_retry=_retry_cb)
                    else:
                        progress_cb("  Extracting piece...")
                        pieces = _extract_single_piece(path, images, base_dir, on_retry=_retry_cb)
            else:
                progress_cb("  Extracting piece...")
                if mode == "choir":
                    pieces = _extract_single_piece_choir(path, images, base_dir, on_retry=_retry_cb)
                else:
                    pieces = _extract_single_piece(path, images, base_dir, on_retry=_retry_cb)

        except Exception as e:
            progress_cb(f"  Vision failed: {e}")
            t, c = _filename_hints(path)
            pieces = [{"title": t, "composer": c, "arranger": "", "publisher": "",
                       "difficulty": "", "visible_notes": ""}]

        if not pieces:
            progress_cb("  Nothing found")
            continue

        progress_cb(f"  Found {len(pieces)} piece(s)")

        for piece in pieces:
            if cancel_flag[0]:
                break
            if not piece.get("title", "").strip():
                progress_cb("  (skipping piece with no title)")
                continue
            piece["_source_file"] = fname
            if enrich:
                title = piece.get("title", "").strip()
                progress_cb(f"  Enriching: {title[:50]}")
                try:
                    if mode == "choir":
                        piece = _enrich_piece_choir(piece, base_dir, on_retry=_retry_cb)
                    else:
                        piece = _enrich_piece(piece, base_dir, on_retry=_retry_cb)
                except Exception as e:
                    progress_cb(f"  Enrichment failed after all retries: {e}")
            all_pieces.append(piece)

    return all_pieces


# ── Normalisation / prefill ────────────────────────────────────────────────────

def _clean_title(raw: str) -> str:
    cleaned = re.sub(r"^(?:No\.?\s*)?\d+\s*[-.]?\s*", "", raw).strip()
    return cleaned if cleaned else raw


def _norm_title(t: str) -> str:
    """Normalised title for duplicate comparison (lowercase, alphanum only)."""
    return re.sub(r"[^a-z0-9]", "", t.lower())


def _dict_to_prefill(d: dict, existing_titles: set[str] | None = None) -> dict:
    def _s(*keys):
        for k in keys:
            v = d.get(k)
            if v:
                return str(v).strip()
        return ""

    # Normalise difficulty: "Grade 2" / "Level 2" → "2"
    diff = _s("difficulty")
    m = re.search(r"(\d+(?:\.\d+)?)", diff)
    diff = m.group(1) if m else diff

    title = _clean_title(_s("title"))
    prefill = {
        "title":          title,
        "composer":       _s("composer"),
        "arranger":       _s("arranger"),
        "publisher":      _s("publisher"),
        "genre":          _s("genre"),
        "ensemble_type":  _s("ensemble_type"),
        "difficulty":     diff,
        "key_signature":  _s("key_signature"),
        "time_signature": _s("time_signature"),
        "location":       "Chinook Middle School",
        "notes":          _s("comments", "visible_notes", "notes"),
        "_duplicate":     False,
        "_source_file":   d.get("_source_file", ""),
        "_confidence":    d.get("confidence", "").strip().lower(),
    }

    if existing_titles and title:
        prefill["_duplicate"] = _norm_title(title) in existing_titles

    return prefill


# ── Choir-specific constants ───────────────────────────────────────────────────

_ENRICH_SYSTEM_CHOIR = (
    "You are a choir director and choral music librarian with deep knowledge of "
    "published educational and professional choral music."
)

_ENRICH_FIELDS_CHOIR = (
    "Fields to fill:\n"
    "- title: exact corrected full title\n"
    "- composer: full name of original composer\n"
    "- arranger: full name of arranger/editor (empty if none)\n"
    "- publisher: publishing house\n"
    "- difficulty: 1–5 scale. 1=beginning/unison, 2=easy (SSA/SAB), "
    "  3=developing (SATB with support), 4=strong SATB, 5=advanced/complex.\n"
    "- key_signature: concert pitch key. Comma-separated if the piece modulates.\n"
    "- voicing: e.g. SATB, SSA, SAB, TTBB, Unison, 2-Part, 3-Part Mixed, 4-Part Mixed, "
    "  or the specific voicing printed on the score.\n"
    "- language: primary language(s) of the text (e.g. English, Latin, Spanish, French, German).\n"
    "- accompaniment: Piano, A Cappella, Organ, Orchestra, Band, Guitar, or None.\n"
    "- genre: Sacred, Secular, Gospel, Folk, Classical, Pop/Rock, Holiday, "
    "  Show/Musical, World, Warm-Up, or Other\n"
    "- comments: One sentence describing the piece, then bullet points covering "
    "  duration, text source, performance occasion, vocal challenges, and extras. "
    "  Omit bullets that duplicate structured fields.\n"
    "- confidence: high | medium | low — your overall confidence that the "
    "  above facts are correct for THIS specific published work.\n\n"
    "Respond ONLY with a JSON object with those exact keys."
)


# ── Choir extraction: SINGLE_PIECE ────────────────────────────────────────────

def _extract_single_piece_choir(path: str, images: list[dict], base_dir: str, on_retry=None) -> list[dict]:
    from llm_client import query_with_images

    title_hint, composer_hint = _filename_hints(path)
    composer_str = f' by "{composer_hint}"' if composer_hint else ""

    _EMPTY = {
        "title": title_hint, "composer": composer_hint, "arranger": "",
        "publisher": "", "voicing": "", "difficulty": "",
        "language": "", "accompaniment": "", "visible_notes": "",
    }

    if not images:
        return [_EMPTY]

    if title_hint:
        intro = f'This image shows ONE choral piece, likely titled "{title_hint}"{composer_str}.'
        title_instruction = "- title: the piece title (confirm or correct the hint above)\n"
    else:
        intro = "This image shows ONE choral piece of sheet music."
        title_instruction = "- title: the piece title as printed on the cover or score\n"

    prompt = (
        intro + "\n\n"
        "Extract everything you can clearly see:\n"
        + title_instruction +
        "- composer: full composer name\n"
        "- arranger: arranger/editor name if visible, else empty\n"
        "- publisher: publishing house if visible "
        "(e.g. Hal Leonard, Alfred, G. Schirmer, Shawnee Press, Walton Music, "
        "Boosey & Hawkes, Mark Foster, Heritage Choral, Earthsongs)\n"
        "- voicing: e.g. SATB, SSA, SAB, TTBB, Unison, 2-Part, 3-Part Mixed — "
        "look for voicing printed on the cover or score\n"
        "- language: language(s) of the text if visible (e.g. English, Latin, Spanish)\n"
        "- accompaniment: Piano, A Cappella, Organ, Orchestra, Band, or None if visible\n"
        "- difficulty: grade/level if shown (e.g. 'Grade 2', 'Level 1', 'Easy')\n"
        "- visible_notes: any other useful text (catalog number, year, series name)\n\n"
        "Respond ONLY with a single JSON object. Use empty string for anything not visible.\n"
        '{"title":"","composer":"","arranger":"","publisher":"","voicing":"",'
        '"language":"","accompaniment":"","difficulty":"","visible_notes":""}'
    )

    try:
        raw = query_with_images(base_dir, prompt, images, on_retry=on_retry)
        result = _extract_json(raw)
        if isinstance(result, dict):
            return [result]
        if isinstance(result, list) and result:
            return [result[0]]
    except Exception:
        pass
    return [_EMPTY]


# ── Choir extraction: FLAT_COVERS ─────────────────────────────────────────────

def _extract_flat_covers_choir(images: list[dict], base_dir: str, on_retry=None) -> list[dict]:
    from llm_client import query_with_images

    prompt = (
        "This image shows multiple choral sheet music folders or booklets laid face-up. "
        "Each folder or booklet is a separate piece.\n\n"
        "For EACH cover you can clearly read, extract:\n"
        "- title: piece title exactly as printed on the cover\n"
        "- composer: composer name if visible\n"
        "- arranger: arranger/editor name if visible, else empty\n"
        "- publisher: publishing house if visible. "
        "Common choral publishers: Hal Leonard, Alfred, G. Schirmer, Shawnee Press, "
        "Walton Music, Boosey & Hawkes, Mark Foster, Heritage Choral, Earthsongs.\n"
        "- voicing: e.g. SATB, SSA, SAB, TTBB, Unison — look for voicing on the cover\n"
        "- language: language(s) of the text if visible\n"
        "- visible_notes: any other text (catalog number, series, occasion)\n\n"
        "Include EVERY cover whose title you can read. "
        "Respond ONLY with a JSON array. Use empty string for anything not visible.\n"
        '[{"title":"","composer":"","arranger":"","publisher":"","voicing":"",'
        '"language":"","visible_notes":""}]'
    )

    try:
        raw = query_with_images(base_dir, prompt, images, on_retry=on_retry)
        result = _extract_json(raw)
        if isinstance(result, list):
            return result
        if isinstance(result, dict):
            return [result]
    except Exception:
        pass
    return []


# ── Choir extraction: SPINE_SHELF ─────────────────────────────────────────────

def _extract_spine_shelf_choir(images: list[dict], base_dir: str, on_retry=None) -> list[dict]:
    from llm_client import query_with_images

    prompt = (
        "This image shows choral music binders or folders stored upright on a shelf. "
        "The title text runs vertically along each spine.\n\n"
        "Carefully read each visible spine. The text is rotated — tilt your "
        "perspective. For each piece you can make out:\n"
        "- title: piece title (read the vertical text carefully)\n"
        "- composer: composer or arranger name if printed on the spine\n"
        "- publisher: publisher name if visible. "
        "Common publishers: Hal Leonard, Alfred, G. Schirmer, Shawnee Press, "
        "Walton Music, Boosey & Hawkes, Mark Foster.\n"
        "- voicing: voicing if printed on spine (e.g. SATB, SSA, SAB)\n"
        "- visible_notes: any other text on that spine (grade level, catalog number)\n\n"
        "Include EVERY spine you can read, even if partial. "
        "Respond ONLY with a JSON array. Use empty string for anything not visible.\n"
        '[{"title":"","composer":"","publisher":"","voicing":"","visible_notes":""}]'
    )

    try:
        raw = query_with_images(base_dir, prompt, images, on_retry=on_retry)
        result = _extract_json(raw)
        if isinstance(result, list):
            return result
        if isinstance(result, dict):
            return [result]
    except Exception:
        pass
    return []


# ── Choir enrichment ──────────────────────────────────────────────────────────

def _enrich_piece_choir(piece: dict, base_dir: str, on_retry=None) -> dict:
    """Three-tier choir enrichment (voicing, language, accompaniment, choral genre)."""
    title = (piece.get("title") or "").strip()
    if not title:
        return piece

    context_lines = [f'Title: "{title}"']
    for key, label in [
        ("composer", "Composer"), ("arranger", "Arranger"),
        ("publisher", "Publisher"), ("voicing", "Voicing"),
        ("language", "Language"), ("accompaniment", "Accompaniment"),
        ("visible_notes", "Other visible info"),
    ]:
        val = (piece.get(key) or "").strip()
        if val:
            context_lines.append(f"{label}: {val}")

    piece_context = "\n".join(f"  {l}" for l in context_lines)

    _PLACEHOLDERS = {
        "unknown", "n/a", "none", "not specified", "not listed",
        "not available", "not found", "not applicable", "undetermined",
        "varies", "various", "tbd", "see score", "see parts",
    }

    def _is_placeholder(v: str) -> bool:
        vl = v.lower().strip().rstrip(".")
        return (vl in _PLACEHOLDERS
                or vl.startswith("not specified")
                or vl.startswith("not listed")
                or vl.startswith("not found")
                or vl.startswith("unknown")
                or vl.startswith("not available"))

    def _apply(raw):
        enriched = _extract_json(raw)
        if not isinstance(enriched, dict):
            return None
        result = dict(piece)
        for k, v in enriched.items():
            if v is None:
                continue
            sv = str(v).strip()
            if not sv or _is_placeholder(sv):
                continue
            existing = str(result.get(k) or "").strip()
            if existing and _is_placeholder(sv):
                continue
            result[k] = v
        return result

    # Tier 1: Free DuckDuckGo search → Haiku
    tier1_result = None
    composer_ = (piece.get("composer") or "").strip()
    choir_query = f'"{title}" {composer_} choral sheet music'.strip()
    snippets = ""
    try:
        try:
            from ddgs import DDGS
        except ImportError:
            from duckduckgo_search import DDGS
        with DDGS() as ddgs:
            results = list(ddgs.text(choir_query, max_results=5))
        snippets = "\n\n".join(
            f"[{r.get('href','')}]\n{r.get('body','').strip()}"
            for r in results if r.get("body", "").strip()
        )
    except Exception:
        pass

    if snippets:
        prompt = (
            f"Piece:\n{piece_context}\n\n"
            "Web search results (use as PRIMARY facts where they match this piece):\n"
            f"{snippets}\n\n"
            "Use the search results combined with your knowledge to fill in all fields. "
            "If the search results don't match this piece, rely on your training knowledge.\n\n"
            + _ENRICH_FIELDS_CHOIR
        )
        try:
            from llm_client import query_haiku
            result = _apply(query_haiku(base_dir, prompt,
                                        system_prompt=_ENRICH_SYSTEM_CHOIR, on_retry=on_retry))
            if result:
                conf = str(result.get("confidence") or "").strip().lower()
                if conf != "low":
                    return result
                tier1_result = result
        except Exception:
            pass

    # Tier 2: Haiku + Anthropic web search
    try:
        from llm_client import query_haiku_with_search
        prompt = (
            f"Piece:\n{piece_context}\n\n"
            "Search for this choral piece on halleonard.com, jwpepper.com, or sheetmusicplus.com. "
            "Use any data found as PRIMARY facts; fall back to training knowledge for missing fields.\n\n"
            + _ENRICH_FIELDS_CHOIR
        )
        result = _apply(query_haiku_with_search(base_dir, prompt,
                                                system_prompt=_ENRICH_SYSTEM_CHOIR, on_retry=on_retry))
        if result:
            return result
    except Exception:
        pass

    # Tier 3: Selected model, training knowledge only
    try:
        from llm_client import query
        prompt = (
            f"Piece:\n{piece_context}\n\n"
            "Using your training knowledge and best inference, fill in all fields. "
            "Do not leave fields empty unless you have no basis to infer a value.\n\n"
            + _ENRICH_FIELDS_CHOIR
        )
        result = _apply(query(base_dir, prompt,
                              system_prompt=_ENRICH_SYSTEM_CHOIR, on_retry=on_retry))
        if result:
            return result
    except Exception:
        pass

    if tier1_result:
        return tier1_result
    return piece


# ── Choir prefill normalisation ────────────────────────────────────────────────

def _dict_to_prefill_choir(d: dict, existing_titles: set[str] | None = None) -> dict:
    def _s(*keys):
        for k in keys:
            v = d.get(k)
            if v:
                return str(v).strip()
        return ""

    diff = _s("difficulty")
    m = re.search(r"(\d+(?:\.\d+)?)", diff)
    diff = m.group(1) if m else diff

    title = _clean_title(_s("title"))
    prefill = {
        "title":          title,
        "composer":       _s("composer"),
        "arranger":       _s("arranger"),
        "publisher":      _s("publisher"),
        "genre":          _s("genre"),
        "voicing":        _s("voicing"),
        "language":       _s("language"),
        "accompaniment":  _s("accompaniment"),
        "difficulty":     diff,
        "key_signature":  _s("key_signature"),
        "location":       "Chinook Middle School",
        "notes":          _s("comments", "visible_notes", "notes"),
        "_duplicate":     False,
        "_source_file":   d.get("_source_file", ""),
        "_confidence":    d.get("confidence", "").strip().lower(),
    }

    if existing_titles and title:
        prefill["_duplicate"] = _norm_title(title) in existing_titles

    return prefill


# ── Batch Import Dialog ────────────────────────────────────────────────────────

class BatchImportDialog(ttk.Toplevel):
    """
    Two-phase dialog:
      Phase 1 — analysis progress log while the background thread runs.
      Phase 2 — batch review table where the user checks/edits pieces before import.
    self.results is None if cancelled, or a list of prefill dicts for confirmed pieces.
    """

    _COLS = ("sel", "title", "composer", "arranger", "ensemble_type", "difficulty", "publisher", "conf", "source")
    _HDR  = {"sel": "", "title": "Title", "composer": "Composer",
             "arranger": "Arranger", "ensemble_type": "Ensemble",
             "difficulty": "Diff", "publisher": "Publisher",
             "conf": "Conf", "source": "Source File"}
    _WID  = {"sel": 28, "title": 200, "composer": 130, "arranger": 110,
             "ensemble_type": 100, "difficulty": 40, "publisher": 110,
             "conf": 36, "source": 140}

    _COLS_CHOIR = ("sel", "title", "composer", "arranger", "voicing", "difficulty", "publisher", "conf", "source")
    _HDR_CHOIR  = {"sel": "", "title": "Title", "composer": "Composer",
                   "arranger": "Arranger", "voicing": "Voicing",
                   "difficulty": "Diff", "publisher": "Publisher",
                   "conf": "Conf", "source": "Source File"}
    _WID_CHOIR  = {"sel": 28, "title": 200, "composer": 130, "arranger": 110,
                   "voicing": 100, "difficulty": 40, "publisher": 110,
                   "conf": 36, "source": 140}

    def __init__(self, parent, paths: list[str], base_dir: str,
                 existing_titles: set[str] | None = None, mode: str = "band"):
        super().__init__(parent)
        self.paths          = paths
        self.base_dir       = base_dir
        self._mode          = mode
        self.existing_titles = existing_titles or set()
        self.results        = None          # None=cancelled; list=confirmed pieces
        self._cancel_flag   = [False]
        self._in_review     = False
        self._partial_pieces: list[dict] = []  # grows as analysis runs
        self._prefills: list[dict] = []
        self._check_vars: list[tk.BooleanVar] = []
        self._selected_idx: int | None = None
        self._edit_vars: dict[str, tk.StringVar] = {}
        self._edit_notes: tk.Text | None = None
        self._enrich_var    = tk.BooleanVar(value=True)
        self._mousewheel_bound = False

        # Override column config for choir mode
        if mode == "choir":
            self._COLS = self._COLS_CHOIR
            self._HDR  = self._HDR_CHOIR
            self._WID  = self._WID_CHOIR

        self.title("Import Sheet Music")
        self.geometry("1140x600")
        self.resizable(True, True)
        self.grab_set()
        self.minsize(900, 480)

        self.update_idletasks()
        x = (self.winfo_screenwidth()  - 940) // 2
        y = (self.winfo_screenheight() - 580) // 2
        self.geometry(f"+{x}+{y}")

        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self._build_progress_phase()
        self.after(100, self._start_analysis)

    # ─────────────────────────────────────────── Phase 1: Progress ────────

    def _build_progress_phase(self):
        self._phase1 = ttk.Frame(self)
        self._phase1.pack(fill=BOTH, expand=True)

        hdr = ttk.Frame(self._phase1, bootstyle=INFO)
        hdr.pack(fill=X)
        ttk.Label(hdr, text="  🎼  Analyzing Sheet Music",
                  font=("Segoe UI", 12, "bold"),
                  bootstyle=(INVERSE, INFO)).pack(pady=10, padx=12, anchor=W)

        ttk.Label(self._phase1,
                  text=f"Processing {len(self.paths)} file(s) — this may take a few minutes…",
                  font=("Segoe UI", 9), foreground="#555").pack(anchor=W, padx=14, pady=(10, 2))

        opt = ttk.Frame(self._phase1)
        opt.pack(anchor=W, padx=14, pady=(0, 6))
        ttk.Checkbutton(opt,
                        text="Full enrichment (adds difficulty, key, genre from AI knowledge — slower)",
                        variable=self._enrich_var,
                        bootstyle=SECONDARY).pack(side=LEFT)

        log_frame = ttk.Frame(self._phase1)
        log_frame.pack(fill=BOTH, expand=True, padx=12, pady=(0, 8))

        sb = ttk.Scrollbar(log_frame, orient=VERTICAL)
        self._log = tk.Text(log_frame, wrap=WORD, state="disabled",
                            font=("Consolas", 8), relief="flat",
                            yscrollcommand=sb.set)
        sb.config(command=self._log.yview)
        sb.pack(side=RIGHT, fill=Y)
        self._log.pack(fill=BOTH, expand=True)

        self._status_lbl = ttk.Label(self._phase1, text="Starting…",
                                     font=("Segoe UI", 8), foreground="#555")
        self._status_lbl.pack(anchor=W, padx=14, pady=(0, 4))

        btn_frame = ttk.Frame(self._phase1)
        btn_frame.pack(fill=X, padx=12, pady=8)
        self._cancel_btn = ttk.Button(btn_frame, text="Cancel",
                                      bootstyle=(SECONDARY, OUTLINE),
                                      command=self._cancel)
        self._cancel_btn.pack(side=RIGHT)
        self._partial_btn = ttk.Button(btn_frame, text="Import What We Have",
                                       bootstyle=(WARNING, OUTLINE),
                                       command=self._import_partial)
        self._partial_btn.pack(side=RIGHT, padx=(0, 6))

    def _log_line(self, msg: str):
        try:
            self._log.config(state="normal")
            self._log.insert("end", msg + "\n")
            self._log.config(state="disabled")
            self._log.see("end")
            self._status_lbl.config(text=msg[:90])
        except Exception:
            pass  # dialog was closed while background thread was still running

    def _start_analysis(self):
        enrich = self._enrich_var.get()
        _prefill_fn = _dict_to_prefill_choir if self._mode == "choir" else _dict_to_prefill

        def _run():
            try:
                raw = analyze_music_files(
                    self.paths, self.base_dir,
                    lambda msg: self.after(0, self._log_line, msg),
                    self._cancel_flag,
                    enrich=enrich,
                    results_list=self._partial_pieces,
                    mode=self._mode,
                )
                prefills = [_prefill_fn(p, self.existing_titles) for p in raw]
                self.after(0, self._analysis_done, prefills)
            except Exception as e:
                self.after(0, self._analysis_error, str(e))

        threading.Thread(target=_run, daemon=True).start()

    def _import_partial(self):
        """Stop analysis and review whatever has been found so far."""
        self._cancel_flag[0] = True
        pieces = list(self._partial_pieces)
        if not pieces:
            self._log_line("No pieces found yet — nothing to import.")
            return
        _prefill_fn = _dict_to_prefill_choir if self._mode == "choir" else _dict_to_prefill
        prefills = [_prefill_fn(p, self.existing_titles) for p in pieces]
        self._log_line(f"\nStopped early — {len(prefills)} piece(s) ready to review.")
        self._prefills = prefills
        self._in_review = True
        self._phase1.pack_forget()
        self._build_review_phase()

    def _analysis_done(self, prefills: list[dict]):
        if self._in_review:
            return  # already transitioned via _import_partial
        if self._cancel_flag[0]:
            self.results = []
            self.destroy()
            return

        self._prefills = prefills

        if not prefills:
            self._log_line("\nNo pieces found in the selected files.")
            self._cancel_btn.config(text="Close")
            return

        self._log_line(f"\nDone — found {len(prefills)} piece(s). Preparing review…")
        self._in_review = True
        self._phase1.pack_forget()
        self._build_review_phase()

    def _analysis_error(self, msg: str):
        self._log_line(f"\nERROR: {msg}")
        self._status_lbl.config(text="Analysis failed.", foreground="#cc0000")
        self._cancel_btn.config(text="Close")

    # ─────────────────────────────────────────── Phase 2: Review ──────────

    def _build_review_phase(self):
        n      = len(self._prefills)
        n_dup  = sum(1 for p in self._prefills if p.get("_duplicate"))
        n_low  = sum(1 for p in self._prefills if p.get("_confidence") == "low")

        self._phase2 = ttk.Frame(self)
        self._phase2.pack(fill=BOTH, expand=True)

        # Header
        hdr = ttk.Frame(self._phase2, bootstyle=SUCCESS)
        hdr.pack(fill=X)
        notes = []
        if n_dup:
            notes.append(f"{n_dup} possible duplicate(s) flagged")
        if n_low:
            notes.append(f"{n_low} low-confidence row(s) — spot-check !")
        dup_note = " — " + "; ".join(notes) if notes else ""
        ttk.Label(hdr, text=f"  🎼  Review {n} piece(s){dup_note}",
                  font=("Segoe UI", 12, "bold"),
                  bootstyle=(INVERSE, SUCCESS)).pack(pady=10, padx=12, anchor=W)

        # Control bar
        ctrl = ttk.Frame(self._phase2)
        ctrl.pack(fill=X, padx=10, pady=(6, 2))
        ttk.Button(ctrl, text="Select All", bootstyle=(SECONDARY, OUTLINE),
                   command=lambda: self._set_all(True)).pack(side=LEFT, padx=2)
        ttk.Button(ctrl, text="Select None", bootstyle=(SECONDARY, OUTLINE),
                   command=lambda: self._set_all(False)).pack(side=LEFT, padx=2)
        if n_dup:
            ttk.Button(ctrl, text="Deselect Duplicates", bootstyle=(WARNING, OUTLINE),
                       command=self._deselect_dups).pack(side=LEFT, padx=6)
        self._sel_lbl = ttk.Label(ctrl, text="", font=("Segoe UI", 9))
        self._sel_lbl.pack(side=RIGHT, padx=6)

        # Bottom buttons — must be packed BEFORE the pane so pack reserves space for them
        btns = ttk.Frame(self._phase2)
        btns.pack(fill=X, padx=10, pady=8, side=BOTTOM)
        ttk.Button(btns, text="Cancel", bootstyle=(SECONDARY, OUTLINE),
                   command=self._cancel).pack(side=RIGHT, padx=4)
        self._import_btn = ttk.Button(btns, text="Import Selected",
                                      bootstyle=SUCCESS, command=self._do_import)
        self._import_btn.pack(side=RIGHT, padx=4)

        # Main pane: list left, edit panel right
        pane = ttk.Panedwindow(self._phase2, orient=HORIZONTAL)
        pane.pack(fill=BOTH, expand=True, padx=6, pady=(0, 4))

        left = ttk.Frame(pane)
        pane.add(left, weight=3)
        self._build_review_tree(left)

        right = ttk.Frame(pane, width=320)
        pane.add(right, weight=2)
        self._build_edit_panel(right)

        self._populate_review_tree()
        self._update_sel_count()

        # Update WM_DELETE_WINDOW to also unbind mousewheel
        self.protocol("WM_DELETE_WINDOW", self._cancel)

    def _build_review_tree(self, parent):
        sb  = ttk.Scrollbar(parent, orient=VERTICAL)
        xsb = ttk.Scrollbar(parent, orient=HORIZONTAL)
        self._rev_tree = ttk.Treeview(
            parent, columns=self._COLS, show="headings", selectmode="browse",
            bootstyle=SUCCESS, yscrollcommand=sb.set, xscrollcommand=xsb.set,
        )
        sb.config(command=self._rev_tree.yview)
        xsb.config(command=self._rev_tree.xview)
        sb.pack(side=RIGHT, fill=Y)
        xsb.pack(side=BOTTOM, fill=X)
        self._rev_tree.pack(fill=BOTH, expand=True)

        _STRETCH = {"title", "composer"}
        for col in self._COLS:
            self._rev_tree.heading(col, text=self._HDR[col], anchor=W)
            self._rev_tree.column(col, width=self._WID[col], anchor=W,
                                  minwidth=28, stretch=col in _STRETCH)

        self._rev_tree.tag_configure("dup",       foreground="#bb8800")
        self._rev_tree.tag_configure("conf_low",  foreground="#cc2222")
        self._rev_tree.tag_configure("conf_med",  foreground="#cc7700")
        self._rev_tree.bind("<<TreeviewSelect>>", self._on_tree_select)
        # Click the checkbox column to toggle
        self._rev_tree.bind("<Button-1>", self._on_tree_click)

    def _populate_review_tree(self):
        self._check_vars.clear()
        for i, p in enumerate(self._prefills):
            # Default: unchecked for duplicates, checked for everything else
            checked = not p.get("_duplicate", False)
            var = tk.BooleanVar(value=checked)
            self._check_vars.append(var)
            dup  = p.get("_duplicate", False)
            conf = p.get("_confidence", "")
            if dup:
                tags = ("dup",)
            elif conf == "low":
                tags = ("conf_low",)
            elif conf == "medium":
                tags = ("conf_med",)
            else:
                tags = ()
            self._rev_tree.insert("", "end", iid=str(i), tags=tags,
                                  values=self._row_values(i))

        children = self._rev_tree.get_children()
        if children:
            self._rev_tree.selection_set(children[0])
            self._rev_tree.focus(children[0])
            self._on_tree_select()

    def _row_values(self, idx: int) -> tuple:
        p   = self._prefills[idx]
        chk = "☑" if self._check_vars[idx].get() else "☐"
        dup = " ⚠" if p.get("_duplicate") else ""
        conf_sym = {"high": "✓", "medium": "~", "low": "!"}.get(
            p.get("_confidence", ""), "")
        col4 = p.get("voicing", "") if self._mode == "choir" else p.get("ensemble_type", "")
        return (chk, p.get("title", "") + dup, p.get("composer", ""),
                p.get("arranger", ""), col4,
                p.get("difficulty", ""), p.get("publisher", ""),
                conf_sym, p.get("_source_file", ""))

    def _build_edit_panel(self, parent):
        ttk.Label(parent, text="Edit Selected Piece",
                  font=("Segoe UI", 10, "bold")).pack(anchor=W, padx=8, pady=(8, 4))

        # Scrollable inner frame
        canv = tk.Canvas(parent, highlightthickness=0)
        sb   = ttk.Scrollbar(parent, orient=VERTICAL, command=canv.yview)
        canv.configure(yscrollcommand=sb.set)
        sb.pack(side=RIGHT, fill=Y)
        canv.pack(fill=BOTH, expand=True)

        inner = ttk.Frame(canv)
        win   = canv.create_window((0, 0), window=inner, anchor=NW)

        def _resize(e):
            canv.configure(scrollregion=canv.bbox("all"))
        def _width(e):
            canv.itemconfig(win, width=e.width)
        inner.bind("<Configure>", _resize)
        canv.bind("<Configure>", _width)

        def _wheel(e):
            try:
                canv.yview_scroll(int(-1 * (e.delta / 120)), "units")
            except tk.TclError:
                pass
        canv.bind_all("<MouseWheel>", _wheel)
        self._mousewheel_bound = True
        self._canv_ref = canv   # keep ref for unbinding

        if self._mode == "choir":
            FIELDS = [
                ("Title",        "title"),
                ("Composer",     "composer"),
                ("Arranger",     "arranger"),
                ("Publisher",    "publisher"),
                ("Voicing",      "voicing"),
                ("Language",     "language"),
                ("Difficulty",   "difficulty"),
                ("Genre",        "genre"),
                ("Key Sig",      "key_signature"),
                ("Location",     "location"),
            ]
        else:
            FIELDS = [
                ("Title",        "title"),
                ("Composer",     "composer"),
                ("Arranger",     "arranger"),
                ("Publisher",    "publisher"),
                ("Ensemble",     "ensemble_type"),
                ("Difficulty",   "difficulty"),
                ("Genre",        "genre"),
                ("Key Sig",      "key_signature"),
                ("Time Sig",     "time_signature"),
                ("Location",     "location"),
            ]
        for label, key in FIELDS:
            f = ttk.Frame(inner)
            f.pack(fill=X, padx=8, pady=1)
            ttk.Label(f, text=label + ":", font=("Segoe UI", 8, "bold"),
                      width=11, anchor=W).pack(side=LEFT)
            var = tk.StringVar()
            self._edit_vars[key] = var
            ttk.Entry(f, textvariable=var, font=("Segoe UI", 8)).pack(
                side=LEFT, fill=X, expand=True)
            var.trace_add("write", lambda *_, k=key: self._on_edit_change(k))

        ttk.Label(inner, text="Comments:", font=("Segoe UI", 8, "bold")).pack(
            anchor=W, padx=8, pady=(6, 0))
        self._edit_notes = tk.Text(inner, height=5, font=("Segoe UI", 8),
                                   relief="solid", bd=1, wrap=WORD)
        self._edit_notes.pack(fill=X, padx=8, pady=(2, 6))
        self._edit_notes.bind("<<Modified>>", self._on_notes_modified)

        ttk.Button(inner, text="Toggle ☑/☐ for Selected",
                   bootstyle=(SECONDARY, OUTLINE),
                   command=self._toggle_selected).pack(padx=8, pady=(4, 10), anchor=W)

    # ─────────────────────────────────────── Review interactions ──────────

    def _on_tree_click(self, event):
        """Toggle checkbox when the user clicks the ☑/☐ column."""
        region = self._rev_tree.identify_region(event.x, event.y)
        col    = self._rev_tree.identify_column(event.x)
        if region == "cell" and col == "#1":
            item = self._rev_tree.identify_row(event.y)
            if item:
                idx = int(item)
                self._check_vars[idx].set(not self._check_vars[idx].get())
                self._rev_tree.item(item, values=self._row_values(idx))
                self._update_sel_count()

    def _on_tree_select(self, event=None):
        sel = self._rev_tree.selection()
        if not sel:
            return
        self._flush_edit()
        idx = int(sel[0])
        self._selected_idx = idx
        p = self._prefills[idx]
        for key, var in self._edit_vars.items():
            var.set(p.get(key, "") or "")
        if self._edit_notes:
            self._edit_notes.delete("1.0", "end")
            self._edit_notes.insert("1.0", p.get("notes", "") or "")
            self._edit_notes.edit_modified(False)

    def _on_edit_change(self, key: str):
        if self._selected_idx is None:
            return
        self._prefills[self._selected_idx][key] = self._edit_vars[key].get()
        self._rev_tree.item(str(self._selected_idx),
                            values=self._row_values(self._selected_idx))

    def _on_notes_modified(self, event=None):
        if self._edit_notes and self._edit_notes.edit_modified():
            if self._selected_idx is not None:
                self._prefills[self._selected_idx]["notes"] = (
                    self._edit_notes.get("1.0", "end").strip()
                )
            self._edit_notes.edit_modified(False)

    def _flush_edit(self):
        """Write current edit fields back to prefills before switching rows."""
        if self._selected_idx is None:
            return
        p = self._prefills[self._selected_idx]
        for key, var in self._edit_vars.items():
            p[key] = var.get()
        if self._edit_notes:
            p["notes"] = self._edit_notes.get("1.0", "end").strip()

    def _toggle_selected(self):
        if self._selected_idx is None:
            return
        var = self._check_vars[self._selected_idx]
        var.set(not var.get())
        self._rev_tree.item(str(self._selected_idx),
                            values=self._row_values(self._selected_idx))
        self._update_sel_count()

    def _set_all(self, value: bool):
        for i, var in enumerate(self._check_vars):
            var.set(value)
            self._rev_tree.item(str(i), values=self._row_values(i))
        self._update_sel_count()

    def _deselect_dups(self):
        for i, p in enumerate(self._prefills):
            if p.get("_duplicate"):
                self._check_vars[i].set(False)
                self._rev_tree.item(str(i), values=self._row_values(i))
        self._update_sel_count()

    def _update_sel_count(self):
        n_sel   = sum(1 for v in self._check_vars if v.get())
        n_total = len(self._check_vars)
        if hasattr(self, "_sel_lbl"):
            self._sel_lbl.config(text=f"{n_sel} of {n_total} selected")
        if hasattr(self, "_import_btn"):
            self._import_btn.config(
                text=f"Import Selected ({n_sel})",
                state=NORMAL if n_sel > 0 else DISABLED,
            )

    # ─────────────────────────────────────────── Final actions ────────────

    def _do_import(self):
        self._flush_edit()
        selected = [p for p, var in zip(self._prefills, self._check_vars) if var.get()]
        for p in selected:
            p.pop("_duplicate", None)
            p["source_file"] = p.pop("_source_file", "") or ""
            p.pop("_confidence", None)
        self.results = selected
        self._cleanup()
        self.destroy()

    def _cancel(self):
        self._cancel_flag[0] = True
        self.results = None
        self._cleanup()
        self.destroy()

    def _cleanup(self):
        if self._mousewheel_bound:
            try:
                self._canv_ref.unbind_all("<MouseWheel>")
            except Exception:
                pass
            self._mousewheel_bound = False
