"""Page classification. Declared markup beats inferred URL shape."""

from crawler.model import PageType
from crawler.service_pagetype import classify_page
from crawler.service_parse import parse_html

AMZ = "http://www.amazon.com/Cuisinart-CPT-122/dp/B009GQ034C/ref=sr_1_1"
CNN = "https://www.cnn.com/2025/09/23/tech/google-study-90-percent-tech-jobs-ai"


def test_real_product_page(amazon_html):
    assert parse_html(amazon_html, AMZ).page_type == PageType.product


def test_real_article(cnn_html):
    assert parse_html(cnn_html, CNN).page_type == PageType.article


def test_json_ld_beats_conflicting_og_type():
    """The most specific declaration wins, not the first one found."""
    html = ('<html><script type="application/ld+json">{"@type":"Product"}</script>'
            '<meta property="og:type" content="article"></html>')
    assert parse_html(html, "https://x.com/blog/a").page_type == PageType.product


def test_declared_markup_beats_url_shape():
    html = '<html><meta property="og:type" content="article"></html>'
    assert parse_html(html, "https://x.com/dp/123").page_type == PageType.article


def test_price_markup_implies_product():
    html = '<html><meta property="product:price:amount" content="9.99"></html>'
    assert parse_html(html, "https://x.com/z").page_type == PageType.product


def test_url_shape_is_the_last_resort():
    plain = "<html><body>hi</body></html>"
    assert parse_html(plain, "https://x.com/dp/B1").page_type == PageType.product
    assert parse_html(plain, "https://x.com/2025/09/s").page_type == PageType.article
    assert parse_html(plain, "https://x.com/category/t").page_type == PageType.listing


def test_nothing_identifiable_is_other():
    page = parse_html("<html><body>hi</body></html>", "https://x.com/xyz")
    assert page.page_type == PageType.other


def test_no_html_is_unknown():
    assert classify_page("", "https://x.com/a", {}) == PageType.unknown


def test_malformed_json_ld_does_not_raise():
    html = '<html><script type="application/ld+json">{broken</script></html>'
    assert parse_html(html, "https://x.com/a").page_type == PageType.other
