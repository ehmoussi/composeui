"""The answers of a dialog and of its own buttons, whatever backend shows it."""

from __future__ import annotations

import functools
from typing import TYPE_CHECKING, Optional

import pytest
from typing_extensions import override

from composeui.core.model import RefusedError
from composeui.core.reactivity import reactive, start_reactions
from composeui.core.view import (
    CONVERTER,
    DialogButtonView,
    DialogKind,
    DialogView,
    FormDialogView,
    LabelView,
    LogType,
    MainView,
    child,
    define_view,
)
from tests.dialogs import DialogsMainView
from tests.settingsdialog import NO_FOLDER, SettingsDialog, SettingsMainView
from tests.studydialog import OpenStudyDialog, StudyDialogMainView

if TYPE_CHECKING:
    from pathlib import Path


def _answers(dialog: DialogView) -> list[str]:
    answers: list[str] = []
    dialog.accepted.connect(lambda: answers.append("accepted"))
    dialog.rejected.connect(lambda: answers.append("rejected"))
    return answers


@pytest.mark.parametrize(
    ("kind", "answer"),
    [(DialogKind.CONFIRM, "rejected"), (DialogKind.MESSAGE, "accepted")],
)
def test_dismissing_rejects_a_confirmation_and_accepts_a_message(
    kind: DialogKind, answer: str
) -> None:
    dialog = DialogView(kind=kind)
    answers = _answers(dialog)
    dialog.open()
    dialog.dismiss()
    assert not dialog.is_visible
    assert answers == [answer]


def test_only_an_open_dialog_answers() -> None:
    """A second click on a button already sent (e.g. a double click on the web)."""
    dialog = DialogView(kind=DialogKind.CONFIRM)
    answers = _answers(dialog)
    dialog.accept()
    dialog.open()
    dialog.accept()
    dialog.reject()
    assert answers == ["accepted"]


def _ask(dialog: DialogView, answers: list[str], name: str) -> None:
    """Ask `dialog`, recording its answer in `answers` as ``name`` and whether it agreed."""
    dialog.ask(lambda: answers.append(f"{name} agreed"), lambda: answers.append(f"{name} refused"))


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        ("accept", ["delete agreed", "accepted"]),
        ("reject", ["delete refused", "rejected"]),
        ("dismiss", ["delete refused", "rejected"]),
    ],
)
def test_a_question_asked_calls_its_answer_once_before_the_signal(
    answer: str, expected: list[str]
) -> None:
    dialog = DialogView(kind=DialogKind.CONFIRM)
    answers = _answers(dialog)
    _ask(dialog, answers, "delete")
    assert dialog.is_visible

    getattr(dialog, answer)()
    dialog.open()  # opened again, but not asked
    dialog.accept()

    assert not dialog.is_visible
    assert answers == [*expected, "accepted"]


def test_a_question_asked_without_a_rejecting_function_rejects_with_nothing_more() -> None:
    dialog = DialogView(kind=DialogKind.CONFIRM)
    answers = _answers(dialog)
    dialog.ask(lambda: answers.append("delete agreed"))
    dialog.reject()
    assert answers == ["rejected"]


def test_a_new_question_replaces_the_one_not_answered_and_forget_drops_it() -> None:
    dialog = DialogView(kind=DialogKind.CONFIRM)
    answers: list[str] = []
    _ask(dialog, answers, "close")
    _ask(dialog, answers, "delete")
    dialog.open()  # already open: still the same question
    dialog.accept()
    assert answers == ["delete agreed"]

    _ask(dialog, answers, "run")
    dialog.forget()
    assert not dialog.is_visible
    dialog.open()
    dialog.accept()
    assert answers == ["delete agreed"]


def test_opening_a_dialog_closed_without_an_answer_drops_its_question() -> None:
    dialog = DialogView(kind=DialogKind.CONFIRM)
    answers: list[str] = []
    _ask(dialog, answers, "delete")
    dialog.is_visible = False  # closed by the app
    dialog.open()
    dialog.accept()
    assert answers == []


def test_an_answer_that_asks_again_keeps_its_new_question() -> None:
    dialog = DialogView(kind=DialogKind.CONFIRM)
    answers: list[str] = []
    dialog.ask(lambda: _ask(dialog, answers, "and delete"))
    dialog.accept()
    assert dialog.is_visible
    dialog.accept()
    assert answers == ["and delete agreed"]


def test_an_ok_cancel_question_is_answered_only_once_it_closes() -> None:
    """A failing check or a refusal keeps the dialog open: the question still waits."""
    view = SettingsMainView()
    dialog = view.settings
    answers: list[str] = []
    is_refused = [True]
    dialog.accepting.connect(functools.partial(_refuse, dialog, is_refused=is_refused))
    _ask(dialog, answers, "save")

    _clear_folder(dialog)
    dialog.accept()  # the check fails
    dialog.content.folder.text = "results"
    dialog.accept()  # the model refuses
    assert dialog.is_visible
    assert answers == []
    is_refused[0] = False
    dialog.accept()
    assert answers == ["save agreed"]


def test_a_dialog_s_own_closing_button_drops_the_question() -> None:
    dialog = SettingsDialog()
    answers: list[str] = []
    _ask(dialog, answers, "save")
    dialog.apply.click()  # answers without closing: the question still waits
    dialog.discard.click()
    assert not dialog.is_visible
    dialog.open()
    dialog.accept()
    dialog.open()
    dialog.reject()
    assert answers == []


@define_view
class AskingView(MainView):
    """Asks before it fills a city's name, which a reactive method summarizes."""

    name: LabelView = child(LabelView)
    city: LabelView = child(LabelView)
    confirm: DialogView = child(DialogView, kind=DialogKind.CONFIRM)

    @override
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        #: each summary `summarize` made; not a field: the test's record
        self.summaries: list[str] = []

    @reactive
    def summarize(self) -> None:
        self.summaries.append(f"{self.name.text} in {self.city.text}")


def test_an_answer_s_changes_run_a_reactive_method_once_after_it() -> None:
    view = AskingView()
    start_reactions(view)

    def fill() -> None:
        view.name.text = "Ada"
        view.city.text = "London"

    view.confirm.ask(fill)
    view.confirm.accept()
    assert view.summaries == [" in ", "Ada in London"]


def test_a_dialog_is_neither_saved_nor_loaded(tmp_path: Path) -> None:
    view = DialogsMainView()
    view.confirm_clear.open()
    assert "confirm_clear" not in CONVERTER.unstructure(view)

    filepath = tmp_path / "study.dialogs"
    DialogsMainView().save_state(filepath)  # saved while its dialog is closed
    view.load_state(filepath)
    assert view.confirm_clear.is_visible


def _select(dialog: OpenStudyDialog, row: int) -> None:
    """Select `row` of the dialog's table, which enables OK, as the app does."""
    dialog.content.entries.selected_rows = [row]
    dialog.is_accept_enabled = True


def test_a_content_dialog_closes_on_ok_only_once_the_app_enables_it_and_accepts() -> None:
    view = StudyDialogMainView()
    dialog = view.open_dialog
    answers = _answers(dialog)
    dialog.open()
    assert dialog.kind is DialogKind.CONFIRM

    dialog.accept()  # OK disabled: nothing selected yet
    assert dialog.is_visible
    dialog.show("/studies")
    _select(dialog, 0)  # a folder: its `accept` shows it, the dialog left open
    dialog.accept()
    assert dialog.is_visible
    assert dialog.content.entries.rows == [["beam.export"]]
    assert answers == []

    _select(dialog, 0)
    dialog.accept()

    assert not dialog.is_visible
    assert answers == ["accepted"]
    assert view.study.text == "/studies/beam/beam.export"


def _clear_folder(dialog: SettingsDialog) -> None:
    """Empty the folder as the user does: its widget emits the change."""
    dialog.content.folder.text = ""
    dialog.content.folder.text_changed.emit("")


def test_a_dialog_s_own_button_answers_without_closing_unless_it_closes() -> None:
    view = SettingsMainView()
    dialog = view.settings
    dialog.open()

    dialog.apply.click()
    assert dialog.is_visible
    dialog.discard.click()

    assert not dialog.is_visible
    assert view.answers == ["apply", "discard"]  # closing: neither accepted nor rejected
    dialog.apply.click()  # a click already sent, once closed
    assert view.answers == ["apply", "discard"]


def test_a_dialog_button_outside_a_dialog_clicks_as_a_button() -> None:
    button = DialogButtonView(text="Apply")
    clicks: list[bool] = []
    button.clicked.connect(lambda: clicks.append(True))
    button.click()
    assert clicks == [True]


def _refuse(dialog: SettingsDialog, *, is_refused: list[bool]) -> None:
    """Save as an app does, in the dialog's `refusing`: the model refuses while asked."""
    with dialog.refusing("Can't save: {error}."):
        if is_refused[0]:
            msg = "the folder is read-only"
            raise RefusedError(msg)


@pytest.mark.parametrize("answer", ["save", "discard"])
def test_a_refusal_in_the_answer_s_work_keeps_the_dialog_open_and_says_why(answer: str) -> None:
    view = SettingsMainView()
    dialog = view.settings
    is_refused = [True]
    work = functools.partial(_refuse, dialog, is_refused=is_refused)
    is_open: list[bool] = []
    dialog.accepting.connect(lambda: is_open.append(dialog.is_visible))
    dialog.accepting.connect(work)
    dialog.discard.clicked.connect(work)
    press = dialog.accept if answer == "save" else dialog.discard.click
    dialog.open()

    press()

    assert dialog.is_visible
    assert dialog.log_view.is_visible
    assert dialog.log_view.log_message == "- Can't save: the folder is read-only."
    assert dialog.can_accept  # not a check: the user can try again
    is_refused[0] = False
    press()
    assert not dialog.is_visible
    assert not dialog.log_view.is_visible  # a refusal shows until the next click
    expected = ["accepted"] if answer == "save" else ["discard", "discard"]
    assert view.answers == expected
    assert is_open == ([True, True] if answer == "save" else [])


@pytest.mark.parametrize("answer", ["refusal", "information"])
@pytest.mark.parametrize("next_step", ["click", "check", "opening"])
def test_an_answer_s_message_shows_until_the_next_click_check_or_opening(
    answer: str, next_step: str
) -> None:
    dialog = SettingsDialog()
    if answer == "refusal":
        dialog.apply.clicked.connect(functools.partial(_refuse, dialog, is_refused=[True]))
    else:
        dialog.apply.clicked.connect(lambda: dialog.show_message("Saved."))
    dialog.open()
    dialog.apply.click()
    assert dialog.is_visible
    assert dialog.log_view.is_visible
    is_refusal = answer == "refusal"
    assert dialog.log_view.log_type is (LogType.ERROR if is_refusal else LogType.INFO)
    assert dialog.can_accept  # neither is a check: OK and Apply can be pressed
    assert not dialog.apply.is_blocked

    if next_step == "click":
        dialog.discard.click()  # shows nothing of its own
    elif next_step == "check":
        dialog.content.folder.text_changed.emit("results")
    else:
        dialog.reject()
        dialog.open()

    assert not dialog.log_view.is_visible


def test_a_dialog_s_failing_check_shows_and_blocks_ok_and_its_checking_buttons() -> None:
    view = SettingsMainView()
    dialog = view.settings
    dialog.open()

    _clear_folder(dialog)
    assert dialog.log_view.is_visible
    assert dialog.log_view.log_message == f"- {NO_FOLDER}"
    assert not dialog.can_accept
    assert dialog.apply.is_blocked
    assert not dialog.discard.is_blocked
    dialog.apply.click()
    dialog.accept()
    assert dialog.is_visible  # still open, the message shown
    assert view.answers == []

    dialog.content.folder.text = "out"
    dialog.content.folder.text_changed.emit("out")
    assert not dialog.log_view.is_visible
    assert not dialog.apply.is_blocked
    dialog.apply.click()
    dialog.accept()
    assert not dialog.is_visible
    assert view.answers == ["apply", "accepted"]


def test_ok_and_a_checking_button_run_the_checks_a_change_hasn_t_run() -> None:
    """A value set by code emits nothing: clicking checks it anyway."""
    view = SettingsMainView()
    dialog = view.settings
    dialog.open()
    dialog.content.folder.text = ""

    dialog.apply.click()
    dialog.accept()

    assert dialog.is_visible
    assert dialog.log_view.log_message == f"- {NO_FOLDER}"
    assert view.answers == []


@define_view
class _ApplyFormDialog(FormDialogView):
    apply: DialogButtonView = child(DialogButtonView, text="Apply")


@pytest.mark.parametrize(
    ("form_message", "dialog_message"), [("Too thin.", None), (None, "Taken."), (None, None)]
)
def test_a_form_dialog_s_buttons_wait_for_its_form_s_checks_and_its_own(
    form_message: Optional[str], dialog_message: Optional[str]
) -> None:
    dialog = _ApplyFormDialog()
    dialog.form.add_validator(lambda: form_message)
    dialog.add_check(lambda: dialog_message)
    applied: list[bool] = []
    dialog.apply.clicked.connect(lambda: applied.append(True))
    dialog.open()

    dialog.apply.click()

    passes = form_message is None and dialog_message is None
    assert applied == ([True] if passes else [])
    assert dialog.apply.is_blocked is not passes
    assert dialog.log_view.is_visible is (dialog_message is not None)  # the form shows its own
    dialog.accept()
    assert dialog.is_visible is not passes
