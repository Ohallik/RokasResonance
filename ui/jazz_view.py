"""
ui/jazz_view.py - Jazz rhythm-section planner.

A jazz ensemble's rhythm section is variable, so this tool lets the teacher:

  * list the SEATS in play (Drum set, Vibraphone, Piano, Electric piano, Bass,
    Guitar, plus any custom part like a doubled Tenor Sax),
  * enter each PLAYER and tick the seats they can actually cover (a kid who can
    play drum set OR vibes, one who can only play vibes, etc.),
  * see a warm-up ROTATION that cycles eligible players through the open seats
    day by day, and
  * save each SONG's locked personnel once it's auditioned (Drummer: Murys,
    Piano: Emma), so she never re-enters it — those seats stop rotating and the
    daily agenda pulls them in automatically.

Rotation math lives in ``jazz_rotation.py``; this module is UI + storage.  It's
scoped to the school year via the per-year lesson-plan DB, like Percussion.
"""

import os
import json
import tkinter as tk
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from ttkbootstrap.dialogs import Messagebox

import jazz_rotation as jr
from ui.theme import muted_fg, fs

# Per-seat board colour, keyed loosely by instrument family so the projected
# board reads at a glance (drums warm, keys blue, low end green, mallets amber).
SEAT_COLORS = {
    "drum set": "#f6d9d9", "drums": "#f6d9d9", "aux percussion": "#f3e0cf",
    "piano": "#d6e4f5", "electric piano": "#d9e8f0", "keys": "#d6e4f5",
    "bass": "#d9ecd2", "guitar": "#e6dbf1",
    "vibraphone": "#ffe9c7", "vibes": "#ffe9c7",
}
_DEFAULT_SEAT_COLOR = "#eef1f4"


def seat_color(seat):
    return SEAT_COLORS.get((seat or "").strip().lower(), _DEFAULT_SEAT_COLOR)


def _dumps(val):
    return json.dumps(val)


def _loads(raw, default):
    if not raw:
        return default
    try:
        v = json.loads(raw)
        return v
    except Exception:
        return default


class JazzView(ttk.Frame):
    def __init__(self, parent, db):
        super().__init__(parent)
        self.db = db
        self._selected_id = None
        self._build()
        self.refresh()

    # ─────────────────────────────────────────────────────────────── build ────

    def _build(self):
        toolbar = ttk.Frame(self, bootstyle=LIGHT)
        toolbar.pack(fill=X)
        ttk.Button(toolbar, text="➕ New Jazz Band", bootstyle=SUCCESS,
                   command=self._add_ensemble).pack(side=LEFT, padx=6, pady=6)
        ttk.Button(toolbar, text="✏️ Rename", bootstyle=PRIMARY,
                   command=self._rename_ensemble).pack(side=LEFT, padx=2, pady=6)
        ttk.Button(toolbar, text="🗑️ Delete", bootstyle=DANGER,
                   command=self._delete_ensemble).pack(side=LEFT, padx=2, pady=6)
        ttk.Button(toolbar, text="🔄 Refresh", bootstyle=(SECONDARY, OUTLINE),
                   command=self.refresh).pack(side=LEFT, padx=6, pady=6)
        ttk.Label(toolbar,
                  text="Set up each jazz band's rhythm section → warm-up rotation + per-song lineups",
                  font=("Segoe UI", fs(9)), foreground=muted_fg()).pack(side=LEFT, padx=10)

        paned = ttk.Panedwindow(self, orient=HORIZONTAL)
        paned.pack(fill=BOTH, expand=True, padx=6, pady=6)

        left = ttk.Frame(paned)
        paned.add(left, weight=1)
        ttk.Label(left, text="Jazz Bands", font=("Segoe UI", fs(10), "bold")).pack(
            anchor=W, pady=(2, 4))
        cols = ("Band", "Players", "Songs")
        self._tree = ttk.Treeview(left, columns=cols, show="headings",
                                  selectmode="browse", bootstyle=PRIMARY, height=8)
        for c, w in zip(cols, (150, 60, 60)):
            self._tree.heading(c, text=c, anchor=W)
            self._tree.column(c, width=w, anchor=W, stretch=(c == "Band"))
        self._tree.pack(fill=BOTH, expand=True)
        self._tree.bind("<<TreeviewSelect>>", lambda e: self._on_selected())
        self._tree.bind("<Double-1>", lambda e: self._rename_ensemble())

        right = ttk.Frame(paned)
        paned.add(right, weight=3)
        self._build_right(right)

    def _build_right(self, parent):
        self._placeholder = ttk.Frame(parent)
        ttk.Label(self._placeholder, text="🎷", font=("Segoe UI", fs(36))).pack(pady=(40, 8))
        ttk.Label(self._placeholder,
                  text="Select a jazz band, or click “New Jazz Band” to start.",
                  font=("Segoe UI", fs(11)), foreground=muted_fg()).pack()
        self._placeholder.pack(fill=BOTH, expand=True)

        self._content = ttk.Frame(parent)

        self._name_lbl = ttk.Label(self._content, text="",
                                    font=("Segoe UI", fs(13), "bold"), bootstyle=PRIMARY)
        self._name_lbl.pack(anchor=W)

        # ── Seats in play ──
        seats_box = ttk.Labelframe(self._content, text=" Seats in play ", padding=6)
        seats_box.pack(fill=X, pady=(6, 4))
        self._seats_wrap = ttk.Frame(seats_box)
        self._seats_wrap.pack(fill=X)
        addbar = ttk.Frame(seats_box)
        addbar.pack(fill=X, pady=(4, 0))
        ttk.Button(addbar, text="➕ Add / edit seats…", bootstyle=(INFO, OUTLINE),
                   command=self._edit_seats).pack(side=LEFT)
        ttk.Label(addbar, text="The rhythm-section parts you're rotating today.",
                  font=("Segoe UI", fs(8)), foreground=muted_fg()).pack(side=LEFT, padx=8)

        # ── Rotation / lineup board ──
        board_box = ttk.Labelframe(self._content, text=" Lineup ", padding=6)
        board_box.pack(fill=BOTH, expand=True, pady=4)

        pick = ttk.Frame(board_box)
        pick.pack(fill=X, pady=(0, 4))
        ttk.Label(pick, text="Show:", font=("Segoe UI", fs(9), "bold")).pack(side=LEFT)
        self._view_var = tk.StringVar(value="Warm-up rotation")
        self._view_combo = ttk.Combobox(pick, textvariable=self._view_var,
                                        state="readonly", width=28, values=[])
        self._view_combo.pack(side=LEFT, padx=(4, 10))
        self._view_combo.bind("<<ComboboxSelected>>", lambda e: self._render_board())

        self._day_bar = ttk.Frame(pick)
        self._day_bar.pack(side=LEFT)
        ttk.Label(self._day_bar, text="Day:", font=("Segoe UI", fs(9))).pack(side=LEFT)
        ttk.Button(self._day_bar, text="◀", width=3, bootstyle=(SECONDARY, OUTLINE),
                   command=lambda: self._step_day(-1)).pack(side=LEFT, padx=(4, 2))
        self._day_var = tk.StringVar(value="1")
        self._day_spin = ttk.Spinbox(self._day_bar, from_=1, to=999, width=4,
                                     textvariable=self._day_var, command=self._on_day_edited)
        self._day_spin.pack(side=LEFT)
        self._day_spin.bind("<Return>", lambda e: self._on_day_edited())
        ttk.Button(self._day_bar, text="Next ▶", bootstyle=SUCCESS,
                   command=lambda: self._step_day(1)).pack(side=LEFT, padx=(2, 6))
        self._cycle_lbl = ttk.Label(self._day_bar, text="", font=("Segoe UI", fs(9)),
                                    foreground=muted_fg())
        self._cycle_lbl.pack(side=LEFT)

        ttk.Button(pick, text="📋 Copy", bootstyle=(INFO, OUTLINE),
                   command=self._copy_board).pack(side=RIGHT, padx=2)

        bcols = ("Seat", "Player")
        self._board = ttk.Treeview(board_box, columns=bcols, show="headings",
                                   selectmode="none", bootstyle=INFO, height=6)
        self._board.heading("Seat", text="Seat", anchor=W)
        self._board.heading("Player", text="Player", anchor=W)
        self._board.column("Seat", width=170, anchor=W, stretch=True)
        self._board.column("Player", width=200, anchor=W, stretch=True)
        self._board.pack(fill=BOTH, expand=True)
        self._bench_lbl = ttk.Label(board_box, text="", font=("Segoe UI", fs(9)),
                                    foreground=muted_fg())
        self._bench_lbl.pack(anchor=W, pady=(2, 0))

        # ── Roster ──
        roster_box = ttk.Labelframe(self._content, text=" Players ", padding=6)
        roster_box.pack(fill=BOTH, expand=True, pady=4)
        rbar = ttk.Frame(roster_box)
        rbar.pack(fill=X, pady=(0, 4))
        ttk.Button(rbar, text="➕ Add Players", bootstyle=SUCCESS,
                   command=self._add_players).pack(side=LEFT, padx=2)
        ttk.Button(rbar, text="🎛 Edit Instruments", bootstyle=(PRIMARY, OUTLINE),
                   command=self._edit_player_parts).pack(side=LEFT, padx=2)
        ttk.Button(rbar, text="🗑 Remove", bootstyle=(DANGER, OUTLINE),
                   command=self._remove_player).pack(side=LEFT, padx=2)
        ttk.Button(rbar, text="▲", width=3, bootstyle=(SECONDARY, OUTLINE),
                   command=lambda: self._move_player(-1)).pack(side=LEFT, padx=(8, 1))
        ttk.Button(rbar, text="▼", width=3, bootstyle=(SECONDARY, OUTLINE),
                   command=lambda: self._move_player(1)).pack(side=LEFT, padx=1)
        ttk.Label(rbar, text="Double-click a player to choose the instruments they can cover.",
                  font=("Segoe UI", fs(8)), foreground=muted_fg()).pack(side=LEFT, padx=10)

        rcols = ("Player", "Can play")
        self._roster = ttk.Treeview(roster_box, columns=rcols, show="headings",
                                    selectmode="browse", bootstyle=SECONDARY, height=6)
        self._roster.heading("Player", text="Player", anchor=W)
        self._roster.heading("Can play", text="Can play", anchor=W)
        self._roster.column("Player", width=150, anchor=W, stretch=False)
        self._roster.column("Can play", width=330, anchor=W, stretch=True)
        self._roster.pack(fill=BOTH, expand=True)
        self._roster.bind("<Double-1>", lambda e: self._edit_player_parts())

        # ── Songs ──
        songs_box = ttk.Labelframe(self._content, text=" Songs — locked personnel ", padding=6)
        songs_box.pack(fill=BOTH, expand=True, pady=(4, 2))
        sbar = ttk.Frame(songs_box)
        sbar.pack(fill=X, pady=(0, 4))
        ttk.Button(sbar, text="➕ Add Song", bootstyle=SUCCESS,
                   command=self._add_song).pack(side=LEFT, padx=2)
        ttk.Button(sbar, text="🎼 Edit Lineup", bootstyle=(PRIMARY, OUTLINE),
                   command=self._edit_song).pack(side=LEFT, padx=2)
        ttk.Button(sbar, text="🗑 Remove", bootstyle=(DANGER, OUTLINE),
                   command=self._remove_song).pack(side=LEFT, padx=2)
        ttk.Label(sbar, text="Once auditioned, lock a tune's players here — the agenda pulls them in.",
                  font=("Segoe UI", fs(8)), foreground=muted_fg()).pack(side=LEFT, padx=10)

        scols = ("Song", "Locked lineup")
        self._songs = ttk.Treeview(songs_box, columns=scols, show="headings",
                                   selectmode="browse", bootstyle=SECONDARY, height=5)
        self._songs.heading("Song", text="Song", anchor=W)
        self._songs.heading("Locked lineup", text="Locked lineup", anchor=W)
        self._songs.column("Song", width=150, anchor=W, stretch=False)
        self._songs.column("Locked lineup", width=330, anchor=W, stretch=True)
        self._songs.pack(fill=BOTH, expand=True)
        self._songs.bind("<Double-1>", lambda e: self._edit_song())

    # ─────────────────────────────────────────────────────────── data load ────

    def refresh(self):
        prev = self._selected_id
        self._tree.delete(*self._tree.get_children())
        ensembles = self.db.get_jazz_ensembles(self._year())
        for e in ensembles:
            self._tree.insert("", "end", iid=str(e["id"]),
                              values=(e["name"],
                                      len(self.db.get_jazz_players(e["id"])),
                                      len(self.db.get_jazz_songs(e["id"]))))
        ids = [e["id"] for e in ensembles]
        if prev in ids:
            self._tree.selection_set(str(prev))
        elif ids:
            self._tree.selection_set(str(ids[0]))
        else:
            self._selected_id = None
            self._show_placeholder(True)

    def _year(self):
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

    def _on_selected(self):
        sel = self._tree.selection()
        if not sel:
            return
        self._selected_id = int(sel[0])
        e = self.db.get_jazz_ensemble(self._selected_id)
        if not e:
            return
        self._show_placeholder(False)
        self._day_var.set(str(e["current_day"] or 1))
        self._render()

    def _ensemble(self):
        if self._selected_id is None:
            return None
        return self.db.get_jazz_ensemble(self._selected_id)

    def _seats(self, e=None):
        e = e or self._ensemble()
        return jr._clean_seats(_loads(e["seats"], []) if e else [])

    def _players_payload(self, e=None):
        e = e or self._ensemble()
        if not e:
            return []
        out = []
        for r in self.db.get_jazz_players(e["id"]):
            out.append({"id": r["id"], "name": r["name"],
                        "parts": jr._clean_seats(_loads(r["parts"], []))})
        return out

    # ─────────────────────────────────────────────────────────────── render ───

    def _render(self):
        e = self._ensemble()
        if not e:
            return
        self._name_lbl.config(text=e["name"])
        self._render_seats()
        self._render_view_choices()
        self._render_roster()
        self._render_songs()
        self._render_board()

    def _render_seats(self):
        for w in self._seats_wrap.winfo_children():
            w.destroy()
        seats = self._seats()
        if not seats:
            ttk.Label(self._seats_wrap,
                      text="No seats yet — click “Add / edit seats…”.",
                      font=("Segoe UI", fs(9)), foreground=muted_fg()).pack(anchor=W)
            return
        for s in seats:
            chip = tk.Label(self._seats_wrap, text=" " + s + " ",
                            bg=seat_color(s), fg="#222", relief="solid", bd=1,
                            font=("Segoe UI", fs(9), "bold"), padx=6, pady=2)
            chip.pack(side=LEFT, padx=3, pady=2)

    def _render_view_choices(self):
        choices = ["Warm-up rotation"]
        for s in self.db.get_jazz_songs(self._ensemble()["id"]):
            choices.append(f"🎼 {s['title']}")
        self._view_combo.config(values=choices)
        if self._view_var.get() not in choices:
            self._view_var.set("Warm-up rotation")

    def _current_song(self):
        """The song selected in the 'Show' dropdown, or None for warm-up."""
        val = self._view_var.get()
        if not val.startswith("🎼 "):
            return None
        title = val[2:].strip()
        for s in self.db.get_jazz_songs(self._ensemble()["id"]):
            if s["title"] == title:
                return s
        return None

    def _render_board(self):
        e = self._ensemble()
        if not e:
            return
        seats = self._seats(e)
        players = self._players_payload(e)
        song = self._current_song()
        locked = _loads(song["locked"], {}) if song else {}

        # Day stepper only matters when something rotates (warm-up, or a song
        # with open seats).  A fully-locked song is the same every day.
        cycle = jr.cycle_length(seats, players, locked)
        self._day_spin.config(to=max(cycle, 1))
        self._cycle_lbl.config(text=f"of {cycle}")
        day = self._day()
        if cycle > 1:
            day = ((day - 1) % cycle) + 1
        rotates = cycle > 1
        for child in self._day_bar.winfo_children():
            try:
                child.configure(state=("normal" if rotates else "disabled"))
            except tk.TclError:
                pass

        assignments, bench = jr.day_assignments(seats, players, day, locked)
        self._board.delete(*self._board.get_children())
        _configure_seat_tags(self._board, seats)
        for seat, name in assignments:
            is_locked = seat in locked and locked[seat]
            shown = name or "—"
            if is_locked and name:
                shown = f"🔒 {name}"
            self._board.insert("", "end", values=(seat, shown),
                               tags=(_seat_tag(seat),))
        if bench:
            self._bench_lbl.config(text="Waiting / rotating out:  " + ", ".join(bench))
        else:
            self._bench_lbl.config(text="")

    def _render_roster(self):
        self._roster.delete(*self._roster.get_children())
        for p in self._players_payload():
            parts = ", ".join(p["parts"]) if p["parts"] else "— (no instruments set)"
            self._roster.insert("", "end", iid=str(p["id"]), values=(p["name"], parts))

    def _render_songs(self):
        self._songs.delete(*self._songs.get_children())
        for s in self.db.get_jazz_songs(self._ensemble()["id"]):
            locked = _loads(s["locked"], {})
            summary = ",  ".join(f"{seat}: {who}" for seat, who in locked.items() if who)
            self._songs.insert("", "end", iid=str(s["id"]),
                               values=(s["title"], summary or "(all rotating)"))

    # ─────────────────────────────────────────────────────────── day controls ─

    def _day(self):
        try:
            return max(1, int(self._day_var.get()))
        except (ValueError, TypeError):
            return 1

    def _on_day_edited(self):
        e = self._ensemble()
        if not e:
            return
        self.db.set_jazz_current_day(e["id"], self._day())
        self._render_board()

    def _step_day(self, delta):
        self._day_var.set(str(max(1, self._day() + delta)))
        self._on_day_edited()

    # ─────────────────────────────────────────────────────── ensemble CRUD ────

    def _add_ensemble(self):
        name = _prompt_text(self, "New Jazz Band", "Name (e.g. “Jazz 1”):", "")
        if not name or not name.strip():
            return
        eid = self.db.add_jazz_ensemble({
            "school_year": self._year(), "name": name.strip(),
            "seats": _dumps(list(jr.DEFAULT_SEATS)), "current_day": 1})
        self._selected_id = eid
        self.refresh()

    def _rename_ensemble(self):
        e = self._ensemble()
        if not e:
            return
        name = _prompt_text(self, "Rename Jazz Band", "Name:", e["name"])
        if name and name.strip():
            self.db.update_jazz_ensemble(e["id"], {"name": name.strip()})
            self.refresh()

    def _delete_ensemble(self):
        e = self._ensemble()
        if not e:
            Messagebox.show_warning("Select a jazz band first.", title="No Selection", parent=self)
            return
        if Messagebox.yesno(f"Delete “{e['name']}”, its players and songs?",
                            title="Confirm Delete", parent=self) == "Yes":
            self.db.delete_jazz_ensemble(e["id"])
            self._selected_id = None
            self.refresh()

    # ──────────────────────────────────────────────────────────── seats ───────

    def _edit_seats(self):
        e = self._ensemble()
        if not e:
            return
        dlg = _SeatsDialog(self.winfo_toplevel(), self._seats(e))
        self.wait_window(dlg)
        if dlg.saved:
            self.db.update_jazz_ensemble(e["id"], {"seats": _dumps(dlg.seats)})
            self._render()

    # ─────────────────────────────────────────────────────────── roster CRUD ──

    def _add_players(self):
        e = self._ensemble()
        if not e:
            Messagebox.show_warning("Create a jazz band first.", title="No Band", parent=self)
            return
        dlg = _AddPlayersDialog(self.winfo_toplevel())
        self.wait_window(dlg)
        if not dlg.names:
            return
        for name in dlg.names:
            self.db.add_jazz_player(e["id"], name, _dumps([]))
        self.refresh()
        self._render()

    def _selected_player_id(self):
        sel = self._roster.selection()
        return int(sel[0]) if sel else None

    def _edit_player_parts(self):
        e = self._ensemble()
        pid = self._selected_player_id()
        if not e or pid is None:
            Messagebox.show_warning("Select a player first.", title="No Selection", parent=self)
            return
        player = next((p for p in self._players_payload(e) if p["id"] == pid), None)
        if not player:
            return
        dlg = _PlayerPartsDialog(self.winfo_toplevel(), player["name"],
                                 self._seats(e), player["parts"])
        self.wait_window(dlg)
        if dlg.saved:
            self.db.update_jazz_player(pid, {"parts": _dumps(dlg.parts)})
            self._render()
            self._roster.selection_set(str(pid))

    def _remove_player(self):
        pid = self._selected_player_id()
        if pid is None:
            Messagebox.show_warning("Select a player first.", title="No Selection", parent=self)
            return
        vals = self._roster.item(str(pid), "values")
        name = vals[0] if vals else "this player"
        if Messagebox.yesno(f"Remove {name}?", title="Remove Player", parent=self) == "Yes":
            self.db.delete_jazz_player(pid)
            self.refresh()
            self._render()

    def _move_player(self, delta):
        e = self._ensemble()
        pid = self._selected_player_id()
        if not e or pid is None:
            return
        ids = [p["id"] for p in self._players_payload(e)]
        if pid not in ids:
            return
        i = ids.index(pid)
        j = i + delta
        if j < 0 or j >= len(ids):
            return
        ids[i], ids[j] = ids[j], ids[i]
        self.db.reorder_jazz_players(ids)
        self._render()
        self._roster.selection_set(str(pid))

    # ─────────────────────────────────────────────────────────── song CRUD ────

    def _selected_song_id(self):
        sel = self._songs.selection()
        return int(sel[0]) if sel else None

    def _add_song(self):
        e = self._ensemble()
        if not e:
            Messagebox.show_warning("Create a jazz band first.", title="No Band", parent=self)
            return
        title = _prompt_text(self, "Add Song", "Song title:", "")
        if not title or not title.strip():
            return
        sid = self.db.add_jazz_song(e["id"], title.strip(), _dumps({}))
        self.refresh()
        self._render()
        self._songs.selection_set(str(sid))
        self._edit_song()

    def _edit_song(self):
        e = self._ensemble()
        sid = self._selected_song_id()
        if not e or sid is None:
            Messagebox.show_warning("Select a song first.", title="No Selection", parent=self)
            return
        song = self.db.get_jazz_song(sid)
        if not song:
            return
        dlg = _SongLineupDialog(self.winfo_toplevel(), song["title"], self._seats(e),
                                self._players_payload(e), _loads(song["locked"], {}))
        self.wait_window(dlg)
        if dlg.saved:
            self.db.update_jazz_song(sid, {"title": dlg.title, "locked": _dumps(dlg.locked)})
            self.refresh()
            self._render()

    def _remove_song(self):
        sid = self._selected_song_id()
        if sid is None:
            Messagebox.show_warning("Select a song first.", title="No Selection", parent=self)
            return
        vals = self._songs.item(str(sid), "values")
        title = vals[0] if vals else "this song"
        if Messagebox.yesno(f"Remove “{title}”?", title="Remove Song", parent=self) == "Yes":
            self.db.delete_jazz_song(sid)
            self.refresh()
            self._render()

    # ────────────────────────────────────────────────────────────── copy ──────

    def _copy_board(self):
        e = self._ensemble()
        if not e:
            return
        song = self._current_song()
        header = f"{e['name']} — {song['title']}" if song else \
            f"{e['name']} — Warm-up rotation (Day {self._day()})"
        lines = [header]
        for iid in self._board.get_children():
            seat, name = self._board.item(iid, "values")
            lines.append(f"{seat}: {name.replace('🔒 ', '')}")
        self.clipboard_clear()
        self.clipboard_append("\n".join(lines))
        Messagebox.show_info("Copied as text.", title="Copied", parent=self)


# ── shared tag helpers for the board ──

def _seat_tag(seat):
    return "seat_" + seat_color(seat).lstrip("#")


def _configure_seat_tags(tree, seats):
    for s in seats:
        c = seat_color(s)
        tree.tag_configure("seat_" + c.lstrip("#"), background=c)


# ══════════════════════════════════════════════════════════════ dialogs ══════

class _SeatsDialog(ttk.Toplevel):
    """Edit the ordered list of rhythm-section seats in play."""

    def __init__(self, parent, seats):
        super().__init__(parent)
        self.saved = False
        self.seats = list(seats)
        self.title("Seats in Play")
        self.resizable(False, True)
        self.grab_set()
        self.lift()

        hdr = ttk.Frame(self, bootstyle=INFO)
        hdr.pack(fill=X)
        ttk.Label(hdr, text="🎷  Rhythm-section seats",
                  font=("Segoe UI", 12, "bold"),
                  bootstyle=(INVERSE, INFO)).pack(pady=10, padx=16, anchor=W)

        body = ttk.Frame(self)
        body.pack(fill=BOTH, expand=True, padx=16, pady=10)
        ttk.Label(body, text="One seat per line, in board order. Add an "
                             "“Electric piano” to seat a second pianist, or a "
                             "part like “Tenor Sax” for a doubler.",
                  font=("Segoe UI", 9), wraplength=420, justify=LEFT).pack(anchor=W)

        quick = ttk.Frame(body)
        quick.pack(fill=X, pady=(6, 4))
        ttk.Label(quick, text="Quick add:", font=("Segoe UI", 8),
                  foreground=muted_fg()).pack(side=LEFT)
        for s in jr.COMMON_SEATS:
            ttk.Button(quick, text=s, bootstyle=(SECONDARY, OUTLINE, LINK),
                       command=lambda ss=s: self._append(ss)).pack(side=LEFT, padx=1)

        self._text = tk.Text(body, height=8, width=36, relief="solid", bd=1,
                             font=("Segoe UI", 10))
        self._text.pack(fill=BOTH, expand=True, pady=(4, 0))
        self._text.insert("1.0", "\n".join(self.seats))

        btn = ttk.Frame(self)
        btn.pack(fill=X, padx=16, pady=12)
        ttk.Button(btn, text="Cancel", bootstyle=(SECONDARY, OUTLINE),
                   command=self.destroy).pack(side=RIGHT, padx=4)
        ttk.Button(btn, text="Save", bootstyle=SUCCESS,
                   command=self._save).pack(side=RIGHT, padx=4)

        from ui.theme import fit_window
        fit_window(self, 460, 460)

    def _append(self, seat):
        cur = [l.strip() for l in self._text.get("1.0", "end").splitlines() if l.strip()]
        if seat.lower() not in [c.lower() for c in cur]:
            if cur:
                self._text.insert("end", "\n" + seat)
            else:
                self._text.insert("1.0", seat)

    def _save(self):
        raw = [l.strip() for l in self._text.get("1.0", "end").splitlines() if l.strip()]
        self.seats = jr._clean_seats(raw)
        self.saved = True
        self.destroy()


class _AddPlayersDialog(ttk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.names = []
        self.title("Add Players")
        self.resizable(False, False)
        self.grab_set()
        self.lift()

        hdr = ttk.Frame(self, bootstyle=SUCCESS)
        hdr.pack(fill=X)
        ttk.Label(hdr, text="Add Rhythm-Section Players", font=("Segoe UI", 12, "bold"),
                  bootstyle=(INVERSE, SUCCESS)).pack(pady=10, padx=16, anchor=W)

        body = ttk.Frame(self)
        body.pack(fill=BOTH, expand=True, padx=16, pady=10)
        ttk.Label(body, text="One name per line. Set which instruments each can "
                             "play next (double-click them in the list).",
                  font=("Segoe UI", 9), wraplength=340, justify=LEFT).pack(anchor=W)
        self._text = tk.Text(body, height=8, width=34, relief="solid", bd=1,
                             font=("Segoe UI", 10))
        self._text.pack(fill=BOTH, expand=True, pady=(4, 0))
        self._text.focus_set()

        btn = ttk.Frame(self)
        btn.pack(fill=X, padx=16, pady=12)
        ttk.Button(btn, text="Cancel", bootstyle=(SECONDARY, OUTLINE),
                   command=self.destroy).pack(side=RIGHT, padx=4)
        ttk.Button(btn, text="Add", bootstyle=SUCCESS, command=self._save).pack(side=RIGHT, padx=4)

        from ui.theme import fit_window
        fit_window(self, 380, 320)

    def _save(self):
        raw = self._text.get("1.0", "end").strip()
        self.names = [l.strip() for l in raw.splitlines() if l.strip()]
        self.destroy()


class _PlayerPartsDialog(ttk.Toplevel):
    """Tick the seats one player can cover."""

    def __init__(self, parent, name, seats, current):
        super().__init__(parent)
        self.saved = False
        self.parts = list(current)
        self.title(f"Instruments — {name}")
        self.resizable(False, True)
        self.grab_set()
        self.lift()

        hdr = ttk.Frame(self, bootstyle=PRIMARY)
        hdr.pack(fill=X)
        ttk.Label(hdr, text=f"🎛  {name} can play…",
                  font=("Segoe UI", 12, "bold"),
                  bootstyle=(INVERSE, PRIMARY)).pack(pady=10, padx=16, anchor=W)

        body = ttk.Frame(self)
        body.pack(fill=BOTH, expand=True, padx=16, pady=10)
        if not seats:
            ttk.Label(body, text="Add some seats first (Add / edit seats…).",
                      font=("Segoe UI", 9), foreground=muted_fg()).pack(anchor=W)
        else:
            ttk.Label(body, text="Check every instrument this player can cover. "
                                 "In warm-ups they'll rotate through the ones "
                                 "they share with others.",
                      font=("Segoe UI", 9), wraplength=340, justify=LEFT).pack(anchor=W, pady=(0, 6))
        cur = {c.lower() for c in current}
        self._vars = []
        for s in seats:
            var = tk.BooleanVar(value=s.lower() in cur)
            ttk.Checkbutton(body, text=s, variable=var, bootstyle=PRIMARY).pack(anchor=W, pady=1)
            self._vars.append((s, var))

        btn = ttk.Frame(self)
        btn.pack(fill=X, padx=16, pady=12)
        ttk.Button(btn, text="Cancel", bootstyle=(SECONDARY, OUTLINE),
                   command=self.destroy).pack(side=RIGHT, padx=4)
        ttk.Button(btn, text="Save", bootstyle=SUCCESS, command=self._save).pack(side=RIGHT, padx=4)

        from ui.theme import fit_window
        fit_window(self, 360, 420)

    def _save(self):
        self.parts = [s for s, var in self._vars if var.get()]
        self.saved = True
        self.destroy()


class _SongLineupDialog(ttk.Toplevel):
    """Lock each seat of a song to a specific player (or leave it rotating)."""

    ROTATE = "— (rotate)"

    def __init__(self, parent, title, seats, players, current):
        super().__init__(parent)
        self.saved = False
        self.title_text = title
        self.title(f"Lineup — {title}")
        self.locked = dict(current)
        self.resizable(False, True)
        self.grab_set()
        self.lift()

        hdr = ttk.Frame(self, bootstyle=PRIMARY)
        hdr.pack(fill=X)
        ttk.Label(hdr, text=f"🎼  {title}", font=("Segoe UI", 12, "bold"),
                  bootstyle=(INVERSE, PRIMARY)).pack(pady=10, padx=16, anchor=W)

        body = ttk.Frame(self)
        body.pack(fill=BOTH, expand=True, padx=16, pady=10)

        trow = ttk.Frame(body)
        trow.pack(fill=X, pady=(0, 8))
        ttk.Label(trow, text="Song title:", font=("Segoe UI", 9, "bold")).pack(side=LEFT)
        self._title_var = tk.StringVar(value=title)
        ttk.Entry(trow, textvariable=self._title_var, width=28).pack(side=LEFT, padx=(6, 0))

        ttk.Label(body, text="For each seat, pick the locked player or leave it "
                             "rotating. Only players who can cover the seat are "
                             "offered.",
                  font=("Segoe UI", 9), wraplength=420, justify=LEFT).pack(anchor=W, pady=(0, 8))

        grid = ttk.Frame(body)
        grid.pack(fill=X)
        grid.columnconfigure(1, weight=1)
        self._vars = []
        for i, seat in enumerate(seats):
            ttk.Label(grid, text=seat, font=("Segoe UI", 9, "bold")).grid(
                row=i, column=0, sticky=W, pady=3, padx=(0, 10))
            eligible = [p["name"] for p in players if seat in p["parts"]]
            values = [self.ROTATE] + eligible
            var = tk.StringVar(value=current.get(seat) if current.get(seat) in eligible
                               else self.ROTATE)
            ttk.Combobox(grid, textvariable=var, values=values, state="readonly",
                         width=26).grid(row=i, column=1, sticky=W, pady=3)
            self._vars.append((seat, var))
        if not seats:
            ttk.Label(body, text="Add seats first.", foreground=muted_fg()).pack(anchor=W)

        btn = ttk.Frame(self)
        btn.pack(fill=X, padx=16, pady=12)
        ttk.Button(btn, text="Cancel", bootstyle=(SECONDARY, OUTLINE),
                   command=self.destroy).pack(side=RIGHT, padx=4)
        ttk.Button(btn, text="Save", bootstyle=SUCCESS, command=self._save).pack(side=RIGHT, padx=4)

        from ui.theme import fit_window
        fit_window(self, 480, 520)

    def _save(self):
        self.title = (self._title_var.get() or "").strip() or self.title_text
        locked = {}
        for seat, var in self._vars:
            val = var.get()
            if val and val != self.ROTATE:
                locked[seat] = val
        self.locked = locked
        self.saved = True
        self.destroy()


def _prompt_text(parent, title, label, initial=""):
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
    fit_window(dlg, 340, 150)
    parent.wait_window(dlg)
    return result["value"]
