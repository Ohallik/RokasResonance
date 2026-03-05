"""
Music database audit fix script.
Fixes wrong titles, wrong composers, removes duplicates/collections,
updates source_file references, and adds missing pieces.
"""
import sqlite3, os

DB = r'c:\Users\natem\AppData\Local\RokasResonance\profiles\Meagan R. Mangum\rokas_resonance.db'
PICS = "C:/Users/natem/Downloads/MusicPics"

def p(path): return f"{PICS}/{path}"

conn = sqlite3.connect(DB)
c = conn.cursor()

# ── DELETES ──────────────────────────────────────────────────────────────────
# IDs to delete (garbage, collections, confirmed duplicates with inferior data)
delete_ids = [
    1,    # "El Ritmo de Vida - Washut" dup of 192 (wrong format)
    2,    # "mm" – garbage OCR
    9,    # "First Jazz Performance" – book title, not a piece
    10,   # "First Jazz Performance" – duplicate book title
    11,   # "Rock Charts" – collection section name
    16,   # "Unison Solos 15" – exercise section
    17,   # "Improvisation Starters" – exercise section
    20,   # "Unison Solos 15" – duplicate exercise section
    21,   # "Improvisation Starters" – duplicate exercise section
    23,   # "Rhythm Studies 15" – exercise section
    51,   # "Ain't The Phip" – unidentifiable garbled entry
    75,   # Ain't Misbehavin' – keep 281 (fullest composer credit)
    88,   # St. Louis Blues – dup of 48
    90,   # Ain't Misbehavin' – dup, keep 281
    91,   # All of Me – dup, keep 25
    95,   # Don't Get Around Much Anymore – dup, keep 181
    96,   # Fly Me to the Moon – dup, keep 80
    97,   # Georgia on My Mind – dup, keep 195
    100,  # In a Sentimental Mood – dup, keep 31
    102,  # Misty – dup, keep 67
    104,  # Satin Doll – dup, keep 43
    105,  # Summertime – dup, keep 71
    106,  # Take the 'A' Train – dup, keep 157
    119,  # "First Year Charts Collection for Jazz Ensemble" – collection title
    125,  # Malague?a – dup of 56
    126,  # Malague?a – dup of 56
    130,  # Malague?a – dup of 56
    132,  # "The Les Hooper Silver Series" – collection name
    133,  # "Jazz Classics for the YOUNG ENSEMBLE" – collection name
    136,  # Mood Indigo – dup, keep 134
    147,  # Route 66 – dup, keep 87
    148,  # Over the Rainbow – dup, keep 115
    155,  # Summertime – dup, keep 71
    163,  # Swingin' Shepherd Blues – wrong composer dup, keep 4
    170,  # Caravan – dup, keep 78
    186,  # "EASY PAK #31" – collection/marketing name
    188,  # On Green Dolphin Street – dup, keep 69
    202,  # Freddie Freeloader – dup, keep 28
    207,  # In a Sentimental Mood – dup, keep 31
    210,  # Here's That Rainy Day – wrong composer dup, keep 203
    211,  # "Jazz Classics for the Young Ensemble" – collection name
    214,  # Killer Joe (Billy Eckstine) – wrong composer dup, keep 55
    216,  # Leap Frog (D.A.H.) – wrong composer dup, keep 120
    217,  # It's Only a Paper Moon – dup, keep 215
    220,  # "Festival Classics" – collection name
    221,  # "Beginning Band Series" (Edmondson) – collection name
    247,  # "Beginning Band Series" (McGinty) – collection name
    273,  # All of Me – dup, keep 25
    282,  # April In Paris – dup, keep 278
    284,  # "Discovery! Jazz" – collection name
    285,  # "Sammy Nestico" – collection name
    288,  # Blue and Sentimental – dup, keep 168
    290,  # "Young Jazz Ensemble" – collection name
    296,  # "First Year Charts" – collection name
    302,  # Affirmation (Percy Grainger) – wrong composer dup, keep 326
    306,  # Black Forest Overture (James Curnow) – wrong composer dup, keep 238
    310,  # Aztec Fire – dup, keep 234
    313,  # Be Thou My Vision – dup, keep 241
    314,  # "FJH BEGINNING BAND" – collection name
    315,  # "Very Beginning Band" – collection name
    316,  # "FJH Developing Band" – collection name
    318,  # "Concert Band - Grade 2" – series label
    321,  # "Alfred's Young Symphonic Band Series" – collection name
    322,  # Colliding Visions (Brian Baldridge) – wrong composer dup, keep 265
    323,  # Comet Ride (Michael Story) – wrong composer dup, keep 266
    324,  # "Overture" (Tchaikovsky) – dup of 303 (1812 Overture)
]
c.executemany("DELETE FROM sheet_music WHERE id=?", [(i,) for i in delete_ids])
print(f"Deleted {c.rowcount} collection/duplicate/garbage entries (last batch)")

# ── TITLE/COMPOSER FIXES ─────────────────────────────────────────────────────
updates = [
    # (id, title, composer)  – None = keep existing value
    (12,  "Tyrannosaurus Charlie",              None),
    (14,  "Let's Talk About the Moon",          None),
    (38,  "25 or 6 to 4",                       None),
    (39,  None,                                 "Sammy Nestico"),
    (42,  None,                                 "Sammy Nestico"),
    (44,  "#88 Basie Street",                   "Sammy Nestico"),
    (46,  None,                                 "Sammy Nestico"),
    (49,  None,                                 "Sammy Nestico"),
    (53,  "Gimme Some Lovin'",                  "Steve Winwood, Spencer Davis"),
    (55,  None,                                 "Benny Golson"),
    (81,  None,                                 "Antonio Carlos Jobim"),
    (84,  None,                                 "Miles Davis"),
    (99,  None,                                 "Jimmy McHugh, Dorothy Fields"),
    (129, "Malaguena",                          None),
    (135, "Mini Minor",                         "David Baker"),
    (156, None,                                 "Neal Hefti"),
    (171, None,                                 "Dexter Gordon"),
    (172, None,                                 "Leon Parish, Andy Razaf"),
    (173, None,                                 "Pee Wee Ellis"),
    (191, None,                                 "Michael Bublé"),
    (223, "Alien Invasion",                     None),
    (279, "Basie-Cally the Blues",              None),
    (297, None,                                 "Rob Vuono, Jr."),
    (303, "1812 Overture",                      None),
    (307, "Rendezvous",                         None),
    (319, "Caravelle",                          None),
]
for row_id, title, composer in updates:
    if title and composer:
        c.execute("UPDATE sheet_music SET title=?, composer=? WHERE id=?", (title, composer, row_id))
    elif title:
        c.execute("UPDATE sheet_music SET title=? WHERE id=?", (title, row_id))
    elif composer:
        c.execute("UPDATE sheet_music SET composer=? WHERE id=?", (composer, row_id))
print(f"Applied {len(updates)} title/composer fixes")

# ── SOURCE FILE UPDATES ───────────────────────────────────────────────────────
# (id, image_filename)
source_map = {
    # Jazz – individual open scores (highest confidence)
    28:  "IMG_2573.JPG",  # Freddie Freeloader – open score
    74:  "IMG_2601.JPG",  # Hip Hip Hop – open score
    120: "IMG_2578.JPG",  # Leap Frog – open score
    127: "IMG_2580.JPG",  # Libertango – open score
    128: "IMG_2581.JPG",  # Manteca – open score
    139: "IMG_2584.JPG",  # My Romance – open score
    168: "IMG_2566.JPG",  # Blue and Sentimental – open score
    179: "IMG_2568.JPG",  # Brain Sprain (Andy Clark) – open score
    180: "IMG_2569.JPG",  # CUTE – open score
    201: "IMG_2572.JPG",  # Goodbye My Heart – open score
    209: "IMG_2575.JPG",  # If I Could Fly – open score
    215: "IMG_2577.JPG",  # It's Only a Paper Moon – open score
    3:   "IMG_2591.JPG",  # What A Wonderful World – open score
    4:   "IMG_2592.JPG",  # Swingin' Shepherd Blues – open score
    56:  "IMG_2582.JPG",  # Malaguena – open score
    167: "IMG_2590.JPG",  # White Christmas – open score
    208: "IMG_2574.JPG",  # If I Could – cover shown
    278: "IMG_2563.JPG",  # April in Paris – open score (Alto Sax 1)
    281: "IMG_2562.JPG",  # Ain't Misbehavin' – open conductor score
    # Jazz – Best of Easy Jazz TOC (IMG_2597)
    24:  "IMG_2597.JPG",  # All Blues
    25:  "IMG_2597.JPG",  # All of Me
    26:  "IMG_2597.JPG",  # Beyond the Sea
    27:  "IMG_2597.JPG",  # Boogie Woogie Bugle Boy
    29:  "IMG_2597.JPG",  # Green Onions
    30:  "IMG_2597.JPG",  # Hey Jude
    31:  "IMG_2597.JPG",  # In a Sentimental Mood
    32:  "IMG_2597.JPG",  # Kansas City
    33:  "IMG_2597.JPG",  # Respect
    35:  "IMG_2597.JPG",  # Sesame Street Theme
    36:  "IMG_2597.JPG",  # Sidewinder
    37:  "IMG_2597.JPG",  # Tuxedo Junction
    38:  "IMG_2597.JPG",  # 25 or 6 to 4
    # Jazz – Best of Sammy Nestico TOC (IMG_2598)
    39:  "IMG_2598.JPG",  # First Wish
    40:  "IMG_2598.JPG",  # Do Nothin' Till You Hear From Me
    41:  "IMG_2598.JPG",  # Good News
    42:  "IMG_2598.JPG",  # Martinique
    43:  "IMG_2598.JPG",  # Satin Doll
    44:  "IMG_2598.JPG",  # #88 Basie Street
    45:  "IMG_2598.JPG",  # Just In Time
    46:  "IMG_2598.JPG",  # Odyssey
    47:  "IMG_2598.JPG",  # On The Sunny Side Of The Street
    48:  "IMG_2598.JPG",  # St. Louis Blues
    49:  "IMG_2598.JPG",  # Sugar Valley
    # Jazz – Discovery Jazz Favorites TOC (IMG_2599)
    50:  "IMG_2599.JPG",  # Beauty and the Beast
    53:  "IMG_2599.JPG",  # Gimme Some Lovin'
    54:  "IMG_2599.JPG",  # Hound Dog
    55:  "IMG_2599.JPG",  # Killer Joe
    57:  "IMG_2599.JPG",  # Kiss the Girl
    58:  "IMG_2599.JPG",  # Swingin' Wheel
    59:  "IMG_2599.JPG",  # Tin Roof Blues
    60:  "IMG_2599.JPG",  # Twist And Shout
    61:  "IMG_2599.JPG",  # Frosty the Snow Man
    # Jazz – Young Jazz Ensemble Collection TOC (IMG_2600)
    62:  "IMG_2600.JPG",  # Blues in the Night
    63:  "IMG_2600.JPG",  # Burritos to Go
    64:  "IMG_2600.JPG",  # Have Yourself a Merry Little Christmas
    65:  "IMG_2600.JPG",  # Jumpin' at the Woodside
    66:  "IMG_2600.JPG",  # Jungle Boogie
    67:  "IMG_2600.JPG",  # Misty
    68:  "IMG_2600.JPG",  # Night and Day
    69:  "IMG_2600.JPG",  # On Green Dolphin Street
    70:  "IMG_2600.JPG",  # Sax to the Max
    71:  "IMG_2600.JPG",  # Summertime
    72:  "IMG_2600.JPG",  # Take Five
    73:  "IMG_2600.JPG",  # Tastes Like Chicken
    # Jazz – Easy Jazz Favorites TOC (IMG_2602)
    76:  "IMG_2602.JPG",  # All The Things You Are
    77:  "IMG_2602.JPG",  # Blue Train (Blue Trane)
    78:  "IMG_2602.JPG",  # Caravan
    79:  "IMG_2602.JPG",  # Chameleon
    80:  "IMG_2602.JPG",  # Fly Me To The Moon
    81:  "IMG_2602.JPG",  # The Girl From Ipanema
    82:  "IMG_2602.JPG",  # In The Mood
    83:  "IMG_2602.JPG",  # Inside Out
    84:  "IMG_2602.JPG",  # Milestones
    85:  "IMG_2602.JPG",  # A Nightingale Sang In Berkeley Square
    86:  "IMG_2602.JPG",  # One Note Samba
    87:  "IMG_2602.JPG",  # Route 66
    89:  "IMG_2602.JPG",  # When I Fall In Love
    # Jazz – First Year Charts Collection TOC (IMG_2604)
    107: "IMG_2604.JPG",  # Chattanooga Choo Choo
    108: "IMG_2604.JPG",  # El Gato Gordo
    109: "IMG_2604.JPG",  # James Bond Theme
    110: "IMG_2604.JPG",  # A Jazzy Merry Christmas
    111: "IMG_2604.JPG",  # The Judge
    112: "IMG_2604.JPG",  # Lil' Darlin'
    113: "IMG_2604.JPG",  # LOOSEN UP...
    114: "IMG_2604.JPG",  # One O'Clock Jump
    115: "IMG_2604.JPG",  # Over the Rainbow
    116: "IMG_2604.JPG",  # Peter Gunn Theme
    117: "IMG_2604.JPG",  # The Pink Panther
    118: "IMG_2604.JPG",  # Rock This Town
    # Jazz – IMG_2565 covers
    283: "IMG_2565.JPG",  # The Bare Necessities
    286: "IMG_2565.JPG",  # Birdland
    287: "IMG_2565.JPG",  # (The) Birth of the Blues
    289: "IMG_2565.JPG",  # Black Coffee
    291: "IMG_2565.JPG",  # Blue Train
    292: "IMG_2565.JPG",  # Blues in Hoss Flat
    293: "IMG_2565.JPG",  # Blue Bossa
    294: "IMG_2565.JPG",  # Blue Monk
    295: "IMG_2565.JPG",  # Blues March
    297: "IMG_2565.JPG",  # BOP!
    # Jazz – IMG_2567 covers
    169: "IMG_2567.JPG",  # Brain Sprain (Balmages)
    171: "IMG_2567.JPG",  # Cheesecake
    172: "IMG_2567.JPG",  # Christopher Columbus
    173: "IMG_2567.JPG",  # The Chicken
    174: "IMG_2567.JPG",  # Cubano Chant
    175: "IMG_2567.JPG",  # Cuphead
    176: "IMG_2567.JPG",  # Count Me In
    177: "IMG_2567.JPG",  # Count On Me
    178: "IMG_2567.JPG",  # Danger Zone
    # Jazz – IMG_2570 covers
    181: "IMG_2570.JPG",  # Don't Get Around Much Anymore
    182: "IMG_2570.JPG",  # De Madrugada
    183: "IMG_2570.JPG",  # Doxy
    184: "IMG_2570.JPG",  # Drama for Your Mama
    185: "IMG_2570.JPG",  # Dreamsville
    187: "IMG_2570.JPG",  # Five! Getcha
    189: "IMG_2570.JPG",  # C Jam Blues
    190: "IMG_2570.JPG",  # Embraceable You
    191: "IMG_2570.JPG",  # Everything
    192: "IMG_2570.JPG",  # El Ritmo de Vida
    # Jazz – IMG_2571 covers
    193: "IMG_2571.JPG",  # Feeling Good
    194: "IMG_2571.JPG",  # Funky Cha-Cha
    195: "IMG_2571.JPG",  # Georgia On My Mind
    196: "IMG_2571.JPG",  # Gospel John
    197: "IMG_2571.JPG",  # Groovin' Hard
    198: "IMG_2571.JPG",  # Good Times In Santiago
    199: "IMG_2571.JPG",  # Harlem Nocturne
    200: "IMG_2571.JPG",  # Front Burner
    # Jazz – IMG_2574/2576 covers
    203: "IMG_2574.JPG",  # Here's That Rainy Day
    204: "IMG_2574.JPG",  # How Deep Is the Ocean
    205: "IMG_2574.JPG",  # I Can't Get Started With You
    206: "IMG_2574.JPG",  # I Can't Give You Anything But Love
    212: "IMG_2576.JPG",  # Back Home Again in Indiana
    213: "IMG_2576.JPG",  # Jersey Bounce
    # Jazz – IMG_2579 covers
    121: "IMG_2579.JPG",  # A Little Bit of Sugar for the Band
    122: "IMG_2579.JPG",  # Linus and Lucy
    123: "IMG_2579.JPG",  # Love Is Here to Stay
    124: "IMG_2579.JPG",  # A Little Chicken Soup
    129: "IMG_2579.JPG",  # Malaguena (second copy)
    # Jazz – IMG_2583 covers
    131: "IMG_2583.JPG",  # Midnight Bells
    134: "IMG_2583.JPG",  # Mood Indigo
    135: "IMG_2583.JPG",  # Mini Minor
    137: "IMG_2583.JPG",  # Must Be the Blues
    138: "IMG_2583.JPG",  # A Night In Tunisia
    # Jazz – IMG_2585 covers
    140: "IMG_2585.JPG",  # Night Train
    141: "IMG_2585.JPG",  # Now's the Time
    142: "IMG_2585.JPG",  # Opus One
    143: "IMG_2585.JPG",  # Peace
    144: "IMG_2585.JPG",  # Pete Left Town
    145: "IMG_2585.JPG",  # Puttin' On The Ritz
    146: "IMG_2585.JPG",  # 'Round Midnight
    # Jazz – IMG_2587 covers
    149: "IMG_2587.JPG",  # Sack of Woe
    150: "IMG_2587.JPG",  # Samantha
    151: "IMG_2587.JPG",  # Smoke Gets in Your Eyes
    152: "IMG_2587.JPG",  # Snuffles
    153: "IMG_2587.JPG",  # Someone to Watch Over Me
    154: "IMG_2587.JPG",  # Soul Bossa Nova
    34:  "IMG_2587.JPG",  # Saxes with Attitude
    # Jazz – IMG_2588 covers
    156: "IMG_2588.JPG",  # Sweets
    157: "IMG_2588.JPG",  # Take The 'A' Train
    158: "IMG_2588.JPG",  # Swing Machine
    159: "IMG_2588.JPG",  # Swing Street
    160: "IMG_2588.JPG",  # Watermelon Man
    161: "IMG_2588.JPG",  # What, So?
    162: "IMG_2588.JPG",  # What's Cookin'?
    164: "IMG_2588.JPG",  # Work Song
    # Jazz – IMG_2589 covers
    165: "IMG_2589.JPG",  # Yardbird Suite
    166: "IMG_2589.JPG",  # You've Got a Friend in Me
    # Jazz – IMG_2561 covers
    272: "IMG_2561.JPG",  # Afro Blue
    274: "IMG_2561.JPG",  # Alligator Alley
    275: "IMG_2561.JPG",  # Azure
    276: "IMG_2561.JPG",  # As Time Goes By
    277: "IMG_2561.JPG",  # Avenue 'R'
    279: "IMG_2561.JPG",  # Basie-Cally the Blues
    280: "IMG_2561.JPG",  # Basic Basie
    # Jazz – First Jazz Performance
    5:   "IMG_2593.JPG",  # Blues Machine
    6:   "IMG_2593.JPG",  # Orangatango
    7:   "IMG_2593.JPG",  # Discover the Blues
    8:   "IMG_2593.JPG",  # Step Right Up
    12:  "IMG_2595.JPG",  # Tyrannosaurus Charlie
    13:  "IMG_2595.JPG",  # POWER TRIP
    14:  "IMG_2595.JPG",  # Let's Talk About the Moon
    15:  "IMG_2595.JPG",  # Brazilian Sunset
    18:  "IMG_2596.JPG",  # Shadows Come Home
    19:  "IMG_2596.JPG",  # A Blues to Grow On
    22:  "IMG_2596.JPG",  # Ketchup Is Not a Spice
    # Concert band – open scores
    303: "IMG_2550.JPG",  # 1812 Overture
    304: "IMG_2551.JPG",  # Ashland Park
    # Concert band – IMG_2552 flat covers
    222: "IMG_2547.JPG",  # Algyrythms (shelf)
    300: "IMG_2552.JPG",  # Algorithm (Bernotas)
    326: "IMG_2552.JPG",  # Affirmation (William Owens)
    327: "IMG_2552.JPG",  # African Folk Trilogy
    328: "IMG_2552.JPG",  # Ahtanum Ridge
    329: "IMG_2552.JPG",  # Air and Jig
    # Concert band – IMG_2554 flat covers
    218: "IMG_2554.JPG",  # All Ye Young Sailors
    219: "IMG_2554.JPG",  # Alder Creek Tribute
    223: "IMG_2554.JPG",  # Alien Invasion
    # Concert band – IMG_2555 flat covers (smaller, harder to read)
    225: "IMG_2555.JPG",  # Angel Band
    226: "IMG_2555.JPG",  # Androgynist
    227: "IMG_2555.JPG",  # Ancient Spirits
    228: "IMG_2555.JPG",  # Alabanza Dream
    229: "IMG_2555.JPG",  # Birdwatching: Elements
    # Concert band – IMG_2556 flat covers
    230: "IMG_2556.JPG",  # Australian Choral Fantasy
    231: "IMG_2556.JPG",  # Ashokan Farewell
    232: "IMG_2556.JPG",  # Armed Forces on Parade
    233: "IMG_2556.JPG",  # Austin Park
    236: "IMG_2556.JPG",  # Blue Ridge Overture
    309: "IMG_2556.JPG",  # Australian Cheer
    301: "IMG_2556.JPG",  # Anathem Ridge
    # Concert band – IMG_2548 shelf
    234: "IMG_2548.JPG",  # Aztec Fire
    235: "IMG_2548.JPG",  # At the Crossroads
    238: "IMG_2548.JPG",  # Black Forest Overture
    241: "IMG_2548.JPG",  # Be Thou My Vision
    242: "IMG_2548.JPG",  # The Battle Pavane
    244: "IMG_2548.JPG",  # Norman
    305: "IMG_2548.JPG",  # Benediction Choral
    307: "IMG_2548.JPG",  # Rendezvous
    308: "IMG_2548.JPG",  # Bushido
    325: "IMG_2548.JPG",  # Abington Ridge
    # Concert band – IMG_2557 flat covers
    237: "IMG_2557.JPG",  # Bazaar
    239: "IMG_2557.JPG",  # The Bonsai Tree
    240: "IMG_2557.JPG",  # Praise Adoration
    243: "IMG_2557.JPG",  # El Canto
    # Concert band – IMG_2558/2559 flat covers
    246: "IMG_2558.JPG",  # Cango Caves
    249: "IMG_2558.JPG",  # Canto
    252: "IMG_2559.JPG",  # Cedar Valley March
    253: "IMG_2559.JPG",  # Cayuga Lake Overture
    254: "IMG_2559.JPG",  # Chant and Canon
    255: "IMG_2559.JPG",  # Chariots
    256: "IMG_2559.JPG",  # Chester Variations
    257: "IMG_2559.JPG",  # Chorale and Canon
    258: "IMG_2559.JPG",  # Chorale
    259: "IMG_2559.JPG",  # Chorale and Fugue
    260: "IMG_2559.JPG",  # Chorale and Mystic Chant
    261: "IMG_2559.JPG",  # Clarinet Capers
    262: "IMG_2559.JPG",  # Flam, Snap, Twinkle and Boom
    # Concert band – IMG_2549 shelf
    245: "IMG_2549.JPG",  # Cavendish Overture
    248: "IMG_2549.JPG",  # Funfair
    250: "IMG_2549.JPG",  # Caprice (Victor Ewald)
    251: "IMG_2549.JPG",  # Camel Caravan
    317: "IMG_2549.JPG",  # Caprice (W. Francis McBeth)
    319: "IMG_2549.JPG",  # Caravelle
    320: "IMG_2549.JPG",  # Castle Gate
    # Concert band – IMG_2560 flat covers
    263: "IMG_2560.JPG",  # City of Glass
    264: "IMG_2560.JPG",  # Clarinet Jive
    265: "IMG_2560.JPG",  # Colliding Visions
    266: "IMG_2560.JPG",  # Comet Ride
    267: "IMG_2560.JPG",  # The Curse of Tutankhamun
    268: "IMG_2560.JPG",  # Colonel Bogey March
    269: "IMG_2560.JPG",  # Contempo
    270: "IMG_2560.JPG",  # Appalachian Whisper
    271: "IMG_2560.JPG",  # Crazy for Cartoons
    # Concert band – IMG_2547 shelf (remaining)
    224: "IMG_2547.JPG",  # Arietta and Rondo
    298: "IMG_2547.JPG",  # A Fabia Dream
    299: "IMG_2547.JPG",  # Amazing Grace
}

for row_id, img in source_map.items():
    full_path = f"{PICS}/{img}"
    c.execute("UPDATE sheet_music SET source_file=? WHERE id=?", (full_path, row_id))
print(f"Updated source_file for {len(source_map)} records")

# ── INSERT MISSING PIECES ─────────────────────────────────────────────────────
# Columns: title, composer, genre, ensemble_type, difficulty, publisher, source_file
missing = [
    # (title, composer, genre, ensemble_type, source_file)
    ("Celtic Ritual",           "",                                 "Concert Band", "Concert Band", f"{PICS}/IMG_2559.JPG"),
    ("Footprints",              "Wayne Shorter",                    "Jazz",         "Jazz Ensemble", f"{PICS}/IMG_2571.JPG"),
    ("Greensleeves",            "Traditional",                      "Jazz",         "Jazz Ensemble", f"{PICS}/IMG_2571.JPG"),
    ("The Q.C. Shuffle",        "Chris Sharp",                      "Jazz",         "Jazz Ensemble", f"{PICS}/IMG_2585.JPG"),
    ("Sea Breeze",              "",                                 "Jazz",         "Jazz Ensemble", f"{PICS}/IMG_2587.JPG"),
    ("Stella By Starlight",     "Victor Young",                     "Jazz",         "Jazz Ensemble", f"{PICS}/IMG_2587.JPG"),
    ("Stompin' At the Savoy",   "Benny Goodman, Chick Webb, Edgar Sampson, Andy Razaf", "Jazz", "Jazz Ensemble", f"{PICS}/IMG_2587.JPG"),
    ("Stolen Moments",          "Oliver Nelson",                    "Jazz",         "Jazz Ensemble", f"{PICS}/IMG_2587.JPG"),
    ("A Little Basie, Please",  "Sammy Nestico",                    "Jazz",         "Jazz Ensemble", f"{PICS}/IMG_2598.JPG"),
    ("Moon's Breath Cafe",      "",                                 "Jazz",         "Jazz Ensemble", f"{PICS}/IMG_2595.JPG"),
    ("Sherlock's Gone Home",    "",                                 "Jazz",         "Jazz Ensemble", f"{PICS}/IMG_2596.JPG"),
    ("Danza Nueva",             "",                                 "Jazz",         "Jazz Ensemble", f"{PICS}/IMG_2596.JPG"),
]
for title, composer, genre, ensemble, src in missing:
    c.execute("""INSERT INTO sheet_music (title, composer, genre, ensemble_type, source_file)
                 VALUES (?,?,?,?,?)""",
              (title, composer, genre, ensemble, src))
print(f"Inserted {len(missing)} missing pieces")

conn.commit()

# ── SUMMARY ───────────────────────────────────────────────────────────────────
total = c.execute("SELECT COUNT(*) FROM sheet_music").fetchone()[0]
no_src = c.execute("SELECT COUNT(*) FROM sheet_music WHERE source_file IS NULL OR source_file=''").fetchone()[0]
print(f"\nDatabase now has {total} pieces.")
print(f"Records without source_file: {no_src}")
if no_src > 0:
    rows = c.execute("SELECT id, title FROM sheet_music WHERE source_file IS NULL OR source_file='' ORDER BY id").fetchall()
    for r in rows:
        print(f"  ID {r[0]:4d}: {r[1]}")

conn.close()
print("\nDone.")
