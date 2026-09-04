"""Manifest-driven catalogue ingestion pipeline.

Reads app/data/catalogues/manifest.jsonl and for each entry:
  1. Parses valid_from from the filename (skips with warning if unparseable).
  2. Opens the xlsx/xls file and reads the header row.
  3. Looks up a cached ColumnMapping keyed by header fingerprint; if absent,
     calls OpenRouter (one call per unique header layout, never per row).
  4. Applies the mapping deterministically and bulk-upserts into catalogue.

Usage:
    python -m app.data.catalogues.ingest [--brand <slug>] [--dry-run] [--verbose]
"""

import argparse
import asyncio
import json
import re
import sys
import unicodedata
from pathlib import Path

import httpx
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.catalogue import mapping_store
from app.catalogue.brands import FOLDER_BRANDS, snap_brand
from app.catalogue.canonical_schema import CanonicalRow, FuelCategory, apply_mapping
from app.catalogue.llm_mapper import map_sheet_columns
from app.catalogue.matching import _derive_fuel_family, build_match_key
from app.data.catalogues.parse_date import parse_valid_from
from app.db.models import Catalogue, CO2Standard, FuelType
from app.db.session import AsyncSessionLocal

MANIFEST_PATH = Path(__file__).parent / "manifest.jsonl"

def _short_error(exc: Exception) -> str:
    """SQLAlchemy exceptions stringify to the full SQL statement plus every
    bound parameter — unreadable for a batch of hundreds of rows. Surface
    just the underlying DBAPI error instead."""
    orig = getattr(exc, "orig", None)
    if orig is not None:
        return f"{type(orig).__name__}: {orig}"
    return f"{type(exc).__name__}: {exc}"

# Sheets below this confidence are skipped entirely — the LLM could not
# reliably identify required fields and ingesting would produce garbage.
SHEET_CONFIDENCE_THRESHOLD = 0.6

# Per-mapping-call LLM budget. The mapper retries once internally on a stalled
# connection, so worst-case network time is ~2x this; the outer wait_for caps
# it. Raised from 20s: the last build's 131 transient failures were ALL
# TimeoutError (zero HTTP 429 — we are timeout-bound, not rate-limited), i.e.
# the 20s cutoff was killing valid-but-slow responses and forcing them to be
# re-attempted next run. 60s lets them complete and get cached once.
LLM_TIMEOUT_SECONDS = 60.0

_FUEL_CATEGORY_TO_DB: dict[FuelCategory, FuelType | None] = {
    FuelCategory.DIESEL: FuelType.DIESEL,
    FuelCategory.PETROL: FuelType.PETROL,
    FuelCategory.PETROL_HYBRID: FuelType.PETROL,
    FuelCategory.PETROL_PLUG_IN_HYBRID: FuelType.PETROL,
    FuelCategory.ELECTRIC: None,   # PPMV-exempt — no catalogue row needed
    FuelCategory.UNKNOWN: None,    # needs_review already set; don't insert bad data
}

_DERIVED_FUEL_TO_DB: dict[str, FuelType] = {
    "diesel": FuelType.DIESEL,
    "petrol": FuelType.PETROL,
}

def _override_fuel_from_variant(
    brand: str,
    model: str,
    variant: str,
    mapped_fuel: FuelType | None,
) -> FuelType | None:
    """Derive fuel from the brand/model/variant engine text and let it win over
    the mapped value. Engine words are definitional (TDI/CDI/dCi/HDi/CRDi →
    diesel; TFSI/TSI/TCe/PureTech → petrol) and the numeric badge suffix
    (320d/320i) is a reliable fallback, so a text hit is more trustworthy than
    a source cell — and, crucially, this is the sole fuel signal when a sheet
    has NO fuel column at all (mapped_fuel is None). Reuses matching's
    _derive_fuel_family so ingest and lookup share one multi-brand vocabulary.
    When the text yields nothing, keep whatever the mapping produced."""
    derived = _derive_fuel_family(brand, model, variant, brand=brand)
    if derived is not None:
        return _DERIVED_FUEL_TO_DB[derived]
    return mapped_fuel

def _co2_standard_from_year(year: int) -> CO2Standard:
    return CO2Standard.WLTP if year >= 2021 else CO2Standard.NEDC

def _to_catalogue_dict(
    row: CanonicalRow,
    co2_standard: CO2Standard,
    allowed_brands: tuple[str, ...] | None = None,
) -> dict | None:
    mapped_fuel = _FUEL_CATEGORY_TO_DB.get(row.fuel_category)
    fuel_type = _override_fuel_from_variant(
        brand=row.brand,
        model=row.model_name or row.type_code or "unknown",
        variant=row.full_name or row.type_code or row.model_name or "unknown",
        mapped_fuel=mapped_fuel,
    )

    # fuel_type and co2_g_km are NOT NULL columns on Catalogue (see db/models.py).
    # A single None here fails the whole batch INSERT, taking every other row
    # in that file's batch down with it — so skip individually instead.
    if fuel_type is None or row.co2_g_km is None:
        return None

    # series_name (from a BMW/MINI-style section-header banner row) is the
    # real model line when present — model_name in that case is only the
    # trim (e.g. "116d"), which stays useful for fuel-badge derivation
    # above but would badly fragment the catalogue's model grouping if used
    # as the model itself. Sheets with no banner rows (Audi, etc.) always
    # have series_name None here, so this is a no-op for them.
    model = row.series_name or row.model_name or row.type_code or "unknown"
    # variant keeps the full_name (KOMPLETNO IME) even for BMW/MINI's ugly
    # underscore spec blob. It reads poorly in the UI, but its door/transmission/
    # displacement tokens are load-bearing: they are the ONLY thing separating
    # several same-badge, same-date BMW rows that carry genuinely different
    # prices (e.g. a 3-door vs 5-door 116d, or a manual vs automatic 320d).
    # Collapsing variant to the bare badge merged 740 such price-distinct groups
    # (~14k rows) into one arbitrary price — silent price corruption. The
    # listing-match problem those tokens caused is solved on the query side
    # instead (see matching._strip_bmw_mini_query_noise): a cleaned query is a
    # subset of this blob and still scores 100, so nothing here needs to change.
    variant = row.full_name or row.type_code or row.model_name or "unknown"

    # Snap the row's brand to the canonical spelling allowed for this file's
    # folder-group. Fixes source typos ("Marcedes-Benz") and stray cell values
    # (a type code in the brand column) that would otherwise become phantom
    # brands invisible to any correctly-spelled search. Skip the row if the
    # brand can't be resolved rather than inventing one. When the folder isn't
    # in the vocabulary (allowed_brands is None), keep the value as-is.
    if allowed_brands is not None:
        brand = snap_brand(row.brand, allowed_brands, variant, model)
        if brand is None:
            return None
    else:
        brand = row.brand

    return {
        "brand": brand,
        "model": model,
        "variant": variant,
        "match_key": build_match_key(brand, model, variant),
        "price_eur": row.price_eur,
        "co2_g_km": row.co2_g_km,
        "co2_standard": co2_standard,
        "fuel_type": fuel_type,
        "power_kw": row.power_kw,
        "valid_from": row.valid_from,
        "source_file": row.source_file,
        "source_currency": row.price_source_currency,
    }

def _looks_numeric(value) -> bool:
    """True if a cell holds a number (int/float) or a purely numeric string
    such as a type code, price or CO2 figure. Used to tell header rows (all
    text) apart from data rows (which carry numbers)."""
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return True
    if isinstance(value, str):
        s = value.strip().replace(".", "").replace(",", "").replace(" ", "")
        return s.isdigit()
    return False


def _populated_cols(row: tuple) -> set[int]:
    return {j for j, c in enumerate(row) if c is not None and str(c).strip()}


def _pick_header_index(all_rows: list[tuple], max_scan: int = 20) -> int:
    """Locate the real column-header row.

    The header is a predominantly-text row sitting directly ABOVE the data
    table, so its populated columns line up with the columns the data rows
    fill. Picking the *first* text row (the old behaviour) breaks on sheets
    that stack a title/date/paint-name banner above the header — e.g. Mazda's
    36 per-colour sheets, each with a different 'METALIK Soul crvena' banner:
    each banner was mistaken for the header, producing 36 distinct AND
    unmappable layouts instead of the one real header ('NAZIV MODELA, MSC,
    CO2 …') they all share. Scoring candidates by how many of their columns
    align with the data table below picks the true header in every one of
    them, collapsing 36 doomed LLM calls into a single good mapping.

    Score = (columns aligned with the data below, then width, then earliest).
    Falls back to 0 when nothing qualifies."""
    best_idx: int | None = None
    best_key = (-1, -1, 1)
    for i, row in enumerate(all_rows[:max_scan]):
        cols = _populated_cols(row)
        if len(cols) < 3:
            continue
        numeric = sum(1 for j in cols if _looks_numeric(row[j]))
        if numeric / len(cols) >= 0.3:  # a data row, not a header
            continue
        below = all_rows[i + 1 : i + 21]
        if not below:
            continue
        col_hits: dict[int, int] = {}
        for r in below:
            for j in _populated_cols(r):
                col_hits[j] = col_hits.get(j, 0) + 1
        threshold = max(2, int(0.4 * len(below)))
        data_cols = {j for j, n in col_hits.items() if n >= threshold}
        align = len(cols & data_cols)
        key = (align, len(cols), -i)
        if key > best_key:
            best_key = key
            best_idx = i
    return best_idx if best_idx is not None else 0


def _split_header_and_data(all_rows: list[tuple]) -> tuple[list[str], list[tuple]]:
    if not all_rows:
        return [], []
    idx = _pick_header_index(all_rows)
    header = [str(c) if c is not None else "" for c in all_rows[idx]]
    return header, all_rows[idx + 1:]


# A file yields one entry per worksheet: (sheet_name, header_row, data_rows).
# Reading every sheet (not just the active one) matters for split price lists —
# Mercedes commercial vehicles put Vito/Viano/Sprinter on separate sheets and
# smart lives on its own sheet, all of which were silently dropped when only
# wb.active was read.
Sheet = tuple[str, list[str], list[tuple]]


def _read_xlsx(path: Path) -> list[Sheet]:
    import openpyxl
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    sheets: list[Sheet] = []
    for ws in wb.worksheets:
        all_rows = list(ws.iter_rows(values_only=True))
        header, data = _split_header_and_data(all_rows)
        sheets.append((ws.title, header, data))
    wb.close()
    return sheets

def _read_xls(path: Path) -> list[Sheet]:
    import xlrd
    wb = xlrd.open_workbook(str(path))
    sheets: list[Sheet] = []
    for ws in wb.sheets():
        all_rows = [tuple(ws.row_values(r)) for r in range(ws.nrows)]
        header, data = _split_header_and_data(all_rows)
        sheets.append((ws.name, header, data))
    return sheets

def _read_file(path: Path) -> list[Sheet]:
    if path.suffix.lower() == ".xls":
        return _read_xls(path)
    return _read_xlsx(path)

def _ascii_slug(s: str) -> str:
    normalized = unicodedata.normalize("NFD", s)
    ascii_only = normalized.encode("ascii", "ignore").decode()
    slug = "".join(c if c.isalnum() or c == "-" else "-" for c in ascii_only).lower()
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-")

async def _reset_catalogue() -> None:
    """Wipe every catalogue row so the run repopulates from a clean slate.

    Ingest is upsert-only (on_conflict_do_update) — it can update or add rows
    but never deletes. So rows from an earlier, pre-fix ingestion (phantom
    brands from source typos, stray type-code brand cells, anything the current
    snap_brand logic would now skip) survive every re-run untouched, because
    their (brand, model, variant, valid_from) key never conflicts with a
    correctly-snapped row. This makes the cleanup reproducible: with --fresh,
    a single `python -m app.data.catalogues.ingest --fresh` gives a VPS the
    exact same clean table the manifest describes, no manual SQL required.

    Safe because nothing references catalogue by foreign key (only
    listings -> scrape_runs). TRUNCATE ... RESTART IDENTITY resets the id
    sequence too, so ids stay stable across full rebuilds."""
    async with AsyncSessionLocal() as session:
        await session.execute(text("TRUNCATE TABLE catalogue RESTART IDENTITY"))
        await session.commit()


async def _upsert_rows(rows: list[dict]) -> int:
    if not rows:
        return 0
    # Deduplicate by match_key
    seen: dict[str, dict] = {}
    for row in rows:
        seen[row["match_key"]] = row
    deduped = list(seen.values())

    # Sort by the actual unique-constraint columns so that two concurrent
    # upserts (different files, overlapping brands) always acquire row locks
    # in the same order. Without this, concurrent batches can lock the same
    # conflicting rows in opposite order and Postgres raises a deadlock.
    deduped.sort(key=lambda r: (r["brand"], r["model"], r["variant"], r["valid_from"]))

    total = 0
    # Batch size: 500 rows at a time (12 columns x 500 = 6000 params, well under 32767)
    batch_size = 500
    for i in range(0, len(deduped), batch_size):
        batch = deduped[i:i + batch_size]
        stmt = pg_insert(Catalogue).values(batch)
        # Every column here is DERIVED from ingest logic, so each one goes stale
        # the moment that logic is corrected and the file is re-ingested. The
        # set_ originally listed only price and CO2, which left the audit trail
        # actively lying: after the currency fix (canonical_schema.
        # _resolve_price_currency) re-ingested a row's price as EUR, its
        # source_currency still read "HRK", i.e. the column that exists to
        # explain how price_eur was derived contradicted it. The unique-key
        # columns (brand/model/variant/valid_from) are deliberately absent —
        # those identify the row rather than describe it.
        stmt = stmt.on_conflict_do_update(
            constraint="uq_catalogue_lookup_key",
            set_={
                "price_eur": stmt.excluded.price_eur,
                "co2_g_km": stmt.excluded.co2_g_km,
                "source_currency": stmt.excluded.source_currency,
                "fuel_type": stmt.excluded.fuel_type,
                "power_kw": stmt.excluded.power_kw,
                "co2_standard": stmt.excluded.co2_standard,
                "source_file": stmt.excluded.source_file,
            },
        )
        # Sorting makes deadlocks rare, not impossible, under high concurrency —
        # retry once on a fresh transaction before giving up on this batch.
        for attempt in range(2):
            try:
                async with AsyncSessionLocal() as session:
                    result = await session.execute(stmt)
                    await session.commit()
                total += result.rowcount or 0
                break
            except Exception as exc:
                orig = getattr(exc, "orig", None)
                if attempt == 0 and orig is not None and "deadlock" in str(orig).lower():
                    continue
                raise
    return total

async def _resolve_mapping(
    header_row: list[str],
    sample_rows: list[tuple],
    key: str,
    mapping_cache: dict[str, object],
    store: dict,
    mapping_locks: dict[str, asyncio.Lock],
    label: str,
    verbose: bool,
) -> object | None:
    """Return the ColumnMapping for this header layout, or None if it can't be
    mapped. Resolution order: in-memory cache → persistent store (both loaded
    up front) → one LLM call, whose verdict is written straight back to the
    store so it's never paid for again (here or on the VPS)."""
    if key in mapping_cache:
        cached = mapping_cache[key]
        if cached is None:
            if verbose:
                print(f"[skip] {label} — known-unmappable layout")
        elif verbose:
            print(f"[cache] {label}")
        return cached

    lock = mapping_locks.setdefault(key, asyncio.Lock())
    async with lock:
        # Re-check: another task may have resolved this layout while we waited.
        if key in mapping_cache:
            return mapping_cache[key]
        try:
            mapping = await asyncio.wait_for(
                map_sheet_columns(header_row, sample_rows, timeout_seconds=LLM_TIMEOUT_SECONDS),
                timeout=LLM_TIMEOUT_SECONDS * 2 + 5,
            )
        except (TimeoutError, httpx.HTTPError) as exc:
            # Transient — a property of the network, not the layout. Skip it for
            # this run but DON'T persist, so the next run retries it for free.
            print(f"[WARN] {label} — transient mapping error, will retry next run: {_short_error(exc)}")
            mapping_cache[key] = None
            return None
        except Exception as exc:
            # Deterministic rejection (hallucinated column / malformed response):
            # this layout always fails the same way, so persist the verdict and
            # never spend another call on it.
            print(f"[FAIL] {label} — mapping rejected: {exc}")
            mapping_cache[key] = None
            store[key] = mapping_store.fail_entry(str(exc)[:300], header_row)
            mapping_store.save(store)
            return None
        if mapping.confidence < SHEET_CONFIDENCE_THRESHOLD:
            print(
                f"[FAIL] {label} — confidence {mapping.confidence:.2f} "
                f"< {SHEET_CONFIDENCE_THRESHOLD:.2f}: {mapping.notes}"
            )
            mapping_cache[key] = None
            store[key] = mapping_store.fail_entry(
                f"confidence {mapping.confidence:.2f}: {mapping.notes[:200]}", header_row
            )
            mapping_store.save(store)
            return None
        mapping_cache[key] = mapping
        store[key] = mapping_store.ok_entry(mapping, header_row)
        mapping_store.save(store)
        if verbose:
            print(f"[map] {label} — confidence {mapping.confidence:.2f}")
        return mapping

async def _ingest_entry(
    entry: dict,
    mapping_cache: dict[str, object],
    store: dict,
    mapping_locks: dict[str, asyncio.Lock],
    semaphore: asyncio.Semaphore,
    dry_run: bool,
    verbose: bool,
) -> bool:
    folder_slug = entry["brand"]
    allowed_brands = FOLDER_BRANDS.get(folder_slug)
    filename = entry["filename"]
    path = Path(entry["path"])
    label = f"{folder_slug}/{filename}"

    # A file's parent folders often carry the year (…/opel/2013/Opel_01.07.xlsx)
    # when the filename itself only has a day+month. Pass the nearest /YYYY/
    # ancestor as a fallback for parse_valid_from.
    folder_year = next(
        (int(p.name) for p in path.parents if re.fullmatch(r"20[12]\d", p.name)),
        None,
    )
    valid_from_file = parse_valid_from(filename, folder_year)
    if valid_from_file is None:
        print(f"[WARN] {label} — cannot parse valid_from from filename, skipping")
        return False

    if not path.exists():
        print(f"[WARN] {label} — file not found at {path}, skipping")
        return False

    async with semaphore:
        try:
            sheets = await asyncio.to_thread(_read_file, path)
        except Exception as exc:
            print(f"[FAIL] {path} — read error: {exc}")
            return False

        co2_standard = _co2_standard_from_year(valid_from_file.year)

        # Each worksheet is mapped and applied independently — a split price list
        # can carry a different column layout per sheet (passenger vs commercial),
        # and the mapping cache is keyed by header fingerprint so this stays
        # one LLM call per distinct layout regardless of sheet count.
        catalogue_dicts: list[dict] = []
        total_skipped = 0
        any_sheet_ok = False

        for sheet_name, header_row, data_rows in sheets:
            if not header_row or not data_rows:
                continue
            if not any(c and c.strip() for c in header_row):
                # Blank header row — no column names to map; skip this sheet
                # without spending an LLM call (a title-only cover sheet, etc.).
                continue
            key = mapping_store.fingerprint_key(header_row)

            sheet_label = f"{label}#{sheet_name}"
            mapping = await _resolve_mapping(
                header_row, list(data_rows[:5]), key,
                mapping_cache, store, mapping_locks, sheet_label, verbose,
            )
            if mapping is None:
                continue

            skip_log: list[tuple[int, str]] = []
            try:
                canonical_rows = apply_mapping(
                    rows=list(data_rows),
                    header_row=header_row,
                    mapping=mapping,
                    source_file=str(path),
                    source_sheet=sheet_name,
                    skip_log=skip_log,
                    default_valid_from=valid_from_file,
                )
            except Exception as exc:
                print(f"[FAIL] {sheet_label} — apply_mapping error: {exc}")
                continue

            any_sheet_ok = True
            skipped = len(skip_log)
            for row in canonical_rows:
                d = _to_catalogue_dict(row, co2_standard, allowed_brands)
                if d is None:
                    skipped += 1
                else:
                    catalogue_dicts.append(d)
            total_skipped += skipped

        if not any_sheet_ok and not catalogue_dicts:
            print(f"[FAIL] {path} — no usable sheet (empty/blank-header/mapping failed)")
            return False

        if dry_run:
            if verbose:
                print(f"[DRY RUN] {label} — {len(catalogue_dicts)} rows ready, {total_skipped} skipped")
            else:
                print(f"[DRY RUN] {label} — {len(catalogue_dicts)} rows ready")
            return True

        try:
            upserted = await _upsert_rows(catalogue_dicts)
            if verbose:
                print(f"[OK] {label} — {upserted} rows inserted / {total_skipped} skipped")
            return True
        except Exception as exc:
            print(f"[FAIL] {path} — DB write failed: {_short_error(exc)}")
            return False

async def _main(brand_filter: str | None, dry_run: bool, verbose: bool, concurrency: int, fresh: bool) -> None:
    if fresh and brand_filter:
        # --fresh truncates the whole table; scoping it to one brand would
        # silently wipe every other brand's rows too. Refuse rather than
        # surprise-delete data the user didn't mean to touch.
        print("ERROR: --fresh cannot be combined with --brand (it wipes the whole table).", file=sys.stderr)
        sys.exit(1)

    if not MANIFEST_PATH.exists():
        print(f"ERROR: manifest not found at {MANIFEST_PATH}", file=sys.stderr)
        sys.exit(1)

    entries: list[dict] = []
    with MANIFEST_PATH.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError as exc:
                print(f"[WARN] bad manifest line: {exc}")
                continue
            if brand_filter:
                canonical_brand = entry.get("brand", "")
                if canonical_brand != brand_filter and _ascii_slug(canonical_brand) != _ascii_slug(brand_filter):
                    continue
            entries.append(entry)

    if not entries:
        suffix = f" for brand '{brand_filter}'" if brand_filter else ""
        print(f"No manifest entries{suffix}.")
        return

    suffix = f" for brand '{brand_filter}'" if brand_filter else ""
    print(f"Processing {len(entries)} file(s){suffix}...")

    if fresh and not dry_run:
        print("Truncating catalogue table (--fresh)...")
        await _reset_catalogue()

    # Persistent, committed mapping store: LLM verdicts learned in earlier runs
    # are reused here (and on the VPS) with zero new API calls. The in-memory
    # cache is seeded from it so cache hits skip straight past the LLM.
    store = mapping_store.load()
    mapping_cache: dict[str, object] = {
        key: mapping_store.entry_to_mapping(entry) for key, entry in store.items()
    }
    if store:
        ok = sum(1 for e in store.values() if e.get("status") == "ok")
        print(f"Loaded {len(store)} cached header layouts ({ok} mappable) — these cost no LLM calls.")
    mapping_locks: dict[str, asyncio.Lock] = {}
    semaphore = asyncio.Semaphore(concurrency)

    try:
        results = await asyncio.gather(
            *(_ingest_entry(entry, mapping_cache, store, mapping_locks, semaphore, dry_run, verbose) for entry in entries)
        )
    finally:
        # Persist whatever we learned even if the run is interrupted, so an
        # abort never re-charges for mappings already resolved.
        mapping_store.save(store)

    ok_count = sum(1 for r in results if r)
    fail_count = len(results) - ok_count

    print(f"Done. {ok_count} succeeded, {fail_count} failed.")
    print(f"Mapping store now holds {len(store)} header layouts at {mapping_store.STORE_PATH}")

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ingest all catalogue files from manifest.jsonl into the catalogue DB table."
    )
    parser.add_argument("--brand", metavar="SLUG", help="Process only this brand slug (e.g. bmw-mini)")
    parser.add_argument("--dry-run", action="store_true", help="Parse and map but don't write to DB")
    parser.add_argument("--verbose", action="store_true", help="Show cache hits and per-file details")
    parser.add_argument(
        "--concurrency", type=int, default=48,
        help="Max files processed in parallel (default: 48). Raised from 32: "
             "the pipeline is timeout-bound, not rate-limited (no 429s seen), "
             "so more in-flight calls shorten the one-time build.",
    )
    parser.add_argument(
        "--fresh", action="store_true",
        help="Truncate the catalogue table before ingesting, so a re-run "
             "removes stale/phantom rows from earlier ingestions instead of "
             "leaving them (ingest is otherwise upsert-only). Cannot be used "
             "with --brand.",
    )
    args = parser.parse_args()
    asyncio.run(_main(args.brand, args.dry_run, args.verbose, args.concurrency, args.fresh))

if __name__ == "__main__":
    main()
