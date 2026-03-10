"""
database.py - SQLite database layer for Roka's Resonance
"""

import sqlite3
import shutil
import os
from datetime import datetime


class Database:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_db()

    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        return conn

    def _init_db(self):
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS instruments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    category TEXT,
                    description TEXT,
                    brand TEXT,
                    model TEXT,
                    barcode TEXT,
                    quantity INTEGER DEFAULT 1,
                    district_no TEXT,
                    case_no TEXT,
                    condition TEXT,
                    serial_no TEXT,
                    date_purchased TEXT,
                    year_purchased TEXT,
                    po_number TEXT,
                    last_service TEXT,
                    amount_paid REAL DEFAULT 0,
                    est_value REAL DEFAULT 0,
                    locker TEXT,
                    lock_no TEXT,
                    combo TEXT,
                    comments TEXT,
                    accessories TEXT,
                    is_active INTEGER DEFAULT 1,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS students (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    school_year TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    student_id TEXT,
                    grade TEXT,
                    gender TEXT,
                    birth_date TEXT,
                    address TEXT,
                    city TEXT,
                    state TEXT,
                    zip_code TEXT,
                    phone TEXT,
                    student_email TEXT,
                    parent1_name TEXT,
                    parent1_relation TEXT,
                    parent1_phone TEXT,
                    parent1_email TEXT,
                    parent2_name TEXT,
                    parent2_relation TEXT,
                    parent2_phone TEXT,
                    parent2_email TEXT,
                    notes TEXT,
                    is_active INTEGER DEFAULT 1
                );

                CREATE TABLE IF NOT EXISTS checkouts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    instrument_id INTEGER NOT NULL,
                    student_id INTEGER,
                    student_name TEXT,
                    date_assigned TEXT,
                    date_returned TEXT,
                    due_date TEXT,
                    notes TEXT,
                    form_generated INTEGER DEFAULT 0,
                    FOREIGN KEY (instrument_id) REFERENCES instruments(id),
                    FOREIGN KEY (student_id) REFERENCES students(id)
                );

                CREATE TABLE IF NOT EXISTS repairs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    instrument_id INTEGER NOT NULL,
                    priority INTEGER DEFAULT 0,
                    date_added TEXT,
                    assigned_to TEXT,
                    date_repaired TEXT,
                    description TEXT,
                    location TEXT,
                    est_cost REAL DEFAULT 0,
                    act_cost REAL DEFAULT 0,
                    invoice_number TEXT,
                    notes TEXT,
                    FOREIGN KEY (instrument_id) REFERENCES instruments(id)
                );

                CREATE TABLE IF NOT EXISTS sheet_music (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    composer TEXT,
                    arranger TEXT,
                    genre TEXT,
                    ensemble_type TEXT,
                    difficulty TEXT,
                    file_path TEXT,
                    file_type TEXT,
                    num_pages INTEGER,
                    notes TEXT,
                    is_active INTEGER DEFAULT 1,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS omr_jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    music_id INTEGER NOT NULL,
                    engine TEXT,
                    status TEXT DEFAULT 'pending',
                    musicxml_path TEXT,
                    validation_errors TEXT,
                    started_at TEXT,
                    completed_at TEXT,
                    notes TEXT,
                    FOREIGN KEY (music_id) REFERENCES sheet_music(id)
                );

                CREATE TABLE IF NOT EXISTS performances (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    music_id INTEGER NOT NULL,
                    performance_date TEXT,
                    ensemble TEXT,
                    event_name TEXT,
                    notes TEXT,
                    FOREIGN KEY (music_id) REFERENCES sheet_music(id)
                );
            """)
            # Migrate: add due_date column if it doesn't exist yet
            try:
                conn.execute("ALTER TABLE checkouts ADD COLUMN due_date TEXT")
                conn.commit()
            except Exception:
                pass  # Column already exists
            # Migrate: add corrections_applied column to omr_jobs
            try:
                conn.execute(
                    "ALTER TABLE omr_jobs ADD COLUMN corrections_applied TEXT"
                )
                conn.commit()
            except Exception:
                pass  # Column already exists
            # Migrate: add key_signature, time_signature, location, publisher, source_file to sheet_music
            for col in ("key_signature TEXT", "time_signature TEXT", "location TEXT",
                        "publisher TEXT", "source_file TEXT"):
                try:
                    conn.execute(f"ALTER TABLE sheet_music ADD COLUMN {col}")
                    conn.commit()
                except Exception:
                    pass
            # Migrate: add choir-specific fields
            for col in ("voicing TEXT", "language TEXT", "accompaniment TEXT"):
                try:
                    conn.execute(f"ALTER TABLE sheet_music ADD COLUMN {col}")
                    conn.commit()
                except Exception:
                    pass
            # Migrate: normalize difficulty from "Grade X" to just "X"
            try:
                conn.execute(
                    "UPDATE sheet_music SET difficulty = REPLACE(difficulty, 'Grade ', '') "
                    "WHERE difficulty LIKE 'Grade %'"
                )
                conn.commit()
            except Exception:
                pass
            # Migrate: add indexes for search performance
            for idx_sql in [
                "CREATE INDEX IF NOT EXISTS idx_sm_title ON sheet_music(title COLLATE NOCASE)",
                "CREATE INDEX IF NOT EXISTS idx_sm_composer ON sheet_music(composer COLLATE NOCASE)",
                "CREATE INDEX IF NOT EXISTS idx_sm_genre ON sheet_music(genre)",
                "CREATE INDEX IF NOT EXISTS idx_sm_active ON sheet_music(is_active)",
            ]:
                try:
                    conn.execute(idx_sql)
                    conn.commit()
                except Exception:
                    pass

    # ─── Backup ────────────────────────────────────────────────────────────────

    def backup(self, max_backups: int = 10) -> str | None:
        """
        Copy the database file to a timestamped backup in a 'backups' folder
        next to the database. Keeps the most recent *max_backups* copies.
        Returns the backup path on success, or None if the db file doesn't exist.
        """
        if not os.path.exists(self.db_path):
            return None

        backup_dir = os.path.join(os.path.dirname(self.db_path), "backups")
        os.makedirs(backup_dir, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = f"rokas_resonance_{timestamp}.db"
        backup_path = os.path.join(backup_dir, backup_name)

        # Flush WAL to main db before copying
        try:
            with self._connect() as conn:
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except Exception:
            pass

        shutil.copy2(self.db_path, backup_path)

        # Rotate: keep only the newest max_backups files
        backups = sorted(
            [f for f in os.listdir(backup_dir) if f.endswith(".db")],
            reverse=True,
        )
        for old in backups[max_backups:]:
            try:
                os.remove(os.path.join(backup_dir, old))
            except OSError:
                pass

        return backup_path

    def backup_to_external(self, external_dir: str, profile_name: str = "", max_backups: int = 30) -> str:
        """
        Copy the database to a user-specified external folder (e.g. OneDrive, network drive).
        Files are stored in a subfolder named after the profile so multiple profiles
        don't overwrite each other.  Keeps the most recent *max_backups* copies.
        Returns the backup path on success, raises on failure.
        """
        if not os.path.exists(self.db_path):
            raise FileNotFoundError(f"Database not found: {self.db_path}")

        # Use a subfolder per profile so multiple teachers' backups don't collide
        dest_dir = os.path.join(external_dir, profile_name) if profile_name else external_dir
        os.makedirs(dest_dir, exist_ok=True)

        # Flush WAL before copying
        try:
            with self._connect() as conn:
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except Exception:
            pass

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = f"rokas_resonance_{timestamp}.db"
        backup_path = os.path.join(dest_dir, backup_name)
        shutil.copy2(self.db_path, backup_path)

        # Rotate: keep only the newest max_backups files
        backups = sorted(
            [f for f in os.listdir(dest_dir) if f.endswith(".db")],
            reverse=True,
        )
        for old in backups[max_backups:]:
            try:
                os.remove(os.path.join(dest_dir, old))
            except OSError:
                pass

        return backup_path

    # ─── Instrument CRUD ───────────────────────────────────────────────────────

    def get_all_instruments(self, include_inactive=False):
        with self._connect() as conn:
            if include_inactive:
                return conn.execute(
                    "SELECT * FROM instruments ORDER BY category, description"
                ).fetchall()
            return conn.execute(
                "SELECT * FROM instruments WHERE is_active=1 ORDER BY category, description"
            ).fetchall()

    def get_instrument(self, instrument_id: int):
        with self._connect() as conn:
            return conn.execute(
                "SELECT * FROM instruments WHERE id=?", (instrument_id,)
            ).fetchone()

    def get_instrument_by_serial(self, serial_no: str):
        """Return the first active instrument matching serial_no."""
        with self._connect() as conn:
            return conn.execute(
                "SELECT * FROM instruments WHERE is_active=1 AND serial_no=? LIMIT 1",
                (serial_no,)
            ).fetchone()

    def get_instrument_by_barcode(self, barcode: str):
        """Return the first active instrument matching barcode or district_no."""
        with self._connect() as conn:
            return conn.execute(
                """SELECT * FROM instruments
                   WHERE is_active=1 AND (barcode=? OR district_no=?)
                   LIMIT 1""",
                (barcode, barcode)
            ).fetchone()

    def find_student_by_student_id(self, student_id: str):
        """Lookup student by their district student_id string."""
        with self._connect() as conn:
            return conn.execute(
                "SELECT * FROM students WHERE student_id=? ORDER BY id DESC LIMIT 1",
                (student_id,)
            ).fetchone()

    def add_instrument(self, data: dict) -> int:
        cols = [
            "category", "description", "brand", "model", "barcode", "quantity",
            "district_no", "case_no", "condition", "serial_no", "date_purchased",
            "year_purchased", "po_number", "last_service", "amount_paid", "est_value",
            "locker", "lock_no", "combo", "comments", "accessories"
        ]
        values = [data.get(c) for c in cols]
        placeholders = ",".join(["?"] * len(cols))
        col_str = ",".join(cols)
        with self._connect() as conn:
            cur = conn.execute(
                f"INSERT INTO instruments ({col_str}) VALUES ({placeholders})", values
            )
            return cur.lastrowid

    def update_instrument(self, instrument_id: int, data: dict):
        cols = [
            "category", "description", "brand", "model", "barcode", "quantity",
            "district_no", "case_no", "condition", "serial_no", "date_purchased",
            "year_purchased", "po_number", "last_service", "amount_paid", "est_value",
            "locker", "lock_no", "combo", "comments", "accessories", "is_active"
        ]
        set_clause = ", ".join([f"{c}=?" for c in cols])
        values = [data.get(c) for c in cols] + [instrument_id]
        with self._connect() as conn:
            conn.execute(
                f"UPDATE instruments SET {set_clause} WHERE id=?", values
            )

    def deactivate_instrument(self, instrument_id: int):
        with self._connect() as conn:
            conn.execute(
                "UPDATE instruments SET is_active=0 WHERE id=?", (instrument_id,)
            )

    def get_instrument_status(self, instrument_id: int) -> str:
        """Returns 'Checked Out' or 'Available' by checking active checkouts."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id FROM checkouts WHERE instrument_id=? AND date_returned IS NULL LIMIT 1",
                (instrument_id,)
            ).fetchone()
        return "Checked Out" if row else "Available"

    def get_instruments_with_status(self, include_inactive=False):
        """Return instruments joined with current checkout info."""
        active_filter = "" if include_inactive else "AND i.is_active=1"
        sql = f"""
            SELECT
                i.*,
                CASE WHEN c.id IS NOT NULL THEN 'Checked Out' ELSE 'Available' END AS status,
                c.student_name AS checked_out_to,
                c.date_assigned AS checkout_date
            FROM instruments i
            LEFT JOIN checkouts c ON c.instrument_id = i.id AND c.date_returned IS NULL
            WHERE 1=1 {active_filter}
            ORDER BY i.category, i.description
        """
        with self._connect() as conn:
            return conn.execute(sql).fetchall()

    # ─── Student CRUD ──────────────────────────────────────────────────────────

    def get_all_students(self, school_year=None, include_inactive=False):
        with self._connect() as conn:
            conditions = []
            params = []
            if not include_inactive:
                conditions.append("is_active=1")
            if school_year:
                conditions.append("school_year=?")
                params.append(school_year)
            where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
            return conn.execute(
                f"SELECT * FROM students {where} ORDER BY last_name, first_name", params
            ).fetchall()

    def get_student(self, student_id: int):
        with self._connect() as conn:
            return conn.execute(
                "SELECT * FROM students WHERE id=?", (student_id,)
            ).fetchone()

    def find_student_by_name(self, first_name: str, last_name: str, school_year: str = None):
        with self._connect() as conn:
            if school_year:
                return conn.execute(
                    "SELECT * FROM students WHERE LOWER(first_name)=? AND LOWER(last_name)=? AND school_year=?",
                    (first_name.lower(), last_name.lower(), school_year)
                ).fetchone()
            return conn.execute(
                "SELECT * FROM students WHERE LOWER(first_name)=? AND LOWER(last_name)=?",
                (first_name.lower(), last_name.lower())
            ).fetchone()

    def add_student(self, data: dict) -> int:
        cols = [
            "school_year", "first_name", "last_name", "student_id", "grade",
            "gender", "birth_date", "address", "city", "state", "zip_code",
            "phone", "student_email", "parent1_name", "parent1_relation",
            "parent1_phone", "parent1_email", "parent2_name", "parent2_relation",
            "parent2_phone", "parent2_email", "notes"
        ]
        values = [data.get(c) for c in cols]
        placeholders = ",".join(["?"] * len(cols))
        col_str = ",".join(cols)
        with self._connect() as conn:
            cur = conn.execute(
                f"INSERT INTO students ({col_str}) VALUES ({placeholders})", values
            )
            return cur.lastrowid

    def update_student(self, student_id: int, data: dict):
        cols = [
            "school_year", "first_name", "last_name", "student_id", "grade",
            "gender", "birth_date", "address", "city", "state", "zip_code",
            "phone", "student_email", "parent1_name", "parent1_relation",
            "parent1_phone", "parent1_email", "parent2_name", "parent2_relation",
            "parent2_phone", "parent2_email", "notes", "is_active"
        ]
        set_clause = ", ".join([f"{c}=?" for c in cols])
        values = [data.get(c) for c in cols] + [student_id]
        with self._connect() as conn:
            conn.execute(
                f"UPDATE students SET {set_clause} WHERE id=?", values
            )

    def deactivate_student(self, student_id: int):
        with self._connect() as conn:
            conn.execute(
                "UPDATE students SET is_active=0 WHERE id=?", (student_id,)
            )

    def reactivate_student(self, student_id: int):
        with self._connect() as conn:
            conn.execute(
                "UPDATE students SET is_active=1 WHERE id=?", (student_id,)
            )

    def get_student_active_checkout_count(self, student_id: int) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM checkouts "
                "WHERE student_id=? AND date_returned IS NULL",
                (student_id,)
            ).fetchone()
            return row[0] if row else 0

    def get_school_years(self):
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT DISTINCT school_year FROM students WHERE school_year IS NOT NULL ORDER BY school_year DESC"
            ).fetchall()
        return [r["school_year"] for r in rows]

    # ─── Checkout CRUD ─────────────────────────────────────────────────────────

    def checkout_instrument(self, instrument_id: int, student_id: int,
                            student_name: str, date_assigned: str, notes: str = "",
                            due_date: str = "") -> int:
        with self._connect() as conn:
            cur = conn.execute(
                """INSERT INTO checkouts
                   (instrument_id, student_id, student_name, date_assigned, notes, due_date)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (instrument_id, student_id, student_name, date_assigned, notes, due_date)
            )
            return cur.lastrowid

    def checkin_instrument(self, checkout_id: int, date_returned: str, notes: str = ""):
        with self._connect() as conn:
            conn.execute(
                "UPDATE checkouts SET date_returned=?, notes=? WHERE id=?",
                (date_returned, notes, checkout_id)
            )

    def get_active_checkout(self, instrument_id: int):
        with self._connect() as conn:
            return conn.execute(
                """SELECT c.*, s.grade, s.phone, s.address, s.city, s.state, s.zip_code,
                          s.parent1_name, s.parent1_phone
                   FROM checkouts c
                   LEFT JOIN students s ON s.id = c.student_id
                   WHERE c.instrument_id=? AND c.date_returned IS NULL""",
                (instrument_id,)
            ).fetchone()

    def get_checkout_history(self, instrument_id: int):
        with self._connect() as conn:
            return conn.execute(
                """SELECT * FROM checkouts WHERE instrument_id=? ORDER BY date_assigned DESC""",
                (instrument_id,)
            ).fetchall()

    def mark_form_generated(self, checkout_id: int):
        with self._connect() as conn:
            conn.execute(
                "UPDATE checkouts SET form_generated=1 WHERE id=?", (checkout_id,)
            )

    def get_all_active_checkouts(self):
        with self._connect() as conn:
            return conn.execute(
                """SELECT c.*, i.description, i.category, i.barcode, i.district_no
                   FROM checkouts c
                   JOIN instruments i ON i.id = c.instrument_id
                   WHERE c.date_returned IS NULL
                   ORDER BY c.student_name"""
            ).fetchall()

    # ─── Repair CRUD ───────────────────────────────────────────────────────────

    def get_repairs(self, instrument_id: int):
        with self._connect() as conn:
            return conn.execute(
                "SELECT * FROM repairs WHERE instrument_id=? ORDER BY date_added DESC",
                (instrument_id,)
            ).fetchall()

    def add_repair(self, data: dict) -> int:
        cols = [
            "instrument_id", "priority", "date_added", "assigned_to",
            "date_repaired", "description", "location",
            "est_cost", "act_cost", "invoice_number", "notes"
        ]
        values = [data.get(c) for c in cols]
        placeholders = ",".join(["?"] * len(cols))
        col_str = ",".join(cols)
        with self._connect() as conn:
            cur = conn.execute(
                f"INSERT INTO repairs ({col_str}) VALUES ({placeholders})", values
            )
            return cur.lastrowid

    def update_repair(self, repair_id: int, data: dict):
        cols = [
            "priority", "date_added", "assigned_to", "date_repaired",
            "description", "location", "est_cost", "act_cost", "invoice_number", "notes"
        ]
        set_clause = ", ".join([f"{c}=?" for c in cols])
        values = [data.get(c) for c in cols] + [repair_id]
        with self._connect() as conn:
            conn.execute(f"UPDATE repairs SET {set_clause} WHERE id=?", values)

    def delete_repair(self, repair_id: int):
        with self._connect() as conn:
            conn.execute("DELETE FROM repairs WHERE id=?", (repair_id,))

    # ─── Stats / Misc ──────────────────────────────────────────────────────────

    def get_student_count_for_current_year(self) -> tuple[int, str]:
        """Return (count, school_year) for the most recent school year, or (0, '')."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT school_year FROM students WHERE school_year IS NOT NULL "
                "ORDER BY school_year DESC LIMIT 1"
            ).fetchone()
            if not row:
                return 0, ""
            year = row["school_year"]
            count = conn.execute(
                "SELECT COUNT(*) FROM students WHERE school_year=? AND is_active=1",
                (year,)
            ).fetchone()[0]
        return count, year

    def get_stats(self) -> dict:
        with self._connect() as conn:
            total = conn.execute(
                "SELECT COUNT(*) FROM instruments WHERE is_active=1"
            ).fetchone()[0]
            checked_out = conn.execute(
                """SELECT COUNT(*) FROM checkouts c
                   JOIN instruments i ON i.id=c.instrument_id
                   WHERE c.date_returned IS NULL AND i.is_active=1"""
            ).fetchone()[0]
            in_repair = conn.execute(
                """SELECT COUNT(DISTINCT r.instrument_id) FROM repairs r
                   WHERE r.date_repaired IS NULL"""
            ).fetchone()[0]
            sheet_music = conn.execute(
                "SELECT COUNT(*) FROM sheet_music WHERE is_active=1"
            ).fetchone()[0]
        return {
            "total": total,
            "checked_out": checked_out,
            "available": total - checked_out,
            "in_repair": in_repair,
            "sheet_music": sheet_music,
        }

    def import_instrument(self, data: dict) -> int:
        """Like add_instrument but skips duplicates by district_no/barcode/serial."""
        with self._connect() as conn:
            existing = None
            if data.get("district_no"):
                existing = conn.execute(
                    "SELECT id FROM instruments WHERE district_no=?", (data["district_no"],)
                ).fetchone()
            if not existing and data.get("barcode"):
                existing = conn.execute(
                    "SELECT id FROM instruments WHERE barcode=?", (data["barcode"],)
                ).fetchone()
            if existing:
                return existing["id"]
        return self.add_instrument(data)

    def import_checkout(self, instrument_id: int, student_id: int,
                        student_name: str, date_assigned: str, date_returned: str):
        """Insert a historical checkout, skipping exact duplicates."""
        with self._connect() as conn:
            existing = conn.execute(
                """SELECT id FROM checkouts
                   WHERE instrument_id=? AND student_name=? AND date_assigned=?""",
                (instrument_id, student_name, date_assigned)
            ).fetchone()
            if existing:
                return existing["id"]
            cur = conn.execute(
                """INSERT INTO checkouts
                   (instrument_id, student_id, student_name, date_assigned, date_returned)
                   VALUES (?, ?, ?, ?, ?)""",
                (instrument_id, student_id, student_name, date_assigned, date_returned)
            )
            return cur.lastrowid

    def relink_checkouts_to_students(self) -> dict:
        """
        For every checkout, try to match student_name to a student record.
        Prefers records with more complete data (grade, address, phone).

        Name matching is tolerant of middle initials: a checkout name
        "Kimora Eklund" will match a student record with
        first_name="Kimora E." because only the FIRST WORD of first_name
        is compared (e.g. "Kimora" == "Kimora").

        Returns {"updated": N, "unmatched": M}.
        """
        updated = 0
        unmatched_names = set()

        def _first_word(s: str) -> str:
            """Return the first space-separated word, stripped of trailing punctuation."""
            return (s or "").split()[0].rstrip(".,") if (s or "").split() else ""

        with self._connect() as conn:
            checkouts = conn.execute(
                "SELECT id, student_name, student_id FROM checkouts"
            ).fetchall()

            for co in checkouts:
                name_raw = (co["student_name"] or "").strip()
                if not name_raw:
                    continue

                # Parse "Last, First" or "First Last"
                if "," in name_raw:
                    parts = name_raw.split(",", 1)
                    last_name  = parts[0].strip()
                    first_name = parts[1].strip()
                else:
                    parts = name_raw.split()
                    first_name = parts[0] if parts else ""
                    last_name  = " ".join(parts[1:]) if len(parts) > 1 else ""

                if not first_name and not last_name:
                    continue

                first_lower = first_name.lower()
                last_lower  = last_name.lower()

                # Fetch all students with matching last name, scored by completeness
                candidates = conn.execute(
                    """SELECT id, first_name,
                              (CASE WHEN grade   IS NOT NULL AND grade   != '' THEN 1 ELSE 0 END +
                               CASE WHEN address IS NOT NULL AND address != '' THEN 1 ELSE 0 END +
                               CASE WHEN phone   IS NOT NULL AND phone   != '' THEN 1 ELSE 0 END) AS score
                       FROM students
                       WHERE LOWER(last_name)=?
                       ORDER BY score DESC, id ASC""",
                    (last_lower,)
                ).fetchall()

                # Match on first word of first_name to tolerate middle initials
                matches = [
                    c for c in candidates
                    if _first_word(c["first_name"]).lower() == first_lower
                ]

                # Broader fallback: first_name starts with the checkout first name
                if not matches:
                    matches = [
                        c for c in candidates
                        if c["first_name"].lower().startswith(first_lower)
                    ]

                if not matches:
                    unmatched_names.add(name_raw)
                    continue

                best_id = matches[0]["id"]
                if best_id != co["student_id"]:
                    conn.execute(
                        "UPDATE checkouts SET student_id=? WHERE id=?",
                        (best_id, co["id"])
                    )
                    updated += 1

        return {"updated": updated, "unmatched": len(unmatched_names)}

    def import_repair(self, data: dict) -> int:
        """Insert repair record, skipping exact duplicates."""
        with self._connect() as conn:
            existing = conn.execute(
                """SELECT id FROM repairs
                   WHERE instrument_id=? AND date_added=? AND description=?""",
                (data.get("instrument_id"), data.get("date_added"), data.get("description"))
            ).fetchone()
            if existing:
                return existing["id"]
            cols = [
                "instrument_id", "priority", "date_added", "assigned_to",
                "date_repaired", "description", "location",
                "est_cost", "act_cost", "invoice_number"
            ]
            values = [data.get(c) for c in cols]
            placeholders = ",".join(["?"] * len(cols))
            col_str = ",".join(cols)
            cur = conn.execute(
                f"INSERT INTO repairs ({col_str}) VALUES ({placeholders})", values
            )
            return cur.lastrowid

    # ─── Sheet Music CRUD ─────────────────────────────────────────────────────

    def get_all_sheet_music(self, include_inactive=False):
        with self._connect() as conn:
            if include_inactive:
                return conn.execute(
                    "SELECT * FROM sheet_music ORDER BY title"
                ).fetchall()
            return conn.execute(
                "SELECT * FROM sheet_music WHERE is_active=1 ORDER BY title"
            ).fetchall()

    def search_sheet_music(
        self,
        search: str = "",
        genre: str = "",
        location: str = "",
        voicing: str = "",
        order_col: str = "title",
        order_asc: bool = True,
        limit: int = 200,
        offset: int = 0,
    ):
        """Search sheet music with DB-side filtering and pagination.

        Returns (rows: list[dict], total_count: int).
        Includes last_played from performances via LEFT JOIN.
        """
        params = []
        where_parts = ["sm.is_active=1"]

        if search:
            tok = f"%{search}%"
            where_parts.append(
                "(sm.title LIKE ? OR sm.composer LIKE ? OR sm.arranger LIKE ? "
                "OR sm.genre LIKE ? OR sm.ensemble_type LIKE ? "
                "OR sm.key_signature LIKE ? OR sm.location LIKE ? "
                "OR COALESCE(sm.voicing,'') LIKE ? OR COALESCE(sm.language,'') LIKE ?)"
            )
            params.extend([tok] * 9)

        if genre:
            where_parts.append("sm.genre=?")
            params.append(genre)

        if voicing:
            where_parts.append("sm.voicing=?")
            params.append(voicing)

        if location:
            where_parts.append("sm.location=?")
            params.append(location)

        where_sql = " AND ".join(where_parts)

        valid_cols = {
            "title", "composer", "arranger", "ensemble_type", "genre",
            "difficulty", "key_signature", "time_signature", "location",
            "last_played", "file_type", "voicing", "language",
        }
        if order_col not in valid_cols:
            order_col = "title"
        direction = "ASC" if order_asc else "DESC"

        if order_col == "last_played":
            # NULLs always sorted last regardless of direction
            order_sql = (
                f"CASE WHEN lp.last_played IS NULL THEN 1 ELSE 0 END, "
                f"lp.last_played {direction}"
            )
        else:
            order_sql = f"sm.{order_col} {direction}"

        data_sql = f"""
            SELECT sm.*,
                   lp.last_played
            FROM sheet_music sm
            LEFT JOIN (
                SELECT music_id, MAX(performance_date) AS last_played
                FROM performances
                GROUP BY music_id
            ) lp ON lp.music_id = sm.id
            WHERE {where_sql}
            ORDER BY {order_sql}
            LIMIT ? OFFSET ?
        """
        count_sql = f"SELECT COUNT(*) FROM sheet_music sm WHERE {where_sql}"

        with self._connect() as conn:
            total = conn.execute(count_sql, params).fetchone()[0]
            rows = conn.execute(data_sql, params + [limit, offset]).fetchall()
        return [dict(r) for r in rows], total

    def get_distinct_genres(self) -> list:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT DISTINCT genre FROM sheet_music "
                "WHERE is_active=1 AND genre IS NOT NULL AND genre != '' "
                "ORDER BY genre"
            ).fetchall()
        return [r[0] for r in rows]

    def get_distinct_locations(self) -> list:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT DISTINCT location FROM sheet_music "
                "WHERE is_active=1 AND location IS NOT NULL AND location != '' "
                "ORDER BY location"
            ).fetchall()
        return [r[0] for r in rows]

    def get_distinct_voicings(self) -> list:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT DISTINCT voicing FROM sheet_music "
                "WHERE is_active=1 AND voicing IS NOT NULL AND voicing != '' "
                "ORDER BY voicing"
            ).fetchall()
        return [r[0] for r in rows]

    def get_distinct_languages(self) -> list:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT DISTINCT language FROM sheet_music "
                "WHERE is_active=1 AND language IS NOT NULL AND language != '' "
                "ORDER BY language"
            ).fetchall()
        return [r[0] for r in rows]

    def get_sheet_music(self, music_id: int):
        with self._connect() as conn:
            return conn.execute(
                "SELECT * FROM sheet_music WHERE id=?", (music_id,)
            ).fetchone()

    def add_sheet_music(self, data: dict) -> int:
        cols = [
            "title", "composer", "arranger", "genre", "ensemble_type",
            "difficulty", "file_path", "file_type", "num_pages", "notes",
            "key_signature", "time_signature", "location", "publisher", "source_file",
            "voicing", "language", "accompaniment",
        ]
        values = [data.get(c) for c in cols]
        placeholders = ",".join(["?"] * len(cols))
        col_str = ",".join(cols)
        with self._connect() as conn:
            cur = conn.execute(
                f"INSERT INTO sheet_music ({col_str}) VALUES ({placeholders})", values
            )
            return cur.lastrowid

    def update_sheet_music(self, music_id: int, data: dict):
        cols = [
            "title", "composer", "arranger", "genre", "ensemble_type",
            "difficulty", "file_path", "file_type", "num_pages", "notes", "is_active",
            "key_signature", "time_signature", "location", "publisher", "source_file",
            "voicing", "language", "accompaniment",
        ]
        set_clause = ", ".join([f"{c}=?" for c in cols])
        values = [data.get(c) for c in cols] + [music_id]
        with self._connect() as conn:
            conn.execute(
                f"UPDATE sheet_music SET {set_clause} WHERE id=?", values
            )

    def deactivate_sheet_music(self, music_id: int):
        with self._connect() as conn:
            conn.execute(
                "UPDATE sheet_music SET is_active=0 WHERE id=?", (music_id,)
            )

    def delete_sheet_music(self, music_id: int):
        """Hard-delete a sheet music record and its related jobs/performances."""
        with self._connect() as conn:
            conn.execute("DELETE FROM omr_jobs WHERE music_id=?", (music_id,))
            conn.execute("DELETE FROM performances WHERE music_id=?", (music_id,))
            conn.execute("DELETE FROM sheet_music WHERE id=?", (music_id,))

    # ─── Performances CRUD ────────────────────────────────────────────────────

    def add_performance(self, data: dict) -> int:
        cols = ["music_id", "performance_date", "ensemble", "event_name", "notes"]
        values = [data.get(c) for c in cols]
        placeholders = ",".join(["?"] * len(cols))
        col_str = ",".join(cols)
        with self._connect() as conn:
            cur = conn.execute(
                f"INSERT INTO performances ({col_str}) VALUES ({placeholders})", values
            )
            return cur.lastrowid

    def get_performances(self, music_id: int):
        with self._connect() as conn:
            return conn.execute(
                "SELECT * FROM performances WHERE music_id=? ORDER BY performance_date DESC",
                (music_id,)
            ).fetchall()

    def update_performance(self, performance_id: int, data: dict):
        cols = ["performance_date", "ensemble", "event_name", "notes"]
        set_clause = ", ".join([f"{c}=?" for c in cols])
        values = [data.get(c) for c in cols] + [performance_id]
        with self._connect() as conn:
            conn.execute(
                f"UPDATE performances SET {set_clause} WHERE id=?", values
            )

    def delete_performance(self, performance_id: int):
        with self._connect() as conn:
            conn.execute("DELETE FROM performances WHERE id=?", (performance_id,))

    # ─── OMR Jobs CRUD ────────────────────────────────────────────────────────

    def add_omr_job(self, data: dict) -> int:
        cols = ["music_id", "engine", "status", "started_at", "notes"]
        values = [data.get(c) for c in cols]
        placeholders = ",".join(["?"] * len(cols))
        col_str = ",".join(cols)
        with self._connect() as conn:
            cur = conn.execute(
                f"INSERT INTO omr_jobs ({col_str}) VALUES ({placeholders})", values
            )
            return cur.lastrowid

    def update_omr_job(self, job_id: int, data: dict):
        cols = ["status", "musicxml_path", "validation_errors",
                "corrections_applied", "completed_at", "notes"]
        set_clause = ", ".join([f"{c}=?" for c in cols])
        values = [data.get(c) for c in cols] + [job_id]
        with self._connect() as conn:
            conn.execute(f"UPDATE omr_jobs SET {set_clause} WHERE id=?", values)

    def get_omr_jobs(self, music_id: int):
        with self._connect() as conn:
            return conn.execute(
                "SELECT * FROM omr_jobs WHERE music_id=? ORDER BY started_at DESC",
                (music_id,)
            ).fetchall()

    def get_latest_omr_job(self, music_id: int):
        with self._connect() as conn:
            return conn.execute(
                "SELECT * FROM omr_jobs WHERE music_id=? ORDER BY id DESC LIMIT 1",
                (music_id,)
            ).fetchone()
