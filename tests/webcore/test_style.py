"""Tests of an app's `WebStyle` on the page: its theme, its stylesheets and their folder."""

from __future__ import annotations

import os
import re
import sys
from urllib.parse import quote

import pytest

pytest.importorskip("starlette")
# Starlette's test client: httpx2, which needs Python 3.11, or httpx before it
pytest.importorskip("httpx2" if sys.version_info >= (3, 11) else "httpx")

from typing import TYPE_CHECKING

from composeui.core.registry import RendererType
from composeui.core.webstyle import Palette, Theme, WebStyle
from composeui.webcore._renderers.navigation import WebMainRenderer
from composeui.webcore.webapplication import WebApplication
from examples.webhello import HelloMainView
from tests.pages import PagesMainView
from tests.sidebar import SidebarMainView
from tests.webcore.support import _Browser

if TYPE_CHECKING:
    from pathlib import Path

    from composeui.core.view import MainView

_THEME = Theme(
    light=Palette(primary="#0b5cad", primary_content="oklch(0.98 0.01 268deg)"),
    dark=Palette(primary="#6ea8ff", primary_content="#0a1a2f"),
    radius_box="0",
    border="0.0625rem",
    font='"Inter", "Segoe UI", sans-serif',
)


def _links(page: str) -> list[str]:
    return re.findall(r'<link href="([^"]+)" rel="stylesheet"', page)


def _style_folder(tmp_path: Path) -> Path:
    folder = tmp_path / "style"
    (folder / "fonts").mkdir(parents=True)
    (folder / "fonts" / "inter.woff2").write_bytes(b"wOF2 font")
    (folder / "fonts" / "inter bold.woff2").write_bytes(b"wOF2 bold font")
    (folder / "studio.css").write_text(
        '@font-face { font-family: "Inter"; src: url("fonts/inter.woff2") format("woff2"); }\n'
        '[data-cui="header"] { background: var(--color-primary); }\n'
    )
    # a file's name as an address writes it, and its path from a stylesheet in a folder
    (folder / "fonts" / "bold.css").write_text(
        '@font-face { font-family: "Inter"; font-weight: 700; src: url(inter%20bold.woff2); }\n'
        "/* url(missing.woff2), @import: not read */\n"
        '[data-cui="brand"] { background: url("../fonts/inter.woff2#unused"); }\n'
        "[data-cui=chart] { filter: url(#blur); }\n"
    )
    (folder / "dense #1.css").write_text("[data-cui=row] { gap: 0; }\n")
    return folder


def test_the_page_loads_the_theme_then_the_stylesheets_after_composeui_s(tmp_path: Path) -> None:
    folder = _style_folder(tmp_path)
    style = WebStyle(
        theme=_THEME, folder=folder, stylesheets=("studio.css", "fonts/bold.css", "dense #1.css")
    )
    app = WebApplication(build_main_view=HelloMainView, style=style)
    with _Browser(app.create_starlette_app()) as browser:
        links = _links(browser.get("/").text)
        composeui, theme, studio, bold, dense = links
        assert composeui.startswith("/static/app.css?v=")
        responses = [browser.get(link) for link in (theme, studio, bold, dense)]
        fonts = [
            browser.get("/style/files/fonts/inter.woff2"),
            browser.get("/style/files/fonts/inter%20bold.woff2"),
        ]

    assert [response.status_code for response in responses] == [200, 200, 200, 200]
    assert responses[1].content == (folder / "studio.css").read_bytes()
    assert responses[2].content == (folder / "fonts" / "bold.css").read_bytes()
    assert responses[3].content == (folder / "dense #1.css").read_bytes()
    assert [font.content for font in fonts] == [b"wOF2 font", b"wOF2 bold font"]
    # the theme's colors under the selectors of ComposeUI's themes: the Theme menu, the
    # browser's preference and a chart's image pick them
    css = responses[0].text
    light = "--color-primary:#0b5cad;--color-primary-content:oklch(0.98 0.01 268deg);"
    assert f":where(:root),[data-theme=composeui]{{{light}" in css
    assert (
        "@media (prefers-color-scheme:dark){:root:not([data-theme]){--color-primary:#6ea8ff;" in css
    )
    assert "[data-theme=composeui-dark]{--color-primary:#6ea8ff;" in css
    assert css.count("--radius-box:0;--border:0.0625rem;") == 3
    assert ':root{--font-sans:"Inter", "Segoe UI", sans-serif;}' in css


def test_without_a_style_the_page_is_composeui_s(tmp_path: Path) -> None:
    folder = _style_folder(tmp_path)
    for style in (None, WebStyle(), WebStyle(folder=folder)):
        app = WebApplication(build_main_view=HelloMainView, style=style)
        with _Browser(app.create_starlette_app()) as browser:
            assert len(_links(browser.get("/").text)) == 1
            assert browser.get("/style/theme.css").status_code == 404


@pytest.mark.parametrize(
    "name",
    [
        ".secret.css",  # hidden
        # encoded, so that the client sends them as they are
        "%2e%2e/outside.css",
        "fonts%2f..%2f..%2foutside.css",
        "{outside}",  # its absolute path
        "studio%00.css",  # no file's name: a server error if it reached the disk
        "notes.py",  # no stylesheet, font or image
        "missing.css",
        "fonts",  # a folder
        pytest.param(
            "link.css",  # a link out of the folder
            marks=pytest.mark.skipif(os.name == "nt", reason="a link needs rights on Windows"),
        ),
    ],
)
def test_the_folder_serves_none_of_the_files_a_page_needn_t(tmp_path: Path, name: str) -> None:
    folder = _style_folder(tmp_path)
    (folder / ".secret.css").write_text("secret")
    (folder / "notes.py").write_text("secret")
    (tmp_path / "outside.css").write_text("secret")
    if name == "link.css":  # posix only
        (folder / "link.css").symlink_to(tmp_path / "outside.css")
    app = WebApplication(build_main_view=HelloMainView, style=WebStyle(folder=folder))
    outside = quote((tmp_path / "outside.css").as_posix(), safe="")
    with _Browser(app.create_starlette_app()) as browser:
        response = browser.get(f"/style/files/{name.format(outside=outside)}")

    assert response.status_code == 404
    assert "secret" not in response.text


@pytest.mark.parametrize(
    ("css", "message"),
    [
        ('@import "other.css";', "@import is refused"),
        ("@IMPORT url(other.css);", "@import is refused"),
        ("a { background: url(https://cdn.example/x.png); }", "url(https://cdn.example/x.png)"),
        ("a { background: url('//cdn.example/x.png'); }", "url(//cdn.example/x.png)"),
        ('a { background: url("/static/x.png"); }', "url(/static/x.png)"),
        ("a { background: url(data:image/png;base64,AAAA); }", "url(data:image/png;base64,AAAA)"),
        ("a { background: url(../x.png); }", "url(../x.png) isn't a file that the folder"),
        ("a { background: url(missing.png); }", "url(missing.png) isn't a file that the folder"),
        ("a { background: url(.hidden.png); }", "url(.hidden.png) isn't a file that the folder"),
        ("a { background: url(notes.py); }", "url(notes.py) isn't a file that the folder"),
    ],
)
def test_the_server_refuses_to_start_on_what_the_page_s_policy_would_block(
    tmp_path: Path, css: str, message: str
) -> None:
    """The browser would drop them without a word: the app would look half styled."""
    folder = _style_folder(tmp_path)
    (folder / ".hidden.png").write_bytes(b"PNG")
    (folder / "notes.py").write_text("")
    (folder / "studio.css").write_text(css)
    app = WebApplication(
        build_main_view=HelloMainView, style=WebStyle(folder=folder, stylesheets=("studio.css",))
    )

    with pytest.raises(ValueError, match=re.escape(message)):
        app.create_starlette_app()


@pytest.mark.parametrize("name", ["missing.css", ".hidden.css"])
def test_the_server_refuses_to_start_without_a_stylesheet_it_can_serve(
    tmp_path: Path, name: str
) -> None:
    folder = _style_folder(tmp_path)
    (folder / ".hidden.css").write_text("a { color: red; }")
    app = WebApplication(
        build_main_view=HelloMainView, style=WebStyle(folder=folder, stylesheets=(name,))
    )

    with pytest.raises(ValueError, match=f"the stylesheet {re.escape(name)} isn't a file of"):
        app.create_starlette_app()


def test_the_server_refuses_to_start_without_the_folder(tmp_path: Path) -> None:
    app = WebApplication(build_main_view=HelloMainView, style=WebStyle(folder=tmp_path / "no"))

    with pytest.raises(ValueError, match="isn't a folder"):
        app.create_starlette_app()


#: the parts of the page that an app's stylesheet selects, as the user guide lists them
_SHELL_HOOKS = {"header", "brand", "content", "card", "page_tabs", "sidebar", "row"}


def test_the_page_s_parts_carry_their_hooks() -> None:
    hooks: set[str] = set()
    for main_view_type in (PagesMainView, SidebarMainView):
        main_view: MainView = main_view_type()
        main_view.render(RendererType.WEB)
        assert isinstance(main_view.renderer, WebMainRenderer)
        hooks |= set(re.findall(r'data-cui="([a-z_]+)"', main_view.renderer.page_html()))

    assert sorted(_SHELL_HOOKS - hooks) == []
