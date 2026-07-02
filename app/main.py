"""Application entrypoint. Builds the FastAPI app and mounts feature routers."""

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
        # Creates any tables that don't exist yet, using the column/constraint
        # definitions in db/models.py directly. Does not alter existing tables —
        # schema changes to existing tables need an explicit migration.
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    register_exception_handlers(app)

    app.include_router(ppmv_router, prefix="/ppmv", tags=["ppmv"])
    app.include_router(scraping_router, prefix="/scrape", tags=["scraping"])
    app.include_router(calculate_router, tags=["calculate"])

    return app

app = create_app()