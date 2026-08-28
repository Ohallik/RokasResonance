"""
ui/key_prompt.py - Turn on the AI features at the moment a teacher first
reaches for one.

The old experience was a dead end: click an AI button with no key saved and a
warning sent you off to Settings, three clicks deep, with wording about
tokens.  For a teacher who has never heard the words "API key" that warning
IS the moment they decide the feature is not for them.

So the moment is the setup instead.  One dialog, one paste, one button, and
the feature they clicked carries on.  The key usually comes from their
district or director (who did the sign-up part for them); the dialog also
names where to get their own.
"""

import tkinter as tk
import ttkbootstrap as ttk
from ttkbootstrap.constants import *

from ui.theme import muted_fg, fs


def ensure_llm_ready(parent, base_dir) -> bool:
    """True when the AI backend is ready, prompting for a key if needed.

    Call in place of a bare ``is_configured`` check.  Returns False only when
    the teacher chose Not Now, so the caller simply returns.
    """
    from llm_client import is_configured
    if is_configured(base_dir):
        return True
    dlg = _KeyPrompt(parent, base_dir)
    parent.wait_window(dlg)
    return is_configured(base_dir)


class _KeyPrompt(ttk.Toplevel):
    def __init__(self, parent, base_dir):
        super().__init__(master=parent)
        self.base_dir = base_dir
        self.title("Turn on Roka's AI")
        self.resizable(False, False)
        self.grab_set()
        self.lift()

        hdr = ttk.Frame(self, bootstyle=INFO)
        hdr.pack(fill=X)
        ttk.Label(hdr, text="✨  One paste and you're in",
                  font=("Segoe UI", fs(12), "bold"),
                  bootstyle=(INVERSE, INFO)).pack(pady=10, padx=16, anchor=W)

        body = ttk.Frame(self)
        body.pack(fill=BOTH, expand=True, padx=16, pady=(10, 0))
        ttk.Label(
            body,
            text="This feature uses Claude, and Roka just needs your API "
                 "key. Paste it here:",
            font=("Segoe UI", fs(9)), wraplength=380,
            justify=LEFT).pack(anchor=W)

        row = ttk.Frame(body)
        row.pack(fill=X, pady=(8, 2))
        self._key_var = tk.StringVar()
        self._entry = ttk.Entry(row, textvariable=self._key_var, show="•",
                                width=42)
        self._entry.pack(side=LEFT, fill=X, expand=True)
        self._show = False
        self._show_btn = ttk.Button(row, text="Show",
                                    bootstyle=(SECONDARY, OUTLINE), width=6,
                                    command=self._toggle)
        self._show_btn.pack(side=LEFT, padx=(6, 0))
        self._entry.focus_set()

        hint = ttk.Frame(body)
        hint.pack(fill=X, pady=(4, 0))
        ttk.Label(hint,
                  text="No key yet? One takes about ten minutes and $5.",
                  font=("Segoe UI", fs(8)),
                  foreground=muted_fg()).pack(side=LEFT)
        link = ttk.Label(hint, text="Click here for the step-by-step guide.",
                         font=("Segoe UI", fs(8), "underline"),
                         foreground="#1c6ea4", cursor="hand2")
        link.pack(side=LEFT, padx=(4, 0))
        link.bind("<Button-1>", lambda e: self._open_guide())

        btns = ttk.Frame(self)
        btns.pack(fill=X, padx=16, pady=12)
        ttk.Button(btns, text="Not now", bootstyle=(SECONDARY, OUTLINE),
                   command=self.destroy).pack(side=RIGHT, padx=4)
        ttk.Button(btns, text="Save and continue", bootstyle=SUCCESS,
                   command=self._save).pack(side=RIGHT, padx=4)
        self.bind("<Return>", lambda e: self._save())

        from ui.theme import fit_window
        fit_window(self, 440, 240)

    def _open_guide(self):
        from ui.help_system import open_api_guide
        open_api_guide(parent=self)

    def _toggle(self):
        self._show = not self._show
        self._entry.config(show="" if self._show else "•")
        self._show_btn.config(text="Hide" if self._show else "Show")

    def _save(self):
        key = self._key_var.get().strip()
        if not key:
            return
        if not key.startswith("sk-ant"):
            from ttkbootstrap.dialogs import Messagebox
            if Messagebox.yesno(
                    "Claude keys start with sk-ant and this one doesn't. "
                    "Save it anyway?", title="Does this look right?",
                    parent=self) != "Yes":
                return
        from ui.settings_dialog import load_settings, save_settings
        import llm_client
        settings = load_settings(self.base_dir)
        llm = settings.setdefault("llm", {})
        llm["backend"] = "local"
        llm["anthropic_api_key"] = key
        # The saved model must be a Claude one or the key sits unused; leave
        # a deliberate Claude choice alone, otherwise pick the cheap default.
        if not str(llm.get("model", "")).startswith("claude-"):
            llm["model"] = llm_client.CLAUDE_HAIKU
        save_settings(self.base_dir, settings)
        self.destroy()
