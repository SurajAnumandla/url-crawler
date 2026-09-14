"""Structured JSON logs: one line per event with timestamp, level and fields.

Two destinations. Standard output, which the hosting platform collects (Cloud
Logging on Cloud Run). And a daily file under a logs folder, named
<name>-YYYY-MM-DD.log, where <name> is the container's hostname unless
CRAWLER_LOG_NAME says otherwise; a new file starts at midnight UTC. If the
folder cannot be written, logging continues on stdout alone.
"""

import contextlib
import logging
import socket
from datetime import UTC, datetime
from pathlib import Path
from typing import TextIO

import structlog

from crawler.config import settings


class DailyFileHandler(logging.Handler):
    """Append to <dir>/<name>-<date>.log, opening a new file when the UTC date changes."""

    def __init__(self, directory: Path, name: str) -> None:
        super().__init__()
        self.directory = directory
        self.name_prefix = name
        self._date = ""
        self._stream: TextIO | None = None

    def _path_for(self, date: str) -> Path:
        return self.directory / f"{self.name_prefix}-{date}.log"

    def emit(self, record: logging.LogRecord) -> None:
        try:
            today = datetime.now(UTC).strftime("%Y-%m-%d")
            if today != self._date:
                if self._stream is not None:
                    self._stream.close()
                self.directory.mkdir(parents=True, exist_ok=True)
                self._stream = self._path_for(today).open("a", encoding="utf-8")
                self._date = today
            assert self._stream is not None
            self._stream.write(self.format(record) + "\n")
            self._stream.flush()
        except Exception:
            self.handleError(record)

    def close(self) -> None:
        if self._stream is not None:
            self._stream.close()
        super().close()


def log_name() -> str:
    return settings.log_name or socket.gethostname()


def setup_logging(level: str = "INFO") -> None:
    """Every record — ours and third-party libraries' — becomes one JSON line."""
    shared: list[structlog.types.Processor] = [
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
    ]
    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        foreign_pre_chain=shared,  # stdlib loggers (httpx, uvicorn…) get the same shape
    )
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    with contextlib.suppress(OSError):  # read-only filesystem: stdout only
        handlers.append(DailyFileHandler(Path(settings.log_dir), log_name()))
    for handler in handlers:
        handler.setFormatter(formatter)
    root = logging.getLogger()
    root.handlers[:] = handlers
    root.setLevel(getattr(logging, level.upper()))
    structlog.configure(
        processors=[*shared, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, level.upper())),
        cache_logger_on_first_use=False,
    )


log = structlog.get_logger()
