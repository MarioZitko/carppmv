"""LLM-based column mapping for catalogue ingestion, via OpenRouter.

Calls DeepSeek V4 Flash (cheap, fast, sufficient for header-row pattern
matching — this is not a reasoning-heavy task) with strict JSON-schema
structured output, so the response is guaranteed to parse into a
ColumnMapping without manual JSON repair.

One call per SHEET, never per row — the LLM only ever sees a header row
and a few sample rows for disambiguation; it never transforms or sees
bulk data, keeping both cost and hallucination risk near zero.
"""

import json

import httpx

from app.catalogue.canonical_schema import ColumnMapping
from app.core.config import get_settings

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# When True (recommended), the JSON schema sent per sheet constrains every
# *_column field to an ENUM of that sheet's actual header cells (+ null where
# the field is optional), so the model literally cannot emit a column name that
# isn't in the header — hallucination is eliminated at generation time, not
# caught after. If a provider/model ever rejects enum-constrained structured
# output, flip this to False to fall back to the static string schema below;
# the post-hoc hallucination guard still protects correctness either way.
# Verify with scripts/verify_enum_schema.py before the one paid full build.
USE_ENUM_SCHEMA = True

# Source-column fields the model maps. price_column is the only one that must
# be non-null (a priced catalogue row without a price is useless); every other
# field may legitimately be null when the sheet has no such column — brand,
# fuel and valid_from especially are OFTEN absent as columns (the value comes
# from the file's folder, the model text, or the filename respectively).
_NON_NULL_COLUMN_FIELDS = ("price_column",)
_NULLABLE_COLUMN_FIELDS = (
    "brand_column", "model_name_column", "type_code_column", "full_name_column",
    "fuel_column", "valid_from_column", "co2_column", "co2_min_column",
    "co2_max_column", "power_kw_column", "plug_in_range_column",
    "seats_7plus1_column", "seats_8plus1_column", "camper_column",
    "pickup_8704_column", "euro_norm_column",
)
_ALL_COLUMN_FIELDS = _NON_NULL_COLUMN_FIELDS + _NULLABLE_COLUMN_FIELDS

# Static fallback schema (used when USE_ENUM_SCHEMA is False). Field names
# mirror ColumnMapping exactly. brand/fuel/valid_from are nullable strings —
# null means "this sheet has no such column", a valid and expected answer.
_COLUMN_MAPPING_SCHEMA = {
    "type": "object",
    "properties": {
        **{f: {"type": ["string", "null"]} for f in _NULLABLE_COLUMN_FIELDS},
        "price_column": {"type": "string"},
        "price_currency": {"type": "string", "enum": ["EUR", "HRK"]},
        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "notes": {"type": "string"},
    },
    "required": [
        *_ALL_COLUMN_FIELDS, "price_currency", "confidence", "notes",
    ],
    "additionalProperties": False,
}


def _build_enum_schema(header_row: list[str]) -> dict:
    """Per-sheet schema whose every *_column field is an enum of this sheet's
    real header cells. Nullable fields also allow null; price_column does not.
    Deduplicated, order-preserving, blanks dropped — so the model can only ever
    return a column that actually exists (or null)."""
    cells: list[str] = []
    seen: set[str] = set()
    for c in header_row:
        if c and c.strip() and c not in seen:
            seen.add(c)
            cells.append(c)
    return {
        "type": "object",
        "properties": {
            **{f: {"enum": [*cells, None]} for f in _NULLABLE_COLUMN_FIELDS},
            "price_column": {"enum": list(cells)},
            "price_currency": {"type": "string", "enum": ["EUR", "HRK"]},
            "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
            "notes": {"type": "string"},
        },
        "required": [
            *_ALL_COLUMN_FIELDS, "price_currency", "confidence", "notes",
        ],
        "additionalProperties": False,
    }

_SYSTEM_PROMPT = """You map column headers from Croatian car-import customs \
catalogue Excel files to a fixed canonical schema. These files come from \
different car importer groups (VW Group, BMW, Mercedes, Porsche, etc.) and \
use inconsistent column names, casing, and languages (Croatian/English mix).

For each canonical field below, return the EXACT header string from the \
provided header row that corresponds to it, or null if no column in this \
sheet represents that field.

CRITICAL RULES:
- The provided header array is the ONLY allowed source for column names. Do \
NOT use prior knowledge of what these files usually contain. Never emit a \
Croatian label like "MARKA", "GORIVO" or "VRIJEDI OD" unless that exact \
string is literally one of the header cells provided.
- Returning null is CORRECT and EXPECTED whenever a field has no matching \
column. In particular brand, fuel and valid_from are frequently ABSENT as \
columns (the brand comes from the file's folder, the fuel from the model's \
engine text, the date from the filename) — when you don't see such a column, \
return null. Do NOT invent one, and do NOT return the literal string "null".
- Only price_column is mandatory; a priced catalogue always has a price \
column, so find it.

Example — header ["OPREMA","MODEL","GORIVO","MOTOR","kW (KS)","CO2 (g/km)",\
"CIJENA ZA KUPCA S PDV-OM"] has no brand column and no validity-date column, \
so the correct answer sets brand_column=null and valid_from_column=null \
(while fuel_column="GORIVO", price_column="CIJENA ZA KUPCA S PDV-OM", \
model_name_column="MODEL", co2_column="CO2 (g/km)", power_kw_column="kW (KS)").

Canonical fields and what they mean:
- brand_column: vehicle brand/manufacturer (e.g. "MARKA", "marka"), or null \
  if the sheet has no brand column
- model_name_column: model name (e.g. "TRGOVAČKI NAZIV", "MODEL")
- type_code_column: any internal type/model code column, even if its \
  uniqueness or stability is unclear (e.g. "MODEL KOD", "KOD MODELA", \
  "model"). If multiple candidate code columns exist, prefer the one that \
  appears most specific to a single priced variant, and explain your choice \
  in notes.
- full_name_column: human-readable full descriptive name (e.g. "KOMPLETNO IME")
- fuel_column: fuel type column (e.g. "GORIVO"), or null if the sheet has no \
  fuel column (fuel is then derived from the model's engine text)
- price_column: as-new sale price column, REQUIRED. If both an HRK and a EUR \
  price column exist, prefer EUR.
- price_currency: "EUR" or "HRK" — read this from the price_column's header \
  text itself (e.g. "(kn)" = HRK, "(EUR)" or "(€)" = EUR), not guessed.
- valid_from_column: the date this price became valid (e.g. "VRIJEDI OD"), \
  or null if the sheet has no such column (the date then comes from the \
  filename)
- co2_column: single CO2 g/km column, if the sheet has ONE such column
- co2_min_column / co2_max_column: if the sheet splits CO2 into separate \
  min/max columns instead of one column, use these two and leave \
  co2_column null. A sheet will have EITHER co2_column OR the min/max \
  pair, not both.
- power_kw_column: engine power in kW
- plug_in_range_column: plug-in hybrid electric range in km (e.g. \
  "PLUG-IN (DOSEG)")
- seats_7plus1_column / seats_8plus1_column: flags for 7+1 or 8+1 seat \
  configurations (these affect Croatian tax reductions)
- camper_column: camper/motorhome flag
- pickup_8704_column: pick-up truck customs tariff code 8704 flag
- euro_norm_column: EURO emissions standard (e.g. "EURO NORMA")

Some sheets interleave section-header rows (only one cell populated, no \
price) between data rows, or contain stray unrelated values (e.g. a lone \
currency conversion rate sitting in a cell). Use the sample data rows \
provided to recognize and avoid being misled by these when judging which \
column is which — but your output is ONLY the column mapping, not row \
filtering (that happens separately, after mapping).

Set confidence between 0.0 and 1.0 reflecting how certain you are about \
this mapping as a whole. Use notes to flag any ambiguous calls, especially \
around type_code_column choice or any field you could not confidently map."""


def _build_user_prompt(header_row: list[str], sample_data_rows: list[tuple]) -> str:
    sample_lines = []
    for row in sample_data_rows[:5]:
        sample_lines.append(str(list(row)))
    samples_block = "\n".join(sample_lines)
    return (
        f"Header row (in order):\n{json.dumps(header_row, ensure_ascii=False)}\n\n"
        f"Sample data rows (for disambiguation only):\n{samples_block}"
    )


async def map_sheet_columns(
    header_row: list[str],
    sample_data_rows: list[tuple],
    timeout_seconds: float = 60.0,
) -> ColumnMapping:
    """Calls OpenRouter (DeepSeek V4 Flash by default) with strict JSON-schema
    structured output and returns a validated ColumnMapping.

    Raises:
        RuntimeError: API call failed, or the response referenced a column
            name that doesn't actually appear in header_row (a hallucinated
            mapping — fail loudly rather than silently ingesting garbage).
        httpx.HTTPStatusError: non-2xx from OpenRouter.
    """
    settings = get_settings()
    if not settings.openrouter_api_key:
        raise RuntimeError(
            "OPENROUTER_API_KEY is not set. Add it to .env before running catalogue ingestion."
        )

    schema = _build_enum_schema(header_row) if USE_ENUM_SCHEMA else _COLUMN_MAPPING_SCHEMA
    payload = {
        "model": settings.openrouter_model,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": _build_user_prompt(header_row, sample_data_rows)},
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "column_mapping",
                "strict": True,
                "schema": schema,
            },
        },
        "plugins": [{"id": "response-healing"}],
        "temperature": 0,
    }

    request_kwargs = dict(
        url=OPENROUTER_URL,
        headers={
            "Authorization": f"Bearer {settings.openrouter_api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
    )
    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
        try:
            response = await client.post(**request_kwargs)
        except (httpx.TimeoutException, httpx.TransportError):
            # OpenRouter occasionally stalls a connection well past the read
            # timeout without erroring; one retry on a fresh connection clears it.
            response = await client.post(**request_kwargs)
    response.raise_for_status()
    data = response.json()

    try:
        content = data["choices"][0]["message"]["content"]
        parsed = json.loads(content)
    except (KeyError, IndexError, json.JSONDecodeError) as e:
        raise RuntimeError(f"Unexpected OpenRouter response shape: {data}") from e

    # Defensive validation: reject any non-null mapped column that doesn't
    # literally appear in header_row. strict:true schema mode constrains
    # JSON *shape*, not that string values are real header names — the
    # model could still hallucinate a plausible-looking column name.
    header_set = set(header_row)
    column_fields = [
        "brand_column", "model_name_column", "type_code_column", "full_name_column",
        "fuel_column", "price_column", "valid_from_column", "co2_column",
        "co2_min_column", "co2_max_column", "power_kw_column", "plug_in_range_column",
        "seats_7plus1_column", "seats_8plus1_column", "camper_column",
        "pickup_8704_column", "euro_norm_column",
    ]
    for field in column_fields:
        value = parsed.get(field)
        if value is not None and value not in header_set:
            raise RuntimeError(
                f"LLM mapped {field}={value!r}, which is not a real column "
                f"in this sheet's header row {header_row}. Rejecting "
                f"mapping rather than ingesting against a hallucinated column."
            )

    # ColumnMapping has no field defaults, so a nullable column the model
    # legitimately omits from its JSON (rather than emitting an explicit
    # null) crashes the constructor with "missing N required positional
    # arguments" — caught upstream as a deterministic mapping failure and
    # permanently blacklisting this header layout, silently dropping every
    # row of every file that shares it. price_column/price_currency are the
    # only genuinely required fields; every other column_fields entry is
    # optional (str | None) and safe to default to None here.
    for field in column_fields:
        if field != "price_column":
            parsed.setdefault(field, None)

    return ColumnMapping(**parsed)