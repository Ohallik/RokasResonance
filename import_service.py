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


def _clean(inst):
    return {k: v for k, v in inst.items() if not k.startswith("_")}


# ── Students (Synergy) ────────────────────────────────────────────────────────

def import_students(db, csv_source, ensemble_label, period, school_year):
    """Import one class's Synergy CSV, tagging every student with ``ensemble_label``
    and ``period`` for ``school_year``.  A student already imported (same district
    Student ID this year — e.g. they're in two of your classes) gets the new
    ensemble/period merged onto their record rather than duplicated."""
    studs = synergy_import.parse_synergy_students(csv_source)
    existing = {s["student_id"]: s for s in db.get_all_students(school_year)
                if s["student_id"]}
    added = updated = 0
    for s in studs:
        rec = dict(s)
        rec["school_year"] = school_year
        rec["ensembles"] = ensemble_label
        rec["class_periods"] = str(period) if period else None
        prior = existing.get(rec.get("student_id"))
        if prior:
            merged = dict(prior)
            merged["ensembles"] = _merge_csv(prior["ensembles"], ensemble_label)
            merged["class_periods"] = _merge_csv(prior["class_periods"],
                                                 str(period) if period else "")
            db.update_student(prior["id"], merged)
            updated += 1
        else:
            db.add_student(rec)
            added += 1
    return {"added": added, "updated": updated, "total": len(studs)}


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


def _merge_csv(existing, new):
    have = [x.strip() for x in (existing or "").split(",") if x.strip()]
    if new and new not in have:
        have.append(new)
    return ", ".join(have)


# ── Inventory (CutTime + Charms) ──────────────────────────────────────────────

def import_inventory(db, cuttime_path=None, charms_inv_path=None,
                     charms_repair_path=None):
    """Import inventory from CutTime and/or Charms and recreate current loans +
    repair history.  Returns a summary of what happened."""
    summary = {"added": 0, "enriched": 0, "charms_only_added": 0,
               "repairs": 0, "loans": 0, "loans_unmatched": 0}
    pending_loans = []                    # (instrument_id, checkout dict)

    # 1) CutTime = authoritative current inventory.
    if cuttime_path:
        for inst in cuttime_import.parse_cuttime_inventory(cuttime_path):
            co = inst.get("_checkout")
            row = _match_instrument(db, inst)
            iid = row["id"] if row else db.add_instrument(_clean(inst))
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
                iid = db.add_instrument(_clean(inst))
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
