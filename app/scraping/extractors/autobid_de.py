"""autobid.de extractor — plain httpx + BeautifulSoup (no browser needed, confirmed v7 §2.6).

Why BeautifulSoup over lxml directly: autobid.de renders HTML server-side so there is no
JS to execute — a plain HTTP fetch is enough. BeautifulSoup's .find()/.select() API maps
naturally onto the label→value extraction pattern (iterate <dt>/<dd> or <th>/<td> pairs,
look up the label, read the adjacent value). lxml's native API requires XPath, which is
more verbose and harder to maintain when label strings change. Both use lxml as the
underlying C parser when we pass parser="lxml", so parse throughput is identical.
CO2 is not exposed pre-login on autobid.de — always returned as None.
"""

import json
import re
import urllib.parse
from decimal import Decimal, InvalidOperation

import httpx
from bs4 import BeautifulSoup

from app.catalogue.brands import brand_from_slug_tokens
from app.core.exceptions import ScrapingError
from app.scraping.schemas import ListingData

# Maps the German spec-table labels used on autobid.de to canonical names.
_LABEL_MAP: dict[str, str] = {
    # German
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
    # Brand / manufacturer
    "marke": "brand",
    "hersteller": "brand",
    "make": "brand",
    "fahrzeugmarke": "brand",
    # Model
    "modell": "model",
    "model": "model",
    "fahrzeugmodell": "model",
    # Croatian
    "datum prve registracije": "first_registration",
    "prva registracija": "first_registration",
    "gorivo": "fuel_type",
    "vrsta goriva": "fuel_type",
    "kilometraža": "mileage_km",
    "prijeđeni km": "mileage_km",
    "snaga motora": "power_kw",
    "snaga": "power_kw",
    "broj sjedala": "seat_count",
    "sjedala": "seat_count",
    "verzija": "variant",
    "oprema": "variant",
    "marka": "brand",
    "proizvođač": "brand",
    # VIN / chassis number — German sites label this "FIN", English/Croatian "VIN"
    "fin": "vin",
    "fahrgestellnummer": "vin",
    "fahrzeug-identifizierungsnummer": "vin",
    "vehicle identification no": "vin",
    "vehicle identification number": "vin",
    "vin": "vin",
    "identifikacijski broj vozila": "vin",
    "broj šasije": "vin",
    # Icon-card labels synthesized by _parse_car_parameter_cards()
    "first registration": "first_registration",
    "mileage": "mileage_km",
    "power": "power_kw",
}

_VIN_RE = re.compile(r"^[A-HJ-NPR-Z0-9]{11,17}$")  # excludes I/O/Q, standard VIN charset


def _parse_vin(raw: str | None) -> str | None:
    if not raw:
        return None
    candidate = raw.strip().upper()
    return candidate if _VIN_RE.match(candidate) else None

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
    """Parse '50.000 km', '50000 km', or '233.900 kilometrima' → mileage int."""
    m = re.search(r"(\d[\d.,]*)\s*(?:km|kilomet)", text, re.IGNORECASE)
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


def _parse_json_ld(soup: BeautifulSoup) -> dict:
    """Extract the first schema.org Vehicle/Car JSON-LD block, if present."""
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(data, list):
            data = next((d for d in data if isinstance(d, dict)), {})
        if isinstance(data, dict) and data.get("@type", "").lower() in ("car", "vehicle"):
            return data
    return {}


def _brand_model_from_url_slug(url: str) -> tuple[str | None, str | None]:
    """Parse brand and model from the autobid.de URL slug.

    URL format: /…/artikal/audi-a5-sportback-…-{numeric-id}
    The slug is the reliable source when the page title is the auction center name.

    The brand can span several slug tokens ("mercedes-benz", "land-rover",
    "alfa-romeo"), so it's resolved via the canonical brand vocabulary rather
    than assumed to be the first token — otherwise "mercedes-benz-a-200" yields
    brand "Mercedes" / model "BENZ" and matches nothing. After the brand, the
    model is the next token plus a following numeric badge if present
    ("a" + "200" -> "A 200", "120" -> "120", "x5" -> "X5") — but only when that
    model token is bare letters. When it already contains a digit of its own
    ("a4", "q7", "x5"), the model name is already complete and a following
    digit is an engine-displacement badge, not part of the model — e.g. Audi's
    "a4-40-tdi" is model "A4" + engine badge "40 TDI", and wrongly reading it
    as model "A4 40" makes every genuine A4 catalogue row fail the model-match
    check (confirmed regression: an autobid.de A4 40 TDI listing scored 72%
    against its own correct catalogue rows, all via a bogus model mismatch)."""
    path = urllib.parse.urlparse(url).path
    slug = path.rstrip("/").rsplit("/", 1)[-1]
    # Strip trailing numeric ID
    slug = re.sub(r"-\d+$", "", slug)
    parts = [p for p in slug.split("-") if p]
    if not parts:
        return None, None

    brand, consumed = brand_from_slug_tokens(parts)
    if brand is None:
        # Unknown brand — fall back to the old single-token guess.
        brand = parts[0].capitalize()
        consumed = 1

    rest = parts[consumed:]
    if not rest:
        return brand, None
    model = rest[0].upper()
    if len(rest) > 1 and rest[1].isdigit() and not any(ch.isdigit() for ch in rest[0]):
        model = f"{model} {rest[1]}"
    return brand, model


def _parse_car_parameter_cards(soup: BeautifulSoup) -> dict[str, str]:
    """Collect label->value pairs from autobid.de's icon-based '.car-parameter' cards.

    The Vue/Nuxt frontend renders mileage/power/first-registration/owner-count as
    icon + value pairs (no visible text label, no dt/dd or th/td) — e.g.
    <i class="ab-icon ab-icon-speedmeter">...<span class="car-parameter-value">233.900 kilometrima</span>.
    The icon class is the only reliable label, so map icon name -> canonical field.
    """
    icon_to_label = {
        "ab-icon-date": "first registration",
        "ab-icon-speedmeter": "mileage",
        "ab-icon-performance": "power",
        "ab-icon-owner": "owner",
    }
    specs: dict[str, str] = {}
    for card in soup.select(".car-parameter"):
        icon = card.select_one("i[class*='ab-icon-']")
        if not icon:
            continue
        classes = icon.get("class") or []
        label = next((icon_to_label[c] for c in classes if c in icon_to_label), None)
        if label is None:
            continue
        value_el = card.select_one(".car-parameter-value")
        if value_el:
            specs.setdefault(label, value_el.get_text(strip=True))
    return specs


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
        """Public entrypoint — wraps _extract() so any unexpected failure
        (httpx timeout/connect error, an unhandled parse exception) surfaces
        as the domain-level ScrapingError (-> clean 502) instead of an
        unhandled 500. ScrapingErrors raised deliberately inside _extract()
        pass through unchanged."""
        try:
            return await self._extract(url)
        except ScrapingError:
            raise
        except Exception as exc:
            raise ScrapingError(f"autobid.de: unexpected error scraping {url}: {exc}") from exc

    async def _extract(self, url: str) -> ListingData:
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

        # og:title / page <title> usually carries the vehicle name on autobid.de;
        # H1 is often the auction-center name on the /hr/ (Croatian) site variant.
        title = None
        og_title = soup.find("meta", property="og:title")
        if og_title and og_title.get("content", "").strip():
            title = og_title["content"].strip()
        if not title:
            h2 = soup.find("h2")
            if h2:
                title = h2.get_text(strip=True) or None
        if not title:
            h1 = soup.find("h1")
            if h1:
                title = h1.get_text(strip=True) or None

        price_eur = _extract_price(soup)
        json_ld = _parse_json_ld(soup)
        specs = _parse_spec_table(soup)
        specs.update(_parse_car_parameter_cards(soup))

        first_registration_date: str | None = None
        fuel_type: str | None = None
        mileage_km: int | None = None
        power_kw: float | None = None
        seat_count: int | None = None
        variant: str | None = None
        brand: str | None = None
        model: str | None = None
        vin: str | None = None

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
            elif canonical == "brand":
                brand = raw_value.strip() or None
            elif canonical == "model":
                model = raw_value.strip() or None
            elif canonical == "vin":
                vin = _parse_vin(raw_value)

        # Fill from JSON-LD Vehicle schema when spec table didn't cover a field
        if json_ld:
            if brand is None:
                brand = json_ld.get("brand", {}).get("name") or json_ld.get("manufacturer") or None
                if isinstance(brand, dict):
                    brand = brand.get("name")
            if model is None:
                model = json_ld.get("model") or None
            if mileage_km is None:
                ld_m = json_ld.get("mileageFromOdometer", {})
                if isinstance(ld_m, dict):
                    v = ld_m.get("value")
                    if isinstance(v, (int, float)):
                        mileage_km = int(v)
            if power_kw is None:
                ld_p = json_ld.get("vehicleEngine", {})
                if isinstance(ld_p, dict):
                    v = ld_p.get("enginePower", {}).get("value")
                    if isinstance(v, (int, float)):
                        power_kw = float(v)
            if vin is None:
                ld_vin = json_ld.get("vehicleIdentificationNumber")
                if isinstance(ld_vin, str):
                    vin = _parse_vin(ld_vin)

        # Variant fallback: pull from title if not in spec table
        if variant is None and title:
            variant = title

        # Brand/model URL-slug fallback: autobid.de embeds the vehicle slug in the URL
        # ("…/audi-a5-sportback-…-3464608") which is more reliable than the H1 (which
        # shows the auction center name on the Croatian /hr/ site variant).
        if brand is None or model is None:
            slug_brand, slug_model = _brand_model_from_url_slug(url)
            if brand is None:
                brand = slug_brand
            if model is None:
                model = slug_model

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
            brand=brand,
            model=model,
            vin=vin,
        )
