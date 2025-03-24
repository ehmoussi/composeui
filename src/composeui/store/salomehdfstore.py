from composeui.history.abstracthistory import AbstractHistory
from composeui.store.abstractstore import AbstractStore

from pathlib import Path
from typing import Optional


class SalomeHDFStore(AbstractStore):
    def __init__(self) -> None:
        self._is_debug = False
        self.is_opening_study = False

    def get_extension(self) -> str:
        return ".hdf"

    def get_history(self) -> Optional[AbstractHistory]:
        return None

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
