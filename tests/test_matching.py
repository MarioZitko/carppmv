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
    _derive_fuel_family,
    _gearbox_class,
    _resolve_query_fuel,
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
# Fuel / engine-family derivation (the A4 40 TDI vs 40 TFSI fix)
# ---------------------------------------------------------------------------

def test_derive_fuel_family_from_engine_words():
    assert _derive_fuel_family("Audi A4 40 TDI S-tronic") == "diesel"
    assert _derive_fuel_family("Audi A4 40 TFSI S-tronic") == "petrol"
    assert _derive_fuel_family("A5 Sportback 2.0 TFSI quattro") == "petrol"
    # Multi-brand engine words resolve too.
    assert _derive_fuel_family("Renault Megane dCi") == "diesel"
    assert _derive_fuel_family("Peugeot 308 PureTech") == "petrol"


def test_derive_fuel_family_from_numeric_badge():
    # No engine word — fall back to the trailing d/i of the numeric badge.
    assert _derive_fuel_family("BMW 320d xDrive") == "diesel"
    assert _derive_fuel_family("BMW 120i") == "petrol"


def test_derive_fuel_family_none_when_unknown_or_contradictory():
    assert _derive_fuel_family("BMW 1er Advantage") is None
    # A fused AWD 'xd' badge is NOT read as diesel — the trailing letter there is
    # drivetrain noise, so nothing is claimed (the site's fuel field decides).
    assert _derive_fuel_family("BMW 420xd Gran Coupe") is None


def test_resolve_query_fuel_prefers_engine_word_over_site_field():
    # A "TDI" in the text is definitional and overrides a mislabelled site fuel.
    assert _resolve_query_fuel("petrol", "A4", "A4 40 TDI") == "diesel"
    # With no engine word, the site's own fuel field is used (autoscout24 case).
    assert _resolve_query_fuel("petrol", "120i", "Limousine") == "petrol"
    # No engine word and no site fuel (autobid.de) — badge suffix is the last resort.
    assert _resolve_query_fuel(None, "320d", "Gran Coupe") == "diesel"


def test_gearbox_class():
    assert _gearbox_class("Audi A4 40 TDI S tronic") == "auto"
    assert _gearbox_class("BMW 116i ručni 6 stupnjeva") == "manual"
    assert _gearbox_class("Audi A4 40 TDI S line") is None  # 's line' is a trim, not a gearbox


def test_diesel_listing_never_matches_petrol_sibling_at_saturation():
    # The headline A4 regression: an autobid.de "A4 40 TDI" (no site fuel) must
    # not tie with the petrol "40 TFSI" rows. Same tokens, same 150 kW — only the
    # engine family separates them, and it must win decisively even though the
    # fuzzy blob saturates both at 100.
    query = build_match_key("Audi", "A4", "40 TDI S tronic")
    rows = [
        _cand(brand="Audi", model="A4 Limousine", variant="A4 40TDI S tr Select / Diesel/Hybrid",
              price_eur=43445.0, fuel="diesel", power_kw=150.0, catalogue_id=1),
        _cand(brand="Audi", model="A4 Limousine", variant="A4 40TFSI S tr Select / Benzin/Hybrid",
              price_eur=41000.0, fuel="petrol", power_kw=150.0, catalogue_id=2),
    ]
    result = rank_candidates(query, rows, listing_power_kw=150.0, query_model="A4", query_fuel="diesel")
    assert result.candidates[0].row.catalogue_id == 1
    top, second = result.candidates[0].score, result.candidates[1].score
    assert top - second >= 20.0


def test_distinctive_body_demoted_below_plain_sibling_at_saturation():
    # A body-silent "A4 40 TDI" listing must rank the plain sedan above the
    # Allroad it never mentioned, even though both saturate the fuzzy blob at 100.
    query = build_match_key("Audi", "A4", "40 TDI S tronic")
    rows = [
        _cand(brand="Audi", model="A4 Limousine", variant="A4 40TDI S tr Advanced+ / Diesel",
              price_eur=45650.0, fuel="diesel", power_kw=150.0, catalogue_id=1),
        _cand(brand="Audi", model="A4 allroad quattro", variant="A4 Allroad 40TDI quattro S tr Advanced+ / Diesel",
              price_eur=52228.0, fuel="diesel", power_kw=150.0, catalogue_id=2),
    ]
    result = rank_candidates(
        query, rows, listing_power_kw=150.0, query_model="A4", query_fuel="diesel", year=2023,
    )
    assert result.candidates[0].row.catalogue_id == 1
    assert result.candidates[0].score > result.candidates[1].score


def test_bmw_series_name_model_does_not_penalise_trim_query():
    # Regression: BMW/MINI catalogue rows store the recovered series name in
    # `model` ("Serija 3 (F30)"), not the trim (see canonical_schema's banner
    # / legacy-.xls series recovery). A listing or manual search stating just
    # the trim ("320d") must still score this row highly — the model-mismatch
    # guard has to fall back to `variant` (which holds the trim) rather than
    # penalising every BMW/MINI row for not looking like its own model field.
    query = build_match_key("BMW", "320d", "")
    rows = [
        _cand(brand="BMW", model="Serija 3 (F30)", variant="320d",
              price_eur=25000.0, fuel="diesel", power_kw=140.0, catalogue_id=1),
        _cand(brand="BMW", model="Serija 5 (G30)", variant="520d",
              price_eur=35000.0, fuel="diesel", power_kw=140.0, catalogue_id=2),
    ]
    result = rank_candidates(query, rows, listing_power_kw=140.0, query_model="320d", query_fuel="diesel")
    assert result.candidates[0].row.catalogue_id == 1
    assert result.candidates[0].score >= ACCEPT_SCORE
    # The wrong series (520d) must still be penalised via variant's leading digits.
    assert result.candidates[0].score - result.candidates[1].score >= 20.0


def test_distinctive_drivetrain_demoted_below_plain_sibling_at_saturation():
    # A drivetrain-silent "A4 40 TDI" listing (autobid.de title-only variant,
    # no "Version"/"Ausstattung" field) must rank the plain-FWD row above the
    # quattro (AWD) row it never mentioned, even though both saturate at 100.
    query = build_match_key("Audi", "A4", "40 TDI S tronic")
    rows = [
        _cand(brand="Audi", model="A4 Limousine", variant="A4 40TDI S tr Advanced+ / Diesel",
              price_eur=45650.0, fuel="diesel", power_kw=150.0, catalogue_id=1),
        _cand(brand="Audi", model="A4 Limousine", variant="A4 40TDI quattro S tr Advanced+ / Diesel",
              price_eur=48503.75, fuel="diesel", power_kw=150.0, catalogue_id=2),
    ]
    result = rank_candidates(
        query, rows, listing_power_kw=150.0, query_model="A4", query_fuel="diesel", year=2023,
    )
    assert result.candidates[0].row.catalogue_id == 1
    assert result.candidates[0].score > result.candidates[1].score


# ---------------------------------------------------------------------------
# Sanity: thresholds wired as expected
# ---------------------------------------------------------------------------

def test_accept_score_is_high_bar():
    # Guard against an accidental loosening of the auto-accept threshold.
    assert ACCEPT_SCORE >= 85.0
