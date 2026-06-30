"""mobile.de extractor — Playwright + Firefox.

Chromium is blocked outright on mobile.de (Akamai behavioral challenge, confirmed v7 §2.6).
Firefox passes cleanly. One browser instance per call, closed in the finally block.

The page is server-rendered with structured key-value sections; we parse the rendered HTML
with BeautifulSoup rather than fighting hashed class names.
"""

import re

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
from playwright_stealth import Stealth

from app.core.exceptions import ScrapingError
from app.scraping.schemas import ListingData

_STEALTH = Stealth()

_FUEL_MAP: dict[str, str] = {
    "diesel": "diesel",
    "benzin": "petrol",
    "petrol": "petrol",
    "elektro": "electric",
    "electric": "electric",
    "hybrid (benzin)": "hybrid",
    "hybrid (diesel)": "hybrid",
    "mild-hybrid (benzin)": "hybrid",
    "mild-hybrid (diesel)": "hybrid",
    "plug-in-hybrid (benzin)": "hybrid",
    "plug-in-hybrid (diesel)": "hybrid",
    "erdgas (cng)": "cng",
    "autogas (lpg)": "lpg",
}

# German spec-table labels on mobile.de
_LABEL_MAP: dict[str, str] = {
    "erstzulassung": "first_registration",
    "kraftstoffart": "fuel_type",
    "kraftstoff": "fuel_type",
    "kilometerstand": "mileage_km",
    "co2-emissionen": "co2",
    "co2 emissionen": "co2",
    "co2": "co2",
    "leistung": "power_kw",
    "sitze": "seat_count",
    "anzahl sitze": "seat_count",
    "version": "variant",
    "fahrzeugbeschreibung": "variant",
    "ausstattung": "variant",
    "variante": "variant",
}


def _normalise_number(text: str) -> float | None:
    text = text.strip()
    # German number format: '1.500,00' → 1500.0
    if "," in text and "." in text:
        last_comma = text.rfind(",")
        last_dot = text.rfind(".")
        if last_comma > last_dot:
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        parts = text.split(",")
        if len(parts) == 2 and len(parts[1]) == 3:
            text = text.replace(",", "")
        else:
            text = text.replace(",", ".")
    elif "." in text:
        parts = text.split(".")
        if len(parts) == 2 and len(parts[1]) == 3:
            text = text.replace(".", "")
    try:
        return float(text)
    except ValueError:
        return None


def _extract_price(soup: BeautifulSoup) -> float | None:
    for sel in [
        "[data-testid='price-block'] [class*='price']",
        "[class*='price--primary']",
        "[class*='seller-currency']",
        "[class*='listing-price']",
        "[class*='priceBlock']",
        "span[class*='price']",
    ]:
        el = soup.select_one(sel)
        if el:
            text = el.get_text(strip=True)
            text = re.sub(r"[€$£,\s]", lambda m: "" if m.group() in "€$£" else m.group(), text)
            m = re.search(r"([\d.,]+)", text)
            if m:
                v = _normalise_number(m.group(1))
                if v and v > 0:
                    return v
    # Fallback: any element whose text looks like a EUR price
    pattern = re.compile(r"([\d.,]+)\s*€|€\s*([\d.,]+)")
    for el in soup.find_all(string=pattern):
        m = pattern.search(el)
        if m:
            raw = m.group(1) or m.group(2)
            v = _normalise_number(raw)
            if v and v > 100:  # sanity floor — avoid matching year/mileage fragments
                return v
    return None


def _extract_power_kw(text: str) -> float | None:
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*kw", text, re.IGNORECASE)
    if m:
        return _normalise_number(m.group(1))
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
    # mobile.de also renders specs in <li> pairs inside "g-row"
    for li in soup.find_all("li"):
        text = li.get_text(strip=True)
        if ":" in text:
            parts = text.split(":", 1)
            label = parts[0].strip().lower()
            if label:
                specs.setdefault(label, parts[1].strip())
    return specs


class MobileDeExtractor:
    async def extract(self, url: str) -> ListingData:
        async with async_playwright() as pw:
            # Firefox is required — Chromium is blocked outright by Akamai on mobile.de
            browser = await pw.firefox.launch(headless=True)
            try:
                context = await browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) "
                        "Gecko/20100101 Firefox/125.0"
                    ),
                    locale="de-DE",
                )
                page = await context.new_page()
                await _STEALTH.apply_stealth_async(page)

                response = await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
                if response and response.status >= 400:
                    raise ScrapingError(
                        f"mobile.de returned {response.status} for {url}"
                    )
                await page.wait_for_load_state("networkidle", timeout=15_000)
                html = await page.content()
            finally:
                await browser.close()

        soup = BeautifulSoup(html, "lxml")

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
        co2_g_km: float | None = None
        seat_count: int | None = None
        variant: str | None = None

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
                v = raw_value.strip()
                first_registration_date = v if v and v not in ("-", "n/a") else None
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

        if variant is None and title:
            variant = title

        return ListingData(
            source_url=url,
            source_site="mobile.de",
            title=title,
            price_eur=price_eur,
            co2_g_km=co2_g_km,
            fuel_type=fuel_type,
            first_registration_date=first_registration_date,
            mileage_km=mileage_km,
            power_kw=power_kw,
            variant=variant,
            seat_count=seat_count,
        )
