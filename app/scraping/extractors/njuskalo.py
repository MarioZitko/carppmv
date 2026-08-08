"""njuskalo.hr extractor — Playwright + Chromium (confirmed v7 §2.6).

One browser instance per call, closed in the finally block.
Price is normally in EUR; if in HRK it is converted at the fixed rate
HRK_TO_EUR (1 EUR = 7.53450 HRK — Croatian National Bank fixed rate at ERM II entry).
CO2 is extracted if explicitly shown on the page, never guessed.
seat_count is extracted only when explicitly stated (e.g. "7 sjedala"), never inferred.
"""

import re

from bs4 import BeautifulSoup
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright
from playwright_stealth import Stealth

from app.core.exceptions import ScrapingError
from app.scraping.schemas import ListingData

HRK_TO_EUR = 7.53450  # fixed ECB conversion rate

_STEALTH = Stealth()

_FUEL_MAP: dict[str, str] = {
    "benzin": "petrol",
    "dizel": "diesel",
    "hibrid": "hybrid",
    "električni": "electric",
    "elektrican": "electric",
    "električni/benzin": "hybrid",
    "plin": "lpg",
    "lpg": "lpg",
}


def _parse_price(text: str) -> tuple[float, str] | None:
    """Return (amount, currency) or None. Handles '€ 12.500' and '94.153 kn'."""
    text = text.strip().replace("\xa0", " ")
    # EUR formats
    m = re.search(r"€\s*([\d.,]+)|([\d.,]+)\s*€", text)
    if m:
        raw = (m.group(1) or m.group(2)).strip()
        val = _normalise_number(raw)
        if val:
            return val, "EUR"
    # HRK formats (kn, HRK)
    m = re.search(r"([\d.,]+)\s*(?:kn|HRK)", text, re.IGNORECASE)
    if m:
        val = _normalise_number(m.group(1))
        if val:
            return val, "HRK"
    return None


def _normalise_number(text: str) -> float | None:
    """Handles both '12.500,00' (HRK/HR format) and '12,500.00' (EN format)."""
    text = text.strip()
    if "," in text and "." in text:
        # Determine which is the decimal separator by position from the right
        last_comma = text.rfind(",")
        last_dot = text.rfind(".")
        if last_comma > last_dot:
            # comma is decimal — HRK/HR format: 12.500,00
            text = text.replace(".", "").replace(",", ".")
        else:
            # dot is decimal — EN format: 12,500.00
            text = text.replace(",", "")
    elif "," in text:
        # Only comma — could be decimal (12,5) or thousands (12,500)
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


def _extract_power_kw(text: str) -> float | None:
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*kw", text, re.IGNORECASE)
    if m:
        return _normalise_number(m.group(1))
    # HP only: convert roughly, but only return if kW not found elsewhere
    m = re.search(r"(\d+)\s*(?:ks|hp|ps|cv)", text, re.IGNORECASE)
    if m:
        hp = float(m.group(1))
        return round(hp * 0.7355, 1)
    return None


def _extract_mileage(text: str) -> int | None:
    m = re.search(r"([\d.,]+)\s*km", text, re.IGNORECASE)
    if m:
        v = _normalise_number(m.group(1))
        return int(v) if v is not None else None
    return None


def _extract_co2(text: str) -> float | None:
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*g(?:/km|\\km)?", text, re.IGNORECASE)
    if m:
        return _normalise_number(m.group(1))
    return None


def _extract_seat_count(text: str) -> int | None:
    m = re.search(r"(\d+)", text.strip())
    if m:
        v = int(m.group(1))
        return v if 1 <= v <= 20 else None
    return None


def _parse_spec_table(soup: BeautifulSoup) -> dict[str, str]:
    specs: dict[str, str] = {}
    # njuskalo uses dl/dt/dd or table rows with class "classified-*"
    for dt in soup.find_all("dt"):
        label = dt.get_text(strip=True).lower().rstrip(":")
        dd = dt.find_next_sibling("dd")
        if dd:
            specs[label] = dd.get_text(strip=True)
    for row in soup.find_all("tr"):
        cells = row.find_all(["th", "td"])
        if len(cells) >= 2:
            label = cells[0].get_text(strip=True).lower().rstrip(":")
            if label:
                specs[label] = cells[1].get_text(strip=True)
    return specs


_LABEL_MAP: dict[str, str] = {
    # Croatian
    "godište": "year",
    "godina": "year",
    "datum prve registracije": "first_registration",
    "prva registracija": "first_registration",
    "gorivo": "fuel_type",
    "vrsta goriva": "fuel_type",
    "kilometraža": "mileage_km",
    "prijeđeni km": "mileage_km",
    "snaga motora": "power_kw",
    "snaga": "power_kw",
    "co2 emisija": "co2",
    "co2": "co2",
    "emisija co2": "co2",
    "broj sjedala": "seat_count",
    "sjedala": "seat_count",
    "verzija": "variant",
    "oprema": "variant",
    "marka": "brand",
    "proizvođač": "brand",
    "model": "model",
    "broj šasije": "vin",
    "broj sasije": "vin",
    "vin broj": "vin",
    "vin": "vin",
    # English fallbacks (some listings are bilingual)
    "fuel": "fuel_type",
    "mileage": "mileage_km",
    "power": "power_kw",
    "seats": "seat_count",
    "variant": "variant",
    "make": "brand",
    "brand": "brand",
    "first registration": "first_registration",
    "chassis number": "vin",
    "vin number": "vin",
}

_VIN_RE = re.compile(r"^[A-HJ-NPR-Z0-9]{11,17}$")  # excludes I/O/Q, standard VIN charset


def _normalise_vin(text: str) -> str | None:
    candidate = text.strip().upper()
    return candidate if _VIN_RE.match(candidate) else None


class NjuskaloExtractor:
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
            raise ScrapingError(f"njuskalo.hr: unexpected error scraping {url}: {exc}") from exc

    async def _extract(self, url: str) -> ListingData:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            try:
                context = await browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0.0.0 Safari/537.36"
                    )
                )
                page = await context.new_page()
                await _STEALTH.apply_stealth_async(page)

                response = await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
                if response and response.status >= 400:
                    raise ScrapingError(
                        f"njuskalo.hr returned {response.status} for {url}"
                    )
                try:
                    await page.wait_for_load_state("networkidle", timeout=15_000)
                except PlaywrightTimeoutError:
                    pass  # bot-challenge pages poll indefinitely; fall through to the block check below
                # njuskalo.hr fronts listings with a Radware bot-management challenge that
                # redirects to validate.perfdrive.com instead of returning a 4xx — detect the
                # redirect so callers get a clear error instead of an all-None ListingData.
                if "perfdrive.com" in page.url:
                    raise ScrapingError(
                        f"njuskalo.hr returned 403 (blocked by bot-management challenge) for {url}"
                    )
                html = await page.content()
            finally:
                await browser.close()

        soup = BeautifulSoup(html, "lxml")

        title = None
        h1 = soup.find("h1")
        if h1:
            title = h1.get_text(strip=True) or None

        # Price — look for dedicated price element
        price_eur: float | None = None
        for sel in [
            "[class*='price']",
            "[class*='cijena']",
            "[class*='Price']",
        ]:
            el = soup.select_one(sel)
            if el:
                parsed = _parse_price(el.get_text())
                if parsed:
                    amount, currency = parsed
                    price_eur = amount / HRK_TO_EUR if currency == "HRK" else amount
                    break

        specs = _parse_spec_table(soup)

        first_registration_date: str | None = None
        fuel_type: str | None = None
        mileage_km: int | None = None
        power_kw: float | None = None
        co2_g_km: float | None = None
        seat_count: int | None = None
        variant: str | None = None
        brand: str | None = None
        model: str | None = None
        year: str | None = None
        vin: str | None = None

        for raw_label, raw_value in specs.items():
            canonical = _LABEL_MAP.get(raw_label)
            if canonical is None:
                for key, name in _LABEL_MAP.items():
                    if key in raw_label:
                        canonical = name
                        break
            if canonical is None:
                continue

            if canonical == "first_registration":
                first_registration_date = raw_value.strip() or None
            elif canonical == "year":
                year = raw_value.strip()
            elif canonical == "fuel_type":
                fuel_type = _FUEL_MAP.get(raw_value.lower().strip())
            elif canonical == "mileage_km":
                mileage_km = _extract_mileage(raw_value)
            elif canonical == "power_kw":
                power_kw = _extract_power_kw(raw_value)
            elif canonical == "co2":
                co2_g_km = _extract_co2(raw_value)
            elif canonical == "seat_count":
                seat_count = _extract_seat_count(raw_value)
            elif canonical == "variant":
                variant = raw_value.strip() or None
            elif canonical == "brand":
                brand = raw_value.strip() or None
            elif canonical == "model":
                model = raw_value.strip() or None
            elif canonical == "vin":
                vin = _normalise_vin(raw_value)

        # Use year as first_registration_date if more specific date not found
        if first_registration_date is None and year:
            first_registration_date = year

        if variant is None and title:
            variant = title

        return ListingData(
            source_url=url,
            source_site="njuskalo",
            title=title,
            price_eur=price_eur,
            co2_g_km=co2_g_km,
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
