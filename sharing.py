"""
sharing.py - Co-director shared-inventory support (optional, off by default).

A handful of large high schools have two band directors who keep separate class
lists but share ONE instrument inventory, check-out log, repair log, and music
library.  This module lets those directors point Roka at a shared Turso database
(cloud SQLite) so each sees the other's changes.

Design (see the conversation that produced this): everyone is "solo" by default —
all data local, no network, nothing new.  A director can opt in during onboarding
or later from Settings.  When on, only the SHARED_TABLES live in the cloud copy;
students, agendas, and budget stay personal and local.  The cloud copy is the
single source of truth (edits need internet); a local mirror keeps viewing fast
and available offline.

This file has no tkinter — it is the plumbing:
  * ``TursoClient``  - tiny pure-``urllib`` client for Turso's HTTP (Hrana) API,
                       so nothing needs compiling or bundling beyond the stdlib.
  * connection codes - pack a database URL + token into one paste-able string a
                       director can hand to their co-director.
  * settings helpers - read/write the ``sharing`` block in settings.json.

The sync engine that uses this lives in ``shared_sync.py``.
"""

from __future__ import annotations

import base64
import json
import ssl
import urllib.request
import urllib.error
import zlib

# ── Which tables are shared between co-directors ──────────────────────────────
# Order matters for migration/replace: parents before children (FK-ish order).
# instruments  → checkouts / repairs reference an instrument
# sheet_music  → omr_jobs / performances reference a piece
SHARED_TABLES = [
    "instruments",
    "sheet_music",
    "checkouts",
    "repairs",
    "omr_jobs",
    "performances",
]

# Personal tables never leave the local DB; listed here only for documentation
# and so a future audit can assert the two sets don't overlap.
PERSONAL_TABLES_NOTE = (
    "students, teaching_classes, concert_dates, curriculum_items, lesson_plans, "
    "lesson_blocks, resources, budget_*, fee_types, student_fees, loans (and the "
    "per-year lesson_plans_<year>.db) all stay local."
)

CODE_PREFIX = "ROKA-SHARE-v1."


# ══════════════════════════════════════════════════════════════════════════════
# Connection codes  (URL + token  ⇄  one paste-able string)
# ══════════════════════════════════════════════════════════════════════════════
def make_connection_code(db_url: str, token: str, label: str = "") -> str:
    """Pack a Turso database URL + auth token into a single code string that an
    admin can hand to each director.  Includes a CRC so a mangled paste is
    caught instead of silently failing to connect."""
    db_url = (db_url or "").strip()
    token = (token or "").strip()
    if not db_url or not token:
        raise ValueError("Both a database URL and a token are required.")
    payload = {"u": db_url, "t": token}
    if label:
        payload["l"] = label.strip()
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    body = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    crc = format(zlib.crc32(raw) & 0xFFFFFFFF, "08x")
    return f"{CODE_PREFIX}{crc}.{body}"


def parse_connection_code(code: str) -> dict:
    """Reverse of :func:`make_connection_code`.  Returns
    ``{"url": ..., "token": ..., "label": ...}``.  Raises ValueError with a
    teacher-friendly message on anything malformed."""
    code = (code or "").strip()
    # Tolerate accidental surrounding quotes / whitespace from copy-paste.
    code = code.strip().strip('"').strip("'").strip()
    if not code.startswith(CODE_PREFIX):
        raise ValueError("That doesn't look like a Roka sharing code.")
    rest = code[len(CODE_PREFIX):]
    try:
        crc_hex, body = rest.split(".", 1)
    except ValueError:
        raise ValueError("The sharing code is incomplete — copy the whole thing.")
    pad = "=" * (-len(body) % 4)
    try:
        raw = base64.urlsafe_b64decode(body + pad)
    except Exception:
        raise ValueError("The sharing code is damaged — copy it again exactly.")
    if format(zlib.crc32(raw) & 0xFFFFFFFF, "08x") != crc_hex.lower():
        raise ValueError("The sharing code seems to have been cut off or altered "
                         "— copy it again exactly.")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception:
        raise ValueError("The sharing code is damaged — copy it again exactly.")
    url = (payload.get("u") or "").strip()
    token = (payload.get("t") or "").strip()
    if not url or not token:
        raise ValueError("The sharing code is missing its address or key.")
    return {"url": url, "token": token, "label": (payload.get("l") or "").strip()}


# ══════════════════════════════════════════════════════════════════════════════
# Settings block  (persisted in the profile's settings.json)
# ══════════════════════════════════════════════════════════════════════════════
def load_sharing(base_dir: str) -> dict:
    """Return the profile's ``sharing`` settings block (empty dict if unset)."""
    try:
        from ui.settings_dialog import load_settings
        return dict((load_settings(base_dir) or {}).get("sharing") or {})
    except Exception:
        return {}


def save_sharing(base_dir: str, block: dict) -> None:
    """Persist the ``sharing`` settings block."""
    from ui.settings_dialog import load_settings, save_settings
    s = load_settings(base_dir) or {}
    s["sharing"] = block
    save_settings(base_dir, s)


def is_sharing_enabled(base_dir: str) -> bool:
    b = load_sharing(base_dir)
    return bool(b.get("enabled") and b.get("url") and b.get("token"))


# ══════════════════════════════════════════════════════════════════════════════
# Turso HTTP (Hrana) client — pure urllib, no third-party packages
# ══════════════════════════════════════════════════════════════════════════════
class TursoError(Exception):
    """Any failure talking to the shared database (network, auth, or SQL)."""


class TursoOffline(TursoError):
    """Couldn't reach the server at all (no internet / server down).  Callers
    treat this specially: fall back to the local read-only mirror."""


def _http_base(db_url: str) -> str:
    """libsql://host  →  https://host  (Turso's HTTP endpoint)."""
    u = (db_url or "").strip().rstrip("/")
    if u.startswith("libsql://"):
        u = "https://" + u[len("libsql://"):]
    elif u.startswith("wss://"):
        u = "https://" + u[len("wss://"):]
    elif u.startswith("ws://"):
        u = "http://" + u[len("ws://"):]
    elif not (u.startswith("http://") or u.startswith("https://")):
        u = "https://" + u
    return u


def _encode_arg(v):
    if v is None:
        return {"type": "null"}
    if isinstance(v, bool):
        return {"type": "integer", "value": "1" if v else "0"}
    if isinstance(v, int):
        return {"type": "integer", "value": str(v)}
    if isinstance(v, float):
        return {"type": "float", "value": v}
    if isinstance(v, (bytes, bytearray)):
        return {"type": "blob",
                "base64": base64.b64encode(bytes(v)).decode("ascii")}
    return {"type": "text", "value": str(v)}


def _decode_cell(cell):
    t = cell.get("type")
    if t == "null":
        return None
    if t == "integer":
        return int(cell["value"])
    if t == "float":
        return float(cell["value"])
    if t == "blob":
        return base64.b64decode(cell.get("base64", ""))
    return cell.get("value")


class TursoClient:
    """Minimal synchronous client for Turso's ``/v2/pipeline`` HTTP API.

    Enough for what the sync engine needs: parameterised execute, multi-row
    fetch, and batched writes wrapped in a transaction.  Uses only urllib +
    json so it bundles with zero extra dependencies.
    """

    def __init__(self, db_url: str, token: str, timeout: float = 15.0):
        self.endpoint = _http_base(db_url) + "/v2/pipeline"
        self.token = token
        self.timeout = timeout
        self._ctx = ssl.create_default_context()

    # ── low-level pipeline call ──
    def _pipeline(self, requests_list):
        body = json.dumps({"requests": requests_list}).encode("utf-8")
        req = urllib.request.Request(
            self.endpoint, data=body, method="POST",
            headers={"Authorization": f"Bearer {self.token}",
                     "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout,
                                        context=self._ctx) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = e.read().decode("utf-8", "replace")
            except Exception:
                pass
            if e.code in (401, 403):
                raise TursoError("The shared database rejected the access key "
                                 "(401/403). The token may be wrong or expired.")
            raise TursoError(f"Shared database error {e.code}: {detail[:300]}")
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise TursoOffline(f"Can't reach the shared database: {e}")
        # Surface a per-statement error if the pipeline reports one.
        for r in data.get("results", []):
            if r.get("type") == "error":
                msg = (r.get("error") or {}).get("message", "SQL error")
                raise TursoError(msg)
        return data

    @staticmethod
    def _one_result(data):
        for r in data.get("results", []):
            if r.get("type") == "ok" and \
                    r.get("response", {}).get("type") == "execute":
                return r["response"]["result"]
        return None

    # ── public API ──
    def execute(self, sql: str, args=None):
        """Run one statement.  Returns a dict:
        ``{"rows": [dict,...], "cols": [...], "affected": int,
           "last_insert_rowid": int|None}``."""
        stmt = {"sql": sql, "args": [_encode_arg(a) for a in (args or [])]}
        data = self._pipeline([{"type": "execute", "stmt": stmt},
                               {"type": "close"}])
        res = self._one_result(data)
        if res is None:
            return {"rows": [], "cols": [], "affected": 0,
                    "last_insert_rowid": None}
        cols = [c.get("name") for c in res.get("cols", [])]
        rows = [dict(zip(cols, [_decode_cell(c) for c in row]))
                for row in res.get("rows", [])]
        lirid = res.get("last_insert_rowid")
        return {"rows": rows, "cols": cols,
                "affected": res.get("affected_row_count", 0),
                "last_insert_rowid": int(lirid) if lirid not in (None, "") else None}

    def insert_returning(self, table: str, sql: str, args=None):
        """Run an INSERT on the remote and return the full inserted row (with the
        remote-assigned id) in ONE round trip.  ``last_insert_rowid()`` is valid
        for the rest of the pipeline because it runs on the same connection
        before ``close``.  Returns a row dict, or None if nothing was inserted."""
        ins = {"sql": sql, "args": [_encode_arg(a) for a in (args or [])]}
        sel = {"sql": f"SELECT * FROM {table} WHERE rowid = last_insert_rowid()"}
        data = self._pipeline([{"type": "execute", "stmt": ins},
                               {"type": "execute", "stmt": sel},
                               {"type": "close"}])
        # second execute result is our SELECT
        execs = [r for r in data.get("results", [])
                 if r.get("type") == "ok"
                 and r.get("response", {}).get("type") == "execute"]
        if len(execs) < 2:
            return None
        res = execs[1]["response"]["result"]
        cols = [c.get("name") for c in res.get("cols", [])]
        rows = res.get("rows", [])
        if not rows:
            return None
        return dict(zip(cols, [_decode_cell(c) for c in rows[0]]))

    def batch(self, statements):
        """Run many (sql, args) statements atomically (BEGIN…COMMIT).  Used for
        migration pushes and replace-all pulls so a mid-way failure doesn't
        leave the shared DB half-written."""
        reqs = [{"type": "execute", "stmt": {"sql": "BEGIN"}}]
        for sql, args in statements:
            reqs.append({"type": "execute",
                         "stmt": {"sql": sql,
                                  "args": [_encode_arg(a) for a in (args or [])]}})
        reqs.append({"type": "execute", "stmt": {"sql": "COMMIT"}})
        reqs.append({"type": "close"})
        self._pipeline(reqs)

    def test_connection(self):
        """Quick reachability + auth check.  Returns True or raises TursoError/
        TursoOffline with a message suitable for showing the teacher."""
        self.execute("SELECT 1")
        return True
