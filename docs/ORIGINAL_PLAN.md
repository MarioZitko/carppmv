# Master Plan v7 — Croatian Car-Import Platform (consolidated, supersedes v1-v6)

> **HISTORICAL — the original build-order decision record (was `Car Import
> Taxes Plan.md` at the repo root). Kept for the *why*, not the *what*: the
> build order, the deferral calls and the scraping-feasibility findings still
> explain how the project got its shape.**
>
> Its current-state claims are out of date — mobile.de moved from Playwright
> Firefox to an Apify actor, and catalogue ingestion is no longer deferred.
> For where things actually stand, see [PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md).

> This is the single authoritative doc. Delete MASTER_PLAN.md through v6, PPMV_app_context.md, and the scraping-feasibility doc from the project — everything confirmed in them is folded in below.

---

## 0. Build order (decided)

**Build PPMV calculator first.** Single-URL on-demand mode only. No sweeps, no Apify, no catalogue ingestion yet — those come later and are intentionally deferred (see §6).

---

## 1. Architecture (unchanged from v3, now finalized)

One Data Service backend (Postgres, scrapers, FastAPI internal API, PPMV calc engine) + **one frontend app, two pages** (PPMV Calculator, Profitability) — collapsed per v6.

```
DATA SERVICE
 ├─ PPMV calc engine (tax tables, formula) ─── BUILD NOW
 ├─ catalogue ingestion (xlsx)            ─── deferred
 ├─ on-demand single-URL scraper           ─── needed for PPMV link input
 └─ sweep scrapers (nightly/weekly)        ─── deferred
        │
        ▼
   Postgres ── FastAPI ── Frontend (2 pages)
```

---

## 2. PPMV Calculator — build now

### 2.1 Input mode
Single link/URL paste (one listing) → on-demand scrape → extract spec fields → feed PPMV engine → show result + confidence.

### 2.2 Formula (verified)
```
PPMV(as new) = VN + PC + ON + EN
  PC = (as_new_price − value_bracket_lower) × value_bracket_percent
  EN = (CO2 − eco_bracket_lower) × rate_per_g_km
PPMV(used) = PPMV(as new) × depreciation_percent(months_old)   [Table 1]
```
NEDC (pre-2021 reg) vs WLTP (2021+ reg) selects which eco/value tables apply.

### 2.3 Tax tables — fully resolved (v4)
- Table 1 (depreciation, full 0–180mo + >180mo rule) — confirmed
- Tables 2 & 3 (NEDC eco, diesel/petrol) — confirmed
- Table 4 (post-2021 value brackets) — confirmed
- Tables 5 & 6 (WLTP eco, diesel/petrol) — confirmed
- Table 7 (motorcycle/ATV) — confirmed, likely out of scope
- 12 official worked examples from carina.gov.hr available as additional regression tests

**Action remaining:** hardcode as seed file (JSON/Python), not yet done.

### 2.4 Mandatory regression test
Audi A5 40 TDI, reg 17.08.2020, diesel, 136 g/km, 140 kW, declared 10.07.2025 (58 months) → **must produce exactly 3,475.50 EUR** (value 2,066.96 + eco 1,408.54; as-new 8,362.61 × 41.56%).

### 2.5 CO2 handling
Manual input required if not present/reliable on the scraped page. Never auto-fill or guess a CO2 value — show range/uncertainty instead, never false precision.

### 2.6 On-demand single-URL scraper (confirmed working, no Apify needed)
Live Playwright test results (v6 §4), per site:

| Site | Engine | Result |
|---|---|---|
| njuškalo | Chromium | 200, clean — free |
| AutoScout24 | Chromium | 200, clean — free |
| mobile.de | **Firefox** (Chromium blocked outright, any mode) | 200, clean — free |
| autobid.de | `httpx` (no browser needed) | 200, clean — free |

Engine choice should be per-site config (`engine: chromium | firefox | httpx`), not hardcoded — confirmed flippable behavior (Akamai tuned against Chromium specifically).

**Caveat:** this is "free and currently working," not "permanently guaranteed." Single human-paced fetches are a different risk profile than sweeps — don't scale on-demand into rapid/repeated request patterns.

---

## 3. Sweep scraping — deferred, not blocking PPMV build

Findings stand for when this is built later:

| Site | Sweep status | Method |
|---|---|---|
| autobid.de | Free, no wall | `httpx` |
| njuškalo | **Hard-blocked on first request** (ShieldSquare CAPTCHA, every page) | Apify (`memo23/njuskalo-scraper`, $1.69/1,000) |
| mobile.de | **Hard-blocked on first request** (Akamai behavioral JS challenge, unresolved under Playwright even with extended waits/reloads) | Apify (`memo23`-family) |
| AutoScout24 | Not yet sweep-tested; expect same pattern | Untested — no actor confirmed yet |

All bypass attempts without Apify failed for the sweep specifically: patchright fingerprint-patching, homepage warm-up with mouse simulation, plain wait-tuning. A plain residential proxy does **not** help — these are JS/behavioral challenges, not IP-reputation blocks. This is a separate, more heavily defended surface than detail/single-link pages on the same sites.

Sweep cadence (when built): weekly for all three protected sources, on-demand always available regardless.

---

## 4. Database schema (unchanged from v3, build when sweeps/catalogue start)

`catalogue`, `tax_tables`, `listings`, `listing_snapshots`, `price_history`, `model_stats`, `scrape_runs`, `sweep_config` — Postgres. Full column-level draft already exists in v2/v3 if needed later; not needed for the PPMV-only first build (PPMV only needs `tax_tables` + a one-off scraped record, not the full listings schema).

---

## 5. Infra

Hetzner CAX11 ARM VPS (2 vCPU/4GB/40GB, ~€6/mo). One browser at a time, sequential. Swap file as OOM guard. Sufficient for PPMV-only build; revisit only if sweeps are added later.

---

## 6. Deferred (explicitly not part of this build cycle)

- Apify 50-result cap bug — diagnose when sweeps are built
- njuškalo/mobile.de sweep cost at real segment scale — compute when target segment is chosen
- Target segment (models/age/price bounds) — decide when sweeps are built
- AutoScout24 actor/equivalent — find when sweeps are built
- Catalogue file inventory + ingestion pipeline — start once brand Excel files are uploaded

---

## 7. Legal & monetization (unchanged, reference only)

Publish only derived data, never raw listing mirrors. GDPR applies to stored private-seller PII regardless of seller type included. Ads won't cover hobby-scale traffic (~$1–15/mo); donation/affiliate links preferred if monetizing at all. Not blocking for PPMV build.
