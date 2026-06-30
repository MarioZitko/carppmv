# carPPMV

Croatian car-import PPMV tax calculator. Paste a listing URL, get the exact
tax breakdown before you buy.

PPMV (Poseban porez na motorna vozila) is a Croatian special tax on motor
vehicles, calculated on declaration at customs. The formula and tables are
published by the Croatian Customs Administration (carina.gov.hr) but doing
the math by hand is painful — this tool does it for you.

---

## What it does

1. **Scrapes a listing URL** (mobile.de, AutoScout24, njuškalo, autobid.de)
   to extract price, CO2, fuel type, and registration date.
2. **Runs the PPMV formula** against the official Croatian tax tables.
3. **Returns an itemized breakdown** — value component, eco component,
   depreciation percent, and final tax — so you can cross-check against the
   official customs declaration output.

The formula (simplified):

```
PPMV(as-new) = VN + (price − bracket_floor) × bracket_rate   [value component]
             + (CO2 − eco_bracket_floor) × rate_per_g_km       [eco component]

PPMV(used)   = PPMV(as-new) × depreciation_percent(months_old)
```

NEDC tables apply to vehicles first registered before 2021-01-01; WLTP tables
apply from 2021-01-01 onward.

---

## Quick start

```bash
# Install deps (requires uv)
uv sync

# Copy env template and fill in DATABASE_URL (only needed for listings storage)
cp .env.example .env

# Start the API
uv run uvicorn app.main:app --reload --port 8000
```

The API is now at `http://localhost:8000`. Interactive docs at `/docs`.

---

## API

### `POST /ppmv/calculate`

Calculate PPMV directly from known vehicle specs. No DB or scraping required.

**Request**
```json
{
  "price_eur": 36490,
  "co2_g_km": 136,
  "fuel_type": "diesel",
  "first_registration_date": "2020-08-17",
  "declaration_date": "2025-07-10"
}
```

**Response**
```json
{
  "breakdown": {
    "as_new_value_component": 2066.96,
    "as_new_eco_component": 1408.54,
    "as_new_total": 8362.61,
    "depreciation_percent": 41.56,
    "months_old": 58,
    "final_ppmv": 3475.50
  },
  "co2_standard_used": "NEDC"
}
```

The example above is the official Audi A5 40 TDI regression case from
carina.gov.hr — expected output is exactly **3,475.50 EUR**.

---

## Scraping

On-demand single-URL scraping (one listing at a time) is the primary input
mode. Each site uses a different fetch engine:

| Site | Engine | Notes |
|---|---|---|
| autobid.de | `httpx` | No browser needed |
| njuškalo | Playwright Chromium | Works on single pages |
| AutoScout24 | Playwright Chromium | Works on single pages |
| mobile.de | Playwright **Firefox** | Chromium blocked by Akamai |

Sweep/bulk scraping is out of scope for now. njuškalo and mobile.de block
automated sweeps with bot-detection that requires Apify actors to bypass —
that cost/infrastructure decision is deferred.

---

## Project layout

```
app/
  core/          # config (pydantic-settings), exceptions, shared types
  ppmv/          # tax engine, tables, schemas, router — the main feature
  scraping/      # per-site extractors, fetch-engine config, schemas
  catalogue/     # catalogue ingestion from brand Excel files (deferred)
  profitability/ # import profitability calculator (deferred)
  db/            # SQLAlchemy models (Catalogue, ScrapeRun, Listing), session
  main.py        # FastAPI app factory
tests/
  test_ppmv_engine.py   # 13 unit tests incl. Audi A5 regression
```

---

## Environment variables

See [`.env.example`](.env.example) for all variables. The only required one
for running the API and calculator is:

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://localhost/carppmv` | Postgres for listing storage |
| `OPENROUTER_API_KEY` | _(empty)_ | Only needed for catalogue ingestion |
| `OPENROUTER_MODEL` | `deepseek/deepseek-v4-flash` | LLM for column mapping during ingestion |
| `DEBUG` | `false` | Enable debug logging |

`POST /ppmv/calculate` works without any database. A DB is only needed when
scraped listings are persisted for later use.

---

## Development

```bash
# Run tests (13 unit tests, all pure functions, no DB needed)
uv run pytest tests/ -v

# Lint
uv run ruff check app/ tests/
```

Python ≥ 3.12 required. Dependencies managed with [uv](https://docs.astral.sh/uv/).

---

## Infrastructure

Designed for a Hetzner CAX11 ARM VPS (2 vCPU / 4 GB / €6 per month). One
browser session at a time, sequential scraping. Swap file recommended as an
OOM guard when running Playwright.
