"""Pull metadata and body text out of HTML.

Takes an HTML string, not a URL. Never touches the network — which is what
makes it testable against saved files.
"""

import json

import trafilatura
from selectolax.parser import HTMLParser

from crawler.model import PageData
from crawler.service_pagetype import classify_page


def _meta_tags(tree: HTMLParser) -> dict[str, str]:
    """Every <meta> tag, keyed by its property or name."""
    tags: dict[str, str] = {}
    for node in tree.css("meta"):
        key = node.attributes.get("property") or node.attributes.get("name")
        content = node.attributes.get("content")
        if key and content:
            tags[key.lower()] = content.strip()
    return tags


def _prefixed(tags: dict[str, str], prefix: str) -> dict[str, str]:
    return {k: v for k, v in tags.items() if k.startswith(prefix)}


def _first_text(tree: HTMLParser, selector: str) -> str | None:
    node = tree.css_first(selector)
    if node is None:
        return None
    text = node.text(strip=True)
    return text or None


def _attr(tree: HTMLParser, selector: str, name: str) -> str | None:
    node = tree.css_first(selector)
    if node is None:
        return None
    value = node.attributes.get(name)
    return value.strip() if value else None


def _json_ld_published(tree: HTMLParser) -> str | None:
    """Read datePublished from JSON-LD, where sites actually declare it."""
    for node in tree.css('script[type="application/ld+json"]'):
        try:
            data = json.loads(node.text())
        except (ValueError, TypeError):
            continue
        for entry in data if isinstance(data, list) else [data]:
            if isinstance(entry, dict):
                value = entry.get("datePublished") or entry.get("dateCreated")
                if isinstance(value, str) and value:
                    return value
    return None


def _corroborated(value: str | None, html: str) -> str | None:
    """Only trust an extracted value if it actually appears in the document.

    trafilatura guesses when it finds nothing: it returned the author "The
    Author" for an Amazon product page containing no such string, and fell back
    to today's date as the publication date. Invented metadata is worse than
    missing metadata, so anything we cannot point to in the source is dropped.
    """
    if not value:
        return None
    return value if value in html else None


def _visible_text(html: str) -> str | None:
    """What a reader would see, when the article extractor found no article.

    Parsed afresh so the extraction above is not disturbed; used only as a
    fallback, so the extra parse is paid on the pages that need it.
    """
    tree = HTMLParser(html)
    for node in tree.css("script, style, noscript, template, svg"):
        node.decompose()
    root = tree.body or tree.root
    if root is None:
        return None
    text = " ".join(root.text(separator=" ", strip=True).split())
    return text or None


def parse_html(html: str, url: str | None = None) -> PageData:
    """HTML in, structured fields out. Never raises."""
    if not html:
        return PageData()

    tree = HTMLParser(html)
    tags = _meta_tags(tree)
    og = _prefixed(tags, "og:")
    twitter = _prefixed(tags, "twitter:")

    # trafilatura strips nav, ads, footers and comments. When it finds no
    # article at all, fall back to the visible text so a page without article
    # structure is not mistaken for an empty one.
    body = trafilatura.extract(
        html, include_comments=False, include_tables=False, url=url
    ) or _visible_text(html)

    # Fall back to trafilatura's own metadata for author and date, which it
    # works harder at than a single meta tag lookup.
    meta = trafilatura.extract_metadata(html)

    title = _first_text(tree, "title") or og.get("og:title") or (meta.title if meta else None)
    description = (
        tags.get("description") or og.get("og:description") or twitter.get("twitter:description")
    )
    author = tags.get("author") or _corroborated(meta.author if meta else None, html)
    # Declared publication metadata only. trafilatura's date is not used as a
    # fallback: htmldate returns today's date when it finds nothing, which
    # reports every undated page as published today.
    published = (
        tags.get("article:published_time")
        or tags.get("publishdate")
        or tags.get("pubdate")
        or _json_ld_published(tree)
        or _attr(tree, "time[datetime]", "datetime")
    )
    language = _attr(tree, "html", "lang") or tags.get("language")

    return PageData(
        title=title,
        description=description,
        canonical_url=_attr(tree, 'link[rel="canonical"]', "href"),
        author=author,
        published_date=published,
        language=language,
        h1_headings=[h.text(strip=True) for h in tree.css("h1") if h.text(strip=True)],
        og_tags=og,
        twitter_tags=twitter,
        body=body,
        word_count=len(body.split()) if body else 0,
        page_type=classify_page(html, url, tags),
    )
