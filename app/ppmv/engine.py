"""Pure PPMV calculation logic — no I/O, no FastAPI, no database.

Kept pure deliberately: this is what makes the Audi A5 regression test a
plain function call with no app/DB bootstrap required.
"""

from datetime import date
from typing import Optional

from app.ppmv.exceptions import InvalidCO2Value, InvalidPriceValue, UnsupportedVehicleCategory
from app.ppmv.schemas import CO2Standard, FuelType, PPMVBreakdown
from app.ppmv.tables import (
    DEPRECIATION_FLOOR_MONTHS,
    DEPRECIATION_REDUCTION_PER_12MO,
    DEPRECIATION_TABLE,
    DEPRECIATION_TABLE_MAX_MONTHS,
    ECO_TABLE_DIESEL_NEDC,
    ECO_TABLE_DIESEL_WLTP,
    ECO_TABLE_PETROL_NEDC,
    ECO_TABLE_PETROL_WLTP,
    VALUE_TABLE_POST_2021,
    VALUE_TABLE_PRE_2021,
    EcoBracket,
    ValueBracket,
)

# Vehicles registered on/after this date use WLTP CO2 + the post-2021 tables.
WLTP_CUTOVER_DATE = date(2021, 1, 1)

_ECO_TABLES: dict[tuple[CO2Standard, FuelType], tuple[EcoBracket, ...]] = {
    (CO2Standard.NEDC, FuelType.DIESEL): ECO_TABLE_DIESEL_NEDC,
    (CO2Standard.NEDC, FuelType.PETROL): ECO_TABLE_PETROL_NEDC,
    (CO2Standard.WLTP, FuelType.DIESEL): ECO_TABLE_DIESEL_WLTP,
    (CO2Standard.WLTP, FuelType.PETROL): ECO_TABLE_PETROL_WLTP,
}


def _find_value_bracket(price_eur: float, table: tuple[ValueBracket, ...]) -> ValueBracket:
    for bracket in table:
        lower_ok = price_eur >= bracket.lower_bound_eur
        upper_ok = bracket.upper_bound_eur is None or price_eur <= bracket.upper_bound_eur
        if lower_ok and upper_ok:
            return bracket
    raise InvalidPriceValue(f"No value bracket matches price {price_eur} EUR")


def _find_eco_bracket(co2_g_km: float, table: tuple[EcoBracket, ...]) -> EcoBracket | None:
    """Returns None when CO2 is below the table floor (eco component = 0).
    That is the correct result for PHEVs and very clean vehicles whose CO2
    sits under the lowest bracket — they owe no eco component, not an error.
    """
    if co2_g_km < table[0].lower_bound_co2:
        return None
    for bracket in table:
        lower_ok = co2_g_km >= bracket.lower_bound_co2
        upper_ok = bracket.upper_bound_co2 is None or co2_g_km <= bracket.upper_bound_co2
        if lower_ok and upper_ok:
            return bracket
    raise InvalidCO2Value(f"CO2 value {co2_g_km} g/km is outside all known brackets")


def _months_between(start: date, end: date) -> int:
    """Full months elapsed per Pravilnik čl. 9 st. 4: a month is complete
    on the day of the following month whose day-number matches the
    registration day; if that day doesn't exist in the target month, the
    month is complete on that month's last day.

    Confirmed: 17.08.2020 -> 10.07.2025 = 58 months.
    """
    months = (end.year - start.year) * 12 + (end.month - start.month)

    # Does "start.day" exist in the month `months` after start? If end.day
    # has reached/passed it, that final partial month is complete.
    target_year = start.year + (start.month - 1 + months) // 12
    target_month = (start.month - 1 + months) % 12 + 1
    last_day_of_target_month = _days_in_month(target_year, target_month)
    completion_day = min(start.day, last_day_of_target_month)

    if end.day < completion_day:
        months -= 1
    return max(months, 0)


def _days_in_month(year: int, month: int) -> int:
    if month == 12:
        return (date(year + 1, 1, 1) - date(year, 12, 1)).days
    return (date(year, month + 1, 1) - date(year, month, 1)).days


def _depreciation_percent(months_old: int) -> float:
    if months_old < DEPRECIATION_TABLE_MAX_MONTHS:
        for bracket in DEPRECIATION_TABLE:
            if bracket.min_months <= months_old < bracket.max_months:
                return bracket.percent
        raise UnsupportedVehicleCategory(f"No depreciation bracket matches age {months_old} months")

    # Čl. 9 st. 3: beyond 180mo, reduce the last table value by 0.6
    # percentage points per full 12-month period, frozen at 360mo.
    base_percent = DEPRECIATION_TABLE[-1].percent
    capped_months = min(months_old, DEPRECIATION_FLOOR_MONTHS)
    periods_beyond = (capped_months - DEPRECIATION_TABLE_MAX_MONTHS) // 12
    return round(base_percent - periods_beyond * DEPRECIATION_REDUCTION_PER_12MO, 6)


def calculate_ppmv(
    price_eur: float,
    co2_g_km: float,
    fuel_type: FuelType,
    first_registration_date: date,
    declaration_date: date,
    eaer_city_range_km: Optional[float] = None,
    seat_count: Optional[int] = None,
    is_camper: bool = False,
    is_new_vehicle: bool = False,
) -> PPMVBreakdown:
    """Computes the full PPMV breakdown for a new or used vehicle.

    Reduction order (all applied to as_new_total, before depreciation):
      1. Electric exemption (FuelType.ELECTRIC) — returns immediately, final_ppmv = 0.
      2. Plug-in hybrid: reduction % = eaer_city_range_km, capped at 100.
      3. Seat count: 8 seats (7+1) → ×0.50; 9+ seats (8+1) → ×0.25.
      4. Camper (kamper): ×0.15.
    Reductions multiply together when more than one applies.

    Depreciation (Pravilnik Tablica 1) applies only to USED vehicles.
    Pass is_new_vehicle=True to skip it (depreciation_percent = 1.0,
    months_old = 0), as mandated by čl. 9.

    Raises:
        InvalidCO2Value: CO2 strictly above the table floor but outside all
            known brackets (gap in the table — should not occur with the
            current continuous tables).
        InvalidPriceValue: price outside all known value brackets.
        UnsupportedVehicleCategory: vehicle age outside all known
            depreciation brackets (should not occur — table + formula
            cover 0 to 360+ months).
    """
    # Step 1: Depreciation — new vehicles use factor 1.0 (skip Tablica 1).
    if is_new_vehicle:
        months_old = 0
        depreciation_percent = 1.0
    else:
        months_old = _months_between(first_registration_date, declaration_date)
        depreciation_percent = _depreciation_percent(months_old)

    # Step 2: Electric exemption — fully exempt, no further computation.
    if fuel_type == FuelType.ELECTRIC:
        return PPMVBreakdown(
            as_new_value_component=0.0,
            as_new_eco_component=0.0,
            as_new_total=0.0,
            vehicle_reduction_factor=1.0,
            depreciation_percent=depreciation_percent,
            months_old=months_old,
            final_ppmv=0.0,
        )

    # Step 3: Standard value + eco components.
    is_wltp = first_registration_date >= WLTP_CUTOVER_DATE
    standard = CO2Standard.WLTP if is_wltp else CO2Standard.NEDC
    value_table = VALUE_TABLE_POST_2021 if is_wltp else VALUE_TABLE_PRE_2021
    eco_table = _ECO_TABLES[(standard, fuel_type)]

    value_bracket = _find_value_bracket(price_eur, value_table)
    eco_bracket = _find_eco_bracket(co2_g_km, eco_table)

    value_component = value_bracket.fixed_amount_vn + (
        (price_eur - value_bracket.lower_bound_eur) * value_bracket.percent_pc
    )
    if eco_bracket is None:
        eco_component = 0.0
    else:
        eco_component = eco_bracket.fixed_amount_on + (
            (co2_g_km - eco_bracket.lower_bound_co2) * eco_bracket.rate_per_gkm_en
        )
    as_new_total = value_component + eco_component

    # Step 4: Vehicle-type reductions — applied to as_new_total before depreciation.
    # All three are independent factors that multiply together.
    vehicle_reduction_factor = 1.0

    # Plug-in hybrid: reduction % = EAER city range in km (Zakon čl. 12 st. 1).
    # Use EAER *city* cycle, NOT WLTP combined — the law names "EAER city" explicitly.
    # Official worked example 4: EAER city 59 km → 59% reduction (PDF shows WLTP combined
    # 52 km in the description text but applies 59% in the arithmetic).
    if eaer_city_range_km is not None:
        phev_reduction_pct = min(eaer_city_range_km, 100.0)
        vehicle_reduction_factor *= 1.0 - phev_reduction_pct / 100.0

    # Seat count: 8 total seats (7+1) → −50%; 9+ total seats (8+1) → −75%.
    if seat_count is not None and seat_count >= 8:
        seat_factor = 0.25 if seat_count >= 9 else 0.50
        vehicle_reduction_factor *= seat_factor

    # Camper (kamper): −85%.
    if is_camper:
        vehicle_reduction_factor *= 0.15

    # Step 5: Depreciation applied to reduced as_new_total.
    final_ppmv = round(as_new_total * vehicle_reduction_factor * depreciation_percent, 2)

    return PPMVBreakdown(
        as_new_value_component=round(value_component, 2),
        as_new_eco_component=round(eco_component, 2),
        as_new_total=round(as_new_total, 2),
        vehicle_reduction_factor=vehicle_reduction_factor,
        depreciation_percent=depreciation_percent,
        months_old=months_old,
        final_ppmv=final_ppmv,
    )