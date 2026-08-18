"""Import the downloaded Synergy CSV into the app as 'Advanced Band'.
Usage: python scripts/import_downloaded_roster.py [csv_path]
If no path given, uses CC763F9C-FAF2-4BE8-959F-199949F3D48D.CSV from Downloads.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from database import Database
import import_service

DEFAULT = r"C:\Users\mangu\Downloads\CC763F9C-FAF2-4BE8-959F-199949F3D48D.CSV"
path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT
if not os.path.exists(path):
    print(f"CSV not found: {path}")
    sys.exit(1)

# find DB
local_app_data = os.environ.get("LOCALAPPDATA", "")
profiles_dir = os.path.join(local_app_data, "RokasResonance", "profiles") if local_app_data else ""
profile = None
if profiles_dir and os.path.isdir(profiles_dir):
    profiles = sorted(os.listdir(profiles_dir))
    if profiles:
        profile = profiles[0]
db_path = os.path.join(profiles_dir, profile, "rokas_resonance.db") if profile else None
if not db_path or not os.path.exists(db_path):
    print("No DB found in profiles; aborting.")
    sys.exit(1)

print(f"Using DB: {db_path}")
db = Database(db_path)
sy = db.current_school_year()
print(f"Importing into school year: {sy}")

# Map both sections we found to Advanced Band
section_to_class = {"MU_401.0-0001": "Advanced Band", "MU_404.0-0001": "Advanced Band"}
res = import_service.import_students_sectioned(db, path, section_to_class, period=None, school_year=sy)
print("Import result:", res)
