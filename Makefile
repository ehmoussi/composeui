.PHONY: format
format:
	uv run ruff format

.PHONY: check
check:
	uv run ruff check

.PHONY: check_fix
check_fix:
	uv run ruff check --fix

.PHONY: lint
lint: format check_fix
	
.PHONY: mypy
mypy:
	uv run mypy \
		--config-file pyproject.toml \
		--package composeui \
		--package examples \
		--always-false=PYQT5 \
		--always-false=PYSIDE2 \
		--always-false=PYQT6 \
		--always-true=PYSIDE6 \
		--show-traceback

.PHONY: check
check: lint mypy

.PHONY: test
test:
	uv run pytest tests --cov=src --cov-report=term-missing:skip-covered

.PHONY: clean
clean:
	rm -rf `find . -name __pycache__`
	rm -f `find . -type f -name '*.py[co]'`
	rm -f `find . -type f -name '*~'`
	rm -f `find . -type f -name '.*~'`
	rm -rf .cache
	rm -rf .pytest_cache
	rm -rf .ruff_cache
	rm -rf htmlcov
	rm -rf *.egg-info
	rm -f .coverage
	rm -f .coverage.*
	rm -rf build
	rm -rf dist
	rm -rf site
	rm -rf coverage.xml

.PHONY: all
all: clean check test