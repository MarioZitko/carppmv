# mobile.de single-link parsing via Scrapingdog — implementation handoff

> Hand this to a fresh chat/agent to execute. All paths are under
> `/Users/mariozitko/Projects/carPPMV`. Stack: Python 3.12 + FastAPI, async SQLAlchemy 2.0 /
> asyncpg / Postgres, `uv` for deps; Next.js/React frontend; Docker Compose behind Caddy on a
> Hetzner VPS. Prior research: `docs/MOBILE_DE_FREE_PARSING_PLAN.md`.

## Context

mobile.de is behind **Akamai Bot Manager**. The current extractor drives Playwright **Firefox**
and only works **headful** — it fails headless, so it cannot run on the VPS. The free
Facebook/Telegram OG paths were rejected/blocked in practice. Decision: fetch the listing HTML
through **Scrapingdog** (residential-proxy scraping API, returns raw HTML, ~$0.004–0.01/parse),
and **reuse the existing BeautifulSoup parser unchanged**. Because each parse costs real money,
add **abuse protection**: Cloudflare Turnstile bot-check, per-IP rate limiting, a global daily
spend cap (degrade to manual entry when hit), a 24h result cache, and per-request metrics — all
backed by **Postgres** (no Redis). mobile.de then gets wired into the `/calculate` flow.

## What changes at a glance

- **Keep** all HTML parsing in `app/scraping/extractors/mobile_de.py` (everything from
  `soup = BeautifulSoup(html, "lxml")` at line ~221 onward: `_extract_price`,
  `_parse_spec_table`, `_LABEL_MAP`, `_FUEL_MAP`, `_normalise_number` + field helpers, the
  `ListingData` construction) and the `sec-if-cpt-container` / short-page / status-code
  `ScrapingError` guards.
- **Replace** only the transport (`MobileDeExtractor.extract` lines ~183–219, the Playwright
  Firefox block) with a Scrapingdog HTTP fetch, following the httpx pattern already used in
  `app/scraping/extractors/autobid_de.py` (`extract`, lines ~284–299). Keep Firefox selectable
  for local dev.
- **Add** Scrapingdog fetcher, mobile.de URL parser, two Postgres tables (cache + metrics),
  rate-limit + budget + Turnstile guards on `/calculate`, and frontend Turnstile + manual
  fallback. Wire mobile.de into `/calculate`.

---

## Step 0 — Scrapingdog spike (do first, ~15 min)

With the API key, curl the two real URLs to find the **minimal params** that return real HTML
(not an Akamai challenge) and note the credit cost. Endpoint: `https://api.scrapingdog.com/scrape`
params `api_key`, `url`, `dynamic` (JS render), `premium` (residential). Try `dynamic=false`
first (cheapest), then `dynamic=true`, then add `premium=true`. Set the defaults below from the
cheapest combo that works.
- `https://suchen.mobile.de/auto-inserat/audi-a5-3-0-tdi-s-tronic-quattro-korb/456793544.html`
- `https://suchen.mobile.de/fahrzeuge/details.html?id=459632333`

---

## 1. Config & secrets — `app/core/config.py`

Add fields to `Settings` (pydantic-settings; env var = UPPER_SNAKE of the attribute; give each a
default so unset never crashes). Consume via `get_settings()`.

```python
scrapingdog_api_key: str = ""
mobile_de_fetcher: str = "scrapingdog"          # "scrapingdog" (VPS) | "firefox" (local dev)
scrapingdog_dynamic: bool = False               # set from Step 0
scrapingdog_premium: bool = False               # set from Step 0
scrapingdog_cost_usd_per_call: float = 0.01     # for the budget ledger
turnstile_secret_key: str = ""                  # empty ⇒ bot-check disabled (dev)
ip_hash_salt: str = "change-me"                 # salt for hashing client IPs
listing_cache_ttl_hours: int = 24
rate_limit_per_ip_hour: int = 10
rate_limit_per_ip_day: int = 30
daily_scrape_budget_calls: int = 200            # global Scrapingdog ceiling/day
```
Document all of these in `.env.example`. Frontend needs `NEXT_PUBLIC_TURNSTILE_SITE_KEY` (see §6/§7).

---

## 2. Scrapingdog fetcher — new `app/scraping/fetchers/scrapingdog.py`

```python
async def fetch_html(url: str) -> str:
    s = get_settings()
    if not s.scrapingdog_api_key:
        raise ScrapingError("SCRAPINGDOG_API_KEY not configured")
    params = {"api_key": s.scrapingdog_api_key, "url": url,
              "dynamic": str(s.scrapingdog_dynamic).lower()}
    if s.scrapingdog_premium:
        params["premium"] = "true"
    async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
        resp = await client.get("https://api.scrapingdog.com/scrape", params=params)
    if resp.status_code != 200:
        raise ScrapingError(f"Scrapingdog returned {resp.status_code} for {url}")
    return resp.text
```
`httpx` is already a dependency. Use a 60s timeout (JS render is slow). `ScrapingError` is in
`app/core/exceptions.py` (mapped to HTTP 502 by `register_exception_handlers`).

### Refactor `MobileDeExtractor.extract`
Split transport from parsing. Add `_fetch_html(self, url)` that dispatches on
`get_settings().mobile_de_fetcher`: `"scrapingdog"` → `scrapingdog.fetch_html(url)`;
`"firefox"` → the existing Playwright code (keep it intact for local dev). After fetch, keep the
existing block guards (`sec-if-cpt-container` in html, `len(html) < 2000`) then run the unchanged
parsing pipeline. Net: `extract` = `_fetch_html` + existing guards + existing parse.

---

## 3. mobile.de URL parser — new `app/scraping/extractors/mobile_de_url.py`

```python
@dataclass
class MobileDeUrlInfo:
    listing_id: str | None
    brand: str | None
    model: str | None
    variant: str | None

def parse_mobile_de_url(url: str) -> MobileDeUrlInfo: ...
```
Handle both formats: `/auto-inserat/{make-model-variant-slug}/{id}.html` (split slug → brand =
first token, handling multi-word brands like `mercedes-benz`, `alfa-romeo`, `land-rover`; rest →
model/variant) and `/fahrzeuge/details.html?id={id}` (id only, no brand/model). Secondary signal
now that Scrapingdog returns full HTML (the spec-table parser already yields brand/model/EZ/price)
— use it to cross-fill brand/model when the HTML omits them, especially for id-only URLs.
Unit-test it (see §8), pattern per `tests/test_autobid_de_extractor.py`.

---

## 4. Postgres cache + metrics — `app/db/models.py`

Add two `Base` tables (auto-created by the startup hook in `app/main.py` — no Alembic):

```python
class ListingCache(Base):            # 24h result cache to avoid re-spending
    __tablename__ = "listing_cache"
    id: Mapped[int] = mapped_column(primary_key=True)
    cache_key: Mapped[str] = mapped_column(unique=True, index=True)   # "mobile.de:{listing_id}"
    payload: Mapped[dict] = mapped_column(JSON)                       # serialized ListingData
    fetched_at: Mapped[datetime] = mapped_column(index=True)

class ParseEvent(Base):              # per-request ledger: metrics + rate-limit + budget source
    __tablename__ = "parse_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    ip_hash: Mapped[str] = mapped_column(index=True)
    site: Mapped[str]
    listing_id: Mapped[str | None]
    source: Mapped[str]              # "cache" | "scrapingdog" | "firefox"
    status: Mapped[str]             # success|failed|blocked|rate_limited|cap_reached|needs_manual|bot_rejected
    cost_usd: Mapped[float] = mapped_column(default=0.0)
    created_at: Mapped[datetime] = mapped_column(index=True)
```
(Existing `ScrapeRun` table is run/sweep-oriented; a dedicated `ParseEvent` is cleaner for
on-demand per-request accounting.)

---

## 5. Abuse protection — new `app/core/limits.py` + `app/core/turnstile.py`

**Client IP:** behind Caddy, read `X-Forwarded-For` (first hop), fallback `request.client.host`.
Store only `sha256(ip_hash_salt + ip)`.

**Rate limit** (`limits.py`): count `ParseEvent` rows for `ip_hash` in the last hour/day; exceed
`rate_limit_per_ip_hour`/`_day` → raise HTTP 429 (log a `rate_limited` event). Applies to all
`/calculate` URL submits (cheap protection).

**Global budget** (`limits.py`): count `ParseEvent` where `source="scrapingdog"` and
`created_at >= today 00:00` ≥ `daily_scrape_budget_calls` → **cap reached** → skip Scrapingdog
and return a "needs manual input" response (degrade, don't 429). Log `cap_reached`.

**Turnstile** (`turnstile.py`):
```python
async def verify_turnstile(token: str | None, ip: str) -> bool:
    secret = get_settings().turnstile_secret_key
    if not secret:            # disabled in dev
        return True
    async with httpx.AsyncClient(timeout=10.0) as c:
        r = await c.post("https://challenges.cloudflare.com/turnstile/v0/siteverify",
                         data={"secret": secret, "response": token or "", "remoteip": ip})
    return bool(r.json().get("success"))
```
Invalid token → HTTP 403 (log `bot_rejected`) before any spend.

---

## 6. Wire mobile.de into `/calculate` — `app/calculate/router.py` + `schemas.py`

- `schemas.py`: add `turnstile_token: str | None = None` to `CalculateRequest`.
- `router.py`: **remove** `"mobile.de"` from `_UNSUPPORTED_SITES` (line 42); **add**
  `MobileDeExtractor()` to `_EXTRACTORS` (lines 36–40).
- Add `request: Request` param to `calculate()`. Order of operations:
  1. Resolve IP + `ip_hash`; **rate-limit check** → 429 if exceeded.
  2. Detect site. **For mobile.de only:** verify **Turnstile** (403 on fail); `parse_mobile_de_url`
     → `cache_key`; check `ListingCache` fresh within TTL → use cached `ListingData`
     (`source="cache"`, cost 0). On miss: **budget check** → if cap reached, return degraded
     "manual required" response; else `await extractor.extract(url)`, upsert `ListingCache`, log
     `ParseEvent(source="scrapingdog", cost=cost_usd_per_call)`.
  3. Continue the **existing** path: build `ParsedFields`; if `listing.brand`, call `find_match`
     (`app/catalogue/matching.py:619`, signature already takes `brand, model, variant, fuel_type,
     power_kw, year, co2_g_km, limit`) to fill CO₂/fuel from the catalogue; `calculate_ppmv(...)`.
  4. If `price_eur` or `first_registration` is missing, set `co2_source`/warnings so the frontend
     prompts manual completion (the form is already prefilled from `parsed`).
- Log a `ParseEvent` on every terminal outcome (success/failed/blocked/needs_manual/cap_reached).

`CalculateResponse` already carries `parsed`, `co2_source`, `match_status`, `candidates`,
`warnings` — reuse them; the frontend already renders these.

---

## 7. Frontend — Turnstile + manual fallback

- `frontend/lib/api.ts`: `calculateFromUrl(url, turnstileToken)` → include token in the POST body.
  Surface new statuses via `ApiError`: 429 (rate limited), 403 (verification failed).
- `frontend/components/UrlInputForm.tsx`: render a **Cloudflare Turnstile** widget (add
  `@marsidev/react-turnstile` to `frontend/package.json`, or load the vanilla script), site key
  from `process.env.NEXT_PUBLIC_TURNSTILE_SITE_KEY`; if unset (dev), skip the widget. Pass the
  token up to `handleUrlSubmit`.
- `frontend/app/page.tsx` (`handleUrlSubmit`, lines ~58–92): pass the token; **remove** the blanket
  `err.status === 400 →` "mobile.de trenutno nije podržan…" message (mobile.de is now supported).
  Map 429 → "previše zahtjeva, pokušajte kasnije", 403 → "provjera nije uspjela". When the response
  indicates missing price/EZ or a cap-degraded result, keep the user on the **prefilled
  `VehicleForm`** (`frontend/components/VehicleForm.tsx`) to type the missing field — the URL flow
  already patches `form` from `data.parsed`, so this is mostly messaging + ensuring the form shows.

---

## 8. Tests — `tests/` (pytest, `asyncio_mode=auto`, no conftest)

- **URL parser unit** (`tests/test_mobile_de_url.py`, no marker/network): inline slug + id-only
  URLs → assert `MobileDeUrlInfo`. Mirror `tests/test_autobid_de_extractor.py`.
- **Parser-from-HTML unit**: save a captured Scrapingdog HTML response as a fixture
  (`tests/fixtures/mobile_de_sample.html`); feed it into the parsing portion (mock `_fetch_html`
  with `unittest.mock.AsyncMock`, or add `pytest-httpx`/`respx` as a dev dep to mock the
  Scrapingdog GET) → assert `ListingData` (price, first_registration=EZ, brand, model).
- **Limits/budget/turnstile**: unit-test the SQL count logic against a test session and mock
  httpx for `verify_turnstile`. Mark DB-dependent ones `@pytest.mark.integration`.
- **Do not touch** the €3,475.50 regression in `tests/test_ppmv_engine.py::test_audi_a5_regression`.
- Run: `uv run pytest` (skip integration in CI).

---

## 9. Deploy — compose / Dockerfiles / Caddy / env

- `.env.example` (+ real `.env` on VPS): add `SCRAPINGDOG_API_KEY`, `MOBILE_DE_FETCHER=scrapingdog`,
  `SCRAPINGDOG_DYNAMIC`, `SCRAPINGDOG_PREMIUM`, `TURNSTILE_SECRET_KEY`, `IP_HASH_SALT`, the
  rate-limit/budget vars, and `NEXT_PUBLIC_TURNSTILE_SITE_KEY`.
- `frontend/Dockerfile`: add `ARG NEXT_PUBLIC_TURNSTILE_SITE_KEY` + `ENV` before `npm run build`
  (it's inlined at build time, like `NEXT_PUBLIC_API_BASE_URL`). Pass it as a build arg in
  `docker-compose.yml` under the `frontend` service.
- `docker-compose.yml`: backend already `env_file: .env` — new backend vars flow automatically.
- `Caddyfile`: unchanged; Caddy sets `X-Forwarded-For` by default (the backend trusts it since only
  Caddy fronts it).
- **Optional slimming:** the backend `Dockerfile` runs `playwright install --with-deps chromium`.
  With `MOBILE_DE_FETCHER=scrapingdog` no browser is used on the VPS — this step can be dropped for
  a smaller/faster image (keep the `playwright` dep for local Firefox dev).

---

## Verification (end to end)

1. Step 0 spike returns real Audi A5 HTML → confirms params + credit cost.
2. `uv run pytest` green (URL parser, HTML-fixture parse, limits; €3,475.50 untouched).
3. Local: `MOBILE_DE_FETCHER=scrapingdog`, key set, Turnstile unset → `POST /calculate` with both
   real URLs returns `ppmv_eur` (or a clean "needs manual" with prefilled fields). Second identical
   request is served from `ListingCache` (a `ParseEvent(source="cache")` row, no new spend).
4. Rate limit: exceed `rate_limit_per_ip_hour` → 429. Budget: set `daily_scrape_budget_calls=0` →
   degraded manual response, no Scrapingdog call.
5. Staging with Turnstile keys: the widget appears; a forged/absent token → 403.
6. Inspect `parse_events` for correct `source`/`status`/`cost_usd` accounting.

---

## What YOU must provide before/while implementing

1. **Scrapingdog** account → `SCRAPINGDOG_API_KEY` (and run Step 0 to set `dynamic`/`premium`).
2. **Cloudflare Turnstile** site → `NEXT_PUBLIC_TURNSTILE_SITE_KEY` + `TURNSTILE_SECRET_KEY`.
3. A random **`IP_HASH_SALT`**.
4. Confirm/tune the numbers: `rate_limit_per_ip_hour/day`, `daily_scrape_budget_calls`,
   `scrapingdog_cost_usd_per_call`, `listing_cache_ttl_hours`.
5. Note (housekeeping): a live `OPENROUTER_API_KEY` is committed in `.env` — rotate it.
