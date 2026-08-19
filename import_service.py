"""
import_service.py - Orchestrates a one-time "new profile" data import.

Ties the three parsers (synergy / cuttime / charms) to the database.  Run once
when a teacher first sets up their profile from scratch; afterwards their data
lives locally and only class lists are re-uploaded each year (the New School Year
wizard).  All operations are idempotent enough to re-run safely: instruments are
matched by serial / barcode / district before adding, repairs and open checkouts
dedup, and students dedup by district Student ID within the school year.

Merge policy (as the teacher specified): CutTime is the AUTHORITATIVE source for
current inventory; Charms only BACK-FILLS blank purchase/history fields on matched
instruments and contributes the repair log (CutTime has no repair export).  A
Charms-only user (no CutTime) imports their Charms inventory directly.

Pure logic + DB calls, no UI, so it can be unit-tested and driven by the wizard.
"""

from datetime import datetime

import synergy_import
import cuttime_import
import charms_import


def _norm_date(s):
    """A Charms/CutTime date string → YYYY-MM-DD (best effort; date part only)."""
    if not s:
        return s
    part = str(s).strip().split()[0]
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(part, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return part


def _match_instrument(db, inst):
    """Find an existing instrument for an import row by serial, then barcode,
    then district number."""
    sn, bc, dist = inst.get("serial_no"), inst.get("barcode"), inst.get("district_no")
    row = db.get_instrument_by_serial(sn) if sn else None
    if not row and bc:
        row = db.get_instrument_by_barcode(bc)
    if not row and dist:
        row = db.get_instrument_by_barcode(dist)
    return row


def _clean(inst, site_id=None):
    out = {k: v for k, v in inst.items() if not k.startswith("_")}
    if site_id:
        out["site_id"] = site_id
    return out


# ── Students (Synergy) ────────────────────────────────────────────────────────

def import_students(db, csv_source, ensemble_label, period, school_year,
                    site_id=None):
    """Import one class's Synergy CSV, tagging every student with ``ensemble_label``
    and ``period`` for ``school_year``.  A student already imported (same district
    Student ID this year — e.g. they're in two of your classes) gets the new
    ensemble/period merged onto their record rather than duplicated.

    ``site_id`` says which school the children on this list are at.  It does
    NOT narrow the matching: the district Student ID is unique district-wide,
    so it -- not the name and not the building -- is what decides whether two
    rows are the same child.  Six Alex Lis with six IDs are six children; one
    ID appearing at a second school is one child who has moved, and gets moved
    rather than duplicated."""
    studs = synergy_import.parse_synergy_students(csv_source)
    existing = {s["student_id"]: s for s in db.get_all_students(school_year)
                if s["student_id"]}
    # Where a school's choir IS the year group, every child imported joins it.
    # Ticking two hundred boxes by hand is not a reasonable alternative.
    choir_label = site_name = None
    if site_id:
        site = db.get_site(site_id)
        if site:
            site_name = dict(site)["name"]
            if dict(site).get("choir_default"):
                from ui.ensembles import choir_ensemble
                choir_label = choir_ensemble(site_name)
    added = updated = moved = 0
    for s in studs:
        rec = dict(s)
        rec["school_year"] = school_year
        rec["ensembles"] = ensemble_label
        rec["class_periods"] = str(period) if period else None
        if choir_label:
            rec["ensembles"] = _merge_csv(rec["ensembles"], choir_label)
        prior = existing.get(rec.get("student_id"))
        if prior:
            merged = dict(prior)
            base = prior["ensembles"]
            if site_name:
                # One section per school. Alex Li is in Section 1 or Section 2,
                # never both -- they run back to back in the same room, so
                # being in both is not a thing that can happen. Turning up on
                # the other list means he was moved, so the old section goes.
                base = _drop_site_classes(base, site_name, sections_only=True)
            merged["ensembles"] = _merge_csv(base, ensemble_label)
            if choir_label:
                merged["ensembles"] = _merge_csv(merged["ensembles"], choir_label)
            merged["class_periods"] = _merge_csv(prior["class_periods"],
                                                 str(period) if period else "")
            merged["provisional"] = 0     # official roster confirms an incoming student
            # Turning up on a different school's list means they moved.  Drop
            # the old school's sections on the way: a child at Sherwood Forest
            # is not still in Clyde Hill's Section 1, and leaving it there puts
            # them on their previous teacher's class list all year.
            transferred = (site_id and prior["site_id"]
                           and prior["site_id"] != site_id)
            if transferred:
                old_site = db.get_site(prior["site_id"])
                if old_site:
                    merged["ensembles"] = _drop_site_classes(
                        merged["ensembles"], dict(old_site)["name"])
            db.update_student(prior["id"], merged)
            updated += 1
            # site_id is not in update_student's column list on purpose -- an
            # edit that forgot it would blank the school -- so set it here.
            if site_id and prior["site_id"] != site_id:
                db.set_student_site(prior["id"], site_id)
                if transferred:
                    moved += 1
        else:
            rec["site_id"] = site_id
            db.add_student(rec)
            added += 1
    return {"added": added, "updated": updated, "moved": moved,
            "total": len(studs)}


def import_students_sectioned(db, csv_source, section_to_class, period, school_year):
    """Import a Synergy CSV that contains MORE THAN ONE class section, routing
    each student to the class mapped from their Section.

    ``section_to_class`` maps a section code -> class label; a section mapped to
    a blank/None label is skipped (e.g. the co-director's section you don't want
    to pull in).  A student appearing in several mapped sections is tagged with
    all of them.  Dedups across the run by district Student ID, merging the
    ensembles/periods onto the existing record rather than duplicating."""
    studs = synergy_import.parse_synergy_students(csv_source)
    existing = {s["student_id"]: s for s in db.get_all_students(school_year)
                if s["student_id"]}
    per = str(period) if period else None
    added = updated = skipped = 0
    per_class = {}
    for s in studs:
        labels = []
        for sec in (s.get("sections") or ([s.get("section")] if s.get("section") else [])):
            lab = (section_to_class.get(sec) or "").strip()
            if lab and lab not in labels:
                labels.append(lab)
        if not labels:
            skipped += 1
            continue
        prior = existing.get(s.get("student_id"))
        if prior:
            merged = dict(prior)
            ens = prior.get("ensembles")
            for lab in labels:
                ens = _merge_csv(ens, lab)
            merged["ensembles"] = ens
            merged["class_periods"] = _merge_csv(prior.get("class_periods"), per or "")
            merged["provisional"] = 0     # official roster confirms an incoming student
            db.update_student(prior["id"], merged)
            merged["id"] = prior["id"]
            existing[s["student_id"]] = merged
            updated += 1
        else:
            rec = dict(s)
            rec["school_year"] = school_year
            rec["ensembles"] = ", ".join(labels)
            rec["class_periods"] = per
            new_id = db.add_student(rec)
            rec["id"] = new_id
            existing[s["student_id"]] = rec
            added += 1
        for lab in labels:
            per_class[lab] = per_class.get(lab, 0) + 1
    return {"added": added, "updated": updated, "skipped": skipped,
            "total": len(studs), "per_class": per_class}


def _drop_site_classes(csv_val, site_name, sections_only=False):
    """Remove one school's classes from a student's ensembles.

    5th grade classes are named after their school ("Clyde Hill Elementary
    School: Section 1"), so the school's own name is what identifies them.
    Anything not recognisably that school's is left alone -- a secondary class
    has no business being touched by an elementary import.

    ``sections_only`` keeps that school's choir. Choir is something a child is
    in AS WELL as their section, so moving them between sections must not
    quietly take them out of it.
    """
    prefix = (site_name or "").strip().lower()
    if not prefix:
        return csv_val
    kept = []
    for part in (csv_val or "").split(","):
        p = part.strip()
        if not p:
            continue
        mine = p.lower().startswith(prefix)
        if mine and sections_only and p.lower().rstrip().endswith("choir"):
            kept.append(p)          # their choir survives a section change
        elif not mine:
            kept.append(p)
    return ", ".join(kept)


def _merge_csv(existing, new):
    have = [x.strip() for x in (existing or "").split(",") if x.strip()]
    if new and new not in have:
        have.append(new)
    return ", ".join(have)


# ── Inventory (CutTime + Charms) ──────────────────────────────────────────────

def import_inventory(db, cuttime_path=None, charms_inv_path=None,
                     charms_repair_path=None, site_id=None):
    """Import inventory from CutTime and/or Charms and recreate current loans +
    repair history.  Returns a summary of what happened.

    ``site_id`` puts the instruments at one school, for a 5th grade teacher
    bringing an elementary cupboard across in their first year."""
    summary = {"added": 0, "enriched": 0, "charms_only_added": 0,
               "repairs": 0, "loans": 0, "loans_unmatched": 0}
    pending_loans = []                    # (instrument_id, checkout dict)

    # 1) CutTime = authoritative current inventory.
    if cuttime_path:
        for inst in cuttime_import.parse_cuttime_inventory(cuttime_path):
            co = inst.get("_checkout")
            row = _match_instrument(db, inst)
            iid = row["id"] if row else db.add_instrument(_clean(inst, site_id))
            if not row:
                summary["added"] += 1
            if co:
                pending_loans.append((iid, co))

    # 2) Charms inventory — back-fill purchase data on matches; a Charms-only
    #    user (no CutTime) imports the instruments themselves.
    if charms_inv_path:
        for inst in charms_import.parse_charms_inventory(charms_inv_path):
            co = inst.get("_checkout")
            row = _match_instrument(db, inst)
            if row:
                pf = charms_import.charms_purchase_fields(inst)
                merged = dict(row)
                changed = False
                for k, v in pf.items():
                    if not merged.get(k):
                        merged[k] = v
                        changed = True
                if changed:
                    db.update_instrument(row["id"], merged)
                    summary["enriched"] += 1
                iid = row["id"]
            elif not cuttime_path:
                iid = db.add_instrument(_clean(inst, site_id))
                summary["charms_only_added"] += 1
            else:
                iid = None                # in Charms but not CutTime → skip add
            # Charms loan assignments are historical; when CutTime is present it
            # is authoritative for who currently holds what, so only trust Charms
            # loans for a Charms-only import.
            if co and iid and not cuttime_path:
                pending_loans.append((iid, co))

    # 3) Charms repair log → repairs (dedup by instrument+date+description).
    if charms_repair_path:
        for r in charms_import.parse_charms_repairs(charms_repair_path):
            row = None
            if r.get("match_serial"):
                row = db.get_instrument_by_serial(r["match_serial"])
            if not row and r.get("match_district"):
                row = db.get_instrument_by_barcode(r["match_district"])
            if not row:
                continue
            db.import_repair({
                "instrument_id": row["id"], "priority": r["priority"],
                "date_added": _norm_date(r["date_added"]),
                "assigned_to": r["assigned_to"],
                "date_repaired": _norm_date(r["date_repaired"]),
                "description": r["description"], "location": r["location"],
                "est_cost": r["est_cost"], "act_cost": r["act_cost"],
                "invoice_number": r["invoice_number"]})
            summary["repairs"] += 1

    # 4) Recreate current loans, matching the assignee to an imported student.
    for iid, co in pending_loans:
        name = f"{co.get('first_name', '')} {co.get('last_name', '')}".strip()
        sid = None
        studno = co.get("student_id")
        if studno:
            st = db.find_student_by_student_id(studno)
            if st:
                sid = st["id"]
        db.import_open_checkout(iid, sid, name or "(unknown)",
                                _norm_date(co.get("date_assigned")))
        summary["loans"] += 1
        if not sid:
            summary["loans_unmatched"] += 1
    return summary
