"""Request/response contracts for the POST /calculate endpoint."""

from typing import Literal

from pydantic import BaseModel, HttpUrl

from app.catalogue.schemas import CatalogueCandidate

# Named so the router can annotate its own working state with the same types
# the response is validated against — otherwise those locals are plain `str`
# and every response construction needs a type: ignore to get past the check.
Co2Source = Literal["scraped", "catalogue", "manual_required"]
Confidence = Literal["high", "low"]
MatchStatusStr = Literal["auto_matched", "candidates", "no_match", "not_attempted"]


class CalculateRequest(BaseModel):
    url: HttpUrl
    # Cloudflare Turnstile token from the frontend widget — verified only for
    # the mobile.de/Apify path (app/scraping/mobile_de_guard.py). None when
    # Turnstile is unconfigured (dev) or the request isn't mobile.de.
    turnstile_token: str | None = None


class ParsedFields(BaseModel):
    brand: str | None = None
    model: str | None = None
    variant: str | None = None
    fuel_type: str | None = None
    first_registration: str | None = None
    power_kw: float | None = None
    co2_g_km: float | None = None
    price_eur: float | None = None
    seat_count: int | None = None
    is_new: bool = False
    vin: str | None = None


class CalculateResponse(BaseModel):
    ppmv_eur: float | None
    parsed: ParsedFields
    co2_source: Co2Source
    confidence: Confidence
    warnings: list[str]
    debug: dict | None = None
    # Ranked catalogue rows the listing was matched against, so the user can
    # pick a different one (and its price/CO2) instead of the auto-picked row.
    match_status: MatchStatusStr = "not_attempted"
    candidates: list[CatalogueCandidate] = []
