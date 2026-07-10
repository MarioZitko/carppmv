"""Abuse-protection guard in front of the mobile.de/Apify on-demand fetch.

Shared by every entry point that can receive a mobile.de URL — POST
/calculate (app/calculate/router.py) and POST /scrape/listing
(app/scraping/router.py) — so rate limiting, Turnstile verification, and IP
hashing are enforced identically regardless of which endpoint is hit. Order:
rate limit -> Turnstile -> cache/budget/Apify (delegated, unchanged).
"""

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import RateLimitExceeded, TurnstileVerificationFailed
from app.core.ip import client_ip_hash, resolve_client_ip
from app.core.limits import check_rate_limit
from app.core.turnstile import verify_turnstile
from app.scraping.mobile_de_service import get_mobile_de_listing, log_apify_event
from app.scraping.schemas import ListingData


async def guarded_mobile_de_listing(
    url: str,
    db: AsyncSession,
    request: Request,
    turnstile_token: str | None,
) -> ListingData:
    """Raises RateLimitExceeded (429), TurnstileVerificationFailed (403), or
    ApifyBudgetExceeded/ScrapingError (bubbled from get_mobile_de_listing)."""
    ip_hash = client_ip_hash(request)

    try:
        await check_rate_limit(db, ip_hash)
    except RateLimitExceeded:
        await log_apify_event(db, ip_hash, None, "apify", "rate_limited", 0.0)
        raise

    ip = resolve_client_ip(request)
    if not await verify_turnstile(turnstile_token, ip):
        await log_apify_event(db, ip_hash, None, "apify", "bot_rejected", 0.0)
        raise TurnstileVerificationFailed("Turnstile verification failed")

    return await get_mobile_de_listing(url, db, ip_hash=ip_hash)
