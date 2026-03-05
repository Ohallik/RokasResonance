"""
main.py - Entry point for Roka's Resonance
Chinook Middle School Band Instrument Inventory Manager
"""

import json
import os
import shutil
import sys
import tkinter as tk
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from ttkbootstrap.dialogs import Messagebox, Querybox

# Ensure the app directory is in sys.path
APP_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, APP_DIR)

from database import Database
from ui.main_menu import MainMenu

# User data lives in AppData so app-folder updates never touch it
_LOCALAPPDATA = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
APP_DATA_DIR  = os.path.join(_LOCALAPPDATA, "RokasResonance")
PROFILES_DIR  = os.path.join(APP_DATA_DIR, "profiles")
PROFILES_JSON = os.path.join(APP_DATA_DIR, "profiles.json")
CHARMS_DIR = os.path.dirname(APP_DIR)  # Parent of RokasResonance folder

# Files/dirs that belong to a profile (moved during migration)
_PROFILE_ITEMS = [
    "rokas_resonance.db",
    ".imported",
    "backups",
    "sheet_music",
    "checkout_forms",
    "column_prefs.json",
]


# ── Profile helpers ──────────────────────────────────────────────────────────

def _load_profiles():
    """Return (profile_names: list[str], last_used: str|None)."""
    if not os.path.exists(PROFILES_JSON):
        return [], None
    try:
        with open(PROFILES_JSON, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("profiles", []), data.get("last_used")
    except Exception:
        return [], None


def _save_profiles(profiles: list[str], last_used: str | None = None):
    with open(PROFILES_JSON, "w", encoding="utf-8") as f:
        json.dump({"profiles": profiles, "last_used": last_used}, f, indent=2)


def _migrate_to_appdata():
    """One-time migration: move profiles from the app folder to AppData.
    Runs silently on the first launch after an update that introduced AppData storage.
    """
    old_json = os.path.join(APP_DIR, "profiles.json")
    old_profiles_dir = os.path.join(APP_DIR, "profiles")

    # Nothing to do if already migrated, or no old data exists
    if os.path.exists(PROFILES_JSON) or not os.path.exists(old_json):
        return

    os.makedirs(APP_DATA_DIR, exist_ok=True)

    if os.path.exists(old_profiles_dir):
        shutil.move(old_profiles_dir, PROFILES_DIR)

    shutil.move(old_json, PROFILES_JSON)


def _migrate_legacy_data():
    """One-time migration: move root-level data into profiles/Meagan R. Mangum/."""
    legacy_db = os.path.join(APP_DIR, "rokas_resonance.db")
    if os.path.exists(PROFILES_JSON) or not os.path.exists(legacy_db):
        return  # Already migrated or no data to migrate

    profile_name = "Meagan R. Mangum"
    dest = os.path.join(PROFILES_DIR, profile_name)
    os.makedirs(dest, exist_ok=True)

    for item in _PROFILE_ITEMS:
        src = os.path.join(APP_DIR, item)
        if os.path.exists(src):
            shutil.move(src, os.path.join(dest, item))

    _save_profiles([profile_name], last_used=profile_name)


def _create_profile(name: str):
    """Create a new empty profile directory."""
    dest = os.path.join(PROFILES_DIR, name)
    os.makedirs(dest, exist_ok=True)
    # Pre-create .imported so legacy Charms import doesn't run
    with open(os.path.join(dest, ".imported"), "w") as f:
        f.write("imported")

    profiles, last = _load_profiles()
    if name not in profiles:
        profiles.append(name)
    _save_profiles(profiles, last)


def _delete_profile(name: str):
    """Remove a profile and its data."""
    dest = os.path.join(PROFILES_DIR, name)
    if os.path.exists(dest):
        shutil.rmtree(dest)

    profiles, last = _load_profiles()
    if name in profiles:
        profiles.remove(name)
    if last == name:
        last = profiles[0] if profiles else None
    _save_profiles(profiles, last)


# ── Profile Selector Dialog ──────────────────────────────────────────────────

class ProfileSelector:
    """Modal dialog for choosing or creating a teacher profile."""

    def __init__(self, parent):
        self.selected = None

        self.dialog = ttk.Toplevel(parent)
        self.dialog.title("Select Teacher Profile — Roka's Resonance")
        self.dialog.geometry("420x380")
        self.dialog.resizable(False, False)
        self.dialog.grab_set()
        self.dialog.protocol("WM_DELETE_WINDOW", self._on_close)

        # Center on screen
        self.dialog.update_idletasks()
        x = (self.dialog.winfo_screenwidth() - 420) // 2
        y = (self.dialog.winfo_screenheight() - 380) // 2
        self.dialog.geometry(f"+{x}+{y}")

        ttk.Label(
            self.dialog,
            text="Teacher Profiles",
            font=("Segoe UI", 14, "bold"),
            bootstyle=PRIMARY,
        ).pack(pady=(18, 4))

        ttk.Label(
            self.dialog,
            text="Select a profile to open, or create a new one.",
            font=("Segoe UI", 9),
            foreground="#666",
        ).pack(pady=(0, 12))

        # Listbox
        list_frame = ttk.Frame(self.dialog)
        list_frame.pack(fill=BOTH, expand=True, padx=30, pady=(0, 10))

        scrollbar = ttk.Scrollbar(list_frame, orient=VERTICAL)
        self.listbox = tk.Listbox(
            list_frame,
            font=("Segoe UI", 11),
            activestyle="dotbox",
            selectmode=tk.SINGLE,
            yscrollcommand=scrollbar.set,
        )
        scrollbar.config(command=self.listbox.yview)
        scrollbar.pack(side=RIGHT, fill=Y)
        self.listbox.pack(fill=BOTH, expand=True)
        self.listbox.bind("<Double-1>", lambda e: self._open())

        # Populate
        profiles, last_used = _load_profiles()
        for p in profiles:
            self.listbox.insert(tk.END, p)
        # Pre-select last used
        if last_used and last_used in profiles:
            idx = profiles.index(last_used)
            self.listbox.selection_set(idx)
            self.listbox.see(idx)
        elif profiles:
            self.listbox.selection_set(0)

        # Buttons
        btn_frame = ttk.Frame(self.dialog)
        btn_frame.pack(fill=X, padx=30, pady=(0, 18))

        ttk.Button(
            btn_frame, text="Open", bootstyle=PRIMARY, command=self._open
        ).pack(side=LEFT, padx=(0, 6))

        ttk.Button(
            btn_frame, text="New Profile", bootstyle=SUCCESS, command=self._new
        ).pack(side=LEFT, padx=6)

        ttk.Button(
            btn_frame, text="Delete", bootstyle=DANGER, command=self._delete
        ).pack(side=LEFT, padx=6)

        ttk.Button(
            btn_frame, text="Cancel", bootstyle=SECONDARY, command=self._on_close
        ).pack(side=RIGHT)

    def _open(self):
        sel = self.listbox.curselection()
        if not sel:
            return
        self.selected = self.listbox.get(sel[0])
        self.dialog.destroy()

    def _new(self):
        name = Querybox.get_string(
            prompt="Enter the teacher's full name:",
            title="New Profile",
            parent=self.dialog,
        )
        if not name or not name.strip():
            return
        name = name.strip()
        profiles, _ = _load_profiles()
        if name in profiles:
            Messagebox.show_warning(
                f"A profile named '{name}' already exists.",
                title="Duplicate Profile",
                parent=self.dialog,
            )
            return
        _create_profile(name)
        self.listbox.insert(tk.END, name)
        # Select the new one
        self.listbox.selection_clear(0, tk.END)
        self.listbox.selection_set(tk.END)
        self.listbox.see(tk.END)

    def _delete(self):
        sel = self.listbox.curselection()
        if not sel:
            return
        name = self.listbox.get(sel[0])
        profiles, _ = _load_profiles()
        if len(profiles) <= 1:
            Messagebox.show_warning(
                "Cannot delete the only remaining profile.",
                title="Cannot Delete",
                parent=self.dialog,
            )
            return
        answer = Messagebox.yesno(
            f"Are you sure you want to delete the profile '{name}'?\n\n"
            f"This will permanently remove all of their data\n"
            f"(database, sheet music, backups, etc.).",
            title="Confirm Delete",
            parent=self.dialog,
        )
        if answer != "Yes":
            return
        _delete_profile(name)
        self.listbox.delete(sel[0])
        if self.listbox.size() > 0:
            self.listbox.selection_set(0)

    def _on_close(self):
        self.selected = None
        self.dialog.destroy()

    def wait(self):
        self.dialog.wait_window()
        return self.selected


# ── First-time import (legacy Charms data) ───────────────────────────────────

def run_first_import(db: Database, parent_window, import_flag: str):
    """Show import progress dialog and run the Excel import."""
    import threading
    from importer import run_full_import

    dialog = ttk.Toplevel(parent_window)
    dialog.title("First Run — Importing Inventory Data")
    dialog.geometry("500x320")
    dialog.resizable(False, False)
    dialog.grab_set()

    # Center on screen
    dialog.update_idletasks()
    x = (dialog.winfo_screenwidth() - 500) // 2
    y = (dialog.winfo_screenheight() - 320) // 2
    dialog.geometry(f"+{x}+{y}")

    ttk.Label(
        dialog,
        text="Importing your inventory data...",
        font=("Segoe UI", 12, "bold"),
        bootstyle=PRIMARY
    ).pack(pady=(20, 5))

    ttk.Label(
        dialog,
        text="This only happens once. Please wait.",
        font=("Segoe UI", 9)
    ).pack(pady=(0, 12))

    progress = ttk.Progressbar(dialog, mode="indeterminate", bootstyle=PRIMARY)
    progress.pack(fill=X, padx=30, pady=4)
    progress.start(10)

    log_frame = ttk.Frame(dialog)
    log_frame.pack(fill=BOTH, expand=True, padx=20, pady=8)

    log_text = tk.Text(log_frame, height=8, font=("Consolas", 8), state="disabled",
                       bg="#F8F8F8", relief="flat", bd=1)
    log_text.pack(fill=BOTH, expand=True)

    def log(msg):
        log_text.config(state="normal")
        log_text.insert("end", msg + "\n")
        log_text.see("end")
        log_text.config(state="disabled")
        dialog.update()

    def do_import():
        try:
            run_full_import(db, base_dir=CHARMS_DIR, progress_callback=log)
            with open(import_flag, "w") as f:
                f.write("imported")
        except Exception as e:
            log(f"Warning: {e}")
        finally:
            progress.stop()
            dialog.after(500, dialog.destroy)

    thread = threading.Thread(target=do_import, daemon=True)
    thread.start()
    dialog.wait_window()


# ── Main ─────────────────────────────────────────────────────────────────────

def _load_profile(app, profile_name: str):
    """Set up DB and menu for the given profile. Returns the menu widget."""
    # Save last-used
    profiles, _ = _load_profiles()
    _save_profiles(profiles, last_used=profile_name)

    # Set up data directory
    data_dir = os.path.join(PROFILES_DIR, profile_name)
    os.makedirs(data_dir, exist_ok=True)
    db_path = os.path.join(data_dir, "rokas_resonance.db")
    import_flag = os.path.join(data_dir, ".imported")

    db = Database(db_path)
    db.backup()
    db.relink_checkouts_to_students()

    # External backup (if configured) — non-fatal, errors go to console only
    from ui.settings_dialog import load_settings as _load_settings
    _ext_path = (_load_settings(data_dir).get("backup") or {}).get("external_path", "").strip()
    if _ext_path:
        try:
            db.backup_to_external(_ext_path, profile_name)
        except Exception:
            import traceback
            traceback.print_exc()

    app.title(f"Roka's Resonance — {profile_name}")

    # Run first-time import if needed
    if not os.path.exists(import_flag):
        app.after(200, lambda: run_first_import(db, app, import_flag))

    menu = MainMenu(app, db, base_dir=data_dir, app_dir=APP_DIR, teacher_name=profile_name)
    menu.pack(fill=BOTH, expand=True)
    return menu


def _resolve_startup_display(profiles, last_used):
    """
    Read display settings from the about-to-be-loaded profile so we can
    create the Window with the correct theme and apply font scaling.
    Returns (theme_name: str, font_size: str).
    """
    from ui.settings_dialog import load_settings
    profile_name = last_used if (last_used and last_used in profiles) else (profiles[0] if profiles else None)
    if profile_name:
        data_dir = os.path.join(PROFILES_DIR, profile_name)
        settings = load_settings(data_dir)
        display = settings.get("display") or {}
        return display.get("theme", "litera"), display.get("font_size", "normal")
    return "litera", "normal"


def main():
    # Move profiles to AppData if coming from an older version
    _migrate_to_appdata()
    # Migrate legacy (pre-profile) data if needed
    _migrate_legacy_data()

    profiles, last_used = _load_profiles()

    # Read saved display preferences before creating the window
    from ui.theme import (
        set_theme_name, set_font_scale, apply_global_font_scaling,
        LARGE_FONT_SCALE,
    )
    startup_theme, startup_font_size = _resolve_startup_display(profiles, last_used)
    set_theme_name(startup_theme)
    if startup_font_size == "large":
        set_font_scale(LARGE_FONT_SCALE)

    win_w = 680 if startup_font_size == "large" else 600
    win_h = 820 if startup_font_size == "large" else 720

    app = ttk.Window(
        title="Roka's Resonance",
        themename=startup_theme,
        size=(win_w, win_h),
        resizable=(True, True),
    )
    app.minsize(520 if startup_font_size == "normal" else 580, 600)
    app.withdraw()

    # Apply font scaling after Tk root exists
    apply_global_font_scaling()

    # Pick initial profile (no dialog on first launch)
    if not profiles:
        name = Querybox.get_string(
            prompt="Welcome! Enter your name to create your profile:",
            title="Create First Profile",
            parent=app,
        )
        if not name or not name.strip():
            app.destroy()
            return
        name = name.strip()
        _create_profile(name)
        profile_name = name
    elif last_used and last_used in profiles:
        profile_name = last_used
    else:
        profile_name = profiles[0]

    # Center and show
    app.update_idletasks()
    sw = app.winfo_screenwidth()
    sh = app.winfo_screenheight()
    x = (sw - win_w) // 2
    y = (sh - win_h) // 2
    app.geometry(f"+{x}+{y}")
    app.deiconify()

    # State holder for the current menu widget
    current_menu = [None]

    def switch_profile():
        """Show profile selector dialog and reload the menu if a new profile is chosen."""
        selector = ProfileSelector(app)
        new_profile = selector.wait()
        if new_profile is None:
            return  # Cancelled
        # Remove old menu
        if current_menu[0]:
            current_menu[0].destroy()
        current_menu[0] = _load_profile(app, new_profile)
        # Re-attach the switch callback
        app._switch_profile_callback = switch_profile

    # Attach the callback so MainMenu._switch_profile can reach it
    app._switch_profile_callback = switch_profile

    current_menu[0] = _load_profile(app, profile_name)

    app.mainloop()


if __name__ == "__main__":
    main()
