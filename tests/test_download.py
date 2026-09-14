"""Downloading. Network is mocked with respx — nothing leaves the machine."""

import httpx
import respx

from crawler.model import Reason
from crawler.service_download import download_page, is_valid_url


def test_rejects_bad_urls():
    for bad in ["", "notaurl", "ftp://x.com", "http://", "https://x.com/\x00"]:
        assert is_valid_url(bad) is False


def test_accepts_good_urls():
    assert is_valid_url("https://example.com/a?b=c")


@respx.mock
async def test_retries_server_errors():
    route = respx.get("https://x.test/").mock(return_value=httpx.Response(503))
    result = await download_page("https://x.test/")
    assert result.reason == Reason.server_error
    assert route.call_count == 3          # retried


@respx.mock
async def test_does_not_retry_404():
    route = respx.get("https://x.test/").mock(return_value=httpx.Response(404))
    await download_page("https://x.test/")
    assert route.call_count == 1          # pointless to retry


@respx.mock
async def test_403_is_forbidden():
    respx.get("https://x.test/").mock(return_value=httpx.Response(403))
    assert (await download_page("https://x.test/")).reason == Reason.forbidden


@respx.mock
async def test_429_is_rate_limited():
    respx.get("https://x.test/").mock(return_value=httpx.Response(429))
    assert (await download_page("https://x.test/")).reason == Reason.rate_limited


@respx.mock
async def test_missing_content_type_is_sniffed():
    """Amazon serves HTML with no Content-Type header."""
    respx.get("https://x.test/").mock(
        return_value=httpx.Response(200, html="<!doctype html><html><body>hi</body></html>")
    )
    result = await download_page("https://x.test/")
    assert result.ok is True


@respx.mock
async def test_non_html_is_rejected():
    respx.get("https://x.test/").mock(
        return_value=httpx.Response(200, json={"a": 1})
    )
    assert (await download_page("https://x.test/")).reason == Reason.not_html


@respx.mock
async def test_oversized_page_is_reported_as_too_large():
    big = "<html>" + "x" * 21_000_000 + "</html>"
    respx.get("https://x.test/").mock(return_value=httpx.Response(200, html=big))
    assert (await download_page("https://x.test/")).reason == Reason.too_large


@respx.mock
async def test_401_and_451_are_refusals_not_client_errors():
    """401 wants credentials we do not have; 451 is a legal block. Both are the
    site refusing us, so they belong with 403, not with a malformed request."""
    for code in (401, 451):
        respx.get("https://x.test/").mock(return_value=httpx.Response(code))
        assert (await download_page("https://x.test/")).reason == Reason.forbidden


@respx.mock
async def test_410_is_not_found_and_other_4xx_is_client_error():
    respx.get("https://x.test/").mock(return_value=httpx.Response(410))
    assert (await download_page("https://x.test/")).reason == Reason.not_found
    respx.get("https://x.test/").mock(return_value=httpx.Response(400))
    assert (await download_page("https://x.test/")).reason == Reason.client_error


@respx.mock
async def test_failure_keeps_what_the_server_said():
    """A 403 must be reported as a 403, not as http_status null."""
    respx.get("https://x.test/p").mock(
        return_value=httpx.Response(403, headers={"content-type": "text/html"})
    )
    result = await download_page("https://x.test/p")
    assert result.ok is False
    assert result.http_status == 403
    assert result.final_url == "https://x.test/p"
    assert result.content_type == "text/html"


@respx.mock
async def test_unknown_charset_falls_back_to_utf8():
    """A bogus charset must not escape as LookupError; download_page never raises."""
    respx.get("https://x.test/").mock(return_value=httpx.Response(
        200, content=b"<!doctype html><html><title>ok</title></html>",
        headers={"content-type": "text/html; charset=bogus"}))
    result = await download_page("https://x.test/")
    assert result.ok is True
    assert "ok" in (result.html or "")


@respx.mock
async def test_content_type_match_is_case_insensitive():
    respx.get("https://x.test/").mock(return_value=httpx.Response(
        200, content=b"<!doctype html><html>x</html>", headers={"content-type": "Text/HTML"}))
    assert (await download_page("https://x.test/")).ok is True


@respx.mock
async def test_server_error_keeps_its_status_after_retries():
    respx.get("https://x.test/").mock(return_value=httpx.Response(503))
    result = await download_page("https://x.test/")
    assert result.reason == Reason.server_error
    assert result.http_status == 503


@respx.mock
async def test_unfollowed_redirect_is_not_a_page(monkeypatch):
    from crawler.service_download import settings

    monkeypatch.setattr(settings, "follow_redirects", False)
    respx.get("https://x.test/old").mock(return_value=httpx.Response(
        301, headers={"location": "/new", "content-type": "text/html"},
        content=b"<html><body>Moved</body></html>"))
    result = await download_page("https://x.test/old")
    assert result.ok is False
    assert result.reason == Reason.redirect_not_followed
    assert result.http_status == 301


async def test_dns_failure_is_recognised_from_the_exception_chain():
    """httpx chains the resolver's socket.gaierror under ConnectError; the message
    text differs per OS, so the chain is what identifies a DNS failure."""
    import socket

    def handler(request: httpx.Request) -> httpx.Response:
        try:
            raise socket.gaierror(8, "nodename nor servname provided, or not known")
        except socket.gaierror as inner:
            raise httpx.ConnectError("[Errno 8] nodename nor servname", request=request) from inner

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        assert (await download_page("https://nx.test/", client)).reason == Reason.dns_error


async def test_private_and_local_targets_are_refused_without_a_fetch():
    from crawler.service_download import is_private_target

    for url in ("http://127.0.0.1:8000/", "http://localhost/x", "http://192.168.1.1/",
                "http://10.0.0.5/", "http://169.254.169.254/computeMetadata/v1/",
                "http://[::1]/", "http://0.0.0.0/"):
        assert is_private_target(url), url
        assert (await download_page(url)).reason == Reason.private_address
    for url in ("https://example.com/", "http://8.8.8.8/", "https://[2606:4700::1111]/"):
        assert not is_private_target(url), url
