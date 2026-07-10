"""Scraping API router — mounted at /scrape in main.py."""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session
from app.scraping.engines import SITE_ENGINE_MAP
from app.scraping.extractors.autobid_de import AutobidDeExtractor
from app.scraping.extractors.autoscout24 import AutoScout24Extractor
from app.scraping.extractors.njuskalo import NjuskaloExtractor
from app.scraping.mobile_de_guard import guarded_mobile_de_listing
from app.scraping.mobile_de_service import MOBILE_DE_SITE, ApifyBudgetExceeded
from app.scraping.schemas import ListingData

router = APIRouter()


class ScrapeRequest(BaseModel):
    url: str
    turnstile_token: str | None = None


_EXTRACTORS = {
    "autobid.de": AutobidDeExtractor(),
    "autoscout24": AutoScout24Extractor(),
    "njuskalo": NjuskaloExtractor(),
}

_SUPPORTED_DOMAINS = sorted([*_EXTRACTORS.keys(), MOBILE_DE_SITE])


def _detect_site(url: str) -> str:
    for site in SITE_ENGINE_MAP:
        if site in url:
            return site
    return ""


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
    site = _detect_site(payload.url)
    if not site:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Unsupported domain in URL '{payload.url}'. "
                f"Supported sites: {', '.join(_SUPPORTED_DOMAINS)}."
            ),
        )

    if site == MOBILE_DE_SITE:
        try:
            return await guarded_mobile_de_listing(payload.url, session, request, payload.turnstile_token)
        except ApifyBudgetExceeded as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    extractor = _EXTRACTORS.get(site)
    if extractor is None:
        raise HTTPException(
            status_code=422,
            detail=f"No extractor implemented for site '{site}'.",
        )
    return await extractor.extract(payload.url)
