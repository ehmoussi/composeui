"""Tests of `FormDialogView` in the core: OK follows its form's checks."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from tests.formdialog import EditPipeDialog, PipeMainView

if TYPE_CHECKING:
    from pathlib import Path


def test_ok_can_be_pressed_only_while_every_check_shown_passes() -> None:
    view = PipeMainView()
    dialog = view.edit_dialog
    view.edit.clicked.emit()
    assert dialog.is_visible
    assert dialog.is_accept_enabled

    dialog.form.name.text = ""
    dialog.form.name.text_edited.emit("")  # as typing does
    assert not dialog.is_accept_enabled
    dialog.form.name.text = "Return"
    dialog.form.name.text_edited.emit("Return")
    assert dialog.is_accept_enabled

    dialog.accept()
    assert not dialog.is_visible
    assert view.pipe.text == "Return, 12 m"


def test_accepting_runs_every_check_and_stays_open_while_one_fails() -> None:
    dialog = EditPipeDialog()
    accepted: list[bool] = []
    dialog.accepted.connect(lambda: accepted.append(True))
    dialog.open()
    assert dialog.is_accept_enabled  # no check ran yet

    dialog.accept()

    assert dialog.is_visible
    assert accepted == []
    assert not dialog.is_accept_enabled
    assert dialog.form.name.log_message == "A name is mandatory"
    assert dialog.form.length.log_message == "The length must be positive"


def test_cancel_leaves_the_record_alone_and_the_dialog_is_not_study_data(
    tmp_path: Path,
) -> None:
    view = PipeMainView()
    view.edit.clicked.emit()
    view.edit_dialog.form.name.text = "Return"
    view.edit_dialog.reject()
    assert not view.edit_dialog.is_visible
    assert view.pipe.text == "Main line, 12 m"

    path = tmp_path / "study.pipe"
    view.save_state(path)
    assert "edit_dialog" not in json.loads(path.read_text())
