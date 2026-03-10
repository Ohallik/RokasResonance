"""
ui/settings_dialog.py - Application settings dialog
"""

import json
import os
import threading
import tkinter as tk
from tkinter import filedialog
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from ttkbootstrap.dialogs import Messagebox

SETTINGS_FILE = "settings.json"
GITHUB_MODELS_ENDPOINT = "https://models.github.ai/inference"
GITHUB_MODELS_CATALOG = "https://models.github.ai/catalog/models"

# Anthropic Claude models (direct API, separate key)
ANTHROPIC_MODELS = [
    "claude-haiku-4-5-20251001",   # fast, low cost
    "claude-sonnet-4-6",            # balanced quality/speed
    "claude-opus-4-6",              # most capable
]

# Default model list (publisher/model format) — shown before "Fetch Models" is clicked.
# Vision-capable models marked with [V]. Low-tier = ~15 RPM, High-tier = ~10 RPM.
GITHUB_MODELS = [
    # OpenAI — low tier, vision  ← recommended for batch image import
    "openai/gpt-4o-mini",       # [V] low tier
    "openai/gpt-4.1-mini",      # [V] low tier
    "openai/gpt-4.1-nano",      # [V] low tier, fastest
    # OpenAI — high tier, vision
    "openai/gpt-4o",            # [V] high tier
    "openai/gpt-4.1",           # [V] high tier
    "openai/gpt-5",             # [V] custom tier
    # Meta Llama — vision
    "meta/llama-3.2-11b-vision-instruct",   # [V] low tier
    "meta/llama-3.2-90b-vision-instruct",   # [V] high tier
    "meta/llama-4-scout-17b-16e-instruct",  # [V] high tier
    # Text-only
    "meta/llama-3.3-70b-instruct",
    "mistral-ai/mistral-small-2503",
    "microsoft/phi-4",
]


def load_settings(base_dir: str) -> dict:
    path = os.path.join(base_dir, SETTINGS_FILE)
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_settings(base_dir: str, settings: dict):
    path = os.path.join(base_dir, SETTINGS_FILE)
    with open(path, "w") as f:
        json.dump(settings, f, indent=2)


class SettingsDialog(ttk.Toplevel):
    def __init__(self, parent, base_dir: str, app_dir: str = None):
        super().__init__(parent)
        self.base_dir = base_dir
        self._app_dir = app_dir
        self._settings = load_settings(base_dir)
        self._show_key = False
        self._show_anthropic_key = False

        self.title("Settings — Roka's Resonance")
        self.resizable(False, True)
        self.grab_set()
        self.lift()

        self._build()
        self._load()

        from ui.theme import fit_window
        fit_window(self, 560, 680)

    # ───────────────────────────────────────────────────── Build UI ────────

    def _build(self):
        # Header
        hdr = ttk.Frame(self, bootstyle=SECONDARY)
        hdr.pack(fill=X)
        ttk.Label(hdr, text="  Settings", font=("Segoe UI", 13, "bold"),
                  bootstyle=(INVERSE, SECONDARY)).pack(pady=12, padx=16, anchor=W)

        # Notebook — Teacher tab first
        nb = ttk.Notebook(self, bootstyle=SECONDARY)
        nb.pack(fill=BOTH, expand=True, padx=12, pady=(10, 0))

        teacher_tab = ttk.Frame(nb)
        nb.add(teacher_tab, text="  Teacher  ")

        display_tab = ttk.Frame(nb)
        nb.add(display_tab, text="  Display  ")

        llm_tab = ttk.Frame(nb)
        nb.add(llm_tab, text="  LLM Configuration  ")

        backup_tab = ttk.Frame(nb)
        nb.add(backup_tab, text="  Backup  ")

        self._build_teacher_tab(teacher_tab)
        self._build_display_tab(display_tab)
        self._build_llm_tab(llm_tab)
        self._build_backup_tab(backup_tab)

        # Bottom buttons
        btn_frame = ttk.Frame(self)
        btn_frame.pack(fill=X, padx=16, pady=12)
        ttk.Button(btn_frame, text="Cancel", bootstyle=(SECONDARY, OUTLINE),
                   command=self.destroy).pack(side=RIGHT, padx=4)
        ttk.Button(btn_frame, text="Save", bootstyle=SUCCESS,
                   command=self._save).pack(side=RIGHT, padx=4)
        self._test_btn = ttk.Button(btn_frame, text="Test Connection",
                                    bootstyle=(INFO, OUTLINE),
                                    command=self._test_connection)
        # Show/hide Test Connection based on active tab (LLM is now index 2)
        def _on_tab_change(event):
            idx = nb.index(nb.select())
            if idx == 2:  # LLM Configuration tab
                self._test_btn.pack(side=LEFT, padx=4)
            else:
                self._test_btn.pack_forget()
        nb.bind("<<NotebookTabChanged>>", _on_tab_change)
        self._nb = nb
        # Teacher tab is first — button starts hidden

    def _build_teacher_tab(self, parent):
        outer = ttk.Frame(parent)
        outer.pack(fill=BOTH, expand=True, padx=20, pady=14)

        ttk.Label(outer, text="Program Type",
                  font=("Segoe UI", 10, "bold")).pack(anchor=W)
        ttk.Label(
            outer,
            text="Select the type of music program you teach. "
                 "The Music Manager will load the appropriate repertoire library for your program.",
            font=("Segoe UI", 9), foreground="#888",
            wraplength=460, justify=LEFT,
        ).pack(anchor=W, pady=(2, 12))

        self._program_type_var = tk.StringVar(value="band")

        for value, label, desc in [
            ("band",  "Band",  "Concert band, jazz band, and marching band repertoire."),
            ("choir", "Choir", "Choral and vocal ensemble repertoire."),
        ]:
            row = ttk.Frame(outer)
            row.pack(fill=X, pady=3)
            ttk.Radiobutton(
                row, text=label, value=value,
                variable=self._program_type_var,
                bootstyle=PRIMARY,
            ).pack(side=LEFT, padx=(0, 10))
            ttk.Label(row, text=desc, font=("Segoe UI", 8),
                      foreground="#888").pack(side=LEFT)

        ttk.Separator(outer, orient=HORIZONTAL).pack(fill=X, pady=(14, 12))

        # ── School info ────────────────────────────────────────────────────
        for label, attr in [
            ("School District", "_school_district_var"),
            ("School Name",     "_school_name_var"),
        ]:
            ttk.Label(outer, text=label,
                      font=("Segoe UI", 9, "bold")).pack(anchor=W)
            var = tk.StringVar()
            setattr(self, attr, var)
            ttk.Entry(outer, textvariable=var, width=40).pack(
                anchor=W, pady=(2, 10))

        ttk.Separator(outer, orient=HORIZONTAL).pack(fill=X, pady=(4, 12))

        ttk.Label(outer, text="External Database",
                  font=("Segoe UI", 10, "bold")).pack(anchor=W)
        ttk.Label(
            outer,
            text="Select a Roka's Resonance database (.db) from another profile to "
                 "view its music library as a read-only source in the Band Music Manager.",
            font=("Segoe UI", 9), foreground="#888",
            wraplength=460, justify=LEFT,
        ).pack(anchor=W, pady=(2, 8))

        self._ext_db_var = tk.StringVar()
        ext_db_row = ttk.Frame(outer)
        ext_db_row.pack(fill=X, pady=(0, 4))
        self._ext_db_entry = ttk.Entry(ext_db_row, textvariable=self._ext_db_var,
                                       state="readonly", width=34)
        self._ext_db_entry.pack(side=LEFT, fill=X, expand=True)
        ttk.Button(ext_db_row, text="Browse…", bootstyle=(SECONDARY, OUTLINE),
                   command=self._browse_external_db).pack(side=LEFT, padx=(6, 0))
        ttk.Button(ext_db_row, text="Clear", bootstyle=(SECONDARY, OUTLINE),
                   command=lambda: self._ext_db_var.set("")).pack(side=LEFT, padx=(4, 0))

        ttk.Label(outer, text="Leave blank to use only your own database.",
                  font=("Segoe UI", 8), foreground="#aaa").pack(anchor=W, pady=(2, 0))

    def _build_display_tab(self, parent):
        from ui.theme import DISPLAY_THEMES, THEME_DESCRIPTIONS
        outer = ttk.Frame(parent)
        outer.pack(fill=BOTH, expand=True, padx=20, pady=14)

        # ── Color Scheme ───────────────────────────────────────────────────
        ttk.Label(outer, text="Color Scheme",
                  font=("Segoe UI", 10, "bold")).pack(anchor=W)
        ttk.Label(
            outer,
            text="Changes take effect immediately after saving.",
            font=("Segoe UI", 8), foreground="#888",
        ).pack(anchor=W, pady=(0, 8))

        self._theme_var = tk.StringVar(value="Classic")

        theme_frame = ttk.Frame(outer)
        theme_frame.pack(fill=X, pady=(0, 4))

        for name, theme_id in DISPLAY_THEMES.items():
            row = ttk.Frame(theme_frame)
            row.pack(fill=X, pady=3)

            rb = ttk.Radiobutton(
                row,
                text=name,
                value=name,
                variable=self._theme_var,
                bootstyle=PRIMARY,
            )
            rb.pack(side=LEFT, padx=(0, 10))

            ttk.Label(row, text=THEME_DESCRIPTIONS[name],
                      font=("Segoe UI", 8), foreground="#888").pack(
                side=LEFT, padx=(4, 0))

        ttk.Separator(outer, orient=HORIZONTAL).pack(fill=X, pady=(14, 12))

        # ── Display Size ───────────────────────────────────────────────────
        ttk.Label(outer, text="Display Size",
                  font=("Segoe UI", 10, "bold")).pack(anchor=W)
        ttk.Label(
            outer,
            text="Changing the display size requires restarting the app.",
            font=("Segoe UI", 8), foreground="#888",
        ).pack(anchor=W, pady=(0, 8))

        self._size_var = tk.StringVar(value="normal")

        size_frame = ttk.Frame(outer)
        size_frame.pack(fill=X)

        sizes = [
            ("normal",      "Normal",
             "Default text sizes (recommended for most displays)."),
            ("large",       "Large",
             "25% larger text — easier to read for accessibility."),
            ("extra_large", "Extra Large",
             "50% larger text — maximum accessibility."),
        ]
        for val, label, desc in sizes:
            row = ttk.Frame(size_frame)
            row.pack(fill=X, pady=3)
            ttk.Radiobutton(
                row, text=label, value=val, variable=self._size_var,
                bootstyle=PRIMARY,
            ).pack(side=LEFT, padx=(0, 10))
            ttk.Label(row, text=desc, font=("Segoe UI", 8),
                      foreground="#888").pack(side=LEFT)

    def _build_llm_tab(self, parent):
        outer = ttk.Frame(parent)
        outer.pack(fill=BOTH, expand=True, padx=20, pady=14)

        # ── Backend toggle ────────────────────────────────────────────────
        ttk.Label(outer, text="AI Backend",
                  font=("Segoe UI", 10, "bold")).pack(anchor=W)

        self._backend_var = tk.StringVar(value="local")

        backend_frame = ttk.Frame(outer)
        backend_frame.pack(fill=X, pady=(4, 0))

        ttk.Radiobutton(
            backend_frame, text="Local API Keys",
            variable=self._backend_var, value="local",
            bootstyle=PRIMARY,
            command=self._on_backend_change,
        ).pack(side=LEFT, padx=(0, 16))
        ttk.Radiobutton(
            backend_frame, text="Claude Proxy",
            variable=self._backend_var, value="proxy",
            bootstyle=PRIMARY,
            command=self._on_backend_change,
        ).pack(side=LEFT)

        ttk.Separator(outer, orient=HORIZONTAL).pack(fill=X, pady=(10, 0))

        # ── Local API Keys section ────────────────────────────────────────
        self._local_frame = ttk.Frame(outer)

        ttk.Label(self._local_frame,
                  text="GitHub API Key  (for GPT, Llama, Mistral, Phi models)",
                  font=("Segoe UI", 9, "bold")).pack(anchor=W, pady=(10, 0))

        saved_key = (self._settings.get("llm") or {}).get("api_key", "").strip()
        env_key = os.environ.get("GITHUB_TOKEN", "")
        if saved_key:
            env_note, env_color = "Key saved in settings below.", "#2a7a2a"
        elif env_key:
            env_note = f"GITHUB_TOKEN env var is set ({len(env_key)} chars) — used as fallback."
            env_color = "#2a7a2a"
        else:
            env_note, env_color = "No key saved. Enter your GitHub personal access token.", "#888"

        ttk.Label(self._local_frame, text=env_note, font=("Segoe UI", 8),
                  foreground=env_color, wraplength=460).pack(anchor=W, pady=(0, 4))

        key_row = ttk.Frame(self._local_frame)
        key_row.pack(fill=X, pady=(0, 10))
        self._key_var = tk.StringVar()
        self._key_entry = ttk.Entry(key_row, textvariable=self._key_var,
                                    show="•", width=44)
        self._key_entry.pack(side=LEFT, fill=X, expand=True)
        self._toggle_btn = ttk.Button(
            key_row, text="Show", bootstyle=(SECONDARY, OUTLINE), width=6,
            command=self._toggle_key_visibility)
        self._toggle_btn.pack(side=LEFT, padx=(6, 0))

        ttk.Separator(self._local_frame, orient=HORIZONTAL).pack(fill=X, pady=(0, 10))

        ttk.Label(self._local_frame, text="Anthropic API Key  (for Claude models)",
                  font=("Segoe UI", 9, "bold")).pack(anchor=W)

        saved_ak = (self._settings.get("llm") or {}).get("anthropic_api_key", "").strip()
        ak_note = "Key saved in settings below." if saved_ak else \
            "No key saved. Get a free key at console.anthropic.com (5 RPM free tier)."
        ak_color = "#2a7a2a" if saved_ak else "#888"
        ttk.Label(self._local_frame, text=ak_note, font=("Segoe UI", 8),
                  foreground=ak_color, wraplength=460).pack(anchor=W, pady=(0, 4))

        anthropic_key_row = ttk.Frame(self._local_frame)
        anthropic_key_row.pack(fill=X, pady=(0, 10))
        self._anthropic_key_var = tk.StringVar()
        self._anthropic_key_entry = ttk.Entry(anthropic_key_row,
                                              textvariable=self._anthropic_key_var,
                                              show="•", width=44)
        self._anthropic_key_entry.pack(side=LEFT, fill=X, expand=True)
        self._anthropic_toggle_btn = ttk.Button(
            anthropic_key_row, text="Show", bootstyle=(SECONDARY, OUTLINE), width=6,
            command=self._toggle_anthropic_key_visibility)
        self._anthropic_toggle_btn.pack(side=LEFT, padx=(6, 0))

        ttk.Separator(self._local_frame, orient=HORIZONTAL).pack(fill=X, pady=(0, 10))

        ttk.Label(self._local_frame, text="Model",
                  font=("Segoe UI", 9, "bold")).pack(anchor=W)
        self._model_hint = ttk.Label(
            self._local_frame,
            text="Claude models use Anthropic key. All others use GitHub key.",
            font=("Segoe UI", 8), foreground="#888")
        self._model_hint.pack(anchor=W, pady=(0, 4))

        model_row = ttk.Frame(self._local_frame)
        model_row.pack(fill=X, pady=(0, 14))
        all_models = ANTHROPIC_MODELS + GITHUB_MODELS
        self._model_var = tk.StringVar(value=all_models[0])
        self._model_combo = ttk.Combobox(model_row, textvariable=self._model_var,
                                         values=all_models, width=34)
        self._model_combo.pack(side=LEFT)
        self._fetch_btn = ttk.Button(
            model_row, text="Fetch GitHub Models", bootstyle=(SECONDARY, OUTLINE),
            command=self._fetch_models)
        self._fetch_btn.pack(side=LEFT, padx=(6, 0))

        # ── Claude Proxy section ──────────────────────────────────────────
        self._proxy_frame = ttk.Frame(outer)

        ttk.Label(self._proxy_frame,
                  text="Proxy Endpoint",
                  font=("Segoe UI", 9, "bold")).pack(anchor=W, pady=(10, 0))
        ttk.Label(self._proxy_frame,
                  text="The base URL of your deployed proxy (e.g. https://your-app.railway.app)",
                  font=("Segoe UI", 8), foreground="#888").pack(anchor=W, pady=(0, 4))
        self._proxy_endpoint_var = tk.StringVar()
        ttk.Entry(self._proxy_frame, textvariable=self._proxy_endpoint_var,
                  width=50).pack(fill=X, pady=(0, 10))

        ttk.Separator(self._proxy_frame, orient=HORIZONTAL).pack(fill=X, pady=(0, 10))

        ttk.Label(self._proxy_frame, text="Proxy Token",
                  font=("Segoe UI", 9, "bold")).pack(anchor=W)
        ttk.Label(self._proxy_frame,
                  text="The secret token required by your proxy (x-proxy-token).",
                  font=("Segoe UI", 8), foreground="#888").pack(anchor=W, pady=(0, 4))
        proxy_token_row = ttk.Frame(self._proxy_frame)
        proxy_token_row.pack(fill=X, pady=(0, 14))
        self._proxy_token_var = tk.StringVar()
        self._proxy_token_entry = ttk.Entry(proxy_token_row,
                                            textvariable=self._proxy_token_var,
                                            show="•", width=44)
        self._proxy_token_entry.pack(side=LEFT, fill=X, expand=True)
        self._proxy_token_toggle_btn = ttk.Button(
            proxy_token_row, text="Show", bootstyle=(SECONDARY, OUTLINE), width=6,
            command=self._toggle_proxy_token_visibility)
        self._proxy_token_toggle_btn.pack(side=LEFT, padx=(6, 0))
        self._show_proxy_token = False

        ttk.Label(self._proxy_frame,
                  text="Note: Import Music (vision) routes through the proxy when enabled. "
                       "Text enrichment and chat also use the proxy.",
                  font=("Segoe UI", 8), foreground="#888",
                  wraplength=460, justify=LEFT).pack(anchor=W, pady=(0, 8))

        # Status area (shared)
        self._status_frame = ttk.Frame(outer)
        self._status_frame.pack(fill=X, side=BOTTOM)
        self._refresh_status()

        # Show correct section for current backend
        self._on_backend_change()

    def _build_backup_tab(self, parent):
        outer = ttk.Frame(parent)
        outer.pack(fill=BOTH, expand=True, padx=20, pady=14)

        ttk.Label(outer, text="External Backup Folder",
                  font=("Segoe UI", 10, "bold")).pack(anchor=W)
        ttk.Label(
            outer,
            text="Choose a folder on a network drive, OneDrive, or USB drive.\n"
                 "A copy of your database is saved here automatically each time\n"
                 "the app starts. Up to 30 backups are kept per profile.",
            font=("Segoe UI", 9),
            foreground="#888",
            justify=LEFT,
        ).pack(anchor=W, pady=(2, 10))

        # Path row
        path_row = ttk.Frame(outer)
        path_row.pack(fill=X, pady=(0, 6))

        self._backup_path_var = tk.StringVar()
        path_entry = ttk.Entry(path_row, textvariable=self._backup_path_var, width=38)
        path_entry.pack(side=LEFT, fill=X, expand=True)

        ttk.Button(
            path_row, text="Browse…", bootstyle=(SECONDARY, OUTLINE),
            command=self._browse_backup_folder,
        ).pack(side=LEFT, padx=(6, 0))

        ttk.Label(
            outer,
            text="Leave blank to use only the local backup folder.",
            font=("Segoe UI", 8), foreground="#aaa",
        ).pack(anchor=W, pady=(0, 16))

        ttk.Separator(outer, orient=HORIZONTAL).pack(fill=X, pady=(0, 14))

        # Back Up Now row
        ttk.Label(outer, text="Manual Backup",
                  font=("Segoe UI", 10, "bold")).pack(anchor=W)
        ttk.Label(
            outer,
            text="Back up immediately to both the local and external folders.",
            font=("Segoe UI", 9), foreground="#888",
        ).pack(anchor=W, pady=(2, 8))

        backup_btn_row = ttk.Frame(outer)
        backup_btn_row.pack(anchor=W)

        self._backup_now_btn = ttk.Button(
            backup_btn_row, text="Back Up Now", bootstyle=PRIMARY,
            command=self._backup_now,
        )
        self._backup_now_btn.pack(side=LEFT)

        self._backup_status_lbl = ttk.Label(
            backup_btn_row, text="", font=("Segoe UI", 8), foreground="#555",
        )
        self._backup_status_lbl.pack(side=LEFT, padx=(10, 0))

    # ───────────────────────────────────────────────────── Logic ───────────

    def _browse_external_db(self):
        path = filedialog.askopenfilename(
            title="Select External Database",
            parent=self,
            initialdir=os.path.expanduser("~"),
            filetypes=[("Database files", "*.db"), ("All files", "*.*")],
        )
        if path:
            self._ext_db_entry.config(state="normal")
            self._ext_db_var.set(path)
            self._ext_db_entry.config(state="readonly")

    def _browse_backup_folder(self):
        folder = filedialog.askdirectory(
            title="Choose External Backup Folder",
            parent=self,
            initialdir=self._backup_path_var.get() or os.path.expanduser("~"),
        )
        if folder:
            self._backup_path_var.set(folder)

    def _backup_now(self):
        """Run both local and external backup immediately."""
        self._backup_now_btn.config(state="disabled")
        self._backup_status_lbl.config(text="Backing up…", foreground="#555")

        # Read path from field (not yet saved)
        external_path = self._backup_path_var.get().strip()
        base_dir = self.base_dir
        profile_name = os.path.basename(base_dir)

        def _run():
            msgs = []
            try:
                from database import Database
                db_path = os.path.join(base_dir, "rokas_resonance.db")
                db = Database(db_path)
                local_path = db.backup()
                if local_path:
                    msgs.append(f"Local: {os.path.basename(local_path)}")
            except Exception as e:
                msgs.append(f"Local backup failed: {e}")

            if external_path:
                try:
                    from database import Database
                    db_path = os.path.join(base_dir, "rokas_resonance.db")
                    db = Database(db_path)
                    ext_path = db.backup_to_external(external_path, profile_name)
                    msgs.append(f"External: saved")
                except Exception as e:
                    msgs.append(f"External failed: {e}")

            self.after(0, self._on_backup_done, msgs)

        threading.Thread(target=_run, daemon=True).start()

    def _on_backup_done(self, msgs):
        self._backup_now_btn.config(state="normal")
        has_error = any("failed" in m.lower() for m in msgs)
        color = "#CC0000" if has_error else "#2a7a2a"
        self._backup_status_lbl.config(text="  ".join(msgs), foreground=color)

    def _refresh_status(self):
        for w in self._status_frame.winfo_children():
            w.destroy()
        backend = getattr(self, "_backend_var", None)
        if backend and backend.get() == "proxy":
            endpoint = self._proxy_endpoint_var.get().strip()
            token = self._proxy_token_var.get().strip()
            if endpoint and token:
                msg, style = "Claude Proxy configured.", SUCCESS
            else:
                msg, style = "Claude Proxy selected — enter endpoint and token.", WARNING
        else:
            saved_key = (self._settings.get("llm") or {}).get("api_key", "").strip()
            env_key = os.environ.get("GITHUB_TOKEN", "")
            if saved_key:
                msg, style = "Custom API key configured.", SUCCESS
            elif env_key:
                msg, style = "Using GITHUB_TOKEN from environment.", INFO
            else:
                msg, style = "No API key available — AI features disabled.", WARNING
        ttk.Label(self._status_frame, text=msg, font=("Segoe UI", 8),
                  bootstyle=style).pack(anchor=W)

    def _on_backend_change(self):
        if self._backend_var.get() == "proxy":
            self._local_frame.pack_forget()
            self._proxy_frame.pack(fill=X)
        else:
            self._proxy_frame.pack_forget()
            self._local_frame.pack(fill=X)
        self._refresh_status()

    def _toggle_proxy_token_visibility(self):
        self._show_proxy_token = not self._show_proxy_token
        self._proxy_token_entry.config(show="" if self._show_proxy_token else "•")
        self._proxy_token_toggle_btn.config(
            text="Hide" if self._show_proxy_token else "Show")

    def _toggle_key_visibility(self):
        self._show_key = not self._show_key
        self._key_entry.config(show="" if self._show_key else "•")
        self._toggle_btn.config(text="Hide" if self._show_key else "Show")

    def _toggle_anthropic_key_visibility(self):
        self._show_anthropic_key = not self._show_anthropic_key
        self._anthropic_key_entry.config(show="" if self._show_anthropic_key else "•")
        self._anthropic_toggle_btn.config(text="Hide" if self._show_anthropic_key else "Show")

    def _load(self):
        # Teacher settings
        teacher = self._settings.get("teacher") or {}
        self._program_type_var.set(teacher.get("program_type", "band"))
        self._school_district_var.set(teacher.get("school_district", ""))
        self._school_name_var.set(teacher.get("school_name", ""))
        ext_path = teacher.get("external_db_path", "")
        self._ext_db_entry.config(state="normal")
        self._ext_db_var.set(ext_path)
        self._ext_db_entry.config(state="readonly")

        # LLM settings
        llm = self._settings.get("llm") or {}
        self._backend_var.set(llm.get("backend", "local"))
        self._key_var.set(llm.get("api_key", ""))
        self._anthropic_key_var.set(llm.get("anthropic_api_key", ""))
        self._proxy_endpoint_var.set(llm.get("proxy_endpoint", ""))
        self._proxy_token_var.set(llm.get("proxy_token", ""))
        all_models = ANTHROPIC_MODELS + GITHUB_MODELS
        model = llm.get("model", all_models[0])
        current_vals = list(self._model_combo["values"])
        if model and model not in current_vals:
            current_vals.insert(0, model)
            self._model_combo["values"] = current_vals
        self._model_var.set(model)
        self._on_backend_change()

        # Display settings
        from ui.theme import DISPLAY_THEMES
        display = self._settings.get("display") or {}
        saved_theme_id = display.get("theme", "litera")
        # Find the display name for the saved theme id
        theme_name = "Classic"
        for disp_name, theme_id in DISPLAY_THEMES.items():
            if theme_id == saved_theme_id:
                theme_name = disp_name
                break
        self._theme_var.set(theme_name)
        self._size_var.set(display.get("font_size", "normal"))

        # Backup settings
        backup = self._settings.get("backup") or {}
        self._backup_path_var.set(backup.get("external_path", ""))

    def _save(self):
        from ui.theme import DISPLAY_THEMES, LARGE_FONT_SCALE, set_theme_name

        api_key = self._key_var.get().strip()
        anthropic_key = self._anthropic_key_var.get().strip()
        model = self._model_var.get().strip()
        if not model:
            model = (ANTHROPIC_MODELS + GITHUB_MODELS)[0]

        if "teacher" not in self._settings:
            self._settings["teacher"] = {}
        self._settings["teacher"]["program_type"] = self._program_type_var.get()
        self._settings["teacher"]["school_district"] = self._school_district_var.get().strip()
        self._settings["teacher"]["school_name"] = self._school_name_var.get().strip()
        self._settings["teacher"]["external_db_path"] = self._ext_db_var.get().strip()

        if "llm" not in self._settings:
            self._settings["llm"] = {}
        self._settings["llm"]["backend"] = self._backend_var.get()
        self._settings["llm"]["api_key"] = api_key
        self._settings["llm"]["anthropic_api_key"] = anthropic_key
        self._settings["llm"]["model"] = model
        self._settings["llm"]["proxy_endpoint"] = self._proxy_endpoint_var.get().strip().rstrip("/")
        self._settings["llm"]["proxy_token"] = self._proxy_token_var.get().strip()

        # Display settings
        chosen_theme_name = self._theme_var.get()
        chosen_theme_id = DISPLAY_THEMES.get(chosen_theme_name, "litera")
        chosen_size = self._size_var.get()

        if "display" not in self._settings:
            self._settings["display"] = {}
        self._settings["display"]["theme"] = chosen_theme_id
        self._settings["display"]["font_size"] = chosen_size

        # Backup settings
        external_path = self._backup_path_var.get().strip()
        if "backup" not in self._settings:
            self._settings["backup"] = {}
        self._settings["backup"]["external_path"] = external_path

        try:
            save_settings(self.base_dir, self._settings)
        except Exception as e:
            Messagebox.show_error(f"Failed to save settings:\n{e}", title="Error",
                                  parent=self)
            return

        # If Claude-Proxy.txt is present and the user changed any proxy settings,
        # move the file so it no longer overrides settings on next launch.
        self._retire_proxy_file_if_changed()

        # Apply theme change immediately
        try:
            import ttkbootstrap as ttk_mod
            ttk_mod.Style().theme_use(chosen_theme_id)
            set_theme_name(chosen_theme_id)
        except Exception:
            pass

        # Notify about font size restart requirement
        from ui.theme import get_font_scale, LARGE_FONT_SCALE, EXTRA_LARGE_FONT_SCALE
        _scale_map = {"normal": 1.0, "large": LARGE_FONT_SCALE, "extra_large": EXTRA_LARGE_FONT_SCALE}
        current_scale = get_font_scale()
        needs_restart = _scale_map.get(chosen_size, 1.0) != current_scale
        if needs_restart:
            Messagebox.show_info(
                "Display size change will take effect after restarting the app.",
                title="Restart Required",
                parent=self,
            )

        self.destroy()

    def _retire_proxy_file_if_changed(self):
        """Move Claude-Proxy.txt to Claude-Proxy/ subfolder if user edited proxy settings."""
        if not self._app_dir:
            return
        proxy_file = os.path.join(self._app_dir, "Claude-Proxy.txt")
        if not os.path.exists(proxy_file):
            return
        # Parse original values from the file
        orig_endpoint = orig_token = None
        try:
            with open(proxy_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    for sep in (":", "="):
                        if sep in line:
                            key, _, val = line.partition(sep)
                            key = key.strip().lower().replace(" ", "").replace("-", "").replace("_", "")
                            val = val.strip()
                            if key == "proxyendpoint":
                                orig_endpoint = val.rstrip("/")
                            elif key == "token":
                                orig_token = val
                            break
        except Exception:
            return
        # Compare with what was just saved
        new_backend = self._settings.get("llm", {}).get("backend", "local")
        new_endpoint = self._settings.get("llm", {}).get("proxy_endpoint", "")
        new_token = self._settings.get("llm", {}).get("proxy_token", "")
        changed = (
            new_backend != "proxy"
            or new_endpoint != orig_endpoint
            or new_token != orig_token
        )
        if changed:
            import shutil
            archive_dir = os.path.join(self._app_dir, "Claude-Proxy")
            os.makedirs(archive_dir, exist_ok=True)
            dest = os.path.join(archive_dir, "Claude-Proxy.txt")
            try:
                shutil.move(proxy_file, dest)
            except Exception:
                pass

    def _fetch_models(self):
        """Query the endpoint for available models and populate the combobox."""
        api_key = self._key_var.get().strip() or os.environ.get("GITHUB_TOKEN", "")
        if not api_key:
            Messagebox.show_warning(
                "Enter an API key first (or set GITHUB_TOKEN).",
                title="No Key", parent=self
            )
            return

        self._fetch_btn.config(state="disabled", text="Fetching...")
        self._model_hint.config(text="Querying endpoint for available models...",
                                foreground="#555")

        import threading

        def _run():
            try:
                import httpx
                resp = httpx.get(
                    GITHUB_MODELS_CATALOG,
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "X-GitHub-Api-Version": "2022-11-28",
                    },
                    timeout=15,
                )
                resp.raise_for_status()
                data = resp.json()
                models = data if isinstance(data, list) else data.get("data", [])
                ids = sorted(
                    m["id"] for m in models
                    if isinstance(m, dict) and m.get("id")
                    and m.get("supported_input_modalities")  # skip embedding-only
                    and "text" in m.get("supported_input_modalities", [])
                )
                if not ids:
                    self.after(0, self._on_models_fetched, None,
                               f"No models returned. Raw: {str(data)[:200]}")
                else:
                    # Prepend Anthropic models so they stay at top of dropdown
                    full_list = ANTHROPIC_MODELS + ids
                    self.after(0, self._on_models_fetched, full_list, None)
            except Exception as e:
                self.after(0, self._on_models_fetched, None, str(e))

        threading.Thread(target=_run, daemon=True).start()

    def _on_models_fetched(self, model_ids, error):
        self._fetch_btn.config(state="normal", text="Fetch Models")
        if error:
            self._model_hint.config(
                text=f"Fetch failed: {error}", foreground="#CC0000"
            )
            return

        if not model_ids:
            self._model_hint.config(
                text="No models returned from endpoint.", foreground="#888"
            )
            return

        current = self._model_var.get()
        self._model_combo["values"] = model_ids
        if current in model_ids:
            self._model_var.set(current)
        else:
            self._model_var.set(model_ids[0])

        github_count = len(model_ids) - len(ANTHROPIC_MODELS)
        self._model_hint.config(
            text=f"{len(ANTHROPIC_MODELS)} Anthropic + {github_count} GitHub models loaded.",
            foreground="#2a7a2a"
        )

    def _test_connection(self):
        """Attempt a minimal query using the current backend settings."""
        import threading

        if self._backend_var.get() == "proxy":
            endpoint = self._proxy_endpoint_var.get().strip().rstrip("/")
            token = self._proxy_token_var.get().strip()
            if not endpoint or not token:
                Messagebox.show_warning(
                    "Enter both the proxy endpoint and token.",
                    title="Missing Fields", parent=self)
                return

            def _run_proxy():
                try:
                    import httpx
                    resp = httpx.post(
                        f"{endpoint}/api/chat",
                        json={"message": "Reply with just the word OK."},
                        headers={"x-proxy-token": token},
                        timeout=20,
                    )
                    resp.raise_for_status()
                    reply = resp.json().get("reply", "").strip()
                    self.after(0, lambda: Messagebox.show_info(
                        f"Proxy connection successful!\nEndpoint: {endpoint}\nResponse: {reply}",
                        title="Test Passed", parent=self))
                except Exception as e:
                    err = str(e)
                    self.after(0, lambda: Messagebox.show_error(
                        f"Proxy connection failed:\n{err}", title="Test Failed", parent=self))

            threading.Thread(target=_run_proxy, daemon=True).start()
            return

        # Local API key test
        model = self._model_var.get().strip() or (ANTHROPIC_MODELS + GITHUB_MODELS)[0]
        is_claude = model.startswith("claude-")

        if is_claude:
            api_key = self._anthropic_key_var.get().strip()
            if not api_key:
                Messagebox.show_warning(
                    "No Anthropic API key. Enter one in the Anthropic API Key field.",
                    title="No Key", parent=self)
                return
        else:
            api_key = self._key_var.get().strip() or os.environ.get("GITHUB_TOKEN", "")
            if not api_key:
                Messagebox.show_warning(
                    "No GitHub API key available. Enter a key or set the GITHUB_TOKEN "
                    "environment variable.",
                    title="No Key", parent=self)
                return

        def _run():
            try:
                if is_claude:
                    from anthropic import Anthropic
                    client = Anthropic(api_key=api_key)
                    resp = client.messages.create(
                        model=model, max_tokens=10,
                        messages=[{"role": "user", "content": "Reply with just the word OK."}],
                    )
                    reply = resp.content[0].text.strip()
                else:
                    from openai import OpenAI
                    client = OpenAI(base_url=GITHUB_MODELS_ENDPOINT, api_key=api_key)
                    response = client.chat.completions.create(
                        model=model,
                        messages=[{"role": "user", "content": "Reply with just the word OK."}],
                        max_tokens=10,
                    )
                    reply = response.choices[0].message.content.strip()
                self.after(0, lambda: Messagebox.show_info(
                    f"Connection successful!\nModel: {model}\nResponse: {reply}",
                    title="Test Passed", parent=self))
            except Exception as e:
                err = str(e)
                self.after(0, lambda: Messagebox.show_error(
                    f"Connection failed:\n{err}", title="Test Failed", parent=self))

        threading.Thread(target=_run, daemon=True).start()
