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
| autobid.de | `httpx` | Server-rendered, no browser needed. CO2 not exposed pre-login. |
| njuškalo | Playwright Chromium | JS-rendered |
| AutoScout24 | Playwright Chromium | Parses the `__NEXT_DATA__` JSON blob |
| mobile.de | **Apify actor** | Akamai Bot Manager blocks direct browser fetches outright |

mobile.de therefore sits behind a guard stack (per-IP rate limit, Cloudflare
Turnstile, a TTL cache and a daily spend cap) rather than a local extractor —
see [`docs/MOBILE_DE_APIFY_SPEC.md`](docs/MOBILE_DE_APIFY_SPEC.md).

Sweep/bulk scraping is out of scope for now. njuškalo and mobile.de block
automated sweeps with bot-detection that requires Apify actors to bypass —
that cost/infrastructure decision is deferred.

---

## Project layout

```
app/
  core/          # config (pydantic-settings), exceptions, rate limits, Turnstile
  ppmv/          # tax engine, tables, schemas, router — the main feature
  calculate/     # POST /calculate — the endpoint the frontend actually calls
  scraping/      # per-site extractors, Apify fetcher, guard stack, persistence
  catalogue/     # fuzzy listing→catalogue matching + Excel ingestion pipeline
  data/          # offline catalogue ingestion CLI + source files
  profitability/ # import profitability calculator (deferred, empty package)
  db/            # SQLAlchemy models + session
  main.py        # FastAPI app factory
frontend/        # Next.js — PPMV calculator page (live), Profitability (shell)
tests/           # 243 tests incl. the official Audi A5 regression
```

See [`docs/PROJECT_STRUCTURE.md`](docs/PROJECT_STRUCTURE.md) for the
file-by-file view and current status, and [`CLAUDE.md`](CLAUDE.md) for
architecture and conventions.

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
# Tests — 243 of them, about half a second, no DB needed
uv run pytest tests/ -m "not integration" -q

# Lint / typecheck
uv run ruff check app/ tests/ scripts/
cd frontend && npx tsc --noEmit && npm run lint
```

Those four commands are exactly what CI runs
([`.github/workflows/ci.yml`](.github/workflows/ci.yml)); the deploy workflow
requires them to pass before it ships. Tests marked
`@pytest.mark.integration` need a real database and an `OPENROUTER_API_KEY`.

Python ≥ 3.12 required. Dependencies managed with [uv](https://docs.astral.sh/uv/).

---

## Infrastructure

Designed for a Hetzner CAX11 ARM VPS (2 vCPU / 4 GB / €6 per month). One
browser session at a time, sequential scraping. Swap file recommended as an
OOM guard when running Playwright.

---

## Deployment

The stack (Postgres, backend, frontend) ships as a single
`docker-compose.yml` for a self-hosted VPS:

```bash
cp .env.example .env   # fill in real values, see below
docker compose up -d --build
```

- [`Dockerfile`](Dockerfile) — FastAPI backend with Playwright/Chromium.
- [`frontend/Dockerfile`](frontend/Dockerfile) — Next.js standalone build.
- [`.github/workflows/deploy.yml`](.github/workflows/deploy.yml) — SSHes into
  the VPS and redeploys on every push to `main`, once CI passes.

Compose binds everything to localhost (`8011` backend, `3011` frontend); a
reverse proxy on the host terminates HTTPS and forwards to those ports.

See **[DEPLOYMENT.md](DEPLOYMENT.md)** for the full step-by-step guide:
buying a domain, provisioning the VPS, environment configuration, and setting
up automatic deploys.
