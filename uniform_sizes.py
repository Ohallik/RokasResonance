"""
uniform_sizes.py — best-effort size ordering for garments, so the app can
suggest an available piece "one or two sizes bigger" than what a returning
student had last year.

Uniform sizing is messy and inconsistent across garment types:
    Jackets:   '26XS', '28-L C', '30-XL C', '30 XL C'   (chest number + length)
    Pants:     '20 R (38)'                               (size + inseam + waist)
    Shakos:    'Small', 'Large', 'X-Large'
    Rain gear: 'S', 'M', 'L', 'XL'

We reduce any size string to a sortable rank = (numeric, alpha) so bigger sizes
sort after smaller ones.  This is a heuristic and is always presented as a
*suggestion* — the director makes the final call.
"""

import re

# Alphabetic size word / abbreviation -> ordinal.  Matched against whole tokens
# (after digits are stripped), so a lone 'L' never matches inside 'small'.
_ALPHA = {
    "xxxl": 7, "3xl": 7, "xxxlarge": 7,
    "xxl": 6, "2xl": 6, "xxlarge": 6,
    "xlarge": 5, "xl": 5,
    "large": 4, "lg": 4, "l": 4,
    "medium": 3, "med": 3, "m": 3,
    "small": 1, "sm": 1, "s": 1,
    "xsmall": 0, "xs": 0,
}


def _alpha_rank(text: str):
    """Return the ordinal of the size word in *text*, else None.  'X-Large' and
    'X Large' collapse to 'xlarge'; glued forms like '26XS' / '30XL' have their
    leading digits stripped so the letter cluster is matched exactly."""
    t = (text or "").lower()
    # collapse 'x large' / 'x-large' / 'x small' into single tokens
    t = re.sub(r"\bx[\s\-]+(large|small)", r"x\1", t)
    t = re.sub(r"[^a-z0-9]+", " ", t)
    best = None
    for tok in t.split():
        core = tok.lstrip("0123456789")  # '26xs' -> 'xs', '30xl' -> 'xl'
        if core in _ALPHA:
            v = _ALPHA[core]
            if best is None or v > best:
                best = v
    return best


def size_rank(size: str):
    """Sortable rank for a size string: (numeric_part, alpha_part).
    Missing parts default so that any recognizable size still orders sensibly."""
    s = str(size or "").strip()
    # Leading / primary number (chest size, numeric shako, etc.)
    m = re.search(r"\d+", s)
    num = int(m.group()) if m else -1
    alpha = _alpha_rank(s)
    return (num, alpha if alpha is not None else -1)


def is_larger(candidate_size: str, base_size: str) -> bool:
    """True if candidate_size ranks strictly larger than base_size."""
    return size_rank(candidate_size) > size_rank(base_size)


def suggest_larger(available, base_size: str, limit: int = 2):
    """Given *available* (a list of dict-like uniform rows, each with 'size' and
    'item_number'), return up to *limit* pieces that are one/two steps larger
    than *base_size*, smallest-first.  Falls back to the smallest available if
    nothing is strictly larger (so the director always gets a suggestion)."""
    base = size_rank(base_size)

    def _row_size(r):
        try:
            return r["size"]
        except (KeyError, TypeError):
            return r.get("size") if hasattr(r, "get") else ""

    ranked = sorted(available, key=lambda r: size_rank(_row_size(r)))
    larger = [r for r in ranked if size_rank(_row_size(r)) > base]
    if larger:
        return larger[:limit]
    # nothing bigger available — offer the closest (same size or, failing that,
    # the largest we do have) so the suggestion box is never empty
    same = [r for r in ranked if size_rank(_row_size(r)) == base]
    if same:
        return same[:limit]
    return ranked[-limit:] if ranked else []
