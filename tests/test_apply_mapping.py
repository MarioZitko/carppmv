"""Tests for apply_mapping() in isolation.

Hardcoded ColumnMapping fixtures cover each of the 4 confirmed Excel schema
families. No LLM calls — map_sheet_columns() is never invoked here.

Family notes (from canonical_schema.py):
- VW-group: letter-coded fuel (D/B/MH/H/E), standard column layout
- BMW: spelled-out fuel ('benzin'/'diesel'), interleaved section-header rows
- Mercedes: split min/max CO2 (~11 g/km avg spread), co2_min_max_policy="max"
- Porsche: lowercase Croatian column names; fuel codes are still B/D (same as
  VW — 'different vocabulary' from the original spec refers only to column
  NAMES, not to the fuel code values, per real Porsche file inspection)
"""

from datetime import date

import pytest

from app.catalogue.canonical_schema import (
    CanonicalRow,
    ColumnMapping,
    FuelCategory,
    apply_mapping,
)
from app.core.config import get_settings


# ---------------------------------------------------------------------------
# Helper: build a ColumnMapping with optional fields defaulted to None
# ---------------------------------------------------------------------------

def _mapping(**kwargs) -> ColumnMapping:
    defaults: dict = dict(
        brand_column="MARKA",
        model_name_column=None,
        type_code_column=None,
        full_name_column=None,
        fuel_column="GORIVO",
        price_column="CIJENA (EUR)",
        price_currency="EUR",
        valid_from_column="VRIJEDI OD",
        co2_column="CO2 (g/km)",
        co2_min_column=None,
        co2_max_column=None,
        power_kw_column=None,
        plug_in_range_column=None,
        seats_7plus1_column=None,
        seats_8plus1_column=None,
        camper_column=None,
        pickup_8704_column=None,
        euro_norm_column=None,
        confidence=0.95,
        notes="",
    )
    defaults.update(kwargs)
    return ColumnMapping(**defaults)


# ===========================================================================
# VW-group family
# Letter-coded fuel: D=diesel, B=petrol, MH=mild-hybrid, H=plug-in, E=electric
# Standard column layout; prices in EUR; single CO2 column with trailing * ok
# ===========================================================================

VW_HEADER = [
    "MARKA", "MODEL KOD", "MODEL", "KOMPLETNO IME", "GORIVO",
    "CIJENA (EUR)", "VRIJEDI OD", "CO2* (g/km)", "KW", "PLUG-IN (DOSEG)",
    "7+1", "8+1", "EURO NORMA",
]

VW_MAPPING = _mapping(
    model_name_column="MODEL",
    type_code_column="MODEL KOD",
    full_name_column="KOMPLETNO IME",
    price_column="CIJENA (EUR)",
    co2_column="CO2* (g/km)",
    power_kw_column="KW",
    plug_in_range_column="PLUG-IN (DOSEG)",
    seats_7plus1_column="7+1",
    seats_8plus1_column="8+1",
    euro_norm_column="EURO NORMA",
)

def _vw(*args) -> tuple:
    # positional: marka, kod, model, ime, gorivo, cijena, vrijedi_od, co2, kw, doseg, 7+1, 8+1, euro
    return args + (None,) * (len(VW_HEADER) - len(args))


def test_vw_diesel():
    rows = [_vw("VW", "VW001", "Golf TDI", "VW Golf 8 2.0 TDI", "D", 32000.0, date(2025, 1, 1), 130.0, 110.0)]
    result = apply_mapping(rows, VW_HEADER, VW_MAPPING, "vw.xlsx", "Sheet1")
    assert len(result) == 1
    r = result[0]
    assert r.fuel_category == FuelCategory.DIESEL
    assert r.price_eur == 32000.0
    assert r.price_source_currency == "EUR"
    assert r.co2_g_km == 130.0
    assert r.co2_resolution_policy == "single_column"
    assert r.power_kw == 110.0
    assert r.power_boost_kw is None
    assert r.valid_from == date(2025, 1, 1)
    assert r.brand == "VW"
    assert r.model_name == "Golf TDI"
    assert r.type_code == "VW001"
    assert r.full_name == "VW Golf 8 2.0 TDI"
    assert r.needs_review is False


def test_vw_petrol():
    rows = [_vw("VW", "VW002", "Golf TSI", "VW Golf 8 1.5 TSI", "B", 28000.0, date(2025, 1, 1), 120.0, 110.0)]
    result = apply_mapping(rows, VW_HEADER, VW_MAPPING, "vw.xlsx", "Sheet1")
    assert len(result) == 1
    assert result[0].fuel_category == FuelCategory.PETROL


def test_vw_electric():
    rows = [_vw("VW", "VW003", "ID.3", "VW ID.3 Pure", "E", 38000.0, date(2025, 1, 1), 0.0, 107.0)]
    result = apply_mapping(rows, VW_HEADER, VW_MAPPING, "vw.xlsx", "Sheet1")
    assert len(result) == 1
    assert result[0].fuel_category == FuelCategory.ELECTRIC
    assert result[0].co2_g_km == 0.0


def test_vw_plug_in_hybrid():
    # H code + populated PLUG-IN (DOSEG) → PETROL_PLUG_IN_HYBRID
    rows = [_vw("VW", "VW004", "Golf GTE", "VW Golf GTE", "H", 43000.0, date(2025, 1, 1), 19.0, 180.0, 54.0)]
    result = apply_mapping(rows, VW_HEADER, VW_MAPPING, "vw.xlsx", "Sheet1")
    assert len(result) == 1
    r = result[0]
    assert r.fuel_category == FuelCategory.PETROL_PLUG_IN_HYBRID
    assert r.plug_in_range_km == 54.0


def test_vw_mild_hybrid():
    # MH code → PETROL_HYBRID
    rows = [_vw("VW", "VW005", "Touareg eH", "VW Touareg eHybrid", "MH", 78000.0, date(2025, 1, 1), 102.0, 250.0)]
    result = apply_mapping(rows, VW_HEADER, VW_MAPPING, "vw.xlsx", "Sheet1")
    assert len(result) == 1
    assert result[0].fuel_category == FuelCategory.PETROL_HYBRID


def test_vw_unknown_fuel_code():
    # G (Erdgas/CNG) → UNKNOWN — never silently defaulted
    rows = [_vw("VW", "VW006", "Caddy TGI", "VW Caddy 2.0 TGI", "G", 30000.0, date(2025, 1, 1), 109.0, 96.0)]
    result = apply_mapping(rows, VW_HEADER, VW_MAPPING, "vw.xlsx", "Sheet1")
    assert len(result) == 1
    r = result[0]
    assert r.fuel_category == FuelCategory.UNKNOWN
    assert r.fuel_raw_value == "G"
    assert r.needs_review is True


def test_vw_junk_row_with_blank_model_skipped():
    rows = [
        _vw("VW", None, None, None, None, None, None, None, None),  # blank model → junk
        _vw("VW", "VW001", "Golf TDI", "VW Golf 8 2.0 TDI", "D", 32000.0, date(2025, 1, 1), 130.0, 110.0),
    ]
    skip_log: list[tuple[int, str]] = []
    result = apply_mapping(rows, VW_HEADER, VW_MAPPING, "vw.xlsx", "Sheet1", skip_log=skip_log)
    assert len(result) == 1
    assert any(reason == "junk_row" for _, reason in skip_log)


def test_vw_co2_trailing_asterisk():
    # Trailing asterisk (BMW-style footnote marker also present in some VW sheets)
    rows = [_vw("VW", "VW007", "Arteon TDI", "VW Arteon 2.0 TDI", "D", 52000.0, date(2025, 1, 1), "154*", 110.0)]
    result = apply_mapping(rows, VW_HEADER, VW_MAPPING, "vw.xlsx", "Sheet1")
    assert len(result) == 1
    assert result[0].co2_g_km == 154.0


def test_vw_missing_co2_row_dropped():
    rows = [
        _vw("VW", "VW001", "Golf TDI", "VW Golf 8 2.0 TDI", "D", 32000.0, date(2025, 1, 1), None, 110.0),
        _vw("VW", "VW002", "Golf TSI", "VW Golf 8 1.5 TSI", "B", 28000.0, date(2025, 1, 1), 120.0, 110.0),
    ]
    skip_log: list[tuple[int, str]] = []
    result = apply_mapping(rows, VW_HEADER, VW_MAPPING, "vw.xlsx", "Sheet1", skip_log=skip_log)
    assert len(result) == 1
    assert result[0].model_name == "Golf TSI"
    assert any(reason == "missing_co2" for _, reason in skip_log)


def test_vw_source_row_index():
    # source_row_index is 1-indexed with 1 for header → data row 0 = row 2, data row 1 = row 3
    rows = [
        _vw("VW", "VW001", "Golf TDI", "x", "D", 32000.0, date(2025, 1, 1), 130.0, 110.0),
        _vw("VW", "VW002", "Golf TSI", "x", "B", 28000.0, date(2025, 1, 1), 120.0, 110.0),
    ]
    result = apply_mapping(rows, VW_HEADER, VW_MAPPING, "vw.xlsx", "Sheet1")
    assert result[0].source_row_index == 2
    assert result[1].source_row_index == 3


# ===========================================================================
# BMW family
# Fuel spelled out: 'diesel' (English) and 'benzin' (Croatian)
# Interleaved section-header rows: brand column has section title, model blank
# CO2 values may have trailing asterisk footnote markers
# VRIJEDI OD as "DD.MM.YYYY." string (trailing dot) or native Excel date
# Power may have "+NN" boost suffix → PETROL_HYBRID when present
# ===========================================================================

BMW_HEADER = [
    "MARKA", "TRGOVAČKI NAZIV", "GORIVO", "OSNOVNA CIJENA (EUR)", "VRIJEDI OD",
    "CO2 (g/km)", "kW",
]

BMW_MAPPING = _mapping(
    model_name_column="TRGOVAČKI NAZIV",
    price_column="OSNOVNA CIJENA (EUR)",
    valid_from_column="VRIJEDI OD",
    co2_column="CO2 (g/km)",
    power_kw_column="kW",
)

def _bmw(marka, naziv, gorivo, cijena, vrijedi_od, co2, kw) -> tuple:
    return (marka, naziv, gorivo, cijena, vrijedi_od, co2, kw)


def test_bmw_section_header_filtered():
    # Section-header rows have content only in the brand column; TRGOVAČKI NAZIV is blank.
    # Two real data rows (both plain "BMW" in the brand cell) establish that sheet's normal
    # brand text, so the banner's distinctively different text is recognized as such — the
    # "typical brand cell" heuristic needs more than one real row to not tie against a lone banner.
    rows = [
        ("BMW serije 1 (F40)", None, None, None, None, None, None),  # section header
        _bmw("BMW", "BMW 320d xDrive", "diesel", 55000.0, date(2020, 2, 17), 130.0, 140.0),
        _bmw("BMW", "BMW 116d", "diesel", 40000.0, date(2020, 2, 17), 108.0, 85.0),
    ]
    skip_log: list[tuple[int, str]] = []
    result = apply_mapping(rows, BMW_HEADER, BMW_MAPPING, "bmw.xlsx", "Cjenik", skip_log=skip_log)
    assert len(result) == 2
    assert result[0].model_name == "BMW 320d xDrive"
    assert any(reason == "series_banner" for _, reason in skip_log)
    assert not any(reason == "junk_row" for _, reason in skip_log)


def test_bmw_section_header_recovered_as_series_name():
    # The banner's series text is stripped of its trailing chassis code and
    # its redundant leading brand token (downstream consumers, e.g. the
    # frontend, already prefix the brand themselves — a source-side repeat
    # would otherwise show up as "BMW BMW serije 1"), then carried forward
    # onto every row until the next banner.
    rows = [
        ("BMW serije 1 (F40)", None, None, None, None, None, None),
        _bmw("BMW", "116d", "diesel", 43000.0, date(2020, 2, 17), 108.0, 110.0),
        _bmw("BMW", "118i", "benzin", 41000.0, date(2020, 2, 17), 145.0, 103.0),
    ]
    result = apply_mapping(rows, BMW_HEADER, BMW_MAPPING, "bmw.xlsx", "Cjenik")
    assert len(result) == 2
    assert result[0].series_name == "serije 1"
    assert result[0].model_name == "116d"
    assert result[1].series_name == "serije 1"


def test_no_section_header_leaves_series_name_none():
    # Families with no banner rows at all (VW, Audi, ...) get series_name=None
    # for every row — apply_mapping never invents one.
    rows = [_vw("VW", "VW001", "Golf TDI", "VW Golf 8 2.0 TDI", "D", 32000.0, date(2025, 1, 1), 130.0, 110.0)]
    result = apply_mapping(rows, VW_HEADER, VW_MAPPING, "vw.xlsx", "Cjenik")
    assert len(result) == 1
    assert result[0].series_name is None


def test_bmw_diesel_english_spelling():
    # BMW uses 'diesel' (English), not 'dizel' (Croatian)
    rows = [_bmw("BMW", "BMW 320d", "diesel", 48000.0, date(2020, 2, 17), 130.0, 140.0)]
    result = apply_mapping(rows, BMW_HEADER, BMW_MAPPING, "bmw.xlsx", "Cjenik")
    assert len(result) == 1
    assert result[0].fuel_category == FuelCategory.DIESEL
    assert result[0].fuel_raw_value == "diesel"


def test_bmw_benzin():
    rows = [_bmw("BMW", "BMW 320i", "benzin", 44000.0, date(2020, 2, 17), 151.0, 135.0)]
    result = apply_mapping(rows, BMW_HEADER, BMW_MAPPING, "bmw.xlsx", "Cjenik")
    assert len(result) == 1
    assert result[0].fuel_category == FuelCategory.PETROL


def test_bmw_co2_trailing_asterisk():
    rows = [_bmw("BMW", "BMW 530d", "diesel", 72000.0, date(2020, 2, 17), "122*", 195.0)]
    result = apply_mapping(rows, BMW_HEADER, BMW_MAPPING, "bmw.xlsx", "Cjenik")
    assert len(result) == 1
    assert result[0].co2_g_km == 122.0


def test_bmw_vrijedi_od_string_trailing_dot():
    # "17.02.2020." — BMW 2020 format with trailing dot
    rows = [_bmw("BMW", "BMW 118i", "benzin", 40000.0, "17.02.2020.", 145.0, 103.0)]
    result = apply_mapping(rows, BMW_HEADER, BMW_MAPPING, "bmw.xlsx", "Cjenik")
    assert len(result) == 1
    assert result[0].valid_from == date(2020, 2, 17)


def test_bmw_vrijedi_od_string_no_trailing_dot():
    # "07.02.2023" — BMW 2023 format without trailing dot
    rows = [_bmw("BMW", "BMW 118i", "benzin", 43000.0, "07.02.2023", 143.0, 103.0)]
    result = apply_mapping(rows, BMW_HEADER, BMW_MAPPING, "bmw.xlsx", "Cjenik")
    assert len(result) == 1
    assert result[0].valid_from == date(2023, 2, 7)


def test_bmw_power_boost_suffix_yields_mild_hybrid():
    # 'benzin' + power_boost_kw > 0 → PETROL_HYBRID (mild hybrid)
    rows = [_bmw("BMW", "BMW 745e", "benzin", 110000.0, date(2020, 2, 17), "81*", "210+15")]
    result = apply_mapping(rows, BMW_HEADER, BMW_MAPPING, "bmw.xlsx", "Cjenik")
    assert len(result) == 1
    r = result[0]
    assert r.power_kw == 210.0
    assert r.power_boost_kw == 15.0
    assert r.fuel_category == FuelCategory.PETROL_HYBRID
    assert r.co2_g_km == 81.0


def test_bmw_banner_with_merged_cell_numeric_bleed_still_detected():
    # Regression: confirmed against a real file (bmw-mini/2018/BMW 2018
    # 1201.xlsx) — a vertically-merged source column (BROJ SJEDALA) leaks its
    # numeric value into every row of a block, including banner rows. A
    # banner row with that stray numeric cell must still be recognized as a
    # banner (not silently rejected, which would forward-fill the PREVIOUS
    # series onto the wrong section — e.g. an X1 SAV block inheriting the
    # prior "7 Series" banner in production).
    rows = [
        ("BMW serije 3 (G20)", None, None, None, None, None, None),
        _bmw("BMW", "BMW 318d", "diesel", 50000.0, date(2020, 2, 17), 116.0, 110.0),
        ("BMW serije X1", None, None, None, None, None, 6),  # banner + stray numeric cell
        _bmw("BMW", "X1 sDrive18d", "diesel", 45000.0, date(2020, 2, 17), 120.0, 110.0),
    ]
    skip_log: list[tuple[int, str]] = []
    result = apply_mapping(rows, BMW_HEADER, BMW_MAPPING, "bmw.xlsx", "Cjenik", skip_log=skip_log)
    assert len(result) == 2
    assert len([r for _, r in skip_log if r == "series_banner"]) == 2
    assert result[0].series_name == "serije 3"
    assert result[1].series_name == "serije X1"
    assert result[1].model_name == "X1 sDrive18d"


def test_bmw_multiple_section_headers():
    rows = [
        ("BMW serije 1 (F40)", None, None, None, None, None, None),
        _bmw("BMW", "BMW 118d", "diesel", 43000.0, date(2020, 2, 17), 108.0, 110.0),
        ("BMW serije 3 (G20)", None, None, None, None, None, None),
        _bmw("BMW", "BMW 318d", "diesel", 50000.0, date(2020, 2, 17), 116.0, 110.0),
    ]
    skip_log: list[tuple[int, str]] = []
    result = apply_mapping(rows, BMW_HEADER, BMW_MAPPING, "bmw.xlsx", "Cjenik", skip_log=skip_log)
    assert len(result) == 2
    assert len([r for _, r in skip_log if r == "series_banner"]) == 2
    assert not any(r == "junk_row" for _, r in skip_log)
    assert result[0].series_name == "serije 1"
    assert result[0].model_name == "BMW 118d"
    assert result[1].series_name == "serije 3"
    assert result[1].model_name == "BMW 318d"


# ===========================================================================
# Mercedes family
# Split CO2: co2_min_column + co2_max_column (no single co2_column)
# Default policy "max" → conservative for tax purposes
# 'benzin' + power boost suffix → PETROL_HYBRID
# Mercedes spells diesel 'dizel' (Croatian), not 'diesel' (English)
# ===========================================================================

MB_HEADER = [
    "MARKA", "MODEL", "KOMPLETNO IME", "GORIVO", "CIJENA (EUR)", "VRIJEDI OD",
    "CO2 min (g/km)", "CO2 max (g/km)", "kW",
]

MB_MAPPING = _mapping(
    model_name_column="MODEL",
    full_name_column="KOMPLETNO IME",
    price_column="CIJENA (EUR)",
    co2_column=None,
    co2_min_column="CO2 min (g/km)",
    co2_max_column="CO2 max (g/km)",
    power_kw_column="kW",
)

def _mb(marka, model, ime, gorivo, cijena, vrijedi_od, co2_min, co2_max, kw) -> tuple:
    return (marka, model, ime, gorivo, cijena, vrijedi_od, co2_min, co2_max, kw)


def test_mercedes_co2_max_policy():
    rows = [_mb("Mercedes-Benz", "E 220 d", "MB E 220 d 4MATIC", "dizel", 70000.0, date(2024, 1, 1), 148.0, 159.0, 143.0)]
    result = apply_mapping(rows, MB_HEADER, MB_MAPPING, "mb.xlsx", "Cjenik", co2_min_max_policy="max")
    assert len(result) == 1
    r = result[0]
    assert r.co2_g_km == 159.0
    assert r.co2_min_g_km == 148.0
    assert r.co2_max_g_km == 159.0
    assert r.co2_resolution_policy == "max"


def test_mercedes_co2_min_policy():
    rows = [_mb("Mercedes-Benz", "E 220 d", "MB E 220 d 4MATIC", "dizel", 70000.0, date(2024, 1, 1), 148.0, 159.0, 143.0)]
    result = apply_mapping(rows, MB_HEADER, MB_MAPPING, "mb.xlsx", "Cjenik", co2_min_max_policy="min")
    assert len(result) == 1
    assert result[0].co2_g_km == 148.0
    assert result[0].co2_resolution_policy == "min"


def test_mercedes_co2_average_policy():
    rows = [_mb("Mercedes-Benz", "E 220 d", "MB E 220 d", "dizel", 70000.0, date(2024, 1, 1), 148.0, 160.0, 143.0)]
    result = apply_mapping(rows, MB_HEADER, MB_MAPPING, "mb.xlsx", "Cjenik", co2_min_max_policy="average")
    assert len(result) == 1
    assert result[0].co2_g_km == 154.0
    assert result[0].co2_resolution_policy == "average"


def test_mercedes_diesel_dizel_spelling():
    # Mercedes uses Croatian 'dizel', not English 'diesel'
    rows = [_mb("Mercedes-Benz", "C 220 d", "MB C 220 d", "dizel", 58000.0, date(2024, 1, 1), 130.0, 141.0, 143.0)]
    result = apply_mapping(rows, MB_HEADER, MB_MAPPING, "mb.xlsx", "Cjenik")
    assert len(result) == 1
    assert result[0].fuel_category == FuelCategory.DIESEL
    assert result[0].fuel_raw_value == "dizel"


def test_mercedes_petrol_mild_hybrid_via_boost():
    # 'benzin' + power boost suffix "380+16" → PETROL_HYBRID
    rows = [_mb("Mercedes-Benz", "GLS 580", "MB GLS 580 4MATIC", "benzin", 130000.0, date(2024, 1, 1), 256.0, 267.0, "380+16")]
    result = apply_mapping(rows, MB_HEADER, MB_MAPPING, "mb.xlsx", "Cjenik", co2_min_max_policy="max")
    assert len(result) == 1
    r = result[0]
    assert r.fuel_category == FuelCategory.PETROL_HYBRID
    assert r.power_kw == 380.0
    assert r.power_boost_kw == 16.0
    assert r.co2_g_km == 267.0  # max policy


def test_mercedes_co2_spread_representative():
    # Confirm the ~11 g/km spread described in the spec is handled (not averaged silently)
    rows = [_mb("Mercedes-Benz", "GLE 400 d", "MB GLE 400 d 4MATIC", "dizel", 95000.0, date(2024, 1, 1), 203.0, 214.0, 243.0)]
    result = apply_mapping(rows, MB_HEADER, MB_MAPPING, "mb.xlsx", "Cjenik", co2_min_max_policy="max")
    r = result[0]
    assert r.co2_max_g_km - r.co2_min_g_km == pytest.approx(11.0)
    assert r.co2_g_km == r.co2_max_g_km


# ===========================================================================
# Porsche family
# Lowercase Croatian column names (marka, model, gorivo, etc.)
# Old files priced in HRK → converted at fixed rate 7.5345
# Fuel codes are B/D (same letter scheme as VW — confirmed against real files)
# 'B' + populated doseg (plug-in range column) → PETROL_PLUG_IN_HYBRID
# ===========================================================================

PORSCHE_HEADER = [
    "marka", "model", "kompletno_ime", "gorivo", "osnovna_cijena_kn",
    "vrijedi_od", "co2_gkm", "kw_snaga", "doseg",
]

PORSCHE_MAPPING = _mapping(
    brand_column="marka",
    model_name_column="model",
    full_name_column="kompletno_ime",
    fuel_column="gorivo",
    price_column="osnovna_cijena_kn",
    price_currency="HRK",
    valid_from_column="vrijedi_od",
    co2_column="co2_gkm",
    power_kw_column="kw_snaga",
    plug_in_range_column="doseg",
)

def _porsche(marka, model, ime, gorivo, cijena_kn, vrijedi_od, co2, kw, doseg=None) -> tuple:
    return (marka, model, ime, gorivo, cijena_kn, vrijedi_od, co2, kw, doseg)


def test_porsche_hrk_to_eur():
    # 376725.0 kn ÷ 7.5345 = 50000.0 EUR (exact: 7.5345 × 50000 = 376725)
    rows = [_porsche("Porsche", "911 Carrera", "Porsche 911 Carrera", "B", 376725.0, date(2017, 2, 1), 198.0, 272.0)]
    result = apply_mapping(rows, PORSCHE_HEADER, PORSCHE_MAPPING, "porsche.xlsx", "Cjenik")
    assert len(result) == 1
    r = result[0]
    assert r.price_source_currency == "HRK"
    assert r.price_raw_value == 376725.0
    expected_eur = round(376725.0 / get_settings().hrk_to_eur_rate, 2)
    assert r.price_eur == pytest.approx(expected_eur, abs=0.01)


def test_porsche_currency_detected_from_header():
    # _detect_currency_from_header("osnovna_cijena_kn") should find "kn" token → HRK
    # (price_currency="HRK" in mapping is the fallback; header detection wins)
    rows = [_porsche("Porsche", "Macan", "Porsche Macan S", "B", 300000.0, date(2017, 2, 1), 162.0, 220.0)]
    result = apply_mapping(rows, PORSCHE_HEADER, PORSCHE_MAPPING, "porsche.xlsx", "Cjenik")
    assert result[0].price_source_currency == "HRK"


def test_porsche_diesel_letter_code():
    # Porsche uses B/D codes (same as VW) — not spelled-out words
    rows = [_porsche("Porsche", "Macan D", "Porsche Macan D", "D", 376725.0, date(2017, 2, 1), 139.0, 190.0)]
    result = apply_mapping(rows, PORSCHE_HEADER, PORSCHE_MAPPING, "porsche.xlsx", "Cjenik")
    assert len(result) == 1
    assert result[0].fuel_category == FuelCategory.DIESEL


def test_porsche_plug_in_via_doseg():
    # 'B' fuel + populated doseg → PETROL_PLUG_IN_HYBRID (e.g. Cayenne S E-Hybrid)
    rows = [_porsche("Porsche", "Cayenne S E-Hybrid", "Porsche Cayenne S E-Hybrid", "B", 640000.0, date(2017, 2, 1), 71.0, 270.0, doseg=36.0)]
    result = apply_mapping(rows, PORSCHE_HEADER, PORSCHE_MAPPING, "porsche.xlsx", "Cjenik")
    assert len(result) == 1
    r = result[0]
    assert r.fuel_category == FuelCategory.PETROL_PLUG_IN_HYBRID
    assert r.plug_in_range_km == 36.0


def test_porsche_vrijedi_od_single_digit_day_month():
    # "D.M.YYYY." — single-digit day/month format confirmed in real files
    rows = [_porsche("Porsche", "Panamera", "Porsche Panamera 4S", "B", 800000.0, "1.2.2017.", 198.0, 310.0)]
    result = apply_mapping(rows, PORSCHE_HEADER, PORSCHE_MAPPING, "porsche.xlsx", "Cjenik")
    assert len(result) == 1
    assert result[0].valid_from == date(2017, 2, 1)


def test_porsche_missing_co2_dropped():
    rows = [
        _porsche("Porsche", "911 Turbo S", "Porsche 911 Turbo S", "B", 1300000.0, date(2017, 2, 1), None, 478.0),
        _porsche("Porsche", "Boxster", "Porsche Boxster", "B", 420000.0, date(2017, 2, 1), 182.0, 195.0),
    ]
    skip_log: list[tuple[int, str]] = []
    result = apply_mapping(rows, PORSCHE_HEADER, PORSCHE_MAPPING, "porsche.xlsx", "Cjenik", skip_log=skip_log)
    assert len(result) == 1
    assert result[0].model_name == "Boxster"
    assert any(reason == "missing_co2" for _, reason in skip_log)


def test_porsche_no_doseg_is_plain_petrol():
    # 'B' + no doseg, no power boost → plain PETROL
    rows = [_porsche("Porsche", "718 Cayman", "Porsche 718 Cayman", "B", 300000.0, date(2017, 2, 1), 182.0, 220.0, doseg=None)]
    result = apply_mapping(rows, PORSCHE_HEADER, PORSCHE_MAPPING, "porsche.xlsx", "Cjenik")
    assert len(result) == 1
    assert result[0].fuel_category == FuelCategory.PETROL
    assert result[0].plug_in_range_km is None


# ===========================================================================
# Cross-family: skip_log completeness
# ===========================================================================

def test_skip_log_all_reasons():
    # Drive multiple skip paths in one call and verify the log captures all reasons
    rows = [
        # junk_row (model blank)
        _vw("VW", None, None, None, None, None, None, None, None),
        # missing_price
        _vw("VW", "VW001", "Golf TDI", "x", "D", None, date(2025, 1, 1), 130.0, 110.0),
        # missing_co2
        _vw("VW", "VW002", "Golf TSI", "x", "B", 28000.0, date(2025, 1, 1), None, 110.0),
        # missing_or_unparseable_valid_from
        _vw("VW", "VW003", "Polo TSI", "x", "B", 22000.0, "not-a-date", 110.0, 70.0),
        # valid row
        _vw("VW", "VW004", "Passat TDI", "x", "D", 42000.0, date(2025, 1, 1), 140.0, 140.0),
    ]
    skip_log: list[tuple[int, str]] = []
    result = apply_mapping(rows, VW_HEADER, VW_MAPPING, "vw.xlsx", "Sheet1", skip_log=skip_log)
    assert len(result) == 1
    reasons = {reason for _, reason in skip_log}
    assert "junk_row" in reasons
    assert "missing_price" in reasons
    assert "missing_co2" in reasons
    assert "missing_or_unparseable_valid_from" in reasons


# ===========================================================================
# Cross-module: series_name -> catalogue "model" at the ingest layer
# ===========================================================================

def test_series_name_wins_as_catalogue_model():
    from app.data.catalogues.ingest import _to_catalogue_dict, _co2_standard_from_year

    rows = [
        ("BMW serije 1 (F40)", None, None, None, None, None, None),
        _bmw("BMW", "116d", "diesel", 43000.0, date(2020, 2, 17), 108.0, 110.0),
        _bmw("BMW", "118i", "benzin", 41000.0, date(2020, 2, 17), 145.0, 103.0),
    ]
    canonical_rows = apply_mapping(rows, BMW_HEADER, BMW_MAPPING, "bmw.xlsx", "Cjenik")
    assert len(canonical_rows) == 2
    d = _to_catalogue_dict(canonical_rows[0], _co2_standard_from_year(2020), allowed_brands=("BMW",))
    assert d is not None
    # No redundant "BMW" prefix — the frontend/ingest layer already prefixes
    # the brand itself when displaying/building the catalogue row.
    assert d["model"] == "serije 1"
    assert d["variant"] == "116d"  # full_name/type_code absent here, so variant still falls back to the trim


def test_no_series_name_keeps_model_name_as_model():
    from app.data.catalogues.ingest import _to_catalogue_dict, _co2_standard_from_year

    rows = [_vw("VW", "VW001", "Golf TDI", "VW Golf 8 2.0 TDI", "D", 32000.0, date(2025, 1, 1), 130.0, 110.0)]
    canonical_rows = apply_mapping(rows, VW_HEADER, VW_MAPPING, "vw.xlsx", "Cjenik")
    assert len(canonical_rows) == 1
    d = _to_catalogue_dict(canonical_rows[0], _co2_standard_from_year(2025), allowed_brands=("Volkswagen",))
    assert d is not None
    assert d["model"] == "Golf TDI"


# ===========================================================================
# Integration test placeholder — skipped, requires real DB + API key
# ===========================================================================

@pytest.mark.integration
def test_ingest_cli_smoke():
    """Full round-trip: LLM → apply_mapping → DB insert. Requires real env."""
    pytest.skip("Integration: needs OPENROUTER_API_KEY + running DB")
