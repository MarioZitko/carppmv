"""Catalogue browsing/search API — lets the frontend look up brand/model/
variant + price/CO2 directly from the database, with no listing URL at all.

Mounted at /catalogue in main.py.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.catalogue.matching import MAX_CANDIDATES, find_match
from app.catalogue.schemas import CatalogueCandidate, CatalogueSearchResponse
from app.db.models import Catalogue
from app.db.session import get_db_session

router = APIRouter()

# The manual "search the database" flow has no listing signal beyond what the
# user types, so it gets a smaller default than /calculate's scraped-listing
# flow — still scrollable on the frontend, not a hard cap on correctness.
_SEARCH_CANDIDATE_LIMIT = 12


@router.get("/brands", response_model=list[str])
async def list_brands(session: AsyncSession = Depends(get_db_session)) -> list[str]:
    stmt = select(distinct(Catalogue.brand)).order_by(Catalogue.brand)
    rows = (await session.execute(stmt)).scalars().all()
    return list(rows)


@router.get("/models", response_model=list[str])
async def list_models(
    brand: str = Query(...),
    session: AsyncSession = Depends(get_db_session),
) -> list[str]:
    """Distinct model names for one brand — feeds the search form's model
    suggestions so typing doesn't require knowing the exact catalogue string;
    the actual match is still fuzzy-scored server-side regardless of what's
    picked here."""
    stmt = (
        select(distinct(Catalogue.model))
        .where(func.lower(Catalogue.brand) == brand.strip().lower())
        .order_by(Catalogue.model)
    )
    rows = (await session.execute(stmt)).scalars().all()
    return list(rows)


@router.get("/search", response_model=CatalogueSearchResponse)
async def search_catalogue(
    brand: str = Query(...),
    model: str | None = Query(None),
    variant: str | None = Query(None),
    fuel_type: str | None = Query(None),
    power_kw: float | None = Query(None),
    year: int | None = Query(None, description="First-registration year, used to prefer the catalogue price/CO2 period valid around that year"),
    session: AsyncSession = Depends(get_db_session),
) -> CatalogueSearchResponse:
    """Fuzzy-search the catalogue by brand + free-text model/variant.

    Reuses the same matcher the /calculate flow uses for scraped listings,
    so a manual search and a scraped listing resolve to candidates the same
    way. Fuzzy match quality (`score`) always ranks first — `year`, when
    given, only breaks ties *within* the same score (rows the matcher already
    considers equally good), to prefer the catalogue period closest to that
    year. It never lets a low-quality match with the "right" year outrank a
    genuinely better match. The tiebreak happens inside find_match/rank_candidates
    (before candidates are truncated to `limit`), so a correct-year row can't
    get cut before it has a chance to win the tiebreak.
    """
    result = await find_match(
        session,
        brand=brand,
        model=model,
        variant=variant,
        fuel_type=fuel_type,
        power_kw=power_kw,
        limit=max(_SEARCH_CANDIDATE_LIMIT, MAX_CANDIDATES),
        year=year,
    )

    def to_candidate(row, score: float) -> CatalogueCandidate:
        return CatalogueCandidate(
            catalogue_id=row.catalogue_id,
            brand=row.brand,
            model=row.model,
            variant=row.variant,
            price_eur=row.price_eur,
            co2_g_km=row.co2_g_km,
            co2_standard=row.co2_standard,
            fuel_type=row.fuel_type,
            power_kw=row.power_kw,
            valid_from=row.valid_from,
            score=score,
        )

    matched = to_candidate(result.matched, 100.0) if result.matched else None
    candidates = [to_candidate(c.row, c.score) for c in result.candidates]

    return CatalogueSearchResponse(status=result.status.value, matched=matched, candidates=candidates)
