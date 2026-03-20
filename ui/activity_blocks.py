"""
Activity Blocks widget for lesson plan editing.
Compact, professional block cards with inline editing.
"""

import tkinter as tk
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from ttkbootstrap.dialogs import Messagebox
from ui.theme import muted_fg, subtle_fg, fg, fs, is_dark


BLOCK_TYPES = {
    "rehearsal":     {"icon": "\u266b", "label": "Repertoire Rehearsal",  "color": "#4A90D9"},
    "sectional":     {"icon": "\u2261", "label": "Sectional",            "color": "#E67E22"},
    "sight_reading": {"icon": "\u25ce", "label": "Sight-Reading",        "color": "#27AE60"},
    "theory":        {"icon": "\u2263", "label": "Theory/Musicianship",  "color": "#8E44AD"},
    "listening":     {"icon": "\u266a", "label": "Listening/Analysis",   "color": "#2980B9"},
    "composition":   {"icon": "\u270e", "label": "Composition/Improv",   "color": "#D35400"},
    "warmup":        {"icon": "\u2600", "label": "Warm-Up Activity",     "color": "#F39C12"},
    "custom":        {"icon": "\u2022", "label": "Custom Activity",      "color": "#7F8C8D"},
}


class ActivityBlocksWidget(ttk.Frame):
    """Compact activity block manager with inline editing."""

    def __init__(self, parent, db, lesson_plan_id=None, class_duration=45, on_change=None):
        super().__init__(parent)
        self.db = db
        self.lesson_plan_id = lesson_plan_id
        self.class_duration = class_duration
        self.on_change = on_change
        self.blocks = []
        self.selected_block_id = None
        self.editing_block_id = None
        self._edit_widgets = {}

        self._build_ui()
        if lesson_plan_id:
            self.load_blocks(lesson_plan_id)

    def _build_ui(self):
        """Build toolbar and scrollable block list."""
        # ── Toolbar ──
        toolbar = ttk.Frame(self)
        toolbar.pack(fill=X, padx=4, pady=(4, 2))

        # Add Block dropdown
        self.add_btn = ttk.Menubutton(toolbar, text="+ Add Block", bootstyle=PRIMARY)
        self.add_btn.pack(side=LEFT, padx=(0, 4))
        add_menu = tk.Menu(self.add_btn, tearoff=False)
        self.add_btn.config(menu=add_menu)
        for btype, info in BLOCK_TYPES.items():
            add_menu.add_command(
                label=f"{info['icon']} {info['label']}",
                command=lambda bt=btype: self._add_block(bt),
            )

        # Compact toolbar buttons
        ttk.Button(toolbar, text="\u25b2", bootstyle=(SECONDARY, OUTLINE),
                   command=self._move_up, width=3).pack(side=LEFT, padx=1)
        ttk.Button(toolbar, text="\u25bc", bootstyle=(SECONDARY, OUTLINE),
                   command=self._move_down, width=3).pack(side=LEFT, padx=1)
        ttk.Button(toolbar, text="\u2715", bootstyle=(DANGER, OUTLINE),
                   command=self._remove_block, width=3).pack(side=LEFT, padx=(1, 4))

        # Time summary
        self.time_label = ttk.Label(toolbar, text="0 / 45 min", bootstyle=INFO,
                                     font=("Segoe UI", fs(9)))
        self.time_label.pack(side=LEFT, padx=4)

        # ── Block list (simple frame — blocks stack vertically) ──
        self.blocks_scrollable = ttk.Frame(self)
        self.blocks_scrollable.pack(fill=X, padx=4, pady=2)

    # ═══════════════════════ Block CRUD ═══════════════════════

    def _add_block(self, block_type):
        info = BLOCK_TYPES[block_type]
        new_block = {
            "id": id(object()),  # temp unique id
            "lesson_plan_id": self.lesson_plan_id,
            "block_type": block_type,
            "title": f"New {info['label']}",
            "description": "",
            "duration_minutes": 10,
            "sort_order": len(self.blocks),
            "notes": "",
            "technique_focus": "",
            "grouping": "",
            "difficulty_level": "Medium",
            "measure_start": None,
            "measure_end": None,
            "music_piece_id": None,
        }
        self.blocks.append(new_block)
        self._redraw_blocks()
        self._fire_on_change()

    def _remove_block(self):
        if self.selected_block_id is None:
            return
        self.blocks = [b for b in self.blocks if b.get("id") != self.selected_block_id]
        self.selected_block_id = None
        self.editing_block_id = None
        self._update_sort_order()
        self._redraw_blocks()
        self._fire_on_change()

    def _move_up(self):
        idx = self._selected_index()
        if idx is None or idx == 0:
            return
        self.blocks[idx], self.blocks[idx - 1] = self.blocks[idx - 1], self.blocks[idx]
        self._update_sort_order()
        self._redraw_blocks()
        self._fire_on_change()

    def _move_down(self):
        idx = self._selected_index()
        if idx is None or idx >= len(self.blocks) - 1:
            return
        self.blocks[idx], self.blocks[idx + 1] = self.blocks[idx + 1], self.blocks[idx]
        self._update_sort_order()
        self._redraw_blocks()
        self._fire_on_change()

    def _selected_index(self):
        if self.selected_block_id is None:
            return None
        for i, b in enumerate(self.blocks):
            if b.get("id") == self.selected_block_id:
                return i
        return None

    def _update_sort_order(self):
        for i, block in enumerate(self.blocks):
            block["sort_order"] = i

    # ═══════════════════════ Rendering ═══════════════════════

    def _redraw_blocks(self):
        for widget in self.blocks_scrollable.winfo_children():
            widget.destroy()
        self._edit_widgets = {}

        for block in self.blocks:
            self._create_block_card(block)

        self._update_time_label()

    def _create_block_card(self, block):
        """Create a compact block card with optional inline edit panel."""
        bid = block.get("id")
        btype = block.get("block_type", "custom")
        info = BLOCK_TYPES.get(btype, BLOCK_TYPES["custom"])
        is_selected = bid == self.selected_block_id
        is_editing = bid == self.editing_block_id

        # ── Outer container ──
        outer = ttk.Frame(self.blocks_scrollable)
        outer.pack(fill=X, padx=0, pady=1)

        # ── Card row — use tk.Frame so we can set highlightbackground for selection ──
        sel_color = info["color"] if is_selected else (
            "#cccccc" if not is_dark() else "#555555"
        )
        card = tk.Frame(
            outer,
            highlightbackground=sel_color,
            highlightthickness=2 if is_selected else 1,
            bg=ttk.Style().lookup("TFrame", "background"),
        )
        card.pack(fill=X)
        card.bind("<Button-1>", lambda e, b=bid: self._select_block(b))

        # Color stripe
        stripe = tk.Frame(card, width=4, bg=info["color"])
        stripe.pack(side=LEFT, fill=Y)
        stripe.pack_propagate(False)
        stripe.bind("<Button-1>", lambda e, b=bid: self._select_block(b))

        # ── RIGHT side packed BEFORE content so expand=True doesn't crowd it out ──
        right = ttk.Frame(card)
        right.pack(side=RIGHT, padx=4, pady=3)

        dur_var = tk.IntVar(value=block.get("duration_minutes", 10))
        ttk.Spinbox(
            right, from_=1, to=60, textvariable=dur_var, width=3,
            command=lambda: self._update_block_duration(block, dur_var.get()),
        ).pack(side=LEFT, padx=1)
        ttk.Label(right, text="m", font=("Segoe UI", fs(8)),
                  foreground=muted_fg()).pack(side=LEFT)
        edit_lbl = tk.Label(
            right, text="Edit",
            font=("Segoe UI", fs(8)),
            foreground="#17a2b8",
            cursor="hand2",
            relief=tk.GROOVE,
            bd=1,
            padx=4,
            pady=2,
        )
        edit_lbl.pack(side=LEFT, padx=(4, 0))
        edit_lbl.bind("<Button-1>", lambda e, b=bid: self._toggle_edit(b))

        # Content area — packed after right so right is never crowded out
        content = ttk.Frame(card)
        content.pack(side=LEFT, fill=X, expand=True, padx=4, pady=3)
        content.bind("<Button-1>", lambda e, b=bid: self._select_block(b))

        title_text = block.get("title", "Untitled")
        title_lbl = ttk.Label(
            content, text=f"{info['icon']}  {title_text}",
            font=("Segoe UI", fs(9), "bold"),
        )
        title_lbl.pack(anchor=W)
        title_lbl.bind("<Button-1>", lambda e, b=bid: self._select_block(b))

        desc = block.get("description", "")
        if desc:
            desc_display = desc[:80] + "..." if len(desc) > 80 else desc
            desc_lbl = ttk.Label(
                content, text=desc_display,
                foreground=muted_fg(), font=("Segoe UI", fs(8)),
            )
            desc_lbl.pack(anchor=W)
            desc_lbl.bind("<Button-1>", lambda e, b=bid: self._select_block(b))

        # ── Inline edit panel (shown below card when editing) ──
        if is_editing:
            self._build_inline_edit(outer, block)

    def _toggle_edit(self, block_id):
        """Toggle inline edit for a block."""
        if self.editing_block_id == block_id:
            # Close edit
            self.editing_block_id = None
        else:
            self.editing_block_id = block_id
            self.selected_block_id = block_id
        self._redraw_blocks()

    def _build_inline_edit(self, parent, block):
        """Build inline edit form below the block card."""
        edit = ttk.Frame(parent, relief=GROOVE, borderwidth=1)
        edit.pack(fill=X, padx=8, pady=(0, 2))

        # Title
        row0 = ttk.Frame(edit)
        row0.pack(fill=X, padx=6, pady=(6, 2))
        ttk.Label(row0, text="Title:", font=("Segoe UI", fs(8)),
                  foreground=muted_fg()).pack(side=LEFT, padx=(0, 4))
        title_var = tk.StringVar(value=block.get("title", ""))
        title_entry = ttk.Entry(row0, textvariable=title_var, font=("Segoe UI", fs(9)))
        title_entry.pack(side=LEFT, fill=X, expand=True)

        # Description
        row1 = ttk.Frame(edit)
        row1.pack(fill=X, padx=6, pady=2)
        ttk.Label(row1, text="Desc:", font=("Segoe UI", fs(8)),
                  foreground=muted_fg()).pack(side=LEFT, anchor=N, padx=(0, 4), pady=2)
        desc_text = tk.Text(row1, height=2, font=("Segoe UI", fs(9)))
        desc_text.insert("1.0", block.get("description", ""))
        desc_text.pack(side=LEFT, fill=X, expand=True)

        # Type-specific fields
        btype = block.get("block_type", "")
        extra_vars = {}

        if btype == "rehearsal":
            row2 = ttk.Frame(edit)
            row2.pack(fill=X, padx=6, pady=2)
            ttk.Label(row2, text="Focus:", font=("Segoe UI", fs(8)),
                      foreground=muted_fg()).pack(side=LEFT, padx=(0, 4))
            tech_var = tk.StringVar(value=block.get("technique_focus", ""))
            ttk.Entry(row2, textvariable=tech_var, font=("Segoe UI", fs(9))).pack(
                side=LEFT, fill=X, expand=True)
            extra_vars["technique_focus"] = tech_var

            row3 = ttk.Frame(edit)
            row3.pack(fill=X, padx=6, pady=2)
            ttk.Label(row3, text="Measures:", font=("Segoe UI", fs(8)),
                      foreground=muted_fg()).pack(side=LEFT, padx=(0, 4))
            ms_var = tk.IntVar(value=block.get("measure_start") or 1)
            ttk.Spinbox(row3, from_=1, to=500, textvariable=ms_var, width=4).pack(side=LEFT)
            ttk.Label(row3, text="to", font=("Segoe UI", fs(8))).pack(side=LEFT, padx=4)
            me_var = tk.IntVar(value=block.get("measure_end") or 1)
            ttk.Spinbox(row3, from_=1, to=500, textvariable=me_var, width=4).pack(side=LEFT)
            extra_vars["measure_start"] = ms_var
            extra_vars["measure_end"] = me_var

        elif btype == "sectional":
            row2 = ttk.Frame(edit)
            row2.pack(fill=X, padx=6, pady=2)
            ttk.Label(row2, text="Group:", font=("Segoe UI", fs(8)),
                      foreground=muted_fg()).pack(side=LEFT, padx=(0, 4))
            grp_var = tk.StringVar(value=block.get("grouping", ""))
            ttk.Entry(row2, textvariable=grp_var, font=("Segoe UI", fs(9))).pack(
                side=LEFT, fill=X, expand=True)
            extra_vars["grouping"] = grp_var

        elif btype == "sight_reading":
            row2 = ttk.Frame(edit)
            row2.pack(fill=X, padx=6, pady=2)
            ttk.Label(row2, text="Level:", font=("Segoe UI", fs(8)),
                      foreground=muted_fg()).pack(side=LEFT, padx=(0, 4))
            diff_var = tk.StringVar(value=block.get("difficulty_level", "Medium"))
            ttk.Combobox(row2, values=["Easy", "Medium", "Hard"],
                         textvariable=diff_var, width=10, state="readonly").pack(side=LEFT)
            extra_vars["difficulty_level"] = diff_var

        # Notes
        row_notes = ttk.Frame(edit)
        row_notes.pack(fill=X, padx=6, pady=2)
        ttk.Label(row_notes, text="Notes:", font=("Segoe UI", fs(8)),
                  foreground=muted_fg()).pack(side=LEFT, anchor=N, padx=(0, 4), pady=2)
        notes_text = tk.Text(row_notes, height=1, font=("Segoe UI", fs(9)))
        notes_text.insert("1.0", block.get("notes", ""))
        notes_text.pack(side=LEFT, fill=X, expand=True)

        # Save / Cancel buttons
        btn_row = ttk.Frame(edit)
        btn_row.pack(fill=X, padx=6, pady=(2, 6))

        def _save():
            block["title"] = title_var.get()
            block["description"] = desc_text.get("1.0", "end").strip()
            block["notes"] = notes_text.get("1.0", "end").strip()
            for key, var in extra_vars.items():
                block[key] = var.get()
            self.editing_block_id = None
            self._redraw_blocks()
            self._fire_on_change()

        def _cancel():
            self.editing_block_id = None
            self._redraw_blocks()

        ttk.Button(btn_row, text="Done", bootstyle=SUCCESS, width=6,
                   command=_save).pack(side=LEFT, padx=(0, 4))
        ttk.Button(btn_row, text="Cancel", bootstyle=SECONDARY, width=6,
                   command=_cancel).pack(side=LEFT)

    # ═══════════════════════ Selection & Updates ═══════════════════════

    def _select_block(self, block_id):
        self.selected_block_id = block_id
        self._redraw_blocks()

    def _update_block_duration(self, block, minutes):
        block["duration_minutes"] = minutes
        self._update_time_label()
        self._fire_on_change()

    def _update_time_label(self):
        total = self.get_total_minutes()
        self.time_label.config(text=f"{total} / {self.class_duration} min")
        if total <= self.class_duration:
            self.time_label.config(bootstyle=SUCCESS)
        elif total <= self.class_duration + 5:
            self.time_label.config(bootstyle=WARNING)
        else:
            self.time_label.config(bootstyle=DANGER)

    def _fire_on_change(self):
        if self.on_change:
            self.on_change()

    # ═══════════════════════ Data ═══════════════════════

    def load_blocks(self, lesson_plan_id):
        if not self.db:
            return
        self.lesson_plan_id = lesson_plan_id
        db_blocks = self.db.get_lesson_blocks(lesson_plan_id)
        self.blocks = [dict(b) for b in db_blocks] if db_blocks else []
        self._redraw_blocks()

    def get_blocks_data(self):
        return self.blocks

    def save_blocks(self, lesson_plan_id):
        if not self.db:
            return
        self.lesson_plan_id = lesson_plan_id
        for block in self.db.get_lesson_blocks(lesson_plan_id) or []:
            self.db.delete_lesson_block(block["id"])
        for block in self.blocks:
            self.db.add_lesson_block({
                "lesson_plan_id": lesson_plan_id,
                "block_type": block.get("block_type", "custom"),
                "title": block.get("title", ""),
                "description": block.get("description", ""),
                "duration_minutes": block.get("duration_minutes", 5),
                "sort_order": block.get("sort_order", 0),
                "notes": block.get("notes", ""),
                "music_piece_id": block.get("music_piece_id"),
                "measure_start": block.get("measure_start"),
                "measure_end": block.get("measure_end"),
                "technique_focus": block.get("technique_focus", ""),
                "grouping": block.get("grouping", ""),
                "difficulty_level": block.get("difficulty_level", "Medium"),
            })

    def get_total_minutes(self):
        return sum(b.get("duration_minutes", 0) for b in self.blocks)
