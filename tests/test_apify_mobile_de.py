"""Unit tests for the Apify mobile.de fetcher — no network."""

from app.scraping.fetchers.apify_mobile_de import _parse, extract_mobile_de_id

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


def test_extract_id_none_when_absent():
    assert extract_mobile_de_id("https://suchen.mobile.de/fahrzeuge/search") is None
