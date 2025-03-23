from composeui.store.abstractstore import AbstractStore, DataReadError

import atexit
import contextlib
import shutil
import tarfile
import tempfile
from pathlib import Path
from typing import Generator, List, Optional


class BaseModel:
    def __init__(
        self, app_name: str, version: str, *stores: AbstractStore, is_debug: bool = False
    ) -> None:
        self.app_name = app_name
        self.version = version
        self._is_debug = is_debug
        self.stores = stores
        self.filepath: Optional[Path] = None
        self.other_files_dir: Path = self.create_other_files_directory()
        atexit.register(self.clear_other_files_directory)

    @property
    def is_debug(self) -> bool:
        return self._is_debug

    @is_debug.setter
    def is_debug(self, is_debug: bool) -> None:
        for store in self.stores:
            store.set_debug_mode(is_debug)
        self._is_debug = is_debug

    def clear(self) -> None:
        """Clear all the data."""
        self.filepath = None
        self.clear_other_files_directory()
        self.other_files_dir = self.create_other_files_directory()
        self.clear_stores()

    def new(self) -> None:
        """Create a new study."""
        self.clear()
        for store in self.stores:
            store.new_study()

    def open_file(self, filepath: Path) -> None:
        r"""Open a study and the other files in the directory."""
        with tempfile.TemporaryDirectory(
            prefix=f"{self.app_name}_open_"
        ) as tmp_dir, tarfile.open(filepath, "r:bz2") as tar:
            # extract the files of the study
            try:
                tar.extractall(tmp_dir)
            except tarfile.ReadError as e:
                if self.is_debug:
                    raise
                raise DataReadError(filepath) from e
            # read the study in the specific format for each store
            ignore_patterns: List[str] = []
            for index, store in enumerate(self.stores):
                store_filename = self.get_store_filename(index)
                store_filepath = Path(tmp_dir, store_filename)
                if not store_filepath.exists():
                    msg = (
                        f"Missing a file for the store at the index '{index}' "
                        f"inside {filepath}"
                    )
                    raise ValueError(msg)
                store.open_study(store_filepath)
                ignore_patterns.append(store_filename)
            # copy the other files in a new 'other files directory'
            new_other_files_dir = self.create_other_files_directory()
            # remove the directory to avoid the raise of an exception by copytree
            # can be removed and replaced by dirs_exist_ok if python < 3.8 is not supported
            new_other_files_dir.rmdir()
            shutil.copytree(
                Path(tmp_dir),
                new_other_files_dir,
                ignore=shutil.ignore_patterns(*ignore_patterns),
                # dirs_exist_ok=True,
            )
            # clean the current 'other files directory'
            self.clear_other_files_directory()
            # substitute the current 'other files with directory' with the new one
            self.other_files_dir = new_other_files_dir
            # update the filepath
            self.filepath = filepath

    def save(self, filepath: Path) -> None:
        r"""Save the stores and other files to the given filepath."""
        try:
            filepath = Path(filepath)
            with tarfile.open(filepath, "w:bz2") as tar, tempfile.TemporaryDirectory(
                prefix=f"{self.app_name}_save_"
            ) as tmp_dir:
                # save the stores
                for index, store in enumerate(self.stores):
                    store_filepath = Path(tmp_dir, self.get_store_filename(index))
                    store.save_study(store_filepath)
                    tar.add(store_filepath, arcname=store_filepath.name, recursive=False)
                # save other files
                for other_filepath in self.other_files_dir.iterdir():
                    tar.add(
                        other_filepath,
                        arcname=other_filepath.name,
                        recursive=other_filepath.is_dir(),
                    )
                # update the filepath
                self.filepath = filepath
        except Exception as e:
            if self._is_debug:
                raise
            raise ValueError("Something went wrong during the save.") from e

    def undo(self) -> None:
        for store in self.stores:
            history = store.get_history()
            if history is not None:
                history.undo()

    def redo(self) -> None:
        for store in self.stores:
            history = store.get_history()
            if history is not None:
                history.redo()

    @contextlib.contextmanager
    def record_history(self) -> Generator[None, None, None]:
        self.start_recording_history()
        try:
            yield
        finally:
            self.stop_recording_history()

    def start_recording_history(self) -> None:
        """Start recording the history."""
        for store in self.stores:
            history = store.get_history()
            if history is not None:
                history.start_recording()

    def stop_recording_history(self) -> None:
        """Stop recording the history."""
        for store in self.stores:
            history = store.get_history()
            if history is not None:
                history.stop_recording()

    def clear_stores(self) -> None:
        """Clear all the stores."""
        for store in self.stores:
            store.clear_study()

    def get_store_filename(self, index: int) -> str:
        return f"store_{index}{self.stores[index].get_extension()}"

    def create_other_files_directory(self) -> Path:
        """Create a directory for the other files of the study."""
        return Path(tempfile.mkdtemp(prefix=f"{self.app_name}_"))

    def clear_other_files_directory(self) -> None:
        """Clear the other files directory."""
        shutil.rmtree(self.other_files_dir, ignore_errors=self.is_debug)
