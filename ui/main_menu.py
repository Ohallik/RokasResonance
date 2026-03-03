"""
ui/main_menu.py - Main menu hub for Roka's Resonance
"""

import os
import tkinter as tk
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from PIL import Image, ImageTk

class MainMenu(ttk.Frame):
    def __init__(self, parent, db, base_dir: str, app_dir: str = None, teacher_name: str = ""):
        super().__init__(parent)
        self.db = db
        self.base_dir = base_dir
        self.app_dir = app_dir or base_dir
        self.teacher_name = teacher_name
        self._windows = {}  # key -> Toplevel; tracks open manager windows
        self._build()
        self._refresh_stats()

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
            font=("Segoe UI", 22, "bold"),
            bootstyle=(INVERSE, PRIMARY),
            anchor=CENTER,
        ).pack(fill=X, pady=(0, 2))

        ttk.Label(
            text_frame,
            text=f"{self.teacher_name}  •  Instrument Management" if self.teacher_name else "Instrument Management",
            font=("Segoe UI", 10),
            bootstyle=(INVERSE, PRIMARY),
            anchor=CENTER,
        ).pack(fill=X)

        # ── Stats Bar ─────────────────────────────────────────────────────────
        stats_outer = ttk.Frame(self, bootstyle=SECONDARY)
        stats_outer.pack(fill=X)

        self._stats_frame = ttk.Frame(stats_outer)
        self._stats_frame.pack(pady=12)

        self._stat_total     = self._make_stat(self._stats_frame, "0", "Total Instruments", 0)
        self._stat_available = self._make_stat(self._stats_frame, "0", "Available", 1)
        self._stat_checkedout = self._make_stat(self._stats_frame, "0", "Checked Out", 2)
        self._stat_repair    = self._make_stat(self._stats_frame, "0", "In Repair", 3)

        # ── Main Buttons ──────────────────────────────────────────────────────
        btn_area = ttk.Frame(self)
        btn_area.pack(fill=BOTH, expand=True, padx=40, pady=(20, 30))

        # ── Instrument Inventory group ───────────────────────────────────────
        ttk.Label(
            btn_area,
            text="Instrument Inventory",
            font=("Segoe UI", 10, "bold"),
            foreground="#555555",
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
            text="Manage Students",
            subtext="View and edit student records by school year",
            icon="🎓",
            command=self._open_students,
            style=INFO,
            row=1
        )

        self._make_main_button(
            btn_area,
            text="Active Checkouts",
            subtext="See all instruments currently checked out",
            icon="📋",
            command=self._open_active_checkouts,
            style=WARNING,
            row=2
        )

        # ── Sheet Music group ────────────────────────────────────────────────
        ttk.Separator(btn_area).pack(fill=X, pady=(16, 12))

        ttk.Label(
            btn_area,
            text="Sheet Music",
            font=("Segoe UI", 10, "bold"),
            foreground="#555555",
        ).pack(anchor=W, pady=(0, 6))

        self._make_main_button(
            btn_area,
            text="Music Manager",
            subtext="Manage sheet music library and OMR processing",
            icon="🎼",
            command=self._open_music_manager,
            style=SECONDARY,
            row=3
        )

        # ── Footer ────────────────────────────────────────────────────────────
        footer = ttk.Frame(self)
        footer.pack(fill=X, side=BOTTOM)
        ttk.Separator(footer).pack(fill=X)

        footer_inner = ttk.Frame(footer)
        footer_inner.pack(pady=8)

        ttk.Label(
            footer_inner,
            text=f"Roka's Resonance  •  {self.teacher_name}" if self.teacher_name else "Roka's Resonance",
            font=("Segoe UI", 8),
            foreground="#999999",
        ).pack(side=LEFT)

        ttk.Label(
            footer_inner,
            text="  •  ",
            font=("Segoe UI", 8),
            foreground="#999999",
        ).pack(side=LEFT)

        switch_lbl = ttk.Label(
            footer_inner,
            text="Switch Profile",
            font=("Segoe UI", 8, "underline"),
            foreground="#4A90D9",
            cursor="hand2",
        )
        switch_lbl.pack(side=LEFT)
        switch_lbl.bind("<Button-1>", lambda e: self._switch_profile())

    def _make_stat(self, parent, value: str, label: str, col: int):
        f = ttk.Frame(parent)
        f.grid(row=0, column=col, padx=20)
        val_lbl = ttk.Label(f, text=value, font=("Segoe UI", 20, "bold"), bootstyle=PRIMARY)
        val_lbl.pack()
        ttk.Label(f, text=label, font=("Segoe UI", 8), foreground="#666666").pack()
        return val_lbl

    def _make_main_button(self, parent, text, subtext, icon, command, style, row):
        frame = ttk.Frame(parent, bootstyle=LIGHT)
        frame.pack(fill=X, pady=6)

        btn = ttk.Button(
            frame,
            text=f"  {icon}  {text}",
            command=command,
            bootstyle=style,
            width=40,
        )
        btn.pack(fill=X, ipady=10, padx=0)

        ttk.Label(
            frame,
            text=f"      {subtext}",
            font=("Segoe UI", 8),
            foreground="#666666",
        ).pack(anchor=W, pady=(2, 0))

    def _refresh_stats(self):
        try:
            stats = self.db.get_stats()
            self._stat_total.config(text=str(stats["total"]))
            self._stat_available.config(text=str(stats["available"]))
            self._stat_checkedout.config(text=str(stats["checked_out"]))
            self._stat_repair.config(text=str(stats["in_repair"]))
        except Exception:
            pass
        # Refresh every 30 seconds
        self.after(30000, self._refresh_stats)

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
        win = ttk.Toplevel(self.winfo_toplevel())
        win.title("Music Manager — Roka's Resonance")
        win.state("zoomed")
        manager = MusicManager(win, self.db, self.base_dir)
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
