# Free single-link mobile.de parsing for PPMV — research & plan

> Status: **research/design only — not implemented yet.** This document captures the research
> and the agreed approach so we can pick it up in a future prompt.
>
> **UPDATE — the key unknown is resolved.** A live WhatsApp preview of the ID-only URL
> (`details.html?id=459632333`) shows mobile.de exposes the **EZ date in its OG metadata**:
> - `og:title` = `Audi A5 für 29.990 €`  → brand, model, **price**
> - `og:description` = `Gebrauchtfahrzeug • 79.530 km • 150 kW (204 PS) • Benzin • Automatik • 03/2021`
>   → condition, mileage, power, fuel, transmission, and **`03/2021` = first registration (EZ)**
>
> So the **pure free-forever path is viable** and Scrapingdog is very likely unnecessary. The
> only remaining check is that the **Facebook Graph API** (server-side `facebookexternalhit`)
> returns the same fields as the WhatsApp client-side preview — this is the first thing to test
> in code (Step 1).

## Plain-English glossary

- **EZ** = *Erstzulassung* = **first registration date** of the car. The most important field.
  Drives the NEDC↔WLTP cutoff (2021-01-01) and the depreciation months in PPMV.
- **OG** = **Open Graph** — the `<meta property="og:...">` tags in a page's `<head>`
  (`og:title`, `og:description`, `og:image`). They're what generate the little preview card
  when you paste a link into WhatsApp/Telegram/Facebook.
- **"OG scrape"** = fetching just those meta tags instead of the whole page. Cheap and small,
  but only contains whatever the site chose to put in them.

---

## Context & problem

We want a user to paste **one** mobile.de listing link and get a PPMV tax estimate. For that
we only need:
- **brand + model + variant** → for catalogue matching
- **first registration (EZ)** → most important
- **price** → required by the PPMV value component
- CO₂ / fuel → **not** taken from the listing; filled from our catalogue via the existing
  `find_match()` (`app/catalogue/matching.py`)

**Why the current approach fails on the VPS (and even locally):**
mobile.de is behind **Akamai Bot Manager**. The existing extractor
(`app/scraping/extractors/mobile_de.py`) drives Playwright **Firefox**, and it **only works with
a real, visible (headful) browser**. Headless fails **even locally**, and the Hetzner VPS can
only run headless. So the browser path is a **dead end for production**, not just "hard." We need
a non-browser method.

**Research verdict (checked exhaustively):** every fetch from generic/datacenter infrastructure
is Akamai-blocked — confirmed 4× live (plain HTTP → 403; Jina Reader → 403 "Access denied";
Microlink → fail; and `curl_cffi`, even impersonating Chrome's TLS fingerprint, can't clear
Akamai's JavaScript `_abck` sensor and gets flagged as a datacenter IP anyway). **The only free
channels that get through are crawlers mobile.de explicitly allowlists** — which is exactly why
link previews work but scrapers don't.

**Two URL formats exist and behave differently:**
1. `https://suchen.mobile.de/auto-inserat/{make-model-variant-slug}/{id}.html`
   → brand/model/variant are **in the slug** → free, zero network (pure string parsing; this
   cannot be "blocked" — it never hits the network).
2. `https://suchen.mobile.de/fahrzeuge/details.html?id={id}&...`
   → **opaque ID only**, no slug → brand/model must come from a fetched OG title. The URL-parse
   trick gives us nothing here.

**Confirmed via a live WhatsApp preview:** mobile.de **does** put the EZ date (and price,
mileage, power, fuel, transmission) into its OG metadata — even for the harder ID-only URL. The
only remaining unknown is whether the Facebook Graph API server-side crawler returns the same as
the WhatsApp client-side preview (Step 1 confirms this in code).

**Observed OG payload (real example):**
```
og:title       = "Audi A5 für 29.990 €"
og:description = "Gebrauchtfahrzeug • 79.530 km • 150 kW (204 PS) • Benzin • Automatik • 03/2021"
```
The description is a `•`-delimited list: `condition • mileage • power (PS) • fuel • transmission •
MM/YYYY(=EZ)`. Trivial to parse.

---

## The free options, researched and ranked

### Option A — Facebook Graph OG scrape  ·  free forever  ·  RECOMMENDED first
`GET/POST https://graph.facebook.com/?id={listing_url}&scrape=true&access_token={app_token}`
- Free **App Access Token** (`client_id|client_secret`, no app review). High rate limits.
- Facebook's crawler (`facebookexternalhit`) is allowlisted by mobile.de → gets through Akamai
  from Facebook's infrastructure. **Your VPS never touches mobile.de.**
- Works for **both** URL formats. Returns `og:title` / `og:description` / `og:image`.
- Cost: **$0, forever.** The OG fields include everything we need — make/model + price (title)
  and mileage/power/fuel/transmission/**EZ** (description), confirmed via WhatsApp. Step 1 just
  confirms the Graph API server-side returns the same.

### Option B — Telegram link-preview via a userbot  ·  free forever  ·  fallback
Telegram's servers fetch the URL server-side (whitelisted infra) to build previews.
- Method: MTProto `messages.getWebPagePreview` (via Telethon/Pyrogram). **Caveat, confirmed in
  the docs: "Only users can use this method"** — it needs a **full user account** (a phone
  number + a userbot session), **not** a plain Bot API token.
- Pros: free forever, another allowlisted server-side fetcher, good backup if Facebook's OG ever
  changes or rate-limits. Same title/description content as OG.
- Cons: more setup (phone-number-based session), running an automated userbot is a gray area vs
  Telegram ToS and can be rate-limited/flagged; same **EZ uncertainty** as Option A.
- Verdict: viable and truly free, but heavier and riskier to operate than Option A → keep as a
  **fallback**, not the primary.

### Option C — Scrapingdog (managed API)  ·  cheap  ·  likely NOT needed
Since the WhatsApp preview confirmed EZ is in the OG metadata, this is now only a **safety net**
for edge cases (e.g. a listing whose OG description omits the MM/YYYY, or if the Graph API ever
returns less than the client-side preview). Keep it as an optional configurable provider, not a
required dependency.
- Returns full HTML → reuse the **existing** BeautifulSoup spec-table parser in
  `mobile_de.py` (already reads *Erstzulassung* + price + German number formats).
- Pricing (researched): 1,000 free credits to start; **1 credit = plain HTML, 5–25 credits =
  JS-render / premium proxy** (Akamai needs premium ≈ 10–25 credits/request). Pay-as-you-go
  **$10 = 25,000 credits, non-expiring** → **≈ $0.004–0.01 per parse**. Free credits ≈ 40–200
  parses one-time (not a sustainable "forever free").

### Dead ends (do not pursue)
Google/Bing free search APIs (Bing's retired 2025) — and individual ads aren't reliably
indexed anyway (searching an exact ID returned only category pages); Google Cache (removed);
Jina/Microlink/allorigins/12ft (datacenter → blocked); self-hosted `curl_cffi` (needs
residential IP + can't run Akamai's JS sensor); official mobile.de Search/Seller API (paid
dealer account); the app's internal API (same Akamai + ToS + fragile).

### "Can Google Ads pay for Scrapingdog?" — the economics
Rough but honest math:
- **Parse cost** (only when the free OG path can't supply EZ): ~**$0.004–0.01** per listing.
- **Ad revenue**: automotive-niche EU RPM is quoted at ~$8–20 / 1,000 pageviews for content
  sites, but a *utility/calculator* page realistically earns **lower (~$1–5 RPM = $0.001–0.005
  per visit)** because dwell time and ad slots are limited.
- **Conclusion:** if each calculation ≈ one ad-bearing visit, ad revenue is **roughly
  break-even to modestly positive** against Scrapingdog — *thin margin, not a money-printer.*
  The big lever is: the more calculations that resolve on the **free** Facebook-OG path (EZ in
  OG, or make/model+price from OG with EZ typed once), the closer you get to **pure profit**.
  Practical stance: run free-first, use Scrapingdog only for the EZ gap, and add the
  login/paid tier before volume makes even $0.01/parse add up.

---

## Recommended architecture (build later)

A free-first chain that degrades gracefully and always produces a result:

1. **URL parse (free, always):** detect format; for slug URLs extract brand/model/variant; grab
   `listing_id` in both formats. New helper e.g. `app/scraping/extractors/mobile_de_url.py`.
2. **Facebook-OG fetch (free):** call the Graph scrape endpoint; parse `og:title` for
   brand/model + price and split `og:description` on `•` for mileage/power/fuel/transmission/**EZ
   (MM/YYYY)**. New pluggable provider; **your VPS never calls mobile.de directly.**
3. **Catalogue fill:** brand/model/variant + year → `find_match()` fills CO₂/fuel from our DB.
4. **EZ gap handling** (only if OG lacks EZ): either **manual one-field entry** (free, always
   works) or **Scrapingdog** full-HTML auto-read (reuses existing parser) — configurable.
5. **PPMV:** feed price + CO₂ + first_registration to `app/ppmv/engine.py` (unchanged).

Design as a **config-driven provider chain** (env `MOBILE_DE_FETCH_CHAIN`) so Facebook-OG /
Telegram / Scrapingdog / manual can be reordered without code changes. Keep the existing Firefox
provider for headful local debugging only; **exclude it from the VPS chain.**

Wiring points already located in the codebase:
- Remove `"mobile.de"` from `_UNSUPPORTED_SITES` in `app/calculate/router.py`; on missing
  price/EZ, return a structured **"needs manual input"** response (not a hard 400).
- Reuse `app/scraping/extractors/mobile_de.py` parsing; replace only the **fetch transport**.
- Reuse `find_match()` in `app/catalogue/matching.py` for CO₂/fuel.
- Frontend `frontend/app/page.tsx`: replace the hard "not supported" message with a minimal form
  **pre-filled** with auto-parsed fields, asking only for whatever's missing (usually EZ).

---

## Step 1 — Verification spike (must run before building)

The data question is already answered (WhatsApp preview shows EZ in OG). The remaining check:
**does the Facebook Graph API server-side crawler return the same OG fields as the client-side
preview?**
1. Create a free Facebook app → App Access Token.
2. Call the Graph scrape endpoint for **both** real URLs; inspect raw `og_object` /
   `og:title` / `og:description`:
   - `https://suchen.mobile.de/auto-inserat/audi-a5-3-0-tdi-s-tronic-quattro-korb/456793544.html`
   - `https://suchen.mobile.de/fahrzeuge/details.html?id=459632333`
3. Confirm the description still contains the `MM/YYYY` EZ + price.
- **Same as WhatsApp** → ship the **pure free-forever** path (Facebook-OG only; no paid API, no
  manual entry on the happy path).
- **Graph returns less / gets blocked** → fall back to the Telegram userbot (also server-side,
  free) or Scrapingdog for those cases; keep manual EZ entry as the last resort.

---

## WHAT YOU NEED TO DO / GIVE ME (to implement in a new prompt)

Bring these when you want me to build it, so I don't have to stop midway:

1. **Facebook App credentials** (for the free primary path):
   - Create an app at developers.facebook.com → copy **App ID** and **App Secret**
     (used as the App Access Token `APPID|APPSECRET`). Decide how they should be stored
     (`.env` var names).
   - *Or* just run the Step 1 spike yourself and paste the raw `og:title` + `og:description`
     for the two URLs above — that alone tells us whether EZ is available and unblocks the design.
2. **EZ gap fallback** (likely unneeded — OG already carries EZ; only for rare listings whose
   description omits the MM/YYYY): decide between "manual one-field entry" (100% free) and/or
   "Scrapingdog auto-read". If Scrapingdog: account + **API key** + storage + budget.
3. **(Optional) Telegram fallback:** if wanted, a phone number/session for a userbot (Telethon).
   Otherwise skip it.
4. **Confirm data flow expectations:** OK to auto-fill CO₂/fuel from our catalogue via
   `find_match()` on brand/model/variant/year? (Already agreed — confirm at build time.)
5. **Confirm the manual-fallback UX** on the frontend: a small pre-filled form asking for EZ
   (month/year) and/or price when the free path can't supply them.

With #1 (or just the pasted OG output) we can start; the rest only branch the fallback.

---

## Verification (when built)

- Step 1 spike is the critical experiment.
- Unit-test URL parsing against both real example URLs (slug + id-only).
- Integration test on the **VPS** (not just locally): both URLs → chain → assert
  brand/model/price/EZ populated or correctly flagged → PPMV computed. Cross-check the existing
  Audi A5 40 TDI regression in `tests/test_scraping_integration.py` (expected €3,475.50) where
  applicable.
- Confirm the Firefox provider is excluded from the VPS chain and Facebook-OG runs first at $0.
