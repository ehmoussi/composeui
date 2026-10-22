"""Tests of the example largetable: readings in a `ListSource`, shown by a `DataTableView`."""

from __future__ import annotations

import argparse
from typing import TYPE_CHECKING

import pytest

from composeui.core.application import Application
from composeui.core.registry import RendererType
from examples.largetable import LargeTableMainView

if TYPE_CHECKING:
    from pathlib import Path

    from pytestqt.qtbot import QtBot

ROWS = 300
TEMPERATURE = 2


@pytest.fixture
def main_view() -> LargeTableMainView:
    main_view = Application(build_main_view=LargeTableMainView).main_view
    main_view.apply_arguments(argparse.Namespace(rows=ROWS))
    return main_view


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
    qt_renderer = pytest.importorskip("composeui.qtcore.qtrenderer")
    qt_core = pytest.importorskip("qtpy.QtCore")
    QPoint, Qt = qt_core.QPoint, qt_core.Qt  # noqa: N806 (Qt's own names)
    main_view = LargeTableMainView()
    main_view.render(RendererType.QT)
    main_view.apply_arguments(argparse.Namespace(rows=ROWS))
    assert isinstance(main_view.renderer, qt_renderer.QtWidgetRenderer)
    window = main_view.renderer.qt_object
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
