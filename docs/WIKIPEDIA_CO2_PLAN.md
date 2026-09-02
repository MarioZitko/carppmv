# Wikipedia CO2 Estimation Pipeline — Implementation Plan

> Status: **Phase 0 and Phase 1 implemented** (`app/wikipedia/`, CLI
> `python -m app.wikipedia.crawl`) and run for the 10 in-scope brands.
> Phases 2–5 are design only, not implemented. Supplements MASTER_PLAN_v7.md — does not
> replace the catalogue as the primary CO2 source. This fills the CO2 gap for
> vehicles not in the catalogue (or not yet ingested). No vehicle-age cutoff is
> assumed — coverage depends on what each individual Wikipedia article actually
> contains, discovered per-row during extraction, not decided upfront. See §0.

---

## 0. Ground rules (apply to every phase, non-negotiable)

- **`de.wikipedia.org` is the source** — best structured engine-spec table coverage,
  language of the article is irrelevant since only numbers/codes/dates are extracted.
- **Never auto-fills the tax calculation.** New `co2_source: "wikipedia_estimate"`
  value. When only this tier is available, `/calculate` still returns
  `manual_required` — the range is shown in the UI as a hint only
  ("we estimate 99–116 g/km for this engine — check your COC and enter the exact
  value"). This was decided explicitly and must not be silently relaxed later.
- **Null CO2 is a valid, expected outcome for any row, regardless of vehicle
  age — this is a per-row fact, not an age-based rule.** No assumption about
  which eras have CO2 data is baked into the pipeline anywhere. Phase 0/2 run
  against every resolved article the same way regardless of how old the car is;
  whether a given table has a CO2 column is discovered per-article, not decided
  in advance. (A small spot-check during planning found CO2 markers absent on a
  handful of 1980s Opel/Mazda articles, but this was not tested broadly enough
  to generalize — do not encode an age cutoff based on it. Some brands'
  German-Wikipedia editors maintain more thorough historical tables than others;
  let the data decide per row.) Extraction schema must allow `co2_min`/`co2_max`
  to be null. Validation must not flag null CO2 as an error. When null, the
  matching layer (Phase 5) returns "no Wikipedia estimate available," and the UI
  shows nothing — never an empty or misleading range.
- **Every stored row keeps its provenance**: raw wikitext snippet (the specific
  table, not the whole article) + `source_url` (article + section anchor). This is
  the audit trail for fixing a bad extraction later — same pattern as the
  catalogue's `source_url`.
- **LLM (DeepSeek V4 Flash via OpenRouter, matching the existing `llm_mapper.py`
  pattern) is used narrowly for two bounded sub-tasks only**: (a) section
  classification when mechanical fuzzy-matching fails, (b) wikitext table →
  structured JSON extraction. It is never used to estimate, guess, or fill a CO2
  value from general knowledge — only to structure what is literally present in
  fetched wikitext.
- **This whole pipeline is offline/batch**, same category as
  `app/data/catalogues/ingest.py` — not a live call in the `/calculate` request
  path. Phase 5's matching function reads only from your own Postgres table.

---

## Phase 0 — Crawl (mechanical, no LLM)

**Goal:** for each brand, find every model/generation article link, fetch and cache
its raw wikitext.

**Steps:**
1. Fetch brand article wikitext (`action=parse&prop=wikitext`).
2. Parse into sections (`mwparserfromhell`, `get_sections(levels=[2])`).
3. Identify the model-list section(s) using **fuzzy match**, not an exact
   whitelist: `"modell" in heading.lower()` (catches `Modelle`, `Modellübersicht`,
   `Modellprogramm`, `Pkw-Modellüberblick`, etc. — confirmed necessary; an exact
   whitelist missed Volvo's actual heading in testing).
4. Within matched section(s), extract candidate model links:
   - `{{Hauptartikel|...}}` template params (primary signal where present)
   - plain `[[wikilinks]]` filtered to `title.startswith(brand_prefix)`
   - exclude `Datei:`/`File:`/`Kategorie:` namespace links
5. **Normalize `#anchor` links.** A link like `Opel Agila#Agila A (Typ 0HAF68,
   2000–2007)` means the generation's data lives as a *section* of a shared article
   (`Opel Agila`), not a separate page. Store `(base_article_title, anchor_or_null)`
   as a pair — fetch the base article once, and Phase 2 will operate on the
   relevant section when an anchor is present, on the whole article's tables
   otherwise.
6. Dedupe on `(base_article_title, anchor)`.
7. Fetch and cache full wikitext for each resulting `base_article_title` (one
   fetch per unique article, even if multiple anchors point into it).

**Batching (required structure, not optional):** batch unit is **one brand**, sourced
from your catalogue's distinct `brand` values. For each brand: skip if already
fully crawled (resumability check), otherwise crawl and cache, then sleep the
throttle delay before the next brand's first request. This gives natural
stop/resume checkpoints — e.g. run only Mercedes + Kia first, review output,
continue with the rest — rather than committing to a full-scope run blind.
Phase 2 batches the same way, reading cached wikitext per brand rather than
re-fetching.

**Rate limiting & resumability (required — confirmed necessary in testing: a 429
was hit after roughly a dozen rapid unthrottled calls):**
- Throttle: minimum delay between requests (start at ~0.5–1s, adjust if still
  throttled), exponential backoff on HTTP 429 (e.g. 3 retries, delay doubling from
  5s).
- Idempotent/resumable: before fetching any article, check whether wikitext for
  that exact title is already cached in the DB/cache table; skip if present. This
  is what makes it safe to kill and restart a multi-hour crawl over ~43 brands ×
  dozens–100+ models each (easily 1,000–3,000+ requests total) without re-fetching
  everything from scratch.
- Log every fetch outcome (`ok | not_found | error`) per article title — needed for
  Phase 1's trigger condition and for auditing coverage afterward.

**Storage (new table, working name `WikipediaRawArticle`):**
```
brand, article_title, anchor (nullable), wikitext (raw), fetched_at, fetch_status
```

**Explicit trigger condition for escalating to Phase 1 (must be a fixed rule, not
left to inference):**
> A brand escalates to Phase 1 if step 3's fuzzy section match returns zero
> sections, OR returns a matched section containing fewer than 5 qualifying
> wikilinks after filtering. (Adjust the "5" threshold after seeing real Phase 0
> output across a handful of brands — but it must be a stated number, not a vague
> "if it looks wrong.")

**Scope decision (must be made before running, not left implicit):**
Recommend starting with your top 5–10 brands by catalogue row volume (Mercedes,
Kia, Renault, Opel, Land Rover, Fiat, Jaguar, Volvo, Dacia, Hyundai — ~63% of your
5,091 catalogue rows) rather than all 43 at once. Confirm this scope explicitly in
the Claude Code prompt; don't let it default to "everything."

---

### Phase 0 HTTP client requirements (amendment — applies to every request)

Implemented in `app/wikipedia/client.py`.

- **User-Agent is mandatory**, format
  `kalkulatoruvoza-co2-crawler/1.0 (https://kalkulatoruvoza.com; <contact>) httpx/<version>`.
  A default library UA is routed into a stricter rate-limit tier by Wikimedia —
  this is policy, not etiquette.
- **Authenticate** with the Special:BotPasswords credentials
  (`WIKI_BOT_USERNAME` / `WIKI_BOT_PASSWORD`) before crawling: it raises the
  concurrency allowance to 3 (from 2 anonymous) and the per-second ceiling.
  `action=clientlogin` is attempted first; de.wikipedia rejects bot passwords
  there (`Cannot log in as MarioZitko@co2-crawler using this method`), so the
  working path is the legacy `action=login`, which is what bot passwords are
  documented for. Both are tried, and the session is verified with
  `meta=userinfo` — a silently-anonymous session would run the whole crawl at
  the lower tier without saying so.
- **Concurrency 3 is a hard ceiling**, not a perf knob. Each worker waits
  ~0.5–1 s between its own requests (enforced globally as one shared minimum
  gap of `delay / concurrency`, so the aggregate rate holds regardless of task
  scheduling).
- **Batch the "does this title exist / where does it redirect" question** with
  `action=query&titles=A|B|C` (pipe-separated, 50 titles per call). The
  per-article `action=parse&prop=wikitext` fetch does not batch and stays one
  request per unique article.
- **HTTP 429**: 3 retries, delay doubling from 5 s, honoring `Retry-After`
  when present.

---

## Phase 1 — LLM section classification (fallback only, DeepSeek V4 Flash)

**Trigger:** only for brands flagged by Phase 0's explicit trigger condition above.
Most brands should not need this if Phase 0's fuzzy match works — this is the
exception path, not the primary path.

**Input:** the brand article's list of `==level-2 heading==` strings.
**Prompt:** ask which heading(s), if any, list car models (enum-constrained: must
pick from the literal heading strings present, or return "none" — same
hallucination guard as `llm_mapper.py`'s column-mapping constraint).
**Output:** re-run Phase 0 steps 4–7 against the LLM-identified section instead of
the fuzzy-matched one.

**If the LLM also returns "none":** flag the brand for manual review, do not
retry automatically, do not fall back to guessing. Log to a review queue.

---

## Open items from the actual Phase 0 run (2026-09-02)

Findings from the first real crawl of the 10 in-scope brands. Read before
building Phase 2.

1. **Brand articles are traps — the bare marque name is often wrong.**
   "Fiat" is a disambiguation page and "Fiat S.p.A." (the holding company) has
   no model list at all; "Mercedes-Benz" is a vehicle-TYPE routing table
   (Pkw/Vans/Lkw/Bus) that yields 7 category articles and zero models. The
   working articles are `Fiat (Marke)` and `Mercedes-Benz-Pkw`. Both are now in
   `brand_articles.py`'s candidate lists; expect the same class of problem when
   extending scope beyond these 10 brands.

2. **Short-name links.** German model tables frequently link a model by its
   short name (`[[Twingo]]`, `[[Captur]]`, `[[Oroch]]`), which the plan's
   `title.startswith(brand_prefix)` filter drops. The crawler now resolves
   those candidates and keeps only the ones whose *resolved* title carries the
   brand prefix — the redirect is the filter, so table neighbours like
   "Nissan Navara", "Dacia Duster" and "Limousine" still stay out. This
   recovered 47 modern Renault models (Twingo I–IV, Mégane I–IV, Captur,
   Koleos, Laguna…), i.e. essentially all of Renault's catalogue-relevant era.
   The escalation trigger still uses the pre-rescue mechanical count, exactly
   as specified.

3. **Index articles are followed one hop (Hyundai).** Hyundai's "Modelle"
   section lists commercial vehicles inline but delegates passenger cars to
   `{{Hauptartikel|Personenwagen von Hyundai}}`, so it passed the escalation
   trigger (10 links > 5) while holding no i30/Tucson/Kona. The crawler now
   follows a `{{Hauptartikel}}` target that is not itself a brand-prefixed
   model article, and harvests that index's model links — **one hop only**,
   and never into a target that IS a model article. This is narrow by
   construction: across all ten brands exactly one target qualifies, so the
   rule cannot add noise elsewhere. Hyundai went 9 → 70 rows (+62 links).

4. **How much of the corpus actually carries CO2** (measured after the crawl,
   902 rows / 850 ok / 758 unique articles):
   - 295 of 758 articles contain **no wikitext table at all** (e.g. the German
     "Kia Picanto" article is 5 kB of prose) — nothing for Phase 2 to extract
     regardless of CO2.
   - Of the 1,128 tables that do exist, **344 (30%) contain a CO2 token**. The
     rest are genuine engine-spec tables (Motortyp / Hubraum / max. Leistung /
     Drehmoment) that simply have no emissions row — "Kia Niro" and "Kia
     Carnival" are typical. This is exactly the "null is a valid outcome" case
     §0 predicted, confirmed empirically rather than assumed.
   - Sanity-checked against known-modern articles: 11 of 12 (XC60, Astra K,
     Baureihe 205, Captur I, Sportage, 500L, Duster, Discovery Sport, Corsa E,
     Twingo, XC90) do carry CO2; "Jaguar XE" does not. So the low percentage is
     corpus composition, not a detection failure.

5. **The "5 qualifying links" threshold did not misfire, but it is not
   sufficient on its own** — Hyundai passed it with 10 links while missing its
   entire passenger-car range (item 3). A useful complement when scope
   widens: compare link count against the brand's catalogue row count and flag
   the outliers, rather than raising the flat threshold.

6. **Table ORIENTATION is not fixed — this changes Phase 2's design.** The
   `Audi A5 F5` article the Phase 2 section was written against is
   *transposed*: each attribute is a row header (`! Bauzeitraum`,
   `! Hubraum`, `! CO<sub>2</sub>-Emission, kombiniert`) and each engine
   variant is a COLUMN. That is the minority shape. Across the corpus's 381
   CO2-bearing tables: **230 (60%) are normal** (one row per variant, e.g.
   "Kia Carens"), **147 (38%) are transposed** (e.g. "Kia Cadenza", "Kia K9"),
   4 have no header cells at all. An extractor tuned only on the Audi example
   would silently mis-parse the majority — the prompt must state that either
   orientation is possible and that the model should determine which it is
   looking at.

7. **One table yields MANY variants, so the Phase 2 schema must be an array.**
   The schema block below shows a single JSON object, but a transposed table
   has one variant per column and a normal table one per row — the A5 F5's
   first table alone carries several. The plan already implies multiplicity
   ("dual-fuel rows split into multiple output rows"); make it explicit, e.g.
   `{"variants": [ {…}, {…} ]}`, with the per-variant object being the schema
   as written.

8. **Not every table is an engine table.** The "Kia Niro" article's first
   table is a Euro NCAP crashtest table; others are sales figures. The
   per-table CO2 prefilter (item 4) removes these for free, which is a second
   reason to apply it beyond saving calls.

9. **`filter_tags(matches=lambda t: t.tag == "table")` works as specified** —
   verified against cached wikitext, it finds exactly the same tables as a
   `^\{\|…^\|\}` scan, with no nesting issues. No change needed there.

10. **Rate limiting was a non-issue.** 562 requests for the first full pass, 3.6
   minutes wall-clock, **zero 429s and zero transport errors** at concurrency 3
   with a 1 s per-worker delay and an authenticated session. The plan's
   estimate of 10–20 minutes for this scope was conservative.

---

## Full-scope expansion (2026-09-02) — findings

Scope is now **every catalogue brand except `EXCLUDED_BRANDS`** (BAIC,
Forthing, Foton, Isuzu, Lynk & Co — confirmed as exact `catalogue.brand`
values, 28 rows between them, not the ~20 this doc originally estimated).
That is 38 brands / 159,415 catalogue rows. `Suzuki` is in scope with a single
catalogue row: it was never on the exclusion list, so it stays, but it is the
one brand whose crawl cost clearly exceeds its catalogue value.

A **dry-run pass over all 38 brands before any writes** is now the standard
procedure — it costs ~175 requests and 2 minutes and caught every problem
below before a single row was stored. Do this when adding brands.

1. **Four more brand-article traps**, same class as the original Fiat and
   Mercedes-Benz cases. The bare marque name keeps being the wrong article:
   - `BMW` is the corporate article (15 links, current range only) →
     **`BMW (Automarke)`**, the marque article with per-era Modellgeschichte
     sections (160 links).
   - `Mini (Automarke)` is brand history with ~2 model links →
     **`Mini (BMW Group)`** (13 links).
   - `MG (Automarke)` does not exist and `MG Rover Group` redirects to
     **the Rover article** — the first mapping silently crawled Rover. The
     marque is split in two: `MG (chinesische Automarke)` (modern, what the
     catalogue's 162 rows actually are) and `MG (britische Automarke)`
     (historical).
   - `Maserati`'s "Serienfahrzeuge" section has 4 links →
     **`Liste von Maserati-Serienfahrzeugen`** (54).

2. **`BrandArticle.extra_articles`** was added for MG: a marque whose range is
   split across two articles that don't link to each other. Each article runs
   through section-matching, escalation and the one-hop independently, and the
   resulting links are unioned.

3. **The one-hop index rule did NOT stay narrow at full scope.** At ten brands
   exactly one target qualified; at 38 it began following
   `Konzeptfahrzeuge von Volkswagen` (+34 show cars, never homologated, in no
   customs catalogue) and `Liste der Suzuki-Motorräder` (**+141 motorcycles** —
   PPMV is a car tax), plus Citroën↔DS cross-following that would file each
   marque's models under the other's brand. Two guards were added: a denylist
   of non-passenger-car index categories
   (`sections._INDEX_TITLE_DENYLIST`) and a rule that an index target may not
   be another mapped brand's own article. After both, the rule is back to
   exactly one firing across 38 brands (Hyundai), and 188 junk links are gone.
   **Re-check this whenever brands are added — narrowness is not a property
   the rule keeps for free.**

4. **Phase 1 is not deterministic, and that had to be fixed.** Two consecutive
   dry-runs at temperature 0 gave different answers for Cupra on identical
   input: once `Fahrzeugmarke Cupra` (its complete 5-model lineup), once
   "none" → review queue. With seven brands escalating, the review queue was
   not reproducible between runs. `app/wikipedia/section_store.py` now
   persists verdicts to `section_classifications.json`, keyed by
   (brand, article, heading list) — the same build-once-artifact pattern as
   `catalogue/mapping_store.py`. **Only non-empty verdicts are stored**: a
   cached "none" would freeze a brand out of coverage on one flaky call,
   whereas an empty answer goes to the review queue and is retried next run.

5. **Phase 1's prompt needed German heading vocabulary.** It rejected Nissan's
   `Verkaufsbezeichnungen` as "naming conventions" while accepting Toyota's
   identical `Verkaufsbezeichnungen (Mitteleuropa)` — Nissan lost 139 model
   links to that. The prompt now names the wordings that ARE model
   enumerations in German auto articles (Verkaufsbezeichnungen,
   Typenbezeichnungen, Produktpalette, Produktlinien, Serienfahrzeuge,
   Fahrzeuge, Personenwagen, "Fahrzeugmarke X", "Auflistung" in a list
   article, and era/class-split headings). This recovered Nissan 0→140,
   Maserati 4→54, MG 0→56, Cupra 0→5.

6. **`<gallery>` captions were invisible to the link extractor — a real
   coverage bug.** mwparserfromhell treats an extension tag's body as raw
   text, so `filter_wikilinks()` never saw
   `<gallery>Seat Ibiza.jpg|[[Seat Ibiza V]] (seit 2017)</gallery>`. Seat
   lists its entire production range that way: the crawl stored 8 articles
   (concept cars and race cars — Bolero, IBE, Tribu, Leon WTCC) for a brand
   with **8,091 catalogue rows**, and the "Modelle" heading matched so nothing
   escalated. `sections._iter_wikilinks` now re-parses each gallery body.
   Seat went 8 → 48 articles (Ibiza I–V, Leon I–IV, Toledo I–IV, Ateca,
   Arona, Tarraco, Mii, Altea, Exeo). Worth remembering that this failure was
   invisible to every existing signal — no error, no escalation, no empty
   result, just a plausible-looking wrong answer.

7. **Escalation rate at full scope: 7 of 38 brands** (Toyota, Mercedes-Benz,
   Peugeot, Nissan, Maserati, Cupra, MG) — Phase 1 remains the exception path
   the plan intended, not the primary one. All seven resolved; the review
   queue is empty.

---

## Phase 2 — LLM table extraction (DeepSeek V4 Flash)

**Input:** for each cached article (Phase 0), extract wikitext tables
(`mwparserfromhell`, `filter_tags(matches=lambda t: t.tag == 'table')` or
equivalent) — scoped to the relevant section when an anchor was recorded in Phase
0, otherwise the whole article.

**Granularity: one LLM call per table**, not per article. Some articles contain
multiple tables (e.g. separate Otto/Diesel tables per the pasted Audi A5 example)
— each gets its own call, its own schema-constrained output, its own provenance
record. This keeps prompts small and the schema clean; do not batch multiple
tables into one call.

**Schema (strict JSON, all fields except the identifying ones nullable):**
```json
{
  "engine_code": "string | null",
  "production_start": "YYYY-MM | null",
  "production_end": "YYYY-MM | null",
  "displacement_cc": "number | null",
  "power_kw": "number | null",
  "fuel_type": "diesel | petrol | null",
  "co2_min": "number | null",
  "co2_max": "number | null"
}
```
- `fuel_type` is not always a table column — it's often only inferable from the
  section heading (Ottomotoren/Dieselmotoren) above the table, per the pasted
  example. Pass that heading into the prompt as context, don't expect the table
  itself to always state it.
- Dual-fuel rows (e.g. the g-tron example: separate CO2 for Super vs Erdgas) split
  into multiple output rows, not one row with two numbers crammed together.
- **`co2_min`/`co2_max` null is a valid, expected output** — do not prompt the
  model to infer or estimate a value if the table doesn't have one. Explicitly
  instruct: "if no CO2 figure is present in this table, return null — do not
  estimate."

**Output storage:** each extracted row stores the schema fields **plus** the raw
wikitext of the source table and the source article URL/anchor (§0 non-negotiable
requirement) — this is what makes a bad extraction traceable and fixable later
rather than silently poisoning downstream matches.

---

## Phase 3 — Mechanical validation (no LLM)

Run on every Phase 2 output row before it's eligible for upsert:
- `co2_min <= co2_max` when both present
- plausible bounds: reject/flag anything outside a sane range (e.g. negative, or
  above ~500 g/km) as a likely extraction error, not a real value
- `power_kw` parses as a positive number when present
- `production_start <= production_end` when both present (or `production_end`
  null/ongoing is fine)
- **Null CO2 passes validation cleanly** — it is not an error condition (§0)

Rows failing these checks go to a review queue (flagged, not silently discarded
and not silently inserted) — same "confirm unless certain" posture as your
existing catalogue matcher.

---

## Phase 4 — Upsert into `WikipediaEngineData`

Same batch-sorted-upsert pattern as `app/data/catalogues/ingest.py` (sort by
unique-constraint columns before insert, to avoid Postgres deadlocks under
concurrent writes).

**Schema:**
```
brand, model_article_title, engine_code, production_start, production_end,
displacement_cc, power_kw, fuel_type, co2_min, co2_max,
source_url, source_wikitext_snippet
```
**Unique constraint:** `(brand, model_article_title, engine_code, production_start)`

---

## Phase 5 — Matching function

`resolve_co2_from_wikipedia(brand, model, fuel, power_kw, date) -> {co2_min,
co2_max, source_url} | None`

This is a **new, separate matching subsystem** from `catalogue/matching.py` — same
general shape (fuzzy filter → score → accept/reject policy) but different
disambiguators, since Wikipedia rows are keyed by engine spec, not by variant text.
Do not reuse `catalogue/matching.py`'s tuning constants as-is; they were tuned for
a different data shape (customs variant text vs. engine-spec numeric matching).

**Required before this phase is built, not left implicit** (per your own
CLAUDE.md's warning that a wrong auto-picked value "silently corrupts the whole
tax result"):
- Explicit disambiguator list and priority order (likely: brand exact match
  (hard filter) → production date range contains vehicle's registration date
  (hard filter) → power_kw proximity → displacement_cc proximity → fuel_type
  match)
- Explicit `ACCEPT_SCORE` / `ACCEPT_MARGIN`-equivalent constants, with the same
  "confirm unless certain" policy: return null result (not a guess) when no
  candidate is clearly best
- Return the CO2 **range**, never collapse to a point value, and always attach
  `source_url` so the UI hint can link back to the Wikipedia article

**Design as a standalone, directly-callable function** (not tightly coupled to
the batch ingestion script) — this keeps the door open to later calling it live
on a catalogue-match cache-miss, without a rebuild, per the earlier discussion
of batch-now/live-later architecture. Not required for this build, just don't
architect it in a way that forecloses it.

---

## Estimated time & cost

**Time (Phase 0 crawl, dominated by Wikipedia API throttling, not compute):**

| Scope | Est. article fetches | Est. wall-clock time |
|---|---|---|
| Top 10 brands by catalogue volume | ~500–1,000 | ~10–20 minutes |
| All 43 brands | ~2,000–4,000+ | ~30–60+ minutes |

Run as a background batch job (per the batching structure above), not something
to wait on synchronously. Actual time depends heavily on how often Wikipedia's
API throttles (a 429 was hit after roughly a dozen rapid unthrottled calls in
testing) — the resumability requirement exists specifically so a slow or
interrupted run isn't costly to restart.

**Cost (DeepSeek V4 Flash via OpenRouter, Phase 1–2 only — Phase 0 crawl itself
is free, no LLM involved):**

Rates as of this writing are roughly $0.10/M input, $0.20/M output tokens on
OpenRouter (confirm live pricing before running — this has moved noticeably in
recent months). Phase 1 (section classification fallback) is negligible — small
prompts, only runs for the minority of brands that need it. Phase 2 (table
extraction) is the real volume, roughly 1,000–2,000 tokens in / ~200 tokens out
per table.

| Scope | Est. table-extraction calls | Est. cost |
|---|---|---|
| Top 10 brands | ~800–1,500 | **~$0.20–0.40** |
| All 43 brands | ~3,000–6,000 | **~$0.70–1.50** |

**Bottom line: LLM spend is a few dollars at most, not a real budget constraint.**
The bottleneck is wall-clock time from Wikipedia's own rate limiting, not cost.

---

## Recommended handoff sequencing (do not hand off all 5 phases in one prompt)

1. **Phase 0 + 1 first.** Review actual crawl coverage/output before proceeding —
   this is where unknowns are highest (per-brand section-naming variance).
2. **Phase 2 + 3 next**, once real crawl data exists to test extraction against
   (don't build/tune the extractor against only the Audi example already seen).
3. **Phase 4 + 5 last**, with Phase 5's matching constants designed and reviewed
   explicitly before shipping — this is the phase most capable of silently
   producing wrong output if rushed.

---

## Explicitly out of scope for this pipeline

- Price data (Wikipedia doesn't have usable listing price data — dropped from the
  original idea)
- No blanket age cutoff exists in this pipeline. Individual old vehicles may or
  may not have Wikipedia CO2 data — this is discovered per-article in Phase 2,
  not assumed in advance. Vehicles whose specific table lacks CO2 remain
  manual-entry-only for that field, same as today, with no misleading "estimate"
  shown — but this applies row-by-row, not to a whole era of vehicles by default.
- Live/on-request Wikipedia calls — this is a batch pipeline into your own DB;
  Phase 5 never calls Wikipedia at request time
- Brands with near-zero catalogue volume (BAIC, Forthing, Foton, Isuzu, Lynk & Co
  — ~20 rows combined) — not worth scoping into Phase 0 initially
