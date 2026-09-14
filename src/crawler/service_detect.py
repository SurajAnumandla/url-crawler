"""Spot a block page that arrived with a 200 status.

Some sites return HTTP 200 and serve a CAPTCHA or "access denied" page instead
of the content. Status codes alone miss those.

Two checks, at two points in the pipeline:

- CAPTCHA pages carry distinctive phrases and form markup, so they are found
  on the raw HTML before parsing (cheap; no parse of a page we will discard).
- Everything else is decided after parsing, from two properties every
  block, maintenance or soft-404 page shares whatever its wording or language:
  almost no extracted text (under MAX_BLOCK_PAGE_WORDS after boilerplate
  removal) and no declared metadata (no description, canonical, Open Graph,
  Twitter, JSON-LD type, author or date — nobody marks an error page up for
  search engines). Such a page is reported as no_content. If its title or
  heading also says it is a denial, that is upgraded to forbidden: calling a
  page a block is a stronger claim and needs the page to say so. Its limit: a
  page whose surrounding chrome survives extraction as more than the word
  limit is reported as content.

Deliberately NOT used as a signal: the ratio of visible text to HTML size.
JavaScript-heavy pages score terribly on it while serving good content.
"""

from crawler.model import PageData, PageType, Reason

# Lowercase. Matched against the start of the raw document.
CAPTCHA_MARKERS = (
    "robot check",
    "enter the characters you see below",
    "validatecaptcha",
    "/errors/validatecaptcha",
    "type the characters you see in this image",
    "are you a robot",
    "verify you are a human",
    "unusual traffic from your computer network",
    "robot or human",  # measured: walmart.com challenge page, 2026-09-14
)

# Lowercase. Refinement only: matched against the parsed title and h1 headings
# of a page already found to carry no content, to name it a denial.
DENIED_MARKERS = (
    "access denied",
    "attention required",
    "just a moment",
    "you don't have permission to access",
    "request blocked",
)

SCAN_CHARS = 20_000       # CAPTCHA markers: head of the document
MAX_BLOCK_PAGE_WORDS = 100  # a block or error page has no article behind its heading


def detect_captcha(html: str) -> Reason | None:
    """Return Reason.captcha if the raw HTML is a CAPTCHA page, else None."""
    if not html:
        return None
    head = html[:SCAN_CHARS].lower()
    return Reason.captcha if any(marker in head for marker in CAPTCHA_MARKERS) else None


def _declares_metadata(page: PageData) -> bool:
    """Does the page mark itself up for search engines at all?"""
    return bool(
        page.description
        or page.canonical_url
        or page.og_tags
        or page.twitter_tags
        or page.author
        or page.published_date
        or page.page_type not in (PageType.other, PageType.unknown)
    )


def detect_denial(page: PageData) -> Reason | None:
    """Return why the parsed page is not the content, or None if it is.

    Generic rule first: near-empty extracted text and no declared metadata →
    no_content. Refinement: if such a page names itself a denial → forbidden.
    """
    if page.word_count >= MAX_BLOCK_PAGE_WORDS:
        return None
    probe = " ".join([page.title or "", *page.h1_headings]).lower()
    if any(marker in probe for marker in DENIED_MARKERS):
        return Reason.forbidden
    if not _declares_metadata(page):
        return Reason.no_content
    return None
