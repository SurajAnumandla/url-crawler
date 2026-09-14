"""HTTP door onto service_crawl. One shared HTTP client for the process lifetime."""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import httpx
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from crawler import __version__
from crawler.home import render_home
from crawler.logging import setup_logging
from crawler.model import CrawlResult
from crawler.service_crawl import crawl_url
from crawler.service_download import make_client

setup_logging()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # One client, one connection pool, reused by robots and page fetches alike.
    app.state.client = make_client()
    try:
        yield
    finally:
        await app.state.client.aclose()


app = FastAPI(
    title="Crawler",
    description="Extract metadata, page type and topics from any URL",
    lifespan=lifespan,
)


_HOME = render_home()


@app.get("/home", include_in_schema=False)
async def home() -> HTMLResponse:
    return HTMLResponse(_HOME)


@app.get("/", include_in_schema=False)
async def root() -> RedirectResponse:
    return RedirectResponse(url="/home", status_code=307)


@app.exception_handler(404)
async def not_found(request: Request, exc: HTTPException) -> Response:
    """A path that is not an endpoint sends the visitor to the landing page."""
    return RedirectResponse(url="/home", status_code=307)


@app.get("/favicon.ico", include_in_schema=False)
async def favicon() -> Response:
    return Response(status_code=204)


_STARTED_AT = datetime.now(UTC)


@app.get("/health")
async def health() -> dict[str, str | int]:
    """Liveness plus enough context to tell which build answered and since when.

    `revision` is the Cloud Run revision name (K_REVISION), which identifies the
    deployment; `instance_started_at` is when this instance booted, which resets
    every time the service wakes from zero — it is not the deploy time.
    """
    now = datetime.now(UTC)
    return {
        "status": "ok",
        "time": now.isoformat(timespec="seconds"),
        "instance_started_at": _STARTED_AT.isoformat(timespec="seconds"),
        "uptime_seconds": int((now - _STARTED_AT).total_seconds()),
        "revision": os.environ.get("K_REVISION", "local"),
        "version": __version__,
    }


def _client(request: Request) -> httpx.AsyncClient:
    """The lifespan's client; created on first use if the server skipped lifespan events."""
    client: httpx.AsyncClient | None = getattr(request.app.state, "client", None)
    if client is None:
        client = request.app.state.client = make_client()
    return client


@app.get("/extract", response_model=CrawlResult)
async def extract(
    request: Request, url: str = Query(..., description="URL to crawl")
) -> CrawlResult:
    """Same JSON as `python -m crawler <url>`."""
    return await crawl_url(url, _client(request))
