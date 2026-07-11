"""
concert_program_pub.py - Generate Microsoft Publisher (.pub) documents for
concert programs and family details pages.

BSD music teachers edit programs in Publisher, so instead of exporting a
fixed PDF we drive Publisher itself (COM, via pywin32) and build a real .pub:
a cover page (school, title, director, date/location/time, Tonight's Program,
Acknowledgements, Upcoming Performances) plus personnel pages in score order.
Everything lands in ordinary text boxes the teacher can restyle or move.

Requires Windows + Microsoft Publisher + pywin32 (already app dependencies —
the concert-program importer uses the same COM bridge to read .pub files).
"""

from concert_tools import (fmt_date, ensembles_list, mark_name, marks_legend,
                           _lines, _time_range)

IN = 72.0                       # Publisher measures in points
PAGE_W, PAGE_H = 8.5 * IN, 11 * IN
MARGIN = 0.5 * IN

_HORIZ = 1                      # pbTextOrientationHorizontal
_CENTER = 1                     # pbParagraphAlignmentCenter
_LEFT = 3                       # pbParagraphAlignmentLeft

FONT = "Calibri"


class PublisherError(RuntimeError):
    pass


PRINT_BOOKLET_SIDE_FOLD = 5      # pbPrintStyleBookletSideFold
PRINT_ONE_PER_SHEET = 1          # pbPrintStyleOnePagePerSheet


def open_pub(path, print_style=None):
    """Open a .pub in Publisher for the user.

    Publisher can't persist print settings inside the file (PrintStyle
    resets on reopen and PublicationLayout is read-only via COM), so for
    folded booklets we open the document through COM and set 'Booklet,
    side-fold' in that live session — the print dialog then comes up with
    the right setting instead of 'multiple copies per sheet'.  Falls back
    to a plain shell-open if automation fails."""
    import os
    if print_style is not None:
        try:
            import pythoncom
            import win32com.client
            pythoncom.CoInitialize()
            app = win32com.client.DispatchEx("Publisher.Application")
            doc = app.Open(os.path.abspath(path))
            app.ActiveWindow.Visible = True
            # Set AFTER the window exists — window init can reset it
            try:
                doc.PrintStyle = print_style
            except Exception:
                pass
            return                      # leave Publisher open for the user
        except Exception:
            pass
    os.startfile(path)


def _open_publisher():
    try:
        import win32com.client
    except ImportError:
        raise PublisherError(
            "pywin32 isn't installed, so Publisher files can't be created. "
            "Run 'pip install pywin32' and try again.")
    try:
        app = win32com.client.DispatchEx("Publisher.Application")
    except Exception as e:
        raise PublisherError(
            f"Couldn't start Microsoft Publisher ({e}). Publisher must be "
            "installed to generate an editable .pub program.")
    return app


def _new_document(app):
    """Publisher's automation API varies slightly by version — try the
    known entry points in order."""
    for attempt in ("NewDocument", "Documents.Add"):
        try:
            if attempt == "NewDocument":
                return app.NewDocument()
            return app.Documents.Add()
        except Exception:
            continue
    raise PublisherError("Publisher started, but a new document couldn't be "
                         "created (unsupported Publisher version?).")


def _add_box(page, left, top, width, height, lines, *,
             align=_LEFT, size=11, bold_idx=(), sizes=None, border=False,
             fill=None, font=None, tight=False):
    """One text box.  lines = list of paragraph strings; bold_idx = indices to
    bold; sizes = {index: pt} for per-paragraph sizes.  font overrides the
    default (personnel pages use Segoe UI so ♪/★ marks have real glyphs);
    tight removes after-paragraph spacing for dense rosters."""
    tb = page.Shapes.AddTextbox(_HORIZ, left, top, width, height)
    try:
        tb.TextFrame.AutoFitText = 0        # pbTextAutoFitNone — no shrink
    except Exception:
        pass
    tr = tb.TextFrame.TextRange
    tr.Text = "\r".join(lines) if lines else ""
    try:
        tr.Font.Name = font or FONT
        tr.Font.Size = size
        tr.ParagraphFormat.Alignment = align
        if tight:
            tr.ParagraphFormat.SpaceAfter = 0
            tr.ParagraphFormat.SpaceBefore = 0
    except Exception:
        pass
    for i in bold_idx:
        try:
            tr.Paragraphs(i + 1, 1).Font.Bold = -1
        except Exception:
            pass
    for i, pt in (sizes or {}).items():
        try:
            tr.Paragraphs(i + 1, 1).Font.Size = pt
        except Exception:
            pass
    if border:
        try:
            tb.Line.Visible = -1
            tb.Line.Weight = 1.25
        except Exception:
            pass
    if fill:
        try:
            tb.Fill.ForeColor.RGB = fill
            tb.Fill.Visible = -1
        except Exception:
            pass
    return tb


def _rgb(r, g, b):
    return r + (g << 8) + (b << 16)


# ── Program (.pub) ────────────────────────────────────────────────────────────

def _program_lines(pieces_by_ensemble):
    """Tonight's Program body: ensemble headings + 'Title……Composer' lines
    with dot leaders, like the printed programs teachers already make."""
    lines, bold = [], []
    for ens, pieces in pieces_by_ensemble.items():
        bold.append(len(lines))
        lines.append(ens)
        if not pieces:
            lines.append("Selections to be announced")
        for p in pieces:
            credit = (p.get("composer") or "").strip()
            arr = (p.get("arranger") or "").strip()
            if arr:
                credit = (credit + ", " if credit else "") + f"arr. {arr}"
            title = (p.get("title") or "").strip()
            if credit:
                dots = "." * max(8, 56 - len(title) - len(credit))
                lines.append(f"{title}{dots}{credit}")
            else:
                lines.append(title)
        lines.append("")
    if lines and lines[-1] == "":
        lines.pop()
    return lines, bold


def _masthead_lines(concert, school_name, director):
    title = (concert.get("title") or "Concert").strip()
    when = fmt_date(concert.get("concert_date"))
    tr_time = _time_range(concert)
    head = [school_name.upper() if school_name else "", title,
            f"{when}" + (f", {tr_time}" if tr_time else "")]
    head_bold = [0, 1]
    head_sizes = {0: 20, 1: 34, 2: 13}
    n = 3
    if concert.get("location"):
        head.append(concert["location"])
        head_sizes[n] = 13
        n += 1
    directors = (concert.get("directors") or "").strip() or director
    if directors:
        head.append(f"Directed by {directors}")
        head_sizes[n] = 12
        n += 1
    guests = (concert.get("special_guests") or "").strip()
    if guests:
        head.append(f"Special Guests: {guests}")
        head_sizes[n] = 12
    head = [h for h in head if h != ""]
    if not school_name:
        head_sizes = {i - 1: s for i, s in head_sizes.items() if i >= 1}
        head_bold = [0]
    return head, head_bold, head_sizes


def _personnel_pages(doc, personnel, *, page_w, page_h, margin, per_page,
                     cap, start_after, name_size=11, sec_size=12,
                     ens_size=17):
    """Render personnel columns onto new pages appended after start_after.

    Layout planning lives in concert_tools.personnel_columns: each ensemble
    starts a fresh column and stays on one page when it fits; sections stay
    whole (nobody strands alone at a column top); single-spaced names with a
    blank line between sections.

    Each ensemble's columns are created as LINKED text frames and its whole
    roster is poured into the first one, so if fonts run a little taller
    than planned the text flows into the next column automatically — never
    hidden behind Publisher's overflow marker.  The planning cap is set
    conservatively so every chain has spare room."""
    from concert_tools import personnel_columns, paginate_columns
    cols, owners = personnel_columns(personnel, cap=cap)
    pages = paginate_columns(cols, owners, per_page=per_page)
    legend = marks_legend(personnel)

    gutter = 0.25 * IN
    col_w = (page_w - 2 * margin - (per_page - 1) * gutter) / per_page

    # 1) create every column box, empty
    shapes = []
    page_no = start_after
    for pg in pages:
        page_no += 1
        doc.Pages.Add(1, page_no - 1)
        p = doc.Pages(page_no)
        for ci in range(len(pg)):
            x = margin + ci * (col_w + gutter)
            tb = p.Shapes.AddTextbox(_HORIZ, x, margin, col_w,
                                     page_h - 2 * margin - 0.35 * IN)
            try:
                tb.TextFrame.AutoFitText = 0
            except Exception:
                pass
            shapes.append(tb)

    # 2) per ensemble: link its boxes into one chain, pour the roster in,
    #    then format paragraph-by-paragraph across the whole story
    i = 0
    while i < len(shapes):
        j = i
        while j + 1 < len(owners) and owners[j + 1] == owners[i]:
            j += 1
        chain = shapes[i:j + 1]
        for a, b in zip(chain, chain[1:]):
            try:
                a.TextFrame.NextLinkedTextFrame = b.TextFrame
            except Exception:
                pass
        lines, styles = [], []
        for k in range(i, j + 1):
            for t, st in cols[k]:
                lines.append(t)
                styles.append(st)
        while lines and styles[-1] == "gap":
            lines.pop()
            styles.pop()

        tr = chain[0].TextFrame.TextRange
        tr.Text = "\r".join(lines)
        try:
            story = chain[0].TextFrame.Story.TextRange
        except Exception:
            story = tr
        try:
            story.Font.Name = "Segoe UI Symbol"
            story.Font.Size = name_size
            story.ParagraphFormat.SpaceAfter = 0
            story.ParagraphFormat.SpaceBefore = 0
        except Exception:
            pass
        for idx, st in enumerate(styles):
            if st in ("ens", "sec"):
                try:
                    para = story.Paragraphs(idx + 1, 1)
                    para.Font.Bold = -1
                    para.Font.Size = ens_size if st == "ens" else sec_size
                except Exception:
                    pass
        i = j + 1

    if legend and page_no > start_after:
        p = doc.Pages(page_no)
        _add_box(p, margin, page_h - margin - 0.3 * IN,
                 page_w - 2 * margin, 0.3 * IN, [legend],
                 align=_CENTER, size=10, font="Segoe UI Symbol")
    return page_no


def build_program_pub(path, concert, pieces_by_ensemble, personnel,
                      school_name="", director="", layout="full"):
    """Create the .pub program.

    pieces_by_ensemble: {ensemble: [piece dicts]} in performance order.
    personnel: {ensemble: [(section, [member dicts]), ...]} from
    concert_tools.personnel_sections — pass {} to skip personnel pages.
    layout: 'full' = 8.5×11 pages, staple-friendly front-to-back printing;
    'folded' = half-letter 5.5×8.5 pages (front cover / program / acks /
    personnel) — print with Publisher's booklet setting and fold.
    """
    import pythoncom
    pythoncom.CoInitialize()
    app = _open_publisher()
    doc = None
    try:
        doc = _new_document(app)
        if layout == "folded":
            page_w, page_h, margin = 5.5 * IN, 8.5 * IN, 0.4 * IN
        else:
            page_w, page_h, margin = PAGE_W, PAGE_H, MARGIN
        # Always set the page size explicitly — Publisher's "new document"
        # inherits whatever template/size the machine last used (a folded
        # Music template gave a teacher half-letter "full page" programs).
        try:
            doc.PageSetup.PageWidth = page_w
            doc.PageSetup.PageHeight = page_h
        except Exception:
            pass
        # Print settings: folded booklets print as "Booklet, side-fold"
        # (Publisher's default for half-letter pages is "multiple copies per
        # sheet", which prints two copies of every page); full pages print
        # one per sheet.
        try:
            doc.PrintStyle = 5 if layout == "folded" else 1
        except Exception:
            pass

        head, head_bold, head_sizes = _masthead_lines(concert, school_name,
                                                      director)
        prog_lines, prog_bold = _program_lines(pieces_by_ensemble)
        ack = _lines(concert.get("acknowledgements"))
        upc = _lines(concert.get("upcoming"))

        head_h = (0.9 + 0.34 * (len(head) - 1)) * IN   # title line + the rest

        if layout == "folded":
            # ── p1: front cover (title block; room below for artwork) ──
            page = doc.Pages(1)
            _add_box(page, margin, 1.1 * IN, page_w - 2 * margin,
                     head_h + 0.3 * IN,
                     head, align=_CENTER, size=12, bold_idx=head_bold,
                     sizes={k: (26 if v == 34 else v - 1 if v > 12 else v)
                            for k, v in head_sizes.items()})
            # ── p2: Tonight's Program ──
            doc.Pages.Add(1, 1)
            body = ["Tonight's Program", ""] + prog_lines
            _add_box(doc.Pages(2), margin, margin, page_w - 2 * margin,
                     page_h - 2 * margin,
                     body, align=_CENTER, size=10.5,
                     bold_idx=[0] + [i + 2 for i in prog_bold],
                     sizes={0: 15})
            # ── p3: Acknowledgements + Upcoming ──
            doc.Pages.Add(1, 2)
            p3 = doc.Pages(3)
            if ack:
                _add_box(p3, margin, margin, page_w - 2 * margin, 4.0 * IN,
                         ["Acknowledgements", ""] + ack, align=_CENTER,
                         size=10, bold_idx=[0], sizes={0: 14})
            if upc:
                _add_box(p3, margin, 4.3 * IN, page_w - 2 * margin,
                         page_h - 4.3 * IN - margin,
                         ["Upcoming Performances", ""] + upc, align=_CENTER,
                         size=10, bold_idx=[0], sizes={0: 14})
            last_page = 3
            if personnel:
                last_page = _personnel_pages(doc, personnel, page_w=page_w,
                                             page_h=page_h, margin=margin,
                                             per_page=2, cap=34,
                                             start_after=3)
        else:
            # ── Full page: newspaper-style cover — boxed masthead across the
            # top, Tonight's Program down the left, Acknowledgements and
            # Upcoming Performances boxed on the right ──
            page = doc.Pages(1)
            _add_box(page, margin, margin, page_w - 2 * margin, head_h,
                     head, align=_CENTER, size=13, bold_idx=head_bold,
                     sizes=head_sizes, border=True)
            body_y = margin + head_h + 0.2 * IN
            body = ["Tonight's Program", ""] + prog_lines
            _add_box(page, margin, body_y, 4.55 * IN,
                     page_h - body_y - margin,
                     body, align=_CENTER, size=11,
                     bold_idx=[0] + [i + 2 for i in prog_bold],
                     sizes={0: 16}, border=True, fill=_rgb(252, 250, 232))
            right_x = margin + 4.75 * IN
            right_w = page_w - right_x - margin
            right_h = page_h - body_y - margin
            if ack:
                _add_box(page, right_x, body_y, right_w,
                         right_h * 0.55,
                         ["Acknowledgements", ""] + ack, align=_CENTER,
                         size=10, bold_idx=[0], sizes={0: 15}, border=True,
                         fill=_rgb(235, 243, 252))
            if upc:
                upc_y = body_y + right_h * 0.55 + 0.2 * IN
                _add_box(page, right_x, upc_y, right_w,
                         page_h - upc_y - margin,
                         ["Upcoming Performances", ""] + upc, align=_CENTER,
                         size=10, bold_idx=[0], sizes={0: 15}, border=True,
                         fill=_rgb(246, 235, 250))
            # Personnel: FOUR columns per page so two ensembles share a page
            # (Jazz 1 + Jazz 2 together, Entry + Intermediate, …) instead of
            # burning a page per ensemble.
            last_page = 1
            if personnel:
                last_page = _personnel_pages(doc, personnel, page_w=page_w,
                                             page_h=page_h, margin=margin,
                                             per_page=4, cap=42,
                                             start_after=1,
                                             name_size=10.5, sec_size=11.5,
                                             ens_size=15)

        # ── Additional program info (recruiting blurbs, class descriptions,
        # testimonials…) — its own page at the back; first line = heading ──
        extra = [ln.strip() for ln in
                 (concert.get("extra_info") or "").splitlines()]
        while extra and not extra[0]:
            extra.pop(0)
        while extra and not extra[-1]:
            extra.pop()
        if extra:
            doc.Pages.Add(1, last_page)
            p = doc.Pages(last_page + 1)
            _add_box(p, margin, margin, page_w - 2 * margin,
                     page_h - 2 * margin, extra,
                     size=10.5 if layout == "folded" else 11.5,
                     bold_idx=[0], sizes={0: 16 if layout == "folded" else 18})

        import os
        doc.SaveAs(os.path.abspath(path))
    finally:
        try:
            if doc is not None:
                doc.Close()
        except Exception:
            pass
        try:
            app.Quit()
        except Exception:
            pass
        try:
            pythoncom.CoUninitialize()
        except Exception:
            pass
    return path


# ── Details page (.pub) ───────────────────────────────────────────────────────

def build_details_pub(path, concert, school_name=""):
    """One-page family details sheet: masthead, What to Wear / Required
    Rehearsals side boxes, and The Plan itinerary — like the concert guides
    the program already sends home."""
    import pythoncom
    pythoncom.CoInitialize()
    app = _open_publisher()
    doc = None
    try:
        doc = _new_document(app)
        page = doc.Pages(1)

        from concert_tools import TUTORIAL_BLURB

        title = (concert.get("title") or "Concert").strip()
        when = fmt_date(concert.get("concert_date"))
        tr_time = _time_range(concert)
        head = [title, when + (f", {tr_time}" if tr_time else "")]
        if concert.get("location"):
            head.append(concert["location"])
        if (concert.get("setup") or "").strip():
            head.append(f"Set-up: {concert['setup'].strip()}")
        if (concert.get("arrival") or "").strip():
            head.append(f"Student arrival: {concert['arrival'].strip()}")
        if (concert.get("seated_by") or "").strip():
            head.append(f"Everyone seated in the venue by: {concert['seated_by'].strip()}")
        head_h = (0.75 + 0.28 * (len(head) - 1)) * IN
        _add_box(page, MARGIN, MARGIN, PAGE_W - 2 * MARGIN, head_h,
                 head, align=_CENTER, size=13, bold_idx=[0, 1],
                 sizes={0: 26})

        # ── Left column: What to wear + Required tutorials ──
        box_y = MARGIN + head_h + 0.2 * IN
        col_h = 4.0 * IN
        left_w = 3.5 * IN
        y = box_y
        wear = _lines(concert.get("attire"))
        if wear:
            _add_box(page, MARGIN, y, left_w, 1.5 * IN,
                     ["What to wear:"] + wear, size=11, bold_idx=[0],
                     border=True, tight=True)
            y += 1.5 * IN + 0.18 * IN
        reh = _lines(concert.get("rehearsals"))
        block = []
        if reh:
            block = ["REQUIRED TUTORIALS:"] + reh + ["", TUTORIAL_BLURB]
        bring = _lines(concert.get("bring"))
        if bring:
            block += ([""] if block else []) + ["What to bring:"] + bring
        if block:
            _add_box(page, MARGIN, y, left_w, box_y + col_h - y,
                     block, size=10,
                     bold_idx=[i for i, ln in enumerate(block)
                               if ln.rstrip(":").isupper() or ln == "What to bring:"],
                     border=True, tight=True)

        # ── Right column: space to draw the performance set-up ──
        right_x = MARGIN + left_w + 0.25 * IN
        right_w = PAGE_W - right_x - MARGIN
        _add_box(page, right_x, box_y, right_w, col_h,
                 ["Performance set-up:"], size=11, bold_idx=[0], border=True)

        # ── The Plan (full width) ──
        plan_y = box_y + col_h + 0.25 * IN
        plan = ["The Plan:", ""]
        bold_idx = [0]
        for ln in _lines(concert.get("itinerary")):
            if "|" in ln:
                t, act = ln.split("|", 1)
                plan.append(f"{t.strip()}   {act.strip()}")
            else:
                plan.append(ln)
        if concert.get("perf_order"):
            plan += ["", f"Performance order: {concert['perf_order'].strip()}"]
            bold_idx.append(len(plan) - 1)
        _add_box(page, MARGIN, plan_y, PAGE_W - 2 * MARGIN,
                 PAGE_H - plan_y - MARGIN,
                 plan, size=11.5, bold_idx=bold_idx, sizes={0: 18})

        import os
        doc.SaveAs(os.path.abspath(path))
    finally:
        try:
            if doc is not None:
                doc.Close()
        except Exception:
            pass
        try:
            app.Quit()
        except Exception:
            pass
        try:
            pythoncom.CoUninitialize()
        except Exception:
            pass
    return path
