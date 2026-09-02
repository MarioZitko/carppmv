"""Phase 2 + Phase 3 runner: cached wikitext -> validated engine variants.

Offline/batch CLI, same category as app/wikipedia/crawl.py and
app/data/catalogues/ingest.py — never called from the /calculate request path.

    python -m app.wikipedia.extract --dry-run          # count tables, spend nothing
    python -m app.wikipedia.extract                    # extract every crawled brand
    python -m app.wikipedia.extract --brand Audi --brand Dacia
    python -m app.wikipedia.extract --report out.json --sample 50

Pipeline per crawled row (wikipedia_raw_articles, fetch_status=ok):
  1. select the tables in scope — the anchor's section if the row has one, the
     whole article otherwise (tables.tables_for_anchor)
  2. drop tables with no CO2 token (tables.select_tables) — ~70% of the corpus,
     and a call against one of them could only ever return null CO2
  3. dedupe on (brand, article, table content) so a shared article referenced by
     several anchors is not paid for twice
  4. one LLM call per surviving table, skipping tables already in the
     extraction store (extraction_store)
  5. Phase 3 validation per extracted variant; failures go to a review queue
  6. regex tripwire: flag any table that returned null CO2 while its wikitext
     contains CO2-shaped text (\\d{2,3} g/km)

**This phase writes nothing to Postgres.** Phase 4 (upsert into
WikipediaEngineData) is a separate, not-yet-built phase, gated behind a manual
review of this run's accuracy spot-check. Results land in the extraction store
and the JSON run report.
"""

import argparse
import asyncio
import collections
import json
import logging
import random
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select

from app.db.models import Base, WikipediaFetchStatus, WikipediaRawArticle
from app.db.session import AsyncSessionLocal, engine
from app.wikipedia import extraction_store, tables as tbl, validation
from app.wikipedia.llm_tables import extract_table

logger = logging.getLogger(__name__)

DEFAULT_CONCURRENCY = 12

# How much wikitext of a table is kept in the run report's spot-check sample.
# The full snippet always goes to the extraction store; the report just needs
# enough for a human to hand-check the numbers.
SAMPLE_SNIPPET_CHARS = 2600

# Share of the spot-check sample reserved for non-majority table orientations.
# Without a floor the sample mirrors the corpus (~88% transposed) and shows the
# reviewer nothing about the normal-table path.
MINORITY_ORIENTATION_SHARE = 0.4


@dataclass
class TableJob:
    """One table plus the provenance of the crawled row it came from."""

    brand: str
    article_title: str
    anchor: str | None
    source_url: str
    heading_context: str
    wikitext: str
    fingerprint: str
    mechanical_orientation: str


@dataclass
class RunStats:
    rows_scanned: int = 0
    articles: int = 0
    tables_seen: int = 0
    tables_after_prefilter: int = 0
    tables_from_cache: int = 0
    tables_called: int = 0
    tables_failed: int = 0
    variants_extracted: int = 0
    variants_with_co2: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    orientation_llm: dict = field(default_factory=dict)
    orientation_mechanical: dict = field(default_factory=dict)
    orientation_agreement: int = 0


async def _ensure_schema() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def _load_rows(brands: list[str] | None) -> list[WikipediaRawArticle]:
    async with AsyncSessionLocal() as session:
        stmt = (
            select(WikipediaRawArticle)
            .where(WikipediaRawArticle.fetch_status == WikipediaFetchStatus.OK)
            .order_by(WikipediaRawArticle.brand, WikipediaRawArticle.article_title)
        )
        if brands:
            stmt = stmt.where(WikipediaRawArticle.brand.in_(brands))
        return list((await session.execute(stmt)).scalars().all())


def build_jobs(rows: list[WikipediaRawArticle], stats: RunStats) -> list[TableJob]:
    """Steps 1-3: scope, prefilter, dedupe.

    Dedupe is on (brand, article, table fingerprint) rather than on the table
    alone: two brands can legitimately share an article (MG/Rover), and each
    brand's rows are its own coverage.
    """
    seen: set[tuple[str, str, str]] = set()
    counted_articles: set[str] = set()
    jobs: list[TableJob] = []

    for row in rows:
        stats.rows_scanned += 1
        if not row.wikitext:
            continue
        if row.article_title not in counted_articles:
            counted_articles.add(row.article_title)
            stats.tables_seen += len(tbl.iter_article_tables(row.wikitext))

        kept, _dropped = tbl.select_tables(row.wikitext, row.anchor)
        for table in kept:
            key = (row.brand, row.article_title, table.fingerprint)
            if key in seen:
                continue
            seen.add(key)
            jobs.append(
                TableJob(
                    brand=row.brand,
                    article_title=row.article_title,
                    anchor=row.anchor,
                    source_url=row.source_url,
                    heading_context=table.heading_context,
                    wikitext=table.wikitext,
                    fingerprint=table.fingerprint,
                    mechanical_orientation=tbl.guess_orientation(table.wikitext),
                )
            )
    stats.articles = len(counted_articles)
    stats.tables_after_prefilter = len(jobs)
    return jobs


async def _run_jobs(
    jobs: list[TableJob], store: dict, stats: RunStats, concurrency: int, store_path: Path
) -> list[dict]:
    """Step 4 — one call per table, bounded concurrency, cache-first.

    The store is saved periodically rather than only at the end so an
    interrupted run keeps what it paid for, matching crawl.py's incremental
    section_store.save.
    """
    semaphore = asyncio.Semaphore(concurrency)
    results: list[dict] = []
    failures: list[tuple[TableJob, str]] = []
    lock = asyncio.Lock()
    done = 0

    async def worker(job: TableJob) -> None:
        nonlocal done
        cached = store.get(job.fingerprint)
        if cached is not None:
            async with lock:
                stats.tables_from_cache += 1
                results.append({**cached, "fingerprint": job.fingerprint, "from_cache": True})
                done += 1
            return

        async with semaphore:
            try:
                extraction = await extract_table(
                    table_wikitext=job.wikitext,
                    heading_context=job.heading_context,
                    article_title=job.article_title,
                    brand=job.brand,
                )
            except Exception as exc:  # noqa: BLE001 - one bad table must not kill the run
                async with lock:
                    stats.tables_failed += 1
                    failures.append((job, f"{type(exc).__name__}: {exc}"))
                    done += 1
                return

        async with lock:
            stats.tables_called += 1
            stats.prompt_tokens += extraction.prompt_tokens
            stats.completion_tokens += extraction.completion_tokens
            stats.cost_usd += extraction.cost_usd
            record = {
                "brand": job.brand,
                "article_title": job.article_title,
                "anchor": job.anchor,
                "source_url": job.source_url,
                "heading_context": job.heading_context,
                "orientation": extraction.orientation,
                "variants": extraction.variants,
                "table_wikitext": job.wikitext,
                "fingerprint": job.fingerprint,
                "from_cache": False,
            }
            results.append(record)
            # The asymmetric cache rule (extraction_store's docstring): a result
            # that found CO2 is a fact worth freezing; an all-null one is left
            # out so a flaky false-null is retried rather than made permanent.
            if extraction.has_co2:
                extraction_store.record(
                    store,
                    job.fingerprint,
                    brand=job.brand,
                    article_title=job.article_title,
                    anchor=job.anchor,
                    source_url=job.source_url,
                    heading_context=job.heading_context,
                    orientation=extraction.orientation,
                    variants=extraction.variants,
                    table_wikitext=job.wikitext,
                )
            done += 1
            if done % 100 == 0:
                print(
                    f"  {done}/{len(jobs)} tables "
                    f"(called {stats.tables_called}, cached {stats.tables_from_cache}, "
                    f"failed {stats.tables_failed}, ${stats.cost_usd:.4f})",
                    flush=True,
                )
                extraction_store.save(store, store_path)

    await asyncio.gather(*(worker(job) for job in jobs))
    extraction_store.save(store, store_path)

    if failures:
        print(f"\n{len(failures)} table(s) failed extraction:")
        for job, message in failures[:10]:
            print(f"  {job.brand} / {job.article_title}: {message}")
    return results


def _analyse(results: list[dict], jobs: list[TableJob], stats: RunStats) -> dict:
    """Steps 5-6 plus the orientation cross-check and the flagged lists."""
    mechanical = {job.fingerprint: job.mechanical_orientation for job in jobs}
    llm_counts: collections.Counter = collections.Counter()
    mech_counts: collections.Counter = collections.Counter()

    valid_rows: list[dict] = []
    review_queue: list[dict] = []
    tripwire: list[dict] = []

    for result in results:
        fingerprint = result["fingerprint"]
        llm_orientation = result["orientation"]
        mech_orientation = mechanical.get(fingerprint, "unknown")
        llm_counts[llm_orientation] += 1
        mech_counts[mech_orientation] += 1
        if llm_orientation == mech_orientation:
            stats.orientation_agreement += 1

        variants = result.get("variants") or []
        stats.variants_extracted += len(variants)
        table_has_co2 = False

        for index, variant in enumerate(variants):
            has_co2 = variant.get("co2_min") is not None or variant.get("co2_max") is not None
            table_has_co2 = table_has_co2 or has_co2
            if has_co2:
                stats.variants_with_co2 += 1

            outcome = validation.validate_variant(variant)
            # Provenance travels with every row (plan §0): the structured
            # fields are useless for auditing without the wikitext they came
            # from and the URL they came from.
            row = {
                "brand": result["brand"],
                "article_title": result["article_title"],
                "anchor": result["anchor"],
                "source_url": result["source_url"],
                "heading_context": result["heading_context"],
                "orientation": llm_orientation,
                "orientation_mechanical": mech_orientation,
                "variant_index": index,
                **variant,
            }
            if outcome.ok:
                valid_rows.append(row)
            else:
                review_queue.append({**row, "validation_errors": outcome.errors})

        # Tripwire (Phase 2.5 amendment): the table produced no CO2 at all, but
        # its wikitext contains something SHAPED like a CO2 figure. Surfaced,
        # never auto-corrected — the point is to find prompt/schema blind spots.
        if not table_has_co2 and tbl.has_co2_shaped_value(result["table_wikitext"]):
            matches = tbl.CO2_VALUE_RE.findall(result["table_wikitext"])
            tripwire.append(
                {
                    "brand": result["brand"],
                    "article_title": result["article_title"],
                    "source_url": result["source_url"],
                    "heading_context": result["heading_context"],
                    "orientation": llm_orientation,
                    "variants_returned": len(variants),
                    "co2_shaped_matches": matches[:12],
                    "table_wikitext": result["table_wikitext"][:SAMPLE_SNIPPET_CHARS],
                }
            )

    stats.orientation_llm = dict(llm_counts)
    stats.orientation_mechanical = dict(mech_counts)
    return {"valid": valid_rows, "review_queue": review_queue, "tripwire": tripwire}


def _pick_across_brands(pool: list[dict], want: int, rng: random.Random) -> list[dict]:
    """Round-robin over brands so every brand is reached once before any brand
    gets a second table."""
    by_brand: dict[str, list[dict]] = collections.defaultdict(list)
    for result in pool:
        by_brand[result["brand"]].append(result)
    for items in by_brand.values():
        rng.shuffle(items)

    brands = sorted(by_brand, key=lambda b: (-len(by_brand[b]), b))
    picked: list[dict] = []
    while len(picked) < want:
        progressed = False
        for brand in brands:
            if len(picked) >= want:
                break
            if by_brand[brand]:
                picked.append(by_brand[brand].pop())
                progressed = True
        if not progressed:
            break
    return picked


def build_sample(results: list[dict], size: int, seed: int = 7) -> list[dict]:
    """Stratified spot-check sample (Phase 2.5 amendment).

    Stratifies on ORIENTATION first, then brand within each orientation. That
    order is load-bearing: the corpus is ~88% transposed, so a brand-first
    sample comes back 100% transposed and cannot show whether the normal-table
    path works at all — which is exactly what the spot-check exists to
    establish. A fixed share is therefore reserved for the minority
    orientations, capped by what actually exists.

    Each entry carries the extracted JSON, the raw wikitext it came from, and
    the source URL — the three things needed to hand-check a row.
    """
    usable = [r for r in results if r.get("variants")]
    if not usable:
        return []
    rng = random.Random(seed)

    by_orientation: dict[str, list[dict]] = collections.defaultdict(list)
    for result in usable:
        by_orientation[result["orientation"]].append(result)

    ordered = sorted(by_orientation, key=lambda o: -len(by_orientation[o]))
    majority, minorities = ordered[0], ordered[1:]
    quota: dict[str, int] = {}
    if minorities:
        per_minority = max(1, int(size * MINORITY_ORIENTATION_SHARE) // len(minorities))
        for orientation in minorities:
            quota[orientation] = min(len(by_orientation[orientation]), per_minority)
    quota[majority] = min(len(by_orientation[majority]), size - sum(quota.values()))

    picked: list[dict] = []
    for orientation, want in quota.items():
        picked.extend(_pick_across_brands(by_orientation[orientation], want, rng))

    return [
        {
            "brand": r["brand"],
            "article_title": r["article_title"],
            "source_url": r["source_url"],
            "heading_context": r["heading_context"],
            "orientation_llm": r["orientation"],
            "extracted_json": r["variants"],
            "table_wikitext": r["table_wikitext"][:SAMPLE_SNIPPET_CHARS],
        }
        for r in picked
    ]


async def run(
    brands: list[str] | None,
    dry_run: bool,
    concurrency: int,
    limit: int | None,
    sample_size: int,
    report_path: Path | None,
    store_path: Path,
) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    await _ensure_schema()

    stats = RunStats()
    rows = await _load_rows(brands)
    if not rows:
        raise SystemExit("No crawled wikipedia_raw_articles rows found — run the Phase 0 crawl first.")

    jobs = build_jobs(rows, stats)
    if limit:
        jobs = jobs[:limit]

    by_brand = collections.Counter(job.brand for job in jobs)
    print(f"Crawled rows scanned:      {stats.rows_scanned}")
    print(f"Unique ok articles:        {stats.articles}")
    print(f"Tables found (all):        {stats.tables_seen}")
    print(f"Tables after CO2 prefilter:{stats.tables_after_prefilter}"
          f"  ({stats.tables_after_prefilter / max(stats.tables_seen, 1) * 100:.0f}%)")
    print(f"Jobs this run:             {len(jobs)} across {len(by_brand)} brands")
    print("\nMechanical orientation guess over the prefiltered tables:")
    mech = collections.Counter(job.mechanical_orientation for job in jobs)
    for name, count in mech.most_common():
        print(f"  {name:<18}{count:>5}  {count / max(len(jobs), 1) * 100:.0f}%")

    if dry_run:
        print("\n--dry-run: no LLM calls made, nothing written.")
        return

    store = extraction_store.load(store_path)
    print(f"\nExtraction store: {len(store)} cached table(s) — these cost no LLM calls.")
    print(f"Extracting with concurrency {concurrency}…\n")

    started = time.monotonic()
    results = await _run_jobs(jobs, store, stats, concurrency, store_path)
    wall = time.monotonic() - started

    analysis = _analyse(results, jobs, stats)
    sample = build_sample(results, sample_size)

    print("\n" + "=" * 64)
    print(f"Wall-clock: {wall / 60:.1f} min")
    print(f"Tables: called={stats.tables_called} cached={stats.tables_from_cache} "
          f"failed={stats.tables_failed}")
    print(f"Variants extracted: {stats.variants_extracted} "
          f"({stats.variants_with_co2} with a CO2 value)")
    print(f"Tokens: in={stats.prompt_tokens:,} out={stats.completion_tokens:,}")
    print(f"Cost:   ${stats.cost_usd:.4f}")
    print("\nOrientation as reported by the LLM:")
    for name, count in sorted(stats.orientation_llm.items(), key=lambda kv: -kv[1]):
        print(f"  {name:<18}{count:>5}  {count / max(len(results), 1) * 100:.0f}%")
    print("Orientation per the mechanical heuristic (cross-check):")
    for name, count in sorted(stats.orientation_mechanical.items(), key=lambda kv: -kv[1]):
        print(f"  {name:<18}{count:>5}  {count / max(len(results), 1) * 100:.0f}%")
    print(f"Agreement: {stats.orientation_agreement}/{len(results)} "
          f"({stats.orientation_agreement / max(len(results), 1) * 100:.0f}%)")
    print(f"\nPhase 3 — valid rows:  {len(analysis['valid'])}")
    print(f"Phase 3 — review queue: {len(analysis['review_queue'])}")
    print(f"Regex tripwire flagged: {len(analysis['tripwire'])} table(s)")
    print(f"Spot-check sample:      {len(sample)} tables across "
          f"{len({s['brand'] for s in sample})} brands")

    if report_path:
        payload = {
            "generated_at": datetime.now(UTC).isoformat(),
            "brands": sorted(by_brand),
            "stats": asdict(stats),
            "wall_clock_seconds": wall,
            "valid_rows": analysis["valid"],
            "review_queue": analysis["review_queue"],
            "tripwire": analysis["tripwire"],
            "spot_check_sample": sample,
        }
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=1))
        print(f"\nReport written to {report_path}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Phase 2/3: extract engine variants from crawled de.wikipedia tables."
    )
    parser.add_argument(
        "--brand", action="append", dest="brands", metavar="BRAND",
        help="Crawled brand to extract (repeatable). Default: every crawled brand.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Count tables and show the prefilter/orientation breakdown, make no LLM calls.",
    )
    parser.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY)
    parser.add_argument("--limit", type=int, help="Process at most N tables (smoke tests).")
    parser.add_argument("--sample", type=int, default=50, help="Spot-check sample size.")
    parser.add_argument("--report", type=Path, help="Write the JSON run report here.")
    parser.add_argument(
        "--store", type=Path, default=extraction_store.STORE_PATH,
        help="Extraction store path (determinism cache + Phase 2 output artifact).",
    )
    args = parser.parse_args()
    asyncio.run(
        run(args.brands, args.dry_run, args.concurrency, args.limit,
            args.sample, args.report, args.store)
    )


if __name__ == "__main__":
    main()
