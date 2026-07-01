"""Application entrypoint. Builds the FastAPI app and mounts feature routers."""

import sqlalchemy as sa
from fastapi import FastAPI

from app.db.models import Base
from app.db.session import engine
from app.calculate.router import router as calculate_router
from app.ppmv.router import router as ppmv_router
from app.scraping.router import router as scraping_router
from app.core.config import get_settings
from app.core.exceptions import register_exception_handlers

def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="carPPMV",
        version="0.1.0",
        debug=settings.debug,
    )

    @app.on_event("startup")
    async def _create_tables() -> None:
        async with engine.begin() as conn:
            # 1. Create any missing tables (idempotent)
            await conn.run_sync(Base.metadata.create_all)

            # 2. Add missing columns to existing tables
            await conn.execute(
                sa.text("""
                    ALTER TABLE catalogue
                    ADD COLUMN IF NOT EXISTS match_key VARCHAR(256) NOT NULL DEFAULT ''
                """)
            )
            # 3. Ensure unique constraint exists
            await conn.execute(
                sa.text("ALTER TABLE catalogue DROP CONSTRAINT IF EXISTS uq_catalogue_lookup_key")
            )
            await conn.execute(
                sa.text("ALTER TABLE catalogue ADD CONSTRAINT uq_catalogue_lookup_key UNIQUE (match_key)")
            )

    register_exception_handlers(app)

    app.include_router(ppmv_router, prefix="/ppmv", tags=["ppmv"])
    app.include_router(scraping_router, prefix="/scrape", tags=["scraping"])
    app.include_router(calculate_router, tags=["calculate"])

    return app

app = create_app()