"""One-off migration: add the ip_hash column to apify_events.

app/main.py's startup hook only runs Base.metadata.create_all, which creates
missing tables but never alters existing ones. apify_events already existed
before ip_hash was added to the ApifyEvent model (app/db/models.py), so this
adds the column by hand. Safe to run multiple times (IF NOT EXISTS).

Run once:
    .venv/bin/python -m scripts.migrate_apify_events_ip_hash
"""

import asyncio
import sys

from sqlalchemy import text

from app.db.session import engine


async def main() -> None:
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "ALTER TABLE apify_events "
                "ADD COLUMN IF NOT EXISTS ip_hash VARCHAR(64) NOT NULL DEFAULT ''"
            )
        )
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_apify_events_ip_hash "
                "ON apify_events (ip_hash)"
            )
        )
    print("apify_events.ip_hash column + index ensured.")


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
