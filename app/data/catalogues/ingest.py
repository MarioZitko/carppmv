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
import sys
import unicodedata
from pathlib import Path

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.pool import NullPool

from app.catalogue.canonical_schema import CanonicalRow, FuelCategory, apply_mapping
from app.catalogue.llm_mapper import map_sheet_columns
from app.catalogue.matching import build_match_key
from app.data.catalogues.parse_date import parse_valid_from
from app.db.models import CO2Standard, Catalogue, FuelType
from app.db.session import engine, AsyncSessionLocal, create_async_engine
from app.core.config import get_settings

MANIFEST_PATH = Path(__file__).parent / "manifest.jsonl"

# Sheets below this confidence are skipped entirely — the LLM could not
# reliably identify required fields and ingesting would produce garbage.
SHEET_CONFIDENCE_THRESHOLD = 0.6

_FUEL_CATEGORY_TO_DB: dict[FuelCategory, FuelType | None] = {
    FuelCategory.DIESEL: FuelType.DIESEL,
    FuelCategory.PETROL: FuelType.PETROL,
    FuelCategory.PETROL_HYBRID: FuelType.PETROL,
    FuelCategory.PETROL_PLUG_IN_HYBRID: FuelType.PETROL,
    FuelCategory.ELECTRIC: None,   # PPMV-exempt — no catalogue row needed
    FuelCategory.UNKNOWN: None,    # needs_review already set; don't insert bad data
}

_FUEL_OVERRIDE_PATTERNS: list[tuple[list[str], FuelType | None]] = [
    # Brand-agnostic patterns (lowest priority)
    ([".*tdi.*", ".*diesel.*"], FuelType.DIESEL),
    ([".*tfsi.*", ".*tsi.*", ".*benzin.*"], FuelType.PETROL),

    # BMW specific: "d" suffix after digits => Diesel, "i" suffix => Petrol
    (["^.*[0-9]+d[^a-z]*$"], FuelType.DIESEL),
    (["^.*[0-9]+i[^a-z]*$"], FuelType.PETROL),

    # Mercedes: "d" suffix => Diesel, "e" => Petrol hybrid
    (["^.*[0-9]+d[^a-z]*$"], FuelType.DIESEL),
    (["^.*[0-9]+e[^a-z]*$"], FuelType.PETROL),
]

def _override_fuel_from_variant(
    brand: str,
    model: str,
    variant: str,
    mapped_fuel: FuelType | None,
) -> FuelType | None:
    """Check variant text against known patterns. If a pattern matches and
    conflicts with the LLM's guess, trust the pattern (they're deterministic)."""
    text_to_check = f"{brand} {model} {variant}".lower()
    import re
    for patterns, correct_fuel in _FUEL_OVERRIDE_PATTERNS:
        if any(re.search(p, text_to_check) for p in patterns):
            return correct_fuel
    return mapped_fuel

def _co2_standard_from_year(year: int) -> CO2Standard:
    return CO2Standard.WLTP if year >= 2021 else CO2Standard.NEDC

def _to_catalogue_dict(row: CanonicalRow, co2_standard: CO2Standard) -> dict | None:
    mapped_fuel = _FUEL_CATEGORY_TO_DB.get(row.fuel_category)
    fuel_type = _override_fuel_from_variant(
        brand=row.brand,
        model=row.model_name or row.type_code or "unknown",
        variant=row.full_name or row.type_code or row.model_name or "unknown",
        mapped_fuel=mapped_fuel,
    )

    model = row.model_name or row.type_code or "unknown"
    variant = row.full_name or row.type_code or row.model_name or "unknown"

    return {
        "brand": row.brand,
        "model": model,
        "variant": variant,
        "match_key": build_match_key(row.brand, model, variant),
        "price_eur": row.price_eur,
        "co2_g_km": row.co2_g_km,
        "co2_standard": co2_standard,
        "fuel_type": fuel_type,
        "power_kw": row.power_kw,
        "valid_from": row.valid_from,
        "source_file": row.source_file,
        "source_currency": row.price_source_currency,
    }

def _read_xlsx(path: Path) -> tuple[list[str], list[tuple]]:
    import openpyxl
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    ws = wb.active
    all_rows = list(ws.iter_rows(values_only=True))
    wb.close()
    if not all_rows:
        return [], []
    header = [str(c) if c is not None else "" for c in all_rows[0]]
    return header, all_rows[1:]

def _read_xls(path: Path) -> tuple[list[str], list[tuple]]:
    import xlrd
    wb = xlrd.open_workbook(str(path))
    ws = wb.sheet_by_index(0)
    if ws.nrows == 0:
        return [], []
    header = [str(c) if c is not None else "" for c in ws.row_values(0)]
    data = [tuple(ws.row_values(r)) for r in range(1, ws.nrows)]
    return header, data

def _read_file(path: Path) -> tuple[list[str], list[tuple]]:
    if path.suffix.lower() == ".xls":
        return _read_xls(path)
    return _read_xlsx(path)

def _header_fingerprint(header_row: list[str]) -> frozenset[str]:
    return frozenset(c for c in header_row if c.strip())

def _ascii_slug(s: str) -> str:
    normalized = unicodedata.normalize("NFD", s)
    ascii_only = normalized.encode("ascii", "ignore").decode()
    slug = "".join(c if c.isalnum() or c == "-" else "-" for c in ascii_only).lower()
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-")

async def _upsert_rows(rows: list[dict]) -> int:
    if not rows:
        return 0
    # Deduplicate by match_key
    seen: dict[str, dict] = {}
    for row in rows:
        seen[row["match_key"]] = row
    deduped = list(seen.values())

    total = 0
    # Batch size: 500 rows at a time (12 columns x 500 = 6000 params, well under 32767)
    batch_size = 500
    async with AsyncSessionLocal() as session:
        for i in range(0, len(deduped), batch_size):
            batch = deduped[i:i + batch_size]
            stmt = pg_insert(Catalogue).values(batch)
            stmt = stmt.on_conflict_do_update(
                constraint="uq_catalogue_lookup_key",
                set_={
                    "price_eur": stmt.excluded.price_eur,
                    "co2_g_km": stmt.excluded.co2_g_km,
                },
            )
            result = await session.execute(stmt)
            total += result.rowcount or 0
        await session.commit()
    return total

async def _ingest_entry(
    entry: dict,
    mapping_cache: dict[frozenset, object],
    dry_run: bool,
    verbose: bool,
) -> None:
    brand = entry["brand"]
    filename = entry["filename"]
    path = Path(entry["path"])
    label = f"{brand}/{filename}"

    valid_from_file = parse_valid_from(filename)
    if valid_from_file is None:
        print(f"[WARN] {label} — cannot parse valid_from from filename, skipping")
        return

    if not path.exists():
        print(f"[WARN] {label} — file not found at {path}, skipping")
        return

    try:
        header_row, data_rows = _read_file(path)
    except Exception as exc:
        print(f"[FAIL] {path} — read error: {exc}")
        return

    if not header_row or not data_rows:
        print(f"[FAIL] {path} — empty file or no data rows")
        return

    fingerprint = _header_fingerprint(header_row)

    if fingerprint in mapping_cache:
        if verbose:
            print(f"[cache] {label}")
        mapping = mapping_cache[fingerprint]
    else:
        try:
            mapping = map_sheet_columns(header_row, list(data_rows[:5]))
        except Exception as exc:
            print(f"[FAIL] {path} — mapping failed: {exc}")
            return
        if mapping.confidence < SHEET_CONFIDENCE_THRESHOLD:
            print(
                f"[FAIL] {path} — confidence {mapping.confidence:.2f} "
                f"< {SHEET_CONFIDENCE_THRESHOLD:.2f}: {mapping.notes}"
            )
            return
        mapping_cache[fingerprint] = mapping

    co2_standard = _co2_standard_from_year(valid_from_file.year)
    skip_log: list[tuple[int, str]] = []

    try:
        canonical_rows = apply_mapping(
            rows=list(data_rows),
            header_row=header_row,
            mapping=mapping,
            source_file=str(path),
            source_sheet=path.stem,
            skip_log=skip_log,
        )
    except Exception as exc:
        print(f"[FAIL] {path} — apply_mapping error: {exc}")
        return

    catalogue_dicts: list[dict] = []
    skipped_fuel = 0
    for row in canonical_rows:
        d = _to_catalogue_dict(row, co2_standard)
        if d is None:
            skipped_fuel += 1
        else:
            catalogue_dicts.append(d)

    total_skipped = len(skip_log) + skipped_fuel

    if dry_run:
        if verbose:
            print(f"[DRY RUN] {label} — {len(catalogue_dicts)} rows ready, {total_skipped} skipped")
        else:
            print(f"[DRY RUN] {label} — {len(catalogue_dicts)} rows ready")
        return

    try:
        upserted = await _upsert_rows(catalogue_dicts)
        if verbose:
            print(f"[OK] {label} — {upserted} rows inserted / {total_skipped} skipped")
    except Exception as exc:
        print(f"[FAIL] {path} — DB write failed: {exc}")

async def _main(brand_filter: str | None, dry_run: bool, verbose: bool) -> None:
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

    mapping_cache: dict[frozenset, object] = {}
    ok_count = 0
    fail_count = 0
    for entry in entries:
        await _ingest_entry(entry, mapping_cache, dry_run, verbose)

    print(f"Done. {ok_count} succeeded, {fail_count} failed.")

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ingest all catalogue files from manifest.jsonl into the catalogue DB table."
    )
    parser.add_argument("--brand", metavar="SLUG", help="Process only this brand slug (e.g. bmw-mini)")
    parser.add_argument("--dry-run", action="store_true", help="Parse and map but don't write to DB")
    parser.add_argument("--verbose", action="store_true", help="Show cache hits and per-file details")
    args = parser.parse_args()
    asyncio.run(_main(args.brand, args.dry_run, args.verbose))

if __name__ == "__main__":
    main()