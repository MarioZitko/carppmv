"""Phase 4 — upsert validated Phase 2/3 rows into `wikipedia_engine_data`.

Offline/batch CLI, same category as app/wikipedia/extract.py and
app/data/catalogues/ingest.py — never called from the /calculate request path.

    python -m app.wikipedia.upsert --dry-run     # classify + validate, write nothing
    python -m app.wikipedia.upsert               # upsert every eligible row
    python -m app.wikipedia.upsert --brand Audi --brand Opel
    python -m app.wikipedia.upsert --review-out data/wikipedia/phase4_review_queue.json

**Gated phase.** The plan makes this upsert conditional on a human having read
the Phase 2.5 accuracy spot-check first (`extract.py --sample`), because a
wrong orientation reading produces well-formed, plausible, wrong rows that no
mechanical check catches. Nothing here re-checks that; it is a process gate,
not a code gate.

Input is `data/wikipedia/table_extractions.json` — the extraction store, which
is the canonical Phase 2 artifact: it is keyed by table fingerprint and carries
the raw wikitext and source URL each row needs for provenance. Tables whose
variants ALL came back with null CO2 are deliberately absent from it
(extraction_store's asymmetric cache rule), which is the right cut here too: a
row with no CO2 gives Phase 5 nothing to return. The run report's totals are
therefore slightly higher than this phase's; the printed summary reconciles the
two rather than leaving the gap unexplained.

Per-row pipeline:

  1. **Brand cross-check** (app/wikipedia/brand_check.py). The crawl brand is
     not authoritative — see that module. Rows whose title names a different
     marque are re-filed under it; rows whose title names no recognisable
     marque are held out of the upsert entirely and land in the review queue.
  2. **co2 order correction.** When the source table gave co2_min > co2_max the
     two are swapped and `source_order_corrected` is set. The correction is
     applied *before* validation, so a row whose only defect was the ordering
     becomes eligible instead of sitting in the queue forever — and the column
     records that it happened, so it is traceable rather than silent. 53 rows
     in the first run are exactly this case.
  3. **Phase 3 validation** (app/wikipedia/validation.py) on the corrected row.
     Anything still failing goes to the review queue and is never inserted.
  4. **Batch sorted upsert**, mirroring app/data/catalogues/ingest.py: rows are
     sorted by the unique-constraint columns before insert so concurrent
     batches acquire row locks in the same order (Postgres deadlock avoidance),
     with a single retry on a fresh transaction if one slips through anyway.

The unique key is `(source_fingerprint, variant_index)`. This is a deliberate
departure from the key named in docs/WIKIPEDIA_CO2_PLAN.md §Phase 4
(`brand, model_article_title, engine_code, production_start`), measured against
the real corpus: that key collapses 757 of 8,895 rows, and 409 of the collapsed
groups carry genuinely different CO2 values. The cause is not fixable by adding
spec columns — the Phase 2 schema has no gearbox or drivetrain field, so a
table's "2.0 TDI · 103 kW · manual · 153 g/km" and "2.0 TDI · 103 kW ·
automatic · 159 g/km" rows are byte-identical on every column the plan's key
could use (adding power_kw, displacement_cc *and* fuel_type still collapses 313
rows, 98 of them conflicting). Keying on provenance keeps every distinct
measurement, stays idempotent across re-runs because the fingerprint is a
content hash of the source table, and still converges two brands that crawled
the same article onto one row. Phase 5 then reports the union of an
indistinguishable group as a range, which is the honest answer and the one the
plan asks for ("return the CO2 range, never collapse to a point value").
"""

import argparse
import asyncio
import collections
import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import delete, func, select, tuple_
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db.models import Base, WikipediaBrandCheck, WikipediaEngineData
from app.db.session import AsyncSessionLocal, engine
from app.wikipedia import brand_check, extraction_store, validation

logger = logging.getLogger(__name__)

# 20 columns x 400 rows = 8,000 bound parameters, comfortably under Postgres'
# 32,767 ceiling. Same shape as ingest.py's 500 x 12.
BATCH_SIZE = 400

# How much source wikitext travels with each row. The whole table is often
# 10-30 kB and the same table backs dozens of variants; this is the audit trail
# (plan §0), and 4 kB is enough to find and hand-check the row it came from.
SNIPPET_CHARS = 4000

DEFAULT_REVIEW_PATH = Path("data/wikipedia/phase4_review_queue.json")
# Phase 2's run report. Read for one thing only: the Phase 2.5 regex tripwire
# list. Those tables returned no CO2 at all, so they are absent from the
# extraction store by construction and this phase would otherwise never see
# them — but they are held-for-review items in exactly the same sense as a
# validation failure, and belong in one queue rather than two.
DEFAULT_PHASE2_REPORT = Path("data/wikipedia/phase2_report.json")

# Ceiling on how wide a swap-corrected range may be before the correction is
# disbelieved and the row goes to review instead of the table.
#
# The swap assumes `co2_min > co2_max` means the source printed the range
# backwards. That is true 48 times out of 49 — every legitimate correction in
# the first run lands at 28 g/km or less. The 49th was `Audi A3 8V / 30 g-tron`,
# whose wikitext literally reads "114–12 g/km": a dropped digit on 124 in the
# German Wikipedia source, sitting between neighbours reading 129–150 and
# 144–159. Swapping that does not recover a range, it manufactures a
# plausible-looking 12–114 out of a typo — and 12 g/km matches neither the
# CNG (~88–99) nor the petrol (~115–120) mode of the car.
#
# So the rule is: a cell that needs swapping AND yields an implausibly wide
# range is not a backwards range, it is a corrupt cell. 40 sits in the empty
# band between the widest real correction (28) and the outlier (102).
WIDE_CORRECTED_RANGE_G_KM = 40.0


@dataclass
class UpsertStats:
    tables_read: int = 0
    variants_read: int = 0
    brand_confirmed: int = 0
    brand_refiled: int = 0
    brand_unverified: int = 0
    co2_order_corrected: int = 0
    validation_failed: int = 0
    correction_rejected: int = 0
    eligible: int = 0
    rows_written: int = 0
    rows_pruned: int = 0
    refiled_pairs: dict = field(default_factory=dict)
    unverified_titles: dict = field(default_factory=dict)


def _snippet(text: str) -> str:
    return text[:SNIPPET_CHARS]


def _clean_number(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _clean_str(value, limit: int) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text[:limit] if text else None


def build_rows(
    store: dict, brands: list[str] | None, stats: UpsertStats
) -> tuple[list[dict], list[dict], list[dict]]:
    """Steps 1-3: cross-check, correct, validate.

    Returns (eligible_rows, review_queue, wide_corrected_ranges). Filtering by
    `--brand` is applied to the CRAWL brand, so `--brand Subaru` still shows
    what Subaru's crawl produced even though those rows re-file to Opel.
    """
    eligible: list[dict] = []
    review: list[dict] = []
    wide: list[dict] = []
    refiled: collections.Counter = collections.Counter()
    unverified: collections.Counter = collections.Counter()

    for fingerprint in sorted(store):
        record = store[fingerprint]
        crawl_brand = record["brand"]
        if brands and crawl_brand not in brands:
            continue
        stats.tables_read += 1

        title = record["article_title"]
        verdict = brand_check.check(crawl_brand, title)
        if verdict.verdict is WikipediaBrandCheck.CONFIRMED:
            stats.brand_confirmed += 1
        elif verdict.verdict is WikipediaBrandCheck.REFILED:
            stats.brand_refiled += 1
            refiled[f"{crawl_brand} -> {verdict.effective_brand}: {title}"] += len(
                record.get("variants") or []
            )
        else:
            stats.brand_unverified += 1
            unverified[f"{crawl_brand}: {title}"] += len(record.get("variants") or [])

        for index, variant in enumerate(record.get("variants") or []):
            stats.variants_read += 1
            provenance = {
                "crawl_brand": crawl_brand,
                "effective_brand": verdict.effective_brand,
                "brand_check": verdict.verdict.value,
                "model_article_title": title,
                "heading_context": record.get("heading_context") or "",
                "source_url": record["source_url"],
                "source_fingerprint": fingerprint,
                "variant_index": index,
            }

            # Step 2 — order correction, applied BEFORE validation so a row
            # whose only defect was the ordering becomes eligible, with the
            # column recording that it was touched.
            co2_min = _clean_number(variant.get("co2_min"))
            co2_max = _clean_number(variant.get("co2_max"))
            corrected = False
            if co2_min is not None and co2_max is not None and co2_min > co2_max:
                co2_min, co2_max = co2_max, co2_min
                corrected = True
                stats.co2_order_corrected += 1

            candidate = {**variant, "co2_min": co2_min, "co2_max": co2_max}
            outcome = validation.validate_variant(candidate)

            if not outcome.ok:
                stats.validation_failed += 1
                review.append(
                    {
                        **provenance,
                        **candidate,
                        "source_order_corrected": corrected,
                        "reason": "phase3_validation",
                        "validation_errors": outcome.errors,
                    }
                )
                continue

            # Step 1's held-back case. The row is well-formed; what is missing
            # is any way to confirm which marque it belongs to, so it is queued
            # rather than filed under a brand it may not be.
            if not verdict.usable:
                review.append(
                    {
                        **provenance,
                        **candidate,
                        "source_order_corrected": corrected,
                        "reason": "brand_unverified",
                        "validation_errors": [
                            f"article title {title!r} names no recognisable marque; "
                            f"cannot confirm the crawl brand {crawl_brand!r}"
                        ],
                    }
                )
                continue

            # A correction we do not believe (see WIDE_CORRECTED_RANGE_G_KM).
            # Held for review rather than upserted: Phase 5 would refuse to
            # serve it anyway on width, so storing it buys nothing and risks a
            # future reader trusting the flag column instead of the number.
            if corrected and co2_max - co2_min > WIDE_CORRECTED_RANGE_G_KM:
                stats.correction_rejected += 1
                entry = {**provenance, **candidate, "source_order_corrected": corrected}
                wide.append(entry)
                review.append(
                    {
                        **entry,
                        "reason": "implausible_correction",
                        "validation_errors": [
                            f"co2_min/co2_max swap yields {co2_max - co2_min:.0f} g/km "
                            f"({co2_min:.0f}-{co2_max:.0f}), wider than "
                            f"{WIDE_CORRECTED_RANGE_G_KM:.0f} — the source cell is "
                            f"corrupt (truncated or dual-fuel), not printed backwards"
                        ],
                    }
                )
                continue

            eligible.append(
                {
                    "brand": verdict.effective_brand,
                    "crawl_brand": crawl_brand,
                    "brand_check": verdict.verdict,
                    "model_article_title": title[:512],
                    "heading_context": (record.get("heading_context") or "")[:512],
                    "engine_code": _clean_str(variant.get("engine_code"), 256),
                    "production_start": _clean_str(variant.get("production_start"), 16),
                    "production_end": _clean_str(variant.get("production_end"), 16),
                    "displacement_cc": _clean_number(variant.get("displacement_cc")),
                    "power_kw": _clean_number(variant.get("power_kw")),
                    "fuel_type": _clean_str(variant.get("fuel_type"), 32),
                    "co2_min": co2_min,
                    "co2_max": co2_max,
                    "source_order_corrected": corrected,
                    "source_url": record["source_url"][:1024],
                    "source_wikitext_snippet": _snippet(record.get("table_wikitext") or ""),
                    "source_fingerprint": fingerprint,
                    "variant_index": index,
                }
            )

    stats.eligible = len(eligible)
    stats.refiled_pairs = dict(refiled)
    stats.unverified_titles = dict(unverified)
    return eligible, review, wide


def tripwire_entries(report_path: Path | None, brands: list[str] | None) -> list[dict]:
    """Phase 2.5's regex-tripwire tables, shaped as review-queue entries.

    A tripwire table produced no CO2 while its wikitext contains CO2-shaped
    text — a suspected prompt or schema blind spot. It is *never* auto-corrected
    (that is the whole point of surfacing it), and it cannot be upserted since
    there is nothing to upsert; it is carried here so the review queue is one
    list a human works through, not two.
    """
    if not report_path or not report_path.exists():
        return []
    report = json.loads(report_path.read_text(encoding="utf-8"))
    entries = []
    for item in report.get("tripwire") or []:
        if brands and item.get("brand") not in brands:
            continue
        entries.append(
            {
                "crawl_brand": item.get("brand"),
                "effective_brand": item.get("brand"),
                "brand_check": None,
                "model_article_title": item.get("article_title"),
                "heading_context": item.get("heading_context"),
                "source_url": item.get("source_url"),
                "reason": "phase2_5_tripwire",
                "validation_errors": [
                    "table returned no CO2 but its wikitext contains CO2-shaped text: "
                    + ", ".join(item.get("co2_shaped_matches") or [])
                ],
                "variants_returned": item.get("variants_returned"),
            }
        )
    return entries


async def _ensure_schema() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def upsert_rows(rows: list[dict]) -> int:
    """Step 4 — batch sorted upsert, mirroring ingest.py::_upsert_rows.

    Sorting by the unique-constraint columns is what keeps concurrent batches
    acquiring row locks in the same order; without it two batches touching the
    same conflicting rows in opposite order deadlock.
    """
    if not rows:
        return 0

    # Last-writer-wins within this run, so a re-derived row cannot collide with
    # itself inside one INSERT (Postgres rejects a batch that hits the same
    # conflict target twice).
    deduped: dict[tuple[str, int], dict] = {}
    for row in rows:
        deduped[(row["source_fingerprint"], row["variant_index"])] = row
    ordered = sorted(deduped.values(), key=lambda r: (r["source_fingerprint"], r["variant_index"]))

    updatable = (
        "brand", "crawl_brand", "brand_check", "model_article_title", "heading_context",
        "engine_code", "production_start", "production_end", "displacement_cc",
        "power_kw", "fuel_type", "co2_min", "co2_max", "source_order_corrected",
        "source_url", "source_wikitext_snippet",
    )

    total = 0
    for start in range(0, len(ordered), BATCH_SIZE):
        batch = ordered[start : start + BATCH_SIZE]
        stmt = pg_insert(WikipediaEngineData).values(batch)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_wikipedia_engine_row",
            set_={name: getattr(stmt.excluded, name) for name in updatable},
        )
        # Sorting makes deadlocks rare, not impossible — retry once on a fresh
        # transaction before giving up on the batch.
        for attempt in range(2):
            try:
                async with AsyncSessionLocal() as session:
                    result = await session.execute(stmt)
                    await session.commit()
                total += result.rowcount or 0
                break
            except Exception as exc:
                orig = getattr(exc, "orig", None)
                if attempt == 0 and orig is not None and "deadlock" in str(orig).lower():
                    continue
                raise
    return total


async def prune_review_rows(review: list[dict]) -> int:
    """Delete rows the table holds that this run has ruled ineligible.

    The upsert alone cannot do this: it only ever inserts or updates, so a row
    that was eligible on an earlier run and is held for review on this one
    would sit in the table indefinitely, still carrying the old values. That is
    exactly what happened to the `Audi A3 8V / 30 g-tron` row when the
    implausible-correction rule was added.

    Scoped to the review queue's own keys rather than "everything not eligible",
    because a `--brand`-filtered run must not delete other brands' rows.
    """
    keys = [
        (row["source_fingerprint"], row["variant_index"])
        for row in review
        if row.get("source_fingerprint") is not None
        and row.get("variant_index") is not None
    ]
    if not keys:
        return 0
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            delete(WikipediaEngineData).where(
                tuple_(
                    WikipediaEngineData.source_fingerprint,
                    WikipediaEngineData.variant_index,
                ).in_(keys)
            )
        )
        await session.commit()
    return result.rowcount or 0


async def brand_counts() -> list[tuple[str, int]]:
    async with AsyncSessionLocal() as session:
        stmt = (
            select(WikipediaEngineData.brand, func.count())
            .group_by(WikipediaEngineData.brand)
            .order_by(func.count().desc(), WikipediaEngineData.brand)
        )
        return [(brand, count) for brand, count in (await session.execute(stmt)).all()]


async def run(
    brands: list[str] | None,
    dry_run: bool,
    store_path: Path,
    review_path: Path | None,
    report_path: Path | None,
    phase2_report_path: Path | None,
) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    store = extraction_store.load(store_path)
    if not store:
        raise SystemExit(
            f"No extraction store at {store_path} — run `python -m app.wikipedia.extract` first."
        )

    stats = UpsertStats()
    eligible, review, wide = build_rows(store, brands, stats)
    review.extend(tripwire_entries(phase2_report_path, brands))

    print(f"Extraction store:        {len(store)} table(s) at {store_path}")
    print(f"Tables in scope:         {stats.tables_read}")
    print(f"Variants read:           {stats.variants_read}")
    print("\nBrand cross-check (per table):")
    print(f"  confirmed              {stats.brand_confirmed}")
    print(f"  re-filed to the marque the title names   {stats.brand_refiled}")
    for label, count in sorted(stats.refiled_pairs.items(), key=lambda kv: -kv[1]):
        print(f"      {count:>4} variants  {label}")
    print(f"  unverified (held back) {stats.brand_unverified}")
    for label, count in sorted(stats.unverified_titles.items(), key=lambda kv: -kv[1]):
        print(f"      {count:>4} variants  {label}")
    print(f"\nco2_min/co2_max order corrected: {stats.co2_order_corrected}")
    if wide:
        print(f"  …of which wider than {WIDE_CORRECTED_RANGE_G_KM:.0f} g/km after the swap "
              f"({len(wide)}) — correction DISBELIEVED, held for review, not upserted:")
        for row in wide:
            print(f"      {row['effective_brand']} {row['model_article_title']} "
                  f"{row.get('engine_code')!r}: {row['co2_min']:.0f}-{row['co2_max']:.0f} g/km")
    print(f"\nReview queue (not upserted): {len(review)}")
    reasons = collections.Counter(r["reason"] for r in review)
    for reason, count in reasons.most_common():
        print(f"  {reason:<24} {count}")
    print(f"Eligible for upsert:     {stats.eligible}")

    if review_path:
        review_path.parent.mkdir(parents=True, exist_ok=True)
        review_path.write_text(
            json.dumps(
                {
                    "generated_at": datetime.now(UTC).isoformat(),
                    "counts": dict(reasons),
                    "rows": review,
                },
                ensure_ascii=False,
                indent=1,
            )
        )
        print(f"Review queue written to {review_path}")

    if dry_run:
        print("\n--dry-run: nothing written to Postgres.")
        return

    await _ensure_schema()
    stats.rows_written = await upsert_rows(eligible)
    print(f"\nUpserted: {stats.rows_written} row(s)")
    stats.rows_pruned = await prune_review_rows(review)
    if stats.rows_pruned:
        print(f"Pruned:   {stats.rows_pruned} row(s) the table held that are now held for review")

    counts = await brand_counts()
    total = sum(count for _brand, count in counts)
    print(f"\nwikipedia_engine_data now holds {total} row(s) across {len(counts)} brands:")
    for brand, count in counts:
        print(f"  {count:>6}  {brand}")

    if report_path:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(
                {
                    "generated_at": datetime.now(UTC).isoformat(),
                    "stats": asdict(stats),
                    "rows_by_brand": dict(counts),
                    "total_rows": total,
                    "review_queue_size": len(review),
                    "review_queue_reasons": dict(reasons),
                    "wide_corrected_ranges": wide,
                },
                ensure_ascii=False,
                indent=1,
            )
        )
        print(f"\nReport written to {report_path}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Phase 4: upsert validated Wikipedia engine rows into Postgres."
    )
    parser.add_argument(
        "--brand", action="append", dest="brands", metavar="BRAND",
        help="Filter by CRAWL brand (repeatable). Default: everything in the store.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Cross-check, correct and validate, print the summary, write nothing.",
    )
    parser.add_argument(
        "--store", type=Path, default=extraction_store.STORE_PATH,
        help="Phase 2 extraction store to read.",
    )
    parser.add_argument(
        "--review-out", type=Path, default=DEFAULT_REVIEW_PATH,
        help="Where to write the review queue (rows held back, with reasons).",
    )
    parser.add_argument("--report", type=Path, help="Write the JSON run report here.")
    parser.add_argument(
        "--phase2-report", type=Path, default=DEFAULT_PHASE2_REPORT,
        help="Phase 2 run report, read for its Phase 2.5 tripwire list only.",
    )
    args = parser.parse_args()
    asyncio.run(
        run(args.brands, args.dry_run, args.store, args.review_out,
            args.report, args.phase2_report)
    )


if __name__ == "__main__":
    main()
