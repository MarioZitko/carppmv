import asyncio
from sqlalchemy import text
from app.db.session import AsyncSessionLocal

async def clean_brands():
    async with AsyncSessionLocal() as session:
        await session.execute(text("""
            UPDATE catalogue SET brand =
                CASE
                    WHEN UPPER(REGEXP_REPLACE(REPLACE(brand, ',', ''), '\s+', ' ', 'g')) = 'AUDI' THEN 'Audi'
                    WHEN UPPER(REGEXP_REPLACE(REPLACE(brand, ',', ''), '\s+', ' ', 'g')) = 'PORSCHE' THEN 'Porsche'
                    WHEN UPPER(REGEXP_REPLACE(REPLACE(brand, ',', ''), '\s+', ' ', 'g')) = 'SEAT' THEN 'Seat'
                    WHEN UPPER(REGEXP_REPLACE(REPLACE(brand, ',', ''), '\s+', ' ', 'g')) = 'SKODA' THEN 'Škoda'
                    WHEN UPPER(REGEXP_REPLACE(REPLACE(brand, ',', ''), '\s+', ' ', 'g')) = 'CUPRA' THEN 'Cupra'
                    WHEN UPPER(REGEXP_REPLACE(REPLACE(brand, ',', ''), '\s+', ' ', 'g')) = 'VOLKSWAGEN VW' THEN 'Volkswagen'
                    WHEN UPPER(REGEXP_REPLACE(REPLACE(brand, ',', ''), '\s+', ' ', 'g')) = 'VOLKSWAGEN' THEN 'Volkswagen'
                    ELSE INITCAP(brand)
                END
        """))
        await session.commit()
        print('Brands cleaned')

asyncio.run(clean_brands())