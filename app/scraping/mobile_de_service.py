"""Cache-first, budget-guarded mobile.de listing fetch via Apify.

Shared by every entry point that can receive a mobile.de URL — POST /calculate
(app/calculate/router.py) and POST /scrape/listing (app/scraping/router.py) —
so a listing is only ever paid for once per cache TTL window and the daily
Apify spend cap is enforced regardless of which endpoint is hit.
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import ScrapingError
from app.core.limits import apify_budget_remaining
from app.db.models import ApifyEvent, ListingCache
from app.scraping.fetchers import apify_mobile_de
from app.scraping.schemas import ListingData

MOBILE_DE_SITE = "mobile.de"


class ApifyBudgetExceeded(Exception):
    """Raised when the daily Apify call cap has been reached — callers
    should degrade to a manual-entry response instead of erroring."""


async def _log_apify_event(
    db: AsyncSession, listing_id: str | None, source: str, status: str, cost_usd: float
) -> None:
    db.add(
        ApifyEvent(
            site=MOBILE_DE_SITE,
            listing_id=listing_id,
            source=source,
            status=status,
            cost_usd=cost_usd,
            created_at=datetime.now(timezone.utc),
        )
    )
    await db.commit()


async def get_mobile_de_listing(url: str, db: AsyncSession) -> ListingData:
    """Cache-first, budget-guarded fetch of a mobile.de listing via Apify.

    Raises ApifyBudgetExceeded when the daily budget is exhausted, and
    ScrapingError (bubbled from the fetcher) on an actual fetch failure.
    """
    settings = get_settings()
    listing_id = apify_mobile_de.extract_mobile_de_id(url)
    cache_key = f"{MOBILE_DE_SITE}:{listing_id}" if listing_id else None

    cached: ListingCache | None = None
    if cache_key:
        result = await db.execute(select(ListingCache).where(ListingCache.cache_key == cache_key))
        cached = result.scalar_one_or_none()
        if cached is not None:
            ttl = timedelta(hours=settings.listing_cache_ttl_hours)
            if datetime.now(timezone.utc) - cached.fetched_at < ttl:
                await _log_apify_event(db, listing_id, "cache", "success", 0.0)
                return ListingData(**cached.payload)

    if not await apify_budget_remaining(db):
        await _log_apify_event(db, listing_id, "apify", "cap_reached", 0.0)
        raise ApifyBudgetExceeded(f"Daily Apify budget reached ({settings.daily_apify_budget_calls} calls)")

    try:
        listing = await apify_mobile_de.fetch_listing(url)
    except ScrapingError:
        await _log_apify_event(db, listing_id, "apify", "failed", 0.0)
        raise

    if cache_key:
        if cached is not None:
            cached.payload = listing.model_dump()
            cached.fetched_at = datetime.now(timezone.utc)
        else:
            db.add(
                ListingCache(
                    cache_key=cache_key,
                    payload=listing.model_dump(),
                    fetched_at=datetime.now(timezone.utc),
                )
            )
        await db.commit()

    await _log_apify_event(db, listing_id, "apify", "success", 0.0015)
    return listing
