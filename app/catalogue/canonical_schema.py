"""Canonical intermediate schema for catalogue ingestion.

The problem: brand Excel files come from different importer groups with
genuinely different column schemas (confirmed across 4+ distinct families:
VW-group letter-coded, BMW spelled-out-with-section-headers, Mercedes
with split min/max CO2, Porsche with entirely different lowercase Croatian
column names and no shared header vocabulary). A fixed column-index or
column-name mapping cannot generalize across new files.

The solution: an LLM reads each sheet's header row once (plus a couple of
sample data rows for context) and returns a ColumnMapping — which source
column (by name) corresponds to each canonical field. This mapping is then
applied deterministically to every row in that sheet with plain pandas; the
LLM never sees or transforms per-row data values, so cost stays near-zero
(one call per sheet, not per row) and there's no risk of it inventing
numbers.

Two-stage pipeline:
  1. map_sheet_columns(header_row, sample_rows) -> ColumnMapping   [LLM, stubbed]
  2. apply_mapping(sheet_rows, mapping) -> list[CanonicalRow]      [deterministic, pure]
"""

from dataclasses import dataclass
from datetime import date
from enum import Enum


class FuelCategory(str, Enum):
    """Canonical fuel category, AFTER mapping from whatever source value
    appeared (D/B/MH/H/E, 'benzin'/'dizel', spelled-out English, etc).

    Mapping notes (confirmed against carina.gov.hr worked examples):
    - DIESEL / PETROL: feed the PPMV eco tables directly (Tables 2/3/5/6).
    - PETROL_HYBRID (mild hybrid, no plug): no separate tax table — taxed
      as ordinary PETROL using the combined-cycle CO2 already in the file.
    - PETROL_PLUG_IN_HYBRID: taxed as PETROL eco table, then the *whole*
      PPMV gets an extra reduction equal to the electric range in km
      (see plug_in_range_km below) — confirmed via official example 4.
    - ELECTRIC: CO2 = 0 g/km vehicles are PPMV-exempt by law. Not "petrol
      with 0 CO2" — engine.py must special-case this, not run bracket math.
    - UNKNOWN: source fuel value didn't match any known code/word. Row
      should be flagged for manual review, never silently defaulted to
      petrol or diesel.
    """
    DIESEL = "diesel"
    PETROL = "petrol"
    PETROL_HYBRID = "petrol_hybrid"  # mild hybrid, taxed as petrol
    PETROL_PLUG_IN_HYBRID = "petrol_plug_in_hybrid"  # taxed as petrol + range-based PPMV reduction
    ELECTRIC = "electric"  # PPMV-exempt
    UNKNOWN = "unknown"  # needs manual review — never guess


@dataclass(frozen=True)
class ColumnMapping:
    """Which source column (by exact header string, as it appears in the
    sheet) corresponds to each canonical field. None means the field isn't
    present in this sheet at all (e.g. Porsche files have no PLUG-IN (DOSEG)
    column in the samples seen so far).

    co2_min_column / co2_max_column are separate from co2_column because
    Mercedes splits CO2 into two columns (observed spread: avg 11 g/km,
    max 17 g/km between min and max — too wide to silently average; see
    co2_min_max_policy on CanonicalRow for how this gets resolved).
    """

    brand_column: str
    model_name_column: str | None
    type_code_column: str | None  # whatever this sheet uses as its closest thing to a stable code (MODEL KOD / KOD MODELA / model / etc — name varies per family)
    full_name_column: str | None  # KOMPLETNO IME / kompletno ime — human-readable, used as fallback display/dedup aid, NOT the lookup key
    fuel_column: str
    price_column: str
    price_currency: str  # "EUR" or "HRK" — read from the column header text itself (e.g. "(kn)" vs "(EUR)"), not guessed from date
    valid_from_column: str
    co2_column: str | None  # single CO2 column, if this format has one
    co2_min_column: str | None  # Mercedes-style split
    co2_max_column: str | None
    power_kw_column: str | None
    plug_in_range_column: str | None  # PLUG-IN (DOSEG) / doseg
    seats_7plus1_column: str | None
    seats_8plus1_column: str | None
    camper_column: str | None
    pickup_8704_column: str | None  # KN 8704 pick-up flag — different PPMV formula entirely (PP = S x KS)
    euro_norm_column: str | None  # only relevant for motorcycle/ATV KO coefficient — out of scope per MASTER_PLAN_v7, kept for completeness

    # Confidence/audit trail — the LLM should always report this so low-
    # confidence mappings can be queued for human review rather than
    # silently ingested.
    confidence: float  # 0.0-1.0
    notes: str  # LLM's free-text explanation of any ambiguous calls


@dataclass(frozen=True)
class CanonicalRow:
    """One fully-normalized catalogue row, ready for a DB insert — but
    insertion/lookup-key design is intentionally NOT handled here (see
    module docstring; that's still blocked on resolving the cross-format
    identity problem). This is the contract between ingestion and whatever
    persistence step comes next.
    """

    brand: str
    model_name: str | None
    type_code: str | None  # raw value from whatever column the mapping pointed at — meaning/uniqueness varies per source, do not assume global uniqueness
    full_name: str | None

    fuel_category: FuelCategory
    fuel_raw_value: str  # original source value, kept for audit when fuel_category is UNKNOWN

    price_eur: float
    price_source_currency: str  # "EUR" or "HRK", as detected — kept even after normalization, for traceability
    price_raw_value: float  # pre-normalization, in source_currency

    valid_from: date

    co2_g_km: float | None  # resolved single value (see co2_resolution_policy)
    co2_min_g_km: float | None  # raw, if source had a min/max split
    co2_max_g_km: float | None
    co2_resolution_policy: str | None  # e.g. "max" / "min" / "average" / "single_column" — records how co2_g_km was derived, for auditability

    power_kw: float | None  # base kW, hybrid boost suffix (e.g. "+16") stripped into power_boost_kw
    power_boost_kw: float | None  # the "+NN" mild-hybrid boost component, if present; None if source had a plain number

    plug_in_range_km: float | None  # drives the plug-in PPMV reduction in engine.py; None if not a plug-in or column absent

    is_camper: bool
    is_pickup_8704: bool  # different PPMV formula entirely (PP = S x KS), out of scope for the standard calculate_ppmv() path
    seats_7plus1: bool
    seats_8plus1: bool

    source_file: str
    source_sheet: str
    source_row_index: int  # 1-indexed row in the original sheet, for traceability/debugging back to the Excel

    mapping_confidence: float  # copied from the ColumnMapping that produced this row
    needs_review: bool  # True if fuel_category is UNKNOWN, co2/price missing, or mapping_confidence below threshold


def map_sheet_columns(
    header_row: list[str],
    sample_data_rows: list[tuple],
) -> ColumnMapping:
    """STUBBED — wire in your own LLM call here.

    Should send `header_row` plus a few `sample_data_rows` (for
    disambiguation — e.g. telling 'CO2* (g/km)' apart from a genuinely
    unrelated column, or recognizing that a column full of '17.02.2020.'
    strings is a date despite not being typed as one) to an LLM, with a
    prompt instructing it to return ONLY a JSON object whose keys match
    ColumnMapping's fields and whose values are either an exact header
    string from header_row, or null.

    Deliberately NOT calling any LLM API directly — interface only.
    The caller wires in their own client/key per their own infra (see
    MASTER_PLAN_v7: catalogue ingestion uses "LLM API key" per Mario's
    own setup, not a hardcoded provider here).

    Raises:
        NotImplementedError: always, until wired in.
    """
    raise NotImplementedError(
        "Wire in your LLM API call here. Expected return: ColumnMapping "
        "built from the model's JSON response, validated against "
        "header_row (every non-null mapped value must actually appear "
        "in header_row, or this is a hallucinated column name)."
    )


def apply_mapping(
    rows: list[tuple],
    header_row: list[str],
    mapping: ColumnMapping,
    source_file: str,
    source_sheet: str,
    co2_min_max_policy: str = "max",
) -> list[CanonicalRow]:
    """Deterministic, pure — applies an already-computed ColumnMapping to
    every data row in a sheet. No LLM calls happen here; this is plain
    pandas-equivalent row transformation, safe to re-run and unit test
    without any API cost.

    co2_min_max_policy: how to resolve CO2 when a sheet splits it into
    min/max columns (Mercedes-style). Default "max" is the more
    conservative choice for tax purposes (higher CO2 = higher tax, so
    defaulting to the lower min figure could understate a real liability
    if challenged) — but this is a judgment call, not a verified rule
    from carina.gov.hr, and should be confirmed before relying on it.

    Raises:
        NotImplementedError: stub — fill in once ColumnMapping shape is
        validated against a real LLM response on at least the 4 known
        format families (VW-group, BMW, Mercedes, Porsche) plus one
        unseen file, to confirm the mapping generalizes as intended.
    """
    raise NotImplementedError("Implement once map_sheet_columns is wired in and validated.")