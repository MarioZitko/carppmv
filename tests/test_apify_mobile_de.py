"""Unit tests for the Apify mobile.de fetcher — no network."""

from urllib.parse import parse_qs, urlparse

import pytest

from app.scraping.fetchers.apify_mobile_de import (
    _canonical_actor_url,
    _normalise_fuel,
    _parse,
    _parse_mileage,
    _with_english_locale,
    extract_mobile_de_id,
)

SAMPLE = {
    "id": 459632333,
    "manufacturer": "Audi",
    "model": "A5",
    "subTitle": "Sportback 40 TFSI*S LINE",
    "properties": {
        "firstRegistration": "03/2021",
        "power": "150 kW (204 hp)",
        "fuelType": "Petrol",
        "co2Emission": "132 g/km",
        "milage": "79,530 km",
        "emissionClass": "Euro6d-TEMP",
        "vin": "wauzzz8k5na012345",
    },
    "price": {"amount": 29990, "currency": "EUR"},
}


def test_parse_fields():
    listing = _parse(SAMPLE, "https://suchen.mobile.de/auto-inserat/audi-a5/459632333.html")
    assert listing.source_site == "mobile.de"
    assert listing.brand == "Audi"
    assert listing.model == "A5"
    assert listing.price_eur == 29990.0
    assert listing.co2_g_km == 132.0
    assert listing.power_kw == 150.0
    assert listing.fuel_type == "petrol"
    assert listing.first_registration_date == "03/2021"
    assert listing.mileage_km == 79530
    assert listing.emission_class == "Euro6d-TEMP"
    assert listing.scraper == "apify_mobile_de"
    assert listing.vin == "WAUZZZ8K5NA012345"


def test_parse_vin_absent():
    sample = {**SAMPLE, "properties": {**SAMPLE["properties"]}}
    del sample["properties"]["vin"]
    listing = _parse(sample, "https://suchen.mobile.de/auto-inserat/audi-a5/459632333.html")
    assert listing.vin is None


def test_extract_id_slug():
    url = "https://suchen.mobile.de/auto-inserat/audi-a5-sportback/459632333.html"
    assert extract_mobile_de_id(url) == "459632333"


def test_extract_id_query():
    url = "https://suchen.mobile.de/fahrzeuge/details.html?id=459632333&dam=false"
    assert extract_mobile_de_id(url) == "459632333"


MOBILE_SITE_SHARE_URL = (
    "https://m.mobile.de/fahrzeuge/details.html?id=45688064542528"
    "&utm_campaign=socialbuttons&utm_source=other&utm_medium=social"
    "&utm_content=app_android_vip&lang=en"
)


def test_extract_id_mobile_site():
    assert extract_mobile_de_id(MOBILE_SITE_SHARE_URL) == "45688064542528"


def test_extract_id_none_when_absent():
    assert extract_mobile_de_id("https://suchen.mobile.de/fahrzeuge/search") is None


# ---------------------------------------------------------------------------
# Locale robustness
#
# Everything _parse() reads is a pre-formatted display string chosen by the
# locale mobile.de rendered the page in. The actor exposes no language input, so
# fetch_listing pins lang=en on the URL — but the parsing must not depend on
# that having worked, hence the German-shaped payload below.
# ---------------------------------------------------------------------------

GERMAN_SAMPLE = {
    "id": 459632333,
    "manufacturer": "Audi",
    "model": "A5",
    "subTitle": "Sportback 40 TFSI*S LINE",
    "properties": {
        "firstRegistration": "03/2021",
        "power": "110,5 kW (150 PS)",
        "fuelType": "Benzin",
        "co2Emission": "132,0 g/km",
        "milage": "79.530 km",
        "emissionClass": "Euro6d-TEMP",
    },
    "price": {"amount": 29990, "currency": "EUR"},
}


def test_parse_german_formatted_values():
    """Decimal commas used to raise ValueError inside a bare float() and the
    value was silently dropped to None — losing CO2 forces the catalogue-match
    fallback for a listing that actually stated its emissions."""
    listing = _parse(GERMAN_SAMPLE, "https://suchen.mobile.de/auto-inserat/audi-a5/459632333.html")
    assert listing.power_kw == 110.5
    assert listing.co2_g_km == 132.0
    assert listing.mileage_km == 79530
    assert listing.fuel_type == "petrol"


@pytest.mark.parametrize(
    "raw,expected",
    [
        # Compound labels must not be shadowed by the single-fuel entries: both
        # of these used to resolve to "petrol" because "benzin"/"petrol" was
        # tested before "elektro"/"electric".
        ("Elektro/Benzin", "petrol"),
        ("Electric/Petrol", "petrol"),
        ("Elektro/Diesel", "diesel"),
        ("Electric/Diesel", "diesel"),
        ("Hybrid (Benzin/Elektro)", "petrol"),
        ("Hybrid (Diesel/Elektro)", "diesel"),
        # Single fuels, either language.
        ("Benzin", "petrol"),
        ("Petrol, E10-enabled", "petrol"),
        ("Diesel", "diesel"),
        ("Elektro", "electric"),
        ("Electric", "electric"),
        ("Autogas (LPG)", "petrol"),
        ("Erdgas (CNG)", "petrol"),
        # Unknown values return None rather than leaking raw source text into
        # ListingData.fuel_type, where it reaches the user-facing warning.
        ("Wasserstoff", None),
        ("Andere", None),
        ("", None),
        (None, None),
    ],
)
def test_normalise_fuel(raw, expected):
    assert _normalise_fuel(raw) == expected


@pytest.mark.parametrize(
    "url",
    [
        "https://suchen.mobile.de/auto-inserat/audi-a5/459632333.html",
        "https://suchen.mobile.de/fahrzeuge/details.html?id=459632333&dam=false",
        "https://suchen.mobile.de/fahrzeuge/details.html?id=459632333&lang=de",
    ],
)
def test_english_locale_is_pinned(url):
    """The actor gets an English URL whatever the user pasted."""
    result = _with_english_locale(url)
    assert parse_qs(urlparse(result).query)["lang"] == ["en"]
    # The listing id must survive, or the cache key and the actor both break.
    assert extract_mobile_de_id(result) == extract_mobile_de_id(url) == "459632333"


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("79,530 km", 79530),  # English thousands separator
        ("79.530 km", 79530),  # German thousands separator
        ("1.234.567 km", 1234567),  # multi-group — parse_number rejects this
        ("1,234,567 km", 1234567),
        ("250 km", 250),
        ("", None),
        (None, None),
        ("abc", None),
    ],
)
def test_parse_mileage_handles_any_number_of_separator_groups(raw, expected):
    """A mileage has no fractional part, so every separator is a thousands
    separator and deleting all of them is correct in any locale. Routing this
    through parse_number() instead looks tidier but silently returns None for
    anything with two separator groups."""
    assert _parse_mileage(raw) == expected


@pytest.mark.parametrize("value", [None, "", "n/a"])
def test_parse_survives_null_co2(value):
    """co2Emission is frequently present-but-null in the actor's output."""
    item = {
        "id": 1,
        "manufacturer": "Audi",
        "model": "A5",
        "subTitle": "x",
        "price": {"amount": 1000},
        "properties": {"co2Emission": value},
    }
    assert _parse(item, "https://suchen.mobile.de/x/1.html").co2_g_km is None


@pytest.mark.parametrize(
    "url,listing_id",
    [
        # The app/mobile-site share link the actor skipped outright.
        (MOBILE_SITE_SHARE_URL, "45688064542528"),
        ("https://www.mobile.de/fahrzeuge/details.html?id=459632333", "459632333"),
        ("https://suchen.mobile.de/auto-inserat/audi-a5/459632333.html", "459632333"),
        ("https://suchen.mobile.de/fahrzeuge/details.html?id=459632333&dam=false&lang=de", "459632333"),
    ],
)
def test_canonical_actor_url(url, listing_id):
    """Every listing URL variant reaches the actor in its whitelisted form."""
    assert _canonical_actor_url(url) == (
        f"https://suchen.mobile.de/fahrzeuge/details.html?id={listing_id}&lang=en"
    )


def test_canonical_actor_url_without_id_keeps_url():
    url = "https://suchen.mobile.de/fahrzeuge/search.html?ms=1900"
    result = _canonical_actor_url(url)
    assert result.startswith("https://suchen.mobile.de/fahrzeuge/search.html")
    assert parse_qs(urlparse(result).query)["lang"] == ["en"]
