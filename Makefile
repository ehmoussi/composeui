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

# the main views of the apps with catalogs, as module:Class
TRANSLATED_MAIN_VIEWS := examples.pipeform:PipeMainView \
	examples.taskview:TaskMainView

# every catalog against the text its app translates; each app reported before failing
.PHONY: translations
translations:
	@status=0; for main_view in $(TRANSLATED_MAIN_VIEWS); do \
		uv run python -m composeui.core.translationcheck $$main_view || status=1; \
	done; exit $$status

.PHONY: check
check: lint mypy translations

.PHONY: test
test:
	QT_QPA_PLATFORM=offscreen uv run pytest tests -m "not browser" --cov=src --cov-report=term-missing:skip-covered

# the web backend in headless Chromium; skipped unless Chromium is installed:
# uv run --group browser playwright install chromium
# No pytest-qt: it refuses to start without a Qt binding, which these tests don't need.
.PHONY: browser-test
browser-test:
	uv run --group browser pytest tests/test_browser.py -m browser -p no:pytest-qt

# Tailwind's standalone CLI and daisyUI's plugin files: no Node/npm needed. Downloaded
# once into css/vendor/ (not committed); the built static/app.css is committed.
TAILWIND_VERSION := 4.3.3
DAISYUI_VERSION := 5.7.47
CSS_VENDOR := css/vendor
# Tailwind's release names for this machine: linux, macos or windows (Git Bash, MSYS2 or
# Cygwin report MINGW64_NT-..., MSYS_NT-..., CYGWIN_NT-...), then x64 or arm64. Override
# it for another build, e.g. `make css TAILWIND_PLATFORM=linux-x64-musl` on Alpine.
TAILWIND_PLATFORMS := linux-x64 linux-arm64 macos-x64 macos-arm64 linux-x64-musl \
	linux-arm64-musl windows-x64
TAILWIND_PLATFORM ?= $(shell uname -s | sed -e 's/^Linux$$/linux/' -e 's/^Darwin$$/macos/' \
	-e 's/^MINGW.*/windows/' -e 's/^MSYS.*/windows/' -e 's/^CYGWIN.*/windows/')-$(shell uname -m | sed -e 's/^x86_64$$/x64/' \
	-e 's/^aarch64$$/arm64/')
# Windows only runs it as an .exe
TAILWIND_SUFFIX := $(if $(filter windows-%,$(TAILWIND_PLATFORM)),.exe)
# the platform in the name: a checkout shared between machines keeps one binary for each
TAILWIND := $(CSS_VENDOR)/tailwindcss-$(TAILWIND_VERSION)-$(TAILWIND_PLATFORM)$(TAILWIND_SUFFIX)
DAISYUI := $(CSS_VENDOR)/daisyui.mjs
DAISYUI_THEME := $(CSS_VENDOR)/daisyui-theme.mjs

$(TAILWIND):
	$(if $(filter $(TAILWIND_PLATFORM),$(TAILWIND_PLATFORMS)),,\
		$(error No Tailwind binary for '$(TAILWIND_PLATFORM)': pass one of \
		$(TAILWIND_PLATFORMS) as TAILWIND_PLATFORM))
	mkdir -p $(CSS_VENDOR)
	curl -sSfL -o $@ https://github.com/tailwindlabs/tailwindcss/releases/download/v$(TAILWIND_VERSION)/tailwindcss-$(TAILWIND_PLATFORM)$(TAILWIND_SUFFIX)
	chmod +x $@

$(DAISYUI):
	mkdir -p $(CSS_VENDOR)
	curl -sSfL -o $@ https://github.com/saadeghi/daisyui/releases/download/v$(DAISYUI_VERSION)/daisyui.mjs

$(DAISYUI_THEME):
	mkdir -p $(CSS_VENDOR)
	curl -sSfL -o $@ https://github.com/saadeghi/daisyui/releases/download/v$(DAISYUI_VERSION)/daisyui-theme.mjs

.PHONY: css
css: $(TAILWIND) $(DAISYUI) $(DAISYUI_THEME)
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