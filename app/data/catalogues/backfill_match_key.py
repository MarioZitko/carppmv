"""One-off backfill: recompute Catalogue.match_key for every row.

match_key is computed once at ingestion time (ingest.py) and persisted, not
derived on the fly — so a change to normalize_text()/build_match_key() in
app/catalogue/matching.py (e.g. the digit+trim-code tokenization fix) does
NOT retroactively affect rows already in the database. Run this after any
such change to bring existing rows in line with the current normalization,
otherwise fuzzy search keeps scoring against stale tokens.

Usage:
    python -m app.data.catalogues.backfill_match_key [--dry-run]
"""

import argparse
import asyncio

from sqlalchemy import select

from app.catalogue.matching import build_match_key
from app.db.models import Catalogue
from app.db.session import AsyncSessionLocal

_BATCH_SIZE = 500


async def backfill(dry_run: bool = False) -> None:
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(select(Catalogue))).scalars().all()
        changed = 0
        for i, row in enumerate(rows):
            new_key = build_match_key(row.brand, row.model, row.variant)
            if new_key != row.match_key:
                changed += 1
                if not dry_run:
                    row.match_key = new_key
            if not dry_run and (i + 1) % _BATCH_SIZE == 0:
                await session.commit()
        if not dry_run:
            await session.commit()
        print(f"{'Would update' if dry_run else 'Updated'} {changed}/{len(rows)} rows.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Report the count without writing.")
    args = parser.parse_args()
    asyncio.run(backfill(dry_run=args.dry_run))


if __name__ == "__main__":
    main()
