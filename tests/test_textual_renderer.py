"""End-to-end coverage for the Textual backend (roadmap item 12).

Uses Textual's headless `App.run_test()` pilot to drive a real rendered widget
tree, proving `composeui.core` isn't secretly Qt-only: the same views/mixins used
by the Qt backend render, accept input, and round-trip state through a second,
unrelated GUI toolkit.
"""

import pytest

pytest.importorskip("textual")
pytest.importorskip("textual_fspicker")

from pathlib import Path
from typing import Any, Optional, Union

from attrs import Factory
from textual.containers import VerticalScroll
from textual.coordinate import Coordinate
from textual.widget import Widget
from textual.widgets import Button, Checkbox, DataTable, Footer, Input, Label

from composeui.core.application import _add_reference_to_signals
from composeui.core.renderer import Renderer, RendererContainer
from composeui.core.view import (
    ActionView,
    ButtonVariant,
    DialogKind,
    EditRefusedError,
    MainView,
    RendererType,
    SelectionMode,
    View,
    define_view,
    replace_cell,
)
from composeui.textualcore.textualrenderer import (
    ROW_INVALID_CLASS,
    TextualMainRenderer,
    TextualWidgetRenderer,
)
from composeui.textualcore.widgets.composecombobox import ComposeCombobox
from composeui.textualcore.widgets.composedialog import ComposeDialog
from composeui.textualcore.widgets.composeradioset import ComposeRadioSet
from composeui.textualcore.widgets.composetable import ComposeRowEditor
from composeui.textualcore.widgets.composetoolbar import ComposeToolbar, ComposeToolbarButton
from examples.pipeform import EdgeType, Material, PipeMainView
from examples.textual_demo import TextualDemoMainView
from tests.dialogs import DialogsMainView
from tests.horizontal import ButtonsMainView, HorizontalMainView
from tests.pages import PagesMainView
from tests.tables import EditableTableMainView
from tests.toolbar import ToolBarMainView
from tests.translated import Size, TranslatedMainView
from tests.vertical import VerticalMainView


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
        table = view.pages.results.summary.renderer.widget
        assert isinstance(table, DataTable)

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
    table = view.tables.narrow.renderer.widget
    assert isinstance(table, DataTable)
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
    table = table_view.renderer.widget
    assert isinstance(table, DataTable)
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
    table = view.places.renderer.widget
    assert isinstance(table, DataTable)
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
    table = view.places.renderer.widget
    assert isinstance(table, DataTable)

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
