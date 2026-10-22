"""The large table's view, in core: what it reads from its source, and what it keeps."""

from __future__ import annotations

import enum
import tracemalloc
from typing import TYPE_CHECKING, Any, Optional

import attrs
import pytest

from composeui.core.view import (
    DATA_TABLE_CACHE,
    DATA_TABLE_WINDOW,
    DataTableView,
    FilterError,
    ListSource,
    MainView,
    SelectionMode,
    child,
    define_view,
)
from tests.tables import MillionSource

if TYPE_CHECKING:
    from collections.abc import Hashable, Mapping, Sequence
    from pathlib import Path

    from composeui.core.view import Filter, Sort


class Kind(enum.Enum):
    PROBE = "probe"
    GAUGE = "gauge"


@attrs.frozen
class Sample:
    name: str
    value: float
    kind: Kind = Kind.PROBE
    note: Optional[float] = None


def _samples(count: int) -> list[Sample]:
    return [
        Sample(f"s{index:04d}", index / 4, Kind.GAUGE if index % 3 == 0 else Kind.PROBE)
        for index in range(count)
    ]


class CountingSource(ListSource[Sample]):
    """A list source that records what a table asks it for."""

    def __init__(self, samples: Sequence[Sample]) -> None:
        super().__init__(
            Sample, {"name": "Name", "value": "Value", "kind": "Kind", "note": "Note"}, samples
        )
        self.orders = 0
        self.read: list[list[Hashable]] = []

    def ordered_ids(
        self, sort: Optional[Sort], search: str, filters: Mapping[str, Filter]
    ) -> list[Hashable]:
        self.orders += 1
        return super().ordered_ids(sort, search, filters)

    def cells(self, ids: Sequence[Hashable], columns: Sequence[str]) -> dict[Hashable, list[Any]]:
        self.read.append(list(ids))
        return super().cells(ids, columns)


@pytest.fixture
def source() -> CountingSource:
    return CountingSource(_samples(1000))


@pytest.fixture
def table(source: CountingSource) -> DataTableView:
    return DataTableView(source=source)


def test_rows_read_the_windows_of_the_rows_asked_once(
    table: DataTableView, source: CountingSource
) -> None:
    assert (table.row_count, source.orders) == (1000, 1)
    assert table.headers == ["Name", "Value", "Kind", "Note"]

    assert [row_id for row_id, _cells in table.rows(0, 50)] == list(range(50))
    assert source.read == [list(range(DATA_TABLE_WINDOW))]
    # half of it read already: only the next window
    assert len(table.rows(150, 250)) == 100
    assert source.read[1:] == [list(range(DATA_TABLE_WINDOW, 2 * DATA_TABLE_WINDOW))]
    table.rows(0, 50)
    assert len(source.read) == 2
    assert table.rows(990, 2000)[-1][0] == 999
    assert (table.rows(1000, 1100), table.rows(-5, 0)) == ([], [])


def test_the_rows_read_first_go_once_more_rows_are_read_than_the_cache_keeps() -> None:
    source = CountingSource(_samples(2 * DATA_TABLE_CACHE))
    table = DataTableView(source=source)
    table.rows(0, 1)
    # the next rows, as many as the cache keeps: the first window goes
    table.rows(DATA_TABLE_WINDOW, DATA_TABLE_WINDOW + DATA_TABLE_CACHE)
    assert len(source.read) == 2

    table.rows(0, 1)
    assert source.read[2:] == [list(range(DATA_TABLE_WINDOW))]


def test_rows_known_by_text_ids_read_as_rows_known_by_numbers() -> None:
    samples = ListSource(Sample, {"value": "Value"}, _samples(3), id_field="name")
    table = DataTableView(source=samples, sort_column="value", sort_descending=True)

    assert table.rows(0, 2) == [("s0002", ["0.5"]), ("s0001", ["0.25"])]


def test_rows_format_each_column_s_values(source: CountingSource) -> None:
    source.records = [Sample("a", 1.25, Kind.GAUGE, None), Sample("b", 2.0, note=0.5)]
    table = DataTableView(source=source, column_formats={"value": ".1f", "note": ".0%"})

    assert table.rows(0, 2) == [(0, ["a", "1.2", "gauge", ""]), (1, ["b", "2.0", "probe", "50%"])]
    table.column_formats = {"name": ".1f"}  # a format for numbers: the text as it is
    assert table.rows(0, 1) == [(0, ["a", "1.25", "gauge", ""])]


def test_the_sort_the_search_and_the_filters_read_the_order_again(
    table: DataTableView, source: CountingSource
) -> None:
    table.rows(0, 10)

    table.sort_column, table.sort_descending = "value", True
    assert table.ids(0, 3) == [999, 998, 997]
    table.search = "s000"
    assert table.ids(0, 20) == [9, 8, 7, 6, 5, 4, 3, 2, 1, 0]
    table.filters = {"value": "<1", "kind": "=gauge"}
    assert (table.ids(0, 20), table.row_count) == ([3, 0], 2)
    table.search = "s000"  # unchanged
    assert source.orders == 5
    # the rows already read, in another order
    assert [row_id for row_id, _cells in table.rows(0, 2)] == [3, 0]
    assert len(source.read) == 1


def test_a_header_s_clicks_sort_ascending_descending_then_as_the_source_gives(
    table: DataTableView, source: CountingSource
) -> None:
    table.sort_by("kind")
    assert (table.sort_column, table.sort_descending) == ("kind", False)
    assert table.ids(0, 3) == [0, 3, 6]  # "gauge" before "probe", ties in the source's order
    table.sort_by("kind")
    assert (table.sort_column, table.sort_descending) == ("kind", True)
    table.sort_by("value")  # another column: ascending again, the source asked once
    assert (table.sort_column, table.sort_descending, table.ids(0, 2)) == ("value", False, [0, 1])
    assert source.orders == 4
    table.sort_by("value")
    table.sort_by("value")
    assert (table.sort_column, table.sort_descending, table.ids(0, 2)) == (None, False, [0, 1])

    with pytest.raises(ValueError, match="sort by DataTableView's column 'mass'"):
        table.sort_by("mass")


def test_the_filter_bar_reads_its_count_chips_errors_and_hints_by_column_name(
    table: DataTableView,
) -> None:
    assert table.count_text == ""  # every row shown
    table.filters = {"value": ">=249.5", "name": "/s09[89]/"}
    assert table.count_text == "2 of 1,000"
    assert table.filter_chip("value") == "Value: >=249.5"
    assert table.filter_chip("name") == "Name matches s09[89]"
    assert table.filter_error("value", "heavy") == '"heavy" isn\'t a number'
    assert table.filter_error("value", "<3") is None
    assert table.filter_takes_pattern("name")
    assert not table.filter_takes_pattern("value")
    assert table.filter_placeholder("value") == ">=20, 18..24"
    with pytest.raises(ValueError, match="filter DataTableView's column 'mass'"):
        table.filter_error("mass", "1")


def test_the_settings_name_the_source_s_columns(table: DataTableView) -> None:
    with pytest.raises(ValueError, match="sort by DataTableView's column 'mass'"):
        table.sort_column = "mass"
    with pytest.raises(ValueError, match="filter DataTableView's column 'mass'"):
        table.filters = {"mass": ">1"}
    with pytest.raises(FilterError):
        table.filters = {"value": ">heavy"}
    assert (table.sort_column, table.filters) == (None, {})


def test_the_source_s_change_reads_the_order_and_the_rows_again(
    table: DataTableView, source: CountingSource
) -> None:
    table.rows(0, 10)

    source.records = [*_samples(3), Sample("new", 9.0)]

    assert (table.row_count, source.orders) == (4, 2)
    assert table.rows(3, 4) == [(3, ["new", "9.0", "probe", ""])]
    assert len(source.read) == 2


def test_a_row_gone_from_the_source_shows_empty_cells_until_its_change(
    table: DataTableView, source: CountingSource
) -> None:
    # gone without a change: as a source read while another thread deletes its rows
    source._set_records(_samples(5))  # noqa: SLF001

    assert table.rows(4, 6) == [(4, ["s0004", "1.0", "probe", ""]), (5, ["", "", "", ""])]


def test_a_new_order_drops_the_selected_rows_it_hides(table: DataTableView) -> None:
    emitted: list[list[Any]] = []
    table.selection_changed.connect(emitted.append)
    table.selection_mode = SelectionMode.MULTIPLE
    table.selected_ids = [5, 1]

    table.filters = {"value": ">1"}
    assert (table.selected_ids, emitted) == ([5], [[5]])
    table.filters = {"value": ">0.5"}  # still shown: no change
    assert emitted == [[5]]

    with pytest.raises(ValueError, match="a row is selected twice"):
        table.selected_ids = [5, 5]
    table.selected_ids = [5, 9]
    table.selection_mode = SelectionMode.SINGLE
    assert table.selected_ids == [5]
    with pytest.raises(ValueError, match="selects a single row"):
        table.selected_ids = [5, 9]


def test_the_user_s_clicks_select_a_row_or_toggle_rows_saying_so(
    table: DataTableView,
) -> None:
    emitted: list[list[Any]] = []
    table.selection_changed.connect(emitted.append)
    table.sort_column, table.sort_descending = "value", True

    table.select_at(0)
    table.select_at(0)  # already selected: no change
    table.select_at(1)
    assert (table.selected_ids, emitted) == ([998], [[999], [998]])
    assert table.is_selected(998)
    assert not table.is_selected(999)

    table.selection_mode = SelectionMode.MULTIPLE
    table.select_at(3)
    table.select_at(1)  # selected: removed
    assert table.selected_ids == [996]
    table.select_at(2_000)  # no row there
    assert len(emitted) == 4


def test_a_shift_click_adds_the_rows_from_the_one_selected_last(table: DataTableView) -> None:
    table.selection_mode = SelectionMode.MULTIPLE
    table.selected_ids = [500]
    table.extend_to(3)  # none selected by the user yet: a click
    table.extend_to(5)
    assert table.selected_ids == [500, 3, 4, 5]
    table.select_at(900)
    table.extend_to(898)  # backwards, rows never read
    assert table.selected_ids == [500, 3, 4, 5, 900, 898, 899]

    table.search = "s0"  # a new order: its positions start no range
    table.extend_to(1)
    assert table.selected_ids[-1] == 1

    table.selection_mode = SelectionMode.SINGLE
    table.extend_to(7)
    assert table.selected_ids == [7]


def test_ctrl_c_copies_the_selected_rows_as_shown_tab_separated(
    table: DataTableView, source: CountingSource
) -> None:
    assert table.selection_text() == ""
    source.records = [
        Sample("a\tb", 1.25, Kind.GAUGE, None),
        Sample("multi\nline", 2.0),
        Sample("c", 3.0),
    ]
    table.column_formats = {"value": ".1f"}
    table.selection_mode = SelectionMode.MULTIPLE
    table.selected_ids = [2, 0]
    table.sort_column, table.sort_descending = "value", True
    reads = len(source.read)

    # in their order, as shown, a tab in a cell a space
    assert table.selection_text() == "c\t3.0\tprobe\t\na b\t1.2\tgauge\t"
    assert len(source.read) == reads + 1  # one read, outside the table's cache
    table.selected_ids = [1]
    assert table.selection_text() == "multi line\t2.0\tprobe\t"


def test_an_export_gives_the_rows_shown_as_csv_their_values_in_full(
    table: DataTableView, source: CountingSource, tmp_path: Path
) -> None:
    source.records = [
        Sample('a, "b"', 1.25, Kind.GAUGE, None),
        Sample("multi\nline", 2.0, note=0.1),
        Sample("hidden", 3.0),
        *_samples(DATA_TABLE_WINDOW + 1),
    ]
    table.column_formats = {"value": ".1f"}
    table.filters = {"name": "!hidden"}
    table.sort_column = "value"
    reads = len(source.read)
    chunks = table.csv_chunks()
    lines = next(chunks).splitlines() + next(chunks).splitlines()

    # a new order once the export started: the export keeps its own
    table.sort_descending = True
    lines += "".join(chunks).splitlines()

    assert lines[:8] == [
        "Name,Value,Kind,Note",
        "s0000,0.0,gauge,",
        "s0001,0.25,probe,",
        "s0002,0.5,probe,",
        "s0003,0.75,gauge,",
        "s0004,1.0,probe,",
        '"a, ""b""",1.25,gauge,',  # quoted; not as `column_formats` shows it
        "s0005,1.25,probe,",
    ]
    assert len(lines) == 1 + DATA_TABLE_WINDOW + 3 + 1  # the line break quoted too
    assert len(set(lines)) == len(lines)  # each row once
    assert lines[-1] == f"s{DATA_TABLE_WINDOW:04d},{DATA_TABLE_WINDOW / 4},probe,"
    assert '"multi\nline",2.0,probe,0.1' in "\n".join(lines)
    assert all(len(ids) <= DATA_TABLE_WINDOW for ids in source.read[reads:])

    table.export_csv(tmp_path / "rows.csv")  # not in an app: written at once
    assert (tmp_path / "rows.csv").read_text(encoding="utf-8").startswith("Name,Value,")


def test_a_double_click_activates_the_row_at_its_position(table: DataTableView) -> None:
    activated: list[Any] = []
    table.row_activated.connect(activated.append)
    table.sort_column, table.sort_descending = "value", True

    table.activate_at(2)
    table.activate_at(5_000)  # no row there

    assert activated == [997]


def test_a_new_source_s_rows_replace_the_old_one_s(
    table: DataTableView, source: CountingSource
) -> None:
    table.rows(0, 10)
    other = CountingSource(_samples(3))

    table.source = other
    source.records = _samples(7)  # the old source: no longer read

    assert table.row_count == 3
    assert source.orders == 1
    assert other.read == []
    assert len(table.rows(0, 10)) == 3


def test_a_million_rows_keep_their_ids_alone_and_read_a_window() -> None:
    source = MillionSource()
    table = DataTableView()
    tracemalloc.start()
    try:
        table.source = source
        kept = tracemalloc.get_traced_memory()[0]
    finally:
        tracemalloc.stop()

    # 8 bytes an id, in an array: a list of a million integers takes about 36 MB
    assert kept < 9_000_000
    assert table.rows(500_010, 500_012) == [
        (500_010, ["1000020", "250005.0"]),
        (500_011, ["1000022", "250005.5"]),
    ]
    assert len(source.read) == DATA_TABLE_WINDOW


@define_view
class SamplesMainView(MainView):
    samples: DataTableView = child(DataTableView, selection_mode=SelectionMode.MULTIPLE)


def test_a_study_saves_the_settings_and_the_selection_never_the_rows(tmp_path: Path) -> None:
    main_view = SamplesMainView()
    main_view.samples.source = CountingSource(_samples(20))
    main_view.samples.sort_column, main_view.samples.sort_descending = "value", True
    main_view.samples.filters = {"kind": "=gauge"}
    main_view.samples.selected_ids = [18, 3]
    path = tmp_path / "samples.json"

    main_view.save_state(path)

    assert "s0018" not in path.read_text()
    reopened = SamplesMainView()
    reopened.samples.source = CountingSource(_samples(20))
    reopened.load_state(path)
    assert reopened.samples.ids(0, 3) == [18, 15, 12]
    assert reopened.samples.selected_ids == [18, 3]
