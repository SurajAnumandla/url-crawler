"""Run the crawler against a broad, deliberately hostile set of live URLs.

Prints one line per URL and a status/reason distribution. The point is not
that every URL succeeds — many should be blocked or errors — but that every
URL yields a CrawlResult (nothing raises) and that the reasons are right.

Usage: python scripts/smoke.py [--live https://service.run.app]
"""

import asyncio
import sys
import time
from collections import Counter

import httpx

sys.path.insert(0, "src")
from crawler.model import CrawlResult  # noqa: E402
from crawler.service_crawl import crawl_url  # noqa: E402
from crawler.service_download import make_client  # noqa: E402

URLS = [
    # news and articles
    "https://www.bbc.com/news", "https://www.theguardian.com/international", "https://www.reuters.com/",
    "https://techcrunch.com/", "https://arstechnica.com/", "https://www.thehindu.com/",
    # e-commerce
    "https://www.walmart.com/ip/Cuisinart-2-Slice-Compact-Plastic-Toaster-White/17160185",
    "https://www.bestbuy.com/site/apple-airpods-pro-2/6447382.p", "https://www.flipkart.com/",
    "https://www.etsy.com/", "https://www.target.com/", "https://www.myntra.com/45710099",
    # blogs, docs, reference
    "https://blog.cloudflare.com/", "https://docs.python.org/3/library/asyncio.html",
    "https://github.com/encode/httpx", "https://stackoverflow.com/questions/231767",
    "https://dev.to/henriavo/design-a-web-crawler-1ecn", "https://www.rfc-editor.org/rfc/rfc9309.html",
    "https://en.wikipedia.org/wiki/Web_crawler",
    # government and non-English
    "https://www.gov.uk/", "https://www.spiegel.de/", "https://www.lemonde.fr/", "https://www.asahi.com/",
    "https://www.naver.com/", "https://ar.wikipedia.org/wiki/الصفحة_الرئيسية",
    # JavaScript-heavy applications
    "https://www.linkedin.com/", "https://twitter.com/", "https://www.netflix.com/",
    # non-HTML and odd responses
    "https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf", "https://httpbin.org/json",
    "https://httpbin.org/image/png", "https://httpbin.org/status/500", "https://httpbin.org/status/404",
    "https://httpbin.org/status/429", "https://httpbin.org/redirect/3", "https://httpbin.org/encoding/utf8",
    "https://httpbin.org/html", "https://httpbin.org/gzip", "https://example.com/",
    # broken and hostile
    "https://expired.badssl.com/", "https://self-signed.badssl.com/", "http://nonexistent-host-xyz.invalid/",
    "http://192.168.1.1/", "http://169.254.169.254/computeMetadata/v1/", "http://localhost:8000/health",
    "ftp://ftp.example.com/", "mailto:a@b.c", "javascript:alert(1)", "https://example.com/" + "a" * 3000,
    "https://xn--nxasmq6b.com/", "https://www.example.com/%ZZ", "https://[::1]/",
]


async def local(url: str, client: httpx.AsyncClient) -> CrawlResult:
    return await crawl_url(url, client)


async def remote(url: str, client: httpx.AsyncClient, base: str) -> CrawlResult:
    response = await client.get(f"{base}/extract", params={"url": url}, timeout=130)
    response.raise_for_status()
    return CrawlResult.model_validate(response.json())


async def main() -> int:
    base = sys.argv[sys.argv.index("--live") + 1].rstrip("/") if "--live" in sys.argv else None
    semaphore = asyncio.Semaphore(4)
    counts: Counter[tuple[str, str]] = Counter()
    raised = 0

    async def one(url: str, client: httpx.AsyncClient) -> None:
        nonlocal raised
        started = time.perf_counter()
        async with semaphore:
            try:
                r = await (remote(url, client, base) if base else local(url, client))
            except Exception as exc:  # the whole point: this must not happen
                raised += 1
                print(f"RAISED   {type(exc).__name__:22s} {url[:70]}  {exc}")
                return
        counts[(r.status.value, r.reason.value)] += 1
        print(f"{r.status.value:8s} {r.reason.value:22s} {str(r.http_status):4s} {r.page_type.value:8s} "
              f"{r.word_count:6d}w {len(r.topics):2d}t {time.perf_counter() - started:5.1f}s  {url[:70]}")

    async with make_client() as client:
        await asyncio.gather(*(one(u, client) for u in URLS))
    print("\nstatus / reason distribution:")
    for (status, reason), n in counts.most_common():
        print(f"  {n:3d}  {status:8s} {reason}")
    print(f"\n{len(URLS)} URLs, {raised} raised")
    return 1 if raised else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
