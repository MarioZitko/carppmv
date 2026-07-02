"""Request/response contracts for catalogue search & matching results.

Shared between the /calculate flow (candidates surfaced alongside a scraped
listing) and the standalone /catalogue/search flow (no listing URL at all —
the user picks brand/model/variant directly from the database).
"""

from datetime import date

from pydantic import BaseModel


class CatalogueCandidate(BaseModel):
    """One ranked catalogue row, with enough info for a human to pick it."""

    catalogue_id: int | None
    brand: str
    model: str
    variant: str
    price_eur: float
    co2_g_km: float | None
    co2_standard: str | None
    fuel_type: str | None
    power_kw: float | None
    valid_from: date | None
    score: float


class CatalogueSearchRequest(BaseModel):
    brand: str
    model: str | None = None
    variant: str | None = None
    fuel_type: str | None = None
    power_kw: float | None = None


class CatalogueSearchResponse(BaseModel):
    status: str  # "auto_matched" | "candidates" | "no_match"
    matched: CatalogueCandidate | None
    candidates: list[CatalogueCandidate]
