"""
ui/email_compose.py - The "Open in Outlook" button behind every email template.

Roka's editor stays the place the wording lives.  Pressing the button saves
whatever is in the box as this concert's or trip's template, then hands that
same text to Outlook.  So the reusable version is always the last thing that
actually went out, with no separate save step to forget.

Anything the teacher then changes inside Outlook is for that one message.  That
is the right default, since a lot of last-minute edits are "and Priya's mum is
driving", not wording worth keeping.  When it IS worth keeping, the note under
the button says to paste it back into Roka.
"""

import tkinter as tk
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from ttkbootstrap.dialogs import Messagebox

import email_launcher


def _ask_for_address(window, base_dir) -> str:
    """First time out, collect the teacher's own address and keep it.

    Asked here rather than left to Settings because this is the moment it is
    needed, and an empty To line is how a teacher ends up with no record of
    what they sent."""
    import tkinter.simpledialog as sd
    from ui.settings_dialog import load_settings, save_settings
    entered = sd.askstring(
        "Your Email Address",
        "Roka puts families in BCC and you in the To line, so you get your own "
        "copy of what went out.\n\nYour email address:",
        parent=window)
    if not entered or "@" not in entered:
        return ""
    entered = entered.strip()
    try:
        settings = load_settings(base_dir)
        settings.setdefault("teacher", {})["email"] = entered
        save_settings(base_dir, settings)
    except Exception:
        pass
    return entered


def open_message(window, base_dir, subject, body, bcc=(), saved_note=""):
    """Open the finished message in Outlook, and say what happened.

    ``bcc`` is the family/chaperone list.  It never goes in To: a class list in
    the To line shows every family every other family's address."""
    to = email_launcher.teacher_address(base_dir)
    if not to:
        to = _ask_for_address(window, base_dir)

    how = email_launcher.compose(to=to, bcc=bcc, subject=subject, body=body,
                                 parent=window)
    count = len([a for a in (bcc or []) if a])
    if how == "outlook":
        return (f"✓ Opened in Outlook, {count} address(es) in BCC."
                + (f" {saved_note}" if saved_note else ""))
    if how == "mailto":
        return (f"✓ Opened in your email program, {count} address(es) in BCC."
                + (f" {saved_note}" if saved_note else ""))
    if how == "clipboard":
        Messagebox.show_info(
            f"The message is open in your email program, but the {count} "
            "addresses were too long to pass across in one go.\n\n"
            "They have been copied instead: click into the BCC line and press "
            "Ctrl+V.",
            title="Paste the addresses into BCC", parent=window)
        return f"✓ Opened. {count} address(es) copied, paste them into BCC."
    Messagebox.show_warning(
        "Your email program couldn't be opened automatically.\n\n"
        "Use the copy buttons instead, and paste into a new message.",
        title="Couldn't Open Email", parent=window)
    return ""


def add_send_button(parent_row, window, base_dir, get_subject, get_body,
                    get_bcc, on_before_send=None, flash=None,
                    saved_note="Saved for next time."):
    """The primary button on an email template screen.

    ``on_before_send`` is what saves the edited text, and runs first, so the
    template kept is exactly the message sent."""
    def send():
        subject = (get_subject() or "").strip()
        body = (get_body() or "").strip()
        if on_before_send:
            on_before_send(subject, body)
        message = open_message(window, base_dir, subject, body,
                               get_bcc() or [], saved_note)
        if message and flash:
            flash(message)

    btn = ttk.Button(parent_row, text="✉ Open in Outlook", bootstyle=SUCCESS,
                     command=send)
    btn.pack(side=RIGHT, padx=4)
    return btn


def add_send_hint(parent, extra=""):
    """The one line that answers "where do my edits go?" before it is asked."""
    from ui.theme import muted_fg
    text = ("Your edits here are saved and reused next time. Changes you make "
            "in Outlook after it opens apply to that one message only" +
            (f" {extra}" if extra else "") + ".")
    return ttk.Label(parent, text=text, font=("Segoe UI", 8),
                     foreground=muted_fg(), wraplength=600, justify=LEFT)
