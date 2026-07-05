"""One-off migration of the committed LLM mapping cache to the normalized
fingerprint, in preparation for the reworked ingest.

Two things change at once in the rework:

  1. `mapping_store.fingerprint_key` now hashes *normalized* header cells
     (case/whitespace/newline/trailing-punctuation folded), so near-duplicate
     layouts collapse to one key. Every existing key is therefore stale.
  2. The rejected-layout logic changed (nullable brand/fuel/valid_from,
     per-sheet enum schema, hardened prompt). The old "fail" verdicts were
     produced by the OLD, stricter logic and must NOT be trusted anymore —
     they are the very sheets the rework is meant to recover.

So this script:
  * re-keys every "ok" entry under the new fingerprint (deduping collisions),
    preserving the paid ColumnMapping values — those stay valid because the
    stored exact column names are snapped to each sheet's real header by
    canonical_schema._resolve_columns at apply time;
  * DROPS every "fail" entry, so the next `--fresh` build re-evaluates those
    layouts once under the new logic (this is the intended one paid build).

A handful of very wide sheets (>24 non-empty columns) had their audit
`sample_header` truncated at store time, so their recomputed key won't match
the build-time key computed from the full header — those few re-pay once. That
is expected and cheap.

Run once, then commit the rewritten column_mappings.json:
    .venv/bin/python -m scripts.migrate_mapping_cache
"""

import shutil
import sys
from collections import Counter

from app.catalogue import mapping_store


def main() -> None:
    store = mapping_store.load()
    if not store:
        print(f"No cache found at {mapping_store.STORE_PATH}; nothing to migrate.")
        return

    status = Counter(e.get("status") for e in store.values())
    print(f"Loaded {len(store)} entries: {dict(status)}")

    backup = mapping_store.STORE_PATH.with_suffix(".json.pre-migration.bak")
    shutil.copy2(mapping_store.STORE_PATH, backup)
    print(f"Backed up original to {backup}")

    migrated: dict = {}
    kept, collisions, dropped_fail, dropped_other = 0, 0, 0, 0
    for entry in store.values():
        if entry.get("status") != "ok":
            if entry.get("status") == "fail":
                dropped_fail += 1
            else:
                dropped_other += 1
            continue
        sample = entry.get("sample_header") or []
        new_key = mapping_store.fingerprint_key(sample)
        if new_key in migrated:
            collisions += 1  # identical layout under normalization — keep first
            continue
        migrated[new_key] = entry
        kept += 1

    mapping_store.save(migrated)
    print(
        f"Migrated: kept {kept} ok entries "
        f"({collisions} collapsed as normalized duplicates), "
        f"dropped {dropped_fail} fail + {dropped_other} other "
        f"(these layouts re-evaluate under the new logic on the next build)."
    )
    print(f"Wrote {len(migrated)} entries to {mapping_store.STORE_PATH}")
    print("Review the diff, then commit column_mappings.json.")


if __name__ == "__main__":
    sys.exit(main())
