"""
email_launcher.py - Open a filled-in message in the teacher's mail program.

Every "email template" screen in Roka used to end at the clipboard: copy the
subject, switch to Outlook, paste, copy the addresses, paste them into BCC,
copy the body, paste that.  Five steps to send one reminder, and the addresses
are the step people get wrong.  This hands the whole message to Outlook already
built, with one press.

Families always go in BCC, never in To.  A class list pasted into To shows every
family every other family's address, which is both a privacy problem and the
thing a parent notices first.  The teacher's own address goes in To instead, so
the message is addressed to somebody, it lands in their own inbox as a record of
exactly what went out, and a stray Reply All reaches the teacher rather than two
hundred families.

Two ways of doing it, in order:

  1. Outlook itself, through COM.  No length limit, real BCC, and the message
     opens in the compose window for a last read before it goes.
  2. A mailto: link, for a machine without Outlook.  Windows caps these at
     around 2000 characters, so a long recipient list would be cut in half
     silently; when that would happen the addresses go to the clipboard instead
     and the teacher is told to paste them.

Nothing here ever sends.  The message is opened for the teacher to read and
send themselves.
"""

import os
import sys
import webbrowser
from urllib.parse import quote

# Windows hands a mailto: link to the shell, which stops reading at about 2 KB.
# Staying under it matters more than squeezing every address in: a truncated
# BCC means some families silently never got the email.
_MAILTO_LIMIT = 1800


def _join(addresses) -> str:
    """Outlook separates addresses with semicolons."""
    if isinstance(addresses, str):
        return addresses.strip()
    return "; ".join(a.strip() for a in (addresses or []) if a and a.strip())


def compose(to="", bcc="", subject="", body="", cc="", parent=None) -> str:
    """Open a new message, filled in.  Returns how it was opened:

    "outlook"   - opened in Outlook, everything in place
    "mailto"    - opened in the default mail program
    "clipboard" - too long for a mailto link, so the addresses were copied and
                  the caller should say so
    ""          - nothing worked
    """
    to, cc, bcc = _join(to), _join(cc), _join(bcc)
    subject = (subject or "").strip()
    body = body or ""

    if _open_in_outlook(to, cc, bcc, subject, body):
        return "outlook"

    link = _mailto_link(to, cc, bcc, subject, body)
    if len(link) <= _MAILTO_LIMIT:
        if _shell_open(link):
            return "mailto"
        return ""

    # Too long: send without the recipient list, and put it on the clipboard so
    # it can be pasted into BCC.  Better than a list cut off half way.
    short = _mailto_link(to, cc, "", subject, body)
    if len(short) <= _MAILTO_LIMIT and _shell_open(short):
        _to_clipboard(bcc, parent)
        return "clipboard"
    if _shell_open(_mailto_link(to, "", "", subject, "")):
        _to_clipboard(bcc, parent)
        return "clipboard"
    return ""


def _open_in_outlook(to, cc, bcc, subject, body) -> bool:
    """Build the message in Outlook itself.  False if Outlook isn't here."""
    if not sys.platform.startswith("win"):
        return False
    try:
        import pythoncom
        import win32com.client
    except ImportError:
        return False
    try:
        # Tk's thread has no COM apartment of its own until something asks.
        try:
            pythoncom.CoInitialize()
        except Exception:
            pass
        # Dispatch, not DispatchEx: Outlook is meant to run as one instance, and
        # this attaches to the copy the teacher already has open.
        outlook = win32com.client.Dispatch("Outlook.Application")
        mail = outlook.CreateItem(0)          # 0 = olMailItem
        if to:
            mail.To = to
        if cc:
            mail.CC = cc
        if bcc:
            mail.BCC = bcc
        mail.Subject = subject
        mail.Body = body
        mail.Display(False)                   # show it; False = don't go modal
        return True
    except Exception:
        return False


def _mailto_link(to, cc, bcc, subject, body) -> str:
    params = []
    for name, value in (("cc", cc), ("bcc", bcc),
                        ("subject", subject), ("body", body)):
        if value:
            params.append(f"{name}={quote(value)}")
    link = "mailto:" + quote(to)
    if params:
        link += "?" + "&".join(params)
    return link


def _shell_open(link: str) -> bool:
    """Hand a mailto: link to whatever program handles mail on this machine."""
    try:
        if sys.platform.startswith("win"):
            os.startfile(link)
        else:
            webbrowser.open(link)
        return True
    except Exception:
        try:
            webbrowser.open(link)
            return True
        except Exception:
            return False


def _to_clipboard(text: str, parent=None):
    if not text or parent is None:
        return
    try:
        parent.clipboard_clear()
        parent.clipboard_append(text)
        parent.update_idletasks()
    except Exception:
        pass


def teacher_address(base_dir: str) -> str:
    """The teacher's own address, for the To line, from Settings."""
    try:
        from ui.settings_dialog import load_settings
        return ((load_settings(base_dir).get("teacher") or {})
                .get("email") or "").strip()
    except Exception:
        return ""
