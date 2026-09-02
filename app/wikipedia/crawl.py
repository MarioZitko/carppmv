"""Phase 0 + Phase 1 crawler: brand article -> model articles -> cached wikitext.

Offline/batch CLI, same category as app/data/catalogues/ingest.py — never
called from the /calculate request path.

    python -m app.wikipedia.crawl                       # the 10 in-scope brands
    python -m app.wikipedia.crawl --brand Opel --brand Kia
    python -m app.wikipedia.crawl --dry-run --report /tmp/crawl.json

Per brand (the batch unit, so a run can be stopped and resumed between
brands):
  1. resolve the brand's de.wikipedia article (first candidate that exists and
     isn't a disambiguation page)
  2. fetch its wikitext, split into level-2 sections
  3. fuzzy-match the model-list section(s) on "modell"
  4. pull {{Hauptartikel}} targets and brand-prefixed wikilinks out of them
  5. escalate to Phase 1 (LLM heading classification) if that yielded zero
     sections or fewer than 5 qualifying links
  6. batch-resolve the link titles (existence + redirects, 50 per request)
  7. fetch wikitext once per unique article, skipping anything already cached
     ok in wikipedia_raw_articles, and upsert one row per (title, anchor)

Resumability is what makes an interrupted multi-hundred-request crawl cheap to
restart: an already-cached ok row is never re-fetched, so a re-run costs one
request per brand article plus the batched title lookups.
"""

import argparse
import asyncio
import json
import logging
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db.models import Base, Catalogue, WikipediaFetchStatus, WikipediaRawArticle
from app.db.session import AsyncSessionLocal, engine
from app.wikipedia import section_store, sections as sec
from app.wikipedia.brand_articles import BRAND_ARTICLES, PHASE_0_BRANDS, get_brand_article
from app.wikipedia.client import WikipediaClient
from app.wikipedia.llm_sections import classify_model_sections

logger = logging.getLogger(__name__)

# Rows written per upsert statement. Wikitext is large (tens to hundreds of KB
# per article), so batches stay small — this is not the catalogue's 1k-row case.
UPSERT_BATCH_SIZE = 20

# For each brand, every article title that belongs to a DIFFERENT brand's
# mapping — used to stop the index one-hop from crossing marque boundaries.
# Phase 1 verdicts, loaded once per process so escalated brands resolve the
# same way on every run instead of re-asking a non-deterministic model.
_SECTION_STORE: dict = section_store.load()

_OTHER_BRAND_ARTICLES: dict[str, frozenset[str]] = {
    brand: frozenset(
        title
        for other, spec in BRAND_ARTICLES.items()
        if other != brand
        for title in (*spec.candidates, *spec.extra_articles)
    )
    for brand in BRAND_ARTICLES
}


@dataclass
class BrandReport:
    """Everything the run log needs to say about one brand."""

    brand: str
    catalogue_rows: int = 0
    article_title: str | None = None
    # Every article this brand's links were harvested from — the resolved
    # candidate plus any extra_articles (see BrandArticle.extra_articles).
    articles_processed: list[str] = field(default_factory=list)
    article_candidates_tried: list[str] = field(default_factory=list)
    level2_headings: int = 0
    # What the mechanical "modell" match found, kept separate from
    # matched_headings so an escalated brand's report still shows that the
    # fuzzy pass came up empty rather than looking like it succeeded.
    fuzzy_matched_headings: list[str] = field(default_factory=list)
    matched_headings: list[str] = field(default_factory=list)
    links_found: int = 0
    # Short-name links ([[Twingo]]) admitted because they redirect INTO a
    # brand-prefixed article. Counted separately so the report shows how much
    # of a brand's coverage depends on that rescue.
    links_rescued: int = 0
    # Model links harvested one hop into an index article (see
    # sections.extract_index_targets).
    index_articles_followed: list[str] = field(default_factory=list)
    links_from_index: int = 0
    escalated: bool = False
    escalation_reason: str | None = None
    llm_headings: list[str] = field(default_factory=list)
    llm_reasoning: str | None = None
    # True when the Phase 1 verdict came from the persisted store rather than
    # a fresh LLM call (see app/wikipedia/section_store.py).
    llm_from_cache: bool = False
    needs_manual_review: bool = False
    unique_articles: int = 0
    pairs: int = 0
    fetch_ok: int = 0
    fetch_not_found: int = 0
    fetch_error: int = 0
    skipped_cached: int = 0
    sample_articles: list[str] = field(default_factory=list)
    error: str | None = None
    seconds: float = 0.0


async def _ensure_schema() -> None:
    """create_all only adds missing tables (app/main.py does the same on
    startup) — running the CLI before the API has ever booted still works."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def _catalogue_brand_counts(brands: list[str]) -> dict[str, int]:
    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                select(Catalogue.brand, func.count())
                .where(Catalogue.brand.in_(brands))
                .group_by(Catalogue.brand)
            )
        ).all()
    return {brand: count for brand, count in rows}


async def _cached_state(brand: str) -> tuple[set[tuple[str, str]], set[str]]:
    """(pairs already cached ok, article titles already cached ok) for a brand."""
    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                select(WikipediaRawArticle.article_title, WikipediaRawArticle.anchor_key)
                .where(WikipediaRawArticle.brand == brand)
                .where(WikipediaRawArticle.fetch_status == WikipediaFetchStatus.OK)
            )
        ).all()
    pairs = {(title, anchor_key) for title, anchor_key in rows}
    return pairs, {title for title, _ in pairs}


async def _load_cached_wikitext(brand: str, titles: set[str]) -> dict[str, str]:
    """Reuse wikitext already stored for this brand when a *new* anchor points
    into an article we've fetched before — no reason to pay for it twice."""
    if not titles:
        return {}
    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                select(WikipediaRawArticle.article_title, WikipediaRawArticle.wikitext)
                .where(WikipediaRawArticle.brand == brand)
                .where(WikipediaRawArticle.article_title.in_(sorted(titles)))
                .where(WikipediaRawArticle.fetch_status == WikipediaFetchStatus.OK)
            )
        ).all()
    return {title: text for title, text in rows if text}


async def _upsert_rows(rows: list[dict]) -> None:
    """Batch upsert, sorted by the unique-constraint columns first — same
    Postgres deadlock avoidance as app/data/catalogues/ingest.py."""
    if not rows:
        return
    rows = sorted(rows, key=lambda r: (r["brand"], r["article_title"], r["anchor_key"]))
    async with AsyncSessionLocal() as session:
        for start in range(0, len(rows), UPSERT_BATCH_SIZE):
            chunk = rows[start : start + UPSERT_BATCH_SIZE]
            stmt = pg_insert(WikipediaRawArticle).values(chunk)
            stmt = stmt.on_conflict_do_update(
                index_elements=["brand", "article_title", "anchor_key"],
                set_={
                    "wikitext": stmt.excluded.wikitext,
                    "fetch_status": stmt.excluded.fetch_status,
                    "error_message": stmt.excluded.error_message,
                    "fetched_at": stmt.excluded.fetched_at,
                },
            )
            await session.execute(stmt)
        await session.commit()


async def _resolve_brand_article(
    client: WikipediaClient, candidates: tuple[str, ...], report: BrandReport
) -> str | None:
    """First candidate that exists and isn't a disambiguation page."""
    resolutions = await client.resolve_titles(list(candidates))
    for candidate in candidates:
        res = resolutions.get(candidate)
        if not res or not res.exists:
            outcome = "missing"
        elif res.is_disambiguation:
            outcome = "disambiguation"
        else:
            outcome = f"-> {res.resolved_title}"
        report.article_candidates_tried.append(f"{candidate}: {outcome}")
        if res and res.exists and not res.is_disambiguation and res.resolved_title:
            return res.resolved_title
    return None


async def _clear_brand(brand: str) -> int:
    """Drop a brand's cached rows so a re-crawl replaces them instead of
    leaving stale ones behind — needed when the brand's source ARTICLE
    changes (a wrong article's rows are not rows the new one will overwrite)."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            delete(WikipediaRawArticle).where(WikipediaRawArticle.brand == brand)
        )
        await session.commit()
    return result.rowcount or 0


async def _links_for_article(
    client: WikipediaClient,
    brand: str,
    spec,
    article_title: str,
    report: BrandReport,
) -> tuple[list[sec.ModelLink] | None, list[sec.Section]]:
    """Sections -> model links for ONE article, including Phase 1 escalation
    and the index one-hop. Returns (None, []) when the article can't be fetched.

    Split out of crawl_brand so a brand whose range spans two articles runs
    each through the identical rules rather than a special case."""
    page = await client.fetch_wikitext(article_title)
    if page.status != "ok" or not page.wikitext:
        report.error = f"article {article_title!r} fetch {page.status}: {page.error}"
        report.needs_manual_review = True
        return None, []

    all_sections = sec.iter_level2_sections(page.wikitext)
    report.level2_headings += len(all_sections)

    matched = sec.find_model_sections(page.wikitext)
    links = sec.dedupe_links(
        [
            link
            for section in matched
            for link in sec.extract_model_links(section.text, spec.link_prefixes)
        ]
    )
    report.fuzzy_matched_headings.extend(s.heading for s in matched)
    report.matched_headings.extend(s.heading for s in matched)

    # ---- Phase 1 escalation (explicit trigger, plan §Phase 0) ----
    if sec.should_escalate(matched, links):
        report.escalated = True
        report.escalation_reason = (
            "zero sections matched 'modell'"
            if not matched
            else f"only {len(links)} qualifying links (< {sec.MIN_QUALIFYING_LINKS})"
        )
        headings = [s.heading for s in all_sections]
        key = section_store.fingerprint_key(brand, article_title, headings)
        cached = _SECTION_STORE.get(key)
        if cached is not None:
            chosen, reasoning = list(cached["headings"]), cached["reasoning"]
            report.llm_from_cache = True
        else:
            try:
                verdict = await classify_model_sections(brand, article_title, headings)
            except Exception as exc:
                # Transient (timeout/5xx) — a property of the run, not of the
                # headings, so it is NOT stored; the next run retries it.
                report.error = f"phase 1 classification failed: {type(exc).__name__}: {exc}"
                report.needs_manual_review = True
                return [], []
            chosen, reasoning = verdict.headings, verdict.reasoning
            # Only a NON-EMPTY verdict is persisted. "none" has been observed
            # to be non-deterministic on identical input (Cupra returned both
            # its real 5-model section and "none" across two runs), so caching
            # a "none" would freeze a brand out of coverage on one flaky call.
            # An empty answer goes to the review queue and is retried next run.
            if chosen:
                section_store.record(
                    _SECTION_STORE, key, brand, article_title, chosen, reasoning
                )

        report.llm_headings.extend(chosen)
        report.llm_reasoning = reasoning
        if not chosen:
            # Plan §Phase 1: do not retry, do not guess — review queue.
            report.needs_manual_review = True
            return [], []

        llm_sections = sec.sections_by_heading(page.wikitext, chosen)
        llm_links = sec.dedupe_links(
            [
                link
                for section in llm_sections
                for link in sec.extract_model_links(section.text, spec.link_prefixes)
            ]
        )
        # Keep whichever pass found more — an LLM section that yields nothing
        # must not throw away a working fuzzy match.
        if len(llm_links) >= len(links):
            matched, links = llm_sections, llm_links
            report.matched_headings.extend(s.heading for s in llm_sections)

    # ---- follow index articles one hop ----
    # A {{Hauptartikel}} target that isn't itself a model article is an index
    # of models (Hyundai delegates its whole passenger-car range to
    # "Personenwagen von Hyundai"). Fetch it once and harvest its
    # brand-prefixed links. One hop only — an index's index is not followed,
    # and a target that IS a model article is not re-scanned.
    index_targets = sec.dedupe_links(
        [
            link
            for section in matched
            for link in sec.extract_index_targets(section.text, spec.link_prefixes)
            # Never hop into another mapped brand's own article: Citroën's
            # model section links {{Hauptartikel|DS Automobiles}} and DS's
            # links back to Citroën, which would file each marque's models
            # under the other's brand. Both are crawled separately anyway.
            if link.title not in _OTHER_BRAND_ARTICLES[brand]
        ]
    )
    for target in index_targets:
        index_page = await client.fetch_wikitext(target.title)
        if index_page.status != "ok" or not index_page.wikitext:
            logger.warning(
                "index article %r for %s: %s", target.title, brand, index_page.error
            )
            continue
        harvested = sec.dedupe_links(
            [
                link
                for section in sec.iter_level2_sections(index_page.wikitext)
                for link in sec.extract_model_links(section.text, spec.link_prefixes)
            ]
        )
        before = len(links)
        links = sec.dedupe_links(links + harvested)
        report.index_articles_followed.append(target.title)
        report.links_from_index += len(links) - before

    return links, matched


async def crawl_brand(client: WikipediaClient, brand: str, dry_run: bool) -> BrandReport:
    started = time.monotonic()
    report = BrandReport(brand=brand)
    spec = get_brand_article(brand)

    try:
        article_title = await _resolve_brand_article(client, spec.candidates, report)
        if not article_title:
            report.error = "no brand article candidate resolved"
            report.needs_manual_review = True
            return report
        report.article_title = article_title

        # Each article is run through section-matching, Phase 1 escalation and
        # the index one-hop independently; their links are then unioned. Most
        # brands have exactly one article — extra_articles exists for a marque
        # split across two (MG).
        links: list[sec.ModelLink] = []
        matched: list[sec.Section] = []
        for source_title in [article_title, *spec.extra_articles]:
            article_links, article_sections = await _links_for_article(
                client, brand, spec, source_title, report
            )
            if article_links is None:  # fetch failed; report already updated
                if source_title == article_title:
                    return report
                continue
            report.articles_processed.append(source_title)
            links = sec.dedupe_links(links + article_links)
            matched.extend(article_sections)

        report.links_found = len(links)
        if not links:
            report.needs_manual_review = True
            return report

        # ---- resolve link titles (batched: existence + redirects) ----
        # Short-name candidates are resolved alongside the prefix-matched
        # links (same batched calls) and kept only if they redirect into a
        # brand-prefixed article — see sections.extract_link_candidates. This
        # runs AFTER the escalation decision above, so the Phase 1 trigger
        # stays exactly the mechanical rule the plan specifies.
        known = {link.key for link in links}
        rescue_candidates = [
            link
            for section in matched
            for link in sec.extract_link_candidates(section.text)
            if link.key not in known and not sec.matches_brand(link.title, spec.link_prefixes)
        ]
        rescue_candidates = sec.dedupe_links(rescue_candidates)

        resolutions = await client.resolve_titles(
            [link.title for link in links + rescue_candidates]
        )

        rescued: list[sec.ModelLink] = []
        for link in rescue_candidates:
            res = resolutions.get(link.title)
            if (
                res
                and res.exists
                and res.resolved_title
                and sec.matches_brand(res.resolved_title, spec.link_prefixes)
            ):
                rescued.append(link)
        report.links_rescued = len(rescued)
        links = sec.dedupe_links(links + rescued)
        report.links_found = len(links)

        pairs: dict[tuple[str, str], sec.ModelLink] = {}
        missing: dict[tuple[str, str], tuple[sec.ModelLink, str]] = {}
        for link in links:
            res = resolutions.get(link.title)
            if not res or not res.exists or not res.resolved_title:
                key = (link.title, link.anchor or "")
                missing.setdefault(key, (link, "title does not exist on de.wikipedia"))
                continue
            # A redirect straight to a section carries the anchor itself.
            anchor = link.anchor or sec.normalize_anchor(res.fragment)
            resolved = sec.ModelLink(res.resolved_title, anchor)
            pairs.setdefault(resolved.key, resolved)

        report.pairs = len(pairs) + len(missing)
        report.unique_articles = len({title for title, _ in pairs})
        report.sample_articles = [
            (f"{t}#{a}" if a else t) for t, a in sorted({p.key for p in pairs.values()})
        ]

        cached_pairs, cached_titles = await _cached_state(brand)
        todo = {key: link for key, link in pairs.items() if key not in cached_pairs}
        report.skipped_cached = len(pairs) - len(todo)
        report.fetch_ok += report.skipped_cached  # cached rows are ok rows

        titles_to_fetch = sorted({t for t, _ in todo} - cached_titles)
        reusable = await _load_cached_wikitext(brand, {t for t, _ in todo} & cached_titles)

        if dry_run:
            report.seconds = time.monotonic() - started
            return report

        fetched = {}
        if titles_to_fetch:
            results = await asyncio.gather(
                *(client.fetch_wikitext(t) for t in titles_to_fetch)
            )
            fetched = {r.title: r for r in results}

        now = datetime.now(UTC)
        rows: list[dict] = []
        for (title, anchor_key), link in todo.items():
            result = fetched.get(title)
            if result is None and title in reusable:
                status, wikitext, error = WikipediaFetchStatus.OK, reusable[title], None
            elif result is None:
                status, wikitext, error = WikipediaFetchStatus.ERROR, None, "no fetch result"
            elif result.status == "ok":
                status, wikitext, error = WikipediaFetchStatus.OK, result.wikitext, None
            elif result.status == "not_found":
                status, wikitext, error = WikipediaFetchStatus.NOT_FOUND, None, result.error
            else:
                status, wikitext, error = WikipediaFetchStatus.ERROR, None, result.error
            rows.append(
                {
                    "brand": brand,
                    "article_title": title,
                    "anchor": link.anchor,
                    "anchor_key": anchor_key,
                    "wikitext": wikitext,
                    "fetch_status": status,
                    "error_message": (error or "")[:1024] or None,
                    "fetched_at": now,
                }
            )

        for (title, anchor_key), (link, why) in missing.items():
            rows.append(
                {
                    "brand": brand,
                    "article_title": title,
                    "anchor": link.anchor,
                    "anchor_key": anchor_key,
                    "wikitext": None,
                    "fetch_status": WikipediaFetchStatus.NOT_FOUND,
                    "error_message": why,
                    "fetched_at": now,
                }
            )

        for row in rows:
            if row["fetch_status"] == WikipediaFetchStatus.OK:
                report.fetch_ok += 1
            elif row["fetch_status"] == WikipediaFetchStatus.NOT_FOUND:
                report.fetch_not_found += 1
            else:
                report.fetch_error += 1

        await _upsert_rows(rows)

    except Exception as exc:  # one brand's failure must not kill the run
        logger.exception("crawl failed for %s", brand)
        report.error = f"{type(exc).__name__}: {exc}"
        report.needs_manual_review = True

    report.seconds = time.monotonic() - started
    return report


def _print_brand(report: BrandReport) -> None:
    print(f"\n=== {report.brand} ({report.catalogue_rows} catalogue rows) ===")
    print(f"  article: {report.article_title}")
    print(
        f"  level-2 headings: {report.level2_headings}; "
        f"fuzzy match: {report.fuzzy_matched_headings or 'none'}"
    )
    if report.matched_headings != report.fuzzy_matched_headings:
        print(f"  sections used: {report.matched_headings}")
    extra = []
    if report.links_rescued:
        extra.append(f"+{report.links_rescued} via redirect")
    if report.links_from_index:
        extra.append(f"+{report.links_from_index} from {report.index_articles_followed}")
    suffix = f" ({', '.join(extra)})" if extra else ""
    print(f"  qualifying links: {report.links_found}{suffix}")
    if report.escalated:
        print(f"  ESCALATED to Phase 1 — {report.escalation_reason}")
        print(f"    LLM headings: {report.llm_headings}")
        print(f"    LLM reasoning: {report.llm_reasoning}")
    print(
        f"  pairs: {report.pairs} over {report.unique_articles} unique articles "
        f"(skipped cached: {report.skipped_cached})"
    )
    print(
        f"  fetch: ok={report.fetch_ok} not_found={report.fetch_not_found} "
        f"error={report.fetch_error}  [{report.seconds:.1f}s]"
    )
    if report.needs_manual_review:
        print("  !! FLAGGED FOR MANUAL REVIEW")
    if report.error:
        print(f"  error: {report.error}")


async def run(
    brands: list[str], dry_run: bool, report_path: Path | None, refresh: bool = False
) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    # One INFO line per request from httpx would bury the per-brand report in a
    # crawl this size; warnings (backoffs, failures) still surface.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    await _ensure_schema()

    counts = await _catalogue_brand_counts(brands)
    unknown = [b for b in brands if b not in counts]
    if unknown:
        raise SystemExit(
            f"These brands have no rows in the catalogue table: {unknown}. "
            f"Crawling a brand the catalogue doesn't have would produce data "
            f"nothing can ever match against."
        )
    print("Scope confirmed against catalogue.brand:")
    for brand in brands:
        print(f"  {brand:<16} {counts[brand]:>6} rows")

    started = time.monotonic()
    reports: list[BrandReport] = []
    async with WikipediaClient() as client:
        auth = await client.login()
        print(f"\nAuth: {auth}")
        print(f"User-Agent: {client._client.headers['user-agent']}")
        print(
            f"Concurrency: {client.concurrency}; "
            f"per-worker delay: {client.per_worker_delay}s\n"
        )
        for brand in brands:
            if refresh and not dry_run:
                cleared = await _clear_brand(brand)
                print(f"\n--refresh: cleared {cleared} cached row(s) for {brand}")
            report = await crawl_brand(client, brand, dry_run)
            report.catalogue_rows = counts[brand]
            reports.append(report)
            _print_brand(report)
            # Persist incrementally so an interrupted run keeps what it learned.
            section_store.save(_SECTION_STORE)
        stats = client.stats

    wall = time.monotonic() - started
    print("\n" + "=" * 60)
    print(f"Brands: {len(reports)}   wall-clock: {wall / 60:.1f} min")
    print(
        f"Requests: {stats.requests}  429s: {stats.http_429}  "
        f"retries: {stats.retries}  transport/API errors: {stats.errors}"
    )
    print(
        f"Rows: ok={sum(r.fetch_ok for r in reports)} "
        f"not_found={sum(r.fetch_not_found for r in reports)} "
        f"error={sum(r.fetch_error for r in reports)}"
    )
    escalated = [r.brand for r in reports if r.escalated]
    review = [r.brand for r in reports if r.needs_manual_review]
    print(f"Escalated to Phase 1: {escalated or 'none'}")
    print(f"Manual review queue: {review or 'none'}")

    if report_path:
        payload = {
            "generated_at": datetime.now(UTC).isoformat(),
            "dry_run": dry_run,
            "wall_clock_seconds": wall,
            "requests": stats.requests,
            "http_429": stats.http_429,
            "retries": stats.retries,
            "transport_errors": stats.errors,
            "brands": [asdict(r) for r in reports],
        }
        report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
        print(f"Report written to {report_path}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Phase 0/1 de.wikipedia crawl: cache model-article wikitext per brand."
    )
    parser.add_argument(
        "--brand", action="append", dest="brands", metavar="BRAND",
        help="Catalogue brand to crawl (repeatable). Default: the 10 in-scope brands.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Resolve and report, write nothing")
    parser.add_argument("--report", type=Path, help="Write a JSON run report here")
    parser.add_argument(
        "--refresh", action="store_true",
        help="Delete each named brand's cached rows before crawling it. Needed "
             "when the brand's source article mapping changed — resumability "
             "would otherwise keep the old article's rows forever.",
    )
    args = parser.parse_args()
    asyncio.run(
        run(args.brands or list(PHASE_0_BRANDS), args.dry_run, args.report, args.refresh)
    )


if __name__ == "__main__":
    main()
