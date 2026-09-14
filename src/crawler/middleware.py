"""One log line per HTTP request: method, path, query, client, headers, body,
response status and duration. Credential headers are logged as [redacted]."""

import time
from collections.abc import Awaitable, Callable

from starlette.requests import Request
from starlette.responses import Response

from crawler.logging import log

REDACTED_HEADERS = {"authorization", "cookie", "proxy-authorization", "x-api-key", "set-cookie"}
MAX_BODY_BYTES = 4_096


def _headers(request: Request) -> dict[str, str]:
    return {
        k: ("[redacted]" if k.lower() in REDACTED_HEADERS else v)
        for k, v in request.headers.items()
    }


async def log_requests(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    started = time.perf_counter()
    body = await request.body()
    response = await call_next(request)
    duration_ms = round((time.perf_counter() - started) * 1000)
    entry = dict(
        method=request.method,
        path=request.url.path,
        query=dict(request.query_params),
        client=request.client.host if request.client else None,
        headers=_headers(request),
        body=body[:MAX_BODY_BYTES].decode("utf-8", errors="replace"),
        body_bytes=len(body),
        status=response.status_code,
        duration_ms=duration_ms,
    )
    if response.status_code >= 500:
        log.error("http.request", **entry)
    else:
        log.info("http.request", **entry)
    return response
