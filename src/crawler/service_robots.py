"""Check robots.txt before fetching.

Follows RFC 9309: a robots.txt we cannot reach (4xx) means crawling is
unrestricted; a 5xx means the site is unwell, so we hold off; redirects are
followed; only the first 512 KiB is parsed. Each outcome is reported by state
rather than collapsed into "not allowed".

The cache is per process, bounded (LRU) and time-limited: a worker that sees
millions of hosts must neither grow without limit nor trust a robots file
forever. A 5xx or unreachable result is cached briefly so a recovered host is
re-checked soon.
"""

from collections import OrderedDict
from time import monotonic
from urllib.parse import urlsplit

import httpx
from protego import Protego

from crawler.config import settings
from crawler.model import RobotsResult, RobotsState
from crawler.service_download import make_client, read_capped

MAX_ROBOTS_BYTES = 512 * 1024  # RFC 9309 §2.5: crawlers may stop at 500 KiB

# origin -> (state when there are no rules, parsed rules, expires_at). LRU order.
_cache: OrderedDict[str, tuple[RobotsState | None, Protego | None, float]] = OrderedDict()

_SHORT_LIVED = (RobotsState.unavailable, RobotsState.unreachable)


def _robots_url(url: str) -> tuple[str, str]:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}", f"{parts.scheme}://{parts.netloc}/robots.txt"


def _cached(origin: str) -> tuple[RobotsState | None, Protego | None] | None:
    entry = _cache.get(origin)
    if entry is None:
        return None
    state, rules, expires_at = entry
    if monotonic() >= expires_at:
        del _cache[origin]
        return None
    _cache.move_to_end(origin)
    return state, rules


def _store(origin: str, state: RobotsState | None, rules: Protego | None) -> None:
    ttl = (
        settings.robots_unavailable_ttl_seconds
        if state in _SHORT_LIVED
        else settings.robots_cache_ttl_seconds
    )
    _cache[origin] = (state, rules, monotonic() + ttl)
    _cache.move_to_end(origin)
    while len(_cache) > settings.robots_cache_size:
        _cache.popitem(last=False)


async def _load(
    robots_url: str, client: httpx.AsyncClient
) -> tuple[RobotsState | None, Protego | None]:
    """Fetch one robots.txt. Returns (state, rules); rules is set only when found."""
    try:
        # Redirects are always followed here, whatever the page-fetch setting:
        # robots.txt on http:// commonly redirects to https://.
        async with client.stream("GET", robots_url, follow_redirects=True) as response:
            if response.status_code >= 500:
                return RobotsState.unavailable, None
            if response.status_code >= 400:
                return RobotsState.missing, None
            body, _truncated = await read_capped(response, MAX_ROBOTS_BYTES)
    except (httpx.HTTPError, httpx.InvalidURL, ValueError):
        # Could not reach it at all — usually the host itself is down. Let the
        # page fetch report the real error instead of guessing.
        return RobotsState.unreachable, None
    return None, Protego.parse(body.decode("utf-8", errors="replace"))


def _decide(url: str, state: RobotsState | None, rules: Protego | None) -> RobotsResult:
    if rules is None or state is not None:
        # No rules to apply; the state says whether we may proceed.
        assert state is not None
        permissive = (RobotsState.missing, RobotsState.unreachable)
        return RobotsResult(allowed=state in permissive, state=state)
    allowed = bool(rules.can_fetch(url, settings.user_agent))
    return RobotsResult(
        allowed=allowed, state=RobotsState.allowed if allowed else RobotsState.disallowed
    )


async def check_robots(url: str, client: httpx.AsyncClient | None = None) -> RobotsResult:
    """May we fetch this URL? Never raises."""
    if not settings.respect_robots:
        return RobotsResult(allowed=True, state=RobotsState.skipped)

    origin, robots_url = _robots_url(url)
    hit = _cached(origin)
    if hit is None:
        owned = client is None
        if client is None:
            client = make_client()
        try:
            state, rules = await _load(robots_url, client)
        finally:
            if owned:
                await client.aclose()
        _store(origin, state, rules)
        hit = (state, rules)

    return _decide(url, *hit)
