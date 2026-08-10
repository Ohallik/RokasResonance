"""
ui/main_menu.py - Main menu hub for Roka's Resonance
"""

import os
import sys
import tkinter as tk
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from PIL import Image, ImageTk
from ui.theme import (fs, muted_fg, subtle_fg, link_fg, register_nav_styles,
                      nav_color, best_fg)

# Earlier builds kept choir and orchestra repertoire in their own files beside
# the profile database.  Switching program type then swapped the Music Manager
# onto an empty file, so a band library looked deleted.  One library per profile
# now; these names are only still known so their contents can be folded back in.
_LEGACY_MUSIC_DBS = ("choir_music.db", "orchestra_music.db")


def _absorb_legacy_music_db(main_db, path):
    """Copy sheet music out of a retired per-program file into the profile DB."""
    import sqlite3
    cols = ["title", "composer", "arranger", "genre", "ensemble_type",
            "difficulty", "file_path", "file_type", "num_pages", "notes",
            "key_signature", "time_signature", "location", "publisher",
            "source_file", "voicing", "language", "accompaniment"]
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("SELECT * FROM sheet_music").fetchall()
    except sqlite3.Error:
        rows = []
    finally:
        conn.close()

    if rows:
        with main_db._connect() as main_conn:
            existing = {
                ((r["title"] or "").strip().lower(),
                 (r["composer"] or "").strip().lower())
                for r in main_conn.execute(
                    "SELECT title, composer FROM sheet_music")
            }
        for r in rows:
            keys = r.keys()
            key = ((r["title"] or "").strip().lower(),
                   (r["composer"] or "").strip().lower())
            if not key[0] or key in existing:
                continue
            main_db.add_sheet_music({c: (r[c] if c in keys else None) for c in cols})
            existing.add(key)

    # Retire the file rather than deleting it, so the rows stay recoverable.
    try:
        os.replace(path, path + ".merged")
    except OSError:
        pass


def music_db_for_profile(main_db, base_dir):
    """The profile database is the one music library, whatever the program type."""
    for name in _LEGACY_MUSIC_DBS:
        path = os.path.join(base_dir, name)
        if os.path.exists(path):
            try:
                _absorb_legacy_music_db(main_db, path)
            except Exception:
                pass
    return main_db


class MainMenu(ttk.Frame):
    def __init__(self, parent, db, base_dir: str, app_dir: str = None, teacher_name: str = "", version: str = ""):
        super().__init__(parent)
        self.db = db
        self.base_dir = base_dir
        self.app_dir = app_dir or base_dir
        # The profile FOLDER may carry a middle initial ("Meagan R. Mangum");
        # everything shown on screen uses first + last only.
        from ui.names import display_person
        self.teacher_name = display_person(teacher_name)
        self._version = version
        self._windows = {}  # key -> Toplevel; tracks open manager windows
        self._helper_mode = False  # restricted parent-volunteer mode
        from ui.settings_dialog import load_settings
        settings = load_settings(base_dir)
        self._program_type = (settings.get("teacher") or {}).get("program_type", "band")
        # Stat label refs — populated in _build(), None for unused slots
        self._stat_checkedout = None
        self._stat_repair = None
        self._stat_students = None
        self._stat_students_year = None
        self._stat_music = None
        self._refresh_after_id = None
        self._build()
        self._schedule_refresh()
        self.after(1200, self._check_year_rollover)
        if self._version:
            self.after(2000, self._start_update_check)  # slight delay so UI loads first

    def _raise_or_open(self, key: str) -> ttk.Toplevel | None:
        """If the window for *key* is still open, bring it to front and return it.
        Otherwise return None so the caller knows to create a new one."""
        win = self._windows.get(key)
        if win is not None:
            try:
                if win.winfo_exists():
                    win.lift()
                    win.focus_force()
                    # Restore from minimised if needed
                    if win.state() == "iconic":
                        win.deiconify()
                    return win
            except tk.TclError:
                pass
            # Window was destroyed — clear stale reference
            self._windows.pop(key, None)
        return None

    def _build(self):
        # ── Logo / Title Area ─────────────────────────────────────────────────
        header = ttk.Frame(self, bootstyle=PRIMARY)
        header.pack(fill=X)

        # Load mascot image (remove white background for clean banner look)
        logo_path = os.path.join(self.app_dir, "assets", "banner_logo.png")
        self._banner_img = None
        try:
            img = Image.open(logo_path).convert("RGBA")
            # Replace near-white pixels with transparency
            data = img.getdata()
            new_data = []
            for r, g, b, a in data:
                if r > 220 and g > 220 and b > 220:
                    new_data.append((r, g, b, 0))
                else:
                    new_data.append((r, g, b, a))
            img.putdata(new_data)
            # Resize to fit the banner height — cap at 80px to save vertical space
            target_h = 80
            aspect = img.width / img.height
            target_w = int(target_h * aspect)
            img = img.resize((target_w, target_h), Image.LANCZOS)
            self._banner_img = ImageTk.PhotoImage(img)
        except Exception:
            pass

        # Image on the right (pack first so it claims space)
        if self._banner_img:
            ttk.Label(
                header,
                image=self._banner_img,
                bootstyle=(INVERSE, PRIMARY),
            ).pack(side=RIGHT, padx=(0, 30), pady=8)

        # Text centered in remaining space (left of the image)
        text_frame = ttk.Frame(header, bootstyle=PRIMARY)
        text_frame.pack(side=LEFT, fill=BOTH, expand=True, pady=(10, 8))

        ttk.Label(
            text_frame,
            text="🎵  Roka's Resonance",
            font=("Segoe UI", fs(22), "bold"),
            bootstyle=(INVERSE, PRIMARY),
            anchor=CENTER,
        ).pack(fill=X, pady=(0, 2))

        ttk.Label(
            text_frame,
            text=f"{self.teacher_name}  •  Music Management" if self.teacher_name else "Music Management",
            font=("Segoe UI", fs(10)),
            bootstyle=(INVERSE, PRIMARY),
            anchor=CENTER,
        ).pack(fill=X)

        # ── Stats Bar ─────────────────────────────────────────────────────────
        stats_outer = ttk.Frame(self, bootstyle=SECONDARY)
        stats_outer.pack(fill=X)

        stats_inner = ttk.Frame(stats_outer)
        stats_inner.pack(pady=6)

        # Left stats — rebuilt dynamically when program type changes
        self._left_stats_container = ttk.Frame(stats_inner)
        self._left_stats_container.pack(side=LEFT, padx=(24, 28))
        self._build_left_stats()

        # Vertical divider
        ttk.Separator(stats_inner, orient=VERTICAL).pack(side=LEFT, fill=Y, padx=4, pady=6)

        # Right: Music section (same for all program types)
        music_section = ttk.Frame(stats_inner)
        music_section.pack(side=LEFT, padx=(28, 24))

        ttk.Label(
            music_section,
            text="MUSIC",
            font=("Segoe UI", fs(7), "bold"),
            foreground=muted_fg(),
            anchor=CENTER,
        ).pack(fill=X, pady=(0, 6))

        music_stats = ttk.Frame(music_section)
        music_stats.pack()
        self._stat_music = self._make_stat(music_stats, "—", "Pieces of Music", 0)

        # ── Banners (hidden until needed) ─────────────────────────────────────
        self._update_banner = None    # an app update is available
        self._rollover_banner = None  # the school year has moved on

        # ── Footer ────────────────────────────────────────────────────────────
        # Pack footer BEFORE btn_area so it reserves bottom space first.
        footer = ttk.Frame(self)
        footer.pack(fill=X, side=BOTTOM)
        ttk.Separator(footer).pack(fill=X)

        footer_inner = ttk.Frame(footer)
        footer_inner.pack(pady=4)

        ttk.Label(
            footer_inner,
            text=f"Roka's Resonance  •  {self.teacher_name}" if self.teacher_name else "Roka's Resonance",
            font=("Segoe UI", fs(8)),
            foreground=subtle_fg(),
        ).pack(side=LEFT)

        ttk.Label(
            footer_inner,
            text="  •  ",
            font=("Segoe UI", fs(8)),
            foreground=subtle_fg(),
        ).pack(side=LEFT)

        switch_lbl = ttk.Label(
            footer_inner,
            text="Switch Profile",
            font=("Segoe UI", fs(8), "underline"),
            foreground=link_fg(),
            cursor="hand2",
        )
        switch_lbl.pack(side=LEFT)
        switch_lbl.bind("<Button-1>", lambda e: self._switch_profile())

        ttk.Label(
            footer_inner,
            text="  •  ",
            font=("Segoe UI", fs(8)),
            foreground=subtle_fg(),
        ).pack(side=LEFT)

        settings_lbl = ttk.Label(
            footer_inner,
            text="Settings",
            font=("Segoe UI", fs(8), "underline"),
            foreground=link_fg(),
            cursor="hand2",
        )
        settings_lbl.pack(side=LEFT)
        settings_lbl.bind("<Button-1>", lambda e: self._open_settings())

        ttk.Label(footer_inner, text="  •  ", font=("Segoe UI", fs(8)),
                  foreground=subtle_fg()).pack(side=LEFT)
        import_lbl = ttk.Label(
            footer_inner, text="Import Data",
            font=("Segoe UI", fs(8), "underline"),
            foreground=link_fg(), cursor="hand2")
        import_lbl.pack(side=LEFT)
        import_lbl.bind("<Button-1>", lambda e: self._open_import_wizard())

        ttk.Label(footer_inner, text="  •  ", font=("Segoe UI", fs(8)),
                  foreground=subtle_fg()).pack(side=LEFT)
        helper_lbl = ttk.Label(
            footer_inner, text="Helper Mode",
            font=("Segoe UI", fs(8), "underline"),
            foreground=link_fg(), cursor="hand2")
        helper_lbl.pack(side=LEFT)
        helper_lbl.bind("<Button-1>", lambda e: self._enter_helper_mode())

        # Ownership / copyright notice — proprietary software, all rights reserved.
        _copy = "© 2026 Meagan Mangum. All rights reserved."
        if self._version:
            _copy += f"   •   {self._version}"
        ttk.Label(footer, text=_copy, font=("Segoe UI", fs(7)),
                  foreground=subtle_fg()).pack(pady=(0, 3))

        # ── Main Navigation Grid ─────────────────────────────────────────────
        # Two-column layout for compact, accessible navigation.
        # Each destination gets its own hue (see ui.theme.register_nav_styles) so
        # the hub reads as a map rather than a stack of identical blue bars.
        _btn_font = ("Segoe UI", min(fs(11), 20), "bold")
        _btn_font_sm = ("Segoe UI", min(fs(10), 18), "bold")
        register_nav_styles(_btn_font, _btn_font_sm)

        btn_area = ttk.Frame(self)
        btn_area.pack(fill=X, padx=30, pady=(8, 4))
        btn_area.columnconfigure(0, weight=1)
        btn_area.columnconfigure(1, weight=1)
        self._btn_area = btn_area
        self._build_nav_buttons()

    @staticmethod
    def _nav_button(parent, text, command, hue, small=False):
        """A navigation button in one of the palette hues.

        The style has to be applied AFTER construction: ttkbootstrap's Button
        re-derives ``style`` from its own bootstyle vocabulary at build time and
        silently drops any name it doesn't recognise (which is how every button
        ends up default blue).  Configuring afterwards sticks.
        """
        btn = ttk.Button(parent, text=text, command=command)
        btn.configure(style=f"{'NavSm' if small else 'Nav'}.{hue}.TButton")
        return btn

    def _build_nav_buttons(self):
        """(Re)populate the navigation grid.  In Helper Mode only the Uniforms
        tool is offered (with student contact data hidden) so a parent volunteer
        can run uniform check-out without reaching any sensitive data."""
        btn_area = self._btn_area
        for w in btn_area.winfo_children():
            w.destroy()
        btn_pad = min(fs(5), 10)  # internal padding, capped
        cur_row = 0

        if self._helper_mode:
            ttk.Label(
                btn_area, text="Helper Mode — uniform check-out only",
                font=("Segoe UI", fs(9), "bold"), foreground=muted_fg(),
            ).grid(row=cur_row, column=0, columnspan=2, sticky=W, pady=(4, 2))
            cur_row += 1
            self._nav_button(
                btn_area, "  👕  Uniform Check-Out", self._open_uniforms, "amber"
            ).grid(row=cur_row, column=0, columnspan=2, sticky="ew", pady=2, ipady=btn_pad)
            cur_row += 1
            self._nav_button(
                btn_area, "  🔒  Exit Helper Mode (PIN)", self._exit_helper_mode, "gray"
            ).grid(row=cur_row, column=0, columnspan=2, sticky="ew", pady=(10, 2), ipady=btn_pad)
            return

        # ── Inventory (things: equipment + sheet music) ──
        ttk.Label(
            btn_area, text="Inventory",
            font=("Segoe UI", fs(9), "bold"), foreground=muted_fg(),
        ).grid(row=cur_row, column=0, columnspan=2, sticky=W, pady=(4, 2))
        cur_row += 1

        # Equipment / Sheet Music / Uniforms share one row.  A nested 3-column
        # frame keeps the outer 2-column grid (used by every other row) intact.
        inv_row = ttk.Frame(btn_area)
        inv_row.grid(row=cur_row, column=0, columnspan=2, sticky="ew", pady=2)
        for _c in (0, 1, 2):
            inv_row.columnconfigure(_c, weight=1, uniform="inv")
        self._nav_button(
            inv_row, "  🎺  Equipment", self._open_inventory, "red"
        ).grid(row=0, column=0, sticky="ew", padx=(0, 3), ipady=btn_pad)
        self._nav_button(
            inv_row, "  🎼  Sheet Music", self._open_music_manager, "orange"
        ).grid(row=0, column=1, sticky="ew", padx=3, ipady=btn_pad)
        self._nav_button(
            inv_row, "  👕  Uniforms", self._open_uniforms, "amber"
        ).grid(row=0, column=2, sticky="ew", padx=(3, 0), ipady=btn_pad)
        cur_row += 1

        # ── Students ──
        ttk.Label(
            btn_area, text="Students",
            font=("Segoe UI", fs(9), "bold"), foreground=muted_fg(),
        ).grid(row=cur_row, column=0, columnspan=2, sticky=W, pady=(8, 2))
        cur_row += 1

        stu_row = ttk.Frame(btn_area)
        stu_row.grid(row=cur_row, column=0, columnspan=2, sticky="ew", pady=2)
        stu_row.columnconfigure(0, weight=3, uniform="stu")
        stu_row.columnconfigure(1, weight=2, uniform="stu")
        self._nav_button(
            stu_row, "  🎓  Manage Students", self._open_students, "green"
        ).grid(row=0, column=0, sticky="ew", padx=(0, 3), ipady=btn_pad)
        # Rolling the roster forward is a whole-program action, not a lesson-
        # planning one — it belongs beside the students it moves, in the hub,
        # where a new teacher will actually find it before anything depends on it.
        self._nav_button(
            stu_row, "  📦  New School Year…", self._open_year_wizard, "purple"
        ).grid(row=0, column=1, sticky="ew", padx=(3, 0), ipady=btn_pad)
        cur_row += 1

        # ── Teacher Prep (budget + lesson planning) ──
        ttk.Label(
            btn_area, text="Teacher Prep",
            font=("Segoe UI", fs(9), "bold"), foreground=muted_fg(),
        ).grid(row=cur_row, column=0, columnspan=2, sticky=W, pady=(8, 2))
        cur_row += 1

        self._nav_button(
            btn_area, "  💵  Budget", self._open_budget, "teal"
        ).grid(row=cur_row, column=0, sticky="ew", padx=(0, 3), pady=2, ipady=btn_pad)

        self._nav_button(
            btn_area, "  🧰  Teacher Tools", self._open_lesson_plans, "blue"
        ).grid(row=cur_row, column=1, sticky="ew", padx=(3, 0), pady=2, ipady=btn_pad)

    def _make_stat(self, parent, value: str, label: str, col: int):
        f = ttk.Frame(parent)
        f.grid(row=0, column=col, padx=14)
        val_lbl = ttk.Label(f, text=value, font=("Segoe UI", fs(18), "bold"), bootstyle=PRIMARY)
        val_lbl.pack()
        ttk.Label(f, text=label, font=("Segoe UI", fs(8)), foreground=muted_fg()).pack()
        return val_lbl

    def _build_left_stats(self):
        """Build (or rebuild) the left stats section for the current program type."""
        # Reset stat refs
        self._stat_checkedout = None
        self._stat_repair = None
        self._stat_students = None
        self._stat_students_year = None
        # Clear existing children
        for w in self._left_stats_container.winfo_children():
            w.destroy()

        if self._program_type == "choir":
            ttk.Label(
                self._left_stats_container,
                text="STUDENTS",
                font=("Segoe UI", fs(7), "bold"),
                foreground=muted_fg(),
                anchor=CENTER,
            ).pack(fill=X, pady=(0, 6))
            inner = ttk.Frame(self._left_stats_container)
            inner.pack(anchor=CENTER)
            f = ttk.Frame(inner)
            f.grid(row=0, column=0, padx=20)
            self._stat_students = ttk.Label(f, text="—", font=("Segoe UI", fs(20), "bold"), bootstyle=PRIMARY)
            self._stat_students.pack()
            self._stat_students_year = ttk.Label(f, text="This Year", font=("Segoe UI", fs(8)), foreground=muted_fg())
            self._stat_students_year.pack()
        else:
            ttk.Label(
                self._left_stats_container,
                text="EQUIPMENT",
                font=("Segoe UI", fs(7), "bold"),
                foreground=muted_fg(),
                anchor=CENTER,
            ).pack(fill=X, pady=(0, 6))
            inner = ttk.Frame(self._left_stats_container)
            inner.pack(anchor=CENTER)
            self._stat_checkedout = self._make_stat(inner, "—", "Checked Out", 0)
            self._stat_repair     = self._make_stat(inner, "—", "In Repair", 1)

    def _refresh_stats(self):
        """Read current settings + DB stats and update the stats bar. Safe to call any time."""
        # Re-read program type in case settings changed
        try:
            from ui.settings_dialog import load_settings
            settings = load_settings(self.base_dir)
            new_type = (settings.get("teacher") or {}).get("program_type", "band")
            if new_type != self._program_type:
                self._program_type = new_type
                self._build_left_stats()
        except Exception:
            pass
        try:
            stats = self.db.get_stats()
            if self._program_type == "choir":
                count, year = self.db.get_student_count_for_current_year()
                self._stat_students.config(text=str(count))
                self._stat_students_year.config(text=year if year else "This Year")
            else:
                co, total = stats["checked_out"], stats["total"]
                self._stat_checkedout.config(text=f"{co} / {total}")
                self._stat_repair.config(text=str(stats["in_repair"]))
            self._stat_music.config(text=str(stats.get("sheet_music", 0)))
        except Exception:
            pass

    def _schedule_refresh(self):
        """Periodic 30-second refresh loop — only one instance should run at a time."""
        self._refresh_stats()
        self._refresh_after_id = self.after(30000, self._schedule_refresh)

    def _start_update_check(self):
        from updater import check_for_update
        check_for_update(
            self._version,
            lambda tag, html_url, zipball_url, installer_url: self.after(
                0, self._show_update_banner, tag, html_url, zipball_url, installer_url
            ),
        )

    def _show_update_banner(self, tag: str, html_url: str, zipball_url: str, installer_url: str | None):
        if self._update_banner:
            return  # already showing
        banner = ttk.Frame(self, bootstyle=WARNING)
        banner.pack(fill=X, before=self._btn_area)
        ttk.Label(
            banner,
            text=f"⬆  Update available: {tag}",
            font=("Segoe UI", fs(9), "bold"),
            bootstyle=(INVERSE, WARNING),
        ).pack(side=LEFT, padx=(16, 8), pady=6)

        # Frozen bundles can't be updated in place — direct the user to download
        # the new installer instead. Dev / copy-files installs keep the original
        # in-app source-copy update flow.
        if getattr(sys, "frozen", False):
            download_url = installer_url or html_url
            ttk.Button(
                banner,
                text="Download Installer",
                bootstyle=WARNING,
                command=lambda: self._open_installer_download(download_url),
            ).pack(side=LEFT, pady=4)
        else:
            ttk.Button(
                banner,
                text="Install Update",
                bootstyle=WARNING,
                command=lambda: self._do_update(tag, zipball_url),
            ).pack(side=LEFT, pady=4)

        ttk.Button(
            banner,
            text="✕",
            bootstyle=(OUTLINE, WARNING),
            width=3,
            command=lambda: banner.pack_forget(),
        ).pack(side=RIGHT, padx=8, pady=4)
        self._update_banner = banner

    def _open_installer_download(self, url: str):
        import webbrowser
        webbrowser.open(url)

    def _do_update(self, tag: str, zipball_url: str):
        """Show a progress dialog, download the release zip, install, then prompt restart."""
        from updater import download_and_install
        import subprocess

        dlg = ttk.Toplevel(self.winfo_toplevel())
        dlg.title(f"Installing {tag}")
        dlg.resizable(False, False)
        dlg.grab_set()

        ttk.Label(dlg, text=f"Installing update {tag}",
                  font=("Segoe UI", fs(11), "bold"), bootstyle=PRIMARY).pack(pady=(20, 4), padx=30)

        status_var = tk.StringVar(value="Starting…")
        ttk.Label(dlg, textvariable=status_var,
                  font=("Segoe UI", fs(9))).pack(pady=(0, 8), padx=30)

        bar = ttk.Progressbar(dlg, mode="indeterminate", bootstyle=PRIMARY)
        bar.pack(fill=X, padx=30, pady=(0, 20))
        bar.start(10)

        from ui.theme import fit_window
        fit_window(dlg, 400, 160)

        def on_progress(msg):
            self.after(0, lambda: status_var.set(msg))

        def on_done():
            def _show_done():
                bar.stop()
                bar.pack_forget()
                status_var.set("Update installed successfully!")
                ttk.Label(dlg, text="Restart the app to use the new version.",
                          font=("Segoe UI", fs(9))).pack(pady=(0, 12), padx=30)
                btn_row = ttk.Frame(dlg)
                btn_row.pack(pady=(0, 16))
                ttk.Button(
                    btn_row, text="Restart Now", bootstyle=PRIMARY,
                    command=lambda: _restart(dlg),
                ).pack(side=LEFT, padx=6)
                ttk.Button(
                    btn_row, text="Later", bootstyle=SECONDARY,
                    command=dlg.destroy,
                ).pack(side=LEFT, padx=6)
                fit_window(dlg, 400, 200)
            self.after(0, _show_done)

        def on_error(msg):
            def _show_error():
                bar.stop()
                bar.pack_forget()
                status_var.set(f"Update failed: {msg}")
                ttk.Button(dlg, text="Close", bootstyle=DANGER,
                           command=dlg.destroy).pack(pady=(0, 16))
                fit_window(dlg, 420, 160)
            self.after(0, _show_error)

        def _restart(dialog):
            dialog.destroy()
            main_py = os.path.join(self.app_dir, "main.py")
            subprocess.Popen([sys.executable, main_py])
            self.winfo_toplevel().destroy()

        download_and_install(self.app_dir, zipball_url, on_progress, on_done, on_error)

    def _on_child_close(self, key: str):
        """Clean up window reference and refresh stats when a child window closes."""
        win = self._windows.pop(key, None)
        if win is not None:
            try:
                win.destroy()
            except tk.TclError:
                pass
        self._refresh_stats()

    def _open_inventory(self):
        if self._raise_or_open("inventory"):
            return
        from ui.inventory_manager import InventoryManager
        win = ttk.Toplevel(self.winfo_toplevel())
        win.title("Manage Equipment Inventory — Roka's Resonance")
        win.state("zoomed")
        manager = InventoryManager(win, self.db, self.base_dir,
                                   on_checkouts=self._open_active_checkouts)
        manager.pack(fill=BOTH, expand=True)
        win.protocol("WM_DELETE_WINDOW", lambda: self._on_child_close("inventory"))
        self._windows["inventory"] = win

    def _open_uniforms(self):
        if self._raise_or_open("uniforms"):
            return
        from ui.uniform_manager import UniformManager
        win = ttk.Toplevel(self.winfo_toplevel())
        win.title("Uniforms & Attire — Roka's Resonance")
        win.state("zoomed")
        manager = UniformManager(win, self.db, self.base_dir,
                                 on_checkouts=self._open_active_checkouts,
                                 helper_mode=self._helper_mode)
        manager.pack(fill=BOTH, expand=True)
        win.protocol("WM_DELETE_WINDOW", lambda: self._on_child_close("uniforms"))
        self._windows["uniforms"] = win

    # ── Helper Mode (restricted parent-volunteer access) ──────────────────────
    def _helper_pin(self) -> str:
        from ui.settings_dialog import load_settings
        return ((load_settings(self.base_dir).get("security") or {})
                .get("helper_pin") or "").strip()

    def _enter_helper_mode(self):
        """Hand the computer to a parent volunteer: hide every tool except
        uniform check-out (with contact data suppressed).  Requires a Helper PIN
        to be set first, since that same PIN is what locks the director back in."""
        import tkinter.simpledialog as sd
        pin = self._helper_pin()
        if not pin:
            from ttkbootstrap.dialogs import Messagebox
            new = sd.askstring(
                "Set a Helper PIN",
                "Before using Helper Mode, set a PIN the volunteer will NOT know.\n"
                "You'll enter it to switch back to full access.\n\nNew PIN:",
                show="•", parent=self.winfo_toplevel())
            if not new or not new.strip():
                return
            from ui.settings_dialog import load_settings, save_settings
            settings = load_settings(self.base_dir)
            settings.setdefault("security", {})["helper_pin"] = new.strip()
            save_settings(self.base_dir, settings)
            pin = new.strip()
        # Close any open sensitive windows before dropping into helper mode.
        for key in list(self._windows):
            w = self._windows.pop(key, None)
            if w:
                try:
                    w.destroy()
                except tk.TclError:
                    pass
        self._helper_mode = True
        self._build_nav_buttons()

    def _exit_helper_mode(self):
        import tkinter.simpledialog as sd
        from ttkbootstrap.dialogs import Messagebox
        pin = self._helper_pin()
        entered = sd.askstring("Exit Helper Mode", "Enter the Helper PIN:",
                               show="•", parent=self.winfo_toplevel())
        if entered is None:
            return
        if entered.strip() != pin:
            Messagebox.show_warning("Incorrect PIN.", title="Helper Mode",
                                    parent=self.winfo_toplevel())
            return
        for key in list(self._windows):
            w = self._windows.pop(key, None)
            if w:
                try:
                    w.destroy()
                except tk.TclError:
                    pass
        self._helper_mode = False
        self._build_nav_buttons()

    def _open_budget(self):
        if self._raise_or_open("budget"):
            return
        from ui.budget_manager import BudgetManager
        win = ttk.Toplevel(self.winfo_toplevel())
        win.title("Budget — Roka's Resonance")
        win.state("zoomed")
        program_type = self._program_type
        manager = BudgetManager(win, self.db, self.base_dir, program_type=program_type)
        manager.pack(fill=BOTH, expand=True)
        win.protocol("WM_DELETE_WINDOW", lambda: self._on_child_close("budget"))
        self._windows["budget"] = win

    def _open_students(self):
        if self._raise_or_open("students"):
            return
        from ui.student_manager import StudentManager
        from ui.settings_dialog import load_settings
        program_type = (load_settings(self.base_dir).get("teacher") or {}).get("program_type", "band")
        win = ttk.Toplevel(self.winfo_toplevel())
        win.title("Student Manager — Roka's Resonance")
        win.resizable(True, True)
        manager = StudentManager(win, self.db, program_type=program_type)
        manager.pack(fill=BOTH, expand=True)
        win.protocol("WM_DELETE_WINDOW", lambda: self._on_child_close("students"))
        self._windows["students"] = win
        from ui.theme import fit_window
        fit_window(win, 1000, 650)

    # ── School-year rollover ──────────────────────────────────────────────────

    def _check_year_rollover(self):
        """Offer the New School Year wizard when the calendar has moved on but
        the data hasn't.

        Without this, the app quietly keeps showing last year: rosters, seating
        charts, and rotations all look empty or wrong for the new year, and the
        natural "fix" — nudging a year selector forward — files everything under
        a year nothing else knows about.  Asking once, up front, is the only
        moment where rolling forward is cheap."""
        from lesson_plan_db import current_school_year, year_start
        cur = current_school_year()
        try:
            years = self.db.get_school_years()
        except Exception:
            return
        if not years:
            return                      # brand-new profile — onboarding covers it
        newest = max(years, key=year_start)
        if year_start(newest) >= year_start(cur):
            return                      # already rolled forward

        from ui.settings_dialog import load_settings
        settings = load_settings(self.base_dir) or {}
        if (settings.get("teacher") or {}).get("year_prompt_dismissed") == cur:
            self._show_rollover_banner(cur, newest)
            return

        from ttkbootstrap.dialogs import Messagebox
        answer = Messagebox.yesno(
            f"Your student records are still from {newest}, but the "
            f"{cur} school year has started.\n\n"
            "The New School Year wizard archives last year's roster, brings "
            "returning students forward, and imports this year's class lists — "
            "so seating charts, percussion rotations, and agendas all line up "
            "with the students actually in the room.\n\n"
            "Run it now?",
            title="Start the new school year?", parent=self.winfo_toplevel())
        if answer == "Yes":
            self._open_year_wizard()
            return
        # Don't nag on every launch — but keep it visible on the hub.
        settings.setdefault("teacher", {})["year_prompt_dismissed"] = cur
        try:
            from ui.settings_dialog import save_settings
            save_settings(self.base_dir, settings)
        except Exception:
            pass
        self._show_rollover_banner(cur, newest)

    def _show_rollover_banner(self, cur, newest):
        if getattr(self, "_rollover_banner", None):
            return
        banner = ttk.Frame(self, bootstyle=INFO)
        banner.pack(fill=X, before=self._btn_area)
        ttk.Label(
            banner,
            text=f"📦  Your roster is still {newest} — the {cur} year has started.",
            font=("Segoe UI", fs(9), "bold"),
            bootstyle=(INVERSE, INFO),
        ).pack(side=LEFT, padx=(16, 8), pady=6)
        ttk.Button(banner, text="Start New School Year…", bootstyle=INFO,
                   command=self._open_year_wizard).pack(side=LEFT, pady=4)
        ttk.Button(banner, text="✕", bootstyle=(OUTLINE, INFO), width=3,
                   command=banner.pack_forget).pack(side=RIGHT, padx=8, pady=4)
        self._rollover_banner = banner

    def _open_year_wizard(self):
        """Roll the whole program into the next school year.  Lives here (not
        buried in Teacher Tools) because everything else — rosters, seating
        charts, percussion sections — depends on it having been run."""
        from ui.year_wizard import NewSchoolYearWizard
        from lesson_plan_db import current_school_year
        try:
            years = self.db.get_school_years()
        except Exception:
            years = []
        current = years[0] if years else current_school_year()
        wiz = NewSchoolYearWizard(self.winfo_toplevel(), self.db, self.base_dir,
                                  current_year=current)
        self.winfo_toplevel().wait_window(wiz)
        # Any open Teacher Tools / Student windows are now showing last year.
        if getattr(wiz, "new_year", None):
            for key in ("lesson_plans", "students"):
                win = self._windows.pop(key, None)
                if win is not None:
                    try:
                        win.destroy()
                    except tk.TclError:
                        pass
        self._refresh_stats()

    def _open_music_manager(self):
        if self._raise_or_open("music"):
            return
        from ui.music_manager import MusicManager
        from ui.settings_dialog import load_settings

        settings = load_settings(self.base_dir)
        program_type = (settings.get("teacher") or {}).get("program_type", "band")

        music_db = music_db_for_profile(self.db, self.base_dir)
        title = {
            "choir":     "Choir Music Manager — Roka's Resonance",
            "orchestra": "Orchestra Music Manager — Roka's Resonance",
        }.get(program_type, "Music Manager — Roka's Resonance")

        win = ttk.Toplevel(self.winfo_toplevel())
        win.title(title)
        win.state("zoomed")
        manager = MusicManager(win, music_db, self.base_dir, mode=program_type)
        manager.pack(fill=BOTH, expand=True)
        win.protocol("WM_DELETE_WINDOW", lambda: self._on_child_close("music"))
        self._windows["music"] = win

    def _open_lesson_plans(self):
        if self._raise_or_open("lesson_plans"):
            return
        from ui.lesson_plans_hub import LessonPlansHub
        win = ttk.Toplevel(self.winfo_toplevel())
        win.title("Teacher Tools — Roka's Resonance")
        win.state("zoomed")
        hub = LessonPlansHub(win, self.db)
        hub.pack(fill=BOTH, expand=True)
        win.protocol("WM_DELETE_WINDOW",
                     lambda: self._on_child_close("lesson_plans"))
        self._windows["lesson_plans"] = win

    def _open_active_checkouts(self):
        if self._raise_or_open("checkouts"):
            return
        self._show_active_checkouts_window()

    def _show_active_checkouts_window(self):
        win = ttk.Toplevel(self.winfo_toplevel())
        win.title("Active Checkouts — Roka's Resonance")
        win.protocol("WM_DELETE_WINDOW", lambda: self._on_child_close("checkouts"))
        self._windows["checkouts"] = win

        ttk.Label(win, text="Currently Checked Out Instruments",
                  font=("Segoe UI", 13, "bold"), bootstyle=PRIMARY).pack(pady=(14, 4))

        cols = ("Student", "Instrument", "Category", "Barcode", "Date Checked Out")
        tree_frame = ttk.Frame(win)
        tree_frame.pack(fill=BOTH, expand=True, padx=14, pady=8)

        scrollbar = ttk.Scrollbar(tree_frame, orient=VERTICAL)
        tree = ttk.Treeview(tree_frame, columns=cols, show="headings",
                            yscrollcommand=scrollbar.set, bootstyle=PRIMARY,
                            selectmode="browse")
        scrollbar.config(command=tree.yview)

        widths = [180, 200, 120, 100, 120]
        _stretch = {"Student", "Instrument"}
        for col, w in zip(cols, widths):
            tree.heading(col, text=col, anchor=W)
            tree.column(col, width=w, anchor=W, stretch=col in _stretch)

        scrollbar.pack(side=RIGHT, fill=Y)
        tree.pack(fill=BOTH, expand=True)

        count_lbl = ttk.Label(win, text="", font=("Segoe UI", 9), foreground="#666")

        def _reload():
            tree.delete(*tree.get_children())
            checkouts = self.db.get_all_active_checkouts()
            for c in checkouts:
                is_item = not c["instrument_id"]
                label = (c["description"] or "") + ("  (item)" if is_item else "")
                tree.insert("", "end", iid=f"co:{c['id']}", values=(
                    c["student_name"] or "",
                    label,
                    c["category"] or "",
                    c["barcode"] or c["district_no"] or "",
                    c["date_assigned"] or "",
                ))
            loans = self.db.get_all_active_loans()
            for l in loans:
                who = "🏫 " + (l["school"] or "Another school")
                if l["contact_name"]:
                    who += f" — {l['contact_name']}"
                tree.insert("", "end", iid=f"loan:{l['id']}", values=(
                    who,
                    (l["description"] or "") + "  (on loan)",
                    l["category"] or "",
                    l["barcode"] or l["district_no"] or "",
                    l["date_out"] or "",
                ))
            count_lbl.config(
                text=f"{len(checkouts) + len(loans)} item(s) out "
                     f"({len(loans)} on loan to other schools)")

        def _return_selected():
            sel = tree.selection()
            if not sel:
                from ttkbootstrap.dialogs import Messagebox
                Messagebox.show_warning("Select a checked-out item to return.",
                                        title="No Selection", parent=win)
                return
            from datetime import datetime as _dt
            today = _dt.today().strftime("%Y-%m-%d")
            iid = sel[0]
            if iid.startswith("loan:"):
                self.db.return_loan(int(iid.split(":", 1)[1]), today)
            else:
                self.db.checkin_instrument(int(iid.split(":", 1)[1]), today)
            _reload()
            self._refresh_stats()

        btn_row = ttk.Frame(win)
        btn_row.pack(fill=X, padx=14, pady=(0, 4))
        ttk.Button(btn_row, text="📥 Return Selected", bootstyle=INFO,
                   command=_return_selected).pack(side=LEFT, padx=4, pady=4)
        ttk.Button(btn_row, text="🔄 Refresh", bootstyle=(SECONDARY, OUTLINE),
                   command=_reload).pack(side=LEFT, padx=4, pady=4)

        count_lbl.pack(pady=6)
        _reload()

        from ui.theme import fit_window
        fit_window(win, 900, 600)

    def _open_import_wizard(self):
        from ui.import_wizard import ImportWizard
        try:
            from lesson_plan_db import current_school_year
            year = current_school_year()
        except Exception:
            year = None
        ImportWizard(self.winfo_toplevel(), self.db, self.base_dir, year)
        self._refresh_stats()

    def _open_settings(self):
        from ui.settings_dialog import SettingsDialog
        dlg = SettingsDialog(self.winfo_toplevel(), self.base_dir, app_dir=self.app_dir)
        self.winfo_toplevel().wait_window(dlg)  # block until Save/Cancel closes dialog
        self._refresh_stats()

    def _switch_profile(self):
        """Ask main.py to show the profile selector via the callback."""
        # Close all child windows first
        for key in list(self._windows):
            win = self._windows.pop(key, None)
            if win:
                try:
                    win.destroy()
                except tk.TclError:
                    pass
        # Call the switch callback provided by main.py
        root = self.winfo_toplevel()
        cb = getattr(root, "_switch_profile_callback", None)
        if cb:
            cb()
