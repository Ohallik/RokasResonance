"""
Quick test of the music importer pipeline on a sample of images.
Run from the RokasResonance directory: python test_importer.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

BASE_DIR = r"C:\Users\natem\AppData\Local\RokasResonance\profiles\Meagan R. Mangum"
PICS_DIR = r"C:\Users\natem\Downloads\MusicPics"

# Representative sample: one of each type
TEST_IMAGES = [
    ("IMG_2572.JPG", ""),
    ("IMG_2573.JPG", ""),
    ("IMG_2574.JPG", ""),
    ("IMG_2576.JPG", ""),
    ("IMG_2577.JPG", ""),
    ("IMG_2578.JPG", ""),
    ("IMG_2579.JPG", ""),
    ("IMG_2580.JPG", ""),
    ("IMG_2581.JPG", ""),
    ("IMG_2582.JPG", ""),
    ("IMG_2583.JPG", ""),
    ("IMG_2584.JPG", ""),
    ("IMG_2585.JPG", ""),
    ("IMG_2586.JPG", ""),
    ("IMG_2587.JPG", ""),
    ("IMG_2588.JPG", ""),
    ("IMG_2589.JPG", ""),
    ("IMG_2591.JPG", ""),
    ("IMG_2592.JPG", ""),
    ("IMG_2593.JPG", ""),
    ("IMG_2594.JPG", ""),
    ("IMG_2595.JPG", ""),
    ("IMG_2596.JPG", ""),
    ("IMG_2597.JPG", ""),
    ("IMG_2598.JPG", ""),
    ("IMG_2599.JPG", ""),
    ("IMG_2600.JPG", ""),
    ("IMG_2601.JPG", ""),
    ("IMG_2602.JPG", ""),
    ("IMG_2604.JPG", ""),
    ("IMG_2605.JPG", ""),
]

from ui.music_importer import (
    _file_to_images, _classify_image,
    _extract_single_piece, _extract_flat_covers,
    _extract_spine_shelf, _extract_toc,
    _dict_to_prefill,
)

def hr(char="=", n=70):
    print(char * n)

for fname, note in TEST_IMAGES:
    path = os.path.join(PICS_DIR, fname)
    hr()
    print(f"FILE: {fname}")
    print(f"NOTE: {note}")
    hr("-")

    images = _file_to_images(path, max_px=1800)
    if not images:
        print("  ERROR: could not load image")
        continue

    img_type = _classify_image(images, BASE_DIR)
    print(f"CLASSIFIED AS: {img_type}")
    hr()

    if img_type == "FLAT_COVERS":
        pieces = _extract_flat_covers(images, BASE_DIR)
    elif img_type == "SPINE_SHELF":
        hi_res = _file_to_images(path, max_px=2400)
        pieces = _extract_spine_shelf(hi_res or images, BASE_DIR)
    elif img_type == "TABLE_OF_CONTENTS":
        pieces = _extract_toc(images, BASE_DIR)
    else:
        pieces = _extract_single_piece(path, images, BASE_DIR)

    print(f"PIECES FOUND: {len(pieces)}")
    hr()
    for i, p in enumerate(pieces, 1):
        prefill = _dict_to_prefill(p)
        title     = prefill.get("title", "")
        composer  = prefill.get("composer", "")
        arranger  = prefill.get("arranger", "")
        publisher = prefill.get("publisher", "")
        ensemble  = prefill.get("ensemble_type", "")
        diff      = prefill.get("difficulty", "")
        print(f"  {i:>3}. {title}")
        parts = []
        if composer:  parts.append(f"by {composer}")
        if arranger:  parts.append(f"arr. {arranger}")
        if publisher: parts.append(publisher)
        if ensemble:  parts.append(ensemble)
        if diff:      parts.append(f"Grade {diff}")
        if parts:
            print(f"       {' | '.join(parts)}")

print()
hr()
print("Test complete.")
