"""Diagnostic: list prior-year instrument assignments and whether they
resolve to the current roster.

Usage: python scripts/diagnose_rollover.py [profile_name]
If no profile_name is given the script picks the first profile found in
LOCALAPPDATA/RokasResonance/profiles.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import Database


def find_database(profile_name=None):
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    profiles_dir = os.path.join(local_app_data, "RokasResonance", "profiles") if local_app_data else ""

    if profiles_dir and os.path.isdir(profiles_dir):
        profiles = sorted(os.listdir(profiles_dir))
        if profile_name:
            candidate = os.path.join(profiles_dir, profile_name, "rokas_resonance.db")
            if os.path.exists(candidate):
                return candidate, profile_name
            else:
                print(f"Profile {profile_name} not found in {profiles_dir}")
                sys.exit(1)
        for profile in profiles:
            candidate = os.path.join(profiles_dir, profile, "rokas_resonance.db")
            if os.path.exists(candidate):
                return candidate, profile

    # Fallback: local DB next to repo
    local = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "rokas_resonance.db")
    local = os.path.normpath(local)
    if os.path.exists(local):
        return local, "(local)"

    print("ERROR: No database found. Run the app first to create a profile.")
    sys.exit(1)


def main():
    profile = sys.argv[1] if len(sys.argv) > 1 else None
    db_path, profile_used = find_database(profile)
    print(f"Using DB: {db_path} (profile: {profile_used})")
    db = Database(db_path)

    cur_year = db.current_school_year()
    prior = db.previous_school_year(cur_year)
    print(f"Current year: {cur_year}, prior year: {prior}\n")

    assignments = db.get_assignments_for_school_year(prior)
    if not assignments:
        print("No assignments found for prior year.")
        return

    print(f"Found {len(assignments)} assignments from {prior}:\n")
    rows = [dict(r) for r in assignments]

    all_inst = [dict(r) for r in db.get_instruments_with_status()]

    # Try to resolve each to current roster using same logic as the UI
    unresolved = []
    for r in rows:
        first, last = r.get("first_name"), r.get("last_name")
        if not (first and last):
            parts = (r.get("student_name") or "").split(None, 1)
            first = parts[0] if parts else ""
            last = parts[1] if len(parts) > 1 else ""
        # Prefer the exported district_id (stable identifier) from the
        # assignment row. Fall back to the checkout's student_id only for
        # completeness, but the DB expects a string for district_id.
        district_id = r.get("district_id") or r.get("student_id") or ""
        if district_id is not None:
            district_id = str(district_id)
        current = None
        if district_id:
            current = db.find_enrolled_student(cur_year, district_id=district_id)
        if not current and first and last:
            current = db.find_enrolled_student(cur_year, first=first, last=last)
        cur = dict(current) if current else None
        ok = bool(cur)
        print(f"Checkout {r.get('checkout_id')}: {r.get('student_name')!r} (district_id={r.get('student_id')}) -> matched={ok}")
        if not ok:
            unresolved.append(r)
        else:
            print(f"  Matched to: {cur.get('first_name')} {cur.get('last_name')} (id={cur.get('id')}, grade={cur.get('grade')})")

    print(f"\nUnresolved assignments: {len(unresolved)}")
    if unresolved:
        for u in unresolved[:40]:
            print(f"  - {u.get('student_name')!r} (checkout_id={u.get('checkout_id')}, district_id={u.get('student_id')}, student_active={u.get('student_active')})")

if __name__ == '__main__':
    main()
