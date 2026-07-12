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

from app.catalogue.brands import canonical_brand
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

# CO2 disambiguation, same shape as the power ramp above. Only engaged when the
# listing itself already carries a scraped CO2 value (most don't — that's the
# common case this matcher exists to fill in), in which case it's a real signal
# that two rows sharing brand/model/variant/power text are actually different
# engine tunes or model years.
CO2_TOLERANCE_G_KM = 8.0
CO2_BONUS = 3.0
CO2_PENALTY_GAP_G_KM = 40.0
CO2_PENALTY = 15.0

# Year disambiguation — same ramp shape, applied to the gap between the
# listing's first-registration year and a candidate's validity-period start
# year. Needs real weight, not a token nudge: the catalogue holds the same
# model across a decade of validity periods, and early-ingestion periods
# (2013-2015) often carry only a bare "120i"-style variant with no spec detail
# at all, while later periods spell out transmission/doors/displacement. That
# spec detail is real information the listing can't provide, so it can never
# appear on the query side — token_set_ratio then scores the sparse old
# period's near-empty variant as a near-perfect subset match while the
# accurate current-period row, diluted by all that unmatched detail, scores
# markedly lower on text alone. A small year nudge can't overcome a ~25-point
# text gap like that; the bonus/penalty below are sized so a same-year period
# reliably outranks a decade-old one even when the old period's thin text
# otherwise looks like a "better" match. This also keeps the shown percentage
# consistent with the year-aware sort tiebreak rank_candidates performs
# separately for the exact period pick (see its docstring) — that tiebreak
# remains the authority when scores end up tied, this makes them not tie in
# the first place when the years clearly disagree.
YEAR_TOLERANCE_YEARS = 1.0
YEAR_BONUS = 8.0
YEAR_PENALTY_GAP_YEARS = 6.0
YEAR_PENALTY = 27.0

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

# Fuel/engine-family mismatch. The engine badge (TDI/TFSI, or a numeric badge's
# trailing d/i) is the single most reliable cross-source signal after
# brand+model: it appears in the free-text variant on BOTH sides and it *defines*
# the fuel. This penalty is belt-and-suspenders behind the hard fuel filter in
# find_match — if that filter's anti-wipeout guard ever keeps a wrong-fuel row
# (because filtering would empty the set), this still shoves it out of
# auto-accept. Sized like a wrong model: a diesel listing must never silently
# take a petrol row's as-new price, since 40 TDI and 40 TFSI routinely share
# every other token AND the same power_kw (both 150 kW), so no other signal
# separates them.
FUEL_MISMATCH_PENALTY = 35.0

# Gearbox (manual vs automatic) and body-style disagreements, applied only when
# the two sides genuinely contradict — a listing that states "automatik" against
# a manual-only trim, or a plain-model listing against a distinctively-bodied
# candidate (Avant/Allroad/Sportback/Cabrio) it never mentioned. Softer than
# fuel: neither side always spells gearbox/body out, so these must demote a
# mismatch without hard-dropping the many rows that simply stay silent about it.
GEARBOX_MISMATCH_PENALTY = 12.0
BODY_MISMATCH_PENALTY = 12.0

# Character-level fuzz ratio breaks down for BMW/Mercedes/Audi-style numeric
# model codes: "120i" vs "520i" is a single-digit edit on a 4-char string, so
# token_set_ratio scores it ~75 — above MODEL_MATCH_THRESHOLD — even though the
# leading digits are the actual series/class identifier (1er vs 5er) and a
# single-digit difference there is never a rounding/trim variation, unlike the
# same difference in a word like "a3"/"q3". So the leading digit run is checked
# as a hard override: when both models have one and they differ, that's always
# a mismatch regardless of how similar the surrounding text scores.
_LEADING_DIGITS_RE = re.compile(r"^(\d+)")


def _leading_digits(text: str) -> str | None:
    match = _LEADING_DIGITS_RE.match(text.strip())
    return match.group(1) if match else None

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
    # Catalogue rows ingested from 2023-07 onward abbreviate "S tronic" to
    # "S tr" (Audi's dual-clutch transmission), while older rows and listing
    # sites spell it out — confirmed every standalone "tr" token in the
    # catalogue immediately follows "s". Without this, the abbreviated-name
    # 2023+ row for a still-current model loses enough score to "S tronic" ->
    # "S tr" tokenizing as unrelated words that a stale pre-2023 row (same
    # model, wrong generation's kW) outranks it.
    "tr": "tronic",
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

# Splits BMW's drivetrain badge from a *following* fused engine badge
# ("xDrive20d" -> "xDrive 20d", "sDrive18i" -> "sDrive 18i"). Sites commonly
# write the two badges with no separator, and the catalogue itself is
# inconsistent about it (confirmed in the DB: "X1 sDrive23d" fused alongside
# "X3 sDrive 18d" spaced, same drivetrain, same source), so without this a
# fused query is one opaque token that shares nothing with a spaced
# catalogue row and can drop below CANDIDATE_FLOOR entirely even though
# every other field matches.
#
# Deliberately an allowlist of the specific known drivetrain words rather
# than a generic "2+ letters then digit" rule: a generic rule also fires on
# unrelated fused codes elsewhere in the catalogue (gearbox speed counts
# like "DSG7"/"EAT6"/"MT6", factory chassis codes like "0JZ68MXK1") and,
# worse, can make an unrelated digit collide with one already emitted by the
# split and get silently dropped by build_match_key's dedup — regressing
# non-BMW brands to fix a BMW-only problem. Keep this list narrow; extend
# only with badges confirmed to appear fused this way.
#
# Uses a negative lookbehind for a letter rather than \b: the catalogue's raw
# variant text separates fields with underscores ("BMW_X6_xDrive40i_SAV_..."),
# and \b does not treat "_" as a boundary (it's a \w character), so \b would
# silently miss badges embedded mid-string like that one.
_FUSED_DRIVETRAIN_BADGE_RE = re.compile(r"(?<![a-z])(xdrive|sdrive)(?=\d)")


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
    spaced = _FUSED_DRIVETRAIN_BADGE_RE.sub(r"\1 ", spaced)
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


# --- engine / fuel-family derivation ---------------------------------------
# Engine *words* are definitional: their presence fixes the fuel with no
# ambiguity. Kept multi-brand so the same derivation works whether the source is
# an Audi (TDI/TFSI), a VW/Skoda/Seat (TDI/TSI), a PSA (HDi/PureTech), a Renault
# (dCi/TCe), a Ford (TDCi/EcoBoost), a Hyundai/Kia (CRDi/GDi) or a Mercedes
# (CDI). "diesel"/"dizel"/"benzin" also appear verbatim in the catalogue's own
# variant text (e.g. "... / Diesel/Hybrid / 2l ..."), so listing them here makes
# candidate-side derivation rock-solid too.
_DIESEL_ENGINE_WORDS = frozenset({
    "tdi", "tdci", "dci", "cdi", "cdti", "hdi", "bluehdi", "crdi", "bluetec",
    "multijet", "jtd", "d4d", "ddis", "diesel", "dizel",
})
_PETROL_ENGINE_WORDS = frozenset({
    "tfsi", "tsi", "fsi", "tce", "thp", "puretech", "vti", "ecoboost",
    "gdi", "tgdi", "mpi", "benzin", "benzina", "gasoline",
})
# BMW/Mercedes/Audi numeric badge whose trailing letter is the fuel code:
# 320d/420d/120d → diesel, 320i/120i → petrol. Anchored to a digit run so it
# never fires on a stray word. The AWD 'xd'/'xi' that _parse_model_suffix can
# fuse onto a badge ("420xd") is deliberately NOT matched — that trailing letter
# is drivetrain noise, not a reliable fuel code — so the badge path stays a
# weaker fallback consulted only when no engine word and no site fuel exist.
_BADGE_DIESEL_RE = re.compile(r"\b\d{2,3}d\b")
_BADGE_PETROL_RE = re.compile(r"\b\d{2,3}i\b")


def _fuel_from_engine_words(text: str) -> str | None:
    """diesel / petrol from engine words (tdi/tfsi/...), or None when the text
    carries neither or — self-contradictorily — both."""
    tokens = set(normalize_text(text).split())
    diesel = bool(tokens & _DIESEL_ENGINE_WORDS)
    petrol = bool(tokens & _PETROL_ENGINE_WORDS)
    if diesel == petrol:  # neither, or contradictory → don't guess
        return None
    return "diesel" if diesel else "petrol"


def _fuel_from_badge(text: str) -> str | None:
    """diesel / petrol from a numeric badge suffix (320d/320i), or None."""
    blob = normalize_text(text)
    diesel = bool(_BADGE_DIESEL_RE.search(blob))
    petrol = bool(_BADGE_PETROL_RE.search(blob))
    if diesel == petrol:
        return None
    return "diesel" if diesel else "petrol"


def _derive_fuel_family(*texts: str | None) -> str | None:
    """Best fuel guess from brand/model/variant free text: an engine word wins
    (definitional), else the numeric badge suffix. Used for candidate-side
    scoring; the query side goes through _resolve_query_fuel, which also folds in
    the site's own fuel field."""
    joined = " ".join(t for t in texts if t)
    return _fuel_from_engine_words(joined) or _fuel_from_badge(joined)


def _resolve_query_fuel(
    site_fuel: str | None, model: str | None, variant: str | None
) -> str | None:
    """The listing's fuel, most trustworthy source first:

    1. Engine word in model/variant (TDI/TFSI/...) — definitional, so it wins
       even over the site's stated fuel, which is occasionally mislabelled.
    2. The site's own fuel field, when it maps cleanly.
    3. The numeric badge suffix (320d/320i) — last, because model parsing can
       fuse an AWD 'xd'/'xi' onto the badge and muddy the trailing letter.

    Returning None (unknown) is safe: find_match simply skips the fuel filter,
    matching the pre-existing "no fuel → no filter" behaviour."""
    text = f"{model or ''} {variant or ''}"
    return (
        _fuel_from_engine_words(text)
        or _map_listing_fuel(site_fuel)
        or _fuel_from_badge(text)
    )


# --- gearbox / body-style derivation ----------------------------------------
# Manual vs automatic. normalize_text folds "tr" -> "tronic", so an Audi
# "S tr"/"S tronic" and a listing "S-tronic" both surface a "tronic" token here.
_GEARBOX_MANUAL_TOKENS = frozenset({
    "rucni", "manuell", "manual", "schaltgetriebe", "schalt",
})
_GEARBOX_AUTO_TOKENS = frozenset({
    "automatik", "automatski", "automatic", "tiptronic", "tip", "tronic",
    "stronic", "dsg", "pdk", "steptronic", "dct", "multitronic", "edc",
    "powershift",
})


def _gearbox_class(text: str) -> str | None:
    """'manual' / 'auto' / None from transmission tokens. Only a clean signal
    when exactly one class is present. Note "s tronic" tokenizes to "s" +
    "tronic" — the "tronic" token carries the automatic signal, and the stray
    "s" (which also appears in the "s line" trim) is deliberately ignored."""
    tokens = set(normalize_text(text).split())
    manual = bool(tokens & _GEARBOX_MANUAL_TOKENS)
    auto = bool(tokens & _GEARBOX_AUTO_TOKENS)
    if manual == auto:
        return None
    return "manual" if manual else "auto"


# Distinctive (non-sedan) body styles. A sedan is the assumed default, so its
# presence on a candidate is never penalised when the listing stays silent;
# a wagon/coupe/cabrio/allroad/sportback/gran-coupe the listing never named is.
# normalize_text already folds avant/touring/estate/kombi/karavan -> "wagon" and
# limousine/berline -> "sedan", so only the canonical tokens need listing here.
_DISTINCTIVE_BODY_TOKENS = frozenset({
    "wagon", "sportback", "coupe", "cabrio", "cabriolet", "roadster",
    "allroad", "gran", "fastback", "liftback", "suv",
})

# AWD/4WD drivetrain markers — same asymmetric treatment as body style: a
# candidate stating quattro/xDrive/4MATIC etc. that the listing never
# mentioned is a real, price-relevant spec difference, not silence-as-absence.
_DISTINCTIVE_DRIVETRAIN_TOKENS = frozenset({
    "quattro", "xdrive", "4matic", "allrad", "4motion", "awd", "4x4",
})


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


def _ramp_adjustment(diff: float, tolerance: float, penalty_gap: float, bonus: float, penalty: float) -> float:
    """Shared shape for the power/CO2/year disambiguators: +bonus within
    tolerance, -penalty beyond penalty_gap, linear ramp between the two so the
    mid band isn't left flat (see POWER_* tuning-knob comment for why a flat
    mid band lets a wrong-engine row hide within a point of the right one)."""
    if diff <= tolerance:
        return bonus
    if diff >= penalty_gap:
        return -penalty
    span = penalty_gap - tolerance
    frac = (diff - tolerance) / span
    return bonus - frac * (bonus + penalty)


def _score_one(
    query_key: str,
    cand: CandidateRow,
    listing_power_kw: float | None,
    query_model: str | None = None,
    listing_co2_g_km: float | None = None,
    year: int | None = None,
    query_fuel: str | None = None,
    query_gearbox: str | None = None,
    query_tokens: frozenset[str] | None = None,
) -> float:
    base = float(fuzz.token_set_ratio(query_key, cand.match_key))

    if query_model and cand.model:
        model_score = fuzz.token_set_ratio(normalize_text(query_model), normalize_text(cand.model))
        q_digits = _leading_digits(query_model)
        c_digits = _leading_digits(cand.model)
        digits_mismatch = q_digits is not None and c_digits is not None and q_digits != c_digits
        if model_score < MODEL_MATCH_THRESHOLD or digits_mismatch:
            base = max(0.0, base - MODEL_MISMATCH_PENALTY)

    # Positive (bonus) and negative (penalty) adjustments are kept apart on
    # purpose: bonuses are capped so they can't push the score past 100, but
    # penalties always subtract afterwards. token_set_ratio already saturates at
    # 100 for any candidate whose text is a superset of the sparse query (a plain
    # "A4 40 TDI" is a subset of both the sedan AND the Allroad row), so the
    # whole job of the body/gearbox/fuel penalties is to break exactly those
    # saturated ties — if a +8 year bonus and +4 power bonus were allowed to lift
    # the base over 100 first, the clamp would silently swallow a -12 body
    # penalty and the tie would never break. Capping bonuses at 100 keeps them
    # useful for separating sub-100 rows (the stale-old-period case) while
    # letting penalties bite at saturation.
    bonus = 0.0
    penalty = 0.0

    # Fuel/engine family — the candidate's stored fuel_type is authoritative
    # (ingested from the source Excel). A contradiction with the listing's
    # derived fuel is a wrong-engine match; penalise it hard.
    if query_fuel is not None and cand.fuel_type is not None and query_fuel != cand.fuel_type:
        penalty += FUEL_MISMATCH_PENALTY

    # Gearbox — demote a manual/automatic contradiction, but only when both
    # sides actually state a gearbox (either is None → no signal → no penalty).
    if query_gearbox is not None:
        cand_gearbox = _gearbox_class(cand.match_key)
        if cand_gearbox is not None and cand_gearbox != query_gearbox:
            penalty += GEARBOX_MISMATCH_PENALTY

    # Body style — demote a candidate carrying a distinctive body (Avant/Allroad/
    # Sportback/Coupe/Cabrio...) the listing never mentioned. Sedan is the
    # assumed default and is never in _DISTINCTIVE_BODY_TOKENS, so a plain-sedan
    # candidate is never penalised against a body-silent listing.
    if query_tokens is not None:
        cand_tokens = set(cand.match_key.split())
        extra_bodies = (cand_tokens & _DISTINCTIVE_BODY_TOKENS) - query_tokens
        if extra_bodies:
            penalty += BODY_MISMATCH_PENALTY

        extra_drivetrain = (cand_tokens & _DISTINCTIVE_DRIVETRAIN_TOKENS) - query_tokens
        if extra_drivetrain:
            penalty += BODY_MISMATCH_PENALTY

    def _accumulate(signed: float) -> None:
        nonlocal bonus, penalty
        if signed >= 0:
            bonus += signed
        else:
            penalty += -signed

    if listing_power_kw is not None and cand.power_kw is not None:
        diff = abs(listing_power_kw - cand.power_kw)
        _accumulate(_ramp_adjustment(diff, POWER_TOLERANCE_KW, POWER_PENALTY_GAP_KW, POWER_BONUS, POWER_PENALTY))

    if listing_co2_g_km is not None and cand.co2_g_km is not None:
        diff = abs(listing_co2_g_km - cand.co2_g_km)
        _accumulate(_ramp_adjustment(diff, CO2_TOLERANCE_G_KM, CO2_PENALTY_GAP_G_KM, CO2_BONUS, CO2_PENALTY))

    if year is not None and cand.valid_from is not None:
        diff = abs(year - cand.valid_from.year)
        _accumulate(_ramp_adjustment(diff, YEAR_TOLERANCE_YEARS, YEAR_PENALTY_GAP_YEARS, YEAR_BONUS, YEAR_PENALTY))

    return max(0.0, min(100.0, base + bonus) - penalty)


def rank_candidates(
    query_key: str,
    candidates: list[CandidateRow],
    listing_power_kw: float | None = None,
    limit: int = MAX_CANDIDATES,
    query_model: str | None = None,
    year: int | None = None,
    listing_co2_g_km: float | None = None,
    query_fuel: str | None = None,
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

    # Query-side gearbox/body derived once from the (normalized) query_key, then
    # reused for every candidate — the listing side never changes across the set.
    query_gearbox = _gearbox_class(query_key)
    query_tokens = frozenset(query_key.split())

    scored = [
        ScoredCandidate(
            c,
            _score_one(
                query_key, c, listing_power_kw, query_model, listing_co2_g_km,
                year, query_fuel, query_gearbox, query_tokens,
            ),
        )
        for c in candidates
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


_VARIANT_KW_SUFFIX_RE = re.compile(r"(\d+)(kw)$", re.IGNORECASE)


def _correct_variant_kw_suffix(variant: str | None, power_kw: float | None) -> str | None:
    """Some BMW source spreadsheets freeze a "...140kW" figure into the
    free-text variant description that never gets updated when the numeric
    SNAGA (kW) column is later revised (confirmed: ~145 BMW rows carry this
    mismatch, always disagreeing with the row's own power_kw, which matches
    BMW's published spec sheets — the frozen text is what's wrong). The UI
    shows the description and power_kw side by side, so a stale suffix reads
    as a contradiction; this is display-only, match_key/scoring never touch
    this field."""
    if not variant or power_kw is None:
        return variant
    match = _VARIANT_KW_SUFFIX_RE.search(variant)
    if not match or int(match.group(1)) == round(power_kw):
        return variant
    return variant[: match.start(1)] + str(round(power_kw)) + variant[match.end(1):]


def _to_candidate(row: Catalogue) -> CandidateRow:
    return CandidateRow(
        catalogue_id=row.id,
        brand=row.brand,
        model=row.model,
        variant=_correct_variant_kw_suffix(row.variant, row.power_kw),
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
    co2_g_km: float | None = None,
) -> MatchResult:
    """Fetch this brand's catalogue rows and rank them against the listing.

    Brand is a hard filter (case-insensitive); at O(thousands) total rows a
    per-brand fetch is a handful to a few hundred rows — trivial for the
    human-paced, one-listing-at-a-time PPMV flow. Fuel narrows further only when
    it maps cleanly and doesn't wipe out every candidate. `year` (first
    registration year, or the year the user typed in a manual search) picks
    which validity period wins among otherwise-identical rows, and also nudges
    the score toward that period so the shown percentage agrees with the pick.
    `co2_g_km` (only when the listing itself already states one) is an extra
    disambiguator alongside power_kw — see rank_candidates()."""
    # Normalize the listing's brand to the catalogue's canonical spelling before
    # the hard filter, so a site that says "Mercedes" (or "VW") still hits the
    # stored "Mercedes-Benz" ("Volkswagen") rows. Same vocabulary the catalogue
    # is ingested against, so the two sides are guaranteed comparable.
    brand = canonical_brand(brand) or brand
    query_key = build_match_key(brand, model, variant)

    stmt = select(Catalogue).where(func.lower(Catalogue.brand) == brand.strip().lower())
    rows = (await session.execute(stmt)).scalars().all()
    candidates = [_to_candidate(r) for r in rows]

    # Resolve the listing's fuel from the engine badge first, the site's fuel
    # field second — so a diesel "A4 40 TDI" from autobid.de (which never exposes
    # a fuel field) still hard-filters out the petrol "A4 40 TFSI" rows it would
    # otherwise tie with at 100 (same tokens, same 150 kW). See _resolve_query_fuel.
    query_fuel = _resolve_query_fuel(fuel_type, model, variant)
    if query_fuel is not None:
        narrowed = [c for c in candidates if c.fuel_type == query_fuel]
        if narrowed:  # don't let an over-strict fuel filter erase a real match
            candidates = narrowed

    return rank_candidates(
        query_key,
        candidates,
        listing_power_kw=power_kw,
        limit=limit,
        query_model=model,
        year=year,
        listing_co2_g_km=co2_g_km,
        query_fuel=query_fuel,
    )
