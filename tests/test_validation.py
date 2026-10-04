"""Tests for the validation abstraction (roadmap item 5).

Before this, every form hand-rolled its own `_display_error_message`-style method
(see the pre-existing pattern still visible in git history for `examples/pipeform.py`
and `examples/textual_demo.py`). `LogMixin.set_validator`/`run_validator` cover a
single row validating itself into its own log; `FormView.add_validator`/`validate`
cover a form combining several independent cross-field checks into its shared
`log_view` - `PipeFormView` in `examples/pipeform.py` now uses both.
"""

from composeui.core.view import CONVERTER, FormView, LogType, RowInputView


def test_set_validator_pushes_a_failing_message_to_the_rows_own_log() -> None:
    row = RowInputView()
    row.set_validator(lambda: "required" if row.text == "" else None, row.text_edited)

    row.text_edited.emit("")
    assert row.log_message == "required"
    assert row.log_type == LogType.ERROR


def test_set_validator_clears_the_log_once_the_check_passes() -> None:
    row = RowInputView()
    row.set_validator(lambda: "required" if row.text == "" else None, row.text_edited)
    row.text_edited.emit("")
    assert row.log_message == "required"

    row.text = "hi"
    row.text_edited.emit("hi")
    assert row.log_message == ""
    assert row.log_type == LogType.INFO


def test_set_validator_does_not_run_immediately() -> None:
    row = RowInputView()  # text == "" - would fail if run eagerly
    row.set_validator(lambda: "required" if row.text == "" else None, row.text_edited)
    assert row.log_message == ""  # untouched until the signal fires or run_validator() is called


def test_run_validator_can_be_connected_directly_to_a_no_argument_signal() -> None:
    row = RowInputView()
    row.set_validator(lambda: "required" if row.text == "" else None, row.editing_finished)

    row.editing_finished.emit()
    assert row.log_message == "required"


def test_row_validator_field_is_excluded_from_saved_state() -> None:
    row = RowInputView()
    row.set_validator(lambda: None, row.text_edited)
    data = CONVERTER.unstructure(row)
    assert "validator" not in data


def test_add_validator_combines_failing_messages_from_multiple_checks() -> None:
    form = FormView()
    form.add_validator(lambda: "first is wrong")
    form.add_validator(lambda: "second is wrong")

    form.validate()
    assert form.log_view.log_message == "- first is wrong\n- second is wrong"
    assert form.log_view.log_type == LogType.ERROR
    assert form.log_view.is_visible is True


def test_validate_hides_the_log_once_every_validator_passes() -> None:
    form = FormView()
    should_fail = True
    form.add_validator(lambda: "broken" if should_fail else None)

    form.validate()
    assert form.log_view.is_visible is True

    should_fail = False
    form.validate()
    assert form.log_view.is_visible is False
    assert form.log_view.log_message == ""
    assert form.log_view.log_type == LogType.INFO


def test_add_validator_does_not_run_immediately() -> None:
    form = FormView()
    form.add_validator(lambda: "broken")  # would fail if run eagerly
    assert form.log_view.is_visible is False
    assert form.log_view.log_message == ""


def test_form_validators_are_excluded_from_saved_state() -> None:
    form = FormView()
    form.add_validator(lambda: "broken")
    data = CONVERTER.unstructure(form)
    assert "_validators" not in data
    assert "validators" not in data


def test_a_failing_check_flags_the_rows_it_names_until_it_passes() -> None:
    form = FormView()
    radius, width, length = RowInputView(), RowInputView(), RowInputView()
    fits, wide_enough = True, True
    form.add_validator(lambda: None if fits else "too big", rows=(radius, length))
    form.add_validator(lambda: None if wide_enough else "too thin", rows=(radius, width))

    fits, wide_enough = False, False
    form.validate()
    assert [row.has_form_error for row in (radius, width, length)] == [True, True, True]
    assert radius.is_invalid

    # the radius stays flagged while the other check naming it still fails
    fits = True
    form.validate()
    assert [row.has_form_error for row in (radius, width, length)] == [True, True, False]

    wide_enough = True
    form.validate()
    assert [row.is_invalid for row in (radius, width, length)] == [False, False, False]


def test_a_row_is_invalid_while_its_own_check_fails_too() -> None:
    row = RowInputView()
    row.set_validator(lambda: "required" if row.text == "" else None, row.text_edited)

    row.text_edited.emit("")
    assert row.is_invalid
    assert not row.has_form_error  # its own message, not its form's

    row.text = "hi"
    row.text_edited.emit("hi")
    assert not row.is_invalid
