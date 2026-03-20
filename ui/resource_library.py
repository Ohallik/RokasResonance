"""
ui/resource_library.py - Resource Library management for lesson plans

Manages external resources (OneNote links, OneDrive folders, local folders, URLs,
files, method book references, etc.) with tagging and filtering for easy retrieval.
"""

import os
import webbrowser
import tkinter as tk
from tkinter import filedialog
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from ttkbootstrap.dialogs import Messagebox
from ui.theme import muted_fg, subtle_fg, fg, fs


RESOURCE_TYPES = {
    "onenote":         "OneNote Link",
    "onedrive":        "OneDrive Folder",
    "local_folder":    "Local Folder",
    "url":             "Website/URL",
    "file":            "Uploaded File",
    "music_link":      "Music Manager Link",
    "method_book_ref": "Method Book Reference",
    "custom":          "Custom Resource",
}

RESOURCE_TYPE_DISPLAY = list(RESOURCE_TYPES.values())


class ResourceLibrary(ttk.Frame):
    def __init__(self, parent, db):
        super().__init__(parent)
        self.db = db
        self._search_var = tk.StringVar()
        self._type_var = tk.StringVar(value="All Types")
        self._tag_var = tk.StringVar(value="All Tags")
        self._selected_id = None
        self._all_resources = []

        self._build()
        self.refresh()

    def _build(self):
        # ── Toolbar ───────────────────────────────────────────────────────────
        toolbar = ttk.Frame(self, bootstyle=LIGHT)
        toolbar.pack(fill=X)

        ttk.Button(toolbar, text="➕ Add Resource", bootstyle=SUCCESS,
                   command=self._add_resource).pack(side=LEFT, padx=6, pady=6)
        ttk.Button(toolbar, text="✏️ Edit", bootstyle=PRIMARY,
                   command=self._edit_resource).pack(side=LEFT, padx=2, pady=6)
        ttk.Button(toolbar, text="🗑️ Delete", bootstyle=DANGER,
                   command=self._delete_resource).pack(side=LEFT, padx=2, pady=6)
        ttk.Button(toolbar, text="🔄 Refresh", bootstyle=(SECONDARY, OUTLINE),
                   command=self.refresh).pack(side=LEFT, padx=6, pady=6)

        ttk.Separator(toolbar, orient=VERTICAL).pack(side=LEFT, fill=Y, padx=8, pady=4)

        ttk.Button(toolbar, text="📂 Browse Folder", bootstyle=INFO,
                   command=self._quick_add_folder).pack(side=LEFT, padx=6, pady=6)
        ttk.Button(toolbar, text="🔗 Add URL", bootstyle=INFO,
                   command=self._quick_add_url).pack(side=LEFT, padx=6, pady=6)

        # ── Filter bar (below toolbar) ─────────────────────────────────────────
        filter_bar = ttk.Frame(self)
        filter_bar.pack(fill=X, padx=6, pady=(2, 0))

        ttk.Label(filter_bar, text="Search:").pack(side=LEFT, padx=(0, 4))
        ttk.Entry(filter_bar, textvariable=self._search_var, width=26).pack(side=LEFT)
        self._search_var.trace_add("write", lambda *_: self._apply_filter())

        ttk.Label(filter_bar, text="Type:").pack(side=LEFT, padx=(12, 4))
        type_combo = ttk.Combobox(filter_bar, textvariable=self._type_var,
                                   state="readonly", width=18)
        type_combo["values"] = ["All Types"] + RESOURCE_TYPE_DISPLAY
        type_combo.pack(side=LEFT)
        type_combo.bind("<<ComboboxSelected>>", lambda e: self._apply_filter())

        ttk.Label(filter_bar, text="Tags:").pack(side=LEFT, padx=(12, 4))
        self._tag_combo = ttk.Combobox(filter_bar, textvariable=self._tag_var,
                                        state="readonly", width=18)
        self._tag_combo.pack(side=LEFT)
        self._tag_combo.bind("<<ComboboxSelected>>", lambda e: self._apply_filter())

        self._count_lbl = ttk.Label(filter_bar, text="", foreground=muted_fg())
        self._count_lbl.pack(side=RIGHT, padx=6)

        # ── Content: Tree + Detail ─────────────────────────────────────────────
        paned = ttk.Panedwindow(self, orient=HORIZONTAL)
        paned.pack(fill=BOTH, expand=True, padx=6, pady=6)

        # Left: resource list
        list_frame = ttk.Frame(paned)
        paned.add(list_frame, weight=2)

        cols = ("Name", "Type", "Tags", "Description")
        sb = ttk.Scrollbar(list_frame, orient=VERTICAL)
        self.tree = ttk.Treeview(list_frame, columns=cols, show="headings",
                                  yscrollcommand=sb.set, selectmode="browse",
                                  bootstyle=PRIMARY)
        sb.config(command=self.tree.yview)
        sb.pack(side=RIGHT, fill=Y)
        self.tree.pack(fill=BOTH, expand=True)

        widths = [200, 120, 150, 300]
        _stretch = {"Name", "Description"}
        for col, w in zip(cols, widths):
            self.tree.heading(col, text=col, anchor=W)
            self.tree.column(col, width=w, anchor=W, stretch=col in _stretch)

        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.bind("<Double-1>", lambda e: self._edit_resource())

        # Right: detail panel
        detail_frame = ttk.Frame(paned, width=300)
        paned.add(detail_frame, weight=1)
        self._build_detail(detail_frame)

        self._all_resources = []

    def _build_detail(self, parent):
        nb = ttk.Notebook(parent, bootstyle=PRIMARY)
        nb.pack(fill=BOTH, expand=True)

        info_tab = ttk.Frame(nb)
        usage_tab = ttk.Frame(nb)
        nb.add(info_tab, text="Resource Info")
        nb.add(usage_tab, text="Usage")

        # ── Info tab ──────────────────────────────────────────────────────────
        outer = ttk.Frame(info_tab)
        outer.pack(fill=BOTH, expand=True, padx=8, pady=8)

        self._detail_labels = {}
        fields = [
            ("Name", "display_name"),
            ("Type", "resource_type"),
            ("Description", "description"),
            ("URL/Path", "url_or_path"),
            ("Tags", "tags"),
            ("Method Book", "method_book_info"),
            ("Notes", "notes"),
        ]
        for label, key in fields:
            r = ttk.Frame(outer)
            r.pack(fill=X, pady=1)
            ttk.Label(r, text=f"{label}:", font=("Segoe UI", fs(8), "bold"),
                      width=12, anchor=W).pack(side=LEFT)
            lbl = ttk.Label(r, text="", font=("Segoe UI", fs(8)),
                             anchor=W, wraplength=180, justify=LEFT)
            lbl.pack(side=LEFT, fill=X, expand=True)
            self._detail_labels[key] = lbl

        # Buttons
        btn_frame = ttk.Frame(outer)
        btn_frame.pack(fill=X, pady=(8, 0))
        ttk.Button(btn_frame, text="📋 Copy Path", bootstyle=SECONDARY,
                   command=self._copy_path).pack(side=LEFT, padx=2)
        ttk.Button(btn_frame, text="🔗 Open", bootstyle=INFO,
                   command=self._open_resource).pack(side=LEFT, padx=2)

        # ── Usage tab ─────────────────────────────────────────────────────────
        usage_frame = ttk.Frame(usage_tab)
        usage_frame.pack(fill=BOTH, expand=True, padx=8, pady=8)

        cols_u = ("Date", "Class", "Plan Summary")
        sb_u = ttk.Scrollbar(usage_frame, orient=VERTICAL)
        self._usage_tree = ttk.Treeview(usage_frame, columns=cols_u, show="headings",
                                        yscrollcommand=sb_u.set, bootstyle=INFO)
        sb_u.config(command=self._usage_tree.yview)
        sb_u.pack(side=RIGHT, fill=Y)
        self._usage_tree.pack(fill=BOTH, expand=True)

        for col in cols_u:
            self._usage_tree.heading(col, text=col, anchor=W)
            width = 80 if col == "Date" else (100 if col == "Class" else 200)
            self._usage_tree.column(col, width=width, anchor=W,
                                   minwidth=40, stretch=col == "Plan Summary")

    # ─────────────────────────────────────────────────────────── Data Loading ─

    def refresh(self):
        self._all_resources = list(self.db.get_all_resources())
        self._populate_tag_options()
        self._apply_filter()

    def _populate_tag_options(self):
        all_tags = self.db.get_all_tags()
        self._tag_combo["values"] = ["All Tags"] + all_tags
        if self._tag_var.get() not in ["All Tags"] + all_tags:
            self._tag_var.set("All Tags")

    def _apply_filter(self):
        search = self._search_var.get().lower()
        type_display = self._type_var.get()
        tag = self._tag_var.get()

        # Map display name back to resource type key
        resource_type = None
        if type_display != "All Types":
            for key, display in RESOURCE_TYPES.items():
                if display == type_display:
                    resource_type = key
                    break

        tag_filter = None if tag == "All Tags" else tag

        # Use database search
        visible = self.db.search_resources(
            search=search,
            resource_type=resource_type,
            tag=tag_filter
        )

        self._populate_tree(list(visible))
        self._count_lbl.config(text=f"{len(visible)} resource(s)")

    def _populate_tree(self, resources):
        self.tree.delete(*self.tree.get_children())
        for r in resources:
            resource_id = r["id"]
            name = r.get("display_name") or ""
            res_type = r.get("resource_type") or ""
            type_display = RESOURCE_TYPES.get(res_type, res_type)

            # Get tags for this resource
            tags = self.db.get_resource_tags(resource_id)
            tags_str = ", ".join(tags) if tags else ""

            description = r.get("description") or ""

            self.tree.insert("", "end", iid=str(resource_id), values=(
                name,
                type_display,
                tags_str,
                description,
            ))

    def _on_select(self, event=None):
        sel = self.tree.selection()
        if not sel:
            return
        self._selected_id = int(sel[0])
        self._load_detail(self._selected_id)

    def _load_detail(self, resource_id: int):
        resource = self.db.get_resource(resource_id)
        if not resource:
            return

        res_type = resource.get("resource_type") or ""
        type_display = RESOURCE_TYPES.get(res_type, res_type)

        # Get tags
        tags = self.db.get_resource_tags(resource_id)
        tags_str = ", ".join(tags) if tags else ""

        # Build method book info
        method_book_info = ""
        if resource.get("method_book_title"):
            info_parts = [resource["method_book_title"]]
            if resource.get("method_book_pages"):
                info_parts.append(f"Pages {resource['method_book_pages']}")
            method_book_info = " - ".join(info_parts)

        self._detail_labels["display_name"].config(text=resource.get("display_name") or "")
        self._detail_labels["resource_type"].config(text=type_display)
        self._detail_labels["description"].config(text=resource.get("description") or "")
        self._detail_labels["url_or_path"].config(text=resource.get("url_or_path") or "")
        self._detail_labels["tags"].config(text=tags_str)
        self._detail_labels["method_book_info"].config(text=method_book_info)
        self._detail_labels["notes"].config(text=resource.get("notes") or "")

        # Load usage tab
        self._usage_tree.delete(*self._usage_tree.get_children())
        with self.db._connect() as conn:
            plans = conn.execute(
                """SELECT lp.id, lp.date_created, c.class_name, lp.plan_summary
                   FROM lesson_plan_resources lpr
                   JOIN lesson_plans lp ON lp.id = lpr.lesson_plan_id
                   LEFT JOIN classes c ON c.id = lp.class_id
                   WHERE lpr.resource_id = ?
                   ORDER BY lp.date_created DESC""",
                (resource_id,),
            ).fetchall()

        for plan in plans:
            self._usage_tree.insert("", "end", values=(
                plan["date_created"] or "",
                plan["class_name"] or "",
                plan["plan_summary"] or "",
            ))

    # ─────────────────────────────────────────────────────────── Actions ──────

    def _get_selected(self):
        sel = self.tree.selection()
        if not sel:
            Messagebox.show_warning("Please select a resource first.", title="No Selection", parent=self)
            return None
        return int(sel[0])

    def _add_resource(self):
        dlg = ResourceDialog(self.winfo_toplevel(), self.db)
        self.wait_window(dlg)
        self.refresh()

    def _edit_resource(self):
        rid = self._get_selected()
        if rid is None:
            return
        dlg = ResourceDialog(self.winfo_toplevel(), self.db, resource_id=rid)
        self.wait_window(dlg)
        self.refresh()
        self._load_detail(rid)

    def _delete_resource(self):
        rid = self._get_selected()
        if rid is None:
            return
        resource = self.db.get_resource(rid)
        if not resource:
            return
        name = resource.get("display_name", "Unknown")

        answer = Messagebox.yesno(
            f"Are you sure you want to delete '{name}'?\n\n"
            f"This will remove it from the resource library.",
            title="Confirm Delete"
, parent=self)
        if answer != "Yes":
            return

        self.db.delete_resource(rid)
        self._selected_id = None
        self.refresh()

    def _quick_add_folder(self):
        path = filedialog.askdirectory(
            title="Select a Folder to Add",
            parent=self.winfo_toplevel(),
        )
        if not path:
            return
        folder_name = os.path.basename(path) or path
        dlg = ResourceDialog(self.winfo_toplevel(), self.db,
                            default_type="local_folder",
                            default_path=path,
                            default_name=folder_name)
        self.wait_window(dlg)
        self.refresh()

    def _quick_add_url(self):
        dlg = ResourceDialog(self.winfo_toplevel(), self.db,
                            default_type="url")
        self.wait_window(dlg)
        self.refresh()

    def _copy_path(self):
        if self._selected_id is None:
            return
        resource = self.db.get_resource(self._selected_id)
        if resource and resource.get("url_or_path"):
            path = resource["url_or_path"]
            self.clipboard_clear()
            self.clipboard_append(path)
            Messagebox.show_info(f"Copied: {path}", title="Copied", parent=self)

    def _open_resource(self):
        if self._selected_id is None:
            return
        resource = self.db.get_resource(self._selected_id)
        if not resource:
            return

        url_or_path = resource.get("url_or_path")
        if not url_or_path:
            Messagebox.show_warning("No URL or path available.", title="Cannot Open", parent=self)
            return

        res_type = resource.get("resource_type")

        # For web URLs
        if res_type == "url" or url_or_path.startswith("http"):
            webbrowser.open(url_or_path)
        # For local folders
        elif res_type in ("local_folder", "onedrive"):
            try:
                if os.name == "nt":  # Windows
                    os.startfile(url_or_path)
                else:  # Mac/Linux
                    import subprocess
                    subprocess.Popen(["xdg-open", url_or_path])
            except Exception as e:
                Messagebox.show_error(f"Could not open: {e}", title="Error", parent=self)
        else:
            # Try web first, then file
            if url_or_path.startswith("http"):
                webbrowser.open(url_or_path)
            else:
                try:
                    if os.name == "nt":
                        os.startfile(url_or_path)
                    else:
                        import subprocess
                        subprocess.Popen(["xdg-open", url_or_path])
                except Exception as e:
                    Messagebox.show_error(f"Could not open: {e}", title="Error", parent=self)


class ResourceDialog(ttk.Toplevel):
    def __init__(self, parent, db, resource_id=None, default_type=None,
                 default_path=None, default_name=None):
        super().__init__(parent)
        self.db = db
        self.resource_id = resource_id
        self.default_type = default_type
        self.default_path = default_path
        self.default_name = default_name

        self.title("Edit Resource" if resource_id else "Add Resource")
        self.resizable(True, True)
        self.grab_set()
        self.lift()

        self._vars = {}
        self._sheet_music_map = {}
        self._build()
        if resource_id:
            self._load(resource_id)
        elif default_type:
            self._vars["resource_type"].set(RESOURCE_TYPES.get(default_type, default_type))
            if default_name:
                self._vars["display_name"].set(default_name)
            if default_path:
                self._vars["url_or_path"].set(default_path)

        from ui.theme import fit_window
        fit_window(self, 520, 600)

    def _build(self):
        hdr = ttk.Frame(self, bootstyle=PRIMARY)
        hdr.pack(fill=X)
        title = "Edit Resource" if self.resource_id else "Add Resource"
        ttk.Label(hdr, text=title, font=("Segoe UI", 13, "bold"),
                  bootstyle=(INVERSE, PRIMARY)).pack(pady=12, padx=16, anchor=W)

        # Scrollable body
        canvas = tk.Canvas(self, highlightthickness=0)
        sb = ttk.Scrollbar(self, orient=VERTICAL, command=canvas.yview)
        canvas.configure(yscrollcommand=sb.set)
        sb.pack(side=RIGHT, fill=Y)
        canvas.pack(fill=BOTH, expand=True)

        content = ttk.Frame(canvas)
        cw = canvas.create_window((0, 0), window=content, anchor=NW)

        def _resize(event):
            canvas.configure(scrollregion=canvas.bbox("all"))
            canvas.itemconfig(cw, width=canvas.winfo_width())

        content.bind("<Configure>", _resize)
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(cw, width=e.width))

        def _wheel(event):
            try:
                canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
            except tk.TclError:
                canvas.unbind_all("<MouseWheel>")
        canvas.bind_all("<MouseWheel>", _wheel)
        self.bind("<Destroy>", lambda e: canvas.unbind_all("<MouseWheel>"))

        self._build_form(content)

        btn = ttk.Frame(self)
        btn.pack(fill=X, padx=16, pady=10)
        ttk.Button(btn, text="Cancel", bootstyle=(SECONDARY, OUTLINE),
                   command=self.destroy).pack(side=RIGHT, padx=4)
        ttk.Button(btn, text="Save", bootstyle=SUCCESS,
                   command=self._save).pack(side=RIGHT, padx=4)

    def _field(self, parent, label, key, widget="entry", options=None, side=LEFT, width=20):
        f = ttk.Frame(parent)
        f.pack(side=side, padx=6, pady=2)
        ttk.Label(f, text=label, font=("Segoe UI", 8)).pack(anchor=W)
        var = tk.StringVar()
        self._vars[key] = var
        if widget == "combobox":
            cb = ttk.Combobox(f, textvariable=var, values=options or [],
                             width=width, state="readonly" if options else "normal")
            cb.pack(anchor=W)
            if key == "resource_type":
                cb.bind("<<ComboboxSelected>>", lambda e: self._on_type_change())
        else:
            ttk.Entry(f, textvariable=var, width=width).pack(anchor=W)
        return var

    def _build_form(self, parent):
        # Resource Type
        row0 = ttk.Frame(parent)
        row0.pack(fill=X, padx=16, pady=(8, 0))
        self._field(row0, "Resource Type *", "resource_type", widget="combobox",
                   options=RESOURCE_TYPE_DISPLAY, side=LEFT, width=22)

        # Display Name
        row1 = ttk.Frame(parent)
        row1.pack(fill=X, padx=16, pady=(4, 0))
        self._field(row1, "Display Name *", "display_name", side=LEFT, width=28)

        # Description
        desc_label = ttk.Label(parent, text="Description:", font=("Segoe UI", 8, "bold"))
        desc_label.pack(anchor=W, padx=24, pady=(8, 2))
        desc_frame = ttk.Frame(parent)
        desc_frame.pack(fill=X, padx=20, pady=(0, 4))
        self._desc_text = tk.Text(desc_frame, height=2, font=("Segoe UI", 9),
                                  relief="solid", bd=1, wrap=WORD, width=50)
        self._desc_text.pack(fill=X)

        # Type-specific fields container
        self._type_fields_frame = ttk.Frame(parent)
        self._type_fields_frame.pack(fill=X, padx=16, pady=(4, 0))

        # Tags
        tags_label = ttk.Label(parent, text="Tags:", font=("Segoe UI", 8, "bold"))
        tags_label.pack(anchor=W, padx=24, pady=(8, 2))
        tags_frame = ttk.Frame(parent)
        tags_frame.pack(fill=X, padx=20, pady=(0, 4))
        self._tags_entry = ttk.Entry(tags_frame, width=50)
        self._tags_entry.pack(fill=X)
        tags_help = ttk.Label(parent, text="Separate tags with commas (e.g., fundamentals, band, grade-6)",
                             font=("Segoe UI", 7), foreground=muted_fg())
        tags_help.pack(anchor=W, padx=24, pady=(0, 4))

        # Notes
        notes_label = ttk.Label(parent, text="Notes:", font=("Segoe UI", 8, "bold"))
        notes_label.pack(anchor=W, padx=24, pady=(4, 2))
        notes_frame = ttk.Frame(parent)
        notes_frame.pack(fill=X, padx=20, pady=(0, 4))
        self._notes_text = tk.Text(notes_frame, height=2, font=("Segoe UI", 9),
                                   relief="solid", bd=1, wrap=WORD, width=50)
        self._notes_text.pack(fill=X)

    def _on_type_change(self):
        # Clear previous type-specific fields
        for w in self._type_fields_frame.winfo_children():
            w.destroy()

        selected = self._vars["resource_type"].get()
        if not selected:
            return

        # Map display back to key
        resource_type = None
        for key, display in RESOURCE_TYPES.items():
            if display == selected:
                resource_type = key
                break

        if resource_type == "onenote":
            self._add_field("URL", "url_or_path")
        elif resource_type == "onedrive":
            row = ttk.Frame(self._type_fields_frame)
            row.pack(fill=X, pady=4)
            ttk.Label(row, text="URL or Path:", font=("Segoe UI", 8)).pack(side=LEFT, padx=(0, 6))
            var = self._vars.get("url_or_path") or tk.StringVar()
            self._vars["url_or_path"] = var
            ttk.Entry(row, textvariable=var, width=28).pack(side=LEFT, fill=X, expand=True)
            ttk.Button(row, text="Browse", bootstyle=INFO,
                      command=self._browse_folder).pack(side=LEFT, padx=(4, 0))
        elif resource_type == "local_folder":
            row = ttk.Frame(self._type_fields_frame)
            row.pack(fill=X, pady=4)
            ttk.Label(row, text="Path:", font=("Segoe UI", 8)).pack(side=LEFT, padx=(0, 6))
            var = self._vars.get("url_or_path") or tk.StringVar()
            self._vars["url_or_path"] = var
            ttk.Entry(row, textvariable=var, width=28).pack(side=LEFT, fill=X, expand=True)
            ttk.Button(row, text="Browse", bootstyle=INFO,
                      command=self._browse_folder).pack(side=LEFT, padx=(4, 0))
        elif resource_type == "url":
            self._add_field("URL", "url_or_path")
        elif resource_type == "file":
            row = ttk.Frame(self._type_fields_frame)
            row.pack(fill=X, pady=4)
            ttk.Label(row, text="File:", font=("Segoe UI", 8)).pack(side=LEFT, padx=(0, 6))
            var = self._vars.get("url_or_path") or tk.StringVar()
            self._vars["url_or_path"] = var
            ttk.Entry(row, textvariable=var, width=28).pack(side=LEFT, fill=X, expand=True)
            ttk.Button(row, text="Browse", bootstyle=INFO,
                      command=self._browse_file).pack(side=LEFT, padx=(4, 0))
        elif resource_type == "music_link":
            row = ttk.Frame(self._type_fields_frame)
            row.pack(fill=X, pady=4)
            ttk.Label(row, text="Music Piece:", font=("Segoe UI", 8)).pack(side=LEFT, padx=(0, 6))

            # Build sheet music dropdown
            self._sheet_music_map = {}
            options = []
            pieces = self.db.get_all_sheet_music()
            for piece in pieces:
                label = piece.get("title", "Unknown")
                self._sheet_music_map[label] = piece["id"]
                options.append(label)

            var = self._vars.get("music_id") or tk.StringVar()
            self._vars["music_id"] = var
            ttk.Combobox(row, textvariable=var, values=options,
                        width=28, state="readonly").pack(side=LEFT, fill=X, expand=True)
        elif resource_type == "method_book_ref":
            row1 = ttk.Frame(self._type_fields_frame)
            row1.pack(fill=X, pady=2)
            ttk.Label(row1, text="Book Title:", font=("Segoe UI", 8)).pack(side=LEFT, padx=(0, 6))
            var = self._vars.get("method_book_title") or tk.StringVar()
            self._vars["method_book_title"] = var
            ttk.Entry(row1, textvariable=var, width=28).pack(side=LEFT, fill=X, expand=True)

            row2 = ttk.Frame(self._type_fields_frame)
            row2.pack(fill=X, pady=2)
            ttk.Label(row2, text="Page Range:", font=("Segoe UI", 8)).pack(side=LEFT, padx=(0, 6))
            var = self._vars.get("method_book_pages") or tk.StringVar()
            self._vars["method_book_pages"] = var
            ttk.Entry(row2, textvariable=var, width=28).pack(side=LEFT, fill=X, expand=True)
        elif resource_type == "custom":
            self._add_field("URL/Path", "url_or_path")

    def _add_field(self, label, key):
        row = ttk.Frame(self._type_fields_frame)
        row.pack(fill=X, pady=4)
        ttk.Label(row, text=f"{label}:", font=("Segoe UI", 8)).pack(side=LEFT, padx=(0, 6))
        var = self._vars.get(key) or tk.StringVar()
        self._vars[key] = var
        ttk.Entry(row, textvariable=var, width=40).pack(side=LEFT, fill=X, expand=True)

    def _browse_folder(self):
        path = filedialog.askdirectory(parent=self)
        if path:
            self._vars.get("url_or_path").set(path)

    def _browse_file(self):
        path = filedialog.askopenfilename(parent=self)
        if path:
            self._vars.get("url_or_path").set(path)

    def _load(self, resource_id: int):
        resource = self.db.get_resource(resource_id)
        if not resource:
            return

        res_type = resource.get("resource_type")
        type_display = RESOURCE_TYPES.get(res_type, res_type)
        self._vars["resource_type"].set(type_display)
        self._on_type_change()

        self._vars["display_name"].set(resource.get("display_name") or "")
        self._desc_text.delete("1.0", "end")
        self._desc_text.insert("1.0", resource.get("description") or "")

        self._vars["url_or_path"].set(resource.get("url_or_path") or "")
        self._vars["method_book_title"].set(resource.get("method_book_title") or "")
        self._vars["method_book_pages"].set(resource.get("method_book_pages") or "")
        self._vars["music_id"].set(resource.get("music_id") or "")
        self._notes_text.delete("1.0", "end")
        self._notes_text.insert("1.0", resource.get("notes") or "")

        tags = self.db.get_resource_tags(resource_id)
        self._tags_entry.delete(0, "end")
        self._tags_entry.insert(0, ", ".join(tags))

    def _collect(self) -> dict:
        selected = self._vars.get("resource_type", tk.StringVar()).get()
        resource_type = None
        for key, display in RESOURCE_TYPES.items():
            if display == selected:
                resource_type = key
                break

        data = {
            "resource_type": resource_type,
            "display_name": self._vars.get("display_name", tk.StringVar()).get().strip(),
            "description": self._desc_text.get("1.0", "end").strip(),
            "url_or_path": self._vars.get("url_or_path", tk.StringVar()).get().strip(),
            "method_book_title": self._vars.get("method_book_title", tk.StringVar()).get().strip(),
            "method_book_pages": self._vars.get("method_book_pages", tk.StringVar()).get().strip(),
            "music_id": self._vars.get("music_id", tk.StringVar()).get(),
            "notes": self._notes_text.get("1.0", "end").strip(),
        }

        # Parse tags
        tags_str = self._tags_entry.get().strip()
        data["tags"] = [t.strip() for t in tags_str.split(",") if t.strip()]

        return data

    def _validate(self, data: dict) -> bool:
        if not data.get("resource_type"):
            Messagebox.show_warning("Resource type is required.", title="Validation", parent=self)
            return False
        if not data.get("display_name"):
            Messagebox.show_warning("Display name is required.", title="Validation", parent=self)
            return False
        if not data.get("url_or_path") and data.get("resource_type") != "music_link":
            if data.get("resource_type") != "method_book_ref":
                Messagebox.show_warning(
                    "URL/Path is required for this resource type.",
                    title="Validation"
, parent=self)
                return False
        return True

    def _save(self):
        data = self._collect()
        if not self._validate(data):
            return
        if self.resource_id:
            self.db.update_resource(self.resource_id, data)
        else:
            self.db.add_resource(data)
        self.destroy()
