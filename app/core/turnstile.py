"""Cloudflare Turnstile bot-check for the mobile.de on-demand scraping path."""

import httpx

from app.core.config import get_settings

_SITEVERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"


async def verify_turnstile(token: str | None, ip: str) -> bool:
    """Returns True if the Turnstile token is valid. When turnstile_secret_key
    is unset (dev default), verification is disabled and this always returns
    True — set the key in production to enforce the bot-check."""
    settings = get_settings()
    if not settings.turnstile_secret_key:
        return True

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                _SITEVERIFY_URL,
                data={"secret": settings.turnstile_secret_key, "response": token or "", "remoteip": ip},
            )
        response.raise_for_status()
        return bool(response.json().get("success"))
    except (httpx.HTTPStatusError, httpx.TransportError, ValueError):
        # Cloudflare unreachable/5xx or a malformed body — fail closed rather
        # than let the exception escape as an unhandled 500. A bot-check that
        # can't be verified is treated the same as a failed bot-check.
        return False
