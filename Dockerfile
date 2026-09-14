# Build stage: install dependencies into a throwaway venv.
FROM python:3.12-slim AS builder

WORKDIR /build
COPY pyproject.toml ./
COPY src ./src

RUN python -m venv /opt/venv \
 && /opt/venv/bin/pip install --no-cache-dir --upgrade pip \
 && /opt/venv/bin/pip install --no-cache-dir .

# Runtime stage: only the venv and the code. No build tools, no caches.
FROM python:3.12-slim

RUN useradd --create-home --uid 1000 crawler
COPY --from=builder /opt/venv /opt/venv

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER crawler
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s \
  CMD python -c "import os,urllib.request;urllib.request.urlopen('http://127.0.0.1:'+os.getenv('PORT','8000')+'/health')"

# Shell form so ${PORT} expands. Hosting platforms inject their own port;
# default to 8000 for local runs.
CMD uvicorn crawler.app:app --host 0.0.0.0 --port ${PORT:-8000}
