"""
batch_enrich.py - Batch enrich sheet music Comments for Meagan R. Mangum's profile.

Runs the same enrichment as: Edit → Enrich with LLM → Yes → Save in the UI.

Only updates: genre, ensemble_type, difficulty, key_signature, time_signature, notes.
Never touches: title, composer, arranger, publisher, location, file_path, source_file.

Usage:
    cd <project_dir>
    python batch_enrich.py
"""

import os
import sys
import time
import sqlite3
from datetime import datetime

# ── Paths ─────────────────────────────────────────────────────────────────────

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_DIR)

PROFILE_DIR = r"C:\Users\natem\AppData\Local\RokasResonance\profiles\Meagan R. Mangum"
DB_PATH     = os.path.join(PROFILE_DIR, "rokas_resonance.db")
LOG_PATH    = os.path.join(PROJECT_DIR, "batch_enrich_log.txt")

# ── DB helpers ────────────────────────────────────────────────────────────────

def _conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def get_unenriched(remaining_only: bool = False) -> list[dict]:
    """Return active pieces to enrich.
    remaining_only=True: only pieces without bullet-formatted notes
    (i.e. not yet processed by the current pipeline).
    """
    where = "is_active=1"
    if remaining_only:
        where += " AND (notes NOT LIKE '%•%' OR notes IS NULL OR notes='')"
    with _conn() as conn:
        rows = conn.execute(
            "SELECT id, title, composer, arranger, publisher, "
            "genre, ensemble_type, difficulty, key_signature, time_signature, notes "
            f"FROM sheet_music WHERE {where} ORDER BY title"
        ).fetchall()
    return [dict(r) for r in rows]


def apply_enrichment(music_id: int, updates: dict):
    """Targeted UPDATE — only the six enrichment fields."""
    with _conn() as conn:
        conn.execute(
            "UPDATE sheet_music "
            "SET genre=?, ensemble_type=?, difficulty=?, "
            "    key_signature=?, time_signature=?, notes=? "
            "WHERE id=?",
            (
                updates["genre"],
                updates["ensemble_type"],
                updates["difficulty"],
                updates["key_signature"],
                updates["time_signature"],
                updates["notes"],
                music_id,
            ),
        )

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    from ui.music_importer import _enrich_piece   # lazy import after sys.path is set

    remaining_only = "--remaining" in sys.argv
    pieces = get_unenriched(remaining_only=remaining_only)
    total  = len(pieces)

    print(f"Roka's Resonance — Batch Enrichment")
    print(f"Profile : {PROFILE_DIR}")
    print(f"Database: {DB_PATH}")
    print(f"Pieces to enrich: {total}")
    print(f"Log: {LOG_PATH}")
    print()

    log = [
        f"Batch enrichment started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"Profile: {PROFILE_DIR}",
        f"Total pieces: {total}",
        "",
    ]

    succeeded = failed = skipped = 0

    for i, piece in enumerate(pieces, 1):
        music_id = piece["id"]
        title    = piece["title"] or ""

        print(f"[{i:3d}/{total}] {title[:65]}", end="", flush=True)

        input_piece = {
            "title":     title,
            "composer":  piece["composer"]  or "",
            "arranger":  piece["arranger"]  or "",
            "publisher": piece["publisher"] or "",
        }

        # ── Call LLM (already retries internally) ──────────────────────────
        try:
            enriched = _enrich_piece(input_piece, PROFILE_DIR)
        except Exception as exc:
            msg = str(exc)
            print(f"\n    ERR: {msg}")
            log.append(f"[{i:3d}] FAIL  [{music_id:4d}] {title[:60]} — {msg}")
            failed += 1
            print(f"    Waiting 30 s before next piece...")
            time.sleep(30)
            continue

        # ── Extract enriched values (same logic as _on_enrich_done) ────────
        def _s(key):
            return str(enriched.get(key) or "").strip()

        genre       = _s("genre")         or piece["genre"]          or ""
        ensemble    = _s("ensemble_type") or piece["ensemble_type"]  or ""
        difficulty  = _s("difficulty")    or piece["difficulty"]     or ""
        key_sig     = _s("key_signature") or piece["key_signature"]  or ""
        time_sig    = _s("time_signature")or piece["time_signature"] or ""
        confidence  = _s("confidence")

        # notes: prefer "comments" key, fall back to "notes", then keep existing
        notes_raw = str(enriched.get("comments") or enriched.get("notes") or "").strip()
        if notes_raw:
            notes = notes_raw.replace(" • ", "\n• ")
        else:
            notes = piece["notes"] or ""

        # Skip only if nothing at all came back
        nothing_new = (
            not notes_raw
            and not _s("genre")
            and not _s("ensemble_type")
            and not _s("difficulty")
            and not _s("key_signature")
            and not _s("time_signature")
        )
        if nothing_new:
            print(f"  — no data returned")
            log.append(f"[{i:3d}] SKIP  [{music_id:4d}] {title[:60]} — LLM returned nothing")
            skipped += 1
            continue

        # ── Write to DB ────────────────────────────────────────────────────
        apply_enrichment(music_id, {
            "genre":          genre,
            "ensemble_type":  ensemble,
            "difficulty":     difficulty,
            "key_signature":  key_sig,
            "time_signature": time_sig,
            "notes":          notes,
        })

        conf_tag = f"[{confidence}]" if confidence else ""
        print(f"  OK {conf_tag}")
        log.append(f"[{i:3d}] OK    [{music_id:4d}] {title[:60]}  conf={confidence}")
        succeeded += 1

    # ── Summary ───────────────────────────────────────────────────────────────
    summary = (
        f"\nDone: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"Succeeded: {succeeded}  |  Failed: {failed}  |  Skipped: {skipped}"
    )
    print(summary)
    log += ["", summary.strip()]

    with open(LOG_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(log))
    print(f"Log written to: {LOG_PATH}")


if __name__ == "__main__":
    main()
