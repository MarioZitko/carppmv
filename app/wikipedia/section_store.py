"""Persistent store of Phase 1 section-classification verdicts.

Mirrors app/catalogue/mapping_store.py, for the same reason and with the same
shape: the LLM call is the only non-deterministic step in the crawl, and its
answer is a property of the article's heading list, not of a particular run.

The concrete defect this fixes: at full scope, Phase 1 returned different
answers for Cupra on identical input across two consecutive runs — once
selecting "Fahrzeugmarke Cupra" (its complete 5-model lineup), once returning
"none" and dropping the brand into the review queue. Seven brands escalate, so
without a store the review queue is not reproducible between runs and coverage
silently wobbles.

Only deterministic verdicts are stored — an answer ("ok", including a genuine
"none") is a fact about the headings; a timeout or 5xx is not, and is left to
be retried next run. Same rule as mapping_store.
"""

import hashlib
import json
from pathlib import Path

STORE_PATH = Path(__file__).parent / "section_classifications.json"


def fingerprint_key(brand: str, article_title: str, headings: list[str]) -> str:
    """Stable content hash of the exact question asked: this brand, this
    article, this heading list. Order is preserved (unlike mapping_store's
    order-independent key) because the headings ARE the article's structure —
    a reordered or edited article is a different question."""
    blob = " ".join([brand, article_title, *headings])
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()


def load(path: Path = STORE_PATH) -> dict:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def save(data: dict, path: Path = STORE_PATH) -> None:
    """Atomic write (tmp + replace) so a crash mid-write can't corrupt the file."""
    tmp = path.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
    tmp.replace(path)


def record(
    store: dict,
    key: str,
    brand: str,
    article_title: str,
    headings: list[str],
    reasoning: str,
) -> None:
    store[key] = {
        "brand": brand,
        "article_title": article_title,
        "headings": headings,
        "reasoning": reasoning,
    }
