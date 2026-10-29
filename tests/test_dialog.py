"""The answers of a dialog, whatever backend shows it."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from composeui.core.view import CONVERTER, DialogKind, DialogView
from tests.dialogs import DialogsMainView
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
