"""Download one page. Returns the HTML and what the server did.

Never reads meaning from the HTML — that is service_parse.
Never decides if a 200 page is really a block page — that is service_detect.
"""

import ipaddress
import socket
from urllib.parse import urlsplit

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from crawler.config import settings
from crawler.model import DownloadResult, Reason

HTML_TYPES = ("text/html", "application/xhtml+xml")

# Some servers send no Content-Type at all. Sniff the body rather than assume.
HTML_SNIFF = ("<!doctype html", "<html")


class ServerError(Exception):
    """A 5xx. Worth retrying. Carries the response so the final result keeps its status."""

    def __init__(self, response: httpx.Response) -> None:
        super().__init__(str(response.status_code))
        self.response = response


class TooLargeError(Exception):
    """Body exceeded max_bytes while streaming. Not retried."""

    def __init__(self, response: httpx.Response) -> None:
        super().__init__("too large")
        self.response = response


def make_client() -> httpx.AsyncClient:
    """The one way to build a client, so every stage shares the same settings."""
    return httpx.AsyncClient(
        headers={"User-Agent": settings.user_agent},
        follow_redirects=settings.follow_redirects,
        max_redirects=settings.max_redirects,
        timeout=settings.timeout_seconds,
        http2=True,
    )


def is_valid_url(url: str) -> bool:
    # Control characters reach httpx as InvalidURL, which is not an HTTPError
    # and would escape our handlers. Reject them here.
    if not url or any(ord(c) < 0x20 or ord(c) == 0x7F for c in url):
        return False
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    return parts.scheme in ("http", "https") and bool(parts.netloc)


def is_private_target(url: str) -> bool:
    """Loopback, private, link-local, reserved or unspecified literal address, or localhost.

    A crawler has no business on those, and on a cloud host they reach the
    metadata service. Hostnames that *resolve* to such addresses are not caught
    here; that needs a resolver hook and is listed as a limitation.
    """
    try:
        host = urlsplit(url).hostname or ""
    except ValueError:
        return False
    if host == "localhost" or host.endswith(".localhost"):
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return (
        address.is_private or address.is_loopback or address.is_link_local
        or address.is_reserved or address.is_multicast or address.is_unspecified
    )


async def read_capped(response: httpx.Response, limit: int) -> tuple[bytes, bool]:
    """Read a streamed body up to `limit` bytes.

    Returns (bytes read, truncated). Reading — rather than abandoning — a body
    we do not want keeps the pooled connection reusable.
    """
    buf = bytearray()
    async for chunk in response.aiter_bytes():
        buf.extend(chunk)
        if len(buf) > limit:
            return bytes(buf[:limit]), True
    return bytes(buf), False


def decode(response: httpx.Response, body: bytes) -> str:
    """Decode with the declared charset when Python knows it, else UTF-8."""
    try:
        return body.decode(response.charset_encoding or "utf-8", errors="replace")
    except LookupError:
        return body.decode("utf-8", errors="replace")


def _is_dns_failure(exc: BaseException) -> bool:
    """Walk the exception chain for a resolver error; the message text varies by OS."""
    visited: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in visited:
        if isinstance(current, socket.gaierror):
            return True
        visited.add(id(current))  # exception chains can be cyclic after a retry
        current = current.__cause__ or current.__context__
    return False


@retry(
    stop=stop_after_attempt(settings.max_retries),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    retry=retry_if_exception_type((httpx.TimeoutException, httpx.TransportError, ServerError)),
    reraise=True,
)
async def _get(client: httpx.AsyncClient, url: str) -> tuple[httpx.Response, bytes]:
    """One attempt. Retried on timeouts, transport errors and 5xx.

    Streams the body and stops the moment it passes max_bytes, so the cap
    bounds memory, not just parse cost.
    """
    async with client.stream("GET", url) as response:
        if response.status_code >= 500:
            raise ServerError(response)
        body, truncated = await read_capped(response, settings.max_bytes)
        if truncated and response.status_code < 400:
            raise TooLargeError(response)
        return response, body


def _fail(reason: Reason, response: httpx.Response | None = None) -> DownloadResult:
    """A failure keeps what the server said, so a 403 is reported as a 403."""
    if response is None:
        return DownloadResult(ok=False, reason=reason)
    return DownloadResult(
        ok=False,
        reason=reason,
        final_url=str(response.url),
        http_status=response.status_code,
        content_type=response.headers.get("content-type", ""),
    )


def _looks_like_html(content_type: str, body: str) -> bool:
    if content_type:
        return any(t in content_type.lower() for t in HTML_TYPES)
    return any(marker in body[:2000].lower() for marker in HTML_SNIFF)


async def download_page(url: str, client: httpx.AsyncClient | None = None) -> DownloadResult:
    """Fetch one URL. Returns a result whatever happens — never raises."""
    if not is_valid_url(url):
        return _fail(Reason.bad_url)
    if is_private_target(url):
        return _fail(Reason.private_address)

    owned = client is None
    if client is None:
        client = make_client()

    try:
        response, body = await _get(client, url)
    except TooLargeError as exc:
        return _fail(Reason.too_large, exc.response)
    except ServerError as exc:
        return _fail(Reason.server_error, exc.response)
    except httpx.TimeoutException:
        return _fail(Reason.timeout)
    except httpx.TooManyRedirects:
        return _fail(Reason.connect_error)
    except httpx.ConnectError as exc:
        return _fail(Reason.dns_error if _is_dns_failure(exc) else Reason.connect_error)
    except (httpx.HTTPError, httpx.InvalidURL, ValueError):
        return _fail(Reason.connect_error)
    finally:
        if owned:
            await client.aclose()

    return _inspect(response, body)


def _inspect(response: httpx.Response, body: bytes) -> DownloadResult:
    """Turn a response into a result. Status codes and content type only."""
    status = response.status_code
    content_type = response.headers.get("content-type", "")

    # The site refused us: 401 wants credentials we do not have, 403 and 451
    # (legal) are explicit refusals, 429 is a rate limit. All are 'blocked'.
    if status in (401, 403, 451):
        return _fail(Reason.forbidden, response)
    if status == 429:
        return _fail(Reason.rate_limited, response)
    if status in (404, 410):
        return _fail(Reason.not_found, response)
    if status >= 400:
        return _fail(Reason.client_error, response)
    if 300 <= status < 400:
        # Only reachable with redirects disabled; the stub body is not the page.
        return _fail(Reason.redirect_not_followed, response)

    html = decode(response, body)
    if not _looks_like_html(content_type, html):
        return _fail(Reason.not_html, response)

    return DownloadResult(
        ok=True,
        reason=Reason.ok,
        html=html,
        final_url=str(response.url),
        http_status=status,
        content_type=content_type,
    )
