"""Tests of what every Textual renderer shares."""

from __future__ import annotations

import pytest

pytest.importorskip("textual")
pytest.importorskip("textual_fspicker")

import asyncio
import subprocess
import sys
import threading
from typing import TYPE_CHECKING

from textual.widgets import (
    Button,
    Checkbox,
    Input,
    Label,
    Static,
)
from textual.widgets._select import SelectCurrent

from composeui.core.registry import RendererType, create_renderer
from composeui.core.renderer import NoRenderedObjectError, RendererContainer
from composeui.core.view import (
    LabelView,
    MainView,
    View,
)
from composeui.textualcore._renderers.navigation import TextualMainRenderer
from composeui.textualcore.textualrenderer import TextualWidgetRenderer
from composeui.textualcore.widgets.composecombobox import ComposeComboBox
from composeui.textualcore.widgets.composedialog import ComposeDialog
from composeui.textualcore.widgets.composefiltertable import (
    ComposeFilterChip,
    ComposeFilterTable,
)
from examples.pipecatalogue import PipeCatalogueMainView
from examples.pipeform import PipeMainView
from examples.textual_demo import TextualDemoMainView
from tests.bookings import BookingMainView
from tests.charts import ChartPagesMainView
from tests.choices import ChoicesMainView
from tests.console import RunMainView
from tests.datafiles import DataFileMainView
from tests.dialogs import DialogsMainView
from tests.expander import RecordMainView
from tests.formdialog import PipeMainView as EditedPipeMainView
from tests.grid import GridMainView
from tests.hours import HoursMainView
from tests.listview import PipesMainView
from tests.markdown import HelpMainView
from tests.markup import MARKUP, MarkupMainView
from tests.menubutton import MenuButtonMainView
from tests.metrics import JobsMainView
from tests.ranges import RangesMainView
from tests.sidebar import SidebarMainView
from tests.splitter import SplitterMainView
from tests.tables import (
    CellWidgetsMainView,
    RoomsDataMainView,
)
from tests.tabs import TabsMainView
from tests.toolbar import ToolBarMainView
from tests.translated import Size, TranslatedMainView
from tests.workers import WorkersMainView

if TYPE_CHECKING:
    from composeui.core.view import View

from tests.textualcore.support import _app_of, _field_widget, _widget


@pytest.mark.asyncio
async def test_textual_app_renders_and_round_trips_input_and_radio_selection() -> None:
    view = TextualDemoMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None

    async with app.run_test() as pilot:
        size_widget = _field_widget(view.form.size.renderer)
        assert isinstance(size_widget, Input)
        assert size_widget.value == "3.0"  # pushed post-mount from the view's initial state

        name_widget = _field_widget(view.form.name.renderer)
        name_widget.focus()
        await pilot.press(*"hi")
        await pilot.pause()
        assert view.form.name.text == "hi"

        shape_widget = _field_widget(view.form.shape.renderer)
        shape_widget.focus()
        await pilot.press("space")
        await pilot.pause()
        assert view.form.shape.value == "ROUND"
        assert view.status_bar.message == "Shape changed: ROUND"


@pytest.mark.asyncio
async def test_a_language_set_once_rendered_relabels_the_widgets() -> None:
    view = TranslatedMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    size = view.shape.size
    seen: list[object] = []
    size.value_changed.connect(seen.append)

    async with app.run_test() as pilot:
        await pilot.pause()
        view.set_language("fr")
        await pilot.pause()

        group = view.shape.renderer
        assert isinstance(group, TextualWidgetRenderer)
        assert group.widget is not None
        assert group.widget.border_title == "Forme"
        assert isinstance(size.renderer, RendererContainer)
        label = size.renderer.get_renderer("label")
        assert isinstance(label, TextualWidgetRenderer)
        assert isinstance(label.widget, Label)
        assert str(label.widget.render()) == "Taille de la forme"
        combobox = _field_widget(size.renderer)
        assert isinstance(combobox, ComposeComboBox)
        # Selection is restored after refresh; pause() can return before that callback.
        await asyncio.wait_for(combobox.wait_for_refresh(), timeout=5)
        await pilot.pause()
        assert [str(prompt) for prompt, _ in combobox._options[1:]] == ["Petite", "Grande"]  # noqa: SLF001
        assert combobox.selection is Size.LARGE
        assert size.value is Size.LARGE
        assert seen == []


@pytest.mark.asyncio
async def test_a_text_like_markup_shows_as_it_is() -> None:
    """Textual reads a string as its markup: `[/]` would crash it, an action would run."""
    view = MarkupMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None

    async with app.run_test(size=(160, 60)) as pilot:
        await pilot.pause()
        note, run, keep = _widget(view.note), _widget(view.run), _widget(view.keep)
        assert isinstance(run, Button)
        assert isinstance(keep, Checkbox)
        assert [str(note.render()), str(run.label), str(keep.label)] == [MARKUP] * 3
        (current,) = _widget(view.size).query(SelectCurrent)
        assert MARKUP in [str(static.render()) for static in current.query(Static)]
        assert isinstance(view.form.name.renderer, RendererContainer)
        label = view.form.name.renderer.get_renderer("label")
        assert isinstance(label, TextualWidgetRenderer)
        assert label.widget is not None
        assert str(label.widget.render()) == f"{MARKUP}\n{MARKUP}"  # the label, its help
        assert str(_widget(view.status_bar).render()) == MARKUP
        box = _widget(view.notes)
        assert isinstance(box, ComposeFilterTable)
        (chip,) = box.bar.chips.query(ComposeFilterChip)
        assert str(chip.open_button.label) == f"{MARKUP}: ={MARKUP} ✎"

        view.warning.open()
        await pilot.pause()
        dialog = app.screen
        assert isinstance(dialog, ComposeDialog)
        title, text = dialog.title_label.render(), dialog.text_label.render()
        assert [str(title), str(text)] == [MARKUP] * 2


_PROGRESS_IN_A_TRANSACTION = """
import asyncio, faulthandler
faulthandler.dump_traceback_later(30, exit=True)
from composeui.core.registry import RendererType
from composeui.core.sqlitemodel import DatabaseModel, SqliteDatabase, SqliteTable, per_session
from composeui.core.view import MainView

class Numbers(SqliteTable):
    create = "CREATE TABLE number(value INTEGER);"

class NumbersDatabase(SqliteDatabase):
    def __init__(self):
        super().__init__()
        self.numbers = self.add_table(Numbers)

class NumbersModel(DatabaseModel):
    study = per_session(NumbersDatabase)

async def main():
    model, view = NumbersModel(), MainView()
    view.render(RendererType.TEXTUAL)
    read = []

    def work(job):
        with model.study.numbers.connection() as db:
            db.execute("INSERT INTO number VALUES (1)")
            job.report_progress(1)

    def show_progress(_value):
        read.append(model.study.numbers.fetch_column("SELECT value FROM number"))

    async with view.renderer.app.run_test() as pilot:
        job = view.jobs.start(work)
        job.progress.connect(show_progress)
        while not read or view.jobs.is_running:
            await pilot.pause(0.01)
    assert read == [[1]], read
    print("finished")

asyncio.run(main())
"""


def test_a_job_reporting_inside_a_transaction_and_a_callback_reading_the_model_both_end() -> None:
    result = subprocess.run(  # noqa: S603 (the script above)
        [sys.executable, "-c", _PROGRESS_IN_A_TRANSACTION],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr  # the stacks of a deadlock
    assert "finished" in result.stdout


@pytest.mark.asyncio
@pytest.mark.parametrize("through_a_job", [False, True])
async def test_a_callback_that_raises_runtime_error_runs_once_on_the_app_s_thread(
    *, through_a_job: bool
) -> None:
    view = MainView()
    app = _app_of(view)
    renderer = view.renderer
    assert isinstance(renderer, TextualMainRenderer)
    threads: list[int] = []
    errors: list[Exception] = []

    def callback() -> None:
        threads.append(threading.get_ident())
        msg = "after a side effect"
        raise RuntimeError(msg)

    def from_a_thread() -> None:
        with pytest.raises(RuntimeError, match="after a side effect"):
            renderer.call_on_main_thread(callback)

    async with app.run_test() as pilot:
        if through_a_job:
            job = view.jobs.start(lambda job: job.call_on_main_thread(callback))
            job.failed.connect(errors.append)
            for _ in range(600):  # the job's end, not time: a slow runner takes seconds
                await pilot.pause(0.05)
                if not view.jobs.is_running:
                    break
            assert app.is_running  # its error is logged: no thread waits for the callback
            assert errors == []
        else:
            await asyncio.to_thread(from_a_thread)

    assert threads == [threading.get_ident()]


def _textual_widgets_of(view: View) -> list[object]:
    """Get the widgets of `view` and of its children, depth first."""
    renderer = view.renderer
    if isinstance(renderer, RendererContainer):
        widgets: list[object] = []
        for part in renderer.renderers:
            assert isinstance(part, TextualWidgetRenderer)
            widgets.append(part.widget)
    else:
        widgets = [getattr(renderer, "widget", getattr(renderer, "app", None))]
    for child_view in view.children_views:
        widgets.extend(_textual_widgets_of(child_view))
    return widgets


@pytest.mark.parametrize(
    "main_view_type",
    [
        PipeMainView,
        PipeCatalogueMainView,
        ChartPagesMainView,
        DialogsMainView,
        GridMainView,
        PipesMainView,
        RecordMainView,
        SidebarMainView,
        SplitterMainView,
        TabsMainView,
        ToolBarMainView,
        MenuButtonMainView,
        CellWidgetsMainView,
        RoomsDataMainView,
        HelpMainView,
        RunMainView,
        JobsMainView,
        BookingMainView,
        DataFileMainView,
        EditedPipeMainView,
        HoursMainView,
        WorkersMainView,
        ChoicesMainView,
        RangesMainView,
    ],
)
def test_a_main_view_rendered_again_keeps_every_widget(main_view_type: type[MainView]) -> None:
    view = main_view_type()
    view.render(RendererType.TEXTUAL)
    before = _textual_widgets_of(view)

    view.render(RendererType.TEXTUAL)

    assert [id(widget) for widget in _textual_widgets_of(view)] == [id(widget) for widget in before]


def test_a_view_shown_before_its_widget_is_built_raises() -> None:
    view = LabelView()
    view.renderer = create_renderer(RendererType.TEXTUAL, "label", view)

    with pytest.raises(NoRenderedObjectError):
        view.text = "Too early"
