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


# Rosters spell an instrument every way a human would: "Violin", "violin",
# "Violin 1", "1st Violin", "Violin II".  Filters have to see through all of
# that, or a section quietly comes back empty.
_INSTR_PART_SUFFIX = re.compile(r"\s*(?:#\s*)?([1-4]|i{1,3}|iv)$", re.IGNORECASE)
_INSTR_PART_PREFIX = re.compile(r"^([1-4])(?:st|nd|rd|th)\s+", re.IGNORECASE)
_ROMAN_PARTS = {"i": "1", "ii": "2", "iii": "3", "iv": "4"}


def split_instrument(name: str):
    """Split an instrument into (base, part), e.g. "1st Violin" -> ("violin", "1").
    Part is "" when the name doesn't name a chair/division."""
    s = " ".join((name or "").strip().lower().split())
    if not s:
        return "", ""
    part = ""
    m = _INSTR_PART_PREFIX.match(s)
    if m:
        part = m.group(1)
        s = s[m.end():].strip()
    m = _INSTR_PART_SUFFIX.search(s)
    if m:
        tok = m.group(1).lower()
        part = _ROMAN_PARTS.get(tok, tok)
        s = s[:m.start()].strip()
    return s, part


def instrument_matches(wanted: str, stored: str) -> bool:
    """Does a student's instrument satisfy an instrument filter?  Asking for
    "Violin" includes Violin 1 and Violin 2; asking for "Violin 1" does not
    include the seconds."""
    wb, wp = split_instrument(wanted)
    sb, sp = split_instrument(stored)
    if not wb or not sb or wb != sb:
        return False
    return not wp or wp == sp


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


def _fee_description(fee_type: str) -> str:
    """The part of a fee that is not already in another column.

    "Instrument Rental (School Year)" sits next to a Category of "Instrument
    Rental Fees", so the words that earn their place are the ones in brackets.
    Anything else keeps its own name.
    """
    name = (fee_type or "Student Fee").strip()
    if name.lower().startswith("instrument rental"):
        if "(" in name and ")" in name:
            return name[name.index("(") + 1:name.rindex(")")].strip()
        return "Rental"
    return name


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
                    category TEXT,        -- family: Strings, Woodwind, Brass, …
                    description TEXT,     -- the instrument: Viola, Trumpet - Bb
                    size TEXT,            -- 3/4, 1/2, 14" — its own field so it
                                          -- stays sortable and never has to be
                                          -- squeezed into the name

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
            # Migrate: add size (3/4, 1/2, 14") so string inventories can record
            # it without hiding it inside the category or the description
            try:
                conn.execute("ALTER TABLE instruments ADD COLUMN size TEXT")
                conn.commit()
            except Exception:
                pass  # Column already exists
            # Migrate: invoice number + vendor on a budget line, so a purchase
            # can be matched back to the paperwork it came from
            for col in ("invoice_no TEXT", "vendor TEXT"):
                try:
                    conn.execute(f"ALTER TABLE budget_transactions ADD COLUMN {col}")
                    conn.commit()
                except Exception:
                    pass  # Column already exists
            # Migrate: a Books category for method and class books.  The seed
            # list only runs on an empty database, so existing profiles need
            # this added explicitly.
            try:
                have = conn.execute(
                    "SELECT 1 FROM budget_categories WHERE LOWER(name)='books' "
                    "AND kind='expense'").fetchone()
                if not have:
                    conn.execute(
                        "INSERT INTO budget_categories (name, kind) "
                        "VALUES ('Books', 'expense')")
                    conn.commit()
            except Exception:
                pass
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
                        invoice_no TEXT,          -- both optional, for matching
                        vendor TEXT,              -- a purchase back to paperwork
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
                        # Method and class books, separate from performance
                        # repertoire — every program buys them.
                        ("Books", "expense"),
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

            # Migrate: uniform / attire inventory + assignments.  Mirrors the
            # instruments + checkouts pair but for garments (marching jackets,
            # pants, shakos, rain gear, and — for choir/orchestra later — robes,
            # dresses, tuxes, etc.).  Unlike instruments, a garment piece can be
            # assigned to only ONE student at a time (enforced in checkout_uniform),
            # and no rental fee is auto-added.  garment_types is a user-definable
            # list so any ensemble can define its own clothing items.
            try:
                conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS garment_types (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT NOT NULL,
                        sort_order INTEGER DEFAULT 0,
                        is_active INTEGER DEFAULT 1
                    );
                    CREATE TABLE IF NOT EXISTS uniforms (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        garment_type TEXT,        -- e.g. 'Marching Jacket' (see garment_types)
                        item_number TEXT,         -- the number kids remember, e.g. '158'
                        size TEXT,
                        style TEXT,
                        gender TEXT,
                        color TEXT,
                        manufacturer TEXT,
                        barcode TEXT,
                        location TEXT,
                        condition TEXT,
                        date_last_cleaned TEXT,
                        date_purchased TEXT,
                        purchase_price REAL DEFAULT 0,
                        comments TEXT,
                        is_active INTEGER DEFAULT 1,
                        created_at TEXT DEFAULT CURRENT_TIMESTAMP
                    );
                    CREATE TABLE IF NOT EXISTS uniform_checkouts (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        uniform_id INTEGER NOT NULL,
                        student_id INTEGER,
                        student_name TEXT,
                        date_assigned TEXT,
                        date_returned TEXT,
                        due_date TEXT,
                        notes TEXT,
                        form_generated INTEGER DEFAULT 0,
                        FOREIGN KEY (uniform_id) REFERENCES uniforms(id),
                        FOREIGN KEY (student_id) REFERENCES students(id)
                    );
                    CREATE INDEX IF NOT EXISTS idx_uniform_checkouts_uniform
                        ON uniform_checkouts(uniform_id);
                    CREATE INDEX IF NOT EXISTS idx_uniform_checkouts_student
                        ON uniform_checkouts(student_id);
                    """
                )
                conn.commit()
            except Exception:
                pass

            # ── Migrate: school sites ──────────────────────────────────────
            # A teacher is not necessarily posted to one building.  Itinerant
            # elementary specialists carry up to six schools, and some
            # secondary directors hold a high school, a middle school and two
            # elementaries between them.  Each building owns its own
            # instruments, so an instrument and the child borrowing it have to
            # belong to the same place -- see _assert_same_site.
            #
            # "level" is secondary or elementary; it decides which tools a site
            # is shown, not how its rows are stored.  "program" is band or
            # orchestra and belongs here rather than in a class name, because
            # one teacher cannot run both at one school: the sections meet in
            # the same slot and nobody is in two rooms at once.
            try:
                conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS sites (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT NOT NULL,
                        level TEXT DEFAULT 'secondary',
                        program TEXT,
                        charges_fees INTEGER DEFAULT 1,
                        is_active INTEGER DEFAULT 1,
                        created_at TEXT DEFAULT CURRENT_TIMESTAMP
                    );
                    CREATE INDEX IF NOT EXISTS idx_sites_active ON sites(is_active);
                    """
                )
                conn.commit()
            except Exception:
                pass
            # Some elementary schools run a choir before or after school and
            # simply put the whole 5th grade in it.  When that is true, ticking
            # every child by hand is a hundred clicks nobody should make.
            try:
                conn.execute("ALTER TABLE sites ADD COLUMN choir_default INTEGER DEFAULT 0")
                conn.commit()
            except Exception:
                pass
            for _t in ("instruments", "students"):
                try:
                    conn.execute(f"ALTER TABLE {_t} ADD COLUMN site_id INTEGER")
                    conn.commit()
                except Exception:
                    pass  # Column already exists
                try:
                    conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{_t}_site "
                                 f"ON {_t}(site_id)")
                    conn.commit()
                except Exception:
                    pass

            # First run on an existing profile: the teacher already has a
            # school, so turn it into their one site rather than asking again.
            try:
                if not conn.execute("SELECT 1 FROM sites LIMIT 1").fetchone():
                    name, level, program = self._school_from_settings()
                    if name:
                        conn.execute(
                            "INSERT INTO sites (name, level, program, charges_fees) "
                            "VALUES (?, ?, ?, 1)", (name, level, program))
                        conn.commit()
            except Exception:
                pass

            # Stamp anything unassigned -- but only when there is exactly one
            # site to stamp it with.  With one school there is no ambiguity;
            # with several there is nothing to infer from, and a wrong guess
            # here is what puts one school's trumpet in another school's list.
            try:
                sites = conn.execute(
                    "SELECT id FROM sites WHERE is_active = 1").fetchall()
                if len(sites) == 1:
                    only = sites[0]["id"]
                    for _t in ("instruments", "students"):
                        conn.execute(
                            f"UPDATE {_t} SET site_id = ? WHERE site_id IS NULL",
                            (only,))
                    conn.commit()
            except Exception:
                pass

    # ─── Sites (the schools this teacher is posted to) ─────────────────────────

    def _school_from_settings(self):
        """(name, level, program) for the school already in Settings.

        Used once, to turn an existing single-school profile into its first
        site without asking the teacher to type anything she has typed before.
        """
        import os as _os
        base_dir = _os.path.dirname(self.db_path)
        try:
            from ui.settings_dialog import school_name, load_settings
            name = school_name(base_dir)
            teacher = (load_settings(base_dir) or {}).get("teacher") or {}
            program = (teacher.get("program_type") or "").strip() or None
        except Exception:
            return ("", "secondary", None)
        if program == "elementary":
            # The old single "elementary" focus never recorded band or
            # orchestra, so there is nothing truthful to put here.  Left unset
            # for the teacher to choose; guessing "band" is the assumption
            # that sent orchestra teachers a band class list.
            return (name, "elementary", None)
        return (name, "secondary", program)

    ELEMENTARY = "elementary"
    SECONDARY = "secondary"

    def get_sites(self, include_inactive: bool = False, level: str = None):
        sql = "SELECT * FROM sites"
        where, params = [], []
        if not include_inactive:
            where.append("is_active = 1")
        if level:
            where.append("level = ?")
            params.append(level)
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY level DESC, name"
        with self._connect() as conn:
            return conn.execute(sql, params).fetchall()

    def get_site(self, site_id: int):
        if not site_id:
            return None
        with self._connect() as conn:
            return conn.execute("SELECT * FROM sites WHERE id = ?",
                                (site_id,)).fetchone()

    def add_site(self, name: str, level: str = "secondary", program: str = None,
                 charges_fees: bool = None, choir_default: bool = False) -> int:
        """Add a school.  Elementary loans carry no fee unless told otherwise --
        the district's elementary form says so in as many words."""
        if charges_fees is None:
            charges_fees = (level != self.ELEMENTARY)
        name = (name or "").strip()
        with self._connect() as conn:
            # Two schools with the same name is never what anybody meant, and a
            # twin is worse than useless -- its instruments and children are
            # split across two tabs with identical labels.  Adding a school
            # that is already here, including one retired earlier, brings that
            # one back rather than making a second.
            existing = conn.execute(
                "SELECT id FROM sites WHERE lower(trim(name)) = lower(?)",
                (name,)).fetchone()
            if existing:
                conn.execute(
                    "UPDATE sites SET is_active = 1, level = ?, program = ?, "
                    "charges_fees = ?, choir_default = ? WHERE id = ?",
                    (level, program, 1 if charges_fees else 0,
                     1 if choir_default else 0, existing["id"]))
                conn.commit()
                return existing["id"]
            cur = conn.execute(
                "INSERT INTO sites (name, level, program, charges_fees, "
                "choir_default) VALUES (?, ?, ?, ?, ?)",
                (name, level, program, 1 if charges_fees else 0,
                 1 if choir_default else 0))
            conn.commit()
            return cur.lastrowid

    def update_site(self, site_id: int, **fields):
        allowed = ("name", "level", "program", "charges_fees", "is_active",
                   "choir_default")
        sets = [(k, v) for k, v in fields.items() if k in allowed]
        if not sets:
            return
        with self._connect() as conn:
            conn.execute(
                "UPDATE sites SET " + ", ".join(f"{k} = ?" for k, _ in sets)
                + " WHERE id = ?", [v for _, v in sets] + [site_id])
            conn.commit()

    def restore_site(self, site_id: int) -> dict:
        """Bring a school back, with its instruments but NOT its old children.

        A school comes back after a year or two away, and the children who were
        in its 5th grade then are in secondary school now.  Carrying them
        forward would hand the returning teacher a roster of people who left,
        so the roster starts empty and the new class lists fill it.

        The instruments stay, because a cupboard does not empty itself -- but
        anything still checked out to one of those children is returned, or the
        cupboard would look fuller on paper than it is on the shelf.
        """
        with self._connect() as conn:
            conn.execute("UPDATE sites SET is_active = 1 WHERE id = ?", (site_id,))
            returned = conn.execute(
                "UPDATE checkouts SET date_returned = date('now') "
                "WHERE date_returned IS NULL AND student_id IN "
                "(SELECT id FROM students WHERE site_id = ?)", (site_id,)).rowcount
            cleared = conn.execute(
                "UPDATE students SET is_active = 0 WHERE site_id = ? AND is_active = 1",
                (site_id,)).rowcount
            instruments = conn.execute(
                "SELECT COUNT(*) n FROM instruments WHERE site_id = ? AND is_active = 1",
                (site_id,)).fetchone()["n"]
            conn.commit()
        return {"students_cleared": cleared, "checkouts_returned": returned,
                "instruments": instruments}

    def archive_site(self, site_id: int):
        """Archive a school without deleting it.  An assignment ending does not
        make last year's checkout history untrue, and the handoff export still
        needs to read it."""
        self.update_site(site_id, is_active=0)

    # Old name, kept so nothing calling it breaks.
    deactivate_site = archive_site

    def default_site_id(self):
        """The site to assume when nothing says otherwise -- only meaningful
        for a teacher at one school.  None once there is a choice to make, so
        callers are forced to ask rather than quietly pick the first."""
        rows = self.get_sites()
        return rows[0]["id"] if len(rows) == 1 else None

    def site_charges_fees(self, site_id) -> bool:
        site = self.get_site(site_id)
        return bool(site["charges_fees"]) if site else True

    def _student_site_charges_fees(self, student_id) -> bool:
        """Does this child's school charge for an instrument loan?  Unknown
        sites keep the old behavior and charge, so nothing silently stops
        billing on a profile that has not set its schools up yet."""
        if not student_id:
            return True
        try:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT s.charges_fees AS cf FROM students st "
                    "JOIN sites s ON s.id = st.site_id WHERE st.id = ?",
                    (student_id,)).fetchone()
            return bool(row["cf"]) if row else True
        except Exception:
            return True

    @staticmethod
    def _site_scope(alias: str, site_id=None, level: str = None):
        """(sql, params) restricting a query to one school, or to one level.

        Rows with no site are treated as belonging to the level being asked
        for, never excluded.  A profile part-way through the migration, or one
        whose owner has not opened the Schools tab, still has unstamped rows;
        dropping those would empty the inventory list, which is a far worse
        failure than showing one row too many.
        """
        col = f"{alias}.site_id"
        if site_id:
            return f" AND {col} = ?", [site_id]
        if level:
            return (f" AND ({col} IS NULL OR {col} IN "
                    f"(SELECT id FROM sites WHERE level = ?))", [level])
        return "", []

    def _assert_same_site(self, conn, instrument_id: int, student_id: int):
        """Refuse to lend one school's instrument to another school's child.

        This lives here rather than in a screen on purpose.  A filter left on
        the wrong setting is how the mistake happens, and no dialog can be
        relied on to be the only route to a checkout -- the bulk scanner and
        the carry-over both write straight through.

        A site that is not yet known is not treated as a mismatch: profiles
        mid-migration have unstamped rows, and refusing those would break
        checkouts that are perfectly fine today.
        """
        if not student_id or not instrument_id:
            return
        row = conn.execute(
            "SELECT (SELECT site_id FROM instruments WHERE id = ?) AS i_site, "
            "       (SELECT site_id FROM students    WHERE id = ?) AS s_site",
            (instrument_id, student_id)).fetchone()
        if not row:
            return
        i_site, s_site = row["i_site"], row["s_site"]
        if i_site is None or s_site is None or i_site == s_site:
            return
        names = {}
        for sid in (i_site, s_site):
            got = conn.execute("SELECT name FROM sites WHERE id = ?",
                               (sid,)).fetchone()
            names[sid] = (got["name"] if got else None) or f"site {sid}"
        raise ValueError(
            f"That instrument belongs to {names[i_site]}, and this student is "
            f"at {names[s_site]}. Each school's instruments stay with that "
            f"school."
        )

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
            "category", "description", "size", "brand", "model", "barcode", "quantity",
            "district_no", "case_no", "condition", "serial_no", "date_purchased",
            "year_purchased", "year_manufactured", "po_number", "last_service", "amount_paid", "est_value",
            "locker", "lock_no", "combo", "comments", "accessories", "site_id"
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
            "category", "description", "size", "brand", "model", "barcode", "quantity",
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

    # ── Inventory layout normalization ────────────────────────────────────
    # The intended layout is category = family ("Strings"), description = the
    # instrument ("Viola"), size = the size ("14""").  An inventory built before
    # there was a size field often reads category "Viola", description 14" —
    # which makes sense to the person who typed it, but means every feature that
    # groups by family, prints a loan form, or prints barcode labels sees a
    # family it does not recognize.

    def find_instrument_layout_issues(self):
        """Instruments whose category holds an instrument name rather than a
        family.  Returns [(row, proposed_category, proposed_description,
        proposed_size)] so the change can be shown before it is made."""
        import instrument_sizes as isz
        families = {f.lower() for f in isz.FAMILIES}
        out = []
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM instruments WHERE is_active=1").fetchall()
        for r in rows:
            cat = (r["category"] or "").strip()
            desc = (r["description"] or "").strip()
            size = (r["size"] or "").strip()
            if not cat or cat.lower() in families:
                continue                      # already a family; nothing to do
            family = isz.family_for(cat)
            if not family:
                continue                      # not an instrument name either
            # The category names the instrument.  The description is either its
            # size or a genuine detail worth keeping on the name.
            if desc and isz.looks_like_size(desc):
                new_desc, new_size = cat, (size or isz.normalize_size(desc))
            elif desc:
                new_desc, new_size = f"{cat} - {desc}", size
            else:
                new_desc, new_size = cat, size
            out.append((r, family, new_desc, new_size))
        return out

    def normalize_instrument_layout(self):
        """Move instrument names out of the category and sizes into their own
        field.  Returns (rows_changed, families_used)."""
        issues = self.find_instrument_layout_issues()
        if not issues:
            return (0, [])
        families = set()
        with self._connect() as conn:
            for row, family, desc, size in issues:
                conn.execute(
                    "UPDATE instruments SET category=?, description=?, size=? "
                    "WHERE id=?", (family, desc, size or None, row["id"]))
                families.add(family)
        return (len(issues), sorted(families))

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

    def get_instruments_with_status(self, include_inactive=False,
                                    site_id=None, level=None):
        """Return instruments with computed status, handling several active
        checkouts per instrument and out-on-loan instruments.  Uses scalar
        subqueries so an instrument is never duplicated in the result."""
        active_filter = "" if include_inactive else "AND i.is_active=1"
        # One school's instruments never appear in another's list -- that is
        # what stops a Sherwood Forest trumpet being offered to a high schooler
        # in the first place, rather than only refusing at the last moment.
        site_filter, site_params = self._site_scope("i", site_id, level)
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
            WHERE 1=1 {active_filter} {site_filter}
            ORDER BY i.category, i.description
        """
        with self._connect() as conn:
            rows = conn.execute(sql, site_params).fetchall()

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

    # ── Carrying instrument assignments into a new year ───────────────────
    # Most students keep the instrument they had, so the new year starts from
    # last year's assignments rather than from nothing.  Everything here is
    # per CHECKOUT, never per student: a tuba player keeps one at school and one
    # at home, and a sax player may have three.

    @staticmethod
    def previous_school_year(school_year: str):
        try:
            start_year = int(str(school_year).split("-")[0])
        except (ValueError, AttributeError, IndexError):
            return ""
        return f"{start_year - 1}-{start_year}"

    def get_assignments_for_school_year(self, school_year: str):
        """Every instrument assignment made during that school year, one row per
        checkout, with the instrument and whether the student is still here."""
        # school_year_bounds is July-to-June and its end date is inclusive.
        start, end = self.school_year_bounds(school_year)
        if not start:
            return []
        with self._connect() as conn:
            return conn.execute(
                """SELECT c.id            AS checkout_id,
                          c.student_id    AS student_id,
                          c.student_name  AS student_name,
                          c.date_assigned AS date_assigned,
                          c.date_returned AS date_returned,
                          c.notes         AS notes,
                          i.id            AS instrument_id,
                          i.category      AS category,
                          i.description   AS description,
                          i.size          AS size,
                          i.brand         AS brand,
                          i.barcode       AS barcode,
                          i.district_no   AS district_no,
                          i.serial_no     AS serial_no,
                          s.grade         AS grade,
                          s.first_name    AS first_name,
                          s.last_name     AS last_name,
                          s.student_id    AS district_id,
                          s.school_year   AS student_year,
                          s.is_active     AS student_active
                     FROM checkouts c
                     JOIN instruments i ON i.id = c.instrument_id
                     LEFT JOIN students s ON s.id = c.student_id
                    WHERE c.date_assigned >= ? AND c.date_assigned <= ?
                      AND i.is_active = 1
                    ORDER BY c.student_name, i.description, i.size""",
                (start, end),
            ).fetchall()

    def find_enrolled_student(self, school_year, district_id="", first="", last="",
                              fallback_id=None):
        """This person's record on `school_year`'s roster, or None if they are
        not on it.

        A checkout stores the student ROW it was made against, and that row is
        last year's.  Whether it is still the right row depends on how the
        roster was brought forward: the class-list import updates a student in
        place, while a district CSV import creates a fresh row for the new year
        and archives the old one.  Following the stored key therefore says
        "this student left" for every returning student in the second case, so
        identity — district ID, then name — is what actually answers the
        question."""
        did = (district_id or "").strip()
        f = (first or "").strip().lower()
        l = (last or "").strip().lower()
        with self._connect() as conn:
            if did:
                row = conn.execute(
                    "SELECT * FROM students WHERE student_id=? AND school_year=? "
                    "AND COALESCE(is_active,1)=1 ORDER BY id DESC LIMIT 1",
                    (did, school_year)).fetchone()
                if row:
                    return row
            if f and l:
                row = conn.execute(
                    "SELECT * FROM students WHERE LOWER(first_name)=? "
                    "AND LOWER(last_name)=? AND school_year=? "
                    "AND COALESCE(is_active,1)=1 ORDER BY id DESC LIMIT 1",
                    (f, l, school_year)).fetchone()
                if row:
                    return row
            if fallback_id is not None:
                row = conn.execute(
                    "SELECT * FROM students WHERE id=? AND school_year=? "
                    "AND COALESCE(is_active,1)=1", (fallback_id, school_year)
                ).fetchone()
                if row:
                    return row
        return None

    def get_available_instruments(self):
        """Active instruments with nothing checked out against them and not out
        on loan to another school."""
        with self._connect() as conn:
            return conn.execute(
                """SELECT i.* FROM instruments i
                    WHERE i.is_active = 1
                      AND NOT EXISTS (SELECT 1 FROM checkouts c
                                       WHERE c.instrument_id = i.id
                                         AND c.date_returned IS NULL)
                      AND NOT EXISTS (SELECT 1 FROM loans l
                                       WHERE l.instrument_id = i.id
                                         AND l.date_returned IS NULL)
                    ORDER BY i.description, i.size, i.barcode""").fetchall()

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

    def get_open_instrument_checkouts(self):
        """Every instrument still out, whoever has it.  Answers "is this one
        already in that student's hands?" in one query, which the carry-over
        screen asks of every row."""
        with self._connect() as conn:
            return conn.execute(
                """SELECT c.id            AS checkout_id,
                          c.instrument_id AS instrument_id,
                          c.student_id    AS student_id,
                          c.student_name  AS student_name,
                          c.date_assigned AS date_assigned,
                          c.notes         AS notes
                     FROM checkouts c
                    WHERE c.date_returned IS NULL OR TRIM(c.date_returned)=''
                    ORDER BY c.id"""
            ).fetchall()

    CARRIED_NOTE = "Carried over to"

    def carry_checkout_into_year(self, checkout_id: int, school_year: str,
                                 due_date: str = ""):
        """Run an open loan on into a new school year.

        A student who kept their instrument over the summer never handed it
        back, so the loan continues rather than being closed and re-opened —
        opening a second one would show the instrument out twice and leave it
        impossible to check in cleanly.  The note is also what tells a second
        run of the carry-over screen that this loan has already been dealt
        with, so nobody is billed for the same instrument twice."""
        marker = f"{self.CARRIED_NOTE} {school_year}"
        with self._connect() as conn:
            row = conn.execute("SELECT notes FROM checkouts WHERE id=?",
                               (checkout_id,)).fetchone()
            if row is None:
                return
            notes = (row["notes"] or "").strip()
            if marker not in notes:
                notes = f"{notes}; {marker}" if notes else marker
            if due_date:
                conn.execute("UPDATE checkouts SET notes=?, due_date=? WHERE id=?",
                             (notes, due_date, checkout_id))
            else:
                conn.execute("UPDATE checkouts SET notes=? WHERE id=?",
                             (notes, checkout_id))

    # ─── Uniforms / attire ──────────────────────────────────────────────────────
    #
    # A parallel inventory to instruments, for marching-band garments (and, later,
    # choir robes / orchestra attire).  Two rules differ from instruments:
    #   1. A garment piece is assigned to only ONE student at a time — there is no
    #      shared-mouthpiece exception, so checkout_uniform refuses a second open
    #      assignment on the same piece.
    #   2. No rental fee is auto-added on checkout.
    _UNIFORM_COLS = [
        "garment_type", "item_number", "size", "style", "gender", "color",
        "manufacturer", "barcode", "location", "condition", "date_last_cleaned",
        "date_purchased", "purchase_price", "comments",
    ]

    def get_garment_types(self, include_inactive=False):
        """User-definable list of garment types (Marching Jacket, Shako, Robe …).
        Falls back to any distinct garment_type values already on uniform rows so
        an imported inventory always has its types listed even before the director
        curates them."""
        with self._connect() as conn:
            filt = "" if include_inactive else "WHERE is_active=1"
            defined = [r["name"] for r in conn.execute(
                f"SELECT name FROM garment_types {filt} ORDER BY sort_order, name"
            ).fetchall()]
            used = [r[0] for r in conn.execute(
                "SELECT DISTINCT garment_type FROM uniforms "
                "WHERE is_active=1 AND garment_type IS NOT NULL AND TRIM(garment_type)!=''"
            ).fetchall()]
        out = list(defined)
        for u in used:
            if u not in out:
                out.append(u)
        return out

    def add_garment_type(self, name: str) -> int:
        name = (name or "").strip()
        if not name:
            return 0
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT id FROM garment_types WHERE LOWER(name)=LOWER(?)", (name,)
            ).fetchone()
            if existing:
                conn.execute("UPDATE garment_types SET is_active=1 WHERE id=?",
                             (existing["id"],))
                return existing["id"]
            nxt = conn.execute(
                "SELECT COALESCE(MAX(sort_order),0)+1 FROM garment_types"
            ).fetchone()[0]
            cur = conn.execute(
                "INSERT INTO garment_types (name, sort_order) VALUES (?, ?)",
                (name, nxt))
            return cur.lastrowid

    def rename_garment_type(self, old_name: str, new_name: str):
        old_name, new_name = (old_name or "").strip(), (new_name or "").strip()
        if not old_name or not new_name:
            return
        with self._connect() as conn:
            conn.execute("UPDATE garment_types SET name=? WHERE LOWER(name)=LOWER(?)",
                         (new_name, old_name))
            conn.execute("UPDATE uniforms SET garment_type=? WHERE garment_type=?",
                         (new_name, old_name))

    def delete_garment_type(self, name: str):
        """Soft-remove a type from the list.  Existing uniform rows keep their
        garment_type text, so nothing in inventory is lost."""
        with self._connect() as conn:
            conn.execute("UPDATE garment_types SET is_active=0 WHERE LOWER(name)=LOWER(?)",
                         ((name or "").strip(),))

    def get_all_uniforms(self, include_inactive=False):
        with self._connect() as conn:
            if include_inactive:
                return conn.execute(
                    "SELECT * FROM uniforms ORDER BY garment_type, item_number"
                ).fetchall()
            return conn.execute(
                "SELECT * FROM uniforms WHERE is_active=1 "
                "ORDER BY garment_type, item_number"
            ).fetchall()

    def get_uniform(self, uniform_id: int):
        with self._connect() as conn:
            return conn.execute(
                "SELECT * FROM uniforms WHERE id=?", (uniform_id,)
            ).fetchone()

    def get_uniform_by_barcode(self, barcode: str):
        """First active garment matching barcode, or (garment_type + item_number)
        typed as 'Jacket 158' won't match here — barcode/exact only."""
        with self._connect() as conn:
            return conn.execute(
                "SELECT * FROM uniforms WHERE is_active=1 AND barcode=? LIMIT 1",
                (barcode,)
            ).fetchone()

    def add_uniform(self, data: dict) -> int:
        cols = self._UNIFORM_COLS
        values = [data.get(c) for c in cols]
        placeholders = ",".join(["?"] * len(cols))
        with self._connect() as conn:
            cur = conn.execute(
                f"INSERT INTO uniforms ({','.join(cols)}) VALUES ({placeholders})",
                values)
            return cur.lastrowid

    def update_uniform(self, uniform_id: int, data: dict):
        cols = self._UNIFORM_COLS + ["is_active"]
        set_clause = ", ".join([f"{c}=?" for c in cols])
        values = [data.get(c) for c in cols] + [uniform_id]
        with self._connect() as conn:
            conn.execute(
                f"UPDATE uniforms SET {set_clause} WHERE id=?", values)

    def deactivate_uniform(self, uniform_id: int):
        with self._connect() as conn:
            conn.execute("UPDATE uniforms SET is_active=0 WHERE id=?", (uniform_id,))

    def get_uniforms_with_status(self, include_inactive=False):
        """Uniform rows with computed 'Available'/'Checked Out' status and the
        current holder's name.  One open checkout max per piece, so no counting
        gymnastics are needed."""
        active_filter = "" if include_inactive else "AND u.is_active=1"
        sql = f"""
            SELECT
                u.*,
                (SELECT c.student_name FROM uniform_checkouts c
                    WHERE c.uniform_id = u.id AND c.date_returned IS NULL
                    ORDER BY c.id DESC LIMIT 1) AS checkout_name,
                (SELECT c.date_assigned FROM uniform_checkouts c
                    WHERE c.uniform_id = u.id AND c.date_returned IS NULL
                    ORDER BY c.id DESC LIMIT 1) AS checkout_date
            FROM uniforms u
            WHERE 1=1 {active_filter}
            ORDER BY u.garment_type, CAST(u.item_number AS INTEGER), u.item_number
        """
        with self._connect() as conn:
            rows = conn.execute(sql).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            if (d.get("checkout_name") or "").strip():
                d["status"] = "Checked Out"
                d["checked_out_to"] = d["checkout_name"]
            else:
                d["status"] = "Available"
                d["checked_out_to"] = ""
            out.append(d)
        return out

    def checkout_uniform(self, uniform_id: int, student_id, student_name: str,
                         date_assigned: str, notes: str = "", due_date: str = "") -> int:
        """Assign a garment piece to a student.  Refuses if the piece is already
        out to someone (one piece → one kid).  No rental fee side effect."""
        with self._connect() as conn:
            open_row = conn.execute(
                "SELECT id, student_name FROM uniform_checkouts "
                "WHERE uniform_id=? AND date_returned IS NULL LIMIT 1",
                (uniform_id,)
            ).fetchone()
            if open_row:
                raise ValueError(
                    f"That garment is already checked out to "
                    f"{open_row['student_name'] or 'another student'}. "
                    f"Check it in first.")
            cur = conn.execute(
                """INSERT INTO uniform_checkouts
                   (uniform_id, student_id, student_name, date_assigned, notes, due_date)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (uniform_id, student_id, student_name, date_assigned, notes, due_date))
            return cur.lastrowid

    def import_open_uniform_checkout(self, uniform_id: int, student_id,
                                     student_name: str, date_assigned: str) -> int:
        """Recreate a current (open) garment assignment during a data import,
        skipping pieces that already have one so re-running is safe."""
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT id FROM uniform_checkouts WHERE uniform_id=? AND "
                "(date_returned IS NULL OR TRIM(date_returned)='')",
                (uniform_id,)).fetchone()
            if existing:
                return existing["id"]
            cur = conn.execute(
                "INSERT INTO uniform_checkouts (uniform_id, student_id, "
                "student_name, date_assigned) VALUES (?, ?, ?, ?)",
                (uniform_id, student_id, student_name, date_assigned))
            return cur.lastrowid

    def checkin_uniform(self, checkout_id: int, date_returned: str, notes: str = ""):
        with self._connect() as conn:
            conn.execute(
                "UPDATE uniform_checkouts SET date_returned=?, notes=? WHERE id=?",
                (date_returned, notes, checkout_id))

    def get_active_uniform_checkout(self, uniform_id: int):
        with self._connect() as conn:
            return conn.execute(
                """SELECT c.*, s.grade, s.phone, s.parent1_name, s.parent1_phone
                   FROM uniform_checkouts c
                   LEFT JOIN students s ON s.id = c.student_id
                   WHERE c.uniform_id=? AND c.date_returned IS NULL
                   ORDER BY c.id DESC LIMIT 1""",
                (uniform_id,)
            ).fetchone()

    def get_uniform_checkout_history(self, uniform_id: int):
        with self._connect() as conn:
            return conn.execute(
                "SELECT * FROM uniform_checkouts WHERE uniform_id=? "
                "ORDER BY date_assigned DESC, id DESC",
                (uniform_id,)
            ).fetchall()

    def get_all_active_uniform_checkouts(self):
        with self._connect() as conn:
            return conn.execute(
                """SELECT c.*, u.garment_type, u.item_number, u.size, u.barcode
                   FROM uniform_checkouts c
                   JOIN uniforms u ON u.id = c.uniform_id
                   WHERE c.date_returned IS NULL
                   ORDER BY c.student_name"""
            ).fetchall()

    def mark_uniform_form_generated(self, checkout_id: int):
        with self._connect() as conn:
            conn.execute("UPDATE uniform_checkouts SET form_generated=1 WHERE id=?",
                         (checkout_id,))

    def get_uniform_stats(self) -> dict:
        with self._connect() as conn:
            total = conn.execute(
                "SELECT COUNT(*) FROM uniforms WHERE is_active=1").fetchone()[0]
            checked_out = conn.execute(
                """SELECT COUNT(*) FROM uniform_checkouts c
                   JOIN uniforms u ON u.id=c.uniform_id
                   WHERE c.date_returned IS NULL AND u.is_active=1"""
            ).fetchone()[0]
        return {
            "total": total,
            "checked_out": checked_out,
            "available": total - checked_out,
        }

    def get_uniform_chart(self, school_year=None):
        """Data for the 'who has which garment' chart: for every current student,
        the item_number they hold in each garment type (blank where unassigned).
        Returns (garment_types, rows) where each row is
        {student, grade, assignments: {garment_type: item_number}}.
        Only OPEN assignments count.  Also surfaces any assigned holder whose name
        isn't on the current roster (e.g. a still-out piece from a former student)
        so nothing is silently dropped."""
        types = self.get_garment_types()
        roster = self.get_current_roster()
        # Map open assignments by holder name -> {garment_type: item_number}
        with self._connect() as conn:
            open_rows = conn.execute(
                """SELECT c.student_id, c.student_name, u.garment_type, u.item_number
                   FROM uniform_checkouts c
                   JOIN uniforms u ON u.id = c.uniform_id
                   WHERE c.date_returned IS NULL"""
            ).fetchall()

        def _key(name):
            return (name or "").strip().lower()

        by_name = {}
        by_id = {}
        for r in open_rows:
            entry = None
            if r["student_id"] is not None:
                entry = by_id.setdefault(r["student_id"], {})
            else:
                entry = by_name.setdefault(_key(r["student_name"]), {})
            gt = r["garment_type"] or "(unspecified)"
            if r["item_number"]:
                entry[gt] = r["item_number"]

        try:
            from ui.names import display_full  # local import; UI layer optional
        except Exception:
            def display_full(s):
                return f"{s.get('first_name','')} {s.get('last_name','')}".strip()
        rows = []
        seen_ids = set()
        seen_names = set()
        for s in sorted(roster, key=lambda x: ((x.get("last_name") or "").lower(),
                                               (x.get("first_name") or "").lower())):
            assignments = {}
            if s["id"] in by_id:
                assignments = by_id[s["id"]]
                seen_ids.add(s["id"])
            name_key = _key(f"{s.get('first_name','')} {s.get('last_name','')}")
            if name_key in by_name:
                for k, v in by_name[name_key].items():
                    assignments.setdefault(k, v)
                seen_names.add(name_key)
            try:
                disp = display_full(s)
            except Exception:
                disp = f"{s.get('last_name','')}, {s.get('first_name','')}"
            rows.append({
                "student": disp,
                "grade": s.get("grade") or "",
                "assignments": assignments,
            })
        # Holders not on the current roster but still holding gear
        for r in open_rows:
            if r["student_id"] is not None and r["student_id"] in seen_ids:
                continue
            if r["student_id"] is None and _key(r["student_name"]) in seen_names:
                continue
            nm = (r["student_name"] or "").strip()
            if not nm:
                continue
            # find or create a row for this off-roster holder
            existing = next((x for x in rows if x["student"] == nm + " (not on roster)"), None)
            if not existing:
                existing = {"student": nm + " (not on roster)", "grade": "",
                            "assignments": {}}
                rows.append(existing)
            gt = r["garment_type"] or "(unspecified)"
            if r["item_number"]:
                existing["assignments"][gt] = r["item_number"]
        return types, rows

    def get_last_uniform_for_student(self, student_id, student_name: str,
                                     garment_type: str):
        """Most recent garment of *garment_type* this student has held (open or
        returned) — powers the 'what did they have last year' + size-up
        suggestion.  Matches by student_id first, then by name."""
        with self._connect() as conn:
            row = None
            if student_id is not None:
                row = conn.execute(
                    """SELECT u.item_number, u.size, c.date_assigned
                       FROM uniform_checkouts c JOIN uniforms u ON u.id=c.uniform_id
                       WHERE c.student_id=? AND u.garment_type=?
                       ORDER BY c.date_assigned DESC, c.id DESC LIMIT 1""",
                    (student_id, garment_type)).fetchone()
            if row is None and student_name:
                row = conn.execute(
                    """SELECT u.item_number, u.size, c.date_assigned
                       FROM uniform_checkouts c JOIN uniforms u ON u.id=c.uniform_id
                       WHERE LOWER(c.student_name)=LOWER(?) AND u.garment_type=?
                       ORDER BY c.date_assigned DESC, c.id DESC LIMIT 1""",
                    (student_name.strip(), garment_type)).fetchone()
            return row

    def get_available_uniforms_of_type(self, garment_type: str):
        """Active, currently-unassigned pieces of a garment type — the pool the
        size-up suggestion draws from."""
        with self._connect() as conn:
            return conn.execute(
                """SELECT u.* FROM uniforms u
                   WHERE u.is_active=1 AND u.garment_type=?
                     AND NOT EXISTS (SELECT 1 FROM uniform_checkouts c
                         WHERE c.uniform_id=u.id AND c.date_returned IS NULL)
                   ORDER BY CAST(u.item_number AS INTEGER), u.item_number""",
                (garment_type,)).fetchall()

    def checkin_uniforms_for_inactive_students(self, date_returned: str) -> int:
        """Close open garment assignments held by students who are no longer
        active (graduated / left).  Used at year rollover so leftover gear from
        departed students frees up, while returning students KEEP their pieces.
        Returns how many were checked in."""
        with self._connect() as conn:
            open_rows = conn.execute(
                """SELECT c.id, c.student_id FROM uniform_checkouts c
                   WHERE c.date_returned IS NULL AND c.student_id IS NOT NULL"""
            ).fetchall()
            n = 0
            for r in open_rows:
                active = conn.execute(
                    "SELECT 1 FROM students WHERE id=? AND is_active=1",
                    (r["student_id"],)).fetchone()
                if not active:
                    conn.execute(
                        "UPDATE uniform_checkouts SET date_returned=?, "
                        "notes=COALESCE(NULLIF(notes,''),'')||' [auto-returned at rollover]' "
                        "WHERE id=?", (date_returned, r["id"]))
                    n += 1
        return n

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

    def get_all_students(self, school_year=None, include_inactive=False,
                         site_id=None, level=None):
        """The roster.  ``site_id`` narrows to one school; ``level`` narrows to
        secondary or elementary.

        Both default to off, so every existing caller keeps seeing what it saw.
        Screens that must not show 5th graders -- the concert and trip mailing
        lists above all -- ask for level="secondary" rather than filtering
        afterwards, so the children are not in the result to be missed.
        """
        with self._connect() as conn:
            conditions = []
            params = []
            if not include_inactive:
                conditions.append("is_active=1")
            if school_year:
                conditions.append("school_year=?")
                params.append(school_year)
            where = ("WHERE " + " AND ".join(conditions)) if conditions else "WHERE 1=1"
            scope, sp = self._site_scope("students", site_id, level)
            return conn.execute(
                f"SELECT * FROM students {where}{scope} "
                f"ORDER BY last_name, first_name", params + sp
            ).fetchall()

    def set_student_site(self, student_id: int, site_id):
        """Move one child to a school.

        Deliberately its own method.  site_id is kept out of update_student's
        column list so that an ordinary edit -- which passes a dict that may not
        mention it -- cannot blank a child's school; that means moving one has
        to be asked for explicitly, which is the right way round.
        """
        with self._connect() as conn:
            conn.execute("UPDATE students SET site_id = ? WHERE id = ?",
                         (site_id, student_id))
            conn.commit()

    def get_student(self, student_id: int):
        with self._connect() as conn:
            return conn.execute(
                "SELECT * FROM students WHERE id=?", (student_id,)
            ).fetchone()

    # ── Botched-import repair ──────────────────────────────────────────────
    # A class-list CSV whose name column was really the Student ID column once
    # imported a whole year of "students" named 1006424, 3007735, … while the
    # real roster sat archived under the previous year.  The parser now refuses
    # such files, but any database already damaged needs a way back.

    @staticmethod
    def _is_id_name(row) -> bool:
        name = f"{row['first_name'] or ''}{row['last_name'] or ''}".strip()
        return bool(name) and name.replace("-", "").replace(" ", "").isdigit()

    def find_botched_import_students(self):
        """Rows whose entire name is a number — the signature of the bad
        import.  Returns the full rows so callers can show/count them."""
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM students").fetchall()
        return [r for r in rows if self._is_id_name(r)]

    def undo_botched_import(self):
        """Delete ID-named students; if that leaves the newest school year
        with no active students, re-activate the most recent year that has
        any (the roster the bad import displaced).

        Returns ``(deleted, restored_year, restored_count)`` —
        ``restored_year`` is None when nothing needed re-activating."""
        bad = self.find_botched_import_students()
        with self._connect() as conn:
            for r in bad:
                conn.execute("DELETE FROM students WHERE id=?", (r["id"],))
        restored_year, restored = None, 0
        with self._connect() as conn:
            newest = conn.execute(
                "SELECT school_year FROM students WHERE school_year IS NOT NULL "
                "ORDER BY school_year DESC LIMIT 1").fetchone()
            if newest:
                year = newest["school_year"]
                n_active = conn.execute(
                    "SELECT COUNT(*) FROM students WHERE school_year=? "
                    "AND is_active=1", (year,)).fetchone()[0]
                if n_active == 0:
                    # The newest roster is fully archived — that's the wizard's
                    # close-out with nothing valid imported after it.  Bring
                    # the displaced roster back.
                    restored_year = year
                    cur = conn.execute(
                        "UPDATE students SET is_active=1 WHERE school_year=?",
                        (year,))
                    restored = cur.rowcount
        return len(bad), restored_year, restored

    # ── Duplicate students ────────────────────────────────────────────────
    # A class list names a student once per section or meeting day.  An older
    # import created a record for every one of those rows, so beginners could
    # end up with two or three copies, all of them missing the contact details
    # that only ever arrive with the district roster.

    # Fields whose emptiness makes a record the weaker copy.
    _IDENTITY_FIELDS = ("student_id", "grade", "address", "phone",
                        "student_email", "parent1_name", "parent1_email",
                        "parent1_phone", "parent2_name", "parent2_email",
                        "parent2_phone", "birth_date", "primary_instrument")

    @staticmethod
    def _dup_key(row):
        """Two rows are the same person if they share a district ID, or failing
        that a last name plus a first name that agrees to the first word."""
        sid = (row["student_id"] or "").strip()
        if sid:
            return ("sid", sid.lower())
        first = (row["first_name"] or "").strip().lower().split()
        last = (row["last_name"] or "").strip().lower()
        if not first or not last:
            return None
        return ("name", first[0], last)

    # Two students really can share a name.  When the only evidence they are
    # the same person is that name, any hard disagreement means they are not.
    _DISTINGUISHING_FIELDS = ("student_id", "birth_date", "grade", "address",
                              "student_email", "parent1_email", "parent1_name")

    @classmethod
    def _members_conflict(cls, members):
        for f in cls._DISTINGUISHING_FIELDS:
            seen = {str(m[f] or "").strip().lower()
                    for m in members if str(m[f] or "").strip()}
            if len(seen) > 1:
                return True
        return False

    def find_duplicate_students(self, school_year=None):
        """Groups of rows that describe one student.  Each group is ordered
        best-first: the record with the most real data is the keeper."""
        sql = "SELECT * FROM students WHERE is_active=1"
        params = []
        if school_year:
            sql += " AND school_year=?"
            params.append(school_year)
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()

        groups = {}
        for r in rows:
            key = self._dup_key(r)
            if key:
                groups.setdefault(key, []).append(r)

        def score(r):
            return sum(1 for f in self._IDENTITY_FIELDS
                       if str(r[f] or "").strip())

        out = []
        for key, members in groups.items():
            if len(members) < 2:
                continue
            # A shared district ID is proof.  A shared name is only a guess, so
            # two same-named students with different birthdays, grades, homes or
            # guardians are left alone rather than silently fused into one.
            if key[0] == "name" and self._members_conflict(members):
                continue
            members.sort(key=lambda r: (-score(r), r["id"]))
            out.append(members)
        return out

    def merge_duplicate_students(self, school_year=None):
        """Fold each duplicate group into its best record: fill blanks from the
        copies, union the ensemble/period lists, repoint checkouts, fees and
        uniforms, then delete the copies.

        Returns ``(groups_merged, records_removed)``."""
        groups = self.find_duplicate_students(school_year)
        if not groups:
            return (0, 0)

        fill = [f for f in self._IDENTITY_FIELDS] + [
            "gender", "city", "state", "zip_code", "preferred_name",
            "secondary_instrument", "jazz_instrument", "notes",
            "parent1_relation", "parent2_relation"]
        removed = 0
        with self._connect() as conn:
            for members in groups:
                keeper, extras = members[0], members[1:]
                updates = {}
                for f in fill:
                    if str(keeper[f] or "").strip():
                        continue
                    for e in extras:
                        val = str(e[f] or "").strip()
                        if val:
                            updates[f] = val
                            break
                for f in ("ensembles", "class_periods"):
                    merged = keeper[f] or ""
                    for e in extras:
                        merged = self._csv_merge(
                            merged,
                            [p.strip() for p in (e[f] or "").split(",") if p.strip()],
                            False, by_class=(f == "ensembles"))
                    if merged != (keeper[f] or ""):
                        updates[f] = merged
                for f in ("honors", "all_state"):
                    if not keeper[f] and any(e[f] for e in extras):
                        updates[f] = 1
                if updates:
                    conn.execute(
                        "UPDATE students SET "
                        + ", ".join(f"{c}=?" for c in updates)
                        + " WHERE id=?",
                        list(updates.values()) + [keeper["id"]])

                for e in extras:
                    for table in ("checkouts", "student_fees",
                                  "uniform_checkouts", "budget_transactions"):
                        try:
                            conn.execute(
                                f"UPDATE {table} SET student_id=? WHERE student_id=?",
                                (keeper["id"], e["id"]))
                        except sqlite3.Error:
                            pass
                    conn.execute("DELETE FROM students WHERE id=?", (e["id"],))
                    removed += 1
        return (len(groups), removed)

    # Everything a district roster export can tell us about a student that the
    # teacher would otherwise type in by hand.  Deliberately excludes ensembles,
    # class_periods and instruments: those are the teacher's to set, and the
    # import labels them separately.
    _ROSTER_FILL_FIELDS = (
        "student_id", "grade", "gender", "birth_date", "address", "city",
        "state", "zip_code", "phone", "student_email",
        "parent1_name", "parent1_relation", "parent1_phone", "parent1_email",
        "parent2_name", "parent2_relation", "parent2_phone", "parent2_email",
    )

    def fill_student_blanks(self, student_id: int, data: dict) -> int:
        """Copy roster values into the fields this student has left empty, and
        only those.  Anything the teacher already entered is never overwritten.

        Returns how many fields were filled.  Writes only the changed columns,
        so unlike update_student this can safely take a partial dict."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM students WHERE id=?", (student_id,)).fetchone()
            if row is None:
                return 0
            updates = {}
            for f in self._ROSTER_FILL_FIELDS:
                if f not in data:
                    continue
                incoming = str(data.get(f) or "").strip()
                if incoming and not str(row[f] or "").strip():
                    updates[f] = incoming
            if not updates:
                return 0
            conn.execute(
                "UPDATE students SET "
                + ", ".join(f"{c}=?" for c in updates)
                + " WHERE id=?",
                list(updates.values()) + [student_id])
            return len(updates)

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
            "preferred_name", "jazz_instrument", "provisional", "site_id"
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

    def archive_school_year(self, school_year: str, level: str = None) -> int:
        """Close out a school year: mark its active students inactive.  Their
        records stay in the database and can be reactivated (or picked up by
        the New School Year class-list import).  Honors / Jr. All-State marks
        are cleared — they must be earned again each year.  Returns the
        count archived.

        ``level`` limits it to one kind of school.  Every 5th grader leaves for
        middle school at the end of every year without exception, so their
        archiving is not a decision anybody needs to be asked about; a
        secondary roster is a different matter and keeps its checkbox.
        """
        scope, params = self._site_scope("students", None, level)
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE students SET is_active=0, honors=0, all_state=0 "
                f"WHERE school_year=? AND is_active=1{scope}",
                [school_year] + params)
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
    def _csv_merge(existing: str, values, replace: bool,
                   by_class: bool = False) -> str:
        """Merge/replace a comma-separated multi-value field, order-preserving,
        de-duplicated.  `values` is a list of strings to set or add.

        With ``by_class`` (the ensembles field), duplicates are detected by
        class IDENTITY: adding "MS Band (Entry)" to a student who already has
        "Entry Band" replaces the old spelling instead of stacking a second
        copy of the same class — so stored data converges on whatever spelling
        the class pickers offer."""
        wanted = [str(v).strip() for v in values if str(v).strip()]

        def _dup(items, v):
            if by_class:
                from class_registry import same_class
                return any(same_class(v, i) for i in items)
            return v in items

        if replace:
            out = []
            for v in wanted:
                if not _dup(out, v):
                    out.append(v)
            return ",".join(out)
        out = [p.strip() for p in (existing or "").split(",") if p.strip()]
        for v in wanted:
            if by_class:
                from class_registry import same_class
                # The NEW spelling wins: swap out any same-class variant.
                out = [i for i in out if not same_class(v, i)]
            if not _dup(out, v):
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
                merged = self._csv_merge(current, values, replace,
                                         by_class=(field == "ensembles"))
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
                               instrument=None, include_inactive=False,
                               site_id=None, level="secondary"):
        """Return active student rows matching the given filters.  Multi-value
        fields (ensembles, class_periods) are matched by membership.

        Scoped to secondary students by DEFAULT, unlike every other query here.
        This one builds the lists people are actually contacted from -- concert
        and field trip mail, seating charts, percussion rotations, ensembles --
        and every one of those is a secondary idea. A 5th grader has no seating
        chart and must never turn up on a marching band trip email, so the safe
        default is the one where they are absent unless asked for.

        The 5th grade screens pass site_id for their own school, which takes
        precedence; level=None returns everybody.
        """
        sql = "SELECT * FROM students WHERE 1=1"
        params = []
        if not include_inactive:
            sql += " AND is_active=1"
        if school_year:
            sql += " AND school_year=?"
            params.append(school_year)
        scope, sp = self._site_scope("students", site_id, level)
        sql += scope
        params += sp
        sql += " ORDER BY last_name, first_name"
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()

        def _has(csv_val, target):
            return target in [p.strip() for p in (csv_val or "").split(",") if p.strip()]

        # Class membership is compared by IDENTITY, not spelling: an imported
        # roster's "Entry Band", the registry's "MS Band (Entry)" and a filter's
        # "Entry" are the same class.  Every ensemble filter in the app funnels
        # through here, so this one line is what keeps them all agreeing.
        from class_registry import csv_has_class

        out = []
        for r in rows:
            if ensemble and not csv_has_class(r["ensembles"], ensemble):
                continue
            if period and not _has(r["class_periods"], str(period)):
                continue
            if instrument:
                # One instrument or several.  A teacher writing to "the low
                # brass" means trombone AND baritone AND tuba, and asking them
                # to send the same message three times is how one of the three
                # gets forgotten.
                wanted = ([instrument] if isinstance(instrument, str)
                          else list(instrument))
                if not any(instrument_matches(w, r[c])
                           for w in wanted
                           for c in ("primary_instrument", "secondary_instrument")):
                    continue
            out.append(r)
        return out

    # ─── Checkout CRUD ─────────────────────────────────────────────────────────

    def checkout_instrument(self, instrument_id: int, student_id: int,
                            student_name: str, date_assigned: str, notes: str = "",
                            due_date: str = "", rental_type: str = "school_year",
                            charge_fee: bool = True,
                            fee_per_instrument: bool = False) -> int:
        with self._connect() as conn:
            # Both schools' instruments are in one list; only one of them is
            # this child's.  Checked before the row is written, so a refused
            # checkout leaves nothing behind.
            self._assert_same_site(conn, instrument_id, student_id)
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
        # The rental fee is an annual charge every student renting an instrument
        # is expected to pay, so it is added by default.  charge_fee=False is
        # only for re-recording assignments that were already billed.
        # Elementary loans are free -- the district's own elementary form says
        # so -- so the site has the final word over whatever the caller asked
        # for.  Otherwise every 5th grade checkout would raise a $75 charge
        # that somebody then has to find and waive.
        if student_id and charge_fee and self._student_site_charges_fees(student_id):
            try:
                self._auto_add_rental_fee(student_id, date_assigned, rental_type,
                                          per_instrument=fee_per_instrument)
            except Exception:
                pass
        return checkout_id

    def add_rental_fee(self, student_id: int, date_assigned: str,
                       rental_type: str = "school_year",
                       per_instrument: bool = True):
        """Bill the rental fee on its own, for an instrument the student is
        already holding — a summer loan that simply runs on into the new school
        year owes the new year's fee without a second check-out."""
        self._auto_add_rental_fee(student_id, date_assigned, rental_type,
                                  per_instrument=per_instrument)

    def _auto_add_rental_fee(self, student_id: int, date_assigned: str,
                             rental_type: str = "school_year",
                             per_instrument: bool = False):
        """The rental fee for one check-out.

        ``per_instrument`` bills this instrument on its own line, which is what
        a student renting three of them actually owes.  Left off, the fee is
        deduped to one per student per year — the older behavior, kept so a
        single check-out screen can't double-bill someone by accident."""
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
        if per_instrument:
            self.add_student_fee(student_id, name, year, amount)
        else:
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

    def get_checkouts_for_site(self, site_id):
        """Every checkout, past and present, against one school's instruments.

        The handoff needs the history and not just what is out today: next
        year's teacher wants to know which horn has been through four children
        and which has never left the cupboard."""
        with self._connect() as conn:
            return conn.execute(
                """SELECT c.*, i.category, i.description AS instrument_desc,
                          i.brand, i.serial_no, i.barcode, i.district_no, i.size,
                          s.first_name, s.last_name, s.grade, s.student_id AS district_student_id
                   FROM checkouts c
                   JOIN instruments i ON i.id = c.instrument_id
                   LEFT JOIN students s ON s.id = c.student_id
                   WHERE i.site_id = ?
                   ORDER BY c.date_assigned DESC, c.id DESC""",
                (site_id,)).fetchall()

    def get_pending_repairs(self, site_id=None):
        """All not-yet-completed repairs (date_repaired blank), joined with the
        instrument, for the technician printout / needs-repair export.

        ``site_id`` narrows it to one school, which is what the handoff to next
        year's teacher needs: they are taking on that building, not everything
        their predecessor happened to look after."""
        scope, params = self._site_scope("i", site_id)
        with self._connect() as conn:
            return conn.execute(
                f"""SELECT r.*, i.category, i.description AS instrument_desc,
                          i.brand, i.model, i.serial_no, i.barcode, i.district_no,
                          i.condition AS instrument_condition, i.locker
                   FROM repairs r
                   LEFT JOIN instruments i ON i.id = r.instrument_id
                   WHERE (r.date_repaired IS NULL OR TRIM(r.date_repaired) = '')
                         {scope}
                   ORDER BY r.priority DESC, i.category, i.description""",
                params
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

    def get_all_repairs(self, site_id=None):
        """Every repair record joined with its instrument, for the repair-hub
        history view and cost analysis.  ``site_id`` narrows it to one school."""
        scope, params = self._site_scope("i", site_id)
        with self._connect() as conn:
            return conn.execute(
                f"""SELECT r.*, i.category, i.description AS instrument_desc,
                          i.brand, i.model, i.serial_no, i.barcode, i.district_no,
                          i.condition AS instrument_condition, i.locker,
                          i.amount_paid, i.est_value, i.year_purchased
                   FROM repairs r
                   LEFT JOIN instruments i ON i.id = r.instrument_id
                   WHERE 1=1 {scope}
                   ORDER BY r.date_added DESC""",
                params
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

    # District belongs here because it really does pay for some things -- the
    # district-run festivals a high school enters, above all -- and without it
    # those landed under "Other" alongside everything else nobody could
    # categorise.
    FUNDING_SOURCES = ["Building", "District", "ASB", "Boosters", "Other"]

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
                "funding_source", "student_id", "invoice_no", "vendor", "notes"]
        vals = [data.get(c) for c in cols]
        with self._connect() as conn:
            cur = conn.execute(
                f"INSERT INTO budget_transactions ({','.join(cols)}) "
                f"VALUES ({','.join('?' * len(cols))})", vals)
            return cur.lastrowid

    def update_budget_transaction(self, txn_id: int, data: dict):
        cols = ["txn_date", "description", "category", "kind", "amount",
                "funding_source", "student_id", "invoice_no", "vendor", "notes"]
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
                # Not "Repair: ..." -- the Category column beside it already
                # says Instrument Repair.
                "description": f"{rp['inst'] or ''} — {rp['description'] or ''}".strip(" —"),
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
                # Every word of "Fee: Instrument Rental (School Year) — Charlie
                # Zhang" except two is already on the row: the Category column
                # says Instrument Rental Fees and the Student column says
                # Charlie Zhang.  What is left worth saying is which rental it
                # is, so that is all this says.
                "description": _fee_description(ftype),
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

    # ── Tidying up AI-written text ────────────────────────────────────────
    # A web-search enrichment answers with its sources marked up in the text
    # ("<cite index="4-14">A Duke Ellington classic…</cite>"), which is meant
    # for a program that turns them into footnotes.  Here it lands in the notes
    # field a teacher reads, so it reads as gibberish wrapped round the useful
    # sentence.  llm_client strips it on the way in now; these two find and fix
    # what earlier imports already saved.

    # Every free-text column a description could have been written into.
    _MUSIC_TEXT_COLUMNS = ("notes", "title", "composer", "arranger", "genre",
                           "publisher", "location", "voicing", "language",
                           "accompaniment")

    def find_music_markup(self, include_inactive=True):
        """Pieces whose text still carries citation markup.

        Returns [(row, {column: cleaned_text})] so the teacher can be shown
        exactly what would change before any of it is written."""
        from llm_client import strip_citation_markup
        out = []
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM sheet_music" +
                ("" if include_inactive else " WHERE is_active=1") +
                " ORDER BY title"
            ).fetchall()
        for row in rows:
            keys = row.keys()
            fixes = {}
            for col in self._MUSIC_TEXT_COLUMNS:
                if col not in keys:
                    continue
                before = row[col]
                if not isinstance(before, str) or not before:
                    continue
                after = strip_citation_markup(before)
                if after != before:
                    fixes[col] = after
            if fixes:
                out.append((row, fixes))
        return out

    def clean_music_markup(self, music_ids=None):
        """Take the citation markup off, keeping every word inside it.

        ``music_ids`` limits the job to a chosen few; left out, it does the lot.
        Returns the number of pieces changed."""
        targets = self.find_music_markup()
        if music_ids is not None:
            wanted = set(music_ids)
            targets = [(r, f) for r, f in targets if r["id"] in wanted]
        if not targets:
            return 0
        with self._connect() as conn:
            for row, fixes in targets:
                sets = ", ".join(f"{col}=?" for col in fixes)
                conn.execute(f"UPDATE sheet_music SET {sets} WHERE id=?",
                             list(fixes.values()) + [row["id"]])
        return len(targets)

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
