"""Scraping API router — mounted at /scrape in main.py."""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ScrapingError
from app.db.session import get_db_session
from app.scraping.mobile_de_guard import guarded_mobile_de_listing
from app.scraping.mobile_de_service import MOBILE_DE_SITE, ApifyBudgetExceeded
from app.scraping.persistence import record_scrape_outcome
from app.scraping.schemas import ListingData
from app.scraping.site_registry import EXTRACTORS, SITE_TO_SCRAPE_SITE, detect_site

router = APIRouter()


class ScrapeRequest(BaseModel):
    url: str
    turnstile_token: str | None = None


_SUPPORTED_DOMAINS = sorted([*EXTRACTORS.keys(), MOBILE_DE_SITE])


@router.post("/listing", response_model=ListingData)
async def scrape_listing(
    payload: ScrapeRequest,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
) -> ListingData:
    """Scrape a single car listing URL and return normalized ListingData.

    Supported domains: autobid.de, autoscout24.com, mobile.de, njuskalo.hr.
    mobile.de goes through the Apify actor, guarded by rate limiting,
    Turnstile, cache, and the daily budget cap (see
    app/scraping/mobile_de_guard.py); the others are fetched directly.
    Returns 422 for unrecognized domains, 503 if the daily budget is spent.
    """
    site = detect_site(payload.url)
    if not site:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Unsupported domain in URL '{payload.url}'. "
                f"Supported sites: {', '.join(_SUPPORTED_DOMAINS)}."
            ),
        )

    scrape_site = SITE_TO_SCRAPE_SITE.get(site)

    if site == MOBILE_DE_SITE:
        try:
            listing = await guarded_mobile_de_listing(payload.url, session, request, payload.turnstile_token)
        except ApifyBudgetExceeded as exc:
            if scrape_site is not None:
                await record_scrape_outcome(session, site=scrape_site, error_message=str(exc))
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        if scrape_site is not None:
            await record_scrape_outcome(session, site=scrape_site, listing=listing)
        return listing

    extractor = EXTRACTORS.get(site)
    if extractor is None:
        raise HTTPException(
            status_code=422,
            detail=f"No extractor implemented for site '{site}'.",
        )
    try:
        listing = await extractor.extract(payload.url)
    except ScrapingError as exc:
        if scrape_site is not None:
            await record_scrape_outcome(session, site=scrape_site, error_message=str(exc))
        raise
    if scrape_site is not None:
        await record_scrape_outcome(session, site=scrape_site, listing=listing)
    return listing
