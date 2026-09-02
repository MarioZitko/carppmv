"""Phase 5's matcher — pure scoring and the accept/reject decision.

Exercises `rank_candidates` directly, which is DB-free by design (the same
split as catalogue/matching.py's rank_candidates vs find_match). Every fixture
below is shaped from a real `wikipedia_engine_data` row.

The negative cases matter more than the positive ones here: a null answer costs
a user one manual CO2 entry, and a confident wrong range corrupts a tax
calculation silently.
"""

from datetime import date

import pytest

from app.wikipedia.co2_lookup import (
    ACCEPT_SCORE,
    DESIGNATOR_MISMATCH_PENALTY,
    Candidate,
    Vehicle,
    normalize_fuel,
    rank_candidates,
)


def make(
    title: str,
    engine_code: str | None,
    power_kw: float | None,
    co2: tuple[float | None, float | None],
    *,
    brand: str = "BMW",
    start: str | None = "2015-01",
    end: str | None = "2020-01",
    fuel: str | None = "diesel",
    displacement_cc: float | None = None,
    brand_check: str = "confirmed",
) -> Candidate:
    return Candidate(
        brand=brand,
        model_article_title=title,
        engine_code=engine_code,
        production_start=start,
        production_end=end,
        displacement_cc=displacement_cc,
        power_kw=power_kw,
        fuel_type=fuel,
        co2_min=co2[0],
        co2_max=co2[1],
        source_url=f"https://de.wikipedia.org/wiki/{title.replace(' ', '_')}",
        brand_check=brand_check,
    )


# --------------------------------------------------------------------------
# Confident matches
# --------------------------------------------------------------------------


def test_confident_match_returns_a_range_and_its_source() -> None:
    """BMW G20 320d: the badge lives in engine_code, the title is a chassis
    code no listing ever states. Matching has to work off the combination."""
    rows = [
        make("BMW G20", "320d", 140, (105, 107), start="2020-03", end="2024-05"),
        make("BMW G20", "320d xDrive", 140, (114, 117), start="2020-03", end="2024-05"),
    ]
    vehicle = Vehicle("BMW", "320d", "diesel", 140, date(2021, 6, 1))
    estimate, ranked = rank_candidates(vehicle, rows)

    assert estimate is not None
    assert (estimate.co2_min, estimate.co2_max) == (105, 107)
    assert estimate.source_url.endswith("BMW_G20")
    assert estimate.score >= ACCEPT_SCORE
    assert ranked[0].candidate.engine_code == "320d"


def test_range_is_never_collapsed_to_a_point() -> None:
    rows = [make("BMW G20", "320d", 140, (105, 122), start="2019-03", end="2024-05")]
    estimate, _ = rank_candidates(
        Vehicle("BMW", "320d", "diesel", 140, date(2021, 6, 1)), rows
    )
    assert estimate is not None
    assert estimate.co2_min == 105
    assert estimate.co2_max == 122


def test_near_ties_within_one_article_are_merged_not_chosen_between() -> None:
    """Same car, two measurement regimes. The union is the honest answer —
    picking one of them would be inventing precision."""
    rows = [
        make("BMW G20", "320d", 140, (105, 107), start="2019-03", end="2024-05"),
        make("BMW G20", "320d", 140, (115, 122), start="2019-03", end="2024-05"),
    ]
    estimate, _ = rank_candidates(
        Vehicle("BMW", "320d", "diesel", 140, date(2021, 6, 1)), rows
    )
    assert estimate is not None
    assert (estimate.co2_min, estimate.co2_max) == (105, 122)
    assert estimate.merged_rows == 2
    assert len(estimate.source_urls) == 1


# --------------------------------------------------------------------------
# The refusals — each of these was a real wrong answer before its guard existed
# --------------------------------------------------------------------------


def test_near_ties_across_articles_are_never_merged() -> None:
    """The X3 case. BMW's whole X range shares the "xDrive20d" badge and 140 kW,
    and de.wikipedia titles those articles by chassis code, so nothing in the
    text separates an X1 from an X4. Merging them produced a confident-looking
    121-149 g/km that described none of the four cars."""
    rows = [
        make("BMW F39", "xDrive20d", 140, (121, 126), start="2018-03", end="2020-01"),
        make("BMW F25", "xDrive20d", 140, (136, 136), start="2014-04", end=None),
        make("BMW F26", "xDrive20d", 140, (143, 143), start="2014-07", end="2018-03"),
        make("BMW G02", "xDrive20d", 140, (142, 149), start="2018-03", end="2021-08"),
    ]
    estimate, ranked = rank_candidates(
        Vehicle("BMW", "X3 xDrive20d", "diesel", 140, date(2019, 4, 1)), rows
    )
    assert estimate is None
    # Still ranked, so a caller can show "we found these but could not choose".
    assert ranked


def test_model_designator_conflict_cannot_auto_accept() -> None:
    """"C 220 d" vs "E 220 d" is one character, and token_set_ratio scored them
    within a point of each other — putting an E-Class range one rounding error
    away from being served for a C-Class query."""
    rows = [
        make(
            "Mercedes-Benz Baureihe 213", "E 220 d", 143, (102, 112),
            brand="Mercedes-Benz", start="2016-07", end="2019-04",
        ),
        make(
            "Mercedes-Benz Baureihe 205", "C 220 d", 143, (117, 126),
            brand="Mercedes-Benz", start="2018-07", end="2023-03",
        ),
    ]
    estimate, ranked = rank_candidates(
        Vehicle("Mercedes-Benz", "C 220 d", "diesel", 143, date(2020, 3, 1)), rows
    )
    assert estimate is not None
    assert (estimate.co2_min, estimate.co2_max) == (117, 126)
    # The E-Class row is demoted below the C-Class one, not merely tied.
    by_code = {s.candidate.engine_code: s.score for s in ranked}
    assert by_code["C 220 d"] - by_code["E 220 d"] >= DESIGNATOR_MISMATCH_PENALTY


def test_designator_guard_stays_quiet_when_the_pool_lacks_the_vocabulary() -> None:
    """"X3" appears nowhere in BMW's chassis-code-titled pool, so convicting
    every BMW row of not-being-an-X3 would reject the brand on a token the
    corpus has no opinion about. The guard must not fire at all here."""
    rows = [make("BMW G01", "xDrive20d", 140, (140, 146), start="2017-11", end="2021-08")]
    estimate, ranked = rank_candidates(
        Vehicle("BMW", "X3 xDrive20d", "diesel", 140, date(2019, 4, 1)), rows
    )
    assert ranked
    assert not any("designator_conflict" in r for r in ranked[0].reasons)
    assert estimate is not None


def test_production_period_is_a_hard_filter() -> None:
    rows = [make("BMW G20", "320d", 140, (105, 107), start="2019-03", end="2024-05")]
    estimate, ranked = rank_candidates(
        Vehicle("BMW", "320d", "diesel", 140, date(1998, 1, 1)), rows
    )
    assert estimate is None
    assert ranked == []


def test_period_grace_is_asymmetric() -> None:
    """Registration after production ended is ordinary (unsold stock); before it
    started is close to impossible. Symmetric grace pulled a facelift row into a
    pre-facelift car's answer."""
    row = [make("BMW G20", "320d", 140, (105, 107), start="2020-03", end="2020-12")]
    query = lambda d: rank_candidates(  # noqa: E731
        Vehicle("BMW", "320d", "diesel", 140, d), row
    )[0]
    assert query(date(2022, 1, 1)) is not None   # 13 months after end: allowed
    assert query(date(2019, 9, 1)) is None       # 6 months before start: not


def test_fuel_contradiction_is_a_hard_filter() -> None:
    rows = [make("BMW G20", "320d", 140, (105, 107), start="2019-03", end="2024-05")]
    estimate, ranked = rank_candidates(
        Vehicle("BMW", "320i", "petrol", 140, date(2021, 6, 1)), rows
    )
    assert estimate is None
    assert ranked == []


def test_power_gap_beyond_tolerance_is_a_hard_filter() -> None:
    rows = [make("BMW G20", "320d", 140, (105, 107), start="2019-03", end="2024-05")]
    estimate, ranked = rank_candidates(
        Vehicle("BMW", "320d", "diesel", 80, date(2021, 6, 1)), rows
    )
    assert estimate is None
    assert ranked == []


def test_unverified_brand_rows_never_enter_the_pool() -> None:
    """The Eurovan / Roewe case, enforced in the pure layer too — load_candidates
    also filters in SQL, but a caller assembling candidates by hand must not be
    able to slip one past."""
    rows = [
        make(
            "Eurovan (PSA/Fiat)", "2.0", 89, (247, 252),
            brand="Peugeot", start="1994-01", end="2001-12",
            brand_check="unverified",
        )
    ]
    estimate, ranked = rank_candidates(
        Vehicle("Peugeot", "806 2.0", "petrol", 89, date(1998, 5, 1)), rows
    )
    assert estimate is None
    assert ranked == []


def test_rows_without_co2_are_not_candidates() -> None:
    rows = [make("BMW G20", "320d", 140, (None, None), start="2019-03", end="2024-05")]
    estimate, ranked = rank_candidates(
        Vehicle("BMW", "320d", "diesel", 140, date(2021, 6, 1)), rows
    )
    assert estimate is None
    assert ranked == []


def test_row_without_a_production_period_is_withheld_when_a_date_is_known() -> None:
    rows = [make("BMW G20", "320d", 140, (105, 107), start=None, end=None)]
    assert rank_candidates(
        Vehicle("BMW", "320d", "diesel", 140, date(2021, 6, 1)), rows
    ) == (None, [])
    # …but is perfectly usable when the caller has no date to check it against.
    estimate, _ = rank_candidates(Vehicle("BMW", "320d", "diesel", 140, None), rows)
    assert estimate is not None


def test_absurdly_wide_merged_range_is_refused() -> None:
    """A hint of "45-250 g/km" is noise wearing a hint's clothes."""
    rows = [
        make("BMW G20", "320d", 140, (45, 60), start="2019-03", end="2024-05"),
        make("BMW G20", "320d", 140, (240, 250), start="2019-03", end="2024-05"),
    ]
    estimate, ranked = rank_candidates(
        Vehicle("BMW", "320d", "diesel", 140, date(2021, 6, 1)), rows
    )
    assert estimate is None
    assert ranked


def test_no_candidates_at_all() -> None:
    assert rank_candidates(Vehicle("Chevrolet", "Captiva"), []) == (None, [])


# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Diesel", "diesel"),
        ("dizel", "diesel"),
        ("Benzin", "petrol"),
        ("petrol", "petrol"),
        # Wikipedia rows hold only petrol/diesel; hybrids read as petrol, the
        # same call the catalogue matcher and the tax treatment make.
        ("Hybrid", "petrol"),
        ("Elektro", None),
        (None, None),
        ("", None),
    ],
)
def test_normalize_fuel(raw: str | None, expected: str | None) -> None:
    assert normalize_fuel(raw) == expected
