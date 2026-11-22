"""The look of the web app: its colors, shapes and font, and stylesheets of its own.

Pass a `WebStyle` to `composeui.core.application.run` as ``web_style``. The other backends
ignore it. Each value is checked as it is set: a color that doesn't parse, or a text color
that a reader can't tell from its background, raises `ValueError`.
"""

from __future__ import annotations

import math
import re
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Optional

import attrs

if TYPE_CHECKING:
    from collections.abc import Iterable

__all__ = ["Palette", "Theme", "WebStyle"]


#: ``#rrggbb``, or ``oklch(L C H)`` with L as a percentage or a number from 0 to 1
_HEX = re.compile(r"#[0-9a-fA-F]{6}")
_OKLCH = re.compile(
    r"oklch\(\s*(?P<l>\d+(?:\.\d+)?)(?P<percent>%?)\s+(?P<c>\d+(?:\.\d+)?)"
    r"\s+(?P<h>-?\d+(?:\.\d+)?)(?:deg)?\s*\)"
)
_COLOR = re.compile(f"{_HEX.pattern}|{_OKLCH.pattern}")
#: a length of CSS, e.g. ``0.5rem`` or ``2px``: nothing else reaches the stylesheet
_LENGTH = re.compile(r"(?:0|\d+(?:\.\d+)?(?:rem|em|px))")
#: font names, each quoted or a name of words, separated by commas: an unclosed quote or a
#: character that ends a CSS rule would drop the font, or write another rule
_FONT_NAME = r"""\s*(?:"[\w '.-]+"|'[\w ".-]+'|[\w-]+(?: [\w-]+)*)\s*"""
_FONT = re.compile(f"{_FONT_NAME}(?:,{_FONT_NAME})*")
#: WCAG's least contrast for a text of normal size (level AA)
MIN_CONTRAST = 4.5


#: where sRGB's gamma curve starts
_SRGB_KNEE = 0.04045


def _linear(channel: float) -> float:
    """Get an sRGB channel (0 to 1) without its gamma."""
    return channel / 12.92 if channel <= _SRGB_KNEE else ((channel + 0.055) / 1.055) ** 2.4


def _linear_rgb(color: str) -> tuple[float, float, float]:
    """Get the linear sRGB channels of a color that `Palette` accepts."""
    if _HEX.fullmatch(color):
        red, green, blue = (int(color[i : i + 2], 16) / 255 for i in (1, 3, 5))
        return _linear(red), _linear(green), _linear(blue)
    match = _OKLCH.fullmatch(color)
    assert match is not None  # checked as it was set
    lightness = float(match["l"]) / (100 if match["percent"] else 1)
    chroma = float(match["c"])
    hue = math.radians(float(match["h"]))
    a, b = chroma * math.cos(hue), chroma * math.sin(hue)
    # OKLab to linear sRGB (Björn Ottosson's matrices); out of the gamut, clipped
    long = (lightness + 0.3963377774 * a + 0.2158037573 * b) ** 3
    medium = (lightness - 0.1055613458 * a - 0.0638541728 * b) ** 3
    short = (lightness - 0.0894841775 * a - 1.2914855480 * b) ** 3
    rgb = (
        4.0767416621 * long - 3.3077115913 * medium + 0.2309699292 * short,
        -1.2684380046 * long + 2.6097574011 * medium - 0.3413193965 * short,
        -0.0041960863 * long - 0.7034186147 * medium + 1.7076147010 * short,
    )
    red, green, blue = (min(max(channel, 0.0), 1.0) for channel in rgb)
    return red, green, blue


def contrast(color: str, other: str) -> float:
    """Get WCAG's contrast ratio of two colors, from 1 (the same) to 21 (black on white)."""
    red, green, blue = _linear_rgb(color)
    red2, green2, blue2 = _linear_rgb(other)
    luminance = 0.2126 * red + 0.7152 * green + 0.0722 * blue
    luminance2 = 0.2126 * red2 + 0.7152 * green2 + 0.0722 * blue2
    return (max(luminance, luminance2) + 0.05) / (min(luminance, luminance2) + 0.05)


def _check(name: str, value: object, pattern: re.Pattern[str], kind: str) -> None:
    if value is not None and not (isinstance(value, str) and pattern.fullmatch(value)):
        msg = f"{name} must be {kind}, not {value!r}"
        raise ValueError(msg)


@attrs.frozen(kw_only=True)
class Palette:
    """The colors of a theme, light or dark, each ``#rrggbb`` or ``oklch(L C H)``.

    A color left out keeps ComposeUI's. A ``*_content`` color is the text on its color,
    e.g. a primary button's text on `primary`; `base_content` is the text on the page.
    """

    #: The background of the boxes, such as the page's card and the fields.
    base_100: Optional[str] = None
    #: The background of the page, and of a group of rows.
    base_200: Optional[str] = None
    #: The borders.
    base_300: Optional[str] = None
    base_content: Optional[str] = None
    #: Main buttons, current tab, links.
    primary: Optional[str] = None
    primary_content: Optional[str] = None
    secondary: Optional[str] = None
    secondary_content: Optional[str] = None
    accent: Optional[str] = None
    accent_content: Optional[str] = None
    neutral: Optional[str] = None
    neutral_content: Optional[str] = None
    info: Optional[str] = None
    info_content: Optional[str] = None
    success: Optional[str] = None
    success_content: Optional[str] = None
    warning: Optional[str] = None
    warning_content: Optional[str] = None
    #: Danger buttons, invalid fields, error messages.
    error: Optional[str] = None
    error_content: Optional[str] = None

    def __attrs_post_init__(self) -> None:
        for field in attrs.fields(Palette):
            _check(field.name, getattr(self, field.name), _COLOR, "'#rrggbb' or 'oklch(L C H)'")

    def colors(self) -> dict[str, str]:
        """Get the colors set, by field name."""
        return {
            field.name: value
            for field in attrs.fields(Palette)
            if (value := getattr(self, field.name)) is not None
        }


#: ComposeUI's colors, as `css/app.css` sets them (a test checks the copy)
DEFAULT_LIGHT: dict[str, str] = {
    "base_100": "oklch(100% 0 0)",
    "base_200": "oklch(97.4% 0.006 264)",
    "base_300": "oklch(91.5% 0.012 264)",
    "base_content": "oklch(27% 0.03 264)",
    "primary": "oklch(52% 0.2 268)",
    "primary_content": "oklch(98% 0.01 268)",
    "secondary": "oklch(60% 0.15 300)",
    "secondary_content": "oklch(98% 0.01 300)",
    "accent": "oklch(70% 0.13 185)",
    "accent_content": "oklch(25% 0.05 185)",
    "neutral": "oklch(32% 0.03 264)",
    "neutral_content": "oklch(96% 0.01 264)",
    "info": "oklch(58% 0.15 240)",
    "info_content": "oklch(98% 0.01 240)",
    "success": "oklch(62% 0.15 155)",
    "success_content": "oklch(98% 0.01 155)",
    "warning": "oklch(68% 0.16 65)",
    "warning_content": "oklch(25% 0.06 65)",
    "error": "oklch(58% 0.21 22)",
    "error_content": "oklch(98% 0.01 22)",
}
DEFAULT_DARK: dict[str, str] = {
    "base_100": "oklch(23.5% 0.018 264)",
    "base_200": "oklch(19.5% 0.016 264)",
    "base_300": "oklch(32% 0.022 264)",
    "base_content": "oklch(93% 0.012 264)",
    "primary": "oklch(70% 0.15 268)",
    "primary_content": "oklch(20% 0.05 268)",
    "secondary": "oklch(72% 0.13 300)",
    "secondary_content": "oklch(20% 0.05 300)",
    "accent": "oklch(76% 0.12 185)",
    "accent_content": "oklch(22% 0.04 185)",
    "neutral": "oklch(30% 0.02 264)",
    "neutral_content": "oklch(93% 0.012 264)",
    "info": "oklch(72% 0.13 240)",
    "info_content": "oklch(20% 0.05 240)",
    "success": "oklch(74% 0.14 155)",
    "success_content": "oklch(20% 0.05 155)",
    "warning": "oklch(80% 0.14 75)",
    "warning_content": "oklch(22% 0.05 75)",
    "error": "oklch(70% 0.17 22)",
    "error_content": "oklch(20% 0.05 22)",
}
#: the text and its background that a reader must tell apart
_PAIRS = (
    ("base_content", "base_100"),
    ("base_content", "base_200"),
    ("base_content", "base_300"),
    *(
        (f"{name}_content", name)
        for name in (
            "primary",
            "secondary",
            "accent",
            "neutral",
            "info",
            "success",
            "warning",
            "error",
        )
    ),
)


def _check_contrast(palette: Palette, defaults: dict[str, str], name: str) -> None:
    set_colors = palette.colors()
    colors = {**defaults, **set_colors}
    for text, background in _PAIRS:
        if text not in set_colors and background not in set_colors:
            continue  # ComposeUI's own pair, not the app's to answer for
        ratio = contrast(colors[text], colors[background])
        if ratio < MIN_CONTRAST:
            msg = (
                f"{name}.{text} on {name}.{background} has a contrast of {ratio:.2f}:1, "
                f"less than {MIN_CONTRAST}:1: its text would be hard to read"
            )
            raise ValueError(msg)


@attrs.frozen(kw_only=True)
class Theme:
    """The colors of the web app, light and dark, its shapes and its font.

    The header's Theme menu still picks light, dark, or the browser's preference. A value
    left out keeps ComposeUI's. Where a palette sets a text color or its background, the
    two must keep a contrast of 4.5:1 (WCAG AA), ComposeUI's color standing in for the one
    left out.
    """

    light: Palette = attrs.field(factory=Palette)
    dark: Palette = attrs.field(factory=Palette)
    #: The corners of the fields and buttons, e.g. ``"0"`` for square ones.
    radius_field: Optional[str] = None
    #: The corners of the boxes: the page's card, groups, dialogs, menus.
    radius_box: Optional[str] = None
    #: The corners of the small controls: checkboxes, toggles, badges.
    radius_selector: Optional[str] = None
    #: The width of the borders, e.g. ``"1px"``.
    border: Optional[str] = None
    #: The text's font, e.g. ``'"Inter", sans-serif'``: a font the browser has, or one that
    #: a stylesheet of the `WebStyle` declares with ``@font-face``.
    font: Optional[str] = None

    def __attrs_post_init__(self) -> None:
        length = "a length in rem, em or px, e.g. '0.5rem'"
        for name in ("radius_field", "radius_box", "radius_selector", "border"):
            _check(name, getattr(self, name), _LENGTH, length)
        _check("font", self.font, _FONT, "font names separated by commas")
        _check_contrast(self.light, DEFAULT_LIGHT, "light")
        _check_contrast(self.dark, DEFAULT_DARK, "dark")

    def is_default(self) -> bool:
        """Tell whether the theme changes nothing of ComposeUI's."""
        return self == Theme()


def _names(names: Iterable[str]) -> tuple[str, ...]:
    return tuple(names)


def _check_stylesheets(instance: WebStyle, _attribute: object, value: tuple[str, ...]) -> None:
    if value and instance.folder is None:
        msg = "stylesheets are files of the folder: pass folder too"
        raise ValueError(msg)
    for name in value:
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts or "\\" in name or path.suffix != ".css":
            msg = f"a stylesheet is a .css file of the folder, by its relative path: {name!r}"
            raise ValueError(msg)


@attrs.frozen(kw_only=True)
class WebStyle:
    """The look of the web app: its `theme`, then `stylesheets` of its own.

    The web server serves `folder` at ``/style/files/``: the stylesheets, and the fonts
    and images they name by a relative ``url(...)``. Its hidden files, and any file
    outside it, are not served. The stylesheets load after ComposeUI's, in their order, so
    their rules win over its. They select the parts of the page by their ``data-cui``
    attribute, such as ``[data-cui="header"]``: ComposeUI's classes are not part of the API.
    The server checks them as it starts. A missing file, an ``@import``, or a ``url(...)`` that
    names an address or a file the folder doesn't serve stops it: the page's policy would block
    them.
    """

    theme: Theme = attrs.field(factory=Theme)
    folder: Optional[Path] = attrs.field(default=None, converter=attrs.converters.optional(Path))
    stylesheets: tuple[str, ...] = attrs.field(
        default=(), converter=_names, validator=_check_stylesheets
    )
