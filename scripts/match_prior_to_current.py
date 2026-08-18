"""Try multiple heuristics to match prior-year assignments to current roster.
Prints counts for each matching method and shows examples.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from database import Database

local_app_data = os.environ.get("LOCALAPPDATA", "")
profiles_dir = os.path.join(local_app_data, "RokasResonance", "profiles") if local_app_data else ""
profiles = sorted(os.listdir(profiles_dir)) if profiles_dir and os.path.isdir(profiles_dir) else []
if not profiles:
    print("No profiles found")
    sys.exit(1)
profile = profiles[0]
db_path = os.path.join(profiles_dir, profile, "rokas_resonance.db")
print(f"Using DB: {db_path}")
db = Database(db_path)
cur = db.current_school_year()
prior = db.previous_school_year(cur)
assigns = [dict(r) for r in db.get_assignments_for_school_year(prior)]
students = [dict(s) for s in db.get_all_students(cur)]
print(f"Assignments: {len(assigns)}, Current students: {len(students)}")

# build lookup maps
by_id = { (s.get('student_id') or '').strip(): s for s in students if s.get('student_id') }
by_name = { ( (s.get('first_name') or '').strip().lower(), (s.get('last_name') or '').strip().lower() ): s for s in students }
by_last_initial = {}
for s in students:
    last = (s.get('last_name') or '').strip().lower()
    first = (s.get('first_name') or '').strip()
    if not last:
        continue
    key = (last, (first[:1].lower() if first else ''))
    by_last_initial.setdefault(key, []).append(s)

match_id = []
match_name = []
match_lastinit = []
match_last_unique = []
unmatched = []
for a in assigns:
    aid = (a.get('district_id') or '') or (a.get('student_id') or '')
    aid = str(aid).strip()
    afirst = (a.get('first_name') or '')
    alast = (a.get('last_name') or '')
    key_name = (afirst.strip().lower(), alast.strip().lower())
    key_lastinit = (alast.strip().lower(), (afirst.strip()[:1].lower() if afirst else ''))
    if aid and aid in by_id:
        match_id.append((a, by_id[aid]))
        continue
    if key_name in by_name:
        match_name.append((a, by_name[key_name]))
        continue
    if key_lastinit in by_last_initial and len(by_last_initial[key_lastinit])==1:
        match_lastinit.append((a, by_last_initial[key_lastinit][0]))
        continue
    # last-name unique? if only one student has that last name
    last_lower = alast.strip().lower()
    last_matches = [s for s in students if (s.get('last_name') or '').strip().lower()==last_lower]
    if last_lower and len(last_matches)==1:
        match_last_unique.append((a, last_matches[0]))
        continue
    unmatched.append(a)

print(f"Matched by ID: {len(match_id)}")
print(f"Matched by exact name: {len(match_name)}")
print(f"Matched by last+initial unique: {len(match_lastinit)}")
print(f"Matched by last-name unique: {len(match_last_unique)}")
print(f"Unmatched: {len(unmatched)}\n")

print("Examples of matched by ID (first 10):")
for a,s in match_id[:10]:
    print(f"  {a.get('student_name')} (checkout {a.get('checkout_id')}) -> {s.get('first_name')} {s.get('last_name')} id={s.get('student_id')}")
print("\nExamples of matched by exact name (first 10):")
for a,s in match_name[:10]:
    print(f"  {a.get('student_name')} -> {s.get('first_name')} {s.get('last_name')}")
print("\nExamples of unmatched (first 20):")
for a in unmatched[:20]:
    print(f"  {a.get('student_name')} (checkout {a.get('checkout_id')}, district_id={a.get('district_id')}, student_active={a.get('student_active')})")
