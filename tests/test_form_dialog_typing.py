"""Constructor and mutable-field contracts for typed form dialogs."""

from __future__ import annotations

import re
import runpy
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path


_SCHEMA = """\
from __future__ import annotations

import attrs
from composeui.core.view import (
    FormDialogView, FormView, LabelRowInputView, TypedFormDialogView, child, define_view,
)

@define_view
class PipeForm(FormView):
    name: LabelRowInputView = child(LabelRowInputView)

@define_view
class EditPipe(TypedFormDialogView[PipeForm]):
    form: PipeForm = attrs.Factory(PipeForm)

@define_view
class RequiredPipe(TypedFormDialogView[PipeForm]):
    pass

default = FormDialogView()
given = TypedFormDialogView(form=PipeForm())
specialized = TypedFormDialogView[PipeForm](form=PipeForm())
derived = EditPipe()
required = RequiredPipe(form=PipeForm())
given.form.name.text = "Given"
specialized.form.name.text = "Specialized"
derived.form.name.text = "Derived"
required.form.name.text = "Required"
"""

_INVALID = """\
missing_specialized = TypedFormDialogView[PipeForm]()
missing_subclass = RequiredPipe()
wrong_form = TypedFormDialogView[PipeForm](form=FormView())
specialized.form = FormView()
derived.form = FormView()
concrete: TypedFormDialogView[FormView] = specialized
"""


def test_typed_form_dialogs_require_their_form_and_prevent_incompatible_writes(
    tmp_path: Path,
) -> None:
    mypy = pytest.importorskip("mypy.api")
    source = tmp_path / "form_dialog.py"
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
    first_invalid_line = len(_SCHEMA.splitlines()) + 1
    expected = set(range(first_invalid_line, first_invalid_line + len(_INVALID.splitlines())))
    actual = {int(line) for line in re.findall(r":(\d+): error:", stdout)}
    assert actual == expected, stdout
