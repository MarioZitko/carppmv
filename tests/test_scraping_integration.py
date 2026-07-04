"""Integration tests for on-demand scraping extractors.

These tests hit real websites — they are SKIPPED in normal CI runs.
Run them explicitly:
    uv run pytest -m integration tests/test_scraping_integration.py -v

URLs below are hardcoded to stable/cheap listings. Car listings expire; if a URL
returns 404 or the extractor raises ScrapingError with a 4xx status, the test skips
rather than fails — replace the URL constant with a current listing and re-run.

No mocking — these tests exercise real network + HTML parsing.
"""

import pytest
import pytest_asyncio

from app.scraping.extractors.autobid_de import AutobidDeExtractor
from app.scraping.extractors.autoscout24 import AutoScout24Extractor, _parse_model_name
from app.scraping.extractors.mobile_de import MobileDeExtractor
from app.scraping.extractors.njuskalo import NjuskaloExtractor
from app.scraping.schemas import ListingData
from app.core.exceptions import ScrapingError


# ---------------------------------------------------------------------------
# autoscout24 model-badge assembly (pure — no network)
# ---------------------------------------------------------------------------

def test_autoscout24_model_suffix_appends_engine_letter():
    # AS24 gives a bare model number + the engine letter as the first token of
    # modelVersionInput; the two must combine into the catalogue-style badge.
    listing = {"model": "120", "modelVersionInput": "i Advantage|NAV|SHZG|LED"}
    assert _parse_model_name(listing) == "120i"


def test_autoscout24_model_suffix_folds_xdrive_prefix_to_fuel_letter():
    # A leading 'x' is xDrive (AWD), not the engine code: "xd" must fold to "d"
    # so the model is "420d" (a real catalogue badge), not "420xd" (which no row
    # matches and which trips the model-mismatch penalty).
    listing = {"model": "420", "modelVersionInput": "xd Luxury Line|HUD|HIFI"}
    assert _parse_model_name(listing) == "420d"

# ---------------------------------------------------------------------------
# Hardcoded listing URLs — replace when listings expire.
# Format reminder:
#   autobid.de:   https://www.autobid.de/de/auktion/{slug}-{id}
#   njuskalo.hr:  https://www.njuskalo.hr/osobni-automobili/{slug}-oglas{id}
#   autoscout24:  https://www.autoscout24.com/offers/{make}-{model}-{spec}-{uuid}
#   mobile.de:    https://suchen.mobile.de/fahrzeuge/details.html?id={id}
# ---------------------------------------------------------------------------

_AUTOBID_URL = (
    "https://autobid.de/hr/artikal/audi-a5-sportback-40-tdi-quattro-s-tronic-s-line-3464608"
)
_NJUSKALO_URL = (
    "https://www.njuskalo.hr/auti/audi-a3-2.0-tdi-sport-automatik-oglas-50586146"
)
_AUTOSCOUT24_URL = (
    "https://www.autoscout24.de/angebote/audi-a4-35-tfsi-navi-pdc-sihz-s-tronic-benzin-schwarz-cat_ma9mo1626-4e26643e-0e3f-48f3-8ab4-3d4640516761"
    "?source=autocatalog_carousel&position=3"
)
_MOBILE_DE_URL = (
    "https://suchen.mobile.de/auto-inserat/"
    "audi-a5-coupe-3-0d-sport-s-line-18-b-o-standhz-nav-x-bebra/456779908.html"
)


def _skip_if_gone(exc: ScrapingError) -> None:
    """If the site returned 4xx (listing gone/expired), skip instead of fail."""
    msg = str(exc)
    for code in ("404", "410", "403", "400", "returned 4"):
        if code in msg:
            pytest.skip(f"Listing URL gone/expired: {exc}")
    raise exc


# ---------------------------------------------------------------------------
# autobid.de
# ---------------------------------------------------------------------------

@pytest.mark.integration
@pytest.mark.asyncio
async def test_autobid_de_extractor() -> None:
    extractor = AutobidDeExtractor()
    try:
        result = await extractor.extract(_AUTOBID_URL)
    except ScrapingError as exc:
        _skip_if_gone(exc)
        raise

    assert isinstance(result, ListingData)
    assert result.source_site == "autobid.de"
    assert result.source_url == _AUTOBID_URL
    # CO2 is never available pre-login on autobid.de
    assert result.co2_g_km is None, "autobid.de must never return CO2 (not exposed pre-login)"

    assert result.price_eur is not None, "Expected price_eur from autobid.de listing"
    assert result.price_eur > 0

    assert result.brand is not None, "Expected brand from autobid.de listing"
    assert result.brand.lower() == "audi", f"Expected brand='Audi', got {result.brand!r}"
    assert result.model is not None, "Expected model from autobid.de listing"
    assert "a5" in result.model.lower(), f"Expected model to contain 'A5', got {result.model!r}"

    # mileage / power are in the spec table; present when the page renders them in
    # parseable HTML, may be None when hidden behind login on this auction site.
    if result.mileage_km is not None:
        assert result.mileage_km > 0
    if result.power_kw is not None:
        assert result.power_kw > 0
    if result.seat_count is not None:
        assert 1 <= result.seat_count <= 20


# ---------------------------------------------------------------------------
# njuskalo.hr
# ---------------------------------------------------------------------------

@pytest.mark.integration
@pytest.mark.asyncio
async def test_njuskalo_extractor() -> None:
    extractor = NjuskaloExtractor()
    try:
        result = await extractor.extract(_NJUSKALO_URL)
    except ScrapingError as exc:
        _skip_if_gone(exc)
        raise

    assert isinstance(result, ListingData)
    assert result.source_site == "njuskalo"
    assert result.source_url == _NJUSKALO_URL
    assert result.price_eur is not None, "Expected price_eur from njuskalo listing"
    assert result.price_eur > 0
    # Price should be in EUR (already converted from HRK if needed)
    assert result.price_eur < 500_000, "Unexpectedly large price — possible HRK→EUR conversion error"
    if result.power_kw is not None:
        assert result.power_kw > 0
    if result.seat_count is not None:
        assert 1 <= result.seat_count <= 20


# ---------------------------------------------------------------------------
# autoscout24.com
# ---------------------------------------------------------------------------

@pytest.mark.integration
@pytest.mark.asyncio
async def test_autoscout24_extractor() -> None:
    extractor = AutoScout24Extractor()
    try:
        result = await extractor.extract(_AUTOSCOUT24_URL)
    except ScrapingError as exc:
        _skip_if_gone(exc)
        raise

    assert isinstance(result, ListingData)
    assert result.source_site == "autoscout24"
    assert result.source_url == _AUTOSCOUT24_URL
    assert result.price_eur is not None, "Expected price_eur from AutoScout24 listing"
    assert result.price_eur > 0
    # AutoScout24 typically has CO2 and power — warn if missing but don't hard-fail
    # (not every listing fills every field)
    if result.power_kw is not None:
        assert result.power_kw > 0
    if result.co2_g_km is not None:
        assert result.co2_g_km > 0


# ---------------------------------------------------------------------------
# mobile.de
# ---------------------------------------------------------------------------

@pytest.mark.integration
@pytest.mark.asyncio
async def test_mobile_de_extractor() -> None:
    extractor = MobileDeExtractor()
    try:
        result = await extractor.extract(_MOBILE_DE_URL)
    except ScrapingError as exc:
        _skip_if_gone(exc)
        raise

    assert isinstance(result, ListingData)
    assert result.source_site == "mobile.de"
    assert result.source_url == _MOBILE_DE_URL
    assert result.price_eur is not None, "Expected price_eur from mobile.de listing"
    assert result.price_eur > 0
    if result.power_kw is not None:
        assert result.power_kw > 0
    if result.seat_count is not None:
        assert 1 <= result.seat_count <= 20
