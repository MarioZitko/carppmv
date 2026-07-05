import re
from datetime import date
from pathlib import Path


def _valid(y: int, m: int, d: int) -> "date | None":
    if not (2013 <= y <= 2030 and 1 <= m <= 12 and 1 <= d <= 31):
        return None
    try:
        return date(y, m, d)
    except ValueError:
        return None


def parse_valid_from(filename: str, folder_year: "int | None" = None) -> "date | None":
    """Parse the validity-start date from a catalogue filename.

    `folder_year`, when given, is the year of the file's parent `/YYYY/`
    folder. It's used only as a last resort: many importers name files with
    just a day+month ("Opel_01.07.", "Nissan_15.10.", "Land Rover 01.07.")
    and rely on the folder to carry the year. Without it those files parse to
    None and get dropped before mapping — 44 files across Chevrolet, Opel,
    Nissan, Mazda and Land Rover in the current manifest. Every one of them
    sits under a /YYYY/ folder, so this fallback recovers them all.

    The new patterns (6-8 below) are appended AFTER the existing ones, so any
    filename that already parses keeps hitting an earlier pattern and returns
    unchanged — the fallbacks only ever fire on names that previously failed."""
    stem = Path(filename).stem

    # Pattern 1: D.M.YYYY (1- or 2-digit day/month, e.g. "24.3.2025")
    m = re.search(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", stem)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        result = _valid(y, mo, d)
        if result:
            return result

    # Pattern 1b: YYYY [words] DD.MM. — a 4-digit year followed anywhere later
    # by a DD.MM. day (possibly with words like "gospodarska"/"Sprinter" in
    # between, e.g. "MB 2017 gospodarska 13.04." or "MB 2018 15.2.").
    m = re.search(r"(\d{4})\D+?(\d{1,2})\.(\d{1,2})(?!\d)", stem)
    if m:
        y, d, mo = int(m.group(1)), int(m.group(2)), int(m.group(3))
        result = _valid(y, mo, d)
        if result:
            return result

    # Pattern 2: YYYYMMDD (8-digit run, not preceded or followed by a digit)
    m = re.search(r"(?<!\d)(\d{4})(\d{2})(\d{2})(?!\d)", stem)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        result = _valid(y, mo, d)
        if result:
            return result

    # Pattern 3: YYYY DDMM — try MMDD first, fall back to DDMM
    m = re.search(r"(\d{4})\s(\d{2})(\d{2})(?!\d)", stem)
    if m:
        y, a, b = int(m.group(1)), int(m.group(2)), int(m.group(3))
        result = _valid(y, a, b) or _valid(y, b, a)  # MMDD then DDMM
        if result:
            return result

    # Pattern 4: YYYY_MMDD (underscore separator)
    m = re.search(r"(?<!\d)(\d{4})_(\d{2})(\d{2})(?!\d)", stem)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        result = _valid(y, mo, d)
        if result:
            return result

    # Pattern 5: YYYY MM (year + 2-digit month only → day=01)
    m = re.search(r"(\d{4})\s(\d{2})(?!\d)", stem)
    if m:
        y, mo = int(m.group(1)), int(m.group(2))
        result = _valid(y, mo, 1)
        if result:
            return result

    # --- Fallbacks below only fire on names the patterns above couldn't parse.

    # Pattern 5b: YYYY-MM-DD — ISO-style with dashes (Suzuki_2014-03-10).
    m = re.search(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)", stem)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        result = _valid(y, mo, d)
        if result:
            return result

    # Pattern 6: DD.MM.YY / DD_MM_YY — day-first with a 2-digit year, e.g.
    # Mazda's "...(01_07_13)...". Croatian convention is day-first, so the
    # 2-digit year is the trailing group. Interpreted as 20YY.
    m = re.search(r"(?<!\d)(\d{1,2})[._](\d{1,2})[._](\d{2})(?!\d)", stem)
    if m:
        d, mo, yy = int(m.group(1)), int(m.group(2)), int(m.group(3))
        result = _valid(2000 + yy, mo, d)
        if result:
            return result

    # Pattern 7: DDMMYYYY — an 8-digit day-first run (Chevrolet's "01072013").
    # Distinct from Pattern 2's YYYYMMDD, which is tried first; this only runs
    # when reading the same 8 digits year-first gave an invalid date.
    m = re.search(r"(?<!\d)(\d{2})(\d{2})(\d{4})(?!\d)", stem)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        result = _valid(y, mo, d)
        if result:
            return result

    # Pattern 8: DD.MM. with no year in the name — take the year from the
    # parent /YYYY/ folder (Opel_01.07., Nissan_15.10., Land Rover 01.07.).
    if folder_year is not None:
        m = re.search(r"(?<!\d)(\d{1,2})\.(\d{1,2})\.", stem)
        if m:
            d, mo = int(m.group(1)), int(m.group(2))
            result = _valid(folder_year, mo, d)
            if result:
                return result

    return None
