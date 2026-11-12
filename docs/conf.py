"""Sphinx configuration of the ComposeUI documentation (`make docs`)."""

from __future__ import annotations

import posixpath
import re
import shutil
import subprocess
import sys
from importlib.metadata import version as package_version
from os import environ
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sphinx.application import Sphinx

# the local extension that writes the widget catalog
sys.path.insert(0, str(Path(__file__).parent / "_ext"))

project = "ComposeUI"
author = "El Hadi Moussi"
project_copyright = f"%Y, {author}"
release = package_version("composeui")
version = release

extensions = [
    "myst_parser",
    "sphinx.ext.autodoc",
    "sphinx.ext.intersphinx",
    "sphinx.ext.viewcode",
    "sphinx_sitemap",
    "widgetcatalog",
]

source_suffix = {".md": "markdown"}
exclude_patterns = ["_build", "_site"]

# the guides link to their sections as `#core-concepts`, as GitHub does
myst_heading_anchors = 3

# docstrings name code in single backticks: make each a cross-reference
default_role = "py:obj"
autodoc_default_options = {
    "members": True,
    "undoc-members": True,
    "show-inheritance": True,
    "member-order": "bysource",
}
autodoc_typehints = "description"
autodoc_class_signature = "separated"

intersphinx_mapping = {"python": ("https://docs.python.org/3", None)}

html_theme = "furo"
_DOCS_REF = environ.get("COMPOSEUI_DOCS_REF", "main")
_LATEST_TAG = environ.get("COMPOSEUI_DOCS_LATEST_TAG", "")
if not _LATEST_TAG and (git := shutil.which("git")):
    # Fixed arguments only; use local tags so a normal `make docs` shows both choices.
    tags = subprocess.run(  # noqa: S603 - the executable is resolved and arguments are fixed
        [git, "tag", "--list", "v[0-9]*", "--sort=-version:refname"],
        cwd=Path(__file__).parent,
        capture_output=True,
        text=True,
        check=False,
    ).stdout.splitlines()
    _LATEST_TAG = tags[0] if tags else ""
_SITE_ROOT = "https://ehmoussi.github.io/composeui/"
html_baseurl = _SITE_ROOT + ("stable/" if _DOCS_REF != "main" else "")
sitemap_url_scheme = "{link}"
html_title = f"ComposeUI: Python UIs for desktop, terminal, and web ({_DOCS_REF})"
html_static_path = ["_static"]
templates_path = ["_templates"]
html_css_files = ["versions.css", "github.css"]
html_js_files = ["versions.js"]
html_sidebars = {
    "**": [
        "sidebar/brand.html",
        "sidebar/github.html",
        "sidebar/versions.html",
        "sidebar/search.html",
        "sidebar/scroll-start.html",
        "sidebar/navigation.html",
        "sidebar/ethical-ads.html",
        "sidebar/scroll-end.html",
        "sidebar/variant-selector.html",
    ],
}
html_context = {
    "docs_ref": _DOCS_REF,
    "docs_latest_tag": _LATEST_TAG,
    "docs_site_root": _SITE_ROOT,
}
# _site/ is copied as is to the root of the site: llms.txt for language models
# (https://llmstxt.org), and the skill for coding agents (skills/composeui/SKILL.md)
html_extra_path = ["_site"]
# the default icon of the apps (`MainView.app_icon`)
html_favicon = "../src/composeui/images/composeui.svg"
# the logos already hold the name, so the sidebar doesn't repeat it under them
html_theme_options = {
    "light_logo": "composeui-logo-light.svg",
    "dark_logo": "composeui-logo-dark.svg",
    "sidebar_hide_name": True,
}

# the guides link to the repository's files (`../src/examples/pipeform.py`), which the site
# does not hold: those links go to the files on GitHub
REPOSITORY_URL = f"https://github.com/ehmoussi/composeui/blob/{_DOCS_REF}/"
_RELATIVE_LINK = re.compile(r"\]\((\.\./[^)\s]*)\)")


def _link_repository_files(_app: Sphinx, docname: str, source: list[str]) -> None:
    def replace(match: re.Match[str]) -> str:
        path = posixpath.normpath(posixpath.join("docs", posixpath.dirname(docname), match[1]))
        if path.startswith("docs/"):
            return match[0]
        return f"]({REPOSITORY_URL}{path})"

    source[0] = _RELATIVE_LINK.sub(replace, source[0])


# proves to Google Search Console that the site is ours: it reads the home page
_GOOGLE_SITE_VERIFICATION = (
    '<meta name="google-site-verification" content="0MoGkjpMyCBgk-B3bGTadusOhKy6XVJNqYBvi3MVI9k" />'
)


def _add_site_verification(
    _app: Sphinx, pagename: str, _template: str, context: dict[str, Any], _doctree: object
) -> None:
    if pagename == "index":
        context["metatags"] = context.get("metatags", "") + _GOOGLE_SITE_VERIFICATION + "\n"


def setup(app: Sphinx) -> None:
    app.connect("source-read", _link_repository_files)
    app.connect("html-page-context", _add_site_verification)
