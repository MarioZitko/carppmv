"""Locale-invariance tests for the scraping layer.

These lock in a property that was verified empirically but was never enforced:
a listing must parse to the same ListingData no matter which language variant
of the source site the user happened to copy the URL from.

The fixtures are real captures of the *same* listing served by different
locales:

  * autoscout24_listing_{de,hr}.json — the __NEXT_DATA__ listing object for one
    AutoScout24 listing as served by autoscout24.de and autoscout24.hr. It is
    also a hybrid (fuelCategory.raw == "3"), so it doubles as the regression
    test for hybrids aborting the PPMV calculation.
  * autobid_listing_{hr,de,en}.html — the og:title, icon parameter cards and
    price node for one autobid.de listing at /hr/artikal/, /de/artikel/ and
    /en/item/. The values are localized ("113.700 kilometrima" /
    "Kilometer" / "Kilometres"; "150 KS" / "PS" / "HP") which is exactly what
    the unit-anchored regexes have to survive.
"""

import json
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from app.scraping.extractors import autobid_de as AB, autoscout24 as AS
from app.scraping.parsing import parse_number
from app.scraping.site_registry import detect_site

FIXTURES = Path(__file__).parent / "fixtures"


def _as24(tag: str) -> dict:
    return json.loads((FIXTURES / f"autoscout24_listing_{tag}.json").read_text(encoding="utf-8"))


def _autobid(tag: str) -> BeautifulSoup:
    return BeautifulSoup(
        (FIXTURES / f"autobid_listing_{tag}.html").read_text(encoding="utf-8"), "lxml"
    )


# --------------------------------------------------------------------------
# AutoScout24
# --------------------------------------------------------------------------

AS24_PARSERS = {
    "price": AS._parse_price,
    "co2": AS._parse_co2,
    "fuel": AS._parse_fuel,
    "first_registration": AS._parse_first_registration,
    "mileage": AS._parse_mileage,
    "power_kw": AS._parse_power_kw,
    "variant": AS._parse_variant,
    "seat_count": AS._parse_seat_count,
    "brand": AS._parse_brand,
    "model": AS._parse_model_name,
    "vin": AS._parse_vin,
    "is_new": AS._parse_is_new,
}


def test_autoscout24_parses_identically_across_locales():
    """Every field the pipeline consumes must be identical on .de and .hr.

    The extractor reads only raw/enum keys for these; the translated `formatted`
    siblings and the title are deliberately not consumed.
    """
    de, hr = _as24("de"), _as24("hr")
    assert {name: fn(de) for name, fn in AS24_PARSERS.items()} == {
        name: fn(hr) for name, fn in AS24_PARSERS.items()
    }


def test_autoscout24_fixture_really_is_localized():
    """Guards the test above from passing vacuously — if a future re-capture
    accidentally saved the same locale twice, the assertion of equality would
    prove nothing. These are the fields that *should* differ."""
    de, hr = _as24("de"), _as24("hr")
    assert de["fuelCategory"]["formatted"] == "Elektro/Diesel"
    assert hr["fuelCategory"]["formatted"] == "Elektro/Dizel"
    assert de["transmissionType"] == "Automatik"
    assert hr["transmissionType"] == "Automatski mjenjač"


def test_autoscout24_hybrid_resolves_to_its_combustion_fuel():
    """Regression: fuelCategory.raw "3" (Electric/Diesel) was unmapped, so
    fuel_type came back None and calculate/router.py aborted the whole PPMV
    calculation — the user got no tax number at all."""
    listing = _as24("de")
    assert listing["fuelCategory"]["raw"] == "3"
    assert AS._parse_fuel(listing) == "diesel"


@pytest.mark.parametrize(
    "code,expected",
    [
        ("B", "petrol"),  # Gasoline
        ("D", "diesel"),
        ("E", "electric"),
        ("2", "petrol"),  # Electric/Gasoline hybrid
        ("3", "diesel"),  # Electric/Diesel hybrid
        ("L", "petrol"),  # LPG   — PPMV taxes these as non-diesel
        ("C", "petrol"),  # CNG
        ("M", "petrol"),  # Ethanol
        ("H", None),  # Hydrogen — no PPMV table; was wrongly mapped to hybrid
        ("O", None),  # Others
    ],
)
def test_autoscout24_fuel_code_table(code, expected):
    """The full fuelCategory.raw code space, enumerated off the live site."""
    assert AS._parse_fuel({"fuelCategory": {"raw": code}}) == expected


@pytest.mark.parametrize(
    "offer_type,expected", [("N", True), ("U", False), ("", None), ("X", None)]
)
def test_autoscout24_new_used_flag(offer_type, expected):
    """Depreciation applies only to used vehicles, so a new car read as used is
    under-taxed. offerType carries this and used to be ignored entirely."""
    assert AS._parse_is_new({"offerType": offer_type}) is expected


def test_autoscout24_is_new_absent():
    assert AS._parse_is_new({}) is None


# --------------------------------------------------------------------------
# autobid.de
# --------------------------------------------------------------------------


def test_autobid_parses_identically_across_language_paths():
    """/hr/artikal/, /de/artikel/ and /en/item/ are the same listing. autobid.de
    picks language purely from the URL path segment (its Accept-Language header
    is ignored), so all three must yield the same numbers."""
    results = []
    for tag in ("hr", "de", "en"):
        soup = _autobid(tag)
        specs = AB._parse_spec_table(soup)
        specs.update(AB._parse_car_parameter_cards(soup))
        results.append(
            {
                "price": AB._extract_price(soup),
                "first_registration": AB._normalise_first_reg(specs["first registration"]),
                "mileage": AB._extract_mileage(specs["mileage"]),
                "power_kw": AB._extract_power_kw(specs["power"]),
            }
        )

    assert results[0] == results[1] == results[2]
    assert results[0] == {
        "price": 18500.0,
        "first_registration": "06.2022",
        "mileage": 113700,
        "power_kw": 110.0,
    }


def test_autobid_fixture_really_is_localized():
    """Same vacuous-pass guard as for AutoScout24 — the units are translated
    even though the parsed numbers are not."""
    values = {}
    for tag in ("hr", "de", "en"):
        specs = AB._parse_car_parameter_cards(_autobid(tag))
        values[tag] = (specs["mileage"], specs["power"])

    assert values["hr"] == ("113.700 kilometrima", "110 KW / 150 KS")
    assert values["de"] == ("113.700 Kilometer", "110 KW / 150 PS")
    assert values["en"] == ("113.700 Kilometres", "110 KW / 150 HP")


# --------------------------------------------------------------------------
# Shared number parsing
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        ("12.500,00", 12500.0),  # German/Croatian
        ("12,500.00", 12500.0),  # English
        ("1,234.56", 1234.56),  # became 1.23456 under the old German-only parser
        ("18.500", 18500.0),
        ("113.700", 113700.0),
        ("132,0", 132.0),  # bare float() raised ValueError and dropped this
        ("110,5", 110.5),
        ("79,530", 79530.0),
        ("132", 132.0),
        ("", None),
        (None, None),
        ("n/a", None),
    ],
)
def test_parse_number_is_locale_agnostic(text, expected):
    assert parse_number(text) == expected


# --------------------------------------------------------------------------
# URL tolerance
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url,site",
    [
        ("https://www.autoscout24.de/angebote/bmw-318d-cat_x-abc", "autoscout24"),
        ("https://www.autoscout24.com/offers/bmw-318d-cat_x-abc", "autoscout24"),
        ("https://www.autoscout24.hr/ponude/bmw-318d-cat_x-abc", "autoscout24"),
        ("https://www.autoscout24.it/annunci/bmw-318d-cat_x-abc", "autoscout24"),
        ("https://autobid.de/hr/artikal/bmw-318d-touring-3543882", "autobid.de"),
        ("https://autobid.de/de/artikel/bmw-318d-touring-3543882", "autobid.de"),
        ("https://autobid.de/en/item/bmw-318d-touring-3543882", "autobid.de"),
        ("https://suchen.mobile.de/auto-inserat/audi-a5/459632333.html", "mobile.de"),
        ("https://suchen.mobile.de/fahrzeuge/details.html?id=459632333", "mobile.de"),
        ("https://www.njuskalo.hr/auti/bmw-318d-oglas-12345", "njuskalo"),
    ],
)
def test_detect_site_accepts_every_language_variant(url, site):
    """Localized domains and path segments must all route to the same extractor."""
    assert detect_site(url) == site
