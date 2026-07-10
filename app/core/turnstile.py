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

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(
            _SITEVERIFY_URL,
            data={"secret": settings.turnstile_secret_key, "response": token or "", "remoteip": ip},
        )
    return bool(response.json().get("success"))
