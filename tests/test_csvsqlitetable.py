"""CSV imports through attrs schemas and real SQLite transactions."""

from __future__ import annotations

import contextlib
import datetime
import decimal
import io
import subprocess
import sys
from typing import TYPE_CHECKING, Any, Optional

import attrs
import pytest

from composeui.core.model import RefusedError
from composeui.core.sqlitemodel import CSVSqliteTable, SqliteModel, csv_field, table

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


@attrs.define
class Reading:
    name: str = csv_field("Name", converter=str.strip)
    value: float = csv_field("Value", validator=attrs.validators.ge(0))
    day: datetime.date = csv_field("Day", date_format="%d/%m/%Y")
    moment: datetime.datetime = csv_field("Moment", date_format="%d/%m/%Y %H:%M%z")
    optional: Optional[datetime.date] = csv_field("Optional", date_format="%d/%m/%Y", default=None)
    note: str = attrs.field(factory=lambda: "default")
    computed: int = attrs.field(init=False, default=7)


class Readings(CSVSqliteTable, row_type=Reading, name='reading "values"'):
    pass


class InheritedReadings(Readings):
    pass


class ReadingsModel(SqliteModel):
    readings = table(InheritedReadings)


@pytest.fixture
def model() -> Iterator[ReadingsModel]:
    model = ReadingsModel()
    yield model
    model.close()


_HEADER = "Name;Value;Day;Moment;Optional\n"
_FIRST = '" First; reading ";1.5;25/10/2026;25/10/2026 17:00+0200;26/10/2026\n'
_SECOND = '"Two\nlines";2.5;26/10/2026;26/10/2026 18:00+0200\n'


def test_csv_import_converts_validates_and_commits_batches_together(model: ReadingsModel) -> None:
    changes: list[None] = []
    model.readings.changed.connect(lambda: changes.append(None))
    text = io.StringIO(_HEADER + _FIRST + _SECOND + "unread\n")
    counts = []
    for count in model.readings.fill(text, delimiter=";", batch_size=1, limit=2):
        counts.append(count)
        with model.readings.reading() as db:
            assert db.execute('SELECT COUNT(*) FROM "reading ""values"""').fetchone()[0] == 0
        assert changes == []
    assert counts == [1, 2]
    assert text.readline() == "unread\n"
    assert not text.closed
    with model.readings.reading() as db:
        assert [tuple(row) for row in db.execute('SELECT * FROM "reading ""values"""')] == [
            (
                "First; reading",
                1.5,
                "2026-10-25",
                "2026-10-25T17:00:00+02:00",
                "2026-10-26",
                "default",
                7,
            ),
            ("Two\nlines", 2.5, "2026-10-26", "2026-10-26T18:00:00+02:00", None, "default", 7),
        ]
    assert changes == [None]


@pytest.mark.parametrize(
    ("text", "message"),
    [
        (_HEADER + _FIRST.replace("1.5", "-1"), "must be >= 0"),
        (_HEADER + _FIRST.replace("1.5", "bad"), "could not convert"),
        (_HEADER + _FIRST.replace("25/10/2026", "invalid"), "does not match format"),
        ("Name\nMissing required values\n", "required"),
    ],
)
def test_invalid_csv_rows_refuse_the_whole_import(
    model: ReadingsModel, text: str, message: str
) -> None:
    changes: list[None] = []
    model.readings.changed.connect(lambda: changes.append(None))
    # A previously submitted batch must also roll back when the later row fails.
    lines = (
        io.StringIO(_HEADER + _FIRST + text.removeprefix(_HEADER))
        if text.startswith(_HEADER)
        else io.StringIO(text)
    )
    with pytest.raises(RefusedError, match=message):
        list(model.readings.fill(lines, delimiter=";", batch_size=1))
    with model.readings.reading() as db:
        assert db.execute('SELECT COUNT(*) FROM "reading ""values"""').fetchone()[0] == 0
    assert changes == []


def test_closing_csv_progress_rolls_back_and_leaves_the_input_open(model: ReadingsModel) -> None:
    text = io.StringIO(_HEADER + _FIRST + _SECOND)
    with contextlib.closing(model.readings.fill(text, delimiter=";", batch_size=1)) as batches:
        assert next(batches) == 1
    assert not text.closed
    with model.readings.reading() as db:
        assert db.execute('SELECT COUNT(*) FROM "reading ""values"""').fetchone()[0] == 0


@attrs.define
class ScalarRow:
    name: str = csv_field(
        "Name",
        metadata={"minimum_length": 2},
        validator=lambda _i, a, v: attrs.validators.min_len(a.metadata["minimum_length"])(_i, a, v),
    )
    count: int
    enabled: bool = attrs.field(converter=lambda text: text == "yes")
    amount: decimal.Decimal = attrs.field(converter=decimal.Decimal)
    payload: bytes = attrs.field(converter=str.encode)
    optional: Optional[int] = None


class Scalars(CSVSqliteTable, row_type=ScalarRow, name="scalar"):
    pass


def test_csv_options_and_attrs_metadata_defaults_and_scalar_types() -> None:
    model = SqliteModel()
    try:
        scalars = model.add_table(Scalars)
        assert list(
            scalars.fill(
                ["ok,3,yes,1.25,hello\n"],
                fieldnames=["Name", "count", "enabled", "amount", "payload"],
            )
        ) == [1]
        with scalars.reading() as db:
            assert tuple(db.execute("SELECT * FROM scalar").fetchone()) == (
                "ok",
                3,
                1,
                1.25,
                b"hello",
                None,
            )
        with pytest.raises(RefusedError, match="Length"):
            list(scalars.fill(["Name,count,enabled,amount,payload\n", "x,3,no,1,hello\n"]))
    finally:
        model.close()


@attrs.define
class ISODates:
    day: datetime.date
    moment: datetime.datetime


class ISODateTable(CSVSqliteTable, row_type=ISODates, name="iso_dates"):
    pass


def test_dates_without_a_format_use_iso_text_and_round_trip() -> None:
    model = SqliteModel()
    try:
        dates = model.add_table(ISODateTable)
        assert list(dates.fill(["day,moment\n", "2026-10-25,2026-10-25T17:00:00\n"])) == [1]
        assert dates.fetch(ISODates, "SELECT * FROM iso_dates") == [
            ISODates(
                datetime.date(2026, 10, 25), datetime.datetime.fromisoformat("2026-10-25T17:00:00")
            )
        ]
    finally:
        model.close()


@attrs.define
class Empty:
    pass


@attrs.define
class Unsupported:
    values: list[int]


@attrs.define
class WrongDateType:
    value: float = attrs.field(metadata={"csv_date_format": "%Y"})


@pytest.mark.parametrize(
    ("options", "message"),
    [
        ({"row_type": Reading}, "requires an attrs row_type and a table name"),
        ({"name": "reading"}, "requires an attrs row_type and a table name"),
        ({"row_type": Empty, "name": "empty"}, "at least one field"),
        ({"row_type": Unsupported, "name": "unsupported"}, "Unsupported CSV field type"),
        ({"row_type": WrongDateType, "name": "wrong_date"}, "requires a date or datetime"),
    ],
)
def test_invalid_csv_schema_is_rejected_before_creating_a_database(
    options: dict[str, Any], message: str
) -> None:
    with pytest.raises(TypeError, match=message):
        type("InvalidCSVTable", (CSVSqliteTable,), {}, **options)


def test_csv_date_format_and_custom_converter_are_mutually_exclusive() -> None:
    with pytest.raises(TypeError, match="either date_format or converter"):
        csv_field("Date", date_format="%Y", converter=str)


def test_csv_date_format_is_restricted_by_static_type_checking(tmp_path: Path) -> None:
    script = tmp_path / "csv_types.py"
    script.write_text(
        "from datetime import date, datetime\n"
        "from typing import Optional\n"
        "import attrs\n"
        "from composeui.core.sqlitemodel import csv_field\n"
        "@attrs.define\n"
        "class Row:\n"
        "    day: date = csv_field('Day', date_format='%Y-%m-%d')\n"
        "    moment: datetime = csv_field('Moment', date_format='%Y-%m-%d')\n"
        "    optional: Optional[date] = csv_field('Optional', date_format='%Y-%m-%d')\n"
        "    number: float = csv_field('Number')\n"
        "    invalid: float = csv_field('Invalid', date_format='%Y-%m-%d')\n",
        encoding="utf-8",
    )
    result = subprocess.run(  # noqa: S603 (the script contains only the declarations above)
        [
            sys.executable,
            "-m",
            "mypy",
            "--follow-imports=silent",
            "--cache-dir",
            str(tmp_path / "cache"),
            str(script),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert 'expression has type "datetime", variable has type "float"' in result.stdout
    assert "Found 1 error in 1 file" in result.stdout
