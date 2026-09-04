"""Response contracts for the Wikipedia engine-browser API (/wikipedia/*)."""

from pydantic import BaseModel


class WikipediaEngineRow(BaseModel):
    """One `wikipedia_engine_data` row as the browser renders it.

    Carries no score. The browse endpoint is explicitly not a confidence UI —
    the user is picking their own engine off a list, and a relevance number
    next to each row would invite reading it as "how sure we are that this is
    your car", which is exactly the impression this tier must not give.
    """

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


class WikipediaEngineSearchResponse(BaseModel):
    #: The canonical brand actually queried, which may differ from what the
    #: caller sent ("skoda" -> "Škoda"); the UI echoes it so a surprising empty
    #: result is explainable rather than mysterious.
    brand: str
    #: True when the brand isn't in the corpus at all — a different situation
    #: from "brand exists, this query matched nothing", and worth telling apart.
    brand_known: bool
    rows: list[WikipediaEngineRow]
    #: Query words no returned row matched. The search deliberately ignores a
    #: word the corpus has never heard of rather than returning nothing, so
    #: this is how the caller learns which part of what they typed went
    #: unanswered — and it is the only thing standing between a user and
    #: quietly accepting a row for a body variant we do not actually hold
    #: (a 3-series "GT" being the standing example). Empty on a clean match.
    ignored_terms: list[str] = []


class WikipediaModelRow(BaseModel):
    """One de.wikipedia article, as the picker's first screen lists it.

    Carries the recognition aids rather than just the title, because these
    articles are named by chassis code — "BMW G20", "Mercedes-Benz Baureihe
    205" — and almost nobody reads a logbook and thinks "G20". The years and
    the engine badges inside the generation are what a person actually matches
    their own car against.
    """

    model_article_title: str
    #: How many engine variants sit inside, so a one-variant stub is visibly
    #: different from a full generation.
    variant_count: int
    production_start: str | None
    #: None also means "still in production", not only "unknown" — a generation
    #: with a current variant has no end, and showing its newest stated end
    #: would read as discontinued.
    production_end: str | None
    sample_engine_codes: list[str]
    co2_min: float | None
    co2_max: float | None
    source_url: str


class WikipediaModelListResponse(BaseModel):
    brand: str
    brand_known: bool
    models: list[WikipediaModelRow]
    ignored_terms: list[str] = []
