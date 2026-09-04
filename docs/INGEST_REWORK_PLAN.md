# Catalogue Ingestion Rework — Implementation Plan (handoff)

> **STATUS (2026-07-05): code implemented.** All §5 changes below are in the
> tree (nullable brand/fuel/valid_from source columns + fallbacks; per-sheet
> enum schema `llm_mapper.USE_ENUM_SCHEMA`; normalized fingerprint +
> `_resolve_columns` pre-pass; timeout 20→60, concurrency 32→48). Plus two bug
> fixes found while doing it: `_parse_date` 2-digit-year handling (fixed the
> BAIC year-`0026` trash) and a non-positive-price drop (fixed a €0 Mercedes
> row); both trash rows were deleted from the live DB. New tooling:
> `scripts/verify_enum_schema.py` (pre-flight, ~$0) and
> `scripts/migrate_mapping_cache.py` (re-key OK, drop stale fails).
>
> **Remaining = the one paid build, run by the user:**
> 1. `.venv/bin/python -m scripts.verify_enum_schema` → expect PASS (if it
>    400s on enum, set `llm_mapper.USE_ENUM_SCHEMA = False` and re-run).
> 2. `.venv/bin/python -m scripts.migrate_mapping_cache`.
> 3. `.venv/bin/python -m app.data.catalogues.ingest --fresh`.
> 4. Validate (§6), then commit `column_mappings.json`.
>
> Refinement to §3's diagnosis: of the 646 cached rejections, **399 were
> `low_confidence`**, not hallucination — likely the same forced-invention
> hedging, so §5.1 should recover much of it too. Confirm post-build.

This is a self-contained brief for a fresh session. It describes the catalogue
ingestion pipeline, its current state, and the concrete changes to make. You do
not need prior chat context — everything needed is here.

## 1. What the pipeline does

`python -m app.data.catalogues.ingest [--fresh] [--brand SLUG] [--dry-run] [--verbose] [--concurrency N]`

For each file in `app/data/catalogues/manifest.jsonl` (2163 files, grouped into
brand folders):
1. Parse `valid_from` from the filename (`parse_date.py`).
2. Read every worksheet; pick the header row (`_pick_header_index`), split header/data.
3. For each sheet's header, get a `ColumnMapping` (which source column → which
   canonical field). This is the only LLM step — one OpenRouter call per unique
   header layout (`llm_mapper.map_sheet_columns`, model `deepseek/deepseek-v4-flash`).
4. `apply_mapping` turns rows into `CanonicalRow`s; `_to_catalogue_dict` snaps the
   brand to canonical (`brands.snap_brand`), derives fuel/CO2 standard, builds a
   `match_key`, and bulk-upserts into the `catalogue` table.

Key files:
- `app/data/catalogues/ingest.py` — orchestration, header detection, upsert, `--fresh`.
- `app/catalogue/llm_mapper.py` — the OpenRouter call, JSON schema, prompt, hallucination guard.
- `app/catalogue/canonical_schema.py` — `ColumnMapping`, `CanonicalRow`, `apply_mapping`.
- `app/catalogue/mapping_store.py` — persistent, committed cache of mappings.
- `app/catalogue/brands.py` — canonical brand vocabulary + `snap_brand`.
- `app/data/catalogues/parse_date.py` — filename → `valid_from`.
- `app/data/catalogues/column_mappings.json` — the committed mapping cache (COMMIT THIS).

DB: Postgres in docker (`carppmv-db-1`, `postgres:16-alpine`), host port 5433,
db `carppmv`, user `user`. `catalogue` has NO foreign keys pointing at it, so
truncate/rebuild is safe. Run the app via `.venv/bin/python`.

## 2. Current state (already done — do NOT redo)

- **`--fresh` flag**: truncates `catalogue` (TRUNCATE … RESTART IDENTITY) before
  ingesting, so cleanup is reproducible. Refuses to combine with `--brand`.
- **Persistent mapping store** (`mapping_store.py` + `column_mappings.json`):
  keyed by a hash of header cells; stores `ok` (a `ColumnMapping`) or `fail`
  (deterministic rejection). Loaded at startup, written incrementally (crash-safe,
  resumable). Transient errors (timeouts/HTTP) are NOT persisted so they retry.
  **Effect: after one build, re-runs and the VPS make ZERO LLM calls.**
- **Header detection rewritten** to alignment-based (`_pick_header_index`): picks
  the text row whose columns line up with the data below, not the first text row.
  Fixed the Mazda "36 per-colour sheets each mistaken for a header → 36 doomed
  LLM calls" explosion.
- **Date parser** (`parse_date.py`) now takes a `folder_year` fallback and handles
  `YYYY-MM-DD`, `DD_MM_YY`, day-first `DDMMYYYY`, and `DD.MM.`+folder-year.

### Last full build result (the baseline to protect)
`--fresh` build: **120,811 rows, 38 brands, ZERO phantom brands**, 36 min.
Store: 965 layouts (319 ok / **646 fail**). 1818 files ok / 345 failed.

Per-brand baseline (protect these on any re-run):

| brand | rows | | brand | rows |
|---|---|---|---|---|
| Volkswagen | 31978 | | Citroën | 1249 |
| Audi | 28772 | | Hyundai | 868 |
| Škoda | 22684 | | MINI | 505 |
| Seat | 8119 | | Mitsubishi | 495 |
| Mercedes-Benz | 5233 | | Fiat | 471 |
| Kia | 3993 | | Cupra | 452 |
| Porsche | 3376 | | Dacia | 358 |
| BMW | 3202 | | Honda | 291 |
| Peugeot | 3115 | | DS | 229 |
| Volvo | 2964 | | Jeep | 215 |
| Renault | 1524 | | Chevrolet | 179 |

Plus a long tail (MG, Alfa Romeo, Toyota, SsangYong, Infiniti, smart, Abarth,
Geely, Isuzu, Lexus, Lancia, Forthing, Lynk & Co, Foton, BAIC, Suzuki).

**Empty brands (11):** BYD, Jaecoo, Omoda (all likely all-electric → PPMV-exempt,
verify), Maserati (0 source files — expected), and **Mazda, Nissan, Opel, Subaru,
Land Rover, Jaguar, Tata** (the real targets — see §3).

**Known minor regressions from the header change (investigate, §3.6):**
BMW −242 and Porsche −106 vs the pre-header-change run.

## 3. The problem to fix: 646 rejected layouts

The mapper asks the LLM for the **exact header string** of each field, then
rejects any answer not byte-identical to a header cell (the "hallucination
guard"). Breakdown of the 646 rejections (from build logs):

- `brand_column` invented: **115**
- `fuel_column` invented: **35**
- `valid_from_column` invented: **27**
- `model_name_column`: 13, `price_column`: 12, `type_code_column`: 11, misc: ~5
- **Of these, 67 were the literal string `"null"`** — the model *wanted* to say
  "no such column" but the schema (`type: string`, required) forbade real null,
  so it wrote `"null"` and got rejected.

Two root causes:
1. **Required non-null fields force invention.** `brand_column`, `fuel_column`,
   `valid_from_column`, `price_column` are `required` non-null strings in
   `_COLUMN_MAPPING_SCHEMA` (`llm_mapper.py`). Many real sheets legitimately lack
   a brand/fuel/valid-from column (the value comes from the filename or model
   text), so the model invents one. Example that *should* map perfectly but is
   rejected only for this reason:
   `DACIA…#LOGAN header ['OPREMA','MODEL','GORIVO','MOTOR','kW (KS)','CO2 (g/km)','CIJENA ZA KUPCA S PDV-OM']`
   → rejected because LLM invented `valid_from_column='VRIJEDI OD'`.
2. **Exact-string matching is brittle** against messy headers (`'MPC neto\n(bez
   PDV-a)'`, `'Emisija\nCO2\n(g/km)'`). The model returns a sensible paraphrase
   that doesn't byte-match. This ALSO bloats `column_mappings.json`: the
   fingerprint hashes raw cells, so `g/km` vs `g km` or a stray `\n` makes a
   *new* entry and a *new* LLM call (965 entries for ~a few hundred real layouts).

## 4. Requirements / constraints (from the product owner)

- **brand, fuel, valid_from are MANDATORY in every output row.** Do NOT make the
  *output* nullable. Only relax the requirement that they map to a *sheet column*:
  - **brand** → when no brand column, use the folder-group brand via
    `snap_brand` (already happens in `_to_catalogue_dict`); brand is never null.
  - **valid_from** → when no column, use the filename date (already parsed as
    `valid_from_file` in `_ingest_entry`); never null.
  - **fuel** → when no column, derive from the model/variant text
    (`SKYACTIV-D`=diesel, `TDI`/`CDI`/`dCi`=diesel, `TFSI`/`TSI`=petrol, badge
    suffix `…d`/`…i`, etc. — logic already exists in `matching.py`:
    `_fuel_from_engine_words`, `_fuel_from_badge`). If it truly can't be derived,
    the row is flagged `needs_review` / skipped — NOT shipped with null fuel.
- Do **not** re-pay for mappings already in `column_mappings.json` — migrate them.
- We are **NOT rate-limited.** Evidence: in the last build all 131 transient
  failures were `TimeoutError`, **zero HTTP 429**. OpenRouter/DeepSeek use dynamic
  limits and signal overload with 429 (we saw none). The 20s timeout was cutting
  off valid slow responses.

## 5. Changes to implement

### 5.1 Stop forcing invention — make source-columns nullable (biggest win)
In `llm_mapper.py` `_COLUMN_MAPPING_SCHEMA`, change `brand_column`, `fuel_column`,
`valid_from_column` from `{"type":"string"}` to `{"type":["string","null"]}`
(keep `price_column` required — a priced catalogue row without a price is useless).
Update the system prompt: "Return null for any field that has NO corresponding
column in the provided header. brand/fuel/valid_from are often absent as columns —
that is normal and expected; returning null is correct, do not guess a column."
This alone recovers the 67 `"null"` cases and most of the 115 brand / 35 fuel /
27 valid_from inventions.

Then in `canonical_schema.apply_mapping` + `ingest.py`:
- Pass the filename date into `apply_mapping` as `default_valid_from`; use it when
  `valid_from_column` is null OR the cell is blank/unparseable (currently
  `apply_mapping` hard-requires a valid_from cell — `canonical_schema.py:~474`).
- When `fuel_column` is null/blank, derive fuel from the model/variant text using
  the existing helpers (lift/share `_fuel_from_engine_words` / `_fuel_from_badge`
  from `matching.py`, or import them). Keep `needs_review` when underivable.
- brand null already handled downstream by `snap_brand`; make sure a null
  `brand_column` doesn't crash `apply_mapping` (treat as empty → snap from folder).

### 5.2 Strongest anti-hallucination: constrain the decoder (recommended)
Build the JSON schema **per sheet** so each `*_column` field is an `enum` of that
sheet's actual header cells plus `null`:
`{"enum": [<header cell 1>, <header cell 2>, …, null]}`.
OpenRouter structured-output (`strict: true`) then makes it *impossible* for the
model to return a string that isn't a real header cell — hallucination is
eliminated at generation time, not caught after. This keeps the string-based
lookup and makes the post-hoc guard a no-op safety net. Verify DeepSeek-V4-Flash
honours enum under OpenRouter strict mode with a quick one-sheet test first.

Alternative if enum proves unreliable: **index-based mapping** — present the
header as a numbered list and ask for the 0-based column index (or null) per
field; validate `0 <= idx < len(header)`; `apply_mapping` uses the index directly.
Also eliminates hallucination, but index-counting on ragged (blank-filled)
headers is a bit more error-prone than enum.

### 5.3 Prompt hardening (regardless of 5.2)
- "The provided header array is the ONLY allowed source. Do NOT use prior
  knowledge of what these files usually contain (e.g. MARKA/GORIVO/VRIJEDI OD).
  If a field's column is not literally present, return null."
- Add one few-shot example: a header with no brand/fuel/valid_from column → the
  correct all-null answer for those three.
- Temperature is already 0.

### 5.4 Normalized fingerprint + cache migration (shrink JSON, cut calls)
- In `mapping_store.fingerprint_key`, normalize each cell before hashing:
  lowercase, replace `\n`/multiple spaces with single space, strip surrounding
  punctuation. Near-duplicate layouts (`g/km` vs `g km`) then collapse to one key
  → fewer entries, fewer LLM calls.
- **Migration**: write a one-off script that loads the current
  `column_mappings.json`, recomputes each key with the new normalizer, and
  writes the deduped file. The stored `ColumnMapping` values (exact column names)
  stay valid because lookups still use exact strings within a sheet. This
  preserves everything already paid for. (If you switch to index-based in 5.2,
  the stored values change shape — then re-run once instead of migrating, but the
  enum approach avoids that.)

### 5.5 Speed (we are timeout-bound, not rate-limited)
- `ingest.py`: raise `LLM_TIMEOUT_SECONDS` from 20 → 60 (stop killing valid slow
  calls; they'll now complete and get cached, so they aren't re-paid next run).
- Raise default `--concurrency` from 32 → 48. Keep the transient-retry path in
  `_resolve_mapping` (it already retries next run); optionally add in-run retry
  with small backoff on HTTP 429 in `llm_mapper` in case higher concurrency ever
  triggers dynamic limits.

### 5.6 Investigate BMW −242 / Porsche −106
The alignment header picker chose a different header on some BMW/Porsche sheets
vs the previous run. Diff which sheets lost rows (compare a build with the old
`_pick_header_index` vs new on those two brands), and either refine the picker or
confirm the lost rows were junk. Do this before final sign-off.

## 6. Validation

1. `.venv/bin/python -m app.data.catalogues.ingest --fresh` (the one paid build).
2. Diff per-brand row counts against the §2 baseline. Big brands must hold
   (±small); the 7 target empties (Mazda/Nissan/Opel/Subaru/Land Rover/Jaguar/
   Tata) should now produce rows; BMW/Porsche should recover to ~baseline.
3. Assert ZERO phantom brands:
   `SELECT DISTINCT brand FROM catalogue` all in `brands.CANONICAL_BRANDS`.
4. Re-run once more and confirm **0 new LLM calls** (store fully warm) and much
   smaller wall-clock.
5. Confirm `column_mappings.json` shrank (normalized fingerprint) and rejection
   count dropped sharply.
6. Commit `column_mappings.json` so the VPS ingest is free/fast, OR ship the DB
   via `pg_dump` (catalogue table has no FKs; see DEPLOYMENT.md).

## 7. Per-empty-brand diagnostic (run first to confirm causes)
For each empty brand, grep the build log or run `--brand <slug> --verbose` and
look at the `[FAIL]` reasons. Expected: Mazda/Nissan/Opel/Subaru/Land Rover/
Jaguar/Tata are the nullable-column issue (§5.1); BYD/Omoda/Jaecoo are
all-electric (fuel maps to None → exempt, verify in source); Maserati has no files.

## 8. Do NOT
- Do not make brand/fuel/valid_from null in the *output* — only in the *source
  mapping*, with the deterministic fallbacks above.
- Do not lower concurrency thinking it's rate limits — it's timeouts.
- Do not throw away `column_mappings.json` — migrate it.

## 9. Iteration 2 (2026-07-18) — the `model` field is wrong for BMW/MINI

Found while auditing per-brand row counts on the DB produced by iteration 1
(159,084 rows / 43 brands — the nullable-column fix landed and `--fresh` was
run since §2's baseline). `SELECT brand, COUNT(*), COUNT(DISTINCT model) …`
showed BMW at 4,799 rows / **532 distinct models** (~9 rows/model) vs Audi's
28,772 rows / 109 models (~264 rows/model). Sample BMW models: `116d Unique
Line`, `118d Advantage+6U3` — trim/package names, not model lines.

**Root cause** (`app/catalogue/canonical_schema.py`, confirmed against real
files in `app/data/catalogues/bmw-mini/`): recent-format BMW/MINI sheets
interleave a section-header "banner" row per series (single populated cell,
e.g. `"BMW serije 1 (F40)"`, `"MINI CLUBMAN(F54)"`) between blocks of trim
rows, where `TRGOVAČKI NAZIV` ("trade name") holds only the trim (`118i`,
`M135i xDrive`). `_is_junk_row` correctly identified these banners as junk
and **dropped them** — discarding the only real series signal in the file —
so the trim column got ingested as `model` directly. `matching.py`'s
`build_match_key` docstring already assumed `model='serija 3'` was the real
shape; it never was, for these files.

Same shape confirmed in **Jaguar** (451 rows/290 models, `model='260JY'` — an
internal type code) and **Land Rover** (999/541, `model='350NA'`) — both use a
type code instead of a real model name (`"RR Sport HSE..."`, `"Jaguar XF
S..."` sits in `variant`/`full_name` instead). NOT fixed by iteration 2 — no
banner rows to recover from in these two, would need a model-family regex
extraction from the descriptive text instead. Left for iteration 3.

Also found in passing, NOT fixed (separate bug classes, flagged for later):
- **Mazda: 59 source files, 0 DB rows.** `apply_mapping` succeeds, but every
  row is dropped in `ingest.py::_to_catalogue_dict` because `fuel_type`
  resolves to `None`. Mazda uses plain displacement badges (`"1.3i"`,
  `"2.0d"`) with no fuel column in the sheet; `matching.py`'s
  `_fuel_from_badge` regex requires a 2-3 digit badge
  (`\b\d{2,3}[di]\b`, tuned for BMW-style `320d`) and `normalize_text`
  fragments `"1.3i"` into tokens `"1"`/`"3i"` — `"3i"` is 1 digit, never
  matches. Fix: widen the badge regex (or add a decimal-displacement variant)
  — needs testing against the full Mazda corpus for false positives first.
- **Suzuki: 38 source files, 1 DB row.** At least the pre-2014 files have no
  CO2 column in the sheet at all (`missing_co2` on every row) — looks like a
  genuine source-data gap (pre-dating stricter CO2 labeling), not a parsing
  bug. Spot-check a couple of newer Suzuki files before concluding this is
  unfixable.
- **A legacy BMW format** (`bmw-mini/2013/BMW 2013 0731.xls`, header
  `Marka/Tip/Varijanta/Trgovački naziv/...`) has NO banner rows — instead
  `Tip` holds the series per-row (`"Serija 1 (F20)"`, populated on every
  data row). The cached mapping (confidence 0.95) declined to map `Tip` at
  all because its 5-row LLM sample happened to show it blank (`'/'`); the
  full sheet has it populated throughout. Iteration 2's fix doesn't touch
  this — no banner to detect, so it's inert here (no regression either).
  Re-mapping needs a fresh (paid) LLM call for this fingerprint, or a
  code-level override; out of scope for now.
- Other low-row brands (BAIC 2, Foton 5, Forthing 5, Lynk & Co 5, Isuzu 11,
  Geely 14, smart 33, Infiniti 37, Subaru 40) look structurally plausible for
  low-volume marques — re-audit after the Mazda/Suzuki items above land, in
  case the same junk-row/fuel-derivation bug classes are clipping them too.

### Fix implemented (`app/catalogue/canonical_schema.py`, `app/data/catalogues/ingest.py`)

- New `CanonicalRow.series_name: str | None` field.
- `_detect_series_banner(row, brand_col_idx, typical_brand_text)`: a row is a
  banner only if ALL of — exactly one populated cell in the whole row; that
  cell sits in the mapped `brand_column` position; its text is non-numeric;
  and its text differs from `_typical_brand_cell_text` (the sheet's
  majority/mode brand-cell value, e.g. `"bmw"`). That last check is the
  important guard: without it, an ordinary malformed row with only its
  (plain) brand cell populated — a real junk shape, unrelated to banners —
  would be misread as a banner and forward-fill a bogus series onto every
  later row in the sheet. `brand_col_idx`/`typical_brand_text` are computed
  once per `apply_mapping` call, not per row.
- `apply_mapping` tracks `current_series`, updated on each banner row
  (skip-logged as `"series_banner"`, not `"junk_row"`, for auditability) and
  carried onto every subsequent `CanonicalRow.series_name` until the next
  banner. Sheets with no banner rows (Audi, VW, ...) get `series_name=None`
  throughout — behavior is unchanged for every brand except BMW/MINI.
- `ingest.py::_to_catalogue_dict`: `model = row.series_name or row.model_name
  or row.type_code or "unknown"` (was `row.model_name or row.type_code or
  "unknown"`). `variant` is untouched. The fuel-derivation call still passes
  `row.model_name` (the trim, e.g. `"320d"`) — badge-based fuel detection
  needs the trim text, not the series name, so that path is deliberately
  left alone.
- Tests: `tests/test_apply_mapping.py` — updated the two existing BMW
  section-header tests (`"junk_row"` → `"series_banner"` skip reason) and
  added coverage for `series_name` propagation across multiple banners, the
  "no banner → series_name stays None" case for non-BMW families, and the
  `_to_catalogue_dict` model-selection behavior end-to-end.

### Verified against real files (not yet a DB rebuild)
`bmw-mini/2020/BMW 2020 3011.xlsx`, BMW sheet: 179 rows, **16 distinct
models** (was ~implicitly ~100+ trim-polluted values under the old logic) —
`BMW serije 1`, `BMW serija 2 Gran Coupe`, `BMW serija 5 LCI (G30/F90)`, etc.
`bmw-mini/2013/BMW 2013 0731.xls` (the no-banner legacy format above):
unchanged, 201 rows / 115 models, as expected — confirms no regression.

### Next step — local rebuild (no LLM cost)
This iteration changes only `apply_mapping`'s row-transform logic, not the
column-*mapping* step — `column_mappings.json` stays fully valid, so a
rebuild costs $0 and makes 0 new LLM calls. Run:

```
.venv/bin/python -m app.data.catalogues.ingest --fresh
```

Then verify:
```sql
SELECT brand, COUNT(*), COUNT(DISTINCT model) FROM catalogue
WHERE brand IN ('BMW','MINI') GROUP BY brand;
```
BMW's distinct-model count should drop from ~532 to roughly the mid-teens
(real BMW series count); MINI similarly. Every other brand's row/model counts
should be unchanged from before this iteration (spot-check Audi/VW to
confirm the no-banner path is untouched).

### Iteration 2 result (verified against the live DB, 2026-07-18)
`--fresh` was run and committed (`b17ce51`). Actual outcome:
- **MINI: 100% fixed** — 620/620 rows have a real series model
  (`MINI CLUBMAN`, `MINI COUNTRYMAN (F60) LCI`, ...).
- **BMW: 67.5% fixed** — 3,228 of 4,779 rows now carry a real series name
  (56 distinct series/generation strings, e.g. `BMW serije 1`, `BMW serija 5
  LCI (G30/F90)` — the count is >15 because generation/facelift suffixes and
  inconsistent year-to-year spelling of "serija"/"serije" each produce a
  distinct string; still vastly better than the old ~500+ trim-polluted
  values). The other 1,551 rows (32.5%) are still trim-named.
- The **entire unfixed 32.5%** traces to exactly **61 `.xls` files, 2013-2017**
  — none from `.xlsx` files. Every one of them shares one of two near-identical
  header layouts (`Marka, Tip, [blank], Varijanta, Trgovački naziv, ...` and a
  variant with no blank column) — this is the same legacy format flagged in
  §9's "legacy BMW format" note, just now fully scoped. `Tip` holds the real
  series per-row (`"Serija 1 (F20)"`) but the cached LLM mapping (confidence
  0.95, all 61 files share the same 2 fingerprints) declined to map it —
  its 5-row sample happened to show `Tip` blank, even though it's populated
  throughout the real sheet.

## 10. Iteration 3 — handoff plan (not yet started)

Five known, scoped issues remain. Ordered by impact/effort. None of these
require re-touching the iteration-2 banner-row logic — they're independent.

### 10.1 Legacy 2013-2017 BMW `.xls` format (highest impact, ~1,551 rows)
**Root cause**: `Tip` (holds the real series, e.g. `"Serija 1 (F20)"`,
populated on every data row) was left unmapped because the LLM's 5-row
sample happened to show it blank. This is a mapping-cache quality issue, not
a code bug — the same class of failure could recur for any column that's
sparse in whichever 5 rows happen to get sampled.

**Recommended fix** — do NOT re-pay for a fresh LLM call (uncertain it'd fix
itself, same sampling luck applies). Instead, directly patch the 2 affected
cache entries in `column_mappings.json`:
1. Find the two fingerprints: `mapping_store.fingerprint_key(header)` for
   `['Marka','Tip','','Varijanta','Trgovački naziv',...]` and the no-blank
   variant.
2. Set `model_name_column: "Tip"` (was `"Trgovački naziv"`) on both cached
   entries directly in the JSON (or via a small one-off script using
   `mapping_store.load()`/`save()` — mirrors `scripts/migrate_mapping_cache.py`'s
   pattern of editing the store programmatically).
3. `Trgovački naziv` (the actual trim, e.g. `"125d"`) then needs to keep
   flowing into `variant` — check what `full_name_column`/`type_code_column`
   are mapped to for these two fingerprints first; if neither already covers
   the trim text, remap one of them to `"Trgovački naziv"` so `variant` isn't
   left with only the type code.
4. Re-run `--fresh` (still $0 — these are cache edits, not new LLM calls).
5. Verify: `SELECT COUNT(*) FROM catalogue WHERE brand='BMW' AND model NOT
   ILIKE '%serij%' AND model NOT ILIKE '%serie%';` should drop close to 0
   (a few pre-2013 or odd-format rows may remain — check before assuming bug).

**Effort**: small — 2 cache entries, no new logic, verify via SQL diff.

### 10.2 Jaguar / Land Rover: type-code-as-model (~1,450 rows combined)
**Root cause** (§9): no banner rows in these files — `model='260JY'` (Jaguar)
/ `'350NA'` (Land Rover) are internal type codes; the real model name
(`Range Rover Sport`, `XF`, `Discovery`, `F-Pace`...) is embedded in
`variant`/`full_name` text like `"RR Sport HSE Dynamic 5.0 V8..."` /
`"Jaguar XF S 2.0D I4..."`.

**Recommended fix**: a small, hand-maintained regex/keyword extraction —
NOT an LLM call (this is row-level text, out of scope for the per-sheet
column mapper). Add a `_extract_model_family(text: str, known_families:
tuple[str,...]) -> str | None` helper (probably in `canonical_schema.py`
next to `_detect_series_banner`, or a new small module if it needs a
per-brand family list) that matches the longest known family name appearing
in the variant/full_name text. Needs real family lists:
- Land Rover: `Range Rover Sport`, `Range Rover Velar`, `Range Rover Evoque`,
  `Range Rover` (check longest-match-first so "Range Rover Sport" doesn't
  match as plain "Range Rover"), `Discovery Sport`, `Discovery`, `Defender`.
- Jaguar: `XE`, `XF`, `XF Sportbrake`, `XJ`, `F-Pace`, `E-Pace`, `I-Pace`,
  `F-Type`.
Verify these lists against real file samples first (`grep` a few dozen
`variant` values per brand out of the current DB — the strings are already
there) rather than trusting the WebSearch-sourced 2026 lineup blind, since
these files span 2013-2024 and include discontinued models (e.g. Jaguar XE
was discontinued but will appear in older files).
**Fallback** for text that matches no known family: keep the current
type-code behavior (`model = type_code`) rather than dropping the row —
same "never silently invent, but don't lose data either" principle as the
rest of this pipeline.

**Effort**: medium — needs real-data-verified family lists per brand, plus
tests per family. Higher risk of false matches than 10.1 (regex-based, not
a clean per-row column), so test thoroughly against the full corpus before
trusting it.

### 10.3 Mazda: 0 DB rows despite 59 source files
**Root cause** (§9): `_fuel_from_badge` (`app/catalogue/matching.py:272-273`,
`\b\d{2,3}[di]\b`) requires a 2-3 digit badge; Mazda's `"1.3i"`/`"2.0d"`
style gets fragmented by `normalize_text` into sub-2-digit tokens (`"1"`,
`"3i"`), so fuel never resolves and every row is dropped (NOT NULL
`fuel_type`).

**Recommended fix**: add a second regex alongside `_BADGE_DIESEL_RE`/
`_BADGE_PETROL_RE` for the decimal-displacement style, e.g.
`\b\d\.\d[di]\b` matched against the RAW text (before `normalize_text`
strips the `.`) — or normalize differently for this specific pattern.
**Caution**: this is a shared, multi-brand function (`_derive_fuel_family` is
used for fuel derivation across ALL brands during ingest AND for scoring
listing matches in `/calculate`). Before landing this, grep the full corpus
for any OTHER brand using `\d\.\d[di]` as a coincidental substring that
would now misfire (e.g. a trim name containing a version number like "2.0i
Limited" is fine/intended, but something like a random spec code shouldn't
false-positive). Test against Mazda's full 59-file corpus for the actual
fix, and spot-check 2-3 other brands' full data for false positives before
committing.

**Effort**: small code change, but needs careful cross-brand regression
testing since `matching.py` fuel derivation is shared, high-blast-radius code.

### 10.3 result (DONE, 2026-09-04)
Mazda is live: **0 → 11,212 rows**, 44 brands in the catalogue (was 43). Code
change only, no LLM calls — all 59 files' header layouts were already cached,
so the re-ingest was $0 (`--brand mazda`, 59 succeeded / 0 failed).

**The original diagnosis above was right about the mechanism and wrong about
the shape**, which matters because a fix built to the description alone would
have recovered a minority of the rows and looked like it worked. `"1.3i"` /
`"2.0d"` is a real Mazda naming style but a small one; the dominant shape is
the family letter *leading* the power figure — `Skyactiv-G120`, `CD175`,
`e-Skyactiv-X186`, `G100` — plus `e-SKYACTIV PHEV` on the CX-60/CX-80.

Three rules added in `matching.py`, in tiers:
- `_SKYACTIV_{DIESEL,PETROL}_RE` — the family letter anchored to a `skyactiv`
  token, in the *engine-word* tier (it is definitional, like TDI/TSI).
- `_BADGE_PREFIX_{DIESEL,PETROL}_RE` — the bare leading-letter badge, badge
  tier, **gated on brand == Mazda**.
- `_BADGE_DECIMAL_{DIESEL,PETROL}_RE` — `2.0i`/`2.2d`, matched on RAW text
  (normalize_text splits the period into an unanchorable one-digit run) and
  multi-brand, with a `(?!-)` guard.
- `"phev"` added to `_PETROL_ENGINE_WORDS`, agreeing with canonical_schema's
  existing `PETROL_PLUG_IN_HYBRID -> FuelType.PETROL`.

**The brand gate is a measured result, not caution.** §10.3 flagged the
false-positive risk and it was real: replayed unrestricted over the 159,443
rows already in the catalogue, the leading-letter rule mislabelled 47 in two
classes that no tightening removes — BMW's chassis code normalizes to a bare
`g20` token (every G20/G21 diesel read as petrol), and `normalize_text`
fragments Opel's `0UC98CD61` into `0 uc98 cd61`, whose `cd61` read as diesel
on a petrol Adam. The `(?!-)` guard came from the same run: Kia's petrol
`1.4 D-CVVT` read as diesel and Honda's diesel `1.6 i-DTEC` read as petrol.

Final regression over all 159,443 pre-existing rows: **0 derivations
contradicting the stored fuel**, 483 rows (Land Rover 273, Jaguar 175,
Infiniti 21, Kia 14) newly deriving a value that agrees with it. Fuel now
resolves for **98.7%** of the Mazda corpus; the ~223 that don't are MX-30 EVs
(correctly excluded — EVs are PPMV-exempt) and ~30 "Mazda2 Hybrid" rows
("hybrid" alone is deliberately not in the vocabulary — it sits on diesel
hybrids too). Locked in by four tests in `tests/test_matching.py`.

**Two things this did NOT fix, both pre-existing classes:**
- **Mazda's `model` column is the descriptive blob, not a model family** —
  3,070 distinct values for 11,212 rows, e.g. `CX-60 2022 5WGN 2.5L e-SKYACTIV
  PHEV 327ps 8AT AWD EXCLUSIVE-LINE CON-P PAN-P`, plus 594 rows where it is a
  bare type code (`KDRPEAWCS7`). This is the same class as 10.2
  (Jaguar/Land Rover) and makes `GET /catalogue/models?brand=Mazda` a poor
  suggestion list, though fuzzy matching on variant text still works.
- **411 rows have a paint colour as the model** (`Mazda3 Soul crvena
  Crystal`) — the per-colour-sheet banner issue §5 already describes.
- Related cascade, fixed separately or not at all: because `PHASE_0_BRANDS`
  was derived from brands *present in the DB*, Mazda was never in
  `BRAND_ARTICLES` either, so `wikipedia_engine_data` holds 0 Mazda rows. The
  catalogue now covers Mazda, but the Wikipedia fallback tier still does not.

### Currency resolution fix (DONE, 2026-09-04)
Found while verifying 10.3 in the UI: a Mazda CX-5 listed at 50,142 EUR was
stored as **6,655 EUR**. The value is not in the source file — it is
`50142.5712 / 7.5345`, i.e. an already-euro price divided by the kuna rate.

**Root cause.** `apply_mapping` resolved currency as
`_detect_currency_from_header(price_column) or mapping.price_currency`. When
the header names no currency — Mazda's is `MPC (s trošarinom)` — that falls
through to the LLM's *guess*, and the model has nothing to read, so it guesses.
It guessed HRK on **7,354 post-euro rows** across Mazda (5,634), Hyundai (611),
Opel (585), Renault (356) and Dacia (168). Price is the base of the whole PPMV
formula, so this understates the tax ~7.5x, confidently and with no warning.

**Fix** (`canonical_schema._resolve_price_currency`), four tiers:
header text → **sub-header cell in the same column** → **validity date
(`EURO_ADOPTION_DATE`, 2023-01-01)** → the LLM's guess. `valid_from` is now
resolved *before* the price is normalized, since it feeds the decision.

**The tier order is the whole design, and the date is deliberately third.**
A date-first rule looked right and is wrong: Opel's `OPEL 11.09.2023..xlsx` is
a post-euro *file* holding legacy MY21/MY22 sheets whose real prices are in
kuna (median raw 283,100 — as euro that would be a 283k Opel; as kuna it is a
correct 37,573). Date-first would have multiplied every Opel price by 7.53
while fixing Mazda. What saves it is that the evidence is in the document:
Opel's price column carries a *sub-header* row reading `Preporucena cijena sa
ukljucenim PDV-om KN`, which `_pick_header_index` never selected. Reading that
row is the second tier, and it beats the date. An absolute magnitude threshold
was considered and rejected — Land Rover's legitimate post-euro EUR median is
112,435, too close to Opel's kuna figures to separate them safely.

**Corpus-wide replay before re-ingesting** (all 7,477 mapped sheets):
815 sheets flip HRK→EUR, every one with a plausible euro median (17k-37k);
exactly **1** flips EUR→HRK (Opel's, landing at 36,435). Three Land Rover
"-options" sheets also flip, but they are accessory lists with no CO2 column
and produce zero catalogue rows either way.

**Second defect found while verifying the first.** The re-ingest corrected
prices but left `source_currency` reading "HRK" — the upsert's
`on_conflict_do_update` set only `price_eur` and `co2_g_km`, so every other
derived column goes stale on re-ingest and the audit column ended up
contradicting the price it exists to explain. `set_` now also refreshes
`source_currency`, `fuel_type`, `power_kw`, `co2_standard` and `source_file`;
the unique-key columns stay out, since they identify the row rather than
describe it.

**Result** after re-ingesting the 8 affected brand folders (all cached
mappings, $0): post-euro rows still tagged HRK **7,354 → 570**, and those 570
are Opel's genuinely-kuna sheets at a correct 34,165 EUR average. Mazda's
average price 14,543 → 40,907. Verified in the browser: the CX-5 row now reads
50.142,57 EUR. Four tests in `tests/test_apply_mapping.py` cover the tier
order, including the dual-display carve-out and the 2023-01-01 boundary.

### 10.4 Suzuki: 1 DB row despite 38 source files
**Not confirmed as a bug yet** — at least the pre-2014 files genuinely lack
a CO2 column in the sheet. Before writing any code:
1. Open 3-4 of the newer Suzuki files (`app/data/catalogues/suzuki/2020/` or
   later) directly and check by eye whether they have a CO2 column.
2. If yes and it's just not mapping: check the cached mapping for those
   fingerprints (`mapping_store.load()`, filter by any file under
   `suzuki/`) and see whether `co2_column`/`co2_min_column`/`co2_max_column`
   are all null despite a real CO2 header being present — that'd be an LLM
   mapping-quality issue like 10.1, fixable the same way (direct cache edit).
3. If no CO2 in any Suzuki file ever: this is a genuine source-data gap,
   not fixable in code. Document it and move on.

**Effort**: investigation first (30 min), fix only if step 1/2 finds a real
mapping bug — could be zero-effort ("confirmed not a bug") or small
(cache edit like 10.1).

### 10.5 Re-audit remaining low-row brands
BAIC, Foton, Forthing, Lynk & Co, Isuzu, Geely, smart, Infiniti, Subaru —
row/model ratios looked structurally plausible for low-volume marques when
last checked, but weren't individually root-caused. Re-run the same probe
used for Mazda/Suzuki this session (`apply_mapping` + `_to_catalogue_dict`
on a sample file per brand, check whether rows survive `apply_mapping` but
get dropped in `_to_catalogue_dict`, and why) — do this AFTER 10.3 lands,
since a fuel-derivation fix might independently un-block some of these too.

**Effort**: investigation only, small if it turns out to be the same root
causes as 10.3/10.4; otherwise scope per-brand as discovered.

### Suggested order
10.1 (BMW legacy format) → 10.3 (Mazda) → 10.5 (re-audit, may now be smaller)
→ 10.4 (Suzuki, investigation-only) → 10.2 (Jaguar/Land Rover, highest effort,
do last). Each is independent — no ordering dependency, this is just
effort/impact sorted. Run `--fresh` once after all code/cache changes land
rather than after each one (all are free/cache-only, no reason to rebuild
5 times), then do one full per-brand row/model diff against this session's
baseline (§2's table plus the iteration-2 result above) before calling it done.

### 10.1 result (DONE, 2026-07-18)
Two cache entries patched directly in `column_mappings.json`
(`mapping_store.load()`/`save()`, no LLM call, $0):
- `59b66e02379c3638e40f38d91b539c651e0dc2f5` — the blank-column variant
  (`Marka, Tip, '', Varijanta, Trgovački naziv, ...`). Note: this single
  fingerprint actually covers BOTH header shapes described in the original
  plan (blank-column and no-blank-column) — `fingerprint_key` hashes the
  *set* of non-empty normalized cells, so a blank column doesn't change the
  key. The "two fingerprints" in the original diagnosis turned out to be one.
- `3616f5f3f670890fadc5d4696d2cc6747e4b4c81` — a second, distinct legacy
  fingerprint found only after rebuilding once and re-auditing leftover
  trim-named rows by `source_file`: 2015-2017 files whose CO2 header has a
  literal `*` prefix (`'*Prosječna emisija CO2'`, a footnote marker), which
  hashes differently. Same root cause, same fix.

Both entries: `model_name_column` moved `"Trgovački naziv"` → `"Tip"`;
`full_name_column` set to `"Trgovački naziv"` (was `null`) so the trim text
keeps flowing into `variant` instead of being dropped.

**False lead, ruled out before patching further**: a broader grep of the
whole cache for "`Tip` + `Trgovački naziv` present, `model_name_column` ==
`Trgovački naziv`" turned up 10 fingerprints, not 2. Traced all 10 to their
source files across the full 2160-file corpus (not just `bmw-mini/`) before
touching anything — only the 2 above are actually BMW/MINI. The other 8 are
Mercedes-Benz/smart and Honda files that happen to reuse the same Croatian
column labels with different semantics (Mercedes' `Tip` is a genuine model
class, e.g. `"C klasa"`/`"E klasa"` — already correct; patching those would
have broken Mercedes-Benz, which was not broken). Lesson: header *label*
reuse across brands is not evidence of the same bug — verify against a real
source file per brand before batch-patching by grep pattern alone.

Rebuilt `--fresh` twice (once per fingerprint fix, $0 both times — cache
edits only, zero new LLM calls, `2141 succeeded, 22 failed` unchanged from
before, the 22 failures are pre-existing and unrelated). Verified against
the live DB:
- **BMW: 99.6% fixed** — 4,850 of 4,870 rows now carry a real series name
  (was 3,228/4,779 = 67.5%). The remaining 20 rows are two `.xlsx` files
  (`bmw-mini/2019/BMW 2019 0102.xlsx`, `bmw-mini/2020/BMW 2020 2407.xlsx`) —
  a modern, structurally different format, out of scope for this item and
  negligible (20 rows).
- Full per-brand rebuild produced 43 brands (Nissan/Opel/Subaru now populated
  from the earlier iteration's nullable-column fix, as expected); no phantom
  brands, no other brand's row count changed from this session's baseline.

Next up per the suggested order: **10.3 (Mazda)**.

## 11. Production regression from iteration 3 (found + fixed same day, 2026-07-18)

10.1's fix was deployed (code push + `pg_dump`/restore to the VPS) and
immediately broke the live "Pretraži bazu vozila" (search-the-database) UI
for BMW/MINI: searching brand=BMW, model="320" returned "Nema podudaranja"
(no match) for a listing that obviously exists in the catalogue. Two
distinct bugs, found by actually using the deployed feature rather than
just checking the DB — a reminder that a DB-level verification (§6/§10.1's
SQL checks) doesn't exercise the matching/scoring code path at all.

### 11.1 matching.py: model-mismatch guard never accounted for series-name models
**Root cause**: iteration 2/3 moved the recovered series name into
`catalogue.model` for BMW/MINI, leaving the trim in `variant`. But
`app/catalogue/matching.py::_score_one`'s model-mismatch guard (existing,
pre-dates this work — see its `MODEL_MATCH_THRESHOLD`/`MODEL_MISMATCH_PENALTY`
comment block) only ever compared the query's stated model (what a scraped
listing or a manual search states, e.g. "320d" — always trim-level text for
every brand) against `cand.model`. For every other brand `cand.model` IS
that short trim/model identifier already (confirmed: VW "PASSAT", Audi "A6
Limousine", Mercedes "A 200 d"), so the guard's assumption held everywhere
except BMW/MINI post-fix, where `cand.model` is now a series name ("Serija
3 (F30)") that scores ~27 against a "320" query — triggering the -40
mismatch penalty and dropping every real BMW/MINI candidate below
`CANDIDATE_FLOOR`. This affected BOTH the manual search AND the primary
`/calculate` scraped-listing flow (same `find_match`/`rank_candidates` code
path, `query_model=listing.model`) — i.e. every BMW/MINI listing lookup in
production, not just the search form.

**Fix**: `_score_one` now scores `query_model` against whichever of
`cand.model`/`cand.variant` matches better (and takes the leading-digit
badge from whichever has one), instead of `cand.model` alone. Safe for
every other brand — a genuinely wrong-model candidate's variant/spec text
doesn't carry the other model's letter/number either, so the guard still
fires correctly (verified: all pre-existing tests, including the A4-vs-Q3
saturation-tie tests, still pass unchanged). Added
`test_bmw_series_name_model_does_not_penalise_trim_query` to
`tests/test_matching.py` covering the exact regression (a bare "320d" query
must beat a "520d" candidate row despite both having non-trim `model` text).

### 11.2 canonical_schema.py: two banner-detection bugs, found while root-causing 11.1's fix
While spot-checking real search results after deploying 11.1's fix, found
that some BMW rows' `model` was carrying an entirely WRONG series (e.g. an
`X1 SAV` row tagged `"BMW serija 7 (G11, G12)"`, a plain sedan `320i` row
tagged `"BMW serija 2 Gran Coupe"`). Root-caused via the real source file
(`bmw-mini/2018/BMW 2018 1201.xlsx`): `_detect_series_banner`
(`canonical_schema.py`) required the banner row to have **exactly one**
populated cell in the whole row. Some source sheets have a vertically-merged
column (`BROJ SJEDALA`, seat count) whose value leaks into every row of a
block via openpyxl's read of the merge — including banner rows — giving the
banner row 2 populated cells instead of 1. The strict check then silently
rejected the real banner, and `current_series` kept carrying forward the
PREVIOUS section's (wrong) series name onto the whole next block (e.g. X1
SAV rows inheriting whatever series came right before them in that file).
This is a pre-existing iteration-2 bug, not something introduced by 10.1 —
it was invisible to iteration 2's validation because every affected row
still had *a* series-shaped string (`model ILIKE '%serij%'`), just the
*wrong* one, so it silently passed the "is this row series-named" check
without anyone verifying it was the *correct* series.

**Fix**: `_detect_series_banner` now only counts populated *non-numeric*
cells toward the "exactly one" requirement — a real data row always has
more than one non-numeric cell (model name text, at minimum), so this can't
newly misread a genuine data row as a banner; it only rescues a real banner
row from being disqualified by numeric merge-cell noise.

Also found in the same file: some sheets bake the brand name into the
banner cell itself (`"BMW serije i3"`, `"BMW  serija X1 SAV (F48)"`), others
don't (`"Serija 1 (F20)"`) — inconsistent even within BMW. Since both
`ingest.py`'s `model` field and the frontend's `{brand} {model}` display
already prefix the brand themselves, the inconsistency showed up as a
visible `"BMW BMW serije 3 Touring"` duplicate in the search UI. Added
`_strip_leading_brand` (`canonical_schema.py`) to strip a redundant leading
brand token from banner text before it becomes `series_name`.

Added `test_bmw_banner_with_merged_cell_numeric_bleed_still_detected` to
`tests/test_apply_mapping.py`, and updated the 3 existing banner tests whose
assertions still expected the old brand-duplicated text.

### Verified impact (local `--fresh` rebuild + diff against the pre-11.2 DB dump)
Restored the pre-11.2 catalogue dump into a scratch Postgres container
(`docker run ... postgres:16-alpine` on a spare port) to diff row-for-row
against the fixed rebuild, rather than trusting aggregate counts alone.
BMW/MINI row counts dropped (BMW 4,870→4,796, MINI 620→587) — confirmed
this is correct deduplication, NOT data loss: several real vehicles were
previously appearing as 2-3 near-duplicate DB rows (same variant/price/date)
purely because different source files' banner text resolved to different —
often wrong — series names before this fix (e.g. the `216d Active Tourer`
example traced to 3 rows: one bare trim, one wrongly `"serije 1"`, one
correctly `"serije 2 Active Tourer"`; all 3 now correctly collapse to the
one true row). Spot-checked several of the ~110 collapsed
(variant, valid_from, price) combos — every one followed this same
"multiple wrong/inconsistent series names for the same real car" pattern,
never a case of two genuinely different cars colliding. BMW is now
**100% series-named** (4,796/4,796, up from 99.6%/4,850 pre-11.2). Every
other brand's row count is byte-identical to the pre-11.2 baseline (banner
detection only runs for BMW/MINI's header family).

### Deploy status
Code (both `matching.py` and `canonical_schema.py` fixes) committed
locally; not yet pushed. Since 11.2 changes ingested DATA (not just search
scoring like 11.1), shipping this to the VPS needs BOTH a code deploy (git
push → autodeploy, or manual `docker compose up -d --build`) AND a fresh
`pg_dump`/restore of the `catalogue` table (same procedure as 10.1's
deploy) — a code-only deploy would fix the search-scoring bug (11.1) but
leave the wrong-series data (11.2) live until the DB is re-synced.
