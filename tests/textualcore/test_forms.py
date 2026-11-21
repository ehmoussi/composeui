"""Tests of the Textual forms and their rows."""

from __future__ import annotations

import pytest

pytest.importorskip("textual")
pytest.importorskip("textual_fspicker")

from typing import Any

from textual.color import Color as TextualColor
from textual.coordinate import Coordinate
from textual.widget import Widget
from textual.widgets import (
    Input,
    Label,
)

from composeui.core.registry import RendererType
from composeui.core.renderer import RendererContainer
from composeui.core.view import (
    LogType,
)
from composeui.textualcore._renderers.navigation import TextualMainRenderer
from composeui.textualcore.textualrenderer import TextualWidgetRenderer
from composeui.textualcore.widgets.composefiltertable import (
    ComposeFilterTable,
)
from composeui.textualcore.widgets.composeformdialog import ComposeFormDialog
from examples.pipeform import PipeMainView
from tests.folderform import StudyMainView
from tests.lonerows import LoneRowsMainView
from tests.textualcore.support import _app_of, _field_widget, _widget
from tests.unlabelled import NoteMainView


def _textual_part(row: Any, part: str) -> Widget:
    """Get the widget of one of a form row's parts: "label", "field" or "log"."""
    assert isinstance(row.renderer, RendererContainer)
    renderer = row.renderer.get_renderer(part)
    assert isinstance(renderer, TextualWidgetRenderer)
    assert isinstance(renderer.widget, Widget)
    return renderer.widget


@pytest.mark.asyncio
async def test_a_form_row_outside_a_form_shows_as_a_form_shows_it() -> None:
    view = LoneRowsMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    hour, name, note = view.sidebar.hour, view.column.name, view.note
    label = _textual_part(name, "label")
    assert isinstance(label, Label)

    async with app.run_test(size=(120, 50)) as pilot:
        await pilot.pause()
        # in the sidebar, a column, and the main view itself: each part, as in a form
        for row, parts in (
            (hour, ["label", "field"]),
            (name, ["label", "field"]),
            (note, ["field"]),
        ):
            for part in parts:
                widget = _textual_part(row, part)
                assert widget.is_mounted
                assert widget.region.area > 0

        name.label = "Full name"
        await pilot.pause()
        assert str(label.render()) == "Full name"
        # a list's rows: one record more keeps the first one's row, its text with it
        view.names.items = ["First"]
        await pilot.pause()
        (first,) = view.names.item_views
        first_field = _textual_part(first, "field")
        view.names.items = ["First", "Second"]
        await pilot.pause()
        assert view.names.item_views[0] is first
        assert _textual_part(first, "field") is first_field
        for item_view in view.names.item_views:
            assert _textual_part(item_view, "label").is_mounted


@pytest.mark.asyncio
async def test_a_row_s_help_shows_as_a_hint_under_its_label() -> None:
    view = PipeMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    edge_type = view.pages.inputs.pipe_form.edge_type
    assert isinstance(edge_type.renderer, RendererContainer)
    label = edge_type.renderer.get_renderer("label")
    assert isinstance(label, TextualWidgetRenderer)
    assert isinstance(label.widget, Label)

    async with app.run_test() as pilot:
        await pilot.pause()
        assert str(label.widget.render()) == (
            "Edge Type\nHow the edge joining the two pipes is finished"
        )

        edge_type.help = ""
        await pilot.pause()
        assert str(label.widget.render()) == "Edge Type"


@pytest.mark.asyncio
async def test_group_form_shows_a_border_and_title_separating_it_from_other_groups() -> None:
    """A `GroupFormView` must be visually set apart from its siblings, not just labelled.

    `TextualGroupFormRenderer` sets `border_title`, but `border_title` has no effect
    without an actual border style to attach to - without one, every group (e.g.
    pipeform.py's "Main Pipe"/"Incident Pipe") rendered as a plain, undecorated `Vertical`
    indistinguishable from the rest of the form, and adjacent groups ran straight into
    each other with no visible separation at all.
    """
    view = PipeMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None

    async with app.run_test() as pilot:
        await pilot.pause()
        main_pipe_renderer = view.pages.inputs.pipe_form.main_pipe.renderer
        assert isinstance(main_pipe_renderer, TextualWidgetRenderer)
        main_pipe_widget = main_pipe_renderer.widget
        assert main_pipe_widget is not None
        assert main_pipe_widget.styles.border_top[0] != ""  # an actual border is set
        assert main_pipe_widget.border_title == "Main Pipe"


@pytest.mark.asyncio
async def test_a_form_shows_its_other_views_between_its_rows_in_their_order() -> None:
    view = StudyMainView()
    app = _app_of(view)
    form = view.open_dialog.form
    folder = _field_widget(form.folder.renderer)
    assert isinstance(folder, Input)
    buttons, up = _widget(form.buttons), _widget(form.buttons.up)
    box = _widget(form.entries)
    assert isinstance(box, ComposeFilterTable)

    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.pause()
        await pilot.click(_widget(view.open))
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ComposeFormDialog)
        assert folder in screen.walk_children()
        # the folder's row, then the buttons and the table, above the form's message
        assert list(_widget(form).children)[:3] == [folder.parent, buttons, box]

        await pilot.click(up)
        await pilot.pause()

        assert app.screen is screen  # a button of its form leaves it open
        assert folder.value == "/studies"
        assert str(box.table.get_cell_at(Coordinate(0, 0))) == "beam"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("log_type", "color"),
    [(LogType.ERROR, "red"), (LogType.WARNING, "orange"), (LogType.INFO, None)],
)
async def test_a_row_s_message_is_coloured_by_its_type(
    log_type: LogType, color: str | None
) -> None:
    view = PipeMainView()
    app = _app_of(view)
    name = view.pages.inputs.pipe_form.name
    assert isinstance(name.renderer, RendererContainer)
    log = name.renderer.get_renderer("log")
    assert isinstance(log, TextualWidgetRenderer)
    label = log.widget
    assert isinstance(label, Label)

    async with app.run_test(size=(80, 40)) as pilot:
        await pilot.pause()
        name.log_message = "Check the name"
        name.log_type = log_type
        await pilot.pause()

        if color is None:
            assert not label.styles.has_rule("color")
        else:
            assert label.styles.color == TextualColor.parse(color)


@pytest.mark.asyncio
async def test_a_row_without_a_label_shows_its_field_and_its_message() -> None:
    view = NoteMainView()
    app = _app_of(view)
    field = _field_widget(view.form.note.renderer)

    async with app.run_test(size=(80, 20)) as pilot:
        await pilot.pause()
        row = field.parent

        assert row is not None
        children = list(row.children)
        assert children[0] is field  # no label above it
        assert [type(child) for child in children[1:]] == [Label]  # its message
