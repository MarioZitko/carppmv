"""Common interface every site extractor implements.

New site? Add one file implementing this Protocol — nothing else changes.
"""

from typing import Protocol

from app.scraping.schemas import ListingData


class Extractor(Protocol):
    async def extract(self, url: str) -> ListingData:
        """Fetches the page (per its configured engine) and returns normalized data."""
        ...