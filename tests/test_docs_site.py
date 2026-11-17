"""The built documentation includes its assets and lists only indexable pages in its sitemaps."""

from __future__ import annotations

from html.parser import HTMLParser
from os import environ
from pathlib import Path
from urllib.parse import unquote, urlsplit
from xml.etree import ElementTree as ET

import pytest

pytestmark = pytest.mark.skipif(
    not environ.get("COMPOSEUI_DOCS_SITE"),
    reason="Set COMPOSEUI_DOCS_SITE to the built main and stable documentation.",
)


class _PageMetadata(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.urls: list[str] = []
        self.noindex = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        url = None
        if tag == "link" and attributes.get("rel") == "stylesheet":
            url = attributes.get("href")
        elif tag == "script":
            url = attributes.get("src")
        if url and not urlsplit(url).scheme and not urlsplit(url).netloc:
            self.urls.append(url)
        if tag == "meta" and (attributes.get("name") or "").lower() in {"robots", "googlebot"}:
            self.noindex |= "noindex" in (attributes.get("content") or "").lower()


@pytest.fixture
def site_root() -> Path:
    return Path(__file__).parent.parent / environ["COMPOSEUI_DOCS_SITE"]


@pytest.mark.parametrize("version", ["", "stable"])
def test_each_built_site_includes_its_stylesheets_and_scripts(
    site_root: Path, version: str
) -> None:
    page = site_root / version / "index.html"
    assets = _PageMetadata()
    assets.feed(page.read_text(encoding="utf-8"))

    assert assets.urls
    missing = [
        url for url in assets.urls if not (page.parent / unquote(urlsplit(url).path)).is_file()
    ]
    assert not missing, f"{page}: missing stylesheets or scripts: {missing}"


@pytest.mark.parametrize("version", ["", "stable"])
def test_each_sitemap_omits_pages_that_refuse_indexing(site_root: Path, version: str) -> None:
    sitemap = ET.parse(site_root / version / "sitemap.xml")  # noqa: S314 - local build
    locations = [
        element.text
        for element in sitemap.findall(
            "{http://www.sitemaps.org/schemas/sitemap/0.9}url/"
            "{http://www.sitemaps.org/schemas/sitemap/0.9}loc"
        )
    ]
    site_url = "https://ehmoussi.github.io/composeui/"
    version_url = site_url + (f"{version}/" if version else "")
    assert version_url + "index.html" in locations
    noindex = []
    for location in locations:
        assert location is not None
        assert location.startswith(version_url)
        page = site_root / unquote(location.removeprefix(site_url))
        metadata = _PageMetadata()
        metadata.feed(page.read_text(encoding="utf-8"))
        if metadata.noindex:
            noindex.append(location)
    assert not noindex, f"Sitemap lists pages that refuse indexing: {noindex}"
