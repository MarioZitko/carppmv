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
   doesn't expose it *and* the auto-matched row actually carries one —
   nothing in the accept rule (score + price agreement) requires a CO2
   value, so `matched.co2_g_km is None` is checked explicitly rather than
   inferred from AUTO_MATCHED. It *always* returns ranked candidates so
   the frontend can let the user override the auto-pick with a different
   priced row.
3b. **Wikipedia CO2 hint** (`app/wikipedia/co2_lookup.py`) — last resort,
   reached only when steps 2 and 3 both produced no CO2. Fills
   `wikipedia_hint`, never `co2_g_km`; see the Phase 5 notes below.
4. **Tax calculation** (`app/ppmv/engine.py::calculate_ppmv`) — pure
   function, no I/O.
5. Return `CalculateResponse` with the breakdown, parsed fields,
   `co2_source` (`scraped` | `catalogue` | `manual_required`),
   `match_status`/`candidates`, and `wikipedia_hint`.

   Note what the frontend actually reads: **`co2_source`, `confidence` and
   `match_status` are declared in `frontend/lib/types.ts` and used
   nowhere**. Confidence reaches the user only through `CandidatesList`'s
   per-row score badge and, for the last tier, `Co2HintNote`. Don't assume
   a `match_status`-driven UI exists — it doesn't.

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
  --concurrency 24` (omit `--brand` for everything). Ingestion status is
  a property of the database, not of a doc — query per-brand row counts
  directly (`docs/PROJECT_STRUCTURE.md` has the command) rather than
  trusting a checked-in list, which drifts the moment a brand is loaded.

### Wikipedia CO2 pipeline (`app/wikipedia/`)

Offline/batch pipeline (like catalogue ingestion — never in the `/calculate`
request path) that fills the CO2 gap for vehicles the catalogue doesn't cover.
Full design in `docs/WIKIPEDIA_CO2_PLAN.md`; **all five phases are
implemented**. Three CLIs: `crawl` (Phase 0/1, fetches wikitext), `extract`
(Phase 2/3, turns it into validated engine rows) and `upsert` (Phase 4, loads
them into Postgres). Phase 5 is a library function, not a CLI — and, since
the `/calculate` wiring, the one part of this pipeline that runs inside a
request.

**Phase 2 still writes to `data/wikipedia/`, not Postgres** — Phase 4 reads
that artifact. The Phase 2.5 spot-check gate in front of the upsert was
reviewed and cleared on 2026-09-02; it remains a *process* gate, so a future
re-extraction that changes the corpus needs the spot-check read again before
re-upserting. A wrongly extracted CO2 range is exactly the silent-corruption
case the gate exists for.

`python -m app.wikipedia.crawl [--brand X] [--dry-run] [--refresh] [--report out.json]`
crawls de.wikipedia per brand — brand article → model-list section → model
article wikitext, cached in `WikipediaRawArticle`.

- `client.py` — the Wikimedia policy layer: required descriptive User-Agent
  with contact (a default library UA lands in a stricter rate-limit tier),
  bot-password login (`action=clientlogin` is refused for bot passwords, so
  `action=login` is the working path; the session is verified via
  `meta=userinfo`), **hard concurrency ceiling of 3**, ~1s per-worker
  throttle, 429 backoff. Existence/redirect questions batch 50 titles per
  request; `action=parse&prop=wikitext` does not batch.
- `sections.py` — pure, DB-free, unit-tested. Section matching is the fuzzy
  substring `"modell"`, not a whitelist (a whitelist missed Volvo's real
  heading). A `#anchor` link means the generation lives in a *section* of a
  shared article, so `(article_title, anchor)` is the stored unit.
- `brand_articles.py` — brand → candidate de.wikipedia articles, plus the
  crawl scope (`PHASE_0_BRANDS` = all catalogue brands bar `EXCLUDED_BRANDS`).
  Candidates, not one title, because the bare marque name often isn't the
  marque article ("Fiat" is a disambiguation, "Mercedes-Benz" is a
  vehicle-type routing page, "BMW" is the corporate article, "MG Rover Group"
  redirects to *Rover*). `extra_articles` covers a marque split across two
  articles (MG: modern Chinese + historical British).
- `section_store.py` — persisted Phase 1 verdicts
  (`section_classifications.json`), mirroring `catalogue/mapping_store.py`.
  The LLM proved non-deterministic at temperature 0, so without this the
  review queue changes between runs. Only non-empty verdicts are cached.
- `llm_sections.py` — Phase 1 fallback only, triggered by the plan's explicit
  rule (zero matched sections, or fewer than 5 qualifying links). Same
  enum-constrained-schema + post-hoc guard pattern as `catalogue/llm_mapper.py`.

Phase 2/3 (`python -m app.wikipedia.extract [--brand X] [--dry-run]
[--concurrency N] [--limit N] [--sample N] [--report out.json]`):

- `tables.py` — pure, DB-free, unit-tested. Picks which tables get an LLM call:
  scopes to the anchor's section, then **prefilters on a CO2 token per table**
  (only ~30% of the corpus's 3,942 tables carry one; the rest are spec tables
  with no emissions row, or crashtest/sales tables). The filter is per table,
  never per article — CO2 often sits in one table of several.
- `llm_tables.py` — **one call per table**, never per article. The prompt makes
  the model name the table's ORIENTATION before extracting, because the corpus
  contains both shapes in bulk: normal (one row per variant) and transposed
  (one column per variant, attributes down the left). Returns an array of
  variants, since one table yields many. It is never asked to estimate a CO2
  value — null is a correct answer, and the prompt says so explicitly.
- `extraction_store.py` — the determinism cache, mirroring `section_store.py`.
  **Only results that found a CO2 value are cached**; an all-null result is
  re-asked next run, because caching a flaky false-null would be permanent
  silent coverage loss on a table that really does carry emissions data.
- `validation.py` — Phase 3, pure and mechanical. Failing rows go to a review
  queue, never silently dropped or silently inserted. Null CO2 passes cleanly
  (it is an expected outcome, not an error); a bare `YYYY` production period is
  accepted, because demanding `YYYY-MM` would make the model invent months.
- `extract.py` — the orchestrator, plus the Phase 2.5 gate artifacts: a
  brand-stratified spot-check sample, an orientation cross-check against
  `tables.guess_orientation`, and a regex tripwire flagging any table that
  returned no CO2 while its wikitext contains `\d{2,3} g/km`.

`guess_orientation` is a cross-check on the model, never an override. Its rule
is content-based — which axis carries the German attribute vocabulary
(Bauzeitraum/Hubraum/Leistung…) — because both markup shortcuts were tried and
failed: `!` header cells alone miss the very common bold-data-cell
"Kenngrößen" style, and "first cell is bold" fires on normal tables that bold
their variant name.

Phase 4 (`python -m app.wikipedia.upsert [--brand X] [--dry-run]
[--report out.json]`) — reads the extraction store, cross-checks the brand,
corrects CO2 ordering, re-runs Phase 3 validation and batch-upserts into
`wikipedia_engine_data`. Three things in it are load-bearing:

- `brand_check.py` — **the crawl brand is not authoritative.** Phase 0 files an
  article under whichever brand article linked to it, and brand articles link
  to other marques' rebadges: 28 Opel Zafira variants under Subaru (the
  Traviq), Lexus ES/GS/IS under Toyota, Dacia Logan under Nissan. The title's
  longest marque prefix is read through `catalogue/brands.py` (reused, not
  reimplemented — a second brand vocabulary would drift) and the row is either
  confirmed, re-filed under the marque the title names, or — when no marque is
  recognisable, as in the four-marque `Eurovan (PSA/Fiat)` article — held out
  of every brand's pool. `crawl_brand` is kept so a re-filing is auditable.
- The unique key is `(source_fingerprint, variant_index)`, deliberately not the
  spec-shaped key the plan named. Spec columns cannot separate a table's manual
  and automatic rows — the Phase 2 schema has no gearbox field — so that key
  silently collapsed 757 rows, 409 of them with conflicting CO2.
- `co2_min > co2_max` is swapped *before* validation and flagged in
  `source_order_corrected`, so the fix is traceable rather than silent — but a
  swap that yields an implausibly wide range is *disbelieved* and the row goes
  to review instead. `Audi A3 8V / 30 g-tron`'s wikitext really does read
  "114–12 g/km" (a dropped digit in the Wikipedia source, not an extraction
  bug); swapping it would manufacture a 12–114 range out of a typo. Width alone
  is not an error signal — real rows span a whole production era — only width
  *plus* needing a swap is. `prune_review_rows` then deletes anything the table
  already held that a later run rules ineligible, which an upsert alone cannot
  do.

Phase 5 (`co2_lookup.resolve_co2_from_wikipedia`) shares **no tuning
constants** with `catalogue/matching.py` — that matcher reconciles free-text
variant blobs, this one matches exact engine numbers. `rank_candidates()` is
pure and DB-free; the async wrapper takes an optional session, and
`/calculate` passes the request's own so no second `AsyncSessionLocal` is
opened mid-request. Read the
constants' comments before touching them; each records the wrong answer it was
introduced to stop. Two are easy to break by "simplifying":

- **Near-ties are merged into a wider range, but only within one article.**
  Merging is correct for a range-valued answer; across articles it produced a
  confident 121-149 g/km for a BMW X3 by unioning an X1, X2, X3 and X4 that
  all share the "xDrive20d" badge and 140 kW.
- **The designator guard** (A4 vs A5, C 220 d vs E 220 d) fires only on
  designators the candidate pool actually uses, because BMW's X-range articles
  are titled by chassis code and "X3" appears nowhere in them.

**The picker (`app/wikipedia/browse.py`, `GET /wikipedia/models` +
`GET /wikipedia/engines`) is a different job from Phase 5 and shares only
`normalize_text` with it.** Phase 5 asks "which engine is this vehicle?" and
declines when unsure; this asks "what does Wikipedia have for this car at all?"
and is deliberately permissive — the person reading the list decides, so there
is no accept threshold, no auto-pick and no score in the response.

**It is a two-step drill-down — model, then engine — and that shape is the
point.** Free-text matching over a listing blob cannot always be trusted to
have found the right car, and *nothing in its result says when it hasn't*: a
3-series Gran Turismo has no article in the corpus, so the closest honest answer
is a different body of the same era, offered with no visible difference from a
correct one. Ranking harder cannot fix that; only the person holding the logbook
can. So `GET /models` groups the brand's rows by article and lets them choose,
and `GET /engines?article=...` then filters *exactly* to that choice. What is
left for free text — telling engines apart inside one generation — is the job
the corpus does reliably. Three properties are load-bearing:

- **The model list ranks but never filters** (`group_models` appends the
  unmatched remainder). The engine list may filter, because by then the user has
  told us the generation. Filtering the model list would strand the Gran Turismo
  user on one confidently wrong option.
- **`article` is an exact filter, not a ranking hint**, and it outranks the date
  scope. It carries an explicit human choice; a fuzzy reading of that would be
  worse than none.
- **Model rows carry recognition aids, not just titles.** de.wikipedia names
  these articles by chassis code ("BMW G20", "Mercedes-Benz Baureihe 205") and
  nobody reads a logbook and thinks "G20", so a row shows the production years
  and the shortest distinct engine badges inside it.

Underneath both steps, three ranking rules, each fixing a measured regression:

- **Best-coverage ranking, not all-or-nothing.** The first version dropped a
  row as soon as any query token matched nothing, which was fatal for the
  listing text this endpoint is actually given: `320d xDrive GT
  Sport-Automatic "Sport Line"` and `Golf 1.6 TDI Comfortline DSG` both
  returned zero rows while `320d` returned fourteen. Rows are now tiered by how
  many query tokens they match, and a word the corpus has never heard of is
  ignored rather than fatal. Growing `QUERY_NOISE_TOKENS` is not the fix — the
  tail of trim names is unbounded, and that vocabulary is shared with
  `calculate/router.py::_wikipedia_model_text`.
- **`ignored_terms` is load-bearing, not decoration.** Because ranking now
  always returns something, a row can be offered for a car the corpus does not
  hold. The 3-series Gran Turismo is the standing case: there is no F34 article
  at all, so "GT" matches nothing and what comes back is a different body of
  the same era. Reporting the dropped word is the only thing that makes that
  visible.
- **`registered` scopes the pool *before* ranking, never after.** A 2016 "320d
  xDrive" query ranked first and filtered second returns nothing, because the
  only xDrive rows in the corpus are a 2019+ G20; scoped first it settles for
  "320d" and returns the correct-era F30. An over-narrow date is abandoned
  rather than obeyed — a mistyped year costs relevance, never the whole list.
  The UI also makes the scope visible and switchable (the year chip in
  `Co2EnginesModal`), because a silently narrowed model list rebuilds the same
  trap: a user whose parsed date is a year out would see their car missing with
  nothing saying why.

IDF weighting inside a tier is computed over the *current* pool, which is
deliberate (it answers which typed word discriminates among the rows being
shown) and bounded: the tier is picked by matched-token count before any weight
applies, so a row matching two tokens can never be displaced by one matching a
single rare token.

Measured against 500 random catalogue rows with known CO2 (re-run 2026-09-02,
passing model+variant as the query text): **36.2% answered, 55.2% of those
containing the true value** — i.e. roughly one in five vehicles gets an answer
that is actually right. An earlier 1,200-row run recorded 38.8%/57% (p90 miss
20 g/km); the two agree within sampling noise. There is no checked-in
benchmark script for either, so re-measuring means writing one.

That hit rate is why §0 forbids this tier from auto-filling — it is a "check
your COC" hint, never a tax input. It is wired into `/calculate` as a fourth
tier that writes **only** `CalculateResponse.wikipedia_hint`:

- It runs only when the listing had no CO2 *and* the catalogue produced none.
- `co2_source` stays `manual_required` — deliberately **not** the
  `wikipedia_estimate` enum value `docs/WIKIPEDIA_CO2_PLAN.md` §0 asks for.
  That same section also requires `/calculate` to keep returning
  `manual_required` for this case, and one field cannot do both; a sibling
  field keeps "manual_required means manual_required" true for every
  consumer. **The plan document is stale on this point; this file is right.**
- Its value never reaches `calculate_ppmv` — the missing-CO2 guard returns
  before the engine is invoked.
- It appends no warning (`require_manual_co2` already added the single CO2
  warning) and swallows its own exceptions: a hint must never turn a working
  200 into a 500.
- Query text is `listing.model + listing.variant`. Model alone answers
  slightly more often (38.4%) but less accurately (50.5%); see
  `_wikipedia_model_text`'s docstring for the measured trade.

**Run `--dry-run` over the full scope before any real crawl when brands
change** — it costs ~175 requests and 2 minutes and catches wrong brand
articles, LLM misclassifications and over-broad index-following before
anything is written.

Resumable by design: an already-cached `ok` row is never re-fetched, so an
interrupted crawl restarts cheaply. `--refresh` is the escape hatch for when a
brand's *source article* mapping changed and its old rows are now wrong.

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
- `WikipediaEngineData` — one engine variant extracted from a de.wikipedia
  spec table, unique on `(source_fingerprint, variant_index)`. `brand` is the
  *cross-checked* brand and is what Phase 5 filters on; `crawl_brand` records
  what the crawl thought and is never a matching filter.
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

Next.js app. `components/` holds the UI the calculator is actually built
from — `CandidatesList` (catalogue picker + score badges), `VehicleForm`
(the manual-entry fields), `Co2HintNote` (the Wikipedia range, styled to
read as provisional rather than confident), `Co2EnginesModal` (the engine
picker, and the only modal in the app — its overlay/Escape/positioning are
bespoke and inlined, there is no shared `Modal` to reuse) and
`ParsedFieldsCard`.

`Co2EnginesModal` is a two-step drill-down with a breadcrumb header — model
list, then that model's engines. The brand crumb is a real button, not a label:
on a phone it is the only way back to step one, and leaving that to the
browser's back gesture (which closes the page, not the step) turns a two-step
modal into a trap.

`Co2HintNote` renders **inside** the CO2 field: a muted chip in the input's
trailing edge, and an absolutely-positioned popover for the detail. Both are
outside the layout flow on purpose. An earlier version was a block below the
input, and because that input is one cell of a three-column grid, the block
stretched the whole row and pushed the date fields down the page. Anything
added here has to stay out of flow or the grid rhythm breaks again. The two
actions inside it are deliberately unalike — "Promijeni motor" is a filled
in-app control, the source link is muted with an external-link glyph — because
as two identical lines of blue text they were indistinguishable.
`app/page.tsx` is the PPMV calculator (the live product);
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
  auto-pick the top match." Note this holds on the **backend only**:
  `frontend/app/page.tsx` auto-applies `candidates[0]`'s price and fuel on
  every URL submit regardless of `match_status`. The one carve-out is CO2
  when a `wikipedia_hint` is present — filling the field from an unconfirmed
  candidate would contradict the "we don't know this" note rendered directly
  beneath it.
- **`normalize_text`/`build_match_key` in `matching.py` must stay
  deterministic and side-effect-free** — the same function normalizes
  both the stored `match_key` at ingestion time and the query at lookup
  time; if they ever diverge, matching silently breaks for every
  already-ingested row.
