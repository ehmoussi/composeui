"""Tests of `WebStyle`'s checks: what an app's theme may write into the page's stylesheet."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest

from composeui.core.webstyle import DEFAULT_DARK, DEFAULT_LIGHT, Palette, Theme, WebStyle, contrast

_APP_CSS = Path(__file__).parents[1] / "css" / "app.css"


@pytest.mark.parametrize(
    ("build", "field"),
    [
        (lambda: Palette(primary="red"), "primary"),
        (lambda: Palette(primary="#fff"), "primary"),
        (lambda: Palette(primary="#12345g"), "primary"),
        (lambda: Palette(base_100="oklch(50% 0.1)"), "base_100"),
        # what would end the rule, and write another into the page
        (lambda: Palette(primary="#123456;}body{display:none"), "primary"),
        (lambda: Theme(radius_box="1rem;}body{display:none"), "radius_box"),
        (lambda: Theme(border="thin"), "border"),
        (lambda: Theme(font="Inter;}body{display:none"), "font"),
        # an unclosed quote: the browser would drop the font without a word
        (lambda: Theme(font='"Inter, sans-serif'), "font"),
        (lambda: Theme(font="Inter,, sans-serif"), "font"),
    ],
)
def test_a_value_that_isn_t_a_color_a_length_or_a_font_is_refused(build: Any, field: str) -> None:
    with pytest.raises(ValueError, match=f"^{field} must be"):
        build()


@pytest.mark.parametrize(
    ("foreground", "background", "expected"),
    [
        # WebAIM's contrast checker gives these
        ("#000000", "#ffffff", 21.0),
        ("#767676", "#ffffff", 4.54),
        ("#777777", "#ffffff", 4.48),
        ("#0000ff", "#ffffff", 8.59),
        ("#ff0000", "#ffffff", 4.0),
        # the same colors in OKLCH (CSS Color 4's conversion)
        ("oklch(0% 0 0)", "oklch(100% 0 0)", 21.0),
        ("oklch(45.2% 0.313 264.05)", "#ffffff", 8.59),
        ("oklch(62.8% 0.2577 29.23)", "#ffffff", 4.0),
    ],
)
def test_the_contrast_of_two_colors_is_wcag_s(
    foreground: str, background: str, expected: float
) -> None:
    assert contrast(foreground, background) == pytest.approx(expected, abs=0.01)
    assert contrast(background, foreground) == pytest.approx(expected, abs=0.01)


@pytest.mark.parametrize(
    ("theme", "message"),
    [
        (
            lambda: Theme(light=Palette(primary="#777777", primary_content="#888888")),
            "light.primary_content on light.primary has a contrast of 1.26:1",
        ),
        (
            lambda: Theme(dark=Palette(error_content="#ffffff", error="#ff6666")),
            "dark.error_content on dark.error",
        ),
        # judged with ComposeUI's text on it: a dark text on a dark page
        (lambda: Theme(light=Palette(base_100="#222222")), "light.base_content on light.base_100"),
        (lambda: Theme(dark=Palette(base_content="#333333")), "dark.base_content on dark.base_100"),
    ],
)
def test_a_text_color_too_close_to_its_background_is_refused(theme: Any, message: str) -> None:
    with pytest.raises(ValueError, match=re.escape(message)):
        theme()


def test_composeui_s_own_pairs_are_not_judged() -> None:
    # ComposeUI's own success button is below 4.5:1: not the app's to answer for
    assert contrast(DEFAULT_LIGHT["success_content"], DEFAULT_LIGHT["success"]) < 4.5

    Theme(light=Palette(primary="#0b5cad", primary_content="#ffffff"))  # no ValueError


def _theme_colors(name: str) -> dict[str, str]:
    """Get the colors of ComposeUI's theme `name` from the stylesheet's source."""
    block = re.search(
        r'@plugin "[^"]+daisyui-theme.mjs" \{\s*name: "' + name + r'";(.*?)\}',
        _APP_CSS.read_text(encoding="utf-8"),
        re.DOTALL,
    )
    assert block is not None
    return {
        variable.replace("-", "_"): value
        for variable, value in re.findall(r"--color-([a-z0-9-]+): ([^;]+);", block[1])
    }


def test_the_colors_judged_in_place_of_composeui_s_are_its_stylesheet_s() -> None:
    assert _theme_colors("composeui") == DEFAULT_LIGHT
    assert _theme_colors("composeui-dark") == DEFAULT_DARK


@pytest.mark.parametrize(
    ("stylesheets", "folder", "message"),
    [
        (("studio.css",), None, "pass folder too"),
        (("../studio.css",), "style", "by its relative path"),
        (("/srv/studio.css",), "style", "by its relative path"),
        (("css\\studio.css",), "style", "by its relative path"),
        (("studio.txt",), "style", "by its relative path"),
    ],
)
def test_a_stylesheet_out_of_the_folder_is_refused(
    stylesheets: tuple[str, ...], folder: str | None, message: str
) -> None:
    with pytest.raises(ValueError, match=re.escape(message)):
        WebStyle(folder=folder, stylesheets=stylesheets)
