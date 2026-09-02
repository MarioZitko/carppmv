"""Free-text browsing over `wikipedia_engine_data` — the "show me every CO2
value for this car" lookup behind GET /wikipedia/engines.

A **different job** from `co2_lookup.py`, which is why it lives apart from it.
That module answers "which single engine is this vehicle?" and declines
whenever it is not sure. This one answers "what does Wikipedia have for this
car at all?" and is deliberately permissive: the human reading the list decides
which row is theirs, so showing a near-miss costs nothing and hiding it costs
them the answer.

The motivating case is the Audi A2. The corpus stores all five of its variants
correctly (1.4 petrol 142, 1.6 FSI 142, 1.2 3L TDI 81, 1.4 TDI 55kW 116, 1.4
TDI 66kW 116), but an autobid.de listing carries no fuel type, so "A2 1.4" at
55 kW ties the 55 kW petrol 1.4 (142 g/km) with the 55 kW diesel 1.4 TDI (116
g/km) at exactly 80.0 each. The matcher does the honest thing and reports the
union, 116-142 — useless to someone who knows perfectly well which one they
bought. No amount of tuning fixes that; only the person can.

Consequently there is no accept threshold, no auto-pick and no score in the
response. `co2_lookup`'s tuning constants deliberately have no influence here;
the only thing shared is `normalize_text`, imported rather than reimplemented
so both paths agree that "320 d" and "320d" are the same thing.

**Matching is per token, never whole-string.** Both filters here were first
written with `fuzz.token_set_ratio` over the joined title+engine text, and both
were wrong the same way: that score is dominated by the words the user did
*not* type, so a short query against a long title scores near zero. "320"
against "bmw f30 320d efficientdynamics" scores ~24, which meant typing "320"
returned nothing while "320d" returned fourteen rows. Length bias is fatal for
an incremental search box, so query tokens are matched against row tokens
individually instead.
"""

from dataclasses import dataclass

from rapidfuzz import fuzz

from app.db.models import WikipediaEngineData
from app.wikipedia.co2_lookup import normalize_text

#: Per-token similarity a query word needs to count as a typo of a row word.
#: Applied only in the fallback pass, and only token-to-token ("karokq" vs
#: "karoq" is 91). High on purpose: below roughly this, "typo" stops meaning
#: typo and starts meaning different word.
TYPO_TOKEN_FLOOR = 80.0

#: Hard cap on rows returned, so a bare brand browse of Mercedes-Benz (1,086
#: rows) doesn't ship a megabyte of JSON to render a scroll list nobody reads
#: to the end of.
MAX_ROWS = 200

#: A query token that exactly equals a row token is worth more than one that
#: merely prefixes it ("320d" == "320d" beats "320" -> "320d"), which floats
#: exact matches to the top of an otherwise equally valid list. A token matched
#: only through the typo fallback is worth least of all.
_EXACT_TOKEN_WEIGHT = 1.0
_PREFIX_TOKEN_WEIGHT = 0.8
_FUZZY_TOKEN_WEIGHT = 0.6


#: Words that appear all over dealer listing titles and never in a de.wikipedia
#: engine table: body styles, door counts and trim names. Used to clean a
#: free-text QUERY — never applied to stored data.
#:
#: Shared by `calculate/router.py::_wikipedia_model_text` (which builds the
#: automatic lookup's query) and by GET /wikipedia/engines (whose callers pass
#: the same listing text). One vocabulary, two callers: two copies would drift,
#: and then the picker and the automatic hint would disagree about the same car.
#:
#: Only words that are unambiguously not engine designations belong here. When
#: in doubt, leave it in: an extra token costs a few points of score, whereas
#: stripping a real designation ("TDI", "quattro", "S3") would make the matcher
#: confidently answer about a different engine.
QUERY_NOISE_TOKENS = frozenset(
    {
        # Body styles (de/en/hr)
        "sportback", "limousine", "limuzina", "berlina", "avant", "variant",
        "kombi", "karavan", "estate", "touring", "sw", "break", "coupe",
        "cabrio", "cabriolet", "roadster", "hatchback", "sedan", "van",
        "minivan", "suv", "crossover", "fastback", "liftback", "grandtour",
        # Door/seat descriptors
        "vrata", "door", "doors", "turer", "tuerer",
        # Trim / equipment lines
        "attraction", "ambition", "ambiente", "comfortline", "highline",
        "trendline", "elegance", "executive", "business", "advanced",
        "exclusive", "premium", "lounge", "urban", "intens", "expression",
        "zen", "allure", "titanium", "zetec", "ghia", "active", "style",
        "edition", "selection", "advance", "essential", "ultimate",
    }
)


def clean_query(text: str | None, brand: str | None = None) -> str:
    """Strip brand words, body/trim words and repeats from listing-derived text.

    Cleaning only ever *removes* tokens, so it can lose a match but never
    invent one. Returns "" when there is nothing left to search with; callers
    decide what that means.

    The brand goes too: it is already the SQL filter on both paths and is
    stripped from the candidate side of the comparison, so repeating it in the
    query is pure dilution.
    """
    if not text or not text.strip():
        return ""
    brand_tokens = set(normalize_text(brand).split()) if brand else set()
    kept: list[str] = []
    seen: set[str] = set()
    for token in normalize_text(text).split():
        if token in brand_tokens or token in QUERY_NOISE_TOKENS or token in seen:
            continue
        seen.add(token)
        kept.append(token)
    return " ".join(kept)


@dataclass(frozen=True)
class EngineRow:
    """One row, decoupled from the ORM so ranking stays pure and testable."""

    model_article_title: str
    engine_code: str | None
    power_kw: float | None
    displacement_cc: float | None
    fuel_type: str | None
    production_start: str | None
    production_end: str | None
    co2_min: float | None
    co2_max: float | None
    source_url: str

    @classmethod
    def from_row(cls, row: WikipediaEngineData) -> "EngineRow":
        return cls(
            model_article_title=row.model_article_title,
            engine_code=row.engine_code,
            power_kw=row.power_kw,
            displacement_cc=row.displacement_cc,
            fuel_type=row.fuel_type,
            production_start=row.production_start,
            production_end=row.production_end,
            co2_min=row.co2_min,
            co2_max=row.co2_max,
            source_url=row.source_url,
        )


def _haystack(row: EngineRow) -> str:
    return normalize_text(f"{row.model_article_title} {row.engine_code or ''}")


def _token_score(
    query_tokens: list[str],
    row_tokens: list[str],
    *,
    allow_typos: bool = False,
) -> float | None:
    """Percentage match, or None when some query token matches nothing.

    Matching is per *token*, not substring-over-the-whole-string. "1.6 TDI"
    normalizes to the tokens ("1", "6", "tdi"), and a bare "1" as a substring
    of the joined text would hit "Audi A1 8X"; as a token it correctly does
    not, because no token there starts with "1".

    Requiring *every* query token to match is what makes the box behave like a
    filter — each word the user adds narrows the list rather than reshuffling
    it.
    """
    total = 0.0
    for q in query_tokens:
        best = 0.0
        for h in row_tokens:
            if h == q:
                best = _EXACT_TOKEN_WEIGHT
                break
            if h.startswith(q):
                best = max(best, _PREFIX_TOKEN_WEIGHT)
            elif allow_typos:
                similarity = fuzz.ratio(q, h)
                if similarity >= TYPO_TOKEN_FLOOR:
                    best = max(best, _FUZZY_TOKEN_WEIGHT * similarity / 100.0)
        if best == 0.0:
            return None
        total += best
    return 100.0 * total / len(query_tokens)


def _display_sort_key(row: EngineRow) -> tuple:
    """Article, then production start, then power — the order someone scanning
    for their own car reads in. Nulls sort last rather than first, so rows that
    state nothing don't head the list."""
    return (
        row.model_article_title,
        row.production_start or "9999",
        row.power_kw if row.power_kw is not None else 1e9,
    )


def rank_engine_rows(
    rows: list[EngineRow], query: str | None, limit: int = MAX_ROWS
) -> list[EngineRow]:
    """Rows matching `query`, best first; everything (display-ordered) when the
    query is blank.

    Pure and DB-free. An empty result is a legitimate answer — the corpus
    genuinely has nothing for plenty of model/engine combinations, and saying
    so is better than relaxing the filter until something appears.
    """
    if not rows:
        return []

    normalized = normalize_text(query) if query else ""
    if not normalized:
        return sorted(rows, key=_display_sort_key)[:limit]

    query_tokens = normalized.split()
    tokens = {id(row): _haystack(row).split() for row in rows}

    def pass_over(allow_typos: bool) -> list[tuple[float, EngineRow]]:
        out = []
        for row in rows:
            score = _token_score(query_tokens, tokens[id(row)], allow_typos=allow_typos)
            if score is not None:
                out.append((score, row))
        return out

    scored = pass_over(allow_typos=False)
    # Typo pass runs only when the strict one found nothing at all. While the
    # strict filter is producing rows, those are strictly better answers than
    # anything fuzzy matching would add — mixing the two would push "Golf" rows
    # into a list the user had narrowed to "Golf GTI".
    if not scored:
        scored = pass_over(allow_typos=True)

    scored.sort(key=lambda pair: (-pair[0], _display_sort_key(pair[1])))
    return [row for _score, row in scored[:limit]]
