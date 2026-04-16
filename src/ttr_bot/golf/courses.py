"""Maps on-screen / OCR course names to Custom Golf Actions JSON stem names."""

# Keys: substrings expected in scoreboard or HUD text.
# Values: filename stem under golf_actions/ (without .json).
COURSE_NAME_TO_FILE: dict[str, str] = {
    # EASY — Walk in the Par
    "Afternoon Tee": "EASY - Afternoon Tee",
    "Down the Hatch": "EASY - Down the Hatch",
    "Hole In Fun": "EASY - Hole In Fun",
    "Hole on the Range": "EASY - Hole on the Range",
    "Holey Mackeral": "EASY - Holey Mackeral",
    "Holey Mackerel": "EASY - Holey Mackeral",
    "Hot Links": "EASY - Hot Links",
    "One Little Birdie": "EASY - One Little Birdie",
    "Peanut Putter": "EASY - Peanut Putter",
    "Seeing Green": "EASY - Seeing green",
    "Swing Time": "EASY - Swing Time",
    "Swing-A-Long": "EASY - Swing-A-Long",
    "Swing A Long": "EASY - Swing-A-Long",
    # MEDIUM — Hole-some Fun
    "At the Drive In": "MEDIUM - At the Drive In",
    "Bogey Nights-2": "MEDIUM - Bogey Nights-2",
    "Down the Hatch-2": "MEDIUM - Down the Hatch-2",
    "Hole in Fun-2": "MEDIUM - Hole in Fun-2",
    "Holey Mackerel-2": "MEDIUM - Holey Mackerel-2",
    "Holey Mackeral-2": "MEDIUM - Holey Mackerel-2",
    "Hot Links-2": "MEDIUM - Hot Links-2",
    "No Putts About It": "MEDIUM - No Putts About It",
    "Rock and Roll In": "MEDIUM - Rock and Roll In",
    "Rock and Roll In-2": "MEDIUM - Rock and Roll In-2",
    "Second Wind": "MEDIUM - Second Wind",
    "Swing Time-2": "MEDIUM - Swing Time-2",
    "Tea Off Time": "MEDIUM - Tea Off Time",
    # HARD — The Hole Kit and Caboodle
    "Afternoon Tee-2": "HARD - Afternoon Tee-2",
    "At the Drive In-2": "HARD - At the Drive In-2",
    "Hole on the Range-2": "HARD - Hole on the Range-2",
    "No Putts About It-2": "HARD - No Putts About It-2",
    "One Little Birdie-2": "HARD - One Little Birdie-2",
    "Peanut Putter-2": "HARD - Peanut Putter-2",
    "Second Wind-2": "HARD - Second Wind-2",
    "Seeing Green-2": "HARD - Seeing Green-2",
    "Swing-A-Long-2": "HARD - Swing-A-Long-2",
    "Swing A Long-2": "HARD - Swing-A-Long-2",
    "Tea Off Time-2": "HARD - Tea Off Time-2",
    "Whole in Won": "HARD - Whole in Won",
    "Whole in Won-2": "HARD - Whole in Won-2",
}


def match_course_name(text: str) -> str | None:
    """Return action-file stem if *text* contains a known course name."""
    if not text or not text.strip():
        return None

    cleaned = " ".join(text.replace("\n", " ").replace("\r", " ").split())

    for key, stem in COURSE_NAME_TO_FILE.items():
        if key.lower() in cleaned.lower():
            return stem

    # Fuzzy: majority of words from key appear in text
    lower = cleaned.lower()
    for key, stem in COURSE_NAME_TO_FILE.items():
        words = [w for w in key.replace("-", " ").split() if len(w) > 1]
        if not words:
            continue
        hits = sum(1 for w in words if w.lower() in lower)
        if hits > len(words) // 2:
            return stem

    return None
