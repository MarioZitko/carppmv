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
