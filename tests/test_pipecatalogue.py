"""Tests of the example pipecatalogue: views kept in step with a SQLite model."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from composeui.core.application import ModelApplication
from examples.pipecatalogue import (
    Material,
    PipeCatalogueMainView,
    PipeCatalogueModel,
    connect_model,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

App = ModelApplication[PipeCatalogueMainView, PipeCatalogueModel]


@pytest.fixture
def app() -> Iterator[App]:
    app = App(main_view=PipeCatalogueMainView(), model=PipeCatalogueModel())
    app.main_view.status_bar.timeout = 0
    connect_model(app.main_view, app.model)
    yield app
    app.model.close()


def _add(
    app: App,
    name: str,
    material: Material = Material.STEEL,
    dimensions: tuple[float | None, float | None, float | None] = (50.0, 5.0, 6.0),
) -> None:
    """Fill the Add page's form and click its button.

    `dimensions` are the outer radius and the wall thickness (mm), and the length (m).
    """
    form = app.main_view.pages.add.pipe
    form.name.text = name
    form.material.value = material
    form.radius.value, form.thickness.value, form.length.value = dimensions
    app.main_view.pages.add.add_pipe.clicked.emit()


def _listed(app: App) -> list[list[str]]:
    return app.main_view.pages.catalogue.pipes.rows


def test_the_catalogue_lists_filters_and_removes_the_pipes_added(app: App) -> None:
    catalogue = app.main_view.pages.catalogue
    _add(app, "Main line")
    _add(app, "Return", Material.COPPER, (20.0, 2.0, 3.0))

    assert _listed(app) == [
        ["Main line", "Steel", "50", "5", "6", "70.3"],
        ["Return", "Copper", "20", "2", "3", "6.4"],
    ]
    assert catalogue.total.text == "2 pipes, 76.7 kg"
    assert app.main_view.status_bar.message == "Added 'Return'"

    catalogue.shown.min_radius.value = 30.0
    catalogue.shown.min_radius.editing_finished.emit()
    assert [row[0] for row in _listed(app)] == ["Main line"]
    assert catalogue.total.text == "1 pipe, 70.3 kg"

    catalogue.remove_shown.clicked.emit()
    app.main_view.confirm_remove.accept()
    assert _listed(app) == []
    catalogue.shown.min_radius.value = None
    catalogue.shown.min_radius.editing_finished.emit()
    assert [row[0] for row in _listed(app)] == ["Return"]


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
    assert [row[0] for row in _listed(app)] == ["Main line"]


def test_an_opened_catalogue_lists_its_pipes_through_its_own_filter(
    app: App, tmp_path: Path
) -> None:
    _add(app, "Main line")
    _add(app, "Return", Material.COPPER, (20.0, 2.0, 3.0))
    app.main_view.pages.catalogue.shown.material.value = "Copper"
    path = tmp_path / "plant.pipes"
    app.main_view.file_view.filepath = path
    app.main_view.file_menu.save.triggered.emit()
    other = App(main_view=PipeCatalogueMainView(), model=PipeCatalogueModel())
    connect_model(other.main_view, other.model)

    other.main_view.file_view.filepath = path
    other.main_view.file_menu.open_file.triggered.emit()

    assert [row[0] for row in _listed(other)] == ["Return"]
    other.main_view.file_menu.new.triggered.emit()
    assert _listed(other) == []
    assert other.main_view.pages.catalogue.total.text == "0 pipes, 0.0 kg"
    other.model.close()
