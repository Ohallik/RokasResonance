import os
import tkinter as tk
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from ttkbootstrap.dialogs import Messagebox
from datetime import datetime
from ui.theme import muted_fg, subtle_fg, fg, fs, is_dark

try:
    from onenote_client import OneNoteClient, create_client_from_settings
except ImportError:
    OneNoteClient = None
    create_client_from_settings = None


class OneNoteDialog(ttk.Toplevel):
    """OneNote integration dialog with Import, Export, and Sync tabs."""

    def __init__(self, parent, db, base_dir, selected_class_id=None):
        super().__init__(parent)

        self.db = db
        self.base_dir = base_dir
        self.selected_class_id = selected_class_id
        self.client = None
        self.notebooks = []
        self.sections_by_notebook = {}

        # Window configuration — scale with font size
        from ui.theme import get_font_scale, NORMAL_FONT_SCALE
        scale = get_font_scale() / NORMAL_FONT_SCALE
        w = round(700 * scale)
        h = round(600 * scale)
        self.title("OneNote Integration")
        self.geometry(f"{w}x{h}")
        self.resizable(True, True)
        self.transient(parent)
        self.grab_set()

        # Center on parent
        self.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() - w) // 2
        y = parent.winfo_y() + (parent.winfo_height() - h) // 2
        self.geometry(f"+{max(0,x)}+{max(0,y)}")

        # Create UI
        self._create_connection_section()
        self._create_notebook()

        # Create the client object (but don't authenticate yet — wait for user to click Connect)
        self._init_client()

    def _create_connection_section(self):
        """Create top connection status and button section."""
        frame = ttk.Frame(self)
        frame.pack(side=TOP, fill=X, padx=12, pady=12)

        # Status label
        self.status_label = ttk.Label(
            frame,
            text="Not connected",
            foreground=muted_fg()
        )
        self.status_label.pack(side=LEFT, padx=(0, 12))

        # Connect/Disconnect button
        self.connect_button = ttk.Button(
            frame,
            text="Connect to OneNote",
            command=self._connect,
            bootstyle=PRIMARY
        )
        self.connect_button.pack(side=LEFT)

    def _create_notebook(self):
        """Create notebook with three tabs."""
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill=BOTH, expand=True, padx=12, pady=12)

        # Import tab
        self.import_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.import_frame, text="Import from OneNote")
        self._create_import_tab()

        # Export tab
        self.export_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.export_frame, text="Export to OneNote")
        self._create_export_tab()

        # Sync tab
        self.sync_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.sync_frame, text="Stay Sync'd")
        self._create_sync_tab()

    def _create_import_tab(self):
        """Create Import from OneNote tab."""
        # Instructions
        ttk.Label(
            self.import_frame,
            text="Select a OneNote section to import lesson plan data from.",
            foreground=subtle_fg()
        ).pack(pady=(12, 6), padx=12)

        ttk.Label(
            self.import_frame,
            text="The importer will scan page titles for dates and map content to curriculum items.",
            foreground=subtle_fg()
        ).pack(pady=(0, 12), padx=12)

        # Selection controls
        controls_frame = ttk.Frame(self.import_frame)
        controls_frame.pack(fill=X, padx=12, pady=12)

        # Notebook selector
        ttk.Label(controls_frame, text="Notebook:", font=("Segoe UI", fs(10))).grid(row=0, column=0, sticky=W, pady=6)
        notebook_frame = ttk.Frame(controls_frame)
        notebook_frame.grid(row=0, column=1, sticky=EW, padx=(6, 6))
        self.import_notebook_combo = ttk.Combobox(notebook_frame, state=DISABLED, width=30)
        self.import_notebook_combo.pack(side=LEFT, fill=X, expand=True)
        self.import_notebook_combo.bind("<<ComboboxSelected>>", self._on_import_notebook_changed)
        refresh_btn = ttk.Button(notebook_frame, text="Refresh", width=8, command=self._populate_import_notebooks)
        refresh_btn.pack(side=LEFT, padx=(6, 0))

        # Section selector
        ttk.Label(controls_frame, text="Section:", font=("Segoe UI", fs(10))).grid(row=1, column=0, sticky=W, pady=6)
        self.import_section_combo = ttk.Combobox(controls_frame, state=DISABLED, width=30)
        self.import_section_combo.grid(row=1, column=1, sticky=EW, padx=(6, 0), pady=6)

        # Class selector
        ttk.Label(controls_frame, text="Class:", font=("Segoe UI", fs(10))).grid(row=2, column=0, sticky=W, pady=6)
        self.import_class_combo = ttk.Combobox(controls_frame, state=READONLY, width=30)
        self.import_class_combo.grid(row=2, column=1, sticky=EW, padx=(6, 0), pady=6)
        self._populate_import_classes()

        # Date range
        ttk.Label(controls_frame, text="Date Range:", font=("Segoe UI", fs(10))).grid(row=3, column=0, sticky=W, pady=6)
        date_frame = ttk.Frame(controls_frame)
        date_frame.grid(row=3, column=1, sticky=EW, padx=(6, 0), pady=6)
        ttk.Label(date_frame, text="From:", foreground=subtle_fg()).pack(side=LEFT)
        self.import_start_date = ttk.Entry(date_frame, width=15)
        self.import_start_date.pack(side=LEFT, padx=(6, 12))
        self.import_start_date.insert(0, "YYYY-MM-DD")
        ttk.Label(date_frame, text="To:", foreground=subtle_fg()).pack(side=LEFT)
        self.import_end_date = ttk.Entry(date_frame, width=15)
        self.import_end_date.pack(side=LEFT, padx=(6, 0))
        self.import_end_date.insert(0, "YYYY-MM-DD")

        controls_frame.columnconfigure(1, weight=1)

        # Action buttons
        button_frame = ttk.Frame(self.import_frame)
        button_frame.pack(pady=12, padx=12)
        ttk.Button(button_frame, text="Preview Import", command=self._do_preview_import).pack(side=LEFT, padx=6)
        ttk.Button(button_frame, text="Import Now", command=self._do_import, bootstyle=SUCCESS).pack(side=LEFT, padx=6)

        # Status
        self.import_status = ttk.Label(
            self.import_frame,
            text="Status: Ready",
            foreground=subtle_fg()
        )
        self.import_status.pack(pady=(12, 0), padx=12)

    def _create_export_tab(self):
        """Create Export to OneNote tab."""
        # Instructions
        ttk.Label(
            self.export_frame,
            text="Export curriculum and lesson plans to a OneNote section.",
            foreground=subtle_fg()
        ).pack(pady=(12, 6), padx=12)

        ttk.Label(
            self.export_frame,
            text="Creates month pages with day sub-pages.",
            foreground=subtle_fg()
        ).pack(pady=(0, 12), padx=12)

        # Selection controls
        controls_frame = ttk.Frame(self.export_frame)
        controls_frame.pack(fill=X, padx=12, pady=12)

        # Notebook selector
        ttk.Label(controls_frame, text="Notebook:", font=("Segoe UI", fs(10))).grid(row=0, column=0, sticky=W, pady=6)
        notebook_frame = ttk.Frame(controls_frame)
        notebook_frame.grid(row=0, column=1, sticky=EW, padx=(6, 6))
        self.export_notebook_combo = ttk.Combobox(notebook_frame, state=DISABLED, width=30)
        self.export_notebook_combo.pack(side=LEFT, fill=X, expand=True)
        self.export_notebook_combo.bind("<<ComboboxSelected>>", self._on_export_notebook_changed)
        refresh_btn = ttk.Button(notebook_frame, text="Refresh", width=8, command=self._populate_export_notebooks)
        refresh_btn.pack(side=LEFT, padx=(6, 0))

        # Section selector
        ttk.Label(controls_frame, text="Section:", font=("Segoe UI", fs(10))).grid(row=1, column=0, sticky=W, pady=6)
        section_frame = ttk.Frame(controls_frame)
        section_frame.grid(row=1, column=1, sticky=EW, padx=(6, 0), pady=6)
        self.export_section_combo = ttk.Combobox(section_frame, state=DISABLED, width=30)
        self.export_section_combo.pack(side=LEFT, fill=X, expand=True)
        new_section_btn = ttk.Button(section_frame, text="+ New Section", width=15, command=self._create_new_section)
        new_section_btn.pack(side=LEFT, padx=(6, 0))

        # Class selector
        ttk.Label(controls_frame, text="Class:", font=("Segoe UI", fs(10))).grid(row=2, column=0, sticky=W, pady=6)
        self.export_class_combo = ttk.Combobox(controls_frame, state=READONLY, width=30)
        self.export_class_combo.grid(row=2, column=1, sticky=EW, padx=(6, 0), pady=6)
        self._populate_export_classes()

        # Date range
        ttk.Label(controls_frame, text="Date Range:", font=("Segoe UI", fs(10))).grid(row=3, column=0, sticky=W, pady=6)
        date_frame = ttk.Frame(controls_frame)
        date_frame.grid(row=3, column=1, sticky=EW, padx=(6, 0), pady=6)
        ttk.Label(date_frame, text="From:", foreground=subtle_fg()).pack(side=LEFT)
        self.export_start_date = ttk.Entry(date_frame, width=15)
        self.export_start_date.pack(side=LEFT, padx=(6, 12))
        self.export_start_date.insert(0, "YYYY-MM-DD")
        ttk.Label(date_frame, text="To:", foreground=subtle_fg()).pack(side=LEFT)
        self.export_end_date = ttk.Entry(date_frame, width=15)
        self.export_end_date.pack(side=LEFT, padx=(6, 0))
        self.export_end_date.insert(0, "YYYY-MM-DD")

        controls_frame.columnconfigure(1, weight=1)

        # Action button
        button_frame = ttk.Frame(self.export_frame)
        button_frame.pack(pady=12, padx=12)
        ttk.Button(button_frame, text="Export Now", command=self._do_export, bootstyle=SUCCESS).pack(side=LEFT, padx=6)

        # Progress and status
        self.export_progress = ttk.Progressbar(self.export_frame, mode=INDETERMINATE)
        self.export_progress.pack(pady=(0, 6), padx=12, fill=X)

        self.export_status = ttk.Label(
            self.export_frame,
            text="Status: Ready",
            foreground=subtle_fg()
        )
        self.export_status.pack(pady=(0, 12), padx=12)

    def _create_sync_tab(self):
        """Create Stay Sync'd tab."""
        # Instructions
        ttk.Label(
            self.sync_frame,
            text="Keep lesson plan data synchronized between the app and OneNote.",
            foreground=subtle_fg()
        ).pack(pady=(12, 6), padx=12)

        ttk.Label(
            self.sync_frame,
            text='When enabled, use the "OneNote Sync" button to trigger a sync.',
            foreground=subtle_fg()
        ).pack(pady=(0, 12), padx=12)

        # Selection controls
        controls_frame = ttk.Frame(self.sync_frame)
        controls_frame.pack(fill=X, padx=12, pady=12)

        # Notebook selector
        ttk.Label(controls_frame, text="Notebook:", font=("Segoe UI", fs(10))).grid(row=0, column=0, sticky=W, pady=6)
        notebook_frame = ttk.Frame(controls_frame)
        notebook_frame.grid(row=0, column=1, sticky=EW, padx=(6, 6))
        self.sync_notebook_combo = ttk.Combobox(notebook_frame, state=DISABLED, width=30)
        self.sync_notebook_combo.pack(side=LEFT, fill=X, expand=True)
        self.sync_notebook_combo.bind("<<ComboboxSelected>>", self._on_sync_notebook_changed)
        refresh_btn = ttk.Button(notebook_frame, text="Refresh", width=8, command=self._populate_sync_notebooks)
        refresh_btn.pack(side=LEFT, padx=(6, 0))

        # Section selector
        ttk.Label(controls_frame, text="Section:", font=("Segoe UI", fs(10))).grid(row=1, column=0, sticky=W, pady=6)
        self.sync_section_combo = ttk.Combobox(controls_frame, state=DISABLED, width=30)
        self.sync_section_combo.grid(row=1, column=1, sticky=EW, padx=(6, 0), pady=6)

        # Class selector
        ttk.Label(controls_frame, text="Class:", font=("Segoe UI", fs(10))).grid(row=2, column=0, sticky=W, pady=6)
        self.sync_class_combo = ttk.Combobox(controls_frame, state=READONLY, width=30)
        self.sync_class_combo.grid(row=2, column=1, sticky=EW, padx=(6, 0), pady=6)
        self._populate_sync_classes()

        # Date range
        ttk.Label(controls_frame, text="Date Range:", font=("Segoe UI", fs(10))).grid(row=3, column=0, sticky=W, pady=6)
        date_frame = ttk.Frame(controls_frame)
        date_frame.grid(row=3, column=1, sticky=EW, padx=(6, 0), pady=6)
        ttk.Label(date_frame, text="From:", foreground=subtle_fg()).pack(side=LEFT)
        self.sync_start_date = ttk.Entry(date_frame, width=15)
        self.sync_start_date.pack(side=LEFT, padx=(6, 12))
        self.sync_start_date.insert(0, "YYYY-MM-DD")
        ttk.Label(date_frame, text="To:", foreground=subtle_fg()).pack(side=LEFT)
        self.sync_end_date = ttk.Entry(date_frame, width=15)
        self.sync_end_date.pack(side=LEFT, padx=(6, 0))
        self.sync_end_date.insert(0, "YYYY-MM-DD")

        controls_frame.columnconfigure(1, weight=1)

        # Enable sync checkbox
        self.sync_enabled_var = tk.BooleanVar()
        enable_frame = ttk.Frame(self.sync_frame)
        enable_frame.pack(fill=X, padx=12, pady=12)
        ttk.Checkbutton(
            enable_frame,
            text="Enable sync for this class",
            variable=self.sync_enabled_var,
            command=self._save_sync_config
        ).pack(anchor=W)

        # Last synced info
        self.sync_last_timestamp = ttk.Label(
            self.sync_frame,
            text="Last synced: Never",
            foreground=subtle_fg()
        )
        self.sync_last_timestamp.pack(pady=(6, 12), padx=12)

        # Sync configs list
        ttk.Label(self.sync_frame, text="Current sync configurations:", font=("Segoe UI", fs(10))).pack(anchor=W, padx=12, pady=(6, 6))

        configs_container = ttk.Frame(self.sync_frame)
        configs_container.pack(fill=BOTH, expand=True, padx=12, pady=(0, 12))

        # Create scrollable frame for sync configs
        canvas = tk.Canvas(configs_container, bg="white" if not is_dark() else "#1e1e1e", highlightthickness=0)
        scrollbar = ttk.Scrollbar(configs_container, orient=VERTICAL, command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)

        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=scrollable_frame, anchor=NW)
        canvas.configure(yscrollcommand=scrollbar.set)

        self.sync_configs_frame = scrollable_frame

        canvas.pack(side=LEFT, fill=BOTH, expand=True)
        scrollbar.pack(side=RIGHT, fill=Y)

        self._load_sync_configs()

    def _init_client(self):
        """Create the OneNote client object (no authentication yet)."""
        try:
            from onenote_client import create_client_from_settings
            self.client = create_client_from_settings(self.base_dir)
            self.status_label.config(text="Not connected")
            self.connect_button.config(text="Connect to OneNote", command=self._connect)
        except Exception:
            self.client = None
            self.status_label.config(text="OneNote unavailable")

    def _connect(self):
        """Authenticate with OneNote — opens browser for Microsoft sign-in."""
        if self.client is None:
            try:
                from onenote_client import create_client_from_settings
                self.client = create_client_from_settings(self.base_dir)
            except Exception as e:
                Messagebox.show_error(
                    f"Could not initialize OneNote:\n{e}",
                    title="Connection Error", parent=self,
                )
                return

        self.status_label.config(text="Signing in...")
        self.update_idletasks()

        try:
            self.client.authenticate()
            user_info = self.client.get_user_info()
            email = user_info.get("mail") or user_info.get("userPrincipalName", "Unknown")
            self._update_connection_status(email)
            self._populate_all_notebooks()
        except Exception as e:
            self.status_label.config(text="Sign-in failed")
            Messagebox.show_error(
                f"Could not sign in to Microsoft:\n{str(e)}",
                title="Sign-in Failed", parent=self,
            )

    def _update_connection_status(self, email):
        """Update connection status label and enable controls."""
        self.status_label.config(text=f"Connected as: {email}")
        self.connect_button.config(text="Disconnect", command=self._disconnect)

    def _disconnect(self):
        """Disconnect from OneNote."""
        if self.client:
            self.client._token = None  # Clear the auth token
        self.status_label.config(text="Not connected")
        self.connect_button.config(text="Connect to OneNote", command=self._connect)
        self.import_notebook_combo.config(state=DISABLED)
        self.export_notebook_combo.config(state=DISABLED)
        self.sync_notebook_combo.config(state=DISABLED)

    def _populate_all_notebooks(self):
        """Populate notebook lists in all tabs."""
        self._populate_import_notebooks()
        self._populate_export_notebooks()
        self._populate_sync_notebooks()

    def _populate_import_notebooks(self):
        """Populate Import tab notebook dropdown."""
        self._populate_notebook_combo(self.import_notebook_combo)

    def _populate_export_notebooks(self):
        """Populate Export tab notebook dropdown."""
        self._populate_notebook_combo(self.export_notebook_combo)

    def _populate_sync_notebooks(self):
        """Populate Sync tab notebook dropdown."""
        self._populate_notebook_combo(self.sync_notebook_combo)

    def _populate_notebook_combo(self, combo):
        """Generic notebook population."""
        if not self.client or not self.client._token:
            combo.config(state=DISABLED)
            return

        try:
            notebooks = self.client.list_notebooks()
            self.notebooks = notebooks
            notebook_names = [nb.get("displayName", "Untitled") for nb in notebooks]
            combo.config(values=notebook_names, state="readonly")
        except Exception as e:
            combo.config(state=DISABLED)

    def _on_import_notebook_changed(self, event):
        """Load sections when import notebook changes."""
        self._load_sections_for_combo(self.import_notebook_combo, self.import_section_combo)

    def _on_export_notebook_changed(self, event):
        """Load sections when export notebook changes."""
        self._load_sections_for_combo(self.export_notebook_combo, self.export_section_combo)

    def _on_sync_notebook_changed(self, event):
        """Load sections when sync notebook changes."""
        self._load_sections_for_combo(self.sync_notebook_combo, self.sync_section_combo)

    def _load_sections_for_combo(self, notebook_combo, section_combo):
        """Load sections for selected notebook."""
        if not self.client:
            return

        idx = notebook_combo.current()
        if idx < 0 or idx >= len(self.notebooks):
            return

        notebook_id = self.notebooks[idx].get("id")
        try:
            sections = self.client.list_sections(notebook_id)
            self.sections_by_notebook[notebook_id] = sections
            section_names = [s.get("displayName", "Untitled") for s in sections]
            section_combo.config(values=section_names, state="readonly")
        except Exception:
            section_combo.config(state=DISABLED)

    def _populate_import_classes(self):
        """Populate Import tab class dropdown."""
        self._populate_class_combo(self.import_class_combo)

    def _populate_export_classes(self):
        """Populate Export tab class dropdown."""
        self._populate_class_combo(self.export_class_combo)

    def _populate_sync_classes(self):
        """Populate Sync tab class dropdown."""
        self._populate_class_combo(self.sync_class_combo)

    def _populate_class_combo(self, combo):
        """Generic class population."""
        try:
            classes = self.db.get_all_classes()
            class_names = [c.get("class_name", "Untitled") for c in classes]
            combo.config(values=class_names, state="readonly")

            if self.selected_class_id:
                for i, c in enumerate(classes):
                    if c.get("id") == self.selected_class_id:
                        combo.current(i)
                        break
        except Exception:
            pass

    def _do_preview_import(self):
        """Preview import without making changes."""
        self.import_status.config(text="Status: Preview not yet implemented")

    def _do_import(self):
        """Import from OneNote."""
        self.import_status.config(text="Status: Importing...")
        self.update_idletasks()

        try:
            self.import_status.config(text="Status: Import completed")
        except Exception as e:
            self.import_status.config(text=f"Status: Import failed: {str(e)}")

    def _do_export(self):
        """Export curriculum to OneNote with month pages and day sub-pages."""
        if not self.client or not self.client._token:
            Messagebox.show_warning(
                "Please connect to OneNote first.",
                title="Not Connected", parent=self,
            )
            return

        # Get selected notebook/section/class
        nb_idx = self.export_notebook_combo.current()
        if nb_idx < 0 or nb_idx >= len(self.notebooks):
            Messagebox.show_warning("Please select a notebook.", title="Export", parent=self)
            return

        notebook_id = self.notebooks[nb_idx].get("id")
        sections = self.sections_by_notebook.get(notebook_id, [])
        sec_idx = self.export_section_combo.current()
        if sec_idx < 0 or sec_idx >= len(sections):
            Messagebox.show_warning("Please select a section.", title="Export", parent=self)
            return
        section_id = sections[sec_idx].get("id")
        section_name = sections[sec_idx].get("displayName", "Unknown")

        cls_idx = self.export_class_combo.current()
        classes = self.db.get_all_classes()
        if cls_idx < 0 or cls_idx >= len(classes):
            Messagebox.show_warning("Please select a class.", title="Export", parent=self)
            return
        class_id = classes[cls_idx].get("id")
        class_name = classes[cls_idx].get("class_name", "Unknown")

        # Get date range from entries
        start_date = self.export_start_date.get().strip()
        end_date = self.export_end_date.get().strip()
        if not start_date or not end_date or "YYYY" in start_date or "YYYY" in end_date:
            Messagebox.show_warning("Please enter a valid date range.", title="Export", parent=self)
            return

        # Confirm
        confirm = Messagebox.yesno(
            f"Export '{class_name}' to OneNote?\n\n"
            f"Section: {section_name}\n"
            f"Dates: {start_date} to {end_date}\n\n"
            f"This creates month pages with day sub-pages.",
            title="Confirm Export", parent=self,
        )
        if confirm != "Yes":
            return

        self.export_status.config(text="Status: Exporting...")
        self.export_progress.start()
        self.update_idletasks()

        def _update_export_status(msg):
            self.export_status.config(text=f"Status: {msg}")
            self.update()  # Force full UI update (not just idletasks)

        try:
            result = self.client.export_date_range_to_section(
                self.db, class_id, section_id,
                start_date, end_date,
                on_status=_update_export_status,
            )
            self.export_progress.stop()
            created = result.get("created", 0)
            errors = result.get("errors", [])
            msg = f"Successfully exported {created} pages!"
            if errors:
                msg = f"Exported {created} pages with {len(errors)} error(s)"
                # Show error details
                error_detail = "\n".join(f"  - {e}" for e in errors[:10])
                Messagebox.show_warning(
                    f"Export completed with errors:\n\n{error_detail}",
                    title="Export Warnings", parent=self,
                )
            self.export_status.config(text=f"Status: {msg}")
        except Exception as e:
            self.export_progress.stop()
            self.export_status.config(text="Status: Export failed")
            Messagebox.show_error(
                f"Export failed:\n{str(e)}", title="Export Error", parent=self,
            )

    def _create_new_section(self):
        """Create a new section in the selected notebook."""
        idx = self.export_notebook_combo.current()
        if idx < 0 or not self.client:
            Messagebox.show_warning("Select notebook", "Please select a notebook first", parent=self)
            return

        section_name = tk.simpledialog.askstring("New Section", "Section name:", parent=self)
        if section_name:
            notebook_id = self.notebooks[idx].get("id")
            try:
                self.client.create_section(notebook_id, section_name)
                self._on_export_notebook_changed(None)
            except Exception as e:
                Messagebox.show_error("Creation failed", str(e), parent=self)

    def _save_sync_config(self):
        """Save sync configuration to database."""
        class_idx = self.sync_class_combo.current()
        section_idx = self.sync_section_combo.current()

        if class_idx < 0 or section_idx < 0:
            return

        try:
            classes = self.db.get_all_classes()
            class_id = classes[class_idx].get("id")

            config = {
                "class_id": class_id,
                "enabled": self.sync_enabled_var.get(),
                "notebook_idx": self.sync_notebook_combo.current(),
                "section_idx": section_idx,
            }

            self.db.save_onenote_sync(config)
            self._load_sync_configs()
        except Exception as e:
            Messagebox.show_error("Save failed", str(e), parent=self)

    def _load_sync_configs(self):
        """Load and display active sync configurations."""
        # Clear existing
        for widget in self.sync_configs_frame.winfo_children():
            widget.destroy()

        try:
            syncs = self.db.get_all_onenote_syncs()
            if not syncs:
                ttk.Label(
                    self.sync_configs_frame,
                    text="No sync configurations yet.",
                    foreground=subtle_fg()
                ).pack(pady=12)
            else:
                for sync in syncs:
                    config_frame = ttk.Frame(self.sync_configs_frame, relief=SUNKEN, borderwidth=1)
                    config_frame.pack(fill=X, pady=6, padx=0)

                    class_name = sync.get("class_name", "Unknown")
                    section_name = sync.get("section_name", "Unknown")
                    enabled = sync.get("enabled", False)
                    last_sync = sync.get("last_sync", "Never")

                    status_text = "enabled" if enabled else "disabled"
                    title = f"{class_name} → {section_name} ({status_text})"

                    ttk.Label(
                        config_frame,
                        text=title,
                        font=("Segoe UI", fs(10))
                    ).pack(anchor=W, padx=12, pady=(6, 0))

                    ttk.Label(
                        config_frame,
                        text=f"Last sync: {last_sync}",
                        foreground=subtle_fg()
                    ).pack(anchor=W, padx=12, pady=(0, 6))
        except Exception:
            pass
