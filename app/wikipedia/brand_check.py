"""Cross-check a crawled row's brand against the article title it came from.

**The crawl brand is not authoritative on its own.** Phase 0 files an article
under whichever brand article linked to it, and brand articles routinely link
to other marques' rebadges, to sub-marques, and to shared platform articles.
Using that column as a hard filter unchanged is the silent-corruption case
CLAUDE.md warns about: it would offer 28 Opel Zafira variants to any Subaru
query, because Subaru's brand article links the Traviq rebadge.

What is actually in the corpus (599 distinct brand/article pairs, 1,133 tables):

| filed under | article title       | reality                                  |
|-------------|---------------------|------------------------------------------|
| Subaru      | Opel Zafira         | the Traviq rebadge — 28 variants         |
| Toyota      | Lexus ES / GS / IS  | Lexus is its own catalogue brand         |
| Nissan      | Dacia Logan         | Renault-alliance cross-link              |
| Nissan      | Renault Symbol      | same                                     |
| MG          | Roewe RX9           | SAIC sibling marque, not MG              |
| Peugeot     | Eurovan (PSA/Fiat)  | 4-marque van platform article            |

The check is mechanical and deterministic — no LLM, no fuzzy scoring. It reads
the *longest leading marque prefix* of the title through the existing canonical
brand vocabulary (`app/catalogue/brands.py`), which is what already knows that
"VW Golf VII" is Volkswagen, "Mercedes-AMG C 192" is Mercedes-Benz and
"Range Rover Velar" is Land Rover. Reusing it is the point: a second private
brand vocabulary here would drift out of sync with ingestion and matching, and
that drift is exactly what brands.py's own docstring exists to prevent.

Three verdicts, and note that only one of them discards anything:

- CONFIRMED (589/599 pairs) — title's marque is the crawl brand. Trusted.
- REFILED (6 pairs) — title names a *different known marque*. The row is
  **re-filed under the marque the title names**, not dropped: a "Lexus ES"
  row is wrong as Toyota and correct as Lexus, and Lexus is a catalogue brand
  in its own right. This turns a corruption risk into coverage.
- UNVERIFIED (2 pairs) — the title carries no recognisable marque prefix at
  all ("Eurovan (PSA/Fiat)", "Roewe RX9"), so the claim can be neither
  confirmed nor contradicted. Held out of every brand's candidate pool by
  default and surfaced under an explicit opt-in, never mixed in silently.

The asymmetry between REFILED and UNVERIFIED is deliberate. A recognised
different marque is a *fact* about the row and can be acted on. An
unrecognised prefix is an absence of evidence, and the honest response to
absence of evidence — per the plan's "confirm unless certain" posture — is to
withhold the row rather than assume the crawl was right.

Pure and DB-free; unit-tested in tests/test_wikipedia_brand_check.py.
"""

import re
from dataclasses import dataclass

from app.catalogue.brands import _fold, brand_from_slug_tokens
from app.db.models import WikipediaBrandCheck

# Title -> tokens. Folded first (so "Citroën C4" and "Škoda Octavia" reduce to
# ascii, which is what the slug vocabulary is keyed on), then split on anything
# that is not alphanumeric or "&" (Lynk & Co). Without the fold, 498 perfectly
# good Citroën/Škoda rows read as UNVERIFIED.
_TOKEN_SPLIT = re.compile(r"[^0-9a-z&]+")


@dataclass(frozen=True)
class BrandCheck:
    """Outcome of the cross-check.

    `effective_brand` is what Phase 5 filters on; `crawl_brand` is kept beside
    it so a re-filing is auditable instead of silent.
    """

    effective_brand: str
    crawl_brand: str
    title_brand: str | None
    verdict: WikipediaBrandCheck

    @property
    def usable(self) -> bool:
        """Whether this row may enter a brand's candidate pool by default."""
        return self.verdict is not WikipediaBrandCheck.UNVERIFIED


def title_brand(article_title: str) -> str | None:
    """Canonical marque named by the article title's leading prefix, or None.

    Longest-prefix, so "Land Rover Defender" resolves to Land Rover rather than
    stopping at a one-token guess, and "Mercedes-AMG One" resolves through the
    alias table rather than being read as an unknown marque.
    """
    tokens = [t for t in _TOKEN_SPLIT.split(_fold(article_title)) if t]
    if not tokens:
        return None
    brand, _consumed = brand_from_slug_tokens(tokens)
    return brand


def check(crawl_brand: str, article_title: str) -> BrandCheck:
    """Cross-check one row's crawl brand against its article title."""
    named = title_brand(article_title)
    if named is None:
        return BrandCheck(
            effective_brand=crawl_brand,
            crawl_brand=crawl_brand,
            title_brand=None,
            verdict=WikipediaBrandCheck.UNVERIFIED,
        )
    if named == crawl_brand:
        return BrandCheck(
            effective_brand=crawl_brand,
            crawl_brand=crawl_brand,
            title_brand=named,
            verdict=WikipediaBrandCheck.CONFIRMED,
        )
    # The title names a different marque and the title is the stronger signal:
    # it is a property of the article the numbers were actually read out of,
    # whereas the crawl brand only records which brand article linked here.
    return BrandCheck(
        effective_brand=named,
        crawl_brand=crawl_brand,
        title_brand=named,
        verdict=WikipediaBrandCheck.REFILED,
    )
