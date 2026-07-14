"""
ui/sharing_view.py - The "Co-director sync" Settings panel.

Off for almost everyone.  A handful of large high schools have two band
directors who keep separate rosters but share ONE instrument inventory, check-out
log, repair log, and music library.  This panel lets a director connect this
computer to a shared Turso database using a one-line code.

Two things happen here:
  * Generate a code  - an admin pastes the Turso database URL + token they
                       created and gets one paste-able code to hand to both
                       directors.  (You only do this once per shared library.)
  * Connect          - paste a code; the app checks whether the shared library
                       is empty (→ seed it from THIS computer, you're the owner)
                       or already has data (→ back up local, adopt the shared
                       copy).  It figures out which and explains before doing it.

The heavy lifting lives in ``sharing`` + ``shared_sync``; this is the form and
the confirm/So-what messaging around it.  All network calls run on a worker
thread so the dialog never freezes.
"""

import os
import threading
import tkinter as tk
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from ttkbootstrap.dialogs import Messagebox


def _mask(url: str) -> str:
    """Show enough of the URL to recognise it without exposing the whole host."""
    u = (url or "").split("//", 1)[-1]
    return (u[:22] + "…") if len(u) > 24 else u


class SharingPanel(ttk.Frame):
    def __init__(self, parent, base_dir: str):
        super().__init__(parent)
        self.base_dir = base_dir
        self.db_path = os.path.join(base_dir, "rokas_resonance.db")
        self._busy = False
        self._build()

    # ── build ──
    def _build(self):
        outer = ttk.Frame(self)
        outer.pack(fill=BOTH, expand=True, padx=20, pady=14)
        self._outer = outer

        ttk.Label(outer, text="Co-director shared inventory",
                  font=("Segoe UI", 10, "bold")).pack(anchor=W)
        ttk.Label(
            outer,
            text="For two directors at one school who share the same instruments, "
                 "check-out log, repairs, and music library while keeping separate "
                 "class lists. Almost everyone should leave this off.",
            font=("Segoe UI", 9), foreground="#888",
            wraplength=470, justify=LEFT).pack(anchor=W, pady=(2, 10))

        # Status line (rebuilt by _refresh)
        self._status = ttk.Label(outer, text="", font=("Segoe UI", 9, "bold"))
        self._status.pack(anchor=W, pady=(0, 8))

        self._body = ttk.Frame(outer)
        self._body.pack(fill=BOTH, expand=True)
        self._refresh()

    def _sharing(self) -> dict:
        from sharing import load_sharing
        return load_sharing(self.base_dir)

    def _refresh(self):
        for w in self._body.winfo_children():
            w.destroy()
        block = self._sharing()
        if block.get("enabled") and block.get("url"):
            self._build_connected(block)
        else:
            self._build_disconnected()

    # ── connected state ──
    def _build_connected(self, block):
        self._status.config(
            text="● Sharing is ON for this computer", foreground="#2a7a2a")
        info = ttk.Frame(self._body)
        info.pack(fill=X, pady=(0, 8))
        lbl = block.get("label") or _mask(block.get("url"))
        role = {"owner": "you set up this shared library",
                "join": "you joined a co-director's shared library"}.get(
                    block.get("role"), "")
        ttk.Label(info, text=f"Shared library: {lbl}",
                  font=("Segoe UI", 9)).pack(anchor=W)
        if role:
            ttk.Label(info, text=f"({role})", font=("Segoe UI", 8),
                      foreground="#888").pack(anchor=W)
        ttk.Label(self._body,
                  text="Changes you make to instruments, check-outs, repairs, and "
                       "the music library sync to your co-director over the "
                       "internet. You can view everything offline; editing shared "
                       "items needs a connection.",
                  font=("Segoe UI", 8), foreground="#888",
                  wraplength=470, justify=LEFT).pack(anchor=W, pady=(0, 10))

        row = ttk.Frame(self._body)
        row.pack(fill=X)
        ttk.Button(row, text="Check connection", bootstyle=(INFO, OUTLINE),
                   command=self._check).pack(side=LEFT)
        ttk.Button(row, text="Stop sharing on this computer",
                   bootstyle=(DANGER, OUTLINE),
                   command=self._disconnect).pack(side=LEFT, padx=(8, 0))
        self._msg = ttk.Label(self._body, text="", font=("Segoe UI", 8),
                              wraplength=470, justify=LEFT)
        self._msg.pack(anchor=W, pady=(8, 0))

    # ── disconnected state ──
    def _build_disconnected(self):
        self._status.config(text="○ Sharing is off (solo)", foreground="#888")

        # A) Connect with a code
        box = ttk.Labelframe(self._body, text=" Connect to a shared library ",
                             padding=10)
        box.pack(fill=X, pady=(0, 12))
        ttk.Label(box, text="Paste the sharing code your co-director or admin gave "
                            "you, then Connect.",
                  font=("Segoe UI", 9), foreground="#888",
                  wraplength=450, justify=LEFT).pack(anchor=W)
        self._code = tk.Text(box, height=3, wrap="char", relief="solid", bd=1,
                             font=("Consolas", 8))
        self._code.pack(fill=X, pady=(6, 6))
        crow = ttk.Frame(box)
        crow.pack(fill=X)
        self._connect_btn = ttk.Button(crow, text="Connect", bootstyle=SUCCESS,
                                       command=self._connect)
        self._connect_btn.pack(side=LEFT)
        self._msg = ttk.Label(crow, text="", font=("Segoe UI", 8),
                              wraplength=320, justify=LEFT)
        self._msg.pack(side=LEFT, padx=(10, 0))

        # B) Generate a code (admin, once per shared library)
        gbox = ttk.Labelframe(
            self._body, text=" Set up a new shared library (admin — once) ",
            padding=10)
        gbox.pack(fill=X)
        ttk.Label(gbox, text="Create a database at turso.tech, then paste its "
                            "Database URL and auth token here to make a code. Give "
                            "that same code to BOTH directors.",
                  font=("Segoe UI", 9), foreground="#888",
                  wraplength=450, justify=LEFT).pack(anchor=W)
        grid = ttk.Frame(gbox)
        grid.pack(fill=X, pady=(6, 0))
        grid.columnconfigure(1, weight=1)
        ttk.Label(grid, text="Database URL", font=("Segoe UI", 8, "bold")).grid(
            row=0, column=0, sticky=W, padx=(0, 8), pady=3)
        self._g_url = tk.StringVar()
        ttk.Entry(grid, textvariable=self._g_url).grid(
            row=0, column=1, sticky="ew", pady=3)
        ttk.Label(grid, text="Auth token", font=("Segoe UI", 8, "bold")).grid(
            row=1, column=0, sticky=W, padx=(0, 8), pady=3)
        self._g_tok = tk.StringVar()
        ttk.Entry(grid, textvariable=self._g_tok, show="•").grid(
            row=1, column=1, sticky="ew", pady=3)
        ttk.Label(grid, text="Label (optional)", font=("Segoe UI", 8, "bold")).grid(
            row=2, column=0, sticky=W, padx=(0, 8), pady=3)
        self._g_lbl = tk.StringVar()
        ttk.Entry(grid, textvariable=self._g_lbl).grid(
            row=2, column=1, sticky="ew", pady=3)
        ttk.Button(gbox, text="Generate code", bootstyle=(PRIMARY, OUTLINE),
                   command=self._generate).pack(anchor=W, pady=(8, 6))
        self._gen_out = tk.Text(gbox, height=3, wrap="char", relief="solid", bd=1,
                                font=("Consolas", 8))
        self._gen_out.pack(fill=X)
        self._gen_out.insert("1.0", "(your code appears here)")
        # Read-only but still SELECTABLE, so the code can be highlighted and
        # copied with the mouse / Ctrl+C (a fully-disabled Text can't be copied).
        self._gen_out.bind("<Key>", self._readonly_guard)
        grow = ttk.Frame(gbox)
        grow.pack(fill=X, pady=(4, 0))
        ttk.Button(grow, text="Copy code", bootstyle=(SECONDARY, OUTLINE),
                   command=self._copy_code).pack(side=LEFT)
        ttk.Button(grow, text="Use it to connect this computer",
                   bootstyle=(SUCCESS, OUTLINE, LINK),
                   command=self._use_generated).pack(side=LEFT, padx=(8, 0))

    # ── generate-code handlers ──
    @staticmethod
    def _readonly_guard(event):
        """Block edits to the code box but allow selection, copy, and select-all."""
        if (event.state & 0x4) and event.keysym.lower() in ("c", "a"):
            return  # Ctrl+C / Ctrl+A
        if event.keysym in ("Left", "Right", "Up", "Down", "Home", "End",
                            "Prior", "Next", "Shift_L", "Shift_R",
                            "Control_L", "Control_R"):
            return
        return "break"

    def _generate(self):
        from sharing import make_connection_code
        try:
            code = make_connection_code(self._g_url.get(), self._g_tok.get(),
                                        self._g_lbl.get())
        except ValueError as e:
            Messagebox.show_warning(str(e), title="Can't make a code", parent=self)
            return
        self._gen_out.delete("1.0", "end")
        self._gen_out.insert("1.0", code)

    def _copy_code(self):
        code = self._gen_out.get("1.0", "end").strip()
        if code and not code.startswith("("):
            self.clipboard_clear()
            self.clipboard_append(code)
            self.update()          # flush so the clipboard survives after focus loss
            Messagebox.show_info("Code copied to the clipboard.", title="Copied",
                                 parent=self)

    def _use_generated(self):
        code = self._gen_out.get("1.0", "end").strip()
        if code and not code.startswith("("):
            self._code.delete("1.0", "end")
            self._code.insert("1.0", code)
            self._connect()

    # ── connect / disconnect ──
    def _set_busy(self, busy, msg=""):
        self._busy = busy
        if hasattr(self, "_connect_btn"):
            self._connect_btn.config(state="disabled" if busy else "normal")
        if msg and hasattr(self, "_msg"):
            self._msg.config(text=msg, foreground="#555")

    def _connect(self):
        if self._busy:
            return
        from sharing import parse_connection_code
        code = self._code.get("1.0", "end").strip()
        try:
            info = parse_connection_code(code)
        except ValueError as e:
            Messagebox.show_warning(str(e), title="Check the code", parent=self)
            return
        self._set_busy(True, "Connecting…")

        def work():
            from sharing import TursoClient, TursoError, TursoOffline
            try:
                client = TursoClient(info["url"], info["token"])
                client.test_connection()
                # Empty shared library → this computer seeds it (owner).
                r = client.execute("SELECT name FROM sqlite_master WHERE "
                                   "type='table' AND name='instruments'")
                count = 0
                if r["rows"]:
                    count = client.execute(
                        "SELECT COUNT(*) AS n FROM instruments")["rows"][0]["n"]
            except TursoOffline:
                self.after(0, self._connect_failed,
                           "No internet connection — connect to wifi and try again.")
                return
            except TursoError as e:
                self.after(0, self._connect_failed, str(e))
                return
            except Exception as e:
                self.after(0, self._connect_failed, f"Unexpected error: {e}")
                return
            self.after(0, self._connect_confirm, info, count)

        threading.Thread(target=work, daemon=True).start()

    def _connect_failed(self, msg):
        self._set_busy(False)
        Messagebox.show_error(msg, title="Couldn't connect", parent=self)

    def _connect_confirm(self, info, count):
        """On the UI thread: explain what will happen, then apply."""
        self._set_busy(False)
        if count == 0:
            local_n = self._local_instrument_count()
            ok = Messagebox.yesno(
                f"This shared library is empty.\n\nSet it up from THIS computer's "
                f"inventory ({local_n} instruments)? Your co-director can then "
                f"connect with the same code and see everything.",
                title="Set up shared library", parent=self)
            role = "owner"
        else:
            ok = Messagebox.yesno(
                f"This shared library already has {count} instruments.\n\nConnect "
                f"this computer to it? Your current local inventory will be backed "
                f"up first, then replaced by the shared copy. (Your students, "
                f"agendas, and budget stay untouched.)",
                title="Join shared library", parent=self)
            role = "join"
        if ok != "Yes":
            return
        self._apply(info, role)

    def _apply(self, info, role):
        self._set_busy(True, "Setting up… this can take a moment.")

        def work():
            try:
                from database import Database
                from shared_sync import SharedSync
                from sharing import TursoClient, save_sharing
                # Safety backup before any replace.
                try:
                    Database(self.db_path).backup()
                except Exception:
                    pass
                client = TursoClient(info["url"], info["token"])
                sync = SharedSync(self.db_path, client)
                if role == "owner":
                    sync.start_as_owner()
                else:
                    sync.start_as_join()
                save_sharing(self.base_dir, {
                    "enabled": True, "url": info["url"], "token": info["token"],
                    "role": role, "label": info.get("label", "")})
            except Exception as e:
                self.after(0, self._apply_failed, str(e))
                return
            self.after(0, self._apply_done)

        threading.Thread(target=work, daemon=True).start()

    def _apply_failed(self, msg):
        self._set_busy(False)
        Messagebox.show_error(f"Setup didn't finish:\n{msg}\n\nYour local data was "
                              "not changed.", title="Setup failed", parent=self)

    def _apply_done(self):
        self._busy = False
        Messagebox.show_info(
            "Connected! This computer is now sharing.\n\nPlease close and reopen "
            "Roka so the shared inventory loads everywhere.",
            title="Sharing is on", parent=self)
        self._refresh()

    def _check(self):
        block = self._sharing()
        self._msg.config(text="Checking…", foreground="#555")

        def work():
            from sharing import TursoClient, TursoError, TursoOffline
            try:
                TursoClient(block["url"], block["token"]).test_connection()
                self.after(0, lambda: self._msg.config(
                    text="✓ Connected to the shared library.", foreground="#2a7a2a"))
            except TursoOffline:
                self.after(0, lambda: self._msg.config(
                    text="Offline — you can still view; editing shared items needs "
                         "internet.", foreground="#b06a00"))
            except (TursoError, Exception) as e:
                self.after(0, lambda: self._msg.config(
                    text=f"Problem: {e}", foreground="#CC0000"))

        threading.Thread(target=work, daemon=True).start()

    def _disconnect(self):
        ok = Messagebox.yesno(
            "Stop sharing on this computer?\n\nThe shared inventory you have now "
            "stays here as your local copy, but it will no longer update from — or "
            "send updates to — your co-director. You can reconnect later with the "
            "same code.",
            title="Stop sharing", parent=self)
        if ok != "Yes":
            return
        from sharing import save_sharing
        block = self._sharing()
        block["enabled"] = False
        save_sharing(self.base_dir, block)
        Messagebox.show_info("Sharing turned off. Restart Roka to finish.",
                             title="Sharing off", parent=self)
        self._refresh()

    # ── helpers ──
    def _local_instrument_count(self):
        try:
            import sqlite3
            c = sqlite3.connect(self.db_path)
            n = c.execute("SELECT COUNT(*) FROM instruments").fetchone()[0]
            c.close()
            return n
        except Exception:
            return 0
