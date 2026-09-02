"""Phase 3 mechanical validation (app/wikipedia/validation.py)."""

import pytest

from app.wikipedia import validation as val


def variant(**overrides) -> dict:
    base = {
        "engine_code": "2.0 TFSI",
        "production_start": "2016-06",
        "production_end": "2019-09",
        "displacement_cc": 1984,
        "power_kw": 185,
        "fuel_type": "petrol",
        "co2_min": 144,
        "co2_max": 152,
    }
    return {**base, **overrides}


def test_a_well_formed_row_passes():
    assert val.validate_variant(variant()).ok


def test_null_co2_passes_cleanly():
    """Plan §0: a table without emissions data is an expected outcome, not an
    error. Flagging it would bury the real failures under thousands of
    non-events."""
    result = val.validate_variant(variant(co2_min=None, co2_max=None))
    assert result.ok and not result.errors


def test_co2_min_above_max_is_flagged():
    result = val.validate_variant(variant(co2_min=200, co2_max=100))
    assert not result.ok
    assert any("co2_min" in e and "co2_max" in e for e in result.errors)


@pytest.mark.parametrize("value", [-5, 900])
def test_implausible_co2_is_flagged(value):
    assert not val.validate_variant(variant(co2_min=value, co2_max=value)).ok


def test_zero_co2_is_accepted():
    """Battery-electric rows in a mixed table legitimately state 0 g/km."""
    assert val.validate_variant(variant(co2_min=0, co2_max=0)).ok


@pytest.mark.parametrize("value", [0, -10, 5000])
def test_implausible_power_is_flagged(value):
    assert not val.validate_variant(variant(power_kw=value)).ok


def test_production_start_after_end_is_flagged():
    result = val.validate_variant(variant(production_start="2019-01", production_end="2016-01"))
    assert not result.ok


def test_open_ended_production_is_fine():
    assert val.validate_variant(variant(production_end=None)).ok


def test_bare_year_periods_are_accepted():
    """German tables often print only a year; demanding YYYY-MM would force the
    model to invent a month, which §0's no-estimation rule forbids."""
    assert val.validate_variant(variant(production_start="2016", production_end="2019")).ok


def test_unparseable_period_is_flagged():
    assert not val.validate_variant(variant(production_start="seit 2016")).ok


def test_non_numeric_values_are_flagged_not_crashed():
    result = val.validate_variant(variant(co2_min="144", power_kw="185 kW"))
    assert not result.ok
    assert len(result.errors) == 2


def test_a_row_can_fail_several_checks_at_once():
    result = val.validate_variant(
        variant(co2_min=600, co2_max=600, power_kw=-1,
                production_start="2020", production_end="2010")
    )
    assert len(result.errors) == 4  # co2_min, co2_max, power_kw, period order
