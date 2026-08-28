"""
usage_log.py - Record what every AI call actually used, so "what does this
cost?" is a button in Settings instead of a guess.

Every Anthropic and GitHub Models response carries exact token counts; this
module writes them (with an estimated dollar cost) into an ``api_usage``
table in the profile's main database -- the main DB on purpose, so the
history rides along with backups and survives year rollovers.  The teacher
reads it back by school year in Settings -> LLM Configuration ->
Token Cost History.

Recording must never break a query: every entry point swallows its own
errors.  A lost log row is a shrug; a lost enrichment is a bug report.
"""

import os
import sqlite3
from datetime import datetime

# $ per MILLION tokens by model family: (input, output, cache write, cache
# read).  These are Anthropic's published rates when this was written -- the
# stored cost is an ESTIMATE stamped at time of use, and the exact bill lives
# in the Anthropic Console.  Raw token counts are stored too, so a rate
# change never corrupts history.  GitHub Models calls match no family and
# cost $0 (free tier).
_RATES = [
    ("claude-haiku",  (1.0, 5.0, 1.25, 0.10)),
    ("claude-sonnet", (3.0, 15.0, 3.75, 0.30)),
    ("claude-opus",   (5.0, 25.0, 6.25, 0.50)),
]
_SEARCH_COST = 0.01          # $10 per 1,000 web searches

_TABLE = """
CREATE TABLE IF NOT EXISTS api_usage (
    id INTEGER PRIMARY KEY,
    ts TEXT NOT NULL,
    school_year TEXT NOT NULL,
    model TEXT NOT NULL,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    cache_write_tokens INTEGER NOT NULL DEFAULT 0,
    cache_read_tokens INTEGER NOT NULL DEFAULT 0,
    searches INTEGER NOT NULL DEFAULT 0,
    est_cost REAL NOT NULL DEFAULT 0
)
"""


def _school_year() -> str:
    today = datetime.today()
    if today.month >= 8:
        return f"{today.year}-{today.year + 1}"
    return f"{today.year - 1}-{today.year}"


def _rates_for(model: str):
    for prefix, rates in _RATES:
        if (model or "").startswith(prefix):
            return rates
    return (0.0, 0.0, 0.0, 0.0)


def estimate_cost(model, input_tokens, output_tokens,
                  cache_write=0, cache_read=0, searches=0) -> float:
    r_in, r_out, r_cw, r_cr = _rates_for(model)
    return (input_tokens * r_in + output_tokens * r_out
            + cache_write * r_cw + cache_read * r_cr) / 1_000_000 \
        + searches * _SEARCH_COST


def _grab(usage, *names) -> int:
    """A token count off an SDK usage object or a plain dict, else 0."""
    for n in names:
        v = None
        if isinstance(usage, dict):
            v = usage.get(n)
        else:
            v = getattr(usage, n, None)
        if v:
            try:
                return int(v)
            except (TypeError, ValueError):
                pass
    return 0


def record(base_dir, model, usage, searches=0):
    """Write one call's usage.  Silent on ANY failure -- see module note."""
    try:
        if usage is None:
            return
        inp = _grab(usage, "input_tokens", "prompt_tokens")
        out = _grab(usage, "output_tokens", "completion_tokens")
        cw = _grab(usage, "cache_creation_input_tokens")
        cr = _grab(usage, "cache_read_input_tokens")
        if not (inp or out or cw or cr):
            return
        cost = estimate_cost(model, inp, out, cw, cr, searches)
        path = os.path.join(base_dir or "", "rokas_resonance.db")
        if not os.path.exists(path):
            return
        conn = sqlite3.connect(path, timeout=5)
        try:
            conn.execute(_TABLE)
            conn.execute(
                "INSERT INTO api_usage (ts, school_year, model, input_tokens,"
                " output_tokens, cache_write_tokens, cache_read_tokens,"
                " searches, est_cost) VALUES (?,?,?,?,?,?,?,?,?)",
                (datetime.now().isoformat(timespec="seconds"), _school_year(),
                 model or "", inp, out, cw, cr, int(searches or 0), cost))
            conn.commit()
        finally:
            conn.close()
    except Exception:
        pass


def record_response(base_dir, model, response):
    """Convenience: record straight off an SDK response object."""
    try:
        usage = getattr(response, "usage", None)
        searches = 0
        stu = getattr(usage, "server_tool_use", None)
        if stu is not None:
            searches = _grab(stu, "web_search_requests")
        record(base_dir, model, usage, searches)
    except Exception:
        pass


def summary(base_dir):
    """[(school_year, calls, tokens_in, tokens_out, est_cost), ...] oldest
    first, tokens_in counting every input kind (plain, cache write, cache
    read) so the number matches what the teacher means by "tokens in"."""
    path = os.path.join(base_dir or "", "rokas_resonance.db")
    if not os.path.exists(path):
        return []
    try:
        conn = sqlite3.connect(path, timeout=5)
        try:
            conn.execute(_TABLE)
            rows = conn.execute(
                "SELECT school_year, COUNT(*),"
                " SUM(input_tokens + cache_write_tokens + cache_read_tokens),"
                " SUM(output_tokens), SUM(est_cost)"
                " FROM api_usage GROUP BY school_year"
                " ORDER BY school_year").fetchall()
            return [(r[0], r[1], r[2] or 0, r[3] or 0, r[4] or 0.0)
                    for r in rows]
        finally:
            conn.close()
    except Exception:
        return []
