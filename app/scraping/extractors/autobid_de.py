"""autobid.de extractor — plain httpx, no browser needed (confirmed v7 §2.6)."""

import httpx

from app.core.exceptions import ScrapingError
from app.scraping.schemas import ListingData


class AutobidDeExtractor:
    async def extract(self, url: str) -> ListingData:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(url)
            if response.status_code != 200:
                raise ScrapingError(f"autobid.de returned {response.status_code} for {url}")

            # TODO: parse response.text with an HTML parser (selectolax/lxml)
            # once the field selectors are finalized.
            return ListingData(source_url=url, source_site="autobid.de")