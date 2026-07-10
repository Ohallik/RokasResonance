"""
seating_render.py - Render a seating chart to a PIL image (rows or arcs).

Returns (image, seat_boxes) where seat_boxes maps a seat key -> (x0, y0, x1, y1)
in FINAL image pixels.  A seat key is (row_index, col) for a normal seat or
("P", col) for a seat in the separate percussion back row, so the on-screen view
can map a click to a seat (for swapping) and the same picture can be copied to
the clipboard.
"""

import math

from percussion_board_image import _calibri, _text_size, copy_image_to_clipboard  # noqa
import seating_chart as sc

_SS = 3  # supersample for crisp text

# Row colors aligned to typical velcro carpet markers (front -> back).
DEFAULT_PALETTE = ["#ff3b30", "#8db4e2", "#ffd966", "#a9d08e",
                   "#b3a2c7", "#f4b183", "#76d7c4", "#f7a5c4"]
NO_COLOR = "#e9e9e9"
PERC_COLOR = "#c9bfe0"   # distinct lavender for the percussion back row


def _text_on(hex_color):
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    lum = 0.299 * r + 0.587 * g + 0.114 * b
    return "#000000" if lum > 150 else "#ffffff"


def _name_of(seat):
    return (seat.get("name") or "") if seat else ""


# Short instrument labels for the chart (full names stay in pickers/data).
INSTRUMENT_ABBREV = {
    "Baritone BC": "Bar BC", "Baritone TC": "Bar TC",
    "Euphonium BC": "Euph BC", "Euphonium TC": "Euph TC",
    "Baritone/Euphonium": "Bar/Euph",
    "Alto Saxophone": "Alto Sax", "Tenor Saxophone": "Tenor Sax",
    "Baritone Saxophone": "Bari Sax",
}


def _inst_label(seat):
    inst = (seat.get("instrument") or "") if seat else ""
    return INSTRUMENT_ABBREV.get(inst, inst)


def render_rows(rows, row_caps, palette_on=True, palette=None,
                front_label="FRONT OF THE ROOM", flip=False, font_pt=14,
                percussion=None, show_instrument=True, color_mode="row"):
    from PIL import Image, ImageDraw

    palette = palette or DEFAULT_PALETTE
    s = _SS
    fs = int(font_pt * 96 / 72 * s)
    fs_i = int(fs * 0.78)
    pad = int(10 * s)
    num_h = int(fs * 1.5)
    name_h = int(fs * 2.6) if show_instrument else int(fs * 1.8)
    row_gap = int(fs * 0.8)
    label_h = int(fs * 1.7) + pad
    cap_h = int(fs * 1.3)      # small caption above the percussion row

    scratch = Image.new("RGB", (10, 10), "white")
    d0 = ImageDraw.Draw(scratch)
    font = _calibri(fs)
    font_b = _calibri(fs, bold=True)
    font_i = _calibri(fs_i)
    font_lbl = _calibri(int(fs * 1.15), bold=True)

    n_rows = len(rows)
    caps = [sc.row_capacity(row_caps, r) for r in range(n_rows)]

    row_band = (color_mode == "row")
    # Build the ordered list of "row specs" front -> back.
    specs = []
    for r in range(n_rows):
        specs.append({
            "key": r, "cap": caps[r], "cells": rows[r],
            "color": palette[r % len(palette)] if row_band else NO_COLOR,
            "caption": None,
        })
    if percussion:
        specs.append({
            "key": "P", "cap": len(percussion), "cells": percussion,
            "color": PERC_COLOR if row_band else NO_COLOR,
            "caption": "Percussion (back row)",
        })

    all_names = [_name_of(x) for sp in specs for x in sp["cells"]] + ["Wwwwwwww"]
    cell_w = max(_text_size(d0, n, font)[0] for n in all_names) + pad * 2
    if show_instrument:
        all_insts = [_inst_label(x) for sp in specs for x in sp["cells"] if x] + ["Ww"]
        cell_w = max(cell_w, max(_text_size(d0, i, font_i)[0] for i in all_insts) + pad * 2)
    cell_w = max(cell_w, int(70 * s))

    width = pad * 2 + max((sp["cap"] * cell_w for sp in specs), default=cell_w)
    body_h = 0
    for sp in specs:
        body_h += num_h + name_h + row_gap + (cap_h if sp["caption"] else 0)
    top_h = label_h if (front_label and not flip) else 0
    bot_h = label_h if (front_label and flip) else 0
    height = pad * 2 + top_h + body_h + bot_h

    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    seat_boxes = {}
    grid = "#b8b8b8"

    y = pad
    if front_label and not flip:
        draw.text((pad, y), front_label, font=font_lbl, fill="#000000")
    y += top_h

    ordered_specs = specs if not flip else specs[::-1]
    for sp in ordered_specs:
        if sp["caption"]:
            draw.text((pad, y), sp["caption"], font=_calibri(int(fs * 1.0), bold=True),
                      fill="#555555")
            y += cap_h
        color = sp["color"]
        txt_on = _text_on(color)
        cap = sp["cap"]
        cells = sp["cells"]
        key = sp["key"]
        x = pad
        for c in range(cap):
            draw.rectangle([x, y, x + cell_w, y + num_h], fill=color, outline=grid)
            num = str(c + 1)
            nw, nh = _text_size(draw, num, font_b)
            draw.text((x + (cell_w - nw) / 2, y + (num_h - nh) / 2), num,
                      font=font_b, fill=txt_on)
            x += cell_w
        x = pad
        ny = y + num_h
        for c in range(cap):
            seat = cells[c] if c < len(cells) else None
            reserved = bool(seat and seat.get("reserved"))
            nm = _name_of(seat)
            raw_inst = (seat.get("instrument") or "") if seat else ""
            inst = _inst_label(seat)
            if reserved:
                cell_bg, nm_fill, inst_fill = "#e6ded0", "#8a7a55", "#8a7a55"
            elif color_mode == "section" and seat and raw_inst:
                cell_bg = sc.section_color(raw_inst)
                on = _text_on(cell_bg)
                nm_fill = on
                inst_fill = on
            else:
                cell_bg, nm_fill, inst_fill = "#ffffff", "#000000", "#555555"
            draw.rectangle([x, ny, x + cell_w, ny + name_h], fill=cell_bg, outline=grid)
            if reserved:
                rw, rh = _text_size(draw, "reserved", font_i)
                draw.text((x + (cell_w - rw) / 2, ny + (name_h - rh) / 2), "reserved",
                          font=font_i, fill=nm_fill)
                seat_boxes[(key, c)] = (x // s, ny // s, (x + cell_w) // s, (ny + name_h) // s)
                x += cell_w
                continue
            show_inst = show_instrument and inst and key != "P"
            if nm:
                tw, th = _text_size(draw, nm, font)
                if show_inst:
                    iw, ih = _text_size(draw, inst, font_i)
                    block = th + int(fs_i * 0.3) + ih
                    top = ny + (name_h - block) / 2
                    draw.text((x + (cell_w - tw) / 2, top), nm, font=font, fill=nm_fill)
                    draw.text((x + (cell_w - iw) / 2, top + th + int(fs_i * 0.3)), inst,
                              font=font_i, fill=inst_fill)
                else:
                    draw.text((x + (cell_w - tw) / 2, ny + (name_h - th) / 2), nm,
                              font=font, fill=nm_fill)
            seat_boxes[(key, c)] = (x // s, ny // s, (x + cell_w) // s, (ny + name_h) // s)
            x += cell_w
        y += num_h + name_h + row_gap

    if front_label and flip:
        draw.text((pad, y), front_label, font=font_lbl, fill="#000000")

    if s != 1:
        img = img.resize((width // s, height // s), Image.LANCZOS)
    return img, seat_boxes


def render_arcs(rows, row_caps, palette_on=True, palette=None,
                front_label="CONDUCTOR", flip=False, font_pt=14, percussion=None,
                show_instrument=True, color_mode="row"):
    """Concentric arcs.  By default the front row is innermost (nearest the
    conductor at the bottom-centre) and rows arc upward toward the back; ``flip``
    puts the conductor at the top with rows arcing downward.  Percussion, when
    separated, is drawn as a straight row across the far (back) side."""
    from PIL import Image, ImageDraw

    palette = palette or DEFAULT_PALETTE
    s = _SS
    fs = int(font_pt * 96 / 72 * s)
    pad = int(14 * s)

    scratch = Image.new("RGB", (10, 10), "white")
    d0 = ImageDraw.Draw(scratch)
    fs_i = int(fs * 0.78)
    font = _calibri(fs)
    font_i = _calibri(fs_i)
    font_lbl = _calibri(int(fs * 1.15), bold=True)

    all_names = ([_name_of(x) for row in rows for x in row]
                 + [_name_of(x) for x in (percussion or [])] + ["Wwwww"])
    seat_w = max(_text_size(d0, n, font)[0] for n in all_names) + int(14 * s)
    if show_instrument:
        all_insts = [_inst_label(x) for row in rows for x in row if x] + ["Ww"]
        seat_w = max(seat_w, max(_text_size(d0, i, font_i)[0] for i in all_insts) + int(14 * s))
    seat_w = max(seat_w, int(64 * s))
    seat_h = int(fs * 2.6) if show_instrument else int(fs * 1.9)

    n_rows = len(rows)
    caps = [sc.row_capacity(row_caps, r) for r in range(n_rows)]

    ring_gap = int(seat_h * 2.0)
    span_deg = 140
    span_rad = math.radians(span_deg)
    start_deg = 90 + span_deg / 2

    radii = []
    prev = int(seat_h * 2.0)
    for r in range(n_rows):
        needed = (caps[r] * seat_w * 1.02) / span_rad
        R = max(prev + ring_gap, needed) if r else max(int(seat_h * 2.0), needed)
        radii.append(R)
        prev = R
    r_max = radii[-1] if radii else int(seat_h * 2.0)

    perc = percussion or []
    perc_band = (seat_h * 1.9) if perc else 0    # caption + straight row
    lbl_h = int(fs * 1.7) if front_label else 0

    width = int(max(2 * (r_max + seat_w), len(perc) * seat_w + pad * 2))
    height = int(r_max + seat_h * 2 + pad * 2 + perc_band + lbl_h)
    cx = width / 2

    # ``flip`` True == front of the room at the BOTTOM (conductor bottom, arcs
    # fan upward, percussion straight row across the top).  Matches the rows view.
    d = -1 if flip else 1                         # arc grow direction (screen y)
    if flip:
        cy = height - pad - lbl_h - seat_h / 2     # conductor near bottom
        perc_py = pad + seat_h * 1.5               # percussion across the top
        front_y = height - pad - lbl_h             # front label at very bottom
    else:
        cy = pad + lbl_h + seat_h / 2              # conductor near top
        perc_py = height - pad - seat_h / 2        # percussion across the bottom
        front_y = pad                              # front label at very top

    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    seat_boxes = {}
    grid = "#8f8f8f"

    row_band = (color_mode == "row")
    for r in range(n_rows):
        row = rows[r]
        cap = caps[r]
        color = (palette[r % len(palette)] if row_band else NO_COLOR)
        R = radii[r]
        if cap == 1:
            angles = [90.0]
        else:
            angles = [start_deg - span_deg * (c / (cap - 1)) for c in range(cap)]
        for c in range(cap):
            a = math.radians(angles[c])
            sx = cx + R * math.cos(a)
            sy = cy + d * R * math.sin(a)
            x0, y0 = sx - seat_w / 2, sy - seat_h / 2
            x1, y1 = sx + seat_w / 2, sy + seat_h / 2
            seat = row[c] if c < len(row) else None
            reserved = bool(seat and seat.get("reserved"))
            raw_inst = (seat.get("instrument") or "") if seat else ""
            if reserved:
                fill = "#e6ded0"
            elif color_mode == "section" and seat and raw_inst:
                fill = sc.section_color(raw_inst)
            elif seat:
                fill = color
            else:
                fill = "#ffffff"
            txt_on = _text_on(fill)
            draw.rounded_rectangle([x0, y0, x1, y1], radius=int(8 * s),
                                   fill=fill, outline=grid, width=max(1, s))
            if reserved:
                rl = "reserved"
                rw, rh = _text_size(draw, rl, font_i)
                draw.text((sx - rw / 2, sy - rh / 2), rl, font=font_i, fill="#8a7a55")
                seat_boxes[(r, c)] = (int(x0 // s), int(y0 // s), int(x1 // s), int(y1 // s))
                continue
            nm = _name_of(seat)
            inst = _inst_label(seat)
            if nm and show_instrument and inst:
                tw, th = _text_size(draw, nm, font)
                iw, ih = _text_size(draw, inst, font_i)
                block = th + int(fs_i * 0.25) + ih
                top = sy - block / 2
                draw.text((sx - tw / 2, top), nm, font=font, fill=txt_on)
                draw.text((sx - iw / 2, top + th + int(fs_i * 0.25)), inst, font=font_i, fill=txt_on)
            elif nm:
                tw, th = _text_size(draw, nm, font)
                draw.text((sx - tw / 2, sy - th / 2), nm, font=font, fill=txt_on)
            seat_boxes[(r, c)] = (int(x0 // s), int(y0 // s), int(x1 // s), int(y1 // s))

    # Percussion: a straight row across the far (back) side.
    if perc:
        pcolor = PERC_COLOR if palette_on else NO_COLOR
        ptxt = _text_on(pcolor)
        total_w = len(perc) * seat_w
        px = cx - total_w / 2
        py = perc_py
        cap_font = _calibri(int(fs * 1.0), bold=True)
        cw, _ = _text_size(draw, "Percussion", cap_font)
        draw.text((cx - cw / 2, py - seat_h), "Percussion", font=cap_font, fill="#555555")
        for c, seat in enumerate(perc):
            x0, y0 = px + c * seat_w, py - seat_h / 2
            x1, y1 = x0 + seat_w, py + seat_h / 2
            draw.rounded_rectangle([x0, y0, x1, y1], radius=int(8 * s),
                                   fill=pcolor, outline=grid, width=max(1, s))
            nm = _name_of(seat)
            if nm:
                tw, th = _text_size(draw, nm, font)
                draw.text((x0 + seat_w / 2 - tw / 2, py - th / 2), nm, font=font, fill=ptxt)
            seat_boxes[("P", c)] = (int(x0 // s), int(y0 // s), int(x1 // s), int(y1 // s))

    # Conductor marker.
    cw = int(seat_w * 0.9)
    draw.rounded_rectangle([cx - cw / 2, cy - seat_h / 2, cx + cw / 2, cy + seat_h / 2],
                           radius=int(8 * s), outline="#333333", width=max(1, s))
    cw2, ch2 = _text_size(draw, "Conductor", font_i)
    draw.text((cx - cw2 / 2, cy - ch2 / 2), "Conductor", font=font_i, fill="#333333")

    # Persistent "FRONT OF THE ROOM" label on the front side.
    if front_label:
        tw, th = _text_size(draw, front_label, font_lbl)
        draw.text((cx - tw / 2, front_y), front_label, font=font_lbl, fill="#000000")

    if s != 1:
        img = img.resize((width // s, height // s), Image.LANCZOS)
    return img, seat_boxes
