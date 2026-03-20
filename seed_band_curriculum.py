"""
seed_band_curriculum.py — Generate a full year of realistic band curriculum data
for Chinook Middle School: Entry Band, Intermediate Band, and Advanced Band.

Each of the 178 school days gets a unique, pedagogically sequenced curriculum item
for each class — no cycling. Monthly topic lists are indexed directly to school days.

Usage:
    python seed_band_curriculum.py              # create classes (skip if already exist)
    python seed_band_curriculum.py --replace    # clear and re-seed curriculum items
    python seed_band_curriculum.py <path/to/db> [--replace]
"""

import os
import sys
import sqlite3
from datetime import datetime, timedelta, date
from database import Database

# ─── Bellevue SD 2025-2026 Calendar ──────────────────────────────────────────

SCHOOL_START = date(2025, 9, 3)
SCHOOL_END   = date(2026, 6, 18)

NO_SCHOOL_DATES = set()

def _add_range(start, end):
    d = start
    while d <= end:
        NO_SCHOOL_DATES.add(d)
        d += timedelta(days=1)

NO_SCHOOL_DATES.add(date(2025,  9,  1))             # Labor Day
NO_SCHOOL_DATES.add(date(2025, 11, 11))             # Veterans Day
_add_range(date(2025, 11, 26), date(2025, 11, 28))  # Thanksgiving break
_add_range(date(2025, 12, 22), date(2026,  1,  2))  # Winter break
NO_SCHOOL_DATES.add(date(2026,  1, 19))             # MLK Day
_add_range(date(2026,  2, 16), date(2026,  2, 20))  # Mid-winter break
_add_range(date(2026,  4,  6), date(2026,  4, 10))  # Spring break
NO_SCHOOL_DATES.add(date(2026,  5, 25))             # Memorial Day
NO_SCHOOL_DATES.add(date(2025, 10, 10))             # Teacher workday
NO_SCHOOL_DATES.add(date(2025, 10, 24))             # Conferences
NO_SCHOOL_DATES.add(date(2026,  3,  6))             # Teacher workday


def get_school_days():
    """Return list of school days (Mon–Fri, excluding holidays/breaks)."""
    days = []
    d = SCHOOL_START
    while d <= SCHOOL_END:
        if d.weekday() < 5 and d not in NO_SCHOOL_DATES:
            days.append(d)
        d += timedelta(days=1)
    return days


# ─── Concert Dates ────────────────────────────────────────────────────────────
# Day indices within school-day lists (0-based, within each month):
#   Fall Concert    Nov 6  = Nov school day 3  (4th school day of November)
#   Winter Concert  Dec 16 = Dec school day 11 (12th school day of December)
#   Large Group Fes Apr 17 = Apr school day 7  (8th school day of April)
#   Spring Concert  May 28 = May school day 18 (19th school day of May)
#   Solo & Ensemble Feb 28 = SATURDAY — not a school day

CONCERTS = {
    "Fall Concert":             date(2025, 11,  6),
    "Winter Concert":           date(2025, 12, 16),
    "Solo & Ensemble Festival": date(2026,  2, 28),
    "Large Group Festival":     date(2026,  4, 17),
    "Spring Concert":           date(2026,  5, 28),
}


# ─── Helpers ─────────────────────────────────────────────────────────────────

def ci(date_str, summary, activity_type, unit_name, notes=""):
    """Create a curriculum item dict."""
    return {
        "item_date":     date_str,
        "summary":       summary,
        "activity_type": activity_type,
        "unit_name":     unit_name,
        "is_locked":     1 if activity_type == "concert" else 0,
        "sort_order":    0,
        "notes":         notes,
    }


def _build_items(school_days, monthly_topics):
    """Map school days to per-month topic lists (one unique topic per school day)."""
    items = []
    counters = {}
    for day in school_days:
        key = (day.year, day.month)
        idx = counters.get(key, 0)
        topics = monthly_topics.get(key, [])
        if idx < len(topics):
            topic = topics[idx]
        else:
            topic = ("Continuation of current unit", "skill_building", "", "")
        items.append(ci(day.isoformat(), *topic))
        counters[key] = idx + 1
    return items


# ─── Entry Band (MU_101) ──────────────────────────────────────────────────────

def generate_entry_band(school_days):
    """Entry Band — Grade 6, Beginning level. Essential Elements Book 2.
    School day counts: Sep=20, Oct=21, Nov=16, Dec=15, Jan=19, Feb=15,
                       Mar=21, Apr=17, May=20, Jun=14  (Total=178)"""

    monthly = {

        # ── September 2025 (20 days): Fundamentals Review + EE2 Launch ───────
        (2025, 9): [
            ("Welcome back! Review instrument assembly, care, and posture; explain seating audition format; distribute EE Book 2", "skill_building", "Fundamentals Review", "Post class expectations; instrument supply checklist; introduce year performance plan"),
            ("Long tone warm-up: whole notes on concert B-flat; 4-count breathe, 4-count sustain; tone quality focus", "skill_building", "Fundamentals Review", "Model correct posture and embouchure; listen for matching pitch across sections"),
            ("Rhythm review: whole, half, quarter, eighth notes in 4/4; clap-count-play sequence from EE Book 1", "skill_building", "Fundamentals Review", "Clap patterns on stand, count aloud, then play on concert B-flat; no rushing"),
            ("Articulation review: single tongue 'tah' syllable; legato scale on B-flat major (EE2 p.2)", "skill_building", "Fundamentals Review", "Exaggerated legato; teach connected tone vs separated; play scale at q=72"),
            ("Eighth note patterns: 'ta-di' counting syllables; air pattern before playing; EE2 p.3 exercises", "skill_building", "Fundamentals Review", "Clap, tap on stand, then play; eighth notes on B-flat and F only; no rushing"),
            ("Seating audition: B-flat major scale from memory + 4-bar sight-read; teacher records results", "assessment", "Placement & Review", "Temporary seating during audition; placements announced next class; rubric: tone, scale, rhythm"),
            ("Staccato vs. legato contrast; accent marks introduced; EE2 pp.3-4 articulation patterns", "skill_building", "Fundamentals Review", "Four-note patterns: slur 4, tongue 4, accent 4; demonstrate each articulation style"),
            ("Announce seating results; EE2 pp.5-6: dotted half notes; ties across barlines; counting rules", "skill_building", "EE Book 2 Unit 1", "Clap dotted half patterns; play EE2 exercises slowly; subdivide every beat aloud"),
            ("EE2 pp.7-8: F major scale introduction; relate F major to B-flat; section fingering workshop", "skill_building", "EE Book 2 Unit 1", "Identify new fingerings by instrument type; play B-flat then F scale back to back"),
            ("EE2 pp.9-10: D.C. al Fine and repeat signs; map musical form on whiteboard before playing", "theory", "EE Book 2 Unit 1", "Draw roadmaps on board; class follows form map while playing; identify form in EE2 examples"),
            ("Sight-reading activity: Level 1 cards in 4/4, B-flat major; teach KATS scanning strategy", "sight_reading", "Sight-Reading Skills", "KATS: Key, Accidentals, Time, Scan; 30-second prep; play without stopping no matter what"),
            ("Dynamic contrast: pp, p, mp, mf, f, ff levels; teacher plays a dynamic, class echoes and matches", "skill_building", "EE Book 2 Unit 1", "Introduce Italian terms; apply to B-flat scale; discuss what dynamics do for music"),
            ("EE2 pp.11-13: Eighth rests and dotted quarter + eighth patterns; clap before playing", "skill_building", "EE Book 2 Unit 1", "Emphasize 'the and of the beat'; dotted quarter = long; following eighth = short"),
            ("EE2 pp.14-15: Cut time (2/2) introduction; conduct in 2; compare 4/4 vs 2/2 feel", "theory", "EE Book 2 Unit 1", "March around room to feel cut time; 2 long beats vs 4 short beats; march examples"),
            ("F major scale played assessment: goal q=80 without stopping; student self-assessment card", "assessment", "EE Book 2 Unit 1", "Students self-rate first; teacher confirms; improvement stamp for successful scale"),
            ("Distribute 'Chant and Jubilo' (arr. Saucedo, Hal Leonard Grade 1); full class read-through", "concert_prep", "Fall Concert Prep", "Identify key sig, time sig, tempo; highlight all rest measures; mark stop points in pencil"),
            ("'Chant and Jubilo' mm.1-16: clap rhythms, identify articulation, play at half tempo q=76", "concert_prep", "Fall Concert Prep", "Section by section; count eighth rests carefully; pencil marks on trouble spots"),
            ("'Chant and Jubilo' mm.17-32: clap first then play; brass check pitch on final B-flat chord", "concert_prep", "Fall Concert Prep", "Metronome q=76; listen across ensemble; tune final chord; clean unified cutoff"),
            ("Distribute 'Prehistoric Suite' mvt.1 (FJH Music, Grade 1); full read-through; identify challenges", "concert_prep", "Fall Concert Prep", "Mark key changes; note percussion cues; circle rhythms that look tricky in pencil"),
            ("'Prehistoric Suite' mvt.1 mm.1-24: slow drill q=80; section cue identification and entrances", "concert_prep", "Fall Concert Prep", "Section leaders model entrances; restart from beginning once; listen for section cues"),
        ],

        # ── October 2025 (21 days): Fall Concert Prep + EE2 Unit 2 ──────────
        (2025, 10): [
            ("'Chant and Jubilo' mm.1-32 run at q=88 + 'Prehistoric Suite' mm.1-24 back to back", "concert_prep", "Fall Concert Prep", "Circle 2 most challenging measures in each piece after run; target them next class"),
            ("EE2 pp.16-17: Key of C major; natural sign review; C major scale fingering workshop by section", "skill_building", "EE Book 2 Unit 2", "Relate C major to B-flat; identify naturals; play scale slowly by instrument family"),
            ("C major scale full ensemble with tuner; adjust embouchure for open-tone pitches by section", "skill_building", "EE Book 2 Unit 2", "Sustain each pitch 4 beats; listen for matching pitch; use Tonal Energy app if available"),
            ("'Prehistoric Suite' mvt.1 mm.25-48: rhythmic precision; brass cue identification in context", "concert_prep", "Fall Concert Prep", "Isolate hard measures; slow to 70% tempo; rebuild speed one repetition at a time"),
            ("EE2 pp.18-19: Syncopation introduction; clap 'push' rhythm patterns before playing", "skill_building", "EE Book 2 Unit 2", "Syncopation = note pushed onto the 'and'; clap on stand first; then air band; then play"),
            ("'Chant and Jubilo' full movement at q=88: no stopping; circle problem spots after in pencil", "concert_prep", "Fall Concert Prep", "Full ensemble m.1 to end; pencils down while playing; write problem spots immediately after"),
            ("Section balance workshop: melody vs. accompaniment; melody at mf, accompaniment at mp", "concert_prep", "Fall Concert Prep", "Demonstrate balance; apply to both fall pieces; melody leads — accompaniment supports"),
            ("'Prehistoric Suite' mvt.1 full movement at target tempo; brass intonation on open intervals", "concert_prep", "Fall Concert Prep", "Focus on last 8 bars; clean ending; long tone on final chord 4 beats together"),
            ("Sight-reading day: Level 2 exercises in F major and C major; timing strategy review", "sight_reading", "Sight-Reading Skills", "KATS strategy review; 30-sec scan; no-stopping rule applies; debrief what was hard"),
            ("Concert etiquette: walking onto stage, tuning order, unified bow, walking off stage protocol", "concert_prep", "Fall Concert Prep", "Walk through procedure in band room; assign section leaders to lead their sections"),
            ("Full concert mock run: both pieces + transitions in mock-stage room arrangement", "concert_prep", "Fall Concert Prep", "Chairs in performance layout; from entrance to exit; record if possible for review"),
            ("Playing assessment: B-flat scale + 8-bar excerpt from 'Chant and Jubilo'; rubric scoring", "assessment", "Fall Concert Prep", "Rubric: tone (5), rhythm (5), dynamics (5), posture (5); rotate sections during rehearsal"),
            ("'Chant and Jubilo' phrase shaping: identify climax notes in each phrase; add crescendo marks", "concert_prep", "Fall Concert Prep", "Conductor shows phrase arches on board; students mark with pencil; sing before playing"),
            ("'Prehistoric Suite' percussion coordination drill; woodwind/brass balance with percussion", "concert_prep", "Fall Concert Prep", "Percussion section leads; winds listen and follow percussion pulse; metro q=96"),
            ("Woodwind sectional: tone production and intonation in 'Chant and Jubilo' A section", "concert_prep", "Fall Concert Prep", "Tune thirds and fifths with drone; hold sustained notes 4 beats; adjust and match pitch"),
            ("Brass sectional: unified attacks in 'Prehistoric Suite'; tune B-flat open tones with drone", "concert_prep", "Fall Concert Prep", "Trumpet/trombone/tuba: unison B-flat with drone; add voices; listen for beats"),
            ("Full dress run: both pieces back-to-back; conductor eye contact practice; no stopping", "concert_prep", "Fall Concert Prep", "No stopping; perform with audience posture; note all dynamic changes made or missed"),
            ("'Chant and Jubilo' final polish: every dynamic marking observed; clean releases on fermatas", "concert_prep", "Fall Concert Prep", "Identify every dynamic in score; practice fade at end; unified cutoff on final chord"),
            ("'Prehistoric Suite' final polish: articulation accuracy; tempo stability through fast passages", "concert_prep", "Fall Concert Prep", "Even eighth notes; no rushing mm.32-40; use drum click track for time stability"),
            ("Concert week: uniform checklist, music folder order, equipment check, call time review", "concert_prep", "Fall Concert Prep", "Distribute uniform checklist; folder order confirmed; call time 6:00 PM announced"),
            ("Final full run-through; mental performance prep: deep breaths and concert visualization", "concert_prep", "Fall Concert Prep", "Run both pieces once; positive pep talk; reinforce confidence; they are ready tonight"),
        ],

        # ── November 2025 (16 days): Fall Concert Week + Post-Concert + Winter Prep
        (2025, 11): [
            ("Pre-concert final rehearsal: run both pieces once cleanly; only critical last-minute fixes", "concert_prep", "Fall Concert Prep", "Full ensemble; no new changes; fix only obvious issues; end with positive energy"),
            ("Concert logistics walk-through: stage positions confirmed; equipment check; music order", "concert_prep", "Fall Concert Prep", "Walk through stage if possible; instrument readiness check; music folders confirmed"),
            ("Final dress prep: uniforms confirmed; brief warm-up run; save energy for tonight", "concert_prep", "Fall Concert Prep", "Warm-up only; no full pieces; save energy; pep talk and positive energy building"),
            ("FALL CONCERT — daytime: brief review; reminder of 6:00 PM call time for tonight", "concert", "Fall Concert Prep", "Call time 6:00 PM; concert 7:00 PM; posture, stage presence, listening are the focus"),
            ("Post-concert debrief: listen to recording clip; self-evaluation form (1-5 stars each skill)", "flex", "Post-Concert", "What went well? What to do differently? Write 3 specific improvement ideas for winter"),
            ("Recovery day: student-requested music; sight-read a fun pops arrangement together", "flex", "Post-Concert", "Film theme or pop chart; sight-read for fun; no pressure; enjoy playing together"),
            ("EE2 pp.22-23: 6/8 time introduction; feel pulse in 2 vs. 6; practice conducting in 6", "theory", "EE Book 2 Unit 3", "Clap in 6 first; find the 'big 2' feel; compare 3/4 to 6/8 subdivision; EE2 examples"),
            ("6/8 time practice: 'Greensleeves' EE2 p.24; count subdivisions aloud while playing", "skill_building", "EE Book 2 Unit 3", "Slow tempo; count 1-2-3-4-5-6 aloud; feel big beats on 1 and 4; no rushing"),
            ("Chromatic scale introduction: B-flat up one octave; whole notes; slow; name each note", "skill_building", "Scale Mastery", "One step at a time; name each chromatic pitch; slide rule for trombones; tuning focus"),
            ("Winter concert music: 'Hanukkah Festival' (arr. Higgins, Grade 1); full read-through", "concert_prep", "Winter Concert Prep", "Discuss Hanukkah briefly; identify time sig changes; mark all dynamics; circle hard spots"),
            ("'Hanukkah Festival' mm.1-32: A section melody focus; flute/clarinet leads; balance drill", "concert_prep", "Winter Concert Prep", "Melody at mf; accompaniment at mp; demonstrate difference; then play"),
            ("Distribute 'Jingle Bells Fantasy' (arr., Grade 1): full read-through; mark tricky spots", "concert_prep", "Winter Concert Prep", "Note swing feel indication; discuss jazz vs. straight eighth notes; mark trouble spots"),
            ("'Jingle Bells Fantasy' swing feel: clap straight vs. swing eighths; tongue lightly on swing", "concert_prep", "Winter Concert Prep", "Demonstrate swing with teacher; class claps along; then play mm.1-16 with swing feel"),
            ("Full winter concert program run: both pieces; identify top 3 fixes for each piece", "concert_prep", "Winter Concert Prep", "No stopping; pencils down; circle rough measures after; write priority fix list"),
            ("EE2 pp.25-26: Review dotted quarter + eighth, 6/8 subdivisions, and syncopation patterns", "skill_building", "EE Book 2 Unit 3", "Comprehensive rhythmic review; flashcards for patterns; clap, count, then play"),
            ("'Hanukkah Festival' B section rehearsal; brass sustained chord tuning with drone", "concert_prep", "Winter Concert Prep", "B section = new key area; brass sustain chords; woodwinds carry melody; balance"),
        ],

        # ── December 2025 (15 days): Winter Concert Prep ─────────────────────
        (2025, 12): [
            ("'Jingle Bells Fantasy' opening gallop rhythm: isolate mm.1-8; clap then play slowly", "concert_prep", "Winter Concert Prep", "Gallop = long-short dotted eighth + sixteenth; count subdivisions; drums set tempo"),
            ("'Hanukkah Festival' full run at performance tempo; mark all unresolved balance issues", "concert_prep", "Winter Concert Prep", "Melody at least one dynamic level above accompaniment; check every section"),
            ("Woodwind sectional: 'Hanukkah Festival' melodic line with expression and intonation focus", "concert_prep", "Winter Concert Prep", "Tune within section using drone; add crescendo/decrescendo; sing first then play"),
            ("'Jingle Bells Fantasy' mm.17-32: percussion coordination; bells entrance timing check", "concert_prep", "Winter Concert Prep", "Bells and chimes: soft mallets; tune bell chords; enter precisely on correct beats"),
            ("Full winter concert run: performance order; practice between-piece transitions and retuning", "concert_prep", "Winter Concert Prep", "Retune between pieces; silence between; conductor waits for complete silence before next piece"),
            ("EE2 pp.27-28: Slurs and tongued passages contrast; 'slur 2, tongue 2' alternating patterns", "skill_building", "EE Book 2 Unit 3", "Alternate slur/tongue patterns build control; apply to EE2 exercises; hear the difference"),
            ("'Hanukkah Festival' balance workshop: remove melody to hear harmony; add back; compare", "concert_prep", "Winter Concert Prep", "Accompaniment alone first; identify chord function; add melody back; listen for balance"),
            ("Sight-reading: Level 2 holiday-themed exercise in 3/4 time; apply 6/8 knowledge", "sight_reading", "Sight-Reading Skills", "KATS strategy; 30-second scan; look for rhythms similar to 6/8; play without stopping"),
            ("Playing quiz: 'Jingle Bells Fantasy' mm.1-16 accuracy check and tone quality rubric", "assessment", "Winter Concert Prep", "Rubric: rhythmic accuracy (5), tone quality (5), dynamics (5); rotate by section"),
            ("Full concert dress run: uniform review; both pieces polished back-to-back", "concert_prep", "Winter Concert Prep", "Formal run from entrance to exit; no talking between pieces; full performance posture"),
            ("Winter concert final polish: clean all entrances; dynamics correct; final chord in tune", "concert_prep", "Winter Concert Prep", "Target: first entrance of each piece; final chord tuning; all fermatas together"),
            ("WINTER CONCERT — daytime class: brief warm-up only; reminder of 6:00 PM call time", "concert", "Winter Concert Prep", "Call time 6:00 PM; concert 7:00 PM; brief warm-up only; save energy for tonight"),
            ("Post-concert debrief: watch recording; compare tone and balance growth from Fall Concert", "flex", "Post-Concert", "How did we improve since Fall? List 3 specific improvements; set January goals together"),
            ("Theory review activity: music bingo with key signatures, rhythm patterns, Italian terms", "theory", "EE Book 2 Unit 3", "Bingo cards with note values, key signatures, Italian terms; prizes for winners"),
            ("Winter break listening: what makes a professional wind band recording great?", "listening", "Music Appreciation", "Listen to a professional band holiday recording; compare blend and tone to our concert"),
        ],

        # ── January 2026 (19 days): New Semester + EE2 Unit 4 ────────────────
        (2026, 1): [
            ("Welcome back! Embouchure reset after break; long tones from low register to high register", "skill_building", "Technique Builder", "Lips stiff after break; slow long tones at mp; no forcing; rebuild carefully over 10 min"),
            ("Scale review: B-flat, E-flat, F, C major at q=80; identify which scales need most work", "skill_building", "Scale Mastery", "Compare to December level; note which scales are strongest and weakest; set targets"),
            ("EE2 pp.29-30: A-flat major scale introduction; 4 flats; relate to E-flat major", "skill_building", "EE Book 2 Unit 4", "A-flat = E-flat + add D-flat and A-flat; whole notes on each pitch first; slow"),
            ("A-flat major fingering workshop by section; slow practice; ear training on A-flat scale", "skill_building", "EE Book 2 Unit 4", "Section by section; check fingerings; play with drone on A-flat; find the center pitch"),
            ("Sixteenth note introduction: 'ta-ka-di-mi' counting; clap groups of four; no instrument yet", "skill_building", "EE Book 2 Unit 4", "Clap 4 on one beat; say ta-ka-di-mi; combine with quarter notes; build patterns"),
            ("Sixteenth notes on instruments: EE2 pp.31-32 exercises; metronome on every quarter beat", "skill_building", "EE Book 2 Unit 4", "Start at q=60; play 4 sixteenth notes per beat; even subdivision; no rushing"),
            ("Sixteenth + eighth note combo patterns; avoid rushing; metronome required throughout", "skill_building", "EE Book 2 Unit 4", "Pattern: 4 sixteenths then 2 eighths then quarter; repeat sequence; EE2 exercises"),
            ("Sight-reading Level 2: C major and F major exercises; 2-minute prep strategy review", "sight_reading", "Sight-Reading Skills", "Two minutes to scan; call out potential problems aloud; play through without stopping"),
            ("A-flat major scale quiz (played): goal q=80; student self-assessment before teacher checks", "assessment", "EE Book 2 Unit 4", "Students rate themselves first; compare to teacher assessment; discuss growth mindset"),
            ("EE2 pp.33-34: Triplets introduction; triplet feel vs. eighth note pairs; ta-ki-da counting", "skill_building", "EE Book 2 Unit 4", "Clap triplets; compare to two-against-three; relate to swing eighths they already know"),
            ("Mid-year self-assessment worksheet: rate each skill 1-5; set goals for spring semester", "flex", "Mid-Year Review", "Tone, rhythm, scales, listening, concert participation; students honest with themselves"),
            ("Mid-year playing assessment: B-flat scale + 8-bar excerpt from winter concert piece", "assessment", "Mid-Year Assessment", "Rubric: tone (5), rhythm (5), dynamics (5), sight-reading (5); record each student"),
            ("EE2 pp.35-36: Compound rhythms review; dotted eighth + sixteenth patterns; counting", "skill_building", "EE Book 2 Unit 4", "Ta-a-ka for dotted eighth; feel the lopsided quality; apply to march-style excerpts"),
            ("Composition mini-project: write 4 measures in 4/4, B-flat major (due in one week)", "composition", "Creative Music", "Use quarter, half, eighth notes; include 2 dynamic marks; write on staff paper"),
            ("EE2 pp.37-38: Key of D-flat major (concert); 5 flats; workshop by section", "skill_building", "EE Book 2 Unit 4", "D-flat = A-flat + D-flat + G-flat; relate to keys known; slow whole notes by section"),
            ("Listening activity: middle school band recording vs. professional wind ensemble on same piece", "listening", "Music Appreciation", "Differences in tone, balance, precision? Write 3 observations to share with class"),
            ("D-flat major scale full ensemble; sustain each scale degree 4 beats with drone", "skill_building", "EE Book 2 Unit 4", "Whole notes; listen across ensemble; match pitch; relate to EE2 exercises in D-flat"),
            ("Composition share: each student plays their 4-bar composition; class responds positively", "composition", "Creative Music", "Positive feedback only; discuss interesting rhythms; class votes on most creative idea"),
            ("Scale speed challenge: B-flat, E-flat, F, C major; friendly competition to reach q=100", "skill_building", "Scale Mastery", "Record current tempos on scale ladder; celebrate improvement; set next target tempo"),
        ],

        # ── February 2026 (15 days): S&E Festival Prep + Spring Concert Intro ─
        (2026, 2): [
            ("Solo & Ensemble Festival info: what is S&E? Solo vs. duet; Level 1 solos explained", "concert_prep", "Festival Prep", "Show last year's program; discuss scoring; sign-up options for all skill levels"),
            ("Festival literature browsing: Rubank Elementary solos displayed; students choose piece", "concert_prep", "Festival Prep", "Students try a few measures of each option; make selection; order music if needed"),
            ("S&E festival rehearsal: pairs/trios in practice rooms; teacher coaches each group rotation", "concert_prep", "Festival Prep", "Rotate 5 min per group; focus on intonation and rhythm accuracy; one fix per group"),
            ("EE2 pp.39-40: D minor scale and relative minor concept; compare D minor to F major", "theory", "EE Book 2 Unit 5", "Natural minor scale pattern; D minor = same as F major starting on D; play both"),
            ("Major vs. minor ear training: play major scale then parallel minor; identify by ear", "listening", "EE Book 2 Unit 5", "Play B-flat major then B-flat minor; which sounds happy? Which sounds sad? Discuss"),
            ("Full band warm-up routine formalized: 10-minute standard warm-up every class from now on", "skill_building", "Technique Builder", "Routine: long tones (2 min), scale (2 min), chorale (2 min), rhythm (2 min), sight (2 min)"),
            ("S&E coaching day: individual 5-minute rotations with teacher; technique and expression focus", "concert_prep", "Festival Prep", "One-on-one feedback; mark issues in music; one change at a time per student or group"),
            ("Spring concert: 'Afterburn' by Brian Balmages (Grade 1.5); full read-through", "concert_prep", "Spring Concert Prep", "High energy; note the fanfare opening; identify exciting passages; read without stopping"),
            ("'Afterburn' mm.1-16: opening fanfare; brass unison attacks; woodwind answer phrases clean", "concert_prep", "Spring Concert Prep", "Brass attack together; woodwinds answer cleanly; balance between instrument groups"),
            ("'Afterburn' mm.17-32: B section woodwind running passages at slow tempo q=80", "concert_prep", "Spring Concert Prep", "Slow first; subdivide each beat; gradually increase tempo each repetition; no rushing"),
            ("Post-mid-winter-break warm-up: scale review; embouchure check; re-establish ensemble blend", "skill_building", "Technique Builder", "Long tones; scales at q=80; chorale; reset breath support after 5-day break"),
            ("S&E intensive final coaching: last session before Saturday festival; expression priority", "concert_prep", "Festival Prep", "Final technical touches; push for musical communication beyond just notes and rhythms"),
            ("'Afterburn' full read-through at slow tempo; circle all problem measures for next class", "concert_prep", "Spring Concert Prep", "Metro at q=90; circle trouble spots consistently; note them for next week's work"),
            ("Distribute 'An Irish Farewell' (arr. Swearingen, Grade 1); read-through; mark lyrical lines", "concert_prep", "Spring Concert Prep", "Contrast piece; slow and lyrical; identify phrases; mark breath points at phrase ends"),
            ("S&E Festival logistics: who participates Saturday? Performance expectations and location", "flex", "Festival Prep", "Review festival schedule; encourage all participants; professional behavior discussion"),
        ],

        # ── March 2026 (21 days): Spring Concert Building ────────────────────
        (2026, 3): [
            ("'Afterburn' mm.1-24: percussion isolation then add winds; build layers one at a time", "concert_prep", "Spring Concert Prep", "Percussion alone first; winds add when rhythm is locked; build texture step by step"),
            ("'An Irish Farewell' mm.1-24: lyrical melody; long phrase breath marks; breath support focus", "concert_prep", "Spring Concert Prep", "Sing melody first; then play; one breath per phrase; sustained and warm open tone"),
            ("EE2 pp.41-42: Key of G major introduced; F-sharp fingering workshop by instrument family", "skill_building", "EE Book 2 Unit 5", "G major = C major + F-sharp; woodwind F-sharp fingerings reviewed; play scale at q=80"),
            ("G major scale full ensemble with drone; ear training on each scale degree", "skill_building", "EE Book 2 Unit 5", "Sustain each pitch 4 beats; match pitch across ensemble; relate to EE2 G major exercises"),
            ("'Afterburn' mm.25-48: C section full ensemble at target tempo q=120; no stopping", "concert_prep", "Spring Concert Prep", "All parts together; no stopping; circle after; rebuild problem measures one at a time"),
            ("'An Irish Farewell' mm.25-end: expressiveness; sing each phrase then play with same emotion", "concert_prep", "Spring Concert Prep", "Ask: what story does this melody tell? Let your tone reflect that answer"),
            ("Sight-reading challenge day: Level 2 in various keys including G major and C major", "sight_reading", "Sight-Reading Skills", "Rotate through 4 exercises; emphasize KATS; time the 30-second scan; debrief each"),
            ("Theory: key signature written quiz — identify B-flat, E-flat, F, C, G major by sight", "assessment", "EE Book 2 Unit 5", "Written quiz: draw and identify key signatures; 10 questions; 10 minutes; review after"),
            ("Both spring pieces back-to-back; annotate transition cues and any equipment changes", "concert_prep", "Spring Concert Prep", "Transitions: retune, flip music, reset; run at performance pace no matter what"),
            ("'Afterburn' detail work: every dynamic and accent mark identified; circle unplayed markings", "concert_prep", "Spring Concert Prep", "Every forte is a real forte; every accent is a real accent; dynamics matter greatly"),
            ("'An Irish Farewell' balance workshop: melody stands at mf; accompaniment at pp", "concert_prep", "Spring Concert Prep", "Melody = emotional center; accompaniment = warm backdrop; demonstrate the difference"),
            ("Woodwind sectional: 'Afterburn' running passages — rhythmic accuracy goal q=112", "concert_prep", "Spring Concert Prep", "Isolate woodwind passage; subdivide; slow practice to q=96; build toward q=112"),
            ("Brass sectional: 'Afterburn' attacks and releases; 'Irish Farewell' chord tuning with drone", "concert_prep", "Spring Concert Prep", "Attacks together on beat 1; releases on conductor cutoff; tune chords by intervals"),
            ("Full concert run-through: both pieces with transitions; record if possible; listen next class", "concert_prep", "Spring Concert Prep", "Record today; listen next class; class identifies top 3 improvements needed"),
            ("EE2 pp.43-44: Review chromatic scale up full range; B-flat chromatic ascending and descending", "skill_building", "Scale Mastery", "Chromatic both directions; quarter notes at q=72; name each chromatic pitch aloud"),
            ("Large Group Festival preview: what is the festival? Sight-reading procedure explained", "concert_prep", "Festival Prep", "Review festival format; sight-reading = 30-second scan then play; discuss strategies"),
            ("'Afterburn' final section: climax measure accuracy; strong ending chord with full energy", "concert_prep", "Spring Concert Prep", "Work climax passage until clean; final chord: all together, forte, held until cutoff"),
            ("'An Irish Farewell' expressiveness workshop: go beyond the notes; connect with the audience", "concert_prep", "Spring Concert Prep", "Can you hear when someone just plays vs. truly expresses? Aim for the expression"),
            ("Spring concert full run: no stopping; performance-style; time the full program", "concert_prep", "Spring Concert Prep", "Run from entrance to exit; note total time; discuss pacing between pieces"),
            ("Playing test: B-flat scale + excerpt from 'An Irish Farewell' mm.1-16", "assessment", "Spring Concert Prep", "Rubric: tone (5), rhythm (5), expression/dynamics (5); record student for feedback"),
            ("EE2 pp.45-46: Advanced rhythms and compound meter review; comprehensive skills check", "skill_building", "EE Book 2 Unit 6", "Mix of all rhythms learned; challenge level; clap first then play; identify errors"),
        ],

        # ── April 2026 (17 days): Large Group Festival + Concert Polish ───────
        (2026, 4): [
            ("Festival sight-reading practice: cold read in 2/4 and 4/4 following festival procedure", "sight_reading", "Festival Prep", "Time the scan (30 sec); brief class discussion; play through once; grade the attempt"),
            ("Large Group Festival prep: full program run at performance level; record and listen back", "concert_prep", "Festival Prep", "No stopping; perform as if judges present; record; listen; identify top 3 issues to fix"),
            ("'Afterburn' technique: articulation consistency at performance tempo q=132", "concert_prep", "Festival Prep", "Every articulation clean at performance tempo; use metronome click track throughout"),
            ("Post-spring-break warm-up: scale review; embouchure re-check; ensemble focus rebuilt", "skill_building", "Technique Builder", "Long tones first; B-flat through G major; refocus on blend, balance, and listening"),
            ("Large Group Festival logistics: stage setup, sight-reading room, bus schedule, attire", "concert_prep", "Festival Prep", "Complete logistics review; assign responsibilities; professional behavior discussion"),
            ("Full program mock festival: perform for invited class; mutual critique afterwards", "concert_prep", "Festival Prep", "Real audience changes energy; debrief: what felt different with an audience present?"),
            ("Final festival details: every dynamic, breath mark, and release unified across ensemble", "concert_prep", "Festival Prep", "Last run before festival; fix final three measures of each piece; confidence building"),
            ("LARGE GROUP FESTIVAL — performance day (bus trip to festival site)", "concert", "Festival Prep", "Depart 8:00 AM; warm up off-site; perform program + sight-reading; return by noon"),
            ("Post-festival debrief: review judges' score sheets and comments together as a class", "flex", "Post-Festival", "Read each judge comment; celebrate rating; identify one area to improve for spring concert"),
            ("Fun day: student-requested pops arrangements; sight-read movie themes for enjoyment", "flex", "Post-Festival", "Students suggest pieces; vote on top 3; sight-read without pressure; just enjoy playing"),
            ("EE2 pp.47-48: Comprehensive review of all keys, rhythms, and musicianship concepts", "skill_building", "EE Book 2 Unit 6", "Review all key signatures; play each scale; review all rhythm types from EE2"),
            ("Spring concert refinement: apply festival feedback to each piece; specific problem measures", "concert_prep", "Spring Concert Prep", "Take judge comments; address each in rehearsal; confirm improvements are implemented"),
            ("Introduce third spring piece if ready: march or similar Grade 1.5 selection", "concert_prep", "Spring Concert Prep", "March form: intro, 1st strain, 2nd strain, trio; read through; mark form sections"),
            ("Three-piece concert run: time the program; fix all transitions; confirm running order", "concert_prep", "Spring Concert Prep", "Total program 12-14 min; transitions under 30 seconds each; running order confirmed"),
            ("EE2 end-of-book review: play through examples from all units; check concept mastery", "skill_building", "EE Book 2 Unit 6", "Comprehensive play-through; students self-assess which units they mastered best"),
            ("Scale mastery target: B-flat, E-flat, F, C, G, A-flat major at q=96; progress check", "assessment", "Scale Mastery", "Individual scale checks; record progress on ladder; set goal to reach q=100 by May"),
            ("Full spring concert program practice with stage arrangement; rehearse stage movement", "concert_prep", "Spring Concert Prep", "Chairs in concert layout; full run; walk-on, seating, tuning, bow, walk-off rehearsed"),
        ],

        # ── May 2026 (20 days): Spring Concert + Year End ────────────────────
        (2026, 5): [
            ("Spring concert full rehearsal: all three pieces in performance order; no stopping rule", "concert_prep", "Spring Concert Prep", "Full ensemble from entrance to exit; annotate issues after; prioritize top fixes"),
            ("Detail rehearsal: each piece's two weakest passages isolated and slowly drilled", "concert_prep", "Spring Concert Prep", "Use pencil marks from festival run; slow drill; rebuild tempo; full ensemble applies"),
            ("Sectional day: woodwinds, brass, and percussion each polish their own roles independently", "concert_prep", "Spring Concert Prep", "Sections in separate rooms; section leaders run warm-ups; teacher rotates rooms"),
            ("Year-end scale assessment announced: all 6 major scales; practice plan distributed", "skill_building", "Year-End Assessment", "Review B-flat, E-flat, F, C, G, A-flat; practice guide sent home; test next week"),
            ("'Afterburn' concert-ready run: every dynamic, accent, and cutoff as marked throughout", "concert_prep", "Spring Concert Prep", "No stopping; circle what was missed; fix immediately after run; full energy throughout"),
            ("'An Irish Farewell' final expressiveness: make every phrase tell a complete story", "concert_prep", "Spring Concert Prep", "Review the 'journey' of the piece; what emotion does each section convey to the audience?"),
            ("Year-end scale assessment: B-flat, E-flat, F, C, G, A-flat major on record", "assessment", "Year-End Assessment", "Individual assessments during warm-up; rubric: q=96 minimum, two-octave attempt"),
            ("Three-piece concert rehearsal: full program timing check; transitions polished", "concert_prep", "Spring Concert Prep", "Record total time; under 14 min; note transition length; rehearse bowing procedure"),
            ("Dress rehearsal for Spring Concert: full concert attire; bowing; all transitions", "concert_prep", "Spring Concert Prep", "Concert clothes required; treat as real concert; no do-overs; perform all the way through"),
            ("Spring concert final polish: no new changes; confidence-building run-through only", "concert_prep", "Spring Concert Prep", "Run through once; celebrate what sounds great; reinforce positives only today"),
            ("Concert week: equipment, uniform, and music folder final check; call time confirmed", "concert_prep", "Spring Concert Prep", "Everything ready by today; no changes after this; visualize a great concert tonight"),
            ("Last full rehearsal before Spring Concert: brief and positive; trust the preparation", "concert_prep", "Spring Concert Prep", "Run each piece once; positive reinforcement only; end class on maximum confidence"),
            ("Instrument maintenance day: oil valves, grease slides, swab woodwinds, tighten hardware", "flex", "Year End", "Hands-on instrument care; each student services own instrument; report damage to teacher"),
            ("Pre-concert mental preparation: visualization exercises and team breathing", "concert_prep", "Spring Concert Prep", "Guide 5-minute visualization: play perfectly; bow; audience applauds; feel the success"),
            ("Spring concert final confirmation: call time, uniform, music order, instrument check", "concert_prep", "Spring Concert Prep", "Final confirmation of all logistics; answer last questions; folders confirmed complete"),
            ("Spring concert last class: brief positive warm-up and pep talk before tonight", "concert_prep", "Spring Concert Prep", "Brief warm-up; quick run of first 8 bars of each piece; encourage and dismiss with energy"),
            ("Post-spring-concert debrief: watch concert recording; celebrate the year's growth", "flex", "Year End", "Watch recording; identify 3 things improved from Fall Concert; cheer each other on"),
            ("Year-end awards: most improved, outstanding musician, section MVPs announced", "flex", "Year End", "Teacher-selected awards; celebrate all contributors; group photo taken together"),
            ("SPRING CONCERT — evening performance tonight", "concert", "Spring Concert Prep", "Call time 6:00 PM; concert 7:00 PM; dress code enforced; all music folders organized"),
            ("Summer practice guide distributed; instrument damage check; end-of-year goodbyes", "flex", "Year End", "Summer scale sheet; instrument tags for repairs; goodbyes and excitement for next year"),
        ],

        # ── June 2026 (14 days): Year-End Activities ─────────────────────────
        (2026, 6): [
            ("Music games: rhythm bingo with prizes; class competes to complete card first", "flex", "Year End", "Bingo cards with note values, key signatures, Italian terms; small prizes for winners"),
            ("Play-along day: YouTube backing tracks for fun songs; informal jam session", "flex", "Year End", "Students choose 2 songs; find parts; play along with backing track; no pressure at all"),
            ("Year-end reflection worksheet: what I learned + goals for next year in Intermediate Band", "flex", "Year End", "Written: top 3 skills learned, top 3 improvements, goals for Intermediate Band next fall"),
            ("Music history: how concert band music evolved from military bands to modern wind ensemble", "listening", "Music Appreciation", "Watch clips across the decades; trace instrumentation and style evolution over time"),
            ("Try a different instrument day: swap with neighbor; explore another instrument world", "flex", "Year End", "No pressure; explore embouchure and fingerings; teacher helps; discussion after class"),
            ("Sight-reading Olympics: team competition with increasingly difficult sight-reading rounds", "sight_reading", "Year End", "Teams of 4; bracket-style competition; celebrate bravery and accuracy equally"),
            ("Student showcase: volunteer students perform their S&E solo or self-chosen piece", "flex", "Year End", "Celebrate musical growth; supportive audience; teacher facilitates peer appreciation"),
            ("Instrument return and care day: clean, case, tag, and store all school instruments", "flex", "Year End", "Instrument condition form; report any damage; return all school music and books"),
            ("Final celebration: watch a professional wind band concert clip; class choice of recording", "flex", "Year End", "Watch a Tokyo Kosei or similar professional performance; discuss what stands out"),
            ("Music theory review game: Kahoot with all theory concepts learned this year", "theory", "Year End", "Key signatures, rhythm values, Italian terms, musical symbols; fun competitive review"),
            ("Creative music day: improvise a melody over simple backing track using B-flat scale", "composition", "Year End", "No wrong notes on the scale; experiment with rhythm and phrasing; bravery points for soloists"),
            ("Listening comparison: favorite piece from year vs. first-day recording; growth discussion", "listening", "Year End", "Play September recording and spring concert recording side by side; celebrate how far they came"),
            ("Professional pathway preview: high school band, honor ensembles, all-state; how to prepare", "flex", "Year End", "Discuss opportunities; encourage continued growth; resources and audition prep info"),
            ("Last day: summer packet, instrument check-in, locker clean-out, and goodbyes", "flex", "Year End", "Return all school materials; final group photo; goodbyes; excitement for Intermediate Band"),
        ],
    }

    return _build_items(school_days, monthly)


# ─── Intermediate Band (MU_201) ───────────────────────────────────────────────

def generate_intermediate_band(school_days):
    """Intermediate Band — Grade 7, Intermediate level. EE Book 2-3 + FSP.
    School day counts: Sep=20, Oct=21, Nov=16, Dec=15, Jan=19, Feb=15,
                       Mar=21, Apr=17, May=20, Jun=14  (Total=178)"""

    monthly = {

        # ── September 2025 (20 days): Placement + FSP Launch + Fall Repertoire ─
        (2025, 9): [
            ("Seating audition: B-flat major scale from memory + 4-bar sight-read; teacher records results", "assessment", "Placement & Review", "Rubric: tone (5), scale accuracy (5), rhythm reading (5); chair placements Friday"),
            ("Chair placements announced; review ensemble expectations, rehearsal etiquette, leadership roles", "skill_building", "Placement & Review", "Section leaders introduced; mutual accountability discussed; rehearsal procedures posted"),
            ("Daily warm-up routine established: Remington exercises (brass), long tones (WW), rudiments (perc)", "skill_building", "Warm-Up Mastery", "10-minute daily routine; teacher models each component; this routine runs all year"),
            ("Scale review: B-flat, E-flat, F, C major at q=100; two octaves where possible", "skill_building", "Warm-Up Mastery", "Scale ladder posted; compare to entry level; set spring tempo targets for each scale"),
            ("EE Book 2 review: pp.28-32 syncopation, dotted patterns, and 6/8; rhythm workshop", "skill_building", "Foundations Review", "Rhythm dictation: teacher plays, students notate; discuss air patterns before playing"),
            ("Introduce 'Foundations for Superior Performance' (FSP) warm-up book: chorales #1-3", "skill_building", "Warm-Up Mastery", "Hold each chord 4 beats; tune across ensemble; adjust in real time; listen globally"),
            ("A-flat major scale; chromatic scale ascending and descending through full range", "skill_building", "Scale Mastery", "A-flat: two octaves; chromatic from low B-flat to high B-flat; name every pitch"),
            ("Fall concert: 'English Folk Song Suite' arr. Vaughan Williams (Grade 2); full read-through", "concert_prep", "Fall Concert Prep", "Historical context: 1923; British folk songs; mvt.1 'March' — identify form sections"),
            ("Rhythm workshop: 6/8 in 'EFS Suite' context; count and conduct compound meter accurately", "theory", "Rhythm Skills", "Practice conducting in 6 and in 2; EFS Suite uses both; know which feel applies when"),
            ("Sight-reading Level 2-3: B-flat and E-flat major in 4/4 and 3/4; team approach", "sight_reading", "Sight-Reading Skills", "Teams of 4 sight-read together; compete for accuracy; debrief and compare strategies"),
            ("Second fall piece: 'Ye Banks and Braes O Bonnie Doon' (arr. Swearingen, Grade 2); read-through", "concert_prep", "Fall Concert Prep", "Scottish folk melody; lyrical contrast to the march; sing melody before playing"),
            ("G major and D major scale introduction; relate sharp keys to flat keys by pattern", "skill_building", "Scale Mastery", "G major = 1 sharp; D major = 2 sharps; pattern recognition; play both back-to-back"),
            ("Theory: key signature identification quiz (all flat and sharp keys, 0-6 accidentals)", "assessment", "Theory Skills", "Written quiz: 12 key signatures; identify key name; 10 minutes; review immediately after"),
            ("'EFS Suite' mvt.1 mm.1-32: march style with crisp articulation at q=120 target", "concert_prep", "Fall Concert Prep", "March = crisp staccato eighths; strong beat 1; steady pulse; bass line leads always"),
            ("'Ye Banks and Braes' — tone quality focus; sing then play; one long phrase per breath", "concert_prep", "Fall Concert Prep", "Singing exercise: whole class sings melody; then play; match vocal quality on instrument"),
            ("FSP chorales #4-5: tuning with drone tones; Tonal Energy app for pitch centering", "skill_building", "Warm-Up Mastery", "Hold each chord 4 beats; adjust beats until resolved; listen for ringing when in tune"),
            ("'EFS Suite' mvt.2 'Intermezzo' read-through: lyrical, graceful vs mvt.1 march character", "concert_prep", "Fall Concert Prep", "Contrast: how does your playing need to change between movements? Discuss articulation"),
            ("Section leaders run sectional: woodwinds on Suite; brass on Ye Banks; teacher rotates", "concert_prep", "Fall Concert Prep", "Section leaders facilitate; teacher coaches from back; develop student leadership skills"),
            ("Full concert program run-through: both pieces with transitions; audience etiquette practiced", "concert_prep", "Fall Concert Prep", "Walk on, tune, bow as one; silence between pieces; professional deportment throughout"),
            ("Scale mastery check: B-flat through A-flat major; who needs extra support? Practice plan", "assessment", "Scale Mastery", "Quick individual checks during warm-up; mark progress chart; assign focused home practice"),
        ],

        # ── October 2025 (21 days): Fall Concert Polish ───────────────────────
        (2025, 10): [
            ("'EFS Suite' mvt.1 full movement at q=120; bass line support check; balance assessment", "concert_prep", "Fall Concert Prep", "Bass line drives the march; listen to the bottom; upper voices float over strong foundation"),
            ("'Ye Banks and Braes' — melody/accompaniment balance: melody stands, accompaniment sits", "concert_prep", "Fall Concert Prep", "Melody section stands; accompaniment hears what they support; switch and compare"),
            ("FSP chorale #6-7: third voicing in chords; just intonation basics; adjust by ear actively", "skill_building", "Warm-Up Mastery", "Root tallest; fifth medium; third softest; adjust until chord rings with no beats heard"),
            ("Sectional: woodwinds on 'EFS Suite' mm.33-64; brass on 'Ye Banks' sustained chords", "concert_prep", "Fall Concert Prep", "Section rooms; 15 min each; teacher rotates; section leaders facilitate warm-up"),
            ("Full concert program run with professional transitions between pieces", "concert_prep", "Fall Concert Prep", "Walk-on; tune; bow; play; bow; walk-off; no smiling during performance; silent transitions"),
            ("'EFS Suite' mvt.2: dynamics and expression; contrast with martial character of mvt.1", "concert_prep", "Fall Concert Prep", "Mvt.2 = graceful and light; delicate balance; teacher demonstrates phrasing shapes"),
            ("'Ye Banks and Braes' — staggered breathing in sustained sections; seamless melody line", "concert_prep", "Fall Concert Prep", "Mark individual breath points; stagger so melody never stops; seamless long phrases"),
            ("'EFS Suite' mvt.3 read-through if programming three movements; decide and mark form", "concert_prep", "Fall Concert Prep", "Decide if third movement is programmed; if so, read through; note challenges"),
            ("Sight-reading Level 3: 2 sharps, compound time; team competition for accuracy", "sight_reading", "Sight-Reading Skills", "Teams of 4; read a new piece cold; score on accuracy; debrief and compare approaches"),
            ("Concert etiquette workshop: tuning procedure, entrance protocol, unified bow technique", "concert_prep", "Fall Concert Prep", "Professional bow: stand together, bend at waist, return together; tune as one section"),
            ("Full dress run in performance arrangement; transitions timed; record for review next class", "concert_prep", "Fall Concert Prep", "Stage arrangement in band room; run all pieces; record; review recording next class"),
            ("Playing assessment: B-flat + G major scales + 8-bar 'Ye Banks' excerpt; rubric scoring", "assessment", "Fall Concert Prep", "Rubric: scales (20), excerpt tone (10), rhythm (10), style (10); rotate during rehearsal"),
            ("Concert polish: musical storytelling in 'EFS Suite'; discuss Vaughan Williams' intent", "concert_prep", "Fall Concert Prep", "What stories do the folk songs tell? How does the music express each character?"),
            ("'Ye Banks and Braes' sectionals: identify 3 improvements per section; report back", "concert_prep", "Fall Concert Prep", "15 min in section rooms; leaders identify 3 improvements; share with full ensemble"),
            ("Full program for invited audience; real audience critique with specific feedback requested", "concert_prep", "Fall Concert Prep", "Perform for another class; debrief: what did audience notice? What could improve?"),
            ("Concert week: 'EFS Suite' articulation final check; every staccato clear and present", "concert_prep", "Fall Concert Prep", "Circle any staccatos played long; fix them; march precision cannot be compromised"),
            ("Concert week: 'Ye Banks and Braes' phrase release on fermata; unified cutoff together", "concert_prep", "Fall Concert Prep", "Fermata: hold until conductor's hand drops; release simultaneously; silence follows"),
            ("Equipment and music check: uniform complete, folder organized, instrument maintained", "concert_prep", "Fall Concert Prep", "Uniform checklist confirmed; music folder order; instrument clean and ready"),
            ("Final full run-through: back-to-back pieces; positive conclusion; confidence send-off", "concert_prep", "Fall Concert Prep", "Run once; end on energy; positive send-off into concert week; they are ready"),
            ("Pre-concert day: stage logistics; tech check; confirm warm-up routine for tonight", "concert_prep", "Fall Concert Prep", "Stage positions confirmed; sound check if amplification used; warm-up plan finalized"),
            ("FALL CONCERT — daytime class: brief warm-up; reminder of 6:00 PM call time tonight", "concert", "Fall Concert Prep", "Call time 6:00 PM; concert 7:00 PM; professionalism and excellence are expected"),
        ],

        # ── November 2025 (16 days): Post-Concert + EE3 + Winter Prep ─────────
        (2025, 11): [
            ("Post-concert debrief: watch recording; section self-evaluation; written critique form", "flex", "Post-Concert", "Rate yourself 1-5 on tone, rhythm, dynamics, focus; teacher adds written comments"),
            ("Recovery day: music theory Kahoot review; jazz listening — Count Basie 'One O'Clock Jump'", "flex", "Post-Concert", "Kahoot key signatures and rhythm values; listen to jazz; compare feel to concert band"),
            ("EE Book 3 introduction pp.2-5: key of D-flat major; 5 flats; slow whole-note scale challenge", "skill_building", "EE Book 3 Unit 1", "D-flat = A-flat + D-flat + G-flat; relate to scales known; whole notes first; very slow"),
            ("Sixteenth note fluency: rhythmic dictation exercises; teacher plays, students notate", "skill_building", "EE Book 3 Unit 1", "8-beat rhythmic dictation; clap back; notate; check answers; discuss air pattern"),
            ("Winter repertoire: 'Sleigh Ride' by Leroy Anderson (arr. Grade 2.5); full read-through", "concert_prep", "Winter Concert Prep", "Classic piece; tricky gallop rhythms; whip crack effect discussed; exciting and fun"),
            ("'Sleigh Ride' opening gallop: isolate mm.1-8; metro q=152; even eighth note subdivision", "concert_prep", "Winter Concert Prep", "Gallop = dotted eighth + sixteenth; count carefully; drums anchor the tempo"),
            ("Chorale warm-up: 'Amazing Grace' band arrangement; tune each chord with sustained drone", "skill_building", "Warm-Up Mastery", "Full band chorale; hold each chord 4 beats; adjust pitch until no beats are heard"),
            ("Second winter piece: 'A Christmas Festival' arr. Anderson (Grade 2); read medley through", "concert_prep", "Winter Concert Prep", "Christmas carol medley; smooth transitions between carols; identify each carol used"),
            ("'A Christmas Festival': transitions between carols; navigate key changes confidently", "concert_prep", "Winter Concert Prep", "Key changes: watch accidentals; feel each new key; identify the carol at each section"),
            ("EE3 pp.6-9: mixed meter (2/4, 3/4, 4/4 changes); conduct through pattern changes", "skill_building", "EE Book 3 Unit 2", "Conduct through time signature changes; feel the shift; EE3 mixed meter exercises"),
            ("'Sleigh Ride' trumpet solo coaching: solo line practice with accompaniment balance", "concert_prep", "Winter Concert Prep", "Solo above accompaniment; accompaniment = soft harmonic backdrop; tune carefully"),
            ("'A Christmas Festival': dynamics for each carol; which carol gets which energy level?", "concert_prep", "Winter Concert Prep", "Jingle Bells = bright mf; Silent Night = soft and peaceful; O Holy Night = majestic"),
            ("Full winter concert run: address transitions; check total program time; under 12 minutes", "concert_prep", "Winter Concert Prep", "Run both pieces; time it; clean transitions; confirm program order and transition lengths"),
            ("D-flat major scale quiz: play at q=80; compare to first attempt; celebrate improvement", "assessment", "EE Book 3 Unit 1", "Improvement tracking; students note own progress; growth mindset discussion"),
            ("FSP chorales #8-9: full-range tuning; advanced balance in four-part harmony", "skill_building", "Warm-Up Mastery", "More complex harmonies; listen for all 4 voices; adjust to blend into chord color"),
            ("'Sleigh Ride' full movement run at performance tempo; circle remaining trouble spots", "concert_prep", "Winter Concert Prep", "No stopping; end to end; note total time; final fixes for next rehearsal session"),
        ],

        # ── December 2025 (15 days): Winter Concert Prep ─────────────────────
        (2025, 12): [
            ("'Sleigh Ride' detail work: gallop precision; trumpet solo coaching with ensemble balance", "concert_prep", "Winter Concert Prep", "Isolate gallop mm.1-8; match section sound; solo trumpet plays with accompaniment"),
            ("'A Christmas Festival' smooth transitions: stop at each key change and feel new key", "concert_prep", "Winter Concert Prep", "Feel each new key; watch accidentals; sing key change notes before playing them"),
            ("Full winter concert run-through; audience entrance simulation; between-piece protocol", "concert_prep", "Winter Concert Prep", "Rehearse exactly as performance; no stopping; conductor waits for complete silence"),
            ("Woodwind sectional: 'Sleigh Ride' melody passages; 'Christmas Festival' ornaments", "concert_prep", "Winter Concert Prep", "20 min in section room; bring specific measure numbers to work; leaders facilitate"),
            ("Brass sectional: 'Sleigh Ride' accompaniment rhythms; 'Christmas Festival' brass chorale", "concert_prep", "Winter Concert Prep", "Brass gallop accompaniment precision; chorale sections in tune with drone; together"),
            ("'Sleigh Ride' ending: coda and final chord; clean rhythmic release together on cutoff", "concert_prep", "Winter Concert Prep", "Coda = exciting energy build; final chord: all together, forte, held until conductor release"),
            ("Sight-reading: Level 2 holiday exercise; 3/4 time; apply KATS scanning strategy", "sight_reading", "Sight-Reading Skills", "Holiday-themed exercise; KATS strategy; 30-second scan; play without stopping"),
            ("Playing quiz: 'Sleigh Ride' mm.1-16 + tone quality and dynamics rubric", "assessment", "Winter Concert Prep", "Individual rotation during rehearsal; rubric: tone (5), rhythm (5), dynamics (5)"),
            ("Dress rehearsal: full concert attire; complete program; concert protocol practiced", "concert_prep", "Winter Concert Prep", "Walk on; tune; bow; both pieces; bow; walk off; no smiling; professional protocol"),
            ("Winter concert final polish: 'Sleigh Ride' coda climax; 'A Christmas Festival' ending clean", "concert_prep", "Winter Concert Prep", "Climax = full energy; festive ending of Christmas Festival; run once clean and strong"),
            ("Concert day: uniform check; brief warm-up plan; call time 6:00 PM reminder confirmed", "concert_prep", "Winter Concert Prep", "Confirm uniform complete; folder in order; call time 6:00 PM; energy and focus"),
            ("WINTER CONCERT — daytime class: brief warm-up; reminder of 6:00 PM call time tonight", "concert", "Winter Concert Prep", "Call time 6:00 PM; concert 7:00 PM; Intermediate Band excellence expected"),
            ("Post-concert debrief: recording review; compare growth from Fall Concert to Winter", "flex", "Post-Concert", "Watch recording; identify improvements since Fall; celebrate musical growth as ensemble"),
            ("Theory game: rhythm dictation challenge; teacher plays increasingly complex patterns", "theory", "EE Book 3 Unit 2", "Progressive difficulty; 4-beat patterns; students notate; check; discuss errors together"),
            ("Winter break listening: assign masterwork; return in January with written observations", "listening", "Music Appreciation", "Listen to 'Holst Planets' or Tokyo Kosei Band recording; write 3 observations about playing"),
        ],

        # ── January 2026 (19 days): New Semester + Scale Push + Spring Prep ───
        (2026, 1): [
            ("New semester goal-setting: 3 personal technique goals and 1 ensemble goal for spring", "flex", "New Semester", "Written goal sheet; teacher collects; review mid-March; goals must be specific and measurable"),
            ("Chromatic scale full range; scale speed challenge: all major scales at q=108 target", "skill_building", "Scale Mastery", "Scale ladder; chromatic from low B-flat to high B-flat; q=100 today; push toward 108"),
            ("EE3 pp.6-9: mixed meter review; 2/4, 3/4, 4/4 transitions; conduct along with music", "skill_building", "EE Book 3 Unit 2", "Conduct through time changes; feel the shift; isolate transition measure; EE3 exercises"),
            ("Solo & Ensemble literature selection: Rubank Intermediate solos displayed and browsed", "concert_prep", "Festival Prep", "Browse intermediate solos; try 8 bars of each; select by ability level; sign up"),
            ("Listening analysis: compare 3 recordings of Sousa 'Stars and Stripes' march performance", "listening", "Music Analysis", "Discuss tempo, articulation style, balance differences; which version resonates most?"),
            ("Scale speed results: who reached q=108? Recognition given; continued push toward q=116", "skill_building", "Scale Mastery", "Scale ladder posted; students move up as they reach targets; healthy motivation"),
            ("EE3 pp.10-12: alla breve (cut time) in march style; conduct in 2; feel march energy", "skill_building", "EE Book 3 Unit 2", "March in cut time = 2 big beats; feel the march energy; EE3 march exercises"),
            ("Spring concert: 'Cajun Folk Songs' by Frank Ticheli (Grade 2.5); full read-through", "concert_prep", "Spring Concert Prep", "Discuss Cajun culture briefly; read mvt.1 'Acadian Songs'; identify folk song themes"),
            ("'Cajun Folk Songs' mvt.1: melody shaping; sing melody before playing; folk song feel", "concert_prep", "Spring Concert Prep", "Singing connects to folk tradition; play with vocal quality; feel the folk music idiom"),
            ("Sight-reading: Level 3 mixed meter exercise; practice cut time and 6/8 side by side", "sight_reading", "Sight-Reading Skills", "KATS strategy; note time signature changes during scan; plan meter changes before playing"),
            ("S&E solo coaching rotation: 5-min per student/small group; technical feedback given", "concert_prep", "Festival Prep", "Rotate teacher efficiently; focus on biggest issue per group; one change at a time"),
            ("EE3 pp.13-15: D minor natural and harmonic scales; hear the difference between versions", "theory", "EE Book 3 Unit 3", "Natural minor pattern; harmonic minor = raise 7th; play both versions; hear difference"),
            ("'Cajun Folk Songs' mvt.1 full run at target tempo; circle problems for sectionals", "concert_prep", "Spring Concert Prep", "Full ensemble at target tempo; no stopping; circle issues after; section leaders prioritize"),
            ("Second spring piece: 'Lexington March' by John Edmondson (Grade 2); read-through", "concert_prep", "Spring Concert Prep", "Classic march form: intro, 1st strain, 2nd strain, trio, D.C.; identify each section"),
            ("'Lexington March' march style: crisp articulation; even pulse; snare drum anchors feel", "concert_prep", "Spring Concert Prep", "Staccato eighths in march; bass line drives; snare anchors; upper voices float over"),
            ("FSP chorales #10-11: advanced balance and blend; six-part harmony challenge", "skill_building", "Warm-Up Mastery", "Six-voice chorale; equal weight per voice; listen across entire ensemble simultaneously"),
            ("Scale mastery check: all 7 major scales + D natural minor; compare to December level", "assessment", "Scale Mastery", "Play 8 scales; self-rate first; teacher confirms; mark on progress chart; discuss"),
            ("Full spring concert run: both pieces back-to-back; timed; note transition procedures", "concert_prep", "Spring Concert Prep", "Run full program; time it; transitions under 30 seconds; clean walk-on procedure"),
            ("'Lexington March' trio section: low brass melody emerges; upper voices accompany softly", "concert_prep", "Spring Concert Prep", "Trio = upper brass first; low brass melody emerges; everyone backs off dynamically"),
        ],

        # ── February 2026 (15 days): S&E Festival + Spring Building ──────────
        (2026, 2): [
            ("S&E coaching intensive: small group rotation 8-min each; musicality and expression focus", "concert_prep", "Festival Prep", "Not just notes; expression, intonation, phrasing; push for musical communication"),
            ("EE3 pp.10-12: Alla breve (cut time) march style; march in 2; feel the energy in cut time", "skill_building", "EE Book 3 Unit 2", "March excerpts in cut time; feel 2 big beats; don't micro-conduct; feel the swing"),
            ("'Cajun Folk Songs' mvt.2 'Papa's Tune': energetic contrast to mvt.1; full read-through", "concert_prep", "Spring Concert Prep", "Faster tempo; Cajun dance feel; exciting rhythms; discuss Cajun fiddle tradition briefly"),
            ("Composition project: 8-bar melody in student's choice of key; dynamics and articulation required", "composition", "Creative Music", "Any key learned; include at least 2 dynamic marks and 1 articulation pattern throughout"),
            ("S&E festival logistics: schedule, location, time for participants; professional behavior", "concert_prep", "Festival Prep", "Review logistics; all students support each other even if not individually performing"),
            ("'Lexington March' full run at performance tempo; ensemble precision and articulation check", "concert_prep", "Spring Concert Prep", "No stopping; target tempo; every staccato marked and played; does the march march?"),
            ("Sight-reading Level 3: sharp keys and compound time; festival-level difficulty simulation", "sight_reading", "Sight-Reading Skills", "Festival-style: 30-second scan, no-stop play; debrief and compare what each player noticed"),
            ("'Cajun Folk Songs' mvt.1 + mvt.2 back-to-back: attacca transition rehearsed and clean", "concert_prep", "Spring Concert Prep", "No break between movements; attacca = go immediately; rehearse the transition point"),
            ("EE3 pp.16-18: Minor keys in depth — G minor natural, harmonic, and melodic forms", "theory", "EE Book 3 Unit 3", "Three versions of G minor; play all three; hear the raised 6th/7th in melodic minor"),
            ("Composition projects due: students share 8-bar melodies; class gives structured feedback", "composition", "Creative Music", "Positive critique structure: 'I noticed... I liked... I wonder if...' — no negativity"),
            ("Post-mid-winter-break: scale warm-up; re-establish ensemble blend and balance after break", "skill_building", "Technique Builder", "Systematic restart; tune as if for the first time; establish ensemble blend after break"),
            ("S&E final coaching: last rehearsal before Saturday festival; expression and communication", "concert_prep", "Festival Prep", "Final technical touches; biggest remaining fix; play through with full musical expression"),
            ("Full spring concert run: 'Cajun Folk Songs' (both mvts) + 'Lexington March'; timing check", "concert_prep", "Spring Concert Prep", "Complete program; time it; work longest transition; celebrate what sounds great"),
            ("Spring concert sight-reading practice: prepare for Large Group Festival sight-reading room", "sight_reading", "Festival Prep", "Festival procedure: scan, discuss, perform; simulate full festival experience precisely"),
            ("S&E Festival final prep and logistics; post-festival debrief expectations for next class", "concert_prep", "Festival Prep", "Final encouragement; professional behavior reminder; bring comments back to class Monday"),
        ],

        # ── March 2026 (21 days): Spring Concert + Festival Build ─────────────
        (2026, 3): [
            ("S&E Festival debrief: share experiences; analyze judges' feedback as a class group", "flex", "Post-Festival", "Read comments aloud; common feedback themes identified; celebrate all performances"),
            ("'Cajun Folk Songs' mvt.1 — Acadian Songs: phrase shaping; sing the folk melody first", "concert_prep", "Spring Concert Prep", "Discuss Acadian history; each phrase tells part of the cultural story; play musically"),
            ("'Cajun Folk Songs' mvt.2 — Papa's Tune: Cajun dance energy; rhythmic precision throughout", "concert_prep", "Spring Concert Prep", "Cajun two-step feel; rhythmic drive; drums lock in; winds dance on top of the groove"),
            ("EE3 pp.19-21: Major scale review + relative minors for all flat key signatures", "skill_building", "EE Book 3 Unit 3", "Each flat major paired with relative minor; pattern = count down a third from tonic"),
            ("'Lexington March' trio detail: low brass melody in trio section; upper voices back off", "concert_prep", "Spring Concert Prep", "Trio = cue low brass melody; upper voices accompany at mp; dynamic contrast critical"),
            ("Scale mastery push: all 7 major scales + D and G natural minor; April speed test", "skill_building", "Scale Mastery", "Scale practice chart distributed; April target; daily home practice required"),
            ("Sight-reading Level 3: sharps and compound time; festival cold read practice", "sight_reading", "Sight-Reading Skills", "Festival sight-reading procedure; discuss: what do you look for in 30 seconds?"),
            ("'Cajun Folk Songs' full both-movement run: attacca transition clean; energy builds naturally", "concert_prep", "Spring Concert Prep", "Full ensemble; mvt.1 to mvt.2 without stopping; energy builds into mvt.2 seamlessly"),
            ("FSP chorales #12-14: advanced tuning with complex chromatic harmonies; listen globally", "skill_building", "Warm-Up Mastery", "Difficult chords; adjust in real time; teacher points to voices that need adjustment"),
            ("'Lexington March' full performance run: march style; crisp articulation; tempo stable", "concert_prep", "Spring Concert Prep", "March tempo stable throughout; no rushing in trio; conductor holds tempo strictly"),
            ("Student conductor day: volunteer student conducts warm-ups; discuss conducting gesture", "flex", "Leadership", "Student conductor tries conducting signals; class follows; teacher observes from back"),
            ("Theory: scale degree functions — tonic, dominant, subdominant; harmonic progression intro", "theory", "EE Book 3 Unit 3", "Identify tonic, dominant, subdominant in 'Cajun Folk Songs'; function in harmonic context"),
            ("Full concert program: both pieces with transitions; mock festival run; record for review", "concert_prep", "Spring Concert Prep", "Treat as if judges present; performance level; record; listen next class for improvements"),
            ("Recording review: class identifies top 3 improvements needed; address them today", "concert_prep", "Spring Concert Prep", "Listen together; class votes on top 3; address each one in detail during rehearsal"),
            ("'Cajun Folk Songs' cultural expressiveness: connect Cajun tradition to musical performance", "concert_prep", "Spring Concert Prep", "Cajun music = joy and community; feel that joy in your playing; let it show in tone"),
            ("Playing test: G major + D major scales + 8-bar excerpt from 'Cajun Folk Songs' mvt.1", "assessment", "Spring Concert Prep", "Rubric: tone (5), rhythm (5), expression (5); students know the criteria in advance"),
            ("Large Group Festival prep: discuss sight-reading strategy; cold read new Level 3 exercise", "concert_prep", "Festival Prep", "Festival format review; sight-reading = 30-sec scan + play; no repeats allowed"),
            ("'Lexington March' march style final check: every staccato, every accent, strong beat 1", "concert_prep", "Spring Concert Prep", "Circle any inconsistent articulations; fix section by section; full ensemble applies"),
            ("Full spring concert performance run: no stopping; performance-quality effort expected", "concert_prep", "Spring Concert Prep", "Can you play through without stopping? Celebrate if you do; this is the standard now"),
            ("EE3 pp.22-24: Comprehensive skills review; identify areas of strength and needed focus", "skill_building", "EE Book 3 Unit 4", "Comprehensive review page; identify strongest and weakest areas per student honestly"),
            ("Spring concert additional polish: expressiveness and dynamics not yet being observed", "concert_prep", "Spring Concert Prep", "Read every dynamic marking aloud before playing; then play with those markings present"),
        ],

        # ── April 2026 (17 days): Large Group Festival + Spring Final ─────────
        (2026, 4): [
            ("Large Group Festival final prep: full program run at performance level; record and review", "concert_prep", "Festival Prep", "Perform as if judges watching; record; listen; identify last-minute fixes"),
            ("Festival sight-reading: cold reads in 2 different keys; simulate full festival procedure", "sight_reading", "Festival Prep", "Full procedure: 30-sec scan, brief discussion, play once; debrief each attempt carefully"),
            ("Scale test: 7 major scales + chromatic + D and G natural minor at target tempo q=104", "assessment", "Scale Mastery", "Individual testing; rubric: accuracy (5), tone (5), tempo (5); record all results"),
            ("Post-spring-break: scale warm-up; FSP chorale reset; re-establish ensemble precision", "skill_building", "Technique Builder", "Post-break warm-up routine; tune as if from scratch; recalibrate ensemble precision"),
            ("Large Group Festival logistics final review: bus schedule, attire, performance order", "concert_prep", "Festival Prep", "Final logistics; everyone knows the full schedule; confirm attire and call time"),
            ("Mock festival performance for invited critical audience; real audience feedback", "concert_prep", "Festival Prep", "Real audience changes the energy; debrief: what did you do differently with audience?"),
            ("'Cajun Folk Songs' final detail: every phrase shaped; every dynamic a real level change", "concert_prep", "Festival Prep", "Check every dynamic in the score; are you playing it? Adjust each section; run through"),
            ("LARGE GROUP FESTIVAL — full day performance trip; professional behavior expected", "concert", "Festival Prep", "Depart early; warm up at festival; perform program + sight-reading; return midday"),
            ("Festival debrief: read judges' score sheets together; celebrate rating; discuss themes", "flex", "Post-Festival", "Read each judge comment; celebrate achievement; identify one area to improve for concert"),
            ("Student conductor masterclass: two volunteer students conduct warm-up chorales", "flex", "Leadership", "Discuss conducting clarity; what gestures communicate what? Class follows student conductor"),
            ("EE3 pp.25-27: Advanced review: mixed meter, minor scales, rhythmic complexity", "skill_building", "EE Book 3 Unit 4", "Comprehensive rhythmic and harmonic review; push for higher complexity in performance"),
            ("Spring concert continued prep: apply festival feedback to pieces; specific measure focus", "concert_prep", "Spring Concert Prep", "Take top 5 judge comments; address each in rehearsal; confirm each improvement made"),
            ("Full spring concert run: three pieces + transitions; timed; stage movement practiced", "concert_prep", "Spring Concert Prep", "Time the full concert; under 15 minutes; transitions smooth; stage movement clean"),
            ("Expression workshop: connecting emotion to musical performance; storytelling through music", "concert_prep", "Spring Concert Prep", "Each piece has a story; can the audience feel that story? Practice communicating it"),
            ("Sight-reading as daily warm-up skill: Level 3 cold read; daily practice builds fluency", "sight_reading", "Sight-Reading Skills", "Short daily cold read as warm-up; build automatic sight-reading as a permanent skill"),
            ("Spring concert final polish: implement all festival and practice run improvements", "concert_prep", "Spring Concert Prep", "Last major rehearsal before final week; fix everything still addressable today"),
            ("Full spring concert program with stage arrangement; confirm all logistics and transitions", "concert_prep", "Spring Concert Prep", "Stage arrangement in band room; full concert run; time; all logistics reviewed"),
        ],

        # ── May 2026 (20 days): Spring Concert + Year End ────────────────────
        (2026, 5): [
            ("Spring concert full rehearsal: both pieces + third piece if ready; performance level", "concert_prep", "Spring Concert Prep", "Full program; no stopping; annotate issues after; prioritize highest-impact fixes"),
            ("Expression and musicality workshop: go beyond correct notes; make it truly MUSICAL", "concert_prep", "Spring Concert Prep", "Pick one phrase from each piece; play without expression; then with; hear the difference"),
            ("Year-end playing exam: 2 scales + prepared 8-bar excerpt + 4-bar sight-read", "assessment", "Year-End Assessment", "Exam: scales (20), excerpt (40), sight-reading (20), tone quality (20) = 100 pts"),
            ("Sectional polish: each section perfects their toughest passage under section leader", "concert_prep", "Spring Concert Prep", "Toughest passage = most circled; section leaders facilitate; teacher rotates rooms"),
            ("Spring concert dress rehearsal: full attire; full program; no do-overs at all", "concert_prep", "Spring Concert Prep", "Concert attire required; full program from entrance to exit; assess professional readiness"),
            ("'Cajun Folk Songs' final expressiveness: honor the Cajun folk tradition in every note", "concert_prep", "Spring Concert Prep", "Play with cultural respect and joy; folk music is alive and real; feel that energy"),
            ("'Lexington March' final performance run: march tempo stable; march energy complete", "concert_prep", "Spring Concert Prep", "March from start to finish with full energy; march feel in every note; no dragging"),
            ("Full concert program run: timing check; transitions polished; all logistics confirmed", "concert_prep", "Spring Concert Prep", "Time the full program; under 15 min; transitions under 30 sec; all logistics confirmed"),
            ("Year-end scale assessment (final): all 7 major scales + 2 minor scales on record", "assessment", "Year-End Assessment", "Final scale check; record improvement from year beginning; celebrate scale growth"),
            ("Concert week: uniform and equipment final check; call time 6:00 PM confirmed", "concert_prep", "Spring Concert Prep", "Everything ready today; no last-minute changes; visualize an excellent concert"),
            ("Instrument maintenance day: oil valves, grease slides, swab woodwinds, tighten mouthpieces", "flex", "Year End", "Hands-on instrument care; each student services own instrument; report damage"),
            ("Spring concert final week prep: run both spring pieces once each; calm and confident", "concert_prep", "Spring Concert Prep", "Brief focused run; calm energy; trust the preparation; you are ready for this"),
            ("Pre-concert mental preparation: visualization, breathing exercises, positive team talk", "concert_prep", "Spring Concert Prep", "Guide 5-minute visualization: walk on stage; play perfectly; bow; audience applauds"),
            ("Spring concert last rehearsal day: answer final questions; confirm call time tonight", "concert_prep", "Spring Concert Prep", "Answer final questions; folder confirmed; uniform confirmed; call time 6:00 PM"),
            ("SPRING CONCERT — evening performance; full year's work on display tonight", "concert", "Spring Concert Prep", "Call time 6:00 PM; concert 7:00 PM; celebrate a full year of hard ensemble work"),
            ("Post-concert celebration: watch recording; year-end awards; celebrate the growth", "flex", "Year End", "Awards: most improved, outstanding musician, section MVPs, leadership award"),
            ("Music history exploration: evolution of the concert band from military to modern", "listening", "Year End", "Listen to Holst 'First Suite', Grainger 'Country Gardens'; discuss band music evolution"),
            ("Instrument petting zoo: try a different instrument for 15 minutes with teacher guidance", "flex", "Year End", "No pressure; explore embouchure and fingerings; teacher circulates; discussion after"),
            ("Year-end reflection and goal-setting for Advanced Band next year", "flex", "Year End", "What do you want to accomplish in Advanced Band? Write 3 specific and measurable goals"),
            ("Final day: instrument return, music turn-in, locker clean-out, summer scale packet", "flex", "Year End", "Return all school materials; inventory check; summer scale sheet; goodbyes and well-wishes"),
        ],

        # ── June 2026 (14 days): Year-End ─────────────────────────────────────
        (2026, 6): [
            ("Music history: Evolution of the concert band from town bands to modern wind ensemble", "listening", "Year End", "Listen to clips across the decades; trace instrumentation and style evolution over time"),
            ("Instrument petting zoo: try a different instrument for 15 minutes; teacher guides", "flex", "Year End", "No pressure; explore embouchure, air support, fingerings; class discussion after"),
            ("Year-end reflection: what I'm proud of + what I'll focus on in Advanced Band next year", "flex", "Year End", "Written reflection; sealed and returned first week of Advanced Band next September"),
            ("Sight-reading Olympics: team competition with increasingly difficult sight-reading rounds", "sight_reading", "Year End", "Teams of 4; bracket-style competition; celebrate bravery and accuracy equally"),
            ("Creative music day: improvise over a simple Cajun-style backing track using B-flat major", "composition", "Year End", "Folk music improvisation; no wrong notes; bravery points; encourage expression"),
            ("Student-led mini-concert: volunteers perform solos or duets prepared during the year", "flex", "Year End", "Celebrate individual achievement; supportive audience; each performer gets recognition"),
            ("Advanced Band preview: repertoire, expectations, audition prep, summer practice guide", "flex", "Year End", "What students can expect in Advanced Band; summer audition material distributed"),
            ("Theory review game: Kahoot covering EE3 content, key signatures, and musical terms", "theory", "Year End", "Fun competitive review; discuss answers; celebrate knowledge gained this year"),
            ("Listening: watch Tokyo Kosei Band recording; discuss professional-level ensemble playing", "listening", "Year End", "Watch performance; discuss tone, balance, precision, expression; what to aspire to"),
            ("Final day: instrument return, locker clean-out, summer assignments distributed", "flex", "Year End", "Return all school instruments; clean lockers; summer practice sheet; goodbyes"),
            ("Music improvisation game: pass the melody; each student adds 2 bars of improvisation", "composition", "Year End", "Call and response improvisation; build a group composition; record the result"),
            ("Listening comparison: first-day recording vs. spring concert recording; celebrate growth", "listening", "Year End", "Play September and spring recordings side by side; how far did this ensemble come?"),
            ("Professional pathway discussion: high school band, honors band, all-state; how to prepare", "flex", "Year End", "Discuss opportunities ahead; encourage continued music-making; resources for summer"),
            ("Year-end celebration concert: perform favorite pieces for parents or visiting class", "flex", "Year End", "Informal concert; invite parents or another class; celebrate the year together"),
        ],
    }

    return _build_items(school_days, monthly)


# ─── Advanced Band (MU_301) ───────────────────────────────────────────────────

def generate_advanced_band(school_days):
    """Advanced Band — Wind Ensemble, Grades 7-8, Advanced level. FSP + Masterworks.
    School day counts: Sep=20, Oct=21, Nov=16, Dec=15, Jan=19, Feb=15,
                       Mar=21, Apr=17, May=20, Jun=14  (Total=178)"""

    monthly = {

        # ── September 2025 (20 days): Wind Ensemble Launch ────────────────────
        (2025, 9): [
            ("Audition results posted; Wind Ensemble welcome; expectations, handbook, and repertoire preview", "skill_building", "Orientation", "Distribute handbook; concert dress code; attendance policy; leadership structure established"),
            ("Full-range warm-up: Remington series (brass), overtone long tone series (WW), stick control (perc)", "skill_building", "Advanced Warm-Up", "Remington exercises 1-5; WW overtone series from low B-flat; perc stick control pp.1-3"),
            ("All 12 major scales review: begin at q=100; target q=120 by October 1; two-octave minimum", "skill_building", "Scale Mastery", "Scale speed ladder posted; three-octave for advanced players; clean fingerings required"),
            ("Bach chorale warm-up (arr. Fussell): tune each chord; listen across ensemble; adjust actively", "skill_building", "Advanced Warm-Up", "Hold each chord 4 beats; tune root, fifth, third; adjust beats; chord rings when in tune"),
            ("Fall repertoire: 'Lullaby for Band' by Larry Daehn (Grade 3); full read-through with expression", "concert_prep", "Fall Concert Prep", "Gorgeous lyrical Grade 3 work; discuss phrasing before playing; identify long phrase arches"),
            ("'The Thunderer' march by Sousa (arr. Grade 3): read-through; march form labeled in score", "concert_prep", "Fall Concert Prep", "Form: intro-1st strain-2nd strain-trio-break-trio; label every section in the score"),
            ("Advanced rhythm workshop: mixed meter, hemiola, polyrhythm concepts; clap 2-against-3", "theory", "Advanced Theory", "2-against-3 clapping exercise; hemiola in Sousa trios; feel it before trying to play it"),
            ("Sight-reading Level 4: 2 sharps/flats; compound time; syncopation; score-reading strategy", "sight_reading", "Sight-Reading Skills", "Score reading from conductor perspective; KATS + look for modal or chromatic passages"),
            ("Third fall piece: 'Encanto' by Robert W. Smith (Grade 3); read-through; Latin rhythm intro", "concert_prep", "Fall Concert Prep", "Latin-influenced; clave rhythm; bongo/conga patterns; exciting and very energetic"),
            ("'Lullaby for Band' phrase shaping: identify climax notes; dynamic architecture mapped on board", "concert_prep", "Fall Concert Prep", "Map dynamics measure by measure; identify where each phrase leads; arch shape on board"),
            ("'The Thunderer' march precision at tempo: marcato style; bass line drives the ensemble", "concert_prep", "Fall Concert Prep", "Marcato vs staccato; bass line = backbone of the march; low brass drives forward"),
            ("'Encanto' — percussion feature isolation: clave, bongos, congas; layer one rhythm at a time", "concert_prep", "Fall Concert Prep", "Percussion alone first; layer clave, then bongos, then winds over the percussion groove"),
            ("Tuning workshop: just intonation in chorale; demonstrate beats between mistuned pitches", "skill_building", "Advanced Warm-Up", "Tune root, fifth, third of each chord; demonstrate by going slightly out of tune first"),
            ("All 12 major scales assessment at q=112: accuracy and two-octave range check", "assessment", "Scale Mastery", "Must play all 12 at q=112 minimum; 2 octaves; rubric: accuracy (5), tone (5), tempo (5)"),
            ("Full fall concert rehearsal: 3 pieces in program order; time the full program", "concert_prep", "Fall Concert Prep", "Run all three pieces; timed; discuss pacing between pieces; note transitions needed"),
            ("Score study: 'Lullaby for Band' with full score; identify form, harmonic structure", "theory", "Advanced Theory", "Distribute scores; identify key areas, phrase structure, instrumentation; share findings"),
            ("'The Thunderer' trio section: counter-melody in low voices; everyone else backs off to mp", "concert_prep", "Fall Concert Prep", "Trio = low brass take the melodic spotlight; everyone else at mp or below; let it emerge"),
            ("'Encanto' rhythmic precision at performance tempo: percussion and winds locked together", "concert_prep", "Fall Concert Prep", "Winds listen to percussion for cue; lock in with clave pattern; feel the Latin groove"),
            ("FSP chorale warm-up #1-5: advanced tuning with close voicings; four-part harmony mastery", "skill_building", "Advanced Warm-Up", "Close voicings need careful tuning; listen for beats in all intervals; resolve actively"),
            ("Full fall concert run: 3 pieces at performance quality; record and review critically next class", "concert_prep", "Fall Concert Prep", "Record on phone; listen next class; identify top 3 things to fix before October"),
        ],

        # ── October 2025 (21 days): Fall Concert Polish ───────────────────────
        (2025, 10): [
            ("'Lullaby for Band' — rubato and expressive freedom; follow conductor; breathe together", "concert_prep", "Fall Concert Prep", "Rubato = flexible tempo; conductor stretches and contracts; ensemble follows as one unit"),
            ("'The Thunderer' — dynamic contrast; trio vs. march sections; balance shifts explained", "concert_prep", "Fall Concert Prep", "March = bold marcato; trio = lighter and melodious; contrast creates the drama of march"),
            ("'Encanto' — full speed run; each player circles 3 personal trouble measures to fix", "concert_prep", "Fall Concert Prep", "Run at target tempo; no stopping; after, circle 3 own trouble measures; fix them today"),
            ("Music theory: Roman numeral analysis of 'Lullaby for Band' harmonic structure", "theory", "Advanced Theory", "Identify I, IV, V, vi, II chords; note modulations; map harmonic rhythm of the phrases"),
            ("Concert stage presence: professional entrance, bow technique, tuning protocol, exit", "concert_prep", "Fall Concert Prep", "Silent transitions; no talking; professional deportment; conductor commands the stage"),
            ("'Lullaby for Band' full movement at full performance expression; no stopping allowed", "concert_prep", "Fall Concert Prep", "Every dynamic, every rubato, every phrase arch; complete musical and technical performance"),
            ("'The Thunderer' — march form walkthrough final; all repeats and D.C. navigation confirmed", "concert_prep", "Fall Concert Prep", "Walk through form verbally as class; everyone confirms their personal roadmap"),
            ("'Encanto' — Latin style refinement: clave feel internalized; accents on correct beats", "concert_prep", "Fall Concert Prep", "Clave pattern internalized; don't just play it — feel it; Latin music lives in the body"),
            ("Sight-reading Level 4: two sharp/flat keys and compound time; score-study lens applied", "sight_reading", "Sight-Reading Skills", "30-second scan with score study; identify harmonic areas; discuss then play once"),
            ("Playing assessment: all 12 major scales + 8-bar excerpt from 'The Thunderer'; rubric", "assessment", "Fall Concert Prep", "Rubric: scales accuracy (20), excerpt tone (10), rhythm (10), march style (10)"),
            ("Full concert dress rehearsal in performance arrangement; record for class review", "concert_prep", "Fall Concert Prep", "Stage setup in band room; run all three pieces; record; review recording next class"),
            ("Recording review: class identifies top 3 improvements needed; implement them today", "concert_prep", "Fall Concert Prep", "Listen to yesterday's recording together; class votes on top 3; fix them right now"),
            ("'Lullaby for Band' final phrase shaping: every phrase has a peak and a resolution", "concert_prep", "Fall Concert Prep", "Identify the highest emotional point; everything builds to and falls from that peak"),
            ("'Encanto' percussion-winds coordination final check: every cue synchronized perfectly", "concert_prep", "Fall Concert Prep", "Percussion cues for winds; wind cues for percussion; listen and follow each other"),
            ("Full program run with invited guest: principal, visiting class, or parent volunteers", "concert_prep", "Fall Concert Prep", "Real audience changes the energy; perform at full concert level; debrief after run"),
            ("Concert week: 'The Thunderer' articulation check; every staccato is a real staccato", "concert_prep", "Fall Concert Prep", "Circle any staccatos played long; fix every one; march precision is non-negotiable"),
            ("Concert week: 'Lullaby' ending — final pp must be ethereal and barely audible", "concert_prep", "Fall Concert Prep", "pp ending; fade to near nothing; last note barely audible; magic created in silence"),
            ("Concert week: 'Encanto' — Latin groove energy high from first note to the last", "concert_prep", "Fall Concert Prep", "Energy never drops; excitement is the goal from first note to last; end at maximum"),
            ("Equipment, music, and uniform final check; call time 5:30 PM firmly established", "concert_prep", "Fall Concert Prep", "Confirm complete uniform; music folder organized; call time 5:30 PM confirmed"),
            ("Full program final run; mental performance preparation; positive send-off pep talk", "concert_prep", "Fall Concert Prep", "Run all 3 once; end positively; visualize a great concert; they are ready"),
            ("FALL CONCERT — daytime class: brief warm-up; reminder of 5:30 PM call time tonight", "concert", "Fall Concert Prep", "Call time 5:30 PM; concert 7:00 PM; Wind Ensemble professionalism and excellence expected"),
        ],

        # ── November 2025 (16 days): Post-Concert + Winter Prep ───────────────
        (2025, 11): [
            ("Post-concert debrief: watch recording; section self-evaluations; written critiques shared", "flex", "Post-Concert", "Each section identifies one clear success and one growth area; written and discussed"),
            ("Flex day: student-choice chamber music; small groups form and read a piece informally", "flex", "Post-Concert", "Students form quartets/quintets; read appropriate chamber music; informal sharing"),
            ("Jazz band preview: swing style; dominant 7th chords; blues scale; improvisation intro", "skill_building", "Jazz Exploration", "Swing vs straight feel; demonstrate; play a blues scale; volunteer a 4-bar solo attempt"),
            ("Winter repertoire: 'Russian Christmas Music' by Alfred Reed (Grade 4); full read-through", "concert_prep", "Winter Concert Prep", "Discuss Russian Orthodox musical tradition; iconic Grade 4 masterwork; read through"),
            ("Minor scale deep dive: harmonic and melodic minor in all 12 keys; pattern recognition", "skill_building", "Scale Mastery", "Harmonic = raise 7th; melodic = raise 6th and 7th ascending; play both all 12 keys"),
            ("'Russian Christmas Music' opening chorale mm.1-40: pp to fff crescendo patience and control", "concert_prep", "Winter Concert Prep", "40-measure crescendo requires patience; start barely audible; build gradually over 40 bars"),
            ("Score study: 'Russian Christmas Music' full score; form, themes, key areas, climaxes", "theory", "Advanced Theory", "Read score together; identify each theme; note key area shifts; mark climax points"),
            ("'Russian Christmas Music' Allegro section mm.41-100: technical passages at slow tempo", "concert_prep", "Winter Concert Prep", "Slow practice first; subdivide; build speed gradually; no rushing ahead of the metro"),
            ("Bach chorale advanced: 8-part harmony; listen for all eight voices simultaneously", "skill_building", "Advanced Warm-Up", "FSP advanced chorales; eight voices; listen globally and locally at the same time"),
            ("Second winter piece: 'Greensleeves' arr. Reed (Grade 3); read-through; assign featured solos", "concert_prep", "Winter Concert Prep", "Beautiful Reed setting; solo features; read through; identify solo opportunities; audition"),
            ("'Greensleeves' solo coaching: featured soloists rehearse with full accompaniment balance", "concert_prep", "Winter Concert Prep", "Solo above accompaniment; accompaniment = warm harmonic support; tune carefully"),
            ("All 12 harmonic minor scales introduced: goal all 24 scales ready by January assessment", "skill_building", "Scale Mastery", "Pattern: raise 7th of natural minor; introduce first 3 new harmonic minor scales today"),
            ("Full winter program: 'Russian Christmas Music' + 'Greensleeves'; transitions and contrast", "concert_prep", "Winter Concert Prep", "Run full program; transitions; discuss the contrasting character of the two pieces"),
            ("'Russian Christmas Music' mm.100-end: review coda and climax preparation", "concert_prep", "Winter Concert Prep", "Coda approach: fff climax; full range; controlled decrescendo to the final chord"),
            ("Playing quiz: 6 harmonic minor scales + 'Greensleeves' mm.1-16 sight excerpt", "assessment", "Winter Concert Prep", "Rubric: scales (15), excerpt tone (5), expression/phrasing (5); rotate during rehearsal"),
            ("'Greensleeves' full performance run: expression, rubato, soloists in balance, ensemble", "concert_prep", "Winter Concert Prep", "Full expression; conductor signals rubato moments; soloists lead their sections forward"),
        ],

        # ── December 2025 (15 days): Winter Concert ───────────────────────────
        (2025, 12): [
            ("'Russian Christmas Music' full movement run; note remaining technical challenges", "concert_prep", "Winter Concert Prep", "No stopping; full movement; circle unresolved passages; prioritize for sectionals"),
            ("'Greensleeves' solo balance coaching: solo voice clearly above accompaniment always", "concert_prep", "Winter Concert Prep", "Soloists practice with accompaniment; balance; expression coaching individual and ensemble"),
            ("Full winter program: 'Russian Christmas Music' + 'Greensleeves'; complete run through", "concert_prep", "Winter Concert Prep", "Crowd-pleasing program; contrast between pieces; professional transitions practiced"),
            ("Woodwind sectional: 'Russian Christmas Music' Allegro woodwind passages at tempo", "concert_prep", "Winter Concert Prep", "Isolated woodwind passages; slow practice; build speed; tune within the section"),
            ("Brass sectional: 'Russian Christmas Music' fanfare sections; unified attacks and tuning", "concert_prep", "Winter Concert Prep", "Fanfare attacks together; tune open chord; match tone quality across all brass voices"),
            ("'Russian Christmas Music' chorale pp opening: start barely audible; patience required", "concert_prep", "Winter Concert Prep", "The opening must start at pp; everyone together; build with patience over 40 measures"),
            ("Sight-reading exercise: advanced Level 4; prepare for spring festival difficulty level", "sight_reading", "Sight-Reading Skills", "Level 4 cold read; score-study approach; 30 seconds; play through once; debrief after"),
            ("Scale assessment: 12 major + 12 harmonic minor; speed and accuracy combined evaluation", "assessment", "Scale Mastery", "Individual assessment; rubric: all 24 scales at q=116 minimum; 2 octaves each"),
            ("Winter concert dress rehearsal: full attire; complete program; no stopping allowed", "concert_prep", "Winter Concert Prep", "Concert attire required; full program from entrance to exit; professional protocol"),
            ("Winter concert final polish: 'Russian Christmas Music' climax; 'Greensleeves' solo peak", "concert_prep", "Winter Concert Prep", "Climax = full energy; solo = expressive and well-balanced; final run through clean"),
            ("Concert day: brief warm-up; uniform check; call time 5:30 PM reminder confirmed", "concert_prep", "Winter Concert Prep", "Brief warm-up; confirm uniform complete; call time 5:30 PM; they are ready"),
            ("WINTER CONCERT — daytime class: final preparation; call time 5:30 PM tonight", "concert", "Winter Concert Prep", "Call time 5:30 PM; concert 7:00 PM; Wind Ensemble excellence expected"),
            ("Post-concert debrief: recording review; judge's-eye critique; compare to Fall Concert", "flex", "Post-Concert", "Write critique as if you were a judge; grade yourself; discuss with class"),
            ("Theory: analyze 'Russian Christmas Music' harmonic language; modal and tonal sections", "theory", "Advanced Theory", "Identify which sections are tonal vs. modal; what scales are used in modal sections?"),
            ("Winter break listening: assign masterwork; return with written observations in January", "listening", "Music Appreciation", "Listen to Holst 'Planets' or Shostakovich 5th; write 3 observations about orchestration"),
        ],

        # ── January 2026 (19 days): Scale Mastery + Spring Masterworks ────────
        (2026, 1): [
            ("New Year warm-up: full chromatic range; long tone pyramids build outward from B-flat", "skill_building", "Advanced Warm-Up", "Chromatic pyramid: B-flat to B to C to D-flat to D; add voices one at a time upward"),
            ("12 major + 12 harmonic minor scales: target all 24 at q=120 by March scale test", "skill_building", "Scale Mastery", "Scale ladder for all 24; daily practice plan distributed; accountability system in place"),
            ("Introduce 'Lincolnshire Posy' mvt.1 'Lisbon' by Percy Grainger (Grade 5); read-through", "concert_prep", "Spring Concert Prep", "Masterwork; Grade 5; mixed meter; Grainger's folk song settings; complex and beautiful"),
            ("Score study: 'Lincolnshire Posy' full score; identify meter changes, folk themes, texture", "theory", "Advanced Theory", "Read score together; map meter changes; identify folk song themes; discuss Grainger's approach"),
            ("'Lincolnshire Posy' mvt.1 meter changes workshop: 3/4 to 5/8 to 2/4; sing before playing", "concert_prep", "Spring Concert Prep", "Sing through meter changes; conduct along; no instruments yet; feel each meter change"),
            ("S&E literature selection: advanced solos from Rubank Advanced, Voxman, contest lists", "concert_prep", "Festival Prep", "Students try advanced literature; appropriate level; self-assess with teacher guidance"),
            ("Listening analysis: share winter break observations; discuss orchestration and style elements", "listening", "Music Appreciation", "Students share written observations; class discussion on masterwork techniques and choices"),
            ("'Lincolnshire Posy' mvt.1 on instruments: very slow; stop at every meter change; clarify", "concert_prep", "Spring Concert Prep", "Very slow first time; stop at each meter change; confirm everyone counts it correctly"),
            ("Second spring piece: 'Rest' by Frank Ticheli (Grade 4); full read-through; discuss context", "concert_prep", "Spring Concert Prep", "Profound emotional work; Ticheli wrote it after a tragedy; read the program note aloud"),
            ("'Rest' — emotional arc of the piece; discuss what 'rest' means in Ticheli's context", "concert_prep", "Spring Concert Prep", "Rest as peace after struggle; how does the music express peace? What does it feel like?"),
            ("Advanced sight-reading Level 4-5: all keys; 16th note runs; score-marking strategies", "sight_reading", "Sight-Reading Skills", "Mark accidentals, meter, danger zones in 30 seconds; then play through once; debrief"),
            ("12 harmonic minor scale check: play 12 at q=116; note progress on accountability chart", "assessment", "Scale Mastery", "Quick assessment; who has all 12? Who needs more time? Accountability chart updated"),
            ("'Lincolnshire Posy' mvt.1 at target tempo: no more slow practice; perform at full tempo", "concert_prep", "Spring Concert Prep", "First time at full tempo; expect difficulties; mark what fell apart; rebuild immediately"),
            ("FSP advanced chorales: complex harmonics with chromatic voice leading; listen closely", "skill_building", "Advanced Warm-Up", "Chromatic chords; each voice leads smoothly to next pitch; listen and adjust constantly"),
            ("'Rest' mm.1-40: opening lyrical section; pp dynamic level; warm, pure, controlled tone", "concert_prep", "Spring Concert Prep", "Very quiet; requires absolute tonal control; every player at the same quiet dynamic level"),
            ("S&E coaching day: individual 8-minute rotations; musicality and expression coaching", "concert_prep", "Festival Prep", "Technical is mostly solved; push for expression and musical communication beyond notes"),
            ("Scale mastery progress: how many of 24 scales are at q=120? Recognition for achievers", "assessment", "Scale Mastery", "Count scales at target; celebrate progress; final push toward March comprehensive test"),
            ("'Lincolnshire Posy' mvt.1 performance-level run: record and discuss critically as class", "concert_prep", "Spring Concert Prep", "Record; listen; class identifies top 3 issues; teacher adds top 3; compare perspectives"),
            ("'Rest' mm.40-80: dynamic climax building; everyone builds together; unified climax point", "concert_prep", "Spring Concert Prep", "Crescendo feels inevitable when everyone builds together; climax hits simultaneously"),
        ],

        # ── February 2026 (15 days): S&E Festival + Spring Prep ──────────────
        (2026, 2): [
            ("'Lincolnshire Posy' meter changes mastery: conduct and play simultaneously; internal tempo", "concert_prep", "Spring Concert Prep", "Students who have it can conduct while playing; test internal tempo through meter changes"),
            ("S&E intensive coaching: 8-min group rotations; musical communication as primary focus", "concert_prep", "Festival Prep", "Push past technical; can you communicate something to the audience? Aim for that goal"),
            ("Third spring piece: 'Fairest of the Fair' march by Sousa (Grade 3.5); read-through", "concert_prep", "Spring Concert Prep", "Sousa march to contrast with serious works; beautiful trio melody; march energy throughout"),
            ("Improvisation workshop: 12-bar blues in B-flat; build a solo over chord changes", "composition", "Jazz & Improv", "Blues scale: B-flat, D-flat, E-flat, E-natural, F, A-flat; volunteer solos; express freely"),
            ("'Rest' full run with full emotional intention; every player thinks about the program note", "concert_prep", "Spring Concert Prep", "Play it with the story in mind; this is about peace after loss; honor that in your tone"),
            ("'Fairest of the Fair' march analysis: intro, 1st strain, 2nd strain, trio; sing trio", "concert_prep", "Spring Concert Prep", "Sing the trio melody before playing; it is one of Sousa's most beautiful and lyrical tunes"),
            ("Advanced sight-reading Level 5: all keys; complex rhythms; 16th runs; discuss strategies", "sight_reading", "Sight-Reading Skills", "State-level difficulty; 30-second scan; mark danger zones; play through; debrief after"),
            ("'Lincolnshire Posy' advanced detail: Grainger's notation; tone clusters; glissandi discussed", "concert_prep", "Spring Concert Prep", "Grainger's unique notation includes glissandi and ossias; discuss and attempt carefully"),
            ("Full spring program rehearsal: 'Lincolnshire Posy' + 'Rest' + 'Fairest of the Fair'", "concert_prep", "Spring Concert Prep", "Full three-piece program; back to back; transitions; time the full program; no stops"),
            ("Composition project: compose 8-bar theme with harmonic accompaniment (due in 2 weeks)", "composition", "Creative Music", "Theme must have clear harmonic function (I, IV, V); present to section for peer feedback"),
            ("Post-mid-winter-break: scale warm-up; FSP chorale; reset ensemble blend and precision", "skill_building", "Technique Builder", "Systematic warm-up restart; tune as if for the first time; establish ensemble blend"),
            ("S&E Festival final preparation: last coaching before Saturday; expression priority", "concert_prep", "Festival Prep", "Final technical touches; biggest remaining fix; play through with full expression"),
            ("'Fairest of the Fair' trio section: trio melody sing and play; everyone loves this tune", "concert_prep", "Spring Concert Prep", "Sing trio; then play; express the beauty of Sousa's most lyrical melody; conductor floats"),
            ("Full program run with recording: listen back immediately and class critiques together", "concert_prep", "Spring Concert Prep", "Record today; listen immediately; class critiques using judge vocabulary; fix top issue"),
            ("S&E Festival logistics and encouragement; professional behavior and performance expectations", "concert_prep", "Festival Prep", "Confirm logistics; encourage; remind: play for the judge as you would for any audience"),
        ],

        # ── March 2026 (21 days): Spring Concert + Large Group Festival Build ──
        (2026, 3): [
            ("S&E Festival debrief: share experiences; analyze judges' feedback together as a class", "flex", "Post-Festival", "Read comments aloud; identify common feedback themes; celebrate all performances"),
            ("'Lincolnshire Posy' mvt.1 at full tempo: technical precision is now the expectation", "concert_prep", "Spring Concert Prep", "No excuses; perform at full tempo; mark errors; address immediately after each run"),
            ("'Rest' emotional arc coaching: each section has a specific emotional purpose discussed", "concert_prep", "Spring Concert Prep", "Map emotional arc: quiet peace → tension → climax → resolution → final rest"),
            ("'Fairest of the Fair' march precision: articulation mastery; no blurring of any rhythms", "concert_prep", "Spring Concert Prep", "Every staccato, accent, slur present; march never blurs; crisp and precise always"),
            ("Comprehensive scale assessment: all 24 scales (12 major + 12 harmonic minor) on record", "assessment", "Scale Mastery", "Individual testing; rubric: all 24 at q=120; 2 octaves min; 50-point total recorded"),
            ("Theory: analyze 'Lincolnshire Posy' modal content; Mixolydian, Dorian, Aeolian modes", "theory", "Advanced Theory", "Identify which passages use which modes; Grainger loved modes; discuss why he used them"),
            ("Sight-reading Level 5: state-level difficulty; modal passages; complex rhythmic patterns", "sight_reading", "Sight-Reading Skills", "State-festival level; discuss what advanced players look for beyond the basic KATS strategy"),
            ("Full program run at performance level: record; students write self-critique homework", "concert_prep", "Spring Concert Prep", "Record; students take recording home; write 5 specific improvements for next class"),
            ("Homework debrief: share self-critiques; address most common issues as full ensemble", "concert_prep", "Spring Concert Prep", "Most common issues = highest impact fixes; address top 3 from homework immediately"),
            ("'Rest' pp control clinic: how quiet can the ensemble get while staying together?", "concert_prep", "Spring Concert Prep", "Decrescendo to the limit; stay together in the silence; hardest skill in ensemble playing"),
            ("Student conductor masterclass: advanced students conduct 'Fairest of the Fair' march", "flex", "Leadership", "Discuss conducting technique; gesture clarity; students give each other constructive feedback"),
            ("'Lincolnshire Posy' — Grainger's text and program notes; historical context for performance", "theory", "Advanced Theory", "Read Grainger's original notes; what was he trying to say? How do we honor that intent?"),
            ("Large Group Festival prep: sight-reading strategy; simulate full festival procedure", "concert_prep", "Festival Prep", "Full simulation: 30-sec scan; class discussion; play; no repeat; debrief each attempt"),
            ("Full program mock performance for invited critical audience; request specific feedback", "concert_prep", "Festival Prep", "Invite principal or music teacher as judge; perform; ask for genuine and specific feedback"),
            ("Apply critical feedback: top 5 issues from mock performance addressed in rehearsal today", "concert_prep", "Festival Prep", "Take specific feedback; address each measure; fix and confirm improvement made"),
            ("'Rest' final run-through: honor the piece; play it with full and complete intention", "concert_prep", "Spring Concert Prep", "This piece requires full commitment; play it with everything you have; honor Ticheli"),
            ("'Fairest of the Fair' trio expressiveness: Sousa's most lyrical theme needs full beauty", "concert_prep", "Spring Concert Prep", "Trio = a moment of beauty in the march; let it breathe; contrast to march energy clearly"),
            ("Scale review: play all 24 from memory in random order; teacher calls the key instantly", "skill_building", "Scale Mastery", "Teacher calls random keys; students play immediately; build instant recall of all 24"),
            ("Full program run: 'Lincolnshire Posy' + 'Rest' + 'Fairest of the Fair' — no stopping", "concert_prep", "Spring Concert Prep", "Performance level; no excuses; this is the standard now; run without stopping"),
            ("Pre-festival logistics: bus, attire, warm-up room, sight-reading room procedure confirmed", "concert_prep", "Festival Prep", "Review all logistics; assign gate-keeper roles; everyone knows the full day schedule"),
            ("Final festival tune-up: run each piece once; nothing new; trust the preparation fully", "concert_prep", "Festival Prep", "One run per piece; no new feedback; reinforce the positives; you are ready"),
        ],

        # ── April 2026 (17 days): Large Group Festival + Spring Concert Final ──
        (2026, 4): [
            ("Festival sight-reading drill: advanced cold read; full festival procedure; debrief after", "sight_reading", "Festival Prep", "Simulate festival exactly; 30-sec scan; discussion allowed; play once; debrief carefully"),
            ("Full program performance-level run for Large Group Festival; record and review critically", "concert_prep", "Festival Prep", "Last full run before festival; performance level; record; review critically as a class"),
            ("'Rest' final polish: every dynamic, breath mark, and emotion; honor Ticheli's intent fully", "concert_prep", "Festival Prep", "This piece should move the judges; play it with everything; honor what Ticheli intended"),
            ("Post-spring-break: scale warm-up; FSP chorale reset; re-establish ensemble precision", "skill_building", "Technique Builder", "Post-break full warm-up; tune as if from scratch; establish precision and blend quickly"),
            ("Large Group Festival logistics final review: bus, attire, performance order, warm-up room", "concert_prep", "Festival Prep", "Final logistics review; everyone knows the schedule; confirm attire and call time"),
            ("Pre-festival pep talk: Wind Ensemble's history, values, and performance standards reviewed", "concert_prep", "Festival Prep", "What does it mean to perform at this level? What are you representing? Discuss as a group"),
            ("Final full program run before festival: no new changes; trust the preparation completely", "concert_prep", "Festival Prep", "One complete run; no stopping; end positively; rest voices and embouchures for tomorrow"),
            ("LARGE GROUP FESTIVAL — target: Superior rating; leave it all on the stage today", "concert", "Festival Prep", "Leave it all on the stage; play for the judges and the music; honor the preparation"),
            ("Festival debrief: read judges' comments aloud; identify common themes; discuss rating", "flex", "Post-Festival", "Read each judge's comment; celebrate achievements; identify one area to improve for concert"),
            ("Student conducting masterclass: 2 volunteer conductors lead 'Fairest of the Fair'", "flex", "Leadership", "Technical conducting feedback; class analyzes each conductor; teacher facilitates"),
            ("Commission project: listen to 5 works being considered for next year; class votes", "listening", "Music Selection", "Play 5-minute excerpts from each candidate; discuss difficulty, value, and interest level"),
            ("Spring concert program: apply festival feedback to all three pieces; specific measures", "concert_prep", "Spring Concert Prep", "Take top 5 judge comments; address each in rehearsal; confirm improvements are made"),
            ("'Lincolnshire Posy' — post-festival refinement: implement judges' specific feedback", "concert_prep", "Spring Concert Prep", "What did judges say specifically? Address each comment in today's rehearsal"),
            ("'Rest' — post-festival refinement: apply judges' feedback on expression and dynamics", "concert_prep", "Spring Concert Prep", "Judges praised or criticized what specifically? Implement every actionable comment"),
            ("Full spring concert program: three pieces + transitions; timed; stage movement rehearsed", "concert_prep", "Spring Concert Prep", "Time the full concert; 20 minutes max; transitions smooth; stage movement clean"),
            ("Sight-reading as daily warm-up: Level 4-5 cold read to keep sight-reading skills sharp", "sight_reading", "Sight-Reading Skills", "Daily cold read keeps skills automatic; short practice pays off over the full year"),
            ("Spring concert final polish: every dynamic, phrase, and technique comprehensively addressed", "concert_prep", "Spring Concert Prep", "Last major rehearsal before final week; fix everything still addressable today"),
        ],

        # ── May 2026 (20 days): Spring Concert + Year End ────────────────────
        (2026, 5): [
            ("Spring concert full program: 'Lincolnshire Posy' + 'Rest' + 'Fairest of the Fair'; full run", "concert_prep", "Spring Concert Prep", "Full performance run; performance level; this is the definitive version; make it great"),
            ("Musicality masterclass: what separates good from great ensembles? Class discussion", "concert_prep", "Spring Concert Prep", "Discuss: tone quality, intonation, expression, commitment, communication, and blend"),
            ("Year-end comprehensive exam: scales, sight-reading, and music theory (written + playing)", "assessment", "Year-End Assessment", "Written theory (20) + playing all 24 scales (20) + 8-bar sight-read (10) = 50 pts"),
            ("Final sectional polish: each section's showcase moment identified and perfected fully", "concert_prep", "Spring Concert Prep", "Every section has a moment in one of the three pieces; make that moment perfect"),
            ("Spring Concert dress rehearsal: concert attire; full program; final preparation", "concert_prep", "Spring Concert Prep", "Dress rehearsal is a real performance; no excuses; perform through everything"),
            ("'Lincolnshire Posy' — final Grainger tribute: play it the way he would have wanted", "concert_prep", "Spring Concert Prep", "Read Grainger's notes one more time; play with full commitment to his original vision"),
            ("'Rest' — final Ticheli tribute: honor the emotional weight of this profound piece", "concert_prep", "Spring Concert Prep", "Ticheli wrote this for a reason; honor that; play with full and complete commitment"),
            ("'Fairest of the Fair' — final Sousa tribute: march energy and trio beauty both present", "concert_prep", "Spring Concert Prep", "Honor Sousa's legacy; every staccato, every accent, every beautiful trio note honored"),
            ("Year-end scale certification: all 24 scales at q=120 minimum; final certification issued", "assessment", "Year-End Assessment", "Certification for completing all 24 scales; this is a Wind Ensemble achievement"),
            ("Concert week: uniform and equipment final check; call time 5:30 PM firmly confirmed", "concert_prep", "Spring Concert Prep", "Everything ready today; no changes after this; visualize and prepare for excellence"),
            ("Full program last run: brief and positive; trust the preparation completely", "concert_prep", "Spring Concert Prep", "One run each piece; celebrate what sounds great; end class on maximum confidence"),
            ("Spring Concert pre-performance mental preparation: visualization and breathing exercises", "concert_prep", "Spring Concert Prep", "Guide visualization: walk on stage; play perfectly; audience is moved; receive applause"),
            ("SPRING CONCERT — year-end gala performance; reception follows the concert tonight", "concert", "Spring Concert Prep", "Call time 5:30 PM; concert 7:00 PM; reception follows; celebrate the full year's work"),
            ("Year-end awards: Sousa Award, Outstanding Musician, section MVPs — recognize every member", "flex", "Year End", "John Philip Sousa Award for outstanding achievement; section MVPs; recognize all members"),
            ("8th grade send-off: congratulations; high school band preview; marching band information", "flex", "Year End", "Discuss HS band expectations; marching band season; audition preparation; proud send-off"),
            ("Post-concert reflection: what made this year's Wind Ensemble special and memorable?", "flex", "Year End", "Group discussion: what are you most proud of? What will you remember about this ensemble?"),
            ("Summer practice assignments: high school audition materials; scale maintenance sheet", "flex", "Year End", "HS audition excerpts distributed; summer scale sheet; daily 20-min practice encouraged"),
            ("Music history deep dive: Grainger, Ticheli, Reed — what made these composers distinctly great?", "listening", "Year End", "Listen to more works by each composer; discuss compositional voice and distinctive style"),
            ("Guest musician if available: BSO or UW professional performs and Q&A session with class", "listening", "Year End", "Professional musician demonstrates; students ask questions; inspiration for the next level"),
            ("Final day: letter to next year's Wind Ensemble; advice and encouragement for successors", "flex", "Year End", "Students write letters; sealed and given to next year's ensemble members in September"),
        ],

        # ── June 2026 (14 days): Year-End ─────────────────────────────────────
        (2026, 6): [
            ("Guest masterclass if available: professional from BSO or UW performs and teaches class", "listening", "Year End", "Live performance; technique demonstration; Q&A; inspiration for high school and beyond"),
            ("Free play / sight-read fun: movie themes, video game music — students choose the set list", "flex", "Year End", "Student-choice playlist; sight-read whatever they want; informal and joyful experience"),
            ("Year-end reflection essay: what made you a better musician this year? What comes next?", "flex", "Year End", "Written reflection; specific examples of growth; goals for high school or next year"),
            ("Student-led mini-concert: volunteer students perform solos or chamber pieces prepared", "flex", "Year End", "Celebrate individual achievement; supportive audience; each performer receives recognition"),
            ("Music theory mastery review: Kahoot with advanced theory from the entire year", "theory", "Year End", "Scales, modes, harmonic analysis, form analysis, Italian terms; competitive and fun"),
            ("Composition showcase: share 8-bar composition from February; reflect on growth since then", "composition", "Year End", "Play original compositions; discuss how they'd revise now; celebrate creativity"),
            ("High school band discussion: what to expect; marching band; concert band; honor ensembles", "flex", "Year End", "Practical information; answer questions; encourage continued music-making at next level"),
            ("Instrument return, locker clean-out, summer assignments; goodbyes and final group photos", "flex", "Year End", "Return all school instruments; audition music distributed; final goodbyes and photos"),
            ("Listening: compare first-day recording to spring concert recording; celebrate remarkable growth", "listening", "Year End", "Play September and spring recordings side by side; how far did this ensemble come?"),
            ("Final celebration: favorite pieces from the year; informal student concert for parents", "flex", "Year End", "Invite parents if possible; play favorite pieces; celebrate the complete year together"),
            ("Professional musician career paths: performance, education, composition, music therapy", "flex", "Year End", "Discuss: performer, educator, composer, arranger, music therapist, audio engineer paths"),
            ("Creative improv jam: class improvises over backing track using modes learned this year", "composition", "Year End", "Modal improvisation; Dorian, Mixolydian; layer improvised lines over a backing track"),
            ("Scale celebration: who achieved all 24 scales? Recognition and certificates distributed", "skill_building", "Year End", "Celebrate scale achievements; distribute certificates; encourage those still working toward it"),
            ("Last day: summer packet, final goodbyes, excitement for high school or next year of band", "flex", "Year End", "Summer practice packet; final photos; goodbyes; well wishes for all the next steps ahead"),
        ],
    }

    return _build_items(school_days, monthly)


# ─── Main ─────────────────────────────────────────────────────────────────────

# ─── Lesson Plan Generation ──────────────────────────────────────────────────

_STANDARDS = {
    "skill_building": (
        "MU:Pr5.1.8b — Apply feedback to refine and improve individual and ensemble performance.\n"
        "MU:Pr4.2.8a — Demonstrate understanding of the structure and elements of music "
        "(e.g., rhythm, pitch, form, texture/timbre/dynamics) in selected works."
    ),
    "concert_prep": (
        "MU:Pr6.1.8a — Perform the music with technical accuracy and expressive qualities "
        "to convey the creator's intent.\n"
        "MU:Pr5.1.8b — Apply established and collaboratively developed criteria and feedback "
        "to evaluate and refine ensemble performance."
    ),
    "concert": (
        "MU:Pr6.1.8a — Perform music with technical accuracy and expressive qualities to "
        "convey the creator's intent.\n"
        "MU:Pr6.1.8b — Demonstrate performance decorum and audience etiquette appropriate "
        "for the context, purpose, and style."
    ),
    "assessment": (
        "MU:Pr5.1.8a — Apply established criteria to judge the accuracy, expressiveness, "
        "and effectiveness of individual and ensemble performances."
    ),
    "sight_reading": (
        "MU:Pr4.2.8a — Demonstrate understanding of the structure and elements of music "
        "in works selected for performance.\n"
        "MU:Pr4.3.8 — Apply teacher-provided and collaboratively developed criteria to "
        "evaluate accuracy and expressiveness of sight-reading."
    ),
    "theory": (
        "MU:Re7.2.8a — Explain how analysis of passages and understanding of style, genre, "
        "and musical elements inform the response to music.\n"
        "MU:Cr1.1.8b — Generate musical ideas using understanding of music notation, "
        "theory, and compositional techniques."
    ),
    "composition": (
        "MU:Cr2.1.8a — Select, organize, and document musical ideas for defined purposes "
        "and contexts using appropriate notation.\n"
        "MU:Cr1.1.8a — Compose or improvise ideas for a melody using elements of music."
    ),
    "listening": (
        "MU:Re7.1.8a — Select or choose music to listen to and explain the connections "
        "to specific interests or experiences for a specific purpose.\n"
        "MU:Re8.1.8a — Explain how performers' and personal interpretations of musical "
        "elements reflect expressive intent."
    ),
    "flex": (
        "MU:Cn10.0.8a — Demonstrate how interests, knowledge, and skills relate to "
        "personal choices and intent when creating, performing, and responding to music."
    ),
}

# Eight warm-up rotations for intermediate/entry/advanced levels
_WARMUPS_STANDARD = [
    ("Long tones on B-flat concert scale: sustain each pitch for 4 beats at q=60. "
     "Breathe in 4 counts, sustain 4 counts. Focus on centered tone, supported air column, "
     "relaxed embouchure. Listen across sections for matching pitch."),
    ("B-flat major scale: ascending and descending, first tongued (q=80) then slurred (q=80). "
     "Keep air moving continuously through all slurs. "
     "Goal: identical tone quality whether tongued or slurred."),
    ("Rhythm echo warm-up: teacher claps a 2-bar pattern in 4/4; class echoes in unison on stand. "
     "Increase complexity each round (add eighth rests, dotted quarter patterns). "
     "After 3 patterns, transfer to instrument on concert B-flat."),
    ("Chorale warm-up: play a 4-bar I–IV–V–I progression in B-flat concert, whole notes. "
     "Hold each chord until all sections are in tune. No vibrato. Listen vertically — "
     "match pitch and blend within your section before blending across the ensemble."),
    ("Chromatic scale: from low B-flat (concert) ascending one octave, half notes at q=60. "
     "Name each pitch aloud on first pass. Focus on smooth voice connections and "
     "consistent tone quality on every half step."),
    ("Articulation pattern on B-flat scale: tongue–tongue–slur–slur (ta-ta-la-la). "
     "Repeat reversed: slur–slur–tongue–tongue. Keep steady air; "
     "only the tongue stops the note — never the air."),
    ("Dynamic control warm-up: B-flat scale pp ascending, ff descending. "
     "Repeat: mp ascending, mf descending. Focus on consistent tone center at "
     "all dynamic levels. Air support must increase at louder dynamics."),
    ("4-bar sight-reading warm-up written on board. Apply KATS: Key signature, "
     "Accidentals, Time signature, Scan for tricky rhythms. 30-second prep — "
     "then play once without stopping. Debrief: what would you fix on a second read?"),
]

_WARMUPS_ENTRY = [
    ("Long tones: B-flat concert, hold 4 beats at q=60. Teacher counts aloud. "
     "Breathe together — all sections in and out on the same count. "
     "Check posture: feet flat, bell angle correct, music stand at eye level."),
    ("B-flat major scale, tongued only, q=72 ascending and descending. "
     "Count aloud before playing. Clap the rhythm of the scale first, then play. "
     "Goal: every note even length, no rushing."),
    ("Rhythm clapping: teacher claps quarter–eighth–eighth–half pattern; class echoes. "
     "Then add quarter rest. Clap on stand, say syllables aloud (ta, ta-di, ta-a). "
     "Then play rhythm on concert B-flat."),
    ("Sustained chord: teacher plays B-flat drone; class joins one section at a time. "
     "Listen for when your section blends. Hold 8 beats. Breathe together. "
     "Add one section per repeat until full ensemble is playing."),
    ("B-flat scale by instrument family: woodwinds alone, then brass alone, then together. "
     "Listen for matching pitch between families. "
     "Count subdivisions aloud before playing."),
    ("Articulation echo: teacher demonstrates staccato, legato, accent — class echoes each "
     "style on concert B-flat. Three repetitions of each. "
     "Articulation starts with the tongue, not the air."),
    ("Soft dynamics practice: play B-flat scale at p. "
     "Open the throat, keep air flowing — don't squeeze. "
     "Compare soft vs. loud tone quality."),
    ("Short sight-reading warm-up: teacher writes 4-beat rhythm on board. "
     "Students clap first, then play on concert B-flat. One try with prep, "
     "one without. Focus on rhythm accuracy, not pitch."),
]

_WARMUPS_ADVANCED = [
    ("Long tones on chromatic scale: half steps from low B-flat ascending a full octave. "
     "Sustain each pitch 4 beats; adjust tuning by ear with drone. "
     "Brass: add lip slurs between adjacent scale degrees."),
    ("Scales in thirds: B-flat major ascending and descending, q=92. "
     "Then E-flat major in thirds. Maintain even tone quality. "
     "Goal: no accent on beat 1 — even emphasis throughout."),
    ("Rhythm dictation: teacher plays a 2-bar rhythm; students notate it. "
     "Verify together. Then play it on a B-flat major scale fragment. "
     "Check: are you hearing the subdivision between notes?"),
    ("4-part chorale: SATB voicing in B-flat, teacher assigns parts. "
     "Whole notes; first chord held until perfectly in tune. "
     "Listen to the overtone series — tune to the fundamental, not the melody."),
    ("Chromatic scale: two octaves at q=80, ascending and descending. "
     "Brass: lip slurs on each pitch (1–1.5 octave slurs). "
     "Focus on smooth register transitions."),
    ("Articulation contrast at speed: tongue–tongue–slur–slur on B-flat major scale q=96. "
     "Then marcato on scale degrees 1–3–5–8–5–3–1. "
     "Clean releases — no scooping into notes."),
    ("Dynamic range: pp to ff on a single sustained B-flat, 8 counts each way. "
     "Control the crescendo — no sudden jump. Decrescendo to pp without pinching. "
     "Apply same dynamic arch to the B-flat major scale."),
    ("Sight-reading warm-up at grade 3+ difficulty: 8 bars on board. "
     "KATS strategy, 30-second silent prep. Play once, identify top 2 issues. "
     "Play again targeting only those 2 issues."),
]


def _warmup_text(day_idx, level):
    if level == "entry":
        pool = _WARMUPS_ENTRY
    elif level == "advanced":
        pool = _WARMUPS_ADVANCED
    else:
        pool = _WARMUPS_STANDARD
    return pool[day_idx % len(pool)]


def _objectives(summary, activity_type, unit_name):
    core = summary.split(";")[0].strip().rstrip(".")
    core_lc = core[0].lower() + core[1:] if core else summary
    action = {
        "skill_building":  "accurately demonstrate",
        "concert_prep":    "rehearse and refine",
        "concert":         "perform",
        "assessment":      "demonstrate mastery of",
        "sight_reading":   "apply sight-reading strategies to",
        "theory":          "identify and explain",
        "composition":     "create and notate",
        "listening":       "analyze and describe",
        "flex":            "engage with",
    }.get(activity_type, "demonstrate")
    unit_ref = unit_name if unit_name else "the current unit"
    return (
        f"Students will {action} {core_lc}.\n"
        f"Students will connect this activity to the goals of {unit_ref}."
    )


def _assessment_for(activity_type, summary):
    s = summary.lower()
    if activity_type == "assessment":
        if "scale" in s or "b-flat" in s or "major" in s:
            return (
                "Playing test",
                "Scale accuracy check — tone quality (5 pts), fingering accuracy (5 pts), "
                "rhythmic evenness (5 pts), intonation (5 pts). "
                "Rotate sections during rehearsal; record results in gradebook.",
            )
        elif "quiz" in s or "bingo" in s or "theory" in s:
            return (
                "Written quiz",
                "Written theory quiz: matching (note values / Italian terms), "
                "fill-in (key signatures), short answer (one rhythm or form concept). "
                "Completed individually; self-check with class after.",
            )
        else:
            return (
                "Observation rubric",
                "Observation rubric (20 pts): tone quality (5), rhythmic accuracy (5), "
                "dynamics followed (5), posture and position (5). "
                "Rotate through sections; mark rubric during rehearsal.",
            )
    elif activity_type == "sight_reading":
        return (
            "Exit ticket",
            "After sight-reading: students write on an index card — "
            "1) one thing they executed well, 2) one rhythm or pitch issue to fix next time. "
            "Collected at door.",
        )
    elif activity_type == "concert":
        return (
            "Observation rubric",
            "Concert rubric: technical accuracy (5), expressive qualities (5), "
            "stage presence and decorum (5), ensemble listening and balance (5). "
            "Completed by director during performance.",
        )
    elif activity_type == "theory":
        return (
            "Exit ticket",
            "3-2-1 exit ticket: 3 things learned today, 2 things to remember, "
            "1 question still remaining. Collected on a sticky note before leaving.",
        )
    else:
        return ("None", "")


def _differentiation(activity_type, level):
    iep = (
        "Check IEP/504 files before class for any students requiring accommodations "
        "(extended time, alternate seating, adapted materials). "
        "Consult with the special education coordinator as needed."
    )
    if activity_type in ("skill_building", "concert_prep"):
        adv = (
            "Advanced: assign a second part or harmony line if available; "
            "increase personal tempo target by 8–10 BPM; "
            "challenge with expressive phrasing (crescendo, decrescendo, vibrato if applicable)."
        )
        str_ = (
            "Struggling: reduce range to comfortable middle register; "
            "practice at 70% of target tempo; provide fingering chart reference card; "
            "pair with a section buddy for peer modeling."
        )
    elif activity_type == "theory":
        adv = (
            "Advanced: apply the concept to a different key or meter; "
            "compose a 4-bar example using today's concept; "
            "explain the concept to a peer in their own words."
        )
        str_ = (
            "Struggling: use visual aids and color-coded notation; "
            "reduce to the single core concept only; "
            "provide a worked example to trace before completing independently."
        )
    elif activity_type == "sight_reading":
        adv = (
            "Advanced: sight-read an additional harder passage; "
            "add dynamics and articulation on second read; "
            "identify the form of the excerpt after playing."
        )
        str_ = (
            "Struggling: pre-scan with teacher before the group attempt; "
            "isolate rhythm only (play on one pitch first); "
            "allow one extra preparation minute before playing."
        )
    elif activity_type == "assessment":
        adv = (
            "Advanced: demonstrate at a higher tempo or add expressive details; "
            "offer an optional challenge passage at the next difficulty level."
        )
        str_ = (
            "Struggling: assess a shorter excerpt (first 4 bars only); "
            "allow one practice run-through before scoring; "
            "focus rubric on tone and rhythm, defer dynamics if needed."
        )
    elif activity_type == "listening":
        adv = (
            "Advanced: write a short paragraph comparing the recording to our ensemble; "
            "identify specific techniques the professional ensemble uses that we should adopt."
        )
        str_ = (
            "Struggling: provide a graphic organizer with specific listening prompts; "
            "focus attention on one musical element at a time."
        )
    elif activity_type == "concert":
        adv = (
            "Advanced: take on a section leader role; "
            "model stage entrance and posture for the ensemble."
        )
        str_ = (
            "Struggling: review music folder order and stage cues individually beforehand; "
            "assign a peer buddy to sit beside them for stage navigation."
        )
    else:
        adv = (
            "Advanced: increase complexity, add expressive layers, "
            "or take on a leadership role in the activity."
        )
        str_ = (
            "Struggling: simplify the task, reduce tempo, "
            "or provide additional teacher modeling and one-on-one support."
        )
    return adv, str_, iep


def _build_lesson_plan(item, level, day_idx):
    """Generate a lesson_plan dict for a curriculum_item row (sqlite3.Row or dict-like)."""
    activity_type = item["activity_type"] or "skill_building"
    summary       = item["summary"]   or ""
    unit_name     = item["unit_name"] or ""
    notes         = item["notes"]     or ""
    a_type, a_det = _assessment_for(activity_type, summary)
    d_adv, d_str, d_iep = _differentiation(activity_type, level)
    return {
        "curriculum_item_id":         item["id"],
        "objectives":                 _objectives(summary, activity_type, unit_name),
        "standards":                  _STANDARDS.get(activity_type, _STANDARDS["skill_building"]),
        "warmup_text":                _warmup_text(day_idx, level),
        "warmup_template_id":         None,
        "assessment_type":            a_type,
        "assessment_details":         a_det,
        "differentiation_advanced":   d_adv,
        "differentiation_struggling": d_str,
        "differentiation_iep":        d_iep,
        "reflection_text":            "",
        "reflection_rating":          "",
        "status":                     "draft",
        "total_minutes_planned":      45,
        "notes":                      notes,
    }


def _bulk_insert_lesson_plans(db_path, plans):
    """Bulk-insert lesson_plan rows using direct sqlite3."""
    if not plans:
        return
    cols = [
        "curriculum_item_id", "objectives", "standards",
        "warmup_text", "warmup_template_id",
        "assessment_type", "assessment_details",
        "differentiation_advanced", "differentiation_struggling", "differentiation_iep",
        "reflection_text", "reflection_rating",
        "status", "total_minutes_planned", "notes",
    ]
    placeholders = ",".join("?" * len(cols))
    col_str      = ",".join(cols)
    rows = [tuple(p[c] for c in cols) for p in plans]
    with sqlite3.connect(db_path) as conn:
        conn.executemany(
            f"INSERT INTO lesson_plans ({col_str}) VALUES ({placeholders})", rows
        )
        conn.commit()


def _get_lp_rows_for_class(db_path, class_id):
    """Return (lp_id, activity_type, summary, unit_name, notes) rows ordered by date."""
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        return conn.execute(
            "SELECT lp.id AS lp_id, ci.activity_type, ci.summary, ci.unit_name, ci.notes "
            "FROM lesson_plans lp "
            "JOIN curriculum_items ci ON ci.id = lp.curriculum_item_id "
            "WHERE ci.class_id = ? "
            "ORDER BY ci.item_date",
            (class_id,),
        ).fetchall()


def _warmup_brief(day_idx, level):
    """Return a short warm-up label (first clause) for use inside activity block descriptions."""
    full = _warmup_text(day_idx, level)
    first = full.split(".")[0]
    return first[:80]


def _blk(block_type, title, description, minutes, order,
         technique="", grouping="full ensemble", difficulty="Medium", notes=""):
    return {
        "block_type":       block_type,
        "title":            title,
        "description":      description,
        "duration_minutes": minutes,
        "sort_order":       order,
        "music_piece_id":   None,
        "measure_start":    None,
        "measure_end":      None,
        "technique_focus":  technique,
        "grouping":         grouping,
        "difficulty_level": difficulty,
        "notes":            notes,
    }


def _build_blocks(activity_type, summary, unit_name, ci_notes, level, day_idx):
    """Return a list of activity block dicts (no lesson_plan_id) for one lesson."""
    core       = summary.split(";")[0].strip().rstrip(".")
    core_s     = core[:55]           # short version for titles
    wu         = _warmup_brief(day_idx, level)
    notes_snip = (ci_notes or "")[:80]
    diff_map   = {"entry": "Easy", "intermediate": "Medium", "advanced": "Hard"}
    diff       = diff_map.get(level, "Medium")

    if activity_type == "concert_prep":
        return [
            _blk("warmup",    "Warm-Up & Tune",
                 f"Warm-up: {wu}. Sustain a B-flat chord; adjust pitch by ear before proceeding.",
                 5,  0, "intonation and blend"),
            _blk("rehearsal", f"Rehearsal: {core_s}",
                 f"Targeted rehearsal: {core}. Slow-drill problem measures; rebuild speed.",
                 20, 1, "rhythm accuracy and dynamics"),
            _blk("sectional", "Section Refinement",
                 "Section-specific work on problem spots from last class. "
                 "Woodwinds: tone/intonation. Brass: entrances and releases. Percussion: blend.",
                 12, 2, "tone quality and precision", "by section"),
            _blk("rehearsal", "Full Run-Through",
                 f"Run current {unit_name or 'concert'} piece(s) start to finish without stopping. "
                 "Mark problem spots with pencil; address next class.",
                 7,  3, "performance flow"),
            _blk("custom",    "Debrief",
                 "Quick debrief: name one thing that went well and one top fix for next class.",
                 1,  4),
        ]

    elif activity_type == "skill_building":
        return [
            _blk("warmup",    "Warm-Up",
                 f"Warm-up: {wu}.",
                 7,  0, "tone and intonation"),
            _blk("rehearsal", "Scales & Technique",
                 "B-flat major scale ascending/descending — tongued then slurred. "
                 "Goal: matched tone quality between articulation styles.",
                 8,  1, "scale and tone"),
            _blk("theory",    f"Skill: {core_s}",
                 f"Main instruction: {core}. {notes_snip}",
                 20, 2, core_s[:30]),
            _blk("rehearsal", "Apply to Repertoire",
                 f"Transfer today's skill ({core_s}) directly into a passage from current concert music.",
                 7,  3, "musical application"),
            _blk("custom",    "Closure",
                 "Thumbs up/sideways/down for today's skill. Preview tomorrow's focus.",
                 3,  4),
        ]

    elif activity_type == "theory":
        return [
            _blk("warmup",    "Warm-Up",
                 f"Warm-up: {wu}.",
                 7,  0),
            _blk("theory",    f"Concept: {core_s}",
                 f"Theory instruction: {core}. Use whiteboard, notation examples, and call-and-response.",
                 13, 1, core_s[:30]),
            _blk("theory",    "Practice & Application",
                 f"Students apply today's concept: clap, notate, or play examples on instrument. {notes_snip}",
                 15, 2),
            _blk("rehearsal", "Connect to Repertoire",
                 "Locate and play the passage in current concert music where today's concept appears.",
                 7,  3),
            _blk("custom",    "Exit Ticket",
                 "3-2-1 exit ticket: 3 things learned, 2 to remember, 1 question. Collected at door.",
                 3,  4),
        ]

    elif activity_type == "assessment":
        return [
            _blk("warmup",    "Warm-Up",
                 f"Brief warm-up: {wu}.",
                 5,  0),
            _blk("custom",    f"Assessment: {core_s}",
                 f"Assessment rotation: {core}. Teacher scores with rubric while other sections "
                 "practice assigned passage quietly.",
                 30, 1, "accuracy and tone", "rotating sections"),
            _blk("custom",    "Independent Section Practice",
                 "Sections waiting to be assessed review current concert music independently "
                 "or with section leader.",
                 8,  2, "", "by section"),
            _blk("custom",    "Feedback & Debrief",
                 "Return rubrics. Quick debrief: class trends, what to prioritize before next assessment.",
                 2,  3),
        ]

    elif activity_type == "sight_reading":
        return [
            _blk("warmup",       "Warm-Up",
                 f"Warm-up: {wu}.",
                 5,  0),
            _blk("theory",       "KATS Strategy Review",
                 "Review KATS sight-reading strategy: Key signature → Accidentals → Time signature → Scan. "
                 "Teacher models one example on board.",
                 5,  1, "sight-reading strategy"),
            _blk("sight_reading", f"Sight-Read: {core_s}",
                 f"{core}. 30-second prep, then play without stopping. No correction during reading.",
                 25, 2, "rhythm and pitch accuracy", "full ensemble", diff),
            _blk("custom",        "Debrief & Re-Read",
                 "Debrief: what was hardest? Identify top fix, then sight-read the excerpt again.",
                 10, 3),
        ]

    elif activity_type == "concert":
        return [
            _blk("custom",    "Pre-Concert Setup & Tune",
                 "Tune all instruments, confirm music folder order, review stage entrance and bow procedure.",
                 10, 0, "intonation"),
            _blk("rehearsal", "Performance",
                 f"Full concert performance: {unit_name or 'concert program'}.",
                 25, 1, "expressive performance"),
            _blk("custom",    "Post-Concert Debrief",
                 "Celebrate success. Quick director feedback. Logistics for instrument pack-out.",
                 10, 2),
        ]

    elif activity_type == "listening":
        return [
            _blk("warmup",    "Warm-Up",
                 f"Warm-up: {wu}.",
                 5,  0),
            _blk("listening", f"Context: {core_s}",
                 f"Background on {core_s}: composer, style, historical period, and performance context.",
                 5,  1),
            _blk("listening", "Active Listening",
                 f"Active listening: {core}. Use graphic organizer with focus elements "
                 "(dynamics, timbre, form, texture).",
                 20, 2, "musical elements"),
            _blk("custom",    "Discussion",
                 "Class discussion: what did you notice? How does this connect to our ensemble sound?",
                 12, 3),
            _blk("rehearsal", "Apply to Repertoire",
                 "Can we apply any observed techniques to our current concert music? Try one passage.",
                 3,  4),
        ]

    elif activity_type == "composition":
        return [
            _blk("warmup",      "Warm-Up",
                 f"Warm-up: {wu}.",
                 5,  0),
            _blk("theory",      f"Instruction: {core_s}",
                 f"Composition instruction: {core}. Model process on whiteboard with class.",
                 10, 1),
            _blk("composition", "Work Time",
                 f"Independent/partner composition: {core_s}. Teacher circulates and guides.",
                 25, 2, "melody and rhythm"),
            _blk("custom",      "Share-Out",
                 "Volunteers share composition. Class gives specific, kind, helpful feedback.",
                 5,  3),
        ]

    else:  # flex, post-concert, or unrecognized
        return [
            _blk("warmup",  "Warm-Up",
                 f"Warm-up: {wu}.",
                 5,  0),
            _blk("custom",  core_s or "Class Activity",
                 f"{core}. {notes_snip}".strip(),
                 32, 1),
            _blk("custom",  "Reflection & Closure",
                 "Rate today's class 1–5. What was most valuable? Preview next class focus.",
                 8,  2),
        ]


def _bulk_insert_lesson_blocks(db_path, blocks):
    """Bulk-insert lesson_block rows using direct sqlite3."""
    if not blocks:
        return
    cols = [
        "lesson_plan_id", "block_type", "title", "description",
        "duration_minutes", "sort_order",
        "music_piece_id", "measure_start", "measure_end",
        "technique_focus", "grouping", "difficulty_level", "notes",
    ]
    placeholders = ",".join("?" * len(cols))
    col_str      = ",".join(cols)
    rows = [tuple(b[c] for c in cols) for b in blocks]
    with sqlite3.connect(db_path) as conn:
        conn.executemany(
            f"INSERT INTO lesson_blocks ({col_str}) VALUES ({placeholders})", rows
        )
        conn.commit()


def main():
    replace_mode = "--replace" in sys.argv
    args = [a for a in sys.argv[1:] if not a.startswith("--")]

    # ── Locate the database ────────────────────────────────────────────────────
    db_path = None

    if args:
        db_path = args[0]
        if not os.path.exists(db_path):
            print(f"ERROR: Database not found at: {db_path}")
            return
        print(f"Using specified database: {db_path}")
    else:
        local_app_data = os.environ.get("LOCALAPPDATA", "")
        profiles_dir = os.path.join(local_app_data, "RokasResonance", "profiles") if local_app_data else ""

        if profiles_dir and os.path.isdir(profiles_dir):
            found_profiles = []
            for profile in os.listdir(profiles_dir):
                candidate = os.path.join(profiles_dir, profile, "rokas_resonance.db")
                if os.path.exists(candidate):
                    found_profiles.append((profile, candidate))

            if len(found_profiles) == 1:
                db_path = found_profiles[0][1]
                print(f"Using profile database: {found_profiles[0][0]}")
                print(f"  Path: {db_path}")
            elif len(found_profiles) > 1:
                print("Multiple profiles found:")
                for i, (name, path) in enumerate(found_profiles):
                    print(f"  {i+1}. {name} — {path}")
                choice = input(f"Select profile (1-{len(found_profiles)}): ").strip()
                try:
                    idx = int(choice) - 1
                    db_path = found_profiles[idx][1]
                    print(f"Using: {found_profiles[idx][0]}")
                except (ValueError, IndexError):
                    print("Invalid choice. Exiting.")
                    return

        if not db_path:
            fallback = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rokas_resonance.db")
            if os.path.exists(fallback):
                db_path = fallback
                print(f"Using local database: {db_path}")
            else:
                print("No database found!")
                print("Run the app first to create a profile, then try again.")
                print("Or specify a path: python seed_band_curriculum.py <path_to_db>")
                return

    db = Database(db_path)
    school_days = get_school_days()
    print(f"School year: {SCHOOL_START} to {SCHOOL_END}")
    print(f"Total school days: {len(school_days)}")
    if replace_mode:
        print("Mode: --replace (will clear and re-seed existing curriculum items)")

    # ── Class definitions ──────────────────────────────────────────────────────
    classes = [
        {
            "class_name": "Entry Band",
            "ensemble_type": "Band",
            "grade_levels": "6",
            "skill_level": "Beginning",
            "period": "2",
            "days_of_week": "M,T,W,Th,F",
            "class_duration": 45,
            "student_count": 65,
            "method_book": "Essential Elements Book 2",
            "school_year": "2025-2026",
            "room": "Band Room",
            "notes": "MU_101 — Performance-based; day and evening performances required. "
                     "Students with ~1 year experience. New students may need accelerated plan.",
        },
        {
            "class_name": "Intermediate Band",
            "ensemble_type": "Band",
            "grade_levels": "7",
            "skill_level": "Intermediate",
            "period": "3",
            "days_of_week": "M,T,W,Th,F",
            "class_duration": 45,
            "student_count": 52,
            "method_book": "Essential Elements Book 2-3; Foundations for Superior Performance",
            "school_year": "2025-2026",
            "room": "Band Room",
            "notes": "MU_201 — Completed Entry Band. Chair auditions in September. "
                     "Intermediate theory, articulation, rhythm, and musical styles.",
        },
        {
            "class_name": "Advanced Band",
            "ensemble_type": "Band",
            "grade_levels": "7-8",
            "skill_level": "Advanced",
            "period": "4",
            "days_of_week": "M,T,W,Th,F",
            "class_duration": 45,
            "student_count": 48,
            "method_book": "Foundations for Superior Performance; Concert repertoire",
            "school_year": "2025-2026",
            "room": "Band Room",
            "notes": "MU_301 — Wind Ensemble. Audition required. Compound meters, advanced "
                     "articulation, form. Multi-graded (7th and 8th graders).",
        },
    ]

    generators = [generate_entry_band, generate_intermediate_band, generate_advanced_band]
    levels     = ["entry",             "intermediate",              "advanced"]

    existing = db.get_all_classes(school_year="2025-2026")
    existing_map = {c["class_name"]: c["id"] for c in existing}

    for cls_data, generator, level in zip(classes, generators, levels):
        name = cls_data["class_name"]

        if name in existing_map:
            if replace_mode:
                class_id = existing_map[name]
                print(f"\n♻️  Replacing curriculum for '{name}' (ID: {class_id})")
                with sqlite3.connect(db_path) as raw_conn:
                    # Cascade: lesson_blocks → lesson_plan_resources → lesson_plans → curriculum_items
                    raw_conn.execute(
                        "DELETE FROM lesson_blocks WHERE lesson_plan_id IN "
                        "(SELECT id FROM lesson_plans WHERE curriculum_item_id IN "
                        "(SELECT id FROM curriculum_items WHERE class_id = ?))",
                        (class_id,),
                    )
                    raw_conn.execute(
                        "DELETE FROM lesson_plan_resources WHERE lesson_plan_id IN "
                        "(SELECT id FROM lesson_plans WHERE curriculum_item_id IN "
                        "(SELECT id FROM curriculum_items WHERE class_id = ?))",
                        (class_id,),
                    )
                    raw_conn.execute(
                        "DELETE FROM lesson_plans WHERE curriculum_item_id IN "
                        "(SELECT id FROM curriculum_items WHERE class_id = ?)",
                        (class_id,),
                    )
                    raw_conn.execute(
                        "DELETE FROM curriculum_items WHERE class_id = ?", (class_id,)
                    )
                    raw_conn.commit()
            else:
                print(f"\n⚠️  '{name}' already exists — skipping (use --replace to re-seed)")
                continue
        else:
            class_id = db.add_class(cls_data)
            print(f"\n✅ Created '{name}' (ID: {class_id})")

            # Add concert dates for new classes
            for event_name, concert_date in CONCERTS.items():
                db.add_concert_date({
                    "class_id": class_id,
                    "concert_date": concert_date.isoformat(),
                    "event_name": event_name,
                    "location": "Chinook Middle School Gymnasium" if "Concert" in event_name else "District Venue",
                    "notes": "",
                })
            print(f"   Added {len(CONCERTS)} concert dates")

        # Generate and insert curriculum items
        curriculum_items = generator(school_days)
        for item in curriculum_items:
            item["class_id"] = class_id

        db.bulk_add_curriculum_items(curriculum_items)
        print(f"   Seeded {len(curriculum_items)} curriculum items ({school_days[0]} to {school_days[-1]})")

        # Generate and insert lesson plans (one per curriculum item)
        ci_rows = db.get_curriculum_items(class_id)
        lesson_plans = [_build_lesson_plan(row, level, idx) for idx, row in enumerate(ci_rows)]
        _bulk_insert_lesson_plans(db_path, lesson_plans)
        print(f"   Seeded {len(lesson_plans)} lesson plans")

        # Generate and insert activity blocks (fetch LP IDs first)
        lp_rows = _get_lp_rows_for_class(db_path, class_id)
        blocks = []
        for day_idx, row in enumerate(lp_rows):
            for blk in _build_blocks(
                row["activity_type"], row["summary"], row["unit_name"],
                row["notes"] or "", level, day_idx
            ):
                blk["lesson_plan_id"] = row["lp_id"]
                blocks.append(blk)
        _bulk_insert_lesson_blocks(db_path, blocks)
        print(f"   Seeded {len(blocks)} activity blocks")

    # Summary
    stats = db.get_lesson_plan_stats()
    with sqlite3.connect(db_path) as _c:
        total_blocks = _c.execute("SELECT COUNT(*) FROM lesson_blocks").fetchone()[0]
    print(f"\n{'='*60}")
    print(f"Database seeded successfully!")
    print(f"  Classes:           {stats['classes']}")
    print(f"  Curriculum items:  {stats['curriculum_items']}")
    print(f"  Lesson plans:      {stats['lesson_plans']}")
    print(f"  Activity blocks:   {total_blocks}")
    print(f"  Upcoming concerts: {stats['upcoming_concerts']}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
