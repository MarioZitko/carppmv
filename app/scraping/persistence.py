"""Observability persistence for scraper executions — ScrapeRun + Listing.

Shared by every entry point that produces a ListingData (app/calculate/router.py
and app/scraping/router.py), so a scrape's outcome is recorded the same way
regardless of which endpoint triggered it.

This is purely observability, not the product path: any failure writing
these rows must never break the actual /calculate or /scrape/listing
response. Callers should wrap calls to finish_scrape_run in the same
try/except-and-log pattern already used elsewhere in this codebase for
non-critical side effects (see mobile_de_service.py's cache-write handling).
"""

import logging
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import FuelType, Listing, ScrapeMode, ScrapeRun, ScrapeRunStatus, ScrapeSite
from app.scraping.parsing import parse_listing_date
from app.scraping.schemas import ListingData

log = logging.getLogger(__name__)

# ListingData.fuel_type is already normalized to these canonical strings by
# every extractor's own site-specific fuel map (see e.g.
# extractors/autoscout24.py::_FUEL_MAP) before it ever reaches this module —
# so persistence just needs to resolve the string to the DB enum, not
# re-derive it from raw site text.
_LISTING_FUEL_TO_DB: dict[str, FuelType] = {
    "diesel": FuelType.DIESEL,
    "petrol": FuelType.PETROL,
    "electric": FuelType.ELECTRIC,
    "hybrid": FuelType.HYBRID,
    "lpg": FuelType.LPG,
    "cng": FuelType.CNG,
}


async def record_scrape_run(db: AsyncSession, site: ScrapeSite, mode: ScrapeMode) -> ScrapeRun:
    """Creates and flushes a ScrapeRun row (status=RUNNING) before the fetch
    starts, so its id is available to link a Listing row once the fetch
    finishes. Caller commits alongside finish_scrape_run — a lone flush here
    is enough to get the id without prematurely committing a run that might
    still fail."""
    run = ScrapeRun(site=site, mode=mode, status=ScrapeRunStatus.RUNNING)
    db.add(run)
    await db.flush()
    return run


async def finish_scrape_run(
    db: AsyncSession,
    run: ScrapeRun,
    *,
    status: ScrapeRunStatus,
    listing: ListingData | None = None,
    error_message: str | None = None,
    estimated_cost_usd: float | None = None,
) -> None:
    """Finalizes a ScrapeRun and, on success with a listing, persists a
    linked Listing row. Commits once at the end.

    error_message is truncated defensively — Listing/ScrapeRun error columns
    are bounded varchars and an unhandled scraper exception's str() can be
    arbitrarily long.
    """
    run.finished_at = datetime.now(timezone.utc)
    run.status = status
    run.estimated_cost_usd = estimated_cost_usd
    if error_message:
        run.error_message = error_message[:2048]

    if status == ScrapeRunStatus.SUCCESS and listing is not None:
        run.listings_found = 1
        db.add(
            Listing(
                scrape_run_id=run.id,
                site=run.site,
                source_url=listing.source_url,
                external_id=None,
                brand=listing.brand,
                model=listing.model,
                variant=listing.variant,
                price_eur=listing.price_eur,
                co2_g_km=listing.co2_g_km,
                fuel_type=_LISTING_FUEL_TO_DB.get((listing.fuel_type or "").strip().lower()),
                first_registration_date=parse_listing_date(listing.first_registration_date),
                mileage_km=listing.mileage_km,
                power_kw=int(listing.power_kw) if listing.power_kw is not None else None,
            )
        )
    else:
        run.listings_failed = 1

    await db.commit()


async def record_scrape_outcome(
    db: AsyncSession,
    *,
    site: ScrapeSite,
    mode: ScrapeMode = ScrapeMode.ON_DEMAND,
    listing: ListingData | None = None,
    error_message: str | None = None,
    estimated_cost_usd: float | None = None,
) -> None:
    """Convenience wrapper for the common case: a scrape already ran (outside
    this module) and the caller just wants to record its outcome after the
    fact, rather than bracketing the fetch with record_scrape_run/
    finish_scrape_run. Never raises — a failure here is logged and swallowed,
    since this is observability, not the product path."""
    try:
        run = await record_scrape_run(db, site, mode)
        status = ScrapeRunStatus.SUCCESS if listing is not None else ScrapeRunStatus.FAILED
        await finish_scrape_run(
            db,
            run,
            status=status,
            listing=listing,
            error_message=error_message,
            estimated_cost_usd=estimated_cost_usd,
        )
    except Exception:
        log.exception("Failed to record scrape outcome for site=%s", site)
        await db.rollback()
