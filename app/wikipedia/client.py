"""Throttled, authenticated MediaWiki API client for the Phase 0 crawl.

Wikimedia's API etiquette is enforced infrastructure-side, not just asked for:

- **User-Agent**: a descriptive UA with a contact address is *required*. A
  default library UA (``python-httpx/x.y``) is routed into a stricter
  rate-limit tier, so setting this is correctness, not politeness.
- **Concurrency**: 3 in-flight requests for a logged-in client, 2 anonymous.
  ``max_concurrency`` is a hard ceiling — raising it because "it seems to
  work" is exactly the behavior that gets a client blocked.
- **429**: backed off with 3 retries, doubling from 5s, honoring
  ``Retry-After`` when the response carries it.

Login uses the bot password from Special:BotPasswords. ``action=clientlogin``
is tried first (the modern entry point); MediaWiki restricts bot passwords to
the legacy ``action=login`` on many wikis, so that is the documented fallback
rather than a hack. Either way the result is verified with ``meta=userinfo``
before the crawl trusts it — a silently-anonymous session would quietly run at
the lower tier all night.
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)

# action=query&titles= accepts 50 titles per call for normal users (500 for
# bots with apihighlimits). 50 is the safe universal ceiling.
TITLES_PER_QUERY = 50

MAX_429_RETRIES = 3
INITIAL_BACKOFF_SECONDS = 5.0


class WikipediaAPIError(RuntimeError):
    """API returned an error object, or an unusable response shape."""


@dataclass
class RequestStats:
    """Counters for the run report — total requests, 429s, retries."""

    requests: int = 0
    http_429: int = 0
    retries: int = 0
    errors: int = 0


@dataclass
class TitleResolution:
    """What the API says about one requested title.

    ``resolved_title`` is the title AFTER normalization and redirect
    following — the page the wikitext actually lives on. ``fragment`` is set
    when the redirect itself targeted a section (``#REDIRECT [[X#Y]]``), which
    matters because that section, not the whole article, is the generation's
    data.
    """

    requested: str
    resolved_title: str | None
    exists: bool
    fragment: str | None = None
    is_disambiguation: bool = False


@dataclass
class WikitextResult:
    title: str
    status: str  # "ok" | "not_found" | "error"
    wikitext: str | None = None
    error: str | None = None


@dataclass
class _RateGate:
    """Spaces request *starts* so that, with ``concurrency`` workers, each
    worker issues at most one request per ``per_worker_delay`` seconds.

    Implemented as one global minimum gap rather than per-task timers: with N
    workers each waiting D seconds between its own requests, the aggregate
    rate is N/D req/s, which is the same as one shared gap of D/N. This way
    the ceiling holds no matter how tasks are scheduled.
    """

    min_gap: float
    _next_allowed: float = 0.0
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def wait(self) -> None:
        async with self._lock:
            now = time.monotonic()
            delay = max(0.0, self._next_allowed - now)
            self._next_allowed = max(now, self._next_allowed) + self.min_gap
        if delay:
            await asyncio.sleep(delay)


def build_user_agent() -> str:
    """Wikimedia-policy User-Agent, e.g.
    ``kalkulatoruvoza-co2-crawler/1.0 (https://…; you@example.com) httpx/0.27``.
    """
    s = get_settings()
    return (
        f"{s.wiki_user_agent_product} "
        f"({s.wiki_site_url}; {s.wiki_contact_email}) "
        f"httpx/{httpx.__version__}"
    )


class WikipediaClient:
    """Async MediaWiki client. Use as an async context manager."""

    def __init__(
        self,
        api_url: str | None = None,
        concurrency: int | None = None,
        per_worker_delay: float | None = None,
        timeout_seconds: float = 60.0,
    ) -> None:
        s = get_settings()
        self.api_url = api_url or s.wiki_api_url
        # Hard ceiling — never above the configured policy limit, even if a
        # caller asks for more.
        requested = concurrency or s.wiki_max_concurrency
        self.concurrency = max(1, min(requested, s.wiki_max_concurrency))
        self.per_worker_delay = (
            per_worker_delay if per_worker_delay is not None else s.wiki_throttle_seconds
        )
        self.stats = RequestStats()
        self.logged_in_as: str | None = None
        self._semaphore = asyncio.Semaphore(self.concurrency)
        self._gate = _RateGate(min_gap=self.per_worker_delay / self.concurrency)
        self._client = httpx.AsyncClient(
            timeout=timeout_seconds,
            headers={"User-Agent": build_user_agent(), "Accept-Encoding": "gzip"},
            follow_redirects=True,
        )

    async def __aenter__(self) -> "WikipediaClient":
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self._client.aclose()

    # ---------------------------------------------------------------- requests

    async def _request(self, params: dict, *, method: str = "GET") -> dict:
        """One throttled API call with 429 backoff. Returns parsed JSON."""
        params = {**params, "format": "json", "formatversion": "2"}
        backoff = INITIAL_BACKOFF_SECONDS
        last_error: Exception | None = None

        for attempt in range(MAX_429_RETRIES + 1):
            async with self._semaphore:
                await self._gate.wait()
                self.stats.requests += 1
                try:
                    if method == "POST":
                        response = await self._client.post(self.api_url, data=params)
                    else:
                        response = await self._client.get(self.api_url, params=params)
                except (httpx.TimeoutException, httpx.TransportError) as exc:
                    last_error = exc
                    self.stats.errors += 1
                    response = None

            if response is not None and response.status_code != 429:
                response.raise_for_status()
                return response.json()

            if attempt == MAX_429_RETRIES:
                break

            if response is not None:  # 429
                self.stats.http_429 += 1
                retry_after = response.headers.get("Retry-After")
                try:
                    sleep_for = float(retry_after) if retry_after else backoff
                except ValueError:  # HTTP-date form; fall back to our own curve
                    sleep_for = backoff
                logger.warning("HTTP 429 from Wikipedia, backing off %.1fs", sleep_for)
            else:
                sleep_for = backoff

            self.stats.retries += 1
            await asyncio.sleep(sleep_for)
            backoff *= 2

        if last_error is not None:
            raise WikipediaAPIError(f"transport failure after retries: {last_error}") from last_error
        raise WikipediaAPIError("rate limited (HTTP 429) after all retries")

    # ------------------------------------------------------------------- login

    async def login(self) -> str:
        """Authenticate with the bot password. Returns a human-readable status
        line for the run log; never raises on failed auth — the crawl is still
        valid anonymously, just slower."""
        s = get_settings()
        if not (s.wiki_bot_username and s.wiki_bot_password):
            return "anonymous (WIKI_BOT_USERNAME/WIKI_BOT_PASSWORD not set)"

        attempts: list[str] = []
        for method_name in ("clientlogin", "login"):
            try:
                ok, detail = await self._try_login(method_name, s.wiki_bot_username, s.wiki_bot_password)
            except Exception as exc:  # network/API failure — report, don't abort
                attempts.append(f"{method_name}: {type(exc).__name__}: {exc}")
                continue
            if ok:
                name = await self._whoami()
                if name:
                    self.logged_in_as = name
                    return f"logged in as {name} via action={method_name}"
                attempts.append(f"{method_name}: reported success but userinfo says anonymous")
            else:
                attempts.append(f"{method_name}: {detail}")

        return "anonymous (login failed: " + "; ".join(attempts) + ")"

    async def _try_login(self, method_name: str, username: str, password: str) -> tuple[bool, str]:
        token_data = await self._request({"action": "query", "meta": "tokens", "type": "login"})
        token = token_data.get("query", {}).get("tokens", {}).get("logintoken")
        if not token:
            return False, f"no login token in response: {token_data}"

        if method_name == "clientlogin":
            payload = {
                "action": "clientlogin",
                "username": username,
                "password": password,
                "logintoken": token,
                "loginreturnurl": get_settings().wiki_site_url,
            }
        else:
            payload = {
                "action": "login",
                "lgname": username,
                "lgpassword": password,
                "lgtoken": token,
            }

        data = await self._request(payload, method="POST")
        if "error" in data:
            return False, str(data["error"].get("info", data["error"]))
        block = data.get(method_name, {})
        status = block.get("status") or block.get("result")
        if status in ("PASS", "Success"):
            return True, "ok"
        return False, str(block.get("message") or block.get("reason") or status or data)

    async def _whoami(self) -> str | None:
        data = await self._request({"action": "query", "meta": "userinfo"})
        info = data.get("query", {}).get("userinfo", {})
        if info.get("anon") or not info.get("name"):
            return None
        return str(info["name"])

    # -------------------------------------------------------------- title info

    async def resolve_titles(self, titles: list[str]) -> dict[str, TitleResolution]:
        """Batched existence/redirect lookup — up to 50 titles per request.

        This is the "does this title exist / where does it redirect" question,
        which batches; full wikitext does not (see fetch_wikitext).
        """
        unique = list(dict.fromkeys(t for t in titles if t.strip()))
        out: dict[str, TitleResolution] = {}
        batches = [unique[i : i + TITLES_PER_QUERY] for i in range(0, len(unique), TITLES_PER_QUERY)]
        results = await asyncio.gather(*(self._resolve_batch(b) for b in batches))
        for chunk in results:
            out.update(chunk)
        return out

    async def _resolve_batch(self, titles: list[str]) -> dict[str, TitleResolution]:
        data = await self._request(
            {
                "action": "query",
                "titles": "|".join(titles),
                "redirects": "1",
                "prop": "pageprops",
                "ppprop": "disambiguation",
            }
        )
        query = data.get("query", {})

        # The API reports normalization and redirects as separate hop lists;
        # chain them so a requested title maps to its final destination.
        norm = {n["from"]: n["to"] for n in query.get("normalized", [])}
        redirects = {r["from"]: r for r in query.get("redirects", [])}
        pages = {p.get("title"): p for p in query.get("pages", [])}

        out: dict[str, TitleResolution] = {}
        for requested in titles:
            current = norm.get(requested, requested)
            fragment = None
            seen = {current}
            while current in redirects:
                hop = redirects[current]
                fragment = hop.get("tofragment") or fragment
                current = hop["to"]
                if current in seen:  # redirect loop — stop where we are
                    break
                seen.add(current)
            page = pages.get(current, {})
            exists = not page.get("missing", False) and "invalid" not in page
            out[requested] = TitleResolution(
                requested=requested,
                resolved_title=current if exists else None,
                exists=exists,
                fragment=fragment,
                is_disambiguation="disambiguation" in (page.get("pageprops") or {}),
            )
        return out

    # ---------------------------------------------------------------- wikitext

    async def fetch_wikitext(self, title: str) -> WikitextResult:
        """Full wikitext of one page. One request per page — action=parse does
        not take a pipe-separated title list the way action=query does."""
        try:
            data = await self._request(
                {"action": "parse", "page": title, "prop": "wikitext", "redirects": "1"}
            )
        except httpx.HTTPStatusError as exc:
            self.stats.errors += 1
            return WikitextResult(title, "error", error=f"HTTP {exc.response.status_code}")
        except WikipediaAPIError as exc:
            self.stats.errors += 1
            return WikitextResult(title, "error", error=str(exc))

        if "error" in data:
            code = data["error"].get("code", "")
            info = str(data["error"].get("info", ""))
            if code in ("missingtitle", "nosuchpageid", "invalidtitle"):
                return WikitextResult(title, "not_found", error=info)
            self.stats.errors += 1
            return WikitextResult(title, "error", error=f"{code}: {info}")

        wikitext = data.get("parse", {}).get("wikitext")
        if isinstance(wikitext, dict):  # formatversion=1 shape, defensive
            wikitext = wikitext.get("*")
        if not wikitext:
            self.stats.errors += 1
            return WikitextResult(title, "error", error="empty wikitext in parse response")
        return WikitextResult(title, "ok", wikitext=wikitext)
