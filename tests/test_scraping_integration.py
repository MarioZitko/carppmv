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
from app.scraping.extractors.autoscout24 import AutoScout24Extractor
from app.scraping.extractors.mobile_de import MobileDeExtractor
from app.scraping.extractors.njuskalo import NjuskaloExtractor
from app.scraping.schemas import ListingData
from app.core.exceptions import ScrapingError

# ---------------------------------------------------------------------------
# Hardcoded listing URLs — replace when listings expire.
# Format reminder:
#   autobid.de:   https://www.autobid.de/de/auktion/{slug}-{id}
#   njuskalo.hr:  https://www.njuskalo.hr/osobni-automobili/{slug}-oglas{id}
#   autoscout24:  https://www.autoscout24.com/offers/{make}-{model}-{spec}-{uuid}
#   mobile.de:    https://suchen.mobile.de/fahrzeuge/details.html?id={id}
# ---------------------------------------------------------------------------

_AUTOBID_URL = (
    "https://www.autobid.de/de/auktionen"  # TODO: replace with a specific vehicle detail page
)
_NJUSKALO_URL = (
    "https://www.njuskalo.hr/osobni-automobili/volkswagen-golf-2020-dizel-oglas58713227"
)
_AUTOSCOUT24_URL = (
    "https://www.autoscout24.com/offers/"
    "volkswagen-golf-tdi-2020-grey-23467897-fb38fd11-8e6b-4f5f-be69-a4abd00c7b3e"  # TODO: replace with valid listing UUID
)
_MOBILE_DE_URL = (
    "https://suchen.mobile.de/fahrzeuge/details.html?id=367890123"  # TODO: replace with valid listing ID
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
    # At minimum we expect title or price to have been extracted
    assert result.price_eur is not None or result.title is not None, (
        "Expected at least price_eur or title from autobid.de listing"
    )
    if result.price_eur is not None:
        assert result.price_eur > 0
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
