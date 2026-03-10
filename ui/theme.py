"""
ui/theme.py - Global display preferences: theme name and font scale.

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

LARGE_FONT_SCALE = 1.25
EXTRA_LARGE_FONT_SCALE = 1.5

_DARK_THEMES = {"darkly", "superhero", "cyborg", "vapor", "solar", "slate"}

# ── Runtime state ─────────────────────────────────────────────────────────────

_font_scale: float = 1.0
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
    """Return base_size scaled by the current font scale setting."""
    return max(6, round(base_size * _font_scale))


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

def muted_fg() -> str:
    """Muted secondary text (e.g. subtitles, helper text, column headers)."""
    return "#e0e0e0" if is_dark() else "#666666"


def subtle_fg() -> str:
    """Very subtle text (e.g. footer, separators, timestamps)."""
    return "#bbbbbb" if is_dark() else "#999999"


def fg() -> str:
    """Standard body text color (adapts to dark/light)."""
    return "#dddddd" if is_dark() else "#222222"


def link_fg() -> str:
    """Hyperlink / action label color."""
    return "#6ab0f5" if is_dark() else "#4A90D9"


def file_selected_fg() -> str:
    """Foreground for a selected/filled filename label."""
    return "#dddddd" if is_dark() else "#000000"


# ── Startup application ───────────────────────────────────────────────────────

def fit_window(win, min_w: int = 200, min_h: int = 200, margin: int = 80):
    """Size a Toplevel to fit its content, then center it on screen.
    Uses the larger of the measured required size and min_w/min_h, capped at
    screen size minus margin. Call this AFTER all widgets have been added.
    """
    win.update_idletasks()
    sw = win.winfo_screenwidth()
    sh = win.winfo_screenheight()
    w = min(max(min_w, win.winfo_reqwidth()), sw - margin)
    h = min(max(min_h, win.winfo_reqheight()), sh - margin)
    x = (sw - w) // 2
    y = max(0, (sh - h) // 2)
    win.geometry(f"{w}x{h}+{x}+{y}")


def apply_global_font_scaling():
    """
    Scale all named tkinter fonts and set the ttkbootstrap style default font.
    Must be called after the Tk root window exists.
    """
    if _font_scale == 1.0:
        return

    import tkinter.font as tkfont
    for name in tkfont.names():
        try:
            f = tkfont.nametofont(name)
            size = abs(f.cget("size"))
            if size > 0:
                f.configure(size=max(6, round(size * _font_scale)))
        except Exception:
            pass

    # Configure ttkbootstrap default font so ttk widgets (entries, comboboxes,
    # treeview rows) also pick up the larger size.
    try:
        import ttkbootstrap as ttk
        style = ttk.Style()
        base = round(9 * _font_scale)
        style.configure(".", font=("Segoe UI", base))
    except Exception:
        pass
