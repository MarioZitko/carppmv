"""Application entrypoint. Builds the FastAPI app and mounts feature routers."""

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.calculate.router import router as calculate_router
from app.catalogue.router import router as catalogue_router
from app.core.config import get_settings
from app.core.exceptions import register_exception_handlers
from app.db.models import Base
from app.db.session import engine
from app.ppmv.router import router as ppmv_router
from app.scraping.router import router as scraping_router

log = logging.getLogger(__name__)


def create_app() -> FastAPI:
    settings = get_settings()

    if not settings.debug and settings.ip_hash_salt == "change-me":
        # Every client-IP hash (rate limiting, ApifyEvent accounting) uses
        # this salt — the checked-in default is public, so leaving it unset
        # in prod makes raw IPs recoverable from the hashes. Not a hard
        # fail: a misconfigured salt shouldn't take the whole API down.
        log.warning(
            "IP_HASH_SALT is unset (using the insecure default 'change-me') "
            "while DEBUG=false. Set a real secret in production — see "
            "app/core/ip.py."
        )

    app = FastAPI(
        title="carPPMV",
        version="0.1.0",
        debug=settings.debug,
    )

    @app.on_event("startup")
    async def _create_tables() -> None:
        # Creates any tables that don't exist yet, using the column/constraint
        # definitions in db/models.py directly. Does not alter existing tables —
        # schema changes to existing tables need an explicit migration.
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[origin.strip() for origin in settings.cors_allow_origins.split(",") if origin.strip()],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_exception_handlers(app)

    app.include_router(ppmv_router, prefix="/ppmv", tags=["ppmv"])
    app.include_router(scraping_router, prefix="/scrape", tags=["scraping"])
    app.include_router(calculate_router, tags=["calculate"])
    app.include_router(catalogue_router, prefix="/catalogue", tags=["catalogue"])

    return app

app = create_app()
