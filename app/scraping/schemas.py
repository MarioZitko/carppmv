"""The normalized listing contract — the shared seam between PPMV (single-URL
mode) and the future Isplativost feature (bulk sweeps). Every site extractor
must produce one of these regardless of source quirks.
"""

from pydantic import BaseModel


class ListingData(BaseModel):
    source_url: str
    source_site: str  # "mobile.de" | "njuskalo" | "autoscout24" | "autobid.de"
    price_eur: float | None = None
    co2_g_km: float | None = None  # often unavailable — PPMV must handle None, never guess
    fuel_type: str | None = None
    first_registration_date: str | None = None  # raw string; caller parses/validates
    title: str | None = None
    mileage_km: int | None = None
    power_kw: float | None = None
    variant: str | None = None
    seat_count: int | None = None