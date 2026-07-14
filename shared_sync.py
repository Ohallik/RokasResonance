"""
shared_sync.py - The engine that keeps a director's local mirror in step with a
shared Turso database (see ``sharing.py`` for the plumbing / rationale).

Model: the cloud copy is the single source of truth for the SHARED_TABLES.  Each
director keeps a *local mirror* of those tables inside their normal
``rokas_resonance.db`` so reads are instant and available offline.  Writes to a
shared table are sent to the cloud first (which assigns the row id), then applied
to the local mirror — so two directors inserting instruments never collide on ids.

Integration is deliberately surgical: ``Database`` swaps its one connection
factory for a thin proxy when sharing is active, so none of the ~30 existing
write sites had to change.  The proxy:
  * passes SELECTs and non-shared writes straight through to local SQLite,
  * routes INSERT/UPDATE/DELETE on a shared table to the cloud, then mirrors the
    result locally,
  * raises a clear "you're offline" error if the cloud can't be reached during a
    shared write (viewing still works from the mirror — that's the tradeoff the
    teacher opted into).

The ``remote`` object is duck-typed (``execute`` / ``insert_returning`` /
``batch``): production passes a ``sharing.TursoClient``; tests pass a local
SQLite stand-in, so all of this logic is verifiable without a network.
"""

from __future__ import annotations

import re
import sqlite3

from sharing import SHARED_TABLES, TursoOffline

# Leading verb + target table.  Our own SQL is simple (no CTEs before the verb),
# so anchoring at the start is reliable.
_WRITE_RE = re.compile(
    r'^\s*(INSERT(?:\s+OR\s+\w+)?\s+INTO|REPLACE\s+INTO|UPDATE|DELETE\s+FROM)'
    r'\s+["\[`]?(\w+)', re.IGNORECASE)


def _classify(sql: str):
    """Return (table, is_insert) if ``sql`` writes a shared table, else None."""
    m = _WRITE_RE.match(sql or "")
    if not m:
        return None
    verb = m.group(1).upper()
    table = m.group(2).lower()
    if table not in SHARED_TABLES:
        return None
    is_insert = verb.startswith("INSERT") or verb.startswith("REPLACE")
    return table, is_insert


def _insert_sql(table: str, row: dict):
    cols = list(row.keys())
    ph = ", ".join("?" for _ in cols)
    collist = ", ".join(cols)
    return (f"INSERT OR REPLACE INTO {table} ({collist}) VALUES ({ph})",
            [row[c] for c in cols])


class _FakeCursor:
    """Stand-in returned for an intercepted INSERT so callers that read
    ``.lastrowid`` keep working."""
    def __init__(self, lastrowid=None):
        self.lastrowid = lastrowid
        self.rowcount = 1 if lastrowid is not None else 0

    def fetchone(self):
        return None

    def fetchall(self):
        return []


class _SyncConnection:
    """Wraps a live sqlite3 connection.  Everything delegates to the real
    connection except ``execute`` on a shared-table write, which is routed to the
    cloud first.  Used only while sharing is active."""

    def __init__(self, conn: sqlite3.Connection, engine: "SharedSync"):
        self._conn = conn
        self._engine = engine

    # context-manager: `with self._connect() as conn:` must yield the proxy but
    # commit/rollback on the real connection.
    def __enter__(self):
        self._conn.__enter__()
        return self

    def __exit__(self, *exc):
        return self._conn.__exit__(*exc)

    def execute(self, sql, params=()):
        hit = _classify(sql)
        if hit is None:
            return self._conn.execute(sql, params)
        table, is_insert = hit
        if is_insert:
            # Cloud assigns the id; mirror the returned row locally so ids match.
            row = self._engine.remote.insert_returning(table, sql, list(params))
            if row:
                isql, iargs = _insert_sql(table, row)
                self._conn.execute(isql, iargs)
                return _FakeCursor(lastrowid=row.get("id"))
            return _FakeCursor(lastrowid=None)
        # UPDATE / DELETE: ids already agree (mirror was built from the cloud),
        # so run the identical statement on both.
        self._engine.remote.execute(sql, list(params))
        return self._conn.execute(sql, params)

    def executescript(self, sql):
        # Only schema (CREATE TABLE…) uses this; never shared data writes.
        return self._conn.executescript(sql)

    def __getattr__(self, name):
        # commit / rollback / close / row_factory / cursor / total_changes …
        return getattr(self._conn, name)


class SharedSync:
    """Owns the cloud ``remote`` and the local mirror path; performs schema
    setup, full push (owner) / pull (join + refresh), and hands the proxy to
    ``Database``."""

    def __init__(self, db_path: str, remote, tables=None):
        self.db_path = db_path
        self.remote = remote
        self.tables = list(tables or SHARED_TABLES)
        self.active = False       # flipped on once bound + first pull succeeds
        self.last_error = None
        self._refreshing = False  # guards overlapping periodic refreshes

    def wrap(self, conn):
        """Return a proxy connection if active, else the plain connection."""
        if self.active:
            return _SyncConnection(conn, self)
        return conn

    # ── schema ──
    def _local_conn(self):
        c = sqlite3.connect(self.db_path)
        c.row_factory = sqlite3.Row
        return c

    def local_create_sql(self):
        """The exact CREATE TABLE statements for the shared tables, read from the
        local schema so cloud + local never drift."""
        out = {}
        with self._local_conn() as c:
            for t in self.tables:
                r = c.execute("SELECT sql FROM sqlite_master WHERE type='table' "
                              "AND name=?", (t,)).fetchone()
                if r and r[0]:
                    out[t] = r[0]
        return out

    def ensure_remote_schema(self):
        """Create any missing shared tables on the cloud (idempotent).  SQLite
        stores DDL without "IF NOT EXISTS", so inject it before replaying."""
        for t, sql in self.local_create_sql().items():
            s = sql.lstrip()
            if s[:12].upper() == "CREATE TABLE" and "IF NOT EXISTS" not in s[:40].upper():
                s = s[:12] + " IF NOT EXISTS" + s[12:]
            self.remote.execute(s)

    # ── full transfers ──
    def _read_local_rows(self, table):
        with self._local_conn() as c:
            cur = c.execute(f"SELECT * FROM {table}")
            cols = [d[0] for d in cur.description]
            return cols, [dict(zip(cols, row)) for row in cur.fetchall()]

    def push_all(self):
        """Replace the cloud's shared tables with this director's local data.
        Used when a director turns sharing ON as the OWNER."""
        self.ensure_remote_schema()
        for t in self.tables:
            _, rows = self._read_local_rows(t)
            stmts = [(f"DELETE FROM {t}", [])]
            for row in rows:
                stmts.append(_insert_sql(t, row))
            self.remote.batch(stmts)

    def _read_remote_rows(self, table):
        res = self.remote.execute(f"SELECT * FROM {table}")
        return res.get("rows", [])

    def pull_all(self):
        """Replace the local mirror's shared tables with the cloud's data.  Used
        when a director JOINs, and again periodically to pick up the co-director's
        changes.  FK checks are suspended because a shared checkout may reference
        a student who lives only in the *other* director's local roster."""
        remote_data = {t: self._read_remote_rows(t) for t in self.tables}
        conn = self._local_conn()
        try:
            conn.execute("PRAGMA foreign_keys = OFF")
            conn.execute("BEGIN")
            # children first on delete, parents first on insert (self.tables is
            # already parent→child, so delete in reverse).
            for t in reversed(self.tables):
                conn.execute(f"DELETE FROM {t}")
            for t in self.tables:
                for row in remote_data[t]:
                    isql, iargs = _insert_sql(t, row)
                    conn.execute(isql, iargs)
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        finally:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.close()

    # ── lifecycle ──
    def start_as_owner(self):
        """Turn sharing on for the director whose data seeds the shared set."""
        self.ensure_remote_schema()
        self.push_all()
        self.active = True

    def start_as_join(self):
        """Turn sharing on for a director adopting an existing shared set."""
        self.ensure_remote_schema()
        self.pull_all()
        self.active = True

    def resume(self):
        """Re-activate an already-configured share at app startup: go active and
        best-effort pull.  If offline, stay active on the last-known mirror
        (reads work; shared writes will fail until back online)."""
        self.active = True
        return self.refresh()

    def refresh(self):
        """Pull the latest cloud data into the mirror.  Returns True on success,
        False if offline (caller keeps showing the last-known mirror)."""
        if not self.active or self._refreshing:
            return False
        self._refreshing = True
        try:
            self.pull_all()
            self.last_error = None
            return True
        except TursoOffline as e:
            self.last_error = str(e)
            return False
        except Exception as e:
            # Never let a background refresh crash the app; keep last-known mirror.
            self.last_error = str(e)
            return False
        finally:
            self._refreshing = False


def build_from_settings(base_dir: str, db_path: str):
    """Return a (not-yet-active) SharedSync from the profile's saved sharing
    settings, or None if this profile isn't sharing.  Caller decides whether to
    ``resume()`` (startup) vs ``start_as_owner/join`` (first enable)."""
    from sharing import load_sharing, TursoClient
    b = load_sharing(base_dir)
    if not (b.get("enabled") and b.get("url") and b.get("token")):
        return None
    client = TursoClient(b["url"], b["token"])
    return SharedSync(db_path, client)
