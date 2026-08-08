"""autoscout24.com extractor — Playwright + Chromium.

Data is parsed from the __NEXT_DATA__ JSON payload embedded in the page, not from CSS
selectors. CSS class names on AutoScout24 are hashed at build time and change with every
deploy; __NEXT_DATA__ is part of the Next.js data contract and its top-level structure
is stable across deploys.

One browser instance per call, closed in the finally block.
"""

import json
import re
from typing import Any

from playwright.async_api import async_playwright
from playwright_stealth import Stealth

from app.core.exceptions import ScrapingError
from app.scraping.schemas import ListingData

_STEALTH = Stealth()

_FUEL_MAP: dict[str, str] = {
    # AutoScout24 fuel keys (from __NEXT_DATA__ fuel.key or fuel.id)
    "d": "diesel",
    "b": "petrol",
    "e": "electric",
    "h": "hybrid",
    "lpg": "lpg",
    "cng": "cng",
    # Full strings also seen
    "diesel": "diesel",
    "petrol": "petrol",
    "benzin": "petrol",
    "electric": "electric",
    "hybrid": "hybrid",
    "plug-in hybrid": "hybrid",
    "mild hybrid": "hybrid",
}


def _get(obj: Any, *keys: str) -> Any:
    """Safe nested dict access: _get(d, 'a', 'b', 'c') → d['a']['b']['c'] or None."""
    for key in keys:
        if not isinstance(obj, dict):
            return None
        obj = obj.get(key)
    return obj


def _find_listing(data: dict) -> dict | None:
    """Navigate __NEXT_DATA__ props to the listing object.

    AutoScout24 has changed the path several times; try known variants in order.
    """
    page_props = _get(data, "props", "pageProps")
    if page_props is None:
        return None
    # Variant D (current as of 2026) — details split across "listingDetails" with
    # vehicle specs nested under "vehicle" and pricing/imgAltText at the top level.
    details = _get(page_props, "listingDetails")
    if isinstance(details, dict) and details:
        merged = dict(details.get("vehicle") or {})
        merged["prices"] = details.get("prices")
        merged["price"] = details.get("price")
        merged["imgAltText"] = details.get("imgAltText")
        return merged
    # Variant A (common as of 2024)
    listing = _get(page_props, "listing")
    if isinstance(listing, dict) and listing:
        return listing
    # Variant B
    listing = _get(page_props, "data", "listing")
    if isinstance(listing, dict) and listing:
        return listing
    # Variant C — wrapped in an "item" key
    listing = _get(page_props, "item")
    if isinstance(listing, dict) and listing:
        return listing
    return None


def _parse_price(listing: dict) -> float | None:
    # Current structure: prices.public.priceRaw (a dict, not a list)
    val = _get(listing, "prices", "public", "priceRaw")
    if isinstance(val, (int, float)):
        return float(val)
    # prices is a list; first entry is the main asking price
    prices = listing.get("prices")
    if isinstance(prices, list) and prices:
        val = _get(prices[0], "value")
        if isinstance(val, (int, float)):
            return float(val)
    # Some structures use a single price object
    val = _get(listing, "price", "value")
    if isinstance(val, (int, float)):
        return float(val)
    val = listing.get("price")
    if isinstance(val, (int, float)):
        return float(val)
    return None


def _parse_fuel(listing: dict) -> str | None:
    # Current structure: fuelCategory.raw is a single-letter code (e.g. "B", "D")
    val = _get(listing, "fuelCategory", "raw")
    if isinstance(val, str):
        mapped = _FUEL_MAP.get(val.lower().strip())
        if mapped:
            return mapped
    # fuel.id or fuel.key
    for path in [("fuel", "id"), ("fuel", "key"), ("fuelCategory", "key"), ("fuel",)]:
        val = _get(listing, *path) if len(path) > 1 else listing.get(path[0])
        if isinstance(val, str):
            mapped = _FUEL_MAP.get(val.lower().strip())
            if mapped:
                return mapped
    return None


def _parse_power_kw(listing: dict) -> float | None:
    # Current structure: rawPowerInKw is a plain int
    val = listing.get("rawPowerInKw")
    if isinstance(val, (int, float)):
        return float(val)
    # engine.power.kw is the most reliable path in older structures
    for path in [
        ("engine", "power", "kw"),
        ("power", "kw"),
        ("kw",),
    ]:
        val = _get(listing, *path) if len(path) > 1 else listing.get(path[0])
        if isinstance(val, (int, float)):
            return float(val)
    return None


def _parse_mileage(listing: dict) -> int | None:
    # Current structure: mileageInKmRaw is a plain int
    val = listing.get("mileageInKmRaw")
    if isinstance(val, (int, float)):
        return int(val)
    for path in [("mileage", "value"), ("mileage",), ("km",)]:
        val = _get(listing, *path) if len(path) > 1 else listing.get(path[0])
        if isinstance(val, (int, float)):
            return int(val)
    return None


def _parse_co2(listing: dict) -> float | None:
    # Current structure: co2emissionInGramPerKmWithFallback.raw (often None — not guessed)
    val = _get(listing, "co2emissionInGramPerKmWithFallback", "raw")
    if isinstance(val, (int, float)):
        return float(val)
    for path in [
        ("co2Emission", "value"),
        ("emissionCo2", "value"),
        ("co2",),
    ]:
        val = _get(listing, *path) if len(path) > 1 else listing.get(path[0])
        if isinstance(val, (int, float)):
            return float(val)
    return None


def _parse_first_registration(listing: dict) -> str | None:
    for key in (
        "firstRegistrationDateRaw",
        "firstRegistrationDate",
        "firstRegistration",
        "first_registration",
        "registrationDate",
        "registered",
    ):
        val = listing.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return None


def _parse_variant(listing: dict) -> str | None:
    for key in ("version", "trim", "variant", "versionId", "modelVersionInput"):
        val = listing.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return None


def _parse_seat_count(listing: dict) -> int | None:
    for path in [("seats",), ("numberOfSeats",), ("specs", "seats")]:
        val = _get(listing, *path) if len(path) > 1 else listing.get(path[0])
        if isinstance(val, int) and 1 <= val <= 20:
            return val
    return None


def _parse_brand(listing: dict) -> str | None:
    make = listing.get("make")
    if isinstance(make, dict):
        return make.get("name") or make.get("label") or None
    if isinstance(make, str) and make.strip():
        return make.strip()
    return None


_ENGINE_SUFFIX_RE = re.compile(r"^[a-zA-Z]{1,3}$")


def _parse_model_suffix(listing: dict) -> str | None:
    """AutoScout24's `model` field is a bare number ("120"); the engine-code
    suffix that actually distinguishes trims ("i"/"d"/"e"/"xd"...) only shows
    up as the first whitespace-separated token of modelVersionInput, e.g.
    "i Advantage|NAV|SHZG|LED|PDC|Lenkradhzg|LWS" for a 120i — the rest of that
    string is a trim name plus a pipe-separated equipment list. Without this,
    the catalogue's model field ("120i") never matches the listing's ("120").

    A leading "x" is xDrive (all-wheel drive), not part of the engine code, so
    "xd"/"xi"/"xe" are folded to the bare fuel letter "d"/"i"/"e" — otherwise
    the model becomes "420xd", which no catalogue "420d"/"420i" row matches (and
    the stray "x" even trips the model-mismatch penalty). Drivetrain is captured
    elsewhere; the model badge only needs the series number + fuel letter."""
    val = listing.get("modelVersionInput")
    if isinstance(val, str) and val.strip():
        first_token = val.strip().split(maxsplit=1)[0]
        if _ENGINE_SUFFIX_RE.match(first_token):
            suffix = first_token.lower()
            if len(suffix) == 2 and suffix[0] == "x" and suffix[1] in "die":
                suffix = suffix[1]
            return suffix
    return None


def _parse_model_name(listing: dict) -> str | None:
    model = listing.get("model")
    if isinstance(model, dict):
        base = model.get("name") or model.get("label") or None
    elif isinstance(model, str) and model.strip():
        base = model.strip()
    else:
        base = None
    if base is None:
        return None
    suffix = _parse_model_suffix(listing)
    if suffix and not base.lower().endswith(suffix):
        return f"{base}{suffix}"
    return base


_VIN_RE = re.compile(r"^[A-HJ-NPR-Z0-9]{11,17}$")  # excludes I/O/Q, standard VIN charset


def _parse_vin(listing: dict) -> str | None:
    for key in ("vin", "vehicleIdentificationNumber"):
        val = listing.get(key)
        if isinstance(val, str) and val.strip():
            candidate = val.strip().upper()
            if _VIN_RE.match(candidate):
                return candidate
    return None


def _parse_title(listing: dict) -> str | None:
    for key in ("imgAltText", "title", "name", "shortTitle"):
        val = listing.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    # Assemble from make + model + version
    parts = [
        listing.get("make", {}).get("name") if isinstance(listing.get("make"), dict) else listing.get("make"),
        listing.get("model", {}).get("name") if isinstance(listing.get("model"), dict) else listing.get("model"),
        _parse_variant(listing),
    ]
    assembled = " ".join(p for p in parts if isinstance(p, str) and p.strip())
    return assembled or None


class AutoScout24Extractor:
    async def extract(self, url: str) -> ListingData:
        """Public entrypoint — wraps _extract() so any unexpected failure
        (Playwright timeout, an unhandled parse exception) surfaces as the
        domain-level ScrapingError (-> clean 502) instead of an unhandled
        500. ScrapingErrors raised deliberately inside _extract() pass
        through unchanged."""
        try:
            return await self._extract(url)
        except ScrapingError:
            raise
        except Exception as exc:
            raise ScrapingError(f"autoscout24.com: unexpected error scraping {url}: {exc}") from exc

    async def _extract(self, url: str) -> ListingData:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            try:
                context = await browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0.0.0 Safari/537.36"
                    ),
                    locale="en-GB",
                )
                page = await context.new_page()
                await _STEALTH.apply_stealth_async(page)

                response = await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
                if response and response.status >= 400:
                    raise ScrapingError(
                        f"autoscout24.com returned {response.status} for {url}"
                    )

                # Extract __NEXT_DATA__ from the page source before any JS runs further
                next_data_json = await page.evaluate("""
                    () => {
                        const el = document.getElementById('__NEXT_DATA__');
                        return el ? el.textContent : null;
                    }
                """)
            finally:
                await browser.close()

        if not next_data_json:
            raise ScrapingError(
                f"autoscout24.com: __NEXT_DATA__ not found on page {url}"
            )

        try:
            data = json.loads(next_data_json)
        except json.JSONDecodeError as exc:
            raise ScrapingError(
                f"autoscout24.com: could not parse __NEXT_DATA__ JSON: {exc}"
            ) from exc

        listing = _find_listing(data)
        if listing is None:
            raise ScrapingError(
                f"autoscout24.com: could not locate listing object in __NEXT_DATA__ for {url}"
            )

        return ListingData(
            source_url=url,
            source_site="autoscout24",
            title=_parse_title(listing),
            price_eur=_parse_price(listing),
            co2_g_km=_parse_co2(listing),
            fuel_type=_parse_fuel(listing),
            first_registration_date=_parse_first_registration(listing),
            mileage_km=_parse_mileage(listing),
            power_kw=_parse_power_kw(listing),
            variant=_parse_variant(listing),
            seat_count=_parse_seat_count(listing),
            brand=_parse_brand(listing),
            model=_parse_model_name(listing),
            vin=_parse_vin(listing),
        )
