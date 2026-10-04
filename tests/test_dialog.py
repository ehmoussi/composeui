"""The answers of a dialog, whatever backend shows it."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from composeui.core.view import CONVERTER, DialogKind, DialogView
from tests.dialogs import DialogsMainView

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
