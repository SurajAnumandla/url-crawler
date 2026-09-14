"""Parsing is a pure function of HTML. No network."""

from crawler.service_parse import parse_html


def test_cnn_title(cnn_html):
    assert "Google says 90%" in parse_html(cnn_html).title


def test_cnn_author_and_date(cnn_html):
    page = parse_html(cnn_html)
    assert page.author == "Lisa Eadicicco"
    assert page.published_date.startswith("2025-09-23")


def test_cnn_language_and_canonical(cnn_html):
    page = parse_html(cnn_html)
    assert page.language == "en"
    assert page.canonical_url.startswith("https://www.cnn.com/")


def test_cnn_og_and_twitter_tags(cnn_html):
    page = parse_html(cnn_html)
    assert page.og_tags["og:type"] == "article"
    assert "twitter:card" in page.twitter_tags


def test_cnn_body_is_article_not_chrome(cnn_html):
    body = parse_html(cnn_html).body
    assert "artificial intelligence" in body
    assert "Ad Feedback" not in body       # nav/ads stripped
    assert parse_html(cnn_html).word_count > 300


def test_amazon_title_and_headings(amazon_html):
    page = parse_html(amazon_html)
    assert "Cuisinart" in page.title
    assert any("Toaster" in h for h in page.h1_headings)


def test_empty_html_returns_empty_page():
    page = parse_html("")
    assert page.title is None and page.word_count == 0


def test_garbage_does_not_raise():
    page = parse_html("<<<>>> not html at all &&&")
    assert page.title is None and page.page_type == "other"   # visible text is kept as body


def test_product_page_invents_no_author(amazon_html):
    """Regression: trafilatura returned the author 'The Author' for a page
    containing no such string. Missing metadata beats invented metadata."""
    assert parse_html(amazon_html).author is None


def test_product_page_invents_no_date(amazon_html):
    """Regression: htmldate falls back to today's date when it finds nothing,
    which reported an undated product page as published today."""
    assert parse_html(amazon_html).published_date is None


def test_article_still_reports_real_author_and_date(cnn_html):
    """The strictness above must not cost us genuine metadata."""
    page = parse_html(cnn_html)
    assert page.author == "Lisa Eadicicco"
    assert page.published_date.startswith("2025-09-23")


def test_page_without_article_structure_still_yields_its_visible_text():
    """trafilatura finds no article in a bare text page; the visible text is the body."""
    words = " ".join(f"word{i}" for i in range(150))
    html = (f"<html><head><title>Plain</title><script>var x=1;</script></head>"
            f"<body>{words}</body></html>")
    page = parse_html(html)
    assert page.word_count >= 150
    assert "var x" not in (page.body or "")
