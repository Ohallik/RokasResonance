"""
test_enrich.py - Test three-tier enrichment on sample pieces.
Reports which tier was used, enriched fields, and estimated token cost.
"""
import os, sys, time, json, sqlite3
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Force UTF-8 output so music symbols (♭ ♯) don't crash on Windows cp1252 consoles
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

PROFILE_DIR = r"C:\Users\natem\AppData\Local\RokasResonance\profiles\Meagan R. Mangum"
DB_PATH = os.path.join(PROFILE_DIR, "rokas_resonance.db")

# Haiku pricing (March 2026)
HAIKU_IN  = 0.80 / 1_000_000   # $0.80 per million input tokens
HAIKU_OUT = 4.00 / 1_000_000   # $4.00 per million output tokens
SEARCH_FEE = 0.01               # $10 per 1000 searches = $0.01 each

_calls = []   # records each LLM call made during enrichment

# ── Patch llm_client before importing music_importer ─────────────────────────

import llm_client as lc

_orig_haiku    = lc.query_haiku
_orig_haiku_ws = lc.query_haiku_with_search
_orig_query    = lc.query

def _tok(s):
    """Rough token count: ~4 chars per token."""
    return max(1, len(str(s)) // 4)

def _wrap_haiku(base_dir, prompt, system_prompt=None, on_retry=None):
    t0 = time.time()
    result = _orig_haiku(base_dir, prompt, system_prompt=system_prompt, on_retry=on_retry)
    in_tok  = _tok((system_prompt or "") + prompt)
    out_tok = _tok(result)
    _calls.append({
        "tier": 1, "label": "DDG -> Haiku (text-only)",
        "in": in_tok, "out": out_tok,
        "cost": in_tok * HAIKU_IN + out_tok * HAIKU_OUT,
        "sec": round(time.time() - t0, 1),
    })
    return result

def _wrap_haiku_ws(base_dir, prompt, system_prompt=None, on_retry=None):
    t0 = time.time()
    result = _orig_haiku_ws(base_dir, prompt, system_prompt=system_prompt, on_retry=on_retry)
    in_tok  = _tok((system_prompt or "") + prompt)
    out_tok = _tok(result)
    _calls.append({
        "tier": 2, "label": "Haiku + Anthropic web search (1 use)",
        "in": in_tok, "out": out_tok,
        "cost": in_tok * HAIKU_IN + out_tok * HAIKU_OUT + SEARCH_FEE,
        "sec": round(time.time() - t0, 1),
    })
    return result

def _wrap_query(base_dir, prompt, system_prompt=None, on_retry=None):
    t0 = time.time()
    result = _orig_query(base_dir, prompt, system_prompt=system_prompt, on_retry=on_retry)
    in_tok  = _tok((system_prompt or "") + prompt)
    out_tok = _tok(result)
    _calls.append({
        "tier": 3, "label": "Selected model, training knowledge only",
        "in": in_tok, "out": out_tok,
        "cost": None,   # depends on which model user has selected
        "sec": round(time.time() - t0, 1),
    })
    return result

# Patch before importing music_importer (which imports lazily)
lc.query_haiku             = _wrap_haiku
lc.query_haiku_with_search = _wrap_haiku_ws
lc.query                   = _wrap_query

from ui.music_importer import _enrich_piece, _ddg_search

# ── DB helpers ────────────────────────────────────────────────────────────────

def get_pieces():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, title, composer, arranger, publisher, "
        "genre, ensemble_type, difficulty, key_signature, time_signature, notes "
        "FROM sheet_music WHERE id IN (146, 372, 293, 459, 190, 212, 140, 434) ORDER BY title"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    pieces = get_pieces()
    print(f"Three-tier enrichment test — {len(pieces)} pieces\n")

    total_cost = 0.0
    tier_counts = {1: 0, 2: 0, 3: 0}

    for piece in pieces:
        _calls.clear()
        title    = piece["title"] or "(no title)"
        composer = piece["composer"] or ""

        print("=" * 70)
        print(f"  {title}")
        if composer:
            print(f"  Composer: {composer}")

        # Show what DDG finds before calling LLM
        print("\n  [DDG search preview]")
        snippets = _ddg_search(piece)
        if snippets:
            preview = snippets[:300].replace("\n", " ")
            print(f"  {preview}...")
        else:
            print("  (no results)")

        t0 = time.time()
        enriched = _enrich_piece(piece, PROFILE_DIR)
        elapsed  = round(time.time() - t0, 1)

        # ── Which tier succeeded? ────────────────────────────────────────────
        if _calls:
            c = _calls[-1]
            tier_counts[c["tier"]] = tier_counts.get(c["tier"], 0) + 1
            print(f"\n  Tier {c['tier']}: {c['label']}  ({c['sec']}s)")
            print(f"  Tokens : ~{c['in']:,} in / ~{c['out']:,} out")
            if c["cost"] is not None:
                print(f"  Cost   : ${c['cost']:.4f}")
                total_cost += c["cost"]
            else:
                print(f"  Cost   : (depends on selected model)")
        else:
            print("\n  (no LLM call made)")

        # ── Enriched fields ──────────────────────────────────────────────────
        print("\n  Enriched fields:")
        FIELDS = [
            ("genre",          "Genre"),
            ("ensemble_type",  "Ensemble"),
            ("difficulty",     "Difficulty"),
            ("key_signature",  "Key"),
            ("time_signature", "Time"),
            ("publisher",      "Publisher"),
            ("composer",       "Composer"),
            ("arranger",       "Arranger"),
        ]
        for key, label in FIELDS:
            old = str(piece.get(key) or "").strip()
            new = str(enriched.get(key) or "").strip()
            tag = ""
            if new and not old:
                tag = " [+NEW]"
            elif new and old and new != old:
                tag = f" [was: {old}]"
            elif not new:
                tag = " [empty]"
            print(f"    {label:12s}: {new or '—'}{tag}")

        confidence = (enriched.get("confidence") or "").strip()
        if confidence:
            print(f"    {'Confidence':12s}: {confidence}")

        notes = (enriched.get("comments") or enriched.get("notes") or "").strip()
        if notes:
            # Show first 300 chars
            preview = notes[:300] + ("..." if len(notes) > 300 else "")
            print(f"\n  Notes preview:\n    {preview.replace(chr(10), chr(10) + '    ')}")

        print(f"\n  Total elapsed: {elapsed}s")

    # ── Summary ───────────────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("SUMMARY")
    print(f"  Pieces tested : {len(pieces)}")
    for t in (1, 2, 3):
        if tier_counts.get(t):
            labels = {1: "Tier 1 (DDG->Haiku)",
                      2: "Tier 2 (Haiku+Search)",
                      3: "Tier 3 (selected model)"}
            print(f"  {labels[t]:30s}: {tier_counts[t]} piece(s)")
    print(f"\n  Estimated cost for these {len(pieces)} pieces: ${total_cost:.4f}")
    n_total = 315  # full catalog
    est_total = (total_cost / len(pieces)) * n_total if pieces else 0
    print(f"  Projected cost for all {n_total} pieces:   ${est_total:.2f}")
    print()


if __name__ == "__main__":
    main()
