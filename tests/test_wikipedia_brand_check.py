"""Phase 4's crawl-brand vs. article-title cross-check.

Every case here is a real (brand, article_title) pair from the 599 distinct
pairs the first full crawl produced — the point of this check is the handful of
rows that are filed under the wrong marque, so the tests are those rows rather
than invented ones.
"""

import pytest

from app.db.models import WikipediaBrandCheck
from app.wikipedia.brand_check import check, title_brand


@pytest.mark.parametrize(
    "brand,title",
    [
        ("Opel", "Opel Astra K"),
        ("Audi", "Audi A3 8V"),
        ("BMW", "BMW G20"),
        # Alias spellings de.wikipedia uses that the crawl brand does not.
        ("Volkswagen", "VW Golf VII"),
        ("Mercedes-Benz", "Mercedes-AMG One"),
        ("Mercedes-Benz", "Mercedes-Benz Baureihe 205"),
        ("Land Rover", "Range Rover Velar"),
        # Diacritics: these fold to ascii before the vocabulary lookup. Without
        # the fold both brands read as UNVERIFIED and lose ~500 good rows.
        ("Citroën", "Citroën C4"),
        ("Škoda", "Škoda Octavia III"),
    ],
)
def test_confirmed(brand: str, title: str) -> None:
    result = check(brand, title)
    assert result.verdict is WikipediaBrandCheck.CONFIRMED
    assert result.effective_brand == brand
    assert result.usable


@pytest.mark.parametrize(
    "crawl_brand,title,expected",
    [
        # The Traviq rebadge: 28 variants of Opel Zafira filed under Subaru.
        # Offering these for any Subaru query is the corruption this prevents.
        ("Subaru", "Opel Zafira", "Opel"),
        # Lexus is its own catalogue brand, reached via Toyota's article.
        ("Toyota", "Lexus ES", "Lexus"),
        ("Toyota", "Lexus GS", "Lexus"),
        # Renault-Nissan alliance cross-links.
        ("Nissan", "Dacia Logan", "Dacia"),
        ("Nissan", "Renault Symbol", "Renault"),
    ],
)
def test_refiled_to_the_marque_the_title_names(
    crawl_brand: str, title: str, expected: str
) -> None:
    result = check(crawl_brand, title)
    assert result.verdict is WikipediaBrandCheck.REFILED
    assert result.effective_brand == expected
    assert result.crawl_brand == crawl_brand
    # Re-filed rows stay usable — under the OTHER brand. Dropping them would
    # discard real coverage; the fix is filing them correctly, not deleting.
    assert result.usable


@pytest.mark.parametrize(
    "crawl_brand,title",
    [
        # A four-marque van platform article (Peugeot 806 / Citroën Evasion /
        # Fiat Ulysse / Lancia Zeta). Which marque any given row belongs to is
        # not recoverable, so none of them may claim it.
        ("Peugeot", "Eurovan (PSA/Fiat)"),
        # Roewe is a SAIC sibling of MG, not MG.
        ("MG", "Roewe RX9"),
    ],
)
def test_unverified_is_held_back(crawl_brand: str, title: str) -> None:
    result = check(crawl_brand, title)
    assert result.verdict is WikipediaBrandCheck.UNVERIFIED
    assert result.title_brand is None
    # The load-bearing assertion: these never enter a brand's candidate pool.
    assert not result.usable


def test_longest_prefix_wins() -> None:
    """"Land Rover Defender" must not stop at a one-token guess."""
    assert title_brand("Land Rover Defender") == "Land Rover"
    assert title_brand("Alfa Romeo 159") == "Alfa Romeo"


def test_unrecognised_title_returns_none() -> None:
    assert title_brand("Eurovan (PSA/Fiat)") is None
    assert title_brand("") is None
