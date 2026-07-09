"""Test of the example pipeform."""

import time

import pytest

from examples.pipeform import EdgeType, PipeApp


@pytest.fixture
def app() -> PipeApp:
    """Create app."""
    return PipeApp()


def test_check_name(app: PipeApp) -> None:
    assert app.main_view.pipe_form.name.log_message != ""
    app.main_view.pipe_form.name.text = "PipeTShape"
    app.main_view.pipe_form.name.text_edited.emit("PipeTShape")
    assert app.main_view.pipe_form.name.log_message == ""
    assert app.main_view.pipe_form.name.text == "PipeTShape"


def test_display_edge_options(app: PipeApp) -> None:
    assert app.main_view.pipe_form.chamfer.is_visible is False
    assert app.main_view.pipe_form.fillet.is_visible is False
    app.main_view.pipe_form.edge_type.value = EdgeType.Chamfer
    app.main_view.pipe_form.edge_type.value_changed.emit(EdgeType.Chamfer)
    assert app.main_view.pipe_form.chamfer.is_visible is True
    assert app.main_view.pipe_form.fillet.is_visible is False
    app.main_view.pipe_form.edge_type.value = EdgeType.Fillet
    app.main_view.pipe_form.edge_type.value_changed.emit(EdgeType.Fillet)
    assert app.main_view.pipe_form.chamfer.is_visible is False
    assert app.main_view.pipe_form.fillet.is_visible is True
    app.main_view.pipe_form.edge_type.value = EdgeType.Normal
    app.main_view.pipe_form.edge_type.value_changed.emit(EdgeType.Normal)
    assert app.main_view.pipe_form.chamfer.is_visible is False
    assert app.main_view.pipe_form.fillet.is_visible is False


def test_display_message_status_bar(app: PipeApp) -> None:
    # change timeout to speed up the test
    timeout = 0.1
    app.main_view.status_bar.timeout = timeout
    assert app.main_view.status_bar.message == ""
    app.main_view.pipe_form.edge_type.value = EdgeType.Chamfer
    app.main_view.pipe_form.edge_type.value_changed.emit(EdgeType.Chamfer)
    assert app.main_view.status_bar.message != ""
    time.sleep(1.1 * timeout)
    assert app.main_view.status_bar.message == ""


def test_display_error_message(app: PipeApp) -> None:
    assert app.main_view.pipe_form.log_view.is_visible is False
    assert app.main_view.pipe_form.log_view.log_message == ""
    # main radius + main width > incident half length
    app.main_view.pipe_form.main_pipe.radius.value = 2000
    app.main_view.pipe_form.main_pipe.radius.editing_finished.emit()
    assert app.main_view.pipe_form.log_view.is_visible is True
    assert app.main_view.pipe_form.log_view.log_message != ""
    assert len(app.main_view.pipe_form.log_view.log_message.split("-")) == 2
    # incident_radius > main_radius
    app.main_view.pipe_form.incident_pipe.radius.value = 20000
    app.main_view.pipe_form.main_pipe.radius.editing_finished.emit()
    assert app.main_view.pipe_form.log_view.is_visible is True
    assert app.main_view.pipe_form.log_view.log_message != ""
    assert len(app.main_view.pipe_form.log_view.log_message.split("-")) == 3
    # Go back to old values
    app.main_view.pipe_form.main_pipe.radius.value = 20
    app.main_view.pipe_form.main_pipe.radius.editing_finished.emit()
    app.main_view.pipe_form.incident_pipe.radius.value = 20
    app.main_view.pipe_form.main_pipe.radius.editing_finished.emit()
    assert app.main_view.pipe_form.log_view.is_visible is False
    assert app.main_view.pipe_form.log_view.log_message == ""
