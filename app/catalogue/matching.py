"""Match a scraped listing to a Catalogue row.

The problem this solves is NOT the cross-format-code problem that ingestion
faces (VW MODEL KOD vs BMW KOD MODELA vs Porsche bare `model`). Those codes
are an ingestion concern only — a car listing site never exposes the customs
internal code, it shows free text like "BMW 320d xDrive M Sport". The only
vocabulary both sides share is human-readable brand + model + variant text, so
matching is fuzzy text reconciliation, not a join on a shared key.

Two tiers, deliberately no embeddings and no LLM in this path (the LLM stays at
ingestion, for column mapping):

  1. Exact: normalize the listing's brand+model+variant into a match_key and
     hit Catalogue.match_key (indexed). Instant, high confidence.
  2. Fuzzy: hard-filter by brand (and fuel when the listing states it), then
     score remaining variants with rapidfuzz token_set_ratio, using power_kw as
     a strong disambiguator — a listing whose power contradicts a candidate's
     engine drops that candidate below the auto-accept bar.

Decision policy is "confirm unless certain": auto-accept ONLY when the top score
clears ACCEPT_SCORE and no *differently-priced* candidate sits within
ACCEPT_MARGIN of it. Everything else returns ranked candidates for the user to
confirm — because a wrong as-new price (or CO2) silently corrupts the whole PPMV,
whereas an unfilled field is harmless and the user can always type it.

rank_candidates() is pure and DB-free (unit-tested in isolation); find_match()
is the thin async DB layer that fetches brand-filtered candidates and delegates
to it.
"""

import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from enum import Enum

from rapidfuzz import fuzz
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Catalogue

# --- tuning knobs -----------------------------------------------------------
# Auto-accept needs a high score AND no differently-priced rival this close.
ACCEPT_SCORE = 88.0
ACCEPT_MARGIN = 6.0
# Below this, even the best candidate isn't worth showing — treat as no match.
CANDIDATE_FLOOR = 62.0
MAX_CANDIDATES = 5

# power_kw disambiguation. A small gap (rounding, trim variation) earns a nudge;
# a large gap means a different engine and is penalised hard enough to keep a
# wrong-engine fuzzy hit out of auto-accept. Between the two, the adjustment
# ramps linearly rather than sitting at zero — a flat "untouched" mid band let
# same-model-different-engine rows (e.g. a 131kW 120i vs a 115kW 120, 16kW
# apart) land within a point of the correct candidate on fuzzy text alone,
# since the sparse brand+model+variant text barely distinguishes them either.
POWER_TOLERANCE_KW = 7.0
POWER_BONUS = 4.0
POWER_PENALTY_GAP_KW = 25.0
POWER_PENALTY = 25.0

# Model disambiguation. token_set_ratio on the full brand+model+variant blob is
# fooled by shared trim/engine tokens (e.g. "Audi A3 Sportback 35 TDI S tronic"
# vs "Audi Q3 35 TDI S tronic" scores ~93 on the blob alone — nearly every token
# except the model letter matches). Scoring the model field on its own catches
# this: "a3" vs "q3" scores ~50, nowhere near "a3" vs "a3" at 100. When the
# model-only score falls below MODEL_MATCH_THRESHOLD, the blob score is
# penalised hard enough to drop a wrong-model row out of auto-accept and,
# usually, out of CANDIDATE_FLOOR entirely.
MODEL_MATCH_THRESHOLD = 70.0
MODEL_MISMATCH_PENALTY = 40.0

# Token-level canonicalisation for the few body-style synonyms that genuinely
# differ between listing sites and customs sheets. Kept tiny and conservative on
# purpose — over-eager synonym folding hides real distinctions. Extend only with
# pairs confirmed across both sources.
_TOKEN_SYNONYMS: dict[str, str] = {
    "limousine": "sedan",
    "limuzina": "sedan",
    "berline": "sedan",
    "touring": "wagon",
    "estate": "wagon",
    "avant": "wagon",
    "karavan": "wagon",
    "kombi": "wagon",
}


def _strip_diacritics(text: str) -> str:
    """č/ć/ž/š/đ and accented Latin → ASCII base letters, so 'Škoda' and
    'Skoda' (and Croatian vs English spellings) collapse together."""
    decomposed = unicodedata.normalize("NFKD", text)
    # đ/Đ don't decompose under NFKD — handle them explicitly.
    decomposed = decomposed.replace("đ", "d").replace("Đ", "D")
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


# Splits a digit run from a *following* multi-letter run ("40TDI" -> "40 TDI",
# "45TFSI" -> "45 TFSI"), but deliberately requires 2+ letters so genuine
# fused model/engine codes with a single trailing letter ("320d", "530i")
# are left alone — those aren't trim-naming shorthand, splitting them would
# just discard a real identifier.
_DIGIT_LETTER_BOUNDARY = re.compile(r"(?<=[0-9])(?=[a-zA-Z]{2,})")


def normalize_text(text: str | None) -> str:
    """Lowercase, strip diacritics, split digit+trim-code runs apart, replace
    every remaining non-alphanumeric run with a single space, canonicalise
    known synonym tokens, collapse whitespace.

    The digit/trim-code split matters: engine-code trims are written with no
    separator on one side and a period on the other depending on the naming
    era ("40TDI" post-2019 vs "2.0 TDI" pre-2019), and without it "40TDI"
    fuses into one opaque token that can't token-match a query's "40" + "tdi"
    — while "2.0 TDI" splits on its period and keeps a clean "tdi" token, so
    an unrelated old-naming variant would outscore the correct new-naming one
    purely from that accidental tokenization difference.

    Deterministic and side-effect free — the same function normalizes both the
    stored match_key (at ingestion) and the query (at lookup), so the two sides
    are guaranteed comparable."""
    if not text:
        return ""
    lowered = _strip_diacritics(text.lower())
    spaced = _DIGIT_LETTER_BOUNDARY.sub(" ", lowered)
    cleaned = "".join(ch if ch.isalnum() else " " for ch in spaced)
    tokens = (_TOKEN_SYNONYMS.get(tok, tok) for tok in cleaned.split())
    return " ".join(tokens)


def build_match_key(brand: str | None, model: str | None, variant: str | None) -> str:
    """Normalized brand+model+variant, deduplicating repeated tokens while
    preserving order (brand/model words often reappear inside variant, e.g.
    variant 'BMW 320d xDrive' under brand 'BMW' model 'serija 3') so the key
    isn't skewed by accidental repetition."""
    combined = normalize_text(" ".join(p for p in (brand, model, variant) if p))
    seen: set[str] = set()
    unique: list[str] = []
    for tok in combined.split():
        if tok not in seen:
            seen.add(tok)
            unique.append(tok)
    return " ".join(unique)


@dataclass(frozen=True)
class CandidateRow:
    """DB-free view of a Catalogue row, so the ranker can be unit-tested without
    a database. Built from an ORM row by _to_candidate()."""

    catalogue_id: int | None
    brand: str
    model: str
    variant: str
    match_key: str
    price_eur: float
    co2_g_km: float | None
    co2_standard: str | None
    fuel_type: str | None
    power_kw: float | None
    valid_from: date | None


class MatchStatus(str, Enum):
    AUTO_MATCHED = "auto_matched"  # one confident, unambiguous row — safe to prefill
    CANDIDATES = "candidates"      # plausible rows, but user must confirm which
    NO_MATCH = "no_match"          # nothing close enough — manual entry


@dataclass(frozen=True)
class ScoredCandidate:
    row: CandidateRow
    score: float  # 0–100, after power adjustment


@dataclass(frozen=True)
class MatchResult:
    status: MatchStatus
    matched: CandidateRow | None       # populated only when AUTO_MATCHED
    candidates: list[ScoredCandidate]  # ranked best-first; empty when NO_MATCH


def _score_one(
    query_key: str,
    cand: CandidateRow,
    listing_power_kw: float | None,
    query_model: str | None = None,
) -> float:
    base = float(fuzz.token_set_ratio(query_key, cand.match_key))

    if query_model and cand.model:
        model_score = fuzz.token_set_ratio(normalize_text(query_model), normalize_text(cand.model))
        if model_score < MODEL_MATCH_THRESHOLD:
            base = max(0.0, base - MODEL_MISMATCH_PENALTY)

    if listing_power_kw is not None and cand.power_kw is not None:
        diff = abs(listing_power_kw - cand.power_kw)
        if diff <= POWER_TOLERANCE_KW:
            return min(100.0, base + POWER_BONUS)
        if diff >= POWER_PENALTY_GAP_KW:
            return max(0.0, base - POWER_PENALTY)
        # Linear ramp from +POWER_BONUS (at the tolerance edge) down to
        # -POWER_PENALTY (at the penalty-gap edge) — see the tuning-knob
        # comment above for why the mid band can't just be left flat.
        span = POWER_PENALTY_GAP_KW - POWER_TOLERANCE_KW
        frac = (diff - POWER_TOLERANCE_KW) / span
        adjustment = POWER_BONUS - frac * (POWER_BONUS + POWER_PENALTY)
        return max(0.0, min(100.0, base + adjustment))
    return base


def rank_candidates(
    query_key: str,
    candidates: list[CandidateRow],
    listing_power_kw: float | None = None,
    limit: int = MAX_CANDIDATES,
    query_model: str | None = None,
    year: int | None = None,
) -> MatchResult:
    """Pure scoring + decision. Sorts candidates by adjusted score, then applies
    the confirm-unless-certain policy.

    Same brand+model+variant text commonly repeats across several catalogue
    validity periods (price/CO2 change year to year), so those periods always
    tie on score and need a tiebreak: when a target `year` is known (the
    listing's first registration, or what the user typed in the search form),
    the period actually in effect that year wins — i.e. the latest valid_from
    that is still <= year (a validity period runs from valid_from until
    superseded, so "closest by raw date distance" is wrong: a period starting
    after the target year was never in effect for it, no matter how close).
    If no period had started yet by that year, the soonest future period is
    the least-wrong fallback. With no year signal, the most recent valid_from
    wins (best guess). This must happen here, before `limit` truncates the
    list — reordering only the already-truncated top N (as a post-hoc step)
    can drop the actually-correct period before it ever gets a chance to win
    the tiebreak.

    Auto-accept requires the top score ≥ ACCEPT_SCORE and that every candidate
    within ACCEPT_MARGIN of the top shares the top's price_eur — i.e. the only
    near-ties are the same priced answer under different validity periods, not a
    genuinely different (differently-priced) variant. Otherwise the caller gets
    ranked candidates to confirm.

    `limit` caps how many ranked candidates are returned to the caller — the
    decision policy above always scores the full candidate set first, so a
    larger limit only affects how many alternatives a human sees, never the
    auto-accept/no-match decision itself."""
    if not candidates:
        return MatchResult(MatchStatus.NO_MATCH, None, [])

    scored = [
        ScoredCandidate(c, _score_one(query_key, c, listing_power_kw, query_model)) for c in candidates
    ]

    if year is not None:
        def _sort_key(s: ScoredCandidate) -> tuple[float, int, int]:
            vf = s.row.valid_from
            vf_year = vf.year if vf else year
            ordinal = vf.toordinal() if vf else 0
            if vf_year <= year:
                return (s.score, 1, ordinal)  # already in effect: prefer most recent update
            return (s.score, 0, -ordinal)  # not yet in effect: prefer soonest
    else:
        def _sort_key(s: ScoredCandidate) -> tuple[float, date]:
            return (s.score, s.row.valid_from or date.min)

    scored.sort(key=_sort_key, reverse=True)

    top = scored[0]
    if top.score < CANDIDATE_FLOOR:
        return MatchResult(MatchStatus.NO_MATCH, None, [])

    near_top = [s for s in scored if top.score - s.score <= ACCEPT_MARGIN]
    distinct_prices = {round(s.row.price_eur, 2) for s in near_top}
    if top.score >= ACCEPT_SCORE and len(distinct_prices) == 1:
        return MatchResult(MatchStatus.AUTO_MATCHED, top.row, scored[:limit])

    return MatchResult(MatchStatus.CANDIDATES, None, scored[:limit])


# Listing fuel strings are messy and multilingual; only map the unambiguous
# cases. Anything else → None → no fuel filter (better to over-include than to
# wrongly drop the correct row). Catalogue stores only petrol/diesel: electric
# is exempt (never ingested) and hybrids are taxed-as-petrol.
_LISTING_FUEL_MAP: dict[str, str] = {
    "diesel": "diesel",
    "dizel": "diesel",
    "petrol": "petrol",
    "benzin": "petrol",
    "gasoline": "petrol",
}


def _map_listing_fuel(fuel_type: str | None) -> str | None:
    if not fuel_type:
        return None
    return _LISTING_FUEL_MAP.get(fuel_type.strip().lower())


def _to_candidate(row: Catalogue) -> CandidateRow:
    return CandidateRow(
        catalogue_id=row.id,
        brand=row.brand,
        model=row.model,
        variant=row.variant,
        match_key=row.match_key,
        price_eur=row.price_eur,
        co2_g_km=row.co2_g_km,
        co2_standard=row.co2_standard.value if row.co2_standard is not None else None,
        fuel_type=row.fuel_type.value if row.fuel_type is not None else None,
        power_kw=row.power_kw,
        valid_from=row.valid_from,
    )


async def find_match(
    session: AsyncSession,
    *,
    brand: str,
    model: str | None,
    variant: str | None,
    fuel_type: str | None = None,
    power_kw: float | None = None,
    limit: int = MAX_CANDIDATES,
    year: int | None = None,
) -> MatchResult:
    """Fetch this brand's catalogue rows and rank them against the listing.

    Brand is a hard filter (case-insensitive); at O(thousands) total rows a
    per-brand fetch is a handful to a few hundred rows — trivial for the
    human-paced, one-listing-at-a-time PPMV flow. Fuel narrows further only when
    it maps cleanly and doesn't wipe out every candidate. `year` (first
    registration year, or the year the user typed in a manual search) picks
    which validity period wins among otherwise-identical rows — see
    rank_candidates()."""
    query_key = build_match_key(brand, model, variant)

    stmt = select(Catalogue).where(func.lower(Catalogue.brand) == brand.strip().lower())
    rows = (await session.execute(stmt)).scalars().all()
    candidates = [_to_candidate(r) for r in rows]

    fuel = _map_listing_fuel(fuel_type)
    if fuel is not None:
        narrowed = [c for c in candidates if c.fuel_type == fuel]
        if narrowed:  # don't let an over-strict fuel filter erase a real match
            candidates = narrowed

    return rank_candidates(
        query_key, candidates, listing_power_kw=power_kw, limit=limit, query_model=model, year=year
    )
