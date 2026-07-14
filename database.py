"""
database.py - SQLite database layer for Roka's Resonance
"""

import sqlite3
import shutil
import os
import re
from datetime import datetime


def school_name_variants(school_name: str):
    """Ways the teacher's school may be written in front of an ensemble name.
    'Chinook Middle School' -> ['Chinook Middle School', 'Chinook MS',
    'Chinook', ...], longest first so the most specific prefix wins."""
    s = (school_name or "").strip()
    if not s:
        return []
    variants = {s}
    base = re.sub(
        r"\s+(middle school|high school|elementary school|junior high school|"
        r"junior high|intermediate school|school|m\.?s\.?|h\.?s\.?)\.?$",
        "", s, flags=re.IGNORECASE).strip()
    if base:
        variants |= {base, f"{base} Middle School", f"{base} High School",
                     f"{base} MS", f"{base} HS"}
    return sorted((v for v in variants if v), key=len, reverse=True)


def strip_school_prefix(ensemble: str, school_name: str) -> str:
    """Fold the teacher's own school out of an ensemble name so joint-concert
    listings like 'Chinook Jazz 1' land in the existing 'Jazz 1' cohort."""
    e = (ensemble or "").strip()
    low = e.lower()
    for v in school_name_variants(school_name):
        vl = v.lower()
        if low.startswith(vl) and (len(e) == len(v) or not e[len(v)].isalnum()):
            rest = e[len(v):].lstrip(" -–—:")
            if rest:
                return rest
    return e


def _dict_factory(cursor, row):
    """Row factory that returns dicts supporting both d["col"] and d[0] access."""
    fields = [description[0] for description in cursor.description]
    d = dict(zip(fields, row))
    # Preserve numeric index access for fetchone()[0] patterns
    d["__values__"] = row
    return d


class _DictRow(dict):
    """A dict that also supports integer indexing for backward compat."""

    def __init__(self, cursor, row):
        fields = [desc[0] for desc in cursor.description]
        super().__init__(zip(fields, row))
        self._row = row

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._row[key]
        return super().__getitem__(key)

    def keys(self):
        return super().keys()


class Database:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._sync = None          # optional co-director SharedSync (off by default)
        self._init_db()

    def bind_sharing(self, sync):
        """Attach a shared_sync.SharedSync so shared-table writes route to the
        cloud.  Passing None (or a sync that isn't active) restores solo mode."""
        self._sync = sync

    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = _DictRow
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        if self._sync is not None and getattr(self._sync, "active", False):
            return self._sync.wrap(conn)
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
                    year_manufactured TEXT,
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
                    exclude_from_budget INTEGER DEFAULT 0,
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
                -- ═══════════════════════════════════════════════════════════
                -- LESSON PLANS MODULE TABLES
                -- ═══════════════════════════════════════════════════════════

                CREATE TABLE IF NOT EXISTS teaching_classes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    class_name TEXT NOT NULL,
                    ensemble_type TEXT,
                    grade_levels TEXT,
                    skill_level TEXT,
                    period TEXT,
                    days_of_week TEXT,
                    class_duration INTEGER DEFAULT 45,
                    student_count INTEGER DEFAULT 0,
                    method_book TEXT,
                    school_year TEXT,
                    room TEXT,
                    notes TEXT,
                    is_active INTEGER DEFAULT 1,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS concert_dates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    class_id INTEGER NOT NULL,
                    concert_date TEXT NOT NULL,
                    event_name TEXT,
                    location TEXT,
                    notes TEXT,
                    FOREIGN KEY (class_id) REFERENCES teaching_classes(id)
                );

                CREATE TABLE IF NOT EXISTS curriculum_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    class_id INTEGER NOT NULL,
                    item_date TEXT NOT NULL,
                    summary TEXT,
                    activity_type TEXT DEFAULT 'skill_building',
                    unit_name TEXT,
                    is_locked INTEGER DEFAULT 0,
                    sort_order INTEGER DEFAULT 0,
                    notes TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (class_id) REFERENCES teaching_classes(id)
                );

                CREATE TABLE IF NOT EXISTS lesson_plans (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    curriculum_item_id INTEGER NOT NULL,
                    objectives TEXT,
                    standards TEXT,
                    warmup_text TEXT,
                    warmup_template_id INTEGER,
                    assessment_type TEXT,
                    assessment_details TEXT,
                    differentiation_advanced TEXT,
                    differentiation_struggling TEXT,
                    differentiation_iep TEXT,
                    reflection_text TEXT,
                    reflection_rating TEXT,
                    status TEXT DEFAULT 'draft',
                    total_minutes_planned INTEGER DEFAULT 0,
                    notes TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (curriculum_item_id) REFERENCES curriculum_items(id),
                    FOREIGN KEY (warmup_template_id) REFERENCES lesson_templates(id)
                );

                CREATE TABLE IF NOT EXISTS lesson_blocks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    lesson_plan_id INTEGER NOT NULL,
                    block_type TEXT NOT NULL,
                    title TEXT,
                    description TEXT,
                    duration_minutes INTEGER DEFAULT 5,
                    sort_order INTEGER DEFAULT 0,
                    music_piece_id INTEGER,
                    measure_start INTEGER,
                    measure_end INTEGER,
                    technique_focus TEXT,
                    difficulty_level TEXT,
                    grouping TEXT,
                    notes TEXT,
                    FOREIGN KEY (lesson_plan_id) REFERENCES lesson_plans(id),
                    FOREIGN KEY (music_piece_id) REFERENCES sheet_music(id)
                );

                CREATE TABLE IF NOT EXISTS resources (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    resource_type TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    description TEXT,
                    url_or_path TEXT,
                    file_data BLOB,
                    method_book_title TEXT,
                    method_book_pages TEXT,
                    music_id INTEGER,
                    notes TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (music_id) REFERENCES sheet_music(id)
                );

                CREATE TABLE IF NOT EXISTS resource_tags (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    resource_id INTEGER NOT NULL,
                    tag TEXT NOT NULL,
                    FOREIGN KEY (resource_id) REFERENCES resources(id)
                );

                CREATE TABLE IF NOT EXISTS lesson_plan_resources (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    lesson_plan_id INTEGER NOT NULL,
                    resource_id INTEGER NOT NULL,
                    block_id INTEGER,
                    UNIQUE(lesson_plan_id, resource_id),
                    FOREIGN KEY (lesson_plan_id) REFERENCES lesson_plans(id),
                    FOREIGN KEY (resource_id) REFERENCES resources(id),
                    FOREIGN KEY (block_id) REFERENCES lesson_blocks(id)
                );

                CREATE TABLE IF NOT EXISTS lesson_templates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    template_type TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    description TEXT,
                    content_json TEXT,
                    ensemble_type TEXT,
                    notes TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS onenote_sync (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    class_id INTEGER NOT NULL,
                    notebook_id TEXT,
                    notebook_name TEXT,
                    section_id TEXT NOT NULL,
                    section_name TEXT,
                    start_date TEXT NOT NULL,
                    end_date TEXT NOT NULL,
                    sync_enabled INTEGER DEFAULT 0,
                    last_sync_at TEXT,
                    sync_direction TEXT DEFAULT 'app_to_onenote',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (class_id) REFERENCES teaching_classes(id)
                );
            """)
            # ── Lesson Plans indexes ──
            for idx_sql in [
                "CREATE INDEX IF NOT EXISTS idx_ci_class_date ON curriculum_items(class_id, item_date)",
                "CREATE INDEX IF NOT EXISTS idx_lp_curriculum ON lesson_plans(curriculum_item_id)",
                "CREATE INDEX IF NOT EXISTS idx_lb_plan ON lesson_blocks(lesson_plan_id)",
                "CREATE INDEX IF NOT EXISTS idx_rt_resource ON resource_tags(resource_id)",
                "CREATE INDEX IF NOT EXISTS idx_rt_tag ON resource_tags(tag)",
                "CREATE INDEX IF NOT EXISTS idx_lpr_plan ON lesson_plan_resources(lesson_plan_id)",
                "CREATE INDEX IF NOT EXISTS idx_cd_class ON concert_dates(class_id)",
            ]:
                try:
                    conn.execute(idx_sql)
                    conn.commit()
                except Exception:
                    pass
            # Migrate: add due_date column if it doesn't exist yet
            try:
                conn.execute("ALTER TABLE checkouts ADD COLUMN due_date TEXT")
                conn.commit()
            except Exception:
                pass  # Column already exists
            # Migrate: add year_manufactured (serial-dated PRODUCTION year, kept
            # separate from year_purchased) to instruments
            try:
                conn.execute("ALTER TABLE instruments ADD COLUMN year_manufactured TEXT")
                conn.commit()
            except Exception:
                pass  # Column already exists
            # Migrate: flag imported/archival repairs so they stay in the repair
            # log but don't count as current budget expenses.
            try:
                conn.execute("ALTER TABLE repairs ADD COLUMN exclude_from_budget INTEGER DEFAULT 0")
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
            # Migrate: loans table — an instrument loaned out to another school.
            # While a loan is open (date_returned NULL) the instrument is "On
            # Loan" and unavailable for local checkout.
            try:
                conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS loans (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        instrument_id INTEGER NOT NULL,
                        school TEXT,
                        contact_name TEXT,
                        contact_email TEXT,
                        contact_phone TEXT,
                        date_out TEXT,
                        date_due TEXT,
                        date_returned TEXT,
                        notes TEXT,
                        FOREIGN KEY (instrument_id) REFERENCES instruments(id)
                    );
                    CREATE INDEX IF NOT EXISTS idx_loans_instrument
                        ON loans(instrument_id);
                    """
                )
                conn.commit()
            except Exception:
                pass
            # Migrate: budgeting + student-fee tables.
            try:
                conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS budget_categories (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT NOT NULL,
                        kind TEXT NOT NULL        -- 'expense' | 'income'
                    );
                    CREATE TABLE IF NOT EXISTS budget_transactions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        txn_date TEXT,
                        description TEXT,
                        category TEXT,
                        kind TEXT,                -- 'expense' | 'income'
                        amount REAL DEFAULT 0,
                        funding_source TEXT,      -- Building | ASB | Boosters | Other
                        student_id INTEGER,
                        notes TEXT,
                        created_at TEXT DEFAULT CURRENT_TIMESTAMP
                    );
                    CREATE TABLE IF NOT EXISTS fee_types (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT NOT NULL,
                        default_amount REAL DEFAULT 0
                    );
                    CREATE TABLE IF NOT EXISTS student_fees (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        student_id INTEGER,
                        fee_type TEXT,
                        school_year TEXT,
                        amount REAL DEFAULT 0,
                        status TEXT DEFAULT 'unpaid',   -- unpaid | paid | waived
                        date_paid TEXT,
                        notes TEXT,
                        FOREIGN KEY (student_id) REFERENCES students(id)
                    );
                    CREATE INDEX IF NOT EXISTS idx_txn_date ON budget_transactions(txn_date);
                    CREATE INDEX IF NOT EXISTS idx_sfee_student ON student_fees(student_id);
                    """
                )
                conn.commit()
            except Exception:
                pass
            # Seed default budget categories + fee types once (only if empty).
            try:
                if conn.execute("SELECT COUNT(*) FROM budget_categories").fetchone()[0] == 0:
                    for name, kind in [
                        ("Instrument Repair", "expense"),
                        ("Instrument Supplies", "expense"),
                        ("Sheet Music", "expense"),
                        ("Office Supplies", "expense"),
                        ("Field Trip", "expense"),
                        ("Guest Artist / Clinician", "expense"),
                        ("Festival / Registration", "expense"),
                        ("Uniforms / Attire", "expense"),
                        ("Fundraiser", "income"),
                        ("Ticket Sales", "income"),
                        ("Donations", "income"),
                        ("Instrument Rental Fees", "income"),
                        ("Student Fees", "income"),
                        ("Other", "expense"),
                        ("Other", "income"),
                    ]:
                        conn.execute("INSERT INTO budget_categories (name, kind) VALUES (?, ?)",
                                     (name, kind))
                if conn.execute("SELECT COUNT(*) FROM fee_types").fetchone()[0] == 0:
                    # Only BSD-wide standards are seeded.  Uniform/attire fees vary
                    # by program (HS marching uniforms, choir robes, a MS polo, …),
                    # so teachers add their own rather than getting Chinook's polo.
                    for name, amt in [
                        ("Instrument Rental (School Year)", 75.0),  # BSD standard
                        ("Instrument Rental (Summer)", 20.0),       # BSD standard
                    ]:
                        conn.execute("INSERT INTO fee_types (name, default_amount) VALUES (?, ?)",
                                     (name, amt))
                conn.commit()
            except Exception:
                pass
            # Correct the earlier placeholder seed amounts to the real BSD/Chinook
            # values — only where still at the old default (never clobber edits).
            try:
                conn.execute("UPDATE fee_types SET default_amount=15 "
                             "WHERE name='Polo Shirt' AND default_amount=25")
                old = conn.execute("SELECT id FROM fee_types "
                                   "WHERE name='Instrument Rental' AND default_amount=40").fetchone()
                if old:
                    conn.execute("UPDATE fee_types SET name='Instrument Rental (School Year)', "
                                 "default_amount=75 WHERE id=?", (old["id"],))
                    if not conn.execute("SELECT 1 FROM fee_types "
                                        "WHERE name='Instrument Rental (Summer)'").fetchone():
                        conn.execute("INSERT INTO fee_types (name, default_amount) "
                                     "VALUES ('Instrument Rental (Summer)', 20)")
                conn.commit()
            except Exception:
                pass
            # Migrate: student ensemble / class-period / instrument fields.
            # Stored as comma-separated strings (e.g. "Advanced Band,Jazz 1"
            # and "1,3,5") so a student can belong to several at once.
            # honors / all_state: program-recognition flags ("♪ = Honors in
            # Band", Jr. All-State) shown next to names on concert programs.
            # jazz_instrument: what they play in jazz band when it differs
            # from their concert instrument (e.g. Horn player on Guitar).
            # provisional: an "incoming" student pre-loaded from a feeder
            # school's handoff (with instruments) before the official roster
            # exists.  Shown grayed/tagged; contactable; confirmed or removed
            # when the official class list is imported.
            for col in ("ensembles TEXT", "class_periods TEXT",
                        "primary_instrument TEXT", "secondary_instrument TEXT",
                        "preferred_name TEXT",
                        "honors INTEGER DEFAULT 0", "all_state INTEGER DEFAULT 0",
                        "jazz_instrument TEXT", "provisional INTEGER DEFAULT 0"):
                try:
                    conn.execute(f"ALTER TABLE students ADD COLUMN {col}")
                    conn.commit()
                except Exception:
                    pass
            # Migrate: shorter saxophone names (unambiguous 1:1 renames).
            # "Baritone/Euphonium" is left alone — it split into four clef-
            # specific options and we can't guess which one a student plays.
            try:
                for old, new in (("Alto Saxophone", "Alto Sax"),
                                 ("Tenor Saxophone", "Tenor Sax"),
                                 ("Baritone Saxophone", "Bari Sax")):
                    conn.execute("UPDATE students SET primary_instrument=? "
                                 "WHERE primary_instrument=?", (new, old))
                    conn.execute("UPDATE students SET secondary_instrument=? "
                                 "WHERE secondary_instrument=?", (new, old))
                conn.commit()
            except Exception:
                pass
            # Migrate: support free-text "random item" checkouts.
            # Adds item_description and makes instrument_id nullable.  SQLite
            # can't drop a NOT NULL constraint in place, so rebuild the table.
            try:
                ck_cols = [r["name"] for r in
                           conn.execute("PRAGMA table_info(checkouts)").fetchall()]
                if "item_description" not in ck_cols:
                    conn.executescript(
                        """
                        CREATE TABLE checkouts_new (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            instrument_id INTEGER,
                            student_id INTEGER,
                            student_name TEXT,
                            date_assigned TEXT,
                            date_returned TEXT,
                            due_date TEXT,
                            notes TEXT,
                            item_description TEXT,
                            form_generated INTEGER DEFAULT 0,
                            FOREIGN KEY (instrument_id) REFERENCES instruments(id),
                            FOREIGN KEY (student_id) REFERENCES students(id)
                        );
                        INSERT INTO checkouts_new
                            (id, instrument_id, student_id, student_name, date_assigned,
                             date_returned, due_date, notes, form_generated)
                            SELECT id, instrument_id, student_id, student_name, date_assigned,
                                   date_returned, due_date, notes, form_generated
                            FROM checkouts;
                        DROP TABLE checkouts;
                        ALTER TABLE checkouts_new RENAME TO checkouts;
                        """
                    )
                    conn.commit()
            except Exception:
                pass

    # ─── Backup ────────────────────────────────────────────────────────────────

    def _companion_files(self):
        """Everything else in the profile folder that holds user data and
        must ride along in backups: the per-year Teacher Tools databases
        (seating charts, percussion rotations, concerts, field trips) and
        settings.json."""
        base = os.path.dirname(os.path.abspath(self.db_path))
        out = []
        try:
            for fn in os.listdir(base):
                if fn.startswith("lesson_plans_") and fn.endswith(".db"):
                    out.append(os.path.join(base, fn))
        except OSError:
            pass
        settings = os.path.join(base, "settings.json")
        if os.path.exists(settings):
            out.append(settings)
        return out

    @staticmethod
    def _checkpoint_sqlite(path):
        """Flush a WAL journal into the main file so the copy is complete."""
        try:
            conn = sqlite3.connect(path)
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            conn.close()
        except Exception:
            pass

    @staticmethod
    def _rotate_backups(dir_, max_backups):
        """Keep the newest max_backups per file family — a family is the
        name before the _YYYYMMDD_HHMMSS timestamp, so the main database,
        each year's Teacher Tools file, and settings rotate independently."""
        try:
            files = os.listdir(dir_)
        except OSError:
            return
        groups = {}
        for f in files:
            m = re.match(r"(.+)_\d{8}_\d{6}(\.\w+)$", f)
            if not m:
                continue
            groups.setdefault(m.group(1) + m.group(2), []).append(f)
        for fam_files in groups.values():
            for old in sorted(fam_files, reverse=True)[max_backups:]:
                try:
                    os.remove(os.path.join(dir_, old))
                except OSError:
                    pass

    def _backup_all_to(self, dest_dir: str, max_backups: int) -> str:
        """Copy the main database plus all companion files (per-year Teacher
        Tools DBs, settings.json) into dest_dir with a shared timestamp."""
        os.makedirs(dest_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Flush WAL to main db before copying
        try:
            with self._connect() as conn:
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except Exception:
            pass
        backup_path = os.path.join(dest_dir, f"rokas_resonance_{timestamp}.db")
        shutil.copy2(self.db_path, backup_path)

        for path in self._companion_files():
            try:
                if path.endswith(".db"):
                    self._checkpoint_sqlite(path)
                stem, ext = os.path.splitext(os.path.basename(path))
                shutil.copy2(path, os.path.join(dest_dir,
                                                f"{stem}_{timestamp}{ext}"))
            except OSError:
                pass    # one bad companion shouldn't sink the whole backup

        self._rotate_backups(dest_dir, max_backups)
        return backup_path

    def backup(self, max_backups: int = 10) -> str | None:
        """
        Copy the database — plus the per-year Teacher Tools databases and
        settings.json — to timestamped backups in a 'backups' folder next to
        the database. Keeps the most recent *max_backups* copies of each.
        Returns the main backup path, or None if the db file doesn't exist.
        """
        if not os.path.exists(self.db_path):
            return None
        backup_dir = os.path.join(os.path.dirname(self.db_path), "backups")
        return self._backup_all_to(backup_dir, max_backups)

    def backup_to_external(self, external_dir: str, profile_name: str = "", max_backups: int = 30) -> str:
        """
        Copy the database — plus the per-year Teacher Tools databases and
        settings.json — to a user-specified external folder (e.g. OneDrive,
        network drive).  Files are stored in a subfolder named after the
        profile so multiple profiles don't overwrite each other.  Keeps the
        most recent *max_backups* copies of each file.
        """
        if not os.path.exists(self.db_path):
            raise FileNotFoundError(f"Database not found: {self.db_path}")
        dest_dir = os.path.join(external_dir, profile_name) if profile_name else external_dir
        return self._backup_all_to(dest_dir, max_backups)

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
            "year_purchased", "year_manufactured", "po_number", "last_service", "amount_paid", "est_value",
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
            "year_purchased", "year_manufactured", "po_number", "last_service", "amount_paid", "est_value",
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
        """Return instruments with computed status, handling several active
        checkouts per instrument and out-on-loan instruments.  Uses scalar
        subqueries so an instrument is never duplicated in the result."""
        active_filter = "" if include_inactive else "AND i.is_active=1"
        sql = f"""
            SELECT
                i.*,
                (SELECT COUNT(*) FROM checkouts c
                    WHERE c.instrument_id = i.id AND c.date_returned IS NULL) AS active_count,
                (SELECT COUNT(*) FROM loans l
                    WHERE l.instrument_id = i.id AND l.date_returned IS NULL) AS loan_count,
                (SELECT c.student_name FROM checkouts c
                    WHERE c.instrument_id = i.id AND c.date_returned IS NULL
                    ORDER BY c.id LIMIT 1) AS first_checkout_name,
                (SELECT c.date_assigned FROM checkouts c
                    WHERE c.instrument_id = i.id AND c.date_returned IS NULL
                    ORDER BY c.id LIMIT 1) AS checkout_date,
                (SELECT l.school FROM loans l
                    WHERE l.instrument_id = i.id AND l.date_returned IS NULL
                    ORDER BY l.id LIMIT 1) AS loan_school
            FROM instruments i
            WHERE 1=1 {active_filter}
            ORDER BY i.category, i.description
        """
        with self._connect() as conn:
            rows = conn.execute(sql).fetchall()

        out = []
        for r in rows:
            d = dict(r)
            ac = d.get("active_count") or 0
            lc = d.get("loan_count") or 0
            if lc:
                d["status"] = "On Loan"
                d["checked_out_to"] = f"🏫 {d.get('loan_school') or 'Another school'}"
            elif ac:
                d["status"] = "Checked Out"
                name = d.get("first_checkout_name") or ""
                d["checked_out_to"] = name + (f"  (+{ac - 1} more)" if ac > 1 else "")
            else:
                d["status"] = "Available"
                d["checked_out_to"] = ""
            out.append(d)
        return out

    def get_active_checkouts_for_instrument(self, instrument_id):
        """All open checkouts for one instrument (may be several)."""
        with self._connect() as conn:
            return conn.execute(
                """SELECT c.*, s.grade, s.phone, s.parent1_name
                   FROM checkouts c
                   LEFT JOIN students s ON s.id = c.student_id
                   WHERE c.instrument_id=? AND c.date_returned IS NULL
                   ORDER BY c.id""",
                (instrument_id,)
            ).fetchall()

    # ─── Loans (to another school) ──────────────────────────────────────────────

    def add_loan(self, data: dict) -> int:
        cols = ["instrument_id", "school", "contact_name", "contact_email",
                "contact_phone", "date_out", "date_due", "notes"]
        values = [data.get(c) for c in cols]
        placeholders = ",".join(["?"] * len(cols))
        with self._connect() as conn:
            cur = conn.execute(
                f"INSERT INTO loans ({','.join(cols)}) VALUES ({placeholders})", values
            )
            return cur.lastrowid

    def get_active_loan(self, instrument_id: int):
        with self._connect() as conn:
            return conn.execute(
                """SELECT * FROM loans
                   WHERE instrument_id=? AND date_returned IS NULL
                   ORDER BY id DESC LIMIT 1""",
                (instrument_id,)
            ).fetchone()

    def get_all_active_loans(self):
        with self._connect() as conn:
            return conn.execute(
                """SELECT l.*, i.description, i.category, i.barcode, i.district_no,
                          i.serial_no
                   FROM loans l
                   JOIN instruments i ON i.id = l.instrument_id
                   WHERE l.date_returned IS NULL
                   ORDER BY l.school, i.description"""
            ).fetchall()

    def return_loan(self, loan_id: int, date_returned: str):
        with self._connect() as conn:
            conn.execute("UPDATE loans SET date_returned=? WHERE id=?",
                         (date_returned, loan_id))

    def get_loan_history(self, instrument_id: int):
        with self._connect() as conn:
            return conn.execute(
                "SELECT * FROM loans WHERE instrument_id=? ORDER BY date_out DESC",
                (instrument_id,)
            ).fetchall()

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

    def get_current_roster(self):
        """Current, active members only — for every dropdown/autocomplete in the
        app.  Uses the most recent enrolled school year (so students who left or
        aged out, i.e. are only on prior-year rosters, are excluded), keeps only
        active students, and de-duplicates by name (preferring the record that
        has a district student_id)."""
        years = self.get_school_years()
        year = years[0] if years else self.current_school_year()
        rows = self.get_all_students(school_year=year, include_inactive=False)
        seen = {}
        for s in rows:
            has_sid = bool((s["student_id"] or "").strip())
            first = (s["first_name"] or "")
            fw = first.split()[0].lower() if first else ""
            key = f"{fw}|{(s['last_name'] or '').lower()}"
            if key not in seen or (has_sid and not seen[key][1]):
                seen[key] = (dict(s), has_sid)
        return [s for s, _ in seen.values()]

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

    # ─── Provisional / "incoming" students ──────────────────────────────────────

    def get_provisional_students(self, school_year=None):
        """Active students still flagged provisional (pre-loaded from a feeder
        handoff, not yet confirmed by an official roster import)."""
        sql = ("SELECT * FROM students WHERE COALESCE(provisional,0)=1 "
               "AND COALESCE(is_active,1)=1")
        args = ()
        if school_year:
            sql += " AND school_year=?"
            args = (school_year,)
        sql += " ORDER BY last_name, first_name"
        with self._connect() as conn:
            return conn.execute(sql, args).fetchall()

    def clear_provisional(self, ids):
        """Confirm students (drop the provisional flag) once they appear on the
        official roster."""
        with self._connect() as conn:
            for i in ids:
                conn.execute("UPDATE students SET provisional=0 WHERE id=?", (i,))

    def set_students_active(self, ids, active=1):
        with self._connect() as conn:
            for i in ids:
                conn.execute("UPDATE students SET is_active=? WHERE id=?",
                             (1 if active else 0, i))

    def add_student(self, data: dict) -> int:
        cols = [
            "school_year", "first_name", "last_name", "student_id", "grade",
            "gender", "birth_date", "address", "city", "state", "zip_code",
            "phone", "student_email", "parent1_name", "parent1_relation",
            "parent1_phone", "parent1_email", "parent2_name", "parent2_relation",
            "parent2_phone", "parent2_email", "notes",
            "ensembles", "class_periods", "primary_instrument", "secondary_instrument",
            "preferred_name", "jazz_instrument", "provisional"
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
            "parent2_phone", "parent2_email", "notes",
            "ensembles", "class_periods", "primary_instrument", "secondary_instrument",
            "preferred_name", "jazz_instrument", "is_active", "provisional"
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

    def archive_school_year(self, school_year: str) -> int:
        """Close out a school year: mark its active students inactive.  Their
        records stay in the database and can be reactivated (or picked up by
        the New School Year class-list import).  Honors / Jr. All-State marks
        are cleared — they must be earned again each year.  Returns the
        count archived."""
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE students SET is_active=0, honors=0, all_state=0 "
                "WHERE school_year=? AND is_active=1", (school_year,))
            return cur.rowcount

    def set_student_honors(self, student_id: int, honors=None, all_state=None):
        """Set the concert-program recognition flags.  Deliberately separate
        from update_student so ordinary edits can't wipe them."""
        sets, vals = [], []
        if honors is not None:
            sets.append("honors=?"); vals.append(1 if honors else 0)
        if all_state is not None:
            sets.append("all_state=?"); vals.append(1 if all_state else 0)
        if not sets:
            return
        vals.append(student_id)
        with self._connect() as conn:
            conn.execute(f"UPDATE students SET {', '.join(sets)} WHERE id=?", vals)

    # ─── Bulk ensemble / period / instrument assignment ─────────────────────────

    @staticmethod
    def _csv_merge(existing: str, values, replace: bool) -> str:
        """Merge/replace a comma-separated multi-value field, order-preserving,
        de-duplicated.  `values` is a list of strings to set or add."""
        wanted = [str(v).strip() for v in values if str(v).strip()]
        if replace:
            out = []
            for v in wanted:
                if v not in out:
                    out.append(v)
            return ",".join(out)
        out = [p.strip() for p in (existing or "").split(",") if p.strip()]
        for v in wanted:
            if v not in out:
                out.append(v)
        return ",".join(out)

    def bulk_set_student_multi(self, student_ids, field: str, values, replace: bool = False):
        """Add (or replace) values in a comma-separated field (ensembles or
        class_periods) for many students at once."""
        if field not in ("ensembles", "class_periods"):
            raise ValueError(f"Unsupported multi-value field: {field}")
        with self._connect() as conn:
            for sid in student_ids:
                row = conn.execute(
                    f"SELECT {field} FROM students WHERE id=?", (sid,)
                ).fetchone()
                current = row[field] if row else ""
                merged = self._csv_merge(current, values, replace)
                conn.execute(
                    f"UPDATE students SET {field}=? WHERE id=?", (merged, sid)
                )

    def bulk_clear_student_multi(self, student_ids, field: str):
        if field not in ("ensembles", "class_periods"):
            raise ValueError(f"Unsupported multi-value field: {field}")
        with self._connect() as conn:
            for sid in student_ids:
                conn.execute(f"UPDATE students SET {field}='' WHERE id=?", (sid,))

    def carry_over_instruments(self, student_ids) -> int:
        """For each given student, if their instrument is blank, copy it from the
        same person's most recent prior record (matched by district student_id,
        else by name).  Students rarely change instruments year to year.
        Returns how many were filled in."""
        filled = 0
        with self._connect() as conn:
            for sid in student_ids:
                cur = conn.execute(
                    """SELECT id, student_id, first_name, last_name,
                              primary_instrument, secondary_instrument
                       FROM students WHERE id=?""", (sid,)
                ).fetchone()
                if not cur:
                    continue
                if (cur["primary_instrument"] or "").strip():
                    continue  # never overwrite an instrument that's already set
                sid_str = (cur["student_id"] or "").strip()
                prior = conn.execute(
                    """SELECT primary_instrument, secondary_instrument
                       FROM students
                       WHERE id != ?
                         AND ( (?!='' AND student_id=?)
                               OR (LOWER(first_name)=LOWER(?) AND LOWER(last_name)=LOWER(?)) )
                         AND primary_instrument IS NOT NULL
                         AND TRIM(primary_instrument) != ''
                       ORDER BY school_year DESC, id DESC LIMIT 1""",
                    (cur["id"], sid_str, sid_str,
                     cur["first_name"] or "", cur["last_name"] or "")
                ).fetchone()
                if prior:
                    conn.execute(
                        """UPDATE students
                           SET primary_instrument=?, secondary_instrument=?
                           WHERE id=?""",
                        (prior["primary_instrument"], prior["secondary_instrument"], sid)
                    )
                    filled += 1
        return filled

    def update_student_instruments(self, student_id: int, primary=None, secondary=None):
        """Set instrument fields only (used by the HS instrument-update import)."""
        sets, params = [], []
        if primary is not None:
            sets.append("primary_instrument=?"); params.append(primary)
        if secondary is not None:
            sets.append("secondary_instrument=?"); params.append(secondary)
        if not sets:
            return
        params.append(student_id)
        with self._connect() as conn:
            conn.execute(f"UPDATE students SET {', '.join(sets)} WHERE id=?", params)

    def bulk_set_student_field(self, student_ids, field: str, value):
        """Set a single-value field (primary_instrument / secondary_instrument)
        on many students at once."""
        if field not in ("primary_instrument", "secondary_instrument"):
            raise ValueError(f"Unsupported field: {field}")
        with self._connect() as conn:
            for sid in student_ids:
                conn.execute(
                    f"UPDATE students SET {field}=? WHERE id=?", (value, sid)
                )

    def get_students_for_email(self, school_year=None, ensemble=None, period=None,
                               instrument=None, include_inactive=False):
        """Return active student rows matching the given filters.  Multi-value
        fields (ensembles, class_periods) are matched by membership."""
        sql = "SELECT * FROM students WHERE 1=1"
        params = []
        if not include_inactive:
            sql += " AND is_active=1"
        if school_year:
            sql += " AND school_year=?"
            params.append(school_year)
        sql += " ORDER BY last_name, first_name"
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()

        def _has(csv_val, target):
            return target in [p.strip() for p in (csv_val or "").split(",") if p.strip()]

        out = []
        for r in rows:
            if ensemble and not _has(r["ensembles"], ensemble):
                continue
            if period and not _has(r["class_periods"], str(period)):
                continue
            if instrument:
                prim = (r["primary_instrument"] or "").strip()
                sec = (r["secondary_instrument"] or "").strip()
                if instrument not in (prim, sec):
                    continue
            out.append(r)
        return out

    # ─── Checkout CRUD ─────────────────────────────────────────────────────────

    def checkout_instrument(self, instrument_id: int, student_id: int,
                            student_name: str, date_assigned: str, notes: str = "",
                            due_date: str = "", rental_type: str = "school_year") -> int:
        with self._connect() as conn:
            cur = conn.execute(
                """INSERT INTO checkouts
                   (instrument_id, student_id, student_name, date_assigned, notes, due_date)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (instrument_id, student_id, student_name, date_assigned, notes, due_date)
            )
            checkout_id = cur.lastrowid
        # Auto-add the instrument rental fee for this student so it shows up
        # under Budget ▸ Student Fees (dedup keeps it to one per year; waive or
        # remove it there if the instrument is the student's own).  rental_type
        # is "school_year" ($75 default) or "summer" ($20 default).
        if student_id:
            try:
                self._auto_add_rental_fee(student_id, date_assigned, rental_type)
            except Exception:
                pass
        return checkout_id

    def _auto_add_rental_fee(self, student_id: int, date_assigned: str,
                             rental_type: str = "school_year"):
        year = self.academic_year_of(date_assigned)
        if rental_type == "summer":
            name, amount, want = "Instrument Rental (Summer)", 20.0, "summer"
        else:
            name, amount, want = "Instrument Rental (School Year)", 75.0, "school year"
        for t in self.get_fee_types():
            n = t["name"] or ""
            if n.lower().startswith("instrument rental") and want in n.lower():
                name, amount = n, float(t["default_amount"] or amount)
                break
        self.ensure_student_fee(student_id, name, year, amount)

    @staticmethod
    def academic_year_of(date_str: str) -> str:
        """Academic year label (Aug–Jul boundary) for a date."""
        d = (date_str or "")[:10]
        try:
            y, m = int(d[:4]), int(d[5:7])
        except (ValueError, IndexError):
            from datetime import datetime as _dt
            t = _dt.today(); y, m = t.year, t.month
        start = y if m >= 8 else y - 1
        return f"{start}-{start + 1}"

    def checkout_item(self, student_id, student_name: str, item_description: str,
                      date_assigned: str, due_date: str = "", notes: str = "") -> int:
        """Check out a free-text item (mute, lyre, method book, etc.) that has no
        inventory record.  student_id may be None for a non-student borrower
        (para, another teacher); student_name then holds whatever was typed."""
        with self._connect() as conn:
            cur = conn.execute(
                """INSERT INTO checkouts
                   (instrument_id, student_id, student_name, item_description,
                    date_assigned, notes, due_date)
                   VALUES (NULL, ?, ?, ?, ?, ?, ?)""",
                (student_id, student_name, item_description, date_assigned, notes, due_date)
            )
            return cur.lastrowid

    def import_open_checkout(self, instrument_id: int, student_id, student_name: str,
                             date_assigned: str) -> int:
        """Recreate a current (open) loan during a one-time data import, WITHOUT
        the auto rental fee (importing existing state shouldn't invent new
        charges).  Skips instruments that already have an open checkout so
        re-running is safe."""
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT id FROM checkouts WHERE instrument_id=? AND "
                "(date_returned IS NULL OR TRIM(date_returned)='')",
                (instrument_id,)).fetchone()
            if existing:
                return existing["id"]
            cur = conn.execute(
                "INSERT INTO checkouts (instrument_id, student_id, student_name, "
                "date_assigned) VALUES (?, ?, ?, ?)",
                (instrument_id, student_id, student_name, date_assigned))
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
        # LEFT JOIN so free-text "random item" checkouts (instrument_id IS NULL)
        # still appear.  For those rows, fall back to the typed item_description.
        with self._connect() as conn:
            return conn.execute(
                """SELECT c.*,
                          COALESCE(i.description, c.item_description) AS description,
                          COALESCE(i.category,
                                   CASE WHEN c.item_description IS NOT NULL
                                        AND c.item_description != ''
                                        THEN 'Other Item' END) AS category,
                          i.barcode, i.district_no
                   FROM checkouts c
                   LEFT JOIN instruments i ON i.id = c.instrument_id
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

    def find_duplicate_repair(self, instrument_id, invoice_number,
                              description=None):
        """A repair id that looks like a duplicate of one being entered — same
        instrument and same (non-blank) invoice number — so re-scanning an
        invoice doesn't create duplicate records.  When several share that
        invoice number, an optional matching description picks the closest.
        Returns the repair id, or None."""
        inv = (invoice_number or "").strip()
        if not instrument_id or not inv:
            return None
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, description FROM repairs WHERE instrument_id=? "
                "AND TRIM(IFNULL(invoice_number,''))=?", (instrument_id, inv)
            ).fetchall()
        if not rows:
            return None
        if description:
            d = description.strip().lower()
            for r in rows:
                if (r["description"] or "").strip().lower() == d:
                    return r["id"]
        return rows[0]["id"]

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

    def get_pending_repairs(self):
        """All not-yet-completed repairs (date_repaired blank), joined with the
        instrument, for the technician printout / needs-repair export."""
        with self._connect() as conn:
            return conn.execute(
                """SELECT r.*, i.category, i.description AS instrument_desc,
                          i.brand, i.model, i.serial_no, i.barcode, i.district_no,
                          i.condition AS instrument_condition, i.locker
                   FROM repairs r
                   LEFT JOIN instruments i ON i.id = r.instrument_id
                   WHERE r.date_repaired IS NULL OR TRIM(r.date_repaired) = ''
                   ORDER BY r.priority DESC, i.category, i.description"""
            ).fetchall()

    def get_instruments_needing_repair(self):
        """One row per instrument that has at least one open (not-yet-repaired)
        repair, with the open repairs aggregated.  Used by the Needs/Out-for-
        Repair views and the technician export so each instrument appears once.
        Instruments whose condition is 'Unrepairable' are excluded — they are
        beyond salvage, so open repairs shouldn't keep surfacing them."""
        with self._connect() as conn:
            return conn.execute(
                """SELECT i.id, i.category, i.description AS instrument_desc,
                          i.brand, i.model, i.serial_no, i.barcode, i.district_no,
                          i.condition AS instrument_condition, i.locker,
                          COUNT(r.id) AS open_count,
                          MAX(r.priority) AS max_priority,
                          MAX(r.date_added) AS last_reported,
                          GROUP_CONCAT(NULLIF(TRIM(r.description), ''), '  •  ') AS needs,
                          MAX(COALESCE(NULLIF(TRIM(r.assigned_to), ''),
                                       NULLIF(TRIM(r.location), ''), '')) AS shop
                   FROM instruments i
                   JOIN repairs r ON r.instrument_id = i.id
                   WHERE (r.date_repaired IS NULL OR TRIM(r.date_repaired) = '')
                     AND LOWER(TRIM(IFNULL(i.condition,''))) != 'unrepairable'
                   GROUP BY i.id
                   ORDER BY max_priority DESC, i.category, i.description"""
            ).fetchall()

    def get_instruments_marked_needs_repair(self):
        """Instruments whose condition is 'Needs Repair' but that have NO open
        repair record — they'd otherwise be invisible in the Needs-Repair list
        even though the teacher flagged them on the instrument itself.  Returned
        in the same shape as get_instruments_needing_repair() so the two can be
        combined.  'Unrepairable' is still excluded (beyond salvage)."""
        with self._connect() as conn:
            return conn.execute(
                """SELECT i.id, i.category, i.description AS instrument_desc,
                          i.brand, i.model, i.serial_no, i.barcode, i.district_no,
                          i.condition AS instrument_condition, i.locker,
                          0 AS open_count, 0 AS max_priority,
                          '' AS last_reported, '' AS needs, '' AS shop
                   FROM instruments i
                   WHERE LOWER(TRIM(IFNULL(i.condition,''))) = 'needs repair'
                     AND COALESCE(i.is_active, 1) = 1
                     AND NOT EXISTS (
                         SELECT 1 FROM repairs r
                         WHERE r.instrument_id = i.id
                           AND (r.date_repaired IS NULL OR TRIM(r.date_repaired) = ''))
                   ORDER BY i.category, i.description"""
            ).fetchall()

    def clear_needs_repair_if_done(self, instrument_id: int) -> bool:
        """Once an instrument has no open repairs left, reset a lingering
        'Needs Repair' condition to 'Good' so it stops resurfacing on the
        Needs-Repair list.  Returns True if the condition was changed."""
        with self._connect() as conn:
            open_ct = conn.execute(
                "SELECT COUNT(*) FROM repairs WHERE instrument_id=? "
                "AND (date_repaired IS NULL OR TRIM(date_repaired) = '')",
                (instrument_id,)).fetchone()[0]
            if open_ct:
                return False
            cur = conn.execute(
                "UPDATE instruments SET condition='Good' WHERE id=? "
                "AND LOWER(TRIM(IFNULL(condition,''))) = 'needs repair'",
                (instrument_id,))
            return cur.rowcount > 0

    def get_open_repairs_for_instrument(self, instrument_id):
        """The individual open repair records for one instrument (for the
        edit/mark-repaired pickers)."""
        with self._connect() as conn:
            return conn.execute(
                """SELECT * FROM repairs
                   WHERE instrument_id=? AND (date_repaired IS NULL OR TRIM(date_repaired)='')
                   ORDER BY date_added DESC""",
                (instrument_id,)
            ).fetchall()

    def get_all_repairs(self):
        """Every repair record joined with its instrument, for the repair-hub
        history view and cost analysis."""
        with self._connect() as conn:
            return conn.execute(
                """SELECT r.*, i.category, i.description AS instrument_desc,
                          i.brand, i.model, i.serial_no, i.barcode, i.district_no,
                          i.condition AS instrument_condition, i.locker,
                          i.amount_paid, i.est_value, i.year_purchased
                   FROM repairs r
                   LEFT JOIN instruments i ON i.id = r.instrument_id
                   ORDER BY r.date_added DESC"""
            ).fetchall()

    def get_repair_cost_summary(self):
        """Per-instrument repair totals, ranked by total spent (desc), for the
        'which instruments cost the most' report."""
        with self._connect() as conn:
            return conn.execute(
                """SELECT i.id, i.category, i.description AS instrument_desc,
                          i.brand, i.model, i.serial_no, i.barcode, i.district_no,
                          i.condition AS instrument_condition,
                          i.amount_paid, i.est_value, i.year_purchased,
                          COUNT(r.id) AS repair_count,
                          COALESCE(SUM(COALESCE(r.act_cost, 0)), 0) AS total_spent,
                          MAX(COALESCE(r.date_repaired, r.date_added)) AS last_repair
                   FROM instruments i
                   JOIN repairs r ON r.instrument_id = i.id
                   GROUP BY i.id
                   ORDER BY total_spent DESC, repair_count DESC"""
            ).fetchall()

    def mark_repair_completed(self, repair_id: int, date_repaired: str):
        with self._connect() as conn:
            conn.execute(
                "UPDATE repairs SET date_repaired=? WHERE id=?",
                (date_repaired, repair_id)
            )

    def recover_repair_notes_from_checkins(self) -> int:
        """One-time recovery: convert repair info that was buried in returned
        check-in notes into real (pending) repair records.  Idempotent — each
        source checkout is tagged, so re-running never duplicates.  Returns the
        number of repair records created."""
        created = 0
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT id, instrument_id, notes, date_returned, student_name
                   FROM checkouts
                   WHERE date_returned IS NOT NULL
                     AND instrument_id IS NOT NULL
                     AND notes IS NOT NULL AND TRIM(notes) != ''"""
            ).fetchall()
            for r in rows:
                note = (r["notes"] or "").strip()
                if "repair" not in note.lower():
                    continue
                marker = f"[recovered from check-in #{r['id']}]"
                existing = conn.execute(
                    "SELECT COUNT(*) FROM repairs WHERE instrument_id=? AND notes LIKE ?",
                    (r["instrument_id"], f"%{marker}%")
                ).fetchone()
                if existing and existing[0]:
                    continue
                # Strip the "Condition at return: X." boilerplate for the summary
                desc = note
                if desc.lower().startswith("condition at return:"):
                    parts = desc.split(".", 1)
                    desc = parts[1].strip() if len(parts) > 1 and parts[1].strip() else note
                who = (r["student_name"] or "").strip()
                full_notes = note
                if who:
                    full_notes = f"Reported at check-in from {who}. {note}"
                full_notes = f"{full_notes}\n{marker}"
                conn.execute(
                    """INSERT INTO repairs
                       (instrument_id, priority, date_added, description, notes, date_repaired)
                       VALUES (?, ?, ?, ?, ?, NULL)""",
                    (r["instrument_id"], 1, r["date_returned"], desc[:250], full_notes)
                )
                created += 1
            conn.commit()
        return created

    # ─── Budgeting ───────────────────────────────────────────────────────────────

    FUNDING_SOURCES = ["Building", "ASB", "Boosters", "Other"]

    @staticmethod
    def school_year_bounds(school_year: str):
        """('2025-2026') → ('2025-07-01', '2026-06-30')."""
        try:
            start = int(school_year.split("-")[0])
        except (ValueError, AttributeError, IndexError):
            from datetime import datetime as _dt
            start = _dt.today().year
        return f"{start}-07-01", f"{start + 1}-06-30"

    @staticmethod
    def current_school_year():
        from datetime import datetime as _dt
        t = _dt.today()
        start = t.year if t.month >= 7 else t.year - 1
        return f"{start}-{start + 1}"

    def get_budget_categories(self, kind: str = None):
        with self._connect() as conn:
            if kind:
                rows = conn.execute(
                    "SELECT * FROM budget_categories WHERE kind=? ORDER BY name", (kind,)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM budget_categories ORDER BY kind, name").fetchall()
        return rows

    def add_budget_category(self, name: str, kind: str) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO budget_categories (name, kind) VALUES (?, ?)", (name, kind))
            return cur.lastrowid

    def delete_budget_category(self, cat_id: int):
        with self._connect() as conn:
            conn.execute("DELETE FROM budget_categories WHERE id=?", (cat_id,))

    def add_budget_transaction(self, data: dict) -> int:
        cols = ["txn_date", "description", "category", "kind", "amount",
                "funding_source", "student_id", "notes"]
        vals = [data.get(c) for c in cols]
        with self._connect() as conn:
            cur = conn.execute(
                f"INSERT INTO budget_transactions ({','.join(cols)}) "
                f"VALUES ({','.join('?' * len(cols))})", vals)
            return cur.lastrowid

    def update_budget_transaction(self, txn_id: int, data: dict):
        cols = ["txn_date", "description", "category", "kind", "amount",
                "funding_source", "student_id", "notes"]
        set_clause = ", ".join(f"{c}=?" for c in cols)
        with self._connect() as conn:
            conn.execute(f"UPDATE budget_transactions SET {set_clause} WHERE id=?",
                         [data.get(c) for c in cols] + [txn_id])

    def delete_budget_transaction(self, txn_id: int):
        with self._connect() as conn:
            conn.execute("DELETE FROM budget_transactions WHERE id=?", (txn_id,))

    def get_budget_transactions(self, school_year: str):
        """Manual transactions within a school year, plus auto-linked instrument
        repair costs for that year (as read-only synthetic rows)."""
        lo, hi = self.school_year_bounds(school_year)
        with self._connect() as conn:
            rows = [dict(r) for r in conn.execute(
                """SELECT t.*, (s.first_name || ' ' || s.last_name) AS student_name
                   FROM budget_transactions t
                   LEFT JOIN students s ON s.id = t.student_id
                   WHERE t.txn_date >= ? AND t.txn_date <= ?
                   ORDER BY t.txn_date DESC""", (lo, hi)).fetchall()]
            for r in rows:
                r["source"] = "manual"
            # Auto-linked repair expenses (actual costs) in the same window
            reps = conn.execute(
                """SELECT r.id, r.act_cost, r.date_repaired, r.date_added, r.description,
                          i.description AS inst
                   FROM repairs r LEFT JOIN instruments i ON i.id = r.instrument_id
                   WHERE COALESCE(NULLIF(r.act_cost,0),0) > 0
                     AND COALESCE(r.exclude_from_budget,0)=0
                     AND COALESCE(NULLIF(r.date_repaired,''), r.date_added) >= ?
                     AND COALESCE(NULLIF(r.date_repaired,''), r.date_added) <= ?""",
                (lo, hi)).fetchall()
            # Collected student fees (status 'paid') for this year → income, as
            # read-only synthetic rows (managed in Budget ▸ Student Fees, same
            # pattern as auto-linked repair expenses).  Matched on the fee's
            # academic-year label so the July fiscal-boundary can't drop them.
            fees = conn.execute(
                """SELECT sf.id, sf.fee_type, sf.amount, sf.date_paid, sf.student_id,
                          (s.first_name || ' ' || s.last_name) AS student_name
                   FROM student_fees sf
                   LEFT JOIN students s ON s.id = sf.student_id
                   WHERE sf.status='paid' AND sf.school_year=?""",
                (school_year,)).fetchall()
        for rp in reps:
            rows.append({
                "id": None, "source": "repair", "repair_id": rp["id"],
                "txn_date": rp["date_repaired"] or rp["date_added"] or "",
                "description": f"Repair: {rp['inst'] or ''} — {rp['description'] or ''}".strip(" —"),
                "category": "Instrument Repair", "kind": "expense",
                "amount": float(rp["act_cost"] or 0), "funding_source": "Building",
                "student_id": None, "student_name": "", "notes": "",
            })
        for f in fees:
            ftype = f["fee_type"] or "Student Fee"
            cat = ("Instrument Rental Fees"
                   if ftype.lower().startswith("instrument rental") else "Student Fees")
            who = f["student_name"] or ""
            rows.append({
                "id": None, "source": "fee", "fee_id": f["id"],
                "txn_date": f["date_paid"] or lo,
                "description": f"Fee: {ftype}" + (f" — {who}" if who else ""),
                "category": cat, "kind": "income",
                "amount": float(f["amount"] or 0), "funding_source": "Other",
                "student_id": f["student_id"], "student_name": who, "notes": "",
            })
        rows.sort(key=lambda r: r.get("txn_date") or "", reverse=True)
        return rows

    def get_budget_summary(self, school_year: str):
        """Totals by funding source and kind for the year."""
        rows = self.get_budget_transactions(school_year)
        summary = {}
        for r in rows:
            src = r.get("funding_source") or "Other"
            d = summary.setdefault(src, {"expense": 0.0, "income": 0.0})
            d[r.get("kind") or "expense"] += float(r.get("amount") or 0)
        return summary

    @staticmethod
    def _fiscal_year_of(date_str: str):
        d = (date_str or "")[:10]
        try:
            y, m = int(d[:4]), int(d[5:7])
        except (ValueError, IndexError):
            return None
        start = y if m >= 7 else y - 1
        return f"{start}-{start + 1}"

    def _budget_activity_years(self):
        """Fiscal years that actually have transactions or repair costs."""
        years = set()
        with self._connect() as conn:
            for r in conn.execute("SELECT txn_date FROM budget_transactions "
                                  "WHERE txn_date IS NOT NULL").fetchall():
                fy = self._fiscal_year_of(r["txn_date"])
                if fy:
                    years.add(fy)
            for r in conn.execute(
                    "SELECT COALESCE(NULLIF(date_repaired,''), date_added) AS d FROM repairs "
                    "WHERE COALESCE(NULLIF(act_cost,0),0) > 0 "
                    "AND COALESCE(exclude_from_budget,0)=0").fetchall():
                fy = self._fiscal_year_of(r["d"])
                if fy:
                    years.add(fy)
        return years

    def get_budget_school_years(self):
        years = set(self._budget_activity_years())
        cur = self.current_school_year()
        years.add(cur)
        start = int(cur.split("-")[0])
        years.add(f"{start - 1}-{start}")   # also offer the previous fiscal year
        return sorted(years, reverse=True)

    def get_budget_default_year(self):
        """Open on the most recent year that has activity — so repairs/expenses
        show without the user hunting for the right year (fiscal 'current' is
        often empty right after July 1)."""
        activity = self._budget_activity_years()
        return max(activity) if activity else self.current_school_year()

    # ─── Student fees ────────────────────────────────────────────────────────────

    def get_fee_types(self):
        with self._connect() as conn:
            return conn.execute("SELECT * FROM fee_types ORDER BY name").fetchall()

    def add_fee_type(self, name: str, default_amount: float = 0) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO fee_types (name, default_amount) VALUES (?, ?)",
                (name, default_amount))
            return cur.lastrowid

    def ensure_fee_type(self, name: str, default_amount: float = 0):
        """Create the fee type if absent; update its default amount if present."""
        with self._connect() as conn:
            row = conn.execute("SELECT id FROM fee_types WHERE name=?", (name,)).fetchone()
            if row:
                conn.execute("UPDATE fee_types SET default_amount=? WHERE id=?",
                             (default_amount, row["id"]))
                return row["id"]
            cur = conn.execute("INSERT INTO fee_types (name, default_amount) VALUES (?, ?)",
                               (name, default_amount))
            return cur.lastrowid

    def delete_fee_type(self, fee_id: int):
        with self._connect() as conn:
            conn.execute("DELETE FROM fee_types WHERE id=?", (fee_id,))

    def get_student_fees(self, fee_type: str, school_year: str):
        """All student_fee rows for a fee type + year, joined with the student."""
        with self._connect() as conn:
            return conn.execute(
                """SELECT sf.*, s.first_name, s.last_name, s.preferred_name, s.grade,
                          s.ensembles, s.student_email, s.parent1_email, s.parent2_email
                   FROM student_fees sf
                   JOIN students s ON s.id = sf.student_id
                   WHERE sf.fee_type=? AND sf.school_year=?
                   ORDER BY s.last_name, s.first_name""",
                (fee_type, school_year)).fetchall()

    def ensure_student_fee(self, student_id, fee_type, school_year, amount, status="unpaid"):
        """Create a fee row for a student if one doesn't already exist."""
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT id FROM student_fees WHERE student_id=? AND fee_type=? AND school_year=?",
                (student_id, fee_type, school_year)).fetchone()
            if existing:
                return existing["id"]
            cur = conn.execute(
                """INSERT INTO student_fees (student_id, fee_type, school_year, amount, status)
                   VALUES (?, ?, ?, ?, ?)""",
                (student_id, fee_type, school_year, amount, status))
            return cur.lastrowid

    def add_student_fee(self, student_id, fee_type, school_year, amount, status="unpaid"):
        """Always INSERT a fee row (no dedup) — for students who owe a fee more
        than once, e.g. renting several instruments (3 summer rentals = 3 × $20)."""
        with self._connect() as conn:
            cur = conn.execute(
                """INSERT INTO student_fees (student_id, fee_type, school_year, amount, status)
                   VALUES (?, ?, ?, ?, ?)""",
                (student_id, fee_type, school_year, amount, status))
            return cur.lastrowid

    def set_student_fee_status(self, fee_id, status, date_paid=None):
        with self._connect() as conn:
            conn.execute("UPDATE student_fees SET status=?, date_paid=? WHERE id=?",
                         (status, date_paid, fee_id))

    def delete_student_fee(self, fee_id):
        with self._connect() as conn:
            conn.execute("DELETE FROM student_fees WHERE id=?", (fee_id,))

    def get_unpaid_fee(self, fee_type, school_year):
        """All students who still owe this fee (status 'unpaid')."""
        return [dict(r) for r in self.get_student_fees(fee_type, school_year)
                if r["status"] == "unpaid"]

    def get_unpaid_fee_with_checkout(self, fee_type, school_year):
        """Students who owe this fee (status 'unpaid') AND currently have an
        instrument checked out — the set to nudge for payment."""
        rows = self.get_student_fees(fee_type, school_year)
        out = []
        with self._connect() as conn:
            for r in rows:
                if r["status"] != "unpaid":
                    continue
                n = conn.execute(
                    "SELECT COUNT(*) FROM checkouts WHERE student_id=? AND date_returned IS NULL",
                    (r["student_id"],)).fetchone()[0]
                if n > 0:
                    out.append(dict(r))
        return out

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
            # Instruments currently in the repair pipeline — MUST match the
            # Repair Center's Needs/Out-for-Repair views: an open repair is one
            # with no repaired-date (NULL *or* empty string — "Mark Out for
            # Repair" saves date_repaired=""), on an active, not-unrepairable
            # instrument.  (Previously counted only IS NULL, so the 12 "out for
            # repair" instruments — saved with ""— showed as 1.)
            in_repair = conn.execute(
                """SELECT COUNT(DISTINCT r.instrument_id) FROM repairs r
                   JOIN instruments i ON i.id = r.instrument_id
                   WHERE (r.date_repaired IS NULL OR TRIM(r.date_repaired) = '')
                     AND i.is_active = 1
                     AND LOWER(TRIM(IFNULL(i.condition, ''))) != 'unrepairable'"""
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
        """Insert a repair record from a bulk import, skipping exact duplicates.
        Imported repairs are ARCHIVAL — they belong in the repair log for history
        but must NOT count as current budget expenses (they were paid long ago
        under some other budget), so they default to exclude_from_budget=1."""
        excl = data.get("exclude_from_budget", 1)
        with self._connect() as conn:
            existing = conn.execute(
                """SELECT id FROM repairs
                   WHERE instrument_id=? AND date_added=? AND description=?""",
                (data.get("instrument_id"), data.get("date_added"), data.get("description"))
            ).fetchone()
            if existing:
                # Re-importing flags an already-imported repair as archival too,
                # so it stops counting as a budget expense.
                conn.execute("UPDATE repairs SET exclude_from_budget=? WHERE id=?",
                             (excl, existing["id"]))
                return existing["id"]
            cols = [
                "instrument_id", "priority", "date_added", "assigned_to",
                "date_repaired", "description", "location",
                "est_cost", "act_cost", "invoice_number", "exclude_from_budget"
            ]
            data = {**data, "exclude_from_budget": excl}
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
        elif order_col == "title":
            # Library-style: ignore a leading article (A / An / The) when sorting.
            order_sql = (
                "CASE "
                "WHEN sm.title LIKE 'A ' || '%' THEN substr(sm.title, 3) "
                "WHEN sm.title LIKE 'An ' || '%' THEN substr(sm.title, 4) "
                "WHEN sm.title LIKE 'The ' || '%' THEN substr(sm.title, 5) "
                "ELSE sm.title END COLLATE NOCASE " + direction
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

    def get_performances_by_ensemble(self, ensemble: str = None):
        """Performance history joined with the piece, optionally filtered to one
        ensemble.  A performance may list several comma-separated ensembles
        (combined performances), so filtering matches membership."""
        sql = """SELECT p.*, sm.title, sm.composer, sm.arranger,
                        sm.ensemble_type, sm.difficulty, sm.voicing
                 FROM performances p
                 JOIN sheet_music sm ON sm.id = p.music_id
                 ORDER BY p.performance_date DESC, sm.title"""
        with self._connect() as conn:
            rows = conn.execute(sql).fetchall()
        if not ensemble or ensemble == "All":
            return rows
        target = ensemble.strip()
        out = []
        for r in rows:
            members = [e.strip() for e in (r["ensemble"] or "").split(",") if e.strip()]
            if target in members:
                out.append(r)
        return out

    def normalize_performance_ensembles(self, school_name: str) -> int:
        """Strip the teacher's own school name from recorded performance
        ensembles so 'Chinook Jazz 1' and 'Jazz 1' are one cohort.  Ensembles
        may be comma-separated (combined performances); each member is folded
        and de-duplicated.  Idempotent — safe to run every launch.  Returns
        the number of rows rewritten."""
        if not school_name_variants(school_name):
            return 0
        changed = 0
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, ensemble FROM performances "
                "WHERE ensemble IS NOT NULL AND TRIM(ensemble) != ''"
            ).fetchall()
            for r in rows:
                parts = [p.strip() for p in (r["ensemble"] or "").split(",")
                         if p.strip()]
                new_parts = []
                for p in parts:
                    np = strip_school_prefix(p, school_name)
                    if np not in new_parts:
                        new_parts.append(np)
                if new_parts != parts:
                    conn.execute("UPDATE performances SET ensemble=? WHERE id=?",
                                 (", ".join(new_parts), r["id"]))
                    changed += 1
        return changed

    def get_distinct_performance_ensembles(self):
        """Individual ensemble names across all performances, splitting any
        comma-separated combined entries."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT ensemble FROM performances "
                "WHERE ensemble IS NOT NULL AND TRIM(ensemble) != ''"
            ).fetchall()
        seen = []
        for r in rows:
            for e in (r["ensemble"] or "").split(","):
                e = e.strip()
                if e and e not in seen:
                    seen.append(e)
        return sorted(seen)

    def get_music_for_matching(self):
        """Lightweight (id, title, composer) list of active pieces, for matching
        program entries against the library."""
        with self._connect() as conn:
            return [dict(r) for r in conn.execute(
                "SELECT id, title, composer, arranger, ensemble_type, voicing "
                "FROM sheet_music WHERE is_active=1"
            ).fetchall()]

    def performance_exists(self, music_id: int, performance_date: str, ensemble: str) -> bool:
        """Guard against importing the same program twice."""
        with self._connect() as conn:
            row = conn.execute(
                """SELECT 1 FROM performances
                   WHERE music_id=? AND performance_date=?
                     AND IFNULL(ensemble,'')=IFNULL(?,'') LIMIT 1""",
                (music_id, performance_date, ensemble)
            ).fetchone()
        return bool(row)

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

    # ═══════════════════════════════════════════════════════════════════════════
    # LESSON PLANS MODULE
    # ═══════════════════════════════════════════════════════════════════════════

    # ─── Teaching Classes CRUD ────────────────────────────────────────────────

    def get_all_classes(self, school_year=None, include_inactive=False):
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
                f"SELECT * FROM teaching_classes {where} ORDER BY period, class_name",
                params,
            ).fetchall()

    def get_class(self, class_id: int):
        with self._connect() as conn:
            return conn.execute(
                "SELECT * FROM teaching_classes WHERE id=?", (class_id,)
            ).fetchone()

    def add_class(self, data: dict) -> int:
        cols = [
            "class_name", "ensemble_type", "grade_levels", "skill_level",
            "period", "days_of_week", "class_duration", "student_count",
            "method_book", "school_year", "room", "notes",
        ]
        values = [data.get(c) for c in cols]
        placeholders = ",".join(["?"] * len(cols))
        col_str = ",".join(cols)
        with self._connect() as conn:
            cur = conn.execute(
                f"INSERT INTO teaching_classes ({col_str}) VALUES ({placeholders})",
                values,
            )
            return cur.lastrowid

    def update_class(self, class_id: int, data: dict):
        cols = [
            "class_name", "ensemble_type", "grade_levels", "skill_level",
            "period", "days_of_week", "class_duration", "student_count",
            "method_book", "school_year", "room", "notes", "is_active",
        ]
        set_clause = ", ".join([f"{c}=?" for c in cols])
        values = [data.get(c) for c in cols] + [class_id]
        with self._connect() as conn:
            conn.execute(
                f"UPDATE teaching_classes SET {set_clause} WHERE id=?", values
            )

    def deactivate_class(self, class_id: int):
        with self._connect() as conn:
            conn.execute(
                "UPDATE teaching_classes SET is_active=0 WHERE id=?", (class_id,)
            )

    def get_class_school_years(self):
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT DISTINCT school_year FROM teaching_classes "
                "WHERE school_year IS NOT NULL ORDER BY school_year DESC"
            ).fetchall()
        return [r["school_year"] for r in rows]

    # ─── Concert Dates CRUD ──────────────────────────────────────────────────

    def get_concert_dates(self, class_id: int = None):
        with self._connect() as conn:
            if class_id:
                return conn.execute(
                    "SELECT * FROM concert_dates WHERE class_id=? ORDER BY concert_date",
                    (class_id,),
                ).fetchall()
            return conn.execute(
                "SELECT cd.*, tc.class_name FROM concert_dates cd "
                "JOIN teaching_classes tc ON tc.id = cd.class_id "
                "ORDER BY cd.concert_date"
            ).fetchall()

    def add_concert_date(self, data: dict) -> int:
        cols = ["class_id", "concert_date", "event_name", "location", "notes"]
        values = [data.get(c) for c in cols]
        placeholders = ",".join(["?"] * len(cols))
        col_str = ",".join(cols)
        with self._connect() as conn:
            cur = conn.execute(
                f"INSERT INTO concert_dates ({col_str}) VALUES ({placeholders})",
                values,
            )
            return cur.lastrowid

    def update_concert_date(self, concert_id: int, data: dict):
        cols = ["class_id", "concert_date", "event_name", "location", "notes"]
        set_clause = ", ".join([f"{c}=?" for c in cols])
        values = [data.get(c) for c in cols] + [concert_id]
        with self._connect() as conn:
            conn.execute(
                f"UPDATE concert_dates SET {set_clause} WHERE id=?", values
            )

    def delete_concert_date(self, concert_id: int):
        with self._connect() as conn:
            conn.execute("DELETE FROM concert_dates WHERE id=?", (concert_id,))

    # ─── Curriculum Items CRUD ────────────────────────────────────────────────

    def get_curriculum_items(self, class_id: int, start_date: str = None,
                            end_date: str = None):
        with self._connect() as conn:
            conditions = ["class_id=?"]
            params = [class_id]
            if start_date:
                conditions.append("item_date >= ?")
                params.append(start_date)
            if end_date:
                conditions.append("item_date <= ?")
                params.append(end_date)
            where = " AND ".join(conditions)
            return conn.execute(
                f"SELECT * FROM curriculum_items WHERE {where} ORDER BY item_date",
                params,
            ).fetchall()

    def get_curriculum_item(self, item_id: int):
        with self._connect() as conn:
            return conn.execute(
                "SELECT * FROM curriculum_items WHERE id=?", (item_id,)
            ).fetchone()

    def get_curriculum_item_by_date(self, class_id: int, item_date: str):
        with self._connect() as conn:
            return conn.execute(
                "SELECT * FROM curriculum_items WHERE class_id=? AND item_date=?",
                (class_id, item_date),
            ).fetchone()

    def add_curriculum_item(self, data: dict) -> int:
        cols = [
            "class_id", "item_date", "summary", "activity_type",
            "unit_name", "is_locked", "sort_order", "notes",
        ]
        values = [data.get(c) for c in cols]
        placeholders = ",".join(["?"] * len(cols))
        col_str = ",".join(cols)
        with self._connect() as conn:
            cur = conn.execute(
                f"INSERT INTO curriculum_items ({col_str}) VALUES ({placeholders})",
                values,
            )
            return cur.lastrowid

    def update_curriculum_item(self, item_id: int, data: dict):
        cols = [
            "class_id", "item_date", "summary", "activity_type",
            "unit_name", "is_locked", "sort_order", "notes",
        ]
        set_clause = ", ".join([f"{c}=?" for c in cols])
        values = [data.get(c) for c in cols] + [item_id]
        with self._connect() as conn:
            conn.execute(
                f"UPDATE curriculum_items SET {set_clause} WHERE id=?", values
            )

    def delete_curriculum_item(self, item_id: int):
        """Delete a curriculum item and its associated lesson plan (if any)."""
        with self._connect() as conn:
            # cascade: delete lesson blocks, then lesson plan, then curriculum item
            conn.execute(
                "DELETE FROM lesson_blocks WHERE lesson_plan_id IN "
                "(SELECT id FROM lesson_plans WHERE curriculum_item_id=?)",
                (item_id,),
            )
            conn.execute(
                "DELETE FROM lesson_plan_resources WHERE lesson_plan_id IN "
                "(SELECT id FROM lesson_plans WHERE curriculum_item_id=?)",
                (item_id,),
            )
            conn.execute(
                "DELETE FROM lesson_plans WHERE curriculum_item_id=?", (item_id,)
            )
            conn.execute(
                "DELETE FROM curriculum_items WHERE id=?", (item_id,)
            )

    def move_curriculum_item(self, item_id: int, new_date: str):
        """Move a single curriculum item to a new date."""
        with self._connect() as conn:
            conn.execute(
                "UPDATE curriculum_items SET item_date=? WHERE id=?",
                (new_date, item_id),
            )

    def shift_curriculum_items(self, class_id: int, from_date: str, days: int):
        """Shift all unlocked curriculum items on or after from_date by N days.
        Positive = forward, negative = backward."""
        with self._connect() as conn:
            items = conn.execute(
                "SELECT id, item_date FROM curriculum_items "
                "WHERE class_id=? AND item_date >= ? AND is_locked=0 "
                "ORDER BY item_date " + ("DESC" if days > 0 else "ASC"),
                (class_id, from_date),
            ).fetchall()
            for item in items:
                from datetime import timedelta
                old = datetime.strptime(item["item_date"], "%Y-%m-%d")
                new = old + timedelta(days=days)
                conn.execute(
                    "UPDATE curriculum_items SET item_date=? WHERE id=?",
                    (new.strftime("%Y-%m-%d"), item["id"]),
                )

    def swap_curriculum_items(self, item_id_a: int, item_id_b: int):
        """Swap the dates of two curriculum items."""
        with self._connect() as conn:
            a = conn.execute(
                "SELECT item_date FROM curriculum_items WHERE id=?", (item_id_a,)
            ).fetchone()
            b = conn.execute(
                "SELECT item_date FROM curriculum_items WHERE id=?", (item_id_b,)
            ).fetchone()
            if a and b:
                conn.execute(
                    "UPDATE curriculum_items SET item_date=? WHERE id=?",
                    (b["item_date"], item_id_a),
                )
                conn.execute(
                    "UPDATE curriculum_items SET item_date=? WHERE id=?",
                    (a["item_date"], item_id_b),
                )

    def bulk_add_curriculum_items(self, items: list[dict]) -> list[int]:
        """Insert multiple curriculum items at once. Returns list of new IDs."""
        cols = [
            "class_id", "item_date", "summary", "activity_type",
            "unit_name", "is_locked", "sort_order", "notes",
        ]
        placeholders = ",".join(["?"] * len(cols))
        col_str = ",".join(cols)
        ids = []
        with self._connect() as conn:
            for data in items:
                values = [data.get(c) for c in cols]
                cur = conn.execute(
                    f"INSERT INTO curriculum_items ({col_str}) VALUES ({placeholders})",
                    values,
                )
                ids.append(cur.lastrowid)
        return ids

    def clear_curriculum(self, class_id: int):
        """Delete all curriculum items (and their lesson plans) for a class."""
        with self._connect() as conn:
            # cascade lesson blocks and resources
            conn.execute(
                "DELETE FROM lesson_blocks WHERE lesson_plan_id IN "
                "(SELECT lp.id FROM lesson_plans lp "
                " JOIN curriculum_items ci ON ci.id = lp.curriculum_item_id "
                " WHERE ci.class_id=?)",
                (class_id,),
            )
            conn.execute(
                "DELETE FROM lesson_plan_resources WHERE lesson_plan_id IN "
                "(SELECT lp.id FROM lesson_plans lp "
                " JOIN curriculum_items ci ON ci.id = lp.curriculum_item_id "
                " WHERE ci.class_id=?)",
                (class_id,),
            )
            conn.execute(
                "DELETE FROM lesson_plans WHERE curriculum_item_id IN "
                "(SELECT id FROM curriculum_items WHERE class_id=?)",
                (class_id,),
            )
            conn.execute(
                "DELETE FROM curriculum_items WHERE class_id=?", (class_id,)
            )

    # ─── Lesson Plans CRUD ───────────────────────────────────────────────────

    def get_lesson_plan(self, plan_id: int):
        with self._connect() as conn:
            return conn.execute(
                "SELECT * FROM lesson_plans WHERE id=?", (plan_id,)
            ).fetchone()

    def get_lesson_plan_by_curriculum_item(self, curriculum_item_id: int):
        with self._connect() as conn:
            return conn.execute(
                "SELECT * FROM lesson_plans WHERE curriculum_item_id=?",
                (curriculum_item_id,),
            ).fetchone()

    def get_lesson_plan_for_date(self, class_id: int, plan_date: str):
        """Get lesson plan for a specific class and date (via curriculum item)."""
        with self._connect() as conn:
            return conn.execute(
                "SELECT lp.* FROM lesson_plans lp "
                "JOIN curriculum_items ci ON ci.id = lp.curriculum_item_id "
                "WHERE ci.class_id=? AND ci.item_date=?",
                (class_id, plan_date),
            ).fetchone()

    def add_lesson_plan(self, data: dict) -> int:
        cols = [
            "curriculum_item_id", "objectives", "standards",
            "warmup_text", "warmup_template_id", "assessment_type",
            "assessment_details", "differentiation_advanced",
            "differentiation_struggling", "differentiation_iep",
            "reflection_text", "reflection_rating", "status",
            "total_minutes_planned", "notes",
        ]
        values = [data.get(c) for c in cols]
        placeholders = ",".join(["?"] * len(cols))
        col_str = ",".join(cols)
        with self._connect() as conn:
            cur = conn.execute(
                f"INSERT INTO lesson_plans ({col_str}) VALUES ({placeholders})",
                values,
            )
            return cur.lastrowid

    def update_lesson_plan(self, plan_id: int, data: dict):
        cols = [
            "curriculum_item_id", "objectives", "standards",
            "warmup_text", "warmup_template_id", "assessment_type",
            "assessment_details", "differentiation_advanced",
            "differentiation_struggling", "differentiation_iep",
            "reflection_text", "reflection_rating", "status",
            "total_minutes_planned", "notes",
        ]
        set_clause = ", ".join([f"{c}=?" for c in cols])
        values = [data.get(c) for c in cols] + [plan_id]
        with self._connect() as conn:
            conn.execute(
                f"UPDATE lesson_plans SET {set_clause} WHERE id=?", values
            )

    def delete_lesson_plan(self, plan_id: int):
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM lesson_blocks WHERE lesson_plan_id=?", (plan_id,)
            )
            conn.execute(
                "DELETE FROM lesson_plan_resources WHERE lesson_plan_id=?", (plan_id,)
            )
            conn.execute("DELETE FROM lesson_plans WHERE id=?", (plan_id,))

    # ─── Lesson Blocks CRUD ──────────────────────────────────────────────────

    def get_lesson_blocks(self, lesson_plan_id: int):
        with self._connect() as conn:
            return conn.execute(
                "SELECT * FROM lesson_blocks WHERE lesson_plan_id=? ORDER BY sort_order",
                (lesson_plan_id,),
            ).fetchall()

    def add_lesson_block(self, data: dict) -> int:
        cols = [
            "lesson_plan_id", "block_type", "title", "description",
            "duration_minutes", "sort_order", "music_piece_id",
            "measure_start", "measure_end", "technique_focus",
            "difficulty_level", "grouping", "notes",
        ]
        values = [data.get(c) for c in cols]
        placeholders = ",".join(["?"] * len(cols))
        col_str = ",".join(cols)
        with self._connect() as conn:
            cur = conn.execute(
                f"INSERT INTO lesson_blocks ({col_str}) VALUES ({placeholders})",
                values,
            )
            return cur.lastrowid

    def update_lesson_block(self, block_id: int, data: dict):
        cols = [
            "lesson_plan_id", "block_type", "title", "description",
            "duration_minutes", "sort_order", "music_piece_id",
            "measure_start", "measure_end", "technique_focus",
            "difficulty_level", "grouping", "notes",
        ]
        set_clause = ", ".join([f"{c}=?" for c in cols])
        values = [data.get(c) for c in cols] + [block_id]
        with self._connect() as conn:
            conn.execute(
                f"UPDATE lesson_blocks SET {set_clause} WHERE id=?", values
            )

    def delete_lesson_block(self, block_id: int):
        with self._connect() as conn:
            conn.execute("DELETE FROM lesson_blocks WHERE id=?", (block_id,))

    def reorder_lesson_blocks(self, lesson_plan_id: int, block_ids: list[int]):
        """Reorder blocks by updating sort_order based on position in block_ids list."""
        with self._connect() as conn:
            for idx, block_id in enumerate(block_ids):
                conn.execute(
                    "UPDATE lesson_blocks SET sort_order=? "
                    "WHERE id=? AND lesson_plan_id=?",
                    (idx, block_id, lesson_plan_id),
                )

    # ─── Resources CRUD ──────────────────────────────────────────────────────

    def get_all_resources(self, resource_type: str = None):
        with self._connect() as conn:
            if resource_type:
                return conn.execute(
                    "SELECT * FROM resources WHERE resource_type=? ORDER BY display_name",
                    (resource_type,),
                ).fetchall()
            return conn.execute(
                "SELECT * FROM resources ORDER BY display_name"
            ).fetchall()

    def get_resource(self, resource_id: int):
        with self._connect() as conn:
            return conn.execute(
                "SELECT * FROM resources WHERE id=?", (resource_id,)
            ).fetchone()

    def search_resources(self, search: str = "", resource_type: str = "",
                         tag: str = ""):
        """Search resources with filtering. Returns list of rows."""
        with self._connect() as conn:
            conditions = []
            params = []
            if search:
                tok = f"%{search}%"
                conditions.append(
                    "(r.display_name LIKE ? OR r.description LIKE ? "
                    "OR r.url_or_path LIKE ?)"
                )
                params.extend([tok, tok, tok])
            if resource_type:
                conditions.append("r.resource_type=?")
                params.append(resource_type)
            if tag:
                conditions.append(
                    "r.id IN (SELECT resource_id FROM resource_tags WHERE tag=?)"
                )
                params.append(tag)
            where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
            return conn.execute(
                f"SELECT r.* FROM resources r {where} ORDER BY r.display_name",
                params,
            ).fetchall()

    def add_resource(self, data: dict) -> int:
        cols = [
            "resource_type", "display_name", "description",
            "url_or_path", "file_data", "method_book_title",
            "method_book_pages", "music_id", "notes",
        ]
        values = [data.get(c) for c in cols]
        placeholders = ",".join(["?"] * len(cols))
        col_str = ",".join(cols)
        with self._connect() as conn:
            cur = conn.execute(
                f"INSERT INTO resources ({col_str}) VALUES ({placeholders})",
                values,
            )
            resource_id = cur.lastrowid
            # Insert tags if provided
            tags = data.get("tags", [])
            for tag in tags:
                conn.execute(
                    "INSERT INTO resource_tags (resource_id, tag) VALUES (?, ?)",
                    (resource_id, tag),
                )
            return resource_id

    def update_resource(self, resource_id: int, data: dict):
        cols = [
            "resource_type", "display_name", "description",
            "url_or_path", "file_data", "method_book_title",
            "method_book_pages", "music_id", "notes",
        ]
        set_clause = ", ".join([f"{c}=?" for c in cols])
        values = [data.get(c) for c in cols] + [resource_id]
        with self._connect() as conn:
            conn.execute(
                f"UPDATE resources SET {set_clause} WHERE id=?", values
            )
            # Replace tags if provided
            if "tags" in data:
                conn.execute(
                    "DELETE FROM resource_tags WHERE resource_id=?",
                    (resource_id,),
                )
                for tag in data["tags"]:
                    conn.execute(
                        "INSERT INTO resource_tags (resource_id, tag) VALUES (?, ?)",
                        (resource_id, tag),
                    )

    def delete_resource(self, resource_id: int):
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM resource_tags WHERE resource_id=?", (resource_id,)
            )
            conn.execute(
                "DELETE FROM lesson_plan_resources WHERE resource_id=?",
                (resource_id,),
            )
            conn.execute("DELETE FROM resources WHERE id=?", (resource_id,))

    def get_resource_tags(self, resource_id: int) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT tag FROM resource_tags WHERE resource_id=? ORDER BY tag",
                (resource_id,),
            ).fetchall()
        return [r["tag"] for r in rows]

    def get_all_tags(self) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT DISTINCT tag FROM resource_tags ORDER BY tag"
            ).fetchall()
        return [r["tag"] for r in rows]

    # ─── Lesson Plan ↔ Resource Links ────────────────────────────────────────

    def link_resource_to_plan(self, lesson_plan_id: int, resource_id: int,
                              block_id: int = None):
        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO lesson_plan_resources "
                "(lesson_plan_id, resource_id, block_id) VALUES (?, ?, ?)",
                (lesson_plan_id, resource_id, block_id),
            )

    def unlink_resource_from_plan(self, lesson_plan_id: int, resource_id: int):
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM lesson_plan_resources "
                "WHERE lesson_plan_id=? AND resource_id=?",
                (lesson_plan_id, resource_id),
            )

    def get_resources_for_plan(self, lesson_plan_id: int):
        with self._connect() as conn:
            return conn.execute(
                "SELECT r.*, lpr.block_id FROM resources r "
                "JOIN lesson_plan_resources lpr ON lpr.resource_id = r.id "
                "WHERE lpr.lesson_plan_id=? ORDER BY r.display_name",
                (lesson_plan_id,),
            ).fetchall()

    # ─── Lesson Plan Templates CRUD ──────────────────────────────────────────

    def get_all_templates(self, template_type: str = None):
        with self._connect() as conn:
            if template_type:
                return conn.execute(
                    "SELECT * FROM lesson_templates WHERE template_type=? "
                    "ORDER BY display_name",
                    (template_type,),
                ).fetchall()
            return conn.execute(
                "SELECT * FROM lesson_templates ORDER BY template_type, display_name"
            ).fetchall()

    def get_template(self, template_id: int):
        with self._connect() as conn:
            return conn.execute(
                "SELECT * FROM lesson_templates WHERE id=?", (template_id,)
            ).fetchone()

    def add_template(self, data: dict) -> int:
        cols = [
            "template_type", "display_name", "description",
            "content_json", "ensemble_type", "notes",
        ]
        values = [data.get(c) for c in cols]
        placeholders = ",".join(["?"] * len(cols))
        col_str = ",".join(cols)
        with self._connect() as conn:
            cur = conn.execute(
                f"INSERT INTO lesson_templates ({col_str}) VALUES ({placeholders})",
                values,
            )
            return cur.lastrowid

    def update_template(self, template_id: int, data: dict):
        cols = [
            "template_type", "display_name", "description",
            "content_json", "ensemble_type", "notes",
        ]
        set_clause = ", ".join([f"{c}=?" for c in cols])
        values = [data.get(c) for c in cols] + [template_id]
        with self._connect() as conn:
            conn.execute(
                f"UPDATE lesson_templates SET {set_clause} WHERE id=?", values
            )

    def delete_template(self, template_id: int):
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM lesson_templates WHERE id=?", (template_id,)
            )

    # ─── Lesson Plan Stats ───────────────────────────────────────────────────

    def get_lesson_plan_stats(self) -> dict:
        """Get summary stats for the lesson plans module."""
        with self._connect() as conn:
            classes = conn.execute(
                "SELECT COUNT(*) FROM teaching_classes WHERE is_active=1"
            ).fetchone()[0]
            curriculum_items = conn.execute(
                "SELECT COUNT(*) FROM curriculum_items"
            ).fetchone()[0]
            lesson_plans = conn.execute(
                "SELECT COUNT(*) FROM lesson_plans"
            ).fetchone()[0]
            resources = conn.execute(
                "SELECT COUNT(*) FROM resources"
            ).fetchone()[0]
            upcoming_concerts = conn.execute(
                "SELECT COUNT(*) FROM concert_dates WHERE concert_date >= date('now')"
            ).fetchone()[0]
        return {
            "classes": classes,
            "curriculum_items": curriculum_items,
            "lesson_plans": lesson_plans,
            "resources": resources,
            "upcoming_concerts": upcoming_concerts,
        }

    # ─── OneNote Sync CRUD ───────────────────────────────────────────────────

    def get_onenote_sync(self, class_id: int):
        """Get the OneNote sync config for a class (if any)."""
        with self._connect() as conn:
            return conn.execute(
                "SELECT * FROM onenote_sync WHERE class_id=? ORDER BY id DESC LIMIT 1",
                (class_id,),
            ).fetchone()

    def get_all_onenote_syncs(self):
        """Get all active OneNote sync configs."""
        with self._connect() as conn:
            return conn.execute(
                "SELECT os.*, tc.class_name FROM onenote_sync os "
                "JOIN teaching_classes tc ON tc.id = os.class_id "
                "WHERE os.sync_enabled=1 ORDER BY tc.class_name"
            ).fetchall()

    def save_onenote_sync(self, data: dict) -> int:
        """Create or update a OneNote sync config."""
        cols = [
            "class_id", "notebook_id", "notebook_name",
            "section_id", "section_name", "start_date", "end_date",
            "sync_enabled", "last_sync_at", "sync_direction",
        ]
        # Check if one already exists for this class
        existing = self.get_onenote_sync(data.get("class_id"))
        if existing:
            set_clause = ", ".join([f"{c}=?" for c in cols])
            values = [data.get(c) for c in cols] + [existing["id"]]
            with self._connect() as conn:
                conn.execute(
                    f"UPDATE onenote_sync SET {set_clause} WHERE id=?", values
                )
            return existing["id"]
        else:
            values = [data.get(c) for c in cols]
            placeholders = ",".join(["?"] * len(cols))
            col_str = ",".join(cols)
            with self._connect() as conn:
                cur = conn.execute(
                    f"INSERT INTO onenote_sync ({col_str}) VALUES ({placeholders})",
                    values,
                )
                return cur.lastrowid

    def update_sync_timestamp(self, sync_id: int):
        """Update the last_sync_at timestamp."""
        with self._connect() as conn:
            conn.execute(
                "UPDATE onenote_sync SET last_sync_at=datetime('now') WHERE id=?",
                (sync_id,),
            )

    def disable_onenote_sync(self, class_id: int):
        """Disable sync for a class."""
        with self._connect() as conn:
            conn.execute(
                "UPDATE onenote_sync SET sync_enabled=0 WHERE class_id=?",
                (class_id,),
            )
