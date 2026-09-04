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

**Per token, but not all-or-nothing.** The first version of that per-token
filter dropped a row as soon as *any* single query token matched nothing, and
that was fatal for the text this endpoint is actually given. Callers pass
listing-derived blobs, and a listing carries trim, body and transmission words
that a de.wikipedia engine table never contains — "GT", "Sport", "Automatic",
"Line", "DSG", "Navi", "Klima". One of them was enough to annihilate the whole
result set: `320d xDrive GT Sport-Automatic "Sport Line"` and
`Golf 1.6 TDI Comfortline DSG` both returned zero rows against the live corpus
while `320d` returned fourteen. `QUERY_NOISE_TOKENS` cannot fix that by growing
— it is a vocabulary of words we are *sure* about, and the tail of trim names
is unbounded.

So the rule is **best coverage** instead: rank by how many query tokens a row
matches, keep only the rows that achieve the maximum, and let a token that
matches nothing *anywhere* be ignored rather than fatal. That keeps the search
box behaving the way a search box should — every word that matches something
narrows the list — while a word the corpus has never heard of costs nothing.
The words that were ignored are reported back so the UI can say so; see
`EngineSearchResult.ignored_terms`, which exists because silence there is
dangerous. A 3-series Gran Turismo listing is a real example: the corpus has no
F34 article at all, so "GT" matches nothing and the rows offered are a
different body of the same era. The user has to be able to see that.
"""

import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from rapidfuzz import fuzz

from app.db.models import WikipediaEngineData
from app.wikipedia.co2_lookup import normalize_text
from app.wikipedia.validation import period_sort_key

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

#: Shortest query token allowed to earn credit by *prefixing* a row token; at
#: or below this length a token has to match exactly. Set by two regressions on
#: the live corpus, both of which are the same defect at different scales: "c"
#: from "C 220 d" prefixed "citan" and put a Citan van above the W205 C 220 d,
#: and "gt" from a 3-series Gran Turismo listing prefixed "gts" and floated an
#: M4 GTS above the 320d rows. Short tokens prefix too much to be evidence.
#: Two-character model designations ("A4", "Q5", "S3") are unaffected — they
#: are matched exactly, never by prefix.
MIN_PREFIX_LEN = 3

#: Fraction of the tier's best weighted credit a row must reach to stay in it.
#: Set by the BMW "320d xDrive GT Sport-Automatic" query scoped to a 2016
#: registration: every surviving row there matches exactly one query token, so
#: the count tier alone admitted 65 rows, most of them carried only by the
#: common "xdrive". At 0.6 it is 8, all of them F30 320d variants. Purely a
#: pruning rule within one tier — it can never promote a row over one that
#: matched more of the query.
TIER_RETAIN_FRACTION = 0.6

#: Grace either side of a row's stated production period when the caller
#: supplies a first-registration date. Deliberately wider than
#: `co2_lookup`'s 3/18 — CLAUDE.md pins these two modules as sharing no tuning
#: constants, and the postures genuinely differ: the matcher is deciding what
#: to *assert*, this is deciding what to *show*. A car registered a year after
#: its generation ended (dealer stock) is still that car, and a browse list
#: that hides it has failed the person reading it.
PERIOD_GRACE_BEFORE_START_MONTHS = 6
PERIOD_GRACE_AFTER_END_MONTHS = 24


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


def _match_credit(
    query_token: str,
    row_tokens: list[str],
    *,
    allow_typos: bool = False,
) -> float:
    """How strongly one query token is carried by a row, 0.0 for not at all.

    Matching is per *token*, not substring-over-the-whole-string. "1.6 TDI"
    normalizes to the tokens ("1", "6", "tdi"), and a bare "1" as a substring
    of the joined text would hit "Audi A1 8X"; as a token it correctly does
    not, because no token there starts with "1".

    Prefix credit is scaled by how much of the row token the query actually
    accounted for. "320" -> "320d" is nearly the whole word and scores close to
    a prefix match's full weight; a short fragment landing at the head of a long
    unrelated word is mostly luck and scores accordingly. Prefixing a word we
    already know to be listing noise earns nothing at all — "sport" reaching
    "sportback" was ranking Q3 Sportback rows above the Audi A4 rows an A4
    query asked for.
    """
    best = 0.0
    for row_token in row_tokens:
        if row_token == query_token:
            return _EXACT_TOKEN_WEIGHT
        if len(query_token) < MIN_PREFIX_LEN:
            continue
        if row_token.startswith(query_token) and row_token not in QUERY_NOISE_TOKENS:
            best = max(
                best,
                _PREFIX_TOKEN_WEIGHT * len(query_token) / len(row_token),
            )
        elif allow_typos:
            similarity = fuzz.ratio(query_token, row_token)
            if similarity >= TYPO_TOKEN_FLOOR:
                best = max(best, _FUZZY_TOKEN_WEIGHT * similarity / 100.0)
    return best


def _period_months(value: str | None) -> int | None:
    """A "YYYY"/"YYYY-MM" production bound as a comparable month count."""
    parsed = period_sort_key(value)
    if parsed is None:
        return None
    year, month = parsed
    return year * 12 + (month - 1)


def _within_period(row: EngineRow, registered: int | None) -> bool:
    """Whether `row` could be the generation registered in that month.

    Permissive by design, in two ways the matcher is not. A row that states no
    period at all is kept — `co2_lookup` withholds those because it is deciding
    what to assert, whereas hiding a row from a list the user is reading just
    costs them the answer. And the grace windows are wide (see the constants).
    """
    if registered is None:
        return True
    start = _period_months(row.production_start)
    end = _period_months(row.production_end)
    if start is None and end is None:
        return True
    if start is not None and registered < start - PERIOD_GRACE_BEFORE_START_MONTHS:
        return False
    return not (
        end is not None and registered > end + PERIOD_GRACE_AFTER_END_MONTHS
    )



def _token_weights(
    query_tokens: list[str],
    matched_counts: dict[str, int],
    pool_size: int,
) -> dict[str, float]:
    """Inverse document frequency per query token, over the current pool.

    Needed because a matched-token *count* treats every word as equally
    informative, and they are not: for a BMW pool, "320d" names the car while
    "xdrive" is shared by a quarter of it. Ranking a one-token tier by count
    alone put a 2er Gran Tourer carried by "xdrive" above the F30 320d rows.

    **Pool-relative on purpose, and bounded in what it can do.** IDF here
    answers "which of the words the user typed discriminates among the rows we
    are about to show them" — a token that is rare corpus-wide but present on
    every row of this brand's pool discriminates nothing here, so a globally
    precomputed IDF would get it backwards. What it can affect is deliberately
    small: the tier is chosen by matched-token count *before* any of this is
    applied, so a row matching two query tokens can never be displaced by one
    matching a single rare token, whatever the pool contains. IDF only orders
    within one tier, and (through TIER_RETAIN_FRACTION) prunes within it. The
    one thing that does move with the pool is tier *membership* — narrowing the
    pool by registration date can drop a row that survived the wider one, which
    is the intent of scoping, not a surprise. Ordering across tiers is invariant.
    """
    return {
        token: math.log(1 + pool_size / (1 + matched_counts.get(token, 0)))
        for token in query_tokens
    }


def _rank_by_coverage[T](
    items: list[tuple[list[str], T]],
    query_tokens: list[str],
    tie_break: Callable[[T], tuple],
    limit: int,
) -> tuple[list[T], tuple[str, ...]]:
    """Best-coverage ranking over anything with searchable tokens.

    Generic over the payload because two different things are ranked this way —
    engine rows and the model articles that group them — and they must agree.
    A model list ordered by one rule and the engine list inside it by another
    would put a user's car top of one screen and buried on the next.

    Returns the kept payloads and the query tokens no kept payload matched.
    """

    def pass_over(allow_typos: bool) -> list[tuple[int, list[float], T]]:
        out = []
        for tokens, payload in items:
            credits = [
                _match_credit(token, tokens, allow_typos=allow_typos)
                for token in query_tokens
            ]
            matched = sum(1 for credit in credits if credit > 0)
            if matched:
                out.append((matched, credits, payload))
        return out

    scored = pass_over(allow_typos=False)
    # Typo pass runs only when the strict one found nothing at all. While the
    # strict filter is producing rows, those are strictly better answers than
    # anything fuzzy matching would add — mixing the two would push "Golf" rows
    # into a list the user had narrowed to "Golf GTI".
    if not scored:
        scored = pass_over(allow_typos=True)
    if not scored:
        return [], tuple(query_tokens)

    frequency: dict[str, int] = dict.fromkeys(query_tokens, 0)
    for _matched, credits, _payload in scored:
        for token, credit in zip(query_tokens, credits, strict=True):
            if credit > 0:
                frequency[token] += 1
    # Items matching nothing are absent from `scored` but contribute 0 to every
    # token's frequency anyway, so this is the frequency over the whole pool.
    weights = _token_weights(query_tokens, frequency, len(items))

    best_count = max(matched for matched, _credits, _payload in scored)
    tier = [
        (
            sum(
                weights[token] * credit
                for token, credit in zip(query_tokens, credits, strict=True)
            ),
            credits,
            payload,
        )
        for matched, credits, payload in scored
        if matched == best_count
    ]
    best_value = max(value for value, _credits, _payload in tier)
    tier = [entry for entry in tier if entry[0] >= best_value * TIER_RETAIN_FRACTION]
    tier.sort(key=lambda entry: (-entry[0], tie_break(entry[2])))
    kept = tier[:limit]

    honoured = {
        token
        for _value, credits, _payload in kept
        for token, credit in zip(query_tokens, credits, strict=True)
        if credit > 0
    }
    return (
        [payload for _value, _credits, payload in kept],
        tuple(token for token in query_tokens if token not in honoured),
    )


def _display_sort_key(row: EngineRow) -> tuple:
    """Article, then production start, then power — the order someone scanning
    for their own car reads in. Nulls sort last rather than first, so rows that
    state nothing don't head the list."""
    return (
        row.model_article_title,
        row.production_start or "9999",
        row.power_kw if row.power_kw is not None else 1e9,
    )


def _scoped_pool(rows: list[EngineRow], registered: date | None) -> list[EngineRow]:
    """Rows whose generation could have been registered then, or all of them.

    Scoping happens *before* ranking, never after. A 2016 "320d xDrive" query
    ranked first and filtered second returns nothing, because the only xDrive
    rows in the corpus are a 2019+ G20. Scoped first, the same query settles for
    matching "320d" alone and finds the correct-era F30. If the date leaves
    nothing at all the scope is abandoned rather than obeyed — a mistyped year
    should cost relevance, never the whole list.
    """
    if registered is None:
        return list(rows)
    months = registered.year * 12 + (registered.month - 1)
    return [row for row in rows if _within_period(row, months)] or list(rows)


@dataclass(frozen=True)
class EngineSearchResult:
    """Rows to show, plus the words we could not honour.

    `ignored_terms` is not decoration. Best-coverage ranking always returns
    *something* when any word matches, which is what makes the box usable on
    listing text — but it also means a row can be offered for a car the corpus
    does not actually contain. The 3-series Gran Turismo is the standing
    example: no F34 article exists, so "GT" matches nothing and what comes back
    is a different body of the same era. Reporting the dropped word is what lets
    the person reading the list notice that.
    """

    rows: list[EngineRow]
    ignored_terms: tuple[str, ...]


def search_engine_rows(
    rows: list[EngineRow],
    query: str | None,
    *,
    registered: date | None = None,
    article: str | None = None,
    limit: int = MAX_ROWS,
) -> EngineSearchResult:
    """Rows matching `query`, best first, plus the query words nothing matched.

    Pure and DB-free. An empty result is a legitimate answer — the corpus
    genuinely has nothing for plenty of model/engine combinations, and saying so
    is better than relaxing the filter until something appears.

    `article` restricts to one model article and is an *exact* filter, not a
    ranking hint — it carries a title the user picked off the model list, and a
    fuzzy reading of an explicit choice would be a worse answer than none. It is
    also what makes the search's guesswork optional: once the model is chosen,
    the free-text box only has to separate engines within one generation, which
    is a job the corpus can actually do reliably.
    """
    if not rows:
        return EngineSearchResult([], ())

    pool = _scoped_pool(rows, registered)
    if article is not None:
        # The user's own choice outranks the date scope: if they say F30 and the
        # date disagrees, they are the ones holding the logbook.
        chosen = [row for row in rows if row.model_article_title == article]
        pool = [row for row in pool if row.model_article_title == article] or chosen
        if not pool:
            return EngineSearchResult([], ())

    normalized = normalize_text(query) if query else ""
    if not normalized:
        return EngineSearchResult(sorted(pool, key=_display_sort_key)[:limit], ())

    kept, ignored = _rank_by_coverage(
        [(_haystack(row).split(), row) for row in pool],
        normalized.split(),
        _display_sort_key,
        limit,
    )
    return EngineSearchResult(kept, ignored)


def rank_engine_rows(
    rows: list[EngineRow],
    query: str | None,
    *,
    registered: date | None = None,
    article: str | None = None,
    limit: int = MAX_ROWS,
) -> list[EngineRow]:
    """`search_engine_rows` without the ignored-terms half, for callers that
    only want the list."""
    return search_engine_rows(
        rows, query, registered=registered, article=article, limit=limit
    ).rows


# ---------------------------------------------------------------------------
# Model articles — the first step of the picker.
#
# The engine search alone asks the user to trust that free-text matching found
# their car, and on a listing blob it cannot always be trusted: a 3-series Gran
# Turismo has no article at all, so the closest honest answer is a different
# body of the same era, and only the person holding the logbook can see that.
# Choosing the model first removes the guess from the part that matters. What is
# left for the text box — telling engines apart inside one generation — is the
# job the corpus does reliably.
#
# The catch is that de.wikipedia names these articles by chassis code ("BMW
# G20", "Mercedes-Benz Baureihe 205"), which almost nobody recognises. So a
# model row carries what the person *does* know: the years, and the engine
# badges inside it.
# ---------------------------------------------------------------------------

#: Engine designations listed per model as recognition aids. Enough to tell an
#: F30 from a G20 at a glance, few enough not to wrap on a phone.
MODEL_SAMPLE_CODES = 4


@dataclass(frozen=True)
class ModelGroup:
    """One de.wikipedia article, summarised for the picker's first screen."""

    model_article_title: str
    variant_count: int
    production_start: str | None
    production_end: str | None
    sample_engine_codes: tuple[str, ...]
    co2_min: float | None
    co2_max: float | None
    source_url: str


@dataclass(frozen=True)
class ModelSearchResult:
    models: list[ModelGroup]
    ignored_terms: tuple[str, ...]


def _model_sort_key(group: ModelGroup) -> tuple:
    """Newest generation first. Someone importing a car is far likelier to be
    looking at a recent one, and the alternative — alphabetical over chassis
    codes — is an ordering with no meaning to the reader at all."""
    return (
        group.production_start is None,
        _negated(group.production_start),
        group.model_article_title,
    )


def _negated(period: str | None) -> str:
    """Sortable descending form of a "YYYY-MM" bound."""
    parsed = period_sort_key(period)
    if parsed is None:
        return ""
    year, month = parsed
    return f"{9999 - year:04d}{12 - month:02d}"


def group_models(
    rows: list[EngineRow],
    query: str | None = None,
    *,
    registered: date | None = None,
    limit: int = MAX_ROWS,
) -> ModelSearchResult:
    """The brand's model articles, best match first.

    Pure and DB-free. Ranked with exactly the same coverage machinery as the
    engine list, over a haystack of the article title plus every engine badge
    inside it — so a query of "320d" finds the F30 even though the article is
    named after a chassis code the listing never mentions.
    """
    pool = _scoped_pool(rows, registered)
    if not pool:
        return ModelSearchResult([], ())

    grouped: dict[str, list[EngineRow]] = {}
    for row in pool:
        grouped.setdefault(row.model_article_title, []).append(row)

    groups = [_summarise(title, members) for title, members in grouped.items()]

    normalized = normalize_text(query) if query else ""
    if not normalized:
        return ModelSearchResult(sorted(groups, key=_model_sort_key)[:limit], ())

    haystacks = [
        (
            normalize_text(
                f"{title} " + " ".join(row.engine_code or "" for row in members)
            ).split(),
            group,
        )
        for group, (title, members) in zip(groups, grouped.items(), strict=True)
    ]
    matched, ignored = _rank_by_coverage(
        haystacks, normalized.split(), _model_sort_key, limit
    )
    # **Ranked, never filtered.** The engine list may hide non-matches — by then
    # the user has already told us the generation. This list is where they say
    # so, and the case it exists for is precisely the one where matching got it
    # wrong: a 3-series Gran Turismo has no article, so every "match" here is
    # the wrong body. Filtering would leave that user staring at one confidently
    # wrong option with no way to reach the right neighbourhood.
    seen = {group.model_article_title for group in matched}
    rest = sorted(
        (group for group in groups if group.model_article_title not in seen),
        key=_model_sort_key,
    )
    return ModelSearchResult((matched + rest)[:limit], ignored)


def _generation_end(members: list[EngineRow], ends: list[str]) -> str | None:
    """The generation's end date, or None while it is still being built."""
    if not ends:
        return None
    newest = max(members, key=lambda row: period_sort_key(row.production_start) or (0, 0))
    if newest.production_end is None:
        return None
    return max(ends, key=lambda value: period_sort_key(value) or (0, 0))


def _summarise(title: str, members: list[EngineRow]) -> ModelGroup:
    starts = [row.production_start for row in members if row.production_start]
    ends = [row.production_end for row in members if row.production_end]
    co2s = [
        value
        for row in members
        for value in (row.co2_min, row.co2_max)
        if value is not None
    ]
    # The shortest distinct badges, then alphabetical. Shortest because these are
    # recognition aids and the base designation is the recognisable part — "320i"
    # says 3-series far better than "320i EfficientDynamics Edition", which
    # crowds out three other badges for no extra information.
    distinct = {code for row in members if (code := (row.engine_code or "").strip())}
    codes = sorted(sorted(distinct, key=len)[:MODEL_SAMPLE_CODES])
    return ModelGroup(
        model_article_title=title,
        variant_count=len(members),
        production_start=min(starts, key=lambda v: period_sort_key(v) or (0, 0))
        if starts
        else None,
        # Open-ended only when the *newest-starting* variant is open-ended. Keying
        # off "any member lacks an end" instead marks a long-discontinued
        # generation as current the moment one of its 48 rows failed to state an
        # end — which is what the BMW F30 did.
        production_end=_generation_end(members, ends),
        sample_engine_codes=tuple(codes),
        co2_min=min(co2s) if co2s else None,
        co2_max=max(co2s) if co2s else None,
        source_url=members[0].source_url,
    )
