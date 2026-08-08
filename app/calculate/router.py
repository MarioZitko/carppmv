"""POST /calculate — URL in, PPMV out.

Pipeline:
  1. Detect site from URL domain → pick extractor
  2. Run extractor → ListingData
  3. Catalogue matcher always runs (when brand is known) → fills CO2 when
     missing, and always surfaces ranked candidates so the user can pick a
     different catalogue row (different price/CO2) than the auto-picked one.
  4. Run PPMV engine
  5. Return CalculateResponse
"""

import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.calculate.schemas import CalculateRequest, CalculateResponse, ParsedFields
from app.catalogue.display import format_variant_display
from app.catalogue.matching import MatchStatus, find_match
from app.catalogue.schemas import CatalogueCandidate
from app.core.config import get_settings
from app.core.exceptions import ScrapingError
from app.db.session import get_db_session
from app.ppmv.engine import calculate_ppmv
from app.ppmv.schemas import FuelType
from app.scraping.mobile_de_guard import guarded_mobile_de_listing
from app.scraping.mobile_de_service import MOBILE_DE_SITE, ApifyBudgetExceeded
from app.scraping.parsing import parse_listing_date
from app.scraping.persistence import record_scrape_outcome
from app.scraping.site_registry import EXTRACTORS, SITE_TO_SCRAPE_SITE, detect_site

log = logging.getLogger(__name__)

router = APIRouter()

# A scraped listing already carries a strong brand/model/variant/power signal,
# so it's worth surfacing more alternatives than the catalogue-search default —
# the frontend renders these in a scrollable list, not a page-length one.
_CALCULATE_CANDIDATE_LIMIT = 15

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


def _parse_fuel(raw: str | None) -> FuelType | None:
    if not raw:
        return None
    return _FUEL_MAP.get(raw.strip().lower())


def _to_candidate(row, score: float) -> CatalogueCandidate:
    return CatalogueCandidate(
        catalogue_id=row.catalogue_id,
        brand=row.brand,
        model=row.model,
        variant=format_variant_display(row.brand, row.variant),
        price_eur=row.price_eur,
        co2_g_km=row.co2_g_km,
        co2_standard=row.co2_standard,
        fuel_type=row.fuel_type,
        power_kw=row.power_kw,
        valid_from=row.valid_from,
        score=score,
    )


@router.post("/calculate", response_model=CalculateResponse)
async def calculate(
    body: CalculateRequest,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
) -> CalculateResponse:
    url = str(body.url)
    settings = get_settings()

    site = detect_site(url)

    scrape_site = SITE_TO_SCRAPE_SITE.get(site)

    if site == MOBILE_DE_SITE:
        try:
            listing = await guarded_mobile_de_listing(url, session, request, body.turnstile_token)
        except ApifyBudgetExceeded:
            # Daily Apify budget exhausted — degrade gracefully instead of erroring.
            if scrape_site is not None:
                await record_scrape_outcome(
                    session,
                    site=scrape_site,
                    error_message="Daily Apify budget exhausted",
                )
            return CalculateResponse(
                ppmv_eur=None,
                parsed=ParsedFields(),
                co2_source="manual_required",
                confidence="low",
                warnings=["Dnevni limit automatskog dohvata je dostignut. Unesite podatke ručno."],
                match_status="not_attempted",
                candidates=[],
            )
        if scrape_site is not None:
            await record_scrape_outcome(session, site=scrape_site, listing=listing)
    elif not site or site not in EXTRACTORS:
        raise HTTPException(
            status_code=422,
            detail=[{"loc": ["body", "url"], "msg": f"Unrecognized domain: {url}", "type": "value_error"}],
        )
    else:
        extractor = EXTRACTORS[site]
        try:
            listing = await extractor.extract(url)
        except ScrapingError as exc:
            if scrape_site is not None:
                await record_scrape_outcome(session, site=scrape_site, error_message=str(exc))
            raise
        if scrape_site is not None:
            await record_scrape_outcome(session, site=scrape_site, listing=listing)

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
        vin=listing.vin,
    )

    warnings: list[str] = []
    co2_source = "scraped"
    confidence = "high"
    debug: dict | None = None
    match_status = "not_attempted"
    candidates: list[CatalogueCandidate] = []

    co2_g_km = listing.co2_g_km
    reg_date = parse_listing_date(listing.first_registration_date)

    # Catalogue matching always runs when the brand is known — it fills CO2
    # when missing, and always surfaces ranked candidates so the user can
    # override the auto-picked row with a different price/CO2 combination.
    # The first-registration year (when known) picks the catalogue validity
    # period that actually applied on that date, instead of defaulting to
    # the most recent one regardless of how old the vehicle is.
    if listing.brand:
        match_result = await find_match(
            session,
            brand=listing.brand,
            model=listing.model,
            variant=listing.variant,
            fuel_type=listing.fuel_type,
            power_kw=listing.power_kw,
            limit=_CALCULATE_CANDIDATE_LIMIT,
            year=reg_date.year if reg_date else None,
            co2_g_km=co2_g_km,
        )
        match_status = match_result.status.value
        candidates = [_to_candidate(c.row, c.score) for c in match_result.candidates]

        if co2_g_km is None:
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
                warnings.append("CO2 vrijednost nije moguće automatski odrediti — unesite je ručno.")

    # Guard: zero/negative CO2 is only valid for electric; invalidate it for all others.
    if co2_g_km is not None and co2_g_km <= 0:
        resolved_fuel = _parse_fuel(listing.fuel_type)
        if resolved_fuel != FuelType.ELECTRIC:
            co2_g_km = None
            parsed.co2_g_km = None
            co2_source = "manual_required"
            confidence = "low"
            warnings.append("CO2 vrijednost nije ispravna (≤ 0) — potreban je ručni unos.")

    def _early_return(msg: str | None = None) -> CalculateResponse:
        if msg:
            warnings.append(msg)
        return CalculateResponse(
            ppmv_eur=None,
            parsed=parsed,
            co2_source=co2_source,  # type: ignore[arg-type]
            confidence=confidence,  # type: ignore[arg-type]
            warnings=warnings,
            debug=debug,
            match_status=match_status,  # type: ignore[arg-type]
            candidates=candidates,
        )

    # If CO2 still None after catalogue, can't compute PPMV.
    if co2_g_km is None:
        return _early_return()

    # Resolve fuel type.
    fuel_type = _parse_fuel(listing.fuel_type)
    if fuel_type is None:
        return _early_return(f"Nepoznata vrsta goriva {listing.fuel_type!r} — izračun PPMV-a preskočen.")

    # Resolve registration date.
    if reg_date is None:
        return _early_return("Nedostaje ili je neprepoznat datum prve registracije — izračun PPMV-a preskočen.")

    if listing.price_eur is None:
        return _early_return("Nedostaje cijena — izračun PPMV-a preskočen.")

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
        match_status=match_status,  # type: ignore[arg-type]
        candidates=candidates,
    )
