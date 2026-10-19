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
from rich.style import Style
from rich.text import Text
from textual.containers import VerticalScroll
from textual.coordinate import Coordinate
from textual.widgets import Button, Checkbox, Footer, Input, Label, ProgressBar, TabPane
from textual.widgets.collapsible import CollapsibleTitle
from textual.widgets.markdown import MarkdownBlock

from composeui.core import chartimage
from composeui.core.application import ModelApplication, _add_reference_to_signals
from composeui.core.renderer import Renderer, RendererContainer
from composeui.core.view import (
    ActionView,
    ButtonVariant,
    ChartKind,
    DialogKind,
    EditRefusedError,
    MainView,
    ReferenceLine,
    RendererType,
    SelectionMode,
    Series,
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
from composeui.textualcore.widgets.composedateinput import (
    ComposeCalendar,
    ComposeDateInput,
    ComposeMonth,
)
from composeui.textualcore.widgets.composedialog import ComposeDialog
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
from composeui.textualcore.widgets.composetable import ComposeRowEditor, ComposeTable
from composeui.textualcore.widgets.composetoolbar import ComposeToolbar, ComposeToolbarButton
from composeui.textualcore.widgets.composetree import ComposeTree
from examples.batman import BatmanMainView
from examples.pipecatalogue import Material as CatalogueMaterial
from examples.pipecatalogue import Pipe as CataloguePipe
from examples.pipecatalogue import PipeCatalogueMainView, PipeCatalogueModel
from examples.pipecatalogue import PipeExpander as CataloguePipeExpander
from examples.pipechart import PipeChartMainView
from examples.pipeform import EdgeType, Material, PipeMainView
from examples.textual_demo import TextualDemoMainView
from tests.bookings import BookingMainView
from tests.buildings import SiteMainView
from tests.charts import ChartPagesMainView
from tests.dialogs import DialogsMainView
from tests.expander import RecordMainView
from tests.formdialog import PipeMainView as EditedPipeMainView
from tests.grid import GridMainView
from tests.horizontal import ButtonsMainView, HorizontalMainView
from tests.hours import HoursMainView
from tests.listview import PIPES, Pipe, PipeExpander, PipesMainView
from tests.markdown import HelpMainView, HelpViewerMainView
from tests.metrics import JobsMainView
from tests.pages import PagesMainView
from tests.sidebar import SidebarMainView
from tests.splitter import SplitterMainView, VerticalSplitterMainView
from tests.tables import EditableTableMainView, Room, SortedRoomsMainView
from tests.tabs import TabsMainView
from tests.toolbar import ToolBarMainView
from tests.translated import Size, TranslatedMainView
from tests.vertical import VerticalMainView
from tests.workers import WorkersMainView

if TYPE_CHECKING:
    from pathlib import Path

    from textual.app import App
    from textual.pilot import Pilot
    from textual.widget import Widget


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
        await pilot.pause()

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
        second.focus()  # the arrow keys move a focused border
        await pilot.press("left", "left")
        await pilot.pause()
        assert widget.pane_lengths()[2] == result + 2

        splitter.sizes = [1, 1, 1]  # set in code: shared alike
        await pilot.pause()
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
        assert len(plotted.x[1]) == 6
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
async def test_its_key_saves_the_chart_s_image(tmp_path: Path) -> None:
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
        app.screen.dismiss(tmp_path / "drop")  # as the dialog's Save button does
        await pilot.pause()

    assert (tmp_path / "drop.pdf").read_bytes().startswith(b"%PDF")  # PDF unless named


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
