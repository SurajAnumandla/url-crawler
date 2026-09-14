"""What kind of page is this — product, article, listing?

Reads declared markup first (JSON-LD, Open Graph), falls back to URL shape only
when the page declares nothing. Same principle as metadata extraction: prefer
what the page states over what we guess.
"""

import json
import re

from selectolax.parser import HTMLParser

from crawler.model import PageType

# schema.org types, lowercased. The site is telling us directly.
SCHEMA_TYPES = {
    "product": PageType.product,
    "individualproduct": PageType.product,
    "productmodel": PageType.product,
    "offer": PageType.product,
    "article": PageType.article,
    "newsarticle": PageType.article,
    "blogposting": PageType.article,
    "techarticle": PageType.article,
    "report": PageType.article,
    "itemlist": PageType.listing,
    "collectionpage": PageType.listing,
    "searchresultspage": PageType.listing,
    "person": PageType.profile,
    "profilepage": PageType.profile,
    "organization": PageType.profile,
}

OG_TYPES = {
    "product": PageType.product,
    "product.item": PageType.product,
    "article": PageType.article,
    "profile": PageType.profile,
}

# Weakest signal — only used when nothing is declared.
URL_PATTERNS = (
    (re.compile(r"/(dp|gp/product|product|item|p)/", re.I), PageType.product),
    (re.compile(r"/(blog|news|article|story|post)/", re.I), PageType.article),
    (re.compile(r"/\d{4}/\d{1,2}/"), PageType.article),
    (re.compile(r"/(category|categories|collection|search|browse|c)/", re.I), PageType.listing),
)


def _from_json_ld(tree: HTMLParser) -> PageType | None:
    for node in tree.css('script[type="application/ld+json"]'):
        try:
            data = json.loads(node.text())
        except (ValueError, TypeError):
            continue
        for entry in data if isinstance(data, list) else [data]:
            if not isinstance(entry, dict):
                continue
            declared = entry.get("@type")
            names = declared if isinstance(declared, list) else [declared]
            for name in names:
                if isinstance(name, str) and name.lower() in SCHEMA_TYPES:
                    return SCHEMA_TYPES[name.lower()]
    return None


def _from_meta(tags: dict[str, str]) -> PageType | None:
    og = tags.get("og:type", "").lower()
    if og in OG_TYPES:
        return OG_TYPES[og]
    # Price markup is a strong implicit product signal.
    if any(k.startswith("product:") or k == "og:price:amount" for k in tags):
        return PageType.product
    return None


def _from_url(url: str) -> PageType | None:
    for pattern, page_type in URL_PATTERNS:
        if pattern.search(url):
            return page_type
    return None


def classify_page(html: str, url: str | None, tags: dict[str, str]) -> PageType:
    """Declared markup first, URL shape last. Never raises."""
    if not html:
        return PageType.unknown

    tree = HTMLParser(html)
    return (
        _from_json_ld(tree)
        or _from_meta(tags)
        or (_from_url(url) if url else None)
        or PageType.other
    )
