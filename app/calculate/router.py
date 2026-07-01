"""POST /calculate — URL in, PPMV out.

Pipeline:
  1. Detect site from URL domain → pick extractor
  2. Run extractor → ListingData
  3. If co2_g_km missing → catalogue matcher → fill or flag manual_required
  4. Run PPMV engine
  5. Return CalculateResponse
"""

import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.calculate.schemas import CalculateRequest, CalculateResponse, ParsedFields
from app.catalogue.matching import MatchStatus, find_match
from app.core.config import get_settings
from app.db.session import get_db_session
from app.ppmv.engine import calculate_ppmv
from app.ppmv.schemas import FuelType
from app.scraping.engines import SITE_ENGINE_MAP
from app.scraping.extractors.autobid_de import AutobidDeExtractor
from app.scraping.extractors.autoscout24 import AutoScout24Extractor
from app.scraping.extractors.njuskalo import NjuskaloExtractor

log = logging.getLogger(__name__)

router = APIRouter()

_EXTRACTORS = {
    "autobid.de": AutobidDeExtractor(),
    "autoscout24": AutoScout24Extractor(),
    "njuskalo": NjuskaloExtractor(),
}

_UNSUPPORTED_SITES = {"mobile.de"}

_FUEL_MAP: dict[str, FuelType] = {
    "diesel": FuelType.DIESEL,
    "dizel": FuelType.DIESEL,
    "petrol": FuelType.PETROL,
    "benzin": FuelType.PETROL,
    "gasoline": FuelType.PETROL,
    "electric": FuelType.ELECTRIC,
    "elektrisch": FuelType.ELECTRIC,
    "elektro": FuelType.ELECTRIC,
}


def _detect_site(url: str) -> str:
    for site in SITE_ENGINE_MAP:
        if site in url:
            return site
    return ""


def _parse_fuel(raw: str | None) -> FuelType | None:
    if not raw:
        return None
    return _FUEL_MAP.get(raw.strip().lower())


def _parse_date(raw: str | None) -> date | None:
    if not raw:
        return None
    # Support YYYY-MM-DD (ISO) and DD.MM.YYYY (European)
    for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            from datetime import datetime
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


@router.post("/calculate", response_model=CalculateResponse)
async def calculate(
    body: CalculateRequest,
    session: AsyncSession = Depends(get_db_session),
) -> CalculateResponse:
    url = str(body.url)
    settings = get_settings()

    site = _detect_site(url)

    if site in _UNSUPPORTED_SITES:
        raise HTTPException(status_code=400, detail=f"{site} is not supported")

    if not site or site not in _EXTRACTORS:
        raise HTTPException(
            status_code=422,
            detail=[{"loc": ["body", "url"], "msg": f"Unrecognized domain: {url}", "type": "value_error"}],
        )

    extractor = _EXTRACTORS[site]
    listing = await extractor.extract(url)

    # Build ParsedFields from listing.
    # first_registration: ListingData uses first_registration_date (raw string)
    parsed = ParsedFields(
        brand=listing.brand,
        model=listing.model,
        variant=listing.variant,
        fuel_type=listing.fuel_type,
        first_registration=listing.first_registration_date,
        power_kw=listing.power_kw,
        co2_g_km=listing.co2_g_km,
        price_eur=listing.price_eur,
        seat_count=listing.seat_count,
        is_new=False,
    )

    warnings: list[str] = []
    co2_source = "scraped"
    confidence = "high"
    debug: dict | None = None

    co2_g_km = listing.co2_g_km

    # Catalogue lookup if CO2 missing.
    if co2_g_km is None and listing.brand:
        match_result = await find_match(
            session,
            brand=listing.brand,
            model=listing.model,
            variant=listing.variant,
            fuel_type=listing.fuel_type,
            power_kw=listing.power_kw,
        )

        if match_result.status == MatchStatus.AUTO_MATCHED and match_result.matched:
            row = match_result.matched
            co2_g_km = row.co2_g_km
            co2_source = "catalogue"
            parsed.co2_g_km = co2_g_km

            if settings.debug:
                debug = {
                    "catalogue_match": {
                        "brand": row.brand,
                        "model": row.model,
                        "variant": row.variant,
                        "power_kw": row.power_kw,
                        "catalogue_id": row.catalogue_id,
                    }
                }
        else:
            co2_source = "manual_required"
            confidence = "low"
            warnings.append("CO2 value could not be determined automatically — please enter it manually.")

    # Guard: zero/negative CO2 is only valid for electric; invalidate it for all others.
    if co2_g_km is not None and co2_g_km <= 0:
        resolved_fuel = _parse_fuel(listing.fuel_type)
        if resolved_fuel != FuelType.ELECTRIC:
            co2_g_km = None
            parsed.co2_g_km = None
            co2_source = "manual_required"
            confidence = "low"
            warnings.append("CO2 value invalid (≤ 0) — manual input required.")

    # If CO2 still None after catalogue, can't compute PPMV.
    if co2_g_km is None:
        return CalculateResponse(
            ppmv_eur=None,
            parsed=parsed,
            co2_source=co2_source,  # type: ignore[arg-type]
            confidence=confidence,  # type: ignore[arg-type]
            warnings=warnings,
            debug=debug,
        )

    # Resolve fuel type.
    fuel_type = _parse_fuel(listing.fuel_type)
    if fuel_type is None:
        warnings.append(f"Unrecognized fuel type {listing.fuel_type!r} — PPMV calculation skipped.")
        return CalculateResponse(
            ppmv_eur=None,
            parsed=parsed,
            co2_source=co2_source,  # type: ignore[arg-type]
            confidence=confidence,  # type: ignore[arg-type]
            warnings=warnings,
            debug=debug,
        )

    # Resolve registration date.
    reg_date = _parse_date(listing.first_registration_date)
    if reg_date is None:
        warnings.append("Missing or unrecognized first registration date — PPMV calculation skipped.")
        return CalculateResponse(
            ppmv_eur=None,
            parsed=parsed,
            co2_source=co2_source,  # type: ignore[arg-type]
            confidence=confidence,  # type: ignore[arg-type]
            warnings=warnings,
            debug=debug,
        )

    if listing.price_eur is None:
        warnings.append("Missing price — PPMV calculation skipped.")
        return CalculateResponse(
            ppmv_eur=None,
            parsed=parsed,
            co2_source=co2_source,  # type: ignore[arg-type]
            confidence=confidence,  # type: ignore[arg-type]
            warnings=warnings,
            debug=debug,
        )

    breakdown = calculate_ppmv(
        price_eur=listing.price_eur,
        co2_g_km=co2_g_km,
        fuel_type=fuel_type,
        first_registration_date=reg_date,
        declaration_date=date.today(),
        seat_count=listing.seat_count,
        is_new_vehicle=False,
    )

    return CalculateResponse(
        ppmv_eur=breakdown.final_ppmv,
        parsed=parsed,
        co2_source=co2_source,  # type: ignore[arg-type]
        confidence=confidence,  # type: ignore[arg-type]
        warnings=warnings,
        debug=debug,
    )
