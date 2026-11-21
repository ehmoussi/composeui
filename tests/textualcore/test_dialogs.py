"""Tests of the Textual dialogs."""

from __future__ import annotations

import pytest

pytest.importorskip("textual")
pytest.importorskip("textual_fspicker")

from attrs import Factory
from textual.coordinate import Coordinate
from textual.screen import Screen
from textual.widgets import (
    Button,
    Input,
)

from composeui.core.application import ModelApplication
from composeui.core.registry import RendererType
from composeui.core.view import (
    DialogKind,
    DialogView,
    FormDialogView,
    MainView,
    define_view,
)
from composeui.textualcore._renderers.navigation import TextualMainRenderer
from composeui.textualcore.textualrenderer import TextualWidgetRenderer
from composeui.textualcore.widgets.composecombobox import ComposeComboBox
from composeui.textualcore.widgets.composedialog import ComposeDialog
from composeui.textualcore.widgets.composefiltertable import (
    ComposeFilterTable,
)
from composeui.textualcore.widgets.composeformdialog import ComposeFormDialog
from examples.pipecatalogue import Material as CatalogueMaterial
from examples.pipecatalogue import Pipe as CataloguePipe
from examples.pipecatalogue import PipeCatalogueMainView, PipeCatalogueModel
from examples.pipecatalogue import PipeExpander as CataloguePipeExpander
from tests.dialogs import DialogsMainView
from tests.formdialog import PipeMainView as EditedPipeMainView
from tests.settingsdialog import NO_FOLDER, SettingsMainView
from tests.studydialog import StudyDialogMainView
from tests.textualcore.support import _app_of, _field_widget, _widget


@define_view
class _CoveredDialogsMainView(MainView):
    form: FormDialogView = Factory(FormDialogView)
    message: DialogView = Factory(DialogView)
    above: FormDialogView = Factory(FormDialogView)


@pytest.mark.asyncio
@pytest.mark.parametrize("covered_name", ["form", "message"])
async def test_a_dialog_closed_under_another_does_not_come_back(covered_name: str) -> None:
    view = _CoveredDialogsMainView()
    app = _app_of(view)
    covered = getattr(view, covered_name)

    async with app.run_test() as pilot:
        base = app.screen
        covered.open()
        await pilot.pause()
        covered_screen = app.screen
        view.above.open()
        await pilot.pause()
        above_screen = app.screen
        covered.reject()
        await pilot.pause()
        assert app.screen is above_screen  # the dialog above stays

        view.above.reject()
        await pilot.pause()
        await pilot.pause()

        assert app.screen is base
        assert covered_screen not in app.screen_stack


@pytest.mark.asyncio
async def test_a_form_dialog_opened_again_under_another_is_on_the_stack_once() -> None:
    view = _CoveredDialogsMainView()
    app = _app_of(view)

    async with app.run_test() as pilot:
        base = app.screen
        view.form.open()
        await pilot.pause()
        form_screen = app.screen
        view.above.open()
        await pilot.pause()
        view.form.reject()
        view.form.open()
        await pilot.pause()
        assert app.screen_stack.count(form_screen) == 1

        view.above.reject()
        await pilot.pause()
        await pilot.pause()
        assert app.screen is form_screen  # open, so it stays

        view.form.reject()
        await pilot.pause()
        assert app.screen is base


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
async def test_a_content_dialog_shows_its_view_whose_buttons_leave_it_open() -> None:
    view = StudyDialogMainView()
    app = _app_of(view)
    content = view.open_dialog.content
    up = _widget(content.up)
    box = _widget(content.entries)
    assert isinstance(box, ComposeFilterTable)

    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.pause()
        await pilot.click(_widget(view.open))
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ComposeFormDialog)
        shown = list(screen.walk_children())
        assert all(widget in shown for widget in (_widget(content.folder), up, box))
        assert screen.accept_button.disabled  # nothing selected yet

        await pilot.click(up)
        await pilot.pause()

        assert app.screen is screen
        assert str(box.table.get_cell_at(Coordinate(0, 0))) == "beam"


@pytest.mark.asyncio
async def test_a_dialog_s_own_buttons_and_check_show_in_textual_and_act_on_their_clicks() -> None:
    view = SettingsMainView()
    app = _app_of(view)
    settings = view.settings
    apply, discard = _widget(settings.apply), _widget(settings.discard)
    folder, log = _widget(settings.content.folder), _widget(settings.log_view)
    assert isinstance(folder, Input)

    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        settings.open()
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ComposeFormDialog)
        buttons = list(screen.query(Button))
        assert buttons == [screen.reject_button, apply, discard, screen.accept_button]
        assert not log.display

        folder.focus()
        folder.action_end()
        await pilot.press(*["backspace"] * len("results"))
        await pilot.pause()
        assert log.display
        assert NO_FOLDER in str(log.render())
        assert screen.accept_button.disabled
        assert apply.disabled
        assert not discard.disabled

        await pilot.press(*"out")
        await pilot.pause()
        assert not screen.accept_button.disabled
        await pilot.click(apply)
        await pilot.pause()
        assert app.screen is screen
        await pilot.click(discard)
        await pilot.pause()
        assert app.screen is not screen
    assert view.answers == ["apply", "discard"]


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
    assert isinstance(material, ComposeComboBox)

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
async def test_enter_rejects_a_destructive_confirmation_focused_on_its_safe_button() -> None:
    view = DialogsMainView()
    app = _app_of(view)
    dialog = view.confirm_clear

    async with app.run_test() as pilot:
        dialog.open()
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ComposeDialog)
        dialog.is_destructive = True  # while open, as Qt's and the web's move the focus too
        await pilot.pause()
        changed = (screen.accept_button.variant, screen.focused is screen.reject_button)
        await pilot.press("escape")
        await pilot.pause()

        dialog.open()
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ComposeDialog)
        opened = (screen.accept_button.variant, screen.focused is screen.reject_button)
        await pilot.press("enter")
        await pilot.pause()

        assert changed == ("error", True)
        assert opened == ("error", True)
        assert not dialog.is_visible
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
