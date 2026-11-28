"""Tests of the Textual actions, menus and toolbars."""

from __future__ import annotations

import pytest

pytest.importorskip("textual")
pytest.importorskip("textual_fspicker")

from typing import TYPE_CHECKING, Any

from attrs import Factory
from textual.widgets import (
    Footer,
    Input,
)
from textual_fspicker.base_dialog import FileSystemPickerScreen
from textual_fspicker.parts import DirectoryNavigation

from composeui.core.application import _add_reference_to_signals
from composeui.core.registry import RendererType
from composeui.core.view import (
    ActionView,
    MainView,
    define_view,
)
from composeui.textualcore._renderers.navigation import TextualMainRenderer
from composeui.textualcore.textualrenderer import TextualWidgetRenderer
from composeui.textualcore.widgets.composedialog import ComposeDialog
from composeui.textualcore.widgets.composemenubutton import ComposeMenuPopup
from composeui.textualcore.widgets.composetoolbar import ComposeToolbar, ComposeToolbarButton
from examples.pipeform import PipeMainView
from tests.dialogs import DialogsMainView
from tests.markdown import HelpMainView, HelpViewerMainView
from tests.menubutton import MenuButtonMainView
from tests.textualcore.support import (
    _app_of,
    _click_laid_out,
    _field_widget,
    _wait_for_screen,
    _widget,
)
from tests.toolbar import ToolBarMainView

if TYPE_CHECKING:
    from pathlib import Path

    from textual.pilot import Pilot
    from textual.widget import Widget


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
        await app.workers.wait_for_complete()  # the action's worker thread, done
        await pilot.pause()  # what it handed back to the app's thread

        assert len(app.screen_stack) == 1  # modal closed
        assert view.file_view.filepath == filepath
        assert view.pages.inputs.pipe_form.name.text == "loaded_name"
        name_widget = _field_widget(view.pages.inputs.pipe_form.name.renderer)
        assert isinstance(name_widget, Input)
        assert name_widget.value == "loaded_name"  # the real widget reflects it too


@pytest.mark.asyncio
async def test_open_and_quit_ask_before_they_discard_unsaved_changes(tmp_path: Path) -> None:
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
    form = view.pages.inputs.pipe_form

    async with app.run_test() as pilot:
        await pilot.pause()
        view._mark_saved()  # noqa: SLF001 (as the app's start does)
        form.name.text = "edited"
        await pilot.press("ctrl+o")
        await pilot.pause()
        await pilot.pause()
        file_input = app.screen.query_one(Input)
        file_input.focus()
        file_input.value = str(filepath)
        await pilot.pause()
        await pilot.press("enter")
        await app.workers.wait_for_complete()  # the picker's worker thread, done
        await pilot.pause()  # the question it handed to the app's thread
        screen = app.screen
        assert isinstance(screen, ComposeDialog)
        assert form.name.text == "edited"
        await pilot.click(screen.accept_button)
        await pilot.pause()
        assert form.name.text == "loaded_name"

        form.name.text = "edited again"
        await pilot.press("ctrl+q")
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ComposeDialog)
        assert app.is_running
        await pilot.click(screen.accept_button)
        await pilot.pause()
        assert app.return_code is not None  # exited


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
        await app.workers.wait_for_complete()  # the action's worker thread, done
        await pilot.pause()  # what it handed back to the app's thread
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
        await app.workers.wait_for_complete()  # the action's worker thread, done
        await pilot.pause()  # what it handed back to the app's thread

        assert len(app.screen_stack) == 1
        assert view.file_view.filepath is None


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
        # pushed by the action's worker thread
        await _wait_for_screen(pilot, FileSystemPickerScreen, DirectoryNavigation)
        assert [type(s).__name__ for s in app.screen_stack] == ["Screen", "FileOpen"]


async def _open_menu(pilot: Pilot[Any], button: Widget) -> ComposeMenuPopup:
    """Click a menu button, and get its list once on screen and laid out.

    The button opens the list from its own message, after the click: a slow machine takes more
    than one pause.
    """
    app = button.app
    await _click_laid_out(pilot, button)
    for _ in range(100):
        if isinstance(app.screen, ComposeMenuPopup) and app.screen.options.region.area > 0:
            break
        await pilot.pause()
    popup = app.screen
    assert isinstance(popup, ComposeMenuPopup)
    return popup


@pytest.mark.asyncio
async def test_a_menu_button_lists_its_shown_actions_under_it_and_runs_the_one_picked() -> None:
    view = MenuButtonMainView()
    more = view.actions.more
    more.reload.is_enabled = False
    more.preview.text = "Preview [/draft]"  # shown as it is, not read as Textual's markup
    more.wrap.is_visible = False
    app = _app_of(view)

    async with app.run_test() as pilot:
        button = _widget(more)
        popup = await _open_menu(pilot, button)
        options = [popup.options.get_option_at_index(i) for i in range(2)]
        assert [(str(o.prompt), o.disabled) for o in options] == [
            ("Reload", True),
            ("Preview [/draft]", False),
        ]
        assert popup.options.region.y == button.region.bottom  # under the button

        await pilot.click(popup.options, offset=(2, 2))  # Preview, under the border and Reload
        await pilot.pause()

        assert not isinstance(app.screen, ComposeMenuPopup)
        assert view.last.text == "Previewed"

        view.last.text = ""
        await _open_menu(pilot, button)
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, ComposeMenuPopup)
        await _open_menu(pilot, button)
        await pilot.click(offset=(app.size.width - 1, app.size.height - 1))  # outside the list
        await pilot.pause()

        assert not isinstance(app.screen, ComposeMenuPopup)
        assert view.last.text == ""

        # an entry hidden while the list shows it no longer runs, as Qt and the web refuse it
        popup = await _open_menu(pilot, button)
        more.preview.is_visible = False
        await pilot.click(popup.options, offset=(2, 2))
        await pilot.pause()
        assert not isinstance(app.screen, ComposeMenuPopup)
        assert view.last.text == ""


@pytest.mark.asyncio
async def test_a_menu_button_s_entry_keys_work_only_while_it_is_enabled_and_shown() -> None:
    view = MenuButtonMainView()
    more = view.actions.more
    app = _app_of(view)

    async with app.run_test() as pilot:
        await pilot.pause()
        more.is_enabled = False
        await pilot.press("ctrl+r")
        await pilot.pause()
        more.is_enabled = True
        more.is_visible = False
        await pilot.press("ctrl+r")
        await pilot.pause()
        assert view.last.text == ""
        more.is_visible = True
        await pilot.press("ctrl+r")
        await pilot.pause()
        assert view.last.text == "Reloaded"


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
        await app.workers.wait_for_complete()  # the action's worker thread, done
        await pilot.pause()  # what it handed back to the app's thread

        assert len(app.screen_stack) == 1  # modal closed
        assert view.file_view.filepath == typed.with_suffix(".pipe")
        assert "saved_name" in typed.with_suffix(".pipe").read_text()


@define_view
class _TwinShortcutsMainView(MainView):
    """Two actions sharing a key: an app's own mistake, or a key given back and forth."""

    app_title = "Twins"
    extension = ".twins"

    first: ActionView = Factory(lambda: ActionView(text="First", shortcut="Ctrl+e"))
    second: ActionView = Factory(lambda: ActionView(text="Second", shortcut="Ctrl+e"))


@pytest.mark.asyncio
async def test_the_shortcuts_of_disabled_actions_do_nothing_until_they_are_enabled() -> None:
    view = _TwinShortcutsMainView()
    view.second.shortcut = "Ctrl+y"
    app = _app_of(view)
    triggered: list[str] = []
    view.first.triggered.connect(lambda: triggered.append("custom"))
    view.file_menu.new.triggered.connect(lambda: triggered.append("new"))
    view.file_menu.open_file.triggered.connect(lambda: triggered.append("open"))

    async with app.run_test() as pilot:
        await pilot.pause()
        for action in (view.first, view.file_menu.new, view.file_menu.open_file):
            action.is_enabled = False
        await pilot.pause()
        await pilot.press("ctrl+e", "ctrl+n", "ctrl+o")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert triggered == []

        view.first.is_enabled = True
        await pilot.press("ctrl+e")
        await pilot.pause()
        assert triggered == ["custom"]


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
