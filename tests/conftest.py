"""Fixtures are real pages, saved gzipped. Tests never touch the network."""

import gzip
import pathlib

import pytest

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def load(name: str) -> str:
    raw = gzip.decompress((FIXTURES / f"{name}.html.gz").read_bytes())
    return raw.decode("utf-8", errors="replace")


@pytest.fixture(scope="session")
def cnn_html() -> str:
    """A real news article."""
    return load("cnn")


@pytest.fixture(scope="session")
def amazon_html() -> str:
    """A real product page. Served with no Content-Type header."""
    return load("amazon")


@pytest.fixture(scope="session")
def rei_html() -> str:
    """A real 403 block page from an Akamai edge."""
    return load("rei")
