"""End-to-end coverage for the Textual backend (roadmap item 12).

Uses Textual's headless `App.run_test()` pilot to drive a real rendered widget
tree, proving `composeui.core` isn't secretly Qt-only: the same views/mixins used
by the Qt backend render, accept input, and round-trip state through a second,
unrelated GUI toolkit.
"""

from __future__ import annotations

import pytest

pytest.importorskip("textual")
pytest.importorskip("textual_fspicker")

import datetime
import math
from typing import TYPE_CHECKING, Any, Optional, Union

from attrs import Factory
from rich.color import Color
from rich.style import Style
from rich.text import Text
from textual.color import Color as TextualColor
from textual.containers import VerticalScroll
from textual.coordinate import Coordinate
from textual.screen import Screen
from textual.widgets import (
    Button,
    Checkbox,
    Footer,
    Input,
    Label,
    ProgressBar,
    Static,
    TabPane,
)
from textual.widgets._select import SelectCurrent
from textual.widgets.collapsible import CollapsibleTitle
from textual.widgets.markdown import MarkdownBlock

from composeui.core import chartimage
from composeui.core.application import ModelApplication, _add_reference_to_signals
from composeui.core.registry import create_renderer
from composeui.core.renderer import NoRenderedObjectError, Renderer, RendererContainer
from composeui.core.view import (
    DATA_TABLE_WINDOW,
    SEARCH_DELAY_MS,
    ActionView,
    ButtonVariant,
    CellStyle,
    CellWidget,
    ChartKind,
    DataTableView,
    DialogKind,
    EditRefusedError,
    LabelView,
    ListSource,
    LogType,
    MainView,
    ReferenceLine,
    RendererType,
    SelectionMode,
    Series,
    T,
    TabPage,
    TabView,
    TreeNode,
    View,
    define_view,
    replace_cell,
)
from composeui.textualcore.textualrenderer import (
    ROW_INVALID_CLASS,
    TextualMainRenderer,
    TextualWidgetRenderer,
)
from composeui.textualcore.widgets.composechart import ComposeChart
from composeui.textualcore.widgets.composecollapsible import ComposeCollapsible
from composeui.textualcore.widgets.composecombobox import ComposeCombobox
from composeui.textualcore.widgets.composedatatable import (
    ComposeDataFilterTable,
    ComposeDataTable,
)
from composeui.textualcore.widgets.composedateinput import (
    ComposeCalendar,
    ComposeDateInput,
    ComposeMonth,
)
from composeui.textualcore.widgets.composedialog import ComposeDialog
from composeui.textualcore.widgets.composefilepathinput import ComposeFilePathInput
from composeui.textualcore.widgets.composefiltertable import (
    ComposeFilterBar,
    ComposeFilterChip,
    ComposeFilterTable,
)
from composeui.textualcore.widgets.composeformdialog import ComposeFormDialog
from composeui.textualcore.widgets.composemarkdown import ComposeMarkdown
from composeui.textualcore.widgets.composemetric import ComposeMetric
from composeui.textualcore.widgets.composeradioset import ComposeRadioSet
from composeui.textualcore.widgets.composesidebar import ComposeSidebar
from composeui.textualcore.widgets.composeslider import ComposeSlider
from composeui.textualcore.widgets.composesplitter import ComposeSplitter, SplitterHandle
from composeui.textualcore.widgets.composetabbedcontent import ComposeTabbedContent
from composeui.textualcore.widgets.composetable import (
    ComposeOptionPicker,
    ComposeRowEditor,
    ComposeTable,
)
from composeui.textualcore.widgets.composetoolbar import ComposeToolbar, ComposeToolbarButton
from composeui.textualcore.widgets.composetree import ComposeTree
from examples.batman import BatmanMainView
from examples.pipecatalogue import Material as CatalogueMaterial
from examples.pipecatalogue import Pipe as CataloguePipe
from examples.pipecatalogue import PipeCatalogueMainView, PipeCatalogueModel
from examples.pipecatalogue import PipeExpander as CataloguePipeExpander
from examples.pipechart import MEASUREMENTS, PipeChartMainView
from examples.pipeform import EdgeType, Material, PipeMainView
from examples.textual_demo import TextualDemoMainView
from tests.bookings import BookingMainView
from tests.buildings import SiteMainView, styled_site
from tests.charts import ChartPagesMainView
from tests.datafiles import DataFileMainView
from tests.dialogs import DialogsMainView
from tests.expander import RecordMainView
from tests.formdialog import PipeMainView as EditedPipeMainView
from tests.grid import GridMainView
from tests.horizontal import ButtonsMainView, HorizontalMainView
from tests.hours import HoursMainView
from tests.listview import PIPES, Pipe, PipeExpander, PipesMainView
from tests.markdown import HelpMainView, HelpViewerMainView
from tests.markup import MARKUP, MarkupMainView
from tests.metrics import JobsMainView
from tests.pages import PagesMainView
from tests.partial import PartialMainView, UnregisteredView
from tests.sidebar import SidebarMainView
from tests.splitter import SplitterMainView, VerticalSplitterMainView
from tests.tables import (
    CellWidgetsMainView,
    EditableTableMainView,
    GatedMainView,
    GatedSource,
    MillionRowsMainView,
    MillionSource,
    Room,
    RoomsDataMainView,
    SortedRoomsMainView,
    StyledTablesMainView,
)
from tests.tabs import TabsMainView
from tests.toolbar import ToolBarMainView
from tests.translated import Size, TranslatedMainView
from tests.unlabelled import NoteMainView
from tests.vertical import VerticalMainView
from tests.workers import WorkersMainView

if TYPE_CHECKING:
    from pathlib import Path

    from textual.app import App
    from textual.pilot import Pilot
    from textual.widget import Widget

    from composeui.core.view import TableView, View


def _field_widget(
    field_row_renderer: Optional[Union[Renderer[Any, Any], RendererContainer[Any]]],
) -> Widget:
    assert isinstance(field_row_renderer, RendererContainer)
    field_renderer = field_row_renderer.get_renderer("field")
    assert isinstance(field_renderer, TextualWidgetRenderer)
    assert field_renderer.widget is not None
    return field_renderer.widget


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
async def test_a_float_input_shows_its_value_with_at_most_its_decimals() -> None:
    view = TextualDemoMainView()
    size = view.form.size
    size.decimals = 2
    size.value = 2.71828
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None

    async with app.run_test() as pilot:
        widget = _field_widget(size.renderer)
        assert isinstance(widget, Input)
        await pilot.pause()
        # Textual reports the text set too: the rounded text doesn't replace the value
        assert (widget.value, size.value) == ("2.72", 2.71828)

        size.decimals = 0
        await pilot.pause()
        assert (widget.value, size.value) == ("3", 2.71828)

        widget.focus()
        await pilot.press("end", "backspace", *"1.5")
        await pilot.pause()
        assert size.value == 1.5  # what the user types is the value


@pytest.mark.asyncio
async def test_an_int_input_takes_only_whole_numbers_marking_those_out_of_range() -> None:
    view = HoursMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None

    async with app.run_test() as pilot:
        widget = _field_widget(view.form.opening.renderer)
        assert isinstance(widget, Input)
        await pilot.pause()
        assert widget.value == "8"
        widget.focus()
        await pilot.press("end", "backspace", *"1.5a")
        await pilot.pause()
        assert (widget.value, view.form.opening.value) == ("15", 15)  # "." and "a" never typed
        assert not widget.has_class("-invalid")

        await pilot.press("backspace", "backspace", "-")
        await pilot.pause()
        assert view.form.opening.value is None  # emptied; the "-" alone isn't a value
        await pilot.press("backspace", *"30")
        await pilot.pause()
        assert view.form.opening.value == 30
        assert widget.has_class("-invalid")  # past 23


def _track_and_value(slider: ComposeSlider) -> tuple[str, str]:
    """Get a slider's track and its value, as drawn on its one line."""
    rendered = slider.render()
    assert isinstance(rendered, Text)
    track, value = rendered.plain.split()
    return track, value


#: clears a Textual field of up to 12 characters, the cursor first at its end
_CLEAR = ("end", *["backspace"] * 12)


async def _booking_app() -> tuple[BookingMainView, App[None], list[Optional[datetime.date]]]:
    """Get the booking app in French, and the dates its arrival reports, as they come."""
    view = BookingMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    changes: list[Optional[datetime.date]] = []
    view.form.arrival.value_changed.connect(changes.append)
    view.set_language("fr")
    return view, app, changes


@pytest.mark.asyncio
async def test_a_date_input_is_typed_in_the_language_s_format_marking_what_isn_t_allowed() -> None:
    view, app, changes = await _booking_app()
    arrival = view.form.arrival

    async with app.run_test(size=(80, 30)) as pilot:
        field = _field_widget(arrival.renderer)
        assert isinstance(field, ComposeDateInput)
        await pilot.pause()
        assert field.input.value == "18/10/2026"
        field.input.focus()
        await pilot.press(*_CLEAR, *"25/10/20")
        await pilot.pause()
        assert (arrival.value, changes) == (None, [None])  # emptied, then not a date yet
        assert field.input.has_class("-invalid")
        await pilot.press(*"26")
        await pilot.pause()
        assert (arrival.value, changes[-1]) == (datetime.date(2026, 10, 25),) * 2
        assert not field.input.has_class("-invalid")
        await pilot.press(*_CLEAR, *"1/1/2027")
        await pilot.pause()
        assert arrival.value == datetime.date(2027, 1, 1)
        assert field.input.has_class("-invalid")  # past the maximum: marked, not refused

        await pilot.press("backspace", "enter")  # "1/1/202" left: the date back
        await pilot.pause()
        assert field.input.value == "01/01/2027"
        arrival.value = datetime.date(2026, 10, 18)  # set in code: shown, not reported
        await pilot.pause()
        assert field.input.value == "18/10/2026"
        assert changes[-1] == datetime.date(2027, 1, 1)


@pytest.mark.asyncio
async def test_a_date_input_s_calendar_names_its_days_in_the_language_and_keeps_to_the_range() -> (
    None
):
    view, app, changes = await _booking_app()
    arrival = view.form.arrival

    async with app.run_test(size=(80, 30)) as pilot:
        field = _field_widget(arrival.renderer)
        assert isinstance(field, ComposeDateInput)
        await pilot.pause()
        await pilot.click(field.button)
        await pilot.pause()
        month = app.screen.query_one(ComposeMonth)
        assert month.has_focus
        title, names, *_ = month.render().plain.split("\n")
        assert "octobre 2026" in title
        assert names.split() == ["lu", "ma", "me", "je", "ve", "sa", "di"]
        await pilot.press("down", "pagedown", "enter")  # a week on, then a month on
        await pilot.pause()
        assert not isinstance(app.screen, ComposeCalendar)
        assert (arrival.value, field.input.value) == (datetime.date(2026, 11, 25), "25/11/2026")
        assert changes == [datetime.date(2026, 11, 25)]

        await pilot.click(field.button)
        await pilot.pause()
        month = app.screen.query_one(ComposeMonth)
        await pilot.press("pagedown", "pagedown")  # past the maximum: its last day
        await pilot.pause()
        assert month.cursor == datetime.date(2026, 12, 31)
        # a click on a day: the 1st, on the first week's Tuesday
        await pilot.click(month, offset=(1 * 3 + 2, 2))
        await pilot.pause()
        assert arrival.value == datetime.date(2026, 12, 1)
        await pilot.click(field.button)
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, ComposeCalendar)
        assert changes == [datetime.date(2026, 11, 25), datetime.date(2026, 12, 1)]


@pytest.mark.asyncio
async def test_a_file_path_is_typed_or_picked_in_the_picker_and_reloaded(tmp_path: Path) -> None:
    (tmp_path / "flows.csv").write_text("1,2", encoding="utf-8")
    view = DataFileMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    measurements = view.form.measurements
    picked: list[Path] = []
    measurements.path_picked.connect(picked.append)
    reloads: list[None] = []
    measurements.reload_clicked.connect(lambda: reloads.append(None))

    async with app.run_test(size=(80, 30)) as pilot:
        field = _field_widget(measurements.renderer)
        assert isinstance(field, ComposeFilePathInput)
        await pilot.pause()
        field.input.focus()
        await pilot.press(*str(tmp_path / "x"))
        await pilot.pause()
        assert measurements.path == tmp_path / "x"

        await pilot.click(field.browse_button)
        await pilot.pause()
        assert [type(s).__name__ for s in app.screen_stack] == ["Screen", "FileOpen"]
        file_input = app.screen.query_one(Input)
        file_input.focus()
        file_input.value = str(tmp_path / "flows.csv")
        await pilot.pause()
        await pilot.press("enter")
        for _ in range(4):
            await pilot.pause()
        assert len(app.screen_stack) == 1
        assert (measurements.path, picked) == (tmp_path / "flows.csv", [tmp_path / "flows.csv"])
        assert field.input.value == str(tmp_path / "flows.csv")

        await pilot.click(field.reload_button)
        await pilot.pause()
        assert len(reloads) == 1


@pytest.mark.asyncio
async def test_a_slider_stops_on_its_steps_its_value_drawn_beside_the_track() -> None:
    view = WorkersMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    workers = view.form.workers
    moves: list[int] = []
    workers.value_changed.connect(moves.append)

    async with app.run_test(size=(80, 24)) as pilot:
        slider = _field_widget(workers.renderer)
        assert isinstance(slider, ComposeSlider)
        retries = _field_widget(view.form.retries.renderer)
        await pilot.pause()
        assert slider.region.height == retries.region.height  # a row as tall as an input's
        track, value = _track_and_value(slider)
        assert value == "5"
        first_handle = track.index("●")

        slider.focus()
        await pilot.press("right")
        assert (workers.value, moves) == (8, [8])
        track, value = _track_and_value(slider)
        assert value == "8"
        assert track.index("●") > first_handle
        await pilot.press("end")
        assert (workers.value, moves) == (14, [8, 14])  # the last step, short of 16
        end_track, value = _track_and_value(slider)
        assert value == "14"
        assert len(end_track) == len(track)  # the value's slot as wide: the track keeps its length

        # the track's first column, past the padding, then its last, before the value
        await pilot.click(slider, offset=(1, 1))
        assert (workers.value, moves) == (2, [8, 14, 2])
        await pilot.click(slider, offset=(len(track), 1))
        assert (workers.value, moves) == (14, [8, 14, 2, 14])

        workers.value = 6  # set in code: shown at its nearest step, and not reported
        await pilot.pause()
        assert (_track_and_value(slider)[1], moves) == ("5", [8, 14, 2, 14])


@pytest.mark.asyncio
async def test_textual_radio_group_with_nonnull_initial_value_mounts_without_crashing() -> None:
    """A radio group whose `value` is already non-None on first render used to crash.

    `refresh()` fires "values" (rebuild) and "value" (select) back to back; the
    rebuild's `remove_children()`/`mount()` are asynchronous, so selecting a button
    before that rebuild actually lands raced with it - Textual's own `RadioSet`
    then crashed trying to look up a button that had since been removed.
    `EdgeTypeView` in `examples/pipeform.py` sets a non-None `value` right after
    `values` in `__attrs_post_init__`, which triggers exactly this path.
    """
    view = PipeMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.pause()
        widget = _field_widget(view.pages.inputs.pipe_form.edge_type.renderer)
        assert isinstance(widget, ComposeRadioSet)
        assert widget.value() == EdgeType.Normal
        assert view.pages.inputs.pipe_form.edge_type.value == EdgeType.Normal


@pytest.mark.asyncio
async def test_editing_finished_fires_on_blur_not_just_enter() -> None:
    """Check that editing_finished fires on blur, not just Enter.

    `editing_finished` must match Qt's `QLineEdit.editingFinished`, which fires on
    Enter *or* losing focus - `Input.Submitted` alone only covers Enter, so tabbing
    or clicking away from a field (a common way to fill out a form) used to never
    trigger validation wired to `editing_finished` (e.g. `PipeFormView._display_error_message`).
    """
    view = PipeMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None

    async with app.run_test() as pilot:
        await pilot.pause()
        widget = _field_widget(view.pages.inputs.pipe_form.main_pipe.radius.renderer)
        widget.focus()
        await pilot.press("5")
        await pilot.pause()
        await pilot.press("tab")
        await pilot.pause()

        assert view.pages.inputs.pipe_form.log_view.is_visible
        assert "incident radius" in view.pages.inputs.pipe_form.log_view.log_message


@pytest.mark.asyncio
async def test_a_failing_pipe_check_marks_the_fields_it_names() -> None:
    view = PipeMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    form = view.pages.inputs.pipe_form
    rows = [
        form.main_pipe.radius,
        form.main_pipe.width,
        form.incident_pipe.half_length,
        form.incident_pipe.radius,
    ]

    def marked() -> list[bool]:
        return [_field_widget(row.renderer).has_class(ROW_INVALID_CLASS) for row in rows]

    async with app.run_test() as pilot:
        await pilot.pause()
        radius = _field_widget(form.main_pipe.radius.renderer)
        radius.focus()
        clear = ["end"] + ["backspace"] * 10  # Textual's ctrl+a only goes to the start
        await pilot.press(*clear, *"300", "tab")
        await pilot.pause()
        # radius + width > the incident half length: the incident radius isn't involved
        assert marked() == [True, True, True, False]

        radius.focus()
        await pilot.press(*clear, *"50", "tab")
        await pilot.pause()
        assert marked() == [False, False, False, False]


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
async def test_pressing_the_checkbox_checks_the_view_and_enables_its_row() -> None:
    view = PipeMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    insulated = view.pages.inputs.pipe_form.insulated
    toggled: list[bool] = []
    insulated.toggled.connect(toggled.append)

    async with app.run_test() as pilot:
        await pilot.pause()
        checkbox = _field_widget(insulated.renderer)
        assert isinstance(checkbox, Checkbox)
        assert str(checkbox.label) == "Insulated pipe"
        thickness_widget = _field_widget(view.pages.inputs.pipe_form.insulation_thickness.renderer)
        assert thickness_widget.disabled

        checkbox.focus()
        await pilot.press("space")
        await pilot.pause()

        assert insulated.is_checked is True
        assert not thickness_widget.disabled  # toggled -> the thickness row
        assert toggled == [True]

        # set in code: the box follows, but only the user's toggles are reported
        insulated.is_checked = False
        await pilot.pause()
        assert checkbox.value is False
        assert toggled == [True]


@pytest.mark.asyncio
async def test_the_summary_table_shows_each_edit_as_plain_text() -> None:
    view = PipeMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None

    async with app.run_test(size=(100, 60)) as pilot:
        await pilot.pause()
        assert isinstance(view.pages.results.summary.renderer, TextualWidgetRenderer)
        box = view.pages.results.summary.renderer.widget
        assert isinstance(box, ComposeFilterTable)
        table = box.table

        def lines() -> list[str]:
            return [table.render_line(y).text.strip() for y in range(table.size.height)]

        radius = _field_widget(view.pages.inputs.pipe_form.main_pipe.radius.renderer)
        radius.focus()
        await pilot.press("end", *["backspace"] * 10, *"35", "tab")
        view.pages.navigate("results")
        await pilot.pause()
        assert lines()[1].split() == ["Main", "Pipe", "35", "20", "200"]

        # shown as typed, not read as Rich markup (which would drop "[red]")
        view.pages.results.summary.rows = [["[red]", "1", "2", "3"]]
        await pilot.pause()
        assert lines()[1].split() == ["[red]", "1", "2", "3"]


@pytest.mark.asyncio
async def test_long_log_message_wraps_instead_of_being_clipped() -> None:
    """Check that a long validation message wraps instead of being clipped.

    A `Label`'s default `width: auto` sizes it to its *unwrapped* text - fine for
    a short field label, but a validation message can be long (see
    `PipeFormView._display_error_message`), and left at `auto` it silently overflows
    past the terminal width and gets clipped by the parent's `overflow: hidden`
    instead of wrapping onto more lines.
    """
    view = PipeMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None

    async with app.run_test(size=(80, 40)) as pilot:
        await pilot.pause()
        # Set up values that trip the validation directly on the view, then blur a
        # field for real (through the widget) to run `_display_error_message` via
        # its actual `editing_finished` wiring, not by calling it directly.
        view.pages.inputs.pipe_form.main_pipe.radius.value = 100.0
        view.pages.inputs.pipe_form.main_pipe.width.value = 150.0
        radius_widget = _field_widget(view.pages.inputs.pipe_form.main_pipe.radius.renderer)
        radius_widget.focus()
        await pilot.press("tab")
        await pilot.pause()

        message = view.pages.inputs.pipe_form.log_view.log_message
        assert len(message) > 80  # long enough that width:auto would overflow
        log_renderer = view.pages.inputs.pipe_form.log_view.renderer
        assert isinstance(log_renderer, TextualWidgetRenderer)
        widget = log_renderer.widget
        assert widget is not None
        assert widget.size.width <= 80  # wrapped within the screen, not clipped
        assert widget.size.height > 1  # actually wrapped onto more than one line


@pytest.mark.asyncio
async def test_content_taller_than_the_terminal_is_reachable_by_scrolling() -> None:
    """Toggling a hidden `GroupFormView` visible can grow the form past screen height.

    A plain `Vertical` clips anything past the screen's height instead of making it
    reachable - there'd be no way to see the rest of the form (e.g. `chamfer`'s
    fields, revealed by picking `EdgeType.Chamfer`) with no scrollbar or resize to
    fall back on, unlike a real (resizable) Qt window. `TextualMainRenderer` wraps
    the form content in a `VerticalScroll` for exactly this; `StatusBar` is kept
    outside of it so it stays docked to the actual bottom of the terminal.
    """
    view = PipeMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None

    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        view.pages.inputs.pipe_form.edge_type.value = EdgeType.Chamfer
        await pilot.pause()

        chamfer_renderer = view.pages.inputs.pipe_form.chamfer.renderer
        assert isinstance(chamfer_renderer, TextualWidgetRenderer)
        chamfer_widget = chamfer_renderer.widget
        assert chamfer_widget is not None
        screen_height = app.screen.size.height
        # past the bottom of the terminal before scrolling
        assert chamfer_widget.region.y >= screen_height

        scroller = app.screen.query_one(VerticalScroll)
        assert scroller.max_scroll_y > 0  # there's actually overflow to scroll through
        scroller.scroll_end(animate=False)
        await pilot.pause()
        assert chamfer_widget.region.y < screen_height  # reachable now


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
async def test_menu_actions_become_key_bindings_shown_in_the_footer() -> None:
    """`FileMenu`'s actions aren't rendered as widgets (see `TextualMenuRenderer`).

    Instead `_ComposeUIApp` turns each `ActionView` with a shortcut into a key
    binding, discoverable through a `Footer` - the "key bindings + Footer" style
    chosen for this backend instead of trying to reproduce a Qt-style menu bar.
    """
    view = PipeMainView()
    _add_reference_to_signals(view, None)
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None

    async with app.run_test() as pilot:
        await pilot.pause()
        assert any(isinstance(w, Footer) for w in app.screen.walk_children())
        shortcuts = {action.shortcut for action in app.registered_actions.values()}
        assert shortcuts == {
            "Ctrl+n",
            "Ctrl+o",
            "Ctrl+s",
            "Ctrl+Shift+s",
            "Ctrl+q",
            "Ctrl+r",
            "Ctrl+Shift+e",
            "Ctrl+Shift+f",
        }

        # a plain action (no file dialog involved) dispatches directly - no
        # modal, no worker thread, nothing left on the screen stack.
        await pilot.press("ctrl+n")
        await pilot.pause()
        assert len(app.screen_stack) == 1


@define_view
class _WrapMainView(MainView):
    app_title = "Wrap"
    extension = ".wrap"

    wrap: ActionView = Factory(
        lambda: ActionView(text="Wrap", shortcut="Ctrl+e", is_checkable=True)
    )


@pytest.mark.asyncio
async def test_a_checkable_action_shows_its_check_mark_in_the_footer() -> None:
    view = _WrapMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None

    def descriptions() -> list[str]:
        bindings = app.screen.active_bindings.values()
        return [b.binding.description for b in bindings if "Wrap" in b.binding.description]

    async with app.run_test() as pilot:
        await pilot.pause()
        assert descriptions() == ["Wrap"]

        await pilot.press("ctrl+e")
        await pilot.pause()

        assert view.wrap.is_checked is True
        assert descriptions() == ["✓ Wrap"]


@pytest.mark.asyncio
async def test_open_file_action_runs_the_picker_on_a_worker_thread_and_loads_state(
    tmp_path: Path,
) -> None:
    """Ctrl+O should show `textual-fspicker`'s modal and load the picked file.

    `ask_open_filepath` blocks waiting for the picked path; blocking the app's own
    thread while it needs to render and drive that same modal would deadlock, so
    `_ComposeUIApp.action_trigger` runs file-dialog actions on a worker thread
    (`TextualMainRenderer.open_file` bridges back to the modal via
    `App.call_from_thread`). The subsequent `MainView.load_state` call then mutates
    widgets from that worker thread, which is exactly why `TextualWidgetRenderer.
    refresh`/`refresh_attribute` marshal onto the main thread instead of applying
    Textual reactives directly.
    """
    donor = PipeMainView()
    donor.pages.inputs.pipe_form.name.text = "loaded_name"
    filepath = tmp_path / "state.pipe"
    donor.save_state(filepath)

    view = PipeMainView()
    _add_reference_to_signals(view, None)
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("ctrl+o")
        await pilot.pause()
        await pilot.pause()
        assert [type(s).__name__ for s in app.screen_stack] == ["Screen", "FileOpen"]

        file_input = app.screen.query_one(Input)
        file_input.focus()
        file_input.value = str(filepath)
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()
        await pilot.pause()

        assert len(app.screen_stack) == 1  # modal closed
        assert view.file_view.filepath == filepath
        assert view.pages.inputs.pipe_form.name.text == "loaded_name"
        name_widget = _field_widget(view.pages.inputs.pipe_form.name.renderer)
        assert isinstance(name_widget, Input)
        assert name_widget.value == "loaded_name"  # the real widget reflects it too


@pytest.mark.asyncio
async def test_pick_file_action_hands_the_picked_file_over(tmp_path: Path) -> None:
    """Its picker blocks a worker thread, as Open's does: the app keeps driving the modal."""
    path = tmp_path / "notes.md"
    path.write_text("# Notes", encoding="utf-8")
    view = HelpMainView()
    _add_reference_to_signals(view, None)
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("ctrl+h")
        await pilot.pause()
        await pilot.pause()
        assert [type(s).__name__ for s in app.screen_stack] == ["Screen", "FileOpen"]
        file_input = app.screen.query_one(Input)
        file_input.focus()
        file_input.value = str(path)
        await pilot.pause()
        await pilot.press("enter")
        for _ in range(4):
            await pilot.pause()
        assert len(app.screen_stack) == 1
        assert view.help.text == "# Notes"


@pytest.mark.asyncio
async def test_an_app_without_studies_binds_no_file_menu_key() -> None:
    view = HelpViewerMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None

    async with app.run_test() as pilot:
        await pilot.pause()
        descriptions = [b.binding.description for b in app.screen.active_bindings.values()]
        assert "Open Help" in descriptions
        assert not {"New", "Open", "Save", "Save As"} & set(descriptions)


@pytest.mark.asyncio
async def test_open_file_action_can_be_cancelled_without_hanging() -> None:
    """Dismissing the picker (Escape) must resolve the worker cleanly, not hang.

    `TextualMainRenderer.open_file` blocks a worker thread on `call_from_thread`;
    if cancelling the modal didn't unblock it, the app would hang forever waiting
    for a path that's never coming.
    """
    view = PipeMainView()
    _add_reference_to_signals(view, None)
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("ctrl+o")
        await pilot.pause()
        await pilot.pause()
        assert len(app.screen_stack) == 2

        await pilot.press("escape")
        await pilot.pause()
        await pilot.pause()

        assert len(app.screen_stack) == 1
        assert view.file_view.filepath is None


@pytest.mark.asyncio
async def test_a_horizontal_view_shares_the_row_by_stretch() -> None:
    view = HorizontalMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    widgets = []
    for table in (view.tables.narrow, view.tables.wide, view.tables):
        assert isinstance(table.renderer, TextualWidgetRenderer)
        assert table.renderer.widget is not None
        widgets.append(table.renderer.widget)

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        narrow, wide, row = (widget.region for widget in widgets)
        assert narrow.y == wide.y
        assert narrow.right <= wide.x
        assert wide.width == pytest.approx(3 * narrow.width, rel=0.02)
        # the hidden table takes no share: the two shown span the row
        assert (narrow.x, wide.right) == (row.x, row.right)


@pytest.mark.asyncio
async def test_a_vertical_view_stacks_its_views_at_its_top() -> None:
    view = VerticalMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    widgets = []
    for child in (view.tables.column.table, view.tables.column.button, view.tables.tall):
        assert isinstance(child.renderer, TextualWidgetRenderer)
        assert child.renderer.widget is not None
        widgets.append(child.renderer.widget)

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        table, button, tall = (widget.region for widget in widgets)
        assert table.y == tall.y
        assert button.y == table.bottom
        # next to a taller table, the column's spare height is left below its views
        assert button.bottom < tall.bottom


@pytest.mark.asyncio
async def test_a_grid_view_places_its_views_in_equally_wide_columns() -> None:
    view = GridMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    widgets = []
    for child in (view.tables.first, view.tables.button, view.tables.spanning, view.tables):
        assert isinstance(child.renderer, TextualWidgetRenderer)
        assert child.renderer.widget is not None
        widgets.append(child.renderer.widget)

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        first, button, spanning, grid = (widget.region for widget in widgets)
        assert (first.x, first.y, button.y) == (grid.x, grid.y, grid.y)
        assert first.width == grid.width // 3
        # the hidden table's column is kept: the button is in the third one
        assert button.x == grid.x + 2 * first.width
        # as wide as its text, unlike the table filling its column
        assert button.width < first.width // 2
        # the next row starts below the taller of the views above it, spanning the columns
        assert (spanning.x, spanning.y, spanning.right) == (grid.x, first.bottom, grid.right)


@pytest.mark.asyncio
async def test_buttons_with_no_share_pack_at_their_row_s_start_or_end() -> None:
    view = ButtonsMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None

    def widget(of: View) -> Widget:
        assert isinstance(of.renderer, TextualWidgetRenderer)
        assert of.renderer.widget is not None
        return of.renderer.widget

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        for row, packed_at_end in ((view.start, False), (view.end, True)):
            first, second = widget(row.first).region, widget(row.second).region
            row_region = widget(row).region
            # as wide as their text, side by side
            assert first.width < row_region.width // 4
            assert second.x - first.right < 4
            if packed_at_end:
                assert second.right == row_region.right
            else:
                assert first.x == row_region.x


@pytest.mark.asyncio
async def test_the_toolbar_shows_one_page_at_a_time() -> None:
    view = PagesMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    name = view.router.inputs.name.renderer
    total = view.router.results.total.renderer
    assert isinstance(name, TextualWidgetRenderer)
    assert isinstance(total, TextualWidgetRenderer)
    assert name.widget is not None
    assert total.widget is not None

    async with app.run_test() as pilot:
        await pilot.pause()
        buttons = {str(button.label): button for button in app.query(ComposeToolbarButton)}
        assert list(buttons) == ["Inputs", "Results"]
        assert buttons["Inputs"].variant == "primary"
        assert name.widget.region.height > 0
        assert total.widget.region.height == 0

        await pilot.click(buttons["Results"])
        await pilot.pause()
        assert view.router.current_route == "results"
        assert total.widget.region.height > 0
        assert name.widget.region.height == 0
        assert buttons["Results"].variant == "primary"
        assert buttons["Inputs"].variant == "default"

        view.router.navigate("inputs")  # from app code
        await pilot.pause()
        assert name.widget.region.height > 0
        assert buttons["Inputs"].variant == "primary"


@pytest.mark.asyncio
async def test_a_sidebar_is_a_column_left_of_the_pages_whatever_the_page() -> None:
    view = SidebarMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    widgets = [
        renderer.widget
        for renderer in (
            view.sidebar.renderer,
            view.sidebar.create.renderer,
            view.router.inputs.submit.renderer,
            view.router.results.progress.renderer,
        )
        if isinstance(renderer, TextualWidgetRenderer)
    ]
    sidebar, create, submit, progress = widgets
    assert isinstance(sidebar, ComposeSidebar)

    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        assert str(sidebar.title.render()) == "New record"
        assert create in sidebar.walk_children()
        assert sidebar.region.right <= submit.region.x  # on the pages' left

        view.router.navigate("results")
        await pilot.pause()
        assert create.region.area > 0  # still shown, beside the other page
        assert sidebar.region.right <= progress.region.x
        view.sidebar.title = ""
        await pilot.pause()
        assert not sidebar.title.display  # no empty heading


@pytest.mark.asyncio
async def test_a_sidebar_retracts_to_a_strip_by_its_arrow_and_back() -> None:
    view = SidebarMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    widgets = [
        renderer.widget
        for renderer in (view.sidebar.renderer, view.sidebar.create.renderer)
        if isinstance(renderer, TextualWidgetRenderer)
    ]
    sidebar, create = widgets
    assert isinstance(sidebar, ComposeSidebar)
    toggles: list[bool] = []
    view.sidebar.toggled.connect(toggles.append)

    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        width = sidebar.region.width
        await pilot.click(sidebar.toggle)
        await pilot.pause()
        assert (view.sidebar.is_expanded, toggles) == (False, [False])
        assert create.region.area == 0
        assert sidebar.region.width < width / 4  # a strip: the pages take the room
        assert sidebar.toggle.region.area > 0  # its arrow brings it back
        assert not sidebar.title.display

        sidebar.toggle.focus()
        await pilot.press("enter")
        await pilot.pause()
        assert (view.sidebar.is_expanded, toggles) == (True, [False, True])
        assert create.region.area > 0
        view.sidebar.is_expanded = False  # set in code: retracted, and not reported
        await pilot.pause()
        assert create.region.area == 0
        assert toggles == [False, True]


@pytest.mark.asyncio
async def test_a_list_view_shows_a_view_per_record_as_the_records_change() -> None:
    view = PipesMainView()
    view.status_bar.timeout = 0
    _add_reference_to_signals(view, None)
    view.pipes.items = PIPES[:1]  # before rendering, as at startup
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    assert isinstance(view.pipes.renderer, TextualWidgetRenderer)
    column = view.pipes.renderer.widget
    assert column is not None

    def shown() -> list[str]:
        return [
            str(child.title) for child in column.children if isinstance(child, ComposeCollapsible)
        ]

    async with app.run_test(size=(80, 40)) as pilot:
        await pilot.pause()
        assert shown() == ["Main line"]
        main_line = view.pipes.item_views[0]
        assert isinstance(main_line.renderer, TextualWidgetRenderer)
        main_line_widget = main_line.renderer.widget

        view.pipes.items = [Pipe("Feed", 1), *PIPES]  # built since: mounted as they come
        await pilot.pause()
        assert shown() == ["Feed", "Main line", "Return"]
        # collapsed, a line apart: a rule, then the title
        assert [child.region.height for child in column.children] == [2, 2, 2]
        assert column.children[1] is main_line_widget  # the record's own widget
        feed = view.pipes.item_views[0]
        assert isinstance(feed, PipeExpander)
        feed.is_expanded = True
        await pilot.pause()
        assert isinstance(feed.length.renderer, TextualWidgetRenderer)
        length = feed.length.renderer.widget
        assert isinstance(length, Label)
        assert str(length.render()) == "Length: 1 m"  # its state, given once mounted

        assert isinstance(feed.delete.renderer, TextualWidgetRenderer)
        delete = feed.delete.renderer.widget
        assert delete is not None
        await pilot.click(delete)
        await pilot.pause()
        assert shown() == ["Main line", "Return"]
        assert view.status_bar.message == "Deleted Feed"


@pytest.mark.asyncio
async def test_a_tab_view_shows_the_tab_the_user_picks() -> None:
    view = TabsMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    tabs = view.tabs
    assert isinstance(tabs.renderer, TextualWidgetRenderer)
    tabbed = tabs.renderer.widget
    assert isinstance(tabbed, ComposeTabbedContent)
    panes = []
    for tab in tabs.tabs:
        assert isinstance(tab.renderer, TextualWidgetRenderer)
        panes.append(tab.renderer.widget)
    details, history, notes = panes
    assert isinstance(history, TabPane)
    assert isinstance(notes, TabPane)
    picks: list[int] = []
    tabs.current_changed.connect(picks.append)

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        assert [str(tabbed.get_tab(pane).label) for pane in panes] == [
            "Details",
            "History",
            "Notes",
        ]
        assert tabbed.active_pane is details

        await pilot.click(tabbed.get_tab(history))
        await pilot.pause()
        assert (tabs.current_index, picks) == (1, [1])
        assert tabbed.active_pane is history

        tabs.current_index = 0  # set in code: shown, and not reported
        await pilot.pause()
        assert (tabbed.active_pane, picks) == (details, [1])
        tabs.history.title = "Changes"
        tabs.notes.is_enabled = False
        tabs.notes.is_visible = False
        await pilot.pause()
        assert str(tabbed.get_tab(history).label) == "Changes"
        assert tabbed.get_tab(notes).disabled
        assert not tabbed.get_tab(notes).display


@pytest.mark.asyncio
async def test_a_form_dialog_s_ok_follows_its_form_s_checks() -> None:
    view = EditedPipeMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    name = _field_widget(view.edit_dialog.form.name.renderer)
    assert isinstance(name, Input)
    assert isinstance(view.edit.renderer, TextualWidgetRenderer)
    edit = view.edit.renderer.widget
    assert edit is not None

    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.pause()
        await pilot.click(edit)
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ComposeFormDialog)
        assert name in screen.walk_children()
        assert str(screen.title_label.render()) == "Edit the pipe"
        assert not screen.accept_button.disabled
        name.focus()
        await pilot.press("end", *["backspace"] * len("Main line"))
        await pilot.pause()
        assert screen.accept_button.disabled  # a name is mandatory
        await pilot.press(*"Return")
        await pilot.pause()
        assert not screen.accept_button.disabled
        await pilot.click(screen.accept_button)
        await pilot.pause()
        assert app.screen is not screen
        assert view.pipe.text == "Return, 12 m"

        await pilot.click(edit)  # its screen again, its form's widgets kept
        await pilot.pause()
        assert app.screen is screen
        await pilot.press("escape")  # Cancel
        await pilot.pause()
        assert app.screen is not screen
        assert view.pipe.text == "Return, 12 m"


@pytest.mark.asyncio
async def test_a_form_dialog_s_form_gets_its_state_once_its_screen_shows() -> None:
    """Its widgets mount with its screen, not the app: a `Select` takes its options only then."""
    app_views = ModelApplication(
        build_main_view=PipeCatalogueMainView,
        build_model=PipeCatalogueModel,
        setup_model=PipeCatalogueMainView.connect_model,
    )
    app_views.model.pipes.add(CataloguePipe("Main line", CatalogueMaterial.COPPER, 50.0, 5.0, 6.0))
    view = app_views.main_view
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    material = _field_widget(view.edit_dialog.form.material.renderer)
    assert isinstance(material, ComposeCombobox)

    async with app.run_test(size=(120, 40)) as pilot:  # the app starts, its dialog closed
        await pilot.pause()
        (pipe,) = view.catalogue.browser.pipes.item_views
        assert isinstance(pipe, CataloguePipeExpander)
        pipe.is_expanded = True
        await pilot.pause()
        assert isinstance(pipe.buttons.edit.renderer, TextualWidgetRenderer)
        edit = pipe.buttons.edit.renderer.widget
        assert edit is not None

        await pilot.click(edit)
        # the screen's widgets mount a few messages later, more than one pause on a slow system
        for _ in range(100):
            await pilot.pause(0.05)
            if material.value == CatalogueMaterial.COPPER:
                break

        assert isinstance(app.screen, ComposeFormDialog)
        assert material.value == CatalogueMaterial.COPPER
    app_views.model.close()


@pytest.mark.asyncio
async def test_a_toolbar_shows_its_actions_above_the_pages_toolbar() -> None:
    view = ToolBarMainView()
    _add_reference_to_signals(view, None)
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None

    async with app.run_test() as pilot:
        await pilot.pause()
        toolbar, pages = app.query(ComposeToolbar)
        # docked at the top together, not over each other
        assert toolbar.region.y == 0
        assert pages.region.y == toolbar.region.bottom
        buttons = {str(button.label): button for button in toolbar.query(ComposeToolbarButton)}
        assert list(buttons) == ["Open", "Run", "Wrap"]

        await pilot.click(buttons["Run"])
        await pilot.pause()
        assert view.router.results.total.text == "Ran"
        await pilot.click(buttons["Wrap"])
        await pilot.pause()
        assert view.toolbar.wrap.is_checked
        assert buttons["Wrap"].variant == "primary"

        # the picker blocks its caller: run from the app's own thread, it would never show
        await pilot.click(buttons["Open"])
        await pilot.pause()
        await pilot.pause()
        assert [type(s).__name__ for s in app.screen_stack] == ["Screen", "FileOpen"]


def _tree_lines(tree: ComposeTree) -> list[tuple[str, bool]]:
    """Get a tree's lines as shown: each node's label, and whether it is marked selected."""
    lines = []
    for line in range(tree.last_line + 1):
        node = tree.get_node_at_line(line)
        assert node is not None
        label = tree.render_label(node, Style(), Style())
        is_marked = any(isinstance(span.style, Style) and span.style.bold for span in label.spans)
        lines.append((label.plain, is_marked))
    return lines


@pytest.mark.asyncio
async def test_a_tree_selects_its_nodes_by_enter_or_click_and_expands_them_by_space() -> None:
    view = SiteMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    site = view.site
    assert isinstance(site.renderer, TextualWidgetRenderer)
    tree = site.renderer.widget
    assert isinstance(tree, ComposeTree)
    selections: list[tuple[str, ...]] = []
    toggles: list[tuple[tuple[str, ...], bool]] = []
    site.selection_changed.connect(selections.append)
    site.toggled.connect(lambda path, is_expanded: toggles.append((path, is_expanded)))

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        assert [label for label, _ in _tree_lines(tree)] == [
            "▼ Building A",
            "▶ Floor 1",
            "▶ Floor 2",
            "▶ Building B",
            "Parking",
        ]
        await pilot.click(tree, offset=(8, 2))
        await pilot.pause()
        assert (site.selected, selections) == (
            ("Building A", "Floor 2"),
            [("Building A", "Floor 2")],
        )
        assert _tree_lines(tree)[2] == ("▶ Floor 2", True)
        assert site.expanded == [("Building A",)]  # a click selects, without toggling

        tree.focus()
        await pilot.press("space")  # the node under the cursor
        await pilot.pause()
        assert site.expanded == [("Building A",), ("Building A", "Floor 2")]
        assert toggles == [(("Building A", "Floor 2"), True)]
        await pilot.press("down", "enter")
        await pilot.pause()
        assert selections[-1] == ("Building A", "Floor 2", "Room 201")
        assert [marked for _, marked in _tree_lines(tree)] == [
            False,
            False,
            False,
            True,
            False,
            False,
        ]

        # set in code: shown, and not reported
        site.expanded = []
        site.selected = ("Parking",)
        await pilot.pause()
        assert _tree_lines(tree) == [
            ("▶ Building A", False),
            ("▶ Building B", False),
            ("Parking", True),
        ]
        assert (len(selections), len(toggles)) == (2, 1)
        site.nodes = [*site.nodes, TreeNode("Garden")]
        await pilot.pause()
        assert _tree_lines(tree)[-2:] == [("Parking", True), ("Garden", False)]


@pytest.mark.asyncio
async def test_a_tree_shows_its_nodes_style_and_mark_after_the_label() -> None:
    view = SiteMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    site = view.site
    assert isinstance(site.renderer, TextualWidgetRenderer)
    tree = site.renderer.widget
    assert isinstance(tree, ComposeTree)

    async with app.run_test(size=(80, 30)) as pilot:
        site.nodes = styled_site("building.png")  # a terminal shows no icon
        site.selected = ("Building A", "Room 101")
        await pilot.pause()
        labels = {}
        for line in range(tree.last_line + 1):
            node = tree.get_node_at_line(line)
            assert node is not None
            label = tree.render_label(node, Style(), Style())
            labels[label.plain] = label
        assert list(labels) == ["▼ Building A", "Room 101 ✓", "Room 102 ✗", "Parking !"]

        def style_of(label: str, text: str) -> Style:
            start = label.index(text)
            return labels[label].get_style_at_offset(app.console, start)

        assert style_of("▼ Building A", "Building").bold
        assert not style_of("▼ Building A", "Building").underline
        assert style_of("Parking !", "Parking").underline
        assert not style_of("Parking !", "Parking").bold
        # the mark in its own color, the selected label's left out
        selected, done = style_of("Room 101 ✓", "Room"), style_of("Room 101 ✓", "✓")
        assert selected.color != done.color
        assert {
            done.color,
            style_of("Room 102 ✗", "✗").color,
            style_of("Parking !", "!").color,
        } == {
            Color.parse("green"),
            Color.parse("red"),
            Color.parse("orange1"),
        }


@pytest.mark.asyncio
async def test_an_expander_shows_its_views_while_expanded_by_its_title() -> None:
    view = RecordMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    record, history = view.record, view.record.history
    toggles: list[bool] = []
    history_toggles: list[bool] = []
    record.toggled.connect(toggles.append)
    history.toggled.connect(history_toggles.append)
    widgets = [
        renderer.widget
        for renderer in (record.renderer, history.renderer, record.buttons.edit.renderer)
        if isinstance(renderer, TextualWidgetRenderer)
    ]
    expander, history_expander, edit = widgets
    assert isinstance(expander, ComposeCollapsible)
    assert isinstance(history_expander, ComposeCollapsible)

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        assert expander.title == "Pipe A"
        assert edit.region.area == 0  # collapsed: not laid out

        await pilot.click(expander.query_one(CollapsibleTitle))
        await pilot.pause()
        assert (record.is_expanded, toggles) == (True, [True])
        assert edit.region.area > 0
        # the nested expander's toggle is its own
        history_expander.query_one(CollapsibleTitle).focus()
        await pilot.press("enter")
        await pilot.pause()
        assert (history.is_expanded, history_toggles, toggles) == (True, [True], [True])
        await pilot.press("enter")  # and back
        await pilot.pause()
        assert (history.is_expanded, history_toggles) == (False, [True, False])
        await pilot.press("enter")
        await pilot.pause()

        record.is_expanded = False  # set in code: collapsed, and not reported
        await pilot.pause()
        assert edit.region.area == 0
        assert toggles == [True]


@pytest.mark.asyncio
async def test_a_splitter_shares_its_width_as_its_sizes_and_takes_the_users_drags() -> None:
    view = SplitterMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    splitter = view.splitter
    assert isinstance(splitter.renderer, TextualWidgetRenderer)
    widget = splitter.renderer.widget
    assert isinstance(widget, ComposeSplitter)

    async with app.run_test(size=(84, 20)) as pilot:
        await pilot.pause()
        study, settings, result = widget.pane_lengths()
        assert study == pytest.approx(settings, abs=1)  # rounded to cells
        assert result == pytest.approx(2 * study, abs=2)
        resizes: list[list[int]] = []
        splitter.resized.connect(resizes.append)
        first, second = widget.query(SplitterHandle)
        # the borders as tall as the panes, not the screen
        assert first.region.height == widget.region.height == 1

        # on the screen: the handle follows the mouse
        dragged_to = (first.region.x + 6, first.region.y)
        await pilot.mouse_down(first)
        await pilot.hover(None, offset=dragged_to)
        await pilot.mouse_up(None, offset=dragged_to)
        await pilot.pause()
        widths = widget.pane_lengths()
        assert widths == [study + 6, settings - 6, result]
        assert splitter.sizes == [round(100 * width / sum(widths)) for width in widths]
        assert resizes == [splitter.sizes]  # once dropped
        await pilot.click(second)  # a click: nothing moves, nothing reported
        await pilot.pause()
        assert len(resizes) == 1
        second.focus()  # the arrow keys move a focused border
        await pilot.press("left", "left")
        await pilot.pause()
        assert widget.pane_lengths()[2] == result + 2
        assert len(resizes) == 3

        splitter.sizes = [1, 1, 1]  # set in code: shared alike, and not reported
        await pilot.pause()
        assert len(resizes) == 3
        study, settings, result = widget.pane_lengths()
        assert study == pytest.approx(settings, abs=1)
        assert study == pytest.approx(result, abs=1)
        splitter.settings.is_visible = False  # its width to the others, its share kept
        await pilot.pause()
        assert widget.pane_lengths()[1] == 0
        assert (first.display, second.display) == (False, True)
        study, _, result = widget.pane_lengths()
        await pilot.press("right")  # the study's border, now
        await pilot.pause()
        assert widget.pane_lengths() == [study + 1, 0, result - 1]
        assert splitter.sizes == [
            round(100 * (study + 1) / (study + result)),
            1,
            round(100 * (result - 1) / (study + result)),
        ]


@pytest.mark.asyncio
async def test_a_splitter_keeps_its_panes_through_a_language_switch() -> None:
    view = SplitterMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None

    async with app.run_test(size=(84, 20)) as pilot:
        await pilot.pause()
        view.set_language("fr")  # its borders' name is the web's only
        await pilot.pause()

        assert view.splitter.border_text == "Redimensionner les volets"
        assert isinstance(view.splitter.renderer, TextualWidgetRenderer)
        widget = view.splitter.renderer.widget
        assert isinstance(widget, ComposeSplitter)
        assert len(widget.pane_lengths()) == 3


@pytest.mark.asyncio
async def test_a_vertical_splitter_shares_its_rows_and_moves_its_border_up_and_down() -> None:
    view = VerticalSplitterMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    splitter = view.splitter
    assert isinstance(splitter.renderer, TextualWidgetRenderer)
    widget = splitter.renderer.widget
    assert isinstance(widget, ComposeSplitter)

    async with app.run_test(size=(60, 40)) as pilot:
        await pilot.pause()
        chart, table = widget.pane_lengths()
        assert chart + table + 1 == widget.region.height == 24  # and the border's row
        assert chart == pytest.approx(2 * table, abs=1)
        handle = widget.query_one(SplitterHandle)
        assert (handle.region.width, handle.region.height) == (widget.region.width, 1)

        dragged_to = (handle.region.x + 5, handle.region.y + 4)
        await pilot.mouse_down(handle, offset=(5, 0))
        await pilot.hover(None, offset=dragged_to)
        await pilot.mouse_up(None, offset=dragged_to)
        await pilot.pause()
        assert widget.pane_lengths() == [chart + 4, table - 4]
        handle.focus()
        await pilot.press("left", "right")  # across the border: nothing moves
        await pilot.press("up")
        await pilot.pause()
        assert widget.pane_lengths() == [chart + 3, table - 3]
        assert splitter.sizes == [
            round(100 * (chart + 3) / (chart + table)),
            round(100 * (table - 3) / (chart + table)),
        ]


@pytest.mark.asyncio
async def test_a_metric_shows_its_change_as_a_badge_colored_by_sign() -> None:
    view = JobsMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    running, failed = view.summary.running.renderer, view.summary.failed.renderer
    assert isinstance(running, TextualWidgetRenderer)
    assert isinstance(failed, TextualWidgetRenderer)
    running_metric, failed_metric = running.widget, failed.widget
    assert isinstance(running_metric, ComposeMetric)
    assert isinstance(failed_metric, ComposeMetric)

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        assert str(running_metric.value.render()) == "3"
        assert str(running_metric.badge.render()) == "↑ 2 since yesterday"
        assert not failed_metric.badge.display  # no change given
        # side by side in their row
        assert failed_metric.region.x > running_metric.region.x
        rise = running_metric.badge.styles.color

        view.summary.running.delta = -2
        view.summary.failed.delta = 0
        await pilot.pause()
        assert str(running_metric.badge.render()) == "↓ 2 since yesterday"
        assert running_metric.badge.styles.color != rise
        assert failed_metric.badge.display


@pytest.mark.asyncio
async def test_the_progress_bar_follows_its_view() -> None:
    view = PagesMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    progress = view.router.results.progress
    assert isinstance(progress.renderer, TextualWidgetRenderer)
    bar = progress.renderer.widget
    assert isinstance(bar, ProgressBar)

    async with app.run_test() as pilot:
        await pilot.pause()
        assert (bar.progress, bar.total) == (0, 100)
        progress.value = 40
        progress.maximum = 200
        await pilot.pause()
        assert (bar.progress, bar.total) == (40, 200)
        progress.value = 250
        await pilot.pause()
        assert bar.progress == 200  # full, not past its end
        progress.maximum = None
        await pilot.pause()
        assert bar.percentage is None  # Textual's bar for a task of unknown length


def _shown_blocks(markdown: ComposeMarkdown) -> list[tuple[str, str]]:
    """Return the document's top blocks: each one's kind and Markdown."""
    return [
        (type(block).__name__, block.source or "")
        for block in markdown.children
        if isinstance(block, MarkdownBlock)
    ]


@pytest.mark.asyncio
async def test_the_markdown_shows_its_text_formatted() -> None:
    view = HelpMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    assert isinstance(view.help.renderer, TextualWidgetRenderer)
    markdown = view.help.renderer.widget
    assert isinstance(markdown, ComposeMarkdown)

    async with app.run_test() as pilot:
        await pilot.pause()
        assert _shown_blocks(markdown) == [
            ("MarkdownH1", "# Help\n"),
            ("MarkdownBulletList", "- Open a study\n- Run it\n"),
        ]
        # set twice in a row: only the last text shows, once
        view.help.text = "## Results"
        view.help.text = "## Results\n\nAll done."
        await pilot.pause()
        await pilot.pause()
        assert _shown_blocks(markdown) == [
            ("MarkdownH2", "## Results\n"),
            ("MarkdownParagraph", "All done."),
        ]


@pytest.mark.asyncio
async def test_pressing_the_button_runs_what_its_view_connects() -> None:
    view = PagesMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    inputs = view.router.inputs
    assert isinstance(inputs.submit.renderer, TextualWidgetRenderer)
    button = inputs.submit.renderer.widget
    assert isinstance(button, Button)

    async with app.run_test() as pilot:
        await pilot.pause()
        assert str(button.label) == "Submit"
        inputs.name.text = "Ada"

        await pilot.click(button)
        await pilot.pause()

        assert view.router.results.total.text == "Submitted: Ada"
        inputs.submit.text = "Send"
        await pilot.pause()
        assert str(button.label) == "Send"
        assert button.variant == "primary"
        inputs.submit.variant = ButtonVariant.DANGER
        await pilot.pause()
        assert button.variant == "error"


@pytest.mark.asyncio
async def test_a_confirmation_is_a_modal_screen_answered_with_its_buttons() -> None:
    view = DialogsMainView()
    view.confirm_clear.open()  # before the app runs: shown once it does
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None

    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ComposeDialog)
        assert str(screen.text_label.render()) == "The name will be lost."
        assert str(screen.accept_button.label) == "Clear"
        assert screen.reject_button.display
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, ComposeDialog)
        assert not view.confirm_clear.is_visible
        assert view.name.text == "Ada"

        await pilot.press("ctrl+l")  # the Clear action
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ComposeDialog)
        view.confirm_clear.text = "Really?"  # while open
        await pilot.pause()
        assert str(screen.text_label.render()) == "Really?"
        await pilot.click("#accept")
        await pilot.pause()
        assert not isinstance(app.screen, ComposeDialog)
        assert view.name.text == ""


@pytest.mark.asyncio
async def test_the_app_closes_a_dialog_unanswered_and_escape_accepts_a_message() -> None:
    view = DialogsMainView()
    dialog = view.confirm_clear
    answers: list[str] = []
    dialog.accepted.connect(lambda: answers.append("accepted"))
    dialog.rejected.connect(lambda: answers.append("rejected"))
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None

    async with app.run_test() as pilot:
        dialog.open()
        await pilot.pause()
        assert isinstance(app.screen, ComposeDialog)
        dialog.is_visible = False
        await pilot.pause()
        assert not isinstance(app.screen, ComposeDialog)
        assert answers == []
        # a message: Escape accepts it
        dialog.kind = DialogKind.MESSAGE
        dialog.open()
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ComposeDialog)
        assert not screen.reject_button.display
        await pilot.press("escape")
        await pilot.pause()
        assert answers == ["accepted"]


@pytest.mark.asyncio
async def test_clicking_a_table_row_selects_it_and_emits_only_for_the_user() -> None:
    view = HorizontalMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    assert isinstance(view.tables.narrow.renderer, TextualWidgetRenderer)
    box = view.tables.narrow.renderer.widget
    assert isinstance(box, ComposeFilterTable)
    table = box.table
    emitted: list[list[int]] = []
    view.tables.narrow.selection_changed.connect(emitted.append)

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        assert not table.show_cursor  # nothing selected yet

        # the header, then the rows: South is the second
        await pilot.click(table, offset=(2, 2))
        await pilot.pause()
        assert table.show_cursor
        assert view.tables.narrow.selected_rows == [1]
        assert emitted == [[1]]

        await pilot.press("down")
        await pilot.pause()
        assert view.tables.narrow.selected_rows == [2]
        assert emitted == [[1], [2]]

        # set from code: shown, but not the user's doing
        view.tables.narrow.selected_rows = [0]
        await pilot.pause()
        assert table.cursor_row == 0
        # new rows still holding it, moved: the cursor follows it
        view.tables.narrow.rows = [["West"], ["North"]]
        await pilot.pause()
        assert (table.show_cursor, table.cursor_row) == (True, 1)
        view.tables.narrow.rows = [["West"]]
        await pilot.pause()
        assert not table.show_cursor
        assert emitted == [[1], [2]]


@pytest.mark.asyncio
async def test_a_click_or_enter_adds_or_removes_its_row_in_a_table_selecting_several() -> None:
    view = HorizontalMainView()
    table_view = view.tables.narrow
    table_view.selection_mode = SelectionMode.MULTIPLE
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    assert isinstance(table_view.renderer, TextualWidgetRenderer)
    box = table_view.renderer.widget
    assert isinstance(box, ComposeFilterTable)
    table = box.table
    emitted: list[list[int]] = []
    table_view.selection_changed.connect(emitted.append)

    def checked() -> list[str]:
        return [str(table.get_cell_at(Coordinate(row, 0))) for row in range(table.row_count)]

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        # the header, then the rows: South is the second
        await pilot.click(table, offset=(2, 2))
        await pilot.pause()
        # the cursor only moves: Enter adds its row
        await pilot.press("down", "enter")
        await pilot.pause()
        assert table_view.selected_rows == [1, 2]
        assert checked() == ["", "✓", "✓"]
        await pilot.click(table, offset=(2, 2))
        await pilot.pause()
        assert table_view.selected_rows == [2]
        assert emitted == [[1], [1, 2], [2]]

        # set from code: shown, but not the user's doing
        table_view.selected_rows = [0, 1]
        await pilot.pause()
        assert checked() == ["✓", "✓", ""]
        # new rows still holding one of them, moved: its check follows it
        table_view.rows = [["West"], ["North"]]
        await pilot.pause()
        assert checked() == ["", "✓"]
        assert emitted == [[1], [1, 2], [2]]


@pytest.mark.asyncio
async def test_f2_or_a_double_click_edits_a_row_s_editable_cells_keeping_the_selection() -> None:
    view = EditableTableMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    assert isinstance(view.places.renderer, TextualWidgetRenderer)
    box = view.places.renderer.widget
    assert isinstance(box, ComposeFilterTable)
    table = box.table
    edited: list[tuple[int, int, str, list[str]]] = []

    def record(row: int, column: int, text: str) -> None:
        # the row as it was: the edit is applied once the callbacks have run
        edited.append((row, column, text, view.places.rows[row]))

    view.places.cell_edited.connect(record)

    def cells() -> list[list[str]]:
        return [[str(cell) for cell in table.get_row_at(row)] for row in range(table.row_count)]

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        # the header, then the rows: the harbour's, short of its note, is the second
        await pilot.click(table, offset=(2, 2))
        await pilot.press("f2")
        await pilot.pause()
        assert isinstance(app.screen, ComposeRowEditor)
        assert app.focused is app.screen.inputs[1]  # the only editable cell, the note
        await pilot.press(*"Busy", "enter")
        await pilot.pause()
        assert view.places.rows == [["Lake", "Calm"], ["Harbour", "Busy"]]
        assert cells() == [["Lake", "Calm"], ["Harbour", "Busy"]]
        assert edited == [(1, 1, "Busy", ["Harbour"])]
        # its row moved nowhere: it stays selected
        assert view.places.selected_rows == [1]

        # the lake's note: past the place's cell, whose own double click edits nothing
        await pilot.double_click(table, offset=(2, 1))
        await pilot.pause()
        assert not isinstance(app.screen, ComposeRowEditor)
        place = next(iter(table.columns.values()))
        note = place.get_render_width(table) + 1
        await pilot.double_click(table, offset=(note, 1))
        await pilot.pause()
        assert isinstance(app.screen, ComposeRowEditor)
        # Escape leaves the row as it was
        await pilot.press("ctrl+a", *"Windy", "escape")
        await pilot.pause()
        assert not isinstance(app.screen, ComposeRowEditor)
        assert view.places.rows == [["Lake", "Calm"], ["Harbour", "Busy"]]
        assert edited == [(1, 1, "Busy", ["Harbour"])]

        # the app answers with its rows sorted by note: the cursor follows the lake
        def answer(row: int, column: int, text: str) -> None:
            rows = replace_cell(view.places.rows, row, column, text)
            view.places.rows = sorted(rows, key=lambda cells: cells[1])

        view.places.cell_edited.connect(answer)
        await pilot.double_click(table, offset=(note, 1))
        await pilot.press("end", *["backspace"] * len("Calm"), *"Windy", "enter")
        await pilot.pause()
        assert cells() == [["Harbour", "Busy"], ["Lake", "Windy"]]
        assert view.places.selected_rows == [1]
        assert table.cursor_row == 1


@pytest.mark.asyncio
async def test_a_table_s_cells_and_headers_look_as_the_view_says() -> None:
    view = StyledTablesMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None

    def table_of(table_view: TableView) -> ComposeTable:
        assert isinstance(table_view.renderer, TextualWidgetRenderer)
        box = table_view.renderer.widget
        assert isinstance(box, ComposeFilterTable)
        return box.table

    table, numbers = table_of(view.points), table_of(view.numbers)

    def x(column: int) -> int:
        return sum(each.get_render_width(table) for each in list(table.columns.values())[:column])

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        # the group's text over its first column's header
        labels = [str(column.label) for column in table.columns.values()]
        assert labels[1:4] == ["\nPoint", "Coordinates\nStandard space", "\nPhysical space"]
        assert table.header_height == 2
        # the group's cell shows its text once, in its first row
        rows = [table.get_row_at(row) for row in range(3)]
        assert [str(cells[0]) for cells in rows] == ["A", "", "B"]
        # NaN on red, its text white; a warning marked before its text; a disabled cell dim
        assert [str(span.style) for span in rows[1][2].spans] == ["#ffffff on #dc2626"]
        assert str(rows[2][3]) == "! 40.0"
        assert any("dim" in str(span.style) for span in rows[1][1].spans)
        # a click on a box toggles it, unless disabled
        await pilot.click(table, offset=(x(4) + 1, 2))
        await pilot.click(table, offset=(x(4) + 1, 3))
        await pilot.pause()
        assert [row[4] for row in view.points.rows] == ["False", "False", "True"]
        # the key/value table's keys head its rows
        assert [str(row.label) for row in numbers.rows.values()] == ["Number of calls", "Time (s)"]

        # new looks show at once, in place of the old ones
        view.points.cell_styles = {(0, 2): CellStyle(background="#dc2626")}
        view.numbers.row_headers = ["Calls", "Time (s)"]
        await pilot.pause()
        assert [str(span.style) for span in table.get_row_at(0)[2].spans] == ["#ffffff on #dc2626"]
        assert table.get_row_at(1)[2].spans == []
        assert [str(row.label) for row in numbers.rows.values()] == ["Calls", "Time (s)"]


@pytest.mark.asyncio
async def test_a_table_s_cell_widgets_edit_their_cells_or_report_their_clicks() -> None:
    view = CellWidgetsMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    assert isinstance(view.variables.renderer, TextualWidgetRenderer)
    box = view.variables.renderer.widget
    assert isinstance(box, ComposeFilterTable)
    table = box.table
    events: list[tuple[int, ...] | tuple[int, int, str]] = []
    view.variables.cell_edited.connect(lambda row, column, text: events.append((row, column, text)))
    view.variables.cell_clicked.connect(lambda row, column: events.append((row, column)))

    def x(column: int) -> int:
        """Get the offset of a column's first character."""
        return sum(each.get_render_width(table) for each in list(table.columns.values())[:column])

    def cells(row: int) -> list[str]:
        return [str(cell) for cell in table.get_row_at(row)]

    def header() -> str:
        return str(next(iter(table.columns.values())).label)

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        assert cells(0) == ["\u2611", "Length", "Input \u25be", "Normal [\u2026]", "doc"]
        assert header() == "\u25a3 Keep"  # some rows checked

        # a click toggles a box: the header's follows
        await pilot.click(table, offset=(x(0) + 1, 2))
        await pilot.pause()
        assert view.variables.rows[1][0] == "True"
        assert (cells(1)[0], header()) == ("\u2611", "\u2611 Keep")
        # the header's box unchecks every row, each an edit
        await pilot.click(table, offset=(x(0) + 1, 0))
        await pilot.pause()
        assert [row[0] for row in view.variables.rows] == ["False", "False"]
        assert header() == "\u2610 Keep"
        # Space toggles the cursor row's box
        await pilot.press("space")
        await pilot.pause()
        assert [row[0] for row in view.variables.rows] == ["False", "True"]

        # a combobox's click picks among its options
        await pilot.click(table, offset=(x(2) + 1, 1))
        await pilot.pause()
        assert isinstance(app.screen, ComposeOptionPicker)
        await pilot.press("down", "enter")
        await pilot.pause()
        assert view.variables.rows[0][2] == "Output"

        # a button and a link report their clicks, editing nothing
        await pilot.click(table, offset=(x(3) + 1, 2))
        await pilot.click(table, offset=(x(4) + 1, 1))
        await pilot.pause()
        assert events == [
            (1, 0, "True"),
            (0, 0, "False"),
            (1, 0, "False"),
            (1, 0, "True"),
            (0, 2, "Output"),
            (1, 3),
            (0, 4),
        ]


@pytest.mark.asyncio
async def test_a_refused_edit_leaves_its_cell_and_the_selection_as_they_were() -> None:
    view = EditableTableMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    assert isinstance(view.places.renderer, TextualWidgetRenderer)
    box = view.places.renderer.widget
    assert isinstance(box, ComposeFilterTable)
    table = box.table

    def refuse(_row: int, _column: int, _text: str) -> None:
        raise EditRefusedError

    view.places.cell_edited.connect(refuse)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await pilot.click(table, offset=(2, 1))  # the lake's row
        await pilot.press("f2", *"Windy", "enter")
        await pilot.pause()
        assert view.places.rows == [["Lake", "Calm"], ["Harbour"]]
        assert [str(cell) for cell in table.get_row_at(0)] == ["Lake", "Calm"]
        assert view.places.selected_rows == [0]


@pytest.mark.asyncio
async def test_a_combobox_emits_its_value_when_the_user_picks_it_not_when_code_sets_it() -> None:
    view = PipeMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    material = view.pages.inputs.pipe_form.material
    seen: list[object] = []
    material.value_changed.connect(seen.append)

    async with app.run_test() as pilot:
        await pilot.pause()
        material.values = dict(reversed(material.values.items()))
        material.value = Material.Copper
        await pilot.pause()
        assert seen == []

        combobox = _field_widget(material.renderer)
        assert isinstance(combobox, ComposeCombobox)
        combobox.value = Material.Steel  # what picking an option does
        await pilot.pause()
        assert seen == [Material.Steel]
        assert material.value is Material.Steel


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
        assert isinstance(combobox, ComposeCombobox)
        assert [str(prompt) for prompt, _ in combobox._options[1:]] == ["Petite", "Grande"]  # noqa: SLF001
        assert combobox.selection is Size.LARGE
        assert size.value is Size.LARGE
        assert seen == []


@pytest.mark.asyncio
async def test_the_language_menu_shortcut_relabels_the_widgets() -> None:
    view = PipeMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("ctrl+shift+f")
        await pilot.pause()

        assert view.language == "fr"
        assert app.title == "Formulaire de conduite"
        main_pipe = view.pages.inputs.pipe_form.main_pipe.renderer
        assert isinstance(main_pipe, TextualWidgetRenderer)
        assert main_pipe.widget is not None
        assert main_pipe.widget.border_title == "Conduite principale"


@pytest.mark.asyncio
async def test_the_chart_draws_its_titles_and_series() -> None:
    view = PipeChartMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    assert isinstance(view.chart.renderer, TextualWidgetRenderer)
    chart = view.chart.renderer.widget
    assert isinstance(chart, ComposeChart)

    async with app.run_test(size=(120, 60)) as pilot:
        await pilot.pause()
        view.add_curve()
        view.chart.series = [
            *view.chart.series,
            Series(name="Measured", x=[0.5, 1, 1.5], y=[1, math.nan, 3]),
        ]
        await pilot.pause()
        text = chart.render().plain  # type: ignore[union-attr]
        assert "Pressure Drop" in text
        assert "Flow Rate (L/s)" in text
        assert "Pressure Drop (kPa)" in text
        assert "D = 50 mm" in text
        assert "Measured" in text
        view.chart.x_unit = "m3/h"
        view.chart.series = []
        await pilot.pause()
        text = chart.render().plain  # type: ignore[union-attr]
        assert "Flow Rate (m3/h)" in text
        assert "D = 50 mm" not in text


@pytest.mark.asyncio
async def test_a_scatter_series_is_plotted_as_dots() -> None:
    view = PipeChartMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    assert isinstance(view.chart.renderer, TextualWidgetRenderer)
    chart = view.chart.renderer.widget
    assert isinstance(chart, ComposeChart)

    async with app.run_test(size=(120, 60)) as pilot:
        await pilot.pause()
        view.add_curve()
        view.add_measurements()
        await pilot.pause()
        plotted = chart.plt._active.monitor  # what plotext was given  # noqa: SLF001
        assert plotted.label == ["D = 50 mm", "Measured, D = 50 mm"]
        assert plotted.lines == [True, False]  # a line, then dots
        assert len(plotted.x[1]) == len(MEASUREMENTS)
        view.chart.kind = ChartKind.SCATTER
        await pilot.pause()
        assert chart.plt._active.monitor.lines == [False, False]  # noqa: SLF001


@pytest.mark.asyncio
async def test_a_bar_chart_plots_a_bar_per_series_in_each_category() -> None:
    view = ChartPagesMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    energy = view.router.chart.energy
    assert isinstance(energy.renderer, TextualWidgetRenderer)
    chart = energy.renderer.widget
    assert isinstance(chart, ComposeChart)

    async with app.run_test(size=(120, 60)) as pilot:
        view.router.current_route = "chart"
        await pilot.pause()
        text = chart.render().plain  # type: ignore[union-attr]
        for name in ("Heating", "Cooling", "Kitchen", "Bedroom", "Office", "Energy"):
            assert name in text
        assert "120" in text  # the tallest bar's height, on the y axis


@pytest.mark.asyncio
async def test_a_log_axis_plots_what_it_can_show() -> None:
    view = ChartPagesMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    page = view.router.chart
    assert isinstance(page.chart.renderer, TextualWidgetRenderer)
    chart = page.chart.renderer.widget
    assert isinstance(chart, ComposeChart)
    assert isinstance(page.energy.renderer, TextualWidgetRenderer)
    energy = page.energy.renderer.widget
    assert isinstance(energy, ComposeChart)

    async with app.run_test(size=(120, 60)) as pilot:
        view.router.current_route = "chart"
        page.chart.series = [Series(name="Decay", x=[0, 1, 10, 100], y=[5, -1, 10, 100])]
        page.chart.x_log = page.chart.y_log = True
        page.energy.series = [Series(name="Heating", x=[0, 1, 2], y=[1000, 0, 50])]
        page.energy.y_log = True
        await pilot.pause()
        plotted = chart.plt._active.monitor  # what plotext was given  # noqa: SLF001
        # the scales of the axes at the bottom and left, those drawn
        assert (plotted.xscale[0], plotted.yscale[0]) == ("log", "log")
        assert list(plotted.x[0]) == [0, 1, 2]  # 1, 10 and 100, as their logs: no x of 0
        assert math.isnan(plotted.y[0][0])  # a y of -1: a gap
        text = energy.render().plain  # type: ignore[union-attr]
        assert "1000" in text  # its axis, log from 10
        assert energy.plt._active.monitor.yscale[0] == "log"  # noqa: SLF001


@pytest.mark.asyncio
async def test_reference_lines_are_plotted_labeled() -> None:
    view = ChartPagesMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    page = view.router.chart
    assert isinstance(page.chart.renderer, TextualWidgetRenderer)
    chart = page.chart.renderer.widget
    assert isinstance(chart, ComposeChart)
    assert isinstance(page.energy.renderer, TextualWidgetRenderer)
    energy = page.energy.renderer.widget
    assert isinstance(energy, ComposeChart)

    async with app.run_test(size=(120, 60)) as pilot:
        view.router.current_route = "chart"
        page.energy.reference_lines = [ReferenceLine(1, "Mine", vertical=True)]
        await pilot.pause()
        text = chart.render().plain  # type: ignore[union-attr]
        assert "Max: 4.6" in text
        assert "Now" in text
        plotted = chart.plt._active.monitor  # what plotext was given  # noqa: SLF001
        assert (plotted.hcoord[0], plotted.vcoord[0]) == ([4.6, 0.6], [2.3])
        assert plotted.hcolors[0] == [(208, 48, 48), (32, 128, 64)]  # their own colors
        assert "Mine" in energy.render().plain  # type: ignore[union-attr]
        # on the bedroom's bars: plotext draws the categories from 1
        assert energy.plt._active.monitor.vcoord[0] == [2]  # noqa: SLF001


@pytest.mark.asyncio
async def test_a_step_series_is_plotted_in_steps() -> None:
    view = ChartPagesMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    jobs = view.router.chart.jobs
    assert isinstance(jobs.renderer, TextualWidgetRenderer)
    chart = jobs.renderer.widget
    assert isinstance(chart, ComposeChart)

    async with app.run_test(size=(120, 60)) as pilot:
        view.router.current_route = "chart"
        await pilot.pause()
        chart.render()
        plotted = chart.plt._active.monitor  # what plotext was given  # noqa: SLF001
        # each count held until the next change
        assert list(plotted.x[0]) == [0, 2, 2, 5, 5, 6, 6]
        assert list(plotted.y[0]) == [1, 1, 3, 3, 2, 2, 4]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("picked", "saved"),
    [
        ("drop", ["drop.pdf"]),  # PDF unless named
        ("drop.png", ["drop.png"]),
        (None, []),  # cancelled
    ],
)
async def test_its_key_saves_the_chart_s_image(
    picked: str | None, saved: list[str], tmp_path: Path
) -> None:
    pytest.importorskip("matplotlib")
    view = PipeChartMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    assert isinstance(view.chart.renderer, TextualWidgetRenderer)
    chart = view.chart.renderer.widget
    assert isinstance(chart, ComposeChart)

    async with app.run_test(size=(120, 60)) as pilot:
        view.add_curve()
        chart.focus()
        await pilot.pause()
        footer = [binding.description for (_, binding, *_rest) in app.active_bindings.values()]
        assert "Save Image" in footer

        await pilot.press("s")
        await pilot.pause()
        assert [type(screen).__name__ for screen in app.screen_stack] == ["Screen", "FileSave"]
        # as the dialog's Save button does, or Cancel
        app.screen.dismiss(None if picked is None else tmp_path / picked)
        await pilot.pause()

    assert _names(tmp_path) == saved


@pytest.mark.asyncio
async def test_without_matplotlib_the_chart_has_no_key_saving_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(chartimage, "is_available", lambda: False)
    view = PipeChartMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    assert isinstance(view.chart.renderer, TextualWidgetRenderer)
    chart = view.chart.renderer.widget
    assert isinstance(chart, ComposeChart)

    async with app.run_test(size=(120, 60)) as pilot:
        chart.focus()
        await pilot.press("s")
        await pilot.pause()
        assert len(app.screen_stack) == 1


@pytest.mark.asyncio
async def test_a_series_of_its_own_color_is_plotted_so_filled() -> None:
    view = BatmanMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    assert isinstance(view.chart.renderer, TextualWidgetRenderer)
    chart = view.chart.renderer.widget
    assert isinstance(chart, ComposeChart)

    async with app.run_test(size=(120, 60)) as pilot:
        await pilot.pause()
        plotted = chart.plt._active.monitor  # what plotext was given  # noqa: SLF001
        assert [colors[0] for colors in plotted.color] == [(255, 215, 0)] * 2 + [(0, 0, 0)] * 2
        assert plotted.fillx == [0] * 4  # filled down to 0; an unfilled one is False


@pytest.mark.asyncio
async def test_the_chart_is_as_tall_as_its_view_says_in_rows() -> None:
    view = PipeChartMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    assert isinstance(view.chart.renderer, TextualWidgetRenderer)
    chart = view.chart.renderer.widget
    assert isinstance(chart, ComposeChart)

    async with app.run_test(size=(120, 80)) as pilot:
        await pilot.pause()
        assert chart.size.height == 20  # its own CSS's
        view.chart.height = 480
        await pilot.pause()
        assert chart.size.height == 30  # rows of about 16 pixels
        view.chart.height = 10
        await pilot.pause()
        assert chart.size.height == 5  # enough for its axes still
        view.chart.height = None
        await pilot.pause()
        assert chart.size.height == 20


def _sorted_rooms(
    view: Optional[SortedRoomsMainView] = None,
) -> tuple[SortedRoomsMainView, App[Any], ComposeFilterTable]:
    """Render the rooms (`view`, or new ones): set them up before, the app not yet running."""
    view = SortedRoomsMainView() if view is None else view
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    assert isinstance(view.rooms.renderer, TextualWidgetRenderer)
    box = view.rooms.renderer.widget
    assert isinstance(box, ComposeFilterTable)
    return view, app, box


def _names(directory: Path) -> list[str]:
    """Get the names of the files in `directory`: an async test can't list it itself."""
    return sorted(path.name for path in directory.iterdir())


def _shown_column(table: ComposeTable, column: int) -> list[str]:
    return [str(table.get_row_at(row)[column]) for row in range(table.row_count)]


@pytest.mark.asyncio
async def test_clicking_a_sortable_header_sorts_by_it_then_back_and_marks_the_order() -> None:
    view, app, box = _sorted_rooms()
    table = box.table

    async with app.run_test(size=(160, 40)) as pilot:
        await pilot.pause()

        async def click_header(column: int) -> None:
            x = sum(c.get_render_width(table) for c in list(table.columns.values())[:column])
            await pilot.click(table, offset=(x + 1, 0))
            await pilot.pause()

        await click_header(2)  # the occupants
        assert _shown_column(table, 2) == ["2", "9", "10", ""]
        assert str(list(table.columns.values())[2].label) == "Occupants ▲"
        await click_header(2)
        assert _shown_column(table, 2) == ["10", "9", "2", ""]
        assert str(list(table.columns.values())[2].label) == "Occupants ▼"
        await click_header(2)
        assert view.rooms.sort_column is None
        assert _shown_column(table, 0) == ["Hall", "kitchen", "Attic", "Bedroom"]
        assert str(list(table.columns.values())[2].label) == "Occupants"

        # a table sorting and filtering by no column: no bar
        assert isinstance(view.notes.renderer, TextualWidgetRenderer)
        notes = view.notes.renderer.widget
        assert isinstance(notes, ComposeFilterTable)
        assert not notes.bar.display
        assert box.bar.display


async def _add_filter(pilot: Pilot[Any], bar: ComposeFilterBar, option: int, text: str) -> None:
    """Add a filter through the bar's editor, on the column at `option` in its picker."""
    if not bar.is_editing():
        await pilot.click(bar.add_filter)
        await pilot.pause()
    # the column picker's options: a blank one, then the columns
    await pilot.click(bar.column)
    await pilot.pause()
    await pilot.press("home", *["down"] * (option + 1), "enter")
    await pilot.click(bar.value)
    await pilot.press("end", *["backspace"] * len(bar.value.value), *text, "enter")
    await pilot.pause()


@pytest.mark.asyncio
async def test_the_filter_bar_searches_and_adds_filters_shown_as_chips() -> None:
    view, app, box = _sorted_rooms()
    bar, table = box.bar, box.table

    async with app.run_test(size=(160, 40)) as pilot:
        await pilot.pause()
        await pilot.click(bar.search)
        await pilot.press(*"ROOM")
        await pilot.pause()
        assert view.rooms.search == ""  # once the user stops typing: one search, not four
        await pilot.pause(SEARCH_DELAY_MS / 1000 * 2)
        assert _shown_column(table, 0) == ["Bedroom"]
        assert str(bar.count.render()) == "1 of 4"
        await pilot.press(*["backspace"] * 4)
        await pilot.pause()
        assert table.row_count == 4
        assert not bar.count.display

        # a value that doesn't parse isn't added: the field says why, the editor stays
        await _add_filter(pilot, bar, 1, "warm")  # the temperature
        assert bar.is_editing()
        assert bar.value.has_class("-invalid")
        assert str(bar.value.tooltip) == '"warm" isn\'t a number'
        assert bar.value.placeholder == ">=20, 18..24"
        await _add_filter(pilot, bar, 1, ">=20")
        assert not bar.is_editing()
        assert _shown_column(table, 0) == ["kitchen", "Bedroom"]
        (chip,) = bar.chips.query(ComposeFilterChip)
        assert str(chip.open_button.label) == "Temperature: >=20 \u270e"
        assert str(chip.open_button.tooltip) == "Edit the filter on Temperature"
        # its chip has the focus: Enter opens it again, to replace the filter on its
        # column; another column's combines
        assert app.focused is chip.open_button
        await pilot.press("enter")
        await pilot.pause()
        assert bar.value.value == ">=20"
        await _add_filter(pilot, bar, 1, ">=21")
        await _add_filter(pilot, bar, 3, "true")  # heated
        assert view.rooms.filters == {1: ">=21", 3: "true"}
        assert _shown_column(table, 0) == ["Bedroom"]

        chips = list(bar.chips.query(ComposeFilterChip))
        await pilot.click(chips[0].remove_button)
        await pilot.pause()
        assert view.rooms.filters == {3: "true"}
        await _add_filter(pilot, bar, 2, ">100")  # occupants
        assert table.row_count == 0
        assert box.empty.display
        assert str(box.empty.render()) == "No rows match the filters"
        # Escape closes the editor, adding nothing
        await pilot.click(bar.add_filter)
        await pilot.pause()
        await pilot.press(*"=", "escape")
        await pilot.pause()
        assert not bar.is_editing()
        assert view.rooms.filters == {2: ">100", 3: "true"}


@pytest.mark.asyncio
async def test_the_filter_editor_s_toggle_makes_the_value_a_regular_expression() -> None:
    view, app, box = _sorted_rooms()
    bar, table = box.bar, box.table

    async with app.run_test(size=(160, 40)) as pilot:
        await pilot.pause()
        await pilot.click(bar.add_filter)
        await pilot.pause()
        # only for text, the first column: a number column takes comparisons
        assert bar.pattern.display
        await pilot.click(bar.pattern)
        await pilot.pause()
        assert bar.value.placeholder == "a regular expression, as Room [1-3]"
        await pilot.click(bar.value)
        await pilot.press(*"^(hall|attic)$", "enter")
        await pilot.pause()
        assert _shown_column(table, 0) == ["Hall", "Attic"]
        (chip,) = bar.chips.query(ComposeFilterChip)
        assert str(chip.open_button.label) == "Room matches ^(hall|attic)$ \u270e"

        # reopened, the toggle is on and the value the pattern as typed
        await pilot.press("enter")
        await pilot.pause()
        assert bar.is_pattern()
        assert bar.value.value == "^(hall|attic)$"
        await _add_filter(pilot, bar, 1, ">=20")  # the temperature
        assert not bar.pattern.display
        assert view.rooms.filters == {0: "/^(hall|attic)$/", 1: ">=20"}


@pytest.mark.asyncio
async def test_a_click_and_an_edit_on_a_sorted_filtered_table_reach_their_rows() -> None:
    view = SortedRoomsMainView()
    rooms = view.rooms
    rooms.filters = {3: "true"}
    rooms.sort_by(0)
    rooms.sort_by(0)  # descending: the kitchen, then the bedroom
    view, app, box = _sorted_rooms(view)
    table = box.table
    emitted: list[list[int]] = []
    rooms.selection_changed.connect(emitted.append)
    edited: list[tuple[Room, Room]] = []
    rooms.record_edited.connect(lambda old, new: edited.append((old, new)))

    async with app.run_test(size=(160, 40)) as pilot:
        await pilot.pause()
        # the header, then the rows: the bedroom is the second
        await pilot.click(table, offset=(2, 2))
        await pilot.pause()
        assert rooms.selected_records == [Room("Bedroom", 21, 9, is_heated=True)]
        assert emitted == [[3]]

        # renamed, the bedroom sorts first and stays selected
        await pilot.press("f2")
        await pilot.pause()
        await pilot.press("end", *["backspace"] * len("Bedroom"), *"Study", "enter")
        await pilot.pause()
        assert edited == [
            (Room("Bedroom", 21, 9, is_heated=True), Room("Study", 21, 9, is_heated=True))
        ]
        assert _shown_column(table, 0) == ["Study", "kitchen"]
        assert rooms.selected_rows == [3]
        assert table.cursor_row == 0


@pytest.mark.asyncio
async def test_a_large_table_draws_the_lines_on_screen_reading_only_their_windows() -> None:
    view = MillionRowsMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    source = view.table.source
    assert isinstance(source, MillionSource)

    async with app.run_test(size=(80, 30)) as pilot:
        table = app.query_one(ComposeDataTable)
        assert table.virtual_size.height == 1_000_001  # the headers' line, then the rows'
        assert table.render_line(0).text.split() == ["Value", "Half"]
        assert table.render_line(2).text.split() == ["2", "2", "0.5"]
        table.scroll_to(y=500_000, animate=False)
        await pilot.pause()
        assert table.render_line(1).text.split() == ["500,001", "1000000", "250000.0"]
        assert table.render_line(0).text.split() == ["Value", "Half"]  # still on top
        assert len(source.read) < 10 * DATA_TABLE_WINDOW

        source.size = 3
        source.changed.emit()
        await pilot.pause()
        assert table.virtual_size.height == 4


@pytest.mark.asyncio
async def test_a_large_table_s_header_clicks_sort_by_its_column_marking_the_order() -> None:
    view = MillionRowsMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None

    async with app.run_test(size=(80, 30)) as pilot:
        table = app.query_one(ComposeDataTable)
        # the positions take "1,000,000 ", the two columns share the 70 cells left
        half = (len("1,000,000 ") + 35 + 2, 0)
        await pilot.click(ComposeDataTable, offset=half)
        assert (view.table.sort_column, view.table.sort_descending) == ("half", False)
        assert table.render_line(0).text.split() == ["Value", "Half", "▲"]
        await pilot.click(ComposeDataTable, offset=half)
        assert table.render_line(0).text.split() == ["Value", "Half", "▼"]
        await pilot.click(ComposeDataTable, offset=(3, 0))  # over the positions: nothing
        await pilot.click(ComposeDataTable, offset=(15, 2))  # on a row: nothing
        assert view.table.sort_column == "half"


@pytest.mark.asyncio
async def test_a_large_table_s_cursor_and_clicks_select_its_rows_and_activate_one() -> None:
    view = MillionRowsMainView()
    view.table.selection_mode = SelectionMode.MULTIPLE
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    activated: list[Any] = []
    view.table.row_activated.connect(activated.append)

    async with app.run_test(size=(80, 30)) as pilot:
        table = app.query_one(ComposeDataTable)
        table.focus()
        await pilot.press("down", "down", "space", "down", "down", "shift+space", "enter")
        assert view.table.selected_ids == [2, 3, 4]
        assert activated == [4]

        await pilot.click(ComposeDataTable, offset=(15, 1))  # the first row's line
        await pilot.click(ComposeDataTable, offset=(15, 3))  # the selected third: off
        await pilot.double_click(ComposeDataTable, offset=(15, 7))
        assert view.table.selected_ids == [3, 4, 0, 6]
        assert activated == [4, 6]

        await pilot.press("end")
        assert table.cursor == 999_999
        last = table.scrollable_content_region.height - 1
        assert table.render_line(last).text.split()[0] == "1,000,000"
        await pilot.press("home")  # back up: scrolled to the first row
        assert table.render_line(1).text.split()[0] == "1"


@pytest.mark.asyncio
async def test_a_large_table_s_bar_searches_and_filters_its_columns_by_name() -> None:
    view = RoomsDataMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None

    async with app.run_test(size=(160, 40)) as pilot:
        await pilot.pause()
        box = app.query_one(ComposeDataFilterTable)
        bar = box.bar
        assert bar.display
        await pilot.click(bar.search)
        await pilot.press(*"room", "enter")  # searches at once
        await pilot.pause()
        assert (view.rooms.search, view.rooms.row_count) == ("room", 1)
        assert str(bar.count.render()) == "1 of 3"
        await pilot.press(*["backspace"] * 4)
        await pilot.pause()

        await _add_filter(pilot, bar, 1, "warm")  # the temperature: by the column's name
        assert str(bar.value.tooltip) == '"warm" isn\'t a number'
        await _add_filter(pilot, bar, 1, ">19")
        assert view.rooms.filters == {"temperature": ">19"}
        assert view.rooms.row_count == 2
        (chip,) = bar.chips.query(ComposeFilterChip)
        assert str(chip.open_button.label) == "Temperature: >19 \u270e"

        view.rooms.filters = {"temperature": ">30"}
        await pilot.pause()
        assert box.empty.display
        (chip,) = bar.chips.query(ComposeFilterChip)
        await pilot.click(chip.remove_button)
        await pilot.pause()
        assert (view.rooms.filters, view.rooms.row_count, box.empty.display) == ({}, 3, False)


@pytest.mark.asyncio
async def test_ctrl_c_copies_a_large_table_s_selected_rows_to_the_clipboard() -> None:
    view = MillionRowsMainView()
    view.table.selection_mode = SelectionMode.MULTIPLE
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None

    async with app.run_test(size=(80, 30)) as pilot:
        app.query_one(ComposeDataTable).focus()
        await pilot.press("down", "space", "down", "down", "space", "ctrl+c")
        await pilot.pause()
        # the value, then its half
        assert app.clipboard == "2\t0.5\n6\t1.5"


@pytest.mark.asyncio
async def test_a_large_source_s_rows_show_loading_while_a_job_orders_them() -> None:
    view = GatedMainView()
    view.render(RendererType.TEXTUAL)
    _add_reference_to_signals(view, None)  # as the app does: the table finds the jobs
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    source = view.table.source
    assert isinstance(source, GatedSource)

    async with app.run_test(size=(80, 30)) as pilot:
        table = app.query_one(ComposeDataTable)
        source.gate.clear()
        view.table.sort_by("value")
        view.table.sort_by("value")  # descending, while the job orders
        await pilot.pause()
        assert table.loading

        source.gate.set()
        for _ in range(100):
            await pilot.pause(0.05)
            if not view.table.is_ordering:
                break
        assert not table.loading
        assert view.table.rows(0, 1) == [(source.size - 1, [str(source.size - 1)])]


@pytest.mark.asyncio
async def test_a_large_table_s_cell_shows_on_its_row_s_line_its_breaks_as_spaces() -> None:
    view = RoomsDataMainView()
    view.rooms.source = ListSource(
        Room, {"name": T("Room"), "temperature": T("Temperature")}, [Room("Hall\tway\nB", 18.0)]
    )
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        line = app.query_one(ComposeDataTable).render_line(1).text

    assert "Hall way B" in line
    assert line.split() == ["1", "Hall", "way", "B", "18.0"]


@pytest.mark.asyncio
@pytest.mark.parametrize("is_cancelled", [False, True])
async def test_a_large_table_s_key_exports_its_rows_as_csv(
    is_cancelled: bool,
    tmp_path: Path,
) -> None:
    view = RoomsDataMainView()
    view.rooms.sort_column = "temperature"
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None

    async with app.run_test(size=(80, 30)) as pilot:
        app.query_one(ComposeDataTable).focus()
        await pilot.pause()
        footer = [binding.description for (_, binding, *_rest) in app.active_bindings.values()]
        assert "Export CSV" in footer

        await pilot.press("e")
        await pilot.pause()
        assert [type(screen).__name__ for screen in app.screen_stack] == ["Screen", "FileSave"]
        # as the dialog's Save button does, or Cancel
        app.screen.dismiss(None if is_cancelled else tmp_path / "rooms")
        await pilot.pause()

    if is_cancelled:
        assert _names(tmp_path) == []
        return
    assert (tmp_path / "rooms.csv").read_text(encoding="utf-8").splitlines() == [
        "Room,Temperature,Occupants",
        "Hall,18.0,",
        "Bedroom,19.5,1",
        "Kitchen,21.5,2",
    ]


def _widget(view: View) -> Widget:
    assert isinstance(view.renderer, TextualWidgetRenderer)
    assert view.renderer.widget is not None
    return view.renderer.widget


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


@pytest.mark.asyncio
async def test_an_action_s_shortcut_icon_and_data_change_while_the_app_runs() -> None:
    view = DialogsMainView()
    clear = view.edit_menu.clear  # Ctrl+L opens the confirmation
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None

    async def opens(key: str) -> bool:
        await pilot.press(key)
        await pilot.pause()
        is_open = isinstance(app.screen, ComposeDialog)
        if is_open:
            await pilot.press("escape")
            await pilot.pause()
        return is_open

    async with app.run_test() as pilot:
        await pilot.pause()
        clear.icon = "clear.svg"  # nothing shows it, nor the data
        clear.data = "names"
        clear.shortcut = "Ctrl+k"
        await pilot.pause()
        assert [await opens("ctrl+l"), await opens("ctrl+k")] == [False, True]
        clear.shortcut = None
        await pilot.pause()
        assert not await opens("ctrl+k")
        clear.shortcut = "Ctrl+j"  # an action bound to no key at first gets one
        await pilot.pause()
        assert await opens("ctrl+j")


@pytest.mark.asyncio
async def test_a_check_all_box_leaves_its_column_once_a_plain_one() -> None:
    view = CellWidgetsMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    assert isinstance(view.variables.renderer, TextualWidgetRenderer)
    box = view.variables.renderer.widget
    assert isinstance(box, ComposeFilterTable)

    def header() -> str:
        return str(next(iter(box.table.columns.values())).label)

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        boxed = header()
        view.variables.cell_widgets = {2: CellWidget.combobox(["Input", "Output"])}
        await pilot.pause()

        assert (boxed, header()) == ("▣ Keep", "Keep")


def _app_of(view: MainView) -> App[Any]:
    """Render `view` on Textual, and get the app that shows it, not running yet."""
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    return app


@pytest.mark.asyncio
async def test_a_dialog_opened_before_the_app_runs_shows_and_its_cancel_rejects() -> None:
    view = DialogsMainView()
    app = _app_of(view)
    view.confirm_clear.open()  # rendered, the app not running yet
    answers: list[str] = []
    view.confirm_clear.rejected.connect(lambda: answers.append("rejected"))

    async with app.run_test() as pilot:
        await pilot.pause()
        shown = isinstance(app.screen, ComposeDialog)
        await pilot.click("#reject")
        await pilot.pause()

        assert shown
        assert answers == ["rejected"]
        assert view.name.text == "Ada"


@pytest.mark.asyncio
async def test_a_dialog_the_app_closes_under_another_screen_is_left_unanswered() -> None:
    view = DialogsMainView()
    app = _app_of(view)
    answers: list[str] = []
    view.confirm_clear.accepted.connect(lambda: answers.append("accepted"))
    view.confirm_clear.rejected.connect(lambda: answers.append("rejected"))

    async with app.run_test() as pilot:
        view.confirm_clear.open()
        await pilot.pause()
        app.push_screen(Screen())  # e.g. a file picker over it
        await pilot.pause()
        view.confirm_clear.is_visible = False
        await pilot.pause()
        app.pop_screen()
        await pilot.pause()

        assert not any(isinstance(screen, ComposeDialog) for screen in app.screen_stack)
        assert answers == []


@pytest.mark.asyncio
async def test_a_form_dialog_opened_before_the_app_runs_shows_once_it_does() -> None:
    view = EditedPipeMainView()
    app = _app_of(view)
    view.edit_dialog.open()

    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.pause()

        assert isinstance(app.screen, ComposeFormDialog)


@pytest.mark.asyncio
async def test_save_file_action_saves_under_the_extension_the_name_lacks(tmp_path: Path) -> None:
    view = PipeMainView()
    view.pages.inputs.pipe_form.name.text = "saved_name"
    _add_reference_to_signals(view, None)
    app = _app_of(view)
    typed = tmp_path / "out"  # no extension: the renderer adds the study's

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("ctrl+s")
        await pilot.pause()
        await pilot.pause()
        file_input = app.screen.query_one(Input)
        file_input.focus()
        file_input.value = str(typed)
        await pilot.pause()
        await pilot.press("enter")
        for _ in range(3):
            await pilot.pause()

        assert len(app.screen_stack) == 1  # modal closed
        assert view.file_view.filepath == typed.with_suffix(".pipe")
        assert "saved_name" in typed.with_suffix(".pipe").read_text()


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


@pytest.mark.asyncio
async def test_a_header_s_click_sorts_or_checks_only_a_column_that_allows_it() -> None:
    rooms, rooms_app, rooms_box = _sorted_rooms()
    rooms.rooms.sortable_columns = [2]
    async with rooms_app.run_test(size=(160, 40)) as pilot:
        await pilot.pause()
        await pilot.click(rooms_box.table, offset=(1, 0))  # the room's
        await pilot.pause()
        assert rooms.rooms.sort_column is None

    view = CellWidgetsMainView()
    view.variables.editable_columns = []
    app = _app_of(view)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await pilot.click(_widget(view.variables), offset=(1, 0))  # the box
        await pilot.pause()
        assert [row[0] for row in view.variables.rows] == ["True", "false"]


@pytest.mark.asyncio
async def test_the_filter_bar_clears_its_filters_and_shows_a_search_set_in_code() -> None:
    view = SortedRoomsMainView()
    view.rooms.filters = {1: ">=20", 3: "true"}  # the bar clears two or more
    view, app, box = _sorted_rooms(view)

    async with app.run_test(size=(160, 40)) as pilot:
        await pilot.pause()
        await pilot.click(box.bar.clear)
        await pilot.pause()
        view.rooms.search = "kit"
        await pilot.pause()

        assert view.rooms.filters == {}
        assert box.bar.search.value == "kit"


@pytest.mark.asyncio
async def test_a_view_textual_doesn_t_render_is_left_out_of_its_container() -> None:
    view = PartialMainView()
    app = _app_of(view)

    async with app.run_test(size=(120, 60)) as pilot:
        await pilot.pause()
        item = LabelView()
        view.items.item_views = [UnregisteredView(), item]
        await pilot.pause()

        for container in (view.row, view.column, view.grid, view.splitter, view.page):
            assert container.skipped.renderer is None
            assert _widget(container) in _widget(container.shown).ancestors
        assert _widget(view.expander.shown).parent is not None
        assert _widget(view.shown).is_attached
        assert _widget(view.items) in _widget(item).ancestors
        assert len(_widget(view.toolbar).query(ComposeToolbarButton)) == 1


@pytest.mark.asyncio
async def test_a_list_s_records_set_before_the_app_runs_show_once_it_does() -> None:
    view = PipesMainView()
    _add_reference_to_signals(view, None)
    app = _app_of(view)
    view.pipes.items = PIPES[:1]  # rendered, the app not running yet
    column = _widget(view.pipes)

    def shown() -> list[str]:
        return [
            str(child.title) for child in column.children if isinstance(child, ComposeCollapsible)
        ]

    async with app.run_test(size=(80, 40)) as pilot:
        await pilot.pause()
        first = shown()
        view.pipes.items = []
        await pilot.pause()
        view.pipes.items = PIPES[1:2]  # into an empty list
        await pilot.pause()

        assert first == ["Main line"]
        assert shown() == ["Return"]


@pytest.mark.asyncio
async def test_tabs_start_on_the_tab_their_view_says_unreported() -> None:
    view = TabsMainView()
    view.tabs.current_index = 1  # e.g. by the app's setup, before rendering
    picks: list[int] = []
    view.tabs.current_changed.connect(picks.append)
    app = _app_of(view)
    tabbed = _widget(view.tabs)
    assert isinstance(tabbed, ComposeTabbedContent)

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        assert tabbed.active_pane is _widget(view.tabs.history)
        assert (view.tabs.current_index, picks) == (1, [])


@pytest.mark.asyncio
async def test_tabs_changed_before_the_app_runs_show_so_once_it_does() -> None:
    view = TabsMainView()
    app = _app_of(view)
    tabs = view.tabs
    tabbed = _widget(tabs)
    assert isinstance(tabbed, ComposeTabbedContent)
    history, notes = _widget(tabs.history), _widget(tabs.notes)
    assert isinstance(history, TabPane)
    assert isinstance(notes, TabPane)
    tabs.history.title = "Changes"
    tabs.notes.is_visible = False

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        assert str(tabbed.get_tab(history).label) == "Changes"
        assert not tabbed.get_tab(notes).display


@define_view
class _TwinShortcutsMainView(MainView):
    """Two actions sharing a key: an app's own mistake, or a key given back and forth."""

    app_title = "Twins"
    extension = ".twins"

    first: ActionView = Factory(lambda: ActionView(text="First", shortcut="Ctrl+e"))
    second: ActionView = Factory(lambda: ActionView(text="Second", shortcut="Ctrl+e"))


@pytest.mark.asyncio
async def test_a_key_moved_off_an_action_still_runs_the_other_bound_to_it() -> None:
    view = _TwinShortcutsMainView()
    app = _app_of(view)
    triggered: list[str] = []
    view.first.triggered.connect(lambda: triggered.append("first"))
    view.second.triggered.connect(lambda: triggered.append("second"))

    async with app.run_test() as pilot:
        await pilot.pause()
        view.first.shortcut = "Ctrl+r"
        await pilot.pause()
        await pilot.press("ctrl+e")
        await pilot.pause()

        assert triggered == ["second"]


def _textual_widgets_of(view: View) -> list[object]:
    """Get the widgets of `view` and of its children, depth first."""
    renderer = view.renderer
    if isinstance(renderer, RendererContainer):
        widgets: list[object] = [part.widget for part in renderer.renderers]  # type: ignore[attr-defined]
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
        CellWidgetsMainView,
        RoomsDataMainView,
        HelpMainView,
        JobsMainView,
        BookingMainView,
        DataFileMainView,
        EditedPipeMainView,
        HoursMainView,
        WorkersMainView,
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


@pytest.mark.asyncio
async def test_ctrl_q_quits_through_the_exit_action() -> None:
    view = HelpMainView()
    _add_reference_to_signals(view, None)
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    exits: list[None] = []
    view.file_menu.exit_app.triggered.connect(lambda: exits.append(None))

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("ctrl+q")
        await pilot.pause()

    assert exits == [None]
    assert app.return_code == 0


@pytest.mark.asyncio
async def test_ctrl_q_cancels_the_jobs_of_an_app_without_a_file_menu() -> None:
    view = HelpViewerMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None

    async with app.run_test() as pilot:
        await pilot.pause()
        job = view.jobs.start(lambda job: job.sleep(10))
        await pilot.press("ctrl+q")
        await pilot.pause()

    assert job.is_canceled
    assert app.return_code == 0


@pytest.mark.asyncio
async def test_a_tab_picked_in_code_before_its_tabs_mount_shows_once_they_do() -> None:
    view = TabsMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    assert isinstance(view.tabs.renderer, TextualWidgetRenderer)
    tabbed = view.tabs.renderer.widget
    assert isinstance(tabbed, ComposeTabbedContent)
    assert isinstance(view.tabs.history.renderer, TextualWidgetRenderer)
    history = view.tabs.history.renderer.widget
    picks: list[int] = []
    view.tabs.current_changed.connect(picks.append)
    view.tabs.current_index = 1  # e.g. tabs in a dialog's form, its screen not shown yet

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        assert tabbed.active_pane is history
        assert (view.tabs.current_index, picks) == (1, [])


@pytest.mark.asyncio
async def test_a_tree_reports_a_node_selected_once_and_its_collapse() -> None:
    view = SiteMainView()
    app = _app_of(view)
    site = view.site
    tree = _widget(site)
    selections: list[tuple[str, ...]] = []
    toggles: list[tuple[tuple[str, ...], bool]] = []
    site.selection_changed.connect(selections.append)
    site.toggled.connect(lambda path, is_expanded: toggles.append((path, is_expanded)))

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        tree.focus()
        await pilot.press("down", "enter", "enter")  # the top node, twice
        await pilot.press("space")  # it was expanded
        await pilot.pause()

        assert selections == [("Building A",)]
        assert toggles == [(("Building A",), False)]


@pytest.mark.asyncio
async def test_a_slider_moves_by_a_page_and_follows_a_drag() -> None:
    view = WorkersMainView()
    app = _app_of(view)
    workers = view.form.workers
    moves: list[int] = []
    workers.value_changed.connect(moves.append)

    async with app.run_test(size=(80, 24)) as pilot:
        slider = _field_widget(workers.renderer)
        assert isinstance(slider, ComposeSlider)
        await pilot.pause()
        slider.focus()
        await pilot.press("pageup", "pagedown")  # a tenth of the track, at least a step
        track, _ = _track_and_value(slider)
        await pilot.mouse_down(slider, offset=(1, 1))
        await pilot.hover(slider, offset=(len(track) // 2, 1))
        await pilot.mouse_up(slider, offset=(len(track) // 2, 1))
        await pilot.hover(slider, offset=(1, 1))  # released: no move
        await pilot.pause()

        assert moves[:3] == [8, 5, 2]  # by a page each, then pressed at the start
        assert 2 < moves[-1] < 14  # dragged to the track's middle
        assert workers.value == moves[-1]


@pytest.mark.asyncio
async def test_a_date_input_s_calendar_keeps_off_the_days_before_its_minimum() -> None:
    view, app, changes = await _booking_app()
    arrival = view.form.arrival

    async with app.run_test(size=(80, 30)) as pilot:
        field = _field_widget(arrival.renderer)
        assert isinstance(field, ComposeDateInput)
        await pilot.pause()
        arrival.minimum = datetime.date(2026, 10, 10)
        await pilot.pause()
        await pilot.click(field.button)
        await pilot.pause()
        month = app.screen.query_one(ComposeMonth)
        await pilot.click(month, offset=(3 * 3 + 2, 2))  # Thursday the 1st, before it
        await pilot.click(month, offset=(1, 12))  # under the weeks
        await pilot.click(month, offset=(1, 0))  # the title's left: the month before
        await pilot.pause()
        cursor = month.cursor
        await pilot.press("enter")
        await pilot.pause()

        assert cursor == datetime.date(2026, 10, 10)  # as near the month before as allowed
        assert (arrival.value, changes) == (cursor, [cursor])


@pytest.mark.asyncio
async def test_a_table_s_picker_closes_on_escape_and_a_disabled_box_ignores_space() -> None:
    view = CellWidgetsMainView()
    view.variables.cell_styles = {(0, 0): CellStyle(is_disabled=True)}
    app = _app_of(view)
    box = _widget(view.variables)
    assert isinstance(box, ComposeFilterTable)
    table = box.table
    edits: list[tuple[int, int, str]] = []
    view.variables.cell_edited.connect(lambda row, column, text: edits.append((row, column, text)))

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        first = next(iter(table.columns.values())).get_render_width(table)
        await pilot.click(table, offset=(first + 1, 1))  # the first row's name
        await pilot.press("space")  # its box, disabled
        await pilot.press("f2")  # no field typed in: the role's picker
        await pilot.pause()
        picked = isinstance(app.screen, ComposeOptionPicker)
        await pilot.press("escape")
        await pilot.pause()
        await pilot.press("f2")
        await pilot.pause()
        await pilot.press("enter")  # the role it has
        await pilot.pause()

        assert picked
        assert not isinstance(app.screen, ComposeOptionPicker)
        assert edits == []
        assert view.variables.rows[0][:3] == ["True", "Length", "Input"]


@pytest.mark.asyncio
async def test_a_large_table_without_rows_answers_no_key_or_click() -> None:
    view = RoomsDataMainView()
    view.rooms.filters = {"temperature": ">30"}
    activated: list[Any] = []
    view.rooms.row_activated.connect(activated.append)
    app = _app_of(view)

    # 81 columns: the rows' numbers' 2, then 26 a header, one left over past the last
    async with app.run_test(size=(81, 30)) as pilot:
        table = app.query_one(ComposeDataTable)
        table.focus()
        await pilot.press("space", "enter")
        await pilot.click(ComposeDataTable, offset=(15, 1))
        await pilot.click(ComposeDataTable, offset=(80, 0))
        await pilot.pause()

        assert (view.rooms.selected_ids, activated, view.rooms.sort_column) == ([], [], None)


@define_view
class _EmptyDataMainView(MainView):
    app_title = "Empty"
    extension = ".empty"

    table: DataTableView = Factory(DataTableView)  # no source: no column


@pytest.mark.asyncio
async def test_a_large_table_without_columns_draws_its_lines_empty() -> None:
    app = _app_of(_EmptyDataMainView())

    async with app.run_test(size=(80, 20)) as pilot:
        await pilot.pause()
        table = app.query_one(ComposeDataTable)

        assert table.render_line(0).text.strip() == ""


@pytest.mark.asyncio
async def test_a_splitter_s_border_stays_on_a_hover_and_beside_a_hidden_pane() -> None:
    view = SplitterMainView()
    app = _app_of(view)
    resizes: list[list[int]] = []
    view.splitter.resized.connect(resizes.append)

    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        first, _second = app.query(SplitterHandle)
        await pilot.hover(first)  # no button held: no drag
        view.splitter.study.is_visible = False  # no pane left of the first border
        await pilot.pause()
        first.focus()
        await pilot.press("right")
        await pilot.pause()

        assert len(resizes) <= 1  # nothing moved: the sizes as they were, if reported
        assert all(sizes == view.splitter.sizes for sizes in resizes)


@pytest.mark.asyncio
async def test_a_disabled_dialog_isn_t_closed_by_escape() -> None:
    view = DialogsMainView()
    app = _app_of(view)
    edited = EditedPipeMainView()
    edited_app = _app_of(edited)

    async with app.run_test() as pilot:
        view.confirm_clear.open()
        await pilot.pause()
        view.confirm_clear.is_enabled = False
        await pilot.press("escape")
        await pilot.pause()
        assert isinstance(app.screen, ComposeDialog)
    async with edited_app.run_test(size=(100, 40)) as pilot:
        edited.edit_dialog.open()
        await pilot.pause()
        edited.edit_dialog.is_enabled = False
        await pilot.press("escape")
        await pilot.pause()
        assert isinstance(edited_app.screen, ComposeFormDialog)


@pytest.mark.asyncio
async def test_a_combobox_without_a_value_shows_none() -> None:
    view = TranslatedMainView()
    app = _app_of(view)
    combobox = _field_widget(view.shape.size.renderer)
    assert isinstance(combobox, ComposeCombobox)

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        view.shape.size.value = None
        await pilot.pause()

        assert combobox.is_blank()


@pytest.mark.asyncio
async def test_a_markdown_set_before_the_app_runs_shows_once_it_does() -> None:
    view = HelpMainView()
    app = _app_of(view)
    view.help.text = "# Other help"  # rendered, the app not running yet

    async with app.run_test() as pilot:
        await pilot.pause()
        markdown = _widget(view.help)
        assert isinstance(markdown, ComposeMarkdown)

        assert markdown.source == "# Other help"


@pytest.mark.asyncio
async def test_a_file_path_s_picker_opens_here_on_a_path_typed_halfway_and_cancels() -> None:
    view = DataFileMainView()
    app = _app_of(view)
    picked: list[Path] = []
    view.form.measurements.path_picked.connect(picked.append)

    async with app.run_test(size=(100, 30)) as pilot:
        field = _field_widget(view.form.measurements.renderer)
        assert isinstance(field, ComposeFilePathInput)
        await pilot.pause()
        field.input.focus()
        await pilot.press(*"nowhere/da")
        await pilot.click(field.browse_button)
        await pilot.pause()
        opened = [type(screen).__name__ for screen in app.screen_stack]
        app.screen.dismiss(None)  # as the picker's Cancel does
        await pilot.pause()

        assert opened == ["Screen", "FileOpen"]
        assert (picked, field.input.value) == ([], "nowhere/da")
        assert field.input.has_focus


@pytest.mark.asyncio
async def test_a_table_emptied_under_its_cursor_answers_no_key() -> None:
    view = CellWidgetsMainView()
    app = _app_of(view)
    places_view = EditableTableMainView()
    places_app = _app_of(places_view)
    edits: list[tuple[int, int, str]] = []
    view.variables.cell_edited.connect(lambda row, column, text: edits.append((row, column, text)))

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        table = _widget(view.variables)
        assert isinstance(table, ComposeFilterTable)
        name = next(iter(table.table.columns.values())).get_render_width(table.table) + 1
        await pilot.click(table.table, offset=(name, 1))  # the cursor shown, on the first row
        view.variables.rows = []  # e.g. its records deleted
        await pilot.pause()
        await pilot.press("space", "f2")
        await pilot.pause()
        assert not isinstance(app.screen, ComposeOptionPicker)
    async with places_app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        places = _widget(places_view.places)
        assert isinstance(places, ComposeFilterTable)
        await pilot.click(places.table, offset=(2, 1))
        places_view.places.rows = []
        await pilot.pause()
        await pilot.press("f2")
        await pilot.pause()
        assert not isinstance(places_app.screen, ComposeRowEditor)

    assert edits == []


@pytest.mark.asyncio
async def test_an_edit_whose_answer_empties_the_table_leaves_its_other_cells() -> None:
    view = EditableTableMainView()
    view.places.editable_columns = [0, 1]
    app = _app_of(view)
    edits: list[tuple[int, int, str]] = []

    def answer(row: int, column: int, text: str) -> None:
        edits.append((row, column, text))
        view.places.rows = []  # e.g. the edit deletes its record

    view.places.cell_edited.connect(answer)

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        table = _widget(view.places)
        assert isinstance(table, ComposeFilterTable)
        await pilot.click(table.table, offset=(2, 1))
        await pilot.press("f2")
        await pilot.pause()
        await pilot.press("end", *"side", "tab", "end", *"er", "enter")
        await pilot.pause()

        assert edits == [(0, 0, "Lakeside")]  # the note's edit had no row left
        assert view.places.rows == []


@pytest.mark.asyncio
async def test_a_table_selecting_several_shows_its_cursor_first_and_checks_none_by_its_header() -> (
    None
):
    view = HorizontalMainView()
    table_view = view.tables.narrow
    table_view.selection_mode = SelectionMode.MULTIPLE
    app = _app_of(view)
    emitted: list[list[int]] = []
    table_view.selection_changed.connect(emitted.append)

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        box = _widget(table_view)
        assert isinstance(box, ComposeFilterTable)
        await pilot.click(box.table, offset=(1, 0))  # the header of the selection's column
        box.table.focus()
        await pilot.press("enter")  # the cursor shows, selecting nothing yet
        await pilot.pause()
        shown = box.table.show_cursor
        table_view.rows = []
        await pilot.pause()
        await pilot.press("enter")  # no row under the cursor
        await pilot.pause()

        assert shown
        assert emitted == []


@pytest.mark.asyncio
async def test_the_filter_bar_offers_the_columns_set_before_the_app_runs_and_adds_by_button() -> (
    None
):
    view, app, box = _sorted_rooms()
    view.rooms.filterable_columns = [1, 2]  # the temperature and the occupants
    bar = box.bar

    async with app.run_test(size=(160, 40)) as pilot:
        await pilot.pause()
        await pilot.click(bar.search)
        await pilot.press("enter")  # nothing typed since: no search
        await pilot.click(bar.add_filter)
        await pilot.pause()
        await pilot.click(bar.column)
        await pilot.pause()
        await pilot.press("home", "enter")  # the blank option: no column
        await pilot.pause()
        blank_placeholder = bar.value.placeholder
        await pilot.click(bar.add)  # nothing to add without a column
        await pilot.pause()
        await _add_filter(pilot, bar, 1, ">5")  # the second offered: the occupants

        assert blank_placeholder == ""
        assert view.rooms.search == ""
        assert view.rooms.filters == {2: ">5"}


@pytest.mark.asyncio
async def test_a_date_input_s_calendar_picks_no_day_outside_a_range_changed_while_open() -> None:
    view, app, changes = await _booking_app()
    arrival = view.form.arrival

    async with app.run_test(size=(80, 30)) as pilot:
        field = _field_widget(arrival.renderer)
        assert isinstance(field, ComposeDateInput)
        await pilot.pause()
        await pilot.click(field.button)
        await pilot.pause()
        month = app.screen.query_one(ComposeMonth)
        month.maximum = datetime.date(2026, 10, 15)  # under the cursor, on the 18th
        await pilot.press("enter")
        await pilot.click(month, offset=(7 * 3 + 1, 2))  # right of the week's last day
        await pilot.pause()

        assert changes == []
        assert isinstance(app.screen, ComposeCalendar)


@pytest.mark.asyncio
async def test_the_chart_leaves_out_what_it_has_no_data_for() -> None:
    view = PipeChartMainView()
    view.chart.series = []
    view.chart.reference_lines = [ReferenceLine(5, vertical=True, label="Start")]
    bars = ChartPagesMainView()
    bars.router.chart.energy.series = []
    app, bars_app = _app_of(view), _app_of(bars)

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        chart = _widget(view.chart)
        assert isinstance(chart, ComposeChart)
        assert "Start" not in str(chart.render())  # a label beside no data
    async with bars_app.run_test(size=(120, 40)) as pilot:
        bars.router.current_route = "chart"
        await pilot.pause()
        energy = _widget(bars.router.chart.energy)
        assert isinstance(energy, ComposeChart)
        assert "Kitchen" not in str(energy.render())  # no bar, nor its category


@pytest.mark.asyncio
async def test_a_slider_too_narrow_for_its_track_draws_none_and_takes_no_drag() -> None:
    view = WorkersMainView()
    app = _app_of(view)
    moves: list[int] = []
    view.form.workers.value_changed.connect(moves.append)

    async with app.run_test(size=(80, 24)) as pilot:
        slider = _field_widget(view.form.workers.renderer)
        assert isinstance(slider, ComposeSlider)
        await pilot.pause()
        slider.styles.width = 4  # its value's slot and a space, no track
        await pilot.pause()
        drawn = str(slider.render())
        await pilot.mouse_down(slider, offset=(1, 0))
        await pilot.mouse_up(slider, offset=(1, 0))

        assert (drawn, moves) == ("", [])


@pytest.mark.asyncio
async def test_a_splitter_s_border_released_undragged_reports_nothing() -> None:
    view = SplitterMainView()
    app = _app_of(view)
    resizes: list[list[int]] = []
    view.splitter.resized.connect(resizes.append)

    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        first, _second = app.query(SplitterHandle)
        await pilot.mouse_up(first)  # pressed elsewhere

        assert resizes == []


@define_view
class _InnerFirstTab(TabPage):
    text: LabelView = Factory(lambda: LabelView(text="One"))


@define_view
class _InnerSecondTab(TabPage):
    text: LabelView = Factory(lambda: LabelView(text="Two"))


@define_view
class _InnerTabs(TabView):
    first: _InnerFirstTab = Factory(lambda: _InnerFirstTab(title="First"))
    second: _InnerSecondTab = Factory(lambda: _InnerSecondTab(title="Second"))


@define_view
class _OuterTab(TabPage):
    inner: _InnerTabs = Factory(_InnerTabs)


@define_view
class _OtherTab(TabPage):
    text: LabelView = Factory(lambda: LabelView(text="Other"))


@define_view
class _OuterTabs(TabView):
    outer: _OuterTab = Factory(lambda: _OuterTab(title="Outer"))
    other: _OtherTab = Factory(lambda: _OtherTab(title="Other"))


@define_view
class _NestedTabsMainView(MainView):
    app_title = "Nested"
    extension = ".nested"

    tabs: _OuterTabs = Factory(_OuterTabs)


@pytest.mark.asyncio
async def test_a_tab_picked_in_tabs_within_tabs_is_theirs_only() -> None:
    view = _NestedTabsMainView()
    app = _app_of(view)
    outer_picks: list[int] = []
    view.tabs.current_changed.connect(outer_picks.append)

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inner = _widget(view.tabs.outer.inner)
        assert isinstance(inner, ComposeTabbedContent)
        second = _widget(view.tabs.outer.inner.second)
        assert isinstance(second, TabPane)
        await pilot.click(inner.get_tab(second))
        await pilot.pause()

        assert view.tabs.outer.inner.current_index == 1
        assert (view.tabs.current_index, outer_picks) == (0, [])


@pytest.mark.asyncio
async def test_f2_on_a_row_whose_editable_cells_are_disabled_opens_nothing() -> None:
    view = CellWidgetsMainView()
    view.variables.cell_styles = {(0, 2): CellStyle(is_disabled=True)}  # its role
    app = _app_of(view)

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        box = _widget(view.variables)
        assert isinstance(box, ComposeFilterTable)
        name = next(iter(box.table.columns.values())).get_render_width(box.table) + 1
        await pilot.click(box.table, offset=(name, 1))  # the first row
        await pilot.press("f2")
        await pilot.pause()

        assert not isinstance(app.screen, (ComposeOptionPicker, ComposeRowEditor))
