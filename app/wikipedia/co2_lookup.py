"""Phase 5 — resolve a CO2 *range* for a vehicle from `wikipedia_engine_data`.

    resolve_co2_from_wikipedia(brand=..., model=..., fuel=..., power_kw=..., date=...)
        -> WikipediaCo2Estimate | None

A **separate matching subsystem** from `app/catalogue/matching.py`, deliberately
sharing none of its tuning constants. That matcher reconciles free-text customs
variant blobs against free-text listing titles, and its numbers (ACCEPT_SCORE
88 on a token_set_ratio base, POWER_TOLERANCE_KW 7, and so on) are calibrated
for that. Here the rows are keyed by *engine spec* — power in kW, displacement
in cm3, a production period, a fuel — which are exact numbers on both sides of
the comparison rather than prose. Different evidence, different arithmetic,
different thresholds. Reusing the catalogue's constants here would be cargo
cult, which is why the plan calls it out explicitly.

**This never auto-fills a tax calculation** (plan §0). Its output is a hint
shown next to a manual-entry field — `/calculate` still returns
`manual_required` when this is the only source available. Nothing in this module
should be repurposed to fill `co2_g_km` silently.

**Standalone and directly callable.** `rank_candidates()` is pure and DB-free
(unit-tested in tests/test_wikipedia_co2_lookup.py); `resolve_co2_from_wikipedia()`
is a thin async layer that fetches a brand-filtered candidate set and delegates.
It accepts an optional session so a future live call on a catalogue-match
cache-miss needs no restructuring — same split as `matching.rank_candidates` /
`matching.find_match`.

---

## Decision policy

Hard filters first — a candidate that fails any is dropped, never scored:

1. **Brand** must equal the query's canonical brand, and the row's
   `brand_check` must not be `unverified`. The brand column here is already the
   *cross-checked* brand (app/wikipedia/brand_check.py), so a Subaru query can
   no longer be answered with Opel Zafira rows that Subaru's crawl happened to
   pick up.
2. **Production period must contain the registration date** when the row states
   a period, with a grace window either side. A row that states no period at
   all is dropped when a date was supplied — it cannot be confirmed, and the
   plan's posture is to withhold rather than assume.
3. **Fuel must not contradict.** Petrol vs diesel is categorical on both sides
   and is never a rounding artefact. Null on either side is no signal, not a
   contradiction.
4. **Power must be within POWER_DROP_KW.** Both sides state kW as a number; a
   gap that large is a different engine, not measurement noise.
5. **Model text must clear MODEL_FLOOR**, which is what stops a Golf query
   being answered by a Touareg row.
6. **The row must carry a CO2 value.** A row with none is a valid extraction
   (plan §0) but has nothing to return.

Then a 100-point score over the survivors, and an accept rule of the same
"confirm unless certain" shape as the catalogue matcher: the top must clear
ACCEPT_SCORE, and everything within ACCEPT_MARGIN of it is merged rather than
picked between — see `MAX_ACCEPT_RANGE_G_KM` for why merging, not rejecting, is
the right move for a range-valued answer.
"""

import re
import unicodedata
from dataclasses import dataclass
from datetime import date

from rapidfuzz import fuzz
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.catalogue.brands import brand_from_slug_tokens, canonical_brand
from app.db.models import WikipediaBrandCheck, WikipediaEngineData
from app.wikipedia.validation import period_sort_key

# ---------------------------------------------------------------------------
# Tuning constants. Every one of these is a claim about the data; the comment
# says which claim, so a future change can be argued with rather than guessed
# at. Measured against the 8,739-row first upsert.
# ---------------------------------------------------------------------------

# Score budget, summing to 100. Model text gets the largest single share because
# it is the only signal that says *which car*; the numeric disambiguators say
# which engine within it, and are worth less on their own — an exact 110 kW
# diesel match against the wrong model is worse than useless.
MODEL_TEXT_POINTS = 50.0
POWER_POINTS = 30.0
DISPLACEMENT_POINTS = 12.0
FUEL_POINTS = 8.0

# Power. Listings quote kW converted from PS and rounded, so 110 vs 111 kW is
# the same engine; POWER_EXACT_KW is that rounding band and scores full marks.
# Past POWER_DROP_KW the candidate is dropped outright — within one model's
# range the extremes are 30+ kW apart, so a gap that size is a different engine.
#
# The ramp between them is deliberately steep. Power is the strongest numeric
# disambiguator here — both sides state an exact integer — and within one
# article the neighbouring engine is usually only 4-8 kW away (VW Golf VII
# 1.6 TDI: 66 / 77 / 81 / 85 kW). A gentle ramp left a 4 kW-off engine within
# ACCEPT_MARGIN of the exact one, so the two got merged and produced an
# 82-119 g/km range spanning two different engines. At 8 kW the off-by-one
# engine now falls clearly outside the margin instead.
POWER_EXACT_KW = 3.0
POWER_ZERO_KW = 8.0
POWER_DROP_KW = 25.0

# Displacement. 1995 / 1998 / 2000 cm3 are all "2.0"; 60 cm3 covers that plus
# the usual listing rounding. Ramps to zero at 300 cm3. Never a hard drop —
# listings state displacement inconsistently (or not at all), so it is a
# corroborator, not a gate.
DISPLACEMENT_EXACT_CC = 60.0
DISPLACEMENT_ZERO_CC = 300.0

# Production period vs. registration date, and the grace is deliberately
# ASYMMETRIC because the two directions are not the same event. Registration
# well after production ended is ordinary — unsold stock, a pre-registration, a
# late import — so the trailing window is wide. Registration *before* the model
# went on sale is close to impossible, so the leading window covers only the
# reporting slop in Wikipedia's own month boundaries.
#
# Symmetric 12/12 was tried first and was measurably too loose at the start
# edge: a BMW G20 320d registered 2019-09 pulled in the 2020-03 facelift row
# alongside the correct 2019-03 one and merged their two different ranges.
PERIOD_GRACE_BEFORE_START_MONTHS = 3
PERIOD_GRACE_AFTER_END_MONTHS = 18

# Model text. token_set_ratio over the normalized article title + engine code.
# 60 is deliberately low for a *floor*: it only has to reject a different model,
# and the scoring above it does the discriminating. Raising it starts costing
# real matches on brands whose article titles are chassis codes ("BMW G20"),
# where the only shared token with the listing is the badge in engine_code.
MODEL_FLOOR = 60.0

# A candidate carrying a distinctive extra word the query never mentioned
# ("Sportsvan", "Cabriolet", "Tourer") is probably a different body variant.
# token_set_ratio scores a subset query at 100 and cannot see this, so it is
# charged separately, capped so a chain of them cannot dominate the score.
EXTRA_TOKEN_PENALTY = 6.0
EXTRA_TOKEN_PENALTY_CAP = 18.0

# Model-designator conflict. token_set_ratio cannot see the difference between
# "A4" and "A5", or "C 220 d" and "E 220 d" — one character in a two-character
# token — and scored them within a point of each other, which put an E-Class
# range one rounding error away from being auto-accepted for a C-Class query.
# This is the same class of defect catalogue/matching.py fixes with its
# BMW leading-digit-series override, and it needs its own answer here.
#
# The penalty is sized so that 100 - PENALTY < ACCEPT_SCORE: a designator
# conflict makes auto-acceptance arithmetically impossible, however well
# everything else agrees, while still letting the row be shown as a ranked
# candidate. A hard drop was rejected as too blunt — see _active_designators
# for the case it would break.
DESIGNATOR_MISMATCH_PENALTY = 25.0

# Accept policy.
#
# ACCEPT_SCORE 80 of 100 is reachable essentially only when the text agrees AND
# both numeric disambiguators land in their tolerance band: 90% text (45) +
# power in band (30) + fuel agreeing (8) = 83, or 75% text (37.5) + power (30) +
# displacement (12) + fuel (8) = 87.5. Text agreement alone tops out at 58, so
# a well-named row with contradicting specs can never auto-accept. Compare the
# catalogue matcher's 88, which sits on an entirely different base (raw
# token_set_ratio, not a weighted budget) and is not comparable.
ACCEPT_SCORE = 80.0

# Candidates within this of the top are treated as equally good and MERGED
# rather than chosen between — see resolve()'s docstring.
ACCEPT_MARGIN = 5.0

# Ceiling on the width of the merged range. Measured on the corpus, a single
# row's own co2_max - co2_min is 0 at the median, 15 at p90, 20 at p95 and 31 at
# p99 — so 30 g/km is roughly "as wide as a real single-engine range ever gets".
# A merged range wider than that is not a hint, it is noise dressed as a hint,
# and the honest answer becomes "no estimate available".
MAX_ACCEPT_RANGE_G_KM = 30.0

# Below this, a row is not even worth showing as an alternative.
CANDIDATE_FLOOR = 50.0
MAX_CANDIDATES = 5

# ---------------------------------------------------------------------------

# Tokens that carry no model identity and would otherwise be charged as
# "distinctive extra words". "Baureihe" prefixes every Mercedes article title;
# roman numerals and chassis codes are generation markers that the production-
# date filter already adjudicates far more reliably than text ever could.
_NOISE_TOKENS = frozenset(
    {"baureihe", "typ", "type", "klasse", "class", "serie", "series", "generation"}
)
_ROMAN_RE = re.compile(r"^[ivxl]+$")
_NON_ALNUM = re.compile(r"[^0-9a-z]+")

# Listing fuel strings are messy and multilingual; map only the unambiguous
# ones. Anything unrecognised becomes None -> no fuel signal, which is safer
# than a wrong contradiction. Wikipedia rows only ever hold petrol/diesel, so
# hybrids are read as petrol (the same call the catalogue matcher makes, and
# what the tax treatment assumes) and electric resolves to None here because an
# electric vehicle is PPMV-exempt and never needs this lookup.
_FUEL_MAP: dict[str, str] = {
    "diesel": "diesel",
    "dizel": "diesel",
    "tdi": "diesel",
    "petrol": "petrol",
    "benzin": "petrol",
    "benzine": "petrol",
    "gasoline": "petrol",
    "hybrid": "petrol",
    "hibrid": "petrol",
    "plug-in hybrid": "petrol",
    "mild hybrid": "petrol",
}


def normalize_fuel(raw: str | None) -> str | None:
    """Listing/catalogue fuel string -> 'petrol' | 'diesel' | None."""
    if not raw:
        return None
    return _FUEL_MAP.get(raw.strip().lower())


def normalize_text(value: str | None) -> str:
    """Lowercase, de-diacritic, punctuation -> space, whitespace collapsed.

    Local on purpose. `catalogue.matching.normalize_text` carries a synonym map
    tuned for customs variant blobs, and CLAUDE.md pins that function to the
    ingestion/lookup pair it is shared by — a third caller with different needs
    is how that pairing gets broken. This one is plain and does one job.
    """
    if not value:
        return ""
    decomposed = unicodedata.normalize("NFKD", value.strip().lower()).replace("đ", "d")
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return " ".join(_NON_ALNUM.sub(" ", stripped).split())


def _haystack(title: str, engine_code: str | None, brand: str) -> str:
    """The candidate's searchable text: article title + engine code, brand removed.

    Both halves are needed because de.wikipedia names articles two different
    ways and the listing only ever knows one of them:

      - "Opel Astra K" / "VW Golf VII" — the model name is in the TITLE, while
        engine_code is an internal code ("B16DTC") or a displacement badge
        ("1.6 TDI") that no listing quotes as its model.
      - "BMW G20" / "Mercedes-Benz Baureihe 205" — the title is a chassis code
        no listing ever states, and the sales badge the listing DOES state
        ("320d", "C 220 d") is in engine_code.

    The brand is stripped because every candidate in the pool shares it: leaving
    it in raises every score by the same amount and discriminates nothing, while
    making a short model name look more similar than it is.

    Stripping it by the *canonical* spelling alone is not enough, and getting
    this wrong is expensive. de.wikipedia titles Volkswagen's articles "VW Golf
    VII" and Mercedes' "Mercedes-AMG ...", so matching on the token
    "volkswagen" leaves "vw" behind — a dead token in every haystack that
    diluted a real query's ratio from 86 down to 77 and pushed correct answers
    under ACCEPT_SCORE. The marque prefix is therefore removed the same way
    brand_check reads it: longest recognised prefix, alias-aware.
    """
    title_tokens = normalize_text(title).split()
    _marque, consumed = brand_from_slug_tokens(title_tokens)
    remainder = title_tokens[consumed:]

    text = " ".join(remainder + normalize_text(engine_code or "").split())
    # Belt and braces: also drop the canonical brand's own tokens, which catches
    # a marque named mid-title rather than as a prefix.
    brand_tokens = set(normalize_text(brand).split())
    return " ".join(t for t in text.split() if t not in brand_tokens)


def _extra_distinctive_tokens(query_tokens: frozenset[str], candidate: str) -> int:
    """Count candidate words that look like a body, trim or drivetrain
    distinction the query never mentioned ("Sportsvan", "Cabriolet", "allroad",
    "4MATIC", "xDrive20d", "BlueMotion").

    Two shapes qualify, and the length floors are what keep chassis and
    generation markers out — those are the production-date filter's business,
    not the text's:

      - purely alphabetic, 4+ characters — "allroad", "ecoflex", "sportsvan";
        "g20"/"b9"/"vii" are too short or not alphabetic.
      - mixed alphanumeric, 5+ characters — "4matic", "xdrive20d". The floor is
        5 rather than 4 specifically so that model designators ("320d", "c220")
        and chassis codes ("c257") stay exempt; charging a car for its own
        badge would penalise every correct row equally.

    "4MATIC" was the case that forced the second shape: it is a different
    drivetrain with a genuinely different CO2 figure (C 220 d: 103-109 vs
    127-134), it scored identically to the two-wheel-drive row, and the two
    were merged into a 31 g/km range that then failed the width check — losing
    an answer that was actually available.
    """
    count = 0
    for token in set(candidate.split()) - query_tokens:
        if token in _NOISE_TOKENS or _ROMAN_RE.match(token):
            continue
        if token.isalpha():
            if len(token) >= 4:
                count += 1
        elif len(token) >= 5 and any(c.isalpha() for c in token):
            count += 1
    return count


# Model designators — the short alphanumeric tokens that name a model line.
# Four shapes, each anchored so it cannot swallow ordinary spec text:
#   letter + 1-2 digits   A4, A5, Q2, X3, i3  (also BMW/Audi chassis: G20, B9)
#   3 digits + letter(s)  320d, 520i, 116d    (a sales badge; a PS rating never
#                                              carries a trailing letter)
#   letter + 3 digits     c220, e220          (Mercedes, after the merge below)
#   bare 3 digits         308, 206            (only as the FIRST token — mid-
#                                              string "120" is a PS rating, not
#                                              a Peugeot model)
_DESIGNATOR_RES = (
    re.compile(r"^[a-z]\d{1,2}$"),
    re.compile(r"^\d{3}[a-z]{1,2}$"),
    re.compile(r"^[a-z]\d{3}$"),
)
_BARE_SERIES_RE = re.compile(r"^\d{3}$")


def _designators(text: str) -> frozenset[str]:
    """Model designators present in normalized text.

    Mercedes writes its badge as two tokens ("C 220 d"), so a single-letter
    token immediately followed by a three-digit one is merged first — otherwise
    the class letter is a bare "c" that no pattern can anchor on and the C/E
    distinction stays invisible.
    """
    tokens = text.split()
    merged: list[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        nxt = tokens[index + 1] if index + 1 < len(tokens) else None
        if len(token) == 1 and token.isalpha() and nxt and _BARE_SERIES_RE.match(nxt):
            merged.append(token + nxt)
            index += 2
            continue
        merged.append(token)
        index += 1

    found = set()
    for position, token in enumerate(merged):
        if any(pattern.match(token) for pattern in _DESIGNATOR_RES) or (
            position == 0 and _BARE_SERIES_RE.match(token)
        ):
            found.add(token)
    return frozenset(found)


def _active_designators(
    query_text: str, pool_texts: list[str]
) -> frozenset[str]:
    """Query designators that this candidate pool actually speaks.

    The guard only means something when the corpus uses the same vocabulary the
    query does. Audi's article titles carry the model line ("Audi A4 B9"), so a
    query saying "A4" can legitimately convict a candidate saying "A5". BMW's
    do not: its X-range articles are titled by chassis code ("BMW G01"), the
    string "x3" appears nowhere in the pool, and convicting every BMW row of
    not-being-an-X3 would reject the whole brand on a token the corpus has no
    opinion about.

    Intersecting the query's designators with the pool's is what tells those
    two situations apart, and it is why this is a penalty computed over the
    whole candidate set rather than a per-row hard filter. The X3-style query
    then falls back to text plus the numeric disambiguators — which works,
    because BMW's badge does live in `engine_code`.
    """
    query = _designators(query_text)
    if not query:
        return frozenset()
    pool: set[str] = set()
    for text in pool_texts:
        pool |= _designators(text)
    return frozenset(query & pool)


def _months(value: str | None) -> int | None:
    """'YYYY-MM' or 'YYYY' -> months since year 0, for interval arithmetic."""
    parsed = period_sort_key(value)
    if parsed is None:
        return None
    year, month = parsed
    return year * 12 + (month - 1)


def _ramp(diff: float, exact: float, zero: float, points: float) -> float:
    """`points` inside `exact`, linearly down to 0 at `zero`, 0 beyond."""
    if diff <= exact:
        return points
    if diff >= zero:
        return 0.0
    return points * (zero - diff) / (zero - exact)


@dataclass(frozen=True)
class Vehicle:
    """The query side. Only `brand` is required; everything else narrows."""

    brand: str
    model: str | None = None
    fuel: str | None = None
    power_kw: float | None = None
    registration_date: date | None = None
    displacement_cc: float | None = None


@dataclass(frozen=True)
class Candidate:
    """One `wikipedia_engine_data` row, decoupled from the ORM so
    `rank_candidates` stays pure and testable without a database."""

    brand: str
    model_article_title: str
    engine_code: str | None
    production_start: str | None
    production_end: str | None
    displacement_cc: float | None
    power_kw: float | None
    fuel_type: str | None
    co2_min: float | None
    co2_max: float | None
    source_url: str
    brand_check: str = WikipediaBrandCheck.CONFIRMED.value
    source_order_corrected: bool = False

    @classmethod
    def from_row(cls, row: WikipediaEngineData) -> "Candidate":
        return cls(
            brand=row.brand,
            model_article_title=row.model_article_title,
            engine_code=row.engine_code,
            production_start=row.production_start,
            production_end=row.production_end,
            displacement_cc=row.displacement_cc,
            power_kw=row.power_kw,
            fuel_type=row.fuel_type,
            co2_min=row.co2_min,
            co2_max=row.co2_max,
            source_url=row.source_url,
            brand_check=(
                row.brand_check.value
                if isinstance(row.brand_check, WikipediaBrandCheck)
                else str(row.brand_check)
            ),
            source_order_corrected=bool(row.source_order_corrected),
        )


@dataclass(frozen=True)
class ScoredCandidate:
    candidate: Candidate
    score: float
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class WikipediaCo2Estimate:
    """A CO2 *range*, never a point value (plan §Phase 5), with its provenance.

    `co2_min == co2_max` happens and is fine — that is what the source table
    said. What is not allowed is collapsing a genuine range to one number.
    """

    co2_min: float
    co2_max: float
    source_url: str
    #: every source that contributed to the merged range, deduped, top first
    source_urls: tuple[str, ...]
    brand: str
    model_article_title: str
    engine_code: str | None
    score: float
    #: rows merged into this range (>1 means near-ties were unioned)
    merged_rows: int
    #: True if any contributing row had its co2_min/co2_max swapped at upsert
    source_order_corrected: bool


def _hard_filter(vehicle: Vehicle, candidate: Candidate) -> str | None:
    """Reason the candidate is disqualified, or None if it survives."""
    if candidate.brand_check == WikipediaBrandCheck.UNVERIFIED.value:
        return "brand_unverified"
    if candidate.co2_min is None and candidate.co2_max is None:
        return "no_co2"

    query_fuel = normalize_fuel(vehicle.fuel)
    if query_fuel and candidate.fuel_type and query_fuel != candidate.fuel_type:
        return "fuel_mismatch"

    if (
        vehicle.power_kw is not None
        and candidate.power_kw is not None
        and abs(vehicle.power_kw - candidate.power_kw) > POWER_DROP_KW
    ):
        return "power_gap"

    if vehicle.registration_date is not None:
        start = _months(candidate.production_start)
        end = _months(candidate.production_end)
        if start is None and end is None:
            # The row states no period, so it cannot be confirmed against the
            # registration date. Withhold rather than assume (plan §Phase 5).
            return "no_production_period"
        reg = vehicle.registration_date.year * 12 + (vehicle.registration_date.month - 1)
        if start is not None and reg < start - PERIOD_GRACE_BEFORE_START_MONTHS:
            return "registered_before_production"
        if end is not None and reg > end + PERIOD_GRACE_AFTER_END_MONTHS:
            return "registered_after_production"
    return None


def _score(
    vehicle: Vehicle,
    candidate: Candidate,
    haystack: str,
    active_designators: frozenset[str],
) -> tuple[float, tuple[str, ...]]:
    reasons: list[str] = []
    query_text = normalize_text(vehicle.model)
    query_tokens = frozenset(query_text.split())

    if query_text:
        ratio = fuzz.token_set_ratio(query_text, haystack)
    else:
        # No model text to go on. Award the neutral middle rather than 0 or 100:
        # the numeric disambiguators still have to carry the row over
        # ACCEPT_SCORE, and 50% of the text budget is not enough on its own.
        ratio = 50.0
        reasons.append("no_model_text")

    text_points = MODEL_TEXT_POINTS * ratio / 100.0
    extras = _extra_distinctive_tokens(query_tokens, haystack) if query_text else 0
    if extras:
        text_points -= min(extras * EXTRA_TOKEN_PENALTY, EXTRA_TOKEN_PENALTY_CAP)
        reasons.append(f"extra_tokens={extras}")
    # The candidate positively claims a different model line than the query,
    # in vocabulary this pool demonstrably uses. Charged outside the text
    # budget so it cannot be absorbed by a high token_set_ratio.
    designator_penalty = 0.0
    if active_designators:
        candidate_designators = _designators(haystack)
        if candidate_designators and not (candidate_designators & active_designators):
            designator_penalty = DESIGNATOR_MISMATCH_PENALTY
            reasons.append(
                "designator_conflict="
                + "/".join(sorted(candidate_designators))
                + " vs "
                + "/".join(sorted(active_designators))
            )

    text_points = max(0.0, text_points)

    power_points = 0.0
    if vehicle.power_kw is not None and candidate.power_kw is not None:
        diff = abs(vehicle.power_kw - candidate.power_kw)
        power_points = _ramp(diff, POWER_EXACT_KW, POWER_ZERO_KW, POWER_POINTS)
        reasons.append(f"power_diff={diff:.0f}kW")
    else:
        reasons.append("power_unknown")

    displacement_points = 0.0
    if vehicle.displacement_cc is not None and candidate.displacement_cc is not None:
        diff = abs(vehicle.displacement_cc - candidate.displacement_cc)
        displacement_points = _ramp(
            diff, DISPLACEMENT_EXACT_CC, DISPLACEMENT_ZERO_CC, DISPLACEMENT_POINTS
        )

    fuel_points = 0.0
    query_fuel = normalize_fuel(vehicle.fuel)
    if query_fuel and candidate.fuel_type and query_fuel == candidate.fuel_type:
        fuel_points = FUEL_POINTS

    total = text_points + power_points + displacement_points + fuel_points
    return max(0.0, min(100.0, total) - designator_penalty), tuple(reasons)


def rank_candidates(
    vehicle: Vehicle, candidates: list[Candidate], limit: int = MAX_CANDIDATES
) -> tuple[WikipediaCo2Estimate | None, list[ScoredCandidate]]:
    """Pure, DB-free scoring and accept decision.

    Returns `(estimate_or_None, ranked_candidates)`. The ranked list is returned
    even when the estimate is None, so a caller that wants to show "we found
    these but could not choose" has the material — and so the reason a lookup
    declined is inspectable rather than a bare null.

    **Near-ties are merged, not rejected.** The catalogue matcher refuses to
    auto-accept when candidates within ACCEPT_MARGIN carry different prices,
    because a price has to be one number and picking the wrong one is silent
    corruption. This answer is a *range*, so the equivalent situation has a
    better resolution: take the union of the tied rows' ranges. That is usually
    the same engine measured under NEDC and WLTP, or with a manual and an
    automatic gearbox — genuinely different real values for the same car, and
    reporting 108-124 rather than picking 108 or 124 is the honest reading.
    The safeguard is MAX_ACCEPT_RANGE_G_KM: if the union is wider than any real
    single-engine range, the tie was between genuinely different engines after
    all, and the answer becomes None.
    """
    survivors = [c for c in candidates if _hard_filter(vehicle, c) is None]
    if not survivors:
        return None, []

    # Haystacks once, then the designator vocabulary of the surviving pool —
    # the guard is a property of the whole pool, not of any one row.
    haystacks = {
        id(c): _haystack(c.model_article_title, c.engine_code, c.brand) for c in survivors
    }
    active = _active_designators(normalize_text(vehicle.model), list(haystacks.values()))

    scored = [
        ScoredCandidate(c, *_score(vehicle, c, haystacks[id(c)], active)) for c in survivors
    ]
    scored = [s for s in scored if s.score >= CANDIDATE_FLOOR]
    if not scored:
        return None, []

    # Tie-break on a narrower own-range, so an equally-scoring precise row is
    # preferred as the representative over a vague one.
    def _sort_key(s: ScoredCandidate) -> tuple[float, float]:
        lo, hi = _range_of(s.candidate)
        return (s.score, -(hi - lo))

    scored.sort(key=_sort_key, reverse=True)
    ranked = scored[:limit]

    top = scored[0]
    if top.score < ACCEPT_SCORE:
        return None, ranked

    near_top = [s for s in scored if top.score - s.score <= ACCEPT_MARGIN]

    # Merging is only ever legitimate WITHIN one article. Rows from one article
    # are the same car measured differently (NEDC vs WLTP, manual vs automatic);
    # rows from different articles are different cars, and unioning their ranges
    # invents a figure that describes none of them.
    #
    # This is not hypothetical. "BMW X3 xDrive20d, 140 kW" ties BMW F39 (an X2),
    # F25 (the X3), F26 (an X4) and F48 (an X1) at 80.9-82.0 — the badge and the
    # power are identical across BMW's whole X range, and de.wikipedia titles
    # those articles by chassis code, so no text signal separates them. Without
    # this check the four merged into a confident-looking 121-149 g/km that is
    # not any of the four cars' actual range. A tie spanning articles is real
    # ambiguity, and real ambiguity is what None is for.
    if len({s.candidate.model_article_title for s in near_top}) > 1:
        return None, ranked

    lows, highs = zip(*(_range_of(s.candidate) for s in near_top), strict=True)
    co2_min, co2_max = min(lows), max(highs)
    if co2_max - co2_min > MAX_ACCEPT_RANGE_G_KM:
        return None, ranked

    urls: list[str] = []
    for s in near_top:
        if s.candidate.source_url not in urls:
            urls.append(s.candidate.source_url)

    estimate = WikipediaCo2Estimate(
        co2_min=co2_min,
        co2_max=co2_max,
        source_url=top.candidate.source_url,
        source_urls=tuple(urls),
        brand=top.candidate.brand,
        model_article_title=top.candidate.model_article_title,
        engine_code=top.candidate.engine_code,
        score=top.score,
        merged_rows=len(near_top),
        source_order_corrected=any(s.candidate.source_order_corrected for s in near_top),
    )
    return estimate, ranked


def _range_of(candidate: Candidate) -> tuple[float, float]:
    """A row's own range. One-sided rows (only min or only max stated) are read
    as a point value on the side that exists — never widened to an invented
    bound."""
    low = candidate.co2_min if candidate.co2_min is not None else candidate.co2_max
    high = candidate.co2_max if candidate.co2_max is not None else candidate.co2_min
    return float(low), float(high)  # type: ignore[arg-type]


async def load_candidates(session: AsyncSession, brand: str) -> list[Candidate]:
    """Every usable row filed under `brand` after the cross-check.

    The brand filter is applied in SQL (it is the one hard filter that is a
    plain equality on an indexed column) and `unverified` rows are excluded
    here rather than in Python, so a row whose marque could not be confirmed
    never even enters the pool.
    """
    canonical = canonical_brand(brand) or brand
    stmt = select(WikipediaEngineData).where(
        WikipediaEngineData.brand == canonical,
        WikipediaEngineData.brand_check != WikipediaBrandCheck.UNVERIFIED,
        or_(
            WikipediaEngineData.co2_min.is_not(None),
            WikipediaEngineData.co2_max.is_not(None),
        ),
    )
    rows = (await session.execute(stmt)).scalars().all()
    return [Candidate.from_row(row) for row in rows]


async def resolve_co2_from_wikipedia(
    brand: str,
    model: str | None = None,
    fuel: str | None = None,
    power_kw: float | None = None,
    date: date | None = None,
    *,
    displacement_cc: float | None = None,
    session: AsyncSession | None = None,
) -> WikipediaCo2Estimate | None:
    """Best-effort CO2 range for one vehicle, or None when nothing is certain.

    **What to pass as `model` matters.** Give it the model name plus the engine
    designation — "Golf 1.6 TDI", "320d", "C 220 d", "308 1.6 BlueHDi" — i.e.
    `ListingData.model` plus the engine part of the variant. Do NOT pass the
    whole dealer trim blob: Croatian trim and body wording ("Comfortline",
    "Limuzina", "Dynamique", "Allure") appears nowhere in a de.wikipedia table
    and costs roughly 10 points of text score, which is enough to push a
    correctly-ranked top candidate under ACCEPT_SCORE. It degrades to None
    rather than to a wrong answer, but it is a needless loss of coverage.

    `date` is the vehicle's first-registration date. `displacement_cc` is beyond
    the plan's stated signature but is one of its named disambiguators, so it is
    accepted as a keyword when the caller happens to have it — scrapers usually
    do not, which is why it is optional and carries only 12 of the 100 points.

    Pass `session` to reuse an open one (the intended shape for a future live
    call from `/calculate` on a catalogue-match miss); omit it and a session is
    opened and closed here, which is what the batch/CLI callers want.

    Returning None is a first-class outcome, not a failure: "no Wikipedia
    estimate available" is what the UI shows when the corpus has nothing, and
    it is strictly better than a confident wrong range.
    """
    vehicle = Vehicle(
        brand=brand,
        model=model,
        fuel=fuel,
        power_kw=power_kw,
        registration_date=date,
        displacement_cc=displacement_cc,
    )
    if session is not None:
        candidates = await load_candidates(session, brand)
    else:
        from app.db.session import AsyncSessionLocal

        async with AsyncSessionLocal() as owned:
            candidates = await load_candidates(owned, brand)

    estimate, _ranked = rank_candidates(vehicle, candidates)
    return estimate


async def explain_co2_from_wikipedia(
    vehicle: Vehicle, *, session: AsyncSession | None = None
) -> tuple[WikipediaCo2Estimate | None, list[ScoredCandidate]]:
    """Same lookup, but also returns the ranked candidates and their scores.

    For debugging, tuning and the CLI — a null answer that cannot be
    interrogated is very hard to tune against.
    """
    if session is not None:
        candidates = await load_candidates(session, vehicle.brand)
    else:
        from app.db.session import AsyncSessionLocal

        async with AsyncSessionLocal() as owned:
            candidates = await load_candidates(owned, vehicle.brand)
    return rank_candidates(vehicle, candidates)
