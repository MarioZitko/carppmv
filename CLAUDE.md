# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Croatian car-import PPMV tax calculator. A user pastes a car-listing URL
(mobile.de, AutoScout24, njuškalo, autobid.de); the backend scrapes it,
fills in missing spec fields (mainly CO2) from an ingested catalogue of
official Croatian customs price lists, and runs the official PPMV tax
formula to return an itemized breakdown. FastAPI backend + Next.js
frontend, Postgres for catalogue/listing storage.

## Commands

```bash
# Install deps (requires uv for backend, npm for frontend)
uv sync
cd frontend && npm install

# One-command local dev: Postgres (docker) + backend (:8000) + frontend (:3000)
./dev.sh

# Or run pieces individually:
uv run uvicorn app.main:app --reload --port 8000
cd frontend && npm run dev

# Tests (pure-function unit tests, no DB needed for most)
uv run pytest tests/ -v
uv run pytest tests/test_ppmv_engine.py -v              # single file
uv run pytest tests/test_matching.py -k test_name -v     # single test
uv run pytest tests/ -m "not integration"                 # skip DB/LLM-dependent tests

# Lint
uv run ruff check app/ tests/
cd frontend && npm run lint
```

Python ≥ 3.12, managed with `uv`. `POST /ppmv/calculate` and most unit
tests need no database. `DATABASE_URL` is only required for catalogue
matching, listing persistence, and the mobile.de/Apify cache path — see
`.env.example`.

Tests marked `@pytest.mark.integration` require a real DB and/or
`OPENROUTER_API_KEY`; they're skipped in CI-style runs.

## Architecture

### Request flow: `POST /calculate` is the product

`app/calculate/router.py` is the single endpoint the frontend's landing
page calls. It's a pipeline, not a thin CRUD handler:

1. **Detect site** from the URL domain (`SITE_ENGINE_MAP` in
   `app/scraping/engines.py`) and dispatch to that site's extractor.
2. **Scrape** → each extractor (`app/scraping/extractors/*.py`) returns a
   normalized `ListingData` (`app/scraping/schemas.py`) regardless of
   source quirks. mobile.de is special-cased (see below).
3. **Catalogue match** (`app/catalogue/matching.py::find_match`) always
   runs when the listing's brand is known. It fills CO2 when the listing
   doesn't expose it, and *always* returns ranked candidates so the
   frontend can let the user override the auto-pick with a different
   priced row.
4. **Tax calculation** (`app/ppmv/engine.py::calculate_ppmv`) — pure
   function, no I/O.
5. Return `CalculateResponse` with the breakdown, parsed fields,
   `co2_source` (`scraped` | `catalogue` | `manual_required`), and
   `match_status`/`candidates` so the frontend can show a confidence UI
   instead of a silent black box.

`POST /ppmv/calculate` (app/ppmv/router.py) bypasses scraping/catalogue
entirely — specs in, tax out — and is what the manual-entry form and the
Audi A5 regression test use.

`POST /scrape/listing` and `GET /catalogue/*` expose the scraping and
catalogue-matching pieces standalone (used by the frontend's manual
"search the database" flow, which reuses `find_match` the same way
`/calculate` does).

### The PPMV tax engine (`app/ppmv/`)

`engine.py::calculate_ppmv` is deliberately pure (no FastAPI, no DB) so
the official Audi A5 regression case from carina.gov.hr (expected output
exactly 3,475.50 EUR) is a plain function call. `tables.py` hardcodes the
NEDC/WLTP value and eco brackets and the depreciation table, transcribed
directly from the Croatian Uredba (NN 156/22) and Pravilnik (NN 1/17 et
al.) — comments in that file cite the exact legal source and note a
naming collision (the Uredba's own "Tablica 1" is a different table from
the Pravilnik's "Tablica 1").

Key domain rules baked into `engine.py` (see its docstrings for the
"why," not just the "what"):
- NEDC tables apply to vehicles first registered before 2021-01-01, WLTP
  from then on (`WLTP_CUTOVER_DATE`).
- Depreciation (Tablica 1) applies only to used vehicles; new vehicles
  use factor 1.0.
- Reduction order: electric is fully exempt (returns immediately) →
  plug-in hybrid EAER-city-range reduction → seat-count reduction (8
  seats → ×0.50, 9+ → ×0.25) → camper → ×0.15. All multiply together,
  applied to `as_new_total` *before* depreciation.
- Month-counting between first registration and declaration date follows
  a specific "day-of-month completion" rule (Pravilnik čl. 9 st. 4), not
  naive calendar-month subtraction — see `_months_between`'s docstring
  before touching it.

Domain errors (`InvalidCO2Value`, `InvalidPriceValue`,
`UnsupportedVehicleCategory`) are raised by the engine and never caught
in `ppmv/router.py` — they propagate to handlers registered in
`app/core/exceptions.py::register_exception_handlers`, which is the only
place HTTP status mapping happens. Don't add try/except in routers for
these; that duplicates the handler.

### Scraping (`app/scraping/`)

One extractor per site, all implementing the `Extractor` protocol
(`extractors/base.py`) and returning `ListingData`. Each extractor's public
`extract()` wraps an internal `_extract()` in a catch-all that re-raises
anything unexpected as `ScrapingError` — so a Playwright/httpx timeout or
transport error still gets the clean 502 mapping instead of leaking as an
unhandled 500. Fetch engine is per-site (`engines.py`), not hardcoded,
because sites need genuinely different approaches:

| Site | Engine | Why |
|---|---|---|
| autobid.de | `httpx` + BeautifulSoup | Server-rendered HTML, no JS needed. CO2 never exposed pre-login. |
| njuškalo | Playwright Chromium | JS-rendered |
| AutoScout24 | Playwright Chromium | Parses the `__NEXT_DATA__` JSON blob, not CSS selectors (CSS classes are hashed/unstable across deploys) |
| mobile.de | **Apify actor**, not direct | Akamai Bot Manager blocks direct Chromium/Firefox fetches outright |

**mobile.de is architecturally different from the other three.** It
doesn't go through a local `Extractor` — it's fetched via a third-party
Apify actor (`app/scraping/fetchers/apify_mobile_de.py`) behind a guard
stack that both `/calculate` and `/scrape/listing` share
(`app/scraping/mobile_de_guard.py` → `mobile_de_service.py`):

1. **Rate limit** (`app/core/limits.py`) — per-IP-hash hourly/daily caps,
   tracked via `ApifyEvent` rows (IP is hashed with a salt,
   `app/core/ip.py`; raw IPs are never persisted).
2. **Turnstile bot-check** (`app/core/turnstile.py`) — disabled
   automatically in dev when `TURNSTILE_SECRET_KEY` is unset.
3. **Cache-first fetch** (`ListingCache` table, TTL from
   `listing_cache_ttl_hours`) — avoids paying Apify twice for the same
   listing.
4. **Daily budget cap** (`daily_apify_budget_calls`) — when exhausted,
   `/calculate` degrades gracefully to a manual-entry response instead
   of erroring (`ApifyBudgetExceeded`).

Every outcome (cache hit, paid call, rate-limited, bot-rejected,
cap-reached, failed) is logged as an `ApifyEvent` row — this is the
observability/cost-accounting trail, not just a rate-limit counter.

Sweep/bulk scraping is explicitly out of scope — njuškalo and mobile.de
block automated sweeps with bot detection that would need paid Apify
actors, deferred as a cost decision.

### Catalogue matching (`app/catalogue/matching.py`)

This solves a *different* problem than ingestion. A car-listing site
never exposes the customs internal type code (VW `MODEL KOD`, BMW `KOD
MODELA`, Porsche's bare `model`, etc.) — only free text like "BMW 320d
xDrive M Sport". So matching a listing to a `Catalogue` row is fuzzy text
reconciliation on brand+model+variant, not a key join. Two tiers,
deliberately no embeddings/LLM here (LLM stays confined to ingestion's
column mapping):

1. **Exact**: normalize listing text into a `match_key`
   (`build_match_key`) and hit the indexed `Catalogue.match_key` column.
2. **Fuzzy**: hard-filter by brand (and fuel when derivable), score
   remaining rows with `rapidfuzz.token_set_ratio` on the normalized
   text, then adjust with several purpose-built disambiguators — power_kw
   proximity, CO2 proximity, registration-year vs. catalogue validity
   period, model-field-only scoring (catches e.g. "A3" vs "Q3" scoring
   falsely high on the full blob), fuel/gearbox/body-style mismatch
   penalties, and a BMW-specific leading-digit-series hard override
   (single-digit series differences like "120i" vs "520i" are never a
   rounding/trim variation).

Decision policy is **"confirm unless certain"**: auto-accept only when
the top score clears `ACCEPT_SCORE` *and* no differently-priced candidate
sits within `ACCEPT_MARGIN` of it. Otherwise the caller gets ranked
candidates for the user to pick from — a wrong auto-picked price/CO2
silently corrupts the whole tax result, whereas an unfilled field is
just something the user types in.

`rank_candidates()` is pure and DB-free (unit-tested directly in
`tests/test_matching.py`); `find_match()` is the thin async layer that
fetches brand-filtered rows and delegates to it. Read the extensive
inline comments in this file before touching any tuning constant
(`ACCEPT_SCORE`, `POWER_TOLERANCE_KW`, etc.) — most encode a specific
real-world regression that was fixed by that exact value.

`app/catalogue/brands.py` is the single source of truth for canonical
brand spelling, shared by ingestion (fixing source typos like
"Marcedes-Benz"), the autobid.de URL-slug parser, and matching's brand
normalization — all three would drift apart without it.

### Catalogue ingestion (`app/catalogue/canonical_schema.py`,
`llm_mapper.py`, `app/data/catalogues/ingest.py`)

Offline/CLI pipeline, not part of the request-serving path. Ingests
official Croatian customs brand Excel files (one folder per importer
group — some groups bundle several marques, see `FOLDER_BRANDS` in
`brands.py`) into the `Catalogue` table.

- **Column mapping is LLM-assisted, once per unique header layout, never
  per row.** `llm_mapper.py` calls OpenRouter (DeepSeek V4 Flash by
  default) with a strict enum-constrained JSON schema — the model can
  only return a column name that literally exists in that sheet's header
  row, and a post-hoc guard rejects any hallucinated non-null column
  anyway. The LLM never sees or transforms bulk row data.
- `canonical_schema.py::apply_mapping` turns a `ColumnMapping` +raw rows
  into `CanonicalRow`s; this is what both ingestion paths (the main
  pipeline and the one-off `scripts/ingest_catalogue.py`) share, and
  what `tests/test_apply_mapping.py` exercises without any LLM calls.
- `ingest.py` runs concurrently (`--concurrency`, default 24), caches
  LLM mappings per header layout (success *and* failure, so a bad layout
  isn't retried every file), sorts batch upserts by the unique-constraint
  columns before insert (Postgres deadlock avoidance under concurrent
  writes), and filters bad rows individually rather than failing an
  entire file's batch on one row.
- Run with `python -m app.data.catalogues.ingest --brand <slug>
  --concurrency 24` (omit `--brand` for everything). See
  `docs/PROJECT_STRUCTURE.md` for current ingestion status per brand —
  it tracks which of the 38 brand folders are actually loaded, since
  this is an ongoing, partially-completed effort, not a one-time script.

### Database (`app/db/models.py`)

- `Catalogue` — one priced variant for one validity period, unique on
  `(brand, model, variant, valid_from)`. `match_key` is the precomputed
  normalized text matching indexes against.
- `ScrapeRun` / `Listing` — observability for scraper executions and
  persisted listings (Apify billing is per-result, so knowing what a run
  actually produced matters). Written via `app/scraping/persistence.py`
  (`record_scrape_run`/`finish_scrape_run`/`record_scrape_outcome`), called
  from both `POST /calculate` and `POST /scrape/listing` for every scrape
  attempt (success and failure) across all four sites. Persistence failures
  here are logged and swallowed — this is observability, not the product
  path, and must never break the actual response.
- `ListingCache` — TTL cache keyed by `"{site}:{external_id}"`, currently
  used only by the mobile.de/Apify path.
- `ApifyEvent` — one row per mobile.de request outcome, for rate-limit
  accounting and cost tracking.

Schema is created via `Base.metadata.create_all` on app startup
(`app/main.py`) — this only adds missing tables, it never alters an
existing table's columns/constraints. There is no migration tool
(Alembic or similar) yet; a breaking schema change to an existing table
currently has no defined process.

Site detection (`detect_site`) and the extractor registry (`EXTRACTORS`) live
in `app/scraping/site_registry.py`, shared by `calculate/router.py` and
`scraping/router.py` — don't reintroduce a second copy in either router.

### Config (`app/core/config.py`)

Single `Settings` (pydantic-settings, `.env`-backed, cached via
`lru_cache`). Notable: most settings have safe dev defaults (Turnstile
verification is a no-op when `TURNSTILE_SECRET_KEY` is unset; the
OpenRouter key is only required when actually running ingestion, not for
normal API operation) — don't add hard-required validation that would
break running the calculator without the ingestion/scraping-abuse
subsystems configured.

### Frontend (`frontend/`)

Next.js app. `app/page.tsx` is the PPMV calculator (the live product);
`app/profitability/page.tsx` is a shell with no backend yet
(`app/profitability/` on the backend is an empty stub — deferred, not
broken). `lib/api.ts` is the only place that calls the backend — thin
fetch wrappers per endpoint, typed via `lib/types.ts` (hand-kept mirrors
of the Pydantic schemas, not generated).

## Cross-cutting conventions worth knowing before editing

- **PPMV engine stays pure.** No I/O, no FastAPI imports in `engine.py`
  or `tables.py` — this is what keeps the regression test a plain
  function call.
- **Domain exceptions, not HTTP exceptions, in business logic.** Routers
  don't catch `PPMVError`/`ScrapingError`/etc.; `app/core/exceptions.py`
  is the only HTTP-mapping layer.
- **Raw client IPs are never persisted or logged** — only
  `sha256(salt + ip)` via `app/core/ip.py::client_ip_hash`.
- **Matching's "confirm unless certain" policy is intentional product
  behavior**, not a missing feature — resist the urge to "just always
  auto-pick the top match."
- **`normalize_text`/`build_match_key` in `matching.py` must stay
  deterministic and side-effect-free** — the same function normalizes
  both the stored `match_key` at ingestion time and the query at lookup
  time; if they ever diverge, matching silently breaks for every
  already-ingested row.
