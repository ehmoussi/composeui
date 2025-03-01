from examples.asyncview.app import AsyncViewApp
from examples.asyncview.example import ExampleMainView
from examples.asyncview.filereader import FileReaderView

import pytest

import asyncio
from pathlib import Path


@pytest.fixture()
def file_reader_view(app: AsyncViewApp) -> FileReaderView:
    return app.main_view.file_reader


@pytest.fixture()
def main_view(app: AsyncViewApp) -> ExampleMainView:
    return app.main_view


@pytest.mark.asyncio(loop_scope="function")
async def test_read_write_file(
    file_reader_view: FileReaderView, main_view: ExampleMainView, tmpdir: Path
) -> None:
    # set up read test
    # - file to read
    filepath = Path("tests/test_asyncview/data/message.txt")
    main_view.file_view.open_file = lambda: str(filepath)  # type: ignore[method-assign]
    # - change the delay to 0 to avoid a too long test
    file_reader_view.delay.field_view.value = 0
    file_reader_view.delay.field_view.value_changed()
    # start reading the file
    file_reader_view.filepath.field_view.clicked()
    await asyncio.gather(*file_reader_view.filepath.field_view.clicked.tasks)
    # check
    assert file_reader_view.content.field_view.text == filepath.read_text(encoding="utf-8")
    # set up write test
    # - file to write
    output_filepath = Path(tmpdir, "test_message.txt")
    main_view.file_view.save_file = lambda: str(output_filepath)  # type: ignore[method-assign]
    file_reader_view.output_filepath.field_view.clicked()
    # start writing the file
    file_reader_view.apply_clicked()
    await asyncio.gather(*file_reader_view.apply_clicked.tasks)
    # check
    assert output_filepath.exists()
    assert output_filepath.read_text(encoding="utf-8") == filepath.read_text(encoding="utf-8")
