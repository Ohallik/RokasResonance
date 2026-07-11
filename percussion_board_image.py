"""
percussion_board_image.py - Render a percussion rotation board to an image and
put it on the Windows clipboard, so it can be pasted into PowerPoint / Word /
OneNote looking like the teacher's projected board:

    * a circular rotation icon with the day number beside it
    * player names down the left column
    * each player's station down the right column, colour-coded by station type
    * Calibri, ~14 pt

If the teacher drops their own icon at ``assets/rotation_icon.png`` it is used;
otherwise a clean double-arrow facsimile is drawn.
"""

import io
import math
import os

# Supersample factor for crisp, anti-aliased text (rendered big, scaled down).
_SS = 3


def _calibri(size, bold=False):
    from PIL import ImageFont
    names = (["calibrib.ttf", "calibri.ttf"] if bold else ["calibri.ttf"])
    for n in names:
        for path in (n, os.path.join(r"C:\Windows\Fonts", n)):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    from PIL import ImageFont as _F
    return _F.load_default()


def _text_size(draw, text, font):
    l, t, r, b = draw.textbbox((0, 0), text, font=font)
    return r - l, b - t


def _draw_arrowhead(draw, tip, direction, size, color):
    dx, dy = direction
    mag = math.hypot(dx, dy) or 1.0
    ux, uy = dx / mag, dy / mag           # unit along travel
    px, py = -uy, ux                      # perpendicular
    back_x, back_y = tip[0] - ux * size, tip[1] - uy * size
    p1 = (back_x + px * size * 0.6, back_y + py * size * 0.6)
    p2 = (back_x - px * size * 0.6, back_y - py * size * 0.6)
    draw.polygon([tip, p1, p2], fill=color)


def _draw_mallet_glyph(draw, box, family):
    """Small crossed-mallets glyph inside box: warm red heads for yarn
    mallets (marimba, vibraphone), white heads for rubber/plastic (xylophone,
    bells) — the same visual cue as on the app's board."""
    x0, y0, x1, y1 = box
    W, H = x1 - x0, y1 - y0
    sw = max(2, int(W * 0.10))
    stick = (70, 70, 70)
    draw.line([(x0 + W * 0.22, y0 + H * 0.90), (x0 + W * 0.64, y0 + H * 0.34)],
              fill=stick, width=sw)
    draw.line([(x0 + W * 0.78, y0 + H * 0.90), (x0 + W * 0.36, y0 + H * 0.34)],
              fill=stick, width=sw)
    if family == "yarn":
        head, hi = (211, 78, 55), (242, 150, 120)
    else:
        head, hi = (232, 232, 235), (255, 255, 255)
    r = int(W * 0.18)
    for cx, cy in [(x0 + W * 0.64, y0 + H * 0.30), (x0 + W * 0.36, y0 + H * 0.30)]:
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=head,
                     outline=(60, 60, 60), width=max(1, sw // 2))
        draw.ellipse([cx - r * 0.5, cy - r * 0.5, cx + r * 0.1, cy + r * 0.1],
                     fill=hi)


def _mallet_family(station):
    try:
        import percussion_rotation as pr
        return pr.mallet_family(station)
    except Exception:
        return None


def _draw_rotation_icon(img, box, color):
    """Draw a double-arrow 'rotation' glyph inside box=(x0,y0,x1,y1)."""
    from PIL import ImageDraw
    draw = ImageDraw.Draw(img)
    x0, y0, x1, y1 = box
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    r = (min(x1 - x0, y1 - y0) / 2) * 0.72
    width = max(2, int(r * 0.22))
    arc_box = (cx - r, cy - r, cx + r, cy + r)

    def pt(deg):
        a = math.radians(deg)
        return (cx + r * math.cos(a), cy + r * math.sin(a))

    # Two arcs leaving gaps at the 0 and 180 positions.
    draw.arc(arc_box, start=20, end=160, fill=color, width=width)
    draw.arc(arc_box, start=200, end=340, fill=color, width=width)
    head = r * 0.55
    for end_deg in (160, 340):
        tip = pt(end_deg + 6)
        prev = pt(end_deg - 10)
        direction = (tip[0] - prev[0], tip[1] - prev[1])
        _draw_arrowhead(draw, tip, direction, head, color)


def render_board(day_number, rows, color_for, section_name="",
                 icon_path=None, font_pt=14):
    """Return a PIL.Image of the rotation board.

    rows: list of (name, station).  color_for: station -> hex bg colour.
    """
    from PIL import Image, ImageDraw

    s = _SS
    fs = int(font_pt * 96 / 72 * s)          # px at 96dpi, supersampled
    pad = int(10 * s)
    row_h = int(fs * 1.9)
    cell_pad = int(10 * s)

    scratch = Image.new("RGB", (10, 10), "white")
    d0 = ImageDraw.Draw(scratch)
    font = _calibri(fs)
    font_b = _calibri(fs, bold=True)
    font_day = _calibri(int(fs * 1.9), bold=True)

    # Column widths from content.
    name_w = max([_text_size(d0, n, font_b)[0] for n, _ in rows] + [_text_size(d0, "Player", font_b)[0]])
    stn_w = max([_text_size(d0, st, font)[0] for _, st in rows] + [_text_size(d0, "Drum set", font)[0]])
    name_w += cell_pad * 2
    # Room for a mallet-type glyph in front of mallet-instrument names.
    glyph_w = int(fs * 1.7)
    stn_w += cell_pad * 2 + glyph_w
    table_w = name_w + stn_w

    # Header holds the icon + day number.
    icon_sz = int(fs * 2.6)
    day_text = str(day_number)
    day_w, day_h = _text_size(d0, day_text, font_day)
    header_h = max(icon_sz, day_h) + pad
    cap_font = _calibri(int(fs * 1.15), bold=True)
    cap_h = (int(fs * 1.4) + pad) if section_name else 0
    cap_w = _text_size(d0, section_name, cap_font)[0] if section_name else 0

    W = pad * 2 + max(table_w, icon_sz + int(fs) + day_w + pad, cap_w)
    H = pad + cap_h + header_h + row_h * len(rows) + pad

    img = Image.new("RGB", (W, H), "white")
    draw = ImageDraw.Draw(img)
    navy = "#14477d"

    y = pad
    if section_name:
        draw.text((pad, y), section_name, font=cap_font, fill="#333333")
        y += cap_h

    # Icon + day number.
    icon_box = (pad, y, pad + icon_sz, y + icon_sz)
    used_custom = False
    if icon_path and os.path.exists(icon_path):
        try:
            ic = Image.open(icon_path).convert("RGBA").resize((icon_sz, icon_sz))
            img.paste(ic, (pad, y), ic)
            used_custom = True
        except Exception:
            used_custom = False
    if not used_custom:
        _draw_rotation_icon(img, icon_box, navy)
    draw.text((pad + icon_sz + int(fs * 0.6), y + (icon_sz - day_h) / 2),
              day_text, font=font_day, fill=navy)
    y += header_h

    # Table.
    grid = "#c9c9c9"
    for name, station in rows:
        bg = color_for(station) or "#ffffff"
        draw.rectangle([pad, y, pad + name_w, y + row_h], fill="#ffffff", outline=grid)
        draw.rectangle([pad + name_w, y, pad + table_w, y + row_h], fill=bg, outline=grid)
        nw, nh = _text_size(draw, name, font_b)
        draw.text((pad + cell_pad, y + (row_h - nh) / 2), name, font=font_b, fill="#000000")
        sx = pad + name_w + cell_pad
        fam = _mallet_family(station)
        if fam:
            gsz = int(row_h * 0.62)
            gy = y + (row_h - gsz) / 2
            _draw_mallet_glyph(draw, (sx, gy, sx + gsz, gy + gsz), fam)
            sx += gsz + int(cell_pad * 0.7)
        sw, sh = _text_size(draw, station, font)
        draw.text((sx, y + (row_h - sh) / 2), station, font=font, fill="#000000")
        y += row_h

    if s != 1:
        img = img.resize((W // s, H // s), Image.LANCZOS)
    return img


def copy_image_to_clipboard(img):
    """Put a PIL image on the Windows clipboard as a DIB. Returns True on success."""
    try:
        import win32clipboard
    except Exception:
        return False
    output = io.BytesIO()
    img.convert("RGB").save(output, "BMP")
    data = output.getvalue()[14:]     # strip 14-byte BMP file header -> DIB
    output.close()
    try:
        win32clipboard.OpenClipboard()
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardData(win32clipboard.CF_DIB, data)
        win32clipboard.CloseClipboard()
        return True
    except Exception:
        try:
            win32clipboard.CloseClipboard()
        except Exception:
            pass
        return False


def copy_board(day_number, rows, color_for, section_name="", icon_path=None, font_pt=14):
    """Render + copy in one call. Returns True if the image reached the clipboard."""
    img = render_board(day_number, rows, color_for, section_name=section_name,
                        icon_path=icon_path, font_pt=font_pt)
    return copy_image_to_clipboard(img)
