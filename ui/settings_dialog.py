"""
ui/settings_dialog.py - Application settings dialog
"""

import json
import os
import tkinter as tk
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from ttkbootstrap.dialogs import Messagebox

SETTINGS_FILE = "settings.json"
GITHUB_MODELS_ENDPOINT = "https://models.inference.ai.azure.com"

# Models available on GitHub Models (OpenAI-compatible endpoint)
# https://github.com/marketplace/models
GITHUB_MODELS = [
    "claude-opus-4-5",
    "claude-sonnet-4-5",
    "claude-3-7-sonnet",
    "claude-3-5-haiku",
    "gpt-4o",
    "gpt-4o-mini",
    "o1",
    "o3-mini",
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
    def __init__(self, parent, base_dir: str):
        super().__init__(parent)
        self.base_dir = base_dir
        self._settings = load_settings(base_dir)
        self._show_key = False

        self.title("Settings — Roka's Resonance")
        self.geometry("560x540")
        self.resizable(False, True)
        self.grab_set()

        self.update_idletasks()
        x = (self.winfo_screenwidth() - 560) // 2
        y = (self.winfo_screenheight() - 540) // 2
        self.geometry(f"+{x}+{y}")

        self._build()
        self._load()

    # ───────────────────────────────────────────────────── Build UI ────────

    def _build(self):
        # Header
        hdr = ttk.Frame(self, bootstyle=SECONDARY)
        hdr.pack(fill=X)
        ttk.Label(hdr, text="  Settings", font=("Segoe UI", 13, "bold"),
                  bootstyle=(INVERSE, SECONDARY)).pack(pady=12, padx=16, anchor=W)

        # Notebook — Display tab first
        nb = ttk.Notebook(self, bootstyle=SECONDARY)
        nb.pack(fill=BOTH, expand=True, padx=12, pady=(10, 0))

        display_tab = ttk.Frame(nb)
        nb.add(display_tab, text="  Display  ")

        llm_tab = ttk.Frame(nb)
        nb.add(llm_tab, text="  LLM Configuration  ")

        self._build_display_tab(display_tab)
        self._build_llm_tab(llm_tab)

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
        # Show/hide Test Connection based on active tab
        def _on_tab_change(event):
            idx = nb.index(nb.select())
            if idx == 1:  # LLM Configuration tab
                self._test_btn.pack(side=LEFT, padx=4)
            else:
                self._test_btn.pack_forget()
        nb.bind("<<NotebookTabChanged>>", _on_tab_change)
        # Display tab is first — button starts hidden

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

            # Color swatch
            swatch_colors = {
                "Classic":    ("#ffffff", "#0d6efd"),   # white bg, blue accent
                "Warm Earth": ("#f5f0e8", "#c47a1e"),   # tan bg, brown accent
                "Dark Mode":  ("#2b2b2b", "#4dabf7"),   # dark bg, blue accent
            }
            bg, accent = swatch_colors.get(name, ("#fff", "#333"))
            swatch = tk.Frame(row, width=28, height=16, bg=bg,
                              relief="solid", bd=1)
            swatch.pack(side=LEFT, padx=(0, 6))
            tk.Frame(swatch, width=8, height=16, bg=accent).pack(
                side=RIGHT)

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
            ("normal", "Normal",
             "Default text sizes (recommended for most displays)."),
            ("large",  "Large",
             "25% larger text — easier to read for accessibility."),
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

        # Description
        ttk.Label(
            outer,
            text="Uses GitHub Models — an OpenAI-compatible endpoint with access to "
                 "Claude, GPT, and other models.",
            font=("Segoe UI", 9),
            foreground="#555",
            wraplength=460,
            justify=LEFT,
        ).pack(anchor=W, pady=(0, 2))

        # Endpoint (read-only info)
        endpoint_row = ttk.Frame(outer)
        endpoint_row.pack(fill=X, pady=(0, 12))
        ttk.Label(endpoint_row, text="Endpoint: ", font=("Segoe UI", 8),
                  foreground="#888").pack(side=LEFT)
        ttk.Label(endpoint_row, text=GITHUB_MODELS_ENDPOINT,
                  font=("Segoe UI", 8, "italic"), foreground="#555").pack(side=LEFT)

        ttk.Separator(outer, orient=HORIZONTAL).pack(fill=X, pady=(0, 12))

        # API Key section
        ttk.Label(outer, text="API Key",
                  font=("Segoe UI", 9, "bold")).pack(anchor=W)

        # Check if GITHUB_TOKEN env var is set
        saved_key = (self._settings.get("llm") or {}).get("api_key", "").strip()
        env_key = os.environ.get("GITHUB_TOKEN", "")
        if saved_key:
            env_note = "Key saved in settings below."
            env_color = "#2a7a2a"
        elif env_key:
            env_note = f"GITHUB_TOKEN env var is set ({len(env_key)} chars) — used as fallback if field is empty."
            env_color = "#2a7a2a"
        else:
            env_note = "No key saved. Enter your GitHub token below."
            env_color = "#888"

        ttk.Label(outer, text=env_note, font=("Segoe UI", 8),
                  foreground=env_color, wraplength=460).pack(anchor=W, pady=(0, 4))

        key_row = ttk.Frame(outer)
        key_row.pack(fill=X, pady=(0, 14))

        self._key_var = tk.StringVar()
        self._key_entry = ttk.Entry(key_row, textvariable=self._key_var,
                                    show="•", width=44)
        self._key_entry.pack(side=LEFT, fill=X, expand=True)

        self._toggle_btn = ttk.Button(
            key_row, text="Show", bootstyle=(SECONDARY, OUTLINE), width=6,
            command=self._toggle_key_visibility
        )
        self._toggle_btn.pack(side=LEFT, padx=(6, 0))

        # Model section
        ttk.Label(outer, text="Model",
                  font=("Segoe UI", 9, "bold")).pack(anchor=W)

        self._model_hint = ttk.Label(
            outer,
            text="Click 'Fetch Models' to load available models using your API key.",
            font=("Segoe UI", 8), foreground="#888"
        )
        self._model_hint.pack(anchor=W, pady=(0, 4))

        model_row = ttk.Frame(outer)
        model_row.pack(fill=X, pady=(0, 14))

        self._model_var = tk.StringVar(value=GITHUB_MODELS[0])
        self._model_combo = ttk.Combobox(model_row, textvariable=self._model_var,
                                         values=GITHUB_MODELS, width=34)
        self._model_combo.pack(side=LEFT)

        self._fetch_btn = ttk.Button(
            model_row, text="Fetch Models", bootstyle=(SECONDARY, OUTLINE),
            command=self._fetch_models
        )
        self._fetch_btn.pack(side=LEFT, padx=(6, 0))

        # Status area
        self._status_frame = ttk.Frame(outer)
        self._status_frame.pack(fill=X)
        self._refresh_status()

    # ───────────────────────────────────────────────────── Logic ───────────

    def _refresh_status(self):
        for w in self._status_frame.winfo_children():
            w.destroy()
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

    def _toggle_key_visibility(self):
        self._show_key = not self._show_key
        self._key_entry.config(show="" if self._show_key else "•")
        self._toggle_btn.config(text="Hide" if self._show_key else "Show")

    def _load(self):
        # LLM settings
        llm = self._settings.get("llm") or {}
        self._key_var.set(llm.get("api_key", ""))
        model = llm.get("model", GITHUB_MODELS[0])
        current_vals = list(self._model_combo["values"])
        if model and model not in current_vals:
            current_vals.insert(0, model)
            self._model_combo["values"] = current_vals
        self._model_var.set(model)

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

    def _save(self):
        from ui.theme import DISPLAY_THEMES, LARGE_FONT_SCALE, set_theme_name

        api_key = self._key_var.get().strip()
        model = self._model_var.get().strip()
        if not model:
            model = GITHUB_MODELS[0]

        if "llm" not in self._settings:
            self._settings["llm"] = {}
        self._settings["llm"]["api_key"] = api_key
        self._settings["llm"]["model"] = model

        # Display settings
        chosen_theme_name = self._theme_var.get()
        chosen_theme_id = DISPLAY_THEMES.get(chosen_theme_name, "litera")
        chosen_size = self._size_var.get()

        if "display" not in self._settings:
            self._settings["display"] = {}
        self._settings["display"]["theme"] = chosen_theme_id
        self._settings["display"]["font_size"] = chosen_size

        try:
            save_settings(self.base_dir, self._settings)
        except Exception as e:
            Messagebox.show_error(f"Failed to save settings:\n{e}", title="Error",
                                  parent=self)
            return

        # Apply theme change immediately
        try:
            import ttkbootstrap as ttk_mod
            ttk_mod.Style().theme_use(chosen_theme_id)
            set_theme_name(chosen_theme_id)
        except Exception:
            pass

        # Notify about font size restart requirement
        from ui.theme import get_font_scale
        current_scale = get_font_scale()
        needs_restart = (chosen_size == "large") != (current_scale > 1.0)
        if needs_restart:
            Messagebox.show_info(
                "Display size change will take effect after restarting the app.",
                title="Restart Required",
                parent=self,
            )

        self.destroy()

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
                    f"{GITHUB_MODELS_ENDPOINT}/models",
                    headers={"Authorization": f"Bearer {api_key}"},
                    timeout=15,
                )
                resp.raise_for_status()
                data = resp.json()
                models = data if isinstance(data, list) else data.get("data", [])
                ids = sorted(
                    m["id"] for m in models
                    if m.get("id") and not str(m["id"]).startswith("azureml://")
                )
                self.after(0, self._on_models_fetched, ids, None)
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

        self._model_hint.config(
            text=f"{len(model_ids)} models available. Select one below.",
            foreground="#2a7a2a"
        )

    def _test_connection(self):
        """Save current field values temporarily and attempt a minimal query."""
        api_key = self._key_var.get().strip() or os.environ.get("GITHUB_TOKEN", "")
        model = self._model_var.get().strip() or GITHUB_MODELS[0]

        if not api_key:
            Messagebox.show_warning(
                "No API key available. Enter a key or set the GITHUB_TOKEN "
                "environment variable.",
                title="No Key", parent=self
            )
            return

        import threading

        def _run():
            try:
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
                    title="Test Passed", parent=self
                ))
            except Exception as e:
                err = str(e)
                self.after(0, lambda: Messagebox.show_error(
                    f"Connection failed:\n{err}", title="Test Failed", parent=self
                ))

        threading.Thread(target=_run, daemon=True).start()
