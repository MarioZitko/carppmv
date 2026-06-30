"""Per-site fetch-engine configuration.

Confirmed (v7 §2.6): engine choice is per-site, not hardcoded — Akamai on
mobile.de specifically blocks Chromium but passes Firefox; autobid.de needs
no browser at all.
"""

from enum import Enum


class FetchEngine(str, Enum):
    CHROMIUM = "chromium"
    FIREFOX = "firefox"
    HTTPX = "httpx"


SITE_ENGINE_MAP: dict[str, FetchEngine] = {
    "mobile.de": FetchEngine.FIREFOX,
    "njuskalo": FetchEngine.CHROMIUM,
    "autoscout24": FetchEngine.CHROMIUM,
    "autobid.de": FetchEngine.HTTPX,
}