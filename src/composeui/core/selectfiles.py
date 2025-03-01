r"""Presenter of the File view."""

from composeui.core.views.selectpathview import FileMode, SelectPathView
from composeui.items.core.views.itemsview import FormatExtension
from composeui.mainview.views.mainview import MainView

from pathlib import Path
from typing import Optional, Tuple


def select_file(
    main_view: MainView,
    extensions: str,
    mode: FileMode = "open_file",
) -> Optional[Path]:
    r"""Select a file."""
    main_view.file_view.filter_path = extensions
    filepath_str = ""
    if mode == "open_file":
        filepath_str = main_view.file_view.open_file()
    elif mode == "save_file":
        filepath_str = main_view.file_view.save_file()
    elif mode == "existing_directory":
        filepath_str = main_view.file_view.existing_directory()
    if filepath_str != "":
        filepath = Path(filepath_str)
        if mode == "save_file" or filepath.exists():
            return filepath
    return None


def select_path(*, view: SelectPathView, main_view: MainView) -> Optional[Path]:
    r"""Select a path file."""
    filepath = select_file(main_view, view.filter_path, view.mode)
    if filepath is not None:
        view.path = str(filepath)
        return filepath
    return None


def select_study_file(main_view: MainView) -> Optional[Path]:
    r"""Select a file with the extension of the study of the view."""
    extension_study = main_view.extension_study
    if extension_study == "":
        raise ValueError("The extension of the study is not defined.")
    return select_file(main_view, f"Study Files (*.{extension_study})")


def select_excel_file(main_view: MainView) -> Optional[Path]:
    r"""Select an excel file."""
    return select_file(main_view, "Excel Files (*.xl*)")


def select_csv_file(main_view: MainView) -> Optional[Path]:
    r"""Select a csv file."""
    return select_file(main_view, "csv Files (*.csv)")


def select_table_file(
    main_view: MainView, table_extensions: FormatExtension
) -> Tuple[Optional[Path], Optional[FormatExtension]]:
    r"""Select a file compatible to import a table."""
    filepath = select_file(main_view, _to_fileview_extension_format(table_extensions))
    if filepath is None:
        return None, None
    else:
        return filepath, _get_extension_from_filepath(filepath)


def save_file(main_view: MainView, extensions: str) -> Optional[Path]:
    r"""Save a file."""
    return select_file(main_view, extensions, mode="save_file")


def save_csv_file(main_view: MainView) -> Optional[Path]:
    r"""Save a csv file."""
    return save_file(main_view, "csv Files (*.csv)")


def save_table_file(
    main_view: MainView, table_extensions: FormatExtension
) -> Tuple[Optional[Path], Optional[FormatExtension]]:
    r"""Select a file compatible to export a table."""
    filepath = save_file(main_view, _to_fileview_extension_format(table_extensions))
    if filepath is None:
        return None, None
    else:
        return filepath, _get_extension_from_filepath(filepath)


def save_study_file(main_view: MainView) -> Optional[Path]:
    r"""Save a study file."""
    extension_study = main_view.extension_study
    if extension_study == "":
        raise ValueError("The extension of the study is not defined.")
    return save_file(main_view, f"Study Files (*.{extension_study})")


def _get_extension_from_filepath(filepath: Path) -> FormatExtension:
    """Get the extension of the given filepath or raise an error."""
    if filepath.suffix == ".csv":
        return FormatExtension.CSV
    elif filepath.suffix[:3] == ".xl":
        return FormatExtension.EXCEL
    elif filepath.suffix == ".json":
        return FormatExtension.JSON
    elif filepath.suffix == ".md":
        return FormatExtension.MARKDOWN
    elif filepath.suffix == ".html":
        return FormatExtension.HTML
    else:
        msg = f"Unknow Extension '{filepath.suffix}'"
        raise ValueError(msg)


def _to_fileview_extension_format(table_extensions: FormatExtension) -> str:
    """Transform the given format extension to the format of IFileView."""
    extensions = []
    for extension_type, extension_text in (
        (FormatExtension.CSV, "csv Files (*.csv)"),
        (FormatExtension.EXCEL, "Excel Files (*.xlsx *.xl*)"),
        (FormatExtension.JSON, "Json Files (*.json)"),
        (FormatExtension.MARKDOWN, "Markdown (*.md)"),
        (FormatExtension.HTML, "HTML (*.html)"),
    ):
        if extension_type in table_extensions:
            extensions.append(extension_text)
    return ";;".join(extensions)
