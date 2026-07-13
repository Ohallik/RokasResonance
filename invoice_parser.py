"""
invoice_parser.py - Parse repair invoices (PDF) and match to instrument records.
"""

import os
import re
from datetime import datetime


# Repair shops BSD programs actually use.  Detected anywhere in the invoice
# text (so "BandWright Repair, LLC" in the letterhead → "BandWright"); the
# same list feeds the Repair Shop dropdown in the repair dialog.
KNOWN_SHOPS = ["BandWright", "Kennelly Keys", "Precision Woodwind", "Music & Arts"]


def extract_pdf_text(pdf_path: str) -> str:
    """
    Extract all text from a PDF file using pypdf.

    Uses layout-aware extraction (pypdf >= 3.17) so that table columns on
    the same row stay on the same text line — critical for reading amounts
    next to serial numbers.  Falls back to plain extraction if unavailable.
    """
    try:
        import pypdf
    except ImportError:
        raise ImportError(
            "pypdf is required for invoice parsing.\n"
            "Install it with:  pip install pypdf"
        )
    reader = pypdf.PdfReader(pdf_path)
    pages = []
    for page in reader.pages:
        try:
            text = page.extract_text(extraction_mode="layout") or ""
        except Exception:
            text = page.extract_text() or ""
        pages.append(text)
    return "\n".join(pages)


# ── Field parsers ─────────────────────────────────────────────────────────────

def _parse_date(text: str) -> str:
    """Return first date found as YYYY-MM-DD, or today's date."""
    m = re.search(r'\b(\d{4})[/\-](\d{1,2})[/\-](\d{1,2})\b', text)
    if m:
        y, mo, d = m.groups()
        return f"{y}-{int(mo):02d}-{int(d):02d}"
    m = re.search(r'\b(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})\b', text)
    if m:
        mo, d, y = m.groups()
        return f"{y}-{int(mo):02d}-{int(d):02d}"
    m = re.search(r'\b(\d{1,2})[/\-](\d{1,2})[/\-](\d{2})\b', text)
    if m:
        mo, d, y = m.groups()
        return f"20{y}-{int(mo):02d}-{int(d):02d}"
    return datetime.today().strftime("%Y-%m-%d")


def _parse_tax_rate(text: str) -> float:
    """
    Extract sales tax rate as a decimal fraction (e.g. 0.103 for 10.3%).
    Returns 0.0 if not found.
    """
    patterns = [
        r'[Ss]ales\s+[Tt]ax\s*\(\s*(\d+\.?\d*)\s*%\s*\)',  # Sales Tax (10.3%)
        r'[Tt]ax\s+[Rr]ate\s*[:\s]+(\d+\.?\d*)\s*%',
        r'(\d+\.?\d*)\s*%\s+[Ss]ales\s+[Tt]ax',
        r'[Tt]ax\s+(\d+\.?\d*)\s*%',
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            try:
                rate = float(m.group(1))
                if 0 < rate < 100:
                    return rate / 100.0
            except ValueError:
                pass
    return 0.0


def _parse_line_amount(text: str, match_pos: int, match_val_len: int) -> float:
    """
    Find the line-item dollar amount for the instrument at match_pos.

    Two strategies, tried in order:

    1. Character-window: examine the 300 chars immediately after the serial
       number.  This works when the PDF preserves row layout (with layout mode
       or row-major content streams).  We prefer amounts followed by 'T' (the
       BandWright taxable marker) because they are unambiguous line-item values.

    2. Line-scan: split on newlines, scan ±5 lines around the match line.
       Catches cases where the amount wraps to the next line.
    """
    after_start = match_pos + match_val_len
    after_text  = text[after_start : after_start + 300]

    # ── Strategy 1: character window after the serial number ──────────────────
    # Prefer explicit taxable-marker amounts (e.g. "65.00T")
    taxable = re.findall(r'(\d+\.\d{2})T', after_text)
    if taxable:
        try:
            return float(taxable[-1])
        except ValueError:
            pass

    # Plain decimals right after the serial (the first reasonable one encountered)
    plain_after = re.findall(r'\b(\d{1,4}\.\d{2})\b', after_text)
    valid = [float(p) for p in plain_after if 1.0 <= float(p) <= 9999.0]
    if valid:
        return valid[-1]   # last = Amount column (Rate ≤ Amount when Qty=1)

    # ── Strategy 2: line-scan ±5 lines ───────────────────────────────────────
    lines = text.split('\n')
    cumulative = 0
    match_line_idx = 0
    for i, line in enumerate(lines):
        cumulative += len(line) + 1
        if cumulative > match_pos:
            match_line_idx = i
            break

    for offset in range(-2, 6):
        li = match_line_idx + offset
        if li < 0 or li >= len(lines):
            continue
        line = lines[li]

        # Strong signal: BandWright-style taxable marker
        taxable_line = re.findall(r'(\d+\.\d{2})T', line)
        if taxable_line:
            try:
                return float(taxable_line[-1])
            except ValueError:
                pass

        # Plain decimals only on the exact match line (avoid false positives elsewhere)
        if offset == 0:
            plain = re.findall(r'\b(\d+\.\d{2})\b', line)
            valid2 = [float(p) for p in plain if 1.0 <= float(p) <= 9999.0]
            if valid2:
                return valid2[-1]

    return 0.0


def _parse_cost_from_context(context: str) -> float:
    """
    Extract the most likely individual repair cost from context text.
    Uses explicit $X.XX notation.  Avoids totals by taking the smallest
    reasonable amount found (individual repairs are cheaper than the total).
    """
    raw = re.findall(r'\$\s*([\d,]+\.\d{2})', context)
    amounts = sorted(
        float(a.replace(',', '')) for a in raw
        if 1.0 <= float(a.replace(',', '')) <= 9999.0
    )
    return amounts[0] if amounts else 0.0


def _parse_invoice_number(text: str, source_name: str = "") -> str:
    """Extract the invoice / work-order number.

    The number usually sits next to an 'Invoice #' header at the top of page 1,
    but text extraction can shuffle the header cells (which is how a naive
    pattern once captured the word 'Date').  So: only accept values that
    contain a digit, then fall back to the filename — shops like BandWright
    put it right in the file name (Invoice_2139_BandWrightRepair.pdf)."""
    def _plausible(val):
        val = (val or "").strip()
        return (bool(val) and any(ch.isdigit() for ch in val)
                and not re.fullmatch(r'\d{1,2}', val) and '/' not in val)

    # "Invoice #" followed (possibly on the next line) by the number itself
    m = re.search(r'Invoice\s*#\s*[:\-]?\s*([A-Za-z0-9][A-Za-z0-9\-]{2,19})',
                  text, re.IGNORECASE)
    if m and _plausible(m.group(1)):
        return m.group(1).strip()
    # QuickBooks-style header block: "Date  Invoice #" / "10/1/2025  2139"
    m = re.search(r'Invoice\s*#.{0,80}?\b\d{1,2}/\d{1,2}/\d{2,4}\s+(\d{3,12})\b',
                  text, re.IGNORECASE | re.DOTALL)
    if m:
        return m.group(1)
    # Filename
    m = re.search(r'(?:invoice|inv)[\s_#\-]*(\d{3,12})', source_name, re.IGNORECASE)
    if m:
        return m.group(1)
    # Work-order style
    for pat in (r'(?:work\s*order|wo)[\s#:\-]*([A-Z0-9\-]{3,20})',
                r'(?:order\s*(?:no|#|number))[\s:.\-]*([A-Z0-9\-]{3,20})'):
        m = re.search(pat, text, re.IGNORECASE)
        if m and _plausible(m.group(1)):
            return m.group(1).strip()
    return ""


def _parse_invoice_total(text: str) -> float:
    """The invoice's grand total (bottom of the page).  Prefer 'Balance Due',
    then 'Total' ('Subtotal' can't match — \\b requires a word boundary).
    Multi-page invoices repeat the footer with blanks on early pages, so take
    the last non-zero value."""
    for pat in (r'Balance\s+Due\s*:?\s*\$?\s*([\d,]+\.\d{2})',
                r'\bTotal\b\s*:?\s*\$?\s*([\d,]+\.\d{2})'):
        try:
            vals = [float(v.replace(',', ''))
                    for v in re.findall(pat, text, re.IGNORECASE)]
        except ValueError:
            continue
        vals = [v for v in vals if v > 0]
        if vals:
            return vals[-1]
    return 0.0


def _parse_repair_description(text: str, match_pos: int) -> str:
    """
    Extract the repair description that follows a matched instrument line item.

    BandWright invoices (and similar) have this pattern:

        Repair (Brass)    Trombone, Bundy, SN:364819            65.00   65.00T
                          ↵
                          Resolder waterkey. Severe bell dents. Minor case
                          repair (3DP handslide retention tabs).
                          ↵
        Repair (Brass)    Trombone, Olds, SN:502994   ...

    The description sits on indented lines between the matched line item and
    the next line item (or a section boundary like Subtotal).
    """
    lines = text.split('\n')
    match_line_idx = _line_index_of(lines, match_pos)

    desc_parts = []
    for i in range(match_line_idx + 1, min(match_line_idx + 12, len(lines))):
        line = lines[i]
        stripped = line.strip()

        # Stop at section boundaries
        if _BOUNDARY_RE.search(stripped):
            break

        # Stop at a new line item
        if _ITEM_RE.match(line) and stripped:
            break

        # Skip blank lines (but don't break — description may follow)
        if not stripped:
            # If we already have description text and hit a blank line,
            # peek ahead: if the next non-blank line is a new item, stop
            if desc_parts:
                for j in range(i + 1, min(i + 3, len(lines))):
                    peek = lines[j].strip()
                    if peek and _ITEM_RE.match(lines[j]):
                        break
                else:
                    continue
                break
            continue

        # Skip lines that look like they're just price columns (all numbers)
        if re.fullmatch(r'[\d\s.,T$%]+', stripped):
            continue

        desc_parts.append(stripped)

    return " ".join(desc_parts)


def _parse_vendor(text: str) -> str:
    """Identify the repair shop.  Known BSD shops are matched anywhere in the
    text (letterheads say things like 'BandWright Repair, LLC'); otherwise
    fall back to the first line that isn't boilerplate like 'Repair Invoice'."""
    low = text.lower()
    for shop in KNOWN_SHOPS:
        keys = [shop.lower()]
        if "&" in shop:
            keys.append(shop.replace("&", "and").lower())
        if any(k in low for k in keys):
            return shop
    skip = re.compile(r'^(repair\s+)?invoice$|^date$|^customer$|^invoice\s*#'
                      r'|^page\b|^p\.?o\.?\s*number|^project\s+name',
                      re.IGNORECASE)
    for line in text.split('\n'):
        line = line.strip()
        if line and len(line) > 2 and not skip.match(line):
            return line[:80]
    return ""


# ── Line-item structure (shared by description + cost extraction) ─────────────

# Left-aligned Item-column values that start a NEW line item
_ITEM_RE = re.compile(
    r'^\s{0,4}'
    r'(?:Repair|Neck Cork|Minimum Shop|Service|Parts|Supplies|'
    r'Repad|Overhaul|Dent Removal|Play Test|Emergency|Soldering|'
    r'Rental|Accessory|Assembly|Cleaning|Custom|Clarinet PC|Tenon Cork|'
    r'No Charge)',
    re.IGNORECASE
)
# A parts line that belongs to the labor item above it
_PARTS_LINE_RE = re.compile(r'(?:repair\s+)?parts\s*/\s*supplies', re.IGNORECASE)
# Boundaries that end the line-item section entirely
_BOUNDARY_RE = re.compile(
    r'(?:Subtotal|Total|Sales Tax|Balance Due|Thank|BandWright stands)',
    re.IGNORECASE
)


def _line_index_of(lines, pos: int) -> int:
    """Index of the line containing character offset pos."""
    cumulative = 0
    for i, line in enumerate(lines):
        cumulative += len(line) + 1
        if cumulative > pos:
            return i
    return max(0, len(lines) - 1)


def _amount_on_line(line: str) -> float:
    """The line-item amount on one text line.  Prefer the taxable-marker form
    ('14.00T', unambiguous); otherwise the last reasonable decimal, which is
    the Amount column (Rate comes before Amount)."""
    taxable = re.findall(r'(\d+(?:,\d{3})*\.\d{2})T\b', line)
    if taxable:
        try:
            return float(taxable[-1].replace(',', ''))
        except ValueError:
            pass
    plain = re.findall(r'\b(\d{1,4}\.\d{2})\b', line)
    valid = [float(p) for p in plain if 1.0 <= float(p) <= 9999.0]
    return valid[-1] if valid else 0.0


def _parse_instrument_cost(text: str, match_pos: int, match_val_len: int,
                           tax_rate: float):
    """Full cost of one instrument's repair: its labor line plus every cost line
    that follows, up to the NEXT instrument or the invoice footer.

    Each instrument's block is keyed off the SERIAL NUMBER in the second
    (Description) column — e.g. 'Repair (WW)  Alto saxophone, Bundy II, SN:
    945610 … 75.00T' — NOT the Item-column label.  Everything after that line
    with no serial of its own (description lines, and cost lines such as
    'Repair Parts/Supplies', extra 'Soldering', etc.) belongs to this
    instrument; the block ends at the next line that carries a serial number
    (the next instrument) or a footer boundary (Subtotal / Total …).  Keying on
    the serial makes attribution robust to whatever wording the shop puts in the
    Item column.  Returns (labor, extra_total, cost_with_tax)."""
    lines = text.split('\n')
    li = _line_index_of(lines, match_pos)

    labor = _amount_on_line(lines[li])
    if labor <= 0:
        labor = _parse_line_amount(text, match_pos, match_val_len)

    extra = 0.0
    for i in range(li + 1, len(lines)):
        line = lines[i]
        stripped = line.strip()
        if not stripped:
            continue
        if _BOUNDARY_RE.search(stripped):
            break
        # A serial number in the description column = the next instrument's
        # block begins here, so everything up to now belonged to THIS one.
        if re.search(r'\bS[/ ]?N\s*[:#]', line, re.IGNORECASE):
            break
        # Any dollar amount on an in-between line (parts/supplies, extra labor,
        # etc.) counts toward this instrument, whatever its Item-column reads.
        extra += _amount_on_line(line)

    total = round((labor + extra) * (1 + tax_rate), 2) if labor > 0 else 0.0
    return labor, extra, total


# ── Main entry point ──────────────────────────────────────────────────────────

def parse_invoices(pdf_paths: list, instruments: list) -> list:
    """
    Parse one or more PDF invoices and match content against instrument records.

    Matching looks for serial_no, barcode, or district_no in the PDF text.
    Values shorter than 4 characters are skipped to avoid false positives.

    Cost logic (per instrument):
      1. Labor: the amount on the line containing the serial/barcode
      2. Parts: any 'Repair Parts/Supplies' lines below it (before the next item)
      3. cost = (labor + parts) * (1 + invoice tax rate)
      4. Fall back to the smallest $X.XX in context if no line amount found

    Returns a list of dicts; error entries contain an "error" key.  Each file
    with matches also yields one reconciliation entry ({"summary": True, ...})
    comparing the matched records' cost sum against the invoice's grand total,
    so the caller can flag line items that didn't match any instrument.
    """
    results = []
    seen = set()  # (instrument_id, pdf_path) to avoid duplicate entries

    for pdf_path in pdf_paths:
        source_name = os.path.basename(pdf_path)
        try:
            text = extract_pdf_text(pdf_path)
        except Exception as e:
            results.append({"error": f"{source_name}: {e}", "source_file": source_name})
            continue

        # Invoice-level fields — computed once per file
        invoice_number = _parse_invoice_number(text, source_name)
        vendor         = _parse_vendor(text)
        invoice_date   = _parse_date(text)       # header date = when repaired
        tax_rate       = _parse_tax_rate(text)   # e.g. 0.103 for 10.3%
        invoice_total  = _parse_invoice_total(text)
        scan_date      = datetime.today().strftime("%Y-%m-%d")
        file_matches   = []

        for instr in instruments:
            if not instr.get("is_active", 1):
                continue

            serial  = (instr.get("serial_no")  or "").strip()
            barcode = (instr.get("barcode")     or "").strip()
            dist_no = (instr.get("district_no") or "").strip()

            matched_by  = None
            matched_val = None

            for field, val in [
                ("serial_no",   serial),
                ("barcode",     barcode),
                ("district_no", dist_no),
            ]:
                if not val or len(val) < 4:
                    continue
                if re.search(r'\b' + re.escape(val) + r'\b', text, re.IGNORECASE):
                    matched_by  = field
                    matched_val = val
                    break

            if not matched_by:
                continue

            key = (instr["id"], pdf_path)
            if key in seen:
                continue
            seen.add(key)

            # Locate the match precisely
            m_obj   = re.search(r'\b' + re.escape(matched_val) + r'\b', text, re.IGNORECASE)
            match_pos = m_obj.start() if m_obj else text.lower().find(matched_val.lower())

            # ── Cost: labor + this instrument's parts lines + tax ────────────
            labor, parts, act_cost = _parse_instrument_cost(
                text, match_pos, len(matched_val), tax_rate)

            if act_cost <= 0:
                # Fallback: smallest explicit $X.XX in surrounding context
                ctx_start = max(0, match_pos - 400)
                ctx_end   = min(len(text), match_pos + 600)
                act_cost  = _parse_cost_from_context(text[ctx_start:ctx_end])

            # Extract the actual repair description from the invoice
            repair_desc = _parse_repair_description(text, match_pos)

            desc  = instr.get("description") or ""
            brand = instr.get("brand") or ""
            label = desc + (f" — {brand}" if brand else "")
            label += f" ({matched_by.replace('_', ' ').title()}: {matched_val})"

            if labor > 0:
                bits = [f"Labor ${labor:.2f}"]
                if parts > 0:
                    bits.append(f"parts ${parts:.2f}")
                if tax_rate > 0:
                    bits.append(f"tax ({tax_rate*100:.1f}%)")
                cost_note = " + ".join(bits) + f" = ${act_cost:.2f}"
            else:
                cost_note = ""

            notes_parts = [
                f"Matched by {matched_by.replace('_', ' ')}: {matched_val}",
                f"Source: {source_name}",
            ]
            if cost_note:
                notes_parts.append(cost_note)

            prefill = {
                "description":    repair_desc if repair_desc else f"Repair — see {source_name}",
                "priority":       1,                # Normal
                "assigned_to":    vendor,
                "date_added":     scan_date,        # when the invoice was scanned
                "date_repaired":  invoice_date,     # the invoice's own date
                "act_cost":       f"{act_cost:.2f}" if act_cost else "",
                "invoice_number": invoice_number,
                "notes":          "\n".join(notes_parts),
            }

            entry = {
                "instrument_id":    instr["id"],
                "instrument_label": label,
                "matched_by":       matched_by,
                "matched_value":    matched_val,
                "source_file":      source_name,
                "prefill":          prefill,
            }
            results.append(entry)
            file_matches.append(entry)

        # ── Reconciliation: do the matched records add up to the invoice? ──
        # Per-instrument tax rounding can drift a cent or two per line, so
        # allow 2¢ per matched record before calling it a mismatch.
        if file_matches:
            matched_total = round(sum(
                float(m["prefill"]["act_cost"] or 0) for m in file_matches), 2)
            tolerance = 0.02 * len(file_matches)
            results.append({
                "summary":       True,
                "source_file":   source_name,
                "invoice_total": invoice_total,
                "matched_total": matched_total,
                "n_matched":     len(file_matches),
                "balanced":      (invoice_total > 0
                                  and abs(invoice_total - matched_total) <= tolerance),
            })

    return results
