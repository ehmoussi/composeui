"""Test of the example pipeform."""

import time
from pathlib import Path

import pytest

from composeui.qtcore.qtapplication import QtApplication
from examples.pipeform import EdgeType, Material, PipeMainView


@pytest.fixture
def app() -> QtApplication[PipeMainView]:
    """Create app."""
    return QtApplication(main_view=PipeMainView())


def test_check_name(app: QtApplication[PipeMainView]) -> None:
    assert app.main_view.pages.inputs.pipe_form.name.log_message != ""
    app.main_view.pages.inputs.pipe_form.name.text = "PipeTShape"
    app.main_view.pages.inputs.pipe_form.name.text_edited.emit("PipeTShape")
    assert app.main_view.pages.inputs.pipe_form.name.log_message == ""
    assert app.main_view.pages.inputs.pipe_form.name.text == "PipeTShape"


def test_display_edge_options(app: QtApplication[PipeMainView]) -> None:
    assert app.main_view.pages.inputs.pipe_form.chamfer.is_visible is False
    assert app.main_view.pages.inputs.pipe_form.fillet.is_visible is False
    app.main_view.pages.inputs.pipe_form.edge_type.value = EdgeType.Chamfer
    app.main_view.pages.inputs.pipe_form.edge_type.value_changed.emit(EdgeType.Chamfer)
    assert app.main_view.pages.inputs.pipe_form.chamfer.is_visible is True
    assert app.main_view.pages.inputs.pipe_form.fillet.is_visible is False
    app.main_view.pages.inputs.pipe_form.edge_type.value = EdgeType.Fillet
    app.main_view.pages.inputs.pipe_form.edge_type.value_changed.emit(EdgeType.Fillet)
    assert app.main_view.pages.inputs.pipe_form.chamfer.is_visible is False
    assert app.main_view.pages.inputs.pipe_form.fillet.is_visible is True
    app.main_view.pages.inputs.pipe_form.edge_type.value = EdgeType.Normal
    app.main_view.pages.inputs.pipe_form.edge_type.value_changed.emit(EdgeType.Normal)
    assert app.main_view.pages.inputs.pipe_form.chamfer.is_visible is False
    assert app.main_view.pages.inputs.pipe_form.fillet.is_visible is False


def test_display_message_status_bar(app: QtApplication[PipeMainView]) -> None:
    # change timeout to speed up the test
    timeout = 0.1
    app.main_view.status_bar.timeout = timeout
    assert app.main_view.status_bar.message == ""
    app.main_view.pages.inputs.pipe_form.edge_type.value = EdgeType.Chamfer
    app.main_view.pages.inputs.pipe_form.edge_type.value_changed.emit(EdgeType.Chamfer)
    assert app.main_view.status_bar.message != ""
    time.sleep(1.1 * timeout)
    assert app.main_view.status_bar.message == ""


def test_display_error_message(app: QtApplication[PipeMainView]) -> None:
    assert app.main_view.pages.inputs.pipe_form.log_view.is_visible is False
    assert app.main_view.pages.inputs.pipe_form.log_view.log_message == ""
    # main radius + main width > incident half length
    app.main_view.pages.inputs.pipe_form.main_pipe.radius.value = 2000
    app.main_view.pages.inputs.pipe_form.main_pipe.radius.editing_finished.emit()
    assert app.main_view.pages.inputs.pipe_form.log_view.is_visible is True
    assert app.main_view.pages.inputs.pipe_form.log_view.log_message != ""
    assert len(app.main_view.pages.inputs.pipe_form.log_view.log_message.split("-")) == 2
    # incident_radius > main_radius
    app.main_view.pages.inputs.pipe_form.incident_pipe.radius.value = 20000
    app.main_view.pages.inputs.pipe_form.main_pipe.radius.editing_finished.emit()
    assert app.main_view.pages.inputs.pipe_form.log_view.is_visible is True
    assert app.main_view.pages.inputs.pipe_form.log_view.log_message != ""
    assert len(app.main_view.pages.inputs.pipe_form.log_view.log_message.split("-")) == 3
    # Go back to old values
    app.main_view.pages.inputs.pipe_form.main_pipe.radius.value = 20
    app.main_view.pages.inputs.pipe_form.main_pipe.radius.editing_finished.emit()
    app.main_view.pages.inputs.pipe_form.incident_pipe.radius.value = 20
    app.main_view.pages.inputs.pipe_form.main_pipe.radius.editing_finished.emit()
    assert app.main_view.pages.inputs.pipe_form.log_view.is_visible is False
    assert app.main_view.pages.inputs.pipe_form.log_view.log_message == ""


def test_resetting_the_dimensions_waits_for_the_confirmation(
    app: QtApplication[PipeMainView],
) -> None:
    main_view = app.main_view
    main_view.status_bar.timeout = 0
    radius = main_view.pages.inputs.pipe_form.main_pipe.radius
    radius.value = 2000
    radius.editing_finished.emit()
    assert main_view.pages.inputs.pipe_form.log_view.is_visible

    main_view.pipe_menu.reset_dimensions.triggered.emit()
    assert main_view.confirm_reset.is_visible
    main_view.confirm_reset.reject()
    assert radius.value == 2000

    main_view.pipe_menu.reset_dimensions.triggered.emit()
    main_view.confirm_reset.accept()
    assert radius.value == 50.0
    assert main_view.pages.results.summary.rows[0][1] == "50"
    assert not main_view.pages.inputs.pipe_form.log_view.is_visible


def test_the_pipe_form_in_french(app: QtApplication[PipeMainView]) -> None:
    view = app.main_view
    view.status_bar.timeout = 0
    pipe_form = view.pages.inputs.pipe_form
    pipe_form.incident_pipe.radius.value = 80.0
    pipe_form.validate()

    view.set_language("fr")

    assert pipe_form.main_pipe.title == "Conduite principale"
    assert pipe_form.name.log_message == "Un nom est obligatoire"
    assert pipe_form.log_view.log_message == (
        "- Le rayon incident ne peut pas dépasser le rayon principal : (80.0 > 50.0)"
    )
    assert list(pipe_form.edge_type.values) == ["Normale", "Chanfrein", "Congé"]
    assert view.pages.results.summary.headers == ["Conduite", "Rayon", "Largeur", "Demi-longueur"]
    assert [row[0] for row in view.pages.results.summary.rows] == [
        "Conduite principale",
        "Conduite incidente",
    ]
    pipe_form.edge_type.value = EdgeType.Fillet
    pipe_form.edge_type.value_changed.emit(EdgeType.Fillet)
    assert view.status_bar.message == "Type d'arête changé : Congé"


def test_a_study_saved_in_french_opens_in_english(tmp_path: Path) -> None:
    french = PipeMainView()
    french.set_language("fr")
    french.pages.inputs.pipe_form.edge_type.value = EdgeType.Chamfer
    french.pages.inputs.pipe_form.material.value = Material.Copper
    filepath = tmp_path / "study.pipe"
    french.save_state(filepath)

    english = PipeMainView()
    english.load_state(filepath)

    pipe_form = english.pages.inputs.pipe_form
    assert pipe_form.edge_type.value is EdgeType.Chamfer
    assert pipe_form.material.value is Material.Copper
    assert pipe_form.main_pipe.title == "Main Pipe"
