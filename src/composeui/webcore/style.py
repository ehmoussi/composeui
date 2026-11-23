"""The app's `WebStyle` on the page: its theme as a stylesheet, and the files of its folder."""

from __future__ import annotations

import hashlib
import posixpath
import re
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Final
from urllib.parse import quote, unquote

from markupsafe import Markup
from starlette.responses import FileResponse, PlainTextResponse, Response

if TYPE_CHECKING:
    from starlette.requests import Request

    from composeui.core.webstyle import Palette, Theme, WebStyle

#: the files of the app's folder that the page may load: stylesheets, fonts, images
_SERVED_SUFFIXES: Final = frozenset(
    {".css", ".woff2", ".woff", ".ttf", ".otf", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}
)
#: a file of the folder may change while the server runs: the browser asks again each time;
#: an SVG opened on its own runs no script
_FILE_HEADERS: Final = {
    "Cache-Control": "no-cache",
    "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'",
    "X-Content-Type-Options": "nosniff",
}
#: the theme's address names its content
_THEME_HEADERS: Final = {**_FILE_HEADERS, "Cache-Control": "public, max-age=31536000, immutable"}
_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_IMPORT = re.compile(r"@import\b", re.IGNORECASE)
_URL = re.compile(r"""url\(\s*(?P<quote>['"]?)(?P<url>.*?)(?P=quote)\s*\)""", re.IGNORECASE)
_SCHEME = re.compile(r"[a-zA-Z][a-zA-Z0-9+.-]*:")


def _variables(palette: Palette, theme: Theme) -> str:
    """Get the CSS variables of `palette` and of `theme`'s shapes, as daisyUI names them."""
    variables = {
        f"--color-{name.replace('_', '-')}": color for name, color in palette.colors().items()
    }
    for name in ("radius_field", "radius_box", "radius_selector", "border"):
        value = getattr(theme, name)
        if value is not None:
            variables[f"--{name.replace('_', '-')}"] = value
    return "".join(f"{name}:{value};" for name, value in variables.items())


def theme_css(theme: Theme) -> str:
    """Get the stylesheet that sets `theme` over ComposeUI's, loaded after it.

    The same selectors as ComposeUI's themes in `css/app.css`, so the Theme menu, the
    browser's preference and a chart's image (`charts.js`) pick these colors too.
    """
    light = _variables(theme.light, theme)
    dark = _variables(theme.dark, theme)
    font = "" if theme.font is None else f":root{{--font-sans:{theme.font};}}\n"
    return (
        f":where(:root),[data-theme=composeui]{{{light}}}\n"
        f"@media (prefers-color-scheme:dark){{:root:not([data-theme]){{{dark}}}}}\n"
        f"[data-theme=composeui-dark]{{{dark}}}\n{font}"
    )


def _digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()[:16]


class StyleFiles:
    """What the page loads of the app's `WebStyle`, checked once, as the server starts.

    A stylesheet edited while the server runs shows at the next page, unchecked until the
    server starts again.
    """

    def __init__(self, style: WebStyle | None) -> None:
        #: the theme's stylesheet; None when it changes nothing
        self.theme: bytes | None = None
        self._folder: Path | None = None
        links: list[Markup] = []
        if style is None:
            self.links = Markup()
            return
        if not style.theme.is_default():
            self.theme = theme_css(style.theme).encode()
            links.append(_link(f"/_composeui/style/theme.css?v={_digest(self.theme)}"))
        if style.folder is not None:
            self._folder = style.folder.resolve()
            if not self._folder.is_dir():
                msg = f"the style's folder {style.folder} isn't a folder"
                raise ValueError(msg)
        for name in style.stylesheets:
            # as the route serves it: not hidden, nor a link out of the folder
            path = self.file(name)
            if path is None:
                msg = f"the stylesheet {name} isn't a file of {style.folder}"
                raise ValueError(msg)
            content = path.read_bytes()
            self._check_urls(name, content.decode("utf-8", errors="replace"))
            # no digest: the route answers `no-cache`, so an edit shows at the next page
            links.append(_link(f"/_composeui/style/files/{quote(name)}"))
        #: the page's `<link>` tags, after ComposeUI's stylesheet
        self.links = Markup("").join(links)

    def _check_urls(self, stylesheet: str, text: str) -> None:
        """Raise `ValueError` for what the page couldn't load of `stylesheet`'s.

        The page's policy blocks other addresses, and the browser drops what it can't
        load without a word: the app would look half styled.
        """
        text = _COMMENT.sub("", text)
        if _IMPORT.search(text):
            msg = f"{stylesheet}: @import is refused, list the stylesheet in WebStyle instead"
            raise ValueError(msg)
        base = posixpath.dirname(stylesheet)
        for match in _URL.finditer(text):
            url = unquote(match["url"].split("#")[0].split("?")[0])
            if url == "":
                continue  # the page's own element, e.g. an SVG filter's `url(#blur)`
            if _SCHEME.match(url) or url.startswith("/"):
                msg = f"{stylesheet}: url({url}) is refused: name a file of the folder, by its path"
                raise ValueError(msg)
            # as the browser resolves it, from the stylesheet's address: out of the folder,
            # it starts with `..`, which `file` refuses
            name = posixpath.normpath(posixpath.join(base, url))
            if self.file(name) is None:
                msg = f"{stylesheet}: url({url}) isn't a file that the folder serves"
                raise ValueError(msg)

    def file(self, name: str) -> Path | None:
        """Get the file of the folder served as `name`; None for any other name."""
        if self._folder is None:
            return None
        parts = PurePosixPath(name).parts
        if any(part.startswith(".") for part in parts) or "\\" in name or "\0" in name:
            return None  # a hidden file, a way out of the folder, or no file's name
        path = (self._folder / name).resolve()
        if (
            not path.is_relative_to(self._folder)
            or path.suffix.lower() not in _SERVED_SUFFIXES
            or not path.is_file()
        ):
            return None
        return path


def _link(url: str) -> Markup:
    return Markup('<link href="{}" rel="stylesheet" type="text/css" />\n').format(url)


def theme(request: Request) -> Response:
    """Serve the stylesheet of the app's theme."""
    files: StyleFiles = request.app.state.style_files
    if files.theme is None:
        return PlainTextResponse("Not Found", status_code=404)
    return Response(files.theme, media_type="text/css", headers=_THEME_HEADERS)


def style_file(request: Request) -> Response:
    """Serve a file of the app's style folder; any other name is not found."""
    files: StyleFiles = request.app.state.style_files
    path = files.file(request.path_params["name"])
    if path is None:
        return PlainTextResponse("Not Found", status_code=404)
    return FileResponse(path, headers=_FILE_HEADERS)
