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
	uv run --locked --group browser --all-extras mypy \
		--config-file pyproject.toml \
		--package composeui \
		--package examples \
		--package tests \
		--always-false=PYQT5 \
		--always-false=PYSIDE2 \
		--always-false=PYQT6 \
		--always-true=PYSIDE6 \
		--show-traceback

# Tests import every backend and Playwright; static checks need their packages, not Chromium.
TYPECHECK_RUN = uv run --locked --group typecheck --group browser --all-extras

.PHONY: typecheck pyright pyrefly ty zuban
typecheck: mypy pyright pyrefly ty

pyright:
	$(TYPECHECK_RUN) pyright

pyrefly:
	$(TYPECHECK_RUN) pyrefly check

ty:
	$(TYPECHECK_RUN) ty check

# Keep its nonzero exit visible locally; CI runs Zuban as a non-blocking job.
zuban:
	$(TYPECHECK_RUN) zuban mypy tests

# the main views of the apps with catalogs, as module:Class
TRANSLATED_MAIN_VIEWS := examples.pipeform:PipeMainView \
	examples.pipesweep:PipeSweepMainView \
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
# in parallel, a worker per CPU (pytest-xdist)
test:
	QT_QPA_PLATFORM=offscreen uv run pytest tests -m "not browser" -n auto --cov=src --cov-report=term-missing:skip-covered

# the web backend in headless Chromium; skipped unless Chromium is installed:
# uv run --group browser playwright install chromium
# No pytest-qt: it refuses to start without a Qt binding, which these tests don't need.
.PHONY: browser-test
browser-test:
	uv run --group browser pytest tests/test_browser.py -m browser -p no:pytest-qt

# the documentation site (Sphinx + MyST): the guides, the widget catalog and the API
# reference, in docs/_build/html; any warning fails it. The API reference imports every
# backend's application module: run `uv sync --group docs --all-extras` first.
.PHONY: docs
docs:
	uv run --group docs sphinx-build -W --keep-going -b html docs docs/_build/html

# the screenshots of the examples guide, on every backend, into docs/images/; needs the
# browser group's Chromium (see browser-test). Pass names to take only some of them:
# make screenshots EXAMPLES="pipeform batman"
.PHONY: screenshots
screenshots:
	QT_QPA_PLATFORM=offscreen uv run --group browser python docs/screenshots.py $(EXAMPLES)

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
# the SHA-256 of each download, from Tailwind's sha256sums.txt and the digests of daisyUI's
# release assets: change them with the versions
TAILWIND_SHA256_linux-x64 := dc61b3ac6b8c9ca874c0cc4c57b2409791a64c5540404ca5f5367360babc313a
TAILWIND_SHA256_linux-arm64 := 55fd0b241214eff3de1e8ee4f22796662f2d2e7a49bcfca7477cfd0bac398195
TAILWIND_SHA256_macos-x64 := 7922e0953f2110c05976e3bf58f14e643d90427575e766b7d433f5f80cbee7e1
TAILWIND_SHA256_macos-arm64 := cdf646702987a743464dff4d9c60fd4480d1c1e73dd819a9a67f1078815dce9d
TAILWIND_SHA256_linux-x64-musl := a04d34ceacc8f52cbe8920ad846cdeb61d3d0021dba32db0d1f77c9d9fad7a6c
TAILWIND_SHA256_linux-arm64-musl := 71ea4be79c9de9827545682df3e040053fb535d37c71ed2cfdedf9385a0868e0
TAILWIND_SHA256_windows-x64 := e0e260ce048014e9268f6237ff18f8ccf02cef521cbd0ae04e82c2cdf7aa3955
TAILWIND_SHA256 := $(TAILWIND_SHA256_$(TAILWIND_PLATFORM))
DAISYUI_SHA256 := 85819d3fe86a852237b439b13f481481aac58e562ac47694cd11c3038e994f2a
DAISYUI_THEME_SHA256 := d92d2f488933dab757f046e81ebd4986e51e9423307798dc3545d09a15542c89
# macOS before 15 has shasum, not sha256sum
SHA256SUM := $(shell command -v sha256sum >/dev/null 2>&1 && echo sha256sum || echo shasum -a 256)
# download URL $(1) into file $(2), kept only when its SHA-256 is $(3)
fetch = mkdir -p $(dir $(2)) && curl -sSfL -o $(2).tmp $(1) \
	&& { echo "$(3)  $(2).tmp" | $(SHA256SUM) -c || { rm -f $(2).tmp; exit 1; }; } \
	&& mv $(2).tmp $(2)

$(TAILWIND):
	$(if $(filter $(TAILWIND_PLATFORM),$(TAILWIND_PLATFORMS)),,\
		$(error No Tailwind binary for '$(TAILWIND_PLATFORM)': pass one of \
		$(TAILWIND_PLATFORMS) as TAILWIND_PLATFORM))
	$(call fetch,https://github.com/tailwindlabs/tailwindcss/releases/download/v$(TAILWIND_VERSION)/tailwindcss-$(TAILWIND_PLATFORM)$(TAILWIND_SUFFIX),$@,$(TAILWIND_SHA256))
	chmod +x $@

$(DAISYUI):
	$(call fetch,https://github.com/saadeghi/daisyui/releases/download/v$(DAISYUI_VERSION)/daisyui.mjs,$@,$(DAISYUI_SHA256))

$(DAISYUI_THEME):
	$(call fetch,https://github.com/saadeghi/daisyui/releases/download/v$(DAISYUI_VERSION)/daisyui-theme.mjs,$@,$(DAISYUI_THEME_SHA256))

# the files already there are checked too: they can be from an older version, or have
# changed since
.PHONY: css
css: $(TAILWIND) $(DAISYUI) $(DAISYUI_THEME)
	@printf '%s  %s\n' $(TAILWIND_SHA256) $(TAILWIND) $(DAISYUI_SHA256) $(DAISYUI) \
		$(DAISYUI_THEME_SHA256) $(DAISYUI_THEME) | $(SHA256SUM) -c \
		|| { echo "Delete $(CSS_VENDOR)/ to download them again"; exit 1; }
	$(TAILWIND) -i css/app.css -o src/composeui/webcore/static/app.css --minify

# the web page's scripts from npm, through unpkg, and uPlot's stylesheet, which app.css
# imports: committed, so the package needs no download. Change a version and its SHA-256,
# run `make web-deps css`, and commit the files.
STATIC := src/composeui/webcore/static
HTMX_VERSION := 2.0.10
UPLOT_VERSION := 1.6.32
CALLY_VERSION := 0.9.2
DECKGL_VERSION := 9.2.6
DECKGL_SHA256 := 234e0af97a691b8e5aea6c6ca9e703a7ba5206fd1f53daa9f670e41db089de2d
DECKGL_LICENSE_SHA256 := e499a2c2ba3b9faabe91fdfddf43e329439263264b7148e5548d0ec605cce9f2
HTMX_SHA256 := 71ea67185bfa8c98c39d31717c6fce5d852370fcdfd129db4543774d3145c0de
UPLOT_SHA256 := 19c8d4c6ad88929a79f4ae49d6f7161566dfd0ba3d15cc495e974f787eb78f1f
UPLOT_CSS_SHA256 := df630c6a8d6f8eeaff264b50f73ce5b114f646ffd9a0bb74f049b0a00135fa04
CALLY_SHA256 := 4dcba6a3b8ec63b66ff2fbfc6cf47b7dee1eb4896eac89fe7487d82e28e15870
CALLY_LICENSE_SHA256 := c48fd407090d6d752b0370d39db55bd750e6dfc678ee252d4c906bddf54132eb

# Cally's file has no license comment: it gets Cally's LICENSE as one
.PHONY: web-deps
web-deps:
	$(call fetch,https://unpkg.com/deck.gl@$(DECKGL_VERSION)/dist.min.js,$(STATIC)/deckgl.min.js,$(DECKGL_SHA256))
	$(call fetch,https://unpkg.com/deck.gl@$(DECKGL_VERSION)/LICENSE,$(STATIC)/deckgl.LICENSE,$(DECKGL_LICENSE_SHA256))
	$(call fetch,https://unpkg.com/htmx.org@$(HTMX_VERSION)/dist/htmx.min.js,$(STATIC)/htmx.min.js,$(HTMX_SHA256))
	$(call fetch,https://unpkg.com/uplot@$(UPLOT_VERSION)/dist/uPlot.iife.min.js,$(STATIC)/uPlot.iife.min.js,$(UPLOT_SHA256))
	$(call fetch,https://unpkg.com/uplot@$(UPLOT_VERSION)/dist/uPlot.min.css,css/uPlot.min.css,$(UPLOT_CSS_SHA256))
	$(call fetch,https://unpkg.com/cally@$(CALLY_VERSION)/dist/cally.js,$(STATIC)/cally.dist.js,$(CALLY_SHA256))
	$(call fetch,https://unpkg.com/cally@$(CALLY_VERSION)/LICENSE,$(STATIC)/cally.LICENSE,$(CALLY_LICENSE_SHA256))
	{ echo '/*! https://github.com/WickyNilliams/cally (v$(CALLY_VERSION)), its dependency atomico bundled in'; \
		sed -e 's/^/ * /' -e 's/ *$$//' $(STATIC)/cally.LICENSE; echo ' */'; \
		cat $(STATIC)/cally.dist.js; } > $(STATIC)/cally.js
	rm -f $(STATIC)/cally.dist.js $(STATIC)/cally.LICENSE

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
	rm -rf docs/_build
	rm -rf coverage.xml

.PHONY: all
all: clean check test
