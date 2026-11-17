"""The built documentation includes the stylesheets and scripts that its pages use."""

from __future__ import annotations

from html.parser import HTMLParser
from os import environ
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest


class _PageAssets(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.urls: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        url = None
        if tag == "link" and attributes.get("rel") == "stylesheet":
            url = attributes.get("href")
        elif tag == "script":
            url = attributes.get("src")
        if url and not urlsplit(url).scheme and not urlsplit(url).netloc:
            self.urls.append(url)


@pytest.mark.parametrize("version", ["", "stable"])
def test_each_built_site_includes_its_stylesheets_and_scripts(version: str) -> None:
    site = environ.get("COMPOSEUI_DOCS_SITE")
    if not site:
        pytest.skip("Set COMPOSEUI_DOCS_SITE to the built main and stable documentation.")
    root = Path(__file__).parent.parent / site
    page = root / version / "index.html"
    assets = _PageAssets()
    assets.feed(page.read_text(encoding="utf-8"))

    assert assets.urls
    missing = [
        url for url in assets.urls if not (page.parent / unquote(urlsplit(url).path)).is_file()
    ]
    assert not missing, f"{page}: missing stylesheets or scripts: {missing}"
