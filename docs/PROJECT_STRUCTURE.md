# Project structure & status

Where things actually stand. For *how* the pieces work and why they're shaped
that way, read [`CLAUDE.md`](../CLAUDE.md) — it's the architecture doc and it's
kept current. This file is the shorter "what exists, what's live, what's
deferred" view.

---

## Documentation map

| Doc | What it is |
|---|---|
| [`README.md`](../README.md) | Public overview, quick start, API examples |
| [`CLAUDE.md`](../CLAUDE.md) | Architecture and conventions — the deep reference |
| [`DEPLOYMENT.md`](../DEPLOYMENT.md) | VPS + Docker Compose deploy guide |
| [`MOBILE_DE_APIFY_SPEC.md`](MOBILE_DE_APIFY_SPEC.md) | Design record for the shipped mobile.de/Apify path |
| [`MONETIZATION_SPEC.md`](MONETIZATION_SPEC.md) | carVertical (live) + AdSense (deferred) |
| [`INGEST_REWORK_PLAN.md`](INGEST_REWORK_PLAN.md) | Ingestion rework — code done, **one paid rebuild still pending** |
| [`ORIGINAL_PLAN.md`](ORIGINAL_PLAN.md) | Historical: the original build-order decision record |

---

## Layout

```
app/
  ppmv/                  # Tax engine — DONE
    engine.py              # calculate_ppmv(), pure function, no I/O
    tables.py              # NEDC/WLTP brackets + depreciation table (NN 156/22, NN 1/17)
    schemas.py             # PPMVRequest/Response, FuelType, CO2Standard
    exceptions.py          # InvalidCO2Value, InvalidPriceValue, ...
    router.py              # POST /ppmv/calculate — specs in, tax out

  calculate/             # The product endpoint — DONE
    router.py              # POST /calculate — scrape + catalogue match + tax
    schemas.py             # CalculateRequest/Response, ParsedFields, Literal aliases

  scraping/              # Single-URL on-demand scraping — DONE, 4 sites
    extractors/            # autobid_de, autoscout24, njuskalo (+ base protocol)
    fetchers/
      apify_mobile_de.py   # mobile.de via Apify actor — no local extractor
    mobile_de_guard.py     # rate limit + Turnstile + budget guard stack
    mobile_de_service.py   # cache-first fetch, ApifyBudgetExceeded
    site_registry.py       # EXTRACTORS / detect_site() / SITE_TO_SCRAPE_SITE
    engines.py             # Per-site fetch engine (httpx | chromium | apify)
    parsing.py             # parse_listing_date(), parse_number() — locale-safe
    persistence.py         # ScrapeRun/Listing writes for every scrape attempt
    schemas.py             # ListingData — the contract every extractor returns
    router.py              # POST /scrape/listing

  catalogue/             # Matching (request path) + ingestion support
    matching.py            # find_match()/rank_candidates() — fuzzy listing→row
    brands.py              # canonical brand vocabulary + snap_brand()
    display.py             # format_variant_display()
    canonical_schema.py    # ColumnMapping, CanonicalRow, apply_mapping()
    llm_mapper.py          # OpenRouter column mapping, one call per header layout
    mapping_store.py       # committed mapping cache (column_mappings.json)
    router.py              # GET /catalogue/brands|models|search

  data/catalogues/       # Offline ingestion CLI — not in the request path
    ingest.py              # concurrent manifest-driven ingest
    parse_date.py          # filename → valid_from
    download_catalogues.py, backfill_match_key.py
    manifest.jsonl         # 2163 source files across 36 brand folders
    <brand-slug>/          # downloaded customs Excel files

  core/                  # config.py, exceptions.py, limits.py, ip.py, turnstile.py
  db/                    # models.py (Catalogue, ScrapeRun, Listing,
                         #  ListingCache, ApifyEvent), session.py
  profitability/         # DEFERRED — empty package (__init__.py only)
  main.py                # app factory, router registration, create_all on startup

frontend/                # Next.js — PPMV calculator live, Profitability is a shell
  app/                     # page.tsx (calculator), profitability/, layout, seo routes
  components/              # 13 components (UrlInputForm, VehicleForm,
                           #  PPMVBreakdownCard, CandidatesList, CarVerticalCard, ...)
  lib/                     # api.ts (the only backend caller), types.ts, format.ts,
                           #  fuel.ts, vehicleForm.ts

tests/                   # 243 tests, ~0.5s, no DB needed except where marked
scripts/                 # one-off CLIs: ingest_catalogue, verify_enum_schema,
                         #  migrate_mapping_cache, migrate_apify_events_ip_hash
```

---

## What's live

| Endpoint | Does |
|---|---|
| `POST /ppmv/calculate` | Specs in, tax breakdown out. No DB, no scraping. |
| `POST /calculate` | **The product.** URL in, PPMV out — scrapes, fills missing CO2 from the catalogue, runs the engine. Degrades to a prefilled manual form instead of erroring. |
| `POST /scrape/listing` | URL in, normalized `ListingData` out. All 4 sites. |
| `GET /catalogue/brands` · `/models` · `/search` | Backs the frontend's manual "search the database" flow. |

All four scraping sites are wired into `/calculate`, **mobile.de included** —
it goes through the Apify guard stack rather than a local extractor.

---

## Tests

243 tests, all pure-function or stubbed; the suite runs in about half a second.

| File | Covers |
|---|---|
| `test_ppmv_engine.py` | Tax engine incl. the official Audi A5 case (exactly 3,475.50 EUR) |
| `test_apply_mapping.py` | Ingestion column mapping, no LLM calls |
| `test_matching.py` | `rank_candidates()` scoring and disambiguators |
| `test_calculate_pipeline.py` | `/calculate` decision logic — CO2 sourcing, degradation paths |
| `test_scraper_locale.py` | Same listing must parse identically across site locales |
| `test_apify_mobile_de.py`, `test_autobid_de_extractor.py` | Fetcher/extractor parsing |
| `test_display.py`, `test_parse_date.py` | Formatting and filename-date helpers |
| `test_scraping_persistence.py`, `test_scraping_integration.py` | Partly `@pytest.mark.integration` (needs DB) |

```bash
uv run pytest tests/ -m "not integration" -q   # what CI runs
```

CI ([`.github/workflows/ci.yml`](../.github/workflows/ci.yml)) runs ruff +
pytest + `tsc --noEmit` + eslint, and
[`deploy.yml`](../.github/workflows/deploy.yml) requires it before shipping.

---

## Catalogue ingestion

Pipeline is complete and has been run; 36 brand folders and a 2163-file
manifest are on disk. Per-brand row counts live in the database, not in this
file — check them directly rather than trusting a number written here:

```bash
docker compose exec db psql -U "$POSTGRES_USER" "$POSTGRES_DB" \
  -c "select brand, count(*) from catalogue group by brand order by 2 desc;"
```

To ingest or re-ingest:

```bash
python -m app.data.catalogues.ingest --brand <slug> --concurrency 24
```

Drop `--brand` for everything. `INGEST_REWORK_PLAN.md` still has one pending
paid rebuild (`--fresh`) plus its validation steps.

---

## Deferred

- **Profitability calculator** — `app/profitability/` is an empty package and
  `frontend/app/profitability/` is a shell. Will consume `catalogue/matching.py`
  the same way `/calculate` does.
- **Sweep scraping** (nightly/weekly bulk) — njuškalo and mobile.de hard-block
  sweep patterns; needs an Apify cost decision that hasn't been made.
- **AdSense** — gated on content pages and traffic, see `MONETIZATION_SPEC.md`.

---

## Known gaps

- **No migration tool.** `Base.metadata.create_all` only adds missing tables;
  it never alters an existing one. A breaking change to an existing table has
  no defined process. Fine while the schema is stable, needs a real answer
  before the first one.
- `find_match()` fetches all rows for a brand on every call — no SQL-level
  limit. Fine at current per-brand counts; revisit if a brand grows much larger.
- `_upsert_rows` batches at 500; no manifest file gets close, so the
  batch boundary is untested in practice.
