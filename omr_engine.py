"""
omr_engine.py - OMR processing and MusicXML validation for Roka's Resonance

Supports two OMR engines:
  - Audiveris (primary, best accuracy, requires separate install)
  - homr (fallback, pure Python via pip)

Uses music21 for post-OMR MusicXML validation.
"""

import os
import shutil
import subprocess
import json
from datetime import datetime


# ── Managed file storage ──────────────────────────────────────────────────────

def get_music_dir(base_dir: str) -> str:
    """Return (and create if needed) the managed sheet_music folder."""
    d = os.path.join(base_dir, "sheet_music")
    os.makedirs(d, exist_ok=True)
    return d


def get_piece_dir(base_dir: str, music_id: int) -> str:
    """Return (and create if needed) a per-piece subfolder."""
    d = os.path.join(get_music_dir(base_dir), str(music_id))
    os.makedirs(d, exist_ok=True)
    return d


def import_file(base_dir: str, music_id: int, source_path: str) -> str:
    """Copy a source file into the managed sheet_music/<id>/ folder."""
    dest_dir = get_piece_dir(base_dir, music_id)
    filename = os.path.basename(source_path)
    dest = os.path.join(dest_dir, filename)
    if os.path.abspath(source_path) != os.path.abspath(dest):
        shutil.copy2(source_path, dest)
    return dest


# ── Engine detection ──────────────────────────────────────────────────────────

def detect_audiveris() -> str | None:
    """Return the Audiveris CLI command if available, else None."""
    # Check common install locations on Windows
    common_paths = [
        r"C:\Program Files\Audiveris\bin\Audiveris.bat",
        r"C:\Program Files (x86)\Audiveris\bin\Audiveris.bat",
        r"C:\Program Files\Audiveris\bin\Audiveris",
    ]
    for p in common_paths:
        if os.path.exists(p):
            return p

    # Check environment variable
    env_path = os.environ.get("AUDIVERIS_PATH")
    if env_path and os.path.exists(env_path):
        return env_path

    # Try PATH
    try:
        result = subprocess.run(
            ["audiveris", "-help"],
            capture_output=True, timeout=10
        )
        return "audiveris"
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    return None


def detect_homr() -> bool:
    """Check if the homr package is installed."""
    try:
        import homr  # noqa: F401
        return True
    except ImportError:
        return False


def get_available_engines() -> list[str]:
    """Return list of available OMR engine names."""
    engines = []
    if detect_audiveris():
        engines.append("audiveris")
    if detect_homr():
        engines.append("homr")
    return engines


# ── Audiveris processing ─────────────────────────────────────────────────────

def run_audiveris(input_path: str, output_dir: str,
                  progress_callback=None) -> str:
    """
    Run Audiveris CLI on input_path, output MusicXML to output_dir.
    Returns path to the generated .mxl file.
    """
    cmd_path = detect_audiveris()
    if not cmd_path:
        raise RuntimeError("Audiveris is not installed or not found in PATH.")

    if progress_callback:
        progress_callback("Starting Audiveris OMR processing...")
        progress_callback(f"  Input: {os.path.basename(input_path)}")

    # Audiveris CLI: -batch -export -output <dir> <input>
    cmd = [cmd_path, "-batch", "-export", "-output", output_dir, input_path]

    proc = subprocess.run(
        cmd, capture_output=True, text=True, timeout=600  # 10 min max
    )

    if progress_callback:
        progress_callback(f"Audiveris exit code: {proc.returncode}")
        if proc.stdout:
            for line in proc.stdout.strip().split('\n')[-5:]:
                progress_callback(f"  {line}")
        if proc.stderr:
            for line in proc.stderr.strip().split('\n')[-3:]:
                progress_callback(f"  [stderr] {line}")

    if proc.returncode != 0:
        error_msg = proc.stderr.strip() if proc.stderr else "Unknown error"
        raise RuntimeError(f"Audiveris failed (exit {proc.returncode}): {error_msg}")

    # Find the output .mxl file
    base_name = os.path.splitext(os.path.basename(input_path))[0]
    for ext in (".mxl", ".musicxml", ".xml"):
        candidate = os.path.join(output_dir, base_name + ext)
        if os.path.exists(candidate):
            return candidate

    # Search output_dir for any MusicXML file
    for f in os.listdir(output_dir):
        if f.endswith((".mxl", ".musicxml", ".xml")):
            return os.path.join(output_dir, f)

    raise RuntimeError("Audiveris completed but no MusicXML output found.")


# ── PDF to image conversion (for homr) ───────────────────────────────────────

def _pdf_to_images(pdf_path: str, output_dir: str,
                   progress_callback=None) -> list[str]:
    """
    Convert a PDF to a series of PNG images (one per page).
    Uses pypdf + PIL to render pages. Returns list of image paths.
    """
    if progress_callback:
        progress_callback("Rendering PDF pages to images...")

    image_paths = []

    # pymupdf renders full pages (vector + raster) at high quality
    try:
        import fitz  # pymupdf

        doc = fitz.open(pdf_path)
        for i, page in enumerate(doc):
            # Render at 300 DPI (default is 72; scale factor = 300/72 ≈ 4.17)
            mat = fitz.Matrix(4, 4)
            pix = page.get_pixmap(matrix=mat)
            img_path = os.path.join(output_dir, f"page_{i+1}.png")
            pix.save(img_path)
            image_paths.append(img_path)
            if progress_callback:
                progress_callback(f"  Rendered page {i+1}")
        doc.close()
        return image_paths
    except ImportError:
        pass

    # Fallback: pdf2image + Poppler
    try:
        from pdf2image import convert_from_path
        pages = convert_from_path(pdf_path, dpi=300)
        for i, page_img in enumerate(pages):
            img_path = os.path.join(output_dir, f"page_{i+1}.png")
            page_img.save(img_path, "PNG")
            image_paths.append(img_path)
            if progress_callback:
                progress_callback(f"  Rendered page {i+1}")
        return image_paths
    except ImportError:
        pass

    raise RuntimeError(
        "No PDF rendering library found.\n"
        "Install one of: pip install pymupdf\n"
        "            or: pip install pdf2image (+ Poppler)"
    )


# ── HOMR processing (fallback) ───────────────────────────────────────────────

def run_homr(input_path: str, output_dir: str,
             progress_callback=None,
             progress_percent_callback=None) -> str:
    """
    Run homr OMR on input_path (image or PDF).
    homr works on images, so PDFs are converted to images first.
    Returns path to the generated MusicXML file.

    progress_percent_callback(current_page, total_pages) is called after
    each page so the UI can update a determinate progress bar.
    """
    if progress_callback:
        progress_callback("Starting homr OMR processing...")
        progress_callback(f"  Input: {os.path.basename(input_path)}")

    ext = os.path.splitext(input_path)[1].lower()
    is_pdf = ext == ".pdf"

    # For PDFs, convert to images first
    if is_pdf:
        image_dir = os.path.join(output_dir, "_pages")
        os.makedirs(image_dir, exist_ok=True)
        image_paths = _pdf_to_images(input_path, image_dir, progress_callback)
        if not image_paths:
            raise RuntimeError("No images could be extracted from the PDF.")
        pages_to_process = image_paths
    else:
        # Copy image to output dir so homr writes output there
        work_path = os.path.join(output_dir, os.path.basename(input_path))
        if os.path.abspath(input_path) != os.path.abspath(work_path):
            shutil.copy2(input_path, work_path)
        pages_to_process = [work_path]

    total_pages = len(pages_to_process)
    if progress_callback:
        progress_callback(f"  Processing {total_pages} page(s)...")

    # Prepare subprocess environment and launcher script
    import sys
    env = os.environ.copy()
    try:
        import certifi
        env["SSL_CERT_FILE"] = certifi.where()
        env["REQUESTS_CA_BUNDLE"] = certifi.where()
    except ImportError:
        pass

    # Write launcher script (patches SSL + numpy 2.x autocrop bug)
    launcher = os.path.join(output_dir, "_run_homr.py")
    with open(launcher, "w") as f:
        f.write(
            "import ssl, sys\n"
            "try:\n"
            "    import certifi\n"
            "    ssl._create_default_https_context = "
            "lambda: ssl.create_default_context(cafile=certifi.where())\n"
            "except ImportError:\n"
            "    pass\n"
            "\n"
            "# Patch homr.autocrop for numpy 2.x compatibility\n"
            "import homr.autocrop as _ac\n"
            "import cv2 as _cv2\n"
            "import numpy as _np\n"
            "def _patched_autocrop(img):\n"
            "    gray = _cv2.cvtColor(img, _cv2.COLOR_BGR2GRAY)\n"
            "    hist = _cv2.calcHist([img], [0], None, [256], [0, 256])\n"
            "    dominant = max(enumerate(hist), key=lambda x: x[1].item())[0]\n"
            "    thresh = _cv2.threshold(gray, dominant - 30, 255, _cv2.THRESH_BINARY)[1]\n"
            "    kernel = _np.ones((7, 7), _np.uint8)\n"
            "    morph = _cv2.morphologyEx(thresh, _cv2.MORPH_CLOSE, kernel)\n"
            "    kernel = _np.ones((9, 9), _np.uint8)\n"
            "    morph = _cv2.morphologyEx(morph, _cv2.MORPH_ERODE, kernel)\n"
            "    contours = _cv2.findContours(morph, _cv2.RETR_EXTERNAL, _cv2.CHAIN_APPROX_SIMPLE)\n"
            "    contours = contours[0] if len(contours) == 2 else contours[1]\n"
            "    area_thresh = 0.0\n"
            "    big_contour = None\n"
            "    for c in contours:\n"
            "        area = _cv2.contourArea(c)\n"
            "        if area > area_thresh:\n"
            "            area_thresh = area\n"
            "            big_contour = c\n"
            "    if big_contour is None:\n"
            "        return img\n"
            "    x, y, w, h = _cv2.boundingRect(big_contour)\n"
            "    pw, ph = img.shape[1], img.shape[0]\n"
            "    if x < pw * 0.25 or y < ph * 0.25:\n"
            "        return img\n"
            "    return img[y:y+h, x:x+w]\n"
            "_ac.autocrop = _patched_autocrop\n"
            "\n"
            "# Patch homr.tr_omr_parser to handle multirest tokens\n"
            "# (homr skips them by default, losing multi-measure rests)\n"
            "from homr.tr_omr_parser import TrOMRParser as _TrOMR\n"
            "from homr.results import (\n"
            "    ResultMeasure as _RM, ResultChord as _RC,\n"
            "    ResultDuration as _RD, ResultClef as _RClef, ResultStaff as _RS,\n"
            ")\n"
            "from homr import constants as _const\n"
            "from homr.simple_logging import eprint as _eprint\n"
            "\n"
            "def _patched_parse(self, output):\n"
            "    measures = []\n"
            "    current_measure = _RM([])\n"
            "    parse_functions = {\n"
            "        'clef': self.parse_clef,\n"
            "        'timeSignature': self.parse_time_signature,\n"
            "    }\n"
            "    for chord in output:\n"
            "        part = str(chord)\n"
            "        if part == 'barline':\n"
            "            measures.append(current_measure)\n"
            "            current_measure = _RM([])\n"
            "        elif part.startswith('keySignature'):\n"
            "            if len(current_measure.symbols) > 0 and isinstance(\n"
            "                current_measure.symbols[-1], _RClef\n"
            "            ):\n"
            "                self.parse_key_signature(part, current_measure.symbols[-1])\n"
            "        elif part.startswith('multirest'):\n"
            "            if len(current_measure.symbols) > 0:\n"
            "                measures.append(current_measure)\n"
            "                current_measure = _RM([])\n"
            "            try:\n"
            "                n = int(part.split('-')[1])\n"
            "            except (IndexError, ValueError):\n"
            "                n = 1\n"
            "            whole_dur = _RD(_const.duration_of_quarter * 4)\n"
            "            for _ in range(n):\n"
            "                measures.append(_RM([_RC(whole_dur, [])]))\n"
            "            current_measure = _RM([])\n"
            "            _eprint(f'Expanded multirest-{n} into {n} whole-rest measures')\n"
            "        elif part.startswith(('note', 'rest')) or '|' in part:\n"
            "            note_result = self.parse_notes(chord)\n"
            "            if note_result is not None:\n"
            "                current_measure.symbols.append(note_result)\n"
            "        else:\n"
            "            for prefix, parse_function in parse_functions.items():\n"
            "                if part.startswith(prefix):\n"
            "                    current_measure.symbols.append(parse_function(part))\n"
            "                    break\n"
            "    if len(current_measure.symbols) > 0:\n"
            "        measures.append(current_measure)\n"
            "    return _RS(measures)\n"
            "\n"
            "_TrOMR.parse_tr_omr_output = _patched_parse\n"
            "\n"
            "from homr.main import main\n"
            "sys.argv = ['homr'] + sys.argv[1:]\n"
            "main()\n"
        )

    # Process each page individually for progress tracking
    failed_pages = []
    for page_idx, page_path in enumerate(pages_to_process):
        page_num = page_idx + 1
        pct = int(page_num / total_pages * 100)

        if progress_callback:
            progress_callback(f"  Page {page_num}/{total_pages} ({pct}%): "
                              f"{os.path.basename(page_path)}")
        if progress_percent_callback:
            progress_percent_callback(page_num, total_pages)

        try:
            homr_cmd = [sys.executable, launcher, page_path]
            proc = subprocess.run(
                homr_cmd, capture_output=True, text=True, timeout=600,
                cwd=output_dir, env=env
            )

            if proc.returncode != 0:
                stderr = proc.stderr.strip() if proc.stderr else ""
                if "SSL" in stderr or "certificate" in stderr:
                    raise RuntimeError(
                        "homr needs to download models on first use but SSL "
                        "verification failed.\nTry: pip install certifi"
                    )
                failed_pages.append(page_num)
                if progress_callback:
                    # Show last few lines of error
                    err_lines = stderr.split('\n')[-3:]
                    for line in err_lines:
                        progress_callback(f"    Error: {line}")
            else:
                if progress_callback:
                    progress_callback(f"    Page {page_num} complete")

        except subprocess.TimeoutExpired:
            failed_pages.append(page_num)
            if progress_callback:
                progress_callback(f"    Page {page_num} timed out")
        except FileNotFoundError:
            raise RuntimeError(
                "homr is not installed.\n"
                "Install with: pip install homr"
            )

    if progress_callback:
        ok = total_pages - len(failed_pages)
        progress_callback(f"  homr finished: {ok}/{total_pages} pages succeeded")
        if failed_pages:
            progress_callback(f"  Failed pages: {failed_pages}")

    # Collect all generated MusicXML files
    musicxml_files = []
    for root, dirs, files in os.walk(output_dir):
        for f in sorted(files):
            if f.endswith((".musicxml", ".mxl")):
                musicxml_files.append(os.path.join(root, f))

    if not musicxml_files:
        for root, dirs, files in os.walk(output_dir):
            for f in sorted(files):
                if f.endswith(".xml"):
                    musicxml_files.append(os.path.join(root, f))

    if musicxml_files:
        final_name = os.path.splitext(os.path.basename(input_path))[0] + ".musicxml"
        final_path = os.path.join(output_dir, final_name)
        if os.path.abspath(musicxml_files[0]) != os.path.abspath(final_path):
            shutil.move(musicxml_files[0], final_path)
        else:
            final_path = musicxml_files[0]
        if progress_callback:
            progress_callback("homr processing complete.")
        return final_path

    raise RuntimeError("homr completed but no MusicXML output found.")


# ── MusicXML Validation (music21) ─────────────────────────────────────────────

# Typical pitch ranges for middle school band instruments.
# Uses WRITTEN pitch (as notated on the staff) because OMR outputs written
# pitch — it doesn't know the transposition.
INSTRUMENT_RANGES = {
    # Non-transposing (concert = written)
    "flute":        ("C4", "C7"),
    "oboe":         ("Bb3", "A6"),
    "bassoon":      ("Bb1", "E5"),
    "trombone":     ("E2", "F5"),
    "baritone":     ("E2", "Bb4"),
    "euphonium":    ("E2", "Bb4"),
    "tuba":         ("D1", "Bb4"),
    # Bb transposing (written = concert + M2)
    "clarinet":     ("E3", "C7"),
    "bass clarinet": ("E2", "A5"),
    "trumpet":      ("F#3", "D6"),
    "cornet":       ("F#3", "D6"),
    "tenor sax":    ("Bb2", "F#6"),
    # Eb transposing (written = concert + M6)
    "alto sax":     ("Bb3", "F#6"),
    "bari sax":     ("Bb2", "F#5"),
    "baritone sax": ("Bb2", "F#5"),
    "soprano sax":  ("Bb3", "F#6"),
    # F transposing (written = concert + P5)
    "french horn":  ("F#3", "C6"),
    "horn":         ("F#3", "C6"),
    # Piccolo (sounds 8va)
    "piccolo":      ("D4", "C7"),
}

# Band instruments that can only play one note at a time.
# Used by postprocess_musicxml() to remove false chords from OMR output.
MONOPHONIC_INSTRUMENTS = {
    "flute", "piccolo", "oboe", "clarinet", "bass clarinet", "bassoon",
    "trumpet", "cornet", "french horn", "horn", "trombone",
    "baritone", "euphonium", "tuba",
    "alto sax", "tenor sax", "bari sax", "baritone sax", "soprano sax",
}


# ── MusicXML Post-Processing Corrections ─────────────────────────────────────

def _fix_monophonic_chords(part, part_name, music21_mod):
    """Remove chords on monophonic instruments, keeping the highest pitch."""
    corrections = []
    name_lower = (part_name or "").lower()

    is_monophonic = any(k in name_lower for k in MONOPHONIC_INSTRUMENTS)
    if not is_monophonic:
        return corrections

    for measure in part.getElementsByClass('Measure'):
        for element in list(measure.notesAndRests):
            if isinstance(element, music21_mod.chord.Chord):
                top_pitch = sorted(element.pitches, key=lambda p: p.midi)[-1]
                new_note = music21_mod.note.Note(
                    top_pitch, quarterLength=element.quarterLength
                )
                if element.tie:
                    new_note.tie = element.tie
                measure.replace(element, new_note)
                pitches_str = ", ".join(
                    p.nameWithOctave for p in element.pitches
                )
                corrections.append({
                    "type": "correction",
                    "measure": measure.number,
                    "part": part_name,
                    "message": f"Removed chord [{pitches_str}] on monophonic "
                               f"instrument, kept {top_pitch.nameWithOctave}"
                })

    return corrections


def _fix_short_measures(part, part_name, music21_mod):
    """Upgrade tiny rests and pad short measures with rests."""
    corrections = []

    for measure in part.getElementsByClass('Measure'):
        ts = measure.getContextByClass('TimeSignature')
        if not ts:
            continue
        expected = ts.barDuration.quarterLength
        actual = measure.duration.quarterLength
        gap = expected - actual

        if gap <= 0.001 or gap > 2.0:
            continue

        # Fix 3: upgrade leading 16th rest if measure is short
        notes_rests = list(measure.notesAndRests)
        if notes_rests and notes_rests[0].isRest:
            first_rest = notes_rests[0]
            if abs(first_rest.quarterLength - 0.25) < 0.001:  # 16th rest
                if abs(gap - 0.25) < 0.001:
                    first_rest.quarterLength = 0.5
                    corrections.append({
                        "type": "correction",
                        "measure": measure.number,
                        "part": part_name,
                        "message": "Upgraded 16th rest to eighth rest "
                                   "(measure was 0.25 beats short)"
                    })
                    continue  # Gap fully resolved
                elif gap >= 0.25:
                    first_rest.quarterLength = 0.5
                    gap -= 0.25
                    corrections.append({
                        "type": "correction",
                        "measure": measure.number,
                        "part": part_name,
                        "message": "Upgraded 16th rest to eighth rest "
                                   "(partial fix)"
                    })

        # Fix 1: pad remaining gap with rest at end
        actual = sum(el.quarterLength for el in measure.notesAndRests)
        gap = expected - actual
        if gap > 0.001 and gap <= 2.0:
            pad_rest = music21_mod.note.Rest(quarterLength=gap)
            measure.append(pad_rest)
            corrections.append({
                "type": "correction",
                "measure": measure.number,
                "part": part_name,
                "message": f"Padded short measure with {gap}-beat rest "
                           f"(was {actual}/{expected} beats)"
            })

    return corrections


# ── Instrument Detection ──────────────────────────────────────────────────────

# Common abbreviations → canonical names (matches MONOPHONIC_INSTRUMENTS keys)
INSTRUMENT_ALIASES = {
    "a. sax": "alto sax", "alto saxophone": "alto sax",
    "t. sax": "tenor sax", "tenor saxophone": "tenor sax",
    "b. sax": "bari sax", "bari saxophone": "bari sax",
    "baritone saxophone": "baritone sax",
    "soprano saxophone": "soprano sax", "s. sax": "soprano sax",
    "trpt": "trumpet", "tpt": "trumpet",
    "tbn": "trombone", "trb": "trombone",
    "cl": "clarinet", "b. cl": "bass clarinet",
    "fl": "flute", "picc": "piccolo",
    "fhn": "french horn", "hn": "horn",
    "euph": "euphonium", "bar": "baritone",
}

# All known instrument names (for matching)
_ALL_KNOWN_INSTRUMENTS = (
    set(MONOPHONIC_INSTRUMENTS) | set(INSTRUMENT_RANGES.keys())
    | {"piano", "percussion", "drums", "mallet", "xylophone", "bells",
       "marimba", "vibraphone", "timpani", "snare", "bass drum"}
)


def _detect_instrument_from_title(title):
    """Extract instrument name from a title like 'Piece - Alto Sax 1'."""
    if not title:
        return None
    # Try splitting on common delimiters
    for delim in [" - ", " -- ", " _ "]:
        if delim in title:
            candidate = title.split(delim)[-1].strip()
            # Remove trailing part numbers (e.g., "1", "2", "I", "II")
            candidate_base = candidate.rstrip("0123456789IViv ").strip()
            candidate_lower = candidate_base.lower()
            # Check exact match against known instruments
            if candidate_lower in _ALL_KNOWN_INSTRUMENTS:
                return candidate
            # Check aliases
            if candidate_lower in INSTRUMENT_ALIASES:
                return candidate
            # Partial match
            for key in _ALL_KNOWN_INSTRUMENTS:
                if key in candidate_lower:
                    return candidate
    return None


def _detect_instrument_from_image(page_images_dir):
    """OCR the left margin of page 1 to find the instrument name."""
    if not page_images_dir or not os.path.isdir(page_images_dir):
        return None
    page1 = os.path.join(page_images_dir, "page_1.png")
    if not os.path.exists(page1):
        return None
    try:
        # Patch SSL for easyocr model download (same issue as homr)
        import ssl
        try:
            import certifi
            ssl._create_default_https_context = (
                lambda: ssl.create_default_context(cafile=certifi.where())
            )
        except ImportError:
            pass
        import easyocr
        import cv2
        reader = easyocr.Reader(["en"], gpu=False, verbose=False)
        img = cv2.imread(page1)
        if img is None:
            return None
        h, w = img.shape[:2]
        # Crop left ~18% width, top ~35% height (instrument label area)
        left_margin = img[0:int(h * 0.35), 0:int(w * 0.18)]
        results = reader.readtext(left_margin, detail=0, paragraph=True)
        if not results:
            return None
        # Check each detected text against known instruments
        for text in results:
            text_clean = text.strip()
            text_lower = text_clean.lower()
            for key in _ALL_KNOWN_INSTRUMENTS:
                if key in text_lower:
                    return text_clean
            for alias in INSTRUMENT_ALIASES:
                if alias in text_lower:
                    return text_clean
        return None
    except Exception:
        return None


def _detect_instrument_name(metadata, progress_callback=None):
    """Detect instrument from title, then fall back to image OCR."""
    title = (metadata or {}).get("title", "")
    result = _detect_instrument_from_title(title)
    if result:
        if progress_callback:
            progress_callback(f"  Detected instrument from title: {result}")
        return result
    # Fallback: OCR page image
    page_images_dir = (metadata or {}).get("page_images_dir", "")
    result = _detect_instrument_from_image(page_images_dir)
    if result and progress_callback:
        progress_callback(f"  Detected instrument from page image: {result}")
    return result


# ── Metadata & Part Name Fixes ────────────────────────────────────────────────

def _fix_metadata(score, metadata, music21_mod):
    """Replace garbled OMR title with the known title from the database."""
    corrections = []
    title = (metadata or {}).get("title", "")
    if not title:
        return corrections

    if score.metadata:
        old_title = score.metadata.title or ""
        if old_title != title:
            score.metadata.title = title
            corrections.append({
                "type": "correction",
                "measure": 0,
                "part": "",
                "message": f"Replaced OMR title '{old_title}' with '{title}'"
            })
    else:
        md = music21_mod.metadata.Metadata()
        md.title = title
        score.insert(0, md)
        corrections.append({
            "type": "correction",
            "measure": 0,
            "part": "",
            "message": f"Set title to '{title}' (was missing)"
        })
    return corrections


def _fix_part_name(part, detected_name, music21_mod):
    """Replace 'Piano' part name with the detected instrument name."""
    corrections = []
    old_name = part.partName or ""
    if not detected_name:
        return corrections
    if old_name.lower() in ("piano", "pno", "") or not old_name:
        part.partName = detected_name
        for inst in part.getInstruments(recurse=True):
            if hasattr(inst, 'instrumentName'):
                inst.instrumentName = detected_name
        corrections.append({
            "type": "correction",
            "measure": 0,
            "part": detected_name,
            "message": f"Renamed part from '{old_name or 'Piano'}' "
                       f"to '{detected_name}'"
        })
    return corrections


def postprocess_musicxml(musicxml_path: str,
                         progress_callback=None,
                         metadata=None) -> list[dict]:
    """
    Apply automatic corrections to OMR output MusicXML.

    Fixes: pad short measures, remove chords on monophonic instruments,
    upgrade 16th rests to eighth rests when measure is short.

    Saves the original file as <name>_original.musicxml before overwriting.
    Returns list of correction dicts.
    """
    try:
        import music21
    except ImportError:
        return [{"type": "warning", "measure": 0, "part": "",
                 "message": "music21 not installed - post-processing skipped."}]

    corrections = []

    if progress_callback:
        progress_callback("Starting post-processing corrections...")

    try:
        score = music21.converter.parse(musicxml_path, forceSource=True)
    except Exception as e:
        return [{"type": "error", "measure": 0, "part": "",
                 "message": f"Post-processing: failed to parse MusicXML: {e}"}]

    if progress_callback:
        progress_callback(f"  Score loaded: {len(score.parts)} part(s)")

    # Save original as backup before modifying
    base, ext = os.path.splitext(musicxml_path)
    original_path = base + "_original" + ext
    if not os.path.exists(original_path):
        shutil.copy2(musicxml_path, original_path)
        if progress_callback:
            progress_callback(
                f"  Original saved as: {os.path.basename(original_path)}"
            )

    # Fix metadata (title) from database
    corrections.extend(_fix_metadata(score, metadata, music21))

    # Detect instrument name for part renaming and monophonic detection
    detected_instrument = _detect_instrument_name(metadata, progress_callback)

    # Apply fixes to each part
    for part in score.parts:
        part_name = part.partName or f"Part {part.id}"
        if progress_callback:
            progress_callback(f"  Processing part: {part_name}")

        # Fix part name from "Piano" to detected instrument
        if detected_instrument:
            name_fixes = _fix_part_name(part, detected_instrument, music21)
            corrections.extend(name_fixes)
            if name_fixes:
                part_name = part.partName  # Use the updated name

        # Chord removal, then duration correction
        corrections.extend(_fix_monophonic_chords(part, part_name, music21))
        corrections.extend(_fix_short_measures(part, part_name, music21))

    # Write corrected score back only if changes were made
    if corrections:
        try:
            score.write('musicxml', fp=musicxml_path)
            if progress_callback:
                progress_callback(
                    f"  Wrote corrected file: "
                    f"{os.path.basename(musicxml_path)}"
                )
        except Exception as e:
            corrections.append({
                "type": "error", "measure": 0, "part": "",
                "message": f"Failed to write corrected MusicXML: {e}"
            })
    else:
        if progress_callback:
            progress_callback("  No corrections needed.")

    if progress_callback:
        progress_callback(
            f"Post-processing complete: {len(corrections)} correction(s)"
        )

    return corrections


def validate_musicxml(musicxml_path: str,
                      progress_callback=None,
                      metadata=None) -> list[dict]:
    """
    Validate a MusicXML file using music21 + custom checks.
    Returns a list of validation issue dicts:
        [{"type": "error"|"warning"|"info", "measure": N,
          "part": "...", "message": "..."}]
    """
    try:
        import music21
    except ImportError:
        return [{"type": "warning", "measure": 0, "part": "",
                 "message": "music21 not installed - validation skipped. "
                            "Install with: pip install music21"}]

    issues = []

    if progress_callback:
        progress_callback("Parsing MusicXML with music21...")

    try:
        score = music21.converter.parse(musicxml_path, forceSource=True)
    except Exception as e:
        return [{"type": "error", "measure": 0, "part": "",
                 "message": f"Failed to parse MusicXML: {e}"}]

    if progress_callback:
        progress_callback(f"Score loaded: {len(score.parts)} part(s)")
        progress_callback("Running validation checks...")

    # ── Check 1: Time signature / measure duration consistency ─────────
    for part in score.parts:
        part_name = part.partName or f"Part {part.id}"
        for measure in part.getElementsByClass('Measure'):
            ts = measure.getContextByClass('TimeSignature')
            if ts:
                expected = ts.barDuration.quarterLength
                actual = measure.duration.quarterLength
                if abs(actual - expected) > 0.001 and actual > 0:
                    issues.append({
                        "type": "warning",
                        "measure": measure.number,
                        "part": part_name,
                        "message": f"Duration mismatch: expected {expected} beats, "
                                   f"got {actual} beats"
                    })

    # ── Check 2: Pitch range validation ───────────────────────────────
    for part in score.parts:
        part_name = part.partName or f"Part {part.id}"
        # Try to match part name to known ranges
        matched_range = None
        name_lower = part_name.lower()
        for instr_key, pitch_range in INSTRUMENT_RANGES.items():
            if instr_key in name_lower:
                matched_range = pitch_range
                break

        if matched_range:
            low = music21.pitch.Pitch(matched_range[0])
            high = music21.pitch.Pitch(matched_range[1])
            out_of_range_count = 0
            for note in part.recurse().notes:
                if hasattr(note, 'pitch'):
                    if note.pitch < low or note.pitch > high:
                        out_of_range_count += 1
                        if out_of_range_count <= 5:  # Limit reported notes
                            issues.append({
                                "type": "warning",
                                "measure": getattr(note, 'measureNumber', 0) or 0,
                                "part": part_name,
                                "message": f"Pitch {note.nameWithOctave} outside "
                                           f"typical range ({matched_range[0]}-"
                                           f"{matched_range[1]})"
                            })
            if out_of_range_count > 5:
                issues.append({
                    "type": "warning",
                    "measure": 0,
                    "part": part_name,
                    "message": f"... and {out_of_range_count - 5} more out-of-range "
                               f"pitches (total: {out_of_range_count})"
                })

    # ── Check 3: Empty / rest-only parts (possible OCR failure) ───────
    for part in score.parts:
        part_name = part.partName or f"Part {part.id}"
        measures = list(part.getElementsByClass('Measure'))
        total = len(measures)
        if total == 0:
            continue
        empty = 0
        for m in measures:
            notes_and_rests = list(m.notesAndRests)
            if not notes_and_rests or all(
                n.isRest for n in notes_and_rests
            ):
                empty += 1
        if total > 0 and empty / total > 0.8:
            issues.append({
                "type": "warning",
                "measure": 0,
                "part": part_name,
                "message": f"{empty}/{total} measures are empty/rests only - "
                           f"possible OMR recognition failure"
            })

    # ── Check 4: Key/time signature present ───────────────────────────
    ts_found = score.flatten().getElementsByClass('TimeSignature')
    if not list(ts_found):
        issues.append({
            "type": "warning",
            "measure": 0,
            "part": "",
            "message": "No time signature found in score"
        })

    ks_found = score.flatten().getElementsByClass('KeySignature')
    if not list(ks_found):
        issues.append({
            "type": "warning",
            "measure": 0,
            "part": "",
            "message": "No key signature found in score"
        })

    # ── Check 5: Possible output truncation ─────────────────────────
    for part in score.parts:
        part_name = part.partName or f"Part {part.id}"
        measures = list(part.getElementsByClass('Measure'))
        if not measures:
            continue
        total = len(measures)

        # Heuristic A: last measure is less than 50% of expected duration
        last_measure = measures[-1]
        ts = last_measure.getContextByClass('TimeSignature')
        if ts:
            expected_ql = ts.barDuration.quarterLength
            actual_ql = last_measure.duration.quarterLength
            if 0 < actual_ql < expected_ql * 0.5:
                issues.append({
                    "type": "warning",
                    "measure": total,
                    "part": part_name,
                    "message": f"Last measure appears truncated "
                               f"({actual_ql}/{expected_ql} beats) — "
                               f"OMR may have hit a sequence length limit"
                })

        # Heuristic B: low measure count per page
        num_pages = (metadata or {}).get("num_pages")
        if num_pages and isinstance(num_pages, int) and num_pages > 0:
            measures_per_page = total / num_pages
            if measures_per_page < 20:
                issues.append({
                    "type": "warning",
                    "measure": 0,
                    "part": part_name,
                    "message": f"Only {total} measures across {num_pages} "
                               f"page(s) ({measures_per_page:.0f}/page) — "
                               f"output may be incomplete"
                })

    # ── Summary ───────────────────────────────────────────────────────
    if progress_callback:
        n_warn = sum(1 for i in issues if i["type"] == "warning")
        n_err = sum(1 for i in issues if i["type"] == "error")
        progress_callback(f"Validation complete: {n_err} error(s), {n_warn} warning(s)")

    if not issues:
        issues.append({
            "type": "info",
            "measure": 0,
            "part": "",
            "message": "No validation issues found."
        })

    return issues


# ── Main processing function ──────────────────────────────────────────────────

def process_sheet_music(input_path: str, output_dir: str,
                        engine: str = "audiveris",
                        progress_callback=None,
                        progress_percent_callback=None,
                        metadata=None) -> dict:
    """
    Full OMR pipeline: run engine -> validate -> return results.

    progress_percent_callback(current, total) is called per-page so
    the UI can show a determinate progress bar.

    Returns: {
        "musicxml_path": str | None,
        "engine": str,
        "validation_issues": list[dict],
        "status": "completed" | "failed",
        "error": str | None
    }
    """
    os.makedirs(output_dir, exist_ok=True)

    try:
        if progress_callback:
            progress_callback(f"Using engine: {engine}")

        if engine == "audiveris":
            musicxml_path = run_audiveris(input_path, output_dir, progress_callback)
        elif engine == "homr":
            musicxml_path = run_homr(input_path, output_dir, progress_callback,
                                     progress_percent_callback)
        else:
            raise ValueError(f"Unknown engine: {engine}")

        if progress_callback:
            progress_callback(f"OMR complete: {os.path.basename(musicxml_path)}")

        # Enrich metadata with page images path (for instrument OCR)
        if metadata is None:
            metadata = {}
        pages_dir = os.path.join(output_dir, "_pages")
        if os.path.isdir(pages_dir):
            metadata["page_images_dir"] = pages_dir

        # Post-processing corrections (between engine output and validation)
        corrections = postprocess_musicxml(musicxml_path, progress_callback,
                                           metadata=metadata)

        if progress_callback:
            progress_callback("Starting MusicXML validation...")

        validation = validate_musicxml(musicxml_path, progress_callback,
                                       metadata=metadata)

        return {
            "musicxml_path": musicxml_path,
            "engine": engine,
            "validation_issues": validation,
            "corrections": corrections,
            "status": "completed",
            "error": None,
        }

    except Exception as e:
        if progress_callback:
            progress_callback(f"ERROR: {e}")
        return {
            "musicxml_path": None,
            "engine": engine,
            "validation_issues": [],
            "status": "failed",
            "error": str(e),
        }
