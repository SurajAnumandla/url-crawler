PYTHON ?= python3.12
VENV   := .venv
PY     := $(VENV)/bin/python

.PHONY: setup test lint typecheck check run serve clean

# Creates the venv only if it is missing.
$(PY):
	$(PYTHON) -m venv $(VENV)

setup: $(PY)
	$(PY) -m pip install -q --upgrade pip
	$(PY) -m pip install -e ".[dev]"

test: ; $(PY) -m pytest
lint: ; $(PY) -m ruff check .
typecheck: ; $(PY) -m mypy
check: lint typecheck test

run: ; $(PY) -m crawler "$(URL)"
serve: ; $(PY) -m uvicorn crawler.app:app --host 0.0.0.0 --port 8000

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache src/*.egg-info
