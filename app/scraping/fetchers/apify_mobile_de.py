"""mobile.de listing fetch via the Apify actor `ivanvs/mobile-de-scraper`.

mobile.de is behind Akamai Bot Manager — direct scraping (see the retired
app/scraping/extractors/mobile_de.py) gets IP-flagged after one request. The
Apify actor is a paid ($0.0015/result) run-and-wait HTTPS call instead, so
this fetcher needs no browser — see docs/MOBILE_DE_APIFY_SPEC.md.

The actor accepts one listing URL and is asked for `maxRecords` results (the
actor's minimum is 10), but only `items[0]` is ever used — one on-demand
fetch always wants exactly one listing.
"""

import re
from urllib.parse import parse_qs, urlparse

import httpx

_VIN_RE = re.compile(r"^[A-HJ-NPR-Z0-9]{11,17}$")  # excludes I/O/Q, standard VIN charset

from app.core.config import get_settings
from app.core.exceptions import ScrapingError
from app.scraping.schemas import ListingData

APIFY_RUN_SYNC_URL = (
    "https://api.apify.com/v2/acts/{actor_id}/run-sync-get-dataset-items"
    "?token={token}&timeout={timeout}&format=json"
)

_FUEL_MAP: dict[str, str] = {
    "diesel": "diesel",
    "petrol": "petrol",
    "benzin": "petrol",
    "electric": "electric",
    "elektro": "electric",
    "hybrid": "hybrid",
}


async def fetch_listing(url: str) -> ListingData:
    settings = get_settings()
    if not settings.apify_api_token:
        raise ScrapingError("APIFY_API_TOKEN not configured")

    # Apify's REST API takes the actor id as "username~actor-name" — the
    # config/env value stays in the human-readable "username/actor-name"
    # form (as shown on the actor's Apify Store page), and a "/" in the URL
    # path is read as an extra path segment, which 404s.
    actor_id = settings.apify_mobile_de_actor_id.replace("/", "~")
    endpoint = APIFY_RUN_SYNC_URL.format(
        actor_id=actor_id,
        token=settings.apify_api_token,
        timeout=settings.apify_call_timeout_seconds,
    )
    payload = {"urls": [{"url": url}], "maxRecords": 10}

    async with httpx.AsyncClient(timeout=settings.apify_call_timeout_seconds + 10) as client:
        response = await client.post(endpoint, json=payload)

    # run-sync-get-dataset-items returns 201 (run completed, dataset created)
    # on the normal success path, not 200.
    if response.status_code not in (200, 201):
        raise ScrapingError(f"Apify returned {response.status_code} for {url}")

    items = response.json()
    if not items:
        raise ScrapingError(f"Apify returned empty dataset for {url}")

    return _parse(items[0], url)


def _parse(item: dict, source_url: str) -> ListingData:
    """Maps the Apify actor's output to our internal ListingData contract."""
    props = item.get("properties", {})
    price = item.get("price", {})

    # firstRegistration is "MM/YYYY" — kept as a raw string; the calculate
    # router's _parse_date already handles that exact format.
    first_registration_date = props.get("firstRegistration") or None

    # power: "150 kW (204 hp)" -> 150.0
    power_kw = None
    raw_power = props.get("power", "")
    if raw_power and "kW" in raw_power:
        try:
            power_kw = float(raw_power.split("kW")[0].strip().split()[-1])
        except (ValueError, IndexError):
            pass

    # CO2: "132 g/km" -> 132.0
    co2_g_km = None
    raw_co2 = props.get("co2Emission")
    if raw_co2:
        try:
            co2_g_km = float(raw_co2.replace("g/km", "").strip())
        except ValueError:
            pass

    fuel_type = _normalise_fuel(props.get("fuelType"))
    mileage_km = _parse_mileage(props.get("milage"))
    vin = _parse_vin(props.get("vin") or item.get("vin"))

    return ListingData(
        source_url=source_url,
        source_site="mobile.de",
        title=item.get("subTitle"),
        brand=item.get("manufacturer"),
        model=item.get("model"),
        variant=item.get("subTitle"),
        price_eur=float(price["amount"]) if price.get("amount") is not None else None,
        first_registration_date=first_registration_date,
        mileage_km=mileage_km,
        power_kw=power_kw,
        fuel_type=fuel_type,
        co2_g_km=co2_g_km,
        emission_class=props.get("emissionClass"),
        scraper="apify_mobile_de",
        vin=vin,
    )


def _parse_vin(raw: str | None) -> str | None:
    if not raw:
        return None
    candidate = raw.strip().upper()
    return candidate if _VIN_RE.match(candidate) else None


def _normalise_fuel(raw: str | None) -> str | None:
    if not raw:
        return None
    raw = raw.lower()
    for key, value in _FUEL_MAP.items():
        if key in raw:
            return value
    return raw


def _parse_mileage(raw: str | None) -> int | None:
    if not raw:
        return None
    try:
        return int(raw.replace(",", "").replace(".", "").replace("km", "").strip())
    except ValueError:
        return None


def extract_mobile_de_id(url: str) -> str | None:
    """Extracts the listing ID from either mobile.de URL format: the
    id-only query-param format (details.html?id=459632333) or the slug
    format (/auto-inserat/some-slug/459632333.html)."""
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    if "id" in qs:
        return qs["id"][0]
    match = re.search(r"/(\d+)\.html", parsed.path)
    if match:
        return match.group(1)
    return None
