"""Shared parsing helpers for raw ListingData fields.

Extracted from app/calculate/router.py so app/scraping/persistence.py (which
also needs to turn a ListingData.first_registration_date string into a real
date, to persist a Listing row) doesn't duplicate the same format-guessing
logic.
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
