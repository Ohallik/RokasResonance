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
            """)
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
