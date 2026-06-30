"""Application entrypoint. Builds the FastAPI app and mounts feature routers."""

from fastapi import FastAPI

from app.ppmv.router import router as ppmv_router
from app.scraping.router import router as scraping_router
from app.core.config import get_settings
from app.core.exceptions import register_exception_handlers


def create_app() -> FastAPI:
    """Factory function so tests can spin up isolated app instances."""
    settings = get_settings()

    app = FastAPI(
        title="carPPMV",
        version="0.1.0",
        debug=settings.debug,
    )

    register_exception_handlers(app)

    # Each feature owns its own router; main.py only wires them together.
    app.include_router(ppmv_router, prefix="/ppmv", tags=["ppmv"])
    app.include_router(scraping_router, prefix="/scrape", tags=["scraping"])

    return app


app = create_app()