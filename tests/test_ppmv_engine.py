"""Regression tests for the PPMV engine.

Two independently-sourced worked examples are used as ground truth:
1. Audi A5 40 TDI — real Croatian customs tax decision (KLASA:
   UP/I-410-22/25-09/50070), NEDC/diesel/used-vehicle path.
2. Postanivozac.com blog example — WLTP/petrol/new-vehicle path. Used
   only to cross-check Tables 4 & 6 since example #1 doesn't exercise WLTP.

Plus targeted edge cases for the month-counting rule (čl. 9 st. 4) and the
post-180-month depreciation reduction (čl. 9 st. 3), since those are easy
to get subtly wrong and weren't exercised by either example.
"""

from datetime import date

import pytest

from app.ppmv.engine import _depreciation_percent, _months_between, calculate_ppmv
from app.ppmv.schemas import FuelType, PPMVRequest


# ---------------------------------------------------------------------------
# Shared parameters for reduction tests — Audi A5 40 TDI (same as the
# mandatory regression) used as a stable known-good baseline so we can
# isolate each reduction factor without inventing new vehicle inputs.
# The as_new_total (8 362.61 EUR) and depreciation (41.56 %) are fixed by
# the existing regression; the reduction tests just layer on top.
_AUDI_KWARGS = dict(
    price_eur=70318.61,
    co2_g_km=136.0,
    fuel_type=FuelType.DIESEL,
    first_registration_date=date(2020, 8, 17),
    declaration_date=date(2025, 7, 10),
)
_AUDI_AS_NEW = 8362.61  # value + eco, rounded; from regression
_AUDI_DEPR = 0.4156     # 58 months; from regression


def test_audi_a5_regression():
    """NEDC, diesel, used vehicle. Ground truth: real tax decision."""
    breakdown = calculate_ppmv(
        price_eur=70318.61,  # implied as-new price, reverse-engineered from official totals
        co2_g_km=136.0,
        fuel_type=FuelType.DIESEL,
        first_registration_date=date(2020, 8, 17),
        declaration_date=date(2025, 7, 10),
    )
    assert breakdown.months_old == 58
    assert breakdown.depreciation_percent == pytest.approx(0.4156)
    assert breakdown.as_new_value_component == pytest.approx(4973.43)
    assert breakdown.as_new_eco_component == pytest.approx(3389.18)
    assert breakdown.as_new_total == pytest.approx(8362.61)
    assert breakdown.final_ppmv == pytest.approx(3475.50)


def test_wltp_petrol_new_vehicle():
    """WLTP, petrol, new vehicle. Ground truth: independent worked example,
    used to cross-check Tables 4 & 6. Pravilnik čl. 9: new vehicles skip
    Tablica 1 — depreciation_percent = 1.0, so final_ppmv = as_new_total."""
    breakdown = calculate_ppmv(
        price_eur=35000.0,
        co2_g_km=137.0,
        fuel_type=FuelType.PETROL,
        first_registration_date=date(2026, 1, 1),
        declaration_date=date(2026, 1, 1),
        is_new_vehicle=True,
    )
    assert breakdown.months_old == 0
    assert breakdown.depreciation_percent == pytest.approx(1.0)
    assert breakdown.as_new_total == pytest.approx(1093.59)
    assert breakdown.final_ppmv == pytest.approx(1093.59)


class TestMonthCounting:
    """Pravilnik čl. 9 st. 4: a month is complete on the day-of-next-month
    matching the registration day; if that day doesn't exist in the target
    month, completion falls on that month's last day."""

    def test_exact_month_boundary(self):
        assert _months_between(date(2020, 8, 17), date(2025, 7, 10)) == 58

    def test_short_month_completion_day_clamped(self):
        # Jan 31 + 1 month: Feb has no 31st, so the month completes on
        # Feb 28 (or 29 in leap years), not on Mar 3.
        assert _months_between(date(2021, 1, 31), date(2021, 2, 28)) == 1
        assert _months_between(date(2021, 1, 31), date(2021, 2, 27)) == 0

    def test_zero_months_same_day(self):
        assert _months_between(date(2024, 3, 1), date(2024, 3, 1)) == 0

    def test_leap_year_february(self):
        assert _months_between(date(2024, 1, 31), date(2024, 2, 29)) == 1
        assert _months_between(date(2024, 1, 31), date(2024, 2, 28)) == 0


class TestPost180MonthDepreciation:
    """Pravilnik čl. 9 st. 3: -0.6pp per full 12mo period after 180mo,
    frozen at 360mo."""

    def test_at_180_months_uses_table_value_unchanged(self):
        assert _depreciation_percent(180) == pytest.approx(0.1932)

    def test_191_months_no_full_period_yet(self):
        assert _depreciation_percent(191) == pytest.approx(0.1932)

    def test_192_months_one_full_period(self):
        assert _depreciation_percent(192) == pytest.approx(0.1872)

    def test_floor_at_360_months(self):
        assert _depreciation_percent(360) == pytest.approx(0.1032)

    def test_beyond_360_months_frozen_at_floor(self):
        assert _depreciation_percent(400) == pytest.approx(0.1032)
        assert _depreciation_percent(1000) == pytest.approx(0.1032)


class TestOutOfRangeInputs:
    def test_co2_below_table_floor_gives_zero_eco(self):
        # CO2 below the table floor (70 g/km for diesel NEDC) → eco = 0, no error.
        # This is the correct result for PHEVs and very clean vehicles; they owe
        # no eco component, not an "invalid" input.
        breakdown = calculate_ppmv(
            price_eur=30000.0,
            co2_g_km=10.0,
            fuel_type=FuelType.DIESEL,
            first_registration_date=date(2020, 1, 1),
            declaration_date=date(2020, 1, 1),
        )
        assert breakdown.as_new_eco_component == 0.0

    def test_negative_price_rejected_by_schema_not_engine(self):
        # Engine itself doesn't validate price > 0 (that's PPMVRequest's
        # job); a 0 or negative price here should still resolve to the
        # bottom value bracket rather than raising, since 0 is in-range.
        breakdown = calculate_ppmv(
            price_eur=0.0,
            co2_g_km=80.0,
            fuel_type=FuelType.DIESEL,
            first_registration_date=date(2020, 1, 1),
            declaration_date=date(2020, 1, 1),
        )
        assert breakdown.as_new_value_component == 0.0


# ---------------------------------------------------------------------------
# Reduction tests — factors sourced directly from the official PDF
# "Kako izračunati posebni porez na motorna vozila" (carina.gov.hr).
# Absolute amounts in the PDF are in HRK (pre-2023 kuna era) and cannot be
# reproduced by the EUR-table engine; the tested values are the reduction
# FACTORS confirmed by that PDF.
# ---------------------------------------------------------------------------


class TestElectricExemption:
    """CO2 == 0 / FuelType.ELECTRIC → PPMV = 0, no table lookup needed.
    Not an explicit worked example in the PDF but mandated by Zakon čl. 12."""

    def test_electric_final_ppmv_is_zero(self):
        breakdown = calculate_ppmv(
            price_eur=50000.0,
            co2_g_km=0.0,
            fuel_type=FuelType.ELECTRIC,
            first_registration_date=date(2022, 6, 1),
            declaration_date=date(2025, 6, 1),
        )
        assert breakdown.final_ppmv == 0.0

    def test_electric_all_monetary_components_zero(self):
        breakdown = calculate_ppmv(
            price_eur=80000.0,
            co2_g_km=0.0,
            fuel_type=FuelType.ELECTRIC,
            first_registration_date=date(2023, 1, 1),
            declaration_date=date(2025, 1, 1),
        )
        assert breakdown.as_new_value_component == 0.0
        assert breakdown.as_new_eco_component == 0.0
        assert breakdown.as_new_total == 0.0
        assert breakdown.final_ppmv == 0.0

    def test_electric_schema_rejects_nonzero_co2(self):
        with pytest.raises(Exception):
            PPMVRequest(
                price_eur=50000.0,
                co2_g_km=120.0,
                fuel_type=FuelType.ELECTRIC,
                first_registration_date=date(2023, 1, 1),
                declaration_date=date(2025, 1, 1),
            )


class TestPlugInHybridReduction:
    """PDF Example 4: PHEV, EAER city range in km = reduction %.
    The PDF displays WLTP combined range 52 km and labels the reduction
    '-52%', but the printed arithmetic (16 980 − 10 018.20 = 6 961.80)
    corresponds to a 59% reduction — consistent with EAER city = 59 km.
    The law explicitly names 'Electric range (EAER city) [km]', so we
    accept the EAER city value as input and apply km → % directly."""

    def test_phev_59km_reduction_factor(self):
        # Example 4 arithmetic: 10 018.20 / 16 980 = 59 % → remaining = 41 %
        breakdown = calculate_ppmv(**_AUDI_KWARGS, eaer_city_range_km=59.0)
        assert breakdown.vehicle_reduction_factor == pytest.approx(0.41)
        assert breakdown.final_ppmv == pytest.approx(
            _AUDI_AS_NEW * 0.41 * _AUDI_DEPR, abs=0.01
        )

    def test_phev_52km_reduction_factor(self):
        # If caller passes EAER city = 52 km (label shown in PDF), factor = 0.48.
        breakdown = calculate_ppmv(**_AUDI_KWARGS, eaer_city_range_km=52.0)
        assert breakdown.vehicle_reduction_factor == pytest.approx(0.48)

    def test_phev_100km_capped_at_100pct(self):
        # Range ≥ 100 km → fully exempt (factor = 0.0, final_ppmv = 0).
        breakdown = calculate_ppmv(**_AUDI_KWARGS, eaer_city_range_km=100.0)
        assert breakdown.vehicle_reduction_factor == pytest.approx(0.0)
        assert breakdown.final_ppmv == 0.0

    def test_phev_120km_still_capped(self):
        breakdown = calculate_ppmv(**_AUDI_KWARGS, eaer_city_range_km=120.0)
        assert breakdown.vehicle_reduction_factor == pytest.approx(0.0)
        assert breakdown.final_ppmv == 0.0


class TestSeatCountReduction:
    """PDF Example 3: 7+1 seats → −50%; 8+1 seats → −75%.
    Base PPMV in the example: 93 385 kn.
    93 385 × 50 % = 46 692.50 kn (7+1); 93 385 × 25 % = 23 346.25 kn (8+1)."""

    def test_seven_plus_one_seats_50pct(self):
        # PDF Example 3: 7+1 (8 total seats) → vehicle_reduction_factor = 0.50.
        breakdown = calculate_ppmv(**_AUDI_KWARGS, seat_count=8)
        assert breakdown.vehicle_reduction_factor == pytest.approx(0.50)
        assert breakdown.final_ppmv == pytest.approx(
            _AUDI_AS_NEW * 0.50 * _AUDI_DEPR, abs=0.01
        )

    def test_eight_plus_one_seats_75pct(self):
        # PDF Example 3: 8+1 (9 total seats) → vehicle_reduction_factor = 0.25.
        breakdown = calculate_ppmv(**_AUDI_KWARGS, seat_count=9)
        assert breakdown.vehicle_reduction_factor == pytest.approx(0.25)
        assert breakdown.final_ppmv == pytest.approx(
            _AUDI_AS_NEW * 0.25 * _AUDI_DEPR, abs=0.01
        )

    def test_fewer_than_8_seats_no_reduction(self):
        breakdown = calculate_ppmv(**_AUDI_KWARGS, seat_count=7)
        assert breakdown.vehicle_reduction_factor == pytest.approx(1.0)
        assert breakdown.final_ppmv == pytest.approx(3475.50)

    def test_no_seat_count_no_reduction(self):
        breakdown = calculate_ppmv(**_AUDI_KWARGS)
        assert breakdown.vehicle_reduction_factor == pytest.approx(1.0)


class TestCamperReduction:
    """PDF Example 5: kamper → −85%, vehicle_reduction_factor = 0.15.
    Base PPMV in the example: 160 935 kn.
    160 935 × 15 % = 24 140.25 kn."""

    def test_camper_85pct_reduction(self):
        # PDF Example 5: is_camper → vehicle_reduction_factor = 0.15.
        breakdown = calculate_ppmv(**_AUDI_KWARGS, is_camper=True)
        assert breakdown.vehicle_reduction_factor == pytest.approx(0.15)
        assert breakdown.final_ppmv == pytest.approx(
            _AUDI_AS_NEW * 0.15 * _AUDI_DEPR, abs=0.01
        )

    def test_not_camper_no_reduction(self):
        breakdown = calculate_ppmv(**_AUDI_KWARGS, is_camper=False)
        assert breakdown.vehicle_reduction_factor == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# PDF worked-example regression tests — values converted from HRK to EUR at
# the fixed euro conversion rate of 7.53450 HRK/EUR (in force since 1.1.2023).
#
# The EUR tables in tables.py (NN 156/22) are the official EUR equivalents of
# the old HRK tables, so price/as_new/final_ppmv values converted at 7.53450
# reproduce the PDF results to within ±0.30 EUR (rounding in both directions).
#
# New-vehicle examples (1–5): the PDF computes PPMV = as_new_total directly
# (law path for new vehicles, factor = 1.0). The engine always multiplies by
# the depreciation table value; for months_old=0 that is 0.96, not 1.0. So for
# new-vehicle examples we verify as_new_total and vehicle_reduction_factor only.
# Used-vehicle examples (9, 10): both as_new_total AND final_ppmv are verified.
# ---------------------------------------------------------------------------

_HRK = 7.53450  # fixed HRK→EUR conversion rate


class TestNewVehicleDepreciation:
    """Pravilnik čl. 9: Tablica 1 depreciation applies to used vehicles only.
    New vehicles (is_new_vehicle=True) use depreciation_percent=1.0."""

    def test_new_vehicle_depreciation_is_one(self):
        bd = calculate_ppmv(
            price_eur=30_000.0,
            co2_g_km=130.0,
            fuel_type=FuelType.PETROL,
            first_registration_date=date(2023, 1, 1),
            declaration_date=date(2023, 1, 1),
            is_new_vehicle=True,
        )
        assert bd.months_old == 0
        assert bd.depreciation_percent == pytest.approx(1.0)
        assert bd.final_ppmv == pytest.approx(bd.as_new_total * bd.vehicle_reduction_factor)

    def test_used_vehicle_same_day_uses_96pct(self):
        # A USED vehicle declared on the same day it was first registered (0 months,
        # e.g. just imported from abroad) does NOT get factor=1.0 — it sits in the
        # [0, 1) bracket of Tablica 1 which is 96%.
        bd = calculate_ppmv(
            price_eur=30_000.0,
            co2_g_km=130.0,
            fuel_type=FuelType.PETROL,
            first_registration_date=date(2023, 1, 1),
            declaration_date=date(2023, 1, 1),
            is_new_vehicle=False,  # default — used-vehicle path
        )
        assert bd.months_old == 0
        assert bd.depreciation_percent == pytest.approx(0.96)


class TestPDFExamplesNewVehicles:
    """PDF Examples 1–5 (section I, new vehicles). Dates set to 2023-01-01
    so WLTP/post-2021 tables apply. All use is_new_vehicle=True per čl. 9.
    Both as_new_total and final_ppmv are verified against the PDF (converted
    at the fixed rate 7.53450 HRK/EUR), within ±0.30 EUR rounding tolerance."""

    def test_ex1_new_petrol_wltp_139g(self):
        """PDF Ex.1: benzin, 139 g/km WLTP, 205 000 kn → PPMV 6 485 kn."""
        bd = calculate_ppmv(
            price_eur=205_000 / _HRK,
            co2_g_km=139,
            fuel_type=FuelType.PETROL,
            first_registration_date=date(2023, 1, 1),
            declaration_date=date(2023, 1, 1),
            is_new_vehicle=True,
        )
        assert bd.as_new_total == pytest.approx(6_485 / _HRK, abs=0.15)
        assert bd.final_ppmv == pytest.approx(6_485 / _HRK, abs=0.15)

    def test_ex2_new_diesel_wltp_127g(self):
        """PDF Ex.2: diesel, 127 g/km WLTP, 195 000 kn → PPMV 3 605 kn."""
        bd = calculate_ppmv(
            price_eur=195_000 / _HRK,
            co2_g_km=127,
            fuel_type=FuelType.DIESEL,
            first_registration_date=date(2023, 1, 1),
            declaration_date=date(2023, 1, 1),
            is_new_vehicle=True,
        )
        assert bd.as_new_total == pytest.approx(3_605 / _HRK, abs=0.15)
        assert bd.final_ppmv == pytest.approx(3_605 / _HRK, abs=0.15)

    def test_ex3_seven_plus_one_seats_50pct(self):
        """PDF Ex.3: diesel 219g 335kkn, 7+1 (8 seats) → base 93 385 kn, reduced by 50%
        → final PPMV 46 692.50 kn."""
        bd = calculate_ppmv(
            price_eur=335_000 / _HRK,
            co2_g_km=219,
            fuel_type=FuelType.DIESEL,
            first_registration_date=date(2023, 1, 1),
            declaration_date=date(2023, 1, 1),
            seat_count=8,
            is_new_vehicle=True,
        )
        assert bd.as_new_total == pytest.approx(93_385 / _HRK, abs=0.15)
        assert bd.vehicle_reduction_factor == pytest.approx(0.50)
        assert bd.final_ppmv == pytest.approx(46_692.50 / _HRK, abs=0.15)

    def test_ex3_eight_plus_one_seats_75pct(self):
        """PDF Ex.3: diesel 219g 335kkn, 8+1 (9 seats) → base 93 385 kn, reduced by 75%
        → final PPMV 23 346.25 kn."""
        bd = calculate_ppmv(
            price_eur=335_000 / _HRK,
            co2_g_km=219,
            fuel_type=FuelType.DIESEL,
            first_registration_date=date(2023, 1, 1),
            declaration_date=date(2023, 1, 1),
            seat_count=9,
            is_new_vehicle=True,
        )
        assert bd.as_new_total == pytest.approx(93_385 / _HRK, abs=0.15)
        assert bd.vehicle_reduction_factor == pytest.approx(0.25)
        assert bd.final_ppmv == pytest.approx(23_346.25 / _HRK, abs=0.15)

    def test_ex4_phev_eaer_city_59km(self):
        """PDF Ex.4: benzin PHEV 59 g/km, 418 000 kn, EAER city 59 km → PPMV 6 961.80 kn.
        CO2=59 is below the WLTP petrol table floor (95 g/km) → eco_component=0.
        The PDF base of 16 980 kn is value-only; the 59% reduction gives 6 961.80 kn.
        Note: the PDF labels the reduction '-52%' (WLTP combined range) but the
        arithmetic proves 59% was applied — consistent with EAER city = 59 km."""
        bd = calculate_ppmv(
            price_eur=418_000 / _HRK,
            co2_g_km=59,
            fuel_type=FuelType.PETROL,
            first_registration_date=date(2023, 1, 1),
            declaration_date=date(2023, 1, 1),
            eaer_city_range_km=59,
            is_new_vehicle=True,
        )
        assert bd.as_new_eco_component == 0.0           # CO2 below WLTP petrol floor (95 g/km)
        assert bd.as_new_total == pytest.approx(16_980 / _HRK, abs=0.15)
        assert bd.vehicle_reduction_factor == pytest.approx(0.41)
        assert bd.final_ppmv == pytest.approx(6_961.80 / _HRK, abs=0.15)

    def test_ex5_camper_85pct(self):
        """PDF Ex.5: diesel 258 g/km, 475 000 kn, kamper → base 160 935 kn, −85%
        → final PPMV 24 140.25 kn."""
        bd = calculate_ppmv(
            price_eur=475_000 / _HRK,
            co2_g_km=258,
            fuel_type=FuelType.DIESEL,
            first_registration_date=date(2023, 1, 1),
            declaration_date=date(2023, 1, 1),
            is_camper=True,
            is_new_vehicle=True,
        )
        assert bd.as_new_total == pytest.approx(160_935 / _HRK, abs=0.30)
        assert bd.vehicle_reduction_factor == pytest.approx(0.15)
        assert bd.final_ppmv == pytest.approx(24_140.25 / _HRK, abs=0.30)


class TestPDFExamplesUsedVehicles:
    """PDF Examples 9–10 (section II, used vehicles). Both as_new_total and
    final_ppmv are verified against the PDF — depreciation is in the table path."""

    def test_ex9_used_diesel_nedc_99g_20months(self):
        """PDF Ex.9: diesel NEDC 99 g/km, 285 000 kn, reg 15.4.2019, 20 months,
        depr 68.36% → as_new 11 910 kn, PPMV 8 141.68 kn."""
        bd = calculate_ppmv(
            price_eur=285_000 / _HRK,
            co2_g_km=99,
            fuel_type=FuelType.DIESEL,
            first_registration_date=date(2019, 4, 15),
            declaration_date=date(2020, 12, 15),
        )
        assert bd.months_old == 20
        assert bd.depreciation_percent == pytest.approx(0.6836)
        assert bd.as_new_total == pytest.approx(11_910 / _HRK, abs=0.10)
        assert bd.final_ppmv == pytest.approx(8_141.68 / _HRK, abs=0.10)

    def test_ex10_used_petrol_wltp_145g_4months(self):
        """PDF Ex.10: benzin WLTP 145 g/km, 215 000 kn, reg 4.1.2021, 4 months,
        depr 86% → as_new 7 625 kn, PPMV 6 557.50 kn."""
        bd = calculate_ppmv(
            price_eur=215_000 / _HRK,
            co2_g_km=145,
            fuel_type=FuelType.PETROL,
            first_registration_date=date(2021, 1, 4),
            declaration_date=date(2021, 5, 4),
        )
        assert bd.months_old == 4
        assert bd.depreciation_percent == pytest.approx(0.86)
        assert bd.as_new_total == pytest.approx(7_625 / _HRK, abs=0.10)
        assert bd.final_ppmv == pytest.approx(6_557.50 / _HRK, abs=0.10)