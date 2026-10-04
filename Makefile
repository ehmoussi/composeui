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
	QT_QPA_PLATFORM=offscreen uv run pytest tests --cov=src --cov-report=term-missing:skip-covered

# Tailwind's standalone CLI and daisyUI's plugin files: no Node/npm needed. Downloaded
# once into css/vendor/ (not committed); the built static/app.css is committed.
TAILWIND_VERSION := 4.3.3
DAISYUI_VERSION := 5.7.47
CSS_VENDOR := css/vendor
TAILWIND := $(CSS_VENDOR)/tailwindcss-$(TAILWIND_VERSION)
DAISYUI := $(CSS_VENDOR)/daisyui.mjs

$(TAILWIND):
	mkdir -p $(CSS_VENDOR)
	curl -sSfL -o $@ https://github.com/tailwindlabs/tailwindcss/releases/download/v$(TAILWIND_VERSION)/tailwindcss-linux-x64
	chmod +x $@

$(DAISYUI):
	mkdir -p $(CSS_VENDOR)
	curl -sSfL -o $@ https://github.com/saadeghi/daisyui/releases/download/v$(DAISYUI_VERSION)/daisyui.mjs

.PHONY: css
css: $(TAILWIND) $(DAISYUI)
	$(TAILWIND) -i css/app.css -o src/composeui/webcore/static/app.css --minify

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