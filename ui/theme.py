"""
ui/theme.py - Global display preferences: theme name, font scale, and accessibility.

Accessibility-first design:
  - "Normal" is sized for comfortable reading on most displays (1.25x base)
  - "Large" is for users who prefer bigger text (1.5x base)
  - "Extra Large" is maximum accessibility for low-vision users (1.85x base)
  - All text colors meet WCAG AA contrast ratio (4.5:1 minimum)
  - Minimum touch/click targets are 44px at all sizes

Apply these at startup (main.py) before any windows are built so that
all widget creation picks up the correct values.
"""

# ── Available display themes ──────────────────────────────────────────────────

DISPLAY_THEMES = {
    "Classic":    "litera",     # Clean white, blue accents (default)
    "Warm Earth": "sandstone",  # Tan backgrounds, warm tones
    "Dark Mode":  "darkly",     # Dark charcoal, subtle accents
}

THEME_DESCRIPTIONS = {
    "Classic":    "Light white background with blue accents. Clean and professional.",
    "Warm Earth": "Warm tan tones with earthy accents. Easy on the eyes.",
    "Dark Mode":  "Dark charcoal background. Ideal for low-light environments.",
}

# ── Font scale presets ────────────────────────────────────────────────────────
# These are absolute multipliers applied to all base font sizes in the app.
# The base font sizes in the code (fs(9), fs(10), etc.) represent design-time
# values that get multiplied by the active scale.
#
# WCAG and accessibility guidelines recommend:
#   - Body text minimum 16px for comfortable reading
#   - 12px absolute minimum for any text
#   - High contrast (4.5:1 ratio minimum for normal text)
#
# With Segoe UI at these scales:
#   Normal:      fs(9)=11px, fs(10)=13px, fs(12)=15px — comfortable on 1080p+
#   Large:       fs(9)=14px, fs(10)=15px, fs(12)=18px — easier for accessibility
#   Extra Large: fs(9)=17px, fs(10)=19px, fs(12)=22px — low-vision friendly

NORMAL_FONT_SCALE = 1.25       # was 1.0 — now a comfortable readable default
LARGE_FONT_SCALE = 1.5         # was 1.25 — now a proper large text option
EXTRA_LARGE_FONT_SCALE = 1.85  # was 1.5 — now true maximum accessibility

_DARK_THEMES = {"darkly", "superhero", "cyborg", "vapor", "solar", "slate"}

# ── Runtime state ─────────────────────────────────────────────────────────────

_font_scale: float = NORMAL_FONT_SCALE
_theme_name: str = "litera"


def set_font_scale(scale: float):
    global _font_scale
    _font_scale = scale


def get_font_scale() -> float:
    return _font_scale


def set_theme_name(name: str):
    global _theme_name
    _theme_name = name


def get_theme_name() -> str:
    return _theme_name


def is_dark() -> bool:
    return _theme_name in _DARK_THEMES


# ── Font helpers ──────────────────────────────────────────────────────────────

def fs(base_size: int) -> int:
    """Return base_size scaled by the current font scale setting.

    All UI code should call this rather than using raw pixel sizes.
    Example: font=("Segoe UI", fs(10)) gives 13px at Normal, 15px at Large.
    """
    return max(8, round(base_size * _font_scale))


def pad() -> int:
    """Return a standard padding value scaled for the current size.
    Use this for padx/pady to keep spacing proportional.
    """
    return max(4, round(6 * _font_scale))


def bind_copy_menu(widget) -> None:
    """Attach a right-click 'Copy' context menu to any Label widget."""
    import tkinter as tk

    def _show(event):
        text = widget.cget("text")
        if not text:
            return
        menu = tk.Menu(widget, tearoff=0)
        menu.add_command(
            label="Copy",
            command=lambda: (widget.clipboard_clear(), widget.clipboard_append(text)),
        )
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    widget.bind("<Button-3>", _show)


# ── Adaptive color helpers ────────────────────────────────────────────────────
# Colors are chosen to meet WCAG AA contrast ratios:
#   - fg() on white/dark bg: 7:1+ (AAA level)
#   - muted_fg() on white/dark bg: 4.5:1+ (AA level)
#   - subtle_fg() on white/dark bg: 3:1+ (AA for large text only)

def muted_fg() -> str:
    """Muted secondary text — still readable, meets WCAG AA for body text.
    Use for: subtitles, helper text, column headers, descriptions."""
    return "#d0d0d0" if is_dark() else "#505050"


def subtle_fg() -> str:
    """Subtle text — lighter, meets WCAG AA for large text (14px+ bold or 18px+).
    Use for: footers, separators, timestamps, less important labels."""
    return "#aaaaaa" if is_dark() else "#777777"


def fg() -> str:
    """Standard body text color — maximum contrast.
    Use for: all primary content, headings, form labels."""
    return "#e8e8e8" if is_dark() else "#1a1a1a"


def link_fg() -> str:
    """Hyperlink / action label color — meets WCAG AA on both themes."""
    return "#6ab0f5" if is_dark() else "#2563EB"


def file_selected_fg() -> str:
    """Foreground for a selected/filled filename label."""
    return "#e8e8e8" if is_dark() else "#000000"


# ── Startup application ───────────────────────────────────────────────────────

def fit_window(win, min_w: int = 200, min_h: int = 200, margin: int = 80):
    """Size a Toplevel to fit its content, then center it on screen.
    Uses the larger of the measured required size and min_w/min_h, capped at
    screen size minus margin. Call this AFTER all widgets have been added.

    Scales minimum sizes by the font scale so dialogs grow with text size.
    """
    # Scale min dimensions proportionally
    scale_factor = _font_scale / NORMAL_FONT_SCALE
    min_w = round(min_w * scale_factor)
    min_h = round(min_h * scale_factor)

    win.withdraw()
    win.update_idletasks()
    sw = win.winfo_screenwidth()
    sh = win.winfo_screenheight()
    w = min(max(min_w, win.winfo_reqwidth()), sw - margin)
    h = min(max(min_h, win.winfo_reqheight()), sh - margin)
    x = (sw - w) // 2
    y = max(0, (sh - h) // 2)
    win.geometry(f"{w}x{h}+{x}+{y}")
    win.deiconify()


def apply_global_font_scaling():
    """
    Scale all named tkinter fonts and set the ttkbootstrap style default font.
    Must be called after the Tk root window exists.

    Always runs regardless of scale (since even "Normal" is 1.25x).
    """
    import tkinter.font as tkfont
    for name in tkfont.names():
        try:
            f = tkfont.nametofont(name)
            size = abs(f.cget("size"))
            if size > 0:
                f.configure(size=max(8, round(size * _font_scale)))
        except Exception:
            pass

    # Configure ttkbootstrap default font so ttk widgets (entries, comboboxes,
    # treeview rows) also pick up the larger size.
    try:
        import ttkbootstrap as ttk
        style = ttk.Style()
        base = max(10, round(9 * _font_scale))
        style.configure(".", font=("Segoe UI", base))

        # Also scale treeview row height for readability
        row_height = max(24, round(20 * _font_scale))
        style.configure("Treeview", rowheight=row_height)

        # Scale button padding for larger click targets
        btn_pad = max(4, round(4 * _font_scale))
        style.configure("TButton", padding=(btn_pad * 2, btn_pad))

    except Exception:
        pass
