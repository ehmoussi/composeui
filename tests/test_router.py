"""Tests for pages and their router, in core: navigation and saved state."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from attrs import Factory

from composeui.core.view import CONVERTER, PageView, Router, define_view
from tests.pages import InputsPage, PagesMainView, PagesRouter

if TYPE_CHECKING:
    from pathlib import Path


def _checked_routes(router: Router) -> list[str]:
    return [page.route for page in router.pages if page.action.is_checked]


def test_triggering_a_page_action_shows_its_page() -> None:
    router = PagesRouter()
    shown: list[str] = []
    router.route_changed.connect(shown.append)
    assert router.current_route == "inputs"
    assert _checked_routes(router) == ["inputs"]

    router.results.action.triggered.emit()
    assert router.current_route == "results"
    assert router.current_page is router.results
    assert _checked_routes(router) == ["results"]
    # the shown page's action again: still shown and checked, and not a change
    router.results.action.triggered.emit()
    assert _checked_routes(router) == ["results"]
    assert shown == ["results"]


def test_navigating_to_an_unknown_route_is_rejected() -> None:
    router = PagesRouter()
    with pytest.raises(ValueError, match="'settings'"):
        router.navigate("settings")
    assert router.current_route == "inputs"


@define_view
class _UnroutedPage(PageView):
    pass


@define_view
class _UnroutedRouter(Router):
    unrouted: _UnroutedPage = Factory(_UnroutedPage)


@define_view
class _SlashedPage(PageView):
    route = "a/b"


@define_view
class _SlashedRouter(Router):
    slashed: _SlashedPage = Factory(_SlashedPage)


@define_view
class _TwiceRouter(Router):
    first: InputsPage = Factory(InputsPage)
    second: InputsPage = Factory(InputsPage)


@pytest.mark.parametrize(
    ("router_type", "message"),
    [
        (_UnroutedRouter, "route is ''"),
        (_SlashedRouter, "route is 'a/b'"),
        (_TwiceRouter, "Two pages"),
    ],
)
def test_a_router_rejects_a_missing_invalid_or_repeated_route(
    router_type: type[Router], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        router_type()


def test_the_shown_page_is_never_saved_loaded_or_reset(tmp_path: Path) -> None:
    main_view = PagesMainView()
    main_view.router.inputs.name.text = "pipe"
    main_view.router.navigate("results")
    filepath = tmp_path / "study.pages"
    main_view.save_state(filepath)
    assert "current_route" not in filepath.read_text()

    main_view.reset_state()
    assert main_view.router.inputs.name.text == ""
    assert main_view.router.current_route == "results"
    assert _checked_routes(main_view.router) == ["results"]

    other = PagesMainView()
    other.load_state(filepath)
    assert other.router.inputs.name.text == "pipe"
    assert other.router.current_route == "inputs"
    assert _checked_routes(other.router) == ["inputs"]
    assert "action" not in CONVERTER.unstructure(other)["router"]["inputs"]
