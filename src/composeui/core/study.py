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

#: the views' state inside a study's archive, with its versions (`MainView.file_data`)
VIEWS_NAME = "views.json"
#: what reading a damaged archive can raise
_BAD_ARCHIVE_ERRORS = (zipfile.BadZipFile, zlib.error, EOFError)
#: the compression methods a study's archive may use: what `save_study` writes. `zipfile`
#: unpacks a bzip2 or LZMA member whole, whatever size is read, so a few bytes of one can
#: unpack into gigabytes; another method it can't unpack at all (`NotImplementedError`)
_COMPRESSIONS = frozenset({zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED})
#: a member's flag of an encrypted one, which `zipfile` won't read without a password
_ENCRYPTED = 0x1


def has_data(model: Model | None) -> bool:
    """Tell whether a study with this model is an archive, rather than the views' JSON."""
    return model is not None and model.data_name is not None


def new_study(main_view: MainView, model: Model | None) -> None:
    """Start a new study: the model's data and the views back to their start."""
    main_view.reset_state()
    if model is not None:
        model.new()
        model.loaded()


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
                archive.writestr(VIEWS_NAME, json.dumps(main_view.file_data()))
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
        if model is not None:
            model.loaded()
        return
    invalid = f"it isn't a valid {main_view.extension} file"
    try:
        with zipfile.ZipFile(path) as archive:
            members = archive.infolist()
            if sorted(member.filename for member in members) != sorted(
                [VIEWS_NAME, model.data_name]
            ) or any(
                member.compress_type not in _COMPRESSIONS or member.flag_bits & _ENCRYPTED
                for member in members
            ):
                raise InvalidStateError(invalid)
            # The sizes the archive declares, which it may lie about: a member that unpacks
            # into more is cut there, and then fails its CRC (`BadZipFile`).
            if max_size is not None and sum(member.file_size for member in members) > max_size:
                msg = "the file is too large"
                raise InvalidStateError(msg)
            views = archive.getinfo(VIEWS_NAME)
            try:
                # not `archive.read`: it unpacks the whole member before cutting it
                with archive.open(views) as member:
                    data = json.loads(member.read(views.file_size))
            except ValueError as error:  # also covers bytes that aren't text
                raise InvalidStateError(invalid) from error
            data = main_view.state_data_from_file(data)
            main_view.check_state_data(data)
            # before the model's data is replaced: a job writing to it would write into the
            # study opened (see `Jobs`), so it stops once its open fails too
            main_view.jobs.drop()
            with tempfile.TemporaryDirectory(prefix="composeui-") as directory:
                # the member is named after the model's file, never a path of the archive's
                archive.extract(model.data_name, directory)
                model.open_data(Path(directory, model.data_name))
    except _BAD_ARCHIVE_ERRORS as error:
        raise InvalidStateError(invalid) from error
    # checked above, so it can't fail now that the model has changed
    main_view.load_state_data(data)
    main_view.state_filepath = path
    model.loaded()
