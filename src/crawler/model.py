"""The shape of the JSON we return. Every other module agrees on this."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class Status(StrEnum):
    success = "success"
    blocked = "blocked"  # site refused us
    error = "error"      # something failed


class Reason(StrEnum):
    ok = "ok"

    # blocked — retrying unchanged will not help
    robots_disallowed = "robots_disallowed"
    captcha = "captcha"
    forbidden = "forbidden"
    rate_limited = "rate_limited"

    # error — transport or content problem
    bad_url = "bad_url"
    private_address = "private_address"  # loopback, private, link-local or reserved target
    robots_unavailable = "robots_unavailable"  # robots.txt answered 5xx; not a refusal
    dns_error = "dns_error"
    connect_error = "connect_error"
    timeout = "timeout"
    server_error = "server_error"
    not_found = "not_found"
    client_error = "client_error"
    redirect_not_followed = "redirect_not_followed"  # 3xx while redirects are disabled
    not_html = "not_html"
    too_large = "too_large"
    parse_failed = "parse_failed"
    no_content = "no_content"  # 200 with almost no extracted text and no declared metadata


class PageType(StrEnum):
    """What kind of page this is. The spec asks us to classify the page as well
    as return its topics."""

    product = "product"
    article = "article"
    listing = "listing"
    profile = "profile"
    other = "other"      # readable HTML, but nothing identifies it
    unknown = "unknown"  # we never got the page


class Topic(BaseModel):
    topic: str
    score: float


class RobotsState(StrEnum):
    """What robots.txt said, or why it could not say anything."""

    allowed = "allowed"
    disallowed = "disallowed"
    missing = "missing"          # 4xx: unrestricted per RFC 9309
    unavailable = "unavailable"  # 5xx: hold off; an error, not a refusal
    unreachable = "unreachable"  # could not connect; the page fetch reports the real error
    skipped = "skipped"          # robots checking disabled


class RobotsResult(BaseModel):
    """Why we may or may not crawl. State matters: a robots.txt we could not
    reach is a different fact from one that says no."""

    allowed: bool
    state: RobotsState


class PageData(BaseModel):
    """What we pulled out of the HTML. Internal — not the final JSON."""

    title: str | None = None
    description: str | None = None
    canonical_url: str | None = None
    author: str | None = None
    published_date: str | None = None
    language: str | None = None
    h1_headings: list[str] = Field(default_factory=list)
    og_tags: dict[str, str] = Field(default_factory=dict)
    twitter_tags: dict[str, str] = Field(default_factory=dict)
    body: str | None = None
    word_count: int = 0
    page_type: PageType = PageType.unknown


class DownloadResult(BaseModel):
    """What the downloader hands back. Internal — not the final JSON."""

    ok: bool
    reason: Reason
    html: str | None = None
    final_url: str | None = None
    http_status: int | None = None
    content_type: str | None = None


class CrawlResult(BaseModel):
    """What the crawler returns, whatever happened."""

    # request
    url: str
    final_url: str | None = None
    status: Status
    reason: Reason
    http_status: int | None = None
    content_type: str | None = None
    fetched_at: datetime
    # None only when the URL was rejected before the robots check.
    robots_state: RobotsState | None = None

    # metadata
    title: str | None = None
    description: str | None = None
    canonical_url: str | None = None
    author: str | None = None
    published_date: str | None = None
    language: str | None = None
    h1_headings: list[str] = Field(default_factory=list)
    og_tags: dict[str, str] = Field(default_factory=dict)
    twitter_tags: dict[str, str] = Field(default_factory=dict)

    # content
    body: str | None = None
    word_count: int = 0
    page_type: PageType = PageType.unknown
    topics: list[Topic] = Field(default_factory=list)
