"""File reader."""

from composeui import form
from composeui.form.abstractformitems import AbstractFormItems
from composeui.form.formview import (
    GroupBoxApplyFormView,
    LabelSelectFileView,
    LabelSpinBoxView,
    LabelTextEditView,
    SelectFileView,
)

import aiofiles

import asyncio
import time
import typing
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Tuple

if typing.TYPE_CHECKING:
    from examples.asyncview.app import Model


class FileReaderItems(AbstractFormItems["Model", "FileReaderView"]):
    def __init__(self, model: "Model", view: "FileReaderView") -> None:
        super().__init__(model, view)

    def get_label(self, field: str, parent_fields: Tuple[str, ...] = ()) -> str:
        if field == "llm":
            return "LLM"
        return super().get_label(field, parent_fields)

    def get_value(self, field: str, parent_fields: Tuple[str, ...] = ()) -> Any:
        if field == "filepath":
            return self._model.root.filepath
        elif field == "delay":
            return self._model.root.delay
        elif field == "content":
            return self._model.root.content
        elif field == "output_filepath":
            return self._model.root.output_filepath
        return super().get_value(field, parent_fields)

    def set_value(self, field: str, value: Any, parent_fields: Tuple[str, ...] = ()) -> bool:
        if field == "filepath":
            self._model.root.filepath = str(value)
        elif field == "delay":
            delay = self.to_int_value(value, default=8, min_value=0, max_value=99)
            if delay is not None:
                self._model.root.delay = delay
                return True
            return False
        elif field == "content":
            self._model.root.content = str(value)
        elif field == "output_filepath":
            self._model.root.output_filepath = str(value)
        return super().set_value(field, value, parent_fields)


@dataclass(eq=False)
class FileReaderView(GroupBoxApplyFormView[FileReaderItems]):
    filepath: LabelSelectFileView[FileReaderItems] = field(
        init=False, repr=False, default_factory=LabelSelectFileView
    )
    delay: LabelSpinBoxView[FileReaderItems] = field(
        init=False, repr=False, default_factory=LabelSpinBoxView
    )
    content: LabelTextEditView[FileReaderItems] = field(
        init=False, repr=False, default_factory=LabelTextEditView
    )
    output_filepath: LabelSelectFileView[FileReaderItems] = field(
        init=False, repr=False, default_factory=LabelSelectFileView
    )


def initialize_file_reader(*, view: FileReaderView, model: "Model") -> None:
    form.initialize_form_view_items(view, FileReaderItems(model, view))
    view.title = "File Reader"
    view.content.field_view.is_read_only = True
    view.output_filepath.field_view.mode = "save_file"


async def read_file(
    *, form_view: FileReaderView, view: SelectFileView[FileReaderItems]
) -> None:
    filepath = Path(view.text)
    if filepath.exists():
        async with aiofiles.open(filepath, encoding="utf-8") as f:
            async for line in f:
                delay = form_view.delay.field_view.value
                if delay is not None:
                    await asyncio.sleep(delay / 10.0)
                form_view.content.field_view.append_text(line)


async def write_file(*, view: FileReaderView) -> None:
    filepath = Path(view.output_filepath.field_view.text)
    delay = view.delay.field_view.value
    if filepath.exists():
        filepath.unlink()
    text = view.content.field_view.text
    for line in text.splitlines(keepends=True):
        async with aiofiles.open(filepath, "a", encoding="utf-8") as f:
            if delay is not None:
                await asyncio.sleep(delay / 10.0)
            await f.write(line)


def sync_read_file(
    *, form_view: FileReaderView, view: SelectFileView[FileReaderItems]
) -> None:
    filepath = Path(view.text)
    if filepath.exists():
        with open(filepath, encoding="utf-8") as f:
            for line in f:
                delay = form_view.delay.field_view.value
                if delay is not None:
                    time.sleep(delay / 10.0)
                form_view.content.field_view.append_text(line)


def sync_write_file(*, view: FileReaderView) -> None:
    filepath = Path(view.output_filepath.field_view.text)
    delay = view.delay.field_view.value
    if filepath.exists():
        filepath.unlink()
    for line in view.content.field_view.text.splitlines(keepends=True):
        with open(filepath, "a", encoding="utf-8") as f:
            if delay is not None:
                time.sleep(delay / 10.0)
            f.write(line)


def connect_file_reader(*, view: FileReaderView) -> None:
    # use sync_read_file/sync_write_file instead of read_file/write_file to see the
    # usefulness of the async here
    # view.filepath.field_view.clicked += [sync_read_file]
    # view.apply_clicked += [sync_write_file]
    view.filepath.field_view.clicked += [read_file]
    view.apply_clicked += [write_file]
