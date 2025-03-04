from examples.formview.app import FormViewApp
from examples.formview.pipeform import EdgeType

import pytest

from pathlib import Path


@pytest.fixture()
def app_apply_pipe(app: FormViewApp) -> FormViewApp:
    app.main_view.toolbar.navigation.pipe.is_checked = False
    app.main_view.toolbar.navigation.apply_pipe.is_checked = True
    app.main_view.toolbar.navigation.toggled()
    assert app.main_view.pipe_view.is_visible is False
    assert app.main_view.apply_pipe_view.is_visible is True
    return app


def test_unmodify_db_before_apply(app_apply_pipe: FormViewApp) -> None:
    view, model = app_apply_pipe.main_view.apply_pipe_view, app_apply_pipe.model
    assert model.apply_pipe_query.get_main_radius() == 80
    view.main.radius.field_view.value = 200
    view.main.radius.field_view.editing_finished()
    assert model.apply_pipe_query.get_main_radius() == 80


def test_apply(app_apply_pipe: FormViewApp) -> None:
    view, model = app_apply_pipe.main_view.apply_pipe_view, app_apply_pipe.model
    assert model.apply_pipe_query.get_main_radius() == 80
    view.main.radius.field_view.value = 75
    view.apply_clicked()
    assert model.apply_pipe_query.get_main_radius() == 75


def test_open_file_without_apply(app_apply_pipe: FormViewApp) -> None:
    view, main_view, model = (
        app_apply_pipe.main_view.apply_pipe_view,
        app_apply_pipe.main_view,
        app_apply_pipe.model,
    )
    assert view.export.is_visible is True
    assert model.apply_pipe_query.get_export_path() is None
    assert view.export.field_view.text == ""
    main_view.file_view.save_file = lambda: "test.txt"  # type: ignore[method-assign]
    view.export.field_view.clicked()
    assert view.export.field_view.text == "test.txt"
    assert model.apply_pipe_query.get_export_path() is None


def test_update_visibility_without_apply(app_apply_pipe: FormViewApp) -> None:
    view, model = app_apply_pipe.main_view.apply_pipe_view, app_apply_pipe.model
    assert model.apply_pipe_query.get_name() != ""
    assert view.name.field_view.text != ""
    assert model.apply_pipe_query.get_edge_type() == EdgeType.Normal
    assert view.edge_type.field_view.current_index == 0
    assert view.chamfer.is_visible is False
    view.edge_type.field_view.current_index = 1
    view.edge_type.field_view.current_index_changed()
    assert view.chamfer.is_visible is True
    assert model.apply_pipe_query.get_edge_type() == EdgeType.Normal


def test_update_visibility_with_incorrect_data(app_apply_pipe: FormViewApp) -> None:
    view, model = app_apply_pipe.main_view.apply_pipe_view, app_apply_pipe.model
    assert view.items is not None
    assert view.items.is_visible("chamfer") is False
    assert view.chamfer.is_visible is False
    view.main.radius.field_view.value = 500
    view.main.radius.field_view.editing_finished()
    assert model.apply_pipe_query.get_edge_type() == EdgeType.Normal
    assert view.edge_type.field_view.current_index == 0
    assert view.items.is_visible("chamfer") is False
    assert view.chamfer.is_visible is False
    view.edge_type.field_view.current_index = 1
    view.edge_type.field_view.current_index_changed()
    assert view.items.is_enabled("chamfer") is True
    assert view.chamfer.is_visible is True
    assert model.apply_pipe_query.get_edge_type() == EdgeType.Normal


def test_save_open_file(app_apply_pipe: FormViewApp, tmpdir: Path) -> None:
    view, main_view = app_apply_pipe.main_view.apply_pipe_view, app_apply_pipe.main_view
    study_filepath = Path(tmpdir, "mystudy.qtexample")
    # default values
    assert view.name.field_view.text == "PipeTShape"
    assert view.main.radius.field_view.value == 80.0
    # modify values
    view.name.field_view.text = "New name"
    view.name.field_view.editing_finished()
    view.main.radius.field_view.value = 50.0
    view.main.radius.field_view.editing_finished()
    view.apply_clicked()
    # save the study
    main_view.file_view.save_file = lambda: str(study_filepath)  # type: ignore[method-assign]
    main_view.menu.file.save_as.triggered()
    # clean
    main_view.menu.file.new.triggered()
    assert view.name.field_view.text == "PipeTShape"
    assert view.main.radius.field_view.value == 80.0
    # open the study
    main_view.file_view.open_file = lambda: str(study_filepath)  # type: ignore[method-assign]
    main_view.menu.file.open_file.triggered()
    main_view.progress_popup_view.finished()
    assert view.is_visible is False  # when opening a study the visible view is the default one
    assert app_apply_pipe.model.filepath == study_filepath
    assert view.items is not None
    assert view.p_id.field_view.text == "2"
    assert view.items.get_value("name") == "New name"
    assert view.name.field_view.text == "New name"
    assert view.main.radius.field_view.value == 50.0
