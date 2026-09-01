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

import re
from dataclasses import dataclass, replace
from datetime import date, datetime
from enum import Enum

from app.core.config import get_settings


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

    # None when the sheet has no brand column — the brand then comes from the file's folder-group (snap_brand)
    # or the model/variant text, never guessed by the LLM
    brand_column: str | None
    model_name_column: str | None
    # whatever this sheet uses as its closest thing to a stable code (MODEL KOD / KOD MODELA / model / etc —
    # name varies per family)
    type_code_column: str | None
    # KOMPLETNO IME / kompletno ime — human-readable, used as fallback display/dedup aid, NOT the lookup key
    full_name_column: str | None
    # None when the sheet has no fuel column — fuel is then derived from the model/variant engine text
    # (TDI/TFSI/dCi/...), see ingest._override_fuel_from_variant
    fuel_column: str | None
    price_column: str
    # "EUR" or "HRK" — read from the column header text itself (e.g. "(kn)" vs "(EUR)"), not guessed from date
    price_currency: str
    # None when the sheet has no validity-date column — the date then comes from the filename
    # (default_valid_from), never guessed
    valid_from_column: str | None
    co2_column: str | None  # single CO2 column, if this format has one
    co2_min_column: str | None  # Mercedes-style split
    co2_max_column: str | None
    power_kw_column: str | None
    plug_in_range_column: str | None  # PLUG-IN (DOSEG) / doseg
    seats_7plus1_column: str | None
    seats_8plus1_column: str | None
    camper_column: str | None
    pickup_8704_column: str | None  # KN 8704 pick-up flag — different PPMV formula entirely (PP = S x KS)
    # only relevant for motorcycle/ATV KO coefficient — out of scope per MASTER_PLAN_v7, kept for completeness
    euro_norm_column: str | None

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
    # model-line/series name recovered from a section-header banner row (e.g. 'BMW serije 1'), None when the
    # sheet has no such banner — see _detect_series_banner. model_name stays the raw trim/type text either way
    # (still needed for fuel-badge derivation).
    series_name: str | None
    # raw value from whatever column the mapping pointed at — meaning/uniqueness varies per source, do not
    # assume global uniqueness
    type_code: str | None
    full_name: str | None

    fuel_category: FuelCategory
    fuel_raw_value: str  # original source value, kept for audit when fuel_category is UNKNOWN

    price_eur: float
    # "EUR" or "HRK", as detected — kept even after normalization, for traceability
    price_source_currency: str
    price_raw_value: float  # pre-normalization, in source_currency

    valid_from: date

    co2_g_km: float | None  # resolved single value (see co2_resolution_policy)
    co2_min_g_km: float | None  # raw, if source had a min/max split
    co2_max_g_km: float | None
    # e.g. "max" / "min" / "average" / "single_column" — records how co2_g_km was derived, for auditability
    co2_resolution_policy: str | None

    power_kw: float | None  # base kW, hybrid boost suffix (e.g. "+16") stripped into power_boost_kw
    # the "+NN" mild-hybrid boost component, if present; None if source had a plain number
    power_boost_kw: float | None

    # drives the plug-in PPMV reduction in engine.py; None if not a plug-in or column absent
    plug_in_range_km: float | None

    is_camper: bool
    # different PPMV formula entirely (PP = S x KS), out of scope for the standard calculate_ppmv() path
    is_pickup_8704: bool
    seats_7plus1: bool
    seats_8plus1: bool

    source_file: str
    source_sheet: str
    source_row_index: int  # 1-indexed row in the original sheet, for traceability/debugging back to the Excel

    mapping_confidence: float  # copied from the ColumnMapping that produced this row
    # True if fuel_category is UNKNOWN, co2/price missing, or mapping_confidence below threshold
    needs_review: bool


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


# Below this confidence, a row is flagged needs_review even if every field
# parsed cleanly — separate from (and lower-stakes than) the CLI's
# whole-sheet ingestion gate in scripts/ingest_catalogue.py, which decides
# whether to attempt a sheet at all.
NEEDS_REVIEW_CONFIDENCE_THRESHOLD = 0.7

# Fuel vocabulary confirmed against the 4 known format families. Letter
# codes are VW-group's (and, confirmed against real Porsche files,
# Porsche's too — Porsche's column NAMES differ but its fuel CODES turned
# out to be the same B/D scheme, not "different vocabulary" as originally
# assumed; see apply_mapping module notes). 'H' is plug-in (not plain
# hybrid) per real VW data: e-tron/GTE rows coded 'H' have a populated
# PLUG-IN (DOSEG) value and near-zero CO2. Any code/word not listed here
# (e.g. VW's 'G' for Erdgas/CNG) deliberately falls through to UNKNOWN —
# there is no GAS category, and guessing one would violate the "never
# silently default" rule in FuelCategory's docstring.
_LETTER_CODE_FUEL_MAP: dict[str, FuelCategory] = {
    "D": FuelCategory.DIESEL,
    "B": FuelCategory.PETROL,
    "MH": FuelCategory.PETROL_HYBRID,
    "H": FuelCategory.PETROL_PLUG_IN_HYBRID,
    "E": FuelCategory.ELECTRIC,
}

# Spelled-out words confirmed across BMW ('benzin'/'diesel') and Mercedes
# ('benzin'/'dizel') — note BMW spells diesel the English way, Mercedes
# the Croatian way; both must be recognized. Neither family's spelled-out
# vocabulary distinguishes mild-hybrid/plug-in from plain petrol (unlike
# VW's MH/H codes), so that distinction is recovered separately from the
# power-boost-suffix and plug-in-range signals in _categorize_fuel.
_WORD_FUEL_MAP: dict[str, FuelCategory] = {
    "dizel": FuelCategory.DIESEL,
    "diesel": FuelCategory.DIESEL,
    "benzin": FuelCategory.PETROL,
    "petrol": FuelCategory.PETROL,
    "elektro": FuelCategory.ELECTRIC,
    "električni": FuelCategory.ELECTRIC,
    "electric": FuelCategory.ELECTRIC,
}

_EUR_HEADER_PATTERN = re.compile(r"eur|€", re.IGNORECASE)
_HEADER_WORD_PATTERN = re.compile(r"[a-zčćžšđ]+", re.IGNORECASE)

_WHITESPACE_RE = re.compile(r"\s+")

# The 17 columns of a ColumnMapping that name a source header cell (everything
# except price_currency/confidence/notes). Used by the fingerprint key, the
# per-sheet LLM enum schema, and the header-resolution pre-pass so all three
# stay in lockstep.
COLUMN_FIELDS: tuple[str, ...] = (
    "brand_column", "model_name_column", "type_code_column", "full_name_column",
    "fuel_column", "price_column", "valid_from_column", "co2_column",
    "co2_min_column", "co2_max_column", "power_kw_column", "plug_in_range_column",
    "seats_7plus1_column", "seats_8plus1_column", "camper_column",
    "pickup_8704_column", "euro_norm_column",
)


def normalize_cell(cell: str) -> str:
    """Canonical form of a header cell for fingerprinting and fuzzy column
    lookup: newlines→space, whitespace collapsed, lowercased, surrounding
    punctuation stripped. Collapses the trivially-different spellings that
    otherwise fork a header into distinct layouts (`'CO2\\n(g/km)'` vs
    `'CO2 (g/km)'`) and would each cost their own LLM call. Internal
    punctuation is preserved, so Porsche's `osnovna_cijena_kn` stays intact."""
    s = cell.replace("\n", " ").strip().lower()
    s = _WHITESPACE_RE.sub(" ", s)
    return s.strip(" .:-")


def _resolve_columns(mapping: "ColumnMapping", header_row: list[str]) -> "ColumnMapping":
    """Snap each of a mapping's source-column names to the exact header string
    present in THIS sheet. A cached mapping may have been learned from a
    near-identical header (`'CO2 (g/km)'`) and now be applied to a sheet whose
    header differs only cosmetically (`'CO2\\n(g/km)'`); without this, the exact
    lookup in `_cell` misses and every affected column silently drops. Values
    that already match exactly, or match nothing at all, are left untouched
    (the latter then resolve to None in `_cell`, as before)."""
    exact = set(header_row)
    norm_to_exact: dict[str, str] = {}
    for name in header_row:
        n = normalize_cell(name)
        if n and n not in norm_to_exact:
            norm_to_exact[n] = name

    def fix(value: str | None) -> str | None:
        if value is None or value in exact:
            return value
        return norm_to_exact.get(normalize_cell(value), value)

    return replace(mapping, **{f: fix(getattr(mapping, f)) for f in COLUMN_FIELDS})


def _is_blank(value: object) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _to_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


# Strips a trailing chassis/generation code in parentheses off a banner's
# series text, e.g. "BMW serije 1 (F40)" -> "BMW serije 1",
# "MINI CLUBMAN(F54)" -> "MINI CLUBMAN". Left in place if there's nothing
# else in the string (defensive; not seen in practice).
_CHASSIS_CODE_SUFFIX_RE = re.compile(r"\(\s*[A-Za-z0-9]+\s*\)\s*$")


def _clean_series_text(text: str) -> str:
    cleaned = _CHASSIS_CODE_SUFFIX_RE.sub("", text).strip()
    return cleaned or text.strip()


def _strip_leading_brand(text: str, brand_text: str | None) -> str:
    """Strip a redundant leading brand-name token from banner series text.
    Confirmed against real files: some source sheets bake the brand into the
    banner cell ('BMW serije i3', 'BMW  serija X1 SAV (F48)'), others don't
    ('Serija 1 (F20)') — inconsistent even within the same brand. Every
    downstream consumer of the resulting model text (ingest.py's `model`
    field, the frontend's `{brand} {model}` display) already prefixes the
    brand itself, so a source-side repeat would otherwise show up as a
    visible 'BMW BMW serije 3' duplicate. brand_text is already the sheet's
    lowercased typical brand-cell text (see _typical_brand_cell_text), so a
    straight lowercase-prefix check is enough — no need to re-derive it."""
    if not brand_text:
        return text
    stripped = text.strip()
    if stripped.lower().startswith(brand_text):
        rest = stripped[len(brand_text):].lstrip()
        return rest or stripped
    return stripped


def _is_numeric_like(value: object) -> bool:
    """True for a number or a purely numeric string — mirrors ingest.py's
    _looks_numeric (duplicated rather than imported: canonical_schema is the
    pure/deterministic layer ingest.py depends on, not the reverse)."""
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return True
    if isinstance(value, str):
        s = value.strip().replace(".", "").replace(",", "").replace(" ", "")
        return s.isdigit()
    return False


def _typical_brand_cell_text(rows: list[tuple], brand_col_idx: int | None) -> str | None:
    """The most common non-blank value at the brand column across a sheet's
    rows — a sheet's real data rows all repeat the same plain brand string
    ('BMW ', 'VW', ...), so this is what a genuine brand cell looks like on
    THIS sheet. Used to tell a banner ('BMW serije 1 (F40)') apart from an
    ordinary row that merely happens to have only its brand cell populated
    (e.g. a malformed row) — both are 'one populated text cell in the brand
    column', but only the banner's text differs from the sheet's norm."""
    if brand_col_idx is None:
        return None
    counts: dict[str, int] = {}
    for row in rows:
        if brand_col_idx >= len(row):
            continue
        text = _to_str(row[brand_col_idx])
        if text is None:
            continue
        key = text.strip().lower()
        counts[key] = counts.get(key, 0) + 1
    if not counts:
        return None
    return max(counts, key=lambda k: counts[k])


def _detect_series_banner(
    row: tuple, brand_col_idx: int | None, typical_brand_text: str | None
) -> str | None:
    """BMW/MINI-style sheets interleave section-header rows carrying the
    model series name (e.g. 'BMW serije 1 (F40)', 'MINI CLUBMAN(F54)')
    between blocks of trim rows, with every other cell in the row blank —
    confirmed against real BMW/MINI files, always sitting in the brand
    column. Requires ALL of: exactly one populated NON-NUMERIC cell in the
    whole row; that cell is the mapped brand column (not any arbitrary
    column — a stray junk cell elsewhere isn't a banner); and its text
    differs from the sheet's normal brand string (excludes an ordinary
    malformed row that merely repeats the plain brand, e.g. a lone 'VW'
    with everything else blank — that's junk, not a banner, and must NOT
    get forward-filled as a fake series). No brand_col_idx (sheet has no
    brand column mapped) always returns None — conservative default, since
    banner text has nowhere reliable to live.

    Numeric cells elsewhere in the row are ignored rather than disqualifying
    the row: confirmed against a real file (bmw-mini/2018), some vertically-
    merged source columns (e.g. BROJ SJEDALA) leak their value into every row
    of a block, including banner rows, via openpyxl's read of the merge — a
    real banner row would otherwise be silently rejected (falling back to
    the PREVIOUS series and forward-filling it onto the wrong section, e.g.
    an X1 SAV block inheriting the prior '7 Series' banner). A genuine data
    row always has more than one non-numeric cell (model name text, at
    least), so this stays conservative — it can't newly misread a real data
    row as a banner."""
    if brand_col_idx is None or typical_brand_text is None:
        return None
    text_cells = [(j, c) for j, c in enumerate(row) if not _is_blank(c) and not _is_numeric_like(c)]
    if len(text_cells) != 1:
        return None
    idx, value = text_cells[0]
    if idx != brand_col_idx:
        return None
    text = _to_str(value)
    if not text or text.strip().lower() == typical_brand_text:
        return None
    return _strip_leading_brand(_clean_series_text(text), typical_brand_text)


def _to_bool(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in ("da", "yes", "true", "1", "x")


def _parse_numeric(value: object) -> float | None:
    """Parses ints/floats and numeric-looking strings, including BMW's
    trailing-asterisk footnote marker (e.g. CO2 '122*', power '230*') —
    confirmed present in real BMW files, unrelated to the '+NN' hybrid
    boost suffix handled separately in _parse_power."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().rstrip("*").strip().replace(",", ".")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _parse_power(value: object) -> tuple[float | None, float | None]:
    """Splits Mercedes-style hybrid boost suffixes (e.g. '380+16' kW ->
    base 380, boost 16). Plain numeric power (int, float, or a bare
    numeric string) has no boost component."""
    if value is None:
        return None, None
    if isinstance(value, (int, float)):
        return float(value), None
    text = str(value).strip()
    if not text:
        return None, None
    if "+" in text:
        base_part, boost_part = text.split("+", 1)
        return _parse_numeric(base_part), _parse_numeric(boost_part)
    return _parse_numeric(text), None


def _parse_date(value: object) -> date | None:
    """Real catalogue files mix native Excel dates with VRIJEDI OD as
    plain strings — confirmed formats: 'DD.MM.YYYY.' (BMW 2020, trailing
    dot), 'DD.MM.YYYY' (BMW 2023, no trailing dot), and 'D.M.YYYY.'
    (single-digit day/month seen in one BMW sheet)."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        text = value.strip().rstrip(".")
        parts = text.split(".")
        if len(parts) != 3:
            return None
        try:
            day, month, year = (int(part) for part in parts)
        except ValueError:
            return None
        # 2-digit day-first years ("01.06.26" → 2026): confirmed in real BAIC
        # files, where the naive parse produced year 26 (date 0026-06-01) and
        # leaked into the DB. Interpret as 20YY.
        if year < 100:
            year += 2000
        # Reject implausible years rather than store a garbage date — mirrors
        # parse_date._valid's guard so a mis-split cell fails cleanly (and then
        # falls back to the filename date) instead of poisoning the table.
        if not (2000 <= year <= 2035 and 1 <= month <= 12 and 1 <= day <= 31):
            return None
        try:
            return date(year, month, day)
        except ValueError:
            return None
    return None


def _detect_currency_from_header(header: str | None) -> str | None:
    """Reads currency off the price column's own header text rather than
    trusting ColumnMapping.price_currency blindly — a defensive
    cross-check in the same spirit as llm_mapper's hallucinated-column
    rejection. Handles both '(kn)'/'(EUR)'/'(€)' parenthetical styles
    (VW/BMW/Mercedes) and Porsche's currency-in-the-identifier style
    ('osnovica_kn', no parens) by tokenizing on letters only, so 'kn'
    must appear as its own word/token rather than as a substring."""
    if not header:
        return None
    if _EUR_HEADER_PATTERN.search(header):
        return "EUR"
    if "kn" in _HEADER_WORD_PATTERN.findall(header.lower()):
        return "HRK"
    return None


def _categorize_fuel(
    fuel_raw: object,
    power_boost_kw: float | None,
    plug_in_range_km: float | None,
) -> FuelCategory:
    """Letter codes (D/B/MH/H/E) are unambiguous on their own — confirmed
    against real VW data that 'H' rows are themselves already plug-in
    (populated DOSEG, near-zero CO2), not plain hybrid. Spelled-out words
    ('benzin'/'dizel'/'diesel') only ever mean plain petrol/diesel in the
    BMW/Mercedes files seen, so mild-hybrid and plug-in have to be
    recovered from other columns for those families: Mercedes signals
    mild-hybrid via the power '+NN' boost suffix (e.g. GLS 580 '380+16'),
    and Porsche signals plug-in via a populated doseg/plug-in-range column
    even though its GORIVO value is plain 'B' (e.g. Cayenne S e-hybrid).
    Anything unrecognized (e.g. VW's 'G' for Erdgas/CNG) is UNKNOWN —
    never guessed into petrol/diesel."""
    text = _to_str(fuel_raw)
    if text is None:
        return FuelCategory.UNKNOWN

    base = _LETTER_CODE_FUEL_MAP.get(text.upper())
    if base is None:
        base = _WORD_FUEL_MAP.get(text.lower())
    if base is None:
        return FuelCategory.UNKNOWN

    if base is FuelCategory.PETROL:
        if plug_in_range_km is not None and plug_in_range_km > 0:
            return FuelCategory.PETROL_PLUG_IN_HYBRID
        if power_boost_kw is not None and power_boost_kw > 0:
            return FuelCategory.PETROL_HYBRID

    return base


def _resolve_co2(
    co2_raw: object,
    co2_min_raw: object,
    co2_max_raw: object,
    policy: str,
) -> tuple[float | None, float | None, float | None, str | None]:
    co2_min = _parse_numeric(co2_min_raw)
    co2_max = _parse_numeric(co2_max_raw)
    if co2_min is not None or co2_max is not None:
        if policy == "max":
            resolved = co2_max if co2_max is not None else co2_min
        elif policy == "min":
            resolved = co2_min if co2_min is not None else co2_max
        elif policy == "average":
            if co2_min is not None and co2_max is not None:
                resolved = (co2_min + co2_max) / 2
            else:
                resolved = co2_max if co2_max is not None else co2_min
        else:
            raise ValueError(f"Unknown co2_min_max_policy: {policy!r}")
        return resolved, co2_min, co2_max, policy

    single = _parse_numeric(co2_raw)
    if single is not None:
        return single, None, None, "single_column"
    return None, None, None, None


def _cell(row: tuple, column_index: dict[str, int], column_name: str | None) -> object:
    if column_name is None:
        return None
    index = column_index.get(column_name)
    if index is None or index >= len(row):
        return None
    return row[index]


def _is_junk_row(
    model_name_column: str | None,
    model_name_raw: object,
    fuel_raw: object,
    price_raw: object,
) -> bool:
    """Confirmed against real BMW files: section-header rows (e.g. 'BMW
    serije 1 (F40)' sitting alone in the brand column) and stray
    misplaced values (e.g. the HRK/EUR conversion rate sitting alone in
    the price column) both leave the model-name column blank — so 'model
    name blank' alone catches both junk shapes seen so far without
    needing to pattern-match specific header strings, which wouldn't
    generalize to unseen files anyway. Falls back to 'fuel AND price both
    blank' when a sheet has no model_name_column at all, so that case
    doesn't mark every row in such a sheet as junk."""
    if model_name_column is not None:
        return _is_blank(model_name_raw)
    return _is_blank(fuel_raw) and _is_blank(price_raw)


def apply_mapping(
    rows: list[tuple],
    header_row: list[str],
    mapping: ColumnMapping,
    source_file: str,
    source_sheet: str,
    co2_min_max_policy: str = "max",
    skip_log: list[tuple[int, str]] | None = None,
    default_valid_from: date | None = None,
) -> list[CanonicalRow]:
    """Deterministic, pure — applies an already-computed ColumnMapping to
    every data row in a sheet. No LLM calls happen here; this is plain
    pandas-equivalent row transformation, safe to re-run and unit test
    without any API cost.

    rows must be the sheet's data rows only (header_row already stripped
    out), each a tuple positionally aligned with header_row — e.g.
    `openpyxl`'s `ws.iter_rows(values_only=True)` after consuming the
    first row. source_row_index on the resulting CanonicalRow is computed
    as rows-offset + 2 (1-indexed, plus one for the header row), so it
    points back at the real Excel row.

    co2_min_max_policy: how to resolve CO2 when a sheet splits it into
    min/max columns (Mercedes-style). Default "max" is the more
    conservative choice for tax purposes (higher CO2 = higher tax, so
    defaulting to the lower min figure could understate a real liability
    if challenged) — but this is a judgment call, not a verified rule
    from carina.gov.hr, and should be confirmed before relying on it.

    skip_log: if provided, every dropped row appends an
    (source_row_index, reason) tuple — used by scripts/ingest_catalogue.py
    to print a reason breakdown without re-walking the rows.

    default_valid_from: the validity date parsed from the filename. Used as the
    row's valid_from whenever the sheet has no valid_from column (mapping.
    valid_from_column is None) or its cell is blank/unparseable — the customs
    file is named for the date its prices take effect, so this is the correct
    value, not a guess. When None (e.g. isolated unit tests), the old
    "drop rows without a parseable date" behaviour is preserved.
    """
    mapping = _resolve_columns(mapping, header_row)
    column_index = {name: i for i, name in enumerate(header_row)}
    settings = get_settings()
    results: list[CanonicalRow] = []

    # Updated whenever a section-header banner row is seen (BMW/MINI-style
    # sheets); carried forward onto every subsequent data row as series_name
    # until the next banner. Stays None for sheets with no banner rows at
    # all (Audi, etc.) — those are entirely unaffected by this.
    current_series: str | None = None
    brand_col_idx = column_index.get(mapping.brand_column) if mapping.brand_column else None
    typical_brand_text = _typical_brand_cell_text(rows, brand_col_idx)

    # Defined once rather than per row: a closure built inside the loop would
    # capture `source_row_index` by reference, so it only happened to log the
    # right row because every call fired in the same iteration (ruff B023).
    def log_skip(row_index: int, reason: str) -> None:
        if skip_log is not None:
            skip_log.append((row_index, reason))

    for offset, row in enumerate(rows):
        source_row_index = offset + 2

        banner = _detect_series_banner(row, brand_col_idx, typical_brand_text)
        if banner is not None:
            current_series = banner
            log_skip(source_row_index, "series_banner")
            continue

        model_name_raw = _cell(row, column_index, mapping.model_name_column)
        fuel_raw = _cell(row, column_index, mapping.fuel_column)
        price_raw = _cell(row, column_index, mapping.price_column)

        if _is_junk_row(mapping.model_name_column, model_name_raw, fuel_raw, price_raw):
            log_skip(source_row_index, "junk_row")
            continue

        # No brand column at all → leave brand empty and let the ingest layer
        # snap it from the file's folder-group (single-marque folders) or the
        # model/variant text. When the sheet DOES have a brand column but this
        # row's cell is blank, that's a section-header/junk row, so still skip.
        if mapping.brand_column is None:
            brand = ""
        else:
            brand = _to_str(_cell(row, column_index, mapping.brand_column))
            if brand is None:
                log_skip(source_row_index, "missing_brand")
                continue

        price_value = _parse_numeric(price_raw)
        if price_value is None:
            log_skip(source_row_index, "missing_price")
            continue
        if price_value <= 0:
            # A €0 (or negative) as-new price is never a real catalogue entry —
            # it's a stray/placeholder cell (confirmed: one Mercedes S 450 row).
            # Ingesting it would silently zero out a PPMV calculation.
            log_skip(source_row_index, "nonpositive_price")
            continue

        currency = _detect_currency_from_header(mapping.price_column) or mapping.price_currency
        if currency == "HRK":
            price_eur = round(price_value / settings.hrk_to_eur_rate, 2)
        elif currency == "EUR":
            price_eur = price_value
        else:
            log_skip(source_row_index, "unrecognized_currency")
            continue

        # Prefer the sheet's own date column; fall back to the filename date
        # (default_valid_from) when the sheet has no such column or the cell is
        # blank/unparseable — the file is named for its effective date.
        valid_from = None
        if mapping.valid_from_column is not None:
            valid_from = _parse_date(_cell(row, column_index, mapping.valid_from_column))
        if valid_from is None:
            valid_from = default_valid_from
        if valid_from is None:
            log_skip(source_row_index, "missing_or_unparseable_valid_from")
            continue

        power_kw, power_boost_kw = _parse_power(_cell(row, column_index, mapping.power_kw_column))
        plug_in_range_km = _parse_numeric(_cell(row, column_index, mapping.plug_in_range_column))

        fuel_category = _categorize_fuel(fuel_raw, power_boost_kw, plug_in_range_km)

        co2_g_km, co2_min_g_km, co2_max_g_km, co2_policy = _resolve_co2(
            _cell(row, column_index, mapping.co2_column),
            _cell(row, column_index, mapping.co2_min_column),
            _cell(row, column_index, mapping.co2_max_column),
            co2_min_max_policy,
        )
        if co2_g_km is None:
            log_skip(source_row_index, "missing_co2")
            continue

        results.append(
            CanonicalRow(
                brand=brand,
                model_name=_to_str(model_name_raw),
                series_name=current_series,
                type_code=_to_str(_cell(row, column_index, mapping.type_code_column)),
                full_name=_to_str(_cell(row, column_index, mapping.full_name_column)),
                fuel_category=fuel_category,
                fuel_raw_value=_to_str(fuel_raw) or "",
                price_eur=price_eur,
                price_source_currency=currency,
                price_raw_value=price_value,
                valid_from=valid_from,
                co2_g_km=co2_g_km,
                co2_min_g_km=co2_min_g_km,
                co2_max_g_km=co2_max_g_km,
                co2_resolution_policy=co2_policy,
                power_kw=power_kw,
                power_boost_kw=power_boost_kw,
                plug_in_range_km=plug_in_range_km,
                is_camper=_to_bool(_cell(row, column_index, mapping.camper_column)),
                is_pickup_8704=_to_bool(_cell(row, column_index, mapping.pickup_8704_column)),
                seats_7plus1=_to_bool(_cell(row, column_index, mapping.seats_7plus1_column)),
                seats_8plus1=_to_bool(_cell(row, column_index, mapping.seats_8plus1_column)),
                source_file=source_file,
                source_sheet=source_sheet,
                source_row_index=source_row_index,
                mapping_confidence=mapping.confidence,
                needs_review=(
                    fuel_category is FuelCategory.UNKNOWN
                    or mapping.confidence < NEEDS_REVIEW_CONFIDENCE_THRESHOLD
                ),
            )
        )

    return results
