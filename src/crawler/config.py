"""Settings. Override any value with an env var, e.g. CRAWLER_TIMEOUT_SECONDS=5"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CRAWLER_")

    # network
    timeout_seconds: float = 20.0      # per request
    total_timeout_seconds: float = 90.0  # whole crawl of one URL, all stages and retries
    max_retries: int = 3
    follow_redirects: bool = True
    max_redirects: int = 5

    # limits
    # Real news pages run large — a CNN article measured 5.6 MB.
    max_bytes: int = 20_000_000

    # politeness
    user_agent: str = "Mozilla/5.0 (compatible; URLCrawlerBot/0.1; +https://url-crawler.web.app/home)"
    respect_robots: bool = True
    robots_cache_size: int = 10_000            # origins kept per process (LRU)
    robots_cache_ttl_seconds: float = 86_400   # re-read a robots.txt daily
    robots_unavailable_ttl_seconds: float = 300  # re-check a 5xx/unreachable host soon

    # topics
    max_topics: int = 10

    # logging
    log_dir: str = "logs"     # daily files <log_name>-YYYY-MM-DD.log; stdout always on
    log_name: str = ""        # defaults to the container hostname

    # landing page
    repo_url: str = ""   # link to the public repository once it exists; empty = no link
    author_line: str = "Suraj Anumandla · BrightEdge Engineering Assignment · September 2026"


settings = Settings()
