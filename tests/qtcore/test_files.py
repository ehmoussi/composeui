"""Tests of the Qt file uploads and file, folder and save paths."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from qtpy.QtCore import QSize, Qt
from qtpy.QtWidgets import (
    QFileDialog,
    QMessageBox,
)

from composeui.core.registry import RendererType
from composeui.core.view import (
    UploadedFile,
)
from composeui.qtcore.widgets.qfilepathfield import QFilePathField
from composeui.qtcore.widgets.qfileupload import QFileUpload
from tests.datafiles import DataFileMainView
from tests.studyfiles import StudyFileMainView

if TYPE_CHECKING:
    import pytest
    from pytestqt.qtbot import QtBot


from tests.qtcore.support import _field_widget


def test_a_file_upload_with_multiple_gives_the_files_picked_together_in_qt_s_dialog(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    view = DataFileMainView()
    view.render(RendererType.QT)
    shapes = view.form.shapes
    widget = _field_widget(shapes)
    assert isinstance(widget, QFileUpload)
    qtbot.addWidget(widget)
    given: list[tuple[UploadedFile, ...]] = []
    shapes.files_uploaded.connect(given.append)
    paths = [tmp_path / "roads.shp", tmp_path / "roads.dbf"]
    for path in paths:
        path.write_bytes(b"1")
    filters: list[str] = []
    answer: list[str] = []

    def ask(*args: object) -> tuple[list[str], str]:
        filters.append(str(args[3]))
        return answer, ""

    def ask_one(*_args: object) -> tuple[str, str]:
        msg = "the dialog that picks one file"
        raise AssertionError(msg)

    monkeypatch.setattr(QFileDialog, "getOpenFileNames", staticmethod(ask))
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(ask_one))
    qtbot.mouseClick(widget.button, Qt.MouseButton.LeftButton)  # cancelled
    assert (filters, given) == (["Shapefile (*.shp *.shx *.dbf)"], [])

    answer = [str(path) for path in paths]
    qtbot.mouseClick(widget.button, Qt.MouseButton.LeftButton)
    assert given == [tuple(UploadedFile.of_path(path) for path in paths)]
    assert widget.name.text() == "2 files"
    answer = [str(paths[1])]
    qtbot.mouseClick(widget.button, Qt.MouseButton.LeftButton)
    assert (shapes.files, widget.name.text()) == ((UploadedFile.of_path(paths[1]),), "roads.dbf")
    shapes.files_text = "{count} shapefile parts"
    shapes.take_files(UploadedFile.of_path(path) for path in paths)
    assert widget.name.text() == "2 shapefile parts"


def test_a_file_upload_gives_the_user_s_file_from_qt_s_dialog_without_a_copy(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    view = DataFileMainView()
    view.render(RendererType.QT)
    dataset = view.form.dataset
    widget = _field_widget(dataset)
    assert isinstance(widget, QFileUpload)
    qtbot.addWidget(widget)
    uploads: list[UploadedFile] = []
    dataset.uploaded.connect(uploads.append)
    assert (widget.button.text(), widget.name.text()) == ("Choose a file", "No file chosen")
    filters: list[str] = []
    answer = ("", "")

    def ask(*args: object) -> tuple[str, str]:
        filters.append(str(args[3]))
        return answer

    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(ask))
    qtbot.mouseClick(widget.button, Qt.MouseButton.LeftButton)  # cancelled
    assert (filters, uploads) == (["CSV (*.csv)"], [])

    path = tmp_path / "flows.csv"
    path.write_text("1,2", encoding="utf-8")
    answer = (str(path), "CSV (*.csv)")
    qtbot.mouseClick(widget.button, Qt.MouseButton.LeftButton)
    assert uploads == [UploadedFile("flows.csv", 3, "text/csv", path)]
    assert dataset.file == uploads[0]
    assert widget.name.text() == "flows.csv"
    assert widget.name.textFormat() == Qt.TextFormat.PlainText  # a name may look like HTML
    dataset.empty_text = "Nothing yet"
    assert widget.name.text() == "flows.csv"

    # the user's own file stays
    dataset.empty_text = "No file chosen"
    dataset.clear()
    assert (widget.name.text(), path.exists()) == ("No file chosen", True)


def test_a_file_path_is_typed_or_picked_in_qt_s_dialog_and_reloaded(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    view = DataFileMainView()
    view.render(RendererType.QT)
    view.set_language("fr")
    measurements = view.form.measurements
    field = _field_widget(measurements)
    assert isinstance(field, QFilePathField)
    qtbot.addWidget(field)
    field.show()
    picked: list[Path] = []
    measurements.path_picked.connect(picked.append)
    reloads: list[None] = []
    measurements.reload_clicked.connect(lambda: reloads.append(None))
    asked: list[tuple[str, str, str]] = []
    answer = ("", "")

    def ask(*args: object) -> tuple[str, str]:
        asked.append((str(args[1]), str(args[2]), str(args[3])))
        return answer

    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(ask))
    assert field.browse_button.accessibleName() == "Choisir un fichier"
    assert field.reload_button.isVisible()
    # squares as tall as the field, whatever their text or icon
    side = field.line_edit.height()
    assert field.browse_button.size() == field.reload_button.size() == QSize(side, side)
    qtbot.keyClicks(field.line_edit, str(tmp_path / "old.csv"))
    assert measurements.path == tmp_path / "old.csv"

    qtbot.mouseClick(field.browse_button, Qt.MouseButton.LeftButton)  # cancelled
    assert asked == [("Choisir un fichier", str(tmp_path), "CSV (*.csv);;Text (*.txt *.text)")]
    assert (measurements.text, picked) == (str(tmp_path / "old.csv"), [])
    answer = (str(tmp_path / "new.txt"), "Text (*.txt *.text)")
    qtbot.mouseClick(field.browse_button, Qt.MouseButton.LeftButton)
    assert (measurements.path, field.line_edit.text()) == (tmp_path / "new.txt", answer[0])
    assert picked == [tmp_path / "new.txt"]

    qtbot.mouseClick(field.reload_button, Qt.MouseButton.LeftButton)
    assert len(reloads) == 1
    measurements.has_reload = False
    assert not field.reload_button.isVisible()


def test_a_file_path_s_dialog_opens_in_its_first_server_root_and_can_leave_it(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    view = StudyFileMainView()
    view.study.server_roots = (tmp_path / "studies", tmp_path)
    view.render(RendererType.QT)
    field = _field_widget(view.study)
    assert isinstance(field, QFilePathField)
    qtbot.addWidget(field)
    asked: list[str] = []

    def ask(*args: object) -> tuple[str, str]:
        asked.append(str(args[2]))
        return str(tmp_path / "elsewhere.py"), ""

    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(ask))

    qtbot.mouseClick(field.browse_button, Qt.MouseButton.LeftButton)

    assert asked == [str(tmp_path / "studies")]
    # the app's own machine: a file outside the roots is the field's path too
    assert view.study.path == tmp_path / "elsewhere.py"


def test_a_file_path_s_dialog_opens_in_its_base_folder_and_shows_its_files_relative(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    study = tmp_path / "study"
    view = StudyFileMainView()
    view.render(RendererType.QT)
    view.study.base_folder = study
    field = _field_widget(view.study)
    assert isinstance(field, QFilePathField)
    qtbot.addWidget(field)
    picked: list[Path] = []
    view.study.path_picked.connect(picked.append)
    asked: list[str] = []
    answers = [str(study / "inputs" / "model.py"), str(tmp_path / "elsewhere.py")]

    def ask(*args: object) -> tuple[str, str]:
        asked.append(str(args[2]))
        return answers.pop(0), ""

    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(ask))

    qtbot.mouseClick(field.browse_button, Qt.MouseButton.LeftButton)
    assert field.line_edit.text() == str(Path("inputs", "model.py"))
    assert view.study.path == study / "inputs" / "model.py"
    # again: in the folder of the file picked, one outside the base folder shown whole
    qtbot.mouseClick(field.browse_button, Qt.MouseButton.LeftButton)

    assert asked == [str(study), str(study / "inputs")]
    assert field.line_edit.text() == str(tmp_path / "elsewhere.py")
    assert picked == [study / "inputs" / "model.py", tmp_path / "elsewhere.py"]


def test_a_folder_path_is_picked_in_qt_s_folder_dialog_from_its_folder_else_its_root(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    view = StudyFileMainView()
    view.results.server_roots = (tmp_path / "studies",)
    view.render(RendererType.QT)
    field = _field_widget(view.results)
    assert isinstance(field, QFilePathField)
    qtbot.addWidget(field)
    picked: list[Path] = []
    view.results.path_picked.connect(picked.append)
    asked: list[tuple[str, str]] = []
    answer = str(tmp_path / "results")

    def ask(*args: object) -> str:
        asked.append((str(args[1]), str(args[2])))
        return answer

    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(ask))
    assert not field.reload_button.isVisibleTo(field)  # a folder has nothing to reload

    qtbot.mouseClick(field.browse_button, Qt.MouseButton.LeftButton)
    assert asked == [("Choose a folder", str(tmp_path / "studies"))]
    assert (view.results.path, picked) == (tmp_path / "results", [tmp_path / "results"])
    # again: in the folder picked, and cancelled
    answer = ""
    qtbot.mouseClick(field.browse_button, Qt.MouseButton.LeftButton)
    assert asked[-1] == ("Choose a folder", str(tmp_path / "results"))
    assert len(picked) == 1


def test_a_save_path_is_picked_in_qt_s_save_dialog_its_extension_added(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / "report.pdf").write_text("")
    view = StudyFileMainView()
    report = view.report
    report.extensions = {"PDF": (".pdf",)}
    report.server_roots = (tmp_path,)
    view.render(RendererType.QT)
    field = _field_widget(report)
    assert isinstance(field, QFilePathField)
    qtbot.addWidget(field)
    picked: list[Path] = []
    report.path_picked.connect(picked.append)
    asked: list[tuple[str, str, object]] = []
    questions: list[str] = []
    saved = [""]  # what the save dialog answers
    replaced = [QMessageBox.StandardButton.No]  # what the question answers

    def ask(*args: object, options: object) -> tuple[str, str]:
        asked.append((str(args[2]), str(args[3]), options))
        return saved[0], ""

    def question(*args: object) -> QMessageBox.StandardButton:
        questions.append(str(args[2]))
        return replaced[0]

    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(ask))
    monkeypatch.setattr(QMessageBox, "question", staticmethod(question))

    qtbot.mouseClick(field.browse_button, Qt.MouseButton.LeftButton)  # cancelled
    assert asked == [(str(tmp_path), "PDF (*.pdf)", QFileDialog.Option(0))]
    saved[0] = str(tmp_path / "summary")
    qtbot.mouseClick(field.browse_button, Qt.MouseButton.LeftButton)
    assert (report.path, picked) == (tmp_path / "summary.pdf", [tmp_path / "summary.pdf"])
    assert not report.is_replace_agreed  # a new file: nothing to replace
    # Qt asked about "report": the extension names a file it didn't ask about
    saved[0] = str(tmp_path / "report")
    qtbot.mouseClick(field.browse_button, Qt.MouseButton.LeftButton)
    assert asked[-1][0] == str(tmp_path / "summary.pdf")  # on the field's path
    assert questions == ["report.pdf already exists. Replace it?"]
    assert len(picked) == 1  # kept
    replaced[0] = QMessageBox.StandardButton.Yes
    qtbot.mouseClick(field.browse_button, Qt.MouseButton.LeftButton)
    assert picked[-1] == tmp_path / "report.pdf"
    assert report.is_replace_agreed  # remembered: saving won't ask again
    # without the question: Qt's own is off too, and nothing was agreed
    report.confirms_overwrite = False
    qtbot.mouseClick(field.browse_button, Qt.MouseButton.LeftButton)
    assert asked[-1][2] == QFileDialog.Option.DontConfirmOverwrite
    assert len(questions) == 2
    assert not report.is_replace_agreed
