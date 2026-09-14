"""Block detection: CAPTCHA on raw HTML before parsing; denial on the parsed page."""

from crawler.model import Reason
from crawler.service_detect import detect_captcha, detect_denial
from crawler.service_parse import parse_html


def test_rei_block_page_is_a_denial(rei_html):
    """A real 403 body from an Akamai edge: title 'Access Denied', no content."""
    assert detect_denial(parse_html(rei_html)) == Reason.forbidden


def test_real_article_is_not_blocked(cnn_html):
    """Regression: CNN has a very low text-to-HTML ratio because it is
    JavaScript-heavy. Using that ratio as a block signal flags it wrongly."""
    assert detect_captcha(cnn_html) is None
    assert detect_denial(parse_html(cnn_html)) is None


def test_real_product_page_is_not_blocked(amazon_html):
    assert detect_captcha(amazon_html) is None
    assert detect_denial(parse_html(amazon_html)) is None


def test_captcha_marker():
    assert detect_captcha("<html>Enter the characters you see below</html>") == Reason.captcha


def test_empty_html():
    assert detect_captcha("") is None
    # Nothing extracted and nothing declared: no content.
    assert detect_denial(parse_html("")) == Reason.no_content


def test_templated_waf_page_is_a_denial():
    """Brand in the title, inline CSS, 'Access Denied' as the heading, no body."""
    html = ("<html><head><title>Example Store</title><style>" + "a{color:red}" * 300
            + "</style></head><body><h1>Access Denied</h1><p>Reference #18.abc</p></body></html>")
    assert detect_denial(parse_html(html)) == Reason.forbidden


def test_branded_block_page_with_site_chrome_is_a_denial():
    """Navigation, footer, inline CSS and scripts around a denial title; the
    extracted body stays under the word limit, so byte size is not the signal."""
    items = "".join(f"<li><a href='/c{i}'>Category {i}</a></li>" for i in range(20))
    chrome = f"<nav><ul>{items}</ul></nav>"
    bulk = "<style>" + ".x{margin:0}" * 3000 + "</style><script>" + "var a=1;" * 3000 + "</script>"
    html = ("<html><head><title>Access Denied</title>" + bulk + "</head>"
            f"<body>{chrome}<p>Blocked.</p><footer>{chrome}</footer></body></html>")
    assert len(html) > 50_000
    assert detect_denial(parse_html(html)) == Reason.forbidden


def test_article_that_mentions_access_denied_is_not_a_block():
    """Denial phrases are ordinary English. An article containing them is content."""
    paragraph = "<p>The user saw an access denied message; attention required, it said.</p>"
    html = "<html><head><title>How error pages work</title></head><body>" + paragraph * 200
    assert detect_denial(parse_html(html)) is None


def test_article_titled_attention_required_with_real_body_is_not_a_block():
    body = "<p>" + "Words about attention and how it is required in practice. " * 80 + "</p>"
    html = f"<html><head><title>Attention Required: a study</title></head><body>{body}</body>"
    page = parse_html(html)
    assert page.word_count >= 100
    assert detect_denial(page) is None


def test_maintenance_page_with_200_is_no_content():
    """Measured case: Myntra served this to the crawler's User-Agent with HTTP 200
    while a browser User-Agent received the product page. No phrase list is
    involved: the page has 8 words and declares no metadata."""
    html = ("<html><head><title>Site Maintenance</title></head><body>"
            "<h1>Oops! Something went wrong</h1>"
            "<p>Please contact your administrator</p></body></html>")
    assert detect_denial(parse_html(html)) == Reason.no_content


def test_unknown_wording_and_language_is_still_no_content():
    html = ("<html><head><title>Wir sind gleich zurück</title></head><body>"
            "<h1>Wartungsarbeiten</h1>"
            "<p>Bitte versuchen Sie es später erneut.</p></body></html>")
    assert detect_denial(parse_html(html)) == Reason.no_content


def test_short_page_that_declares_metadata_is_content():
    """A thin but real page: a description and canonical say it is meant to be indexed."""
    html = ('<html><head><title>Contact us</title>'
            '<meta name="description" content="How to reach us">'
            '<link rel="canonical" href="https://x.test/contact"></head>'
            "<body><h1>Contact us</h1><p>Call us on 555-0100, Monday to Friday.</p></body></html>")
    assert detect_denial(parse_html(html)) is None


def test_article_about_maintenance_is_content():
    body = "<p>" + "How teams plan site maintenance windows without downtime. " * 60 + "</p>"
    html = f"<html><head><title>Site maintenance done right</title></head><body>{body}</body>"
    assert detect_denial(parse_html(html)) is None


def test_walmart_style_challenge_is_a_captcha():
    html = "<html><title>Robot or human?</title><body>Activate and hold</body></html>"
    assert detect_captcha(html) == Reason.captcha
