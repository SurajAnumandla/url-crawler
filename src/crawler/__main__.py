"""CLI.  Usage: python -m crawler <url>

The web door is app.py. Both call service_crawl.
"""

import argparse
import asyncio
import sys

from crawler.logging import setup_logging
from crawler.model import Status
from crawler.service_crawl import crawl_url


def main() -> None:
    parser = argparse.ArgumentParser(prog="crawler", description="Crawl one URL, print JSON.")
    parser.add_argument("url", help="the URL to crawl")
    parser.add_argument("--quiet", action="store_true", help="suppress logs")
    args = parser.parse_args()

    setup_logging("ERROR" if args.quiet else "INFO")
    result = asyncio.run(crawl_url(args.url))
    print(result.model_dump_json(indent=2))
    sys.exit(0 if result.status == Status.success else 1)


if __name__ == "__main__":
    main()
