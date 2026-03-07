"""
ui/main_menu.py - Main menu hub for Roka's Resonance
"""

import os
import tkinter as tk
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from PIL import Image, ImageTk
from ui.theme import fs, muted_fg, subtle_fg, link_fg

class MainMenu(ttk.Frame):
    def __init__(self, parent, db, base_dir: str, app_dir: str = None, teacher_name: str = ""):
        super().__init__(parent)
        self.db = db
        self.base_dir = base_dir
        self.app_dir = app_dir or base_dir
        self.teacher_name = teacher_name
        self._windows = {}  # key -> Toplevel; tracks open manager windows
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
            # Resize to fit the banner height
            target_h = 110
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
        text_frame.pack(side=LEFT, fill=BOTH, expand=True, pady=(18, 16))

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
        stats_inner.pack(pady=10)

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

        # ── Footer ────────────────────────────────────────────────────────────
        # Pack footer BEFORE btn_area so it reserves bottom space first.
        footer = ttk.Frame(self)
        footer.pack(fill=X, side=BOTTOM)
        ttk.Separator(footer).pack(fill=X)

        footer_inner = ttk.Frame(footer)
        footer_inner.pack(pady=8)

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

        # ── Main Buttons ──────────────────────────────────────────────────────
        btn_area = ttk.Frame(self)
        btn_area.pack(fill=BOTH, expand=True, padx=40, pady=(20, 16))

        # ── Instrument Inventory group ───────────────────────────────────────
        ttk.Label(
            btn_area,
            text="Instrument Inventory",
            font=("Segoe UI", fs(10), "bold"),
            foreground=muted_fg(),
        ).pack(anchor=W, pady=(0, 6))

        self._make_main_button(
            btn_area,
            text="Manage Instrument Inventory",
            subtext="View, add, edit, check out & track instruments",
            icon="🎺",
            command=self._open_inventory,
            style=PRIMARY,
            row=0
        )

        self._make_main_button(
            btn_area,
            text="Active Checkouts",
            subtext="See all instruments currently checked out",
            icon="📋",
            command=self._open_active_checkouts,
            style=WARNING,
            row=1
        )

        self._make_main_button(
            btn_area,
            text="Manage Students",
            subtext="View and edit student records by school year",
            icon="🎓",
            command=self._open_students,
            style=INFO,
            row=2
        )

        # ── Sheet Music group ────────────────────────────────────────────────
        ttk.Separator(btn_area).pack(fill=X, pady=(16, 12))

        ttk.Label(
            btn_area,
            text="Sheet Music",
            font=("Segoe UI", fs(10), "bold"),
            foreground=muted_fg(),
        ).pack(anchor=W, pady=(0, 6))

        self._make_main_button(
            btn_area,
            text="Music Manager",
            subtext="Manage sheet music library",
            icon="🎼",
            command=self._open_music_manager,
            style=SECONDARY,
            row=3
        )

    def _make_stat(self, parent, value: str, label: str, col: int):
        f = ttk.Frame(parent)
        f.grid(row=0, column=col, padx=20)
        val_lbl = ttk.Label(f, text=value, font=("Segoe UI", fs(20), "bold"), bootstyle=PRIMARY)
        val_lbl.pack()
        ttk.Label(f, text=label, font=("Segoe UI", fs(8)), foreground=muted_fg()).pack()
        return val_lbl

    def _make_main_button(self, parent, text, subtext, icon, command, style, row):
        frame = ttk.Frame(parent)
        frame.pack(fill=X, pady=6)

        btn = ttk.Button(
            frame,
            text=f"  {icon}  {text}",
            command=command,
            bootstyle=style,
            width=40,
        )
        btn.pack(fill=X, ipady=fs(10), padx=0)

        ttk.Label(
            frame,
            text=f"      {subtext}",
            font=("Segoe UI", fs(8)),
            foreground=muted_fg(),
        ).pack(anchor=W, pady=(2, 0))

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
                text="INSTRUMENTS",
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
                # Music count comes from the choir DB, not the band DB
                try:
                    from database import Database
                    choir_db = Database(os.path.join(self.base_dir, "choir_music.db"))
                    music_count = choir_db.get_stats().get("sheet_music", 0)
                except Exception:
                    music_count = 0
            else:
                co, total = stats["checked_out"], stats["total"]
                self._stat_checkedout.config(text=f"{co} / {total}")
                self._stat_repair.config(text=str(stats["in_repair"]))
                music_count = stats.get("sheet_music", 0)
            self._stat_music.config(text=str(music_count))
        except Exception:
            pass

    def _schedule_refresh(self):
        """Periodic 30-second refresh loop — only one instance should run at a time."""
        self._refresh_stats()
        self._refresh_after_id = self.after(30000, self._schedule_refresh)

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
        win.title("Manage Instrument Inventory — Roka's Resonance")
        win.state("zoomed")
        manager = InventoryManager(win, self.db, self.base_dir)
        manager.pack(fill=BOTH, expand=True)
        win.protocol("WM_DELETE_WINDOW", lambda: self._on_child_close("inventory"))
        self._windows["inventory"] = win

    def _open_students(self):
        if self._raise_or_open("students"):
            return
        from ui.student_manager import StudentManager
        win = ttk.Toplevel(self.winfo_toplevel())
        win.title("Student Manager — Roka's Resonance")
        win.geometry("1000x650")
        win.resizable(True, True)
        manager = StudentManager(win, self.db)
        manager.pack(fill=BOTH, expand=True)
        win.protocol("WM_DELETE_WINDOW", lambda: self._on_child_close("students"))
        self._windows["students"] = win

    def _open_music_manager(self):
        if self._raise_or_open("music"):
            return
        from ui.music_manager import MusicManager
        from ui.settings_dialog import load_settings

        settings = load_settings(self.base_dir)
        program_type = (settings.get("teacher") or {}).get("program_type", "band")

        if program_type == "choir":
            from database import Database
            choir_db_path = os.path.join(self.base_dir, "choir_music.db")
            music_db = Database(choir_db_path)
            title = "Choir Music Manager — Roka's Resonance"
        else:
            music_db = self.db
            title = "Music Manager — Roka's Resonance"

        win = ttk.Toplevel(self.winfo_toplevel())
        win.title(title)
        win.state("zoomed")
        manager = MusicManager(win, music_db, self.base_dir, mode=program_type)
        manager.pack(fill=BOTH, expand=True)
        win.protocol("WM_DELETE_WINDOW", lambda: self._on_child_close("music"))
        self._windows["music"] = win

    def _open_active_checkouts(self):
        if self._raise_or_open("checkouts"):
            return
        self._show_active_checkouts_window()

    def _show_active_checkouts_window(self):
        win = ttk.Toplevel(self.winfo_toplevel())
        win.title("Active Checkouts — Roka's Resonance")
        win.geometry("900x600")
        win.protocol("WM_DELETE_WINDOW", lambda: self._on_child_close("checkouts"))
        self._windows["checkouts"] = win

        ttk.Label(win, text="Currently Checked Out Instruments",
                  font=("Segoe UI", 13, "bold"), bootstyle=PRIMARY).pack(pady=(14, 4))

        cols = ("Student", "Instrument", "Category", "Barcode", "Date Checked Out")
        tree_frame = ttk.Frame(win)
        tree_frame.pack(fill=BOTH, expand=True, padx=14, pady=8)

        scrollbar = ttk.Scrollbar(tree_frame, orient=VERTICAL)
        tree = ttk.Treeview(tree_frame, columns=cols, show="headings",
                            yscrollcommand=scrollbar.set, bootstyle=PRIMARY)
        scrollbar.config(command=tree.yview)

        widths = [180, 200, 120, 100, 120]
        _stretch = {"Student", "Instrument"}
        for col, w in zip(cols, widths):
            tree.heading(col, text=col, anchor=W)
            tree.column(col, width=w, anchor=W, stretch=col in _stretch)

        scrollbar.pack(side=RIGHT, fill=Y)
        tree.pack(fill=BOTH, expand=True)

        checkouts = self.db.get_all_active_checkouts()
        for c in checkouts:
            tree.insert("", "end", values=(
                c["student_name"] or "",
                c["description"] or "",
                c["category"] or "",
                c["barcode"] or c["district_no"] or "",
                c["date_assigned"] or "",
            ))

        if not checkouts:
            ttk.Label(win, text="No instruments currently checked out.",
                      font=("Segoe UI", 10), foreground="#888").pack(pady=20)

        ttk.Label(win, text=f"{len(checkouts)} instrument(s) currently checked out",
                  font=("Segoe UI", 9), foreground="#666").pack(pady=6)

    def _open_settings(self):
        from ui.settings_dialog import SettingsDialog
        dlg = SettingsDialog(self.winfo_toplevel(), self.base_dir)
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
