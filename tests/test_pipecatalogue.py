"""Tests of the example pipecatalogue: views kept in step with a SQLite model."""

from __future__ import annotations

import datetime
import json
import sqlite3
import zipfile
from typing import TYPE_CHECKING

import pytest

from composeui.core.application import ModelApplication
from composeui.core.study import VIEWS_NAME
from composeui.core.view import NodeMark
from examples.pipecatalogue import (
    Material,
    PipeCatalogueMainView,
    PipeCatalogueModel,
    PipeExpander,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

App = ModelApplication[PipeCatalogueMainView, PipeCatalogueModel]


@pytest.fixture
def app() -> Iterator[App]:
    app = App(
        build_main_view=PipeCatalogueMainView,
        build_model=PipeCatalogueModel,
        setup_model=PipeCatalogueMainView.connect_model,
    )
    app.main_view.status_bar.timeout = 0
    yield app
    app.model.close()


def _add(
    app: App,
    name: str,
    material: Material = Material.STEEL,
    dimensions: tuple[float | None, float | None, float | None] = (50.0, 5.0, 6.0),
    installed: datetime.date | None = None,
) -> None:
    """Fill the sidebar's form and click its button.

    `dimensions` are the outer radius and the wall thickness (mm), and the length (m).
    """
    form = app.main_view.add.pipe
    form.name.text = name
    form.material.value = material
    form.radius.value, form.thickness.value, form.length.value = dimensions
    form.installed.value = installed
    app.main_view.add.add_pipe.clicked.emit()


def _expanders(app: App) -> list[PipeExpander]:
    views = app.main_view.catalogue.browser.pipes.item_views
    expanders = [view for view in views if isinstance(view, PipeExpander)]
    assert len(expanders) == len(views)
    return expanders


def _listed(app: App) -> list[list[str]]:
    """Get each pipe listed: its name, material and mass, then its dimensions."""
    return [[expander.title, expander.details.text] for expander in _expanders(app)]


def _names(app: App) -> list[str]:
    return [expander.title.split(" · ")[0] for expander in _expanders(app)]


def test_the_tree_shows_the_pipes_listed_by_material_and_expands_the_one_selected(
    app: App,
) -> None:
    tree = app.main_view.catalogue.browser.tree
    _add(app, "Main line", installed=datetime.date(2024, 3, 12))
    _add(app, "Return", Material.COPPER, (20.0, 2.0, 3.0))
    _add(app, "Feed")
    assert [(node.label, [pipe.label for pipe in node.children]) for node in tree.nodes] == [
        ("Steel", ["Feed", "Main line"]),
        ("Copper", ["Return"]),
    ]
    # a material in bold, a pipe marked by whether its installation date is known
    assert all(node.is_bold for node in tree.nodes)
    assert [pipe.mark for node in tree.nodes for pipe in node.children] == [
        NodeMark.WARNING,
        NodeMark.DONE,
        NodeMark.WARNING,
    ]

    tree.expanded = [("STEEL",)]
    tree.selected = ("STEEL", "Main line")  # as the user's click leaves it
    tree.selection_changed.emit(tree.selected)
    assert [expander.is_expanded for expander in _expanders(app)] == [False, True, False]
    tree.selected = ("STEEL",)
    tree.selection_changed.emit(tree.selected)  # a material: nothing more expanded
    assert [expander.is_expanded for expander in _expanders(app)] == [False, True, False]

    tree.selected = ("STEEL", "Feed")
    # the filter, then the model, change the tree: what is still there stays as it was
    material = app.main_view.catalogue.shown.material
    material.value = Material.STEEL.value
    material.value_changed.emit(material.value)
    assert [node.key for node in tree.nodes] == ["STEEL"]
    app.model.pipes.delete("Main line")
    assert (tree.expanded, tree.selected) == ([("STEEL",)], ("STEEL", "Feed"))
    app.model.pipes.delete("Feed")
    assert (tree.nodes, tree.expanded, tree.selected) == ([], [], None)


def test_the_catalogue_lists_filters_and_removes_the_pipes_added(app: App) -> None:
    catalogue = app.main_view.catalogue
    _add(app, "Main line", installed=datetime.date(2024, 3, 12))
    _add(app, "Return", Material.COPPER, (20.0, 2.0, 3.0))

    assert _listed(app) == [
        [
            "Main line · Steel · 70.3 kg",
            "Outer radius 50 mm, wall 5 mm, 6 m long, installed 03/12/2024",
        ],
        [
            "Return · Copper · 6.4 kg",
            "Outer radius 20 mm, wall 2 mm, 3 m long, installed on an unknown date",
        ],
    ]
    assert catalogue.total.text == "2 pipes, 76.7 kg"
    assert app.main_view.status_bar.message == "Added 'Return'"

    installed_from = catalogue.shown.installed_from
    installed_from.value = datetime.date(2024, 1, 1)
    installed_from.value_changed.emit(installed_from.value)
    assert _names(app) == ["Main line"]  # the other's date is unknown
    installed_from.value = None
    installed_from.value_changed.emit(None)
    assert _names(app) == ["Main line", "Return"]

    catalogue.shown.min_radius.value = 30.0
    catalogue.shown.min_radius.editing_finished.emit()
    assert _names(app) == ["Main line"]
    assert catalogue.total.text == "1 pipe, 70.3 kg"

    catalogue.remove_shown.clicked.emit()
    app.main_view.confirm_remove.accept()
    assert _names(app) == []
    catalogue.shown.min_radius.value = None
    catalogue.shown.min_radius.editing_finished.emit()
    assert _names(app) == ["Return"]


def test_a_pipe_s_delete_button_removes_it_from_the_database(app: App) -> None:
    _add(app, "Main line")
    _add(app, "Return", Material.COPPER, (20.0, 2.0, 3.0))
    main_line, ret = _expanders(app)

    # built from the model's rows: its callback gets the model
    main_line.buttons.delete.clicked.emit()

    (kept,) = _expanders(app)
    assert kept is ret
    assert app.model.pipes.total(app.main_view.catalogue.shown.shown()).count == 1
    assert app.main_view.status_bar.message == "Deleted 'Main line'"


def test_a_pipe_s_edit_button_changes_it_in_a_form_dialog(app: App) -> None:
    _add(app, "Main line")
    (main_line,) = _expanders(app)
    dialog = app.main_view.edit_dialog

    main_line.buttons.edit.clicked.emit()  # the pipe's values, as the database has them
    assert dialog.is_visible
    assert (dialog.form.name.text, dialog.form.radius.value) == ("Main line", 50.0)
    assert dialog.form.installed.value is None
    dialog.form.name.text = "Feed"
    dialog.form.material.value = Material.COPPER
    dialog.form.installed.value = datetime.date(2025, 6, 1)
    dialog.accept()

    assert not dialog.is_visible
    # copper: the mass follows its density
    assert _listed(app) == [
        ["Feed · Copper · 80.2 kg", "Outer radius 50 mm, wall 5 mm, 6 m long, installed 06/01/2025"]
    ]
    assert app.main_view.status_bar.message == "Saved 'Feed'"


def test_an_edit_failing_the_form_s_checks_keeps_the_dialog_open(app: App) -> None:
    _add(app, "Main line")
    (main_line,) = _expanders(app)
    dialog = app.main_view.edit_dialog
    main_line.buttons.edit.clicked.emit()

    dialog.form.name.text = ""
    dialog.form.name.text_edited.emit("")  # as typing does
    assert not dialog.is_accept_enabled
    dialog.accept()

    assert dialog.is_visible
    assert _names(app) == ["Main line"]


def test_an_edit_the_database_refuses_is_not_saved_and_says_why(app: App) -> None:
    _add(app, "Main line")
    _add(app, "Return", Material.COPPER, (20.0, 2.0, 3.0))
    ret = _expanders(app)[1]
    ret.buttons.edit.clicked.emit()

    app.main_view.edit_dialog.form.name.text = "Main line"  # passes the form, not the table
    app.main_view.edit_dialog.accept()

    assert app.main_view.status_bar.message == "Can't save the pipe: another pipe has this name."
    assert _names(app) == ["Main line", "Return"]


@pytest.mark.parametrize(
    ("name", "radius", "thickness", "reason"),
    [
        ("Main line", 50.0, 5.0, "another pipe has this name"),
        ("", 50.0, 5.0, "it needs a name"),
        ("Thick", 10.0, 10.0, "its wall must be thinner than its radius"),
        ("Flat", -1.0, 5.0, "its dimensions must be positive"),
        ("Unknown", None, 5.0, "every dimension is needed"),
    ],
)
def test_a_pipe_the_database_refuses_is_not_added_and_says_why(
    app: App, name: str, radius: float | None, thickness: float, reason: str
) -> None:
    _add(app, "Main line")

    _add(app, name, dimensions=(radius, thickness, 6.0))

    assert app.main_view.status_bar.message == f"Can't add the pipe: {reason}."
    assert _names(app) == ["Main line"]


def test_a_pipe_can_t_be_installed_in_the_future(app: App) -> None:
    installed = app.main_view.add.pipe.installed
    tomorrow = installed.maximum + datetime.timedelta(days=1)  # today's, built with it

    installed.value = tomorrow
    installed.value_changed.emit(tomorrow)  # as typing it does: only the calendar refuses it
    assert installed.log_message == "A pipe can't be installed in the future"
    installed.value = None
    installed.value_changed.emit(None)
    assert installed.log_message == ""


#: the pipe table and view of a study saved before pipes had an installation date
_VERSION_1 = """
    CREATE TABLE material(name TEXT PRIMARY KEY, density REAL NOT NULL);
    INSERT INTO material(name, density) VALUES ('Steel', 7850);
    CREATE TABLE pipe(
        id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, material TEXT NOT NULL,
        radius REAL NOT NULL, thickness REAL NOT NULL, length REAL NOT NULL
    );
    INSERT INTO pipe(name, material, radius, thickness, length)
        VALUES ('Main line', 'Steel', 50, 5, 6);
    CREATE VIEW pipe_mass AS SELECT pipe.name, material, radius, thickness, length,
        3.141592653589793 * (radius * radius - (radius - thickness) * (radius - thickness))
            * 1e-6 * length * material.density AS mass
    FROM pipe JOIN material ON material.name = pipe.material;
    PRAGMA user_version = 1;
"""


def test_a_study_from_before_the_installation_dates_opens_its_pipes_without_one(
    app: App, tmp_path: Path
) -> None:
    data = tmp_path / "data.sqlite"
    db = sqlite3.connect(data)
    db.executescript(_VERSION_1)
    db.close()
    path = tmp_path / "old.pipes"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(VIEWS_NAME, json.dumps(app.main_view.state_data()))
        archive.write(data, app.model.data_name)

    app.main_view.file_view.filepath = path
    app.main_view.file_menu.open_file.triggered.emit()

    assert _listed(app) == [
        [
            "Main line · Steel · 70.3 kg",
            "Outer radius 50 mm, wall 5 mm, 6 m long, installed on an unknown date",
        ]
    ]
    (main_line,) = _expanders(app)
    main_line.buttons.edit.clicked.emit()
    app.main_view.edit_dialog.form.installed.value = datetime.date(2020, 5, 4)
    app.main_view.edit_dialog.accept()
    assert _listed(app)[0][1].endswith("installed 05/04/2020")  # the column added


def test_an_opened_catalogue_lists_its_pipes_through_its_own_filter(
    app: App, tmp_path: Path
) -> None:
    _add(app, "Main line")
    _add(app, "Return", Material.COPPER, (20.0, 2.0, 3.0))
    app.main_view.catalogue.shown.material.value = "Copper"
    path = tmp_path / "plant.pipes"
    app.main_view.file_view.filepath = path
    app.main_view.file_menu.save.triggered.emit()
    other = App(
        build_main_view=PipeCatalogueMainView,
        build_model=PipeCatalogueModel,
        setup_model=PipeCatalogueMainView.connect_model,
    )

    other.main_view.file_view.filepath = path
    other.main_view.file_menu.open_file.triggered.emit()

    assert _names(other) == ["Return"]
    other.main_view.file_menu.new.triggered.emit()
    assert _names(other) == []
    assert other.main_view.catalogue.total.text == "0 pipes, 0.0 kg"
    other.model.close()
