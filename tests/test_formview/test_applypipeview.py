from examples.formview.app import FormViewApp, Model
from examples.formview.example import ExampleMainView
from examples.formview.pipeapplyform import PipeApplyFormView
from examples.formview.pipeform import EdgeType

import pytest

from typing import Tuple


@pytest.fixture()
def app_apply_pipe(app: FormViewApp) -> Tuple[PipeApplyFormView, ExampleMainView, Model]:
    app.main_view.toolbar.navigation.pipe.is_checked = False
    app.main_view.toolbar.navigation.apply_pipe.is_checked = True
    app.main_view.toolbar.navigation.toggled()
    assert app.main_view.pipe_view.is_visible is False
    assert app.main_view.apply_pipe_view.is_visible is True
    return app.main_view.apply_pipe_view, app.main_view, app.model


def test_unmodify_db_before_apply(
    app_apply_pipe: Tuple[PipeApplyFormView, ExampleMainView, Model],
) -> None:
    view, _, model = app_apply_pipe
    assert model.apply_pipe_query.get_main_radius() == 80
    view.main.radius.field_view.value = 200
    view.main.radius.field_view.editing_finished()
    assert model.apply_pipe_query.get_main_radius() == 80


def test_apply(app_apply_pipe: Tuple[PipeApplyFormView, ExampleMainView, Model]) -> None:
    view, _, model = app_apply_pipe
    assert model.apply_pipe_query.get_main_radius() == 80
    view.main.radius.field_view.value = 75
    view.apply_clicked()
    assert model.apply_pipe_query.get_main_radius() == 75


def test_open_file_without_apply(
    app_apply_pipe: Tuple[PipeApplyFormView, ExampleMainView, Model],
) -> None:
    view, main_view, model = app_apply_pipe
    assert view.export.is_visible is True
    assert model.apply_pipe_query.get_export_path() is None
    assert view.export.field_view.text == ""
    main_view.file_view.save_file = lambda: "test.txt"  # type: ignore[method-assign]
    view.export.field_view.clicked()
    assert view.export.field_view.text == "test.txt"
    assert model.apply_pipe_query.get_export_path() is None


def test_update_visibility_without_apply(
    app_apply_pipe: Tuple[PipeApplyFormView, ExampleMainView, Model],
) -> None:
    view, _, model = app_apply_pipe
    assert model.apply_pipe_query.get_name() != ""
    assert view.name.field_view.text != ""
    assert model.apply_pipe_query.get_edge_type() == EdgeType.Normal
    assert view.edge_type.field_view.current_index == 0
    assert view.chamfer.is_visible is False
    view.edge_type.field_view.current_index = 1
    view.edge_type.field_view.current_index_changed()
    assert view.chamfer.is_visible is True
    assert model.apply_pipe_query.get_edge_type() == EdgeType.Normal


def test_update_visibility_with_incorrect_data(
    app_apply_pipe: Tuple[PipeApplyFormView, ExampleMainView, Model],
) -> None:
    view, _, model = app_apply_pipe
    view.main.radius.field_view.value = 500
    view.main.radius.field_view.editing_finished()
    assert model.apply_pipe_query.get_edge_type() == EdgeType.Normal
    assert view.edge_type.field_view.current_index == 0
    assert view.chamfer.is_visible is False
    view.edge_type.field_view.current_index = 1
    view.edge_type.field_view.current_index_changed()
    assert view.chamfer.is_visible is True
    assert model.apply_pipe_query.get_edge_type() == EdgeType.Normal
