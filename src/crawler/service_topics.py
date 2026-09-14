"""Work out what a page is about.

Uses YAKE, which scores keyphrases from a single document using statistics —
word position, frequency, and how varied a word's neighbours are.

Why not TF-IDF: the IDF half needs a corpus of many documents to know which
words are rare. With one page there is no corpus, so TF-IDF collapses into raw
word counting and "the" wins. YAKE is built for the single-document case.

This is unsupervised keyphrase extraction: no taxonomy, no training data, so
its quality is unmeasured until a labelled set exists. Page classification is
a separate output, produced by service_pagetype from declared markup.
"""

import yake

from crawler.config import settings
from crawler.logging import log
from crawler.model import Topic

# YAKE scores are "lower is better". Anything above this is weak.
MAX_SCORE = 0.5

# Phrases appearing in the title or an h1 are more likely to be the real subject.
TITLE_BOOST = 0.6


def _normalise(phrase: str) -> str:
    return " ".join(phrase.lower().split())


def _is_near_duplicate(phrase: str, kept: list[str]) -> bool:
    """Drop 'google ai' when we already kept 'google ai study'."""
    words = set(phrase.split())
    for existing in kept:
        other = set(existing.split())
        overlap = len(words & other) / max(len(words), len(other))
        if overlap >= 0.6:
            return True
    return False


def extract_topics(
    body: str | None,
    title: str | None = None,
    headings: list[str] | None = None,
) -> list[Topic]:
    """Body text in, ranked topics out. Never raises."""
    if not body or len(body.split()) < 20:
        return []

    try:
        extractor = yake.KeywordExtractor(
            lan="en",
            n=3,              # up to 3-word phrases
            dedupLim=0.7,
            top=settings.max_topics * 3,
        )
        candidates = extractor.extract_keywords(body)
    except Exception as exc:
        # An empty list must be distinguishable from a crashed extractor:
        # the 'empty topic rate' metric depends on it.
        log.warning("topics.failed", error=str(exc), error_type=type(exc).__name__)
        return []

    prominent = _normalise(" ".join(filter(None, [title, *(headings or [])])))

    scored: list[tuple[str, float]] = []
    for phrase, score in candidates:
        clean = _normalise(phrase)
        if len(clean) < 3 or clean.isdigit():
            continue
        if clean in prominent:
            score *= TITLE_BOOST
        scored.append((clean, score))

    scored.sort(key=lambda pair: pair[1])

    topics: list[Topic] = []
    kept: list[str] = []
    for phrase, score in scored:
        if score > MAX_SCORE or _is_near_duplicate(phrase, kept):
            continue
        kept.append(phrase)
        # Flip to "higher is better" so the JSON reads the way people expect.
        topics.append(Topic(topic=phrase, score=round(max(0.0, 1.0 - score), 3)))
        if len(topics) >= settings.max_topics:
            break

    return topics
