"""The HTTP API. Must return exactly what the CLI returns."""

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

import crawler.service_robots as robots_mod
from crawler.app import app

PAGE = (
    '<!doctype html><html lang="en"><head><title>Hello</title>'
    '<meta name="description" content="A page that declares itself"></head>'
    '<body><h1>Hello</h1></body></html>'
)


def setup_function():
    robots_mod._cache.clear()


@pytest.fixture
def client():
    # The context manager runs the lifespan, which creates the shared client.
    with TestClient(app) as c:
        yield c


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["revision"] == "local"            # K_REVISION is set only on Cloud Run
    assert body["uptime_seconds"] >= 0
    assert body["time"] >= body["instance_started_at"]


def test_extract_requires_a_url(client):
    assert client.get("/extract").status_code == 422


@respx.mock
def test_extract_returns_the_schema(client):
    respx.get("https://x.test/robots.txt").mock(return_value=httpx.Response(404))
    respx.get("https://x.test/p").mock(return_value=httpx.Response(200, html=PAGE))

    body = client.get("/extract", params={"url": "https://x.test/p"}).json()
    assert body["status"] == "success"
    assert body["title"] == "Hello"


def test_bad_url_returns_json_not_500(client):
    response = client.get("/extract", params={"url": "notaurl"})
    assert response.status_code == 200
    assert response.json()["reason"] == "bad_url"


@respx.mock
def test_api_matches_cli_exactly(client):
    """Both doors call service_crawl, so their JSON cannot drift."""
    import asyncio

    from crawler.service_crawl import crawl_url

    respx.get("https://x.test/robots.txt").mock(return_value=httpx.Response(404))
    respx.get("https://x.test/p").mock(return_value=httpx.Response(200, html=PAGE))
    api = client.get("/extract", params={"url": "https://x.test/p"}).json()

    respx.get("https://x.test/robots.txt").mock(return_value=httpx.Response(404))
    respx.get("https://x.test/p").mock(return_value=httpx.Response(200, html=PAGE))
    robots_mod._cache.clear()
    cli = asyncio.run(crawl_url("https://x.test/p")).model_dump(mode="json")

    api.pop("fetched_at"), cli.pop("fetched_at")
    assert api == cli


def test_one_client_shared_for_the_process(client):
    """The lifespan creates one httpx client; requests must not open new ones."""
    shared = app.state.client
    assert isinstance(shared, httpx.AsyncClient)
    client.get("/extract", params={"url": "notaurl"})
    assert app.state.client is shared
    assert shared.is_closed is False


def test_extract_answers_even_without_the_lifespan():
    """A server that skips lifespan events (or a bare TestClient) must still get JSON."""
    bare = TestClient(app)
    app.state._state.pop("client", None)
    response = bare.get("/extract", params={"url": "notaurl"})
    assert response.status_code == 200
    assert response.json()["reason"] == "bad_url"


def test_root_and_unknown_paths_land_on_home(client):
    for path in ("/", "/anything/else", "/extract-typo"):
        response = client.get(path, follow_redirects=False)
        assert response.status_code == 307
        assert response.headers["location"] == "/home"
    home = client.get("/home")
    assert home.status_code == 200
    assert "URL Crawler" in home.text
    assert home.text.count('class="btn"') == 4            # the three assignment URLs + Wikipedia
    assert "/extract?url=http%3A%2F%2Fwww.amazon.com" in home.text   # plain link, no JS needed
    assert "blocked · 403" in home.text                   # each example says what to expect
    assert "BrightEdge Engineering Assignment" in home.text   # byline
    assert "no_content" in home.text                      # reason notes injected
    assert "github" not in home.text          # no repo link until CRAWLER_REPO_URL is set
    assert client.get("/docs").status_code == 200


def test_home_links_the_repository_when_configured(client, monkeypatch):
    import crawler.home as home_mod

    monkeypatch.setattr(home_mod.settings, "repo_url", "https://github.com/x/url-crawler")
    assert "https://github.com/x/url-crawler" in home_mod.render_home()


def test_every_reason_has_an_explanation_on_the_landing_page():
    from crawler.home import REASON_NOTES
    from crawler.model import Reason

    assert set(REASON_NOTES) == set(Reason)
    assert all(note.endswith(".") for note in REASON_NOTES.values())
