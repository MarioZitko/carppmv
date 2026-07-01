"""Async SQLAlchemy engine and session factory.

Single engine per process, built from Settings.database_url (already
configured for asyncpg in config.py's default). Routers depend on
get_db_session via FastAPI's Depends() to get a request-scoped session.
"""

from collections.abc import AsyncGenerator

from sqlalchemy.pool import NullPool
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings

settings = get_settings()

engine = create_async_engine(
    settings.database_url,
    echo=False,
    poolclass=NullPool,  # <-- no pooling = no timeout errors
)

AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency — yields a session, closes it after the request."""
    async with AsyncSessionLocal() as session:
        yield session