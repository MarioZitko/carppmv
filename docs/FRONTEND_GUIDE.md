# Frontend implementation guide

No frontend code exists yet — this is a guide to build it, not a description
of something already there. Backend is a FastAPI app; nothing in this repo
assumes any particular frontend stack, so treat the framework choice below as
a recommendation, not a constraint.

Per [`Car Import Taxes Plan.md`](../Car%20Import%20Taxes%20Plan.md) §1, the
target is **one frontend app, two pages**:

1. **PPMV Calculator** — the page that exists to build now (backend is ready)
2. **Profitability** — backend (`app/profitability`) doesn't exist yet; build
   the page shell now if you want, but it has nothing real to call until
   that feature is built

---

## Recommended stack

Next.js + React + Tailwind (App Router, TypeScript). Reasoning: two pages,
no auth, no complex state — a framework's main value here is routing +
zero-config deploy (Vercel or any Node host), not architecture. Plain
HTML/JS is a legitimate alternative if you want zero build tooling — the API
contracts below don't change either way.

```
frontend/
  app/
    page.tsx              # PPMV Calculator (landing page)
    profitability/
      page.tsx              # Profitability (build shell now, wire up later)
    layout.tsx
  lib/
    api.ts                 # fetch wrappers for the 3 endpoints below
    types.ts                # TypeScript mirrors of the Pydantic schemas below
  components/
    UrlInputForm.tsx
    PPMVBreakdownCard.tsx
    ManualFieldsForm.tsx     # shown when co2_source === "manual_required"
```

Run the backend locally first (`uv run uvicorn app.main:app --reload --port 8000`)
and point the frontend at `http://localhost:8000` via an env var
(`NEXT_PUBLIC_API_BASE_URL`) — don't hardcode the URL, since it'll change at deploy.

---

## The API surface (only 3 endpoints exist)

### `POST /calculate` — the one the PPMV Calculator page actually calls

This is the whole pipeline in one call: scrape → catalogue fallback → tax
calc. Build the main page around this endpoint, not `/ppmv/calculate` or
`/scrape/listing` directly.

**Request**
```ts
{ url: string }  // must be a valid URL (Pydantic HttpUrl — malformed input is a 422)
```

**Response**
```ts
{
  ppmv_eur: number | null;        // null if calculation couldn't complete — check warnings
  parsed: {
    brand: string | null;
    model: string | null;
    variant: string | null;
    fuel_type: string | null;
    first_registration: string | null;
    power_kw: number | null;
    co2_g_km: number | null;
    price_eur: number | null;
    seat_count: number | null;
    is_new: boolean;
  };
  co2_source: "scraped" | "catalogue" | "manual_required";
  confidence: "high" | "low";
  warnings: string[];             // human-readable, safe to render directly
  debug: object | null;           // only populated when backend DEBUG=true — ignore in prod UI
}
```

**UI states to actually handle — this is the part that matters:**

- `ppmv_eur !== null` → show the result. Still render `warnings` if any exist
  (a successful calc can carry a caveat).
- `ppmv_eur === null` → **don't show an error page.** Show the `parsed` fields
  you do have, pre-filled, and let the user fill the rest manually — then let
  them re-submit through a manual-entry path (see below). This is the
  documented behavior, not a failure mode: [README.md §2.5](../README.md)
  is explicit that CO2 is "never guess" and a gap here is expected and normal
  for scraped listings with weak data.
- `co2_source === "manual_required"` → this is the single most important
  state to design for well. It means the scraper got a price but the
  catalogue matcher couldn't confidently resolve CO2. Surface a form
  pre-filled with everything in `parsed`, let the user type in CO2 (and
  correct anything else), and submit **to `POST /ppmv/calculate` directly**
  (not `/calculate` again — that endpoint takes raw specs, not a URL).
- 422 response → malformed URL or a domain none of the extractors handle.
  Show the validation message from the response body directly; don't invent
  a generic "something went wrong."
- 400 response → `mobile.de` specifically (see `_UNSUPPORTED_SITES` in
  `calculate/router.py`) — it's scrape-able standalone but not in the
  combined flow yet. Worth a specific message ("mobile.de isn't supported in
  the combined flow yet — paste price/CO2 manually") rather than a generic error.

### `POST /ppmv/calculate` — the manual-entry fallback

Use this directly when the user is filling in specs by hand (either from
scratch, or completing a partial result from `/calculate`).

**Request**
```ts
{
  price_eur: number;              // > 0
  co2_g_km: number;                // >= 0. Must be 0 for electric, > 0 otherwise (backend validates)
  fuel_type: "diesel" | "petrol" | "electric";
  first_registration_date: string; // "YYYY-MM-DD"
  declaration_date: string;         // "YYYY-MM-DD", must be >= first_registration_date
  eaer_city_range_km?: number;      // plug-in hybrid only — EAER *city* range, not WLTP combined
  seat_count?: number;               // 8 total → -50%, 9+ total → -75%
  is_camper?: boolean;                // -85%
  is_new_vehicle?: boolean;            // true = skip depreciation, pay full as-new PPMV
}
```

**Response**
```ts
{
  breakdown: {
    as_new_value_component: number;
    as_new_eco_component: number;
    as_new_total: number;
    vehicle_reduction_factor: number;  // 1.0 = none, 0.5 = 7+1 seats, 0.15 = camper, etc.
    depreciation_percent: number;
    months_old: number;
    final_ppmv: number;
  };
  co2_standard_used: "NEDC" | "WLTP";  // echo back — worth showing so the user can sanity-check
}
```

Validation errors here are real client-side bugs to prevent, not states to
design around — e.g. don't let the user submit `fuel_type: "electric"` with a
non-zero CO2 value; the backend will reject it with a 422 and there's no
graceful recovery UI for that, just don't send it.

**Render the full breakdown, not just `final_ppmv`.** The point of this tool
per the README is letting the user "cross-check against the official customs
declaration output" — collapsing it to one number defeats that.

### `POST /scrape/listing` — only needed if you build a "preview before calculating" step

Same scraping as `/calculate` internally, but returns the raw `ListingData`
without running the tax engine. Only worth calling separately if you want a
"here's what we found, confirm before we calculate" intermediate screen — not
required for a working v1.

Supports `mobile.de` (unlike `/calculate`). If you use this endpoint for a
preview step, mobile.de listings work here even though they can't go through
`/calculate` — you'd need to collect the manual fields and route to
`POST /ppmv/calculate` yourself for those.

---

## Page 1: PPMV Calculator — concrete flow

1. Single URL input, "Calculate" button.
2. `POST /calculate` with the URL.
3. Branch on the response per the "UI states" list above.
4. On success: render the full breakdown (see `PPMVBreakdown` fields), plus
   `parsed` as a collapsible "what we found" section, plus any `warnings`.
5. On `manual_required` / partial data: render an editable form pre-filled
   from `parsed`, submit to `/ppmv/calculate` on confirm.

Loading state matters here — scraping is a real network fetch to a third-party
site plus (sometimes) a catalogue DB query, not instant. Show a spinner with
something more specific than "loading" (e.g. "Fetching listing…") since it
can take a few seconds.

## Page 2: Profitability — shell only for now

Nothing to call yet (`app/profitability` is empty). If you build the page
now, per the plan this will eventually take a listing (or catalogue browse)
and show import cost vs. resale value — but don't invent the request/response
shape speculatively. Build the shell/nav and leave the content as a
"coming soon," or skip this page entirely until the backend exists.

---

## Things that will bite you if skipped

- **CORS**: FastAPI has no CORS middleware configured in `app/main.py` right
  now. If the frontend runs on a different origin (it will, in dev — Next.js
  on :3000 vs FastAPI on :8000), add `CORSMiddleware` to `main.py` before
  wiring up fetch calls, or every request will fail silently with an opaque
  browser network error that looks nothing like the real cause.
- **`HttpUrl` validation is strict** — a bare domain without `https://` will
  422. Validate/prefix on the client side before sending, or the user sees a
  cryptic Pydantic error for a typo as simple as a missing scheme.
- **Dates are plain strings, not ISO `Date` objects**, on the wire in both
  directions. Format as `"YYYY-MM-DD"` when sending; don't send a JS `Date`
  object directly through JSON.
- **`debug` field**: only populated when the backend runs with `DEBUG=true`.
  Don't build UI that depends on it being present.
