"""
jazz_icons.py - Small rhythm-section instrument icons for the jazz rotation board.

Each seat name maps to an instrument kind (drums, guitar, bass, vibraphone,
piano) and gets a little icon instead of a colour swatch.  Two sources, in order:

  1. A PNG the teacher dropped in ``assets/jazz/<kind>.png`` (her own artwork —
     e.g. the free icons she pasted in).  Expected files:
         drums.png  guitar.png  bass.png  vibraphone.png  piano.png
  2. A simple built-in line drawing, so icons show even before any file is added.

Icons are cached per Tk toplevel (each window keeps its own PhotoImage refs).
Pure-ish: only touches PIL/Tk when an icon is actually requested.
"""

import os

KINDS = ["drums", "guitar", "bass", "vibraphone", "piano", "congas"]


def icon_kind(seat):
    """Map a seat name to an instrument kind, or None (no icon)."""
    s = (seat or "").lower()
    if "drum" in s or "kit" in s:
        return "drums"
    if "guitar" in s:
        return "guitar"
    if "bass" in s:
        return "bass"
    if "conga" in s or "aux" in s:
        return "congas"
    if any(k in s for k in ("vib", "marimba", "mallet", "bell", "xylo", "glock")):
        return "vibraphone"
    if "piano" in s or "key" in s:
        return "piano"
    if "perc" in s:
        return "congas"
    return None


def _assets_dir():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "jazz")


def _draw(kind, px):
    """A simple monochrome line icon for ``kind`` (fallback artwork)."""
    from PIL import Image, ImageDraw
    s = 4
    W = H = px * s
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    ink = (58, 58, 58, 255)
    lw = max(2, int(W * 0.045))

    def rect(x0, y0, x1, y1, **kw):
        d.rectangle([x0 * W, y0 * H, x1 * W, y1 * H], **kw)

    def line(x0, y0, x1, y1, width=lw):
        d.line([(x0 * W, y0 * H), (x1 * W, y1 * H)], fill=ink, width=width)

    def ellipse(cx, cy, rx, ry, **kw):
        d.ellipse([(cx - rx) * W, (cy - ry) * H, (cx + rx) * W, (cy + ry) * H], **kw)

    if kind == "drums":
        # Two cymbals on stands + a bass drum.
        line(0.30, 0.55, 0.20, 0.92)                     # left stand
        line(0.70, 0.55, 0.80, 0.92)                     # right stand
        ellipse(0.28, 0.30, 0.20, 0.05, fill=ink)        # left cymbal
        ellipse(0.72, 0.30, 0.20, 0.05, fill=ink)        # right cymbal
        ellipse(0.50, 0.66, 0.26, 0.26, outline=ink, width=lw)   # bass drum
        line(0.28, 0.90, 0.24, 0.98)                     # legs
        line(0.72, 0.90, 0.76, 0.98)
    elif kind == "guitar":
        ellipse(0.40, 0.64, 0.24, 0.30, outline=ink, width=lw)   # body
        ellipse(0.40, 0.64, 0.07, 0.07, outline=ink, width=lw)   # sound hole
        line(0.55, 0.52, 0.86, 0.18, width=int(lw * 1.4))        # neck
        rect(0.84, 0.10, 0.94, 0.20, outline=ink, width=lw)      # head
    elif kind == "bass":
        ellipse(0.46, 0.66, 0.24, 0.32, outline=ink, width=lw)   # tall body
        line(0.46, 0.34, 0.50, 0.06, width=int(lw * 1.5))        # long neck
        rect(0.45, 0.02, 0.57, 0.10, outline=ink, width=lw)      # scroll/head
        line(0.34, 0.60, 0.40, 0.72, width=max(2, lw // 2))      # f-hole hint
        line(0.58, 0.60, 0.52, 0.72, width=max(2, lw // 2))
    elif kind == "vibraphone":
        rect(0.12, 0.52, 0.88, 0.60, outline=ink, width=lw)      # frame bar
        for i in range(6):                                       # bars
            x = 0.18 + i * 0.12
            rect(x, 0.40, x + 0.07, 0.52, fill=ink)
        line(0.24, 0.80, 0.24, 0.60)                             # legs
        line(0.76, 0.80, 0.76, 0.60)
        line(0.30, 0.30, 0.42, 0.40, width=max(2, lw // 2))      # mallets
        ellipse(0.29, 0.29, 0.05, 0.05, fill=ink)
        line(0.60, 0.30, 0.48, 0.40, width=max(2, lw // 2))
        ellipse(0.61, 0.29, 0.05, 0.05, fill=ink)
    elif kind == "piano":
        rect(0.14, 0.42, 0.86, 0.72, outline=ink, width=lw)      # keyboard
        for i in range(1, 6):                                    # key lines
            x = 0.14 + i * (0.72 / 6)
            line(x, 0.42, x, 0.72, width=max(2, lw // 2))
        for i in range(6):                                       # black keys
            x = 0.14 + 0.06 + i * (0.72 / 6)
            rect(x, 0.42, x + 0.05, 0.58, fill=ink)
    elif kind == "congas":
        for cx in (0.36, 0.64):                                  # two cone drums
            d.polygon([(cx - 0.14) * W, 0.30 * H, (cx + 0.14) * W, 0.30 * H,
                       (cx + 0.10) * W, 0.86 * H, (cx - 0.10) * W, 0.86 * H],
                      outline=ink, width=lw)
            ellipse(cx, 0.30, 0.14, 0.05, outline=ink, width=lw)
    else:
        return None
    return img.resize((px, px), Image.LANCZOS)


def icon(widget, seat, px=20):
    """A cached PhotoImage for ``seat``'s instrument, or None if no kind matches
    or PIL/Tk is unavailable.  Prefers ``assets/jazz/<kind>.png``, else a drawing."""
    kind = icon_kind(seat)
    if not kind:
        return None
    top = widget.winfo_toplevel()
    cache = getattr(top, "_jazz_icons", None)
    if cache is None:
        cache = {}
        top._jazz_icons = cache
    if kind in cache:
        return cache[kind]
    photo = None
    try:
        from PIL import Image, ImageTk
        img = None
        path = os.path.join(_assets_dir(), kind + ".png")
        if os.path.exists(path):
            im = Image.open(path).convert("RGBA")
            im.thumbnail((px, px), Image.LANCZOS)
            img = im
        if img is None:
            img = _draw(kind, px)
        if img is not None:
            photo = ImageTk.PhotoImage(img, master=top)
    except Exception:
        photo = None
    cache[kind] = photo
    return photo
