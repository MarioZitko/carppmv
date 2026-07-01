"""Request/response contracts for the POST /calculate endpoint."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, HttpUrl


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


class CalculateResponse(BaseModel):
    ppmv_eur: float | None
    parsed: ParsedFields
    co2_source: Literal["scraped", "catalogue", "manual_required"]
    confidence: Literal["high", "low"]
    warnings: list[str]
    debug: dict | None = None
