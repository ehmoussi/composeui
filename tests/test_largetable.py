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


def test_the_form_sorts_the_table_s_rows(main_view: LargeTableMainView) -> None:
    form = main_view.form
    form.descending.is_checked = True
    form.sort.value = "temperature"
    form.sort.value_changed.emit("temperature")

    temperatures = _temperatures(main_view)
    assert len(temperatures) == ROWS
    assert temperatures == sorted(temperatures, reverse=True)
    assert main_view.info.text.startswith(f"{ROWS} of {ROWS} rows")


def test_a_temperature_filter_keeps_the_rows_it_passes_or_says_why_it_cannot(
    main_view: LargeTableMainView,
) -> None:
    temperature = main_view.form.temperature
    temperature.text = ">25"
    temperature.editing_finished.emit()
    assert _temperatures(main_view) != []
    assert all(value > 25 for value in _temperatures(main_view))

    count = main_view.table.row_count
    temperature.text = ">warm"
    temperature.editing_finished.emit()
    assert temperature.log_message == "Not a filter: not a number"
    assert main_view.table.row_count == count

    temperature.text = ">99"
    temperature.editing_finished.emit()
    assert (temperature.log_message, main_view.table.row_count) == ("", 0)
    assert main_view.info.text.startswith(f"0 of {ROWS} rows")


def test_a_study_saves_the_search_without_the_readings(
    main_view: LargeTableMainView, tmp_path: Path
) -> None:
    main_view.form.search.text = "Lyon"
    main_view.form.search.editing_finished.emit()
    path = tmp_path / "study.largetable"
    main_view.save_state(path)

    assert "Lyon" in path.read_text()
    assert "S-" not in path.read_text()
    main_view.table.search = ""
    main_view.load_state(path)
    sites = {cells[1] for _row_id, cells in main_view.table.rows(0, ROWS)}
    assert sites == {"Lyon"}


def test_choosing_a_sort_in_qt_s_list_sorts_the_rendered_table(qtbot: QtBot) -> None:
    qt_widgets = pytest.importorskip("qtpy.QtWidgets")
    qt_renderer = pytest.importorskip("composeui.qtcore.qtrenderer")
    main_view = LargeTableMainView()
    main_view.render(RendererType.QT)
    main_view.apply_arguments(argparse.Namespace(rows=ROWS))
    assert isinstance(main_view.renderer, qt_renderer.QtWidgetRenderer)
    window = main_view.renderer.qt_object
    qtbot.addWidget(window)
    combobox = window.findChild(qt_widgets.QComboBox)

    combobox.setCurrentIndex(combobox.findText("Temperature (°C)"))

    assert main_view.form.sort.value == "temperature"
    table = window.findChild(qt_widgets.QTableView)
    temperatures = [float(table.model().index(row, TEMPERATURE).data()) for row in range(ROWS)]
    assert len(temperatures) == ROWS
    assert temperatures == sorted(temperatures)
