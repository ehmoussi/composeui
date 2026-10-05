"""A study: the views' state and the model's data, started, saved and opened together.

Without data of its own in the model (`Model.data_name` is None), a study is the views'
state as JSON (`MainView.save_state`). With it, a study is a zip archive of the views'
state (`views.json`) and the model's file, so the two are never saved or opened apart.
"""

from __future__ import annotations

import json
import tempfile
import zipfile
import zlib
from pathlib import Path
from typing import TYPE_CHECKING

from composeui.core.model import InvalidStateError

if TYPE_CHECKING:
    from composeui.core.model import Model
    from composeui.core.view import MainView

#: the views' state inside a study's archive
VIEWS_NAME = "views.json"
#: what reading a damaged archive can raise
_BAD_ARCHIVE_ERRORS = (zipfile.BadZipFile, zlib.error, EOFError)


def has_data(model: Model | None) -> bool:
    """Whether a study with this model is an archive, rather than the views' JSON."""
    return model is not None and model.data_name is not None


def new_study(main_view: MainView, model: Model | None) -> None:
    """Start a new study: the model's data and the views back to their start."""
    if model is not None:
        model.new()
    main_view.reset_state()


def save_study(main_view: MainView, model: Model | None, path: Path) -> None:
    """Save the views' state and the model's data into the file `path`."""
    if model is None or model.data_name is None:
        main_view.save_state(path)
        return
    # written beside `path` and renamed over it, so a failed save leaves the old study whole
    partial = path.with_name(f".{path.name}.partial")
    try:
        with tempfile.TemporaryDirectory(prefix="composeui-") as directory:
            data_path = Path(directory, model.data_name)
            model.save_data(data_path)
            with zipfile.ZipFile(partial, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr(VIEWS_NAME, json.dumps(main_view.state_data()))
                archive.write(data_path, model.data_name)
        partial.replace(path)
    finally:
        partial.unlink(missing_ok=True)
    main_view.state_filepath = path


def open_study(
    main_view: MainView, model: Model | None, path: Path, *, max_size: int | None = None
) -> None:
    """Open the study saved in the file `path`, into the views and the model.

    Everything is checked before anything changes: raises `InvalidStateError`, leaving the
    views and the model unchanged, for a file that doesn't fit them. `max_size` caps the
    archive's unpacked size, in bytes, against a small file unpacking into a huge one.
    """
    if model is None or model.data_name is None:
        main_view.load_state(path)
        return
    invalid = f"it isn't a valid {main_view.extension} file"
    try:
        with zipfile.ZipFile(path) as archive:
            members = archive.infolist()
            if {member.filename for member in members} != {VIEWS_NAME, model.data_name}:
                raise InvalidStateError(invalid)
            if max_size is not None and sum(member.file_size for member in members) > max_size:
                msg = "the file is too large"
                raise InvalidStateError(msg)
            try:
                data = json.loads(archive.read(VIEWS_NAME))
            except ValueError as error:  # also covers bytes that aren't text
                raise InvalidStateError(invalid) from error
            main_view.check_state_data(data)
            with tempfile.TemporaryDirectory(prefix="composeui-") as directory:
                # the member is named after the model's file, never a path of the archive's
                archive.extract(model.data_name, directory)
                model.open_data(Path(directory, model.data_name))
    except _BAD_ARCHIVE_ERRORS as error:
        raise InvalidStateError(invalid) from error
    # checked above, so it can't fail now that the model has changed
    main_view.load_state_data(data)
    main_view.state_filepath = path
