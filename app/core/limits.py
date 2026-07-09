"""Daily spend ceiling for the Apify on-demand scraping path (mobile.de)."""

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.models import ApifyEvent


async def apify_budget_remaining(db: AsyncSession) -> bool:
    """Returns True if today's Apify call count is under the daily budget."""
    settings = get_settings()
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    result = await db.execute(
        select(func.count()).where(
            ApifyEvent.source == "apify",
            ApifyEvent.created_at >= today_start,
        )
    )
    count = result.scalar() or 0
    return count < settings.daily_apify_budget_calls
