"""autobid.de extractor — plain httpx + BeautifulSoup (no browser needed, confirmed v7 §2.6).

Why BeautifulSoup over lxml directly: autobid.de renders HTML server-side so there is no
JS to execute — a plain HTTP fetch is enough. BeautifulSoup's .find()/.select() API maps
naturally onto the label→value extraction pattern (iterate <dt>/<dd> or <th>/<td> pairs,
look up the label, read the adjacent value). lxml's native API requires XPath, which is
more verbose and harder to maintain when label strings change. Both use lxml as the
underlying C parser when we pass parser="lxml", so parse throughput is identical.
CO2 is not exposed pre-login on autobid.de — always returned as None.
"""

import re
from decimal import Decimal, InvalidOperation

import httpx
from bs4 import BeautifulSoup

from app.core.exceptions import ScrapingError
from app.scraping.schemas import ListingData

# Maps the German spec-table labels used on autobid.de to canonical names.
_LABEL_MAP: dict[str, str] = {
    "erstzulassung": "first_registration",
    "first registration": "first_registration",
    "kraftstoff": "fuel_type",
    "fuel": "fuel_type",
    "kraftstoffart": "fuel_type",
    "kilometerstand": "mileage_km",
    "laufleistung": "mileage_km",
    "mileage": "mileage_km",
    "leistung": "power_kw",
    "power": "power_kw",
    "sitze": "seat_count",
    "seats": "seat_count",
    "anzahl der sitze": "seat_count",
    "version": "variant",
    "variante": "variant",
    "ausstattung": "variant",
    "trim": "variant",
}

_FUEL_MAP: dict[str, str] = {
    "diesel": "diesel",
    "benzin": "petrol",
    "petrol": "petrol",
    "benzin/gas": "petrol",
    "hybrid": "hybrid",
    "elektro": "electric",
    "electric": "electric",
    "erdgas": "cng",
}


def _parse_german_float(text: str) -> float | None:
    """Parse German-formatted numbers: '1.500,00' → 1500.0, '1500' → 1500.0."""
    cleaned = text.strip().replace("\xa0", "").replace(" ", "")
    # Remove currency symbols and unit noise
    cleaned = re.sub(r"[€$£]", "", cleaned)
    cleaned = cleaned.strip()
    # German format: dot = thousands separator, comma = decimal
    if "," in cleaned:
        cleaned = cleaned.replace(".", "").replace(",", ".")
    else:
        cleaned = cleaned.replace(".", "")
    try:
        return float(Decimal(cleaned))
    except (InvalidOperation, ValueError):
        return None


def _extract_price(soup: BeautifulSoup) -> float | None:
    # Starting bid / Mindestgebot — try multiple candidate selectors
    for sel in [
        "[class*='start-price'] [class*='value']",
        "[class*='startprice']",
        "[class*='bid-price']",
        "[class*='current-bid']",
        "[class*='price'] [class*='amount']",
        "[class*='preis']",
        "[data-testid='start-price']",
        "[data-testid='current-price']",
    ]:
        el = soup.select_one(sel)
        if el:
            v = _parse_german_float(el.get_text())
            if v and v > 0:
                return v

    # Fallback: find any text that looks like a EUR price
    pattern = re.compile(r"(\d[\d.,]+)\s*€")
    for tag in soup.find_all(string=pattern):
        m = pattern.search(tag)
        if m:
            v = _parse_german_float(m.group(1))
            if v and v > 0:
                return v
    return None


def _extract_power_kw(text: str) -> float | None:
    """Parse '110 kW (150 PS)' or '110kW' → 110.0."""
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*kw", text, re.IGNORECASE)
    if m:
        v = _parse_german_float(m.group(1))
        return v
    return None


def _extract_mileage(text: str) -> int | None:
    """Parse '50.000 km' or '50000 km' → 50000."""
    m = re.search(r"(\d[\d.,]*)\s*km", text, re.IGNORECASE)
    if m:
        v = _parse_german_float(m.group(1))
        return int(v) if v is not None else None
    return None


def _extract_seat_count(text: str) -> int | None:
    m = re.search(r"(\d+)", text.strip())
    if m:
        v = int(m.group(1))
        return v if 1 <= v <= 20 else None
    return None


def _normalise_first_reg(text: str) -> str | None:
    """Return raw string but strip noise. Caller does full validation."""
    text = text.strip()
    if not text or text in ("-", "n/a", "N/A"):
        return None
    return text


def _parse_spec_table(soup: BeautifulSoup) -> dict[str, str]:
    """Collect all label→value pairs from any dt/dd or th/td table."""
    specs: dict[str, str] = {}

    # dt/dd pattern
    for dt in soup.find_all("dt"):
        label = dt.get_text(strip=True).lower().rstrip(":")
        dd = dt.find_next_sibling("dd")
        if dd:
            specs[label] = dd.get_text(strip=True)

    # th/td pattern
    for row in soup.find_all("tr"):
        cells = row.find_all(["th", "td"])
        if len(cells) >= 2:
            label = cells[0].get_text(strip=True).lower().rstrip(":")
            value = cells[1].get_text(strip=True)
            if label:
                specs[label] = value

    # li items with a colon-separated label pattern
    for li in soup.find_all("li"):
        text = li.get_text(strip=True)
        if ":" in text:
            parts = text.split(":", 1)
            label = parts[0].strip().lower()
            value = parts[1].strip()
            if label and value:
                specs.setdefault(label, value)

    return specs


class AutobidDeExtractor:
    async def extract(self, url: str) -> ListingData:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "de-DE,de;q=0.9",
        }
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            response = await client.get(url, headers=headers)
            if response.status_code != 200:
                raise ScrapingError(
                    f"autobid.de returned {response.status_code} for {url}"
                )

        soup = BeautifulSoup(response.text, "lxml")

        title = None
        h1 = soup.find("h1")
        if h1:
            title = h1.get_text(strip=True) or None

        price_eur = _extract_price(soup)
        specs = _parse_spec_table(soup)

        first_registration_date: str | None = None
        fuel_type: str | None = None
        mileage_km: int | None = None
        power_kw: float | None = None
        seat_count: int | None = None
        variant: str | None = None

        for raw_label, raw_value in specs.items():
            canonical = _LABEL_MAP.get(raw_label)
            if canonical is None:
                # Partial-match fallback for compound labels
                for key, name in _LABEL_MAP.items():
                    if key in raw_label:
                        canonical = name
                        break
            if canonical is None:
                continue

            if canonical == "first_registration":
                first_registration_date = _normalise_first_reg(raw_value)
            elif canonical == "fuel_type":
                fuel_type = _FUEL_MAP.get(raw_value.lower().strip())
            elif canonical == "mileage_km":
                mileage_km = _extract_mileage(raw_value)
            elif canonical == "power_kw":
                power_kw = _extract_power_kw(raw_value)
            elif canonical == "seat_count":
                seat_count = _extract_seat_count(raw_value)
            elif canonical == "variant":
                variant = raw_value.strip() or None

        # Variant fallback: pull from title if not in spec table
        if variant is None and title:
            variant = title

        return ListingData(
            source_url=url,
            source_site="autobid.de",
            title=title,
            price_eur=price_eur,
            co2_g_km=None,  # not exposed pre-login
            fuel_type=fuel_type,
            first_registration_date=first_registration_date,
            mileage_km=mileage_km,
            power_kw=power_kw,
            variant=variant,
            seat_count=seat_count,
        )
