"""The site's `llms.txt` has an entry for each page of the documentation."""

from __future__ import annotations

import re
from pathlib import Path

DOCS = Path(__file__).parent.parent / "docs"
SITE_URL = "https://ehmoussi.github.io/composeui3/"
LINK = re.compile(r"\]\((" + re.escape(SITE_URL) + r"[^)\s]*)\)")


def _linked_pages() -> set[str]:
    text = (DOCS / "_site" / "llms.txt").read_text(encoding="utf-8")
    return {link.removeprefix(SITE_URL).removesuffix(".html") for link in LINK.findall(text)}


def test_each_link_is_a_page() -> None:
    missing = [
        page
        for page in _linked_pages()
        if not (
            (DOCS / "_site" / page) if page.endswith(".md") else (DOCS / f"{page}.md")
        ).is_file()
    ]
    assert not missing


def test_each_page_has_an_entry() -> None:
    # the API reference is one entry (api/index): its module pages are listed in its line
    pages = {
        path.relative_to(DOCS).with_suffix("").as_posix()
        for path in DOCS.rglob("*.md")
        if path.relative_to(DOCS).parts[0] not in {"_build", "_site", "api"}
    }
    pages.add("api/index")
    assert not pages - _linked_pages()
