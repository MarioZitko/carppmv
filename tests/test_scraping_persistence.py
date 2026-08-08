"""Integration tests for scraping observability persistence (ScrapeRun/Listing)
and the mobile.de cache-insert race fix.

Require a real DATABASE_URL — same requirement as other `integration`-marked
tests (see pyproject.toml). Skipped in normal CI-style runs:
    uv run pytest -m integration tests/test_scraping_persistence.py -v

Each test cleans up the rows it creates so repeated runs don't accumulate
data or collide on unique constraints.
"""

import asyncio
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import delete, select

from app.db.models import ApifyEvent, FuelType, Listing, ListingCache, ScrapeMode, ScrapeRun, ScrapeRunStatus, ScrapeSite
from app.db.session import AsyncSessionLocal
from app.scraping.mobile_de_service import get_mobile_de_listing
from app.scraping.persistence import finish_scrape_run, record_scrape_run
from app.scraping.schemas import ListingData


@pytest.mark.integration
@pytest.mark.asyncio
async def test_record_and_finish_scrape_run_success() -> None:
    listing = ListingData(
        source_url="https://example.test/listing/1",
        source_site="autoscout24",
        price_eur=15000.0,
        co2_g_km=110.0,
        fuel_type="hybrid",
        first_registration_date="2022-05-01",
        brand="Toyota",
        model="Corolla",
        power_kw=90.0,
    )

    async with AsyncSessionLocal() as db:
        run = await record_scrape_run(db, ScrapeSite.AUTOSCOUT24, ScrapeMode.ON_DEMAND)
        run_id = run.id
        try:
            await finish_scrape_run(db, run, status=ScrapeRunStatus.SUCCESS, listing=listing)

            refreshed = await db.get(ScrapeRun, run_id)
            assert refreshed is not None
            assert refreshed.status == ScrapeRunStatus.SUCCESS
            assert refreshed.listings_found == 1
            assert refreshed.finished_at is not None

            result = await db.execute(select(Listing).where(Listing.scrape_run_id == run_id))
            persisted = result.scalar_one()
            assert persisted.brand == "Toyota"
            assert persisted.model == "Corolla"
            assert persisted.fuel_type == FuelType.HYBRID  # expanded enum (was diesel/petrol only)
            assert persisted.price_eur == 15000.0
        finally:
            await db.execute(delete(Listing).where(Listing.scrape_run_id == run_id))
            await db.execute(delete(ScrapeRun).where(ScrapeRun.id == run_id))
            await db.commit()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_finish_scrape_run_failure_no_listing() -> None:
    async with AsyncSessionLocal() as db:
        run = await record_scrape_run(db, ScrapeSite.NJUSKALO, ScrapeMode.ON_DEMAND)
        run_id = run.id
        try:
            await finish_scrape_run(
                db, run, status=ScrapeRunStatus.FAILED, error_message="boom" * 1000
            )
            refreshed = await db.get(ScrapeRun, run_id)
            assert refreshed is not None
            assert refreshed.status == ScrapeRunStatus.FAILED
            assert refreshed.listings_failed == 1
            assert len(refreshed.error_message) <= 2048  # defensive truncation

            result = await db.execute(select(Listing).where(Listing.scrape_run_id == run_id))
            assert result.scalar_one_or_none() is None
        finally:
            await db.execute(delete(ScrapeRun).where(ScrapeRun.id == run_id))
            await db.commit()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_concurrent_mobile_de_cache_insert_does_not_raise() -> None:
    """Two concurrent requests for the same never-cached mobile.de listing
    must not surface an IntegrityError from the ListingCache unique
    constraint (see mobile_de_service.py's try/except IntegrityError fix) —
    exactly one cache row should exist afterward, and both calls should
    return successfully."""
    listing_id = uuid.uuid4().hex[:12]
    cache_key = f"mobile.de:{listing_id}"
    url = f"https://suchen.mobile.de/fahrzeuge/details.html?id={listing_id}"
    fake_listing = ListingData(source_url=url, source_site="mobile.de", price_eur=1000.0)

    async def _fake_fetch(_url: str) -> ListingData:
        # Simulate real Apify latency so both coroutines genuinely race past
        # the cache-miss SELECT before either commits its insert.
        await asyncio.sleep(0.05)
        return fake_listing

    async with AsyncSessionLocal() as db1, AsyncSessionLocal() as db2:
        try:
            with patch(
                "app.scraping.mobile_de_service.apify_mobile_de.fetch_listing",
                new=AsyncMock(side_effect=_fake_fetch),
            ), patch(
                "app.scraping.mobile_de_service.apify_budget_remaining",
                new=AsyncMock(return_value=True),
            ):
                results = await asyncio.gather(
                    get_mobile_de_listing(url, db1, ip_hash="test-hash-1"),
                    get_mobile_de_listing(url, db2, ip_hash="test-hash-2"),
                )
            assert all(r.price_eur == 1000.0 for r in results)

            async with AsyncSessionLocal() as verify_db:
                rows = (
                    await verify_db.execute(
                        select(ListingCache).where(ListingCache.cache_key == cache_key)
                    )
                ).scalars().all()
                assert len(rows) == 1
        finally:
            async with AsyncSessionLocal() as cleanup_db:
                await cleanup_db.execute(delete(ListingCache).where(ListingCache.cache_key == cache_key))
                await cleanup_db.execute(
                    delete(ApifyEvent).where(ApifyEvent.ip_hash.in_(["test-hash-1", "test-hash-2"]))
                )
                await cleanup_db.commit()
