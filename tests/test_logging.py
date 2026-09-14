"""Logs: JSON lines with timestamp and level, to stdout and to a daily file."""

import json
import logging
from datetime import UTC, datetime

import structlog
from fastapi.testclient import TestClient

import crawler.logging as logmod
from crawler.app import app


def test_daily_file_has_timestamp_level_and_container_name(tmp_path, monkeypatch):
    monkeypatch.setattr(logmod.settings, "log_dir", str(tmp_path))
    monkeypatch.setattr(logmod.settings, "log_name", "crawler-test")
    logmod.setup_logging("INFO")
    structlog.get_logger().info("unit.event", answer=42)
    for h in logging.getLogger().handlers:
        h.flush()
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    path = tmp_path / f"crawler-test-{today}.log"
    assert path.exists(), list(tmp_path.iterdir())
    line = json.loads(path.read_text().strip().splitlines()[-1])
    assert line["event"] == "unit.event" and line["answer"] == 42
    assert line["level"] == "info"
    assert line["timestamp"].startswith(today)


def test_every_request_is_logged_with_headers_and_redaction(tmp_path, monkeypatch):
    monkeypatch.setattr(logmod.settings, "log_dir", str(tmp_path))
    monkeypatch.setattr(logmod.settings, "log_name", "crawler-test")
    logmod.setup_logging("INFO")
    with TestClient(app) as client:
        client.get("/health", headers={"X-Trace": "abc", "Authorization": "Bearer secret"})
    for h in logging.getLogger().handlers:
        h.flush()
    logfile = next(tmp_path.iterdir())
    lines = [json.loads(line) for line in logfile.read_text().splitlines()]
    req = [e for e in lines if e["event"] == "http.request" and e["path"] == "/health"][-1]
    assert req["method"] == "GET" and req["status"] == 200 and req["duration_ms"] >= 0
    assert req["headers"]["x-trace"] == "abc"
    assert req["headers"]["authorization"] == "[redacted]"
    assert "secret" not in json.dumps(req)
    assert req["body"] == "" and req["body_bytes"] == 0
