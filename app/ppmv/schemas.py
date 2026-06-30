"""Request/response contracts for the PPMV feature.

These are the only PPMV types the outside world (router, tests, other
features) should depend on. engine.py and tables.py stay internal.
"""

from datetime import date
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, model_validator


class FuelType(str, Enum):
    DIESEL = "diesel"
    PETROL = "petrol"  # also covers LPG/CNG/other non-diesel per Tablice 3/6
    ELECTRIC = "electric"  # fully exempt: co2_g_km must be 0, final_ppmv = 0


class CO2Standard(str, Enum):
    NEDC = "NEDC"
    WLTP = "WLTP"


class PPMVRequest(BaseModel):
    price_eur: float = Field(gt=0, description="As-new or purchase price in EUR")
    co2_g_km: float = Field(ge=0, description="CO2 in g/km — 0 for electric; NEDC or WLTP otherwise")
    fuel_type: FuelType
    first_registration_date: date
    declaration_date: date
    # Plug-in hybrid: EAER city electric range in km; reduction % equals km value (capped at 100).
    # Note: use EAER *city* cycle, NOT WLTP combined range — the law cites
    # "Electric range (EAER city) [km]" explicitly.
    eaer_city_range_km: Optional[float] = Field(default=None, ge=0)
    # Total seat count (driver included). 8 seats (7+1) → −50%; 9+ seats (8+1) → −75%.
    seat_count: Optional[int] = Field(default=None, ge=1)
    is_camper: bool = False  # kamper: −85%
    # True when declaring a brand-new vehicle (not yet / simultaneously registered).
    # Pravilnik čl. 9: Tablica 1 depreciation only applies to USED vehicles;
    # new vehicles use factor = 1.0 (pay the full as-new PPMV).
    is_new_vehicle: bool = False

    @model_validator(mode="after")
    def _check_date_order(self) -> "PPMVRequest":
        if self.declaration_date < self.first_registration_date:
            raise ValueError("declaration_date cannot be before first_registration_date")
        return self

    @model_validator(mode="after")
    def _check_electric_co2(self) -> "PPMVRequest":
        if self.fuel_type == FuelType.ELECTRIC and self.co2_g_km != 0.0:
            raise ValueError("Electric vehicles must have co2_g_km == 0")
        if self.fuel_type != FuelType.ELECTRIC and self.co2_g_km <= 0.0:
            raise ValueError("Non-electric vehicles must have co2_g_km > 0")
        return self


class PPMVBreakdown(BaseModel):
    """Itemized result — mirrors the structure of the official tax decision,
    so a user can cross-check against carina.gov.hr output."""

    as_new_value_component: float
    as_new_eco_component: float
    as_new_total: float
    # Combined vehicle-type reduction multiplier applied to as_new_total before
    # depreciation. 1.0 = no reduction; 0.50 = 7+1 seats (−50%); 0.15 = camper (−85%); etc.
    vehicle_reduction_factor: float
    depreciation_percent: float
    months_old: int
    final_ppmv: float


class PPMVResponse(BaseModel):
    breakdown: PPMVBreakdown
    co2_standard_used: CO2Standard  # echoed back so the caller can verify the assumption