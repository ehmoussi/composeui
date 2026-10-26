"""Tests of `ListView` in the core: its records' views, wired as the main view's are."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from composeui.core.application import _add_reference_to_signals
from composeui.core.translation import T
from composeui.core.view import LabelView, ListView, View, define_view
from tests.listview import PIPES, Pipe, PipeExpander, PipesMainView

if TYPE_CHECKING:
    from pathlib import Path


def test_a_record_keeps_its_view_by_its_key_and_a_new_one_gets_a_view() -> None:
    view = PipesMainView()
    pipes = view.pipes
    pipes.items = PIPES
    main_line, ret = pipes.item_views
    assert isinstance(main_line, PipeExpander)
    assert (main_line.title, main_line.length.text) == ("Main line", "Length: 12 m")
    main_line.is_expanded = True

    pipes.items = [Pipe("Feed", 1), Pipe("Main line", 15)]

    feed, kept = pipes.item_views
    assert kept is main_line  # still expanded, its length shown in place
    assert (main_line.is_expanded, main_line.length.text) == (True, "Length: 15 m")
    assert isinstance(feed, PipeExpander)
    assert feed.title == "Feed"
    assert ret not in pipes.children_views  # gone with its record


def test_a_changed_record_gets_a_new_view_unless_it_is_updated_in_place() -> None:
    @define_view
    class Names(ListView[str]):
        def build_item(self, item: str) -> View:
            return LabelView(text=item)

        def item_key(self, item: str) -> str:
            return item.lower()

    names = Names()
    names.items = ["ann"]
    (first,) = names.item_views
    names.items = ["Ann"]  # the same key, changed: no `update_item`, so a new view
    (second,) = names.item_views
    assert second is not first
    assert isinstance(second, LabelView)
    assert second.text == "Ann"
    with pytest.raises(ValueError, match="key 'bob'"):
        names.items = ["bob", "Bob"]


def test_a_view_built_later_passes_the_main_view_and_shows_its_language(tmp_path: Path) -> None:
    (tmp_path / "fr.json").write_text(json.dumps({"Delete": "Supprimer"}), encoding="utf-8")

    @define_view
    class TranslatedPipesMainView(PipesMainView):
        translations_dir = tmp_path

    view = TranslatedPipesMainView()
    view.status_bar.timeout = 0
    _add_reference_to_signals(view, None)
    view.set_language("fr")
    view.pipes.items = PIPES  # built after the app set the main view and the language
    main_line, _ = view.pipes.item_views
    assert isinstance(main_line, PipeExpander)
    assert main_line.delete.text == "Supprimer"

    main_line.delete.clicked.emit()  # its callback asks for the main view by name

    assert view.status_bar.message == "Deleted Main line"
    assert [pipe.name for pipe in view.pipes.items] == ["Return"]
    view.set_language("en")
    (ret,) = view.pipes.item_views
    assert isinstance(ret, PipeExpander)
    assert ret.delete.text == T("Delete")


def test_the_records_are_not_study_data(tmp_path: Path) -> None:
    view = PipesMainView()
    view.pipes.items = PIPES
    path = tmp_path / "study.pipes"
    view.save_state(path)
    assert "items" not in json.dumps(json.loads(path.read_text()))

    other = PipesMainView()
    other.pipes.items = [Pipe("Feed", 1)]
    other.load_state(path)
    other.reset_state()
    assert [pipe.name for pipe in other.pipes.items] == ["Feed"]  # the model's, kept
