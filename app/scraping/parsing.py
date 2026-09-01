"""Shared parsing helpers for raw ListingData fields.

Extracted from app/calculate/router.py so app/scraping/persistence.py (which
also needs to turn a ListingData.first_registration_date string into a real
date, to persist a Listing row) doesn't duplicate the same format-guessing
logic. parse_number() lives here for the same reason — every extractor that
reads a number out of display text needs it, and the copies had drifted apart.
"""

import re
from datetime import date, datetime


def parse_listing_date(raw: str | None) -> date | None:
    """Parses whatever date format a scraper handed back. Listing sites are
    inconsistent about this — ISO datetimes with a time suffix, single-digit
    day/month, a trailing "." (Croatian convention), slash-separated dates,
    "MM/YYYY", or a bare year are all seen in practice, so this deliberately
    tries several shapes rather than requiring one exact format."""
    if not raw:
        return None

    text = raw.strip()

    # ISO date, optionally with a time component ("2021-05-17T00:00:00.000Z").
    iso_prefix = text[:10]
    try:
        return datetime.strptime(iso_prefix, "%Y-%m-%d").date()
    except ValueError:
        pass

    # Normalize whitespace around separators ("17. 05. 2021." -> "17.05.2021.")
    normalized = re.sub(r"\s*([./])\s*", r"\1", text)

    for fmt in ("%d.%m.%Y.", "%d.%m.%Y", "%d/%m/%Y", "%m.%Y", "%m/%Y", "%Y-%m", "%Y"):
        try:
            return datetime.strptime(normalized, fmt).date()
        except ValueError:
            continue
    return None


def parse_number(text: str | None) -> float | None:
    """Parses a number out of display text without assuming a locale.

    Listing sites disagree on separators — "12.500,00" (German/Croatian) and
    "12,500.00" (English) are both seen, and autobid.de serves German
    formatting even on its /en/ pages while mobile.de's values arrive
    pre-formatted by whatever locale the source page was rendered in. Guessing
    one convention is how you turn "1,234.56" into 1.23456, so the separator
    role is decided by position instead:

      * both present  -> the rightmost one is the decimal separator
      * comma only    -> thousands iff exactly 3 digits follow, else decimal
      * dot only      -> thousands iff exactly 3 digits follow, else decimal

    The residual ambiguity is a bare "1,500"/"1.500", read as 1500. That is the
    right call for prices and mileages, which is all this parses.
    """
    if text is None:
        return None
    text = text.strip()
    if not text:
        return None

    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            # comma is decimal — "12.500,00"
            text = text.replace(".", "").replace(",", ".")
        else:
            # dot is decimal — "12,500.00"
            text = text.replace(",", "")
    elif "," in text:
        parts = text.split(",")
        if len(parts) == 2 and len(parts[1]) == 3:
            text = text.replace(",", "")  # thousands separator
        else:
            text = text.replace(",", ".")  # decimal separator
    elif "." in text:
        parts = text.split(".")
        if len(parts) == 2 and len(parts[1]) == 3:
            text = text.replace(".", "")  # thousands separator

    try:
        return float(text)
    except ValueError:
        return None
