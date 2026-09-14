"""Run the whole job: URL in, finished JSON out.

Order: robots -> download -> captcha check -> parse -> content check -> topics.
Every path returns a CrawlResult and logs one terminal event. Nothing raises.

Both doors call this, so the CLI and the API cannot drift apart.
"""

import asyncio
from datetime import UTC, datetime

import httpx

from crawler.config import settings
from crawler.logging import log
from crawler.model import CrawlResult, DownloadResult, Reason, RobotsState, Status
from crawler.service_detect import detect_captcha, detect_denial
from crawler.service_download import download_page, is_private_target, is_valid_url, make_client
from crawler.service_parse import parse_html
from crawler.service_robots import check_robots
from crawler.service_topics import extract_topics

# Reasons that mean "the site refused us", as opposed to "something broke".
BLOCKED_REASONS = {
    Reason.robots_disallowed,
    Reason.captcha,
    Reason.forbidden,
    Reason.rate_limited,
}

_EVENT = {Status.success: "crawl.ok", Status.blocked: "crawl.blocked", Status.error: "crawl.failed"}


def _finish(url: str, status: Status, reason: Reason, **fields: object) -> CrawlResult:
    """Build the result and log the one terminal event every outcome shares."""
    result = CrawlResult(
        url=url,
        status=status,
        reason=reason,
        fetched_at=datetime.now(UTC),
        **fields,  # type: ignore[arg-type]
    )
    log.info(
        _EVENT[status],
        url=url,
        reason=reason,
        robots_state=result.robots_state,
        http_status=result.http_status,
    )
    return result


def _from_download(downloaded: DownloadResult) -> dict[str, object]:
    """The response facts every post-download result carries."""
    return {
        "final_url": downloaded.final_url,
        "http_status": downloaded.http_status,
        "content_type": downloaded.content_type,
    }


async def crawl_url(url: str, client: httpx.AsyncClient | None = None) -> CrawlResult:
    """Fetch and understand one page. Never raises.

    One HTTP client serves the robots and page fetches; a caller may supply it
    (the API shares one for the process), otherwise one is made for this crawl.
    """
    log.info("crawl.start", url=url)

    # Check before the robots fetch, or a malformed URL comes back as 'blocked'
    # when it is really our caller's error.
    if not is_valid_url(url):
        return _finish(url, Status.error, Reason.bad_url)
    if is_private_target(url):
        return _finish(url, Status.error, Reason.private_address)

    owned = client is None
    if client is None:
        client = make_client()
    try:
        return await asyncio.wait_for(_crawl(url, client), timeout=settings.total_timeout_seconds)
    except TimeoutError:
        return _finish(url, Status.error, Reason.timeout)
    except Exception:
        # Every stage is written not to raise; this is the guarantee if one does.
        log.exception("crawl.internal_error", url=url)
        return _finish(url, Status.error, Reason.internal_error)
    finally:
        if owned:
            await client.aclose()


async def _crawl(url: str, client: httpx.AsyncClient) -> CrawlResult:
    # 1. May we? check_robots reports 'skipped' when robots checking is off.
    robots = await check_robots(url, client)
    state = robots.state
    if not robots.allowed:
        # 'unavailable' means robots.txt returned 5xx — the site is unwell, not
        # refusing us. It is an error, not a policy refusal.
        if state == RobotsState.unavailable:
            return _finish(url, Status.error, Reason.robots_unavailable, robots_state=state)
        return _finish(url, Status.blocked, Reason.robots_disallowed, robots_state=state)

    # 2. Download it.
    downloaded = await download_page(url, client)
    facts: dict[str, object] = {"robots_state": state, **_from_download(downloaded)}
    if not downloaded.ok or downloaded.html is None:
        status = Status.blocked if downloaded.reason in BLOCKED_REASONS else Status.error
        return _finish(url, status, downloaded.reason, **facts)

    # 3. A CAPTCHA wearing a 200? Cheap check on the raw HTML, before parsing.
    captcha = detect_captcha(downloaded.html)
    if captcha is not None:
        return _finish(url, Status.blocked, captcha, **facts)

    # 4. Read it. The parse is CPU-bound and holds the interpreter lock; running
    #    it in a worker thread keeps this event loop serving other requests.
    try:
        page = await asyncio.to_thread(parse_html, downloaded.html, downloaded.final_url)
    except Exception as exc:
        log.warning("crawl.parse_error", url=url, error=str(exc))
        return _finish(url, Status.error, Reason.parse_failed, **facts)

    # 5. Is this the content, or an error/block page wearing a 200? Decided on the parsed page.
    not_content = detect_denial(page)
    if not_content is not None:
        status = Status.blocked if not_content in BLOCKED_REASONS else Status.error
        return _finish(url, status, not_content, **facts)

    # 6. What is it about?
    topics = await asyncio.to_thread(extract_topics, page.body, page.title, page.h1_headings)
    return _finish(url, Status.success, Reason.ok, topics=topics, **facts, **page.model_dump())
