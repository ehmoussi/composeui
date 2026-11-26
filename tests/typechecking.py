"""Check an app's code with mypy, as an app's own type check would."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

#: the end of each line of a checked source that mypy must reject
REJECTED = "# rejected"


def check_rejected_lines(tmp_path: Path, source: str) -> None:
    """Check that mypy rejects the lines of `source` marked `REJECTED`, and only them."""
    mypy = pytest.importorskip("mypy.api")
    path = tmp_path / "app.py"
    path.write_text(source)
    stdout, stderr, _status = mypy.run(
        [
            "--config-file",
            "pyproject.toml",
            "--no-incremental",
            "--cache-dir",
            str(tmp_path / "mypy-cache"),
            str(path),
        ]
    )
    assert stderr == "", stderr
    expected = {
        number
        for number, line in enumerate(source.splitlines(), start=1)
        if line.endswith(REJECTED)
    }
    assert expected, "no line is marked as rejected"
    # by the file's name: a path on Windows starts with its drive, as C:
    reported = re.findall(rf"{re.escape(path.name)}:(\d+): error:", stdout)
    rejected = {int(number) for number in reported}
    assert rejected == expected, stdout
