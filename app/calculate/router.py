"""POST /calculate — URL in, PPMV out.

Pipeline:
  1. Detect site from URL domain → pick extractor
  2. Run extractor → ListingData
  3. Catalogue matcher always runs (when brand is known) → fills CO2 when
     missing, and always surfaces ranked candidates so the user can pick a
     different catalogue row (different price/CO2) than the auto-picked one.
  3b. Wikipedia CO2 lookup — last resort, hint only. Runs only when steps 2
     and 3 both failed to produce a CO2 value. Its answer NEVER feeds step 4
     and never changes co2_source; it rides along in `wikipedia_hint` for the
     UI to show next to the manual CO2 field.
  4. Run PPMV engine
  5. Return CalculateResponse

Each step below is one helper, so `calculate()` itself reads as those five
lines. Anything that stops the pipeline short (no CO2, unknown fuel, missing
date or price) still returns a 200 with the fields we did manage to parse —
the frontend turns that into a prefilled manual-entry form, so a partial
answer is worth much more to the user than an error.
"""

import logging
from dataclasses import dataclass, field
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.calculate.schemas import (
    CalculateRequest,
    CalculateResponse,
    Co2Source,
    Confidence,
    MatchStatusStr,
    ParsedFields,
    WikipediaCo2Hint,
)
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
from app.scraping.schemas import ListingData
from app.scraping.site_registry import EXTRACTORS, SITE_TO_SCRAPE_SITE, detect_site
from app.wikipedia.browse import clean_query
from app.wikipedia.co2_lookup import WikipediaCo2Estimate, resolve_co2_from_wikipedia

log = logging.getLogger(__name__)

router = APIRouter()

# A scraped listing already carries a strong brand/model/variant/power signal,
# so it's worth surfacing more alternatives than the catalogue-search default —
# the frontend renders these in a scrollable list, not a page-length one.
_CALCULATE_CANDIDATE_LIMIT = 15

# Accepts the full canonical ListingData.fuel_type vocabulary, not just the
# three PPMV enum spellings. The extractors legitimately emit "hybrid", "lpg"
# and "cng" (see app/db/models.py::FuelType, which has all six), and any value
# missing here aborts the whole calculation — an unmapped fuel is a blank
# result for the user, not a degraded one.
#
# lpg/cng/hybrid fold to PETROL because FuelType.PETROL is defined as "also
# covers LPG/CNG/other non-diesel per Tablice 3/6" (app/ppmv/schemas.py). A
# bare "hybrid" carries no parent-fuel signal, so non-diesel is the
# conservative read; extractors that know the parent fuel (autoscout24) already
# resolve it to petrol/diesel themselves.
#
# frontend/lib/fuel.ts mirrors this map for the manual-entry form — add
# spellings to both, or the two paths disagree about the same car.
_FUEL_MAP: dict[str, FuelType] = {
    "diesel": FuelType.DIESEL,
    "dizel": FuelType.DIESEL,
    "petrol": FuelType.PETROL,
    "benzin": FuelType.PETROL,
    "gasoline": FuelType.PETROL,
    "lpg": FuelType.PETROL,
    "cng": FuelType.PETROL,
    "hybrid": FuelType.PETROL,
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


@dataclass
class _Resolution:
    """Everything the pipeline accumulates between scraping and the tax call.

    Exists so the several places that give up early and the one that succeeds
    all build their response through `respond()` instead of repeating the same
    eight-field constructor.
    """

    parsed: ParsedFields
    co2_g_km: float | None
    co2_source: Co2Source = "scraped"
    confidence: Confidence = "high"
    warnings: list[str] = field(default_factory=list)
    debug: dict | None = None
    match_status: MatchStatusStr = "not_attempted"
    candidates: list[CatalogueCandidate] = field(default_factory=list)
    #: Set only by the last-resort Wikipedia tier, and only when co2_g_km is
    #: still None after scraping and the catalogue. Never read by anything
    #: that decides the tax.
    wikipedia_hint: WikipediaCo2Hint | None = None

    def require_manual_co2(self, warning: str) -> None:
        """Drop the CO2 we have (if any) and ask the user for it instead."""
        self.co2_g_km = None
        self.parsed.co2_g_km = None
        self.co2_source = "manual_required"
        self.confidence = "low"
        self.warnings.append(warning)

    def respond(self, ppmv_eur: float | None = None, warning: str | None = None) -> CalculateResponse:
        if warning:
            self.warnings.append(warning)
        return CalculateResponse(
            ppmv_eur=ppmv_eur,
            parsed=self.parsed,
            co2_source=self.co2_source,
            confidence=self.confidence,
            warnings=self.warnings,
            debug=self.debug,
            match_status=self.match_status,
            candidates=self.candidates,
            wikipedia_hint=self.wikipedia_hint,
        )


async def _scrape(
    url: str,
    site: str,
    session: AsyncSession,
    request: Request,
    turnstile_token: str | None,
) -> ListingData:
    """Step 1+2 — dispatch to the site's fetch path and record the outcome.

    mobile.de has no local Extractor; it goes through the Apify-backed guard
    stack instead. Raises ScrapingError (→ 502 via core/exceptions.py),
    ApifyBudgetExceeded (caught by the caller), or 422 for an unknown domain.
    """
    scrape_site = SITE_TO_SCRAPE_SITE.get(site)

    if site == MOBILE_DE_SITE:
        fetch = guarded_mobile_de_listing(url, session, request, turnstile_token)
    elif site in EXTRACTORS:
        fetch = EXTRACTORS[site].extract(url)
    else:
        raise HTTPException(
            status_code=422,
            detail=[{"loc": ["body", "url"], "msg": f"Unrecognized domain: {url}", "type": "value_error"}],
        )

    try:
        listing = await fetch
    except ScrapingError as exc:
        if scrape_site is not None:
            await record_scrape_outcome(session, site=scrape_site, error_message=str(exc))
        raise

    if scrape_site is not None:
        await record_scrape_outcome(session, site=scrape_site, listing=listing)
    return listing


def _to_parsed_fields(listing: ListingData) -> ParsedFields:
    return ParsedFields(
        brand=listing.brand,
        model=listing.model,
        variant=listing.variant,
        fuel_type=listing.fuel_type,
        # ListingData carries the raw string; the caller parses it separately.
        first_registration=listing.first_registration_date,
        power_kw=listing.power_kw,
        co2_g_km=listing.co2_g_km,
        price_eur=listing.price_eur,
        seat_count=listing.seat_count,
        is_new=False,
        vin=listing.vin,
    )


async def _apply_catalogue_match(
    state: _Resolution,
    session: AsyncSession,
    listing: ListingData,
    reg_date: date | None,
) -> None:
    """Step 3 — always runs when the brand is known. Fills CO2 when the listing
    didn't expose it, and always surfaces ranked candidates so the user can
    override the auto-picked row with a different price/CO2 combination.

    The first-registration year (when known) picks the catalogue validity
    period that actually applied on that date, instead of defaulting to the
    most recent one regardless of how old the vehicle is.
    """
    match_result = await find_match(
        session,
        brand=listing.brand,
        model=listing.model,
        variant=listing.variant,
        fuel_type=listing.fuel_type,
        power_kw=listing.power_kw,
        limit=_CALCULATE_CANDIDATE_LIMIT,
        year=reg_date.year if reg_date else None,
        co2_g_km=state.co2_g_km,
    )
    state.match_status = match_result.status.value
    state.candidates = [_to_candidate(c.row, c.score) for c in match_result.candidates]

    row = match_result.matched if match_result.status == MatchStatus.AUTO_MATCHED else None

    # Fuel from the matched row when the listing didn't state one. autobid.de
    # exposes neither CO2 nor fuel pre-login, so its listings arrived with
    # fuel_type None — and an unknown fuel aborts the whole calculation, which
    # is how a car the catalogue had matched *exactly* ("Audi A3 Sportback 1.2
    # TFSI Attraction / Benzin / 1.2l / 77 kW", auto-matched, CO2 114) still
    # produced no number at all.
    #
    # Trusting the row for fuel is not a new leap of faith: this is the same
    # auto-matched row whose CO2 we already take below, and fuel is the coarser
    # of the two facts. Done before the CO2 early-return, because a listing can
    # state CO2 and still omit fuel.
    if row is not None and not state.parsed.fuel_type and row.fuel_type:
        state.parsed.fuel_type = row.fuel_type

    if state.co2_g_km is not None:
        return  # listing already had CO2; the candidates are just for override

    # An auto-matched row is not automatically a *useful* row. Nothing in
    # matching.py's accept rule (top score >= ACCEPT_SCORE, and the near-tied
    # rows agreeing on price) requires the row to carry a CO2 value, so
    # `matched` can arrive with co2_g_km None. Every catalogue row has one
    # today, which makes this latent rather than live — but taking `matched` on
    # faith set co2_source="catalogue" while co2_g_km stayed None, which reads
    # to every consumer as "we found it", skipped the manual-entry warning, and
    # left the user with no CO2 and no prompt to supply one.
    if row is None or row.co2_g_km is None:
        state.require_manual_co2("CO2 vrijednost nije moguće automatski odrediti — unesite je ručno.")
        return

    state.co2_g_km = row.co2_g_km
    state.co2_source = "catalogue"
    state.parsed.co2_g_km = row.co2_g_km

    if get_settings().debug:
        state.debug = {
            "catalogue_match": {
                "brand": row.brand,
                "model": row.model,
                "variant": row.variant,
                "power_kw": row.power_kw,
                "catalogue_id": row.catalogue_id,
            }
        }


def _to_wikipedia_hint(estimate: WikipediaCo2Estimate) -> WikipediaCo2Hint:
    """Project the frozen dataclass onto the response schema.

    The bare `co2_min`/`co2_max` of the dataclass and the DB column become the
    unit-suffixed names the schema layer uses everywhere else; this is the only
    place the two spellings meet.
    """
    return WikipediaCo2Hint(
        co2_min_g_km=estimate.co2_min,
        co2_max_g_km=estimate.co2_max,
        source_url=estimate.source_url,
        brand=estimate.brand,
        model_article_title=estimate.model_article_title,
    )


def _wikipedia_model_text(listing: ListingData) -> str | None:
    """The `model` string to hand the Wikipedia matcher.

    It wants the model name plus the engine designation ("Golf 1.6 TDI",
    "320d") and explicitly does NOT want the dealer trim blob — trim and body
    words appear nowhere in a de.wikipedia table and only dilute the text
    score. Both `model` and `variant` go in because the engine designation is
    reliably somewhere across the two, but the result is cleaned first:

    1. Brand tokens are dropped. The brand is already the matcher's SQL filter
       and is stripped from the candidate side of the comparison, so "Audi" in
       the query is pure dilution.
    2. Body-style and trim words are dropped.
    3. Repeats are collapsed. Several sites restate the model inside the
       variant ("A3" + "Audi A3 Sportback ..."), which double-counts a token
       that carries no extra information.

    Cleaning only ever *removes* tokens, so it cannot invent a match; the worst
    case is the same declined lookup as before.

    Measured over 500 random catalogue rows with known CO2, cleaning is a wash:

        model + variant, cleaned     35.8% answered, 55.3% of answers correct
        model + variant, raw         36.2% answered, 55.2% of answers correct
        model alone                  38.4% answered, 50.5% of answers correct

    That benchmark is a poor proxy for this specific fix and is kept only for
    continuity with the earlier measurement. Catalogue variant strings are
    spec sheets ("... / Diesel / 2.0l / 110 kW/150 KS / 4-Vrata"), so their
    noise is units and gearbox words rather than the body-and-trim wording this
    list targets; stripping that spec noise too was tried and moved the number
    by nothing at all. Real listing titles are where the difference shows:
    autobid.de's Audi A3 Sportback 1,2 TFSI "Attraction" went from a declined
    lookup to 123-132 g/km, because its variant field is the whole title.

    Model alone still answers most often, and still least accurately — extra
    answers bought by dropping the engine designation are disproportionately
    wrong ones, which is the wrong trade for a value the user is meant to check
    against a COC.
    """
    raw = " ".join(p for p in (listing.model, listing.variant) if p)
    if not raw.strip():
        return None
    # If cleaning removed everything (a listing whose variant is nothing but
    # trim words), fall back to the raw text rather than querying for "".
    return clean_query(raw, brand=listing.brand) or raw


async def _apply_wikipedia_hint(
    state: _Resolution,
    session: AsyncSession,
    listing: ListingData,
    reg_date: date | None,
) -> None:
    """Step 3b — the last-resort CO2 tier, reached only when steps 2 and 3 both
    came up empty.

    Hint only, and structurally so: it writes `state.wikipedia_hint` and
    nothing else. `co2_g_km` stays None, `co2_source` stays whatever
    `require_manual_co2` set it to, and the value therefore cannot reach
    `calculate_ppmv` — the guard below this call returns before the engine is
    ever invoked. That is docs/WIKIPEDIA_CO2_PLAN.md §0, which is
    non-negotiable: coverage is ~39% and only 57% of answers contain the true
    value, so it is a "check your COC" prompt, not a tax input.

    **No warning is appended here.** `require_manual_co2` has already added the
    one CO2 warning this response gets, and a second one would both duplicate
    it and frame a *successful* extra lookup as another thing that went wrong.

    Failures are swallowed. This tier is strictly additive — the user gets the
    same manual-entry response with or without it — so a DB hiccup in a hint
    must never turn a working 200 into a 500. Same posture as
    scraping/persistence.py, and distinct from the domain exceptions that
    core/exceptions.py maps: there is no HTTP status that would improve here.
    """
    model = _wikipedia_model_text(listing)
    try:
        estimate = await resolve_co2_from_wikipedia(
            brand=listing.brand,
            model=model,
            # parsed.fuel_type, not listing.fuel_type: the catalogue step may
            # have supplied a fuel the listing itself never stated, and fuel is
            # one of this matcher's hard filters.
            fuel=state.parsed.fuel_type,
            power_kw=listing.power_kw,
            date=reg_date,
            # Reuse the request's open session. Omitting it makes the resolver
            # open a second AsyncSessionLocal of its own, which inside a
            # request handler is a needless extra pool connection.
            session=session,
        )
    except Exception:  # noqa: BLE001 — see docstring; a hint must not 500
        log.exception("Wikipedia CO2 hint lookup failed for %s", listing.source_url)
        return

    if estimate is not None:
        state.wikipedia_hint = _to_wikipedia_hint(estimate)


@router.post("/calculate", response_model=CalculateResponse)
async def calculate(
    body: CalculateRequest,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
) -> CalculateResponse:
    url = str(body.url)
    site = detect_site(url)

    try:
        listing = await _scrape(url, site, session, request, body.turnstile_token)
    except ApifyBudgetExceeded:
        # Daily Apify budget exhausted — degrade to manual entry rather than
        # erroring, so the user can still finish the calculation by hand.
        scrape_site = SITE_TO_SCRAPE_SITE.get(site)
        if scrape_site is not None:
            await record_scrape_outcome(
                session, site=scrape_site, error_message="Daily Apify budget exhausted"
            )
        return _Resolution(
            parsed=ParsedFields(),
            co2_g_km=None,
            co2_source="manual_required",
            confidence="low",
            warnings=["Dnevni limit automatskog dohvata je dostignut. Unesite podatke ručno."],
        ).respond()

    state = _Resolution(parsed=_to_parsed_fields(listing), co2_g_km=listing.co2_g_km)
    reg_date = parse_listing_date(listing.first_registration_date)

    if listing.brand:
        await _apply_catalogue_match(state, session, listing, reg_date)

        # Step 3b. `state.co2_g_km is None` here is exactly "the listing had no
        # CO2 and the catalogue did not supply one" — the only two things that
        # can have written it at this point are the listing itself and the
        # catalogue branch above. Nothing else in the pipeline has run yet, so
        # this needs no extra bookkeeping to stay in sync with those two tiers.
        if state.co2_g_km is None:
            await _apply_wikipedia_hint(state, session, listing, reg_date)

    # parsed.fuel_type rather than listing.fuel_type — an auto-matched
    # catalogue row may have filled it in above.
    fuel_type = _parse_fuel(state.parsed.fuel_type)

    # Zero/negative CO2 is only meaningful for electric vehicles (which are
    # exempt anyway); for anything else it's a scrape artefact, not a reading.
    if state.co2_g_km is not None and state.co2_g_km <= 0 and fuel_type != FuelType.ELECTRIC:
        state.require_manual_co2("CO2 vrijednost nije ispravna (≤ 0) — potreban je ručni unos.")

    # Step 4 needs all four of these; any one missing means we hand the user a
    # prefilled form instead of a number.
    if state.co2_g_km is None:
        return state.respond()
    if fuel_type is None:
        return state.respond(
            warning=(
                f"Nepoznata vrsta goriva {state.parsed.fuel_type!r} — "
                "izračun PPMV-a preskočen."
            )
        )
    if reg_date is None:
        return state.respond(
            warning="Nedostaje ili je neprepoznat datum prve registracije — izračun PPMV-a preskočen."
        )
    if listing.price_eur is None:
        return state.respond(warning="Nedostaje cijena — izračun PPMV-a preskočen.")

    breakdown = calculate_ppmv(
        price_eur=listing.price_eur,
        co2_g_km=state.co2_g_km,
        fuel_type=fuel_type,
        first_registration_date=reg_date,
        declaration_date=date.today(),
        seat_count=listing.seat_count,
        # None (source does not expose new/used) keeps the historical
        # used-vehicle assumption, which is right for every site we scrape
        # except AutoScout24 — autobid.de is an auction house, and njuskalo
        # /mobile.de have no signal wired up yet.
        is_new_vehicle=bool(listing.is_new),
    )
    return state.respond(ppmv_eur=breakdown.final_ppmv)
