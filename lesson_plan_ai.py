"""
lesson_plan_ai.py - AI engine for curriculum generation and lesson plan assistance.

Provides LLM-powered features for the Lesson Plans module:
  - Year-long curriculum generation (from scratch, from previous data, hybrid)
  - Individual lesson plan generation and refinement
  - Teaching idea suggestions with web search
  - Curriculum alignment checking

Uses the existing llm_client.py infrastructure (GitHub Models + Anthropic).
"""

import json
import os
from datetime import datetime, timedelta
from database import Database


# ─── File Context Reading ─────────────────────────────────────────────────────

# File extensions we can extract text from
_TEXT_EXTENSIONS = {".txt", ".csv", ".tsv", ".md", ".markdown", ".json", ".xml", ".html"}
_PDF_EXTENSION = ".pdf"
_MAX_FILE_SIZE = 500_000  # 500KB per file
_MAX_TOTAL_CONTEXT = 50_000  # 50K chars total for file context


def read_file_as_text(file_path: str) -> str:
    """Read a file and return its text content. Supports text files and PDFs."""
    if not os.path.exists(file_path):
        return ""

    ext = os.path.splitext(file_path)[1].lower()

    # Skip files that are too large
    try:
        if os.path.getsize(file_path) > _MAX_FILE_SIZE:
            return f"[File too large: {os.path.basename(file_path)}]"
    except OSError:
        return ""

    # Text-based files
    if ext in _TEXT_EXTENSIONS:
        try:
            with open(file_path, "r", encoding="utf-8-sig", errors="replace") as f:
                return f.read()
        except Exception:
            return ""

    # PDF files (using pymupdf which is already in requirements)
    if ext == _PDF_EXTENSION:
        try:
            import fitz  # pymupdf
            doc = fitz.open(file_path)
            text_parts = []
            for page_num in range(min(doc.page_count, 20)):  # max 20 pages
                page = doc[page_num]
                text_parts.append(page.get_text())
            doc.close()
            return "\n".join(text_parts)
        except ImportError:
            return f"[PDF file: {os.path.basename(file_path)} — pymupdf not available]"
        except Exception:
            return ""

    return ""


def read_folder_as_context(folder_path: str) -> str:
    """Read all readable files in a folder and return combined text context."""
    if not os.path.isdir(folder_path):
        return ""

    supported_exts = _TEXT_EXTENSIONS | {_PDF_EXTENSION}
    parts = []
    total_chars = 0

    # Sort files for consistent ordering
    try:
        files = sorted(os.listdir(folder_path))
    except OSError:
        return ""

    for filename in files:
        file_path = os.path.join(folder_path, filename)
        if not os.path.isfile(file_path):
            continue

        ext = os.path.splitext(filename)[1].lower()
        if ext not in supported_exts:
            continue

        content = read_file_as_text(file_path)
        if content:
            header = f"\n--- {filename} ---\n"
            if total_chars + len(content) + len(header) > _MAX_TOTAL_CONTEXT:
                parts.append(f"\n[Remaining files truncated — context limit reached]")
                break
            parts.append(header + content)
            total_chars += len(content) + len(header)

    return "".join(parts) if parts else ""


def build_file_context(paths: list) -> str:
    """Build context string from a list of file and/or folder paths.

    Args:
        paths: List of file paths or folder paths

    Returns:
        Combined text content with file headers
    """
    if not paths:
        return ""

    all_parts = ["REFERENCE MATERIALS PROVIDED BY TEACHER:"]
    total_chars = 0

    for path in paths:
        if os.path.isdir(path):
            folder_text = read_folder_as_context(path)
            if folder_text:
                folder_name = os.path.basename(path)
                header = f"\n=== Folder: {folder_name} ===\n"
                all_parts.append(header + folder_text)
                total_chars += len(header) + len(folder_text)
        elif os.path.isfile(path):
            file_text = read_file_as_text(path)
            if file_text:
                filename = os.path.basename(path)
                header = f"\n--- {filename} ---\n"
                all_parts.append(header + file_text)
                total_chars += len(header) + len(file_text)

        if total_chars > _MAX_TOTAL_CONTEXT:
            all_parts.append("\n[Context truncated — limit reached]")
            break

    return "\n".join(all_parts) if len(all_parts) > 1 else ""


# ─── System Prompts ───────────────────────────────────────────────────────────

_CURRICULUM_SYSTEM = """You are an expert middle school music education curriculum designer.
You have deep knowledge of:
- National Core Arts Standards and Washington State K-12 Arts Learning Standards
- Essential Elements method books (Band, Strings) scope and sequence
- Suzuki method progression for strings
- Essential Musicianship and Choir Builders for choral programs
- Standard middle school class structures (40-45 min periods)
- Concert cycle planning (fall, winter, spring concerts)
- Differentiated instruction for beginning through advanced levels
- Assessment strategies for music education (formative, summative, performance-based)

When generating curricula, you always:
- Pace content realistically for the skill level and grade
- Build toward concert dates as structural anchors
- Interleave technique, theory, sight-reading, and repertoire
- Include assessment checkpoints every 2-3 weeks
- Account for school holidays and breaks
- Provide specific method book page references when applicable"""

_LESSON_PLAN_SYSTEM = """You are an expert middle school music teacher's assistant.
You help teachers create, refine, and improve daily lesson plans for band, orchestra, choir,
and general music classes. You understand:
- Typical class period structures (warm-up, main activity, assessment, reflection)
- Age-appropriate engagement strategies for grades 6-8
- Differentiation for mixed-ability ensembles
- Practical classroom management for large groups (30-100+ students)
- How to adjust when things aren't working mid-lesson
- Assessment strategies that don't disrupt rehearsal flow

When creating or modifying lesson plans, you always:
- Include specific, measurable learning objectives
- Provide realistic time allocations that fit the class period
- Suggest concrete activities (not vague instructions)
- Reference specific measures, pages, or exercises when applicable
- Consider student engagement and energy levels throughout the period"""


# ─── Context Gathering (Data Pipeline) ───────────────────────────────────────

def _build_class_context(db: Database, class_id: int) -> str:
    """Build context string about a teaching class for the LLM."""
    cls = db.get_class(class_id)
    if not cls:
        return ""

    parts = [
        f"Class: {cls['class_name']}",
        f"Ensemble Type: {cls['ensemble_type']}",
        f"Grade Level(s): {cls['grade_levels']}",
        f"Skill Level: {cls['skill_level']}",
        f"Class Duration: {cls['class_duration']} minutes",
        f"Days: {cls['days_of_week']}",
        f"School Year: {cls['school_year']}",
    ]
    if cls['method_book']:
        parts.append(f"Method Book: {cls['method_book']}")
    if cls['student_count']:
        parts.append(f"Student Count: {cls['student_count']}")
    if cls['notes']:
        parts.append(f"Notes: {cls['notes']}")

    # Concert dates
    concerts = db.get_concert_dates(class_id)
    if concerts:
        concert_strs = [
            f"  - {c['concert_date']}: {c['event_name'] or 'Concert'}"
            for c in concerts
        ]
        parts.append("Concert Dates:\n" + "\n".join(concert_strs))

    return "\n".join(parts)


def _build_curriculum_context(db: Database, class_id: int, limit: int = 30) -> str:
    """Build context from existing curriculum items for the LLM."""
    items = db.get_curriculum_items(class_id)
    if not items:
        return "No existing curriculum items."

    lines = ["Existing Curriculum:"]
    for item in items[:limit]:
        locked = " [LOCKED]" if item["is_locked"] else ""
        unit = f" ({item['unit_name']})" if item["unit_name"] else ""
        lines.append(
            f"  {item['item_date']}: {item['summary']}"
            f" [{item['activity_type']}]{unit}{locked}"
        )
    if len(items) > limit:
        lines.append(f"  ... and {len(items) - limit} more items")
    return "\n".join(lines)


def _build_lesson_plan_context(db: Database, class_id: int, date_str: str) -> str:
    """Build context about a specific day's lesson plan and surrounding days."""
    parts = []

    # Previous day's plan
    prev_date = datetime.strptime(date_str, "%Y-%m-%d") - timedelta(days=1)
    # Skip weekends
    while prev_date.weekday() >= 5:
        prev_date -= timedelta(days=1)
    prev_item = db.get_curriculum_item_by_date(class_id, prev_date.strftime("%Y-%m-%d"))
    if prev_item:
        parts.append(f"Previous lesson ({prev_date.strftime('%m/%d')}): {prev_item['summary']}")
        prev_plan = db.get_lesson_plan_by_curriculum_item(prev_item["id"])
        if prev_plan and prev_plan["reflection_text"]:
            parts.append(f"  Teacher reflection: {prev_plan['reflection_text']}")
        if prev_plan and prev_plan["reflection_rating"]:
            parts.append(f"  Rating: {prev_plan['reflection_rating']}")

    # Current day
    curr_item = db.get_curriculum_item_by_date(class_id, date_str)
    if curr_item:
        parts.append(f"Current day ({date_str}): {curr_item['summary']}")
        parts.append(f"  Activity type: {curr_item['activity_type']}")
        if curr_item["unit_name"]:
            parts.append(f"  Unit: {curr_item['unit_name']}")

    # Next day's plan
    next_date = datetime.strptime(date_str, "%Y-%m-%d") + timedelta(days=1)
    while next_date.weekday() >= 5:
        next_date += timedelta(days=1)
    next_item = db.get_curriculum_item_by_date(class_id, next_date.strftime("%Y-%m-%d"))
    if next_item:
        parts.append(f"Next lesson ({next_date.strftime('%m/%d')}): {next_item['summary']}")

    return "\n".join(parts) if parts else "No surrounding lesson context available."


def _build_music_library_context(db: Database, limit: int = 20) -> str:
    """Build context from the teacher's sheet music library."""
    try:
        pieces = db.get_all_sheet_music()
        if not pieces:
            return ""
        lines = ["Sheet Music Library:"]
        for piece in pieces[:limit]:
            diff = f" (Difficulty: {piece['difficulty']})" if piece.get("difficulty") else ""
            lines.append(f"  - {piece['title']} by {piece.get('composer', 'Unknown')}{diff}")
        return "\n".join(lines)
    except Exception:
        return ""


def _build_reflection_history(db: Database, class_id: int, limit: int = 10) -> str:
    """Build context from recent lesson plan reflections."""
    items = db.get_curriculum_items(class_id)
    reflections = []
    for item in items:
        plan = db.get_lesson_plan_by_curriculum_item(item["id"])
        if plan and plan.get("reflection_text"):
            reflections.append({
                "date": item["item_date"],
                "topic": item["summary"],
                "reflection": plan["reflection_text"],
                "rating": plan.get("reflection_rating", ""),
            })
    if not reflections:
        return ""

    lines = ["Recent Reflections:"]
    for r in reflections[-limit:]:
        rating = f" [{r['rating']}]" if r["rating"] else ""
        lines.append(f"  {r['date']} ({r['topic']}): {r['reflection']}{rating}")
    return "\n".join(lines)


# ─── Curriculum Generation ────────────────────────────────────────────────────

def generate_curriculum(
    base_dir: str,
    db: Database,
    class_id: int,
    start_date: str,
    end_date: str,
    days_of_week: str = "M,T,W,Th,F",
    approach: str = "from_scratch",
    additional_instructions: str = "",
    reference_paths: list = None,
    on_retry=None,
    on_status=None,
) -> dict:
    """
    Generate a year-long curriculum for a class using LLM.

    Args:
        base_dir: App base directory (for LLM settings)
        db: Database instance
        class_id: Teaching class ID
        start_date: First day of instruction (YYYY-MM-DD)
        end_date: Last day of instruction (YYYY-MM-DD)
        days_of_week: Which days the class meets
        approach: "from_scratch", "from_previous", "hybrid", "template"
        additional_instructions: Teacher's custom instructions
        reference_paths: List of file/folder paths to use as context
        on_retry: LLM retry callback
        on_status: Status update callback(message_str)

    Returns:
        {"items": list[dict], "error": str or None}
    """
    from llm_client import query

    if on_status:
        on_status("Gathering class context...")

    class_context = _build_class_context(db, class_id)
    existing_context = ""
    if approach in ("from_previous", "hybrid"):
        existing_context = _build_curriculum_context(db, class_id, limit=100)

    music_context = _build_music_library_context(db)
    reflection_context = _build_reflection_history(db, class_id)

    # Count available school days
    day_map = {"m": 0, "t": 1, "w": 2, "th": 3, "f": 4, "sa": 5, "su": 6}
    active_days = set()
    for d in days_of_week.split(","):
        d_lower = d.strip().lower()
        if d_lower in day_map:
            active_days.add(day_map[d_lower])

    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")
    school_days = 0
    current = start
    while current <= end:
        if current.weekday() in active_days:
            school_days += 1
        current += timedelta(days=1)

    if on_status:
        on_status(f"Generating curriculum for {school_days} school days...")

    prompt_parts = [
        f"Generate a complete curriculum for this class:\n\n{class_context}",
        f"\nDate range: {start_date} to {end_date}",
        f"School days available: {school_days}",
        f"Class meets on: {days_of_week}",
    ]

    if approach == "from_previous" and existing_context:
        prompt_parts.append(
            f"\nBase this curriculum on the teacher's previous plans, "
            f"improving where their reflections indicated issues:\n{existing_context}"
        )
        if reflection_context:
            prompt_parts.append(f"\n{reflection_context}")
    elif approach == "hybrid" and existing_context:
        prompt_parts.append(
            f"\nThe teacher has a partial plan. Fill in gaps and improve:\n{existing_context}"
        )

    if music_context:
        prompt_parts.append(f"\n{music_context}")

    # Add file/folder reference materials
    if reference_paths:
        if on_status:
            on_status("Reading reference materials...")
        file_context = build_file_context(reference_paths)
        if file_context:
            prompt_parts.append(f"\n{file_context}")

    if additional_instructions:
        prompt_parts.append(f"\nTeacher's additional instructions: {additional_instructions}")

    prompt_parts.append(
        "\n\nGenerate the curriculum as a JSON array. Each item must have:"
        '\n  - "item_date": date in YYYY-MM-DD format (only on school days)'
        '\n  - "summary": 1-2 sentence description of the day\'s focus'
        '\n  - "activity_type": one of [skill_building, concert_prep, concert, '
        "assessment, sight_reading, theory, composition, listening, flex, no_class]"
        '\n  - "unit_name": the unit/chapter this belongs to'
        '\n  - "notes": any specific details, method book pages, or materials'
        "\n\nReturn ONLY the JSON array. No markdown, no explanation."
        f"\nGenerate exactly {school_days} items, one per school day."
    )

    user_prompt = "\n".join(prompt_parts)

    try:
        response = query(
            base_dir, user_prompt,
            system_prompt=_CURRICULUM_SYSTEM,
            on_retry=on_retry,
        )

        # Parse the LLM response
        from lesson_plan_importer import import_curriculum_from_llm_response
        result = import_curriculum_from_llm_response(
            db, response, class_id,
            start_date=start_date,
            days_of_week=days_of_week,
            preview_only=True,
        )
        return {"items": result.get("preview", []), "error": None}

    except Exception as e:
        return {"items": [], "error": str(e)}


# ─── Lesson Plan Generation ──────────────────────────────────────────────────

def generate_lesson_plan(
    base_dir: str,
    db: Database,
    class_id: int,
    date_str: str,
    mode: str = "generate",
    teacher_feedback: str = "",
    reference_paths: list = None,
    on_retry=None,
) -> dict:
    """
    Generate or refine a lesson plan for a specific day.

    Args:
        base_dir: App base directory
        db: Database instance
        class_id: Teaching class ID
        date_str: Date string (YYYY-MM-DD)
        mode: "generate" (new plan), "regenerate" (fresh alternative),
              "adjust" (modify based on feedback), "ideas" (suggest activities)
        teacher_feedback: Teacher's instructions for adjustment
        on_retry: LLM retry callback

    Returns:
        dict with lesson plan data or {"error": str}
    """
    from llm_client import query_with_search

    class_context = _build_class_context(db, class_id)
    lesson_context = _build_lesson_plan_context(db, class_id, date_str)

    # Get existing plan if any
    existing_plan_text = ""
    item = db.get_curriculum_item_by_date(class_id, date_str)
    if item:
        plan = db.get_lesson_plan_by_curriculum_item(item["id"])
        if plan:
            blocks = db.get_lesson_blocks(plan["id"])
            existing_plan_text = _format_existing_plan(plan, blocks)

    cls = db.get_class(class_id)
    duration = cls["class_duration"] if cls else 45

    if mode == "generate":
        user_prompt = (
            f"Create a detailed lesson plan for this class:\n\n{class_context}"
            f"\n\nDate: {date_str}\n{lesson_context}"
            f"\n\nThe class period is {duration} minutes."
        )
    elif mode == "regenerate":
        user_prompt = (
            f"Create a COMPLETELY DIFFERENT lesson plan for this class. "
            f"Do NOT reuse the same approach as the existing plan.\n\n"
            f"{class_context}\n\nDate: {date_str}\n{lesson_context}"
            f"\n\nExisting plan to avoid repeating:\n{existing_plan_text}"
            f"\n\nThe class period is {duration} minutes."
        )
    elif mode == "adjust":
        user_prompt = (
            f"Modify this lesson plan based on the teacher's feedback:\n\n"
            f"{class_context}\n\nDate: {date_str}\n{lesson_context}"
            f"\n\nCurrent plan:\n{existing_plan_text}"
            f"\n\nTeacher feedback: {teacher_feedback}"
            f"\n\nThe class period is {duration} minutes."
        )
    elif mode == "ideas":
        user_prompt = (
            f"Suggest creative teaching ideas and activities for this lesson:\n\n"
            f"{class_context}\n\nDate: {date_str}\n{lesson_context}"
            f"\n\nTeacher request: {teacher_feedback or 'Give me engaging alternatives'}"
            f"\n\nProvide 3-5 specific, actionable ideas with time estimates."
        )
    else:
        return {"error": f"Unknown mode: {mode}"}

    # Append file/folder reference materials
    if reference_paths:
        file_context = build_file_context(reference_paths)
        if file_context:
            user_prompt += f"\n\n{file_context}"

    output_format = (
        "\n\nReturn a JSON object with these fields:"
        '\n  "objectives": learning objectives for the day'
        '\n  "standards": applicable standards (National Core Arts or WA State)'
        '\n  "warmup_text": detailed warm-up activity (5-10 min)'
        '\n  "blocks": array of activity blocks, each with:'
        '\n    "block_type": rehearsal/sectional/sight_reading/theory/listening/composition/custom'
        '\n    "title": activity title'
        '\n    "description": detailed description'
        '\n    "duration_minutes": integer'
        '\n    "technique_focus": if applicable'
        '\n    "notes": any additional notes'
        '\n  "assessment_type": None/Exit ticket/Playing test/Observation rubric/etc.'
        '\n  "assessment_details": details of assessment'
        '\n  "differentiation_advanced": accommodations for advanced students'
        '\n  "differentiation_struggling": accommodations for struggling students'
        '\n  "notes": any additional notes'
        "\n\nReturn ONLY the JSON object. No markdown, no explanation."
    )

    if mode != "ideas":
        user_prompt += output_format

    try:
        response = query_with_search(
            base_dir, user_prompt,
            system_prompt=_LESSON_PLAN_SYSTEM,
            on_retry=on_retry,
        )

        if mode == "ideas":
            # Ideas mode returns plain text, not JSON
            return {"ideas_text": response, "error": None}

        # Parse JSON response
        cleaned = response.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            cleaned = "\n".join(lines)

        plan_data = json.loads(cleaned)
        return {"plan": plan_data, "error": None}

    except json.JSONDecodeError as e:
        return {"error": f"Failed to parse AI response as JSON: {e}", "raw": response}
    except Exception as e:
        return {"error": str(e)}


def _format_existing_plan(plan, blocks) -> str:
    """Format an existing lesson plan as text for LLM context."""
    parts = []
    if plan.get("objectives"):
        parts.append(f"Objectives: {plan['objectives']}")
    if plan.get("warmup_text"):
        parts.append(f"Warm-up: {plan['warmup_text']}")
    for block in blocks:
        parts.append(
            f"Activity ({block['block_type']}, {block['duration_minutes']} min): "
            f"{block['title']} - {block.get('description', '')}"
        )
    if plan.get("assessment_type"):
        parts.append(f"Assessment: {plan['assessment_type']}")
    if plan.get("reflection_text"):
        parts.append(f"Reflection: {plan['reflection_text']}")
    return "\n".join(parts) if parts else "No existing plan."


# ─── Curriculum Alignment Check ───────────────────────────────────────────────

def check_curriculum_alignment(
    base_dir: str,
    db: Database,
    class_id: int,
    on_retry=None,
) -> dict:
    """
    Check a curriculum against Washington State / National Core Arts Standards.

    Returns:
        {"report": str, "gaps": list[str], "error": str or None}
    """
    from llm_client import query

    class_context = _build_class_context(db, class_id)
    curriculum_context = _build_curriculum_context(db, class_id, limit=200)

    user_prompt = (
        f"Audit this curriculum against the Washington State K-12 Arts Learning Standards "
        f"(aligned with National Core Arts Standards) for the appropriate grade level.\n\n"
        f"{class_context}\n\n{curriculum_context}"
        f"\n\nFor each of the four artistic processes (Creating, Performing, Responding, "
        f"Connecting), identify:"
        f"\n1. Which standards ARE addressed by the curriculum"
        f"\n2. Which standards are MISSING or underrepresented"
        f"\n3. Specific suggestions to address any gaps"
        f"\n\nReturn a JSON object with:"
        f'\n  "summary": brief overall assessment (2-3 sentences)'
        f'\n  "coverage_pct": estimated percentage of standards covered (0-100)'
        f'\n  "strengths": array of strings describing what the curriculum does well'
        f'\n  "gaps": array of strings describing missing standards or areas'
        f'\n  "suggestions": array of specific actionable suggestions'
        f"\n\nReturn ONLY the JSON object."
    )

    try:
        response = query(
            base_dir, user_prompt,
            system_prompt=_CURRICULUM_SYSTEM,
            on_retry=on_retry,
        )

        cleaned = response.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            cleaned = "\n".join(lines)

        report = json.loads(cleaned)
        return {"report": report, "error": None}

    except Exception as e:
        return {"report": None, "error": str(e)}


# ─── Practice Assignment Generator ───────────────────────────────────────────

def generate_practice_assignment(
    base_dir: str,
    db: Database,
    class_id: int,
    date_str: str,
    on_retry=None,
) -> dict:
    """
    Generate a student-facing practice assignment based on the day's lesson.

    Returns:
        {"assignment_text": str, "error": str or None}
    """
    from llm_client import query_haiku

    class_context = _build_class_context(db, class_id)
    lesson_context = _build_lesson_plan_context(db, class_id, date_str)

    user_prompt = (
        f"Create a student-facing practice assignment based on today's lesson.\n\n"
        f"{class_context}\n\n{lesson_context}"
        f"\n\nThe assignment should:"
        f"\n- Be written in student-friendly language (middle school level)"
        f"\n- Include specific measures, pages, or exercises to practice"
        f"\n- Have a clear practice goal (e.g., 'Be able to play mm. 12-24 at 80 bpm')"
        f"\n- Suggest a practice duration (10-20 minutes)"
        f"\n- Include a self-assessment checklist"
        f"\n\nFormat as plain text that could be printed or shared digitally."
    )

    try:
        response = query_haiku(
            base_dir, user_prompt,
            system_prompt=_LESSON_PLAN_SYSTEM,
            on_retry=on_retry,
        )
        return {"assignment_text": response, "error": None}
    except Exception as e:
        return {"assignment_text": "", "error": str(e)}


# ─── Substitute Teacher Plan Generator ────────────────────────────────────────

def generate_sub_plan(
    base_dir: str,
    db: Database,
    class_id: int,
    date_str: str,
    on_retry=None,
) -> dict:
    """
    Generate a simplified lesson plan formatted for a substitute teacher.

    Returns:
        {"sub_plan_text": str, "error": str or None}
    """
    from llm_client import query_haiku

    class_context = _build_class_context(db, class_id)
    lesson_context = _build_lesson_plan_context(db, class_id, date_str)

    user_prompt = (
        f"Create a substitute teacher lesson plan for a music class. "
        f"The substitute may NOT be a musician.\n\n"
        f"{class_context}\n\n{lesson_context}"
        f"\n\nThe sub plan must:"
        f"\n- Be extremely simple and step-by-step"
        f"\n- Include basic classroom procedures (where instruments are, rules)"
        f"\n- Have a 'just press play' backup activity (listening to a recording)"
        f"\n- List student leaders who can help"
        f"\n- Include emergency contact info placeholder"
        f"\n- Be printable on one page"
        f"\n\nFormat as a clean, well-organized document with clear headings."
    )

    try:
        response = query_haiku(
            base_dir, user_prompt,
            system_prompt=_LESSON_PLAN_SYSTEM,
            on_retry=on_retry,
        )
        return {"sub_plan_text": response, "error": None}
    except Exception as e:
        return {"sub_plan_text": "", "error": str(e)}
