"""Client IP resolution and hashing for the mobile.de abuse-protection layer.

Raw client IPs are never stored or logged — only sha256(salt + ip) is, via
client_ip_hash(). Callers needing the raw IP for one-off use (e.g. passing it
to Cloudflare's Turnstile siteverify) should use resolve_client_ip() directly
and not persist the result.
"""

import hashlib

from fastapi import Request

from app.core.config import get_settings


def resolve_client_ip(request: Request) -> str:
    """Behind Caddy, the first hop of X-Forwarded-For is the real client IP;
    fall back to the direct connection when the header is absent (local dev)."""
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.client.host if request.client else ""


def client_ip_hash(request: Request) -> str:
    settings = get_settings()
    ip = resolve_client_ip(request)
    return hashlib.sha256((settings.ip_hash_salt + ip).encode()).hexdigest()
