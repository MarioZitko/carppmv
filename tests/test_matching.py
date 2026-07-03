"""Tests for listing→catalogue matching (app/catalogue/matching.py).

All pure — rank_candidates and the normalizers are DB-free, so no database or
network here. find_match's thin SQL layer is exercised separately by the
integration smoke test (skipped without a real DB).

The cases that matter most for correctness:
- the 320d-vs-330d power guard: a wrong-engine fuzzy hit the listing's power
  contradicts must NOT auto-match (it would inject a wrong as-new price);
- confirm-unless-certain: differently-priced near-ties return CANDIDATES, while
  same-priced rows under different validity periods collapse to one AUTO match.
"""

from datetime import date

from app.catalogue.matching import (
    ACCEPT_SCORE,
    CandidateRow,
    MatchStatus,
    build_match_key,
    normalize_text,
    rank_candidates,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cand(
    *,
    brand="BMW",
    model="serija 3",
    variant="320d xDrive",
    price_eur=50000.0,
    co2=130.0,
    co2_standard="WLTP",
    fuel="diesel",
    power_kw=140.0,
    valid_from=date(2023, 1, 1),
    catalogue_id=1,
) -> CandidateRow:
    return CandidateRow(
        catalogue_id=catalogue_id,
        brand=brand,
        model=model,
        variant=variant,
        match_key=build_match_key(brand, model, variant),
        price_eur=price_eur,
        co2_g_km=co2,
        co2_standard=co2_standard,
        fuel_type=fuel,
        power_kw=power_kw,
        valid_from=valid_from,
    )


# ---------------------------------------------------------------------------
# normalize_text / build_match_key
# ---------------------------------------------------------------------------

def test_normalize_lowercases_and_strips_punctuation():
    assert normalize_text("BMW 320d  xDrive (M-Sport)") == "bmw 320d xdrive m sport"


def test_normalize_strips_croatian_diacritics():
    assert normalize_text("Škoda Octavia RS") == "skoda octavia rs"
    assert normalize_text("Đorđe") == "dorde"


def test_normalize_applies_body_style_synonyms():
    # Limousine→sedan and Touring/Avant/Karavan→wagon collapse cross-source naming
    assert normalize_text("Limousine") == "sedan"
    assert normalize_text("Touring") == "wagon"
    assert normalize_text("Avant") == "wagon"


def test_normalize_none_and_empty():
    assert normalize_text(None) == ""
    assert normalize_text("   ") == ""


def test_build_match_key_dedupes_repeated_tokens_preserving_order():
    # brand 'BMW' + variant repeating 'BMW' shouldn't double-count
    assert build_match_key("BMW", "serija 3", "BMW 320d xDrive") == "bmw serija 3 320d xdrive"


def test_build_match_key_handles_none_parts():
    assert build_match_key("Audi", None, "A4 40 TDI") == "audi a4 40 tdi"


# ---------------------------------------------------------------------------
# rank_candidates — no match / empty
# ---------------------------------------------------------------------------

def test_no_candidates_is_no_match():
    result = rank_candidates(build_match_key("BMW", "serija 3", "320d"), [])
    assert result.status == MatchStatus.NO_MATCH
    assert result.matched is None
    assert result.candidates == []


def test_unrelated_candidate_below_floor_is_no_match():
    query = build_match_key("BMW", "serija 3", "320d xDrive")
    junk = _cand(brand="BMW", model="serija 7", variant="M760e xDrive", power_kw=420.0)
    result = rank_candidates(query, [junk], listing_power_kw=140.0)
    assert result.status == MatchStatus.NO_MATCH


# ---------------------------------------------------------------------------
# rank_candidates — confident auto-match
# ---------------------------------------------------------------------------

def test_exact_key_auto_matches():
    query = build_match_key("BMW", "serija 3", "320d xDrive")
    rows = [
        _cand(variant="320d xDrive", price_eur=50000.0, power_kw=140.0, catalogue_id=1),
        _cand(model="serija 5", variant="530d xDrive", price_eur=72000.0, power_kw=210.0, catalogue_id=2),
    ]
    result = rank_candidates(query, rows, listing_power_kw=140.0)
    assert result.status == MatchStatus.AUTO_MATCHED
    assert result.matched is not None
    assert result.matched.catalogue_id == 1


def test_extra_trim_words_still_auto_match_with_power_agreement():
    # Listing has extra trim noise ('M Sport Pro'); token_set_ratio tolerates it,
    # and matching power confirms the engine.
    query = build_match_key("BMW", "serija 3", "320d xDrive M Sport Pro Edition")
    rows = [
        _cand(variant="320d xDrive", price_eur=50000.0, power_kw=140.0, catalogue_id=1),
        _cand(model="serija 5", variant="520d xDrive", price_eur=60000.0, power_kw=145.0, catalogue_id=2),
    ]
    result = rank_candidates(query, rows, listing_power_kw=140.0)
    assert result.status == MatchStatus.AUTO_MATCHED
    assert result.matched.catalogue_id == 1


# ---------------------------------------------------------------------------
# rank_candidates — the power guard (the headline correctness case)
# ---------------------------------------------------------------------------

def test_power_guard_blocks_wrong_engine_auto_match():
    # Catalogue has ONLY the 330d (190 kW). Listing is a 320d at 140 kW. Without
    # the power guard the near-identical text could auto-match and inject the
    # wrong as-new price; with it, the 50 kW gap must demote it out of AUTO.
    query = build_match_key("BMW", "serija 3", "320d xDrive M Sport")
    only_330d = _cand(variant="330d xDrive", price_eur=62000.0, power_kw=190.0, catalogue_id=9)
    result = rank_candidates(query, [only_330d], listing_power_kw=140.0)
    assert result.status != MatchStatus.AUTO_MATCHED


def test_power_guard_picks_right_engine_among_siblings():
    # 320d and 330d both present; listing power (140) must select the 320d.
    query = build_match_key("BMW", "serija 3", "320d xDrive M Sport")
    rows = [
        _cand(variant="320d xDrive", price_eur=50000.0, power_kw=140.0, catalogue_id=1),
        _cand(variant="330d xDrive", price_eur=62000.0, power_kw=190.0, catalogue_id=2),
    ]
    result = rank_candidates(query, rows, listing_power_kw=140.0)
    assert result.status == MatchStatus.AUTO_MATCHED
    assert result.matched.catalogue_id == 1
    # the wrong-priced sibling must not be the top candidate
    assert result.candidates[0].row.catalogue_id == 1


def test_power_mid_gap_still_demotes_wrong_engine():
    # Real case: a BMW 120i listing (131 kW) parsed with only "120" for model
    # and no useful variant text ("Limousine"), scraped against a catalogue
    # that also has a plain "120" 115 kW trim. 16 kW apart — inside the old
    # flat "untouched" mid band (tolerance 7, penalty gap 25) — so fuzzy text
    # alone left the wrong-engine row within ~1 point of the correct one. The
    # linear ramp between the two bands must pull them decisively apart.
    query = build_match_key("BMW", "120", "Limousine")
    rows = [
        _cand(brand="BMW", model="120i", variant="120i", price_eur=28771.9, power_kw=130.0, catalogue_id=1),
        _cand(
            brand="BMW",
            model="120",
            variant="120_automatski_7stupnjevaPrijenosa_5vata_1499ccm_115kW",
            price_eur=35125.0,
            power_kw=115.0,
            catalogue_id=2,
        ),
    ]
    result = rank_candidates(query, rows, listing_power_kw=131.0)
    assert result.candidates[0].row.catalogue_id == 1
    top, runner_up = result.candidates[0].score, result.candidates[1].score
    assert top - runner_up > 5.0


# ---------------------------------------------------------------------------
# rank_candidates — ambiguous → confirm
# ---------------------------------------------------------------------------

def test_differently_priced_near_ties_return_candidates():
    # Two trims that score about the same but cost different amounts, and no
    # power signal to separate them → must ask the user, not guess.
    query = build_match_key("Audi", "A4", "40 TDI")
    rows = [
        _cand(brand="Audi", model="A4", variant="40 TDI S line", price_eur=48000.0, fuel="diesel", power_kw=None, catalogue_id=1),
        _cand(brand="Audi", model="A4", variant="40 TDI Advanced", price_eur=44000.0, fuel="diesel", power_kw=None, catalogue_id=2),
    ]
    result = rank_candidates(query, rows, listing_power_kw=None)
    assert result.status == MatchStatus.CANDIDATES
    assert result.matched is None
    assert len(result.candidates) == 2


def test_same_price_different_periods_collapse_to_auto():
    # Same variant priced identically across two validity periods → not
    # ambiguous; auto-match and prefer the most recent valid_from.
    query = build_match_key("BMW", "serija 3", "320d xDrive")
    rows = [
        _cand(variant="320d xDrive", price_eur=50000.0, valid_from=date(2022, 1, 1), catalogue_id=1),
        _cand(variant="320d xDrive", price_eur=50000.0, valid_from=date(2024, 1, 1), catalogue_id=2),
    ]
    result = rank_candidates(query, rows, listing_power_kw=140.0)
    assert result.status == MatchStatus.AUTO_MATCHED
    assert result.matched.valid_from == date(2024, 1, 1)
    assert result.matched.catalogue_id == 2


# ---------------------------------------------------------------------------
# rank_candidates — year-aware period selection
# ---------------------------------------------------------------------------

def test_no_year_defaults_to_most_recent_period():
    # Unchanged legacy behaviour when no year is known (e.g. no target year
    # signal at all) — most recent valid_from wins among same-priced periods.
    query = build_match_key("BMW", "serija 3", "320d xDrive")
    rows = [
        _cand(variant="320d xDrive", price_eur=50000.0, valid_from=date(2022, 1, 1), catalogue_id=1),
        _cand(variant="320d xDrive", price_eur=50000.0, valid_from=date(2024, 1, 1), catalogue_id=2),
    ]
    result = rank_candidates(query, rows, listing_power_kw=140.0)
    assert result.matched.catalogue_id == 2


def test_year_picks_closest_validity_period_not_most_recent():
    # Three periods, same variant, different prices per period (realistic —
    # customs prices change yearly). A 2015-registered car must match the
    # 2015 period's price, not silently fall through to the newest one.
    query = build_match_key("BMW", "serija 3", "320d xDrive")
    rows = [
        _cand(variant="320d xDrive", price_eur=40000.0, valid_from=date(2014, 1, 1), catalogue_id=1),
        _cand(variant="320d xDrive", price_eur=45000.0, valid_from=date(2016, 1, 1), catalogue_id=2),
        _cand(variant="320d xDrive", price_eur=52000.0, valid_from=date(2024, 1, 1), catalogue_id=3),
    ]
    result = rank_candidates(query, rows, listing_power_kw=140.0, year=2015)
    assert result.candidates[0].row.catalogue_id == 1


def test_year_tiebreak_survives_truncation_by_limit():
    # The correct-year period must not be discarded by `limit` before the
    # year tiebreak gets to run — it has to be sorted to the front first.
    query = build_match_key("BMW", "serija 3", "320d xDrive")
    rows = [
        _cand(variant="320d xDrive", price_eur=30000.0 + i, valid_from=date(2000 + i, 1, 1), catalogue_id=i)
        for i in range(10)
    ]
    result = rank_candidates(query, rows, listing_power_kw=140.0, year=2001, limit=3)
    assert result.candidates[0].row.catalogue_id == 1


# ---------------------------------------------------------------------------
# Sanity: thresholds wired as expected
# ---------------------------------------------------------------------------

def test_accept_score_is_high_bar():
    # Guard against an accidental loosening of the auto-accept threshold.
    assert ACCEPT_SCORE >= 85.0
