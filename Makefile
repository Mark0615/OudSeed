PYTHON ?= .venv/bin/python
PIP ?= .venv/bin/pip

.PHONY: install test lint run check clean

install:
	$(PIP) install -r requirements.txt

test:
	$(PYTHON) -m pytest

lint:
	$(PYTHON) -m compileall src tests

run:
	$(PYTHON) -m src.main

check:
	$(PYTHON) -m compileall src tests && $(PYTHON) -m pytest

clean:
	find . -type d -name "__pycache__" -prune -exec rm -rf {} +
	find . -type d -name ".pytest_cache" -prune -exec rm -rf {} +
	find . -type d -name ".mypy_cache" -prune -exec rm -rf {} +
