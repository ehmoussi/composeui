"""Tests of the Textual file uploads and file, folder and save paths."""

from __future__ import annotations

import pytest

pytest.importorskip("textual")
pytest.importorskip("textual_fspicker")

import contextlib
import os
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from textual.widget import AwaitMount
from textual.widgets import (
    Input,
)
from textual_fspicker import FileSave, SelectDirectory
from textual_fspicker.base_dialog import Dialog, FileSystemPickerScreen
from textual_fspicker.parts import DirectoryNavigation
from textual_fspicker.parts.directory_navigation import DirectoryEntry, DirectoryEntryStyling

from composeui.core.registry import RendererType
from composeui.core.view import (
    UploadedFile,
)
from composeui.textualcore._renderers.navigation import TextualMainRenderer
from composeui.textualcore.widgets.composefilepathinput import (
    ComposeFilePathInput,
    ReplaceFileScreen,
)
from composeui.textualcore.widgets.composefileupload import ComposeFileUpload
from tests.datafiles import DataFileMainView
from tests.studyfiles import StudyFileMainView

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from textual.pilot import Pilot
    from textual.screen import Screen


from tests.textualcore.support import (
    _app_of,
    _click_laid_out,
    _field_widget,
    _wait_for_screen,
    _wait_until,
)


async def _open_picker(pilot: Pilot[Any], field: ComposeFilePathInput) -> None:
    """Click the field's browse button, once it takes a click, and wait for its picker.

    A button pressed less than 0.2 s ago ignores a click: on a slow machine, the last one.
    """
    await _click_laid_out(pilot, field.browse_button)
    await _wait_for_screen(pilot, FileSystemPickerScreen, DirectoryNavigation)


@pytest.mark.asyncio
async def test_a_file_upload_gives_the_user_s_file_from_the_picker_without_a_copy(
    tmp_path: Path,
) -> None:
    path = tmp_path / "flows.csv"
    path.write_text("1,2", encoding="utf-8")
    view = DataFileMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    dataset = view.form.dataset
    uploads: list[UploadedFile] = []
    dataset.uploaded.connect(uploads.append)

    async with app.run_test(size=(80, 40)) as pilot:
        widget = _field_widget(dataset.renderer)
        assert isinstance(widget, ComposeFileUpload)
        await pilot.pause()
        assert str(widget.name_label.render()) == "No file chosen"

        # cancelled, then picked
        widget.button.press()
        await pilot.pause()
        assert [type(s).__name__ for s in app.screen_stack] == ["Screen", "FileOpen"]
        await pilot.press("escape")
        await pilot.pause()
        assert (len(app.screen_stack), uploads) == (1, [])

        widget.button.press()
        await pilot.pause()
        # the picker focuses its list as it mounts: on a slow runner, after a pause
        await AwaitMount(app.screen, [app.screen])
        file_input = app.screen.query_one(Input)
        file_input.focus()
        file_input.value = str(path)
        await pilot.pause()
        await pilot.press("enter")
        for _ in range(4):
            await pilot.pause()
        assert uploads == [UploadedFile("flows.csv", 3, "text/csv", path)]
        assert str(widget.name_label.render()) == "flows.csv"
        assert app.focused is widget.button
        dataset.empty_text = "Nothing yet"
        assert str(widget.name_label.render()) == "flows.csv"
        dataset.clear()
        assert str(widget.name_label.render()) == "Nothing yet"


def _row_text(navigation: DirectoryNavigation, name: str) -> str:
    """Get the row of the folder list naming `name`, as the terminal shows it."""
    rows = [navigation.render_line(y).text for y in range(navigation.size.height)]
    return next(row for row in rows if f" {name} " in row)


def _index_in(navigation: DirectoryNavigation, name: str) -> int:
    names = [
        cast("DirectoryEntry", navigation.get_option_at_index(index)).location.name
        for index in range(navigation.option_count)
    ]
    return names.index(name)


class _Picker:
    """The picker of a `FileUploadView` with `multiple`, open in a folder of shapefiles."""

    def __init__(
        self,
        pilot: Pilot[Any],
        widget: ComposeFileUpload,
        given: list[tuple[UploadedFile, ...]],
    ) -> None:
        self.pilot = pilot
        self.widget = widget
        self.navigation = pilot.app.screen.query_one(DirectoryNavigation)
        self.names = pilot.app.screen.query_one(Input)
        #: what `files_uploaded` gave
        self.given = given

    async def mark(self, name: str) -> None:
        self.navigation.highlighted = _index_in(self.navigation, name)
        await self.pilot.press("space")

    async def listed(self) -> None:
        await self.pilot.app.workers.wait_for_complete()  # the list reads its folder in a thread
        await self.pilot.pause()

    def is_marked(self, name: str) -> bool:
        return _row_text(self.navigation, name).lstrip().startswith("✓")


@contextlib.asynccontextmanager
async def _shapes_picker(folder: Path) -> AsyncGenerator[_Picker, None]:
    for name in ("roads.shp", "roads.dbf", "rivers.shp", ".old.shp"):
        (folder / name).write_bytes(b"1")
    (folder / "sub").mkdir()
    view = DataFileMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    given: list[tuple[UploadedFile, ...]] = []
    view.form.shapes.files_uploaded.connect(given.append)
    async with app.run_test(size=(100, 40)) as pilot:
        widget = _field_widget(view.form.shapes.renderer)
        assert isinstance(widget, ComposeFileUpload)
        widget.button.press()
        await pilot.pause()
        await AwaitMount(app.screen, [app.screen])
        picker = _Picker(pilot, widget, given)
        await picker.listed()
        yield picker


@pytest.mark.asyncio
async def test_the_picker_of_several_files_marks_them_in_one_folder_until_a_name_is_typed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)  # where the picker opens
    async with _shapes_picker(tmp_path) as picker:
        await picker.mark("roads.shp")
        assert picker.is_marked("roads.shp")
        # Ctrl+click marks too; a mark on a folder does nothing
        navigation = picker.navigation
        row = _index_in(navigation, "rivers.shp") - int(navigation.scroll_y) + 1
        await picker.pilot.click(DirectoryNavigation, offset=(10, row), control=True)
        await picker.mark("sub")
        assert picker.names.value == '"roads.shp" "rivers.shp"'
        await picker.mark("rivers.shp")  # unmarked
        assert not picker.is_marked("rivers.shp")

        # a name typed is the choice: the marks go
        picker.names.focus()
        await picker.pilot.press("x")
        assert not picker.is_marked("roads.shp")
        navigation.focus()

        # one folder per choice: another one drops the marks
        await picker.mark("roads.shp")
        navigation.highlighted = _index_in(navigation, "sub")
        await picker.pilot.press("enter")
        await picker.listed()
        assert picker.names.value == ""
        await picker.pilot.press("backspace")
        await picker.listed()
        assert not picker.is_marked("roads.shp")

        # a file picked alone with Enter drops the marks; Open then gives it alone
        await picker.mark("roads.dbf")
        navigation.highlighted = _index_in(navigation, "roads.shp")
        await picker.pilot.press("enter")
        await picker.pilot.pause()
        assert (picker.names.value, picker.is_marked("roads.dbf")) == ("roads.shp", False)
        await picker.pilot.click("#select")
        await picker.pilot.pause()
        assert picker.given == [(UploadedFile.of_path(tmp_path / "roads.shp"),)]
        assert str(picker.widget.name_label.render()) == "roads.shp"


@pytest.mark.asyncio
async def test_a_file_upload_with_multiple_gives_the_files_marked_in_the_picker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)  # where the picker opens
    async with _shapes_picker(tmp_path) as picker:
        # a hidden file hidden again drops its mark
        await picker.pilot.press("full_stop")
        await picker.mark(".old.shp")
        await picker.mark("roads.dbf")
        await picker.pilot.press("full_stop")
        assert picker.names.value == '"roads.dbf"'

        # a marked file gone by Open: the picker says so, and stays
        await picker.mark("rivers.shp")
        (tmp_path / "rivers.shp").unlink()
        await picker.pilot.click("#select")
        dialog = picker.pilot.app.screen.query_one(Dialog)
        assert (dialog.border_subtitle, picker.given) == ("The file must exist", [])
        # Space on the focused Open button marks nothing
        await picker.pilot.press("space")
        assert picker.names.value == '"roads.dbf" "rivers.shp"'
        picker.navigation.focus()
        await picker.mark("rivers.shp")  # unmarked, though gone
        await picker.mark("roads.shp")
        # clicked again: once it takes a click
        await _click_laid_out(picker.pilot, picker.pilot.app.screen.query_one("#select"))
        await picker.pilot.pause()

        expected = tuple(UploadedFile.of_path(tmp_path / n) for n in ("roads.dbf", "roads.shp"))
        assert picker.given == [expected]
        assert str(picker.widget.name_label.render()) == "2 files"
        assert picker.pilot.app.focused is picker.widget.button


@pytest.mark.asyncio
async def test_a_file_path_is_typed_or_picked_in_the_picker_and_reloaded(tmp_path: Path) -> None:
    (tmp_path / "flows.csv").write_text("1,2", encoding="utf-8")
    view = DataFileMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    measurements = view.form.measurements
    picked: list[Path] = []
    measurements.path_picked.connect(picked.append)
    texts: list[str] = []
    measurements.text_changed.connect(texts.append)
    measurements.text_edited.connect(lambda text: texts.append(f"typed {text}"))
    measurements.path_picked.connect(lambda path: texts.append(f"picked {path}"))
    reloads: list[None] = []
    measurements.reload_clicked.connect(lambda: reloads.append(None))

    async with app.run_test(size=(80, 30)) as pilot:
        field = _field_widget(measurements.renderer)
        assert isinstance(field, ComposeFilePathInput)
        await pilot.pause()
        field.input.focus()
        await pilot.press(*str(tmp_path / "x"))
        await pilot.pause()
        assert measurements.path == tmp_path / "x"

        await _open_picker(pilot, field)
        assert [type(s).__name__ for s in app.screen_stack] == ["Screen", "FileOpen"]
        # the picker settles first: its folder read in a thread, its filter's change focusing
        # the list, which would take Enter
        await app.workers.wait_for_complete()
        await pilot.pause()
        file_input = app.screen.query_one(Input)
        file_input.focus()
        file_input.value = str(tmp_path / "flows.csv")
        await _wait_until(pilot, lambda: file_input.has_focus)
        await pilot.press("enter")
        await _wait_until(pilot, lambda: len(app.screen_stack) == 1)
        assert (measurements.path, picked) == (tmp_path / "flows.csv", [tmp_path / "flows.csv"])
        assert field.input.value == str(tmp_path / "flows.csv")
        # the picked path changes the text, then is reported, but the user didn't type it
        typed, flows = str(tmp_path / "x"), str(tmp_path / "flows.csv")
        assert texts[-4:] == [typed, f"typed {typed}", flows, f"picked {flows}"]

        await pilot.click(field.reload_button)
        await pilot.pause()
        assert len(reloads) == 1


@pytest.mark.asyncio
async def test_a_file_path_s_picker_opens_here_on_a_path_typed_halfway_and_cancels() -> None:
    view = DataFileMainView()
    app = _app_of(view)
    picked: list[Path] = []
    view.form.measurements.path_picked.connect(picked.append)

    async with app.run_test(size=(100, 30)) as pilot:
        field = _field_widget(view.form.measurements.renderer)
        assert isinstance(field, ComposeFilePathInput)
        await pilot.pause()
        field.input.focus()
        await pilot.press(*"nowhere/da")
        await _open_picker(pilot, field)
        opened = [type(screen).__name__ for screen in app.screen_stack]
        app.screen.dismiss(None)  # as the picker's Cancel does
        # the focus comes back in a call of its own, which a slow runner makes later
        for _ in range(40):
            if field.input.has_focus:
                break
            await pilot.pause(0.05)

        assert opened == ["Screen", "FileOpen"]
        assert (picked, field.input.value) == ([], "nowhere/da")
        assert field.input.has_focus


@pytest.mark.asyncio
async def test_a_file_path_s_picker_opens_in_its_first_server_root_and_can_leave_it(
    tmp_path: Path,
) -> None:
    (tmp_path / "studies").mkdir()
    view = StudyFileMainView()
    view.study.server_roots = (tmp_path / "studies", tmp_path)
    app = _app_of(view)

    async with app.run_test(size=(100, 30)) as pilot:
        field = _field_widget(view.study.renderer)
        assert isinstance(field, ComposeFilePathInput)
        await pilot.pause()
        await _open_picker(pilot, field)
        location = app.screen.query_one(DirectoryNavigation).location
        app.screen.dismiss(tmp_path / "elsewhere.py")  # as the picker's Open does
        await pilot.pause()

    assert Path(location) == tmp_path / "studies"
    # the app's own machine: a file outside the roots is the field's path too
    assert view.study.path == tmp_path / "elsewhere.py"


@pytest.mark.asyncio
async def test_a_file_path_s_picker_opens_in_its_base_folder_and_shows_its_files_relative(
    tmp_path: Path,
) -> None:
    study = tmp_path / "study"
    (study / "inputs").mkdir(parents=True)
    view = StudyFileMainView()
    app = _app_of(view)
    picked: list[Path] = []
    view.study.path_picked.connect(picked.append)

    async with app.run_test(size=(100, 30)) as pilot:
        view.study.base_folder = study
        field = _field_widget(view.study.renderer)
        assert isinstance(field, ComposeFilePathInput)
        await pilot.pause()
        locations: list[Path] = []
        shown: list[str] = []
        for file in (study / "inputs" / "model.py", tmp_path / "elsewhere.py"):
            await _open_picker(pilot, field)
            locations.append(Path(app.screen.query_one(DirectoryNavigation).location))
            app.screen.dismiss(file)  # as the picker's Open does
            await pilot.pause()
            shown.append(field.input.value)

    # again: in the folder of the file picked, one outside the base folder shown whole
    assert locations == [study, study / "inputs"]
    assert shown == [str(Path("inputs", "model.py")), view.study.text]
    assert (view.study.text, picked) == (
        str(tmp_path / "elsewhere.py"),
        [study / "inputs" / "model.py", tmp_path / "elsewhere.py"],
    )


@pytest.mark.asyncio
async def test_a_folder_path_s_picker_selects_a_folder_from_its_folder_else_its_root(
    tmp_path: Path,
) -> None:
    (tmp_path / "studies").mkdir()
    view = StudyFileMainView()
    view.results.server_roots = (tmp_path / "studies",)
    app = _app_of(view)
    picked: list[Path] = []
    view.results.path_picked.connect(picked.append)

    async with app.run_test(size=(100, 30)) as pilot:
        field = _field_widget(view.results.renderer)
        assert isinstance(field, ComposeFilePathInput)
        await pilot.pause()
        locations: list[Path] = []
        for text in ("", str(tmp_path), "nowhere/halfway"):
            field.input.value = text
            await pilot.pause()
            await _open_picker(pilot, field)
            screen = app.screen
            assert isinstance(screen, SelectDirectory)
            locations.append(Path(screen.query_one(DirectoryNavigation).location))
            screen.dismiss(tmp_path / "results")  # as the picker's Select does
            await pilot.pause()

    # its root while empty, the folder typed, else the current directory
    # os.getcwd: `Path.cwd()` is a blocking call in the event loop (ASYNC240)
    here = Path(os.getcwd())  # noqa: PTH109
    assert locations == [tmp_path / "studies", tmp_path, here]
    assert picked == [tmp_path / "results"] * 3
    assert not field.reload_button.display  # a folder has nothing to reload


@pytest.mark.asyncio
async def test_a_picker_s_folder_list_reads_its_styles_on_the_app_s_thread() -> None:
    """textual-fspicker reads them from the thread loading a folder.

    Textual empties a widget's component styles, then fills them anew, as it applies its
    styles again: read in between from another thread, a style would be missing.
    """
    view = DataFileMainView()
    app = _app_of(view)
    read: list[object] = []

    def read_styles(navigation: DirectoryNavigation) -> None:
        try:
            read.append(navigation._styles)  # noqa: SLF001 (what its loading thread reads)
        except KeyError as error:
            read.append(error)

    async with app.run_test(size=(100, 30)) as pilot:
        field = _field_widget(view.form.measurements.renderer)
        assert isinstance(field, ComposeFilePathInput)
        await pilot.pause()
        await _open_picker(pilot, field)
        navigation = app.screen.query_one(DirectoryNavigation)
        # as Textual applies the list's styles again: none, until the app's thread is done
        styles = navigation._component_styles  # noqa: SLF001 (nothing else reaches them)
        kept = dict(styles)
        styles.clear()
        thread = threading.Thread(target=read_styles, args=(navigation,))
        thread.start()
        thread.join(timeout=0.2)  # the app's thread busy: the read waits for it
        assert thread.is_alive()
        styles.update(kept)
        while thread.is_alive():
            await pilot.pause(0.01)

    assert len(read) == 1
    assert isinstance(read[0], DirectoryEntryStyling)


@pytest.mark.asyncio
async def test_a_save_path_is_picked_in_a_save_picker_and_replaces_a_file_once_agreed(
    tmp_path: Path,
) -> None:
    (tmp_path / "report.pdf").write_text("")
    view = StudyFileMainView()
    report = view.report
    report.extensions = {"PDF": (".pdf",)}
    report.server_roots = (tmp_path,)
    app = _app_of(view)
    picked: list[Path] = []
    report.path_picked.connect(picked.append)

    async with app.run_test(size=(100, 30)) as pilot:
        field = _field_widget(report.renderer)
        assert isinstance(field, ComposeFilePathInput)
        await pilot.pause()

        async def save(path: Path) -> Screen[Any]:
            await _open_picker(pilot, field)
            assert isinstance(app.screen, FileSave)
            app.screen.dismiss(path)  # as the picker's Save does
            await pilot.pause()
            return app.screen

        await _open_picker(pilot, field)
        location = app.screen.query_one(DirectoryNavigation).location
        app.screen.dismiss(None)  # cancelled
        await pilot.pause()
        await save(tmp_path / "summary")  # a new file: at once, its extension added
        assert picked == [tmp_path / "summary.pdf"]
        assert not report.is_replace_agreed  # nothing to replace
        question = await save(tmp_path / "report")
        assert isinstance(question, ReplaceFileScreen)
        assert str(question.question.render()) == "report.pdf already exists. Replace it?"
        await pilot.press("escape")  # kept
        await pilot.pause()
        assert len(picked) == 1
        question = await save(tmp_path / "report")
        assert isinstance(question, ReplaceFileScreen)
        # pushed as the picker closed: maybe not laid out yet
        await _click_laid_out(pilot, question.replace_button)
        await pilot.pause()
        assert picked[-1] == tmp_path / "report.pdf"
        assert report.is_replace_agreed  # remembered: saving won't ask again
        report.confirms_overwrite = False
        await save(tmp_path / "report")  # no question, so nothing agreed
        assert not report.is_replace_agreed

    assert Path(location) == tmp_path
    assert picked == [tmp_path / "summary.pdf", tmp_path / "report.pdf", tmp_path / "report.pdf"]
    assert report.path == tmp_path / "report.pdf"
