"""
roster_form.py - Roka's blank student roster form: hand it out, read it back.

The student counterpart of the inventory form, and used the same way.
Import ▸ Get a blank roster form saves an Excel sheet whose columns are the
fields of the Student window, built for this profile (its schools in the
School dropdown, its classes and instruments suggested).  The teacher pastes
whatever list they have into it -- for an elementary specialist that is the
simple name-and-ID list, the only thing Synergy will give them -- and fills
in what else they know.  Import ▸ Student list reads it back and says what
happened.  Roka works out for itself whether a file is the form or a
district CSV, so the teacher is never asked.
"""

import os
from tkinter import filedialog

from ttkbootstrap.dialogs import Messagebox

ELEM_SECTIONS = ["Section 1", "Section 2"]


def _sites(db):
    try:
        return [dict(s) for s in db.get_sites()]
    except Exception:
        return []


def _level(sites):
    """"elementary" when every school is one, "mixed" when some are,
    "secondary" otherwise (including a profile with no schools at all)."""
    if not sites:
        return "secondary"
    elem = [s for s in sites if s.get("level") == "elementary"]
    if len(elem) == len(sites):
        return "elementary"
    return "mixed" if elem else "secondary"


def _program_type(base_dir, fallback="band"):
    try:
        from ui.settings_dialog import load_settings
        return ((load_settings(base_dir).get("teacher") or {})
                .get("program_type") or fallback)
    except Exception:
        return fallback


def _class_suggestions(db, school_year, program_type, base_dir, level):
    """Class names to OFFER: the sections every elementary school runs, and
    the teacher's own configured and in-use secondary classes.  Suggestions
    only; the form accepts anything typed."""
    out = []
    if level in ("elementary", "mixed"):
        out += ELEM_SECTIONS
    if level != "elementary":
        try:
            from ui.ensembles import selectable_ensembles
            for c in selectable_ensembles(db, school_year, program_type,
                                          base_dir, include_empty=True):
                # An elementary school's own groups carry its name; the short
                # forms above already cover them.
                if ": Section " in c or c.endswith(": Choir"):
                    continue
                if c not in out:
                    out.append(c)
        except Exception:
            pass
    return out


def _instrument_suggestions(program_type, sites, level):
    from ui.ensembles import instruments_for, fifth_grade_instruments
    out = []
    progs = [s.get("program") or program_type for s in sites] or [program_type]
    for prog in progs:
        pool = (fifth_grade_instruments(prog) if level == "elementary"
                else instruments_for(prog))
        for i in pool:
            if i not in out:
                out.append(i)
    return out


def offer_blank_roster_form(parent, db, base_dir, school_year=None,
                            program_type=None):
    """Save Roka's blank roster form where the teacher chooses and open it
    in Excel.  Returns the path, or None if they backed out."""
    import roka_roster_xlsx
    program_type = program_type or _program_type(base_dir)
    sites = _sites(db)
    level = _level(sites)
    try:
        from ui.student_manager import RELATION_OPTIONS
        relations = list(RELATION_OPTIONS)
    except Exception:
        relations = None
    jazz = []
    if level != "elementary":
        try:
            from ui.ensembles import JAZZ_INSTRUMENTS
            jazz = list(JAZZ_INSTRUMENTS)
        except Exception:
            jazz = []
    start = os.path.join(os.path.expanduser("~"), "Downloads")
    if not os.path.isdir(start):
        start = os.path.expanduser("~")
    path = filedialog.asksaveasfilename(
        parent=parent, title="Save the blank roster form",
        initialdir=start, initialfile="Roka Student Roster Form.xlsx",
        defaultextension=".xlsx", filetypes=[("Excel", "*.xlsx")])
    if not path:
        return None
    try:
        roka_roster_xlsx.write_template(
            path, schools=[s["name"] for s in sites],
            classes=_class_suggestions(db, school_year, program_type,
                                       base_dir, level),
            instruments=_instrument_suggestions(program_type, sites, level),
            jazz_instruments=jazz, relations=relations, level=level)
    except Exception as e:
        Messagebox.show_error(f"Could not write the form:\n{e}",
                              title="Blank form", parent=parent)
        return None
    try:
        os.startfile(path)
    except Exception:
        Messagebox.show_info(f"The form is saved at:\n{path}\n\nOpen it in "
                             "Excel, fill it in, and save.",
                             title="Blank form", parent=parent)
    return path


def import_roster_file(parent, db, base_dir, school_year, site_id=None,
                       default_class=None, default_period=None, path=None,
                       on_synergy=None):
    """Read a filled-in roster form (or any student list with headings Roka
    knows) onto this year's roster, and say what happened.

    Asks for the file unless ``path`` is given.  A district class-list CSV
    is handed to ``on_synergy(path)`` when the caller has one (the Students
    window's own CSV import), and otherwise pointed at the right menu item.
    Returns the import summary, or None when nothing was imported."""
    import import_service
    import roka_roster_xlsx
    sites = _sites(db)
    where = next((s["name"] for s in sites if s["id"] == site_id), None)
    if path is None:
        start = os.path.join(os.path.expanduser("~"), "Downloads")
        if not os.path.isdir(start):
            start = os.path.expanduser("~")
        path = filedialog.askopenfilename(
            parent=parent, initialdir=start,
            title=f"Student list for {where}" if where else "Student list",
            filetypes=[("Roka roster form or CSV", "*.xlsx *.csv *.txt"),
                       ("All files", "*.*")])
        if not path:
            return None
    kind = import_service.detect_roster_format(path)
    if kind == "synergy":
        if on_synergy:
            on_synergy(path)
            return None
        Messagebox.show_info(
            "That is a district class list (one row per parent). Use "
            "Import ▸ Class roster (district CSV) for it.",
            title="District class list", parent=parent)
        return None
    if kind is None:
        Messagebox.show_error(
            "That file is not a student list Roka recognizes."
            "\n\nFill in Roka's blank roster form (Import ▸ Get a blank "
            "roster form) and choose that, or export the class list from "
            "Synergy as a CSV.",
            title="Could not import", parent=parent)
        return None
    try:
        students = roka_roster_xlsx.parse_roka_roster(
            path, [s["name"] for s in sites])
        if not students:
            Messagebox.show_info(
                "That file has no student rows. Fill in the Students sheet "
                "(one student per row) and save it, then try again.",
                title="Nothing to import", parent=parent)
            return None
        res = import_service.import_roster_rows(
            db, students, school_year, site_id=site_id,
            default_class=default_class, default_period=default_period)
    except Exception as e:
        Messagebox.show_error(f"That file could not be read.\n\n{e}",
                              title="Could not import", parent=parent)
        return None

    def n(count, word):
        return f"{count} {word}{'' if count == 1 else 's'}"

    lines = [f"{n(res['added'], 'student')} added to {school_year}"
             + (f" at {where}." if where and len(res["by_school"]) <= 1
                else ".")]
    if res["updated"]:
        lines.append(f"{n(res['updated'], 'student')} already on the roster: "
                     "blank fields filled in, classes merged.")
    if res["moved"]:
        lines.append(f"{n(res['moved'], 'student')} moved here from another "
                     "school.")
    if len(res["by_school"]) > 1:
        lines.append("")
        for name, count in res["by_school"].items():
            lines.append(f"  {name}: {count}")
    if res["skipped"]:
        lines.append("")
        lines.append(f"{n(res['skipped'], 'row')} skipped: the School column "
                     "names a school Roka does not have ("
                     + ", ".join(res["unknown_schools"]) + "). Add the "
                     "school in Settings, or fix the spelling, and import "
                     "again.")
    elif res["unknown_schools"]:
        lines.append("")
        lines.append("Not a school Roka has, so those rows went to "
                     f"{where or 'no school'}: "
                     + ", ".join(res["unknown_schools"]))
    if res["no_class"]:
        lines.append("")
        lines.append(f"{n(res['no_class'], 'student')} in no class yet. "
                     "Select them in the list and use Assign, or fill in "
                     "the form's class column and import it again.")
    Messagebox.show_info("\n".join(lines), title="Students imported",
                         parent=parent)
    return res
