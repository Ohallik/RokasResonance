"""
ui/percussion_rotation_view.py - Percussion section rotation planner.

Enter the percussionists in each class period and the tool builds a balanced
daily rotation (mallets / snare / timpani-auxiliary, plus bass-drum and, for
Intermediate/Advanced, drum-set seats).  Entry players start on mallets only
and are moved into the full rotation once they pass their first five
assessments.  Special one-off days (everyone on mallets, everyone on
snare/pad) can be set per rotation day.

Rotation math lives in ``percussion_rotation.py``; this module is UI + storage.
"""

import os
import tkinter as tk
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from ttkbootstrap.dialogs import Messagebox

import percussion_rotation as pr
from ui.theme import muted_fg, fs

CLASS_TYPE_LABELS = {
    pr.ENTRY: "Entry",
    pr.INT_ADV: "Intermediate / Advanced",
}
LABEL_TO_CLASS_TYPE = {v: k for k, v in CLASS_TYPE_LABELS.items()}

# Two brand-new mallet colours signify the STICK a student grabs:
YARN_COLOR = "#ffd8a8"      # orange — yarn mallets (marimba, vibraphone)
RUBBER_COLOR = "#ffffff"    # white  — rubber/plastic mallets (xylophone, bells)

# Fixed station colours (the teacher's original board scheme).
STATION_COLORS = {
    pr.MALLETS:   "#f6d9d9",   # reddish — full-rotation free-choice mallet day
    pr.SD:        "#fbeecb",   # light yellow — snare
    pr.BD_SD:     "#d9ecd2",   # green — bass drum
    pr.TIMP_AUX:  "#e6dbf1",   # purple — timpani / auxiliary
    pr.DRUM_SET:  "#d6e4f5",   # blue — drum set
    pr.ALL_SNARE_LABEL: "#fbeecb",
    pr.PAD:       "#ececec",   # gray — practice pad
}


def _color_for_station(station: str) -> str:
    """Background colour for a station: fixed stations by name, mallet
    instruments by stick family (yarn = orange, rubber/plastic = white)."""
    if station in STATION_COLORS:
        return STATION_COLORS[station]
    fam = pr.mallet_family(station)
    if fam == pr.YARN_MALLETS:
        return YARN_COLOR
    if fam == pr.RUBBER_MALLETS:
        return RUBBER_COLOR
    return "#ffffff"


def _station_tag(station: str) -> str:
    return "bg_" + _color_for_station(station).lstrip("#")


def _configure_station_tags(tree: ttk.Treeview):
    colors = set(STATION_COLORS.values()) | {YARN_COLOR, RUBBER_COLOR, "#ffffff"}
    for c in colors:
        tree.tag_configure("bg_" + c.lstrip("#"), background=c)


# ── Mallet-type icons: crossed mallets, red/yarn vs white/rubber ──────────────
# Students see at a glance which sticks to grab.  Drawn with PIL and cached on
# the toplevel (so each window keeps its own live PhotoImage references).

def _mallet_icon_image(family, px=18):
    from PIL import Image, ImageDraw
    s = 4
    W = H = px * s
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    sw = max(2, int(W * 0.08))
    stick = (70, 70, 70, 255)
    d.line([(W * 0.22, H * 0.90), (W * 0.64, H * 0.34)], fill=stick, width=sw)
    d.line([(W * 0.78, H * 0.90), (W * 0.36, H * 0.34)], fill=stick, width=sw)
    if family == pr.YARN_MALLETS:
        head, hi = (211, 78, 55, 255), (242, 150, 120, 255)     # warm red/orange
    else:
        head, hi = (232, 232, 235, 255), (255, 255, 255, 255)   # white/silver
    r = int(W * 0.18)
    for cx, cy in [(W * 0.64, H * 0.30), (W * 0.36, H * 0.30)]:
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=head,
                  outline=(60, 60, 60, 255), width=max(1, sw // 2))
        d.ellipse([cx - r * 0.5, cy - r * 0.5, cx + r * 0.1, cy + r * 0.1], fill=hi)
    return img.resize((px, px), Image.LANCZOS)


def _mallet_icon(widget, family):
    top = widget.winfo_toplevel()
    cache = getattr(top, "_mallet_icons", None)
    if cache is None:
        cache = {}
        top._mallet_icons = cache
    if family not in cache:
        try:
            from PIL import ImageTk
            cache[family] = ImageTk.PhotoImage(_mallet_icon_image(family),
                                               master=top)
        except Exception:
            cache[family] = None
    return cache[family]


def _yarn_icon(widget):
    return _mallet_icon(widget, pr.YARN_MALLETS)


def _rubber_icon(widget):
    return _mallet_icon(widget, pr.RUBBER_MALLETS)


def _icon_for_station(widget, station):
    fam = pr.mallet_family(station)
    if fam == pr.YARN_MALLETS:
        return _yarn_icon(widget)
    if fam == pr.RUBBER_MALLETS:
        return _rubber_icon(widget)
    return None


class PercussionRotationView(ttk.Frame):
    def __init__(self, parent, db):
        super().__init__(parent)
        self.db = db
        self._selected_group_id = None
        self._build()
        self.refresh()

    # ───────────────────────────────────────────────────────────── build ─────

    def _build(self):
        toolbar = ttk.Frame(self, bootstyle=LIGHT)
        toolbar.pack(fill=X)
        ttk.Button(toolbar, text="➕ New Section", bootstyle=SUCCESS,
                   command=self._add_group).pack(side=LEFT, padx=6, pady=6)
        ttk.Button(toolbar, text="✏️ Edit", bootstyle=PRIMARY,
                   command=self._edit_group).pack(side=LEFT, padx=2, pady=6)
        ttk.Button(toolbar, text="🗑️ Delete", bootstyle=DANGER,
                   command=self._delete_group).pack(side=LEFT, padx=2, pady=6)
        ttk.Button(toolbar, text="🎵 Mallet Equipment…", bootstyle=(INFO, OUTLINE),
                   command=self._edit_equipment).pack(side=LEFT, padx=2, pady=6)
        ttk.Button(toolbar, text="🔄 Refresh", bootstyle=(SECONDARY, OUTLINE),
                   command=self.refresh).pack(side=LEFT, padx=6, pady=6)
        ttk.Label(toolbar,
                  text="Enter each class period's percussionists → automatic daily rotation",
                  font=("Segoe UI", fs(9)), foreground=muted_fg()).pack(side=LEFT, padx=10)

        paned = ttk.Panedwindow(self, orient=HORIZONTAL)
        paned.pack(fill=BOTH, expand=True, padx=6, pady=6)

        # Left — list of sections
        left = ttk.Frame(paned)
        paned.add(left, weight=1)
        ttk.Label(left, text="Class Periods", font=("Segoe UI", fs(10), "bold")).pack(
            anchor=W, pady=(2, 4))
        cols = ("Section", "Type", "Players")
        self._groups_tree = ttk.Treeview(left, columns=cols, show="headings",
                                         selectmode="browse", bootstyle=PRIMARY, height=8)
        for c, w in zip(cols, (150, 90, 60)):
            self._groups_tree.heading(c, text=c, anchor=W)
            self._groups_tree.column(c, width=w, anchor=W,
                                     stretch=(c == "Section"))
        self._groups_tree.pack(fill=BOTH, expand=True)
        self._groups_tree.bind("<<TreeviewSelect>>", lambda e: self._on_group_selected())
        self._groups_tree.bind("<Double-1>", lambda e: self._edit_group())

        # Right — working area
        right = ttk.Frame(paned)
        paned.add(right, weight=3)
        self._build_right(right)

    def _build_right(self, parent):
        self._detail = parent

        # Placeholder shown when nothing is selected
        self._placeholder = ttk.Frame(parent)
        ttk.Label(self._placeholder, text="🥁", font=("Segoe UI", fs(36))).pack(pady=(40, 8))
        ttk.Label(self._placeholder,
                  text="Select a class period, or click “New Section” to start.",
                  font=("Segoe UI", fs(11)), foreground=muted_fg()).pack()
        self._placeholder.pack(fill=BOTH, expand=True)

        # The actual content frame (packed when a group is selected)
        self._content = ttk.Frame(parent)

        # -- Header row: section name + composition summary --
        self._section_lbl = ttk.Label(self._content, text="",
                                       font=("Segoe UI", fs(13), "bold"), bootstyle=PRIMARY)
        self._section_lbl.pack(anchor=W)
        self._summary_lbl = ttk.Label(self._content, text="", font=("Segoe UI", fs(9)),
                                      foreground=muted_fg(), wraplength=520, justify=LEFT)
        self._summary_lbl.pack(anchor=W, pady=(0, 6))

        # -- Day controls --
        day_bar = ttk.Frame(self._content)
        day_bar.pack(fill=X, pady=(0, 4))
        ttk.Label(day_bar, text="Rotation Day:",
                  font=("Segoe UI", fs(10), "bold")).pack(side=LEFT)
        ttk.Button(day_bar, text="◀", width=3, bootstyle=(SECONDARY, OUTLINE),
                   command=lambda: self._step_day(-1)).pack(side=LEFT, padx=(6, 2))
        self._day_var = tk.StringVar(value="1")
        self._day_spin = ttk.Spinbox(day_bar, from_=1, to=999, width=5,
                                     textvariable=self._day_var, command=self._on_day_edited)
        self._day_spin.pack(side=LEFT, padx=2)
        self._day_spin.bind("<Return>", lambda e: self._on_day_edited())
        self._day_spin.bind("<FocusOut>", lambda e: self._on_day_edited())
        ttk.Button(day_bar, text="Next ▶", bootstyle=SUCCESS,
                   command=lambda: self._step_day(1)).pack(side=LEFT, padx=(2, 10))
        self._cycle_lbl = ttk.Label(day_bar, text="", font=("Segoe UI", fs(9)),
                                    foreground=muted_fg())
        self._cycle_lbl.pack(side=LEFT)

        ttk.Button(day_bar, text="📋 Copy", bootstyle=(INFO, OUTLINE),
                   command=self._copy_today).pack(side=RIGHT, padx=2)
        ttk.Button(day_bar, text="🗓 Full Grid", bootstyle=(INFO, OUTLINE),
                   command=self._show_full_grid).pack(side=RIGHT, padx=2)
        ttk.Button(day_bar, text="⭐ Special Day…", bootstyle=(WARNING, OUTLINE),
                   command=self._special_day).pack(side=RIGHT, padx=2)

        self._override_lbl = ttk.Label(self._content, text="", font=("Segoe UI", fs(9), "bold"),
                                       bootstyle=WARNING)
        self._override_lbl.pack(anchor=W)

        # -- Today's assignment board --
        board_frame = ttk.Labelframe(self._content, text=" Today's Assignment ", padding=4)
        board_frame.pack(fill=BOTH, expand=True, pady=(4, 6))
        bcols = ("Player", "Station")
        # "tree headings": the #0 column carries the mallet-type icon per row.
        self._board = ttk.Treeview(board_frame, columns=bcols,
                                   show="tree headings",
                                   selectmode="none", bootstyle=INFO)
        self._board.heading("#0", text="")
        self._board.column("#0", width=34, minwidth=34, stretch=False,
                           anchor=CENTER)
        self._board.heading("Player", text="Player", anchor=W)
        self._board.heading("Station", text="Working On", anchor=W)
        self._board.column("Player", width=160, anchor=W, stretch=True)
        self._board.column("Station", width=160, anchor=W, stretch=True)
        _configure_station_tags(self._board)
        self._board.pack(fill=BOTH, expand=True)

        # Legend: what the colours + icons mean.
        legend = ttk.Frame(self._content)
        legend.pack(fill=X, pady=(0, 4))

        def swatch(color, text, icon=None):
            cell = ttk.Frame(legend)
            cell.pack(side=LEFT, padx=(0, 10))
            tk.Label(cell, width=2, background=color, relief="solid",
                     borderwidth=1).pack(side=LEFT)
            if icon is not None:
                tk.Label(cell, image=icon).pack(side=LEFT, padx=(2, 0))
            ttk.Label(cell, text=text, font=("Segoe UI", fs(8))).pack(
                side=LEFT, padx=(3, 0))

        swatch(STATION_COLORS[pr.MALLETS], "Mallets (free choice)")
        swatch(YARN_COLOR, "Marimba / Vibraphone — yarn mallets",
               icon=_yarn_icon(self._board))
        swatch(RUBBER_COLOR, "Xylophone / Bells — rubber/plastic mallets",
               icon=_rubber_icon(self._board))
        swatch(STATION_COLORS[pr.PAD], "Practice pad")

        # -- Roster editor --
        roster_frame = ttk.Labelframe(self._content, text=" Percussionists ", padding=4)
        roster_frame.pack(fill=BOTH, expand=True)
        rbar = ttk.Frame(roster_frame)
        rbar.pack(fill=X, pady=(0, 4))
        ttk.Button(rbar, text="➕ Add Players", bootstyle=SUCCESS,
                   command=self._add_players).pack(side=LEFT, padx=2)
        ttk.Button(rbar, text="🗑 Remove", bootstyle=(DANGER, OUTLINE),
                   command=self._remove_player).pack(side=LEFT, padx=2)
        ttk.Button(rbar, text="▲", width=3, bootstyle=(SECONDARY, OUTLINE),
                   command=lambda: self._move_player(-1)).pack(side=LEFT, padx=(8, 1))
        ttk.Button(rbar, text="▼", width=3, bootstyle=(SECONDARY, OUTLINE),
                   command=lambda: self._move_player(1)).pack(side=LEFT, padx=1)
        self._earn_hint = ttk.Label(
            rbar, text="Tick “Full Rotation” once a player passes 5 assessments.",
            font=("Segoe UI", fs(8)), foreground=muted_fg())
        self._earn_hint.pack(side=LEFT, padx=10)

        rcols = ("Player", "Rotation")
        self._roster = ttk.Treeview(roster_frame, columns=rcols, show="headings",
                                    selectmode="browse", bootstyle=SECONDARY, height=7)
        self._roster.heading("Player", text="Player", anchor=W)
        self._roster.heading("Rotation", text="Full Rotation? (✔ = yes)", anchor=W)
        self._roster.column("Player", width=180, anchor=W, stretch=True)
        self._roster.column("Rotation", width=170, anchor=W)
        self._roster.pack(fill=BOTH, expand=True)
        self._roster.bind("<Button-1>", self._on_roster_click)
        self._roster.bind("<Double-1>", self._on_roster_double)

    # ─────────────────────────────────────────────────────────── data load ────

    def refresh(self):
        prev = self._selected_group_id
        self._groups_tree.delete(*self._groups_tree.get_children())
        groups = self.db.get_percussion_groups(self._school_year())
        for g in groups:
            players = self.db.get_percussion_students(g["id"])
            self._groups_tree.insert(
                "", "end", iid=str(g["id"]),
                values=(g["name"], CLASS_TYPE_LABELS.get(g["class_type"], g["class_type"]),
                        len(players)))
        # Restore / pick selection
        ids = [g["id"] for g in groups]
        if prev in ids:
            self._groups_tree.selection_set(str(prev))
        elif ids:
            self._groups_tree.selection_set(str(ids[0]))
        else:
            self._selected_group_id = None
            self._show_placeholder(True)

    def _inventory(self):
        """The room's mallet equipment [(name, students-at-a-time), ...] as
        set in “Mallet Equipment…”; None means the built-in default room."""
        if not hasattr(self, "_inv_cache"):
            self._inv_cache = self._load_inventory()
        return self._inv_cache

    def _load_inventory(self):
        import json
        raw = self.db.get_program_setting("mallet_inventory")
        if raw:
            try:
                return pr._norm_inventory(json.loads(raw))
            except Exception:
                pass
        # No list saved for this year yet: inherit from the most recent
        # year that has one.  Buying a new marimba is rare — the room list
        # carries forward indefinitely until the teacher edits it.
        from lesson_plan_db import (list_available_school_years,
                                    get_lesson_plan_db)
        base_dir = os.path.dirname(os.path.abspath(self.db.db_path))
        cur = self._year_from_db()
        for y in list_available_school_years(base_dir):     # newest first
            if y == cur:
                continue
            try:
                raw = get_lesson_plan_db(base_dir, y).get_program_setting(
                    "mallet_inventory")
                if raw:
                    return pr._norm_inventory(json.loads(raw))
            except Exception:
                continue
        return None

    def _edit_equipment(self):
        dlg = _MalletEquipmentDialog(self.winfo_toplevel(), self.db,
                                     initial=self._inventory())
        self.wait_window(dlg)
        if dlg.saved:
            if hasattr(self, "_inv_cache"):
                del self._inv_cache
            if self._selected_group_id is not None:
                self._render()

    def _school_year(self):
        return getattr(self.db, "_school_year_hint", None) or self._year_from_db()

    def _year_from_db(self):
        # Derive the year label from the db file name (lesson_plans_YYYY-YYYY.db)
        import os
        base = os.path.basename(self.db.db_path)
        if base.startswith("lesson_plans_") and base.endswith(".db"):
            return base[len("lesson_plans_"):-len(".db")]
        return None

    def _show_placeholder(self, show):
        if show:
            self._content.pack_forget()
            self._placeholder.pack(fill=BOTH, expand=True)
        else:
            self._placeholder.pack_forget()
            self._content.pack(fill=BOTH, expand=True)

    def _on_group_selected(self):
        sel = self._groups_tree.selection()
        if not sel:
            return
        self._selected_group_id = int(sel[0])
        g = self.db.get_percussion_group(self._selected_group_id)
        if not g:
            return
        self._show_placeholder(False)
        is_entry = g["class_type"] == pr.ENTRY
        # Show/hide the earn hint + rotation column meaning for int/adv
        self._earn_hint.config(text=(
            "Tick “Full Rotation” once a player passes 5 assessments."
            if is_entry else
            "All players are in the full rotation."))
        self._day_var.set(str(g["current_day"] or 1))
        self._render()

    def _current_group(self):
        if self._selected_group_id is None:
            return None
        return self.db.get_percussion_group(self._selected_group_id)

    def _students_payload(self, g):
        """Ordered list of dicts for the rotation engine + the raw rows."""
        rows = self.db.get_percussion_students(g["id"])
        is_entry = g["class_type"] == pr.ENTRY
        payload = []
        for r in rows:
            mallets_only = is_entry and not r["full_rotation"]
            payload.append({"name": r["name"], "mallets_only": mallets_only})
        return payload, rows

    def _render(self):
        g = self._current_group()
        if not g:
            return
        self._section_lbl.config(
            text=f"{g['name']}  ·  {CLASS_TYPE_LABELS.get(g['class_type'], '')}")
        payload, rows = self._students_payload(g)
        n_full = sum(1 for p in payload if not p["mallets_only"])
        n_mallet_only = len(payload) - n_full

        # Constrain the day to one cycle (wraps back to Day 1 each round).
        cycle = self._cycle_length()
        self._day_spin.config(to=cycle)
        self._cycle_lbl.config(text=f"of {cycle}")
        cur = ((self._day() - 1) % cycle) + 1
        if str(cur) != self._day_var.get():
            self._day_var.set(str(cur))

        # Composition summary
        if n_full:
            parts = [f"{c}× {label}" for label, c in pr.station_summary(n_full, g["class_type"])]
            summary = f"{n_full} in full rotation → " + ",  ".join(parts) + " each day."
            if n_mallet_only:
                summary += f"   ({n_mallet_only} on mallets-only, earning their rotation.)"
            mallet_load = (dict(pr.station_summary(n_full, g["class_type"]))
                           .get(pr.MALLETS, 0) + n_mallet_only)
        elif payload:
            summary = f"All {len(payload)} players on mallets-only (earning their rotation)."
            mallet_load = len(payload)
        else:
            summary = "No players yet — click “Add Players”."
            mallet_load = 0
        # The room only fits so many mallet players at once — see the
        # “Mallet Equipment…” button for what's available and its capacity.
        cap = sum(c for _, c in pr._norm_inventory(self._inventory()))
        if bool(g["mallet_subrotation"]) and mallet_load > cap:
            summary += (f"   ⚠ {mallet_load} mallet players share the "
                        f"{cap} instrument spots (see Mallet Equipment) — "
                        f"the extras rotate to a practice pad, which "
                        f"lengthens the cycle.")
        self._summary_lbl.config(text=summary)

        day = self._day()
        override = self.db.get_percussion_override(g["id"], day)
        mode = override["mode"] if override else pr.MODE_NORMAL
        if override:
            pretty = {pr.MODE_ALL_MALLETS: "Everyone on Mallets",
                      pr.MODE_ALL_SNARE: "Everyone on Snare / Pad"}.get(mode, mode)
            note = f" — {override['note']}" if override["note"] else ""
            self._override_lbl.config(text=f"⭐ Special day: {pretty}{note}")
        else:
            self._override_lbl.config(text="")

        # Board
        assignments = pr.day_assignments(
            payload, day, g["class_type"],
            mallet_subrotation=bool(g["mallet_subrotation"]), mode=mode,
            inventory=self._inventory())
        self._board.delete(*self._board.get_children())
        for name, station in assignments:
            icon = _icon_for_station(self._board, station)
            kw = {"image": icon} if icon is not None else {}
            self._board.insert("", "end", text="", values=(name, station),
                               tags=(_station_tag(station),), **kw)

        # Roster
        self._roster.delete(*self._roster.get_children())
        is_entry = g["class_type"] == pr.ENTRY
        for r in rows:
            if is_entry:
                rot = "✔  Full rotation" if r["full_rotation"] else "○  Mallets only (earning)"
            else:
                rot = "✔  Full rotation"
            self._roster.insert("", "end", iid=str(r["id"]), values=(r["name"], rot))

    # ───────────────────────────────────────────────────────── day controls ───

    def _day(self):
        try:
            return max(1, int(self._day_var.get()))
        except (ValueError, TypeError):
            return 1

    def _cycle_length(self):
        """Days in one full round (see percussion_rotation.cycle_length)."""
        g = self._current_group()
        if not g:
            return 1
        payload, _ = self._students_payload(g)
        return pr.cycle_length(payload,
                               mallet_subrotation=bool(g["mallet_subrotation"]),
                               inventory=self._inventory())

    def _on_day_edited(self):
        g = self._current_group()
        if not g:
            return
        # Keep the day within one cycle (wraps back to Day 1 after each round).
        cycle = self._cycle_length()
        day = ((self._day() - 1) % cycle) + 1
        if str(day) != self._day_var.get():
            self._day_var.set(str(day))
        self.db.set_percussion_current_day(g["id"], day)
        self._render()

    def _step_day(self, delta):
        cycle = self._cycle_length()
        day = ((self._day() - 1 + delta) % cycle) + 1
        self._day_var.set(str(day))
        self._on_day_edited()

    # ─────────────────────────────────────────────────────────── group CRUD ───

    def _add_group(self):
        dlg = _GroupDialog(self.winfo_toplevel(), self.db, self._school_year())
        self.wait_window(dlg)
        if dlg.saved_id:
            self._selected_group_id = dlg.saved_id
        self.refresh()

    def _edit_group(self):
        g = self._current_group()
        if not g:
            return
        dlg = _GroupDialog(self.winfo_toplevel(), self.db, self._school_year(), group=g)
        self.wait_window(dlg)
        self.refresh()

    def _delete_group(self):
        g = self._current_group()
        if not g:
            Messagebox.show_warning("Select a section first.", title="No Selection", parent=self)
            return
        if Messagebox.yesno(f"Delete “{g['name']}” and its roster?",
                            title="Confirm Delete", parent=self) == "Yes":
            self.db.delete_percussion_group(g["id"])
            self._selected_group_id = None
            self.refresh()

    # ────────────────────────────────────────────────────────── roster CRUD ───

    def _add_players(self):
        g = self._current_group()
        if not g:
            Messagebox.show_warning("Select or create a section first.",
                                    title="No Section", parent=self)
            return
        dlg = _AddPlayersDialog(self.winfo_toplevel(), g["class_type"] == pr.ENTRY)
        self.wait_window(dlg)
        if not dlg.names:
            return
        is_entry = g["class_type"] == pr.ENTRY
        # For Entry, new players default to mallets-only (earning) unless the
        # teacher chose "start in full rotation".
        full = 0 if (is_entry and not dlg.start_full) else 1
        for name in dlg.names:
            self.db.add_percussion_student(g["id"], name, full_rotation=full)
        self._render()
        self.refresh()

    def _selected_player_id(self):
        sel = self._roster.selection()
        return int(sel[0]) if sel else None

    def _remove_player(self):
        pid = self._selected_player_id()
        if pid is None:
            Messagebox.show_warning("Select a player first.", title="No Selection", parent=self)
            return
        vals = self._roster.item(str(pid), "values")
        name = vals[0] if vals else "this player"
        if Messagebox.yesno(f"Remove {name} from the rotation?",
                            title="Remove Player", parent=self) == "Yes":
            self.db.delete_percussion_student(pid)
            self._render()
            self.refresh()

    def _move_player(self, delta):
        pid = self._selected_player_id()
        if pid is None:
            return
        g = self._current_group()
        rows = list(self.db.get_percussion_students(g["id"]))
        ids = [r["id"] for r in rows]
        if pid not in ids:
            return
        i = ids.index(pid)
        j = i + delta
        if j < 0 or j >= len(ids):
            return
        ids[i], ids[j] = ids[j], ids[i]
        self.db.reorder_percussion_students(ids)
        self._render()
        self._roster.selection_set(str(pid))

    def _on_roster_click(self, event):
        # Toggle full-rotation when clicking the Rotation column (Entry only).
        g = self._current_group()
        if not g or g["class_type"] != pr.ENTRY:
            return
        region = self._roster.identify("region", event.x, event.y)
        col = self._roster.identify_column(event.x)
        row = self._roster.identify_row(event.y)
        if region == "cell" and col == "#2" and row:
            r = self._student_row(int(row))
            if r:
                self.db.update_percussion_student(
                    int(row), {"full_rotation": 0 if r["full_rotation"] else 1})
                self._render()
                self._roster.selection_set(row)

    def _on_roster_double(self, event):
        row = self._roster.identify_row(event.y)
        if not row:
            return
        r = self._student_row(int(row))
        if not r:
            return
        new = _prompt_text(self, "Rename Player", "Name:", r["name"])
        if new:
            self.db.update_percussion_student(int(row), {"name": new.strip()})
            self._render()

    def _student_row(self, pid):
        g = self._current_group()
        for r in self.db.get_percussion_students(g["id"]):
            if r["id"] == pid:
                return r
        return None

    # ───────────────────────────────────────────────────────── special day ────

    def _special_day(self):
        g = self._current_group()
        if not g:
            return
        day = self._day()
        existing = self.db.get_percussion_override(g["id"], day)
        dlg = _SpecialDayDialog(self.winfo_toplevel(), day, existing)
        self.wait_window(dlg)
        if dlg.result is None:
            return
        mode, note = dlg.result
        if mode == pr.MODE_NORMAL:
            self.db.clear_percussion_override(g["id"], day)
        else:
            self.db.set_percussion_override(g["id"], day, mode, note)
        self._render()

    # ─────────────────────────────────────────────────────────── copy/grid ────

    def _today_text(self):
        g = self._current_group()
        if not g:
            return ""
        lines = [f"{g['name']} — Rotation Day {self._day()}"]
        for iid in self._board.get_children():
            name, station = self._board.item(iid, "values")
            lines.append(f"{name}: {station}")
        return "\n".join(lines)

    def _color_for(self, station):
        return _color_for_station(station)

    def _icon_path(self):
        """The teacher's own rotation icon, if they dropped one in assets/."""
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for name in ("rotation_icon.png", "percussion_icon.png"):
            p = os.path.join(root, "assets", name)
            if os.path.exists(p):
                return p
        return None

    def _copy_today(self):
        g = self._current_group()
        if not g:
            return
        rows = [tuple(self._board.item(iid, "values")) for iid in self._board.get_children()]
        if not rows:
            Messagebox.show_info("Add players first.", title="No Players", parent=self)
            return
        ok = False
        try:
            import percussion_board_image as pbi
            # Section name is intentionally omitted from the copied image.
            ok = pbi.copy_board(self._day(), rows, self._color_for,
                                section_name="", icon_path=self._icon_path())
        except Exception:
            ok = False
        if ok:
            Messagebox.show_info(
                "Copied as an image — paste it into PowerPoint, Word, or OneNote.",
                title="Copied", parent=self)
        else:
            # Fall back to plain text if image copy is unavailable.
            self.clipboard_clear()
            self.clipboard_append(self._today_text())
            Messagebox.show_info("Copied as text.", title="Copied", parent=self)

    def _show_full_grid(self):
        g = self._current_group()
        if not g:
            return
        payload, _ = self._students_payload(g)
        if not payload:
            Messagebox.show_info("Add players first.", title="No Players", parent=self)
            return
        _FullGridDialog(self.winfo_toplevel(), g, payload, 1,
                        inventory=self._inventory())


# ══════════════════════════════════════════════════════════════ dialogs ══════

class _MalletEquipmentDialog(ttk.Toplevel):
    """What mallet equipment the room actually has, and how many students
    can play each at a time.  Saved once per school year and used by every
    section's rotation."""

    def __init__(self, parent, db, initial=None):
        super().__init__(parent)
        self.db = db
        self._initial = initial
        self.saved = False
        self.title("Mallet Equipment")
        self.resizable(False, False)
        self.grab_set()
        self.lift()

        hdr = ttk.Frame(self, bootstyle=INFO)
        hdr.pack(fill=X)
        ttk.Label(hdr, text="🎵  Mallet Equipment in Your Room",
                  font=("Segoe UI", 12, "bold"),
                  bootstyle=(INVERSE, INFO)).pack(pady=10, padx=16, anchor=W)

        body = ttk.Frame(self)
        body.pack(fill=BOTH, expand=True, padx=16, pady=10)
        ttk.Label(body, text="One row per kind of equipment, with how many "
                             "students can use it at once:",
                  font=("Segoe UI", 9), wraplength=410,
                  justify=LEFT).pack(anchor=W)
        for bullet in [
                "A 4 1/3-octave marimba fits 3 players; a 5-octave fits 4.",
                "Bell sets fit ONE student each — enter how many sets you "
                "have (3 sets = 3).",
                "Add anything you pull out for a big section (e.g. a mini "
                "practice xylophone, 1).",
                "Rotations never exceed these numbers; extra players rotate "
                "to a practice pad."]:
            ttk.Label(body, text="  •  " + bullet, font=("Segoe UI", 8),
                      foreground=muted_fg(), wraplength=400,
                      justify=LEFT).pack(anchor=W)
        ttk.Label(body, text="This list stays with you from year to year "
                             "(new school years inherit it automatically) "
                             "and each year stays editable, so update it "
                             "only when the room actually changes.",
                  font=("Segoe UI", 8), foreground=muted_fg(),
                  wraplength=400, justify=LEFT).pack(anchor=W, pady=(8, 8))

        cols = ttk.Frame(body)
        cols.pack(fill=X)
        ttk.Label(cols, text="Equipment", font=("Segoe UI", 9, "bold"),
                  width=30).pack(side=LEFT)
        ttk.Label(cols, text="Students at a time",
                  font=("Segoe UI", 9, "bold")).pack(side=LEFT)
        self._rows_frame = ttk.Frame(body)
        self._rows_frame.pack(fill=X)
        self._rows = []

        brow = ttk.Frame(body)
        brow.pack(fill=X, pady=(6, 0))
        ttk.Button(brow, text="➕ Add Equipment", bootstyle=(SUCCESS, OUTLINE),
                   command=lambda: self._add_row("", 1)).pack(side=LEFT)
        ttk.Button(brow, text="↺ Reset to Defaults",
                   bootstyle=(SECONDARY, OUTLINE),
                   command=self._reset).pack(side=LEFT, padx=6)

        btn = ttk.Frame(self)
        btn.pack(fill=X, padx=16, pady=12)
        ttk.Button(btn, text="Cancel", bootstyle=(SECONDARY, OUTLINE),
                   command=self.destroy).pack(side=RIGHT, padx=4)
        ttk.Button(btn, text="Save", bootstyle=SUCCESS,
                   command=self._save).pack(side=RIGHT, padx=4)

        start = self._initial if self._initial is not None else self._load()
        for name, cap in pr._norm_inventory(start):
            self._add_row(name, cap)
        from ui.theme import fit_window
        fit_window(self, 460, 560)

    def _load(self):
        import json
        raw = self.db.get_program_setting("mallet_inventory")
        if raw:
            try:
                return json.loads(raw)
            except Exception:
                pass
        return None

    def _add_row(self, name, cap):
        row = ttk.Frame(self._rows_frame)
        row.pack(fill=X, pady=2)
        nv = tk.StringVar(value=name)
        cv = tk.StringVar(value=str(cap))
        ttk.Entry(row, textvariable=nv, width=30).pack(side=LEFT)
        ttk.Spinbox(row, from_=1, to=8, width=4,
                    textvariable=cv).pack(side=LEFT, padx=(8, 0))
        entry = (row, nv, cv)

        def remove():
            row.destroy()
            self._rows.remove(entry)
        ttk.Button(row, text="✕", width=3, bootstyle=(DANGER, OUTLINE, LINK),
                   command=remove).pack(side=LEFT, padx=(8, 0))
        self._rows.append(entry)

    def _reset(self):
        for row, _n, _c in self._rows:
            row.destroy()
        self._rows = []
        for name, cap in pr._norm_inventory(None):
            self._add_row(name, cap)

    def _save(self):
        import json
        items = []
        for _row, nv, cv in self._rows:
            name = nv.get().strip()
            try:
                cap = max(1, int(cv.get()))
            except (TypeError, ValueError):
                cap = 1
            if name:
                items.append({"name": name, "capacity": cap})
        if not items:
            Messagebox.show_warning("Keep at least one piece of equipment "
                                    "(or Reset to Defaults).",
                                    title="Nothing Listed", parent=self)
            return
        self.db.set_program_setting("mallet_inventory", json.dumps(items))
        self.saved = True
        self.destroy()


class _GroupDialog(ttk.Toplevel):
    def __init__(self, parent, db, school_year, group=None):
        super().__init__(parent)
        self.db = db
        self.school_year = school_year
        self.group = group
        self.saved_id = None
        self.title("Edit Section" if group else "New Percussion Section")
        self.resizable(False, False)
        self.grab_set()
        self.lift()
        self._build()
        from ui.theme import fit_window
        fit_window(self, 420, 340)

    def _build(self):
        hdr = ttk.Frame(self, bootstyle=PRIMARY)
        hdr.pack(fill=X)
        ttk.Label(hdr, text="🥁  Percussion Section", font=("Segoe UI", 13, "bold"),
                  bootstyle=(INVERSE, PRIMARY)).pack(pady=12, padx=16, anchor=W)

        body = ttk.Frame(self)
        body.pack(fill=BOTH, expand=True, padx=16, pady=10)

        ttk.Label(body, text="Section name (e.g. “Period 1 – Entry Band”) *",
                  font=("Segoe UI", 9, "bold")).pack(anchor=W)
        self._name = tk.StringVar(value=(self.group["name"] if self.group else ""))
        ttk.Entry(body, textvariable=self._name, width=40).pack(fill=X, pady=(2, 8))

        ttk.Label(body, text="Class type *", font=("Segoe UI", 9, "bold")).pack(anchor=W)
        self._type = tk.StringVar(
            value=CLASS_TYPE_LABELS.get(self.group["class_type"] if self.group else pr.ENTRY,
                                        CLASS_TYPE_LABELS[pr.ENTRY]))
        ttk.Combobox(body, textvariable=self._type, state="readonly",
                     values=list(CLASS_TYPE_LABELS.values()), width=30).pack(anchor=W, pady=(2, 4))
        ttk.Label(body,
                  text="Entry: Mallets / SD / Timp-aux / BD-SD, players earn their rotation.\n"
                       "Intermediate / Advanced: adds a Drum set seat.",
                  font=("Segoe UI", 8), foreground=muted_fg(), justify=LEFT).pack(anchor=W, pady=(0, 8))

        ttk.Label(body, text="Period (optional)", font=("Segoe UI", 9, "bold")).pack(anchor=W)
        self._period = tk.StringVar(value=(self.group["period"] if self.group else ""))
        ttk.Entry(body, textvariable=self._period, width=12).pack(anchor=W, pady=(2, 8))

        self._sub = tk.BooleanVar(
            value=bool(self.group["mallet_subrotation"]) if self.group else True)
        ttk.Checkbutton(body, text="Assign specific mallet instruments each day",
                        variable=self._sub, bootstyle=INFO).pack(anchor=W)
        ttk.Label(body,
                  text="Respects what the room actually has — set it with the "
                       "“🎵 Mallet Equipment…” button (e.g. 1 marimba ×3 "
                       "players, 1 vibraphone ×2, 1 xylophone ×2, 3 bell "
                       "sets ×1). Extra mallet players rotate to a practice pad.",
                  font=("Segoe UI", 8), foreground=muted_fg(), justify=LEFT,
                  wraplength=360).pack(anchor=W)

        btn = ttk.Frame(self)
        btn.pack(fill=X, padx=16, pady=12)
        ttk.Button(btn, text="Cancel", bootstyle=(SECONDARY, OUTLINE),
                   command=self.destroy).pack(side=RIGHT, padx=4)
        ttk.Button(btn, text="Save", bootstyle=SUCCESS, command=self._save).pack(side=RIGHT, padx=4)

    def _save(self):
        name = self._name.get().strip()
        if not name:
            Messagebox.show_warning("Enter a section name.", title="Required", parent=self)
            return
        data = {
            "school_year": self.school_year,
            "name": name,
            "class_type": LABEL_TO_CLASS_TYPE.get(self._type.get(), pr.ENTRY),
            "period": self._period.get().strip(),
            "mallet_subrotation": 1 if self._sub.get() else 0,
        }
        if self.group:
            self.db.update_percussion_group(self.group["id"], data)
            self.saved_id = self.group["id"]
        else:
            data["current_day"] = 1
            self.saved_id = self.db.add_percussion_group(data)
        self.destroy()


class _AddPlayersDialog(ttk.Toplevel):
    def __init__(self, parent, is_entry):
        super().__init__(parent)
        self.names = []
        self.start_full = False
        self.title("Add Players")
        self.resizable(False, False)
        self.grab_set()
        self.lift()

        hdr = ttk.Frame(self, bootstyle=SUCCESS)
        hdr.pack(fill=X)
        ttk.Label(hdr, text="Add Percussionists", font=("Segoe UI", 12, "bold"),
                  bootstyle=(INVERSE, SUCCESS)).pack(pady=10, padx=16, anchor=W)

        body = ttk.Frame(self)
        body.pack(fill=BOTH, expand=True, padx=16, pady=10)
        ttk.Label(body, text="One name per line — paste a whole section at once:",
                  font=("Segoe UI", 9)).pack(anchor=W)
        self._text = tk.Text(body, height=8, width=36, relief="solid", bd=1,
                             font=("Segoe UI", 10))
        self._text.pack(fill=BOTH, expand=True, pady=(4, 6))
        self._text.focus_set()

        self._full = tk.BooleanVar(value=not is_entry)
        if is_entry:
            ttk.Checkbutton(
                body, text="Start these players in the full rotation "
                           "(already passed 5 assessments)",
                variable=self._full, bootstyle=INFO).pack(anchor=W)

        btn = ttk.Frame(self)
        btn.pack(fill=X, padx=16, pady=12)
        ttk.Button(btn, text="Cancel", bootstyle=(SECONDARY, OUTLINE),
                   command=self.destroy).pack(side=RIGHT, padx=4)
        ttk.Button(btn, text="Add", bootstyle=SUCCESS, command=self._save).pack(side=RIGHT, padx=4)

        from ui.theme import fit_window
        fit_window(self, 380, 340)

    def _save(self):
        raw = self._text.get("1.0", "end").strip()
        self.names = [line.strip() for line in raw.splitlines() if line.strip()]
        self.start_full = self._full.get()
        self.destroy()


class _SpecialDayDialog(ttk.Toplevel):
    def __init__(self, parent, day, existing):
        super().__init__(parent)
        self.result = None
        self.title(f"Special Day — Rotation Day {day}")
        self.resizable(False, False)
        self.grab_set()
        self.lift()

        hdr = ttk.Frame(self, bootstyle=WARNING)
        hdr.pack(fill=X)
        ttk.Label(hdr, text=f"⭐ Rotation Day {day}", font=("Segoe UI", 12, "bold"),
                  bootstyle=(INVERSE, WARNING)).pack(pady=10, padx=16, anchor=W)

        body = ttk.Frame(self)
        body.pack(fill=BOTH, expand=True, padx=16, pady=10)
        ttk.Label(body, text="Override just this day's rotation:",
                  font=("Segoe UI", 9)).pack(anchor=W, pady=(0, 6))
        self._mode = tk.StringVar(value=existing["mode"] if existing else pr.MODE_NORMAL)
        for val, text in [
            (pr.MODE_NORMAL, "Normal rotation"),
            (pr.MODE_ALL_MALLETS, "Everyone on Mallets"),
            (pr.MODE_ALL_SNARE, "Everyone on Snare / Practice Pad"),
        ]:
            ttk.Radiobutton(body, text=text, variable=self._mode, value=val).pack(anchor=W, pady=1)

        ttk.Label(body, text="Note (optional):", font=("Segoe UI", 9)).pack(anchor=W, pady=(8, 0))
        self._note = tk.StringVar(value=existing["note"] if existing and existing["note"] else "")
        ttk.Entry(body, textvariable=self._note, width=34).pack(anchor=W, pady=(2, 0))

        btn = ttk.Frame(self)
        btn.pack(fill=X, padx=16, pady=12)
        ttk.Button(btn, text="Cancel", bootstyle=(SECONDARY, OUTLINE),
                   command=self.destroy).pack(side=RIGHT, padx=4)
        ttk.Button(btn, text="Apply", bootstyle=WARNING,
                   command=self._save).pack(side=RIGHT, padx=4)

        from ui.theme import fit_window
        fit_window(self, 360, 300)

    def _save(self):
        self.result = (self._mode.get(), self._note.get().strip())
        self.destroy()


class _FullGridDialog(ttk.Toplevel):
    def __init__(self, parent, group, payload, start_day, inventory=None):
        super().__init__(parent)
        self.title(f"Full Rotation Grid — {group['name']}")
        self.grab_set()
        self.lift()

        day_numbers, rows = pr.full_grid(
            payload, group["class_type"],
            mallet_subrotation=bool(group["mallet_subrotation"]),
            start_day=start_day, inventory=inventory)

        hdr = ttk.Frame(self, bootstyle=PRIMARY)
        hdr.pack(fill=X)
        ttk.Label(hdr, text=f"🗓  {group['name']} — one full cycle",
                  font=("Segoe UI", 12, "bold"), bootstyle=(INVERSE, PRIMARY)).pack(
            pady=10, padx=16, anchor=W)

        wrap = ttk.Frame(self)
        wrap.pack(fill=BOTH, expand=True, padx=8, pady=8)
        cols = ["Player"] + [f"Day {d}" for d in day_numbers]
        xsb = ttk.Scrollbar(wrap, orient=HORIZONTAL)
        tree = ttk.Treeview(wrap, columns=cols, show="headings", bootstyle=INFO,
                            xscrollcommand=xsb.set, selectmode="none")
        xsb.config(command=tree.xview)
        for c in cols:
            tree.heading(c, text=c, anchor=W)
            tree.column(c, width=(120 if c == "Player" else 84), anchor=W, stretch=False)
        _configure_station_tags(tree)
        for name, seq in rows:
            tree.insert("", "end", values=[name] + seq)
        xsb.pack(side=BOTTOM, fill=X)
        tree.pack(fill=BOTH, expand=True)

        btn = ttk.Frame(self)
        btn.pack(fill=X, padx=16, pady=10)
        ttk.Button(btn, text="Close", bootstyle=(SECONDARY, OUTLINE),
                   command=self.destroy).pack(side=RIGHT, padx=4)

        def _copy():
            lines = ["\t".join(cols)]
            for name, seq in rows:
                lines.append("\t".join([name] + seq))
            self.clipboard_clear()
            self.clipboard_append("\n".join(lines))
            Messagebox.show_info("Grid copied (tab-separated — paste into Excel/Word).",
                                 title="Copied", parent=self)
        ttk.Button(btn, text="📋 Copy Grid", bootstyle=INFO, command=_copy).pack(side=RIGHT, padx=4)

        from ui.theme import fit_window
        fit_window(self, 900, 460)


def _prompt_text(parent, title, label, initial=""):
    """Tiny modal single-line text prompt returning the string or None."""
    dlg = ttk.Toplevel(parent)
    dlg.title(title)
    dlg.resizable(False, False)
    dlg.grab_set()
    dlg.lift()
    result = {"value": None}
    ttk.Label(dlg, text=label, font=("Segoe UI", 9)).pack(anchor=W, padx=16, pady=(14, 2))
    var = tk.StringVar(value=initial)
    ent = ttk.Entry(dlg, textvariable=var, width=32)
    ent.pack(padx=16, pady=(0, 8))
    ent.focus_set()
    ent.select_range(0, END)

    def ok():
        result["value"] = var.get()
        dlg.destroy()
    ent.bind("<Return>", lambda e: ok())
    btn = ttk.Frame(dlg)
    btn.pack(fill=X, padx=16, pady=(0, 12))
    ttk.Button(btn, text="Cancel", bootstyle=(SECONDARY, OUTLINE),
               command=dlg.destroy).pack(side=RIGHT, padx=4)
    ttk.Button(btn, text="OK", bootstyle=SUCCESS, command=ok).pack(side=RIGHT, padx=4)
    from ui.theme import fit_window
    fit_window(dlg, 320, 150)
    parent.wait_window(dlg)
    return result["value"]
