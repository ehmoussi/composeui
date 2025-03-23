from composeui.store.abstractstore import AbstractStore

from pathlib import Path


class SalomeHDFStore(AbstractStore):
    def __init__(self) -> None:
        self._is_debug = False
        self.is_opening_study = False

    def get_extension(self) -> str:
        return ".hdf"

    def set_debug_mode(self, is_debug: bool) -> None:
        self._is_debug = is_debug

    def clear_study(self) -> None:
        pass

    def new_study(self) -> None:
        pass

    def save_study(self, filepath: Path) -> None:
        import salome

        # no multi file, no ascii
        is_ok = salome.myStudy.SaveAs(str(filepath), False, False)
        if not is_ok:
            raise ValueError("The saving of the salome study unexpectedly failed")

    def open_study(self, filepath: Path) -> None:
        import salome

        self.is_opening_study = True
        salome.myStudy.Open(str(filepath))

    def undo(self) -> None:
        """Undo the last modification on the store."""

    def redo(self) -> None:
        """Redo the last undo modification on the store."""

    def activate_history(self) -> None:
        """Activate the history."""
        raise NotImplementedError

    def deactivate_history(self) -> None:
        """Deactivate the history."""
        raise NotImplementedError
