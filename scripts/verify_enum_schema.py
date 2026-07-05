"""Cheap pre-flight check: does the configured model honour the per-sheet
ENUM-constrained structured output (llm_mapper.USE_ENUM_SCHEMA)?

The rework's strongest anti-hallucination measure builds a JSON schema whose
every *_column field is an enum of the sheet's real header cells (+ null). This
only helps if OpenRouter + DeepSeek-V4-Flash actually enforce enum under
strict structured output. This script makes ONE real API call (~$0) on a
Dacia-style header that deliberately has NO brand/valid_from column, and checks
that the model returns null for those (rather than inventing MARKA/VRIJEDI OD)
and picks real header strings for the rest.

Run BEFORE the one paid full build:
    .venv/bin/python -m scripts.verify_enum_schema

If it fails or errors, set llm_mapper.USE_ENUM_SCHEMA = False (the nullable
static schema + hardened prompt + post-hoc guard still apply) and re-run.
"""

import asyncio
import sys

from app.catalogue import llm_mapper
from app.catalogue.llm_mapper import map_sheet_columns


HEADER = [
    "OPREMA", "MODEL", "GORIVO", "MOTOR", "kW (KS)", "CO2 (g/km)",
    "CIJENA ZA KUPCA S PDV-OM",
]
SAMPLE_ROWS = [
    ("Comfort", "Logan TCe 90", "B", "1.0", "66 (90)", 120, 15000.0),
    ("Prestige", "Duster dCi 115", "D", "1.5", "85 (115)", 130, 22000.0),
]


async def _run() -> int:
    print(f"USE_ENUM_SCHEMA = {llm_mapper.USE_ENUM_SCHEMA}")
    print(f"Model            = {llm_mapper.get_settings().openrouter_model}")
    print(f"Header (no brand/valid_from column): {HEADER}\n")
    try:
        mapping = await map_sheet_columns(HEADER, SAMPLE_ROWS)
    except Exception as exc:  # noqa: BLE001 — surface any failure verbatim
        print(f"FAIL — call raised {type(exc).__name__}: {exc}")
        print("If this is an HTTP 400 about the schema, the model likely does "
              "not accept enum-constrained output — set USE_ENUM_SCHEMA=False.")
        return 1

    print("Returned mapping:")
    for field in ("brand_column", "valid_from_column", "fuel_column",
                  "model_name_column", "price_column", "co2_column",
                  "power_kw_column", "confidence"):
        print(f"  {field:20s} = {getattr(mapping, field)!r}")

    ok = (
        mapping.brand_column is None
        and mapping.valid_from_column is None
        and mapping.price_column == "CIJENA ZA KUPCA S PDV-OM"
        and mapping.fuel_column == "GORIVO"
    )
    print()
    if ok:
        print("PASS — model returned null for the absent brand/valid_from "
              "columns and real header strings for the rest. Enum honoured.")
        return 0
    print("WARN — model did NOT return the expected nulls. Enum may be ignored; "
          "the post-hoc guard still protects correctness, but consider "
          "USE_ENUM_SCHEMA=False + rely on the nullable schema.")
    return 2


def main() -> None:
    sys.exit(asyncio.run(_run()))


if __name__ == "__main__":
    main()
