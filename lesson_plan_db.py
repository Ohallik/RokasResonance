"""
lesson_plan_db.py - Separate database for lesson plan data, one file per school year.

Architecture:
  - Main rokas_resonance.db: instruments, students, checkouts, repairs, sheet_music
  - lesson_plans_YYYY-YYYY.db: teaching_classes, curriculum_items, lesson_plans,
    lesson_blocks, resources, resource_tags, templates, onenote_sync

Each school year gets its own database file, keeping the data manageable
and allowing teachers to easily switch between years.
"""

import os
import sqlite3
from datetime import datetime
from database import _DictRow


class LessonPlanDatabase:
    """Database for lesson plan data, scoped to a single school year."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_db()

    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = _DictRow
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        return conn

    def _init_db(self):
        with self._connect() as conn:
            conn.executescript("""
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
                    FOREIGN KEY (lesson_plan_id) REFERENCES lesson_plans(id)
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
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
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

                CREATE TABLE IF NOT EXISTS percussion_groups (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    school_year TEXT,
                    name TEXT NOT NULL,
                    class_type TEXT DEFAULT 'entry',
                    period TEXT,
                    current_day INTEGER DEFAULT 1,
                    mallet_subrotation INTEGER DEFAULT 1,
                    class_id INTEGER,
                    notes TEXT,
                    is_active INTEGER DEFAULT 1,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS percussion_students (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    group_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    sort_order INTEGER DEFAULT 0,
                    full_rotation INTEGER DEFAULT 1,
                    assessments_passed INTEGER DEFAULT 0,
                    is_active INTEGER DEFAULT 1,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (group_id) REFERENCES percussion_groups(id)
                );

                CREATE TABLE IF NOT EXISTS percussion_overrides (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    group_id INTEGER NOT NULL,
                    day_number INTEGER NOT NULL,
                    mode TEXT NOT NULL,
                    note TEXT,
                    UNIQUE(group_id, day_number),
                    FOREIGN KEY (group_id) REFERENCES percussion_groups(id)
                );

                CREATE TABLE IF NOT EXISTS agenda_days (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    group_key TEXT NOT NULL,
                    day_date TEXT NOT NULL,
                    data TEXT,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(group_key, day_date)
                );

                CREATE TABLE IF NOT EXISTS jazz_ensembles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    school_year TEXT,
                    name TEXT NOT NULL,
                    seats TEXT,
                    current_day INTEGER DEFAULT 1,
                    sort_order INTEGER DEFAULT 0,
                    notes TEXT,
                    is_active INTEGER DEFAULT 1,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS jazz_players (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ensemble_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    parts TEXT,
                    sort_order INTEGER DEFAULT 0,
                    is_active INTEGER DEFAULT 1,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (ensemble_id) REFERENCES jazz_ensembles(id)
                );

                CREATE TABLE IF NOT EXISTS jazz_songs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ensemble_id INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    locked TEXT,
                    notes TEXT,
                    sort_order INTEGER DEFAULT 0,
                    is_active INTEGER DEFAULT 1,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (ensemble_id) REFERENCES jazz_ensembles(id)
                );

                CREATE TABLE IF NOT EXISTS seating_charts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    school_year TEXT,
                    name TEXT NOT NULL,
                    chart_type TEXT DEFAULT 'class',
                    config_json TEXT,
                    layout_json TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS seating_conflicts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    school_year TEXT,
                    name_a TEXT NOT NULL,
                    name_b TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS seating_pins (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    school_year TEXT,
                    student_name TEXT NOT NULL,
                    pref TEXT,
                    note TEXT,
                    buffer INTEGER DEFAULT 0,
                    UNIQUE(school_year, student_name)
                );

                CREATE TABLE IF NOT EXISTS concerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    school_year TEXT,
                    title TEXT NOT NULL,
                    concert_date TEXT,
                    start_time TEXT,
                    end_time TEXT,
                    location TEXT,
                    offsite INTEGER DEFAULT 0,
                    ensembles TEXT,
                    attire TEXT,
                    bring TEXT,
                    arrival TEXT,
                    rehearsals TEXT,
                    itinerary TEXT,
                    perf_order TEXT,
                    acknowledgements TEXT,
                    upcoming TEXT,
                    notes TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS concert_pieces (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    concert_id INTEGER NOT NULL,
                    ensemble TEXT NOT NULL,
                    title TEXT NOT NULL,
                    composer TEXT,
                    arranger TEXT,
                    position INTEGER DEFAULT 0,
                    FOREIGN KEY (concert_id) REFERENCES concerts(id)
                );

                CREATE TABLE IF NOT EXISTS concert_reminders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    concert_id INTEGER NOT NULL,
                    stage TEXT NOT NULL,
                    sent_date TEXT,
                    UNIQUE(concert_id, stage),
                    FOREIGN KEY (concert_id) REFERENCES concerts(id)
                );

                CREATE TABLE IF NOT EXISTS program_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT
                );

                CREATE TABLE IF NOT EXISTS field_trips (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    school_year TEXT,
                    name TEXT NOT NULL,
                    groups_list TEXT,
                    destination TEXT,
                    depart_date TEXT,
                    depart_time TEXT,
                    return_date TEXT,
                    return_time TEXT,
                    travel_method TEXT,
                    entry_fee REAL DEFAULT 0,
                    transport_cost REAL DEFAULT 0,
                    food_cost REAL DEFAULT 0,
                    sub_cost REAL DEFAULT 0,
                    other_cost REAL DEFAULT 0,
                    funding TEXT DEFAULT 'curricular',
                    covered INTEGER DEFAULT 0,
                    approved INTEGER DEFAULT 0,
                    sub_assigned INTEGER DEFAULT 0,
                    bus_requested INTEGER DEFAULT 0,
                    notes TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS field_trip_exclusions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trip_id INTEGER NOT NULL,
                    student_id INTEGER NOT NULL,
                    UNIQUE(trip_id, student_id),
                    FOREIGN KEY (trip_id) REFERENCES field_trips(id)
                );

                CREATE TABLE IF NOT EXISTS field_trip_chaperones (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trip_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    phone TEXT,
                    email TEXT,
                    cleared INTEGER DEFAULT 0,
                    FOREIGN KEY (trip_id) REFERENCES field_trips(id)
                );

                CREATE TABLE IF NOT EXISTS field_trip_reminders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trip_id INTEGER NOT NULL,
                    stage TEXT NOT NULL,
                    sent_date TEXT,
                    UNIQUE(trip_id, stage),
                    FOREIGN KEY (trip_id) REFERENCES field_trips(id)
                );
            """)
            # Migration: structured itinerary fields on older concerts tables,
            # plus the tri-state prep checklist (0 to do / 1 done / 2 N/A).
            for col in ("setup TEXT", "seated_by TEXT", "directors TEXT",
                        "extra_info TEXT", "special_guests TEXT",
                        "venue_reserved INTEGER DEFAULT 0",
                        "tutorials_scheduled INTEGER DEFAULT 0",
                        "repertoire_final INTEGER DEFAULT 0",
                        "details_sent INTEGER DEFAULT 0",
                        "program_printed INTEGER DEFAULT 0",
                        "setup_ready INTEGER DEFAULT 0",
                        "email_staff TEXT"):
                try:
                    conn.execute(f"ALTER TABLE concerts ADD COLUMN {col}")
                    conn.commit()
                except Exception:
                    pass
            # Migration: per-trip saved email templates (reused year to year)
            # + tri-state checklist items (0 = to do, 1 = done, 2 = N/A).
            # FinalForms replaced paper permission slips: the office builds a
            # participant group giving realtime medical / emergency info.
            for col in ("email_families TEXT", "email_chaperones TEXT",
                        "email_teachers TEXT",
                        "registration_done INTEGER DEFAULT 0",
                        "finalforms_done INTEGER DEFAULT 0",
                        "nurse_check INTEGER DEFAULT 0"):
                try:
                    conn.execute(f"ALTER TABLE field_trips ADD COLUMN {col}")
                    conn.commit()
                except Exception:
                    pass
            # Migration: add the buffer column to older seating_pins tables.
            try:
                conn.execute("ALTER TABLE seating_pins ADD COLUMN buffer INTEGER DEFAULT 0")
                conn.commit()
            except Exception:
                pass
            # Migration: per-student rotation limit (JSON list of the ONLY
            # stations that student may take; NULL = normal earn-based rotation).
            # For students who can only play certain equipment (accessibility).
            try:
                conn.execute("ALTER TABLE percussion_students ADD COLUMN allowed_stations TEXT")
                conn.commit()
            except Exception:
                pass
            # Indexes
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

    # ═══════════════════════════════════════════════════════════════════════════
    # All the same CRUD methods from Database, just for lesson plan tables.
    # These are delegated from the main Database class.
    # ═══════════════════════════════════════════════════════════════════════════

    # ─── Teaching Classes ─────────────────────────────────────────────────────

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

    def get_class(self, class_id):
        with self._connect() as conn:
            return conn.execute(
                "SELECT * FROM teaching_classes WHERE id=?", (class_id,)
            ).fetchone()

    def add_class(self, data):
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
                f"INSERT INTO teaching_classes ({col_str}) VALUES ({placeholders})", values,
            )
            return cur.lastrowid

    def update_class(self, class_id, data):
        cols = [
            "class_name", "ensemble_type", "grade_levels", "skill_level",
            "period", "days_of_week", "class_duration", "student_count",
            "method_book", "school_year", "room", "notes", "is_active",
        ]
        set_clause = ", ".join([f"{c}=?" for c in cols])
        values = [data.get(c) for c in cols] + [class_id]
        with self._connect() as conn:
            conn.execute(f"UPDATE teaching_classes SET {set_clause} WHERE id=?", values)

    def deactivate_class(self, class_id):
        with self._connect() as conn:
            conn.execute("UPDATE teaching_classes SET is_active=0 WHERE id=?", (class_id,))

    def get_class_school_years(self):
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT DISTINCT school_year FROM teaching_classes "
                "WHERE school_year IS NOT NULL ORDER BY school_year DESC"
            ).fetchall()
        return [r["school_year"] for r in rows]

    # ─── Concert Dates ────────────────────────────────────────────────────────

    def get_concert_dates(self, class_id=None):
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

    def add_concert_date(self, data):
        cols = ["class_id", "concert_date", "event_name", "location", "notes"]
        values = [data.get(c) for c in cols]
        placeholders = ",".join(["?"] * len(cols))
        col_str = ",".join(cols)
        with self._connect() as conn:
            cur = conn.execute(
                f"INSERT INTO concert_dates ({col_str}) VALUES ({placeholders})", values,
            )
            return cur.lastrowid

    def update_concert_date(self, concert_id, data):
        cols = ["class_id", "concert_date", "event_name", "location", "notes"]
        set_clause = ", ".join([f"{c}=?" for c in cols])
        values = [data.get(c) for c in cols] + [concert_id]
        with self._connect() as conn:
            conn.execute(f"UPDATE concert_dates SET {set_clause} WHERE id=?", values)

    def delete_concert_date(self, concert_id):
        with self._connect() as conn:
            conn.execute("DELETE FROM concert_dates WHERE id=?", (concert_id,))

    # ─── Curriculum Items ─────────────────────────────────────────────────────

    def get_curriculum_items(self, class_id, start_date=None, end_date=None):
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
                f"SELECT * FROM curriculum_items WHERE {where} ORDER BY item_date", params,
            ).fetchall()

    def get_curriculum_item(self, item_id):
        with self._connect() as conn:
            return conn.execute(
                "SELECT * FROM curriculum_items WHERE id=?", (item_id,)
            ).fetchone()

    def get_curriculum_item_by_date(self, class_id, item_date):
        with self._connect() as conn:
            return conn.execute(
                "SELECT * FROM curriculum_items WHERE class_id=? AND item_date=?",
                (class_id, item_date),
            ).fetchone()

    def add_curriculum_item(self, data):
        cols = [
            "class_id", "item_date", "summary", "activity_type",
            "unit_name", "is_locked", "sort_order", "notes",
        ]
        values = [data.get(c) for c in cols]
        placeholders = ",".join(["?"] * len(cols))
        col_str = ",".join(cols)
        with self._connect() as conn:
            cur = conn.execute(
                f"INSERT INTO curriculum_items ({col_str}) VALUES ({placeholders})", values,
            )
            return cur.lastrowid

    def update_curriculum_item(self, item_id, data):
        cols = [
            "class_id", "item_date", "summary", "activity_type",
            "unit_name", "is_locked", "sort_order", "notes",
        ]
        set_clause = ", ".join([f"{c}=?" for c in cols])
        values = [data.get(c) for c in cols] + [item_id]
        with self._connect() as conn:
            conn.execute(f"UPDATE curriculum_items SET {set_clause} WHERE id=?", values)

    def delete_curriculum_item(self, item_id):
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM lesson_blocks WHERE lesson_plan_id IN "
                "(SELECT id FROM lesson_plans WHERE curriculum_item_id=?)", (item_id,),
            )
            conn.execute(
                "DELETE FROM lesson_plan_resources WHERE lesson_plan_id IN "
                "(SELECT id FROM lesson_plans WHERE curriculum_item_id=?)", (item_id,),
            )
            conn.execute("DELETE FROM lesson_plans WHERE curriculum_item_id=?", (item_id,))
            conn.execute("DELETE FROM curriculum_items WHERE id=?", (item_id,))

    def move_curriculum_item(self, item_id, new_date):
        with self._connect() as conn:
            conn.execute(
                "UPDATE curriculum_items SET item_date=? WHERE id=?", (new_date, item_id),
            )

    def shift_curriculum_items(self, class_id, from_date, days):
        from datetime import timedelta
        with self._connect() as conn:
            items = conn.execute(
                "SELECT id, item_date FROM curriculum_items "
                "WHERE class_id=? AND item_date >= ? AND is_locked=0 "
                "ORDER BY item_date " + ("DESC" if days > 0 else "ASC"),
                (class_id, from_date),
            ).fetchall()
            for item in items:
                old = datetime.strptime(item["item_date"], "%Y-%m-%d")
                new = old + timedelta(days=days)
                conn.execute(
                    "UPDATE curriculum_items SET item_date=? WHERE id=?",
                    (new.strftime("%Y-%m-%d"), item["id"]),
                )

    def swap_curriculum_items(self, item_id_a, item_id_b):
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

    def bulk_add_curriculum_items(self, items):
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
                    f"INSERT INTO curriculum_items ({col_str}) VALUES ({placeholders})", values,
                )
                ids.append(cur.lastrowid)
        return ids

    def clear_curriculum(self, class_id):
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM lesson_blocks WHERE lesson_plan_id IN "
                "(SELECT lp.id FROM lesson_plans lp "
                " JOIN curriculum_items ci ON ci.id = lp.curriculum_item_id "
                " WHERE ci.class_id=?)", (class_id,),
            )
            conn.execute(
                "DELETE FROM lesson_plan_resources WHERE lesson_plan_id IN "
                "(SELECT lp.id FROM lesson_plans lp "
                " JOIN curriculum_items ci ON ci.id = lp.curriculum_item_id "
                " WHERE ci.class_id=?)", (class_id,),
            )
            conn.execute(
                "DELETE FROM lesson_plans WHERE curriculum_item_id IN "
                "(SELECT id FROM curriculum_items WHERE class_id=?)", (class_id,),
            )
            conn.execute("DELETE FROM curriculum_items WHERE class_id=?", (class_id,))

    # ─── Lesson Plans ─────────────────────────────────────────────────────────

    def get_lesson_plan(self, plan_id):
        with self._connect() as conn:
            return conn.execute(
                "SELECT * FROM lesson_plans WHERE id=?", (plan_id,)
            ).fetchone()

    def get_lesson_plan_by_curriculum_item(self, curriculum_item_id):
        with self._connect() as conn:
            return conn.execute(
                "SELECT * FROM lesson_plans WHERE curriculum_item_id=?",
                (curriculum_item_id,),
            ).fetchone()

    def get_lesson_plan_for_date(self, class_id, plan_date):
        with self._connect() as conn:
            return conn.execute(
                "SELECT lp.* FROM lesson_plans lp "
                "JOIN curriculum_items ci ON ci.id = lp.curriculum_item_id "
                "WHERE ci.class_id=? AND ci.item_date=?",
                (class_id, plan_date),
            ).fetchone()

    def add_lesson_plan(self, data):
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
                f"INSERT INTO lesson_plans ({col_str}) VALUES ({placeholders})", values,
            )
            return cur.lastrowid

    def update_lesson_plan(self, plan_id, data):
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
            conn.execute(f"UPDATE lesson_plans SET {set_clause} WHERE id=?", values)

    def delete_lesson_plan(self, plan_id):
        with self._connect() as conn:
            conn.execute("DELETE FROM lesson_blocks WHERE lesson_plan_id=?", (plan_id,))
            conn.execute("DELETE FROM lesson_plan_resources WHERE lesson_plan_id=?", (plan_id,))
            conn.execute("DELETE FROM lesson_plans WHERE id=?", (plan_id,))

    # ─── Lesson Blocks ────────────────────────────────────────────────────────

    def get_lesson_blocks(self, lesson_plan_id):
        with self._connect() as conn:
            return conn.execute(
                "SELECT * FROM lesson_blocks WHERE lesson_plan_id=? ORDER BY sort_order",
                (lesson_plan_id,),
            ).fetchall()

    def add_lesson_block(self, data):
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
                f"INSERT INTO lesson_blocks ({col_str}) VALUES ({placeholders})", values,
            )
            return cur.lastrowid

    def update_lesson_block(self, block_id, data):
        cols = [
            "lesson_plan_id", "block_type", "title", "description",
            "duration_minutes", "sort_order", "music_piece_id",
            "measure_start", "measure_end", "technique_focus",
            "difficulty_level", "grouping", "notes",
        ]
        set_clause = ", ".join([f"{c}=?" for c in cols])
        values = [data.get(c) for c in cols] + [block_id]
        with self._connect() as conn:
            conn.execute(f"UPDATE lesson_blocks SET {set_clause} WHERE id=?", values)

    def delete_lesson_block(self, block_id):
        with self._connect() as conn:
            conn.execute("DELETE FROM lesson_blocks WHERE id=?", (block_id,))

    def reorder_lesson_blocks(self, lesson_plan_id, block_ids):
        with self._connect() as conn:
            for idx, block_id in enumerate(block_ids):
                conn.execute(
                    "UPDATE lesson_blocks SET sort_order=? WHERE id=? AND lesson_plan_id=?",
                    (idx, block_id, lesson_plan_id),
                )

    # ─── Resources ────────────────────────────────────────────────────────────

    def get_all_resources(self, resource_type=None):
        with self._connect() as conn:
            if resource_type:
                return conn.execute(
                    "SELECT * FROM resources WHERE resource_type=? ORDER BY display_name",
                    (resource_type,),
                ).fetchall()
            return conn.execute("SELECT * FROM resources ORDER BY display_name").fetchall()

    def get_resource(self, resource_id):
        with self._connect() as conn:
            return conn.execute("SELECT * FROM resources WHERE id=?", (resource_id,)).fetchone()

    def search_resources(self, search="", resource_type="", tag=""):
        with self._connect() as conn:
            conditions = []
            params = []
            if search:
                tok = f"%{search}%"
                conditions.append(
                    "(r.display_name LIKE ? OR r.description LIKE ? OR r.url_or_path LIKE ?)"
                )
                params.extend([tok, tok, tok])
            if resource_type:
                conditions.append("r.resource_type=?")
                params.append(resource_type)
            if tag:
                conditions.append("r.id IN (SELECT resource_id FROM resource_tags WHERE tag=?)")
                params.append(tag)
            where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
            return conn.execute(
                f"SELECT r.* FROM resources r {where} ORDER BY r.display_name", params,
            ).fetchall()

    def add_resource(self, data):
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
                f"INSERT INTO resources ({col_str}) VALUES ({placeholders})", values,
            )
            resource_id = cur.lastrowid
            for tag in data.get("tags", []):
                conn.execute(
                    "INSERT INTO resource_tags (resource_id, tag) VALUES (?, ?)",
                    (resource_id, tag),
                )
            return resource_id

    def update_resource(self, resource_id, data):
        cols = [
            "resource_type", "display_name", "description",
            "url_or_path", "file_data", "method_book_title",
            "method_book_pages", "music_id", "notes",
        ]
        set_clause = ", ".join([f"{c}=?" for c in cols])
        values = [data.get(c) for c in cols] + [resource_id]
        with self._connect() as conn:
            conn.execute(f"UPDATE resources SET {set_clause} WHERE id=?", values)
            if "tags" in data:
                conn.execute("DELETE FROM resource_tags WHERE resource_id=?", (resource_id,))
                for tag in data["tags"]:
                    conn.execute(
                        "INSERT INTO resource_tags (resource_id, tag) VALUES (?, ?)",
                        (resource_id, tag),
                    )

    def delete_resource(self, resource_id):
        with self._connect() as conn:
            conn.execute("DELETE FROM resource_tags WHERE resource_id=?", (resource_id,))
            conn.execute("DELETE FROM lesson_plan_resources WHERE resource_id=?", (resource_id,))
            conn.execute("DELETE FROM resources WHERE id=?", (resource_id,))

    def get_resource_tags(self, resource_id):
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT tag FROM resource_tags WHERE resource_id=? ORDER BY tag",
                (resource_id,),
            ).fetchall()
        return [r["tag"] for r in rows]

    def get_all_tags(self):
        with self._connect() as conn:
            rows = conn.execute("SELECT DISTINCT tag FROM resource_tags ORDER BY tag").fetchall()
        return [r["tag"] for r in rows]

    # ─── Lesson Plan ↔ Resource Links ─────────────────────────────────────────

    def link_resource_to_plan(self, lesson_plan_id, resource_id, block_id=None):
        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO lesson_plan_resources "
                "(lesson_plan_id, resource_id, block_id) VALUES (?, ?, ?)",
                (lesson_plan_id, resource_id, block_id),
            )

    def unlink_resource_from_plan(self, lesson_plan_id, resource_id):
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM lesson_plan_resources WHERE lesson_plan_id=? AND resource_id=?",
                (lesson_plan_id, resource_id),
            )

    def get_resources_for_plan(self, lesson_plan_id):
        with self._connect() as conn:
            return conn.execute(
                "SELECT r.*, lpr.block_id FROM resources r "
                "JOIN lesson_plan_resources lpr ON lpr.resource_id = r.id "
                "WHERE lpr.lesson_plan_id=? ORDER BY r.display_name",
                (lesson_plan_id,),
            ).fetchall()

    # ─── Templates ────────────────────────────────────────────────────────────

    def get_all_templates(self, template_type=None):
        with self._connect() as conn:
            if template_type:
                return conn.execute(
                    "SELECT * FROM lesson_templates WHERE template_type=? ORDER BY display_name",
                    (template_type,),
                ).fetchall()
            return conn.execute(
                "SELECT * FROM lesson_templates ORDER BY template_type, display_name"
            ).fetchall()

    def get_template(self, template_id):
        with self._connect() as conn:
            return conn.execute(
                "SELECT * FROM lesson_templates WHERE id=?", (template_id,)
            ).fetchone()

    def add_template(self, data):
        cols = ["template_type", "display_name", "description", "content_json", "ensemble_type", "notes"]
        values = [data.get(c) for c in cols]
        placeholders = ",".join(["?"] * len(cols))
        col_str = ",".join(cols)
        with self._connect() as conn:
            cur = conn.execute(
                f"INSERT INTO lesson_templates ({col_str}) VALUES ({placeholders})", values,
            )
            return cur.lastrowid

    def update_template(self, template_id, data):
        cols = ["template_type", "display_name", "description", "content_json", "ensemble_type", "notes"]
        set_clause = ", ".join([f"{c}=?" for c in cols])
        values = [data.get(c) for c in cols] + [template_id]
        with self._connect() as conn:
            conn.execute(f"UPDATE lesson_templates SET {set_clause} WHERE id=?", values)

    def delete_template(self, template_id):
        with self._connect() as conn:
            conn.execute("DELETE FROM lesson_templates WHERE id=?", (template_id,))

    # ─── OneNote Sync ─────────────────────────────────────────────────────────

    def get_onenote_sync(self, class_id):
        with self._connect() as conn:
            return conn.execute(
                "SELECT * FROM onenote_sync WHERE class_id=? ORDER BY id DESC LIMIT 1",
                (class_id,),
            ).fetchone()

    def get_all_onenote_syncs(self):
        with self._connect() as conn:
            return conn.execute(
                "SELECT os.*, tc.class_name FROM onenote_sync os "
                "JOIN teaching_classes tc ON tc.id = os.class_id "
                "WHERE os.sync_enabled=1 ORDER BY tc.class_name"
            ).fetchall()

    def save_onenote_sync(self, data):
        cols = [
            "class_id", "notebook_id", "notebook_name",
            "section_id", "section_name", "start_date", "end_date",
            "sync_enabled", "last_sync_at", "sync_direction",
        ]
        existing = self.get_onenote_sync(data.get("class_id"))
        if existing:
            set_clause = ", ".join([f"{c}=?" for c in cols])
            values = [data.get(c) for c in cols] + [existing["id"]]
            with self._connect() as conn:
                conn.execute(f"UPDATE onenote_sync SET {set_clause} WHERE id=?", values)
            return existing["id"]
        else:
            values = [data.get(c) for c in cols]
            placeholders = ",".join(["?"] * len(cols))
            col_str = ",".join(cols)
            with self._connect() as conn:
                cur = conn.execute(
                    f"INSERT INTO onenote_sync ({col_str}) VALUES ({placeholders})", values,
                )
                return cur.lastrowid

    def update_sync_timestamp(self, sync_id):
        with self._connect() as conn:
            conn.execute(
                "UPDATE onenote_sync SET last_sync_at=datetime('now') WHERE id=?", (sync_id,),
            )

    def disable_onenote_sync(self, class_id):
        with self._connect() as conn:
            conn.execute("UPDATE onenote_sync SET sync_enabled=0 WHERE class_id=?", (class_id,))

    # ─── Percussion Rotations ─────────────────────────────────────────────────

    def get_percussion_groups(self, school_year=None, include_inactive=False):
        with self._connect() as conn:
            conds, params = [], []
            if not include_inactive:
                conds.append("is_active=1")
            if school_year:
                conds.append("school_year=?")
                params.append(school_year)
            where = ("WHERE " + " AND ".join(conds)) if conds else ""
            return conn.execute(
                f"SELECT * FROM percussion_groups {where} ORDER BY period, name", params,
            ).fetchall()

    def get_percussion_group(self, group_id):
        with self._connect() as conn:
            return conn.execute(
                "SELECT * FROM percussion_groups WHERE id=?", (group_id,)
            ).fetchone()

    def add_percussion_group(self, data):
        cols = ["school_year", "name", "class_type", "period", "current_day",
                "mallet_subrotation", "class_id", "notes"]
        values = [data.get(c) for c in cols]
        placeholders = ",".join(["?"] * len(cols))
        with self._connect() as conn:
            cur = conn.execute(
                f"INSERT INTO percussion_groups ({','.join(cols)}) VALUES ({placeholders})",
                values,
            )
            return cur.lastrowid

    def update_percussion_group(self, group_id, data):
        cols = [c for c in ["school_year", "name", "class_type", "period",
                            "current_day", "mallet_subrotation", "class_id",
                            "notes", "is_active"] if c in data]
        if not cols:
            return
        set_clause = ", ".join(f"{c}=?" for c in cols)
        values = [data[c] for c in cols] + [group_id]
        with self._connect() as conn:
            conn.execute(f"UPDATE percussion_groups SET {set_clause} WHERE id=?", values)

    def delete_percussion_group(self, group_id):
        with self._connect() as conn:
            conn.execute("DELETE FROM percussion_students WHERE group_id=?", (group_id,))
            conn.execute("DELETE FROM percussion_overrides WHERE group_id=?", (group_id,))
            conn.execute("DELETE FROM percussion_groups WHERE id=?", (group_id,))

    def set_percussion_current_day(self, group_id, day):
        with self._connect() as conn:
            conn.execute("UPDATE percussion_groups SET current_day=? WHERE id=?",
                         (max(1, int(day)), group_id))

    # ── Percussion students ──

    def get_percussion_students(self, group_id, include_inactive=False):
        with self._connect() as conn:
            cond = "" if include_inactive else " AND is_active=1"
            return conn.execute(
                f"SELECT * FROM percussion_students WHERE group_id=?{cond} "
                "ORDER BY sort_order, id", (group_id,),
            ).fetchall()

    def add_percussion_student(self, group_id, name, full_rotation=1,
                               assessments_passed=0, sort_order=None):
        with self._connect() as conn:
            if sort_order is None:
                row = conn.execute(
                    "SELECT COALESCE(MAX(sort_order), -1)+1 AS n "
                    "FROM percussion_students WHERE group_id=?", (group_id,)
                ).fetchone()
                sort_order = row["n"]
            cur = conn.execute(
                "INSERT INTO percussion_students "
                "(group_id, name, full_rotation, assessments_passed, sort_order) "
                "VALUES (?, ?, ?, ?, ?)",
                (group_id, name, 1 if full_rotation else 0,
                 assessments_passed or 0, sort_order),
            )
            return cur.lastrowid

    def update_percussion_student(self, student_id, data):
        cols = [c for c in ["name", "full_rotation", "assessments_passed",
                            "is_active", "sort_order", "allowed_stations"] if c in data]
        if not cols:
            return
        set_clause = ", ".join(f"{c}=?" for c in cols)
        values = [data[c] for c in cols] + [student_id]
        with self._connect() as conn:
            conn.execute(f"UPDATE percussion_students SET {set_clause} WHERE id=?", values)

    def delete_percussion_student(self, student_id):
        with self._connect() as conn:
            conn.execute("DELETE FROM percussion_students WHERE id=?", (student_id,))

    def reorder_percussion_students(self, ordered_ids):
        with self._connect() as conn:
            for idx, sid in enumerate(ordered_ids):
                conn.execute("UPDATE percussion_students SET sort_order=? WHERE id=?",
                             (idx, sid))

    # ── Percussion day overrides ──

    def get_percussion_overrides(self, group_id):
        with self._connect() as conn:
            return conn.execute(
                "SELECT * FROM percussion_overrides WHERE group_id=? ORDER BY day_number",
                (group_id,),
            ).fetchall()

    def get_percussion_override(self, group_id, day_number):
        with self._connect() as conn:
            return conn.execute(
                "SELECT * FROM percussion_overrides WHERE group_id=? AND day_number=?",
                (group_id, day_number),
            ).fetchone()

    def set_percussion_override(self, group_id, day_number, mode, note=""):
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO percussion_overrides (group_id, day_number, mode, note) "
                "VALUES (?, ?, ?, ?) "
                "ON CONFLICT(group_id, day_number) DO UPDATE SET mode=excluded.mode, "
                "note=excluded.note",
                (group_id, day_number, mode, note),
            )

    # ── Daily agendas ──
    # A day is persisted only once the teacher touches it; until then the
    # agenda view generates it on the fly from the curriculum spine.  ``data``
    # is the whole day as JSON (reminders, announcements, sections, checks,
    # notes).  Keyed by an agenda group ("entry", "intermediate", ...) + date.

    def get_agenda_day(self, group_key, day_date):
        with self._connect() as conn:
            return conn.execute(
                "SELECT * FROM agenda_days WHERE group_key=? AND day_date=?",
                (group_key, day_date)).fetchone()

    def save_agenda_day(self, group_key, day_date, data):
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO agenda_days (group_key, day_date, data, updated_at) "
                "VALUES (?,?,?,datetime('now')) "
                "ON CONFLICT(group_key, day_date) DO UPDATE SET "
                "data=excluded.data, updated_at=datetime('now')",
                (group_key, day_date, data))

    def delete_agenda_day(self, group_key, day_date):
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM agenda_days WHERE group_key=? AND day_date=?",
                (group_key, day_date))

    def get_saved_agenda_dates(self, group_key):
        with self._connect() as conn:
            return [r["day_date"] for r in conn.execute(
                "SELECT day_date FROM agenda_days WHERE group_key=? "
                "ORDER BY day_date", (group_key,)).fetchall()]

    def clear_percussion_override(self, group_id, day_number):
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM percussion_overrides WHERE group_id=? AND day_number=?",
                (group_id, day_number),
            )

    # ─── Jazz rhythm-section ──────────────────────────────────────────────────
    # A jazz ensemble is a flexible rhythm section: an ordered SEATS list (the
    # parts in play), PLAYERS each tagged with the seats they can cover, and
    # SONGS whose seats are LOCKED to specific players once auditioned.  All
    # year-scoped, mirroring the percussion tables.

    def get_jazz_ensembles(self, school_year=None, include_inactive=False):
        with self._connect() as conn:
            conds, params = [], []
            if not include_inactive:
                conds.append("is_active=1")
            if school_year:
                conds.append("school_year=?")
                params.append(school_year)
            where = ("WHERE " + " AND ".join(conds)) if conds else ""
            return conn.execute(
                f"SELECT * FROM jazz_ensembles {where} ORDER BY sort_order, id",
                params).fetchall()

    def get_jazz_ensemble(self, ensemble_id):
        with self._connect() as conn:
            return conn.execute("SELECT * FROM jazz_ensembles WHERE id=?",
                                (ensemble_id,)).fetchone()

    def add_jazz_ensemble(self, data):
        cols = ["school_year", "name", "seats", "current_day", "sort_order", "notes"]
        with self._connect() as conn:
            if data.get("sort_order") is None:
                row = conn.execute(
                    "SELECT COALESCE(MAX(sort_order), -1)+1 AS n FROM jazz_ensembles"
                ).fetchone()
                data = {**data, "sort_order": row["n"]}
            vals = [data.get(c) for c in cols]
            cur = conn.execute(
                f"INSERT INTO jazz_ensembles ({','.join(cols)}) "
                f"VALUES ({','.join(['?'] * len(cols))})", vals)
            return cur.lastrowid

    def update_jazz_ensemble(self, ensemble_id, data):
        cols = [c for c in ["school_year", "name", "seats", "current_day",
                            "sort_order", "notes", "is_active"] if c in data]
        if not cols:
            return
        set_clause = ", ".join(f"{c}=?" for c in cols)
        vals = [data[c] for c in cols] + [ensemble_id]
        with self._connect() as conn:
            conn.execute(f"UPDATE jazz_ensembles SET {set_clause} WHERE id=?", vals)

    def set_jazz_current_day(self, ensemble_id, day):
        with self._connect() as conn:
            conn.execute("UPDATE jazz_ensembles SET current_day=? WHERE id=?",
                         (max(1, int(day)), ensemble_id))

    def delete_jazz_ensemble(self, ensemble_id):
        with self._connect() as conn:
            conn.execute("DELETE FROM jazz_players WHERE ensemble_id=?", (ensemble_id,))
            conn.execute("DELETE FROM jazz_songs WHERE ensemble_id=?", (ensemble_id,))
            conn.execute("DELETE FROM jazz_ensembles WHERE id=?", (ensemble_id,))

    # ── Jazz players ──

    def get_jazz_players(self, ensemble_id, include_inactive=False):
        with self._connect() as conn:
            cond = "" if include_inactive else " AND is_active=1"
            return conn.execute(
                f"SELECT * FROM jazz_players WHERE ensemble_id=?{cond} "
                "ORDER BY sort_order, id", (ensemble_id,)).fetchall()

    def add_jazz_player(self, ensemble_id, name, parts=None, sort_order=None):
        with self._connect() as conn:
            if sort_order is None:
                row = conn.execute(
                    "SELECT COALESCE(MAX(sort_order), -1)+1 AS n "
                    "FROM jazz_players WHERE ensemble_id=?", (ensemble_id,)
                ).fetchone()
                sort_order = row["n"]
            cur = conn.execute(
                "INSERT INTO jazz_players (ensemble_id, name, parts, sort_order) "
                "VALUES (?, ?, ?, ?)", (ensemble_id, name, parts, sort_order))
            return cur.lastrowid

    def update_jazz_player(self, player_id, data):
        cols = [c for c in ["name", "parts", "sort_order", "is_active"] if c in data]
        if not cols:
            return
        set_clause = ", ".join(f"{c}=?" for c in cols)
        vals = [data[c] for c in cols] + [player_id]
        with self._connect() as conn:
            conn.execute(f"UPDATE jazz_players SET {set_clause} WHERE id=?", vals)

    def delete_jazz_player(self, player_id):
        with self._connect() as conn:
            conn.execute("DELETE FROM jazz_players WHERE id=?", (player_id,))

    def reorder_jazz_players(self, ordered_ids):
        with self._connect() as conn:
            for idx, pid in enumerate(ordered_ids):
                conn.execute("UPDATE jazz_players SET sort_order=? WHERE id=?",
                             (idx, pid))

    # ── Jazz songs (locked personnel) ──

    def get_jazz_songs(self, ensemble_id, include_inactive=False):
        with self._connect() as conn:
            cond = "" if include_inactive else " AND is_active=1"
            return conn.execute(
                f"SELECT * FROM jazz_songs WHERE ensemble_id=?{cond} "
                "ORDER BY sort_order, id", (ensemble_id,)).fetchall()

    def get_jazz_song(self, song_id):
        with self._connect() as conn:
            return conn.execute("SELECT * FROM jazz_songs WHERE id=?",
                                (song_id,)).fetchone()

    def add_jazz_song(self, ensemble_id, title, locked=None, notes=None,
                      sort_order=None):
        with self._connect() as conn:
            if sort_order is None:
                row = conn.execute(
                    "SELECT COALESCE(MAX(sort_order), -1)+1 AS n "
                    "FROM jazz_songs WHERE ensemble_id=?", (ensemble_id,)
                ).fetchone()
                sort_order = row["n"]
            cur = conn.execute(
                "INSERT INTO jazz_songs (ensemble_id, title, locked, notes, sort_order) "
                "VALUES (?, ?, ?, ?, ?)",
                (ensemble_id, title, locked, notes, sort_order))
            return cur.lastrowid

    def update_jazz_song(self, song_id, data):
        cols = [c for c in ["title", "locked", "notes", "sort_order",
                            "is_active"] if c in data]
        if not cols:
            return
        set_clause = ", ".join(f"{c}=?" for c in cols)
        vals = [data[c] for c in cols] + [song_id]
        with self._connect() as conn:
            conn.execute(f"UPDATE jazz_songs SET {set_clause} WHERE id=?", vals)

    def delete_jazz_song(self, song_id):
        with self._connect() as conn:
            conn.execute("DELETE FROM jazz_songs WHERE id=?", (song_id,))

    # ─── Seating Charts ───────────────────────────────────────────────────────

    def get_seating_charts(self, school_year=None):
        with self._connect() as conn:
            if school_year:
                return conn.execute(
                    "SELECT * FROM seating_charts WHERE school_year=? ORDER BY name",
                    (school_year,)).fetchall()
            return conn.execute("SELECT * FROM seating_charts ORDER BY name").fetchall()

    def get_seating_chart(self, chart_id):
        with self._connect() as conn:
            return conn.execute("SELECT * FROM seating_charts WHERE id=?",
                                (chart_id,)).fetchone()

    def add_seating_chart(self, data):
        cols = ["school_year", "name", "chart_type", "config_json", "layout_json"]
        vals = [data.get(c) for c in cols]
        with self._connect() as conn:
            cur = conn.execute(
                f"INSERT INTO seating_charts ({','.join(cols)}) VALUES ({','.join(['?']*len(cols))})",
                vals)
            return cur.lastrowid

    def update_seating_chart(self, chart_id, data):
        cols = [c for c in ["name", "chart_type", "config_json", "layout_json"] if c in data]
        if not cols:
            return
        set_clause = ", ".join(f"{c}=?" for c in cols) + ", updated_at=datetime('now')"
        vals = [data[c] for c in cols] + [chart_id]
        with self._connect() as conn:
            conn.execute(f"UPDATE seating_charts SET {set_clause} WHERE id=?", vals)

    def delete_seating_chart(self, chart_id):
        with self._connect() as conn:
            conn.execute("DELETE FROM seating_charts WHERE id=?", (chart_id,))

    # ── Seating conflicts (keep-apart pairs) ──

    def get_seating_conflicts(self, school_year):
        with self._connect() as conn:
            return conn.execute(
                "SELECT * FROM seating_conflicts WHERE school_year=? ORDER BY name_a, name_b",
                (school_year,)).fetchall()

    def add_seating_conflict(self, school_year, name_a, name_b):
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO seating_conflicts (school_year, name_a, name_b) VALUES (?,?,?)",
                (school_year, name_a, name_b))

    def delete_seating_conflict(self, conflict_id):
        with self._connect() as conn:
            conn.execute("DELETE FROM seating_conflicts WHERE id=?", (conflict_id,))

    # ── Seating pins (IEP/504 placement) ──

    def get_seating_pins(self, school_year):
        with self._connect() as conn:
            return conn.execute(
                "SELECT * FROM seating_pins WHERE school_year=? ORDER BY student_name",
                (school_year,)).fetchall()

    def set_seating_pin(self, school_year, student_name, pref, note="", buffer=0):
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO seating_pins (school_year, student_name, pref, note, buffer) "
                "VALUES (?,?,?,?,?) ON CONFLICT(school_year, student_name) "
                "DO UPDATE SET pref=excluded.pref, note=excluded.note, buffer=excluded.buffer",
                (school_year, student_name, pref, note, int(buffer or 0)))

    def clear_seating_pin(self, school_year, student_name):
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM seating_pins WHERE school_year=? AND student_name=?",
                (school_year, student_name))

    # ─── Concerts (planning / programs / reminders) ──────────────────────────

    _CONCERT_COLS = ["school_year", "title", "concert_date", "start_time",
                     "end_time", "location", "offsite", "ensembles", "attire",
                     "bring", "arrival", "setup", "seated_by", "rehearsals",
                     "itinerary", "perf_order", "directors", "special_guests",
                     "acknowledgements", "upcoming", "extra_info",
                     "venue_reserved", "tutorials_scheduled",
                     "repertoire_final", "details_sent", "program_printed",
                     "setup_ready", "email_staff", "notes"]

    def get_program_setting(self, key, default=""):
        """Year-wide program values (e.g. the standing acknowledgements list) —
        entered once, used by every concert in this school year's file."""
        with self._connect() as conn:
            row = conn.execute("SELECT value FROM program_settings WHERE key=?",
                               (key,)).fetchone()
        return row["value"] if row and row["value"] is not None else default

    def set_program_setting(self, key, value):
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO program_settings (key, value) VALUES (?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value))

    def get_concerts(self, school_year=None):
        with self._connect() as conn:
            if school_year:
                return conn.execute(
                    "SELECT * FROM concerts WHERE school_year=? "
                    "ORDER BY concert_date, title", (school_year,)).fetchall()
            return conn.execute(
                "SELECT * FROM concerts ORDER BY concert_date, title").fetchall()

    def get_concert(self, concert_id):
        with self._connect() as conn:
            return conn.execute("SELECT * FROM concerts WHERE id=?",
                                (concert_id,)).fetchone()

    def add_concert(self, data):
        cols = self._CONCERT_COLS
        vals = [data.get(c) for c in cols]
        with self._connect() as conn:
            cur = conn.execute(
                f"INSERT INTO concerts ({','.join(cols)}) "
                f"VALUES ({','.join(['?'] * len(cols))})", vals)
            return cur.lastrowid

    def update_concert(self, concert_id, data):
        cols = [c for c in self._CONCERT_COLS if c in data]
        if not cols:
            return
        set_clause = ", ".join(f"{c}=?" for c in cols) + ", updated_at=datetime('now')"
        vals = [data[c] for c in cols] + [concert_id]
        with self._connect() as conn:
            conn.execute(f"UPDATE concerts SET {set_clause} WHERE id=?", vals)

    def delete_concert(self, concert_id):
        with self._connect() as conn:
            conn.execute("DELETE FROM concert_pieces WHERE concert_id=?", (concert_id,))
            conn.execute("DELETE FROM concert_reminders WHERE concert_id=?", (concert_id,))
            conn.execute("DELETE FROM concerts WHERE id=?", (concert_id,))

    # ── Repertoire per ensemble ──

    def get_concert_pieces(self, concert_id, ensemble=None):
        with self._connect() as conn:
            if ensemble:
                return conn.execute(
                    "SELECT * FROM concert_pieces WHERE concert_id=? AND ensemble=? "
                    "ORDER BY position, id", (concert_id, ensemble)).fetchall()
            return conn.execute(
                "SELECT * FROM concert_pieces WHERE concert_id=? "
                "ORDER BY ensemble, position, id", (concert_id,)).fetchall()

    def add_concert_piece(self, data):
        cols = ["concert_id", "ensemble", "title", "composer", "arranger", "position"]
        vals = [data.get(c) for c in cols]
        with self._connect() as conn:
            cur = conn.execute(
                f"INSERT INTO concert_pieces ({','.join(cols)}) "
                f"VALUES ({','.join(['?'] * len(cols))})", vals)
            return cur.lastrowid

    def update_concert_piece(self, piece_id, data):
        cols = [c for c in ("ensemble", "title", "composer", "arranger", "position")
                if c in data]
        if not cols:
            return
        set_clause = ", ".join(f"{c}=?" for c in cols)
        vals = [data[c] for c in cols] + [piece_id]
        with self._connect() as conn:
            conn.execute(f"UPDATE concert_pieces SET {set_clause} WHERE id=?", vals)

    def delete_concert_piece(self, piece_id):
        with self._connect() as conn:
            conn.execute("DELETE FROM concert_pieces WHERE id=?", (piece_id,))

    # ── Reminder tracking ──

    def get_concert_reminders(self, concert_id):
        with self._connect() as conn:
            return conn.execute(
                "SELECT * FROM concert_reminders WHERE concert_id=?",
                (concert_id,)).fetchall()

    def mark_concert_reminder(self, concert_id, stage, sent_date):
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO concert_reminders (concert_id, stage, sent_date) "
                "VALUES (?,?,?) ON CONFLICT(concert_id, stage) "
                "DO UPDATE SET sent_date=excluded.sent_date",
                (concert_id, stage, sent_date))

    def clear_concert_reminder(self, concert_id, stage):
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM concert_reminders WHERE concert_id=? AND stage=?",
                (concert_id, stage))

    # ─── Field trips ──────────────────────────────────────────────────────────

    _TRIP_COLS = ["school_year", "name", "groups_list", "destination",
                  "depart_date", "depart_time", "return_date", "return_time",
                  "travel_method", "entry_fee", "transport_cost", "food_cost",
                  "sub_cost", "other_cost", "funding", "covered", "approved",
                  "sub_assigned", "bus_requested", "registration_done",
                  "finalforms_done", "nurse_check", "notes",
                  "email_families", "email_chaperones", "email_teachers"]

    def get_field_trips(self, school_year=None):
        with self._connect() as conn:
            if school_year:
                return conn.execute(
                    "SELECT * FROM field_trips WHERE school_year=? "
                    "ORDER BY depart_date, name", (school_year,)).fetchall()
            return conn.execute(
                "SELECT * FROM field_trips ORDER BY depart_date, name").fetchall()

    def get_field_trip(self, trip_id):
        with self._connect() as conn:
            return conn.execute("SELECT * FROM field_trips WHERE id=?",
                                (trip_id,)).fetchone()

    def add_field_trip(self, data):
        cols = self._TRIP_COLS
        vals = [data.get(c) for c in cols]
        with self._connect() as conn:
            cur = conn.execute(
                f"INSERT INTO field_trips ({','.join(cols)}) "
                f"VALUES ({','.join(['?'] * len(cols))})", vals)
            return cur.lastrowid

    def update_field_trip(self, trip_id, data):
        cols = [c for c in self._TRIP_COLS if c in data]
        if not cols:
            return
        set_clause = ", ".join(f"{c}=?" for c in cols) + ", updated_at=datetime('now')"
        vals = [data[c] for c in cols] + [trip_id]
        with self._connect() as conn:
            conn.execute(f"UPDATE field_trips SET {set_clause} WHERE id=?", vals)

    def delete_field_trip(self, trip_id):
        with self._connect() as conn:
            conn.execute("DELETE FROM field_trip_exclusions WHERE trip_id=?", (trip_id,))
            conn.execute("DELETE FROM field_trip_chaperones WHERE trip_id=?", (trip_id,))
            conn.execute("DELETE FROM field_trip_reminders WHERE trip_id=?", (trip_id,))
            conn.execute("DELETE FROM field_trips WHERE id=?", (trip_id,))

    # ── Who's NOT going ──

    def get_trip_exclusions(self, trip_id):
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT student_id FROM field_trip_exclusions WHERE trip_id=?",
                (trip_id,)).fetchall()
        return {r["student_id"] for r in rows}

    def set_trip_exclusions(self, trip_id, student_ids):
        with self._connect() as conn:
            conn.execute("DELETE FROM field_trip_exclusions WHERE trip_id=?",
                         (trip_id,))
            conn.executemany(
                "INSERT OR IGNORE INTO field_trip_exclusions (trip_id, student_id) "
                "VALUES (?,?)", [(trip_id, sid) for sid in student_ids])

    # ── Chaperones ──

    def get_trip_chaperones(self, trip_id):
        with self._connect() as conn:
            return conn.execute(
                "SELECT * FROM field_trip_chaperones WHERE trip_id=? "
                "ORDER BY name", (trip_id,)).fetchall()

    def add_trip_chaperone(self, trip_id, name, phone="", email="", cleared=0):
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO field_trip_chaperones "
                "(trip_id, name, phone, email, cleared) VALUES (?,?,?,?,?)",
                (trip_id, name, phone, email, 1 if cleared else 0))
            return cur.lastrowid

    def update_trip_chaperone(self, chap_id, data):
        cols = [c for c in ("name", "phone", "email", "cleared") if c in data]
        if not cols:
            return
        set_clause = ", ".join(f"{c}=?" for c in cols)
        vals = [data[c] for c in cols] + [chap_id]
        with self._connect() as conn:
            conn.execute(
                f"UPDATE field_trip_chaperones SET {set_clause} WHERE id=?", vals)

    def delete_trip_chaperone(self, chap_id):
        with self._connect() as conn:
            conn.execute("DELETE FROM field_trip_chaperones WHERE id=?", (chap_id,))

    # ── Reminder tracking (stage e.g. 'families-2 weeks') ──

    def get_trip_reminders(self, trip_id):
        with self._connect() as conn:
            return conn.execute(
                "SELECT * FROM field_trip_reminders WHERE trip_id=?",
                (trip_id,)).fetchall()

    def mark_trip_reminder(self, trip_id, stage, sent_date):
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO field_trip_reminders (trip_id, stage, sent_date) "
                "VALUES (?,?,?) ON CONFLICT(trip_id, stage) "
                "DO UPDATE SET sent_date=excluded.sent_date",
                (trip_id, stage, sent_date))

    def clear_trip_reminder(self, trip_id, stage):
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM field_trip_reminders WHERE trip_id=? AND stage=?",
                (trip_id, stage))

    # ─── Stats ────────────────────────────────────────────────────────────────

    def get_lesson_plan_stats(self):
        with self._connect() as conn:
            classes = conn.execute(
                "SELECT COUNT(*) FROM teaching_classes WHERE is_active=1"
            ).fetchone()[0]
            curriculum_items = conn.execute("SELECT COUNT(*) FROM curriculum_items").fetchone()[0]
            lesson_plans = conn.execute("SELECT COUNT(*) FROM lesson_plans").fetchone()[0]
            resources = conn.execute("SELECT COUNT(*) FROM resources").fetchone()[0]
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


# ─── Factory Functions ────────────────────────────────────────────────────────

def current_school_year() -> str:
    """Get the current school year string (e.g., '2025-2026')."""
    today = datetime.today()
    if today.month >= 8:
        return f"{today.year}-{today.year + 1}"
    return f"{today.year - 1}-{today.year}"


def get_lesson_plan_db_path(base_dir: str, school_year: str) -> str:
    """Get the path for a school year's lesson plan database."""
    return os.path.join(base_dir, f"lesson_plans_{school_year}.db")


def get_lesson_plan_db(base_dir: str, school_year: str = None) -> LessonPlanDatabase:
    """
    Get or create a LessonPlanDatabase for the given school year.

    Args:
        base_dir: Profile directory (where rokas_resonance.db lives)
        school_year: e.g., "2025-2026". Defaults to current school year.

    Returns:
        LessonPlanDatabase instance
    """
    if not school_year:
        school_year = current_school_year()
    db_path = get_lesson_plan_db_path(base_dir, school_year)
    return LessonPlanDatabase(db_path)


def list_available_school_years(base_dir: str) -> list:
    """List all school years that have lesson plan databases."""
    years = []
    if not os.path.isdir(base_dir):
        return years
    for fname in os.listdir(base_dir):
        if fname.startswith("lesson_plans_") and fname.endswith(".db"):
            year = fname[len("lesson_plans_"):-len(".db")]
            years.append(year)
    years.sort(reverse=True)
    return years


def migrate_from_main_db(main_db_path: str, base_dir: str) -> str:
    """
    One-time migration: move lesson plan data from the main database
    to a separate per-year database.

    Returns the school year that was migrated, or None if no data to migrate.
    """
    import sqlite3 as _sqlite3

    main_conn = _sqlite3.connect(main_db_path)
    main_conn.row_factory = _sqlite3.Row

    # Check if main DB has lesson plan data
    try:
        count = main_conn.execute("SELECT COUNT(*) FROM teaching_classes").fetchone()[0]
    except _sqlite3.OperationalError:
        main_conn.close()
        return None  # No teaching_classes table — nothing to migrate

    if count == 0:
        main_conn.close()
        return None

    # Determine school year from the classes
    row = main_conn.execute(
        "SELECT school_year FROM teaching_classes WHERE school_year IS NOT NULL LIMIT 1"
    ).fetchone()
    school_year = row[0] if row else current_school_year()

    # Check if already migrated
    target_path = get_lesson_plan_db_path(base_dir, school_year)
    if os.path.exists(target_path):
        target_db = LessonPlanDatabase(target_path)
        existing = target_db.get_all_classes()
        if existing:
            main_conn.close()
            return school_year  # Already migrated

    # Create target DB and copy data
    target_db = LessonPlanDatabase(target_path)
    target_conn = _sqlite3.connect(target_path)

    tables = [
        "teaching_classes", "concert_dates", "curriculum_items",
        "lesson_plans", "lesson_blocks", "resources", "resource_tags",
        "lesson_plan_resources", "lesson_templates", "onenote_sync",
    ]

    for table in tables:
        try:
            rows = main_conn.execute(f"SELECT * FROM {table}").fetchall()
            if not rows:
                continue
            cols = [desc[0] for desc in main_conn.execute(f"SELECT * FROM {table} LIMIT 0").description]
            placeholders = ",".join(["?"] * len(cols))
            col_str = ",".join(cols)
            for row in rows:
                target_conn.execute(
                    f"INSERT OR IGNORE INTO {table} ({col_str}) VALUES ({placeholders})",
                    tuple(row),
                )
            target_conn.commit()
        except _sqlite3.OperationalError:
            pass  # Table doesn't exist in main DB

    target_conn.close()
    main_conn.close()

    return school_year
