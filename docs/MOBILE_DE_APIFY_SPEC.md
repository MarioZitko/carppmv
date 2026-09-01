# mobile.de on-demand scraping via Apify actor — implementation spec

> **STATUS: implemented and live.** This is the design record for the shipped
> mobile.de path, not a task list — `app/scraping/fetchers/apify_mobile_de.py`,
> `mobile_de_guard.py`, `mobile_de_service.py`, `core/limits.py`,
> `core/turnstile.py` and the `ListingCache`/`ApifyEvent` tables all exist.
> Code and `.env.example` point here for the rationale, so it stays.

> Hand this to Claude Code to execute. All paths under
> `/Users/mariozitko/Projects/carPPMV`. Stack: FastAPI/Python, async SQLAlchemy,
> httpx, uv. Prior context: `MASTER_PLAN_v7.md`, `MOBILE_DE_FREE_PARSING_PLAN.md`.

---

## Context

mobile.de is behind Akamai Bot Manager. All free bypass attempts failed (Facebook
OG blocked, Camoufox works once then IP-flagged, no PAYG scraping API exists under
$29/month). Solution: Apify actor `getmediumdata/mobile-de-scraper` at **$0.0015
per listing result** — confirmed working, returns clean structured JSON including
CO2, price, firstRegistration, fuel, power, manufacturer, model.

The actor accepts individual listing URLs (slug format and id-only format) as well
as search URLs. For PPMV on-demand use, we send one listing URL and get one result.

**Confirmed working input format (tested manually):**
Actor ID: `ivanvs/mobile-de-scraper`. Input must include `maxRecords` (minimum 10).
Always take `items[0]` from the response — we only need one result per on-demand fetch.

---

## What to build

### 1. Config — `app/core/config.py`

Add to `Settings`:

```python
apify_api_token: str = ""
apify_mobile_de_actor_id: str = "ivanvs/mobile-de-scraper"
apify_call_timeout_seconds: int = 60
listing_cache_ttl_hours: int = 24
daily_apify_budget_calls: int = 200        # safety ceiling, degrade gracefully above
```

Add to `.env.example`:
```
APIFY_API_TOKEN=
APIFY_MOBILE_DE_ACTOR_ID=getmediumdata/mobile-de-scraper
LISTING_CACHE_TTL_HOURS=24
DAILY_APIFY_BUDGET_CALLS=200
```

---

### 2. Apify fetcher — new `app/scraping/fetchers/apify_mobile_de.py`

Calls the Apify actor synchronously (run-and-wait), returns a single `ListingData`.

```python
import httpx
from app.core.config import get_settings
from app.core.exceptions import ScrapingError
from app.scraping.schemas import ListingData

APIFY_RUN_SYNC_URL = (
    "https://api.apify.com/v2/acts/{actor_id}/run-sync-get-dataset-items"
    "?token={token}&timeout={timeout}&format=json"
)

async def fetch_listing(url: str) -> ListingData:
    s = get_settings()
    if not s.apify_api_token:
        raise ScrapingError("APIFY_API_TOKEN not configured")

    endpoint = APIFY_RUN_SYNC_URL.format(
        actor_id=s.apify_mobile_de_actor_id,
        token=s.apify_api_token,
        timeout=s.apify_call_timeout_seconds,
    )
    payload = {"urls": [{"url": url}], "maxRecords": 10}

    async with httpx.AsyncClient(timeout=s.apify_call_timeout_seconds + 10) as client:
        resp = await client.post(endpoint, json=payload)

    if resp.status_code != 200:
        raise ScrapingError(f"Apify returned {resp.status_code} for {url}")

    items = resp.json()
    if not items:
        raise ScrapingError(f"Apify returned empty dataset for {url}")

    return _parse(items[0], url)


def _parse(item: dict, source_url: str) -> ListingData:
    """Map Apify actor output to our internal ListingData schema."""
    props = item.get("properties", {})
    price = item.get("price", {})

    # firstRegistration is "MM/YYYY" — parse to date
    first_reg = None
    raw_reg = props.get("firstRegistration") or item.get("attributes", {}).get("First Registration")
    if raw_reg:
        try:
            month, year = raw_reg.split("/")
            from datetime import date
            first_reg = date(int(year), int(month), 1)
        except (ValueError, AttributeError):
            pass

    # power: "150 kW (204 hp)" → extract kW
    power_kw = None
    raw_power = props.get("power", "")
    if raw_power and "kW" in raw_power:
        try:
            power_kw = float(raw_power.split("kW")[0].strip().split()[-1])
        except (ValueError, IndexError):
            pass

    # CO2: "132 g/km" → extract float
    co2 = None
    raw_co2 = props.get("co2Emission")
    if raw_co2:
        try:
            co2 = float(raw_co2.replace("g/km", "").strip())
        except ValueError:
            pass

    # fuel type normalisation → our FuelType enum
    raw_fuel = (props.get("fuelType") or "").lower()
    fuel = _normalise_fuel(raw_fuel)

    return ListingData(
        source_url=source_url,
        listing_id=str(item.get("id", "")),
        brand=item.get("manufacturer"),
        model=item.get("model"),
        variant=item.get("subTitle"),
        price_eur=float(price.get("amount")) if price.get("amount") else None,
        first_registration=first_reg,
        mileage_km=_parse_mileage(props.get("milage")),
        power_kw=power_kw,
        fuel_type=fuel,
        co2_g_km=co2,
        emission_class=props.get("emissionClass"),
        scraper="apify_mobile_de",
    )


def _normalise_fuel(raw: str) -> str | None:
    """Map mobile.de fuel strings to our FuelType values."""
    if not raw:
        return None
    if "diesel" in raw:
        return "diesel"
    if "petrol" in raw or "benzin" in raw:
        return "petrol"
    if "electric" in raw or "elektro" in raw:
        return "electric"
    if "hybrid" in raw:
        return "hybrid"
    return raw


def _parse_mileage(raw: str | None) -> int | None:
    if not raw:
        return None
    try:
        return int(raw.replace(",", "").replace(".", "").replace("km", "").strip())
    except ValueError:
        return None
```

---

### 3. Result cache — `app/db/models.py`

Add two tables (auto-created by startup hook in `app/main.py` — no Alembic needed):

```python
from datetime import datetime
from sqlalchemy import JSON, String, Float, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base

class ListingCache(Base):
    __tablename__ = "listing_cache"
    id: Mapped[int] = mapped_column(primary_key=True)
    cache_key: Mapped[str] = mapped_column(String, unique=True, index=True)
    # e.g. "mobile.de:459632333"
    payload: Mapped[dict] = mapped_column(JSON)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, index=True)

class ApifyEvent(Base):
    __tablename__ = "apify_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    site: Mapped[str] = mapped_column(String)          # "mobile.de"
    listing_id: Mapped[str] = mapped_column(String, nullable=True)
    source: Mapped[str] = mapped_column(String)        # "cache" | "apify"
    status: Mapped[str] = mapped_column(String)        # "success" | "failed" | "cap_reached"
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, index=True)
```

---

### 4. Budget guard — `app/core/limits.py`

```python
from datetime import datetime, date
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.db.models import ApifyEvent
from app.core.config import get_settings

async def apify_budget_remaining(db: AsyncSession) -> bool:
    """Returns True if under daily budget, False if cap reached."""
    s = get_settings()
    today_start = datetime.combine(date.today(), datetime.min.time())
    result = await db.execute(
        select(func.count()).where(
            ApifyEvent.source == "apify",
            ApifyEvent.created_at >= today_start,
        )
    )
    count = result.scalar() or 0
    return count < s.daily_apify_budget_calls
```

---

### 5. Wire into `/calculate` — `app/calculate/router.py`

**Remove** `"mobile.de"` from `_UNSUPPORTED_SITES`.

In the `calculate()` handler, after site detection, add the mobile.de branch:

```python
from datetime import datetime, timedelta
from sqlalchemy import select
from app.db.models import ListingCache, ApifyEvent
from app.scraping.fetchers import apify_mobile_de
from app.core.limits import apify_budget_remaining
from app.core.config import get_settings

# Inside calculate() after site is detected as "mobile.de":

s = get_settings()

# Extract listing_id from URL for cache key
listing_id = _extract_mobile_de_id(url)  # see helper below
cache_key = f"mobile.de:{listing_id}" if listing_id else None

listing_data = None

# 1. Check cache
if cache_key:
    result = await db.execute(
        select(ListingCache).where(ListingCache.cache_key == cache_key)
    )
    cached = result.scalar_one_or_none()
    if cached:
        ttl = timedelta(hours=s.listing_cache_ttl_hours)
        if datetime.utcnow() - cached.fetched_at < ttl:
            listing_data = ListingData(**cached.payload)
            await _log_apify_event(db, "mobile.de", listing_id, "cache", "success", 0.0)

# 2. Budget check
if listing_data is None:
    if not await apify_budget_remaining(db):
        # Degrade gracefully — return needs_manual response
        return CalculateResponse(
            status="needs_manual",
            message="Dnevni limit automatskog dohvata je dostignut. Unesite podatke ručno.",
            parsed=ParsedFields(source_url=url),
        )

# 3. Fetch from Apify
if listing_data is None:
    try:
        listing_data = await apify_mobile_de.fetch_listing(url)
        # Upsert cache
        if cache_key:
            await db.merge(ListingCache(
                cache_key=cache_key,
                payload=listing_data.dict(),
                fetched_at=datetime.utcnow(),
            ))
            await db.commit()
        await _log_apify_event(db, "mobile.de", listing_id, "apify", "success", 0.0015)
    except ScrapingError as e:
        await _log_apify_event(db, "mobile.de", listing_id, "apify", "failed", 0.0)
        raise

# 4. Continue existing calculate flow with listing_data
# (catalogue match, PPMV engine — unchanged)
```

**Helper to extract listing ID from both URL formats:**

```python
import re
from urllib.parse import urlparse, parse_qs

def _extract_mobile_de_id(url: str) -> str | None:
    # id-only format: details.html?id=459632333
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    if "id" in qs:
        return qs["id"][0]
    # slug format: /auto-inserat/some-slug/459632333.html
    match = re.search(r"/(\d+)\.html", parsed.path)
    if match:
        return match.group(1)
    return None

async def _log_apify_event(db, site, listing_id, source, status, cost_usd):
    db.add(ApifyEvent(
        site=site,
        listing_id=listing_id,
        source=source,
        status=status,
        cost_usd=cost_usd,
        created_at=datetime.utcnow(),
    ))
    await db.commit()
```

---

### 6. `ListingData` schema check — `app/scraping/schemas.py`

Confirm these fields exist (add if missing):

```python
scraper: str | None = None          # which extractor produced this
emission_class: str | None = None   # e.g. "Euro6d-TEMP"
```

---

### 7. Tests — `tests/`

**`tests/test_apify_mobile_de.py`** — unit tests, no network:

```python
import pytest
from app.scraping.fetchers.apify_mobile_de import _parse, _extract_mobile_de_id

SAMPLE = {
    "id": 459632333,
    "manufacturer": "Audi",
    "model": "A5",
    "subTitle": "Sportback 40 TFSI*S LINE",
    "properties": {
        "firstRegistration": "03/2021",
        "power": "150 kW (204 hp)",
        "fuelType": "Petrol",
        "co2Emission": "132 g/km",
        "milage": "79,530 km",
        "emissionClass": "Euro6d-TEMP",
    },
    "price": {"amount": 29990, "currency": "EUR"},
}

def test_parse_fields():
    listing = _parse(SAMPLE, "https://suchen.mobile.de/auto-inserat/audi-a5/459632333.html")
    assert listing.brand == "Audi"
    assert listing.model == "A5"
    assert listing.price_eur == 29990.0
    assert listing.co2_g_km == 132.0
    assert listing.power_kw == 150.0
    assert listing.fuel_type == "petrol"
    assert listing.first_registration.year == 2021
    assert listing.first_registration.month == 3
    assert listing.mileage_km == 79530

def test_extract_id_slug():
    url = "https://suchen.mobile.de/auto-inserat/audi-a5-sportback/459632333.html"
    assert _extract_mobile_de_id(url) == "459632333"

def test_extract_id_query():
    url = "https://suchen.mobile.de/fahrzeuge/details.html?id=459632333&dam=false"
    assert _extract_mobile_de_id(url) == "459632333"
```

**Do not touch** `tests/test_ppmv_engine.py::test_audi_a5_regression` (€3,475.50).

---

### 8. Deploy

`.env` on VPS — add:
```
APIFY_API_TOKEN=your_token_here
```

No Dockerfile changes needed — no browser, no playwright install required for this
path. The Apify call is a plain HTTPS POST via httpx.

---

## Verification

1. `uv run pytest tests/test_apify_mobile_de.py` — green, no network
2. With `APIFY_API_TOKEN` set: `POST /calculate` with both URL formats → returns
   `ppmv_eur` (or clean `needs_manual` if CO2 missing from listing)
3. Second identical request served from `ListingCache` — no new Apify call, `ApifyEvent(source="cache")` row
4. Set `DAILY_APIFY_BUDGET_CALLS=0` → degraded manual response, no Apify call
5. Check `apify_events` table for correct `source`/`status`/`cost_usd`
6. Audi A5 regression still passes: €3,475.50

---

## Cost note

$0.0015/result. At 1,000 user requests/month with 24h cache hit rate ~60%:
~400 Apify calls × $0.0015 = **$0.60/month**.
