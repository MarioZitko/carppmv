"""Per-site fetch-engine configuration.

Confirmed (v7 §2.6): engine choice is per-site, not hardcoded — autobid.de
needs no browser at all. mobile.de is behind Akamai Bot Manager and is no
longer fetched directly (Chromium blocked outright, Firefox worked once then
got IP-flagged) — it now goes through the Apify actor instead, a plain HTTPS
call, see app/scraping/fetchers/apify_mobile_de.py.
"""

from enum import Enum


class FetchEngine(str, Enum):
    CHROMIUM = "chromium"
    FIREFOX = "firefox"
    HTTPX = "httpx"
    APIFY = "apify"


SITE_ENGINE_MAP: dict[str, FetchEngine] = {
    "mobile.de": FetchEngine.APIFY,
    "njuskalo": FetchEngine.CHROMIUM,
    "autoscout24": FetchEngine.CHROMIUM,
    "autobid.de": FetchEngine.HTTPX,
}
