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
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import httpx

from app.core.config import get_settings
from app.core.exceptions import ScrapingError
from app.scraping.parsing import parse_number
from app.scraping.schemas import ListingData

_VIN_RE = re.compile(r"^[A-HJ-NPR-Z0-9]{11,17}$")  # excludes I/O/Q, standard VIN charset

APIFY_RUN_SYNC_URL = (
    "https://api.apify.com/v2/acts/{actor_id}/run-sync-get-dataset-items"
    "?token={token}&timeout={timeout}&format=json"
)

# Ordered, and _normalise_fuel() matches by substring, so COMPOUND ENTRIES MUST
# COME FIRST. mobile.de labels a hybrid "Elektro/Benzin" (or "Electric/Petrol");
# with the single fuels listed first, "benzin"/"petrol" matched inside those and
# every hybrid resolved to plain petrol.
#
# Hybrids resolve to their combustion fuel for the same reason as in the
# autoscout24 extractor: the PPMV table is keyed on (CO2Standard, FuelType) and
# a bare "hybrid" cannot select one.
#
# German labels are carried alongside the English ones as defence. The actor is
# handed a lang=en URL (see _with_english_locale) and its documented output is
# English, but it exposes no locale input of its own, so this must not depend on
# the actor's behaviour staying that way.
_FUEL_MAP: tuple[tuple[str, str], ...] = (
    # Compound / hybrid labels first.
    ("elektro/diesel", "diesel"),
    ("electric/diesel", "diesel"),
    ("elektro/benzin", "petrol"),
    ("electric/petrol", "petrol"),
    ("hybrid (diesel", "diesel"),
    ("hybrid (benzin", "petrol"),
    ("diesel mildhybrid", "diesel"),
    ("benzin mildhybrid", "petrol"),
    # Single fuels.
    ("diesel", "diesel"),
    ("petrol", "petrol"),
    ("benzin", "petrol"),
    ("gasoline", "petrol"),
    ("elektro", "electric"),
    ("electric", "electric"),
    ("autogas", "petrol"),
    ("lpg", "petrol"),
    ("erdgas", "petrol"),
    ("cng", "petrol"),
    ("ethanol", "petrol"),
    # Bare "hybrid" last — no parent-fuel signal, non-diesel is the safe read.
    ("hybrid", "petrol"),
)


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
    payload = {"urls": [{"url": _canonical_actor_url(url)}], "maxRecords": 10}

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


CANONICAL_DETAILS_URL = "https://suchen.mobile.de/fahrzeuge/details.html?id={listing_id}&lang=en"


def _canonical_actor_url(url: str) -> str:
    """Rewrites any mobile.de listing URL into the one form the actor accepts.

    The actor silently skips any URL not starting with one of its whitelisted
    prefixes (https://suchen.mobile.de/fahrzeuge/details.html, .../auto-inserat/,
    ...) and returns an empty dataset. Links shared from the mobile.de app or
    mobile site are `https://m.mobile.de/fahrzeuge/details.html?id=...&utm_...`,
    which fail that prefix check even though they name a perfectly valid
    listing. Rebuilding the URL from the listing id fixes every host/path
    variant at once and drops tracking params.

    A URL with no recognisable listing id is passed through with only the
    locale pinned (see _with_english_locale).
    """
    listing_id = extract_mobile_de_id(url)
    if listing_id:
        return CANONICAL_DETAILS_URL.format(listing_id=listing_id)
    return _with_english_locale(url)


def _with_english_locale(url: str) -> str:
    """Forces mobile.de's `lang=en` on the URL handed to the actor.

    Everything _parse() reads is a pre-formatted display string chosen by
    whatever locale mobile.de rendered the page in — fuelType, power, mileage
    and co2Emission are all text, not codes. The actor exposes no language
    input of its own and we pass the user's URL straight through, so the page
    language is currently whatever the user happened to be browsing in. Pinning
    it makes the English-only parsing here true by construction.

    Safe for the cache: the ListingCache key in mobile_de_service.py is built
    from extract_mobile_de_id(), which reads the id and ignores other params, so
    this does not fragment cache entries.
    """
    parsed = urlparse(url)
    params = parse_qs(parsed.query, keep_blank_values=True)
    params["lang"] = ["en"]
    return urlunparse(parsed._replace(query=urlencode(params, doseq=True)))


def _parse(item: dict, source_url: str) -> ListingData:
    """Maps the Apify actor's output to our internal ListingData contract."""
    props = item.get("properties", {})
    price = item.get("price", {})

    # firstRegistration is "MM/YYYY" — kept as a raw string; the calculate
    # router's _parse_date already handles that exact format.
    first_registration_date = props.get("firstRegistration") or None

    # power: "150 kW (204 hp)" -> 150.0, and German "110,5 kW" -> 110.5.
    # parse_number handles the decimal comma; a bare float() raised ValueError
    # on it and silently dropped the value.
    power_kw = None
    raw_power = props.get("power", "")
    if raw_power and "kW" in raw_power:
        head = raw_power.split("kW")[0].strip().split()
        if head:
            power_kw = parse_number(head[-1])

    # CO2: "132 g/km" -> 132.0, and German "132,0 g/km" -> 132.0 (a bare
    # float() raised ValueError on the decimal comma and dropped the value).
    # co2Emission is frequently present-but-null, so it needs the guard.
    co2_g_km = None
    raw_co2 = props.get("co2Emission")
    if raw_co2:
        co2_g_km = parse_number(raw_co2.replace("g/km", "").strip())

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
    for key, value in _FUEL_MAP:
        if key in raw:
            return value
    # Return None rather than the raw source string, as every other extractor
    # does. Leaking it puts untranslated text into ListingData.fuel_type, which
    # then gets echoed into the user-facing warning in calculate/router.py and
    # rendered verbatim by ParsedFieldsCard.
    return None


def _parse_mileage(raw: str | None) -> int | None:
    """"79,530 km" / "79.530 km" / "1.234.567 km" -> 79530 / 79530 / 1234567.

    Deliberately NOT parse_number(): a mileage has no fractional part, so every
    separator is a thousands separator regardless of locale and deleting all of
    them is both unambiguous and correct for any number of groups.
    parse_number() has to reason about which separator is the decimal point,
    which makes it strictly worse here — it rejects "1.234.567" outright.
    """
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
