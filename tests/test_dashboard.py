"""The dashboard helpers: filters of a frame's columns, counts, tables, files read and given."""

from __future__ import annotations

import bz2
import csv
import datetime
import decimal
import gzip
import io
import lzma
import math
import zipfile
from typing import TYPE_CHECKING, Any, BinaryIO, Callable, Literal, Optional, cast
from unittest.mock import Mock

import attrs
import pytest
from hypothesis import given
from hypothesis import strategies as st

pytest.importorskip("polars")
pytest.importorskip("pandas")
pytest.importorskip("pyarrow")
import pandas as pd
import polars as pl

from composeui.core import dashboard
from composeui.core.application import Application
from composeui.core.dashboard import (
    column_filter,
    counts_of,
    fill_filters,
    filtered,
    frame_content,
    read_frame,
    show_frame,
)
from composeui.core.reactivity import reactive, reactive_inputs
from composeui.core.view import (
    MAX_SLIDER_STEPS,
    CheckListView,
    ComboBoxView,
    DateRangeInputView,
    DownloadSink,
    FloatRangeSliderView,
    LabelRowMultiComboBoxView,
    MainView,
    RangeSliderView,
    SourceTableView,
    VerticalView,
    View,
    child,
    define_view,
)

if TYPE_CHECKING:
    from pathlib import Path

    from composeui.core.jobs import Job


@attrs.frozen
class Trip:
    base: Optional[str]
    riders: Optional[int]
    distance: Optional[float]
    at: Optional[datetime.datetime]


SCHEMA = {"base": pl.String, "riders": pl.Int64, "distance": pl.Float64, "at": pl.Datetime}


def _columns(trips: list[Trip]) -> dict[str, list[Any]]:
    return {name: [getattr(trip, name) for trip in trips] for name in SCHEMA}


def _polars(trips: list[Trip]) -> pl.DataFrame:
    return pl.DataFrame(_columns(trips), schema=SCHEMA)


#: each library's frame of some trips, by the library's name
FRAMES: dict[str, Callable[[list[Trip]], Any]] = {
    "polars": _polars,
    "pandas": lambda trips: pd.DataFrame(_columns(trips)).astype(
        {"base": "string", "riders": "Int64", "distance": "float64", "at": "datetime64[ns]"}
    ),
    "pyarrow": lambda trips: _polars(trips).to_arrow(),
    "lazy": lambda trips: _polars(trips).lazy(),
}


def _length(frame: Any) -> int:
    return len(frame.collect() if isinstance(frame, pl.LazyFrame) else frame)


@define_view
class Panel(VerticalView):
    distances: FloatRangeSliderView = column_filter(FloatRangeSliderView, "distance")
    days: DateRangeInputView = column_filter(DateRangeInputView, "at")


@define_view
class TripFilters(View):
    # in a form row, and in a child view: the filters are found where they are
    bases: LabelRowMultiComboBoxView[str] = column_filter(
        LabelRowMultiComboBoxView[str], "base", label="Bases"
    )
    riders: RangeSliderView = column_filter(RangeSliderView, "riders")
    panel: Panel = child(Panel)


_DAY = datetime.datetime.fromisoformat("2024-03-01T00:00")
_BASES = st.sampled_from(["B1", "B2", "B3", None])
_RIDERS = st.sampled_from([0, 1, 2, 4, None])
_DISTANCES = st.sampled_from([0.0, 0.5, 1.25, 3.0, None, math.nan])
# times late in their day: a day's end includes them
_TIMES = st.sampled_from(
    [_DAY, _DAY + datetime.timedelta(hours=23, minutes=59), _DAY + datetime.timedelta(days=2), None]
)
_TRIPS = st.lists(st.builds(Trip, _BASES, _RIDERS, _DISTANCES, _TIMES), min_size=1, max_size=8)


def _all(choice: LabelRowMultiComboBoxView[str]) -> list[str]:
    """Get every value of a choice: their keys, the texts themselves."""
    return [key for key, _label in choice.options]


def _keeps(trip: Trip, filters: TripFilters) -> bool:
    """Tell whether the filters keep `trip`, as their docs say, in plain Python."""
    bases, riders = filters.bases, filters.riders
    distances, days = filters.panel.distances, filters.panel.days
    if bases.selected != _all(bases) and trip.base not in bases.selected:
        return False
    for view, cell in ((riders, trip.riders), (distances, trip.distance)):
        low, high = view.value
        last = view.step_rules.value_at(
            view.step_rules.last_position(view.minimum, view.maximum, view.step),
            view.minimum,
            view.step,
        )
        is_bounded = low > view.minimum or high < last
        if is_bounded and (cell is None or math.isnan(cell) or not low <= cell <= high):
            return False
    start, end = days.value
    if start is not None or end is not None:
        if trip.at is None:
            return False
        if (start is not None and trip.at.date() < start) or (
            end is not None and trip.at.date() > end
        ):
            return False
    return True


@given(trips=_TRIPS, data=st.data())
def test_the_filters_keep_the_rows_that_each_accepts_on_every_library(
    trips: list[Trip], data: st.DataObject
) -> None:
    for name, build in FRAMES.items():
        frame = build(trips)
        filters = TripFilters()
        fill_filters(filters, frame)
        if data.draw(st.booleans(), label="touched"):
            _choose(filters, data)

        rows = filtered(frame, filters)

        assert _length(rows) == sum(_keeps(trip, filters) for trip in trips), name


def _choose(filters: TripFilters, data: st.DataObject) -> None:
    bases = filters.bases
    if _all(bases):
        bases.selected = data.draw(st.lists(st.sampled_from(_all(bases))))
    for view in (filters.riders, filters.panel.distances):
        rules = view.step_rules
        last = rules.last_position(view.minimum, view.maximum, view.step)
        low, high = sorted(data.draw(st.lists(st.integers(0, last), min_size=2, max_size=2)))
        view.value = (
            rules.value_at(low, view.minimum, view.step),
            rules.value_at(high, view.minimum, view.step),
        )
    days = [
        None,
        _DAY.date(),
        (_DAY + datetime.timedelta(days=1)).date(),
        (_DAY + datetime.timedelta(days=2)).date(),
    ]
    start, end = data.draw(st.lists(st.sampled_from(days), min_size=2, max_size=2))
    if start is not None and end is not None and start > end:
        start, end = end, start
    filters.panel.days.value = (start, end)


def test_untouched_filters_keep_the_rows_without_a_value() -> None:
    trips = [Trip(None, None, None, None), Trip("B1", 1, 0.5, _DAY), Trip("B2", 3, math.nan, _DAY)]
    for build in FRAMES.values():
        frame = build(trips)
        filters = TripFilters()
        fill_filters(filters, frame)

        assert _length(filtered(frame, filters)) == 3


@pytest.mark.parametrize("library", list(FRAMES))
def test_a_range_with_one_end_moved_leaves_out_nan(library: str) -> None:
    """Polars sorts NaN above every number: a low end alone would keep it."""
    trips = [Trip("B1", 1, 0.0, _DAY), Trip("B1", 1, 3.0, _DAY), Trip("B1", 1, math.nan, _DAY)]
    frame = FRAMES[library](trips)
    filters = TripFilters()
    fill_filters(filters, frame)

    filters.panel.distances.value = (1.0, filters.panel.distances.maximum)

    assert _length(filtered(frame, filters)) == 1


def test_filled_again_the_filters_keep_the_user_s_choice() -> None:
    first = _polars([Trip("B1", 0, 0.0, _DAY), Trip("B2", 10, 2.0, _DAY), Trip("B3", 4, 1.0, _DAY)])
    filters = TripFilters()
    fill_filters(filters, first)
    filters.bases.selected = ["B1", "B3"]
    filters.riders.value = (2, 10)  # its high end at the limit
    filters.panel.days.value = (_DAY.date(), None)

    fill_filters(filters, first)
    assert filters.bases.selected == ["B1", "B3"]
    assert filters.riders.value == (2, 10)
    assert filters.panel.days.value == (_DAY.date(), None)

    # another file: the values that remain, an end at its limit moving to the new one
    later = _DAY + datetime.timedelta(days=5)
    fill_filters(filters, _polars([Trip("B3", 1, 0.0, later), Trip("B4", 20, 1.0, later)]))
    assert list(filters.bases.values) == ["B3", "B4"]
    assert filters.bases.selected == ["B3"]
    assert (filters.riders.minimum, filters.riders.maximum) == (1, 20)
    assert filters.riders.value == (2, 20)
    assert filters.panel.days.value == (None, None)  # its start before the new first day


def test_a_choice_of_all_its_values_follows_new_values() -> None:
    filters = TripFilters()
    fill_filters(filters, _polars([Trip("B1", 0, 0.0, _DAY)]))

    fill_filters(filters, _polars([Trip("B1", 0, 0.0, _DAY), Trip("B2", 0, 0.0, _DAY)]))

    assert filters.bases.selected == ["B1", "B2"]


@pytest.mark.parametrize(
    ("riders", "limits"),
    [
        ([None, None], (0, 0)),  # no value at all
        ([7, 7], (7, 7)),
        # a step of whole numbers far below the slider's limit of steps
        ([-(2**62), 2**62], (-(2**62), 2**62)),
    ],
    ids=["empty", "constant", "wide"],
)
def test_a_whole_number_range_takes_its_column_s_values(
    riders: list[Optional[int]], limits: tuple[int, int]
) -> None:
    filters = TripFilters()
    filters.riders.value = (3, 5)  # before: within the slider's limits

    fill_filters(filters, _polars([Trip("B1", count, 0.0, _DAY) for count in riders]))

    view = filters.riders
    low, high = limits
    assert view.minimum <= low <= high <= view.maximum
    assert view.step_rules.last_position(view.minimum, view.maximum, view.step) <= 1000
    assert view.step_rules.last_position(view.minimum, view.maximum, view.step) < MAX_SLIDER_STEPS


def test_a_decimal_range_leaves_out_nan_and_infinities_and_shows_round_ends() -> None:
    filters = TripFilters()
    distances = [0.013, math.nan, math.inf, -math.inf, 2.071]

    fill_filters(filters, _polars([Trip("B1", 0, d, _DAY) for d in distances]))

    view = filters.panel.distances
    # a step of 1, 2 or 5 times a power of 10, for about a hundred steps
    assert (view.minimum, view.maximum, view.step) == (0.0, 2.1, 0.05)
    assert view.value == (0.0, 2.1)


@define_view
class Days(View):
    days: DateRangeInputView = column_filter(DateRangeInputView, "at")


@pytest.mark.parametrize("time_zone", [None, "America/New_York"])
def test_a_day_s_end_takes_its_times_in_the_column_s_time_zone(time_zone: Optional[str]) -> None:
    at = [datetime.datetime.fromisoformat(t) for t in ("2024-03-01T23:30", "2024-03-02T00:30")]
    frame = pl.DataFrame({"at": at}).with_columns(pl.col("at").dt.replace_time_zone(time_zone))
    view = Days()
    fill_filters(view, frame)
    assert (view.days.minimum, view.days.maximum) == (at[0].date(), at[1].date())

    view.days.value = (None, at[0].date())

    assert filtered(frame, view).get_column("at").dt.hour().to_list() == [23]


def test_a_date_range_of_a_column_of_days_keeps_both_ends() -> None:
    days = [datetime.date(2024, 3, day) for day in (1, 2, 3, 4)]
    frame = pl.DataFrame({"at": days})
    view = Days()
    fill_filters(view, frame)

    view.days.value = (days[1], days[2])

    assert filtered(frame, view).get_column("at").to_list() == days[1:3]


@define_view
class ChoiceOfDecimals(View):
    choice: CheckListView[str] = column_filter(CheckListView[str], "distance")


@define_view
class WholeRangeOfDecimals(View):
    whole: RangeSliderView = column_filter(RangeSliderView, "distance")


@define_view
class DaysOfTexts(View):
    dates: DateRangeInputView = column_filter(DateRangeInputView, "base")


@define_view
class RangeOfTexts(View):
    numbers: FloatRangeSliderView = column_filter(FloatRangeSliderView, "base")


@pytest.mark.parametrize(
    "view_type", [ChoiceOfDecimals, WholeRangeOfDecimals, DaysOfTexts, RangeOfTexts]
)
def test_a_filter_refuses_a_column_of_another_kind(view_type: type[View]) -> None:
    with pytest.raises(TypeError, match=r"can't be|needs a FloatRangeSliderView"):
        fill_filters(view_type(), _polars([Trip("B1", 0, 0.5, _DAY)]))


@define_view
class OneChoice(View):
    choice: ComboBoxView[str] = column_filter(ComboBoxView[str], "base")


def test_a_view_that_can_t_filter_is_refused_as_a_filter() -> None:
    with pytest.raises(TypeError, match=r"OneChoice.choice can't filter a column"):
        filtered(_polars([]), OneChoice())


@define_view
class Prices(View):
    prices: FloatRangeSliderView = column_filter(FloatRangeSliderView, "price")


def test_a_decimal_range_takes_a_column_of_exact_decimals() -> None:
    prices = [decimal.Decimal("1.25"), decimal.Decimal("3.50")]
    frame = pl.DataFrame({"price": prices}, schema={"price": pl.Decimal(10, 2)})
    view = Prices()
    fill_filters(view, frame)
    assert (view.prices.minimum, view.prices.maximum, view.prices.step) == (1.25, 3.5, 0.05)

    view.prices.value = (2.0, 3.5)

    assert filtered(frame, view).get_column("price").to_list() == prices[1:]


@define_view
class OtherColumn(View):
    choice: CheckListView[str] = column_filter(CheckListView[str], "unknown")


def test_a_filter_of_a_column_that_the_frame_lacks_is_refused() -> None:
    with pytest.raises(ValueError, match="no column 'unknown'"):
        fill_filters(OtherColumn(), _polars([]))


def test_a_choice_of_too_many_values_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dashboard, "MAX_CHOICES", 2)
    frame = _polars([Trip(base, 0, 0.0, _DAY) for base in ("B1", "B2", "B3")])

    with pytest.raises(ValueError, match="more than 2 values"):
        fill_filters(TripFilters(), frame)


@define_view
class Kinds(View):
    riders: CheckListView[str] = column_filter(CheckListView[str], "riders")
    is_shared: CheckListView[str] = column_filter(CheckListView[str], "is_shared")
    kind: CheckListView[str] = column_filter(CheckListView[str], "kind")


def test_a_choice_filters_whole_numbers_booleans_and_categories() -> None:
    frame = pl.DataFrame(
        {"riders": [1, 2, 2], "is_shared": [True, False, True], "kind": ["x", "y", "x"]},
        schema={"riders": pl.Int64, "is_shared": pl.Boolean, "kind": pl.Categorical},
    )
    view = Kinds()
    fill_filters(view, frame)
    assert list(view.riders.values) == ["1", "2"]
    assert list(view.is_shared.values) == ["False", "True"]

    view.riders.selected = ["2"]
    view.is_shared.selected = ["True"]
    view.kind.selected = ["x"]

    assert filtered(frame, view).rows() == [(2, True, "x")]


def test_the_counts_keep_the_categories_order_and_their_zeros() -> None:
    trips = [Trip("B2", 1, 0.0, _DAY), Trip(None, 2, 0.0, _DAY), Trip("B2", 3, 0.0, _DAY)]
    for build in FRAMES.values():
        assert counts_of(build(trips), "base", ["B3", "B2", "B1"]) == [0, 2, 0]


@define_view
class Shown(View):
    table: SourceTableView = child(SourceTableView)


def test_a_frame_shows_in_a_table_whose_filter_bar_offers_every_column() -> None:
    view = Shown()
    show_frame(view.table, _polars([Trip("B1", 1, 0.0, _DAY), Trip("B2", 2, 0.0, _DAY)]))
    assert (view.table.row_count, view.table.filterable_columns) == (2, list(SCHEMA))

    view.table.filterable_columns = ["base"]
    show_frame(view.table, _polars([Trip("B3", 9, 0.0, _DAY)]), filterable=False)

    assert (view.table.row_count, view.table.filterable_columns) == (1, ["base"])


_PAGE_TRIPS = _polars([Trip("B1", 1, 0.0, _DAY), Trip("B2", 2, 0.0, _DAY)])


def _read_trips(_job: Job[pl.DataFrame, int]) -> pl.DataFrame:
    return _PAGE_TRIPS


@define_view
class TripsPage(MainView):
    filters: TripFilters = child(TripFilters)
    table: SourceTableView = child(SourceTableView)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.loader = self.jobs.task(_read_trips)
        self.loader.start()

    @reactive
    def fill(self) -> None:
        if self.loader.result is not None:
            fill_filters(self, self.loader.result)

    @reactive
    def show_trips(self) -> None:
        if self.loader.result is not None:
            # the main view itself: its filters wherever they are, and nothing else read
            show_frame(self.table, filtered(self.loader.result, self))


def test_a_reactive_method_filters_with_the_main_view_and_shows_the_rows_in_its_table() -> None:
    page = Application(build_main_view=TripsPage).main_view
    page.jobs.wait()
    assert page.table.row_count == 2

    page.filters.bases.selected = ["B2"]

    assert page.table.row_count == 1
    # the filters' choices, wherever they are, and nothing else of the page: not the table
    # that the method fills, nor where the filters are
    inputs = reactive_inputs(page)["show_trips"]
    assert "filters.bases.selected" in inputs
    filters = ("bases", "riders", "panel.days", "panel.distances")
    assert all(
        name == "loader" or name.startswith(tuple(f"filters.{f}." for f in filters))
        for name in inputs
    )


@pytest.mark.parametrize("is_parquet", [False, True], ids=["csv", "parquet"])
@pytest.mark.parametrize("library", list(FRAMES))
def test_a_frame_s_file_holds_its_rows(library: str, *, is_parquet: bool) -> None:
    trips = [Trip("B1", 2, 0.5, _DAY), Trip("B2", None, 1.5, None)]
    pieces: list[bytes] = []
    # not seekable, as the web's
    sink = cast("BinaryIO", DownloadSink(pieces.append))

    frame_content(FRAMES[library](trips), is_parquet=is_parquet).write(sink)
    sink.close()

    data = io.BytesIO(b"".join(pieces))
    read = pl.read_parquet(data) if is_parquet else pl.read_csv(data)
    assert read.select("base", "riders").rows() == [("B1", 2), ("B2", None)]


@pytest.mark.parametrize("separator", [",", ";", "\t", "|"])
def test_a_csv_file_reads_whatever_its_separator(tmp_path: Path, separator: str) -> None:
    path = tmp_path / "trips.csv"
    lines = [["base", "count", "note"], ["B02512", "1", "a, b"], ["B02764", "2", "c"]]
    with path.open("w", encoding="utf-8", newline="") as file:
        csv.writer(file, delimiter=separator).writerows(lines)

    frame = read_frame(path, backend="polars")

    assert frame.columns == ["base", "count", "note"]
    assert len(frame) == 2


@pytest.mark.parametrize(
    ("text", "columns"),
    [('"a,b,c,d";count\n"1,2,3,4";5\n', ["a,b,c,d", "count"]), ("name\nAda\n", ["name"])],
    ids=["quoted separators", "one column"],
)
def test_a_csv_file_s_separators_inside_quotes_don_t_count(
    tmp_path: Path, text: str, columns: list[str]
) -> None:
    path = tmp_path / "trips.csv"
    path.write_text(text, encoding="utf-8")

    assert read_frame(path, backend="pandas").columns == columns


@pytest.mark.parametrize(
    ("text", "error"),
    [
        # `csv.Sniffer` took 18 s on this, with every other thread stopped; pandas 4 s to read
        # its 16,385 columns
        (',"' * 32768, "longer than 64 KiB"),
        ("a,b,c,d\n1,2,3,4\n", "more than 3 columns"),
    ],
    ids=["crafted line", "many columns"],
)
def test_a_csv_file_of_too_many_columns_is_refused_before_it_is_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, text: str, error: str
) -> None:
    path = tmp_path / "wide.csv"
    path.write_text(text, encoding="utf-8")
    read = Mock(side_effect=AssertionError("read"))
    monkeypatch.setattr(dashboard.nw, "read_csv", read)

    with pytest.raises(ValueError, match=error):
        read_frame(path, backend="pandas", max_columns=3)
    assert not read.called


def _zip(data: bytes) -> bytes:
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as file:
        file.writestr("small.csv", data)
    return archive.getvalue()


_SMALL = b"a,b\n1,2\n"


@pytest.mark.parametrize("backend", ["polars", "pandas", "pyarrow"])
@pytest.mark.parametrize(
    ("name", "content"),
    [
        ("small.csv.gz", gzip.compress(_SMALL)),
        ("small.csv.zst", b"\x28\xb5\x2f\xfd rest"),
        ("small.csv", b"\x78\x9c rest"),
        ("small.csv.bz2", bz2.compress(_SMALL)),
        ("small.csv.xz", lzma.compress(_SMALL)),
        ("small.csv.zip", _zip(_SMALL)),
    ],
    ids=["gzip", "zstd", "zlib", "bzip2", "xz", "zip"],
)
def test_a_compressed_csv_file_is_refused_before_it_is_unpacked(
    tmp_path: Path, backend: Literal["polars", "pandas", "pyarrow"], name: str, content: bytes
) -> None:
    """Pandas and PyArrow unpack a file by its name's extension."""
    path = tmp_path / name
    path.write_bytes(content)

    with pytest.raises(ValueError, match="a compressed file isn't accepted"):
        read_frame(path, backend=backend)


def test_a_parquet_file_reads_with_the_library_asked(tmp_path: Path) -> None:
    path = tmp_path / "trips.PARQUET"
    _polars([Trip("B1", 2, 0.5, _DAY)]).write_parquet(path)

    frame = read_frame(path, backend="pyarrow")

    assert frame.implementation.is_pyarrow()
    assert frame.rows() == [("B1", 2, 0.5, _DAY)]


@pytest.mark.parametrize(
    ("content", "error"),
    [
        (b"not parquet", "not a Parquet file"),
        (b"PAR1" + b"x" * 8 + (100).to_bytes(4, "little") + b"PAR1", "a damaged Parquet file"),
        (b"PAR1" + b"x" * 64 + (64).to_bytes(4, "little") + b"PAR1", "more than 32 bytes"),
    ],
    ids=["other file", "description past the start", "description too large"],
)
def test_a_parquet_file_with_a_damaged_or_large_description_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, content: bytes, error: str
) -> None:
    monkeypatch.setattr(dashboard, "MAX_PARQUET_METADATA_SIZE", 32)
    path = tmp_path / "trips.parquet"
    path.write_bytes(content)

    with pytest.raises(ValueError, match=error):
        read_frame(path, backend="polars")
