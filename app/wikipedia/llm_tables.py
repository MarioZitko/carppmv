"""Phase 2 — LLM table extraction (DeepSeek V4 Flash via OpenRouter).

One call per TABLE, never per article or per brand (plan §Phase 2): prompts stay
small, the schema stays clean, and each extracted row keeps its own provenance.

Same narrow, bounded use of the model as catalogue/llm_mapper.py and
llm_sections.py: it structures what is literally printed in the wikitext it was
handed. It is never asked to estimate, infer from general knowledge, or fill a
CO2 value the table does not state — §0 of the plan makes null CO2 an expected,
valid outcome, and a model that "helpfully" supplies a plausible figure would
poison the tax calculation downstream with no way to tell.

Two shapes the prompt must handle, because the corpus contains both in bulk
(plan §Open items 6): a NORMAL table with one row per engine variant, and a
TRANSPOSED one with attributes down the left (``! Bauzeitraum``, ``!
CO<sub>2</sub>-Emission, kombiniert``) and one COLUMN per variant. The Audi A5
F5 example the plan was drafted against is transposed, which is the shape a
prompt tuned only on it would get right while silently mis-parsing the other.
So the model is asked to name the orientation it sees BEFORE extracting, and the
answer is cross-checked against tables.guess_orientation in the run report.

Output is an ARRAY of variants per call (plan §Open items 7) — one table yields
as many variants as it has engine columns or engine rows.
"""

import json
import logging
from dataclasses import dataclass, field

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

ORIENTATIONS = ("normal", "transposed", "no_header_cells", "unclear")

_SYSTEM_PROMPT = """You extract engine/emissions data from ONE wikitext table \
taken from a German Wikipedia article about a car model.

You will be given the section heading path above the table and the raw table \
wikitext. Return structured data for every engine variant the table describes.

STEP 1 — DETERMINE THE TABLE'S ORIENTATION. Do not assume; both shapes are \
common in this corpus and they must be read differently.

- "normal": the header cells form a row across the TOP (e.g. "! Modell", \
"! Motor", "! Hubraum", "! Leistung", "! CO2-Emission"), and EACH SUBSEQUENT \
ROW IS ONE ENGINE VARIANT. Read across a row to fill one variant.
- "transposed": the header cells run DOWN THE LEFT as attribute labels (e.g. \
"! Bauzeitraum", "! Motorkenndaten", "! Hubraum", "! max. Leistung", \
"! CO<sub>2</sub>-Emission, kombiniert"), and EACH COLUMN IS ONE ENGINE \
VARIANT. Read down a column to fill one variant. The variant names are usually \
in the first row ("2.0 TFSI", "40 TDI", …).
- "no_header_cells": the table uses no "!" header cells at all; work out from \
content which axis is the variant axis.
- "unclear": you genuinely cannot tell. Return an empty variants list rather \
than guessing an axis.

Report your verdict in `orientation`, then extract accordingly.

STEP 2 — EMIT ONE OBJECT PER ENGINE VARIANT, in `variants`.

A transposed table with 5 engine columns yields 5 objects. A normal table with \
12 engine rows yields 12 objects. Never merge variants and never split one \
variant across several objects — with one exception, below.

FIELDS (all nullable; null means "this table does not state it"):
- engine_code: the variant's identifying label as printed — "2.0 TFSI", \
"40 TDI quattro", "1.6 CRDi", "M270 DE16 AL", "116d". Prefer the commercial/ \
engine designation over a bare displacement. Null if the table names no variant.
- production_start / production_end: from Bauzeitraum / Produktionszeitraum \
style rows. Format "YYYY-MM" when a month is given ("06/2016" -> "2016-06"), \
otherwise the bare year "YYYY". NEVER invent a month that is not printed. \
An open-ended range ("seit 2019", "2019-") means production_end is null.
- displacement_cc: cubic centimetres as an integer. "1968 cm³" -> 1968, \
"1,4 l" -> 1400.
- power_kw: kilowatts as a number. "110 kW (150 PS)" -> 110. If the cell lists \
several power figures for one variant (e.g. with/without overboost), take the \
principal/nominal one.
- fuel_type: ONLY "diesel" or "petrol", else null. This is often stated \
nowhere in the table and only inferable from the heading path — a table under \
"Ottomotoren" is petrol, under "Dieselmotoren" is diesel. Use "petrol" for \
Otto/Benzin. Use null for electric, hybrid-only labels, CNG/Erdgas, LPG, \
hydrogen, or anything you cannot place as clearly diesel or petrol.
- co2_min / co2_max: combined CO2 emission in g/km.
  * A range "117-129 g/km" -> co2_min 117, co2_max 129.
  * A single value "129 g/km" -> co2_min 129 AND co2_max 129.
  * IF THIS TABLE STATES NO CO2 FIGURE FOR THIS VARIANT, RETURN NULL FOR BOTH. \
Returning null is CORRECT and EXPECTED — it is not a failure. DO NOT ESTIMATE, \
DO NOT INFER FROM YOUR OWN KNOWLEDGE OF THE CAR, DO NOT COMPUTE A FIGURE FROM \
FUEL CONSUMPTION. Only ever copy a number that is literally printed in this \
table.

DUAL-FUEL EXCEPTION: when one variant is given SEPARATE figures per fuel, emit \
ONE OBJECT PER FUEL, each with that fuel's own co2 values — never one object \
with both crammed together. This covers two spellings:
  * separate labelled figures (a g-tron listing CO2 for Super and again for \
Erdgas);
  * two figures separated by a slash in one cell on a bi-fuel variant \
("MPI LPG 85" with "165/144 g/km" = 165 on petrol, 144 on LPG). A slash pair \
on a bi-fuel variant is TWO VARIANTS, NOT a min/max range. Never put the two \
sides of such a pair into co2_min and co2_max of a single object.
Contrast: a genuine range is written with a dash ("117-129 g/km") and DOES \
belong in co2_min/co2_max of one object.

GENERAL RULES:
- Extract only what is in THIS table. Do not add variants you know exist but \
that this table omits.
- Ignore footnote markers, reference tags and thousands separators. German \
decimal commas ("1,4") are decimal points.
- If the table is not an engine/emissions table at all (sales figures, crash \
test results, model timeline), return an empty variants list."""

_VARIANT_SCHEMA = {
    "type": "object",
    "properties": {
        "engine_code": {"type": ["string", "null"]},
        "production_start": {"type": ["string", "null"]},
        "production_end": {"type": ["string", "null"]},
        "displacement_cc": {"type": ["number", "null"]},
        "power_kw": {"type": ["number", "null"]},
        "fuel_type": {"enum": ["diesel", "petrol", None]},
        "co2_min": {"type": ["number", "null"]},
        "co2_max": {"type": ["number", "null"]},
    },
    "required": [
        "engine_code", "production_start", "production_end", "displacement_cc",
        "power_kw", "fuel_type", "co2_min", "co2_max",
    ],
    "additionalProperties": False,
}

_EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "orientation": {"enum": list(ORIENTATIONS)},
        "variants": {"type": "array", "items": _VARIANT_SCHEMA},
    },
    "required": ["orientation", "variants"],
    "additionalProperties": False,
}


@dataclass
class TableExtraction:
    """One table's result. `variants` are raw dicts — Phase 3 validates them."""

    orientation: str
    variants: list[dict] = field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0

    @property
    def has_co2(self) -> bool:
        """Whether ANY variant carries a CO2 figure.

        This is the determinism-cache gate (plan §Open items 4 / the Phase 2
        amendment): a result with CO2 is cached as final, an all-null one is
        left uncached so a flaky false-null gets another chance on a later run
        instead of freezing that table out of coverage permanently."""
        return any(v.get("co2_min") is not None or v.get("co2_max") is not None for v in self.variants)


async def extract_table(
    table_wikitext: str,
    heading_context: str,
    article_title: str,
    brand: str,
    timeout_seconds: float = 120.0,
) -> TableExtraction:
    """Structure one wikitext table into engine variants.

    Raises:
        RuntimeError: no API key, or an unusable response shape.
    """
    settings = get_settings()
    if not settings.openrouter_api_key:
        raise RuntimeError(
            "OPENROUTER_API_KEY is not set — required for Phase 2 table extraction."
        )

    user_prompt = (
        f"Manufacturer: {brand}\n"
        f"German Wikipedia article: {article_title}\n"
        f"Section heading path above this table: {heading_context}\n\n"
        f"Table wikitext:\n{table_wikitext}"
    )
    payload = {
        "model": settings.openrouter_model,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "engine_table_extraction",
                "strict": True,
                "schema": _EXTRACTION_SCHEMA,
            },
        },
        "plugins": [{"id": "response-healing"}],
        "temperature": 0,
        # Ask OpenRouter to return the generation's actual credit cost alongside
        # token counts, so the run reports real spend rather than an estimate
        # against a published rate that has moved repeatedly.
        "usage": {"include": True},
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
            # Same stall behaviour llm_mapper.py and llm_sections.py work
            # around: one retry on a fresh connection clears it.
            response = await client.post(**request_kwargs)
    response.raise_for_status()
    data = response.json()

    try:
        parsed = json.loads(data["choices"][0]["message"]["content"])
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Unexpected OpenRouter response shape: {data}") from exc

    variants = parsed.get("variants") or []
    if not isinstance(variants, list):
        raise RuntimeError(f"Expected a list of variants, got {variants!r}")

    orientation = parsed.get("orientation")
    if orientation not in ORIENTATIONS:
        raise RuntimeError(f"LLM returned unknown orientation {orientation!r}")

    usage = data.get("usage") or {}
    return TableExtraction(
        orientation=orientation,
        variants=[v for v in variants if isinstance(v, dict)],
        prompt_tokens=int(usage.get("prompt_tokens") or 0),
        completion_tokens=int(usage.get("completion_tokens") or 0),
        cost_usd=float(usage.get("cost") or 0.0),
    )
