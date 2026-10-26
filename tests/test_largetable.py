"""Tests of the example largetable: readings in SQLite, shown by a `DataTableView`."""

from __future__ import annotations

import argparse
import csv
from typing import TYPE_CHECKING, cast

import pytest

from composeui.core.application import ModelApplication
from composeui.core.registry import RendererType
from examples.largetable import LargeTableMainView, ReadingsModel, made_up

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from pytestqt.qtbot import QtBot

    from composeui.qtcore.qtrenderer import QtWidgetRenderer

ROWS = 300
TEMPERATURE = 2


App = ModelApplication[LargeTableMainView, ReadingsModel]


@pytest.fixture
def app() -> Iterator[App]:
    app = App(
        build_main_view=LargeTableMainView,
        build_model=ReadingsModel,
        setup_model=LargeTableMainView.connect_model,
    )
    yield app
    app.model.close()


@pytest.fixture
def main_view(app: App) -> LargeTableMainView:
    app.main_view.apply_arguments(argparse.Namespace(rows=ROWS))
    app.main_view.jobs.wait()
    return app.main_view


def test_the_readings_are_written_in_a_job_and_shown_once_written(app: App) -> None:
    app.main_view.apply_arguments(argparse.Namespace(rows=ROWS))
    assert app.main_view.info.text == f"Writing {ROWS} readings..."
    app.main_view.jobs.wait()
    assert app.main_view.table.row_count == ROWS
    # a study's readings, opened with -f: written already
    app.main_view.apply_arguments(argparse.Namespace(rows=ROWS))
    assert not app.main_view.jobs.is_running


def _temperatures(main_view: LargeTableMainView) -> list[float]:
    rows = main_view.table.rows(0, main_view.table.row_count)
    return [float(cells[TEMPERATURE]) for _row_id, cells in rows]


def test_each_order_of_the_rows_says_how_many_pass(main_view: LargeTableMainView) -> None:
    assert main_view.info.text.startswith(f"{ROWS} of {ROWS} rows, ordered in")
    main_view.table.search = "Lyon"  # as typed in the table's bar
    lyon = main_view.table.row_count
    assert 0 < lyon < ROWS
    assert main_view.info.text.startswith(f"{lyon} of {ROWS} rows")

    main_view.table.sort_by("temperature")  # as a click on its header

    temperatures = _temperatures(main_view)
    assert temperatures == sorted(temperatures)
    assert main_view.info.text.startswith(f"{lyon} of {ROWS} rows")


def test_the_bar_filters_any_column_saying_why_a_value_cannot(
    main_view: LargeTableMainView,
) -> None:
    table = main_view.table
    assert table.filter_error("temperature", "warm") == '"warm" isn\'t a number'
    table.filters = {"temperature": ">25", "status": "=fault"}

    assert 0 < table.row_count < ROWS
    assert all(value > 25 for value in _temperatures(main_view))
    assert {cells[4] for _row_id, cells in table.rows(0, table.row_count)} == {"fault"}
    assert main_view.info.text.startswith(f"{table.row_count} of {ROWS} rows")


def test_the_label_says_how_many_readings_are_selected_and_which_was_activated(
    main_view: LargeTableMainView,
) -> None:
    table = main_view.table
    table.select_at(0)
    table.extend_to(2)
    assert main_view.picked.text == "3 readings selected"

    table.activate_at(1)

    sensor, site, temperature = table.rows(1, 2)[0][1][:3]
    assert main_view.picked.text == f"{sensor} in {site}: {float(temperature)} °C"


def test_an_export_writes_the_rows_shown_in_a_job_the_status_bar_saying_so(
    main_view: LargeTableMainView, tmp_path: Path
) -> None:
    table = main_view.table
    table.search = "Lyon"
    table.sort_by("temperature")
    path = tmp_path / "lyon.csv"

    table.export_csv(path)
    assert main_view.jobs.is_running
    main_view.jobs.wait()

    with path.open(encoding="utf-8", newline="") as file:
        header, *rows = list(csv.reader(file))
    assert header == ["Sensor", "Site", "Temperature (°C)", "Pressure (kPa)", "Status"]
    assert len(rows) == table.row_count
    # in the table's order, each value in full: not as the table formats it
    shown = table.rows(0, len(rows))
    assert [row[0] for row in rows] == [cells[0] for _id, cells in shown]
    assert [float(row[TEMPERATURE]) for row in rows] == _temperatures(main_view)
    message = f"Exported {table.row_count} rows to lyon.csv."
    assert main_view.status_bar.message == message

    table.export_csv(tmp_path / "missing" / "lyon.csv")
    main_view.jobs.wait()
    assert main_view.status_bar.message.startswith("Can't export to lyon.csv: [Errno 2]")


def test_a_study_saves_the_search_without_the_readings(
    main_view: LargeTableMainView, tmp_path: Path
) -> None:
    main_view.table.search = "Lyon"
    path = tmp_path / "study.largetable"
    main_view.save_state(path)

    assert "Lyon" in path.read_text()
    assert "S-" not in path.read_text()
    main_view.table.search = ""
    main_view.load_state(path)
    sites = {cells[1] for _row_id, cells in main_view.table.rows(0, ROWS)}
    assert sites == {"Lyon"}


def test_a_click_on_a_header_in_qt_sorts_the_rendered_table(qtbot: QtBot) -> None:
    qt_widgets = pytest.importorskip("qtpy.QtWidgets")
    renderer_type: type[QtWidgetRenderer] = pytest.importorskip(
        "composeui.qtcore.qtrenderer"
    ).QtWidgetRenderer
    qt_core = pytest.importorskip("qtpy.QtCore")
    QPoint, Qt = qt_core.QPoint, qt_core.Qt  # noqa: N806 (Qt's own names)
    main_view, model = LargeTableMainView(), ReadingsModel()
    main_view.render(RendererType.QT)
    main_view.connect_model(model)
    model.readings.fill(ROWS)  # in the test's thread: no job to wait for
    renderer = main_view.renderer
    assert isinstance(renderer, renderer_type)
    window = cast("QtWidgetRenderer", renderer).qt_object
    assert window is not None
    qtbot.addWidget(window)
    table = window.findChild(qt_widgets.QTableView)
    header = table.horizontalHeader()
    window.show()
    qtbot.waitExposed(window)

    position = QPoint(header.sectionViewportPosition(TEMPERATURE) + 5, header.height() // 2)
    qtbot.mouseClick(header.viewport(), Qt.MouseButton.LeftButton, pos=position)

    assert main_view.table.sort_column == "temperature"
    temperatures = [float(table.model().index(row, TEMPERATURE).data()) for row in range(ROWS)]
    assert len(temperatures) == ROWS
    assert temperatures == sorted(temperatures)
    model.close()


def test_no_readings_asked_writes_none(app: App) -> None:
    app.main_view.apply_arguments(argparse.Namespace(rows=0))
    app.main_view.jobs.wait()

    assert app.main_view.table.total == 0


def test_the_made_up_readings_are_as_many_as_asked_the_same_each_time() -> None:
    readings = list(made_up(3))

    assert len(readings) == 3
    assert readings == list(made_up(3))


def test_the_rows_option_says_how_many_readings_to_write(
    app: App, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("sys.argv", ["largetable", "--rows", "5"])

    app.run()  # the command line, parsed as the app's
    app.main_view.jobs.wait()

    assert app.main_view.table.total == 5
