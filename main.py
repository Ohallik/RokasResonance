"""
main.py - Entry point for Roka's Resonance
Chinook Middle School Band Instrument Inventory Manager
"""

import os
import sys
import threading
import traceback
from datetime import datetime


# ── Early crash handler ──────────────────────────────────────────────────────
# Installed BEFORE the heavier imports (ttkbootstrap etc.) so that any failure
# during startup — including import errors or missing dependencies on an end
# user's machine — still produces a log file we can read.
#
# GUI builds have console=False, so without this any uncaught exception (or
# print/stderr) disappears silently.  We cover four sources of failure:
#   1. main-thread uncaught exceptions   → sys.excepthook
#   2. worker-thread uncaught exceptions → threading.excepthook
#   3. tkinter event-handler crashes     → tk.Tk.report_callback_exception
#   4. stray stdout/stderr               → redirect to the same log when frozen
#
# The log also gets startup/exit markers so "silently blocked before Python
# started" (empty log) is distinguishable from "Python ran, then crashed".

_FROZEN = getattr(sys, "frozen", False)  # True when running from PyInstaller bundle


def _log_path() -> str:
    localappdata = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(localappdata, "RokasResonance", "crash.log")


def _log_line(line: str):
    try:
        path = _log_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(line.rstrip() + "\n")
    except Exception:
        pass


def _log_exception(label: str, exc_type, exc_value, exc_tb):
    try:
        path = _log_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write("\n" + "=" * 72 + "\n")
            f.write(f"{label} at {datetime.now().isoformat()}\n")
            f.write(f"thread : {threading.current_thread().name}\n")
            f.write(f"python : {sys.version.splitlines()[0]}\n")
            f.write(f"exe    : {sys.executable}\n")
            f.write(f"argv   : {sys.argv}\n")
            f.write(f"cwd    : {os.getcwd()}\n")
            f.write("-" * 72 + "\n")
            traceback.print_exception(exc_type, exc_value, exc_tb, file=f)
    except Exception:
        pass  # absolutely last resort — don't let the crash handler itself crash


def _excepthook(exc_type, exc_value, exc_tb):
    _log_exception("UNCAUGHT (main thread)", exc_type, exc_value, exc_tb)


def _threading_excepthook(args):
    _log_exception(
        f"UNCAUGHT (thread: {args.thread.name if args.thread else '?'})",
        args.exc_type, args.exc_value, args.exc_traceback,
    )


sys.excepthook = _excepthook
threading.excepthook = _threading_excepthook


# When frozen, redirect stdout/stderr into the log so library prints (and the
# many traceback.print_exc() calls throughout the codebase) don't vanish.
# Leave alone when running from source so the dev console still works.
if _FROZEN:
    class _LogStream:
        def __init__(self, prefix: str):
            self._prefix = prefix
        def write(self, data: str):
            if not data:
                return
            for line in data.rstrip("\n").split("\n"):
                _log_line(f"[{self._prefix}] {line}")
        def flush(self):
            pass
        def isatty(self):
            return False

    sys.stdout = _LogStream("stdout")
    sys.stderr = _LogStream("stderr")


_log_line("\n" + "#" * 72)
_log_line(f"STARTUP at {datetime.now().isoformat()} — frozen={_FROZEN}")
_log_line(f"exe={sys.executable}")
_log_line(f"argv={sys.argv}")


import json
import shutil
import tkinter as tk
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from ttkbootstrap.dialogs import Messagebox, Querybox


# Tkinter callback crashes — e.g. a button handler raises.  Tk catches these
# and by default prints to stderr (which we've already redirected when frozen,
# but this gives a clearer label).
def _tk_callback_exception(self, exc_type, exc_value, exc_tb):
    _log_exception("UNCAUGHT (tk callback)", exc_type, exc_value, exc_tb)

tk.Tk.report_callback_exception = _tk_callback_exception

# Ensure the app directory is in sys.path
APP_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, APP_DIR)

from database import Database
from ui.main_menu import MainMenu

VERSION = "v0.9.0"

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
        self.dialog.resizable(False, False)
        self.dialog.grab_set()
        self.dialog.protocol("WM_DELETE_WINDOW", self._on_close)

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

        from ui.theme import fit_window
        fit_window(self.dialog, 420, 380)

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
    dialog.resizable(False, False)
    dialog.grab_set()

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

    from ui.theme import fit_window
    fit_window(dialog, 500, 320)

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


def _run_backups(db, data_dir: str, profile_name: str):
    """Run local + external backup for the given profile. Non-fatal: errors print only."""
    try:
        db.backup()
    except Exception:
        import traceback
        traceback.print_exc()

    from ui.settings_dialog import load_settings as _load_settings
    ext_path = (_load_settings(data_dir).get("backup") or {}).get("external_path", "").strip()
    if ext_path:
        try:
            db.backup_to_external(ext_path, profile_name)
        except Exception:
            import traceback
            traceback.print_exc()


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
    _run_backups(db, data_dir, profile_name)
    db.relink_checkouts_to_students()

    # Stash current profile state on the app so the close handler can back it up
    app._current_db = db
    app._current_data_dir = data_dir
    app._current_profile_name = profile_name

    app.title(f"Roka's Resonance — {profile_name}")

    # Run first-time import if needed
    if not os.path.exists(import_flag):
        app.after(200, lambda: run_first_import(db, app, import_flag))

    menu = MainMenu(app, db, base_dir=data_dir, app_dir=APP_DIR, teacher_name=profile_name, version=VERSION)
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
        NORMAL_FONT_SCALE, LARGE_FONT_SCALE, EXTRA_LARGE_FONT_SCALE,
    )
    startup_theme, startup_font_size = _resolve_startup_display(profiles, last_used)
    set_theme_name(startup_theme)
    _scale_map = {
        "normal": NORMAL_FONT_SCALE,
        "large": LARGE_FONT_SCALE,
        "extra_large": EXTRA_LARGE_FONT_SCALE,
    }
    set_font_scale(_scale_map.get(startup_font_size, NORMAL_FONT_SCALE))

    win_w = {"normal": 620, "large": 700, "extra_large": 780}.get(startup_font_size, 620)
    win_h = {"normal": 580, "large": 640, "extra_large": 720}.get(startup_font_size, 580)

    _log_line(f"CHECKPOINT: before ttk.Window (theme={startup_theme})")
    app = ttk.Window(
        title="Roka's Resonance",
        themename=startup_theme,
        size=(win_w, win_h),
        resizable=(True, True),
    )
    _log_line("CHECKPOINT: after ttk.Window")
    app.minsize({"normal": 580, "large": 640, "extra_large": 720}.get(startup_font_size, 580), 650)
    app.withdraw()

    # Apply font scaling after Tk root exists
    apply_global_font_scaling()

    # Pick initial profile (no dialog on first launch)
    if not profiles:
        # Show the main window before the Querybox so the dialog has a visible parent
        # to anchor to — otherwise the prompt renders off-screen on some systems
        # (observed on fresh Windows 11 Enterprise VMs).
        app.deiconify()
        app.update()
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

    # Center and show — clamp to screen so large fonts don't overflow
    app.update_idletasks()
    sw = app.winfo_screenwidth()
    sh = app.winfo_screenheight()
    win_w = min(win_w, sw - 80)
    win_h = min(win_h, sh - 80)
    x = (sw - win_w) // 2
    y = max(20, (sh - win_h) // 2)
    app.geometry(f"{win_w}x{win_h}+{x}+{y}")
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

    # Auto-fit window to actual content, capped at screen size
    app.update_idletasks()
    req_h = app.winfo_reqheight()
    req_w = app.winfo_reqwidth()
    new_h = min(max(win_h, req_h + 4), sh - 80)
    new_w = min(max(win_w, req_w + 4), sw - 80)
    if new_h != win_h or new_w != win_w:
        win_h, win_w = new_h, new_w
        x = (sw - win_w) // 2
        y = max(20, (sh - win_h) // 2)
        app.geometry(f"{win_w}x{win_h}+{x}+{y}")

    def on_close():
        db = getattr(app, "_current_db", None)
        data_dir = getattr(app, "_current_data_dir", None)
        profile_name = getattr(app, "_current_profile_name", None)
        if db and data_dir and profile_name:
            _run_backups(db, data_dir, profile_name)
        app.destroy()

    app.protocol("WM_DELETE_WINDOW", on_close)

    _log_line(f"REACHED mainloop at {datetime.now().isoformat()}")
    app.mainloop()
    _log_line(f"EXITED mainloop at {datetime.now().isoformat()}")


if __name__ == "__main__":
    main()
