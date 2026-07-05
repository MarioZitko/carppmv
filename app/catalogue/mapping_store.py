"""Persistent, committed store of LLM column-mappings.

The LLM column-mapping is the only expensive, non-deterministic step in
catalogue ingestion (one OpenRouter call per distinct header layout). Nothing
about a given header layout changes between runs, so paying for it on every
run — and again on the VPS — is pure waste. This module makes the mapping a
build-once artifact:

  * keyed by a stable hash of the header cells (machine-independent),
  * holding either a resolved ColumnMapping ("ok") or a deterministic
    rejection ("fail": low confidence / hallucinated column),
  * written incrementally so an interrupted run never re-charges for work it
    already did, and
  * committed to the repo (column_mappings.json) so `ingest` on the VPS reads
    it and makes ZERO LLM calls.

Transient failures (timeouts, 5xx, rate limits) are deliberately NOT stored —
they aren't a property of the header layout, so the next run should retry them.
Only "ok" and deterministic "fail" verdicts are persisted.
"""

import hashlib
import json
from dataclasses import asdict
from pathlib import Path

from app.catalogue.canonical_schema import ColumnMapping, normalize_cell

STORE_PATH = Path(__file__).parent.parent / "data" / "catalogues" / "column_mappings.json"

# Cap how much of the header we keep for human auditing — enough to recognise
# the layout, not so much that the file bloats on wide sheets.
_SAMPLE_HEADER_CELLS = 24


def fingerprint_key(header_row: list[str]) -> str:
    """Stable content hash of a header row's non-empty cells, order-independent.

    Two sheets with the same set of column labels map identically, so they must
    share a key regardless of column order or which machine computes it. sha1 of
    the sorted, NORMALIZED cells gives a short, deterministic, JSON-safe key —
    normalization (normalize_cell) folds cosmetic differences (case, stray
    newlines/spaces, trailing punctuation) so near-duplicate headers collapse to
    one key instead of each costing its own LLM call."""
    cells = sorted({normalize_cell(c) for c in header_row if c and normalize_cell(c)})
    blob = "".join(cells)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()


def load(path: Path = STORE_PATH) -> dict:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def save(data: dict, path: Path = STORE_PATH) -> None:
    """Atomic write (tmp + replace) so a crash mid-write can't corrupt the
    committed file. Called synchronously between awaits — safe under asyncio's
    single thread, no lock needed."""
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1, sort_keys=True)
    tmp.replace(path)


def entry_to_mapping(entry: dict) -> "ColumnMapping | None":
    """Rebuild a ColumnMapping from a stored 'ok' entry, or None for a 'fail'."""
    if not entry or entry.get("status") != "ok":
        return None
    return ColumnMapping(**entry["mapping"])


def ok_entry(mapping: ColumnMapping, header_row: list[str]) -> dict:
    return {
        "status": "ok",
        "confidence": mapping.confidence,
        "mapping": asdict(mapping),
        "sample_header": [c for c in header_row if c and c.strip()][:_SAMPLE_HEADER_CELLS],
    }


def fail_entry(reason: str, header_row: list[str]) -> dict:
    return {
        "status": "fail",
        "reason": reason,
        "sample_header": [c for c in header_row if c and c.strip()][:_SAMPLE_HEADER_CELLS],
    }
