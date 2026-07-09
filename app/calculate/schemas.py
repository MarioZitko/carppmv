"""Request/response contracts for the POST /calculate endpoint."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, HttpUrl

from app.catalogue.schemas import CatalogueCandidate


class CalculateRequest(BaseModel):
    url: HttpUrl


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
    co2_source: Literal["scraped", "catalogue", "manual_required"]
    confidence: Literal["high", "low"]
    warnings: list[str]
    debug: dict | None = None
    # Ranked catalogue rows the listing was matched against, so the user can
    # pick a different one (and its price/CO2) instead of the auto-picked row.
    match_status: Literal["auto_matched", "candidates", "no_match", "not_attempted"] = "not_attempted"
    candidates: list[CatalogueCandidate] = []
