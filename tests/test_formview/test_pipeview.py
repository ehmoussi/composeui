from examples.formview.app import FormViewApp, Model
from examples.formview.example import ExampleMainView
from examples.formview.pipeform import EdgeType, PipeFormView

import pytest

from pathlib import Path
from typing import Tuple


@pytest.fixture()
def app_pipe(app: FormViewApp) -> Tuple[PipeFormView, ExampleMainView, Model]:
    return app.main_view.pipe_view, app.main_view, app.model


def test_update_name(app_pipe: Tuple[PipeFormView, ExampleMainView, Model]) -> None:
    view, _, model = app_pipe
    assert view.name.field_view.text == "PipeTShape"
    assert model.pipe_query.get_name() == "PipeTShape"
    view.name.field_view.text = "My Pipe"
    view.name.field_view.editing_finished()
    assert model.pipe_query.get_name() == "My Pipe"


def test_update_export_path(app_pipe: Tuple[PipeFormView, ExampleMainView, Model]) -> None:
    view, main_view, model = app_pipe
    assert model.pipe_query.get_export_path() is None
    assert view.export.field_view.text == ""
    main_view.file_view.save_file = lambda: "/path/to/file"  # type: ignore[method-assign]
    view.export.field_view.clicked()
    assert model.pipe_query.get_export_path() == Path("/path/to/file")
    view.export.field_view.text = "/path/to/file2"
    view.export.field_view.editing_finished()
    assert model.pipe_query.get_export_path() == Path("/path/to/file2")


def test_update_main_radius(app_pipe: Tuple[PipeFormView, ExampleMainView, Model]) -> None:
    view, _, model = app_pipe
    assert model.pipe_query.get_main_radius() == 80.0
    view.main.radius.field_view.value = 150.0
    view.main.radius.field_view.editing_finished()
    assert model.pipe_query.get_main_radius() == 150.0
    view.main.radius.field_view.value = -150.0
    view.main.radius.field_view.editing_finished()
    assert model.pipe_query.get_main_radius() == 150.0


def test_update_edge_type(app_pipe: Tuple[PipeFormView, ExampleMainView, Model]) -> None:
    view, _, model = app_pipe
    assert model.pipe_query.get_edge_type() == EdgeType.Normal
    view.edge_type.field_view.current_index = 1
    view.edge_type.field_view.current_index_changed()
    assert model.pipe_query.get_edge_type() == EdgeType.Chamfer
    assert view.edge_type.items is not None
    assert view.edge_type.items.get_current_index("edge_type") == 1
    assert view.edge_type.items.get_value("edge_type") == 1


def test_color(app_pipe: Tuple[PipeFormView, ExampleMainView, Model]) -> None:
    view, _, _ = app_pipe
    # initial state
    assert view.main.radius.field_view.color is None
    assert view.main.infos == ""
    assert view.incident.infos == ""
    # modify radius with a forbidden value
    view.main.radius.field_view.value = 800.0
    view.main.radius.field_view.editing_finished()
    # check
    assert view.main.radius.field_view.color == (255, 0, 0)
    assert view.main.width.field_view.color == (255, 0, 0)
    assert view.main.infos != ""
    assert view.incident.half_length.field_view.color == (255, 0, 0)
    assert view.incident.infos != ""


def test_is_visible(app_pipe: Tuple[PipeFormView, ExampleMainView, Model]) -> None:
    view, _, _ = app_pipe
    # initial state
    assert view.chamfer.is_visible is False
    assert view.fillet.is_visible is False
    # update edge type to chamfer
    view.edge_type.field_view.current_index = EdgeType.Chamfer.value
    view.edge_type.field_view.current_index_changed()
    # check visibility
    assert view.chamfer.is_visible is True
    assert view.fillet.is_visible is False
    # update edge type to fillet
    view.edge_type.field_view.current_index = EdgeType.Fillet.value
    view.edge_type.field_view.current_index_changed()
    # check visibility
    assert view.chamfer.is_visible is False
    assert view.fillet.is_visible is True
    # go back to initial state
    view.edge_type.field_view.current_index = EdgeType.Normal.value
    view.edge_type.field_view.current_index_changed()
    # check visibility
    assert view.chamfer.is_visible is False
    assert view.fillet.is_visible is False


def test_is_enabled(app_pipe: Tuple[PipeFormView, ExampleMainView, Model]) -> None:
    view, _, _ = app_pipe
    assert view.p_id.label_view.is_enabled is True
    assert view.p_id.field_view.is_enabled is False
