"""robots.txt. An unreachable robots.txt is not a refusal."""

import httpx
import respx

import crawler.service_robots as mod
from crawler.service_robots import check_robots


def setup_function():
    mod._cache.clear()


@respx.mock
async def test_disallow_rule_is_respected():
    respx.get("https://x.test/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\nDisallow: /private")
    )
    assert (await check_robots("https://x.test/private/p")).allowed is False
    mod._cache.clear()
    respx.get("https://x.test/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\nDisallow: /private")
    )
    assert (await check_robots("https://x.test/public/p")).allowed is True


@respx.mock
async def test_missing_robots_means_allowed():
    """RFC 9309: 4xx means unrestricted, not forbidden."""
    respx.get("https://x.test/robots.txt").mock(return_value=httpx.Response(404))
    result = await check_robots("https://x.test/p")
    assert result.allowed is True
    assert result.state == "missing"


@respx.mock
async def test_unreachable_robots_is_not_a_refusal():
    """A dead host is a connection error, not a refusal: reporting it as
    robots_disallowed would inflate the block rate."""
    respx.get("https://x.test/robots.txt").mock(side_effect=httpx.ConnectError("down"))
    result = await check_robots("https://x.test/p")
    assert result.allowed is True
    assert result.state == "unreachable"


@respx.mock
async def test_server_error_holds_off():
    respx.get("https://x.test/robots.txt").mock(return_value=httpx.Response(503))
    result = await check_robots("https://x.test/p")
    assert result.allowed is False
    assert result.state == "unavailable"


@respx.mock
async def test_cached_state_survives_repeat_calls():
    """Regression: the cache stored only the parsed rules, so a 4xx robots.txt
    (allowed) and a 5xx one (hold off) both became None and were indistinguishable
    on the second call. The same URL returned different answers on request 1 and
    request 2."""
    respx.get("https://x.test/robots.txt").mock(return_value=httpx.Response(404))
    first = await check_robots("https://x.test/p")
    second = await check_robots("https://x.test/p")
    third = await check_robots("https://x.test/other")
    assert (first.allowed, first.state) == (True, "missing")
    assert (second.allowed, second.state) == (True, "missing")
    assert (third.allowed, third.state) == (True, "missing")


@respx.mock
async def test_cached_server_error_stays_unavailable():
    respx.get("https://y.test/robots.txt").mock(return_value=httpx.Response(503))
    first = await check_robots("https://y.test/p")
    second = await check_robots("https://y.test/p")
    assert (first.allowed, first.state) == (False, "unavailable")
    assert (second.allowed, second.state) == (False, "unavailable")


@respx.mock
async def test_cache_is_bounded(monkeypatch):
    monkeypatch.setattr(mod.settings, "robots_cache_size", 2)
    for host in ("a.test", "b.test", "c.test"):
        respx.get(f"https://{host}/robots.txt").mock(return_value=httpx.Response(404))
        await check_robots(f"https://{host}/p")
    assert list(mod._cache) == ["https://b.test", "https://c.test"]  # oldest evicted


@respx.mock
async def test_cache_entries_expire(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(mod, "monotonic", lambda: now[0])
    route = respx.get("https://x.test/robots.txt").mock(return_value=httpx.Response(404))
    await check_robots("https://x.test/p")
    now[0] += mod.settings.robots_cache_ttl_seconds - 1
    await check_robots("https://x.test/p")
    assert route.call_count == 1                 # still cached
    now[0] += 2
    await check_robots("https://x.test/p")
    assert route.call_count == 2                 # expired, re-fetched


@respx.mock
async def test_unavailable_is_cached_briefly(monkeypatch):
    """A 5xx is a passing state; re-check it soon rather than holding off all day."""
    now = [0.0]
    monkeypatch.setattr(mod, "monotonic", lambda: now[0])
    route = respx.get("https://x.test/robots.txt").mock(return_value=httpx.Response(503))
    await check_robots("https://x.test/p")
    now[0] += mod.settings.robots_unavailable_ttl_seconds + 1
    route.mock(return_value=httpx.Response(404))
    result = await check_robots("https://x.test/p")
    assert route.call_count == 2
    assert result.state == "missing"


@respx.mock
async def test_robots_redirect_is_followed_even_when_page_redirects_are_off(monkeypatch):
    """http://host/robots.txt commonly 301s to https; a Disallow behind it must be seen."""
    monkeypatch.setattr(mod.settings, "follow_redirects", False)
    respx.get("http://r.test/robots.txt").mock(return_value=httpx.Response(
        301, headers={"location": "https://r.test/robots.txt"}, content=b"Moved"))
    respx.get("https://r.test/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\nDisallow: /"))
    result = await check_robots("http://r.test/p")
    assert result.allowed is False
    assert result.state == "disallowed"


@respx.mock
async def test_oversized_robots_is_truncated_not_buffered():
    big = "User-agent: *\nDisallow: /private\n" + ("# filler\n" * 200_000)   # ~1.8 MB
    respx.get("https://big.test/robots.txt").mock(return_value=httpx.Response(200, text=big))
    result = await check_robots("https://big.test/private/p")
    assert result.allowed is False   # the rule in the first 512 KiB still applies


@respx.mock
async def test_unparseable_robots_is_treated_as_missing(monkeypatch):
    monkeypatch.setattr(mod.Protego, "parse", lambda text: (_ for _ in ()).throw(ValueError("bad")))
    respx.get("https://z.test/robots.txt").mock(return_value=httpx.Response(200, text="garbage"))
    result = await check_robots("https://z.test/p")
    assert result.allowed is True
    assert result.state == "missing"
