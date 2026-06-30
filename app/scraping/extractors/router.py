"""HTTP layer for on-demand single-URL scraping."""

from fastapi import APIRouter

from app.scraping.engines import SITE_ENGINE_MAP
from app.scraping.extractors.autobid_de import AutobidDeExtractor
from app.scraping.schemas import ListingData
from app.core.exceptions import ScrapingError

router = APIRouter()

# Maps site key -> extractor instance. Extend as each extractor is implemented.
_EXTRACTORS = {
    "autobid.de": AutobidDeExtractor(),
}


def _detect_site(url: str) -> str:
    for site in SITE_ENGINE_MAP:
        if site in url:
            return site
    raise ScrapingError(f"Unrecognized site for URL: {url}")


@router.post("/preview", response_model=ListingData)
async def preview(url: str) -> ListingData:
    site = _detect_site(url)
    extractor = _EXTRACTORS.get(site)
    if extractor is None:
        raise ScrapingError(f"No extractor implemented yet for {site}")
    return await extractor.extract(url)