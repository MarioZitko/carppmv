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

# JSON schema OpenRouter enforces on the response. Field names mirror
# ColumnMapping exactly, so the response can be unpacked directly into it.
# All fields are nullable strings (a source column name) except
# confidence (float) and notes (string) — "null" means "this canonical
# field has no corresponding column in this sheet", which is a valid and
# expected answer (e.g. Porsche files have no PLUG-IN (DOSEG) column).
_COLUMN_MAPPING_SCHEMA = {
    "type": "object",
    "properties": {
        "brand_column": {"type": "string"},
        "model_name_column": {"type": ["string", "null"]},
        "type_code_column": {"type": ["string", "null"]},
        "full_name_column": {"type": ["string", "null"]},
        "fuel_column": {"type": "string"},
        "price_column": {"type": "string"},
        "price_currency": {"type": "string", "enum": ["EUR", "HRK"]},
        "valid_from_column": {"type": "string"},
        "co2_column": {"type": ["string", "null"]},
        "co2_min_column": {"type": ["string", "null"]},
        "co2_max_column": {"type": ["string", "null"]},
        "power_kw_column": {"type": ["string", "null"]},
        "plug_in_range_column": {"type": ["string", "null"]},
        "seats_7plus1_column": {"type": ["string", "null"]},
        "seats_8plus1_column": {"type": ["string", "null"]},
        "camper_column": {"type": ["string", "null"]},
        "pickup_8704_column": {"type": ["string", "null"]},
        "euro_norm_column": {"type": ["string", "null"]},
        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "notes": {"type": "string"},
    },
    "required": [
        "brand_column", "model_name_column", "type_code_column", "full_name_column",
        "fuel_column", "price_column", "price_currency", "valid_from_column",
        "co2_column", "co2_min_column", "co2_max_column", "power_kw_column",
        "plug_in_range_column", "seats_7plus1_column", "seats_8plus1_column",
        "camper_column", "pickup_8704_column", "euro_norm_column",
        "confidence", "notes",
    ],
    "additionalProperties": False,
}

_SYSTEM_PROMPT = """You map column headers from Croatian car-import customs \
catalogue Excel files to a fixed canonical schema. These files come from \
different car importer groups (VW Group, BMW, Mercedes, Porsche, etc.) and \
use inconsistent column names, casing, and languages (Croatian/English mix).

For each canonical field below, return the EXACT header string from the \
provided header row that corresponds to it, or null if no column in this \
sheet represents that field. Do not invent or guess column names that are \
not literally present in the header row provided.

Canonical fields and what they mean:
- brand_column: vehicle brand/manufacturer (e.g. "MARKA", "marka")
- model_name_column: model name (e.g. "TRGOVAČKI NAZIV", "MODEL")
- type_code_column: any internal type/model code column, even if its \
  uniqueness or stability is unclear (e.g. "MODEL KOD", "KOD MODELA", \
  "model"). If multiple candidate code columns exist, prefer the one that \
  appears most specific to a single priced variant, and explain your choice \
  in notes.
- full_name_column: human-readable full descriptive name (e.g. "KOMPLETNO IME")
- fuel_column: fuel type column, REQUIRED (e.g. "GORIVO")
- price_column: as-new sale price column, REQUIRED. If both an HRK and a EUR \
  price column exist, prefer EUR.
- price_currency: "EUR" or "HRK" — read this from the price_column's header \
  text itself (e.g. "(kn)" = HRK, "(EUR)" or "(€)" = EUR), not guessed.
- valid_from_column: the date this price became valid, REQUIRED \
  (e.g. "VRIJEDI OD")
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


def map_sheet_columns(
    header_row: list[str],
    sample_data_rows: list[tuple],
    timeout_seconds: float = 30.0,
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
                "schema": _COLUMN_MAPPING_SCHEMA,
            },
        },
        "plugins": [{"id": "response-healing"}],
        "temperature": 0,
    }

    response = httpx.post(
        OPENROUTER_URL,
        headers={
            "Authorization": f"Bearer {settings.openrouter_api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=timeout_seconds,
    )
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

    return ColumnMapping(**parsed)