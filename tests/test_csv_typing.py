"""Constructor contracts for CSV schemas, checked through mypy's public API."""

from __future__ import annotations

import re
import runpy
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path


_SCHEMA = """\
from __future__ import annotations

import datetime
import decimal
from typing import Optional

import attrs
from composeui.core.sqlitemodel import CSVSqliteTable, csv_field, define_csv_row


@define_csv_row
class Reading:
    name: str = csv_field(name="Name", converter=str.strip)
    count: int
    payload: bytes = attrs.field(converter=str.encode)
    total: decimal.Decimal = csv_field(name="Total", converter=decimal.Decimal)
    optional: Optional[int] = csv_field(name="Optional", default=None)
    note: str = csv_field(name="Note", factory=lambda: "default")
    renamed: int = csv_field(name="External", default=1, alias="external")
    hidden: int = csv_field(name="Hidden", default=7, init=False)
    label: str = csv_field(name="Label", default="label", kw_only=True)

    def description(self) -> str:
        return self.name


class Readings(CSVSqliteTable, row_type=Reading, name="reading"):
    pass


@attrs.define
class ExistingRow:
    name: str = csv_field("Name", converter=lambda value: value.strip())
    count: int


@define_csv_row
class Dated:
    day: datetime.date = csv_field(name="Day", date_format="%Y-%m-%d")


@define_csv_row
class Counted:
    count: int = csv_field(name="Count", converter=int)


good = Reading(" name ", 3, "hello", "1.5", external=2, label="reading")
text: str = good.name
payload: bytes = good.payload
assert (good.name, good.payload, good.optional, good.note, good.renamed, good.hidden) == (
    "name", b"hello", None, "default", 2, 7
)
assert good.description() == "name"
existing = ExistingRow(" name ", 3)
dated = Dated(datetime.date(2026, 10, 27))
counted = Counted("3")
assert counted.count == 3
"""

_INVALID = """\
missing = Reading("name")
wrong_count = Reading("name", "three", "hello", "1.5")
wrong_default = Reading("name", 3, "hello", "1.5", optional="wrong")
wrong_alias = Reading("name", 3, "hello", "1.5", renamed=2)
hidden = Reading("name", 3, "hello", "1.5", hidden=2)
wrong_converter_input = Reading("name", 3, b"hello", "1.5")
wrong_name_input = Reading(12, 3, "hello", "1.5")
wrong_output: str = good.payload
positional_label = Reading("name", 3, "hello", "1.5", None, "note", 1, "label")

@define_csv_row
class InvalidDate:
    day: float = csv_field(name="Day", date_format="%Y-%m-%d")

@define_csv_row
class MissingConverter:
    value: str = csv_field(name="Value", converter=str.no_such_method)

@define_csv_row
class InstanceConverter:
    value: str = csv_field(name="Value", converter=good.description)

@define_csv_row
class ExpressionConverter:
    value: str = csv_field(name="Value", converter=Reading("x", 1, "y", "1").description)
"""


def test_csv_schema_constructor_types_preserve_defaults_converters_and_reject_invalid_calls(
    tmp_path: Path,
) -> None:
    mypy = pytest.importorskip("mypy.api")
    source = tmp_path / "csv_schema.py"
    arguments = [
        "--config-file",
        "pyproject.toml",
        "--no-incremental",
        "--cache-dir",
        str(tmp_path / "mypy-cache"),
        str(source),
    ]
    source.write_text(_SCHEMA)
    stdout, stderr, status = mypy.run(arguments)
    assert (status, stderr) == (0, ""), stdout
    runpy.run_path(str(source))

    source.write_text(_SCHEMA + _INVALID)
    stdout, stderr, status = mypy.run(arguments)
    assert (status, stderr) == (1, ""), stdout
    # Every deliberate error must be caught, with no errors on the valid schema.
    expected = {
        line
        for line, text in enumerate((_SCHEMA + _INVALID).splitlines(), start=1)
        if text.startswith(
            (
                "missing =",
                "wrong_",
                "hidden =",
                "positional_label =",
                "    day: float",
                "    value: str",
            )
        )
    }
    actual = {int(line) for line in re.findall(r":(\d+): error:", stdout)}
    assert actual == expected, stdout
