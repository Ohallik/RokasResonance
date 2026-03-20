"""
lesson_plan_importer.py - Import existing lesson plans, curricula, and agendas
into the Roka's Resonance Lesson Plans module.

Supported formats:
  - CSV / TSV files (structured columns: date, topic, objectives, etc.)
  - Plain text / Markdown (semi-structured lists or paragraphs)
  - JSON export (from another Roka's Resonance instance)
  - LLM-assisted import (unstructured documents parsed via AI)
"""

import csv
import json
import os
import re
from datetime import datetime, timedelta
from database import Database


# ─── Utility Helpers ──────────────────────────────────────────────────────────

def _open_csv(path: str):
    """Open a CSV with BOM-aware encoding and fallback."""
    return open(path, encoding="utf-8-sig", errors="replace", newline="")


def _normalize_date(date_str: str) -> str:
    """Normalize dates to YYYY-MM-DD. Returns '' if unparseable."""
    if not date_str:
        return ""
    date_str = date_str.strip()
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d", "%B %d, %Y", "%b %d, %Y",
                "%d %B %Y", "%d %b %Y", "%m-%d-%Y", "%m-%d-%y",
                "%Y/%m/%d", "%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(date_str, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return ""


def _guess_activity_type(text: str) -> str:
    """Guess activity type from lesson/agenda text."""
    text_lower = (text or "").lower()
    if any(w in text_lower for w in ("concert", "performance", "recital", "show")):
        return "concert"
    if any(w in text_lower for w in ("concert prep", "rehearsal", "run-through",
                                      "dress rehearsal")):
        return "concert_prep"
    if any(w in text_lower for w in ("test", "quiz", "assessment", "playing test",
                                      "evaluation", "rubric")):
        return "assessment"
    if any(w in text_lower for w in ("sight-read", "sight read", "sightread")):
        return "sight_reading"
    if any(w in text_lower for w in ("theory", "notation", "scales", "key signature")):
        return "theory"
    if any(w in text_lower for w in ("compose", "composition", "improvise",
                                      "improvisation", "create")):
        return "composition"
    if any(w in text_lower for w in ("listen", "recording", "analysis")):
        return "listening"
    if any(w in text_lower for w in ("no school", "holiday", "break",
                                      "teacher work day", "inservice")):
        return "no_class"
    if any(w in text_lower for w in ("flex", "catch-up", "catch up", "review")):
        return "flex"
    return "skill_building"


def _detect_delimiter(path: str) -> str:
    """Detect CSV delimiter by sniffing the first few lines."""
    with _open_csv(path) as f:
        sample = f.read(4096)
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",\t;|")
        return dialect.delimiter
    except csv.Error:
        return ","


def _find_date_column(headers: list[str]) -> int:
    """Find the column index most likely to contain dates."""
    date_keywords = ["date", "day", "when", "class date", "lesson date"]
    for i, h in enumerate(headers):
        if h.lower().strip() in date_keywords:
            return i
    # Fallback: try first column
    return 0


def _find_column(headers: list[str], keywords: list[str]) -> int:
    """Find column index matching any keyword. Returns -1 if not found."""
    for i, h in enumerate(headers):
        h_lower = h.lower().strip()
        for kw in keywords:
            if kw in h_lower:
                return i
    return -1


# ─── CSV / TSV Import ─────────────────────────────────────────────────────────

def import_curriculum_from_csv(db: Database, csv_path: str, class_id: int,
                                preview_only: bool = False) -> dict:
    """
    Import curriculum items from a CSV/TSV file.

    Expected columns (flexible matching):
      - Date column (required): 'date', 'day', 'class date', etc.
      - Topic/summary column: 'topic', 'summary', 'lesson', 'agenda', 'description'
      - Unit column (optional): 'unit', 'unit name', 'chapter', 'section'
      - Objectives column (optional): 'objectives', 'goals', 'learning objectives'
      - Notes column (optional): 'notes', 'comments', 'details'

    Returns:
        {
            'imported': int,
            'skipped': int,
            'errors': list[str],
            'preview': list[dict]  (if preview_only)
        }
    """
    result = {"imported": 0, "skipped": 0, "errors": [], "preview": []}

    if not os.path.exists(csv_path):
        result["errors"].append(f"File not found: {csv_path}")
        return result

    delimiter = _detect_delimiter(csv_path)

    with _open_csv(csv_path) as f:
        reader = csv.reader(f, delimiter=delimiter)
        rows = list(reader)

    if len(rows) < 2:
        result["errors"].append("File has no data rows (only header or empty)")
        return result

    headers = [h.strip() for h in rows[0]]
    date_col = _find_date_column(headers)
    summary_col = _find_column(headers, ["topic", "summary", "lesson", "agenda",
                                          "description", "title", "content"])
    unit_col = _find_column(headers, ["unit", "chapter", "section", "module"])
    objectives_col = _find_column(headers, ["objective", "goal", "learning"])
    notes_col = _find_column(headers, ["note", "comment", "detail", "additional"])

    if summary_col == -1:
        # If no summary column found, use the column after the date
        summary_col = min(date_col + 1, len(headers) - 1)

    items_to_import = []

    for row_num, row in enumerate(rows[1:], start=2):
        if not row or all(not cell.strip() for cell in row):
            continue

        # Parse date
        raw_date = row[date_col].strip() if date_col < len(row) else ""
        item_date = _normalize_date(raw_date)
        if not item_date:
            result["errors"].append(f"Row {row_num}: Could not parse date '{raw_date}'")
            result["skipped"] += 1
            continue

        # Parse summary
        summary = row[summary_col].strip() if summary_col < len(row) else ""
        if not summary:
            result["skipped"] += 1
            continue

        # Parse optional fields
        unit_name = row[unit_col].strip() if unit_col >= 0 and unit_col < len(row) else ""
        objectives = row[objectives_col].strip() if objectives_col >= 0 and objectives_col < len(row) else ""
        notes = row[notes_col].strip() if notes_col >= 0 and notes_col < len(row) else ""

        # Combine objectives into notes if present
        if objectives and notes:
            notes = f"Objectives: {objectives}\n{notes}"
        elif objectives:
            notes = f"Objectives: {objectives}"

        item = {
            "class_id": class_id,
            "item_date": item_date,
            "summary": summary,
            "activity_type": _guess_activity_type(summary),
            "unit_name": unit_name,
            "is_locked": 0,
            "sort_order": 0,
            "notes": notes,
        }
        items_to_import.append(item)

    if preview_only:
        result["preview"] = items_to_import
        return result

    # Import into database
    if items_to_import:
        db.bulk_add_curriculum_items(items_to_import)
        result["imported"] = len(items_to_import)

    return result


# ─── Plain Text / Markdown Import ─────────────────────────────────────────────

def import_curriculum_from_text(db: Database, text_content: str, class_id: int,
                                 start_date: str = None,
                                 days_of_week: str = "M,T,W,Th,F",
                                 preview_only: bool = False) -> dict:
    """
    Import curriculum items from plain text or Markdown.

    Supports several formats:
      - "MM/DD/YYYY: Topic description" (date-prefixed lines)
      - "Week 1: Topic" or "Week 1\nMonday: Topic\nTuesday: Topic"
      - "- Topic 1\n- Topic 2" (bulleted list, assigned to sequential days)
      - "1. Topic 1\n2. Topic 2" (numbered list, assigned to sequential days)
      - "## Unit Name\n- Topic 1\n- Topic 2" (Markdown with unit headers)

    If dates are not embedded in the text, items are assigned to sequential
    school days starting from start_date using the given days_of_week pattern.

    Returns same dict as import_curriculum_from_csv.
    """
    result = {"imported": 0, "skipped": 0, "errors": [], "preview": []}

    lines = text_content.strip().split("\n")
    if not lines:
        result["errors"].append("No content to import")
        return result

    # Parse days_of_week into weekday numbers (0=Monday)
    day_map = {"m": 0, "t": 1, "w": 2, "th": 3, "f": 4, "sa": 5, "su": 6,
               "mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
    active_days = set()
    for d in days_of_week.split(","):
        d_lower = d.strip().lower()
        if d_lower in day_map:
            active_days.add(day_map[d_lower])
    if not active_days:
        active_days = {0, 1, 2, 3, 4}  # default M-F

    # Try to detect format
    items = []
    current_unit = ""

    # Pattern 1: Date-prefixed lines (e.g., "9/3/2025: Instrument assembly")
    date_prefix_pattern = re.compile(
        r"^(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4})\s*[:|\-\s]\s*(.+)$"
    )

    # Pattern 2: Week headers
    week_pattern = re.compile(r"^(?:week|wk)\s*(\d+)\s*[:|\-\s]*(.*)$", re.IGNORECASE)

    # Pattern 3: Markdown headers (## Unit Name)
    header_pattern = re.compile(r"^#{1,4}\s+(.+)$")

    # Pattern 4: Bullet or numbered list items
    list_pattern = re.compile(r"^\s*(?:[-*•]|\d+[.)]\s)\s*(.+)$")

    # Pattern 5: Day-of-week prefixed (e.g., "Monday: Topic")
    day_prefix_pattern = re.compile(
        r"^(monday|tuesday|wednesday|thursday|friday|mon|tue|wed|thu|fri)\s*[:|\-\s]\s*(.+)$",
        re.IGNORECASE,
    )

    has_dates = False
    for line in lines:
        line = line.strip()
        if date_prefix_pattern.match(line):
            has_dates = True
            break

    if has_dates:
        # Mode 1: Date-prefixed lines
        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Check for unit headers
            hm = header_pattern.match(line)
            if hm:
                current_unit = hm.group(1).strip()
                continue

            dm = date_prefix_pattern.match(line)
            if dm:
                raw_date = dm.group(1)
                summary = dm.group(2).strip()
                item_date = _normalize_date(raw_date)
                if item_date and summary:
                    items.append({
                        "class_id": class_id,
                        "item_date": item_date,
                        "summary": summary,
                        "activity_type": _guess_activity_type(summary),
                        "unit_name": current_unit,
                        "is_locked": 0,
                        "sort_order": 0,
                        "notes": "",
                    })
    else:
        # Mode 2: Sequential assignment — extract topics, assign to school days
        if not start_date:
            result["errors"].append(
                "No dates found in text and no start_date provided. "
                "Please provide a start date for sequential assignment."
            )
            return result

        topics = []
        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Check for unit headers
            hm = header_pattern.match(line)
            if hm:
                current_unit = hm.group(1).strip()
                continue

            # Check for week headers
            wm = week_pattern.match(line)
            if wm:
                week_topic = wm.group(2).strip()
                if week_topic:
                    topics.append((week_topic, current_unit))
                continue

            # Check for list items
            lm = list_pattern.match(line)
            if lm:
                topics.append((lm.group(1).strip(), current_unit))
                continue

            # Plain text line that's not empty
            if len(line) > 3 and not line.startswith("#"):
                topics.append((line, current_unit))

        # Assign topics to sequential school days
        current = datetime.strptime(start_date, "%Y-%m-%d")
        for topic_text, unit in topics:
            # Skip to next active school day
            while current.weekday() not in active_days:
                current += timedelta(days=1)

            items.append({
                "class_id": class_id,
                "item_date": current.strftime("%Y-%m-%d"),
                "summary": topic_text,
                "activity_type": _guess_activity_type(topic_text),
                "unit_name": unit,
                "is_locked": 0,
                "sort_order": 0,
                "notes": "",
            })
            # Advance to next day
            current += timedelta(days=1)

    if preview_only:
        result["preview"] = items
        return result

    if items:
        db.bulk_add_curriculum_items(items)
        result["imported"] = len(items)

    return result


# ─── JSON Export/Import (Roka's Resonance format) ─────────────────────────────

def export_curriculum_to_json(db: Database, class_id: int) -> dict:
    """
    Export a class's curriculum and lesson plans as a JSON-serializable dict.
    This format can be shared with other Roka's Resonance users.
    """
    cls = db.get_class(class_id)
    if not cls:
        return {"error": "Class not found"}

    concerts = db.get_concert_dates(class_id)
    items = db.get_curriculum_items(class_id)

    curriculum_data = []
    for item in items:
        item_dict = dict(item)
        # Include lesson plan if it exists
        plan = db.get_lesson_plan_by_curriculum_item(item["id"])
        if plan:
            plan_dict = dict(plan)
            # Include blocks
            blocks = db.get_lesson_blocks(plan["id"])
            plan_dict["blocks"] = [dict(b) for b in blocks]
            # Include linked resources
            resources = db.get_resources_for_plan(plan["id"])
            plan_dict["resources"] = [
                {"display_name": r["display_name"], "resource_type": r["resource_type"],
                 "url_or_path": r["url_or_path"], "description": r["description"]}
                for r in resources
            ]
            item_dict["lesson_plan"] = plan_dict
        curriculum_data.append(item_dict)

    return {
        "format": "rokas_resonance_curriculum_v1",
        "exported_at": datetime.now().isoformat(),
        "class": dict(cls),
        "concert_dates": [dict(c) for c in concerts],
        "curriculum_items": curriculum_data,
    }


def import_curriculum_from_json(db: Database, json_path: str, class_id: int,
                                 preview_only: bool = False) -> dict:
    """
    Import curriculum from a Roka's Resonance JSON export.
    Maps items to the specified class_id (may differ from the original).
    """
    result = {"imported": 0, "skipped": 0, "errors": [], "preview": []}

    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, FileNotFoundError) as e:
        result["errors"].append(f"Failed to read JSON: {e}")
        return result

    if data.get("format") != "rokas_resonance_curriculum_v1":
        result["errors"].append(
            "Unknown format. Expected 'rokas_resonance_curriculum_v1'."
        )
        return result

    items_data = data.get("curriculum_items", [])
    if not items_data:
        result["errors"].append("No curriculum items found in file")
        return result

    items_to_import = []
    plans_to_import = []

    for item in items_data:
        ci = {
            "class_id": class_id,
            "item_date": item.get("item_date", ""),
            "summary": item.get("summary", ""),
            "activity_type": item.get("activity_type", "skill_building"),
            "unit_name": item.get("unit_name", ""),
            "is_locked": item.get("is_locked", 0),
            "sort_order": item.get("sort_order", 0),
            "notes": item.get("notes", ""),
        }
        if not ci["item_date"] or not ci["summary"]:
            result["skipped"] += 1
            continue
        items_to_import.append(ci)

        # Track lesson plan data for later import
        lp = item.get("lesson_plan")
        if lp:
            plans_to_import.append({
                "item_index": len(items_to_import) - 1,
                "plan_data": lp,
            })

    if preview_only:
        result["preview"] = items_to_import
        return result

    # Import curriculum items
    if items_to_import:
        new_ids = db.bulk_add_curriculum_items(items_to_import)
        result["imported"] = len(new_ids)

        # Import lesson plans that were attached
        for plan_info in plans_to_import:
            idx = plan_info["item_index"]
            if idx < len(new_ids):
                lp = plan_info["plan_data"]
                plan_id = db.add_lesson_plan({
                    "curriculum_item_id": new_ids[idx],
                    "objectives": lp.get("objectives", ""),
                    "standards": lp.get("standards", ""),
                    "warmup_text": lp.get("warmup_text", ""),
                    "warmup_template_id": None,
                    "assessment_type": lp.get("assessment_type", ""),
                    "assessment_details": lp.get("assessment_details", ""),
                    "differentiation_advanced": lp.get("differentiation_advanced", ""),
                    "differentiation_struggling": lp.get("differentiation_struggling", ""),
                    "differentiation_iep": lp.get("differentiation_iep", ""),
                    "reflection_text": lp.get("reflection_text", ""),
                    "reflection_rating": lp.get("reflection_rating", ""),
                    "status": lp.get("status", "imported"),
                    "total_minutes_planned": lp.get("total_minutes_planned", 0),
                    "notes": lp.get("notes", ""),
                })

                # Import blocks
                for block in lp.get("blocks", []):
                    db.add_lesson_block({
                        "lesson_plan_id": plan_id,
                        "block_type": block.get("block_type", "custom"),
                        "title": block.get("title", ""),
                        "description": block.get("description", ""),
                        "duration_minutes": block.get("duration_minutes", 5),
                        "sort_order": block.get("sort_order", 0),
                        "music_piece_id": None,  # can't map cross-instance
                        "measure_start": block.get("measure_start"),
                        "measure_end": block.get("measure_end"),
                        "technique_focus": block.get("technique_focus", ""),
                        "difficulty_level": block.get("difficulty_level", ""),
                        "grouping": block.get("grouping", ""),
                        "notes": block.get("notes", ""),
                    })

    # Import concert dates if present
    concert_dates = data.get("concert_dates", [])
    for cd in concert_dates:
        db.add_concert_date({
            "class_id": class_id,
            "concert_date": cd.get("concert_date", ""),
            "event_name": cd.get("event_name", ""),
            "location": cd.get("location", ""),
            "notes": cd.get("notes", ""),
        })

    return result


# ─── LLM-Assisted Import ─────────────────────────────────────────────────────

def build_llm_import_prompt(raw_text: str, class_info: dict) -> str:
    """
    Build a prompt for the LLM to parse unstructured lesson plan text
    into structured curriculum items.

    The LLM response should be JSON that can be fed into
    import_curriculum_from_llm_response().
    """
    return f"""You are helping a middle school music teacher import their existing lesson plans into a digital planning tool.

The teacher teaches: {class_info.get('class_name', 'Unknown')}
Ensemble type: {class_info.get('ensemble_type', 'Unknown')}
Grade level(s): {class_info.get('grade_levels', 'Unknown')}
Skill level: {class_info.get('skill_level', 'Unknown')}
School year: {class_info.get('school_year', 'Unknown')}

Below is the raw text from their existing lesson plans, agendas, or curriculum documents. Parse this into structured curriculum items.

For each item, extract:
- item_date: the date in YYYY-MM-DD format (if dates are mentioned)
- summary: a brief 1-2 sentence description of what is being taught
- activity_type: one of [skill_building, concert_prep, concert, assessment, sight_reading, theory, composition, listening, flex, no_class]
- unit_name: the unit or chapter this belongs to (if identifiable)
- notes: any additional details, objectives, or materials mentioned

If exact dates are not provided but a sequence is clear (Week 1, Week 2, etc.), use relative ordering and note that dates need to be assigned.

Return ONLY a JSON array of objects. No markdown, no explanation.

Example output:
[
  {{"item_date": "2025-09-03", "summary": "Instrument assembly and care", "activity_type": "skill_building", "unit_name": "Fundamentals", "notes": "EE Book 1 pp. 4-6"}},
  {{"item_date": "2025-09-04", "summary": "First notes: B-flat, F, E-flat", "activity_type": "skill_building", "unit_name": "Fundamentals", "notes": ""}}
]

RAW TEXT:
{raw_text}
"""


def import_curriculum_from_llm_response(db: Database, llm_json: str,
                                         class_id: int,
                                         start_date: str = None,
                                         days_of_week: str = "M,T,W,Th,F",
                                         preview_only: bool = False) -> dict:
    """
    Import curriculum items from LLM-parsed JSON response.
    If items lack dates, assigns sequential school days from start_date.
    """
    result = {"imported": 0, "skipped": 0, "errors": [], "preview": []}

    # Parse the LLM response — handle markdown code blocks
    cleaned = llm_json.strip()
    if cleaned.startswith("```"):
        # Remove markdown code fence
        lines = cleaned.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        cleaned = "\n".join(lines)

    try:
        items_data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        result["errors"].append(f"Failed to parse LLM response as JSON: {e}")
        return result

    if not isinstance(items_data, list):
        result["errors"].append("Expected a JSON array from LLM response")
        return result

    # Parse days_of_week
    day_map = {"m": 0, "t": 1, "w": 2, "th": 3, "f": 4, "sa": 5, "su": 6}
    active_days = set()
    for d in days_of_week.split(","):
        d_lower = d.strip().lower()
        if d_lower in day_map:
            active_days.add(day_map[d_lower])
    if not active_days:
        active_days = {0, 1, 2, 3, 4}

    # Track current date for items missing dates
    current_date = None
    if start_date:
        current_date = datetime.strptime(start_date, "%Y-%m-%d")

    items_to_import = []
    for item in items_data:
        item_date = _normalize_date(item.get("item_date", ""))

        if not item_date and current_date:
            # Assign next school day
            while current_date.weekday() not in active_days:
                current_date += timedelta(days=1)
            item_date = current_date.strftime("%Y-%m-%d")
            current_date += timedelta(days=1)

        summary = (item.get("summary") or "").strip()
        if not summary:
            result["skipped"] += 1
            continue

        ci = {
            "class_id": class_id,
            "item_date": item_date,
            "summary": summary,
            "activity_type": item.get("activity_type", _guess_activity_type(summary)),
            "unit_name": item.get("unit_name", ""),
            "is_locked": 0,
            "sort_order": 0,
            "notes": item.get("notes", ""),
        }
        items_to_import.append(ci)

    if preview_only:
        result["preview"] = items_to_import
        return result

    if items_to_import:
        db.bulk_add_curriculum_items(items_to_import)
        result["imported"] = len(items_to_import)

    return result


# ─── File Type Detection ──────────────────────────────────────────────────────

def detect_import_format(file_path: str) -> str:
    """
    Detect the import format of a file.
    Returns: 'csv', 'json', 'text', or 'unknown'
    """
    ext = os.path.splitext(file_path)[1].lower()
    if ext in (".csv", ".tsv"):
        return "csv"
    if ext == ".json":
        return "json"
    if ext in (".txt", ".md", ".markdown", ".text"):
        return "text"
    # Try to sniff content
    try:
        with open(file_path, "r", encoding="utf-8-sig", errors="replace") as f:
            first_line = f.readline(512)
        if first_line.strip().startswith(("{", "[")):
            return "json"
        if "\t" in first_line or first_line.count(",") >= 2:
            return "csv"
        return "text"
    except Exception:
        return "unknown"


def import_from_file(db: Database, file_path: str, class_id: int,
                     start_date: str = None, days_of_week: str = "M,T,W,Th,F",
                     preview_only: bool = False) -> dict:
    """
    Auto-detect file format and import curriculum items.
    Convenience wrapper that dispatches to the appropriate importer.
    """
    fmt = detect_import_format(file_path)

    if fmt == "csv":
        return import_curriculum_from_csv(db, file_path, class_id,
                                           preview_only=preview_only)
    elif fmt == "json":
        return import_curriculum_from_json(db, file_path, class_id,
                                            preview_only=preview_only)
    elif fmt == "text":
        with open(file_path, "r", encoding="utf-8-sig", errors="replace") as f:
            content = f.read()
        return import_curriculum_from_text(db, content, class_id,
                                            start_date=start_date,
                                            days_of_week=days_of_week,
                                            preview_only=preview_only)
    else:
        return {
            "imported": 0, "skipped": 0, "preview": [],
            "errors": [f"Unsupported file format: {os.path.splitext(file_path)[1]}"],
        }
