"""Pipes shown as an expander each, shared by the core and backend tests of `ListView`."""

from __future__ import annotations

import functools
from typing import TYPE_CHECKING

import attrs

from composeui.core.translation import T
from composeui.core.view import (
    ButtonVariant,
    ButtonView,
    ExpanderView,
    LabelView,
    ListView,
    MainView,
    View,
    child,
    define_view,
)

if TYPE_CHECKING:
    from collections.abc import Hashable


@attrs.frozen
class Pipe:
    name: str
    length: float


@define_view
class PipeExpander(ExpanderView):
    length: LabelView = child(LabelView)
    delete: ButtonView = child(ButtonView, text=T("Delete"), variant=ButtonVariant.DANGER)


@define_view
class PipeList(ListView[Pipe]):
    def build_item(self, item: Pipe) -> View:
        view = PipeExpander(title=item.name)
        self.update_item(view, item)
        view.delete.clicked.connect(functools.partial(self._delete, item.name))
        return view

    def item_key(self, item: Pipe) -> Hashable:
        return item.name

    def update_item(self, view: View, item: Pipe) -> bool:
        assert isinstance(view, PipeExpander)
        view.length.text = f"Length: {item.length:g} m"
        return True

    def _delete(self, name: str, main_view: PipesMainView) -> None:
        """Remove the pipe `name`; the main view tells it, as the record's own view is gone."""
        self.items = [pipe for pipe in self.items if pipe.name != name]
        main_view.status_bar.show_message(f"Deleted {name}")


@define_view
class PipesMainView(MainView):
    app_title = "Pipes"
    extension = ".pipes"

    add: ButtonView = child(ButtonView, text="Add a pipe")
    pipes: PipeList = attrs.Factory(PipeList)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.add.clicked.connect(self._add)

    def _add(self) -> None:
        """Add a pipe first, ahead of the others."""
        self.pipes.items = [Pipe("Feed", 1), *self.pipes.items]


#: two pipes to start with
PIPES = [Pipe("Main line", 12), Pipe("Return", 3)]
