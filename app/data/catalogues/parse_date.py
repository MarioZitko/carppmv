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


def parse_valid_from(filename: str) -> "date | None":
    stem = Path(filename).stem

    # Pattern 1: DD.MM.YYYY
    m = re.search(r"(\d{2})\.(\d{2})\.(\d{4})", stem)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        result = _valid(y, mo, d)
        if result:
            return result

    # Pattern 1b: YYYY DD.MM. (year + space + DD.MM without 4-digit year)
    m = re.search(r"(\d{4})\s(\d{2})\.(\d{2})", stem)
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

    return None
