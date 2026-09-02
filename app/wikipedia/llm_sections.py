"""Phase 1 — LLM section classification (fallback only).

Runs ONLY for brands that trip Phase 0's explicit escalation trigger (zero
fuzzy-matched sections, or a matched section with fewer than
sections.MIN_QUALIFYING_LINKS qualifying links). It is the exception path, not
the primary one.

The model's whole job is: given this article's literal level-2 headings, which
of them (if any) list car models? It never sees article prose, never proposes a
heading of its own, and never touches CO2 values — same narrow, bounded use as
app/catalogue/llm_mapper.py's column mapping.

Hallucination guard, mirroring llm_mapper.py: the JSON schema constrains the
answer to an ENUM of the literal heading strings passed in, and a post-hoc
check rejects anything that isn't one of them anyway (strict schema mode
constrains JSON *shape*, not that a string value is real).
"""

import json
import logging
from dataclasses import dataclass

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

_SYSTEM_PROMPT = """You are given the list of level-2 section headings from a \
German Wikipedia article about a car manufacturer.

Your only task: identify which heading(s), if any, introduce the section that \
LISTS THAT MANUFACTURER'S VEHICLE MODELS (current and/or historical).

German automotive articles very often head that section with something OTHER \
than the word "Modell". All of the following ARE model enumerations when they \
appear in a car-manufacturer article, and you should select them:
- "Verkaufsbezeichnungen", "Typenbezeichnungen" — despite sounding like naming \
  conventions, in these articles they are the enumerated list of models sold.
- "Produktpalette", "Produktlinien", "Produkte" — the model range.
- "Fahrzeuge", "Serienfahrzeuge", "Personenwagen", "Pkw", "Automobile" — the \
  vehicles themselves.
- "Fahrzeugmarke <name>" — in a short brand article this section carries the \
  model list.
- "Auflistung" — in a "Liste von …" article this IS the list.
- Era-split headings such as "Modellgeschichte bis 1941" / "… ab 1951", or \
  class-split ones like "X-Modelle" / "Z-Modelle": select ALL of them.

Also select "Modelle", "Modellübersicht", "Modellpalette", "Aktuelle Modelle" \
and similar obvious wordings. Judge each article's actual headings.

RULES:
- You may only return heading strings that appear EXACTLY as given in the \
input list. Never invent, translate, reword, or reformat a heading.
- Returning an empty list is CORRECT and EXPECTED when no heading lists \
vehicle models — but return it only when NO section could plausibly enumerate \
this manufacturer's vehicles. Do not return empty merely because no heading \
contains the word "Modell"; check the wordings listed above first.
- Do not select company-history, motorsport, financial, controversy, \
literature, or weblink sections, even if models are mentioned in passing. \
Select the section that ENUMERATES models.
- If several headings genuinely each list models (e.g. separate car and van \
sections), return all of them.
- Put your justification in `reasoning`, briefly."""


@dataclass(frozen=True)
class SectionClassification:
    headings: list[str]
    reasoning: str

    @property
    def is_none(self) -> bool:
        return not self.headings


def _build_schema(headings: list[str]) -> dict:
    """Enum-constrained to this article's real headings — the model cannot
    emit a heading that isn't in the list."""
    unique = list(dict.fromkeys(h for h in headings if h.strip()))
    return {
        "type": "object",
        "properties": {
            "headings": {"type": "array", "items": {"enum": unique}},
            "reasoning": {"type": "string"},
        },
        "required": ["headings", "reasoning"],
        "additionalProperties": False,
    }


async def classify_model_sections(
    brand: str,
    article_title: str,
    headings: list[str],
    timeout_seconds: float = 60.0,
) -> SectionClassification:
    """Ask which headings list car models. Returns an empty headings list for
    "none" — the caller then flags the brand for manual review rather than
    retrying or guessing (plan §Phase 1).

    Raises:
        RuntimeError: no API key, unusable response shape, or a heading that
            doesn't literally appear in `headings`.
    """
    settings = get_settings()
    if not settings.openrouter_api_key:
        raise RuntimeError(
            "OPENROUTER_API_KEY is not set — required for Phase 1 section classification."
        )

    user_prompt = (
        f"Manufacturer: {brand}\n"
        f"German Wikipedia article: {article_title}\n\n"
        f"Level-2 headings, in article order:\n"
        f"{json.dumps(headings, ensure_ascii=False, indent=1)}"
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
                "name": "model_section_classification",
                "strict": True,
                "schema": _build_schema(headings),
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
            # Same stall behaviour llm_mapper.py works around: one retry on a
            # fresh connection clears it.
            response = await client.post(**request_kwargs)
    response.raise_for_status()
    data = response.json()

    try:
        parsed = json.loads(data["choices"][0]["message"]["content"])
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Unexpected OpenRouter response shape: {data}") from exc

    returned = parsed.get("headings") or []
    if not isinstance(returned, list):
        raise RuntimeError(f"Expected a list of headings, got {returned!r}")

    known = set(headings)
    for heading in returned:
        if heading not in known:
            raise RuntimeError(
                f"LLM returned heading {heading!r}, which is not one of this "
                f"article's actual headings. Rejecting rather than crawling a "
                f"section that doesn't exist."
            )

    return SectionClassification(
        headings=[str(h) for h in returned],
        reasoning=str(parsed.get("reasoning", "")),
    )
