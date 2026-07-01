"""Async SQLAlchemy engine and session factory.

Single engine per process, built from Settings.database_url (already
configured for asyncpg in config.py's default). Routers depend on
get_db_session via FastAPI's Depends() to get a request-scoped session.
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings

settings = get_settings()

engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    pool_size=20,          # allow up to 20 steady connections
    max_overflow=30,       # allow burst up to 50 total connections
    pool_timeout=30,       # wait up to 30 seconds for a connection
    pool_pre_ping=True,    # test connections before handing them out
)

AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency — yields a session, closes it after the request."""
    async with AsyncSessionLocal() as session:
        yield session