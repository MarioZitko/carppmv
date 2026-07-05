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
