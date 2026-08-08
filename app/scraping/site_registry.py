"""Shared site-detection + extractor registry.

Both app/calculate/router.py and app/scraping/router.py need to (a) map a
listing URL to a site name and (b) dispatch to that site's Extractor. This
used to be defined identically in both files; kept here once so a new site
(or a detection-logic fix) only needs to change one place.

mobile.de is deliberately excluded from EXTRACTORS — it has no local
Extractor, it goes through the Apify-backed guard stack in
mobile_de_guard.py/mobile_de_service.py instead. Callers check
`site == MOBILE_DE_SITE` separately, same as before.
"""

from app.db.models import ScrapeSite
from app.scraping.engines import SITE_ENGINE_MAP
from app.scraping.extractors.autobid_de import AutobidDeExtractor
from app.scraping.extractors.autoscout24 import AutoScout24Extractor
from app.scraping.extractors.base import Extractor
from app.scraping.extractors.njuskalo import NjuskaloExtractor

EXTRACTORS: dict[str, Extractor] = {
    "autobid.de": AutobidDeExtractor(),
    "autoscout24": AutoScout24Extractor(),
    "njuskalo": NjuskaloExtractor(),
}

# Maps the site-detection string (the SITE_ENGINE_MAP/EXTRACTORS key) to the
# ScrapeSite enum value used by the ScrapeRun/Listing tables — the two don't
# share spelling ("njuskalo" vs ScrapeSite.NJUSKALO == "njuskalo.hr").
SITE_TO_SCRAPE_SITE: dict[str, ScrapeSite] = {
    "mobile.de": ScrapeSite.MOBILE_DE,
    "njuskalo": ScrapeSite.NJUSKALO,
    "autoscout24": ScrapeSite.AUTOSCOUT24,
    "autobid.de": ScrapeSite.AUTOBID_DE,
}


def detect_site(url: str) -> str:
    for site in SITE_ENGINE_MAP:
        if site in url:
            return site
    return ""
