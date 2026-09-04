"""Wikipedia CO2 browsing API — "show me every CO2 value Wikipedia has for
this car", so a user whose engine the automatic lookup couldn't pin down can
pick it themselves.

Mounted at /wikipedia in main.py. Read-only: nothing here writes to
`wikipedia_engine_data`, which is populated exclusively by the offline Phase 4
upsert (`python -m app.wikipedia.upsert`).

This is the deliberate escape hatch from `co2_lookup`'s conservatism. When two
variants tie — the Audi A2's 55 kW petrol 1.4 (142 g/km) against its 55 kW
diesel 1.4 TDI (116 g/km), indistinguishable because autobid.de publishes no
fuel type — the matcher honestly reports the union, 116-142. The stored data is
not ambiguous at all; only the *listing* is. Handing the rows to the person
resolves what no amount of matcher tuning can.
"""

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy import distinct, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.catalogue.brands import canonical_brand
from app.db.models import WikipediaBrandCheck, WikipediaEngineData
from app.db.session import get_db_session
from app.wikipedia.browse import (
    MAX_ROWS,
    EngineRow,
    clean_query,
    group_models,
    search_engine_rows,
)
from app.wikipedia.schemas import (
    WikipediaEngineRow,
    WikipediaEngineSearchResponse,
    WikipediaModelListResponse,
    WikipediaModelRow,
)

router = APIRouter()


async def _brand_pool(
    brand: str, session: AsyncSession
) -> tuple[str, list[EngineRow]]:
    """Every CO2-bearing, brand-confirmed row for a marque.

    Rows with no CO2 at all are excluded: a null CO2 is a valid extraction
    (plan §0) but these endpoints exist to show CO2 values, and a list of blanks
    is worse than a shorter list. Rows whose marque could not be cross-checked
    are excluded for the same reason `co2_lookup` excludes them — a row filed
    under a brand we cannot confirm is not evidence about that brand's cars.
    """
    canonical = canonical_brand(brand) or brand.strip()
    stmt = select(WikipediaEngineData).where(
        WikipediaEngineData.brand == canonical,
        WikipediaEngineData.brand_check != WikipediaBrandCheck.UNVERIFIED,
        or_(
            WikipediaEngineData.co2_min.is_not(None),
            WikipediaEngineData.co2_max.is_not(None),
        ),
    )
    rows = (await session.execute(stmt)).scalars().all()
    return canonical, [EngineRow.from_row(row) for row in rows]


@router.get("/brands", response_model=list[str])
async def list_brands(session: AsyncSession = Depends(get_db_session)) -> list[str]:
    """Brands the corpus actually holds — 37, not the 43 the catalogue has, so
    the UI can say "no Wikipedia data for this marque" instead of showing an
    empty search box that looks broken."""
    stmt = (
        select(distinct(WikipediaEngineData.brand))
        .where(WikipediaEngineData.brand_check != WikipediaBrandCheck.UNVERIFIED)
        .order_by(WikipediaEngineData.brand)
    )
    return list((await session.execute(stmt)).scalars().all())


@router.get("/models", response_model=WikipediaModelListResponse)
async def list_models(
    brand: str = Query(..., description="Marque; canonicalised server-side"),
    q: str | None = Query(
        None,
        description=(
            "Free-text model designation. Ranks the list; never hides a model, "
            "because the user is choosing from it."
        ),
    ),
    registered: date | None = Query(
        None,
        description=(
            "Vehicle's first-registration date. Scopes the list to generations "
            "that could plausibly have been registered then; ignored if it "
            "would leave nothing."
        ),
    ),
    limit: int = Query(MAX_ROWS, ge=1, le=MAX_ROWS),
    session: AsyncSession = Depends(get_db_session),
) -> WikipediaModelListResponse:
    """The brand's model articles — the picker's first step.

    Exists because free-text matching over a listing blob cannot always be
    trusted to have found the right car, and when it hasn't, nothing in the
    result says so. A 3-series Gran Turismo has no article in the corpus at all,
    so the closest honest answer is a different body of the same era; only the
    person holding the logbook can see that. Letting them pick the generation
    first takes the guess out of the step that matters, and leaves the text box
    the job it does reliably — telling engines apart inside one generation.
    """
    canonical, rows = await _brand_pool(brand, session)
    result = group_models(
        rows, clean_query(q, brand=canonical), registered=registered, limit=limit
    )
    return WikipediaModelListResponse(
        brand=canonical,
        brand_known=bool(rows),
        models=[WikipediaModelRow(**vars(group)) for group in result.models],
        ignored_terms=list(result.ignored_terms),
    )


@router.get("/engines", response_model=WikipediaEngineSearchResponse)
async def search_engines(
    brand: str = Query(..., description="Marque; canonicalised server-side"),
    q: str | None = Query(
        None,
        description=(
            "Free-text model and/or engine designation, e.g. '320d' or "
            "'Golf 1.6 TDI'. Blank returns every row for the brand."
        ),
    ),
    article: str | None = Query(
        None,
        description=(
            "Exact model_article_title, as picked off GET /models. An exact "
            "filter, not a ranking hint — it carries the user's own choice."
        ),
    ),
    registered: date | None = Query(
        None,
        description=(
            "Vehicle's first-registration date. Scopes the list to generations "
            "that could plausibly have been registered then; ignored if it "
            "would leave nothing."
        ),
    ),
    limit: int = Query(MAX_ROWS, ge=1, le=MAX_ROWS),
    session: AsyncSession = Depends(get_db_session),
) -> WikipediaEngineSearchResponse:
    """Every engine row for a brand, optionally narrowed to one model article
    and filtered by free text."""
    canonical, rows = await _brand_pool(brand, session)

    # Callers pass listing-derived text ("A3 Audi A3 Sportback 1,2 TFSI
    # \"Attraction\""), so the brand and the body/trim words we are sure about
    # come off before ranking: they dilute the score and never discriminate.
    # Cleaning is only a first pass, not the defence — the tail of trim names is
    # unbounded and `search_engine_rows` is what actually tolerates the leftovers.
    # A deliberate short query like "1.4 TDI" is unaffected: cleaning is a no-op.
    result = search_engine_rows(
        rows,
        clean_query(q, brand=canonical),
        registered=registered,
        article=article,
        limit=limit,
    )
    return WikipediaEngineSearchResponse(
        brand=canonical,
        brand_known=bool(rows),
        rows=[WikipediaEngineRow(**vars(row)) for row in result.rows],
        ignored_terms=list(result.ignored_terms),
    )
