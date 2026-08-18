"""
ui/help_system.py - The ? button, and the help page behind it.

Every main window carries a ? in its top-right corner.  Pressing it (or F1)
opens the user guide in the teacher's normal web browser, scrolled to the
section for the window they were looking at — so help arrives already on the
right page rather than at a table of contents.

The guide is one self-contained HTML file, ``help/roka_help.html``.  A browser
is used rather than a Tk window on purpose: teachers already know how to scroll,
search, follow links, zoom and print in a browser, and the guide stays readable
even if the program itself is misbehaving.
"""

import os
import sys
import webbrowser

import ttkbootstrap as ttk
from ttkbootstrap.constants import *

# Where bug reports and feature requests go.  One place, so it can be changed
# for another district without hunting through the code.
SUPPORT_EMAIL = "MangumM@bsd405.org"

HELP_FILE = os.path.join("help", "roka_help.html")


def _app_root() -> str:
    """The folder the program's own files live in.

    Frozen, that is PyInstaller's bundle directory; from source, the project
    folder two levels up from this module."""
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def help_file_path() -> str:
    """The guide on disk, or "" when it is missing from the install."""
    for root in (_app_root(), os.path.dirname(os.path.abspath(sys.argv[0]))):
        candidate = os.path.join(root, HELP_FILE)
        if os.path.exists(candidate):
            return candidate
    return ""


def open_help(topic="", parent=None):
    """Open the guide at *topic* (a section id), or at the top when blank.

    *topic* may be a function returning the id, for a window whose subject
    changes as the teacher moves around it (Teacher Tools, whose ? should land
    on the tab they are actually looking at)."""
    if callable(topic):
        try:
            topic = topic() or ""
        except Exception:
            topic = ""
    path = help_file_path()
    if not path:
        try:
            from ttkbootstrap.dialogs import Messagebox
            Messagebox.show_warning(
                "The help guide couldn't be found in this installation.\n\n"
                f"Email {SUPPORT_EMAIL} and it can be sent to you directly.",
                title="Help Not Found", parent=parent)
        except Exception:
            pass
        return
    url = "file:///" + path.replace("\\", "/").lstrip("/")
    if topic:
        url += "#" + topic
    _open_url(url)


def _open_url(url: str):
    """Open *url* in the teacher's own browser, fragment and all.

    webbrowser hands a Windows machine to os.startfile, which is ShellExecute,
    which throws away the #section on a file: URL — every ? then landed on the
    top of the guide no matter which window it was pressed in.  Handing the URL
    to the browser as an argument instead keeps it, so the default browser is
    looked up and launched directly, with webbrowser as the fallback."""
    argv = _default_browser_argv(url)
    if argv:
        try:
            import subprocess
            subprocess.Popen(argv, close_fds=True)
            return
        except Exception:
            pass
    try:
        webbrowser.open(url)
    except Exception:
        pass


def _default_browser_argv(url: str):
    """The command line for whichever browser this user has chosen, or None.

    Read from the same registry keys Windows itself uses for "open a link",
    so this follows the teacher's default browser rather than picking one."""
    if not sys.platform.startswith("win"):
        return None
    try:
        import winreg
    except ImportError:
        return None

    command = ""
    try:
        for protocol in ("https", "http"):
            try:
                with winreg.OpenKey(
                        winreg.HKEY_CURRENT_USER,
                        r"Software\Microsoft\Windows\Shell\Associations"
                        rf"\UrlAssociations\{protocol}\UserChoice") as key:
                    prog_id = winreg.QueryValueEx(key, "ProgId")[0]
                with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT,
                                    prog_id + r"\shell\open\command") as key:
                    command = winreg.QueryValueEx(key, "")[0]
                if command:
                    break
            except OSError:
                continue
    except Exception:
        return None
    if not command:
        return None

    import shlex
    try:
        parts = [p.strip('"') for p in shlex.split(command, posix=False)]
    except ValueError:
        return None
    if not parts or not os.path.exists(parts[0]):
        return None

    argv, substituted = [], False
    for part in parts:
        if "%1" in part:
            argv.append(part.replace("%1", url))
            substituted = True
        else:
            argv.append(part)
    if not substituted:
        argv.append(url)
    return argv


def add_help_button(header, topic="", dark: bool = True, pady: int = 8,
                    padx=(0, 12)):
    """Put the ? in the top-right of *header* and return it.

    Pack it BEFORE any other right-hand widget in that header, or it lands to
    the left of them instead of in the corner.  ``dark`` styles it for the
    coloured title bars most windows use; pass False on a plain background.
    """
    btn = ttk.Button(header, text="?", width=3,
                     bootstyle=(LIGHT if dark else (SECONDARY, OUTLINE)),
                     command=lambda: open_help(topic, header))
    _enlarge(btn)
    btn.pack(side=RIGHT, padx=padx, pady=pady)
    _bind_f1(header, topic)
    try:
        from ttkbootstrap.tooltip import ToolTip
        ToolTip(btn, text="Help for this screen  (F1)", bootstyle=(INFO, INVERSE))
    except Exception:
        pass
    return btn


def _enlarge(btn):
    """Give the ? a bigger, bolder glyph than a normal button label.

    ttk keeps the font in the style, not on the widget, so this derives a style
    from whichever bootstyle the button already has: "Help.light.TButton" falls
    back to "light.TButton" for every colour, and only the font is overridden.

    The padding is tightened to pay for the bigger glyph.  The result is the
    same width as an ordinary button and a few pixels taller, so a header or a
    toolbar keeps its shape while the ? stops looking like fine print.
    """
    try:
        import tkinter.ttk as _ttk
        from ui.theme import fs
        base = btn.cget("style") or "TButton"
        name = f"Help.{base}"
        _ttk.Style().configure(name, font=("Segoe UI", fs(12), "bold"),
                               padding=(4, 1))
        btn.configure(style=name)
    except Exception:
        pass


def _bind_f1(widget, topic=""):
    """F1 anywhere in this window opens the same page the ? does.

    Bound to the window, not with bind_all: Tk sends an unhandled key up
    through the widget's bindtags to its toplevel, so this catches F1 pressed
    in any child while leaving every OTHER window's F1 pointing at its own
    section.  bind_all would give whichever window opened last the F1 key for
    the whole program."""
    try:
        window = widget.winfo_toplevel()
        window.bind("<F1>", lambda e: open_help(topic, window), add="+")
    except Exception:
        pass


def attach_help(window, topic: str = ""):
    """F1 only, for a window with no header bar to hang a button on."""
    _bind_f1(window, topic)


# ── Reporting a bug / asking for a feature ───────────────────────────────────
# Both open a message in whatever the teacher's default mail program is, which
# on a district machine is Outlook.  A mailto link is used rather than driving
# Outlook directly because it works the same way from the help page in the
# browser, needs nothing installed, and can't leave a half-built message behind.
# Outlook cannot be made to attach a file this way, so the template asks for the
# screenshot in words instead.

_BUG_BODY = """Please describe the problem, then attach your screenshot.

WHAT SCREEN WERE YOU ON?
(for example: Equipment, Teacher Tools > Seating Charts)

WHAT DID YOU DO, STEP BY STEP?
1.
2.
3.

WHAT DID YOU EXPECT TO HAPPEN?


WHAT HAPPENED INSTEAD?


DOES IT HAPPEN EVERY TIME?


-- PLEASE ATTACH A SCREENSHOT --
Press the Windows key + Shift + S, drag a box around the problem, then
press Ctrl+V here to paste the picture into this email.

------------------------------
Sent from Roka's Resonance{version}{screen}
"""

_FEATURE_BODY = """Please describe what you need, in as much detail as you can.

WHAT DO YOU WANT TO BE ABLE TO DO?


HOW DO YOU DO IT TODAY (on paper, in a spreadsheet, in another program)?


WHO WOULD USE IT, AND HOW OFTEN?


WHAT WOULD IT SAVE YOU?


ANYTHING ELSE THAT WOULD HELP (examples, a sample of the form or sheet
you use now, a screenshot of how another program does it):


Please note: to stay within student privacy law, Roka is not going to hold
sensitive student data or detailed instructional modifications. Anything in
that area can only ever be handled in a very general way.

------------------------------
Sent from Roka's Resonance{version}{screen}
"""


def _mailto(subject: str, body: str) -> str:
    from urllib.parse import quote
    return (f"mailto:{SUPPORT_EMAIL}?subject={quote(subject)}"
            f"&body={quote(body)}")


def report_bug(screen: str = "", version: str = "", parent=None):
    """Start a bug report in Outlook, pre-filled with what to include."""
    body = _BUG_BODY.format(
        version=f"  ({version})" if version else "",
        screen=f"\nScreen: {screen}" if screen else "")
    _launch_mail(_mailto("Roka's Resonance: bug report", body), parent)


def request_feature(screen: str = "", version: str = "", parent=None):
    """Start a feature request in Outlook, pre-filled with what to include."""
    body = _FEATURE_BODY.format(
        version=f"  ({version})" if version else "",
        screen=f"\nScreen: {screen}" if screen else "")
    _launch_mail(_mailto("Roka's Resonance: feature request", body), parent)


def _launch_mail(url: str, parent=None):
    try:
        webbrowser.open(url)
    except Exception:
        try:
            from ttkbootstrap.dialogs import Messagebox
            Messagebox.show_warning(
                "Your email program couldn't be opened automatically.\n\n"
                f"Please email {SUPPORT_EMAIL} directly.",
                title="Couldn't Open Email", parent=parent)
        except Exception:
            pass
