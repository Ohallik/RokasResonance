"""
invoice_parser.py - Parse repair invoices (PDF) and match to instrument records.
"""

import os
import re
from datetime import datetime


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


def _parse_invoice_number(text: str) -> str:
    """Try to extract an invoice / work-order number."""
    patterns = [
        r'(?:invoice|inv)[\s#:\-]*([A-Z0-9\-]{3,20})',
        r'(?:work\s*order|wo)[\s#:\-]*([A-Z0-9\-]{3,20})',
        r'(?:order\s*(?:no|#|number))[\s:.\-]*([A-Z0-9\-]{3,20})',
        r'#\s*([A-Z0-9\-]{4,20})',
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            val = m.group(1).strip()
            if not re.fullmatch(r'\d{1,2}', val):
                return val
    return ""


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

    # Locate the line index that contains match_pos
    cumulative = 0
    match_line_idx = 0
    for i, line in enumerate(lines):
        cumulative += len(line) + 1
        if cumulative > match_pos:
            match_line_idx = i
            break

    # Patterns that signal the start of a NEW line item (left-aligned item types)
    _ITEM_RE = re.compile(
        r'^\s{0,4}'  # at most 4 leading spaces (left-aligned)
        r'(?:Repair|Neck Cork|Minimum Shop|Service|Parts|Supplies|'
        r'Repad|Overhaul|Dent Removal|Play Test|Emergency|'
        r'Rental|Accessory|Assembly|Cleaning|Custom)',
        re.IGNORECASE
    )
    # Boundaries that end the line-item section entirely
    _BOUNDARY_RE = re.compile(
        r'(?:Subtotal|Total|Sales Tax|Balance Due|Thank|BandWright stands)',
        re.IGNORECASE
    )

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
    """Return the first non-empty line (usually the company/shop name)."""
    for line in text.split('\n'):
        line = line.strip()
        if line and len(line) > 2:
            return line[:80]
    return ""


# ── Main entry point ──────────────────────────────────────────────────────────

def parse_invoices(pdf_paths: list, instruments: list) -> list:
    """
    Parse one or more PDF invoices and match content against instrument records.

    Matching looks for serial_no, barcode, or district_no in the PDF text.
    Values shorter than 4 characters are skipped to avoid false positives.

    Cost logic (per instrument):
      1. Find the amount on/near the specific line containing the serial/barcode
      2. Extract the invoice-level tax rate (e.g. 'Sales Tax (10.3%)')
      3. act_cost = line_amount * (1 + tax_rate)
      4. Fall back to the smallest $X.XX in context if no line amount found

    Returns a list of dicts; error entries contain an "error" key.
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
        invoice_number = _parse_invoice_number(text)
        vendor         = _parse_vendor(text)
        invoice_date   = _parse_date(text)
        tax_rate       = _parse_tax_rate(text)   # e.g. 0.103 for 10.3%

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

            # ── Cost ─────────────────────────────────────────────────────────
            line_amount = _parse_line_amount(text, match_pos, len(matched_val))

            if line_amount > 0:
                act_cost = round(line_amount * (1 + tax_rate), 2)
            else:
                # Fallback: smallest explicit $X.XX in surrounding context
                ctx_start = max(0, match_pos - 400)
                ctx_end   = min(len(text), match_pos + 600)
                act_cost  = _parse_cost_from_context(text[ctx_start:ctx_end])

            # ── Other fields ─────────────────────────────────────────────────
            ctx_start   = max(0, match_pos - 400)
            ctx_end     = min(len(text), match_pos + 600)
            context     = text[ctx_start:ctx_end]
            repair_date = _parse_date(context)

            # Extract the actual repair description from the invoice
            repair_desc = _parse_repair_description(text, match_pos)

            desc  = instr.get("description") or ""
            brand = instr.get("brand") or ""
            label = desc + (f" — {brand}" if brand else "")
            label += f" ({matched_by.replace('_', ' ').title()}: {matched_val})"

            if line_amount > 0 and tax_rate > 0:
                cost_note = (
                    f"Line item: ${line_amount:.2f}  "
                    f"+ tax ({tax_rate*100:.1f}%)  "
                    f"= ${act_cost:.2f}"
                )
            elif line_amount > 0:
                cost_note = f"Line item: ${line_amount:.2f}"
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
                "assigned_to":    vendor,
                "date_added":     invoice_date,
                "date_repaired":  repair_date,
                "act_cost":       f"{act_cost:.2f}" if act_cost else "",
                "invoice_number": invoice_number,
                "notes":          "\n".join(notes_parts),
            }

            results.append({
                "instrument_id":    instr["id"],
                "instrument_label": label,
                "matched_by":       matched_by,
                "matched_value":    matched_val,
                "source_file":      source_name,
                "prefill":          prefill,
            })

    return results
