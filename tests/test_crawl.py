"""The whole job, end to end. Network mocked."""

import httpx
import respx

import crawler.service_robots as robots_mod
from crawler.model import Reason, Status
from crawler.service_crawl import crawl_url

PAGE = """<!doctype html><html lang="en"><head><title>Solar Power Basics</title>
<meta name="description" content="How solar panels work"/>
<meta property="og:type" content="article"/></head><body><h1>Solar Power Basics</h1>
<p>Solar panels convert sunlight into electricity using photovoltaic cells.
Photovoltaic cells are made of silicon. Solar power is renewable energy that
reduces carbon emissions. Installing solar panels on a roof lowers electricity
bills over time. Solar energy adoption has grown worldwide as panel costs fall.
</p></body></html>"""


def setup_function():
    robots_mod._cache.clear()


@respx.mock
async def test_happy_path_fills_the_schema():
    respx.get("https://x.test/robots.txt").mock(return_value=httpx.Response(404))
    respx.get("https://x.test/solar").mock(return_value=httpx.Response(200, html=PAGE))

    result = await crawl_url("https://x.test/solar")
    assert result.status == Status.success
    assert result.title == "Solar Power Basics"
    assert result.language == "en"
    assert result.h1_headings == ["Solar Power Basics"]
    assert result.og_tags["og:type"] == "article"
    assert result.word_count > 20
    assert result.topics


@respx.mock
async def test_robots_disallow_blocks_before_fetching():
    respx.get("https://x.test/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\nDisallow: /")
    )
    page = respx.get("https://x.test/solar")
    result = await crawl_url("https://x.test/solar")
    assert result.status == Status.blocked
    assert result.reason == Reason.robots_disallowed
    assert page.call_count == 0        # never fetched — polite


@respx.mock
async def test_captcha_page_is_blocked_not_parsed():
    respx.get("https://x.test/robots.txt").mock(return_value=httpx.Response(404))
    respx.get("https://x.test/p").mock(
        return_value=httpx.Response(200, html="<html><body>Robot Check</body></html>")
    )
    result = await crawl_url("https://x.test/p")
    assert result.status == Status.blocked
    assert result.reason == Reason.captcha


async def test_bad_url_is_error_not_blocked():
    result = await crawl_url("notaurl")
    assert result.status == Status.error
    assert result.reason == Reason.bad_url


async def test_never_raises_on_hostile_input():
    for bad in ["", "ftp://x.com", "javascript:alert(1)", "https://x.com/\x00"]:
        assert (await crawl_url(bad)).status == Status.error


@respx.mock
async def test_robots_server_error_is_an_error_not_a_refusal():
    """A robots.txt 5xx says nothing about policy. Counting it as a block would
    inflate block rate with what is really a sick server."""
    respx.get("https://x.test/robots.txt").mock(return_value=httpx.Response(503))
    result = await crawl_url("https://x.test/solar")
    assert result.status == Status.error
    assert result.reason == Reason.robots_unavailable
    assert result.robots_state == "unavailable"


@respx.mock
async def test_robots_state_is_reported_on_every_path():
    respx.get("https://x.test/robots.txt").mock(return_value=httpx.Response(404))
    respx.get("https://x.test/solar").mock(return_value=httpx.Response(200, html=PAGE))
    assert (await crawl_url("https://x.test/solar")).robots_state == "missing"

    robots_mod._cache.clear()
    respx.get("https://x.test/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\nAllow: /")
    )
    respx.get("https://x.test/solar").mock(return_value=httpx.Response(403))
    result = await crawl_url("https://x.test/solar")
    assert result.status == Status.blocked
    assert result.robots_state == "allowed"
    assert result.http_status == 403  # the 403 survives into the final JSON

    assert (await crawl_url("notaurl")).robots_state is None  # rejected before the check


async def test_robots_and_page_go_through_the_same_client():
    """A caller-supplied client is used for both fetches — no hidden second client."""
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, html=PAGE)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await crawl_url("https://shared.test/solar", client)
    assert result.status == Status.success
    assert seen == ["/robots.txt", "/solar"]


@respx.mock
async def test_denial_page_with_200_is_blocked_not_parsed():
    respx.get("https://x.test/robots.txt").mock(return_value=httpx.Response(404))
    respx.get("https://x.test/p").mock(return_value=httpx.Response(
        200, html="<html><head><title>Access Denied</title></head>"
                  "<body><h1>Access Denied</h1>You don't have permission.</body></html>"))
    result = await crawl_url("https://x.test/p")
    assert result.status == Status.blocked
    assert result.reason == Reason.forbidden
    assert result.title is None          # a blocked page carries no metadata


@respx.mock
async def test_cli_path_builds_exactly_one_client(monkeypatch):
    import crawler.service_crawl as crawl_mod
    import crawler.service_download as dl

    calls = [0]
    real = dl.make_client

    def counting():
        calls[0] += 1
        return real()

    monkeypatch.setattr(crawl_mod, "make_client", counting)
    monkeypatch.setattr(dl, "make_client", counting)
    respx.get("https://x.test/robots.txt").mock(return_value=httpx.Response(404))
    respx.get("https://x.test/solar").mock(return_value=httpx.Response(200, html=PAGE))
    assert (await crawl_url("https://x.test/solar")).status == Status.success
    assert calls[0] == 1


@respx.mock
async def test_parse_failure_keeps_response_facts(monkeypatch):
    import crawler.service_crawl as crawl_mod

    def boom(html, url=None):
        raise RuntimeError("parser exploded")

    monkeypatch.setattr(crawl_mod, "parse_html", boom)
    respx.get("https://x.test/robots.txt").mock(return_value=httpx.Response(404))
    respx.get("https://x.test/solar").mock(return_value=httpx.Response(
        200, html=PAGE, headers={"content-type": "text/html"}))
    result = await crawl_url("https://x.test/solar")
    assert result.reason == Reason.parse_failed
    assert result.http_status == 200
    assert result.content_type == "text/html"
    assert result.robots_state == "missing"


@respx.mock
async def test_no_content_page_is_an_error_not_a_success():
    respx.get("https://x.test/robots.txt").mock(return_value=httpx.Response(404))
    respx.get("https://x.test/p").mock(return_value=httpx.Response(
        200, html="<html><head><title>Site Maintenance</title></head>"
                  "<body><h1>Oops! Something went wrong</h1></body></html>"))
    result = await crawl_url("https://x.test/p")
    assert result.status == Status.error
    assert result.reason == Reason.no_content
    assert result.http_status == 200
    assert result.title is None
