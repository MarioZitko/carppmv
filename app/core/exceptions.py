"""Domain-level exceptions and their HTTP mapping.

Keeping these separate from feature code means engine.py (pure business logic)
never needs to know about HTTP — it raises these, and only the API layer
translates them into responses.
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class PPMVError(Exception):
    """Base class for all PPMV-domain errors."""


class InvalidCO2Value(PPMVError):
    """CO2 value falls outside every known eco bracket for the
    applicable standard (NEDC/WLTP) and fuel type."""


class InvalidPriceValue(PPMVError):
    """Price falls outside every known value bracket."""


class UnsupportedVehicleCategory(PPMVError):
    """Vehicle category/fuel/standard combination is recognized but not
    yet implemented (e.g. motorcycles, or a table not yet transcribed)."""


class ScrapingError(Exception):
    """Base class for all scraping-domain errors."""


class RateLimitExceeded(Exception):
    """Raised when a client IP has exceeded the per-hour/day request cap for
    the mobile.de on-demand scraping path."""


class TurnstileVerificationFailed(Exception):
    """Raised when Cloudflare Turnstile rejects (or is missing) the client's
    bot-check token."""


def register_exception_handlers(app: FastAPI) -> None:
    """Maps domain exceptions to consistent JSON error responses."""

    @app.exception_handler(PPMVError)
    async def handle_ppmv_error(request: Request, exc: PPMVError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.exception_handler(ScrapingError)
    async def handle_scraping_error(request: Request, exc: ScrapingError) -> JSONResponse:
        return JSONResponse(status_code=502, content={"detail": str(exc)})

    @app.exception_handler(RateLimitExceeded)
    async def handle_rate_limit_exceeded(request: Request, exc: RateLimitExceeded) -> JSONResponse:
        return JSONResponse(status_code=429, content={"detail": str(exc)})

    @app.exception_handler(TurnstileVerificationFailed)
    async def handle_turnstile_failed(request: Request, exc: TurnstileVerificationFailed) -> JSONResponse:
        return JSONResponse(status_code=403, content={"detail": str(exc)})
