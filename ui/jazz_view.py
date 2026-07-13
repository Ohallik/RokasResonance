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
import jazz_icons
from ui.theme import muted_fg, fs


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


def _who(val):
    """A locked-seat value (a name, or a list of names) as display text."""
    if isinstance(val, list):
        return ", ".join(val)
    return str(val)


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

        # The right panel stacks several sections (seats, lineup, roster, songs),
        # more than fit a short window — so it scrolls, and each section keeps a
        # fixed height instead of fighting over the space (which previously pushed
        # the Songs controls off the bottom).
        self._content_outer = ttk.Frame(parent)
        _cv = tk.Canvas(self._content_outer, highlightthickness=0)
        _sb = ttk.Scrollbar(self._content_outer, orient=VERTICAL, command=_cv.yview)
        _cv.configure(yscrollcommand=_sb.set)
        _sb.pack(side=RIGHT, fill=Y)
        _cv.pack(side=LEFT, fill=BOTH, expand=True)
        self._content = ttk.Frame(_cv)
        _win = _cv.create_window((0, 0), window=self._content, anchor="nw")
        self._content.bind(
            "<Configure>", lambda e: _cv.configure(scrollregion=_cv.bbox("all")))
        _cv.bind("<Configure>", lambda e: _cv.itemconfig(_win, width=e.width))
        _cv.bind("<Enter>", lambda e: _cv.bind_all(
            "<MouseWheel>", lambda ev: _cv.yview_scroll(int(-ev.delta / 120), "units")))
        _cv.bind("<Leave>", lambda e: _cv.unbind_all("<MouseWheel>"))

        self._name_lbl = ttk.Label(self._content, text="",
                                    font=("Segoe UI", fs(13), "bold"), bootstyle=PRIMARY)
        self._name_lbl.pack(anchor=W, fill=X)

        # ── Seats in play ──
        seats_box = ttk.Labelframe(self._content, text=" Seats in play ", padding=6)
        seats_box.pack(fill=X, pady=(6, 4))
        self._seats_wrap = ttk.Frame(seats_box)
        self._seats_wrap.pack(fill=X)
        addbar = ttk.Frame(seats_box)
        addbar.pack(fill=X, pady=(4, 0))
        ttk.Button(addbar, text="➕ Add / edit seats…", bootstyle=(INFO, OUTLINE),
                   command=self._edit_seats).pack(side=LEFT)
        ttk.Button(addbar, text="🎛 Part limits…", bootstyle=(INFO, OUTLINE),
                   command=self._edit_pools).pack(side=LEFT, padx=(6, 0))
        ttk.Label(addbar, text="Set each seat's capacity (how many at once) and "
                              "any shared limits (e.g. amps).",
                  font=("Segoe UI", fs(8)), foreground=muted_fg()).pack(side=LEFT, padx=8)

        # ── Rotation / lineup board ──
        board_box = ttk.Labelframe(self._content, text=" Lineup ", padding=6)
        board_box.pack(fill=X, pady=4)

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
        # "tree headings": the #0 column carries the instrument icon per row.
        self._board = ttk.Treeview(board_box, columns=bcols, show="tree headings",
                                   selectmode="none", bootstyle=INFO, height=6)
        self._board.heading("#0", text="")
        self._board.column("#0", width=34, minwidth=34, stretch=False, anchor=CENTER)
        self._board.heading("Seat", text="Seat", anchor=W)
        self._board.heading("Player", text="Player", anchor=W)
        self._board.column("Seat", width=160, anchor=W, stretch=True)
        self._board.column("Player", width=200, anchor=W, stretch=True)
        self._board.pack(fill=X)
        self._bench_lbl = ttk.Label(board_box, text="", font=("Segoe UI", fs(9)),
                                    foreground=muted_fg(), wraplength=520, justify=LEFT)
        self._bench_lbl.pack(anchor=W, pady=(2, 0))

        # ── Roster ──
        roster_box = ttk.Labelframe(self._content, text=" Players ", padding=6)
        roster_box.pack(fill=X, pady=4)
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
        self._roster.pack(fill=X)
        self._roster.bind("<Double-1>", lambda e: self._edit_player_parts())

        # ── Songs ──
        songs_box = ttk.Labelframe(self._content, text=" Songs — locked personnel ", padding=6)
        songs_box.pack(fill=X, pady=(4, 2))
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
        self._songs.pack(fill=X)
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
            self._content_outer.pack_forget()
            self._placeholder.pack(fill=BOTH, expand=True)
        else:
            self._placeholder.pack_forget()
            self._content_outer.pack(fill=BOTH, expand=True)

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

    def _seats_raw(self, e=None):
        """Seats as stored (list of {name, capacity} dicts)."""
        e = e or self._ensemble()
        return _loads(e["seats"], []) if e else []

    def _seat_pairs(self, e=None):
        """Seats as ordered (name, capacity) tuples."""
        return jr.normalize_seats(self._seats_raw(e))

    def _seat_names(self, e=None):
        return [n for n, _ in self._seat_pairs(e)]

    def _pools(self, e=None):
        e = e or self._ensemble()
        if not e:
            return []
        try:
            raw = e["pools"]
        except (KeyError, IndexError):
            raw = None
        return _loads(raw, []) or []

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
        pairs = self._seat_pairs()
        if not pairs:
            ttk.Label(self._seats_wrap,
                      text="No seats yet — click “Add / edit seats…”.",
                      font=("Segoe UI", fs(9)), foreground=muted_fg()).pack(anchor=W)
            return
        self._seat_chip_icons = []
        for name, cap in pairs:
            chip = ttk.Frame(self._seats_wrap, relief="solid", borderwidth=1)
            chip.pack(side=LEFT, padx=3, pady=2)
            ic = jazz_icons.icon(chip, name, px=fs(16))
            if ic is not None:
                self._seat_chip_icons.append(ic)
                ttk.Label(chip, image=ic).pack(side=LEFT, padx=(4, 0))
            txt = f"{name} ×{cap}" if cap > 1 else name
            ttk.Label(chip, text=txt, font=("Segoe UI", fs(9), "bold"),
                      padding=(4, 2)).pack(side=LEFT)
        pools = self._pools()
        if pools:
            summary = ";  ".join(
                f"{p.get('name','?')}: max {p.get('limit','?')} across "
                f"{', '.join(p.get('seats', []))}" for p in pools)
            ttk.Label(self._seats_wrap, text="   " + summary,
                      font=("Segoe UI", fs(8)),
                      foreground=muted_fg()).pack(side=LEFT, padx=(8, 0))

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
        seats = self._seats_raw(e)
        players = self._players_payload(e)
        pools = self._pools(e)
        song = self._current_song()
        locked = _loads(song["locked"], {}) if song else {}

        # Day stepper only matters when something rotates (warm-up, or a song
        # with open seats).  A fully-locked song is the same every day.
        cycle = jr.cycle_length(seats, players, locked, pools)
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

        assignments, bench = jr.day_assignments(seats, players, day, locked, pools)
        self._board.delete(*self._board.get_children())
        self._board_icons = []          # keep PhotoImage refs alive
        for seat, names in assignments:
            shown = ", ".join(names) if names else "—"
            if names and locked.get(seat):
                shown = "🔒 " + shown
            ic = jazz_icons.icon(self._board, seat, px=fs(20))
            kw = {"image": ic} if ic is not None else {}
            if ic is not None:
                self._board_icons.append(ic)
            self._board.insert("", "end", text="", values=(seat, shown), **kw)
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
            summary = ",  ".join(f"{seat}: {_who(who)}"
                                 for seat, who in locked.items() if who)
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
            "seats": _dumps([dict(s) for s in jr.DEFAULT_SEATS]),
            "pools": _dumps([]), "current_day": 1})
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
        dlg = _SeatsDialog(self.winfo_toplevel(), self._seat_pairs(e))
        self.wait_window(dlg)
        if dlg.saved:
            self.db.update_jazz_ensemble(e["id"], {"seats": _dumps(dlg.seats)})
            self._render()

    def _edit_pools(self):
        e = self._ensemble()
        if not e:
            return
        names = self._seat_names(e)
        if not names:
            Messagebox.show_info("Add some seats first (Add / edit seats…).",
                                 title="No seats", parent=self)
            return
        dlg = _PartLimitsDialog(self.winfo_toplevel(), names, self._pools(e))
        self.wait_window(dlg)
        if dlg.saved:
            self.db.update_jazz_ensemble(e["id"], {"pools": _dumps(dlg.pools)})
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
                                 self._seat_names(e), player["parts"])
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
        dlg = _SongLineupDialog(self.winfo_toplevel(), song["title"], self._seat_pairs(e),
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


# ══════════════════════════════════════════════════════════════ dialogs ══════

class _SeatsDialog(ttk.Toplevel):
    """Edit the seats in play, each with a capacity (players at once)."""

    def __init__(self, parent, pairs):
        super().__init__(parent)
        self.saved = False
        self.seats = []
        self.title("Seats in Play")
        self.resizable(False, True)
        self.grab_set()
        self.lift()

        hdr = ttk.Frame(self, bootstyle=INFO)
        hdr.pack(fill=X)
        ttk.Label(hdr, text="🎷  Rhythm-section seats",
                  font=("Segoe UI", 12, "bold"),
                  bootstyle=(INVERSE, INFO)).pack(pady=10, padx=16, anchor=W)

        # Pin the buttons to the bottom first so they can't be pushed off.
        btn = ttk.Frame(self)
        btn.pack(side=BOTTOM, fill=X, padx=16, pady=12)
        ttk.Button(btn, text="Cancel", bootstyle=(SECONDARY, OUTLINE),
                   command=self.destroy).pack(side=RIGHT, padx=4)
        ttk.Button(btn, text="Save", bootstyle=SUCCESS,
                   command=self._save).pack(side=RIGHT, padx=4)

        body = ttk.Frame(self)
        body.pack(fill=BOTH, expand=True, padx=16, pady=10)
        ttk.Label(body, text="One seat per row, in board order. Capacity is how "
                             "many players can be on it at once — most parts are "
                             "1, but a mallet seat (vibes/marimba/bells) can hold "
                             "several, which is where extra players go so nobody "
                             "sits out.",
                  font=("Segoe UI", 9), wraplength=430, justify=LEFT).pack(anchor=W)

        cols = ttk.Frame(body)
        cols.pack(fill=X, pady=(6, 0))
        ttk.Label(cols, text="Seat", font=("Segoe UI", 9, "bold"),
                  width=28).pack(side=LEFT)
        ttk.Label(cols, text="At once", font=("Segoe UI", 9, "bold")).pack(side=LEFT)
        self._rows_frame = ttk.Frame(body)
        self._rows_frame.pack(fill=X)
        self._rows = []
        for name, cap in pairs:
            self._add_row(name, cap)

        addbar = ttk.Frame(body)
        addbar.pack(fill=X, pady=(6, 0))
        ttk.Button(addbar, text="➕ Add seat", bootstyle=(SUCCESS, OUTLINE),
                   command=lambda: self._add_row("", 1)).pack(side=LEFT)
        ttk.Label(addbar, text="Quick add:", font=("Segoe UI", 8),
                  foreground=muted_fg()).pack(side=LEFT, padx=(10, 2))
        for s in jr.COMMON_SEATS:
            ttk.Button(addbar, text=s, bootstyle=(SECONDARY, OUTLINE, LINK),
                       command=lambda ss=s: self._quick(ss)).pack(side=LEFT, padx=1)

        from ui.theme import fit_window
        fit_window(self, 480, 520)

    def _add_row(self, name, cap):
        row = ttk.Frame(self._rows_frame)
        row.pack(fill=X, pady=2)
        nv = tk.StringVar(value=name)
        cv = tk.StringVar(value=str(cap))
        ttk.Entry(row, textvariable=nv, width=28).pack(side=LEFT)
        ttk.Spinbox(row, from_=1, to=12, width=4,
                    textvariable=cv).pack(side=LEFT, padx=(8, 0))
        rec = (row, nv, cv)

        def remove():
            row.destroy()
            self._rows.remove(rec)
        ttk.Button(row, text="✕", width=3, bootstyle=(DANGER, OUTLINE, LINK),
                   command=remove).pack(side=LEFT, padx=(8, 0))
        self._rows.append(rec)

    def _quick(self, seat):
        cur = [nv.get().strip().lower() for _r, nv, _c in self._rows]
        if seat.lower() not in cur:
            cap = 4 if seat.lower() in ("vibraphone", "aux percussion") else 1
            self._add_row(seat, cap)

    def _save(self):
        seats, seen = [], set()
        for _row, nv, cv in self._rows:
            name = nv.get().strip()
            if not name or name.lower() in seen:
                continue
            seen.add(name.lower())
            try:
                cap = max(1, int(cv.get()))
            except (TypeError, ValueError):
                cap = 1
            seats.append({"name": name, "capacity": cap})
        self.seats = seats
        self.saved = True
        self.destroy()


class _PartLimitsDialog(ttk.Toplevel):
    """Shared limits across seats — e.g. only 3 amps, split any way across Bass
    and Guitar.  Each limit caps the TOTAL players over the seats you check."""

    def __init__(self, parent, seat_names, pools):
        super().__init__(parent)
        self.saved = False
        self.pools = []
        self._seat_names = list(seat_names)
        self.title("Part Limits")
        self.resizable(False, True)
        self.grab_set()
        self.lift()

        hdr = ttk.Frame(self, bootstyle=INFO)
        hdr.pack(fill=X)
        ttk.Label(hdr, text="🎛  Shared part limits",
                  font=("Segoe UI", 12, "bold"),
                  bootstyle=(INVERSE, INFO)).pack(pady=10, padx=16, anchor=W)

        btn = ttk.Frame(self)
        btn.pack(side=BOTTOM, fill=X, padx=16, pady=12)
        ttk.Button(btn, text="Cancel", bootstyle=(SECONDARY, OUTLINE),
                   command=self.destroy).pack(side=RIGHT, padx=4)
        ttk.Button(btn, text="Save", bootstyle=SUCCESS,
                   command=self._save).pack(side=RIGHT, padx=4)

        body = ttk.Frame(self)
        body.pack(fill=BOTH, expand=True, padx=16, pady=10)
        ttk.Label(body, text="A limit caps the TOTAL players across SEVERAL "
                             "seats. Example: “Amps”, max 3, over Bass + Guitar — "
                             "so two basses + a guitar, or two guitars + a bass, "
                             "but never four.",
                  font=("Segoe UI", 9), wraplength=440, justify=LEFT).pack(anchor=W)
        ttk.Label(body, text="To change how many fit on ONE seat (e.g. several "
                             "players on the mallet/vibraphone seat), set that "
                             "seat's capacity in “Add / edit seats…” instead — "
                             "not here.",
                  font=("Segoe UI", 8), foreground=muted_fg(),
                  wraplength=440, justify=LEFT).pack(anchor=W, pady=(4, 0))

        self._rows_frame = ttk.Frame(body)
        self._rows_frame.pack(fill=X, pady=(6, 0))
        self._rows = []
        for p in pools:
            self._add_row(p.get("name", ""), p.get("limit", 1), p.get("seats", []))
        if not pools:
            self._add_row("Amps", 3, [])

        ttk.Button(body, text="➕ Add limit", bootstyle=(SUCCESS, OUTLINE),
                   command=lambda: self._add_row("", 1, [])).pack(anchor=W, pady=(6, 0))

        from ui.theme import fit_window
        fit_window(self, 500, 480)

    def _add_row(self, name, limit, seats):
        box = ttk.Labelframe(self._rows_frame, text="", padding=6)
        box.pack(fill=X, pady=3)
        top = ttk.Frame(box)
        top.pack(fill=X)
        nv = tk.StringVar(value=name)
        lv = tk.StringVar(value=str(limit))
        ttk.Label(top, text="Name:", font=("Segoe UI", 9)).pack(side=LEFT)
        ttk.Entry(top, textvariable=nv, width=16).pack(side=LEFT, padx=(2, 10))
        ttk.Label(top, text="Max total:", font=("Segoe UI", 9)).pack(side=LEFT)
        ttk.Spinbox(top, from_=1, to=12, width=4, textvariable=lv).pack(side=LEFT, padx=2)
        checks = ttk.Frame(box)
        checks.pack(fill=X, pady=(4, 0))
        chosen = {s for s in seats}
        seat_vars = []
        for nm in self._seat_names:
            var = tk.BooleanVar(value=nm in chosen)
            ttk.Checkbutton(checks, text=nm, variable=var,
                            bootstyle=INFO).pack(side=LEFT, padx=(0, 8))
            seat_vars.append((nm, var))
        rec = {"box": box, "name": nv, "limit": lv, "seats": seat_vars}

        def remove():
            box.destroy()
            self._rows.remove(rec)
        ttk.Button(top, text="✕ remove", bootstyle=(DANGER, OUTLINE, LINK),
                   command=remove).pack(side=RIGHT)
        self._rows.append(rec)

    def _save(self):
        pools = []
        for rec in self._rows:
            name = rec["name"].get().strip()
            seats = [nm for nm, v in rec["seats"] if v.get()]
            try:
                limit = max(1, int(rec["limit"].get()))
            except (TypeError, ValueError):
                limit = 1
            if name and seats:
                pools.append({"name": name, "limit": limit, "seats": seats})
        self.pools = pools
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

    def __init__(self, parent, title, pairs, players, current):
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

        btn = ttk.Frame(self)
        btn.pack(side=BOTTOM, fill=X, padx=16, pady=12)
        ttk.Button(btn, text="Cancel", bootstyle=(SECONDARY, OUTLINE),
                   command=self.destroy).pack(side=RIGHT, padx=4)
        ttk.Button(btn, text="Save", bootstyle=SUCCESS,
                   command=self._save).pack(side=RIGHT, padx=4)

        body = ttk.Frame(self)
        body.pack(fill=BOTH, expand=True, padx=16, pady=10)

        trow = ttk.Frame(body)
        trow.pack(fill=X, pady=(0, 8))
        ttk.Label(trow, text="Song title:", font=("Segoe UI", 9, "bold")).pack(side=LEFT)
        self._title_var = tk.StringVar(value=title)
        ttk.Entry(trow, textvariable=self._title_var, width=28).pack(side=LEFT, padx=(6, 0))

        ttk.Label(body, text="Lock this tune's players. A seat with room for "
                             "several (e.g. a mallet seat) gets a line each; leave "
                             "a slot on “rotate” to keep it open. Only players who "
                             "can cover the seat are offered.",
                  font=("Segoe UI", 9), wraplength=440, justify=LEFT).pack(anchor=W, pady=(0, 8))

        grid = ttk.Frame(body)
        grid.pack(fill=X)
        grid.columnconfigure(1, weight=1)
        self._vars = []            # (seat, StringVar) — several per multi-cap seat
        r = 0
        for seat, cap in pairs:
            eligible = [p["name"] for p in players if seat in p["parts"]]
            values = [self.ROTATE] + eligible
            cur = current.get(seat)
            cur_list = cur if isinstance(cur, list) else ([cur] if cur else [])
            for slot in range(max(1, cap)):
                label = seat if slot == 0 else ""
                ttk.Label(grid, text=label, font=("Segoe UI", 9, "bold")).grid(
                    row=r, column=0, sticky=W, pady=3, padx=(0, 10))
                pick = cur_list[slot] if slot < len(cur_list) and cur_list[slot] in eligible \
                    else self.ROTATE
                var = tk.StringVar(value=pick)
                ttk.Combobox(grid, textvariable=var, values=values, state="readonly",
                             width=26).grid(row=r, column=1, sticky=W, pady=3)
                self._vars.append((seat, var))
                r += 1
        if not pairs:
            ttk.Label(body, text="Add seats first.", foreground=muted_fg()).pack(anchor=W)

        from ui.theme import fit_window
        fit_window(self, 480, 560)

    def _save(self):
        self.title = (self._title_var.get() or "").strip() or self.title_text
        locked = {}
        for seat, var in self._vars:
            val = var.get()
            if val and val != self.ROTATE:
                locked.setdefault(seat, [])
                if val not in locked[seat]:
                    locked[seat].append(val)
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
