"""Daily spend ceiling and per-IP rate limiting for the Apify on-demand
scraping path (mobile.de)."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import RateLimitExceeded
from app.db.models import ApifyEvent


async def apify_budget_remaining(db: AsyncSession) -> bool:
    """Returns True if today's Apify call count is under the daily budget."""
    settings = get_settings()
    today_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    result = await db.execute(
        select(func.count()).where(
            ApifyEvent.source == "apify",
            ApifyEvent.created_at >= today_start,
        )
    )
    count = result.scalar() or 0
    return count < settings.daily_apify_budget_calls


async def check_rate_limit(db: AsyncSession, ip_hash: str) -> None:
    """Raises RateLimitExceeded if this IP has made too many mobile.de
    requests (any outcome — cache hit, Apify call, or degrade) in the last
    hour or day. Counts all ApifyEvent rows for the IP, not just paid Apify
    calls — this throttles request volume, separate from apify_budget_remaining
    which caps spend."""
    settings = get_settings()
    now = datetime.now(UTC)

    hour_count = await db.scalar(
        select(func.count()).where(
            ApifyEvent.ip_hash == ip_hash,
            ApifyEvent.created_at >= now - timedelta(hours=1),
        )
    )
    if (hour_count or 0) >= settings.rate_limit_per_ip_hour:
        raise RateLimitExceeded(
            f"Rate limit exceeded: {settings.rate_limit_per_ip_hour} requests/hour"
        )

    day_count = await db.scalar(
        select(func.count()).where(
            ApifyEvent.ip_hash == ip_hash,
            ApifyEvent.created_at >= now - timedelta(days=1),
        )
    )
    if (day_count or 0) >= settings.rate_limit_per_ip_day:
        raise RateLimitExceeded(
            f"Rate limit exceeded: {settings.rate_limit_per_ip_day} requests/day"
        )
