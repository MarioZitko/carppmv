# Project structure & status

Snapshot of what exists, what's wired up, and what's still deferred. Supersedes
nothing in [`Car Import Taxes Plan.md`](../Car%20Import%20Taxes%20Plan.md) —
this is the "where are we now" view; that doc is the original build-order
decision record.

---

## Layout

```
app/
  ppmv/            # Tax engine — DONE
    engine.py        # calculate_ppmv(), pure function, no I/O
    tables.py         # NEDC/WLTP brackets, depreciation table
    schemas.py         # PPMVRequest / PPMVResponse / FuelType / CO2Standard
    router.py          # POST /ppmv/calculate — specs in, tax out, no scraping/DB

  scraping/         # Single-URL on-demand scraper — DONE
    extractors/       # One per site: autobid_de, autoscout24, mobile_de, njuskalo
    engines.py          # Per-site fetch engine config (httpx | chromium | firefox)
    schemas.py          # ListingData — the shared contract every extractor returns
    router.py           # POST /scrape/listing — url in, ListingData out

  calculate/        # The actual product endpoint — DONE
    router.py          # POST /calculate — url in, PPMV out. Combines scraping +
                        # catalogue matching (CO2 fallback) + PPMV in one call.
    schemas.py          # CalculateRequest / CalculateResponse / ParsedFields

  catalogue/         # Catalogue matching + ingestion support — DONE
    matching.py          # find_match() — fuzzy listing→Catalogue matcher, already
                          # called from calculate/router.py as a CO2 fallback
    canonical_schema.py  # CanonicalRow, apply_mapping() — shared by both ingest paths
    llm_mapper.py         # OpenRouter column-mapping call, one per unique header layout

  data/catalogues/    # Catalogue ingestion pipeline — DONE, data now fully loaded
    ingest.py            # Concurrent manifest-driven ingest (see "Ingestion" below)
    manifest.jsonl        # brand/year/path/url for every downloaded Excel file
    <brand-slug>/         # Downloaded source Excel files, one dir per brand group

  db/                 # SQLAlchemy models + session — DONE
    models.py             # Catalogue, ScrapeRun, Listing
    session.py             # AsyncSessionLocal, engine (NullPool)

  profitability/      # DEFERRED — currently an empty package (__init__.py only)

  core/                # config.py (Settings), exceptions.py — DONE

tests/
  test_ppmv_engine.py   # 13 unit tests incl. official Audi A5 regression case
  test_apply_mapping.py # Ingestion column-mapping tests, no LLM calls

scripts/
  ingest_catalogue.py    # Single-file manual ingest CLI (kept for one-off debugging;
                          # app/data/catalogues/ingest.py is the real pipeline)

frontend/                # Next.js app — DONE (PPMV Calculator page); Profitability is a shell
  app/
    page.tsx                # PPMV Calculator (landing page)
    profitability/page.tsx  # Shell only, no backend to call yet
    layout.tsx               # Nav + shared chrome
  lib/
    api.ts                    # fetch wrappers for /calculate and /ppmv/calculate
    types.ts                   # TS mirrors of the Pydantic schemas
    format.ts, fuel.ts          # small client-side formatting/parsing helpers
  components/
    UrlInputForm.tsx
    ParsedFieldsCard.tsx
    PPMVBreakdownCard.tsx
    ManualFieldsForm.tsx
```

---

## What's actually live right now

| Endpoint | Does | Status |
|---|---|---|
| `POST /ppmv/calculate` | Specs in, tax breakdown out. No DB/scraping. | Done, regression-tested |
| `POST /scrape/listing` | URL in, normalized `ListingData` out. | Done, 4 sites |
| `POST /calculate` | URL in, PPMV out — scrapes, fills missing CO2 from catalogue via `find_match()`, runs the tax engine. | Done — this is the real product endpoint |

`mobile.de` is scrape-able standalone (`/scrape/listing`) but **not** wired into `/calculate` yet (`_UNSUPPORTED_SITES` in `calculate/router.py`) — Firefox-engine listings aren't in the combined flow.

---

## Catalogue ingestion — status as of this session

Ingestion pipeline (`app/data/catalogues/ingest.py`) was rewritten this session:
concurrent (`--concurrency`, default 24), per-header-layout LLM call caching
(success *and* failure), blank-header files skipped without wasting an API
call, deadlock-safe upserts (rows sorted by the unique-constraint columns
before each batch), and per-row filtering so one row with an unresolvable
fuel type or missing CO2 no longer fails an entire file's batch insert.

**Ingested so far:** `bmw-mini` only (288/289 files, full 2013–2026 history).
Audi/Porsche/Seat/Škoda/VW/Cupra group was already populated from before this
session's fixes and is believed complete (150 distinct price-list dates,
full manifest range) but hasn't been re-verified against the new pipeline.

**Not yet ingested (33 brand folders):** baic, byd, chevrolet, citroën-ds,
dacia, fiat-lancia-alfa-romeo-abarth-jeep-maserati, forthing, foton, geely,
honda, hyundai, infiniti, isuzu, jaguar, kia, land-rover, lexus, lynkco,
mazda, mercedes-benz-smart, mg, mitsubishi, nissan, omoda-jaecoo, opel,
peugeot, renault, ssangyong, subaru, suzuki, tata, toyota, volvo.

To ingest one: `python -m app.data.catalogues.ingest --brand <slug> --concurrency 24`
(drop `--brand` to run everything at once — expect real OpenRouter latency
per unique column layout per brand, not just file count).

---

## Fixed this session

- **`main.py` startup migration** — was forcibly rewriting the `catalogue`
  table's unique constraint down to `UNIQUE(match_key)` on every app start,
  which would have silently collapsed all per-year price history into one row
  per (brand, model, variant). Removed; `Base.metadata.create_all` from
  `db/models.py` is now the only schema-creation path (new tables only, no
  destructive alters on existing ones).
- **Ingestion speed** — was fully sequential with blocking LLM calls; now
  concurrent with real async cancellation.
- **Batch-insert deadlocks** — concurrent upserts to overlapping brands could
  deadlock in Postgres; fixed by sorting each batch by the unique-constraint
  columns before insert (standard Postgres deadlock-avoidance pattern), plus
  one retry as a safety net.
- **Silent data loss on bad rows** — a single row with an unresolvable fuel
  type or missing CO2 was failing the entire file's insert batch (hundreds of
  good rows lost with it). Now filtered out individually.
- **Unreadable error logs** — DB write failures were dumping the full SQL
  statement plus every bound parameter (thousands of characters). Now logs
  just the underlying Postgres/asyncpg error.

---

## Deferred (per the master plan, unchanged)

- **Profitability calculator** (`app/profitability`) — empty stub, not started.
  Second product page per the plan; will consume `catalogue/matching.py`
  the same way `/calculate` already does.
- **Sweep scraping** (nightly/weekly bulk) — njuškalo and mobile.de are
  hard-blocked by bot detection on sweep patterns (not single-page fetches);
  needs an Apify cost/actor decision that hasn't been made.
- **Profitability page content** — `frontend/app/profitability` is a shell only;
  waits on the `app/profitability` backend above.

---

## Known gaps worth tracking

- `_upsert_rows` batches at 500 rows; no file in the current manifest gets
  close to that, so it's untested at the batch-boundary in practice.
- `matching.py`'s `find_match()` fetches *all* rows for a brand on every call
  (no pagination/limit at the SQL level) — fine at current per-brand row
  counts (hundreds to low thousands), revisit if a brand's catalogue grows
  much larger.
- No migration tool (Alembic or similar) — schema changes to *existing*
  tables currently have no defined process now that the ad-hoc `main.py`
  ALTER statements are gone. Fine while the schema is stable; will need a
  real answer before the first breaking schema change.
