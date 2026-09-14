"""Topics come from body text alone."""

from crawler.service_parse import parse_html
from crawler.service_topics import extract_topics


def test_cnn_topics_are_about_the_article(cnn_html):
    page = parse_html(cnn_html)
    topics = extract_topics(page.body, page.title, page.h1_headings)
    joined = " ".join(t.topic for t in topics)
    assert topics
    assert "google" in joined


def test_amazon_topics_name_the_product(amazon_html):
    page = parse_html(amazon_html)
    topics = extract_topics(page.body, page.title, page.h1_headings)
    joined = " ".join(t.topic for t in topics)
    assert "toaster" in joined


def test_scores_are_ranked_and_bounded(cnn_html):
    page = parse_html(cnn_html)
    scores = [t.score for t in extract_topics(page.body, page.title)]
    assert all(0.0 <= s <= 1.0 for s in scores)
    assert scores == sorted(scores, reverse=True)


def test_too_little_text_yields_nothing():
    assert extract_topics("three words only") == []


def test_no_body_yields_nothing():
    assert extract_topics(None) == []


def test_extractor_failure_is_logged_not_swallowed(monkeypatch):
    import crawler.service_topics as mod

    class Boom:
        def __init__(self, **kwargs):
            raise RuntimeError("model missing")

    warnings: list[dict] = []
    monkeypatch.setattr(mod.yake, "KeywordExtractor", Boom)
    class Log:
        def warning(self, event, **kw):
            warnings.append({"event": event, **kw})

    monkeypatch.setattr(mod, "log", Log())
    assert extract_topics("word " * 50) == []
    assert warnings and warnings[0]["event"] == "topics.failed"
    assert warnings[0]["error_type"] == "RuntimeError"
