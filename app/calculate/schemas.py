"""Request/response contracts for the POST /calculate endpoint."""

from typing import Literal

from pydantic import BaseModel, HttpUrl

from app.catalogue.schemas import CatalogueCandidate

# Named so the router can annotate its own working state with the same types
# the response is validated against — otherwise those locals are plain `str`
# and every response construction needs a type: ignore to get past the check.
# Deliberately NOT extended with a "wikipedia_estimate" member, despite
# docs/WIKIPEDIA_CO2_PLAN.md §0 asking for one. That same section also requires
# /calculate to keep returning `manual_required` when Wikipedia is the only
# tier available, and the two cannot both be true of one field. Keeping the
# enum at three values and carrying the estimate in `wikipedia_hint` below
# means "manual_required still means manual_required" for every consumer, and
# no downstream branch has to learn a fourth value that it would then have to
# treat identically to manual_required anyway.
Co2Source = Literal["scraped", "catalogue", "manual_required"]
Confidence = Literal["high", "low"]
MatchStatusStr = Literal["auto_matched", "candidates", "no_match", "not_attempted"]


class CalculateRequest(BaseModel):
    url: HttpUrl
    # Cloudflare Turnstile token from the frontend widget — verified only for
    # the mobile.de/Apify path (app/scraping/mobile_de_guard.py). None when
    # Turnstile is unconfigured (dev) or the request isn't mobile.de.
    turnstile_token: str | None = None


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


class WikipediaCo2Hint(BaseModel):
    """A CO2 *range* from `wikipedia_engine_data`, shown as an unconfirmed hint.

    The last-resort tier: populated only when neither the listing nor the
    catalogue produced a CO2 value. It is never a tax input — `co2_source`
    stays `manual_required` whenever this is set, and the range never reaches
    `calculate_ppmv` (docs/WIKIPEDIA_CO2_PLAN.md §0, non-negotiable). Measured
    coverage is ~39% of vehicles, and 57% of the answers contain the true
    value, which is useful as a sanity check against a COC document and
    nowhere near good enough to compute a tax bill from.

    A projection of `app/wikipedia/co2_lookup.WikipediaCo2Estimate` (a frozen
    dataclass, not a Pydantic model), narrowed to what the UI needs: the range,
    and enough provenance to render a source link. The estimate's `score`,
    `merged_rows`, `engine_code` and `source_order_corrected` are deliberately
    not exposed — a numeric score rendered next to a range invites exactly the
    "the system is confident" reading this tier must not project, and the other
    three are extraction internals with no meaning to a user.
    """

    # Unit-suffixed to match ParsedFields.co2_g_km / price_eur / power_kw. The
    # source dataclass and DB column are the bare `co2_min`/`co2_max`; this is
    # the one place the two spellings meet (see _to_wikipedia_hint).
    co2_min_g_km: float
    co2_max_g_km: float
    #: de.wikipedia article the range came from, for the "check the source" link
    source_url: str
    brand: str
    model_article_title: str


class CalculateResponse(BaseModel):
    ppmv_eur: float | None
    parsed: ParsedFields
    co2_source: Co2Source
    confidence: Confidence
    warnings: list[str]
    debug: dict | None = None
    # Ranked catalogue rows the listing was matched against, so the user can
    # pick a different one (and its price/CO2) instead of the auto-picked row.
    match_status: MatchStatusStr = "not_attempted"
    candidates: list[CatalogueCandidate] = []
    # Last-resort CO2 hint. Non-null only alongside co2_source ==
    # "manual_required"; None whenever a real CO2 value was found, and also
    # when the Wikipedia corpus simply had no confident answer (the common
    # case — the lookup declines far more often than it answers).
    wikipedia_hint: WikipediaCo2Hint | None = None
