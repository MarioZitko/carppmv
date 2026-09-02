"""Persistent store of Phase 2 table-extraction results.

Mirrors app/wikipedia/section_store.py (and, behind it,
app/catalogue/mapping_store.py) for the same reason: the LLM call is the only
non-deterministic step, and its answer is a property of the table's content, not
of a particular run. Phase 0 proved this empirically — Phase 1 returned
different verdicts for Cupra on identical input at temperature 0 across two
consecutive runs.

**Only results that actually found CO2 are cached.** An extraction whose
variants all came back with null CO2 is left uncached and re-asked on the next
run. This is the deliberate asymmetry (plan §Phase 2 amendment): caching a
false null would turn one flaky call into permanent, silent coverage loss on a
table that really does carry emissions data — exactly the failure mode the
Phase 2.5 spot-check exists to catch, so it must not be re-created here. A
result WITH CO2 is a fact about the table and is cheap to trust.

The file doubles as the run's output artifact: Phase 4's upsert is a separate,
not-yet-built phase, so extraction results land here rather than in Postgres.
"""

import json
from pathlib import Path

# Kept out of the package directory: this is bulk run data (megabytes of
# wikitext snippets), not a small checked-in artifact like
# section_classifications.json.
STORE_PATH = Path("data/wikipedia/table_extractions.json")


def load(path: Path = STORE_PATH) -> dict:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def save(data: dict, path: Path = STORE_PATH) -> None:
    """Atomic write (tmp + replace) so a crash mid-write can't corrupt the file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1, sort_keys=True)
    tmp.replace(path)


def record(
    store: dict,
    key: str,
    *,
    brand: str,
    article_title: str,
    anchor: str | None,
    source_url: str,
    heading_context: str,
    orientation: str,
    variants: list[dict],
    table_wikitext: str,
) -> None:
    """Store one table's result WITH its provenance.

    The raw wikitext snippet and source URL travel with the structured fields
    because §0 makes that non-negotiable — it is the audit trail that makes a
    bad extraction traceable and fixable rather than silently poisoning
    downstream matches.
    """
    store[key] = {
        "brand": brand,
        "article_title": article_title,
        "anchor": anchor,
        "source_url": source_url,
        "heading_context": heading_context,
        "orientation": orientation,
        "variants": variants,
        "table_wikitext": table_wikitext,
    }
