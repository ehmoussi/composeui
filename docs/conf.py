"""Sphinx configuration of the ComposeUI documentation (`make docs`)."""

from __future__ import annotations

import posixpath
import re
import sys
from importlib.metadata import version as package_version
from pathlib import Path
from typing import TYPE_CHECKING

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
    "widgetcatalog",
]

source_suffix = {".md": "markdown"}
exclude_patterns = ["_build"]

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
html_title = f"ComposeUI {release}"

# the guides link to the repository's files (`../src/examples/pipeform.py`), which the site
# does not hold: those links go to the files on GitHub
REPOSITORY_URL = "https://github.com/ehmoussi/composeui3/blob/main/"
_RELATIVE_LINK = re.compile(r"\]\((\.\./[^)\s]*)\)")


def _link_repository_files(_app: Sphinx, docname: str, source: list[str]) -> None:
    def replace(match: re.Match[str]) -> str:
        path = posixpath.normpath(posixpath.join("docs", posixpath.dirname(docname), match[1]))
        if path.startswith("docs/"):
            return match[0]
        return f"]({REPOSITORY_URL}{path})"

    source[0] = _RELATIVE_LINK.sub(replace, source[0])


def setup(app: Sphinx) -> None:
    app.connect("source-read", _link_repository_files)
